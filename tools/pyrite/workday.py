"""Type a job's fill sheet into a Workday application form while the candidate watches. It never submits.

Workday's candidate site is Workday's own app on every tenant, so its fields carry the same ids
everywhere: `workExperience-N--jobTitle`, `education-N--school`, `skills--skills` and so on. That lets
plain code do the typing, with no model in the loop. The candidate signs in, looks at each page
before it's saved, answers what the sheet leaves open, and clicks Submit. The only button this
ever presses at the foot of a page is one that saves and continues; a button that submits is
refused by `is_safe_button`, and there is no code path that submits an application.

Needs Playwright: `python -m pip install playwright` and `python -m playwright install chromium`.
The browser profile lives in the workspace's `data/browser/`, so a tenant's sign-in survives between runs.
"""
import importlib.util
import json
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from . import checks, claude_code, store
from .store import CODE_ROOT, IS_EXAMPLE, get_job, log_event

PROFILE_DIR = Path("data") / "browser"
# The dashboard's run of this, tracked like a resume refresh: in the job's events, with the worker's output in its folder.
STARTED, DONE, FAILED = "autofill_started", "autofill_done", "autofill_failed"
STATE_NAMES = {STARTED: "running", DONE: "done", FAILED: "failed"}
LOG = "autofill-log.txt"
# A run holds the browser open until the window is closed, so "running" can be long. Past this it must have died.
STALE_MINUTES = 180
# Workday's candidate sites, by host. The host is what's checked, never a substring of the whole address, since
# `https://myworkday.example.com` or `https://example.com/?myworkday` would otherwise pass, and a page that copies
# Workday's markup would get the candidate's name, address, history and resume.
WORKDAY_DOMAINS = ("myworkdayjobs.com", "myworkday.com")
OFF =("Workday autofill is experimental and off. To try it, add `autofill = true` under [workday] "
       "in profile/search.toml. It never submits.")


def is_workday(url: str) -> bool:
    """Whether `url` is an https page on one of Workday's own hosts."""
    try:
        parts = urlparse((url or "").strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return parts.scheme == "https" and any(host == domain or host.endswith("." + domain) for domain in WORKDAY_DOMAINS)


def enabled() -> bool:
    """Experimental, so off unless the workspace's search.toml says `autofill = true` under [workday].

    The dashboard's Settings tab edits only [promote], so a page can't turn this on.
    """
    try:
        with open(store.ROOT / "profile" / "search.toml", "rb") as handle:
            return tomllib.load(handle).get("workday", {}).get("autofill") is True
    except (OSError, tomllib.TOMLDecodeError):
        return False


# Workday's own spellings for skills a sheet is likely to name. The workspace's profile/workday-skills.toml
# adds to or overrides these, and `pyrite autofill` prints the ones it had to pick so you can record them.
SKILL_NAMES = {
    "python": "Python (Programming Language)",
    "c++": "C++ Programming Language",
    "machine learning": "Machine Learning (ML)",
    "large language models": "Large Language Models (LLMs)",
    "agile methodologies": "Agile Methodology",
    "continuous integration": "Continuous Integrations",
    "mentoring": "Mentorship",
    "performance management": "Performance Management (PM)",
    "cross-functional team leadership": "Cross-Functional Leadership",
}
SKILL_NAMES_FILE = Path("profile") / "workday-skills.toml"
NEXT_BUTTON = '[data-automation-id="pageFooterNextButton"]'
ADD_BUTTON = '[data-automation-id="add-button"]'
FILE_INPUT = 'input[data-automation-id="file-upload-input-ref"]'
# Pages this knows. Anything else, including the review page, is where it stops.
STEPS = ("Autofill with Resume", "My Information", "My Experience", "Application Questions")
SIGN_IN_MINUTES = 15
SETTLE_MS = 1500
# How long a search picker gets to show its results, and a saved page to turn into the next one.
RESULTS_MS = 8000
PAGE_TURN_MS = 12000
# How long a search's list is given to change before an unchanged one is taken as the answer.
GRACE_MS = 1500


def ask(prompt: str) -> str:
    """input(), after dropping keystrokes typed before the question was asked, so one page's Enter can't answer the next."""
    # Only Windows offers a way to read what's waiting, and checking sys.platform lets type checkers on other systems agree.
    if sys.platform == "win32":
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()
    return input(prompt)


def is_safe_button(text: str) -> bool:
    """Only a button that saves or continues may be pressed at the foot of a page. Submit is the candidate's."""
    words = (text or "").lower()
    return bool(words) and "submit" not in words and "apply" not in words and ("save" in words or "continue" in words or "next" in words)


def short(value: str) -> str:
    """The answer itself, without the sheet's reasoning: "No. Remote or Madison area" is "No"."""
    from .fill import answer
    return answer(value)


def skill_names(skill: str, overrides: dict[str, str] | None = None) -> list[str]:
    """What to look for in Workday's skill list, best first."""
    names = []
    for table in (overrides or {}, SKILL_NAMES):
        for key, value in table.items():
            if key.lower() == skill.lower() and value not in names:
                names.append(value)
    if skill not in names:
        names.append(skill)
    return names


def degree_candidates(degree: str) -> list[str]:
    """Workday tenants list degrees differently: the full name, or a level such as "Masters" or "Bachelors"."""
    text = degree.strip()
    first = text.split(" ")[0] if text else ""
    level = {"master": "Masters", "bachelor": "Bachelors", "doctor": "Doctorate", "associate": "Associates"}
    out = [text] if text else []
    for stem, plural in level.items():
        if first.lower().rstrip("'s").startswith(stem):
            out += [plural, plural.rstrip("s"), plural.rstrip("s") + "'s", plural.rstrip("s") + "'s Degree"]
    if text.lower().startswith("high school"):
        out += ["High School", "High School Diploma", "High School or Equivalent", "High School Diploma or Equivalent", "Secondary School"]
    return list(dict.fromkeys(o for o in out if o))


# The standard questions tenants word in ways that share few words with the sheet's: the page's wording, then the
# sheet row it is. Sponsorship comes before work authorization, since tenants ask it as "require support to obtain
# authorization to work", which also reads as the authorization question.
INTENTS = (
    # "Require relocation assistance to work there" is a different question, and is left to the word match.
    (re.compile(r"sponsor|\bvisa\b|immigration"
                r"|^(?!.*relocat).*(?:require|need)\w*\b.{0,60}\b(?:support|assistance|help)\b.{0,60}\b(?:authori[sz]|work|employment|status)", re.I | re.S),
     re.compile(r"sponsor", re.I)),
    (re.compile(r"(?:authori[sz]ed|eligible|permitted|entitled|legally able)\b.{0,20}\bto work|right to work|work authori[sz]ation", re.I),
     re.compile(r"authori[sz]ed to work|eligible to work|right to work", re.I)),
    (re.compile(r"non.?compete|non.?solicit|restrictive covenant", re.I), re.compile(r"non.?compete|non.?solicit", re.I)),
    (re.compile(r"(?:willing|open|able|prepared)\b.{0,30}\brelocat", re.I), re.compile(r"relocat", re.I)),
)


def match_question(label: str, questions: dict[str, str]) -> tuple[str, str] | None:
    """The sheet row for a question on the page: a standard question by what it asks, else by the words they share."""
    for intent, row in INTENTS:
        if intent.search(label):
            found = next(((q, a) for q, a in questions.items() if row.search(q)), None)
            if found:
                return found
    def words(text: str) -> set[str]:
        return {_stem(w) for w in re.findall(r"[a-z0-9']+", text.lower()) if w not in STOP}
    asked = words(label)
    best, score = None, 0.0
    for question, answer in questions.items():
        ours = words(question)
        if not ours or not asked:
            continue
        overlap = len(asked & ours) / len(ours)
        if overlap > score:
            best, score = (question, answer), overlap
    return best if score >= 0.6 else None


STOP = {"a", "an", "the", "you", "your", "are", "is", "do", "of", "to", "in", "or", "and", "for", "with", "be", "will", "now",
        "have", "has", "this", "that", "any", "please", "us", "we", "our", "at", "by", "on", "if", "it", "as", "from", "been", "one",
        "its", "least", "older", "age"}


def _stem(word: str) -> str:
    """Enough of a stem to pair "subsidiaries" with "subsidiary" and "relatives" with "relative"."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


@dataclass
class Report:
    filled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    stopped_at: str = ""

    def say(self, line: str) -> None:
        print(line, flush=True)

    def summary(self) -> str:
        parts = [f"{len(self.filled)} fields filled"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} left for you")
        if self.decisions:
            parts.append(f"{len(self.decisions)} picks to check")
        return ", ".join(parts) + (f", stopped at {self.stopped_at}" if self.stopped_at else "")

    def detail(self) -> str:
        """The summary and every item that needs the candidate, one per line, for the job's timeline."""
        lines = [self.summary()] + [f"Left for you: {s}" for s in self.skipped] + [f"Check this pick: {d}" for d in self.decisions]
        return "\n".join(lines)


def states(conn) -> dict[int, dict]:
    """Each job's latest autofill run, by job id."""
    return claude_code.latest(conn, STATE_NAMES, STALE_MINUTES, "The run stopped without reporting. Its log is in the job's folder.")


def unchecked(job, cfg: dict | None = None) -> str:
    """Why the assay doesn't vouch for the role text a fill would type into an employer's form, or "" when it does."""
    gap = checks.not_covered(store.ROOT / job["app_folder"], cfg or store.load_config(), job["check_result"])
    return f"{gap} Autofill types only role text that passed the assay, so check the job again first." if gap else ""


def refusal(conn, job, cfg: dict | None = None) -> str | None:
    """Why the dashboard can't start a fill for this job right now, if there's a reason."""
    if IS_EXAMPLE:
        return "The demo doesn't open a browser. In your own workspace, this types the fill sheet into the Workday form."
    if not enabled():
        return OFF
    if job["applied_at"]:
        return "This job was sent, so there's no form left to fill. A second application is a new job."
    if not job["app_folder"] or not (store.ROOT / job["app_folder"] / "resume.md").exists():
        return "This job has no application folder with a resume, so there's nothing to fill from."
    if not (store.ROOT / "profile" / "workday-paste.md").exists():
        return "No profile/workday-paste.md in the workspace. Copy the example and fill it in once."
    if not is_workday(job["url"]):
        return "This only fills Workday forms, and the posting link isn't a Workday site."
    if importlib.util.find_spec("playwright") is None:
        return "Playwright isn't installed. In the pyrite venv: python -m pip install playwright, then python -m playwright install chromium."
    if states(conn).get(job["id"], {}).get("state") == "running":
        return "This form is being filled now. Look for the browser window."
    return unchecked(job, cfg) or None


def start(conn, job_id: int, cfg: dict | None = None) -> None:
    """The dashboard button: check it can work, claim the job, then fill in a process of its own so the page doesn't wait."""
    job = get_job(conn, job_id)
    problem = refusal(conn, job, cfg)
    if problem:
        raise ValueError(problem)
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    problem = refusal(conn, get_job(conn, job_id), cfg)
    if problem:
        conn.rollback()
        raise ValueError(problem)
    log_event(conn, job_id, STARTED)
    conn.commit()
    log = store.ROOT / job["app_folder"] / LOG
    try:
        with log.open("w", encoding="utf-8") as out:
            subprocess.Popen(
                [sys.executable, str(CODE_ROOT / "tools" / "pyrite.py"), "autofill", str(job_id), "--no-pause", "--worker"],
                cwd=store.ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                creationflags=claude_code.NO_WINDOW | claude_code.NEW_GROUP,
            )
    except OSError as err:
        log_event(conn, job_id, FAILED, f"Couldn't start: {err}")
        conn.commit()
        raise ValueError(f"Couldn't start the fill: {err}") from err


def load_skill_overrides(root: Path) -> dict[str, str]:
    path = root / SKILL_NAMES_FILE
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.get("skills", data).items() if isinstance(v, str)}


# ---- Driving the page. Everything below takes a Playwright page and is exercised against a fixture in the tests.

def _fill(page, selector: str, value: str, report: Report, what: str) -> bool:
    box = page.locator(selector)
    if box.count() == 0:
        report.skipped.append(f"{what}: no field on this page")
        return False
    box.first.fill(value)
    report.filled.append(what)
    return True


def _options(page):
    """The entries a search just found. Values already picked show as options too, named for deletion, and aren't these."""
    return page.locator('[role="option"]:not([aria-label*="press delete" i]):visible')


def _says_none(page) -> bool:
    """Whether a search on show says it found nothing. Only a message in view counts: one left in a closed list from an
    earlier search, such as a skill with no entry, would otherwise end the next search before its answer arrives."""
    found = page.get_by_text(re.compile(r"^No Items", re.I))
    return any(found.nth(i).is_visible() for i in range(found.count()))


def _literal(text: str) -> str:
    """`text` as a literal inside a pattern that goes to the browser. Playwright writes a pattern out as /source/flags,
    so a "/" in a name, as in "Electrical/Electronic Engineering Technology", must be escaped too or it ends the
    pattern early and the search fails with a selector error."""
    return re.escape(text).replace("/", r"\/")


def _results(page, names: list[str], before: set[str], timeout_ms: int = RESULTS_MS, chosen_names: list[str] | None = None,
             loading: list[set[str]] | None = None):
    """Wait for a search to answer. Returns the picker's already-chosen entry (one of `chosen_names`, by default `names`),
    an exact match for one of `names`, or neither once the list has settled.

    `before` is what was on show before the search, so a list left over from the last picker isn't taken for this one's.
    Two searches can answer with the same entries, though ("Linux", then "Linux Server"), so a list that hasn't changed
    by the end of the grace period counts as this search's answer.

    `loading` are lists the picker showed the moment the search was sent. An answer takes a round trip, so those are the
    picker's own unfiltered list, which some tenants show while a slow search loads, and never settle as its answer.
    """
    loading = [s for s in (loading or []) if s]
    pattern = "|".join(_literal(n) for n in names)
    picked = "|".join(_literal(n) for n in (chosen_names or names))
    chosen = page.get_by_role("option", name=re.compile(rf"^(?:{picked}), press delete", re.I))
    exact = page.get_by_role("option", name=re.compile(rf"^(?:{pattern})( not checked| checked)?$", re.I))
    now = time.monotonic()
    deadline, grace = now + timeout_ms / 1000, now + GRACE_MS / 1000
    last: set[str] | None = None
    while True:
        if chosen.count():
            return chosen, None
        shown = set(_texts(_options(page)))
        fresh = shown != before or time.monotonic() > grace
        if fresh and exact.count():
            return None, exact
        # Settled means a fresh, non-empty list that stopped changing, or Workday saying there's nothing. An empty list
        # is only the old one cleared while the new one loads.
        if (fresh and shown and shown == last and shown not in loading) or _says_none(page) or time.monotonic() > deadline:
            return None, None
        last = shown
        page.wait_for_timeout(400)


def _picked_name(option, wanted: list[str]) -> str:
    """Which of the wanted names an option is, by its text; the first wanted name when the text says nothing."""
    try:
        text = option.first.inner_text().strip().lower()
    except Exception:
        text = ""
    return next((w for w in sorted(wanted, key=len, reverse=True) if text.startswith(w.lower())), wanted[0])


def pick_search(page, selector, wanted: list[str], report: Report, what: str, must: bool = False, keep_text: bool = False,
                terms: list[str] | None = None) -> str:
    """Type into one of Workday's search pickers and tick the entry that matches. Returns what was picked.

    `selector` is a CSS selector, or a locator already in hand. Each wanted name is searched for in turn, best first,
    and a name is accepted among the results once its own search has come round, so a search for "Python" can turn up
    "Python (Programming Language)" but a last-resort name is never taken while a better one is still to be searched.
    `terms` are further searches to try, such as the first words of a school's name, that must still turn up a wanted name.
    With `must`, the nearest entry offered is taken and reported for a look. With `keep_text`, a name the list lacks
    stays typed in the box, since some tenants accept one that way, and is reported for a look. Otherwise the box
    is cleared and the field is left to the candidate.
    """
    box = page.locator(selector).first if isinstance(selector, str) else selector
    page.keyboard.press("Escape")
    # Everything any search turned up, for the report: a miss should say how this tenant spells things.
    seen: list[str] = []
    said_none: list[str] = []
    for term in list(dict.fromkeys(wanted + list(terms or []))):
        # The wanted names whose turn has come: up to this one, or all of them for a further search term.
        allowed = wanted[:wanted.index(term) + 1] if term in wanted else wanted
        before = set(_texts(_options(page)))
        box.fill(term)
        typed = set(_texts(_options(page)))
        box.press("Enter")
        sent = set(_texts(_options(page)))
        loading = [s for s in (typed, sent) if s != before]
        page.wait_for_timeout(SETTLE_MS // 3)
        # What the picker selected by itself counts whichever name it is; it is on the form already.
        chosen, exact = _results(page, allowed, before, chosen_names=wanted, loading=loading)
        if chosen is None and exact is None:
            found = [t.strip() for t in _texts(_options(page)) if t.strip() and "press delete" not in t.lower()]
            seen += [t for t in found if t not in seen]
            if not found:
                said_none.append(term)
        # A single-value picker selects an exact match by itself and shows it as a removable value.
        if chosen is not None:
            name = _picked_name(chosen, wanted)
            report.filled.append(f"{what}: {name}")
            return name
        if exact is not None:
            name = _picked_name(exact, wanted)
            exact.first.click()
            page.wait_for_timeout(300)
            report.filled.append(f"{what}: {name}")
            return name
        near = _same_name(page, allowed)
        if near:
            report.filled.append(f"{what}: {near}")
            return near
    shown = [t.strip() for t in _options(page).all_inner_texts() if t.strip() and "press delete" not in t.lower()][:8]
    if must and shown:
        _options(page).first.click()
        page.wait_for_timeout(300)
        report.decisions.append(f"{what}: no entry called {wanted[0]!r}, picked {shown[0]!r}. Others: {', '.join(shown[1:6])}")
        return shown[0]
    # Entries sharing words with the wanted names lead, so a whole A-to-Z list a tenant showed can't crowd them out,
    # and "; " keeps a name with a comma in it, such as "Business Administration, Management", in one piece.
    offered = f". Workday offers: {'; '.join(_closest_first(seen or shown, wanted)[:12])}" if (seen or shown) else ""
    if not offered and said_none:
        offered = f". Nothing came up for: {', '.join(said_none)}"
    if keep_text:
        box.fill(wanted[0])
        _close_list(page, box)
        report.skipped.append(f"{what}: this employer's list has no {wanted[0]!r}, so it's typed as is. Check what the page did with it{offered}")
    else:
        report.skipped.append(f"{what}: no entry called {wanted[0]!r}{offered}")
        box.fill("")
        _close_list(page, box)  # A search left open reads as a pick still to finish, and covers the buttons below it.
    return ""


def _closest_first(names: list[str], wanted: list[str]) -> list[str]:
    """`names` with those sharing the most words with any wanted name first, in their order otherwise."""
    words = [set(_same(w).split()) - STOP for w in wanted]
    return sorted(names, key=lambda n: -max((len(set(_same(n).split()) & w) for w in words), default=0))


def _close_list(page, box) -> None:
    """Close a search's list and make sure it stays closed. A slow answer can arrive after Escape and open it again,
    and a list left open covers the fields under it and is read as the next picker's answer."""
    for _ in range(5):
        box.press("Escape")
        page.wait_for_timeout(300)
        if not _options(page).count():
            return


def _same(text: str) -> str:
    """A name reduced to its words, so spellings of one name compare equal: "Test-Driven Development" and "Test Driven
    Development (TDD)", "Electrical & Computer Engineering Technologies" and "Electrical and Computer Engineering Technology"."""
    text = re.sub(r"\([^)]*\)", " ", (text or "").lower()).replace("&", " and ")
    return " ".join(_stem(w) for w in re.findall(r"[a-z0-9+#]+", text))


def _same_name(page, wanted: list[str]) -> str:
    """Click the result that is one of the wanted names in other spelling, if the list shows one. Returns its text."""
    targets = {_same(w) for w in wanted} - {""}
    for i, text in enumerate(_texts(_options(page))):
        if _same(text) in targets:
            _options(page).nth(i).click()
            page.wait_for_timeout(300)
            return text.strip()
    return ""


def _popup(page):
    """The dropdown list that is open now: visible, and not one of the lists that hold values already picked."""
    boxes = page.get_by_role("listbox")
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if box.is_visible() and not box.get_by_role("option", name=re.compile("press delete", re.I)).count():
            return box
    return None


def choose(page, button, wanted: list[str], report: Report, what: str) -> str:
    """Open one of Workday's dropdown buttons and click the entry that matches, trying each wanted name in turn."""
    page.keyboard.press("Escape")
    button.click()
    deadline = time.monotonic() + 4
    listbox = None
    while time.monotonic() < deadline:
        page.wait_for_timeout(300)
        # The list this click opened comes after the button in the page, whether beside it or at the end of the body.
        # Lists of values already picked are skipped by their "press delete" entries.
        following = button.locator("xpath=following::*[@role='listbox']")
        for i in range(following.count()):
            candidate = following.nth(i)
            if candidate.is_visible() and not candidate.get_by_role("option", name=re.compile("press delete", re.I)).count():
                listbox = candidate
                break
        if listbox is None:
            listbox = _popup(page)
        if listbox is not None:
            break
    if listbox is not None:
        for name in wanted:
            entry = listbox.get_by_text(re.compile(rf"^\s*{_literal(name)}\s*$", re.I))
            if entry.count():
                entry.first.click()
                page.wait_for_timeout(300)
                report.filled.append(f"{what}: {name}")
                return name
    shown = [t.strip() for t in listbox.all_inner_texts()][:1] if listbox is not None else []
    page.keyboard.press("Escape")
    report.skipped.append(f"{what}: none of {', '.join(wanted[:3])} is offered" + (f". The list starts: {shown[0][:120]!r}" if shown else ""))
    return ""


def _takes_any_text(page, box, name: str) -> bool:
    """Whether a box is plain text rather than one of Workday's lookups: no picker markings on the box itself, and typing
    a name then pressing Enter brings up no list at all. The name is left typed in a plain box, which is all it needs.

    Only the box's own markings count. The wrapper around it can be a whole education entry on some tenants, holding the
    field-of-study lookup's markings too, and a plain school box read through it is taken for a lookup and left off.
    """
    if box.get_attribute("data-automation-id") == "searchBox" or box.get_attribute("role") == "combobox" \
            or box.get_attribute("aria-autocomplete") is not None or box.get_attribute("aria-haspopup") is not None \
            or re.search(r"select|prompt|multi", box.get_attribute("data-uxi-widget-type") or "", re.I):
        return False
    prompts = page.locator('[data-automation-id="promptOption"]:visible')
    before, shown_before = set(_texts(_options(page))), prompts.count()
    box.fill(name)
    box.press("Enter")
    # A tenant's lookup can take seconds to answer, and a slow answer mistaken for none leaves a name typed but never
    # picked. Values already picked elsewhere on the page show as prompt options too, so only new ones count.
    deadline = time.monotonic() + RESULTS_MS / 2000
    while time.monotonic() < deadline:
        page.wait_for_timeout(300)
        if set(_texts(_options(page))) != before or _says_none(page) or prompts.count() > shown_before:
            return False
    return (box.input_value() or "").strip() == name


def _already_picked(page, selector) -> bool:
    """Whether a search picker already holds a value, as it does when Workday kept a draft of the page."""
    box = page.locator(selector).first if isinstance(selector, str) else selector
    # The field's own container: Workday wraps each in a formField element, and the test fixture in a label.
    holder = box.locator("xpath=ancestor::*[starts-with(@data-automation-id,'formField-') or self::label][1]")
    return bool(holder.count() and holder.get_by_role("option", name=re.compile("press delete", re.I)).count())


def _is_unset(button) -> bool:
    return bool(button.count()) and button.first.inner_text().strip().lower() in ("select one", "")


def _add_after(page, heading: str):
    """The Add button that belongs to a section, found from its heading so other sections' buttons are left alone.

    None when the page has no such section: tenants leave out Languages or Websites.
    """
    heads = page.get_by_role("heading", name=re.compile(rf"^{heading}", re.I))
    if not heads.count():
        return None
    button = heads.first.locator("xpath=following::button[@data-automation-id='add-button'][1]")
    return button if button.count() else None


def fill_roles(page, roles: list[dict], report: Report) -> None:
    for i, role in enumerate(roles):
        titles = page.locator('[id^="workExperience-"][id$="--jobTitle"]')
        if titles.count() <= i:
            _add_after(page, "Work Experience").click()
            page.wait_for_timeout(800)
        block = page.locator('[id^="workExperience-"][id$="--jobTitle"]').nth(i).get_attribute("id").rsplit("--", 1)[0]
        what = f"job {i + 1} ({role['title']})"
        page.locator(f'[id="{block}--jobTitle"]').fill(role["title"])
        page.locator(f'[id="{block}--companyName"]').fill(role["company"])
        if role.get("location"):
            page.locator(f'[id="{block}--location"]').fill(role["location"])
        if role.get("current"):
            page.locator(f'[id="{block}--currentlyWorkHere"]').check()
        for key, name in (("from", "startDate"), ("to", "endDate")):
            value = role.get(key, "")
            if not value or (key == "to" and role.get("current")):
                continue
            month, year = (value.split("/") + [""])[:2]
            page.locator(f'[id="{block}--{name}-dateSectionMonth-input"]').fill(month)
            page.locator(f'[id="{block}--{name}-dateSectionYear-input"]').fill(year)
        page.locator(f'[id="{block}--roleDescription"]').fill(role.get("description", ""))
        report.filled.append(what)


def _blocks(page, prefix: str) -> list[str]:
    """The repeated blocks of a section, by the id prefix Workday gives each: "education-232" and so on."""
    ids = page.locator(f'[id^="{prefix}-"]').evaluate_all("els => els.map(e => e.id)")
    found: list[str] = []
    for one in ids:
        head = one.rsplit("--", 1)[0] if "--" in one else one
        if head not in found:
            found.append(head)
    return found


def _ensure_block(page, prefix: str, heading: str, index: int, report: Report, what: str) -> str:
    """The index-th block of a section, adding one when it isn't there yet. Empty when the page offers no such block."""
    blocks = _blocks(page, prefix)
    if len(blocks) <= index:
        add = _add_after(page, heading)
        if add is None:
            report.skipped.append(f"{what}: this page has no {heading} section")
            return ""
        add.click()
        deadline = time.monotonic() + 6
        while len(blocks) <= index and time.monotonic() < deadline:
            page.wait_for_timeout(400)
            blocks = _blocks(page, prefix)
    if len(blocks) <= index:
        report.skipped.append(f"{what}: no {heading.lower()} block appeared on the page")
        return ""
    return blocks[index]


def _in_block(page, block: str, suffixes: list[str], fallback: str = ""):
    """A field of a block by the id endings it might have on this tenant, else the first element matching a CSS fallback."""
    for suffix in suffixes:
        box = page.locator(f'[id="{block}--{suffix}"]')
        if box.count():
            return box.first
    if fallback:
        box = page.locator(f'[id^="{block}--"]{fallback}')
        if box.count():
            return box.first
    return None


def _remove_block(page, inside) -> None:
    """Take a section entry off the form again, with the Delete button Workday gives each one. Just emptied when there is none."""
    page.keyboard.press("Escape")
    remover = inside.locator("xpath=ancestor::*[.//button[contains(., 'Delete') or contains(@aria-label, 'Delete')]][1]"
                             "//button[contains(., 'Delete') or contains(@aria-label, 'Delete')]")
    if remover.count():
        remover.first.click()
        page.wait_for_timeout(600)
    else:
        inside.fill("")


def fill_education(page, education: list[dict], report: Report) -> None:
    kept = 0  # Blocks on the form so far: an entry left off doesn't take up a place.
    for i, entry in enumerate(education):
        what = f"education {i + 1}"
        block = _ensure_block(page, "education", "Education", kept, report, what)
        if not block:
            return
        kept += 1
        school = _in_block(page, block, ["school", "schoolName", "schoolOrUniversity"], '[data-automation-id="searchBox"]') \
            or _in_block(page, block, [], 'input[type="text"]')
        if school is None:
            ids = page.locator(f'[id^="{block}--"]').evaluate_all("els => els.map(e => e.id)")
            report.skipped.append(f"{what}: no school box found. Fields on this tenant: {', '.join(ids)[:200]}")
            continue
        # Workday keeps a draft of a page it wouldn't save, so a value already there is left alone. A school the tenant's
        # list lacks is never swapped for a random entry: the sheet's stated alternatives are tried, and failing those the
        # entry is left off the form altogether, since the resume carries it. A field of study stays typed as is.
        # Some tenants take the school as plain text instead of a lookup, and that box just gets the name.
        if not _already_picked(page, school):
            name = entry["school"]
            if _takes_any_text(page, school, name):
                report.filled.append(f"{what} school: {name} (typed, since this employer's box takes any name)")
                picked = name
            else:
                # A lookup table may balk at the full name but answer to its first words: "Western Prairie" finds the university.
                shorter = [" ".join(name.split()[:2])] if len(name.split()) > 2 else []
                picked = pick_search(page, school, [name] + entry.get("school_alternatives", []), report, f"{what} school", terms=shorter)
            if not picked:
                # The picker's own message names what the lookup offered, which is the clue to how this tenant spells the school.
                offered = report.skipped.pop().partition(". Workday offers: ")[2]
                # A search that offered nothing may not have been a lookup at all. Removing an entry is only for a list
                # that answered, so the box gets one more look, and a plain one keeps the name.
                if not offered and _takes_any_text(page, school, name):
                    report.filled.append(f"{what} school: {name} (typed, since this employer's box takes any name)")
                    picked = name
            if not picked:
                _remove_block(page, school)
                kept -= 1
                report.skipped.append(f"{what}: this employer's list has no {name!r}, so that entry was left off. The resume carries it."
                                      + (f" Its lookup offers: {offered}" if offered else ""))
                continue
        # The rest of the entry on its own, so one odd field can't stop the next school from going in.
        try:
            _education_details(page, block, entry, report, what)
        except Exception as err:
            report.skipped.append(f"{what}: stopped on an error, so finish it by hand: {str(err).splitlines()[0][:160]}")
            page.keyboard.press("Escape")


def _year_box(page, block: str, name: str):
    """The year input of one of an education entry's dates. Workday wraps a date in elements that share its id stem, and
    only the input takes text, so the match is narrowed to inputs and the year one is preferred over a month."""
    for selector in (f'input[id^="{block}--{name}"][id*="Year" i]', f'[id^="{block}--{name}"] input[id*="Year" i]',
                     f'input[id^="{block}--{name}"]', f'[id^="{block}--{name}"] input'):
        box = page.locator(selector)
        if box.count():
            return box.first
    return None


def _education_details(page, block: str, entry: dict, report: Report, what: str) -> None:
    """An education entry's degree, field of study, GPA and years, once its school is in."""
    degree = _in_block(page, block, ["degree", "degreeType"], "button")
    if degree is not None and _is_unset(degree) and entry.get("degree"):
        choose(page, degree, degree_candidates(entry["degree"]) + entry.get("degree_alternatives", []), report, f"{what} degree")
    elif degree is not None and entry.get("degree"):
        report.filled.append(f"{what} degree: {degree.inner_text().strip()} (already set, left as is)")
    elif entry.get("degree"):
        report.skipped.append(f"{what} degree: no degree dropdown found in this entry")
    field = _in_block(page, block, ["fieldOfStudy", "fieldsOfStudy", "major"])
    if field is not None and entry.get("field"):
        # Workday's field of study is always a pick from the tenant's list, never free text. A name typed and not
        # picked looks filled but is dropped on save, so a field the list lacks is cleared and reported instead.
        if _already_picked(page, field):
            report.filled.append(f"{what} field of study: already set, left as is")
        else:
            # A tenant's search can find nothing for a long name and still list it, so the name's first word is searched
            # too ("Electrical"). It only brings the tenant's spellings into view: just the sheet's names can be picked.
            words = entry["field"].split()
            broader = [words[0]] if len(words) > 2 else []
            pick_search(page, field, [entry["field"]] + entry.get("field_alternatives", []), report, f"{what} field of study", terms=broader)
    elif field is None and entry.get("field"):
        report.skipped.append(f"{what} field of study: no field-of-study box found in this entry")
    gpa = _in_block(page, block, ["gradeAverage", "gpa"])
    if gpa is not None and entry.get("gpa"):
        gpa.fill(entry["gpa"])
        report.filled.append(f"{what} GPA")
    for key, name in (("from", "firstYearAttended"), ("to", "lastYearAttended")):
        value = entry.get(key, "")
        box = _year_box(page, block, name)
        if box is None:
            continue
        if value:
            box.fill(value.split("/")[-1])
            report.filled.append(f"{what} {key}")
        else:
            report.skipped.append(f"{what} {key}: the sheet has no date")


def fill_languages(page, languages: list[str], report: Report) -> None:
    for i, language in enumerate(languages):
        block = _ensure_block(page, "language", "Languages", i, report, f"language {i + 1}")
        if not block:
            return  # Reported already: no block, or no Languages section on this tenant's page.
        picker = _in_block(page, block, ["language"], "button")
        if picker is not None and _is_unset(picker):
            choose(page, picker, [language], report, f"language {i + 1}")
        native = _in_block(page, block, ["native", "fluent"], 'input[type="checkbox"]')
        if native is not None and not native.is_checked():
            native.check()
        # A tenant may ask for a level per skill. Every remaining "Select One" in the block gets the fluent entry.
        for _ in range(8):
            pending = page.locator(f'[id^="{block}--"]').filter(has_text=re.compile(r"^\s*Select One\s*$"))
            if not pending.count():
                break
            if not choose(page, pending.first, ["5 - Fluent", "Fluent", "Native", "Native or Bilingual"], report, f"language {i + 1} level"):
                break


def fill_skills(page, skills: list[str], report: Report, overrides: dict[str, str] | None = None) -> None:
    box = page.locator("#skills--skills")
    if not box.count():
        if skills:
            report.skipped.append("skills: no skills field on this page")
        return
    # Skills already on the form, from a draft Workday kept or an earlier run. A tenant that doesn't wrap the field the
    # usual way still shows them as removable entries somewhere on the page.
    holder = page.locator('[data-automation-id="formField-skills"]')
    chips = (holder if holder.count() else page).get_by_role("option", name=re.compile("press delete", re.I))
    have = {t.split(",")[0].strip().lower() for t in _texts(chips)}
    for skill in skills:
        names = skill_names(skill, overrides)
        if any(n.lower() in have for n in names):
            continue
        pick_search(page, "#skills--skills", names, report, f"skill {skill}")
    page.keyboard.press("Escape")


def fill_websites(page, websites: list[str], report: Report) -> None:
    for i, url in enumerate(websites):
        block = _ensure_block(page, "webAddress", "Websites", i, report, f"website {i + 1}")
        if not block:
            return
        box = _in_block(page, block, ["url", "website", "address"], 'input[type="text"]')
        if box is None or box.input_value().strip():
            continue
        box.fill(url)
        report.filled.append(f"website {url}")


def upload_resume(page, files: dict[str, str], report: Report) -> None:
    box = page.locator(FILE_INPUT)
    path = files.get("resume") or files.get("resume_pdf")
    if page.get_by_text(re.compile("successfully uploaded", re.I)).count() or page.locator('[data-automation-id="delete-file"]').count():
        report.filled.append("resume: already attached")
    elif not box.count():
        report.skipped.append("resume: no upload box on this page")
    elif not path or not Path(path).exists():
        report.skipped.append("resume: no built resume to attach")
    else:
        box.first.set_input_files(path)
        page.wait_for_timeout(SETTLE_MS)
        report.filled.append(f"resume: {Path(path).name}")


def fill_experience(page, data: dict, report: Report, overrides: dict[str, str] | None = None) -> None:
    """Each section on its own, so a tenant's odd education block can't stop the skills or the resume from going in."""
    sections = (
        ("jobs", lambda: fill_roles(page, data.get("roles", []), report)),
        ("education", lambda: fill_education(page, data.get("education", []), report)),
        ("languages", lambda: fill_languages(page, data.get("languages", []), report)),
        ("skills", lambda: fill_skills(page, data.get("skills", []), report, overrides)),
        ("websites", lambda: fill_websites(page, data.get("websites", []), report)),
        ("resume", lambda: upload_resume(page, data.get("files", {}), report)),
    )
    for name, fill_section in sections:
        try:
            fill_section()
        except Exception as err:
            report.skipped.append(f"{name}: stopped on an error, so finish it by hand: {str(err).splitlines()[0][:160]}")
            page.keyboard.press("Escape")


def settle(page) -> None:
    """Give a page that has just appeared its moment to finish drawing its fields."""
    try:
        page.locator(NEXT_BUTTON).first.wait_for(state="visible", timeout=PAGE_TURN_MS)
        page.wait_for_load_state("networkidle", timeout=PAGE_TURN_MS)
    except Exception:
        pass  # A page that never goes quiet is still filled; the pause below gives it a moment either way.
    page.wait_for_timeout(SETTLE_MS)


def _field_for(page, pattern: str):
    """The form field whose label matches, as Workday wraps each one; None when the page has no such question."""
    fields = page.locator('[data-automation-id^="formField-"]').filter(has_text=re.compile(pattern, re.I))
    return fields.first if fields.count() else None


def answer_radio(page, question_pattern: str, value: str, report: Report, what: str) -> bool:
    """Tick Yes or No on the question whose label matches, looking inside that question's own field first."""
    field = _field_for(page, question_pattern)
    scopes = [field, page] if field is not None else [page]
    for scope in scopes:
        radio = scope.get_by_role("radio", name=re.compile(rf"^\s*{_literal(value)}\s*$", re.I))
        if not radio.count():
            radio = scope.get_by_label(re.compile(rf"^\s*{_literal(value)}\s*$", re.I))
        if radio.count():
            radio.first.check()
            report.filled.append(f"{what}: {value}")
            return True
    return False


# Each source a "how did you hear about us" answer can name: the searches to try, the entries to accept among the
# results, and the categories of a tenant's tree to look in. The company-site pattern is narrow on purpose: a loose
# "career" or "company" takes "Career Fair" or "Company Event", which are different answers.
SOURCE_TERMS = {
    "company site": (["Company Website", "Company Careers Site", "Careers Site", "Career Site", "Careers Page", "Corporate Website",
                      "Employer Website", "Website", "Careers"],
                     re.compile(r"(?:company|corporate|employer|careers?)(?:'s)?\s*(?:web\s*site|site|page|portal)"
                                r"|^\s*(?:company\s+)?web\s*site\s*$|^\s*careers?\s*$", re.I),
                     re.compile(r"company|career|website|online|internet", re.I)),
    "linkedin": (["LinkedIn"], re.compile(r"linked\s*in", re.I), re.compile(r"social|job board|online|internet|website|media", re.I)),
    "indeed": (["Indeed"], re.compile(r"indeed", re.I), re.compile(r"job board|online|internet|website", re.I)),
    "glassdoor": (["Glassdoor"], re.compile(r"glassdoor", re.I), re.compile(r"job board|online|internet|website", re.I)),
    "ziprecruiter": (["ZipRecruiter"], re.compile(r"zip\s*recruiter", re.I), re.compile(r"job board|online|internet|website", re.I)),
    "dice": (["Dice"], re.compile(r"\bdice\b", re.I), re.compile(r"job board|online|internet|website", re.I)),
}
# Entries that are never the answer for a source above, whatever words they share with it.
_NOT_A_SOURCE = re.compile(r"fair|event|referr|agency|recruiter\b|newspaper|magazine|mail|radio|tv\b|television|conference|campus|university", re.I)


def source_key(text: str) -> str:
    """Which source a sheet's answer or a picked entry names: "LinkedIn" is linkedin, "Company careers site" is company site."""
    words = short(text or "")
    if not words or _NOT_A_SOURCE.search(words):
        return ""
    for key, (_, accept, _) in SOURCE_TERMS.items():
        if accept.search(words) or key in words.lower():
            return key
    return ""


def _click_matching(page, accept, report: Report, what: str) -> bool:
    for i, text in enumerate(_texts(_options(page))):
        if accept.search(text) and not _NOT_A_SOURCE.search(text):
            _options(page).nth(i).click()
            page.wait_for_timeout(300)
            report.filled.append(f"{what}: {text.strip()}")
            return True
    return False


def pick_source(page, field, box, source: str, report: Report, company: str = "", quiet: bool = False) -> bool:
    """Answer "how did you hear about us" with `source`, taking the tenant's nearest wording.

    Searches first. Tenants that offer a tree of categories instead get the list opened and the likely categories
    looked through. A posting from the employer's own board also accepts an entry that names the employer, such as
    "Acme Careers". With `quiet`, a miss isn't reported, since another source is tried next.
    """
    what = "How did you hear about us"
    terms, accept, categories = SOURCE_TERMS.get(source, ([], None, None))
    if not terms or accept is None or categories is None:
        return False
    if source == "company site" and company:
        first = _literal(company.split()[0])
        terms = [f"{company} Careers", f"{company} Website", company] + terms
        accept = re.compile(rf"{accept.pattern}|^\s*{first}\b.*(?:career|job|site|web)", re.I)
    page.keyboard.press("Escape")
    for term in terms:
        before = set(_texts(_options(page)))
        box.fill(term)
        box.press("Enter")
        page.wait_for_timeout(SETTLE_MS // 3)
        chosen, exact = _results(page, [term], before)
        if chosen is not None:
            report.filled.append(f"{what}: {term}")
            return True
        if exact is not None:
            exact.first.click()
            page.wait_for_timeout(300)
            report.filled.append(f"{what}: {term}")
            return True
        if _click_matching(page, accept, report, what):
            return True
    box.fill("")
    page.keyboard.press("Escape")
    # No search hit. Open the whole list from the field's own button and look in each likely category, one level deep.
    seen: list[str] = []
    opener = field.locator("button").first
    if opener.count():
        tried: set[str] = set()
        for _ in range(4):
            opener.click()
            page.wait_for_timeout(SETTLE_MS)
            shown = [t.strip() for t in _texts(_options(page)) if t.strip()]
            seen += [s for s in shown if s not in seen]
            if _click_matching(page, accept, report, what):
                return True
            category = next((i for i, t in enumerate(shown) if categories.search(t) and t not in tried and not _NOT_A_SOURCE.search(t)), None)
            if category is None:
                page.keyboard.press("Escape")
                break
            tried.add(shown[category])
            _options(page).nth(category).click()
            page.wait_for_timeout(SETTLE_MS)
            shown = [t.strip() for t in _texts(_options(page)) if t.strip()]
            seen += [s for s in shown if s not in seen]
            if _click_matching(page, accept, report, what):
                return True
            page.keyboard.press("Escape")  # Closes the category, so the next pass opens the list at its top again.
    if not quiet:
        report.skipped.append(f"{what}: nothing offered matched {source!r}. Seen: {', '.join(seen[:12]) or 'nothing'}")
    return False


def _picked_values(holder) -> list[str]:
    """The values a picker holds, by the names Workday gives their removable entries: "LinkedIn, press delete to clear value"."""
    return [t.split(",")[0].strip() for t in _texts(holder.get_by_role("option", name=re.compile("press delete", re.I)))]


def _clear_picked(page, holder) -> None:
    """Remove a picker's values, the way their names say to: focus each one and press Delete."""
    for _ in range(4):
        chips = holder.get_by_role("option", name=re.compile("press delete", re.I))
        if not chips.count():
            return
        chips.first.click()
        page.keyboard.press("Delete")
        page.wait_for_timeout(400)


def answer_source(page, field, box, sources: list[str], report: Report, company: str = "") -> bool:
    """Answer the source question with the first of `sources` the tenant offers.

    A value already there, from a draft Workday kept or an earlier run, stays when it is the first wanted source or a
    referral the candidate chose; anything else is replaced, and the run says so.
    """
    what = "How did you hear about us"
    holder = box.locator("xpath=ancestor::*[starts-with(@data-automation-id,'formField-') or self::label][1]")
    holder = holder if holder.count() else field
    have = _picked_values(holder) if holder is not None else []
    if have:
        if any(source_key(v) == sources[0] or re.search(r"referr", v, re.I) for v in have):
            report.filled.append(f"{what}: {have[0]} (already set, left as is)")
            return True
        report.decisions.append(f"{what}: it held {have[0]!r} from before, which isn't what the sheet says, so it was replaced")
        _clear_picked(page, holder)
    # Stops at the first source the form accepts. Every earlier try is quiet, so only the last failure is reported.
    return any(pick_source(page, field, box, source, report, company, quiet=i < len(sources) - 1) for i, source in enumerate(sources))


def _fill_blank(page, selector: str, value: str, report: Report, what: str) -> None:
    """Type into a field only when it is empty: the account's own details are already right."""
    box = page.locator(selector)
    if value and box.count() and not box.first.input_value().strip():
        box.first.fill(value)
        report.filled.append(f"{what}: {value}")


def _choose_field(page, label_pattern: str, wanted: list[str], report: Report, what: str) -> None:
    """Set a dropdown found by its label, when it hasn't been set."""
    field = _field_for(page, label_pattern)
    button = field.locator("button") if field is not None else page.locator("#nothing")
    if _is_unset(button):
        choose(page, button.first, [w for w in wanted if w], report, what)


def _hear_about_field(page):
    """The "how did you hear about us" picker: its field container and its text box, found by label however the tenant lays it out."""
    field = _field_for(page, r"hear about")
    if field is not None and field.locator('input[type="text"]').count():
        return field, field.locator('input[type="text"]').first
    for box in (page.get_by_role("textbox", name=re.compile(r"hear about", re.I)), page.get_by_label(re.compile(r"hear about", re.I))):
        if box.count():
            holder = box.first.locator("xpath=ancestor::*[starts-with(@data-automation-id,'formField-')][1]")
            return (holder if holder.count() else box.first.locator("xpath=ancestor::div[2]")), box.first
    return None, None


def fill_information(page, info: dict[str, str], report: Report, source: str = "", company: str = "") -> None:
    """Page 1 is mostly the account's own details. This answers the yes/no questions, and where the posting was found."""
    from .fill import is_ask
    hear, hear_box = _hear_about_field(page)
    if hear_box is not None:
        # The sheet's answer comes first, so a candidate can name the source every tenant lists (LinkedIn); where the
        # posting was found is the fallback. A sheet answer that isn't a known source is searched for as written.
        sheet_answer = next((a for q, a in info.items() if re.search(r"hear about", q, re.I)), "")
        stated = "" if is_ask(sheet_answer) else short(sheet_answer)
        sources = list(dict.fromkeys(s for s in (source_key(stated), source) if s))
        picked = answer_source(page, hear, hear_box, sources, report, company) if sources else _already_picked(page, hear_box)
        if not picked and stated and not source_key(stated):
            picked = bool(pick_search(page, hear_box, [stated], report, "How did you hear about us"))
        if not picked and not sources:
            report.skipped.append("How did you hear about us: no entry for the posting's source, so it's yours to answer on the page")
    elif hear_box is None and page.get_by_text(re.compile(r"hear about", re.I)).count():
        report.skipped.append("How did you hear about us: the page asks it, but its box wasn't found")
    for question, answer in info.items():
        if is_ask(answer) or re.search(r"hear about", question, re.I):
            continue
        value = short(answer)
        if value.lower() in ("yes", "no") and re.search(r"previously|worked for|employed", question, re.I):
            if not answer_radio(page, r"previously|worked for|employed", value, report, question):
                report.skipped.append(f"{question}: no Yes/No question found on the page")
        elif re.search(r"phone device", question, re.I):
            _choose_field(page, r"phone device type", [value, "Mobile", "Mobile Phone", "Cell", "Cellular", "Home Cellular", "Personal Cellular", "Cell Phone"],
                          report, "Phone device type")
        elif re.search(r"phone code", question, re.I):
            _choose_field(page, r"phone code", [value, "United States of America (+1)", "+1"], report, "Country phone code")
        elif re.search(r"^address", question, re.I):
            from .fill import parse_address
            parts = parse_address(answer)
            for key, selector in (("street", '[id$="--addressLine1"]'), ("city", '[id$="--city"]'), ("postal", '[id$="--postalCode"]')):
                _fill_blank(page, selector, parts[key], report, f"address {key}")
            if parts["state"]:
                _choose_field(page, r"^state|state\b|province|region", [parts["state"]], report, "State")
            if not parts["postal"] and page.locator('[id$="--postalCode"]').count() and not page.locator('[id$="--postalCode"]').first.input_value():
                report.skipped.append("Postal code: not on the sheet. Add it to the Address row as ZIP: 12345")
        elif re.search(r"^email", question, re.I):
            _fill_blank(page, '[id$="--email"]', value, report, "email")
        elif re.search(r"^country$", question, re.I):
            _choose_field(page, r"^country", [value], report, "Country")
    name = short(info.get("Legal name", ""))
    if name and " " in name:
        first, last = name.split(" ", 1)
        for selector, value in (('[id$="--firstName"]', first), ('[id$="--lastName"]', last)):
            box = page.locator(selector)
            if box.count() and not box.first.input_value():
                box.first.fill(value)
                report.filled.append(f"name: {value}")
    phone = re.sub(r"\D", "", info.get("Phone number", ""))
    box = page.locator('[id$="--phoneNumber"]')
    if phone and box.count() and not box.first.input_value():
        box.first.fill(phone)
        report.filled.append("phone")


def fill_questions(page, questions: dict[str, str], report: Report) -> None:
    """Match each question on the page to the sheet by its words. Unmatched ones, and the sheet's asks, are left for you."""
    from .fill import is_ask
    fields = page.locator('[data-automation-id^="formField-"]')
    for i in range(fields.count()):
        box = fields.nth(i)
        label = (box.locator("label").first.inner_text() if box.locator("label").count() else box.inner_text().split("\n")[0]).strip(" *")
        if not label:
            continue
        found = match_question(label, questions)
        if not found:
            report.skipped.append(f"question not on the sheet: {label[:90]}")
            continue
        question, answer = found
        if is_ask(answer):
            report.skipped.append(f"yours to answer: {label[:90]}")
            continue
        value = short(answer)
        button = box.locator("button")
        radios = box.get_by_role("radio")
        if button.count():
            choose(page, button.first, [value, answer], report, label[:60])
        elif radios.count():
            radio = radios.filter(has_text=re.compile(rf"^\s*{_literal(value)}\s*$", re.I))
            if not radio.count():
                radio = box.get_by_role("radio", name=re.compile(rf"^{_literal(value)}$", re.I))
            if radio.count():
                radio.first.check()
                report.filled.append(f"{label[:60]}: {value}")
            else:
                report.skipped.append(f"{label[:60]}: no choice called {value!r}")
        elif box.locator("textarea").count():
            box.locator("textarea").first.fill(answer)
            report.filled.append(label[:60])
        elif box.locator('input[type="text"]').count():
            if len(value) > 80:
                report.skipped.append(f"{label[:60]}: the sheet's answer reads like advice, not a value, so it's yours to type")
                continue
            box.locator('input[type="text"]').first.fill(value)
            report.filled.append(f"{label[:60]}: {value}")
        else:
            report.skipped.append(f"{label[:60]}: a kind of field this can't fill")


def _texts(locator) -> list[str]:
    """A locator's texts, or nothing while the page is between navigations, as it is during a sign-in."""
    try:
        return locator.all_inner_texts()
    except Exception:
        return []


def current_step(page) -> str:
    headings = [t.strip() for t in _texts(page.get_by_role("heading"))]
    # The review page repeats every section under its own heading, so a review or disclosures heading anywhere wins.
    for text in headings:
        if re.match(r"review|voluntary|self.?identif", text, re.I):
            return text
    for text in headings:
        for step in STEPS:
            if text.lower().startswith(step.lower()):
                return step
    return ""


def page_errors(page) -> list[str]:
    """What Workday says is wrong with the page, if it refused to save it."""
    found = _texts(page.locator('[data-automation-id="errorMessage"], [role="alert"]'))
    # An upload's "successfully uploaded" is announced the same way as an error, and isn't one.
    return list(dict.fromkeys(t.strip() for t in found if t.strip() and not re.search(r"success", t, re.I)))


def press_next(page, report: Report, step: str = "") -> bool:
    """Press the page's save-and-continue button and wait for the next page. False, with the reason, when it didn't turn."""
    button = page.locator(NEXT_BUTTON)
    try:
        present = button.count()
    except Exception:
        report.stopped_at = "the browser, which was closed"
        return False
    if not present:
        report.stopped_at = "a page with no continue button"
        return False
    text = button.first.inner_text().strip()
    if not is_safe_button(text):
        report.stopped_at = f"the {text!r} button, which is yours to press"
        return False
    button.first.click()
    deadline = time.monotonic() + PAGE_TURN_MS / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(500)
        if current_step(page) != step:
            page.wait_for_timeout(SETTLE_MS)
            return True
        errors = page_errors(page)
        if errors:
            report.stopped_at = f"{step}: Workday wouldn't save it. It says: " + "; ".join(errors)[:400]
            return False
    if step:
        report.stopped_at = f"{step}: the page didn't turn after saving"
        return False
    return True


COOKIES = "cookies.json"


def save_cookies(context, profile: Path) -> None:
    """Keep the sign-ins. Workday's are session cookies, which the browser drops on close, so they're kept here instead.

    Only Workday's own: the file is plain text, and another site's session, such as an SSO sign-in, has no business in it.
    """
    try:
        kept = [c for c in context.cookies() if is_workday("https://" + str(c.get("domain", "")).lstrip("."))]
        (profile / COOKIES).write_text(json.dumps(kept), encoding="utf-8")
    except Exception:
        pass  # Losing the kept sign-ins only means signing in again next time.


def restore_cookies(context, profile: Path, report: Report) -> bool:
    """Put the kept sign-ins back. True when there were any to put back."""
    path = profile / COOKIES
    if not path.exists():
        return False
    try:
        cookies = json.loads(path.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        return bool(cookies)
    except Exception as err:
        report.say(f"Couldn't restore the last sign-ins: {err}")
        return False


def asks_to_sign_in(page) -> bool:
    """Whether the page that came up is a sign-in form rather than the application."""
    try:
        page.wait_for_load_state("networkidle", timeout=PAGE_TURN_MS)
    except Exception:
        pass  # The check below reads whatever has loaded.
    try:
        return not current_step(page) and page.locator('input[type="password"]:visible').count() > 0
    except Exception:
        return False


def hold_open(context, report: Report, wait_ms: int = 2000) -> None:
    """Keep the browser up until its window is closed, by looking rather than waiting for a close event: a window closed
    during the fill has already had its event, and a wait for the next one would never end."""
    report.say("The browser stays open. Close its window when you're done.")
    strikes = 0
    while strikes < 5:
        try:
            pages = context.pages
            if not pages:
                return
            pages[-1].wait_for_timeout(wait_ms)
            strikes = 0
        except Exception:
            strikes += 1
            time.sleep(wait_ms / 2000)


def wait_for_turn(page, step: str, context) -> bool:
    """Wait for the candidate to move the form past `step` themselves. False if they don't within the sign-in allowance."""
    for _ in range(SIGN_IN_MINUTES * 30):
        if not context.pages:
            return False
        now = current_step(context.pages[-1])
        if now and now != step:
            return True
        try:
            page.wait_for_timeout(2000)
        except Exception:
            time.sleep(2)
    return False


def run(data: dict, url: str, root: Path, pause: bool = True, report: Report | None = None, on_filled=None) -> Report:
    """Open the application in a browser the candidate signs in to, fill what the sheet answers, and stop before Submit.

    `on_filled(report)` is called once the filling is over and before the browser is held open for the candidate.
    """
    if not is_workday(url):
        raise ValueError(f"Not a Workday page, so nothing is filled: {url!r}. Autofill only types into https pages on "
                         f"{' or '.join(WORKDAY_DOMAINS)}.")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as err:
        raise SystemExit("Playwright isn't installed. Run `python -m pip install playwright` and `python -m playwright install chromium` in the venv.") from err
    report = report or Report()
    overrides = load_skill_overrides(root)
    profile = root / PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)
    # Straight into the form, past the Apply menu: Workday's own address for "Apply Manually". A sign-in, if needed, comes first.
    if "/apply" not in url:
        url = url.rstrip("/") + "/apply/applyManually"
    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(str(profile), headless=False, viewport={"width": 1100, "height": 900})
        # A field that isn't there should be noticed in seconds, not half a minute.
        context.set_default_timeout(8000)
        restored = restore_cookies(context, profile, report)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        if restored and asks_to_sign_in(page):
            # The kept sign-in has lapsed on Workday's side. Its cookies go before the candidate signs in, so the fresh
            # session isn't muddled by the old one, which otherwise leaves a page that needs a refresh after signing in.
            report.say("The kept sign-in has lapsed, so it's cleared. Sign in afresh on the page.")
            context.clear_cookies()
            page.reload()
        report.say("Sign in on the Workday page and open the application form. Waiting for the first page of the form.")
        for _ in range(SIGN_IN_MINUTES * 30):
            # A sign-in may open the form in a new tab; the newest one is where the candidate is.
            if context.pages:
                page = context.pages[-1]
            # A sign-in can pass through another site's page; only a form on Workday's own host counts.
            if is_workday(page.url) and current_step(page):
                break
            try:
                page.wait_for_timeout(2000)
            except Exception:
                time.sleep(2)
        else:
            report.stopped_at = "the sign-in: the form never appeared"
            if on_filled:
                on_filled(report)
            context.close()
            return report
        seen: set[str] = set()
        while True:
            if not context.pages:
                report.stopped_at = "the browser, which was closed"
                break
            page = context.pages[-1]
            if not is_workday(page.url):
                report.stopped_at = f"a page off Workday ({urlparse(page.url).hostname or page.url}), so nothing was typed there"
                break
            step = current_step(page)
            if not step or step in seen or step not in STEPS:
                report.stopped_at = step or "a page this doesn't know"
                break
            seen.add(step)
            report.say(f"On {step}.")
            settle(page)
            save_cookies(context, profile)
            try:
                if step == "Autofill with Resume":
                    report.say("Skipping Workday's resume parse: the sheet is typed in instead.")
                elif step == "My Information":
                    fill_information(page, data.get("info", {}), report, data.get("job", {}).get("source", ""), data.get("job", {}).get("company", ""))
                elif step == "My Experience":
                    fill_experience(page, data, report, overrides)
                elif step == "Application Questions":
                    fill_questions(page, data.get("questions", {}), report)
            except Exception as err:
                report.skipped.append(f"{step}: stopped on an error, so finish it by hand: {str(err).splitlines()[0][:160]}")
            if pause and step != "Autofill with Resume":
                answer = ask(f"{step} is filled. Look it over in the browser, then press Enter here to save and continue, or type q to stop: ")
                if answer.strip().lower().startswith("q"):
                    report.stopped_at = f"{step}, at your request"
                    break
            if not is_workday(page.url):  # The page moved while it was being filled.
                report.stopped_at = f"{step}: the page left Workday ({urlparse(page.url).hostname or page.url}), so it wasn't saved"
                break
            if press_next(page, report, step):
                continue
            if "wouldn't save" not in report.stopped_at and "didn't turn" not in report.stopped_at:
                break
            # Workday wants something only the candidate can give, whether or not it said what. Wait for them to fill it
            # and turn the page, then carry on with the next one.
            report.say(f"{report.stopped_at}")
            report.say("Finish that page in the browser and click Save and Continue there. Waiting to carry on with the next page.")
            report.stopped_at = ""
            if not wait_for_turn(page, step, context):
                report.stopped_at = f"{step}: waited {SIGN_IN_MINUTES} minutes for you to finish the page"
                break
        report.say(f"Stopped at {report.stopped_at}.")
        report.say("The rest is yours: answer what's left, read the review page, and click Submit yourself.")
        for line in report.filled:
            report.say(f"  filled: {line}")
        for line in report.skipped:
            report.say(f"  left for you: {line}")
        for line in report.decisions:
            report.say(f"  check this pick: {line}")
        save_cookies(context, profile)
        if on_filled:
            on_filled(report)
        if pause:
            while ask("The browser stays open until you type close here and press Enter: ").strip().lower() != "close":
                report.say("Still open.")
        else:
            hold_open(context, report)
        try:
            context.close()
        except Exception:
            pass  # The browser may already be gone, closed by you.
    return report


def load_sheet(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sheet", type=Path, help="a job's fill-sheet.json")
    ap.add_argument("--url", default="", help="the posting or apply page; defaults to the sheet's")
    ap.add_argument("--no-pause", action="store_true", help="don't wait for a look at each page before saving it")
    args = ap.parse_args(argv)
    data = load_sheet(args.sheet)
    url = args.url or data.get("job", {}).get("url", "")
    if not url:
        sys.exit("No URL: pass --url.")
    report = run(data, url, store.ROOT, pause=not args.no_pause)
    print(report.summary())


if __name__ == "__main__":
    main()
