"""facts.md as sections and bullets, read and written without losing a byte.

The fact bank is Markdown written by hand, and the Profile tab changes it a line at a time. Every line is kept exactly
as it was read, ending included, so an unchanged document renders to the same bytes and a change touches only the
lines it's about. The Timeline is also read as employers and roles, since Work history edits those, but a line that
doesn't read as either is left alone rather than guessed at.
"""
import re
from dataclasses import dataclass, field

from .checks import EXCLUDED_SECTION

HEADING = re.compile(r"##[ \t]+(?P<title>.+?)\s*$")
BULLET = re.compile(r"(?P<indent>[ \t]*)[-*][ \t]+(?P<text>.*?)\s*$")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
DATES = re.compile(rf"(?P<start>{MONTH} \d{{4}}|\d{{4}})(?P<sep>\s*(?:[–—-]|to)\s*)"
                   rf"(?P<end>{MONTH} \d{{4}}|\d{{4}}|[Pp]resent|[Nn]ow)")
BOLD = re.compile(r"\*\*(?P<bold>.+?)\*\*")
COMMENT_LINE = re.compile(r"<!--.*?-->")


class FactsError(ValueError):
    """A change that can't be made to facts.md as it's written, so nothing was changed."""


@dataclass
class Section:
    title: str
    start: int  # The heading's line.
    end: int  # The line after the section's last.

    @property
    def kind(self) -> str:
        """contact, timeline, excluded (approves nothing) or facts."""
        title = self.title.lower()
        if EXCLUDED_SECTION.match(f"## {title}"):
            return "excluded"
        if title.startswith("contact"):
            return "contact"
        if title.startswith("timeline"):
            return "timeline"
        return "facts"


@dataclass
class Item:
    """A bullet, with any lines that continue it or sit under it."""
    line: int
    level: int
    text: str
    end: int


@dataclass
class Role:
    line: int
    text: str  # The whole line, without its ending.
    title: str
    place: str
    start: str
    end: str
    note: str
    head: tuple[int, int]  # Where the title and place are in the line.
    start_at: tuple[int, int]
    end_at: tuple[int, int]


@dataclass
class Employer:
    line: int
    name: str
    start: str
    end: str
    roles: list[Role] = field(default_factory=list)
    single: bool = False  # Written on one line, "**Name,** Title, Place, dates", with no roles under it.


@dataclass
class Labeled:
    """A Timeline line such as "**Education:** ..." that isn't an employer."""
    line: int
    label: str
    text: str


def month_text(value: str) -> str:
    """'2023-01' as 'Jan 2023'. An empty value is the present."""
    if not value:
        return "Present"
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not match or not 1 <= int(match[2]) <= 12:
        raise FactsError(f"{value!r} isn't a month. Use the form 2023-01.")
    return f"{MONTHS[int(match[2]) - 1]} {match[1]}"


def month_value(text: str) -> str:
    """'Jan 2023' as '2023-01', a bare year as '2023', and the present as ''."""
    text = text.strip()
    if text.lower() in ("present", "now"):
        return ""
    match = re.fullmatch(rf"({MONTH}) (\d{{4}})", text)
    if match:
        return f"{match[2]}-{MONTHS.index(match[1][:3]) + 1:02d}"
    if re.fullmatch(r"\d{4}", text):
        return text
    raise FactsError(f"{text!r} isn't a month and year.")


class Doc:
    def __init__(self, text: str):
        self.lines = text.splitlines(keepends=True)
        self.eol = "\r\n" if "\r\n" in text else "\n"

    def render(self) -> str:
        return "".join(self.lines)

    def bare(self, index: int) -> str:
        return self.lines[index].rstrip("\r\n")

    # ---------- reading ----------

    def sections(self) -> list[Section]:
        found: list[Section] = []
        for index in range(len(self.lines)):
            match = HEADING.fullmatch(self.bare(index))
            if match:
                if found:
                    found[-1].end = index
                found.append(Section(match["title"], index, len(self.lines)))
        return found

    def section(self, name: str) -> Section | None:
        """The first section whose title starts with `name`, ignoring case."""
        name = name.lower()
        return next((s for s in self.sections() if s.title.lower().startswith(name)), None)

    def items(self, section: Section) -> list[Item]:
        found: list[Item] = []
        index = section.start + 1
        while index < section.end:
            match = BULLET.fullmatch(self.bare(index))
            if not match:
                index += 1
                continue
            indent = len(match["indent"].expandtabs(2))
            end = index + 1
            while end < section.end:
                line = self.bare(end)
                below = BULLET.fullmatch(line)
                if not line.strip() or (below and len(below["indent"].expandtabs(2)) <= indent):
                    break
                if not below and len(line) - len(line.lstrip()) <= indent:
                    break
                end += 1
            found.append(Item(index, indent // 2, match["text"], end))
            index += 1
        return found

    def contact(self) -> tuple[int, str] | None:
        """The contact line: the first line of text under ## Contact, past any <!-- comment --> saying what goes there."""
        section = self.section("contact")
        if not section:
            return None
        for index in range(section.start + 1, section.end):
            if self.bare(index).strip() and not COMMENT_LINE.fullmatch(self.bare(index).strip()):
                return index, self.bare(index).strip()
        return None

    # ---------- the Timeline ----------

    def timeline(self, titles: tuple[str, ...] = ()) -> tuple[list[Employer], list[Labeled], list[int]]:
        """Employers with their roles, labeled lines such as Education, and the lines that read as neither.

        `titles` are job titles known to be right, such as the master resume's, which settle where a title that has a
        comma in it ends and its place begins."""
        section = self.section("timeline")
        employers: list[Employer] = []
        labeled: list[Labeled] = []
        unread: list[int] = []
        if not section:
            return employers, labeled, unread
        for item in self.items(section):
            if item.level > 0:
                continue
            employer = self._employer(item, titles)
            if isinstance(employer, Employer):
                employers.append(employer)
            elif isinstance(employer, Labeled):
                labeled.append(employer)
            else:
                unread.append(item.line)
        return employers, labeled, unread

    def _employer(self, item: Item, titles: tuple[str, ...]) -> Employer | Labeled | None:
        line = self.bare(item.line)
        bold = BOLD.search(line)
        if not bold:
            return None
        inside = bold["bold"].strip()
        if inside.endswith(":"):
            return Labeled(item.line, inside[:-1].strip(), line[bold.end():].strip())
        if inside.endswith(","):
            role = _role(item.line, line, bold.end(), titles)
            if not role:
                return None
            return Employer(item.line, inside[:-1].strip(), role.start, role.end, [role], single=True)
        dates = _last_dates(inside)
        if not dates:
            return None
        employer = Employer(item.line, inside[:dates.start()].rstrip(" ,"), dates["start"], dates["end"])
        for index in range(item.line + 1, item.end):
            match = BULLET.fullmatch(self.bare(index))
            if match:
                role = _role(index, self.bare(index), len(match["indent"]) + 2, titles)
                if role:
                    employer.roles.append(role)
        return employer

    # ---------- writing ----------

    def set_line(self, index: int, text: str) -> None:
        """Replace one line's text, keeping its line ending."""
        old = self.lines[index]
        ending = old[len(old.rstrip("\r\n")):] or self.eol
        if "\n" in text or "\r" in text:
            raise FactsError("One line can't hold a line break.")
        self.lines[index] = text + ending

    def insert(self, index: int, texts: list[str]) -> None:
        if index > 0 and not self.lines[index - 1].endswith("\n"):
            self.lines[index - 1] += self.eol
        self.lines[index:index] = [text + self.eol for text in texts]

    def delete(self, start: int, end: int) -> None:
        del self.lines[start:end]

    def set_item(self, item: Item, text: str) -> None:
        match = BULLET.fullmatch(self.bare(item.line))
        if not match:
            raise FactsError("That line isn't a bullet any more.")
        bullet = self.bare(item.line)[:match.start("text")]
        self.set_line(item.line, bullet + text.strip())

    def add_item(self, section: Section, text: str, after: Item | None = None, level: int = 0) -> int:
        """Add a bullet after `after` (and anything under it), or after the section's last bullet. Returns its line."""
        items = self.items(section)
        if after is not None:
            at = after.end
        elif items:
            at = max(item.end for item in items)
        else:
            at = section.start + 1
            while at < section.end and not self.bare(at).strip():
                at += 1
        self.insert(at, ["  " * level + "- " + text.strip()])
        return at

    def remove_item(self, item: Item) -> None:
        self.delete(item.line, item.end)

    def add_section(self, title: str, texts: tuple[str, ...] | list[str] = ()) -> Section:
        """A new section, before the ones that approve nothing so those stay last."""
        sections = self.sections()
        excluded = next((s for s in sections if s.kind == "excluded"), None)
        at = excluded.start if excluded else len(self.lines)
        block = [f"## {title.strip()}", *("- " + text.strip() for text in texts), ""]
        if at == len(self.lines) and self.lines and self.bare(len(self.lines) - 1).strip():
            block.insert(0, "")
        self.insert(at, block)
        found = self.section(title.strip())
        assert found is not None
        return found

    def set_role(self, role: Role, title: str | None = None, place: str | None = None,
                 start: str | None = None, end: str | None = None) -> None:
        """Change a role's title, place or dates. Dates are written as the line already writes them, such as Jan 2023."""
        self.set_line(role.line, role_text(role, title, place, start, end))


def role_text(role: Role, title: str | None = None, place: str | None = None,
              start: str | None = None, end: str | None = None) -> str:
    """The role's line with its title, place or dates changed, and everything else, such as a note, as it was."""
    line = role.text
    changes = []
    if title is not None or place is not None:
        head = ", ".join(part for part in ((title if title is not None else role.title).strip(),
                                            (place if place is not None else role.place).strip()) if part)
        changes.append((role.head, head))
    if start is not None:
        changes.append((role.start_at, start))
    if end is not None:
        changes.append((role.end_at, end))
    for (a, b), new in sorted(changes, reverse=True):
        line = line[:a] + new + line[b:]
    return line


def employer_text(line: str, name: str | None = None, start: str | None = None, end: str | None = None) -> str:
    """An employer's line with its name or dates changed. A one-line employer ("**Name,** Title, ...") has only its name
    here: its dates are its role's."""
    bold = BOLD.search(line)
    if not bold:
        raise FactsError("That line isn't an employer any more.")
    inside, offset = bold["bold"], bold.start("bold")
    changes = []
    if inside.rstrip().endswith(","):
        if name is not None:
            core = inside.rstrip()[:-1]
            lead = len(core) - len(core.lstrip())
            changes.append((offset + lead, offset + len(core), name.strip()))
    else:
        dates = _last_dates(inside)
        if not dates:
            raise FactsError("That employer's line has no dates any more.")
        if start is not None:
            changes.append((offset + dates.start("start"), offset + dates.end("start"), start))
        if end is not None:
            changes.append((offset + dates.start("end"), offset + dates.end("end"), end))
        if name is not None:
            head = inside[:dates.start()].rstrip(" ,")
            lead = len(head) - len(head.lstrip())
            changes.append((offset + lead, offset + len(head), name.strip()))
    for a, b, new in sorted(changes, reverse=True):
        line = line[:a] + new + line[b:]
    return line


def date_separator(text: str) -> str:
    """How the first date range in the text joins its dates, such as " – ", for new lines to match."""
    match = DATES.search(text)
    return match["sep"] if match else " – "


def _last_dates(text: str) -> re.Match | None:
    """The last date range in the text, since a role's title or note can hold a date of its own."""
    matches = list(DATES.finditer(text))
    return matches[-1] if matches else None


def _split_title(head: str, titles: tuple[str, ...]) -> tuple[str, str]:
    for title in sorted(titles, key=len, reverse=True):
        if head == title:
            return title, ""
        if head.startswith(title + ", "):
            return title, head[len(title) + 2:]
    title, _, place = head.partition(", ")
    return title, place


def _role(index: int, line: str, offset: int, titles: tuple[str, ...]) -> Role | None:
    """A role from `line`, whose title starts at `offset`: "Title, Place, Jan 2020 – Mar 2023 (a note)"."""
    dates = _last_dates(line[offset:])
    if not dates:
        return None
    raw_head = line[offset:offset + dates.start()]
    head = raw_head.rstrip(" ,")
    lead = len(head) - len(head.lstrip())
    head = head.strip()
    if not head:
        return None
    title, place = _split_title(head, titles)
    start = offset + lead
    return Role(
        line=index, text=line, title=title, place=place, start=dates["start"], end=dates["end"],
        note=line[offset + dates.end():].strip(), head=(start, start + len(head)),
        start_at=(offset + dates.start("start"), offset + dates.end("start")),
        end_at=(offset + dates.start("end"), offset + dates.end("end")),
    )
