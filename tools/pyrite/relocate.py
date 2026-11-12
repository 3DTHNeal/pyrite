"""Whether a job somewhere else pays enough to move for: its pay after tax and local prices, against what you earn now
where you live.

Two numbers answer it:

- The break-even: the pay there whose take-home, scaled by the difference in prices, equals your take-home now at
  home. Pay at it, and you'd live as you do now; above it, better.
- What the posting's range is worth in home dollars: the bottom, middle and top of it (from pay.parse), each taken home
  there and scaled back to home prices, beside your own take-home now.

Prices come in two views, from prices.py. All prices compares BEA's all-items price levels, as for someone whose
housing costs track the local market the way BEA's average household's do. Renting at market weighs housing at
`housing_share` of spending (30% unless set), since moving means paying today's rent or today's house prices there,
and the rest at all items with housing taken out. Taxes come from taxes.py, with its assumptions: wages only, the
standard deduction, the main payroll and local taxes.

Base pay only, on both sides. A bonus, equity or a signing bonus isn't counted, whatever the posting says, and
neither is the cost of moving itself. Remote jobs and jobs in your own area aren't compared: they don't ask you to move.
"""
from dataclasses import dataclass
from typing import Any

from . import pay, prices, taxes
from .score import ELSEWHERE, US_STATES

FILING_CHOICES = (("single", "Single"), ("married", "Married, filing jointly"))
HOUSING_CHOICES = (("rent", "I rent"), ("own", "I own"))
DEFAULT_HOUSING_SHARE = 30
# Location kinds that mean moving: kept though outside your area, or kept with no telling where it is.
MOVING_KINDS = (ELSEWHERE, "unknown")
NOT_COUNTED = "Base pay only: a bonus, equity, a signing bonus and the cost of moving aren't counted."


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """[relocation] from search.toml, with its defaults. current_pay is None until it's set."""
    raw = cfg.get("relocation") or {}
    current = raw.get("current_pay")
    share = raw.get("housing_share", DEFAULT_HOUSING_SHARE)
    local = raw.get("home_local_taxes")
    return {
        "current_pay": float(current) if isinstance(current, int | float) and not isinstance(current, bool) and current > 0 else None,
        "filing": raw.get("filing") if raw.get("filing") in dict(FILING_CHOICES) else "single",
        "housing": raw.get("housing") if raw.get("housing") in dict(HOUSING_CHOICES) else "rent",
        "housing_share": float(share) / 100 if isinstance(share, int | float) and not isinstance(share, bool) and 0 < share < 100
        else DEFAULT_HOUSING_SHARE / 100,
        # None while unset, when the home state's statewide local tax, if it has one, is counted. [] is none at all.
        "home_local_taxes": [str(key) for key in local if key in taxes.LOCAL] if isinstance(local, list) else None,
        "own_local_taxes": own_taxes(raw),
    }


def own_taxes(raw: dict[str, Any]) -> list[taxes.LocalTax]:
    """Your own local taxes from [relocation] own_local_taxes, leaving out any that can't be used: problems() names them."""
    entries = raw.get("own_local_taxes")
    found = []
    for entry in entries if isinstance(entries, list) else []:
        try:
            found.append(taxes.own_local_tax(entry if isinstance(entry, dict) else {}))
        except ValueError:
            continue
    return found


def problems(cfg: dict[str, Any]) -> list[str]:
    """What's wrong under [relocation], each a sentence naming the setting. Numbers are checked with the rest."""
    raw = cfg.get("relocation")
    if not isinstance(raw, dict):
        return []
    found = []
    for key, choices in (("filing", FILING_CHOICES), ("housing", HOUSING_CHOICES)):
        if key in raw and raw[key] not in dict(choices):
            found.append(f"{key} under [relocation] is {raw[key]!r}, which needs to be one of "
                         f"{', '.join(repr(value) for value, _label in choices)}.")
    share = raw.get("housing_share")
    if isinstance(share, int | float) and not isinstance(share, bool) and not 0 < share < 100:
        found.append(f"housing_share under [relocation] is {share}, which needs to be a percent between 0 and 100, as in 30.")
    local = raw.get("home_local_taxes")
    if local is not None:
        if not isinstance(local, list):
            found.append("home_local_taxes under [relocation] needs to be a list, as in [\"nyc\"].")
        else:
            unknown = [str(key) for key in local if key not in taxes.LOCAL]
            if unknown:
                found.append(f"home_local_taxes under [relocation] names {', '.join(map(repr, unknown))}, which Pyrite doesn't know. "
                             "`pyrite relocate --taxes` lists the ones it does.")
    own = raw.get("own_local_taxes")
    if own is not None:
        if not isinstance(own, list):
            found.append('own_local_taxes under [relocation] needs to be a list, as in [{ name = "Transit district tax", rate = 0.5 }].')
        else:
            for at, entry in enumerate(own, 1):
                try:
                    taxes.own_local_tax(entry if isinstance(entry, dict) else {})
                except ValueError as err:
                    found.append(f"own_local_taxes under [relocation], number {at}: {err}.")
    return found


@dataclass(frozen=True)
class Home:
    area: prices.Area
    state: str
    local: tuple[taxes.Local, ...]  # Keys of taxes.LOCAL, then your own.
    pay: float | None
    filing: str
    housing: str
    housing_share: float


def home(cfg: dict[str, Any]) -> Home | str:
    """Where you live and what you earn there, from [market] and [relocation], or a sentence saying what's missing."""
    market = cfg.get("market") or {}
    rules = settings(cfg)
    country = str(market.get("country") or "United States").strip().lower()
    if country not in ("us", "usa", "u.s.", "united states", "united states of america"):
        return "The relocation comparison covers the United States only, and [market] country names another."
    state_name = str(market.get("state") or "").strip()
    abbr = prices.state_code(state_name) if state_name else None
    area: prices.Area | None = prices.find_metro(str(market["metro"])) if market.get("metro") else None
    if market.get("metro") and area is None:
        return (f"Pyrite couldn't find the metro area '{market['metro']}' under [market] among BEA's. Write it as the BLS does, "
                "as in \"Madison, WI\".")
    if area is not None and abbr is None:
        abbr = area.states[0]
    if abbr is None:
        return "Set your metro area or state under [market] (Where you'll work, on the Profile tab), so Pyrite knows where home is."
    if area is None:
        area = prices.state(abbr)
    named = rules["home_local_taxes"]
    local = (*(named if named is not None else taxes.local_for(abbr, "")), *rules["own_local_taxes"])
    return Home(area, abbr, local, rules["current_pay"], rules["filing"], rules["housing"], rules["housing_share"])


def _ratios(home_area: prices.Area, there: prices.Area, share: float) -> dict[str, float]:
    weight = prices.about()["housing_weight"]
    housing = there.housing / home_area.housing
    rest = there.without_housing(weight) / home_area.without_housing(weight)
    return {"all": there.all_items / home_area.all_items, "housing": housing, "rent": share * housing + (1 - share) * rest}


def _tax_lines(result: taxes.TakeHome) -> list[dict[str, Any]]:
    return [{"label": label, "amount": round(amount)} for label, amount in result.lines if round(amount)]


def compare(place: prices.Found, comp: str, cfg: dict[str, Any], here: Home | None = None) -> dict[str, Any]:
    """The comparison for a job at `place` paying `comp` (a posting's pay text), as the job's panel and the command
    show it. Needs a Home with a current pay; ValueError says what's missing."""
    here = here or _home_or_raise(cfg)
    if here.pay is None:
        raise ValueError("Set your current pay under [relocation] current_pay (Settings › Relocation) to compare.")
    local = taxes.local_for(place.state, place.city)
    now = taxes.take_home(here.pay, here.state, here.filing, here.local)
    same = taxes.take_home(here.pay, place.state, here.filing, local)
    ratios = _ratios(here.area, place.area, here.housing_share)
    found = pay.parse(comp or "")
    in_dollars = found is not None and found.currency == "USD"
    points = [("Bottom", found.low), ("Middle", found.middle), ("Top", found.high)] if found and in_dollars else []
    if found and found.high == found.low:
        points = [("Stated pay", found.low)]
    views = []
    for view, label in (("all", "All prices"), ("rent", f"Renting at market ({here.housing_share:.0%} on housing)")):
        ratio = ratios[view]
        break_even = taxes.solve_wages(now.net * ratio, place.state, here.filing, local)
        shown = []
        for name, amount in points:
            net = taxes.take_home(amount, place.state, here.filing, local).net
            worth = net / ratio
            shown.append({"label": name, "pay": round(amount), "net": round(net), "worth": round(worth),
                          "change": round(worth / now.net - 1, 3)})
        views.append({"id": view, "label": label, "ratio": round(ratio, 4), "break_even": round(break_even, -2), "points": shown})
    lead = "rent" if here.housing == "rent" else "all"
    views.sort(key=lambda v: v["id"] != lead)
    return {
        "home": {"name": here.area.name, "state": here.state, "pay": round(here.pay), "net": round(now.net),
                 "taxes": _tax_lines(now), "local": [taxes.resolve(item).name for item in here.local]},
        "there": {"name": place.area.name, "kind": place.area.kind, "state": place.state, "said": place.said,
                  "places": place.places, "local": [taxes.resolve(item).name for item in local],
                  "same_pay_net": round(same.net), "same_pay_taxes": _tax_lines(same)},
        "prices": {"all": round(ratios["all"], 4), "housing": round(ratios["housing"], 4)},
        "views": views,
        "lead": lead,
        "range": {"low": round(found.low), "high": round(found.high), "currency": found.currency} if found else None,
        "summary": _summary(here, place, views[0], found, in_dollars),
        "notes": _notes(here, place, found, in_dollars),
        "about": prices.about(),
    }


def _home_or_raise(cfg: dict[str, Any]) -> Home:
    found = home(cfg)
    if isinstance(found, str):
        raise ValueError(found)
    return found


def _money(amount: float) -> str:
    return pay.money(amount)


def _summary(here: Home, place: prices.Found, lead: dict[str, Any], found: pay.Range | None, in_dollars: bool) -> str:
    view = "renting at market" if lead["id"] == "rent" else "on all prices"
    assert here.pay is not None
    said = f"To live as well in {place.area.name} as on your {_money(here.pay)} at home, you'd need about {_money(lead['break_even'])} ({view})."
    if not found:
        return f"{said} The posting gives no pay range to set against it."
    if not in_dollars:
        return f"{said} Its range is in {found.currency}, which isn't compared."
    middle = next((p for p in lead["points"] if p["label"] in ("Middle", "Stated pay")), None)
    if not middle:
        return said
    change = middle["change"]
    how = f"{abs(change):.0%} {'more' if change > 0 else 'less'} than you take home now" if abs(change) >= 0.005 else "about what you take home now"
    which = "Its stated pay" if middle["label"] == "Stated pay" else "The middle of its range"
    return f"{said} {which}, {_money(middle['pay'])}, is worth {_money(middle['worth'])} at home: {how}."


def _notes(here: Home, place: prices.Found, found: pay.Range | None, in_dollars: bool) -> list[str]:
    about = prices.about()
    notes = [NOT_COUNTED]
    if place.area.kind == "state":
        notes.append(f"{place.said} isn't one of a metro area's principal cities, so {place.area.name}'s average prices are used, "
                     "which run high for a small town.")
    if place.places > 1:
        notes.append(f"The posting names more than one place. This is for {place.said}.")
    if here.housing == "own":
        notes.append("You own your home, so All prices leads. If your housing costs are well under today's market, as with an "
                     "older mortgage, moving would cost you more than either view shows.")
    if found and not in_dollars:
        notes.append(f"The range is in {found.currency}, so it isn't turned into home dollars.")
    notes.append(f"Taxes: {here.filing} filer, wages only, the standard deduction, {taxes.FEDERAL_YEAR} federal tables and each "
                 "state's latest. Local taxes beyond the main ones are left out.")
    notes.append(f"Prices: BEA Regional Price Parities for {about['year']}, released {about['released']}. Housing is measured "
                 "from rents.")
    return notes


def for_job(job: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    """The comparison for a job's panel, or None for a job that doesn't ask you to move: remote, in your area, or with
    no place named. When it can't be worked out, {"problem": a sentence}."""
    if job.get("location_kind") not in MOVING_KINDS or not (job.get("location") or "").strip():
        return None
    try:
        return _for_job(job, cfg)
    except prices.Unavailable as err:
        return {"problem": f"Pyrite couldn't get BEA's price levels, which it downloads the first time: {err}"}


def _for_job(job: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    here = home(cfg)
    if isinstance(here, str):
        return {"problem": here}
    place = prices.find(job["location"])
    if place is None:
        return {"problem": f"Pyrite couldn't tell where \"{job['location']}\" is, so it can't compare pay there with yours."}
    if place.area.code == here.area.code:
        return None  # In your own area after all, so there's nothing to move for.
    if here.pay is None:
        return {"problem": "Set your current pay on the Settings tab, under Relocation, to see what this job is worth after "
                           "taxes and prices there.", "there": {"name": place.area.name}}
    return compare(place, job.get("comp") or "", cfg, here)


def text(result: dict[str, Any]) -> str:
    """The comparison as lines for a terminal."""
    if "problem" in result:
        return str(result["problem"])
    home_, there = result["home"], result["there"]
    lines = [result["summary"], ""]
    lines.append(f"Home: {home_['name']}, {_money(home_['pay'])}, taking home {_money(home_['net'])} a year.")
    lines.append(f"There: {there['name']}. The same pay there would take home {_money(there['same_pay_net'])}.")
    if there["local"]:
        lines.append(f"Local taxes there: {', '.join(there['local'])}.")
    lines.append(f"Prices there: {result['prices']['all'] - 1:+.1%} on everything, {result['prices']['housing'] - 1:+.1%} on housing.")
    for view in result["views"]:
        lines.append("")
        lines.append(f"{view['label']}: break-even pay {_money(view['break_even'])}")
        for point in view["points"]:
            lines.append(f"  {point['label']} {_money(point['pay'])}: takes home {_money(point['net'])}, worth "
                         f"{_money(point['worth'])} at home ({point['change']:+.0%})")
    lines.append("")
    lines += [f"- {note}" for note in result["notes"]]
    return "\n".join(lines)


def known_tax(key: str) -> dict[str, Any]:
    """One of Pyrite's own local taxes, as the Settings tab and `pyrite relocate --taxes` list it."""
    tax = taxes.LOCAL[key]
    where = ("anywhere in the state, unless a city's own applies" if tax.statewide
             else f"in {', '.join(tax.places)}" if tax.places else "")
    return {"key": key, "name": tax.name, "state": tax.state, "state_name": US_STATES.get(tax.state, tax.state),
            "year": tax.year, "rate": taxes.describe(tax), "where": where, "note": tax.note}


def own_entry(tax: taxes.LocalTax, entry: dict[str, Any]) -> dict[str, Any]:
    """One of your own local taxes, as search.toml has it and in words."""
    return {**{k: entry[k] for k in ("name", "rate", "over", "over_married", "base") if k in entry}, "said": taxes.describe(tax)}


def local_view(cfg: dict[str, Any]) -> dict[str, Any]:
    """Your local taxes at home and Pyrite's table to pick from, for the Settings tab."""
    raw = cfg.get("relocation") if isinstance(cfg.get("relocation"), dict) else {}
    assert isinstance(raw, dict)
    rules = settings(cfg)
    market = cfg.get("market") or {}
    state_name = str(market.get("state") or "").strip()
    abbr = prices.state_code(state_name) if state_name else None
    named = rules["home_local_taxes"]
    entries = [entry for entry in raw.get("own_local_taxes") or [] if isinstance(entry, dict)] \
        if isinstance(raw.get("own_local_taxes"), list) else []
    own = []
    for entry in entries:
        try:
            own.append(own_entry(taxes.own_local_tax(entry), entry))
        except ValueError:
            continue
    return {
        "named": named, "own": own, "unset": named is None,
        # While none are named, the home state's statewide one counts, so the page says which that is.
        "default": taxes.local_for(abbr, "") if abbr and named is None else [],
        "home": {"metro": market.get("metro") or "", "state": state_name},
        "table": [known_tax(key) for key in sorted(taxes.LOCAL, key=lambda k: (taxes.LOCAL[k].state, k))],
        "bases": taxes.OWN_BASES, "max_rate": taxes.OWN_MAX_RATE,
    }


def local_taxes_text(words: str = "") -> str:
    """The local taxes Pyrite knows that match `words`, or all of them, for choosing home_local_taxes."""
    keys = taxes.search_local(words)
    if not keys:
        return (f"Pyrite's table has no local tax matching \"{words}\". If you pay one, add it yourself under "
                "[relocation] own_local_taxes, or have Claude look it up: `pyrite relocate --research-taxes \"City, ST\"`.")
    lead = "Local income taxes Pyrite knows" + (f", matching \"{words}\"" if words else "")
    lines = [f"{lead}. Name the ones you pay at home under [relocation] home_local_taxes:", ""]
    for key in sorted(keys, key=lambda k: (taxes.LOCAL[k].state, k)):
        tax = known_tax(key)
        where = f" Charged {tax['where']}." if tax["where"] else ""
        lines.append(f"  {key:<14} {tax['state_name']}: {tax['name']}, {tax['rate']} ({tax['year']}).{where}")
    lines += ["", "One that isn't here, such as a district's, goes under own_local_taxes as a rate over a threshold:",
              '  own_local_taxes = [{ name = "Transit district tax", rate = 0.5, over = 0, base = "wages" }]',
              "`pyrite relocate --research-taxes \"City, ST\"` has Claude look up the ones where you live, with sources."]
    return "\n".join(lines)
