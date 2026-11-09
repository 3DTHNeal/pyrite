# Scheduling and Claude runs

[All of the guide](README.md)

## The schedule

```text
05:15  Pan timer         reads the job boards, filters and ranks, then checks Gmail for replies (no AI, no usage cost)
07:00  Daily Claude run  judges new postings, tailors resumes, leaves a field report
any    You               read each draft, apply on the company's site, log what comes back
```

- **The pan** is `pyrite sweep`, which is `pyrite discover` followed by `pyrite inbox`. On Windows, use Task Scheduler. On Linux, `tools/pyrite/systemd/` has unit files.
- **The daily run** is `pyrite run`. Schedule it the same way, for after the pan. It needs Claude Code installed and signed in.

How much the run does, and which model does it, are set under **Settings** on the dashboard, in **Daily run** and **Claude**, or in `search.toml`: `triage_per_day` and `tailor_per_day` under `[run]`, and `model` and `effort` under `[claude]`. Without a `[claude]` line, Claude Code uses its own default for it.

```toml
[claude]
model = "opus"   # a name or alias Claude Code knows
effort = "high"  # low, medium, high, xhigh or max
```

## Locking down the daily run

`pyrite run` is the daily run with its limits built in. The code does every step that changes anything: it records each verdict, makes each folder, builds the documents and runs the assay. Claude is started once per posting to judge it, with tools that can only read, and once per application to write it, able to change only that application's `resume.md`, `cover-letter.md` and `notes.md`. It never gets a shell or web access, so an instruction hidden in a posting has nothing to reach. Your fact bank and the rest of `profile/`, the database and the workspace's `.claude/` settings are denied outright, so even a workspace `.claude/settings.json` that allowed more couldn't open them to a run, and if anything in `profile/` changes while a draft is written, the run puts that draft back and stops. Judging gets Pyrite's own possible-ghost and scam-sign markings for each posting, outside the posting's fence. The run says what it's doing before every Claude call and every build, so a long job never looks stopped while it works. Its instructions are `tools/pyrite/triage.md` and `tools/pyrite/tailor.md`, and the field report is written by the code from what the run did.

A writing run gets everything it needs in its prompt: `profile/facts.md`, `profile/run-notes.md`, `profile/approved-terms.txt`, the model documents the run notes name in backticks (a folder means its `resume.md`, `cover-letter.md` and `notes.md`; a file path means that file), the job's `posting.md` and any draft already in its folder. That saves the six or seven turns a run used to spend reading them, each of which re-sent the whole conversation. The posting goes in fenced as job-board data, as it is everywhere else. **Refresh resume** gets the same.

The older way is a Claude Code session of your own following `tools/pyrite/daily_run.md`. That session has a shell, so its rules are only instructions, and its limits are yours to set. If you use it, give it permissions that:

- allow the `pyrite` commands it needs: `queue`, `discover`, `job`, `triage`, `folder`, `finish` and `brief`
- allow edits only under `applications/` in your workspace
- deny edits to `profile/`, `data/` and this repository, and deny web access

Either way, the code holds two lines by itself. Only `pyrite finish` can mark a draft ready, and a draft changed after it passed is flagged on the dashboard.

## Claude usage

The **Sources** tab shows what the Claude runs Pyrite started have used: runs, time, tokens and cost, for the last 7 days and all time. `pyrite usage` prints the same numbers.

- **Counted:** every Claude run Pyrite starts, including runs that failed: the daily run's judging and tailoring (`pyrite run`, **Run Claude now** and **Tailor these now**), Refresh resume, Interview prep, and checking mail through the Gmail connector.
- **Not counted:** a Claude Code session of your own, such as the older way of running the daily run from `tools/pyrite/daily_run.md`, since Pyrite doesn't start it.
- **Cost** is Claude Code's own estimate at API prices. On a Claude plan it isn't a bill.
