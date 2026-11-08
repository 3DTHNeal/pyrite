"""The command line's own answers: a job number that isn't there is named in one line, whichever command asked."""
import contextlib
import io
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import cli, store, workday

MESSAGE = "No job 999. The dashboard lists every job; `pyrite queue` shows the ones waiting on a run."

# Every command that takes a job number, with whatever else it needs to reach the lookup.
COMMANDS = (
    ["job", "999"],
    ["triage", "999", "--fit", "good", "--reason", "Close to the posting"],
    ["folder", "999"],
    ["finish", "999"],
    ["refresh", "999"],
    ["prep", "999"],
    ["autofill", "999"],
    ["sent", "999"],
    ["status", "999", "applied"],
    ["outreach", "999"],
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
        # autofill stops before the lookup unless Workday autofill is on; the lookup is what's under test.
        patcher = mock.patch.object(workday, "enabled", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_command_names_the_job_it_couldnt_find(self):
        for argv in COMMANDS:
            with self.subTest(command=argv[0]), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
                cli.main(argv)
            self.assertEqual(caught.exception.code, MESSAGE)

    def test_a_lookup_with_no_number_typed_keeps_its_traceback(self):
        with mock.patch.object(cli, "cmd_where", side_effect=store.JobNotFound(999)):
            with self.assertRaises(store.JobNotFound):
                cli.main(["where"])


class Outreach(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.object(store, "DB_PATH", Path(tmp.name) / "pyrite.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_logs_reaching_out_and_says_when_to_follow_up(self):
        with contextlib.closing(store.connect()) as conn:
            ts = store.now()
            job = conn.execute("INSERT INTO jobs (source_key, source_id, company, title, first_seen, last_seen) VALUES ('manual', '1', 'Acme', 'Lead', ?, ?)",
                               (ts, ts)).lastrowid
            store.set_status(conn, job, "applied")
            conn.commit()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["outreach", str(job), "--to", "the recruiter", "--note", "Asked for a referral"])
        self.assertIn("reached out. Follow up on", out.getvalue())
        with contextlib.closing(store.connect()) as conn:
            detail = conn.execute("SELECT detail FROM events WHERE kind = ?", (store.REACHED_OUT,)).fetchone()[0]
        self.assertTrue(detail.endswith(", to the recruiter. Asked for a referral"), detail)

    def test_a_job_not_yet_sent_is_refused_in_one_line(self):
        with contextlib.closing(store.connect()) as conn:
            ts = store.now()
            job = conn.execute("INSERT INTO jobs (source_key, source_id, company, title, first_seen, last_seen) VALUES ('manual', '1', 'Acme', 'Lead', ?, ?)",
                               (ts, ts)).lastrowid
            conn.commit()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            cli.main(["outreach", str(job)])
        self.assertIn("application you've sent", str(caught.exception.code))
