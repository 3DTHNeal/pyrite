"""The fact checker: deterministic gates between a tailored draft and "ready to apply".

Errors block the draft. Warnings are shown on the dashboard for you to read.
The rules restate profile/facts.md: only claim what's there, keep numbers as
measured, never use anything on the do-not-use list.

The checks that know nothing about resumes are in the `assay` package beside this one. This module adds what's
particular to Pyrite: the workspace's files and [guard] rules, a resume's name line, contact line and roles, a letter's
date and requisition number, page limits, and which drafter built a document.
"""
import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from assay import claims, seal
from assay.factbank import source_body, unsupported_claims, without_contact
from assay.links import link, own_links
from assay.names import PLAIN_NAME, confidential, flexible, term_pattern, widen
from assay.names import unguarded_terms as _unguarded_terms
from assay.numbers import NUMBER, number_errors
from assay.terms import CALENDAR_WORDS, WORD, borrowed_terms, novel_terms, vocabulary
from assay.text import BLANK, PLACEHOLDER, disguises, matchable, set_aside

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
EM_DASH = "—"
LETTER_WORDS_MAX = 350  # a letter longer than this is the one readers say they stop reading
# Titles that open a line as a claim: "Head of firmware for the company." The first word of a sentence is otherwise
# taken as capitalized only because it comes first.
TITLE_WORDS = {"director", "head", "chief", "president", "vice"}
# A line shaped like a role heading, "Title | place | dates", printed as plain or bold text instead of as a heading.
ROLE_LINE = re.compile(r"^[^#@|][^|]*\|[^|]*\|.*\b(?:19|20)\d\d\b")
# Capitalized words a resume or letter uses anyway, which name no skill.
ORDINARY_CAPS = CALENDAR_WORDS | {
    "i", "dear", "sincerely", "hiring", "manager", "team", "summary",
    "experience", "skills", "education", "patent", "patents", "certifications", "core", "selected", "scope",
    "leadership", "ai", "us", "u.s", "ml", "and", "the", "of",
}


def unguarded_terms(facts: str, forbidden: list[str], own_name: str = "") -> list[str]:
    """Capitalized terms under "Do not use" in a fact bank that no pattern in [guard] forbidden matches. See
    `assay.names.unguarded_terms`."""
    return _unguarded_terms(facts, forbidden, own_name, ORDINARY_CAPS)


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
    return ([(flexible(pattern), "") for pattern in cfg.get("guard", {}).get("forbidden", [])]
            + [(flexible(term) if PLAIN_NAME.fullmatch(term) else widen(pattern), rel)
               for term, pattern, rel in listed_terms(cfg, read)[0]])


def with_listed(guard: dict[str, Any], cfg: dict[str, Any], read: Callable[[str], str] | None = None) -> dict[str, Any]:
    """[guard] with a pattern added to forbidden for each name listed under "Do not use", as the assay reads it."""
    return {**guard, "forbidden": [pattern for pattern, _where in blocked_patterns({**cfg, "guard": guard}, read)]}


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


def _clean_markup(line: str) -> str:
    return re.sub(r"^(#{1,4} |@ |~ |- )", "", line).replace("**", "")


def _novel_terms(text: str, vocab: set[str], allowed: set[str]) -> list[str]:
    """Capitalized terms that no approved source has ever used: likely invented skills."""
    return novel_terms(text, vocab | allowed | ORDINARY_CAPS, TITLE_WORDS)


def _borrowed_terms(text: str, posting: str, vocab: set[str], allowed: set[str], already: list[str]) -> list[str]:
    """Posting terms the draft uses capitalized, where the capitals check alone can't tell a name from a verb."""
    return borrowed_terms(text, posting, vocab | allowed | ORDINARY_CAPS, already)


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
        ident = matchable(ident).strip()
        body = re.sub(rf"(?<!\w){re.escape(ident)}(?!\w)", " ", body, flags=re.I)
        digits = re.sub(r"\D", "", ident)
        if digits != ident and len(digits) >= 4:
            body = re.sub(rf"\b{REQUISITION_LABEL}{re.escape(digits)}(?!\w)", " ", body, flags=re.I)
    return body


def explain(sentence: str, guard: dict[str, Any]) -> dict[str, Any]:
    """How the confidential and unsupported checks read one piece of text, for the Profile tab's test box. See
    `assay.claims.explain`: a sentence that passes there passes in a draft."""
    return claims.explain(sentence, guard.get("forbidden", []), guard.get("unsupported", []), guard.get("disclaimers", []))


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
    errors += disguises(text, label)
    blank = next((row.strip() for row in text.splitlines() if BLANK.search(row)), None)
    if blank:
        errors.append(f"{label} has an unfilled placeholder: {blank[:120]!r}")
    # The draft and everything it's compared with are read the same way.
    text, sources, company, title, posting = (matchable(part) for part in (text, sources, company, title, posting))
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    # Nothing from the do-not-use list, anywhere.
    for pattern, where in blocked:
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(confidential(label, match, where))

    # Unsupported claims, unless the sentence disclaims them before naming them.
    unsupported, disclaimed = claims.unsupported(text, guard["unsupported"], guard["disclaimers"], label)
    errors += unsupported

    if contact_line is None:
        contact_line = next((row for row in sources.splitlines() if row.startswith("@ ")), None)
    contact_line = matchable(contact_line).strip() if contact_line else None
    if contact_line and contact_line not in lines:
        errors.append(f"{label} contact line doesn't match the approved one.")
    name_line = f"# {cfg['candidate']['name']}"
    if not any(line == matchable(name_line).strip() for line in lines):
        errors.append(f"{label} doesn't open with '{name_line}'.")

    # Only the approved contact line itself is exempt from what follows. Any other line is checked, whatever it starts with.
    body = "\n".join(line for line in text.splitlines() if line.strip() != contact_line)
    # The company and role are the one thing that's meant to change.
    body = set_aside(set_aside(body, company), title)
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

    own = own_links(sources)
    for line in lines:
        if line == contact_line:
            continue
        if link(line, own):
            errors.append(f"{label} contains a link or domain that isn't yours: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"{label} has an unfilled placeholder: {placeholder.group(0)!r}")

    # Numbers stay as measured. Your phone number and zip code measure nothing.
    vocab = vocabulary(sources)
    errors += number_errors(label, body, without_contact(sources), "not in the fact bank")

    # Specialist terms need a source. A resume can't name a skill you've never claimed, and a title
    # from a job board is no source: on a resume only the exact title was set aside above. A letter
    # names the role in its own words, and its terms only ever warn.
    # A placeholder is reported above, so "[X]" isn't named again as a term. One line at a time, as above, so a
    # bracket left open on one line and closed on a later one can't hide the words between from this check.
    # A number is judged above with its scale, so the K of 1.4K isn't read again as a term of its own.
    plain = "\n".join(_clean_markup(NUMBER.sub(" ", PLACEHOLDER.sub(" ", row)).strip()) for row in body.splitlines())
    allowed = vocabulary(company if kind == "resume" else f"{company} {title}")
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
    errors += disguises(text, "Brief")
    text, sources, company, title, posting = (matchable(part) for part in (text, sources, company, title, posting))

    for pattern, where in blocked_patterns(cfg):
        match = re.search(pattern, text, re.I)
        if match:
            errors.append(confidential("Brief", match, where))

    unsupported, disclaimed = claims.unsupported(text, guard["unsupported"], guard["disclaimers"], "Brief")
    errors += unsupported

    body = set_aside(set_aside(text, company), title)
    for span in disclaimed:
        body = body.replace(span, " ")
    own = own_links(sources)
    for line in (line.strip() for line in body.splitlines()):
        if link(line, own):
            errors.append(f"Brief contains a link or web address: {line[:120]!r}")
        placeholder = PLACEHOLDER.search(line)
        if placeholder:
            errors.append(f"Brief has an unfilled placeholder: {placeholder.group(0)!r}")

    known = without_contact(sources) + "\n" + posting
    errors += number_errors("Brief", body, known, "that aren't in the fact bank or the posting")

    # A term from the posting alone is a requirement, not something you can claim.
    plain = "\n".join(_clean_markup(line) for line in body.splitlines())
    allowed = vocabulary(f"{company} {title}") | {w.lower() for w in guard.get("ordinary_words", [])}
    unclaimed = _novel_terms(plain, vocabulary(sources), allowed)
    asked_for = vocabulary(posting)
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
    return {p.name: seal.digest(p.read_bytes()) for p in covered}


GUARD_KEY = "search.toml [guard]"


def source_fingerprints(cfg: dict[str, Any]) -> dict[str, str]:
    """A hash of everything a pass was judged against: each approved source, the heading source and the [guard] rules.
    Taking a fact out of the bank, or a new pattern in [guard], means an earlier pass no longer says the draft is true."""
    guard = cfg["guard"]
    prints = {}
    for rel in dict.fromkeys([*guard["approved_sources"], guard["heading_source"]]):
        prints[rel] = seal.file_digest(ROOT / rel) or "missing"
    prints[GUARD_KEY] = seal.value_digest(guard)
    return prints


def sources_changed(cfg: dict[str, Any], recorded: dict[str, Any] | None) -> list[str]:
    """Which sources or rules changed after a pass. A pass from before these were recorded has nothing to compare."""
    if not recorded:
        return []
    now = source_fingerprints(cfg)
    return seal.changed(recorded, now)


def changed_since(folder: Path, checked: dict[str, Any]) -> list[str]:
    """Which of the files that passed have changed or gone since, plus a cover letter or a built document added
    afterwards. A pass recorded before the paste-box .txt files were covered says nothing about them."""
    covers_txt = any(name.endswith(".txt") for name in checked)
    added = {p.name for p in folder.iterdir() if p.is_file() and _built(p) and (covers_txt or p.suffix != ".txt")} \
        if folder.is_dir() else set()
    names = set(checked) | {"cover-letter.md"} | added
    now = {name: seal.file_digest(folder / name) for name in names}
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
