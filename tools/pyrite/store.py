"""SQLite storage and the application state machine."""
import json
import os
import re
import sqlite3
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_ROOT = (CODE_ROOT / "example").resolve()
# A one-line, git-ignored file holding the path to your private workspace.
HOME_POINTER = CODE_ROOT / ".pyrite-home"
# Set by the entry point for `init` and help, which a workspace that's named but not made yet mustn't stop: `init` is
# how it gets made. They then see the example, and nothing else is allowed to.
MAY_BE_MISSING = "PYRITE_WORKSPACE_MAY_BE_MISSING"


def _read_pointer(path: Path) -> str:
    """The path in the pointer file, however it was saved. PowerShell's `>` writes UTF-16, and some editors add a byte-order mark."""
    raw = path.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        return raw.decode(encoding).strip().strip('"')
    except UnicodeError:
        raise SystemExit(f"Can't read {path}. Save it as plain text holding one line: the path to your workspace.") from None


def find_workspace() -> Path:
    """Where the data lives: PYRITE_HOME, then .pyrite-home, then the fictional example.

    The code and the data are separate on purpose, so that nothing personal can be
    committed from this repository. A workspace that was named but can't be found
    stops here, because an empty database would look exactly like a lost one.
    """
    chosen, origin = os.environ.get("PYRITE_HOME", "").strip(), "PYRITE_HOME"
    if not chosen and HOME_POINTER.exists():
        chosen, origin = _read_pointer(HOME_POINTER), str(HOME_POINTER)
    if not chosen:
        return EXAMPLE_ROOT
    workspace = Path(_windows_path(chosen)).expanduser().resolve()
    if not workspace.is_dir():
        if os.environ.get(MAY_BE_MISSING):
            return EXAMPLE_ROOT
        raise SystemExit(f"The Pyrite workspace doesn't exist: {workspace}\nThat path comes from {origin}. Fix the path, or make a "
                         f"workspace there with `pyrite init {workspace} --name \"Your Name\"`, with your own name.")
    return workspace


def _windows_path(chosen: str) -> str:
    """A path as Git Bash writes it, such as /d/jobs, in the form Windows reads, D:/jobs. Elsewhere, unchanged."""
    match = re.fullmatch(r"/([A-Za-z])(/.*)?", chosen) if os.name == "nt" else None
    return f"{match[1].upper()}:{match[2] or '/'}" if match else chosen


ROOT = find_workspace()
IS_EXAMPLE = ROOT == EXAMPLE_ROOT
DB_PATH = ROOT / "data" / "pyrite.db"
CONFIG_PATH = ROOT / "profile" / "search.toml"

# Discovery -> tailoring -> your application -> what came back.
STATUSES = (
    "new", "shortlisted", "needs_fix", "ready",
    "applied", "responded", "interviewing", "offer",
    "rejected", "ghosted", "withdrawn", "passed", "closed",
)
ACTIVE = ("new", "shortlisted", "needs_fix", "ready", "applied", "responded", "interviewing", "offer")
# Only the fact checker's verdict puts a job in these, through `pyrite finish`. No command or button sets them by hand.
CHECKER_ONLY = ("ready", "needs_fix")
# Logged when you ask for a job to be tailored next, which also gives a blocked draft a fresh set of tries.
TAILOR_REQUESTED = "tailor_requested"
# Failed tries at a draft before the daily run stops retrying it. `fix_attempts` under [run] overrides this.
DEFAULT_FIX_ATTEMPTS = 6
# Event kinds for mail that might be a reply. Neither one changes a job's status.
REPLY_DETECTED = "reply_detected"
REPLY_DISMISSED = "reply_dismissed"
# Logged when you reach out about an application, such as a note to the hiring manager. It doesn't change the status.
REACHED_OUT = "reached_out"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    source_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    dedupe_key TEXT,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT DEFAULT '',
    location_kind TEXT DEFAULT '',
    workplace TEXT DEFAULT '',
    url TEXT DEFAULT '',
    description TEXT DEFAULT '',
    comp TEXT DEFAULT '',
    posted_at TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    posting_closed_at TEXT,
    score INTEGER DEFAULT 0,
    score_reasons TEXT DEFAULT '[]',
    track TEXT DEFAULT '',
    flags TEXT DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    status_changed_at TEXT,
    fit TEXT DEFAULT '',
    fit_reason TEXT DEFAULT '',
    priority INTEGER DEFAULT 0,
    app_folder TEXT DEFAULT '',
    files TEXT DEFAULT '[]',
    check_result TEXT DEFAULT '',
    ready_at TEXT,
    applied_at TEXT,
    response_at TEXT,
    interview_at TEXT,
    offer_at TEXT,
    closed_out_at TEXT,
    next_action TEXT DEFAULT '',
    next_action_date TEXT,
    notes TEXT DEFAULT '',
    first_posted_at TEXT,
    reposts INTEGER DEFAULT 0,
    redates INTEGER DEFAULT 0,
    last_reposted_at TEXT,
    UNIQUE (source_key, source_id)
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status);
CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs (dedupe_key);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs (id),
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_job ON events (job_id);
CREATE TABLE IF NOT EXISTS listings (
    source_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES jobs (id),
    location TEXT DEFAULT '',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    posted_at TEXT,
    PRIMARY KEY (source_key, source_id)
);
CREATE INDEX IF NOT EXISTS listings_job ON listings (job_id);
CREATE TABLE IF NOT EXISTS rejected (
    source_key TEXT NOT NULL,
    source_id TEXT NOT NULL,
    reason TEXT,
    ts TEXT NOT NULL,
    PRIMARY KEY (source_key, source_id)
);
CREATE TABLE IF NOT EXISTS source_status (
    source_key TEXT PRIMARY KEY,
    company TEXT,
    last_run TEXT,
    last_ok TEXT,
    last_error TEXT DEFAULT '',
    last_count INTEGER DEFAULT 0,
    tracked_since TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    stats TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claude_runs (
    id INTEGER PRIMARY KEY,
    job_id INTEGER REFERENCES jobs (id),
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 1,
    seconds REAL DEFAULT 0,
    turns INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    detail TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS mail_alerts (
    id INTEGER PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    ts TEXT NOT NULL,
    job_id INTEGER REFERENCES jobs (id),
    sender TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    date TEXT,
    reasons TEXT DEFAULT '[]',
    dismissed_at TEXT
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def today_plus(days: int) -> str:
    return (datetime.now().astimezone() + timedelta(days=days)).date().isoformat()


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"There's no {CONFIG_PATH}. Copy example/profile/ into your workspace to start, then run `pyrite doctor`.")
    with CONFIG_PATH.open("rb") as handle:
        return tomllib.load(handle)


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    _stamp_scoring(conn)
    return conn


SCORING_VERSION = "scoring_version"


def get_meta(conn, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))


def _stamp_scoring(conn) -> None:
    """Record which scoring a database's postings have. A new one has none to rescore, so it starts at the current
    version. One from before versions were kept starts at 0, so its next sweep brings every prospect up to date."""
    if get_meta(conn, SCORING_VERSION) is not None:
        return
    from . import score

    empty = conn.execute("SELECT 1 FROM jobs LIMIT 1").fetchone() is None
    conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (SCORING_VERSION, str(score.VERSION if empty else 0)))
    conn.commit()


def scoring_version(conn) -> int:
    return int(get_meta(conn, SCORING_VERSION) or 0)


def _migrate(conn) -> None:
    """Bring an older database up to date. Its listing history starts from what it already knows."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}
    # The sent copy's fingerprints, and the folder's as they were when you said its changes since were fine.
    for column in ("sent_files", "sent_ack"):
        if column not in columns:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError as err:
                if "duplicate column" not in str(err):
                    raise
                # Another process added it first.
            conn.commit()
    _mark_cut_reasons(conn)
    if "reposts" in columns:
        return
    conn.execute("BEGIN IMMEDIATE")
    if "reposts" in {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")}:
        conn.rollback()  # Another process got here first.
        return
    for table, column, kind in (
        ("jobs", "first_posted_at", "TEXT"), ("jobs", "reposts", "INTEGER DEFAULT 0"),
        ("jobs", "redates", "INTEGER DEFAULT 0"), ("jobs", "last_reposted_at", "TEXT"),
        ("source_status", "tracked_since", "TEXT"),
    ):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.execute("UPDATE jobs SET first_posted_at = posted_at")
    conn.execute(
        """INSERT OR IGNORE INTO listings (source_key, source_id, job_id, location, first_seen, last_seen, posted_at)
           SELECT source_key, source_id, id, location, first_seen, last_seen, posted_at FROM jobs
           WHERE source_key NOT IN ('seed', 'manual')"""
    )
    conn.commit()


# Early versions cut a triage reason at 300 characters, often through a word and with nothing to say so.
CUT_REASON = "length(fit_reason) = 300 AND substr(fit_reason, -1) NOT IN ('.', '!', '?', '…', ')', '\"', '''')"


def _mark_cut_reasons(conn) -> None:
    """End each reason those versions cut with an ellipsis, so it reads as cut rather than finished. A marked reason is
    a character longer and never matches again, so this writes only while there's something left to mark."""
    if conn.execute(f"SELECT 1 FROM jobs WHERE {CUT_REASON} LIMIT 1").fetchone():
        conn.execute(f"UPDATE jobs SET fit_reason = fit_reason || '…' WHERE {CUT_REASON}")
        conn.commit()


def shorten(text: str, limit: int) -> str:
    """Text cut to fit a small space, at the end of a word rather than through one, with an ellipsis to say so."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


SENT_FOLDER = "sent"
SENT_SUFFIXES = (".md", ".docx", ".pdf", ".txt")


def sent_copies(folder: Path) -> list[Path]:
    """The documents kept as the record of what was sent, if a copy was made."""
    sent = folder / SENT_FOLDER
    return sorted(p for p in sent.iterdir() if p.is_file()) if sent.is_dir() else []


def freeze_sent(conn, job_id: int, source: Path | None = None) -> dict[str, str]:
    """Keep a copy of what was sent, and record its fingerprints so later changes to the folder show.

    Copies resume.md, cover-letter.md and the built documents into the folder's `sent/`, read-only, the
    first time a job is marked applied. A copy that already exists is left alone: the first application
    is the one that was sent, and a second application is a new job. `source` names another folder to
    copy from, for applications made before this existed. The fictional example is never written to.
    """
    import hashlib
    import shutil
    import stat

    job = get_job(conn, job_id)
    if IS_EXAMPLE or not job["app_folder"] or not (ROOT / job["app_folder"]).is_dir():
        return {}
    folder = ROOT / job["app_folder"]
    sent = folder / SENT_FOLDER
    if sent_copies(folder):
        return json.loads(job["sent_files"] or "{}")
    source = source or folder
    if not source.is_dir():
        return {}
    wanted = [p for p in sorted(source.iterdir()) if p.is_file() and p.suffix in SENT_SUFFIXES
              and (p.suffix != ".md" or p.name in ("resume.md", "cover-letter.md"))]
    if not wanted:
        return {}
    sent.mkdir(exist_ok=True)
    fingerprints = {}
    for path in wanted:
        copy = sent / path.name
        shutil.copyfile(path, copy)
        os.chmod(copy, stat.S_IREAD)
        fingerprints[path.name] = hashlib.sha256(copy.read_bytes()).hexdigest()
    conn.execute("UPDATE jobs SET sent_files = ? WHERE id = ?", (json.dumps(fingerprints), job_id))
    log_event(conn, job_id, "sent_copy", f"Kept a read-only copy of {len(fingerprints)} sent files in {SENT_FOLDER}/")
    return fingerprints


def _recorded(job, column: str) -> dict:
    return json.loads(job[column] or "{}") if column in job.keys() else {}  # noqa: SIM118  sqlite3.Row has no __contains__ for names.


def _folder_fingerprints(job, names) -> dict[str, str | None]:
    """The fingerprint of each named file in the job's folder as it is now, or None for one that's gone."""
    import hashlib

    folder = ROOT / job["app_folder"]
    found: dict[str, str | None] = {}
    for name in names:
        try:
            found[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        except OSError:
            found[name] = None
    return found


def sent_changes(job) -> tuple[list[str], bool]:
    """Files in the folder that no longer match the sent copy, and whether you've said that's fine for the folder as
    it is now. A change after that shows again. Nothing changed when nothing was recorded."""
    recorded = _recorded(job, "sent_files")
    if not recorded or not job["app_folder"]:
        return [], False
    current = _folder_fingerprints(job, recorded)
    changed = sorted(name for name, digest in recorded.items() if current[name] != digest)
    return changed, bool(changed) and _recorded(job, "sent_ack") == current


def changed_after_sending(job) -> list[str]:
    """Files that no longer match the sent copy, unless you've already said the folder as it is now is fine."""
    changed, acknowledged = sent_changes(job)
    return [] if acknowledged else changed


def acknowledge_sent_changes(conn, job_id: int) -> list[str]:
    """Say the folder's changes since sending are fine as they are, so they stop being flagged until it changes again.
    The sent copy stays the record either way. Returns the files that differ from it."""
    job = get_job(conn, job_id)
    changed, acknowledged = sent_changes(job)
    if not changed:
        raise ValueError("Every file still matches the sent copy, so there's nothing to acknowledge.")
    if not acknowledged:
        current = _folder_fingerprints(job, _recorded(job, "sent_files"))
        conn.execute("UPDATE jobs SET sent_ack = ? WHERE id = ?", (json.dumps(current), job_id))
        log_event(conn, job_id, "sent_changes_acknowledged",
                  f"You kept the changes to {', '.join(changed)}. The copy in {SENT_FOLDER}/ is still what was sent.")
    return changed


def record_listing(conn, job_id: int, source_key: str, source_id: str, location: str, posted_at: str | None, ts: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO listings (source_key, source_id, job_id, location, first_seen, last_seen, posted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_key, source_id, job_id, location, ts, ts, posted_at),
    )


def log_event(conn, job_id: int, kind: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO events (job_id, ts, kind, detail) VALUES (?, ?, ?, ?)",
        (job_id, now(), kind, detail),
    )


class JobNotFound(KeyError):
    """A job number that isn't in the database. `str()` gives the plain sentence, without a KeyError's quotes."""

    def __init__(self, job_id: int):
        super().__init__(job_id)
        self.job_id = job_id

    def __str__(self) -> str:
        return f"no job {self.job_id}"


def get_job(conn, job_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise JobNotFound(job_id)
    return row


def set_status(conn, job_id: int, status: str, note: str = "", follow_up_days: int = 7) -> None:
    """Move a job to a status, stamping the funnel dates it has now reached."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    job = get_job(conn, job_id)
    ts = now()
    fields: dict = {"status": status, "status_changed_at": ts}

    if status == "ready" and not job["ready_at"]:
        fields["ready_at"] = ts
    if status == "applied":
        fields["applied_at"] = job["applied_at"] or ts
        fields["next_action"] = "Follow up"
        fields["next_action_date"] = today_plus(follow_up_days)
    if status in ("responded", "interviewing", "offer"):
        fields["response_at"] = job["response_at"] or ts
        if job["next_action"] == "Follow up":
            fields["next_action"] = ""
            fields["next_action_date"] = None
    if status == "interviewing":
        fields["interview_at"] = job["interview_at"] or ts
    if status == "offer":
        fields["offer_at"] = job["offer_at"] or ts
    if status == "rejected" and job["applied_at"]:
        # A rejection is still hearing back, so it counts toward the response rate.
        fields["response_at"] = job["response_at"] or ts
    if status not in ACTIVE:
        fields["closed_out_at"] = ts
        fields["next_action"] = ""
        fields["next_action_date"] = None
    else:
        fields["closed_out_at"] = None

    assignments = ", ".join(f"{key} = ?" for key in fields)
    conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
    log_event(conn, job_id, status, note)
    if status == "applied" and not job["applied_at"]:
        # From here on the documents are the record of what was sent, so keep a copy and freeze the draft.
        freeze_sent(conn, job_id)


def log_outreach(conn, job_id: int, on: str = "", to: str = "", note: str = "", follow_up_days: int = 7) -> None:
    """Record reaching out about a sent application, on the day `on` (today if empty), to whoever `to` names.

    While the automatic follow-up reminder still stands, it moves to `follow_up_days` after the later of the application
    and this, so it comes a week after you last made contact. A next step you set yourself is left alone.
    """
    job = get_job(conn, job_id)
    if not job["applied_at"] or job["status"] not in ACTIVE:
        raise ValueError("Reaching out is logged on an application you've sent and haven't closed.")
    today = datetime.now().astimezone().date()
    try:
        day = date.fromisoformat(on) if on else today
    except ValueError:
        raise ValueError("Give the day as YYYY-MM-DD.") from None
    if day > today:
        raise ValueError("That day hasn't come yet. Log reaching out once you have.")
    to, note = " ".join(to.split())[:120], note.strip()[:2000]
    detail = f"On {day:%b} {day.day}" + (f", to {to}" if to else "") + "." + (f" {note}" if note else "")
    if job["status"] == "applied" and job["next_action"] == "Follow up":
        applied = datetime.fromisoformat(job["applied_at"]).astimezone().date()
        remind = (max(applied, day) + timedelta(days=follow_up_days)).isoformat()
        conn.execute("UPDATE jobs SET next_action_date = ? WHERE id = ?", (remind, job_id))
    log_event(conn, job_id, REACHED_OUT, detail)


def outreach(conn) -> set[int]:
    """The jobs you've logged reaching out about."""
    return {row[0] for row in conn.execute("SELECT DISTINCT job_id FROM events WHERE kind = ?", (REACHED_OUT,))}


def possible_replies(conn) -> dict[int, dict]:
    """Detected mail you haven't dealt with yet, by job. Any status update or a dismissal settles it."""
    settled = (*STATUSES, REPLY_DISMISSED)
    marks = ", ".join("?" * len(settled))
    rows = conn.execute(
        f"""SELECT job_id, detail FROM events AS e
            WHERE kind = ? AND id > COALESCE(
                (SELECT MAX(id) FROM events WHERE job_id = e.job_id AND kind IN ({marks})), 0)
            ORDER BY id""",
        (REPLY_DETECTED, *settled),
    ).fetchall()
    flags: dict[int, dict] = {}
    for row in rows:
        count = flags.get(row["job_id"], {}).get("count", 0) + 1
        flags[row["job_id"]] = {"detail": row["detail"], "count": count}
    return flags


def fix_attempts(conn) -> dict[int, int]:
    """How many times each blocked draft has failed the fact checker since you last asked for it, by job."""
    rows = conn.execute(
        """SELECT e.job_id, COUNT(*) AS tries FROM events AS e JOIN jobs AS j ON j.id = e.job_id
           WHERE j.status = 'needs_fix' AND e.kind = 'needs_fix' AND e.id > COALESCE(
               (SELECT MAX(id) FROM events WHERE job_id = e.job_id AND kind = ?), 0)
           GROUP BY e.job_id""",
        (TAILOR_REQUESTED,),
    ).fetchall()
    return {row["job_id"]: row["tries"] for row in rows}


def job_dict(row: sqlite3.Row, include_description: bool = False) -> dict:
    data = dict(row)
    if not include_description:
        data.pop("description", None)
    for key in ("score_reasons", "flags", "files"):
        data[key] = json.loads(data.get(key) or "[]")
    data["check_result"] = json.loads(data["check_result"]) if data.get("check_result") else None
    return data


def quiet_days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    then = datetime.fromisoformat(iso)
    return (datetime.now(UTC) - then).days
