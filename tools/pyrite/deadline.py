"""When a posting stops taking applications, and what to settle before applying.

Job boards have no closing-date field, so this reads the posting's own words ("accepted at
least until November 8, 2026", "expected to close on November 16th, 2026") and the
**Deadline:** line of the job's notes.md. The notes win, since they were written by reading
the whole posting, or by you after checking. Notes also say what could rule an
application out (residency, a missing core skill, a stale date): a **Check before
applying:** line, a "Before you apply" section, or any line that says to do something
before applying. Posting text is data, so all of this is shown as text and never acted on.
"""
import re
from datetime import date
from pathlib import Path

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

_DEADLINE_LINE = re.compile(r"\*\*deadline\b", re.I)
_CHECK_LINE = re.compile(r"\*\*check before applying:?\*\*:?\s*(.*)", re.I)
_BEFORE = re.compile(r"before (?:applying|you apply)|needs a decision", re.I)
_BEFORE_HEADING = re.compile(r"^#{2,4}\s.*before you apply", re.I)
_ITEM = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.*)")
_BOLD_LEAD = re.compile(r"^\*\*(.+?)\*\*")
_MAX_BLOCKERS = 6
_MAX_CHARS = 220


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


def from_posting(description: str) -> str | None:
    """The closing date a posting states, as an ISO date, or None."""
    for cue in _CUE.finditer(description or ""):
        after = description[cue.end():cue.end() + _CUE_REACH]
        stop = _CUE_STOP.search(after)
        when = first_date(after[:stop.start()] if stop else after)
        if when:
            return when.isoformat()
    return None


def _plain(text: str) -> str:
    text = re.sub(r"\*\*|__|`", "", text).strip()
    return text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS - 1].rstrip() + "…"


def _lead(item: str) -> str:
    """A list item's bold lead if it has one, otherwise its first sentence."""
    bold = _BOLD_LEAD.match(item.strip())
    if bold:
        return bold[1].strip().rstrip(".:")
    return re.split(r"(?<=[.!?])\s", item.strip(), maxsplit=1)[0]


def from_notes(text: str) -> tuple[str | None, list[str]]:
    """The deadline and the things to settle before applying, from a job's notes.md."""
    deadline, blockers = None, []
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
        check = _CHECK_LINE.search(line)
        item = _ITEM.match(line)
        if check and check[1].strip():
            blockers.append(_plain(check[1]))
        elif in_section and item:
            blockers.append(_plain(_lead(item[1])))
        elif _BEFORE.search(line) and not in_section:
            body = item[1] if item else line
            label = _BOLD_LEAD.match(body.strip())
            rest = body.strip()[label.end():].lstrip(" :") if label else body
            sentence = next((s for s in re.split(r"(?<=[.!?])\s", rest) if _BEFORE.search(s)), rest)
            if re.match(r"see\b", sentence.strip(), re.I):
                continue  # A pointer to a "Before you apply" section, whose items are read on their own.
            blockers.append(_plain(f"{label[1].rstrip(':')}: {sentence}" if label else sentence))
    unique = list(dict.fromkeys(b for b in blockers if b))
    return deadline, unique[:_MAX_BLOCKERS]


_cache: dict[Path, tuple[int, tuple[str | None, list[str]]]] = {}


def read_notes(folder: Path) -> tuple[str | None, list[str]]:
    """from_notes for a folder's notes.md, read again only when the file changes."""
    path = folder / "notes.md"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None, []
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        result = from_notes(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        result = (None, [])
    _cache[path] = (stamp, result)
    return result
