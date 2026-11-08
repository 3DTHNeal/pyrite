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

from pyrite import checks


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
        self.assertNotIn("skylift", checks._vocabulary(SOURCES))
        self.assertIn("firmware", checks._vocabulary(SOURCES))
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
        self.assertEqual(checks._numbers("$1.5M, 1,500,000 and 1.5 million"), {"1500000"})
        self.assertEqual(checks._numbers("4.0 and 4"), {"4"})

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
        self.assertFalse(checks._lookalike("Русский"))
        self.assertFalse(checks._disguises("Søren Łukasz Işık José", "Resume"))
        for table in (checks.LOOKALIKES, checks.PLAIN_LATIN):
            plain = [value if isinstance(value, str) else chr(value) for value in table.values()]
            self.assertTrue(all(not chr(key).isascii() and value.isascii() for key, value in zip(table, plain, strict=True)))
        self.assertEqual(len(checks.LOOKALIKES), 20 + 18 + 14 + 24)

    def test_a_company_name_is_set_aside_only_as_a_whole_word(self):
        self.assertEqual(checks._set_aside("Meta and Metadata at Meta's office", "Meta"), "  and Metadata at  's office")
        self.assertEqual(checks._set_aside("Anything", ""), "Anything")

    def test_do_not_use_and_unsupported_approve_nothing_at_any_heading_level(self):
        bank = ("# Facts\n## Record\n- Shipped 3 launches\n### Do not use\n- Project Nightjar, 900 units\n#### Customers\n- Globex\n"
                "### Skills\n- Python\n# Unsupported claims\n- Kubernetes at 4000 nodes\n")
        kept = checks.claimable(bank)
        for gone in ("Nightjar", "900", "Globex", "Kubernetes", "4000"):
            self.assertNotIn(gone, kept)
        for stays in ("3 launches", "Python"):
            self.assertIn(stays, kept)
        self.assertIn("Globex", checks.do_not_use(bank))
        self.assertNotIn("Kubernetes", checks.do_not_use(bank))


class PassRecord(unittest.TestCase):
    def test_a_change_to_the_facts_or_rules_shows_after_a_pass(self):
        recorded = checks.source_fingerprints(CFG)
        self.assertEqual(checks.sources_changed(CFG, recorded), [])
        self.assertEqual(checks.sources_changed(CFG, None), [])  # A pass from before these were kept.
        self.assertEqual(checks.sources_changed(CFG, {**recorded, "profile/facts.md": "0" * 64}), ["profile/facts.md"])
        stricter = {**CFG, "guard": {**CFG["guard"], "forbidden": [*CFG["guard"]["forbidden"], "Nightjar"]}}
        self.assertEqual(checks.sources_changed(stricter, recorded), [checks.GUARD_KEY])


if __name__ == "__main__":
    unittest.main()
