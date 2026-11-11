"""The dashboard's Settings and Facts tabs, and opening a database made by an older version."""
import json
import re
import tempfile
import threading
import tomllib
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from support import CFG

from assay import factbank
from assay import numbers as number_checks
from pyrite import doctor, facts, inbox, options, profile, score, server, settings, store

SETTINGS_TOML = """# Top of the file
[run]
min_score = 40  # keep this comment

# About promotions
[promote]
city_points = 10
industry_points = 10
mentions_needed = 3
cities = [
  { name = "Springfield" },
]
# A comment inside the section
[[promote.industry]]
name = "Robotics"
terms = ['\\brobots?\\b']

# Roles to pursue
[[track]]
name = "AI"
title = ['\\bai\\b']

[dashboard]
allowed_hosts = ['tower']
"""
SETTINGS_FACTS = """# Fact bank
## Work
Wrote firmware and C++ control code.
## Do not use
- Internal name Bluebird
## Unsupported, so don't claim without new evidence
- Reinforcement learning
"""


class SettingsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.path = Path(self.tmp.name) / "search.toml"
        self.path.write_text(SETTINGS_TOML, encoding="utf-8", newline="\n")
        (Path(self.tmp.name) / "facts.md").write_text(SETTINGS_FACTS, encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)
        # The workspace too, so the copies a save keeps in History go in this test's own folder.
        for patcher in (mock.patch.object(store, "CONFIG_PATH", self.path), mock.patch.object(store, "ROOT", Path(self.tmp.name))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def kept(self, key: str) -> list[tuple[str, str]]:
        """What History holds for a file, newest first: each save's reason and the text the file had before it."""
        return [(entry["reason"], profile.kept(key, entry["stamp"])) for entry in profile.history() if entry["key"] == key]

    def form(self, **changes):
        return {"city_points": 10, "industry_points": 10, "mentions_needed": 3,
                "cities": [{"name": "Springfield"}], "industry": [{"name": "Robotics", "terms": [r"\brobots?\b"]}], **changes}

    def body(self, **changes):
        return {"version": settings.view()["version"], "promote": self.form(**changes)}

    def text(self):
        return self.path.read_bytes().decode("utf-8")


class Settings(SettingsBase):
    def test_a_save_changes_only_the_section(self):
        settings.save(self.body(cities=[{"name": "Shelbyville", "points": 4}]))
        text = self.text()
        before, after = SETTINGS_TOML.split("[promote]")[0], SETTINGS_TOML[SETTINGS_TOML.index("# Roles to pursue"):]
        self.assertTrue(text.startswith(before))
        self.assertTrue(text.endswith(after))
        self.assertIn("min_score = 40  # keep this comment", text)
        self.assertEqual(store.load_config()["promote"]["cities"], [{"name": "Shelbyville", "points": 4}])
        self.assertEqual(store.load_config()["track"][0]["name"], "AI")
        self.assertEqual(store.load_config()["dashboard"]["allowed_hosts"], ["tower"])

    def test_values_read_back_exactly(self):
        promote = self.form(
            cities=[{"name": 'Quote " City', "match": r"it's\s+here"}],
            industry=[{"name": "Medical devices", "points": 6, "terms": [r"\bfda\b", "don't"], "companies": ['Acme "Bio"'],
                       "wants": [{"name": "C++", "match": r"C\+\+"}, {"name": "Firmware"}]}])
        settings.save({"version": settings.view()["version"], "promote": promote})
        self.assertEqual(store.load_config()["promote"], promote)

    def test_saving_twice_changes_nothing_more(self):
        settings.save(self.body())
        first = self.text()
        settings.save(self.body())
        self.assertEqual(self.text(), first)

    def test_every_earlier_file_is_kept_in_history(self):
        settings.save(self.body(city_points=7))
        settings.save(self.body(city_points=8))
        settings.save(self.body(city_points=8))  # Nothing changed, so nothing to keep.
        kept = self.kept("config")
        self.assertEqual([reason for reason, _ in kept], ["Changed on the Settings tab"] * 2)
        # Two saves keep two copies, so the file from before the first can still be put back.
        self.assertEqual(kept[-1][1], SETTINGS_TOML)
        self.assertIn("city_points = 7", kept[0][1])
        self.assertFalse(self.path.with_name("search.previous.toml").exists())

    def test_windows_line_endings_are_kept(self):
        self.path.write_bytes(SETTINGS_TOML.replace("\n", "\r\n").encode("utf-8"))
        settings.save(self.body(city_points=7))
        self.assertNotIn("\n", self.text().replace("\r\n", ""))

    def test_a_file_with_a_byte_order_mark_reads_and_saves(self):
        # Windows PowerShell 5.1 writes one, and TOML can't read it.
        self.path.write_bytes(b"\xef\xbb\xbf" + SETTINGS_TOML.encode("utf-8"))
        self.assertEqual(settings.view()["promote"]["city_points"], 10)
        settings.save(self.body(city_points=7))
        self.assertEqual(store.load_config()["promote"]["city_points"], 7)

    def test_settings_the_form_cant_show_stop_the_save_instead_of_being_lost(self):
        cases = {
            "[promote.extra]": SETTINGS_TOML.replace("# A comment inside the section\n", "[promote.extra]\nx = 1\n"),
            "points on the skill Firmware of Robotics": SETTINGS_TOML.replace(
                "terms = ['\\brobots?\\b']", "terms = ['\\brobots?\\b']\nwants = [{ name = \"Firmware\", points = 3 }]"),
            "note on the city Springfield": SETTINGS_TOML.replace('{ name = "Springfield" }', '{ name = "Springfield", note = "x" }'),
            "radius": SETTINGS_TOML.replace("mentions_needed = 3", "mentions_needed = 3\nradius = 30"),
        }
        for named, text in cases.items():
            with self.subTest(named):
                self.assertNotEqual(text, SETTINGS_TOML)
                self.path.write_text(text, encoding="utf-8", newline="\n")
                with self.assertRaisesRegex(ValueError, rf"has {re.escape(named)},.*Nothing was saved"):
                    settings.save(self.body(city_points=7))
                self.assertEqual(self.text(), text)

    def test_a_section_is_added_if_there_is_none(self):
        self.path.write_text("[run]\nmin_score = 40\n", encoding="utf-8", newline="\n")
        settings.save({"version": settings.view()["version"], "promote": self.form()})
        config = store.load_config()
        self.assertEqual(config["run"]["min_score"], 40)
        self.assertEqual(config["promote"]["cities"], [{"name": "Springfield"}])

    def test_bad_input_leaves_the_file_alone(self):
        cases = {
            "broken pattern": {"cities": [{"name": "X", "match": "("}]},
            "broken term": {"industry": [{"name": "X", "terms": ["["]}]},
            "no name": {"cities": [{"name": "  "}]},
            "listed twice": {"cities": [{"name": "X"}, {"name": "x"}]},
            "line break": {"cities": [{"name": "X\n[dashboard]\nallowed_hosts = ['evil.test']"}]},
            "line break in pattern": {"cities": [{"name": "X", "match": "a\nb"}]},
            "text for points": {"city_points": "ten"},
            "boolean points": {"city_points": True},
            "too many points": {"cities": [{"name": "X", "points": 1000}]},
            "negative points": {"industry_points": -1},
            "no mentions": {"mentions_needed": 0},
            "can never match": {"industry": [{"name": "X"}]},
            "not a list": {"cities": "Springfield"},
            "not an entry": {"cities": ["Springfield"]},
        }
        for label, changes in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    settings.save(self.body(**changes))
                self.assertEqual(self.text(), SETTINGS_TOML)

    def test_a_name_can_not_reach_another_section(self):
        name = "x\" ] [dashboard] allowed_hosts = ['evil.test'] #"
        settings.save(self.body(cities=[{"name": name}]))
        config = store.load_config()
        self.assertEqual(config["dashboard"]["allowed_hosts"], ["tower"])
        self.assertEqual(config["promote"]["cities"][0]["name"], name)

    def test_a_stale_form_is_refused(self):
        old = self.body(city_points=1)
        settings.save(self.body(city_points=2))
        with self.assertRaises(settings.Conflict):
            settings.save(old)
        self.assertEqual(store.load_config()["promote"]["city_points"], 2)

    def test_another_section_changing_is_not_a_conflict(self):
        old = self.body(city_points=1)
        self.path.write_text(SETTINGS_TOML.replace("min_score = 40", "min_score = 50"), encoding="utf-8", newline="\n")
        settings.save(old)
        self.assertEqual(store.load_config()["run"]["min_score"], 50)

    def test_only_the_section_can_be_changed(self):
        settings.save({**self.body(), "dashboard": {"allowed_hosts": ["evil.test"]}, "guard": {"forbidden": []}})
        self.assertEqual(store.load_config()["dashboard"]["allowed_hosts"], ["tower"])

    def test_skills_come_from_what_may_be_claimed(self):
        wants = [{"name": "Firmware"}, {"name": "Control software", "match": r"control code"}, {"name": "Reinforcement learning"},
                 {"name": "Bluebird"}, {"name": "Photolithography"}]
        settings.save(self.body(industry=[{"name": "Robotics", "terms": ["robot"], "wants": wants}]))
        self.assertEqual(settings.view()["skills"]["Robotics"],
                         {"have": ["Firmware", "Control software"], "gaps": ["Reinforcement learning", "Bluebird", "Photolithography"]})

    def test_wanted_skills_do_not_change_the_ranking(self):
        job = {"score": 60, "company": "Initech", "title": "Robotics Lead"}
        plain = {**CFG, "promote": {"industry_points": 10, "industry": [{"name": "Robotics", "terms": ["robotics"]}]}}
        wanted = {**CFG, "promote": {"industry_points": 10, "industry": [{"name": "Robotics", "terms": ["robotics"], "wants": [{"name": "Firmware"}]}]}}
        self.assertEqual(score.freshness(job, plain, date(2026, 11, 5))["rank"], score.freshness(job, wanted, date(2026, 11, 5))["rank"])


class SettingsInTheDemo(SettingsBase):
    def test_the_demo_can_not_write_into_the_example(self):
        body = self.body(city_points=1)
        with mock.patch.object(store, "IS_EXAMPLE", True), self.assertRaises(ValueError):
            settings.save(body)
        self.assertEqual(self.text(), SETTINGS_TOML)


class HowPyriteRuns(SettingsBase):
    """The Settings tab's sections on Claude, mail, the daily run and the dashboard: single keys of search.toml."""

    def save(self, **values):
        return options.save({"version": options.view()["version"], "values": {name.replace("__", "."): value for name, value in values.items()}})

    def shown(self, name: str) -> dict[str, Any]:
        return next(field for section in options.view()["sections"] for panel in section["panels"]
                    for field in panel["fields"] if field["id"] == name)

    def test_each_setting_shows_what_the_file_holds_or_what_pyrite_does_without_it(self):
        self.path.write_text(SETTINGS_TOML + '\n[inbox]\nsource = "gmail"\nlookback_days = 21\n', encoding="utf-8", newline="\n")
        self.assertEqual(self.shown("inbox.source")["value"], "gmail")
        self.assertEqual(self.shown("inbox.lookback_days")["value"], 21)
        # Unset: a box stays empty and names the default, and a switch or a list shows the default itself.
        self.assertEqual((self.shown("claude.model")["value"], self.shown("claude.model")["unset"]), (None, "Claude Code's default"))
        self.assertEqual((self.shown("run.fix_attempts")["value"], self.shown("run.fix_attempts")["unset"]), (None, str(store.DEFAULT_FIX_ATTEMPTS)))
        self.assertIs(self.shown("dashboard.reach_out")["value"], True)
        self.assertIsNone(self.shown("claude.effort")["value"])
        self.assertNotIn("table", self.shown("claude.model"))

    def test_a_save_sets_the_keys_it_names_and_leaves_every_other_line_alone(self):
        self.save(claude__model="opus", claude__effort="high", run__tailor_per_day=3, dashboard__reach_out=False, inbox__source="gmail")
        text, cfg = self.text(), store.load_config()
        for line in SETTINGS_TOML.splitlines():
            self.assertIn(line, text)
        self.assertEqual(cfg["claude"], {"model": "opus", "effort": "high"})
        self.assertEqual(cfg["run"], {"min_score": 40, "tailor_per_day": 3})
        self.assertEqual(cfg["dashboard"], {"allowed_hosts": ["tower"], "reach_out": False})
        self.assertEqual(cfg["inbox"], {"source": "gmail"})
        self.assertEqual(cfg["promote"], tomllib.loads(SETTINGS_TOML)["promote"])
        self.assertEqual(self.kept("config"), [("Changed on the Settings tab", SETTINGS_TOML)])

    def test_emptying_a_setting_takes_its_line_out_so_the_default_applies(self):
        self.save(claude__model="sonnet", inbox__lookback_days=30, claude__effort="low")
        self.save(claude__model="", inbox__lookback_days=None, claude__effort=None)
        cfg = store.load_config()
        self.assertEqual((cfg["claude"], cfg["inbox"]), ({}, {}))

    def test_a_setting_left_at_its_default_is_not_written(self):
        self.save(dashboard__check_updates=True, inbox__source="imap", run__cover_letters=True, inbox__model=options.mail.DEFAULT_MODEL)
        self.assertEqual(self.text(), SETTINGS_TOML)
        self.assertEqual(self.kept("config"), [])

    def test_what_a_setting_can_not_hold_is_refused_and_the_file_left_alone(self):
        refused = (
            {"claude.model": "--dangerously-skip-permissions"}, {"claude.model": "two words"}, {"claude.model": 7},
            {"claude.effort": "extreme"}, {"inbox.source": "pop3"}, {"inbox.source": ""},
            {"run.tailor_per_day": 500}, {"run.tailor_per_day": "3"}, {"run.tailor_per_day": True}, {"run.tailor_per_day": 2.5},
            {"run.triage_per_day": None}, {"inbox.lookback_days": 0}, {"dashboard.reach_out": "yes"}, {},
            # One good value doesn't carry a bad one in with it.
            {"claude.effort": "high", "run.tailor_per_day": -1},
        )
        for values in refused:
            with self.subTest(values=values), self.assertRaises(ValueError):
                options.save({"version": options.view()["version"], "values": values})
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_nothing_outside_the_list_can_be_reached(self):
        for name, value in (("guard.forbidden", []), ("guard.max_resume_pages", 9), ("dashboard.allowed_hosts", ["evil.test"]),
                            ("dashboard.port", 80), ("workday.autofill", True), ("promote.city_points", 50), ("run", {}), ("claude", "x")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "isn't a setting this tab can change"):
                options.save({"version": options.view()["version"], "values": {name: value}})
        self.assertEqual(self.text(), SETTINGS_TOML)
        # The fact check's rules, the filters and the names the dashboard answers to are never in the list.
        self.assertLessEqual({field["table"] for field in options.FIELDS.values()}, {"claude", "inbox", "market", "skills", "culture", "run", "dashboard", "relocation"})
        self.assertNotIn("dashboard.allowed_hosts", options.FIELDS)
        self.assertNotIn("dashboard.port", options.FIELDS)

    def test_a_setting_that_would_loosen_a_check_is_refused_even_if_it_were_listed(self):
        autofill = {"id": "workday.autofill", "table": "workday", "key": "autofill", "kind": "switch", "label": "Autofill", "default": False}
        with mock.patch.dict(options.FIELDS, {"workday.autofill": autofill}), self.assertRaisesRegex(ValueError, "loosen a check"):
            self.save(workday__autofill=True)
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_a_stale_form_is_refused_but_a_change_elsewhere_in_the_file_is_not_a_conflict(self):
        version = options.view()["version"]
        settings.save(self.body(city_points=7))
        options.save({"version": version, "values": {"claude.effort": "high"}})
        with self.assertRaises(settings.Conflict):
            options.save({"version": version, "values": {"claude.effort": "low"}})
        self.assertEqual(store.load_config()["claude"], {"effort": "high"})
        self.assertEqual(store.load_config()["promote"]["city_points"], 7)

    def test_windows_line_endings_are_kept(self):
        self.path.write_bytes(SETTINGS_TOML.replace("\n", "\r\n").encode("utf-8"))
        self.save(claude__model="opus", run__tailor_per_day=3)
        self.assertNotIn("\n", self.text().replace("\r\n", ""))

    def test_the_demo_can_not_write_into_the_example(self):
        version = options.view()["version"]
        with mock.patch.object(store, "IS_EXAMPLE", True):
            self.assertIs(options.view()["editable"], False)
            with self.assertRaises(ValueError):
                options.save({"version": version, "values": {"claude.effort": "high"}})
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_the_example_holds_every_number_the_run_can_not_do_without(self):
        with (store.EXAMPLE_ROOT / "profile" / "search.toml").open("rb") as handle:
            example = tomllib.load(handle)
        for field in options.FIELDS.values():
            if field.get("required"):
                self.assertIsInstance(example[field["table"]][field["key"]], int, field["id"])


class FactsTab(SettingsBase):
    """The Facts tab reads and writes two named files in the workspace's profile folder, and nothing else."""

    def facts_path(self):
        return self.path.with_name("facts.md")

    def file(self, key="facts"):
        return next(f for f in facts.view()["files"] if f["key"] == key)

    def save(self, text, key="facts", version=None):
        return facts.save({"file": key, "version": version or self.file(key)["version"], "text": text})

    def test_both_files_are_shown_and_a_missing_one_reads_as_empty(self):
        shown = facts.view()
        self.assertEqual([f["key"] for f in shown["files"]], ["facts", "terms"])
        self.assertEqual(self.file()["text"], SETTINGS_FACTS)
        self.assertEqual((self.file("terms")["text"], self.file("terms")["path"]), ("", "profile/approved-terms.txt"))
        self.assertTrue(shown["editable"])

    def test_a_save_writes_the_file_and_keeps_every_one_before_in_history(self):
        changed = SETTINGS_FACTS.replace("Wrote firmware", "Wrote firmware for 12 robots")
        shown = self.save(changed)
        self.assertEqual(self.facts_path().read_text(encoding="utf-8"), changed)
        self.assertEqual(shown["files"][0]["text"], changed)
        self.assertEqual(self.text(), SETTINGS_TOML)
        self.save(changed + "- One more\n")
        self.save(changed + "- One more\n")  # Nothing changed, so nothing to keep.
        kept = [(reason, text.replace("\r\n", "\n")) for reason, text in self.kept("facts")]
        # Two saves keep two copies, so the file from before the first can still be put back.
        self.assertEqual(kept, [("Changed on the Facts tab", changed), ("Changed on the Facts tab", SETTINGS_FACTS)])
        self.assertFalse(self.path.with_name("facts.previous.md").exists())

    def test_the_checker_uses_what_was_saved(self):
        self.save(SETTINGS_FACTS.replace("## Do not use", "- Shipped to 4,321 sites\n## Do not use"))
        self.assertIn("4321", number_checks.numbers(factbank.claimable(self.facts_path().read_text(encoding="utf-8"))))

    def test_a_stale_page_is_refused(self):
        version = self.file()["version"]
        self.facts_path().write_text(SETTINGS_FACTS + "\n- Added by hand\n", encoding="utf-8")
        with self.assertRaises(settings.Conflict):
            self.save("# Replaced\n", version=version)
        self.assertIn("Added by hand", self.facts_path().read_text(encoding="utf-8"))

    def test_only_the_two_named_files_can_be_written(self):
        for key in ("search", "../search.toml", "facts.md", None, ["facts"]):
            with self.subTest(key), self.assertRaises((ValueError, TypeError)):
                facts.save({"file": key, "version": "x", "text": "[guard]\nforbidden = []\n"})
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_bad_text_leaves_the_file_alone(self):
        for text in ("", "   \n", "has a \x00 byte", "bell \x07", "x" * (facts.MAX_BYTES + 1), None, 5):
            with self.subTest(repr(text)[:20]), self.assertRaises(ValueError):
                self.save(text)
        self.assertEqual(self.facts_path().read_text(encoding="utf-8"), SETTINGS_FACTS)

    def test_approved_terms_can_be_created_and_emptied(self):
        self.save("RTOS\nFreeRTOS", key="terms")
        terms = self.path.with_name("approved-terms.txt")
        self.assertEqual(terms.read_text(encoding="utf-8"), "RTOS\nFreeRTOS\n")
        self.save("", key="terms")
        self.assertEqual(terms.read_text(encoding="utf-8"), "\n")
        # The first save made the file, so there was nothing before it to keep.
        self.assertEqual(self.kept("terms"), [("Changed on the Facts tab", "RTOS\nFreeRTOS\n")])

    def test_windows_line_endings_are_kept(self):
        self.facts_path().write_bytes(SETTINGS_FACTS.replace("\n", "\r\n").encode())
        self.assertNotIn("\r", self.file()["text"])
        self.save(SETTINGS_FACTS + "- One more\n")
        saved = self.facts_path().read_bytes()
        self.assertIn(b"- One more\r\n", saved)
        self.assertNotIn(b"\r\r", saved)

    def test_the_demo_can_not_change_the_fictional_candidate(self):
        with mock.patch.object(store, "IS_EXAMPLE", True):
            self.assertFalse(facts.view()["editable"])
            with self.assertRaisesRegex(ValueError, "demo"):
                self.save("# Changed\n")
        self.assertEqual(self.facts_path().read_text(encoding="utf-8"), SETTINGS_FACTS)


class FactsOverHttp(SettingsBase):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method="GET", headers=None, body=None):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/facts"
        request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def post(self, body, **headers):
        return self.call("POST", {"Content-Type": "application/json", **headers}, json.dumps(body).encode())

    def test_read_save_and_a_clear_answer_when_refused(self):
        status, data = self.call()
        self.assertEqual((status, data["files"][0]["text"]), (200, SETTINGS_FACTS))
        version = data["files"][0]["version"]
        status, data = self.post({"file": "facts", "version": version, "text": SETTINGS_FACTS + "- More\n"})
        self.assertEqual(status, 200)
        self.assertIn("- More", data["files"][0]["text"])
        self.assertEqual(self.post({"file": "facts", "version": version, "text": "# Stale\n"})[0], 409)
        self.assertEqual(self.post({"file": "elsewhere", "version": version, "text": "x"})[0], 400)

    def test_other_sites_and_hosts_can_not_read_or_change_the_facts(self):
        body = {"file": "facts", "version": self.call()[1]["files"][0]["version"], "text": "# Replaced by another site\n"}
        self.assertEqual(self.post(body, Origin="https://evil.test")[0], 403)
        self.assertEqual(self.post(body, Host="evil.test")[0], 403)
        self.assertEqual(self.call(headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.call("POST", {"Content-Type": "text/plain"}, json.dumps(body).encode())[0], 415)
        self.assertEqual(self.path.with_name("facts.md").read_text(encoding="utf-8"), SETTINGS_FACTS)


class SettingsOverHttp(SettingsBase):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method="GET", headers=None, body=None, path="/api/settings"):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"
        request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def post(self, body, path="/api/settings", **headers):
        return self.call("POST", {"Content-Type": "application/json", **headers}, json.dumps(body).encode(), path)

    def test_how_pyrite_runs_is_read_and_saved_beside_the_cities_and_industries(self):
        status, data = self.call()
        self.assertEqual((status, [section["id"] for section in data["options"]["sections"]]), (200, ["claude", "mail", "run", "dashboard", "relocation"]))
        status, data = self.post({"version": data["options"]["version"], "values": {"claude.effort": "high"}}, "/api/settings/options")
        self.assertEqual((status, store.load_config()["claude"]), (200, {"effort": "high"}))
        # The answer is the whole tab again, so the page's copy of the other half stays whole.
        self.assertEqual(data["promote"]["cities"], [{"name": "Springfield"}])
        status, data = self.post({"version": data["version"], "promote": self.form(city_points=7)})
        self.assertEqual((status, data["options"]["version"]), (200, options.view()["version"]))

    def test_a_refused_setting_gets_a_clear_answer_and_changes_nothing(self):
        version = self.call()[1]["options"]["version"]
        path = "/api/settings/options"
        status, data = self.post({"version": version, "values": {"claude.model": "--print"}}, path)
        self.assertEqual(status, 400)
        self.assertIn("isn't a model's name", data["error"])
        self.assertEqual(self.post({"version": "old", "values": {"claude.model": "opus"}}, path)[0], 409)
        body = {"version": version, "values": {"claude.model": "opus"}}
        self.assertEqual(self.post(body, path, Origin="https://evil.test")[0], 403)
        self.assertEqual(self.post(body, path, Host="evil.test")[0], 403)
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_the_connections_are_reported_without_asking_claude_code_each_time(self):
        signed_in = {"ok": True, "what": "Claude Code, signed in, at claude", "fix": ""}
        with mock.patch.object(options, "_claude_seen", None), mock.patch.object(doctor, "claude_check", return_value=signed_in) as asked, \
                mock.patch.object(doctor, "DB_PATH", Path(self.tmp.name) / "none.db"), \
                mock.patch.object(inbox, "CREDENTIALS_PATH", Path(self.tmp.name) / "imap.env"):
            status, data = self.call(path="/api/settings/status")
            self.assertEqual((status, data["claude"]), (200, signed_in))
            self.assertEqual((data["mail"]["ok"], data["mail"]["last_ok"]), (None, ""))
            self.call(path="/api/settings/status")
            self.assertEqual(asked.call_count, 1)
            self.call(path="/api/settings/status?fresh=1")
            self.assertEqual(asked.call_count, 2)
            self.assertEqual(self.call(headers={"Host": "evil.test"}, path="/api/settings/status")[0], 403)

    def test_read_and_save(self):
        status, data = self.call()
        self.assertEqual((status, data["promote"]["cities"]), (200, [{"name": "Springfield"}]))
        status, data = self.post({"version": data["version"], "promote": self.form(city_points=7)})
        self.assertEqual((status, data["promote"]["city_points"]), (200, 7))

    def test_bad_input_and_stale_forms_get_a_clear_answer(self):
        version = self.call()[1]["version"]
        status, data = self.post({"version": version, "promote": self.form(cities=[{"name": "X", "match": "("}])})
        self.assertEqual(status, 400)
        self.assertIn("valid pattern", data["error"])
        self.assertEqual(self.post({"version": "old", "promote": self.form()})[0], 409)
        self.assertEqual(self.text(), SETTINGS_TOML)

    def test_other_sites_and_hosts_can_not_read_or_save(self):
        body = {"version": self.call()[1]["version"], "promote": self.form(city_points=1)}
        self.assertEqual(self.post(body, Origin="https://evil.test")[0], 403)
        self.assertEqual(self.post(body, Host="evil.test")[0], 403)
        self.assertEqual(self.call(headers={"Host": "evil.test"})[0], 403)
        self.assertEqual(self.call("POST", {"Content-Type": "text/plain"}, json.dumps(body).encode())[0], 415)
        self.assertEqual(self.text(), SETTINGS_TOML)


class OlderDatabase(unittest.TestCase):
    def test_gains_listings_and_keeps_its_jobs(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "old.db"
            conn = store.connect(path)
            conn.execute("""INSERT INTO jobs (source_key, source_id, company, title, first_seen, last_seen, posted_at)
                            VALUES ('greenhouse:a', '1', 'A', 'T', 'x', 'x', '2026-01-01'), ('seed', 's', 'B', 'T', 'x', 'x', NULL)""")
            conn.commit()
            for statement in ("DROP TABLE listings", "ALTER TABLE jobs DROP COLUMN reposts", "ALTER TABLE jobs DROP COLUMN redates",
                              "ALTER TABLE jobs DROP COLUMN first_posted_at", "ALTER TABLE jobs DROP COLUMN last_reposted_at",
                              "ALTER TABLE source_status DROP COLUMN tracked_since"):
                conn.execute(statement)
            conn.commit()
            conn.close()
            for _ in range(2):  # The second connection must leave it alone.
                conn = store.connect(path)
                job = conn.execute("SELECT * FROM jobs WHERE source_key = 'greenhouse:a'").fetchone()
                self.assertEqual((job["first_posted_at"], job["reposts"]), ("2026-01-01", 0))
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 2)
                self.assertEqual([tuple(r) for r in conn.execute("SELECT source_key, source_id FROM listings")], [("greenhouse:a", "1")])
                conn.close()

    def test_gains_the_sent_columns_and_marks_reasons_an_old_version_cut(self):
        cut = ("Strong on firmware, but the posting wants a product owner, and your record shows program rather than product manage"
               + " and more" * 40)[:300]
        whole = ("A reason of exactly three hundred characters that ends on a full stop" + " so" * 90)[:299] + "."
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "old.db"
            conn = store.connect(path)
            for source_id, reason in (("1", cut), ("2", whole), ("3", "Short and whole.")):
                conn.execute("""INSERT INTO jobs (source_key, source_id, company, title, first_seen, last_seen, fit_reason)
                                VALUES ('greenhouse:a', ?, 'A', 'T', 'x', 'x', ?)""", (source_id, reason))
            conn.execute("ALTER TABLE jobs DROP COLUMN sent_files")
            conn.execute("ALTER TABLE jobs DROP COLUMN sent_ack")
            conn.commit()
            conn.close()
            for _ in range(2):  # Marked once: the second connection finds nothing left to mark.
                conn = store.connect(path)
                self.assertLessEqual({"sent_files", "sent_ack"}, {row["name"] for row in conn.execute("PRAGMA table_info(jobs)")})
                reasons = [r[0] for r in conn.execute("SELECT fit_reason FROM jobs ORDER BY source_id")]
                self.assertEqual(reasons, [cut + "…", whole, "Short and whole."])
                conn.close()

    def test_gains_the_columns_that_let_you_clear_a_runs_profile_warning(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "old.db"
            conn = store.connect(path)
            conn.execute("INSERT INTO tasks (kind, started_at, updated_at, finished_at, ok, detail) VALUES ('tailor', 'x', 'x', 'x', 0, 'Stopped.')")
            conn.execute("ALTER TABLE tasks DROP COLUMN problem")
            conn.execute("ALTER TABLE tasks DROP COLUMN cleared_at")
            conn.commit()
            conn.close()
            conn = store.connect(path)
            self.assertLessEqual({"problem", "cleared_at"}, {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")})
            self.assertEqual(tuple(conn.execute("SELECT detail, problem, cleared_at FROM tasks").fetchone()), ("Stopped.", None, None))
            conn.close()


if __name__ == "__main__":
    unittest.main()
