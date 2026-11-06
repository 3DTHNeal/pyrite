#!/usr/bin/env python3
"""Refuse to publish anything personal. Reads every commit, not just the current files.

Two layers:

1. Built-in checks need nothing private, so they run in CI too. They look for private
   paths, databases, phone numbers, personal email addresses, private network names
   and addresses, and credentials.
2. A denylist of terms that only you know (employers, internal names, targets). It
   stays in your private workspace, because a public list of secrets would be a leak
   in itself. This layer runs from the pre-push hook on your machine.

Usage:
    python tools/check_public.py                       built-in checks only
    python tools/check_public.py --denylist FILE       both layers

Findings print the term, so keep this output out of public CI logs: only the built-in
layer runs there. Exit status is 1 if anything is found.
"""
import argparse
import io
import re
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Private files belong in the workspace. Anything under example/ is fictional and allowed.
FORBIDDEN_PATH = re.compile(
    r"^(profile|applications|archive|data)/|(^|/)\.warroom-home$|\.db(-shm|-wal)?$|(^|/)imap\.env$|(^|/)\.env$"
)
# Binary files can't be read reliably, so only these places may hold them.
BINARY_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".xlsx", ".pptx", ".db", ".sqlite"}
BINARY_ALLOWED = re.compile(r"^(example/applications/|docs/screenshots/)")

PHONE = re.compile(r"(?<![\d.])(?:\(\d{3}\)\s?|\b\d{3}[-.])\d{3}[-.]\d{4}\b")
FICTIONAL_PHONE = re.compile(r"555")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
PERSONAL_EMAIL_DOMAIN = re.compile(r"^(gmail|googlemail|outlook|hotmail|live|yahoo|icloud|me|proton|protonmail|aol)\.", re.I)
TAILNET = re.compile(r"\b[a-z0-9-]+\.(tail[0-9a-f]{4,}|[a-z0-9-]+)\.ts\.net\b", re.I)
SAFE_TAILNET = re.compile(r"example-tailnet\.ts\.net$", re.I)
CGNAT_IP = re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
USER_PATH = re.compile(r"(?:[A-Za-z]:[\\/]+Users[\\/]+|/home/|/Users/)([A-Za-z0-9._-]+)")
SAFE_USER = {"you", "me", "user", "username", "name", "example", "runner", "alex", "public"}
SECRET = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def builtin_findings(text: str) -> list[str]:
    """Personal data recognizable without knowing whose it is."""
    found = []
    for match in PHONE.finditer(text):
        if not FICTIONAL_PHONE.search(match.group(0)):
            found.append(f"phone number {match.group(0)}")
    for match in EMAIL.finditer(text):
        domain = match.group(1)
        if PERSONAL_EMAIL_DOMAIN.match(domain):
            found.append(f"personal email address {match.group(0)}")
    for match in TAILNET.finditer(text):
        if not SAFE_TAILNET.search(match.group(0)):
            found.append(f"private network name {match.group(0)}")
    found += [f"private network address {m.group(0)}" for m in CGNAT_IP.finditer(text)]
    for match in USER_PATH.finditer(text):
        if match.group(1).lower() not in SAFE_USER and not match.group(1).startswith("<"):
            found.append(f"home folder path {match.group(0)}")
    found += [f"credential {m.group(0)[:12]}..." for m in SECRET.finditer(text)]
    return found


def load_denylist(path: Path) -> list[re.Pattern]:
    """One case-insensitive regular expression per line. Blank lines and # comments are skipped."""
    patterns = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(re.compile(line, re.I))
    if not patterns:
        raise SystemExit(f"The denylist {path} is empty, so it would prove nothing.")
    return patterns


def denylist_findings(text: str, denylist: list[re.Pattern]) -> list[str]:
    return [f"denylisted term {m.group(0)!r}" for pattern in denylist for m in [pattern.search(text)] if m]


def png_metadata(blob: bytes) -> str:
    """A PNG's text and EXIF chunks. Its pixels are compressed noise that can spell anything by chance."""
    parts, position = [], 8
    while position + 8 <= len(blob):
        length = int.from_bytes(blob[position:position + 4], "big")
        kind = blob[position + 4:position + 8]
        if kind in (b"tEXt", b"iTXt", b"eXIf"):
            parts.append(blob[position + 8:position + 8 + length].decode("latin-1"))
        elif kind == b"zTXt":
            try:
                compressed = blob[position + 8:position + 8 + length].split(b"\0", 1)[1][1:]
                parts.append(zlib.decompress(compressed).decode("latin-1"))
            except (IndexError, zlib.error):
                parts.append("unreadable")
        position += length + 12
    return "\n".join(parts)


def readable_text(path: str, blob: bytes) -> str:
    """The text of a blob, including what's inside documents, since a .docx is a zip and a PDF deflates its streams.

    What a screenshot shows can't be read this way, so look at every image before committing it.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return png_metadata(blob)
    parts = [blob.decode("utf-8", "replace")]
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as archive:
                for name in archive.namelist():
                    parts.append(archive.read(name).decode("utf-8", "replace"))
        except zipfile.BadZipFile:
            parts.append("unreadable")
    elif suffix == ".pdf":
        for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", blob, re.S):
            try:
                parts.append(zlib.decompress(stream).decode("latin-1"))
            except zlib.error:
                pass
    return "\n".join(parts)


def scan_blob(path: str, blob: bytes, denylist: list[re.Pattern]) -> list[str]:
    found = []
    if FORBIDDEN_PATH.search(path):
        found.append("private path")
    if Path(path).suffix.lower() in BINARY_SUFFIXES and not BINARY_ALLOWED.search(path):
        found.append("binary file outside example/ and docs/screenshots/")
    text = readable_text(path, blob)
    # This file and its tests name these patterns in order to catch them.
    if path not in ("tools/check_public.py", "tools/tests/test_check_public.py"):
        found += builtin_findings(text)
    found += denylist_findings(text, denylist)
    return found


def _git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True, input=data).stdout


def tree_entries() -> dict[str, str]:
    """Every (path, blob) ever committed, plus what's staged. Maps blob id to one path it had."""
    seen: dict[str, str] = {}
    has_commits = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0
    commits = _git("rev-list", "--all").decode().split() if has_commits else []
    for commit in commits:
        for line in _git("ls-tree", "-r", "-z", commit).decode("utf-8", "replace").split("\0"):
            if line:
                meta, path = line.split("\t", 1)
                seen.setdefault(meta.split()[2], path)
    for line in _git("ls-files", "-s", "-z").decode("utf-8", "replace").split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            seen.setdefault(meta.split()[1], path)
    return seen


def scan_repository(denylist: list[re.Pattern]) -> list[str]:
    problems = []
    for blob_id, path in sorted(tree_entries().items(), key=lambda item: item[1]):
        blob = _git("cat-file", "blob", blob_id)
        problems += [f"{path}: {finding}" for finding in scan_blob(path, blob, denylist)]
    # Commit messages and identities are published too.
    if subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0:
        log = _git("log", "--all", "--format=%h %an <%ae> %cn <%ce>%n%B").decode("utf-8", "replace")
        problems += [f"commit log: {finding}" for finding in builtin_findings(log) + denylist_findings(log, denylist)]
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--denylist", type=Path, help="your private list of terms that must never be published")
    args = parser.parse_args()

    denylist = load_denylist(args.denylist) if args.denylist else []
    problems = scan_repository(denylist)
    for problem in problems:
        print(problem)
    scope = f"built-in checks and {len(denylist)} denylist terms" if denylist else "built-in checks only"
    if problems:
        print(f"\nBLOCKED: {len(problems)} problem(s) found ({scope}).")
        return 1
    print(f"Clean: every commit and the staged files pass ({scope}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
