"""Confirming with a code: what counts as loosening the fact check, the code's rules, the notification that carries it,
and the dashboard's saves that ask for it."""
import contextlib
import io
import json
import re
import shutil
import tempfile
import threading
import tomllib
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import cli, confirm, notify, profile, server, store, tomledit

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"


class Workspace(unittest.TestCase):
    """A fresh copy of the example's profile, with notifications caught instead of shown."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        self.sent: list[str] = []
        self.delivered = True

        def fake_send(title, body):
            self.sent.append(body)
            return self.delivered

        for patcher in (
            mock.patch.object(store, "ROOT", self.root),
            mock.patch.object(store, "IS_EXAMPLE", False),
            mock.patch.object(store, "CONFIG_PATH", self.root / "profile" / "search.toml"),
            mock.patch.object(notify, "send", fake_send),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        confirm._pending = None
        confirm._asked.clear()
        self.addCleanup(confirm._asked.clear)

    def code(self) -> str:
        """The code from the last notification."""
        return self.sent[-1][:7].replace(" ", "")

    def config_with(self, table, key, value, literal=True):
        return tomledit.set_value(profile.read("config"), table, key, value, literal=literal)


class Loosening(Workspace):
    def test_approving_a_term_loosens_and_removing_one_doesnt(self):
        terms = profile.read("terms")
        self.assertEqual(confirm.loosening("terms", terms, terms + "Kubernetes\n"), ["approve “Kubernetes” for every draft"])
        without = re.sub(r"(?m)^FreeRTOS\r?\n", "", terms)
        self.assertNotEqual(without, terms)
        self.assertEqual(confirm.loosening("terms", terms, without), [])
        self.assertEqual(confirm.loosening("terms", terms, terms + "# just a comment\n"), [])
        # Several terms to a line: only the new word is named.
        self.assertEqual(confirm.loosening("terms", "Git GitHub\n", "Git GitHub, Rust\n"), ["approve “Rust” for every draft"])
        self.assertEqual(confirm.loosening("terms", "Git GitHub\n", "GitHub\nGit\n"), [])

    def test_taking_an_item_off_do_not_use_loosens_and_other_edits_dont(self):
        # A Windows checkout has CRLF line endings, so both kinds are checked whatever this one has.
        lf = profile.read("facts").replace("\r\n", "\n")
        for eol in ("\n", "\r\n"):
            facts = lf.replace("\n", eol)
            self.assertEqual(confirm.loosening("facts", facts, facts.replace(f"- Customer names{eol}", "")),
                             ["take “Customer names” off “Do not use” in facts.md"], repr(eol))
            added = facts.replace(f"## Do not use{eol}", f"## Do not use{eol}- Project X{eol}")
            self.assertEqual(confirm.loosening("facts", facts, added), [], repr(eol))
            self.assertEqual(confirm.loosening("facts", facts, facts.replace("Hired 4 engineers", "Hired 5 engineers")), [])

    def test_the_guard_settings_that_loosen(self):
        config = profile.read("config")
        guard = tomllib.loads(config)["guard"]
        cases = [
            ("forbidden", [p for p in guard["forbidden"] if p != "Bluebird"], "unblock the never mention pattern “Bluebird”"),
            ("forbidden", ["Bluebyrd" if p == "Bluebird" else p for p in guard["forbidden"]], "unblock the never mention pattern “Bluebird”"),
            ("unsupported", guard["unsupported"][1:], "unblock the haven't done pattern “ISO 26262”"),
            ("disclaimers", [*guard["disclaimers"], "\\bformerly\\b"], "excuse a claim"),
            ("approved_sources", [*guard["approved_sources"], "profile/anything.md"], "trust “profile/anything.md”"),
            ("heading_source", "profile/other.md", "match every draft's headings"),
            ("ordinary_words", [*guard["ordinary_words"], "kubernetes"], "stop questioning the word “kubernetes”"),
            ("max_resume_pages", 3, "allow a resume of 3 pages"),
        ]
        for key, value, phrase in cases:
            found = confirm.loosening("config", config, self.config_with("guard", key, value))
            self.assertTrue(any(phrase in f for f in found), (key, found))
        for key, value in (("forbidden", [*guard["forbidden"], "Nimbus"]), ("unsupported", [*guard["unsupported"], "SLAM"]),
                           ("max_resume_pages", 1)):
            self.assertEqual(confirm.loosening("config", config, self.config_with("guard", key, value)), [], key)
        self.assertEqual(confirm.loosening("config", config, self.config_with("workday", "autofill", True)), ["turn on Workday autofill"])
        on = self.config_with("workday", "autofill", True)
        self.assertEqual(confirm.loosening("config", on, config), [])

    def test_allowed_hosts_can_only_be_changed_in_the_file(self):
        config = profile.read("config")
        changed = self.config_with("dashboard", "allowed_hosts", ["tower"])
        self.assertIn("only be changed in the file", confirm.file_only("config", config, changed))
        with self.assertRaises(ValueError):
            confirm.require({"config": changed}, {"config": config}, {})
        self.assertEqual(self.sent, [])


class Codes(Workspace):
    def setUp(self):
        super().setUp()
        self.terms = profile.read("terms")
        self.change = {"terms": self.terms + "Kubernetes\n"}
        self.current = {"terms": self.terms}
        self.based_on = {"terms": profile.version(self.terms)}

    def ask(self, change=None) -> str:
        with self.assertRaises(confirm.CodeNeeded) as caught:
            confirm.require(change or self.change, self.current, self.based_on)
        return caught.exception.payload["request_id"]

    def test_a_change_that_loosens_nothing_needs_no_code(self):
        without = re.sub(r"(?m)^Git\r?\n", "", self.terms)
        self.assertNotEqual(without, self.terms)
        confirm.require({"terms": without}, self.current, self.based_on)
        self.assertEqual(self.sent, [])

    def test_the_notification_names_the_change_and_the_right_code_works_once(self):
        request_id = self.ask()
        self.assertRegex(self.sent[0], r"^\d{3} \d{3}  This code will approve “Kubernetes” for every draft\. It expires in 2 minutes")
        self.assertEqual(confirm.waiting()["code"], self.code())
        confirm.require(self.change, self.current, self.based_on, request_id, self.code())
        self.assertIsNone(confirm.waiting())
        with self.assertRaises(confirm.CodeError):
            confirm.require(self.change, self.current, self.based_on, request_id, self.code())

    def test_spaces_in_a_typed_code_dont_matter(self):
        request_id = self.ask()
        confirm.require(self.change, self.current, self.based_on, request_id, f" {self.code()[:3]} {self.code()[3:]} ")

    def test_wrong_codes_count_down_and_the_fifth_ends_it(self):
        request_id = self.ask()
        wrong = "000000" if self.code() != "000000" else "111111"
        for left in (4, 3, 2, 1):
            with self.assertRaisesRegex(confirm.CodeError, f"{left} tr"):
                confirm.require(self.change, self.current, self.based_on, request_id, wrong)
        with self.assertRaisesRegex(confirm.CodeError, "Too many wrong codes"):
            confirm.require(self.change, self.current, self.based_on, request_id, wrong)
        with self.assertRaises(confirm.CodeError):
            confirm.require(self.change, self.current, self.based_on, request_id, self.code())

    def test_a_code_expires(self):
        request_id = self.ask()
        later = confirm.time.time() + confirm.LIFETIME_SECONDS + 1
        with mock.patch.object(confirm.time, "time", return_value=later), self.assertRaisesRegex(confirm.CodeError, "expired"):
            confirm.require(self.change, self.current, self.based_on, request_id, self.code())

    def test_a_code_only_confirms_the_change_it_was_sent_for(self):
        request_id = self.ask()
        other = {"terms": self.terms + "Rust\n"}
        with self.assertRaisesRegex(confirm.CodeError, "different change"):
            confirm.require(other, self.current, self.based_on, request_id, self.code())
        # It's spent, so it can't be used for the first change either.
        with self.assertRaises(confirm.CodeError):
            confirm.require(self.change, self.current, self.based_on, request_id, self.code())

    def test_a_new_code_replaces_the_old_one(self):
        first_id = self.ask()
        first_code = self.code()
        second = confirm.resend(first_id)
        self.assertNotEqual(second["request_id"], first_id)
        with self.assertRaises(confirm.CodeError):
            confirm.require(self.change, self.current, self.based_on, first_id, first_code)
        confirm.require(self.change, self.current, self.based_on, second["request_id"], self.code())

    def test_cancelling_ends_the_code(self):
        request_id = self.ask()
        confirm.cancel(request_id)
        self.assertIsNone(confirm.waiting())
        with self.assertRaises(confirm.CodeError):
            confirm.require(self.change, self.current, self.based_on, request_id, self.code())

    def test_too_many_requests_are_refused(self):
        for _ in range(confirm.REQUESTS_PER_WINDOW):
            self.ask()
        with self.assertRaisesRegex(confirm.CodeError, "Too many codes"):
            confirm.require(self.change, self.current, self.based_on)
        self.assertEqual(len(self.sent), confirm.REQUESTS_PER_WINDOW)

    def test_a_failed_notification_says_so_and_pyrite_code_still_shows_it(self):
        self.delivered = False
        with self.assertRaises(confirm.CodeNeeded) as caught:
            confirm.require(self.change, self.current, self.based_on)
        self.assertFalse(caught.exception.payload["sent"])
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["code"])
        self.assertIn(f"{self.code()[:3]} {self.code()[3:]}", out.getvalue())
        self.assertIn("approve “Kubernetes”", out.getvalue())

    def test_pyrite_code_with_nothing_waiting(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cli.main(["code"])
        self.assertIn("No code is waiting", out.getvalue())


class Notification(unittest.TestCase):
    BODY = "-rf $(whoami) `calc` '; Remove-Item C:\\ \"<toast>"

    def test_on_windows_the_text_travels_in_the_environment_not_the_command(self):
        with mock.patch.object(notify.sys, "platform", "win32"), mock.patch.object(notify.shutil, "which", return_value="powershell.exe"):
            command, env = notify._command("Pyrite", self.BODY)
        self.assertNotIn(self.BODY, " ".join(command))
        self.assertEqual(env["PYRITE_NOTIFY_BODY"], self.BODY)
        self.assertIn("-EncodedCommand", command)

    def test_elsewhere_the_text_is_an_argument_after_the_options_end(self):
        with mock.patch.object(notify.sys, "platform", "linux"), mock.patch.object(notify.shutil, "which", return_value="/usr/bin/notify-send"):
            command, _ = notify._command("Pyrite", self.BODY)
        self.assertEqual(command[-3:], ["--", "Pyrite", self.BODY])
        with mock.patch.object(notify.sys, "platform", "darwin"), mock.patch.object(notify.shutil, "which", return_value="/usr/bin/osascript"):
            command, _ = notify._command("Pyrite", self.BODY)
        self.assertEqual(command[-2:], ["Pyrite", self.BODY])

    def test_with_no_way_to_notify_it_reports_false(self):
        with mock.patch.object(notify.shutil, "which", return_value=None):
            self.assertFalse(notify.send("Pyrite", "x"))
        with mock.patch.object(notify.shutil, "which", return_value="x"), \
                mock.patch.object(notify.subprocess, "run", side_effect=OSError("gone")):
            self.assertFalse(notify.send("Pyrite", "x"))


class OverHttp(Workspace):
    def setUp(self):
        super().setUp()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, path, body=None):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def test_approving_a_term_on_the_profile_tab_waits_for_the_code(self):
        status, view = self.call("/api/profile")
        self.assertEqual(status, 200)
        body = {"changes": {"terms": profile.read("terms") + "Kubernetes\n"}, "based_on": view["versions"], "reason": "Approve"}
        status, data = self.call("/api/profile", body)
        self.assertEqual((status, data["changes"]), (428, ["approve “Kubernetes” for every draft"]))
        self.assertNotIn("Kubernetes", profile.read("terms"))
        status, data = self.call("/api/profile", {**body, "request_id": data["request_id"], "code": "not it"})
        self.assertEqual((status, data.get("code_failed")), (403, True))
        status, data = self.call("/api/profile", {**body, "request_id": confirm._pending["id"], "code": self.code()})
        self.assertEqual(status, 200)
        self.assertIn("Kubernetes", data["terms"])
        self.assertEqual(data["history"][0]["reason"], "Approve")

    def test_a_tightening_save_goes_straight_through(self):
        view = self.call("/api/profile")[1]
        config = self.config_with("guard", "forbidden", [*view["off_limits"]["forbidden"], "Nimbus"])
        status, data = self.call("/api/profile", {"changes": {"config": config}, "based_on": view["versions"]})
        self.assertEqual(status, 200)
        self.assertIn("Nimbus", data["off_limits"]["forbidden"])
        self.assertEqual(self.sent, [])

    def test_the_facts_tab_asks_for_a_code_too(self):
        facts = self.call("/api/facts")[1]
        terms = next(f for f in facts["files"] if f["key"] == "terms")
        body = {"file": "terms", "version": terms["version"], "text": terms["text"] + "Kubernetes\n"}
        status, data = self.call("/api/facts", body)
        self.assertEqual(status, 428)
        status, _ = self.call("/api/facts", {**body, "request_id": data["request_id"], "code": self.code()})
        self.assertEqual(status, 200)
        self.assertIn("Kubernetes", profile.read("terms"))

    def test_allowed_hosts_and_unknown_files_are_refused(self):
        view = self.call("/api/profile")[1]
        config = self.config_with("dashboard", "allowed_hosts", ["tower"])
        status, data = self.call("/api/profile", {"changes": {"config": config}, "based_on": view["versions"]})
        self.assertEqual(status, 400)
        self.assertIn("only be changed in the file", data["error"])
        status, _ = self.call("/api/profile", {"changes": {"../secrets": "x"}, "based_on": view["versions"]})
        self.assertEqual(status, 400)
        self.assertEqual(self.sent, [])

    def test_a_stale_form_is_refused_before_any_code_is_sent(self):
        view = self.call("/api/profile")[1]
        (self.root / "profile" / "approved-terms.txt").write_bytes(b"Changed elsewhere\n")
        body = {"changes": {"terms": "Changed elsewhere\nKubernetes\n"}, "based_on": view["versions"]}
        self.assertEqual(self.call("/api/profile", body)[0], 409)
        facts = self.call("/api/facts")[1]
        terms = next(f for f in facts["files"] if f["key"] == "terms")
        stale = {"file": "terms", "version": "old", "text": terms["text"] + "Rust\n"}
        self.assertEqual(self.call("/api/facts", stale)[0], 409)
        self.assertEqual(self.sent, [])

    def test_a_waiting_code_can_be_sent_again_or_cancelled(self):
        view = self.call("/api/profile")[1]
        body = {"changes": {"terms": profile.read("terms") + "Rust\n"}, "based_on": view["versions"]}
        first = self.call("/api/profile", body)[1]
        status, second = self.call("/api/profile/code", {"action": "resend", "request_id": first["request_id"]})
        self.assertEqual((status, len(self.sent)), (200, 2))
        self.assertEqual(self.call("/api/profile/code", {"action": "cancel", "request_id": second["request_id"]})[0], 200)
        status, data = self.call("/api/profile", {**body, "request_id": second["request_id"], "code": self.code()})
        self.assertEqual((status, data.get("code_failed")), (403, True))


if __name__ == "__main__":
    unittest.main()
