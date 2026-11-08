"""Runs you start yourself, from the dashboard or the command line: a sweep, the Claude run, or a tailoring batch.

Each runs in its own process, one of each kind at a time, and reports its progress through the
`tasks` table so the dashboard can show it. The Claude run and the tailoring batch both write
drafts, so only one of those two goes at a time.
"""
from datetime import datetime, timezone

from . import claude_code, discover, doctor, mail
from .claude_code import find_claude, sign_in_help
from .store import IS_EXAMPLE, ROOT, now

SWEEP, CLAUDE, TAILOR = "sweep", "claude", "tailor"
LABELS = {SWEEP: "pan", CLAUDE: "Claude run", TAILOR: "tailoring batch"}
WRITERS = (CLAUDE, TAILOR)  # both write drafts, so they take turns
# With no word from a run for this long it must have died, for instance when the PC went to sleep or restarted.
STALE_MINUTES = {SWEEP: 60, CLAUDE: 25, TAILOR: 25}
DIED = "The run stopped without finishing."


def _minutes_since(iso: str) -> float:
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60


def latest(conn) -> dict[str, dict]:
    """The latest run of each kind, by kind: its state, when it started and what it last said."""
    rows = conn.execute("SELECT * FROM tasks WHERE id IN (SELECT MAX(id) FROM tasks GROUP BY kind)").fetchall()
    found = {}
    for row in rows:
        state, detail = "running", row["detail"]
        if row["finished_at"]:
            state = "done" if row["ok"] else "failed"
        elif _minutes_since(row["updated_at"]) > STALE_MINUTES.get(row["kind"], 60):
            state, detail = "failed", DIED
        found[row["kind"]] = {"state": state, "started_at": row["started_at"], "finished_at": row["finished_at"], "detail": detail}
    return found


def _scheduled_sweep_running(conn) -> bool:
    """A sweep started by the timer, which never made a row in `tasks`."""
    row = conn.execute("SELECT started_at, finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    return bool(row and not row["finished_at"] and _minutes_since(row["started_at"]) < STALE_MINUTES[SWEEP])


def _facts_still_example() -> bool:
    """A workspace copied from the example and not yet made yours. A Claude run there spends usage on a fictional candidate."""
    return "profile/facts.md" in doctor.still_example(ROOT)


def refusal(conn, kind: str) -> str | None:
    """Why this run can't start right now, if there's a reason."""
    if kind not in LABELS:
        return "Unknown kind of run."
    if IS_EXAMPLE:
        if kind == SWEEP:
            return "The demo doesn't read real job boards. In your own workspace, this pans them and checks your mail."
        if kind == TAILOR:
            return "The demo doesn't run Claude. In your own workspace, this writes every draft waiting under Being tailored."
        return "The demo doesn't run Claude. In your own workspace, this judges new postings and tailors resumes."
    if kind in WRITERS and _facts_still_example():
        return ("profile/facts.md is still the fictional example's, so Claude would judge and write for someone else. "
                "Make it yours first: `pyrite doctor` lists what else is left.")
    running = {name for name, run in latest(conn).items() if run["state"] == "running"}
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


def _finish(conn, task_id: int, ok: bool, detail: str) -> None:
    ts = now()
    conn.execute("UPDATE tasks SET finished_at = ?, updated_at = ?, ok = ?, detail = ? WHERE id = ?",
                 (ts, ts, int(ok), detail[:1500], task_id))
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
    progress(conn, task_id, "Checking mail for replies")
    try:
        result = mail.check(conn, cfg)
    except Exception as err:  # Trouble reading mail never fails a sweep. It shows on the Sources tab instead.
        result = {"state": "error", "message": f"{type(err).__name__}: {err}"}
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
        _finish(conn, task_id, False, f"{err}" if str(err) else type(err).__name__)
        return False
    _finish(conn, task_id, True, said)
    return True


def result(conn, task_id: int) -> str:
    return conn.execute("SELECT detail FROM tasks WHERE id = ?", (task_id,)).fetchone()["detail"]
