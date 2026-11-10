"""The daily runs in Windows Task Scheduler, for Settings › Daily run: whether each is set up, and setting one up,
moving it to another time or taking it away.

Pyrite only ever touches the tasks it names here, in Task Scheduler's top folder. A task someone made by hand that
runs the same command is found and shown, so the page can say it's there instead of setting up a second one, but it's
never changed. Other systems schedule the runs themselves, as docs/schedule.md describes.

The PowerShell scripts are fixed text. What changes between calls, such as the time and the paths, reaches them as
environment variables, so nothing the page sends is ever read as part of a script.
"""
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import store

# PowerShell starts in a second or two, but a busy machine's Task Scheduler can take a while to answer.
TIMEOUT_SECONDS = 60
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Task Scheduler is the only scheduler Pyrite sets runs up in so far.
WINDOWS = sys.platform == "win32"
TIME = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
DOCS = "docs/schedule.md"

# Each run Pyrite can set up. `name` is the task's name in Task Scheduler, and `same` finds a task made by hand that
# already runs the same command, from what it starts.
RUNS: tuple[dict[str, Any], ...] = (
    {"id": "pan", "name": "Pyrite pan", "label": "The pan", "command": "sweep", "default": "05:15",
     "does": "Reads the job boards, then checks mail for replies. It uses no AI.",
     "same": re.compile(r"pyrite(?:\.py|\.exe)?\W+(?:sweep|discover|inbox)\b", re.I)},
    {"id": "run", "name": "Pyrite daily run", "label": "The daily run", "command": "run", "default": "07:00",
     "does": "Judges new postings and tailors the best with Claude, as much as this page allows. Set it for after "
             "the pan.",
     "same": re.compile(r"pyrite(?:\.py|\.exe)?\W+run\b", re.I)},
)
BY_ID = {run["id"]: run for run in RUNS}

# What Task Scheduler holds for any task that starts Pyrite, as JSON.
QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$found = @(Get-ScheduledTask | ForEach-Object {
  $task = $_
  $starts = @($task.Actions | ForEach-Object { ("$($_.Execute) $($_.Arguments)").Trim() } | Where-Object { $_ })
  if (($starts -join ' ') -match 'pyrite') {
    [pscustomobject]@{
      path = $task.TaskPath; name = $task.TaskName; state = [string]$task.State; starts = $starts
      at = @($task.Triggers | ForEach-Object { [string]$_.StartBoundary })
    }
  }
})
ConvertTo-Json -InputObject $found -Depth 4 -Compress
"""
# Made again whole, so a change of time also brings the command up to date with this copy of Pyrite. It runs as you,
# while you're signed in, with no window. One missed while the computer was off or asleep starts once it's back.
REGISTER = r"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute $env:PYRITE_TASK_EXE -Argument $env:PYRITE_TASK_ARGS -WorkingDirectory $env:PYRITE_TASK_DIR
$at = [datetime]::ParseExact($env:PYRITE_TASK_AT, 'HH:mm', $null)
$trigger = New-ScheduledTaskTrigger -Daily -At $at
# The cmdlet writes the start in UTC, which keeps the run at the same UTC hour, an hour off local time half the year.
# A start with no zone follows this computer's clock instead.
$trigger.StartBoundary = $at.ToString('s')
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 12)
Register-ScheduledTask -TaskName $env:PYRITE_TASK_NAME -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings `
  -Description $env:PYRITE_TASK_ABOUT -Force | Out-Null
"""
UNREGISTER = r"""
$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName $env:PYRITE_TASK_NAME -TaskPath '\' -Confirm:$false
"""


class ScheduleError(ValueError):
    """Task Scheduler couldn't be asked, or refused. Nothing was changed by Pyrite."""


def _powershell(script: str, env: dict[str, str] | None = None) -> str:
    """Run a fixed script with no window, and hand back what it printed. Raises ScheduleError when it fails."""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True, timeout=TIMEOUT_SECONDS, env={**os.environ, **(env or {})}, creationflags=NO_WINDOW,
            stdin=subprocess.DEVNULL)
    except FileNotFoundError as err:
        raise ScheduleError("Windows PowerShell isn't on this computer, so Pyrite can't reach Task Scheduler.") from err
    except subprocess.TimeoutExpired as err:
        raise ScheduleError(f"Task Scheduler didn't answer within {TIMEOUT_SECONDS} seconds. Try again in a moment.") from err
    out = done.stdout.decode("utf-8", "replace")
    if done.returncode:
        said = [line.strip() for line in done.stderr.decode("utf-8", "replace").splitlines() if line.strip()]
        raise ScheduleError(f"Task Scheduler refused: {said[0] if said else f'it stopped with code {done.returncode}'}")
    return out


def _time(boundary: str) -> str | None:
    """The HH:MM a trigger starts at here, from its StartBoundary: 2026-11-05T05:15:00 is local time already, and one
    with a zone, such as 2026-11-05T13:15:00Z or 05:15:00-08:00, is moved into this computer's."""
    try:
        start = datetime.fromisoformat((boundary or "").replace("Z", "+00:00"))
    except ValueError:
        match = re.search(r"T(\d\d):(\d\d)", boundary or "")
        return f"{match[1]}:{match[2]}" if match else None
    if start.tzinfo is not None:
        start = start.astimezone()
    return start.strftime("%H:%M")


def _found() -> list[dict[str, Any]]:
    out = _powershell(QUERY).strip()
    try:
        tasks = json.loads(out) if out else []
    except ValueError as err:
        raise ScheduleError("Task Scheduler's answer couldn't be read.") from err
    if isinstance(tasks, dict):  # One task comes back on its own, not in a list.
        tasks = [tasks]
    return [task for task in tasks if isinstance(task, dict)]


def _task_workspace() -> Path | None:
    """The workspace a task started by Task Scheduler would open: PYRITE_HOME as saved in Windows for this user or
    the whole computer, else what .pyrite-home names. A PYRITE_HOME set only in a terminal reaches no task."""
    # sys.platform rather than WINDOWS, so type checkers on other systems know winreg is never reached there.
    if sys.platform == "win32":
        import winreg

        places = ((winreg.HKEY_CURRENT_USER, "Environment"),
                  (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
        for hive, key in places:
            try:
                with winreg.OpenKey(hive, key) as opened:
                    value, _kind = winreg.QueryValueEx(opened, "PYRITE_HOME")
            except OSError:
                continue
            if isinstance(value, str) and value.strip():
                return store._resolve(os.path.expandvars(value.strip()), store.CODE_ROOT)
    return store.pointer_target()


def _command(run: dict[str, Any]) -> tuple[str, str]:
    """The program a task starts and its arguments: this copy of Pyrite's Python, with no window when there's one."""
    python = Path(sys.executable)
    windowless = python.with_name("pythonw.exe")
    exe = windowless if windowless.exists() else python
    return str(exe), f'"{store.CODE_ROOT / "tools" / "pyrite.py"}" {run["command"]}'


def why_not() -> str:
    """Why the runs can't be set up from here, or "" when they can."""
    if not WINDOWS:
        return f"Pyrite sets up the daily runs only in Windows Task Scheduler so far. On this computer, {DOCS} says how."
    if store.IS_EXAMPLE:
        return "This is the demo, so it sets up no runs. Point PYRITE_HOME at your own workspace to set them up."
    found = _task_workspace()
    if found != store.ROOT:
        opens = f"would open {found}" if found else "would find no workspace"
        return (f"A run started by Task Scheduler {opens}, not this one, since this dashboard's workspace comes from a "
                f"PYRITE_HOME set only where it was started. Put {store.ROOT} in the .pyrite-home file in {store.CODE_ROOT}, "
                "or save PYRITE_HOME in your Windows user environment variables, then Check again.")
    return ""


def view() -> dict[str, Any]:
    """Each run: whether Pyrite's own task is set up, at what time, and any task made by hand that does the same."""
    runs = [{key: value for key, value in run.items() if key != "same"} for run in RUNS]
    if not WINDOWS:
        return {"available": False, "why_not": why_not(), "runs": runs}
    try:
        tasks = _found()
    except ScheduleError as err:
        return {"available": False, "why_not": str(err), "runs": runs, "error": True}
    for shown, run in zip(runs, RUNS, strict=True):
        ours = next((task for task in tasks if task.get("path") == "\\" and str(task.get("name", "")).lower() == run["name"].lower()), None)
        times = [time for time in (_time(at) for at in (ours or {}).get("at") or []) if time]
        starts = " ".join((ours or {}).get("starts") or [])
        shown.update({
            "set": ours is not None,
            "time": times[0] if times else None,
            "disabled": bool(ours and ours.get("state") == "Disabled"),
            # Set up from another copy of Pyrite, so it runs that copy's code rather than this one's.
            "other_copy": bool(ours and str(store.CODE_ROOT).lower() not in starts.lower()),
            "elsewhere": [{"name": f"{task.get('path', '')}{task.get('name', '')}".lstrip("\\"),
                           "time": next((t for t in (_time(at) for at in task.get("at") or []) if t), None)}
                          for task in tasks if task is not ours and run["same"].search(" ".join(task.get("starts") or []))],
        })
    reason = why_not()
    return {"available": not reason, "why_not": reason, "runs": runs}


def change(body: dict[str, Any]) -> dict[str, Any]:
    """Set up one run at a time of day, or take it away: {"run": "pan", "action": "set", "time": "05:15"}, or
    "remove". Only ever Pyrite's own task by its own name."""
    reason = why_not()
    if reason:
        raise ValueError(reason)
    run = BY_ID.get(str(body.get("run") or ""))
    if run is None:
        raise ValueError("Say which run: the pan or the daily run.")
    env = {"PYRITE_TASK_NAME": run["name"]}
    if body.get("action") == "set":
        at = str(body.get("time") or "")
        if not TIME.fullmatch(at):
            raise ValueError("Give a time of day as HH:MM, such as 05:15.")
        exe, args = _command(run)
        env.update({"PYRITE_TASK_EXE": exe, "PYRITE_TASK_ARGS": args, "PYRITE_TASK_DIR": str(store.CODE_ROOT),
                    "PYRITE_TASK_AT": at, "PYRITE_TASK_ABOUT": f"{run['does']} Set up from Pyrite's Settings tab."})
        _powershell(REGISTER, env)
    elif body.get("action") == "remove":
        _powershell(UNREGISTER, env)
    else:
        raise ValueError("Say whether to set the run up or remove it.")
    return view()
