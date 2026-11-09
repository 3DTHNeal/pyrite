"""Making a new workspace, for `pyrite init` and for the dashboard's first-run setup."""
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

from . import store, tomledit

# A real folder rather than <folder>, which a shell reads as redirection when it's copied as it is.
INIT_EXAMPLE = 'pyrite init ../my-job-search --name "Your Name"'
# Copied from the example by `pyrite init`, and changed on the way. Each line is checked to be in the example's
# search.toml, so a change there that would leave one behind fails the tests rather than a new user's setup.
INIT_EXAMPLE_NAME = 'name = "Alex Rivera"'
INIT_EXAMPLE_HOSTS = "allowed_hosts = ['workstation', 'workstation.example-tailnet.ts.net']"
# The top of search.toml, which in the example says it's the example's and in a new workspace would say so wrongly.
INIT_EXAMPLE_HEADER = (
    ("# What Pyrite looks for. This is the fictional candidate's search: yours lives in",
     "# What Pyrite looks for. This began as a copy of the fictional candidate's search, so make"),
    ("# your own workspace. Run `pyrite discover --fresh` after changing filters so previously",
     "# it yours: `pyrite doctor` lists what's left. Run `pyrite discover --fresh` after changing filters so previously"),
)
# The master resume and letter carry the name too, as the `# Name` line the assay reads and the letter's signature.
INIT_NAMED_FILES = ("resume.md", "cover-letter.md")
# Its applications are the fictional candidate's, so a new workspace starts with none.
INIT_SKIP = ("seed.toml",)

# `pyrite init --blank` writes these profile files, with headings and comments on what goes where and nothing of the
# fictional candidate's. Their `# Your Name` lines get the name. search.toml is made from the example's, below.
BLANK = Path(__file__).parent / "blank"
BLANK_NAME = "Your Name"
# Settings in the example's search.toml that describe the fictional candidate, emptied in a blank one. The rest are
# how Pyrite works, such as the run's limits and the titles every search leaves out, and are kept as they are.
# `places` isn't in the example, so it's added: plain place names are what someone starting out wants to write.
BLANK_EMPTIED = (
    ("location", "local"), ("location", "local_exact"), ("location", "places"), ("promote", "cities"), ("scoring", "keywords"),
    ("guard", "forbidden"), ("guard", "unsupported"), ("guard", "ordinary_words"), ("guard", "expected_on_resume"),
    ("workday", "queries"), ("dashboard", "allowed_hosts"),
)
BLANK_DROPPED = (("market", "state"), ("market", "metro"))
# Tables whose every key is the example's: whose mail comes from where, and the companies it watches.
BLANK_CLEARED = ("inbox.domains", "watch.greenhouse", "watch.lever", "watch.ashby", "watch.workday")
# Lists of tables, each replaced by a comment showing the form of one.
BLANK_TABLES = {
    "promote.industry": "# [[promote.industry]]\n# name = \"Healthcare\"\n# terms = ['\\bhealth ?care\\b', '\\bhospitals?\\b']\n",
    "track": "# [[track]]\n# name = \"Data engineering\"\n# titles = [\"data engineer\", \"analytics engineer\"]\n"
             "# needs_level = true\n",
}
# Comment lines in the example that would describe the fictional candidate, and what a blank search.toml says instead.
# None leaves the line out. Each is checked to be in the example, as INIT_EXAMPLE_HEADER is.
BLANK_COMMENTS = (
    ("# What Pyrite looks for. This is the fictional candidate's search: yours lives in",
     "# What Pyrite looks for. The settings that describe you start empty: fill them in, and `pyrite doctor`"),
    ("# your own workspace. Run `pyrite discover --fresh` after changing filters so previously",
     "# lists what's left. Run `pyrite discover --fresh` after changing filters so previously"),
    ('# "Madison, WI". Either can be left out. The official numbers cover the United States only, so',
     '# "Springfield, IL". Either can be left out. The official numbers cover the United States only, so'),
    ("# dropped: to accept a city at all, add it under [location] too. These towns already pass",
     "# dropped: to accept a city at all, add it under [location] too."),
    ('# as "local", because [location] accepts anywhere in Wisconsin.', None),
    ("# Either or both will do. Madison is tied to Wisconsin here, so Madison, Alabama isn't local.",
     "# Either or both will do."),
)

# What `pyrite init --git` keeps out of the workspace's repository. pyrite.db isn't among it: it can't be regenerated,
# so the repository is its backup.
GITIGNORE = """\
# Written by `pyrite init --git`. This workspace is private, so keep its repository private too.

# data/pyrite.db is kept on purpose: it's everything Pyrite tracks, and it can't be regenerated.
# These are SQLite's working files beside it, which hold changes in progress.
data/*.db-wal
data/*.db-shm
data/*.db-journal
# The code the dashboard is waiting for, which lasts 2 minutes.
data/confirm-code.json
# The browser profile `pyrite autofill` uses, which holds your sign-ins to Workday sites.
data/browser/
# Official employment numbers from the BLS, downloaded again whenever they're missing.
data/market/*.csv
data/market/qcew/
*.tmp
# The copy a save keeps of the file from before it, such as resume.previous.md and search.previous.toml.
*.previous.*
# Word's lock files, left beside a document while it's open.
~$*

# The built .docx, .pdf and .txt files are kept. Pyrite checks them against the draft that passed and the copy that
# was sent, and a rebuild, on another computer or with another version of Word, never comes out byte for byte the same.
"""


class Refused(ValueError):
    """Nothing was made, and the message says why."""


def _named(text: str, old: str, name: str) -> str:
    """Only whole lines that are the name, so the rest of a file stays as it was."""
    return re.sub(rf"^(# )?{re.escape(old)}$", lambda m: f"{m.group(1) or ''}{name}", text, flags=re.M)


def _setting(cfg: dict, table: str) -> dict:
    for part in table.split("."):
        cfg = cfg.get(part, {}) if isinstance(cfg, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def blank_config(text: str, name: str) -> str:
    """The example's search.toml with every setting that describes the fictional candidate emptied, and the name set.
    Each change goes through tomledit, which proves it changed nothing else and keeps every comment explaining a
    setting, so a blank search.toml stays in step with the example's as that changes."""
    for table, block in BLANK_TABLES.items():
        text = tomledit.replace_table(text, table, block)
    for table, key in BLANK_EMPTIED:
        text = tomledit.set_value(text, table, key, [])
    for table, key in BLANK_DROPPED:
        text = tomledit.delete_value(text, table, key)
    for table in BLANK_CLEARED:
        for key in list(_setting(tomllib.loads(text), table)):
            text = tomledit.delete_value(text, table, key)
    text = tomledit.set_value(text, "candidate", "name", name)
    lines = text.split("\n")
    for old, new in BLANK_COMMENTS:
        at = lines.index(old)
        if new is None:
            del lines[at]
        else:
            lines[at] = new
    return "\n".join(lines)


def _make_blank(profile: Path, name: str) -> None:
    config = blank_config((store.EXAMPLE_ROOT / "profile" / "search.toml").read_text(encoding="utf-8"), name)
    profile.mkdir(parents=True)
    for source in sorted(BLANK.iterdir()):
        if source.is_file():
            text = source.read_text(encoding="utf-8")
            (profile / source.name).write_text(_named(text, BLANK_NAME, name) if source.name in INIT_NAMED_FILES else text,
                                               encoding="utf-8")
    (profile / "search.toml").write_text(config, encoding="utf-8")


def _copy_example(profile: Path, name: str) -> None:
    shutil.copytree(store.EXAMPLE_ROOT / "profile", profile, ignore=shutil.ignore_patterns(*INIT_SKIP, "*.previous.*"))
    config = profile / "search.toml"
    text = config.read_text(encoding="utf-8")
    text = text.replace(INIT_EXAMPLE_NAME, f"name = {json.dumps(name, ensure_ascii=False)}", 1)
    # The dashboard has no login, so it answers to no names but localhost until you add one.
    text = text.replace(INIT_EXAMPLE_HOSTS, "allowed_hosts = []", 1)
    for old, new in INIT_EXAMPLE_HEADER:
        text = text.replace(old, new, 1)
    config.write_text(text, encoding="utf-8")
    # Only the name, so the rest of each file stays the example's for `pyrite doctor` to point out.
    example_name = INIT_EXAMPLE_NAME.split('"')[1]
    for file in INIT_NAMED_FILES:
        path = profile / file
        path.write_text(_named(path.read_text(encoding="utf-8"), example_name, name), encoding="utf-8")


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=60)


def set_up_git(folder: Path) -> list[str]:
    """Make the workspace a git repository of its own, with a .gitignore. It never adds a remote or pushes, since
    everything in it is private. Returns what to tell the person."""
    told = []
    outer = _git(folder, "rev-parse", "--show-toplevel")
    inside = Path(outer.stdout.strip()).resolve() if outer.returncode == 0 and outer.stdout.strip() else None
    if inside == folder:
        told.append(f"{folder} is a git repository already, so it was left as it is.")
    else:
        made = _git(folder, "init", "--quiet")
        if made.returncode:
            return [f"git couldn't make {folder} a repository: {(made.stderr or made.stdout).strip()}"]
        told.append("Made it a git repository of its own. It has no remote, and Pyrite never adds one or pushes.")
        if inside:
            told.append(f"It's inside the repository at {inside}, which must never commit it. If that one is ever shared "
                        "or public, move the workspace out of it.")
    ignore = folder / ".gitignore"
    if ignore.exists():
        told.append(f"{ignore} was there already, so it was left alone. Pyrite's suggestion leaves out SQLite's -wal and -shm "
                    "files, the *.previous.* backups, data/browser/ and Word's ~$ lock files.")
    else:
        ignore.write_text(GITIGNORE, encoding="utf-8")
        told.append("Wrote a .gitignore that leaves out what shouldn't be kept, such as SQLite's working files, the "
                    "backups a save makes and the browser profile autofill signs in with.")
    told.append("data/pyrite.db goes in the repository on purpose. It's everything Pyrite tracks and it can't be "
                "regenerated, so the repository is its backup. Commit when nothing is running, with no pan, Claude run "
                "or dashboard save under way, so the copy is whole. Then:\n"
                f'  git -C "{folder}" add -A\n'
                f'  git -C "{folder}" commit -m "Back up my job search"\n'
                "To keep a copy off this computer too, push it to a private repository you make yourself. Never make it public.")
    return told


def create(folder_text: str, name: str, blank: bool = False, git: bool = False) -> list[str]:
    """Make a workspace from the example's profile, or blank profile files with `blank`, and point this copy of Pyrite
    at it. With `git`, make it a git repository too, which also works on the workspace already in use. Returns what to
    tell the person, a line at a time. Raises Refused, having made nothing, for a placeholder or a folder that won't do."""
    from .doctor import PLACEHOLDER_NAMES

    # Placeholders copied from the docs as they are. Angle brackets can't be in a Windows folder name either.
    if any(mark in folder_text for mark in "<>"):
        raise Refused(f"{folder_text} is a placeholder. Put the folder you want in its place, such as `{INIT_EXAMPLE}`.")
    name = name.strip()
    if name.strip("<>[]").lower() in PLACEHOLDER_NAMES or any(mark in name for mark in "<>[]"):
        raise Refused(f'"{name}" is a placeholder. Use your own name, in quotes, such as --name "Sam Doe". Nothing was made.')
    folder = Path(folder_text).expanduser().resolve()
    code_root = store.CODE_ROOT
    if folder == code_root or code_root in folder.parents:
        beside = Path("..") / folder.name if folder != code_root else Path("..") / "my-job-search"
        raise Refused(f"{folder} is inside this repository. Make your workspace outside it, so nothing personal can be "
                      f"committed here.\nTo put it beside this repository instead: pyrite init {beside} "
                      f"--name {json.dumps(name or 'Your Name', ensure_ascii=False)}")
    if git and not shutil.which("git"):
        raise Refused("--git needs git, which isn't installed or isn't on PATH. Install it, or leave out --git. Nothing was made.")
    if (folder / "profile").exists():
        if folder == store.ROOT:
            # Asking again for what's already true isn't an error, so a setup script can run this twice.
            if git:
                return [f"{folder} is already the workspace in use, so its files were left as they are.",
                        *set_up_git(folder)]
            return [f"{folder} is already the workspace in use, so nothing was changed. `pyrite doctor` lists what's left."]
        raise Refused(f"{folder} already has a profile/ folder, so nothing was changed. To use it, put its path in "
                      f"{store.HOME_POINTER}.")
    if not name:
        # Without it the workspace would carry the fictional candidate's name, which every draft is checked for.
        raise Refused(f"Give your name as it goes on your documents, such as `{INIT_EXAMPLE}` with yours in the quotes. "
                      "Nothing was made.")
    profile = folder / "profile"
    if blank:
        _make_blank(profile, name)
    else:
        _copy_example(profile, name)
    (folder / "applications").mkdir(exist_ok=True)
    told = [f"Made a workspace at {folder}, with blank profile files to fill in." if blank
            else f"Made a workspace at {folder}, from the fictional example's profile."]

    pointer = store.HOME_POINTER
    current = os.environ.get("PYRITE_HOME", "").strip()
    if current and Path(store._windows_path(current)).expanduser().resolve() == folder:
        told.append("PYRITE_HOME already names it, so Pyrite uses it from now on.")
    elif current:
        told.append(f"PYRITE_HOME is set to {current}, which wins over .pyrite-home. Set it to {folder} to use this workspace.")
    elif pointer.exists() and pointer.read_bytes().strip():
        told.append(f"{pointer} already names a workspace, so it was left alone. Put {folder} in it to use this one.")
    else:
        pointer.write_text(f"{folder}\n", encoding="utf-8")
        told.append(f"Pointed Pyrite at it in {pointer}.")
    if git:
        told += set_up_git(folder)
    told.append("\nNext: " + ("fill in the files in its profile/, starting with facts.md, whose comments say what goes where."
                              if blank else "make the files in its profile/ yours, starting with facts.md and resume.md.")
                + " `pyrite doctor` lists what's left.\nKeep the workspace private."
                + ("" if git else f' A private git repository of its own is a good home for it: `pyrite init "{folder}" --git` '
                                  "makes it one, once it's the workspace in use."))
    return told
