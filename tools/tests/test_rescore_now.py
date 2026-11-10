"""Rescore now on the Profile tab, and the pan's own rescore once search.toml's filters change."""
import json
import sqlite3
import tempfile
import threading
import unittest
import unittest.mock as mock
import urllib.error
import urllib.request
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

from support import CFG, Base, Clock, stub_feed

from pyrite import backup, discover, score, server, sources, store

DESCRIPTION = "firmware embedded c++ python robot hardware"
# The same search with remote roles no longer counting, as a save in Where you'll work would leave it.
NO_REMOTE = {**CFG, "location": {**CFG["location"], "accept_remote": False}}


class RescoreNow(unittest.TestCase):
    """The button's endpoint, over HTTP as the page calls it, on a workspace of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / "data" / "pyrite.db"
        self.config = CFG
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "DB_PATH", self.db),
                        mock.patch.object(store, "IS_EXAMPLE", False),
                        mock.patch.object(server, "load_config", side_effect=lambda: self.config)):
            patcher.start()
            self.addCleanup(patcher.stop)
        with closing(store.connect()) as conn:
            ts = store.now()
            for sid, location, notes in (("1", "Madison, WI", None), ("2", "Remote - US", None), ("3", "Remote - US", "Asked a friend there")):
                conn.execute("INSERT INTO jobs (source_key, source_id, company, title, location, description, notes, first_seen, "
                             "last_seen, status, status_changed_at) VALUES ('greenhouse:acme', ?, 'Acme', 'Principal Firmware Engineer', "
                             "?, ?, ?, ?, ?, 'new', ?)", (sid, location, DESCRIPTION, notes, ts, ts, ts))
            conn.commit()
            # Scored with the search as it is, as a pan would have left them.
            discover.rescore(conn, CFG)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def call(self, method="GET", headers=None, body=None):
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/profile/rescore"
        request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            with err:
                return err.code, json.loads(err.read())

    def post(self, **headers):
        return self.call("POST", {"Content-Type": "application/json", **headers}, b"{}")

    def jobs(self, path=None) -> list[str]:
        with closing(sqlite3.connect(path or self.db)) as conn:
            return [row[0] for row in conn.execute("SELECT source_id FROM jobs ORDER BY source_id")]

    def copies(self) -> list[dict]:
        return backup.copies(self.root)

    def test_nothing_is_due_while_the_prospects_match_the_settings(self):
        status, state = self.call()
        self.assertEqual(status, 200)
        self.assertEqual(state["due"], {"total": 3, "changed": 0, "dropped": 0, "held": 0})
        self.assertEqual(state["why_not"], "")

    def test_it_backs_up_first_then_reports_what_the_rescore_did(self):
        self.config = NO_REMOTE
        status, state = self.call()
        self.assertEqual((status, state["due"]), (200, {"total": 3, "changed": 0, "dropped": 1, "held": 1}))
        self.assertEqual(self.copies(), [])

        returned, real = [], discover.rescore

        def rescore(*args, **kw):
            # The copy is already made by the time the rescore starts.
            self.assertEqual(len(self.copies()), 1)
            returned.append(real(*args, **kw))
            return returned[-1]

        with mock.patch.object(discover, "rescore", side_effect=rescore):
            status, done = self.post()
        self.assertEqual(status, 200, done)
        # The counts it reports are what `rescore` did, and what the database now holds.
        self.assertEqual({key: done[key] for key in ("kept", "dropped", "held", "removed")}, returned[0])
        self.assertEqual(returned[0], {"kept": 1, "dropped": 1, "held": 1, "removed": ["Acme: Principal Firmware Engineer (location)"]})
        self.assertEqual(self.jobs(), ["1", "3"])  # The untouched remote one went; the one with a note stayed.
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT source_id, reason FROM rejected").fetchall(), [("2", "location")])
        self.assertIn("dropped 1 that no longer pass", done["said"])
        # The copy was made before anything was dropped, so it still has all three.
        copies = self.copies()
        self.assertEqual(len(copies), 1)
        self.assertEqual(done["backup"]["name"], copies[0]["name"])
        self.assertEqual(done["backup"]["folder"], "data/backups")
        self.assertEqual(self.jobs(self.root / "data" / "backups" / copies[0]["name"]), ["1", "2", "3"])
        # And it's in step now, so the next pan has nothing to do.
        self.assertEqual(done["due"], {"total": 2, "changed": 0, "dropped": 0, "held": 1})
        with closing(store.connect()) as conn:
            self.assertIsNone(discover.rescore_if_outdated(conn, NO_REMOTE))

    def test_it_refuses_while_a_run_is_going_and_changes_nothing(self):
        self.config = NO_REMOTE
        with closing(store.connect()) as conn:
            ts = store.now()
            conn.execute("INSERT INTO tasks (kind, started_at, updated_at) VALUES ('claude', ?, ?)", (ts, ts))
            conn.commit()
        status, state = self.call()
        self.assertEqual(status, 200)
        self.assertIn("A Claude run is going", state["why_not"])
        status, done = self.post()
        self.assertEqual(status, 400)
        self.assertIn("A Claude run is going", done["error"])
        self.assertEqual((self.jobs(), self.copies()), (["1", "2", "3"], []))

    def test_a_pan_the_timer_started_counts_as_a_run_too(self):
        self.config = NO_REMOTE
        with closing(store.connect()) as conn:
            conn.execute("INSERT INTO runs (started_at) VALUES (?)", (store.now(),))
            conn.commit()
        status, done = self.post()
        self.assertEqual(status, 400)
        self.assertIn("A pan is going", done["error"])
        self.assertEqual((self.jobs(), self.copies()), (["1", "2", "3"], []))

    def test_the_demo_refuses(self):
        self.config = NO_REMOTE
        with mock.patch.object(store, "IS_EXAMPLE", True):
            self.assertIn("demo", self.call()[1]["why_not"])
            status, done = self.post()
        self.assertEqual(status, 400)
        self.assertIn("demo", done["error"])
        self.assertEqual((self.jobs(), self.copies()), (["1", "2", "3"], []))

    def test_other_sites_and_hosts_can_not_start_it(self):
        self.config = NO_REMOTE
        self.assertEqual(self.post(Origin="https://evil.test")[0], 403)
        self.assertEqual(self.post(Host="evil.test")[0], 403)
        self.assertEqual(self.call("POST", {"Content-Type": "text/plain"}, b"{}")[0], 415)
        self.assertEqual((self.jobs(), self.copies()), (["1", "2", "3"], []))


class PanRescoresAfterASettingsChange(Base):
    """The next pan rescores the prospects once the filters in search.toml have changed, as an update's scoring does."""

    def setUp(self):
        super().setUp()
        self.clock = Clock(self)
        saved = dict(sources.FEEDS)
        self.addCleanup(lambda: (sources.FEEDS.clear(), sources.FEEDS.update(saved)))
        self.watch = {"watch": {"greenhouse": {"acme": "Acme"}, "lever": {}, "ashby": {}, "workday": {}}}
        # Two jobs, not one posted in two places, which would be one job.
        stub_feed(None, [sources.Posting("greenhouse:acme", "1", "Acme", "Principal Firmware Engineer", "Madison, WI", "",
                                         "https://x.test/1", DESCRIPTION),
                         sources.Posting("greenhouse:acme", "2", "Acme", "Staff Embedded Engineer", "Remote - US", "",
                                         "https://x.test/2", "embedded c++ python robot firmware hardware two")])

    def sweep(self, cfg):
        self.clock.advance()
        return discover.run(conn=self.conn, cfg={**cfg, **self.watch})

    def test_a_change_to_the_filters_rescores_once(self):
        self.assertNotIn("rescored", self.sweep(CFG))
        self.assertNotIn("rescored", self.sweep(CFG))
        stats = self.sweep(NO_REMOTE)
        self.assertEqual({key: stats["rescored"][key] for key in ("kept", "dropped", "settings")}, {"kept": 1, "dropped": 1, "settings": True})
        self.assertTrue(discover.rescore_summary(stats["rescored"]).startswith("Your search settings changed since the prospects were scored"))
        self.assertNotIn("rescored", self.sweep(NO_REMOTE))

    def test_a_setting_that_only_orders_what_you_see_rescores_nothing(self):
        self.sweep(CFG)
        later = {**CFG, "freshness": {**CFG["freshness"], "older_points": -99}, "promote": {**CFG["promote"], "city_points": 99}}
        self.assertEqual(score.settings_key(later), score.settings_key(CFG))
        self.assertNotIn("rescored", self.sweep(later))

    def test_a_database_from_before_takes_the_settings_it_has_now(self):
        self.sweep(CFG)
        self.conn.execute("DELETE FROM meta WHERE key = ?", (store.SCORING_SETTINGS,))
        self.conn.commit()
        self.assertNotIn("rescored", self.sweep(NO_REMOTE))
        self.assertEqual(store.get_meta(self.conn, store.SCORING_SETTINGS), score.settings_key(NO_REMOTE))
