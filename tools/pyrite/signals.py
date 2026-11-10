"""Pyrite's own read of a posting beyond its score: when it closes, what it pays, what it asks that nobody could have,
and how rare a role like it is where you live. All plain code, worked out afresh each time a job is shown or queued.

- Deadline (deadline.py): a firm deadline that has passed makes a job a pass, and one within [run] decide_days puts
  the tailor-or-pass decision in front of you while there's still time to tailor.
- Pay (pay.py): against what postings for the same kind of role, at the same level, pay. Too low to bother means the
  daily run doesn't spend Claude judging it.
- Skill ages (skillage.py): asks for more years of a skill than it has existed.
- Rarity: how many other postings in the same track, near you, Pyrite has seen lately. A role that rarely comes up
  where you live is worth more of a look than one that turns up every week, since there may not be another soon.
  Remote roles are never rare by this measure: they compete with the whole country, not your area. It waits until
  Pyrite has been watching long enough to know, and it only knows the boards you watch and the postings your filters
  kept, so it's a nudge to priority, not a verdict.

Pay and rarity add to a job's priority, beside its age and your [promote] cities and industries. None of it changes
the filter score, which still decides what's kept and tailored.
"""
import copy
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import deadline, pay, score, skillage

RARE_DAYS = 90
RARE_WATCHED_DAYS = 30
DEFAULT_RARE_MAX = 2
DEFAULT_RARE_POINTS = 5


@dataclass
class Context:
    """What judging one job needs to know about all the others."""
    today: date
    peers: dict[str, Any]
    local: Counter[str]
    watched_days: int | None
    decide_days: int


def decide_days(cfg: dict[str, Any]) -> int:
    return int((cfg.get("run") or {}).get("decide_days", deadline.DECIDE_DAYS))


def _recent(first_seen: str | None, today: date) -> bool:
    return bool(first_seen) and str(first_seen)[:10] >= (today - timedelta(days=RARE_DAYS)).isoformat()


def context(conn, cfg: dict[str, Any], today: date) -> Context:
    rows = [{**dict(row), "level": score.level(row["title"], cfg)}
            for row in conn.execute("SELECT title, track, location_kind, first_seen, comp FROM jobs")]
    local = Counter(row["track"] for row in rows if row["location_kind"] == "local" and row["track"] and _recent(row["first_seen"], today))
    first = conn.execute("SELECT MIN(started_at) FROM runs").fetchone()[0]
    watched = (today - date.fromisoformat(first[:10])).days if first else None
    return Context(today, pay.peers(rows, pay.settings(cfg)["currency"]), local, watched, decide_days(cfg))


def alone(cfg: dict[str, Any], today: date) -> Context:
    """A context that knows nothing of the other jobs, so pay is judged against your floor and target only, and nothing is rare."""
    return Context(today, {}, Counter(), None, decide_days(cfg))


def rarity(job: dict[str, Any], cfg: dict[str, Any], ctx: Context) -> dict[str, Any]:
    """Whether a local job is rare in its track, and the priority that earns it."""
    rules = cfg.get("freshness") or {}
    result = {"rare": False, "rare_reason": "", "rare_points": 0}
    track = job.get("track") or ""
    if job.get("location_kind") != "local" or not track or (ctx.watched_days or 0) < RARE_WATCHED_DAYS:
        return result
    others = ctx.local.get(track, 0) - (1 if _recent(job.get("first_seen"), ctx.today) else 0)
    if others > int(rules.get("rare_max", DEFAULT_RARE_MAX)):
        return result
    points = int(rules.get("rare_points", DEFAULT_RARE_POINTS))
    seen = "no other" if not others else f"only {others} other"
    reason = f"{seen} {track} role{'' if others == 1 else 's'} near you in {RARE_DAYS} days"
    return {"rare": True, "rare_reason": reason, "rare_points": points}


def read(job: dict[str, Any], cfg: dict[str, Any], ctx: Context, folder: Path | None) -> dict[str, Any]:
    """Everything this module knows about one job, and the priority points and reasons it adds."""
    description = job.get("description") or ""
    found = deadline.for_job(description, folder, ctx.today)
    found["deadline_expired"] = deadline.expired(found)
    found["decide_soon"] = deadline.decide_soon(found, ctx.decide_days)
    skills = copy.deepcopy(skillage.signals(description, ctx.today))  # Cached, so each job gets its own.
    # A note that only restates an ask nobody could meet isn't something to settle before applying.
    found["impossible_blockers"] = [b for b in found["blockers"] if skillage.only_restates(b, ctx.today)]
    found["blockers"] = [b for b in found["blockers"] if b not in found["impossible_blockers"]]
    money = pay.judge(job.get("comp") or "", job.get("track") or "", score.level(job.get("title") or "", cfg), cfg, ctx.peers)
    rare = rarity(job, cfg, ctx)
    reasons = list(money["pay_reasons"])
    if rare["rare"]:
        reasons.append(f"Rare near you, {rare['rare_reason']} {rare['rare_points']:+d}")
    return {**found, **skills, **money, **rare, "signal_points": money["pay_points"] + rare["rare_points"], "signal_reasons": reasons}


def apply(job: dict[str, Any], found: dict[str, Any]) -> dict[str, Any]:
    """The job with these signals in it, their points in its priority and their reasons with the others."""
    job.update(found)
    job["rank"] = (job.get("rank") or 0) + found["signal_points"]
    job["freshness_reasons"] = list(job.get("freshness_reasons") or []) + found["signal_reasons"]
    return job


def markings(job: dict[str, Any]) -> list[str]:
    """Lines for a triage run about the deadline, pay and rarity, in Pyrite's words. The skills' ages have their own section."""
    lines = []
    if job.get("deadline"):
        when = deadline.label(job["deadline"])
        days = job.get("days_to_deadline")
        if not job.get("deadline_firm", True):
            lines.append(f"- Deadline: applications accepted at least until {when}, a floor rather than a closing date")
        elif days is not None and days >= 0:
            lines.append(f"- Deadline: {when}, " + ("today" if days == 0 else f"in {days} day{'' if days == 1 else 's'}"))
    for sign in job.get("pay_signs") or []:
        lines.append(f"- Pay: {sign['label']}. {sign['detail']}")
    if job.get("rare"):
        lines.append(f"- Rare near the candidate: {job['rare_reason']}")
    return lines
