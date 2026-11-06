"""The fact checker: deterministic gates between a tailored draft and "ready to apply".

Errors block the draft. Warnings are shown on the dashboard for you to read.
The rules restate profile/facts.md: only claim what's there, keep numbers as
measured, never use anything on the do-not-use list.
"""
import hashlib
import re
import subprocess
from pathlib import Path

from .store import ROOT

DATE_LINE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b"
)
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
PERCENT = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*%")
URLISH = re.compile(r"https?://|www\.|\b[\w-]+\.(?:com|io|ai|org|net|co|dev)\b", re.I)
PLACEHOLDER = re.compile(r"\[[^\]]*\]|\{\{|\bTODO\b|\bTBD\b|\bXXX\b|<[a-z_ ]+>")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:[-/.][A-Za-z0-9+#]+)*\+*")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n")
# Sections of a fact bank that list what must not be claimed. Their words and numbers approve nothing.
EXCLUDED_SECTION = re.compile(r"## (do not use|unsupported)", re.I)
# A negative only disclaims what follows it in the same clause. "Not only" is no negative at all.
NOT_A_NEGATIVE = re.compile(r"\b(?:not|no)\s+(?:only|just|merely|less|fewer)\b", re.I)
CLAUSE_BREAK = re.compile(r";|\b(?:but|however|although|though|whereas)\b", re.I)
FIRST_PERSON_DENIAL = re.compile(
    r"\bI\s+(?:have|had|do|did|am|was|would|could|can|will)\s+(?:not|never)\b|\bI\s+have\s+yet\s+to\b|\bI\s+never\b"
    r"|\bI\s+(?:haven|hadn|don|didn|wasn|couldn|wouldn|won|can)['’]t\b|\bI['’]ve\s+(?:not|never)\b"
)
# Numbers written as words slip past a check on digits. One to ten are too common in prose to police.
NUMBER_WORD = re.compile(
    r"\b(?:eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?|billions?|dozens?)\b",
    re.I,
)
ORDINARY_CAPS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday", "friday",
    "i", "dear", "sincerely", "hiring", "manager", "team", "summary",
    "experience", "skills", "education", "patent", "certifications", "core", "selected",
    "leadership", "ai", "us", "u.s", "ml", "and", "the", "of",
}


def claimable(text: str) -> str:
    """A source without the sections that list what must not be claimed."""
    sections = re.split(r"(?m)^(?=## )", text)
    return "".join(section for section in sections if not EXCLUDED_SECTION.match(section))


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


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(",") for m in NUMBER.finditer(text)}


def _percents(text: str) -> set[str]:
    return {m.group(1).replace(",", "") for m in PERCENT.finditer(text)}


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
    if any(re.search(pattern, clause, re.I) for pattern in disclaimers):
        return True
    return FIRST_PERSON_DENIAL.search(after) is not None


def _unsupported(text: str, guard: dict, label: str) -> tuple[list[str], list[str]]:
    """Errors for unsupported claims, and the exact words of the claims that were properly disclaimed."""
    errors, disclaimed = [], []
    for sentence in SENTENCE.split(text):
        for pattern in guard["unsupported"]:
            match = re.search(pattern, sentence, re.I)
            if not match:
                continue
            if _disclaimed(sentence[:match.start()], sentence[match.end():], guard["disclaimers"]):
                disclaimed.append(match.group(0))
                continue
            errors.append(f"{label} makes an unsupported claim: {sentence.strip()[:140]!r}")
            break
    return errors, disclaimed


def check_text(
    text: str, kind: str, cfg: dict, sources: str, company: str = "", title: str = "", contact_line: str | None = None,
    posting: str = "",
) -> tuple[list[str], list[str]]:
    """Check one document's Markdown. kind is 'resume' or 'letter'. posting is the job's text, when there is one."""
    errors, warnings = [], []
    guard = cfg["guard"]
    label = "Resume" if kind == "resume" else "Cover letter"
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
        contact_line = next((l for l in sources.splitlines() if l.startswith("@ ")), None)
    contact_line = contact_line.strip() if contact_line else None
    if contact_line and contact_line not in lines:
        errors.append(f"{label} contact line doesn't match the approved one.")
    name_line = f"# {cfg['candidate']['name']}"
    if not any(line == name_line for line in lines):
        errors.append(f"{label} doesn't open with '{name_line}'.")

    # Only the approved contact line itself is exempt from what follows. Any other line is checked, whatever it starts with.
    body = "\n".join(line for line in text.splitlines() if line.strip() != contact_line)
    # The company and role are the one thing that's meant to change.
    if company:
        body = body.replace(company, " ")
    if title:
        body = body.replace(title, " ")
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
    known_numbers = _numbers(sources)
    known_percents = _percents(sources)
    invented_pct = sorted(_percents(body) - known_percents)
    if invented_pct:
        errors.append(f"{label} has percentages not in the fact bank: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(_numbers(body) - known_numbers - set(invented_pct))
    if invented:
        errors.append(f"{label} has numbers not in the fact bank: {', '.join(invented)}")
    spelled = sorted({match.group(0).lower() for match in NUMBER_WORD.finditer(body)} - vocab)
    if spelled:
        errors.append(f"{label} spells out numbers that aren't in the fact bank: {', '.join(spelled)}. Write numbers as digits, as measured.")

    # Specialist terms need a source. A resume can't name a skill you've never claimed, and a title
    # from a job board is no source: on a resume only the exact title was set aside above. A letter
    # names the role in its own words, and its terms only ever warn.
    plain = "\n".join(_clean_markup(l.strip()) for l in body.splitlines())
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
    return errors, warnings


def check_brief(text: str, cfg: dict, sources: str, company: str = "", title: str = "", posting: str = "") -> tuple[list[str], list[str]]:
    """Check an interview prep brief.

    It's private notes, so it has no name or contact line to match, and it may repeat what the posting
    says. What it has you say still has to be true: nothing confidential, no unsupported claim, and no
    number that neither the fact bank nor the posting holds. A link is blocked too, since a posting
    could try to have one passed along to you.
    """
    errors, warnings = [], []
    guard = cfg["guard"]

    for pattern in guard["forbidden"]:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(f"Brief uses a confidential term: {match.group(0)!r}")

    unsupported, disclaimed = _unsupported(text, guard, "Brief")
    errors += unsupported

    body = text.replace(company, " ") if company else text
    if title:
        body = body.replace(title, " ")
    for span in disclaimed:
        body = body.replace(span, " ")
    for line in (line.strip() for line in body.splitlines()):
        if URLISH.search(line):
            errors.append(f"Brief contains a link or web address: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"Brief has an unfilled placeholder: {placeholder.group(0)!r}")

    known = sources + "\n" + posting
    invented_pct = sorted(_percents(body) - _percents(known))
    if invented_pct:
        errors.append(f"Brief has percentages that aren't in the fact bank or the posting: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(_numbers(body) - _numbers(known) - set(invented_pct))
    if invented:
        errors.append(f"Brief has numbers that aren't in the fact bank or the posting: {', '.join(invented)}")

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
    errors, warnings = [], []
    reference = (ROOT / cfg["guard"]["heading_source"]).read_text(encoding="utf-8")
    # Stripped first, as the builder does: an indented heading still prints as a heading.
    headings = lambda doc: {l.strip() for l in doc.splitlines() if l.strip().startswith(("### ", "#### "))}
    approved, present = headings(reference), headings(text)
    for heading in sorted(present - approved):
        errors.append(f"Employer, title or dates differ from your record: {heading!r}")
    for heading in sorted(approved - present):
        warnings.append(f"Left out of the timeline: {heading.lstrip('# ')}")
    for needed in ("## Experience", "## Education"):
        if not any(l.strip().startswith(needed) for l in text.splitlines()):
            errors.append(f"Resume is missing the {needed[3:]} section.")
    for item in cfg["guard"].get("expected_on_resume", []):
        if item["text"] not in text:
            warnings.append(f"{item['label']} isn't on this resume.")
    return errors, warnings


def fingerprints(folder: Path) -> dict[str, str]:
    """A hash of each file a passing check covered: the two sources and the documents built from them."""
    covered = [p for p in sorted(folder.iterdir()) if p.name in ("resume.md", "cover-letter.md") or p.suffix in (".pdf", ".docx")]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in covered}


def changed_since(folder: Path, checked: dict) -> list[str]:
    """Which of the files that passed have changed or gone since, plus a cover letter added afterwards."""
    names = set(checked) | {"cover-letter.md"}
    now = {}
    for name in names:
        try:
            now[name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
        except OSError:
            now[name] = None
    return sorted(name for name in names if checked.get(name) != now[name])


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

    overlap = keyword_overlap(resume, description, cfg) if description else None
    return {"ok": not errors, "errors": errors, "warnings": warnings, "overlap": overlap}
