"""The Profile tab: changing one TOML setting without touching the rest, reading and writing facts.md without losing a
byte, saving profile files together with their history, and the hub that shows each section and what needs you."""
import ast
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import tomllib
import unittest
import unittest.mock as mock
import urllib.request
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import support  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import backup, doctor, factsdoc, profile, server, settings, store, tomledit

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

    def test_a_new_key_takes_the_place_of_its_commented_out_example(self):
        text = ('[inbox]\nlookback_days = 14\n# Where the mail comes from.\n# source = "gmail"\n'
                '  # model = "claude-sonnet-5-5"  # copies the mail out\n\n[market]\nstate = "Wisconsin"\n')
        new = tomledit.set_value(text, "inbox", "source", "imap")
        self.assertEqual(new, text.replace('# source = "gmail"', 'source = "imap"'))
        new = tomledit.set_value(text, "inbox", "model", "haiku")
        self.assertEqual(new, text.replace('# model = "claude-sonnet-5-5"', 'model = "haiku"'))
        # Set again, it's an existing value like any other, and taking it out leaves no example behind.
        self.assertIn('  model = "opus"  # copies the mail out\n', tomledit.set_value(new, "inbox", "model", "opus"))
        self.assertEqual(tomllib.loads(tomledit.delete_value(new, "inbox", "model"))["inbox"], {"lookback_days": 14})
        windows = text.replace("\n", "\r\n")
        self.assertEqual(tomledit.set_value(windows, "inbox", "source", "imap"), windows.replace('# source = "gmail"', 'source = "imap"'))

    def test_only_a_real_example_in_the_keys_own_table_is_taken_for_one(self):
        # A sentence with the key and an = in it, and a comment inside a list, aren't examples.
        text = '[claude]\n# effort = how hard it thinks\nnames = [\n  "a",\n  # effort = "low"\n]\n'
        new = tomledit.set_value(text, "claude", "effort", "high")
        self.assertEqual(new, text + 'effort = "high"\n')
        # Nor is another table's example, or one for a key that only starts the same.
        text = '[a]\nx = 1\n# y = 2\n# yy = 3\n[b]\n# yy = 4\nz = 3\n'
        self.assertEqual(tomledit.set_value(text, "b", "y", 5), text + "y = 5\n")
        self.assertEqual(tomledit.set_value(text, "a", "y", 5), text.replace("# y = 2", "y = 5"))
        # A root key's example sits before the first table.
        self.assertEqual(tomledit.set_value("# version = 1\n[a]\nx = 1\n", "", "version", 2), "version = 2\n[a]\nx = 1\n")

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
        # Tools check depends on this computer, and Workspace and backup on a copy no test has made yet.
        self.assertEqual({s["status"] for s in steps if s["id"] not in ("tools", "workspace")}, {"set"})
        self.assertEqual((self.section("workspace")["status"], self.section("workspace")["summary"]), ("not_set", "No backup here yet"))

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

    def test_settings_that_cant_be_read_need_you_and_the_tab_still_opens(self):
        config = profile.read("config")
        (self.root / "profile" / "search.toml").write_bytes(config.encode() + b"\nbroken = oops\n")
        with mock.patch.object(profile.doctor, "workspace_todos", support.WORKSPACE_TODOS):
            view = profile.view()
        first = view["needs"][0]
        self.assertEqual((first["severity"], first["step"]), ("bad", None))
        self.assertRegex(first["title"], r"^profile/search\.toml line \d+: .*Fix that line")
        # A list left open is only found at the end of the file, which has no line to name.
        (self.root / "profile" / "search.toml").write_bytes(config.encode() + b"\nbroken = [\n")
        self.assertIn("at the end of the file", profile.view()["needs"][0]["title"])
        # What doctor would say of settings that look empty only because they can't be read is left out.
        self.assertFalse(any("lists no roles" in item["title"] for item in view["needs"]), view["needs"])
        self.assertEqual([s["id"] for s in view["steps"]], [s["id"] for s in profile.STEPS])

    def test_a_setting_of_the_wrong_kind_needs_you(self):
        config = tomledit.set_value(profile.read("config"), "run", "min_score", "forty")
        (self.root / "profile" / "search.toml").write_bytes(config.encode())
        first = profile.view()["needs"][0]
        self.assertEqual(first["severity"], "bad")
        self.assertIn("min_score under [run]", first["title"])

    def test_a_bad_pattern_opens_the_section_that_edits_it(self):
        config = profile.read("config")
        broken = {
            "where": tomledit.set_value(config, "location", "local", ["(unclosed"]),
            "roles": tomledit.set_value(config, "scoring", "exclude_titles", ["(unclosed"]),
            "priorities": config.replace("match = 'hill valley", "match = '(hill valley", 1),
        }
        for step, text in broken.items():
            with self.subTest(step=step):
                self.assertNotEqual(text, config)
                (self.root / "profile" / "search.toml").write_bytes(text.encode())
                with mock.patch.object(profile.doctor, "workspace_todos", support.WORKSPACE_TODOS):
                    view = profile.view()
                found = [item for item in view["needs"] if "isn't a valid pattern" in item["title"]]
                self.assertEqual([(item["step"], item["severity"]) for item in found], [(step, "bad")], view["needs"])
                self.assertEqual(next(s for s in view["steps"] if s["id"] == step)["status"], "attention")

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

    def test_a_whole_save_is_every_file_it_changed(self):
        facts, terms, resume = profile.read("facts"), profile.read("terms"), profile.read("resume")
        profile.write({"facts": facts + "- One more\n", "terms": terms + "Rust\n", "resume": resume}, profile.versions(), "Two files")
        stamp = profile.history()[0]["stamp"]
        # The resume didn't change, so it isn't part of the save.
        self.assertEqual(profile.kept_save(stamp), {"facts": facts, "terms": terms})
        self.assertTrue(profile.put_back_reason(["facts", "terms"], stamp).startswith(
            "Put back facts.md and approved-terms.txt as they were before the save of"))
        for bad in ("20261108T000000000000Z", "../x", None):
            with self.subTest(bad), self.assertRaises(ValueError):
                profile.kept_save(bad)

    def test_saves_from_other_tabs_are_kept_too(self):
        terms = profile.read("terms")
        with settings._lock:
            profile.keep({"terms": terms}, "Changed on the Facts tab")
        entry = profile.history()[0]
        self.assertEqual((entry["reason"], entry.get("step"), profile.kept("terms", entry["stamp"])), ("Changed on the Facts tab", None, terms))


class ToolsAndWorkspace(Profile):
    """The two sections that only show what they find: the programs on this computer, and the workspace and its backups."""

    PROGRAMS = [{"id": "docx", "ok": True, "what": "python-docx, which builds the documents", "fix": ""},
                {"id": "pdf", "ok": True, "what": "Word, which makes the PDFs", "fix": ""},
                {"id": "pdftotext", "ok": None, "what": "poppler's pdftotext", "fix": "Optional."}]

    def programs(self, **ok):
        found = [{**check, "ok": ok.get(check["id"], check["ok"])} for check in self.PROGRAMS]
        if ok.get("pdf") is False:
            found[1]["fix"] = "Install LibreOffice and put `soffice` on PATH."
        return mock.patch.object(doctor, "program_checks", return_value=[{**c, **doctor.TOOLS_ABOUT[c["id"]]} for c in found])

    def section(self, step_id):
        return next(s for s in profile.view()["steps"] if s["id"] == step_id)

    def database(self):
        with closing(store.connect(self.root / "data" / "pyrite.db")) as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('backed_up', 'kept')")
            conn.commit()

    def test_every_tool_says_what_its_for_and_what_works_without_it(self):
        with mock.patch.object(doctor, "claude_check", return_value={"ok": True, "what": "Claude Code, signed in", "fix": ""}):
            tools = doctor.tool_checks({})
        self.assertEqual([t["id"] for t in tools], ["docx", "pdf", "pdftotext", "claude", "mail"])
        self.assertTrue(all(t["name"] and t["for"] and t["without"] for t in tools))
        self.assertEqual({t["id"]: t.get("settings") for t in tools if t.get("settings")},
                         {"claude": "settings/claude", "mail": "settings/mail"})
        # The answer Settings has already asked for is used, rather than asking Claude Code again.
        with mock.patch.object(doctor, "claude_check") as asked:
            doctor.tool_checks({}, {"ok": False, "what": "not signed in", "fix": "log in"})
        asked.assert_not_called()

    def test_a_missing_program_every_draft_needs_opens_tools_check(self):
        with self.programs(pdf=False):
            todos = support.PROGRAM_TODOS()
            self.assertEqual([(t["step"], t["severity"]) for t in todos], [("tools", "bad")])
            self.assertIn("LibreOffice or Word isn't on this computer", todos[0]["what"])
            self.assertEqual(self.section("tools")["summary"], "Missing LibreOffice or Word")
            with mock.patch.object(doctor, "program_todos", support.PROGRAM_TODOS):
                self.assertEqual(self.section("tools")["status"], "attention")
        with self.programs():
            self.assertEqual(support.PROGRAM_TODOS(), [])
            self.assertEqual((self.section("tools")["status"], self.section("tools")["summary"]), ("set", "python-docx and Word found"))
        # An optional one missing is no one's to-do.
        with self.programs(pdftotext=None):
            self.assertEqual(support.PROGRAM_TODOS(), [])

    def test_sections_set_on_the_settings_tab_say_where(self):
        for step_id, where in (("priorities", "settings/ranking"), ("schedule", "settings/run")):
            step = self.section(step_id)
            self.assertEqual(step["fallback"], where)
            self.assertTrue(step["settings"])
            self.assertNotIn("Until it's built", step["meanwhile"])

    def test_a_backup_copies_the_database_whole_and_keeps_the_newest(self):
        self.database()
        with mock.patch.object(backup, "KEEP", 3):
            made = [backup.make(self.root) for _ in range(5)]
        kept = backup.copies(self.root)
        self.assertEqual([c["name"] for c in kept], [m["name"] for m in made[:-4:-1]])
        self.assertFalse(list((self.root / "data" / "backups").glob("*.partial")))
        with closing(sqlite3.connect(self.root / "data" / "backups" / kept[0]["name"])) as copy:
            self.assertEqual(copy.execute("SELECT value FROM meta WHERE key = 'backed_up'").fetchall(), [("kept",)])
        self.assertEqual(self.section("workspace")["status"], "set")
        self.assertTrue(self.section("workspace")["summary"].startswith("Last backup "))

    def test_an_old_backup_isnt_recent(self):
        self.database()
        backup.make(self.root)
        later = datetime.now(UTC) + timedelta(days=backup.FRESH_DAYS + 1)
        self.assertFalse(backup.is_fresh(self.root, later))
        self.assertTrue(backup.is_fresh(self.root))

    def test_nothing_to_back_up_says_so(self):
        with self.assertRaisesRegex(ValueError, "no data/pyrite.db yet"):
            backup.make(self.root)
        with self.assertRaisesRegex(ValueError, "demo"):
            backup.make(store.EXAMPLE_ROOT)
        self.assertFalse((self.root / "data" / "backups").exists())

    def test_the_section_names_the_folder_and_whether_git_keeps_the_database(self):
        self.database()
        about = server._back_up({})
        self.assertEqual(about["folder"], str(self.root))
        self.assertEqual(about["made"]["name"], about["backups"]["copies"][0]["name"])
        self.assertTrue(about["database"]["exists"])
        # A temporary folder is in no repository, or in one further up that isn't its own.
        self.assertFalse(about["git"]["repo"])
        self.assertFalse(about["git"]["tracked"])

    def test_a_git_workspace_that_keeps_the_database_says_when_it_was_committed(self):
        if not shutil.which("git"):
            self.skipTest("git isn't installed")
        self.database()
        git = ["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.com"]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "data/pyrite.db"], check=True)
        subprocess.run([*git, "commit", "-q", "-m", "Back up"], check=True)
        state = backup.about(self.root)["git"]
        self.assertEqual((state["repo"], state["tracked"], state["changed"], state["remote"]), (True, True, False, False))
        self.assertTrue(state["committed"].startswith("20"))


class PageScripts(unittest.TestCase):
    def test_every_script_the_page_loads_is_served_and_every_section_file_is_loaded(self):
        page = server.page().decode()
        loaded = re.findall(r'<script src="([^"]+)"', page)
        self.assertEqual(loaded[0], "/static/profile.js")  # Each section registers itself with profile.js.
        self.assertEqual(loaded[-1], "/static/app.js")  # app.js starts the page, so everything else loads first.
        self.assertTrue(all(src in server.STATIC_FILES for src in loaded), loaded)
        sections = {f"/static/profile/{path.name}" for path in (server.STATIC / "profile").glob("*.js")}
        self.assertLessEqual(sections, set(loaded))
        self.assertEqual(len(loaded), len(set(loaded)))
        self.assertNotIn(server.SECTIONS_MARK, page)

    def test_what_needs_you_opens_a_section_set_on_settings_there(self):
        # A finding can name What comes first, whose settings are on the Settings tab, so its button goes the way the
        # section's card does rather than to an empty section here.
        script = (server.STATIC / "profile.js").read_text(encoding="utf-8")
        needs = script[script.index("function profileNeeds("):script.index("function profileOpen(")]
        self.assertIn("onclick: () => profileOpen(step)", needs)
        self.assertNotIn("profileGo(", needs)
        self.assertIn("profileOpenLabel(step)", needs)

    def test_the_page_served_is_the_one_with_the_section_scripts(self):
        httpd = server.make_server(0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{httpd.server_address[1]}/", timeout=5) as resp:
                self.assertEqual(resp.read(), server.page())
        finally:
            httpd.shutdown()
            httpd.server_close()


class NoNameDefinedTwice(unittest.TestCase):
    """Two branches can each add a function of the same name to one module and merge without a conflict. The second
    then quietly replaces the first, as happened with two editors' _prospects in steps.py."""

    def test_no_module_defines_a_top_level_function_or_class_twice(self):
        for path in sorted((support.CODE_ROOT / "tools").rglob("*.py")):
            seen: dict[str, int] = {}
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    with self.subTest(path=path.name, name=node.name):
                        self.assertNotIn(node.name, seen, f"also defined on line {seen.get(node.name)}")
                    seen[node.name] = node.lineno


if __name__ == "__main__":
    unittest.main()
