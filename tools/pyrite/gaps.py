"""The gaps that keep coming up: requirements the drafts keep calling gaps, ranked, as questions for the candidate.

A candidate may have done something they never thought to put in their fact bank, and then every draft that meets
that requirement says there's no experience of it. Each application's notes.md has a numbered "Gaps to prepare for"
list, written by the tailoring run. This reads those lists, groups the gaps that name the same requirement, and ranks
the groups by how many applications raised them, so the candidate can answer the ones that keep costing them.

No AI decides anything here. The grouping is by words, and every group shows what it holds, so a bad merge is plain
to see. Only the candidate's answers change the fact bank: a "yes" is a fact line they write, added the way the
Achievements section adds one, and a "no" is a line in Unsupported, which only tightens what drafts may say. Either
way the unsent drafts that raised the gap are flagged, since they were written without the answer.
"""
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import factsdoc, forms, settings, store

NOTES = "notes.md"
# The numbered list under this heading is what's read. The fit table's Gap rows repeat it, so they aren't.
GAPS_HEADING = re.compile(r"##[ \t]+gaps\b.*", re.I)
ANY_HEADING = re.compile(r"#{1,2}[ \t]+\S")
ITEM = re.compile(r"[ \t]{0,3}(\d{1,2})[.)][ \t]+(?P<text>\S.*)")
BOLD_LEAD = re.compile(r"\*\*(?P<name>.+?)\*\*[ \t]*(?P<rest>.*)")
TITLE_LINE = re.compile(r"#[ \t]+(?P<title>.+?)\s*$")
# A gap that rests only on the record saying nothing, which the candidate may be able to correct.
SILENT = re.compile(
    r"record\s+(?:is\s+)?(?:only\s+)?silent|nothing\s+(?:on|in\s+the)\s+record|not\s+on\s+record|correct\s+me|"
    r"tell\s+me\s+and\s+I['’]ll\s+add|add\s+it\s+to\s+`?(?:profile/)?facts\.md|\bif\s+you\s+(?:have|did|know|ever)\b",
    re.I)
# A gap the candidate has already settled, which the fact bank says.
KNOWN = re.compile(r"\bconfirmed\b|\byou(?:['’]ve|\s+have)\s+(?:said|confirmed)\b|\byou\s+(?:said|confirmed)\b", re.I)
WORD = re.compile(r"[a-z0-9][a-z0-9+#]*(?:\.[a-z0-9]+)*")
# Words that say how much or what kind, not which requirement. "Hands-on C++" and "C++ depth" are the same question.
FILLER = frozenset((
    "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with", "at", "by", "from", "as", "is", "are", "be",
    "not", "no", "any", "vs", "via", "per", "its", "your", "you", "their", "our", "some", "more", "than", "about",
    "like", "other", "record", "experience", "experienced", "years", "year", "depth", "deep", "hands", "direct",
    "formal", "proven", "strong", "level", "skill", "knowledge", "background", "work", "working", "ability",
    "expertise", "familiarity", "exposure", "title", "held",
    # Categories rather than requirements: "Domain" in one posting's notes and another's aren't the same question.
    "domain", "scale", "scope", "seniority",
))
# A one-letter word names nothing, but these two are languages.
LETTERS = frozenset("cr")
# "Aren't" and "the team's" would leave a stray letter behind.
CONTRACTION = re.compile(r"\b\w+n['’]t\b|['’]s\b")
# Groups raised by at least this many applications are asked first. Fewer are listed only on request.
ASK_FROM = 2
# The dashboard's to-do list names the questions once one has come up this often.
ORDER_FROM = 3
ANSWERS = ("yes", "no", "dismissed")
ANSWERED, SEEN = "gap_answered", "gap_seen"
UNSUPPORTED_TITLE = "Unsupported, so don't claim without new evidence"
MAX_TEXT = 300


@dataclass
class Gap:
    folder: str  # The application folder, relative to the workspace.
    number: int
    name: str
    text: str
    kind: str  # silent (the record says nothing), known (already settled) or open (neither said).
    tokens: frozenset[str]


@dataclass
class Group:
    id: str
    label: str
    gaps: list[Gap] = field(default_factory=list)

    @property
    def folders(self) -> list[str]:
        return list(dict.fromkeys(gap.folder for gap in self.gaps))


# ---------- reading the notes ----------

def tokens(text: str) -> frozenset[str]:
    """The words that name a requirement, in a form that lets two wordings of it match."""
    found = set()
    for word in WORD.findall(CONTRACTION.sub(" ", text.lower())):
        word = word.strip(".")
        if not word or word in FILLER or (len(word) == 1 and word not in LETTERS):
            continue
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        found.add(word)
    return frozenset(found)


def same(a: frozenset[str], b: frozenset[str]) -> bool:
    """Whether two gaps name the same requirement: half their words shared, or one's few words all in the other's."""
    if not a or not b:
        return False
    small, large = sorted((a, b), key=len)
    return len(a & b) / len(a | b) >= 0.5 or (small <= large and len(large) <= 3)


def _clean_name(name: str) -> str:
    name = re.sub(r"[*_`]+", "", name).strip()
    return name.rstrip(".:;,").strip()[:120]


def _kind(text: str) -> str:
    if SILENT.search(text):
        return "silent"
    return "known" if KNOWN.search(text) else "open"


def parse(text: str, folder: str = "") -> list[Gap]:
    """The numbered gaps under a notes file's "Gaps to prepare for" heading. A gap is its number, the requirement in
    bold at its start (or its first sentence, without one), and every line up to the next number or heading."""
    found: list[tuple[int, list[str]]] = []
    inside = False
    for line in text.splitlines():
        if GAPS_HEADING.fullmatch(line.strip()):
            inside = True
            continue
        if not inside:
            continue
        if ANY_HEADING.match(line):
            break
        item = ITEM.fullmatch(line.rstrip())
        if item:
            found.append((int(item[1]), [item["text"]]))
        elif found and line.strip():
            found[-1][1].append(line.strip())
    gaps = []
    for number, lines in found:
        body = " ".join(lines)
        lead = BOLD_LEAD.match(body)
        if lead:
            name, rest = _clean_name(lead["name"]), lead["rest"]
        else:
            first = re.split(r"(?<=[.:])\s", body, maxsplit=1)
            name, rest = _clean_name(first[0]), first[1] if len(first) > 1 else ""
        if not name:
            continue
        whole = re.sub(r"\s+", " ", f"{name}. {rest}".replace("**", "")).strip()
        # A name that's only a category, such as "Domain", names no requirement, so the words after it say which.
        gaps.append(Gap(folder, number, name, whole, _kind(whole), tokens(name) or tokens(rest)))
    return gaps


def _title(text: str) -> str:
    """The notes file's own heading, which names the company and the role."""
    for line in text.splitlines():
        match = TITLE_LINE.fullmatch(line)
        if match:
            return re.sub(r"[*_`]+", "", match["title"])[:160]
    return ""


def read_all(root: Path | None = None) -> tuple[list[Gap], dict[str, dict[str, Any]]]:
    """Every gap in every application's notes, and each folder's heading and when its notes were written."""
    root = root or store.ROOT
    gaps: list[Gap] = []
    folders: dict[str, dict[str, Any]] = {}
    base = root / "applications"
    if not base.is_dir():
        return gaps, folders
    for notes in sorted(base.glob(f"*/{NOTES}")):
        rel = notes.parent.relative_to(root).as_posix()
        try:
            text = notes.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = parse(text, rel)
        folders[rel] = {"title": _title(text) or notes.parent.name, "gaps": len(found)}
        gaps += found
    return gaps, folders


def group(gaps: list[Gap]) -> list[Group]:
    """Gaps that name the same requirement, together, most often raised first. Each gap joins the first group with a
    gap it matches, so the result is the same each time for the same notes."""
    groups: list[Group] = []
    for gap in gaps:
        # A gap with no words to match by stands alone: two gaps called "Domain" can be about anything.
        home = next((g for g in groups if any(same(gap.tokens, other.tokens) for other in g.gaps)), None)
        if home is None:
            groups.append(home := Group("", ""))
        home.gaps.append(gap)
    used: set[str] = set()
    for found in groups:
        names = Counter(gap.name.lower() for gap in found.gaps)
        top = min(names.items(), key=lambda pair: (-pair[1], len(pair[0]), pair[0]))[0]
        found.label = next(gap.name for gap in found.gaps if gap.name.lower() == top)
        slug = ""
        for word in re.findall(r"[a-z0-9+#]+", found.label.lower()):
            if slug and len(slug) + len(word) >= 40:
                break
            slug = f"{slug}-{word}" if slug else word
        slug = slug or "gap"
        found.id, number = slug, 2
        while found.id in used:
            found.id, number = f"{slug}-{number}", number + 1
        used.add(found.id)
    groups.sort(key=lambda g: (-len(g.folders), g.label.lower()))
    return groups


# ---------- answers ----------

def _answers_path() -> Path:
    return store.ROOT / "data" / "gap-answers.json"


def answers() -> list[dict[str, Any]]:
    """Every answer given, oldest first. A file that won't read counts as none, so the questions come back."""
    try:
        found = json.loads(_answers_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = found.get("answers") if isinstance(found, dict) else None
    return [row for row in rows or [] if isinstance(row, dict) and row.get("answer") in ANSWERS]


def _save_answers(rows: list[dict[str, Any]]) -> None:
    path = _answers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    settings._write(path, json.dumps({"answers": rows}, indent=2, ensure_ascii=False) + "\n")


def _keys(found: Group) -> list[list[str]]:
    return [sorted(key) for key in dict.fromkeys(gap.tokens for gap in found.gaps) if key]


def answer_for(found: Group, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The latest answer that's about this group, matched by words, so a new wording of an answered gap counts too."""
    for row in reversed(rows):
        if row.get("id") == found.id:
            return row
        keys = [frozenset(key) for key in row.get("keys", []) if isinstance(key, list)]
        if any(same(key, gap.tokens) for key in keys for gap in found.gaps):
            return row
    return None


def _unsupported(facts: str) -> list[str]:
    doc = factsdoc.Doc(facts)
    section = next((s for s in doc.sections() if s.kind == "excluded" and s.title.lower().startswith("unsupported")), None)
    return [item.text for item in doc.items(section)] if section else []


def _fact_lines(facts: str) -> list[str]:
    doc = factsdoc.Doc(facts)
    return [item.text for section in doc.sections() if section.kind == "facts" for item in doc.items(section)]


def tokenized(lines: list[str]) -> list[tuple[str, frozenset[str]]]:
    """Each line with its words, read once for every group `covered` checks against them."""
    return [(line, tokens(line)) for line in lines]


def covered(found: Group, lines: list[tuple[str, frozenset[str]]]) -> str | None:
    """The first line that names every word of one of the group's gaps, or None. `lines` comes from `tokenized`."""
    for line, words in lines:
        if any(gap.tokens and gap.tokens <= words for gap in found.gaps):
            return line
    return None


def _when(iso: str) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def view(conn=None, root: Path | None = None) -> dict[str, Any]:
    """Every group with what it holds and where it stands, for `pyrite gaps` and the Profile tab.

    A group is a question unless it's answered, already in Unsupported, or every gap in it says it's settled. One
    raised again by notes written after its answer says so, since that draft may have been written without it."""
    root = root or store.ROOT
    gaps, folders = read_all(root)
    jobs: dict[str, dict[str, Any]] = {}
    if conn is not None:
        for row in conn.execute("SELECT id, company, title, status, applied_at, app_folder FROM jobs WHERE app_folder IS NOT NULL"):
            jobs[str(row["app_folder"]).replace("\\", "/").rstrip("/")] = dict(row)
    try:
        facts = (root / "profile" / "facts.md").read_text(encoding="utf-8")
    except OSError:
        facts = ""
    # Tokenized once here: every group is checked against every line, which was most of the dashboard's load time.
    unsupported, fact_lines, rows = tokenized(_unsupported(facts)), tokenized(_fact_lines(facts)), answers()
    out = []
    for found in group(gaps):
        answer = answer_for(found, rows)
        listed = covered(found, unsupported)
        kinds = Counter(gap.kind for gap in found.gaps)
        state = ("answered" if answer else "unsupported" if listed else
                 "known" if kinds["known"] == len(found.gaps) else "open")
        since = _when(answer["at"]) if answer else None
        members = []
        for gap in found.gaps:
            job = jobs.get(gap.folder)
            notes = root / gap.folder / NOTES
            written = datetime.fromtimestamp(notes.stat().st_mtime).astimezone() if notes.exists() else None
            members.append({
                "folder": gap.folder, "title": folders.get(gap.folder, {}).get("title", gap.folder),
                "number": gap.number, "name": gap.name, "text": gap.text[:MAX_TEXT * 2], "kind": gap.kind,
                "job_id": job["id"] if job else None, "status": job["status"] if job else None,
                "sent": bool(job and job["applied_at"]),
                "after_answer": bool(since and written and written > since),
            })
        out.append({
            "id": found.id, "label": found.label, "count": len(found.folders), "state": state,
            "kinds": dict(kinds), "answer": answer, "unsupported": listed,
            "hint": covered(found, fact_lines) if state == "open" else None,
            "raised_again": any(m["after_answer"] for m in members) and state == "answered",
            "members": members,
        })
    return {"groups": out, "applications": len(folders), "gaps": len(gaps), "ask_from": ASK_FROM}


def questions(found: dict[str, Any], least: int = ASK_FROM) -> list[dict[str, Any]]:
    """The groups still to ask about, raised by at least `least` applications, most often raised first."""
    return [g for g in found["groups"] if g["state"] == "open" and g["count"] >= least]


def find(found: dict[str, Any], gap_id: str) -> dict[str, Any]:
    match = next((g for g in found["groups"] if g["id"] == gap_id), None)
    if match is None:
        raise ValueError(f"No gap called {gap_id!r}. `pyrite gaps --all` lists every one with its name.")
    return match


# ---------- answering ----------

def _one_line(value, what: str) -> str:
    """An answer as one line for a bullet of its own: the check every Profile editor makes, and a cap on its length."""
    text = forms.one_line(value, what, bullet=True)
    if len(text) > MAX_TEXT:
        raise ValueError(f"{what} is over {MAX_TEXT} characters. Keep it to one fact.")
    return text


def apply(facts: str, answer: str, text: str, section: str = "") -> str:
    """facts.md with one answer added: a "yes" as a fact under `section`, made if it isn't there, and a "no" as a line
    in Unsupported. A dismissal changes nothing."""
    if answer not in ANSWERS:
        raise ValueError("An answer is yes, no or dismissed.")
    if answer == "dismissed":
        return facts
    doc = factsdoc.Doc(facts)
    if answer == "yes":
        text = _one_line(text, "The fact")
        title = _one_line(section, "The section").lstrip("#").strip()
        if not text:
            raise ValueError("Say what you did, as a fact a draft could use: what, where, and a number if there is one.")
        if not title:
            raise ValueError("Choose the section of facts.md it goes in.")
        if factsdoc.Section(title, 0, 0).kind != "facts":
            raise ValueError(f"“{title}” would read as a section that approves nothing or holds your details. "
                             "Choose a section of facts.")
        home = next((s for s in doc.sections() if s.title.lower() == title.lower()), None)
        if home is None:
            doc.add_section(title, [text])
        else:
            doc.add_item(home, text)
        return doc.render()
    text = _one_line(text, "What you haven't done")
    if not text:
        raise ValueError("Say what you haven't done, in words a draft would use.")
    home = next((s for s in doc.sections() if s.kind == "excluded" and s.title.lower().startswith("unsupported")), None)
    if home is None:
        doc.add_section(UNSUPPORTED_TITLE, [text])
        # add_section puts a new section before "Do not use". Unsupported can go last: neither approves anything.
    else:
        doc.add_item(home, text)
    return doc.render()


def _added(before: str, after: str, text: str, unsupported: bool) -> bool:
    """Whether the save really added this line where the answer says, so the record follows what was written."""
    def where(section: factsdoc.Section) -> bool:
        if unsupported:
            return section.kind == "excluded" and section.title.lower().startswith("unsupported")
        return section.kind == "facts"

    def count(facts: str) -> int:
        doc = factsdoc.Doc(facts)
        return sum(item.text.strip() == text for section in doc.sections() if where(section) for item in doc.items(section))
    return count(after) > count(before)


def _phrase(row: dict[str, Any]) -> str:
    if row["answer"] == "yes":
        return f"you've done it, and added “{row['lines'][0]}” to your facts" if row.get("lines") else "you've done it"
    if row["answer"] == "no":
        return "you haven't done it, so it's under Unsupported now"
    return "it doesn't apply"


def record(conn, found: dict[str, Any], wanted: object, before: str, after: str) -> list[dict[str, Any]]:
    """Keep the answers a save made, and flag the unsent drafts that raised each gap. Only an answer whose line the
    save actually added is kept, so what's recorded is what's in the files, whatever the page said."""
    rows = answers()
    kept = []
    for raw in wanted if isinstance(wanted, list) else []:
        if not isinstance(raw, dict):
            continue
        match = next((g for g in found["groups"] if g["id"] == raw.get("id")), None)
        answer = raw.get("answer")
        if match is None or answer not in ("yes", "no"):
            continue
        default = match["label"] if answer == "no" else ""
        try:
            text = _one_line(raw.get("text"), "The answer") or default
        except ValueError:
            continue
        if not _added(before, after, text, answer == "no"):
            continue
        kept.append(_remember(rows, match, answer, [text]))
    if not kept:
        return []
    _save_answers(rows)
    return [{**row, "flagged": flag(conn, find(found, row["id"]), row)} for row in kept]


def _remember(rows: list[dict[str, Any]], match: dict[str, Any], answer: str, lines: list[str]) -> dict[str, Any]:
    keys = [sorted(tokens(m["name"])) for m in match["members"]]
    row = {"id": match["id"], "label": match["label"], "answer": answer, "at": store.now(), "lines": lines,
           "keys": [list(key) for key in dict.fromkeys(tuple(key) for key in keys if key)]}
    rows[:] = [r for r in rows if r.get("id") != match["id"]] + [row]
    return row


def dismiss(found: dict[str, Any], gap_id: str) -> dict[str, Any]:
    """Stop asking about a gap that isn't a fact to settle, such as whether to travel. No file changes."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so its questions can't be answered.")
    rows = answers()
    row = _remember(rows, find(found, gap_id), "dismissed", [])
    _save_answers(rows)
    return row


def forget(gap_id: str) -> bool:
    """Ask about a gap again. The fact bank is left as it is: a line an answer added stays until you change it."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so its questions can't be answered.")
    rows = answers()
    left = [row for row in rows if row.get("id") != gap_id]
    if len(left) == len(rows):
        return False
    _save_answers(left)
    return True


# ---------- drafts to rework ----------

NOT_SENT = ("new", "shortlisted", "needs_fix", "ready")


def flag(conn, match: dict[str, Any], row: dict[str, Any]) -> list[int]:
    """Note on each unsent draft that raised this gap that it was answered. A sent application is a record, so it's
    left alone."""
    flagged = []
    for member in match["members"]:
        job_id = member.get("job_id")
        if not job_id or member.get("sent") or member.get("status") not in NOT_SENT or job_id in flagged:
            continue
        store.log_event(conn, job_id, ANSWERED,
                        f"You answered “{match['label']}”, which this draft's notes list as a gap: {_phrase(row)}. "
                        "It was written without that, so it may be worth reworking.")
        flagged.append(job_id)
    conn.commit()
    return flagged


def rework(conn, jobs: list[dict[str, Any]], root: Path | None = None) -> dict[int, str]:
    """Unsent drafts with an answer since they were written, by job id, with what was answered. A draft stops being
    flagged once its resume is rewritten after the answer, or you say you've seen it."""
    root = root or store.ROOT
    by_id = {job["id"]: job for job in jobs}
    pending: dict[int, list[tuple[str, str]]] = {}
    for row in conn.execute(f"SELECT job_id, kind, ts, detail FROM events WHERE kind IN ('{ANSWERED}', '{SEEN}') ORDER BY id"):
        if row["kind"] == SEEN:
            pending.pop(row["job_id"], None)
        else:
            pending.setdefault(row["job_id"], []).append((row["ts"], row["detail"]))
    found = {}
    for job_id, entries in pending.items():
        job = by_id.get(job_id)
        if not job or job["status"] not in NOT_SENT or job.get("applied_at") or not job.get("app_folder"):
            continue
        resume = root / job["app_folder"] / "resume.md"
        written = datetime.fromtimestamp(resume.stat().st_mtime).astimezone() if resume.exists() else None
        later = [detail for ts, detail in entries if not (written and (when := _when(ts)) and written > when)]
        if later:
            found[job_id] = " ".join(later)
    return found
