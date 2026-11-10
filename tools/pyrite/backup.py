"""The workspace in use, and copies of the one file in it that can't be regenerated.

data/pyrite.db is everything Pyrite tracks: each job, what happened to it, and the record of what passed the fact
check. The profile files can be written again and the documents built again, but the database can't. So the Profile
tab's Workspace and backup section shows where it is and how it's kept, and can copy it into data/backups.
"""
import os
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import store
from .workspace import _git

FOLDER = Path("data") / "backups"
# Copies kept in data/backups. Older ones are deleted as new ones are made.
KEEP = 10
# A copy older than this many days counts as no recent backup.
FRESH_DAYS = 14
NAME = re.compile(r"pyrite-(\d{8}-\d{6}-\d{6})\.db")
STAMP = "%Y%m%d-%H%M%S-%f"


def _folder(root: Path) -> Path:
    return root / FOLDER


def copies(root: Path) -> list[dict[str, Any]]:
    """The copies in data/backups, newest first, each as {"name", "at", "bytes"}."""
    folder = _folder(root)
    if not folder.is_dir():
        return []
    found = []
    for path in folder.iterdir():
        match = NAME.fullmatch(path.name)
        if match and path.is_file():
            at = datetime.strptime(match[1], STAMP).astimezone()
            found.append({"name": path.name, "at": at.isoformat(), "bytes": path.stat().st_size})
    return sorted(found, key=lambda copy: copy["name"], reverse=True)


def latest(root: Path) -> datetime | None:
    """When the newest copy in data/backups was made, or None if there isn't one. Reads names only."""
    folder = _folder(root)
    names = sorted(m[1] for m in (NAME.fullmatch(p.name) for p in folder.iterdir()) if m) if folder.is_dir() else []
    return datetime.strptime(names[-1], STAMP).astimezone() if names else None


def is_fresh(root: Path, now: datetime | None = None) -> bool:
    made = latest(root)
    return made is not None and (now or datetime.now(UTC)) - made < timedelta(days=FRESH_DAYS)


def make(root: Path) -> dict[str, Any]:
    """Copy data/pyrite.db into data/backups, and delete the copies beyond the newest KEEP. Returns the new copy.

    SQLite's own backup copies the database as it stands at one moment, even while a run is writing to it, which
    copying the file wouldn't: a copy taken halfway through a write can't be opened. The copy is written under a
    temporary name and renamed when it's whole, so a failure never leaves a broken copy among the good ones."""
    if root.resolve() == store.EXAMPLE_ROOT:
        raise ValueError("This is the demo, so there's nothing of yours to back up.")
    database = root / "data" / "pyrite.db"
    if not database.is_file():
        raise ValueError("There's no data/pyrite.db yet, so there's nothing to back up.")
    folder = _folder(root)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    while (target := folder / f"pyrite-{now.strftime(STAMP)}.db").exists():
        now += timedelta(microseconds=1)
    partial = target.with_name(target.name + ".partial")
    try:
        with closing(sqlite3.connect(database, timeout=30)) as source, closing(sqlite3.connect(partial)) as copy:
            source.backup(copy)
        os.replace(partial, target)
    except sqlite3.Error as err:
        raise ValueError(f"data/pyrite.db couldn't be copied: {err}. Nothing was changed.") from err
    finally:
        partial.unlink(missing_ok=True)
    made = copies(root)
    for old in made[KEEP:]:
        (folder / old["name"]).unlink(missing_ok=True)
    return made[0]


def _chosen_by() -> str:
    """What named the workspace in use: PYRITE_HOME, .pyrite-home, or nothing, for the demo."""
    if store.IS_EXAMPLE:
        return ""
    if os.environ.get("PYRITE_HOME", "").strip():
        return "PYRITE_HOME"
    return store.HOME_POINTER.name


def _git_state(root: Path) -> dict[str, Any]:
    """Whether the workspace is a git repository of its own, and whether data/pyrite.db is kept in it.

    git missing, or a folder that isn't a repository, reads as not one."""
    try:
        top = _git(root, "rev-parse", "--show-toplevel")
    except (OSError, ValueError):
        return {"repo": False, "inside": "", "tracked": False, "changed": False, "committed": "", "remote": False}
    outer = Path(top.stdout.strip()).resolve() if top.returncode == 0 and top.stdout.strip() else None
    if outer != root.resolve():
        # A repository further up, such as this code's own, which must never commit the workspace.
        return {"repo": False, "inside": str(outer or ""), "tracked": False, "changed": False, "committed": "", "remote": False}
    tracked = _git(root, "ls-files", "--error-unmatch", "data/pyrite.db").returncode == 0
    changed = bool(_git(root, "status", "--porcelain", "--", "data/pyrite.db").stdout.strip()) if tracked else False
    committed = _git(root, "log", "-1", "--format=%cI", "--", "data/pyrite.db").stdout.strip() if tracked else ""
    remote = bool(_git(root, "remote").stdout.strip())
    return {"repo": True, "inside": "", "tracked": tracked, "changed": changed, "committed": committed, "remote": remote}


def about(root: Path) -> dict[str, Any]:
    """What the Workspace and backup section shows: the folder in use and what named it, whether it's a git
    repository and keeps the database, the database's size and age, and the copies in data/backups."""
    database = root / "data" / "pyrite.db"
    stat = database.stat() if database.is_file() else None
    return {
        "folder": str(root),
        "code": str(store.CODE_ROOT),
        "demo": store.IS_EXAMPLE,
        "chosen_by": _chosen_by(),
        "git": _git_state(root),
        "database": {
            "path": "data/pyrite.db", "exists": stat is not None, "bytes": stat.st_size if stat else 0,
            "changed": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat() if stat else "",
        },
        "backups": {"folder": FOLDER.as_posix(), "keep": KEEP, "fresh_days": FRESH_DAYS, "copies": copies(root)},
    }
