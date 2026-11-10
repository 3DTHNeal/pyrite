"""What a posting pays, read from its pay text, and how that compares with what the same kind of role pays elsewhere.

Boards write pay every way there is: "$130,700 to $205,200 USD", "$257K – $285K • Offers Equity", "CA$250K – CA$535K",
"$45 - $60 an hour". This reads the first range, scales k and M, and turns an hourly, daily, weekly or monthly figure
into a year's (2,080 working hours, 260 working days, 52 weeks, 12 months), so every range compares as annual pay. The
period is the one written beside the range, so "$120k-$160k/yr; contractors $90/hr" is a year's pay. A figure with three
places after a point ("$194.390") is a thousands separator typed wrong, and a range whose top is more than MAX_SPREAD
times its bottom isn't read at all, since one end of it has to be wrong.

The yardstick is the position, not you: the median middle of the ranges Pyrite has seen for other postings like this
one, in the same track and at the same level (level_top or level_mid in the title), widening to the whole track and
then to every track while there are fewer than MIN_PEERS to compare with. The posting itself is left out, so it isn't
measured partly against itself. The level is read as `level` says: "manager" in a Product or Program Manager's title
names the role rather than a rung, and an entry-level title is compared only with other entry-level ones, since
senior pay says nothing about what a junior role should pay. Against that:

- Too low to bother: even the top of the range is under TOO_LOW of what the role typically pays in the middle, at
  its own level. The employer has pitched the job well under the market, and the daily run doesn't spend Claude on
  judging it. Against a whole track or every track, which mix levels, it's only under the going rate.
- Under the going rate: the middle of the range is under LOW of the typical middle.
- Well above similar roles: the middle is HIGH or more of it. That usually means a level above the title, a range
  set for a high-cost city, or a typo, and any of those is worth knowing before you count on it.
- A wide range: the top is WIDE or more times the bottom, which spans more than one level.

None of it is proof. It's only as good as the postings seen so far, which are the ones your filters kept from the
boards you watch, so it waits until there are enough of them. A range in another currency isn't compared.
"""
import re
import statistics
from dataclasses import dataclass
from typing import Any

from . import score

MIN_PEERS = 5
TOO_LOW = 0.75  # The top of the range under this share of the typical middle.
LOW = 0.8  # The middle under this share.
HIGH = 1.4
WIDE = 1.8
MAX_SPREAD = 5  # A top over this many times the bottom is a misread or a typo, not a range.
DEFAULT_POINTS = 5
PER_YEAR = {"hour": 2080, "day": 260, "week": 52, "month": 12, "year": 1}
ENTRY = "entry"
LEVELS = {"top": "senior-most", "mid": "senior", ENTRY: "entry-level", "": "unlevelled"}
# A manager of a product, program or account, not of people: "manager" in level_top doesn't make these senior-most.
_ROLE_MANAGER = re.compile(
    r"\b(?:product|program|project|account|marketing|sales|community|partner|customer success)\s+manager\b", re.I)
_ENTRY = re.compile(
    r"\b(?:entry[\s-]*level|junior|jr\.?|intern(?:ship)?|new[\s-]*grad(?:uate)?|early[\s-]*career|apprentice(?:ship)?)(?!\w)", re.I)

_AMOUNT = r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?([kKmM](?![a-zA-Z]))?"
# The first amount, then optionally a second after a dash, "to" or anything a bad decode made of a dash.
_RANGE = re.compile(
    rf"(?<![A-Za-z])([A-Z]{{1,2}})?([$€£])\s?{_AMOUNT}"
    rf"(?:\s*(?:-|–|—|�|to|and)\s*(?:[A-Z]{{1,2}})?[$€£]?\s?{_AMOUNT})?"
)
_DOT_THOUSANDS = re.compile(r"\d{1,3}\.\d{3}")
_CODE = re.compile(r"\b(USD|CAD|AUD|NZD|EUR|GBP|CHF|SGD|INR|JPY|MXN|HKD|BRL)\b")
_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}
_PREFIX = {"US": "USD", "CA": "CAD", "C": "CAD", "A": "AUD", "AU": "AUD", "NZ": "NZD", "S": "SGD"}
_PERIODS = {
    "hour": re.compile(r"\b(?:hour|hourly|hr)\b", re.I),
    "day": re.compile(r"\b(?:day|daily|diem)\b", re.I),
    "week": re.compile(r"\b(?:week|weekly|wk)\b", re.I),
    "month": re.compile(r"\b(?:month|monthly|mo)\b", re.I),
    "year": re.compile(r"\b(?:year|yearly|yr|annual|annually|annum)\b", re.I),
}
# Where the words that go with a range stop: the next clause, line, sentence or figure.
_CLAUSE = re.compile(r"[;\n]|\.\s|[$€£]")


@dataclass(frozen=True)
class Range:
    low: float  # A year's pay, in `currency`.
    high: float
    currency: str

    @property
    def middle(self) -> float:
        return (self.low + self.high) / 2


def parse(text: str) -> Range | None:
    """The first pay range in the text, as a year's pay, or None if there's no figure to read."""
    text = (text or "").strip()
    found = _RANGE.search(text)
    if not found:
        return None
    prefix, symbol, low, low_scale, high, high_scale = found.groups()
    scale = {"k": 1e3, "m": 1e6}

    def value(digits: str, unit: str | None, other: str | None) -> float:
        unit = (unit or other or "").lower()
        if not unit and _DOT_THOUSANDS.fullmatch(digits):
            digits = digits.replace(".", "")  # No pay is written to a tenth of a cent, so "$194.390" is $194,390.
        return float(digits.replace(",", "")) * scale.get(unit, 1)

    # "$150-200k" means thousands at both ends.
    first = value(low, low_scale, high_scale)
    second = value(high, high_scale, low_scale) if high else first
    lo, hi = min(first, second), max(first, second)
    if lo and hi / lo > MAX_SPREAD:
        return None  # No real range spans that much: one end is a typo the text can't settle.
    # With no word for it, a bare figure this small is an hourly rate: no salaried job pays $95 a year.
    per = _period(text, found.start(), found.end()) or ("hour" if hi < 500 else "year")
    if hi * PER_YEAR[per] < 1000:
        return None  # A bonus percentage or a stipend, not pay.
    code = _CODE.search(text)
    if code:
        currency = code[1]
    elif prefix and symbol == "$":
        # Dollars of a country this doesn't know, such as MX$ or R$, are still not US dollars.
        currency = _PREFIX.get(prefix, f"{prefix}$")
    else:
        currency = _SYMBOL[symbol]
    return Range(lo * PER_YEAR[per], hi * PER_YEAR[per], currency)


def _period(text: str, start: int, end: int) -> str | None:
    """The period written with the range: the first one just after it, else the last one just before it, each within
    its own clause. Another figure's period, later in the text, isn't this one's."""
    after = _CLAUSE.split(text[end:end + 40], maxsplit=1)[0]
    hits = [(m.start(), per) for per, pattern in _PERIODS.items() if (m := pattern.search(after))]
    if hits:
        return min(hits)[1]
    before = re.split(r"[;\n]|\.\s", text[:start])[-1]
    hits = [(m.start(), per) for per, pattern in _PERIODS.items() for m in list(pattern.finditer(before))[-1:]]
    return max(hits)[1] if hits else None


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """[pay] from search.toml, with its defaults."""
    raw = cfg.get("pay") or {}
    return {"currency": str(raw.get("currency") or "USD").upper(), "points": int(raw.get("points", DEFAULT_POINTS))}


def level(title: str, cfg: dict[str, Any]) -> str:
    """How senior a title reads for pay: `score.level`, with a product, program or account manager's "manager" left
    out, and ENTRY for an entry-level title that names no higher rung."""
    title = _ROLE_MANAGER.sub(" ", title or "")
    return score.level(title, cfg) or (ENTRY if _ENTRY.search(title) else "")


def _groups(track: str, level: str) -> list[str]:
    """The comparison groups for a posting, narrowest first. An entry-level one is compared only with its own kind."""
    if level == ENTRY:
        return [f"{track}|{ENTRY}", f"*|{ENTRY}"]
    return [f"{track}|{level}", track, "*"]


def peers(rows, currency: str = "USD") -> dict[str, list[float]]:
    """The middles of the ranges seen in each comparison group, in order: {group: [middle, ...]}. Each row needs comp,
    track and level, as `level` reads its title. Every range counts toward its own level's group, its track and all
    tracks, an entry-level one too."""
    by_group: dict[str, list[float]] = {}
    for row in rows:
        found = parse(row["comp"] or "")
        if not found or found.currency != currency:
            continue
        track, rung = row["track"] or "", row["level"] or ""
        for group in dict.fromkeys([*_groups(track, rung), track, "*"]):
            by_group.setdefault(group, []).append(found.middle)
    return {group: sorted(values) for group, values in by_group.items()}


def money(amount: float, currency: str = "USD") -> str:
    """$185k, or CAD 185k for anything but dollars."""
    figure = f"{amount / 1000:,.0f}k"
    return f"${figure}" if currency == "USD" else f"{currency} {figure}"


def _yardstick(track: str, level: str, known: dict[str, list[float]], own: float | None = None) -> tuple[float, str, bool]:
    """The typical middle to compare with, the postings it's from in words, and whether they're at the posting's own
    level. `own` is the posting's own middle when it's among `known`, and it's left out."""
    said = LEVELS.get(level, level)
    words = ([f"other {said} {track} postings", f"other {said} postings"] if level == ENTRY
             else [f"other {said} {track} postings", f"other {track} postings", "other postings across your tracks"])
    for rank, (group, described) in enumerate(zip(_groups(track, level), words, strict=True)):
        values = list(known.get(group, []))
        if own is not None and own in values:
            values.remove(own)
        median = statistics.median(values) if len(values) >= MIN_PEERS else 0.0
        if median:
            return median, f"{len(values)} {described}", rank == 0 or level == ENTRY
    return 0.0, "", False


def judge(comp: str, track: str, level: str, cfg: dict[str, Any], known: dict[str, list[float]],
          counted: bool = False) -> dict[str, Any]:
    """What a posting's pay says about it. Returns pay_low and pay_high (a year's pay, or None), pay_too_low, pay_signs
    (each a label, a tone and a sentence for the dashboard), pay_points for its priority, and pay_reasons. `counted`
    says the posting's own range is among `known`, as it is when `known` was read from every tracked job."""
    rules = settings(cfg)
    found = parse(comp)
    result: dict[str, Any] = {"pay_low": None, "pay_high": None, "pay_currency": None, "pay_too_low": False, "pay_signs": [],
                    "pay_points": 0, "pay_reasons": []}
    if not found:
        return result
    result.update({"pay_low": round(found.low), "pay_high": round(found.high), "pay_currency": found.currency})
    signs, points = result["pay_signs"], 0
    if found.currency != rules["currency"]:
        signs.append({"label": f"Paid in {found.currency}", "tone": "muted",
                      "detail": f"The range is in {found.currency}, so it isn't compared with the {rules['currency']} ranges Pyrite has seen."})
        return result
    unit = found.currency
    span = f"{money(found.low, unit)}–{money(found.high, unit)}" if found.high > found.low else money(found.low, unit)
    median, scope, same_level = _yardstick(track or "", level or "", known, found.middle if counted else None)
    if median:
        # Too low means the daily run skips it, so that takes postings at its own level. A track or every track mixes
        # levels, and against those it can only be under the going rate.
        if found.high < median * TOO_LOW and same_level:
            result["pay_too_low"] = True
            signs.append({"label": "Too low to bother", "tone": "bad",
                          "detail": f"Even the top of {span} is under {TOO_LOW:.0%} of the {money(median, unit)} typical of the {scope} "
                                    "Pyrite has seen. The daily run doesn't judge it unless you pick it."})
            points -= rules["points"] * 3
        elif found.middle < median * LOW:
            signs.append({"label": "Pays under the going rate", "tone": "warn",
                          "detail": f"The middle of {span} is {found.middle / median:.0%} of the {money(median, unit)} typical of the {scope} "
                                    "Pyrite has seen."})
            points -= rules["points"]
        elif found.middle >= median * HIGH:
            signs.append({"label": "Pays well above similar roles", "tone": "info",
                          "detail": f"The middle of {span} is {found.middle / median:.1f}× the {money(median, unit)} typical of the {scope} Pyrite has seen. "
                                    "That usually means a level above the title, a range set for a high-cost city, or a typo. "
                                    "Check the level before you count on it."})
    if found.low and found.high / found.low >= WIDE:
        signs.append({"label": "Wide range", "tone": "muted",
                      "detail": f"{span} spans more than one level. Ask early where you'd land in it."})
    result["pay_points"] = points
    if points:
        result["pay_reasons"].append(f"Pay {span} {points:+d}")
    return result
