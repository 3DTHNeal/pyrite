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
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .store import ROOT

# A date alone on its line is a letter's date, which may be any day. A date inside a sentence is a claim like any other.
DATE_LINE = re.compile(
    r"(?m)^[ \t]*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}[ \t]*$"
)
# A number keeps its scale: $3M isn't the 3 the fact bank measured, and 212K tests aren't 212. Each reads as its value,
# so 1.5M and 1,500,000 are the same number. A lowercase m is left alone, since 30m is as often minutes as millions.
NUMBER = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?:\s?(thousand|million|billion|trillion)\b|(K|k|M|MM|B|bn|BN)\b)?"
)
SCALE = {"thousand": 3, "k": 3, "million": 6, "m": 6, "mm": 6, "billion": 9, "b": 9, "bn": 9, "trillion": 12}
# A percentage spelled out is still a percentage.
PERCENT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|percent\b|per\s?cent\b|pct\b)", re.I)
# Multiples and orders of magnitude claimed in words are measurements too.
MULTIPLE = re.compile(
    r"\b(?:doubled|tripled|quadrupled|halved|(?:two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)[- ]?fold|"
    r"(?:double|triple)[- ]digits?|order[s]? of magnitude)\b",
    re.I,
)
# Domains people link from a resume, link shorteners and chat handles included, and anything shaped like domain/path.
# File types a skill list names, such as Node.js/React, aren't domains.
LINK_TLDS = "com|io|ai|org|net|co|dev|app|me|ly|gg|so|sh|to|tv|cc|gl|xyz|info|biz|us|uk|ca|de|eu|link|site|page|online|tech|blog|bio|fm|im"
URLISH = re.compile(
    rf"https?://|www\.|\b[\w-]+\.(?:{LINK_TLDS})\b|\b[\w-]{{2,}}\.(?!(?:js|ts|py|md|rb|go|rs|cs|cpp|java|kt|net)\b)[a-z]{{2,}}/[\w-]",
    re.I,
)
# Markdown emphasis can split a word in two that renders whole: **Blue****bird**, or _40_. Underscores inside a word stay.
EMPHASIS = re.compile(r"\*+|(?<!\w)_+|_+(?!\w)")
PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{\{|\bTODO\b|\bTBD\b|\bXXX\b|<[a-z_ ]+>")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[-/.][A-Za-z0-9+#]+)*\+*")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
# Sections of a fact bank that list what must not be claimed, at any heading level. Their words and numbers approve
# nothing, and neither do their subsections.
HEADING = re.compile(r"^[ \t]*(#{1,6})[ \t]+(.*)$")
EXCLUDED_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use|unsupported)\b", re.I)
DO_NOT_USE_SECTION = re.compile(r"\W*(?:do[- ]?not[- ]use|don['’]t[- ]use)\b", re.I)
# A negative only disclaims what follows it in the same clause. "Not only" is no negative at all.
NOT_A_NEGATIVE = re.compile(r"\b(?:not|no)\s+(?:only|just|merely|less|fewer)\b", re.I)
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
# Some negatives that point back are praise, not denial: "I led X, and I could not be prouder of it", "...never missed one".
PRAISE = re.compile(
    r"\b(?:be|prouder|happier|better|more|enough|wait|forget|regret|change|stop|miss|missed|say|imagine|believe|recommend|"
    r"overstate|thank|trade|resist|want|ask|love|enjoy|enjoyed|loved)\b",
    re.I,
)
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
EM_DASH = "—"
LETTER_WORDS_MAX = 350  # a letter longer than this is the one readers say they stop reading
ORDINARY_CAPS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday", "friday",
    "i", "dear", "sincerely", "hiring", "manager", "team", "summary",
    "experience", "skills", "education", "patent", "patents", "certifications", "core", "selected", "scope",
    "leadership", "ai", "us", "u.s", "ml", "and", "the", "of",
}


def _split_sections(text: str, title: re.Pattern) -> tuple[str, str]:
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


def claimable(text: str) -> str:
    """A source without the sections that list what must not be claimed."""
    return _split_sections(text, EXCLUDED_SECTION)[0]


def do_not_use(text: str) -> str:
    """What a fact bank lists under "Do not use", subsections included."""
    return _split_sections(text, DO_NOT_USE_SECTION)[1]


def missing_sources(cfg: dict) -> list[str]:
    """Approved sources named in search.toml that aren't in the workspace. A copied example config names the example's
    own applications, so a new workspace has these until its owner points them at their own files."""
    return [rel for rel in cfg["guard"]["approved_sources"] if not (ROOT / rel).exists()]


def _read_sources(cfg: dict) -> str:
    parts = []
    for rel in cfg["guard"]["approved_sources"]:
        path = ROOT / rel
        if path.exists():
            parts.append(claimable(path.read_text(encoding="utf-8")))
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
    return {_value(m.group(1), m.group(2) or m.group(3) or "") for m in NUMBER.finditer(PERCENT.sub(" ", text))}


def _percents(text: str) -> set[str]:
    return {_value(m.group(1)) for m in PERCENT.finditer(text)}


def _spelled(text: str) -> set[str]:
    """Numbers written as words, apart from a scale word that follows digits, which is part of that number."""
    return {match.group(0).lower() for match in NUMBER_WORD.finditer(NUMBER.sub(" ", text))}


def _number_errors(label: str, body: str, known: str, vocab: set[str], where: str) -> list[str]:
    """Numbers, percentages, spelled-out numbers and multiples in body that the known text doesn't hold."""
    errors = []
    invented_pct = sorted(_percents(body) - _percents(known))
    if invented_pct:
        errors.append(f"{label} has percentages {where}: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(_numbers(body) - _numbers(known))
    if invented:
        errors.append(f"{label} has numbers {where}: {', '.join(invented)}")
    spelled = sorted(_spelled(body) - vocab)
    if spelled:
        errors.append(f"{label} spells out numbers {where}: {', '.join(spelled)}. Write numbers as digits, as measured.")
    multiples = sorted({m.group(0).lower() for m in MULTIPLE.finditer(body)} - _phrases(MULTIPLE, known))
    if multiples:
        errors.append(f"{label} claims a multiple {where}: {', '.join(multiples)}. Give the measured number instead.")
    return errors


def _phrases(pattern: re.Pattern, text: str) -> set[str]:
    return {m.group(0).lower() for m in pattern.finditer(text)}


def _vocabulary(text: str) -> set[str]:
    return {w.lower().strip("+") for w in WORD.findall(text)} | {w.lower() for w in WORD.findall(text)}


def _pages(pdf: Path) -> int | None:
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        # Without poppler, count page objects. A PDF that hides them in compressed streams reads as unknown, not as zero pages.
        try:
            return len(re.findall(rb"/Type\s*/Page\b", pdf.read_bytes())) or None
        except OSError:
            return None
    match = re.search(r"Pages:\s+(\d+)", out)
    return int(match.group(1)) if match else None


def _clean_markup(line: str) -> str:
    return re.sub(r"^(#{1,4} |@ |~ |- )", "", line).replace("**", "")


def _is_acronym_or_camel(word: str) -> bool:
    return any(c.isupper() for c in word[1:])


def _novel_terms(text: str, vocab: set[str], allowed: set[str]) -> list[str]:
    """Capitalized terms that no approved source has ever used: likely invented skills."""
    novel = []
    for sentence in SENTENCE.split(text):
        words = WORD.findall(sentence)
        for index, word in enumerate(words):
            # The first word of a sentence is capitalized anyway, so there only an acronym or CamelCase stands out.
            if not (_is_acronym_or_camel(word) or (index and word[0].isupper())):
                continue
            low = word.lower().strip("+")
            if low in vocab or low in allowed or low in ORDINARY_CAPS:
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
    wanted = _posting_terms(posting) - vocab - allowed - ORDINARY_CAPS - {word.lower().strip("+") for word in already}
    borrowed = []
    for word in WORD.findall(text):
        if word[0].isupper() and word.lower().strip("+") in wanted and word not in borrowed:
            borrowed.append(word)
    return borrowed


def _disclaimed(before: str, after: str, disclaimers: list) -> bool:
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
    return bool(denials) and ATTRIBUTED.search(before) is not None


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
        if "LATIN" in scripts and len(scripts) > 1 and word not in mixed and not _lookalike(unicodedata.normalize("NFKC", word)):
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


def _fold_lookalikes(match: re.Match) -> str:
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


def _unsupported(text: str, guard: dict, label: str) -> tuple[list[str], list[str]]:
    """Errors for unsupported claims, and the exact words of the claims that were properly disclaimed."""
    errors, disclaimed = [], []
    for sentence in SENTENCE.split(text):
        claimed = False
        # Every mention counts, not just the first: "I have not worked under X, but led X audits" claims X.
        for match in (m for pattern in guard["unsupported"] for m in re.finditer(pattern, sentence, re.I)):
            if _disclaimed(sentence[:match.start()], sentence[match.end():], guard["disclaimers"]):
                disclaimed.append(match.group(0))
            else:
                claimed = True
        if claimed:
            errors.append(f"{label} makes an unsupported claim: {sentence.strip()[:140]!r}")
    return errors, disclaimed


def check_text(
    text: str, kind: str, cfg: dict, sources: str, company: str = "", title: str = "", contact_line: str | None = None,
    posting: str = "",
) -> tuple[list[str], list[str]]:
    """Check one document's Markdown. kind is 'resume' or 'letter'. posting is the job's text, when there is one."""
    errors, warnings = [], []
    guard = cfg["guard"]
    label = "Resume" if kind == "resume" else "Cover letter"
    errors += _disguises(text, label)
    # The draft and everything it's compared with are read the same way.
    text, sources, company, title, posting = (_matchable(part) for part in (text, sources, company, title, posting))
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Nothing from the do-not-use list, anywhere.
    for pattern in guard["forbidden"]:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(f"{label} uses a confidential term: {match.group(0)!r}")

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
    body = DATE_LINE.sub(" ", body)
    # A confidential term or a disclaimed claim has been dealt with above, so its own words aren't judged again.
    for pattern in guard["forbidden"]:
        body = re.sub(pattern, " ", body, flags=re.I)
    for span in disclaimed:
        body = body.replace(span, " ")

    for line in lines:
        if line == contact_line:
            continue
        if URLISH.search(line):
            errors.append(f"{label} contains a link or domain that isn't yours: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"{label} has an unfilled placeholder: {placeholder.group(0)!r}")

    # Numbers stay as measured.
    vocab = _vocabulary(sources)
    errors += _number_errors(label, body, sources, vocab, "not in the fact bank")

    # Specialist terms need a source. A resume can't name a skill you've never claimed, and a title
    # from a job board is no source: on a resume only the exact title was set aside above. A letter
    # names the role in its own words, and its terms only ever warn.
    # A placeholder is reported above, so "[X]" isn't named again as a term. One line at a time, as above, so a
    # bracket left open on one line and closed on a later one can't hide the words between from this check.
    plain = "\n".join(_clean_markup(PLACEHOLDER.sub(" ", row).strip()) for row in body.splitlines())
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


def check_brief(text: str, cfg: dict, sources: str, company: str = "", title: str = "", posting: str = "") -> tuple[list[str], list[str]]:
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

    for pattern in guard["forbidden"]:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(f"Brief uses a confidential term: {match.group(0)!r}")

    unsupported, disclaimed = _unsupported(text, guard, "Brief")
    errors += unsupported

    body = _set_aside(_set_aside(text, company), title)
    for span in disclaimed:
        body = body.replace(span, " ")
    for line in (line.strip() for line in body.splitlines()):
        if URLISH.search(line):
            errors.append(f"Brief contains a link or web address: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"Brief has an unfilled placeholder: {placeholder.group(0)!r}")

    known = sources + "\n" + posting
    errors += _number_errors("Brief", body, known, _vocabulary(known), "that aren't in the fact bank or the posting")

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


def check_resume_structure(text: str, cfg: dict) -> tuple[list[str], list[str]]:
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
    for needed in ("## Experience", "## Education"):
        if not any(row.strip().startswith(needed) for row in text.splitlines()):
            errors.append(f"Resume is missing the {needed[3:]} section.")
    for item in cfg["guard"].get("expected_on_resume", []):
        if item["text"] not in text:
            warnings.append(f"{item['label']} isn't on this resume.")
    return errors, warnings


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


def fingerprints(folder: Path) -> dict[str, str]:
    """A hash of each file a passing check covered: the two sources and the documents built from them."""
    covered = [p for p in sorted(folder.iterdir()) if p.name in ("resume.md", "cover-letter.md") or p.suffix in (".pdf", ".docx")]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in covered}


GUARD_KEY = "search.toml [guard]"


def source_fingerprints(cfg: dict) -> dict[str, str]:
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


def sources_changed(cfg: dict, recorded: dict | None) -> list[str]:
    """Which sources or rules changed after a pass. A pass from before these were recorded has nothing to compare."""
    if not recorded:
        return []
    now = source_fingerprints(cfg)
    return sorted(name for name in set(recorded) | set(now) if recorded.get(name) != now.get(name))


def changed_since(folder: Path, checked: dict) -> list[str]:
    """Which of the files that passed have changed or gone since, plus a cover letter added afterwards."""
    names = set(checked) | {"cover-letter.md"}
    now: dict[str, str | None] = {}
    for name in names:
        try:
            now[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        except OSError:
            now[name] = None
    return sorted(name for name in names if checked.get(name) != now[name])


def not_covered(folder: Path, cfg: dict, result: dict | str | None) -> str:
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


def keyword_overlap(resume: str, description: str, cfg: dict) -> dict:
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


def check_application(folder: Path, cfg: dict, company: str, title: str, description: str = "") -> dict:
    """Run every gate over an application folder."""
    errors, warnings = [], []
    sources = _read_sources(cfg)
    warnings += [f"approved_sources under [guard] in profile/search.toml names {rel!r}, which isn't in your workspace, "
                 "so nothing in it counts as a source." for rel in missing_sources(cfg)]
    posting = description or saved_posting(folder)

    resume_path = folder / "resume.md"
    if not resume_path.exists():
        return {"ok": False, "errors": ["resume.md is missing."], "warnings": [], "overlap": None}
    resume = resume_path.read_text(encoding="utf-8")
    new_errors, new_warnings = check_text(resume, "resume", cfg, sources, company, title, posting=posting)
    errors += new_errors
    warnings += new_warnings
    new_errors, new_warnings = check_resume_structure(resume, cfg)
    errors += new_errors
    warnings += new_warnings

    letter_path = folder / "cover-letter.md"
    if letter_path.exists():
        new_errors, new_warnings = check_text(
            letter_path.read_text(encoding="utf-8"), "letter", cfg, sources, company, title, posting=posting)
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
    for name, version in drafter.items():
        if version != DRAFTER_VERSION:
            warnings.append(f"{name} was built by drafter {version}; the current drafter is {DRAFTER_VERSION}. Rebuild it to get the current format.")

    overlap = keyword_overlap(resume, description, cfg) if description else None
    return {"ok": not errors, "errors": errors, "warnings": warnings, "overlap": overlap, "drafter": drafter}


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


def polish_requests(report: dict, letter: bool = True) -> list[str]:
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


def reads_as_copied(overlap: dict | None) -> str:
    """A sentence saying the resume uses too many of the posting's skill terms, or "" when it doesn't."""
    overlap = overlap or {}
    pct, covered = overlap.get("pct"), overlap.get("covered") or []
    if pct is not None and pct > OVERLAP_MAX and len(covered) + len(overlap.get("missing") or []) >= OVERLAP_MIN_TERMS:
        return f"The resume uses {pct}% of the posting's skill terms, which reads as copied from it."
    return ""
