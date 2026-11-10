"""Roles you want on the Profile tab: a role type's industries, picked from the ones under [[promote.industry]], and
the Roles so far line in run-notes.md. The rest of the section is tested in test_steps.py."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

import support  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import profile, score, steps, store

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"
ROLES_SO_FAR = "- **Roles so far:** principal firmware, robotics software, engineering manager and AI tooling roles.\n"


def lf(result: dict[str, Any], key: str) -> str:
    """A drafted file with Unix line endings. A checkout may have either, and a draft keeps whichever the file has."""
    return result["changes"][key].replace("\r\n", "\n")


def changed_lines(result: dict[str, Any]) -> list[str]:
    return [line for d in result["diffs"] for line in d["lines"] if line[:1] in "+-"]


class Roles(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.reload()

    def reload(self):
        self.view = {**profile.view(), **steps.view()}

    def write(self, key: str, text: str):
        (self.root / profile.FILES[key]).write_bytes(text.encode())
        self.reload()

    def text(self, key: str) -> str:
        return profile.read(key).replace("\r\n", "\n")

    def draft(self, edits):
        return steps.draft("roles", edits, self.view["versions"])

    def save(self, result):
        profile.write(result["changes"], self.view["versions"], "test")
        self.reload()

    def form(self) -> dict[str, Any]:
        """The section's form as the page first fills it in: everything as it is."""
        roles = self.view["roles"]
        return {"tracks": [{key: track[key] for key in ("index", "name", "titles", "patterns", "needs_level", "industries",
                                                         "emphasis")} for track in roles["tracks"]],
                "roles_so_far": roles["roles_so_far"]["text"],
                **{key: list(roles[key]) for key in ("level_top", "level_mid", "exclude_titles")},
                "keywords": [list(row) for row in roles["keywords"]], "flags": [list(row) for row in roles["flags"]]}

    def track(self, form: dict[str, Any], name: str) -> dict[str, Any]:
        return next(t for t in form["tracks"] if t["name"] == name)

    def files(self) -> dict[str, bytes]:
        return {key: (self.root / path).read_bytes() for key, path in profile.FILES.items() if (self.root / path).exists()}

    def with_industries(self, line: str):
        """search.toml with `line` added to the Engineering leadership role type, as someone might write it by hand."""
        text = self.text("config").replace('name = "Engineering leadership"\n', f'name = "Engineering leadership"\n{line}\n')
        self.write("config", text)

    # ---- What the section shows ----

    def test_the_industries_to_pick_from_and_roles_so_far_are_shown(self):
        roles = self.view["roles"]
        self.assertEqual(roles["industry_names"], ["Robotics", "Medical devices", "Semiconductors"])
        self.assertEqual([t["industries"] for t in roles["tracks"]], [[], [], [], []])
        self.assertEqual(roles["roles_so_far"]["text"],
                         "principal firmware, robotics software, engineering manager and AI tooling roles.")
        self.assertEqual(roles["roles_so_far"]["more"], 0)

    def test_an_unchanged_form_leaves_every_file_byte_for_byte(self):
        self.with_industries('industries = ["Robotics", "medical devices"]  # by hand, one spelled wrong')
        before = self.files()
        result = self.draft({**self.form(), "test": "Director of Engineering"})
        self.assertEqual((result["changes"], result["count"]), ({}, 0))
        self.assertEqual(before, self.files())
        # The name no industry has is kept, since it wasn't changed here, but it's pointed out.
        self.assertEqual(result["notes"], ["“medical devices” isn't an industry under Settings › Cities and industries, "
                                           "which has “Medical devices”, so Engineering leadership takes no posting for it."])
        why = next(t for t in result["preview"]["test"]["tracks"] if t["name"] == "Engineering leadership")["why"]
        self.assertEqual(why, "only for postings in Robotics, medical devices")

    # ---- A role type's industries ----

    def test_industries_are_set_from_the_names_there_and_saved(self):
        form = self.form()
        self.track(form, "Engineering leadership")["industries"] = ["Robotics", "semiconductors"]
        result = self.draft(form)
        self.assertEqual(set(result["changes"]), {"config"})
        self.assertEqual(changed_lines(result), ['+industries = ["Robotics", "Semiconductors"]'])
        self.assertEqual(result["count"], 2)
        track = tomllib.loads(lf(result, "config"))["track"][2]
        self.assertEqual((track["name"], track["industries"]), ("Engineering leadership", ["Robotics", "Semiconductors"]))
        self.save(result)
        self.assertEqual(self.track(self.form(), "Engineering leadership")["industries"], ["Robotics", "Semiconductors"])
        self.assertEqual(self.draft(self.form())["changes"], {})

    def test_the_scorer_then_takes_the_role_type_only_in_those_industries(self):
        form = self.form()
        self.track(form, "Engineering leadership")["industries"] = ["Medical devices"]
        cfg = steps._with_scoring(tomllib.loads(lf(self.draft(form), "config")))
        self.assertIsNone(score.match_track("Director of Engineering", cfg, {"company": "Initech", "description": ""}))
        self.assertEqual(score.match_track("Director of Engineering", cfg, {"company": "Umbrella Instruments", "description": ""})[0],
                         "Engineering leadership")

    def test_an_industry_that_isnt_there_is_refused(self):
        form = self.form()
        self.track(form, "AI systems")["industries"] = ["Robotics", "Aerospace"]
        with self.assertRaises(ValueError) as caught:
            self.draft(form)
        self.assertIn("“Aerospace” isn't an industry under Settings › Cities and industries. Pick one of Robotics, "
                      "Medical devices, Semiconductors", str(caught.exception))
        for bad, message in (([3], "should be text"), (["Robo\ntics"], "line break"), ("Robotics", "should be a list")):
            self.track(form, "AI systems")["industries"] = bad
            with self.assertRaises(ValueError, msg=message) as caught:
                self.draft(form)
            self.assertIn(message, str(caught.exception))
        # With none under [[promote.industry]], there's nothing to pick, and the refusal says where to add one.
        text = self.text("config")
        self.write("config", text[:text.index("[[promote.industry]]")] + text[text.index("# Roles to pursue."):])
        self.assertEqual(self.view["roles"]["industry_names"], [])
        form = self.form()
        self.track(form, "AI systems")["industries"] = ["Robotics"]
        with self.assertRaises(ValueError) as caught:
            self.draft(form)
        self.assertIn("Add it there first", str(caught.exception))

    def test_industries_written_by_hand_change_a_name_at_a_time_and_keep_their_comment(self):
        self.with_industries('# Only where it counts.\nindustries = ["Robotics", "robots"]  # robots is a typo')
        form = self.form()
        lead = self.track(form, "Engineering leadership")
        self.assertEqual(lead["industries"], ["Robotics", "robots"])
        lead["industries"] = ["Robotics", "Medical devices"]  # The typo taken off, and an industry added.
        result = self.draft(form)
        self.assertEqual(changed_lines(result), ['-industries = ["Robotics", "robots"]  # robots is a typo',
                                                 '+industries = ["Robotics", "Medical devices"]  # robots is a typo'])
        self.assertIn('# Only where it counts.\nindustries = [', lf(result, "config"))
        self.assertEqual((result["count"], result["notes"][:-1]), (2, []))
        # Taking every one off takes the key off, so the role type takes postings in any industry.
        lead["industries"] = []
        config = lf(self.draft(form), "config")
        self.assertIn('name = "Engineering leadership"\n# Only where it counts.\ntitle = [', config)
        self.assertNotIn("industries", tomllib.loads(config)["track"][2])

    def test_a_form_without_industries_keeps_them(self):
        # As a page loaded before this change sends it.
        self.with_industries('industries = ["Robotics"]')
        form = self.form()
        for track in form["tracks"]:
            del track["industries"]
        self.track(form, "Engineering leadership")["needs_level"] = True
        result = self.draft(form)
        self.assertEqual(tomllib.loads(lf(result, "config"))["track"][2]["industries"], ["Robotics"])
        self.assertEqual(changed_lines(result), ["-needs_level = false", "+needs_level = true"])

    def test_a_new_role_type_can_be_limited_to_industries(self):
        form = self.form()
        form["tracks"].append({"index": None, "name": "Software", "titles": ["software engineer"], "patterns": [],
                               "needs_level": False, "industries": ["Robotics"], "emphasis": ""})
        config = lf(self.draft(form), "config")
        self.assertIn('[[track]]\nname = "Software"\ntitles = ["software engineer"]\nindustries = ["Robotics"]\n'
                      'needs_level = false\n', config)

    # ---- pyrite doctor ----

    def test_doctor_names_a_role_type_whose_industries_name_none_there_is(self):
        cfg = tomllib.loads(self.text("config"))
        self.assertEqual(score.unknown_industries(cfg), [])
        cfg["track"][0]["industries"] = ["Robotics", "robotics", "Aerospace"]
        cfg["track"][1]["industries"] = "Medical devices"  # One name written without the brackets reads as that name.
        self.assertEqual(score.unknown_industries(cfg), [("AI systems", "robotics", "Robotics"), ("AI systems", "Aerospace", None)])
        found = [todo for todo in support.WORKSPACE_TODOS(self.root, cfg) if "The role type" in todo["what"]]
        self.assertEqual([todo["what"] for todo in found], [
            "The role type AI systems in profile/search.toml is only for postings in “robotics”, but no "
            "[[promote.industry]] is called that, so it takes no posting for it.",
            "The role type AI systems in profile/search.toml is only for postings in “Aerospace”, but no "
            "[[promote.industry]] is called that, so it takes no posting for it."])
        self.assertEqual(found[0]["fix"], "Write it as “Robotics”: the names must match exactly, case and all.")
        self.assertIn("Roles you want", found[1]["fix"])
        self.assertEqual({todo["step"] for todo in found}, {"roles"})

    # ---- Roles so far ----

    def test_roles_so_far_is_edited_as_one_line_of_prose(self):
        result = self.draft({**self.form(), "roles_so_far": "staff firmware and robotics software roles, some AI tooling"})
        self.assertEqual(set(result["changes"]), {"run_notes"})
        self.assertEqual(changed_lines(result), [f"-{ROLES_SO_FAR.strip()}",
                                                 "+- **Roles so far:** staff firmware and robotics software roles, some AI tooling"])
        self.assertEqual(result["count"], 1)
        self.save(result)
        self.assertEqual(self.form()["roles_so_far"], "staff firmware and robotics software roles, some AI tooling")
        self.assertEqual(self.draft(self.form())["changes"], {})
        # Not kept in step with the role types: renaming one leaves it as you wrote it.
        form = self.form()
        self.track(form, "AI systems")["name"] = "Applied AI"
        self.assertIn("- **Roles so far:** staff firmware and robotics software roles, some AI tooling\n",
                      lf(self.draft(form), "run_notes"))

    def test_roles_so_far_emptied_keeps_its_label(self):
        result = self.draft({**self.form(), "roles_so_far": "  "})
        self.assertIn("\n- **Roles so far:**\n- **Model documents:**", lf(result, "run_notes"))
        with self.assertRaises(ValueError) as caught:
            self.draft({**self.form(), "roles_so_far": "two\nlines"})
        self.assertIn("line break", str(caught.exception))

    def test_roles_so_far_is_added_above_emphasis_by_track_when_it_isnt_there(self):
        self.write("run_notes", self.text("run_notes").replace(ROLES_SO_FAR, ""))
        self.assertEqual(self.view["roles"]["roles_so_far"], {"line": None, "text": "", "more": 0})
        self.assertEqual(self.draft(self.form())["changes"], {})
        result = self.draft({**self.form(), "roles_so_far": "firmware roles"})
        self.assertIn("`notes.md`.\n- **Roles so far:** firmware roles\n- **Emphasis by track:**\n", lf(result, "run_notes"))
        # A blank run-notes.md gets a heading too.
        self.write("run_notes", "")
        result = self.draft({**self.form(), "roles_so_far": "firmware roles"})
        self.assertEqual(result["changes"]["run_notes"], "# Run notes\n\n- **Roles so far:** firmware roles\n")

    def test_lines_under_roles_so_far_and_windows_line_endings_stay(self):
        text = self.text("run_notes").replace(ROLES_SO_FAR, ROLES_SO_FAR + "  - Mostly onsite.\n").replace("\n", "\r\n")
        self.write("run_notes", text)
        self.assertEqual(self.view["roles"]["roles_so_far"]["more"], 1)
        self.assertEqual(self.draft(self.form())["changes"], {})
        notes = self.draft({**self.form(), "roles_so_far": "firmware roles"})["changes"]["run_notes"]
        self.assertIn("\r\n- **Roles so far:** firmware roles\r\n  - Mostly onsite.\r\n", notes)
        self.assertEqual(notes.count("\n"), notes.count("\r\n"))

    def test_roles_so_far_follows_a_change_to_emphasis_in_the_same_save(self):
        form = self.form()
        form["tracks"] = [t for t in form["tracks"] if t["name"] != "Engineering leadership"]
        form["roles_so_far"] = "firmware and AI tooling roles"
        result = self.draft(form)
        notes = lf(result, "run_notes")
        self.assertIn("- **Roles so far:** firmware and AI tooling roles\n", notes)
        self.assertNotIn("*Engineering leadership:*", notes)
        self.assertEqual(result["count"], 3)  # the role type, its emphasis line, and Roles so far


if __name__ == "__main__":
    unittest.main()
