"""A one-time code that shows a person at this computer agreed to loosen the fact check.

The dashboard has no login, so a request can't show who sent it. Tightening a check is always safe and needs nothing.
A change that lets drafts say more (approving a term, unblocking a confidential name or an unsupported claim, trusting
another source) needs a six-digit code that Pyrite sends to this computer's notifications, naming the change. The
server decides what counts as loosening by comparing the files before and after, so the page can't talk its way out of
it, and a code works once, for that exact change, for two minutes.

It isn't a password: anyone who can see this screen can read the code. What it stops is a change made from somewhere
else, or by something driving the browser, without the person at this computer seeing it named.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import tomllib
from pathlib import Path

from . import factsdoc, notify, store

LIFETIME_SECONDS = 120
TRIES = 5
# Codes asked for in a window. Each one is a notification, so this also stops them being used to flood the screen.
REQUESTS_PER_WINDOW = 10
WINDOW_SECONDS = 600
# Settings that can only be changed in the file, whatever code comes with the change.
FILE_ONLY = (("dashboard", "allowed_hosts"),)

_lock = threading.Lock()
_salt = secrets.token_bytes(16)
_pending: dict | None = None
_asked: list[float] = []


class CodeNeeded(Exception):  # Not an error: the page answers it with a code.
    """The change loosens a check. A code has been sent, and `payload` tells the page what to ask for."""

    def __init__(self, payload: dict):
        super().__init__("This change needs a code from this computer.")
        self.payload = payload


class CodeError(ValueError):
    """The code given doesn't confirm this change, so nothing was changed."""


# ---------- what loosens a check ----------

def _terms(text: str) -> set[str]:
    """The words approved-terms.txt approves. The assay reads it word by word, and a line can hold several terms."""
    return {word for line in text.splitlines() if not line.lstrip().startswith("#")
            for word in re.split(r"[\s,;]+", line) if word}


def _excluded(text: str) -> dict[str, set[str]]:
    doc = factsdoc.Doc(text)
    return {section.title: {item.text.strip() for item in doc.items(section)}
            for section in doc.sections() if section.kind == "excluded"}


def _toml(text: str) -> dict:
    try:
        return tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError:
        return {}  # A file that won't read is refused when it's written. Here it just has nothing to compare.


def _get(config: dict, path: tuple[str, ...]):
    for part in path:
        config = config.get(part, {}) if isinstance(config, dict) else {}
    return config if config != {} else None


def _quoted(items) -> str:
    return ", ".join(f"“{item}”" for item in sorted(items))


def loosening(key: str, old: str, new: str) -> list[str]:
    """What a change to one profile file would let drafts do that they couldn't before, each as a phrase that
    finishes "This code will ...". Empty when the change only tightens or leaves the checks alone."""
    found: list[str] = []
    if key == "terms":
        for term in sorted(_terms(new) - _terms(old)):
            found.append(f"approve “{term}” for every draft")
    elif key == "facts":
        listed_before, listed_after = _excluded(old), _excluded(new)
        for title, items in listed_before.items():
            gone = items - listed_after.get(title, set())
            if gone:
                found.append(f"take {_quoted(gone)} off “{title}” in facts.md")
    elif key == "config":
        before, after = _toml(old), _toml(new)
        guard_before, guard_after = before.get("guard", {}), after.get("guard", {})
        for name, what in (("forbidden", "never mention"), ("unsupported", "haven't done")):
            gone = set(guard_before.get(name, [])) - set(guard_after.get(name, []))
            if gone:
                found.append(f"unblock the {what} pattern{'s' if len(gone) > 1 else ''} {_quoted(gone)}")
        added = set(guard_after.get("disclaimers", [])) - set(guard_before.get("disclaimers", []))
        if added:
            found.append(f"let {_quoted(added)} excuse a claim as a denial")
        added = set(guard_after.get("approved_sources", [])) - set(guard_before.get("approved_sources", []))
        if added:
            found.append(f"trust {_quoted(added)} as a source of what's true")
        if guard_before.get("heading_source") != guard_after.get("heading_source"):
            found.append(f"match every draft's headings to “{guard_after.get('heading_source', '')}”")
        added = set(guard_after.get("ordinary_words", [])) - set(guard_before.get("ordinary_words", []))
        if added:
            found.append(f"stop questioning the word{'s' if len(added) > 1 else ''} {_quoted(added)}")
        for name, what in (("max_resume_pages", "resume"), ("max_letter_pages", "letter")):
            if (guard_after.get(name) or 0) > (guard_before.get(name) or 0):
                found.append(f"allow a {what} of {guard_after[name]} pages")
        if not _get(before, ("workday", "autofill")) and _get(after, ("workday", "autofill")):
            found.append("turn on Workday autofill")
    return found


def file_only(key: str, old: str, new: str) -> str | None:
    """Why the change can't be made from the dashboard at all, if it can't."""
    if key != "config":
        return None
    for path in FILE_ONLY:
        if _get(_toml(old), path) != _get(_toml(new), path):
            return (f"{'.'.join(path)} in search.toml can only be changed in the file: the dashboard has no login, "
                    "so it never decides which names it answers to.")
    return None


# ---------- codes ----------

def _hash(code: str) -> str:
    return hashlib.sha256(_salt + code.encode()).hexdigest()


def _fingerprint(changes: dict[str, str], based_on: dict) -> str:
    """The exact change a code is for: each file's new text and the version it was based on."""
    shape = {key: [str(based_on.get(key, "")), hashlib.sha256(text.encode()).hexdigest()] for key, text in changes.items()}
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _code_file() -> Path:
    return store.ROOT / "data" / "confirm-code.json"


def _purpose(summary: list[str]) -> str:
    """What the code confirms, as a phrase that finishes "to ..." or "This code will ..."."""
    more = len(summary) - 1
    return summary[0] + (f", and make {more} more change{'s' if more > 1 else ''} to what drafts may say" if more else "")


def sentence(summary: list[str]) -> str:
    return f"This code will {_purpose(summary)}."


def message(code: str, summary: list[str]) -> tuple[str, str]:
    """The notification's title and text. The title carries the code, since it's the line every system shows in full,
    and the text says where it goes. On Windows the notification is labelled Windows PowerShell, the app that shows it,
    so both name Pyrite."""
    title = f"Pyrite code: {code[:3]} {code[3:]}"
    body = (f"Type it into the Pyrite dashboard, where it's asking for a code, to {_purpose(summary)}. "
            f"It works once and expires in {LIFETIME_SECONDS // 60} minutes. "
            "Didn't ask for it? Close this, and nothing changes.")
    return title, body


def _clear() -> None:
    global _pending
    _pending = None
    _code_file().unlink(missing_ok=True)


def _issue(summary: list[str], fingerprint: str) -> dict:
    """A new code for this change. It replaces any code still waiting."""
    global _pending
    now = time.time()
    _asked[:] = [t for t in _asked if now - t < WINDOW_SECONDS]
    if len(_asked) >= REQUESTS_PER_WINDOW:
        raise CodeError("Too many codes have been asked for in the last few minutes. Wait a while, then try again.")
    _asked.append(now)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    _pending = {"id": secrets.token_urlsafe(12), "hash": _hash(code), "fingerprint": fingerprint, "summary": summary,
                "expires": now + LIFETIME_SECONDS, "tries": TRIES}
    path = _code_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"code": code, "summary": summary, "expires": _pending["expires"]}), encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    sent = notify.send(*message(code, summary))
    return {"needs_code": True, "request_id": _pending["id"], "changes": summary, "sent": sent,
            "expires_in": LIFETIME_SECONDS}


def require(changes: dict[str, str], current: dict[str, str], based_on: dict, request_id=None, code=None) -> None:
    """Let a write go ahead, or stop it. A change that loosens no check passes. One that does raises CodeNeeded
    with a fresh code sent, or, when a code is given, passes only if it's the right code for exactly this change."""
    for key, text in changes.items():
        refusal = file_only(key, current.get(key, ""), text)
        if refusal:
            raise ValueError(refusal)
    summary = [phrase for key, text in changes.items() for phrase in loosening(key, current.get(key, ""), text)]
    if not summary:
        return
    fingerprint = _fingerprint(changes, based_on)
    with _lock:
        if not request_id and not code:
            raise CodeNeeded(_issue(summary, fingerprint))
        pending = _pending
        if not pending or pending["id"] != request_id:
            raise CodeError("That code isn't waiting any more. Ask for a new one.")
        if time.time() > pending["expires"]:
            _clear()
            raise CodeError("That code has expired, so nothing was changed. Ask for a new one.")
        if pending["fingerprint"] != fingerprint:
            _clear()
            raise CodeError("That code was for a different change, so nothing was changed and it no longer works. "
                            "Ask for a new one.")
        digits = re.sub(r"\D", "", str(code or ""))
        if not hmac.compare_digest(_hash(digits), pending["hash"]):
            pending["tries"] -= 1
            if pending["tries"] <= 0:
                _clear()
                raise CodeError("Too many wrong codes, so nothing was changed. Ask for a new one.")
            left = pending["tries"]
            raise CodeError(f"That code doesn't match. {left} {'try' if left == 1 else 'tries'} left.")
        _clear()


def resend(request_id) -> dict:
    """A new code for the change a waiting code was for. The old code stops working."""
    with _lock:
        pending = _pending
        if not pending or pending["id"] != request_id:
            raise CodeError("That code isn't waiting any more. Make the change again to get a new one.")
        return _issue(pending["summary"], pending["fingerprint"])


def cancel(request_id) -> None:
    with _lock:
        if _pending and _pending["id"] == request_id:
            _clear()


def waiting() -> dict | None:
    """The code waiting to be typed, for `pyrite code`, or None."""
    path = _code_file()
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(found, dict) or float(found.get("expires", 0)) < time.time():
        return None
    return found
