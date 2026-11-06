"""Write an interview prep brief on request: Claude drafts it, and the fact checker decides whether it stays.

The limits are the ones a resume refresh has. The posting is untrusted text from the internet, so this
Claude gets no shell and no web access, and can only write the brief. A brief that doesn't pass is thrown
away, and an earlier brief goes back. State lives in the job's events.
"""
import json
import time
from pathlib import Path

from . import checks, claude_code
from .claude_code import ClaudeFailed, find_claude, sign_in_help, spawn_worker
from .cli import _collect_files, write_posting
from .store import IS_EXAMPLE, ROOT, get_job, log_event

STARTED, DONE, FAILED = "prep_started", "prep_done", "prep_failed"
STATE_NAMES = {STARTED: "running", DONE: "done", FAILED: "failed"}
# From the first reply on, a conversation with the employer is coming.
PREPPABLE = ("responded", "interviewing")
BRIEF = "interview-prep.md"
ATTEMPTS = 3
TIME_LIMIT_MINUTES = 20
STALE_MINUTES = TIME_LIMIT_MINUTES + 5
INSTRUCTIONS = Path(__file__).parent / "interview_prep.md"


def states(conn) -> dict[int, dict]:
    """Each job's latest interview prep run, by job id."""
    return claude_code.latest(conn, STATE_NAMES, STALE_MINUTES, "The run stopped without finishing, so no new brief was kept.")


def refusal(conn, job) -> str | None:
    """Why this job can't have a brief written right now, if there's a reason."""
    if IS_EXAMPLE:
        return "The demo doesn't run Claude. In your own workspace, this writes a brief and runs the assay over it."
    if job["status"] not in PREPPABLE:
        return "Interview prep is for a job you've heard back from. Use Got a reply or Interview first."
    if not job["app_folder"] or not (ROOT / job["app_folder"] / "resume.md").exists():
        return "This job has no application folder with a resume, so there's nothing to prepare from."
    if states(conn).get(job["id"], {}).get("state") == "running":
        return "This brief is already being written."
    return None


def begin(conn, job_id: int) -> None:
    """Claim the job, so a double click can't start two runs writing one file."""
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
        raise ValueError("Claude Code wasn't found on this PC, so the brief can't be written.")
    if not claude_code.signed_in(claude):
        raise ValueError(sign_in_help(claude))
    begin(conn, job_id)
    try:
        spawn_worker("prep", job_id, ROOT)
    except OSError as err:
        log_event(conn, job_id, FAILED, f"Couldn't start: {err}")
        conn.commit()
        raise ValueError(f"Couldn't start the interview prep: {err}") from err


def command(claude: str, folder: str) -> list[str]:
    """Claude may read the workspace, and write only this job's brief."""
    return claude_code.command(claude, [f"{folder}/{BRIEF}"])


def prompt(job, folder: str, feedback: str = "") -> str:
    text = INSTRUCTIONS.read_text(encoding="utf-8").replace("{folder}", folder)
    text += claude_code.job_line(job)
    if feedback:
        text += f"\nThe fact checker blocked your last brief. Fix the brief:\n{feedback}\n"
    return text


def _write(conn, cfg, job_id: int, folder: str, claude: str) -> tuple[str, list[str]]:
    """Ask until a brief passes. Returns Claude's summary and the checker's warnings."""
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    brief = ROOT / folder / BRIEF
    sources = checks._read_sources(cfg)
    feedback = ""
    for _ in range(ATTEMPTS):
        job = get_job(conn, job_id)
        summary = claude_code.ask(conn, job_id, "prep", command(claude, folder), prompt(job, folder, feedback),
                                  ROOT, deadline - time.monotonic(), TIME_LIMIT_MINUTES)
        if not brief.exists():
            feedback = f"- You didn't write {folder}/{BRIEF}."
            continue
        errors, warnings = checks.check_brief(
            brief.read_text(encoding="utf-8"), cfg, sources, job["company"], job["title"], job["description"])
        if not errors:
            return summary, warnings
        feedback = "\n".join(f"- {error}" for error in errors)
    raise ClaudeFailed(f"The brief didn't pass the assay after {ATTEMPTS} tries: {feedback}")


def run(conn, cfg, job_id: int, claude: str | None = None) -> bool:
    """Write the brief. On any failure an earlier brief goes back, or none is left. Returns whether it worked."""
    job = get_job(conn, job_id)
    folder = job["app_folder"]
    write_posting(ROOT / folder, job, overwrite=False)
    brief = ROOT / folder / BRIEF
    kept = brief.read_bytes() if brief.exists() else None
    try:
        claude = claude or find_claude()
        if not claude:
            raise ClaudeFailed("Claude Code wasn't found on this PC.")
        summary, warnings = _write(conn, cfg, job_id, folder, claude)
    except Exception as err:  # Anything uncaught here would leave the dashboard saying "writing" for 25 minutes.
        if kept is None:
            brief.unlink(missing_ok=True)
        else:
            brief.write_bytes(kept)
        conn.rollback()
        left = "The earlier brief is still in place." if kept is not None else "No brief was kept."
        log_event(conn, job_id, FAILED, f"{err} {left}"[:1500])
        conn.commit()
        return False
    conn.execute("UPDATE jobs SET files = ? WHERE id = ?", (json.dumps(_collect_files(ROOT / folder)), job_id))
    detail = summary[:500]
    if warnings:
        detail += "\nWorth a look: " + " ".join(warnings)[:800]
    log_event(conn, job_id, DONE, detail)
    conn.commit()
    return True
