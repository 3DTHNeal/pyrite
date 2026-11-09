"""A fill sheet for one application: the workspace's Workday paste sheet, with that job's tailored role text.

Workday takes applications only through its form, and its resume parse fills the work history badly, so a
workspace keeps `profile/workday-paste.md` with every field typed out once. This merges that sheet with
the application's `resume.md`, so the role descriptions typed into Workday are the tailored ones, and it
lists what still has to be answered by hand for this job. Nothing here submits anything: the candidate
signs in, fills each page from the sheet, reviews it and clicks Submit.

The paste sheet is the candidate's own file. All this needs from it is one section per role headed
`### Work experience N`, holding a table with `Job title` and `Company` rows and one fenced ```text block
with the role description. A field whose value says "per application" in italics is listed as one to
answer by hand each time; any other italic "ask" is a blank on the sheet itself.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import store

PASTE_SHEET = Path("profile") / "workday-paste.md"
SHEET = "fill-sheet.md"
# The same sheet as data, for `pyrite autofill`, which types it into Workday while the candidate watches.
SHEET_JSON = "fill-sheet.json"
# The role text comes from resume.md, so a sheet made from a draft the assay doesn't vouch for says so first.
NOT_PASSED = "This role text hasn't passed the assay."
NOT_LOOKED_UP = "Nothing looked up a passing check for this folder."
SHEET_PROBLEM = f"{PASTE_SHEET.as_posix()} has a mistake."
BULLET = "•"

_ROLE_HEADING = re.compile(r"^###\s+work experience\b", re.IGNORECASE)
_TABLE_ROW = re.compile(r"^\|\s*(?P<field>[^|]+?)\s*\|\s*(?P<value>.*?)\s*\|\s*$")
_FENCE_OPEN = re.compile(r"^```")
_ITALIC_ASK = re.compile(r"\*[^*]*\bask\b[^*]*\*", re.IGNORECASE)
_PER_APPLICATION = re.compile(r"per application", re.IGNORECASE)
_TITLE_LINE = re.compile(r"^#\s+(?P<company>[^:]+):\s*(?P<title>.+?)\s*$")
_LINK_LINE = re.compile(r"^-\s+\*\*(Posting|Link):\*\*\s*(?P<url>\S+)")
# Lines in notes.md that bear on the form's own questions rather than on the fit.
_FORM_NOTE = re.compile(
    r"\bsalary\b|\bpay\b|compensation|\$\s?\d|\breferr(al|ed|er)s?\b|\brecruiter\b|hiring manager|job id|\breq(uisition)?\b|how did you hear",
    re.IGNORECASE,
)


# A built cover letter is named `<Name>_Cover_Letter_<Company>`. Matched as that token, not as any "letter", since
# a company called Letterbox or a surname like Letterman would otherwise make the resume a cover letter.
_LETTER_FILE = re.compile(r"(?:^|_)cover[_ -]?letter(?:_|$)", re.IGNORECASE)


class SheetError(ValueError):
    """The paste sheet can't be made into a fill sheet as it is, with a message that says what to fix."""


def is_letter(stem: str) -> bool:
    """Whether a file name (without its extension) is a cover letter's."""
    return bool(_LETTER_FILE.search(stem))


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", "")).strip().lower()


def _same_company(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a in b or b in a)


def paste_roles(lines: list[str]) -> list[dict]:
    """Each work-experience section of the paste sheet: its title, company and the line span of its text block."""
    roles = []
    i = 0
    while i < len(lines):
        if not _ROLE_HEADING.match(lines[i]):
            i += 1
            continue
        fields: dict[str, str] = {}
        fence: tuple[int, int] | None = None
        j = i + 1
        while j < len(lines) and not lines[j].startswith("#"):
            row = _TABLE_ROW.match(lines[j])
            if row and not set(row["field"]) <= set("-: "):
                fields.setdefault(row["field"], row["value"])
            elif fence is None and _FENCE_OPEN.match(lines[j]):
                start = j + 1
                end = start
                # A block never closed ends at the next heading, rather than taking the rest of the sheet with it.
                while end < len(lines) and not _FENCE_OPEN.match(lines[end]) and not lines[end].startswith("#"):
                    end += 1
                fence = (start, end)
                j = end - 1 if end < len(lines) and lines[end].startswith("#") else end
            j += 1
        roles.append({"title": fields.get("Job title", ""), "company": fields.get("Company", ""), "fence": fence, "line": i})
        i = j
    return roles


def resume_roles(text: str) -> list[dict]:
    """Each `####` role in a resume.md, with its bullets as the plain text a description box takes."""
    roles: list[dict] = []
    company = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#### "):
            title = line[5:].split(" | ")[0].strip()
            roles.append({"title": title, "company": company, "lines": []})
        elif line.startswith("### "):
            company = line[4:].split(" | ")[0].strip()
        elif line.startswith("#"):
            company = ""
        elif roles and company and line.startswith("- "):
            roles[-1]["lines"].append(f"{BULLET} {line[2:].replace('**', '')}")
        elif roles and company and line.startswith("~ "):
            roles[-1]["lines"].append(line[2:].replace("**", ""))
    return [r for r in roles if r["lines"]]


def _find(role: dict, candidates: list[dict]) -> dict | None:
    for other in candidates:
        if _norm(other["title"]) == _norm(role["title"]) and _same_company(other["company"], role["company"]):
            return other
    return None


def close_fences(lines: list[str]) -> tuple[list[str], list[str]]:
    """The sheet's lines with every ``` block closed, and what was wrong with each one that wasn't.

    A block missing its closing ``` would otherwise run on through every section after it, so a role's description
    would hold the next role's table and the questions would vanish. Role text never holds a Markdown heading, so a
    block still open at the next heading ends there.
    """
    out: list[str] = []
    problems: list[str] = []
    opened = 0
    section = ""
    for number, line in enumerate(lines, 1):
        if opened and line.startswith("#"):
            out.append("```")
            problems.append(f"The ``` block at line {opened} ({section or 'the top'}) isn't closed before {line.strip()!r}. "
                            "Close it with ``` on a line of its own.")
            opened = 0
        if line.startswith("```"):
            opened = 0 if opened else number
        elif not opened and line.startswith("#"):
            section = line.lstrip("#").strip()
        out.append(line)
    if opened:
        out.append("```")
        problems.append(f"The ``` block at line {opened} ({section or 'the top'}) is never closed. Close it with ``` on a line of its own.")
    return out, problems


def merge(paste: str, resume: str) -> tuple[list[str], dict]:
    """The paste sheet's lines with each matched role's text replaced by the resume's, and what matched."""
    lines, problems = close_fences(paste.splitlines())
    sheet = paste_roles(lines)
    tailored = resume_roles(resume)
    report: dict[str, list] = {"tailored": [], "kept": [], "unmatched": []}
    label = lambda r: f"{r['title']} at {r['company']}".strip()
    # Replace from the bottom up so earlier spans stay valid.
    for role in sorted(sheet, key=lambda r: r["line"], reverse=True):
        match = _find(role, tailored)
        if match and role["fence"]:
            start, end = role["fence"]
            lines[start:end] = match["lines"]
            lines.insert(start + len(match["lines"]) + 1, "*Tailored for this application, from its resume.md.*")
            report["tailored"].append(label(role))
        else:
            if role["fence"]:
                lines.insert(role["fence"][1] + 1, "*Not in this application's resume, so the standard text stays.*")
            report["kept"].append(label(role))
    for role in tailored:
        if not _find(role, sheet):
            report["unmatched"].append(label(role))
    for key in report:
        report[key].reverse() if key != "unmatched" else None
    report["problems"] = problems
    return lines, report


def asks(paste: str) -> tuple[list[str], list[str]]:
    """Fields the sheet says to answer per application, and fields still blank on the sheet itself.

    A blank is named with its `###` section, since "From" alone could be any of the education entries.
    """
    per_application, blanks = [], []
    section = ""
    for line in paste.splitlines():
        if line.startswith("### "):
            section = line[4:].strip()
        elif line.startswith("#"):
            section = ""
        row = _TABLE_ROW.match(line)
        if not row or not _ITALIC_ASK.search(row["value"]):
            continue
        if _PER_APPLICATION.search(row["value"]):
            per_application.append(row["field"])
        else:
            blanks.append(f"{section}: {row['field']}" if section else row["field"])
    return list(dict.fromkeys(per_application)), list(dict.fromkeys(blanks))


def _heading(folder: Path) -> tuple[str, str, str]:
    """Company, title and posting link from the folder's posting.md or notes.md, for a folder with no job row."""
    company = title = url = ""
    for name in ("posting.md", "notes.md"):
        path = folder / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            head = _TITLE_LINE.match(line)
            if head and not company:
                company, title = head["company"].strip(), head["title"].strip()
            link = _LINK_LINE.match(line)
            if link and not url:
                url = link["url"]
        if company:
            break
    return company, title, url


def _form_notes(folder: Path) -> list[str]:
    path = folder / "notes.md"
    if not path.exists():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        # Only the bulleted facts at the top of the notes. The fit tables and gap lists are for interviews, not the form.
        if not text.startswith(("- ", "* ")) or not _FORM_NOTE.search(text):
            continue
        found.append(text[2:].strip().replace("**", ""))
    return found[:12]


def _body(paste: str) -> list[str]:
    """The paste sheet without its own title line, so the fill sheet has one title."""
    lines = paste.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    return lines


def compose(paste: str, resume: str, folder: Path, company: str, title: str, url: str, today: date,
            unchecked: str = "") -> tuple[str, dict]:
    """The sheet's text and a report of what it holds. `unchecked` is why the assay doesn't vouch for the resume now."""
    merged, report = merge(paste, resume)
    per_application, blanks = asks(paste)
    report["ask"] = per_application
    report["blanks"] = blanks
    report["unchecked"] = unchecked
    # The resume first, since it's the one file every site takes. Workday gets the .docx: from a PDF it keeps
    # every wrapped line as a line break, so the PDF is named only as the alternative.
    by_kind = sorted({p.stem for p in folder.glob("*.docx")} | {p.stem for p in folder.glob("*.pdf")},
                     key=lambda n: (is_letter(n), n))
    txts = sorted((p.name for p in folder.glob("*.txt")), key=lambda n: (is_letter(Path(n).stem), n))
    notes = _form_notes(folder)
    out = [
        f"# Fill sheet: {company}: {title}".rstrip(": "),
        "",
        f"Made {today.isoformat()} from `{PASTE_SHEET.as_posix()}` and this folder's `resume.md`. Don't edit this file: "
        "change those and make it again. Nothing here submits anything. You sign in, fill each page from this sheet, "
        "review it and click Submit yourself.",
        "",
    ]
    if unchecked:
        out += [f"> **{NOT_PASSED}** {unchecked} Check it again and make this sheet again before you type any of it into a form.", ""]
    for problem in report["problems"]:
        out += [f"> **{SHEET_PROBLEM}** {problem}", ""]
    out += [
        "## This application",
        "",
    ]
    if url:
        out.append(f"- **Posting:** {url}")
    explained = False
    for stem in by_kind:
        kind = "cover letter" if is_letter(stem) else "resume"
        docx, pdf = (folder / f"{stem}.docx").exists(), (folder / f"{stem}.pdf").exists()
        if docx and pdf:
            why = "" if explained else ": Workday keeps a PDF's line wraps as line breaks, so the PDF is for sites that want one"
            out.append(f"- **Attach as {kind}:** `{stem}.docx` (or `{stem}.pdf`{why})")
            explained = True
        else:
            out.append(f"- **Attach as {kind}:** `{stem}.{'docx' if docx else 'pdf'}`")
    for name in txts:
        out.append(f"- **Paste box text:** `{name}`")
    out += ["", "## Answer by hand for this job", ""]
    out += [f"- {field}" for field in per_application] or ["- Nothing: the sheet answers every field."]
    if notes:
        out += ["", "From `notes.md`:", ""] + [f"- {line}" for line in notes]
    if blanks:
        out += ["", "Still blank on the paste sheet itself, so fill them there once:", ""] + [f"- {field}" for field in blanks]
    out += ["", "## Role text", ""]
    if report["tailored"]:
        out.append("- **Tailored for this application:** " + "; ".join(report["tailored"]))
    if report["kept"]:
        out.append("- **Standard text, since this resume leaves them out:** " + "; ".join(report["kept"]))
    if report["unmatched"]:
        out.append("- **In this resume but not on the paste sheet, so add them there:** " + "; ".join(report["unmatched"]))
    if not any(report[k] for k in ("tailored", "kept", "unmatched")):
        out.append("- The paste sheet has no `### Work experience` sections, so the resume's roles weren't merged.")
    out += ["", "---", ""]
    body = _body("\n".join(merged))
    out += body
    return "\n".join(out).rstrip() + "\n", report


_ITALIC = re.compile(r"\*[^*]*\*")
_PARENS = re.compile(r"\s*\([^)]*\)")
_BACKTICKS = re.compile(r"`[^`]*`")


def clean(value: str) -> str:
    """A sheet value without its notes to the reader: italics, parentheses and code spans."""
    text = _BACKTICKS.sub("", _PARENS.sub("", _ITALIC.sub("", value or "")))
    return re.sub(r"\s+", " ", text).strip(" .;:,")


# The word before a full stop that doesn't end a sentence: an initial ("J. Smith", "U.S. citizen") or a title or place
# abbreviation ("Mary St. John", "St. Louis", "Dr. Lee"). Splitting there would type "Mary St" as a name.
_ABBREVIATION = re.compile(r"(?:^|[\s(.])(?:[A-Za-z]|St|Ste|Mt|Ft|Pt|Dr|Mr|Mrs|Ms|Mx|Jr|Sr|Prof|Rev|Hon|Gen|Col|Capt|Lt|Sgt"
                           r"|Inc|Co|Corp|Ltd|Bros|Ave|Blvd|Rd|vs|etc|approx|dept|e\.g|i\.e)$", re.IGNORECASE)


def answer(value: str) -> str:
    """The answer itself, without the sheet's reasoning: "No. Remote or Madison area" is "No".

    The reasoning starts at the first full stop or semicolon that ends a sentence, so "St. Louis" and "J. Smith" stay whole.
    """
    text = clean(value)
    for stop in re.finditer(r"\.\s|;\s", text):
        if stop.group(0).startswith(";") or not _ABBREVIATION.search(text[:stop.start()]):
            return text[:stop.start()].strip(" .")
    return text.strip(" .")


# A row that tells the candidate what to answer rather than answering: "leave it blank if optional", "the candidate clicks these".
_GUIDANCE = re.compile(
    r"^(?:leave|ask|skip|blank|see|check|n/?a\b)"
    r"|\b(?:himself|herself|yourself|themselves|by hand|per application|if optional|if forced|if allowed|if required)\b",
    re.IGNORECASE,
)


def is_ask(value: str) -> bool:
    """A value the sheet leaves to the candidate rather than answering: an italic ask, a blank, or guidance on what to answer."""
    first = answer(value)
    return bool(_ITALIC_ASK.search(value or "")) or not first or bool(_GUIDANCE.search(first)) or len(first.split()) > 12


def sections(lines: list[str]) -> list[dict]:
    """Every `##` and `###` section of the sheet: its heading, table rows (as cell lists) and loose text lines."""
    found: list[dict] = []
    current: dict | None = None
    in_fence = False
    for line in lines:
        if in_fence and line.startswith("#"):
            in_fence = False  # Never closed: it ends at the heading, as `close_fences` says.
        if line.startswith("```"):
            in_fence = not in_fence
            if current is not None:
                current["fence"].append(line)
            continue
        if in_fence:
            if current is not None:
                current["fence"].append(line)
            continue
        if line.startswith("## ") or line.startswith("### "):
            current = {"level": line.index(" "), "heading": line.lstrip("#").strip(), "rows": [], "text": [], "fence": []}
            found.append(current)
            continue
        if current is None:
            continue
        row = _TABLE_ROW.match(line)
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and not all(set(c) <= set("-: ") for c in cells):
                current["rows"].append(cells)
        elif row:
            current["rows"].append([row["field"], row["value"]])
        elif line.strip():
            current["text"].append(line.strip())
    return found


def _rows(section: dict | None) -> dict[str, str]:
    rows: dict[str, str] = {}
    for cells in (section or {}).get("rows", []):
        if len(cells) >= 2 and cells[0].lower() not in ("field", "question"):
            rows.setdefault(cells[0], cells[1])
    return rows


def _section(found: list[dict], pattern: str, level: int | None = None) -> dict | None:
    rx = re.compile(pattern, re.IGNORECASE)
    for section in found:
        if rx.search(section["heading"]) and (level is None or section["level"] == level):
            return section
    return None


def _fence_text(section: dict) -> str:
    inner = [line for line in section["fence"] if not line.startswith("```")]
    return "\n".join(inner).strip()


def _get(rows: dict[str, str], *names: str) -> str:
    for key, value in rows.items():
        if any(key.lower().startswith(n.lower()) for n in names):
            return value
    return ""


def alternatives(value: str) -> list[str]:
    """Other names a sheet row allows for a pick list, written as "(nearest list option: X)" or "(or: X; Y)"."""
    found = []
    for note in re.findall(r"\(([^)]*)\)", value or ""):
        m = re.match(r"\s*(?:nearest(?: list)? options?|or|also)\s*:\s*(.+)", note, re.IGNORECASE)
        if m:
            found += [a.strip(" .") for a in re.split(r";|\bor\b", m.group(1)) if a.strip(" .")]
    return found


def parse_address(value: str) -> dict[str, str]:
    """Street, city, state and postal code from a sheet's address line, written as "street City: x. State: y. ZIP: z"."""
    text = clean(value)
    out = {"street": "", "city": "", "state": "", "postal": ""}
    # Each value runs to the next "Label:", so a city such as "St. Louis" keeps the words after its full stop.
    labelled = {m.group(1).lower(): m.group(2).strip(" .,") for m in re.finditer(
        r"(City|State|ZIP|Zip|Postal(?: code)?)\s*:\s*(.+?)(?=\s*(?:;|\b[A-Z][A-Za-z]*(?: [a-z]+)?\s*:|$))", text)}
    out["city"] = labelled.get("city", "")
    out["state"] = labelled.get("state", "")
    out["postal"] = labelled.get("zip", "") or labelled.get("postal", "") or labelled.get("postal code", "")
    if not out["postal"]:
        found = re.search(r"\b(\d{5}(?:-\d{4})?)\b", text)
        out["postal"] = found.group(1) if found else ""
    street = re.split(r"\b(?:City|State|ZIP|Zip|Postal)\s*:", text, maxsplit=1)[0]
    street = re.sub(rf"\b{re.escape(out['postal'])}\b", "", street) if out["postal"] else street
    out["street"] = street.strip(" .,;")
    return out


def posting_source(source_key: str, url: str) -> str:
    """Where the posting was found, for a form's "how did you hear about us": the employer's own site, or a job board."""
    board = (source_key or "").split(":")[0].lower()
    if board in ("workday", "greenhouse", "lever", "ashby"):
        return "company site"
    for name in ("linkedin", "indeed", "glassdoor", "ziprecruiter", "dice"):
        if name in (url or "").lower():
            return name
    return ""


def structure(merged_lines: list[str], folder: Path, company: str, title: str, url: str, source: str = "") -> dict:
    """The merged sheet as data: what `pyrite autofill` types, and what it must leave to the candidate."""
    found = sections(merged_lines)
    info = _section(found, r"information", 2)
    questions = _section(found, r"question", 2)
    roles = []
    for section in found:
        if _ROLE_HEADING.match("### " + section["heading"]):
            rows = _rows(section)
            roles.append({
                "title": clean(_get(rows, "Job title")), "company": clean(_get(rows, "Company")),
                "location": clean(_get(rows, "Location")), "current": clean(_get(rows, "I currently")).lower().startswith("y"),
                "from": clean(_get(rows, "From")), "to": clean(_get(rows, "To")), "description": _fence_text(section),
            })
    education = []
    for section in found:
        if re.match(r"education\b", section["heading"], re.IGNORECASE):
            rows = _rows(section)
            # A school still to be filled in on the sheet is a blank, not an entry: the fill sheet lists it as one.
            if is_ask(_get(rows, "School")):
                continue
            education.append({
                "school": clean(_get(rows, "School")), "degree": clean(_get(rows, "Degree")),
                "field": clean(_get(rows, "Field")), "gpa": "" if "blank" in _get(rows, "GPA").lower() else clean(_get(rows, "GPA")),
                # "(nearest list option: Engineering Technology)" on a row: what to take when a tenant's list lacks the real name.
                "school_alternatives": alternatives(_get(rows, "School")),
                "field_alternatives": alternatives(_get(rows, "Field")),
                "degree_alternatives": alternatives(_get(rows, "Degree")),
                "from": "" if is_ask(_get(rows, "From")) else clean(_get(rows, "From")),
                "to": "" if is_ask(_get(rows, "To")) else clean(_get(rows, "To")),
            })
    languages_section = _section(found, r"^languages?$")
    languages = []
    for line in (languages_section or {}).get("text", []):
        name = clean(line.split(",")[0])
        if name:
            languages.append(name)
    certifications = []
    for cells in (_section(found, r"^certifications?$") or {}).get("rows", []):
        if len(cells) >= 2 and cells[0].lower() != "certification":
            certifications.append({"name": clean(cells[0]), "issuer": clean(cells[1]),
                                   "date": "" if len(cells) < 3 or is_ask(cells[2]) else clean(cells[2])})
    skills_section = _section(found, r"^skills$")
    skills: list[str] = []
    for line in (skills_section or {}).get("text", []):
        if "," in line:
            skills += [clean(s) for s in line.split(",") if clean(s)]
    websites = []
    for section in found:
        if re.search(r"website|social", section["heading"], re.IGNORECASE):
            for cells in section["rows"]:
                if len(cells) >= 2 and cells[1].startswith("http"):
                    websites.append(cells[1].strip())
    files: dict[str, str] = {}
    for path in sorted(folder.glob("*.docx")) + sorted(folder.glob("*.pdf")):
        kind = "cover_letter" if is_letter(path.stem) else "resume"
        key = kind if path.suffix == ".docx" else f"{kind}_pdf"
        files.setdefault(key, str(path))
    return {
        "job": {"company": company, "title": title, "url": url, "source": source},
        "files": files,
        "info": _rows(info),
        "roles": roles,
        "education": education,
        "languages": languages,
        "certifications": certifications,
        "skills": list(dict.fromkeys(skills)),
        "websites": list(dict.fromkeys(websites)),
        "questions": _rows(questions),
    }


def make_sheet(folder: Path, company: str = "", title: str = "", url: str = "", today: date | None = None, source: str = "",
               unchecked: str = NOT_LOOKED_UP) -> dict:
    """Write the folder's fill sheet and say what went into it. Raises FileNotFoundError when a source is missing, and
    SheetError when the paste sheet doesn't read back as the roles it holds.

    `unchecked` is `checks.not_covered` for the job: "" only when its last assay pass covers the folder as it is.
    The sheet is still written when it isn't, since you may want to read it, but it says so at the top.
    """
    paste_path = store.ROOT / PASTE_SHEET
    if not paste_path.exists():
        raise FileNotFoundError(
            f"No {PASTE_SHEET.as_posix()} in the workspace. Copy example/{PASTE_SHEET.as_posix()} there and fill it in once."
        )
    resume_path = folder / "resume.md"
    if not resume_path.exists():
        raise FileNotFoundError(f"No resume.md in {folder}, so there's nothing tailored to merge.")
    if not (company or title or url):
        company, title, url = _heading(folder)
    paste = paste_path.read_text(encoding="utf-8")
    resume = resume_path.read_text(encoding="utf-8")
    text, report = compose(paste, resume, folder, company, title, url, today or date.today(), unchecked)
    merged, _ = merge(paste, resume)
    data = structure(merged, folder, company, title, url, source)
    # What autofill types from must hold every role the paste sheet has: one lost to a stray ``` would be typed as
    # another role's text, or not at all. So nothing is written then, and the data from an earlier sheet is taken away.
    expected = sum(1 for line in paste.splitlines() if _ROLE_HEADING.match(line))
    if len(data["roles"]) != expected:
        (folder / SHEET_JSON).unlink(missing_ok=True)
        raise SheetError(f"{PASTE_SHEET.as_posix()} has {expected} work experience sections, but {len(data['roles'])} read "
                         "back after merging, so no fill sheet was written. " + " ".join(report["problems"]).strip())
    out = folder / SHEET
    out.write_text(text, encoding="utf-8")
    (folder / SHEET_JSON).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rel = (lambda p: p.relative_to(store.ROOT).as_posix() if p.is_relative_to(store.ROOT) else str(p))
    report["file"] = rel(out)
    report["json"] = rel(folder / SHEET_JSON)
    return report


def summary(report: dict) -> str:
    parts = [f"{len(report['tailored'])} roles tailored"]
    if report.get("problems"):
        parts.insert(0, f"{SHEET_PROBLEM} " + " ".join(report["problems"]))
    if report["kept"]:
        parts.append(f"{len(report['kept'])} kept from the sheet")
    if report["unmatched"]:
        parts.append(f"{len(report['unmatched'])} in the resume but not on the sheet")
    if report["ask"]:
        parts.append(f"{len(report['ask'])} fields to answer by hand")
    text = ", ".join(parts)
    if report.get("unchecked"):
        text = f"{NOT_PASSED} {report['unchecked']} {text}"
    return text
