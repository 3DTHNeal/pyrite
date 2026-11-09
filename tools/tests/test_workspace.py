"""Finding, creating and guarding the workspace, and importing earlier applications."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path

from support import CFG, CODE_ROOT, FACTS_STILL_EXAMPLE, WORKSPACE, WORKSPACE_TODOS, Base

import pyrite
from pyrite import checks, cli, doctor, launch, score, server, store, tasks, workspace
from pyrite.workspace import INIT_EXAMPLE_HEADER, INIT_NAMED_FILES

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


def made(folder: Path) -> Path:
    """A folder that's a workspace as far as finding one goes: it has a profile/search.toml."""
    (folder / "profile").mkdir(parents=True)
    (folder / "profile" / "search.toml").write_text("", encoding="utf-8")
    return folder


class Workspace(unittest.TestCase):
    def find(self, env=None, pointer=None):
        with mock.patch.dict(os.environ, {"PYRITE_HOME": env or ""}), mock.patch.object(store, "HOME_POINTER", pointer or Path("no-such-file")):
            return store.find_workspace()

    def test_defaults_to_the_fictional_example(self):
        self.assertEqual(self.find(), store.EXAMPLE_ROOT)

    def test_environment_wins_over_the_pointer_file(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            first, second = made(Path(folder) / "first"), made(Path(folder) / "second")
            pointer = Path(folder) / "pointer"
            pointer.write_text(f"{second}\n", encoding="utf-8")
            self.assertEqual(self.find(pointer=pointer), second.resolve())
            self.assertEqual(self.find(env=str(first), pointer=pointer), first.resolve())

    def test_missing_workspace_stops_instead_of_starting_empty(self):
        with self.assertRaises(SystemExit) as caught:
            self.find(env=str(WORKSPACE / "does-not-exist"))
        self.assertIn("pyrite init", str(caught.exception.code))  # Named first and made second is a normal way to start.
        # For `init` and help, which the entry point marks, it isn't there yet and that's fine.
        with mock.patch.dict(os.environ, {store.MAY_BE_MISSING: "1"}):
            self.assertEqual(self.find(env=str(WORKSPACE / "does-not-exist")), store.EXAMPLE_ROOT)

    def test_init_and_help_work_before_the_named_workspace_is_made(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = Path(folder) / "my-job-search"
            env = {**os.environ, "PYRITE_HOME": str(target)}
            env.pop(store.MAY_BE_MISSING, None)
            script = str(CODE_ROOT / "tools" / "pyrite.py")
            ran = subprocess.run([sys.executable, script, "--help"], env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(ran.returncode, 0, ran.stderr)
            # So does help on one command, wherever the flag is.
            for argv in (["queue", "--help"], ["fill", "-h"]):
                ran = subprocess.run([sys.executable, script, *argv], env=env, capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertIn(f"usage: pyrite {argv[0]}", ran.stdout)
            ran = subprocess.run([sys.executable, script, "doctor"], env=env, capture_output=True, text=True, encoding="utf-8")
            self.assertIn("doesn't exist", ran.stderr)
            ran = subprocess.run([sys.executable, script, "init", str(target), "--name", "Sam Doe"], env=env, capture_output=True,
                                 text=True, encoding="utf-8", cwd=folder)
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertIn("PYRITE_HOME already names it", ran.stdout)
            self.assertTrue((target / "profile" / "facts.md").is_file())

    def test_paths_follow_the_workspace_and_code_stays_put(self):
        self.assertEqual(store.ROOT, WORKSPACE.resolve())
        self.assertEqual(store.DB_PATH, WORKSPACE.resolve() / "data" / "pyrite.db")
        self.assertTrue((store.CODE_ROOT / "tools" / "pyrite.py").exists())

    def test_a_pointer_saved_by_powershell_or_with_a_byte_order_mark_is_read(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = made(Path(folder) / "workspace")
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
            target = made(Path(folder) / "workspace").resolve()
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
        self.assertIn("pyrite init", str(caught.exception.code))

    def test_a_folder_that_isnt_a_workspace_stops_rather_than_getting_an_empty_database(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            empty = Path(folder) / "empty"
            empty.mkdir()
            with self.assertRaises(SystemExit) as caught:
                self.find(env=str(empty))
            self.assertIn("isn't a Pyrite workspace", str(caught.exception.code))
            self.assertIn(f"pyrite init {empty.resolve()}", str(caught.exception.code))
            (empty / "profile").mkdir()
            with self.assertRaises(SystemExit) as caught:
                self.find(env=str(empty))
            self.assertIn("Copy example/profile/search.toml", str(caught.exception.code))
            self.assertFalse((empty / "data").exists())
            # A database alone is enough: it's what can't be lost, and load_config says what else is missing.
            (empty / "data").mkdir()
            (empty / "data" / "pyrite.db").write_bytes(b"")
            self.assertEqual(self.find(env=str(empty)), empty.resolve())
            with mock.patch.dict(os.environ, {store.MAY_BE_MISSING: "1"}):
                self.assertEqual(self.find(env=folder), store.EXAMPLE_ROOT)  # For `init` and help.

    def test_a_command_starts_no_database_where_there_is_no_search_toml(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            db = Path(folder) / "data" / "pyrite.db"
            with mock.patch.object(store, "DB_PATH", db), mock.patch.object(store, "CONFIG_PATH", Path(folder) / "profile" / "search.toml"), \
                    contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught:
                cli.main(["brief", "Morning."])
            self.assertIn("search.toml", str(caught.exception.code))
            self.assertNotIn("saved", out.getvalue())
            self.assertFalse(db.exists())

    def test_a_workspace_inside_the_repository_is_refused_but_the_demos_example_is_not(self):
        with self.assertRaises(SystemExit) as caught:
            self.find(env=str(CODE_ROOT / "docs"))
        self.assertIn("inside the code repository", str(caught.exception.code))
        self.assertIn("pyrite init ../my-job-search", str(caught.exception.code))
        # A relative path read from inside the repository is the same folder.
        with mock.patch.object(store.Path, "cwd", return_value=CODE_ROOT), self.assertRaises(SystemExit) as caught:
            self.find(env="docs")
        self.assertIn("inside the code repository", str(caught.exception.code))
        self.assertEqual(self.find(env=str(CODE_ROOT / "example")), store.EXAMPLE_ROOT)

    def test_a_relative_pointer_is_read_from_its_own_folder_past_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = made(Path(folder) / "my-job-search").resolve()
            code = Path(folder) / "code"
            code.mkdir()
            pointer = code / ".pyrite-home"
            pointer.write_text("# Where my job search lives.\n\n../my-job-search\n# ../an-old-one\n", encoding="utf-8")
            # Started from anywhere else, it still names the same folder.
            with mock.patch.object(store.Path, "cwd", return_value=Path(folder) / "elsewhere"):
                self.assertEqual(self.find(pointer=pointer), target)
                with mock.patch.object(store, "HOME_POINTER", pointer):
                    self.assertEqual(store.pointer_target(), target)
            pointer.write_text("# Nothing yet.\n", encoding="utf-8")
            self.assertEqual(self.find(pointer=pointer), store.EXAMPLE_ROOT)

    def test_a_relative_pyrite_home_is_made_whole_for_the_processes_this_starts(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            target = made(Path(folder) / "my-job-search").resolve()
            with mock.patch.dict(os.environ, {"PYRITE_HOME": "my-job-search"}), mock.patch.object(store, "HOME_POINTER", Path("no-such-file")), \
                    mock.patch.object(store.Path, "cwd", return_value=Path(folder)):
                self.assertEqual(store.find_workspace(), target)
                self.assertEqual(os.environ["PYRITE_HOME"], str(target))

    def config(self, text: str, encoding: str = "utf-8") -> Path:
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "search.toml"
        path.write_text(text, encoding=encoding)
        patcher = mock.patch.object(store, "CONFIG_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def test_a_search_toml_saved_with_a_byte_order_mark_reads(self):
        # Windows PowerShell 5.1's Set-Content -Encoding UTF8 starts the file with one.
        self.config((store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8"), encoding="utf-8-sig")
        self.assertEqual(store.load_config()["candidate"], CFG["candidate"])

    def test_a_search_toml_that_isnt_toml_names_the_line_without_a_traceback(self):
        self.config('[run]\nmin_score = 40\ntriage_per_day 20\n')
        with self.assertRaisesRegex(store.ConfigError, r"search\.toml line 3: .*Fix that line"):
            store.load_config()
        with contextlib.redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit) as caught, \
                mock.patch.object(doctor, "tool_checks", return_value=[]):
            cli.main(["doctor"])
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("line 3", out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            cli.main(["sources"])
        self.assertRegex(str(caught.exception.code), r"^\S*search\.toml line 3: ")

    def test_a_number_written_as_text_is_named(self):
        text = (store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8")
        for old, new, named in (("min_score = 40", 'min_score = "forty"', 'min_score under [run] is "forty"'),
                                ("ghost_age_days = 90", "ghost_age_days = true", "ghost_age_days under [freshness]"),
                                ("['python', 3]", "['python', '3']", "keywords under [scoring]"),
                                ("[[3, 30], [7, 20]", "[[3, 'thirty'], [7, 20]", "age_points under [freshness]")):
            with self.subTest(named):
                self.assertIn(old, text)
                self.config(text.replace(old, new))
                with self.assertRaises(store.ConfigError) as caught:
                    store.load_config()
                self.assertIn(named, str(caught.exception))


class NewWorkspace(unittest.TestCase):
    """A workspace made the way docs/setup.md says, by copying example/profile/, and what's left to change in it."""

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
        for path, _, _ in doctor.EXAMPLE_SETTINGS:
            table = cfg
            for key in path[:-1]:
                table = table.setdefault(key, {})
            table[path[-1]] = {"Mine": ["mine.example"]} if path[-1] == "domains" else ["Mine"]
        # Still blocking every name the fact bank's "Do not use" section lists, as a real one should.
        cfg["guard"]["forbidden"] = [*self.cfg()["guard"]["forbidden"], r"\bMine\b"]
        return cfg

    # Profile files written from scratch, as someone making the workspace theirs would, in the form the assay reads.
    OWN_TEXT = {
        "profile/facts.md": "# Fact bank\n\n## Data\n- Moved the nightly batch to Postgres, from 6 hours to 2\n\n## Do not use\n- Internal names: Bluebird\n",
        "profile/approved-terms.txt": "# Mine\nPostgres\nGit\n",
        "profile/run-notes.md": "# Run notes\n\n- **Who:** Sam Doe, open to remote data engineering roles.\n",
        "profile/resume.md": "# Sam Doe\n@ Springfield, IL · sam@example.com\n\n## Experience\n### Acme Data | Jan 2020 – Oct 2026\n"
                             "#### Senior Data Engineer | Springfield, IL | Jan 2020 – Oct 2026\n- Cut nightly batch time from 6 hours to 2.\n\n"
                             "## Education\n- B.S., Computer Science\n",
        "profile/cover-letter.md": "# Sam Doe\n@ Springfield, IL · sam@example.com\n\nDear team,\n\nI make data pipelines faster.\n\nSam Doe\n",
    }

    def make_own(self, *rels):
        for rel in rels or doctor.OWN_FILES:
            (self.root / rel).write_text(self.OWN_TEXT[rel], encoding="utf-8")

    def test_a_copied_profile_has_every_source_its_guard_names(self):
        guard = self.cfg()["guard"]
        for rel in [guard["heading_source"], *guard["approved_sources"]]:
            self.assertTrue((self.root / rel).is_file(), rel)
        self.assertFalse([what for what in self.todos() if "isn't in your workspace" in what])

    def test_whatever_is_still_the_examples_is_listed(self):
        self.assertEqual(doctor.still_example(self.root), list(doctor.OWN_FILES))
        todos = "\n".join(self.todos())
        self.assertIn(f"{doctor.OWN_FILES[0]}, ", todos)  # One finding for them all, the first named with its folder.
        for expected in (*(Path(rel).name for rel in doctor.OWN_FILES), *doctor.OPTIONAL_FILES, "[candidate] name", "allowed_hosts",
                         "profile/seed.toml",
                         *(table for _, table, _ in doctor.EXAMPLE_SETTINGS), *(key for _, _, key in doctor.EXAMPLE_SETTINGS if key)):
            self.assertIn(expected, todos)

    def test_the_examples_settings_are_named_together_by_table_and_only_while_unchanged(self):
        cfg = self.own_settings()
        self.assertFalse([what for what in self.todos(cfg) if "still has the example's" in what])
        example = self.cfg()
        cfg["guard"]["expected_on_resume"] = example["guard"]["expected_on_resume"]
        left = [what for what in self.todos(cfg) if "still has the example's" in what]
        self.assertEqual(left, ["profile/search.toml still has the example's [guard] expected_on_resume."])
        cfg["guard"]["ordinary_words"] = example["guard"]["ordinary_words"]
        cfg["track"] = example["track"]
        left = [what for what in self.todos(cfg) if "still has the example's" in what]
        self.assertEqual(left, ["profile/search.toml still has the example's [[track]]; [guard] ordinary_words and expected_on_resume."])
        cfg["guard"]["expected_on_resume"] = cfg["guard"]["ordinary_words"] = cfg["track"] = []  # Emptied counts as yours.
        self.assertFalse([what for what in self.todos(cfg) if "still has the example's" in what])

    def test_a_file_edited_only_here_and_there_is_still_the_examples(self):
        # The note at the top of facts.md is the first thing anyone deletes, and the fictional facts are all still there.
        path = self.root / "profile" / "facts.md"
        text = path.read_text(encoding="utf-8")
        path.write_text("\n".join(row for row in text.splitlines() if "fictional candidate" not in row), encoding="utf-8")
        self.assertIn("profile/facts.md", doctor.still_example(self.root))
        finding = next(todo for todo in WORKSPACE_TODOS(self.root, self.cfg()) if "still the fictional example's" in todo["what"])
        self.assertIn("profile/facts.md has been edited but still has the example's lines, such as: ", finding["fix"])
        self.assertEqual(finding["tab"], "facts")  # The dashboard's Facts tab can fix it, so the to-do item opens it.
        # Two of the example's sentences could be coincidence or a deliberate keep. Three or more is the example's.
        own = self.OWN_TEXT["profile/facts.md"]
        kept = doctor.example_lines_left(self.root, "profile/facts.md")
        for count, expected in ((2, False), (3, True)):
            path.write_text(own + "\n".join(kept[:count]) + "\n", encoding="utf-8")
            self.assertEqual("profile/facts.md" in doctor.still_example(self.root), expected, count)

    def test_short_terms_shared_with_the_example_dont_make_a_file_the_examples(self):
        # Anyone might list Git or CAN, so approved-terms.txt is the example's only while it's unchanged.
        path = self.root / "profile" / "approved-terms.txt"
        path.write_text(path.read_text(encoding="utf-8") + "Postgres\n", encoding="utf-8")
        self.assertNotIn("profile/approved-terms.txt", doctor.still_example(self.root))

    def test_a_workspace_made_its_own_has_nothing_left(self):
        self.make_own()
        for rel in doctor.OPTIONAL_FILES:
            path = self.root / rel
            path.write_text(path.read_text(encoding="utf-8") + "\nMine now.\n", encoding="utf-8")
        self.edit_config('name = "Alex Rivera"', 'name = "Sam Doe"')
        self.edit_config("allowed_hosts = ['workstation', 'workstation.example-tailnet.ts.net']", "allowed_hosts = []")
        (self.root / "profile" / "seed.toml").unlink()
        cfg = self.own_settings()
        cfg["candidate"]["name"] = "Sam Doe"
        self.assertEqual(self.todos(cfg), [])

    def test_a_master_the_assay_cant_read_is_named_with_what_it_lacks(self):
        resume, letter = self.root / "profile" / "resume.md", self.root / "profile" / "cover-letter.md"
        resume.write_text("Sam Doe\nsam@example.com\n\n## Experience\nAcme, 2020 to now\n", encoding="utf-8")
        letter.write_text("# Alex Rivera\n@ Elsewhere · other@example.com\n\nDear team,\n", encoding="utf-8")
        todos = self.todos()
        self.assertIn("profile/resume.md has no '# Alex Rivera' line, no '@ ' contact line, no '## Education' section and "
                      "no '### Employer | dates' heading, so no resume drafted from it can pass the assay.", todos)
        # The resume has no contact line now, so the letter's is the first one and matches itself.
        self.assertFalse([what for what in todos if what.startswith("profile/cover-letter.md")])
        resume.write_text("# Alex Rivera\n@ Madison, WI · alex@example.com\n## Experience\n### Acme | 2020\n## Education\n", encoding="utf-8")
        todos = self.todos()
        self.assertFalse([what for what in todos if what.startswith("profile/resume.md")])
        self.assertIn("profile/cover-letter.md has a contact line that differs from the resume's, so no letter drafted from it "
                      "can pass the assay.", todos)

    def test_a_master_still_the_examples_is_named_once_not_twice(self):
        self.assertFalse([what for what in self.todos() if "can pass the assay" in what])

    def test_do_not_use_names_are_read_from_the_fact_bank(self):
        facts = "# Facts\n\n## Do not use\n- Project Nightjar\n- Internal names: Bluebird, the Hive\n- Customer names\n\n## Skills\n- Python\n"
        self.assertEqual(checks.unguarded_terms(facts, []), ["Nightjar", "Bluebird", "Hive"])
        self.assertEqual(checks.unguarded_terms(facts, ["Bluebird", r"\bhive\b"]), ["Nightjar"])
        self.assertEqual(checks.unguarded_terms(facts, [r"project nightjar", "Bluebird", r"\bhive\b"]), [])
        self.assertEqual(checks.unguarded_terms("# Facts\n- Python\n", []), [])
        # At any heading level, with its subsections.
        nested = "# Facts\n\n## Notes\n### Don't use\n- Project Nightjar\n#### Customers\n- Customer: Globex\n### Skills\n- Python Pro\n"
        self.assertEqual(checks.unguarded_terms(nested, []), ["Nightjar", "Globex"])
        # A comment saying what goes in the section names nothing.
        self.assertEqual(checks.unguarded_terms("## Do not use\n<!-- Internal names, Customers and Products -->\n", []), [])
        example = (store.EXAMPLE_ROOT / "profile" / "facts.md").read_text(encoding="utf-8")
        self.assertEqual(checks.unguarded_terms(example, self.cfg()["guard"]["forbidden"]), [])

    def test_a_do_not_use_name_needs_no_pattern_unless_your_sources_state_it(self):
        self.make_own("profile/facts.md")
        path = self.root / "profile" / "facts.md"
        path.write_text(path.read_text(encoding="utf-8").replace("## Do not use\n", "## Do not use\n- Project Nightjar\n"), encoding="utf-8")
        cfg = self.cfg()
        read = lambda rel: (self.root / rel).read_text(encoding="utf-8")
        blocked, shared = checks.listed_terms(cfg, read)
        self.assertEqual([term for term, _, _ in blocked], ["Nightjar"])  # Blocked by name, so nothing's left to do.
        self.assertEqual(shared, [])
        self.assertFalse(any("Nightjar" in what for what in self.todos()))
        # A name the fact bank also states as fact can't be blocked by name without failing every draft that states it.
        path.write_text(path.read_text(encoding="utf-8").replace("## Data\n", "## Data\n- Shipped Nightjar on time\n"), encoding="utf-8")
        self.assertEqual(checks.listed_terms(cfg, read)[1], [("Nightjar", "profile/facts.md")])
        todo = next(todo for todo in WORKSPACE_TODOS(self.root, cfg) if "Nightjar" in todo["what"])
        self.assertIn("can't block it by name", todo["what"])
        self.assertEqual((todo["step"], todo["severity"]), ("offlimits", "bad"))
        # A fact bank that's still the example's is named as that, not picked apart term by term.
        shutil.copy(store.EXAMPLE_ROOT / "profile" / "facts.md", path)
        path.write_text(path.read_text(encoding="utf-8").replace("## Do not use\n", "## Do not use\n- Project Nightjar\n")
                        .replace("## Leadership\n", "## Leadership\n- Shipped Nightjar on time\n"), encoding="utf-8")
        self.assertFalse(any("Nightjar" in what for what in self.todos()))

    def test_an_unsupported_line_that_no_pattern_matches_is_a_todo(self):
        self.make_own("profile/facts.md")
        self.assertFalse(any("Unsupported" in what for what in self.todos()))
        path = self.root / "profile" / "facts.md"
        path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n\n## Unsupported\n- Safety certification\n- Any Six Sigma belt\n",
                        encoding="utf-8")
        todo = next(todo for todo in WORKSPACE_TODOS(self.root, self.cfg()) if "Unsupported" in todo["what"])
        self.assertIn("lists a claim under", todo["what"])
        self.assertIn("“Any Six Sigma belt”", todo["what"])
        self.assertEqual(todo["step"], "offlimits")
        # A pattern that matches the line is all it takes.
        cfg = self.cfg()
        cfg["guard"]["unsupported"] = [*cfg["guard"]["unsupported"], "six sigma"]
        self.assertFalse(any("Unsupported" in todo["what"] for todo in WORKSPACE_TODOS(self.root, cfg)))

    def test_explanations_instructions_and_your_own_name_arent_taken_for_secret_names(self):
        # Blocking any of these would do harm: your own name would fail every draft.
        facts = ("# Facts\n\n## Do not use\n"
                 "- Mentions of calibration (Alex Rivera removed them from LinkedIn, 2026-11-06). Say \"Machine Control\" instead.\n"
                 "- Rivera's old team codename Nightjar; Use the plain name.\n"
                 "- Firmware 2.5 Bluebird build\n")
        self.assertEqual(checks.unguarded_terms(facts, [], "Alex Rivera"), ["Nightjar", "Bluebird"])

    def test_outside_a_venv_the_fix_makes_one_rather_than_installing_into_that_python(self):
        self.assertIn("-m venv .venv", doctor.install_fix(in_venv=False))
        self.assertNotIn("-m venv", doctor.install_fix(in_venv=True))

    def test_doctor_wraps_long_lines_without_splitting_a_path(self):
        path = "D:\\job-search\\" + "x" * 120 + "\\facts.md"
        text = cli._doctor_line("TO DO", f"{'word ' * 40}{path}", "first\nsecond")
        self.assertIn(path, text)
        self.assertTrue(text.startswith("  TO DO  word"))
        self.assertTrue(all(line.startswith(" " * 9) for line in text.splitlines()[1:]))
        self.assertIn("\n         second", text)

    def test_a_guard_source_that_isnt_there_is_named(self):
        self.edit_config("heading_source = 'profile/resume.md'", "heading_source = 'profile/master.md'")
        self.assertTrue(any("heading_source" in what and "profile/master.md" in what for what in self.todos()))

    def test_a_seed_folder_that_isnt_there_is_named(self):
        (self.root / "profile" / "seed.toml").write_text(
            '[[application]]\ncompany = "Initech"\ntitle = "Engineer"\nfolder = "applications/gone"\n', encoding="utf-8")
        self.assertTrue(any("applications/gone" in what for what in self.todos()))

    def test_a_watch_entry_or_a_pattern_written_wrong_is_named(self):
        cfg = self.cfg()
        cfg["watch"]["workday"] = {"globex": "Globex"}
        cfg["scoring"]["keywords"].append(["c++(", 3])
        todos = self.todos(cfg)
        self.assertTrue(any(what.startswith("[watch.workday] globex") and "wd and site" in what for what in todos), todos)
        self.assertTrue(any("keywords under [scoring]" in what and "'c++('" in what for what in todos), todos)

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
            # The dashboard gets the same reasons up front, to disable those buttons rather than refuse after a click.
            not_ready = server.build_state(self.conn, CFG)["not_ready"]
            self.assertEqual(set(not_ready), set(tasks.WRITERS))
            self.assertIn("profile/facts.md", not_ready[tasks.CLAUDE])
        self.assertEqual(server.build_state(self.conn, CFG)["not_ready"], {})

    def test_editing_one_line_of_the_facts_doesnt_unlock_the_claude_runs(self):
        path = WORKSPACE / "profile" / "facts.md"
        original = path.read_text(encoding="utf-8")
        self.addCleanup(path.write_text, original, encoding="utf-8")
        path.write_text(original.replace("fictional candidate", "candidate"), encoding="utf-8")
        with mock.patch.object(tasks, "_facts_still_example", FACTS_STILL_EXAMPLE):
            self.assertIn("profile/facts.md", tasks.refusal(self.conn, tasks.CLAUDE))

    def test_the_dashboard_lists_setup_first_and_the_demo_never_does(self):
        left = [{"what": "profile/facts.md is still the fictional example's.", "fix": "Replace it.", "tab": "facts"}]
        with mock.patch.object(doctor, "workspace_todos", return_value=left):
            orders = server.build_state(self.conn, CFG)["orders"]
            self.assertEqual((orders[0]["kind"], orders[0]["job_id"], orders[0]["text"]), ("Finish setup", None, left[0]["what"]))
            self.assertEqual(orders[0]["tab"], "facts")  # Clicking it opens the tab that fixes it.
            with mock.patch.object(server, "IS_EXAMPLE", True):
                self.assertEqual(server._setup_orders(CFG), [])


class CommandLine(unittest.TestCase):
    def test_help_lists_no_hidden_worker(self):
        text = cli.build_parser().format_help()
        self.assertNotIn("SUPPRESS", text)
        self.assertNotRegex(text, r"(?m)^\s+task\b")
        self.assertEqual(cli.build_parser().parse_args(["task", "3"]).id, 3)  # The dashboard's worker still runs.

    def run_cli(self, *argv):
        """(stdout, stderr, exit code) of one command line."""
        out, err, code = io.StringIO(), io.StringIO(), 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(list(argv))
            except SystemExit as stop:
                code = stop.code if isinstance(stop.code, int) else 1
                err.write(str(stop.code) if not isinstance(stop.code, int) else "")
        return out.getvalue(), err.getvalue(), code

    def test_the_bare_command_prints_help_with_where_to_start(self):
        out, _, code = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("usage: pyrite", out)
        self.assertIn(cli.INIT_EXAMPLE, out)
        self.assertIn("python tools/pyrite.py", out)  # Before `pip install -e .`, there's no pyrite command to type.
        self.assertNotIn("<folder>", out)  # Copied as it is, a shell reads it as redirection.

    def test_help_explains_one_command_or_lists_them(self):
        self.assertIn("usage: pyrite init", self.run_cli("help", "init")[0])
        self.assertIn("usage: pyrite [-h]", self.run_cli("help")[0])
        _, err, code = self.run_cli("help", "task")
        self.assertEqual(code, 1)
        self.assertIn("isn't a Pyrite command", err)

    def test_a_mistyped_command_suggests_the_one_meant(self):
        for typed, meant in (("dcotor", "doctor"), ("Doctor", "doctor"), ("serv", "serve"), ("int", "init")):
            _, err, code = self.run_cli(typed)
            self.assertEqual(code, 1, typed)
            self.assertIn(f"Did you mean `pyrite {meant}`?", err)
        _, err, _ = self.run_cli("tsak")
        self.assertNotIn("pyrite task", err)  # The hidden worker is never offered.

    def test_an_unquoted_value_with_a_space_says_to_quote_it(self):
        _, err, code = self.run_cli("add", "--company", "Acme", "Robotics", "--title", "Engineer")
        self.assertEqual(code, 2)
        self.assertIn('--company "Acme Robotics"', err)
        _, err, _ = self.run_cli("where", "--bogus")
        self.assertIn("unrecognized arguments: --bogus", err)
        self.assertNotIn("quotes", err)

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
        for old, _ in INIT_EXAMPLE_HEADER:
            self.assertIn(old, text)
        example_name = cli.INIT_EXAMPLE_NAME.split('"')[1]
        for file in INIT_NAMED_FILES:
            self.assertIn(f"# {example_name}\n", (store.EXAMPLE_ROOT / "profile" / file).read_text(encoding="utf-8"))

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
        self.assertRegex(todos, r"^profile/facts\.md, .* are still the fictional example's")  # Making it yours is the next step.
        # The name goes on the master resume and letter too, and the rest of them is still the example's to replace.
        self.assertIn("resume.md", todos)
        self.assertNotIn("has no '# ", todos)
        for file in INIT_NAMED_FILES:
            text = (self.folder / "profile" / file).read_text(encoding="utf-8")
            self.assertTrue(text.startswith('# Sam "Q" Doe\n'), file)
            self.assertNotRegex(text, r"(?m)^(# )?Alex Rivera$")
        # The top of search.toml no longer says it's the example's own.
        self.assertNotIn("This is the fictional candidate's search", (self.folder / "profile" / "search.toml").read_text(encoding="utf-8"))

    def test_a_name_is_required_so_the_example_name_never_carries_over(self):
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("Give your name", str(caught.exception.code))
        self.assertFalse(self.folder.exists())
        self.assertFalse(self.pointer.exists())

    def test_a_placeholder_copied_from_the_docs_is_refused_before_anything_is_made(self):
        for extra in (("--name", "Your Name"), ("--name", "<your name>"), ("--name", "[Name]")):
            with self.assertRaises(SystemExit) as caught:
                self.init(*extra)
            self.assertIn("placeholder", str(caught.exception.code))
        self.folder = self.base / "<folder>"
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn(cli.INIT_EXAMPLE, str(caught.exception.code))
        self.assertEqual(list(self.base.iterdir()), [])
        self.assertFalse(self.pointer.exists())

    def test_doctor_flags_a_placeholder_name_left_in_search_toml(self):
        self.init("--name", "Sam Doe")
        cfg = self.cfg()
        cfg["candidate"]["name"] = "Your Name"
        todos = [todo["what"] for todo in WORKSPACE_TODOS(self.folder, cfg)]
        self.assertIn('[candidate] name in profile/search.toml is "Your Name", a placeholder.', todos)

    def test_an_existing_profile_is_left_alone(self):
        (self.folder / "profile").mkdir(parents=True)
        (self.folder / "profile" / "facts.md").write_text("Mine.", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("nothing was changed", str(caught.exception.code))
        self.assertIn(f"put its path in {self.pointer}", str(caught.exception.code))
        self.assertIn("no profile/search.toml", str(caught.exception.code))
        self.assertEqual((self.folder / "profile" / "facts.md").read_text(encoding="utf-8"), "Mine.")
        self.assertFalse(self.pointer.exists())
        # Where Pyrite is pointed elsewhere, it says what to change, and doesn't tell you to do what's already done.
        with mock.patch.dict(os.environ, {"PYRITE_HOME": "/elsewhere"}), self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("PYRITE_HOME is set to /elsewhere", str(caught.exception.code))
        self.pointer.write_text("my-job-search\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn(f"{self.pointer} already names it", str(caught.exception.code))

    def test_a_pointer_that_already_names_the_folder_says_so(self):
        # Written relative to its own folder, and so not as `init` would write it, but the same folder all the same.
        self.pointer.write_text("# My job search\nmy-job-search\n", encoding="utf-8")
        out = self.init("--name", "Sam Doe")
        self.assertIn(f"{self.pointer} already names it, so Pyrite uses it from now on.", out)
        self.assertNotIn("Put ", out)
        self.assertEqual(self.pointer.read_text(encoding="utf-8"), "# My job search\nmy-job-search\n")

    def test_a_file_or_a_folder_that_cant_be_written_is_refused_in_a_line(self):
        self.folder.write_text("Not a folder.", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.init("--name", "Sam Doe")
        self.assertIn("is a file, not a folder", str(caught.exception.code))
        self.folder.unlink()
        with mock.patch.object(workspace, "_copy_example", side_effect=PermissionError(13, "Access is denied")), \
                self.assertRaises(SystemExit) as caught:
            self.init("--name", "Sam Doe")
        self.assertIn("Couldn't make a workspace", str(caught.exception.code))
        self.assertIn("Access is denied", str(caught.exception.code))
        self.assertFalse(self.folder.exists())  # Nothing half-made is left to stop the next try.
        self.assertFalse(self.pointer.exists())

    def test_running_it_again_on_the_workspace_in_use_changes_nothing_and_isnt_an_error(self):
        self.init("--name", "Sam Doe")
        (self.folder / "profile" / "facts.md").write_text("Mine.", encoding="utf-8")
        with mock.patch.object(store, "ROOT", self.folder.resolve()):
            out = self.init()
        self.assertIn("already the workspace in use", out)
        self.assertEqual((self.folder / "profile" / "facts.md").read_text(encoding="utf-8"), "Mine.")

    def test_a_folder_inside_the_repository_is_refused(self):
        self.folder = CODE_ROOT / "my-job-search"
        with self.assertRaises(SystemExit) as caught:
            self.init()
        self.assertIn("inside this repository", str(caught.exception.code))
        self.assertIn(f"pyrite init {Path('..') / 'my-job-search'}", str(caught.exception.code))  # Where to put it instead.
        self.assertFalse(self.folder.exists())

    def test_a_workspace_already_named_is_never_replaced(self):
        self.pointer.write_text("/somewhere/else\n", encoding="utf-8")
        out = self.init("--name", "Sam Doe")
        self.assertEqual(self.pointer.read_text(encoding="utf-8"), "/somewhere/else\n")
        self.assertIn("left alone", out)
        with mock.patch.dict(os.environ, {"PYRITE_HOME": "/elsewhere"}):
            self.pointer.unlink()
            self.folder = self.base / "second"
            self.assertIn("PYRITE_HOME", self.init("--name", "Sam Doe"))
        self.assertFalse(self.pointer.exists())

    # ---- --blank ----

    def test_the_comment_lines_a_blank_config_changes_are_in_the_example(self):
        lines = (store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8").splitlines()
        for old, _ in workspace.BLANK_COMMENTS:
            self.assertIn(old, lines)

    def test_blank_writes_headings_and_comments_and_nothing_of_the_examples(self):
        out = self.init("--name", "Sam Doe", "--blank")
        self.assertIn("blank profile files", out)
        profile = self.folder / "profile"
        self.assertEqual(sorted(path.name for path in profile.iterdir()),
                         ["approved-terms.txt", "cover-letter.md", "facts.md", "resume.md", "run-notes.md", "search.toml"])
        for path in profile.iterdir():
            text = path.read_text(encoding="utf-8")
            for word in ("Alex", "Rivera", "Madison", "Wisconsin", "WI", "Northbridge", "Bluebird", "SkyLift", "Sunnydale", "Hooli",
                         "Cyberdyne", "firmware", "anthropic"):
                self.assertNotRegex(text, rf"(?i)\b{word}\b", f"{path.name} still names {word}")
        for file in INIT_NAMED_FILES:
            self.assertTrue((profile / file).read_text(encoding="utf-8").startswith("# Sam Doe\n"), file)
        # search.toml is the example's, with only what describes the fictional candidate emptied.
        cfg, example = self.cfg(), tomllib.loads((store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8"))
        for table, key in workspace.BLANK_EMPTIED:
            self.assertEqual(cfg[table][key], [], (table, key))
            example[table][key] = []
        for table, key in workspace.BLANK_DROPPED:
            del example[table][key]
        for table in workspace.BLANK_CLEARED:
            outer, inner = table.split(".")
            example[outer][inner] = {}
        del example["track"], example["promote"]["industry"]
        example["candidate"]["name"] = "Sam Doe"
        self.assertEqual(cfg, example)
        self.assertIn("# [[track]]", (profile / "search.toml").read_text(encoding="utf-8"))  # The form is shown where they go.

    def test_doctor_reports_what_a_blank_workspace_leaves_empty(self):
        self.init("--name", "Sam Doe", "--blank")
        todos = WORKSPACE_TODOS(self.folder, self.cfg())
        whats = [todo["what"] for todo in todos]
        self.assertIn("profile/facts.md, run-notes.md, resume.md and cover-letter.md are still blank.", whats)
        blank = next(todo for todo in todos if "still blank" in todo["what"])
        self.assertEqual((blank["step"], blank["tab"]), ("basics", "facts"))
        self.assertIn("profile/search.toml lists no roles under [[track]], so a pan keeps no postings.", whats)
        self.assertIn("profile/search.toml watches no companies, so a pan reads no job boards.", whats)
        # Named as blank, so not again as masters the assay can't read, or as the example's.
        self.assertFalse([what for what in whats if "can pass the assay" in what or "example's" in what or "Do not use" in what])
        # Filling in a file takes it off. A label with nothing after it, or a comment, is still blank.
        notes = self.folder / "profile" / "run-notes.md"
        self.assertIn("profile/run-notes.md", doctor.still_blank(self.folder))
        notes.write_text(notes.read_text(encoding="utf-8").replace("- **Who:**", "- **Who:** Sam Doe, open to remote roles."), encoding="utf-8")
        self.assertNotIn("profile/run-notes.md", doctor.still_blank(self.folder))

    def test_a_blank_fact_bank_approves_nothing_and_has_no_contact_line_yet(self):
        from pyrite import factsdoc

        self.init("--name", "Sam Doe", "--blank")
        facts = (self.folder / "profile" / "facts.md").read_text(encoding="utf-8")
        self.assertIsNone(factsdoc.Doc(facts).contact())  # The comment under ## Contact isn't taken for the line.
        self.assertEqual(checks.claimable(facts).count("<!--"), 0)
        self.assertNotIn("Education", checks.claimable(facts))  # A word in a comment approves nothing.
        self.assertEqual(checks.listed_terms(self.cfg(), lambda rel: (self.folder / rel).read_text(encoding="utf-8")), ([], []))

    def test_the_claude_runs_wait_for_a_blank_fact_bank(self):
        self.init("--name", "Sam Doe", "--blank")
        with mock.patch.object(tasks, "ROOT", self.folder), mock.patch.object(tasks, "IS_EXAMPLE", False), \
                mock.patch.object(tasks, "_facts_still_example", return_value=False):
            self.assertIn("still blank", tasks.not_ready(tasks.CLAUDE))
            self.assertIsNone(tasks.not_ready(tasks.SWEEP))

    # ---- --git ----

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.folder), *args], capture_output=True, text=True, check=False)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_git_makes_a_private_repository_that_keeps_the_database_and_leaves_out_working_files(self):
        out = self.init("--name", "Sam Doe", "--git")
        self.assertTrue((self.folder / ".git").is_dir())
        self.assertEqual(self.git("remote").stdout.strip(), "")  # Never a remote.
        self.assertIn("can't be regenerated", out)
        self.assertNotIn("--git` makes it one", out)
        ignored = ["data/pyrite.db-wal", "data/pyrite.db-shm", "data/confirm-code.json", "data/browser/Default/Cookies",
                   "profile/search.previous.toml", "applications/acme/resume.previous.md", "applications/acme/~$m_Doe_Resume_Acme.docx",
                   "data/market/area_titles.csv", "data/market/qcew/index.json"]
        kept = ["data/pyrite.db", "data/history/log.jsonl", "data/market/outlook/robotics.json", "profile/facts.md",
                "applications/acme/Sam_Doe_Resume_Acme.pdf", "applications/acme/Sam_Doe_Resume_Acme.docx",
                "applications/acme/sent/Sam_Doe_Resume_Acme.pdf"]
        for rel in ignored + kept:
            with self.subTest(rel):
                self.assertEqual(self.git("check-ignore", "-q", "--no-index", rel).returncode == 0, rel in ignored)

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_git_on_the_workspace_in_use_sets_up_only_the_repository(self):
        self.init("--name", "Sam Doe")
        (self.folder / "profile" / "facts.md").write_text("Mine.", encoding="utf-8")
        with mock.patch.object(store, "ROOT", self.folder.resolve()):
            out = self.init("--git")
            self.assertIn("files were left as they are", out)
            self.assertTrue((self.folder / ".git").is_dir())
            # Again, it leaves the repository and its .gitignore alone.
            (self.folder / ".gitignore").write_text("mine\n", encoding="utf-8")
            out = self.init("--git")
        self.assertIn("a git repository already", out)
        self.assertEqual((self.folder / ".gitignore").read_text(encoding="utf-8"), "mine\n")
        self.assertEqual((self.folder / "profile" / "facts.md").read_text(encoding="utf-8"), "Mine.")

    def test_git_without_git_installed_makes_nothing(self):
        with mock.patch.object(workspace.shutil, "which", return_value=None), self.assertRaises(SystemExit) as caught:
            self.init("--name", "Sam Doe", "--git")
        self.assertIn("needs git", str(caught.exception.code))
        self.assertFalse(self.folder.exists())

    def test_without_git_it_says_how_to_make_one(self):
        self.assertIn("--git` makes it one", self.init("--name", "Sam Doe"))


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

    def test_ctrl_c_stops_it_quietly_and_frees_the_port(self):
        fake = mock.Mock()
        fake.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(server, "make_server", return_value=fake), mock.patch.object(server, "connect"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            server.serve(8787)
        self.assertIn("Ctrl+C stops it", out.getvalue())
        self.assertTrue(out.getvalue().rstrip().endswith("Stopped."))
        fake.server_close.assert_called_once()

    def test_the_port_comes_from_search_toml_unless_one_is_given(self):
        self.assertEqual(launch.dashboard_port({}), 8787)
        self.assertEqual(launch.dashboard_port({"dashboard": {"port": 8790}}), 8790)
        for wrong in ("8790", 0, 70000, True, 87.9):
            with self.subTest(wrong), self.assertRaises(SystemExit) as caught:
                launch.dashboard_port({"dashboard": {"port": wrong}})
            self.assertIn("port under [dashboard]", str(caught.exception.code))
        cfg = {**CFG, "dashboard": {**CFG["dashboard"], "port": 8790}}
        for argv, port in ((["serve"], 8790), (["serve", "--port", "8791"], 8791)):
            with mock.patch.object(cli, "load_config", return_value=cfg), mock.patch.object(server, "serve") as serve:
                cli.main(argv)
            serve.assert_called_once_with(port)
        with mock.patch.object(cli, "load_config", return_value=cfg), mock.patch.object(launch, "open_dashboard") as opened:
            cli.main(["open"])
        opened.assert_called_once_with(8790)

    def test_the_example_config_documents_the_port(self):
        text = (store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8")
        self.assertIn("# port = 8787", text)


class Open(unittest.TestCase):
    """`pyrite open`, which Pyrite.cmd wraps. Nothing here starts a server, stops a process or opens a browser."""

    def setUp(self):
        self.opened: list[str] = []
        self.child = mock.Mock()
        self.child.poll.return_value = None
        for name, value in (("start", mock.Mock(return_value=self.child)), ("_stop", mock.Mock()), ("listener", mock.Mock(return_value=None)),
                            ("command_line", mock.Mock(return_value="")), ("time", mock.Mock(monotonic=mock.Mock(return_value=0.0)))):
            patcher = mock.patch.object(launch, name, value)
            setattr(self, name.strip("_"), patcher.start())
            self.addCleanup(patcher.stop)

    def run_open(self, answers):
        with mock.patch.object(launch, "answering", side_effect=answers), contextlib.redirect_stdout(io.StringIO()) as out:
            launch.open_dashboard(8790, browse=self.opened.append)
        return out.getvalue()

    def test_a_dashboard_already_answering_is_only_opened(self):
        self.run_open([True])
        self.assertEqual(self.opened, ["http://127.0.0.1:8790/"])
        self.start.assert_not_called()

    def test_with_nothing_on_the_port_it_starts_one_and_opens_it_once_it_answers(self):
        out = self.run_open([False, False, True])
        self.start.assert_called_once_with(8790)
        self.assertEqual(self.opened, ["http://127.0.0.1:8790/"])
        self.assertIn("keeps running", out)

    def test_a_hung_dashboard_is_replaced(self):
        self.listener.return_value = 4321
        self.command_line.return_value = r'"C:\pyrite\.venv\Scripts\pythonw.exe" tools\pyrite.py serve'
        out = self.run_open([False, True])
        self.stop.assert_called_once_with(4321, 8790)
        self.start.assert_called_once_with(8790)
        self.assertIn("stopped answering", out)

    def test_another_program_on_the_port_is_left_alone(self):
        self.listener.return_value = 4321
        self.command_line.return_value = "C:\\Program Files\\Something\\server.exe --listen 8790"
        with self.assertRaises(SystemExit) as caught:
            self.run_open([False])
        self.assertIn("in use by another program", str(caught.exception.code))
        self.assertIn("port under [dashboard]", str(caught.exception.code))
        self.stop.assert_not_called()
        self.start.assert_not_called()

    def test_one_that_stops_at_once_is_run_here_to_show_why(self):
        self.child.poll.return_value = 1
        with mock.patch.object(server, "serve", side_effect=SystemExit("Port 8790 is already in use")) as serve, \
                self.assertRaises(SystemExit):
            self.run_open([False, False])
        serve.assert_called_once_with(8790)
        self.assertEqual(self.opened, [])

    def test_only_pyrites_own_serve_counts_as_a_dashboard(self):
        for line, ours in ((r'"C:\x\.venv\Scripts\pythonw.exe" tools\pyrite.py serve', True),
                           ("/srv/pyrite/.venv/bin/python tools/pyrite.py serve --port 8790", True),
                           ("/srv/pyrite/.venv/bin/pyrite serve", True),
                           ("python -m pyrite serve", True),
                           (r"C:\x\python.exe tools\pyrite.py demo", False),
                           ("node /srv/pyrite-site/node_modules/.bin/vite serve", False),
                           ("", False)):
            with self.subTest(line):
                self.assertEqual(bool(launch.SERVE.search(line)), ours)

    def test_the_listener_is_read_from_netstat_whatever_the_systems_language(self):
        text = ("\nActive Connections\n\n  Proto  Local Address          Foreign Address        State           PID\n"
                "  TCP    0.0.0.0:135            0.0.0.0:0              ABHÖREN         1656\n"
                "  TCP    127.0.0.1:8790         127.0.0.1:50000        HERGESTELLT     99\n"
                "  TCP    127.0.0.1:8790         0.0.0.0:0              ABHÖREN         4321\n")
        self.assertEqual(launch.netstat_listener(text, 8790), 4321)
        self.assertIsNone(launch.netstat_listener(text, 8791))

    def test_pyrite_cmd_is_a_wrapper_around_open(self):
        text = (store.CODE_ROOT / "Pyrite.cmd").read_text(encoding="utf-8")
        self.assertIn(r"tools\pyrite.py open", text)
        self.assertNotIn("127.0.0.1:8787", text)  # No port of its own: it uses the one search.toml sets.


class StartDashboard(unittest.TestCase):
    def test_the_dashboard_it_starts_opens_this_workspace_by_its_whole_path(self):
        # It starts in the code folder, where a relative PYRITE_HOME, or a .pyrite-home edited since, would name another.
        root = Path(tempfile.gettempdir()).resolve() / "my-job-search"
        with mock.patch.object(launch.subprocess, "Popen") as popen, mock.patch.object(launch, "ROOT", root), \
                mock.patch.dict(os.environ, {"PYRITE_HOME": "my-job-search"}):
            launch.start(8790)
        self.assertEqual(popen.call_args.kwargs["env"]["PYRITE_HOME"], str(root))
        self.assertEqual(popen.call_args.kwargs["cwd"], CODE_ROOT)


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

    def test_add_says_when_the_posting_was_already_tracked(self):
        add = ["add", "--company", "Initech", "--title", "Firmware Lead", "--location", "Madison, WI"]
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(add)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(add)
        self.assertRegex(out.getvalue(), r"^Already tracked as job \d+: Initech, Firmware Lead, new\. Nothing was changed\.")
        # The same title in another place is another opening.
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(add[:-1] + ["Remote - US"])
        self.assertRegex(out.getvalue(), r"^Job \d+: Initech")

    def test_folder_starts_the_drafts_from_the_masters_and_never_overwrites_one(self):
        self.root = Path(self.tmp.name) / "mine"
        shutil.copytree(WORKSPACE / "profile", self.root / "profile")
        patcher = mock.patch.object(cli, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["add", "--company", "Initech", "--title", "Firmware Lead"])
        job_id = self.conn.execute("SELECT MAX(id) FROM jobs").fetchone()[0]
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            cli.main(["folder", str(job_id)])
        folder = Path(out.getvalue().strip())
        self.assertEqual({p.name for p in folder.iterdir()}, {"posting.md", "resume.md", "cover-letter.md"})
        master = (self.root / CFG["guard"]["heading_source"]).read_text(encoding="utf-8")
        self.assertEqual((folder / "resume.md").read_text(encoding="utf-8"), master)
        self.assertIn(f"pyrite finish {job_id}", err.getvalue())
        (folder / "resume.md").write_text("Tailored.", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            cli.main(["folder", str(job_id)])
        self.assertEqual((folder / "resume.md").read_text(encoding="utf-8"), "Tailored.")
        self.assertEqual(err.getvalue(), "")

    def test_a_command_that_needs_a_workspace_says_how_to_make_one(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), self.assertRaises(SystemExit) as caught:
            cli.main(["serve"])
        self.assertIn(cli.INIT_EXAMPLE, str(caught.exception.code))

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
