"""What's left to set up. A new workspace starts as a copy of the example, so this looks for what still is one.

Two kinds of finding. The workspace's own (example files left in place, sources that point nowhere)
are cheap file reads, so the dashboard lists them on every refresh. The tools (the PDF maker,
Claude Code, the mail login) take longer to look for, so only `pyrite doctor` checks them.
"""
import importlib.util
import re
import shutil
import sys
import tomllib
from pathlib import Path

from . import inbox
from .checks import do_not_use
from .claude_code import find_claude, signed_in
from .store import EXAMPLE_ROOT

# The profile files a new workspace copies from the example and must then make its own.
OWN_FILES = ("profile/facts.md", "profile/approved-terms.txt", "profile/run-notes.md", "profile/resume.md", "profile/cover-letter.md")
SETUP_DOCS = 'See "Your workspace" in docs/operating.md.'
# Optional profile files that, left as the example's, would put the fictional candidate's answers into a real application.
OPTIONAL_FILES = {
    "profile/workday-paste.md": "Optional. Type your own Workday answers into it, or delete it: `pyrite fill` copies it into each job's fill sheet.",
}
FORMAT_DOCS = 'See "How the documents are written" in docs/operating.md.'
# Names copied from the docs as they are, rather than a person's.
PLACEHOLDER_NAMES = {"your name", "your full name", "name", "first last", "firstname lastname"}
# Settings in search.toml that describe the fictional candidate rather than how Pyrite works. Left as they are, they
# quietly shape a real search: which places count as local, which roles and industries rank first, which words the
# assay blocks or lets through, what every resume is expected to name, and whose mail counts as a reply.
# Each is (its path in the config, the table it's in as search.toml writes it, its key there, or None for the whole table).
EXAMPLE_SETTINGS = (
    (("location", "local"), "[location]", "local"),
    (("location", "local_exact"), "[location]", "local_exact"),
    (("track",), "[[track]]", None),
    (("promote", "cities"), "[promote]", "cities"),
    (("promote", "industry"), "[[promote.industry]]", None),
    (("guard", "forbidden"), "[guard]", "forbidden"),
    (("guard", "unsupported"), "[guard]", "unsupported"),
    (("guard", "ordinary_words"), "[guard]", "ordinary_words"),
    (("guard", "expected_on_resume"), "[guard]", "expected_on_resume"),
    (("inbox", "domains"), "[inbox.domains]", None),
)
CAPITALIZED = re.compile(r"\b[A-Z][\w+#-]*")


def _and(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _setting(cfg: dict, path: tuple[str, ...]):
    value: object = cfg
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def example_settings_left(cfg: dict, example: dict) -> str:
    """The example's settings still in cfg, grouped by table, as "[location] local and local_exact; [[track]]"."""
    tables: dict[str, list[str]] = {}
    for path, table, key in EXAMPLE_SETTINGS:
        mine = _setting(cfg, path)
        if mine and mine == _setting(example, path):
            tables.setdefault(table, []).extend([key] if key else [])
    return "; ".join(f"{table} {_and(keys)}".strip() for table, keys in tables.items())


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
    """What a workspace still needs before Pyrite can do its job, each as {"what", "fix"}. Empty once it's set up.

    Most also name the Profile section that fixes them as "step". The ones that block every draft, or let a
    confidential name through, add "severity": "bad"."""
    if root.resolve() == EXAMPLE_ROOT:
        return [{"what": "No workspace is set, so this is the fictional example.",
                 "fix": "Run `pyrite init ../my-job-search` to make yours beside this repository, or name another folder "
                        f"outside it. {SETUP_DOCS}", "step": "workspace"}]
    if cfg is None:
        return [{"what": "profile/search.toml is missing.", "fix": f"Copy example/profile/ into your workspace to start. {SETUP_DOCS}", "step": "workspace"}]
    todos = []
    same = still_example(root)
    if same:
        # One finding for all of them, since the fix is the same, with the first named in full so it's easy to find.
        names = [same[0], *(Path(rel).name for rel in same[1:])]
        todos.append({"what": f"{_and(names)} {'is' if len(same) == 1 else 'are'} still the fictional example's.",
                      "fix": "Replace each with your own, starting with facts.md. Claude writes from these files, and the "
                             "assay checks against them.", "step": "achievements"})
    for rel, fix in OPTIONAL_FILES.items():
        mine = _text(root / rel)
        if mine is not None and mine == _text(EXAMPLE_ROOT / rel):
            todos.append({"what": f"{rel} is still the fictional example's.", "fix": fix})
    if not (root / "profile" / "facts.md").exists():
        todos.append({"what": "profile/facts.md is missing.",
                      "fix": "It's the fact bank every resume is checked against. Copy the example's and make it yours.",
                      "step": "achievements"})
    example = _example_config()
    name = str(cfg.get("candidate", {}).get("name", "")).strip()
    if name == example["candidate"]["name"]:
        todos.append({"what": "[candidate] name in profile/search.toml is still the example's.",
                      "fix": "Set it to your name, as it goes on your documents.", "step": "basics"})
    elif name.strip("<>[]").lower() in PLACEHOLDER_NAMES:
        todos.append({"what": f'[candidate] name in profile/search.toml is "{name}", a placeholder.',
                      "fix": "Set it to your name, as it goes on your documents.", "step": "basics"})
    guard = cfg.get("guard", {})
    heading = guard.get("heading_source", "")
    if heading and not (root / heading).exists():
        todos.append({"what": f"heading_source under [guard] in profile/search.toml names {heading}, which isn't in your workspace.",
                      "fix": "Point it at your master resume. Until then the assay blocks every draft.", "step": "masters",
                      "severity": "bad"})
    for rel in guard.get("approved_sources", []):
        if not (root / rel).exists():
            todos.append({"what": f"approved_sources under [guard] in profile/search.toml names {rel}, which isn't in your workspace.",
                          "fix": "Point it at a file you have, such as your master resume or letter, or remove it.",
                          "step": "masters"})
    hosts = set(cfg.get("dashboard", {}).get("allowed_hosts", []))
    leftover = sorted(hosts & set(example.get("dashboard", {}).get("allowed_hosts", [])))
    if leftover:
        todos.append({"what": f"allowed_hosts under [dashboard] still lists the example's {', '.join(leftover)}.",
                      "fix": "Remove them. The dashboard has no login, so it should answer only to names you use."})
    left = example_settings_left(cfg, example)
    if left:
        todos.append({"what": f"profile/search.toml still has the example's {left}.",
                      "fix": "They describe the fictional candidate: where they live, the roles and industries they want, their "
                             "confidential terms, and what their resume names. Set them for your own search, or empty them.",
                      "step": "roles"})
    todos += _master_todos(root, cfg)
    todos += _unguarded_todos(root, cfg)
    todos += _seed_todos(root)
    return todos


def _master_todos(root: Path, cfg: dict) -> list[dict]:
    """The master resume and letter, checked for the form the assay reads. A master in another form gets past a
    look at the files and then fails every draft made from it, which is the wrong place to find out."""
    guard = cfg.get("guard", {})
    name = cfg.get("candidate", {}).get("name", "")
    # The assay's contact line is the first one in the approved sources, in the order search.toml lists them.
    contact = next((row.strip() for rel in guard.get("approved_sources", [])
                    for row in (_text(root / rel) or "").splitlines() if row.startswith("@ ")), None)
    todos = []
    for rel, kind in ((guard.get("heading_source", ""), "resume"), ("profile/cover-letter.md", "letter")):
        text = _text(root / rel) if rel else None
        if text is None or text == _text(EXAMPLE_ROOT / rel):
            continue  # Missing or still the example's, and either is named already.
        lines = [row.strip() for row in text.splitlines()]
        problems = []
        if name and f"# {name}" not in lines:
            problems.append(f"no '# {name}' line")
        if not any(row.startswith("@ ") for row in lines):
            problems.append("no '@ ' contact line")
        elif kind == "letter" and contact and contact not in lines:
            problems.append("a contact line that differs from the resume's")
        if kind == "resume":
            problems += [f"no '{heading}' section" for heading in ("## Experience", "## Education")
                         if not any(row.startswith(heading) for row in lines)]
            if not any(row.startswith("### ") for row in lines):
                problems.append("no '### Employer | dates' heading")
        if problems:
            todos.append({"what": f"{rel} has {_and(problems)}, so no {kind} drafted from it can pass the assay.",
                          "fix": f"Every {kind} is checked against it. {FORMAT_DOCS}", "step": "masters", "severity": "bad"})
    return todos


def unguarded_terms(facts: str, forbidden: list[str]) -> list[str]:
    """Capitalized terms under "Do not use" in facts.md that no pattern in [guard] forbidden matches. The assay reads
    nothing from that section, so a term listed only there isn't blocked by name. The first word of each line is
    skipped, since it's usually a label such as "Internal names:" or "Customer names"."""
    found: list[str] = []
    for row in do_not_use(facts).splitlines():
        line = row.strip().lstrip("-*").strip()
        spans = [match.span() for pattern in forbidden for match in re.finditer(pattern, line, re.I)]
        for term in list(CAPITALIZED.finditer(line))[1:]:
            covered = any(start < term.end() and term.start() < end for start, end in spans)
            if not covered and term.group(0) not in found:
                found.append(term.group(0))
    return found


def _unguarded_todos(root: Path, cfg: dict) -> list[dict]:
    facts = _text(root / "profile" / "facts.md")
    if facts is None or facts == _text(EXAMPLE_ROOT / "profile" / "facts.md"):
        return []
    terms = unguarded_terms(facts, cfg.get("guard", {}).get("forbidden", []))
    if not terms:
        return []
    return [{"what": f"profile/facts.md lists {_and(terms)} under \"Do not use\", but forbidden under [guard] in "
                     f"profile/search.toml doesn't block {'it' if len(terms) == 1 else 'them'}.",
             "fix": f"The assay blocks only what forbidden names, so add a pattern for each, such as '\\b{terms[0]}\\b'.",
             "step": "offlimits", "severity": "bad"}]


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


def install_fix(in_venv: bool | None = None) -> str:
    """How to install the requirements: into the venv in use, or, outside one, into a new venv rather than this Python."""
    if in_venv is None:
        in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        return f'Run: "{sys.executable}" -m pip install -r tools/requirements.txt'
    venv_python = r".venv\Scripts\python.exe" if sys.platform == "win32" else ".venv/bin/python"
    return (f'This Python isn\'t a venv, so make one in this folder first: "{sys.executable}" -m venv .venv\n'
            f"Then run {venv_python} -m pip install -r tools/requirements.txt, and use {venv_python} for Pyrite from then on.")


def tool_checks(cfg: dict | None) -> list[dict]:
    """The programs Pyrite uses, each as {"ok": True | False | None, "what", "fix"}. None means optional and missing."""
    found = []
    has_docx = importlib.util.find_spec("docx") is not None
    found.append({"ok": has_docx, "what": "python-docx, which builds the documents", "fix": "" if has_docx else install_fix()})
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
