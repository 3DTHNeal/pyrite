"""The Claude run, driven by code: Claude judges and writes, and this module does everything else.

A posting is untrusted text from the internet, so Claude never gets a shell here. Each posting is judged
by its own run that has no tools at all. Each application is written by a run that can change only that
application's own files. Recording verdicts, making folders, building documents and running the fact
checker all happen in this code, so no instruction in a posting can reach them.
"""
import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

from . import checks, claude_code, confirm, discover, signals, skillage
from .claude_code import ClaudeFailed, find_claude
from .cli import BOARD_FIELDS, apply_triage, ensure_folder, finish_job, queue
from .store import ROOT, get_job, log_event, now, shorten

FITS = ("strong", "good", "stretch", "skip")
# A first draft and two fixes, as the instructions for a hand-run session allow.
ATTEMPTS = 3
ASK_MINUTES = claude_code.ASK_MINUTES
TIME_LIMIT_MINUTES = 120
TAILORING = ("shortlisted", "needs_fix")
TRIAGE_INSTRUCTIONS = Path(__file__).parent / "triage.md"
TAILOR_INSTRUCTIONS = Path(__file__).parent / "tailor.md"
LETTER_SECTION = """## `{folder}/cover-letter.md`

Follow the model letter: same header, today's date, 220 to 320 words in three or four short paragraphs. Half of recruiters never read a letter and most hiring managers do, so write for the hiring manager: open by naming the role and one thing only this company could receive, give two or three concrete pieces of evidence with numbers, bridge the one or two gaps that matter most in a sentence each with no apology, and close with the problem the candidate would want to own and a low-friction ask. No "I am excited to apply". A gap goes in a letter only if `facts.md` confirms it or it follows from the dates on the resume. Never state a negative just because the record is silent, since the candidate may have done the thing. Refer only to things the posting actually says about the company.

Word a gap so the sentence plainly denies it: "I have not worked under that standard", or "the posting lists it as a plus, and I have not done it". The checker blocks a sentence that names an unsupported claim without such a denial, and warns above 350 words.

"""
# The whole reason is kept, and cards and tables shorten it for themselves. This only stops a runaway reply.
REASON_LIMIT = 2000
VERDICT = re.compile(r"\{[^{}]*\}")
UNSAFE_TEXT = re.compile(r"[\s\x00-\x1f\x7f-\x9f]+")


class NotSignedIn(ClaudeFailed):
    """Nothing else in the run can work either, so it stops here."""


class ProfileChanged(ClaudeFailed):
    """Something under profile/ changed while Claude was writing. Every draft is checked against the fact bank there,
    so the run stops rather than check any more of them against something it didn't start with.

    `problem` is what the run's record keeps, so the dashboard can name the files and let you say the change was yours."""

    def __init__(self, message: str, job_id: int | None = None, files: list[str] | None = None):
        super().__init__(message)
        self.problem = {"kind": claude_code.PROFILE_CHANGED, "job_id": job_id, "files": list(files or ())}


# The profile files whose changes can let drafts say more, by the names confirm.loosening knows them by.
LOOSENING = {"profile/facts.md": "facts", "profile/approved-terms.txt": "terms", "profile/search.toml": "config"}


def parse_verdict(message: str) -> tuple[str, str] | None:
    """The fit and reason from Claude's reply, or None if it didn't give a usable one. The last JSON object wins."""
    found = None
    for match in VERDICT.finditer(message or ""):
        try:
            data = json.loads(match.group(0))
        except ValueError:
            continue
        fit, reason = data.get("fit"), data.get("reason")
        if fit in FITS and isinstance(reason, str) and reason.strip():
            found = (fit, shorten(UNSAFE_TEXT.sub(" ", reason).strip(), REASON_LIMIT))
    return found


def markings(marks: dict[str, Any] | None) -> str:
    """Pyrite's own read of a listing: whether it may be a ghost, any scam signs in its text, its deadline, what its pay
    says and whether it's rare nearby, then how old the skills it asks for are. The code words these from the listing's
    dates, reposts, fixed patterns and its own tables, so they go outside the posting's fence."""
    if not marks:
        return ""
    ghost = f"yes, {marks.get('ghost_reason') or 'from its dates and reposts'}" if marks.get("ghost_risk") else "no"
    scam = ", ".join(str(sign) for sign in marks.get("scam_signs") or ()) or "none"
    more = "".join(f"{line}\n" for line in signals.markings(marks))
    return ("\n\n## Pyrite's markings\n\nFrom Pyrite's own checks of this listing's dates, reposts and wording, not from the job board:\n\n"
            f"- Possible ghost: {ghost}\n- Scam signs: {scam}\n{more}" + skillage.prompt_section(marks))


def triage_prompt(job, marks: dict[str, Any] | None = None) -> str:
    board = {key: job[key] for key in BOARD_FIELDS}
    # Triage runs with no tools, so a posting can't steer it into reading anything: the two files it judges by come with it.
    return (TRIAGE_INSTRUCTIONS.read_text(encoding="utf-8") + claude_code.profile_section(ROOT, claude_code.PROFILE_FILES[:2])
            + markings(marks) + claude_code.job_line(job) + "\n"
            + claude_code.posting_block(board, job["description"]) + "\n")


def tailor_files(folder: str, cfg: dict[str, Any]) -> list[str]:
    """The only files a tailoring run may change."""
    names = ["resume.md", "notes.md"] + (["cover-letter.md"] if cfg["run"].get("cover_letters", True) else [])
    return [f"{folder}/{name}" for name in names]


def tailor_prompt(job, folder: str, cfg: dict[str, Any], feedback: str = "", polish: str = "") -> str:
    letters = cfg["run"].get("cover_letters", True)
    files = " and ".join(f"`{path}`" for path in tailor_files(folder, cfg))
    text = TAILOR_INSTRUCTIONS.read_text(encoding="utf-8").replace("{letter_section}", LETTER_SECTION if letters else "")
    text = text.replace("{files}", files).replace("{folder}", folder)
    today = date.today()
    text += claude_code.files_section(ROOT, folder, tuple(path.rsplit("/", 1)[1] for path in tailor_files(folder, cfg)))
    text += claude_code.job_line(job) + f"Today is {today:%B} {today.day}, {today.year}.\n"
    text += skillage.prompt_section(skillage.signals(job["description"] or "", today))
    if feedback:
        text += f"\nThe fact checker blocked your last draft. Fix the draft:\n{feedback}\n"
    if polish:
        text += f"\n{checks.POLISH_ASK}\n{polish}\n"
    return text


def _ask(conn, job_id: int, kind: str, cmd: list[str], text: str, deadline: float) -> str:
    seconds = min(ASK_MINUTES * 60, deadline - time.monotonic())
    try:
        return claude_code.ask(conn, job_id, kind, cmd, text, ROOT, seconds, ASK_MINUTES)
    except ClaudeFailed as err:
        if "auth login" in str(err):
            raise NotSignedIn(str(err)) from err
        raise


def judge(conn, job_id: int, claude: str, deadline: float, marks: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> str | None:
    """Have Claude judge one posting, and record the verdict here. Returns the fit, or None if it couldn't be judged.

    `marks` is the posting as the queue ranked it, whose ghost and scam markings go to Claude with it. `cfg` is
    search.toml, for the model and effort it names."""
    job = get_job(conn, job_id)
    if job["status"] != "new" or not job["description"].strip():
        return None  # Moved on meanwhile, or nothing to read. An empty posting is left for you.
    reply = _ask(conn, job_id, "triage", claude_code.command(claude, [], cfg), triage_prompt(job, marks), deadline)
    verdict = parse_verdict(reply)
    if not verdict or get_job(conn, job_id)["status"] != "new":
        return None
    apply_triage(conn, job_id, *verdict)
    conn.commit()
    return verdict[0]


def _keep(files: list[Path]) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in files if path.exists()}


def _put_back(files: list[Path], kept: dict[Path, bytes]) -> None:
    """The drafts as they were before a run, with any file the run added taken away again."""
    for path in files:
        if path in kept:
            path.write_bytes(kept[path])
        elif path.exists():
            path.unlink()


def _text(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")


def _profile_unchanged(conn, job_id: int, profile: dict[str, bytes], files: list[Path], kept: dict[Path, bytes]) -> None:
    """Raise ProfileChanged, with what this run wrote undone, if anything under profile/ changed since `profile`.

    The message names the files and what the change lets drafts say that they couldn't before, so you can tell your own
    edit from one you didn't make. The job's timeline keeps it too."""
    now_there = claude_code.profile_snapshot(ROOT)
    changed = claude_code.profile_changes(profile, now_there)
    if not changed:
        return
    _put_back(files, kept)
    loosens = [phrase for path in changed if path in LOOSENING
               for phrase in confirm.loosening(LOOSENING[path], _text(profile.get(path)), _text(now_there.get(path)))]
    company = get_job(conn, job_id)["company"]
    files_said = claude_code.some(changed)
    said = (f"{files_said} changed while Claude was writing the {company} draft, so the run stopped and that draft went "
            "back as it was.")
    if loosens:
        said += f" The change will {claude_code.some(loosens)}."
    said += " If you made this change, say so. If you didn't, look it over before tailoring again."
    log_event(conn, job_id, claude_code.PROFILE_CHANGED,
              f"{files_said} changed while Claude was writing this draft, so the run stopped and the draft went back as it was.")
    conn.commit()
    raise ProfileChanged(said, job_id, changed)


def _time_left(deadline: float) -> bool:
    return deadline - time.monotonic() >= claude_code.MIN_ASK_SECONDS


def tailor(conn, cfg: dict[str, Any], job_id: int, claude: str, deadline: float, say=lambda step: None) -> bool:
    """Have Claude write one application, and let the fact checker decide. Returns whether it's ready.

    `say` hears each step before it starts, so a long job keeps showing signs of life on the dashboard."""
    folder = ensure_folder(conn, job_id)
    cmd = claude_code.command(claude, tailor_files(folder, cfg), cfg)
    files = [ROOT / path for path in tailor_files(folder, cfg)]
    profile = claude_code.profile_snapshot(ROOT)
    feedback = ""
    for attempt in range(1, ATTEMPTS + 1):
        job = get_job(conn, job_id)
        if job["status"] not in TAILORING or job["applied_at"] or not _time_left(deadline):
            return False  # You moved it on or sent it, or time ran out. Either way it's left as it is.
        kept = _keep(files)
        say(f"writing draft {attempt}")
        _ask(conn, job_id, "tailor", cmd, tailor_prompt(job, folder, cfg, feedback), deadline)
        _profile_unchanged(conn, job_id, profile, files, kept)
        if get_job(conn, job_id)["status"] not in TAILORING:
            _put_back(files, kept)  # You moved it on while Claude wrote, so what it wrote, unchecked, is undone.
            return False
        say(f"checking draft {attempt}")
        report = finish_job(conn, cfg, job_id)
        if report["ok"]:
            polish(conn, cfg, job_id, folder, cmd, report, deadline, profile, say)
            return True
        if any(error.startswith("Build failed") for error in report["errors"]):
            return False  # Not something a rewrite can fix.
        feedback = "\n".join(f"- {error}" for error in report["errors"])
    return False


def polish(conn, cfg: dict[str, Any], job_id: int, folder: str, cmd: list[str], report: dict[str, Any], deadline: float, profile: dict[str, bytes],
           say=lambda step: None) -> None:
    """One more pass over a draft that passed with warnings a rewrite can clear, such as a letter naming unapproved
    terms or a resume that copies the posting's skill terms. Unless that pass passes the assay, the passing draft goes
    back: when it fails, when Claude does, when you move the job on meanwhile, and when anything else goes wrong."""
    asks = checks.polish_requests(report, letter=cfg["run"].get("cover_letters", True))
    if not asks or not _time_left(deadline):
        return
    files = [ROOT / path for path in tailor_files(folder, cfg)]
    kept = _keep(files)
    failure: Exception | None = None
    try:
        text = tailor_prompt(get_job(conn, job_id), folder, cfg, polish="\n".join(f"- {ask}" for ask in asks))
        say("clearing the assay's warnings")
        _ask(conn, job_id, "tailor", cmd, text, deadline)
        _profile_unchanged(conn, job_id, profile, files, kept)
        if get_job(conn, job_id)["status"] == "ready":
            say("checking the cleared draft")
            if finish_job(conn, cfg, job_id)["ok"]:
                log_event(conn, job_id, "polished", "Passed the assay with warnings, so one more pass cleared what it could: " + "; ".join(asks)[:400])
                conn.commit()
                return
    except Exception as err:  # Whatever it was, the draft that passed goes back first.
        failure = err
    _put_back(files, kept)
    if isinstance(failure, ProfileChanged):
        raise failure
    if get_job(conn, job_id)["status"] in ("ready", "needs_fix"):
        say("putting the passing draft back")
        finish_job(conn, cfg, job_id)
        log_event(conn, job_id, "polished", "A pass to clear the assay's warnings failed it instead, so the draft that passed is back.")
    else:
        # A sent job's folder is a record of what went, which is the draft that passed, so nothing is rebuilt.
        log_event(conn, job_id, "polished", "You moved this job on during a pass to clear the assay's warnings, so the draft that passed is back as it was.")
    conn.commit()
    if failure is not None and (isinstance(failure, NotSignedIn) or not isinstance(failure, ClaudeFailed)):
        raise failure


def _count(number: int, one: str, many: str | None = None) -> str:
    return f"{number} {one if number == 1 else many or one + 's'}"


def briefing(judged: dict[str, Any], unjudged: int, ready: list[str], blocked: list[str], failing: list[str], first_reason: str) -> str:
    """The morning briefing, written from what the run did. No model writes it, so no posting can word it."""
    parts = []
    total = sum(judged.values())
    if total:
        parts.append(f"Judged {_count(total, 'new posting')}: {judged['strong']} strong, {judged['good']} good, "
                     f"{judged['stretch']} a stretch and {judged['skip']} skipped.")
    elif not unjudged:
        parts.append("No new postings to judge.")
    if unjudged:
        parts.append(f"{_count(unjudged, 'posting')} couldn't be judged and {'is' if unjudged == 1 else 'are'} still on the radar.")
    if ready:
        parts.append(f"{_count(len(ready), 'resume is', 'resumes are')} ready: {', '.join(ready)}.")
        parts.append(f"Send {ready[0]} first." + (f" {first_reason}" if first_reason else ""))
    if blocked:
        parts.append(f"Blocked by the assay: {', '.join(blocked)}.")
    if not ready and not blocked:
        parts.append("Nothing was waiting to be tailored.")
    if failing:
        parts.append(f"{_count(len(failing), 'source is', 'sources are')} failing: {', '.join(failing)}.")
    return " ".join(parts)


def _research_skills(conn, cfg: dict[str, Any], waiting: list[dict[str, Any]], claude: str, report) -> list[dict[str, Any]] | None:
    """Date the skills these postings ask years of that the table doesn't know, and queue again with what was learned.
    Returns None when there was nothing to look up. A failed lookup costs only itself: the run goes on without it."""
    ids = [job["id"] for job in waiting]
    marks = ",".join("?" * len(ids))
    texts = [row[0] or "" for row in conn.execute(f"SELECT description FROM jobs WHERE id IN ({marks})", ids)] if ids else []
    phrases = skillage.to_research(texts)
    if not phrases:
        return None
    report(f"Looking up how long {_count(len(phrases), 'skill')} in the new postings have existed")
    try:
        skillage.research(conn, cfg, phrases, claude)
    except ClaudeFailed as err:
        if "auth login" in str(err):
            raise NotSignedIn(str(err)) from err
        report(f"Couldn't look up the skills' ages: {err}")
        return None
    return queue(conn, cfg)["to_triage"]


def run(conn, cfg: dict[str, Any], report=lambda text: None, claude: str | None = None) -> str:
    """Judge the new postings, tailor the best, and leave a briefing. Returns the briefing."""
    claude = claude or find_claude()
    if not claude:
        raise ClaudeFailed("Claude Code wasn't found on this PC.")
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    judged, unjudged = dict.fromkeys(FITS, 0), 0

    # Nothing past its deadline is worth a judgement or a draft. The sweep passes on these too; this catches a day's turn.
    passed = discover.settle_expired(conn)
    if passed:
        report(f"Passed on {_count(len(passed), 'posting')} whose deadline has gone by.")
    waiting = queue(conn, cfg)["to_triage"]
    if skillage.enabled(cfg):
        waiting = _research_skills(conn, cfg, waiting, claude, report) or waiting
    for index, job in enumerate(waiting, start=1):
        if time.monotonic() > deadline:
            unjudged += 1
            continue
        report(f"Judging posting {index} of {len(waiting)}: {job['company']}")
        try:
            fit = judge(conn, job["id"], claude, deadline, job, cfg)
        except NotSignedIn:
            raise
        except ClaudeFailed:
            fit = None
        if fit:
            judged[fit] += 1
        else:
            unjudged += 1

    # Asked again, since judging has just shortlisted more. A stretch waits unless you picked it yourself.
    found = queue(conn, cfg)
    drafts = [job for job in found["to_tailor"] if job["fit"] != "stretch" or job["priority"]]
    ready: list[str] = []
    blocked: list[str] = []
    first_reason = ""
    for index, job in enumerate(drafts, start=1):
        if time.monotonic() > deadline:
            break
        name = f"{job['company']} ({job['title']})"
        doing = f"Tailoring {index} of {len(drafts)}: {job['company']}"
        report(doing)
        try:
            done = tailor(conn, cfg, job["id"], claude, deadline, lambda step, doing=doing: report(f"{doing}, {step}"))
        except (NotSignedIn, ProfileChanged):
            raise
        except ClaudeFailed:
            done = False
        if done:
            first_reason = first_reason or (job["fit_reason"] if not ready else "")
            ready.append(name)
        elif get_job(conn, job["id"])["status"] == "needs_fix":
            blocked.append(name)

    text = briefing(judged, unjudged, ready, blocked, [row["company"] for row in found["failing"]], first_reason)
    conn.execute("INSERT INTO briefings (ts, body) VALUES (?, ?)", (now(), text))
    conn.commit()
    return text


BATCH_LIMIT = 1000  # a batch takes everything that's waiting, not the daily share


def tailor_batch(conn, cfg: dict[str, Any], report=lambda text: None, claude: str | None = None) -> str:
    """Write every draft waiting under Being tailored, stretch jobs included, and say how it went.

    The Tailor these now button. It judges nothing and leaves no briefing: the drafts land as ready
    or needs_fix like any other, and the summary returned is what the dashboard shows beside the button.
    """
    claude = claude or find_claude()
    if not claude:
        raise ClaudeFailed("Claude Code wasn't found on this PC.")
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    found = queue(conn, cfg, limit=BATCH_LIMIT)
    drafts = found["to_tailor"]
    stuck = len(found["stuck"])
    skipped = f" {stuck} stuck draft{'s' if stuck != 1 else ''} left alone: use Tailor this one first to retry one." if stuck else ""
    if not drafts:
        return "Nothing is waiting to be tailored." + skipped
    ready, blocked, left = [], [], 0
    for index, job in enumerate(drafts, start=1):
        if time.monotonic() > deadline:
            left += 1
            continue
        name = f"{job['company']} ({job['title']})"
        doing = f"Tailoring {index} of {len(drafts)}: {job['company']}"
        report(doing)
        try:
            done = tailor(conn, cfg, job["id"], claude, deadline, lambda step, doing=doing: report(f"{doing}, {step}"))
        except (NotSignedIn, ProfileChanged):
            raise
        except ClaudeFailed:
            done = False
        if done:
            ready.append(name)
        elif get_job(conn, job["id"])["status"] == "needs_fix":
            blocked.append(name)
    said = f"Tailored {len(drafts) - left} of {len(drafts)} waiting draft{'s' if len(drafts) != 1 else ''}: {len(ready)} ready"
    if blocked:
        said += f", {len(blocked)} blocked by the assay ({', '.join(blocked)})"
    if left:
        said += f", {left} not reached before the time limit"
    return said + "." + skipped
