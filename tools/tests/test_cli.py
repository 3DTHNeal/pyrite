"""The command line's own answers: a job number that isn't there is named in one line, whichever command asked."""
import contextlib
import io
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import cli, store

MESSAGE = "No job 999. `pyrite queue` lists the open ones."

# Every command that takes a job number, with whatever else it needs to reach the lookup.
COMMANDS = (
    ["job", "999"],
    ["triage", "999", "--fit", "good", "--reason", "Close to the posting"],
    ["folder", "999"],
    ["finish", "999"],
    ["prep", "999"],
    ["sent", "999"],
    ["status", "999", "applied"],
    ["fill", "999"],
)


class MissingJob(unittest.TestCase):
    """A number no command can find, which used to end in a traceback: KeyError: 'no job 999'."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(store, "DB_PATH", Path(tmp.name) / "pyrite.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_command_names_the_job_it_couldnt_find(self):
        for argv in COMMANDS:
            with self.subTest(command=argv[0]), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main(argv)
            self.assertEqual(caught.exception.code, MESSAGE)
