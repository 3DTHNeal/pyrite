"""The Profile tab's section editors: each form drafted into the files a save would write, by the same code a save
uses, without writing anything. Also the pieces they lean on: changing one item in a TOML list, an employer's line,
and how the fact check reads one sentence."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import checks, factsdoc, profile, server, steps, store, tomledit

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"


def lf(result: dict, key: str) -> str:
    """A drafted file with Unix line endings. A checkout may have either, and a draft keeps whichever the file has."""
    return result["changes"][key].replace("\r\n", "\n")


class EditList(unittest.TestCase):
    TEXT = ("[guard]\n"
            "forbidden = ['Bluebird', 'Falconer']  # confidential\n"
            "unsupported = [\n"
            "  'ISO 26262', 'safety',  # two to a line\n"
            "  # a note inside the list\n"
            "  'field failures',\n"
            "]\n")

    def test_one_item_goes_and_the_rest_keep_their_lines_and_comments(self):
        new = tomledit.edit_list(self.TEXT, "guard", "unsupported", remove=["safety"])
        self.assertIn("  'ISO 26262',  # two to a line\n  # a note inside the list\n  'field failures',\n]", new)

    def test_an_item_alone_on_its_line_takes_the_line_with_it(self):
        new = tomledit.edit_list(self.TEXT, "guard", "unsupported", remove=["field failures"])
        self.assertTrue(new.endswith("  # a note inside the list\n]\n"), new)

    def test_a_new_item_gets_its_own_line_before_the_bracket(self):
        new = tomledit.edit_list(self.TEXT, "guard", "unsupported", add=["\\bKubernetes\\b"], literal=True)
        self.assertIn("  'field failures',\n  '\\bKubernetes\\b',\n]", new)
        self.assertEqual(tomllib.loads(new)["guard"]["unsupported"][-1], "\\bKubernetes\\b")

    def test_a_one_line_list_stays_on_its_line(self):
        new = tomledit.edit_list(self.TEXT, "guard", "forbidden", remove=["Falconer"], add=["Osprey"], literal=True)
        self.assertIn("forbidden = ['Bluebird', 'Osprey']  # confidential\n", new)
        new = tomledit.edit_list(self.TEXT, "guard", "forbidden", remove=["Bluebird", "Falconer"])
        self.assertEqual(tomllib.loads(new)["guard"]["forbidden"], [])

    def test_removing_then_adding_back_reads_the_same(self):
        new = tomledit.edit_list(self.TEXT, "guard", "unsupported", remove=["ISO 26262"])
        back = tomledit.edit_list(new, "guard", "unsupported", add=["ISO 26262"])
        self.assertEqual(set(tomllib.loads(back)["guard"]["unsupported"]), set(tomllib.loads(self.TEXT)["guard"]["unsupported"]))

    def test_a_missing_list_is_added_and_nothing_to_do_changes_nothing(self):
        new = tomledit.edit_list(self.TEXT, "guard", "disclaimers", add=["\\bnot\\b"], literal=True)
        self.assertEqual(tomllib.loads(new)["guard"]["disclaimers"], ["\\bnot\\b"])
        self.assertEqual(tomledit.edit_list(self.TEXT, "guard", "forbidden", remove=["Nope"]), self.TEXT)


class EmployerLines(unittest.TestCase):
    def test_a_name_and_dates_change_and_the_rest_of_the_line_stays(self):
        line = "- **Northbridge Robotics, Jun 2017 – Oct 2026** (acquired)"
        self.assertEqual(factsdoc.employer_text(line, name="Northbridge", end="Nov 2026"),
                         "- **Northbridge, Jun 2017 – Nov 2026** (acquired)")

    def test_a_one_line_employer_changes_only_its_name(self):
        line = "- **Lakeshore Instruments,** Embedded Software Engineer, Milwaukee, WI, Aug 2012 – Jun 2017"
        self.assertEqual(factsdoc.employer_text(line, name="Lakeshore"),
                         "- **Lakeshore,** Embedded Software Engineer, Milwaukee, WI, Aug 2012 – Jun 2017")


class Explain(unittest.TestCase):
    GUARD = {"forbidden": ["SkyLift"], "unsupported": ["ISO 26262"], "disclaimers": ["\\bnot\\b"]}

    def test_each_match_is_named_as_the_check_reads_it(self):
        seen = checks.explain("Led SkyLift bring-up. I have not worked under ISO 26262. Earned ISO 26262 sign-off.", self.GUARD)
        self.assertEqual([hit["kind"] for hit in seen["hits"]], ["never", "denied", "claim"])
        self.assertTrue(seen["blocked"])

    def test_a_denial_alone_passes(self):
        self.assertFalse(checks.explain("I have not worked under ISO 26262.", self.GUARD)["blocked"])


class Steps(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = {**profile.view(), **steps.view()}

    def draft(self, step, edits):
        return steps.draft(step, edits, self.view["versions"])

    def save(self, result):
        profile.write(result["changes"], self.view["versions"], "test")
        self.view = {**profile.view(), **steps.view()}

    def employers(self):
        return [{"line": e["line"], "name": e["name"], "roles": [dict(r) for r in e["roles"]]}
                for e in self.view["timeline"]["employers"]]

    def test_an_unchanged_form_writes_nothing(self):
        lists = self.view["off_limits_lists"]
        for step, edits in (
            ("basics", {"name": self.view["basics"]["name"], "paper": "letter",
                        "contact": [p["text"] for p in self.view["contact_parts"]["parts"]]}),
            ("history", {"employers": self.employers(), "other": self.view["timeline"]["other"],
                         "expected": self.view["expected"]}),
            ("offlimits", {"never": {}, "nottrue": {}}),
            ("skills", {"add": [], "drop": []}),
        ):
            result = self.draft(step, edits)
            self.assertEqual((result["changes"], result["count"]), ({}, 0), step)
        self.assertTrue(lists["never"]["items"])

    def test_a_draft_based_on_an_old_version_is_refused(self):
        (self.root / "profile" / "facts.md").write_bytes((profile.read("facts") + "- More\n").encode())
        with self.assertRaises(profile.Conflict):
            self.draft("basics", {"name": "Someone Else"})

    def test_a_section_without_an_editor_is_refused(self):
        with self.assertRaises(ValueError):
            self.draft("roles", {})

    # ---- Name and contact ----

    def test_name_and_contact_go_everywhere_they_appear(self):
        parts = [p["text"] for p in self.view["contact_parts"]["parts"]]
        parts[2] = "alex@rivera.example"
        result = self.draft("basics", {"name": "Alex Q. Rivera", "contact": parts, "paper": "a4"})
        self.assertEqual(set(result["changes"]), {"config", "facts", "resume", "letter"})
        line = "Madison, WI · (555) 010-0142 · alex@rivera.example · linkedin.com/in/alex-rivera-example"
        self.assertIn(f"\n{line}\n", lf(result, "facts"))
        for key in ("resume", "letter"):
            self.assertIn("# Alex Q. Rivera\n", lf(result, key))
            self.assertIn(f"@ {line}\n", lf(result, key))
        config = tomllib.loads(lf(result, "config"))
        self.assertEqual((config["candidate"]["name"], config["documents"]["paper"]), ("Alex Q. Rivera", "a4"))
        self.assertEqual(result["code"], [])

    def test_the_contact_line_is_split_into_parts_by_kind(self):
        kinds = [p["kind"] for p in self.view["contact_parts"]["parts"]]
        self.assertEqual(kinds, ["place", "phone", "email", "link"])
        self.assertEqual(self.view["contact_parts"]["checked_in"], "profile/resume.md")

    def test_a_contact_line_checked_elsewhere_is_named(self):
        (self.root / "applications" / "model").mkdir(parents=True)
        shutil.copy(self.root / "profile" / "resume.md", self.root / "applications" / "model" / "resume.md")
        config = tomledit.edit_list(profile.read("config"), "guard", "approved_sources",
                                    remove=["profile/resume.md", "profile/cover-letter.md"],
                                    add=["applications/model/resume.md"])
        (self.root / "profile" / "search.toml").write_bytes(config.encode())
        self.view = {**profile.view(), **steps.view()}
        result = self.draft("basics", {"contact": ["Springfield"]})
        self.assertTrue(any("applications/model/resume.md" in note for note in result["notes"]), result["notes"])

    def test_what_cant_go_on_the_contact_line_is_refused(self):
        for edits, message in (({"name": " "}, "can't be empty"), ({"contact": ["a · b"]}, "split it in two"),
                               ({"contact": [""]}, "at least one"), ({"paper": "legal"}, "Letter or A4"),
                               ({"name": "Two\nlines"}, "line break")):
            with self.assertRaises(ValueError) as caught:
                self.draft("basics", edits)
            self.assertIn(message, str(caught.exception))

    # ---- Work history ----

    def test_a_changed_role_changes_facts_and_the_master_resume_headings(self):
        employers = self.employers()
        employers[0]["roles"][0].update(title="Distinguished Firmware Engineer", end="Nov 2026")
        result = self.draft("history", {"employers": employers})
        facts, resume = lf(result, "facts"), lf(result, "resume")
        self.assertIn("- **Northbridge Robotics, Jun 2017 – Nov 2026**\n", facts)
        self.assertIn("  - Distinguished Firmware Engineer, Madison, WI, Jan 2023 – Nov 2026\n", facts)
        self.assertIn("### Northbridge Robotics | Jun 2017 – Nov 2026\n", resume)
        self.assertIn("#### Distinguished Firmware Engineer | Madison, WI | Jan 2023 – Nov 2026\n", resume)
        self.assertNotIn("#### Principal Firmware Engineer", resume)

    def test_a_second_role_turns_a_one_line_employer_into_a_list(self):
        employers = self.employers()
        employers[1]["roles"][0]["end"] = "Dec 2015"
        employers[1]["roles"].insert(0, {"line": None, "title": "Senior Embedded Engineer", "place": "Milwaukee, WI",
                                         "start": "Jan 2016", "end": "Jun 2017"})
        result = self.draft("history", {"employers": employers})
        self.assertIn("- **Lakeshore Instruments, Aug 2012 – Jun 2017**\n"
                      "  - Senior Embedded Engineer, Milwaukee, WI, Jan 2016 – Jun 2017\n"
                      "  - Embedded Software Engineer, Milwaukee, WI, Aug 2012 – Dec 2015\n", lf(result, "facts"))
        self.assertIn("#### Senior Embedded Engineer | Milwaukee, WI | Jan 2016 – Jun 2017\n"
                      "#### Embedded Software Engineer | Milwaukee, WI | Aug 2012 – Dec 2015\n", lf(result, "resume"))
        self.save(result)
        names = [r["title"] for r in self.view["timeline"]["employers"][1]["roles"]]
        self.assertEqual(names, ["Senior Embedded Engineer", "Embedded Software Engineer"])

    def test_a_new_employer_goes_first_in_both_files(self):
        employers = [{"line": None, "name": "Initech", "roles": [
            {"title": "Staff Engineer", "place": "Remote", "start": "Dec 2026", "end": ""}]}, *self.employers()]
        result = self.draft("history", {"employers": employers})
        self.assertIn("## Timeline\n- **Initech,** Staff Engineer, Remote, Dec 2026 – Present\n", lf(result, "facts"))
        self.assertIn("## Experience\n### Initech | Dec 2026 – Present\n#### Staff Engineer | Remote | Dec 2026 – Present\n",
                      lf(result, "resume"))

    def test_a_removed_role_takes_its_resume_heading_and_bullets(self):
        employers = self.employers()
        del employers[0]["roles"][2]
        result = self.draft("history", {"employers": employers})
        self.assertNotIn("Senior Firmware Engineer", lf(result, "facts"))
        self.assertNotIn("Senior Firmware Engineer", lf(result, "resume"))
        self.assertNotIn("Cut motion-controller boot time", lf(result, "resume"))
        self.assertIn("### Northbridge Robotics | Mar 2020 – Oct 2026\n", lf(result, "resume"))

    def test_education_lines_and_what_every_resume_should_include(self):
        other = [*self.view["timeline"]["other"], {"line": None, "label": "Patent", "text": "US 1,234,567"}]
        expected = [*self.view["expected"], {"text": "1,234,567", "label": "Patent"}]
        result = self.draft("history", {"employers": self.employers(), "other": other, "expected": expected})
        self.assertIn("- **Certifications:** Certified ScrumMaster\n- **Patent:** US 1,234,567\n", lf(result, "facts"))
        self.assertEqual(tomllib.loads(lf(result, "config"))["guard"]["expected_on_resume"][-1],
                         {"text": "1,234,567", "label": "Patent"})

    def test_a_note_after_the_dates_stays(self):
        facts = profile.read("facts").replace("Jun 2017 – Mar 2020", "Jun 2017 – Mar 2020 (promoted twice)")
        (self.root / "profile" / "facts.md").write_bytes(facts.encode())
        self.view = {**profile.view(), **steps.view()}
        employers = self.employers()
        employers[0]["roles"][2]["place"] = "Remote"
        result = self.draft("history", {"employers": employers})
        self.assertIn("  - Senior Firmware Engineer, Remote, Jun 2017 – Mar 2020 (promoted twice)\n", lf(result, "facts"))

    def test_history_that_wouldnt_read_back_is_refused(self):
        employers = self.employers()
        employers[0]["roles"][0]["end"] = "Dec 2022"
        with self.assertRaises(ValueError) as caught:
            self.draft("history", {"employers": employers})
        self.assertIn("ends before it starts", str(caught.exception))
        employers = self.employers()
        employers[0]["roles"][0]["title"] = "Manager, Firmware"
        with self.assertRaises(ValueError) as caught:
            self.draft("history", {"employers": employers})
        self.assertIn("comma", str(caught.exception))
        employers = self.employers()
        employers[0]["line"] = 999
        with self.assertRaises(ValueError) as caught:
            self.draft("history", {"employers": employers})
        self.assertIn("Reload", str(caught.exception))

    def test_a_row_added_and_left_empty_is_ignored(self):
        employers = [{"line": None, "name": "", "roles": [{"line": None, "title": "", "place": "", "start": "", "end": ""}]},
                     *self.employers()]
        self.assertEqual(self.draft("history", {"employers": employers})["changes"], {})

    # ---- Off limits ----

    def test_blocking_a_term_writes_the_line_and_the_pattern(self):
        result = self.draft("offlimits", {"never": {"add": ["Project Osprey"]}, "test": "Shipped Project-Ospreys."})
        self.assertIn("- Customer names\n- Project Osprey\n", lf(result, "facts"))
        forbidden = tomllib.loads(lf(result, "config"))["guard"]["forbidden"]
        self.assertEqual(forbidden[-1], "\\bProject[\\s-]?Ospreys?\\b")
        self.assertTrue(result["preview"]["test"]["blocked"])
        self.assertEqual(result["code"], [])

    def test_a_term_already_blocked_is_only_noted(self):
        result = self.draft("offlimits", {"never": {"add": ["Falconer"]}})
        self.assertEqual(result["changes"], {})
        self.assertIn("“Falconer” is blocked already.", result["notes"])

    def test_a_listed_but_unblocked_term_gets_only_a_pattern(self):
        facts = profile.read("facts").replace("- Customer names", "- Customer names, such as Globex")
        (self.root / "profile" / "facts.md").write_bytes(facts.encode())
        self.view = {**profile.view(), **steps.view()}
        self.assertEqual(self.view["off_limits_lists"]["unguarded"], ["Globex"])
        result = self.draft("offlimits", {"never": {"add": ["Globex"]}})
        self.assertEqual(set(result["changes"]), {"config"})
        self.assertEqual(result["preview"]["unguarded"], [])

    def test_taking_something_off_needs_a_code(self):
        line = self.view["off_limits_lists"]["nottrue"]["items"][0]["line"]
        result = self.draft("offlimits", {"nottrue": {"drop_items": [line], "drop_patterns": ["ISO 26262"]}})
        self.assertNotIn("Safety certification, including ISO 26262", lf(result, "facts"))
        self.assertEqual(len(result["code"]), 2, result["code"])

    def test_a_term_for_the_unsupported_list_goes_there(self):
        result = self.draft("offlimits", {"nottrue": {"add": ["Kubernetes"]}})
        self.assertIn("- Percentages for fleet uptime or field defect rates\n- Kubernetes\n", lf(result, "facts"))
        self.assertIn("  '\\bKubernetes\\b',\n]", lf(result, "config"))

    def test_patterns_that_would_block_everything_or_your_name_are_refused(self):
        for edits, message in (({"never": {"add_patterns": ["x?"]}}, "every draft"),
                               ({"never": {"add_patterns": ["(unclosed"]}}, "isn't a pattern"),
                               ({"never": {"add": ["Rivera"]}}, "your own name")):
            with self.assertRaises(ValueError) as caught:
                self.draft("offlimits", edits)
            self.assertIn(message, str(caught.exception))

    def test_term_patterns_catch_how_people_write_the_term(self):
        import re
        pattern = steps.term_pattern("SkyLift 900")
        for text in ("SkyLift 900", "skylift-900", "SkyLift900"):
            self.assertTrue(re.search(pattern, text, re.I), text)
        self.assertFalse(re.search(steps.term_pattern("the Hive"), "archive", re.I))
        self.assertTrue(re.search(steps.term_pattern("C++"), "Wrote C++ daily", re.I))

    # ---- Skills and terms ----

    def test_approving_a_term_appends_it_and_needs_a_code(self):
        result = self.draft("skills", {"add": ["Rust", "Zephyr RTOS", "CAN"]})
        self.assertTrue(lf(result, "terms").endswith("GitHub\nRust\nZephyr RTOS\n"))
        self.assertEqual(result["code"], ["approve “Rust” for every draft", "approve “Zephyr” for every draft"])
        self.assertTrue(any("a word at a time" in note for note in result["notes"]))
        self.assertIn("“CAN” is approved already.", result["notes"])

    def test_taking_a_term_off_leaves_the_others_on_its_line(self):
        (self.root / "profile" / "approved-terms.txt").write_bytes(b"# Tools\nGit, Jira Confluence\nRust\n")
        self.view = {**profile.view(), **steps.view()}
        groups = self.view["term_groups"]
        self.assertEqual(groups[0]["note"], "Tools")
        result = self.draft("skills", {"drop": [{"line": 1, "term": "Jira"}, {"line": 2, "term": "Rust"}]})
        self.assertEqual(lf(result, "terms"), "# Tools\nGit, Confluence\n")
        self.assertEqual(result["code"], [])
        with self.assertRaises(ValueError):
            self.draft("skills", {"drop": [{"line": 0, "term": "Tools"}]})

    # ---- the server ----

    def test_the_profile_page_and_the_draft_endpoint(self):
        page = server._profile_page()
        self.assertIn("term_groups", page)
        self.assertIn("history", page)
        result = server.PROFILE_WRITES["/api/profile/draft"](
            {"step": "skills", "edits": {"add": ["Rust"]}, "based_on": page["versions"]})
        self.assertEqual(result["count"], 1)
        self.assertFalse((self.root / "data" / "history").exists())  # A draft writes nothing.


if __name__ == "__main__":
    unittest.main()
