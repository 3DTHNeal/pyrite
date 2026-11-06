"""The fact checker: deterministic gates between a tailored draft and "ready to apply".

Errors block the draft. Warnings are shown on the dashboard for you to read.
The rules restate profile/facts.md: only claim what's there, keep numbers as
measured, never use anything on the do-not-use list.
"""
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
ORDINARY_CAPS = {
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
    "sept", "oct", "nov", "dec", "monday", "tuesday", "wednesday", "thursday", "friday",
    "i", "dear", "sincerely", "hiring", "manager", "team", "summary",
    "experience", "skills", "education", "patent", "certifications", "core", "selected",
    "leadership", "ai", "us", "u.s", "ml", "and", "the", "of",
}


def _read_sources(cfg: dict) -> str:
    parts = []
    for rel in cfg["guard"]["approved_sources"]:
        path = ROOT / rel
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


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


def _novel_terms(text: str, vocab: set[str], allowed: set[str]) -> list[str]:
    """Capitalized terms mid-sentence that no approved source has ever used: likely invented skills."""
    novel = []
    for sentence in SENTENCE.split(text):
        words = WORD.findall(sentence)
        for index, word in enumerate(words):
            # The first word of a sentence, or of a list item after a colon, is capitalized anyway.
            if index == 0:
                continue
            is_acronym_or_camel = any(c.isupper() for c in word[1:])
            if not (word[0].isupper() or is_acronym_or_camel):
                continue
            low = word.lower().strip("+")
            if low in vocab or low in allowed or low in ORDINARY_CAPS:
                continue
            if word not in novel:
                novel.append(word)
    return novel


def check_text(
    text: str, kind: str, cfg: dict, sources: str, company: str = "", title: str = "", contact_line: str | None = None,
) -> tuple[list[str], list[str]]:
    """Check one document's Markdown. kind is 'resume' or 'letter'."""
    errors, warnings = [], []
    guard = cfg["guard"]
    label = "Resume" if kind == "resume" else "Cover letter"
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Nothing from the do-not-use list, anywhere.
    for pattern in guard["forbidden"]:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(f"{label} uses a confidential term: {match.group(0)!r}")

    # Unsupported claims, unless the sentence is plainly disclaiming them.
    for sentence in SENTENCE.split(text):
        for pattern in guard["unsupported"]:
            match = re.search(pattern, sentence, re.I)
            if match and not any(re.search(d, sentence, re.I) for d in guard["disclaimers"]):
                errors.append(f"{label} makes an unsupported claim: {sentence.strip()[:140]!r}")
                break

    # The company and role are the one thing that's meant to change.
    body = text.replace(company, " ") if company else text
    if title:
        body = body.replace(title, " ")
    body = DATE_LINE.sub(" ", body)

    if contact_line is None:
        contact_line = next((l for l in sources.splitlines() if l.startswith("@ ")), None)
    if contact_line and contact_line not in lines:
        errors.append(f"{label} contact line doesn't match the approved one.")
    name_line = f"# {cfg['candidate']['name']}"
    if not any(line == name_line for line in lines):
        errors.append(f"{label} doesn't open with '{name_line}'.")

    for line in lines:
        if line.startswith("@ "):
            continue
        if URLISH.search(line):
            errors.append(f"{label} contains a link or domain that isn't yours: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"{label} has an unfilled placeholder: {placeholder.group(0)!r}")

    body_no_contact = "\n".join(l for l in body.splitlines() if not l.strip().startswith("@ "))

    # Numbers stay as measured.
    known_numbers = _numbers(sources)
    known_percents = _percents(sources)
    invented_pct = sorted(_percents(body_no_contact) - known_percents)
    if invented_pct:
        errors.append(f"{label} has percentages not in the fact bank: {', '.join(p + '%' for p in invented_pct)}")
    invented = sorted(_numbers(body_no_contact) - known_numbers - set(invented_pct))
    if invented:
        errors.append(f"{label} has numbers not in the fact bank: {', '.join(invented)}")

    # Specialist terms need a source. A resume can't name a skill you've never claimed.
    plain = "\n".join(_clean_markup(l) for l in body_no_contact.splitlines())
    allowed = _vocabulary(f"{company} {title}") | {w.lower() for w in guard.get("ordinary_words", [])}
    novel = _novel_terms(plain, _vocabulary(sources), allowed)
    if novel:
        message = f"{label} names terms not in your approved sources: {', '.join(novel[:15])}"
        if kind == "resume":
            errors.append(message + ". Remove them, or add them to profile/approved-terms.txt if they're true.")
        else:
            warnings.append(message)
    return errors, warnings


def check_resume_structure(text: str, cfg: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    reference = (ROOT / cfg["guard"]["heading_source"]).read_text(encoding="utf-8")
    approved = {l.strip() for l in reference.splitlines() if l.startswith(("### ", "#### "))}
    present = {l.strip() for l in text.splitlines() if l.startswith(("### ", "#### "))}
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

    resume_path = folder / "resume.md"
    if not resume_path.exists():
        return {"ok": False, "errors": ["resume.md is missing."], "warnings": [], "overlap": None}
    resume = resume_path.read_text(encoding="utf-8")
    new_errors, new_warnings = check_text(resume, "resume", cfg, sources, company, title)
    errors += new_errors
    warnings += new_warnings
    new_errors, new_warnings = check_resume_structure(resume, cfg)
    errors += new_errors
    warnings += new_warnings

    letter_path = folder / "cover-letter.md"
    if letter_path.exists():
        new_errors, new_warnings = check_text(letter_path.read_text(encoding="utf-8"), "letter", cfg, sources, company, title)
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
