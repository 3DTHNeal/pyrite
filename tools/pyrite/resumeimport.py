"""Draft a master resume in Pyrite's Markdown form from a .docx, a PDF or plain text, for the person to correct.

Nothing here is AI. The structure of a resume (name, contact line, section headings, employers, roles with dates, and
bullets) is mostly mechanical, so this reads it from the text python-docx or pdftotext extracts and writes the `#`,
`=`, `@`, `##`, `###`, `####` and `-` lines the assay reads. Where a line could be read two ways, it picks one and says
which in its notes, so the person knows what to check. It never drops a line it couldn't place: those are kept as
they are, and named.
"""
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import doctor
from .steps import EMAIL, LINK, PHONE

# The dashboard runs under pythonw, with no console of its own, so a console program it starts would open a window
# of its own unless told not to.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SEPARATOR = " · "
DATE_SEP = " – "
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_WHEN = rf"(?:{_MONTH}\s+\d{{4}}|\d{{1,2}}/\d{{4}}|\d{{4}})"
DATES = re.compile(rf"(?P<start>{_WHEN})\s*(?:[–—-]|\bto\b|\buntil\b)\s*(?P<end>{_WHEN}|present|current|now|today)\b",
                   re.I)
# A bullet's mark as extractors give it: the usual glyphs, Symbol-font private-use ones, and "o" from Word's lists.
BULLET_MARK = re.compile(r"^(?:[•●▪■◦○◆◇➢➤►▸✓✔‣⁃∙·*\-–]|o(?=\s))\s*")
LONE_MARK = re.compile(r"^(?:[•●▪■◦○◆◇➢➤►▸✓✔‣⁃∙·*\-–]|o)$")
# What splits a line into fields: a bar, a bullet or dot between spaces, a tab, a wide gap, or a spaced dash.
FIELD_SEP = re.compile(r"\s*(?:\||\t+| {3,})\s*|\s+[•·●◦]\s+|\s+[–—-]\s+")
PLACE = re.compile(r"^(?:[A-Z][A-Za-z.' -]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)(?:\s+\d{5})?|Remote|Hybrid)$")
TRAILING_PLACE = re.compile(r",\s*(?P<place>[A-Z][A-Za-z.' -]+,\s*[A-Z]{2})$")
TITLE_WORD = re.compile(
    r"\b(?:engineer|engineering|manager|director|developer|analyst|lead|leader|specialist|consultant|designer|"
    r"scientist|architect|intern|officer|coordinator|administrator|president|vp|head|technician|associate|assistant|"
    r"owner|founder|co-founder|programmer|researcher|fellow|principal|staff|senior|sr|junior|jr|chief|cto|ceo|cfo|"
    r"coo|supervisor|representative|advisor|adviser|instructor|teacher|professor|editor|writer|accountant|"
    r"nurse|attorney|counsel|partner|strategist|planner|producer|operator|mechanic|electrician|chemist)\b",
    re.I)
SECTIONS = {
    "Summary": ("summary", "professional summary", "profile", "professional profile", "about", "about me",
                "objective", "career objective", "career summary", "executive summary", "overview", "summary of qualifications"),
    "Skills": ("skills", "core skills", "technical skills", "key skills", "core competencies", "competencies",
               "areas of expertise", "expertise", "skills and tools", "technologies", "tools and technologies",
               "skills and expertise", "technical proficiencies"),
    "Experience": ("experience", "work experience", "professional experience", "employment", "employment history",
                   "work history", "career history", "relevant experience", "professional history", "career experience"),
    "Education": ("education", "education and training", "academic background", "academic history", "education and certifications"),
    "Certifications": ("certifications", "certificates", "certification", "licenses and certifications",
                       "certifications and licenses", "licenses", "professional certifications"),
}
OTHER_SECTIONS = ("projects", "selected projects", "key projects", "publications", "patents", "patent", "awards",
                  "honors", "awards and honors", "honors and awards", "achievements", "key achievements", "volunteer",
                  "volunteering", "volunteer experience", "languages", "interests", "affiliations",
                  "professional affiliations", "memberships", "professional memberships", "leadership", "training",
                  "courses", "coursework", "presentations", "speaking", "additional information", "references")
KNOWN = {name: canon for canon, names in SECTIONS.items() for name in names}


class Refused(Exception):
    """The file can't be read, with a message that says why and what to do."""


@dataclass
class Line:
    text: str
    bullet: bool = False
    heading: bool = False  # styled as a heading in a .docx


@dataclass
class Role:
    title: str
    place: str = ""
    dates: str = ""
    body: list[str] = field(default_factory=list)


@dataclass
class Employer:
    name: str
    dates: str = ""
    place: str = ""  # given once for the employer, and used by each role that names none
    roles: list[Role] = field(default_factory=list)


@dataclass
class Draft:
    text: str
    notes: list[str]
    problems: list[str]


# Reading ----------------------------------------------------------------------------------------------------------

def read_lines(path: Path) -> list[Line]:
    """The file's lines, with what its own formatting says about each one."""
    return read(path)[0]


def read(path: Path) -> tuple[list[Line], list[str]]:
    """The file's lines, and notes on anything in it that couldn't be placed or read."""
    suffix = path.suffix.lower()
    if not path.is_file():
        raise Refused(f"There's no file at {path}.")
    if suffix == ".docx":
        return _docx_lines(path)
    if suffix == ".pdf":
        return _wrapped(_pdf_text(path)), []
    if suffix in (".txt", ".md", ".text"):
        return _wrapped(_plain_text(path)), []
    if suffix == ".doc":
        raise Refused("That's an old Word .doc. Open it in Word or LibreOffice, save it as .docx, and import that.")
    raise Refused(f"Pyrite reads a .docx, a .pdf or a .txt resume, not {suffix or 'a file with no extension'}.")


def _plain_text(path: Path) -> str:
    """A text file's words, in whichever encoding its byte-order mark names, and UTF-8 otherwise.

    Notepad saves "Unicode" as UTF-16 with a mark, and can save UTF-8 with one too. Read as plain UTF-8, the first
    would be NUL bytes between the letters, and the second would put the mark in front of the name.
    """
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", "replace")
    else:
        text = raw.decode("utf-8-sig", "replace")
    if "\0" in text:
        raise Refused(f"{path.name} isn't plain text: it holds NUL characters, as UTF-16 without its byte-order mark or a "
                      "binary file does. Open it in a text editor, save it as UTF-8, and import that.")
    return text


# Word's own markup, by name: what holds text, and the places python-docx's paragraph text doesn't reach.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_FALLBACK = "{http://schemas.openxmlformats.org/markup-compatibility/2006}Fallback"
_PAGE_NUMBER = re.compile(r"^(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?$", re.I)


def _run_text(element) -> str:
    """The text of a paragraph's runs, wherever they're nested: in content controls, links, fields or tracked insertions.

    Text boxes are left out, since they're read as blocks of their own, and so is a drawing's fallback copy, which
    repeats a text box for older readers.
    """
    parts = []
    for child in element:
        tag = child.tag
        if tag in (f"{_W}txbxContent", _FALLBACK, f"{_W}del", f"{_W}pPr", f"{_W}rPr"):
            continue
        if tag == f"{_W}t":
            parts.append(child.text or "")
        elif tag == f"{_W}tab":
            parts.append("\t")
        elif tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
        elif tag == f"{_W}noBreakHyphen":
            parts.append("-")
        else:
            parts.append(_run_text(child))
    return "".join(parts)


def _text_boxes(element):
    """The text boxes anchored in a paragraph, each once."""
    for child in element:
        if child.tag == _FALLBACK:
            continue
        if child.tag == f"{_W}txbxContent":
            yield child
        else:
            yield from _text_boxes(child)


def _all_text(element) -> list[str]:
    """Every piece of text in a part, to check that nothing was missed."""
    found = []
    for child in element:
        if child.tag in (_FALLBACK, f"{_W}del"):
            continue
        if child.tag == f"{_W}t" and (child.text or "").strip():
            found.append(child.text.strip())
        else:
            found += _all_text(child)
    return found


def _docx_lines(path: Path) -> tuple[list[Line], list[str]]:
    try:
        import docx
        from docx.text.paragraph import Paragraph
    except ImportError as err:
        raise Refused("Reading a .docx needs python-docx: pip install -r tools/requirements.txt") from err
    try:
        document = docx.Document(str(path))
    except Exception as err:  # python-docx raises several kinds for a file that isn't really a .docx
        raise Refused(f"{path.name} didn't open as a Word document ({err}).") from err
    notes: list[str] = []
    boxed: list[Line] = []  # Text boxes' lines, gathered apart from the page's own flow.

    def lines_of(p) -> list[Line]:
        par = Paragraph(p, document)
        style = (par.style.name if par.style is not None else "") or ""
        ppr = p.pPr
        bullet = "List" in style or (ppr is not None and ppr.numPr is not None)
        heading = style.startswith("Heading")  # Not "Title", which is usually the name.
        return [Line(row, bullet and i == 0, heading) for i, row in enumerate(_run_text(p).split("\n"))]

    def table_lines(tbl) -> list[Line]:
        found: list[Line] = []
        for tr in tbl.iterchildren(f"{_W}tr"):
            # A merged cell is one w:tc, however many columns it spans. Its lines include any table nested in it.
            cells = [[line for line in blocks(tc) if line.text.strip()] for tc in tr.iterchildren(f"{_W}tc")]
            if all(len(lines) <= 1 for lines in cells):
                # A row laid out as fields, such as a title in one cell and its dates in the next, is one line.
                texts = [lines[0].text.strip() for lines in cells if lines]
                if texts:
                    first = next(lines[0] for lines in cells if lines)
                    found.append(Line(" | ".join(texts), first.bullet, first.heading))
            else:
                found += [line for lines in cells for line in lines]
        return found

    def blocks(element) -> list[Line]:
        """The lines of a body, a table cell, a header or a text box, in order, with whatever they nest."""
        found: list[Line] = []
        for child in element.iterchildren():
            tag = child.tag
            if tag == f"{_W}p":
                found += lines_of(child)
                for box in _text_boxes(child):
                    boxed.extend(line for line in blocks(box) if line.text.strip())
            elif tag == f"{_W}tbl":
                found += table_lines(child)
            elif tag == f"{_W}sdt":  # A content control, which Word's resume templates wrap whole sections in.
                for content in child.iterchildren(f"{_W}sdtContent"):
                    found += blocks(content)
            elif tag in (f"{_W}customXml", f"{_W}ins", f"{_W}smartTag"):
                found += blocks(child)
        return found

    def margin(kind: str) -> list[Line]:
        """The first section's header or footer lines, each once, though a first page can have its own."""
        section = document.sections[0]
        parts = [getattr(section, kind)]
        if section.different_first_page_header_footer:
            parts.append(getattr(section, f"first_page_{kind}"))
        found: list[Line] = []
        seen: set[str] = set()
        for part in parts:
            if part.is_linked_to_previous:
                continue
            for line in blocks(part._element):
                if line.text.strip() and line.text.strip() not in seen:
                    seen.add(line.text.strip())
                    found.append(line)
        return found

    margins = bool(document.sections)
    body = blocks(document.element.body)
    header = margin("header") if margins else []
    # Page numbers aren't the resume's. A contact line in the footer or a text box is as much the contact line as one
    # in the header, which reaches no parser either, so they all go at the top, where the contact line is looked for.
    # A text box's other lines, often a sidebar of skills, go after the page's own text, and the footer's after that.
    footer = [line for line in (margin("footer") if margins else []) if not _PAGE_NUMBER.match(line.text.strip())]
    aside = boxed + footer
    # Only a line with a way to reach the person counts here: "Python, Go" reads like "City, ST" on its own.
    reaches = (lambda line: any(EMAIL.fullmatch(p) or PHONE.fullmatch(p) or LINK.fullmatch(p) for p in _contact_pieces(line.text) or []))
    contact = [line for line in aside if reaches(line)]
    rest = [line for line in aside if not reaches(line)]
    found = header + contact + body + rest
    if boxed:
        notes.append(f"Read {len(boxed)} line(s) from text boxes, which sit beside the page's text rather than in it, and put "
                     "them at the end. Check they landed in the right section.")
    footnotes = [line for line in footer if line in rest]
    if footnotes:
        notes.append("Kept the page footer's other lines at the end: " + "; ".join(repr(line.text.strip()[:50]) for line in footnotes))
    # Whatever is still unread is somewhere this doesn't look. It's named, since the draft would otherwise be short of
    # it with nothing said.
    read_text = "\n".join(line.text for line in found)
    parts = [document.element.body]
    if margins:
        section = document.sections[0]
        parts += [part._element for part in (section.header, section.footer, section.first_page_header, section.first_page_footer)
                  if not part.is_linked_to_previous]
    missed = list(dict.fromkeys(piece for part in parts for piece in _all_text(part)
                                if piece not in read_text and not _PAGE_NUMBER.match(piece)))
    if missed:
        notes.append(f"Some of {path.name}'s text is somewhere this doesn't read, so it isn't in the draft. Copy it in by hand: "
                     + "; ".join(repr(piece[:50]) for piece in missed[:5]))
    return [_marked(line) for line in found if line.text.strip()], notes


def _pdf_text(path: Path) -> str:
    """The PDF's text laid out as on the page, or in reading order when the page has two columns.

    pdftotext's layout mode keeps each line whole, so a role's title and its right-aligned dates stay together and
    every bullet keeps its own line. A two-column page would come out with both columns side by side on each line,
    though, and that reads better in the default order, a column at a time.
    """
    if not shutil.which("pdftotext"):
        raise Refused("Reading a PDF needs poppler's pdftotext, which Git for Windows includes. "
                      "Or save the resume as .docx or .txt and import that.")
    text = _pdftotext(path, "-layout")
    if _two_columns(text):
        text = _pdftotext(path)
    if not text.strip():
        raise Refused(f"{path.name} has no text to read. It may be a scanned image, which needs OCR first.")
    return text


def _pdftotext(path: Path, *options: str) -> str:
    try:
        done = subprocess.run(["pdftotext", "-enc", "UTF-8", *options, str(path), "-"], capture_output=True, timeout=60, check=False,
                              creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as err:
        raise Refused(f"pdftotext took over a minute on {path.name}, so it was stopped.") from err
    if done.returncode:
        raise Refused(f"pdftotext couldn't read {path.name}: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout.decode("utf-8", "replace")


def _two_columns(text: str) -> bool:
    """Whether a layout-mode page has text side by side: many lines with a wide gap and something other than dates or
    a place after it. A role line with its dates at the right margin is still one column."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    split = 0
    for line in lines:
        gap = re.search(r"\S {4,}(\S.*)$", line)
        if gap and not DATES.search(gap[1]) and not PLACE.match(gap[1].strip()):
            split += 1
    return split >= 5 and split >= len(lines) // 4


def _marked(line: Line) -> Line:
    """The line with any bullet mark taken off, and noted."""
    text = line.text.replace(" ", " ").strip()
    mark = BULLET_MARK.match(text)
    if mark and text[mark.end():] and not DATES.match(text):
        return Line(text[mark.end():].strip(), True, line.heading)
    return Line(text, line.bullet, line.heading)


# Bullets run together on one line, as a PDF read in its plain order can give them: "Skills • Python: ... • Leadership: ...".
INLINE_BULLET = re.compile(r"\s+[•●▪■]\s+")
SENTENCE_END = (".", "!", "?", ":", ";")


def _inline_bullets(text: str) -> list[Line]:
    """A line holding several bullets, split into them. A contact line set out with bullets between short items, such as
    "City, ST • name@example.com", stays one line: only bullets that read as sentences, or that follow a section's
    name, are split off."""
    parts = INLINE_BULLET.split(text)
    if len(parts) < 2 or not (_section(parts[0]) or any(len(part.split()) >= 4 for part in parts[1:])):
        return [_marked(Line(text))]
    return [_marked(Line(parts[0]))] + [Line(part.strip(), True) for part in parts[1:] if part.strip()]


def _join(first: str, rest: str) -> str:
    """Two pieces of a wrapped line as one. A word broken at its hyphen, "AI-" then "assisted", is joined without a space."""
    if first.endswith("-") and rest[:1].islower():
        return re.sub(r"\s*-$", "-", first) + rest
    return f"{first} {rest}"


def _wrapped(text: str) -> list[Line]:
    """Lines from plain text, where a long bullet or paragraph is wrapped across several lines and has to be joined."""
    out: list[Line] = []
    after_mark = False
    for raw in text.replace("\f", "\n").splitlines():
        stripped = raw.replace(" ", " ").strip()
        if not stripped:
            if out and out[-1].text:
                out.append(Line(""))  # a paragraph break, so the next line isn't joined on
            continue
        if LONE_MARK.match(stripped):
            after_mark = True  # Some PDFs put the bullet mark on a line of its own.
            continue
        first, *more = _inline_bullets(stripped)
        line = Line(first.text, first.bullet or after_mark, first.heading)
        after_mark = False
        # A PDF laid out with space after each paragraph can put a blank line inside a wrapped bullet, before its tail:
        # a bullet that hasn't ended its sentence, then a line that starts in lower case or with a number, is still that bullet.
        if (len(out) >= 2 and not out[-1].text and out[-2].bullet and not line.bullet
                and (line.text[:1].islower() or line.text[:1].isdigit())
                and not out[-2].text.endswith(SENTENCE_END)):
            out.pop()
        prev = out[-1] if out else None
        if prev and prev.text and _continues(prev, line):
            out[-1] = Line(_join(prev.text, line.text), prev.bullet, prev.heading)
        else:
            out.append(line)
        out += more
    return [line for line in out if line.text]


def _continues(prev: Line, line: Line) -> bool:
    """Whether `line` is the rest of `prev`, wrapped."""
    if line.bullet or _section(line.text) or DATES.search(line.text) or DATES.search(prev.text):
        return False
    if _section(prev.text) or (not prev.bullet and len(prev.text) < 60):
        return False  # A short line on its own is a heading, a name or a field, not a wrapped sentence.
    if "|" in prev.text or _contact_pieces(line.text) or _contact_pieces(prev.text):
        return False  # Fields or contact details, which are laid out one line each.
    return line.text[:1].islower() or not prev.text.rstrip().endswith((".", "!", "?", ":", ";"))


# Reading the structure ---------------------------------------------------------------------------------------------

def _section(text: str, styled: bool = False, in_experience: bool = False) -> str | None:
    """The section heading this line is, in Pyrite's words where it's a common one, or None."""
    words = re.sub(r"\s+", " ", text.strip().rstrip(":").replace("&", "and")).strip()
    key = words.lower()
    if key in KNOWN:
        return KNOWN[key]
    if key in OTHER_SECTIONS:
        return words if not words.isupper() else words.capitalize()
    if not words or len(words.split()) > 5 or re.search(r"\d", words) or DATES.search(words):
        return None
    if styled or (words.isupper() and len(words) > 3 and not in_experience):
        return words.capitalize() if words.isupper() else words
    return None


def _when(text: str) -> str:
    text = text.strip().rstrip(".")
    low = text.lower()
    if low in ("present", "current", "now", "today"):
        return "Present"
    numeric = re.fullmatch(r"(\d{1,2})/(\d{4})", text)
    if numeric and 1 <= int(numeric[1]) <= 12:
        return f"{MONTHS[int(numeric[1]) - 1]} {numeric[2]}"
    named = re.fullmatch(rf"({_MONTH})\s+(\d{{4}})", text, re.I)
    if named:
        return f"{named[1][:3].capitalize()} {named[2]}"
    return text


def _dates(text: str) -> tuple[str, str]:
    """The line's date range written as "Jan 2020 – Present", and the line without it."""
    found = DATES.search(text)
    if not found:
        return "", text
    rest = (text[:found.start()] + " | " + text[found.end():])
    rest = re.sub(r"\(\s*\|\s*\)|\[\s*\|\s*\]", " | ", rest)
    return f"{_when(found['start'])}{DATE_SEP}{_when(found['end'])}", rest


def _fields(text: str) -> list[str]:
    parts = []
    for part in FIELD_SEP.split(text):
        part = part.strip(" ,;()[]")
        if not part:
            continue
        trailing = TRAILING_PLACE.search(part)
        if trailing and not PLACE.match(part):
            parts += [part[:trailing.start()].strip(" ,"), trailing["place"]]
        else:
            parts.append(part)
    return parts


COMPANY_ENDINGS = re.compile(r"^(?:inc|llc|ltd|plc|corp|co|gmbh|lp|llp|pc|sa|ag|bv)\.?$", re.I)


def _split_title(parts: list[str]) -> list[str]:
    """"Staff Engineer, Acme" and "Staff Engineer at Acme" as a title and an employer."""
    out = []
    for part in parts:
        split = re.fullmatch(r"(?P<title>.+?)(?:,\s+|\s+at\s+|\s+@\s+)(?P<org>[^,]+)", part)
        if (split and TITLE_WORD.search(split["title"]) and not TITLE_WORD.search(split["org"])
                and not PLACE.match(split["org"]) and not COMPANY_ENDINGS.match(split["org"].strip())):
            out += [split["title"].strip(), split["org"].strip()]
        else:
            out.append(part)
    return out


def _kind(part: str) -> str:
    if PLACE.match(part):
        return "place"
    return "title" if TITLE_WORD.search(part) else "org"


def _contact_pieces(text: str) -> list[str] | None:
    """The contact details in a header line, or None if it isn't a contact line."""
    pieces = [p.strip(" ,;") for p in re.split(r"\s*(?:\||\t+| {3,})\s*|\s+[•·●◦–—-]\s+|\s*[•·●]\s*", text)]
    pieces = [p for p in pieces if p]
    for piece in list(pieces):
        # "City, ST 55555 name@example.com" with no separator at all
        inner = [p for p in re.split(r"(?<![\d)])\s+(?=\S+@|\+?\(?\d{3}\)?[\s.-]\d)", piece) if p]
        if len(inner) > 1:
            at = pieces.index(piece)
            pieces[at:at + 1] = inner
    contact = [p for p in pieces if EMAIL.fullmatch(p) or PHONE.fullmatch(p) or LINK.fullmatch(p) or PLACE.match(p)]
    if not contact:
        return None
    return pieces


def _skill(text: str) -> str:
    label = re.match(r"^([^:]{2,40}):\s+(.+)$", text)
    if label and len(label[1].split()) <= 5 and not label[1].startswith("**"):
        return f"- **{label[1].strip()}:** {label[2].strip()}"
    return f"- {text}"


class _Experience:
    """Employers and roles read from an Experience section, line by line."""

    def __init__(self, notes: list[str]):
        self.employers: list[Employer] = []
        self.pending: list[str] = []  # lines that aren't bullets and have no dates, since the last role or bullet
        self.notes = notes

    @property
    def role(self) -> Role | None:
        return self.employers[-1].roles[-1] if self.employers and self.employers[-1].roles else None

    def _employer(self, name: str, dates: str = "") -> Employer:
        if self.employers and self.employers[-1].name.lower() == name.lower():
            if dates and not self.employers[-1].dates:
                self.employers[-1].dates = dates
            return self.employers[-1]
        self.employers.append(Employer(name, dates))
        return self.employers[-1]

    def _add_role(self, title: str, place: str, dates: str, source: str) -> None:
        if not self.employers:
            self.employers.append(Employer(""))
            self.notes.append(f"No employer was found for '{title}', so its ### line has none. Fill it in. ({source})")
        self.employers[-1].roles.append(Role(title, place, dates))

    def _flush_pending(self) -> None:
        """Lines that came between a role's bullets and the next role: the role's own paragraphs."""
        if self.pending and self.role:
            self.role.body += self.pending
        elif self.pending:
            for text in self.pending:
                self.notes.append(f"Kept as written, since it didn't read as an employer or a role: {text!r}")
            self._employer("").roles.append(Role("", body=list(self.pending)))
        self.pending = []

    def read(self, lines: list[Line]) -> list[str]:
        self.lines, self.at = lines, 0
        while self.at < len(lines):
            self.line(lines[self.at])
            self.at += 1
        return self.finish()

    def _employer_next(self) -> list[str] | None:
        """The next line's fields if it names an employer: "Title, dates" then "Employer | City" is a common order."""
        if self.at + 1 >= len(self.lines):
            return None
        nxt = self.lines[self.at + 1]
        if nxt.bullet or DATES.search(nxt.text) or len(nxt.text) > 70 or nxt.text.rstrip().endswith("."):
            return None
        parts = _fields(nxt.text)
        if not any(_kind(p) == "org" for p in parts):
            return None
        self.at += 1
        return parts

    def line(self, line: Line) -> None:
        if line.bullet:
            if self.pending:
                self._undated(self.pending)
                self.pending = []
            if self.role:
                self.role.body.append(f"- {line.text}")
            else:
                self.notes.append(f"A bullet came before any role, so it was kept as written: {line.text[:60]!r}")
                self._employer("").roles.append(Role("", body=[f"- {line.text}"]))
            return
        dates, rest = _dates(line.text)
        if not dates:
            self.pending.append(line.text)  # The next line settles what it is: an employer, a title or a paragraph.
            return
        self._dated(dates, _split_title(_fields(rest)), line.text)

    def _dated(self, dates: str, parts: list[str], source: str) -> None:
        pending, self.pending = self.pending, []
        before = _split_title([p for text in pending for p in _fields(text)])
        if not pending and not any(_kind(p) == "org" for p in parts) and any(_kind(p) == "title" for p in parts):
            parts += self._employer_next() or []
        place = next((p for p in parts + before if _kind(p) == "place"), "")
        here = [p for p in parts if p != place]
        earlier = [p for p in before if p != place]
        titles = [p for p in here + earlier if _kind(p) == "title"]
        orgs = [p for p in earlier + here if _kind(p) == "org"]
        if titles and orgs:
            employer = self._employer(orgs[0])
            if place and place not in parts:
                employer.place = place  # It came on the employer's own line.
            self._add_role(titles[0], place, dates, source)
            extra = [p for p in here + earlier if p not in (titles[0], orgs[0], place)]
            if extra:
                self.notes.append(f"Read {titles[0]!r} at {orgs[0]!r}; also on those lines and left out: "
                                  f"{', '.join(map(repr, extra))}. ({source})")
        elif titles:
            self._add_role(titles[0], place, dates, source)
            if len(titles) > 1:
                self.notes.append(f"Took {titles[0]!r} as the title and left out {', '.join(map(repr, titles[1:]))}. ({source})")
        elif len(orgs) >= 2:
            # Two names, neither an obvious title: "Employer" on one line and "Title, dates" on the next is the common
            # order, so the earlier one is taken as the employer.
            self._employer(orgs[0])
            self._add_role(orgs[1], place, dates, source)
            self.notes.append(f"Guessed {orgs[0]!r} is the employer and {orgs[1]!r} the title. Swap them if not. ({source})")
        elif orgs:
            # An employer with its overall dates. Its roles come on the lines after.
            self._employer(orgs[0], dates).place = place
        else:
            self.notes.append(f"Found dates but no title or employer, so the line was kept as written: {source!r}")
            if self.role:
                self.role.body.append(source)

    def _undated(self, pending: list[str]) -> None:
        """Lines with no dates right before a bullet: a role whose dates are its employer's, or a role's paragraph."""
        parts = [p for text in pending for p in _fields(text)]
        place = next((p for p in parts if _kind(p) == "place"), "")
        titles = [p for p in parts if _kind(p) == "title"]
        employer = self.employers[-1] if self.employers else None
        named = titles or [p for p in parts if p != place]
        if employer and not employer.roles and named:
            employer.roles.append(Role(named[0], place))
            return
        if self.role:
            self.role.body += pending
        else:
            for text in pending:
                self.notes.append(f"Kept as written, since it didn't read as an employer or a role: {text!r}")
            self._employer("").roles.append(Role("", body=list(pending)))

    def finish(self) -> list[str]:
        self._flush_pending()
        out: list[str] = []
        for employer in self.employers:
            if not employer.name and all(not r.title for r in employer.roles):
                for role in employer.roles:
                    out += role.body
                continue
            out.append(f"### {employer.name}" + (f" | {employer.dates}" if employer.dates else ""))
            place = employer.place
            for role in employer.roles:
                if role.title:
                    place = role.place or place
                    if not role.dates and not employer.dates:
                        self.notes.append(f"No dates were found for {role.title!r} at {employer.name!r}. Add them to its #### line.")
                    out.append(_role_line(role.title, place, role.dates))
                out += role.body
        return out


def _role_line(title: str, place: str, dates: str) -> str:
    """A `#### Title | Place | dates` line. The bar after the title stays even with no place, since the documents
    builder reads the place from the second field and the dates from the third."""
    head = f"#### {title} |" + (f" {place}" if place else "")
    return f"{head} | {dates}" if dates else head


def convert(lines: list[Line], name: str = "") -> Draft:
    """Pyrite's Markdown form of a resume, read from its lines. `name` is [candidate] name, used to find the name line."""
    notes: list[str] = []
    header: list[Line] = []
    sections: list[tuple[str, list[Line]]] = []
    for line in lines:
        title = _section(line.text, line.heading, bool(sections) and sections[-1][0] == "Experience")
        if title and (sections or header):
            sections.append((title, []))
        elif sections:
            sections[-1][1].append(line)
        else:
            header.append(line)

    out: list[str] = []
    named = next((i for i, line in enumerate(header) if name and line.text.lower().startswith(name.lower())),
                 next((i for i, line in enumerate(header) if not _contact_pieces(line.text)), 0))
    contact: list[str] = []
    headline = ""
    extra: list[str] = []
    for i, line in enumerate(header):
        if i == named:
            first, *rest = [p for p in re.split(r"\s*(?:\||\t+| {3,})\s*", line.text) if p] or [""]
            first = first.strip()
            if name and first.lower() == name.lower():
                first = name  # The name as search.toml spells it, which the assay looks for.
            elif first.isupper():
                first = first.title()
                notes.append(f"The name was in capitals, so it reads {first!r} now. Check its spelling.")
            out.append(f"# {first}")
            for piece in rest:
                pieces = _contact_pieces(piece)
                if pieces:
                    contact += pieces
                elif not headline:
                    headline = piece
                else:
                    extra.append(piece)
            continue
        pieces = _contact_pieces(line.text)
        if pieces:
            contact += pieces
        elif not headline and i > named:
            headline = line.text
        else:
            extra.append(line.text)
    if not header:
        notes.append("Nothing came before the first section heading, so there's no name or contact line. Add '# Your Name' "
                     "and an '@ ' line at the top.")
    if headline:
        out.append(f"= {headline}")
    if contact:
        places = [p for p in contact if PLACE.match(p)]
        out.append("@ " + SEPARATOR.join(places[:1] + [p for p in contact if p not in places[:1]]))
    else:
        notes.append("No email, phone or link was found near the name, so there's no '@ ' contact line. Add one.")
    if extra:
        out += extra
        notes.append(f"Kept {len(extra)} line(s) from the top as written, under the contact line: "
                     + "; ".join(repr(t[:50]) for t in extra))

    for title, body in sections:
        out += ["", f"## {title}"]
        if title == "Experience":
            out += _Experience(notes).read(body)
        elif title == "Skills":
            out += [_skill(line.text) for line in body]
        elif title == "Summary":
            out += [f"- {line.text}" if line.bullet else line.text for line in body]
        else:
            for line in body:
                entry = line.text
                if not line.bullet:
                    dates, remainder = _dates(entry)
                    entry = ", ".join(_fields(remainder) + [dates]) if dates else ", ".join(_fields(entry))
                out.append(f"- {entry}")
    text = "\n".join(out).strip() + "\n"
    return Draft(text, notes, doctor.master_problems(text, "resume", name))


def draft(path: Path, name: str = "") -> Draft:
    lines, notes = read(path)
    found = convert(lines, name)
    return Draft(found.text, notes + found.notes, found.problems)
