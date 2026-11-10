"""Companies to watch, the Profile tab section: Check by hand changed an entry at a time, the board addresses a pasted
careers page may name, and how many pages each Workday search reads. Nothing here reaches the network."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import profile, steps, store

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"

# Three companies checked by hand, with comments above, between and after them.
MANUAL = """\
# Employers worth watching with no public feed.
[[manual_check]]
name = "LinkedIn"
url = "https://www.linkedin.com/jobs/"
why = "Its terms forbid automated collection"

# Initech posts only on its own site.
[[manual_check]]
name = "Initech"  # the parent company
url = "https://careers.initech.example/"
# Asked about this one in October.
why = "No board"

# Globex: check Mondays.
[[manual_check]]
name = "Globex"
url = "https://globex.example/jobs"

"""


class Section(unittest.TestCase):
    """A throwaway copy of the example profile, and the section's form as the page first sends it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = {**profile.view(), **steps.view()}

    def draft(self, edits: dict[str, Any]) -> dict[str, Any]:
        return steps.draft("companies", edits, self.view["versions"])

    def save(self, result: dict[str, Any]) -> None:
        profile.write(result["changes"], self.view["versions"], "test")
        self.view = {**profile.view(), **steps.view()}

    def config(self) -> str:
        return profile.read("config")

    def rewrite(self, text: str) -> None:
        (self.root / "profile" / "search.toml").write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}

    def form(self, **change) -> dict[str, Any]:
        companies = self.view["companies"]
        return {
            "boards": [{part: board[part] for part in ("was", "kind", "key", "name", "wd", "site")} for board in companies["boards"]],
            "manual": [dict(entry) for entry in companies["manual"]],
            "queries": list(companies["queries"]),
            "paste": "",
            **change,
        }


class CheckByHand(Section):
    """[[manual_check]] changed an entry at a time: the comments between entries stay."""

    def setUp(self):
        super().setUp()
        text = self.config().replace("\r\n", "\n")
        start = text.index("# Employers worth watching")
        end = text.index("# Company watchlist")
        self.before = text[:start] + MANUAL + text[end:]
        self.rewrite(self.before)

    def written(self, result: dict[str, Any]) -> str:
        return result["changes"]["config"]

    def test_an_unchanged_form_changes_nothing(self):
        result = self.draft(self.form())
        self.assertEqual((result["changes"], result["count"]), ({}, 0))

    def test_changing_one_entry_keeps_every_other_byte(self):
        manual = self.form()["manual"]
        manual[1]["why"] = "Its own site only"
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.written(result), self.before.replace('why = "No board"', 'why = "Its own site only"'))
        manual[1]["why"] = ""
        manual[2]["why"] = "Mondays"
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 2)
        self.assertEqual(self.written(result), self.before.replace('why = "No board"\n', "").replace(
            'url = "https://globex.example/jobs"\n', 'url = "https://globex.example/jobs"\nwhy = "Mondays"\n'))
        # A key the form doesn't show stays, and so does the comment beside a key it changes.
        manual = self.form()["manual"]
        manual[1]["name"] = "Initech Labs"
        result = self.draft(self.form(manual=manual))
        self.assertIn('name = "Initech Labs"  # the parent company\n', self.written(result))

    def test_one_taken_off_goes_with_its_own_lines(self):
        manual = self.form()["manual"]
        result = self.draft(self.form(manual=[manual[0], manual[2]]))
        self.assertEqual(result["count"], 1)
        middle = self.before.index("# Initech posts")
        self.assertEqual(self.written(result),
                         self.before[:middle] + self.before[self.before.index("# Globex: check Mondays."):])
        result = self.draft(self.form(manual=manual[:2]))
        self.assertEqual(self.written(result), self.before.replace(
            '# Globex: check Mondays.\n[[manual_check]]\nname = "Globex"\nurl = "https://globex.example/jobs"\n\n', ""))
        result = self.draft(self.form(manual=manual[1:]))
        self.assertEqual(self.written(result), self.before.replace(
            '[[manual_check]]\nname = "LinkedIn"\nurl = "https://www.linkedin.com/jobs/"\n'
            'why = "Its terms forbid automated collection"\n\n', "", 1))

    def test_a_new_one_goes_after_the_last(self):
        manual = [{"at": None, "name": "Hooli", "url": "hooli.example/careers", "why": ""}] + self.form()["manual"]
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 1)
        last = 'url = "https://globex.example/jobs"\n'
        self.assertEqual(self.written(result), self.before.replace(
            last, last + '\n[[manual_check]]\nname = "Hooli"\nurl = "https://hooli.example/careers"\n'))
        self.assertEqual([m["name"] for m in tomllib.loads(self.written(result))["manual_check"]],
                         ["LinkedIn", "Initech", "Globex", "Hooli"])

    def test_emptied_and_filled_again_the_list_stays_where_it_was(self):
        result = self.draft(self.form(manual=[]))
        self.assertEqual(result["count"], 3)
        self.assertNotIn("manual_check", tomllib.loads(self.written(result)))
        self.assertIn("# Employers worth watching with no public feed.\n# [[manual_check]]\n", self.written(result))
        self.save(result)
        result = self.draft(self.form(manual=[{"at": None, "name": "Hooli", "url": "", "why": ""}]))
        self.assertIn('# Employers worth watching with no public feed.\n[[manual_check]]\nname = "Hooli"\n\n'
                      "# Company watchlist", self.written(result))
        self.assertNotIn("# [[manual_check]]", self.written(result))

    def test_every_one_replaced_keeps_the_list_where_it_was(self):
        result = self.draft(self.form(manual=[{"at": None, "name": "Hooli", "url": "", "why": ""}]))
        self.assertEqual(result["count"], 4)
        self.assertIn('# Employers worth watching with no public feed.\n[[manual_check]]\nname = "Hooli"\n\n'
                      "# Company watchlist", self.written(result))

    def test_windows_line_endings_stay(self):
        self.rewrite(self.before.replace("\n", "\r\n"))
        manual = self.form()["manual"]
        manual[0]["why"] = "Terms"
        manual.append({"at": None, "name": "Hooli", "url": "", "why": ""})
        result = self.draft(self.form(manual=manual))
        self.assertNotIn("\n", self.written(result).replace("\r\n", ""))
        self.assertEqual(self.written(result).replace("\r\n", "\n"), self.before.replace(
            'why = "Its terms forbid automated collection"', 'why = "Terms"').replace(
            'url = "https://globex.example/jobs"\n', 'url = "https://globex.example/jobs"\n\n[[manual_check]]\nname = "Hooli"\n'))

    def test_a_table_inside_an_entry_is_refused_rather_than_lost(self):
        self.rewrite(self.before.replace("# Globex: check Mondays.\n", "[manual_check.extra]\nnote = 1\n\n# Globex: check Mondays.\n"))
        manual = self.form()["manual"]
        manual[0]["why"] = "Terms"
        with self.assertRaisesRegex(ValueError, "a table inside"):
            self.draft(self.form(manual=manual))


if __name__ == "__main__":
    unittest.main()
