"""Tests for folding the notes in changelog.d/ into CHANGELOG.md."""
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import changelog

LOG = """# Changelog

Intro.

## [Unreleased]

### Added

- Old addition.

### Fixed

- Old fix.

## [0.1.0] - 2026-11-09

### Added

- Released addition.
"""


class Parse(unittest.TestCase):
    def test_entries_under_each_heading_with_carried_on_lines(self):
        note = "### Added\n\n- One.\n- Two,\n  carried on.\n\n### Fixed\n\n- A fix.\n"
        self.assertEqual(changelog.parse(note, "n.md"), {"Added": ["- One.", "- Two,", "  carried on."], "Fixed": ["- A fix."]})

    def test_refuses_what_wouldnt_fold(self):
        for note, says in (("- No heading.\n", "goes under a heading"),
                           ("### Improved\n\n- Hm.\n", "one of Added"),
                           ("## Added\n\n- Wrong level.\n", "one of Added"),
                           ("### Added\n\nNot a bullet.\n", 'starts with "- "'),
                           ("### Added\n\n  Carried on from nothing.\n", 'starts with "- "'),
                           ("### Added\n\n### Fixed\n\n- A fix.\n", '"### Added" has no entries'),
                           ("\n", "has no entries")):
            with self.subTest(note=note), self.assertRaisesRegex(ValueError, says):
                changelog.parse(note, "n.md")


class Fold(unittest.TestCase):
    def test_nothing_to_fold_leaves_the_file_as_it_is(self):
        self.assertEqual(changelog.fold(LOG, []), LOG)

    def test_the_real_changelog_survives_a_fold_of_nothing(self):
        text = changelog.CHANGELOG.read_text(encoding="utf-8")
        self.assertEqual(changelog.fold(text, []), text)

    def test_entries_go_on_top_of_their_heading_first_note_first(self):
        folded = changelog.fold(LOG, [{"Added": ["- First note."]}, {"Added": ["- Second note."], "Fixed": ["- New fix."]}])
        self.assertIn("### Added\n\n- First note.\n- Second note.\n- Old addition.\n\n### Fixed\n\n- New fix.\n- Old fix.\n\n## [0.1.0]", folded)
        self.assertTrue(folded.endswith("### Added\n\n- Released addition.\n"))

    def test_a_missing_heading_goes_where_keep_a_changelogs_order_puts_it(self):
        folded = changelog.fold(LOG, [{"Changed": ["- A change."], "Security": ["- A patch."]}])
        self.assertIn("- Old addition.\n\n### Changed\n\n- A change.\n\n### Fixed\n\n- Old fix.\n\n### Security\n\n- A patch.\n\n## [0.1.0]", folded)

    def test_an_empty_unreleased_and_one_at_the_end_of_the_file(self):
        self.assertIn("## [Unreleased]\n\n### Fixed\n\n- New fix.\n\n## [0.1.0]",
                      changelog.fold("# Changelog\n\n## [Unreleased]\n\n## [0.1.0]\n\n- Old.\n", [{"Fixed": ["- New fix."]}]))
        self.assertEqual(changelog.fold("# Changelog\n\n## [Unreleased]\n", [{"Added": ["- New."]}]),
                         "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- New.\n")

    def test_no_unreleased_heading_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no"):
            changelog.fold("# Changelog\n\n## [0.1.0]\n", [{"Added": ["- New."]}])


class Command(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        (self.root / "changelog.d").mkdir()
        (self.root / "changelog.d" / "README.md").write_text("How notes work.\n", encoding="utf-8")
        (self.root / "CHANGELOG.md").write_text(LOG, encoding="utf-8")
        for name, value in (("NOTES", self.root / "changelog.d"), ("CHANGELOG", self.root / "CHANGELOG.md")):
            patcher = mock.patch.object(changelog, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def note(self, name, text):
        (self.root / "changelog.d" / name).write_text(text, encoding="utf-8")

    def test_check_changes_nothing(self):
        self.note("a.md", "### Fixed\n\n- New fix.\n")
        with mock.patch("sys.stdout"):
            self.assertEqual(changelog.main(["--check"]), 0)
        self.assertEqual((self.root / "CHANGELOG.md").read_text(encoding="utf-8"), LOG)
        self.assertTrue((self.root / "changelog.d" / "a.md").exists())

    def test_fold_writes_the_entries_and_deletes_the_notes_but_not_the_readme(self):
        self.note("b.md", "### Fixed\n\n- Second.\n")
        self.note("a.md", "### Fixed\n\n- First.\n")
        with mock.patch("sys.stdout"):
            self.assertEqual(changelog.main([]), 0)
        self.assertIn("### Fixed\n\n- First.\n- Second.\n- Old fix.\n", (self.root / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertEqual([p.name for p in (self.root / "changelog.d").iterdir()], ["README.md"])

    def test_a_bad_note_stops_everything_and_names_the_file(self):
        self.note("a.md", "### Fixed\n\n- Fine.\n")
        self.note("b.md", "### Nope\n\n- Bad.\n")
        with mock.patch("sys.stderr") as err:
            self.assertEqual(changelog.main([]), 1)
        self.assertIn("changelog.d/b.md:1", "".join(c.args[0] for c in err.write.call_args_list))
        self.assertEqual((self.root / "CHANGELOG.md").read_text(encoding="utf-8"), LOG)
        self.assertTrue((self.root / "changelog.d" / "a.md").exists())


if __name__ == "__main__":
    unittest.main()
