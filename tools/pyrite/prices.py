"""What things cost in each US metro area and state, and which of them a posting's location names.

The price levels are the Bureau of Economic Analysis's Regional Price Parities (RPPs). Each area has two: all items,
and housing, which BEA measures from rents. The US is 100 on both, so an area at 110 costs 10% more than the nation for
the same things. Metro areas are matched by their principal cities, from the Census Bureau's list of them under OMB's
delineation of the areas.

Neither list ships with Pyrite. The first comparison downloads both, from BEA and the Census Bureau, about 200 KB in
all, and keeps what it needs in the workspace's data/prices/rpp.json. That's looked for anew once it's RECHECK_DAYS old
(BEA publishes a year's figures each December), keeping the old copy if the download fails. `pyrite relocate
--refresh-prices` fetches them again now. So the repository holds no list of places, and a public copy of it says
nothing about where anyone who uses it lives.

A location is read as places, each a city and a state: "Austin, TX", "Sunnyvale, California", "US-NY-New York",
"Hybrid - Boston, MA | Remote". A city that's one of a metro area's principal cities is in that metro, so Sunnyvale
finds San Jose's. Anywhere else in a state, a smaller city or the countryside, gets the state's level, which averages
its cities and countryside together and so runs a little high for a rural place.
"""
import csv
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Government files over https, and Python's parser resolves no entities, so the standard library's will do.
from xml.etree import ElementTree

from . import store
from .score import US_STATES
from .sources import USER_AGENT

BEA = "https://apps.bea.gov/regional/zip/{table}.zip"
BEA_ABOUT = "https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area"
# OMB's delineation of the metro areas, which BEA's areas follow. A new one comes about every ten years: when BEA's
# footnote names a newer OMB bulletin, change this to that year's list 2.
CITIES = "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list2_2023.xlsx"
TIMEOUT = 30
RECHECK_DAYS = 60
RETRY_SECONDS = 3600  # After a failed download, how long before a comparison tries again.
ALL_ITEMS, GOODS, HOUSING, UTILITIES, OTHER = 1, 2, 3, 4, 5
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
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

Index = tuple[dict[str, "Area"], dict[str, "Area"], dict[tuple[str, str], str]]
_lock = threading.Lock()
_loaded: dict[str, Any] = {}
_failed_at: list[float] = []


class Unavailable(Exception):
    """The price levels couldn't be had, with the reason in words."""


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


def path() -> Path:
    return store.ROOT / "data" / "prices" / "rpp.json"


# ---- Fetching the lists ----

def _download(url: str) -> bytes:
    host = url.split("/")[2]
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body: bytes = response.read()
            return body
    except urllib.error.HTTPError as err:
        err.close()
        raise Unavailable(f"{host} answered {err.code}.") from err
    except OSError as err:
        raise Unavailable(f"Couldn't reach {host}: {getattr(err, 'reason', err)}") from err


def _bea_table(blob: bytes, prefix: str) -> tuple[dict[str, tuple[str, dict[int, float]]], str, str]:
    """One RPP table's areas by code, each its name and its figures by line code for the newest year with figures,
    then that year, and the release date from the table's 'Last updated' line."""
    label = prefix.strip("_")
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        name = next(n for n in archive.namelist() if n.startswith(prefix) and n.endswith(".csv"))
        text = archive.read(name).decode("latin-1")
    except (zipfile.BadZipFile, StopIteration, KeyError) as err:
        raise Unavailable(f"BEA's {label} download wasn't the zip of tables it should be.") from err
    rows = [row for row in csv.DictReader(io.StringIO(text)) if (row.get("LineCode") or "").strip()]
    years = [key for key in rows[0] if key and key.isdigit()] if rows else []
    year = max((y for y in years if re.fullmatch(r"[\d.]+", (rows[0][y] or "").strip())), default="")
    if not year:
        raise Unavailable(f"BEA's {label} table had no year of figures in it.")
    areas: dict[str, tuple[str, dict[int, float]]] = {}
    for row in rows:
        code = row["GeoFIPS"].strip().strip('"')
        _name, lines = areas.setdefault(code, (row["GeoName"].strip().rstrip(" *"), {}))
        try:
            lines[int(row["LineCode"])] = float(row[year])
        except (TypeError, ValueError):
            pass  # (NA): not published for this area.
    updated = next((line.strip('"') for line in text.splitlines() if "Last updated" in line), "")
    return areas, year, updated.replace("Last updated: ", "").split("--")[0].strip()


def _housing_weight(areas: list[dict[int, float]]) -> float:
    """Housing's share of the all-items index, by least squares: all items against goods, housing, utilities and other
    services, across every area. BEA publishes no single national weight, and the renting view needs one."""
    rows = [[a[GOODS], a[HOUSING], a[UTILITIES], a[OTHER], a[ALL_ITEMS]] for a in areas
            if all(k in a for k in (ALL_ITEMS, GOODS, HOUSING, UTILITIES, OTHER))]
    n = 4
    m = [[sum(r[i] * r[j] for r in rows) for j in range(n)] + [sum(r[i] * r[n] for r in rows)] for i in range(n)]
    for i in range(n):  # The normal equations, by elimination: four unknowns need nothing more.
        pivot = max(range(i, n), key=lambda k: abs(m[k][i]))
        m[i], m[pivot] = m[pivot], m[i]
        if not m[i][i]:
            raise Unavailable("BEA's tables didn't have the parts of all items that housing's weight is worked out from.")
        for k in range(n):
            if k != i:
                factor = m[k][i] / m[i][i]
                m[k] = [a - factor * b for a, b in zip(m[k], m[i], strict=True)]
    weights = [m[i][n] / m[i][i] for i in range(n)]
    share = weights[1] / sum(weights)
    if not 0.05 < share < 0.4:
        raise Unavailable(f"Housing's weight in all items came out at {share:.2f}, which can't be right, so the figures weren't used.")
    return round(share, 3)


def _principal_cities(blob: bytes) -> list[tuple[str, str, str]]:
    """(CBSA code, city, state FIPS code) for every metropolitan area's principal cities, from the Census's list 2."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        strings = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))  # noqa: S314
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))  # noqa: S314
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as err:
        raise Unavailable("The Census Bureau's list of principal cities wasn't the spreadsheet it should be.") from err
    shared = ["".join(t.text or "" for t in si.iter(f"{SHEET}t")) for si in strings.findall(f"{SHEET}si")]
    found = []
    for row in sheet.iter(f"{SHEET}row"):
        cells = {}
        for cell in row.findall(f"{SHEET}c"):
            value = cell.find(f"{SHEET}v")
            text = value.text if value is not None and value.text else ""
            if cell.get("t") == "s" and text.isdigit() and int(text) < len(shared):
                text = shared[int(text)]
            cells[re.sub(r"\d+", "", cell.get("r", ""))] = text
        if re.fullmatch(r"\d{5}", cells.get("A", "")) and cells.get("C", "").startswith("Metropolitan"):
            found.append((cells["A"], cells.get("D", ""), cells.get("E", "").zfill(2)))
    return found


def build(fetch: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """The price levels and principal cities as Pyrite keeps them, from BEA's and the Census Bureau's own files.
    `fetch` downloads one address, for tests. Raises Unavailable for a download that fails or isn't what it should be."""
    fetch = fetch or _download
    metros, year, released = _bea_table(fetch(BEA.format(table="MARPP")), "MARPP_")
    states, state_year, _ = _bea_table(fetch(BEA.format(table="SARPP")), "SARPP_")
    if state_year != year:
        raise Unavailable(f"BEA's metro table runs to {year} and its state table to {state_year}, so they don't match yet.")
    abbr = {name: code for code, name in US_STATES.items()}
    fips = {code[:2]: abbr[name] for code, (name, _lines) in states.items() if name in abbr}
    cities: dict[str, list[str]] = {}
    for cbsa, city, state in _principal_cities(fetch(CITIES)):
        if state in fips and city:
            cities.setdefault(cbsa, []).append(f"{city}|{fips[state]}")
    shown = lambda lines: [round(lines[ALL_ITEMS], 3), round(lines[HOUSING], 3)]
    out_states = {abbr[name]: shown(lines) for name, lines in states.values()
                  if name in abbr and ALL_ITEMS in lines and HOUSING in lines}
    out_metros: list[list[Any]] = []
    for code, (name, lines) in sorted(metros.items()):
        if name.endswith("(Metropolitan Statistical Area)") and ALL_ITEMS in lines and HOUSING in lines:
            out_metros.append([code, name.replace(" (Metropolitan Statistical Area)", ""), *shown(lines), cities.get(code, [])])
    if len(out_states) < len(US_STATES) or not out_metros:
        raise Unavailable("BEA's tables were missing states or metro areas, so they weren't used.")
    return {
        "year": int(year), "released": released, "fetched": date.today().isoformat(),
        "source": {"prices": BEA_ABOUT, "cities": CITIES}, "columns": ["all items", "housing (rents)"],
        "housing_weight": _housing_weight([lines for _name, lines in [*metros.values(), *states.values()]]),
        "states": dict(sorted(out_states.items())), "metros": out_metros,
    }


def _write(file: Path, found: dict[str, Any]) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(file.name + ".tmp")
    temporary.write_text(json.dumps(found, indent=0), encoding="utf-8")
    temporary.replace(file)


def refresh() -> dict[str, Any]:
    """Fetch the lists now and keep them. Raises Unavailable, leaving any old copy as it was, when that fails."""
    with _lock:
        found = build()
        _write(path(), found)
        _failed_at.clear()
        _loaded.clear()
        return found


def data() -> dict[str, Any]:
    """The kept price levels, fetched first if there are none, and looked for anew once they're RECHECK_DAYS old.
    Raises Unavailable only when there's no copy at all and none can be had."""
    with _lock:
        file = path()
        old = not file.exists() or time.time() - file.stat().st_mtime > RECHECK_DAYS * 86400
        waiting = bool(_failed_at) and time.monotonic() - _failed_at[-1] < RETRY_SECONDS
        if old and not waiting:
            try:
                _write(file, build())
                _failed_at.clear()
            except Unavailable:
                _failed_at.append(time.monotonic())
                if not file.exists():
                    raise
        if not file.exists():
            raise Unavailable("The price levels couldn't be downloaded a short while ago. Pyrite tries again within the hour.")
        stamp = (str(file), file.stat().st_mtime)
        if _loaded.get("stamp") != stamp:
            found = json.loads(file.read_text(encoding="utf-8"))
            _loaded.clear()
            _loaded.update(stamp=stamp, data=found, areas=_index(found))
        loaded: dict[str, Any] = _loaded["data"]
        return loaded


def about() -> dict[str, Any]:
    """The vintage and sources, for saying where the numbers come from."""
    found = data()
    return {"year": found["year"], "released": found["released"], "source": found["source"]["prices"],
            "housing_weight": found["housing_weight"]}


def _index(found: dict[str, Any]) -> Index:
    """Metros by code, states by their two letters, and each (city, state) to the metro it's a principal city of."""
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


def _areas() -> Index:
    data()
    areas: Index = _loaded["areas"]
    return areas


# ---- Reading a place ----

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
