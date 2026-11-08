"""Making a new workspace, for `pyrite init` and for the dashboard's first-run setup."""
import json
import os
import re
import shutil
from pathlib import Path

from . import store

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


class Refused(ValueError):
    """Nothing was made, and the message says why."""


def create(folder_text: str, name: str) -> list[str]:
    """Make a workspace from the example's profile and point this copy of Pyrite at it. Returns what to tell the
    person, a line at a time. Raises Refused, having made nothing, for a placeholder or a folder that won't do."""
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
    if (folder / "profile").exists():
        if folder == store.ROOT:
            # Asking again for what's already true isn't an error, so a setup script can run this twice.
            return [f"{folder} is already the workspace in use, so nothing was changed. `pyrite doctor` lists what's left."]
        raise Refused(f"{folder} already has a profile/ folder, so nothing was changed. To use it, put its path in "
                      f"{store.HOME_POINTER}.")
    if not name:
        # Without it the workspace would carry the fictional candidate's name, which every draft is checked for.
        raise Refused(f"Give your name as it goes on your documents, such as `{INIT_EXAMPLE}` with yours in the quotes. "
                      "Nothing was made.")
    profile = folder / "profile"
    shutil.copytree(store.EXAMPLE_ROOT / "profile", profile, ignore=shutil.ignore_patterns(*INIT_SKIP, "*.previous.*"))
    config = profile / "search.toml"
    text = config.read_text(encoding="utf-8")
    text = text.replace(INIT_EXAMPLE_NAME, f"name = {json.dumps(name, ensure_ascii=False)}", 1)
    # The dashboard has no login, so it answers to no names but localhost until you add one.
    text = text.replace(INIT_EXAMPLE_HOSTS, "allowed_hosts = []", 1)
    for old, new in INIT_EXAMPLE_HEADER:
        text = text.replace(old, new, 1)
    config.write_text(text, encoding="utf-8")
    # Only whole lines that are the name, so the rest of each file stays the example's for `pyrite doctor` to point out.
    example_name = re.escape(INIT_EXAMPLE_NAME.split('"')[1])
    for file in INIT_NAMED_FILES:
        path = profile / file
        body = path.read_text(encoding="utf-8")
        path.write_text(re.sub(rf"^(# )?{example_name}$", lambda m: f"{m.group(1) or ''}{name}", body, flags=re.M), encoding="utf-8")
    (folder / "applications").mkdir(exist_ok=True)
    told = [f"Made a workspace at {folder}, from the fictional example's profile."]

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
    told.append("\nNext: make the files in its profile/ yours, starting with facts.md and resume.md. `pyrite doctor` lists "
                "what's left.\nKeep the workspace private. A private git repository of its own is a good home for it.")
    return told
