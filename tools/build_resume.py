#!/usr/bin/env python3
"""Build a resume as .docx, .pdf and .txt from a small Markdown file.

Usage:
    python tools/build_resume.py applications/<folder>/resume.md --name Alex_Rivera_Resume_Acme --author "Alex Rivera"

Source syntax (one element per line):
    # Name                         name at the top
    = Headline                     optional bold line under the name: the title family you're after
    @ contact line                 the line under the name, items separated by " · " (built as " | ")
    ## Section                     heading with a rule (a real Word heading, so parsers and screen readers see it)
    ### Company | dates            the employer of the roles below it; prints nothing of its own
    #### Role | place | dates      a block of two lines: bold role with the dates right-aligned, then "Company | place"
                                   (a role without dates takes the company's)
    ~ Label                        italic group label inside a role
    - bullet text                  bullet; **bold** is supported
    anything else                  plain paragraph

The .txt is the same content as plain text, for the paste boxes on LinkedIn, Workday and the like.

Built for the parsers behind applicant tracking systems: one column, no tables, text boxes, headers or
footers, standard section names, a real bullet character in the body text rather than a Symbol-font
glyph, and dates spelled "Mar 2026". Every role is a self-contained block that names its employer, with
no employer header of its own above it: Workday read a header line that carried the employer's overall
dates as a job with no title, and the roles under it as jobs with no employer. Keep it that way. After the PDF is made, its text is read back
and the build fails if the name, contact details, a heading or a date range didn't survive, or if
the export turned "fi" into a ligature a keyword search can't match. docs/resume-playbook.md says why.

Every file carries the drafter version (pyrite.checks.DRAFTER_VERSION) in its properties, so documents
built under different rules can be told apart. The playbook's "Drafter versions" section says what
changed in each one.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036  Kept so an old Python gets a message, not a traceback.
    sys.exit("The builder needs Python 3.11 or newer, and this is {}.{}. Run it with the venv's Python: "
             "see docs/operating.md.".format(*sys.version_info[:2]))
try:
    import docx  # noqa: F401  Only to say what to install when it's missing.
except ImportError:
    sys.exit(f"The builder needs python-docx, which {sys.executable} doesn't have. Install it with:\n"
             f"  {sys.executable} -m pip install -r tools/requirements.txt")

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from pyrite.checks import DRAFTER_VERSION, _pages

FONT = "Arial"  # LibreOffice renders this with the metric-compatible Liberation Sans
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BLACK = RGBColor(0, 0, 0)
BODY_PT = 10
SIDE_MARGIN = 0.7
BULLET = "•"  # a plain bullet, which every parser reads; the Symbol-font one comes out as garbage
# Width and height in inches.
PAPER = {"letter": (8.5, 11), "a4": (8.27, 11.69)}
EXPORT_TIMEOUT_SECONDS = 120
DATE_LINE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
SEPARATOR = " · "  # in the source
BUILT_SEPARATOR = " | "  # on the page: plain ASCII, which is what the tested ATS templates use
LIGATURE = re.compile("[ﬀ-ﬆ]")


def style_run(run, size=BODY_PT, bold=False, italic=False, color=BLACK):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = color  # set outright, so a style's theme color never shows through


def spacing(par, before=0, after=0, line=1.0):
    fmt = par.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line


def add_rich(par, text, size=BODY_PT):
    """Add text to a paragraph, honouring **bold** spans."""
    for chunk in re.split(r"(\*\*.+?\*\*)", text):
        if chunk.startswith("**") and chunk.endswith("**"):
            style_run(par.add_run(chunk[2:-2]), size=size, bold=True)
        elif chunk:
            style_run(par.add_run(chunk), size=size)


def bottom_rule(par):
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for key, value in (("val", "single"), ("sz", "6"), ("space", "1"), ("color", "1F3A5F")):
        bottom.set(qn(f"w:{key}"), value)
    borders.append(bottom)
    par._p.get_or_add_pPr().append(borders)


def right_tab(par, width):
    par.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)


def _split(line: str, prefix: str) -> list[str]:
    return [p.strip() for p in line[len(prefix):].split("|")]


def _employer(line: str) -> tuple[str, str]:
    """The company and its overall dates from a `### Company | dates` line; the dates may be absent."""
    company, *dates = _split(line, "### ")
    return company, dates[0] if dates else ""


def _role(line: str, company_dates: str) -> tuple[str, str, str]:
    """Role, place and dates from a `#### Role | place | dates` line; a role without dates takes the company's."""
    role, place, *dates = _split(line, "#### ")
    return role, place, dates[0] if dates else company_dates


def _employer_line(company: str, place: str) -> str:
    return " | ".join(p for p in (company, place) if p)


def build_docx(source: Path, out: Path, letter: bool = False, author: str = "", paper: str = "letter"):
    paragraph_gap = 9 if letter else 1
    doc = Document()
    sec = doc.sections[0]
    page_width, page_height = PAPER[paper]
    sec.page_width, sec.page_height = Inches(page_width), Inches(page_height)
    sec.left_margin = sec.right_margin = Inches(SIDE_MARGIN)
    content_width = Inches(page_width - 2 * SIDE_MARGIN)
    sec.top_margin = Inches(0.55)
    sec.bottom_margin = Inches(0.5)

    for name in ("Normal", "Heading 1"):
        style = doc.styles[name]
        style.font.name = FONT
        style.font.size = Pt(BODY_PT)
        style.font.color.rgb = BLACK

    company, company_dates = "", ""
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("### "):
            # The employer prints inside each role's block, never as a header: a parser reads a header line that
            # carries dates as a job of its own, and then nests or merges the roles below it.
            company, company_dates = _employer(line)
            continue
        par = doc.add_paragraph()
        if line.startswith("#### "):
            role, place, when = _role(line, company_dates)
            spacing(par, before=5, after=0)
            par.paragraph_format.keep_with_next = True
            right_tab(par, content_width)
            style_run(par.add_run(role), bold=True)
            if when:
                style_run(par.add_run(f"\t{when}"))
            par = doc.add_paragraph()
            spacing(par, after=1)
            par.paragraph_format.keep_with_next = True
            style_run(par.add_run(_employer_line(company, place)))
        elif line.startswith("## "):
            # A real heading: it carries an outline level, which parsers and screen readers use to find sections.
            par.style = doc.styles["Heading 1"]
            spacing(par, before=7, after=2)
            par.paragraph_format.keep_with_next = True
            style_run(par.add_run(line[3:]), size=11, bold=True, color=NAVY)
            bottom_rule(par)
        elif line.startswith("# "):
            spacing(par, after=1)
            style_run(par.add_run(line[2:]), size=18, bold=True, color=NAVY)
        elif line.startswith("= "):
            # Enough space below that text extractors keep the headline and the contact line apart.
            spacing(par, after=4)
            style_run(par.add_run(line[2:]), size=11, bold=True)
        elif line.startswith("@ "):
            spacing(par, after=14 if letter else 2)
            style_run(par.add_run(line[2:].replace(SEPARATOR, BUILT_SEPARATOR)))
        elif line.startswith("~ "):
            spacing(par, before=2, after=0.5)
            par.paragraph_format.keep_with_next = True
            style_run(par.add_run(line[2:]), bold=True, italic=True)
        elif line.startswith("- "):
            # The bullet is ordinary text with a hanging indent, so it survives every extractor as "•".
            spacing(par, after=0.5)
            fmt = par.paragraph_format
            fmt.left_indent = Inches(0.17)
            fmt.first_line_indent = Inches(-0.14)
            style_run(par.add_run(f"{BULLET}\t"))
            add_rich(par, line[2:])
        else:
            spacing(par, after=paragraph_gap)
            add_rich(par, line)

    props = doc.core_properties
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    props.author = author
    props.last_modified_by = author
    props.title = out.stem.replace("_", " ")
    props.subject = "Cover letter" if letter else "Resume"
    props.comments = ""  # python-docx's template says "generated by python-docx" here
    # The drafter version rides in Keywords too, because Word carries that into the PDF's metadata and Version it doesn't.
    props.keywords = f"pyrite drafter {DRAFTER_VERSION}"
    props.version = DRAFTER_VERSION
    props.created = props.modified = now
    props.revision = 1
    doc.save(str(out))


def build_txt(source: Path, out: Path, letter: bool = False):
    """The same content as plain text, shaped for the text boxes that application sites and LinkedIn offer."""
    lines: list[str] = []
    company, company_dates = "", ""
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
        if text.startswith("#### "):
            role, place, when = _role(text, company_dates)
            lines.extend(["", f"{role} ({when})" if when else role, _employer_line(company, place)])
        elif text.startswith("### "):
            company, company_dates = _employer(text)
        elif text.startswith("## "):
            lines.extend(["", text[3:].upper()])
        elif text.startswith("# "):
            if not letter:
                lines.append(text[2:].upper())
        elif text.startswith("= "):
            if not letter:
                lines.append(text[2:])
        elif text.startswith("@ "):
            if not letter:
                lines.append(text[2:].replace(SEPARATOR, BUILT_SEPARATOR))
        elif text.startswith("~ "):
            lines.append(text[2:])
        elif text.startswith("- "):
            lines.append(f"{BULLET} {text[2:]}")
        elif letter:
            # A paste box wants the letter itself: no address block and no date.
            if not DATE_LINE.match(text):
                lines.extend([text, ""])
        else:
            lines.append(text)
    out.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def pdf_text(pdf: Path) -> str | None:
    """The PDF's text as a parser would read it, or None when poppler's pdftotext isn't installed."""
    if not shutil.which("pdftotext"):
        return None
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=True, timeout=60).stdout.decode("utf-8")


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip().lower()


def lint_pdf(source: Path, pdf: Path, letter: bool = False) -> list[str]:
    """What an applicant tracking system would fail to find in the PDF. Empty when it reads cleanly."""
    text = pdf_text(pdf)
    if text is None:
        return []
    flat = _squash(text)
    problems = []
    if LIGATURE.search(text):
        problems.append("the export turned letter pairs such as 'fi' into ligatures, which a keyword search can't match")
    # The top lines must come out as separate lines: a parser that reads "Headline City, ST" as one line loses both.
    top = [_squash(row) for row in text.splitlines() if row.strip()][:4]
    company_dates = ""
    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("# "):
            wanted = [("name", line[2:])]
        elif line.startswith("= "):
            wanted = [("headline", line[2:])]
        elif line.startswith("@ "):
            wanted = [("contact detail", part) for part in line[2:].split(SEPARATOR)]
            first = _squash(line[2:].split(SEPARATOR)[0])
            if any(first in row and len(row) > len(_squash(line[2:].replace(SEPARATOR, BUILT_SEPARATOR))) + 2 for row in top):
                problems.append("the contact line is run together with the line above it in the PDF's text")
        elif line.startswith("## ") and not letter:
            wanted = [("heading", line[3:])]
        elif line.startswith("### ") and not letter:
            # The employer's own dates reach the page only through a role that has none of its own.
            company, company_dates = _employer(line)
            wanted = [("employer", company)]
        elif line.startswith("#### ") and not letter:
            role, _, when = _role(line, company_dates)
            wanted = [("title", role)] + [("date range", when)] * ("–" in when)
        else:
            continue
        for label, item in wanted:
            if item and _squash(item) not in flat:
                problems.append(f"the {label} {item!r} isn't readable in the PDF")
    return problems


def export_pdf(docx: Path):
    export_pdfs([docx])


def export_pdfs(docxs: list[Path]):
    """Make a PDF beside each .docx, all in one session. LibreOffice if it's installed, otherwise Word.

    One session matters with Word: its first export in a process takes most of a minute (50 seconds
    measured, against a third of a second for each one after), so a resume and its letter share an
    instance. Either converter is stopped if it hangs, as Word does behind a dialog nobody can see.
    """
    docxs = [docx.resolve() for docx in docxs]
    if not docxs:
        return
    timeout = EXPORT_TIMEOUT_SECONDS + 30 * (len(docxs) - 1)
    if shutil.which("soffice"):
        for folder in dict.fromkeys(docx.parent for docx in docxs):
            subprocess.run(
                ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(folder), *(str(d) for d in docxs if d.parent == folder)],
                check=True,
                stdout=subprocess.DEVNULL,
                timeout=timeout,
            )
        return
    # 17 is Word's PDF format, and 0 closes without saving. Paths arrive in an environment variable, one per line,
    # to avoid quoting them. The ninth argument, IncludeDocProps, is off by default: without it the PDF has no
    # title, author or keywords, and so no drafter version.
    script = """
    $word = New-Object -ComObject Word.Application
    try {
        $word.DisplayAlerts = 0
        foreach ($path in $env:WR_DOCX -split "`n") {
            if (-not $path) { continue }
            $doc = $word.Documents.Open($path, $false, $true)
            $doc.ExportAsFixedFormat([System.IO.Path]::ChangeExtension($path, ".pdf"), 17, $false, 0, 0, 0, 0, 0, $true)
            $doc.Close(0)
        }
    } finally { $word.Quit() }
    """
    env = {**os.environ, "WR_DOCX": "\n".join(str(docx) for docx in docxs)}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True, env=env, stdout=subprocess.DEVNULL,
                   timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--name", required=True, help="output file name, without extension")
    ap.add_argument("--letter", action="store_true", help="space plain paragraphs for a cover letter")
    ap.add_argument("--author", default="", help="author recorded in the document's properties")
    ap.add_argument("--paper", choices=sorted(PAPER), default="letter", help="page size")
    ap.add_argument("--no-pdf", action="store_true", help="stop after the .docx and .txt")
    ap.add_argument("--letter-source", type=Path, help="also build this cover letter, through the same PDF session")
    ap.add_argument("--letter-name", help="output file name for that cover letter, without extension")
    args = ap.parse_args()
    if bool(args.letter_source) != bool(args.letter_name):
        ap.error("--letter-source and --letter-name go together")

    jobs = [(args.source, args.name, args.letter)]
    if args.letter_source:
        jobs.append((args.letter_source, args.letter_name, True))
    built = []
    for source, name, letter in jobs:
        out_docx = source.parent / f"{name}.docx"
        build_docx(source, out_docx, letter=letter, author=args.author, paper=args.paper)
        build_txt(source, out_docx.with_suffix(".txt"), letter=letter)
        built.append((source, out_docx, letter))
    if args.no_pdf:
        for _, out_docx, _ in built:
            print(f"{out_docx} (drafter {DRAFTER_VERSION})")
        return
    try:
        export_pdfs([out_docx for _, out_docx, _ in built])
    except subprocess.TimeoutExpired:
        sys.exit(f"Making the PDF took over {EXPORT_TIMEOUT_SECONDS // 60} minutes, so it was stopped. "
                 "If Word did this, open Word once and close any dialog it shows.")
    for source, out_docx, letter in built:
        out_pdf = out_docx.with_suffix(".pdf")
        problems = lint_pdf(source, out_pdf, letter=letter)
        if problems:
            sys.exit(f"{out_pdf.name} would not parse cleanly: " + "; ".join(problems) + ".")
        pages = _pages(out_pdf)
        count = "page count unknown" if not pages else f"{pages} page" if pages == 1 else f"{pages} pages"
        print(f"{out_pdf} ({count}, drafter {DRAFTER_VERSION})")


if __name__ == "__main__":
    main()
