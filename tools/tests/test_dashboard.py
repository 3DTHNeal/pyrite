"""The dashboard server: its defenses, the job lifecycle it drives, and the demo."""
import contextlib
import io
import json
import shutil
import threading
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from support import CFG, MODEL, Base

from pyrite import checks, claude_code, cli, demo, refresh, server, store


class Lifecycle(Base):
    def test_applied_sets_follow_up_and_reply_clears_it(self):
        job = self.add()
        store.set_status(self.conn, job, "applied", follow_up_days=7)
        row = store.get_job(self.conn, job)
        self.assertTrue(row["applied_at"])
        self.assertEqual(row["next_action"], "Follow up")
        self.assertEqual(row["next_action_date"], store.today_plus(7))
        store.set_status(self.conn, job, "responded")
        row = store.get_job(self.conn, job)
        self.assertTrue(row["response_at"])
        self.assertEqual(row["next_action"], "")

    def test_rejection_counts_as_hearing_back_only_if_applied(self):
        job = self.add()
        store.set_status(self.conn, job, "applied")
        store.set_status(self.conn, job, "rejected")
        self.assertTrue(store.get_job(self.conn, job)["response_at"])
        other = self.add(source_id="2")
        store.set_status(self.conn, other, "rejected")
        self.assertIsNone(store.get_job(self.conn, other)["response_at"])

    def test_first_applied_date_survives_reopen(self):
        job = self.add()
        store.set_status(self.conn, job, "applied")
        first = store.get_job(self.conn, job)["applied_at"]
        self.conn.execute("UPDATE jobs SET applied_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (job,))
        store.set_status(self.conn, job, "applied")
        self.assertEqual(store.get_job(self.conn, job)["applied_at"], "2026-01-01T00:00:00+00:00")
        self.assertNotEqual(first, "2026-01-01T00:00:00+00:00")

    def test_unknown_status_refused(self):
        with self.assertRaises(ValueError):
            store.set_status(self.conn, self.add(), "hired?")


class Dashboard(Base):
    def test_numbers_and_orders_put_new_listings_first(self):
        today = date.today()
        posted = lambda days: (today - timedelta(days=days)).isoformat()
        self.add(source_id="old", title="Old", score=95, posted_at=posted(200))
        self.add(source_id="new", title="New", score=60, posted_at=posted(1))
        self.add(source_id="back", title="Back", score=70, posted_at=posted(2), reposts=1)
        state = server.build_state(self.conn, CFG)
        self.assertEqual((state["stats"]["to_triage"], state["stats"]["fresh"], state["stats"]["possible_ghosts"]), (3, 1, 1))
        self.assertEqual([o["text"] for o in state["orders"] if o["kind"] == "New listing"], ["Acme: New"])
        self.assertEqual(sorted((j["title"] for j in state["jobs"]), key=lambda t: -next(j["rank"] for j in state["jobs"] if j["title"] == t)), ["New", "Back", "Old"])

    def test_adding_a_link_already_tracked_opens_that_job_instead(self):
        # Added again, it would go to the front of the next run and be tailored a second time.
        sent = self.add(source_id="r1", title="Firmware Lead", status="applied", url="https://jobs.example.com/acme/R-100")
        for url in ("https://jobs.example.com/acme/R-100", "https://JOBS.example.com/acme/R-100/", "https://jobs.example.com/acme/R-100#apply"):
            with self.subTest(url):
                self.assertEqual(server.tracked_by_url(self.conn, url)["id"], sent)
                self.assertEqual(server.add_manual_job(self.conn, CFG, "Acme", "Firmware Lead", url), sent)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)
        # Another posting with the same title, or no link at all, is still added.
        self.assertIsNone(server.tracked_by_url(self.conn, "https://jobs.example.com/acme/R-200"))
        self.assertNotEqual(server.add_manual_job(self.conn, CFG, "Acme", "Firmware Lead", "https://jobs.example.com/acme/R-200"), sent)
        self.assertIsNone(server.tracked_by_url(self.conn, ""))


class Outreach(Base):
    """Reaching out after applying: logged as an event, due on the to-do list a day or so in, and the follow-up keyed to it."""

    def applied(self, days_ago: int, **kw) -> int:
        job = self.add(**kw)
        store.set_status(self.conn, job, "applied", follow_up_days=7)
        when = (datetime.now(UTC) - timedelta(days=days_ago, hours=1)).isoformat(timespec="seconds")
        self.conn.execute("UPDATE jobs SET applied_at = ?, next_action_date = ? WHERE id = ?",
                          (when, (date.today() - timedelta(days=days_ago) + timedelta(days=7)).isoformat(), job))
        return job

    def reach_out_orders(self):
        return [o["job_id"] for o in server.build_state(self.conn, CFG)["orders"] if o["kind"] == "Reach out"]

    def test_due_a_day_or_so_after_applying_until_logged(self):
        young, due, late = self.applied(0, source_id="a"), self.applied(2, source_id="b"), self.applied(5, source_id="c")
        self.assertEqual(self.reach_out_orders(), [due])
        server.apply_action(self.conn, due, {"action": "reached_out", "to": "the hiring manager", "note": "Asked about the team"}, CFG)
        self.assertEqual(self.reach_out_orders(), [])
        self.assertNotIn(young, self.reach_out_orders())
        self.assertNotIn(late, self.reach_out_orders())

    def test_logged_in_the_timeline_and_follow_up_moves_to_a_week_after_it(self):
        job = self.applied(2)
        yesterday = date.today() - timedelta(days=1)
        server.apply_action(self.conn, job, {"action": "reached_out", "date": yesterday.isoformat(), "to": " the  hiring manager "}, CFG)
        self.assertEqual(store.get_job(self.conn, job)["next_action_date"], (yesterday + timedelta(days=7)).isoformat())
        detail = server.job_detail(self.conn, job, CFG)
        self.assertTrue(detail["reached_out"] and detail["can_reach_out"])
        self.assertEqual(detail["events"][0], {**detail["events"][0], "kind": "reached_out",
                                               "detail": f"On {yesterday:%b} {yesterday.day}, to the hiring manager."})
        self.assertEqual(store.get_job(self.conn, job)["status"], "applied")

    def test_outreach_before_applying_leaves_the_follow_up_on_the_application(self):
        job = self.applied(1)
        before = store.get_job(self.conn, job)["next_action_date"]
        store.log_outreach(self.conn, job, (date.today() - timedelta(days=3)).isoformat(), "a referral")
        self.assertEqual(store.get_job(self.conn, job)["next_action_date"], before)

    def test_a_next_step_of_your_own_is_left_alone(self):
        job = self.applied(2)
        server.apply_action(self.conn, job, {"action": "next_action", "text": "Phone screen", "date": "2030-01-02"}, CFG)
        server.apply_action(self.conn, job, {"action": "reached_out"}, CFG)
        self.assertEqual(store.get_job(self.conn, job)["next_action_date"], "2030-01-02")

    def test_refused_before_applying_on_a_closed_job_or_a_day_to_come(self):
        prospect = self.add(source_id="p")
        self.assertFalse(server.job_detail(self.conn, prospect, CFG)["can_reach_out"])
        closed = self.applied(2, source_id="r")
        store.set_status(self.conn, closed, "rejected")
        job = self.applied(2, source_id="j")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        for target, day in ((prospect, ""), (closed, ""), (job, tomorrow), (job, "next week")):
            with self.subTest(target=target, day=day), self.assertRaises(ValueError):
                server.apply_action(self.conn, target, {"action": "reached_out", "date": day}, CFG)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'reached_out'").fetchone()[0], 0)


class Security(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, path, method="GET", headers=None, body=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(request, timeout=5) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.read(), dict(err.headers)

    def test_foreign_host_refused(self):
        self.assertEqual(self.call("/api/state", headers={"Host": "evil.test"})[0], 403)

    def test_private_tailscale_name_allowed_but_lookalikes_refused(self):
        self.assertEqual(self.call("/api/state", headers={"Host": "workstation.example-tailnet.ts.net:8787"})[0], 200)
        for host in ("workstation.evil.test", "workstation.example-tailnet.ts.net.evil.test", "evil.ts.net"):
            with self.subTest(host):
                self.assertEqual(self.call("/api/state", headers={"Host": host})[0], 403)

    def test_foreign_origin_refused(self):
        status, _, _ = self.call("/api/job/1/action", "POST", {"Origin": "https://evil.test", "Content-Type": "application/json"}, b'{"action":"note"}')
        self.assertEqual(status, 403)

    def test_a_negative_length_is_refused_rather_than_waited_on(self):
        status, body, _ = self.call("/api/jobs", "POST", {"Content-Type": "application/json", "Content-Length": "-1"}, b"{}")
        self.assertEqual((status, json.loads(body)["error"]), (400, "bad request"))

    def test_form_posts_refused(self):
        status, _, _ = self.call("/api/jobs", "POST", {"Content-Type": "text/plain"}, b"{}")
        self.assertEqual(status, 415)

    def test_files_stay_inside_allowed_folders(self):
        for path in ("/files/../data/pyrite.db", "/files/..%2f..%2f..%2fetc%2fpasswd", "/files/profile/facts.md",
                     "/files/applications/../profile/facts.md", "/files/data/pyrite.db", "/files/tools/pyrite.py"):
            with self.subTest(path):
                self.assertEqual(self.call(path)[0], 404)

    def test_files_are_served_however_the_workspace_path_was_spelled(self):
        # Windows can name the same folder by a short name such as RUNNER~1, and resolving a path expands it.
        # A ".." does the same on any system: the workspace is the same folder, written differently.
        notes = "applications/2026-11-acme-principal-robotics-software-engineer/notes.md"
        spelled_differently = store.ROOT / "applications" / ".."
        with mock.patch.object(server, "ROOT", spelled_differently):
            self.assertEqual(server.resolve_file(notes), (store.ROOT / notes).resolve())
            self.assertIsNone(server.resolve_file("profile/facts.md"))
            self.assertIsNone(server.resolve_file("applications/../profile/facts.md"))

    def test_document_served_with_protective_headers(self):
        status, _, headers = self.call("/files/applications/2026-11-acme-principal-robotics-software-engineer/notes.md")
        self.assertEqual(status, 200)
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_page_forbids_inline_script(self):
        _, _, headers = self.call("/")
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline'; connect", headers["Content-Security-Policy"].split("script-src")[1].split(";")[0])

    def test_javascript_url_dropped(self):
        self.assertEqual(server.safe_url("javascript:alert(1)"), "")
        self.assertEqual(server.safe_url("https://x.test/a"), "https://x.test/a")

    # Every request gets an answer the page can show, even when something is broken.

    def post(self, path, body):
        return self.call(path, "POST", {"Content-Type": "application/json"}, body)

    def test_a_body_that_is_not_an_object_is_refused(self):
        status, body, _ = self.post("/api/jobs", b"[1]")
        self.assertEqual((status, json.loads(body)["error"]), (400, "bad request"))

    def test_a_broken_search_file_is_reported_to_the_page(self):
        text = store.CONFIG_PATH.read_text(encoding="utf-8")
        try:
            store.CONFIG_PATH.write_text(text + "\n[broken\n", encoding="utf-8")
            status, body, _ = self.call("/api/state")
        finally:
            store.CONFIG_PATH.write_text(text, encoding="utf-8")
        self.assertEqual(status, 500)
        self.assertIn("search.toml", json.loads(body)["error"])
        self.assertEqual(self.call("/api/state")[0], 200)

    def test_a_busy_database_and_an_unexpected_error_are_reported(self):
        with mock.patch.object(server, "build_state", side_effect=server.sqlite3.OperationalError("database is locked")):
            status, body, _ = self.call("/api/state")
        self.assertEqual(status, 503)
        self.assertIn("busy", json.loads(body)["error"])
        with mock.patch.object(server, "build_state", side_effect=RuntimeError("boom")), contextlib.redirect_stderr(io.StringIO()):
            status, body, _ = self.call("/api/state")
        self.assertEqual(status, 500)
        self.assertIn("boom", json.loads(body)["error"])

    def test_a_file_name_outside_latin_1_can_be_served(self):
        folder = store.ROOT / "applications" / "names"
        folder.mkdir(exist_ok=True)
        try:
            (folder / "李雷_Resume.md").write_text("x", encoding="utf-8")
            status, _, headers = self.call("/files/applications/names/" + urllib.request.quote("李雷_Resume.md"))
        finally:
            shutil.rmtree(folder, ignore_errors=True)
        self.assertEqual(status, 200)
        self.assertIn("filename*=UTF-8''%E6%9D%8E%E9%9B%B7_Resume.md", headers["Content-Disposition"])


class OpenedWithoutTheServer(unittest.TestCase):
    def test_template_says_where_the_dashboard_is_and_the_served_page_hides_it(self):
        static = Path(server.__file__).parent / "static"
        self.assertIn("http://127.0.0.1:8787", (static / "index.html").read_text(encoding="utf-8"))
        self.assertIn(".not-served { display: none; }", (static / "style.css").read_text(encoding="utf-8"))


class Demo(Base):
    def test_covers_every_column_with_nothing_real_needed(self):
        demo.load(self.conn, CFG)
        state = server.build_state(self.conn, CFG)
        statuses = {job["status"] for job in state["jobs"]}
        self.assertLessEqual({"new", "needs_fix", "ready", "applied", "responded", "interviewing", "rejected"}, statuses)
        self.assertTrue(state["briefing"])
        self.assertTrue(any(order["kind"] == "Possible reply" for order in state["orders"]))

    def test_blocked_draft_shows_the_real_checker_verdict(self):
        demo.load(self.conn, CFG)
        job = self.conn.execute("SELECT * FROM jobs WHERE company = 'Globex Automation'").fetchone()
        self.assertEqual(job["status"], "needs_fix")
        self.assertTrue(any("confidential term" in e for e in json.loads(job["check_result"])["errors"]))

    def test_loading_twice_replaces_rather_than_adds(self):
        demo.load(self.conn, CFG)
        first = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        demo.load(self.conn, CFG)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], first)

    def test_refresh_button_never_runs_claude_on_the_demo(self):
        demo.load(self.conn, CFG)
        job = self.conn.execute("SELECT * FROM jobs WHERE company = 'Globex Automation'").fetchone()
        with mock.patch.object(refresh, "IS_EXAMPLE", True), mock.patch.object(claude_code.subprocess, "Popen") as popen:
            with self.assertRaises(ValueError) as caught:
                refresh.start(self.conn, job["id"])
        self.assertIn("demo", str(caught.exception))
        popen.assert_not_called()

    def test_refuses_any_workspace_but_the_example(self):
        # This suite's workspace is a copy, so it stands in for someone's real data here.
        self.assertFalse(store.IS_EXAMPLE)
        with mock.patch.object(demo, "load") as load, self.assertRaises(SystemExit):
            cli.main(["demo"])
        load.assert_not_called()


class ReopenNeverSkipsTheAssay(Base):
    """Only the assay makes a draft ready. Reopening a closed job puts back what its last verdict supports, nothing more."""

    def job(self, check_result, **kw):
        rel = MODEL.relative_to(store.ROOT).as_posix()
        return self.add(app_folder=rel, ready_at=store.now(), status="closed",
                        check_result=json.dumps(check_result) if check_result is not None else "", **kw)

    def reopen(self, job):
        server.apply_action(self.conn, job, {"action": "reopen"}, CFG)
        return store.get_job(self.conn, job)["status"]

    def test_a_draft_that_passed_and_hasnt_changed_is_ready_again(self):
        self.assertEqual(self.reopen(self.job({"ok": True, "checked": checks.fingerprints(MODEL)})), "ready")

    def test_a_draft_that_last_failed_goes_back_to_needs_fix(self):
        self.assertEqual(self.reopen(self.job({"ok": False, "errors": ["Resume has numbers not in the fact bank: 137"]})), "needs_fix")

    def test_a_draft_changed_since_it_passed_goes_back_to_needs_fix(self):
        checked = {**checks.fingerprints(MODEL), "resume.md": "0" * 64}
        self.assertEqual(self.reopen(self.job({"ok": True, "checked": checked})), "needs_fix")

    def test_a_draft_passed_against_facts_since_changed_goes_back_to_needs_fix(self):
        passed = {"ok": True, "checked": checks.fingerprints(MODEL), "checked_sources": checks.source_fingerprints(CFG)}
        self.assertEqual(self.reopen(self.job(passed)), "ready")
        taken_back = {**passed, "checked_sources": {**passed["checked_sources"], "profile/facts.md": "0" * 64}}
        self.assertEqual(self.reopen(self.job(taken_back, source_id="4")), "needs_fix")
        stricter = {**passed, "checked_sources": {**passed["checked_sources"], checks.GUARD_KEY: "0" * 64}}
        self.assertEqual(self.reopen(self.job(stricter, source_id="5")), "needs_fix")

    def test_never_checked_is_shortlisted_and_sent_is_applied(self):
        self.assertEqual(self.reopen(self.job(None, source_id="2")), "shortlisted")
        self.assertEqual(self.reopen(self.job(None, source_id="3", applied_at=store.now())), "applied")


if __name__ == "__main__":
    unittest.main()
