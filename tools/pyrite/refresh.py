"""Redo a draft resume on request: Claude rewrites it, and the fact checker decides whether the rewrite stays.

The posting is untrusted text from the internet, so this Claude gets no tools at all: no shell, no web access
and nothing that writes. It hands the rewrite back in its closing message, the code writes the draft's own files,
and Claude never runs the checker or the build. A rewrite that doesn't pass is thrown away and the earlier draft
goes back. State lives in the job's events, so no schema change was needed.
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import checks, claude_code
from .claude_code import ClaudeFailed, NoDocument, find_claude, sign_in_help, spawn_worker
from .cli import finish_job, write_posting
from .store import IS_EXAMPLE, ROOT, get_job, log_event

STARTED, DONE, FAILED = "refresh_started", "refresh_done", "refresh_failed"
STATE_NAMES = {STARTED: "running", DONE: "done", FAILED: "failed"}
# Once you've applied, the resume on file is the one you sent, so it stays as it is.
REFRESHABLE = ("ready", "needs_fix")
PREVIOUS = "resume.previous.md"
DRAFT, NOTES = "resume.md", "notes.md"
ATTEMPTS = 3
TIME_LIMIT_MINUTES = 20
# Claude is never started with less than a minute of the time limit left, but the documents may still be built after
# it: once for the last rewrite, and once more to put the passing one back after a failed polish, each up to five
# minutes. Only past all of that has a run died.
STALE_MINUTES = TIME_LIMIT_MINUTES + 15
INSTRUCTIONS = Path(__file__).parent / "refresh_resume.md"


class RefreshFailed(ClaudeFailed):
    pass


MOVED_ON = "You moved this job on during the refresh, so the resume stays as it was."


def states(conn) -> dict[int, dict[str, Any]]:
    """Each job's latest refresh, by job id."""
    died = f"The run stopped without finishing. Check the resume: the draft from before it started is in {PREVIOUS}."
    return claude_code.latest(conn, STATE_NAMES, STALE_MINUTES, died)


def refusal(conn, job) -> str | None:
    """Why this job's resume can't be refreshed right now, if there's a reason."""
    if IS_EXAMPLE:
        # A real run would spend the visitor's Claude usage and overwrite the deliberately bad sample draft.
        return "The demo doesn't run Claude. In your own workspace, this rewrites the draft and re-runs the assay."
    if job["status"] not in REFRESHABLE:
        return "Only a draft you haven't sent can be refreshed, so the resume on file stays the one you sent."
    if not job["app_folder"] or not (ROOT / job["app_folder"] / "resume.md").exists():
        return "There's no resume to refresh yet. Use Tailor this one first."
    if states(conn).get(job["id"], {}).get("state") == "running":
        return "This resume is already being refreshed."
    return None


def begin(conn, job_id: int) -> None:
    """Claim the job, so a double click can't start two rewrites of one file."""
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    problem = refusal(conn, get_job(conn, job_id))
    if problem:
        conn.rollback()
        raise ValueError(problem)
    log_event(conn, job_id, STARTED)
    conn.commit()


def start(conn, job_id: int) -> None:
    """The dashboard button: check it can work, then run in the background so the page doesn't wait."""
    problem = refusal(conn, get_job(conn, job_id))
    if problem:
        raise ValueError(problem)
    claude = find_claude()
    if not claude:
        raise ValueError("Claude Code wasn't found on this PC, so the resume can't be refreshed.")
    if not claude_code.signed_in(claude):
        raise ValueError(sign_in_help(claude))
    begin(conn, job_id)
    try:
        spawn_worker("refresh", job_id, ROOT)
    except OSError as err:
        log_event(conn, job_id, FAILED, f"Couldn't start: {err}")
        conn.commit()
        raise ValueError(f"Couldn't start the refresh: {err}") from err


def command(claude: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """No tools: everything Claude needs is in the prompt, and the rewrite comes back in its closing message."""
    return claude_code.command(claude, [], cfg)


def prompt(job, folder: str, feedback: str = "", polish: str = "", unusable: bool = False) -> str:
    """The instructions and the files. `feedback` is the checker's errors, or with `unusable`, why the last answer was no use."""
    text = INSTRUCTIONS.read_text(encoding="utf-8").replace("{folder}", folder)
    text += claude_code.files_section(ROOT, folder, (DRAFT, NOTES))
    text += claude_code.job_line(job) + f"Today is {datetime.now().date().isoformat()}.\n"
    if feedback:
        heading = "Your last answer couldn't be used:" if unusable else "The fact checker blocked your last draft. Fix the draft:"
        text += f"\n{heading}\n{feedback}\n"
    if polish:
        text += f"\n{checks.POLISH_ASK}\n{polish}\n"
    return text + claude_code.hand_back(DRAFT, (NOTES,))


def _ask(conn, cfg, job_id: int, folder: str, claude: str, text: str, deadline: float) -> str:
    """One run, its rewrite saved in the folder. Returns Claude's sentence for the dashboard.

    An answer with no resume in it counts as a failed run and raises NoDocument, leaving the files as they were. So
    does moving the job on while Claude wrote, since the resume on file is then the one you sent.
    """
    answer = claude_code.ask(conn, job_id, "refresh", command(claude, cfg), text, ROOT, deadline - time.monotonic(), TIME_LIMIT_MINUTES)
    try:
        found, summary = claude_code.documents(answer, DRAFT, (NOTES,))
    except NoDocument:
        claude_code.mark_failed(conn, answer)
        raise
    if get_job(conn, job_id)["status"] not in REFRESHABLE:
        raise RefreshFailed(MOVED_ON)
    claude_code.save_documents(ROOT / folder, found)
    return summary


def _polish(conn, cfg, job_id: int, folder: str, claude: str, report: dict[str, Any], deadline: float) -> None:
    """One more pass over a rewrite that passed with warnings it can clear. The letter isn't this run's to change,
    so its warnings are left alone. If the pass fails the assay, the rewrite that passed goes back."""
    asks = checks.polish_requests(report, letter=False)
    if not asks or deadline - time.monotonic() < claude_code.MIN_ASK_SECONDS:
        return
    files = [ROOT / folder / name for name in (DRAFT, NOTES)]
    kept = {path: path.read_bytes() for path in files if path.exists()}
    try:
        text = prompt(get_job(conn, job_id), folder, polish="\n".join(f"- {ask}" for ask in asks))
        _ask(conn, cfg, job_id, folder, claude, text, deadline)
        if finish_job(conn, cfg, job_id)["ok"]:
            return
    except ClaudeFailed:
        pass  # Moving the job on meanwhile lands here too, before anything was saved.
    for path, content in kept.items():
        path.write_bytes(content)
    if get_job(conn, job_id)["status"] in REFRESHABLE:
        finish_job(conn, cfg, job_id)  # A sent job's folder is a record, so it isn't rebuilt.


def _rewrite(conn, cfg, job_id: int, folder: str, claude: str) -> str:
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    feedback = ""
    missing: NoDocument | None = None
    for _ in range(ATTEMPTS):
        job = get_job(conn, job_id)
        try:
            summary = _ask(conn, cfg, job_id, folder, claude, prompt(job, folder, feedback, unusable=missing is not None), deadline)
        except NoDocument as err:
            missing = err
            feedback = f"- Your answer had no {DRAFT} block, so nothing was saved. Hand back the whole resume, as the end of these instructions says."
            continue
        missing = None
        report = finish_job(conn, cfg, job_id)
        if report["ok"]:
            _polish(conn, cfg, job_id, folder, claude, report, deadline)
            return summary
        if any(error.startswith("Build failed") for error in report["errors"]):
            raise RefreshFailed("; ".join(report["errors"]))
        feedback = "\n".join(f"- {error}" for error in report["errors"])
    if missing:
        raise RefreshFailed(f"{missing} It was asked {ATTEMPTS} times.")
    raise RefreshFailed(f"The rewrite didn't pass the assay after {ATTEMPTS} tries: {feedback}")


def run(conn, cfg, job_id: int, claude: str | None = None) -> bool:
    """Do the rewrite. On any failure the earlier draft and its documents go back. Returns whether it worked."""
    job = get_job(conn, job_id)
    write_posting(ROOT / job["app_folder"], job, overwrite=False)
    folder = job["app_folder"]
    resume, notes = ROOT / folder / "resume.md", ROOT / folder / "notes.md"
    kept = {path: path.read_bytes() for path in (resume, notes) if path.exists()}
    (ROOT / folder / PREVIOUS).write_bytes(kept[resume])
    try:
        claude = claude or find_claude()
        if not claude:
            raise RefreshFailed("Claude Code wasn't found on this PC.")
        summary = _rewrite(conn, cfg, job_id, folder, claude)
    except Exception as err:  # Anything uncaught here would leave the dashboard saying "refreshing" for 25 minutes.
        rewritten = resume.read_bytes() != kept[resume]
        for path, content in kept.items():
            path.write_bytes(content)
        conn.rollback()
        detail = f"{err} The earlier draft is still in place."
        try:
            if rewritten:
                finish_job(conn, cfg, job_id)
        except Exception as rebuild:
            detail += f" Its documents couldn't be rebuilt: {rebuild}"
        log_event(conn, job_id, FAILED, detail[:1500])
        conn.commit()
        return False
    unchanged = resume.read_bytes() == kept[resume]
    log_event(conn, job_id, DONE, "Claude left the resume as it was." if unchanged else summary[:500] or "Rewrote the resume.")
    conn.commit()
    return True
