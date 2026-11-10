"""The Profile tab's section editors: each form drafted into the files a save would write, by the same code a save
uses, without writing anything. Also the pieces they lean on: changing one item in a TOML list, an employer's line,
and how the fact check reads one sentence."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
import urllib.error
from contextlib import closing
from pathlib import Path
from typing import Any

import support  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import checks, discover, doctor, factsdoc, profile, server, sources, steps, store, tomledit, workspace

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"


def lf(result: dict[str, Any], key: str) -> str:
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

    def test_an_items_own_comment_goes_with_it(self):
        text = "[guard]\nforbidden = [\n  'Alpha',  # about Alpha\n  'Beta',   # about Beta\n  'Gamma'  # about Gamma\n]\n"
        new = tomledit.edit_list(text, "guard", "forbidden", remove=["Beta"])
        self.assertEqual(new, "[guard]\nforbidden = [\n  'Alpha',  # about Alpha\n  'Gamma'  # about Gamma\n]\n")
        new = tomledit.edit_list(text, "guard", "forbidden", remove=["Gamma"])
        self.assertEqual(new, "[guard]\nforbidden = [\n  'Alpha',  # about Alpha\n  'Beta',   # about Beta\n]\n")

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

    def roles_form(self) -> dict[str, Any]:
        """Roles you want's form as the page first fills it in: everything as it is."""
        roles = self.view["roles"]
        return {"tracks": [{key: track[key] for key in ("index", "name", "titles", "patterns", "needs_level", "emphasis")}
                           for track in roles["tracks"]],
                **{key: list(roles[key]) for key in ("level_top", "level_mid", "exclude_titles")},
                "keywords": [list(row) for row in roles["keywords"]], "flags": [list(row) for row in roles["flags"]]}

    def test_an_unchanged_form_writes_nothing(self):
        lists = self.view["off_limits_lists"]
        for step, edits in (
            ("basics", {"name": self.view["basics"]["name"], "paper": "letter",
                        "contact": [p["text"] for p in self.view["contact_parts"]["parts"]]}),
            ("history", {"employers": self.employers(), "other": self.view["timeline"]["other"],
                         "expected": self.view["expected"]}),
            ("offlimits", {"never": {}, "nottrue": {}}),
            ("skills", {"add": [], "drop": []}),
            ("achievements", {"sections": [{"line": s["line"], "title": s["title"],
                                            "items": [{"line": i["line"], "text": i["text"]} for i in s["items"] if i["level"] == 0]}
                                           for s in self.view["sections"] if s["kind"] == "facts"], "wording": []}),
            ("masters", {"resume": {"headline": self.view["master_blocks"]["resume"]["headline"],
                                    "blocks": self.view["master_blocks"]["resume"]["blocks"]},
                         "letter": {"body": self.view["master_blocks"]["letter"]["body"]}}),
            ("where", {key: self.view["where"][key] for key in
                       ("places", "local", "local_exact", "accept_remote", "accept_relocation", "market")}),
            ("roles", self.roles_form()),
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
            self.draft("priorities", {})

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

    def test_an_employer_the_resume_already_names_isnt_added_to_it_twice(self):
        # As after `import-resume`: the master resume has the employer and its bullets, and the Timeline doesn't yet.
        resume = profile.read("resume").replace("\r\n", "\n").replace(
            "## Experience\n", "## Experience\n### Initech\n#### Staff Engineer | Remote | Dec 2026 – Present\n- Shipped the thing\n"
                               "#### Engineer | Jan 2025 – Nov 2026\n", 1)
        (self.root / "profile" / "resume.md").write_bytes(resume.encode())
        self.view = {**profile.view(), **steps.view()}
        employers = [{"line": None, "name": "Initech", "roles": [
            {"title": "Staff Engineer", "place": "Remote", "start": "Dec 2026", "end": ""},
            {"title": "Engineer", "place": "Austin, TX", "start": "Jan 2025", "end": "Nov 2026"},
            {"title": "Intern", "place": "", "start": "Jun 2024", "end": "Dec 2024"}]}, *self.employers()]
        result = self.draft("history", {"employers": employers})
        self.assertIn("- **Initech, Jun 2024 – Present**\n", lf(result, "facts"))
        after = lf(result, "resume")
        self.assertEqual(after.count("### Initech"), 1, after)
        self.assertIn("## Experience\n### Initech\n#### Staff Engineer | Remote | Dec 2026 – Present\n- Shipped the thing\n"
                      "#### Engineer | Austin, TX | Jan 2025 – Nov 2026\n#### Intern | Jun 2024 – Dec 2024\n", after)

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
        # Blocked by name already: the test box shows it, as a draft's check would.
        self.assertEqual(self.view["off_limits_lists"]["by_name"], {"blocked": ["Globex"], "shared": []})
        tested = self.draft("offlimits", {"test": "Shipped it for Globex."})["preview"]["test"]
        self.assertTrue(tested["blocked"])
        result = self.draft("offlimits", {"never": {"add": ["Globex"]}})
        self.assertEqual(set(result["changes"]), {"config"})
        self.assertEqual(result["preview"]["by_name"], {"blocked": [], "shared": []})

    def test_a_listed_name_your_sources_also_state_is_shown_as_not_blocked(self):
        facts = profile.read("facts").replace("- Customer names", "- Customer names, such as Globex").replace(
            "- Hired 4 engineers", "- Ran the Globex pilot\n- Hired 4 engineers")
        (self.root / "profile" / "facts.md").write_bytes(facts.encode())
        self.view = {**profile.view(), **steps.view()}
        self.assertEqual(self.view["off_limits_lists"]["by_name"], {"blocked": [], "shared": ["Globex"]})
        self.assertFalse(self.draft("offlimits", {"test": "Shipped it for Globex."})["preview"]["test"]["blocked"])

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

    # ---- Achievements ----

    def fact_sections(self):
        return [{"line": s["line"], "title": s["title"],
                 "items": [{"line": i["line"], "text": i["text"]} for i in s["items"] if i["level"] == 0]}
                for s in self.view["sections"] if s["kind"] == "facts"]

    def test_facts_change_one_line_at_a_time(self):
        sections = self.fact_sections()
        sections[0]["items"][1]["text"] = "Cut motion-controller boot time from 42 s to 9 s on the production fleet"
        del sections[1]["items"][2]
        sections[1]["items"].insert(0, {"line": None, "text": "Mentored 3 interns"})
        result = self.draft("achievements", {"sections": sections})
        facts = lf(result, "facts")
        self.assertIn("- Cut motion-controller boot time from 42 s to 9 s on the production fleet\n", facts)
        self.assertIn("## Leadership\n- Mentored 3 interns\n- Managed a team of 7", facts)
        self.assertNotIn("Software lead on 3 robot launches", facts)
        self.assertEqual(result["count"], 3)
        self.assertEqual(set(result["changes"]), {"facts"})

    def test_a_new_section_goes_before_the_ones_that_approve_nothing(self):
        sections = [*self.fact_sections(), {"line": None, "title": "Patents", "items": [{"line": None, "text": "US 1,234,567"}]}]
        facts = lf(self.draft("achievements", {"sections": sections}), "facts")
        self.assertLess(facts.index("## Patents\n- US 1,234,567\n"), facts.index("## Do not use"))

    def test_sections_that_would_read_as_something_else_are_refused(self):
        for title, message in (("Do not use either", "may not claim"), ("Timeline 2", "timeline section"),
                               ("Leadership", "already")):
            sections = [*self.fact_sections(), {"line": None, "title": title, "items": [{"line": None, "text": "x"}]}]
            with self.assertRaises(ValueError) as caught:
                self.draft("achievements", {"sections": sections})
            self.assertIn(message, str(caught.exception))

    def test_a_fact_naming_a_blocked_term_is_noted(self):
        sections = self.fact_sections()
        sections[0]["items"].append({"line": None, "text": "Brought up the SkyLift 900 drive"})
        notes = self.draft("achievements", {"sections": sections})["notes"]
        self.assertTrue(any("Never mention" in note for note in notes), notes)

    def test_the_builder_writes_one_line_and_its_wording_rule(self):
        built = steps.compose({"did": "Cut nightly regression time", "before": "6 hours", "after": "50 minutes",
                               "where": "on the shared CI farm", "role": "Senior Firmware Engineer"})
        self.assertEqual(built["text"], "Cut nightly regression time from 6 hours to 50 minutes on the shared CI farm")
        self.assertEqual(built["flags"], [])
        sections = self.fact_sections()
        sections[0]["items"].append({"line": None, "text": built["text"]})
        result = self.draft("achievements", {"sections": sections, "wording": [{"keep": built["where"], "fact": built["text"]}]})
        notes = lf(result, "run_notes")
        self.assertIn('in a pilot of 8 engineers".\n  - Keep “on the shared CI farm” with “Cut nightly regression time', notes)
        self.save(result)
        self.assertEqual(len(self.view["wording"]), 2)

    def test_the_builder_flags_what_reads_badly(self):
        flags = steps.compose({"did": "Helped significantly", "after": "30%", "role": "Senior Firmware Engineer"})["flags"]
        self.assertEqual(len(flags), 2, flags)
        flags = steps.compose({"did": "Managed the bench", "after": "212 tests", "role": "Senior Firmware Engineer"})["flags"]
        self.assertTrue(any("management title" in flag for flag in flags), flags)
        self.assertEqual(steps.compose({"did": "Led 3 launches", "role": "Firmware Engineering Manager"})["flags"], [])

    def test_wording_rules_start_run_notes_when_there_are_none(self):
        self.assertEqual(steps._add_wording("", ["Keep “x” with “y”."]), "# Run notes\n\n- **Wording:**\n  - Keep “x” with “y”.\n")
        self.assertIn("\n- **Wording:**\n  - r\n", steps._add_wording("# Run notes\n\n- **Who:** me\n", ["r"]))

    # ---- Master resume ----

    def test_the_master_is_read_a_block_at_a_time(self):
        blocks = self.view["master_blocks"]["resume"]["blocks"]
        self.assertEqual([b["heading"] for b in blocks[:3]], ["Summary", "Skills", "Experience"])
        self.assertTrue(self.view["master_blocks"]["letter"]["body"].startswith("Dear Hiring Manager,"))

    def test_a_block_and_the_headline_change_and_the_headings_stay(self):
        blocks = self.view["master_blocks"]["resume"]["blocks"]
        summary = next(b for b in blocks if b["heading"] == "Summary")
        result = self.draft("masters", {"resume": {"headline": "Principal Firmware Engineer",
                                                   "blocks": [{"line": summary["line"], "text": "Builds robot firmware.\n"}]}})
        resume = lf(result, "resume")
        self.assertIn("# Alex Rivera\n= Principal Firmware Engineer\n@ ", resume)
        self.assertIn("## Summary\nBuilds robot firmware.\n\n## Skills\n", resume)
        self.assertEqual(result["preview"]["resume"]["errors"], [])

    def test_the_letter_body_changes_under_the_name_and_contact(self):
        body = self.view["master_blocks"]["letter"]["body"].replace("Dear Hiring Manager,", "Dear hiring team,")
        letter = lf(self.draft("masters", {"letter": {"body": body}}), "letter")
        self.assertTrue(letter.startswith("# Alex Rivera\n@ Madison, WI"))
        self.assertIn("\n\nDear hiring team,\n", letter)

    def test_the_fact_check_runs_on_the_draft(self):
        summary = next(b for b in self.view["master_blocks"]["resume"]["blocks"] if b["heading"] == "Summary")
        result = self.draft("masters", {"resume": {"blocks": [{"line": summary["line"], "text": summary["text"] + " Led the Bluebird launch. Cut boot time by 77%."}]}})
        checked = result["preview"]["resume"]
        self.assertTrue(any("Bluebird" in error for error in checked["errors"]), checked)
        self.assertTrue(any("77%" in only for only in checked["only_here"]), checked)

    def test_a_heading_cant_be_typed_into_a_block(self):
        summary = next(b for b in self.view["master_blocks"]["resume"]["blocks"] if b["heading"] == "Summary")
        for text in ("## Sneaky\nx", "### Initech | 2020 – 2021", "@ me@example.com"):
            with self.assertRaises(ValueError):
                self.draft("masters", {"resume": {"blocks": [{"line": summary["line"], "text": text}]}})

    def test_without_a_master_there_is_nothing_to_change(self):
        (self.root / "profile" / "resume.md").unlink()
        self.view = {**profile.view(), **steps.view()}
        self.assertFalse(self.view["master_blocks"]["resume"]["exists"])
        with self.assertRaises(ValueError):
            self.draft("masters", {"resume": {"headline": "x"}})

    # ---- Where you'll work ----

    def where(self, **changes):
        form = {key: self.view["where"][key] for key in
                ("places", "local", "local_exact", "accept_remote", "accept_relocation", "market")}
        return self.draft("where", {**form, **changes})

    def test_where_shows_the_patterns_and_the_area(self):
        where = self.view["where"]
        self.assertEqual(where["places"], [])
        self.assertIn("sun prairie", where["local"])
        self.assertIn(", WI\\b", where["local_exact"])
        self.assertEqual((where["accept_remote"], where["accept_relocation"]), (True, False))
        self.assertEqual(where["market"], {"state": "Wisconsin", "metro": "Madison, WI", "country": ""})
        self.assertIsNone(where["remote_home"])

    def test_an_unchanged_where_leaves_search_toml_byte_for_byte(self):
        before = (self.root / "profile" / "search.toml").read_bytes()
        result = self.where(test="Remote - US")
        self.assertEqual((result["changes"], result["count"]), ({}, 0))
        # The hand-written patterns, given back in another order, are no change either.
        self.assertEqual(self.where(local=self.view["where"]["local"][::-1])["changes"], {})
        self.assertEqual((self.root / "profile" / "search.toml").read_bytes(), before)

    def test_adding_places_keeps_the_patterns_and_comments(self):
        result = self.where(places=["Springfield, IL", "Oak Park", "oak park", " "])
        config = lf(result, "config")
        self.assertIn('accept_relocation = false # onsite roles elsewhere are dropped\nplaces = ["Springfield, IL", "Oak Park"]\n', config)
        self.assertIn("# Either or both will do. Madison is tied to Wisconsin here", config)
        self.assertEqual(tomllib.loads(config)["location"]["local"], self.view["where"]["local"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["code"], [])  # Where you'll work never lets a draft say more.
        self.save(result)
        self.assertEqual(self.view["where"]["places"], ["Springfield, IL", "Oak Park"])
        config = lf(self.where(places=["Oak Park"]), "config")
        self.assertIn('places = ["Oak Park"]\n', config)

    def test_a_place_written_without_brackets_becomes_a_list(self):
        path = self.root / "profile" / "search.toml"
        path.write_bytes(path.read_bytes().replace(b"accept_remote = true", b'places = "Oak Park"\naccept_remote = true'))
        self.view = {**profile.view(), **steps.view()}
        self.assertEqual(self.view["where"]["places"], ["Oak Park"])
        self.assertEqual(tomllib.loads(lf(self.where(places=["Oak Park", "Evanston"]), "config"))["location"]["places"],
                         ["Oak Park", "Evanston"])

    def test_patterns_and_toggles_change_a_key_at_a_time(self):
        local = [p for p in self.view["where"]["local"] if p != "verona"] + ["\\bfitchburg\\b"]
        result = self.where(local=local, accept_remote=False, accept_relocation=True)
        config = lf(result, "config")
        self.assertIn("accept_remote = false      # US remote roles count\n", config)
        self.assertIn("accept_relocation = true # onsite roles elsewhere are dropped\n", config)
        self.assertIn("  '\\bfitchburg\\b',\n]", config)
        self.assertNotIn("'verona'", config)
        self.assertEqual(result["count"], 4)

    def test_the_area_for_the_industries_tab(self):
        result = self.where(market={"state": "Illinois", "metro": "", "country": "United States"})
        config = lf(result, "config")
        self.assertIn('[market]\nstate = "Illinois"\ncountry = "United States"\n', config)
        self.assertNotIn("metro =", config)
        self.assertIn('# model = "claude-sonnet-5-5"', config)  # Settings' key, left alone.
        notes = self.where(market={"state": "Ontario", "metro": "", "country": "Canada"})["notes"]
        self.assertTrue(any("United States only" in note for note in notes), notes)

    def test_a_bad_area_is_named_from_the_bls_list_when_pyrite_has_it(self):
        titles = {"17000": "Illinois -- Statewide", "C4418": "Springfield, IL MSA"}
        with mock.patch.object(steps.market, "_fresh", return_value=True), \
                mock.patch.object(steps.market, "area_titles", return_value=titles):
            self.assertEqual(self.where(market={"state": "Illinois", "metro": "Springfield, IL"})["notes"], [])
            notes = self.where(market={"state": "Illinoise", "metro": "Springfield"})["notes"]
        self.assertTrue(any("no state is called 'Illinoise'" in note for note in notes), notes)

    def test_a_location_is_judged_with_the_settings_as_drafted(self):
        for text, kind, why in (("Remote - US", "remote", "remote role open to you"),
                                ("Madison, Wisconsin", "local", "madison"),
                                ("Springfield, Illinois", "out", "won't relocate"),
                                ("Remote - Germany", "out", "open only somewhere else")):
            tested = self.where(test=text)["preview"]["test"]
            self.assertEqual((tested["now"], tested["after"]), (kind, kind), text)
            self.assertIn(why, tested["why"], text)
        tested = self.where(places=["Springfield, IL"], test="Springfield, Illinois")["preview"]["test"]
        self.assertEqual((tested["now"], tested["after"]), ("out", "local"))
        self.assertIn("“Springfield, IL”", tested["why"])
        tested = self.where(accept_remote=False, test="Remote - US")["preview"]["test"]
        self.assertEqual((tested["now"], tested["after"]), ("remote", "out"))

    def test_the_prospects_are_counted_before_and_after(self):
        path = self.root / "data" / "pyrite.db"
        with closing(store.connect(path)) as conn:
            for index, (location, status, source) in enumerate((
                    ("Madison, WI", "new", "greenhouse:a"), ("Remote - US", "new", "greenhouse:a"),
                    ("Springfield, IL", "new", "lever:b"), ("Springfield, IL", "applied", "lever:b"),
                    ("Springfield, IL", "new", "manual"))):
                conn.execute("INSERT INTO jobs (source_key, source_id, company, title, location, status, first_seen, last_seen) "
                             "VALUES (?, ?, 'Acme', 'Staff Engineer', ?, ?, '', '')", (source, str(index), location, status))
            conn.commit()
        with mock.patch.object(store, "DB_PATH", path):
            found = self.where(places=["Springfield, IL"], accept_remote=False)["preview"]["prospects"]
            self.assertEqual(found["total"], 3)  # Only prospects from the boards: not sent, and not added by hand.
            self.assertEqual((found["now"]["local"], found["now"]["remote"], found["now"]["out"]), (1, 1, 1))
            self.assertEqual((found["after"]["local"], found["after"]["remote"], found["after"]["out"]), (2, 0, 1))
            self.assertEqual([(m["location"], m["now"], m["after"]) for m in found["moves"]],
                             [("Remote - US", "remote", "out"), ("Springfield, IL", "out", "local")])
            notes = self.where(places=["Springfield, IL"])["notes"]
            self.assertTrue(any("pyrite rescore" in note for note in notes), notes)
        with mock.patch.object(store, "DB_PATH", self.root / "data" / "none.db"):
            self.assertIsNone(self.where()["preview"]["prospects"])
        self.assertFalse((self.root / "data" / "none.db").exists())

    def test_bad_where_input_is_refused(self):
        for changes in ({"places": "Oak Park"}, {"places": ["Oak\nPark"]}, {"places": ["--"]}, {"places": ["x" * 200]},
                        {"local": ["(unclosed"]}, {"local": [".*"]}, {"local_exact": [3]}, {"accept_remote": "yes"},
                        {"market": "Illinois"}, {"market": {"state": "Illi\nnois"}}):
            with self.assertRaises(ValueError, msg=changes):
                self.where(**changes)
        # A hand-written pattern already in the file is kept as it is, even one the form wouldn't take today.
        self.assertEqual(self.where(local=self.view["where"]["local"])["changes"], {})

    def test_where_says_what_it_holds_on_the_hub(self):
        step = next(s for s in profile.view()["steps"] if s["id"] == "where")
        self.assertEqual(step["summary"], "11 local places, remote")
        self.assertNotIn("Until it's built", step["meanwhile"])

    # ---- Roles you want ----

    def track(self, form: dict[str, Any], name: str) -> dict[str, Any]:
        return next(t for t in form["tracks"] if t["name"] == name)

    def test_role_types_are_read_with_their_patterns_and_emphasis(self):
        roles = self.view["roles"]
        self.assertEqual([t["name"] for t in roles["tracks"]], ["AI systems", "Embedded, controls and simulation",
                                                                 "Engineering leadership", "Technical program and product"])
        lead = roles["tracks"][2]
        self.assertEqual((lead["titles"], len(lead["patterns"]), lead["needs_level"]), ([], 3, False))
        self.assertEqual(lead["emphasis"], "team management, hiring and launches lead.")
        self.assertIn("junior", roles["exclude_titles"])
        self.assertNotIn("Until it's built", next(s for s in profile.STEPS if s["id"] == "roles")["meanwhile"])
        self.assertIn('src="/static/profile/roles.js"', (server.STATIC / "index.html").read_text(encoding="utf-8"))

    def test_an_unchanged_roles_form_leaves_every_file_byte_for_byte(self):
        before = {key: (self.root / path).read_bytes() for key, path in profile.FILES.items() if (self.root / path).exists()}
        result = self.draft("roles", {**self.roles_form(), "test": "Staff Firmware Engineer"})
        self.assertEqual((result["changes"], result["count"], result["notes"]), ({}, 0, []))
        self.assertEqual(result["preview"]["test"]["track"], "Embedded, controls and simulation")
        self.assertEqual(before, {key: (self.root / path).read_bytes() for key, path in profile.FILES.items()
                                  if (self.root / path).exists()})

    def test_a_new_role_type_is_written_with_plain_titles_and_comments_stay(self):
        form = self.roles_form()
        form["tracks"].append({"index": None, "name": "Data platform", "titles": ["data engineer", "Analytics Engineer"],
                               "patterns": [], "needs_level": True, "emphasis": "the pipeline rewrite leads"})
        result = self.draft("roles", {**form, "test": "Staff Data Engineer"})
        config = lf(result, "config")
        self.assertIn('[[track]]\nname = "Data platform"\ntitles = ["data engineer", "Analytics Engineer"]\nneeds_level = true\n\n[scoring]', config)
        before = profile.read("config").replace("\r\n", "\n")
        # Every other line, the comments and the hand-written patterns among them, is as it was.
        self.assertEqual(config.replace('\n[[track]]\nname = "Data platform"\ntitles = ["data engineer", "Analytics Engineer"]\nneeds_level = true\n', ""), before)
        self.assertIn("  - *Data platform:* the pipeline rewrite leads\n- **Wording:**", lf(result, "run_notes"))
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["preview"]["test"]["track"], "Data platform")
        self.assertEqual(result["code"], [])
        self.save(result)
        added = self.track(self.roles_form(), "Data platform")
        self.assertEqual((added["titles"], added["patterns"], added["emphasis"]),
                         (["data engineer", "Analytics Engineer"], [], "the pipeline rewrite leads"))
        self.assertEqual(self.draft("roles", self.roles_form())["changes"], {})

    def test_a_plain_title_goes_beside_the_patterns_which_stay(self):
        form = self.roles_form()
        lead = self.track(form, "Engineering leadership")
        lead["titles"].append("chief technology officer")
        result = self.draft("roles", form)
        config = tomllib.loads(lf(result, "config"))
        track = next(t for t in config["track"] if t["name"] == "Engineering leadership")
        self.assertEqual(track["titles"], ["chief technology officer"])
        self.assertEqual(track["title"], tomllib.loads(profile.read("config"))["track"][2]["title"])
        self.assertEqual(set(result["changes"]), {"config"})
        diff = [line for d in result["diffs"] for line in d["lines"] if line[:1] in "+-"]
        self.assertEqual(diff, ['+titles = ["chief technology officer"]'])

    def test_a_role_type_taken_off_takes_its_emphasis_and_others_stay(self):
        form = self.roles_form()
        form["tracks"] = [t for t in form["tracks"] if t["name"] != "Engineering leadership"]
        result = self.draft("roles", form)
        config = lf(result, "config")
        self.assertNotIn("Engineering leadership", config)
        before = profile.read("config").replace("\r\n", "\n")
        for track in tomllib.loads(before)["track"]:
            if track["name"] != "Engineering leadership":
                self.assertIn(f'name = "{track["name"]}"', config)
        self.assertIn("# Roles to pursue.", config)
        self.assertNotIn("Engineering leadership", lf(result, "run_notes"))
        self.assertIn("*Technical program and product:*", lf(result, "run_notes"))
        self.assertEqual(result["count"], 2)

    def test_renaming_and_reordering_follow_through_to_run_notes(self):
        form = self.roles_form()
        form["tracks"].reverse()
        self.track(form, "AI systems")["name"] = "Applied AI"
        result = self.draft("roles", form)
        config = tomllib.loads(lf(result, "config"))
        self.assertEqual([t["name"] for t in config["track"]], ["Technical program and product", "Engineering leadership",
                                                                 "Embedded, controls and simulation", "Applied AI"])
        self.assertIn("  - *Applied AI:* the coding-agent workflow", lf(result, "run_notes"))
        self.assertEqual(result["count"], 3)  # the order, the rename, and its emphasis line

    def test_comments_inside_a_role_type_survive_editing_it(self):
        text = profile.read("config").replace("\r\n", "\n").replace('name = "AI systems"\n', 'name = "AI systems"  # the main one\n# Kept narrow on purpose.\n')
        (self.root / "profile" / "search.toml").write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}
        form = self.roles_form()
        ai = self.track(form, "AI systems")
        ai["needs_level"] = False
        ai["patterns"] = ai["patterns"][:1]
        result = self.draft("roles", form)
        config = lf(result, "config")
        self.assertIn('name = "AI systems"  # the main one\n# Kept narrow on purpose.\ntitle = [', config)
        self.assertEqual(len(tomllib.loads(config)["track"][0]["title"]), 1)
        self.assertFalse(tomllib.loads(config)["track"][0]["needs_level"])

    def test_windows_line_endings_are_kept(self):
        text = profile.read("config").replace("\r\n", "\n").replace("\n", "\r\n")
        (self.root / "profile" / "search.toml").write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}
        self.assertEqual(self.draft("roles", self.roles_form())["changes"], {})
        form = self.roles_form()
        form["tracks"].insert(0, {"index": None, "name": "Data platform", "titles": ["data engineer"], "patterns": [],
                                  "needs_level": False, "emphasis": ""})
        form["exclude_titles"].append("trainee")
        config = self.draft("roles", form)["changes"]["config"]
        self.assertEqual(config.count("\n"), config.count("\r\n"))
        self.assertEqual(tomllib.loads(config)["track"][0]["name"], "Data platform")

    def test_title_lists_change_a_word_at_a_time(self):
        form = self.roles_form()
        form["exclude_titles"].remove("payments?")
        form["exclude_titles"].append("trainee")
        form["level_mid"].append("experienced")
        result = self.draft("roles", form)
        diff = [line for d in result["diffs"] for line in d["lines"] if line[:1] in "+-"]
        self.assertIn("+  'trainee',", diff)
        self.assertIn("+level_mid = ['senior', 'sr', 'lead', 'experienced']", diff)
        self.assertEqual(result["count"], 3)
        self.assertNotIn("payments?", tomllib.loads(lf(result, "config"))["scoring"]["exclude_titles"])

    def test_skill_points_and_flags_are_written_a_row_to_a_line(self):
        form = self.roles_form()
        form["keywords"][0][1] = "8"
        form["flags"].append(["Travel", "travel (up to )?\\d+%", 5])
        result = self.draft("roles", form)
        scoring = tomllib.loads(lf(result, "config"))["scoring"]
        self.assertEqual(scoring["keywords"][0], ["embedded", 8])
        self.assertEqual(scoring["flags"][-1], ["Travel", "travel (up to )?\\d+%", 5])
        self.assertIn("keywords = [\n  ['embedded', 8],\n  ['firmware', 6],\n", lf(result, "config"))
        self.assertEqual(result["count"], 3)

    def test_what_the_filters_would_never_take_is_pointed_out(self):
        form = self.roles_form()
        self.track(form, "Technical program and product")["titles"] += ["sales engineer", "software program manager"]
        notes = self.draft("roles", form)["notes"]
        self.assertTrue(any("“sales engineer” has 'sales' in it" in note for note in notes), notes)
        self.assertTrue(any(note.startswith("Engineering leadership takes “software program manager” first") for note in notes), notes)
        self.assertTrue(any("pyrite rescore" in note for note in notes))

    def test_trying_a_title_says_why(self):
        tried = steps.try_title("Data Engineer", tomllib.loads(profile.read("config")))
        self.assertEqual((tried["track"], tried["tracks"]), (None, []))
        form = self.roles_form()
        form["tracks"].append({"index": None, "name": "Data platform", "titles": ["data engineer"], "patterns": [],
                               "needs_level": True, "emphasis": ""})
        tried = self.draft("roles", {**form, "test": "Data Engineer"})["preview"]["test"]
        self.assertIsNone(tried["track"])
        self.assertEqual(tried["tracks"], [{"name": "Data platform", "plain": "data engineer", "pattern": None,
                                            "why": "it has no senior word, which this role type needs"}])
        tried = self.draft("roles", {**form, "test": "Senior Sales Engineer"})["preview"]["test"]
        self.assertEqual((tried["track"], tried["excluded"], tried["level"]), (None, "sales", "mid"))

    def test_a_new_workspace_with_no_role_types_opens_roles_without_an_error(self):
        # Opening the section drafts the form as it is to preview the prospects, so having none yet isn't refused.
        blank = workspace.blank_config((EXAMPLE_PROFILE / "search.toml").read_text(encoding="utf-8"), "Sam Doe")
        profile.write({"config": blank}, self.view["versions"], "test")
        self.view = {**profile.view(), **steps.view()}
        self.assertEqual(self.view["roles"]["tracks"], [])
        result = self.draft("roles", self.roles_form())
        self.assertEqual((result["changes"], result["count"]), ({}, 0))

    def test_bad_roles_are_refused(self):
        def tracks(**change):
            form = self.roles_form()
            form["tracks"][0].update(change)
            return form
        new = {"index": None, "name": "Data platform", "titles": ["data engineer"], "patterns": [], "needs_level": False}
        for form, message in (
            (tracks(name=" "), "needs a name"),
            (tracks(name="Engineering Leadership"), "two role types"),
            (tracks(titles=[], patterns=[]), "at least one job title"),
            (tracks(patterns=["(unclosed"]), "isn't a pattern"),
            (tracks(patterns=[".*"]), "any title at all"),
            (tracks(titles=["--"]), "no words"),
            (tracks(name="AI *systems*"), "formatting"),
            (tracks(index=9), "Reload"),
            ({**self.roles_form(), "tracks": []}, "at least one role type"),
            ({**self.roles_form(), "tracks": [new, {**new, "name": "Other"}, {**self.roles_form()["tracks"][0], "index": 0},
                                              {**self.roles_form()["tracks"][0], "index": 0, "name": "Again"}]}, "Reload"),
            ({**self.roles_form(), "exclude_titles": ["\\w*"]}, "any title at all"),
            ({**self.roles_form(), "keywords": [["rust", 500]]}, "from 0 to 100"),
            ({**self.roles_form(), "keywords": [["rust", "lots"]]}, "whole number"),
            ({**self.roles_form(), "flags": [["", "travel", 5]]}, "needs a label"),
            ({**self.roles_form(), "tracks": "AI"}, "should be a list"),
        ):
            with self.assertRaises(ValueError, msg=message) as caught:
                self.draft("roles", form)
            self.assertIn(message, str(caught.exception))
        # A new row added and left blank is no change, not a refusal.
        form = self.roles_form()
        form["tracks"].append({"index": None, "name": "", "titles": [], "patterns": [], "needs_level": False})
        form["keywords"].append(["", ""])
        self.assertEqual(self.draft("roles", form)["changes"], {})

    def prospects(self) -> Path:
        """A database of prospects at the workspace's own path, for the preview to read."""
        path = self.root / "data" / "pyrite.db"
        patcher = mock.patch.object(store, "DB_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        conn = store.connect(path)
        ts = store.now()
        jobs = [("greenhouse:a", "1", "Initech", "Firmware Engineering Manager", "Middleton, WI", "", 70),
                ("greenhouse:a", "2", "Initech", "Director of Software Engineering", "Madison, WI", "", 60),
                ("greenhouse:b", "3", "Hooli", "Principal Embedded Software Engineer", "Remote - US", "", 77),
                ("greenhouse:b", "4", "Hooli", "Senior Engineering Manager, Platform", "Madison, WI", "Call back", 66),
                ("manual", "5", "Globex", "Director of Engineering", "Madison, WI", "", 50)]
        for key, source_id, company, title, place, notes, score in jobs:
            conn.execute("INSERT INTO jobs (source_key, source_id, company, title, location, description, first_seen, "
                         "last_seen, status, status_changed_at, score, track, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, ?)",
                         (key, source_id, company, title, place, "Firmware and controls for robots, in C++.", ts, ts, ts,
                          score, "Engineering leadership", notes))
        conn.commit()
        conn.close()
        return path

    def test_the_preview_scores_the_prospects_as_a_rescore_would(self):
        path = self.prospects()
        self.assertEqual(self.draft("roles", self.roles_form())["preview"]["prospects"]["total"], 4)
        form = self.roles_form()
        form["tracks"] = [t for t in form["tracks"] if t["name"] != "Engineering leadership"]
        before = path.read_bytes()
        prospects = self.draft("roles", form)["preview"]["prospects"]
        self.assertEqual((prospects["total"], prospects["kept"], prospects["held"]), (4, 2, 1))
        self.assertEqual({(j["title"], j["held"]) for j in prospects["dropped"]},
                         {("Director of Software Engineering", False), ("Senior Engineering Manager, Platform", True)})
        self.assertTrue(all(j["why"] == "no role type takes its title" for j in prospects["dropped"]))
        self.assertFalse(any(j["already"] for j in prospects["dropped"]))
        # The stored scores aren't what these settings give, but the change is judged against the settings as they are,
        # so it moves no score of its own.
        self.assertEqual(prospects["moved"], [])
        changed = self.roles_form()
        changed["keywords"][1][1] = 0  # firmware
        moved = self.draft("roles", changed)["preview"]["prospects"]["moved"]
        self.assertEqual(len(moved), 4)
        self.assertTrue(all(j["after"] == j["before"] - 6 for j in moved), moved)
        self.assertEqual(path.read_bytes(), before)  # Read only: a draft changes nothing.
        # The same as `pyrite rescore` makes of them.
        with mock.patch.object(store, "ROOT", self.root):
            conn = store.connect(path)
            try:
                cfg = tomllib.loads(lf(self.draft("roles", form), "config"))
                done = steps.discover.rescore(conn, {**support.CFG, "track": cfg["track"]})
            finally:
                conn.close()
        self.assertEqual((done["kept"], done["dropped"], done["held"]), (3, 1, 1))  # kept counts the one you added

    def test_a_preview_without_prospects_says_so(self):
        with mock.patch.object(store, "DB_PATH", self.root / "data" / "none.db"):
            form = self.roles_form()
            form["exclude_titles"].append("trainee")
            prospects = self.draft("roles", form)["preview"]["prospects"]
        self.assertEqual((prospects["total"], prospects["changed"]), (0, True))
        self.assertFalse((self.root / "data" / "none.db").exists())

    # ---- the server ----

    def test_the_profile_page_and_the_draft_endpoint(self):
        page = server._profile_page()
        self.assertIn("term_groups", page)
        self.assertIn("history", page)
        self.assertEqual(len(page["roles"]["tracks"]), 4)
        result = server.PROFILE_WRITES["/api/profile/draft"](
            {"step": "skills", "edits": {"add": ["Rust"]}, "based_on": page["versions"]})
        self.assertEqual(result["count"], 1)
        self.assertFalse((self.root / "data" / "history").exists())  # A draft writes nothing.


class Companies(unittest.TestCase):
    """Companies to watch: [watch.*], [[manual_check]] and [workday] queries, a key at a time, and the boards a
    pasted address names. Nothing here reaches the network: Test's reads are stood in for."""
    setUp = Steps.setUp
    draft = Steps.draft
    save = Steps.save

    def config(self) -> str:
        return profile.read("config")

    def form(self, **change) -> dict[str, Any]:
        """The section's form as the page first sends it, with `change` in place of any part."""
        companies = self.view["companies"]
        return {
            "boards": [{part: board[part] for part in ("was", "kind", "key", "name", "wd", "site")} for board in companies["boards"]],
            "manual": [dict(entry) for entry in companies["manual"]],
            "queries": list(companies["queries"]),
            "paste": "",
            **change,
        }

    def rewrite(self, text: str) -> None:
        (self.root / "profile" / "search.toml").write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}

    def test_an_unchanged_form_leaves_search_toml_byte_for_byte(self):
        result = self.draft("companies", self.form())
        self.assertEqual((result["changes"], result["count"]), ({}, 0))
        companies = self.view["companies"]
        self.assertEqual([(b["kind"], b["key"], b["name"]) for b in companies["boards"]], [("greenhouse", "anthropic", "Anthropic")])
        self.assertEqual([m["name"] for m in companies["manual"]], ["LinkedIn"])
        self.assertTrue(companies["queries"])
        # A Workday entry written the wrong way is shown as it is, and left alone while it isn't touched.
        self.rewrite(self.config().replace("[watch.workday]", '[watch.workday]\nglobex = "Globex"', 1))
        board = next(b for b in self.view["companies"]["boards"] if b["key"] == "globex")
        self.assertIn("needs a name, wd and site", board["problem"])
        self.assertEqual(self.draft("companies", self.form())["changes"], {})

    def test_each_kind_of_board_is_added_and_taken_off_and_the_file_comes_back_as_it_was(self):
        before = self.config()
        new = [
            {"was": None, "kind": "greenhouse", "key": "initech", "name": "Initech"},
            {"was": None, "kind": "lever", "key": "globex-robotics", "name": "Globex Robotics"},
            {"was": None, "kind": "ashby", "key": "Hooli", "name": "Hooli"},
            {"was": None, "kind": "workday", "key": "umbrella", "wd": "wd5", "site": "Careers", "name": "Umbrella"},
        ]
        result = self.draft("companies", self.form(boards=self.form()["boards"] + new))
        self.assertEqual(result["count"], 4)
        watch = tomllib.loads(result["changes"]["config"])["watch"]
        self.assertEqual(watch["greenhouse"], {"anthropic": "Anthropic", "initech": "Initech"})
        self.assertEqual(watch["lever"], {"globex-robotics": "Globex Robotics"})
        self.assertEqual(watch["ashby"], {"Hooli": "Hooli"})
        self.assertEqual(watch["workday"], {"umbrella": {"name": "Umbrella", "wd": "wd5", "site": "Careers"}})
        # Only lines were added: every comment, and the commented-out example under [watch.workday], is still there.
        after = lf(result, "config").splitlines()
        self.assertTrue(all(line in after for line in before.replace("\r\n", "\n").splitlines()))
        self.assertIn('# acme = { name = "Acme", wd = "wd1", site = "External" }', after)
        self.assertEqual([d["path"] for d in result["diffs"]], ["profile/search.toml"])
        self.save(result)

        result = self.draft("companies", self.form(boards=[b for b in self.form()["boards"] if b["key"] == "anthropic"]))
        self.assertEqual(result["count"], 4)
        self.assertIn("stops reading Initech, Globex Robotics, Hooli and Umbrella's boards", result["notes"][0])
        self.assertEqual(result["changes"]["config"], before)

    def test_a_name_or_key_changes_in_its_own_line(self):
        boards = self.form()["boards"]
        boards[0]["name"] = "Anthropic PBC"
        result = self.draft("companies", self.form(boards=boards))
        self.assertIn('anthropic = "Anthropic PBC"\n', lf(result, "config"))
        self.assertEqual(result["count"], 1)
        boards[0]["key"] = "anthropic-labs"
        result = self.draft("companies", self.form(boards=boards))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["watch"]["greenhouse"], {"anthropic-labs": "Anthropic PBC"})

    def test_a_workday_site_keeps_what_else_its_table_holds(self):
        self.rewrite(self.config().replace(
            "[watch.workday]", '[watch.workday]\nglobex = { name = "Globex", wd = "wd1", site = "Ext", note = "kept" }', 1))
        boards = self.form()["boards"]
        next(b for b in boards if b["key"] == "globex")["site"] = "External"
        result = self.draft("companies", self.form(boards=boards))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["watch"]["workday"]["globex"],
                         {"name": "Globex", "wd": "wd1", "site": "External", "note": "kept"})

    def test_a_company_written_as_a_table_of_its_own_is_refused_rather_than_half_changed(self):
        self.rewrite(self.config() + '\n[watch.workday.globex]\nname = "Globex"\nwd = "wd1"\nsite = "Ext"\n')
        with self.assertRaisesRegex(ValueError, "a table of its own"):
            self.draft("companies", self.form(boards=[b for b in self.form()["boards"] if b["key"] != "globex"]))

    def test_companies_checked_by_hand_are_added_changed_and_taken_off(self):
        before = self.config()
        manual = self.form()["manual"] + [{"at": None, "name": "Initech", "url": "careers.initech.example/jobs", "why": "Its own site"}]
        result = self.draft("companies", self.form(manual=manual))
        config = tomllib.loads(result["changes"]["config"])
        self.assertEqual(config["manual_check"][1], {"name": "Initech", "url": "https://careers.initech.example/jobs", "why": "Its own site"})
        self.assertEqual(config["manual_check"][0]["name"], "LinkedIn")
        # The comments above and below the list stay where they were.
        self.assertIn("# Employers worth watching with no public feed.", lf(result, "config"))
        self.assertIn("# Company watchlist, checked with `pyrite sources`.", lf(result, "config"))
        self.assertEqual(config["watch"], tomllib.loads(before)["watch"])

        manual = self.form()["manual"]
        manual[0]["why"] = ""
        result = self.draft("companies", self.form(manual=manual))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["manual_check"],
                         [{"name": "LinkedIn", "url": "https://www.linkedin.com/jobs/"}])

        result = self.draft("companies", self.form(manual=[]))
        self.assertNotIn("manual_check", tomllib.loads(result["changes"]["config"]))
        self.assertIn("# [[manual_check]]\n", lf(result, "config"))
        self.save(result)
        result = self.draft("companies", self.form(manual=[{"at": None, "name": "Globex", "url": "", "why": ""}]))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["manual_check"], [{"name": "Globex"}])

    def test_workday_searches_are_added_and_taken_off_an_item_at_a_time(self):
        queries = self.form()["queries"]
        result = self.draft("companies", self.form(queries=queries[1:] + ["robotics", "robotics", " "]))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["workday"]["queries"], queries[1:] + ["robotics"])
        self.assertEqual(result["count"], 2)
        self.assertIn("'robotics'", result["changes"]["config"])
        boards = self.form()["boards"] + [{"was": None, "kind": "workday", "key": "umbrella", "wd": "wd1", "site": "Ext", "name": "Umbrella"}]
        result = self.draft("companies", self.form(boards=boards, queries=[]))
        self.assertTrue(any("finds nothing on them" in note for note in result["notes"]), result["notes"])

    def test_what_cant_be_written_is_refused(self):
        boards = self.form()["boards"]
        for board, said in (
            ({"kind": "greenhouse", "key": "acme/../evil", "name": "Acme"}, "isn't a Greenhouse board"),
            ({"kind": "lever", "key": "evil.test#", "name": "Acme"}, "isn't a Lever board"),
            ({"kind": "ashby", "key": "", "name": "Acme"}, "isn't an Ashby board"),
            ({"kind": "workday", "key": "evil.test", "wd": "wd1", "site": "Ext", "name": "Acme"}, "isn't a Workday tenant"),
            ({"kind": "workday", "key": "acme", "wd": "wd1.evil.test", "site": "Ext", "name": "Acme"}, "isn't a Workday server"),
            ({"kind": "workday", "key": "acme", "wd": "wd1", "site": "Ext?x=1", "name": "Acme"}, "isn't a Workday site"),
            ({"kind": "greenhouse", "key": "acme", "name": ""}, "Name the company"),
            ({"kind": "indeed", "key": "acme", "name": "Acme"}, "Greenhouse, Lever, Ashby or Workday"),
            ({"kind": "greenhouse", "key": "anthropic", "name": "Again"}, "listed twice"),
            ({"kind": "greenhouse", "key": "acme", "name": "Acme\nInc"}, "line break"),
            ({"was": "greenhouse:gone", "kind": "greenhouse", "key": "gone", "name": "Gone"}, "since the page read it"),
        ):
            with self.subTest(board):
                with self.assertRaisesRegex(ValueError, said):
                    self.draft("companies", self.form(boards=boards + [{"was": None, **board}]))
        for manual, said in (
            ([{"at": None, "name": "Evil", "url": "javascript:alert(1)", "why": ""}], "isn't a web address"),
            ([{"at": None, "name": "", "url": "https://example.com", "why": ""}], "needs a name"),
            ([{"at": 5, "name": "LinkedIn", "url": "", "why": ""}], "since the page read"),
            ([{"at": True, "name": "LinkedIn", "url": "", "why": ""}], "since the page read"),
        ):
            with self.subTest(manual):
                with self.assertRaisesRegex(ValueError, said):
                    self.draft("companies", self.form(manual=manual))
        for edits in ({"boards": "nope"}, {"boards": [1]}, {"queries": [1]}, {"queries": "x"}, {"manual": [["x"]]}):
            with self.subTest(edits):
                with self.assertRaises(ValueError):
                    self.draft("companies", edits)
        self.assertFalse((self.root / "data" / "history").exists())

    def test_a_pasted_address_is_read_as_the_board_it_names(self):
        for address, board in (
            ("boards.greenhouse.io/initech", {"kind": "greenhouse", "key": "initech", "name": "Initech"}),
            ("https://job-boards.greenhouse.io/initech/jobs/4012345", {"kind": "greenhouse", "key": "initech", "name": "Initech"}),
            ("https://boards.greenhouse.io/embed/job_board?for=globex-robotics",
             {"kind": "greenhouse", "key": "globex-robotics", "name": "Globex Robotics"}),
            ("https://boards-api.greenhouse.io/v1/boards/initech/jobs", {"kind": "greenhouse", "key": "initech", "name": "Initech"}),
            ("https://jobs.lever.co/hooli/5f7e-41ab/apply", {"kind": "lever", "key": "hooli", "name": "Hooli"}),
            ("http://jobs.ashbyhq.com/Umbrella", {"kind": "ashby", "key": "Umbrella", "name": "Umbrella"}),
            ("https://umbrella.wd5.myworkdayjobs.com/en-US/Careers/job/Madison-WI/Engineer_R-1234",
             {"kind": "workday", "key": "umbrella", "wd": "wd5", "site": "Careers", "name": "Umbrella"}),
            ("UMBRELLA.WD1.myworkdayjobs.com/External", {"kind": "workday", "key": "umbrella", "wd": "wd1", "site": "External", "name": "Umbrella"}),
            ("https://umbrella.wd1.myworkdayjobs.com/wday/cxs/umbrella/External/jobs",
             {"kind": "workday", "key": "umbrella", "wd": "wd1", "site": "External", "name": "Umbrella"}),
        ):
            with self.subTest(address):
                self.assertEqual(discover.board_from_url(address), board)
        for address, said in (
            ("https://careers.initech.example/jobs", "isn't one of them"),
            ("https://boards.greenhouse.io@evil.test/initech", "evil.test isn't one of them"),
            ("https://boards.greenhouse.io.evil.test/initech", "isn't one of them"),
            ("https://boards.greenhouse.io/", "no board after the slash"),
            ("https://umbrella.wd1.myworkdayjobs.com/en-US", "no Workday site"),
            ("https://boards.greenhouse.io/a%2F..%2Fevil", "isn't a Greenhouse board"),
            ("ftp://boards.greenhouse.io/initech", "isn't a web address"),
            ("", "Paste"),
        ):
            with self.subTest(address):
                with self.assertRaisesRegex(ValueError, said):
                    discover.board_from_url(address)
        # The section's draft reads one too, and changes nothing for it.
        result = self.draft("companies", self.form(paste="  https://jobs.lever.co/hooli  "))
        self.assertEqual((result["count"], result["preview"]["pasted"]), (0, {"ok": True, "kind": "lever", "key": "hooli", "name": "Hooli"}))
        result = self.draft("companies", self.form(paste="careers.initech.example"))
        self.assertFalse(result["preview"]["pasted"]["ok"])

    def test_the_view_shows_how_each_board_answered_at_the_last_run(self):
        with mock.patch.object(store, "DB_PATH", self.root / "data" / "pyrite.db"):
            with closing(store.connect()) as conn:
                conn.execute("INSERT INTO source_status (source_key, company, last_run, last_ok, last_error, last_count) "
                             "VALUES ('greenhouse:anthropic', 'Anthropic', '2026-11-08T06:00', '2026-11-08T06:00', '', 42)")
                conn.commit()
            board = steps.view()["companies"]["boards"][0]
        self.assertEqual((board["status"]["count"], board["status"]["error"], board["problem"]), (42, "", ""))

    # ---- Test this board ----

    def test_testing_a_board_reads_only_that_boards_own_feed(self):
        asked = []

        def answer(url, payload=None, retries=3):
            asked.append(url)
            return {"total": 7} if "myworkdayjobs" in url else {"jobs": [{"id": 1, "title": "Engineer"}, {"id": 2, "title": "Lead"}]}

        with mock.patch.object(sources, "_request", side_effect=answer):
            found = server._test_board({"kind": "greenhouse", "key": "initech", "name": "Initech"})
            self.assertEqual((found["ok"], found["count"]), (True, 2))
            found = server._test_board({"url": "https://umbrella.wd5.myworkdayjobs.com/en-US/Careers"})
            self.assertEqual((found["ok"], found["count"], found["board"]["site"]), (True, 7, "Careers"))
        self.assertEqual(asked, ["https://boards-api.greenhouse.io/v1/boards/initech/jobs",
                                 "https://umbrella.wd5.myworkdayjobs.com/wday/cxs/umbrella/Careers/jobs"])

    def test_testing_refuses_anything_but_a_board_on_the_four_hosts(self):
        with mock.patch.object(sources, "_request") as fetch:
            for body in (
                {"url": "https://evil.test/initech"},
                {"url": "https://boards.greenhouse.io@evil.test/initech"},
                {"url": "http://127.0.0.1:8787/api/state"},
                {"url": ["https://boards.greenhouse.io/initech"]},
                {"kind": "greenhouse", "key": "evil.test/x"},
                {"kind": "greenhouse", "key": "@evil.test"},
                {"kind": "lever", "key": "../../evil"},
                {"kind": "workday", "key": "evil.test#", "wd": "wd1", "site": "Ext"},
                {"kind": "workday", "key": "umbrella", "wd": "wd1.evil.test/", "site": "Ext"},
                {"kind": "workday", "key": "umbrella", "wd": "wd1", "site": "../../evil"},
                {"kind": "https://evil.test", "key": "initech"},
                {"kind": "greenhouse", "key": 5},
                {},
            ):
                with self.subTest(body):
                    with self.assertRaises(ValueError):
                        server._test_board(body)
            fetch.assert_not_called()

    def test_a_board_that_doesnt_answer_says_so(self):
        missing = urllib.error.HTTPError("https://boards-api.greenhouse.io/v1/boards/nobody/jobs", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        self.addCleanup(missing.close)
        with mock.patch.object(sources, "_request", side_effect=missing):
            found = server._test_board({"kind": "greenhouse", "key": "nobody"})
        self.assertFalse(found["ok"])
        self.assertIn("No Greenhouse board answers", found["hint"])


class BlankMasters(unittest.TestCase):
    """A blank workspace's master resume and letter start with only the name, and the assay needs a contact line in
    each. Setup has to be able to put it there, since neither master's editor has a field for it."""

    CONTACT = ["Springfield, IL", "sam@example.com"]
    LINE = "@ Springfield, IL · sam@example.com"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        workspace._make_blank(self.root / "profile", "Sam Doe")
        self.view = {**profile.view(), **steps.view()}

    def draft(self, step, edits):
        return steps.draft(step, edits, self.view["versions"])

    def save(self, result):
        profile.write(result["changes"], self.view["versions"], "test")
        self.view = {**profile.view(), **steps.view()}

    def masters_form(self):
        """Master resume's form as the page first sends it, on opening: everything as it is."""
        blocks = self.view["master_blocks"]
        return {"resume": {"headline": blocks["resume"]["headline"] or "", "blocks": []},
                "letter": {"body": blocks["letter"]["body"] or ""}}

    def test_name_and_contact_puts_the_line_under_the_name_in_both_masters(self):
        result = self.draft("basics", {"name": "Sam Doe", "paper": "letter", "contact": self.CONTACT})
        self.assertEqual(result["count"], 3)
        self.assertTrue(lf(result, "resume").startswith(f"# Sam Doe\n{self.LINE}\n\n## Summary"))
        self.assertEqual(lf(result, "letter"), f"# Sam Doe\n{self.LINE}\n")
        self.assertEqual(sum("saving puts" in note for note in result["notes"]), 2, result["notes"])
        self.save(result)
        for key, kind in (("resume", "resume"), ("letter", "letter")):
            self.assertFalse([p for p in doctor.master_problems(profile.read(key), kind, "Sam Doe", self.LINE)
                              if "contact" in p], key)
        # Done once, so the same form opened again has nothing to save.
        self.assertEqual(self.draft("basics", {"name": "Sam Doe", "paper": "letter", "contact": self.CONTACT})["count"], 0)

    def test_master_resume_puts_in_the_line_a_workspace_saved_without(self):
        # A workspace whose Name and contact was saved before setup could put the line in has it only in facts.md.
        self.save(self.draft("basics", {"contact": self.CONTACT}))
        for key in ("resume", "letter"):
            text = "".join(row for row in profile.read(key).splitlines(keepends=True) if not row.startswith("@ "))
            (self.root / profile.FILES[key]).write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}
        result = self.draft("masters", self.masters_form())
        self.assertEqual(result["count"], 2)
        self.assertIn(f"# Sam Doe\n{self.LINE}\n", lf(result, "resume"))
        self.assertIn(f"# Sam Doe\n{self.LINE}\n", lf(result, "letter"))
        self.assertFalse([e for e in result["preview"]["resume"]["errors"] if "contact" in e], result["preview"])

    def test_master_resume_doesnt_pass_with_no_contact_line_anywhere(self):
        result = self.draft("masters", self.masters_form())
        self.assertEqual(result["count"], 0)
        for key in ("resume", "letter"):
            errors = result["preview"][key]["errors"]
            self.assertTrue(any("no '@ ' contact line" in e and "Name and contact" in e for e in errors), errors)

    def test_the_line_goes_under_the_headline_and_keeps_the_line_endings(self):
        self.assertEqual(steps.with_contact("# A\n= Head\n\n## S\n", "x"), "# A\n= Head\n@ x\n\n## S\n")
        self.assertEqual(steps.with_contact("# A", "x"), "# A\n@ x\n")
        self.assertEqual(steps.with_contact("# A\r\n\r\n## S\r\n", "x"), "# A\r\n@ x\r\n\r\n## S\r\n")
        self.assertIsNone(steps.with_contact("# A\n@ y\n", "x"))
        self.assertIsNone(steps.with_contact("## S\n", "x"))
        self.assertIsNone(steps.with_contact("# A\n", ""))


if __name__ == "__main__":
    unittest.main()
