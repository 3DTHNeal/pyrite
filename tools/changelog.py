"""Folds the notes in changelog.d/ into the Unreleased section of CHANGELOG.md.

A pull request adds its note as a file of its own under changelog.d/ instead of editing CHANGELOG.md, so two pull
requests never change the same lines, and merging one never leaves the other with a conflict to resolve and its checks
to run again. A note is one or more of Keep a Changelog's headings, each over its entries:

    ### Fixed

    - **Reach out** no longer lists the same company twice.

    python tools/changelog.py           fold every note into CHANGELOG.md and delete its file, before a release
    python tools/changelog.py --check   only check that every note would fold, as CI does
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTES = ROOT / "changelog.d"
CHANGELOG = ROOT / "CHANGELOG.md"
# Keep a Changelog's headings, in its order. A heading made here goes where this order puts it.
SECTIONS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
UNRELEASED = "## [Unreleased]"


def notes() -> list[Path]:
    """The note files, in name order. The folder's README explains them and isn't one."""
    return sorted(p for p in NOTES.glob("*.md") if p.name.lower() != "readme.md")


def parse(text: str, name: str) -> dict[str, list[str]]:
    """A note's entries under each heading. An entry starts with "- ", and an indented line carries on the one above."""
    entries: dict[str, list[str]] = {}
    heading = None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if line.startswith("#"):
            match = re.fullmatch(r"### (\S+)\s*", line)
            if not match or match.group(1) not in SECTIONS:
                raise ValueError(f'{name}:{number}: a heading is "### " and one of {", ".join(SECTIONS)}')
            heading = match.group(1)
            entries.setdefault(heading, [])
        elif heading is None:
            raise ValueError(f'{name}:{number}: an entry goes under a heading, such as "### Added"')
        elif line.startswith("- ") or (line.startswith(" ") and entries[heading]):
            entries[heading].append(line.rstrip())
        else:
            raise ValueError(f'{name}:{number}: an entry starts with "- "')
    if not any(entries.values()):
        raise ValueError(f"{name}: has no entries")
    empty = [h for h, lines in entries.items() if not lines]
    if empty:
        raise ValueError(f'{name}: "### {empty[0]}" has no entries under it')
    return entries


def fold(changelog: str, additions: list[dict[str, list[str]]]) -> str:
    """CHANGELOG.md with each note's entries at the top of its heading under Unreleased, the first note first.

    A heading Unreleased lacks is made where Keep a Changelog's order puts it. Released sections aren't touched."""
    lines = changelog.splitlines()
    try:
        start = lines.index(UNRELEASED)
    except ValueError:
        raise ValueError(f'CHANGELOG.md has no "{UNRELEASED}" heading to fold the notes under') from None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))

    # The Unreleased block as the lines before its first heading, then each heading with its entries.
    block = lines[start + 1:end]
    first = next((i for i, line in enumerate(block) if line.startswith("### ")), len(block))
    preamble = block[:first]
    sections: list[tuple[str, list[str]]] = []
    for line in block[first:]:
        if line.startswith("### "):
            sections.append((line[4:].strip(), []))
        else:
            sections[-1][1].append(line)
    # Blank lines inside a heading's entries stay where they are. Those around them are written afresh below.
    for _, body in sections:
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()

    def rank(heading: str) -> int:
        return SECTIONS.index(heading) if heading in SECTIONS else len(SECTIONS)

    for heading in SECTIONS:
        new = [line for note in additions for line in note.get(heading, [])]
        if not new:
            continue
        found = next((body for name, body in sections if name == heading), None)
        if found is not None:
            found[:0] = new
            continue
        at = next((i for i, (name, _) in enumerate(sections) if rank(name) > rank(heading)), len(sections))
        sections.insert(at, (heading, new))

    rebuilt = [UNRELEASED]
    if any(line.strip() for line in preamble):
        rebuilt += ["", *[line for line in preamble if line.strip()]]
    for name, body in sections:
        rebuilt += ["", f"### {name}", "", *body]
    if end < len(lines):
        rebuilt.append("")
    return "\n".join(lines[:start] + rebuilt + lines[end:]) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fold the notes in changelog.d/ into CHANGELOG.md.")
    parser.add_argument("--check", action="store_true", help="only check that every note would fold")
    args = parser.parse_args(argv)
    files = notes()
    try:
        additions = [parse(p.read_text(encoding="utf-8"), f"changelog.d/{p.name}") for p in files]
        text = fold(CHANGELOG.read_text(encoding="utf-8"), additions)
    except ValueError as problem:
        print(problem, file=sys.stderr)
        return 1
    if args.check:
        print(f"{len(files)} note{'' if len(files) == 1 else 's'} in changelog.d/ would fold into CHANGELOG.md.")
        return 0
    CHANGELOG.write_text(text, encoding="utf-8", newline="\n")
    for p in files:
        p.unlink()
    print(f"Folded {len(files)} note{'' if len(files) == 1 else 's'} into CHANGELOG.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
