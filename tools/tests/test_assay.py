"""The assay: the fact checker, the document builder and the interview-brief check."""
import contextlib
import importlib.util
import io
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path

from support import BAD_DRAFT, BRIEF, CFG, CONFIDENTIAL, LETTER, LETTER_ROLE, MODEL, RESUME, SOURCES, resume_errors

from assay import factbank, links, names, terms
from assay import numbers as number_checks
from assay import text as reading
from pyrite import checks, store

MASTER = (store.ROOT / "profile" / "resume.md").read_text(encoding="utf-8")

class FactChecker(unittest.TestCase):
    def test_reviewed_documents_pass(self):
        self.assertEqual(resume_errors(RESUME), [])
        errors, _ = checks.check_text(LETTER, "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertEqual(errors, [])
        self.assertEqual(checks.check_resume_structure(RESUME, CFG)[0], [])

    def test_deliberately_bad_draft_is_blocked_for_every_reason(self):
        report = checks.check_application(BAD_DRAFT, CFG, "Globex Automation", "Staff Firmware Engineer")
        self.assertFalse(report["ok"])
        found = " ".join(report["errors"])
        for reason in ("confidential term", "unsupported claim", "not in the fact bank", "differ from your record",
                       "link or domain", "unfilled placeholder", "not in your approved sources"):
            with self.subTest(reason):
                self.assertIn(reason, found)

    def test_page_count_works_without_poppler(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            two_pages = Path(folder) / "two.pdf"
            two_pages.write_bytes(b"%PDF-1.7\n1 0 obj <</Type /Page>> endobj\n2 0 obj <</Type /Page>> endobj\n3 0 obj <</Type /Pages>> endobj\n")
            with mock.patch("pyrite.checks.subprocess.run", side_effect=FileNotFoundError):
                self.assertEqual(checks._pages(two_pages), 2)
                self.assertEqual(checks._pages(MODEL / "Alex_Rivera_Cover_Letter_Acme_Robotics.pdf"), 1)

    def test_confidential_names_blocked(self):
        for term in ("Bluebird", "Falconer", "the hive", "SkyLift 900", "bluebird"):
            with self.subTest(term):
                errors = resume_errors(RESUME + f"\n- Built {term} tooling.\n")
                self.assertTrue(any("confidential term" in e for e in errors), errors)

    def test_a_name_listed_only_under_do_not_use_is_blocked_by_name(self):
        facts = (store.ROOT / "profile" / "facts.md").read_text(encoding="utf-8")
        listed = facts.replace("## Do not use\n", "## Do not use\n- Codename Nightjar (an internal name)\n")
        self.assertFalse(any(re.search(pattern, "Nightjar", re.I) for pattern in CFG["guard"]["forbidden"]))  # No pattern of its own.

        def read(text):
            return lambda rel: text if rel == "profile/facts.md" else (store.ROOT / rel).read_text(encoding="utf-8")

        blocked = checks.blocked_patterns(CFG, read(listed))
        errors, _ = checks.check_text(RESUME + "\n- Shipped nightjars on time.\n", "resume", CFG, SOURCES, "Acme", "Principal Engineer",
                                      blocked=blocked)
        self.assertIn("Resume uses a confidential term: 'nightjars', which profile/facts.md lists under \"Do not use\"", errors)
        # The rest of the draft is judged as before: the name isn't named again as a term outside your sources.
        self.assertFalse([e for e in errors if "not in your approved sources" in e], errors)
        # A name your sources also state as fact can't be blocked by name, or every draft that states it would fail.
        stated = listed.replace("## Leadership\n", "## Leadership\n- Ran the Nightjar launch\n")
        self.assertEqual(checks.listed_terms(CFG, read(stated)), ([], [("Nightjar", "profile/facts.md")]))

    def test_comments_in_a_source_approve_nothing(self):
        text = "# Fact bank\n<!-- Tools such as Kubernetes, and numbers such as 2026. -->\n## Skills\n- Python\n"
        self.assertNotIn("Kubernetes", factbank.claimable(text))
        self.assertNotIn("2026", factbank.claimable(text))
        self.assertIn("- Python", factbank.claimable(text))

    def test_a_placeholder_is_named_once_not_again_as_a_term(self):
        errors = resume_errors(RESUME + "\n- Led a [X] migration.\n")
        self.assertTrue(any("unfilled placeholder: '[X]'" in e for e in errors), errors)
        self.assertFalse([e for e in errors if "not in your approved sources" in e], errors)
        # A bracket opened on one line and closed on another isn't a placeholder, so nothing between is set aside.
        errors = resume_errors(RESUME + "\n- Led a [migration of\n- the fleet to Kubernetes].\n")
        self.assertTrue(any("not in your approved sources: Kubernetes" in e for e in errors), errors)

    def test_archive_is_not_hive(self):
        self.assertEqual(resume_errors(RESUME + "\n- Moved old logs to an archive.\n"), [])

    def test_invented_numbers_blocked(self):
        self.assertTrue(any("not in the fact bank" in e for e in resume_errors(RESUME + "\n- Cut defects by 83%.\n")))
        self.assertTrue(any("not in the fact bank" in e for e in resume_errors(RESUME + "\n- Led a team of 137 engineers.\n")))

    def test_unsupported_claim_blocked_but_honest_disclaimer_allowed(self):
        self.assertTrue(any("unsupported claim" in e for e in resume_errors(RESUME + "\n- Led ISO 26262 certification for the fleet.\n")))
        self.assertTrue(any("unsupported claim" in e for e in resume_errors(RESUME + "\n- Validated by replaying field failures from robots.\n")))
        self.assertEqual(resume_errors(RESUME + "\n- I have not worked under ISO 26262.\n"), [])

    def test_invented_skill_blocked_on_resume_but_only_warned_in_letter(self):
        self.assertTrue(any("Kubernetes" in e for e in resume_errors(RESUME + "\n- Ran services on AWS and Kubernetes.\n")))
        errors, warnings = checks.check_text(LETTER + "\nI admire your Kubernetes work.\n", "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertEqual(errors, [])
        self.assertTrue(any("Kubernetes" in w for w in warnings))

    def test_injected_links_and_placeholders_blocked(self):
        self.assertTrue(resume_errors(RESUME + "\n- See evil-site.com for details.\n"))
        self.assertTrue(resume_errors(RESUME + "\n- Delivered [x%] improvement.\n"))

    def test_changed_contact_line_blocked(self):
        self.assertTrue(resume_errors(RESUME.replace("(555) 010-0142", "(555) 123-4567")))

    def test_wrong_name_blocked(self):
        self.assertTrue(any("doesn't open with" in e for e in resume_errors(RESUME.replace("# Alex Rivera", "# Someone Else"))))

    def test_rewritten_job_history_blocked(self):
        changed = RESUME.replace("#### Principal Firmware Engineer | Madison, WI | Jan 2023 – Oct 2026",
                                 "#### VP of Engineering | Madison, WI | Jan 2015 – Oct 2026")
        self.assertTrue(checks.check_resume_structure(changed, CFG)[0])

    def test_expected_item_missing_is_a_warning_not_an_error(self):
        errors, warnings = checks.check_resume_structure(RESUME.replace("University of Wisconsin", "A University"), CFG)
        self.assertEqual(errors, [])
        self.assertTrue(any("Degree isn't on this resume" in w for w in warnings))

    def test_wording_that_reads_as_machine_written_is_warned_not_blocked(self):
        draft = RESUME + "\n- Spearheaded a results-driven effort — leveraged synergies.\n"
        errors, warnings = checks.check_text(draft, "resume", CFG, SOURCES, "Acme", "Principal Engineer")
        self.assertEqual(errors, [])
        self.assertTrue(any("em dash" in w for w in warnings), warnings)
        self.assertTrue(any("spearheaded" in w and "leveraged" in w and "results-driven" in w for w in warnings), warnings)
        _, warnings = checks.check_text(RESUME, "resume", CFG, SOURCES, "Acme", "Principal Engineer")
        self.assertEqual(warnings, [])

    def test_long_letter_is_warned(self):
        padding = "\n" + " ".join(["I built the bench and ran it on every merge."] * 40) + "\n"
        _, warnings = checks.check_text(LETTER + padding, "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertTrue(any("words" in w and "350" in w for w in warnings), warnings)
        _, warnings = checks.check_text(LETTER, "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertFalse(any("words" in w for w in warnings), warnings)

    def test_polish_requests_pick_what_a_rewrite_can_clear(self):
        report = {"warnings": ["Cover letter names terms not in your approved sources: Ocean, Nodes",
                               "Resume uses an em dash, which readers now take as a sign of unedited AI text.",
                               "old.docx was built by drafter 1; the current drafter is 2."],
                  "overlap": {"pct": 100, "covered": ["embedded", "firmware", "simulation", "controls", "calibration"], "missing": []}}
        asks = checks.polish_requests(report)
        self.assertEqual(len(asks), 3, asks)
        self.assertTrue(any("100%" in a and "60 to 80%" in a and "firmware" in a for a in asks), asks)
        self.assertFalse(any("drafter" in a for a in asks))
        # A refresh can't touch the letter, so its warnings aren't asked of it.
        self.assertEqual(len(checks.polish_requests(report, letter=False)), 2)
        # Every one of two terms is no sign of copying, and 70% of many is the target.
        few = {"warnings": [], "overlap": {"pct": 100, "covered": ["embedded", "firmware"], "missing": []}}
        self.assertEqual(checks.polish_requests(few), [])
        fine = {"warnings": [], "overlap": {"pct": 70, "covered": ["a"] * 7, "missing": ["b"] * 3}}
        self.assertEqual(checks.polish_requests(fine), [])

    def test_letter_date_can_be_any_day(self):
        errors, _ = checks.check_text(LETTER.replace("November 2, 2026", "December 17, 2026"), "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertEqual(errors, [])

    def test_only_the_approved_contact_line_is_exempt(self):
        extra = RESUME.replace("\n## Summary", "\n@ Managed 500 engineers on Kubernetes, see evil-site.com\n\n## Summary", 1)
        errors = resume_errors(extra)
        for reason in ("link or domain", "numbers not in the fact bank: 500", "Kubernetes"):
            with self.subTest(reason):
                self.assertTrue(any(reason in e for e in errors), errors)

    def test_indented_heading_is_still_a_heading(self):
        changed = RESUME.replace("## Experience", "## Experience\n  #### Director of Engineering | Madison, WI | Jan 2023 – Oct 2026", 1)
        self.assertTrue(any("differ from your record" in e for e in checks.check_resume_structure(changed, CFG)[0]))

    def test_a_negative_after_the_claim_denies_nothing(self):
        for line in ("- Led ISO 26262 safety certification with no delays.", "- Achieved safety certification without rework.",
                     "- Not only led ISO 26262 certification, also audited it."):
            with self.subTest(line):
                self.assertTrue(any("unsupported claim" in e for e in resume_errors(RESUME + f"\n{line}\n")))
        for line in ("- I have not yet worked under ISO 26262.", "- The posting asks for safety certification, and I have not done it."):
            with self.subTest(line):
                self.assertEqual(resume_errors(RESUME + f"\n{line}\n"), [])

    def test_do_not_use_and_unsupported_sections_approve_nothing(self):
        self.assertNotIn("skylift", terms.vocabulary(SOURCES))
        self.assertIn("firmware", terms.vocabulary(SOURCES))
        self.assertTrue(any("900" in e for e in resume_errors(RESUME + "\n- Shipped firmware to 900 robots.\n")))

    def test_spelled_out_numbers_blocked(self):
        errors = resume_errors(RESUME + "\n- Managed a team of forty engineers.\n")
        self.assertTrue(any("spells out numbers" in e and "forty" in e for e in errors), errors)

    def test_a_title_from_the_job_board_approves_no_skills(self):
        errors, _ = checks.check_text(RESUME + "\n- Deep experience with Kubernetes and Terraform.\n", "resume", CFG, SOURCES,
                                      "Acme", "Staff Engineer, Kubernetes and Terraform")
        self.assertTrue(any("Kubernetes, Terraform" in e for e in errors), errors)

    def test_invented_skill_that_opens_a_bullet_is_blocked(self):
        self.assertTrue(any("FreeBSD" in e for e in resume_errors(RESUME + "\n- FreeBSD kernel work for the fleet.\n")))
        posting = "We run everything on Kubernetes and Terraform. You will lead the 3D Gives Back program."
        draft = RESUME + "\n- Kubernetes cluster administration for the fleet.\n- Came back to firmware after that.\n"
        errors, _ = checks.check_text(draft, "resume", CFG, SOURCES, "Acme", "Principal Engineer", posting=posting)
        repeated = [e for e in errors if "repeats terms from the posting" in e]
        self.assertEqual(len(repeated), 1, errors)
        self.assertIn("sources: Kubernetes. Remove", repeated[0])

    def test_a_folder_is_checked_against_its_saved_posting(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            folder = Path(folder)
            (folder / "resume.md").write_text(RESUME + "\n- Kubernetes cluster administration for the fleet.\n", encoding="utf-8")
            (folder / "posting.md").write_text("# Acme: Role\n\n- **Link:** \n- **Location:** \n- **Saved:** 2026-11-02\n\nWe run on Kubernetes.\n", encoding="utf-8")
            report = checks.check_application(folder, CFG, "Acme", "Role")
            self.assertTrue(any("Kubernetes" in e for e in report["errors"]), report["errors"])


class Requisition(unittest.TestCase):
    """A cover letter may cite the job's own requisition number, which measures nothing. It was the most common false
    alarm on numbers. A resume may not, and nothing else in a letter is let through by it."""

    WORKDAY = ("workday:acme", "/job/United-States---Remote/Lead-Software-Engineer---Embedded_REQ-14879-1")
    OPENING = "I am applying for the Principal Robotics Software Engineer role at Acme Robotics."

    def letter_errors(self, sentence, requisition):
        letter = LETTER.replace(self.OPENING, f"{self.OPENING} {sentence}")
        self.assertNotEqual(letter, LETTER)
        return checks.check_text(letter, "letter", CFG, SOURCES, *LETTER_ROLE, requisition=requisition)[0]

    def test_the_job_names_its_requisition(self):
        self.assertEqual(checks.requisitions("", *self.WORKDAY), ["REQ-14879-1", "REQ-14879"])
        self.assertEqual(checks.requisitions("", "workday:acme", "/job/Remote-CT/Program-Manager_JR2026528875"), ["JR2026528875"])
        self.assertEqual(checks.requisitions("", "greenhouse:acme", "5786075004"), ["5786075004"])
        # Pyrite makes up the id of a job you add by hand, so no one would cite it.
        self.assertEqual(checks.requisitions("", "manual:acme", "90140f979c794596"), [])
        posting = ("About the role\nRequisition ID: R-0145\nJob ID JR77001\nReq #: 5123\nJob no. 1 of 3\n"
                   "We hire 2500 people a year.")
        self.assertEqual(checks.requisitions(posting), ["JR77001", "R-0145", "5123"])

    def test_a_letter_may_cite_it(self):
        # A number glued to letters, such as JR2026528875, was never read as a number. One set apart from them was.
        idents = checks.requisitions("", *self.WORKDAY)
        for sentence in ("The requisition is REQ-14879.", "I'm applying to requisition REQ-14879-1.", "(Req #req-14879)"):
            with self.subTest(sentence):
                self.assertEqual(self.letter_errors(sentence, idents), [])
                self.assertTrue(self.letter_errors(sentence, []), "without the job's requisition it's a number from nowhere")
        idents = checks.requisitions("", "greenhouse:acme", "5786075004")
        for sentence in ("Job ID 5786075004.", "I saw the posting, 5786075004, on your site."):
            with self.subTest(sentence):
                self.assertEqual(self.letter_errors(sentence, idents), [])
                self.assertTrue(self.letter_errors(sentence, []))

    def test_its_digits_alone_only_where_a_label_says_what_they_are(self):
        idents = ["REQ-14879"]
        self.assertEqual(self.letter_errors("This is for requisition 14879.", idents), [])
        self.assertEqual(self.letter_errors("This is for Job ID: 14879.", idents), [])
        errors = self.letter_errors("I ran 14879 tests a night.", idents)
        self.assertTrue(any("14879" in e for e in errors), errors)

    def test_it_approves_nothing_else(self):
        errors = self.letter_errors("The requisition is REQ-14879, and I cut defects by 91%.", ["REQ-14879"])
        self.assertTrue(any("91%" in e for e in errors), errors)
        self.assertEqual(len(errors), 1, errors)

    def test_a_resume_may_not_cite_it(self):
        resume = RESUME.replace("## Experience", "Requisition REQ-14879\n\n## Experience", 1)
        self.assertNotEqual(resume, RESUME)
        errors, _ = checks.check_text(resume, "resume", CFG, SOURCES, "Acme", "Principal Engineer", requisition=["REQ-14879"])
        self.assertTrue(any("14879" in e for e in errors), errors)

    def test_a_folders_posting_names_it(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp) / "app"
            shutil.copytree(MODEL, folder)
            letter = (folder / "cover-letter.md").read_text(encoding="utf-8").replace(self.OPENING, f"{self.OPENING} Requisition R-0145.")
            (folder / "cover-letter.md").write_text(letter, encoding="utf-8")
            report = checks.check_application(folder, CFG, *LETTER_ROLE, "Requisition ID: R-0145\nBuild motor control.")
            self.assertFalse(any("145" in e for e in report["errors"]), report["errors"])
            report = checks.check_application(folder, CFG, *LETTER_ROLE, "Build motor control.")
            self.assertTrue(any("145" in e for e in report["errors"]), report["errors"])


@unittest.skipUnless(importlib.util.find_spec("docx"), "python-docx isn't installed: pip install -r tools/requirements.txt")
class Builder(unittest.TestCase):
    """The documents a parser sees: plain text for paste boxes, and a PDF read back the way an ATS reads it."""

    def setUp(self):
        import build_resume
        self.build = build_resume
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.folder = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_plain_text_keeps_the_content_and_drops_the_markup(self):
        out = self.folder / "resume.txt"
        self.build.build_txt(MODEL / "resume.md", out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("ALEX RIVERA\nPrincipal Firmware Engineer | Motor Control", text)
        self.assertIn("Madison, WI | (555) 010-0142 | alex.rivera@example.com", text)
        self.assertIn("\nSKILLS\n• Firmware: C++", text)
        # Each role is its own block naming the employer; the employer's overall dates never print on their own.
        self.assertIn("\n\nPrincipal Firmware Engineer (Jan 2023 – Oct 2026)\nNorthbridge Robotics | Madison, WI\n", text)
        self.assertIn("\n\nSenior Firmware Engineer (Jun 2017 – Mar 2020)\nNorthbridge Robotics | Madison, WI\n", text)
        self.assertNotIn("Northbridge Robotics (", text)
        self.assertNotIn("**", text)
        self.assertNotIn("#", text)

    def test_plain_text_letter_is_only_the_letter(self):
        out = self.folder / "letter.txt"
        self.build.build_txt(MODEL / "cover-letter.md", out, letter=True)
        text = out.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Dear Hiring Manager,\n\nI am applying"), text[:60])
        self.assertNotIn("November 2, 2026", text)
        self.assertNotIn("alex.rivera@example.com", text)
        self.assertTrue(text.rstrip().endswith("Alex Rivera"))

    def test_a_byte_order_mark_other_bullets_and_notes_build_as_plain_text(self):
        source = self.folder / "resume.md"
        source.write_text("﻿# Sam Doe\n@ sam@example.com\n<!-- a note to self\n## Not a heading -->\n## Experience\n### Acme\n"
                          "#### Staff Engineer\n* Led the team. <!-- check this -->\n+ Shipped things.\n", encoding="utf-8")
        self.build.build_txt(source, self.folder / "r.txt")
        self.assertEqual((self.folder / "r.txt").read_text(encoding="utf-8"),
                         "SAM DOE\nsam@example.com\n\nEXPERIENCE\n\nStaff Engineer\nAcme\n• Led the team.\n• Shipped things.\n")
        self.build.build_docx(source, self.folder / "r.docx")
        import docx
        paragraphs = [p.text for p in docx.Document(str(self.folder / "r.docx")).paragraphs]
        self.assertEqual(paragraphs[0], "Sam Doe", "the mark isn't part of the name, and the name is a name")
        self.assertIn("•\tLed the team.", paragraphs)
        self.assertFalse([p for p in paragraphs if "<!--" in p or "Not a heading" in p], paragraphs)

    def test_a_role_line_with_a_fourth_part_is_refused_by_name(self):
        source = self.folder / "resume.md"
        source.write_text("# Sam Doe\n## Experience\n### Acme\n#### Staff Engineer | Remote | 2019 – 2024 | extra\n- Led.\n",
                          encoding="utf-8")
        argv = ["build_resume", str(source), "--name", "R", "--no-pdf"]
        with mock.patch.object(sys, "argv", argv), self.assertRaises(SystemExit) as caught:
            self.build.main()
        self.assertIn("at most three parts", str(caught.exception.code))
        self.assertIn("resume.md", str(caught.exception.code))

    def test_docx_has_real_bullets_headings_and_fresh_metadata(self):
        import zipfile
        out = self.folder / "resume.docx"
        self.build.build_docx(MODEL / "resume.md", out, author="Alex Rivera")
        with zipfile.ZipFile(out) as z:
            document = z.read("word/document.xml").decode("utf-8")
            core = z.read("docProps/core.xml").decode("utf-8")
        self.assertIn("•", document)
        self.assertNotIn("ListBullet", document)
        self.assertEqual(document.count('w:val="Heading1"'), 5)
        self.assertIn("Motor Control, Simulation and AI-Assisted Development", document)
        self.assertIn("Madison, WI | (555) 010-0142", document)
        # No employer header above the roles: Workday read one as a job without a title. The employer sits in each block.
        self.assertNotIn("Jun 2017 – Oct 2026", document)
        self.assertEqual(document.count("Northbridge Robotics | Madison, WI"), 3)
        for tag in ("<w:tbl>", "<w:txbxContent>", "w:headerReference", "w:footerReference"):
            self.assertNotIn(tag, document)
        self.assertNotIn("python-docx", core)
        self.assertIn("<dc:creator>Alex Rivera</dc:creator>", core)
        self.assertIn(f"<cp:version>{checks.DRAFTER_VERSION}</cp:version>", core)
        self.assertIn(f"<cp:keywords>pyrite drafter {checks.DRAFTER_VERSION}</cp:keywords>", core)
        # The stamp is in UTC, which is already tomorrow during a US evening.
        self.assertIn(f"<dcterms:created xsi:type=\"dcterms:W3CDTF\">{datetime.now(UTC).date().isoformat()}", core)
        self.assertEqual(checks.drafter_versions(self.folder), {"resume.docx": checks.DRAFTER_VERSION})

    def test_files_from_an_older_drafter_are_named(self):
        import zipfile
        old = self.folder / "old.docx"
        self.build.build_docx(MODEL / "resume.md", old, author="Alex Rivera")
        with zipfile.ZipFile(old) as z:
            parts = {name: z.read(name) for name in z.namelist()}
        parts["docProps/core.xml"] = re.sub(rb"<cp:version>[^<]*</cp:version>", b"", parts["docProps/core.xml"])
        with zipfile.ZipFile(old, "w") as z:
            for name, data in parts.items():
                z.writestr(name, data)
        self.assertEqual(checks.drafter_versions(self.folder), {"old.docx": "1"})
        shutil.copy(MODEL / "resume.md", self.folder / "resume.md")
        report = checks.check_application(self.folder, CFG, "Acme Robotics", "Principal Robotics Software Engineer")
        self.assertEqual(report["drafter"], {"old.docx": "1"})
        self.assertTrue(any("old.docx was built by drafter 1" in w for w in report["warnings"]), report["warnings"])

    def test_pdf_lint_reports_what_a_parser_would_miss(self):
        pdf = self.folder / "resume.pdf"
        pdf.write_bytes(b"%PDF-1.7\n")
        self.build.build_txt(MODEL / "resume.md", self.folder / "clean.txt")
        clean = (self.folder / "clean.txt").read_text(encoding="utf-8")
        with mock.patch.object(self.build, "pdf_text", return_value=clean):
            self.assertEqual(self.build.lint_pdf(MODEL / "resume.md", pdf), [])
        broken = clean.replace("(555) 010-0142", "[NULL]").replace("Jan 2023 – Oct 2026", "").replace("firmware", "ﬁrmware")
        with mock.patch.object(self.build, "pdf_text", return_value=broken):
            problems = self.build.lint_pdf(MODEL / "resume.md", pdf)
        found = " ".join(problems)
        self.assertIn("ligatures", found)
        self.assertIn("'(555) 010-0142'", found)
        self.assertIn("'Jan 2023 – Oct 2026'", found)
        self.assertNotIn("Alex Rivera", found)
        with mock.patch.object(self.build, "pdf_text", return_value=None):
            self.assertEqual(self.build.lint_pdf(MODEL / "resume.md", pdf), [])

    def test_a_resume_and_its_letter_are_built_together_and_exported_in_one_session(self):
        shutil.copy(MODEL / "resume.md", self.folder / "resume.md")
        shutil.copy(MODEL / "cover-letter.md", self.folder / "cover-letter.md")
        argv = ["build_resume", str(self.folder / "resume.md"), "--name", "R", "--letter-source", str(self.folder / "cover-letter.md"),
                "--letter-name", "L", "--no-pdf"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()) as out:
            self.build.main()
        self.assertIn("R.docx (drafter", out.getvalue())
        for name in ("R.docx", "R.txt", "L.docx", "L.txt"):
            self.assertTrue((self.folder / name).exists(), name)
        self.assertTrue((self.folder / "L.txt").read_text(encoding="utf-8").startswith("Dear Hiring Manager"))
        # Without LibreOffice, Word gets both documents in one script: its first export in a process is the slow one.
        with mock.patch.object(self.build.shutil, "which", return_value=None), mock.patch.object(self.build.subprocess, "run") as run:
            self.build.export_pdfs([self.folder / "R.docx", self.folder / "L.docx"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][0], "powershell")
        # Started from the dashboard, which has no console, PowerShell would otherwise open a window for as long as Word takes.
        self.assertEqual(run.call_args.kwargs["creationflags"], self.build.NO_WINDOW)
        self.assertEqual(run.call_args.kwargs["env"]["WR_DOCX"].split("\n"),
                         [str((self.folder / "R.docx").resolve()), str((self.folder / "L.docx").resolve())])


class BriefChecker(unittest.TestCase):
    def check(self, extra, posting=""):
        return checks.check_brief(BRIEF + extra, CFG, SOURCES, "Acme", "Staff Firmware Engineer", posting)

    def test_plain_brief_passes(self):
        self.assertEqual(self.check(""), ([], []))

    def test_confidential_names_and_unsupported_claims_blocked(self):
        self.assertTrue(any("confidential term" in e for e in self.check(f"\n- Bring up {CONFIDENTIAL}.\n")[0]))
        self.assertTrue(any("unsupported claim" in e for e in self.check("\n- Say you led ISO 26262 certification.\n")[0]))
        self.assertEqual(self.check("\n- Say plainly: I have not worked under ISO 26262.\n", "ISO 26262 experience")[0], [])

    def test_numbers_must_come_from_the_fact_bank_or_the_posting(self):
        self.assertTrue(any("numbers" in e for e in self.check("\n- They ask for 11 years of firmware.\n")[0]))
        self.assertEqual(self.check("\n- They ask for 11 years of firmware.\n", "11 years of firmware experience")[0], [])
        self.assertTrue(any("percentages" in e for e in self.check("\n- Say you cut defects by 83%.\n", "11 years")[0]))

    def test_links_and_placeholders_blocked(self):
        self.assertTrue(any("link" in e for e in self.check("\n- Finish applying at evil-site.com first.\n", "Apply at evil-site.com")[0]))
        self.assertTrue(any("placeholder" in e for e in self.check("\n- Ask about [team name].\n")[0]))

    def test_a_term_from_the_posting_alone_is_flagged_as_a_gap(self):
        errors, warnings = self.check("\n- They want Kubernetes, which you haven't used.\n", "Runs on Kubernetes.")
        self.assertEqual(errors, [])
        self.assertTrue(any("Kubernetes" in w and "gaps" in w for w in warnings))
        _, warnings = self.check("\n- They want Kubernetes, which you haven't used.\n")
        self.assertTrue(any("Kubernetes" in w and "or the posting" in w for w in warnings))


class Evasion(unittest.TestCase):
    """Ways a draft could look honest to the checker and read otherwise. Each one was found in review and must stay shut."""

    def assertBlocked(self, line, reason=""):
        errors = resume_errors(RESUME + f"\n{line}\n")
        self.assertTrue(errors and (not reason or any(reason in e for e in errors)), (line, errors))

    def test_a_negative_about_something_else_denies_nothing(self):
        for line in ("- With no added headcount, cut field defect rates by 83%.",
                     "- Never missed a milestone while leading ISO 26262 safety certification for the fleet.",
                     "- With no outside consultants, led ISO 26262 safety certification for the fleet.",
                     "- No outside consultants were needed to lead ISO 26262 safety certification.",
                     "- Led ISO 26262 certification, and I never missed a deadline."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")

    def test_a_denial_next_to_the_claim_still_counts(self):
        for line in ("- I have not worked under ISO 26262.", "- I have not yet worked under ISO 26262.",
                     "- No ISO 26262 experience yet.", "- The posting asks for safety certification, and I have not done it."):
            with self.subTest(line):
                self.assertEqual(resume_errors(RESUME + f"\n{line}\n"), [])

    def test_a_confidential_name_cannot_be_disguised(self):
        name = "Bluebird"
        head, tail = name[:4], name[4:]
        for disguised in (f"{head}\u200b{tail}", f"{head}\u00ad{tail}", f"**{head}****{tail}**", "\u0412" + name[1:]):
            with self.subTest(disguised=disguised):
                self.assertBlocked(f"- Delivered the {disguised} controller ahead of schedule.")

    def test_numbers_cannot_hide_in_formatting_full_width_digits_or_a_date(self):
        for line in ("- Managed a team of _40_ engineers.", "- Managed a team of \uff14\uff10 engineers.",
                     "- Promoted to lead on March 1, 2011."):
            with self.subTest(line):
                self.assertBlocked(line, "not in the fact bank")

    def test_short_links_and_handles_are_links(self):
        for line in ("- Demo reel at bit.ly/alexdemo.", "- Reach me at t.me/alexr.", "- Portfolio at alex.app."):
            with self.subTest(line):
                self.assertBlocked(line, "link or domain")
        # A skill list's file types aren't domains.
        self.assertFalse(any("link" in e for e in resume_errors(RESUME + "\n- Built dashboards in Node.js/React.\n")))

    def test_invisible_tag_characters_are_reported(self):
        self.assertBlocked("- Shipped firmware.\U000e0049\U000e0047\U000e004e", "invisible characters")

    def test_the_brief_check_is_held_to_the_same_rules(self):
        errors, _ = checks.check_brief(BRIEF + "\n- Mention the reel at bit.ly/alexdemo.\n", CFG, SOURCES, "Acme", "Staff Firmware Engineer")
        self.assertTrue(any("link" in e for e in errors), errors)
        for line, reason in (("- Say you managed forty engineers.", "spells out numbers"), ("- Say you doubled throughput.", "multiple"),
                             ("- Say you saved $3M.", "numbers")):
            with self.subTest(line):
                errors, _ = checks.check_brief(BRIEF + f"\n{line}\n", CFG, SOURCES, "Acme", "Staff Firmware Engineer")
                self.assertTrue(any(reason in e for e in errors), errors)

    def test_every_mention_of_a_claim_is_judged_not_just_the_first(self):
        self.assertBlocked("- I have not worked under ISO 26262, but led ISO 26262 audits for the fleet.", "unsupported claim")
        self.assertBlocked("- No ISO 26262 experience; led safety certification for the fleet.", "unsupported claim")

    def test_praise_after_a_claim_is_no_denial(self):
        for line in ("- Led ISO 26262 certification, and I could not be prouder of it.",
                     "- Led ISO 26262 audits, and I never missed one.",
                     "- Ran safety certification for the fleet, and I wouldn't change it.",
                     "- Ran safety certification, and I can't say enough about it."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")
        self.assertEqual(resume_errors(RESUME + "\n- The posting asks for safety certification, and I have not done it.\n"), [])

    def test_a_negative_before_a_new_subject_denies_nothing(self):
        for line in ("- With no budget I led ISO 26262 certification for the fleet.", "- Not once did I fail an ISO 26262 audit."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")
        self.assertEqual(resume_errors(RESUME + "\n- I have not yet worked under ISO 26262.\n"), [])

    def test_a_number_keeps_its_scale(self):
        # 212 tests and 3 launches are in the fact bank. Thousands of them, or millions of dollars, are not.
        for line in ("- Ran 212K automated tests on every merge.", "- Ran 212 thousand automated tests on every merge.",
                     "- Saved $3M across the robot launches.", "- Saved $3 million across the robot launches.", "- Shipped 3B units."):
            with self.subTest(line):
                self.assertBlocked(line, "numbers not in the fact bank")
        errors, _ = checks.check_text(LETTER.rstrip() + "\n\nWe ran 212K automated tests on every merge.\n", "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertTrue(any("212000" in e for e in errors), errors)
        self.assertEqual(number_checks.numbers("$1.5M, 1,500,000 and 1.5 million"), {"1500000"})
        self.assertEqual(number_checks.numbers("4.0 and 4"), {"4"})

    def test_a_percentage_is_a_percentage_however_it_is_written(self):
        # 7 is a team size and 35 a percentage in the fact bank. Neither is the other.
        for line in ("- Cut review time 7 percent.", "- Cut review time 7 per cent.", "- Hired 35 engineers."):
            with self.subTest(line):
                self.assertBlocked(line, "not in the fact bank")
        self.assertEqual(resume_errors(RESUME + "\n- Settling time down about 35 percent on the test rig.\n"), [])

    def test_multiples_are_measurements(self):
        for line in ("- Doubled throughput on the test rig.", "- Cut review time tenfold.", "- Delivered double-digit gains.",
                     "- Improved settling time by an order of magnitude."):
            with self.subTest(line):
                self.assertBlocked(line, "claims a multiple")

    def test_accents_and_look_alike_letters_hide_nothing(self):
        errors, _ = checks.check_text(LETTER.rstrip() + "\n\nI built the Bluébird controller.\n", "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertTrue(any("confidential term" in e for e in errors), errors)
        for disguised in ("Вӏуеbіrd", "ʙʟᴜᴇʙɪʀᴅ"):
            with self.subTest(disguised=disguised):
                self.assertBlocked(f"- Delivered the {disguised} controller.", "look-alike letters")
        # Words in another language, and names with letters of their own, are neither.
        self.assertFalse(reading.is_lookalike("Русский"))
        self.assertFalse(reading.disguises("Søren Łukasz Işık José", "Resume"))
        for table in (reading.LOOKALIKES, reading.PLAIN_LATIN):
            plain = [value if isinstance(value, str) else chr(value) for value in table.values()]
            self.assertTrue(all(not chr(key).isascii() and value.isascii() for key, value in zip(table, plain, strict=True)))
        self.assertEqual(len(reading.LOOKALIKES), 20 + 18 + 14 + 24)

    def test_a_company_name_is_set_aside_only_as_a_whole_word(self):
        self.assertEqual(reading.set_aside("Meta and Metadata at Meta's office", "Meta"), "  and Metadata at  's office")
        self.assertEqual(reading.set_aside("Anything", ""), "Anything")

    def test_contact_details_approve_no_numbers(self):
        # The example's phone number is (555) 010-0142. None of its parts is a measurement.
        for line in ("- Managed a team of 10 engineers.", "- Shipped firmware to 555 robots.", "- Cut boot time on 142 robots.",
                     "- Improved bench throughput 10x."):
            with self.subTest(line):
                self.assertBlocked(line)
        self.assertNotIn("555", factbank.without_contact(SOURCES))
        self.assertIn("1,400", factbank.without_contact(SOURCES))

    def test_praise_in_any_tense_is_no_denial(self):
        for line in ("- Led ISO 26262 certification for the fleet, and I could not have done it alone.",
                     "- Led ISO 26262 certification for the fleet, and I have not forgotten it.",
                     "- Led ISO 26262 certification for the fleet, and I never regretted it.",
                     "- Reproduced field failures in simulation, and I never tired of it.",
                     "- Led ISO 26262 certification for the fleet; I couldn't have done it alone."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")
        self.assertEqual(resume_errors(RESUME + "\n- I do not have ISO 26262 experience.\n"), [])

    def test_a_negative_that_praises_the_record_denies_nothing(self):
        for line in ("- Never failed an ISO 26262 audit.", "- Not a single ISO 26262 finding went unresolved.",
                     "- Shipped firmware without a single ISO 26262 nonconformance.", "- Didn't miss an ISO 26262 deadline."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")

    def test_a_forbidden_name_split_or_hyphenated_is_still_blocked(self):
        for line in ("- Delivered the blue bird controller ahead of schedule.", "- Wrote firmware for the Sky-Lift robot.",
                     "- Built tooling for the hives.", "- Shipped two Bluebirds."):
            with self.subTest(line):
                self.assertBlocked(line, "confidential term")
        errors, _ = checks.check_text(LETTER.rstrip() + "\n\nI delivered the Blue Bird controller.\n", "letter", CFG, SOURCES, *LETTER_ROLE)
        self.assertTrue(any("confidential term" in e for e in errors), errors)
        self.assertEqual(names.flexible(r"\bhives?\b"), r"\bhives?\b")  # A pattern is taken as written.

    def test_a_name_alone_on_a_do_not_use_line_is_blocked(self):
        listed = "## Do not use\n- Nightjar\n- Kestrel, the arm controller\n- Osprey Systems (a customer)\n- Customer names\n- Project Heron\n"
        self.assertEqual(checks.unguarded_terms(listed, []), ["Nightjar", "Kestrel", "Osprey", "Systems", "Heron"])

    def test_a_role_cannot_move_under_another_employer(self):
        role = "#### Principal Firmware Engineer | Madison, WI | Jan 2023 – Oct 2026"
        self.assertIn(role, MASTER)
        lines = [row for row in MASTER.splitlines() if row != role]
        moved = "\n".join(lines).replace("### Lakeshore Instruments | Aug 2012 – Jun 2017",
                                         f"### Lakeshore Instruments | Aug 2012 – Jun 2017\n{role}\n- Led the firmware team.")
        errors, _ = checks.check_resume_structure(moved, CFG)
        self.assertTrue(any("sits under" in e and "Lakeshore" in e for e in errors), errors)
        self.assertEqual(checks.check_resume_structure(MASTER, CFG)[0], [])

    def test_a_role_written_as_bold_text_is_held_to_the_record(self):
        line = "**Director, Firmware Engineering** | Madison, WI | Jan 2023 – Oct 2026"
        errors, _ = checks.check_resume_structure(RESUME + f"\n{line}\n", CFG)
        self.assertTrue(any("differ from your record" in e for e in errors), errors)
        self.assertBlocked("Head of firmware for the whole company.", "not in your approved sources")

    def test_blanks_and_placeholders_in_any_form_are_unfilled(self):
        self.assertBlocked("- Improved throughput by ___%.", "placeholder")
        for line in ("I would bring this to {company_name}.", "I would bring this to <Company Name>.", "FIXME: add a number"):
            with self.subTest(line):
                errors, _ = checks.check_text(LETTER.rstrip() + f"\n\n{line}\n", "letter", CFG, SOURCES, *LETTER_ROLE)
                self.assertTrue(any("placeholder" in e for e in errors), errors)

    def test_a_domain_with_any_ending_is_a_link_unless_your_sources_write_it(self):
        for line in ("- Portfolio and demos at alexrivera.pro", "- Demos at alex-rivera.design.", "- Write to alex@rivera.studio."):
            with self.subTest(line):
                self.assertBlocked(line, "link or domain")
        own = links.own_links("- Interned at Booking.com\n- Telemetry over Socket.IO and ASP.NET\n")
        for line in ("I interned at Booking.com.", "Telemetry over Socket.IO.", "Dashboards in ASP.NET."):
            with self.subTest(line):
                self.assertIsNone(links.link(line, own))
        for fine in ("Built dashboards in Node.js/React.", "Ph.D. and B.S. holders, e.g. the team.", "Ran it at 2.5 Hz.", "deploy.sh"):
            with self.subTest(fine):
                self.assertIsNone(links.link(fine, set()))

    def test_multiples_and_points_in_digits_are_measurements(self):
        for line, reason in (("- Improved bench throughput 8x.", "claims a multiple"), ("- Owned a seven-figure firmware budget.", "multiple"),
                             ("- Raised fleet availability by 60 percentage points.", "percentages"),
                             ("- Cut boot time by .83 seconds.", "numbers")):
            with self.subTest(line):
                self.assertBlocked(line, reason)

    def test_a_letter_date_may_be_written_any_common_way(self):
        for date in ("15 November 2026", "Nov. 15, 2026", "November 15th, 2026", "2026-11-15", "15th of November 2026"):
            with self.subTest(date):
                self.assertIn("November 2, 2026", LETTER)
                errors, _ = checks.check_text(LETTER.replace("November 2, 2026", date), "letter", CFG, SOURCES, *LETTER_ROLE)
                self.assertEqual(errors, [])

    def test_a_long_sentence_is_checked_in_reasonable_time(self):
        import time
        start = time.monotonic()
        resume_errors(RESUME + "\n- " + "I have not worked under ISO 26262 and " * 1500 + "that is all.\n")
        self.assertLess(time.monotonic() - start, 10)

    def test_comment_lines_in_a_plain_text_source_approve_nothing(self):
        self.assertNotIn("Zigbee", factbank.source_body("profile/approved-terms.txt", "CAN\n# Zigbee LoRaWAN\n"))
        self.assertIn("# Fact bank", factbank.source_body("profile/facts.md", "# Fact bank\n- Python\n"))

    def test_do_not_use_and_unsupported_approve_nothing_at_any_heading_level(self):
        bank = ("# Facts\n## Record\n- Shipped 3 launches\n### Do not use\n- Project Nightjar, 900 units\n#### Customers\n- Globex\n"
                "### Skills\n- Python\n# Unsupported claims\n- Kubernetes at 4000 nodes\n")
        kept = factbank.claimable(bank)
        for gone in ("Nightjar", "900", "Globex", "Kubernetes", "4000"):
            self.assertNotIn(gone, kept)
        for stays in ("3 launches", "Python"):
            self.assertIn(stays, kept)
        self.assertIn("Globex", factbank.do_not_use(bank))
        self.assertNotIn("Kubernetes", factbank.do_not_use(bank))

    def letter_errors(self, sentence, sources=SOURCES):
        return checks.check_text(LETTER.rstrip() + f"\n\n{sentence}\n", "letter", CFG, sources, *LETTER_ROLE)[0]

    def test_a_forbidden_name_joined_by_anything_is_still_blocked(self):
        # A letter only warns about a term it doesn't know, so nothing else stops these there.
        for name in ("Blue‑bird", "Blue–bird", "Blue_bird", "Blue/bird", "Blue  bird", "Blue - bird", "B.L.U.E.B.I.R.D.",
                     "Blue.bird", "Sky‑Lift"):
            with self.subTest(name=name):
                errors = self.letter_errors(f"I delivered the {name} controller.")
                self.assertTrue(any("confidential term" in e for e in errors), errors)
        # The full stop that ends a sentence joins nothing.
        self.assertIsNone(re.search(names.flexible("Bluebird"), "The sky was blue. Birds sang.", re.I))
        # Plain words with a space between are joined the same way, and so is a pattern "Block it" wrote earlier.
        for pattern in (names.flexible("SkyLift 900"), names.widen(names.term_pattern("SkyLift 900"))):
            for text in ("SkyLift 900", "skylift‑900", "SkyLift900", "SkyLift_900"):
                with self.subTest(pattern=pattern, text=text):
                    self.assertTrue(re.search(pattern, text, re.I))

    def test_a_name_listed_under_do_not_use_is_blocked_however_it_is_joined(self):
        facts = (store.ROOT / "profile" / "facts.md").read_text(encoding="utf-8")
        listed = facts.replace("## Do not use\n", "## Do not use\n- Codename Nightjar\n")
        blocked = checks.blocked_patterns(CFG, lambda rel: listed if rel == "profile/facts.md" else (store.ROOT / rel).read_text(encoding="utf-8"))
        for name in ("Night-jar", "night jar", "Night–jar"):
            with self.subTest(name=name):
                errors, _ = checks.check_text(LETTER.rstrip() + f"\n\nI shipped {name} on time.\n", "letter", CFG, SOURCES, *LETTER_ROLE,
                                              blocked=blocked)
                self.assertTrue(any("confidential term" in e for e in errors), errors)

    def test_praise_shaped_like_a_denial_denies_nothing(self):
        for line in ("- No stranger to ISO 26262.", "- Not new to ISO 26262 audits.", "- I have no shortage of ISO 26262 experience.",
                     "- Never far from ISO 26262 work.", "- Without question the team's ISO 26262 lead.",
                     "- Not a day went by without ISO 26262 work.",
                     "- The posting asks for ISO 26262 certification, and I have never missed an audit leading it."):
            with self.subTest(line):
                self.assertBlocked(line, "unsupported claim")
        for line in ("- No ISO 26262 experience yet.", "- I have not worked under ISO 26262.",
                     "- The posting lists ISO 26262 as a plus, and I have not worked under that standard."):
            with self.subTest(line):
                self.assertEqual(resume_errors(RESUME + f"\n{line}\n"), [])
        # A claim the posting makes, with a plain denial of your own after it, as the example letter words its gap.
        self.assertEqual(self.letter_errors("Your posting lists safety certification as a plus, and I have not worked under ISO 26262."), [])

    def test_a_multiple_or_fraction_in_any_word_form_is_a_measurement(self):
        for line in ("- Doubling test throughput on the rig.", "- Made the bench twice as fast.", "- Cut review time in half.",
                     "- Cut boot time by half.", "- Delivered a 3-fold gain in bench throughput.", "- Made merges 3 times faster.",
                     "- Tripling bench capacity on the rig.", "- Cut settling time by a third.", "- Cut escaped defects by two-thirds.",
                     "- Kept a third of the bench time for regression runs."):
            with self.subTest(line):
                self.assertBlocked(line, "claims a multiple")
                self.assertTrue(any("claims a multiple" in e for e in self.letter_errors(line[2:])), line)
        # Words that only look like one.
        for line in ("- Led a third robot launch in the second half of 2023.", "- Used double-precision math in the C++ firmware.",
                     "- Ran the bench 3 times on every merge.", "- Wrote the half-duplex CAN driver in C++.",
                     "- Did both halves of that work, firmware and test."):
            with self.subTest(line):
                self.assertEqual(resume_errors(RESUME + f"\n{line}\n"), [])
        # Each way of writing a multiple reads as the same one, so the fact bank's 3× approves "3 times faster" and no other.
        self.assertEqual(number_checks.number_errors("Resume", "about 3 times faster, a 3-fold gain", "about 3× per machine-hour", "x"), [])
        errors = number_checks.number_errors("Resume", "5,000× faster", "350,000× one core", "x")
        self.assertTrue(any("5000x" in e for e in errors), errors)

    def test_a_scale_is_a_scale_however_it_is_written(self):
        for line in ("- Saved $3m across the robot launches.", "- Saved $3 Million across the robot launches.",
                     "- Saved $3 MM across the robot launches.", "- Saved $3 mil across the robot launches.",
                     "- Saved US$3mn across the robot launches.", "- Processed 3 bn sensor readings."):
            with self.subTest(line):
                self.assertBlocked(line, "numbers not in the fact bank")
                self.assertTrue(any("numbers not in the fact bank" in e for e in self.letter_errors(line[2:])), line)
        self.assertEqual(number_checks.numbers("$3m, $3 MM, $3 mil, 3 Million, 3M and 3 bn"), {"3000000", "3000000000"})
        # Without a currency sign, a lowercase m or a letter after a space is as likely a unit.
        self.assertEqual(number_checks.numbers("30m of cable, a 5 mil film and 300 K"), {"30", "5", "300"})
        # A number's scale letter isn't a term of its own, so an honest 1.4K for 1,400 passes.
        self.assertEqual(resume_errors(RESUME + "\n- Wrote firmware for a fleet of 1.4K warehouse robots.\n"), [])

    def test_a_scale_word_beside_digits_approves_no_spelled_out_number(self):
        richer = SOURCES + "\n- Program budget of $1.5 million\n- Migrated hundreds of pages\n"
        for line in ("- Served five million users.", "- Processed several million sensor readings."):
            with self.subTest(line):
                errors, _ = checks.check_text(RESUME + f"\n{line}\n", "resume", CFG, richer, "Acme", "Principal Engineer")
                self.assertTrue(any("spells out numbers" in e and "million" in e for e in errors), errors)
        # A number word the fact bank writes on its own is still yours to use.
        errors, _ = checks.check_text(RESUME + "\n- Migrated hundreds of pages.\n", "resume", CFG, richer, "Acme", "Principal Engineer")
        self.assertEqual(errors, [])

    def test_units_with_a_micro_or_ohm_sign_are_not_disguises(self):
        self.assertEqual(reading.disguises("p95 3.8 µm, 0.17 µs, 4.7 μF and a 10 kΩ load", "Resume"), [])
        richer = SOURCES + "\n- Position error p95 3.8 µm\n"
        errors, _ = checks.check_text(RESUME + "\n- Held position error to p95 3.8 µm.\n", "resume", CFG, richer, "Acme", "Principal Engineer")
        self.assertEqual(errors, [])
        # The same sign inside a word is still a letter that doesn't belong there.
        for disguised in ("Blµebird", "µBluebird"):
            with self.subTest(disguised=disguised):
                self.assertTrue(reading.disguises(f"Delivered the {disguised} controller.", "Resume"))

    def test_the_parts_of_a_compound_the_sources_use_are_known_terms(self):
        richer = SOURCES + "\n- GPU-batched kinetics, tuned over CI/CD\n"
        for line in ("- Ran GPU kinetics on the bench.", "- Built the CI checks for it.", "- Ran Hardware-Loop reviews of the firmware."):
            with self.subTest(line):
                errors, _ = checks.check_text(RESUME + f"\n{line}\n", "resume", CFG, richer, "Acme", "Principal Engineer")
                self.assertEqual(errors, [])
        # A compound with one part no source uses is still named, whole.
        self.assertBlocked("- Ran Kubernetes-Loop reviews of the firmware.", "approved sources: Kubernetes-Loop")
        # A posting that names the compound doesn't make it borrowed.
        errors, _ = checks.check_text(RESUME + "\n- Ran Hardware/Loop reviews of the firmware.\n", "resume", CFG, SOURCES, "Acme",
                                      "Principal Engineer", posting="You will own Hardware/Loop testing.")
        self.assertEqual(errors, [])

    def test_a_date_alone_on_a_resume_line_is_a_claim(self):
        self.assertBlocked("March 1, 2011", "numbers not in the fact bank")

    def test_unsupported_lines_with_no_pattern_are_named(self):
        self.assertEqual(checks.unenforced_claims(CFG), [])  # The example's rules cover each line of its own list.
        facts = (store.ROOT / "profile" / "facts.md").read_text(encoding="utf-8")
        more = facts.rstrip() + "\n- Any Six Sigma belt\n- Percentages for fleet uptime\n"
        read = lambda rel: more if rel == "profile/facts.md" else (store.ROOT / rel).read_text(encoding="utf-8")
        self.assertEqual(checks.unenforced_claims(CFG, read), [("Any Six Sigma belt", "profile/facts.md")])
        self.assertEqual(factbank.unsupported_claims("## Skills\n- Python\n## Unsupported\n<!-- what you can't claim -->\n- Rust\n### More\n* Go\n"),
                         ["Rust", "Go"])
        # The line the example's rules missed until now, in the order the fact bank writes it.
        self.assertBlocked("- Field failures reproduced in simulation.", "unsupported claim")


class PassRecord(unittest.TestCase):
    def test_a_paste_box_text_or_a_new_document_after_a_pass_shows(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp)
            (folder / "resume.md").write_text("# Alex Rivera\n", encoding="utf-8")
            paste = folder / "Alex_Rivera_Resume_Acme.txt"
            paste.write_text("Alex Rivera\n", encoding="utf-8")
            (folder / "autofill-log.txt").write_text("typed\n", encoding="utf-8")
            checked = checks.fingerprints(folder)
            self.assertEqual(sorted(checked), ["Alex_Rivera_Resume_Acme.txt", "resume.md"])
            (folder / "autofill-log.txt").write_text("typed more\n", encoding="utf-8")
            self.assertEqual(checks.changed_since(folder, checked), [])
            paste.write_text("Alex Rivera\nLed a team of 40.\n", encoding="utf-8")
            (folder / "Alex_Rivera_Resume_Acme_v2.docx").write_bytes(b"PK")
            self.assertEqual(checks.changed_since(folder, checked), ["Alex_Rivera_Resume_Acme.txt", "Alex_Rivera_Resume_Acme_v2.docx"])
            # A pass recorded before .txt files were covered isn't held to them.
            self.assertEqual(checks.changed_since(folder, {"resume.md": checked["resume.md"]}), ["Alex_Rivera_Resume_Acme_v2.docx"])

    def test_a_draft_that_is_not_utf8_is_an_error_not_a_crash(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp)
            (folder / "resume.md").write_bytes("# Alex Rivera\n- Café\n".encode("cp1252"))
            report = checks.check_application(folder, CFG, "Acme", "Engineer")
            self.assertFalse(report["ok"])
            self.assertIn("isn't saved as UTF-8", report["errors"][0])

    def test_a_change_to_the_facts_or_rules_shows_after_a_pass(self):
        recorded = checks.source_fingerprints(CFG)
        self.assertEqual(checks.sources_changed(CFG, recorded), [])
        self.assertEqual(checks.sources_changed(CFG, None), [])  # A pass from before these were kept.
        self.assertEqual(checks.sources_changed(CFG, {**recorded, "profile/facts.md": "0" * 64}), ["profile/facts.md"])
        stricter = {**CFG, "guard": {**CFG["guard"], "forbidden": [*CFG["guard"]["forbidden"], "Nightjar"]}}
        self.assertEqual(checks.sources_changed(stricter, recorded), [checks.GUARD_KEY])


if __name__ == "__main__":
    unittest.main()
