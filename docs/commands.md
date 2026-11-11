# Common commands

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

```bash
.venv/Scripts/python.exe tools/pyrite.py sweep
```

```bash
.venv/Scripts/python.exe tools/pyrite.py run
```

```bash
.venv/Scripts/python.exe tools/pyrite.py discover
```

```bash
.venv/Scripts/python.exe tools/pyrite.py sources
```

```bash
.venv/Scripts/python.exe tools/pyrite.py rescore
```

```bash
.venv/Scripts/python.exe tools/pyrite.py queue
```

`sweep` and `run` are what the dashboard's two buttons start. `discover` reads the boards without checking mail, and `--fresh` also re-reads postings it rejected earlier. `sources` tests every watched board. `rescore` re-applies `search.toml` to prospects, so run it after changing filters. It gives each one that still passes its score and reasons again, and drops each one that no longer does unless you've acted on it: a note, a next step, **Tailor this one first**, a fit verdict or a status of your own such as **Undo pass**. Opening one isn't acting on it. It names what it dropped, and jobs past Prospects keep the score they were decided on. When an update to Pyrite changes how postings are scored, or you change the filters in `search.toml`, the next pan does this by itself before reading the boards, and the dashboard names what it dropped beside when the boards were last checked. `queue` shows what the next run will work on, and `pyrite job <id>` shows one posting.

```bash
.venv/Scripts/python.exe tools/pyrite.py gaps
```

`gaps` lists the requirements your applications' notes keep calling gaps, raised by two applications or more and not yet answered, each with the name to answer it by. `--min 1` includes the ones raised once, and `--all` also lists the answered ones and those already under "Unsupported". It answers them as [Gaps to answer](profile.md#gaps-to-answer) on the Profile tab does, and the dashboard's History keeps `facts.md` as it was:

```bash
.venv/Scripts/python.exe tools/pyrite.py gaps answer rust --yes "Wrote a CAN driver in Rust for the test bench" --section "Robotics and firmware"
```

`--no` adds the gap under "Unsupported" (`--no "your words"` to word it), `--dismiss` stops asking about one that isn't a fact to settle, and `gaps forget <name>` asks about one again. Drafts you haven't sent that list an answered gap are flagged for rework on the dashboard.

```bash
.venv/Scripts/python.exe tools/pyrite.py status 42 rejected --note "Form email after the phone screen"
```

`status <id> <status>` moves a job as the dashboard's status buttons do, with an optional `--note` for its timeline: `new`, `shortlisted`, `applied`, `responded`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn`, `passed` or `closed`. `ready` and `needs_fix` aren't among them, since only the assay sets those, through `pyrite finish`. A job you've sent can't go back to `new` or `shortlisted`, where a run would rewrite the folder that records what you sent: `status <id> applied` reopens it as sent. The first `applied` does what **I applied** does: it schedules the follow-up and keeps a read-only copy of the documents in `sent/` ([After you apply](applying.md#after-you-apply)).

```bash
.venv/Scripts/python.exe tools/pyrite.py refresh 42
```

`refresh <id>` is **Refresh resume** from the command line: Claude rewrites that draft's resume, and it's kept only if it passes the assay ([Refreshing a resume](assay.md#refreshing-a-resume)).

`pyrite help` lists every command, and `pyrite help <command>` explains one. The rest are covered where they're used:

| Command | Covered in |
|---|---|
| `init`, `where`, `doctor`, `seed` | [Setting up](setup.md) |
| `demo`, `check` | [The README](../README.md) |
| `import-resume`, `folder`, `finish` | [Writing the documents](documents.md) |
| `serve`, `open` | [The dashboard](dashboard.md) |
| `relocate` | [Moving for a job](dashboard.md#moving-for-a-job) |
| `add`, `skills`, `outlook` | [Finding and ranking postings](prospects.md) |
| `culture`, `fill`, `autofill`, `sent`, `outreach`, `prep` | [Applying and after](applying.md) |
| `code` | [Confirming with a code](profile.md#confirming-with-a-code) |
| `triage`, `brief`, `usage` | [Scheduling and Claude runs](schedule.md) |
| `inbox` | [Reply detection](mail.md) |

On a terminal, `discover`, `rescore`, `queue`, `job`, `check`, `finish`, `fill`, `gaps` and `usage` say what they found in a few lines of words. Add `--json` for JSON instead, which is also what they print whenever their output goes to a file or another program, so a script or a scheduled run reads the same JSON as before. `sources` prints its table either way, and JSON with `--json`.
