"""Pull postings from every watched company, filter, rank and store the keepers."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from . import score as scoring
from . import sources
from .store import ACTIVE, connect, get_job, load_config, log_event, now, quiet_days_since, record_listing

# How much of a posting's vocabulary must match for an edited repost to count as the same job.
NEAR_TWIN_OVERLAP = 0.85


def dedupe_key(company: str, title: str, description: str) -> str:
    """The same posting often appears once per city, with identical text."""
    norm = re.sub(r"\W+", " ", f"{company}|{title}|{description[:600]}").lower()
    return hashlib.sha1(norm.encode()).hexdigest()


def _watchlist(cfg: dict) -> list[tuple]:
    watch = cfg.get("watch", {})
    out = []
    for kind in sources.FEEDS:
        out += [(kind, board, name) for board, name in watch.get(kind, {}).items()]
    out += [("workday", tenant, spec) for tenant, spec in watch.get("workday", {}).items()]
    return out


def _is_candidate(title: str, location: str, cfg: dict) -> bool:
    """Worth the slower call for a full description?"""
    if not scoring.match_track(title, cfg):
        return False
    if scoring.MULTI_LOCATION.match(location):
        return True
    return scoring.classify_location(location, "", cfg) != "out"


def _fetch_one(item: tuple, cfg: dict, known: set, rejected: set, deadline: float) -> dict:
    kind, ident, spec = item
    source_key = f"{kind}:{ident}"
    company = spec["name"] if kind == "workday" else spec
    result = {"source_key": source_key, "company": company, "postings": [], "seen": [], "dates": {}, "error": "", "complete": True}
    if time.monotonic() > deadline:
        result["error"] = "Not reached before the sweep's time limit."
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
                if not _is_candidate(title, listed, cfg):
                    result["postings"].append(sources.Posting(source_key, path, company, title, listed))
                elif time.monotonic() < deadline:
                    try:
                        result["postings"].append(sources.workday_detail(spec, company, path))
                    except Exception:
                        pass  # Retried on the next sweep, since it was never recorded as rejected.
            return result

        postings = sources.FEEDS[kind](ident, company)
        result["seen"] = [p.source_id for p in postings]
        # Greenhouse and Lever report the date a listing was first created, which never moves.
        if kind == "ashby":
            result["dates"] = {p.source_id: p.posted_at for p in postings}
        for posting in postings:
            if posting.source_id in known or posting.source_id in rejected:
                continue
            if posting.description or not _is_candidate(posting.title, posting.location, cfg):
                result["postings"].append(posting)
            elif kind == "greenhouse" and time.monotonic() < deadline:
                try:
                    result["postings"].append(sources.greenhouse_detail(ident, company, posting.source_id))
                except Exception:
                    pass  # Retried on the next sweep.
    except Exception as err:  # Reported on the dashboard, so a dead source is never silent.
        result["error"] = f"{type(err).__name__}: {err}"[:300]
    return result


def run(only: str | None = None, fresh: bool = False, conn=None, cfg=None, max_minutes: float = 45) -> dict:
    cfg = cfg or load_config()
    conn = conn or connect()
    started = now()
    run_id = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started,)).lastrowid
    if fresh:
        conn.execute("DELETE FROM rejected")
    _fill_in_existing(conn, cfg)
    conn.commit()

    known_rows = conn.execute(
        "SELECT source_key, source_id FROM jobs UNION SELECT source_key, source_id FROM listings"
    ).fetchall()
    known: dict[str, set] = {}
    for row in known_rows:
        known.setdefault(row["source_key"], set()).add(row["source_id"])
    rejected: dict[str, set] = {}
    for row in conn.execute("SELECT source_key, source_id FROM rejected"):
        rejected.setdefault(row["source_key"], set()).add(row["source_id"])

    items = _watchlist(cfg)
    if only:
        items = [item for item in items if only.lower() in f"{item[0]}:{item[1]}".lower()]

    deadline = time.monotonic() + max_minutes * 60
    stats = {"partial": bool(only), "sources": len(items), "failed": 0, "postings": 0, "new": 0,
             "rejected": {"title": 0, "location": 0, "score": 0}, "closed": 0, "reposted": 0, "redated": 0, "new_ids": []}

    # Light parallelism on purpose: heavier loads caused DNS failures across whole sources.
    # Results are saved as each source finishes, so an interrupted sweep keeps what it got.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(
                _fetch_one, item, cfg,
                known.get(f"{item[0]}:{item[1]}", set()),
                rejected.get(f"{item[0]}:{item[1]}", set()),
                deadline,
            )
            for item in items
        ]
        for future in as_completed(futures):
            _save_result(conn, future.result(), cfg, started, stats)

    conn.execute(
        "UPDATE runs SET finished_at = ?, stats = ? WHERE id = ?",
        (now(), json.dumps(stats), run_id),
    )
    conn.commit()
    return stats


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


def _count_repost(conn, job_id: int, ts: str, detail: str, stats: dict) -> None:
    conn.execute("UPDATE jobs SET reposts = reposts + 1, last_reposted_at = ? WHERE id = ?", (ts, job_id))
    log_event(conn, job_id, "reposted", detail)
    stats["reposted"] += 1


def _reopen_if_closed(conn, job, ts: str) -> None:
    """A job the sweep closed because its posting vanished goes back on the radar. Your own decisions are left alone."""
    if job["status"] == "closed":
        conn.execute(
            "UPDATE jobs SET status = 'new', status_changed_at = ?, closed_out_at = NULL WHERE id = ?", (ts, job["id"])
        )
        log_event(conn, job["id"], "new", "The posting is back up")


def _mark_seen(conn, key: str, source_id: str, ts: str, cfg: dict, stats: dict) -> None:
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


def _note_redates(conn, result: dict, cfg: dict, ts: str, stats: dict) -> None:
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
            continue
        job_id = listing["job_id"]
        conn.execute("UPDATE jobs SET posted_at = ? WHERE id = ?", (posted, job_id))
        if job_id not in counted:
            counted.add(job_id)
            conn.execute("UPDATE jobs SET redates = redates + 1 WHERE id = ?", (job_id,))
            log_event(conn, job_id, "redated", f"The board moved its posted date from {stored} to {shown}")
            stats["redated"] += 1


def _fill_in(conn, row, cfg: dict) -> None:
    """Applications added before the sweep saw them have no score, track or fingerprint, so work those out from their text."""
    if not row["description"]:
        return
    if not row["dedupe_key"] and row["source_key"] != "manual":
        conn.execute("UPDATE jobs SET dedupe_key = ? WHERE id = ?",
                     (dedupe_key(row["company"], row["title"], row["description"]), row["id"]))
    if row["score"]:
        return
    verdict = scoring.evaluate(row["title"], row["location"], row["workplace"], row["description"],
                               {**cfg, "run": {**cfg["run"], "min_score": 0}})
    if verdict.keep:
        conn.execute(
            "UPDATE jobs SET score = ?, score_reasons = ?, track = ?, flags = ?, location_kind = ? WHERE id = ?",
            (verdict.score, json.dumps(verdict.reasons), verdict.track, json.dumps(verdict.flags), verdict.location_kind, row["id"]),
        )


def _fill_in_existing(conn, cfg: dict) -> None:
    for row in conn.execute("SELECT * FROM jobs WHERE score = 0 OR dedupe_key IS NULL").fetchall():
        _fill_in(conn, row, cfg)


def _norm_title(title: str) -> str:
    return re.sub(r"\W+", " ", title).strip().lower()


def _attach_to_existing(conn, posting, ts, key, cfg) -> bool:
    """If you already added this job by hand, link it up rather than listing it twice."""
    for row in conn.execute(
        "SELECT * FROM jobs WHERE company = ? AND source_key IN ('seed', 'manual')", (posting.company,)
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


def _near_twin(conn, posting, started: str):
    """Reposts often come back lightly edited. A job that's still listed doesn't count, since two live ones may be two openings."""
    words = set(re.findall(r"\w+", posting.description.lower()))
    if not words:
        return None
    for row in conn.execute(
        "SELECT * FROM jobs WHERE company = ? AND last_seen < ? AND description != ''", (posting.company, started)
    ).fetchall():
        if _norm_title(row["title"]) != _norm_title(posting.title):
            continue
        other = set(re.findall(r"\w+", row["description"].lower()))
        if len(words & other) / len(words | other) >= NEAR_TWIN_OVERLAP:
            return row
    return None


def _add_listing(conn, job, posting, fingerprint: str, ts: str, key: str, started: str, baseline: bool, stats: dict) -> None:
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
        if not stats.get("partial") and stats.get("sources", 0) > 1:
            return {**dict(row), "stats": stats}
    return None


def rescore(conn=None, cfg=None) -> dict:
    """Re-apply the current filters to postings you haven't acted on."""
    cfg = cfg or load_config()
    conn = conn or connect()
    kept = dropped = 0
    _fill_in_existing(conn, cfg)
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'new' AND source_key NOT IN ('seed', 'manual')"
    ).fetchall()
    for row in rows:
        verdict = scoring.evaluate(row["title"], row["location"], row["workplace"], row["description"], cfg)
        if verdict.keep:
            conn.execute(
                "UPDATE jobs SET score = ?, score_reasons = ?, track = ?, flags = ?, location_kind = ? WHERE id = ?",
                (verdict.score, json.dumps(verdict.reasons), verdict.track, json.dumps(verdict.flags), verdict.location_kind, row["id"]),
            )
            kept += 1
        else:
            conn.execute("DELETE FROM events WHERE job_id = ?", (row["id"],))
            conn.execute("DELETE FROM listings WHERE job_id = ?", (row["id"],))
            conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
            conn.execute(
                "INSERT OR REPLACE INTO rejected (source_key, source_id, reason, ts) VALUES (?, ?, ?, ?)",
                (row["source_key"], row["source_id"], verdict.reason, now()),
            )
            dropped += 1
    conn.commit()
    return {"kept": kept, "dropped": dropped}


def _ingest(conn, posting, cfg, stats, ts, key, started, baseline):
    if _job_id_for_listing(conn, key, posting.source_id) is not None:
        return
    if _attach_to_existing(conn, posting, ts, key, cfg):
        return

    verdict = scoring.evaluate(posting.title, posting.location, posting.workplace, posting.description, cfg)
    if not verdict.keep:
        stats["rejected"][verdict.reason] += 1
        conn.execute(
            "INSERT OR REPLACE INTO rejected (source_key, source_id, reason, ts) VALUES (?, ?, ?, ?)",
            (key, posting.source_id, verdict.reason, ts),
        )
        return

    fingerprint = dedupe_key(posting.company, posting.title, posting.description)
    twin = conn.execute("SELECT * FROM jobs WHERE dedupe_key = ?", (fingerprint,)).fetchone()
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
        tenant = key.split(":", 1)[1]
        spec = {**cfg["watch"]["workday"][tenant], "tenant": tenant}
        gone = [job for job in open_jobs if sources.is_workday_closed(spec, job["source_id"]) is True]

    for job in gone:
        conn.execute("UPDATE jobs SET posting_closed_at = ? WHERE id = ?", (ts, job["id"]))
        log_event(conn, job["id"], "posting_down", "No longer listed on the company's site")
        stats["closed"] += 1
        if job["status"] in ("new", "shortlisted", "needs_fix"):
            conn.execute(
                "UPDATE jobs SET status = 'closed', status_changed_at = ?, closed_out_at = ? WHERE id = ?",
                (ts, ts, job["id"]),
            )


def check_sources(cfg=None) -> list[dict]:
    """Try each watched source once and report how many postings it returned."""
    cfg = cfg or load_config()
    report = []

    def probe(item):
        kind, ident, spec = item
        name = spec["name"] if kind == "workday" else spec
        try:
            if kind == "workday":
                api, _ = sources.workday_base({**spec, "tenant": ident})
                count = sources._request(f"{api}/jobs", {"limit": 1, "offset": 0, "searchText": "", "appliedFacets": {}}, retries=0).get("total", 0)
            else:
                count = len(sources.FEEDS[kind](ident, name))
            return {"source": f"{kind}:{ident}", "company": name, "ok": True, "count": count}
        except Exception as err:
            return {"source": f"{kind}:{ident}", "company": name, "ok": False, "error": str(err)[:120]}

    with ThreadPoolExecutor(max_workers=3) as pool:
        report = list(pool.map(probe, _watchlist(cfg)))
    return report
