"""Finding, creating and guarding the workspace, and importing earlier applications."""
import contextlib
import io
import os
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path

from support import CFG, CODE_ROOT, FACTS_STILL_EXAMPLE, WORKSPACE, WORKSPACE_TODOS, Base

import pyrite
from pyrite import cli, doctor, score, server, store, tasks

SEED = ('[[application]]\ncompany = "Acme Robotics"\ntitle = "Principal Engineer"\napplied_on = "2026-11-02"\n\n'
        '[[application]]\ncompany = "Hooli"\ntitle = "Director"\nnote = "Not sure it went out."\n')


class Seed(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root, self.path = Path(tmp.name), Path(tmp.name) / "seed.db"
        (self.root / "profile").mkdir()
        (self.root / "profile" / "seed.toml").write_text(SEED, encoding="utf-8")
        for target, name, value in ((store, "DB_PATH", self.path), (cli, "ROOT", self.root)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def statuses(self):
        conn = store.connect(self.path)
        try:
            return {row["company"]: row["status"] for row in conn.execute("SELECT company, status FROM jobs")}
        finally:
            conn.close()

    def test_running_again_adds_nothing_even_after_a_sweep_linked_a_job(self):
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["seed"])
            conn = store.connect(self.path)
            count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            conn.execute("UPDATE jobs SET source_key = 'greenhouse:acme', source_id = '1' WHERE company = 'Acme Robotics'")
            conn.commit()
            cli.main(["seed"])
            self.assertGreater(count, 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], count)
            conn.close()

    def test_nothing_imported_is_ready_since_the_assay_never_saw_it(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["seed"])
        self.assertEqual(self.statuses(), {"Acme Robotics": "applied", "Hooli": "shortlisted"})
        self.assertIn("Added 2 existing applications.", out.getvalue())

    def test_the_examples_seed_is_refused_so_its_applications_never_reach_yours(self):
        shutil.copy(store.EXAMPLE_ROOT / "profile" / "seed.toml", self.root / "profile" / "seed.toml")
        with self.assertRaises(SystemExit) as caught:
            cli.main(["seed"])
        self.assertIn("fictional example's", str(caught.exception.code))
        self.assertEqual(self.statuses(), {})

    def test_a_folder_that_isnt_there_is_skipped_and_named_not_a_crash(self):
        (self.root / "profile" / "seed.toml").write_text(
            '[[application]]\ncompany = "Initech"\ntitle = "Engineer"\nfolder = "applications/gone"\n\n'
            '[[application]]\ncompany = "Hooli"\ntitle = "Director"\n', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
            cli.main(["seed"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("Added 1 existing application.", out.getvalue())
        self.assertIn("Skipped Initech: Engineer, since its folder applications/gone isn't in your workspace", out.getvalue())
        self.assertEqual(list(self.statuses()), ["Hooli"])


class Workspace(unittest.TestCase):
    def find(self, env=None, pointer=None):
        with mock.patch.dict(os.environ, {"PYRITE_HOME": env or ""}), mock.patch.object(store, "HOME_POINTER", pointer or Path("no-such-file")):
            return store.find_workspace()

    def test_defaults_to_the_fictional_example(self):
        self.assertEqual(self.find(), store.EXAMPLE_ROOT)

    def test_environment_wins_over_the_pointer_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            first, second = Path(folder) / "first", Path(folder) / "second"
            first.mkdir()
            second.mkdir()
            pointer = Path(folder) / "pointer"
            pointer.write_text(f"{second}\n", encoding="utf-8")
            self.assertEqual(self.find(pointer=pointer), second.resolve())
            self.assertEqual(self.find(env=str(first), pointer=pointer), first.resolve())

    def test_missing_workspace_stops_instead_of_starting_empty(self):
        with self.assertRaises(SystemExit):
            self.find(env=str(WORKSPACE / "does-not-exist"))

    def test_paths_follow_the_workspace_and_code_stays_put(self):
        self.assertEqual(store.ROOT, WORKSPACE.resolve())
        self.assertEqual(store.DB_PATH, WORKSPACE.resolve() / "data" / "pyrite.db")
        self.assertTrue((store.CODE_ROOT / "tools" / "pyrite.py").exists())

    def test_a_pointer_saved_by_powershell_or_with_a_byte_order_mark_is_read(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = Path(folder) / "workspace"
            target.mkdir()
            pointer = Path(folder) / "pointer"
            for encoding in ("utf-8", "utf-8-sig", "utf-16"):
                with self.subTest(encoding):
                    pointer.write_text(f"{target}\r\n", encoding=encoding)
                    self.assertEqual(self.find(pointer=pointer), target.resolve())

    def test_a_git_bash_path_is_read_as_the_windows_path_it_names(self):
        with mock.patch.object(store.os, "name", "nt"):
            self.assertEqual(store._windows_path("/c/Users/you/jobs"), "C:/Users/you/jobs")
            self.assertEqual(store._windows_path("/d"), "D:/")
            self.assertEqual(store._windows_path(r"C:\Users\you"), r"C:\Users\you")
            self.assertEqual(store._windows_path("/home/you"), "/home/you")
        with mock.patch.object(store.os, "name", "posix"):
            self.assertEqual(store._windows_path("/c/Users/you"), "/c/Users/you")

    @unittest.skipUnless(os.name == "nt", "Git Bash paths only come up on Windows")
    def test_a_pointer_written_from_git_bash_finds_the_workspace(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = Path(folder) / "workspace"
            target.mkdir()
            target = target.resolve()
            pointer = Path(folder) / "pointer"
            pointer.write_text(f"/{target.drive[0].lower()}{target.as_posix()[2:]}\n", encoding="utf-8")
            self.assertEqual(self.find(pointer=pointer), target)

    def test_a_missing_workspace_says_where_its_path_came_from(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            pointer = Path(folder) / "pointer"
            pointer.write_text(str(Path(folder) / "nowhere"), encoding="utf-8")
            with self.assertRaises(SystemExit) as caught:
                self.find(pointer=pointer)
            self.assertIn(str(pointer), str(caught.exception.code))

    def test_a_workspace_with_no_search_toml_says_how_to_start(self):
        with mock.patch.object(store, "CONFIG_PATH", WORKSPACE / "profile" / "no-such.toml"), self.assertRaises(SystemExit) as caught:
            store.load_config()
        self.assertIn("example/profile/", str(caught.exception.code))


class NewWorkspace(unittest.TestCase):
    """A workspace made the way docs/operating.md says, by copying example/profile/, and what's left to change in it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name) / "mine"
        shutil.copytree(store.EXAMPLE_ROOT / "profile", self.root / "profile")

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self):
        import tomllib

        with (self.root / "profile" / "search.toml").open("rb") as handle:
            return tomllib.load(handle)

    def edit_config(self, old, new):
        path = self.root / "profile" / "search.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def todos(self, cfg=None):
        return [todo["what"] for todo in WORKSPACE_TODOS(self.root, cfg or self.cfg())]

    def own_settings(self):
        """The config with every setting that describes the fictional candidate made someone else's."""
        cfg = self.cfg()
        for section, key, _ in doctor.EXAMPLE_SETTINGS:
            cfg.setdefault(section, {})[key] = {"Mine": ["mine.example"]} if key == "domains" else ["Mine"]
        return cfg

    def test_a_copied_profile_has_every_source_its_guard_names(self):
        guard = self.cfg()["guard"]
        for rel in [guard["heading_source"], *guard["approved_sources"]]:
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertFalse([what for what in self.todos() if "isn't in your workspace" in what])

    def test_whatever_is_still_the_examples_is_listed(self):
        self.assertEqual(doctor.still_example(self.root), list(doctor.OWN_FILES))
        todos = "\n".join(self.todos())
        for expected in (*doctor.OWN_FILES, "[candidate] name", "allowed_hosts", "profile/seed.toml",
                         *(label for _, _, label in doctor.EXAMPLE_SETTINGS)):
            self.assertIn(expected, todos)

    def test_the_examples_settings_are_named_together_and_only_while_unchanged(self):
        cfg = self.own_settings()
        self.assertFalse([what for what in self.todos(cfg) if "still has the example's" in what])
        cfg["guard"]["expected_on_resume"] = self.cfg()["guard"]["expected_on_resume"]
        left = [what for what in self.todos(cfg) if "still has the example's" in what]
        self.assertEqual(left, ["profile/search.toml still has the example's expected_on_resume under [guard]."])
        cfg["guard"]["expected_on_resume"] = []  # Emptied counts as yours.
        self.assertFalse([what for what in self.todos(cfg) if "still has the example's" in what])

    def test_a_workspace_made_its_own_has_nothing_left(self):
        for rel in doctor.OWN_FILES:
            path = self.root / rel
            path.write_text(path.read_text(encoding="utf-8") + "\nMine now.\n", encoding="utf-8")
        self.edit_config('name = "Alex Rivera"', 'name = "Sam Doe"')
        self.edit_config("allowed_hosts = ['workstation', 'workstation.example-tailnet.ts.net']", "allowed_hosts = []")
        (self.root / "profile" / "seed.toml").unlink()
        self.assertEqual(self.todos(self.own_settings()), [])

    def test_a_guard_source_that_isnt_there_is_named(self):
        self.edit_config("heading_source = 'profile/resume.md'", "heading_source = 'profile/master.md'")
        self.assertTrue(any("heading_source" in what and "profile/master.md" in what for what in self.todos()))

    def test_a_seed_folder_that_isnt_there_is_named(self):
        (self.root / "profile" / "seed.toml").write_text(
            '[[application]]\ncompany = "Initech"\ntitle = "Engineer"\nfolder = "applications/gone"\n', encoding="utf-8")
        self.assertTrue(any("applications/gone" in what for what in self.todos()))

    def test_no_workspace_and_no_search_toml_each_say_how_to_start(self):
        self.assertIn("No workspace", WORKSPACE_TODOS(store.EXAMPLE_ROOT, CFG)[0]["what"])
        self.assertIn("search.toml", WORKSPACE_TODOS(self.root, None)[0]["what"])

    def test_doctor_says_ready_only_when_nothing_is_left(self):
        programs = [{"ok": True, "what": "everything", "fix": ""}]
        with mock.patch.object(doctor, "tool_checks", return_value=programs), contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["doctor"])
        self.assertIn("Ready.", out.getvalue())
        left = [{"what": "profile/facts.md is still the fictional example's.", "fix": "Replace it."}]
        with mock.patch.object(doctor, "tool_checks", return_value=programs), mock.patch.object(doctor, "workspace_todos", return_value=left), \
                contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
            cli.main(["doctor"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("profile/facts.md", out.getvalue())


class SetupGuard(Base):
    def test_the_claude_runs_refuse_while_the_facts_are_the_examples(self):
        # The suite's workspace is a copy of the example, so the original check finds it unedited.
        self.assertTrue(FACTS_STILL_EXAMPLE())
        with mock.patch.object(tasks, "_facts_still_example", FACTS_STILL_EXAMPLE):
            for kind in tasks.WRITERS:
                self.assertIn("profile/facts.md", tasks.refusal(self.conn, kind))
            self.assertIsNone(tasks.refusal(self.conn, tasks.SWEEP))  # Reading the boards costs nothing, so it isn't held back.

    def test_the_dashboard_lists_setup_first_and_the_demo_never_does(self):
        left = [{"what": "profile/facts.md is still the fictional example's.", "fix": "Replace it."}]
        with mock.patch.object(doctor, "workspace_todos", return_value=left):
            orders = server.build_state(self.conn, CFG)["orders"]
            self.assertEqual((orders[0]["kind"], orders[0]["job_id"], orders[0]["text"]), ("Finish setup", None, left[0]["what"]))
            with mock.patch.object(server, "IS_EXAMPLE", True):
                self.assertEqual(server._setup_orders(CFG), [])


class CommandLine(unittest.TestCase):
    def test_help_lists_no_hidden_worker(self):
        text = cli.build_parser().format_help()
        self.assertNotIn("SUPPRESS", text)
        self.assertNotRegex(text, r"(?m)^\s+task\b")
        self.assertEqual(cli.build_parser().parse_args(["task", "3"]).id, 3)  # The dashboard's worker still runs.

    def test_version_is_the_same_everywhere(self):
        project = tomllib.loads((CODE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(project["version"], pyrite.__version__)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["--version"])
        self.assertEqual(out.getvalue().strip(), f"pyrite {pyrite.__version__}")


class Init(unittest.TestCase):
    """`pyrite init`, which makes a workspace the way the docs say to by hand, minus what would mislead."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.folder, self.pointer = self.base / "my-job-search", self.base / "pointer"
        for patcher in (mock.patch.object(store, "HOME_POINTER", self.pointer), mock.patch.dict(os.environ, {"PYRITE_HOME": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def init(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["init", str(self.folder), *extra])
        return out.getvalue()

    def cfg(self):
        with (self.folder / "profile" / "search.toml").open("rb") as handle:
            return tomllib.load(handle)

    def test_the_lines_it_changes_are_in_the_example(self):
        text = (store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8")
        self.assertIn(cli.INIT_EXAMPLE_NAME, text)
        self.assertIn(cli.INIT_EXAMPLE_HOSTS, text)

    def test_makes_a_workspace_without_the_examples_applications_or_hosts_and_points_at_it(self):
        out = self.init("--name", 'Sam "Q" Doe')
        self.assertFalse((self.folder / "profile" / "seed.toml").exists())
        self.assertTrue((self.folder / "profile" / "facts.md").is_file())
        self.assertTrue((self.folder / "applications").is_dir())
        cfg = self.cfg()
        self.assertEqual(cfg["candidate"]["name"], 'Sam "Q" Doe')
        self.assertEqual(cfg["dashboard"]["allowed_hosts"], [])
        self.assertEqual(self.pointer.read_text(encoding="utf-8").strip(), str(self.folder.resolve()))
        self.assertIn("pyrite doctor", out)
        todos = "\n".join(todo["what"] for todo in WORKSPACE_TODOS(self.folder, cfg))
        for gone in ("[candidate] name", "allowed_hosts", "seed.toml"):
            self.assertNotIn(gone, todos)
        self.assertIn("profile/facts.md is still the fictional example's", todos)  # Making it yours is the next step.

    def test_without_a_name_the_example_name_stays_for_doctor_to_flag(self):
        self.init()
        self.assertEqual(self.cfg()["candidate"]["name"], "Alex Rivera")

    def test_an_existing_profile_is_left_alone(self):
        (self.folder / "profile").mkdir(parents=True)
        (self.folder / "profile" / "facts.md").write_text("Mine.", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("nothing was changed", str(caught.exception.code))
        self.assertEqual((self.folder / "profile" / "facts.md").read_text(encoding="utf-8"), "Mine.")
        self.assertFalse(self.pointer.exists())

    def test_a_folder_inside_the_repository_is_refused(self):
        self.folder = CODE_ROOT / "my-job-search"
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("inside this repository", str(caught.exception.code))
        self.assertFalse(self.folder.exists())

    def test_a_workspace_already_named_is_never_replaced(self):
        self.pointer.write_text("/somewhere/else\n", encoding="utf-8")
        out = self.init()
        self.assertEqual(self.pointer.read_text(encoding="utf-8"), "/somewhere/else\n")
        self.assertIn("left alone", out)
        with mock.patch.dict(os.environ, {"PYRITE_HOME": "/elsewhere"}):
            self.pointer.unlink()
            self.folder = self.base / "second"
            self.assertIn("PYRITE_HOME", self.init())
        self.assertFalse(self.pointer.exists())


class Serve(unittest.TestCase):
    def test_a_port_in_use_stops_a_second_dashboard_with_a_message(self):
        first = server.make_server(0)
        try:
            port = first.server_address[1]
            with self.assertRaises(SystemExit) as caught:
                server.make_server(port)
            self.assertIn(f"Port {port} is already in use", str(caught.exception.code))
        finally:
            first.server_close()


class CommandOutput(Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(store, "DB_PATH", Path(self.tmp.name) / "t.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_says_which_job_and_what_next(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["add", "--company", "Initech", "--title", "Firmware Lead"])
        self.assertRegex(out.getvalue(), r"^Job (\d+): Initech, Firmware Lead\. `pyrite folder \1` makes its application folder\.")

    def test_add_with_a_posting_file_that_isnt_there_adds_nothing_and_says_why(self):
        missing = Path(self.tmp.name) / "no-posting.md"
        with self.assertRaises(SystemExit) as caught:
            cli.main(["add", "--company", "Initech", "--title", "Firmware Lead", "--description-file", str(missing)])
        self.assertIn("Nothing was added", str(caught.exception.code))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_where_keeps_stdout_to_the_path_and_notes_the_example(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cli.cmd_where(None)
        self.assertEqual(out.getvalue().strip(), str(store.ROOT))
        self.assertIn("pyrite init", err.getvalue())

    def test_a_resume_that_reads_as_copied_is_said_in_words(self):
        overlap = {"pct": 90, "covered": ["a", "b", "c", "d", "e", "f", "g", "h", "i"], "missing": ["j"]}
        with contextlib.redirect_stderr(io.StringIO()) as err:
            cli._overlap_note({"overlap": overlap})
            cli._overlap_note({"overlap": {**overlap, "pct": 70}})
        self.assertEqual(err.getvalue().count("reads as copied"), 1)

    def test_help_says_where_to_start(self):
        text = cli.build_parser().format_help()
        for command in ("pyrite demo", "pyrite init", "pyrite doctor"):
            self.assertIn(command, text)
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
            cli.build_parser().parse_args(["finish", "--help"])
        self.assertIn("a job's number", out.getvalue())


class Generalized(unittest.TestCase):
    def test_file_names_come_from_the_candidate(self):
        self.assertEqual(cli._file_prefix({"candidate": {"name": "Alex Q. Rivera-Smith"}}), "Alex_Q_Rivera_Smith")
        self.assertEqual(cli._file_prefix({"candidate": {"name": "José Núñez"}}), "José_Núñez")
        self.assertEqual(cli._file_prefix({"candidate": {"name": "李雷"}}), "李雷")

    def test_remote_rules_can_be_set_for_another_country(self):
        here = {**CFG, "location": {**CFG["location"], "remote_home": [r"\buk\b", "united kingdom"],
                                    "remote_elsewhere": [r"\bus\b", "united states", "germany"]}}
        for location, expected in {"Remote - UK": "remote", "Remote": "remote", "Remote, United States": "out", "Remote - Germany": "out"}.items():
            with self.subTest(location):
                self.assertEqual(score.classify_location(location, "", here), expected)
        self.assertEqual(score.classify_location("Remote - Portugal", "", CFG), "out")
        self.assertEqual(score.classify_location("Remote - UK", "", CFG), "out")

    def test_before_send_reminders_come_from_config(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            conn = store.connect(Path(folder) / "t.db")
            cfg = {**CFG, "dashboard": {"before_send": ["Ask a friend to read it."]}}
            self.assertEqual(server.build_state(conn, cfg)["before_send"], ["Ask a friend to read it."])
            conn.close()


if __name__ == "__main__":
    unittest.main()
