"""Companies to watch, the Profile tab section: Check by hand changed an entry at a time, the board addresses a pasted
careers page may name, and how many pages each Workday search reads. Nothing here reaches the network."""
import shutil
import tempfile
import tomllib
import unittest
import unittest.mock as mock
from pathlib import Path
from typing import Any

import support  # noqa: F401  Points Pyrite at a throwaway workspace before it loads.

from pyrite import discover, profile, server, sources, steps, store

EXAMPLE_PROFILE = store.EXAMPLE_ROOT / "profile"

# Three companies checked by hand, with comments above, between and after them.
MANUAL = """\
# Employers worth watching with no public feed.
[[manual_check]]
name = "LinkedIn"
url = "https://www.linkedin.com/jobs/"
why = "Its terms forbid automated collection"

# Initech posts only on its own site.
[[manual_check]]
name = "Initech"  # the parent company
url = "https://careers.initech.example/"
# Asked about this one in October.
why = "No board"

# Globex: check Mondays.
[[manual_check]]
name = "Globex"
url = "https://globex.example/jobs"

"""


class Section(unittest.TestCase):
    """A throwaway copy of the example profile, and the section's form as the page first sends it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        shutil.copytree(EXAMPLE_PROFILE, self.root / "profile")
        for patcher in (mock.patch.object(store, "ROOT", self.root), mock.patch.object(store, "IS_EXAMPLE", False)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.view = {**profile.view(), **steps.view()}

    def draft(self, edits: dict[str, Any]) -> dict[str, Any]:
        return steps.draft("companies", edits, self.view["versions"])

    def save(self, result: dict[str, Any]) -> None:
        profile.write(result["changes"], self.view["versions"], "test")
        self.view = {**profile.view(), **steps.view()}

    def config(self) -> str:
        return profile.read("config")

    def rewrite(self, text: str) -> None:
        (self.root / "profile" / "search.toml").write_bytes(text.encode())
        self.view = {**profile.view(), **steps.view()}

    def form(self, **change) -> dict[str, Any]:
        companies = self.view["companies"]
        return {
            "boards": [{part: board[part] for part in ("was", "kind", "key", "name", "wd", "site", "eu")} for board in companies["boards"]],
            "manual": [dict(entry) for entry in companies["manual"]],
            "queries": list(companies["queries"]),
            "paste": "",
            **change,
        }


class CheckByHand(Section):
    """[[manual_check]] changed an entry at a time: the comments between entries stay."""

    def setUp(self):
        super().setUp()
        text = self.config().replace("\r\n", "\n")
        start = text.index("# Employers worth watching")
        end = text.index("# Company watchlist")
        self.before = text[:start] + MANUAL + text[end:]
        self.rewrite(self.before)

    def written(self, result: dict[str, Any]) -> str:
        return result["changes"]["config"]

    def test_an_unchanged_form_changes_nothing(self):
        result = self.draft(self.form())
        self.assertEqual((result["changes"], result["count"]), ({}, 0))

    def test_changing_one_entry_keeps_every_other_byte(self):
        manual = self.form()["manual"]
        manual[1]["why"] = "Its own site only"
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.written(result), self.before.replace('why = "No board"', 'why = "Its own site only"'))
        manual[1]["why"] = ""
        manual[2]["why"] = "Mondays"
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 2)
        self.assertEqual(self.written(result), self.before.replace('why = "No board"\n', "").replace(
            'url = "https://globex.example/jobs"\n', 'url = "https://globex.example/jobs"\nwhy = "Mondays"\n'))
        # A key the form doesn't show stays, and so does the comment beside a key it changes.
        manual = self.form()["manual"]
        manual[1]["name"] = "Initech Labs"
        result = self.draft(self.form(manual=manual))
        self.assertIn('name = "Initech Labs"  # the parent company\n', self.written(result))

    def test_one_taken_off_goes_with_its_own_lines(self):
        manual = self.form()["manual"]
        result = self.draft(self.form(manual=[manual[0], manual[2]]))
        self.assertEqual(result["count"], 1)
        middle = self.before.index("# Initech posts")
        self.assertEqual(self.written(result),
                         self.before[:middle] + self.before[self.before.index("# Globex: check Mondays."):])
        result = self.draft(self.form(manual=manual[:2]))
        self.assertEqual(self.written(result), self.before.replace(
            '# Globex: check Mondays.\n[[manual_check]]\nname = "Globex"\nurl = "https://globex.example/jobs"\n\n', ""))
        result = self.draft(self.form(manual=manual[1:]))
        self.assertEqual(self.written(result), self.before.replace(
            '[[manual_check]]\nname = "LinkedIn"\nurl = "https://www.linkedin.com/jobs/"\n'
            'why = "Its terms forbid automated collection"\n\n', "", 1))

    def test_a_new_one_goes_after_the_last(self):
        manual = [{"at": None, "name": "Hooli", "url": "hooli.example/careers", "why": ""}] + self.form()["manual"]
        result = self.draft(self.form(manual=manual))
        self.assertEqual(result["count"], 1)
        last = 'url = "https://globex.example/jobs"\n'
        self.assertEqual(self.written(result), self.before.replace(
            last, last + '\n[[manual_check]]\nname = "Hooli"\nurl = "https://hooli.example/careers"\n'))
        self.assertEqual([m["name"] for m in tomllib.loads(self.written(result))["manual_check"]],
                         ["LinkedIn", "Initech", "Globex", "Hooli"])

    def test_emptied_and_filled_again_the_list_stays_where_it_was(self):
        result = self.draft(self.form(manual=[]))
        self.assertEqual(result["count"], 3)
        self.assertNotIn("manual_check", tomllib.loads(self.written(result)))
        self.assertIn("# Employers worth watching with no public feed.\n# [[manual_check]]\n", self.written(result))
        self.save(result)
        result = self.draft(self.form(manual=[{"at": None, "name": "Hooli", "url": "", "why": ""}]))
        self.assertIn('# Employers worth watching with no public feed.\n[[manual_check]]\nname = "Hooli"\n\n'
                      "# Company watchlist", self.written(result))
        self.assertNotIn("# [[manual_check]]", self.written(result))

    def test_every_one_replaced_keeps_the_list_where_it_was(self):
        result = self.draft(self.form(manual=[{"at": None, "name": "Hooli", "url": "", "why": ""}]))
        self.assertEqual(result["count"], 4)
        self.assertIn('# Employers worth watching with no public feed.\n[[manual_check]]\nname = "Hooli"\n\n'
                      "# Company watchlist", self.written(result))

    def test_windows_line_endings_stay(self):
        self.rewrite(self.before.replace("\n", "\r\n"))
        manual = self.form()["manual"]
        manual[0]["why"] = "Terms"
        manual.append({"at": None, "name": "Hooli", "url": "", "why": ""})
        result = self.draft(self.form(manual=manual))
        self.assertNotIn("\n", self.written(result).replace("\r\n", ""))
        self.assertEqual(self.written(result).replace("\r\n", "\n"), self.before.replace(
            'why = "Its terms forbid automated collection"', 'why = "Terms"').replace(
            'url = "https://globex.example/jobs"\n', 'url = "https://globex.example/jobs"\n\n[[manual_check]]\nname = "Hooli"\n'))

    def test_a_table_inside_an_entry_is_refused_rather_than_lost(self):
        self.rewrite(self.before.replace("# Globex: check Mondays.\n", "[manual_check.extra]\nnote = 1\n\n# Globex: check Mondays.\n"))
        manual = self.form()["manual"]
        manual[0]["why"] = "Terms"
        with self.assertRaisesRegex(ValueError, "a table inside"):
            self.draft(self.form(manual=manual))


class BoardAddresses(unittest.TestCase):
    """Workday's myworkdaysite.com host, Lever's EU site and Ashby board names with spaces, read from the address
    alone. The address is never fetched: only the board it names is."""

    def test_more_addresses_are_read_as_the_board_they_name(self):
        for address, board in (
            ("https://umbrella.wd5.myworkdaysite.com/recruiting/umbrella/Careers",
             {"kind": "workday", "key": "umbrella", "wd": "wd5", "site": "Careers", "name": "Umbrella"}),
            ("wd1.myworkdaysite.com/en-US/recruiting/umbrella/External/job/Madison-WI/Engineer_R-1234",
             {"kind": "workday", "key": "umbrella", "wd": "wd1", "site": "External", "name": "Umbrella"}),
            ("https://wd3.myworkdaysite.com/wday/cxs/umbrella/External/jobs",
             {"kind": "workday", "key": "umbrella", "wd": "wd3", "site": "External", "name": "Umbrella"}),
            ("https://jobs.eu.lever.co/hooli/5f7e-41ab/apply", {"kind": "lever", "key": "hooli", "eu": True, "name": "Hooli"}),
            ("https://api.eu.lever.co/v0/postings/hooli?mode=json", {"kind": "lever", "key": "hooli", "eu": True, "name": "Hooli"}),
            ("https://jobs.ashbyhq.com/Initech%20Labs/4f1c", {"kind": "ashby", "key": "Initech Labs", "name": "Initech Labs"}),
            ("https://jobs.ashbyhq.com/globex%20robotics", {"kind": "ashby", "key": "globex robotics", "name": "Globex Robotics"}),
        ):
            with self.subTest(address):
                self.assertEqual(discover.board_from_url(address), board)

    def test_what_they_cant_name_is_refused_saying_why(self):
        for address, said in (
            ("https://umbrella.wd5.myworkdaysite.com/recruiting/globex/Careers", "two Workday tenants"),
            ("https://wd5.myworkdaysite.com/en-US/umbrella", "no Workday tenant and site"),
            ("https://wd5.myworkdaysite.com/recruiting/evil.test/Careers", "isn't a Workday tenant"),
            ("https://wd5.myworkdaysite.com/recruiting/umbrella/..%2Fevil", "isn't a Workday site"),
            ("https://umbrella.wd5.myworkdaysite.com.evil.test/recruiting/umbrella/Careers", "isn't one of them"),
            ("https://jobs.eu.lever.co.evil.test/hooli", "isn't one of them"),
            ("https://jobs.eu.lever.co/hooli%2F..%2Fevil", "isn't a Lever board"),
            ("https://jobs.ashbyhq.com/a%2F..%2Fevil", "isn't an Ashby board"),
            ("https://jobs.ashbyhq.com/..", "isn't an Ashby board"),
            ("https://jobs.ashbyhq.com/Initech%3Fx%3D1", "isn't an Ashby board"),
            ("https://jobs.ashbyhq.com/%20Initech", "isn't an Ashby board"),
            ("https://jobs.ashbyhq.com/Initech%25", "isn't an Ashby board"),
            # Workday on a company's own domain: the address doesn't say which tenant, and Pyrite won't open it to find out.
            ("https://careers.initech.example/en-US/Careers/job/Madison-WI/Engineer_R-1234", "Workday careers site on the company's own domain"),
            ("https://careers.initech.example/wday/cxs/initech/External/jobs", "names the tenant initech and the site External"),
            ("https://careers.initech.example/jobs/1234", "isn't one of them"),
        ):
            with self.subTest(address):
                with self.assertRaisesRegex(ValueError, said):
                    discover.board_from_url(address)

    def test_testing_reads_only_the_feed_of_the_board_named(self):
        asked = []

        def answer(url, payload=None, retries=3):
            asked.append(url)
            if "myworkdayjobs" in url:
                return {"total": 3}
            return [] if "lever.co" in url else {"jobs": []}

        with mock.patch.object(sources, "_request", side_effect=answer):
            self.assertTrue(server._test_board({"url": "https://jobs.eu.lever.co/hooli"})["ok"])
            found = server._test_board({"kind": "lever", "key": "hooli", "name": "Hooli", "eu": True})
            self.assertEqual((found["ok"], found["board"]["eu"]), (True, True))
            server._test_board({"kind": "lever", "key": "hooli", "name": "Hooli", "eu": "yes"})  # Only true is true.
            server._test_board({"kind": "ashby", "key": "Initech Labs", "name": "Initech Labs"})
            found = server._test_board({"url": "https://wd5.myworkdaysite.com/recruiting/umbrella/Careers"})
            self.assertEqual(found["count"], 3)
        self.assertEqual(asked, [
            "https://api.eu.lever.co/v0/postings/hooli?mode=json",
            "https://api.eu.lever.co/v0/postings/hooli?mode=json",
            "https://api.lever.co/v0/postings/hooli?mode=json",
            "https://api.ashbyhq.com/posting-api/job-board/Initech%20Labs?includeCompensation=true",
            "https://umbrella.wd5.myworkdayjobs.com/wday/cxs/umbrella/Careers/jobs",
        ])

    def test_testing_refuses_a_board_that_could_name_another_site(self):
        with mock.patch.object(sources, "_request") as fetch:
            for body in (
                {"kind": "ashby", "key": "a/../evil"},
                {"kind": "ashby", "key": ".."},
                {"kind": "ashby", "key": "x?y=1"},
                {"kind": "ashby", "key": "x#y"},
                {"kind": "ashby", "key": "@evil.test"},
                {"kind": "ashby", "key": "x\\y"},
                {"kind": "lever", "key": "evil.test/x", "eu": True},
                {"url": "https://jobs.eu.lever.co@evil.test/hooli"},
                {"url": "https://wd1.myworkdaysite.com/recruiting/umbrella/../../evil"},
                {"url": "https://careers.initech.example/wday/cxs/initech/External/jobs"},
            ):
                with self.subTest(body):
                    with self.assertRaises(ValueError):
                        server._test_board(body)
            fetch.assert_not_called()

    def test_a_watched_lever_board_on_the_eu_site_is_read_from_the_eu_feed(self):
        self.assertEqual(discover.watch_problem("lever", "hooli", {"name": "Hooli", "eu": True}), "")
        self.assertEqual(discover.watch_problem("lever", "hooli", {"name": "Hooli"}), "")
        for spec in ({"name": "Hooli", "eu": "yes"}, {"eu": True}, {"name": ""}):
            with self.subTest(spec):
                self.assertIn("eu = true", discover.watch_problem("lever", "hooli", spec))
        self.assertIn("should be the company's name", discover.watch_problem("greenhouse", "hooli", {"name": "Hooli"}))
        with mock.patch.object(sources, "_request", return_value=[]) as fetch:
            self.assertTrue(discover.check_source("lever", "hooli", {"name": "Hooli", "eu": True})["ok"])
            discover.check_source("lever", "hooli", "Hooli")
        self.assertEqual([call.args[0] for call in fetch.call_args_list],
                         ["https://api.eu.lever.co/v0/postings/hooli?mode=json", "https://api.lever.co/v0/postings/hooli?mode=json"])


class Boards(Section):
    """Writing the new kinds of board: a Lever board on its EU site, and an Ashby board whose name has a space."""

    def test_a_lever_board_on_the_eu_site_is_written_as_a_table(self):
        new = {"was": None, "kind": "lever", "key": "hooli", "name": "Hooli", "eu": True}
        result = self.draft(self.form(boards=self.form()["boards"] + [new]))
        self.assertIn('hooli = { name = "Hooli", eu = true }\n', result["changes"]["config"].replace("\r\n", "\n"))
        self.save(result)
        board = next(b for b in self.view["companies"]["boards"] if b["key"] == "hooli")
        self.assertEqual((board["eu"], board["name"], board["problem"]), (True, "Hooli", ""))
        self.assertEqual(self.draft(self.form())["changes"], {})
        # A page that doesn't say keeps the board where it is.
        boards = [{part: value for part, value in b.items() if part != "eu"} for b in self.form()["boards"]]
        self.assertEqual(self.draft(self.form(boards=boards))["changes"], {})
        boards = self.form()["boards"]
        next(b for b in boards if b["key"] == "hooli")["eu"] = False
        result = self.draft(self.form(boards=boards))
        self.assertEqual(result["count"], 1)
        self.assertEqual(tomllib.loads(result["changes"]["config"])["watch"]["lever"], {"hooli": "Hooli"})
        next(b for b in boards if b["key"] == "hooli")["eu"] = "no"
        with self.assertRaisesRegex(ValueError, "true or false"):
            self.draft(self.form(boards=boards))

    def test_an_ashby_board_whose_name_has_a_space_is_written_and_read_back(self):
        new = {"was": None, "kind": "ashby", "key": "Initech Labs", "name": "Initech Labs"}
        result = self.draft(self.form(boards=self.form()["boards"] + [new]))
        self.assertIn('"Initech Labs" = "Initech Labs"\n', result["changes"]["config"].replace("\r\n", "\n"))
        self.save(result)
        self.assertEqual(self.draft(self.form())["changes"], {})
        result = self.draft(self.form(boards=[b for b in self.form()["boards"] if b["key"] != "Initech Labs"]))
        self.assertNotIn("Initech Labs", result["changes"]["config"])
        with self.assertRaisesRegex(ValueError, "isn't an Ashby board"):
            self.draft(self.form(boards=self.form()["boards"] + [{**new, "key": "Initech/../Labs"}]))


class WorkdayPages(Section):
    """[workday] max_pages, set from the section, within discover.WORKDAY_PAGES."""

    def test_the_number_of_pages_is_changed_where_it_is(self):
        self.assertEqual((self.view["companies"]["max_pages"], self.view["companies"]["pages_range"]), (2, [1, 10]))
        self.assertEqual(self.draft(self.form(max_pages=2))["changes"], {})
        before = self.config().replace("\r\n", "\n")
        result = self.draft(self.form(max_pages=5))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["changes"]["config"].replace("\r\n", "\n"), before.replace("max_pages = 2\n", "max_pages = 5\n"))
        sites = sum(b["kind"] == "workday" for b in self.view["companies"]["boards"])
        queries = len(self.view["companies"]["queries"])
        self.assertTrue(any(f"up to {sites * queries * 5} requests" in note for note in result["notes"]), result["notes"])
        # Fewer pages costs nothing to say.
        self.assertFalse(any("requests" in note for note in self.draft(self.form(max_pages=1))["notes"]))

    def test_a_number_out_of_range_is_refused(self):
        for value in (0, 11, -1, "3", 2.5, True, None):
            with self.subTest(value):
                with self.assertRaisesRegex(ValueError, "whole number from 1 to 10"):
                    self.draft(self.form(max_pages=value))

    def test_a_number_out_of_range_already_in_the_file_stays_while_it_isnt_changed(self):
        self.rewrite(self.config().replace("max_pages = 2", "max_pages = 25"))
        self.assertEqual(self.view["companies"]["max_pages"], 25)
        self.assertEqual(self.draft(self.form())["changes"], {})
        self.assertIn("max_pages = 10", self.draft(self.form(max_pages=10))["changes"]["config"])

    def test_a_file_without_it_reads_the_default_and_gets_the_key_when_its_changed(self):
        self.rewrite(self.config().replace("max_pages = 2\n", "").replace("max_pages = 2\r\n", ""))
        self.assertEqual(self.view["companies"]["max_pages"], discover.DEFAULT_WORKDAY_PAGES)
        self.assertEqual(self.draft(self.form())["changes"], {})
        result = self.draft(self.form(max_pages=3))
        self.assertEqual(tomllib.loads(result["changes"]["config"])["workday"]["max_pages"], 3)


if __name__ == "__main__":
    unittest.main()
