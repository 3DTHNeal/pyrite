"""The dashboard server. Localhost only, because this data includes your whole job search.

Posting text comes from the internet, so the page never treats it as HTML, and
requests from other websites can neither read this data nor change it.
"""
import hashlib
import json
import re
import sqlite3
import statistics
import tomllib
import traceback
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from . import checks, claude_code, facts, prep, refresh, tasks
from . import score as scoring
from . import settings
from .cli import finish_job
from .discover import last_full_sweep
from .store import (
    DEFAULT_FIX_ATTEMPTS, IS_EXAMPLE, REPLY_DISMISSED, ROOT, TAILOR_REQUESTED, changed_after_sending, connect, fix_attempts,
    get_job, job_dict, load_config, log_event, now, possible_replies, quiet_days_since, sent_copies, set_status,
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
CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
HEARD_BACK = {"reply": "responded", "interview": "interviewing", "offer": "offer", "rejected": "rejected"}
# What the dashboard's own buttons set. Ready and needs_fix come only from the fact checker.
USER_STATUSES = ("applied", "passed", "ghosted", "withdrawn")
RECHECKABLE = ("ready", "needs_fix")


def safe_url(url: str) -> str:
    url = (url or "").strip()
    return url if urlparse(url).scheme in ("http", "https") else ""


def add_manual_job(conn, cfg, company, title, url="", location="", description="") -> int:
    """A posting you found yourself always goes in, whatever the filters think, at the front of the line."""
    company, title = company.strip(), title.strip()
    if not company or not title:
        raise ValueError("Company and title are required.")
    url = safe_url(url)
    source_id = hashlib.sha1(f"{company}|{title}|{url}".encode()).hexdigest()[:16]
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


def _enrich(row, cfg: dict, today: str, include_description: bool = False) -> dict:
    job = job_dict(row, include_description)
    run = cfg["run"]
    job["days_since_applied"] = quiet_days_since(job["applied_at"])
    job["days_in_status"] = quiet_days_since(job["status_changed_at"])
    job["follow_up_due"] = bool(job["next_action_date"] and job["next_action_date"] <= today)
    job["quiet"] = job["status"] == "applied" and (job["days_since_applied"] or 0) >= run["quiet_days"]
    job["url"] = safe_url(job["url"])
    job["changed_since_check"] = _changed_since_check(job)
    # Once sent, the documents are a record, not a draft: nothing rebuilds or refreshes them.
    job["frozen"] = bool(job["applied_at"])
    job["changed_after_sending"] = changed_after_sending(row) if job["frozen"] else []
    job["sent_files"] = ([p.relative_to(ROOT).as_posix() for p in sent_copies(ROOT / job["app_folder"])]
                         if job["frozen"] and job["app_folder"] else [])
    # The whole row, because priority reads the description even when the page isn't sent it.
    job.update(scoring.freshness(dict(row), cfg, date.fromisoformat(today)))
    return job


def _changed_since_check(job: dict) -> list[str]:
    """Files that changed after the fact checker passed a draft you haven't sent, so the pass no longer covers them."""
    checked = (job["check_result"] or {}).get("checked")
    if job["status"] != "ready" or not checked or not job["app_folder"]:
        return []
    return checks.changed_since(ROOT / job["app_folder"], checked)


def _attach_runs(job: dict, replies: dict, refreshes: dict, preps: dict, tries: dict) -> None:
    job["possible_reply"] = replies.get(job["id"])
    job["refresh"] = refreshes.get(job["id"])
    job["prep"] = preps.get(job["id"])
    job["fix_attempts"] = tries.get(job["id"], 0)
    if job["refresh"] and job["refresh"]["state"] == "running":
        job["changed_since_check"] = []  # A refresh rewrites the draft in place and checks it when it's done.


def _orders(jobs: list[dict], fix_limit: int = DEFAULT_FIX_ATTEMPTS) -> list[dict]:
    """Today's to-do list, most urgent first."""
    orders = []
    for job in jobs:
        name = f"{job['company']}: {job['title']}"
        if job["possible_reply"]:
            orders.append({"rank": 0, "kind": "Possible reply", "job_id": job["id"], "text": name,
                           "detail": job["possible_reply"]["detail"]})
        if job["status"] in ("interviewing", "offer") and job["follow_up_due"]:
            orders.append({"rank": 0, "kind": "Act now", "job_id": job["id"], "text": name,
                           "detail": job["next_action"] or "Next step is due"})
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
    ready = sorted((j for j in jobs if j["status"] == "ready" and not j["posting_closed_at"]),
                   key=lambda j: -j["rank"])
    for job in ready[:5]:
        detail = job["fit_reason"] or job["notes"] or "Read it through, then send."
        if job["changed_since_check"]:
            detail = "Its files changed after the assay passed it. Open it and check it again before you send."
        orders.append({"rank": 2, "kind": "Send", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}", "detail": detail})
    fresh = sorted((j for j in jobs if j["status"] == "new" and j["is_new"]), key=lambda j: -j["rank"])
    for job in fresh[:3]:
        posted = {0: "today", 1: "yesterday"}.get(job["age_days"], f"{job['age_days']} days ago")
        orders.append({"rank": 3, "kind": "New listing", "job_id": job["id"],
                       "text": f"{job['company']}: {job['title']}",
                       "detail": f"Posted {posted}, never reposted. Score {job['score']}."})
    return sorted(orders, key=lambda o: o["rank"])


def build_state(conn, cfg) -> dict:
    today = date.today().isoformat()
    rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC, first_seen DESC").fetchall()
    jobs = [_enrich(r, cfg, today) for r in rows]
    replies, refreshes, preps, tries = possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn)
    for job in jobs:
        _attach_runs(job, replies, refreshes, preps, tries)

    applied =[j for j in jobs if j["applied_at"]]
    heard = [j for j in applied if j["response_at"]]
    days_to_reply = [
        (datetime.fromisoformat(j["response_at"]) - datetime.fromisoformat(j["applied_at"])).days
        for j in heard
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
        "median_days_to_reply": statistics.median(days_to_reply) if days_to_reply else None,
        "interviews": sum(bool(j["interview_at"]) for j in jobs),
        "fresh": sum(j["is_new"] for j in radar),
        "possible_ghosts": sum(j["ghost_risk"] for j in radar),
        "to_triage": len(radar),
    }
    funnel = [
        {"stage": "Found", "count": len(jobs)},
        {"stage": "Resume ready", "count": sum(bool(j["ready_at"]) for j in jobs)},
        {"stage": "Applied", "count": len(applied)},
        {"stage": "Heard back", "count": len(heard)},
        {"stage": "Interview", "count": stats["interviews"]},
        {"stage": "Offer", "count": sum(bool(j["offer_at"]) for j in jobs)},
    ]
    brief = conn.execute("SELECT * FROM briefings ORDER BY id DESC LIMIT 1").fetchone()
    source_rows = [dict(r) for r in conn.execute("SELECT * FROM source_status ORDER BY company")]
    return {
        "jobs": jobs,
        "stats": stats,
        "funnel": funnel,
        "orders": _orders(jobs, cfg["run"].get("fix_attempts", DEFAULT_FIX_ATTEMPTS)),
        "sources": source_rows,
        "manual_check": cfg.get("manual_check", []),
        "last_run": last_full_sweep(conn),
        "briefing": dict(brief) if brief else None,
        "before_send": cfg.get("dashboard", {}).get("before_send", []),
        "usage": claude_code.usage(conn),
        "tasks": tasks.latest(conn),
        "demo": IS_EXAMPLE,
    }


def job_detail(conn, job_id: int, cfg: dict) -> dict:
    job = _enrich(get_job(conn, job_id), cfg, date.today().isoformat(), include_description=True)
    _attach_runs(job, possible_replies(conn), refresh.states(conn), prep.states(conn), fix_attempts(conn))
    job["fix_limit"] = cfg["run"].get("fix_attempts", DEFAULT_FIX_ATTEMPTS)
    job["can_refresh"] = job["status"] in refresh.REFRESHABLE and bool(job["app_folder"])
    job["can_recheck"] = job["status"] in RECHECKABLE and bool(job["app_folder"]) and not IS_EXAMPLE
    # Offered even without an application folder, so the button can say what's missing.
    job["can_prep"] = job["status"] in prep.PREPPABLE
    job["events"] =[dict(r) for r in conn.execute(
        "SELECT ts, kind, detail FROM events WHERE job_id = ? ORDER BY id DESC", (job_id,)
    )]
    job["notes_md"] = ""
    job["prep_file"] = ""
    if job["app_folder"]:
        path = ROOT / job["app_folder"] / "notes.md"
        if path.exists():
            job["notes_md"] = path.read_text(encoding="utf-8")
        if (ROOT / job["app_folder"] / prep.BRIEF).exists():
            job["prep_file"] = f"{job['app_folder']}/{prep.BRIEF}"
    return job


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
    elif action == "refresh_resume":
        refresh.start(conn, job_id)
    elif action == "interview_prep":
        prep.start(conn, job_id)
    elif action == "reopen":
        target = "applied" if job["applied_at"] else "ready" if job["ready_at"] else "shortlisted"
        set_status(conn, job_id, target, "Reopened", follow_up)
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
    """Only finished application documents can be served, never the database or anything else."""
    target = (ROOT / rel).resolve()
    allowed = any(target.is_relative_to(ROOT / folder) for folder in SERVABLE_ROOTS)
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
            if length > 500_000:
                return self._json({"error": "too large"}, 413)
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        if not isinstance(body, dict):
            return self._json({"error": "bad request"}, 400)

        path = urlparse(self.path).path
        if path in ("/api/settings", "/api/facts"):
            try:
                return self._json(settings.save(body) if path == "/api/settings" else facts.save(body))
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
            match = re.fullmatch(r"/api/job/(\d+)/action", path)
            if match:
                apply_action(conn, int(match.group(1)), body, cfg)
                conn.commit()
                return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except (ValueError, KeyError) as err:
            conn.rollback()
            return self._json({"error": str(err)}, 400)
        finally:
            conn.close()


def serve(port: int = 8787) -> None:
    connect().close()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Pyrite: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
