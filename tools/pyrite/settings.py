"""Edits the [promote] section of search.toml for the dashboard's Settings tab.

Only this section of search.toml can change from the browser. The dashboard has no login, so
the patterns under [guard], the filters and the allowed hosts stay out of its reach. A save
rewrites this one block and proves that everything else in the file still reads the same.
The candidate's own facts are a separate matter, handled in facts.py.
"""
import hashlib
import json
import os
import re
import threading
import time
import tomllib
from typing import Any

from . import checks, score, store

MAX_NAME = 80
MAX_PATTERN = 300
MAX_ITEMS = 100
MAX_POINTS = 50
MAX_CODES = 10
# A NAICS code as the BLS writes it: two to six digits, or a range of two-digit sectors such as 31-33.
NAICS = re.compile(r"\d{2,6}|\d{2}-\d{2}")
SECTION = re.compile(r"^\[\[?\s*([^\]\s]+)\s*\]\]?\s*(#.*)?$")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.Lock()


class Conflict(ValueError):
    """The section changed after the form was opened."""


def _read() -> str:
    # newline="" keeps the file's own line endings, so a save doesn't rewrite every line.
    with open(store.CONFIG_PATH, encoding="utf-8", newline="") as handle:
        return handle.read()


def _version(promote: dict | None) -> str:
    return hashlib.sha256(json.dumps(promote or {}, sort_keys=True).encode()).hexdigest()[:16]


def _claimable_facts() -> str:
    """facts.md without the sections that list what must not be claimed."""
    path = store.CONFIG_PATH.with_name("facts.md")
    if not path.exists():
        return ""
    return checks.claimable(path.read_text(encoding="utf-8"))


def skills(promote: dict) -> dict:
    """For each industry, which of the skills it wants appear in the fact bank."""
    facts = _claimable_facts()
    result = {}
    for industry in promote.get("industry", []):
        have: list[str] = []
        gaps: list[str] = []
        for want in industry.get("wants", []):
            try:
                found = re.search(want.get("match") or score._named(want["name"]), facts, re.I)
            except re.error:
                found = None
            (have if found else gaps).append(want["name"])
        result[industry["name"]] = {"have": have, "gaps": gaps}
    return result


def view() -> dict:
    promote = tomllib.loads(_read()).get("promote") or {}
    return {"version": _version(promote), "promote": promote, "skills": skills(promote)}


def _name(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} needs a name.")
    value = value.strip()
    if len(value) > MAX_NAME or CONTROL.search(value):
        raise ValueError(f"{what}: that name is too long or has line breaks in it.")
    return value


def _points(value, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_POINTS:
        raise ValueError(f"{what}: points must be a whole number from 0 to {MAX_POINTS}.")
    return value


def _pattern(value, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what}: a pattern can't be empty.")
    value = value.strip()
    if len(value) > MAX_PATTERN or CONTROL.search(value):
        raise ValueError(f"{what}: that pattern is too long or has line breaks in it.")
    try:
        re.compile(value)
    except re.error as err:
        raise ValueError(f"{what}: '{value}' isn't a valid pattern ({err}).") from err
    return value


def _list(value, what: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise ValueError(f"{what} must be a list of at most {MAX_ITEMS}.")
    return value


def _codes(value, what: str) -> list[str]:
    """Industry codes for the official numbers. One inside another would count its jobs twice."""
    codes = [str(code).strip() for code in _list(value, f"{what} codes")]
    if len(codes) > MAX_CODES:
        raise ValueError(f"{what}: at most {MAX_CODES} industry codes.")
    for code in codes:
        if not NAICS.fullmatch(code):
            raise ValueError(f"{what}: '{code}' isn't an industry code. Use 2 to 6 digits, such as 3332 or 334413.")
    _unique(codes, f"{what} codes")
    for code in codes:
        for other in codes:
            if other != code and other.startswith(code):
                raise ValueError(f"{what}: {other} is part of {code}, so its jobs would be counted twice. Keep one.")
    return codes


def _unique(names: list, what: str) -> None:
    lowered = [n.lower() for n in names]
    for name, low in zip(names, lowered, strict=True):
        if lowered.count(low) > 1:
            raise ValueError(f"{what}: '{name}' is listed twice.")


def _named_item(raw, what: str, with_points: bool = False) -> dict:
    """A city or a wanted skill: a name, with a pattern and points if they were given."""
    if not isinstance(raw, dict):
        raise ValueError(f"{what}: that isn't a valid entry.")
    item: dict[str, Any] = {"name": _name(raw.get("name"), what)}
    label = f"{what} '{item['name']}'"
    if with_points and raw.get("points") is not None:
        item["points"] = _points(raw["points"], label)
    if raw.get("match"):
        item["match"] = _pattern(raw["match"], label)
    return item


def validate(raw) -> dict:
    """Turn what the form sent into a clean section, or say what's wrong with it."""
    if not isinstance(raw, dict):
        raise ValueError("Nothing to save.")
    promote: dict[str, Any] = {
        "city_points": _points(raw.get("city_points"), "Points for a city"),
        "industry_points": _points(raw.get("industry_points"), "Points for an industry"),
        "mentions_needed": _points(raw.get("mentions_needed"), "Mentions needed"),
    }
    if promote["mentions_needed"] < 1:
        raise ValueError("Mentions needed must be at least 1.")
    promote["cities"] = [_named_item(c, "City", with_points=True) for c in _list(raw.get("cities"), "Cities")]
    _unique([c["name"] for c in promote["cities"]], "Cities")

    promote["industry"] = []
    for entry in _list(raw.get("industry"), "Industries"):
        if not isinstance(entry, dict):
            raise ValueError("Industry: that isn't a valid entry.")
        industry: dict[str, Any] = {"name": _name(entry.get("name"), "Industry")}
        label = f"Industry '{industry['name']}'"
        if entry.get("points") is not None:
            industry["points"] = _points(entry["points"], label)
        terms = [_pattern(t, label) for t in _list(entry.get("terms"), f"{label} terms")]
        companies = [_name(c, f"{label} employer") for c in _list(entry.get("companies"), f"{label} employers")]
        wants = [_named_item(w, f"{label} skill") for w in _list(entry.get("wants"), f"{label} skills")]
        _unique([w["name"] for w in wants], f"{label} skills")
        naics = _codes(entry.get("naics"), label)
        if not terms and not companies:
            raise ValueError(f"{label} needs at least one term or employer, or it can never match.")
        if terms:
            industry["terms"] = terms
        if companies:
            industry["companies"] = companies
        if wants:
            industry["wants"] = wants
        if naics:
            industry["naics"] = naics
        promote["industry"].append(industry)
    _unique([i["name"] for i in promote["industry"]], "Industries")
    return promote


def _text(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _regex(value: str) -> str:
    # A literal string keeps backslashes readable, but it can't hold a single quote.
    return _text(value) if "'" in value else f"'{value}'"


def _inline(item: dict) -> str:
    parts = [f"name = {_text(item['name'])}"]
    if "points" in item:
        parts.append(f"points = {item['points']}")
    if "match" in item:
        parts.append(f"match = {_regex(item['match'])}")
    return "{ " + ", ".join(parts) + " }"


def _inline_list(items: list) -> list:
    return [f"  {_inline(item)}," for item in items]


def render(promote: dict) -> str:
    lines = [
        "[promote]",
        f"city_points = {promote['city_points']}       # Each list counts once, at its best match.",
        f"industry_points = {promote['industry_points']}",
        (f"mentions_needed = {promote['mentions_needed']}    # Times an industry's terms must appear in a description. "
         "At 2, degree lists and passing mentions count."),
        "# Matched against the posting's location. The name is matched as a whole word, and `match`",
        "# replaces that with a pattern. Add `points` to any line to override city_points.",
        "cities = [", *_inline_list(promote["cities"]), "]",
    ]
    if promote["industry"]:
        lines += [
            "",
            "# A posting is in an industry if its employer is listed under `companies`, a term is in the",
            "# employer's name or the title, or the terms appear mentions_needed times in the description.",
            "# Keep terms specific: \"medical\" alone would catch most postings' benefits text.",
            "# `wants` are skills the industry looks for. The Settings tab checks them against facts.md,",
            "# and they don't change the ranking. Add `points` to any industry to override industry_points.",
            "# `naics` are the industry's codes, for the official numbers on the Industries tab.",
        ]
    for index, industry in enumerate(promote["industry"]):
        if index:
            lines.append("")
        lines += ["[[promote.industry]]", f"name = {_text(industry['name'])}"]
        if "points" in industry:
            lines.append(f"points = {industry['points']}")
        if "terms" in industry:
            lines.append("terms = [" + ", ".join(_regex(t) for t in industry["terms"]) + "]")
        if "companies" in industry:
            lines.append("companies = [" + ", ".join(_text(c) for c in industry["companies"]) + "]")
        if "wants" in industry:
            lines += ["wants = [", *_inline_list(industry["wants"]), "]"]
        if "naics" in industry:
            lines.append("naics = [" + ", ".join(_text(c) for c in industry["naics"]) + "]")
    return "\n".join(lines) + "\n"


def _is_promote(name: str) -> bool:
    return name == "promote" or name.startswith("promote.")


def _replace_section(text: str, block: str) -> str:
    """Swap the block in. Comments just above the next section belong to that section, so they stay."""
    eol = "\r\n" if "\r\n" in text else "\n"
    block = block.replace("\n", eol)
    lines = text.splitlines(keepends=True)
    start = end = None
    for index, line in enumerate(lines):
        found = SECTION.match(line.rstrip())
        if not found:
            continue
        if start is None:
            if _is_promote(found.group(1)):
                start = index
        elif not _is_promote(found.group(1)):
            end = index
            break
    if start is None:
        return f"{text.rstrip()}{eol}{eol}{block}"
    end = len(lines) if end is None else end
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
        end -= 1
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _write(path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    # Windows refuses the swap while something is reading the file, which only lasts a moment.
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 9:
                temporary.unlink(missing_ok=True)
                raise ValueError(f"{path.name} is busy, so nothing was saved. Try again.") from None
            time.sleep(0.1)


def save(body: dict) -> dict:
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so settings can't be saved. Point PYRITE_HOME at your own workspace to change them.")
    with _lock:
        text = _read()
        current = tomllib.loads(text)
        if body.get("version") != _version(current.get("promote")):
            raise Conflict("These settings changed after you opened them, so nothing was saved. Reload Settings to see the latest.")
        promote = validate(body.get("promote"))
        updated = _replace_section(text, render(promote))
        parsed = tomllib.loads(updated)
        without = lambda config: {k: v for k, v in config.items() if k != "promote"}
        if parsed.get("promote") != promote or without(parsed) != without(current):
            raise ValueError("Saving would have changed something else in search.toml, so nothing was saved.")
        if updated != text:
            # The file as it was goes into History on the Profile tab, where it can be put back. Imported here, since
            # profile imports this module.
            from . import profile
            profile.keep({"config": text}, "Changed on the Settings tab")
        _write(store.CONFIG_PATH, updated)
    return view()
