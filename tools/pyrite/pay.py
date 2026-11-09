"""What a posting pays, read from its pay text, and how that compares with what you'd take and what similar roles pay.

Boards write pay every way there is: "$130,700 to $205,200 USD", "$257K – $285K • Offers Equity", "CA$250K – CA$535K",
"$45 - $60 an hour". This reads the first range, scales k and M, and turns an hourly, weekly or monthly figure into a
year's (2,080 working hours, 52 weeks, 12 months), so every range compares as annual pay.

Three judgements come of it, and none involves a model:

- Against your [pay] floor: a range whose top is under it is too low to bother with. The sweep drops a new posting like
  that, and a job already further along is marked. The top of the range, not the bottom, because that's what a strong
  candidate can negotiate toward.
- Against your [pay] target: a range that starts at or above it is worth seeing sooner.
- Against similar roles: the middle of the range against the median of what Pyrite has seen for the same track. Far
  above that usually means the job sits a level above its title, the range covers a high-cost city, or the number is
  a typo, and any of those is worth knowing before you count on it. Far below means the employer pays under the going
  rate. Neither is proof: it's only as good as the postings seen so far, so it waits until there are enough of them.

A range wider than its bottom by more than WIDE spans more than one level. Ask early where you'd land in it.
"""
import re
import statistics
from dataclasses import dataclass

# Fewer postings than this with pay in a track, and the comparison uses every track, then nothing.
MIN_PEERS = 5
HIGH = 1.4  # The middle of the range this many times the median counts as well above similar roles.
LOW = 0.75
WIDE = 1.8  # Top over bottom.
DEFAULT_POINTS = 5
PER_YEAR = {"hour": 2080, "week": 52, "month": 12, "year": 1}

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
    """[pay] from search.toml, with its defaults. Floor and target are a year's pay; 0 means not set."""
    raw = cfg.get("pay") or {}
    return {
        "floor": float(raw.get("floor") or 0),
        "target": float(raw.get("target") or 0),
        "currency": str(raw.get("currency") or "USD").upper(),
        "points": int(raw.get("points", DEFAULT_POINTS)),
    }


def below_floor(comp: str, cfg: dict) -> bool:
    """Whether the whole range is under your floor, which the sweep treats as too low to bother with."""
    rules = settings(cfg)
    found = parse(comp)
    return bool(rules["floor"] and found and found.currency == rules["currency"] and found.high < rules["floor"])


def peers(rows, currency: str = "USD") -> dict[str, tuple[float, int]]:
    """The median middle of the ranges seen, by track, and under "*" for every track: {track: (median, count)}."""
    by_track: dict[str, list[float]] = {}
    for row in rows:
        found = parse(row["comp"] or "")
        if not found or found.currency != currency:
            continue
        by_track.setdefault(row["track"] or "", []).append(found.middle)
        by_track.setdefault("*", []).append(found.middle)
    return {track: (statistics.median(values), len(values)) for track, values in by_track.items()}


def money(amount: float, currency: str = "USD") -> str:
    """$185k, or CAD 185k for anything but dollars."""
    figure = f"{amount / 1000:,.0f}k"
    return f"${figure}" if currency == "USD" else f"{currency} {figure}"


def judge(comp: str, track: str, cfg: dict, known: dict[str, tuple[float, int]]) -> dict:
    """What a posting's pay says. Returns pay_low and pay_high (a year's pay, or None), pay_signs (each a label, a tone
    and a sentence for the dashboard), pay_points for its priority, and pay_reasons in the priority's words."""
    rules = settings(cfg)
    found = parse(comp)
    result: dict = {"pay_low": None, "pay_high": None, "pay_currency": None, "pay_signs": [], "pay_points": 0, "pay_reasons": []}
    if not found:
        return result
    result.update({"pay_low": round(found.low), "pay_high": round(found.high), "pay_currency": found.currency})
    signs, points = result["pay_signs"], 0
    if found.currency != rules["currency"]:
        signs.append({"label": f"Paid in {found.currency}", "tone": "muted",
                      "detail": f"The range is in {found.currency}, so it isn't compared with your {rules['currency']} figures."})
        return result
    span = f"{money(found.low)}–{money(found.high)}" if found.high > found.low else money(found.low)
    if rules["floor"] and found.high < rules["floor"]:
        signs.append({"label": "Under your floor", "tone": "bad",
                      "detail": f"It pays at most {money(found.high)}, under the {money(rules['floor'])} floor you set under [pay]."})
        points -= rules["points"] * 2
    elif rules["target"] and found.low >= rules["target"]:
        signs.append({"label": "Meets your target", "tone": "good",
                      "detail": f"Even the bottom of its range, {money(found.low)}, reaches your {money(rules['target'])} target."})
        points += rules["points"]
    median, count = known.get(track or "", (0.0, 0))
    scope = f"{count} {track} postings"
    if count < MIN_PEERS:
        median, count = known.get("*", (0.0, 0))
        scope = f"{count} postings across your tracks"
    if count >= MIN_PEERS and median:
        ratio = found.middle / median
        if ratio >= HIGH:
            signs.append({"label": "Pays well above similar roles", "tone": "info",
                          "detail": f"The middle of {span} is {ratio:.1f}× the {money(median)} typical of the {scope} Pyrite has seen. "
                                    "That usually means a level above the title, a range set for a high-cost city, or a typo. "
                                    "Check the level before you count on it."})
        elif ratio <= LOW:
            signs.append({"label": "Pays under the going rate", "tone": "warn",
                          "detail": f"The middle of {span} is {ratio:.0%} of the {money(median)} typical of the {scope} Pyrite has seen."})
            points -= rules["points"]
    if found.low and found.high / found.low >= WIDE:
        signs.append({"label": "Wide range", "tone": "muted",
                      "detail": f"{span} spans more than one level. Ask early where you'd land in it."})
    result["pay_points"] = points
    if points:
        result["pay_reasons"].append(f"Pay {span} {points:+d}")
    return result
