"""The fact checker: deterministic gates between a tailored draft and "ready to apply".

Errors block the draft. Warnings are shown on the dashboard for you to read.
The rules restate profile/facts.md: only claim what's there, keep numbers as
measured, never use anything on the do-not-use list.
"""
import hashlib
import json
import re
import subprocess
import unicodedata
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .store import ROOT, SENT_FOLDER, sent_copies

# The dashboard runs under pythonw, with no console of its own, so a console program it starts would open a window
# of its own unless told not to.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# A date alone on its line is a letter's date, which may be any day. A date inside a sentence is a claim like any other.
# Written any common way: November 15, 2026, Nov. 15th, 2026, 15 November 2026 or 2026-11-15.
_MONTH = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?"
          r"|Nov(?:ember)?|Dec(?:ember)?)\.?")
_DAY = r"\d{1,2}(?:st|nd|rd|th)?"
DATE_LINE = re.compile(
    rf"(?m)^[ \t]*(?:{_MONTH}\s+{_DAY},?\s+\d{{4}}|{_DAY}\s+(?:of\s+)?{_MONTH},?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})[ \t]*$"
)
# A number keeps its scale: $3M isn't the 3 the fact bank measured, and 212K tests aren't 212. Each reads as its value,
# so 1.5M and 1,500,000 are the same number. A scale word counts in any case and after a space: 3 Million, 3 bn.
# A lowercase m, or a letter after a space, is a scale only after a currency sign, as in $3m, $3 MM or $3 mil: on its own
# 30m is as often minutes, 5 mil a film thickness and 300 K a temperature.
# A number may start at its decimal point, as in .83 seconds.
NUMBER = re.compile(
    r"(?:(?P<money>[$€£])\s?|(?<![\w.]))(?P<digits>\d[\d,]*(?:\.\d+)?|\.\d+)"
    r"(?:\s?(?P<word>(?i:thousand|million|billion|trillion|bn))\b|(?P<letter>K|k|M|MM|B)\b"
    r"|(?(money)\s?(?P<cash>(?i:mm|mil|mn|k|m|b))\b|(?!)))?"
)
SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mm": 6, "mil": 6, "mn": 6, "billion": 9, "b": 9, "bn": 9, "trillion": 12}
# A percentage spelled out is still a percentage, and so is a change in percentage points.
PERCENT = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent(?:age)?(?:\s+points?)?\b|per\s?cent\b|pct\b|pp\b|p\.p\.)", re.I
)
# Multiples, fractions and orders of magnitude claimed in words are measurements too, in any form of the word: doubled,
# doubling, twice as fast, cut in half, by a third. Words that only look like one are left alone: a third launch, the
# second half of the year, both halves of a job, double-precision, half-duplex.
MULTIPLE = re.compile(
    r"\b(?:(?:doubl|tripl|quadrupl)(?:ed|es|ing)|halv(?:ed|ing)|(?:double|triple|quadruple)\s+(?:the|its|their|our)"
    r"|twice\s+(?:as|the)|thrice|(?:in|by)\s+half(?!-)|half\s+(?:the|as)"
    r"|(?:a|one)\s+(?:third|quarter|fifth|tenth)\s+(?:of|less|more|fewer|faster|slower|lower|higher)"
    r"|by\s+(?:a|one)\s+(?:third|quarter|fifth|tenth)|(?:two|three|four)[- ](?:thirds|fifths)|three-quarters"
    r"|(?:two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)[- ]?fold"
    r"|(?:double|triple)[- ]digits?|(?:five|six|seven|eight|nine|ten)[- ]figures?|orders? of magnitude)\b",
    re.I,
)
# A multiple in digits, however it's written: 8x, 2.5×, 3-fold, 3 times faster. It's a measurement of its own, whatever
# counts the fact bank holds, and each form reads as the same multiple.
NUMERIC_MULTIPLE = re.compile(
    r"(?<![\w.,])((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(?:\s?[x×](?!\w)|[- ]?fold\b"
    r"|\s+times\s+(?:as|the|faster|slower|more|less|fewer|higher|lower|better|greater|larger|smaller|quicker)\b)",
    re.I,
)
# A web address or a path on a site, which is never a skill. File types a skill list names, such as Node.js/React,
# aren't sites.
FILE_TYPES = "js|jsx|ts|tsx|py|md|rb|go|rs|cs|cpp|hpp|java|kt|css|html|json|ya?ml|toml|sh|txt|csv|pdf|docx|xlsx|exe|dll"
URLISH = re.compile(rf"https?://|www\.|\b[\w-]{{2,}}\.(?!(?:{FILE_TYPES}|net)\b)[a-z]{{2,}}/[\w-]", re.I)
# Anything shaped like a domain, whatever its ending: there are too many endings to list, and .pro or .studio links as
# well as .com. One your own sources write, such as an employer called Booking.com or a skill called Socket.IO, is yours.
DOMAIN = re.compile(rf"(?<![\w@.-])((?:[A-Za-z0-9][\w-]*\.)+(?!(?:{FILE_TYPES})\b)[A-Za-z]{{2,24}})(?![\w-]|\.[A-Za-z0-9])")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Markdown emphasis can split a word in two that renders whole: **Blue****bird**, or _40_. Underscores inside a word stay.
EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
PLACEHOLDER = re.compile(
    r"\[[^\]]*\]|\{\{|\{[^{}\n]{0,40}\}|\bTODO\b|\bTBD\b|\bFIXME\b|\bX{2,}\b|<[A-Za-z_ ]+>"
)
# A blank to fill in, such as ___%. Looked for before emphasis markers are taken out, since those are underscores too.
BLANK = re.compile(r"_{3,}")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[-/.][A-Za-z0-9+#]+)*\+*")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
# Sections of a fact bank that list what must not be claimed, at any heading level. Their words and numbers approve
# nothing, and neither do their subsections.
HEADING = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.*)$")
COMMENT = re.compile(r"<!--.*?-->", re.S)
# Under "Do not use", a capitalized word could be a secret name. Asides in parentheses and quoted wording explain a rule
# or suggest what to say instead, so they name nothing secret.
CAPITALIZED = re.compile(r"\b[A-Z][\w+#-]*")
ASIDE = re.compile(r"\([^)]*\)|\"[^\"]*\"|“[^”]*”")
# A sentence of a "Do not use" line: everything up to a full stop, question mark or semicolon that ends a clause, so
# "2.5" stays whole.
LISTED_SENTENCE = re.compile(r"(?:[^.!?;]|[.!?;](?=\S))+")
EXCLUDED_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use|unsupported)\b", re.I)
DO_NOT_USE_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use)\b", re.I)
UNSUPPORTED_SECTION = re.compile(r"\W*unsupported\b", re.I)
# Your contact details hold numbers, a phone number and a zip code, that are about how to reach you. They count as
# nothing a draft can claim: a phone number of (555) 010-0142 doesn't make a team of 10 true.
CONTACT_SECTION = re.compile(r"\W*contact\b", re.I)
# A negative only disclaims what follows it in the same clause. "Not only" is no negative at all, and neither is one
# that praises the record: "never failed an X audit", "not a single X finding", "without a single X nonconformance".
# Nor is one that says the opposite of what it seems to: "no stranger to X", "not new to X", "no shortage of X",
# "without question", or two that cancel, as in "not a day went by without X".
NOT_A_NEGATIVE = re.compile(
    r"(?:\b(?:not|no|never|without)|n['’]t)\s+(?:only|just|merely|less|fewer|a\s+single|fail\w*|miss\w*|lost|los[ei]\w*"
    r"|stranger|new|shortage|lack|far|question|doubt|exception|equal|peer|rival|unfamiliar)\b"
    r"|\b(?:not|no|never|hardly|rarely)\b[^;,:()]{0,60}?\bwithout\b",
    re.I,
)
# Punctuation and joining words start a new clause, so "With no added headcount, cut defects by 83%" denies nothing.
# So does a new subject: in "With no budget I led X" the negative is about the budget, not X.
CLAUSE_BREAK = re.compile(
    r"[;,:()]|\s[-–]\s|—|\b(?:but|however|although|though|whereas|while|and|after|before|when|which|who|where|since|because|then"
    r"|I|we)\b",
    re.I,
)
# A denial sits right before the claim it denies: "I have not yet worked under X", "no X experience".
# A negative further back is about something else: "Never missed a milestone leading X" is a claim of X.
DENIAL_REACH = 3
FIRST_PERSON_DENIAL = re.compile(
    r"\bI\s+(?:have|had|do|did|am|was|would|could|can|will)\s+(?:not|never)\b|\bI\s+have\s+yet\s+to\b|\bI\s+never\b"
    r"|\bI\s+(?:haven|hadn|don|didn|wasn|couldn|wouldn|won|can)['’]t\b|\bI['’]ve\s+(?:not|never)\b"
)
# A first-person denial after the claim counts only when it points back at it: "...and I have not done it", "...I haven't."
# "Led X, and I never missed a deadline" denies the deadline, not X.
REFERS_BACK = re.compile(r"(?:\s+[\w'’]+){0,4}?\s+(?:it|that|this|them|one|so|either|any|yet)\b|\W*$", re.I)
# Some negatives that point back are praise, not denial: "I led X, and I could not be prouder of it", "...never missed one",
# "...never regretted it", and anything in the would-have form: "I couldn't have done it alone".
PRAISE = re.compile(
    r"\b(?:be|prouder|happier|better|more|enough|wait|forg[eo]t\w*|regret\w*|chang\w*|stop\w*|miss\w*|say|imagine|believe|"
    r"recommend|overstate|thank|trade|resist|want|ask|lov\w*|enjoy\w*|tire[ds]?|tiring|have\s+(?:been|done|\w+ed|\w+en))\b",
    re.I,
)
# How far either side of a claim the denial check reads. A denial sits within a few words of what it denies, and reading
# the whole sentence for every claim in it takes time that grows with the square of its length.
DENIAL_WINDOW = 300
# A claim the sentence puts in the posting's mouth isn't yours: "Your posting lists X as a plus, and I have not worked under Y".
ATTRIBUTED = re.compile(
    r"\b(?:posting|role|job|position|description|you|your)\b[^.;]{0,60}?"
    r"\b(?:lists?|asks?|requires?|mentions?|wants?|calls?|prefers?|names?|includes?|needs?)\b(?:\W+\w+){0,3}?\W*$",
    re.I,
)
# Numbers written as words slip past a check on digits. One to ten are too common in prose to police.
NUMBER_WORD = re.compile(
    r"\b(?:eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?)\b",
    re.I,
)
# The drafter is the builder plus the writing rules it enforces. Bump this when either changes in a way
# that shows in the documents, and say what changed under "Drafter versions" in docs/resume-playbook.md.
# Every .docx and .pdf carries its drafter version, so a folder's files can be told apart from older ones.
DRAFTER_VERSION = "3"
# Wording that recruiters and screening tools now read as machine-written or empty. Warned, never blocked.
CLICHE = re.compile(
    r"\b(?:spearhead(?:ed|ing|s)?|leverag(?:ed|ing|es)?|orchestrat(?:ed|ing|es)?|honed|streamlin(?:ed|ing|es)?|"
    r"results[- ]driven|results[- ]oriented|synerg\w*|passionate|dynamic|proven track record|thought leader|"
    r"self[- ]starter|go[- ]getter|detail[- ]oriented|fast[- ]paced|cutting[- ]edge|best[- ]in[- ]class|"
    r"I am (?:excited|thrilled) to apply)\b",
    re.I,
)
# Letters from other alphabets, and Latin small capitals, that a reader takes for plain Latin ones. A word spelled only
# with these and plain letters reads as English and matches nothing: ВӏуеЬird, ʙʟᴜᴇʙɪʀᴅ.
LOOKALIKES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУԚԜҮҺӀ" "асеһіјӏорԛѕԁуҳхԝүɡ" "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ" "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘʀꜱᴛᴜᴠᴡʏᴢ",
    "ABCEHIJKMOPSTXYQWYHI" "acehijlopqsdyxxwyg" "ABEZHIKMNOPTYX" "abcdefghijklmnoprstuvwyz",
)
# Latin letters that don't decompose into a plain one plus an accent. They're real letters in names (Łukasz, Søren,
# Işık), so they're never an error, but a check reads them as the plain letter so they can't split a word.
PLAIN_LATIN = str.maketrans({"ı": "i", "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ħ": "h", "Ħ": "H"})
# A unit written with the micro or ohm sign, such as µm, µs or kΩ. It sets a Greek letter beside Latin ones by design,
# and hides nothing.
UNIT = re.compile(r"[µμ][A-Za-z]{1,3}|[kKMGmµμ]?[ΩΩ]")
# What can sit between the letters of a name without making it another word: a space, a hyphen or dash of any kind, an
# underscore, a slash or a middle dot, up to three in a row, and a full stop when a letter follows it. "B.l.u.e" is one
# word; the full stop that ends a sentence joins nothing.
JOIN = r"(?:[\s\-_/·‐-―−]|\.(?=\w)){0,3}"
EM_DASH = "—"
LETTER_WORDS_MAX = 350  # a letter longer than this is the one readers say they stop reading
# Titles that open a line as a claim: "Head of firmware for the company." The first word of a sentence is otherwise
# taken as capitalized only because it comes first.
TITLE_WORDS = {"director", "head", "chief", "president", "vice"}
# A line shaped like a role heading, "Title | place | dates", printed as plain or bold text instead of as a heading.
ROLE_LINE = re.compile(r"^[^#@|][^|]*\|[^|]*\|.*\b(?:19|20)\d\d\b")
# Words that open an instruction or a description under "Do not use" rather than name something: "Say Northbridge, not
# the codename", "Project Kestrel", "Customer Globex".
NOT_A_NAME = {"say", "use", "write", "call", "describe", "mention", "refer", "avoid", "never", "do", "don't", "keep",
              "prefer", "omit", "replace", "no", "not", "only", "any", "all", "the", "a", "an", "our", "my", "project",
              "projects", "codename", "codenames", "code", "product", "products", "program", "programs", "team",
              "customer", "customers", "client", "clients", "partner", "partners", "model", "models", "robot", "internal",
              "unreleased", "confidential", "secret", "names", "name"}
ORDINARY_CAPS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday", "friday",
    "i", "dear", "sincerely", "hiring", "manager", "team", "summary",
    "experience", "skills", "education", "patent", "patents", "certifications", "core", "selected", "scope",
    "leadership", "ai", "us", "u.s", "ml", "and", "the", "of",
}


def _split_sections(text: str, title: re.Pattern[str]) -> tuple[str, str]:
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
    """Text without its <!-- comments -->, which say what goes in a file rather than anything true of you."""
    return COMMENT.sub("", text)


def claimable(text: str) -> str:
    """A source without the sections that list what must not be claimed, or its comments."""
    return _split_sections(uncommented(text), EXCLUDED_SECTION)[0]


def source_body(rel: str, text: str) -> str:
    """What an approved source states, as the assay reads it. In a plain-text source such as approved-terms.txt a line
    starting with # is a comment, as the Facts tab and its code check read it, so it approves nothing."""
    if rel.lower().endswith(".txt"):
        text = "\n".join(row for row in text.splitlines() if not row.lstrip().startswith("#"))
    return claimable(text)


def without_contact(text: str) -> str:
    """Sources without their contact details: the Contact section of a fact bank and each "@ " contact line."""
    text = _split_sections(text, CONTACT_SECTION)[0]
    return "\n".join(row for row in text.splitlines() if not row.lstrip().startswith("@ "))


def do_not_use(text: str) -> str:
    """What a fact bank lists under "Do not use", subsections included, without its comments."""
    return _split_sections(uncommented(text), DO_NOT_USE_SECTION)[1]


def unsupported_claims(text: str) -> list[str]:
    """The lines a fact bank lists under "Unsupported", subsections included, without comments, headings or bullets."""
    inside = _split_sections(uncommented(text), UNSUPPORTED_SECTION)[1]
    lines = (row.strip().lstrip("-*").strip() for row in inside.splitlines() if not HEADING.match(row))
    return [line for line in lines if line]


def unenforced_claims(cfg: dict[str, Any], read: Callable[[str], str] | None = None) -> list[tuple[str, str]]:
    """Lines your approved sources list under "Unsupported" that no pattern under [guard] unsupported matches, each as
    (line, the file that lists it).

    The assay blocks an unsupported claim by pattern alone, so a line with no pattern is a rule nothing enforces: a
    draft can make the claim and pass. A pattern about a percentage needs one to match, so each line is also tried
    with a percentage on either side. `read` gives a source's text, for a draft of one that isn't saved yet."""
    guard = cfg.get("guard", {})
    patterns = []
    for pattern in guard.get("unsupported", []):
        try:
            patterns.append(re.compile(pattern, re.I))
        except re.error:
            pass  # `doctor` names a pattern that won't compile. It matches nothing here.
    loose: list[tuple[str, str]] = []
    for rel in dict.fromkeys(guard.get("approved_sources", [])):
        for line in unsupported_claims((read or _source_text)(rel)):
            if not any(pattern.search(text) for pattern in patterns for text in (line, f"50% {line} 50%")):
                loose.append((line, rel))
    return loose


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


def unguarded_terms(facts: str, forbidden: list[str], own_name: str = "") -> list[str]:
    """Capitalized terms under "Do not use" in a fact bank that no pattern in [guard] forbidden matches.

    Only words that could be a secret name count. The first word of each sentence is skipped when it's a label such as
    "Internal names:", an instruction such as "Say", or opens a description such as "Customer names". It counts when it
    stands alone, as in "- Bluebird", is followed by a comma, as in "- Falconer, the robot arm", or starts a run of
    capitalized words, as in "- Acme Corp". Asides in parentheses and quoted wording are skipped, since they explain the
    rule rather than name something. The words of your own name are skipped too: forbidding them would fail every draft."""
    mine = {word.lower() for word in re.findall(r"\w+", own_name)}
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
                                                          masked[terms[0].end():sentence.end()])):
                terms = terms[1:]
            for term in terms:
                covered = any(start < term.end() and term.start() < end for start, end in spans)
                if not covered and term.group(0).lower() not in mine and term.group(0) not in found:
                    found.append(term.group(0))
    return found


def _names_something(before: str, first: re.Match[str], rest: str) -> bool:
    """Whether the first capitalized word of a "Do not use" sentence is a name rather than a label or an instruction."""
    if before.strip():
        return True  # Capitalized in mid-sentence, as in "the Hive".
    if first.group(0).lower() in NOT_A_NAME or first.group(0).lower() in ORDINARY_CAPS:
        return False
    rest = rest.rstrip(" .")
    return not rest.strip() or rest.startswith(",") or bool(re.match(r"\s+[A-Z]", rest))


def _source_text(rel: str) -> str:
    path = ROOT / rel
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeError):
        return ""


def listed_terms(cfg: dict[str, Any], read: Callable[[str], str] | None = None) -> tuple[list[tuple[str, str, str]], list[tuple[str, str]]]:
    """The names your approved sources list under "Do not use" that no pattern under [guard] forbidden blocks.

    The assay blocks each of these by name, as if forbidden had a pattern for it, so a name is written once, in the
    fact bank. The first list holds those, as (term, pattern, the file that lists it). The second holds the ones it
    can't block that way, as (term, file): names your sources also use as fact, such as an employer named in a line
    about its customers, which blocking would fail every draft over. `read` gives a source's text, for a draft of one
    that isn't saved yet."""
    guard = cfg.get("guard", {})
    forbidden = list(guard.get("forbidden", []))
    own_name = str(cfg.get("candidate", {}).get("name", ""))
    texts = {rel: (read or _source_text)(rel) for rel in dict.fromkeys(guard.get("approved_sources", []))}
    stated = "\n".join(source_body(rel, text) for rel, text in texts.items())
    blocked: list[tuple[str, str, str]] = []
    shared: list[tuple[str, str]] = []
    seen: set[str] = set()
    for rel, text in texts.items():
        for term in unguarded_terms(text, forbidden, own_name):
            if term.lower() in seen:
                continue
            seen.add(term.lower())
            pattern = term_pattern(term)
            if re.search(pattern, stated, re.I):
                shared.append((term, rel))
            else:
                blocked.append((term, pattern, rel))
    return blocked, shared


def blocked_patterns(cfg: dict[str, Any], read: Callable[[str], str] | None = None) -> list[tuple[str, str]]:
    """Every pattern a draft must not match, each with where it comes from: "" for forbidden under [guard], or the
    file whose "Do not use" section names it."""
    return ([(_flexible(pattern), "") for pattern in cfg.get("guard", {}).get("forbidden", [])]
            + [(_flexible(term) if PLAIN_NAME.fullmatch(term) else _widen(pattern), rel)
               for term, pattern, rel in listed_terms(cfg, read)[0]])


PLAIN_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{3,}")
PLAIN_WORDS = re.compile(r"[A-Za-z0-9]+(?: [A-Za-z0-9]+)+")


def _widen(pattern: str) -> str:
    """A pattern whose "[\\s-]?", the optional space or hyphen that `term_pattern` writes between words, lets through
    anything that can join a name. Patterns saved before this read the same way, with no change to search.toml."""
    return pattern.replace(r"[\s-]?", JOIN)


def _flexible(pattern: str) -> str:
    """A forbidden pattern that's a plain name, such as Bluebird, also blocks it split anywhere by something that joins
    a name, as in "blue bird", "Sky-Lift" or "Blue_bird", and as a plural. Plain words with spaces between, such as
    "SkyLift 900", block the same name joined another way. A pattern with any other regular-expression syntax is
    taken as written."""
    if PLAIN_NAME.fullmatch(pattern):
        parts = list(pattern)
    elif PLAIN_WORDS.fullmatch(pattern):
        parts = pattern.split(" ")
    else:
        return _widen(pattern)
    body = JOIN.join(re.escape(part) for part in parts)
    return rf"\b{body}{'s?' if pattern[-1].isalpha() and pattern[-1].lower() != 's' else ''}\b"


def with_listed(guard: dict[str, Any], cfg: dict[str, Any], read: Callable[[str], str] | None = None) -> dict[str, Any]:
    """[guard] with a pattern added to forbidden for each name listed under "Do not use", as the assay reads it."""
    return {**guard, "forbidden": [pattern for pattern, _where in blocked_patterns({**cfg, "guard": guard}, read)]}


def _confidential(label: str, match: re.Match[str], where: str) -> str:
    listed = f", which {where} lists under \"Do not use\"" if where else ""
    return f"{label} uses a confidential term: {match.group(0)!r}{listed}"


def missing_sources(cfg: dict[str, Any]) -> list[str]:
    """Approved sources named in search.toml that aren't in the workspace. A copied example config names the example's
    own applications, so a new workspace has these until its owner points them at their own files."""
    return [rel for rel in cfg["guard"]["approved_sources"] if not (ROOT / rel).exists()]


def _read_sources(cfg: dict[str, Any]) -> str:
    parts = []
    for rel in cfg["guard"]["approved_sources"]:
        path = ROOT / rel
        if path.exists():
            parts.append(source_body(rel, path.read_text(encoding="utf-8")))
    return "\n".join(parts)


def saved_posting(folder: Path) -> str:
    """The posting text from a folder's posting.md, without the header `pyrite folder` puts on it."""
    path = folder / "posting.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").partition("- **Saved:**")[2].partition("\n")[2].strip()


def _value(digits: str, scale: str = "") -> str:
    """A number as one canonical string: 1,500,000 and 1.5M are both 1500000, and 4.0 is 4."""
    digits = digits.replace(",", "")
    try:
        value = Decimal(digits).scaleb(SCALE.get(scale.lower(), 0) if scale else 0)
    except InvalidOperation:
        return digits
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _numbers(text: str) -> set[str]:
    """The numbers a text states, percentages aside: a number the fact bank has only as a percentage counts nothing."""
    return {_value(m.group("digits"), m.group("word") or m.group("letter") or m.group("cash") or "")
            for m in NUMBER.finditer(PERCENT.sub(" ", text))}


def _percents(text: str) -> set[str]:
    return {_value(m.group(1)) for m in PERCENT.finditer(text)}


def _spelled(text: str) -> set[str]:
    """Numbers written as words, apart from a scale word that follows digits, which is part of that number."""
    return {match.group(0).lower() for match in NUMBER_WORD.finditer(NUMBER.sub(" ", text))}


def _number_errors(label: str, body: str, known: str, where: str) -> list[str]:
    """Numbers, percentages, spelled-out numbers and multiples in body that the known text doesn't hold."""
    errors = []
    invented_pct = sorted(_percents(body) - _percents(known))
    if invented_pct:
        errors.append(f"{label} has percentages {where}: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(_numbers(body) - _numbers(known))
    if invented:
        errors.append(f"{label} has numbers {where}: {', '.join(invented)}")
    # Both sides are read the same way. The "million" of "$1.5 million" is part of that number in the fact bank as it
    # is in a draft, so it doesn't approve "five million" of anything.
    spelled = sorted(_spelled(body) - _spelled(known))
    if spelled:
        errors.append(f"{label} spells out numbers {where}: {', '.join(spelled)}. Write numbers as digits, as measured.")
    multiples = sorted(({m.group(0).lower() for m in MULTIPLE.finditer(body)} - _phrases(MULTIPLE, known))
                       | {f"{_value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(body)}
                       - {f"{_value(m.group(1))}x" for m in NUMERIC_MULTIPLE.finditer(known)})
    if multiples:
        errors.append(f"{label} claims a multiple {where}: {', '.join(multiples)}. Give the measured number instead.")
    return errors


def _phrases(pattern: re.Pattern[str], text: str) -> set[str]:
    return {m.group(0).lower() for m in pattern.finditer(text)}


def _vocabulary(text: str) -> set[str]:
    """The words a text uses, in lowercase. The parts of a compound are words it uses too: GPU-batched names GPU, and
    CI/CD names CI."""
    words = WORD.findall(text)
    whole = {w.lower().strip("+") for w in words} | {w.lower() for w in words}
    return whole | {part.lower().strip("+") for w in words for part in re.split(r"[-/]", w) if part}


def _pages(pdf: Path) -> int | None:
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.CalledProcessError):
        # Without poppler, count page objects. A PDF that hides them in compressed streams reads as unknown, not as zero pages.
        try:
            return len(re.findall(rb"/Type\s*/Page\b", pdf.read_bytes())) or None
        except OSError:
            return None
    match = re.search(r"Pages:\s+(\d+)", out)
    return int(match.group(1)) if match else None


def _own_links(sources: str) -> set[str]:
    """The domains and addresses your own sources write, in lowercase: an employer such as Booking.com, a skill such as
    Socket.IO, your own email."""
    return {m.group(0).lower() for m in EMAIL.finditer(sources)} | {m.group(1).lower() for m in DOMAIN.finditer(sources)}


def _link(line: str, own: set[str]) -> str | None:
    """The first web address, domain or email in a line that your sources don't write, or None."""
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


def _clean_markup(line: str) -> str:
    return re.sub(r"^(#{1,4} |@ |~ |- )", "", line).replace("**", "")


def _is_acronym_or_camel(word: str) -> bool:
    return any(c.isupper() for c in word[1:])


def _known_term(low: str, known: set[str]) -> bool:
    """Whether a term, in lowercase, is one the sources use, or a compound of ones they use: Cross-Team names nothing
    new when they write both words."""
    parts = [part.strip("+") for part in re.split(r"[-/]", low) if part]
    return low in known or (len(parts) > 1 and all(part in known for part in parts))


def _novel_terms(text: str, vocab: set[str], allowed: set[str]) -> list[str]:
    """Capitalized terms that no approved source has ever used: likely invented skills."""
    known = vocab | allowed | ORDINARY_CAPS
    novel = []
    for sentence in SENTENCE.split(text):
        words = WORD.findall(sentence)
        for index, word in enumerate(words):
            # The first word of a sentence is capitalized anyway, so there only an acronym, CamelCase or a title stands out.
            if not (_is_acronym_or_camel(word) or (word[0].isupper() and (index or word.lower() in TITLE_WORDS))):
                continue
            if _known_term(word.lower().strip("+"), known):
                continue
            if word not in novel:
                novel.append(word)
    return novel


def _posting_terms(posting: str) -> set[str]:
    """Names the posting uses for tools and skills: capitalized mid-sentence or an acronym, and never written in lowercase."""
    named, lowercase = set(), set()
    for sentence in SENTENCE.split(posting):
        for index, word in enumerate(WORD.findall(sentence)):
            if word.islower():
                lowercase.add(word.strip("+"))
            elif _is_acronym_or_camel(word) or (index and word[0].isupper() and len(word) >= 4):
                named.add(word.lower().strip("+"))
    return named - lowercase


def _borrowed_terms(text: str, posting: str, vocab: set[str], allowed: set[str], already: list[str]) -> list[str]:
    """Posting terms the draft opens a sentence or bullet with, where the capitals check alone can't tell a name from a verb.

    Lowercase words are left alone: a posting's "Gives Back" program mustn't block "came back".
    """
    known = vocab | allowed | ORDINARY_CAPS
    wanted = {term for term in _posting_terms(posting) - {word.lower().strip("+") for word in already} if not _known_term(term, known)}
    borrowed = []
    for word in WORD.findall(text):
        if word[0].isupper() and word.lower().strip("+") in wanted and word not in borrowed:
            borrowed.append(word)
    return borrowed


def _either_side(sentence: str, match: re.Match[str]) -> tuple[str, str]:
    """The words before and after a claim that could deny it."""
    return sentence[max(0, match.start() - DENIAL_WINDOW):match.start()], sentence[match.end():match.end() + DENIAL_WINDOW]


def _disclaimed(before: str, after: str, disclaimers: list[str]) -> bool:
    """Whether a sentence denies the claim it names.

    A negative counts when it leads up to the claim ("I have not led X"), or when you deny it in the
    first person afterwards ("the posting lists X, and I have not done it"). A stray negative later
    on denies nothing: "Led X with no delays" is still a claim.
    """
    clause = CLAUSE_BREAK.split(NOT_A_NEGATIVE.sub(" ", before))[-1]
    for pattern in disclaimers:
        for negative in re.finditer(pattern, clause, re.I):
            if len(clause[negative.end():].split()) <= DENIAL_REACH:
                return True
    denials = list(FIRST_PERSON_DENIAL.finditer(after))
    for denial in denials:
        back = REFERS_BACK.match(after, denial.end())
        if back and not PRAISE.search(back.group(0)):
            return True
    # A claim the sentence puts in the posting's mouth needs only a denial of your own after it, of anything, so long
    # as it is one: "the posting asks for X, and I have never missed an audit leading it" is praise, and claims X.
    plain = [denial for denial in denials if not PRAISE.search(" ".join(after[denial.end():].split()[:4]))]
    return bool(plain) and ATTRIBUTED.search(before) is not None


def _disguises(text: str, label: str) -> list[str]:
    """Characters that make a word read one way and match another. None belongs in a resume, a letter or a brief."""
    errors = []
    hidden = sorted({f"U+{ord(ch):04X}" for ch in text.lstrip("﻿") if unicodedata.category(ch) == "Cf"})
    if hidden:
        errors.append(f"{label} contains invisible characters ({', '.join(hidden[:5])}). Retype the lines that hold them.")
    lookalike = list(dict.fromkeys(w for w in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", text)) if _lookalike(w)))
    mixed = []
    for word in re.findall(r"[^\W\d_]+", text):
        scripts = {unicodedata.name(ch, "?").split(" ")[0] for ch in word}
        if ("LATIN" in scripts and len(scripts) > 1 and word not in mixed and not UNIT.fullmatch(word)
                and not _lookalike(unicodedata.normalize("NFKC", word))):
            mixed.append(word)
    if lookalike:
        errors.append(f"{label} spells words in look-alike letters from another alphabet, which hides them from the checks "
                      f"and from screening software: {', '.join(lookalike[:5])}. Retype them.")
    if mixed:
        errors.append(f"{label} mixes alphabets inside a word, which hides it from the checks: {', '.join(mixed[:5])}")
    return errors


def _lookalike(word: str) -> bool:
    """Whether a word is spelled only with plain Latin letters and letters that pass for them, using at least one of
    the latter. A word in another language has letters with no Latin double, so it isn't one."""
    folded = word.translate(LOOKALIKES)
    return folded != word and folded.isascii()


def _fold_lookalikes(match: re.Match[str]) -> str:
    word = match.group(0)
    return word.translate(LOOKALIKES) if _lookalike(word) else word


def _matchable(text: str) -> str:
    """The text as a reader sees it: compatibility forms folded (full-width digits, no-break spaces), accents and
    look-alike letters read as the plain letter, invisible characters and emphasis markers gone. Every check reads
    this, and so do the sources it's compared with, so a word split by formatting or an accent is still that word."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn"))
    text = unicodedata.normalize("NFC", text).translate(PLAIN_LATIN)
    text = re.sub(r"[^\W\d_]+", _fold_lookalikes, text)
    return EMPHASIS.sub("", text)


def _set_aside(body: str, phrase: str) -> str:
    """The body with a phrase blanked out where it stands as words, so a company called Meta leaves Metadata alone."""
    phrase = phrase.strip()
    return re.sub(rf"(?<!\w){re.escape(phrase)}(?!\w)", " ", body) if phrase else body


# A job's requisition number, as a posting labels it: "Requisition ID: R-0145", "Req #: 5123", "Job ID JR2026528875".
# The number must have a digit in it and four characters or more, so "Job no. 1" names nothing.
REQUISITION_LABEL = (r"(?:requisition|req\.?|job|position|posting)(?:[ \t]+(?:id|number|no\.?|num))?[ \t]*[:#]?[ \t]*#?[ \t]*")
REQUISITION_ID = r"[A-Za-z]{0,6}[-_]?\d[\w-]{2,30}"
POSTED_REQUISITION = re.compile(
    rf"\b(?:requisition(?:[ \t]+(?:id|number|no\.?|num))?|req(?:\.|[ \t]*(?:id|#|no\.?|number))|job[ \t]*(?:id|#|no\.?|number)"
    rf"|(?:position|posting)[ \t]*(?:id|#|number))[ \t]*[:#]?[ \t]*#?[ \t]*({REQUISITION_ID})",
    re.I,
)
# Workday names a job by its path, which ends in the requisition: "/job/Remote/Lead-Engineer_REQ-14879-1", where -1
# numbers the posting of that requisition.
WORKDAY_POSTING = re.compile(r"-\d{1,2}$")


def requisitions(posting: str = "", source_key: str = "", source_id: str = "") -> list[str]:
    """The job's own requisition numbers, which a cover letter may cite: the board's id for the job, and any number the
    posting labels as its requisition or job id. A job added by hand has an id Pyrite made up, which no one cites."""
    found: list[str] = []
    source_id = str(source_id or "").strip()
    if source_id and not source_key.startswith("manual"):
        if source_id.startswith("/") and "_" in source_id:
            tail = source_id.rsplit("_", 1)[1]
            found += [tail, WORKDAY_POSTING.sub("", tail)]
        elif re.search(r"\d", source_id) and "/" not in source_id:
            found.append(source_id)
    found += [match.group(1).rstrip("-_") for match in POSTED_REQUISITION.finditer(posting or "")]
    # Longest first, so a posting's own suffix goes with it rather than leaving a stray number behind.
    return sorted({ident for ident in found if len(ident) >= 4 and re.search(r"\d", ident)}, key=lambda i: (-len(i), i))


def _set_aside_requisitions(body: str, idents: list[str]) -> str:
    """A letter's body with the job's requisition numbers blanked out: each as written anywhere, in any case, and its
    digits alone where a label says what they are, as in "requisition 0145" for R-0145."""
    for ident in idents:
        ident = _matchable(ident).strip()
        body = re.sub(rf"(?<!\w){re.escape(ident)}(?!\w)", " ", body, flags=re.I)
        digits = re.sub(r"\D", "", ident)
        if digits != ident and len(digits) >= 4:
            body = re.sub(rf"\b{REQUISITION_LABEL}{re.escape(digits)}(?!\w)", " ", body, flags=re.I)
    return body


def _unsupported(text: str, guard: dict[str, Any], label: str) -> tuple[list[str], list[str]]:
    """Errors for unsupported claims, and the exact words of the claims that were properly disclaimed."""
    errors, disclaimed = [], []
    for sentence in SENTENCE.split(text):
        claimed = False
        # Every mention counts, not just the first: "I have not worked under X, but led X audits" claims X.
        for match in (m for pattern in guard["unsupported"] for m in re.finditer(pattern, sentence, re.I)):
            if _disclaimed(*_either_side(sentence, match), guard["disclaimers"]):
                disclaimed.append(match.group(0))
            else:
                claimed = True
        if claimed:
            errors.append(f"{label} makes an unsupported claim: {sentence.strip()[:140]!r}")
    return errors, disclaimed


def explain(sentence: str, guard: dict[str, Any]) -> dict[str, Any]:
    """How the confidential and unsupported checks read one piece of text, for the Profile tab's test box: the text as
    the checks see it, and each match in it as never (confidential), claim (unsupported and claimed) or denied
    (unsupported, but the sentence denies it). It uses the same patterns and the same reading of a denial as a draft's
    check, so a sentence that passes here passes there."""
    text = _matchable(sentence)
    hits = []
    for pattern in guard.get("forbidden", []):
        hits += [{"start": m.start(), "end": m.end(), "kind": "never", "pattern": pattern}
                 for m in re.finditer(pattern, text, re.I) if m.end() > m.start()]
    at = 0
    for part in SENTENCE.split(text):
        at = text.index(part, at)
        for pattern in guard.get("unsupported", []):
            for m in re.finditer(pattern, part, re.I):
                if m.end() == m.start():
                    continue
                denied = _disclaimed(*_either_side(part, m), guard.get("disclaimers", []))
                hits.append({"start": at + m.start(), "end": at + m.end(), "kind": "denied" if denied else "claim",
                             "pattern": pattern})
        at += len(part)
    hits.sort(key=lambda hit: (hit["start"], -hit["end"]))
    return {"text": text, "hits": hits, "blocked": any(hit["kind"] != "denied" for hit in hits)}


def check_text(
    text: str, kind: str, cfg: dict[str, Any], sources: str, company: str = "", title: str = "", contact_line: str | None = None,
    posting: str = "", blocked: list[tuple[str, str]] | None = None, requisition: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Check one document's Markdown. kind is 'resume' or 'letter'. posting is the job's text, when there is one.
    blocked is what blocked_patterns() gives, for sources that aren't saved yet; by default it's read from the files.
    requisition is the job's own requisition numbers, from requisitions(), which a letter may cite."""
    errors, warnings = [], []
    guard = cfg["guard"]
    blocked = blocked_patterns(cfg) if blocked is None else blocked
    label = "Resume" if kind == "resume" else "Cover letter"
    errors += _disguises(text, label)
    blank = next((row.strip() for row in text.splitlines() if BLANK.search(row)), None)
    if blank:
        errors.append(f"{label} has an unfilled placeholder: {blank[:120]!r}")
    # The draft and everything it's compared with are read the same way.
    text, sources, company, title, posting = (_matchable(part) for part in (text, sources, company, title, posting))
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Nothing from the do-not-use list, anywhere.
    for pattern, where in blocked:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(_confidential(label, match, where))

    # Unsupported claims, unless the sentence disclaims them before naming them.
    unsupported, disclaimed = _unsupported(text, guard, label)
    errors += unsupported

    if contact_line is None:
        contact_line = next((row for row in sources.splitlines() if row.startswith("@ ")), None)
    contact_line = _matchable(contact_line).strip() if contact_line else None
    if contact_line and contact_line not in lines:
        errors.append(f"{label} contact line doesn't match the approved one.")
    name_line = f"# {cfg['candidate']['name']}"
    if not any(line == _matchable(name_line).strip() for line in lines):
        errors.append(f"{label} doesn't open with '{name_line}'.")

    # Only the approved contact line itself is exempt from what follows. Any other line is checked, whatever it starts with.
    body = "\n".join(line for line in text.splitlines() if line.strip() != contact_line)
    # The company and role are the one thing that's meant to change.
    body = _set_aside(_set_aside(body, company), title)
    if kind == "letter":
        # Only a letter is dated. A date alone on a line of a resume is a claim, and its numbers are checked.
        body = DATE_LINE.sub(" ", body)
        # A letter may cite the job's requisition number, as an application form asks. It measures nothing, and only a
        # letter needs it: on a resume it would be a claim.
        body = _set_aside_requisitions(body, requisition or [])
    # A confidential term or a disclaimed claim has been dealt with above, so its own words aren't judged again.
    for pattern, _where in blocked:
        body = re.sub(pattern, " ", body, flags=re.I)
    for span in disclaimed:
        body = body.replace(span, " ")

    own = _own_links(sources)
    for line in lines:
        if line == contact_line:
            continue
        if _link(line, own):
            errors.append(f"{label} contains a link or domain that isn't yours: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"{label} has an unfilled placeholder: {placeholder.group(0)!r}")

    # Numbers stay as measured. Your phone number and zip code measure nothing.
    vocab = _vocabulary(sources)
    errors += _number_errors(label, body, without_contact(sources), "not in the fact bank")

    # Specialist terms need a source. A resume can't name a skill you've never claimed, and a title
    # from a job board is no source: on a resume only the exact title was set aside above. A letter
    # names the role in its own words, and its terms only ever warn.
    # A placeholder is reported above, so "[X]" isn't named again as a term. One line at a time, as above, so a
    # bracket left open on one line and closed on a later one can't hide the words between from this check.
    # A number is judged above with its scale, so the K of 1.4K isn't read again as a term of its own.
    plain = "\n".join(_clean_markup(NUMBER.sub(" ", PLACEHOLDER.sub(" ", row)).strip()) for row in body.splitlines())
    allowed = _vocabulary(company if kind == "resume" else f"{company} {title}")
    allowed |= {w.lower() for w in guard.get("ordinary_words", [])}
    fix = ". Remove them, or add them to profile/approved-terms.txt if they're true."
    novel = _novel_terms(plain, vocab, allowed)
    if novel:
        message = f"{label} names terms not in your approved sources: {', '.join(novel[:15])}"
        if kind == "resume":
            errors.append(message + fix)
        else:
            warnings.append(message)
    borrowed = _borrowed_terms(plain, posting, vocab, allowed, novel) if posting else []
    if borrowed:
        message = f"{label} repeats terms from the posting that aren't in your approved sources: {', '.join(borrowed[:15])}"
        if kind == "resume":
            errors.append(message + fix)
        else:
            warnings.append(message)
    warnings += wording_warnings(body, kind, label)
    return errors, warnings


def wording_warnings(body: str, kind: str, label: str) -> list[str]:
    """Signs of generic or machine-written prose, and a letter that runs long. Read them; none blocks a draft."""
    warnings = []
    if EM_DASH in body:
        warnings.append(f"{label} uses an em dash, which readers now take as a sign of unedited AI text. Use a comma, colon or full stop.")
    cliches = sorted({m.group(0).lower() for m in CLICHE.finditer(body)})
    if cliches:
        warnings.append(f"{label} uses wording that reads as filler: {', '.join(cliches)}. Say what was built, cut or shipped instead.")
    if kind == "letter":
        words = len(WORD.findall(body))
        if words > LETTER_WORDS_MAX:
            warnings.append(f"Cover letter runs {words} words; keep it under {LETTER_WORDS_MAX}, three or four short paragraphs.")
    return warnings


def check_brief(text: str, cfg: dict[str, Any], sources: str, company: str = "", title: str = "", posting: str = "") -> tuple[list[str], list[str]]:
    """Check an interview prep brief.

    It's private notes, so it has no name or contact line to match, and it may repeat what the posting
    says. What it has you say still has to be true: nothing confidential, no unsupported claim, and no
    number that neither the fact bank nor the posting holds. A link is blocked too, since a posting
    could try to have one passed along to you.
    """
    errors, warnings = [], []
    guard = cfg["guard"]
    errors += _disguises(text, "Brief")
    text, sources, company, title, posting = (_matchable(part) for part in (text, sources, company, title, posting))

    for pattern, where in blocked_patterns(cfg):
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(_confidential("Brief", match, where))

    unsupported, disclaimed = _unsupported(text, guard, "Brief")
    errors += unsupported

    body = _set_aside(_set_aside(text, company), title)
    for span in disclaimed:
        body = body.replace(span, " ")
    own = _own_links(sources)
    for line in (line.strip() for line in body.splitlines()):
        if _link(line, own):
            errors.append(f"Brief contains a link or web address: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"Brief has an unfilled placeholder: {placeholder.group(0)!r}")

    known = without_contact(sources) + "\n" + posting
    errors += _number_errors("Brief", body, known, "that aren't in the fact bank or the posting")

    # A term from the posting alone is a requirement, not something you can claim.
    plain = "\n".join(_clean_markup(line) for line in body.splitlines())
    allowed = _vocabulary(f"{company} {title}") | {w.lower() for w in guard.get("ordinary_words", [])}
    unclaimed = _novel_terms(plain, _vocabulary(sources), allowed)
    asked_for = _vocabulary(posting)
    from_posting = [term for term in unclaimed if term.lower().strip("+") in asked_for]
    from_nowhere = [term for term in unclaimed if term not in from_posting]
    if from_posting:
        warnings.append(f"Named in the posting but not in your fact bank, so make sure the brief treats them as gaps: {', '.join(from_posting[:15])}")
    if from_nowhere:
        warnings.append(f"Brief names terms that aren't in your fact bank or the posting: {', '.join(from_nowhere[:15])}")
    return errors, warnings


def check_resume_structure(text: str, cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    source = ROOT / cfg["guard"]["heading_source"]
    if not source.exists():
        # Nothing to compare the employers, titles and dates with, so nothing can pass that check.
        return [f"heading_source under [guard] in profile/search.toml is {cfg['guard']['heading_source']!r}, which isn't in "
                "your workspace. Point it at your own master resume."], warnings
    reference = source.read_text(encoding="utf-8")
    # Stripped first, as the builder does: an indented heading still prints as a heading.
    headings = lambda doc: {row.strip() for row in doc.splitlines() if row.strip().startswith(("### ", "#### "))}
    approved, present = headings(reference), headings(text)
    for heading in sorted(present - approved):
        errors.append(f"Employer, title or dates differ from your record: {heading!r}")
    for heading in sorted(approved - present):
        warnings.append(f"Left out of the timeline: {heading.lstrip('# ')}")
    # The builder prints each role with the employer above it, so a role moved under another employer is a false claim
    # even though both headings are on record.
    record = _employers(reference)
    for role, employer in _employers(text).items():
        if role in approved and role in record and employer != record[role]:
            errors.append(f"{role.lstrip('# ')!r} sits under {(employer or 'no employer').lstrip('# ')!r}, but your record "
                          f"has it under {(record[role] or 'no employer').lstrip('# ')!r}.")
    # A line shaped like a role heading, written as plain or bold text, reads as one on the page.
    on_record = {_role_key(row) for row in reference.splitlines() if row.strip()}
    for row in text.splitlines():
        line = row.strip()
        if not line.startswith("#") and ROLE_LINE.match(line.replace("*", "")) and _role_key(line) not in on_record:
            errors.append(f"Employer, title or dates differ from your record: {line!r}")
    for needed in ("## Experience", "## Education"):
        if not any(row.strip().startswith(needed) for row in text.splitlines()):
            errors.append(f"Resume is missing the {needed[3:]} section.")
    for item in cfg["guard"].get("expected_on_resume", []):
        if item["text"] not in text:
            warnings.append(f"{item['label']} isn't on this resume.")
    return errors, warnings


def _employers(doc: str) -> dict[str, str | None]:
    """Each "####" role heading in a resume, and the "###" employer heading above it, as the builder pairs them."""
    employer: str | None = None
    pairs: dict[str, str | None] = {}
    for row in doc.splitlines():
        line = row.strip()
        if line.startswith("## "):
            employer = None
        elif line.startswith("### "):
            employer = line
        elif line.startswith("#### "):
            pairs.setdefault(line, employer)
    return pairs


def _role_key(line: str) -> str:
    """A line as a role heading reads, whether it's written as a heading, bold or plain text."""
    return re.sub(r"\s+", " ", line.replace("*", "").lstrip("#").strip())


def drafter_versions(folder: Path) -> dict[str, str]:
    """Which drafter built each .docx in the folder. Files from before versioning read as "1"."""
    import zipfile
    versions = {}
    for docx in sorted(folder.glob("*.docx")):
        try:
            with zipfile.ZipFile(docx) as z:
                core = z.read("docProps/core.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError, OSError):
            versions[docx.name] = "unknown"
            continue
        match = re.search(r"<cp:version>([^<]*)</cp:version>", core)
        versions[docx.name] = match.group(1).strip() if match and match.group(1).strip() else "1"
    return versions


def _built(path: Path) -> bool:
    """Whether a file is a document built from the drafts: a .docx, .pdf, or the .txt the fill sheet points paste boxes at."""
    return path.suffix in (".pdf", ".docx") or (path.suffix == ".txt" and ("_Resume_" in path.name or "_Cover_Letter_" in path.name))


def fingerprints(folder: Path) -> dict[str, str]:
    """A hash of each file a passing check covered: the two sources and the documents built from them."""
    covered = [p for p in sorted(folder.iterdir()) if p.is_file() and (p.name in ("resume.md", "cover-letter.md") or _built(p))]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in covered}


GUARD_KEY = "search.toml [guard]"


def source_fingerprints(cfg: dict[str, Any]) -> dict[str, str]:
    """A hash of everything a pass was judged against: each approved source, the heading source and the [guard] rules.
    Taking a fact out of the bank, or a new pattern in [guard], means an earlier pass no longer says the draft is true."""
    guard = cfg["guard"]
    prints = {}
    for rel in dict.fromkeys([*guard["approved_sources"], guard["heading_source"]]):
        try:
            prints[rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
        except OSError:
            prints[rel] = "missing"
    prints[GUARD_KEY] = hashlib.sha256(json.dumps(guard, sort_keys=True, default=str).encode()).hexdigest()
    return prints


def sources_changed(cfg: dict[str, Any], recorded: dict[str, Any] | None) -> list[str]:
    """Which sources or rules changed after a pass. A pass from before these were recorded has nothing to compare."""
    if not recorded:
        return []
    now = source_fingerprints(cfg)
    return sorted(name for name in set(recorded) | set(now) if recorded.get(name) != now.get(name))


def changed_since(folder: Path, checked: dict[str, Any]) -> list[str]:
    """Which of the files that passed have changed or gone since, plus a cover letter or a built document added
    afterwards. A pass recorded before the paste-box .txt files were covered says nothing about them."""
    covers_txt = any(name.endswith(".txt") for name in checked)
    added = {p.name for p in folder.iterdir() if p.is_file() and _built(p) and (covers_txt or p.suffix != ".txt")} \
        if folder.is_dir() else set()
    names = set(checked) | {"cover-letter.md"} | added
    now: dict[str, str | None] = {}
    for name in names:
        try:
            now[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        except OSError:
            now[name] = None
    return sorted(name for name in names if checked.get(name) != now[name])


def not_covered(folder: Path, cfg: dict[str, Any], result: dict[str, Any] | str | None) -> str:
    """Why a job's last assay verdict doesn't vouch for its folder as it is now, or "" when it does.

    Anything that carries the draft's text to an employer asks this first. A pass covers the files it hashed,
    judged against the fact bank and [guard] rules it hashed, and nothing else.
    """
    if isinstance(result, str):
        result = json.loads(result) if result else None
    if not result:
        return "The assay hasn't checked this draft."
    if not result.get("ok"):
        return "The assay's last check of this draft didn't pass."
    checked = result.get("checked")
    if not checked:
        return "The assay's last pass didn't record which files it covered."
    reasons = []
    files = changed_since(folder, checked)
    if files:
        reasons.append(f"{', '.join(files)} changed after the assay passed the draft.")
    sources = sources_changed(cfg, result.get("checked_sources"))
    if sources:
        reasons.append(f"{', '.join(sources)} changed after the assay passed the draft, so the pass no longer vouches for it.")
    return " ".join(reasons)


def keyword_overlap(resume: str, description: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """How many of the skill terms the posting uses also appear on the resume."""
    wanted, covered = [], []
    for pattern, _weight in cfg["scoring"]["keywords"]:
        if re.search(pattern, description, re.I):
            term = pattern.split("|")[0].replace("\\b", "").replace("\\", "")
            wanted.append(term)
            if re.search(pattern, resume, re.I):
                covered.append(term)
    missing = [term for term in wanted if term not in covered]
    pct = round(100 * len(covered) / len(wanted)) if wanted else None
    return {"pct": pct, "covered": covered, "missing": missing}


def check_application(folder: Path, cfg: dict[str, Any], company: str, title: str, description: str = "",
                      source_key: str = "", source_id: str = "") -> dict[str, Any]:
    """Run every gate over an application folder. source_key and source_id are the job's, which name its requisition."""
    errors, warnings = [], []
    sources = _read_sources(cfg)
    warnings += [f"approved_sources under [guard] in profile/search.toml names {rel!r}, which isn't in your workspace, "
                 "so nothing in it counts as a source." for rel in missing_sources(cfg)]
    posting = description or saved_posting(folder)

    resume_path = folder / "resume.md"
    if not resume_path.exists():
        return {"ok": False, "errors": ["resume.md is missing."], "warnings": [], "overlap": None}
    drafts: dict[str, str] = {}
    for name in ("resume.md", "cover-letter.md"):
        path = folder / name
        if name == "cover-letter.md" and not path.exists():
            continue
        try:
            drafts[name] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return {"ok": False, "errors": [f"{name} isn't saved as UTF-8 text. Save it as UTF-8 and check again."],
                    "warnings": [], "overlap": None}
        except OSError as exc:
            return {"ok": False, "errors": [f"Couldn't read {name}: {exc.strerror or exc}."], "warnings": [], "overlap": None}
    resume = drafts["resume.md"]
    new_errors, new_warnings = check_text(resume, "resume", cfg, sources, company, title, posting=posting)
    errors += new_errors
    warnings += new_warnings
    new_errors, new_warnings = check_resume_structure(resume, cfg)
    errors += new_errors
    warnings += new_warnings

    if "cover-letter.md" in drafts:
        new_errors, new_warnings = check_text(drafts["cover-letter.md"], "letter", cfg, sources, company, title, posting=posting,
                                              requisition=requisitions(posting, source_key, source_id))
        errors += new_errors
        warnings += new_warnings

    if not (folder / "notes.md").exists():
        warnings.append("notes.md is missing.")

    guard = cfg["guard"]
    for pdf in folder.glob("*.pdf"):
        pages = _pages(pdf)
        is_letter = "Cover_Letter" in pdf.name
        limit = guard["max_letter_pages"] if is_letter else guard["max_resume_pages"]
        if pages is None:
            warnings.append(f"Couldn't read the page count of {pdf.name}.")
        elif pages > limit:
            errors.append(f"{pdf.name} is {pages} pages; the limit is {limit}.")

    drafter = drafter_versions(folder)
    sent = sent_copies(folder)
    if not sent:
        for name, version in drafter.items():
            if version != DRAFTER_VERSION:
                warnings.append(f"{name} was built by drafter {version}; the current drafter is {DRAFTER_VERSION}. Rebuild it to get the current format.")

    overlap = keyword_overlap(resume, description, cfg) if description else None
    report = {"ok": not errors, "errors": errors, "warnings": warnings, "overlap": overlap, "drafter": drafter}
    if sent:
        # What was sent is the record, so an older drafter is only a fact about it. Rebuilding would make the folder
        # differ from what the company has, which the dashboard then flags as changed after sending.
        report["sent_drafter"] = drafter_versions(folder / SENT_FOLDER)
    return report


# Above this share of the posting's skill terms a resume reads as copied from it, which screeners mark down. The
# dashboard draws the same line. With only a few terms in play the share says little, so it isn't held against a draft.
OVERLAP_MAX = 85
OVERLAP_MIN_TERMS = 5
OVERLAP_TARGET = "60 to 80%"
# Warnings a rewrite can clear. The rest, such as a file from an older drafter, are for you.
POLISH_MARKERS = ("names terms not in your approved sources", "repeats terms from the posting", "uses an em dash",
                  "reads as filler", "Cover letter runs")
POLISH_ASK = ("The fact checker passed your draft, so it's ready to send, but it flagged these, which are worth fixing first. "
              "Fix them and change nothing else, adding no claim the fact bank doesn't support:")


def polish_requests(report: dict[str, Any], letter: bool = True) -> list[str]:
    """What's worth one more pass on a draft that passed: warnings a rewrite can clear, and too close a copy of the posting.

    The draft is ready without these. The daily run and a refresh still give it one more go, because a
    warning you'd otherwise fix by hand is cheaper to fix before you read the draft. `letter` is whether
    the run may change the cover letter; when it can't, the letter's warnings are left for you.
    """
    asks = [warning for warning in report.get("warnings", [])
            if any(marker in warning for marker in POLISH_MARKERS) and (letter or not warning.startswith("Cover letter"))]
    copied = reads_as_copied(report.get("overlap"))
    if copied:
        asks.append(f"{copied} Aim for {OVERLAP_TARGET}: keep the terms the candidate's record backs best and say the rest in plain words. "
                    f"It uses: {', '.join(report['overlap']['covered'])}.")
    return asks


def reads_as_copied(overlap: dict[str, Any] | None) -> str:
    """A sentence saying the resume uses too many of the posting's skill terms, or "" when it doesn't."""
    overlap = overlap or {}
    pct, covered = overlap.get("pct"), overlap.get("covered") or []
    if pct is not None and pct > OVERLAP_MAX and len(covered) + len(overlap.get("missing") or []) >= OVERLAP_MIN_TERMS:
        return f"The resume uses {pct}% of the posting's skill terms, which reads as copied from it."
    return ""
