import argparse
import sys
import unittest
from pathlib import Path

TOOLS_DIR = str(Path(__file__).resolve().parents[1])
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from pyrite import cli


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("No subparsers action")


class CliHelpTests(unittest.TestCase):
    def test_visible_subcommands_have_description(self):
        parser = cli.build_parser()
        sub = _subparsers(parser)
        for name, sp in sub.choices.items():
            if name in cli.HIDDEN_COMMANDS:
                continue
            self.assertTrue(sp.description and sp.description.strip(), f"{name} missing description")

    def test_hand_run_commands_document_changes_needs_and_guide(self):
        parser = cli.build_parser()
        sub = _subparsers(parser)
        for name in ("run", "sweep", "doctor", "finish", "folder", "seed", "check"):
            desc = sub.choices[name].description or ""
            self.assertIn("Changes:", desc)
            self.assertIn("Needs:", desc)
            self.assertIn("Guide:", desc)


if __name__ == "__main__":
    unittest.main()
