"""Deterministic filtering and ranking. Claude only judges what gets through here."""
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Any

from . import quality

# Which scoring the postings in a database were scored with. Raise it by one in any change that alters what `evaluate`,
# `quality.rejection` or `discover.gate` returns for a posting already stored: its score, reasons, flags, track, or whether
# it's kept. The next sweep then rescores the prospects nobody has acted on, so none keeps an old score or a reason in old
# words. Changes to `freshness`, `promotion` and `signals` don't need it, since the dashboard works those out afresh on
# every load.
VERSION = 3

FOREIGN = re.compile(
    r"\b(canada|canadian|toronto|vancouver,?\s*(bc|british)|montreal|ontario|(?<!new\s)mexico|brazil|argentina|colombia|"
    r"uk|u\.k\.|united kingdom|england|london|ireland|dublin|germany|munich|berlin|france|paris|spain|madrid|"
    r"italy|netherlands|amsterdam|sweden|stockholm|switzerland|zurich|poland|warsaw|romania|czech|prague|"
    r"israel|tel aviv|india|bengaluru|bangalore|hyderabad|karnataka|pune|chennai|china|shanghai|beijing|"
    r"shenzhen|taiwan|taipei|hsinchu|japan|tokyo|korea|seoul|singapore|malaysia|penang|kuala lumpur|philippines|"
    r"vietnam|thailand|indonesia|australia|sydney|melbourne|new zealand|emea|apac|latam|europe|asia|"
    r"portugal|lisbon|denmark|copenhagen|norway|oslo|finland|helsinki|austria|belgium|brussels|luxembourg|greece|"
    r"hungary|budapest|bulgaria|serbia|croatia|slovakia|slovenia|ukraine|estonia|latvia|lithuania|scotland|"
    r"turkey|istanbul|uae|united arab emirates|dubai|saudi arabia|egypt|south africa|nigeria|kenya|chile|"
    r"costa rica|uruguay|pakistan|bangladesh|sri lanka|hong kong)\b",
    re.I,
)
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
# A state as boards write it: the abbreviation in capitals, so "in" and "or" stay words, or the name in any case.
_STATE = rf"(?:(?:{'|'.join(US_STATES)})\b|(?i:{'|'.join(sorted(US_STATES.values(), key=len, reverse=True))})\b)"
US_MARKER = re.compile(r"\b(united states|u\.s\.a?\.?|usa|us)\b|\bremote\s*[-,:(]?\s*us\b", re.I)
REMOTE = re.compile(r"\b(remote|work from home|virtual|distributed|anywhere)\b", re.I)
# A remote role open only to one state or area: "Remote - CA", "REMOTE (Texas)", "Remote, MA" or "CA - Remote". Any two
# capitals after "Remote" count, as they always have, since a country code there is no better.
STATE_LIMITED = re.compile(
    rf"(?i:remote)\s*(?:[-–,:]\s*|\(\s*)(?:(?!US\b|USA\b)[A-Z]{{2}}\b|SF\b|(?i:bay area)|{_STATE})|{_STATE}\s*[-–(]\s*(?i:remote)\b"
)
# A US state just after a foreign place's name makes it the American namesake: Dublin, CA or Paris, Texas.
STATE_AFTER = re.compile(rf"[\s,(\-–]+({_STATE})")
# Unless that "state" is the country's own code, as in "Toronto, CA" or "Pune, IN". Ontario, CA is the Californian city,
# since boards write the province "ON" or in full.
COUNTRY_CODES = {
    "CA": ("canada", "canadian", "toronto", "vancouver", "montreal"),
    "DE": ("germany", "munich", "berlin"),
    "IN": ("india", "bengaluru", "bangalore", "hyderabad", "karnataka", "pune", "chennai"),
    "IL": ("israel", "tel aviv"),
    "CO": ("colombia",),
    "AR": ("argentina",),
    "ID": ("indonesia",),
}
MULTI_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)


@dataclass
class Verdict:
    keep: bool
    reason: str = ""
    score: int = 0
    track: str = ""
    location_kind: str = ""
    reasons: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _named(name: str) -> str:
    """A pattern for a plain name as a whole word, so "Acme" doesn't catch "Acmeville"."""
    return rf"(?<!\w){re.escape(name)}(?!\w)"


@lru_cache(maxsize=20000)
def _mentions(terms: tuple[str, ...], text: str) -> int:
    """Cached because the dashboard ranks every job on every refresh, and descriptions rarely change."""
    return sum(len(re.findall(term, text, re.I)) for term in terms)


def _in_industry(industry: dict[str, Any], job: dict[str, Any], mentions_needed: int) -> bool:
    """Postings have no industry field, so this judges from the employer and the text.

    A passing mention isn't enough: "customers in automotive and aerospace" doesn't make
    an automotive job, and neither does a degree list. A term in the employer's name or
    the title is.
    """
    company, title = job.get("company") or "", job.get("title") or ""
    if _any([_named(name) for name in industry.get("companies", [])], company):
        return True
    terms = industry.get("terms", [])
    if _any(terms, f"{company}\n{title}"):
        return True
    return _mentions(tuple(terms), job.get("description") or "") >= mentions_needed


def promotion(job: dict[str, Any], cfg: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    """Priority points for the cities and industries you named under [promote].

    Returns (points, the names that matched, reasons). Each list counts once, at its best
    match, so a posting naming five preferred cities doesn't outrank one naming the right one.
    """
    rules = cfg.get("promote") or {}
    points, names, reasons = 0, [], []

    location = job.get("location") or ""
    cities = [c for c in rules.get("cities", []) if re.search(c.get("match") or _named(c["name"]), location, re.I)]
    if cities:
        gained = max(c.get("points", rules.get("city_points", 0)) for c in cities)
        points += gained
        names += [c["name"] for c in cities]
        reasons.append(f"Preferred city {', '.join(c['name'] for c in cities)} {gained:+d}")

    needed = rules.get("mentions_needed", 3)
    industries = [i for i in rules.get("industry", []) if _in_industry(i, job, needed)]
    if industries:
        gained = max(i.get("points", rules.get("industry_points", 0)) for i in industries)
        points += gained
        names += [i["name"] for i in industries]
        reasons.append(f"Preferred industry {', '.join(i['name'] for i in industries)} {gained:+d}")

    return points, names, reasons


def freshness(job: dict[str, Any], cfg: dict[str, Any], today: date, swept_at: str | None = None) -> dict[str, Any]:
    """How new a listing is, how often it has come back, whether it's a real opening, and the priority that gives it.

    This only orders what you see. Whether a posting is kept stays with the filter score.
    Pass the whole row, since preferred industries are judged from the description. `swept_at`
    is when the latest full sweep started: a listing it didn't see is one nobody has confirmed is up.
    """
    rules = cfg["freshness"]
    # The earliest date on record, so a repost can't make an old job look new.
    first = parse_date(job.get("first_posted_at") or job.get("posted_at"))
    from_board = job.get("source_key") not in (None, "", "seed", "manual")
    # A board can move a date forward without Pyrite seeing it happen, but the job was up when the sweep first found it.
    # That's a floor only: with no date at all, the day it was found says nothing about how new it is.
    seen = parse_date(job.get("first_seen")) if from_board else None
    if first and seen and seen < first:
        first = seen
    age = max((today - first).days, 0) if first else None
    known_for = max((today - seen).days, 0) if seen else None
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
    promoted_points, promoted, promoted_reasons = promotion(job, cfg)
    reasons += promoted_reasons

    ghost = []
    if age is not None and age >= rules["ghost_age_days"]:
        ghost.append(f"listed for {age} days")
    elif age is None and known_for is not None and known_for >= rules["ghost_age_days"]:
        ghost.append(f"listed for at least {known_for} days")
    if changes >= rules["ghost_repost_count"]:
        ghost.append(f"reposted or re-dated {changes} times")
    elif changes and age is not None and age >= rules["ghost_age_if_reposted"]:
        ghost.append(f"reposted or re-dated after {age} days")
    # In the posting's own words. The sweep drops postings that say there's no opening; these are ones it kept or you added.
    description = job.get("description") or ""
    ghost += [said for said in (quality.not_an_opening(job.get("title") or "", description), quality.evergreen(description)) if said]
    unconfirmed = bool(from_board and swept_at and not job.get("posting_closed_at") and (job.get("last_seen") or "") < swept_at)

    return {
        "age_days": age,
        "rank": (job.get("score") or 0) + points - penalty + promoted_points,
        "promoted": promoted,
        "is_new": age is not None and age <= rules["new_days"] and not changes and not ghost and not unconfirmed,
        # The latest full sweep didn't see it: its board failed, left the watch list, or Workday's search left it out unanswered.
        "unconfirmed": unconfirmed,
        "scam_signs": list(quality.scam_signs(description)),
        "ghost_risk": bool(ghost),
        "ghost_reason": ", ".join(ghost),
        # Workday adds -1, -2 and so on to a link when a requisition has more than one posting. A hint, so it costs no points.
        "may_be_repost": not changes and (job.get("source_key") or "").startswith("workday:")
        and bool(re.search(r"_[^_/]*\d-\d{1,2}$", job.get("source_id") or "")),
        "freshness_reasons": reasons,
    }


def _any(patterns, text, flags=re.I):
    return any(re.search(p, text, flags) for p in patterns)


# What may come between plain words: spaces, commas, hyphens, periods and parentheses, so "St. Louis" matches
# "St Louis" and "Madison, WI" matches "Madison (WI)".
_BETWEEN = r"[\s,\-–.()]+"


def _words(words: list[str]) -> str:
    return _BETWEEN.join(re.escape(word) for word in words)


def _state_at_end(words: list[str]) -> tuple[list[str], str] | None:
    """The words before a US state that ends a place, such as "Madison, WI" or "Raleigh, North Carolina", and the
    state as its abbreviation. None when the place doesn't end in a state, or is only a state."""
    names = {name.lower(): abbr for abbr, name in US_STATES.items()}
    for size in (3, 2, 1):
        if len(words) > size:
            tail = " ".join(words[-size:])
            abbr = tail.upper() if size == 1 and tail.upper() in US_STATES else names.get(tail.lower())
            if abbr:
                return words[:-size], abbr
    return None


def plain_pattern(phrase: str, place: bool = False) -> str:
    """A pattern for words written plainly, such as "Springfield, IL" or "data engineer": each word whole, in any case,
    with any spaces, commas, hyphens, periods or parentheses between them. So "springfield il" and "Springfield,IL"
    match the first, and "Big Data Engineer" the second, but "Springfielder" and "data engineering" don't.

    A `place` that ends in a US state matches it written either way and on either side, so "Madison, WI" also matches
    "Madison, Wisconsin, United States" and "US-WI-Madison"."""
    words = re.findall(r"[^\s,\-–.()]+", str(phrase))
    if not words:
        return r"(?!)"
    split = _state_at_end(words) if place else None
    if not split:
        return rf"(?<!\w){_words(words)}(?!\w)"
    town, abbr = split
    state = rf"(?:{re.escape(abbr)}|{_words(US_STATES[abbr].split())})"
    return rf"(?<!\w)(?:{_words(town)}{_BETWEEN}{state}|{state}{_BETWEEN}{_words(town)})(?!\w)"


def _plain(value) -> list[str]:
    """A list of plain phrases from search.toml, tolerating one phrase written without the brackets."""
    return [value] if isinstance(value, str) else [str(item) for item in value or []]


def local_patterns(loc_cfg: dict[str, Any]) -> list[str]:
    """[location]'s patterns under `local`, and its plain place names under `places`, as patterns."""
    return list(loc_cfg.get("local", [])) + [plain_pattern(place, place=True) for place in _plain(loc_cfg.get("places"))]


def title_patterns(track: dict[str, Any]) -> list[str]:
    """A [[track]]'s patterns under `title`, and its plain job-title words under `titles`, as patterns."""
    return list(track.get("title", [])) + [plain_pattern(words) for words in _plain(track.get("titles"))]


def _foreign(text: str) -> bool:
    """Whether a place is outside the US. A foreign name with a US state after it is an American town of that name."""
    for found in FOREIGN.finditer(text):
        state = STATE_AFTER.match(text, found.end())
        if not state:
            return True
        abbr = state.group(1) if state.group(1) in US_STATES else ""
        if abbr and found.group(0).lower().split(",")[0] in COUNTRY_CODES.get(abbr, ()):
            return True
    return False


def classify_location(location: str, workplace: str, cfg: dict[str, Any]) -> str:
    """Return local, remote, unknown or out."""
    loc_cfg = cfg["location"]
    text = location or ""
    if _any(local_patterns(loc_cfg), text) or _any(loc_cfg.get("local_exact", []), text, flags=0):
        return "local"

    is_remote = workplace.lower() == "remote" or bool(REMOTE.search(text))
    if is_remote and loc_cfg.get("accept_remote", True):
        home, elsewhere = loc_cfg.get("remote_home"), loc_cfg.get("remote_elsewhere")
        if home is not None or elsewhere is not None:
            # Your own lists replace the built-in ones, which assume you're in the US.
            if _any(home or [], text):
                return "remote"
            return "out" if _any(elsewhere or [], text) else "remote"
        if US_MARKER.search(text):
            return "remote"
        # Out only when every place it names is: "San Francisco | Toronto" is open from San Francisco. A bare "Remote"
        # names no place, so "Remote | Toronto" is still Toronto's.
        places = [place for place in re.split(r"[|;]", text) if REMOTE.sub("", place).strip(" -–,:()/")]
        return "out" if places and all(_foreign(place) or STATE_LIMITED.search(place) for place in places) else "remote"

    if not text.strip() or MULTI_LOCATION.match(text):
        return "unknown"
    return "unknown" if loc_cfg.get("accept_relocation") else "out"


def _in_any_industry(names: list[str], job: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Whether the job is in one of the named [[promote.industry]] entries."""
    rules = cfg.get("promote", {})
    needed = rules.get("mentions_needed", 3)
    return any(_in_industry(i, job, needed) for i in rules.get("industry", []) if i["name"] in names)


ELSEWHERE_FLAG = "Outside your area"


def _abroad(location: str, loc_cfg: dict[str, Any]) -> bool:
    """Whether every place a posting names is in another country, by the lists that decide it for a remote role."""
    home, elsewhere = loc_cfg.get("remote_home"), loc_cfg.get("remote_elsewhere")
    if home is not None or elsewhere is not None:
        return not _any(home or [], location) and _any(elsewhere or [], location)
    places = [place for place in re.split(r"[|;]", location) if place.strip()]
    return bool(places) and all(_foreign(place) for place in places)


def kept_anywhere(company: str, title: str, location: str, cfg: dict[str, Any]) -> list[str]:
    """The industries marked `anywhere = true` that a posting is plainly in, which keep it wherever in your country
    the job is. A job abroad stays dropped.

    Plainly means its employer is listed or a term is in the employer's name or the title. Mentions in the description
    don't count here: moving is a lot to ask of a passing mention, and a board's listing has no description to read
    until the posting is already worth fetching.
    """
    if _abroad(location or "", cfg["location"]):
        return []
    job = {"company": company, "title": title, "description": ""}
    return [i["name"] for i in (cfg.get("promote") or {}).get("industry", [])
            if i.get("anywhere") is True and _in_industry(i, job, 1)]


def level(title: str, cfg: dict[str, Any]) -> str:
    """How senior a title reads: "top" for a level_top word, "mid" for a level_mid one, or "" for neither."""
    scoring = cfg["scoring"]
    # Grouped, so a pattern with alternatives such as "principal|staff" is whole words too, not "Principality".
    if _any([rf"\b(?:{p})\b" for p in scoring["level_top"]], title or ""):
        return "top"
    return "mid" if _any([rf"\b(?:{p})\b\.?" for p in scoring["level_mid"]], title or "") else ""


def match_track(title: str, cfg: dict[str, Any], job: dict[str, Any] | None = None, industry_unknown: bool = False) -> tuple[str, int] | None:
    """Return (track name, seniority points) for an eligible title, else None.

    A track with `industries` applies only to postings in one of those industries, judged
    the way promotion judges them: from the employer, the title and the description. `job`
    carries the employer and description; without it, such a track is skipped. With
    `industry_unknown`, as for a listing whose description hasn't been fetched yet, such a
    track counts as matching, so the description is fetched and the industry judged from it.
    """
    scoring = cfg["scoring"]
    if _any([rf"\b(?:{p})\b" for p in scoring["exclude_titles"]], title):
        return None
    seniority = level(title, cfg)
    top, mid = seniority == "top", seniority == "mid"
    level_points = 10 if top else 5 if mid else 0
    for track in cfg.get("track", []):  # A blank search.toml has none yet.
        if _any(title_patterns(track), title):
            if track.get("needs_level") and not (top or mid):
                continue
            if (track.get("industries") and not industry_unknown
                    and not (job and _in_any_industry(track["industries"], {**job, "title": title}, cfg))):
                continue
            return track["name"], level_points
    return None


def _tables(value) -> list[dict[str, Any]]:
    """The tables in a list from search.toml, passing over anything else written there."""
    return [item for item in value or [] if isinstance(item, dict)]


def _setting_patterns(cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Every pattern search.toml gives the filters and the ranking, as (where it's set, the pattern as it's used)."""
    loc, scoring, promote = cfg.get("location") or {}, cfg.get("scoring") or {}, cfg.get("promote") or {}
    found = [(f"{key} under [location]", p) for key in ("local", "local_exact", "remote_home", "remote_elsewhere")
             for p in loc.get(key) or []]
    for track in _tables(cfg.get("track")):
        found += [(f"title under the [[track]] named {track.get('name', '?')}", p) for p in track.get("title") or []]
    found += [(f"{key} under [scoring]", rf"\b(?:{p})\b") for key in ("exclude_titles", "level_top", "level_mid")
              for p in scoring.get(key) or []]
    found += [("keywords under [scoring]", entry[0]) for entry in scoring.get("keywords") or [] if entry]
    found += [("flags under [scoring]", entry[1]) for entry in scoring.get("flags") or [] if len(entry) > 1]
    found += [("cities under [promote]", city["match"]) for city in _tables(promote.get("cities")) if city.get("match")]
    for industry in _tables(promote.get("industry")):
        found += [(f"terms of the [[promote.industry]] named {industry.get('name', '?')}", p) for p in industry.get("terms") or []]
    return found


def pattern_problems(cfg: dict[str, Any]) -> list[str]:
    """Each pattern in search.toml that isn't a valid regular expression, naming its setting. One bad pattern would
    otherwise stop every posting from being judged, and look like every job board failing."""
    problems = []
    for where, pattern in _setting_patterns(cfg):
        try:
            re.compile(str(pattern))
        except re.error as err:
            shown = re.sub(r"^\\b\(\?:(.*)\)\\b$", r"\1", str(pattern))
            problems.append(f"{where} in profile/search.toml has '{shown}', which isn't a valid pattern ({err}).")
    return problems


def _matched_words(found: re.Match[str]) -> str:
    """The words a keyword matched, widened to whole words, as the score reason shows them.

    Showing the posting's own words rather than the pattern keeps a bad match visible:
    "pid" found inside "rapid" reads as "rapid", which is easy to spot and fix in the pattern.
    """
    text, start, end = found.string, found.start(), found.end()
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    while end < len(text) and text[end].isalnum():
        end += 1
    return " ".join(text[start:end].split()).lower()[:40]


def evaluate(title: str, location: str, workplace: str, description: str, cfg: dict[str, Any], company: str = "") -> Verdict:
    matched = match_track(title, cfg, {"company": company, "description": description})
    if not matched:
        return Verdict(False, "title")
    track, level_points = matched

    kind = classify_location(location, workplace, cfg)
    anywhere = kept_anywhere(company, title, location, cfg) if kind == "out" else []
    if kind == "out" and not anywhere:
        return Verdict(False, "location", track=track)

    reasons = [f"{track} title +25"]
    score = 25
    if level_points:
        score += level_points
        reasons.append(f"seniority +{level_points}")

    if anywhere:
        # Kept for its industry, with nothing for the place, so a local or remote role of the same kind still ranks above it.
        kind = "elsewhere"
        reasons.append(f"outside your area, kept for {', '.join(anywhere)} +0")
    else:
        location_points = {"local": 15, "remote": 10, "unknown": 3}[kind]
        score += location_points
        reasons.append(f"{kind} +{location_points}")

    body = f"{title}\n{description}"
    keyword_points = 0
    hits = []
    for pattern, weight in cfg["scoring"]["keywords"]:
        found = re.search(pattern, body, re.I)
        if found:
            keyword_points += weight
            hits.append(_matched_words(found))
    keyword_points = min(keyword_points, 40)
    score += keyword_points
    if hits:
        reasons.append(f"skills +{keyword_points}: " + ", ".join(hits[:8]))

    flags = [ELSEWHERE_FLAG] if anywhere else []
    for label, pattern, penalty in cfg["scoring"]["flags"]:
        if re.search(pattern, body, re.I):
            flags.append(label)
            score -= penalty
            reasons.append(f"{label.lower()} -{penalty}")

    score = max(0, min(100, score))
    if score < cfg["run"]["min_score"]:
        return Verdict(False, "score", score=score, track=track, location_kind=kind)
    return Verdict(True, "", score, track, kind, reasons, flags)
