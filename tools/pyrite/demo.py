"""Fill the example workspace's database with a believable, entirely fictional job search.

Everything here is invented so the dashboard can be shown without showing anyone's real
search. The fact checker's verdicts are real: it runs on each draft, and the scorer scores
each posting.
"""
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from . import checks
from . import score as scoring
from .store import REPLY_DETECTED, ROOT, SCORING_SETTINGS, SCORING_VERSION, log_event, set_meta, set_status

ACME = "applications/2026-11-acme-principal-robotics-software-engineer"
GLOBEX = "applications/2026-11-globex-staff-firmware-engineer"
GHOST = "Massive Dynamic"

# company, title, location, fit, why, status, days ago found. The score, track and kind of place are the scorer's.
JOBS = [
    ("Acme Robotics", "Principal Robotics Software Engineer", "Madison, WI", "strong",
     "Motor control and test automation are the core of the job and of the record.", "applied", 12),
    ("Globex Automation", "Staff Firmware Engineer", "Remote - US", "good",
     "Strong firmware match, but the posting requires safety certification experience.", "needs_fix", 3),
    ("Initech Controls", "Firmware Engineering Manager", "Middleton, WI", "strong",
     "Matches the management years, the team size and the location.", "ready", 2),
    ("Stark Dynamics", "Principal Engineer, AI Developer Tools", "Remote - US", "good",
     "The agent workflow is direct evidence, though the pilot was small.", "ready", 2),
    ("Wayne Aerospace", "Senior Embedded Software Engineer", "Madison, WI", "good",
     "Solid firmware fit in a new industry.", "shortlisted", 1),
    ("Contoso Machines", "Staff Simulation Engineer", "Remote - US", "good",
     "Simulation is real but secondary in the record.", "interviewing", 26),
    ("Tyrell Systems", "Director of Software Engineering", "Sun Prairie, WI", "stretch",
     "A level above anything on the record, and worth one try.", "responded", 18),
    ("Soylent Labs", "Principal Embedded Engineer", "Remote - US", "good",
     "Good match on paper.", "rejected", 30),
    ("Aperture Science", "Senior Controls Engineer", "Verona, WI", "good",
     "Controls-heavy role close to home.", "ghosted", 44),
    ("Hooli Autonomy", "Director of Firmware Engineering", "Remote - US", "skip",
     "Needs a decade of people management, and the record has under three years.", "passed", 6),
    ("Cyberdyne Research", "Staff Robotics Engineer", "Madison, WI", "", "", "new", 0),
    ("Massive Dynamic", "Principal Firmware Engineer", "Remote - US", "", "", "new", 0),
    ("Umbrella Instruments", "Senior Firmware Engineer", "Waunakee, WI", "", "", "new", 1),
    ("Oscorp Robotics", "Staff AI Engineer, Inference", "Remote - US", "", "", "new", 1),
    ("Vandelay Motion", "Staff Motion Control Engineer", "Austin, TX", "", "", "new", 2),
]
# Pay ranges, as boards write them, for the postings that give one. A job elsewhere with one shows Moving for it.
COMP = {"Vandelay Motion": "$165,000 - $215,000 a year, plus equity"}
# Each application's folder under example/applications: its drafts and, once past the assay, its built documents.
FOLDERS = {
    "Acme Robotics": ACME,
    "Globex Automation": GLOBEX,
    "Initech Controls": "applications/2026-11-initech-firmware-engineering-manager",
    "Stark Dynamics": "applications/2026-11-stark-principal-engineer-ai-developer-tools",
}
# The steps a job passes through on its way to its final status.
PATH = {
    "applied": ["shortlisted", "ready", "applied"],
    "needs_fix": ["shortlisted", "needs_fix"],
    "ready": ["shortlisted", "ready"],
    "shortlisted": ["shortlisted"],
    "interviewing": ["shortlisted", "ready", "applied", "responded", "interviewing"],
    "responded": ["shortlisted", "ready", "applied", "responded"],
    "rejected": ["shortlisted", "ready", "applied", "rejected"],
    "ghosted": ["shortlisted", "ready", "applied", "ghosted"],
    "passed": ["passed"],
    "new": [],
}
# The note on the status change that closed a job, which the Closed tab shows. A pass says why in its fit reason.
CLOSING_NOTES = {
    "rejected": "They went with someone who has safety certification.",
    "ghosted": "Nothing back, even after a follow-up.",
}
# When each step came, as a share of the days since a job was found: one found 10 days ago was shortlisted 9.5 days
# ago, applied to 8 days ago, and so on. Its timeline then reads in order and agrees with its dates.
STEP_AT = {"found": 1.0, "shortlisted": 0.95, "passed": 0.9, "needs_fix": 0.9, "ready": 0.9, "applied": 0.8, "sent_copy": 0.8,
           "responded": 0.4, "interviewing": 0.3, "rejected": 0.25, "ghosted": 0.1}
# How long ago the last pan finished. The field report comes after it, so everything in the demo happened before the
# report, and it doesn't open out of date.
PAN_AGO = 0.2
SOURCES = [
    ("greenhouse:acme", "Acme Robotics", 41, ""),
    ("greenhouse:initech", "Initech Controls", 18, ""),
    ("lever:stark", "Stark Dynamics", 96, ""),
    ("ashby:cyberdyne", "Cyberdyne Research", 57, ""),
    ("workday:contoso", "Contoso Machines", 203, ""),
    ("workday:umbrella", "Umbrella Instruments", 0, "HTTPError: HTTP Error 503: Service Unavailable"),
    ("inbox:imap", "Email replies", 64, ""),
]
BRIEFING = (
    "Four new postings overnight. Two resumes are ready: send Initech Controls first, since it's local and matches "
    "your management years. The Globex draft is blocked by the assay and needs a rewrite. Umbrella Instruments' "
    "board is failing. Acme Robotics may have replied, so check your mail."
)


def _stamp(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _clear(conn) -> None:
    for table in ("events", "listings", "claude_runs", "tasks", "jobs", "rejected", "source_status", "runs", "briefings"):
        conn.execute(f"DELETE FROM {table}")


def _add_job(conn, cfg, row, index) -> int:
    company, title, location, fit, why, status, days = row
    # A posting found today was found by the last pan, which was before the field report.
    age = max(days, PAN_AGO)
    found = _stamp(age)
    slug = company.split()[0].lower()
    folder = FOLDERS.get(company, "")
    files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).iterdir() if p.suffix in (".pdf", ".docx")) if folder else []
    posting_file = ROOT / folder / "posting.md" if folder else None
    description = (
        posting_file.read_text(encoding="utf-8").partition("- **Saved:**")[2].partition("\n")[2].strip()
        if posting_file else f"Fictional posting. {company} is hiring a {title} to work on firmware, robots and motor control in C++."
    )
    # Scored by the scorer, so the Profile tab doesn't find every prospect out of step with the settings.
    verdict = scoring.evaluate(title, location, "", description, cfg, company)
    source = f"demo:{slug}"
    if not verdict.keep:
        # One the filters drop, such as a job outside the area, is there because it was added by hand, and is stored
        # as one, so a rescore judges it the way it was judged here.
        verdict = scoring.evaluate(title, location, "", description, cfg, company, added=True)
        source = "manual"
    cursor = conn.execute(
        """INSERT INTO jobs (source_key, source_id, company, title, location, location_kind, url, description, first_seen, last_seen,
               score, score_reasons, track, flags, status, status_changed_at, fit, fit_reason, app_folder, files, comp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'new', ?, ?, ?, ?, ?, ?)""",
        (source, str(index), company, title, location, verdict.location_kind,
         f"https://careers.{slug}.example/jobs/{1000 + index}", description, found, _stamp(PAN_AGO), verdict.score,
         json.dumps(verdict.reasons), verdict.track, found, fit, why, folder, json.dumps(files), COMP.get(company, "")),
    )
    job_id = cursor.lastrowid
    log_event(conn, job_id, "found", f"score {verdict.score}")
    # A posting that keeps coming back, to show the ghost-job warning. The rest are as dated.
    reposts, first_posted = (3, _stamp(140)) if company == GHOST else (0, found)
    conn.execute("UPDATE jobs SET posted_at = ?, first_posted_at = ?, reposts = ? WHERE id = ?", (found, first_posted, reposts, job_id))
    follow_up = cfg["run"]["follow_up_days"]
    steps = PATH[status]
    for step in steps:
        set_status(conn, job_id, step, why if step == "shortlisted" else CLOSING_NOTES.get(step, ""), follow_up)
    _backdate(conn, job_id, age, steps, follow_up)
    return job_id


def _backdate(conn, job_id: int, age: float, steps: list[str], follow_up: int) -> None:
    """Move a job's events and dates back to when each step came. set_status stamps them now, which would put every
    event after the field report, and every timeline at today under dates days earlier."""
    stamps = {kind: _stamp(age * share) for kind, share in STEP_AT.items() if kind in ("found", "sent_copy", *steps)}
    for kind, ts in stamps.items():
        conn.execute("UPDATE events SET ts = ? WHERE job_id = ? AND kind = ?", (ts, job_id, kind))
    last = stamps[steps[-1]] if steps else stamps["found"]
    dates: dict[str, str | None] = {
        "first_seen": stamps["found"], "ready_at": stamps.get("ready"), "applied_at": stamps.get("applied"),
        "response_at": stamps.get("responded") or stamps.get("rejected"), "interview_at": stamps.get("interviewing"),
        "status_changed_at": last, "closed_out_at": last}
    for column, when in dates.items():
        # Only the dates set_status set: a job that never heard back has no reply date to move.
        if when:
            conn.execute(f"UPDATE jobs SET {column} = ? WHERE id = ? AND {column} IS NOT NULL", (when, job_id))
    if "applied" in stamps:
        # The follow-up falls due a set time after applying, as it would have then.
        due = (datetime.fromisoformat(stamps["applied"]) + timedelta(days=follow_up)).astimezone().date().isoformat()
        conn.execute("UPDATE jobs SET next_action_date = ? WHERE id = ? AND next_action = 'Follow up'", (due, job_id))


def load(conn, cfg: dict[str, Any]) -> str:
    """Replace whatever the database holds with the demo. Callers must have checked this is the example."""
    _clear(conn)
    ids = {row[0]: _add_job(conn, cfg, row, index) for index, row in enumerate(JOBS, start=1)}

    # The real checker, on the deliberately bad draft and on the good ones.
    for company, folder in FOLDERS.items():
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (ids[company],)).fetchone()
        report = checks.check_application(ROOT / folder, cfg, company, job["title"], job["description"])
        conn.execute("UPDATE jobs SET check_result = ? WHERE id = ?", (json.dumps(report), ids[company]))

    log_event(conn, ids["Acme Robotics"], REPLY_DETECTED,
              f"From Sam Lee <sam@acme-robotics.example> | Subject: Your application | Date: {_stamp(0.3)[:16].replace('T', ' ')} UTC")
    conn.execute("UPDATE events SET ts = ? WHERE job_id = ? AND kind = ?", (_stamp(0.3), ids["Acme Robotics"], REPLY_DETECTED))

    now_stamp = _stamp(PAN_AGO)
    for key, company, count, error in SOURCES:
        conn.execute(
            "INSERT INTO source_status (source_key, company, last_run, last_ok, last_error, last_count) VALUES (?, ?, ?, ?, ?, ?)",
            (key, company, now_stamp, None if error else now_stamp, error, count),
        )
    stats = {"partial": False, "sources": len(SOURCES) - 1, "failed": 1, "postings": sum(s[2] for s in SOURCES[:-1]),
             "new": 4, "rejected": {"title": 301, "location": 88, "score": 7}, "closed": 0, "new_ids": []}
    conn.execute("INSERT INTO runs (started_at, finished_at, stats) VALUES (?, ?, ?)", (_stamp(PAN_AGO + 0.01), now_stamp, json.dumps(stats)))
    conn.execute("INSERT INTO briefings (ts, body) VALUES (?, ?)", (_stamp(0.1), BRIEFING))
    # Scored with the settings in search.toml now, as the pan that found them would have been.
    set_meta(conn, SCORING_VERSION, str(scoring.VERSION))
    set_meta(conn, SCORING_SETTINGS, scoring.settings_key(cfg))
    # A few Claude runs, so the usage table on the Sources tab has something to show.
    for company, kind, days_ago, ok, seconds, turns, tokens_in, tokens_out, cost in (
        ("Initech Controls", "refresh", 2, 1, 212, 14, 286_000, 5_100, 0.61),
        ("Globex Automation", "refresh", 3, 0, 547, 31, 702_000, 12_400, 1.48),
        ("Contoso Machines", "prep", 9, 1, 164, 11, 241_000, 3_900, 0.52),
    ):
        conn.execute(
            """INSERT INTO claude_runs (job_id, ts, kind, ok, seconds, turns, input_tokens, output_tokens, cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ids[company], _stamp(days_ago), kind, ok, seconds, turns, tokens_in, tokens_out, cost),
        )
    conn.commit()
    return f"Loaded {len(JOBS)} fictional jobs into {ROOT / 'data'}."
