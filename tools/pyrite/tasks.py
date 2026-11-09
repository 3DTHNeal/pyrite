"""Runs you start yourself, from the dashboard or the command line: a sweep, the Claude run, or a tailoring batch.

Each runs in its own process, one of each kind at a time, and reports its progress through the
`tasks` table so the dashboard can show it. The Claude run and the tailoring batch both write
drafts, so only one of those two goes at a time.
"""
import json
from datetime import UTC, datetime

from . import claude_code, discover, doctor, mail
from .claude_code import find_claude, sign_in_help
from .store import IS_EXAMPLE, ROOT, log_event, now

SWEEP, CLAUDE, TAILOR = "sweep", "claude", "tailor"
LABELS = {SWEEP: "pan", CLAUDE: "Claude run", TAILOR: "tailoring batch"}
WRITERS = (CLAUDE, TAILOR)  # both write drafts, so they take turns
# With no word from a run for this long it must have died, for instance when the PC went to sleep or restarted.
# The Claude run and the tailoring batch say what they're doing before every step, and the longest step is one Claude
# run or one build of the documents (five minutes at most), so their limit is that step with room to spare. A limit
# for a whole job would let a long tailoring job look dead while it still writes, and a second writer start beside it.
STEP_MINUTES = claude_code.ASK_MINUTES + 10
STALE_MINUTES = {SWEEP: 60, CLAUDE: STEP_MINUTES, TAILOR: STEP_MINUTES}
DIED = "The run stopped without finishing."


def _minutes_since(iso: str) -> float:
    return (datetime.now(UTC) - datetime.fromisoformat(iso)).total_seconds() / 60


def _problem(row) -> dict | None:
    """What stopped a failed run, in a form the dashboard can act on, when the run said."""
    try:
        found = json.loads(row["problem"]) if row["problem"] else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def latest(conn) -> dict[str, dict]:
    """The latest run of each kind, by kind: its state, when it started and what it last said.

    A failed run you've cleared, by saying the profile change that stopped it was yours, is "cleared" rather than
    "failed", so it no longer counts as a problem."""
    rows = conn.execute("SELECT * FROM tasks WHERE id IN (SELECT MAX(id) FROM tasks GROUP BY kind)").fetchall()
    found = {}
    for row in rows:
        state, detail = "running", row["detail"]
        if row["finished_at"]:
            state = "done" if row["ok"] else "cleared" if row["cleared_at"] else "failed"
        elif _minutes_since(row["updated_at"]) > STALE_MINUTES.get(row["kind"], 60):
            state, detail = "failed", DIED
        found[row["kind"]] = {"id": row["id"], "state": state, "started_at": row["started_at"],
                              "finished_at": row["finished_at"], "detail": detail, "problem": _problem(row),
                              "cleared_at": row["cleared_at"]}
    return found


def accept_profile_change(conn, task_id: int) -> str:
    """Say the profile change that stopped this writing run was yours. That one warning clears, and the job whose draft
    went back keeps on its timeline that you said so. No file changes here, so this changes nothing a draft may say:
    the files under profile/ already decide that. Returns the run's kind, so it can be started again."""
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    problem = _problem(row) if row else None
    newest = conn.execute("SELECT MAX(id) FROM tasks WHERE kind = ?", (row["kind"],)).fetchone()[0] if row else None
    if (not problem or problem.get("kind") != claude_code.PROFILE_CHANGED or row["ok"] or row["cleared_at"]
            or newest != task_id):
        raise ValueError("That warning isn't showing any more: it was cleared already, or a newer run took its place.")
    conn.execute("UPDATE tasks SET cleared_at = ? WHERE id = ?", (now(), task_id))
    job_id, files = problem.get("job_id"), [str(path) for path in problem.get("files") or ()]
    if isinstance(job_id, int) and conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone():
        log_event(conn, job_id, "profile_change_accepted",
                  f"You said the change to {claude_code.some(files) or 'profile/'} that stopped the {LABELS[row['kind']]} "
                  "was yours.")
    conn.commit()
    return row["kind"]


def _scheduled_sweep_running(conn) -> bool:
    """A sweep started by the timer, which never made a row in `tasks`."""
    row = conn.execute("SELECT started_at, finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return bool(row and not row["finished_at"] and _minutes_since(row["started_at"]) < STALE_MINUTES[SWEEP])


def going(conn) -> str | None:
    """The run going now, by its label, or None. A pan the timer started counts too."""
    for kind, run in latest(conn).items():
        if run["state"] == "running":
            return LABELS.get(kind, kind)
    return LABELS[SWEEP] if _scheduled_sweep_running(conn) else None


def _facts_still_example() -> bool:
    """A workspace copied from the example and not yet made yours. A Claude run there spends usage on a fictional candidate."""
    return "profile/facts.md" in doctor.still_example(ROOT)


def not_ready(kind: str) -> str | None:
    """Why this kind of run can't start in this workspace at all, whatever else is going on. The dashboard disables
    the run's button with this as its reason, rather than asking to spend your Claude plan and then refusing."""
    if IS_EXAMPLE:
        if kind == SWEEP:
            return "The demo doesn't read real job boards. In your own workspace, this pans them and checks your mail."
        if kind == TAILOR:
            return "The demo doesn't run Claude. In your own workspace, this writes every draft waiting under Being tailored."
        return "The demo doesn't run Claude. In your own workspace, this judges new postings and tailors resumes."
    if kind in WRITERS and _facts_still_example():
        return ("profile/facts.md is still the fictional example's, so Claude would judge and write for someone else. "
                "Make it yours first: `pyrite doctor` lists what else is left.")
    if kind in WRITERS and "profile/facts.md" in doctor.still_blank(ROOT):
        return ("profile/facts.md is still blank, so Claude has nothing true to write from. Fill it in first: "
                "`pyrite doctor` lists what else is left.")
    return None


def refusal(conn, kind: str) -> str | None:
    """Why this run can't start right now, if there's a reason."""
    if kind not in LABELS:
        return "Unknown kind of run."
    why = not_ready(kind)
    if why:
        return why
    running ={name for name, run in latest(conn).items() if run["state"] == "running"}
    if kind in running or (kind == SWEEP and _scheduled_sweep_running(conn)):
        return f"A {LABELS[kind]} is already going."
    if kind in WRITERS:
        for other in WRITERS:
            if other != kind and other in running:
                return f"A {LABELS[other]} is already going, and both write drafts, so this waits for it."
    return None


def begin(conn, kind: str) -> int:
    """Claim the run, so a double click can't start two."""
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    problem = refusal(conn, kind)
    if problem:
        conn.rollback()
        raise ValueError(problem)
    ts = now()
    task_id = conn.execute(
        "INSERT INTO tasks (kind, started_at, updated_at, detail) VALUES (?, ?, ?, 'Starting')", (kind, ts, ts)
    ).lastrowid
    conn.commit()
    return task_id


def progress(conn, task_id: int, detail: str) -> None:
    conn.execute("UPDATE tasks SET detail = ?, updated_at = ? WHERE id = ?", (detail[:300], now(), task_id))
    conn.commit()


def _finish(conn, task_id: int, ok: bool, detail: str, problem: dict | None = None) -> None:
    ts = now()
    conn.execute("UPDATE tasks SET finished_at = ?, updated_at = ?, ok = ?, detail = ?, problem = ? WHERE id = ?",
                 (ts, ts, int(ok), detail[:1500], json.dumps(problem) if problem else None, task_id))
    conn.commit()


def start(conn, kind: str) -> None:
    """The dashboard buttons: check it can work, then run in the background so the page doesn't wait."""
    problem = refusal(conn, kind)
    if problem:
        raise ValueError(problem)
    if kind in WRITERS:
        claude = find_claude()
        if not claude:
            raise ValueError("Claude Code wasn't found on this PC, so the run can't start.")
        if not claude_code.signed_in(claude):
            raise ValueError(sign_in_help(claude))
    task_id = begin(conn, kind)
    try:
        claude_code.spawn_worker("task", task_id, ROOT)
    except OSError as err:
        _finish(conn, task_id, False, f"Couldn't start: {err}")
        raise ValueError(f"Couldn't start the {LABELS[kind]}: {err}") from err


def _sweep(conn, cfg: dict, task_id: int) -> str:
    progress(conn, task_id, "Reading the job boards")
    stats = discover.run(conn=conn, cfg=cfg)
    said = (f"{stats['postings']:,} postings read across {stats['sources']} sources, {stats['new']} new"
            + (f", {stats['failed']} failing" if stats["failed"] else "") + ".")
    if stats.get("rescored"):
        said += " " + discover.rescore_summary(stats["rescored"])
    progress(conn, task_id, "Checking mail for replies")
    try:
        result = mail.check(conn, cfg)
    except Exception as err:  # Trouble reading mail never fails a sweep. It shows on the Sources tab instead.
        conn.rollback()
        result = mail.failed(conn, cfg, f"The mail check stopped with {type(err).__name__}: {err}")
    return f"{said} {mail.summary(result)}"


def run(conn, cfg: dict, task_id: int) -> bool:
    """Do the work of a claimed run, in this process. Returns whether it worked."""
    kind = conn.execute("SELECT kind FROM tasks WHERE id = ?", (task_id,)).fetchone()["kind"]
    try:
        if kind == SWEEP:
            said = _sweep(conn, cfg, task_id)
        else:
            from . import daily  # Here, because daily needs cli and cli offers this module's commands.

            work = daily.tailor_batch if kind == TAILOR else daily.run
            said = work(conn, cfg, lambda text: progress(conn, task_id, text))
    except Exception as err:  # Anything uncaught would leave the dashboard saying "running" until it went stale.
        conn.rollback()
        problem = getattr(err, "problem", None)  # one the dashboard offers a way past, such as daily.ProfileChanged
        _finish(conn, task_id, False, f"{err}" if str(err) else type(err).__name__, problem if isinstance(problem, dict) else None)
        return False
    _finish(conn, task_id, True, said)
    return True


def result(conn, task_id: int) -> str:
    return conn.execute("SELECT detail FROM tasks WHERE id = ?", (task_id,)).fetchone()["detail"]
