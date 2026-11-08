"""What's left to set up. A new workspace starts as a copy of the example, so this looks for what still is one.

Two kinds of finding. The workspace's own (example files left in place, sources that point nowhere)
are cheap file reads, so the dashboard lists them on every refresh. The tools (the PDF maker,
Claude Code, the mail login) take longer to look for, so only `pyrite doctor` checks them.
"""
import importlib.util
import shutil
import sys
import tomllib
from pathlib import Path

from . import inbox
from .claude_code import find_claude, signed_in
from .store import EXAMPLE_ROOT

# The profile files a new workspace copies from the example and must then make its own.
OWN_FILES = ("profile/facts.md", "profile/approved-terms.txt", "profile/run-notes.md", "profile/resume.md", "profile/cover-letter.md")
SETUP_DOCS = 'See "Your workspace" in docs/operating.md.'
# Settings in search.toml that describe the fictional candidate rather than how Pyrite works. Left as they are, they
# quietly shape a real search: which places count as local, which words the assay blocks or lets through, what every
# resume is expected to name, and whose mail counts as a reply.
EXAMPLE_SETTINGS = (
    ("location", "local", "local under [location]"),
    ("location", "local_exact", "local_exact under [location]"),
    ("guard", "forbidden", "forbidden under [guard]"),
    ("guard", "unsupported", "unsupported under [guard]"),
    ("guard", "ordinary_words", "ordinary_words under [guard]"),
    ("guard", "expected_on_resume", "expected_on_resume under [guard]"),
    ("promote", "cities", "cities under [promote]"),
    ("inbox", "domains", "[inbox.domains]"),
)


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    except (OSError, UnicodeError):
        return None


def _example_config() -> dict:
    with (EXAMPLE_ROOT / "profile" / "search.toml").open("rb") as handle:
        return tomllib.load(handle)


def still_example(root: Path) -> list[str]:
    """The profile files that are still word for word the fictional example's."""
    if root.resolve() == EXAMPLE_ROOT:
        return []
    same = []
    for rel in OWN_FILES:
        mine, example = _text(root / rel), _text(EXAMPLE_ROOT / rel)
        if mine is not None and mine == example:
            same.append(rel)
    return same


def workspace_todos(root: Path, cfg: dict | None) -> list[dict]:
    """What a workspace still needs before Pyrite can do its job, each as {"what", "fix"}. Empty once it's set up."""
    if root.resolve() == EXAMPLE_ROOT:
        return [{"what": "No workspace is set, so this is the fictional example.",
                 "fix": f"Make a folder outside this repository, copy example/profile/ into it, and put its path in .pyrite-home. {SETUP_DOCS}"}]
    if cfg is None:
        return [{"what": "profile/search.toml is missing.", "fix": f"Copy example/profile/ into your workspace to start. {SETUP_DOCS}"}]
    todos = []
    for rel in still_example(root):
        todos.append({"what": f"{rel} is still the fictional example's.",
                      "fix": "Replace it with your own. Claude writes from these files, and the assay checks against them."})
    if not (root / "profile" / "facts.md").exists():
        todos.append({"what": "profile/facts.md is missing.",
                      "fix": "It's the fact bank every resume is checked against. Copy the example's and make it yours."})
    example = _example_config()
    if cfg.get("candidate", {}).get("name") == example["candidate"]["name"]:
        todos.append({"what": "[candidate] name in profile/search.toml is still the example's.", "fix": "Set it to your name, as it goes on your documents."})
    guard = cfg.get("guard", {})
    heading = guard.get("heading_source", "")
    if heading and not (root / heading).exists():
        todos.append({"what": f"heading_source under [guard] in profile/search.toml names {heading}, which isn't in your workspace.",
                      "fix": "Point it at your master resume. Until then the assay blocks every draft."})
    for rel in guard.get("approved_sources", []):
        if not (root / rel).exists():
            todos.append({"what": f"approved_sources under [guard] in profile/search.toml names {rel}, which isn't in your workspace.",
                          "fix": "Point it at a file you have, such as your master resume or letter, or remove it."})
    hosts = set(cfg.get("dashboard", {}).get("allowed_hosts", []))
    leftover = sorted(hosts & set(example.get("dashboard", {}).get("allowed_hosts", [])))
    if leftover:
        todos.append({"what": f"allowed_hosts under [dashboard] still lists the example's {', '.join(leftover)}.",
                      "fix": "Remove them. The dashboard has no login, so it should answer only to names you use."})
    same = [label for section, key, label in EXAMPLE_SETTINGS
            if cfg.get(section, {}).get(key) and cfg.get(section, {}).get(key) == example.get(section, {}).get(key)]
    if same:
        todos.append({"what": f"profile/search.toml still has the example's {', '.join(same)}.",
                      "fix": "They describe the fictional candidate: where they live, their confidential terms, and what their resume names. "
                             "Set them for your own search, or empty them."})
    todos += _seed_todos(root)
    return todos


def seed_still_example(root: Path) -> bool:
    """Whether profile/seed.toml is word for word the example's, whose applications belong to the fictional candidate."""
    path = root / "profile" / "seed.toml"
    return root.resolve() != EXAMPLE_ROOT and path.exists() and _text(path) == _text(EXAMPLE_ROOT / "profile" / "seed.toml")


def _seed_todos(root: Path) -> list[dict]:
    path = root / "profile" / "seed.toml"
    if not path.exists():
        return []
    if seed_still_example(root):
        return [{"what": "profile/seed.toml is still the fictional example's.",
                 "fix": "List the applications you made before Pyrite there, or delete it. `pyrite seed` imports it."}]
    try:
        with path.open("rb") as handle:
            seeds = tomllib.load(handle).get("application", [])
    except (OSError, tomllib.TOMLDecodeError) as err:
        return [{"what": "profile/seed.toml can't be read.", "fix": str(err)}]
    return [{"what": f"profile/seed.toml names the folder {seed['folder']}, which isn't in your workspace.",
             "fix": "Fix its path, or remove `folder` from that entry. `pyrite seed` skips it until then."}
            for seed in seeds if seed.get("folder") and not (root / seed["folder"]).is_dir()]


def _word_installed() -> bool:
    # sys.platform rather than os.name, so type checkers on other systems know winreg is never reached there.
    if sys.platform != "win32":
        return False
    import winreg

    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Word.Application"))
        return True
    except OSError:
        return False


def tool_checks(cfg: dict | None) -> list[dict]:
    """The programs Pyrite uses, each as {"ok": True | False | None, "what", "fix"}. None means optional and missing."""
    found = []
    has_docx = importlib.util.find_spec("docx") is not None
    found.append({"ok": has_docx, "what": "python-docx, which builds the documents",
                  "fix": "" if has_docx else f'Run: "{sys.executable}" -m pip install -r tools/requirements.txt'})
    if shutil.which("soffice"):
        found.append({"ok": True, "what": "LibreOffice, which makes the PDFs", "fix": ""})
    elif _word_installed():
        found.append({"ok": True, "what": "Word, which makes the PDFs", "fix": "LibreOffice is used instead when `soffice` is on PATH."})
    else:
        found.append({"ok": False, "what": "Something to make PDFs: LibreOffice or Word",
                      "fix": "Install LibreOffice and put `soffice` on PATH. Until then `pyrite finish` can't build a draft."})
    found.append({"ok": True if shutil.which("pdftotext") else None, "what": "poppler's pdftotext, which reads each PDF back as a parser would",
                  "fix": "" if shutil.which("pdftotext") else "Optional. Git for Windows includes it. Without it that step is skipped."})
    claude = find_claude()
    if not claude:
        found.append({"ok": False, "what": "Claude Code, which the daily run, Refresh resume and Interview prep use",
                      "fix": "Install Claude Code and sign in. Everything else works without it."})
    elif not signed_in(claude):
        found.append({"ok": False, "what": f"Claude Code is at {claude} but isn't signed in", "fix": f"Run once: {claude} auth login"})
    else:
        found.append({"ok": True, "what": f"Claude Code, signed in, at {claude}", "fix": ""})
    source = (cfg or {}).get("inbox", {}).get("source", "imap")
    if source == "gmail":
        found.append({"ok": True, "what": "Reply detection reads Gmail through Claude Code", "fix": "Test it with `pyrite inbox`."})
    elif inbox.CREDENTIALS_PATH.exists():
        found.append({"ok": True, "what": f"Reply detection reads mail with the login in {inbox.CREDENTIALS_PATH}", "fix": "Test it with `pyrite inbox`."})
    else:
        found.append({"ok": None, "what": "Reply detection isn't set up", "fix": 'Optional. See "Reply detection" in docs/operating.md.'})
    return found
