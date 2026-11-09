"""`pyrite import-resume`: a resume someone already has, read into Pyrite's Markdown form for them to correct."""
import contextlib
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from support import CODE_ROOT

import build_resume
from pyrite import cli, profile, resumeimport, store

EXAMPLE = CODE_ROOT / "example" / "profile" / "resume.md"
HAVE_DOCX = importlib.util.find_spec("docx") is not None

# A resume laid out the way many are: capitals, a skills list with labels, an employer line above its roles, dates in
# two forms, a bullet wrapped onto a second line, and an employer whose dates and place are on its own line.
MESSY = """JORDAN LEE
Senior Software Engineer
Springfield, IL | (555) 010-0199 | jordan.lee@example.com | github.com/jlee-example

PROFESSIONAL SUMMARY
Software engineer with ten years building payment systems and the
tools around them.

TECHNICAL SKILLS
Languages: Go, Python, SQL
Cloud: AWS, Terraform

EXPERIENCE
Initech — Springfield, IL
Senior Software Engineer    Jan 2021 - Present
• Led the move of the ledger service to Go, cutting p99 latency
  from 400 ms to 90 ms.
• Mentored 3 engineers.
Software Engineer    06/2018 – 12/2020
• Built the reconciliation job.

Globex Corporation | Chicago, IL | March 2015 to May 2018
Backend Developer
• Wrote billing APIs.

EDUCATION
B.S. Computer Science, University of Illinois, 2015
"""

MESSY_MARKDOWN = """# Jordan Lee
= Senior Software Engineer
@ Springfield, IL · (555) 010-0199 · jordan.lee@example.com · github.com/jlee-example

## Summary
Software engineer with ten years building payment systems and the tools around them.

## Skills
- **Languages:** Go, Python, SQL
- **Cloud:** AWS, Terraform

## Experience
### Initech
#### Senior Software Engineer | Springfield, IL | Jan 2021 – Present
- Led the move of the ledger service to Go, cutting p99 latency from 400 ms to 90 ms.
- Mentored 3 engineers.
#### Software Engineer | Springfield, IL | Jun 2018 – Dec 2020
- Built the reconciliation job.
### Globex Corporation | Mar 2015 – May 2018
#### Backend Developer | Chicago, IL
- Wrote billing APIs.

## Education
- B.S. Computer Science, University of Illinois, 2015
"""


def headings(text: str) -> list[str]:
    """The ### employer names and #### role lines, which every draft must match word for word."""
    found = []
    for row in text.splitlines():
        if row.startswith("### "):
            found.append(row.split(" | ")[0])
        elif row.startswith(("#### ", "## ", "- ", "# ")):
            found.append(row)
    return found


class Tmp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path


class RoundTrip(Tmp):
    """The example's master, built the way Pyrite builds a resume, reads back as the same master."""

    @unittest.skipUnless(HAVE_DOCX, "python-docx isn't installed: pip install -r tools/requirements.txt")
    def test_a_built_docx_reads_back_as_its_master(self):
        build_resume.build_docx(EXAMPLE, self.dir / "r.docx")
        found = resumeimport.draft(self.dir / "r.docx", "Alex Rivera")
        self.assertEqual(headings(found.text), headings(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual((found.notes, found.problems), ([], []))

    def test_a_built_text_file_reads_back_as_its_master(self):
        build_resume.build_txt(EXAMPLE, self.dir / "r.txt")
        found = resumeimport.draft(self.dir / "r.txt", "Alex Rivera")
        self.assertEqual(headings(found.text), headings(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(found.problems, [])
        # The name is written as search.toml has it, though the text file has it in capitals.
        self.assertTrue(found.text.startswith("# Alex Rivera\n"))


class Layouts(Tmp):
    def test_a_common_layout_reads_into_the_form(self):
        found = resumeimport.draft(self.write("r.txt", MESSY))
        self.assertEqual(found.text, MESSY_MARKDOWN)
        self.assertEqual(found.problems, [])
        self.assertEqual(found.notes, ["The name was in capitals, so it reads 'Jordan Lee' now. Check its spelling."])

    def test_the_drafted_master_builds(self):
        # The builder reads place and dates by position, so a role with no place must still have its bar.
        text = resumeimport.convert([resumeimport.Line("Sam Doe"), resumeimport.Line("sam@example.com"),
                                     resumeimport.Line("Experience"), resumeimport.Line("Acme"),
                                     resumeimport.Line("Staff Engineer, 2019 - 2024"),
                                     resumeimport.Line("Shipped things.", bullet=True)]).text
        self.assertIn("#### Staff Engineer | | 2019 – 2024", text)
        source = self.write("m.md", text)
        build_resume.build_txt(source, self.dir / "m.txt")
        self.assertIn("Staff Engineer (2019 – 2024)\nAcme", (self.dir / "m.txt").read_text(encoding="utf-8"))

    def test_a_title_line_above_its_employer_line(self):
        found = resumeimport.convert([resumeimport.Line(t) for t in (
            "Sam Doe", "sam@example.com", "Experience",
            "Lead Engineer\tFeb 2020 – Present", "Umbrella Labs | Springfield, IL")]
            + [resumeimport.Line("Ran the lab.", bullet=True)])
        self.assertIn("### Umbrella Labs\n#### Lead Engineer | Springfield, IL | Feb 2020 – Present\n- Ran the lab.", found.text)

    def test_two_names_with_no_title_word_are_a_guess_it_names(self):
        found = resumeimport.convert([resumeimport.Line(t) for t in (
            "Sam Doe", "sam@example.com", "Work History", "Hooli", "Growth Hacker Extraordinaire  2019 - 2021")])
        self.assertIn("### Hooli\n#### Growth Hacker Extraordinaire | | 2019 – 2021", found.text)
        self.assertTrue(any("Guessed 'Hooli' is the employer" in note for note in found.notes))

    def test_nothing_it_cant_place_is_dropped(self):
        found = resumeimport.convert([resumeimport.Line(t) for t in (
            "Sam Doe", "sam@example.com", "Experience", "Various freelance work for small clients")]
            + [resumeimport.Line("Built websites.", bullet=True)])
        self.assertIn("Various freelance work for small clients", found.text)
        self.assertIn("- Built websites.", found.text)
        self.assertIn("no '### Employer | dates' heading", found.problems)

    def test_a_resume_with_no_contact_details_says_so(self):
        found = resumeimport.convert([resumeimport.Line(t) for t in ("Sam Doe", "Education", "B.A., 2010")])
        self.assertIn("no '@ ' contact line", found.problems)
        self.assertTrue(any("no '@ ' contact line" in note for note in found.notes))


class Files(Tmp):
    def test_a_pdf_is_read_with_pdftotext(self):
        done = subprocess.CompletedProcess([], 0, MESSY.encode("utf-8"), b"")
        with mock.patch.object(shutil, "which", return_value="pdftotext"), \
                mock.patch.object(subprocess, "run", return_value=done) as run:
            found = resumeimport.draft(self.write("r.pdf", ""))
        self.assertEqual(found.text, MESSY_MARKDOWN)
        self.assertEqual(run.call_args.args[0][:3], ["pdftotext", "-enc", "UTF-8"])

    def test_what_cant_be_read_is_refused_with_a_way_forward(self):
        empty = subprocess.CompletedProcess([], 0, b"\f\n", b"")
        cases = [
            (lambda: resumeimport.draft(self.dir / "missing.docx"), "There's no file"),
            (lambda: resumeimport.draft(self.write("r.doc", "")), "save it as .docx"),
            (lambda: resumeimport.draft(self.write("r.rtf", "")), "not .rtf"),
        ]
        for call, words in cases:
            with self.subTest(words=words), self.assertRaises(resumeimport.Refused) as caught:
                call()
            self.assertIn(words, str(caught.exception))
        with mock.patch.object(shutil, "which", return_value=None), self.assertRaises(resumeimport.Refused) as caught:
            resumeimport.draft(self.write("r.pdf", ""))
        self.assertIn("pdftotext", str(caught.exception))
        with mock.patch.object(shutil, "which", return_value="pdftotext"), \
                mock.patch.object(subprocess, "run", return_value=empty), self.assertRaises(resumeimport.Refused) as caught:
            resumeimport.draft(self.write("scan.pdf", ""))
        self.assertIn("scanned image", str(caught.exception))

    @unittest.skipUnless(HAVE_DOCX, "python-docx isn't installed: pip install -r tools/requirements.txt")
    def test_a_docx_with_list_bullets_a_table_and_a_header(self):
        import docx

        document = docx.Document()
        document.sections[0].header.is_linked_to_previous = False
        document.sections[0].header.paragraphs[0].text = "sam@example.com | (555) 010-0111"
        document.add_paragraph("Sam Doe", style="Title")
        document.add_paragraph("Experience", style="Heading 1")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Staff Engineer, Acme"
        table.cell(0, 1).text = "Jan 2020 – Present"
        document.add_paragraph("Led the platform team.", style="List Bullet")
        document.add_paragraph("Education", style="Heading 1")
        document.add_paragraph("B.S., 2010")
        document.save(str(self.dir / "r.docx"))
        found = resumeimport.draft(self.dir / "r.docx")
        self.assertEqual(found.text, "# Sam Doe\n@ sam@example.com · (555) 010-0111\n\n## Experience\n### Acme\n"
                                     "#### Staff Engineer | | Jan 2020 – Present\n- Led the platform team.\n\n"
                                     "## Education\n- B.S., 2010\n")

    @unittest.skipUnless(HAVE_DOCX, "python-docx isn't installed: pip install -r tools/requirements.txt")
    def test_text_in_content_controls_text_boxes_nested_tables_and_the_footer_is_read(self):
        import docx
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls, qn

        document = docx.Document()
        title = document.add_paragraph("Sam Doe", style="Title")
        document.sections[0].footer.is_linked_to_previous = False
        document.sections[0].footer.paragraphs[0].text = "sam@example.com | (555) 010-0111"
        document.add_paragraph("Experience", style="Heading 1")
        # Word's resume templates wrap whole sections in a content control.
        wrapped = [document.add_paragraph(text, style=style)._p for text, style in (
            ("Staff Engineer, Acme", None), ("Jan 2020 – Present", None), ("Led the platform team.", "List Bullet"))]
        control = parse_xml(f'<w:sdt {nsdecls("w")}><w:sdtPr/><w:sdtContent/></w:sdt>')
        wrapped[0].addprevious(control)
        for p in wrapped:
            control.find(qn("w:sdtContent")).append(p)
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "Ran the on-call rotation."
        table.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = "Nested: wrote the runbooks."
        # A sidebar in a text box, written twice as Word writes it: once for new readers and once as a fallback.
        box = "<w:txbxContent><w:p><w:r><w:t>Skills</w:t></w:r></w:p><w:p><w:r><w:t>Python, Go</w:t></w:r></w:p></w:txbxContent>"
        title._p.append(parse_xml(
            f'<w:r {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
            f'<mc:AlternateContent><mc:Choice Requires="wps"><w:pict><v:shape><v:textbox>{box}</v:textbox></v:shape></w:pict></mc:Choice>'
            f"<mc:Fallback><w:pict><v:shape><v:textbox>{box}</v:textbox></v:shape></w:pict></mc:Fallback></mc:AlternateContent></w:r>"))
        document.add_paragraph("Education", style="Heading 1")
        document.add_paragraph("B.S., 2010")
        document.save(str(self.dir / "r.docx"))
        found = resumeimport.draft(self.dir / "r.docx")
        self.assertTrue(found.text.startswith("# Sam Doe\n@ sam@example.com · (555) 010-0111\n"), found.text)
        self.assertIn("### Acme\n#### Staff Engineer | | Jan 2020 – Present\n- Led the platform team.\n", found.text)
        self.assertIn("Ran the on-call rotation.\nNested: wrote the runbooks.\n", found.text)
        self.assertIn("## Skills\n- Python, Go\n", found.text)
        self.assertEqual(found.text.count("Python, Go"), 1, "a text box's fallback copy isn't read twice")
        self.assertTrue(any("2 line(s) from text boxes" in note for note in found.notes), found.notes)
        self.assertFalse([note for note in found.notes if "doesn't read" in note], found.notes)

    @unittest.skipUnless(HAVE_DOCX, "python-docx isn't installed: pip install -r tools/requirements.txt")
    def test_text_somewhere_it_cant_read_is_named(self):
        import docx
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        document = docx.Document()
        document.add_paragraph("Sam Doe")
        document.add_paragraph("sam@example.com")
        # A block this doesn't know, holding a paragraph.
        document.element.body.append(parse_xml(f'<w:unknownBlock {nsdecls("w")}><w:p><w:r><w:t>Hidden award</w:t></w:r></w:p></w:unknownBlock>'))
        document.save(str(self.dir / "r.docx"))
        found = resumeimport.draft(self.dir / "r.docx")
        self.assertTrue(any("doesn't read" in note and "'Hidden award'" in note for note in found.notes), found.notes)

    def test_a_text_file_with_a_byte_order_mark_or_in_utf16_is_read(self):
        for encoding in ("utf-8-sig", "utf-16"):
            with self.subTest(encoding):
                path = self.dir / f"{encoding}.txt"
                path.write_text(MESSY, encoding=encoding)
                self.assertEqual(resumeimport.draft(path).text, MESSY_MARKDOWN)
        path = self.dir / "no-mark.txt"
        path.write_bytes(MESSY.encode("utf-16-le"))
        with self.assertRaisesRegex(resumeimport.Refused, "NUL characters"):
            resumeimport.draft(path)


# A resume as pdftotext lays out the PDF the documents builder makes: each role's dates at the right margin, the
# employer on the line under the title, a space after each paragraph that can split a wrapped bullet from its tail,
# and a word broken at its hyphen.
BUILT_LAYOUT = """Sam Doe

Staff Engineer | Platforms

Springfield, IL | (555) 010-0199 | sam.doe@example.com

Summary

Staff engineer with ten years of experience building payment systems and the AI -
assisted tools around them.

Skills

• Languages: Go, Python, SQL
• Cloud: AWS, Terraform

Experience

Staff Engineer                                                                    Jan 2021 – Present

Initech | Springfield, IL

• Led the move of the ledger service to Go, cutting p99 latency from 400 ms to

90 ms.

• Mentored 3 engineers.

Software Engineer                                                                 Jun 2018 – Dec 2020
Initech | Springfield, IL
• Built the reconciliation job.

Education
• B.S. Computer Science, University of Illinois, 2015
"""

BUILT_MARKDOWN = """# Sam Doe
= Staff Engineer | Platforms
@ Springfield, IL · (555) 010-0199 · sam.doe@example.com

## Summary
Staff engineer with ten years of experience building payment systems and the AI-assisted tools around them.

## Skills
- **Languages:** Go, Python, SQL
- **Cloud:** AWS, Terraform

## Experience
### Initech
#### Staff Engineer | Springfield, IL | Jan 2021 – Present
- Led the move of the ledger service to Go, cutting p99 latency from 400 ms to 90 ms.
- Mentored 3 engineers.
#### Software Engineer | Springfield, IL | Jun 2018 – Dec 2020
- Built the reconciliation job.

## Education
- B.S. Computer Science, University of Illinois, 2015
"""


class Pdfs(Tmp):
    """Pyrite's own PDFs read back as the masters they were built from."""

    def test_a_built_pdf_laid_out_by_pdftotext_reads_back_as_its_master(self):
        done = subprocess.CompletedProcess([], 0, BUILT_LAYOUT.encode("utf-8"), b"")
        with mock.patch.object(shutil, "which", return_value="pdftotext"), \
                mock.patch.object(subprocess, "run", return_value=done) as run:
            found = resumeimport.draft(self.write("r.pdf", ""), "Sam Doe")
        self.assertIn("-layout", run.call_args.args[0])
        self.assertEqual(found.text, BUILT_MARKDOWN)
        self.assertEqual((found.notes, found.problems), ([], []))

    def test_a_two_column_page_is_read_a_column_at_a_time(self):
        columns = "\n".join(f"Skill {n}          Led a team of {n} engineers on the platform" for n in range(8))
        calls = []

        def pdftotext(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, (columns if "-layout" in cmd else MESSY).encode("utf-8"), b"")

        with mock.patch.object(shutil, "which", return_value="pdftotext"), mock.patch.object(subprocess, "run", side_effect=pdftotext):
            found = resumeimport.draft(self.write("r.pdf", ""))
        self.assertEqual(found.text, MESSY_MARKDOWN)
        self.assertEqual(len(calls), 2)

    def test_bullets_run_together_on_one_line_are_split(self):
        lines = resumeimport._wrapped("Skills • Languages: Go, Python and SQL • Cloud: AWS and Terraform for everything\n"
                                      "Certifications • Certified ScrumMaster\n"
                                      "Springfield, IL • sam@example.com • (555) 010-0199\n")
        self.assertEqual([(line.text, line.bullet) for line in lines],
                         [("Skills", False), ("Languages: Go, Python and SQL", True), ("Cloud: AWS and Terraform for everything", True),
                          ("Certifications", False), ("Certified ScrumMaster", True),
                          ("Springfield, IL • sam@example.com • (555) 010-0199", False)])

    @unittest.skipUnless(shutil.which("pdftotext"), "needs poppler's pdftotext")
    def test_the_example_pdf_reads_back_as_its_master(self):
        folder = CODE_ROOT / "example" / "applications" / "2026-11-acme-principal-robotics-software-engineer"
        found = resumeimport.draft(folder / "Alex_Rivera_Resume_Acme_Robotics.pdf", "Alex Rivera")
        self.assertEqual(headings(found.text), headings((folder / "resume.md").read_text(encoding="utf-8")))
        self.assertEqual((found.notes, found.problems), ([], []))

    @unittest.skipUnless(HAVE_DOCX and shutil.which("pdftotext") and shutil.which("soffice"),
                         "needs python-docx, pdftotext and LibreOffice to build a PDF")
    def test_a_pdf_built_now_reads_back_as_its_master(self):
        build_resume.build_docx(EXAMPLE, self.dir / "r.docx")
        build_resume.export_pdfs([self.dir / "r.docx"])
        found = resumeimport.draft(self.dir / "r.pdf", "Alex Rivera")
        self.assertEqual(headings(found.text), headings(EXAMPLE.read_text(encoding="utf-8")))
        self.assertEqual(found.problems, [])


class Command(Tmp):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            cli.main(["import-resume", *argv])
        return out.getvalue(), err.getvalue()

    def test_it_prints_the_draft_and_says_what_to_check(self):
        out, err = self.run_cli(str(self.write("r.txt", MESSY)))
        self.assertEqual(out, MESSY_MARKDOWN)
        self.assertIn("Check: The name was in capitals", err)
        self.assertIn("profile/facts.md", err)

    def test_save_writes_the_master_and_keeps_the_old_one(self):
        root = self.dir / "ws"
        shutil.copytree(CODE_ROOT / "example" / "profile", root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        before = profile.read("resume")
        out, _ = self.run_cli(str(self.write("r.txt", MESSY)), "--save")
        self.assertEqual(profile.read("resume"), MESSY_MARKDOWN)
        self.assertIn("Put back restores it", out)
        last = profile.history()[0]
        self.assertEqual((last["key"], last["reason"], last["step"]), ("resume", "Imported from r.txt", "masters"))
        self.assertEqual(profile.kept("resume", last["stamp"]), before)

    def test_save_is_refused_without_a_workspace(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), self.assertRaises(SystemExit) as caught:
            self.run_cli(str(self.write("r.txt", MESSY)), "--save")
        self.assertIn("fictional example", str(caught.exception.code))


if __name__ == "__main__":
    unittest.main()
