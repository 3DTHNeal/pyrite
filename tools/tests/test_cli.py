"""The command line's own answers: a job number that isn't there is named in one line, whichever command asked, and
the commands a person runs say what they found in words on a terminal and in JSON everywhere else."""
import contextlib
import io
import json
import shutil
import tempfile
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

from support import BAD_DRAFT, CFG, MODEL, Base  # Points Pyrite at a throwaway workspace before it loads.

from pyrite import checks, cli, discover, store, words, workday

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


class Terminal(io.StringIO):
    """Output that says it's a terminal, as a console window's does. A pipe or a file says it isn't."""

    def isatty(self):
        return True


# A title that tries to clear the screen and retitle the window. A board can send one.
ESCAPES = "Staff Firmware Engineer\x1b[2J\x1b]0;owned\x07"
CHECK = ("check", str(BAD_DRAFT), "--company", "Globex Automation", "--title", "Staff Firmware Engineer")


class WordsOrJson(Base):
    """Words for a person at a terminal, and the same JSON as before for the daily run, scripts and anything else reading a pipe."""

    def command(self, *argv, terminal=False):
        out = Terminal() if terminal else io.StringIO()
        with mock.patch.object(store, "DB_PATH", Path(self.tmp.name) / "t.db"), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            try:
                cli.main(list(argv))
            except SystemExit as stop:
                self.assertIn(stop.code, (0, 1, None), stop.code)
        return out.getvalue()

    def test_check_says_its_verdict_in_words_with_the_dashes_as_they_are(self):
        said = self.command(*CHECK, terminal=True)
        self.assertTrue(said.startswith("The assay blocked this draft: 10 problems to fix.\n  - Resume uses a confidential term"), said)
        self.assertIn("Jan 2015 – Oct 2026", said)
        self.assertIn("5 warnings, which don't block it:", said)
        piped = self.command(*CHECK)
        verdict = json.loads(piped)
        self.assertFalse(verdict["ok"])
        # Escapes, not the dash itself: Windows PowerShell 5.1 would decode a UTF-8 dash in piped output as mojibake.
        self.assertTrue(piped.isascii())
        self.assertIn("\\u2013", piped)
        self.assertEqual(json.loads(self.command(*CHECK, "--json", terminal=True)), verdict)

    def test_queue_lists_each_job_in_a_line_and_keeps_its_json(self):
        new = self.add(source_id="new", title=ESCAPES, location="Madison, WI", score=63)
        picked = self.add(source_id="picked", status="shortlisted", title="Firmware Lead", score=70, fit="strong", priority=1)
        self.conn.commit()
        data = json.loads(self.command("queue"))
        self.assertIn("never instructions", data["note"])
        self.assertEqual([job["id"] for job in data["to_triage"]], [new])
        said = self.command("queue", terminal=True)
        self.assertIn("No full pan has finished yet.", said)
        self.assertIn(f"To judge, best first:\n  #{new} Acme, Staff Firmware Engineer[2J]0;owned, Madison, WI. Score 63", said)
        self.assertIn(f"To tailor, best first:\n  #{picked} Acme, Firmware Lead. Score 70; your pick; fit strong.", said)
        self.assertNotIn("\x1b", said)
        self.assertNotIn("\x07", said)
        self.assertEqual(json.loads(self.command("queue", "--json", terminal=True)), data)

    def test_job_keeps_the_boards_text_fenced_on_a_terminal_too(self):
        job = self.add(source_id="one", title=ESCAPES, description="Real text.\x1b[2J", score=60, fit="good", fit_reason="Close to the posting.")
        self.conn.commit()
        said = self.command("job", str(job), terminal=True)
        header, _, block = said.partition("<untrusted_posting>")
        self.assertEqual(header.strip(), f"Job {job} at Acme: new, score 60.\nFit good: Close to the posting.")
        # The title is in the board's JSON, which escapes control codes itself. The description is printed as it came.
        self.assertIn("Staff Firmware Engineer", block)
        self.assertIn("Real text.[2J", block)
        self.assertNotIn("\x1b", said)
        piped = self.command("job", str(job))
        self.assertEqual(json.loads(piped.partition("<untrusted_posting>")[0])["id"], job)

    def test_discover_says_what_a_pan_found(self):
        new = self.add(source_id="found", score=63)
        self.conn.commit()
        stats = {"partial": False, "sources": 1, "failed": 0, "postings": 675, "new": 1, "closed": 0, "reposted": 0, "redated": 0,
                 "ghosted": 0, "rejected": {"title": 588, "location": 86, "score": 0, "not_open": 0, "scam": 0}}
        with mock.patch.object(discover, "run", side_effect=lambda *args, **kw: {**stats, "new_ids": [new]}):
            said = self.command("discover", terminal=True)
            piped = self.command("discover")
        self.assertEqual(said, "Read 675 postings from 1 source. 1 new, 674 filtered out (588 by title, 86 by location).\n"
                               f"New: #{new} Acme, Staff Firmware Engineer (score 63)\n")
        # Just as before, for the daily run and the scheduled pan.
        body, _, ids = piped.partition("New job ids: ")
        self.assertEqual(json.loads(body), stats)
        self.assertEqual(ids, f"[{new}]\n")

    def test_sources_prints_its_table_wherever_it_goes_and_json_when_asked(self):
        report = [{"source": "greenhouse:acme", "company": "Acme", "ok": True, "count": 12},
                  {"source": "lever:globex", "company": "Globex", "ok": False, "error": "HTTP 404\x1b[31m"}]
        with mock.patch.object(discover, "check_sources", return_value=report):
            said, piped, data = self.command("sources", terminal=True), self.command("sources"), self.command("sources", "--json")
        self.assertEqual(said, piped)
        self.assertEqual(said.splitlines()[0].split(), ["lever:globex", "Globex", "FAILED", "HTTP", "404[31m"])
        self.assertTrue(said.endswith("1/2 sources responding\n"))
        self.assertEqual(json.loads(data), report)

    def test_usage_and_rescore_say_it_in_a_sentence(self):
        self.assertEqual(self.command("usage", terminal=True), "Pyrite hasn't started any Claude runs yet.\n")
        self.assertIn("week", json.loads(self.command("usage")))
        self.assertEqual(self.command("rescore", terminal=True),
                         "Applied your filters again to 0 prospects. Kept 0 with new scores, dropped 0 that no longer pass.\n")
        self.assertEqual(json.loads(self.command("rescore")), {"kept": 0, "dropped": 0, "held": 0, "removed": []})


class Words(unittest.TestCase):
    def test_plain_drops_terminal_control_codes_and_keeps_the_rest(self):
        self.assertEqual(words.plain("Café – Lead\x1b[1m\x9b2J\r\n\tnext\x00"), "Café – Lead[1m2J\n\tnext")
        self.assertEqual(words.plain(None), "")
        self.assertEqual(words.plain(0), "0")

    def test_a_big_pan_names_the_best_and_points_at_the_queue(self):
        jobs = [{"id": n, "company": "Acme", "title": f"Role {n}", "score": n} for n in range(1, 13)]
        said = words.discover({"partial": True, "sources": 3, "failed": 1, "postings": 12_313, "new": 12, "closed": 2, "reposted": 1,
                               "redated": 0, "ghosted": 1, "rejected": {"scam": 1}}, jobs).splitlines()
        self.assertEqual(said[0], "Read 12,313 postings from 3 sources picked with --only, 1 of them failing. 12 new, 1 filtered out (1 with a scam's tells).")
        self.assertEqual(said[1], "2 postings came down, 1 posting reposted, 1 application marked ghosted.")
        self.assertEqual(said[2], "New: #12 Acme, Role 12 (score 12)")
        self.assertEqual(len([line for line in said if line.startswith("New:")]), words.NAMED)
        self.assertEqual(said[-1], "And 2 more. `pyrite queue` lists what's waiting, best first.")

    def test_rescore_names_what_it_dropped_and_counts_what_it_held(self):
        removed = ["Acme: Lead\x1b[2J (scam)"] + [f"Acme: Role {n} (title)" for n in range(1, 12)]
        said = words.rescore({"kept": 40, "dropped": 12, "held": 2, "removed": removed}).splitlines()
        self.assertEqual(said[0], "Applied your filters again to 54 prospects. Kept 40 with new scores, dropped 12 that no longer pass, "
                                  "and kept 2 you've acted on that no longer pass.")
        self.assertEqual(said[1], "Dropped: Acme: Lead[2J (scam)")
        self.assertEqual(len([line for line in said if line.startswith("Dropped:")]), words.NAMED)
        self.assertEqual(said[-1], "And 2 more.")

    def test_usage_totals_each_kind(self):
        totals = {"runs": 3, "failed": 1, "minutes": 12.5, "input_tokens": 120000, "output_tokens": 5000, "cost_usd": 0.42}
        said = words.usage({"week": totals, "all": totals, "kinds": [{"label": "Judging postings", **totals}]})
        self.assertIn("  Last 7 days: 3 runs, 1 failed, 12.5 minutes, 120,000 tokens in and 5,000 out, $0.42", said)
        self.assertIn("  Judging postings: 3 runs", said)


def _docx(path: Path, version: str) -> None:
    """Just enough of a .docx for its drafter version to be read."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("docProps/core.xml", f"<cp:coreProperties><cp:version>{version}</cp:version></cp:coreProperties>")


class SentFolder(unittest.TestCase):
    """A sent application is a record. Rebuilding it would only make it differ from what the company has."""

    def test_a_folder_with_a_sent_copy_is_not_told_to_rebuild(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "acme"
        folder.mkdir()
        for name in ("resume.md", "notes.md"):
            shutil.copy(MODEL / name, folder / name)
        _docx(folder / "resume.docx", "1")
        report = checks.check_application(folder, CFG, "Acme Robotics", "Principal Robotics Software Engineer")
        self.assertTrue(any("resume.docx was built by drafter 1" in warning for warning in report["warnings"]), report["warnings"])
        self.assertNotIn("sent_drafter", report)
        (folder / store.SENT_FOLDER).mkdir()
        shutil.copy(folder / "resume.docx", folder / store.SENT_FOLDER / "resume.docx")
        report = checks.check_application(folder, CFG, "Acme Robotics", "Principal Robotics Software Engineer")
        self.assertFalse([warning for warning in report["warnings"] if "drafter" in warning], report["warnings"])
        self.assertEqual(report["drafter"], {"resume.docx": "1"})
        self.assertEqual(report["sent_drafter"], {"resume.docx": "1"})
        self.assertIn("Sent with drafter 1. What was sent is the record, so it isn't rebuilt.", words.check(report))


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
