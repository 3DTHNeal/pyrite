"""How each industry you follow is doing where you live, for the dashboard's Industries tab.

Two halves, and neither involves a model:

- The official numbers come from the Quarterly Census of Employment and Wages (QCEW), which the US
  Bureau of Labor Statistics publishes from employers' unemployment insurance filings. It counts
  nearly every job, by industry code and area, so it's solid, but it runs five to six months behind,
  and a metro area's industry detail comes out a quarter later than a state's. Each area therefore
  uses the newest quarter that has its industry detail, and says which.
- What Pyrite has seen is read from the database: postings that passed your filters, judged to be in
  the industry the same way [promote] judges them.

The Claude-written outlook is in outlook.py.
"""
import csv
import gzip
import io
import json
import re
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import outlook, score
from .sources import USER_AGENT
from .store import ROOT

QCEW = "https://data.bls.gov/cew/data/api/{year}/{quarter}/area/{area}.csv"
AREA_TITLES = "https://data.bls.gov/cew/doc/titles/area/area_titles.csv"
INDUSTRY_TITLES = "https://data.bls.gov/cew/doc/titles/industry/industry_titles.csv"
ABOUT = "https://www.bls.gov/cew/"
NATIONAL = "US000"
PRIVATE = "5"  # QCEW ownership code for private employers. Government jobs are counted separately.
ALL_INDUSTRIES = "10"
TIMEOUT = 60
RECHECK_DAYS = 7  # How long a quarter's numbers are used before looking for a newer one.
TITLES_DAYS = 180
QUARTERS_BACK = 6  # How far back to look for a quarter with the area's industry detail.
SEEN_DAYS = 90
US_NAMES = {"us", "usa", "u.s.", "united states", "united states of america"}

_lock = threading.Lock()


def cache_dir() -> Path:
    return ROOT / "data" / "market"


class Unavailable(Exception):
    """The numbers couldn't be read, with the reason in words."""


def _download(url: str) -> bytes | None:
    """The file, or None when the BLS says there's no such file, which is how a quarter not yet published looks."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            body = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body
    except urllib.error.HTTPError as err:
        err.close()
        if err.code == 404:
            return None
        raise Unavailable(f"The BLS answered {err.code}.") from err
    except OSError as err:
        raise Unavailable(f"Couldn't reach the BLS: {getattr(err, 'reason', err)}") from err


def _rows(body: bytes) -> list[dict[str, Any]]:
    return list(csv.DictReader(io.StringIO(body.decode("utf-8-sig", errors="replace"))))


def _fresh(path: Path, days: int) -> bool:
    return path.exists() and datetime.now(UTC).timestamp() - path.stat().st_mtime < days * 86400


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _titles(url: str, name: str, key: str) -> dict[str, str]:
    """A BLS list of codes and their names, kept for a while since it rarely changes."""
    path = cache_dir() / name
    if not _fresh(path, TITLES_DAYS):
        try:
            body = _download(url)
        except Unavailable:
            body = None
        if body:
            _write(path, body.decode("utf-8-sig", errors="replace"))
    if not path.exists():
        raise Unavailable("Couldn't get the BLS list of area and industry names.")
    with path.open(encoding="utf-8") as handle:
        return {row[key]: row[next(k for k in row if k != key)] for row in csv.DictReader(handle)}


def area_titles() -> dict[str, str]:
    return _titles(AREA_TITLES, "area_titles.csv", "area_fips")


def industry_titles() -> dict[str, str]:
    return _titles(INDUSTRY_TITLES, "industry_titles.csv", "industry_code")


def naics_codes(industry: dict[str, Any]) -> list[str]:
    """An industry's codes as text. Written by hand as naics = [333998], without quotes, they read as numbers."""
    return [str(code).strip() for code in industry.get("naics") or []]


def code_title(titles: dict[str, str], code: str) -> str:
    """'NAICS 3332 Industrial machinery manufacturing' as 'Industrial machinery manufacturing'."""
    return re.sub(rf"^NAICS\s+{re.escape(code)}\s+", "", titles.get(code, "")) or "Not a code the BLS publishes"


def _plain(text: str) -> str:
    return re.sub(r"\s+(msa|micro\s?sa|metropolitan statistical area)$", "", " ".join(text.lower().split()))


def find_state(titles: dict[str, str], wanted: str) -> str:
    """A state by its full name or FIPS code."""
    wanted = wanted.strip()
    if re.fullmatch(r"\d{2}(000)?", wanted):
        code = wanted[:2] + "000"
        if code in titles:
            return code
    for code, title in titles.items():
        if re.fullmatch(r"\d{2}000", code) and title.lower() == f"{wanted.lower()} -- statewide":
            return code
    raise ValueError(f"[market] state: no state is called '{wanted}'. Use its full name, as in Wisconsin.")


def find_metro(titles: dict[str, str], wanted: str) -> str:
    """A metro area as the BLS names it ('Madison, WI'), or its code ('C3154'), or its five-digit CBSA code."""
    wanted = wanted.strip()
    metros = {code: title for code, title in titles.items() if re.fullmatch(r"C\d{4}", code)}
    if wanted.upper() in metros:
        return wanted.upper()
    if re.fullmatch(r"\d{5}", wanted) and f"C{wanted[:4]}" in metros:
        return f"C{wanted[:4]}"
    plain = _plain(wanted)
    exact = [code for code, title in metros.items() if _plain(title) == plain]
    found = exact or [code for code, title in metros.items() if _plain(title).startswith(plain)]
    if len(found) == 1:
        return found[0]
    if found:
        names = "; ".join(metros[code] for code in found[:3])
        raise ValueError(f"[market] metro: '{wanted}' could be more than one area ({names}). Write it out in full.")
    raise ValueError(f"[market] metro: no metro area is called '{wanted}'. Write it as the BLS does, as in \"Madison, WI\".")


def is_us(cfg: dict[str, Any]) -> bool:
    country = str((cfg.get("market") or {}).get("country") or "United States")
    return country.strip().lower() in US_NAMES


def areas(cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """The areas to show, smallest first, and anything about [market] that needs fixing."""
    market = cfg.get("market") or {}
    if not is_us(cfg):
        return [], ["The official numbers cover the United States only."]
    titles = area_titles()
    found, problems = [], []
    for level, finder in (("metro", find_metro), ("state", find_state)):
        wanted = market.get(level)
        if not wanted:
            continue
        try:
            code = finder(titles, str(wanted))
        except ValueError as err:
            problems.append(str(err))
            continue
        name = re.sub(r"\s+--\s+Statewide$", "", titles[code])
        found.append({"code": code, "level": level, "name": name})
    found.append({"code": NATIONAL, "level": "national", "name": "United States"})
    return found, problems


def quarters(today: date, back: int = QUARTERS_BACK) -> list[tuple[int, int]]:
    """The last few finished quarters, newest first. The current one is never published yet."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    found = []
    for _ in range(back):
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        found.append((year, quarter))
    return found


def _number(text: str) -> float:
    try:
        return float(text or 0)
    except ValueError:
        return 0.0


def _keep(row: dict[str, Any]) -> dict[str, Any]:
    """The parts of one QCEW row that the panel uses."""
    return {
        "disclosed": row.get("disclosure_code") != "N",
        "change_disclosed": row.get("oty_disclosure_code") != "N",
        "estabs": _number(row["qtrly_estabs"]),
        "months": [_number(row[f"month{m}_emplvl"]) for m in (1, 2, 3)],
        "wages": _number(row["total_qtrly_wages"]),
        "lq": _number(row.get("lq_month3_emplvl", "")),
        "month_changes": [_number(row.get(f"oty_month{m}_emplvl_chg", "")) for m in (1, 2, 3)],
        "wage_change": _number(row.get("oty_total_qtrly_wages_chg", "")),
        "estab_change": _number(row.get("oty_qtrly_estabs_chg", "")),
    }


def _detail(body: bytes) -> dict[str, dict[str, Any]]:
    """Private employers' rows by industry code. A file with none of them has the area's totals only.

    A disclosure code of "-" marks a row that isn't published yet: every figure in it is a zero
    standing in for a number to come, so a quarter made of those has no detail at all.
    """
    return {row["industry_code"]: _keep(row) for row in _rows(body)
            if row.get("own_code") == PRIVATE and row.get("disclosure_code") != "-"}


def area_numbers(code: str, today: date | None = None) -> dict[str, Any]:
    """One area's newest quarter with industry detail: {"quarter": "2026 Q1", "rows": {...}, "note": ...}.

    Kept on disk, and looked for again after RECHECK_DAYS. Past quarters are kept as they were read.
    """
    today = today or datetime.now().date()
    folder = cache_dir() / "qcew"
    index_path = folder / "index.json"
    with _lock:
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
        known = index.get(code) or {}
        cached = folder / f"{code}-{known.get('quarter', '')}.json"
        if known and cached.exists() and known.get("checked", "") >= (today - timedelta(days=RECHECK_DAYS)).isoformat():
            return {"quarter": known["quarter"], "rows": json.loads(cached.read_text(encoding="utf-8"))}
        note = None
        try:
            for year, quarter in quarters(today):
                label = f"{year}Q{quarter}"
                if label == known.get("quarter") and cached.exists():
                    break  # Nothing newer has come out.
                body = _download(QCEW.format(year=year, quarter=quarter, area=code))
                rows = _detail(body) if body else {}
                if rows:
                    _write(folder / f"{code}-{label}.json", json.dumps(rows))
                    known = {"quarter": label}
                    cached = folder / f"{code}-{label}.json"
                    break
        except Unavailable as err:
            if not cached.exists():
                raise
            note = f"{err} These are the last numbers read."
        if not known.get("quarter") or not cached.exists():
            raise Unavailable(f"The BLS has no industry detail for this area in the last {QUARTERS_BACK} quarters.")
        if not note:
            index[code] = {**known, "checked": today.isoformat()}
            _write(index_path, json.dumps(index, indent=1))
        return {"quarter": known["quarter"], "rows": json.loads(cached.read_text(encoding="utf-8")), "note": note}


def combine(rows: dict[str, dict[str, Any]], codes: list[str]) -> dict[str, Any]:
    """The figures for an industry made of one or more codes, in one area.

    The BLS withholds a figure that would reveal one employer's numbers, so a code can be listed and
    still have nothing to add. What's left out is named, so a small total isn't taken at face value.
    """
    present = [rows[c] for c in codes if c in rows]
    shown = [r for r in present if r["disclosed"]]
    result: dict[str, Any] = {
        "withheld": [c for c in codes if c in rows and not rows[c]["disclosed"]],
        "absent": [c for c in codes if c not in rows],
    }
    # Workplace counts are published even where jobs and pay are withheld, so they count every code on record.
    if present:
        result["estabs"] = round(sum(r["estabs"] for r in present))
        result["estabs_change"] = round(sum(r["estab_change"] for r in present))
    if not shown:
        return result
    jobs = sum(r["months"][2] for r in shown)
    average = sum(sum(r["months"]) / 3 for r in shown)
    wages = sum(r["wages"] for r in shown)
    weekly = wages / average / 13 if average else None
    result.update({"jobs": round(jobs), "weekly_pay": round(weekly) if weekly else None})
    if all(r["change_disclosed"] for r in shown):
        before = jobs - sum(r["month_changes"][2] for r in shown)
        before_average = average - sum(sum(r["month_changes"]) / 3 for r in shown)
        before_wages = wages - sum(r["wage_change"] for r in shown)
        before_weekly = before_wages / before_average / 13 if before_average > 0 else None
        result["jobs_change"] = round(jobs - before)
        result["jobs_change_pct"] = round((jobs - before) / before * 100, 1) if before > 0 else None
        result["pay_change_pct"] = round((weekly - before_weekly) / before_weekly * 100, 1) if weekly and before_weekly else None
    # Each code's concentration is its share of local jobs over its share of national jobs. Together, that's
    # the employment-weighted harmonic mean of the codes' own figures, which needs no other totals.
    weighted = [(r["months"][2], r["lq"]) for r in shown if r["months"][2] > 0 and r["lq"] > 0]
    if weighted:
        result["concentration"] = round(sum(e for e, _ in weighted) / sum(e / lq for e, lq in weighted), 2)
    overall = rows.get(ALL_INDUSTRIES)
    if overall and overall["disclosed"] and weekly and sum(overall["months"]):
        all_weekly = overall["wages"] / (sum(overall["months"]) / 3) / 13
        result["pay_vs_all"] = round(weekly / all_weekly * 100)
    return result


def _since(iso: str | None, today: date) -> int | None:
    parsed = score.parse_date(iso)
    return (today - parsed).days if parsed else None


def history(jobs: list[dict[str, Any]], industry: dict[str, Any], mentions_needed: int, today: date) -> dict[str, Any]:
    """What Pyrite has seen of one industry: postings that passed the filters, and what came of applying."""
    matched = [job for job in jobs if score._in_industry(industry, job, mentions_needed)]
    recent = [job for job in matched if (_since(job["first_seen"], today) or 0) < SEEN_DAYS]
    all_recent = sum(1 for job in jobs if (_since(job["first_seen"], today) or 0) < SEEN_DAYS)
    by_month = [0, 0, 0]
    for job in recent:
        by_month[min((_since(job["first_seen"], today) or 0) // 30, 2)] += 1
    kinds = Counter(job.get("location_kind") or "unknown" for job in recent)
    applied = [job for job in matched if job.get("applied_at")]
    return {
        "recent": len(recent),
        "by_month": by_month,
        "share": round(len(recent) / all_recent * 100) if all_recent else None,
        "open": sum(1 for job in matched if not job.get("posting_closed_at")),
        "local": kinds.get("local", 0),
        "remote": kinds.get("remote", 0),
        "employers": Counter(job["company"] for job in recent).most_common(6),
        "applied": len(applied),
        "replied": sum(1 for job in applied if job.get("replied")),
        "interviews": sum(1 for job in applied if job.get("interview_at") or job.get("offer_at")),
        "offers": sum(1 for job in applied if job.get("offer_at")),
    }


SEEN_COLUMNS = ("company", "title", "description", "location_kind", "first_seen", "posting_closed_at",
                "applied_at", "response_at", "interview_at", "offer_at")
# Replied the way the dashboard's Reply rate counts it: heard back, and that answer was a reply, an interview or an
# offer. A rejection is hearing back too, but it isn't a reply.
REPLIED = """(response_at IS NOT NULL AND (interview_at IS NOT NULL OR offer_at IS NOT NULL OR id IN
              (SELECT job_id FROM events WHERE kind IN ('responded', 'interviewing', 'offer')))) AS replied"""


def view(conn, cfg: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Everything the Industries tab shows, for every industry under [promote]."""
    today = today or datetime.now().date()
    promote = cfg.get("promote") or {}
    industries = promote.get("industry", [])
    jobs = [dict(row) for row in conn.execute(f"SELECT {', '.join(SEEN_COLUMNS)}, {REPLIED} FROM jobs")]
    first = min((job["first_seen"] for job in jobs), default=None)
    needed = promote.get("mentions_needed", 3)

    places: list[dict[str, Any]] = []
    problems: list[str] = []
    numbers: dict[str, dict[str, Any]] = {}
    titles: dict[str, str] = {}
    if any(i.get("naics") for i in industries):
        try:
            places, problems = areas(cfg)
            titles = industry_titles()
        except Unavailable as err:
            problems.append(str(err))
        for place in places:
            try:
                numbers[place["code"]] = area_numbers(place["code"], today)
            except Unavailable as err:
                numbers[place["code"]] = {"error": str(err)}

    shown = []
    for industry in industries:
        codes = naics_codes(industry)
        official = []
        for place in places if codes else []:
            found = numbers.get(place["code"], {})
            entry = {**place, "quarter": found.get("quarter"), "note": found.get("note"), "error": found.get("error")}
            if "rows" in found:
                entry.update(combine(found["rows"], codes))
            official.append(entry)
        shown.append({
            "name": industry["name"],
            "codes": [{"code": c, "title": code_title(titles, c)} for c in codes] if titles else [{"code": c, "title": ""} for c in codes],
            "official": official,
            "seen": history(jobs, industry, needed, today),
            "outlook": outlook.status(industry["name"]),
        })
    market = cfg.get("market") or {}
    return {
        "watching_since": first,
        "market": {"metro": market.get("metro"), "state": market.get("state"), "us": is_us(cfg)},
        "problems": problems,
        "about": ABOUT,
        "industries": shown,
    }
