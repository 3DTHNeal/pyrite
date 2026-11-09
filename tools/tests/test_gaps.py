"""The gaps that keep coming up: reading the numbered gap lists in each application's notes, grouping the ones that
name the same requirement, and turning answers into fact-bank lines and rework flags. All of it on the fictional
example, whose two applications both list Rust and team size as gaps."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import unittest.mock as mock
from pathlib import Path

import support  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import cli, confirm, factsdoc, gaps, profile, server, steps, store

ACME = "applications/2026-11-acme-principal-robotics-software-engineer"
GLOBEX = "applications/2026-11-globex-staff-firmware-engineer"

NOTES = """# Initech Controls: Firmware Engineering Manager

## How the posting maps to the record

| What they want | Evidence | Strength |
|---|---|---|
| Rust | Nothing on record | Gap |

## Gaps to prepare for

1. **Hands-on Rust.** *Record silent:* nothing says whether you've written it.
2. **Team size**: The largest team is 7,
   and the posting wants 10.
3. Travel. Up to a quarter of the time.
4. **Public cloud.** Confirmed: you haven't run production services on it.

## Claims to word carefully

1. **Not a gap.** This list isn't read.
"""


class Reading(unittest.TestCase):
    def test_the_numbered_list_under_the_gaps_heading_is_read(self):
        found = gaps.parse(NOTES, "applications/initech")
        self.assertEqual([g.name for g in found], ["Hands-on Rust", "Team size", "Travel", "Public cloud"])
        self.assertEqual([g.number for g in found], [1, 2, 3, 4])
        self.assertIn("and the posting wants 10", found[1].text)
        self.assertEqual([g.kind for g in found], ["silent", "open", "open", "known"])
        self.assertTrue(all(g.folder == "applications/initech" for g in found))

    def test_notes_without_the_list_have_no_gaps(self):
        self.assertEqual(gaps.parse("# Acme: Engineer\n\n## Claims to word carefully\n\n1. **X.** y\n"), [])

    def test_wordings_of_one_requirement_match_and_others_dont(self):
        same = lambda a, b: gaps.same(gaps.tokens(a), gaps.tokens(b))
        self.assertTrue(same("Hands-on C++", "C++ depth"))
        self.assertTrue(same("Vendors", "Vendor management"))
        self.assertTrue(same("Public cloud", "Production services and public cloud"))
        self.assertTrue(same("Bench results aren’t field results", "Bench results are not field results"))
        self.assertFalse(same("Kubernetes", "Rust"))
        self.assertFalse(same("Domain", "HR technology domain"))  # A category names no requirement of its own.
        self.assertIn("c", gaps.tokens("C and Python"))
        self.assertIn("c++", gaps.tokens("Hands-on C/C++"))

    def test_the_example_ranks_what_both_applications_raise(self):
        found = gaps.view()
        self.assertEqual(found["applications"], 2)
        by_id = {g["id"]: g for g in found["groups"]}
        self.assertEqual([g["id"] for g in gaps.questions(found)], ["rust", "team-size"])
        self.assertEqual(by_id["rust"]["count"], 2)
        self.assertEqual(by_id["rust"]["kinds"], {"silent": 2})
        self.assertEqual({m["folder"] for m in by_id["rust"]["members"]}, {ACME, GLOBEX})
        # Already under Unsupported in the example's fact bank, so not asked again.
        self.assertEqual(by_id["safety-certification"]["state"], "unsupported")
        self.assertEqual(by_id["travel"]["count"], 1)
        self.assertEqual([g["id"] for g in gaps.questions(found, 1)], ["rust", "team-size", "travel"])

    def test_the_tailor_is_told_the_shape_the_count_reads(self):
        text = (Path(gaps.__file__).parent / "tailor.md").read_text(encoding="utf-8")
        self.assertIn("## Gaps to prepare for", text)
        self.assertIn("*Record silent*", text)


class Workspace(support.Base):
    """A real workspace: the example's profile and applications, a database with the two jobs, Acme sent and Globex not.
    Holds no tests of its own."""

    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name) / "workspace"
        for part in ("profile", "applications"):
            shutil.copytree(store.EXAMPLE_ROOT / part, self.root / part)
        for target, name, value in ((store, "ROOT", self.root), (server, "ROOT", self.root), (store, "IS_EXAMPLE", False),
                                    (store, "DB_PATH", Path(self.tmp.name) / "t.db")):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.acme = self.add(company="Acme Robotics", title="Principal Robotics Software Engineer", status="applied",
                             applied_at=store.now(), app_folder=ACME)
        self.globex = self.add(company="Globex Automation", title="Staff Firmware Engineer", status="needs_fix",
                               app_folder=GLOBEX, source_id="2")
        self.conn.commit()
        # The server opens the workspace's database itself, which is this test's.
        self.conn.close()
        self.conn = store.connect()

    def facts(self) -> str:
        return profile.read("facts")

    def draft(self, *answers):
        return steps.draft("gaps", {"answers": list(answers)}, profile.versions())

    def save(self, *answers):
        result = self.draft(*answers)
        return server._save_profile({"changes": result["changes"], "based_on": profile.versions(), "step": "gaps",
                                     "reason": "Gaps to answer", "answers": list(answers)})

    def events(self, kind=gaps.ANSWERED):
        return [tuple(row) for row in self.conn.execute("SELECT job_id, detail FROM events WHERE kind = ?", (kind,))]


class Answering(Workspace):
    def test_a_yes_adds_the_fact_under_the_chosen_section_and_needs_no_code(self):
        result = self.draft({"id": "rust", "answer": "yes", "text": "- Wrote a CAN driver in Rust for the test bench",
                             "section": "Robotics and firmware"})
        self.assertEqual(result["code"], [])
        self.assertEqual(result["count"], 1)
        doc = factsdoc.Doc(result["changes"]["facts"])
        section = doc.section("Robotics and firmware")
        self.assertIn("Wrote a CAN driver in Rust for the test bench", [i.text for i in doc.items(section)])
        # A new section is made before the ones that approve nothing.
        result = self.draft({"id": "rust", "answer": "yes", "text": "Rust on the bench", "section": "Languages"})
        titles = [s.title for s in factsdoc.Doc(result["changes"]["facts"]).sections()]
        self.assertLess(titles.index("Languages"), titles.index("Do not use"))

    def test_a_no_goes_under_unsupported_in_the_gaps_words_or_yours(self):
        result = self.draft({"id": "team-size", "answer": "no"})
        doc = factsdoc.Doc(result["changes"]["facts"])
        unsupported = doc.section("Unsupported")
        self.assertIn("Team size", [i.text for i in doc.items(unsupported)])
        self.assertEqual(result["code"], [])
        result = self.draft({"id": "team-size", "answer": "no", "text": "Leading a team of 10 or more"})
        self.assertIn("Leading a team of 10 or more", result["changes"]["facts"])

    def test_answers_that_cant_be_written_are_refused(self):
        for answer, why in (({"id": "nope", "answer": "no"}, "No gap called"),
                            ({"id": "rust", "answer": "yes", "text": "Rust", "section": ""}, "Choose the section"),
                            ({"id": "rust", "answer": "yes", "text": "Rust", "section": "Unsupported"}, "approves nothing"),
                            ({"id": "rust", "answer": "maybe"}, "yes or no"),
                            ({"id": "rust", "answer": "yes", "text": "two\nlines", "section": "Leadership"}, "line break")):
            with self.subTest(answer=answer), self.assertRaisesRegex(ValueError, why):
                self.draft(answer)
        # A yes still being written adds nothing yet.
        self.assertEqual(self.draft({"id": "rust", "answer": "yes", "text": "", "section": "Leadership"})["count"], 0)

    def test_a_fact_that_names_something_off_limits_is_pointed_out(self):
        result = self.draft({"id": "rust", "answer": "yes", "text": "Wrote Rust tooling for Bluebird", "section": "Leadership"})
        self.assertTrue(any("Never mention" in note for note in result["notes"]))

    def test_saving_records_the_answer_and_flags_only_unsent_drafts(self):
        page = self.save({"id": "rust", "answer": "yes", "text": "Wrote a CAN driver in Rust", "section": "Robotics and firmware"})
        self.assertIn("Wrote a CAN driver in Rust", self.facts())
        rows = gaps.answers()
        self.assertEqual([(r["id"], r["answer"], r["lines"]) for r in rows], [("rust", "yes", ["Wrote a CAN driver in Rust"])])
        flagged = self.events()
        self.assertEqual([job for job, _ in flagged], [self.globex])  # Acme was sent, so it's a record.
        self.assertIn("You answered “Rust”", flagged[0][1])
        # The section stops asking it, and History keeps the file from before.
        rust = next(g for g in page["gaps"]["groups"] if g["id"] == "rust")
        self.assertEqual(rust["state"], "answered")
        self.assertEqual([g["id"] for g in gaps.questions(page["gaps"])], ["team-size"])
        self.assertEqual(profile.history()[0]["step"], "gaps")

    def test_what_is_recorded_follows_the_file_not_the_page(self):
        result = self.draft({"id": "team-size", "answer": "no"})
        server._save_profile({"changes": result["changes"], "based_on": profile.versions(), "step": "gaps",
                              "answers": [{"id": "team-size", "answer": "no"},
                                          {"id": "rust", "answer": "yes", "text": "Rust everywhere", "section": "Leadership"}]})
        self.assertEqual([r["id"] for r in gaps.answers()], ["team-size"])

    def test_a_save_that_loosens_a_check_still_asks_for_a_code(self):
        # Taking a line off Unsupported is loosening wherever the save comes from.
        facts = "".join(line for line in self.facts().splitlines(keepends=True) if "Safety certification" not in line)
        self.assertNotEqual(facts, self.facts())
        with mock.patch.object(confirm.notify, "send", return_value=True), self.assertRaises(confirm.CodeNeeded):
            server._save_profile({"changes": {"facts": facts}, "based_on": profile.versions(), "step": "gaps", "answers": []})
        confirm._clear()

    def test_the_rework_flag_shows_on_the_to_do_list_until_seen_or_rewritten(self):
        self.save({"id": "team-size", "answer": "no"})
        state = server.build_state(self.conn, support.CFG)
        rework = [o for o in state["orders"] if o["kind"] == "Rework"]
        self.assertEqual([o["job_id"] for o in rework], [self.globex])
        self.assertEqual(rework[0]["action"], "gap_seen")
        self.assertIn("Team size", rework[0]["detail"])
        server.apply_action(self.conn, self.globex, {"action": "gap_seen"}, support.CFG)
        self.conn.commit()
        self.assertFalse([o for o in server.build_state(self.conn, support.CFG)["orders"] if o["kind"] == "Rework"])
        # A later answer flags it again, and a resume rewritten after it clears that.
        gaps.forget("team-size")
        self.save({"id": "rust", "answer": "no"})
        self.assertTrue([o for o in server.build_state(self.conn, support.CFG)["orders"] if o["kind"] == "Rework"])
        resume = self.root / GLOBEX / "resume.md"
        later = time.time() + 5
        os.utime(resume, (later, later))
        self.assertFalse([o for o in server.build_state(self.conn, support.CFG)["orders"] if o["kind"] == "Rework"])

    def test_dismissing_and_asking_again_change_no_file(self):
        before = self.facts()
        page = server._gap_question({"action": "dismiss", "id": "team-size"})
        self.assertEqual(self.facts(), before)
        self.assertEqual([g["id"] for g in gaps.questions(page["gaps"])], ["rust"])
        self.assertEqual(self.events(), [])
        page = server._gap_question({"action": "forget", "id": "team-size"})
        self.assertEqual([g["id"] for g in gaps.questions(page["gaps"])], ["rust", "team-size"])
        with self.assertRaisesRegex(ValueError, "wasn't answered"):
            server._gap_question({"action": "forget", "id": "team-size"})
        with self.assertRaisesRegex(ValueError, "dismiss"):
            server._gap_question({"action": "delete", "id": "team-size"})

    def test_a_new_wording_of_an_answered_gap_counts_as_answered(self):
        self.save({"id": "rust", "answer": "no"})
        third = self.root / "applications" / "2026-11-initech-firmware-manager"
        third.mkdir()
        (third / "notes.md").write_text(NOTES, encoding="utf-8")
        found = gaps.view(self.conn)
        rust = next(g for g in found["groups"] if g["id"] == "rust")
        self.assertEqual(rust["state"], "answered")
        self.assertEqual(rust["count"], 3)
        self.assertTrue(rust["raised_again"])  # Those notes were written after the answer.

    def test_the_hub_says_how_many_questions_are_waiting(self):
        view = profile.view()
        section = next(s for s in view["steps"] if s["id"] == "gaps")
        self.assertEqual(section["summary"], "2 questions from 2 applications")
        self.assertEqual(section["status"], "attention")
        self.assertTrue(any(n["step"] == "gaps" for n in view["needs"]))

    def test_the_to_do_list_asks_once_a_gap_comes_up_three_times(self):
        self.assertFalse([o for o in server.build_state(self.conn, support.CFG)["orders"] if o["kind"] == "Gaps to answer"])
        third = self.root / "applications" / "2026-11-initech-firmware-manager"
        third.mkdir()
        (third / "notes.md").write_text(NOTES, encoding="utf-8")
        order = next(o for o in server.build_state(self.conn, support.CFG)["orders"] if o["kind"] == "Gaps to answer")
        self.assertEqual(order["tab"], "profile/gaps")
        self.assertIsNone(order["job_id"])
        self.assertIn("“Rust” in 3", order["detail"])


class Command(Workspace):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cli.main(["gaps", *argv])
            except SystemExit as stop:
                return out.getvalue() + str(stop.code or "")
        return out.getvalue()

    def test_listing_prints_json_to_a_pipe(self):
        found = json.loads(self.run_cli())
        self.assertEqual([g["id"] for g in found["groups"]], ["rust", "team-size"])
        self.assertEqual(len(json.loads(self.run_cli("--all"))["groups"]), 4)

    def test_listing_in_words(self):
        with mock.patch.object(cli, "_as_json", return_value=False):
            text = self.run_cli()
        self.assertIn("2 requirements keep coming up as gaps, from 2 applications' notes", text)
        self.assertIn("rust  Rust", text)
        self.assertIn("1 more gap came up in fewer applications", text)

    def test_answering_from_the_command_line(self):
        text = self.run_cli("answer", "rust", "--yes", "Wrote a CAN driver in Rust", "--section", "Robotics and firmware")
        self.assertIn("Added “Wrote a CAN driver in Rust” under Robotics and firmware", text)
        self.assertIn("1 draft you haven't sent lists this gap", text)
        self.assertIn("Wrote a CAN driver in Rust", self.facts())
        text = self.run_cli("answer", "team-size", "--no")
        self.assertIn("under Unsupported", text)
        self.assertEqual({r["id"]: r["answer"] for r in gaps.answers()}, {"rust": "yes", "team-size": "no"})
        self.assertIn("Choose the section", self.run_cli("answer", "travel", "--yes", "Travelled a lot"))
        self.assertIn("Answer with --yes", self.run_cli("answer", "travel"))
        self.assertIn("Stopped asking", self.run_cli("answer", "travel", "--dismiss"))
        self.assertIn("will be asked again", self.run_cli("forget", "travel"))
        self.assertIn("No gap called", self.run_cli("answer", "nope", "--no"))

    def test_the_example_cant_be_answered(self):
        with mock.patch.object(store, "IS_EXAMPLE", True):
            self.assertIn("fictional example", self.run_cli("answer", "rust", "--no"))
            with self.assertRaisesRegex(ValueError, "demo"):
                server._gap_question({"action": "dismiss", "id": "rust"})


class Untouched(unittest.TestCase):
    def test_a_workspace_with_no_applications_has_no_questions(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            found = gaps.view(root=Path(tmp))
        self.assertEqual(found, {"groups": [], "applications": 0, "gaps": 0, "ask_from": gaps.ASK_FROM})

    def test_an_answers_file_that_wont_read_counts_as_none(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(store, "ROOT", Path(tmp)):
            (Path(tmp) / "data").mkdir()
            (Path(tmp) / "data" / "gap-answers.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(gaps.answers(), [])


if __name__ == "__main__":
    unittest.main()
