"""Links. A web address, domain or email in a draft is blocked unless the sources write it: a reference text could try
to have one passed along, and an employer called Booking.com or a skill called Socket.IO is fine once the sources
name it."""
import re

# A web address or a path on a site, which is never a skill. File types a skill list names, such as Node.js/React,
# aren't sites.
FILE_TYPES = "js|jsx|ts|tsx|py|md|rb|go|rs|cs|cpp|hpp|java|kt|css|html|json|ya?ml|toml|sh|txt|csv|pdf|docx|xlsx|exe|dll"
URLISH = re.compile(rf"https?://|www\.|\b[\w-]{{2,}}\.(?!(?:{FILE_TYPES}|net)\b)[a-z]{{2,}}/[\w-]", re.I)
# Anything shaped like a domain, whatever its ending: there are too many endings to list, and .pro or .studio links as
# well as .com. One your own sources write, such as an employer called Booking.com or a skill called Socket.IO, is yours.
DOMAIN = re.compile(rf"(?<![\w@.-])((?:[A-Za-z0-9][\w-]*\.)+(?!(?:{FILE_TYPES})\b)[A-Za-z]{{2,24}})(?![\w-]|\.[A-Za-z0-9])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def own_links(sources: str) -> set[str]:
    """The domains and addresses the sources write, in lowercase: an employer such as Booking.com, a skill such as
    Socket.IO, your own email."""
    return {m.group(0).lower() for m in EMAIL.finditer(sources)} | {m.group(1).lower() for m in DOMAIN.finditer(sources)}


def link(line: str, own: set[str]) -> str | None:
    """The first web address, domain or email in a line that the sources don't write, or None."""
    found = URLISH.search(line)
    if found:
        return found.group(0)
    for email in EMAIL.finditer(line):
        if email.group(0).lower() not in own:
            return email.group(0)
    for domain in DOMAIN.finditer(EMAIL.sub(" ", line)):
        if domain.group(1).lower() not in own:
            return domain.group(1)
    return None
