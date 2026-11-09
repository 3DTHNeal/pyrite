"""Whether GitHub's main has code this copy of Pyrite lacks, and the dashboard's one-click update to it.

Pyrite is run from a git clone, so the latest is GitHub's main: `origin/main` after a fetch. The check only fetches, and
the update only ever fast-forwards: it refuses a copy on another branch, with edits of its own to tracked files, or with
commits GitHub's main doesn't have, and says why, rather than merging anything or throwing work away. Nothing in the
workspace is touched. The dashboard restarts itself afterwards, since a running server keeps the Python it started with.
"""
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .store import CODE_ROOT

REMOTE, BRANCH = "origin", "main"
LATEST = f"{REMOTE}/{BRANCH}"
# Seconds between fetches. The page asks more often than this, and gets the last answer.
CHECK_EVERY = 3600
GIT_SECONDS = 60
PIP_SECONDS = 600
# The most commit subjects the dashboard lists. It counts the rest.
MAX_CHANGES = 20
REQUIREMENTS = "tools/requirements.txt"
# A git run by the dashboard has no terminal to ask for a sign-in in, so it must fail rather than wait for one. A
# console program started from pythonw would otherwise open a window of its own.
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitError(Exception):
    pass


_lock = threading.Lock()  # One update at a time, and no check halfway through one.
_cache: dict = {}  # The last check, by code folder: (when, what it found).


def _run(command: list[str], cwd: Path, seconds: int) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=seconds, env={**os.environ, **NO_PROMPT}, stdin=subprocess.DEVNULL,
                          creationflags=NO_WINDOW)


def _git(repo: Path, *args: str) -> str:
    try:
        done = _run(["git", *args], repo, GIT_SECONDS)
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} took more than {GIT_SECONDS} seconds.") from None
    except OSError as err:
        raise GitError(f"git couldn't be run: {err}") from None
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        raise GitError(said[-1] if said else f"git {args[0]} failed.")
    return done.stdout.strip()


def why_not(repo: Path, branch: str, edited: bool, ahead: int, demo: bool) -> str | None:
    """Why this copy can't be moved forward from the dashboard, in words that say what to do instead."""
    if demo:
        return f"This is the demo. Run `git pull` in {repo} and start the demo again to get the latest."
    if branch != BRANCH:
        return (f"Pyrite's code folder is on the branch {branch}, not {BRANCH}, so it isn't updated from here. "
                f"Switch it to {BRANCH}, or merge {BRANCH} into {branch}.")
    if edited:
        return (f"Pyrite's code folder, {repo}, has edits of your own to files it tracks, so it isn't updated from here, "
                "since that could lose them. Commit or stash them, then try again.")
    if ahead:
        return (f"This copy's {BRANCH} has {ahead} commit{'s' if ahead != 1 else ''} GitHub's doesn't, so it can't just "
                f"move forward. Run `git pull` in {repo} to merge them.")
    return None


def _look(repo: Path, demo: bool) -> dict:
    """Fetch GitHub's main and compare this copy with it."""
    if not shutil.which("git"):
        return {"available": False, "error": "git isn't installed, so Pyrite can't tell whether it's up to date."}
    if not (repo / ".git").exists():
        return {"available": False, "error": f"{repo} isn't a git clone, so Pyrite can't tell whether it's up to date."}
    try:
        _git(repo, "fetch", "--quiet", "--no-tags", REMOTE, BRANCH)
        behind = int(_git(repo, "rev-list", "--count", f"HEAD..{LATEST}"))
        ahead = int(_git(repo, "rev-list", "--count", f"{LATEST}..HEAD"))
        found: dict = {"available": behind > 0, "behind": behind, "current": _git(repo, "rev-parse", "--short", "HEAD")}
        if behind:
            subjects = _git(repo, "log", "--no-merges", "--format=%s", f"-n{MAX_CHANGES + 1}", f"HEAD..{LATEST}")
            found["changes"] = subjects.splitlines()
            found["latest"] = _git(repo, "rev-parse", "--short", LATEST)
            branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            edited = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
            found["why_not"] = why_not(repo, branch, edited, ahead, demo)
        return found
    except GitError as err:
        return {"available": False, "error": f"Couldn't check GitHub for a newer Pyrite: {err}"}


def check(repo: Path = CODE_ROOT, demo: bool = False, fresh: bool = False) -> dict:
    """Whether GitHub's main is ahead of this copy, fetched at most once an hour unless `fresh`.

    `available` says there's something to update to, `behind` how many commits, `changes` the subjects of up to
    MAX_CHANGES + 1 of them (the page counts past MAX_CHANGES) and `why_not` why the dashboard can't do the update.
    `error` is why nothing could be told."""
    with _lock:
        key = str(repo)
        when, found = _cache.get(key, (None, None))
        if fresh or found is None or time.monotonic() - when >= CHECK_EVERY:
            found = _look(repo, demo)
            _cache[key] = (time.monotonic(), found)
        return {**found, "changes": list(found.get("changes", []))}


def forget() -> None:
    """Drop the last check, so the next one fetches."""
    with _lock:
        _cache.clear()


def apply(repo: Path = CODE_ROOT, demo: bool = False, python: str = sys.executable) -> dict:
    """Fast-forward this copy to GitHub's main, and install the packages again if tools/requirements.txt changed.

    Raises ValueError, with why, when there's nothing to update to or it can't be done safely. Returns what changed:
    the commits it moved from and to, how many, and what installing the packages said, if they were installed."""
    if not _lock.acquire(blocking=False):
        raise ValueError("An update or a check is already going. Try again in a moment.")
    try:
        _cache.clear()
        found = _look(repo, demo)
        if found.get("error"):
            raise ValueError(found["error"])
        if not found["available"]:
            raise ValueError("Pyrite is already up to date.")
        if found.get("why_not"):
            raise ValueError(found["why_not"])
        try:
            changed = _git(repo, "diff", "--name-only", "HEAD", LATEST).splitlines()
            _git(repo, "merge", "--ff-only", "--quiet", LATEST)
            done = {"from": found["current"], "to": _git(repo, "rev-parse", "--short", "HEAD"), "behind": found["behind"],
                    "packages": None}
        except GitError as err:
            raise ValueError(f"The update didn't go through, and the code is as it was: {err}") from None
        if REQUIREMENTS in changed:
            done["packages"] = _install(repo, python)
        return done
    finally:
        _lock.release()


def _install(repo: Path, python: str) -> str:
    """Install tools/requirements.txt with the Python running Pyrite. What it says goes to the page, never an error:
    the code has already moved, so the restart that follows is still wanted."""
    try:
        done = _run([python, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", REQUIREMENTS],
                    repo, PIP_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as err:
        return f"{REQUIREMENTS} changed, and installing it didn't finish ({err}). Run `pip install -r {REQUIREMENTS}`."
    if done.returncode != 0:
        said = (done.stderr or done.stdout).strip().splitlines()
        return (f"{REQUIREMENTS} changed, and installing it failed{': ' + said[-1] if said else ''}. "
                f"Run `pip install -r {REQUIREMENTS}`.")
    return f"{REQUIREMENTS} changed, so the packages were brought up to date."
