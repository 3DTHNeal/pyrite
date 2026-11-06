"""Redo a draft resume on request: Claude rewrites it, and the fact checker decides whether the rewrite stays.

The posting is untrusted text from the internet, so this Claude gets no shell and no web access, can only
change the draft's own files, and never runs the checker or the build. A rewrite that doesn't pass is thrown
away and the earlier draft goes back. State lives in the job's events, so no schema change was needed.
"""
import time
from datetime import datetime
from pathlib import Path

from . import claude_code
from .claude_code import ClaudeFailed, find_claude, sign_in_help, spawn_worker
from .cli import finish_job, write_posting
from .store import IS_EXAMPLE, ROOT, get_job, log_event

STARTED, DONE, FAILED = "refresh_started", "refresh_done", "refresh_failed"
STATE_NAMES = {STARTED: "running", DONE: "done", FAILED: "failed"}
# Once you've applied, the resume on file is the one you sent, so it stays as it is.
REFRESHABLE = ("ready", "needs_fix")
PREVIOUS = "resume.previous.md"
ATTEMPTS = 3
TIME_LIMIT_MINUTES = 20
STALE_MINUTES = TIME_LIMIT_MINUTES + 5
INSTRUCTIONS = Path(__file__).parent / "refresh_resume.md"


class RefreshFailed(ClaudeFailed):
    pass


def states(conn) -> dict[int, dict]:
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


def command(claude: str, folder: str) -> list[str]:
    """Claude may read the workspace, and change only this draft's resume and notes."""
    return claude_code.command(claude, [f"{folder}/resume.md", f"{folder}/notes.md"])


def prompt(job, folder: str, feedback: str = "") -> str:
    text = INSTRUCTIONS.read_text(encoding="utf-8").replace("{folder}", folder)
    text += claude_code.job_line(job) + f"Today is {datetime.now().date().isoformat()}.\n"
    if feedback:
        text += f"\nThe fact checker blocked your last draft. Fix the draft:\n{feedback}\n"
    return text


def _rewrite(conn, cfg, job_id: int, folder: str, claude: str) -> str:
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    feedback = ""
    for _ in range(ATTEMPTS):
        job = get_job(conn, job_id)
        summary = claude_code.ask(conn, job_id, "refresh", command(claude, folder), prompt(job, folder, feedback),
                                  ROOT, deadline - time.monotonic(), TIME_LIMIT_MINUTES)
        if get_job(conn, job_id)["status"] not in REFRESHABLE:
            raise RefreshFailed("You moved this job on during the refresh, so the resume stays as it was.")
        report = finish_job(conn, cfg, job_id)
        if report["ok"]:
            return summary
        if any(error.startswith("Build failed") for error in report["errors"]):
            raise RefreshFailed("; ".join(report["errors"]))
        feedback = "\n".join(f"- {error}" for error in report["errors"])
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
    log_event(conn, job_id, DONE, "Claude left the resume as it was." if unchanged else summary[:500])
    conn.commit()
    return True
