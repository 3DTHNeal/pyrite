"""What every test module shares: a throwaway copy of the example workspace, set up before Pyrite loads, and the
base classes and helpers the tests build on.

Import this before anything from pyrite. It points PYRITE_HOME at the copy, so no test can read or change anyone's real
job search, whatever workspace this machine normally uses.
"""
import atexit
import gc
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
import warnings
from datetime import datetime, timedelta
from pathlib import Path

# A file, socket or database left open fails the run. Python reports one only as a warning, often from the garbage
# collector after the test that leaked it has passed, so they're gathered here and judged once every test has run.
_leaks: list[str] = []
_show_warning = warnings.showwarning


def _note_leak(message, category, filename, lineno, file=None, line=None):
    if issubclass(category, ResourceWarning):
        _leaks.append(str(message))
    _show_warning(message, category, filename, lineno, file, line)


def _fail_on_leaks():
    # A database connection sits in a reference cycle, so it's reported only when the collector runs. By now the test
    # runner has put back Python's default filters, which hide ResourceWarning, so they're turned on again for this.
    with warnings.catch_warnings():
        warnings.simplefilter("always", ResourceWarning)
        gc.collect()
    if _leaks:
        sys.stdout.flush()
        print(f"\nFAILED: resources left open: {len(_leaks)}. The warnings above say which; "
              "run with -X tracemalloc=20 to see where each was opened.", file=sys.stderr, flush=True)
        os._exit(1)


warnings.showwarning = _note_leak
atexit.register(_fail_on_leaks)  # Registered before the workspace's cleanup below, so it runs after it.

CODE_ROOT = Path(__file__).resolve().parents[2]
_workspace = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
atexit.register(_workspace.cleanup)
WORKSPACE = Path(_workspace.name) / "workspace"
shutil.copytree(CODE_ROOT / "example", WORKSPACE, ignore=shutil.ignore_patterns("data"))
os.environ["PYRITE_HOME"] = str(WORKSPACE)  # Before anything loads: this decides where every path below points.

sys.path.insert(0, str(CODE_ROOT / "tools"))

from pyrite import checks, claude_code, cli, daily, doctor, prep, refresh, server, sources, store, tasks  # noqa: E402

# This suite's workspace is an unedited copy of the example, which a real workspace mustn't be: the dashboard would put
# "Finish setup" items at the top of every to-do list, and the Claude runs would refuse to start. Here the copy stands in
# for a finished workspace, so those two are switched off for the suite. The tests of them call the originals kept here.
# Plain assignments rather than started patches, since a test that calls mock.patch.stopall() would undo those.
WORKSPACE_TODOS, FACTS_STILL_EXAMPLE = doctor.workspace_todos, tasks._facts_still_example
doctor.workspace_todos = lambda root, cfg: []
tasks._facts_still_example = lambda: False

CFG = store.load_config()
MODEL = store.ROOT / "applications" / "2026-11-acme-principal-robotics-software-engineer"
BAD_DRAFT = store.ROOT / "applications" / "2026-11-globex-staff-firmware-engineer"
RESUME = (MODEL / "resume.md").read_text(encoding="utf-8")
LETTER = (MODEL / "cover-letter.md").read_text(encoding="utf-8")
SOURCES = checks._read_sources(CFG)
LETTER_ROLE = ("Acme Robotics", "Principal Robotics Software Engineer")


def resume_errors(text):
    errors, _ = checks.check_text(text, "resume", CFG, SOURCES, "Acme", "Principal Engineer")
    return errors


class Base(unittest.TestCase):
    def setUp(self):
        # Windows won't delete a database the command line left open, so a leftover temp file is fine here.
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.conn = store.connect(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add(self, **kw):
        ts = store.now()
        fields = {"source_key": "greenhouse:acme", "source_id": "1", "company": "Acme", "title": "Staff Firmware Engineer",
                  "first_seen": ts, "last_seen": ts, "status": "new", "status_changed_at": ts, **kw}
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        return self.conn.execute(f"INSERT INTO jobs ({cols}) VALUES ({marks})", tuple(fields.values())).lastrowid


class Clock:
    """Moves store.now() forward on demand. Timestamps are to the second, and a sweep tells its own sightings from the
    last one's by comparing them, so a test that runs two sweeps needs a later second without waiting a real one."""

    def __init__(self, test: unittest.TestCase):
        self.offset = timedelta(0)
        clock = self

        class Shifted(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + clock.offset

        patcher = mock.patch.object(store, "datetime", Shifted)
        patcher.start()
        test.addCleanup(patcher.stop)

    def advance(self, seconds: float = 1) -> None:
        self.offset += timedelta(seconds=seconds)


def stub_feed(monkeypatch_target, postings=None, error=None):
    def fetch(board, company):
        if error:
            raise error
        return postings
    sources.FEEDS["greenhouse"] = fetch


CONFIDENTIAL = CFG["guard"]["forbidden"][0]


class ClaudeRun(Base):
    """A job with an application folder, and a stand-in for Claude Code. Holds no tests of its own."""
    writes = "resume.md"

    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name)
        self.rel = "applications/acme"
        self.folder = self.root / self.rel
        self.folder.mkdir(parents=True)
        self.draft = (store.ROOT / CFG["guard"]["heading_source"]).read_text(encoding="utf-8")
        (self.folder / "resume.md").write_text(self.draft, encoding="utf-8")
        (self.folder / "notes.md").write_text("old notes", encoding="utf-8")
        # The fictional profile and its model documents, which the prompts carry.
        shutil.copytree(WORKSPACE / "profile", self.root / "profile")
        shutil.copytree(MODEL, self.root / "applications" / MODEL.name)
        self.job = self.add(status="ready", app_folder=self.rel, description="A posting.")
        self.conn.commit()
        for target, name in ((refresh, "ROOT"), (prep, "ROOT"), (cli, "ROOT"), (server, "ROOT"), (store, "ROOT"), (daily, "ROOT")):
            patcher = mock.patch.object(target, name, self.root)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cli, "_build", return_value="")  # The real one prints the files it made, which a test run needn't.
        self.build = patcher.start()
        self.addCleanup(patcher.stop)

    def claude(self, *drafts, summary="Led with the QA work."):
        """A stand-in for Claude Code that writes each draft in turn and records the prompts it was given."""
        drafts = iter(drafts)
        self.prompts = []

        def fake(cmd, input=None, **kw):
            self.prompts.append(input)
            draft = next(drafts)
            if isinstance(draft, subprocess.CompletedProcess):
                return draft
            if draft is not None:
                (self.folder / self.writes).write_text(draft, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout=summary, stderr="")
        patcher = mock.patch.object(claude_code.subprocess, "run", side_effect=fake)
        patcher.start()
        self.addCleanup(patcher.stop)


BRIEF = "# Interview prep: Acme, Staff Firmware Engineer\n\n## The role in two sentences\n\nThey need someone to own firmware quality.\n"
