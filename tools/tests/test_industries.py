"""The Industries tab: official numbers from the BLS, what Pyrite has seen, and Claude's sourced outlook."""
import contextlib
import json
import subprocess
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from datetime import date
from pathlib import Path

from support import CFG, Base

from pyrite import market, outlook, settings, store
from test_settings import SettingsBase

HEADER = ("area_fips,own_code,industry_code,agglvl_code,size_code,year,qtr,disclosure_code,qtrly_estabs,month1_emplvl,month2_emplvl,"
          "month3_emplvl,total_qtrly_wages,taxable_qtrly_wages,qtrly_contributions,avg_wkly_wage,lq_disclosure_code,lq_qtrly_estabs,"
          "lq_month1_emplvl,lq_month2_emplvl,lq_month3_emplvl,lq_total_qtrly_wages,lq_taxable_qtrly_wages,lq_qtrly_contributions,"
          "lq_avg_wkly_wage,oty_disclosure_code,oty_qtrly_estabs_chg,oty_qtrly_estabs_pct_chg,oty_month1_emplvl_chg,"
          "oty_month1_emplvl_pct_chg,oty_month2_emplvl_chg,oty_month2_emplvl_pct_chg,oty_month3_emplvl_chg,oty_month3_emplvl_pct_chg,"
          "oty_total_qtrly_wages_chg,oty_total_qtrly_wages_pct_chg,oty_taxable_qtrly_wages_chg,oty_taxable_qtrly_wages_pct_chg,"
          "oty_qtrly_contributions_chg,oty_qtrly_contributions_pct_chg,oty_avg_wkly_wage_chg,oty_avg_wkly_wage_pct_chg")


def row(area, own, code, disclosure="", estabs=10, jobs=(100, 100, 100), wages=1_300_000, lq=1.0, changes=(0, 0, 0),
        wage_change=0, estab_change=0, quarter=1):
    fields = [area, own, code, "0", "0", "2026", str(quarter), disclosure, estabs, *jobs, wages, 0, 0, 0, "", 0, 0, 0, lq, 0, 0, 0, 0,
              "", estab_change, 0, changes[0], 0, changes[1], 0, changes[2], 0, wage_change, 0, 0, 0, 0, 0, 0, 0]
    return ",".join(str(f) for f in fields)


def csv(*rows):
    return ("\n".join([HEADER, *rows]) + "\n").encode()


AREA_TITLES = """area_fips,area_title
US000,U.S. TOTAL
55000,Wisconsin -- Statewide
55025,"Dane County, Wisconsin"
C3154,"Madison, WI MSA"
C3150,"Madera, CA MSA"
C4294,"Sandusky, OH MicroSA"
"""


class Codes(SettingsBase):
    def test_codes_are_saved_and_written_back_as_a_list(self):
        industry = {"name": "Robotics", "terms": [r"\brobots?\b"], "naics": ["333998", "3345"]}
        settings.save(self.body(industry=[industry]))
        saved = tomllib.loads(self.text())["promote"]["industry"][0]
        self.assertEqual(saved["naics"], ["333998", "3345"])
        self.assertIn('naics = ["333998", "3345"]', self.text())

    def test_a_code_that_isnt_one_is_refused(self):
        for bad in (["33a"], ["1"], ["1234567"], ["3332", "3332"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                settings.validate(self.form(industry=[{"name": "Robotics", "terms": ["robot"], "naics": bad}]))

    def test_a_code_inside_another_would_count_twice(self):
        with self.assertRaisesRegex(ValueError, "counted twice"):
            settings.validate(self.form(industry=[{"name": "Robotics", "terms": ["robot"], "naics": ["3332", "333248"]}]))

    def test_a_sector_range_is_a_code(self):
        promote = settings.validate(self.form(industry=[{"name": "Making", "terms": ["factory"], "naics": ["31-33"]}]))
        self.assertEqual(promote["industry"][0]["naics"], ["31-33"])


class Places(unittest.TestCase):
    def setUp(self):
        import csv as reader
        import io
        self.titles = {r["area_fips"]: r["area_title"] for r in reader.DictReader(io.StringIO(AREA_TITLES))}

    def test_a_state_by_name_or_code(self):
        self.assertEqual(market.find_state(self.titles, "wisconsin"), "55000")
        self.assertEqual(market.find_state(self.titles, "55"), "55000")
        with self.assertRaisesRegex(ValueError, "full name"):
            market.find_state(self.titles, "WI")

    def test_a_metro_by_name_code_or_cbsa(self):
        for wanted in ("Madison, WI", "madison, wi msa", "C3154", "31540", "Sandusky, OH"):
            with self.subTest(wanted=wanted):
                self.assertIn(market.find_metro(self.titles, wanted), ("C3154", "C4294"))

    def test_a_name_that_fits_two_metros_says_so(self):
        with self.assertRaisesRegex(ValueError, "more than one"):
            market.find_metro(self.titles, "Mad")

    def test_quarters_count_back_from_the_last_finished_one(self):
        self.assertEqual(market.quarters(date(2026, 11, 8), 3), [(2026, 3), (2026, 2), (2026, 1)])
        self.assertEqual(market.quarters(date(2026, 2, 1), 2), [(2025, 4), (2025, 3)])


class Combine(unittest.TestCase):
    def rows(self, *lines):
        return market._detail(csv(*lines))

    def test_codes_add_up_and_compare_with_a_year_before(self):
        rows = self.rows(
            row("55000", "5", "10", jobs=(1000, 1000, 1000), wages=13_000_000),
            row("55000", "5", "3332", jobs=(90, 100, 110), wages=1_950_000, lq=2.0, changes=(-10, 0, 10), wage_change=195_000, estab_change=1),
            row("55000", "5", "3345", estabs=5, jobs=(40, 40, 40), wages=780_000, lq=0.5, changes=(0, 0, -10), wage_change=0),
        )
        got = market.combine(rows, ["3332", "3345"])
        self.assertEqual((got["jobs"], got["estabs"], got["jobs_change"]), (150, 15, 0))
        self.assertEqual(got["jobs_change_pct"], 0.0)
        # (1,950,000 + 780,000) / 140 average jobs / 13 weeks
        self.assertEqual(got["weekly_pay"], 1500)
        self.assertEqual(got["pay_vs_all"], 150)
        # Harmonic: 150 / (110/2 + 40/0.5)
        self.assertEqual(got["concentration"], round(150 / (55 + 80), 2))
        self.assertEqual((got["withheld"], got["absent"]), ([], []))

    def test_withheld_and_missing_codes_are_named_not_added(self):
        rows = self.rows(row("55000", "5", "3332", jobs=(10, 10, 10)), row("55000", "5", "3345", disclosure="N", jobs=(0, 0, 0)))
        got = market.combine(rows, ["3332", "3345", "3361"])
        self.assertEqual((got["jobs"], got["withheld"], got["absent"]), (10, ["3345"], ["3361"]))
        self.assertEqual(got["estabs"], 20, "workplace counts are published even where jobs are withheld")
        nothing = market.combine(rows, ["3345"])
        self.assertNotIn("jobs", nothing)
        self.assertEqual(nothing["estabs"], 10)

    def test_placeholder_rows_are_not_numbers(self):
        rows = self.rows(row("C3154", "5", "3332", disclosure="-", jobs=(0, 0, 0)), row("C3154", "0", "10"))
        self.assertEqual(rows, {})


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(market, "cache_dir", lambda: Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_newest_quarter_with_detail_is_used_and_kept(self):
        files = {
            (2026, 3): None,  # not out yet
            (2026, 2): csv(row("C3154", "0", "10")),  # totals only
            (2026, 1): csv(row("C3154", "5", "3332", disclosure="-")),  # placeholders
            (2025, 4): csv(row("C3154", "5", "3332", jobs=(5, 6, 7))),
        }
        asked = []

        def download(url):
            year, quarter = url.split("/api/")[1].split("/")[:2]
            asked.append((int(year), int(quarter)))
            return files.get((int(year), int(quarter)))

        with mock.patch.object(market, "_download", download):
            first = market.area_numbers("C3154", date(2026, 11, 8))
            again = market.area_numbers("C3154", date(2026, 11, 9))
        self.assertEqual(first["quarter"], "2025Q4")
        self.assertEqual(first["rows"]["3332"]["months"], [5, 6, 7])
        self.assertEqual(again["quarter"], "2025Q4")
        self.assertEqual(len(asked), 4, "a second look within the week reads the copy on disk")

    def test_a_failed_check_falls_back_to_the_last_numbers_read(self):
        with mock.patch.object(market, "_download", lambda url: csv(row("55000", "5", "3332"))):
            market.area_numbers("55000", date(2026, 11, 8))

        def down(url):
            raise market.Unavailable("Couldn't reach the BLS.")

        with mock.patch.object(market, "_download", down):
            later = market.area_numbers("55000", date(2027, 1, 20))
            self.assertEqual(later["quarter"], "2026Q3")
            self.assertIn("last numbers read", later["note"])
            with self.assertRaises(market.Unavailable):
                market.area_numbers("C3154", date(2027, 1, 20))


class Seen(Base):
    def test_history_counts_this_industrys_postings_and_what_came_of_them(self):
        industry = {"name": "Robotics", "terms": [r"\brobots?\b"], "companies": ["Cyberdyne Research"]}
        today = date(2026, 11, 8)
        jobs = [
            {"company": "Cyberdyne Research", "title": "Engineer", "description": "", "location_kind": "local", "first_seen": "2026-11-01T00:00:00+00:00",
             "posting_closed_at": None, "applied_at": "2026-11-02", "response_at": "2026-11-05", "interview_at": None, "offer_at": None,
             "replied": 1},
            {"company": "Acme", "title": "Robot Software Lead", "description": "", "location_kind": "remote", "first_seen": "2026-09-20",
             "posting_closed_at": "2026-10-01", "applied_at": None, "response_at": None, "interview_at": None, "offer_at": None},
            {"company": "Acme", "title": "Accountant", "description": "", "location_kind": "local", "first_seen": "2026-11-01",
             "posting_closed_at": None, "applied_at": None, "response_at": None, "interview_at": None, "offer_at": None},
            {"company": "Acme", "title": "Robot Lead", "description": "", "location_kind": "local", "first_seen": "2026-01-01",
             "posting_closed_at": None, "applied_at": None, "response_at": None, "interview_at": None, "offer_at": None},
        ]
        got = market.history(jobs, industry, 3, today)
        self.assertEqual((got["recent"], got["by_month"], got["share"]), (2, [1, 1, 0], 67))
        self.assertEqual((got["open"], got["local"], got["remote"]), (2, 1, 1))
        self.assertEqual((got["applied"], got["replied"], got["interviews"]), (1, 1, 0))
        self.assertEqual(got["employers"], [("Cyberdyne Research", 1), ("Acme", 1)])

    def test_the_view_works_without_codes_and_without_reaching_the_bls(self):
        cfg = {**CFG, "promote": {**CFG["promote"], "industry": [{"name": "Robotics", "terms": ["robot"]}]}}
        with mock.patch.object(market, "_download", side_effect=AssertionError("no download")):
            view = market.view(self.conn, cfg)
        self.assertEqual([i["name"] for i in view["industries"]], ["Robotics"])
        self.assertEqual(view["industries"][0]["official"], [])

    def test_codes_written_as_numbers_read_as_codes(self):
        # naics = [333998], without quotes, is what someone writing search.toml by hand often types.
        cfg = {**CFG, "promote": {**CFG["promote"], "industry": [{"name": "Robotics", "terms": ["robot"], "naics": [333998]}]}}
        fakes = {"areas": lambda cfg: ([{"code": "55000", "level": "state", "name": "Wisconsin"}], []),
                 "industry_titles": lambda: {"333998": "NAICS 333998 All other general purpose machinery manufacturing"},
                 "area_numbers": lambda code, today=None: {"quarter": "2026Q1", "rows": market._detail(csv(row("55000", "5", "333998")))}}
        with contextlib.ExitStack() as stack:
            for name, fake in fakes.items():
                stack.enter_context(mock.patch.object(market, name, fake))
            view = market.view(self.conn, cfg)
        robotics = view["industries"][0]
        self.assertEqual(robotics["codes"], [{"code": "333998", "title": "All other general purpose machinery manufacturing"}])
        self.assertEqual(robotics["official"][0]["jobs"], 100)
        self.assertIn("(NAICS): 333998", outlook.prompt("Robotics", cfg["promote"]["industry"][0], {}, [], "2026-11-08"))

    def test_a_rejection_isnt_a_reply_here_either(self):
        # The same rule as the dashboard's Reply rate, so the two never disagree.
        cfg = {**CFG, "promote": {**CFG["promote"], "industry": [{"name": "Robotics", "terms": ["robot"]}]}}
        heard = {"applied_at": "2026-11-02T00:00:00+00:00", "response_at": "2026-11-05T00:00:00+00:00"}
        self.add(title="Robot Lead", source_id="a", status="rejected", **heard)
        replied = self.add(title="Robot Engineer", source_id="b", status="responded", **heard)
        store.log_event(self.conn, replied, "responded", "")
        with mock.patch.object(market, "_download", side_effect=AssertionError("no download")):
            seen = market.view(self.conn, cfg)["industries"][0]["seen"]
        self.assertEqual((seen["applied"], seen["replied"]), (2, 1))


SOURCES = [
    {"id": 1, "title": "Plant expands", "publisher": "Gazette", "url": "https://www.example-news.com/plant-expands/", "date": "2026-10-01"},
    {"id": 2, "title": "Invented", "publisher": "Nobody", "url": "https://made-up.example/story", "date": "October"},
    {"id": 3, "title": "State data", "publisher": "DWD", "url": "https://dwd.example.gov/report#jobs", "date": "2026-09"},
]


def answer(**changes):
    return json.dumps({"sections": [
        {"heading": "In short", "points": [
            {"text": "A plant is expanding.", "scope": "metro", "sources": [1]},
            {"text": "Something unconfirmed.", "scope": "state", "sources": [2]},
            {"text": "Uncited.", "scope": "state", "sources": []},
        ]},
        {"heading": "Headwinds", "points": [{"text": "State jobs fell.", "scope": "planet", "sources": [3, 2]}]},
        {"heading": "Made up heading", "points": [{"text": "Ignored.", "sources": [1]}]},
    ], "sources": SOURCES, **changes})


SEEN = ["https://example-news.com/plant-expands", "https://dwd.example.gov/report"]
# A WebSearch result as Claude Code's stream gives it, listing those two pages.
SEARCH_RESULT = "Web search results for query: \"plant\"\n\nLinks: " + json.dumps([{"title": "Page", "url": url} for url in SEEN])


class Vetting(unittest.TestCase):
    def test_only_points_whose_sources_this_run_found_are_kept(self):
        sections, sources, dropped = outlook.vet("Here it is:\n" + answer(), SEEN)
        self.assertEqual([s["heading"] for s in sections], ["In short", "Headwinds"])
        self.assertEqual([p["text"] for p in sections[0]["points"]], ["A plant is expanding."])
        self.assertEqual(sections[1]["points"][0], {"text": "State jobs fell.", "scope": "", "sources": [2]})
        self.assertEqual([(s["n"], s["title"], s["date"]) for s in sources], [(1, "Plant expands", "2026-10-01"), (2, "State data", "2026-09")])
        self.assertEqual(dropped, {"points": 2, "sources": 1})

    def test_a_link_that_isnt_a_web_page_is_dropped(self):
        bad = [{"id": 1, "title": "x", "url": "javascript:alert(1)//example-news.com/plant-expands"}]
        sections, sources, _ = outlook.vet(answer(sources=bad), [*SEEN, "javascript:alert(1)//example-news.com/plant-expands"])
        self.assertEqual((sections, sources), ([], []))

    def test_a_source_counts_only_as_the_whole_address_the_run_came_across(self):
        seen = ["https://www.news.example/business/acme-opens-plant-2026-10-01/"]
        sources = [{"id": 1, "url": "https://news.example"}, {"id": 2, "url": "https://www.news.example/business/acme"},
                   {"id": 3, "url": "https://elsewhere.example/whatever"},
                   {"id": 4, "url": "http://news.example/business/acme-opens-plant-2026-10-01#top"}]
        points = [{"text": f"Point {i}.", "scope": "metro", "sources": [i]} for i in (1, 2, 3, 4)]
        data = {"sections": [{"heading": "In short", "points": points}], "sources": sources}
        sections, kept, dropped = outlook.vet(json.dumps(data), seen)
        self.assertEqual([s["url"] for s in kept], [sources[3]["url"]])
        self.assertEqual([p["text"] for p in sections[0]["points"]], ["Point 4."])
        self.assertEqual(dropped, {"points": 3, "sources": 3})

    def test_an_answer_of_the_wrong_shape_is_left_out_not_trusted(self):
        for data in ({"sections": [], "sources": 5},
                     {"sections": [{"heading": "In short", "points": [{"text": "x", "sources": 1}]}], "sources": [{"id": 1, "url": SEEN[0]}]},
                     {"sections": [{"heading": ["In short"], "points": []}], "sources": []},
                     {"sections": "none", "sources": {"id": 1}},
                     {"sections": [{"heading": "In short", "points": "x"}], "sources": [{"id": 1, "url": SEEN[0]}]}):
            with self.subTest(data=data):
                self.assertEqual(outlook.vet(json.dumps(data), SEEN)[:2], ([], []))

    def test_an_answer_with_no_json_fails(self):
        with self.assertRaises(outlook.ClaudeFailed):
            outlook.vet("I couldn't find anything.", SEEN)

    def test_the_stream_gives_the_answer_and_what_the_tools_saw(self):
        lines = [
            {"type": "system", "subtype": "init"},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "f1", "name": "WebFetch", "input": {"url": "https://fetched.example/a", "prompt": "x"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "f1", "content": "The page says see https://mentioned.example/c"}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "s1", "name": "WebSearch", "input": {"query": "plant"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "s1", "content": [
                {"type": "text", "text": 'Links: [{"title": "B", "url": "https://found.example/b"}] and a summary naming https://said.example/d'}]}]},
             "tool_use_result": {"query": "plant", "results": [{"tool_use_id": "x", "content": [{"title": "E", "url": "https://listed.example/e"}]}, "text"]}},
            {"type": "result", "result": "{}", "is_error": False, "usage": {"output_tokens": 5}},
        ]
        text, result, seen = outlook.read_stream("\n".join(json.dumps(line) for line in lines) + "\nnot json")
        self.assertEqual((text, result["usage"]["output_tokens"]), ("{}", 5))
        self.assertEqual(seen, {"https://fetched.example/a", "https://found.example/b", "https://listed.example/e"})


class Research(Base):
    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.folder.cleanup)
        for target, value in ((outlook, "folder"), (market, "areas")):
            patcher = mock.patch.object(target, value, {
                "folder": lambda: Path(self.folder.name),
                "areas": lambda cfg: ([{"code": "55000", "level": "state", "name": "Wisconsin"}], []),
            }[value])
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(market, "area_numbers", lambda code, today=None: {"quarter": "2026Q1", "rows": market._detail(csv(row("55000", "5", "334413")))})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stream(self, final, seen=SEARCH_RESULT, code=0):
        lines = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "s1", "name": "WebSearch", "input": {"query": "plant"}}]}},
                 {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "s1", "content": seen}]}},
                 {"type": "result", "result": final, "is_error": bool(code), "num_turns": 4, "total_cost_usd": 0.4}]
        return subprocess.CompletedProcess([], code, stdout="\n".join(json.dumps(line) for line in lines), stderr="")

    def test_a_sourced_outlook_is_kept_and_the_run_is_counted(self):
        with mock.patch.object(outlook.claude_code, "run_process", return_value=self.stream(answer())) as ran:
            report = outlook.run(self.conn, CFG, "Semiconductors", claude="claude")
        cmd, prompt = ran.call_args.args[0], ran.call_args.kwargs["input"]
        self.assertEqual(cmd[cmd.index("--tools") + 1], "WebSearch,WebFetch")
        self.assertIn("Read", cmd[cmd.index("--disallowedTools") + 1])
        self.assertIn("never instructions", prompt)
        self.assertIn("Wisconsin, 2026 Q1: 100 private-sector jobs", prompt)
        self.assertEqual(report["area"]["state"], "Wisconsin")
        status = outlook.status("Semiconductors")
        self.assertEqual((status["state"], len(status["report"]["sections"])), ("done", 2))
        runs = self.conn.execute("SELECT kind, ok, cost_usd FROM claude_runs").fetchall()
        self.assertEqual([tuple(r) for r in runs], [("outlook", 1, 0.4)])

    def test_a_failed_redo_keeps_the_last_outlook(self):
        with mock.patch.object(outlook.claude_code, "run_process", return_value=self.stream(answer())):
            outlook.run(self.conn, CFG, "Semiconductors", claude="claude")
        with mock.patch.object(outlook.claude_code, "run_process", return_value=self.stream(answer(), seen="nothing relevant")), \
                self.assertRaisesRegex(outlook.ClaudeFailed, "actually found"):
            outlook.run(self.conn, CFG, "Semiconductors", claude="claude")
        status = outlook.status("Semiconductors")
        self.assertEqual(status["state"], "failed")
        self.assertIsNotNone(status["report"])

    def test_trouble_of_any_kind_finishes_the_research_as_failed(self):
        malformed = json.dumps({"sections": [{"heading": ["In short"], "points": 3}], "sources": 5})
        with mock.patch.object(outlook.claude_code, "run_process", return_value=self.stream(malformed)), \
                self.assertRaises(outlook.ClaudeFailed):
            outlook.run(self.conn, CFG, "Semiconductors", claude="claude")
        self.assertEqual(outlook.status("Semiconductors")["state"], "failed")
        with mock.patch.object(outlook.claude_code, "run_process", return_value=self.stream(answer())), \
                mock.patch.object(outlook, "vet", side_effect=KeyError("url")), self.assertRaises(KeyError):
            outlook.run(self.conn, CFG, "Semiconductors", claude="claude")
        status = outlook.status("Semiconductors")
        self.assertEqual(status["state"], "failed")
        self.assertIn("KeyError", status["detail"])

    def test_the_button_refuses_an_unknown_industry_and_a_second_run(self):
        with self.assertRaisesRegex(ValueError, "no industry"):
            outlook.start(CFG, "Knitting")
        outlook.begin("Robotics")
        with self.assertRaisesRegex(ValueError, "already"):
            outlook.start(CFG, "Robotics")

    def test_the_dashboard_starts_it_in_the_background(self):
        with mock.patch.object(outlook, "find_claude", return_value="claude"), \
                mock.patch.object(outlook.claude_code, "signed_in", return_value=True), \
                mock.patch.object(outlook.subprocess, "Popen") as popen:
            outlook.start(CFG, "Robotics")
        args = popen.call_args.args[0]
        self.assertEqual(args[-3:], ["outlook", "Robotics", "--worker"])
        self.assertEqual(outlook.status("Robotics")["state"], "running")

    def test_the_api_lists_every_industry(self):
        with mock.patch.object(market, "industry_titles", return_value={"334413": "NAICS 334413 Semiconductor and related device manufacturing"}):
            view = market.view(self.conn, CFG)
        names = [i["name"] for i in view["industries"]]
        self.assertEqual(names, [i["name"] for i in CFG["promote"]["industry"]])
        semis = next(i for i in view["industries"] if i["name"] == "Semiconductors")
        self.assertEqual(semis["codes"][0]["title"], "Semiconductor and related device manufacturing")
        self.assertEqual(semis["official"][0]["jobs"], 100)
        self.assertEqual(semis["official"][0]["absent"], ["333242"])


if __name__ == "__main__":
    unittest.main()
