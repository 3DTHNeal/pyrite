"""The Profile tab: changing one TOML setting without touching the rest, reading and writing facts.md without losing a
byte, saving profile files together with their history, and the hub that shows each section and what needs you."""
import re
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path

import support  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import factsdoc, profile, server, settings, store, tomledit

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"

CONFIG = """# What Pyrite looks for.

[candidate]
name = "Sam Doe"  # as it goes on documents

[location]
local = [
  'springfield', 'shelbyville', 'capital city',
]
accept_remote = true

[guard]
forbidden = ['Bluebird', '\\bhive\\b']  # confidential
# Blocked unless denied.
unsupported = [
  'ISO 26262',
  'safety[- ]certifi\\w+',
]
note = "a # inside a string, and a ] too"
long = \"\"\"
first line
second ] line # not a comment
\"\"\"

[inbox.domains]
"Hooli Autonomy" = ["hooli-mail.example"]

# Roles to pursue
[[track]]
name = "AI"
title = ['\\bai\\b']

[[track]]
name = "Embedded"
title = ['\\bfirmware\\b']

# Things the dashboard answers to
[dashboard]
allowed_hosts = []
"""


def outside(old: str, new: str, start: int, end: int) -> bool:
    """Whether everything outside old[start:end] is the same in new."""
    return new.startswith(old[:start]) and new.endswith(old[end:])


class SetValue(unittest.TestCase):
    def pair(self, text, table, key):
        return next(p for p in tomledit.scan(text) if isinstance(p, tomledit.Pair) and p.table == table and p.key == (key,))

    def test_an_existing_value_changes_and_every_other_byte_stays(self):
        p = self.pair(CONFIG, ("candidate",), "name")
        new = tomledit.set_value(CONFIG, "candidate", "name", "Sam Q. Doe")
        self.assertIn('name = "Sam Q. Doe"  # as it goes on documents', new)
        self.assertTrue(outside(CONFIG, new, p.value_start, p.value_end))

    def test_an_array_keeps_its_shape_and_patterns_stay_literal(self):
        new = tomledit.set_value(CONFIG, "location", "local", ["springfield", "ogdenville"], literal=True)
        self.assertIn("local = [\n  'springfield', 'ogdenville',\n]", new)
        new = tomledit.set_value(CONFIG, "guard", "unsupported", ["ISO 26262", "x\\d", "y"], literal=True)
        self.assertIn("unsupported = [\n  'ISO 26262',\n  'x\\d',\n  'y',\n]", new)
        new = tomledit.set_value(CONFIG, "guard", "forbidden", ["Bluebird", "it's"], literal=True)
        self.assertIn("""forbidden = ['Bluebird', "it's"]  # confidential""", new)
        self.assertEqual(tomllib.loads(new)["guard"]["forbidden"], ["Bluebird", "it's"])

    def test_names_in_inline_tables_are_plain_strings_and_patterns_literal(self):
        text = "[promote]\ncities = [\n  { name = \"Springfield\" },\n]\n"
        new = tomledit.set_value(text, "promote", "cities", [{"name": "Ogdenville", "match": "ogden\\w+"}], literal=True)
        self.assertIn("""{ name = "Ogdenville", match = 'ogden\\w+' }""", new)

    def test_a_new_key_goes_after_the_last_in_its_table(self):
        new = tomledit.set_value(CONFIG, "candidate", "pronouns", "they/them")
        self.assertIn('name = "Sam Doe"  # as it goes on documents\npronouns = "they/them"\n', new)

    def test_a_new_table_goes_at_the_end_and_a_root_key_before_the_first_table(self):
        new = tomledit.set_value(CONFIG, "documents", "paper", "a4")
        self.assertTrue(new.endswith('allowed_hosts = []\n\n[documents]\npaper = "a4"\n'))
        new = tomledit.set_value(CONFIG, "", "version", 2)
        self.assertEqual(tomllib.loads(new)["version"], 2)
        self.assertLess(new.index("version = 2"), new.index("[candidate]"))

    def test_strings_with_brackets_hashes_and_quoted_keys_are_read_right(self):
        self.assertEqual(tomledit.get_text(CONFIG, "guard", "note"), '"a # inside a string, and a ] too"')
        new = tomledit.set_value(CONFIG, "inbox.domains", "Hooli Autonomy", ["hooli.example"])
        self.assertEqual(tomllib.loads(new)["inbox"]["domains"]["Hooli Autonomy"], ["hooli.example"])
        new = tomledit.set_value(CONFIG, "guard", "long", "one line")
        self.assertEqual(tomllib.loads(new)["guard"]["long"], "one line")
        self.assertIn("# Blocked unless denied.", new)

    def test_windows_line_endings_stay(self):
        text = CONFIG.replace("\n", "\r\n")
        new = tomledit.set_value(text, "location", "local", ["a", "b", "c", "d"], literal=True)
        self.assertNotIn("\n", new.replace("\r\n", ""))
        new = tomledit.set_value(text, "documents", "paper", "a4")
        self.assertTrue(new.endswith('\r\n[documents]\r\npaper = "a4"\r\n'))

    def test_delete_undoes_an_add_exactly(self):
        added = tomledit.set_value(CONFIG, "dashboard", "max_per_company", 3)
        self.assertEqual(tomledit.delete_value(added, "dashboard", "max_per_company"), CONFIG)
        self.assertEqual(tomledit.delete_value(CONFIG, "dashboard", "nothing_here"), CONFIG)

    def test_a_change_that_would_break_or_alter_the_file_is_refused(self):
        with self.assertRaises(tomledit.EditError):
            tomledit.set_value("a.b = 1\n", "", "a", 2)  # Would define a twice.
        with self.assertRaises(tomledit.EditError):
            tomledit.set_value(CONFIG, "track", "name", "X")  # A list of tables is replaced whole.
        with self.assertRaises(tomledit.EditError):
            tomledit.set_value(CONFIG, "candidate", "when", object())

    def test_a_list_of_tables_is_replaced_whole_and_the_next_tables_comment_stays(self):
        block = '[[track]]\nname = "Leadership"\ntitle = [\'\\bmanager\\b\']\n'
        new = tomledit.replace_table(CONFIG, "track", block, expected=[{"name": "Leadership", "title": ["\\bmanager\\b"]}])
        self.assertIn("# Roles to pursue\n[[track]]\nname = \"Leadership\"", new)
        self.assertIn("# Things the dashboard answers to\n[dashboard]", new)
        self.assertEqual(tomllib.loads(new)["dashboard"], {"allowed_hosts": []})
        with self.assertRaises(tomledit.EditError):
            tomledit.replace_table(CONFIG, "track", block, expected=[{"name": "Other"}])

    def test_a_table_split_by_another_is_refused(self):
        text = "[a.x]\nk = 1\n[b]\nk = 2\n[a.y]\nk = 3\n"
        with self.assertRaises(tomledit.EditError):
            tomledit.replace_table(text, "a", "[a]\nk = 4\n")

    def test_setting_every_key_in_the_example_to_its_own_value_touches_only_that_value(self):
        text = (EXAMPLE_PROFILE / "search.toml").read_bytes().decode("utf-8")
        config = tomllib.loads(text)
        for p in tomledit.scan(text):
            if not isinstance(p, tomledit.Pair) or p.array or len(p.key) != 1:
                continue
            value = config
            for part in p.table + p.key:
                value = value[part]
            new = tomledit.set_value(text, p.table, p.key[0], value, literal="'" in text[p.value_start:p.value_end])
            self.assertTrue(outside(text, new, p.value_start, p.value_end), ".".join(p.table + p.key))
            self.assertEqual(tomllib.loads(new), config)


FACTS = """# Fact bank

## Contact
Springfield, IL · sam@example.com

## Timeline
- **Acme Data, Jan 2020 – Oct 2026**
  - Manager, Data Platform, Springfield, IL, Mar 2023 – Oct 2026 (title changed in 2024)
  - Senior Data Engineer, Springfield, IL, Jan 2020 – Mar 2023
- **Globex,** Data Engineer, Remote, Jun 2016 - Dec 2019
- **Education:** B.S., Statistics, 2016
- Something written some other way

## Data platform
- Cut nightly batch time from 6 hours to 2 hours
  on the shared cluster
- Moved 40 pipelines to Airflow
  - including the billing ones

## Do not use
- Project Nimbus

## Unsupported, so don't claim without new evidence
- Kubernetes
"""


class FactsDoc(unittest.TestCase):
    def test_an_unchanged_document_renders_to_the_same_bytes(self):
        for text in (FACTS, FACTS.replace("\n", "\r\n"), FACTS.rstrip("\n"),
                     (EXAMPLE_PROFILE / "facts.md").read_bytes().decode("utf-8")):
            self.assertEqual(factsdoc.Doc(text).render(), text)

    def test_sections_know_what_they_are(self):
        kinds = {s.title: s.kind for s in factsdoc.Doc(FACTS).sections()}
        self.assertEqual(kinds, {"Contact": "contact", "Timeline": "timeline", "Data platform": "facts",
                                 "Do not use": "excluded", "Unsupported, so don't claim without new evidence": "excluded"})

    def test_bullets_carry_their_continuation_and_nested_lines(self):
        doc = factsdoc.Doc(FACTS)
        items = doc.items(doc.section("data platform"))
        self.assertEqual([(i.level, i.text) for i in items],
                         [(0, "Cut nightly batch time from 6 hours to 2 hours"), (0, "Moved 40 pipelines to Airflow"),
                          (1, "including the billing ones")])
        doc.remove_item(items[0])
        self.assertNotIn("on the shared cluster", doc.render())

    def test_the_timeline_reads_employers_roles_and_labeled_lines(self):
        employers, labeled, unread = factsdoc.Doc(FACTS).timeline(("Manager, Data Platform",))
        acme, globex = employers
        self.assertEqual((acme.name, acme.start, acme.end, acme.single), ("Acme Data", "Jan 2020", "Oct 2026", False))
        self.assertEqual([(r.title, r.place, r.start, r.end, r.note) for r in acme.roles], [
            ("Manager, Data Platform", "Springfield, IL", "Mar 2023", "Oct 2026", "(title changed in 2024)"),
            ("Senior Data Engineer", "Springfield, IL", "Jan 2020", "Mar 2023", ""),
        ])
        self.assertEqual((globex.name, globex.single, globex.roles[0].title, globex.roles[0].place), ("Globex", True, "Data Engineer", "Remote"))
        self.assertEqual([(i.label, i.text) for i in labeled], [("Education", "B.S., Statistics, 2016")])
        self.assertEqual(len(unread), 1)

    def test_without_a_known_title_a_comma_ends_the_title(self):
        employers, _, _ = factsdoc.Doc(FACTS).timeline()
        self.assertEqual((employers[0].roles[0].title, employers[0].roles[0].place), ("Manager", "Data Platform, Springfield, IL"))

    def test_changing_a_role_touches_only_its_line_and_keeps_the_note_and_dash(self):
        doc = factsdoc.Doc(FACTS)
        employers, _, _ = doc.timeline(("Manager, Data Platform",))
        doc.set_role(employers[0].roles[0], title="Director, Data Platform", end="Nov 2026")
        doc.set_role(employers[1].roles[0], start="Jul 2016")
        new = doc.render()
        self.assertIn("  - Director, Data Platform, Springfield, IL, Mar 2023 – Nov 2026 (title changed in 2024)\n", new)
        self.assertIn("- **Globex,** Data Engineer, Remote, Jul 2016 - Dec 2019\n", new)
        self.assertEqual(len(new.splitlines()), len(FACTS.splitlines()))
        changed = [a for a, b in zip(FACTS.splitlines(), new.splitlines(), strict=True) if a != b]
        self.assertEqual(len(changed), 2)

    def test_adding_editing_and_removing_bullets(self):
        doc = factsdoc.Doc(FACTS.replace("\n", "\r\n"))
        section = doc.section("data platform")
        line = doc.add_item(section, "Hired 3 engineers")
        self.assertEqual(doc.bare(line), "- Hired 3 engineers")
        doc.set_item(doc.items(doc.section("data platform"))[0], "Cut nightly batch time from 6 hours to 90 minutes")
        new = doc.render()
        self.assertIn("- Cut nightly batch time from 6 hours to 90 minutes\r\n  on the shared cluster\r\n", new)
        self.assertIn("  - including the billing ones\r\n- Hired 3 engineers\r\n\r\n## Do not use", new)
        self.assertNotIn("\n", new.replace("\r\n", ""))

    def test_a_new_section_goes_before_the_ones_that_approve_nothing(self):
        doc = factsdoc.Doc(FACTS)
        doc.add_section("Leadership", ["Managed a team of 5"])
        titles = [s.title for s in doc.sections()]
        self.assertEqual(titles.index("Leadership"), titles.index("Do not use") - 1)
        self.assertIn("## Leadership\n- Managed a team of 5\n\n## Do not use", doc.render())

    def test_months(self):
        self.assertEqual(factsdoc.month_text("2023-01"), "Jan 2023")
        self.assertEqual(factsdoc.month_text(""), "Present")
        self.assertEqual(factsdoc.month_value("Sept 2021"), "2021-09")
        self.assertEqual(factsdoc.month_value("present"), "")
        with self.assertRaises(factsdoc.FactsError):
            factsdoc.month_text("2023-13")


class Profile(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_view_has_what_the_tab_edits(self):
        view = profile.view()
        self.assertEqual(view["basics"]["name"], "Alex Rivera")
        self.assertTrue(view["basics"]["contact"].startswith("Madison, WI"))
        employers = view["timeline"]["employers"]
        self.assertEqual([e["name"] for e in employers], ["Northbridge Robotics", "Lakeshore Instruments"])
        self.assertEqual(employers[0]["roles"][0]["title"], "Principal Firmware Engineer")
        self.assertIn("CAN", view["terms"])
        self.assertNotIn("Contact", [s["title"] for s in view["sections"]])
        self.assertEqual(view["versions"]["facts"], profile.version(profile.read("facts")))

    def test_titles_come_from_the_heading_source(self):
        titles = profile.known_titles(tomllib.loads(profile.read("config")))
        self.assertIn("Principal Firmware Engineer", titles)

    def test_a_save_writes_every_file_and_keeps_what_they_were(self):
        before = profile.versions()
        facts, terms = profile.read("facts"), profile.read("terms")
        after = profile.write({"facts": facts + "\n- One more fact\n", "terms": terms + "Rust\n"}, before, "Added things")
        self.assertNotEqual(after["facts"], before["facts"])
        self.assertIn("Rust", profile.read("terms"))
        entries = profile.history()
        self.assertEqual({e["key"] for e in entries}, {"facts", "terms"})
        self.assertEqual(entries[0]["reason"], "Added things")
        stamp = entries[0]["stamp"]
        self.assertEqual(profile.kept("facts", stamp), facts)

    def test_an_unchanged_file_is_neither_written_nor_kept(self):
        before = profile.versions()
        profile.write({"facts": profile.read("facts")}, before, "Nothing")
        self.assertEqual(profile.history(), [])

    def test_a_save_based_on_an_old_version_writes_nothing(self):
        before = profile.versions()
        (self.root / "profile" / "approved-terms.txt").write_bytes(b"Changed elsewhere\n")
        with self.assertRaises(profile.Conflict):
            profile.write({"facts": "## New\n- x\n", "terms": "Mine\n"}, before, "x")
        self.assertEqual(profile.versions()["facts"], before["facts"])
        self.assertEqual(profile.read("terms"), "Changed elsewhere\n")

    def test_if_one_file_fails_the_others_are_put_back(self):
        before = profile.versions()
        facts = profile.read("facts")
        real = settings._write
        calls = []

        def flaky(path, text):
            calls.append(path)
            if len(calls) == 2:
                raise ValueError("approved-terms.txt is busy")
            real(path, text)

        with mock.patch.object(settings, "_write", flaky), self.assertRaises(ValueError):
            profile.write({"facts": facts + "- More\n", "terms": "Rust\n"}, before, "x")
        self.assertEqual(profile.read("facts"), facts)

    def test_a_new_file_that_fails_is_removed_again(self):
        (self.root / "profile" / "resume.md").unlink()
        before = profile.versions()
        real = settings._write

        def flaky(path, text):
            real(path, text)
            if path.name == "resume.md":
                return
            raise ValueError("busy")

        with mock.patch.object(settings, "_write", flaky), self.assertRaises(ValueError):
            profile.write({"resume": "# Alex Rivera\n", "facts": profile.read("facts") + "- x\n"}, before, "x")
        self.assertFalse((self.root / "profile" / "resume.md").exists())

    def test_what_isnt_allowed_is_refused_before_anything_is_written(self):
        before = profile.versions()
        for changes, message in (
            ({"../../etc": "x"}, "isn't a file"),
            ({"facts": "  \n"}, "can't be empty"),
            ({"facts": "bell\x07"}, "control characters"),
            ({"config": "[candidate\n"}, "wouldn't read"),
            ({"config": "[run]\nmin_score = 1\n"}, "[candidate] name"),
        ):
            with self.assertRaises(ValueError) as caught:
                profile.write(changes, before, "x")
            self.assertIn(message, str(caught.exception))
        self.assertEqual(profile.versions(), before)
        self.assertEqual(profile.history(), [])

    def test_the_demo_cant_be_changed(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), self.assertRaises(ValueError):
            profile.write({"terms": "x\n"}, profile.versions(), "x")

    def test_history_keeps_only_the_latest_copies(self):
        with mock.patch.object(profile, "HISTORY_KEEP", 3):
            for n in range(5):
                profile.write({"terms": f"Term{n}\n"}, profile.versions(), f"Save {n}")
        self.assertEqual(len(list((self.root / "data" / "history" / "terms").iterdir())), 3)
        kept = [e for e in profile.history() if e["kept"]]
        self.assertEqual([e["reason"] for e in kept], ["Save 4", "Save 3", "Save 2"])
        with self.assertRaises(ValueError):
            profile.kept("terms", "../../facts")

    def test_saves_that_read_the_same_time_keep_a_copy_each(self):
        # Windows' clock on Python 3.11 moves in steps of about 15 ms, so quick saves can read the same time. Each
        # copy must still get its own name, or the later one overwrites the earlier and its history is lost.
        class Stopped(profile.datetime):
            @classmethod
            def now(cls, tz=None):
                return profile.datetime(2026, 11, 8, 12, 0, 0, tzinfo=tz)
        with mock.patch.object(profile, "datetime", Stopped):
            for n in range(4):
                profile.write({"terms": f"Term{n}\n"}, profile.versions(), f"Save {n}")
        kept = [e for e in profile.history() if e["kept"]]
        self.assertEqual([e["reason"] for e in kept], ["Save 3", "Save 2", "Save 1", "Save 0"])
        self.assertEqual(len({e["stamp"] for e in kept}), 4)
        self.assertEqual([profile.kept("terms", e["stamp"]) for e in kept[:3]], ["Term2\n", "Term1\n", "Term0\n"])


class Hub(Profile):
    """The Profile tab's front page: each section's state and summary, what needs you, and History."""

    def section(self, step_id):
        return next(s for s in profile.view()["steps"] if s["id"] == step_id)

    def test_every_section_is_listed_in_order_with_a_summary(self):
        steps = profile.view()["steps"]
        self.assertEqual([s["id"] for s in steps], [s["id"] for s in profile.STEPS])
        self.assertTrue(all(s["summary"] and s["why"] for s in steps))
        self.assertEqual(self.section("basics")["summary"], "Alex Rivera, Madison, WI")
        self.assertEqual(self.section("history")["summary"], "4 roles at 2 employers")
        self.assertEqual(self.section("masters")["summary"], "Resume and letter written")
        self.assertEqual({s["status"] for s in steps if s["id"] != "tools"}, {"set"})
        self.assertEqual(self.section("tools")["status"], "unknown")

    def test_a_section_with_nothing_in_it_is_not_set(self):
        profile.write({"terms": "# none yet\n"}, profile.versions(), "Emptied")
        self.assertEqual((self.section("skills")["status"], self.section("skills")["summary"]), ("not_set", "No approved terms"))
        config = tomledit.set_value(profile.read("config"), "guard", "heading_source", "profile/missing.md")
        (self.root / "profile" / "search.toml").write_bytes(config.encode())
        self.assertEqual(self.section("masters")["status"], "not_set")

    def test_a_master_outside_the_profile_folder_is_named(self):
        (self.root / "applications" / "model").mkdir(parents=True)
        shutil.copy(self.root / "profile" / "resume.md", self.root / "applications" / "model" / "resume.md")
        config = tomledit.set_value(profile.read("config"), "guard", "heading_source", "applications/model/resume.md")
        (self.root / "profile" / "search.toml").write_bytes(config.encode())
        self.assertEqual(self.section("masters")["summary"], "Headings checked against applications/model/resume.md")

    def test_a_save_names_its_section_and_the_hub_says_when(self):
        profile.write({"terms": profile.read("terms") + "Rust\n"}, profile.versions(), "Skills: 1 change", "skills")
        profile.write({"facts": profile.read("facts") + "- One more\n"}, profile.versions(), "Typed by hand", "not-a-section")
        self.assertIsNotNone(self.section("skills")["changed"])
        self.assertIsNone(self.section("achievements")["changed"])
        entries = profile.history()
        self.assertEqual([e.get("step") for e in entries], [None, "skills"])
        self.assertEqual(entries[0]["path"], "profile/facts.md")
        self.assertTrue(entries[0]["at"].startswith("20"))

    def test_setup_findings_need_you_and_name_the_section_that_fixes_them(self):
        # The suite switches these off, since its workspace is the example. Here they're the point.
        with mock.patch.object(profile.doctor, "workspace_todos", support.WORKSPACE_TODOS):
            view = profile.view()
        steps = {item["step"] for item in view["needs"]}
        self.assertTrue({"basics", "achievements"} <= steps, view["needs"])
        statuses = {s["id"]: s["status"] for s in view["steps"]}
        self.assertEqual((statuses["basics"], statuses["achievements"]), ("attention", "attention"))
        ranks = [{"bad": 0, "warn": 1, "info": 2}[item["severity"]] for item in view["needs"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_the_demo_has_nothing_to_set_up(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), mock.patch.object(profile.doctor, "workspace_todos", support.WORKSPACE_TODOS):
            self.assertEqual(profile.view()["needs"], [])

    def test_a_timeline_line_that_cant_be_read_needs_you(self):
        facts = profile.read("facts").replace("## Timeline", "## Timeline\n- Something else entirely", 1)
        profile.write({"facts": facts}, profile.versions(), "x")
        needs = profile.view()["needs"]
        self.assertEqual([(n["step"], n["severity"]) for n in needs], [("history", "info")])

    def test_compare_shows_what_putting_back_would_change(self):
        terms = profile.read("terms")
        profile.write({"terms": terms + "Rust\n"}, profile.versions(), "Added Rust")
        stamp = profile.history()[0]["stamp"]
        shown = profile.compare("terms", stamp)
        self.assertIn("-Rust", shown["diff"])
        self.assertFalse(shown["same"])
        self.assertTrue(profile.put_back_reason("terms", stamp).startswith("Put back approved-terms.txt as it was before the save of"))
        for key, bad in (("terms", "20261108T000000000000Z"), ("terms", "../x"), ("nope", stamp)):
            with self.assertRaises(ValueError):
                profile.compare(key, bad)


class PageScripts(unittest.TestCase):
    def test_every_script_the_page_loads_is_served_and_every_section_file_is_loaded(self):
        page = (server.STATIC / "index.html").read_text(encoding="utf-8")
        loaded = re.findall(r'<script src="([^"]+)"', page)
        self.assertEqual(loaded[-1], "/static/app.js")  # app.js starts the page, so everything else loads first.
        self.assertTrue(all(src in server.STATIC_FILES for src in loaded), loaded)
        sections = {f"/static/profile/{path.name}" for path in (server.STATIC / "profile").glob("*.js")}
        self.assertLessEqual(sections, set(loaded))


if __name__ == "__main__":
    unittest.main()
