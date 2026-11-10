"""Read one posting from its web address, for a posting you add yourself.

Most careers pages carry the posting twice: once for people, and once as schema.org JobPosting data for search engines.
The data is read first, since it names the company, title and place outright. A page without it gives its heading and
its visible text, less the menus around it. Nothing here signs in anywhere, and a page that builds itself in the browser
or sits behind a sign-in is reported as unreadable rather than guessed at.

The address comes from whoever is using the dashboard, so only public web addresses are fetched: a link to this
computer or the network it's on is refused, on the first request and on every redirect.
"""
import gzip
import http.client
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from .sources import USER_AGENT, Posting, _Text, find_comp, html_to_text, strip_invisible, workday_detail

TIMEOUT = 20  # Seconds per connection and per read. Someone is waiting on the dialog.
MAX_BYTES = 3_000_000  # A posting page is tens of kilobytes. Past this it's something else.
MAX_DESCRIPTION = 60_000  # Characters kept. Longer text is the page's furniture, not the posting.
MIN_PAGE_TEXT = 400  # Visible text shorter than this is a shell the browser fills in, not a posting.
MAX_FIELD = 200  # The dashboard's limit on a company, title or location.
PASTE = "Paste the description in yourself."
# Parts of a page that are never the posting.
FURNITURE = {"nav", "header", "footer", "aside", "form", "button", "select", "svg", "dialog", "iframe"}
JSON_LD = re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']?application/ld\+json[\"']?[^>]*>(.*?)</script>", re.S | re.I)
# A Workday posting's address: the tenant, its data center, the site, and the posting's path under it.
WORKDAY = re.compile(r"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)(/job/[^?#]+)")
PER = {"YEAR": "per year", "HOUR": "per hour", "MONTH": "per month", "WEEK": "per week", "DAY": "per day"}


class Unreadable(ValueError):
    """Why a link gave no posting, in words the dashboard can show."""


def _check_public(url: str) -> None:
    """Refuse an address that isn't a web page on the public internet."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Unreadable("That isn't a web address. A link starts with https://.")
    try:
        found = socket.getaddrinfo(parts.hostname, None)
    except OSError:
        raise Unreadable(f"Couldn't find the site {parts.hostname}. Check the link, or your connection.") from None
    for info in found:
        if not ipaddress.ip_address(str(info[4][0]).split("%")[0]).is_global:
            raise Unreadable("That link points at this computer or a private network, so Pyrite won't read it.")


class _PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_page(url: str) -> str:
    """The HTML at a public web address."""
    _check_public(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "gzip",
    })
    try:
        with urllib.request.build_opener(_PublicRedirects).open(request, timeout=TIMEOUT) as resp:
            kind = resp.headers.get_content_type()
            if kind not in ("text/html", "application/xhtml+xml"):
                raise Unreadable(f"That link is a file ({kind}), not a web page. {PASTE}")
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise Unreadable(f"That page is too large to be one posting. {PASTE}")
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            charset = resp.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as err:
        err.close()
        if err.code in (401, 403):
            raise Unreadable(f"The site refused to show that page ({err.code}). It may need a sign-in. {PASTE}") from None
        if err.code in (404, 410):
            raise Unreadable(f"The site has no page at that link ({err.code}). The posting may be closed.") from None
        raise Unreadable(f"The site answered with an error ({err.code}). Try again, or paste the description in.") from None
    except (OSError, http.client.HTTPException, EOFError):
        raise Unreadable(f"Couldn't reach {urlparse(url).hostname}. Check your connection, or paste the description in.") from None
    try:
        return body.decode(charset, "replace")
    except LookupError:  # A character set Python hasn't heard of.
        return body.decode("utf-8", "replace")


def _line(value: object) -> str:
    """One field as a single trimmed line, or nothing if it isn't text."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", strip_invisible(value)).strip()[:MAX_FIELD]


def _name(value: object) -> str:
    """A schema.org thing's name, whether it came as text or as an object."""
    return _line(value.get("name")) if isinstance(value, dict) else _line(value)


def _job_postings(markup: str) -> list[dict[str, Any]]:
    """Every JobPosting in a page's structured data, wherever it's nested."""
    found: list[dict[str, Any]] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kinds = node.get("@type")
            if "JobPosting" in (kinds if isinstance(kinds, list) else [kinds]):
                found.append(node)
            walk(node.get("@graph"))

    for block in JSON_LD.findall(markup):
        try:
            # Not strict, because Workday leaves raw line breaks inside its strings.
            walk(json.loads(block, strict=False))
        except ValueError:
            continue
    return found


def _place(place: object) -> str:
    """One jobLocation as "City, State", or the country when that's all it gives."""
    address = place.get("address") if isinstance(place, dict) else place
    if not isinstance(address, dict):
        return _line(address)
    town = ", ".join(filter(None, (_line(address.get("addressLocality")), _line(address.get("addressRegion")))))
    return town or _name(address.get("addressCountry"))


def _location(job: dict[str, Any]) -> str:
    places = job.get("jobLocation")
    named = [_place(place) for place in (places if isinstance(places, list) else [places])]
    unique = list(dict.fromkeys(filter(None, named)))
    if _line(job.get("jobLocationType")).upper() == "TELECOMMUTE" and not any("remote" in place.lower() for place in unique):
        unique.append("Remote")
    return " | ".join(unique)[:MAX_FIELD]


def _pay(job: dict[str, Any]) -> str:
    """baseSalary as a range in dollars, such as "$120,000 - $150,000 per year", or nothing if it isn't one."""
    salary = job.get("baseSalary")
    value = salary.get("value") if isinstance(salary, dict) else None
    if not isinstance(salary, dict) or not isinstance(value, dict) or _line(salary.get("currency")).upper() != "USD":
        return ""
    try:
        low, high = float(value["minValue"]), float(value["maxValue"])
    except (KeyError, TypeError, ValueError):
        return ""
    if not 0 < low <= high:
        return ""
    per = PER.get(_line(value.get("unitText")).upper(), "")
    amount = "{:,.0f}" if low >= 1000 else "{:,.2f}"
    return f"${amount.format(low)} - ${amount.format(high)} {per}".strip()


def _from_data(job: dict[str, Any]) -> dict[str, Any]:
    raw = job.get("description")
    raw = raw if isinstance(raw, str) else ""
    # Some sites escape the description's HTML a second time, so it arrives as "&lt;p&gt;" with no tags at all.
    description = html_to_text(raw, escaped="<" not in raw and "&lt;" in raw)
    pay = _pay(job)
    if pay and not find_comp(description):
        description = f"{description}\n\nPay: {pay}".strip()
    return {"company": _name(job.get("hiringOrganization")), "title": _line(job.get("title")),
            "location": _location(job), "description": description}


class _PageText(_Text):
    """A page's visible text without its menus, forms and footer."""

    @staticmethod
    def _is_hidden(tag, attrs):
        return tag in FURNITURE or _Text._is_hidden(tag, attrs)


class _Head(_Text):
    """The first heading, and what the page says its title is."""

    def __init__(self):
        super().__init__()
        self.h1: list[str] | None = None
        self.title: list[str] | None = None
        self.og_title = ""
        self._into: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "meta":
            attr = dict(attrs)
            if (attr.get("property") or attr.get("name")) == "og:title" and not self.og_title:
                self.og_title = attr.get("content") or ""
        elif tag == "h1" and self.h1 is None and not self._is_hidden(tag, attrs):
            self.h1 = self._into = []
        elif tag == "title" and self.title is None:
            self.title = self._into = []

    def handle_endtag(self, tag):
        if tag in ("h1", "title"):
            self._into = None

    def handle_data(self, data):
        if self._into is not None:
            self._into.append(data)


def _from_page(markup: str) -> dict[str, Any]:
    """The heading and visible text of a page with no posting data. The company and place aren't marked on such a
    page, so they're left for whoever is adding it."""
    head = _Head()
    head.feed(markup)
    head.close()
    title = _line("".join(head.h1 or [])) or _line(head.og_title) or _line("".join(head.title or []))
    page = _PageText()
    page.feed(markup)
    page.close()
    text = re.sub(r"[ \t\xa0]+", " ", strip_invisible("".join(page.parts)))
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r" ?\n ?", "\n", text)).strip()
    # The posting starts at its heading. What comes before is the site.
    start = text.find(title) if title else -1
    if start > 0:
        text = text[start:]
    return {"company": "", "title": title, "location": "", "description": text if len(text) >= MIN_PAGE_TEXT else ""}


def parse(markup: str) -> dict[str, Any]:
    """The company, title, location and description a page gives, each empty if it doesn't say."""
    postings = _job_postings(markup)
    found = _from_data(postings[0]) if postings else {}
    if not found.get("description"):
        page = _from_page(markup)
        found = {key: found.get(key) or page[key] for key in page}
    if not found["description"]:
        raise Unreadable(f"That page shows no posting Pyrite can read. It may need a sign-in, or build itself in the browser. {PASTE}")
    found["description"] = found["description"][:MAX_DESCRIPTION]
    return found


def _from_workday(url: str, detail: Callable[..., Posting]) -> dict[str, Any] | None:
    """A Workday posting from the endpoint its own page calls, which keeps the paragraphs and lists that the page's
    structured data flattens into one line. None if the link isn't Workday's or the endpoint doesn't answer."""
    found = WORKDAY.match(url)
    if not found:
        return None
    try:
        posting = detail({"tenant": found[1], "wd": found[2], "site": found[3]}, "", found[4])
    except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError):
        return None
    if not posting.description:
        return None
    return {"company": "", "title": _line(posting.title), "location": _line(posting.location),
            "description": posting.description[:MAX_DESCRIPTION]}


def read(url: str, fetch: Callable[[str], str] = fetch_page, workday: Callable[..., Posting] = workday_detail) -> dict[str, Any]:
    """The posting at a link, as the fields the Add a posting form asks for."""
    url = url.strip()
    return _from_workday(url, workday) or parse(fetch(url))
