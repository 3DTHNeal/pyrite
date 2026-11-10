"""Setting up the daily runs in Windows Task Scheduler from Settings › Daily run. Task Scheduler is never reached: each
test stands in for PowerShell and reads what it was asked to run."""
import base64
import json
import subprocess
import unittest
import unittest.mock as mock
from datetime import UTC, datetime
from pathlib import Path

import support  # noqa: F401  Points PYRITE_HOME at a copy of the example before Pyrite loads.

from pyrite import schedule, server, store

HERE = str(store.CODE_ROOT)


def task(name, *starts, path="\\", at="2026-11-05T05:15:00", state="Ready"):
    return {"path": path, "name": name, "state": state, "starts": list(starts), "at": [at]}


class Schedule(unittest.TestCase):
    def setUp(self):
        self.tasks: list = []
        self.calls: list[tuple[str, dict]] = []
        self.answer: subprocess.CompletedProcess | None = None
        for patcher in (mock.patch.object(schedule, "WINDOWS", True),
                        mock.patch.object(store, "IS_EXAMPLE", False),
                        mock.patch.object(schedule, "_task_workspace", return_value=store.ROOT),
                        mock.patch.object(schedule.subprocess, "run", side_effect=self.powershell)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def powershell(self, cmd, **kw):
        """A stand-in for powershell.exe: what it was asked, and Task Scheduler's answer for a query."""
        self.assertEqual(cmd[0], "powershell.exe")
        script = base64.b64decode(cmd[-1]).decode("utf-16-le")
        self.calls.append((script, kw["env"]))
        self.assertIn("timeout", kw)
        if self.answer is not None:
            return self.answer
        out = json.dumps(self.tasks) if "Get-ScheduledTask" in script else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=out.encode(), stderr=b"")

    def runs(self):
        return {run["id"]: run for run in schedule.view()["runs"]}

    def test_each_run_says_whether_it_is_set_up_and_when(self):
        self.tasks = [task("Pyrite pan", f"C:\\py\\pythonw.exe \"{HERE}\\tools\\pyrite.py\" sweep")]
        found = schedule.view()
        self.assertEqual((found["available"], found["why_not"]), (True, ""))
        runs = {run["id"]: run for run in found["runs"]}
        self.assertEqual((runs["pan"]["set"], runs["pan"]["time"], runs["pan"]["other_copy"]), (True, "05:15", False))
        self.assertEqual((runs["run"]["set"], runs["run"]["time"], runs["run"]["default"]), (False, None, "07:00"))
        self.assertNotIn("same", runs["pan"])  # A pattern isn't for the page.

    def test_one_task_on_its_own_is_read_too(self):
        # PowerShell's ConvertTo-Json writes a list of one as the object alone.
        self.tasks = task("Pyrite daily run", f"pythonw.exe \"{HERE}\\tools\\pyrite.py\" run", at="2026-11-05T07:30:00")
        self.assertEqual(self.runs()["run"]["time"], "07:30")

    def test_a_start_written_with_a_zone_is_read_in_local_time(self):
        # New-ScheduledTaskTrigger writes UTC, and a task made elsewhere may carry an offset. Either is shown as the time here.
        local = datetime(2026, 11, 5, 5, 15).astimezone()
        for boundary in (local.isoformat(), local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "2026-11-05T05:15:00"):
            with self.subTest(boundary=boundary):
                self.assertEqual(schedule._time(boundary), "05:15")
        self.assertIsNone(schedule._time(""))

    def test_a_new_task_starts_on_local_time_rather_than_utc(self):
        self.assertIn("$trigger.StartBoundary = $at.ToString('s')", schedule.REGISTER)

    def test_a_task_made_by_hand_that_does_the_same_is_named_and_left_alone(self):
        self.tasks = [task("Pyrite Sweep", "C:\\x\\pythonw.exe tools\\pyrite.py discover", "C:\\x\\pythonw.exe tools\\pyrite.py inbox"),
                      task("Pyrite Update", 'powershell.exe -File "C:\\x\\Update Pyrite.ps1"')]
        runs = self.runs()
        self.assertEqual(runs["pan"]["set"], False)
        self.assertEqual(runs["pan"]["elsewhere"], [{"name": "Pyrite Sweep", "time": "05:15"}])
        self.assertEqual(runs["run"]["elsewhere"], [])

    def test_a_task_from_another_copy_of_pyrite_says_so_and_one_turned_off_too(self):
        self.tasks = [task("Pyrite pan", 'C:\\elsewhere\\pythonw.exe "C:\\elsewhere\\tools\\pyrite.py" sweep', state="Disabled")]
        pan = self.runs()["pan"]
        self.assertEqual((pan["other_copy"], pan["disabled"]), (True, True))

    def test_setting_one_up_hands_the_time_and_paths_over_outside_the_script(self):
        schedule.change({"run": "pan", "action": "set", "time": "05:45"})
        script, env = self.calls[0]
        self.assertIn("Register-ScheduledTask", script)
        self.assertEqual(script, schedule.REGISTER)  # Fixed text: nothing sent from the page is read as PowerShell.
        self.assertEqual((env["PYRITE_TASK_NAME"], env["PYRITE_TASK_AT"], env["PYRITE_TASK_DIR"]), ("Pyrite pan", "05:45", HERE))
        self.assertTrue(env["PYRITE_TASK_ARGS"].endswith('pyrite.py" sweep'))
        self.assertIn(HERE, env["PYRITE_TASK_ARGS"])
        self.assertIn("Get-ScheduledTask", self.calls[-1][0])  # The answer is the page again, read afresh.

    def test_removing_one_names_only_pyrites_own_task(self):
        schedule.change({"run": "run", "action": "remove"})
        script, env = self.calls[0]
        self.assertEqual((script, env["PYRITE_TASK_NAME"]), (schedule.UNREGISTER, "Pyrite daily run"))
        self.assertIn("-TaskPath '\\'", script)

    def test_a_change_it_cannot_make_is_refused_before_task_scheduler_is_asked(self):
        for body, said in (({"run": "pan", "action": "set", "time": "5:15; Remove-Item x"}, "HH:MM"),
                           ({"run": "pan", "action": "set", "time": "24:00"}, "HH:MM"),
                           ({"run": "Pyrite Sweep", "action": "remove"}, "which run"),
                           ({"run": "pan", "action": "start"}, "set the run up or remove")):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, said):
                schedule.change(body)
        self.assertEqual(self.calls, [])

    def test_the_demo_changes_nothing(self):
        with mock.patch.object(store, "IS_EXAMPLE", True), self.assertRaisesRegex(ValueError, "demo"):
            schedule.change({"run": "pan", "action": "set", "time": "05:15"})
        self.assertEqual(self.calls, [])

    def test_a_workspace_a_task_would_not_find_is_named_before_anything_is_set_up(self):
        with mock.patch.object(schedule, "_task_workspace", return_value=Path("C:/some/other")):
            found = schedule.view()
            self.assertFalse(found["available"])
            self.assertIn(".pyrite-home", found["why_not"])
            with self.assertRaisesRegex(ValueError, "PYRITE_HOME"):
                schedule.change({"run": "pan", "action": "set", "time": "05:15"})

    def test_task_scheduler_refusing_or_not_answering_is_said_plainly(self):
        self.answer = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"\r\nAccess is denied.\r\nmore\r\n")
        with self.assertRaisesRegex(schedule.ScheduleError, "refused: Access is denied.$"):
            schedule.change({"run": "pan", "action": "set", "time": "05:15"})
        found = schedule.view()
        self.assertEqual((found["available"], found["error"]), (False, True))
        with mock.patch.object(schedule.subprocess, "run", side_effect=subprocess.TimeoutExpired("powershell.exe", 60)):
            self.assertIn("didn't answer", schedule.view()["why_not"])

    def test_the_dashboard_answers_for_it(self):
        self.assertIs(server.PROFILE_WRITES["/api/settings/schedule"], server._change_schedule)
        self.assertEqual(server._change_schedule({"run": "pan", "action": "remove"})["runs"][0]["id"], "pan")


class ElsewhereThanWindows(unittest.TestCase):
    def test_another_system_is_pointed_at_the_docs_and_nothing_is_run(self):
        with mock.patch.object(schedule, "WINDOWS", False), mock.patch.object(schedule.subprocess, "run") as ran:
            found = schedule.view()
            self.assertFalse(found["available"])
            self.assertIn("docs/schedule.md", found["why_not"])
            self.assertEqual([run["id"] for run in found["runs"]], ["pan", "run"])
            with self.assertRaisesRegex(ValueError, "docs/schedule.md"):
                schedule.change({"run": "pan", "action": "set", "time": "05:15"})
        ran.assert_not_called()

    def test_the_page_asks_before_it_changes_a_task(self):
        script = (store.CODE_ROOT / "tools" / "pyrite" / "static" / "app.js").read_text(encoding="utf-8")
        start = script.index("function scheduleRun(")
        body = script[start:script.index("function schedulePanel(", start)]
        self.assertIn("window.confirm(", body)
        self.assertLess(body.index("window.confirm("), body.index('api("/api/settings/schedule"'))


if __name__ == "__main__":
    unittest.main()
