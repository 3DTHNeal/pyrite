# Running the war room

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python.exe -m pip install -r tools/requirements.txt
```

PDFs come from LibreOffice if `soffice` is on `PATH`, and otherwise from Word. Page counts come from poppler's `pdfinfo` if it's on `PATH`, and otherwise from reading the PDF directly.

## Your workspace

The code and your data are separate. A workspace is a folder outside this repository, preferably its own private git repository:

```text
my-job-search/
  profile/facts.md            what a resume may claim, what's confidential, what's unsupported
  profile/approved-terms.txt  specialist terms that are true of you
  profile/search.toml         what to look for, which companies to watch, what to block
  profile/run-notes.md        personal guidance for the daily run
  profile/seed.toml           optional: applications you made before using this
  applications/               one folder per job
  data/warroom.db             everything the war room tracks. Back this up, because it can't be regenerated.
```

Copy `example/profile/` to start, and replace everything in it. The `[candidate]` and `[guard]` sections of `search.toml` matter most.

Then point the code at your workspace. Either set `WARROOM_HOME`, or put the path on one line in a file called `.warroom-home` in this folder, which git ignores. Check it with:

```bash
.venv/Scripts/python.exe tools/wr.py where
```

With neither set, the code uses the fictional `example/` workspace, so it can't touch your data by accident.

### Protecting a public fork

Turn on the pre-push check once per clone, and keep your denylist in your workspace, since a public list of secrets would be a leak of its own:

```bash
git config core.hooksPath .githooks
```

```bash
git config warroom.denylist /path/to/my-job-search/profile/public-denylist.txt
```

## A new application by hand

1. Make a folder under `applications/` in your workspace and copy the closest `resume.md` into it.
2. Tailor it to the posting using only facts from `profile/facts.md`. Add new confirmed facts there first.
3. Write `notes.md` with the posting link, fit and gaps.
4. Build it and confirm it's two pages:

```bash
.venv/Scripts/python.exe tools/build_resume.py path/to/resume.md --name Your_Name_Resume_Acme --author "Your Name"
```

Cover letters use the same script with `--letter`, and should fit on one page.

## The dashboard

`tools/wr.py serve` runs it at <http://127.0.0.1:8787>. It only listens on this machine. On Windows, double-click `War Room.cmd`, which starts the dashboard if it's down and replaces it if it has hung. To start it at login, put a shortcut to `.venv\Scripts\pythonw.exe tools\wr.py serve` in your Startup folder, with this folder as its working directory.

## The schedule

```text
05:15  Sweep timer       reads the job boards, filters and ranks, then checks Gmail for replies (no AI, no usage cost)
07:00  Daily Claude run  judges new postings, tailors resumes, writes a briefing
any    You               read each draft, apply on the company's site, log what comes back
```

- **The sweep** is `wr discover`, then `wr inbox`. On Windows, use Task Scheduler. On Linux, `tools/warroom/systemd/` has unit files.
- **The daily run** follows `tools/warroom/daily_run.md`. Run it as a scheduled Claude Code task.

Nothing ever applies on your behalf. Click **I applied** on the dashboard and it schedules a follow-up reminder for 7 days later. Log what comes back with **Got a reply**, **Interview** or **Rejected** so the numbers stay right. Reply detection points out mail worth checking, but only those buttons change a job's status.

## New listings, reposts and possible ghost jobs

The Radar, today's orders and the daily run put the newest listings first, ahead of older ones with a similar score. **Priority** is the filter score plus points for age, minus a penalty for each repost. The weights are under `[freshness]` in `search.toml`. Priority only changes the order, and the filter score still decides what's kept and tailored.

- **New:** posted in the last 7 days and never reposted.
- **Reposted:** the same job came back under a new listing, or the same listing came back after being taken down. The same job in another city isn't a repost. Age keeps counting from the earliest date on record, so a repost doesn't look new again.
- **Re-dated:** a board moved a listing's posted date forward. Only Workday and Ashby are checked, since Greenhouse and Lever report the date a listing was created.
- **Possible ghost:** up 90 days or more, reposted or re-dated twice, or reposted and up 45 days or more. It's a prompt to look closer, not proof: some companies keep real openings up all year.
- **May be a repost:** a Workday link ending in `-1` or similar, which often means a requisition has more than one posting. It's a hint only and costs no priority.

A board's first sweep sets a baseline, so repost counts stay at zero until a later sweep sees something come back.

## The fact checker

`wr finish` won't mark a draft ready unless it passes checks that involve no AI. It blocks confidential terms, unsupported claims, numbers not in the fact bank, changed employers, titles or dates, a changed contact line, outside links and unfilled placeholders, and it enforces the page limits. Resumes are also blocked from naming a specialist term that isn't in your approved sources. If a blocked term is true of you, add it to `approved-terms.txt`. It can't catch a true fact twisted into a false impression, so reading each draft still matters.

## Reply detection

`wr inbox` runs after each morning sweep. It reads the sender, subject and date of recent Gmail messages and compares them with every active job you've applied to. A match appears as **Possible reply** on the job's card, in the to-do list and on its timeline. Message bodies are never downloaded.

A match never changes a status, so a wrong one can't affect the response rate. Read the email, then use the usual buttons if it's real, or **Dismiss** if it isn't.

**Setup.** Until this is done, the command says it isn't set up and exits cleanly.

1. Create an app password at <https://myaccount.google.com/apppasswords>, which needs 2-Step Verification turned on.
2. Create the credentials file. It lives outside this repository, and the command refuses to use it if other users can read it. On Windows it checks the file's access list, and a file created in your home folder is private by default.

   ```bash
   mkdir -p ~/.config/warroom && cp tools/warroom/imap.env.example ~/.config/warroom/imap.env
   ```

3. Open `~/.config/warroom/imap.env` and fill in `IMAP_USER` and `IMAP_PASSWORD` yourself.
4. Test it. With no applications logged yet it still checks the login.

   ```bash
   .venv/Scripts/python.exe tools/wr.py inbox
   ```

An app password opens the whole mailbox as far as Google is concerned. The read-only behavior comes from this code, which opens folders with `readonly=True` and only asks for headers. To cut off access, revoke the password on the same Google page.

**What counts as a match:**

- Mail from the company's own domain, including subdomains. If an employer uses a domain that doesn't match its name, add it under `[inbox.domains]` in `search.toml`.
- Mail from an applicant tracking system such as Greenhouse or Workday, if the company is named as a whole word in the sender name or subject.

**What it can miss or get wrong:**

- It misses outside recruiters, personal addresses, LinkedIn messages and anything in Spam. Keep reading your email.
- It flags automatic "we received your application" notices, and non-marketing mail from a company you also buy from. Mailing-list mail is skipped unless its subject is about hiring.
- If you've applied to two roles at one company, a match appears on both.
- Sender names can be forged. Treat a match as a prompt to open your mailbox, and don't follow links from the dashboard's text.

If the login or connection fails, the sweep still succeeds and **Email replies** shows as failing on the Sources tab.

## Common commands

```bash
.venv/Scripts/python.exe tools/wr.py discover
```

```bash
.venv/Scripts/python.exe tools/wr.py sources
```

```bash
.venv/Scripts/python.exe tools/wr.py rescore
```

```bash
.venv/Scripts/python.exe tools/wr.py queue
```

`discover` sweeps now, and `--fresh` also re-reads postings it rejected earlier. `sources` tests every watched board. `rescore` re-applies `search.toml` to postings you haven't acted on, so run it after changing filters. `queue` shows what the next run will work on.

## Adding companies

Add a line under `[watch.*]` in `search.toml` if the careers page is on Greenhouse, Lever, Ashby or Workday, then run `wr sources` to confirm it responds. Employers with no public feed go under `[[manual_check]]`, which lists them on the dashboard's Sources tab. Use **Add a posting** for anything you find yourself, such as on LinkedIn.
