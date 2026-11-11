"""Moving for a job: the tax model, reading a posting's place, and what a range elsewhere is worth at home.

The prices here are a made-up table of fictional towns in real states, so the numbers are easy to check by hand and no
test depends on what BEA publishes next. One test reads the shipped table only for its shape.
"""
import contextlib
import io
import json
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path

from support import CFG, Base

from pyrite import cli, options, prices, relocate, store, taxes
from pyrite.score import US_STATES
from test_settings import SETTINGS_TOML, SettingsBase

FIXTURE = {
    "about": "Fictional", "year": 2024, "released": "February 19, 2026", "fetched": "2026-11-11",
    "source": {"prices": "https://example.test/rpp", "cities": "https://example.test/cities"},
    "columns": ["all items", "housing (rents)"], "housing_weight": 0.2, "us": [100.0, 100.0],
    "states": {"WI": [95.0, 90.0], "CA": [110.0, 150.0], "TX": [97.0, 100.0], "IN": [92.0, 80.0], "IL": [99.0, 95.0],
               "MO": [91.0, 75.0]},
    "metros": [
        ["90001", "Madison, WI", 100.0, 100.0, ["Madison|WI"]],
        ["90002", "Sunnydale-Hill Valley, CA", 120.0, 200.0, ["Sunnydale|CA", "Hill Valley|CA", "Eagle Rock|CA"]],
        ["90003", "Pawnee-Eagleton, IN", 90.0, 70.0, ["Pawnee|IN", "Eagleton|IN"]],
        ["90004", "Springfield-Shelbyville, MO-IL", 95.0, 85.0, []],
        ["90005", "Arlen, TX", 100.0, 100.0, ["Arlen|TX"]],
    ],
}


class FictionalPrices(unittest.TestCase):
    """Every test here reads the fixture's prices, not the shipped ones."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "rpp.json"
        path.write_text(json.dumps(FIXTURE), encoding="utf-8")
        patcher = mock.patch.object(prices, "DATA", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        for cached in (prices.data, prices._areas):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    @staticmethod
    def config(**relocation):
        return {**CFG, "market": {"state": "Wisconsin", "metro": "Madison, WI"}, "relocation": relocation}


class Places(FictionalPrices):
    def test_a_principal_city_finds_its_metro_however_the_location_is_written(self):
        for location in ("Hill Valley, CA", "Hill Valley, California", "US-CA-Hill Valley", "Hybrid - Hill Valley, CA | Remote",
                         "Hill Valley, CA, United States", "Hill Valley, CA 90210", "Eagle Rock, CA (Onsite)", "Greater Hill Valley Area"):
            with self.subTest(location=location):
                found = prices.find(location)
                self.assertEqual((found.area.code, found.state), ("90002", "CA"))

    def test_a_town_in_no_metro_falls_back_to_its_state(self):
        found = prices.find("Twin Peaks, CA")
        self.assertEqual((found.area.kind, found.area.code, found.state, found.city), ("state", "CA", "CA", "Twin Peaks"))
        self.assertEqual(prices.find("Texas").area.code, "TX")

    def test_the_state_written_decides_taxes_in_a_metro_across_two(self):
        # The metro lists no principal cities, so the names in its title stand in, in either of its states.
        self.assertEqual((prices.find("Shelbyville, IL").area.code, prices.find("Shelbyville, IL").state), ("90004", "IL"))
        self.assertEqual(prices.find("Springfield, MO").state, "MO")

    def test_a_city_alone_is_placed_only_when_one_metro_could_be_it(self):
        self.assertEqual(prices.find("Pawnee").area.code, "90003")
        self.assertIsNone(prices.find("Springfield"))  # In both of its metro's states, so which state's taxes is unknown.

    def test_the_first_place_in_a_metro_wins(self):
        found = prices.find("Twin Peaks, CA | Pawnee, IN")
        self.assertEqual((found.area.code, found.said, found.places), ("90003", "Pawnee, IN", 2))

    def test_nowhere_it_can_place(self):
        for location in ("Remote - US", "", "Paris, France", "3 Locations"):
            with self.subTest(location=location):
                self.assertIsNone(prices.find(location))

    def test_home_by_its_bls_name_code_or_a_principal_city(self):
        for wanted in ("Madison, WI", "Madison, WI MSA", "90001", "Madison WI"):
            with self.subTest(wanted=wanted):
                self.assertEqual(prices.find_metro(wanted).code, "90001")
        self.assertEqual(prices.find_metro("Eagleton, IN").code, "90003")
        self.assertIsNone(prices.find_metro("Atlantis, ZZ"))

    def test_the_price_of_everything_but_housing(self):
        area = prices.metro("90002")  # 120 all items and 200 housing, with housing at 0.2 of all items.
        self.assertAlmostEqual(area.without_housing(0.2), 100.0)


class ShippedPrices(unittest.TestCase):
    def test_the_shipped_table_has_every_state_and_the_metros(self):
        data = json.loads(prices.DATA.read_text(encoding="utf-8"))
        self.assertEqual(set(data["states"]), set(US_STATES))
        self.assertGreater(len(data["metros"]), 350)
        self.assertGreaterEqual(data["year"], 2024)
        self.assertTrue(0.05 < data["housing_weight"] < 0.4)
        for code, name, all_items, housing, cities in data["metros"]:
            self.assertRegex(code, r"^\d{5}$")
            self.assertTrue(50 < all_items < 200 and 20 < housing < 400, name)
            self.assertTrue(all("|" in city for city in cities), name)


class Taxes(unittest.TestCase):
    def test_brackets_charge_each_rate_only_past_its_start(self):
        table = ((0, .10), (10_000, .20), (20_000, .30))
        self.assertEqual(taxes.bracket_tax(10_000, table), 1_000)
        self.assertAlmostEqual(taxes.bracket_tax(10_001, table), 1_000.20)
        self.assertEqual(taxes.bracket_tax(30_000, table), 1_000 + 2_000 + 3_000)
        self.assertEqual(taxes.bracket_tax(0, table), 0)
        self.assertEqual(taxes.bracket_tax(5_000, ((10_000, .04),)), 0)  # A first bracket that starts above nothing.

    def test_federal_income_tax_at_its_edges(self):
        self.assertEqual(taxes.federal_income_tax(16_100), 0)  # All of it the standard deduction.
        self.assertAlmostEqual(taxes.federal_income_tax(16_100 + 12_400), 1_240)  # The top of the 10% bracket.
        self.assertAlmostEqual(taxes.federal_income_tax(16_100 + 12_401), 1_240.12)
        self.assertAlmostEqual(taxes.federal_income_tax(32_200 + 24_800, "married"), 2_480)

    def test_social_security_stops_at_its_wage_base_and_medicare_never_does(self):
        base = taxes.SOCIAL_SECURITY_BASE
        self.assertAlmostEqual(taxes.fica(base), base * .0765)
        self.assertAlmostEqual(taxes.fica(base + 10_000) - taxes.fica(base), 10_000 * .0145)
        # The extra 0.9% Medicare, from $200k single and $250k married.
        self.assertAlmostEqual(taxes.fica(210_000) - taxes.fica(200_000), 10_000 * (.0145 + .009))
        self.assertAlmostEqual(taxes.fica(210_000, "married") - taxes.fica(200_000, "married"), 10_000 * .0145)

    def test_every_state_and_dc_has_a_table_in_order(self):
        self.assertEqual(set(taxes.STATES), set(US_STATES))
        for abbr, rules in taxes.STATES.items():
            for brackets in (rules.single, rules.married or ()):
                starts = [start for start, _rate in brackets]
                with self.subTest(state=abbr):
                    self.assertEqual(starts, sorted(starts))
                    self.assertTrue(all(0 <= rate < .15 for _start, rate in brackets))
                    self.assertIn(rules.year, (2025, 2026))

    def test_no_tax_on_wages_where_there_is_none(self):
        for abbr in ("TX", "FL", "WA", "NH"):
            self.assertEqual(taxes.state_income_tax(250_000, abbr), 0)

    def test_a_standard_deduction_that_phases_out(self):
        # Wisconsin's is gone by $136,453 single, so past that every dollar but the exemption is taxed.
        rules = taxes.STATES["WI"]
        self.assertEqual(taxes.state_taxable(136_453, "WI"), 136_453 - 700)
        self.assertEqual(taxes.state_taxable(20_119, "WI"), 20_119 - 13_960 - 700)
        self.assertEqual(rules.deduction, (13_960, 25_840))

    def test_a_credit_that_ends_at_a_cliff(self):
        # Oregon's personal credit isn't allowed over $100k single.
        under, over = taxes.state_income_tax(100_000, "OR"), taxes.state_income_tax(100_001, "OR")
        self.assertAlmostEqual(over - under, 256 + .0875, places=2)

    def test_new_yorks_recapture_taxes_all_of_a_high_income_at_its_bracket_rate(self):
        wages = 180_000  # Past $157,650, and taxable income inside the 5.9% bracket.
        taxable = taxes.state_taxable(wages, "NY")
        self.assertAlmostEqual(taxes.state_income_tax(wages, "NY"), taxable * .059)
        below = 100_000  # Under $107,650: the brackets as they are.
        self.assertAlmostEqual(taxes.state_income_tax(below, "NY"),
                               taxes.bracket_tax(taxes.state_taxable(below, "NY"), taxes.STATES["NY"].single))

    def test_connecticuts_recaptures_stop_at_their_caps(self):
        plain = lambda wages: taxes.bracket_tax(taxes.state_taxable(wages, "CT"), taxes.STATES["CT"].single)
        # By $400k the 2% bracket is all at 4.5% ($250), the first recapture is at its $250 and the second at its $3,150.
        self.assertAlmostEqual(taxes.state_income_tax(400_000, "CT") - plain(400_000), 250 + 250 + 3_150)

    def test_payroll_taxes_with_and_without_a_cap(self):
        base = taxes.SOCIAL_SECURITY_BASE
        oregon = dict(taxes.payroll_taxes(base + 50_000, "OR"))
        self.assertAlmostEqual(oregon["Paid Leave Oregon"], base * .006)
        self.assertAlmostEqual(oregon["Statewide transit tax"], (base + 50_000) * .001)
        self.assertAlmostEqual(dict(taxes.payroll_taxes(500_000, "CA"))["State disability insurance"], 500_000 * .013)
        self.assertEqual(taxes.payroll_taxes(500_000, "TX"), [])

    def test_local_taxes_by_city_or_statewide(self):
        self.assertEqual(taxes.local_for("NY", "Brooklyn"), ["nyc"])
        self.assertEqual(taxes.local_for("PA", "Philadelphia"), ["philadelphia"])
        self.assertEqual(taxes.local_for("PA", "Twin Peaks"), ["pa"])
        self.assertEqual(taxes.local_for("TX", "Arlen"), [])
        # A district's tax over a threshold of state taxable income.
        result = taxes.take_home(150_000, "OR", "single", ["metro-shs"])
        taxable = taxes.state_taxable(150_000, "OR", "single", result.federal)
        self.assertAlmostEqual(result.local, (taxable - 125_000) * .01)
        self.assertTrue(all(tax.state in US_STATES for tax in taxes.LOCAL.values()))

    def test_take_home_adds_up(self):
        result = taxes.take_home(120_000, "CA", "single")
        self.assertAlmostEqual(result.net, 120_000 - sum(amount for _label, amount in result.lines))
        with self.assertRaisesRegex(ValueError, "No tax table"):
            taxes.take_home(1, "ZZ")

    def test_solving_for_wages_finds_the_take_home_asked_for(self):
        for state, local in (("CA", []), ("TX", []), ("NY", ["nyc"]), ("WI", [])):
            with self.subTest(state=state):
                wages = taxes.solve_wages(100_000, state, "single", local)
                self.assertAlmostEqual(taxes.take_home(wages, state, "single", local).net, 100_000, delta=1)


class Comparison(FictionalPrices):
    def job(self, location, comp="", kind="elsewhere"):
        return {"location": location, "location_kind": kind, "comp": comp}

    def test_at_the_same_prices_and_taxes_the_break_even_is_your_own_pay(self):
        result = relocate.for_job(self.job("Pawnee, IN", "$100,000"), self.config(current_pay=100_000))
        home = relocate.Home(prices.metro("90003"), "IN", ("in",), 100_000, "single", "rent", .3)
        same = relocate.compare(prices.find("Eagleton, IN"), "", {}, home)
        self.assertEqual([view["break_even"] for view in same["views"]], [100_000, 100_000])
        self.assertIn("views", result)

    def test_the_break_even_scales_home_take_home_by_the_price_ratio(self):
        cfg = self.config(current_pay=150_000, housing="own")
        result = relocate.for_job(self.job("Hill Valley, CA", "$165k - $215k"), cfg)
        home_net = taxes.take_home(150_000, "WI").net
        views = {view["id"]: view for view in result["views"]}
        self.assertEqual(result["lead"], "all")
        self.assertEqual(result["views"][0]["id"], "all")
        self.assertAlmostEqual(views["all"]["ratio"], 1.2)
        # Renting: 30% at the housing ratio, 200 over 100, and 70% at the ratio without housing, (120 - 40) / 0.8 over
        # (100 - 20) / 0.8, which is 1: all of Hill Valley's higher prices are in its housing.
        self.assertAlmostEqual(views["rent"]["ratio"], .3 * 2.0 + .7 * 1.0)
        for view in views.values():
            there = taxes.take_home(view["break_even"], "CA", "single", taxes.local_for("CA", "Hill Valley")).net
            self.assertAlmostEqual(there / view["ratio"], home_net, delta=100)

    def test_the_range_in_home_dollars(self):
        result = relocate.for_job(self.job("Arlen, TX", "$165,000 - $215,000 a year, plus equity"), self.config(current_pay=150_000))
        home_net = taxes.take_home(150_000, "WI").net
        points = result["views"][0]["points"]
        self.assertEqual([(p["label"], p["pay"]) for p in points], [("Bottom", 165_000), ("Middle", 190_000), ("Top", 215_000)])
        # Arlen's prices are Madison's, so a dollar there is a dollar at home: only the taxes differ.
        self.assertEqual(points[0]["worth"], round(taxes.take_home(165_000, "TX").net))
        self.assertAlmostEqual(points[1]["change"], taxes.take_home(190_000, "TX").net / home_net - 1, places=3)
        self.assertIn("The middle of its range, $190k, is worth", result["summary"])
        self.assertIn(relocate.NOT_COUNTED, result["notes"])

    def test_a_posting_with_no_pay_range_still_gets_its_break_even(self):
        result = relocate.for_job(self.job("Hill Valley, CA"), self.config(current_pay=150_000))
        self.assertIsNone(result["range"])
        self.assertTrue(all(view["points"] == [] and view["break_even"] > 150_000 for view in result["views"]))
        self.assertIn("gives no pay range", result["summary"])

    def test_a_range_in_another_currency_isnt_turned_into_dollars(self):
        result = relocate.for_job(self.job("Hill Valley, CA", "CA$200K – CA$250K"), self.config(current_pay=150_000))
        self.assertEqual(result["views"][0]["points"], [])
        self.assertIn("in CAD", result["summary"])

    def test_remote_local_and_same_metro_jobs_arent_compared(self):
        cfg = self.config(current_pay=150_000)
        self.assertIsNone(relocate.for_job(self.job("Remote - US", "$200k", "remote"), cfg))
        self.assertIsNone(relocate.for_job(self.job("Madison, WI", "$200k", "local"), cfg))
        self.assertIsNone(relocate.for_job(self.job("Madison, WI", "$200k", "unknown"), cfg))
        self.assertIsNone(relocate.for_job(self.job("", "$200k", "unknown"), cfg))

    def test_what_stops_a_comparison_is_said(self):
        self.assertIn("current pay", relocate.for_job(self.job("Hill Valley, CA"), self.config())["problem"])
        self.assertIn("couldn't tell where", relocate.for_job(self.job("Springfield"), self.config(current_pay=1))["problem"])
        no_home = {**CFG, "market": {}, "relocation": {"current_pay": 100_000}}
        self.assertIn("[market]", relocate.for_job(self.job("Hill Valley, CA"), no_home)["problem"])
        abroad = {**CFG, "market": {"country": "Canada"}, "relocation": {"current_pay": 100_000}}
        self.assertIn("United States only", relocate.for_job(self.job("Hill Valley, CA"), abroad)["problem"])

    def test_home_local_taxes_default_to_the_states_own_and_can_be_named(self):
        indiana = {**CFG, "market": {"state": "Indiana"}, "relocation": {"current_pay": 100_000}}
        self.assertEqual(relocate.home(indiana).local, ("in",))
        indiana["relocation"]["home_local_taxes"] = ["indianapolis"]
        self.assertEqual(relocate.home(indiana).local, ("indianapolis",))
        indiana["relocation"]["home_local_taxes"] = []
        self.assertEqual(relocate.home(indiana).local, ())

    def test_settings_that_cant_be_used_are_named(self):
        bad = {"relocation": {"filing": "joint", "housing": "lease", "housing_share": 130, "home_local_taxes": ["atlantis"]}}
        found = " ".join(relocate.problems(bad))
        for words in ("filing under [relocation]", "housing under [relocation]", "housing_share", "'atlantis'"):
            self.assertIn(words, found)
        self.assertIn("current_pay under [relocation]", " ".join(store.config_problems({**CFG, "relocation": {"current_pay": "lots"}})))
        self.assertEqual(relocate.problems(CFG), [])


class Command(FictionalPrices, Base):
    def setUp(self):
        FictionalPrices.setUp(self)
        Base.setUp(self)
        patcher = mock.patch.object(store, "DB_PATH", Path(self.tmp.name) / "t.db")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(cli, "load_config", return_value=self.config(current_pay=150_000))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["relocate", *argv])
        return out.getvalue()

    def test_a_place_and_pay(self):
        printed = json.loads(self.run_cli("--where", "Hill Valley, CA", "--pay", "$200k", "--json"))
        self.assertEqual(printed["there"]["name"], "Sunnydale-Hill Valley, CA")
        self.assertEqual(printed["range"], {"low": 200_000, "high": 200_000, "currency": "USD"})
        self.assertEqual(printed["views"][0]["points"][0]["label"], "Stated pay")

    def test_a_tracked_job(self):
        job = self.add(location="Pawnee, IN", location_kind="elsewhere", comp="$140,000 - $160,000")
        self.conn.commit()
        printed = json.loads(self.run_cli(str(job), "--json"))
        self.assertEqual(printed["there"]["said"], "Pawnee, IN")
        remote = self.add(source_id="2", location="Remote - US", location_kind="remote")
        self.conn.commit()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            cli.main(["relocate", str(remote)])
        self.assertIn("doesn't ask you to move", str(caught.exception.code))

    def test_the_local_taxes_it_knows(self):
        listed = self.run_cli("--taxes")
        self.assertIn("nyc", listed)
        self.assertIn("home_local_taxes", listed)


class RelocationSettings(SettingsBase):
    def save(self, **values):
        return options.save({"version": options.view()["version"], "values": {name.replace("__", "."): value for name, value in values.items()}})

    def test_the_settings_tab_writes_relocation(self):
        self.save(relocation__current_pay=135_000, relocation__filing="married", relocation__housing="own")
        cfg = store.load_config()
        self.assertEqual(cfg["relocation"], {"current_pay": 135_000, "filing": "married", "housing": "own"})
        for line in SETTINGS_TOML.splitlines():
            self.assertIn(line, self.text())
        with self.assertRaisesRegex(ValueError, "Filing status"):
            self.save(relocation__filing="joint")
        with self.assertRaisesRegex(ValueError, "Share of spending on housing"):
            self.save(relocation__housing_share=95)
        self.assertEqual(tomllib.loads(self.text())["relocation"]["filing"], "married")


if __name__ == "__main__":
    unittest.main()
