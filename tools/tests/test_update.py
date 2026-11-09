"""Update available: telling that GitHub's main is ahead of this copy, the one-click update, and the restart after it."""
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from support import Base

from pyrite import launch, server, store, tasks, update


@unittest.skipUnless(shutil.which("git"), "needs git")
class Updating(unittest.TestCase):
    """A copy of Pyrite cloned from an "origin", and another clone standing in for whoever pushes to GitHub."""

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Sam Doe", "-c", "user.email=sam@example.com", *args],
                              capture_output=True, text=True, check=True).stdout.strip()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.origin, self.upstream, self.copy = root / "origin.git", root / "upstream", root / "copy"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.upstream)], check=True, capture_output=True)
        self.git(self.upstream, "symbolic-ref", "HEAD", "refs/heads/main")
        self.push("README.md", "Pyrite.\n", "Start")
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.copy)], check=True, capture_output=True)
        update.forget()
        self.addCleanup(update.forget)

    def push(self, name, text, subject):
        path = self.upstream / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.git(self.upstream, "add", name)
        self.git(self.upstream, "commit", "-q", "-m", subject)
        self.git(self.upstream, "push", "-q", "origin", "main")

    def check(self, **kw):
        return update.check(self.copy, fresh=True, **kw)

    def test_a_copy_matching_github_has_nothing_to_update(self):
        found = self.check()
        self.assertFalse(found["available"])
        self.assertEqual(found["behind"], 0)
        self.assertNotIn("error", found)

    def test_new_commits_on_github_are_counted_and_named(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        self.push("tools/b.py", "b = 1\n", "Add b")
        found = self.check()
        self.assertTrue(found["available"])
        self.assertEqual(found["behind"], 2)
        self.assertEqual(found["changes"], ["Add b", "Add a"])
        self.assertIsNone(found["why_not"])

    def test_the_update_fast_forwards_to_github(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        before = self.git(self.copy, "rev-parse", "--short", "HEAD")
        done = update.apply(self.copy)
        self.assertEqual(done["from"], before)
        self.assertEqual(self.git(self.copy, "rev-parse", "HEAD"), self.git(self.upstream, "rev-parse", "HEAD"))
        self.assertEqual((done["behind"], done["packages"]), (1, None))
        self.assertTrue((self.copy / "tools" / "a.py").exists())
        self.assertFalse(self.check()["available"])

    def test_changed_requirements_are_installed_with_the_python_running_pyrite(self):
        self.push(update.REQUIREMENTS, "requests\n", "Need requests")
        real, installs = update._run, []

        def run(command, cwd, seconds):
            if command[0] != "the-python":
                return real(command, cwd, seconds)
            installs.append(command)
            return subprocess.CompletedProcess(command, 0, "", "")

        with mock.patch.object(update, "_run", side_effect=run):
            done = update.apply(self.copy, python="the-python")
        self.assertEqual(installs, [["the-python", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                                     "-r", update.REQUIREMENTS]])
        self.assertIn("brought up to date", done["packages"])

    def test_a_failed_install_is_reported_rather_than_raised(self):
        failed = subprocess.CompletedProcess([], 1, "", "ERROR: No matching distribution found for requests")
        with mock.patch.object(update, "_run", return_value=failed):
            said = update._install(self.copy, "python")
        self.assertIn("failed: ERROR: No matching distribution", said)
        self.assertIn("pip install -r tools/requirements.txt", said)

    def assert_refused(self, words):
        head = self.git(self.copy, "rev-parse", "HEAD")
        self.assertIn(words, self.check()["why_not"])
        with self.assertRaises(ValueError) as caught:
            update.apply(self.copy)
        self.assertIn(words, str(caught.exception))
        self.assertEqual(self.git(self.copy, "rev-parse", "HEAD"), head)

    def test_a_copy_on_another_branch_is_left_alone(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        self.git(self.copy, "checkout", "-q", "-b", "my-change")
        self.assert_refused("on the branch my-change, not main")

    def test_edits_to_tracked_files_are_never_risked(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        (self.copy / "README.md").write_text("Mine.\n", encoding="utf-8")
        self.assert_refused("has edits of your own")
        self.assertEqual((self.copy / "README.md").read_text(encoding="utf-8"), "Mine.\n")

    def test_an_untracked_file_doesnt_stop_it(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        (self.copy / "notes.txt").write_text("Scratch.\n", encoding="utf-8")
        update.apply(self.copy)
        self.assertTrue((self.copy / "notes.txt").exists())

    def test_local_commits_github_lacks_are_left_for_git_pull(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        (self.copy / "mine.txt").write_text("Mine.\n", encoding="utf-8")
        self.git(self.copy, "add", "mine.txt")
        self.git(self.copy, "commit", "-q", "-m", "Mine")
        self.assert_refused("1 commit GitHub's doesn't")

    def test_the_demo_says_how_to_update_itself(self):
        self.push("tools/a.py", "a = 1\n", "Add a")
        self.assertIn("This is the demo", self.check(demo=True)["why_not"])

    def test_nothing_to_update_to_is_refused(self):
        with self.assertRaisesRegex(ValueError, "already up to date"):
            update.apply(self.copy)

    def test_github_is_asked_once_an_hour_at_most(self):
        with mock.patch.object(update, "_look", return_value={"available": False, "behind": 0}) as look:
            update.check(self.copy)
            update.check(self.copy)
            self.assertEqual(look.call_count, 1)
            update.check(self.copy, fresh=True)
            self.assertEqual(look.call_count, 2)

    def test_an_unreachable_github_is_an_error_not_a_crash(self):
        self.git(self.copy, "remote", "set-url", "origin", str(self.origin.parent / "gone.git"))
        found = self.check()
        self.assertFalse(found["available"])
        self.assertIn("Couldn't check GitHub", found["error"])

    def test_a_folder_that_isnt_a_clone_says_so(self):
        with tempfile.TemporaryDirectory() as folder:
            found = update.check(Path(folder), fresh=True)
        self.assertFalse(found["available"])
        self.assertIn("isn't a git clone", found["error"])


class Going(Base):
    def test_a_run_going_is_named_and_a_finished_one_isnt(self):
        self.assertIsNone(tasks.going(self.conn))
        task = tasks.begin(self.conn, tasks.SWEEP)
        self.assertEqual(tasks.going(self.conn), "pan")
        tasks._finish(self.conn, task, True, "Done")
        self.assertIsNone(tasks.going(self.conn))


class Endpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, body=None):
        headers = {"Content-Type": "application/json"} if body is not None else {}
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers,
                                         data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    BEHIND = {"available": True, "behind": 2, "changes": ["Add b", "Add a"], "current": "aaa", "latest": "bbb", "why_not": None}

    def test_the_page_hears_whether_an_update_is_waiting(self):
        with mock.patch.object(update, "check", return_value=dict(self.BEHIND)), \
                mock.patch.object(tasks, "going", return_value=None):
            status, found = self.call("/api/update")
        self.assertEqual((status, found["behind"], found["why_not"]), (200, 2, None))

    def test_check_updates_false_never_asks_github(self):
        cfg = {**store.load_config(), "dashboard": {"check_updates": False}}
        with mock.patch.object(update, "check") as check:
            self.assertEqual(server.update_state(cfg), {"available": False, "off": True})
        check.assert_not_called()

    def test_a_run_going_holds_the_update_back(self):
        with mock.patch.object(update, "check", return_value=dict(self.BEHIND)), \
                mock.patch.object(tasks, "going", return_value="Claude run"):
            _, found = self.call("/api/update")
            self.assertIn("A Claude run is going", found["why_not"])
            with mock.patch.object(update, "apply") as apply:
                status, said = self.call("/api/update", {})
            apply.assert_not_called()
        self.assertEqual(status, 400)
        self.assertIn("A Claude run is going", said["error"])

    def test_the_update_says_what_changed_and_a_refusal_says_why(self):
        done = {"from": "aaa", "to": "bbb", "behind": 2, "packages": None}
        with mock.patch.object(update, "apply", return_value=done):
            status, said = self.call("/api/update", {})
        # A plain server can't restart itself, so the page is told to restart it.
        self.assertEqual((status, said["to"], said["restarting"], said["server"]), (200, "bbb", False, server.SERVER_ID))
        with mock.patch.object(update, "apply", side_effect=ValueError("Pyrite is already up to date.")):
            self.assertEqual(self.call("/api/update", {}), (400, {"error": "Pyrite is already up to date."}))

    def test_alive_names_this_server(self):
        self.assertEqual(self.call("/api/alive"), (200, {"server": server.SERVER_ID}))


class Restart(unittest.TestCase):
    def test_the_dashboard_stops_serving_and_marks_itself_for_a_restart(self):
        httpd = server.make_server(0)
        serving = threading.Thread(target=httpd.serve_forever)
        serving.start()
        try:
            httpd.restart_soon()
            serving.join(timeout=5)
            self.assertFalse(serving.is_alive())
            self.assertTrue(httpd.restarting)
        finally:
            httpd.server_close()

    def test_serve_starts_a_new_dashboard_once_an_update_stopped_this_one(self):
        stopped = mock.Mock(restarting=True)
        with mock.patch.object(server, "make_server", return_value=stopped), \
                mock.patch.object(launch, "restart", return_value=True) as restart, \
                mock.patch("builtins.print"):
            server.serve(8790)
        stopped.server_close.assert_called_once()
        restart.assert_called_once_with(8790)

    def test_a_port_still_held_is_tried_again(self):
        gone, up = mock.Mock(), mock.Mock()
        gone.poll.return_value, up.poll.return_value = 1, None
        with mock.patch.object(launch, "start", side_effect=[gone, up]) as start, \
                mock.patch.object(launch, "answering", side_effect=[True]), \
                mock.patch.object(launch.time, "sleep"):
            self.assertTrue(launch.restart(8790))
        self.assertEqual(start.call_count, 2)


if __name__ == "__main__":
    unittest.main()
