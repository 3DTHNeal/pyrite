"""Each Profile section's form, turned into the files it writes.

The page sends what its form says, never file text of its own, and gets back every file as a save would leave it,
with a diff of each, anything worth knowing first, and what a save would need a code for. Every preview runs the real
code: factsdoc and tomledit write the text, and the fact check's own patterns judge it. Nothing here writes a file.
The page sends the text back to save, where profile.write and confirm.require decide as they would for any save.

A form is drafted whole each time, against the files as the page read them, so line numbers from the page stay
right: a draft based on a file that has changed since is refused, as a save would be.
"""
import difflib
import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

from . import checks, confirm, doctor, factsdoc, profile, store, tomledit

# Parts of a contact line: "Madison, WI · (555) 010-0142 · alex@example.com".
CONTACT_SEP = re.compile(r"(\s+[·|•]\s+)")
SEP_CHARS = re.compile(r"[·|•]")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE = re.compile(r"\+?[\d(][\d\s().-]{6,}\d")
LINK = re.compile(r"(?:https?://|www\.)\S+|[\w.-]+\.(?:com|net|org|io|dev|me|co|ai|app|page|site|info)(?:/\S*)?", re.I)
HEADING_PARTS = re.compile(r"\s*\|\s*")
TERM_SPLIT = re.compile(r"([\s,;]+)")
# A role that starts more than this many months after the one before it ends is noted as a gap.
GAP_MONTHS = 3
MAX_PATTERN = 300
DO_NOT_USE_TITLE = "Do not use"
UNSUPPORTED_TITLE = "Unsupported, so don't claim without new evidence"


@dataclass
class Draft:
    texts: dict[str, str]
    count: int
    notes: list[str] = field(default_factory=list)
    preview: dict = field(default_factory=dict)


def _one_line(value, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{what} should be text.")
    if "\n" in value or "\r" in value or any(ord(c) < 32 and c != "\t" for c in value):
        raise ValueError(f"{what} can't hold a line break or control characters.")
    return value.strip()


def _list(value, what: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{what} should be a list.")
    return value


def _keep_end(old: str, text: str) -> str:
    """Text in place of a line, keeping the line's ending."""
    return text + old[len(old.rstrip("\r\n")):]


def _config(text: str) -> dict:
    try:
        return tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as err:
        raise ValueError(f"profile/search.toml can't be read ({err}), so nothing can be changed here until it's fixed.") from err


def _written(rel: str) -> bool:
    return rel in profile.FILES.values()


def _diff(old: str, new: str) -> dict:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), "now", "after", n=1, lineterm=""))[2:]
    return {"lines": lines[:profile.DIFF_LINES], "cut": max(0, len(lines) - profile.DIFF_LINES)}


class Plan:
    """Line changes to make to a document at once, so the line numbers they name all refer to the text as it was read."""

    def __init__(self):
        self.replace: dict[int, str] = {}
        self.deletes: list[tuple[int, int]] = []
        self.inserts: dict[int, list[str]] = {}

    def set(self, line: int, text: str) -> None:
        self.replace[line] = text

    def delete(self, start: int, end: int) -> None:
        self.deletes.append((start, end))

    def insert(self, at: int, texts: list[str]) -> None:
        self.inserts.setdefault(at, []).extend(texts)

    def apply(self, doc: factsdoc.Doc) -> None:
        for line, text in self.replace.items():
            doc.set_line(line, text)
        # From the bottom up, so each change leaves the lines above it where they were. At one place, a deletion goes
        # first, so what's inserted there isn't deleted with it.
        ops = [(start, 1, end) for start, end in self.deletes] + [(at, 0, 0) for at in self.inserts]
        for at, kind, end in sorted(ops, reverse=True):
            if kind:
                doc.delete(at, end)
            else:
                doc.insert(at, self.inserts[at])


# ---------- reading what the editors show ----------

def contact_parts(line: str) -> tuple[list[dict], str]:
    """A contact line's parts, each with what kind it reads as, and the separator it uses."""
    pieces = CONTACT_SEP.split(line)
    seps = pieces[1::2]
    parts, place = [], False
    for text in (piece.strip() for piece in pieces[0::2]):
        if not text:
            continue
        kind = ("email" if EMAIL.fullmatch(text) else "phone" if PHONE.fullmatch(text)
                else "link" if LINK.fullmatch(text) else "other" if place else "place")
        place = place or kind == "place"
        parts.append({"kind": kind, "text": text})
    return parts, seps[0] if seps else " · "


def contact_source(cfg: dict) -> tuple[str, str] | None:
    """The file the fact check takes the contact line from, and that line: the first "@ " line in the approved
    sources, in the order search.toml lists them."""
    for rel in cfg.get("guard", {}).get("approved_sources", []):
        path = store.ROOT / rel
        if path.is_file():
            for row in path.read_text(encoding="utf-8").splitlines():
                if row.startswith("@ "):
                    return rel, row[2:].strip()
    return None


def _excluded(doc: factsdoc.Doc, kind: str) -> factsdoc.Section | None:
    """The fact bank's Do not use section (never) or its Unsupported one (nottrue)."""
    for section in doc.sections():
        if section.kind != "excluded":
            continue
        is_never = bool(checks.DO_NOT_USE_SECTION.match(section.title))
        if is_never == (kind == "never"):
            return section
    return None


def _term_lines(text: str) -> list[dict]:
    """approved-terms.txt as groups: each comment block, and the terms on the lines after it."""
    groups: list[dict] = [{"note": "", "terms": []}]
    for index, row in enumerate(text.splitlines()):
        stripped = row.strip()
        if stripped.startswith("#"):
            note = stripped.lstrip("#").strip()
            if groups[-1]["terms"] or not groups[-1]["note"]:
                if groups[-1]["terms"] or groups[-1]["note"]:
                    groups.append({"note": "", "terms": []})
                groups[-1]["note"] = note
            else:
                groups[-1]["note"] += " " + note
            continue
        for word in (w for w in re.split(r"[\s,;]+", stripped) if w):
            groups[-1]["terms"].append({"line": index, "term": word})
    return [group for group in groups if group["terms"]]


def view() -> dict:
    """What the section editors need beyond profile.view(): the contact line in parts and where the check reads it, the
    off-limits lists with their patterns, and the approved terms by line."""
    texts = {key: profile.read(key) for key in profile.FILES}
    try:
        cfg = _config(texts["config"])
    except ValueError:
        cfg = {}
    doc = factsdoc.Doc(texts["facts"])
    found = doc.contact()
    parts, sep = contact_parts(found[1] if found else "")
    source = contact_source(cfg)
    masters = {}
    for key in ("resume", "letter"):
        lines = [row.strip() for row in texts[key].splitlines()]
        masters[key] = {"path": profile.FILES[key], "exists": bool(texts[key]),
                        "contact": next((row[2:].strip() for row in lines if row.startswith("@ ")), None)}
    guard = cfg.get("guard", {})
    lists = {}
    for kind, key in (("never", "forbidden"), ("nottrue", "unsupported")):
        section = _excluded(doc, kind)
        lists[kind] = {
            "section": section.title if section else None,
            "items": [{"line": item.line, "text": item.text} for item in doc.items(section)] if section else [],
            "patterns": list(guard.get(key, [])),
        }
    heading = str(guard.get("heading_source", "") or "")
    return {
        "contact_parts": {"parts": parts, "sep": sep, "masters": masters,
                          "checked_in": source[0] if source else None, "checked_line": source[1] if source else None},
        "heading_source": {"path": heading, "written": _written(heading)},
        "expected": [{"text": str(item.get("text", "")), "label": str(item.get("label", ""))}
                     for item in guard.get("expected_on_resume", []) if isinstance(item, dict)],
        "off_limits_lists": {**lists, "unguarded": doctor.unguarded_terms(
            texts["facts"], guard.get("forbidden", []), str(cfg.get("candidate", {}).get("name", "")))},
        "term_groups": _term_lines(texts["terms"]),
    }


# ---------- drafting ----------

def draft(step: str, edits, based_on) -> dict:
    """A section's form as the files it would write, without writing them."""
    if step not in DRAFTERS:
        raise ValueError("That section can't be edited here yet.")
    if not isinstance(edits, dict):
        raise ValueError("Nothing to draft.")
    keys = next(s["files"] for s in profile.STEPS if s["id"] == step)
    texts = {key: profile.read(key) for key in profile.FILES}
    profile.refuse_stale({key: texts[key] for key in keys}, based_on if isinstance(based_on, dict) else {})
    cfg = _config(texts["config"])
    try:
        result = DRAFTERS[step](texts, cfg, edits)
    except (factsdoc.FactsError, tomledit.EditError) as err:
        raise ValueError(str(err)) from err
    changes = {key: text for key, text in result.texts.items() if key in keys and text != texts[key]}
    for key, text in changes.items():
        profile._clean(key, text)  # Refused here as a save would refuse it, before you get as far as saving.
    return {
        "changes": changes,
        "count": max(result.count, 1) if changes else 0,
        "notes": result.notes,
        "code": [phrase for key, text in changes.items() for phrase in confirm.loosening(key, texts[key], text)],
        "diffs": [{"key": key, "path": profile.FILES[key], **_diff(texts[key], text)} for key, text in changes.items()],
        "preview": result.preview,
    }


# ---------- Name and contact ----------

def _basics(texts: dict, cfg: dict, edits: dict) -> Draft:
    out = dict(texts)
    notes: list[str] = []
    old_name = str(cfg.get("candidate", {}).get("name", "")).strip()
    name = _one_line(edits.get("name", old_name), "Your name")
    if not name:
        raise ValueError("Your name can't be empty: every resume and letter opens with it.")
    old_paper = cfg.get("documents", {}).get("paper")
    paper = edits.get("paper", old_paper or "letter")
    if paper not in ("letter", "a4"):
        raise ValueError("Paper size is US Letter or A4.")
    doc = factsdoc.Doc(texts["facts"])
    found = doc.contact()
    old_contact = found[1] if found else ""
    _, sep = contact_parts(old_contact)
    contact = old_contact
    if "contact" in edits:
        kept = []
        for part in _list(edits["contact"], "The contact line"):
            text = _one_line(part, "A contact detail")
            if SEP_CHARS.search(text):
                raise ValueError(f"“{text}” has a ·, | or • in it, which would split it in two on the contact line.")
            if text:
                kept.append(text)
        contact = sep.join(kept)
        if not contact:
            raise ValueError("Add at least one way to reach you. It goes under your name on every resume and letter.")

    config = texts["config"]
    if name != old_name:
        config = tomledit.set_value(config, "candidate", "name", name)
    if paper != (old_paper or "letter"):
        config = tomledit.set_value(config, "documents", "paper", paper)
    out["config"] = config

    if contact != old_contact:
        if found:
            doc.set_line(found[0], contact)
        elif contact_section := doc.section("contact"):
            doc.insert(contact_section.start + 1, [contact])
        else:
            sections = doc.sections()
            doc.insert(sections[0].start if sections else len(doc.lines), ["## Contact", contact, ""])
        out["facts"] = doc.render()

    for key in ("resume", "letter"):
        if not texts[key]:
            continue
        lines = texts[key].splitlines(keepends=True)
        path = profile.FILES[key]
        if name != old_name:
            at = next((i for i, row in enumerate(lines) if row.strip() == f"# {old_name}"), None)
            if at is None:
                notes.append(f"{path} has no “# {old_name}” line, so its name wasn't changed. Its first line should be “# {name}”.")
            else:
                lines[at] = _keep_end(lines[at], f"# {name}")
        if contact != old_contact:
            at = next((i for i, row in enumerate(lines) if row.startswith("@ ")), None)
            if at is None:
                notes.append(f"{path} has no “@ ” contact line, so it wasn't changed. Add “@ {contact}” under your name.")
            else:
                lines[at] = _keep_end(lines[at], f"@ {contact}")
        out[key] = "".join(lines)

    source = contact_source(cfg)
    if contact != old_contact and source and not _written(source[0]):
        notes.append(f"The fact check takes the contact line from {source[0]}, which this section doesn't change. "
                      "Change its “@ ” line to match, or drafts will still be checked against the old one.")
    heading = str(cfg.get("guard", {}).get("heading_source", "") or "")
    if name != old_name and heading and not _written(heading):
        notes.append(f"Your master resume, {heading}, opens with your name. This section doesn't change it, so change "
                     f"“# {old_name}” there too.")
    count = (name != old_name) + (contact != old_contact) + (paper != (old_paper or "letter"))
    return Draft(out, count, notes, {"name": name, "contact": contact, "paper": paper})


# ---------- Work history ----------

def _date(raw, what: str, present: bool) -> tuple[str, str]:
    """A typed date as its value ("2023-01", "2023" or "" for the present) and the text a line writes for it."""
    text = _one_line(raw, what)
    if not text or text.lower() in ("present", "now"):
        if not present:
            raise ValueError(f"{what} needs a date, such as Jan 2023.")
        return "", "Present"
    try:
        if re.fullmatch(r"\d{4}-\d{2}", text):
            return text, factsdoc.month_text(text)
        value = factsdoc.month_value(text[:1].upper() + text[1:])
    except factsdoc.FactsError:
        raise ValueError(f"“{text}” isn't a date. Write it as Jan 2023 or 2023, and leave To empty for Present.") from None
    return value, factsdoc.month_text(value) if len(value) == 7 else value


def _months(value: str, end: bool = False) -> int:
    """A date value as a count of months, for comparing. The present is later than any date."""
    if not value:
        return 10 ** 6
    return int(value[:4]) * 12 + (int(value[5:7]) - 1 if len(value) == 7 else (11 if end else 0))


def _value(text: str) -> str:
    try:
        return factsdoc.month_value(text)
    except factsdoc.FactsError:
        return text


def _role(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("A role should be a title, place and dates.")
    title = _one_line(raw.get("title"), "A title")
    if not title:
        raise ValueError("Every role needs a title.")
    place = _one_line(raw.get("place"), "A place")
    start = _date(raw.get("start"), f"{title}'s From", present=False)
    end = _date(raw.get("end"), f"{title}'s To", present=True)
    if _months(end[0], True) < _months(start[0]):
        raise ValueError(f"{title} ends before it starts.")
    line = raw.get("line")
    return {"line": line if isinstance(line, int) else None, "title": title, "place": place, "start": start, "end": end}


def _span(roles: list[tuple[str, str]]) -> tuple[str, str]:
    """The first start and last end of some roles' (start, end) values."""
    return min((r[0] for r in roles), key=_months), max((r[1] for r in roles), key=lambda v: _months(v, True))


def _role_line(indent: str, role: dict, sep: str, old: factsdoc.Role | None = None) -> str:
    start = old.start if old and _value(old.start) == role["start"][0] else role["start"][1]
    end = old.end if old and _value(old.end) == role["end"][0] else role["end"][1]
    note = f" {old.note}" if old and old.note else ""
    head = ", ".join(part for part in (role["title"], role["place"]) if part)
    return f"{indent}- {head}, {start}{sep}{end}{note}"


def _span_text(roles: list[dict]) -> tuple[str, str]:
    first = min(roles, key=lambda r: _months(r["start"][0]))
    last = max(roles, key=lambda r: _months(r["end"][0], True))
    return first["start"][1], last["end"][1]


def _section_end(doc: factsdoc.Doc, section: factsdoc.Section) -> int:
    at = section.end
    while at > section.start + 1 and not doc.bare(at - 1).strip():
        at -= 1
    return at


def _history(texts: dict, cfg: dict, edits: dict) -> Draft:
    out = dict(texts)
    notes: list[str] = []
    titles = profile.known_titles(cfg)
    doc = factsdoc.Doc(texts["facts"])
    want = [entry for entry in _list(edits.get("employers"), "Employers")]
    want_other = edits.get("other")
    if not doc.section("timeline") and (want or want_other):
        sections = [s for s in doc.sections() if s.kind != "contact"]
        doc.insert(sections[0].start if sections else len(doc.lines), ["## Timeline", ""])
    section = doc.section("timeline")
    employers, labeled, unread = doc.timeline(titles)
    items = {item.line: item for item in doc.items(section)} if section else {}
    sep = factsdoc.date_separator("".join(doc.lines[section.start:section.end])) if section else " – "
    plan = Plan()
    count = 0
    known = {e.line: e for e in employers}
    kept: set[int] = set()
    # For the master resume: each employer as it was and as it will be.
    moves: list[dict] = []
    last_employer_end = max((items[e.line].end for e in employers), default=None)
    labeled_end = max((items[entry.line].end for entry in labeled), default=None)
    end_of_section = _section_end(doc, section) if section else len(doc.lines)

    parsed: list[dict[str, Any]] = []
    for entry in want:
        if not isinstance(entry, dict):
            raise ValueError("An employer should be a name and roles.")
        name = _one_line(entry.get("name"), "An employer's name")
        # A row just added and not yet typed in is left out rather than refused.
        raws = [raw for raw in _list(entry.get("roles"), "Roles")
                if not (isinstance(raw, dict) and raw.get("line") is None and not any(
                    str(raw.get(k) or "").strip() for k in ("title", "place", "start", "end")))]
        if not name and not raws and entry.get("line") is None:
            continue
        if not name:
            raise ValueError("Every employer needs a name.")
        roles = [_role(raw) for raw in raws]
        if not roles:
            raise ValueError(f"{name} needs at least one role. To take {name} off, remove the employer.")
        line = entry.get("line")
        old = known.get(line) if isinstance(line, int) else None
        if isinstance(line, int) and old is None:
            raise ValueError("An employer has moved in facts.md since the page read it. Reload and try again.")
        if old is not None:
            if old.line in kept:
                raise ValueError(f"{name} is listed twice.")
            kept.add(old.line)
        parsed.append({"old": old, "name": name, "roles": roles})

    for index, entry in enumerate(parsed):
        old, name, roles = entry["old"], entry["name"], entry["roles"]
        move: dict[str, Any] = {"old": old, "name": name, "roles": [], "removed": []}
        moves.append(move)
        if old is None:
            count += 1 + len(roles)
            if len(roles) == 1:
                role = roles[0]
                head = ", ".join(part for part in (role["title"], role["place"]) if part)
                block = [f"- **{name},** {head}, {role['start'][1]}{sep}{role['end'][1]}"]
            else:
                start, end = _span_text(roles)
                block = [f"- **{name}, {start}{sep}{end}**", *(_role_line("  ", role, sep) for role in roles)]
            move["roles"] = [{"old": None, "new": role} for role in roles]
            after = next((p["old"].line for p in parsed[index + 1:] if p["old"] is not None), None)
            at = after if after is not None else last_employer_end if last_employer_end is not None else \
                min(entry.line for entry in labeled) if labeled else end_of_section
            plan.insert(at, block)
            continue

        by_line = {r.line: r for r in old.roles}
        for role in roles:
            if role["line"] is not None and role["line"] not in by_line:
                raise ValueError(f"A role at {old.name} has moved in facts.md since the page read it. Reload and try again.")
        old_values = [(_value(r.start), _value(r.end)) for r in old.roles]
        new_values = [(r["start"][0], r["end"][0]) for r in roles]
        renamed = name != old.name
        count += renamed

        if old.single and not (len(roles) == 1 and roles[0]["line"] == old.line):
            # One role becomes several, or a different one: written out as an employer with its roles under it.
            prefix = doc.bare(old.line)[:doc.bare(old.line).index("**")]
            indent = prefix[:len(prefix) - len(prefix.lstrip())] + "  "
            start, end = _span_text(roles)
            block = [f"{prefix}**{name}, {start}{sep}{end}**"]
            for role in roles:
                was = by_line.get(role["line"])
                block.append(_role_line(indent, role, sep, was))
                move["roles"].append({"old": was, "new": role})
                count += was is None or _role_changed(was, role)
            move["removed"] = [r for r in old.roles if r.line not in {role["line"] for role in roles}]
            count += len(move["removed"])
            plan.delete(old.line, old.line + 1)
            plan.insert(old.line, block)
            continue

        if old.single:
            role, was = roles[0], old.roles[0]
            text = factsdoc.role_text(was, *_role_changes(was, role))
            if renamed:
                text = factsdoc.employer_text(text, name=name)
            if text != doc.bare(old.line):
                plan.set(old.line, text)
            count += _role_changed(was, role)
            move["roles"].append({"old": was, "new": role})
            continue

        # An employer with its roles under it.
        span_start = span_end = None
        if (_value(old.start), _value(old.end)) == _span(old_values) and _span(new_values) != _span(old_values):
            start, end = _span_text(roles)
            span_start = start if _span(new_values)[0] != _span(old_values)[0] else None
            span_end = end if _span(new_values)[1] != _span(old_values)[1] else None
        if renamed or span_start or span_end:
            plan.set(old.line, factsdoc.employer_text(doc.bare(old.line), name if renamed else None, span_start, span_end))
        bullet = factsdoc.BULLET.fullmatch(doc.bare(old.roles[0].line)) if old.roles else None
        indent = bullet["indent"] if bullet else "  "
        wanted = {role["line"] for role in roles if role["line"] is not None}
        for was in old.roles:
            if was.line not in wanted:
                plan.delete(was.line, items[was.line].end)
                move["removed"].append(was)
                count += 1
        for at, role in enumerate(roles):
            was = by_line.get(role["line"])
            move["roles"].append({"old": was, "new": role})
            if was is not None:
                if _role_changed(was, role):
                    plan.set(was.line, factsdoc.role_text(was, *_role_changes(was, role)))
                    count += 1
                continue
            following = next((r["line"] for r in roles[at + 1:] if r["line"] is not None), None)
            plan.insert(following if following is not None else items[old.line].end, [_role_line(indent, role, sep)])
            count += 1

    removed = [e for e in employers if e.line not in kept]
    for employer in removed:
        plan.delete(employer.line, items[employer.line].end)
        count += 1

    if want_other is not None:
        seen: set[int] = set()
        labeled_by_line = {entry.line: entry for entry in labeled}
        for raw in _list(want_other, "Other lines"):
            if not isinstance(raw, dict):
                raise ValueError("An education or certification line should be a label and text.")
            label = _one_line(raw.get("label"), "A label").rstrip(":")
            text = _one_line(raw.get("text"), "A line's text")
            if not label and not text and not isinstance(raw.get("line"), int):
                continue
            if not label or not text:
                raise ValueError("Education and certification lines need a label, such as Education, and the text.")
            line = raw.get("line")
            if isinstance(line, int):
                old_line = labeled_by_line.get(line)
                if old_line is None:
                    raise ValueError("A line in the Timeline has moved since the page read it. Reload and try again.")
                seen.add(line)
                if (label, text) != (old_line.label, old_line.text):
                    bold = factsdoc.BOLD.search(doc.bare(line))
                    assert bold is not None  # A labeled line is one that starts with a bold label.
                    plan.set(line, f"{doc.bare(line)[:bold.start()]}**{label}:** {text}")
                    count += 1
            else:
                at = labeled_end if labeled_end is not None else last_employer_end if last_employer_end is not None else end_of_section
                plan.insert(at, [f"- **{label}:** {text}"])
                count += 1
        for old_line in labeled:
            if old_line.line not in seen:
                plan.delete(old_line.line, items[old_line.line].end)
                count += 1

    plan.apply(doc)
    out["facts"] = doc.render()
    after_employers, after_labeled, _ = factsdoc.Doc(out["facts"]).timeline(titles)
    _read_back(parsed, after_employers)

    config = texts["config"]
    if "expected" in edits:
        expected = []
        for raw in _list(edits["expected"], "What every resume should include"):
            text = _one_line(raw.get("text") if isinstance(raw, dict) else None, "What a resume should include")
            label = _one_line(raw.get("label"), "Its label") if isinstance(raw, dict) else ""
            if text:
                expected.append({"text": text, "label": label or text})
        before = [{"text": str(i.get("text", "")), "label": str(i.get("label", ""))}
                  for i in cfg.get("guard", {}).get("expected_on_resume", []) if isinstance(i, dict)]
        if expected != before:
            config = tomledit.set_value(config, "guard", "expected_on_resume", expected)
            count += len({(e["text"], e["label"]) for e in expected} ^ {(e["text"], e["label"]) for e in before}) or 1
    out["config"] = config

    heading = str(cfg.get("guard", {}).get("heading_source", "") or "")
    # Roles that are new or changed, by the employer's name as it will be.
    touched = [(m["name"], r["new"]) for m in moves for r in m["roles"]
               if m["old"] is None or m["name"] != m["old"].name or r["old"] is None or _role_changed(r["old"], r["new"])]
    if texts["resume"] and (touched or removed or any(m["removed"] for m in moves)):
        resume, resume_notes = _sync_headings(texts["resume"], moves, removed)
        out["resume"] = resume
        notes += resume_notes
    if (touched or removed or any(m["removed"] for m in moves)) and heading and not _written(heading):
        notes.append(f"Every draft's employers, titles and dates are checked against {heading}, which this section "
                     "doesn't change. Change its ### and #### headings to match, or drafts that use the new ones will be blocked.")
    for employer, role in touched:
        for pattern in cfg.get("guard", {}).get("forbidden", []):
            if re.search(pattern, f"{employer} {role['title']} {role['place']}", re.I):
                notes.append(f"“{role['title']}” at {employer} matches the never-mention pattern {pattern!r}, "
                             "so any draft that shows that role will be blocked.")
    preview_heads = None
    if heading == profile.FILES["resume"] and out["resume"]:
        preview_heads = [row.strip() for row in out["resume"].splitlines() if row.strip().startswith(("### ", "#### "))]
    return Draft(out, count, notes, {
        "headings": preview_heads,
        "timeline": [{"name": e.name, "start": e.start, "end": e.end,
                      "roles": [{"title": r.title, "place": r.place, "start": r.start, "end": r.end} for r in e.roles]}
                     for e in after_employers],
        "other": [{"label": entry.label, "text": entry.text} for entry in after_labeled],
        "gaps": _gaps(after_employers),
    })


def _role_changes(was: factsdoc.Role, role: dict) -> tuple:
    """set_role's arguments: only what differs from the line as it is."""
    return (role["title"] if role["title"] != was.title else None,
            role["place"] if role["place"] != was.place else None,
            role["start"][1] if role["start"][0] != _value(was.start) else None,
            role["end"][1] if role["end"][0] != _value(was.end) else None)


def _role_changed(was: factsdoc.Role, role: dict) -> bool:
    return any(change is not None for change in _role_changes(was, role))


def _read_back(parsed: list[dict], after: list[factsdoc.Employer]) -> None:
    """Refuse a change that facts.md wouldn't read back as it was typed, such as a title with a comma in it."""
    got = {(e.name, r.title, r.place, _value(r.start), _value(r.end)) for e in after for r in e.roles}
    for entry in parsed:
        for role in entry["roles"]:
            if (entry["name"], role["title"], role["place"], role["start"][0], role["end"][0]) not in got:
                raise ValueError(f"facts.md wouldn't read “{role['title']}” at {entry['name']} back as you typed it, so "
                                 "nothing was changed. A comma in a title reads as where the place starts, unless your "
                                 "master resume already uses that title.")


def _gaps(employers: list[factsdoc.Employer]) -> list[str]:
    roles = sorted(((_value(r.start), _value(r.end), r.title) for e in employers for r in e.roles), key=lambda r: _months(r[0]))
    found = []
    latest = None
    for start, end, title in roles:
        if latest is not None and latest < 10 ** 6:
            gap = _months(start) - latest - 1
            if gap > GAP_MONTHS:
                found.append(f"A {gap}-month gap before {title}. That's fine: drafts don't try to hide it.")
        latest = max(latest or 0, _months(end, True))
    return found


# ---------- the master resume's headings ----------

def _heads(doc: factsdoc.Doc) -> list[dict]:
    """The resume's ### employer and #### role headings, read as name or title, place and date values."""
    found = []
    for index in range(len(doc.lines)):
        row = doc.bare(index)
        stripped = row.strip()
        level = 4 if stripped.startswith("#### ") else 3 if stripped.startswith("### ") else 0
        if not level:
            continue
        parts = HEADING_PARTS.split(stripped[level + 1:].strip())
        dates = factsdoc.DATES.fullmatch(parts[-1]) if len(parts) > 1 else None
        found.append({"line": index, "level": level, "parts": parts, "dates": dates,
                      "start": _value(dates["start"]) if dates else None, "end": _value(dates["end"]) if dates else None,
                      "prefix": row[:len(row) - len(row.lstrip())] + "#" * level + " "})
    return found


def _block_end(doc: factsdoc.Doc, start: int, stop) -> int:
    """Where a heading's block ends: the next line that `stop` matches, less any blank lines before it."""
    end = start + 1
    while end < len(doc.lines) and not stop(doc.bare(end).strip()):
        end += 1
    while end > start + 1 and not doc.bare(end - 1).strip():
        end -= 1
    return end


def _dates_part(head: dict, start: str | None, end: str | None) -> str:
    part, dates = head["parts"][-1], head["dates"]
    for (a, b), new in sorted(((dates.span("start"), start), (dates.span("end"), end)), reverse=True):
        if new is not None:
            part = part[:a] + new + part[b:]
    return part


def _sync_headings(text: str, moves: list[dict], removed: list[factsdoc.Employer]) -> tuple[str, list[str]]:
    """profile/resume.md with its headings changed to match the Timeline: renamed, re-dated, added and removed."""
    doc = factsdoc.Doc(text)
    heads = _heads(doc)
    sep = next((h["dates"]["sep"] for h in heads if h["dates"]), " – ")
    plan = Plan()
    notes: list[str] = []
    path = profile.FILES["resume"]
    top = lambda row: row.startswith(("### ", "## ", "# "))
    any_heading = lambda row: row.startswith("#")

    def employer_head(name: str) -> dict | None:
        return next((h for h in heads if h["level"] == 3 and h["parts"][0] == name), None)

    def role_heads(employer: dict | None) -> list[dict]:
        if employer is None:
            return [h for h in heads if h["level"] == 4]
        end = _block_end(doc, employer["line"], top)
        return [h for h in heads if h["level"] == 4 and employer["line"] < h["line"] < end]

    def find_role(employer: dict | None, role: factsdoc.Role) -> dict | None:
        under = role_heads(employer)
        exact = [h for h in under if h["parts"][0] == role.title and h["start"] == _value(role.start)
                 and h["end"] == _value(role.end)]
        if exact:
            return exact[0]
        named = [h for h in under if h["parts"][0] == role.title]
        return named[0] if len(named) == 1 else None

    def new_role_head(role: dict) -> str:
        return "#### " + " | ".join(p for p in (role["title"], role["place"], f"{role['start'][1]}{sep}{role['end'][1]}") if p)

    for employer in removed:
        head = employer_head(employer.name)
        if head:
            plan.delete(head["line"], _block_end(doc, head["line"], top))
        else:
            notes.append(f"{path} has no ### heading for {employer.name}, so nothing was removed there.")

    experience = next((i for i in range(len(doc.lines)) if doc.bare(i).strip().startswith("## Experience")), None)
    for index, move in enumerate(moves):
        old, roles = move["old"], move["roles"]
        if old is None:
            start, end = _span_text([r["new"] for r in roles])
            block = [f"### {move['name']} | {start}{sep}{end}", *(new_role_head(r["new"]) for r in roles)]
            after = next((employer_head(m["old"].name) for m in moves[index + 1:] if m["old"] is not None
                          and employer_head(m["old"].name)), None)
            if after:
                plan.insert(after["line"], block)
            elif experience is not None:
                plan.insert(_block_end(doc, experience, lambda row: row.startswith(("## ", "# "))), block)
            else:
                notes.append(f"{path} has no ## Experience section, so {move['name']} wasn't added there.")
            continue
        head = employer_head(old.name)
        if head is None:
            notes.append(f"{path} has no ### heading for {old.name}, so its headings weren't changed. Add them in your master resume.")
            continue
        parts = list(head["parts"])
        if move["name"] != old.name:
            parts[0] = move["name"]
        before_span = _span([(_value(r.start), _value(r.end)) for r in old.roles])
        after_span = _span([(r["new"]["start"][0], r["new"]["end"][0]) for r in roles])
        if head["dates"] and (head["start"], head["end"]) == before_span and after_span != before_span:
            start, end = _span_text([r["new"] for r in roles])
            parts[-1] = _dates_part(head, start if after_span[0] != before_span[0] else None,
                                    end if after_span[1] != before_span[1] else None)
        if parts != head["parts"]:
            plan.set(head["line"], head["prefix"] + " | ".join(parts))
        for was in move["removed"]:
            found = find_role(head, was)
            if found:
                plan.delete(found["line"], _block_end(doc, found["line"], any_heading))
            else:
                notes.append(f"{path} has no #### heading for {was.title} at {old.name}, so nothing was removed there.")
        for at, pair in enumerate(roles):
            was, role = pair["old"], pair["new"]
            if was is None:
                following = next((find_role(head, p["old"]) for p in roles[at + 1:] if p["old"] is not None
                                  and find_role(head, p["old"])), None)
                plan.insert(following["line"] if following else _block_end(doc, head["line"], top), [new_role_head(role)])
                continue
            if not _role_changed(was, role):
                continue
            found = find_role(head, was)
            if found is None:
                notes.append(f"{path} has no #### heading for {was.title} at {old.name}, so it wasn't changed there.")
                continue
            title, place, start, end = _role_changes(was, role)
            parts = list(found["parts"])
            if title is not None:
                parts[0] = title
            if place is not None:
                if len(parts) >= 3:
                    parts[1:2] = [place] if place else []
                elif place:
                    parts.insert(1, place)
            if found["dates"] and (start is not None or end is not None):
                parts[-1] = _dates_part(found, start, end)
            plan.set(found["line"], found["prefix"] + " | ".join(parts))
    plan.apply(doc)
    return doc.render(), notes


# ---------- Off limits ----------

def term_pattern(term: str) -> str:
    """A pattern that blocks a term as people write it: any case, a hyphen or space or nothing between its words, and
    a plural. "SkyLift 900" blocks SkyLift-900 and skylift 900s."""
    words = [w for w in re.split(r"[\s-]+", re.sub(r"^the\s+", "", term.strip(), flags=re.I)) if w]
    if not words:
        raise ValueError("Type the name or claim to block.")
    body = r"[\s-]?".join(re.escape(w) for w in words)
    last = words[-1][-1]
    if last.isalpha() and last.lower() != "s":
        body += "s?"
    start = r"\b" if re.match(r"\w", words[0]) else r"(?<!\w)"
    end = r"\b" if re.match(r"\w", last) else r"(?!\w)"
    return start + body + end


def _pattern(raw) -> str:
    pattern = _one_line(raw, "A pattern")
    if not pattern:
        raise ValueError("A pattern can't be empty.")
    if len(pattern) > MAX_PATTERN:
        raise ValueError(f"A pattern can be at most {MAX_PATTERN} characters.")
    try:
        compiled = re.compile(pattern, re.I)
    except re.error as err:
        raise ValueError(f"{pattern!r} isn't a pattern Pyrite can read ({err}).") from None
    if compiled.search(""):
        raise ValueError(f"{pattern!r} matches nothing at all, so it would block every draft.")
    return pattern


def _offlimits(texts: dict, cfg: dict, edits: dict) -> Draft:
    out = dict(texts)
    notes: list[str] = []
    guard = cfg.get("guard", {})
    name = str(cfg.get("candidate", {}).get("name", ""))
    doc = factsdoc.Doc(texts["facts"])
    plan = Plan()
    config = texts["config"]
    lists = {}
    adds: dict[str, list[str]] = {}
    count = 0
    for kind, key in (("never", "forbidden"), ("nottrue", "unsupported")):
        change = edits.get(kind) or {}
        if not isinstance(change, dict):
            raise ValueError("Nothing to change.")
        section = _excluded(doc, kind)
        items = {item.line: item for item in doc.items(section)} if section else {}
        for line in _list(change.get("drop_items"), "Items to remove"):
            if line not in items:
                raise ValueError("A line in facts.md has moved since the page read it. Reload and try again.")
            plan.delete(line, items[line].end)
            count += 1
        drop = set(_list(change.get("drop_patterns"), "Patterns to remove"))
        patterns = [p for p in guard.get(key, []) if p not in drop]
        count += len(guard.get(key, [])) - len(patterns)
        remaining = [item.text for line, item in items.items() if line not in set(change.get("drop_items") or [])]
        adds[kind] = []
        for raw in _list(change.get("add"), "Terms to block"):
            term = _one_line(raw, "A term")
            if not term:
                continue
            made = term_pattern(term)
            listed = any(re.search(made, text, re.I) for text in remaining + adds[kind])
            blocked = any(re.search(p, term, re.I) for p in patterns)
            if listed and blocked:
                notes.append(f"“{term}” is blocked already.")
                continue
            if not listed:
                adds[kind].append(term)
            if not blocked:
                patterns.append(made)
            count += 1
        for raw in _list(change.get("add_patterns"), "Patterns to add"):
            pattern = _pattern(raw)
            if pattern not in patterns:
                patterns.append(pattern)
                count += 1
        if key == "forbidden":
            for pattern in patterns:
                if name and pattern not in guard.get(key, []) and re.search(pattern, name, re.I):
                    raise ValueError(f"{pattern!r} matches your own name, so every draft would be blocked.")
        if patterns != guard.get(key, []):
            config = tomledit.edit_list(config, "guard", key, remove=drop,
                                        add=[p for p in patterns if p not in guard.get(key, [])], literal=True)
        lists[key] = patterns
        if section and adds[kind]:
            found = doc.items(section)
            at = max((item.end for item in found), default=_section_end(doc, section))
            plan.insert(at, [f"- {term}" for term in adds[kind]])
    plan.apply(doc)
    for kind, title in (("never", DO_NOT_USE_TITLE), ("nottrue", UNSUPPORTED_TITLE)):
        if adds[kind] and not _excluded(doc, kind):
            doc.add_section(title, adds[kind])
    out["facts"] = doc.render()
    out["config"] = config

    titles = profile.known_titles(cfg)
    for employer in factsdoc.Doc(out["facts"]).timeline(titles)[0]:
        for pattern in lists["forbidden"]:
            if pattern not in guard.get("forbidden", []) and re.search(pattern, employer.name, re.I):
                notes.append(f"{pattern!r} matches {employer.name}, an employer in your work history, so every draft "
                             "that names it will be blocked.")
    new_guard = {**guard, "forbidden": lists["forbidden"], "unsupported": lists["unsupported"]}
    test = _one_line(edits.get("test"), "The sentence to test")
    return Draft(out, count, notes, {
        "test": checks.explain(test, new_guard) if test else None,
        "unguarded": doctor.unguarded_terms(out["facts"], lists["forbidden"], name),
        "patterns": {"never": lists["forbidden"], "nottrue": lists["unsupported"]},
    })


# ---------- Skills and terms ----------

def _skills(texts: dict, cfg: dict, edits: dict) -> Draft:
    out = dict(texts)
    text = texts["terms"]
    lines = text.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in text else "\n"
    count = 0
    notes: list[str] = []
    drops: dict[int, list[str]] = {}
    for raw in _list(edits.get("drop"), "Terms to remove"):
        line, term = (raw.get("line"), raw.get("term")) if isinstance(raw, dict) else (None, None)
        if not isinstance(line, int) or not 0 <= line < len(lines) or lines[line].lstrip().startswith("#") \
                or term not in re.split(r"[\s,;]+", lines[line].strip()):
            raise ValueError("approved-terms.txt has changed since the page read it. Reload and try again.")
        drops.setdefault(line, []).append(term)
    for line in sorted(drops, reverse=True):
        pieces = TERM_SPLIT.split(lines[line].rstrip("\r\n"))
        for term in drops[line]:
            at = next(i for i in range(0, len(pieces), 2) if pieces[i] == term)
            # The term goes with the separator after it, or before it if it's last.
            if at + 1 < len(pieces):
                del pieces[at:at + 2]
            else:
                del pieces[max(at - 1, 0):at + 1]
            count += 1
        rest = "".join(pieces)
        if rest.strip():
            lines[line] = _keep_end(lines[line], rest)
        else:
            del lines[line]
    approved = confirm._terms(text)
    added = []
    for raw in _list(edits.get("add"), "Terms to approve"):
        term = _one_line(raw, "A term")
        if not term:
            continue
        if term.startswith("#"):
            raise ValueError("A term can't start with #: that line would be read as a comment.")
        words = [w for w in re.split(r"[\s,;]+", term) if w]
        if all(word in approved for word in words):
            notes.append(f"“{term}” is approved already.")
            continue
        if len(words) > 1:
            notes.append(f"Drafts read approved-terms.txt a word at a time, so “{term}” approves "
                         f"{', '.join(f'“{w}”' for w in words)} each on its own.")
        added.append(term)
        count += 1
    if added:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += eol
        lines += [term + eol for term in added]
    out["terms"] = "".join(lines)
    return Draft(out, count, notes, {"groups": _term_lines(out["terms"])})


DRAFTERS = {"basics": _basics, "history": _history, "offlimits": _offlimits, "skills": _skills}
