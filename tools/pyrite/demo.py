"""Fill the example workspace's database with a believable, entirely fictional job search.

Everything here is invented so the dashboard can be shown without showing anyone's real
search. The fact checker's verdict on the blocked draft is real: it runs on that draft.
"""
import json
from datetime import UTC, datetime, timedelta

from . import checks
from .store import REPLY_DETECTED, ROOT, log_event, set_status

ACME = "applications/2026-11-acme-principal-robotics-software-engineer"
GLOBEX = "applications/2026-11-globex-staff-firmware-engineer"
GHOST = "Massive Dynamic"
TRACK_AI, TRACK_EMBEDDED, TRACK_LEAD = "AI systems", "Embedded, controls and simulation", "Engineering leadership"

# company, title, location, kind, track, score, fit, why, status, days ago found
JOBS = [
    ("Acme Robotics", "Principal Robotics Software Engineer", "Madison, WI", "local", TRACK_EMBEDDED, 88, "strong",
     "Motor control and test automation are the core of the job and of the record.", "applied", 12),
    ("Globex Automation", "Staff Firmware Engineer", "Remote - US", "remote", TRACK_EMBEDDED, 74, "good",
     "Strong firmware match, but the posting requires safety certification experience.", "needs_fix", 3),
    ("Initech Controls", "Firmware Engineering Manager", "Middleton, WI", "local", TRACK_LEAD, 81, "strong",
     "Matches the management years, the team size and the location.", "ready", 2),
    ("Stark Dynamics", "Principal Engineer, AI Developer Tools", "Remote - US", "remote", TRACK_AI, 79, "good",
     "The agent workflow is direct evidence, though the pilot was small.", "ready", 2),
    ("Wayne Aerospace", "Senior Embedded Software Engineer", "Madison, WI", "local", TRACK_EMBEDDED, 66, "good",
     "Solid firmware fit in a new industry.", "shortlisted", 1),
    ("Contoso Machines", "Staff Simulation Engineer", "Remote - US", "remote", TRACK_EMBEDDED, 71, "good",
     "Simulation is real but secondary in the record.", "interviewing", 26),
    ("Tyrell Systems", "Director of Software Engineering", "Sun Prairie, WI", "local", TRACK_LEAD, 69, "stretch",
     "A level above anything on the record, and worth one try.", "responded", 18),
    ("Soylent Labs", "Principal Embedded Engineer", "Remote - US", "remote", TRACK_EMBEDDED, 70, "good",
     "Good match on paper.", "rejected", 30),
    ("Aperture Science", "Senior Controls Engineer", "Verona, WI", "local", TRACK_EMBEDDED, 64, "good",
     "Controls-heavy role close to home.", "ghosted", 44),
    ("Hooli Autonomy", "Director of Firmware Engineering", "Remote - US", "remote", TRACK_LEAD, 62, "skip",
     "Needs a decade of people management, and the record has under three years.", "passed", 6),
    ("Cyberdyne Research", "Staff Robotics Engineer", "Madison, WI", "local", TRACK_EMBEDDED, 77, "", "", "new", 0),
    ("Massive Dynamic", "Principal Firmware Engineer", "Remote - US", "remote", TRACK_EMBEDDED, 73, "", "", "new", 0),
    ("Umbrella Instruments", "Senior Firmware Engineer", "Waunakee, WI", "local", TRACK_EMBEDDED, 61, "", "", "new", 1),
    ("Oscorp Robotics", "Staff AI Engineer, Inference", "Remote - US", "remote", TRACK_AI, 58, "", "", "new", 1),
]
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
    company, title, location, kind, track, score, fit, why, status, days = row
    found = _stamp(days)
    slug = company.split()[0].lower()
    folder = {"Acme Robotics": ACME, "Globex Automation": GLOBEX}.get(company, "")
    files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / folder).iterdir() if p.suffix in (".pdf", ".docx")) if folder else []
    posting_file = ROOT / folder / "posting.md" if folder else None
    description = (
        posting_file.read_text(encoding="utf-8").partition("- **Saved:**")[2].partition("\n")[2].strip()
        if posting_file else f"Fictional posting. {company} is hiring a {title} to work on firmware, robots and motor control in C++."
    )
    reasons = [f"{track} title +25", "seniority +10", f"{kind} +{15 if kind == 'local' else 10}", f"skills +{score - 45}: firmware, c++, robot"]
    cursor = conn.execute(
        """INSERT INTO jobs (source_key, source_id, company, title, location, location_kind, url, description, first_seen, last_seen,
               score, score_reasons, track, flags, status, status_changed_at, fit, fit_reason, app_folder, files)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'new', ?, ?, ?, ?, ?)""",
        (f"demo:{slug}", str(index), company, title, location, kind, f"https://careers.{slug}.example/jobs/{1000 + index}",
         description, found, _stamp(0), score, json.dumps(reasons), track, found, fit, why, folder, json.dumps(files)),
    )
    job_id = cursor.lastrowid
    log_event(conn, job_id, "found", f"score {score}")
    # A posting that keeps coming back, to show the ghost-job warning. The rest are as dated.
    reposts, first_posted = (3, _stamp(140)) if company == GHOST else (0, found)
    conn.execute("UPDATE jobs SET posted_at = ?, first_posted_at = ?, reposts = ? WHERE id = ?", (found, first_posted, reposts, job_id))
    follow_up = cfg["run"]["follow_up_days"]
    for step in PATH[status]:
        set_status(conn, job_id, step, why if step == "shortlisted" else "", follow_up)
    # Spread the funnel over the time the search has been running, so the rates mean something.
    if status not in ("new", "passed", "shortlisted"):
        conn.execute("UPDATE jobs SET ready_at = ? WHERE id = ? AND ready_at IS NOT NULL", (_stamp(days * 0.9), job_id))
        conn.execute("UPDATE jobs SET applied_at = ?, status_changed_at = ? WHERE id = ? AND applied_at IS NOT NULL",
                     (_stamp(days * 0.8), _stamp(days * 0.8), job_id))
        conn.execute("UPDATE jobs SET response_at = ? WHERE id = ? AND response_at IS NOT NULL", (_stamp(days * 0.4), job_id))
    return job_id


def load(conn, cfg: dict) -> str:
    """Replace whatever the database holds with the demo. Callers must have checked this is the example."""
    _clear(conn)
    ids = {row[0]: _add_job(conn, cfg, row, index) for index, row in enumerate(JOBS, start=1)}

    # The real checker, on the deliberately bad draft and on the good one.
    for company, folder in (("Globex Automation", GLOBEX), ("Acme Robotics", ACME)):
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (ids[company],)).fetchone()
        report = checks.check_application(ROOT / folder, cfg, company, job["title"], job["description"])
        conn.execute("UPDATE jobs SET check_result = ? WHERE id = ?", (json.dumps(report), ids[company]))

    log_event(conn, ids["Acme Robotics"], REPLY_DETECTED,
              f"From Sam Lee <sam@acme-robotics.example> | Subject: Your application | Date: {_stamp(0.3)[:16].replace('T', ' ')} UTC")

    now_stamp = _stamp(0.2)
    for key, company, count, error in SOURCES:
        conn.execute(
            "INSERT INTO source_status (source_key, company, last_run, last_ok, last_error, last_count) VALUES (?, ?, ?, ?, ?, ?)",
            (key, company, now_stamp, None if error else now_stamp, error, count),
        )
    stats = {"partial": False, "sources": len(SOURCES) - 1, "failed": 1, "postings": sum(s[2] for s in SOURCES[:-1]),
             "new": 4, "rejected": {"title": 301, "location": 88, "score": 7}, "closed": 0, "new_ids": []}
    conn.execute("INSERT INTO runs (started_at, finished_at, stats) VALUES (?, ?, ?)", (_stamp(0.21), now_stamp, json.dumps(stats)))
    conn.execute("INSERT INTO briefings (ts, body) VALUES (?, ?)", (_stamp(0.1), BRIEFING))
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
