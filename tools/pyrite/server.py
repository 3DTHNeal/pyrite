"""The dashboard server. Localhost only, because this data includes your whole job search.

Posting text comes from the internet, so the page never treats it as HTML, and
requests from other websites can neither read this data nor change it.
"""
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import statistics
import sys
import threading
import time
import tomllib
import traceback
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import date, datetime
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import (
    backup,
    checks,
    claude_code,
    confirm,
    culture,
    deadline,
    discover,
    doctor,
    facts,
    fill,
    gaps,
    launch,
    link,
    mail,
    market,
    options,
    outlook,
    prep,
    profile,
    refresh,
    schedule,
    settings,
    signals,
    steps,
    store,
    tasks,
    update,
    words,
    workday,
    workspace,
)
from . import score as scoring
from .cli import finish_job
from .discover import ghost_after_days, last_full_sweep, waiting_on_gone
from .sources import find_comp
from .store import (
    DEFAULT_FIX_ATTEMPTS,
    IS_EXAMPLE,
    REPLY_DISMISSED,
    ROOT,
    STATUSES,
    TAILOR_REQUESTED,
    connect,
    fix_attempts,
    get_job,
    job_dict,
    load_config,
    log_event,
    now,
    possible_replies,
    quiet_days_since,
    sent_changes,
    sent_copies,
    set_status,
    shorten,
)

STATIC = Path(__file__).parent / "static"
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SERVABLE_ROOTS = ("applications", "archive")
# Where setup suggests making your workspace: beside the code folder, as docs/setup.md does.
SETUP_FOLDER = "my-job-search"
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
    "/static/profile.js": ("profile.js", "text/javascript; charset=utf-8"),
    # Each Profile section's editor is its own file, and page() loads every one of them.
    **{f"/static/profile/{path.name}": (f"profile/{path.name}", "text/javascript; charset=utf-8")
       for path in sorted((STATIC / "profile").glob("*.js"))},
    # The mark, its two animations and the stage icons, drawn by art/icons/build.py.
    **{f"/static/icons/{path.name}": (f"icons/{path.name}", "image/png") for path in sorted((STATIC / "icons").glob("*.png"))},
}
# The line in index.html that page() replaces with a script tag for each section's editor.
SECTIONS_MARK = "<!-- profile sections -->"


def page() -> bytes:
    """index.html with a script tag for every file in static/profile/, in place of SECTIONS_MARK. No section's script
    uses another's, so their order doesn't matter, and adding a section adds no line to a list here."""
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    tags = "\n".join(f'<script src="{src}"></script>' for src in STATIC_FILES if src.startswith("/static/profile/"))
    return text.replace(SECTIONS_MARK, tags, 1).encode()
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
# Days. A deadline this close is urgent: first on the to-do list. One within [run] decide_days is on it.
SOON = 2
# A to-do item shows the start of a long fit reason. The job panel has all of it.
ORDER_REASON = 200
# Days after applying when a short note to the hiring manager is due, until one is logged.
REACH_OUT_DAYS = range(1, 4)
# The longest text each box on the page takes. The page stops typing at these, and the server refuses longer rather
# than cutting it short without saying so.
MAX_NOTE = 2000  # The note that goes with a status change.
MAX_NOTES = 5000  # Your notes on a job.
MAX_NEXT_STEP = 300
MAX_NAME = 200  # A company, title or location you add by hand.
MAX_LINK = 2000  # A posting's web address. Anything longer was pasted into the wrong box.
# A job's or an alert's number. Longer ones can't be one, and SQLite can't even look them up.
JOB_ID = r"(\d{1,18})"
# Tells this server from the one that replaces it after an update, so the page knows when to reload.
SERVER_ID = f"{os.getpid()}-{time.time_ns()}"


def safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else ""


def _same_posting(url: str) -> str:
    """A link in the form two copies of it share: no fragment, no trailing slash, and the host in lower case."""
    parts = urlparse(url.strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}?{parts.query}" if parts.netloc else ""


def tracked_by_url(conn, url: str):
    """The job already tracked at this link, whoever found it, or None. Two postings can share a title, but not a link."""
    wanted = _same_posting(safe_url(url))
    if not wanted:
        return None
    rows = conn.execute("SELECT id, company, title, status, url FROM jobs WHERE url != '' ORDER BY id").fetchall()
    return next((row for row in rows if _same_posting(row["url"]) == wanted), None)


def _text(body: dict[str, Any], key: str, label: str, limit: int) -> str:
    """A text field from a request, trimmed. Anything but text, or text over `limit`, is refused rather than stored
    some other way or cut short."""
    value = body.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{label} should be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{label} can be at most {limit:,} characters, and that's {len(value):,}, so nothing was saved. Shorten it and try again.")
    return value


def add_manual_job(conn, cfg, company, title, url="", location="", description="") -> int:
    """A posting you found yourself always goes in, whatever the filters think, at the front of the line. One already
    tracked at the same link isn't added twice: that job's number comes back instead. Without a link, the same company,
    title, place and text is the same posting, but another place or other text is another opening, so it goes in too."""
    company, title = company.strip(), title.strip()
    if not company or not title:
        raise ValueError("Company and title are required.")
    for label, value in (("Company", company), ("Title", title), ("Location", location.strip())):
        if len(value) > MAX_NAME:
            raise ValueError(f"{label} is over {MAX_NAME} characters. Shorten it, and paste the rest into the description.")
    url = safe_url(url)
    known = tracked_by_url(conn, url)
    if known:
        return known["id"]
    text = hashlib.sha1(description.encode(), usedforsecurity=False).hexdigest()
    source_id = hashlib.sha1(f"{company}|{title}|{url}|{location}|{text}".encode(), usedforsecurity=False).hexdigest()[:16]
    existing = conn.execute(
        """SELECT id FROM jobs WHERE source_key = 'manual' AND (source_id = ?
               OR (company = ? AND title = ? AND url = ? AND location = ? AND description = ?))""",
        (source_id, company, title, url, location, description),
    ).fetchone()
    if existing:
        return existing["id"]
    # Scored in full even where a filter would refuse it, so the score says how it compares rather than a flat 0.
    verdict = scoring.evaluate(title, location, "", description, cfg, company, added=True)
    ts = now()
    cursor = conn.execute(
        """INSERT INTO jobs (source_key, source_id, company, title, location, location_kind, url, description, comp,
               first_seen, last_seen, score, score_reasons, track, flags, status, status_changed_at, priority)
           VALUES ('manual', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, 1)""",
        (source_id, company, title, location, verdict.location_kind, url, description, find_comp(description, title), ts, ts,
         verdict.score, json.dumps(verdict.reasons), verdict.track or scoring.ADDED_TRACK,
         json.dumps(verdict.flags), ts),
    )
    log_event(conn, cursor.lastrowid, "found", "Added by you")
    return cursor.lastrowid


def _enrich(row, cfg: dict[str, Any], today: str, include_description: bool = False, swept_at: str | None = None,
            context: signals.Context | None = None) -> dict[str, Any]:
    """One job as the page shows it. `context` is what judging pay and rarity needs to know about the other jobs:
    without it, those two are left out."""
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
    changed, acknowledged = sent_changes(row) if job["frozen"] else ([], False)
    job["changed_after_sending"] = [] if acknowledged else changed
    # Changes you've said are fine. They show again, as changed_after_sending, if the folder changes after that.
    job["acknowledged_changes"] = changed if acknowledged else []
    job["sent_files"] = ([p.relative_to(ROOT).as_posix() for p in sent_copies(ROOT / job["app_folder"])]
                         if job["frozen"] and job["app_folder"] else [])
    # The whole row, because priority reads the description even when the page isn't sent it.
    job.update(scoring.freshness(dict(row), cfg, date.fromisoformat(today), swept_at))
    # The deadline, pay, skills' ages and rarity, with what pay and rarity add to the priority.
    context = context or signals.alone(cfg, date.fromisoformat(today))
    signals.apply(job, signals.read(dict(row), cfg, context, ROOT / job["app_folder"] if job["app_folder"] else None))
    if job["status"] not in NOT_SENT:
        job["blockers"], job["decide_soon"] = [], False
    return job


def _changed_since_check(job: dict[str, Any], cfg: dict[str, Any]) -> list[str]:
    """Files that changed after the fact checker passed a draft you haven't sent, so the pass no longer covers them.
    The fact bank and the [guard] rules count too: a pass against a fact since taken back says nothing now."""
    result = job["check_result"] or {}
    checked = result.get("checked")
    if job["status"] != "ready" or not checked or not job["app_folder"]:
        return []
    return checks.changed_since(ROOT / job["app_folder"], checked) + checks.sources_changed(cfg, result.get("checked_sources"))


def _scam_alerts(alerts: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """The latest open scam warning that names each job's company, by job id."""
    by_job: dict[int, dict[str, Any]] = {}
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


def _applied_by_company(conn) -> dict[str, list[dict[str, Any]]]:
    """Every application sent so far, grouped by employer, oldest first."""
    history: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute("SELECT id, company, title, applied_at FROM jobs WHERE applied_at IS NOT NULL ORDER BY applied_at"):
        history.setdefault(_company_key(row["company"]), []).append(dict(row))
    return history


def _attach_history(job: dict[str, Any], history: dict[str, Any], limit: int) -> None:
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


def _deadline_text(job: dict[str, Any]) -> str:
    days = job["days_to_deadline"]
    if days is None:
        return ""
    label = deadline.label(job["deadline"])
    if days < 0 and not job.get("deadline_firm", True):
        return f"It took applications at least until {label}, so it may close any day."
    if days < 0:
        return f"Its stated deadline, {label}, has passed: check the posting is still open."
    if days == 0:
        return f"Apply today: the posting gives {label}."
    if days == 1:
        return f"Apply by tomorrow, {label}."
    return f"Apply by {label}, in {days} days."


def _history_text(job: dict[str, Any]) -> str:
    same = job.get("same_title_applied")
    if same:
        sent = date.fromisoformat(same["applied_at"][:10])
        return f"You applied for {same['title']} here on {sent:%b} {sent.day}: this may be another listing of it."
    if job.get("applied_here", 0) >= job.get("company_limit", DEFAULT_MAX_PER_COMPANY):
        return f"You've already applied here {job['applied_here']} times."
    return ""


def _attach_runs(job: dict[str, Any], replies: dict[int, dict[str, Any]], refreshes: dict[int, dict[str, Any]],
                 preps: dict[int, dict[str, Any]], tries: dict[int, int], scams: dict[int, dict[str, Any]] | None = None) -> None:
    job["possible_reply"] = replies.get(job["id"])
    job["scam_alert"] = (scams or {}).get(job["id"])
    job["refresh"] = refreshes.get(job["id"])
    job["prep"] = preps.get(job["id"])
    job["fix_attempts"] = tries.get(job["id"], 0)
    if job["refresh"] and job["refresh"]["state"] == "running":
        job["changed_since_check"] = []  # A refresh rewrites the draft in place and checks it when it's done.


def _gone_text(job: dict[str, Any], ghost_days: int) -> str:
    """What happens to a sent application whose posting came down, and when."""
    down = quiet_days_since(job["posting_closed_at"]) or 0
    since = {0: "today", 1: "yesterday"}.get(down, f"{down} days ago")
    if not ghost_days:
        return f"The posting came down {since} and you haven't heard. Mark it ghosted or rejected if you think it's filled."
    left = ghost_days - down
    when = "on the next sweep" if left <= 0 else "tomorrow" if left == 1 else f"in {left} days"
    return (f"The posting came down {since} and you haven't heard. It counts as ghosted {when} "
            "unless you log a reply or set a next step.")


def _reach_out_order(waiting: list[dict[str, Any]]) -> dict[str, Any]:
    """One to-do item for every application due a note to the hiring manager, so a busy week of applying doesn't fill
    the list with them. It names the one whose window closes first and counts the rest."""
    waiting = sorted(waiting, key=lambda j: (-j["days_since_applied"], j["applied_at"] or ""))
    first = waiting[0]
    detail = (f"Applied {_days(first['days_since_applied'])} ago with no outreach logged. Send the hiring manager a short note, "
              "then log it with Reached out.")
    others = [job["company"] for job in waiting[1:]]
    if others:
        # Each employer named once, and "more" counts the applications at the ones not named, so it all adds up.
        shown = list(dict.fromkeys(others))[:4]
        rest = sum(company not in shown for company in others)
        named = ", ".join(shown) + (f" and {rest} more" if rest else "")
        detail += f" {len(others)} more {'is' if len(others) == 1 else 'are'} due one too: {named}."
    return {"rank": 3, "kind": "Reach out", "job_id": first["id"], "text": f"{first['company']}: {first['title']}", "detail": detail}


def _orders(jobs: list[dict[str, Any]], fix_limit: int = DEFAULT_FIX_ATTEMPTS, alerts: Sequence[dict[str, Any]] = (), ghost_days: int = 0,
            reach_out: bool = True) -> list[dict[str, Any]]:
    """Today's to-do list, most urgent first. `reach_out` False leaves out the reminders to write to hiring managers."""
    orders = []
    reach: list[dict[str, Any]] = []
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
            when = f"Applied {_days(job['days_since_applied'])} ago." if job["days_since_applied"] is not None else ""
            orders.append({"rank": 1, "kind": "Follow up", "job_id": job["id"], "text": name,
                           "detail": f"{when} {job['next_action']}".strip()})
        elif job["status"] == "applied" and not job.get("reached_out") and job["days_since_applied"] in REACH_OUT_DAYS:
            reach.append(job)
        elif job["status"] == "needs_fix":
            tries = job.get("fix_attempts", 0)
            detail = "The draft failed the assay. The next run retries it."
            if tries >= fix_limit:
                detail = (f"The draft failed the assay {tries} times, so the daily run has stopped retrying it. "
                          "Open it to see why, then use Tailor this one first to try again.")
            orders.append({"rank": 2, "kind": "Blocked", "job_id": job["id"], "text": name, "detail": detail})
    def soon(job):
        """Urgent: closing within SOON days, or a floor date already past."""
        days = job["days_to_deadline"]
        return bool(job.get("decide_soon")) and days is not None and days <= SOON

    def joined(*parts):
        return " ".join(part for part in parts if part)

    # The ones closing first lead, so a deadline is never cut off the end of the list.
    ready = sorted((j for j in jobs if j["status"] == "ready" and not j["posting_closed_at"]),
                   key=lambda j: (not soon(j), -j["rank"]))
    for job in ready[:5]:
        # The short label, since the whole reason is in the job's panel.
        labels = job.get("blocker_labels") or {}
        label = labels.get(job["blockers"][0], job["blockers"][0]) if job["blockers"] else ""
        first = f"Check first: {label}{'' if label[-1:] in '.?!…' else '.'}" if label else ""
        if job["changed_since_check"]:
            # Not ready to send: the pass no longer covers what's on file.
            orders.append({"rank": 1 if soon(job) else 2, "kind": "Check again", "job_id": job["id"], "action": "recheck",
                           "text": f"{job['company']}: {job['title']}",
                           "detail": joined(_deadline_text(job), "Its files changed after the assay passed it, so check it again before you send.", first)})
            continue
        detail = (joined(_deadline_text(job), first, _history_text(job)) or shorten(job["fit_reason"] or "", ORDER_REASON)
                  or job["notes"] or "Read it through, then send.")
        orders.append({"rank": 1 if soon(job) else 2, "kind": "Send", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}", "detail": detail})
    listed = {o["job_id"] for o in orders}
    # Within [run] decide_days, so there's time to tailor before it closes. A prospect not yet judged needs that first.
    closing = sorted((j for j in jobs if j["status"] in ("new", "shortlisted", "needs_fix") and j.get("decide_soon") and j["id"] not in listed),
                     key=lambda j: (max(j["days_to_deadline"], 0), -j["rank"]))
    for job in closing[:5]:
        decide = "Tailor it now or pass." if job["status"] != "new" else "Decide now: use Tailor this one first, or pass."
        orders.append({"rank": 1 if soon(job) else 2, "kind": "Closing soon", "job_id": job["id"], "text": f"{job['company']}: {job['title']}",
                       "detail": joined(_deadline_text(job), _history_text(job), decide)})
        listed.add(job["id"])
    fresh = sorted((j for j in jobs if j["status"] == "new" and j["is_new"] and not j.get("pay_too_low") and j["id"] not in listed),
                   key=lambda j: -j["rank"])
    for job in fresh[:3]:
        posted = {0: "today", 1: "yesterday"}.get(job["age_days"], f"{job['age_days']} days ago")
        orders.append({"rank": 3, "kind": "New listing", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}",
                       "detail": joined(f"Posted {posted}, never reposted. Score {job['score']}.", _deadline_text(job), _history_text(job))})
    for job in jobs:
        if job.get("rework"):
            orders.append({"rank": 2, "kind": "Rework", "job_id": job["id"], "action": "gap_seen",
                           "text": f"{job['company']}: {job['title']}",
                           "detail": f"{job['rework']} Refresh resume or Tailor this one first, or Got it to keep it as it is."})
    if reach and reach_out:
        orders.append(_reach_out_order(reach))
    return sorted(orders, key=lambda o: o["rank"])


def _gaps_order(found: dict[str, Any]) -> list[dict[str, Any]]:
    """One to-do item for the gaps that keep coming up, once one has come up in gaps.ORDER_FROM applications."""
    asked = gaps.questions(found)
    if not asked or asked[0]["count"] < gaps.ORDER_FROM:
        return []
    top = ", ".join(f"“{g['label']}” in {g['count']}" for g in asked[:2])
    many = len(asked)
    return [{"rank": 3, "kind": "Gaps to answer", "job_id": None, "tab": "profile/gaps",
             "text": f"{many} requirement{'s keep' if many > 1 else ' keeps'} coming up as gaps in your drafts",
             "detail": f"{top}. You may have done some of them: answer them so drafts stop guessing."}]


def _days(count: int) -> str:
    return f"{count} day{'' if count == 1 else 's'}"


def _setup_orders(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """What a new workspace still has to change, first on the to-do list. The demo is the example on purpose, so it has none."""
    if IS_EXAMPLE:
        return []
    # Each opens the Profile section that fixes it, where there is one, and otherwise the tab that does.
    return [{"rank": 0, "kind": "Finish setup", "job_id": None, "text": todo["what"], "detail": todo["fix"],
             "tab": f"profile/{todo['step']}" if todo.get("step") in profile.STEP_IDS else todo.get("tab")}
            for todo in doctor.workspace_todos(ROOT, cfg)]


def build_state(conn, cfg) -> dict[str, Any]:
    today = date.today().isoformat()
    rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC, first_seen DESC").fetchall()
    last_run = last_full_sweep(conn)
    swept_at = last_run["started_at"] if last_run else None
    context = signals.context(conn, cfg, date.fromisoformat(today))
    jobs = [_enrich(r, cfg, today, swept_at=swept_at, context=context) for r in rows]
    replies, refreshes, preps, tries = possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn)
    alerts = mail.open_alerts(conn)
    scams = _scam_alerts(alerts)
    history = _applied_by_company(conn)
    limit = cfg.get("dashboard", {}).get("max_per_company", DEFAULT_MAX_PER_COMPANY)
    seen = {r[0] for r in conn.execute("SELECT DISTINCT job_id FROM events WHERE kind = ?", (SEEN,))}
    reached = store.outreach(conn)
    rework = gaps.rework(conn, jobs, ROOT)
    for job in jobs:
        _attach_runs(job, replies, refreshes, preps, tries, scams)
        _attach_history(job, history, limit)
        job["seen"] = job["id"] in seen
        job["reached_out"] = job["id"] in reached
        job["rework"] = rework.get(job["id"])

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

    sendable = [j for j in jobs if j["status"] == "ready" and not j["posting_closed_at"]]
    stats = {
        # Ready to send means it can go: a draft whose posting came down can't, though the funnel still has it there.
        "ready": len(sendable),
        "ready_recheck": sum(bool(j["changed_since_check"]) for j in sendable),
        "ready_closed": sum(j["status"] == "ready" and bool(j["posting_closed_at"]) for j in jobs),
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
    # Each stage's icon reads the search as a fire assay: panned, forged, tested, in the furnace, melting, weighed, the bead.
    funnel = [
        {"stage": "Prospects", "icon": "pan", "count": at("new")},
        {"stage": "Being tailored", "icon": "anvil", "count": at("shortlisted", "needs_fix")},
        {"stage": "Ready to send", "icon": "streak", "count": at("ready")},
        {"stage": "Waiting to hear", "icon": "furnace", "count": at("applied")},
        {"stage": "Replied", "icon": "crucible", "count": at("responded")},
        {"stage": "Interviewing", "icon": "balance", "count": at("interviewing")},
        {"stage": "Offer", "icon": "cupel", "count": at("offer")},
    ]
    closed_labels = {"rejected": "rejected", "ghosted": "ghosted", "withdrawn": "withdrawn", "passed": "passed", "closed": "posting closed"}
    closed = [{"label": label, "count": at(status)} for status, label in closed_labels.items() if at(status)]
    brief = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1").fetchone()
    briefing = dict(brief) if brief else None
    if briefing:
        # The report names jobs as they stood when it was written, so say how much has moved since. A pass you undid
        # or reopened doesn't count: the job is where the report left it. Applying can't be undone.
        briefing["since"] = {kind: count for kind, count in conn.execute(
            """SELECT e.kind, COUNT(DISTINCT e.job_id) FROM events e JOIN jobs j ON j.id = e.job_id
               WHERE e.ts > ? AND (e.kind = 'applied' OR (e.kind = 'passed' AND j.status = 'passed')) GROUP BY e.kind""",
            (briefing["ts"],))}
    # The boards search.toml watches now, and the inbox. A board taken out of it isn't checked any more, so its last
    # good read would otherwise stay on the list as working. The demo's boards are made up, and the example's search.toml
    # can't watch them without asking real boards for companies that don't exist, so the demo lists every one.
    watched = {f"{kind}:{ident}" for kind, ident, _ in discover._watchlist(cfg)}
    source_rows = [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY company")
                   if IS_EXAMPLE or r["source_key"] in watched or r["source_key"].startswith("inbox:")]
    return {
        "jobs": jobs,
        "stats": stats,
        "funnel": funnel,
        "closed": closed,
        "orders": _setup_orders(cfg) + _orders(jobs, cfg["run"].get("fix_attempts", DEFAULT_FIX_ATTEMPTS), alerts, ghost_after_days(cfg),
                                               bool(cfg.get("dashboard", {}).get("reach_out", True)))
                  + _gaps_order(gaps.view(conn, ROOT)),
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
        "setup": setup_info(),
        # How far a new workspace's guided setup has got, for the rail. None when no setup is going.
        "guide": profile.progress(),
    }


class _Build:
    def __init__(self, changes: int) -> None:
        self.changes = changes
        self.done = threading.Event()
        self.state: dict[str, Any] | None = None
        self.error: BaseException | None = None


class SharedState:
    """The page's state, worked out once for every request that asks while a build is going.

    The first build after a start reads every posting and takes several seconds, and two at once would each take about
    twice as long. So a request that comes while one is going waits for it and takes its answer, unless something was
    changed through the dashboard since that build began: then it gets a build of its own, so a job you just passed
    never comes back. `warm` starts a build as the server starts, before the page asks.
    """

    def __init__(self, build: Callable[[], dict[str, Any]]) -> None:
        self._build = build
        self._lock = threading.Lock()
        self._changes = 0  # Changes begun through the dashboard.
        self._changing = 0  # Changes still going.
        self._going: _Build | None = None

    @contextmanager
    def changing(self) -> Iterator[None]:
        """Around anything that may change what the state says."""
        with self._lock:
            self._changes += 1
            self._changing += 1
        try:
            yield
        finally:
            with self._lock:
                self._changing -= 1

    def get(self) -> dict[str, Any]:
        with self._lock:
            going = self._going
            if going is None or going.changes != self._changes:
                going = None
                mine = _Build(self._changes)
                # A build that began while a change was going may have missed it, so nothing else takes its answer.
                if not self._changing:
                    self._going = mine
        if going is not None:
            going.done.wait()
            if going.error is not None or going.state is None:
                raise going.error or RuntimeError("The dashboard's state couldn't be worked out.")
            return going.state
        try:
            mine.state = self._build()
        except BaseException as err:
            mine.error = err
            raise
        finally:
            mine.done.set()
            with self._lock:
                if self._going is mine:
                    self._going = None
        return mine.state

    def warm(self) -> None:
        """Start a build now, in the background. A problem it finds is said when the page asks, not here."""
        def build() -> None:
            try:
                self.get()
            except Exception:
                pass
        threading.Thread(target=build, name="pyrite-warm", daemon=True).start()


def _state_now() -> dict[str, Any]:
    with closing(connect()) as conn:
        return build_state(conn, load_config())


STATE = SharedState(_state_now)


def job_detail(conn, job_id: int, cfg: dict[str, Any]) -> dict[str, Any]:
    last_run = last_full_sweep(conn)
    job = _enrich(get_job(conn, job_id), cfg, date.today().isoformat(), include_description=True,
                  swept_at=last_run["started_at"] if last_run else None, context=signals.context(conn, cfg, date.today()))
    _attach_runs(job, possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn),
                 _scam_alerts(mail.open_alerts(conn)))
    _attach_history(job, _applied_by_company(conn), cfg.get("dashboard", {}).get("max_per_company", DEFAULT_MAX_PER_COMPANY))
    job["seen"] = bool(conn.execute("SELECT 1 FROM events WHERE job_id = ? AND kind = ?", (job_id, SEEN)).fetchone())
    job["can_unpass"] = job["status"] == "passed" and _status_before_pass(conn, job_id) is not None
    job["reached_out"] = job_id in store.outreach(conn)
    job["can_reach_out"] = bool(job["applied_at"]) and job["status"] in store.ACTIVE
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
    # What the web says about the employer, shared by every job there, and where to read reviews yourself.
    job["culture"] = culture.status(row["company"]) if culture.company_key(row["company"]) else None
    job["culture_links"] = culture.links(row["company"])
    return job


def _reopen_target(job, cfg: dict[str, Any]) -> str:
    """Where a reopened job goes back to. Ready only if the assay's last verdict was a pass and nothing has changed since:
    having once been ready says nothing about the draft on disk now."""
    if job["applied_at"]:
        return "applied"
    if not job["app_folder"]:
        return "shortlisted"
    if not job["check_result"]:
        return "shortlisted"
    return "needs_fix" if checks.not_covered(ROOT / job["app_folder"], cfg, job["check_result"]) else "ready"


def apply_action(conn, job_id: int, body: dict[str, Any], cfg: dict[str, Any]) -> None:
    action = body.get("action")
    note = _text(body, "note", "The note", MAX_NOTE)
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
        # Hearing back is about an application, and the reply rate counts it against one.
        if not job["applied_at"]:
            raise ValueError("This one hasn't been sent, so there's no reply to log. Mark it applied first if you did apply.")
        set_status(conn, job_id, HEARD_BACK[kind], note, follow_up)
    elif action == "dismiss_reply":
        log_event(conn, job_id, REPLY_DISMISSED, note)
    elif action == "acknowledge_changes":
        store.acknowledge_sent_changes(conn, job_id)
    elif action == "reached_out":
        store.log_outreach(conn, job_id, _text(body, "date", "The day", 40), _text(body, "to", "Who you reached", 120), note, follow_up)
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
    elif action == "gap_seen":
        log_event(conn, job_id, gaps.SEEN, "You kept this draft as it is after answering a gap it lists.")
    elif action == "seen":
        if not conn.execute("SELECT 1 FROM events WHERE job_id = ? AND kind = ?", (job_id, SEEN)).fetchone():
            log_event(conn, job_id, SEEN)
    elif action == "note":
        conn.execute("UPDATE jobs SET notes = ? WHERE id = ?", (_text(body, "notes", "Your notes", MAX_NOTES), job_id))
    elif action == "next_action":
        text = _text(body, "text", "The next step", MAX_NEXT_STEP)
        when = _text(body, "date", "The date", 40) or None
        if when:
            try:
                # The pattern first, since fromisoformat also takes forms such as 20260102 that the page never sends.
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
                    raise ValueError
                date.fromisoformat(when)
            except ValueError:
                raise ValueError(f"{when} isn't a date. Give it as YYYY-MM-DD.") from None
        conn.execute("UPDATE jobs SET next_action = ?, next_action_date = ? WHERE id = ?", (text, when, job_id))
        log_event(conn, job_id, "next_action", f"{text} {when or ''}".strip())
    else:
        raise ValueError(f"Unknown action {action!r}")


def allowed_hosts(cfg: dict[str, Any]) -> set[str]:
    """The extra names under [dashboard] allowed_hosts, in lower case. Only a list of names counts: a single string
    would let any piece of it match, so it allows nothing, and `pyrite doctor` says so."""
    dashboard = cfg.get("dashboard", {})
    names = dashboard.get("allowed_hosts", []) if isinstance(dashboard, dict) else []
    if not isinstance(names, list):
        return set()
    return {name.strip().lower() for name in names if isinstance(name, str) and name.strip()}


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
        # Refusing unknown Host headers stops DNS rebinding from reading this data. A request with no Host at all
        # names nothing this server answers to, so it's refused too.
        host = re.sub(r":\d+$", "", self.headers.get("Host", "")).strip().lower()
        if not host:
            return False
        try:
            extra = allowed_hosts(load_config())
        except (OSError, tomllib.TOMLDecodeError, store.ConfigError):
            extra = set()  # Localhost still gets through, so the page can say what's wrong with the file.
        return host in ALLOWED_HOSTS or host in extra

    def _guarded(self, handle) -> None:
        """Answer every request, even a failed one. A dropped connection tells the page nothing."""
        try:
            handle()
        except tomllib.TOMLDecodeError as err:
            self._json({"error": f"profile/search.toml can't be read, so nothing loaded. Fix it and reload: {err}"}, 500)
        except store.ConfigError as err:
            self._json({"error": f"{err} Nothing loads until it's fixed, so reload once it is."}, 500)
        except sqlite3.OperationalError as err:
            if "locked" in str(err) or "busy" in str(err):
                self._json({"error": "The database is busy, probably with a sweep. Try again in a moment."}, 503)
            else:
                self._json({"error": f"Database error: {err}"}, 500)
        except ConnectionError:
            pass  # The browser went away mid-answer.
        except Exception:
            # The details go to the window the dashboard runs in, not to whatever sent the request.
            traceback.print_exc()
            self._json({"error": "Something went wrong on the server, so that didn't work. The details are in the window "
                                 "the dashboard is running in."}, 500)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, Any] | None = None) -> None:
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
        with STATE.changing():
            self._guarded(self._post)

    def _get(self):
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        path = urlparse(self.path).path
        try:
            if path in STATIC_FILES:
                name, mime = STATIC_FILES[path]
                return self._send(200, page() if name == "index.html" else (STATIC / name).read_bytes(), mime)
            if path == "/api/state":
                return self._json(STATE.get())
            if path == "/api/settings":
                return self._json(_settings_page())
            if path == "/api/settings/schedule":
                return self._json(schedule.view())
            if path == "/api/settings/status":
                fresh = parse_qs(urlparse(self.path).query).get("fresh") == ["1"]
                return self._json(options.status(load_config(), fresh))
            if path == "/api/facts":
                return self._json(facts.view())
            if path == "/api/profile":
                return self._json(_profile_page())
            if path == "/api/profile/tools":
                fresh = parse_qs(urlparse(self.path).query).get("fresh") == ["1"]
                return self._json({"tools": doctor.tool_checks(load_config(), options.claude_status(fresh))})
            if path == "/api/profile/workspace":
                return self._json(backup.about(store.ROOT))
            if path == "/api/profile/rescore":
                return self._json(_rescore_state())
            if path == "/api/profile/kept":
                query = parse_qs(urlparse(self.path).query)
                try:
                    return self._json(profile.compare(query.get("key", [""])[0], query.get("stamp", [""])[0]))
                except ValueError as err:
                    return self._json({"error": str(err)}, 404)
            if path == "/api/update":
                return self._json(update_state(load_config()))
            if path == "/api/alive":
                return self._json({"server": SERVER_ID})
            if path == "/api/industries":
                conn = connect()
                try:
                    return self._json(market.view(conn, load_config()))
                finally:
                    conn.close()
            match = re.fullmatch(rf"/api/job/{JOB_ID}", path)
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
        except (ValueError, RecursionError):
            # RecursionError is JSON nested deeper than Python will follow, which no page of this dashboard sends.
            return self._json({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return self._json({"error": "bad request"}, 400)

        path = urlparse(self.path).path
        if path == "/api/profile/test-board":
            try:
                return self._json(_test_board(body))
            except ValueError as err:
                return self._json({"error": str(err)}, 400)
        if path == "/api/setup":
            try:
                folder, told = make_workspace(body)
            except ValueError as err:
                return self._json({"error": str(err)}, 400)
            restart = getattr(self.server, "restart_soon", None)
            self._json({"told": told, "folder": str(folder), "restarting": restart is not None, "server": SERVER_ID})
            if restart:
                restart(folder)
            return None
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
                known = tracked_by_url(conn, str(body.get("url", "")))
                job_id = add_manual_job(
                    conn, cfg, str(body.get("company", "")), str(body.get("title", "")),
                    str(body.get("url", "")), str(body.get("location", "")), str(body.get("description", "")),
                )
                conn.commit()
                if known:
                    return self._json({"id": job_id, "existing": True, "status": known["status"]}, 200)
                return self._json({"id": job_id}, 201)
            if path == "/api/jobs/read":
                # What the posting at a link says, so the Add a posting form can fill itself in. Nothing is saved.
                return self._json(link.read(_text(body, "url", "The link", MAX_LINK)))
            if path == "/api/run":
                tasks.start(conn, str(body.get("kind") or ""))
                return self._json({"ok": True}, 202)
            if path == "/api/run/accept":
                # "I made this change": clears one run's profile-changed warning, and with retry starts that run again.
                task_id = body.get("id")
                if not isinstance(task_id, int) or isinstance(task_id, bool):
                    raise ValueError("Say which run's warning to clear.")
                kind = tasks.accept_profile_change(conn, task_id)
                if body.get("retry") is True:
                    tasks.start(conn, kind)
                    return self._json({"ok": True, "started": kind}, 202)
                return self._json({"ok": True})
            if path == "/api/update":
                return self._update(conn, cfg, body.get("switch") is True)
            if path == "/api/industries/outlook":
                outlook.start(cfg, str(body.get("name") or ""))
                return self._json({"ok": True}, 202)
            match = re.fullmatch(rf"/api/job/{JOB_ID}/culture", path)
            if match:
                culture.start(conn, int(match.group(1)))
                return self._json({"ok": True}, 202)
            match = re.fullmatch(rf"/api/job/{JOB_ID}/action", path)
            if match:
                apply_action(conn, int(match.group(1)), body, cfg)
                conn.commit()
                return self._json({"ok": True})
            match = re.fullmatch(rf"/api/alert/{JOB_ID}/dismiss", path)
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

    def _update(self, conn, cfg: dict[str, Any], switch: bool) -> None:
        """Update Pyrite's code to GitHub's main, then restart on it once the page has heard what happened. `switch`
        says the page offered to switch the code folder to main, so a folder on another branch may be."""
        # The page hides the button then, but `check_updates = false` promises GitHub is never asked, so this keeps it.
        if not updates_on(cfg):
            raise ValueError("check_updates = false under [dashboard], so Pyrite doesn't ask GitHub. Update with "
                             "`git pull` instead.")
        running = tasks.going(conn)
        if running:
            raise ValueError(f"A {running} is going, and updating the code under it could break it. Update once it's done.")
        done = update.apply(demo=IS_EXAMPLE, switch=switch)
        restart = getattr(self.server, "restart_soon", None)
        self._json({**done, "restarting": restart is not None, "server": SERVER_ID})
        if restart:
            restart()


def setup_info() -> dict[str, Any] | None:
    """What the page's Make your workspace form starts from, or None once a workspace is named."""
    if not store.NEEDS_SETUP:
        return None
    return {"suggested": str(store.CODE_ROOT.parent / SETUP_FOLDER), "code_folder": str(store.CODE_ROOT),
            "git": shutil.which("git") is not None}


def make_workspace(body: dict[str, Any]) -> tuple[Path, list[str]]:
    """Setup's Make your workspace: the folder made, and what `pyrite init` would have said, a line at a time. Only while
    nothing names a workspace, so a page can never make a second one or move Pyrite off the one in use. A relative
    folder is read from the code folder, as docs/setup.md writes them, such as ../my-job-search."""
    if not store.NEEDS_SETUP:
        raise ValueError("Pyrite already has a workspace, so setup can't make another. `pyrite init` in a terminal can.")
    folder_text, name = body.get("folder"), body.get("name")
    if not isinstance(folder_text, str) or not folder_text.strip():
        raise ValueError("Say which folder to make your workspace in.")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Give your name as it goes on your documents. Nothing was made.")
    if body.get("start") not in ("blank", "example") or not isinstance(body.get("git", False), bool):
        raise ValueError("Say whether to start from blank files or from the example.")
    if any(ord(char) < 32 for char in folder_text + name):
        raise ValueError("The folder and name can't hold line breaks or control characters. Nothing was made.")
    folder = (store.CODE_ROOT / Path(folder_text.strip()).expanduser()).resolve()
    try:
        told = workspace.create(str(folder), name, blank=body["start"] == "blank", git=bool(body.get("git")))
    except workspace.Refused as err:
        raise ValueError(str(err)) from None
    return folder, [line.strip() for line in told if line.strip()]


def updates_on(cfg: dict[str, Any]) -> bool:
    """Whether the dashboard may ask GitHub for a newer Pyrite: anything but `check_updates = false` under [dashboard]."""
    return cfg.get("dashboard", {}).get("check_updates", True) is not False


def update_state(cfg: dict[str, Any]) -> dict[str, Any]:
    """What the Update available button needs: whether GitHub's main is ahead of this copy, and anything stopping the
    update. `check_updates = false` under [dashboard] means GitHub is never asked."""
    if not updates_on(cfg):
        return {"available": False, "off": True}
    found = update.check(demo=IS_EXAMPLE)
    if found.get("available") and not found.get("why_not"):
        conn = connect()
        try:
            running = tasks.going(conn)
        finally:
            conn.close()
        if running:
            found["why_not"] = f"A {running} is going, and updating the code under it could break it. Update once it's done."
    return found


def _settings_page() -> dict[str, Any]:
    """Everything the Settings tab shows: how Pyrite runs, and the cities and industries to see first."""
    return {**settings.view(), "options": options.view()}


def _save_settings(body: dict[str, Any]) -> dict[str, Any]:
    settings.save(body)
    return _settings_page()


def _save_options(body: dict[str, Any]) -> dict[str, Any]:
    options.save(body)
    return _settings_page()


def _change_schedule(body: dict[str, Any]) -> dict[str, Any]:
    """Set up, move or remove one of the daily runs in Task Scheduler. It changes no file, and no run can say more
    than it could, so it needs no code: the page asks you to confirm before it sends."""
    return schedule.change(body)


def _save_facts(body: dict[str, Any]) -> dict[str, Any]:
    """The Facts tab's save. Approving a term or unlisting a "Do not use" item needs a code, as on the Profile tab."""
    # The demo refuses every save, so it shouldn't send a code first.
    if not store.IS_EXAMPLE:
        # A save that would be refused is refused before any code is sent, so it never costs a code or a notification.
        key, text = facts._clean(body.get("file"), body.get("text"))
        current = facts._read(key)
        if body.get("version") != facts._version(current):
            raise settings.Conflict("This file changed after you opened it, so nothing was saved. Reload the Facts tab to see the latest.")
        confirm.require({key: text}, {key: current}, {key: body.get("version")}, body.get("request_id"), body.get("code"))
    return facts.save(body)


def _save_profile(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("step") != "gaps":
        return _write_profile(body.get("changes"), body.get("based_on"), body, str(body.get("reason") or ""), body.get("step"))
    # Answers to gaps also keep which questions were answered and flag the drafts that raised them. What's kept follows
    # what the save actually added to facts.md, so the page can't record an answer the files don't hold.
    with closing(connect()) as conn:
        found, before = gaps.view(conn), profile.read("facts")
        _write_profile(body.get("changes"), body.get("based_on"), body, str(body.get("reason") or ""), "gaps")
        gaps.record(conn, found, body.get("answers"), before, profile.read("facts"))
    return _profile_page()


def _gap_question(body: dict[str, Any]) -> dict[str, Any]:
    """Stop asking about a gap that doesn't apply, or ask about one again. Neither changes a file the assay reads."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so its questions can't be answered.")
    gap_id = str(body.get("id") or "")
    if body.get("action") == "dismiss":
        gaps.dismiss(gaps.view(), gap_id)
    elif body.get("action") == "forget":
        if not gaps.forget(gap_id):
            raise ValueError("That question wasn't answered, so there's nothing to ask again.")
    else:
        raise ValueError("Say whether to dismiss the question or ask it again.")
    return _profile_page()


def _put_back(body: dict[str, Any]) -> dict[str, Any]:
    """History's Put back: the copy a file had before an earlier save, or with `whole`, every file that save changed.
    The copies are read here rather than sent by the page, and written like any other save, so one that loosens a
    check still needs a code."""
    key, stamp = str(body.get("key") or ""), str(body.get("stamp") or "")
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's profile can't be changed.")
    texts = profile.kept_save(stamp) if body.get("whole") is True else {key: profile.kept(key, stamp)}
    return _write_profile(texts, body.get("based_on"), body, profile.put_back_reason(list(texts), stamp), None)


def _write_profile(changes, based_on, body: dict[str, Any], reason: str, step) -> dict[str, Any]:
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's profile can't be changed.")
    if not isinstance(changes, dict) or not changes or not isinstance(based_on, dict):
        raise ValueError("Nothing to save.")
    # Everything that would refuse the save is checked before any code is sent, so a save that can't go through
    # never costs a code or a notification: what each file would hold, then whether the form is stale.
    changes = {key: profile._clean(key, text) for key, text in changes.items()}
    current = {key: profile.read(key) for key in changes}
    profile.refuse_stale(current, based_on)
    confirm.require(changes, current, based_on, body.get("request_id"), body.get("code"))
    profile.write(changes, based_on, reason, step if isinstance(step, str) else None)
    return _profile_page()


def _profile_page() -> dict[str, Any]:
    """Everything the Profile tab shows: the files as the sections read them, and History."""
    return {**profile.view(), **steps.view(), "history": profile.history()}


def _draft_profile(body: dict[str, Any]) -> dict[str, Any]:
    """What a section's form would write, worked out by the same code a save uses. Nothing is written."""
    return steps.draft(str(body.get("step") or ""), body.get("edits"), body.get("based_on"))


def _test_board(body: dict[str, Any]) -> dict[str, Any]:
    """Companies to watch's Test: read one board once, as `pyrite sources` does, and say whether it answers and how many
    postings it lists. Nothing is saved. The request names a board by its kind and key, or by a careers page address,
    never by the address to fetch: only the key goes into the address of that board's own feed, and a key that could
    name any other site is refused before anything is fetched."""
    if body.get("url") is not None:
        board = discover.board_from_url(_text(body, "url", "The address", MAX_LINK))
    else:
        board = {part: body.get(part) or "" for part in ("kind", "key", "wd", "site", "name")}
        if not all(isinstance(value, str) for value in board.values()):
            raise ValueError("Say which board to test.")
        board = {part: value.strip() for part, value in board.items()}
        if board["kind"] == "lever" and body.get("eu") is True:
            board["eu"] = True  # Lever's EU site: the same key, read from its EU feed.
    kind, key = board["kind"], board["key"]
    problem = discover.board_problem(kind, key, board.get("wd", ""), board.get("site", ""))
    if problem:
        raise ValueError(problem)
    name = board.get("name") or key
    spec: Any = {"name": name, "wd": board["wd"], "site": board["site"]} if kind == "workday" else name
    if kind == "lever" and board.get("eu") is True:
        spec = {"name": name, "eu": True}
    found = discover.check_source(kind, key, spec)
    if not found["ok"] and re.search(r"\b404\b", found["error"]):
        found["hint"] = (f"No {discover.BOARD_KINDS[kind]} board answers at that address. Check it against the careers "
                         "page, or the company may use another board.")
    return {**found, "board": {**board, "kind": kind, "key": key}}


def _back_up(body: dict[str, Any]) -> dict[str, Any]:
    """Copy data/pyrite.db into data/backups. It adds a file and changes none, so it needs no code."""
    made = backup.make(store.ROOT)
    return {**backup.about(store.ROOT), "made": made}


def _rescore_state() -> dict[str, Any]:
    """What Rescore now needs, under Your prospects in Roles you want and Where you'll work: what a rescore would change
    now, why it can't run if it can't, and when the latest pan started, since the next one rescores too."""
    with closing(connect()) as conn:
        going = tasks.going(conn)
        row = conn.execute("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        try:
            due: dict[str, Any] = discover.rescore_due(conn, load_config())
        except ValueError as err:
            due = {"error": f"Pyrite couldn't score your prospects with your settings ({err})."}
    why_not = (_RESCORE_DEMO if store.IS_EXAMPLE else _rescore_busy(going) if going else "")
    return {"due": due, "why_not": why_not, "last_pan": row["started_at"] if row else None}


_RESCORE_DEMO = "This is the demo, so its prospects can't be scored again."


def _rescore_busy(running: str) -> str:
    return f"A {running} is going, and a rescore could drop a prospect it's working on. Rescore once it's done."


def _rescore_now(body: dict[str, Any]) -> dict[str, Any]:
    """Rescore now: copy data/pyrite.db into data/backups, as Back up now does, then score the prospects again as
    `pyrite rescore` does, and say what that did. Refused in the demo, and while any run is going, as an update is."""
    if store.IS_EXAMPLE:
        raise ValueError(_RESCORE_DEMO)
    with closing(connect()) as conn:
        running = tasks.going(conn)
        if running:
            raise ValueError(_rescore_busy(running))
        made = backup.make(store.ROOT)  # First, so a rescore never drops anything there's no copy of.
        result = discover.rescore(conn, load_config())
    return {**result, "said": words.rescore(result), "backup": {**made, "folder": backup.FOLDER.as_posix()},
            **_rescore_state()}


def _profile_code(body: dict[str, Any]) -> dict[str, Any]:
    """Send a waiting change's code again, or give up on it."""
    if body.get("action") == "resend":
        return confirm.resend(body.get("request_id"))
    if body.get("action") == "cancel":
        confirm.cancel(body.get("request_id"))
        return {"ok": True}
    raise ValueError("Ask to resend or cancel a code.")


# Saves that change the profile, and the drafts that show what one would do. Each refuses a stale form, and any save
# that loosens a check asks for a code first.
PROFILE_WRITES = {
    "/api/profile/draft": _draft_profile,
    "/api/settings": _save_settings,
    "/api/settings/options": _save_options,
    "/api/settings/schedule": _change_schedule,
    "/api/facts": _save_facts,
    "/api/profile": _save_profile,
    "/api/profile/put-back": _put_back,
    "/api/profile/code": _profile_code,
    "/api/profile/backup": _back_up,
    "/api/profile/rescore": _rescore_now,
    "/api/gaps": _gap_question,
}


class DashboardServer(ThreadingHTTPServer):
    """The dashboard's server, which won't share its port.

    HTTPServer turns on SO_REUSEADDR. On Windows that lets a second process listen on a port that's already taken, so a
    second dashboard would start without complaint and requests would go to either one. Any other program on this
    machine could do the same to answer in the dashboard's place. Windows gets an exclusive port instead, and elsewhere
    SO_REUSEADDR only lets a restart reuse the port of one that just closed.
    """
    allow_reuse_address = sys.platform != "win32"
    # Set once an update has moved the code, or setup has made a workspace, so serve() starts a new dashboard after
    # this one stops.
    restarting = False
    # The workspace setup just made, which the new dashboard opens. None to open the one this one has.
    restart_home: Path | None = None

    def restart_soon(self, home: Path | None = None) -> None:
        """Stop serving, from another thread, since the one serving can't wait for itself, and come back on the new
        code, or on the workspace `home` that setup just made."""
        self.restarting = True
        self.restart_home = home
        threading.Thread(target=self.shutdown, daemon=True).start()

    def server_bind(self) -> None:
        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def make_server(port: int) -> DashboardServer:
    try:
        return DashboardServer(("127.0.0.1", port), Handler)
    except OverflowError:
        raise SystemExit(f"{port} isn't a port: a port is a number from 1 to 65535. Pick one with --port.") from None
    except OSError as err:
        raise SystemExit(f"Port {port} is already in use, so the dashboard didn't start ({err.strerror or err}).\n"
                         f"If Pyrite is already running, open http://127.0.0.1:{port}. Otherwise pick another port with --port.") from None


def serve(port: int = 8787) -> None:
    connect().close()
    server = make_server(port)
    STATE.warm()
    print(f"Pyrite: http://127.0.0.1:{port}\nOpen that in your browser. The dashboard runs while this window is open, "
          "and Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        # Ctrl+C is how a dashboard started by hand is meant to stop, so it isn't an error worth a traceback.
        print("Stopped.", flush=True)
    finally:
        server.server_close()
    # Only an update or setup sets it, and only to True. Anything else standing in for a server must never start a dashboard.
    if server.restarting is True:
        home = server.restart_home if isinstance(server.restart_home, Path) else None
        print(f"Your workspace is made at {home}, so the dashboard is starting again on it." if home else
              "Pyrite was updated, so the dashboard is starting again on the new code.", flush=True)
        if launch.restart(port, home):
            print(f"It's running in the background at {launch.url(port)}, and keeps going after this window closes.", flush=True)
        else:
            print(f"It didn't come back on port {port}. Run `pyrite open` to start it, or `pyrite serve` to see why not.",
                  flush=True)
