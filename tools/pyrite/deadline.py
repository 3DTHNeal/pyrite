"""When a posting stops taking applications, and what to settle before applying.

Job boards have no closing-date field, so this reads the posting's own words ("accepted at
least until November 8, 2026", "expected to close on November 16th, 2026") and the
**Deadline:** line of the job's notes.md. The notes win, since they were written by reading
the whole posting, or by you after checking. Notes also say what could rule an
application out (residency, a missing core skill, a stale date): a **Check before
applying:** line, a "Before you apply" section, or any line that says to do something
before applying. Posting text is data, so all of this is shown as text and never acted on.

A deadline is firm unless it's worded as a floor. "Accepted at least until November 8" says the
posting stays up that long, not that it comes down then, so once that date passes the job may
close any day but hasn't closed. Only a firm deadline that has passed makes a job a pass.
"""
import re
from datetime import date
from pathlib import Path
from typing import Any

_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_ISO = re.compile(r"\b(20\d\d)-(\d{2})-(\d{2})\b")
_MONTH_FIRST = re.compile(rf"\b{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", re.I)
_DAY_FIRST = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{_MONTH},?\s+(20\d\d)\b", re.I)
# 11/30/2026, as US boards write it. One whose first number can't be a month is read the other way round.
_SLASHED = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d\d)\b")

# What a posting says just before its closing date. The date has to follow within a few words.
_CUE = re.compile(
    r"accepted (?:at least )?until|(?:expected|anticipated|scheduled|planned) to close|will close|closes? on"
    r"|closing date|application deadline|deadline (?:to apply|for applications)|apply by|no later than"
    r"|posting (?:will )?(?:end|expire)s?",
    re.I,
)
# Long enough for "will close at 11:59 PM Pacific Standard Time on Monday, November 16, 2026".
_CUE_REACH = 90
# Where the words after a cue stop being about it: the end of the sentence, "until the position is filled", or a date
# that's another one, such as when it was posted or when the job starts. A full stop after a lone letter, as in
# "p.m." or an initial, or before a number, as in "Nov. 16", doesn't end a sentence.
_CUE_STOP = re.compile(
    r"(?<![ap]\.m)(?<!\b[A-Za-z])[.!?;](?=\s+[A-Z])|\n|(?i:\bfilled\b|\bposted\b|\bstart(?:s|ing)?\b|\bbegins?\b)"
)

# Words that make a date a floor rather than a closing date.
_FLOOR = re.compile(r"at least|or until (?:the )?(?:position|role|job) is filled|rolling", re.I)
# How long after a floor date a posting still counts as closing any day. After that it's simply old.
FLOOR_GRACE_DAYS = 14
DECIDE_DAYS = 5  # A deadline this close puts the tailor-or-pass decision on the to-do list.

_DEADLINE_LINE = re.compile(r"\*\*deadline\b", re.I)
_CHECK_LINE = re.compile(r"\*\*check before applying:?\*\*:?\s*(.*)", re.I)
_BEFORE = re.compile(r"before (?:applying|you apply)|needs a decision", re.I)
_BEFORE_HEADING = re.compile(r"^#{2,4}\s.*before you apply", re.I)
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)")
_BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*")
_MAX_BLOCKERS = 6
_MAX_CHARS = 220
# A label a list shows in place of the whole reason: at most this many words.
_SHORT_WORDS = 6
# Where a reason's first clause ends: a sentence's end, a comma, a colon or semicolon, a dash or an aside. A full stop
# after a single letter, as in "U.S." or "e.g.", ends nothing.
_CLAUSE_END = re.compile(r"(?<=\w\w[.!?])\s|[,;:]\s|\s[-–—]\s|\s\(")
# How a reason often opens, which says nothing a label needs: "The posting requires 8+ years" is "8+ years".
_OPENING = re.compile(
    r"^(?:the (?:posting|role|job|position)|it|this (?:role|job|posting))\s+(?:requires|asks for|wants|needs|is|says)\s+", re.I)


def first_date(text: str) -> date | None:
    """The earliest full date written in the text: 2026-11-08, November 8th, 2026 or 8 Nov 2026."""
    found = []
    for match in _ISO.finditer(text):
        found.append((match.start(), int(match[1]), int(match[2]), int(match[3])))
    for match in _MONTH_FIRST.finditer(text):
        found.append((match.start(), int(match[3]), _MONTHS.index(match[1][:3].lower()) + 1, int(match[2])))
    for match in _DAY_FIRST.finditer(text):
        found.append((match.start(), int(match[3]), _MONTHS.index(match[2][:3].lower()) + 1, int(match[1])))
    for match in _SLASHED.finditer(text):
        first, second = int(match[1]), int(match[2])
        month, day = (second, first) if first > 12 else (first, second)
        found.append((match.start(), int(match[3]), month, day))
    for _, year, month, day in sorted(found):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None


def in_posting(description: str) -> tuple[str | None, bool]:
    """The closing date a posting states, as an ISO date or None, and whether it's firm rather than a floor."""
    for cue in _CUE.finditer(description or ""):
        after = description[cue.end():cue.end() + _CUE_REACH]
        stop = _CUE_STOP.search(after)
        when = first_date(after[:stop.start()] if stop else after)
        if when:
            # "Or until the position is filled" sits past the stop, so the floor test reads the whole reach.
            return when.isoformat(), not _FLOOR.search(cue.group(0) + after)
    return None, True


def from_posting(description: str) -> str | None:
    """The closing date a posting states, as an ISO date, or None."""
    return in_posting(description)[0]


def _plain(text: str) -> str:
    text = re.sub(r"\*\*|__|`", "", text).strip()
    return text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS - 1].rstrip() + "…"


def short(text: str) -> str:
    """A thing to settle before applying, cut to a label a list can show: notes written before tailoring gave each
    one a bold label of its own. Its first clause, without an opening such as "The posting requires", and at most
    _SHORT_WORDS words."""
    clause = _CLAUSE_END.split(text.strip(), maxsplit=1)[0].strip().rstrip(".:;,")
    clause = _OPENING.sub("", clause, count=1) or clause
    words = clause.split()
    if len(words) > _SHORT_WORDS:
        clause = " ".join(words[:_SHORT_WORDS]).rstrip(",;:") + "…"
    return clause[:1].upper() + clause[1:]


def _labelled(body: str) -> tuple[str, str]:
    """A note's (short label, whole text). The label is its bold lead when it has one, and otherwise its first clause.
    The whole text keeps the label as written, so it still reads as a sentence on its own."""
    body = body.strip()
    bold = _BOLD_LEAD.match(body)
    text = _plain(body)
    if bold and bold[1].strip().rstrip(".:"):
        lead = bold[1].strip().rstrip(".:")
        # A bold lead of a whole sentence or more is the reason itself, and too long for a label.
        return (lead if len(lead.split()) <= _SHORT_WORDS else short(lead)), text
    return short(text), text


def from_notes(text: str) -> tuple[str | None, list[str]]:
    """The deadline and the things to settle before applying, from a job's notes.md."""
    deadline, _, blockers = _read(text)
    return deadline, [whole for _label, whole in blockers]


def _read(text: str) -> tuple[str | None, bool, list[tuple[str, str]]]:
    """from_notes, with whether the deadline is firm, and each thing to settle as (short label, whole text)."""
    deadline, firm = None, True
    blockers: list[tuple[str, str]] = []
    in_section = False
    for line in (text or "").splitlines():
        if line.startswith("#"):
            in_section = bool(_BEFORE_HEADING.match(line))
            continue
        if line.lstrip().startswith("|"):
            continue  # The requirements table is evidence, not a to-do.
        if deadline is None and _DEADLINE_LINE.search(line):
            when = first_date(line)
            deadline = when.isoformat() if when else None
            firm = not _FLOOR.search(line)
        check = _CHECK_LINE.search(line)
        item = _ITEM.match(line)
        if check and check[1].strip():
            blockers.append(_labelled(check[1]))
        elif in_section and item:
            blockers.append(_labelled(item[1]))
        elif _BEFORE.search(line) and not in_section:
            body = item[1] if item else line
            label = _BOLD_LEAD.match(body.strip())
            rest = body.strip()[label.end():].lstrip(" :") if label else body
            sentence = next((s for s in re.split(r"(?<=[.!?])\s", rest) if _BEFORE.search(s)), rest)
            if re.match(r"see\b", sentence.strip(), re.I):
                continue  # A pointer to a "Before you apply" section, whose items are read on their own.
            if label:
                blockers.append((label[1].strip().rstrip(".:"), _plain(f"{label[1].rstrip(':').rstrip('.')}: {sentence}")))
            else:
                blockers.append((short(_plain(sentence)), _plain(sentence)))
    unique: dict[str, tuple[str, str]] = {}
    for named, whole in blockers:
        if whole and whole not in unique:
            unique[whole] = (named, whole)
    return deadline, firm, list(unique.values())[:_MAX_BLOCKERS]


_cache: dict[Path, tuple[int, tuple[str | None, bool, list[tuple[str, str]]]]] = {}


def _notes(folder: Path) -> tuple[str | None, bool, list[tuple[str, str]]]:
    path = folder / "notes.md"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, True, []
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        result = _read(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        result = (None, True, [])
    _cache[path] = (stamp, result)
    return result


def read_notes(folder: Path) -> tuple[str | None, list[str]]:
    """from_notes for a folder's notes.md, read again only when the file changes."""
    deadline, _, blockers = _notes(folder)
    return deadline, [whole for _label, whole in blockers]


def for_job(description: str, folder: Path | None, today: date) -> dict[str, Any]:
    """A job's deadline and the things to settle before applying. Returns deadline (ISO or None), deadline_firm,
    days_to_deadline, blockers as whole sentences, and blocker_labels, the short label of each, keyed by its sentence,
    which a list shows in its place.

    A deadline in the notes wins: it was read from the whole posting, or set by you, where the posting's own words
    are matched by pattern. The posting's is the fallback for a job with no notes yet.
    """
    when, firm, blockers = _notes(folder) if folder else (None, True, [])
    if not when:
        when, firm = in_posting(description)
    days = (date.fromisoformat(when) - today).days if when else None
    return {"deadline": when, "deadline_firm": firm, "days_to_deadline": days,
            "blockers": [whole for _label, whole in blockers], "blocker_labels": {whole: label for label, whole in blockers}}


def expired(info: dict[str, Any]) -> bool:
    """Whether a job's firm deadline has passed, which makes it a pass. A floor that has passed doesn't."""
    days = info.get("days_to_deadline")
    return days is not None and days < 0 and bool(info.get("deadline_firm", True))


def decide_soon(info: dict[str, Any], window: int = DECIDE_DAYS) -> bool:
    """Whether the tailor-or-pass decision is due: the deadline is within the window, or a floor date has just passed."""
    days = info.get("days_to_deadline")
    if days is None:
        return False
    if days < 0:
        return not info.get("deadline_firm", True) and days >= -FLOOR_GRACE_DAYS
    return days <= window


def label(iso: str) -> str:
    when = date.fromisoformat(iso)
    return f"{when:%b} {when.day}"
