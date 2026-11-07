"""Reply detection and scam warnings through the Gmail connector in Claude Code.

Where IMAP isn't set up, Claude Code can read Gmail through the claude.ai connector. This module
starts Claude for one narrow job: copy the sender, subject, date and a little text of recent mail
into a JSON list, handed back as its closing message. It gets the two Gmail reading tools and
nothing else, not even a file to write, so it can't send, reply, label, delete or change anything
on this machine, whatever an email tells it.

Everything that judges the mail is plain code here: the same reply matching as `inbox`, plus a
set of rules for the shapes job scams take. A warning changes nothing on its own, and the list
is thrown away once judged, so message text never stays on disk or in the database.
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from . import claude_code, inbox
from .claude_code import ClaudeFailed, find_claude, sign_in_help
from .inbox import ATS_DOMAINS, DOMAIN_SHAPE, HIRING_SUBJECT, JOB_BOARDS, Message, registrable
from .store import ROOT, now

SOURCE = "gmail"  # `source = "gmail"` under [inbox] in search.toml picks this over IMAP.
SOURCE_KEY = "inbox:gmail"
KIND = "mail"
INSTRUCTIONS = Path(__file__).parent / "mail_check.md"
GMAIL_TOOLS = ("mcp__claude_ai_Gmail__search_threads", "mcp__claude_ai_Gmail__get_message")
# Replies and recruiter mail land in Primary or Updates. Reading promotions, social and forum mail too would make the run long and dear.
# Job-board mail (alerts and digests) is never counted as a reply and its text is never read, so the search leaves it
# out rather than paying for Claude to page through it: every page of results is sent again on each later turn.
QUERY = "after:{day} -in:sent -from:me {{category:primary category:updates}} " + " ".join(f"-from:{domain}" for domain in JOB_BOARDS)
TIME_LIMIT_MINUTES = 25  # A first read of a week or two of mail is the long one; later runs read back only a couple of days.
# Copying headers into a list needs no judgment, so the cheapest model that handles long JSON reliably does it.
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_ITEMS = 3000
MAX_TEXT = 4000
MAX_LINKS = 50
# A run reads back this far past the last good one, so a late-arriving message is still seen.
OVERLAP_DAYS = 2

FREE_MAIL = (
    "aol.com", "gmail.com", "googlemail.com", "gmx.com", "hotmail.com", "icloud.com", "live.com", "mail.com", "me.com",
    "msn.com", "outlook.com", "proton.me", "protonmail.com", "yahoo.com", "yandex.com", "zoho.com",
)
CHAT_LINKS = ("wa.me", "api.whatsapp.com", "chat.whatsapp.com", "t.me", "telegram.me", "signal.me")
SHORTENERS = ("bit.ly", "cutt.ly", "goo.gl", "is.gd", "rb.gy", "shorturl.at", "t.co", "tiny.cc", "tinyurl.com")
FORMS = ("docs.google.com", "forms.gle", "forms.office.com", "jotform.com", "typeform.com")
CHAT_APPS = re.compile(
    r"\b(whats\s?app|telegram|signal app|google chat|google hangouts|skype|(?:text|chat|sms)[- ]only interview"
    r"|interview (?:via|over|through|by) (?:chat|text|sms|messaging)|chat interview)\b", re.I)
MONEY_OR_ID = re.compile(
    r"\b(gift ?cards?|cashier'?s? check|e-?check|checks? (?:will be |is |are )?(?:mailed|sent|deposited)|deposit (?:the|a|this) check"
    r"|wire transfer|processing fee|training fee|application fee|registration fee|bitcoin|crypto(?:currency)?|zelle|cash ?app|venmo"
    r"|social security|ssn|bank (?:account|details|information)|routing number|driver'?s licen[sc]e|passport|date of birth"
    r"|(?:buy|purchase|order) (?:the |your |some )?(?:equipment|software|materials|supplies)|reimburse\w*)\b", re.I)
TOO_GOOD = re.compile(
    r"\b(no interview|without (?:an |any )?interview|guaranteed|you(?:'ve| have) been (?:selected|chosen|shortlisted)"
    r"|congratulations.{0,40}(?:hired|selected|offer)|we (?:found|came across|reviewed) your (?:resume|cv|profile)"
    r"|\$\s?\d{2,3}(?:\.\d\d)?\s?(?:/|per|an)\s?(?:hr|hour))\b", re.I)
URGENT = re.compile(r"\b(within (?:12|24|48) hours|urgent(?:ly)?|immediately|act now|respond (?:asap|today|now)|time[- ]sensitive)\b", re.I)


@dataclass
class Item(Message):
    """One exported message. `text` is the snippet and, for hiring-related mail, some of the body."""
    message_id: str = ""
    reply_domain: str = ""
    text: str = ""
    links: tuple = ()


def _field(entry: dict, key: str, limit: int) -> str:
    value = entry.get(key)
    return inbox._clean(value, limit) if isinstance(value, str) else ""


def _strings(value) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _date(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _address(value: str) -> str:
    """A bare lower-case address from "Name <addr>" or "addr"."""
    return (parseaddr(value)[1] if "<" in value else value).strip().lower()


def _domain_of(address: str) -> str:
    """The registered domain of an address, or nothing if it doesn't look like one."""
    local, _, domain = _address(address).rpartition("@")
    return registrable(domain) if local and DOMAIN_SHAPE.fullmatch(domain) else ""


def _link_host(link: str) -> str:
    text = link.strip().lower()
    host = urlparse(text if "://" in text else f"//{text}").hostname or ""
    return host if DOMAIN_SHAPE.fullmatch(host) else ""


def _item(entry) -> Item | None:
    if not isinstance(entry, dict):
        return None
    local, _, domain = _address(_field(entry, "from_address", 200)).rpartition("@")
    if not DOMAIN_SHAPE.fullmatch(domain) or not re.fullmatch(r"[a-z0-9._%+=-]+", local):
        return None
    date = _date(entry.get("date"))
    if not date:
        return None
    links = sorted({host for host in map(_link_host, _strings(entry.get("links"))[:MAX_LINKS]) if host})
    text = inbox._clean(f"{_field(entry, 'snippet', 1000)} {_field(entry, 'body', MAX_TEXT)}", MAX_TEXT)
    return Item(
        _field(entry, "from_name", 80), local, domain, _field(entry, "subject", 200), date,
        bulk="CATEGORY_PROMOTIONS" in _strings(entry.get("labels")),  # Only in an export made by hand: the run skips Promotions.
        message_id=_field(entry, "id", 64), reply_domain=_domain_of(_field(entry, "reply_to", 200)),
        text=text, links=tuple(links),
    )


def _find_list(raw: str) -> list:
    """The longest JSON list of objects anywhere in the text, so a code fence or a sentence around it does no harm."""
    decoder = json.JSONDecoder()
    best: list = []
    position = raw.find("[")
    while position != -1:
        try:
            value, _ = decoder.raw_decode(raw, position)
        except ValueError:
            value = None
        if isinstance(value, list) and len(value) > len(best) and any(isinstance(entry, dict) for entry in value):
            best = value
        position = raw.find("[", position + 1)
    if not best and "[]" not in raw:
        raise ValueError("No list of messages in Claude's answer.")
    return best


def parse_export(raw: str) -> list[Item]:
    """The messages Claude handed back, with anything malformed left out. Raises ValueError if there's no list at all."""
    return [item for item in map(_item, _find_list(raw)[:MAX_ITEMS]) if item]


def known_companies(conn, cfg: dict) -> dict[str, set[str]]:
    """Every company Pyrite has seen, with the domains known to be theirs. Scams borrow big names, applied to or not."""
    companies: dict[str, set[str]] = {}
    for job in conn.execute("SELECT company, url, source_key FROM jobs"):
        core = inbox._core_name(job["company"])
        if core:
            companies.setdefault(core, set()).update(inbox.employer_domains(job, cfg))
    for company, domains in cfg.get("inbox", {}).get("domains", {}).items():
        core = inbox._core_name(company)
        if core and isinstance(domains, list):
            companies.setdefault(core, set()).update(registrable(str(d)) for d in domains)
    return companies


def _own_domain(site: str, core: str, domains: set[str]) -> bool:
    label, _, suffix = site.partition(".")
    compact = inbox._compact(core)
    return site in domains or compact in (label, label + suffix)


def assess(item: Item, companies: dict[str, set[str]]) -> list[str]:
    """Why this message looks like a job scam, in plain words. Empty means nothing stood out.

    Only mail about hiring, or mail that names a known company, is looked at. One strong sign is enough
    to warn; weaker ones need company. A sender at the company's own domain or a known applicant tracking
    system gets the benefit of the doubt on wording, since the lookalike and free-mail tricks don't apply.
    """
    text = f"{item.subject} {item.text}"
    named = [core for core in companies if inbox._names_company(item.name, core) or inbox._names_company(item.subject, core)]
    hiring = HIRING_SUBJECT.search(text) is not None
    if not hiring and not named:
        return []
    site = registrable(item.domain)
    trusted = inbox._within(item.domain, ATS_DOMAINS + JOB_BOARDS)
    free = site in FREE_MAIL
    verified = trusted or any(_own_domain(site, core, companies[core]) for core in named)
    strong, weak = [], []

    for core in named:
        if trusted or _own_domain(site, core, companies[core]):
            continue
        label = site.partition(".")[0]
        if inbox._compact(core) in inbox._compact(label):
            strong.append(f"Sent from {site}, which looks like {core} but isn't its domain")
        elif free:
            strong.append(f"Says it's from {core} but was sent from a personal {site} address")
        else:
            weak.append(f"Names {core} but was sent from {site}")
    if item.reply_domain and item.reply_domain != site and not inbox._within(item.reply_domain, ATS_DOMAINS):
        (strong if item.reply_domain in FREE_MAIL else weak).append(f"Replies would go to {item.reply_domain}, not {site}")
    if free and hiring and not named:
        weak.append(f"Hiring mail from a personal {site} address")

    match = CHAT_APPS.search(text)
    if match:
        (weak if verified else strong).append(f"Wants to talk over {match.group(1)}, which real employers don't ask for")
    match = MONEY_OR_ID.search(text)
    if match:
        (weak if verified else strong).append(f"Mentions {match.group(1).lower()}: never pay, deposit a check or share ID for a job")
    if not verified:
        match = TOO_GOOD.search(text)
        if match:
            (strong if free else weak).append(f"Too easy: \"{match.group(1)}\"")
        match = URGENT.search(text)
        if match:
            weak.append(f"Pushes for speed: \"{match.group(1)}\"")
    for host in item.links:
        if inbox._within(host, CHAT_LINKS):
            strong.append(f"Links to {host}, a chat app")
        elif inbox._within(host, SHORTENERS):
            weak.append(f"Links through {host}, which hides where it goes")
        elif inbox._within(host, FORMS) and not verified:
            weak.append(f"Asks for details on a form at {host}")

    return strong + weak if strong or len(weak) >= 2 else []


def _job_named(item: Item, jobs: list) -> int | None:
    """The tracked job whose company the mail names, if any, so the warning shows on its card. A guess, not a match."""
    for job in jobs:
        core = inbox._core_name(job["company"])
        if core and (inbox._names_company(item.name, core) or inbox._names_company(item.subject, core)):
            return job["id"]
    return None


def record_alerts(conn, items: list[Item], jobs: list, companies: dict[str, set[str]]) -> list[dict]:
    """Keep each new warning, with the sender, subject, date and reasons only. Never touches a job."""
    known = {row["message_id"] for row in conn.execute("SELECT message_id FROM mail_alerts")}
    found = []
    for item in items:
        reasons = assess(item, companies)
        key = item.message_id or item.detail()
        if not reasons or key in known:
            continue
        known.add(key)
        job_id = _job_named(item, jobs)
        sender = f"{item.name} <{item.address}>" if item.name else item.address
        conn.execute(
            """INSERT INTO mail_alerts (message_id, ts, job_id, sender, subject, date, reasons)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, now(), job_id, sender, item.subject, item.date.astimezone(timezone.utc).isoformat(timespec="minutes"),
             json.dumps(reasons)),
        )
        found.append({"job_id": job_id, "sender": item.address, "reasons": reasons})
    return found


def open_alerts(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM mail_alerts WHERE dismissed_at IS NULL ORDER BY date DESC, id DESC").fetchall()
    alerts = []
    for row in rows:
        alert = dict(row)
        alert["reasons"] = json.loads(row["reasons"] or "[]")
        alerts.append(alert)
    return alerts


def dismiss_alert(conn, alert_id: int) -> None:
    if conn.execute("UPDATE mail_alerts SET dismissed_at = ? WHERE id = ?", (now(), alert_id)).rowcount != 1:
        raise ValueError("No such warning.")


def command(claude: str, model: str = DEFAULT_MODEL) -> list[str]:
    """Two Gmail reading tools, found through ToolSearch, and nothing that writes. dontAsk refuses everything else.

    A path-scoped Write rule isn't honored on every platform, so Claude gets no Write tool at all and
    hands the list back as its closing message instead. Your user settings can't widen this.
    """
    return [
        claude, "-p", "--output-format", "json", "--no-session-persistence", "--model", model,
        "--setting-sources", "project", "--permission-mode", "dontAsk", "--max-turns", "60",
        "--tools", "ToolSearch",
        "--allowedTools", ",".join(GMAIL_TOOLS),
        "--disallowedTools", "Write,Edit,NotebookEdit,Bash,PowerShell,Read,WebFetch,WebSearch,Agent,Task",
    ]


def window(conn, cfg: dict) -> datetime:
    """How far back to read: the lookback at most, and only a little past the last good run."""
    days = cfg.get("inbox", {}).get("lookback_days", inbox.DEFAULT_LOOKBACK_DAYS)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    row = conn.execute("SELECT last_ok FROM source_status WHERE source_key = ?", (SOURCE_KEY,)).fetchone()
    if row and row["last_ok"]:
        last = datetime.fromisoformat(row["last_ok"])
        since = max(since, (last if last.tzinfo else last.replace(tzinfo=timezone.utc)) - timedelta(days=OVERLAP_DAYS))
    return since


def prompt(companies: dict[str, set[str]], since: datetime) -> str:
    names = ", ".join(sorted(companies)) or "(none yet)"
    day = since.astimezone(timezone.utc).strftime("%Y/%m/%d")
    # Mail from these can be judged from its subject and snippet. Reading its text would cost most of the run.
    known = sorted(set(ATS_DOMAINS + JOB_BOARDS).union(*companies.values()))
    return (
        INSTRUCTIONS.read_text(encoding="utf-8")
        + f"\n\nThe search query: `{QUERY.format(day=day)}`\n"
        f"Companies the person has applied to or watches: {names}\n"
        f"Senders whose text you never read (step 2 doesn't apply): any address at or under {', '.join(known)}\n"
    )


def _fail(conn, message: str) -> dict:
    inbox._record_status(conn, error=message, source_key=SOURCE_KEY, company="Email replies (Gmail)")
    conn.commit()
    return {"state": "error", "message": message[:300]}


def ingest(conn, cfg: dict, items: list[Item]) -> dict:
    """Judge exported messages: possible replies to tracked jobs, and warnings about likely scams."""
    jobs = inbox.tracked_jobs(conn)
    found = inbox.record_matches(conn, jobs, items, cfg)
    alerts = record_alerts(conn, items, jobs, known_companies(conn, cfg))
    inbox._record_status(conn, count=len(items), source_key=SOURCE_KEY, company="Email replies (Gmail)")
    conn.commit()
    return {"state": "ok", "jobs": len(jobs), "messages": len(items), "found": found, "alerts": alerts}


def ingest_file(conn, cfg: dict, path: Path) -> dict:
    """An export made by hand, for instance by a Claude session that read Gmail itself."""
    try:
        items = parse_export(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as err:
        return _fail(conn, f"Couldn't read the export: {err}")
    return ingest(conn, cfg, items)


def run(conn, cfg: dict, claude: str | None = None, ask=claude_code.ask) -> dict:
    """One scan through Claude Code. Never raises for mail trouble: that's reported beside the job boards instead."""
    claude = claude or find_claude()
    if not claude:
        return _fail(conn, "Claude Code wasn't found on this PC, so mail couldn't be checked.")
    if not claude_code.signed_in(claude):
        return _fail(conn, sign_in_help(claude))
    text = prompt(known_companies(conn, cfg), window(conn, cfg))
    model = str(cfg.get("inbox", {}).get("model") or DEFAULT_MODEL)
    try:
        answer = ask(conn, None, KIND, command(claude, model), text, ROOT, TIME_LIMIT_MINUTES * 60, TIME_LIMIT_MINUTES)
        items = parse_export(answer)
    except ClaudeFailed as err:
        return _fail(conn, str(err))
    except ValueError as err:
        preview = inbox._clean(answer, 120)
        return _fail(conn, f"Claude didn't hand back a usable list: {err} Its answer began: {preview}")
    return ingest(conn, cfg, items)


def check(conn, cfg: dict) -> dict:
    """The sweep's mail step: Gmail through Claude Code if search.toml asks for it, otherwise IMAP."""
    if cfg.get("inbox", {}).get("source", "imap") == SOURCE:
        return run(conn, cfg)
    return inbox.run(conn, cfg)


def summary(result: dict) -> str:
    """One sentence for the sweep's report."""
    if result["state"] == "ok":
        replies, alerts = len(result["found"]), len(result.get("alerts", []))
        said = f"Mail checked: {replies} possible repl{'y' if replies == 1 else 'ies'}"
        return said + (f", {alerts} possible scam{'' if alerts == 1 else 's'}." if alerts else ".")
    if result["state"] == "error":
        return "Mail couldn't be checked: see the Veins tab."
    return "Reply detection isn't set up, so no mail was checked."
