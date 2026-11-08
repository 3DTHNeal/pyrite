"""Whether a listing is a real opening: talent pools, evergreen roles, scam tells, unconfirmed listings and reposts."""
import json
import unittest
from datetime import date

from support import CFG, Base, Clock, stub_feed

from pyrite import discover, quality, score, server, sources, store

FIRMWARE = "firmware embedded c++ python robot hardware"


class NoOpening(unittest.TestCase):
    """Wording taken from real postings, with the employer left out."""

    def test_titles_that_name_no_job(self):
        for title in ("General Application", "[Expression of Interest] Research Engineer", "Join Our Talent Community!",
                      "Future Opportunities - Firmware", "Don't see the right role? Apply here"):
            self.assertTrue(quality.not_an_opening(title, ""), title)
        for title in ("Principal Firmware Engineer", "Talent Acquisition Partner", "General Manager, Robotics"):
            self.assertFalse(quality.not_an_opening(title, ""), title)

    def test_text_saying_there_is_no_opening(self):
        said = "While we don’t have an open position at the moment, we’re actively growing our network for future opportunities."
        self.assertTrue(quality.not_an_opening("Associate Technical Program Manager", said))
        self.assertTrue(quality.not_an_opening("Engineer", "This posting is for future openings on the platform team."))
        # A hedge about other teams isn't a statement that this one has nothing.
        hedge = "You may not hear back from us directly if we do not currently have an open role on any of our teams that matches."
        self.assertFalse(quality.not_an_opening("Research Engineer", hedge))
        ordinary = ("Building a talent pipeline for future hiring. Applications are reviewed on a rolling basis. "
                    "Not the right fit? Join our talent community.")
        self.assertFalse(quality.not_an_opening("Technical Recruiter", ordinary))

    def test_evergreen_wording_and_its_namesakes(self):
        self.assertTrue(quality.evergreen('Note: This is an "evergreen" role that we keep open on an ongoing basis.'))
        self.assertTrue(quality.evergreen("This is a pipeline role feeding four areas."))
        self.assertTrue(quality.evergreen("We accept applications for this role year-round."))
        for text in ("Turn winning pilots into evergreen, automated motions.", "Our office is at 100 Evergreen Road.",
                     "Monitor projects on an ongoing basis.", "Experience building pipeline in new territories.",
                     "Applications are reviewed on a rolling basis."):
            self.assertFalse(quality.evergreen(text), text)

    def test_a_posting_that_says_it_has_no_opening_is_dropped_before_one_that_looks_like_a_scam(self):
        self.assertEqual(quality.rejection("General Application", "Interviews are held over Telegram."), "not_open")
        self.assertEqual(quality.rejection("Firmware Engineer", "Interviews are held over Telegram."), "scam")
        self.assertEqual(quality.rejection("Firmware Engineer", FIRMWARE), "")


class ScamTells(unittest.TestCase):
    def test_tells(self):
        self.assertEqual(quality.scam_signs("A $75 training fee is required before your first day."), ("Asks you to pay a fee",))
        self.assertEqual(quality.scam_signs("You will pay a small registration fee to start."), ("Asks you to pay a fee",))
        self.assertEqual(quality.scam_signs("Please message our hiring manager on WhatsApp."), ("Wants you to talk over a chat app",))
        self.assertEqual(quality.scam_signs("The interview will be conducted via Telegram."), ("Wants you to talk over a chat app",))
        self.assertEqual(quality.scam_signs("We will send you a check for your home office."), ("Sends you a check to deposit",))

    def test_disclaimers_and_ordinary_work_are_not_tells(self):
        for text in ("We will never charge an application fee or ask you to pay a training fee.",
                     "We don't send checks. We will never send you a check before you start.",
                     "Our recruiters will not contact you on WhatsApp or Telegram.",
                     "Reach customers via WhatsApp and SMS campaigns.", "Experience with the Telegram Bot API.",
                     "Process vendor payments through ACH and wire transfers. Deposit the checks daily.",
                     "Tuition reimbursement. We'll order you a laptop and reimburse home office equipment.",
                     "Background in post-training feedback loops.", "We cover required certification fees."):
            self.assertEqual(quality.scam_signs(text), (), text)


class FreshnessSignals(unittest.TestCase):
    TODAY = date(2026, 11, 5)
    SWEPT = "2026-11-05T06:00:00+00:00"

    def view(self, swept_at=None, **job):
        row = {"score": 60, "reposts": 0, "redates": 0, "source_key": "greenhouse:acme", **job}
        return score.freshness(row, CFG, self.TODAY, swept_at)

    def test_the_day_it_was_found_is_a_floor_on_age(self):
        # The board says it was posted yesterday, but the sweep has seen it since June.
        moved = self.view(posted_at="2026-11-04", first_seen="2026-06-01T00:00:00+00:00")
        self.assertEqual(moved["age_days"], 157)
        self.assertFalse(moved["is_new"])
        self.assertTrue(moved["ghost_risk"])
        self.assertEqual(self.view(posted_at="2026-11-04", first_seen="2026-11-04T09:00:00+00:00")["age_days"], 1)

    def test_with_no_date_the_day_it_was_found_only_raises_a_ghost(self):
        found_today = self.view(first_seen="2026-11-05T06:00:00+00:00")
        self.assertEqual((found_today["age_days"], found_today["rank"], found_today["is_new"], found_today["ghost_risk"]),
                         (None, 60, False, False))
        long_ago = self.view(first_seen="2026-05-01T06:00:00+00:00")
        self.assertIsNone(long_ago["age_days"])
        self.assertEqual(long_ago["ghost_reason"], "listed for at least 188 days")

    def test_a_job_you_added_keeps_its_own_dates(self):
        added = self.view(source_key="manual", posted_at="2026-11-04", first_seen="2026-06-01T00:00:00+00:00")
        self.assertEqual(added["age_days"], 1)

    def test_a_listing_the_last_full_sweep_did_not_see_is_unconfirmed(self):
        stale = self.view(self.SWEPT, posted_at="2026-11-03", last_seen="2026-11-01T06:00:00+00:00")
        self.assertTrue(stale["unconfirmed"])
        self.assertFalse(stale["is_new"])
        seen = self.view(self.SWEPT, posted_at="2026-11-03", last_seen="2026-11-05T06:01:00+00:00")
        self.assertEqual((seen["unconfirmed"], seen["is_new"]), (False, True))
        for job in ({"posting_closed_at": "2026-11-02T00:00:00+00:00"}, {"source_key": "manual"}):
            self.assertFalse(self.view(self.SWEPT, last_seen="2026-11-01T06:00:00+00:00", **job)["unconfirmed"])
        self.assertFalse(self.view(None, last_seen="2026-11-01T06:00:00+00:00")["unconfirmed"])

    def test_the_postings_own_words_raise_a_ghost_and_a_scam(self):
        evergreen = self.view(posted_at="2026-11-03", description='This is an "evergreen" role we keep open on an ongoing basis.')
        self.assertTrue(evergreen["ghost_risk"])
        self.assertIn("ongoing hiring", evergreen["ghost_reason"])
        self.assertFalse(evergreen["is_new"])
        scam = self.view(posted_at="2026-11-03", description="Interviews are held over Telegram.")
        self.assertEqual(scam["scam_signs"], ["Wants you to talk over a chat app"])
        self.assertEqual(self.view(posted_at="2026-11-03", description=FIRMWARE)["scam_signs"], [])


class SweepDropsWhatIsNoOpening(Base):
    def setUp(self):
        super().setUp()
        self.clock = Clock(self)
        self.saved = dict(sources.FEEDS)
        self.addCleanup(lambda: (sources.FEEDS.clear(), sources.FEEDS.update(self.saved)))
        self.cfg = {**CFG, "watch": {"greenhouse": {"acme": "Acme"}, "lever": {}, "ashby": {}, "workday": {}}}

    def posting(self, sid, desc=FIRMWARE, title="Principal Firmware Engineer"):
        return sources.Posting("greenhouse:acme", sid, "Acme", title, "Madison, WI", "", "https://x.test/1", desc)

    def test_a_talent_pool_and_a_scam_are_dropped_and_counted(self):
        stub_feed(None, [self.posting("1"),
                         self.posting("2", f"{FIRMWARE}. While we don't have an open position at the moment, we're growing our network."),
                         self.posting("3", f"{FIRMWARE}. Interviews are conducted over Telegram.")])
        stats = discover.run(conn=self.conn, cfg=self.cfg)
        self.assertEqual((stats["new"], stats["rejected"]["not_open"], stats["rejected"]["scam"]), (1, 1, 1))
        reasons = dict(self.conn.execute("SELECT source_id, reason FROM rejected").fetchall())
        self.assertEqual((reasons["2"], reasons["3"]), ("not_open", "scam"))

    def test_rescore_drops_a_stored_posting_that_says_it_has_no_opening(self):
        self.add(source_id="9", title="Principal Firmware Engineer", location="Madison, WI",
                 description=f"{FIRMWARE}. This posting is for future openings.")
        self.assertEqual(discover.rescore(self.conn, self.cfg), {"kept": 0, "dropped": 1})
        self.assertEqual(self.conn.execute("SELECT reason FROM rejected").fetchone()[0], "not_open")


class Requisitions(Base):
    KEY = "workday:contoso"

    def setUp(self):
        super().setUp()
        self.clock = Clock(self)
        self.stats = {"new": 0, "reposted": 0, "rejected": {}, "new_ids": []}

    def ingest(self, path, title="Principal Firmware Engineer", desc=FIRMWARE, baseline=False, location="Madison, WI"):
        started = store.now()
        posting = sources.Posting(self.KEY, path, "Contoso", title, location, "", "", desc, "", "2026-11-01")
        discover._ingest(self.conn, posting, CFG, self.stats, store.now(), self.KEY, started, baseline)
        self.clock.advance()

    def jobs(self):
        return self.conn.execute("SELECT * FROM jobs").fetchall()

    def test_the_id_in_a_workday_link(self):
        cases = {"/job/x/Eng_R-88690": "R-88690", "/job/x/Arch_JR0000456-1": "JR0000456", "/job/x/Lead_4000123-12": "4000123",
                 "/job/x/Mgr_REQ-10001": "REQ-10001", "/job/x/Page_2": "", "/job/x/Engineer": ""}
        for path, wanted in cases.items():
            self.assertEqual(discover.requisition(self.KEY, path), wanted, path)
        self.assertEqual(discover.requisition("greenhouse:acme", "/job/x/Eng_R-88690"), "")

    def test_a_rewritten_repost_under_the_same_requisition_is_one_job(self):
        self.ingest("/job/x/Principal-Firmware-Engineer_R-12345", baseline=True)
        rewritten = "embedded firmware for robots in c++ and python, with board bring-up and hardware test " * 3
        self.ingest("/job/x/Principal-Firmware-Engr_R-12345-1", title="Principal Firmware Engr", desc=rewritten)
        jobs = self.jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0]["reposts"], jobs[0]["source_id"]), (1, "/job/x/Principal-Firmware-Engr_R-12345-1"))

    def test_on_a_first_look_the_same_requisition_is_listed_once_without_a_repost(self):
        self.ingest("/job/x/Principal-Firmware-Engineer_R-12345", baseline=True)
        self.ingest("/job/y/Principal-Firmware-Engineer_R-12345-1", baseline=True, desc=f"{FIRMWARE} in our second office",
                    location="Sunnydale, WI")
        self.assertEqual([job["reposts"] for job in self.jobs()], [0])

    def test_a_reused_id_on_a_different_job_stays_separate(self):
        self.ingest("/job/x/Principal-Firmware-Engineer_R-12345", baseline=True)
        self.ingest("/job/x/Principal-Robotics-Software-Engineer_R-12345-1", title="Principal Robotics Software Engineer",
                    desc="robot software " * 20 + FIRMWARE)
        self.assertEqual(len(self.jobs()), 2)

    def test_short_forms_in_titles_read_as_the_words(self):
        self.assertEqual(discover._norm_title("Sr. Firmware Engr"), discover._norm_title("Senior Firmware Engineer"))
        self.assertEqual(discover._norm_title("TPM, Platform"), discover._norm_title("Technical Program Manager - Platform"))


class LateDates(Base):
    def test_a_date_that_turns_up_later_gives_the_job_an_age_without_a_redate(self):
        job = self.add()
        store.record_listing(self.conn, job, "greenhouse:acme", "1", "Madison, WI", None, store.now())
        stats = {"redated": 0}
        discover._note_redates(self.conn, {"source_key": "greenhouse:acme", "dates": {"1": "2026-10-01"}}, CFG, store.now(), stats)
        row = store.get_job(self.conn, job)
        self.assertEqual((row["posted_at"], row["first_posted_at"], row["redates"], stats["redated"]), ("2026-10-01", "2026-10-01", 0, 0))


class OnTheDashboard(Base):
    def full_sweep(self, started):
        self.conn.execute("INSERT INTO runs (started_at, finished_at, stats) VALUES (?, ?, ?)",
                          (started, started, json.dumps({"partial": False, "sources": 3})))

    def test_a_posting_with_scam_tells_leads_the_to_do_list(self):
        job = self.add(source_key="manual", description="Interviews are held over Telegram. A training fee is required.")
        state = server.build_state(self.conn, CFG)
        order = next(o for o in state["orders"] if o["job_id"] == job)
        self.assertEqual((order["kind"], order["rank"]), ("Possible scam", 0))
        self.assertIn("chat app", order["detail"])

    def test_a_listing_the_last_sweep_missed_is_unconfirmed_and_not_new(self):
        missed = self.add(source_id="1", posted_at=date.today().isoformat(), last_seen="2026-01-01T00:00:00+00:00")
        seen = self.add(source_id="2", posted_at=date.today().isoformat())
        self.full_sweep("2026-06-01T00:00:00+00:00")
        jobs = {j["id"]: j for j in server.build_state(self.conn, CFG)["jobs"]}
        self.assertEqual((jobs[missed]["unconfirmed"], jobs[missed]["is_new"]), (True, False))
        self.assertEqual((jobs[seen]["unconfirmed"], jobs[seen]["is_new"]), (False, True))
        self.assertTrue(server.job_detail(self.conn, missed, CFG)["unconfirmed"])


if __name__ == "__main__":
    unittest.main()
