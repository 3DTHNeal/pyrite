"""Redo a draft resume on request: Claude rewrites it, and the fact checker decides whether the rewrite stays.

The posting is untrusted text from the internet, so this Claude gets no shell and no web access, can only
change the draft's own files, and never runs the checker or the build. A rewrite that doesn't pass is thrown
away and the earlier draft goes back. State lives in the job's events, so no schema change was needed.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .cli import finish_job, write_posting
from .store import CODE_ROOT, IS_EXAMPLE, ROOT, get_job, log_event

STARTED, DONE, FAILED = "refresh_started", "refresh_done", "refresh_failed"
STATE_NAMES = {STARTED: "running", DONE: "done", FAILED: "failed"}
# Once you've applied, the resume on file is the one you sent, so it stays as it is.
REFRESHABLE = ("ready", "needs_fix")
PREVIOUS = "resume.previous.md"
ATTEMPTS = 3
TIME_LIMIT_MINUTES = 20
# Past this a run must have died, for instance when the PC went to sleep or restarted.
STALE_MINUTES = TIME_LIMIT_MINUTES + 5
INSTRUCTIONS = Path(__file__).parent / "refresh_resume.md"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


class RefreshFailed(Exception):
    pass


def find_claude() -> str | None:
    """Claude Code on PATH, or else the newest copy the desktop app keeps."""
    found = shutil.which("claude")
    if found:
        return found
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    installs = sorted(Path(appdata).glob("Claude/claude-code/*/*/claude.exe"), key=lambda p: p.stat().st_mtime)
    return str(installs[-1]) if installs else None


def _signed_in(claude: str) -> bool:
    try:
        out = subprocess.run([claude, "auth", "status"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        return bool(json.loads(out.stdout).get("loggedIn"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return True  # Unsure, so let the run itself report what's wrong.


def states(conn) -> dict[int, dict]:
    """Each job's latest refresh, by job id."""
    kinds = tuple(STATE_NAMES)
    rows = conn.execute(
        f"""SELECT job_id, ts, kind, detail FROM events WHERE id IN (
                SELECT MAX(id) FROM events WHERE kind IN ({", ".join("?" * len(kinds))}) GROUP BY job_id)""",
        kinds,
    ).fetchall()
    found = {}
    for row in rows:
        state, detail = STATE_NAMES[row["kind"]], row["detail"]
        minutes = (datetime.now(timezone.utc) - datetime.fromisoformat(row["ts"])).total_seconds() / 60
        if state == "running" and minutes > STALE_MINUTES:
            state = "failed"
            detail = f"The run stopped without finishing. Check the resume: the draft from before it started is in {PREVIOUS}."
        found[row["job_id"]] = {"state": state, "at": row["ts"], "detail": detail}
    return found


def refusal(conn, job) -> str | None:
    """Why this job's resume can't be refreshed right now, if there's a reason."""
    if IS_EXAMPLE:
        # A real run would spend the visitor's Claude usage and overwrite the deliberately bad sample draft.
        return "The demo doesn't run Claude. In your own workspace, this rewrites the draft and re-runs the fact checker."
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
    if not _signed_in(claude):
        raise ValueError(f'Claude Code isn\'t signed in for background use. Run this once in a terminal: "{claude}" auth login')
    begin(conn, job_id)
    try:
        # Its own process, so restarting the dashboard doesn't kill a rewrite halfway through.
        subprocess.Popen(
            [sys.executable, str(CODE_ROOT / "tools" / "wr.py"), "refresh", str(job_id), "--worker"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW | NEW_GROUP,
        )
    except OSError as err:
        log_event(conn, job_id, FAILED, f"Couldn't start: {err}")
        conn.commit()
        raise ValueError(f"Couldn't start the refresh: {err}") from err


def command(claude: str, folder: str) -> list[str]:
    """Reading and writing only. dontAsk refuses anything these rules don't allow, and user settings can't widen them."""
    return [
        claude, "-p", "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "project",
        "--permission-mode", "dontAsk", "--max-turns", "30",
        "--tools", "Read,Write,Edit",
        "--allowedTools", f"Edit(./{folder}/resume.md),Edit(./{folder}/notes.md)",
        "--disallowedTools", "Read(./data/**)",
    ]


def prompt(job, folder: str, feedback: str = "") -> str:
    text = INSTRUCTIONS.read_text(encoding="utf-8").replace("{folder}", folder)
    text += f"\n\nThe job: {job['company']}, {job['title']}. Today is {datetime.now().date().isoformat()}.\n"
    if feedback:
        text += f"\nThe fact checker blocked your last draft. Fix the draft:\n{feedback}\n"
    return text


def _ask_claude(claude: str, folder: str, text: str, seconds: float) -> str:
    try:
        out = subprocess.run(
            command(claude, folder), input=text, cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
            timeout=max(seconds, 1), creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired as err:
        raise RefreshFailed(f"Claude hadn't finished after {TIME_LIMIT_MINUTES} minutes.") from err
    except OSError as err:
        raise RefreshFailed(f"Couldn't run Claude Code: {err}") from err
    message = (out.stdout or out.stderr or "").strip()
    if out.returncode:
        if "not logged in" in message.lower():
            raise RefreshFailed(f'Claude Code isn\'t signed in for background use. Run this once in a terminal: "{claude}" auth login')
        raise RefreshFailed(f"Claude stopped with an error: {message[-500:] or out.returncode}")
    return message


def _rewrite(conn, cfg, job_id: int, folder: str, claude: str) -> str:
    deadline = time.monotonic() + TIME_LIMIT_MINUTES * 60
    feedback = ""
    for _ in range(ATTEMPTS):
        job = get_job(conn, job_id)
        summary = _ask_claude(claude, folder, prompt(job, folder, feedback), deadline - time.monotonic())
        if get_job(conn, job_id)["status"] not in REFRESHABLE:
            raise RefreshFailed("You moved this job on during the refresh, so the resume stays as it was.")
        report = finish_job(conn, cfg, job_id)
        if report["ok"]:
            return summary
        if any(error.startswith("Build failed") for error in report["errors"]):
            raise RefreshFailed("; ".join(report["errors"]))
        feedback = "\n".join(f"- {error}" for error in report["errors"])
    raise RefreshFailed(f"The rewrite didn't pass the fact checker after {ATTEMPTS} tries: {feedback}")


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
