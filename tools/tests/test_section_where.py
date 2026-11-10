"""Where you'll work's remote lists, its warning about a promoted city that isn't one of your places, and how its card
on the Profile hub counts places and patterns."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

import support  # Points Pyrite at a throwaway workspace before it loads.  # noqa: F401

from pyrite import profile, steps, store

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"
FORM = ("places", "local", "local_exact", "remote_home", "remote_elsewhere", "accept_remote", "accept_relocation", "market")


def lf(result: dict[str, Any], key: str) -> str:
    """A drafted file with Unix line endings. A checkout may have either, and a draft keeps whichever the file has."""
    return result["changes"][key].replace("\r\n", "\n")


class Where(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.load()

    def load(self):
        self.view = {**profile.view(), **steps.view()}

    def where(self, **changes):
        """A draft of the form as the page sends it: every field as it is, with a remote list that isn't set as empty."""
        form = {key: self.view["where"][key] or [] if key in steps.WHERE_REMOTE_LISTS else self.view["where"][key]
                for key in FORM}
        return steps.draft("where", {**form, **changes}, self.view["versions"])

    def save(self, result):
        profile.write(result["changes"], self.view["versions"], "test")
        self.load()

    def config(self) -> bytes:
        return (self.root / "profile" / "search.toml").read_bytes()

    def summary(self) -> str:
        return next(s for s in profile.view()["steps"] if s["id"] == "where")["summary"]

    # ---- The remote lists ----

    def test_a_remote_list_is_added_in_place_of_its_example(self):
        self.assertIsNone(self.view["where"]["remote_home"])
        result = self.where(remote_home=["\\buk\\b", "united kingdom"], remote_elsewhere=["\\bus\\b"])
        config = lf(result, "config")
        self.assertIn("remote_home = ['\\buk\\b', 'united kingdom']    # a remote role naming one of these is open to you\n", config)
        self.assertIn("remote_elsewhere = ['\\bus\\b']  # one naming these, and none of yours, is not\n", config)
        location = tomllib.loads(config)["location"]
        self.assertEqual((location["remote_home"], location["remote_elsewhere"]), (["\\buk\\b", "united kingdom"], ["\\bus\\b"]))
        self.assertEqual(location["local"], self.view["where"]["local"])
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["notes"], [])
        self.save(result)
        self.assertEqual(self.view["where"]["remote_home"], ["\\buk\\b", "united kingdom"])

    def test_one_pattern_at_a_time_and_the_last_takes_the_list(self):
        self.save(self.where(remote_home=["\\buk\\b", "united kingdom"], remote_elsewhere=["\\bus\\b", "canada"]))
        result = self.where(remote_elsewhere=["canada", "\\bemea\\b"])
        config = lf(result, "config")
        self.assertEqual(tomllib.loads(config)["location"]["remote_elsewhere"], ["canada", "\\bemea\\b"])
        self.assertIn("# one naming these, and none of yours, is not\n", config)
        self.assertEqual(result["count"], 2)
        # An empty list would still replace the built-in one, so the key goes, and with it the comment on its line.
        result = self.where(remote_home=[])
        location = tomllib.loads(lf(result, "config"))["location"]
        self.assertNotIn("remote_home", location)
        self.assertEqual(location["remote_elsewhere"], ["\\bus\\b", "canada"])
        self.assertEqual(result["count"], 2)

    def test_an_unchanged_where_with_remote_lists_leaves_search_toml_byte_for_byte(self):
        before = self.config()
        result = self.where(test="Remote - UK")
        self.assertEqual((result["changes"], result["count"]), ({}, 0))
        self.save(self.where(remote_home=["\\buk\\b", "united kingdom"], remote_elsewhere=["\\bus\\b"]))
        saved = self.config()
        self.assertNotEqual(saved, before)
        result = self.where(remote_home=self.view["where"]["remote_home"][::-1], test="Remote - UK")
        self.assertEqual((result["changes"], result["count"]), ({}, 0))
        # A form without the remote lists, as an older page sends it, changes nothing either.
        form = {key: self.view["where"][key] for key in FORM if key not in steps.WHERE_REMOTE_LISTS}
        self.assertEqual(steps.draft("where", form, self.view["versions"])["changes"], {})
        self.assertEqual(self.config(), saved)

    def test_a_bad_remote_pattern_is_refused(self):
        for changes in ({"remote_home": ["(unclosed"]}, {"remote_elsewhere": [".*"]}, {"remote_home": [""]},
                        {"remote_elsewhere": [3]}, {"remote_home": "\\buk\\b"}, {"remote_home": ["uk\nus"]}):
            with self.assertRaises(ValueError, msg=changes):
                self.where(**changes)
        self.assertNotIn("remote_home =", self.config().decode().replace("# remote_home =", ""))

    def test_one_remote_list_without_the_other_is_named(self):
        notes = self.where(remote_home=["\\buk\\b"])["notes"]
        self.assertTrue(any(note.startswith("remote_home is set and remote_elsewhere isn't") for note in notes), notes)
        notes = self.where(remote_elsewhere=["\\bus\\b"])["notes"]
        self.assertTrue(any(note.startswith("remote_elsewhere is set and remote_home isn't") for note in notes), notes)
        self.assertEqual(self.where(remote_home=["\\buk\\b"], remote_elsewhere=["\\bus\\b"])["notes"], [])
        # Without remote roles, neither list is read.
        notes = self.where(remote_home=["\\buk\\b"], accept_remote=False)["notes"]
        self.assertFalse(any("remote_elsewhere" in note for note in notes), notes)

    def test_a_location_is_judged_with_the_remote_lists_as_drafted(self):
        lists = {"remote_home": ["\\buk\\b"], "remote_elsewhere": ["\\bus\\b", "germany"]}
        for text, now, after, why in (("Remote - UK", "out", "remote", "'\\\\buk\\\\b' under remote_home"),
                                      ("Remote - US", "remote", "out", "under remote_elsewhere"),
                                      ("Remote - Japan", "out", "remote", "matches nothing under remote_home")):
            tested = self.where(**lists, test=text)["preview"]["test"]
            self.assertEqual((tested["now"], tested["after"]), (now, after), text)
            self.assertIn(why, tested["why"], text)
        # A place of yours is judged by it first, remote or not.
        tested = self.where(**lists, test="Remote - Madison, WI")["preview"]["test"]
        self.assertEqual(tested["after"], "local")

    # ---- A promoted city that isn't one of your places ----

    def test_a_promoted_city_outside_your_places_is_named(self):
        # The example promotes three made-up cities, none of them local.
        result = self.where(places=["Sunnydale"])
        self.assertEqual(result["preview"]["promoted_out"], ["Eagleton", "Hill Valley"])
        note = next(note for note in result["notes"] if "promoted" in note)
        self.assertIn("Eagleton and Hill Valley are promoted under Settings › Cities and industries", note)
        self.assertNotIn("Sunnydale", note)
        result = self.where(places=["Sunnydale", "Eagleton"])
        self.assertIn("Hill Valley is promoted under Settings › Cities and industries, but isn't one of your places",
                      " ".join(result["notes"]))
        self.assertEqual(self.where(places=["Sunnydale", "Eagleton", "Hill Valley"])["preview"]["promoted_out"], [])

    def test_a_promoted_city_is_named_only_when_the_filters_change_and_drop_it(self):
        # With relocation, an onsite posting anywhere is kept, so its promotion counts.
        self.assertEqual(self.where(accept_relocation=True)["preview"]["promoted_out"], [])
        # Changing only remote roles or the area for the Industries tab says nothing about it.
        for changes in ({"market": {"state": "Illinois", "metro": "", "country": ""}}, {"accept_remote": False},
                        {"remote_home": ["\\buk\\b"], "remote_elsewhere": ["\\bus\\b"]}):
            result = self.where(**changes)
            self.assertEqual(result["preview"]["promoted_out"], [], changes)
            self.assertFalse(any("promoted" in note for note in result["notes"]), result["notes"])
        local = [p for p in self.view["where"]["local"] if p != "verona"]
        self.assertEqual(self.where(local=local)["preview"]["promoted_out"], ["Sunnydale", "Eagleton", "Hill Valley"])

    # ---- The card on the hub ----

    def test_the_card_counts_places_and_patterns_apart(self):
        self.assertEqual(self.summary(), "11 location patterns, remote")
        self.save(self.where(places=["Springfield, IL", "Oak Park", "Evanston"]))
        self.assertEqual(self.summary(), "3 places and 11 patterns, remote")
        self.save(self.where(places=["Oak Park"], local=["sun prairie"], local_exact=[], accept_relocation=True))
        self.assertEqual(self.summary(), "1 place and 1 pattern, remote, will relocate")
        self.save(self.where(local=[], accept_remote=False))
        self.assertEqual(self.summary(), "1 place, no remote, will relocate")


if __name__ == "__main__":
    unittest.main()
