"""The dashboard server. Localhost only, because this data includes your whole job search.

Posting text comes from the internet, so the page never treats it as HTML, and
requests from other websites can neither read this data nor change it.
"""
import hashlib
import json
import re
import socket
import sqlite3
import statistics
import sys
import tomllib
import traceback
from collections.abc import Sequence
from datetime import date, datetime
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from . import checks, claude_code, confirm, deadline, doctor, facts, fill, mail, market, outlook, prep, profile, refresh, settings, store, tasks, workday
from . import score as scoring
from .cli import finish_job
from .discover import ghost_after_days, last_full_sweep, waiting_on_gone
from .store import (
    DEFAULT_FIX_ATTEMPTS,
    IS_EXAMPLE,
    REPLY_DISMISSED,
    ROOT,
    STATUSES,
    TAILOR_REQUESTED,
    changed_after_sending,
    connect,
    fix_attempts,
    get_job,
    job_dict,
    load_config,
    log_event,
    now,
    possible_replies,
    quiet_days_since,
    sent_copies,
    set_status,
)

STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SERVABLE_ROOTS = ("applications", "archive")
MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
HEARD_BACK = {"reply": "responded", "interview": "interviewing", "offer": "offer", "rejected": "rejected"}
# What the dashboard's own buttons set. Ready and needs_fix come only from the fact checker.
USER_STATUSES = ("applied", "passed", "ghosted", "withdrawn")
RECHECKABLE = ("ready", "needs_fix")
# Logged the first time you open a prospect, so the Prospects tab can show what you haven't looked at yet.
SEEN = "seen"
# Jobs that haven't gone out, and so the statuses Pass can be undone back to. Anything further along is Reopen's job.
NOT_SENT = ("new", "shortlisted", "needs_fix", "ready")
DEFAULT_MAX_PER_COMPANY = 3
# How alike two titles at one company must be to count as the same job, such as a second requisition of it.
SAME_TITLE = 0.9
SOON = 2  # Days. A deadline this close puts a job near the top of the Sluice.


def safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else ""


def add_manual_job(conn, cfg, company, title, url="", location="", description="") -> int:
    """A posting you found yourself always goes in, whatever the filters think, at the front of the line."""
    company, title = company.strip(), title.strip()
    if not company or not title:
        raise ValueError("Company and title are required.")
    url = safe_url(url)
    source_id = hashlib.sha1(f"{company}|{title}|{url}".encode(), usedforsecurity=False).hexdigest()[:16]
    existing = conn.execute(
        "SELECT id FROM jobs WHERE source_key = 'manual' AND source_id = ?", (source_id,)
    ).fetchone()
    if existing:
        return existing["id"]
    verdict = scoring.evaluate(title, location, "", description, {**cfg, "run": {**cfg["run"], "min_score": 0}}, company)
    ts = now()
    cursor = conn.execute(
        """INSERT INTO jobs (source_key, source_id, company, title, location, location_kind, url, description, comp,
               first_seen, last_seen, score, score_reasons, track, flags, status, status_changed_at, priority)
           VALUES ('manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, 1)""",
        (source_id, company, title, location, verdict.location_kind or "unknown", url, description, "", ts, ts,
         verdict.score, json.dumps(verdict.reasons or ["Added by you"]), verdict.track or "Added by you",
         json.dumps(verdict.flags), ts),
    )
    log_event(conn, cursor.lastrowid, "found", "Added by you")
    return cursor.lastrowid


def _enrich(row, cfg: dict, today: str, include_description: bool = False, swept_at: str | None = None) -> dict:
    job = job_dict(row, include_description)
    run = cfg["run"]
    job["days_since_applied"] = quiet_days_since(job["applied_at"])
    job["days_in_status"] = quiet_days_since(job["status_changed_at"])
    job["follow_up_due"] = bool(job["next_action_date"] and job["next_action_date"] <= today)
    job["quiet"] = job["status"] == "applied" and (job["days_since_applied"] or 0) >= run["quiet_days"]
    job["url"] = safe_url(job["url"])
    job["changed_since_check"] = _changed_since_check(job, cfg)
    # Once sent, the documents are a record, not a draft: nothing rebuilds or refreshes them.
    job["frozen"] = bool(job["applied_at"])
    job["changed_after_sending"] = changed_after_sending(row) if job["frozen"] else []
    job["sent_files"] = ([p.relative_to(ROOT).as_posix() for p in sent_copies(ROOT / job["app_folder"])]
                         if job["frozen"] and job["app_folder"] else [])
    # The whole row, because priority reads the description even when the page isn't sent it.
    job.update(scoring.freshness(dict(row), cfg, date.fromisoformat(today), swept_at))
    # The posting's own closing date first; the notes written from it are the fallback.
    noted, blockers = deadline.read_notes(ROOT / job["app_folder"]) if job["app_folder"] else (None, [])
    job["deadline"] = deadline.from_posting(row["description"] or "") or noted
    job["days_to_deadline"] = (date.fromisoformat(job["deadline"]) - date.fromisoformat(today)).days if job["deadline"] else None
    job["blockers"] = blockers if job["status"] in NOT_SENT else []
    return job


def _changed_since_check(job: dict, cfg: dict) -> list[str]:
    """Files that changed after the fact checker passed a draft you haven't sent, so the pass no longer covers them.
    The fact bank and the [guard] rules count too: a pass against a fact since taken back says nothing now."""
    result = job["check_result"] or {}
    checked = result.get("checked")
    if job["status"] != "ready" or not checked or not job["app_folder"]:
        return []
    return checks.changed_since(ROOT / job["app_folder"], checked) + checks.sources_changed(cfg, result.get("checked_sources"))


def _scam_alerts(alerts: list[dict]) -> dict[int, dict]:
    """The latest open scam warning that names each job's company, by job id."""
    by_job: dict[int, dict] = {}
    for alert in alerts:
        if alert["job_id"] is not None:
            by_job.setdefault(alert["job_id"], alert)
    return by_job


def _company_key(name: str) -> str:
    name = re.sub(r"\b(inc|incorporated|corp|corporation|llc|ltd|co|company)\b\.?", " ", (name or "").lower())
    return " ".join(re.findall(r"[a-z0-9]+", name))


def _title_key(title: str) -> str:
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    return " ".join("senior" if w == "sr" else w for w in words)


def _applied_by_company(conn) -> dict[str, list[dict]]:
    """Every application sent so far, grouped by employer, oldest first."""
    history: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT id, company, title, applied_at FROM jobs WHERE applied_at IS NOT NULL ORDER BY applied_at"):
        history.setdefault(_company_key(row["company"]), []).append(dict(row))
    return history


def _attach_history(job: dict, history: dict, limit: int) -> None:
    """How many times you've applied to this employer, and whether one of them was this same job under another listing."""
    sent = [a for a in history.get(_company_key(job["company"]), []) if a["id"] != job["id"]]
    job["applied_here"] = len(sent)
    job["company_limit"] = limit
    same = None
    if not job["applied_at"]:
        title = _title_key(job["title"])
        same = next((a for a in reversed(sent) if SequenceMatcher(None, _title_key(a["title"]), title).ratio() >= SAME_TITLE), None)
    job["same_title_applied"] = {"id": same["id"], "title": same["title"], "applied_at": same["applied_at"]} if same else None


def _status_before_pass(conn, job_id: int) -> str | None:
    """What a passed job was before you passed on it, if that was a job not yet sent. None means Pass can't be undone."""
    marks = ", ".join("?" * len(STATUSES))
    kinds = [r[0] for r in conn.execute(
        f"SELECT kind FROM events WHERE job_id = ? AND kind IN ({marks}) ORDER BY id DESC", (job_id, *STATUSES))]
    if not kinds or kinds[0] != "passed":
        return None
    before = kinds[1] if len(kinds) > 1 else "new"  # A job found and passed has no status event before the pass.
    return before if before in NOT_SENT else None


def _deadline_text(job: dict) -> str:
    days = job["days_to_deadline"]
    if days is None:
        return ""
    when = date.fromisoformat(job["deadline"])
    label = f"{when:%b} {when.day}"
    if days < 0:
        return f"Its stated deadline, {label}, has passed: check the posting is still open."
    if days == 0:
        return f"Apply today: the posting gives {label}."
    if days == 1:
        return f"Apply by tomorrow, {label}."
    return f"Apply by {label}, in {days} days."


def _history_text(job: dict) -> str:
    same = job.get("same_title_applied")
    if same:
        sent = date.fromisoformat(same["applied_at"][:10])
        return f"You applied for {same['title']} here on {sent:%b} {sent.day}: this may be another listing of it."
    if job.get("applied_here", 0) >= job.get("company_limit", DEFAULT_MAX_PER_COMPANY):
        return f"You've already applied here {job['applied_here']} times."
    return ""


def _attach_runs(job: dict, replies: dict, refreshes: dict, preps: dict, tries: dict, scams: dict | None = None) -> None:
    job["possible_reply"] = replies.get(job["id"])
    job["scam_alert"] = (scams or {}).get(job["id"])
    job["refresh"] = refreshes.get(job["id"])
    job["prep"] = preps.get(job["id"])
    job["fix_attempts"] = tries.get(job["id"], 0)
    if job["refresh"] and job["refresh"]["state"] == "running":
        job["changed_since_check"] = []  # A refresh rewrites the draft in place and checks it when it's done.


def _gone_text(job: dict, ghost_days: int) -> str:
    """What happens to a sent application whose posting came down, and when."""
    down = quiet_days_since(job["posting_closed_at"]) or 0
    since = {0: "today", 1: "yesterday"}.get(down, f"{down} days ago")
    if not ghost_days:
        return f"The posting came down {since} and you haven't heard. Mark it ghosted or rejected if you think it's filled."
    left = ghost_days - down
    when = "on the next sweep" if left <= 0 else "tomorrow" if left == 1 else f"in {left} days"
    return (f"The posting came down {since} and you haven't heard. It counts as ghosted {when} "
            "unless you log a reply or set a next step.")


def _orders(jobs: list[dict], fix_limit: int = DEFAULT_FIX_ATTEMPTS, alerts: Sequence[dict] = (), ghost_days: int = 0) -> list[dict]:
    """Today's to-do list, most urgent first."""
    orders = []
    for alert in alerts:
        # The sender and subject were written by whoever sent the mail, so the page shows them as text only.
        orders.append({"rank": 0, "kind": "Possible scam", "job_id": alert["job_id"], "alert_id": alert["id"],
                       "text": f"{alert['sender']}: {alert['subject'] or '(no subject)'}",
                       "detail": "; ".join(alert["reasons"]) + ". Don't reply, click or pay. Dismiss this if it's genuine."})
    for job in jobs:
        name = f"{job['company']}: {job['title']}"
        if job["scam_signs"] and job["status"] in NOT_SENT:
            orders.append({"rank": 0, "kind": "Possible scam", "job_id": job["id"], "text": name,
                           "detail": "The posting itself: " + "; ".join(job["scam_signs"]).lower()
                           + ". Real employers don't. Check it on the company's own site before you apply, or pass on it."})
        if job["possible_reply"]:
            orders.append({"rank": 0, "kind": "Possible reply", "job_id": job["id"], "text": name,
                           "detail": job["possible_reply"]["detail"]})
        if job["status"] in ("interviewing", "offer") and job["follow_up_due"]:
            orders.append({"rank": 0, "kind": "Act now", "job_id": job["id"], "text": name,
                           "detail": job["next_action"] or "Next step is due"})
        elif waiting_on_gone(job):
            orders.append({"rank": 2, "kind": "Posting down", "job_id": job["id"], "text": name,
                           "detail": _gone_text(job, ghost_days)})
        elif job["quiet"]:
            orders.append({"rank": 3, "kind": "Gone quiet", "job_id": job["id"], "text": name,
                           "detail": f"No reply in {job['days_since_applied']} days. Mark it ghosted, or try one last nudge."})
        elif job["status"] in ("applied", "responded") and job["follow_up_due"]:
            when = f"Applied {job['days_since_applied']} days ago." if job["days_since_applied"] is not None else ""
            orders.append({"rank": 1, "kind": "Follow up", "job_id": job["id"], "text": name,
                           "detail": f"{when} {job['next_action']}".strip()})
        elif job["status"] == "needs_fix":
            tries = job.get("fix_attempts", 0)
            detail = "The draft failed the assay. The next run retries it."
            if tries >= fix_limit:
                detail = (f"The draft failed the assay {tries} times, so the daily run has stopped retrying it. "
                          "Open it to see why, then use Tailor this one first to try again.")
            orders.append({"rank": 2, "kind": "Blocked", "job_id": job["id"], "text": name, "detail": detail})
    def soon(job):
        return job["days_to_deadline"] is not None and 0 <= job["days_to_deadline"] <= SOON

    def joined(*parts):
        return " ".join(part for part in parts if part)

    # The ones closing first lead, so a deadline is never cut off the end of the list.
    ready = sorted((j for j in jobs if j["status"] == "ready" and not j["posting_closed_at"]),
                   key=lambda j: (not soon(j), -j["rank"]))
    for job in ready[:5]:
        first = f"Check first: {job['blockers'][0]}" if job["blockers"] else ""
        if job["changed_since_check"]:
            # Not ready to send: the pass no longer covers what's on file.
            orders.append({"rank": 1 if soon(job) else 2, "kind": "Check again", "job_id": job["id"], "action": "recheck",
                           "text": f"{job['company']}: {job['title']}",
                           "detail": joined(_deadline_text(job), "Its files changed after the assay passed it, so check it again before you send.", first)})
            continue
        detail = joined(_deadline_text(job), first, _history_text(job)) or job["fit_reason"] or job["notes"] or "Read it through, then send."
        orders.append({"rank": 1 if soon(job) else 2, "kind": "Send", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}", "detail": detail})
    listed = {o["job_id"] for o in orders}
    closing = sorted((j for j in jobs if j["status"] in ("new", "shortlisted", "needs_fix") and soon(j) and j["id"] not in listed),
                     key=lambda j: (j["days_to_deadline"], -j["rank"]))
    for job in closing[:3]:
        orders.append({"rank": 1, "kind": "Closing soon", "job_id": job["id"], "text": f"{job['company']}: {job['title']}",
                       "detail": joined(_deadline_text(job), _history_text(job), "Tailor it now or pass.")})
        listed.add(job["id"])
    fresh = sorted((j for j in jobs if j["status"] == "new" and j["is_new"] and j["id"] not in listed), key=lambda j: -j["rank"])
    for job in fresh[:3]:
        posted = {0: "today", 1: "yesterday"}.get(job["age_days"], f"{job['age_days']} days ago")
        orders.append({"rank": 3, "kind": "New listing", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}",
                       "detail": joined(f"Posted {posted}, never reposted. Score {job['score']}.", _deadline_text(job), _history_text(job))})
    return sorted(orders, key=lambda o: o["rank"])


def _setup_orders(cfg: dict) -> list[dict]:
    """What a new workspace still has to change, first on the to-do list. The demo is the example on purpose, so it has none."""
    if IS_EXAMPLE:
        return []
    return [{"rank": 0, "kind": "Finish setup", "job_id": None, "text": todo["what"], "detail": todo["fix"], "tab": todo.get("tab")}
            for todo in doctor.workspace_todos(ROOT, cfg)]


def build_state(conn, cfg) -> dict:
    today = date.today().isoformat()
    rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC, first_seen DESC").fetchall()
    last_run = last_full_sweep(conn)
    swept_at = last_run["started_at"] if last_run else None
    jobs = [_enrich(r, cfg, today, swept_at=swept_at) for r in rows]
    replies, refreshes, preps, tries = possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn)
    alerts = mail.open_alerts(conn)
    scams = _scam_alerts(alerts)
    history = _applied_by_company(conn)
    limit = cfg.get("dashboard", {}).get("max_per_company", DEFAULT_MAX_PER_COMPANY)
    seen = {r[0] for r in conn.execute("SELECT DISTINCT job_id FROM events WHERE kind = ?", (SEEN,))}
    for job in jobs:
        _attach_runs(job, replies, refreshes, preps, tries, scams)
        _attach_history(job, history, limit)
        job["seen"] = job["id"] in seen

    applied =[j for j in jobs if j["applied_at"]]
    heard = [j for j in applied if j["response_at"]]
    # A rejection is hearing back, but it isn't progress, so replies and rejections are counted apart.
    answered = {r[0] for r in conn.execute("SELECT DISTINCT job_id FROM events WHERE kind IN ('responded', 'interviewing', 'offer')")}
    replied = [j for j in heard if j["id"] in answered or j["interview_at"] or j["offer_at"]]
    rejected = [j for j in applied if j["status"] == "rejected" and j not in replied]
    days_to_reply = [
        (datetime.fromisoformat(j["response_at"]) - datetime.fromisoformat(j["applied_at"])).days
        for j in replied
    ]
    this_week = [j for j in applied if (quiet_days_since(j["applied_at"]) or 0) < 7]
    radar = [j for j in jobs if j["status"] == "new"]

    stats = {
        "ready": sum(j["status"] == "ready" for j in jobs),
        "awaiting": sum(j["status"] == "applied" for j in jobs),
        "follow_ups": sum(j["status"] in ("applied", "responded") and j["follow_up_due"] for j in jobs),
        "applied": len(applied),
        "applied_week": len(this_week),
        "heard": len(heard),
        "response_rate": round(100 * len(heard) / len(applied)) if applied else None,
        "replied": len(replied),
        "rejected": len(rejected),
        "ghosted": sum(j["status"] == "ghosted" and bool(j["applied_at"]) for j in jobs),
        "reply_rate": round(100 * len(replied) / len(applied)) if applied else None,
        "median_days_to_reply": statistics.median(days_to_reply) if days_to_reply else None,
        "interviews": sum(bool(j["interview_at"]) for j in jobs),
        "fresh": sum(j["is_new"] for j in radar),
        "possible_ghosts": sum(j["ghost_risk"] for j in radar),
        "to_triage": len(radar),
    }
    # Each job once, at the stage it's at now, so a resume that went out counts as sent and no longer as ready.
    at = lambda *statuses: sum(j["status"] in statuses for j in jobs)
    funnel = [
        {"stage": "Prospects", "count": at("new")},
        {"stage": "Being tailored", "count": at("shortlisted", "needs_fix")},
        {"stage": "Ready to send", "count": at("ready")},
        {"stage": "Waiting to hear", "count": at("applied")},
        {"stage": "Replied", "count": at("responded")},
        {"stage": "Interviewing", "count": at("interviewing")},
        {"stage": "Offer", "count": at("offer")},
    ]
    closed_labels = {"rejected": "rejected", "ghosted": "ghosted", "withdrawn": "withdrawn", "passed": "passed", "closed": "posting closed"}
    closed = [{"label": label, "count": at(status)} for status, label in closed_labels.items() if at(status)]
    brief = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1").fetchone()
    briefing = dict(brief) if brief else None
    if briefing:
        # The report names jobs as they stood when it was written, so say how much has moved since.
        briefing["since"] = {kind: count for kind, count in conn.execute(
            "SELECT kind, COUNT(DISTINCT job_id) FROM events WHERE ts > ? AND kind IN ('applied', 'passed') GROUP BY kind",
            (briefing["ts"],))}
    source_rows = [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY company")]
    return {
        "jobs": jobs,
        "stats": stats,
        "funnel": funnel,
        "closed": closed,
        "orders": _setup_orders(cfg) + _orders(jobs, cfg["run"].get("fix_attempts", DEFAULT_FIX_ATTEMPTS), alerts, ghost_after_days(cfg)),
        "alerts": alerts,
        "sources": source_rows,
        "manual_check": cfg.get("manual_check", []),
        "last_run": last_run,
        "briefing": briefing,
        "before_send": cfg.get("dashboard", {}).get("before_send", []),
        "usage": claude_code.usage(conn),
        "tasks": tasks.latest(conn),
        # Runs this workspace can't start at all yet, with why, so their buttons say so instead of being pressed.
        "not_ready": {kind: why for kind in tasks.LABELS if (why := tasks.not_ready(kind))},
        "demo": IS_EXAMPLE,
    }


def job_detail(conn, job_id: int, cfg: dict) -> dict:
    last_run = last_full_sweep(conn)
    job = _enrich(get_job(conn, job_id), cfg, date.today().isoformat(), include_description=True,
                  swept_at=last_run["started_at"] if last_run else None)
    _attach_runs(job, possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn),
                 _scam_alerts(mail.open_alerts(conn)))
    _attach_history(job, _applied_by_company(conn), cfg.get("dashboard", {}).get("max_per_company", DEFAULT_MAX_PER_COMPANY))
    job["seen"] = bool(conn.execute("SELECT 1 FROM events WHERE job_id = ? AND kind = ?", (job_id, SEEN)).fetchone())
    job["can_unpass"] = job["status"] == "passed" and _status_before_pass(conn, job_id) is not None
    job["fix_limit"] = cfg["run"].get("fix_attempts", DEFAULT_FIX_ATTEMPTS)
    job["can_refresh"] = job["status"] in refresh.REFRESHABLE and bool(job["app_folder"])
    job["can_recheck"] = job["status"] in RECHECKABLE and bool(job["app_folder"]) and not IS_EXAMPLE
    # Offered even without an application folder, so the button can say what's missing.
    job["can_prep"] = job["status"] in prep.PREPPABLE
    job["events"] =[dict(r) for r in conn.execute(
        "SELECT ts, kind, detail FROM events WHERE job_id = ? AND kind != ? ORDER BY id DESC", (job_id, SEEN)
    )]
    job["notes_md"] = ""
    job["prep_file"] = ""
    job["fill_sheet"] = ""
    job["can_fill"] = False
    if job["app_folder"]:
        folder = ROOT / job["app_folder"]
        path = folder / "notes.md"
        if path.exists():
            job["notes_md"] = path.read_text(encoding="utf-8")
        if (folder / prep.BRIEF).exists():
            job["prep_file"] = f"{job['app_folder']}/{prep.BRIEF}"
        if (folder / fill.SHEET).exists():
            job["fill_sheet"] = f"{job['app_folder']}/{fill.SHEET}"
        # The sheet is for filling the form, so a sent job doesn't get a new one.
        job["can_fill"] = (folder / "resume.md").exists() and (ROOT / fill.PASTE_SHEET).exists() and not job["frozen"] and not IS_EXAMPLE
    row = get_job(conn, job_id)
    job["autofill"] = workday.states(conn).get(job_id)
    job["autofill_refusal"] = workday.refusal(conn, row, cfg)
    job["can_autofill"] = job["autofill_refusal"] is None or (job["autofill"] or {}).get("state") == "running"
    job["autofill_log"] = f"{job['app_folder']}/{workday.LOG}" if job["app_folder"] and (ROOT / job["app_folder"] / workday.LOG).exists() else ""
    return job


def _reopen_target(job, cfg: dict) -> str:
    """Where a reopened job goes back to. Ready only if the assay's last verdict was a pass and nothing has changed since:
    having once been ready says nothing about the draft on disk now."""
    if job["applied_at"]:
        return "applied"
    if not job["app_folder"]:
        return "shortlisted"
    if not job["check_result"]:
        return "shortlisted"
    return "needs_fix" if checks.not_covered(ROOT / job["app_folder"], cfg, job["check_result"]) else "ready"


def apply_action(conn, job_id: int, body: dict, cfg: dict) -> None:
    action = body.get("action")
    note = str(body.get("note") or "").strip()[:2000]
    follow_up = cfg["run"]["follow_up_days"]
    job = get_job(conn, job_id)

    if action == "status":
        if body.get("status") not in USER_STATUSES:
            raise ValueError("That status can't be set from the dashboard. A draft becomes ready only by passing the assay.")
        set_status(conn, job_id, body["status"], note, follow_up)
    elif action == "heard_back":
        kind = body.get("kind")
        if not isinstance(kind, str) or kind not in HEARD_BACK:
            raise ValueError("Unknown kind of reply.")
        set_status(conn, job_id, HEARD_BACK[kind], note, follow_up)
    elif action == "dismiss_reply":
        log_event(conn, job_id, REPLY_DISMISSED, note)
    elif action == "tailor_next":
        conn.execute("UPDATE jobs SET priority = 1 WHERE id = ?", (job_id,))
        # Also the marker that gives a draft the daily run gave up on a fresh set of tries.
        log_event(conn, job_id, TAILOR_REQUESTED, "You asked for this one next")
        if job["status"] in ("new", "passed", "closed"):
            set_status(conn, job_id, "shortlisted", "You asked for this one next", follow_up)
    elif action == "recheck":
        if IS_EXAMPLE:
            raise ValueError("The demo doesn't rebuild documents.")
        if job["status"] not in RECHECKABLE or not job["app_folder"]:
            raise ValueError("Only a draft you haven't sent can be checked again.")
        if (refresh.states(conn).get(job_id) or {}).get("state") == "running":
            raise ValueError("This resume is being refreshed, and that run checks it when it's done.")
        finish_job(conn, cfg, job_id)
    elif action == "fill_sheet":
        if IS_EXAMPLE:
            raise ValueError("The demo doesn't write fill sheets.")
        if job["applied_at"]:
            raise ValueError("This job was sent, so its folder is a record. A second application is a new job.")
        if not job["app_folder"]:
            raise ValueError("No application folder yet, so there's no tailored resume to merge.")
        try:
            report = fill.make_sheet(ROOT / job["app_folder"], job["company"], job["title"], job["url"],
                                     source=fill.posting_source(job["source_key"], job["url"]),
                                     unchecked=checks.not_covered(ROOT / job["app_folder"], cfg, job["check_result"]))
        except FileNotFoundError as err:
            raise ValueError(str(err)) from err
        log_event(conn, job_id, "fill_sheet", fill.summary(report))
    elif action == "autofill":
        workday.start(conn, job_id, cfg)
    elif action == "refresh_resume":
        refresh.start(conn, job_id)
    elif action == "interview_prep":
        prep.start(conn, job_id)
    elif action == "reopen":
        set_status(conn, job_id, _reopen_target(job, cfg), "Reopened", follow_up)
    elif action == "unpass":
        before = _status_before_pass(conn, job_id) if job["status"] == "passed" else None
        if before is None:
            raise ValueError("Only a job you passed on before sending it can be put back. Use Reopen instead.")
        set_status(conn, job_id, before, "Pass undone", follow_up)
    elif action == "seen":
        if not conn.execute("SELECT 1 FROM events WHERE job_id = ? AND kind = ?", (job_id, SEEN)).fetchone():
            log_event(conn, job_id, SEEN)
    elif action == "note":
        conn.execute("UPDATE jobs SET notes = ? WHERE id = ?", (str(body.get("notes") or "")[:5000], job_id))
    elif action == "next_action":
        when = str(body.get("date") or "") or None
        if when and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            raise ValueError("Bad date.")
        conn.execute(
            "UPDATE jobs SET next_action = ?, next_action_date = ? WHERE id = ?",
            (str(body.get("text") or "")[:300], when, job_id),
        )
        log_event(conn, job_id, "next_action", f"{body.get('text', '')} {when or ''}".strip())
    else:
        raise ValueError(f"Unknown action {action!r}")


def resolve_file(rel: str) -> Path | None:
    """Only finished application documents can be served, never the database or anything else.

    Both sides are resolved before they're compared, since one folder can be written more than one way,
    such as a Windows short name or a path with ".." in it.
    """
    root = ROOT.resolve()
    target = (root / rel).resolve()
    allowed = any(target.is_relative_to(root / folder) for folder in SERVABLE_ROOTS)
    if allowed and target.is_file() and target.suffix in MIME:
        return target
    return None


class Handler(BaseHTTPRequestHandler):
    server_version = "Pyrite"
    sys_version = ""

    def log_message(self, *args):
        pass

    def _host_ok(self) -> bool:
        # Refusing unknown Host headers stops DNS rebinding from reading this data.
        host = re.sub(r":\d+$", "", self.headers.get("Host", ""))
        try:
            extra = load_config().get("dashboard", {}).get("allowed_hosts", [])
        except (OSError, tomllib.TOMLDecodeError):
            extra = []  # Localhost still gets through, so the page can say what's wrong with the file.
        return host in ALLOWED_HOSTS or host in extra

    def _guarded(self, handle) -> None:
        """Answer every request, even a failed one. A dropped connection tells the page nothing."""
        try:
            handle()
        except tomllib.TOMLDecodeError as err:
            self._json({"error": f"profile/search.toml can't be read, so nothing loaded. Fix it and reload: {err}"}, 500)
        except sqlite3.OperationalError as err:
            if "locked" in str(err) or "busy" in str(err):
                self._json({"error": "The database is busy, probably with a sweep. Try again in a moment."}, 503)
            else:
                self._json({"error": f"Database error: {err}"}, 500)
        except ConnectionError:
            pass  # The browser went away mid-answer.
        except Exception as err:
            traceback.print_exc()
            self._json({"error": f"Something went wrong on the server. {type(err).__name__}: {err}"}, 500)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, default=str).encode(), "application/json")

    def do_GET(self):
        self._guarded(self._get)

    def do_POST(self):
        self._guarded(self._post)

    def _get(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        path = urlparse(self.path).path
        try:
            if path in STATIC_FILES:
                name, mime = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), mime)
            if path == "/api/state":
                conn = connect()
                try:
                    return self._json(build_state(conn, load_config()))
                finally:
                    conn.close()
            if path == "/api/settings":
                return self._json(settings.view())
            if path == "/api/facts":
                return self._json(facts.view())
            if path == "/api/profile":
                return self._json({**profile.view(), "history": profile.history()})
            if path == "/api/industries":
                conn = connect()
                try:
                    return self._json(market.view(conn, load_config()))
                finally:
                    conn.close()
            match = re.fullmatch(r"/api/job/(\d+)", path)
            if match:
                conn = connect()
                try:
                    return self._json(job_detail(conn, int(match.group(1)), load_config()))
                finally:
                    conn.close()
            if path.startswith("/files/"):
                target = resolve_file(unquote(path[len("/files/"):]))
                if not target:
                    return self._json({"error": "not found"}, 404)
                # Headers are Latin-1 only, so a name outside it travels percent-encoded, with a plain fallback.
                plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", target.name)
                extra = {"Content-Disposition": f"inline; filename=\"{plain}\"; filename*=UTF-8''{quote(target.name)}"}
                return self._send(200, target.read_bytes(), MIME[target.suffix], extra)
            return self._json({"error": "not found"}, 404)
        except KeyError as err:
            return self._json({"error": str(err)}, 404)

    def _post(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        # A website can't send JSON here without a preflight this server never approves.
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host"):
            return self._json({"error": "bad origin"}, 403)
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json({"error": "json only"}, 415)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                # read(-1) would wait for a close that never comes, holding a thread.
                return self._json({"error": "bad request"}, 400)
            if length > 500_000:
                return self._json({"error": "too large"}, 413)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return self._json({"error": "bad request"}, 400)

        path = urlparse(self.path).path
        if path in PROFILE_WRITES:
            try:
                return self._json(PROFILE_WRITES[path](body))
            except confirm.CodeNeeded as err:
                # 428 Precondition Required: the page asks for the code that was just sent, then sends the change again.
                return self._json(err.payload, 428)
            except confirm.CodeError as err:
                return self._json({"error": str(err), "code_failed": True}, 403)
            except settings.Conflict as err:
                return self._json({"error": str(err)}, 409)
            except ValueError as err:
                return self._json({"error": str(err)}, 400)
        conn = connect()
        cfg = load_config()
        try:
            if path == "/api/jobs":
                job_id = add_manual_job(
                    conn, cfg, str(body.get("company", "")), str(body.get("title", "")),
                    str(body.get("url", "")), str(body.get("location", "")), str(body.get("description", "")),
                )
                conn.commit()
                return self._json({"id": job_id}, 201)
            if path == "/api/run":
                tasks.start(conn, str(body.get("kind") or ""))
                return self._json({"ok": True}, 202)
            if path == "/api/industries/outlook":
                outlook.start(cfg, str(body.get("name") or ""))
                return self._json({"ok": True}, 202)
            match = re.fullmatch(r"/api/job/(\d+)/action", path)
            if match:
                apply_action(conn, int(match.group(1)), body, cfg)
                conn.commit()
                return self._json({"ok": True})
            match = re.fullmatch(r"/api/alert/(\d+)/dismiss", path)
            if match:
                mail.dismiss_alert(conn, int(match.group(1)))
                conn.commit()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except (ValueError, KeyError) as err:
            conn.rollback()
            return self._json({"error": str(err)}, 400)
        finally:
            conn.close()


def _save_facts(body: dict) -> dict:
    """The Facts tab's save. Approving a term or unlisting a "Do not use" item needs a code, as on the Profile tab."""
    key, text = body.get("file"), body.get("text")
    # The demo refuses every save, so it shouldn't send a code first.
    if key in facts.FILES and isinstance(text, str) and not store.IS_EXAMPLE:
        current = facts._read(key)
        # A stale form is refused before any code is sent, since that save can't go through anyway.
        if body.get("version") != facts._version(current):
            raise settings.Conflict("This file changed after you opened it, so nothing was saved. Reload the Facts tab to see the latest.")
        confirm.require({key: text}, {key: current}, {key: body.get("version")}, body.get("request_id"), body.get("code"))
    return facts.save(body)


def _save_profile(body: dict) -> dict:
    changes, based_on = body.get("changes"), body.get("based_on")
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's profile can't be changed.")
    if not isinstance(changes, dict) or not changes or not isinstance(based_on, dict):
        raise ValueError("Nothing to save.")
    for key, text in changes.items():
        if key not in profile.FILES:
            raise ValueError("That isn't a file the Profile tab can change.")
        if not isinstance(text, str):
            raise ValueError(f"Nothing to save for {profile.FILES[key]}.")
    current = {key: profile.read(key) for key in changes}
    # A stale form is refused before any code is sent, since that save can't go through anyway.
    profile.refuse_stale(current, based_on)
    confirm.require(changes, current, based_on, body.get("request_id"), body.get("code"))
    profile.write(changes, based_on, str(body.get("reason") or ""))
    return {**profile.view(), "history": profile.history()}


def _profile_code(body: dict) -> dict:
    """Send a waiting change's code again, or give up on it."""
    if body.get("action") == "resend":
        return confirm.resend(body.get("request_id"))
    if body.get("action") == "cancel":
        confirm.cancel(body.get("request_id"))
        return {"ok": True}
    raise ValueError("Ask to resend or cancel a code.")


# Saves that change the profile. Each refuses a stale form, and any that loosens a check asks for a code first.
PROFILE_WRITES = {
    "/api/settings": settings.save,
    "/api/facts": _save_facts,
    "/api/profile": _save_profile,
    "/api/profile/code": _profile_code,
}


class DashboardServer(ThreadingHTTPServer):
    """The dashboard's server, which won't share its port.

    HTTPServer turns on SO_REUSEADDR. On Windows that lets a second process listen on a port that's already taken, so a
    second dashboard would start without complaint and requests would go to either one. Any other program on this
    machine could do the same to answer in the dashboard's place. Windows gets an exclusive port instead, and elsewhere
    SO_REUSEADDR only lets a restart reuse the port of one that just closed.
    """
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port: int) -> DashboardServer:
    try:
        return DashboardServer(("127.0.0.1", port), Handler)
    except OSError as err:
        raise SystemExit(f"Port {port} is already in use, so the dashboard didn't start ({err.strerror or err}).\n"
                         f"If Pyrite is already running, open http://127.0.0.1:{port}. Otherwise pick another port with --port.") from None


def serve(port: int = 8787) -> None:
    connect().close()
    server = make_server(port)
    print(f"Pyrite: http://127.0.0.1:{port}\nOpen that in your browser. The dashboard runs while this window is open, "
          "and Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl+C is how a dashboard started by hand is meant to stop, so it isn't an error worth a traceback.
        print("Stopped.", flush=True)
    finally:
        server.server_close()
