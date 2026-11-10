"""Pull postings from every watched company, filter, rank and store the keepers."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, cast

from . import deadline, quality, sources
from . import score as scoring
from .store import (
    ACTIVE,
    REPLY_DETECTED,
    ROOT,
    SCORING_VERSION,
    STATUSES,
    ConfigError,
    get_job,
    load_config,
    log_event,
    now,
    possible_replies,
    quiet_days_since,
    record_listing,
    scoring_version,
    set_meta,
    set_status,
)

# How much of a posting's vocabulary must match for an edited repost to count as the same job.
NEAR_TWIN_OVERLAP = 0.85
# How many of their title words two postings under one requisition id must share. Below it, the id was reused for another job.
SAME_REQUISITION_TITLE_OVERLAP = 0.5
# Workday ends a posting's link with its requisition id, and adds -1, -2 and so on when the requisition is posted again.
WORKDAY_REQUISITION = re.compile(r"_([A-Za-z]*-?\d[\w-]*?)(?:-\d{1,2})?$")
# Short forms boards use in titles, so "Sr. Firmware Engr" and "Senior Firmware Engineer" read as one title.
TITLE_WORDS = {"sr": "senior", "jr": "junior", "mgr": "manager", "engr": "engineer", "eng": "engineer", "dir": "director",
               "assoc": "associate", "tpm": "technical program manager"}
# Days a sent application's posting can be down, with nothing heard, before it counts as ghosted. 0 turns this off.
DEFAULT_GHOST_AFTER_DOWN_DAYS = 14
# How a ghosted status set by the sweep starts, so a posting that comes back can undo it without touching your own calls.
AUTO_GHOSTED = "The posting came down"
# How a pass set because a posting's deadline went by starts, so Undo pass sticks: the sweep passes on a job once.
AUTO_PASSED = "Passed automatically: its deadline"
# Jobs a passed deadline can still pass on: anything not yet sent.
NOT_SENT = ("new", "shortlisted", "needs_fix", "ready")
# How the sweep notes putting a closed prospect back, so a rescore can tell that from a status you set.
BACK_UP = "The posting is back up"
# Events Pyrite logs on a prospect by itself, which say nothing about whether you've acted on it. "seen" is the
# dashboard's marker for a prospect you've opened, and opening one isn't deciding about it.
UNPROMPTED_EVENTS = ("found", "linked", "reposted", "redated", "posting_down", "seen", REPLY_DETECTED)


def dedupe_key(company: str, title: str, description: str) -> str:
    """The same posting often appears once per city, with identical text."""
    norm = re.sub(r"\W+", " ", f"{company}|{title}|{description[:600]}").lower()
    return hashlib.sha1(norm.encode(), usedforsecurity=False).hexdigest()


def _watchlist(cfg: dict[str, Any]) -> list[tuple[str, str, Any]]:
    watch = cfg.get("watch", {})
    out = []
    for kind in sources.FEEDS:
        out += [(kind, board, name) for board, name in watch.get(kind, {}).items()]
    out += [("workday", tenant, spec) for tenant, spec in watch.get("workday", {}).items()]
    return out


def watch_problem(kind: str, ident: str, spec) -> str:
    """What's wrong with how one watched company is written in search.toml, or "" if nothing is. Workday needs a
    table of three settings, and the other boards a name, so the one written the other's way says which it needs."""
    if kind == "workday":
        if isinstance(spec, dict) and all(isinstance(spec.get(key), str) and spec[key].strip() for key in ("name", "wd", "site")):
            return ""
        return (f"[watch.workday] {ident} in profile/search.toml needs a name, wd and site, written as "
                f'{ident} = {{ name = "Company", wd = "wd1", site = "External" }}, with the wd and site from its careers page address.')
    if isinstance(spec, str) and spec.strip():
        return ""
    return f'[watch.{kind}] {ident} in profile/search.toml should be the company\'s name, written as {ident} = "Company".'


def watch_problems(cfg: dict[str, Any]) -> list[str]:
    """watch_problem for every watched company that has one."""
    return [problem for kind, ident, spec in _watchlist(cfg) if (problem := watch_problem(kind, ident, spec))]


def _company(ident: str, spec) -> str:
    """The company's name for a watched source, however its entry is written."""
    if isinstance(spec, dict):
        return str(spec.get("name") or ident)
    return str(spec or ident)


def check_patterns(cfg: dict[str, Any]) -> None:
    """Stop before reading any board when a pattern in search.toml can't be read, since it would fail every posting."""
    problems = scoring.pattern_problems(cfg)
    if problems:
        raise ConfigError(" ".join(problems) + " Fix it, then try again.")


def _is_candidate(title: str, location: str, cfg: dict[str, Any], workplace: str = "", company: str = "") -> bool:
    """Worth the slower call for a full description? A track limited to industries counts here, since the industry
    is judged from the description this would fetch."""
    if not scoring.match_track(title, cfg, {"company": company}, industry_unknown=True):
        return False
    if scoring.MULTI_LOCATION.match(location):
        return True
    return scoring.classify_location(location, workplace, cfg) != "out"


def _probe_workday(spec: dict[str, Any], open_ids: list[str], hits: dict[str, Any], deadline: float) -> tuple[list[str], list[str]]:
    """Ask Workday about each tracked posting its search left out. Returns the paths that are gone, and those still up.

    This runs with the other network calls, before anything is saved, so a slow board never
    holds the database. A posting it couldn't ask about is in neither list and stays as it was.
    """
    closed: list[str] = []
    live: list[str] = []
    for path in open_ids:
        if path in hits or time.monotonic() > deadline:
            continue
        try:
            gone = sources.is_workday_closed(spec, path)
        except Exception:  # A probe that fails leaves the job as it was.
            continue
        if gone is not None:
            (closed if gone else live).append(path)
    return closed, live


def _fetch_one(item: tuple[str, str, Any], cfg: dict[str, Any], known: set[str], rejected: set[str], deadline: float,
               open_ids: list[str] | None = None) -> dict[str, Any]:
    kind, ident, spec = item
    source_key = f"{kind}:{ident}"
    company = _company(ident, spec)
    result: dict[str, Any] = {"source_key": source_key, "company": company, "postings": [], "seen": [], "dates": {}, "error": "",
                              "complete": True, "closed": [], "live": []}
    # One entry written the wrong way fails only its own source, saying how to write it.
    result["error"] = watch_problem(kind, ident, spec)
    if result["error"]:
        return result
    if time.monotonic() > deadline:
        result["error"] = "Not reached before the pan's time limit."
        return result
    try:
        if kind == "workday":
            # Workday lists are search results, so absence doesn't mean a posting closed.
            result["complete"] = False
            spec = {**spec, "tenant": ident}
            hits = sources.workday_search(spec, cfg["workday"]["queries"], cfg["workday"]["max_pages"])
            result["seen"] = list(hits)
            today = date.today()
            result["dates"] = {path: sources.workday_posted_date(hit.get("postedOn"), today) for path, hit in hits.items()}
            for path, hit in hits.items():
                if path in known or path in rejected:
                    continue
                title, listed = hit.get("title", ""), hit.get("locationsText", "")
                # Some sites list a remote role under a city and say it's remote only in this field.
                workplace = str(hit.get("remoteType") or "").lower()
                if not _is_candidate(title, listed, cfg, workplace, company):
                    result["postings"].append(sources.Posting(source_key, path, company, title, listed, workplace))
                elif time.monotonic() < deadline:
                    try:
                        result["postings"].append(sources.workday_detail(spec, company, path))
                    except Exception:
                        pass  # Retried on the next sweep, since it was never recorded as rejected.
            result["closed"], result["live"] = _probe_workday(spec, open_ids or [], hits, deadline)
            return result

        postings = sources.FEEDS[kind](ident, company)
        result["seen"] = [p.source_id for p in postings]
        # Greenhouse and Lever report the date a listing was first created, which never moves.
        if kind == "ashby":
            result["dates"] = {p.source_id: p.posted_at for p in postings}
        for posting in postings:
            if posting.source_id in known or posting.source_id in rejected:
                continue
            if posting.description or not _is_candidate(posting.title, posting.location, cfg, company=company):
                result["postings"].append(posting)
            elif kind == "greenhouse" and time.monotonic() < deadline:
                try:
                    result["postings"].append(sources.greenhouse_detail(ident, company, posting.source_id))
                except Exception:
                    pass  # Retried on the next sweep.
    except Exception as err:  # Reported on the dashboard, so a dead source is never silent.
        result["error"] = f"{type(err).__name__}: {err}"[:300]
    return result


def run(conn, only: str | None = None, fresh: bool = False, cfg=None, max_minutes: float = 45) -> dict[str, Any]:
    cfg = cfg or load_config()
    check_patterns(cfg)
    started = now()
    run_id = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started,)).lastrowid
    if fresh:
        conn.execute("DELETE FROM rejected")
    _fill_in_existing(conn, cfg)
    # Before reading the boards, so a prospect this drops is already among the rejected ones the boards' listings skip.
    rescored = rescore_if_outdated(conn, cfg)
    conn.commit()

    known_rows = conn.execute(
        "SELECT source_key, source_id FROM jobs UNION SELECT source_key, source_id FROM listings"
    ).fetchall()
    known: dict[str, set[str]] = {}
    for row in known_rows:
        known.setdefault(row["source_key"], set()).add(row["source_id"])
    rejected: dict[str, set[str]] = {}
    for row in conn.execute("SELECT source_key, source_id FROM rejected"):
        rejected.setdefault(row["source_key"], set()).add(row["source_id"])

    # Postings each source should still have up. Workday is asked about the ones its search doesn't return.
    open_ids: dict[str, list[str]] = {}
    for row in conn.execute(
        f"SELECT source_key, source_id FROM jobs WHERE posting_closed_at IS NULL AND status IN ({','.join('?' * len(ACTIVE))})", ACTIVE
    ):
        open_ids.setdefault(row["source_key"], []).append(row["source_id"])

    items = _watchlist(cfg)
    if only:
        items = [item for item in items if only.lower() in f"{item[0]}:{item[1]}".lower()]

    deadline = time.monotonic() + max_minutes * 60
    stats = {"partial": bool(only), "sources": len(items), "failed": 0, "postings": 0, "new": 0,
             "rejected": {"title": 0, "location": 0, "score": 0, "not_open": 0, "scam": 0, "expired": 0},
             "closed": 0, "reposted": 0, "redated": 0, "new_ids": []}
    if rescored:
        stats["rescored"] = rescored

    # Light parallelism on purpose: heavier loads caused DNS failures across whole sources.
    # Results are saved as each source finishes, so an interrupted sweep keeps what it got.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                _fetch_one, item, cfg,
                known.get(f"{item[0]}:{item[1]}", set()),
                rejected.get(f"{item[0]}:{item[1]}", set()),
                deadline,
                open_ids.get(f"{item[0]}:{item[1]}", []),
            )
            for item in items
        ]
        for future in as_completed(futures):
            result = future.result()
            try:
                _save_result(conn, result, cfg, started, stats)
            except Exception as err:  # One board's bad data mustn't cost the sweep every board after it.
                conn.rollback()
                _save_result(conn, {**result, "error": f"Couldn't be saved. {type(err).__name__}: {err}"[:300]}, cfg, started, stats)

    stats["ghosted"] = len(settle_gone(conn, cfg))
    stats["expired"] = len(settle_expired(conn))
    conn.execute(
        "UPDATE runs SET finished_at = ?, stats = ? WHERE id = ?",
        (now(), json.dumps(stats), run_id),
    )
    conn.commit()
    return stats


def ghost_after_days(cfg: dict[str, Any]) -> int:
    return cfg["run"].get("ghost_after_down_days", DEFAULT_GHOST_AFTER_DOWN_DAYS)


def waiting_on_gone(job) -> bool:
    """A sent application whose posting is down and that you haven't updated since: no reply, decision or next step of your own."""
    return (job["status"] == "applied" and bool(job["posting_closed_at"])
            and (job["next_action"] or "") in ("", "Follow up"))


def settle_gone(conn, cfg: dict[str, Any]) -> list[int]:
    """Mark ghosted each sent application whose posting has been down for the set days with nothing heard.

    Mail the inbox flagged that you haven't dealt with yet holds a job back, since it may be the reply.
    """
    days = ghost_after_days(cfg)
    if not days:
        return []
    flagged = possible_replies(conn)
    settled = []
    for job in conn.execute("SELECT * FROM jobs WHERE status = 'applied' AND posting_closed_at IS NOT NULL").fetchall():
        if not waiting_on_gone(job) or job["id"] in flagged or (quiet_days_since(job["posting_closed_at"]) or 0) < days:
            continue
        down = date.fromisoformat(job["posting_closed_at"][:10])
        set_status(conn, job["id"], "ghosted",
                   f"{AUTO_GHOSTED} on {down:%b} {down.day} and nothing came back in {days} days. "
                   "Reopen it if they get in touch.", cfg["run"]["follow_up_days"])
        settled.append(job["id"])
    conn.commit()
    return settled


def settle_expired(conn, today: date | None = None) -> list[int]:
    """Pass on each job not yet sent whose firm deadline has gone by. A floor ("at least until") doesn't count, and a job
    you put back with Undo pass after the sweep passed on it is left alone from then on."""
    today = today or date.today()
    marks = ",".join("?" * len(NOT_SENT))
    passed = []
    for job in conn.execute(f"SELECT * FROM jobs WHERE status IN ({marks}) AND applied_at IS NULL", NOT_SENT).fetchall():
        info = deadline.for_job(job["description"] or "", ROOT / job["app_folder"] if job["app_folder"] else None, today)
        if not deadline.expired(info):
            continue
        if conn.execute("SELECT 1 FROM events WHERE job_id = ? AND kind = 'passed' AND detail LIKE ?",
                        (job["id"], AUTO_PASSED + "%")).fetchone():
            continue
        set_status(conn, job["id"], "passed",
                   f"{AUTO_PASSED}, {deadline.label(info['deadline'])}, has gone by. Undo the pass if it's still taking applications.")
        passed.append(job["id"])
    conn.commit()
    return passed


def gate(description: str, today: date | None = None) -> str:
    """Why a posting that passed the filters still isn't worth storing: "expired" when its own firm deadline has gone by,
    or nothing. Only a new posting is held to this. A rescore mustn't drop a job for a date: the sweep passes on those
    instead, so their record stays."""
    return "expired" if deadline.expired(deadline.for_job(description, None, today or date.today())) else ""


def _ghosted_by_sweep(conn, job_id: int) -> bool:
    last = conn.execute(
        f"SELECT kind, detail FROM events WHERE job_id = ? AND kind IN ({','.join('?' * len(STATUSES))}) ORDER BY id DESC LIMIT 1",
        (job_id, *STATUSES),
    ).fetchone()
    return bool(last and last["kind"] == "ghosted" and (last["detail"] or "").startswith(AUTO_GHOSTED))


def _save_result(conn, result, cfg, started, stats):
    key = result["source_key"]
    ts = now()
    if result["error"]:
        stats["failed"] += 1
        conn.execute(
            """INSERT INTO source_status (source_key, company, last_run, last_error, last_count)
               VALUES (?, ?, ?, ?, 0)
               ON CONFLICT (source_key) DO UPDATE SET last_run = excluded.last_run,
                   last_error = excluded.last_error, company = excluded.company""",
            (key, result["company"], ts, result["error"]),
        )
        conn.commit()
        return

    count = len(result["seen"])
    stats["postings"] += count
    # The first look at a board has no history, so duplicates it finds there can't be called reposts.
    tracked = conn.execute("SELECT tracked_since FROM source_status WHERE source_key = ?", (key,)).fetchone()
    baseline = not (tracked and tracked["tracked_since"])
    conn.execute(
        """INSERT INTO source_status (source_key, company, last_run, last_ok, last_error, last_count)
           VALUES (?, ?, ?, ?, '', ?)
           ON CONFLICT (source_key) DO UPDATE SET company = excluded.company, last_run = excluded.last_run,
               last_ok = excluded.last_ok, last_error = '', last_count = excluded.last_count""",
        (key, result["company"], ts, ts, count),
    )
    for source_id in result["seen"]:
        _mark_seen(conn, key, source_id, ts, cfg, stats)
    # A posting Workday confirmed is up counts as seen, though its search didn't return it. Otherwise
    # the same job turning up in another city would look like a repost of one that had gone.
    for source_id in result.get("live", []):
        conn.execute("UPDATE listings SET last_seen = ? WHERE source_key = ? AND source_id = ?", (ts, key, source_id))
        conn.execute("UPDATE jobs SET last_seen = ? WHERE source_key = ? AND source_id = ?", (ts, key, source_id))
    _note_redates(conn, result, cfg, ts, stats)

    for posting in result["postings"]:
        _ingest(conn, posting, cfg, stats, ts, key, started, baseline)

    _close_missing(conn, result, cfg, started, stats, ts)
    conn.execute("UPDATE source_status SET tracked_since = COALESCE(tracked_since, ?) WHERE source_key = ?", (ts, key))
    conn.commit()


def _job_id_for_listing(conn, key: str, source_id: str) -> int | None:
    row = conn.execute("SELECT job_id FROM listings WHERE source_key = ? AND source_id = ?", (key, source_id)).fetchone()
    if row:
        return row["job_id"]
    row = conn.execute("SELECT id FROM jobs WHERE source_key = ? AND source_id = ?", (key, source_id)).fetchone()
    return row["id"] if row else None


def _count_repost(conn, job_id: int, ts: str, detail: str, stats: dict[str, Any]) -> None:
    conn.execute("UPDATE jobs SET reposts = reposts + 1, last_reposted_at = ? WHERE id = ?", (ts, job_id))
    log_event(conn, job_id, "reposted", detail)
    stats["reposted"] += 1


def _reopen_if_closed(conn, job, ts: str) -> None:
    """A job the sweep closed because its posting vanished goes back on the radar. Your own decisions are left alone."""
    if job["status"] == "closed":
        conn.execute(
            "UPDATE jobs SET status = 'new', status_changed_at = ?, closed_out_at = NULL WHERE id = ?", (ts, job["id"])
        )
        log_event(conn, job["id"], "new", BACK_UP)
    elif job["status"] == "ghosted" and _ghosted_by_sweep(conn, job["id"]):
        # Only the sweep's own call is undone. A job you marked ghosted yourself stays that way.
        set_status(conn, job["id"], "applied", "The posting is back up, so this is waiting to hear again")


def _mark_seen(conn, key: str, source_id: str, ts: str, cfg: dict[str, Any], stats: dict[str, Any]) -> None:
    job_id = _job_id_for_listing(conn, key, source_id)
    if job_id is None:
        return
    conn.execute("UPDATE listings SET last_seen = ? WHERE source_key = ? AND source_id = ?", (ts, key, source_id))
    job = get_job(conn, job_id)
    if job["posting_closed_at"]:
        if quiet_days_since(job["posting_closed_at"]) >= cfg["freshness"]["came_back_after_days"]:
            _count_repost(conn, job_id, ts, "The same listing came back after being taken down", stats)
        _reopen_if_closed(conn, job, ts)
    conn.execute("UPDATE jobs SET last_seen = ?, posting_closed_at = NULL WHERE id = ?", (ts, job_id))


def _note_redates(conn, result: dict[str, Any], cfg: dict[str, Any], ts: str, stats: dict[str, Any]) -> None:
    """A listing whose posted date jumps forward is being made to look new."""
    key = result["source_key"]
    tolerance = cfg["freshness"]["redate_tolerance_days"]
    counted = set()
    for source_id, posted in result["dates"].items():
        listing = conn.execute("SELECT * FROM listings WHERE source_key = ? AND source_id = ?", (key, source_id)).fetchone()
        shown = scoring.parse_date(posted)
        if not listing or not shown:
            continue
        stored = scoring.parse_date(listing["posted_at"])
        if stored and (shown - stored).days <= tolerance:
            continue
        conn.execute("UPDATE listings SET posted_at = ? WHERE source_key = ? AND source_id = ?", (posted, key, source_id))
        if not stored:
            # A date that turns up later isn't a re-date, but it does give a job that had none an age.
            conn.execute("UPDATE jobs SET posted_at = COALESCE(posted_at, ?), first_posted_at = COALESCE(first_posted_at, ?) WHERE id = ?",
                         (posted, posted, listing["job_id"]))
            continue
        job_id = listing["job_id"]
        conn.execute("UPDATE jobs SET posted_at = ? WHERE id = ?", (posted, job_id))
        if job_id not in counted:
            counted.add(job_id)
            conn.execute("UPDATE jobs SET redates = redates + 1 WHERE id = ?", (job_id,))
            log_event(conn, job_id, "redated", f"The board moved its posted date from {stored} to {shown}")
            stats["redated"] += 1


def _fill_in(conn, row, cfg: dict[str, Any]) -> None:
    """Applications added before the sweep saw them have no score, track or fingerprint, so work those out from their text."""
    if not row["description"]:
        return
    if not row["dedupe_key"] and row["source_key"] != "manual":
        conn.execute("UPDATE jobs SET dedupe_key = ? WHERE id = ?",
                     (dedupe_key(row["company"], row["title"], row["description"]), row["id"]))
    if row["score"]:
        return
    verdict = scoring.evaluate(row["title"], row["location"], row["workplace"], row["description"],
                               {**cfg, "run": {**cfg["run"], "min_score": 0}}, row["company"])
    if verdict.keep:
        conn.execute(
            "UPDATE jobs SET score = ?, score_reasons = ?, track = ?, flags = ?, location_kind = ? WHERE id = ?",
            (verdict.score, json.dumps(verdict.reasons), verdict.track, json.dumps(verdict.flags), verdict.location_kind, row["id"]),
        )


def _fill_in_existing(conn, cfg: dict[str, Any]) -> None:
    for row in conn.execute("SELECT * FROM jobs WHERE score = 0 OR dedupe_key IS NULL").fetchall():
        _fill_in(conn, row, cfg)


def _norm_title(title: str) -> str:
    words = re.sub(r"\W+", " ", title).strip().lower().split()
    return " ".join(TITLE_WORDS.get(word, word) for word in words)


def requisition(source_key: str, source_id: str) -> str:
    """The requisition id in a Workday link, or nothing. Other boards keep it out of the link."""
    if not source_key.startswith("workday:"):
        return ""
    match = WORKDAY_REQUISITION.search(source_id or "")
    # A bare "_2" is a page counter, not an id.
    return match.group(1).upper() if match and len(re.sub(r"\D", "", match.group(1))) >= 4 else ""


def _requisition_twin(conn, key: str, posting):
    """A job already tracked under the same Workday requisition. A repost often comes back with its text or title
    rewritten, but the requisition id stays, so this catches what the text comparison can't."""
    wanted = requisition(key, posting.source_id)
    if not wanted:
        return None
    words = set(_norm_title(posting.title).split())
    for row in conn.execute(
        "SELECT jobs.*, listings.source_id AS listed_id FROM listings JOIN jobs ON jobs.id = listings.job_id WHERE listings.source_key = ?",
        (key,),
    ).fetchall():
        if row["listed_id"] == posting.source_id or requisition(key, row["listed_id"]) != wanted:
            continue
        others = set(_norm_title(row["title"]).split())
        if words and others and len(words & others) / len(words | others) >= SAME_REQUISITION_TITLE_OVERLAP:
            return get_job(conn, row["id"])
    return None


# Jobs you added yourself, never linked to a board, that are over: rejected, passed, withdrawn and so on. A board's
# posting with the same title is then a new opening, so it becomes a job of its own. Linked to the old one, or counted
# as its repost, it would take the old status and never reach the queue. A board's own jobs still keep their status
# across reposts, so a posting you passed on stays passed when it comes back.
_ADDED_AND_OVER = "source_key IN ('seed', 'manual') AND status NOT IN (" + ",".join(f"'{status}'" for status in ACTIVE) + ")"


def _attach_to_existing(conn, posting, ts, key, cfg) -> bool:
    """If you already added this job by hand and it's still in play, link it up rather than listing it twice."""
    for row in conn.execute(
        f"SELECT * FROM jobs WHERE company = ? AND source_key IN ('seed', 'manual') AND status IN ({','.join('?' * len(ACTIVE))})",
        (posting.company, *ACTIVE),
    ).fetchall():
        if _norm_title(row["title"]) != _norm_title(posting.title):
            continue
        posted = row["posted_at"] or posting.posted_at
        conn.execute(
            """UPDATE jobs SET source_key = ?, source_id = ?, last_seen = ?, url = ?, description = ?, comp = ?,
                   location = ?, posted_at = ?, first_posted_at = ? WHERE id = ?""",
            (key, posting.source_id, ts, row["url"] or posting.url, row["description"] or posting.description,
             row["comp"] or posting.comp, row["location"] or posting.location, posted, row["first_posted_at"] or posted, row["id"]),
        )
        record_listing(conn, row["id"], key, posting.source_id, posting.location, posting.posted_at, ts)
        log_event(conn, row["id"], "linked", "Matched to the live posting, so the sweep now watches whether it stays up")
        _fill_in(conn, get_job(conn, row["id"]), cfg)
        return True
    return False


def _same_text(one: str, other: str) -> bool:
    """Whether two descriptions share nearly all their vocabulary. With one of them empty there's nothing to compare."""
    words, others = set(re.findall(r"\w+", one.lower())), set(re.findall(r"\w+", other.lower()))
    if not words or not others:
        return True
    return len(words & others) / len(words | others) >= NEAR_TWIN_OVERLAP


def _exact_twin(conn, posting, fingerprint: str):
    """A job with the same opening text. The fingerprint reads only the first 600 characters, which many
    employers fill with the same paragraph about themselves, so the rest of the text has to agree too."""
    for row in conn.execute(f"SELECT * FROM jobs WHERE dedupe_key = ? AND NOT ({_ADDED_AND_OVER})", (fingerprint,)).fetchall():
        if _same_text(posting.description, row["description"]):
            return row
    return None


def _near_twin(conn, posting, started: str):
    """Reposts often come back lightly edited. A job that's still listed doesn't count, since two live ones may be two openings."""
    if not posting.description.strip():
        return None
    for row in conn.execute(
        f"SELECT * FROM jobs WHERE company = ? AND last_seen < ? AND description != '' AND NOT ({_ADDED_AND_OVER})",
        (posting.company, started),
    ).fetchall():
        if _norm_title(row["title"]) == _norm_title(posting.title) and _same_text(posting.description, row["description"]):
            return row
    return None


def _add_listing(conn, job, posting, fingerprint: str, ts: str, key: str, started: str, baseline: bool, stats: dict[str, Any]) -> None:
    """Another listing for a job already tracked: either the same job in another place, or a repost."""
    record_listing(conn, job["id"], key, posting.source_id, posting.location, posting.posted_at, ts)
    found_together = job["first_seen"] >= started
    another_place = job["last_seen"] >= started and posting.location != job["location"]
    if baseline or found_together or another_place:
        conn.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (ts, job["id"]))
        return

    # The job now follows its newest listing, so "posting down" reflects the one that's live.
    earliest = job["first_posted_at"] or job["posted_at"] or job["first_seen"]
    conn.execute(
        """UPDATE jobs SET source_key = ?, source_id = ?, dedupe_key = ?, url = COALESCE(NULLIF(?, ''), url),
               posted_at = COALESCE(?, posted_at), first_posted_at = ?, last_seen = ?, posting_closed_at = NULL WHERE id = ?""",
        (key, posting.source_id, fingerprint, posting.url, posting.posted_at, earliest, ts, job["id"]),
    )
    _count_repost(conn, job["id"], ts, f"Came back under a new listing, {posting.source_id}", stats)
    _reopen_if_closed(conn, job, ts)


def last_full_sweep(conn):
    """The latest sweep of every source. A retry of one board doesn't count as a fresh look."""
    for row in conn.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC"):
        stats = json.loads(row["stats"])
        # Runs from before sweeps recorded `partial` are told apart by size, as they were then.
        partial = stats["partial"] if "partial" in stats else stats.get("sources", 0) <= 1
        if not partial:
            return {**dict(row), "stats": stats}
    return None


def acted_on(conn, job) -> bool:
    """Whether you've done anything with a prospect beyond opening it: a note, a next step, a pick, a folder, a verdict,
    or any status of your own, such as one put back by Undo pass. Only the sweep's and the inbox's own events don't count.
    A prospect you've acted on is never dropped by a rescore, so its history stays."""
    if job["notes"] or job["next_action"] or job["priority"] or job["app_folder"] or job["fit"]:
        return True
    for event in conn.execute("SELECT kind, detail FROM events WHERE job_id = ?", (job["id"],)):
        if event["kind"] == "new" and event["detail"] == BACK_UP:
            continue
        if event["kind"] not in UNPROMPTED_EVENTS:
            return True
    return False


def rescore(conn, cfg=None) -> dict[str, Any]:
    """Re-apply the current scoring and filters to prospects: jobs still new, found on a board.

    Each one that passes gets its score and reasons again. One that no longer passes is dropped and remembered as
    rejected, unless you've acted on it: then it's left as it was and counted as held. `removed` names the dropped ones,
    since the record of each is gone. A posting you added is scored again too, and never dropped. Jobs past new, and
    ones you imported, keep the score they were decided on.
    Records that the prospects now have this code's scoring, so the next sweep doesn't do it again.
    """
    cfg = cfg or load_config()
    check_patterns(cfg)
    kept = dropped = held = 0
    removed = []
    _fill_in_existing(conn, cfg)
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND source_key NOT IN ('seed', 'manual')"
    ).fetchall()
    for row in rows:
        verdict = scoring.evaluate(row["title"], row["location"], row["workplace"], row["description"], cfg, row["company"])
        reason = quality.rejection(row["title"], row["description"] or "") if verdict.keep else verdict.reason
        if not reason:
            conn.execute(
                "UPDATE jobs SET score = ?, score_reasons = ?, track = ?, flags = ?, location_kind = ? WHERE id = ?",
                (verdict.score, json.dumps(verdict.reasons), verdict.track, json.dumps(verdict.flags), verdict.location_kind, row["id"]),
            )
            kept += 1
        elif acted_on(conn, row):
            held += 1
        else:
            conn.execute("DELETE FROM events WHERE job_id = ?", (row["id"],))
            conn.execute("DELETE FROM listings WHERE job_id = ?", (row["id"],))
            # A Claude run that failed to judge it still counts toward usage, and a mail warning naming it still stands.
            conn.execute("UPDATE claude_runs SET job_id = NULL WHERE job_id = ?", (row["id"],))
            conn.execute("UPDATE mail_alerts SET job_id = NULL WHERE job_id = ?", (row["id"],))
            conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
            conn.execute(
                "INSERT OR REPLACE INTO rejected (source_key, source_id, reason, ts) VALUES (?, ?, ?, ?)",
                (row["source_key"], row["source_id"], reason, now()),
            )
            dropped += 1
            removed.append(f"{row['company']}: {row['title']} ({reason.replace('_', ' ')})")
    for row in conn.execute("SELECT * FROM jobs WHERE status = 'new' AND source_key = 'manual'").fetchall():
        verdict = scoring.evaluate(row["title"], row["location"], row["workplace"], row["description"], cfg, row["company"],
                                   added=True)
        conn.execute(
            "UPDATE jobs SET score = ?, score_reasons = ?, track = ?, flags = ?, location_kind = ? WHERE id = ?",
            (verdict.score, json.dumps(verdict.reasons), verdict.track or scoring.ADDED_TRACK, json.dumps(verdict.flags),
             verdict.location_kind, row["id"]),
        )
        kept += 1
    set_meta(conn, SCORING_VERSION, str(scoring.VERSION))
    conn.commit()
    return {"kept": kept, "dropped": dropped, "held": held, "removed": removed}


def rescore_if_outdated(conn, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Rescore when this code scores postings differently from the scoring the database's prospects were given.
    Returns what `rescore` did and the versions, or None when the scores are already current."""
    before = scoring_version(conn)
    if before >= scoring.VERSION:
        return None
    return {**rescore(conn, cfg), "from": before, "to": scoring.VERSION}


def rescore_summary(result: dict[str, Any], names: int = 10) -> str:
    """What a sweep's automatic rescore did, naming the prospects it dropped, since nothing else of them is left."""
    def count(number: int) -> str:
        return f"{number} prospect{'' if number == 1 else 's'}"

    said = [f"Scoring changed in this version, so {count(result['kept'])} got new scores."]
    if result["dropped"]:
        named = result["removed"][:names] + ([f"{len(result['removed']) - names} more"] if len(result["removed"]) > names else [])
        said.append(f"Dropped {count(result['dropped'])} that no longer pass: {'; '.join(named)}.")
    if result.get("held"):
        said.append(f"Kept {count(result['held'])} you've acted on that no longer pass.")
    return " ".join(said)


def _ingest(conn, posting, cfg, stats, ts, key, started, baseline):
    if _job_id_for_listing(conn, key, posting.source_id) is not None:
        return
    if _attach_to_existing(conn, posting, ts, key, cfg):
        return

    verdict = scoring.evaluate(posting.title, posting.location, posting.workplace, posting.description, cfg, posting.company)
    # A posting can pass every filter and still be no opening: a talent pool, or a scam on a board you added. Or it can
    # be one too late to apply for.
    reason = (quality.rejection(posting.title, posting.description) or gate(posting.description)) if verdict.keep else verdict.reason
    if reason:
        stats["rejected"][reason] = stats["rejected"].get(reason, 0) + 1
        conn.execute(
            "INSERT OR REPLACE INTO rejected (source_key, source_id, reason, ts) VALUES (?, ?, ?, ?)",
            (key, posting.source_id, reason, ts),
        )
        return

    fingerprint = dedupe_key(posting.company, posting.title, posting.description)
    # One requisition is one job, on the first look at a board too, so its postings for other places don't list it twice.
    twin = _exact_twin(conn, posting, fingerprint) or _requisition_twin(conn, key, posting)
    if not twin and not baseline:
        twin = _near_twin(conn, posting, started)
    if twin:
        _add_listing(conn, twin, posting, fingerprint, ts, key, started, baseline, stats)
        return

    cursor = conn.execute(
        """INSERT INTO jobs (source_key, source_id, dedupe_key, company, title, location, location_kind, workplace,
               url, description, comp, posted_at, first_posted_at, first_seen, last_seen, score, score_reasons, track, flags,
               status, status_changed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
        (key, posting.source_id, fingerprint, posting.company, posting.title, posting.location,
         verdict.location_kind, posting.workplace, posting.url, posting.description, posting.comp,
         posting.posted_at, posting.posted_at, ts, ts, verdict.score, json.dumps(verdict.reasons), verdict.track,
         json.dumps(verdict.flags), ts),
    )
    record_listing(conn, cursor.lastrowid, key, posting.source_id, posting.location, posting.posted_at, ts)
    log_event(conn, cursor.lastrowid, "found", f"score {verdict.score}")
    stats["new"] += 1
    stats["new_ids"].append(cursor.lastrowid)


def _close_missing(conn, result, cfg, started, stats, ts):
    """Flag postings that came down, without touching where you are in the process."""
    key = result["source_key"]
    placeholders = ",".join("?" * len(ACTIVE))
    open_jobs = conn.execute(
        f"""SELECT id, source_id, status FROM jobs WHERE source_key = ? AND last_seen < ?
            AND posting_closed_at IS NULL AND status IN ({placeholders})""",
        (key, started, *ACTIVE),
    ).fetchall()
    if not open_jobs:
        return

    if result["complete"]:
        # An empty feed is more likely an outage or a moved board than every job closing at once.
        if not result["seen"]:
            return
        gone = list(open_jobs)
    else:
        # Only what the board itself confirmed is gone. That was asked before saving began.
        confirmed = set(result.get("closed", []))
        gone = [job for job in open_jobs if job["source_id"] in confirmed]

    for job in gone:
        conn.execute("UPDATE jobs SET posting_closed_at = ? WHERE id = ?", (ts, job["id"]))
        log_event(conn, job["id"], "posting_down", "No longer listed on the company's site")
        stats["closed"] += 1
        if job["status"] in ("new", "shortlisted", "needs_fix"):
            conn.execute(
                "UPDATE jobs SET status = 'closed', status_changed_at = ?, closed_out_at = ? WHERE id = ?",
                (ts, ts, job["id"]),
            )


def check_sources(cfg=None) -> list[dict[str, Any]]:
    """Try each watched source once and report how many postings it returned."""
    cfg = cfg or load_config()
    check_patterns(cfg)
    report = []

    def probe(item):
        kind, ident, spec = item
        name = _company(ident, spec)
        problem = watch_problem(kind, ident, spec)
        if problem:
            return {"source": f"{kind}:{ident}", "company": name, "ok": False, "error": problem}
        try:
            if kind == "workday":
                api, _ = sources.workday_base({**spec, "tenant": ident})
                page = cast(dict[str, Any], sources._request(f"{api}/jobs", {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}}, retries=0))
                count = page.get("total", 0)
            else:
                count = len(sources.FEEDS[kind](ident, name))
            return {"source": f"{kind}:{ident}", "company": name, "ok": True, "count": count}
        except Exception as err:
            return {"source": f"{kind}:{ident}", "company": name, "ok": False, "error": str(err)[:120]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        report = list(pool.map(probe, _watchlist(cfg)))
    return report
