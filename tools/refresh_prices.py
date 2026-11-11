#!/usr/bin/env python3
"""Rebuild tools/pyrite/rpp.json, the price levels the relocation comparison uses, from the government's own files.

Two public-domain sources, both read whole:

- The US Bureau of Economic Analysis's Regional Price Parities (RPPs): how much more or less the same things cost in
  each metropolitan statistical area (MSA) and each state than in the US as a whole, which is 100. BEA publishes one
  vintage a year, usually in December, covering the year two before. Pyrite keeps all items and housing (rents).
- The Census Bureau's list of each MSA's principal cities, under OMB's delineation of the areas, so a posting in a
  city that isn't in its metro's name ("Sunnyvale, CA") still finds its metro.

Run it once a year, after BEA's December release, then the tests, and commit the new file with the vintage in the
message:

    python tools/refresh_prices.py

It also works out the housing weight within BEA's all-items index (about one sixth), which the "renting at market"
view needs to take housing out of all items. BEA doesn't publish one weight for the nation, so it's estimated by least
squares across every area: all items against goods, housing, utilities and other services.
"""
import argparse
import csv
import io
import json
import re
import sys
import urllib.request

# Government files over https, and Python's parser resolves no entities, so the standard library's will do.
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pyrite.score import US_STATES

BEA = "https://apps.bea.gov/regional/zip/{table}.zip"
BEA_ABOUT = "https://www.bea.gov/data/prices-inflation/regional-price-parities-state-and-metro-area"
# OMB's delineation of the metro areas, which BEA's areas follow. A new one comes every ten years or so: when BEA's
# footnote names a newer OMB bulletin, change this to that year's list 2.
CITIES = "https://www2.census.gov/programs-surveys/metro-micro/geographies/reference-files/2023/delineation-files/list2_2023.xlsx"
OUT = Path(__file__).resolve().parent / "pyrite" / "rpp.json"
TIMEOUT = 120
ALL_ITEMS, GOODS, HOUSING, UTILITIES, OTHER = 1, 2, 3, 4, 5
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Pyrite price refresh (+https://github.com/3DTHNeal/pyrite)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def bea_table(blob: bytes, prefix: str) -> tuple[list[dict[str, str]], str, str]:
    """The rows of one RPP table, the newest year with figures, and the 'Last updated' line."""
    archive = zipfile.ZipFile(io.BytesIO(blob))
    name = next(n for n in archive.namelist() if n.startswith(prefix) and n.endswith(".csv"))
    text = archive.read(name).decode("latin-1")
    rows = [row for row in csv.DictReader(io.StringIO(text)) if (row.get("LineCode") or "").strip()]
    years = [key for key in rows[0] if key and key.isdigit()]
    year = max(y for y in years if re.fullmatch(r"[\d.]+", rows[0][y].strip()))
    updated = next((line.strip('"') for line in text.splitlines() if "Last updated" in line), "")
    return rows, year, updated


def figures(rows: list[dict[str, str]], year: str) -> dict[str, tuple[str, dict[int, float]]]:
    """Each area's name and its figures by line code, for one year, by its code."""
    areas: dict[str, tuple[str, dict[int, float]]] = {}
    for row in rows:
        code = row["GeoFIPS"].strip().strip('"')
        _name, lines = areas.setdefault(code, (row["GeoName"].strip().rstrip(" *"), {}))
        try:
            lines[int(row["LineCode"])] = float(row[year])
        except ValueError:
            pass  # (NA): not published for this area.
    return areas


def housing_weight(areas: list[dict[int, float]]) -> float:
    """Housing's share of the all-items index, by least squares: all items against the four parts, across every area."""
    rows = [[a[GOODS], a[HOUSING], a[UTILITIES], a[OTHER], a[ALL_ITEMS]] for a in areas
            if all(k in a for k in (ALL_ITEMS, GOODS, HOUSING, UTILITIES, OTHER))]
    n = 4
    # The normal equations, solved by elimination: four unknowns need nothing more.
    m = [[sum(r[i] * r[j] for r in rows) for j in range(n)] + [sum(r[i] * r[n] for r in rows)] for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda k: abs(m[k][i]))
        m[i], m[pivot] = m[pivot], m[i]
        for k in range(n):
            if k != i:
                factor = m[k][i] / m[i][i]
                m[k] = [a - factor * b for a, b in zip(m[k], m[i], strict=True)]
    weights = [m[i][n] / m[i][i] for i in range(n)]
    return round(weights[1] / sum(weights), 3)


def principal_cities(blob: bytes) -> list[tuple[str, str, str]]:
    """(CBSA code, city, state FIPS code) for every metropolitan area's principal cities, from the Census's list 2."""
    archive = zipfile.ZipFile(io.BytesIO(blob))
    shared = [("".join(t.text or "" for t in si.iter(f"{SHEET}t")))
              for si in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall(f"{SHEET}si")]  # noqa: S314
    sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))  # noqa: S314
    found = []
    for row in sheet.iter(f"{SHEET}row"):
        cells = {}
        for cell in row.findall(f"{SHEET}c"):
            value = cell.find(f"{SHEET}v")
            text = value.text if value is not None and value.text else ""
            if cell.get("t") == "s" and text:
                text = shared[int(text)]
            cells[re.sub(r"\d+", "", cell.get("r", ""))] = text
        if re.fullmatch(r"\d{5}", cells.get("A", "")) and cells.get("C", "").startswith("Metropolitan"):
            found.append((cells["A"], cells["D"], cells["E"].zfill(2)))
    return found


def build() -> dict[str, object]:
    metro_rows, year, updated = bea_table(download(BEA.format(table="MARPP")), "MARPP_")
    state_rows, state_year, _ = bea_table(download(BEA.format(table="SARPP")), "SARPP_")
    if state_year != year:
        raise SystemExit(f"BEA's metro table runs to {year} and its state table to {state_year}. Try again once both are out.")
    metros, states = figures(metro_rows, year), figures(state_rows, year)
    abbr = {name: code for code, name in US_STATES.items()}
    fips = {code[:2]: abbr[name] for code, (name, _lines) in states.items() if name in abbr}
    cities: dict[str, list[str]] = {}
    for cbsa, city, state in principal_cities(download(CITIES)):
        if state in fips:
            cities.setdefault(cbsa, []).append(f"{city}|{fips[state]}")
    shown = lambda lines: [round(lines[ALL_ITEMS], 3), round(lines[HOUSING], 3)]
    every = [lines for _name, lines in [*metros.values(), *states.values()]]
    out_states = {abbr[name]: shown(lines) for name, lines in states.values() if name in abbr}
    out_metros: list[list[object]] = []
    for code, (name, lines) in sorted(metros.items()):
        if not name.endswith("(Metropolitan Statistical Area)"):
            continue  # The US, and its nonmetropolitan portion.
        if not (ALL_ITEMS in lines and HOUSING in lines):
            continue
        out_metros.append([code, name.replace(" (Metropolitan Statistical Area)", ""), *shown(lines), cities.get(code, [])])
    missing = [str(m[1]) for m in out_metros if not m[4]]
    if missing:
        print(f"No principal cities listed for {len(missing)} metro areas, which then match by the names in their titles: "
              f"{'; '.join(missing[:5])}", file=sys.stderr)
    return {
        "about": "Regional Price Parities: what the same things cost in each area, with the US at 100. Public domain.",
        "year": int(year),
        "released": updated.replace("Last updated: ", "").split("--")[0].strip(),
        "fetched": date.today().isoformat(),
        "source": {"prices": BEA_ABOUT, "cities": CITIES},
        "columns": ["all items", "housing (rents)"],
        "housing_weight": housing_weight(every),
        "us": [100.0, 100.0],
        "states": dict(sorted(out_states.items())),
        "metros": out_metros,
    }


def write(data: dict[str, object], path: Path) -> None:
    """One area to a line, so a refresh's diff shows which areas moved."""
    head = {k: v for k, v in data.items() if k not in ("states", "metros")}
    lines = ["{"] + [f"  {json.dumps(k)}: {json.dumps(v)}," for k, v in head.items()]
    states = data["states"]
    assert isinstance(states, dict)
    lines.append('  "states": {')
    lines += [f"    {json.dumps(k)}: {json.dumps(v)}{',' if i < len(states) - 1 else ''}" for i, (k, v) in enumerate(states.items())]
    lines.append("  },")
    metros = data["metros"]
    assert isinstance(metros, list)
    lines.append('  "metros": [')
    lines += [f"    {json.dumps(m)}{',' if i < len(metros) - 1 else ''}" for i, m in enumerate(metros)]
    lines += ["  ]", "}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=OUT, help="where to write it (default: the one Pyrite reads)")
    args = parser.parse_args()
    data = build()
    write(data, args.out)
    metros, states = data["metros"], data["states"]
    assert isinstance(metros, list) and isinstance(states, dict)
    print(f"Wrote {args.out}: {data['year']} prices for {len(metros)} metro areas and {len(states)} states, "
          f"released {data['released']}. Housing weighs {data['housing_weight']} of all items.")


if __name__ == "__main__":
    main()
