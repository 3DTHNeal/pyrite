"""The candidate's own record, shown and edited on the dashboard's Facts tab.

These two files are what a resume may claim, so being able to change them from a page with no
login is a real trade: it was asked for, and it's fenced in. Only these two files can be written,
never a path the page supplies. A save is refused if the file changed since the page read it, and
the file from before each save is kept in History on the Profile tab, where it can be put back. The
patterns that block a term by name, under [guard] in search.toml, still can't be changed from the browser.
"""
import hashlib
from typing import Any

from . import profile, settings, store

# What the page may ask for, by key. The file names are fixed here and never come from a request.
FILES = {
    "facts": ("facts.md", "Fact bank"),
    "terms": ("approved-terms.txt", "Approved terms"),
}
MAX_BYTES = 200_000
# Tabs and line breaks are fine. Anything else below a space has no place in a text file.
ALLOWED_CONTROL = "\n\r\t"


def _path(key: str):
    return store.CONFIG_PATH.with_name(FILES[key][0])


def _read(key: str) -> str:
    path = _path(key)
    if not path.exists():
        return ""
    # newline="" keeps the file's own line endings, so the version matches what's on disk.
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def _version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def view() -> dict[str, Any]:
    files = []
    for key, (name, title) in FILES.items():
        text = _read(key)
        files.append({"key": key, "title": title, "path": f"profile/{name}", "version": _version(text),
                      "text": text.replace("\r\n", "\n")})
    return {"files": files, "editable": not store.IS_EXAMPLE}


def _clean(key, text) -> tuple[str, str]:
    """Refuse what a save would refuse about the text itself, or give back the key and text. The dashboard checks this
    before it asks for a code."""
    if key not in FILES:
        raise ValueError("That isn't a file the Facts tab can change.")
    if not isinstance(text, str):
        raise ValueError("Nothing to save.")
    if any(ord(char) < 32 and char not in ALLOWED_CONTROL for char in text) or "\x7f" in text:
        raise ValueError("That text has control characters in it, so it wasn't saved.")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"That's over {MAX_BYTES // 1000} KB, which is too long for this file, so it wasn't saved.")
    if key == "facts" and not text.strip():
        raise ValueError("The fact bank can't be empty: every draft would fail without it.")
    return key, text


def save(body: dict[str, Any]) -> dict[str, Any]:
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's facts can't be changed. Point PYRITE_HOME at your own workspace to edit yours.")
    key, text = _clean(body.get("file"), body.get("text"))
    with settings._lock:
        current = _read(key)
        if body.get("version") != _version(current):
            raise settings.Conflict("This file changed after you opened it, so nothing was saved. Reload the Facts tab to see the latest.")
        eol = "\r\n" if "\r\n" in current else "\n"
        text = (text.replace("\r\n", "\n").rstrip("\n") + "\n").replace("\n", eol)
        path = _path(key)
        # The file as it was goes into History on the Profile tab, as every save's does, where it can be put back.
        if path.exists() and text != current:
            profile.keep({key: current}, "Changed on the Facts tab")
        settings._write(path, text)
    return view()
