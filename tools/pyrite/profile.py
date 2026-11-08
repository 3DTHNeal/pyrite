"""The workspace's profile files as one view, and the one way the Profile tab writes them.

These files decide what a resume may claim and what Pyrite searches for, and the dashboard that changes them has no
login. So the files it may write are fixed here by name and never come from a request. A write names the version of
each file it was based on and is refused if any has changed since. Several files change together or not at all, and
the text each one had before is kept in data/history, so any save can be put back.
"""
import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from . import factsdoc, settings, store

# What may be written, by key. The paths are fixed here and never come from a request.
FILES = {
    "facts": "profile/facts.md",
    "terms": "profile/approved-terms.txt",
    "run_notes": "profile/run-notes.md",
    "resume": "profile/resume.md",
    "letter": "profile/cover-letter.md",
    "config": "profile/search.toml",
}
MAX_BYTES = 200_000
ALLOWED_CONTROL = "\n\r\t"
# Earlier copies kept for each file. Older ones are deleted as new ones arrive.
HISTORY_KEEP = 50
ROLE_HEADING = re.compile(r"(?m)^####[ \t]+([^|\r\n]+?)[ \t]*(?:\||$)")


class Conflict(settings.Conflict):
    """A file changed after the page read it."""


def _path(key: str) -> Path:
    return store.ROOT / FILES[key]


def _history_dir() -> Path:
    return store.ROOT / "data" / "history"


def read(key: str) -> str:
    """A profile file's text exactly as it is on disk, line endings included, or "" if it doesn't exist."""
    path = _path(key)
    if not path.exists():
        return ""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def versions() -> dict[str, str]:
    return {key: version(read(key)) for key in FILES}


def known_titles(cfg: dict) -> tuple[str, ...]:
    """Job titles from the resume every draft's headings must match, which settle where a title with a comma ends."""
    source = cfg.get("guard", {}).get("heading_source", "")
    path = store.ROOT / source if source else None
    if not path or not path.is_file():
        return ()
    return tuple(dict.fromkeys(m.group(1).strip() for m in ROLE_HEADING.finditer(path.read_text(encoding="utf-8"))))


def _terms(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def view() -> dict:
    """What the Profile tab shows: each file's version, and the parts of them it edits."""
    texts = {key: read(key) for key in FILES}
    cfg = tomllib.loads(texts["config"]) if texts["config"] else {}
    doc = factsdoc.Doc(texts["facts"])
    employers, labeled, unread = doc.timeline(known_titles(cfg))
    contact = doc.contact()
    sections = []
    for section in doc.sections():
        if section.kind in ("contact", "timeline"):
            continue
        sections.append({
            "title": section.title, "kind": section.kind, "line": section.start,
            "items": [{"line": item.line, "level": item.level, "text": item.text} for item in doc.items(section)],
        })
    guard = cfg.get("guard", {})
    return {
        "editable": not store.IS_EXAMPLE,
        "versions": {key: version(text) for key, text in texts.items()},
        "exists": {key: _path(key).exists() for key in FILES},
        "basics": {
            "name": cfg.get("candidate", {}).get("name", ""),
            "contact": contact[1] if contact else "",
            "paper": cfg.get("documents", {}).get("paper", "letter"),
        },
        "timeline": {
            "employers": [{
                "line": employer.line, "name": employer.name, "single": employer.single,
                "start": employer.start, "end": employer.end,
                "roles": [{"line": role.line, "title": role.title, "place": role.place, "start": role.start,
                           "end": role.end, "note": role.note} for role in employer.roles],
            } for employer in employers],
            "other": [{"line": item.line, "label": item.label, "text": item.text} for item in labeled],
            # Lines that read as neither an employer nor a labeled line. The tab offers them as plain text.
            "unread": [{"line": line, "text": doc.bare(line)} for line in unread],
        },
        "sections": sections,
        "off_limits": {"forbidden": guard.get("forbidden", []), "unsupported": guard.get("unsupported", [])},
        "terms": _terms(texts["terms"]),
    }


def _clean(key: str, text) -> str:
    if key not in FILES:
        raise ValueError("That isn't a file the Profile tab can change.")
    if not isinstance(text, str):
        raise ValueError(f"Nothing to save for {FILES[key]}.")
    if any(ord(char) < 32 and char not in ALLOWED_CONTROL for char in text) or "\x7f" in text:
        raise ValueError(f"The text for {FILES[key]} has control characters in it, so nothing was saved.")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"{FILES[key]} would be over {MAX_BYTES // 1000} KB, so nothing was saved.")
    if key == "facts" and not text.strip():
        raise ValueError("The fact bank can't be empty: every draft would fail without it.")
    if key == "config":
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as err:
            raise ValueError(f"profile/search.toml wouldn't read after that change ({err}), so nothing was saved.") from err
        if not str(parsed.get("candidate", {}).get("name", "")).strip():
            raise ValueError("search.toml needs [candidate] name, so nothing was saved.")
    return text


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _keep(stamp: str, key: str, text: str, reason: str) -> None:
    """Keep the text a file had before a save, and note why it changed."""
    folder = _history_dir() / key
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}{Path(FILES[key]).suffix}"
    with open(folder / name, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    with open(_history_dir() / "log.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"stamp": stamp, "key": key, "file": name, "reason": reason}) + "\n")
    for old in sorted(folder.iterdir())[:-HISTORY_KEEP]:
        old.unlink(missing_ok=True)


def write(changes: dict, based_on: dict, reason: str) -> dict:
    """Write several profile files at once, each only if it hasn't changed since `based_on` says it was read.

    Every file's earlier text is kept in data/history first. If one write fails, the ones already made are put back,
    so a save never leaves half its files changed. Returns the new versions of every file."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's profile can't be changed. "
                         "Point PYRITE_HOME at your own workspace to edit yours.")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Nothing to save.")
    if not isinstance(based_on, dict):
        raise ValueError("The save didn't say which version it was based on.")
    reason = str(reason or "").strip()[:200] or "Changed on the Profile tab"
    texts = {key: _clean(key, text) for key, text in changes.items()}
    with settings._lock:
        current = {key: read(key) for key in texts}
        for key, text in current.items():
            if based_on.get(key) != version(text):
                raise Conflict(f"{FILES[key]} changed after you opened it, so nothing was saved. "
                               "Reload to see the latest, then make your change again.")
        changed = [key for key, text in texts.items() if text != current[key]]
        existed = {key: _path(key).exists() for key in changed}
        stamp = _stamp()
        for key in changed:
            if existed[key]:
                _keep(stamp, key, current[key], reason)
        done: list[str] = []
        try:
            for key in changed:
                _path(key).parent.mkdir(parents=True, exist_ok=True)
                settings._write(_path(key), texts[key])
                done.append(key)
        except Exception:
            for key in done:
                if existed[key]:
                    settings._write(_path(key), current[key])
                else:
                    _path(key).unlink(missing_ok=True)
            raise
    return versions()


def history(limit: int = 100) -> list[dict]:
    """Earlier copies, newest first, with why each file changed."""
    log = _history_dir() / "log.jsonl"
    if not log.exists():
        return []
    entries = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("key") in FILES:
            entry["kept"] = (_history_dir() / entry["key"] / str(entry.get("file", ""))).is_file()
            entries.append(entry)
    return entries[::-1][:limit]


def kept(key: str, stamp: str) -> str:
    """The text a file had just before the save at `stamp`."""
    if key not in FILES or not re.fullmatch(r"\d{8}T\d{12}Z", stamp or ""):
        raise ValueError("That isn't a saved copy.")
    path = _history_dir() / key / f"{stamp}{Path(FILES[key]).suffix}"
    if not path.is_file():
        raise ValueError("That copy is no longer kept.")
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()
