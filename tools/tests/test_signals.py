"""Deadlines that pass on a job or put the decision first, pay against your floor and similar roles, skills asked for
longer than they've existed, and roles that rarely come up nearby."""
import json
import unittest
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

from support import CFG, Base  # Also sets up the throwaway workspace every path points into.

from pyrite import cli, daily, deadline, discover, pay, server, signals, skillage, sources, store

TODAY = date(2026, 11, 8)


def spelled(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


class Deadlines(unittest.TestCase):
    def test_at_least_until_is_a_floor_and_the_rest_are_firm(self):
        self.assertEqual(deadline.in_posting("Applications will be accepted at least until November 6, 2026."), ("2026-11-06", False))
        self.assertEqual(deadline.in_posting("Applications accepted until November 6, 2026."), ("2026-11-06", True))
        self.assertEqual(deadline.in_posting("Apply by November 6, 2026, or until the position is filled."), ("2026-11-06", False))
        self.assertEqual(deadline.in_posting("This posting is expected to close on November 16th, 2026."), ("2026-11-16", True))
        self.assertEqual(deadline.in_posting("No dates here."), (None, True))

    def test_a_notes_deadline_wins_and_keeps_its_own_firmness(self):
        tmp = Path(self.id().replace(".", "_"))
        folder = store.ROOT / "applications" / tmp.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "notes.md").write_text("- **Deadline:** accepted at least until November 20, 2026\n", encoding="utf-8")
        info = deadline.for_job("Apply by November 1, 2026.", folder, TODAY)
        self.assertEqual((info["deadline"], info["deadline_firm"], info["days_to_deadline"]), ("2026-11-20", False, 12))

    def test_notes_restating_a_floor_date_dont_make_it_firm(self):
        folder = store.ROOT / "applications" / self.id().replace(".", "_")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "notes.md").write_text("- **Deadline:** November 6, 2026\n", encoding="utf-8")
        info = deadline.for_job("Applications will be accepted at least until November 6, 2026.", folder, TODAY)
        self.assertEqual((info["deadline"], info["deadline_firm"]), ("2026-11-06", False))
        self.assertFalse(deadline.expired(info))
        # A date of its own in the notes still keeps the notes' firmness.
        self.assertTrue(deadline.for_job("Applications will be accepted at least until November 1, 2026.", folder, TODAY)["deadline_firm"])

    def test_a_date_without_a_year_is_the_nearest_one_and_never_expires_a_job(self):
        self.assertEqual(deadline.in_posting("Applications accepted until Dec 1.", TODAY), ("2026-12-01", True))
        self.assertEqual(deadline.in_posting("Applications accepted until January 15th.", TODAY), ("2027-01-15", True))
        # Gone by, with its year guessed: a floor, so it doesn't pass on the job.
        self.assertEqual(deadline.in_posting("Applications accepted until November 1.", TODAY), ("2026-11-01", False))
        self.assertEqual(deadline.in_posting("Applications accepted until Dec 1."), (None, True))  # No today, no guess.

    def test_only_closing_words_make_a_deadline(self):
        self.assertEqual(deadline.in_posting("You must relocate no later than March 1, 2027."), (None, True))
        self.assertEqual(deadline.in_posting("Applications must be received no later than March 1, 2027."), ("2027-03-01", True))
        self.assertEqual(deadline.in_posting("Apply by November 20, 2026 or once filled."), ("2026-11-20", False))

    def test_only_a_firm_deadline_gone_by_expires(self):
        self.assertTrue(deadline.expired({"days_to_deadline": -1, "deadline_firm": True}))
        self.assertFalse(deadline.expired({"days_to_deadline": -1, "deadline_firm": False}))
        self.assertFalse(deadline.expired({"days_to_deadline": 0, "deadline_firm": True}))
        self.assertFalse(deadline.expired({"days_to_deadline": None}))

    def test_the_decision_is_due_within_the_window_or_just_past_a_floor(self):
        due = lambda days, firm=True: deadline.decide_soon({"days_to_deadline": days, "deadline_firm": firm}, 5)
        self.assertTrue(due(0))
        self.assertTrue(due(5))
        self.assertFalse(due(6))
        self.assertFalse(due(-1))
        self.assertTrue(due(-3, firm=False))
        self.assertFalse(due(-deadline.FLOOR_GRACE_DAYS - 1, firm=False))


class ExpiredJobs(Base):
    def posting(self, days: int, floor: bool = False) -> str:
        cue = "accepted at least until" if floor else "Applications accepted until"
        return f"About us. {cue} {spelled(date.today() + timedelta(days=days))}. Benefits."

    def test_the_sweep_passes_on_jobs_not_yet_sent_once_their_deadline_goes_by(self):
        gone = [self.add(source_id=str(n), status=status, description=self.posting(-2))
                for n, status in enumerate(("new", "shortlisted", "ready"))]
        floor = self.add(source_id="10", description=self.posting(-2, floor=True))
        open_ = self.add(source_id="11", description=self.posting(3))
        sent = self.add(source_id="12", status="applied", applied_at=store.now(), description=self.posting(-2))
        self.assertEqual(sorted(discover.settle_expired(self.conn)), sorted(gone))
        for job in gone:
            row = store.get_job(self.conn, job)
            self.assertEqual(row["status"], "passed")
        self.assertEqual({store.get_job(self.conn, j)["status"] for j in (floor, open_)}, {"new"})
        self.assertEqual(store.get_job(self.conn, sent)["status"], "applied")
        detail = self.conn.execute("SELECT detail FROM events WHERE job_id = ? AND kind = 'passed'", (gone[0],)).fetchone()[0]
        self.assertTrue(detail.startswith(discover.AUTO_PASSED))

    def test_undo_pass_sticks(self):
        job = self.add(description=self.posting(-1))
        discover.settle_expired(self.conn)
        store.set_status(self.conn, job, "new", "Undo pass")
        self.assertEqual(discover.settle_expired(self.conn), [])
        self.assertEqual(store.get_job(self.conn, job)["status"], "new")

    def test_the_gate_drops_a_new_posting_past_its_firm_deadline(self):
        self.assertEqual(discover.gate(self.posting(-1)), "expired")
        self.assertEqual(discover.gate(self.posting(-1, floor=True)), "")
        self.assertEqual(discover.gate(self.posting(2)), "")

    def test_the_queue_judges_a_closing_job_first_and_skips_an_expired_one(self):
        best = self.add(source_id="1", score=90, description="Plenty of time.")
        closing = self.add(source_id="2", score=50, description=self.posting(3))
        self.add(source_id="3", score=95, description=self.posting(-1))
        self.assertEqual([job["id"] for job in cli.queue(self.conn, CFG)["to_triage"]], [closing, best])

    def test_the_queue_doesnt_judge_a_job_paying_too_little_for_the_role_unless_you_picked_it(self):
        for n in range(6):
            self.add(source_id=f"peer{n}", status="passed", track="AI systems", title="Staff AI Engineer", comp="$240,000 - $280,000")
        fair = self.add(source_id="1", track="AI systems", title="Staff AI Engineer", comp="$230,000 - $270,000")
        low = self.add(source_id="2", track="AI systems", title="Staff AI Engineer", comp="$120,000 - $150,000")
        self.assertEqual([job["id"] for job in cli.queue(self.conn, CFG)["to_triage"]], [fair])
        self.conn.execute("UPDATE jobs SET priority = 1 WHERE id = ?", (low,))
        self.assertEqual([job["id"] for job in cli.queue(self.conn, CFG)["to_triage"]], [low, fair])


class Pay(unittest.TestCase):
    def test_ranges_read_as_a_years_pay(self):
        cases = {
            "$130,700 to $205,200 USD": (130700, 205200, "USD"),
            "$168,000�$285,600 USD": (168000, 285600, "USD"),
            "$257K – $285K • Offers Equity": (257000, 285000, "USD"),
            "CA$250K – CA$535K": (250000, 535000, "CAD"),
            "$149,750.00-275,580.00 USD": (149750, 275580, "USD"),
            "$45 - $60 an hour": (93600, 124800, "USD"),
            "$150-200k": (150000, 200000, "USD"),
            "£60,000 - £80,000": (60000, 80000, "GBP"),
        }
        for text, (low, high, currency) in cases.items():
            found = pay.parse(text)
            self.assertEqual((found.low, found.high, found.currency), (low, high, currency), text)
        self.assertIsNone(pay.parse("Up to 15% bonus"))
        self.assertIsNone(pay.parse(""))

    def test_a_typo_is_read_or_refused_not_misread(self):
        # A posting wrote "$194.390", a point where the comma goes, and it was read as $194.39.
        found = pay.parse("$141,380 -$194.390")
        self.assertEqual((found.low, found.high), (141380, 194390))
        self.assertEqual(pay.parse("$1.250M").high, 1250000)  # A scaled figure keeps its point.
        self.assertIsNone(pay.parse("$150,000 - $15,000,000"))  # One end has to be wrong, and nothing says which.

    def labels(self, comp: str, known: dict[str, list[float]], track: str = "AI systems", level: str = "top") -> list[str]:
        return [s["label"] for s in pay.judge(comp, track, level, {}, known)["pay_signs"]]

    def test_judged_against_the_role_not_the_candidate(self):
        known = {"AI systems|top": [200000.0] * 10}
        self.assertEqual(self.labels("$190,000 - $230,000", known), [])
        self.assertEqual(self.labels("$140,000 - $175,000", known), ["Pays under the going rate"])
        self.assertEqual(self.labels("$300,000 - $340,000", known), ["Pays well above similar roles"])
        low = pay.judge("$110,000 - $140,000", "AI systems", "top", {}, known)
        self.assertEqual([s["label"] for s in low["pay_signs"]], ["Too low to bother"])
        self.assertTrue(low["pay_too_low"])
        self.assertLess(low["pay_points"], 0)
        self.assertEqual(self.labels("CA$100K – CA$140K", known), ["Paid in CAD"])  # Another currency isn't compared.

    def test_the_narrowest_group_with_enough_postings_is_the_yardstick(self):
        known = {"AI systems|top": [300000.0] * 2, "AI systems": [200000.0] * 9, "*": [130000.0] * 30}
        self.assertEqual(self.labels("$140,000 - $175,000", known), ["Pays under the going rate"])  # Against the track.
        self.assertEqual(self.labels("$140,000 - $175,000", known, track="Rare track"), [])  # Against every track.
        self.assertEqual(self.labels("$140,000 - $175,000", {"*": [300000.0] * 3}), [])  # Too few to say.

    def test_too_low_to_bother_takes_postings_at_its_own_level(self):
        # Against its whole track, which is mostly senior-most roles, it's only under the going rate: the run still judges it.
        widened = pay.judge("$110,000 - $140,000", "T", "", {}, {"T": [215000.0] * 30})
        self.assertEqual(([s["label"] for s in widened["pay_signs"]], widened["pay_too_low"]), (["Pays under the going rate"], False))
        self.assertTrue(pay.judge("$110,000 - $140,000", "T", "", {}, {"T|": [215000.0] * 5})["pay_too_low"])

    def test_a_wide_range_says_so(self):
        self.assertIn("Wide range", self.labels("$120,000 - $260,000", {}))

    def test_peers_take_the_middles_at_each_level(self):
        rows = ([{"comp": f"${n}0,000 - ${n + 2}0,000", "track": "T", "level": "top"} for n in (10, 12, 14)]
                + [{"comp": "$50,000 - $70,000", "track": "T", "level": "mid"}, {"comp": "", "track": "T", "level": "top"}])
        self.assertEqual(pay.peers(rows), {"T|top": [110000.0, 130000.0, 150000.0], "T|mid": [60000.0],
                                           "T": [60000.0, 110000.0, 130000.0, 150000.0], "*": [60000.0, 110000.0, 130000.0, 150000.0]})

    def test_a_posting_isnt_measured_against_itself(self):
        # Five others pay a middle of $200k. Counted in, its own $120k middle would pull the median down to $190k.
        known = {"T|top": sorted([200000.0] * 5 + [120000.0])}
        judged = pay.judge("$110,000 - $130,000", "T", "top", {}, known, counted=True)
        self.assertIn("$200k", judged["pay_signs"][0]["detail"])
        self.assertIn("5 other", judged["pay_signs"][0]["detail"])
        # With only four others it has too few to compare with, though five ranges are on file.
        self.assertEqual(pay.judge("$110,000 - $130,000", "T", "top", {}, {"T|top": [120000.0] + [200000.0] * 4}, counted=True)["pay_signs"], [])

    def test_a_product_manager_isnt_senior_most_and_entry_level_stands_apart(self):
        cfg = {"scoring": {"level_top": ["principal", "director", "manager"], "level_mid": ["senior", "sr", "lead"]}}
        self.assertEqual(pay.level("Product Manager, Software", cfg), "")
        self.assertEqual(pay.level("Technical Program Manager - Entry Level", cfg), "entry")
        self.assertEqual(pay.level("Manager, Software Engineering", cfg), "top")
        self.assertEqual(pay.level("Principal Product Manager", cfg), "top")
        self.assertEqual(pay.level("Senior Program Manager", cfg), "mid")
        # Entry-level pay is compared only with other entry-level pay, never with the senior pay of its track.
        known = {"T": [200000.0] * 20, "*": [200000.0] * 20}
        self.assertEqual(self.labels("$110,000 - $140,000", known, track="T", level="entry"), [])

    def test_the_period_and_currency_beside_the_range_count(self):
        cases = {
            "$12,000 - $15,000 per month": (144000, 180000, "USD"),
            "$400 - $450 per day": (104000, 117000, "USD"),
            "$120k-$160k/yr; contractors $90/hr": (120000, 160000, "USD"),
            "Hourly: $45 - $60": (93600, 124800, "USD"),
            "$150,000 - $200,000 CAD": (150000, 200000, "CAD"),
            "MX$400,000 - MX$500,000": (400000, 500000, "MX$"),
        }
        for text, (low, high, currency) in cases.items():
            found = pay.parse(text)
            self.assertEqual((found.low, found.high, found.currency), (low, high, currency), text)

    def test_pay_text_keeps_what_it_says_about_the_range(self):
        self.assertEqual(sources.find_comp("Pays $12,000 - $15,000 per month."), "$12,000 - $15,000 per month")
        self.assertEqual(sources.find_comp("The range is between $132,000 and $198,000 annually."), "$132,000 - $198,000 annually")
        self.assertEqual(sources.find_comp("$150,000 - $200,000 CAD plus equity"), "$150,000 - $200,000 CAD")
        # A sign-on bonus isn't the pay, whether it's named before the range or after it.
        self.assertEqual(sources.find_comp("Sign-on bonus: $10,000 - $20,000. Base salary $150,000 - $180,000."), "$150,000 - $180,000")
        self.assertEqual(sources.find_comp("A $10,000 - $20,000 sign-on bonus, and $150,000 - $180,000 base."), "$150,000 - $180,000")
        self.assertEqual(sources.find_comp("Base pay $150,000 - $180,000, plus bonus."), "$150,000 - $180,000")
        self.assertEqual(sources._lever_pay({"currency": "cad", "interval": "per-hour-wage", "min": 40, "max": 50}), "$40 - $50 CAD per hour")

    def test_pay_missed_when_found_is_read_from_the_description(self):
        job = {"comp": "", "description": "Pay is between $132,000 and $198,000.", "title": "Manager"}
        self.assertEqual(signals.comp_for(job), "$132,000 - $198,000")
        self.assertEqual(signals.comp_for({**job, "comp": "$257K – $285K • Offers Equity"}), "$257K – $285K • Offers Equity")
        older = {"comp": "$12,000 - $15,000", "description": "Pays $12,000 - $15,000 per month.", "title": ""}
        self.assertEqual(signals.comp_for(older), "$12,000 - $15,000 per month")


class SkillAges(unittest.TestCase):
    def test_an_ask_longer_than_the_skill_has_existed(self):
        found = skillage.asks("Requirements: 8+ years of experience building AI agents and LLM-based workflows.", TODAY)
        self.assertEqual([(a.skill.name, a.years, a.impossible) for a in found], [("AI agents", 8, True)])
        self.assertIn("Nobody meets that", skillage.describe(found[0]))

    def test_an_ask_within_the_skills_life(self):
        found = skillage.asks("5+ years of hands-on experience with large language models.", TODAY)
        self.assertEqual([(a.skill.name, a.impossible) for a in found], [("large language models", False)])
        self.assertIn("of its whole life", skillage.describe(found[0]))

    def test_the_skill_can_come_before_the_years(self):
        found = skillage.asks("Experience with Kubernetes (5+ years). Python required.", TODAY)
        self.assertEqual([a.skill.name for a in found], ["Kubernetes"])

    def test_years_of_something_broad_dont_land_on_a_skill_named_after_it(self):
        self.assertEqual(skillage.asks("8+ years of software engineering experience, including LLM agents.", TODAY), [])
        self.assertEqual(skillage.asks("We use LLMs daily. 8 years of software experience.", TODAY), [])
        self.assertEqual(skillage.asks("A company 25 years old.", TODAY), [])

    def test_ranges_and_spelled_numbers_count_from_the_bottom(self):
        found = {a.skill.name: a.years for a in skillage.asks("3-5 years of Rust; five (5) years of experience with React.js.", TODAY)}
        self.assertEqual(found, {"Rust": 3, "React": 5})

    def test_unknown_phrases_are_what_research_could_date(self):
        self.assertEqual(skillage.unknown_phrases("10+ years of experience with distributed storage systems and RDMA"),
                         ["distributed storage"])
        self.assertEqual(skillage.unknown_phrases("10+ years of professional software engineering experience"), [])

    def test_a_note_that_only_restates_an_impossible_ask(self):
        self.assertTrue(skillage.only_restates("The posting requires 8+ years of AI agents; the record shows one.", TODAY))
        self.assertFalse(skillage.only_restates("The posting requires 5+ years of large language models.", TODAY))
        self.assertFalse(skillage.only_restates("Requires US citizenship.", TODAY))

    def test_research_keeps_only_dated_answers_it_found_a_source_for(self):
        answer = json.dumps({"skills": [
            {"phrase": "rdma", "name": "RDMA", "kind": "dated", "since": "2000-10", "basis": "x", "source": "https://example.org/rdma"},
            {"phrase": "made up", "name": "X", "kind": "dated", "since": "2020-01", "basis": "x", "source": "https://example.org/nowhere"},
            {"phrase": "distributed storage", "kind": "general"},
            {"phrase": "not asked", "kind": "general"},
        ]})
        kept = skillage.vet(answer, ["rdma", "made up", "distributed storage"], {"https://example.org/rdma"}, TODAY)
        self.assertEqual({k: v["kind"] for k, v in kept.items()}, {"rdma": "dated", "made up": "unknown", "distributed storage": "general"})

    def test_researched_skills_are_used_and_not_asked_about_again(self):
        path = skillage.learned_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        path.write_text(json.dumps({"phrases": {
            "frobnicator": {"kind": "dated", "name": "Frobnicator", "since": "2024-01", "basis": "Released.", "source": "https://e.org"},
            "distributed storage": {"kind": "general"},
        }}), encoding="utf-8")
        found = skillage.asks("5+ years of experience with the Frobnicator platform.", TODAY)
        self.assertEqual([(a.skill.name, a.impossible) for a in found], [("Frobnicator", True)])
        self.assertEqual(skillage.to_research(["10+ years of distributed storage", "3+ years of Quuxify"]), ["quuxify"])

    def test_the_prompt_section_says_not_to_count_it(self):
        text = skillage.prompt_section(skillage.signals("8+ years of AI agents.", TODAY))
        self.assertIn("How old the skills it asks for are", text)
        self.assertIn("isn't the candidate's gap", text)
        self.assertEqual(skillage.prompt_section({}), "")


class Rarity(unittest.TestCase):
    def ctx(self, local: dict[str, int], watched: int = 60) -> signals.Context:
        return signals.Context(TODAY, {}, Counter(local), watched, 5)

    def job(self, **kw) -> dict[str, Any]:
        return {"track": "AI systems", "location_kind": "local", "first_seen": TODAY.isoformat(), **kw}

    def test_a_local_role_few_others_share(self):
        found = signals.rarity(self.job(), CFG, self.ctx({"AI systems": 2}))
        self.assertTrue(found["rare"])
        self.assertEqual(found["rare_reason"], "only 1 other AI systems role near you in 90 days")
        self.assertFalse(signals.rarity(self.job(), CFG, self.ctx({"AI systems": 4}))["rare"])

    def test_never_for_remote_roles_or_before_there_is_history(self):
        self.assertFalse(signals.rarity(self.job(location_kind="remote"), CFG, self.ctx({}))["rare"])
        self.assertFalse(signals.rarity(self.job(), CFG, self.ctx({}, watched=5))["rare"])


class OnTheDashboard(Base):
    def test_the_job_carries_the_signals_and_its_priority_counts_them(self):
        self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", ((date.today() - timedelta(days=60)).isoformat(),))
        for n in range(5):  # Remote, so they set the going rate without making the local one any less rare.
            self.add(source_id=f"peer{n}", status="passed", track="AI systems", title="Staff AI Engineer",
                     location_kind="remote", comp="$240,000 - $280,000")
        job = self.add(track="AI systems", title="Staff AI Engineer", location_kind="local", comp="$160,000 - $200,000",
                       description="8+ years of experience building AI agents.")
        found = server._enrich(store.get_job(self.conn, job), CFG, date.today().isoformat(),
                               context=signals.context(self.conn, CFG, date.today()))
        self.assertEqual(found["impossible_asks"], ["AI agents"])
        self.assertTrue(found["rare"])
        self.assertIn("Pays under the going rate", [s["label"] for s in found["pay_signs"]])
        self.assertTrue(any(reason.startswith("Rare near you") for reason in found["freshness_reasons"]))
        self.assertTrue(any(reason.startswith("Pay ") for reason in found["freshness_reasons"]))

    def test_a_decision_within_the_window_is_on_the_to_do_list(self):
        soon = date.today() + timedelta(days=4)
        job = self.add(description=f"Applications accepted until {spelled(soon)}.")
        state = server.build_state(self.conn, CFG)
        order = next(o for o in state["orders"] if o["job_id"] == job)
        self.assertEqual(order["kind"], "Closing soon")
        self.assertEqual(order["rank"], 2)
        self.assertIn("Decide now", order["detail"])


class InThePrompts(unittest.TestCase):
    def test_triage_hears_about_the_deadline_pay_rarity_and_skill_ages(self):
        marks = {"deadline": "2026-11-12", "days_to_deadline": 4, "deadline_firm": True, "rare": True,
                 "rare_reason": "no other AI systems roles near you in 90 days",
                 "pay_signs": [{"label": "Too low to bother", "tone": "bad", "detail": "Even the top is under 75% of the norm."}],
                 **skillage.signals("8+ years of AI agents.", TODAY)}
        text = daily.markings(marks)
        for said in ("Deadline: Nov 12, in 4 days", "Pay: Too low to bother", "Rare near the candidate", "How old the skills"):
            self.assertIn(said, text)

    def test_tailoring_hears_about_skill_ages(self):
        row = {"company": "Acme", "title": "Staff Engineer", "description": "8+ years of AI agents."}
        with mock.patch.object(daily.claude_code, "files_section", return_value=""):
            text = daily.tailor_prompt(row, "applications/acme", CFG)
        self.assertIn("How old the skills it asks for are", text)


if __name__ == "__main__":
    unittest.main()
