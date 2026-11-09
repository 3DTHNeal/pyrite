"""Whether GitHub's main has code this copy of Pyrite lacks, and the dashboard's one-click update to it.

Pyrite is run from a git clone, so the latest is GitHub's main: `origin/main` after a fetch. The check only fetches, and
the update only ever moves forward: it fast-forwards main, and switches a copy on another branch to main first only when
everything on that branch is already in GitHub's main. It refuses a copy with edits of its own to tracked files, or with
commits GitHub's main doesn't have, and says why and what to run, rather than merging anything or throwing work away.
Nothing in the workspace is touched. The dashboard restarts itself afterwards, since a running server keeps the Python
it started with.
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
# Schemes git fetches over with nothing to say the code came from where it claims. Anyone on the network could hand
# over code of their own, and the update would run it, so a copy cloned over one of these is never updated from here.
PLAIN = ("http://", "git://")


class GitError(Exception):
    pass


_lock = threading.Lock()  # One update at a time, and no check halfway through one.
_fetched: dict = {}  # The last fetch of GitHub's main, by code folder: (when, why it failed or None).


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


def _commits(n: int) -> str:
    return f"{n} commit{'s' if n != 1 else ''}"


def why_not(repo: Path, branch: str | None, edited: bool, ahead: int, ours: int, demo: bool) -> str | None:
    """Why this copy can't be moved forward from the dashboard, in words that say what to run instead.

    `branch` is the one checked out, None for none (a detached HEAD). `ahead` counts its commits GitHub's main lacks,
    and `ours` those of this copy's own main."""
    if demo:
        return f"This is the demo. Run `git pull` in {repo} and start the demo again to get the latest."
    on_main = branch == BRANCH
    where = f" is on the branch {branch}" if branch else " isn't on a branch"
    if edited:
        place = "" if on_main else f"{where}, not {BRANCH}, and" if branch else f"{where}, and"
        return (f"Pyrite's code folder, {repo},{place} has edits of your own to files it tracks, so it isn't updated "
                "from here, since that could lose them. Commit or stash them, then check again.")
    if ahead and not on_main:
        has = f"which has {_commits(ahead)}" if branch else f"and has {_commits(ahead)}"
        instead = (f"To run {BRANCH} instead, run `git switch {BRANCH}` there, then check again. To stay on {branch}, run "
                   f"`git merge {LATEST}` there, then restart the dashboard." if branch else
                   f"To keep {'it' if ahead == 1 else 'them'}, run `git branch <name>` there. Then run "
                   f"`git switch {BRANCH}`, and check again.")
        return (f"Pyrite's code folder, {repo},{where}, {has} GitHub's {BRANCH} doesn't, so it isn't updated from here. "
                f"{instead}")
    if ours:
        pull = "`git pull`" if on_main else f"`git switch {BRANCH}` and then `git pull`"
        return (f"This copy's {BRANCH} has {_commits(ours)} GitHub's doesn't, so it can't just move forward. Run {pull} "
                f"in {repo} to merge them.")
    return None


def _own_main(repo: Path) -> bool:
    """Whether this copy has a main branch of its own. A clone made at another branch, or at a commit, has none."""
    return bool(_git(repo, "for-each-ref", f"refs/heads/{BRANCH}"))


def _look(repo: Path, demo: bool, fresh: bool) -> dict:
    """Compare this copy with GitHub's main, fetching that first if `fresh` or the last fetch is an hour old."""
    if not shutil.which("git"):
        return {"available": False, "error": "git isn't installed, so Pyrite can't tell whether it's up to date."}
    if not (repo / ".git").exists():
        return {"available": False, "error": f"{repo} isn't a git clone, so Pyrite can't tell whether it's up to date."}
    try:
        # get-url applies any url.insteadOf rewrite, so this is the address the fetch really uses.
        if _git(repo, "remote", "get-url", REMOTE).lower().startswith(PLAIN):
            return {"available": False, "error": f"Pyrite's code folder fetches from {REMOTE} over an unencrypted "
                                                 "connection, so it isn't updated from here. Point it at an https:// "
                                                 "or SSH address with `git remote set-url`."}
        when, failed = _fetched.get(str(repo), (None, None))
        if fresh or when is None or time.monotonic() - when >= CHECK_EVERY:
            try:
                _git(repo, "fetch", "--quiet", "--no-tags", REMOTE, BRANCH)
                failed = None
            except GitError as err:
                failed = str(err)
            _fetched[str(repo)] = (time.monotonic(), failed)
        if failed:
            raise GitError(failed)
        behind = int(_git(repo, "rev-list", "--count", f"HEAD..{LATEST}"))
        ahead = int(_git(repo, "rev-list", "--count", f"{LATEST}..HEAD"))
        found: dict = {"available": behind > 0, "behind": behind, "current": _git(repo, "rev-parse", "--short", "HEAD")}
        if behind:
            # A merge says nothing about the code, so only the commits it brought in are listed. The list is empty when
            # GitHub's main is ahead only by merging what this copy already has.
            subjects = _git(repo, "log", "--no-merges", "--format=%s", f"-n{MAX_CHANGES + 1}", f"HEAD..{LATEST}")
            found["changes"] = subjects.splitlines()
            found["latest"] = _git(repo, "rev-parse", "--short", LATEST)
            name = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
            branch = found["branch"] = None if name == "HEAD" else name
            edited = bool(_git(repo, "status", "--porcelain", "--untracked-files=no"))
            if branch == BRANCH:
                ours = ahead
            else:
                ours = int(_git(repo, "rev-list", "--count", f"{LATEST}..refs/heads/{BRANCH}")) if _own_main(repo) else 0
            found["why_not"] = why_not(repo, branch, edited, ahead, ours, demo)
            # Off main with nothing in the way, everything checked out is already in GitHub's main, so switching to
            # main and moving that forward leaves nothing behind.
            found["switch"] = branch != BRANCH and found["why_not"] is None
        return found
    except GitError as err:
        return {"available": False, "error": f"Couldn't check GitHub for a newer Pyrite: {err}"}


def check(repo: Path = CODE_ROOT, demo: bool = False, fresh: bool = False) -> dict:
    """Whether GitHub's main is ahead of this copy. GitHub is asked at most once an hour unless `fresh`, but this copy
    is read again every time, so the answer follows a branch switched or an edit stashed since the last one.

    `available` says there's something to update to, `behind` how many commits, `changes` the subjects of up to
    MAX_CHANGES + 1 of them that aren't merges (the page counts past MAX_CHANGES), `branch` the one checked out, or
    None for none, `why_not` why the dashboard can't do the update, and `switch` that the update would switch this copy
    to main first. `error` is why nothing could be told."""
    with _lock:
        return _look(repo, demo, fresh)


def forget() -> None:
    """Drop the last fetch, so the next check asks GitHub."""
    with _lock:
        _fetched.clear()


def apply(repo: Path = CODE_ROOT, demo: bool = False, python: str = sys.executable, switch: bool = False) -> dict:
    """Move this copy forward to GitHub's main, and install the packages again if tools/requirements.txt changed.

    A copy on main is fast-forwarded. One on another branch, or on none, with nothing GitHub's main lacks is switched
    to main, which is moved forward first, but only when `switch` says whoever asked was told so. The branch it was on
    is kept.

    Raises ValueError, with why, when there's nothing to update to or it can't be done safely. Returns what changed:
    the commits it moved from and to, how many, whether it switched and the branch it was on, and what installing the
    packages said, if they were installed."""
    if not _lock.acquire(blocking=False):
        raise ValueError("An update or a check is already going. Try again in a moment.")
    try:
        found = _look(repo, demo, fresh=True)
        if found.get("error"):
            raise ValueError(found["error"])
        if not found["available"]:
            raise ValueError("Pyrite is already up to date.")
        if found.get("why_not"):
            raise ValueError(found["why_not"])
        if found["switch"] and not switch:
            raise ValueError(f"Pyrite's code folder isn't on {BRANCH} any more, so updating it now means switching it to "
                             f"{BRANCH}. Open Update available again to see what that does.")
        try:
            changed = _git(repo, "diff", "--name-only", "HEAD", LATEST).splitlines()
            if not found["switch"]:
                _git(repo, "merge", "--ff-only", "--quiet", LATEST)
            elif _own_main(repo):
                # Main moves forward before it's checked out, so a step git refuses leaves the code as it was.
                _git(repo, "fetch", "--quiet", "--no-tags", ".", f"refs/remotes/{LATEST}:refs/heads/{BRANCH}")
                _git(repo, "checkout", "--quiet", BRANCH)
            else:
                _git(repo, "checkout", "--quiet", "-b", BRANCH, "--track", LATEST)
            done = {"from": found["current"], "to": _git(repo, "rev-parse", "--short", "HEAD"), "behind": found["behind"],
                    "switched": found["switch"], "branch": found["branch"], "packages": None}
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
