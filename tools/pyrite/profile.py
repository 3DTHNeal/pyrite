"""The workspace's profile files as one view, and the one way the Profile tab writes them.

These files decide what a resume may claim and what Pyrite searches for, and the dashboard that changes them has no
login. So the files it may write are fixed here by name and never come from a request. A write names the version of
each file it was based on and is refused if any has changed since. Several files change together or not at all, and
the text each one had before is kept in data/history, so any save can be put back.
"""
import difflib
import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import backup, doctor, factsdoc, gaps, score, settings, store, workspace

# What may be written, by key. The paths are fixed here and never come from a request.
FILES = {
    "facts": "profile/facts.md",
    "terms": "profile/approved-terms.txt",
    "run_notes": "profile/run-notes.md",
    "resume": "profile/resume.md",
    "letter": "profile/cover-letter.md",
    "config": "profile/search.toml",
}
MAX_BYTES = 200_000
ALLOWED_CONTROL = "\n\r\t"
# Earlier copies kept for each file. Older ones are deleted as new ones arrive.
HISTORY_KEEP = 50
ROLE_HEADING = re.compile(r"(?m)^####[ \t]+([^|\r\n]+?)[ \t]*(?:\||$)")
STAMP = re.compile(r"\d{8}T\d{12}Z")
# A History diff longer than this many lines is shown cut short. Put back still writes the whole copy.
DIFF_LINES = 400

# The Profile tab's sections, in the order it shows them. Setup walks the same ones. `files` are the keys a section
# writes, and `required` ones must be set before Pyrite can do its job. Until a section's own editor is built,
# `meanwhile` says where to change it instead, and `fallback` names the tab that edits it, if one does, with the
# section of that tab after a slash. A section with `settings` is set on the Settings tab for good, in the section of
# that name, so it says so and opens it rather than calling itself unbuilt.
STEPS: tuple[dict[str, Any], ...] = (
    {"id": "basics", "group": "About you", "label": "Name and contact", "required": True, "fallback": "facts",
     "files": ("config", "facts", "resume", "letter"),
     "meanwhile": "Until it's built: your name and contact on the Facts tab, and [candidate] name in profile/search.toml.",
     "why": "These go at the top of every resume and letter. The fact check blocks a draft that changes your name or "
            "contact line.",
     "writes": ("search.toml › [candidate] and [documents]", "facts.md › Contact",
                "resume.md and cover-letter.md › the name and @ lines")},
    {"id": "history", "group": "About you", "label": "Work history", "required": True, "fallback": "facts",
     "files": ("facts", "resume", "config"),
     "meanwhile": "Until it's built: the Timeline on the Facts tab, and the same headings in your master resume.",
     "why": "Every draft must use these employers, titles and dates word for word. A draft that changes one is blocked.",
     "writes": ("facts.md › Timeline", "resume.md › employer and role headings", "search.toml › [guard] expected_on_resume")},
    {"id": "achievements", "group": "About you", "label": "Achievements", "required": True, "fallback": "facts",
     "files": ("facts", "run_notes"),
     "meanwhile": "Until it's built: the themed sections on the Facts tab.",
     "why": "Drafts may only claim what's here. A strong list is the biggest single thing you can do for draft quality.",
     "writes": ("facts.md › your themed sections", "run-notes.md › emphasis and wording rules")},
    {"id": "offlimits", "group": "About you", "label": "Off limits", "required": False, "fallback": "facts",
     "files": ("facts", "config"),
     "meanwhile": "Until it's built: Do not use and Unsupported on the Facts tab, and the patterns under [guard] in profile/search.toml.",
     "why": "Confidential names and things you haven't done. Pyrite blocks any draft that mentions them.",
     "writes": ("facts.md › Do not use and Unsupported", "search.toml › [guard] forbidden and unsupported")},
    {"id": "skills", "group": "About you", "label": "Skills and terms", "required": False, "fallback": "facts",
     "files": ("terms",),
     "meanwhile": "Until it's built: approved-terms.txt on the Facts tab.",
     "why": "Specialist words a draft may use. Pyrite blocks unfamiliar ones until you say they're true of you.",
     "writes": ("approved-terms.txt",)},
    {"id": "gaps", "group": "About you", "label": "Gaps to answer", "required": False, "fallback": None,
     "files": ("facts",),
     "meanwhile": "Until it's built: run `pyrite gaps` in a terminal.",
     "why": "Requirements your drafts keep calling gaps. You may have done some of them: a yes adds a fact, and a no "
            "goes under Unsupported, so drafts stop guessing either way.",
     "writes": ("facts.md › a section of facts, or Unsupported", "data/gap-answers.json › which questions you've answered")},
    {"id": "masters", "group": "About you", "label": "Master resume", "required": True, "fallback": None,
     "files": ("resume", "letter"),
     "meanwhile": "Until it's built: edit your master resume and letter in any text editor.",
     "why": "Your master resume and letter. Every draft starts from these, and they must pass the fact check first.",
     "writes": ("resume.md", "cover-letter.md")},
    {"id": "roles", "group": "Your search", "label": "Roles you want", "required": True, "fallback": None,
     "files": ("config", "run_notes"),
     "meanwhile": "Until it's built: [[track]] and [scoring] in profile/search.toml.",
     "why": "The kinds of role Pyrite keeps from the boards. Everything else is dropped before you see it.",
     "writes": ("search.toml › [[track]] and [scoring]", "run-notes.md › roles")},
    {"id": "where", "group": "Your search", "label": "Where you'll work", "required": True, "fallback": None,
     "files": ("config",),
     "meanwhile": "Until it's built: [location] in profile/search.toml.",
     "why": "Which locations count. Onsite roles elsewhere are dropped unless you'll relocate.",
     "writes": ("search.toml › [location] and [market]",)},
    {"id": "companies", "group": "Your search", "label": "Companies to watch", "required": True, "fallback": None,
     "files": ("config",),
     "meanwhile": "Until it's built: [watch.*] and [[manual_check]] in profile/search.toml. The Sources tab shows how each board is answering.",
     "why": "Pyrite reads these companies' job boards every morning.",
     "writes": ("search.toml › [watch.*], [[manual_check]] and [workday] queries",)},
    {"id": "priorities", "group": "Your search", "label": "What comes first", "required": False, "fallback": "settings/ranking",
     "settings": "Cities and industries", "files": ("config",),
     "meanwhile": "Set on the Settings tab, under Cities and industries, beside the points each one adds to a job's score.",
     "why": "Cities and industries you want to see first. These change the order of what you see, not what's kept.",
     "writes": ("search.toml › [promote]",)},
    {"id": "tools", "group": "Automation", "label": "Tools check", "required": False, "fallback": None,
     "files": (),
     "meanwhile": "`pyrite doctor` in a terminal checks the same things.",
     "why": "What Pyrite needs on this computer, and what each thing is for. Everything else works without the "
            "missing ones.",
     "writes": ()},
    {"id": "schedule", "group": "Automation", "label": "Schedule and mail", "required": False, "fallback": "settings/run",
     "settings": "Daily run", "files": ("config",),
     "meanwhile": "Set on the Settings tab: Daily run for how much Pyrite does each morning, and Mail for where it reads "
                  "replies. Your computer's scheduler starts the daily runs themselves, as docs/schedule.md describes.",
     "why": "How much Pyrite does each morning, and where it reads replies from.",
     "writes": ("search.toml › [run] and [inbox]",)},
    {"id": "workspace", "group": "Workspace", "label": "Workspace and backup", "required": False, "fallback": None,
     "files": (),
     "meanwhile": "`pyrite where` in a terminal names the folder in use.",
     "why": "Your resumes, fact bank and tracking data live in a private folder on this computer. Pyrite's own code "
            "folder never holds them.",
     "writes": ("data/backups › a copy of data/pyrite.db, when you make one",)},
)
STEP_IDS = {step["id"] for step in STEPS}


class Conflict(settings.Conflict):
    """A file changed after the page read it."""


def _path(key: str) -> Path:
    return store.ROOT / FILES[key]


def _history_dir() -> Path:
    return store.ROOT / "data" / "history"


def read(key: str) -> str:
    """A profile file's text exactly as it is on disk, line endings included, or "" if it doesn't exist. A byte-order
    mark, which Windows PowerShell 5.1 adds, is left out, since search.toml won't read as TOML with one."""
    path = _path(key)
    if not path.exists():
        return ""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return handle.read()


def version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def versions() -> dict[str, str]:
    return {key: version(read(key)) for key in FILES}


def known_titles(cfg: dict[str, Any]) -> tuple[str, ...]:
    """Job titles from the resume every draft's headings must match, which settle where a title with a comma ends."""
    source = cfg.get("guard", {}).get("heading_source", "")
    path = store.ROOT / source if source else None
    if not path or not path.is_file():
        return ()
    return tuple(dict.fromkeys(m.group(1).strip() for m in ROLE_HEADING.finditer(path.read_text(encoding="utf-8"))))


def _terms(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def view() -> dict[str, Any]:
    """What the Profile tab shows: each file's version, and the parts of them it edits."""
    texts = {key: read(key) for key in FILES}
    cfg = tomllib.loads(texts["config"]) if texts["config"] else {}
    doc = factsdoc.Doc(texts["facts"])
    employers, labeled, unread = doc.timeline(known_titles(cfg))
    contact = doc.contact()
    sections = []
    for section in doc.sections():
        if section.kind in ("contact", "timeline"):
            continue
        sections.append({
            "title": section.title, "kind": section.kind, "line": section.start,
            "items": [{"line": item.line, "level": item.level, "text": item.text} for item in doc.items(section)],
        })
    guard = cfg.get("guard", {})
    return {
        "editable": not store.IS_EXAMPLE,
        "versions": {key: version(text) for key, text in texts.items()},
        "exists": {key: _path(key).exists() for key in FILES},
        "basics": {
            "name": cfg.get("candidate", {}).get("name", ""),
            "contact": contact[1] if contact else "",
            "paper": cfg.get("documents", {}).get("paper", "letter"),
        },
        "timeline": {
            "employers": [{
                "line": employer.line, "name": employer.name, "single": employer.single,
                "start": employer.start, "end": employer.end,
                "roles": [{"line": role.line, "title": role.title, "place": role.place, "start": role.start,
                           "end": role.end, "note": role.note} for role in employer.roles],
            } for employer in employers],
            "other": [{"line": item.line, "label": item.label, "text": item.text} for item in labeled],
            # Lines that read as neither an employer nor a labeled line. The tab offers them as plain text.
            "unread": [{"line": line, "text": doc.bare(line)} for line in unread],
        },
        "sections": sections,
        "off_limits": {"forbidden": guard.get("forbidden", []), "unsupported": guard.get("unsupported", [])},
        "terms": _terms(texts["terms"]),
        **hub(texts, cfg if texts["config"] else None, employers, sections, unread),
    }


# ---------- the hub: each section's state, and what needs you ----------

def _plural(count: int, one: str, many: str = "") -> str:
    return f"{count} {one if count == 1 else many or one + 's'}"


def _watched(cfg: dict[str, Any]) -> int:
    return sum(len(board) for board in cfg.get("watch", {}).values() if isinstance(board, dict))


def _questions(found: dict[str, Any]) -> str:
    asked = gaps.questions(found)
    if asked:
        return f"{_plural(len(asked), 'question')} from {_plural(found['applications'], 'application')}"
    return "Nothing keeps coming up" if found["applications"] else "No applications yet"


def _summaries(texts: dict[str, str], cfg: dict[str, Any], employers, sections: list[dict[str, Any]],
               found: dict[str, Any] | None = None) -> dict[str, tuple[bool, str]]:
    """Each section's one-line summary, and whether it's set at all."""
    name = str(cfg.get("candidate", {}).get("name", "")).strip()
    contact = factsdoc.Doc(texts["facts"]).contact()
    place = re.split(r"\s*[·|•]\s*", contact[1])[0] if contact else ""
    roles = sum(len(employer.roles) for employer in employers)
    facts = sum(1 for section in sections if section["kind"] == "facts" for item in section["items"] if item["level"] == 0)
    themes = sum(1 for section in sections if section["kind"] == "facts" and section["items"])
    guard = cfg.get("guard", {})
    never, not_done = len(guard.get("forbidden", [])), len(guard.get("unsupported", []))
    terms = len(_terms(texts["terms"]))
    # Every draft's headings are checked against heading_source, which needn't be profile/resume.md.
    heading = str(guard.get("heading_source", "") or "")
    has_master = bool(heading) and (store.ROOT / heading).is_file()
    master = ("Resume and letter written" if texts["letter"].strip() else "Resume written, no letter yet") \
        if heading == FILES["resume"] else f"Headings checked against {heading}"
    tracks = [str(track.get("name", "")) for track in cfg.get("track", []) if isinstance(track, dict)]
    location = cfg.get("location", {})
    places = len(score.local_patterns(location)) + len(location.get("local_exact", []))
    where = [_plural(places, "local place")] if places else []
    where += ["remote" if location.get("accept_remote") else "no remote"]
    where += ["will relocate"] if location.get("accept_relocation") else []
    watched, by_hand = _watched(cfg), len(cfg.get("manual_check", []))
    promote = cfg.get("promote", {})
    cities, industries = len(promote.get("cities", [])), len(promote.get("industry", []))
    run, mail = cfg.get("run", {}), cfg.get("inbox", {}).get("source", "imap")
    return {
        "basics": (bool(name and contact), ", ".join(part for part in (name or "No name yet", place) if part)),
        "history": (bool(employers), f"{_plural(roles, 'role')} at {_plural(len(employers), 'employer')}" if employers
                    else "No employers yet"),
        "achievements": (facts > 0, f"{_plural(facts, 'fact')} in {_plural(themes, 'section')}" if facts else "No facts yet"),
        "offlimits": (bool(never or not_done), f"{never} never mentioned, {not_done} not done"),
        "skills": (terms > 0, f"{_plural(terms, 'approved term')}" if terms else "No approved terms"),
        "gaps": (True, _questions(found or gaps.view())),
        "masters": (has_master, master if has_master else "No master resume yet"),
        "roles": (bool(tracks), f"{_plural(len(tracks), 'role type')}: {', '.join(tracks[:3])}{'…' if len(tracks) > 3 else ''}"
                  if tracks else "No role types yet"),
        "where": (bool(places or location.get("accept_remote")), ", ".join(where).capitalize()),
        "companies": (bool(watched or by_hand), f"{watched} watched, {by_hand} by hand"),
        "priorities": (bool(cities or industries), f"{_plural(cities, 'city', 'cities')}, {_plural(industries, 'industry', 'industries')}"),
        "tools": _tools_summary(),
        "schedule": (True, f"Up to {_plural(int(run.get('tailor_per_day', 0) or 0), 'draft')} a day, replies from "
                           f"{'Gmail' if mail == 'gmail' else 'mail (IMAP)'}"),
        "workspace": _workspace_summary(),
    }


def _tools_summary() -> tuple[bool, str]:
    """Whether this computer has what every draft needs, and which of the programs that build documents it found.
    Claude Code takes a second or two to ask, so the section asks it when it's opened."""
    found = doctor.program_checks()
    missing = [check["name"] for check in found if check["required"] and check["ok"] is False]
    if missing:
        return False, f"Missing {' and '.join(missing)}"
    named = [check["what"].split(",")[0] if check["id"] == "pdf" else check["name"] for check in found if check["ok"]]
    return True, f"{', '.join(named[:-1])} and {named[-1]} found" if len(named) > 1 else f"{named[0]} found"


def _workspace_summary() -> tuple[bool, str]:
    """Whether data/pyrite.db has a recent copy in data/backups, and when the newest was made."""
    if store.IS_EXAMPLE:
        return True, "The demo's fictional example"
    made = backup.latest(store.ROOT)
    if made is None:
        return False, "No backup here yet"
    return backup.is_fresh(store.ROOT), f"Last backup {made:%d %b %Y}"


def needs(cfg: dict[str, Any] | None, unread: list[int], asked: int = 0) -> list[dict[str, Any]]:
    """What the Profile tab asks you to look at, most important first: what setup still needs and anything the tab
    couldn't read. Each names the section that fixes it, when one does."""
    found: list[dict[str, Any]] = []
    if not store.IS_EXAMPLE:  # The demo is the example on purpose, so it has nothing left to set up.
        for todo in [*doctor.workspace_todos(store.ROOT, cfg), *doctor.program_todos()]:
            step = todo.get("step") if todo.get("step") in STEP_IDS else None
            found.append({"severity": todo.get("severity", "warn"), "title": todo["what"], "detail": todo["fix"], "step": step})
    if unread:
        found.append({"severity": "info", "title": f"{_plural(len(unread), 'line')} in the Timeline in facts.md "
                                                   f"{'reads' if len(unread) == 1 else 'read'} as neither an employer nor a labeled line.",
                      "detail": "Drafts can still use them. Work history shows them as plain text until they're in that form.",
                      "step": "history"})
    if asked:
        found.append({"severity": "info", "title": f"{_plural(asked, 'requirement')} {'keeps' if asked == 1 else 'keep'} coming up as gaps in your drafts.",
                      "detail": "You may have done some of them. Answer them so drafts stop guessing.", "step": "gaps"})
    rank = {"bad": 0, "warn": 1, "info": 2}
    return sorted(found, key=lambda item: rank.get(item["severity"], 1))


def hub(texts: dict[str, str], cfg: dict[str, Any] | None, employers, sections: list[dict[str, Any]], unread: list[int]) -> dict[str, Any]:
    """Each section with its state and summary, and the list of what needs you."""
    found = gaps.view()
    waiting = needs(cfg, unread, len(gaps.questions(found)))
    summaries = _summaries(texts, cfg or {}, employers, sections, found)
    changed: dict[str, str] = {}
    for entry in history(limit=10_000):
        changed.setdefault(str(entry.get("step") or ""), entry["at"])
    steps = []
    for step in STEPS:
        is_set, summary = summaries[step["id"]]
        attention = any(item["step"] == step["id"] for item in waiting)
        status = "attention" if attention else "set" if is_set else "not_set"
        steps.append({**step, "status": status, "summary": summary, "changed": changed.get(step["id"])})
    setting_up = workspace.setting_up()
    if setting_up and all(step["status"] == "set" for step in steps if step["required"]):
        workspace.finish_setup()  # For good: from here on, loosening a check needs a code.
        setting_up = False
    if setting_up:
        waiting.append({"severity": "info", "title": "Your workspace is new, so changes need no code from this computer yet.",
                        "detail": "Once every required section is set, a change that lets drafts say more, such as "
                                  "approving a term, asks for a code sent to this computer's notifications.", "step": None})
    return {"steps": steps, "needs": waiting, "setting_up": setting_up}


def _clean(key: str, text) -> str:
    if key not in FILES:
        raise ValueError("That isn't a file the Profile tab can change.")
    if not isinstance(text, str):
        raise ValueError(f"Nothing to save for {FILES[key]}.")
    if any(ord(char) < 32 and char not in ALLOWED_CONTROL for char in text) or "\x7f" in text:
        raise ValueError(f"The text for {FILES[key]} has control characters in it, so nothing was saved.")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"{FILES[key]} would be over {MAX_BYTES // 1000} KB, so nothing was saved.")
    if key == "facts" and not text.strip():
        raise ValueError("The fact bank can't be empty: every draft would fail without it.")
    if key == "config":
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as err:
            raise ValueError(f"profile/search.toml wouldn't read after that change ({err}), so nothing was saved.") from err
        if not str(parsed.get("candidate", {}).get("name", "")).strip():
            raise ValueError("search.toml needs [candidate] name, so nothing was saved.")
    return text


def _stamp(keys: list[str]) -> str:
    """A save's stamp, which names the copies it keeps, so it must not be one those files already have.

    On Windows, Python 3.11's clock moves in steps of about 15 ms, so two quick saves could read the same time, and
    the second's copy of a file would overwrite the first's. The stamp is moved on a microsecond until it's free.
    """
    now = datetime.now(UTC)
    while True:
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")
        if not any((_history_dir() / key / f"{stamp}{Path(FILES[key]).suffix}").exists() for key in keys):
            return stamp
        now += timedelta(microseconds=1)


def _keep(stamp: str, key: str, text: str, reason: str, step: str | None) -> None:
    """Keep the text a file had before a save, and note why it changed and which section changed it."""
    folder = _history_dir() / key
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{stamp}{Path(FILES[key]).suffix}"
    with open(folder / name, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    with open(_history_dir() / "log.jsonl", "a", encoding="utf-8") as handle:
        entry = {"stamp": stamp, "key": key, "file": name, "reason": reason, **({"step": step} if step else {})}
        handle.write(json.dumps(entry) + "\n")
    for old in sorted(folder.iterdir())[:-HISTORY_KEEP]:
        old.unlink(missing_ok=True)


def keep(before: dict[str, str], reason: str) -> None:
    """Keep the text files had before a save made outside the Profile tab, as the Facts and Settings tabs make, so
    History lists that save too and can put it back. The caller holds settings._lock and writes the files itself."""
    stamp = _stamp(list(before))
    for key, text in before.items():
        _keep(stamp, key, text, reason, None)


def refuse_stale(current: dict[str, str], based_on: dict[str, Any]) -> None:
    """Raise Conflict if any file changed since the version the page read."""
    for key, text in current.items():
        if based_on.get(key) != version(text):
            raise Conflict(f"{FILES[key]} changed after you opened it, so nothing was saved. "
                           "Reload to see the latest, then make your change again.")


def write(changes: dict[str, Any], based_on: dict[str, Any], reason: str, step: str | None = None) -> dict[str, Any]:
    """Write several profile files at once, each only if it hasn't changed since `based_on` says it was read.

    Every file's earlier text is kept in data/history first. If one write fails, the ones already made are put back,
    so a save never leaves half its files changed. Returns the new versions of every file."""
    if store.IS_EXAMPLE:
        raise ValueError("This is the demo, so the fictional candidate's profile can't be changed. "
                         "Point PYRITE_HOME at your own workspace to edit yours.")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Nothing to save.")
    if not isinstance(based_on, dict):
        raise ValueError("The save didn't say which version it was based on.")
    reason = str(reason or "").strip()[:200] or "Changed on the Profile tab"
    step = step if step in STEP_IDS else None
    texts = {key: _clean(key, text) for key, text in changes.items()}
    with settings._lock:
        current = {key: read(key) for key in texts}
        refuse_stale(current, based_on)
        changed = [key for key, text in texts.items() if text != current[key]]
        existed = {key: _path(key).exists() for key in changed}
        stamp = _stamp(changed)
        for key in changed:
            if existed[key]:
                _keep(stamp, key, current[key], reason, step)
        done: list[str] = []
        try:
            for key in changed:
                _path(key).parent.mkdir(parents=True, exist_ok=True)
                settings._write(_path(key), texts[key])
                done.append(key)
        except Exception:
            for key in done:
                if existed[key]:
                    settings._write(_path(key), current[key])
                else:
                    _path(key).unlink(missing_ok=True)
            raise
    return versions()


def history(limit: int = 100) -> list[dict[str, Any]]:
    """Earlier copies, newest first, with why each file changed."""
    log = _history_dir() / "log.jsonl"
    if not log.exists():
        return []
    entries = []
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("key") in FILES and STAMP.fullmatch(str(entry.get("stamp", ""))):
            entry["kept"] = (_history_dir() / entry["key"] / str(entry.get("file", ""))).is_file()
            entry["path"] = FILES[entry["key"]]
            entry["at"] = datetime.strptime(entry["stamp"], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC).isoformat()
            entries.append(entry)
    return entries[::-1][:limit]


def compare(key: str, stamp: str) -> dict[str, Any]:
    """What putting back the copy kept at `stamp` would change in the file as it is now, as diff lines."""
    old, now = kept(key, stamp), read(key)
    lines = list(difflib.unified_diff(now.splitlines(), old.splitlines(), "now", "put back", n=2, lineterm=""))[2:]
    return {"key": key, "path": FILES[key], "stamp": stamp, "same": old == now,
            "diff": lines[:DIFF_LINES], "cut": max(0, len(lines) - DIFF_LINES)}


def put_back_reason(keys: str | list[str], stamp: str) -> str:
    """The History line for putting back one file, or several, as they were before the save at `stamp`."""
    names = [Path(FILES[key]).name for key in ([keys] if isinstance(keys, str) else keys)]
    named = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    when = datetime.strptime(stamp, "%Y%m%dT%H%M%S%fZ").replace(tzinfo=UTC).astimezone()
    return f"Put back {named} as {'it was' if len(names) == 1 else 'they were'} before the save of {when:%d %b %Y %H:%M}"


def kept_save(stamp: str) -> dict[str, str]:
    """Every file the save at `stamp` changed, as it was just before. A save that changed several files is put back
    whole or not at all, so it can't leave them out of step, such as a name changed back in one file but not another."""
    if not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
        raise ValueError("That isn't a saved copy.")
    keys = list(dict.fromkeys(entry["key"] for entry in history(limit=10_000) if entry["stamp"] == stamp))
    if not keys:
        raise ValueError("That save isn't in History any more.")
    try:
        return {key: kept(key, stamp) for key in keys}
    except ValueError:
        raise ValueError("Some of that save's copies are no longer kept, so it can't be put back whole. "
                         "Put back the files that are kept one at a time.") from None


def kept(key: str, stamp: str) -> str:
    """The text a file had just before the save at `stamp`."""
    if key not in FILES or not isinstance(stamp, str) or not STAMP.fullmatch(stamp):
        raise ValueError("That isn't a saved copy.")
    path = _history_dir() / key / f"{stamp}{Path(FILES[key]).suffix}"
    if not path.is_file():
        raise ValueError("That copy is no longer kept.")
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()
