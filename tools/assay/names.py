"""Confidential names. A name listed under "Do not use" in a fact bank, or given as a pattern, is blocked however a
draft writes it: in any case, as a plural, and split anywhere by whatever can join a name."""
import re
from collections.abc import Iterable

from .factbank import HEADING, do_not_use

# Under "Do not use", a capitalized word could be a secret name. Asides in parentheses and quoted wording explain a rule
# or suggest what to say instead, so they name nothing secret.
CAPITALIZED = re.compile(r"\b[A-Z][\w+#-]*")
ASIDE = re.compile(r"\([^)]*\)|\"[^\"]*\"|“[^”]*”")
# A sentence of a "Do not use" line: everything up to a full stop, question mark or semicolon that ends a clause, so
# "2.5" stays whole.
LISTED_SENTENCE = re.compile(r"(?:[^.!?;]|[.!?;](?=\S))+")
# Words that open an instruction or a description under "Do not use" rather than name something: "Say Northbridge, not
# the codename", "Project Kestrel", "Customer Globex".
NOT_A_NAME = {"say", "use", "write", "call", "describe", "mention", "refer", "avoid", "never", "do", "don't", "keep",
              "prefer", "omit", "replace", "no", "not", "only", "any", "all", "the", "a", "an", "our", "my", "project",
              "projects", "codename", "codenames", "code", "product", "products", "program", "programs", "team",
              "customer", "customers", "client", "clients", "partner", "partners", "model", "models", "robot", "internal",
              "unreleased", "confidential", "secret", "names", "name"}
# What can sit between the letters of a name without making it another word: a space, a hyphen or dash of any kind, an
# underscore, a slash or a middle dot, up to three in a row, and a full stop when a letter follows it. "B.l.u.e" is one
# word; the full stop that ends a sentence joins nothing.
JOIN = r"(?:[\s\-_/·‐-―−]|\.(?=\w)){0,3}"
PLAIN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{3,}")
PLAIN_WORDS = re.compile(r"[A-Za-z0-9]+(?: [A-Za-z0-9]+)+")


def term_pattern(term: str) -> str:
    """A pattern that blocks a term as people write it: any case, a hyphen or space or nothing between its words, and
    a plural. "SkyLift 900" blocks SkyLift-900 and skylift 900s."""
    words = [w for w in re.split(r"[\s-]+", re.sub(r"^the\s+", "", term.strip(), flags=re.I)) if w]
    if not words:
        raise ValueError("Type the name or claim to block.")
    body = r"[\s-]?".join(re.escape(w) for w in words)
    last = words[-1][-1]
    if last.isalpha() and last.lower() != "s":
        body += "s?"
    start = r"\b" if re.match(r"\w", words[0]) else r"(?<!\w)"
    end = r"\b" if re.match(r"\w", last) else r"(?!\w)"
    return start + body + end


def unguarded_terms(facts: str, forbidden: list[str], own_name: str = "", ordinary: Iterable[str] = ()) -> list[str]:
    """Capitalized terms under "Do not use" in a fact bank that no pattern in `forbidden` matches.

    Only words that could be a secret name count. The first word of each sentence is skipped when it's a label such as
    "Internal names:", an instruction such as "Say", or opens a description such as "Customer names". It counts when it
    stands alone, as in "- Bluebird", is followed by a comma, as in "- Falconer, the robot arm", or starts a run of
    capitalized words, as in "- Acme Corp". Asides in parentheses and quoted wording are skipped, since they explain the
    rule rather than name something. The words of your own name are skipped too: forbidding them would fail every draft.
    `ordinary` are lowercase words that, opening a sentence, are taken as capitalized only because they come first."""
    mine = {word.lower() for word in re.findall(r"\w+", own_name)}
    plain = set(ordinary)
    found: list[str] = []
    for row in do_not_use(facts).splitlines():
        heading = HEADING.match(row)
        line = heading.group(2).strip() if heading else row.strip().lstrip("-*").strip()
        spans = [match.span() for pattern in forbidden for match in re.finditer(pattern, line, re.I)]
        masked = ASIDE.sub(lambda aside: " " * len(aside.group(0)), line)
        for sentence in LISTED_SENTENCE.finditer(masked):
            terms = list(CAPITALIZED.finditer(masked, sentence.start(), sentence.end()))
            # A subsection's heading, such as "#### Customers", says what's listed under it.
            if terms and (heading or not _names_something(masked[sentence.start():terms[0].start()], terms[0],
                                                          masked[terms[0].end():sentence.end()], plain)):
                terms = terms[1:]
            for term in terms:
                covered = any(start < term.end() and term.start() < end for start, end in spans)
                if not covered and term.group(0).lower() not in mine and term.group(0) not in found:
                    found.append(term.group(0))
    return found


def _names_something(before: str, first: re.Match[str], rest: str, ordinary: set[str]) -> bool:
    """Whether the first capitalized word of a "Do not use" sentence is a name rather than a label or an instruction."""
    if before.strip():
        return True  # Capitalized in mid-sentence, as in "the Hive".
    if first.group(0).lower() in NOT_A_NAME or first.group(0).lower() in ordinary:
        return False
    rest = rest.rstrip(" .")
    return not rest.strip() or rest.startswith(",") or bool(re.match(r"\s+[A-Z]", rest))


def widen(pattern: str) -> str:
    """A pattern whose "[\\s-]?", the optional space or hyphen that `term_pattern` writes between words, lets through
    anything that can join a name. Patterns saved before this read the same way."""
    return pattern.replace(r"[\s-]?", JOIN)


def flexible(pattern: str) -> str:
    """A forbidden pattern that's a plain name, such as Bluebird, also blocks it split anywhere by something that joins
    a name, as in "blue bird", "Sky-Lift" or "Blue_bird", and as a plural. Plain words with spaces between, such as
    "SkyLift 900", block the same name joined another way. A pattern with any other regular-expression syntax is
    taken as written."""
    if PLAIN_NAME.fullmatch(pattern):
        parts = list(pattern)
    elif PLAIN_WORDS.fullmatch(pattern):
        parts = pattern.split(" ")
    else:
        return widen(pattern)
    body = JOIN.join(re.escape(part) for part in parts)
    return rf"\b{body}{'s?' if pattern[-1].isalpha() and pattern[-1].lower() != 's' else ''}\b"


def confidential(label: str, match: re.Match[str], where: str) -> str:
    """The error for a confidential name found in a draft. `where` names the source that lists it, or is ""."""
    listed = f", which {where} lists under \"Do not use\"" if where else ""
    return f"{label} uses a confidential term: {match.group(0)!r}{listed}"
