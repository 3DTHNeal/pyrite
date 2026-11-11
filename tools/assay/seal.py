"""A pass is a sealed record. It keeps a SHA-256 hash of the text it passed and of everything it judged that text
against, so a change to any of them means the pass no longer vouches for what's there now. It can keep the checker's
version too, since a new version may judge the same text differently."""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import __version__

# The name the checker's version is kept under in a seal.
CHECKER_KEY = "assay version"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str | None:
    """A file's hash, or None when it can't be read."""
    try:
        return digest(path.read_bytes())
    except OSError:
        return None


def value_digest(value: Any) -> str:
    """A hash of rules or settings, the same however their keys are ordered."""
    return digest(json.dumps(value, sort_keys=True, default=str).encode())


def with_checker(prints: Mapping[str, Any]) -> dict[str, Any]:
    """A seal's hashes with the checker's version beside them, under `CHECKER_KEY`. `changed` then names that key once
    the checker is a different version, so a pass it gave no longer vouches under rules that may judge differently.
    A seal is only what its caller records: one that never adds the version is compared as it always was, and one
    recorded before the caller began adding it names the key once, as a change."""
    return {**prints, CHECKER_KEY: __version__}


def changed(recorded: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """The names whose hash differs between a recorded seal and now, including any that one of them lacks."""
    return sorted(name for name in set(recorded) | set(now) if recorded.get(name) != now.get(name))
