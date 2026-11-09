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
