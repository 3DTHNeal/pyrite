"""Public job listings. No logins, and no scraping of sites that forbid it.

Greenhouse, Lever and Ashby publish these feeds. Workday has no published API, so
its reader calls the same JSON endpoint its public careers pages use.

Written for a slow connection: everything is compressed, and where a board offers a
light listing, full descriptions are fetched only for postings that pass the filters.
"""
import gzip
import html
import http.client
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, cast

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) job-search-pyrite/1.0"
TIMEOUT = 60  # Per socket read, so slow but steady downloads still finish.
_DOLLARS = r"(?<![A-Za-z])(?:US|CA|C|AU|A|NZ|S|MX|HK|R)?\$\s?"
_FIGURE = r"\d{2,3}(?:,\d{3})?(?:\.\d+)?\s?[kK]?"
# What a range says after it, kept so pay.parse can read it: the currency, then the period it's paid by.
_PAID = (r"(?:\s*(?:USD|CAD|AUD|NZD|SGD|MXN|HKD|BRL)\b)?"
         r"(?i:\s*(?:/\s*(?:yr|year|hr|hour|mo|month|wk|week|day)\b|(?:per|an|a)\s+(?:year|annum|hour|month|week|day)\b"
         r"|annually|hourly|monthly|weekly|daily))?")
COMP = re.compile(
    rf"(?i:between)\s+{_DOLLARS}{_FIGURE}\s+and\s+(?:{_DOLLARS})?{_FIGURE}{_PAID}"
    rf"|{_DOLLARS}{_FIGURE}\s*(?:-|–|—|to)\s*(?:{_DOLLARS})?{_FIGURE}{_PAID}"
)
# A range for something other than base pay, named just before it on its line or just after it.
_NOT_BASE = re.compile(r"\b(?:sign[\s-]*on|signing|bonus|relocation|stipend|commission|allowance)", re.I)
_BASE = re.compile(r"\b(?:base|salary|pay|compensation|wage)\b", re.I)
# The words a pay band's label and a title share when they mean the same level.
LEVEL_WORDS = {"intern", "junior", "associate", "mid", "senior", "staff", "principal", "lead", "distinguished", "fellow",
               "manager", "director", "head", "vp", "ii", "iii", "iv"}
LEVEL_ALIASES = {"sr": "senior", "jr": "junior", "snr": "senior"}
BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section"}
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
# Inline styles that hide text from a reader but not from a model. Whitespace and CSS comments are removed first, so
# "display:\tnone" and "display:/**/none" count. Text too small or faint to read, and text the color of its own
# background, are judged in _unreadable, since those take numbers and colors rather than one fixed spelling.
HIDING_STYLE = re.compile(
    r"display:none|visibility:(?:hidden|collapse)|(?:^|;)color:transparent"
    r"|(?:height|width|max-height|max-width):0(?:px)?(?![.\d]).*overflow:hidden|overflow:hidden.*(?:height|width):0(?:px)?(?![.\d])"
    r"|clip(?:-path)?:(?:rect\(0|inset\(50%)|text-indent:-\d{3,}|(?:left|top):-\d{4,}"
    r"|transform:[^;]*scale(?:x|y|3d)?\((?:0|0?\.0+)[,)]"
)
# Below these no one reads the text, though a model still does. font-size:0.9em and opacity:0.5 stay visible.
TINY_FONT = {"px": 2, "pt": 1.5, "em": 0.15, "rem": 0.15, "%": 15}
FAINT_OPACITY = 0.05
# Colors written by name that a hiding trick uses most, as the hex they stand for.
NAMED_COLORS = {"white": "#ffffff", "black": "#000000"}


def strip_invisible(text: str) -> str:
    """Remove format characters: zero-width spaces and joiners, direction overrides, and the Unicode tag block that
    can spell out a whole instruction no reader sees."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def plain_text(text: str) -> str:
    """A board's own plain-text field, held to the same rule as text taken from its HTML."""
    return strip_invisible(text or "").strip()


@dataclass
class Posting:
    source_key: str
    source_id: str
    company: str
    title: str
    location: str = ""
    workplace: str = ""
    url: str = ""
    description: str = ""
    comp: str = ""
    posted_at: str | None = None


class _Text(HTMLParser):
    """Visible text only, so text hidden in a posting's markup never reaches Claude."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_stack = []

    @staticmethod
    def _is_hidden(tag, attrs):
        if tag in ("script", "style", "noscript", "template", "head"):
            return True
        attr = dict(attrs)
        if "hidden" in attr or attr.get("aria-hidden") == "true":
            return True
        # An old <font color="white"> is white on a posting's white page.
        if tag == "font" and _color(attr.get("color") or "") == NAMED_COLORS["white"]:
            return True
        style = re.sub(r"/\*.*?\*/|\s+", "", attr.get("style") or "", flags=re.S).lower()
        return HIDING_STYLE.search(style) is not None or _unreadable(style)

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag == "br" and not self.hidden_stack:
                self.parts.append("\n")
            return
        if self.hidden_stack or self._is_hidden(tag, attrs):
            self.hidden_stack.append(tag)
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if self.hidden_stack:
            if tag in self.hidden_stack:
                while self.hidden_stack.pop() != tag:
                    pass
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden_stack:
            self.parts.append(data)


def _color(value: str) -> str:
    """A CSS color as lowercase six-digit hex, or the value as written if it's some other form."""
    value = value.strip().lower().removesuffix("!important")
    value = NAMED_COLORS.get(value, value)
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return "#" + "".join(ch * 2 for ch in value[1:])
    rgb = re.fullmatch(r"rgba?\((\d+),(\d+),(\d+)(?:,[\d.]+)?\)", value.replace(" ", ""))
    if rgb:
        return "#" + "".join(f"{min(int(part), 255):02x}" for part in rgb.groups())
    return value


def _number(value: str) -> tuple[float, str] | None:
    """A CSS number and its unit, such as (0.01, "px") from "0.01px" or (0.0, "") from ".0"."""
    found = re.fullmatch(r"(\d*\.?\d+)([a-z%]*)", value.removesuffix("!important"))
    return (float(found[1]), found[2]) if found else None


def _unreadable(style: str) -> bool:
    """Whether an inline style, with its spaces taken out, leaves its text too small or faint to read, or the color of
    its own background."""
    rules = dict(part.split(":", 1) for part in style.split(";") if ":" in part)
    size = _number(rules.get("font-size", ""))
    if size and (size[0] == 0 or size[0] < TINY_FONT.get(size[1], 0)):
        return True
    opacity = _number(rules.get("opacity", ""))
    if opacity and opacity[0] / (100 if opacity[1] == "%" else 1) <= FAINT_OPACITY:
        return True
    color = _color(rules.get("color", ""))
    background = _color(rules.get("background-color") or rules.get("background") or "")
    return bool(color) and color == background


def html_to_text(markup: str, escaped: bool = False) -> str:
    """The visible text of a posting's HTML. `escaped` is for a board that sends its HTML escaped, as Greenhouse does:
    only then is it unescaped first. Unescaping real HTML would turn text such as "&lt;/div&gt;" into tags, and let
    text hidden inside an element out of it."""
    if not markup:
        return ""
    parser = _Text()
    parser.feed(html.unescape(markup) if escaped else markup)
    parser.close()
    text = strip_invisible("".join(parser.parts))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _level_words(text: str) -> set[str]:
    words = {LEVEL_ALIASES.get(word, word) for word in re.findall(r"[a-z]+", text.lower())}
    return words & LEVEL_WORDS


def find_comp(text: str, title: str = "") -> str:
    """The pay range in a posting's text. Where it lists a band per level ("Senior: $141,380 - $194,390", then
    "Staff: $163,270 - $224,500"), the band whose label names the title's level, else the first range."""
    text = text or ""
    found = list(COMP.finditer(text))
    labels = []
    for i, match in enumerate(found):
        # A band's label is what comes before it on its line, back to the band before it.
        start = max(text.rfind("\n", 0, match.start()) + 1, found[i - 1].end() if i else 0)
        labels.append(text[start:match.start()])
    def other_pay(match, label: str) -> bool:
        """A sign-on bonus or a stipend, named right after the range or in its own clause before it."""
        clause = re.split(r"[,;.]\s", label)[-1]
        return bool(_NOT_BASE.match(text[match.end():match.end() + 20].lstrip(" :-–—("))
                    or (_NOT_BASE.search(clause) and not _BASE.search(clause)))

    kept = [(match, label) for match, label in zip(found, labels, strict=True) if not other_pay(match, label)]
    if not kept:
        return ""
    wanted = _level_words(title)
    fits = [(len(_level_words(label) & wanted), -len(_level_words(label) - wanted)) for _, label in kept]
    # max keeps the first of equals. With no label naming the title's level, the first range, as it always was.
    best = max(range(len(kept)), key=fits.__getitem__)
    words = re.sub(r"\s+", " ", kept[best if fits[best][0] else 0][0].group(0)).strip()
    # "between $132,000 and $198,000" is written as the range it is.
    return re.sub(r"^between\s+(.*?)\s+and\s+", r"\1 - ", words, flags=re.I)


def _request(url: str, payload: dict[str, Any] | None = None, retries: int = 3) -> dict[str, Any] | list[Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"}
    if data:
        headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=TIMEOUT) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as err:
            if err.code not in (429, 500, 502, 503, 504) or attempt == retries:
                raise
            err.close()  # It holds the response open, and the retry won't read it.
        except (OSError, http.client.HTTPException):
            # A refused, reset or half-finished connection, not only a failed lookup.
            if attempt == retries:
                raise
        time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def fetch_greenhouse(board: str, company: str) -> list[Posting]:
    """The light listing. Descriptions come from greenhouse_detail, for candidates only."""
    key = f"greenhouse:{board}"
    data = cast(dict[str, Any], _request(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"))
    return [
        Posting(key, str(job["id"]), company, job["title"].strip(), (job.get("location") or {}).get("name", ""), "",
                job.get("absolute_url", ""), "", "", job.get("first_published") or job.get("updated_at"))
        for job in data.get("jobs", [])
    ]


def greenhouse_detail(board: str, company: str, job_id: str) -> Posting:
    job = cast(dict[str, Any], _request(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}", retries=1))
    # Greenhouse sends the description's HTML escaped, as "&lt;p&gt;".
    description = html_to_text(job.get("content", ""), escaped=True)
    return Posting(
        f"greenhouse:{board}", str(job["id"]), company, job["title"].strip(),
        (job.get("location") or {}).get("name", ""), "", job.get("absolute_url", ""),
        description, find_comp(description, job["title"]), job.get("first_published") or job.get("updated_at"),
    )


def _lever_pay(salary: dict[str, Any]) -> str:
    """Lever's salaryRange as text pay.parse reads, keeping its currency and how often it's paid, as
    {"currency": "CAD", "interval": "per-hour-wage", "min": 40, "max": 50}."""
    if not (salary.get("min") and salary.get("max")):
        return ""
    interval = str(salary.get("interval") or "").lower()
    per = next((word for word in ("hour", "day", "week", "month") if word in interval), "year")
    currency = str(salary.get("currency") or "USD").upper()
    return f"${salary['min']:,} - ${salary['max']:,} {currency} per {per}"


def fetch_lever(board: str, company: str) -> list[Posting]:
    key = f"lever:{board}"
    data = cast(list[dict[str, Any]], _request(f"https://api.lever.co/v0/postings/{board}?mode=json"))
    postings = []
    for job in data:
        categories = job.get("categories") or {}
        places = categories.get("allLocations") or [categories.get("location", "")]
        sections = "\n".join(
            f"{section.get('text', '')}\n{html_to_text(section.get('content', ''))}"
            for section in job.get("lists", [])
        )
        description = "\n".join(filter(None, [
            # The HTML first: only there can text hidden with CSS be told apart and dropped.
            html_to_text(job.get("description", "")) or plain_text(job.get("descriptionPlain", "")),
            sections,
            html_to_text(job.get("additional", "")) or plain_text(job.get("additionalPlain", "")),
        ]))
        comp = _lever_pay(job.get("salaryRange") or {})
        created = job.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, UTC).isoformat() if created else None
        postings.append(Posting(
            key, job["id"], company, job["text"].strip(), " | ".join(filter(None, places)),
            job.get("workplaceType", "") or "", job.get("hostedUrl", ""), description,
            comp or find_comp(description, job["text"]), posted,
        ))
    return postings


def fetch_ashby(board: str, company: str) -> list[Posting]:
    key = f"ashby:{board}"
    data = cast(dict[str, Any], _request(f"https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true"))
    postings = []
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        places = [job.get("location", "")] + [
            place.get("location", "") for place in job.get("secondaryLocations") or []
        ]
        address = ((job.get("address") or {}).get("postalAddress") or {}).get("addressCountry", "")
        location = " | ".join(filter(None, places))
        if address and address not in location:
            location = f"{location} ({address})"
        # isRemote is also true on hybrid roles, so workplaceType decides when it's present.
        workplace = job.get("workplaceType") or ("remote" if job.get("isRemote") else "")
        description = html_to_text(job.get("descriptionHtml", "")) or plain_text(job.get("descriptionPlain", ""))
        comp = (job.get("compensation") or {}).get("compensationTierSummary") or find_comp(description, job["title"])
        postings.append(Posting(
            key, job.get("id") or job["jobUrl"], company, job["title"].strip(), location, workplace.lower(),
            job.get("jobUrl", ""), description, comp, job.get("publishedAt"),
        ))
    return postings


def workday_base(spec: dict[str, Any]) -> tuple[str, str]:
    host = f"{spec['tenant']}.{spec['wd']}.myworkdayjobs.com"
    return (
        f"https://{host}/wday/cxs/{spec['tenant']}/{spec['site']}",
        f"https://{host}/en-US/{spec['site']}",
    )


def workday_detail(spec: dict[str, Any], company: str, path: str) -> Posting:
    api, site = workday_base(spec)
    info = cast(dict[str, Any], _request(f"{api}{path}", retries=1))["jobPostingInfo"]
    places = [info.get("location", "")] + (info.get("additionalLocations") or [])
    description = html_to_text(info.get("jobDescription", ""))
    return Posting(
        f"workday:{spec['tenant']}", path, company, info.get("title", "").strip(),
        " | ".join(filter(None, places)), (info.get("remoteType") or "").lower(),
        info.get("externalUrl") or f"{site}{path}", description, find_comp(description, info.get("title", "")),
        info.get("startDate"),
    )


def workday_search(spec: dict[str, Any], queries: list[str], max_pages: int) -> dict[str, dict[str, Any]]:
    """Search one Workday site. Returns {external path: summary}."""
    api, _ = workday_base(spec)
    found: dict[str, dict[str, Any]] = {}
    for query in queries:
        for page in range(max_pages):
            data = cast(dict[str, Any], _request(f"{api}/jobs", {
                "limit": 20, "offset": page * 20, "searchText": query, "appliedFacets": {},
            }))
            jobs = data.get("jobPostings", [])
            for job in jobs:
                if job.get("externalPath"):
                    found[job["externalPath"]] = job
            if len(jobs) < 20:
                break
    return found


def workday_posted_date(text: str | None, today: date) -> str | None:
    """Workday lists say "Posted 3 Days Ago". "Posted 30+ Days Ago" isn't a date, so that gives nothing."""
    text = (text or "").lower()
    if "+" in text:
        return None
    if "today" in text:
        days = 0
    elif "yesterday" in text:
        days = 1
    else:
        match = re.search(r"(\d+)\s+day", text)
        if not match:
            return None
        days = int(match.group(1))
    return (today - timedelta(days=days)).isoformat()


def is_workday_closed(spec: dict[str, Any], path: str) -> bool | None:
    """True if a posting is gone, False if live, None if we couldn't tell."""
    api, _ = workday_base(spec)
    try:
        info = _request(f"{api}{path}", retries=1)
    except urllib.error.HTTPError as err:
        with err:
            return True if err.code in (404, 410) else None
    except (OSError, http.client.HTTPException, ValueError):
        return None
    return "jobPostingInfo" not in info


FEEDS = {"greenhouse": fetch_greenhouse, "lever": fetch_lever, "ashby": fetch_ashby}
