"""What things cost in each US metro area and state, and which of them a posting's location names.

The price levels are the Bureau of Economic Analysis's Regional Price Parities (RPPs), shipped in rpp.json, which
tools/refresh_prices.py rebuilds from BEA's own files once a year. Each area has two: all items, and housing, which BEA
measures from rents. The US is 100 on both, so an area at 110 costs 10% more than the nation for the same things.

A location is read as places, each a city and a state: "Austin, TX", "Sunnyvale, California", "US-NY-New York",
"Hybrid - Boston, MA | Remote". A city that's one of a metro area's principal cities, as OMB lists them, is in that
metro, so Sunnyvale finds San Jose's. Anywhere else in a state, a smaller city or the countryside, gets the state's
level, which averages its cities and countryside together and so runs a little high for a rural place.
"""
import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .score import US_STATES

DATA = Path(__file__).with_name("rpp.json")
_NAMES = {name.lower(): abbr for abbr, name in US_STATES.items()}
# Words about how a job is worked, not where.
_MODE = re.compile(r"\b(?:remote|hybrid|on[\s-]?site|in[\s-]?office|in[\s-]?person|flexible|office|onsite|full[\s-]?time)\b", re.I)
_COUNTRY = re.compile(r",?\s*\b(?:united states(?: of america)?|u\.s\.a?\.?|usa|us)\b\.?", re.I)
# "US-CA-Mountain View", "USA-TX-Austin", "CA-San Jose".
_CODED = re.compile(r"^(?:US|USA)?-?([A-Z]{2})-(.+)$")
_SPLIT = re.compile(r"\s*(?:\||;|\bor\b|\n| / | & )\s*", re.I)
# Names a posting uses for a whole area, as the city its metro is named for.
_ALIASES = {
    "new york city": "new york", "nyc": "new york", "manhattan": "new york", "brooklyn": "new york", "queens": "new york",
    "bronx": "new york", "the bronx": "new york", "staten island": "new york",
    "bay area": "san francisco", "san francisco bay area": "san francisco", "sf": "san francisco", "silicon valley": "san jose",
    "washington dc": "washington", "washington d c": "washington", "dc": "washington",
    "dallas fort worth": "dallas", "dfw": "dallas", "twin cities": "minneapolis",
}
_ALIAS_STATES = {"new york": "NY", "san francisco": "CA", "san jose": "CA", "washington": "DC", "dallas": "TX",
                 "minneapolis": "MN"}


@dataclass(frozen=True)
class Area:
    code: str  # A metro area's five-digit CBSA code, or a state's two letters.
    name: str
    kind: str  # "metro" or "state"
    all_items: float
    housing: float
    states: tuple[str, ...]

    def without_housing(self, weight: float) -> float:
        """The price level of everything but housing: all items with housing's share taken out."""
        return (self.all_items - weight * self.housing) / (1 - weight)


@dataclass(frozen=True)
class Found:
    """Where a location was placed: the area whose prices apply, the state whose taxes do, and the city, if named."""
    area: Area
    state: str
    city: str
    said: str  # The place as the posting wrote it.
    places: int  # How many places the location names.


@functools.cache
def data() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return loaded


def about() -> dict[str, Any]:
    """The vintage and sources, for saying where the numbers come from."""
    found = data()
    return {"year": found["year"], "released": found["released"], "source": found["source"]["prices"],
            "housing_weight": found["housing_weight"]}


@functools.cache
def _areas() -> tuple[dict[str, Area], dict[str, Area], dict[tuple[str, str], str]]:
    """Metros by code, states by their two letters, and each (city, state) to the metro it's a principal city of."""
    found = data()
    states = {abbr: Area(abbr, US_STATES.get(abbr, abbr), "state", figures[0], figures[1], (abbr,))
              for abbr, figures in found["states"].items()}
    metros: dict[str, Area] = {}
    cities: dict[tuple[str, str], str] = {}
    for code, name, all_items, housing, principal in found["metros"]:
        in_states = tuple(name.rsplit(", ", 1)[-1].split("-"))
        metros[code] = Area(code, name, "metro", all_items, housing, in_states)
        # The cities in its name are principal cities too, and the only ones known when OMB's list has none. Which
        # state each is in, the name doesn't say.
        for city in name.rsplit(", ", 1)[0].split("-") if not principal else ():
            for state in in_states:
                cities.setdefault((city_key(city), state), code)
        for entry in principal:
            city, state = entry.split("|")
            cities[(city_key(city), state)] = code
    return metros, states, cities


def city_key(city: str) -> str:
    """A city's name as it's compared: lowercase, abbreviations spelled out, with no punctuation."""
    text = city.lower().replace("’", "'")
    text = re.sub(r"\bst\.?\s", "saint ", text)
    text = re.sub(r"\bft\.?\s", "fort ", text)
    text = re.sub(r"\bmt\.?\s", "mount ", text)
    text = re.sub(r"\s+city\s+of\b|\bcity of\s+", " ", text)
    text = " ".join(re.sub(r"[^a-z0-9' ]+", " ", text).split())
    if text in _ALIASES:
        return _ALIASES[text]
    text = re.sub(r"^greater\s+|\s+(?:metro(?:politan)?|metroplex)?\s*area$|\s+metro$", "", text)
    return _ALIASES.get(text, text)


def state_code(text: str) -> str | None:
    """A state's two letters, from its two letters or its name in any case."""
    text = " ".join(text.replace(".", "").split())
    if text.upper() in US_STATES and (text.isupper() or len(text) == 2):
        return text.upper()
    return _NAMES.get(text.lower())


def state(abbr: str) -> Area:
    return _areas()[1][abbr]


def metro(code: str) -> Area:
    return _areas()[0][code]


def metros() -> list[Area]:
    return list(_areas()[0].values())


def _one_place(text: str) -> tuple[str, str] | None:
    """(city, state) for one place, either of which may be "", or None when it names neither."""
    text = _COUNTRY.sub("", text)
    text = re.sub(r"\([^)]*\)", " ", text)
    text = _MODE.sub(" ", text)
    text = re.sub(r"\b\d{5}(?:-\d{4})?\b", " ", text)  # A ZIP code.
    text = text.strip(" -–—,:/")
    if not text:
        return None
    coded = _CODED.match(text)
    if coded and coded.group(1) in US_STATES:
        return coded.group(2).strip(" -,"), coded.group(1)
    text = re.sub(r"\s+[-–—]\s+", ", ", text)
    parts = [part.strip() for part in text.split(",") if part.strip()]
    for at in range(len(parts) - 1, -1, -1):
        abbr = state_code(parts[at])
        if abbr:
            return (parts[at - 1] if at else ""), abbr
    tail = re.fullmatch(r"(.+?)\s+([A-Z]{2})", parts[0]) if parts else None
    if tail and tail.group(2) in US_STATES:
        return tail.group(1), tail.group(2)
    return (parts[0], "") if parts else None


def places(location: str) -> list[tuple[str, str]]:
    """Each place a location names, as (city, state)."""
    found = []
    for part in _SPLIT.split(location or ""):
        place = _one_place(part)
        if place and place not in found:
            found.append(place)
    return found


def place(city: str, abbr: str) -> tuple[Area, str] | None:
    """The area a city and state are in, and the state, by the rules in this module's docstring. Without a state, a
    city is placed only if there's one metro it could be."""
    metros_by_code, states, cities = _areas()
    key = city_key(city) if city else ""
    if key and not abbr:
        abbr = _ALIAS_STATES.get(key, "")
        if not abbr:
            matches = {(code, state) for (name, state), code in cities.items() if name == key}
            if len(matches) == 1:
                only, abbr = next(iter(matches))
                return metros_by_code[only], abbr
            return None
    if not abbr or abbr not in states:
        return None
    code = cities.get((key, abbr)) if key else None
    return (metros_by_code[code] if code else states[abbr]), abbr


def find(location: str) -> Found | None:
    """Where a posting's location is, for its prices and taxes: the first place it names that's in a metro, or else
    the first it can place at all. None when it names nowhere that can be placed."""
    named = places(location)
    placed = []
    for city, abbr in named:
        where = place(city, abbr)
        if where:
            said = f"{city}, {abbr}" if city and abbr else city or US_STATES.get(abbr, abbr)
            placed.append(Found(where[0], where[1], city, said, len(named)))
    return next((f for f in placed if f.area.kind == "metro"), placed[0] if placed else None)


def _plain(name: str) -> str:
    return re.sub(r"\s+(msa|metropolitan statistical area|\(metropolitan statistical area\))$", "", " ".join(name.lower().split()))


def find_metro(wanted: str) -> Area | None:
    """A metro area by its name as BEA or the BLS writes it ("Madison, WI" or "Madison, WI MSA"), the start of that
    name, its CBSA code, or a principal city and state ("Sunnyvale, CA")."""
    metros_by_code = _areas()[0]
    wanted = (wanted or "").strip()
    code = re.fullmatch(r"C?(\d{4,5})", wanted)
    if code:
        digits = code.group(1)
        found = [area for c, area in metros_by_code.items() if c == digits or (len(digits) == 4 and c.startswith(digits))]
        return found[0] if len(found) == 1 else None
    plain = _plain(wanted)
    exact = [area for area in metros_by_code.values() if _plain(area.name) == plain]
    starts = exact or [area for area in metros_by_code.values() if _plain(area.name).startswith(plain)]
    if len(starts) == 1:
        return starts[0]
    placed = find(wanted)
    return placed.area if placed and placed.area.kind == "metro" else None
