"""First-run setup: the dashboard opening on making a workspace when nothing names one, and a new workspace needing no
codes until its required Profile sections are set."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import cli, confirm, launch, notify, profile, server, steps, store, workspace


class NothingNamed(unittest.TestCase):
    def test_only_no_pyrite_home_and_no_pointer_is_nothing_named(self):
        with tempfile.TemporaryDirectory() as folder:
            pointer = Path(folder) / ".pyrite-home"
            with mock.patch.object(store, "HOME_POINTER", pointer):
                with mock.patch.dict(os.environ, {"PYRITE_HOME": ""}):
                    self.assertTrue(store.nothing_named())
                    pointer.write_text("# a note, and no path\n", encoding="utf-8")
                    self.assertTrue(store.nothing_named())
                    pointer.write_text(f"{folder}\n", encoding="utf-8")
                    self.assertFalse(store.nothing_named())
                pointer.unlink()
                with mock.patch.dict(os.environ, {"PYRITE_HOME": folder}):
                    self.assertFalse(store.nothing_named())


class Commands(unittest.TestCase):
    """With nothing named, the dashboard starts so it can open on setup. Everything else that writes still refuses."""

    def run_cli(self, *argv):
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(store, "IS_EXAMPLE", True):
            cli.main(list(argv))

    def test_serve_and_open_start_the_dashboard_on_setup(self):
        # The parser is built on each run, so it picks these up.
        with mock.patch.object(store, "NEEDS_SETUP", True), mock.patch.object(cli, "cmd_serve") as serve, \
                mock.patch.object(cli, "cmd_open") as opened:
            self.run_cli("serve")
            self.run_cli("open")
        serve.assert_called_once()
        opened.assert_called_once()

    def test_with_the_example_named_on_purpose_serve_still_refuses(self):
        with mock.patch.object(store, "NEEDS_SETUP", False), self.assertRaises(SystemExit) as caught:
            self.run_cli("serve")
        self.assertIn("No workspace is set", str(caught.exception.code))

    def test_commands_that_write_still_refuse_with_nothing_named(self):
        with mock.patch.object(store, "NEEDS_SETUP", True), self.assertRaises(SystemExit) as caught:
            self.run_cli("discover")
        self.assertIn("No workspace is set", str(caught.exception.code))


class Launching(unittest.TestCase):
    def env(self, home=None):
        with mock.patch.object(launch.subprocess, "Popen") as popen:
            launch.start(8790, home)
        return popen.call_args.kwargs["env"]

    def test_with_nothing_named_the_dashboard_starts_with_nothing_named(self):
        # Naming the example would open the demo, not setup.
        with mock.patch.object(launch, "NEEDS_SETUP", True), mock.patch.dict(os.environ, {"PYRITE_HOME": ""}):
            self.assertNotIn("PYRITE_HOME", self.env())

    def test_a_workspace_just_made_is_named_whole(self):
        made = Path(tempfile.gettempdir()) / "my-job-search"
        with mock.patch.object(launch, "NEEDS_SETUP", True):
            self.assertEqual(self.env(made)["PYRITE_HOME"], str(made))

    def test_otherwise_the_workspace_in_use_is_named(self):
        with mock.patch.object(launch, "NEEDS_SETUP", False):
            self.assertEqual(self.env()["PYRITE_HOME"], str(launch.ROOT))

    def test_serve_comes_back_on_the_workspace_setup_made(self):
        made = Path(tempfile.gettempdir()) / "my-job-search"
        stopped = mock.Mock(restarting=True, restart_home=made)
        with mock.patch.object(server, "make_server", return_value=stopped), \
                mock.patch.object(launch, "restart", return_value=True) as restart, \
                mock.patch("builtins.print") as said:
            server.serve(8790)
        restart.assert_called_once_with(8790, made)
        self.assertIn(str(made), said.call_args_list[1].args[0])


class MakingAWorkspace(unittest.TestCase):
    """The page's Make your workspace, which makes one as `pyrite init` does, but only while nothing names one."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        # A stand-in code folder inside the temporary one, so "../mine" lands beside it and never beside the real one.
        self.code = self.base / "pyrite"
        self.code.mkdir()
        self.pointer = self.code / ".pyrite-home"
        for patcher in (mock.patch.object(store, "CODE_ROOT", self.code), mock.patch.object(store, "HOME_POINTER", self.pointer),
                        mock.patch.object(store, "NEEDS_SETUP", True), mock.patch.dict(os.environ, {"PYRITE_HOME": ""})):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, body):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/setup", method="POST",
                                         headers={"Content-Type": "application/json"}, data=json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_the_page_is_told_where_to_suggest(self):
        info = server.setup_info()
        self.assertEqual(info["suggested"], str(self.base / "my-job-search"))
        self.assertEqual(info["code_folder"], str(self.code))
        with mock.patch.object(store, "NEEDS_SETUP", False):
            self.assertIsNone(server.setup_info())

    def test_makes_a_blank_workspace_beside_the_code_folder_and_points_at_it(self):
        status, said = self.post({"folder": "../mine", "name": "Sam Doe", "start": "blank", "git": False})
        mine = (self.base / "mine").resolve()
        self.assertEqual(status, 200, said)
        self.assertEqual(said["folder"], str(mine))
        # A plain server can't restart itself, so the page is told to restart it.
        self.assertFalse(said["restarting"])
        self.assertTrue((mine / "profile" / "search.toml").is_file())
        self.assertNotIn("Alex Rivera", (mine / "profile" / "facts.md").read_text(encoding="utf-8"))
        self.assertEqual(self.pointer.read_text(encoding="utf-8").strip(), str(mine))
        self.assertTrue(workspace.setting_up(mine))
        self.assertTrue(any("Made a workspace" in line for line in said["told"]))

    def test_the_example_start_copies_the_example(self):
        status, said = self.post({"folder": str(self.base / "mine"), "name": "Sam Doe", "start": "example"})
        self.assertEqual(status, 200, said)
        self.assertIn("Sam Doe", (self.base / "mine" / "profile" / "resume.md").read_text(encoding="utf-8"))

    def test_what_init_refuses_is_refused_and_nothing_is_made(self):
        for body, says in (
            ({"folder": "inside", "name": "Sam Doe", "start": "blank"}, "inside this repository"),
            ({"folder": "../mine", "name": "Your Name", "start": "blank"}, "placeholder"),
            ({"folder": "../mine", "name": " ", "start": "blank"}, "Give your name"),
            ({"folder": "", "name": "Sam Doe", "start": "blank"}, "which folder"),
            ({"folder": "../mine", "name": "Sam Doe", "start": "copy"}, "blank files or from the example"),
            ({"folder": "../mine", "name": "Sam Doe", "start": "blank", "git": "yes"}, "blank files or from the example"),
            ({"folder": "../mi\nne", "name": "Sam Doe", "start": "blank"}, "line breaks"),
            ({"folder": ["../mine"], "name": "Sam Doe", "start": "blank"}, "which folder"),
        ):
            with self.subTest(body):
                status, said = self.post(body)
                self.assertEqual(status, 400)
                self.assertIn(says, said["error"])
        self.assertFalse((self.base / "mine").exists())
        self.assertFalse((self.code / "inside").exists())
        self.assertFalse(self.pointer.exists())

    def test_once_a_workspace_is_named_setup_makes_nothing(self):
        with mock.patch.object(store, "NEEDS_SETUP", False):
            status, said = self.post({"folder": "../mine", "name": "Sam Doe", "start": "blank"})
        self.assertEqual(status, 400)
        self.assertIn("already has a workspace", said["error"])
        self.assertFalse((self.base / "mine").exists())

    def test_a_page_from_elsewhere_cant_make_one(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/setup", method="POST",
                                         headers={"Content-Type": "application/json", "Origin": "https://evil.test"},
                                         data=b'{"folder": "../mine", "name": "Sam Doe", "start": "blank"}')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        caught.exception.close()
        self.assertEqual(caught.exception.code, 403)
        self.assertFalse((self.base / "mine").exists())


class NoCodesWhileSettingUp(unittest.TestCase):
    """A new workspace has nothing of the person's in it yet to loosen, so its changes need no code until it's set up."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(store.EXAMPLE_ROOT / "profile", self.root / "profile")
        self.sent: list[str] = []
        for patcher in (
            mock.patch.object(store, "ROOT", self.root),
            mock.patch.object(store, "IS_EXAMPLE", False),
            mock.patch.object(store, "CONFIG_PATH", self.root / "profile" / "search.toml"),
            mock.patch.object(notify, "send", lambda title, body: self.sent.append(body) or True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        confirm._pending = None
        confirm._asked.clear()
        self.addCleanup(confirm._asked.clear)
        terms = profile.read("terms")
        self.change, self.current = {"terms": terms + "Kubernetes\n"}, {"terms": terms}
        self.based_on = {"terms": profile.version(terms)}

    def test_an_existing_workspace_needs_a_code_to_approve_a_term(self):
        self.assertFalse(workspace.setting_up())
        with self.assertRaises(confirm.CodeNeeded):
            confirm.require(self.change, self.current, self.based_on)
        self.assertEqual(len(self.sent), 1)

    def test_a_new_one_needs_none_and_the_preview_asks_for_none(self):
        workspace._start_setup(self.root)
        self.assertTrue(workspace.setting_up())
        confirm.require(self.change, self.current, self.based_on)
        self.assertEqual(self.sent, [])
        drafted = steps.draft("skills", {"add": ["Kubernetes"]}, profile.versions())
        self.assertEqual(drafted["code"], [])

    def test_whats_never_changed_from_the_dashboard_still_isnt(self):
        workspace._start_setup(self.root)
        config = profile.read("config")
        changed = config.replace("allowed_hosts = ['workstation', 'workstation.example-tailnet.ts.net']",
                                 "allowed_hosts = ['tower']")
        self.assertNotEqual(changed, config)
        with self.assertRaises(ValueError) as caught:
            confirm.require({"config": changed}, {"config": config}, {})
        self.assertIn("only be changed in the file", str(caught.exception))

    def test_the_demo_is_never_setting_up(self):
        workspace._start_setup(self.root)
        with mock.patch.object(store, "IS_EXAMPLE", True):
            self.assertFalse(workspace.setting_up())

    def test_setup_ends_for_good_once_every_required_section_is_set(self):
        workspace._start_setup(self.root)
        with mock.patch.object(profile, "needs", return_value=[]):
            unfinished = {step["id"]: (step["id"] != "roles", "") for step in profile.STEPS}
            with mock.patch.object(profile, "_summaries", return_value=unfinished):
                found = profile.view()
            self.assertTrue(found["setting_up"])
            self.assertTrue(any("need no code" in need["title"] for need in found["needs"]))
            self.assertTrue(workspace.setting_up())
            finished = {step["id"]: (True, "") for step in profile.STEPS}
            with mock.patch.object(profile, "_summaries", return_value=finished):
                found = profile.view()
        self.assertFalse(found["setting_up"])
        self.assertFalse(workspace.setting_up())
        self.assertFalse((self.root / workspace.SETTING_UP).exists())
        # Emptying a section afterwards doesn't start it again, so it can't be used to get round a code.
        with mock.patch.object(profile, "needs", return_value=[]), mock.patch.object(profile, "_summaries", return_value=unfinished):
            self.assertFalse(profile.view()["setting_up"])
        with self.assertRaises(confirm.CodeNeeded):
            confirm.require(self.change, self.current, self.based_on)

    def test_init_starts_a_workspace_in_setup(self):
        folder = self.root / "made"
        with mock.patch.object(store, "HOME_POINTER", self.root / "pointer"), mock.patch.dict(os.environ, {"PYRITE_HOME": ""}):
            workspace.create(str(folder), "Sam Doe", blank=True)
        self.assertTrue(workspace.setting_up(folder))


if __name__ == "__main__":
    unittest.main()
