"""Deterministic filtering and ranking. Claude only judges what gets through here."""
import re
from dataclasses import dataclass, field
from datetime import date

FOREIGN = re.compile(
    r"\b(canada|canadian|toronto|vancouver,?\s*(bc|british)|montreal|ontario|mexico|brazil|argentina|colombia|"
    r"uk|u\.k\.|united kingdom|england|london|ireland|dublin|germany|munich|berlin|france|paris|spain|madrid|"
    r"italy|netherlands|amsterdam|sweden|stockholm|switzerland|zurich|poland|warsaw|romania|czech|prague|"
    r"israel|tel aviv|india|bengaluru|bangalore|hyderabad|karnataka|pune|chennai|china|shanghai|beijing|"
    r"shenzhen|taiwan|taipei|hsinchu|japan|tokyo|korea|seoul|singapore|malaysia|penang|kuala lumpur|philippines|"
    r"vietnam|thailand|indonesia|australia|sydney|melbourne|new zealand|emea|apac|latam|europe|asia)\b",
    re.I,
)
US_MARKER = re.compile(r"\b(united states|u\.s\.a?\.?|usa|us)\b|\bremote\s*[-,:(]?\s*us\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|virtual|distributed|anywhere)\b", re.I)
STATE_LIMITED = re.compile(r"Remote\s*[-–]\s*(?!US\b|USA\b)(?:[A-Z]{2}\b|SF\b|Bay Area)")
MULTI_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    score: int = 0
    track: str = ""
    location_kind: str = ""
    reasons: list = field(default_factory=list)
    flags: list = field(default_factory=list)


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def freshness(job: dict, cfg: dict, today: date) -> dict:
    """How new a listing is, how often it has come back, and the priority that gives it.

    This only orders what you see. Whether a posting is kept stays with the filter score.
    """
    rules = cfg["freshness"]
    # The earliest date on record, so a repost can't make an old job look new.
    first = parse_date(job.get("first_posted_at") or job.get("posted_at"))
    age = max((today - first).days, 0) if first else None
    reposts, redates = job.get("reposts") or 0, job.get("redates") or 0
    changes = reposts + redates

    reasons = []
    points = 0
    if age is not None:
        points = next((p for limit, p in rules["age_points"] if age <= limit), rules["older_points"])
        reasons.append(f"Posted {age} days ago {points:+d}")
    penalty = min(reposts * rules["repost_penalty"] + redates * rules["redate_penalty"], rules["max_penalty"])
    if penalty:
        reasons.append(f"Reposted {reposts}, re-dated {redates} -{penalty}")

    ghost = []
    if age is not None and age >= rules["ghost_age_days"]:
        ghost.append(f"listed for {age} days")
    if changes >= rules["ghost_repost_count"]:
        ghost.append(f"reposted or re-dated {changes} times")
    elif changes and age is not None and age >= rules["ghost_age_if_reposted"]:
        ghost.append(f"reposted or re-dated after {age} days")

    return {
        "age_days": age,
        "rank": (job.get("score") or 0) + points - penalty,
        "is_new": age is not None and age <= rules["new_days"] and not changes,
        "ghost_risk": bool(ghost),
        "ghost_reason": ", ".join(ghost),
        # Workday adds -1, -2 and so on to a link when a requisition has more than one posting. A hint, so it costs no points.
        "may_be_repost": not changes and (job.get("source_key") or "").startswith("workday:")
        and bool(re.search(r"_[^_/]*\d-\d{1,2}$", job.get("source_id") or "")),
        "freshness_reasons": reasons,
    }


def _any(patterns, text, flags=re.I):
    return any(re.search(p, text, flags) for p in patterns)


def classify_location(location: str, workplace: str, cfg: dict) -> str:
    """Return local, remote, unknown or out."""
    loc_cfg = cfg["location"]
    text = location or ""
    if _any(loc_cfg["local"], text) or _any(loc_cfg.get("local_exact", []), text, flags=0):
        return "local"

    is_remote = workplace.lower() == "remote" or bool(REMOTE.search(text))
    if is_remote and loc_cfg.get("accept_remote", True):
        if US_MARKER.search(text):
            return "remote"
        return "out" if FOREIGN.search(text) or STATE_LIMITED.search(text) else "remote"

    if not text.strip() or MULTI_LOCATION.match(text):
        return "unknown"
    return "unknown" if loc_cfg.get("accept_relocation") else "out"


def match_track(title: str, cfg: dict) -> tuple[str, int] | None:
    """Return (track name, seniority points) for an eligible title, else None."""
    scoring = cfg["scoring"]
    if _any([rf"\b(?:{p})\b" for p in scoring["exclude_titles"]], title):
        return None
    top = _any([rf"\b{p}\b" for p in scoring["level_top"]], title)
    mid = _any([rf"\b{p}\b\.?" for p in scoring["level_mid"]], title)
    level_points = 10 if top else 5 if mid else 0
    for track in cfg["track"]:
        if _any(track["title"], title):
            if track.get("needs_level") and not (top or mid):
                continue
            return track["name"], level_points
    return None


def evaluate(title: str, location: str, workplace: str, description: str, cfg: dict) -> Verdict:
    matched = match_track(title, cfg)
    if not matched:
        return Verdict(False, "title")
    track, level_points = matched

    kind = classify_location(location, workplace, cfg)
    if kind == "out":
        return Verdict(False, "location", track=track)

    reasons = [f"{track} title +25"]
    score = 25
    if level_points:
        score += level_points
        reasons.append(f"seniority +{level_points}")

    location_points = {"local": 15, "remote": 10, "unknown": 3}[kind]
    score += location_points
    reasons.append(f"{kind} +{location_points}")

    body = f"{title}\n{description}"
    keyword_points = 0
    hits = []
    for pattern, weight in cfg["scoring"]["keywords"]:
        if re.search(pattern, body, re.I):
            keyword_points += weight
            hits.append(pattern.split("|")[0].replace("\\b", "").replace("\\", ""))
    keyword_points = min(keyword_points, 40)
    score += keyword_points
    if hits:
        reasons.append(f"skills +{keyword_points}: " + ", ".join(hits[:8]))

    flags = []
    for label, pattern, penalty in cfg["scoring"]["flags"]:
        if re.search(pattern, body, re.I):
            flags.append(label)
            score -= penalty
            reasons.append(f"{label.lower()} -{penalty}")

    score = max(0, min(100, score))
    if score < cfg["run"]["min_score"]:
        return Verdict(False, "score", score=score, track=track, location_kind=kind)
    return Verdict(True, "", score, track, kind, reasons, flags)
