"""A pass is a sealed record. It keeps a SHA-256 hash of the text it passed and of everything it judged that text
against, so a change to any of them means the pass no longer vouches for what's there now."""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


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


def changed(recorded: Mapping[str, Any], now: Mapping[str, Any]) -> list[str]:
    """The names whose hash differs between a recorded seal and now, including any that one of them lacks."""
    return sorted(name for name in set(recorded) | set(now) if recorded.get(name) != now.get(name))
