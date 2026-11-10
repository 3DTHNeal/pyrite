"""A fact bank: Markdown a person wrote, holding what is true, and in sections of its own what must not be said.

A section headed "Do not use" lists confidential names. One headed "Unsupported" lists claims that aren't true. Neither
approves anything, and neither do their subsections. A "Contact" section, and each line starting with "@ ", holds contact
details, whose numbers measure nothing. `<!-- comments -->` say what goes in the file, not what's true.
"""
import re

# Sections of a fact bank that list what must not be claimed, at any heading level. Their words and numbers approve
# nothing, and neither do their subsections.
HEADING = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
EXCLUDED_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use|unsupported)\b", re.I)
DO_NOT_USE_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use)\b", re.I)
UNSUPPORTED_SECTION = re.compile(r"\W*unsupported\b", re.I)
# Your contact details hold numbers, a phone number and a zip code, that are about how to reach you. They count as
# nothing a draft can claim: a phone number of (555) 010-0142 doesn't make a team of 10 true.
CONTACT_SECTION = re.compile(r"\W*contact\b", re.I)


def split_sections(text: str, title: re.Pattern[str]) -> tuple[str, str]:
    """The text outside and inside the sections whose heading matches title, at any heading level. Such a section runs
    to the next heading at its own level or above, so its subsections go with it."""
    outside: list[str] = []
    inside: list[str] = []
    level_in = None
    for line in text.splitlines(keepends=True):
        heading = HEADING.match(line.rstrip("\r\n"))
        if heading:
            level = len(heading.group(1))
            if level_in is not None and level <= level_in:
                level_in = None
            if level_in is None and title.match(heading.group(2)):
                level_in = level
                continue
        (outside if level_in is None else inside).append(line)
    return "".join(outside), "".join(inside)


def uncommented(text: str) -> str:
    """Text without its <!-- comments -->, which say what goes in a file rather than anything true."""
    return COMMENT.sub("", text)


def claimable(text: str) -> str:
    """A source without the sections that list what must not be claimed, or its comments."""
    return split_sections(uncommented(text), EXCLUDED_SECTION)[0]


def source_body(name: str, text: str) -> str:
    """What a source states, as the assay reads it. In a plain-text source (a name ending .txt) a line starting with #
    is a comment, so it approves nothing."""
    if name.lower().endswith(".txt"):
        text = "\n".join(row for row in text.splitlines() if not row.lstrip().startswith("#"))
    return claimable(text)


def without_contact(text: str) -> str:
    """Sources without their contact details: the Contact section of a fact bank and each "@ " contact line."""
    text = split_sections(text, CONTACT_SECTION)[0]
    return "\n".join(row for row in text.splitlines() if not row.lstrip().startswith("@ "))


def do_not_use(text: str) -> str:
    """What a fact bank lists under "Do not use", subsections included, without its comments."""
    return split_sections(uncommented(text), DO_NOT_USE_SECTION)[1]


def unsupported_claims(text: str) -> list[str]:
    """The lines a fact bank lists under "Unsupported", subsections included, without comments, headings or bullets."""
    inside = split_sections(uncommented(text), UNSUPPORTED_SECTION)[1]
    lines = (row.strip().lstrip("-*").strip() for row in inside.splitlines() if not HEADING.match(row))
    return [line for line in lines if line]
