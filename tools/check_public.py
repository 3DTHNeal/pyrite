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
import functools
import html
import io
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

# Before the definitions below, which an older Python can't read: a privacy check that crashes mustn't look like one that ran.
if sys.version_info < (3, 11):  # noqa: UP036
    sys.exit("This check needs Python 3.11 or newer, and this is {}.{}. On Windows, `py -3 tools/check_public.py` runs the newest "
             "one installed, and elsewhere `python3` may be newer.".format(*sys.version_info[:2]))

REPO = Path(__file__).resolve().parents[1]

# Private files belong in the workspace. Anything under example/ is fictional and allowed. Matched in any case, since
# Windows and macOS treat Profile/ and profile/ as one folder, and including a database's journal and backups, and any
# .env file but an example one.
FORBIDDEN_PATH = re.compile(
    r"^(profile|applications|archive|data)/|(^|/)\.pyrite-home$"
    r"|\.(?:db|sqlite3?)(?:-shm|-wal|-journal)?(?:\.bak|\.old|~)?$"
    r"|(^|/)imap\.env(?:\.(?!example$)[^/]+)?$|(^|/)\.env(?:\.(?!example$|sample$|template$)[^/]+)?$",
    re.I,
)
# Binary files can't be read reliably, so only these places may hold them, and only the kinds read below: a .docx's
# text, a PDF's pages and a PNG's metadata. A spreadsheet or an archive there would pass with its insides unread.
BINARY_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".gif", ".zip", ".xlsx", ".pptx", ".db", ".sqlite", ".sqlite3"}
BINARY_ALLOWED = re.compile(r"^(example/applications/|docs/screenshots/)")
BINARY_KINDS = {".docx", ".pdf", ".png"}
# A zip's members are read up to this size each. A larger one, or one that won't open, is a finding, not a pass.
MEMBER_LIMIT = 50 * 1024 * 1024
UNREADABLE_ARCHIVE = "archive or document whose contents can't be read here, so nothing vouches for them"

# North American numbers, written with dashes, dots or spaces, and anything written with a country code.
PHONE = re.compile(r"(?<![\d.])(?:\(\d{3}\)\s?|\b\d{3}[-. ])\d{3}[-. ]\d{4}\b")
INTERNATIONAL_PHONE = re.compile(r"(?<![\w+])\+\d[\d ().-]{7,18}\d\b")
# Ten digits run together are a phone number only where something says so: a ten-digit order or build number isn't.
BARE_PHONE = re.compile(r"\b(?:phone|tel|telephone|mobile|cell|call|text|sms|fax|whatsapp)\b[^\d\n]{0,25}(?<![\d.+-])(1?\d{10})(?!\d)",
                        re.I)
UNREADABLE_PDF = "PDF whose pages can't be read here, so nothing vouches for them. Install poppler's pdftotext, or pypdf"
PDF_UTF16_STRING = re.compile(rb"\(\xfe\xff((?:[^()\\]|\\.)*)\)")
PDF_UTF16_HEX = re.compile(rb"<\s*FEFF([0-9A-Fa-f\s]+)>")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")
PERSONAL_EMAIL_DOMAIN = re.compile(
    r"^(gmail|googlemail|outlook|hotmail|live|yahoo|icloud|me|proton|protonmail|pm|aol|fastmail|comcast)\.", re.I)
TAILNET = re.compile(r"\b[a-z0-9-]+\.(tail[0-9a-f]{4,}|[a-z0-9-]+)\.ts\.net\b", re.I)
SAFE_TAILNET = re.compile(r"example-tailnet\.ts\.net$", re.I)
CGNAT_IP = re.compile(r"\b100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
# Windows doesn't care how "Users" is written, so neither does this. The Unix forms keep their case, since a web
# address such as api.example.com/users/name isn't a home folder.
USER_PATH = re.compile(r"(?:[A-Za-z]:[\\/]+(?i:users)[\\/]+|/home/|/Users/)([A-Za-z0-9._-]+)")
SAFE_USER = {"you", "me", "user", "username", "name", "example", "runner", "alex", "public"}
SECRET = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}|\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{16,}|\bsk-[A-Za-z0-9]{40,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|hooks\.slack\.com/services/[A-Za-z0-9_/-]{10,}"
    r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|\b[rs]k_live_[0-9A-Za-z]{16,}"
    r"|\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"  # a JSON web token
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)
# A secret written as a setting: `password = "..."`, `IMAP_TOKEN: ...`, `aws_secret_access_key=...`. The value has to
# look like one, with letters and digits, so code that passes a variable along (`token = cfg.token`) isn't one.
ASSIGNED_SECRET = re.compile(
    r"[\w.-]*(?:password|passwd|passphrase|secret|token|api_?key|access_?key)[\w.-]*[\"']?\s*[=:]\s*"
    r"(?P<quote>[\"']?)(?P<value>[^\s\"'`<>{}()\[\],;]{8,})(?P=quote)", re.I)
PLACEHOLDER = re.compile(r"(?:your|my|the|some|example|dummy|fake|placeholder|changeme|redacted|x+|\*+)\b|https?:", re.I)
# A Gmail app password as Google shows it: four groups of four letters. The start of the alphabet is the usual stand-in.
APP_PASSWORD = re.compile(r"password\w*[\"']?\s*[=:]\s*[\"']?(?!abcd efgh ijkl mnop)[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}\b", re.I)


def builtin_findings(text: str) -> list[str]:
    """Personal data recognizable without knowing whose it is."""
    found = []
    for match in PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        # 555 as the area code or the exchange marks a number as made up. Elsewhere in a number it means nothing.
        if "555" not in (digits[:3], digits[3:6]):
            found.append(f"phone number {match.group(0)}")
    for match in INTERNATIONAL_PHONE.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 11 and digits.startswith("1"):
            # A North American number with its country code. Written "+1 312-867-5309", it was judged above; written
            # "+13128675309" or "+1.312.867.5309", it wasn't, and the same 555 rule settles it.
            if not PHONE.search(match.group(0)) and "555" not in (digits[1:4], digits[4:7]):
                found.append(f"phone number {match.group(0)}")
        elif 9 <= len(digits) <= 15:
            found.append(f"phone number {match.group(0)}")
    for match in BARE_PHONE.finditer(text):
        digits = match.group(1)[-10:]
        if "555" not in (digits[:3], digits[3:6]):
            found.append(f"phone number {match.group(1)}")
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
    for match in ASSIGNED_SECRET.finditer(text):
        # Judged as it reads, so the digits of an escape such as ä in a test's made-up password don't count.
        value = re.sub(r"\\(?:u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2}|.)", "", match.group("value"))
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value) and not PLACEHOLDER.match(value):
            found.append(f"credential {match.group(0)[:20]}...")
    found += [f"credential {m.group(0)[:20]}..." for m in APP_PASSWORD.finditer(text)]
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
            data = blob[position + 8:position + 8 + length]
            # EXIF's Windows fields, such as XPAuthor, hold UTF-16 text, which reads as letters and NULs byte by byte.
            parts += [data.decode("latin-1"), utf16_text(data)]
        elif kind == b"zTXt":
            try:
                compressed = blob[position + 8:position + 8 + length].split(b"\0", 1)[1][1:]
                parts.append(zlib.decompress(compressed).decode("latin-1"))
            except (IndexError, zlib.error):
                parts.append("unreadable")
        position += length + 12
    return "\n".join(parts)


@functools.lru_cache(maxsize=1)
def _pdftotext() -> str | None:
    """poppler's pdftotext, from PATH or from beside git: Git for Windows ships it, though not on PATH outside Git Bash."""
    found = shutil.which("pdftotext")
    if found:
        return found
    try:
        exec_path = Path(subprocess.run(["git", "--exec-path"], capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        return None
    candidate = exec_path.parents[1] / "bin" / "pdftotext.exe"
    return str(candidate) if candidate.exists() else None


def pdf_text(blob: bytes) -> str | None:
    """The words on a PDF's pages, or None if nothing here can read them.

    A PDF stores its text as glyph codes, so inflating its streams finds nothing readable.
    This needs a real reader: pypdf if it's installed, and otherwise pdftotext.
    """
    try:
        import pypdf
    except ImportError:
        pypdf = None
    if pypdf:
        try:
            return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(io.BytesIO(blob)).pages)
        except Exception:
            return None
    tool = _pdftotext()
    if not tool:
        return None
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "blob.pdf"
        source.write_bytes(blob)
        try:
            out = subprocess.run([tool, "-enc", "UTF-8", str(source), "-"], capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


def pdf_metadata(blob: bytes) -> str:
    """A PDF's author, title and the like, which Word writes as UTF-16 and a plain read can't see."""
    parts = []
    for match in PDF_UTF16_STRING.finditer(blob):
        raw = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), match.group(1))
        parts.append(re.sub(rb"\\(.)", rb"\1", raw, flags=re.S).decode("utf-16-be", "replace"))
    for match in PDF_UTF16_HEX.finditer(blob):
        digits = re.sub(rb"\s", b"", match.group(1))
        parts.append(bytes.fromhex(digits[:len(digits) // 4 * 4].decode()).decode("utf-16-be", "replace"))
    return "\n".join(parts)


def looks_binary(blob: bytes) -> bool:
    """The test git itself uses: text has no NUL bytes near its start."""
    return b"\0" in blob[:8000]


def utf16_text(data: bytes) -> str:
    """Runs of UTF-16 text in either byte order, at any offset: a name in EXIF or a Windows field."""
    runs = [m.group(0).decode("utf-16-le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){3,}", data)]
    runs += [m.group(0).decode("utf-16-be") for m in re.finditer(rb"(?:\x00[\x20-\x7e]){3,}", data)]
    return "\n".join(runs)


def xml_text(xml: str) -> str:
    """The words in a document's XML as a reader sees them.

    Word splits a paragraph into runs wherever the formatting changes, even inside a word, and writes characters as
    entities such as `&#105;`. So the text of each paragraph is joined up with its entities read, and the whole part
    is given again with a space for every tag, so words in neighboring cells aren't run together either.
    """
    paragraphs = re.split(r"</(?:w:p|a:p|text:p|text:h|si|row)>", xml)
    joined = [html.unescape(re.sub(r"<[^>]+>", "", paragraph)) for paragraph in paragraphs]
    return "\n".join(joined) + "\n" + html.unescape(re.sub(r"<[^>]+>", " ", xml))


def archive_text(blob: bytes, depth: int = 0) -> tuple[list[str], list[str]]:
    """The text of every member of a zip, a .docx, .xlsx or .pptx among them, and of zips inside it. Also what
    couldn't be read, since a member nobody read is one nobody checked."""
    parts: list[str] = []
    problems: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if info.file_size > MEMBER_LIMIT:
                    problems.append(f"{UNREADABLE_ARCHIVE}: {info.filename} is too large to read")
                    continue
                data = archive.read(info)
                text = data.decode("utf-8", "replace")
                parts.append(text)
                if data.startswith(b"PK\x03\x04"):
                    if depth < 3:
                        inner, trouble = archive_text(data, depth + 1)
                        parts += inner
                        problems += trouble
                    else:
                        problems.append(f"{UNREADABLE_ARCHIVE}: {info.filename} is nested too deep to read")
                elif text.lstrip().startswith("<"):
                    parts.append(xml_text(text))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error) as err:
        problems.append(f"{UNREADABLE_ARCHIVE} ({type(err).__name__})")
    return parts, problems


def is_archive(path: str, blob: bytes) -> bool:
    return blob.startswith(b"PK\x03\x04") or Path(path).suffix.lower() in (".docx", ".xlsx", ".pptx", ".zip")


def readable_text(path: str, blob: bytes) -> str:
    """The text of a blob, including what's inside documents, since a .docx is a zip and a PDF deflates its streams.

    What a screenshot shows can't be read this way, so look at every image before committing it.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return png_metadata(blob)
    parts = [blob.decode("utf-8", "replace")]
    if is_archive(path, blob):
        parts += archive_text(blob)[0]
    elif suffix == ".pdf":
        for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", blob, re.S):
            try:
                parts.append(zlib.decompress(stream).decode("latin-1"))
            except zlib.error:
                pass
        parts.append(pdf_metadata(blob))
    return "\n".join(parts)


def scan_blob(path: str, blob: bytes, denylist: list[re.Pattern]) -> list[str]:
    found = []
    if FORBIDDEN_PATH.search(path):
        found.append("private path")
    suffix = Path(path).suffix.lower()
    # By content as well as by name, so a database or an archive under some other extension doesn't pass as text.
    binary = suffix in BINARY_SUFFIXES or looks_binary(blob) or blob.startswith(b"PK\x03\x04")
    if binary and not BINARY_ALLOWED.search(path):
        found.append("binary file outside example/ and docs/screenshots/")
    elif binary and suffix not in BINARY_KINDS:
        found.append(f"binary file of a kind this doesn't read ({suffix or 'no extension'}): only .docx, .pdf and .png may go there")
    if is_archive(path, blob):
        found += archive_text(blob)[1]
    text = readable_text(path, blob)
    if suffix == ".pdf":
        pages = pdf_text(blob)
        if pages is None:
            found.append(UNREADABLE_PDF)
        else:
            # Once as laid out, and once on one line, so a name broken across lines is still found.
            text += "\n" + pages + "\n" + re.sub(r"\s+", " ", pages)
    # This file and its tests name these patterns in order to catch them.
    if path not in ("tools/check_public.py", "tools/tests/test_check_public.py"):
        found += builtin_findings(text)
        found += [f"{finding}, in the file's path" for finding in builtin_findings(path)]
    found += denylist_findings(text, denylist)
    # A folder named after an employer publishes the name as surely as a file that mentions it.
    found += [f"{finding}, in the file's path" for finding in denylist_findings(path, denylist)]
    return found


def ref_findings(names: list[str], denylist: list[re.Pattern]) -> list[str]:
    """Branch and tag names are published with a push, like everything else."""
    text = "\n".join(names)
    return [f"branch or tag name: {finding}" for finding in builtin_findings(text) + denylist_findings(text, denylist)]


def _git(*args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True, input=data).stdout


GITLINK = "160000"
SUBMODULE = "submodule, whose files are in another repository this doesn't read, so nothing vouches for them"


def tree_entries(gitlinks: set[str] | None = None) -> dict[str, set[str]]:
    """Everything ever committed, plus what's staged. Maps each blob id to every path it has had.

    Every path, because the same content can sit at an allowed path in one commit and a private one in another.
    A submodule is a commit id, not a blob, so its path goes into `gitlinks` instead.
    """
    seen: dict[str, set[str]] = {}
    links = gitlinks if gitlinks is not None else set()
    has_commits = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0
    commits = _git("rev-list", "--all").decode().split() if has_commits else []
    for commit in commits:
        for line in _git("ls-tree", "-r", "-z", commit).decode("utf-8", "replace").split("\0"):
            if line:
                meta, path = line.split("\t", 1)
                _mode, kind, object_id = meta.split()
                if kind == "blob":
                    seen.setdefault(object_id, set()).add(path)
                else:
                    links.add(path)
    for line in _git("ls-files", "-s", "-z").decode("utf-8", "replace").split("\0"):
        if line:
            meta, path = line.split("\t", 1)
            mode, object_id = meta.split()[:2]
            if mode == GITLINK:
                links.add(path)
            else:
                seen.setdefault(object_id, set()).add(path)
    return seen


def tag_messages() -> list[str]:
    """Each annotated tag's text: its tagger's name and address, and its message."""
    found = []
    for line in _git("for-each-ref", "--format=%(objecttype) %(objectname)", "refs/tags").decode("utf-8", "replace").splitlines():
        kind, _, object_id = line.partition(" ")
        if kind == "tag":
            found.append(_git("cat-file", "tag", object_id).decode("utf-8", "replace"))
    return found


def scan_repository(denylist: list[re.Pattern]) -> list[str]:
    found: set[str] = set()
    gitlinks: set[str] = set()
    for blob_id, paths in tree_entries(gitlinks).items():
        blob = _git("cat-file", "blob", blob_id)
        for path in paths:
            found |= {f"{path}: {finding}" for finding in scan_blob(path, blob, denylist)}
    found |= {f"{path}: {SUBMODULE}" for path in gitlinks}
    problems = sorted(found)
    # Commit messages, identities and the names of branches and tags are published too, and so are annotated tags.
    if subprocess.run(["git", "-C", str(REPO), "rev-parse", "--verify", "-q", "HEAD"], capture_output=True).returncode == 0:
        log = _git("log", "--all", "--format=%h %an <%ae> %cn <%ce>%n%B").decode("utf-8", "replace")
        problems += [f"commit log: {finding}" for finding in builtin_findings(log) + denylist_findings(log, denylist)]
    for text in tag_messages():
        name = re.search(r"^tag (.*)$", text, re.M)
        problems += [f"tag {name.group(1) if name else '?'}: {finding}"
                     for finding in builtin_findings(text) + denylist_findings(text, denylist)]
    refs = _git("for-each-ref", "--format=%(refname)").decode("utf-8", "replace").split()
    problems += ref_findings(refs, denylist)
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
