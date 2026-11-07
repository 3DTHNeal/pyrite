"""Deadlines, what to settle before applying, and moving quickly through prospects without losing anything."""
import json
import unittest
from datetime import date, timedelta

from test_pyrite import CFG, Base  # Also sets up the throwaway workspace every path points into.

from pyrite import deadline, server, store


def spelled(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


class PostingDeadline(unittest.TestCase):
    def test_the_ways_boards_write_a_closing_date(self):
        cases = {
            "Applications for this job will be accepted at least until November 6, 2026.": "2026-11-06",
            "We anticipate the application window for this opening will close on - 9 Nov 2026": "2026-11-09",
            "This posting is expected to close on November 16th, 2026.": "2026-11-16",
            "Application deadline: 2026-12-01": "2026-12-01",
        }
        for text, want in cases.items():
            self.assertEqual(deadline.from_posting(f"About us. {text} Benefits."), want, text)

    def test_a_date_that_isnt_a_deadline_is_left_alone(self):
        self.assertIsNone(deadline.from_posting("Founded on March 3, 2001. Apply by sending your resume."))
        self.assertIsNone(deadline.from_posting("Start no later than 30 days after an offer."))
        self.assertIsNone(deadline.from_posting(""))


class NotesBeforeApplying(unittest.TestCase):
    NOTES = """# Acme: Role

- **Location:** Springfield, or remote in IL. Confirm before applying from Wisconsin, since relocation is out.
- **Deadline:** applications accepted at least until November 8, 2026, two days from the save date.
- **Check before applying:** **The remote option may need Illinois residency.**
- **Referral:** none known. See "Before you apply".

## Before you apply

Some framing first.

1. **The core requirement is unmet.** Nothing on record covers lidar.
2. Location is a stretch. More words here.

## How the posting maps

| Want | Have |
|---|---|
| A thing to do before applying | Nothing |
"""

    def test_deadline_and_the_things_that_could_rule_it_out(self):
        when, blockers = deadline.from_notes(self.NOTES)
        self.assertEqual(when, "2026-11-08")
        # The referral line only points at the section, and the table is evidence, so neither is listed.
        self.assertEqual(blockers, [
            "Location: Confirm before applying from Wisconsin, since relocation is out.",
            "The remote option may need Illinois residency.",
            "The core requirement is unmet",
            "Location is a stretch.",
        ])

    def test_notes_without_any_say_nothing(self):
        self.assertEqual(deadline.from_notes("# Acme\n\n- **Posting:** https://example.com\n"), (None, []))


class Sluice(Base):
    def folder(self, name, checked=None):
        folder = store.ROOT / "applications" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "resume.md").write_text("# Resume\n", encoding="utf-8")
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()] and folder.rmdir())
        return f"applications/{name}", json.dumps({"ok": True, "checked": checked or {}})

    def test_the_draft_closing_tomorrow_comes_first_and_says_so(self):
        tomorrow = date.today() + timedelta(days=1)
        self.add(source_id="a", title="Calm", status="ready", score=90)
        self.add(source_id="b", title="Urgent", status="ready", score=50,
                 description=f"Applications accepted at least until {spelled(tomorrow)}.")
        sends = [o for o in server.build_state(self.conn, CFG)["orders"] if o["kind"] == "Send"]
        self.assertEqual([o["text"] for o in sends], ["Acme: Urgent", "Acme: Calm"])
        self.assertIn("Apply by tomorrow", sends[0]["detail"])

    def test_a_draft_changed_after_its_pass_asks_to_be_checked_not_sent(self):
        folder, result = self.folder("2026-11-acme-changed", {"resume.md": "not the hash of what's there now"})
        self.add(source_id="a", title="Changed", status="ready", app_folder=folder, check_result=result)
        orders = server.build_state(self.conn, CFG)["orders"]
        self.assertEqual([(o["kind"], o.get("action")) for o in orders], [("Check again", "recheck")])

    def test_a_prospect_closing_soon_is_on_the_list_even_when_not_new(self):
        soon = date.today() + timedelta(days=2)
        old = (date.today() - timedelta(days=40)).isoformat()
        self.add(source_id="a", title="Old but closing", posted_at=old, description=f"Expected to close on {spelled(soon)}.")
        orders = server.build_state(self.conn, CFG)["orders"]
        self.assertEqual([o["kind"] for o in orders], ["Closing soon"])

    def test_a_second_listing_of_a_job_you_sent_is_pointed_out(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.add(source_id="sent", company="Initech Corporation", title="Seniors AI Software Development Engineer",
                 status="applied", applied_at=yesterday + "T17:00:00+00:00")
        self.add(source_id="again", company="Initech", title="Senior AI Software Development Engineer", posted_at=yesterday)
        state = server.build_state(self.conn, CFG)
        again = next(j for j in state["jobs"] if j["source_id"] == "again")
        self.assertEqual((again["applied_here"], again["same_title_applied"]["title"]), (1, "Seniors AI Software Development Engineer"))
        listing = next(o for o in state["orders"] if o["kind"] == "New listing")
        self.assertIn("You applied for Seniors AI Software Development Engineer here", listing["detail"])
        self.assertIsNone(next(j for j in state["jobs"] if j["source_id"] == "sent")["same_title_applied"])

    def test_a_different_title_at_the_same_company_is_only_counted(self):
        self.add(source_id="sent", title="Firmware Lead", status="applied", applied_at=store.now())
        self.add(source_id="other", title="Product Manager, Cloud")
        other = next(j for j in server.build_state(self.conn, CFG)["jobs"] if j["source_id"] == "other")
        self.assertEqual((other["applied_here"], other["same_title_applied"]), (1, None))

    def test_the_field_report_says_how_much_has_moved_since(self):
        self.conn.execute("INSERT INTO briefings (ts, body) VALUES ('2000-01-01T00:00:00+00:00', 'Send Acme first.')")
        job = self.add()
        self.assertEqual(server.build_state(self.conn, CFG)["briefing"]["since"], {})
        store.set_status(self.conn, job, "applied")
        self.assertEqual(server.build_state(self.conn, CFG)["briefing"]["since"], {"applied": 1})


class Triage(Base):
    def act(self, job, **body):
        server.apply_action(self.conn, job, body, CFG)

    def test_opening_a_prospect_marks_it_seen_once_and_keeps_the_timeline_clean(self):
        job = self.add()
        self.assertFalse(server.build_state(self.conn, CFG)["jobs"][0]["seen"])
        self.act(job, action="seen")
        self.act(job, action="seen")
        self.assertTrue(server.build_state(self.conn, CFG)["jobs"][0]["seen"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'seen'").fetchone()[0], 1)
        self.assertNotIn("seen", [e["kind"] for e in server.job_detail(self.conn, job, CFG)["events"]])

    def test_undoing_a_pass_puts_the_job_back_where_it_was(self):
        prospect = self.add(source_id="a")
        self.act(prospect, action="status", status="passed")
        self.assertTrue(server.job_detail(self.conn, prospect, CFG)["can_unpass"])
        self.act(prospect, action="unpass")
        self.assertEqual(store.get_job(self.conn, prospect)["status"], "new")

        queued = self.add(source_id="b")
        self.act(queued, action="tailor_next")
        self.act(queued, action="status", status="passed")
        self.act(queued, action="unpass")
        self.assertEqual(store.get_job(self.conn, queued)["status"], "shortlisted")

    def test_only_a_pass_can_be_undone_this_way(self):
        sent = self.add()
        self.act(sent, action="status", status="applied")
        self.act(sent, action="status", status="withdrawn")
        with self.assertRaises(ValueError):
            self.act(sent, action="unpass")
        withdrawn_then_passed = self.add(source_id="c")
        self.act(withdrawn_then_passed, action="status", status="applied")
        self.act(withdrawn_then_passed, action="status", status="passed")
        self.assertFalse(server.job_detail(self.conn, withdrawn_then_passed, CFG)["can_unpass"])



class ReplyNumbers(Base):
    def applied(self, source_id, *then):
        job = self.add(source_id=source_id)
        for status in ("applied", *then):
            store.set_status(self.conn, job, status)
        return job

    def test_a_rejection_is_counted_beside_replies_not_inside_them(self):
        self.applied("a", "rejected")
        self.applied("b", "responded")
        self.applied("c")
        state = server.build_state(self.conn, CFG)
        stats = state["stats"]
        self.assertEqual((stats["replied"], stats["rejected"], stats["reply_rate"], stats["heard"]), (1, 1, 33, 2))
        self.assertEqual({f["stage"]: f["count"] for f in state["funnel"]}["Replied"], 1)

    def test_a_rejection_after_an_interview_still_counts_as_a_reply(self):
        self.applied("a", "interviewing", "rejected")
        stats = server.build_state(self.conn, CFG)["stats"]
        self.assertEqual((stats["replied"], stats["rejected"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
