"""Spot possible replies to your applications in Gmail, over read-only IMAP.

This only ever notes that a reply might have come. It records the sender, subject
and date on the job's timeline and never changes a status, so a false match can't
touch the response rate. You confirm on the dashboard.

Mailboxes are opened with EXAMINE and read with BODY.PEEK, and only the headers
are requested, so message bodies never reach this machine's database. Header text
is written by whoever sent the mail, so it's cleaned here and shown as text only.
"""
import email
import email.policy
import getpass
import imaplib
import os
import re
import sqlite3
import ssl
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.headerregistry import Address
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .sources import strip_invisible
from .store import ACTIVE, REPLY_DETECTED, log_event, now

# The dashboard runs under pythonw, with no console of its own, so a console program it starts would open a window
# of its own unless told not to.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CREDENTIALS_PATH = Path.home() / ".config" / "pyrite" / "imap.env"
SOURCE_KEY = "inbox:imap"
DEFAULT_HOST = "imap.gmail.com"
# All Mail, so a reply you read and archived before the morning scan still counts.
DEFAULT_FOLDER = "[Gmail]/All Mail"
FALLBACK_FOLDER = "INBOX"
TIMEOUT_SECONDS = 60
DEFAULT_LOOKBACK_DAYS = 14
BATCH_SIZE = 200
MAX_MESSAGES = 5000
HEADER_FETCH = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE LIST-UNSUBSCRIBE)])"

# Applicant tracking systems send for many employers, so the sender's domain says
# nothing here. The company has to be named in the display name or subject.
ATS_DOMAINS = (
    "ashbyhq.com", "bamboohr.com", "breezy.hr", "dover.com", "eightfold.ai", "gem.com", "greenhouse-mail.io",
    "greenhouse.io", "icims.com", "jazz.co", "jazzhr.com", "jobvite.com", "lever.co", "myworkday.com",
    "myworkdayjobs.com", "oraclecloud.com", "paradox.ai", "recruitee.com", "rippling.com", "smartrecruiters.com",
    "successfactors.com", "successfactors.eu", "taleo.net", "teamtailor.com", "workable.com", "workday.com",
)
# Job boards name employers in every alert, so their mail is never a reply.
JOB_BOARDS = (
    "builtin.com", "dice.com", "glassdoor.com", "hired.com", "indeed.com", "indeedemail.com", "linkedin.com",
    "monster.com", "otta.com", "welcometothejungle.com", "wellfound.com", "ziprecruiter.com",
)
TWO_PART_SUFFIXES = {
    "co.uk", "org.uk", "ac.uk", "com.au", "co.nz", "co.jp", "co.kr", "co.in", "co.il", "com.br", "com.cn", "com.mx", "com.sg",
}
PLACEHOLDER_COMPANIES = {"company not recorded"}
LEGAL_SUFFIX = re.compile(r"[,.\s]+(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|gmbh|plc)\.?$", re.I)
# Mailing lists carry List-Unsubscribe. From an employer that's usually marketing
# unless the subject is about hiring: think of a holiday sale versus an interview.
HIRING_SUBJECT = re.compile(
    r"\b(appl(y|ied|ying|ications?)|interview\w*|candidate\w*|position|role|recruit\w*|hiring|careers?|jobs?|next steps?)\b",
    re.I,
)
# Automatic mail that every application sets off: the receipt, and the candidate account's password and codes.
# None of it is the company answering. "Thank you for your interest" isn't here, since rejections often say that.
RECEIPT_SUBJECT = re.compile(
    r"\b(successfully (applied|submitted)|thanks? (you )?for applying|thanks? (you )?for (submitting )?your application"
    r"|application (was )?(received|submitted|complete|confirmation)|received your application|got your application"
    r"|reset (your )?password|password reset|verify your (email|account)|verification code|one[- ]time (pass)?code"
    r"|(sign[- ]in|security|access) code)\b",
    re.I,
)
# Words that make a receipt-like subject a real answer after all, when the message's own text is at hand.
ANSWER_TEXT = re.compile(
    r"\b(unfortunately|regret|not (to )?(move|moving) forward|other candidates|decided to|interview\w*|schedule|"
    r"next steps?|offer)\b",
    re.I,
)
UNSAFE_WHITESPACE = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")
DOMAIN_SHAPE = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
# What the part of an address before the @ may hold, so an o'brien isn't dropped.
LOCAL_PART = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+")


class NotConfigured(Exception):
    """No usable credentials yet. Normal until you set it up, so not a failure."""


class UnsafeCredentials(Exception):
    """The file exists but shouldn't be used as it stands."""


@dataclass
class Credentials:
    user: str
    password: str = field(repr=False)
    host: str = DEFAULT_HOST
    port: int = 993
    folder: str = ""


@dataclass
class Message:
    name: str
    local: str
    domain: str
    subject: str
    date: datetime
    bulk: bool = False

    @property
    def address(self) -> str:
        return f"{self.local}@{self.domain}"

    def detail(self) -> str:
        sender = f"{self.name} <{self.address}>" if self.name else self.address
        when = self.date.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        return f"From {sender} | Subject: {self.subject or '(none)'} | Date: {when}"


def _privacy_fix(path: Path, info: os.stat_result) -> str:
    """The command that makes this file private, or nothing if it already is."""
    if os.name != "nt":
        return f"chmod 600 {path}" if info.st_mode & 0o077 else ""
    # Windows has no meaningful mode bits, so read the access list. Anyone unrecognized counts as other users.
    fix = f'icacls "{path}" /inheritance:r /grant:r "{getpass.getuser()}:F"'
    try:
        listing = subprocess.run(["icacls", str(path)], capture_output=True, text=True, errors="replace", check=True,
                                 creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.CalledProcessError):
        return fix
    allowed = {"nt authority\\system", "builtin\\administrators", "owner rights", getpass.getuser().lower()}
    principals = re.findall(r"^\s*(.+?):\(", listing.replace(str(path), "", 1), re.M)
    if not principals:
        return fix
    private = all(p.lower() in allowed or p.lower().rsplit("\\", 1)[-1] == getpass.getuser().lower() for p in principals)
    return "" if private else fix


def load_credentials(path: Path) -> Credentials:
    try:
        info = path.stat()
    except FileNotFoundError:
        raise NotConfigured(f"No credentials at {path}.") from None
    except OSError as err:
        raise UnsafeCredentials(f"Can't read {path}: {err.strerror}.") from None
    fix = _privacy_fix(path, info)
    if fix:
        raise UnsafeCredentials(f"{path} can be read by other users. Fix it with: {fix}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise UnsafeCredentials(f"Can't read {path}.") from None

    values = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    user, password = values.get("IMAP_USER", ""), values.get("IMAP_PASSWORD", "")
    if not user or not password:
        raise NotConfigured(f"{path} needs both IMAP_USER and IMAP_PASSWORD filled in.")
    # IMAP sends the login as plain ASCII, so anything else can't be sent at all. The value itself is never repeated.
    for key, value in (("IMAP_USER", user), ("IMAP_PASSWORD", password)):
        if not value.isascii():
            raise UnsafeCredentials(f"{key} in {path} has a character IMAP can't send, such as an accented letter or a curly "
                                    "quote. An app password is plain letters: copy it again.")
    host = values.get("IMAP_HOST") or DEFAULT_HOST
    if host == DEFAULT_HOST:
        password = password.replace(" ", "")  # Google displays app passwords in groups of four.
    try:
        port = int(values.get("IMAP_PORT") or 993)
    except ValueError:
        raise UnsafeCredentials(f"IMAP_PORT in {path} isn't a number.") from None
    return Credentials(user, password, host, port, values.get("IMAP_FOLDER", ""))


def open_client(creds: Credentials):
    # imaplib doesn't verify certificates unless given a context, and this carries a password.
    return imaplib.IMAP4_SSL(creds.host, creds.port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT_SECONDS)


def _clean(text, limit: int) -> str:
    text = UNSAFE_WHITESPACE.sub(" ", strip_invisible(str(text or ""))).strip()
    return text[:limit]


def parse_headers(raw: bytes) -> Message | None:
    """Turn raw header bytes into a Message, or None if the sender or date can't be trusted to parse."""
    try:
        parsed = email.message_from_bytes(raw, policy=email.policy.default)
        addresses: Sequence[Address] = parsed["from"].addresses if parsed["from"] else ()
        if len(addresses) != 1:
            return None
        local, domain = addresses[0].username.lower(), addresses[0].domain.lower()
        name = addresses[0].display_name
        subject = parsed["subject"]
        date = parsedate_to_datetime(str(parsed["date"]))
        bulk = parsed["list-unsubscribe"] is not None
    except (ValueError, TypeError, AttributeError, IndexError, LookupError):
        return None
    if not DOMAIN_SHAPE.fullmatch(domain) or not LOCAL_PART.fullmatch(local):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=UTC)
    return Message(_clean(name, 80), local, domain, _clean(subject, 200), date, bulk)


def registrable(host: str) -> str:
    labels = host.lower().rstrip(".").split(".")
    keep = 3 if ".".join(labels[-2:]) in TWO_PART_SUFFIXES else 2
    return ".".join(labels[-keep:])


def _within(host: str, domains) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _core_name(company: str) -> str:
    name = re.sub(r"\(.*?\)", " ", company or "").strip()
    name = LEGAL_SUFFIX.sub("", name).strip()
    return "" if name.lower() in PLACEHOLDER_COMPANIES else name


def _compact(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _names_company(text: str, core: str) -> bool:
    """A whole-word match, so "Initech" doesn't match "Applied Initechnics"."""
    words = r"\s+".join(re.escape(word) for word in core.split())
    return re.search(rf"(?<![^\W_]){words}(?![^\W_])", text, re.I) is not None


def employer_domains(job, cfg: dict[str, Any]) -> set[str]:
    """Domains known to belong to this employer: from search.toml, and the posting's own link."""
    listed = cfg.get("inbox", {}).get("domains", {}).get(job["company"], [])
    domains = {registrable(domain) for domain in listed}
    host = urlparse(job["url"] or "").hostname or ""
    if host and DOMAIN_SHAPE.fullmatch(host.lower()) and not _within(host.lower(), ATS_DOMAINS + JOB_BOARDS):
        domains.add(registrable(host))
    return domains


def is_match(job, message: Message, domains: set[str]) -> bool:
    core = _core_name(job["company"])
    if not core or _within(message.domain, JOB_BOARDS):
        return False
    if message.bulk and not HIRING_SUBJECT.search(message.subject):
        return False
    compact = _compact(core)
    if _within(message.domain, ATS_DOMAINS):
        board = job["source_key"].partition(":")[2].lower()
        return (_names_company(message.name, core) or _names_company(message.subject, core)
                or message.local in {compact, board})
    # Only the registered domain counts, so acme.evil.example isn't Acme.
    site = registrable(message.domain)
    label, _, suffix = site.partition(".")
    return site in domains or compact in (label, label + suffix)


def _as_utc(iso: str) -> datetime:
    value = datetime.fromisoformat(iso)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _cutoff(job) -> datetime:
    """Mail older than your last update on a job has already been accounted for."""
    return max(_as_utc(stamp) for stamp in (job["applied_at"], job["status_changed_at"]) if stamp)


def tracked_jobs(conn) -> list[sqlite3.Row]:
    marks = ", ".join("?" * len(ACTIVE))
    return conn.execute(
        f"SELECT * FROM jobs WHERE applied_at IS NOT NULL AND status IN ({marks})", ACTIVE,
    ).fetchall()


def _select(client, folder: str) -> bool:
    quoted = folder.replace('"', "")
    typ, _ = client.select(f'"{quoted}"', readonly=True)
    return typ == "OK"


def _all_mail_folder(client) -> str | None:
    """The folder the server flags \\All, whatever it's called. Listing folders reads nothing and changes nothing."""
    try:
        typ, rows = client.list()
    except (imaplib.IMAP4.error, OSError):
        return None
    if typ != "OK":
        return None
    for row in rows or []:
        line = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if match and "\\All" in match.group("flags").split():
            return match.group("name").strip().strip('"')
    return None


def read_messages(client, since: datetime, own_address: str) -> list[Message]:
    typ, data = client.uid("SEARCH", "SINCE", since.strftime("%d-%b-%Y"))
    if typ != "OK":
        raise imaplib.IMAP4.error("The mailbox search failed.")
    uids = (data[0].split() if data and data[0] else [])[-MAX_MESSAGES:]
    messages = []
    for start in range(0, len(uids), BATCH_SIZE):
        chunk = b",".join(uids[start:start + BATCH_SIZE]).decode()
        typ, data = client.uid("FETCH", chunk, HEADER_FETCH)
        if typ != "OK":
            raise imaplib.IMAP4.error("Reading message headers failed.")
        for part in data:
            if isinstance(part, tuple):
                message = parse_headers(part[1])
                if message and message.address != own_address:
                    messages.append(message)
    return messages


def _read_mailbox(creds: Credentials, jobs: list[sqlite3.Row], cfg: dict[str, Any], client_factory) -> tuple[list[Message], str]:
    client = client_factory(creds)
    try:
        typ, _ = client.login(creds.user, creds.password)
        if typ != "OK":
            raise imaplib.IMAP4.error("Login refused.")
        folder = creds.folder or DEFAULT_FOLDER
        if not _select(client, folder):
            if creds.folder:
                raise imaplib.IMAP4.error(f"Couldn't open the folder {folder}.")
            # Gmail names All Mail in the account's language, so look for the folder flagged as it.
            named = _all_mail_folder(client)
            if named and _select(client, named):
                folder = named
            elif _select(client, FALLBACK_FOLDER):
                folder = FALLBACK_FOLDER
            else:
                raise imaplib.IMAP4.error(f"Couldn't open the folder {folder}.")
        if not jobs:
            return [], folder  # Still logged in above, so setup can be tested before the first application.
        days = cfg.get("inbox", {}).get("lookback_days", DEFAULT_LOOKBACK_DAYS)
        oldest_allowed = datetime.now(UTC) - timedelta(days=days)
        # SINCE ignores time zones, so start a day early and let _cutoff decide.
        since = max(oldest_allowed, min(_cutoff(job) for job in jobs)) - timedelta(days=1)
        return read_messages(client, since, creds.user.lower()), folder
    finally:
        try:
            client.logout()
        except (imaplib.IMAP4.error, OSError, EOFError):
            pass


def is_receipt(message: Message) -> bool:
    """Automatic mail an application sets off, which isn't the company answering. When the message's own text is at
    hand, as it is through Gmail, a receipt-like subject over a rejection or an interview invitation still counts."""
    if not RECEIPT_SUBJECT.search(message.subject):
        return False
    return not ANSWER_TEXT.search(getattr(message, "text", "") or "")


def _words(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", (text or "").lower())) + " "


def _names_title(subject: str, title: str) -> bool:
    words = _words(title)
    return words.strip() != "" and words in _words(subject)


def record_matches(conn, jobs: list[sqlite3.Row], messages: Sequence[Message], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Add each new match to its job's timeline. This never touches a job's status.

    Receipts are left out. When a message matches several applications at one company and its subject names some of
    their titles, only those get it; otherwise there's no telling which it's about, so they all do."""
    found = []
    domains = {job["id"]: employer_domains(job, cfg) for job in jobs}
    cutoffs = {job["id"]: _cutoff(job) for job in jobs}
    seen = {job["id"]: {row["detail"] for row in conn.execute(
        "SELECT detail FROM events WHERE job_id = ? AND kind = ?", (job["id"], REPLY_DETECTED),
    )} for job in jobs}
    for message in messages:
        if is_receipt(message):
            continue
        matched = [job for job in jobs if message.date >= cutoffs[job["id"]] and is_match(job, message, domains[job["id"]])]
        named = [job for job in matched if _names_title(message.subject, job["title"])]
        detail = message.detail()
        for job in named or matched:
            if detail in seen[job["id"]]:
                continue
            seen[job["id"]].add(detail)
            log_event(conn, job["id"], REPLY_DETECTED, detail)
            found.append({"job_id": job["id"], "company": job["company"], "sender": message.address})
    return found


def _record_status(conn, error: str = "", count: int = 0, source_key: str = SOURCE_KEY, company: str = "Email replies") -> None:
    """Reported beside the job boards: a dead login must not look like a quiet inbox."""
    ts = now()
    conn.execute(
        """INSERT INTO source_status (source_key, company, last_run, last_ok, last_error, last_count)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (source_key) DO UPDATE SET last_run = excluded.last_run, last_error = excluded.last_error,
               last_count = excluded.last_count, last_ok = COALESCE(excluded.last_ok, last_ok)""",
        (source_key, company, ts, None if error else ts, error[:300], count),
    )


def _describe(err: Exception, creds: Credentials) -> str:
    text = f"{type(err).__name__}: {err}"
    for secret in {creds.password, creds.user}:
        text = text.replace(secret, "***")
    return text[:300]


def run(conn, cfg: dict[str, Any], path: Path | None = None, client_factory=open_client) -> dict[str, Any]:
    """One scan. Returns {"state": "not_configured" | "error" | "ok", ...} and never raises for mail trouble."""
    try:
        creds = load_credentials(path or CREDENTIALS_PATH)
    except NotConfigured as err:
        conn.execute("DELETE FROM source_status WHERE source_key = ?", (SOURCE_KEY,))
        conn.commit()
        return {"state": "not_configured", "message": str(err)}
    except UnsafeCredentials as err:
        _record_status(conn, error=str(err))
        conn.commit()
        return {"state": "error", "message": str(err)}

    jobs = tracked_jobs(conn)
    try:
        # Nothing is written until the network is done, so a slow mailbox never holds the database.
        messages, folder = _read_mailbox(creds, jobs, cfg, client_factory)
    except (imaplib.IMAP4.error, OSError, EOFError, UnicodeError) as err:
        message = _describe(err, creds)
        _record_status(conn, error=message)
        conn.commit()
        return {"state": "error", "message": message}

    found = record_matches(conn, jobs, messages, cfg)
    _record_status(conn, count=len(messages))
    conn.commit()
    return {"state": "ok", "folder": folder, "jobs": len(jobs), "messages": len(messages), "found": found}
