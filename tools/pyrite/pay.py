"""What a posting pays, read from its pay text, and how that compares with what the same kind of role pays elsewhere.

Boards write pay every way there is: "$130,700 to $205,200 USD", "$257K – $285K • Offers Equity", "CA$250K – CA$535K",
"$45 - $60 an hour". This reads the first range, scales k and M, and turns an hourly, weekly or monthly figure into a
year's (2,080 working hours, 52 weeks, 12 months), so every range compares as annual pay.

The yardstick is the position, not you: the median middle of the ranges Pyrite has seen for postings like this one,
in the same track and at the same level (level_top or level_mid in the title), widening to the whole track and then
to every track while there are fewer than MIN_PEERS to compare with. Against that:

- Too low to bother: even the top of the range is under TOO_LOW of what the role typically pays in the middle.
  The employer has pitched the job well under the market, and the daily run doesn't spend Claude on judging it.
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

MIN_PEERS = 5
TOO_LOW = 0.75  # The top of the range under this share of the typical middle.
LOW = 0.8  # The middle under this share.
HIGH = 1.4
WIDE = 1.8
DEFAULT_POINTS = 5
PER_YEAR = {"hour": 2080, "week": 52, "month": 12, "year": 1}
LEVELS = {"top": "senior-most", "mid": "senior", "": "unlevelled"}

_AMOUNT = r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s?([kKmM](?![a-zA-Z]))?"
# The first amount, then optionally a second after a dash, "to" or anything a bad decode made of a dash.
_RANGE = re.compile(
    rf"(?<![A-Za-z])([A-Z]{{1,2}})?([$€£])\s?{_AMOUNT}"
    rf"(?:\s*(?:-|–|—|�|to|and)\s*(?:[A-Z]{{1,2}})?[$€£]?\s?{_AMOUNT})?"
)
_CODE = re.compile(r"\b(USD|CAD|AUD|NZD|EUR|GBP|CHF|SGD|INR|JPY)\b")
_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP"}
_PREFIX = {"US": "USD", "CA": "CAD", "C": "CAD", "A": "AUD", "AU": "AUD", "NZ": "NZD", "S": "SGD"}
_HOURLY = re.compile(r"\b(?:hour|hourly|hr)\b|/\s*h(?:ou)?r\b", re.I)
_WEEKLY = re.compile(r"\b(?:week|weekly|wk)\b", re.I)
_MONTHLY = re.compile(r"\b(?:month|monthly|mo)\b", re.I)


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
        return float(digits.replace(",", "")) * scale.get((unit or other or "").lower(), 1)

    # "$150-200k" means thousands at both ends.
    first = value(low, low_scale, high_scale)
    second = value(high, high_scale, low_scale) if high else first
    lo, hi = min(first, second), max(first, second)
    if _HOURLY.search(text):
        per = "hour"
    elif _WEEKLY.search(text):
        per = "week"
    elif _MONTHLY.search(text):
        per = "month"
    else:
        # A bare figure this small is an hourly rate: no salaried job pays $95 a year.
        per = "hour" if hi < 500 else "year"
    if hi * PER_YEAR[per] < 1000:
        return None  # A bonus percentage or a stipend, not pay.
    code = _CODE.search(text)
    currency = code[1] if code else _PREFIX.get(prefix or "", _SYMBOL[symbol]) if prefix else _SYMBOL[symbol]
    return Range(lo * PER_YEAR[per], hi * PER_YEAR[per], currency)


def settings(cfg: dict) -> dict:
    """[pay] from search.toml, with its defaults."""
    raw = cfg.get("pay") or {}
    return {"currency": str(raw.get("currency") or "USD").upper(), "points": int(raw.get("points", DEFAULT_POINTS))}


def _groups(track: str, level: str) -> list[str]:
    """The comparison groups for a posting, narrowest first."""
    return [f"{track}|{level}", track, "*"]


def peers(rows, currency: str = "USD") -> dict[str, tuple[float, int]]:
    """The median middle of the ranges seen in each comparison group: {group: (median, count)}. Each row needs comp,
    track and level, as `score.level` reads its title."""
    by_group: dict[str, list[float]] = {}
    for row in rows:
        found = parse(row["comp"] or "")
        if not found or found.currency != currency:
            continue
        for group in _groups(row["track"] or "", row["level"] or ""):
            by_group.setdefault(group, []).append(found.middle)
    return {group: (statistics.median(values), len(values)) for group, values in by_group.items()}


def money(amount: float, currency: str = "USD") -> str:
    """$185k, or CAD 185k for anything but dollars."""
    figure = f"{amount / 1000:,.0f}k"
    return f"${figure}" if currency == "USD" else f"{currency} {figure}"


def _yardstick(track: str, level: str, known: dict[str, tuple[float, int]]) -> tuple[float, int, str]:
    """The typical middle to compare with, how many postings it's from, and those postings in words."""
    words = [f"{LEVELS.get(level, level)} {track} postings", f"{track} postings", "postings across your tracks"]
    for group, said in zip(_groups(track, level), words, strict=True):
        median, count = known.get(group, (0.0, 0))
        if count >= MIN_PEERS and median:
            return median, count, f"{count} {said}"
    return 0.0, 0, ""


def judge(comp: str, track: str, level: str, cfg: dict, known: dict[str, tuple[float, int]]) -> dict:
    """What a posting's pay says about it. Returns pay_low and pay_high (a year's pay, or None), pay_too_low, pay_signs
    (each a label, a tone and a sentence for the dashboard), pay_points for its priority, and pay_reasons."""
    rules = settings(cfg)
    found = parse(comp)
    result: dict = {"pay_low": None, "pay_high": None, "pay_currency": None, "pay_too_low": False, "pay_signs": [],
                    "pay_points": 0, "pay_reasons": []}
    if not found:
        return result
    result.update({"pay_low": round(found.low), "pay_high": round(found.high), "pay_currency": found.currency})
    signs, points = result["pay_signs"], 0
    if found.currency != rules["currency"]:
        signs.append({"label": f"Paid in {found.currency}", "tone": "muted",
                      "detail": f"The range is in {found.currency}, so it isn't compared with the {rules['currency']} ranges Pyrite has seen."})
        return result
    span = f"{money(found.low)}–{money(found.high)}" if found.high > found.low else money(found.low)
    median, _, scope = _yardstick(track or "", level or "", known)
    if median:
        if found.high < median * TOO_LOW:
            result["pay_too_low"] = True
            signs.append({"label": "Too low to bother", "tone": "bad",
                          "detail": f"Even the top of {span} is under {TOO_LOW:.0%} of the {money(median)} typical of the {scope} "
                                    "Pyrite has seen. The daily run doesn't judge it unless you pick it."})
            points -= rules["points"] * 3
        elif found.middle < median * LOW:
            signs.append({"label": "Pays under the going rate", "tone": "warn",
                          "detail": f"The middle of {span} is {found.middle / median:.0%} of the {money(median)} typical of the {scope} Pyrite has seen."})
            points -= rules["points"]
        elif found.middle >= median * HIGH:
            signs.append({"label": "Pays well above similar roles", "tone": "info",
                          "detail": f"The middle of {span} is {found.middle / median:.1f}× the {money(median)} typical of the {scope} Pyrite has seen. "
                                    "That usually means a level above the title, a range set for a high-cost city, or a typo. "
                                    "Check the level before you count on it."})
    if found.low and found.high / found.low >= WIDE:
        signs.append({"label": "Wide range", "tone": "muted",
                      "detail": f"{span} spans more than one level. Ask early where you'd land in it."})
    result["pay_points"] = points
    if points:
        result["pay_reasons"].append(f"Pay {span} {points:+d}")
    return result
