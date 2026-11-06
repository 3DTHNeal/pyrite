#!/usr/bin/env python3
"""Build a resume .docx and .pdf from a small Markdown file.

Usage:
    python tools/build_resume.py applications/<folder>/resume.md --name Alex_Rivera_Resume_Acme --author "Alex Rivera"

Source syntax (one element per line):
    # Name                         name at the top
    @ contact line                 the line under the name
    ## Section                     navy heading with a rule
    ### Company | dates            bold line, dates right-aligned
    #### Role | place | dates      bold role, plain place, dates right-aligned (dates optional)
    ~ Label                        italic group label inside a role
    - bullet text                  bullet; **bold** is supported
    anything else                  plain paragraph
"""
import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from warroom.checks import _pages

FONT = "Arial"  # LibreOffice renders this with the metric-compatible Liberation Sans
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
BODY_PT = 10
CONTENT_WIDTH = Inches(7.1)


def style_run(run, size=BODY_PT, bold=False, italic=False, color=None):
    run.font.name = FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color is not None:
        run.font.color.rgb = color


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


def right_tab(par):
    par.paragraph_format.tab_stops.add_tab_stop(CONTENT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)


def build_docx(source: Path, out: Path, letter: bool = False, author: str = ""):
    paragraph_gap = 9 if letter else 1
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.5), Inches(11)
    sec.left_margin = sec.right_margin = Inches(0.7)
    sec.top_margin = Inches(0.55)
    sec.bottom_margin = Inches(0.5)

    style = doc.styles["Normal"]
    style.font.name = FONT
    style.font.size = Pt(BODY_PT)

    for raw in source.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        par = doc.add_paragraph()
        if line.startswith("#### "):
            role, place, *dates = [p.strip() for p in line[5:].split("|")]
            spacing(par, before=3, after=1)
            par.paragraph_format.keep_with_next = True
            right_tab(par)
            style_run(par.add_run(role), bold=True)
            style_run(par.add_run(f" | {place}" + (f"\t{dates[0]}" if dates else "")))
        elif line.startswith("### "):
            company, dates = [p.strip() for p in line[4:].split("|")]
            spacing(par, before=4, after=0)
            par.paragraph_format.keep_with_next = True
            right_tab(par)
            style_run(par.add_run(f"{company}\t{dates}"), bold=True)
        elif line.startswith("## "):
            spacing(par, before=7, after=2)
            par.paragraph_format.keep_with_next = True
            style_run(par.add_run(line[3:]), size=11, bold=True, color=NAVY)
            bottom_rule(par)
        elif line.startswith("# "):
            spacing(par, after=1)
            style_run(par.add_run(line[2:]), size=18, bold=True, color=NAVY)
        elif line.startswith("@ "):
            spacing(par, after=14 if letter else 2)
            style_run(par.add_run(line[2:]))
        elif line.startswith("~ "):
            spacing(par, before=2, after=0.5)
            par.paragraph_format.keep_with_next = True
            style_run(par.add_run(line[2:]), bold=True, italic=True)
        elif line.startswith("- "):
            par.style = doc.styles["List Bullet"]
            spacing(par, after=0.5)
            fmt = par.paragraph_format
            fmt.left_indent = Inches(0.17)
            fmt.first_line_indent = Inches(-0.14)
            add_rich(par, line[2:])
        else:
            spacing(par, after=paragraph_gap)
            add_rich(par, line)

    props = doc.core_properties
    props.author = author
    props.last_modified_by = author
    props.title = out.stem.replace("_", " ")
    doc.save(out)


def export_pdf(docx: Path):
    """Use LibreOffice if it's installed, otherwise Word."""
    if shutil.which("soffice"):
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(docx.parent), str(docx)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return
    # 17 is Word's PDF format, and 0 closes without saving. Paths arrive as environment variables to avoid quoting them.
    script = """
    $word = New-Object -ComObject Word.Application
    try {
        $word.DisplayAlerts = 0
        $doc = $word.Documents.Open($env:WR_DOCX, $false, $true)
        $doc.ExportAsFixedFormat($env:WR_PDF, 17)
        $doc.Close(0)
    } finally { $word.Quit() }
    """
    env = {**os.environ, "WR_DOCX": str(docx.resolve()), "WR_PDF": str(docx.resolve().with_suffix(".pdf"))}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True, env=env, stdout=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("--name", required=True, help="output file name, without extension")
    ap.add_argument("--letter", action="store_true", help="space plain paragraphs for a cover letter")
    ap.add_argument("--author", default="", help="author recorded in the document's properties")
    args = ap.parse_args()

    out_docx = args.source.parent / f"{args.name}.docx"
    build_docx(args.source, out_docx, letter=args.letter, author=args.author)
    export_pdf(out_docx)
    out_pdf = out_docx.with_suffix(".pdf")
    print(f"{out_pdf} ({_pages(out_pdf) or 'unknown'} pages)")


if __name__ == "__main__":
    main()
