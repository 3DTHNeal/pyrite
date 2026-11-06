# Running Pyrite

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
  data/pyrite.db              everything Pyrite tracks. Back this up, because it can't be regenerated.
```

Copy `example/profile/` to start, and replace everything in it. The `[candidate]` and `[guard]` sections of `search.toml` matter most.

Then point the code at your workspace. Either set `PYRITE_HOME`, or put the path on one line in a file called `.pyrite-home` in this folder, which git ignores. Check it with:

```bash
.venv/Scripts/python.exe tools/pyrite.py where
```

With neither set, the code uses the fictional `example/` workspace, so it can't touch your data by accident. Commands that write, such as `discover`, `folder`, `finish` and `serve`, then refuse to run, so nothing real ends up inside this repository. `pyrite demo` is the way to look around without a workspace.

If you're not in the US, two settings in `search.toml` matter early: `remote_home` and `remote_elsewhere` under `[location]`, which replace the built-in idea of which remote roles are open to you, and `paper = "a4"` under `[documents]`.

### Protecting a public fork

Turn on the pre-push check once per clone, and keep your denylist in your workspace, since a public list of secrets would be a leak of its own:

```bash
git config core.hooksPath .githooks
```

```bash
git config pyrite.denylist /path/to/my-job-search/profile/public-denylist.txt
```

The check reads file contents, file and branch names, commit messages and the text inside `.docx` and `.pdf` files. Reading a PDF's pages needs poppler's `pdftotext`, which Git for Windows includes, or `pypdf`. Without either, a PDF blocks the push, since nothing would vouch for what's on its pages.

## A new application by hand

1. Make a folder under `applications/` in your workspace and copy the closest `resume.md` into it.
2. Tailor it to the posting using only facts from `profile/facts.md`. Add new confirmed facts there first.
3. Write `notes.md` with the posting link, fit and gaps.
4. Build it and confirm it's two pages:

```bash
.venv/Scripts/python.exe tools/build_resume.py path/to/resume.md --name Your_Name_Resume_Acme --author "Your Name"
```

Cover letters use the same script with `--letter`, and should fit on one page.

Each build makes three files: the `.docx`, the `.pdf` and a `.txt` for the paste boxes on application sites and LinkedIn. The documents are shaped for the parsers behind applicant tracking systems (one column, standard section names, real bullet characters, nothing in headers or footers), and after the PDF is made its text is read back the way a parser reads it. The build fails if the name, a contact detail, a heading or a date range didn't survive, or if the export produced ligatures that a keyword search can't match. That read-back needs poppler's `pdftotext`, which Git for Windows includes; without it the step is skipped. `docs/resume-playbook.md` has the evidence behind the format and the writing rules, and the table of what each application system does with an upload.

The builder and its writing rules together are the drafter, and they carry a version number (`DRAFTER_VERSION` in `tools/pyrite/checks.py`). Every file built is stamped with it, in the Word document's Version and Keywords properties and the PDF's Keywords, so you can tell which rules a document was written under. `pyrite check` reports the version behind each `.docx` in a folder and warns when it isn't the current one; the dashboard shows the same under the assay result. The playbook's "Drafter versions" table says what changed in each.

## The dashboard

`tools/pyrite.py serve` runs it at <http://127.0.0.1:8787>. It only listens on this machine. On Windows, double-click `Pyrite.cmd`, which starts the dashboard if it's down and replaces it if it has hung. If another program holds port 8787, it says so and closes nothing. To start it at login, put a shortcut to `.venv\Scripts\pythonw.exe tools\pyrite.py serve` in your Startup folder, with this folder as its working directory.

The dashboard uses a prospector's words for its parts:

| Name | What it is |
|---|---|
| Sluice | Today's to-do list: what needs you, most urgent first |
| Field report | The summary each Claude run leaves at the top of the Sluice |
| Yield | How many jobs have reached each stage, from found to offer |
| Claims | Jobs you're working: being tailored, ready, applied and beyond |
| Nuggets | Drafts that passed the assay and are ready to send |
| Prospects | New postings you haven't judged yet |
| Tailings | Jobs that are closed out: passed, rejected, ghosted or taken down |
| Veins | The job boards Pyrite reads, and whether each is working |
| Pan | Reading the boards and checking mail. The command is still `pyrite sweep` |
| Assay | The fact checker that decides whether a draft is ready |

Two buttons at the top start a run without waiting for the schedule:

- **Pan now** reads the job boards and checks mail, as the morning pan does. It uses no AI.
- **Run Claude now** judges the new postings and tailors the best, as the daily run does. It uses your Claude plan, so it asks first.

Each runs in the background, shows its progress beside the buttons, and refuses to start while one of its kind is already going. The demo starts neither.

## The schedule

```text
05:15  Pan timer         reads the job boards, filters and ranks, then checks Gmail for replies (no AI, no usage cost)
07:00  Daily Claude run  judges new postings, tailors resumes, leaves a field report
any    You               read each draft, apply on the company's site, log what comes back
```

- **The pan** is `pyrite sweep`, which is `pyrite discover` followed by `pyrite inbox`. On Windows, use Task Scheduler. On Linux, `tools/pyrite/systemd/` has unit files.
- **The daily run** is `pyrite run`. Schedule it the same way, for after the pan. It needs Claude Code installed and signed in.

### Locking down the daily run

`pyrite run` is the daily run with its limits built in. The code does every step that changes anything: it records each verdict, makes each folder, builds the documents and runs the assay. Claude is started once per posting to judge it, with tools that can only read, and once per application to write it, able to change only that application's `resume.md`, `cover-letter.md` and `notes.md`. It never gets a shell or web access, so an instruction hidden in a posting has nothing to reach. Its instructions are `tools/pyrite/triage.md` and `tools/pyrite/tailor.md`, and the field report is written by the code from what the run did.

The older way is a Claude Code session of your own following `tools/pyrite/daily_run.md`. That session has a shell, so its rules are only instructions, and its limits are yours to set. If you use it, give it permissions that:

- allow the `pyrite` commands it needs: `queue`, `discover`, `job`, `triage`, `folder`, `finish` and `brief`
- allow edits only under `applications/` in your workspace
- deny edits to `profile/`, `data/` and this repository, and deny web access

Either way, the code holds two lines by itself. Only `pyrite finish` can mark a draft ready, and a draft changed after it passed is flagged on the dashboard.

Nothing ever applies on your behalf. Click **I applied** on the dashboard and it schedules a follow-up reminder for 7 days later. It also freezes the job: a read-only copy of `resume.md`, `cover-letter.md` and the built documents goes into the folder's `sent/`, the job leaves the ready list, and from then on nothing rebuilds, refreshes or re-checks its documents. The job shows **Frozen** with links to the sent copies, and **Changed after sending** if a file in the folder stops matching them. A second application to the same company is a new job with its own folder. For applications made before this existed, `pyrite sent <id> --from <subfolder>` keeps the copy from a subfolder you saved by hand. Log what comes back with **Got a reply**, **Interview** or **Rejected** so the numbers stay right. Reply detection points out mail worth checking, but only those buttons change a job's status.

## New listings, reposts and possible ghost jobs

Prospects, the Sluice and the daily run put the newest listings first, ahead of older ones with a similar score. **Priority** is the filter score plus points for age and for a preferred city or industry, minus a penalty for each repost. The weights are under `[freshness]` and `[promote]` in `search.toml`. Priority only changes the order, and the filter score still decides what's kept and tailored.

- **New:** posted in the last 7 days and never reposted.
- **Reposted:** the same job came back under a new listing, or the same listing came back after being taken down. The same job in another city isn't a repost. Age keeps counting from the earliest date on record, so a repost doesn't look new again.
- **Re-dated:** a board moved a listing's posted date forward. Only Workday and Ashby are checked, since Greenhouse and Lever report the date a listing was created.
- **Possible ghost:** up 90 days or more, reposted or re-dated twice, or reposted and up 45 days or more. It's a prompt to look closer, not proof: some companies keep real openings up all year.
- **May be a repost:** a Workday link ending in `-1` or similar, which often means a requisition has more than one posting. It's a hint only and costs no priority.

A board's first pan sets a baseline, so repost counts stay at zero until a later pan sees something come back.

Two postings count as one job only when their text nearly matches throughout, so openings that share a title and an "about us" paragraph stay separate. Workday's search returns only some of a site's postings, so each pan asks it directly about the tracked ones it left out. A posting is marked down only when Workday confirms it's gone, and one it confirms is still up isn't mistaken for a repost when the same job appears in another city.

## Preferred cities and industries

Open the dashboard's **Settings** tab to choose the cities and industries you want to see first. A match adds to Priority and shows as a blue tag on Prospects, whose **Preferred city or industry** filter lists only those postings. Open a job to see the points under **Why its priority is**.

The tab has a panel for the points, one for cities and a card for each industry, and each has its own **Save**. A save writes only that panel's part, so an edit you haven't finished in another panel isn't saved with it. Industry cards stay closed until you open one, and show what's saved in a line.

In the Cities panel, start typing and the name box suggests places your own postings name, with how many postings each has. Beside each city it shows how many prospects the name matches right now, and how the job boards write the place, which is how you spot a city that shares its name with one in another state.

The tab edits only `[promote]` in `search.toml`, which you can also edit by hand. A save rewrites that section and its comments, leaves the rest of the file alone, and keeps the earlier file as `search.previous.toml` beside it. Filters, the patterns under `[guard]` and allowed hosts can't be changed from the dashboard, because it has no login. The demo can't save settings.

- **Cities** match the posting's location, as a whole word. Add `match` if the name alone isn't enough, as when another state has a city with the same name.
- **Industries** have no field on a job board, so they're judged from the posting. It counts if the employer is under `companies`, a term is in the employer's name or the title, or the terms appear at least `mentions_needed` times in the description. One passing mention doesn't count, and terms need to be specific, since "medical" alone would catch most postings' benefits text.
- **Points** are `city_points` and `industry_points`, and any line can override them with `points`. Each list counts once, at its best match.
- **Tracks can be limited to industries.** A `[[track]]` with `industries = ["Robotics"]` matches only postings in those industries, judged the same way. Use it for a broad title, such as plain "software engineer", that you want only from the employers you care most about.
- **Skills it wants** are what an industry looks for. The tab checks them against `facts.md`, skipping its "Do not use" and "Unsupported" sections, and shows what you have and what's missing. It's a word match to help you set the points, so it doesn't change the ranking or what a resume may claim. If a gap is true of you, add it to `facts.md` first.

Promotions change the order and nothing else. They raise no filter score, so a posting below `tailor_min_score` still won't be tailored, and they can't bring back a posting the filters dropped. To accept a new city at all, add it under `[location]` too. The daily run works through its limit in Priority order, so promoted postings do get read first.

Changes apply the next time the dashboard refreshes, and need no `rescore`.

## Your facts

The **Facts** tab shows `profile/facts.md` and `profile/approved-terms.txt`, the two files that say what a resume may claim. The fact bank is shown a section at a time. Click **Edit** on a section, change it and **Save**, or use **Add a section**. Sections named "Do not use" and "Unsupported" are marked **Approves nothing**, because the assay never treats them as a source.

- A save takes effect the next time a draft is checked. Drafts that already passed aren't checked again by themselves.
- The file from before each save is kept beside it, as `facts.previous.md` or `approved-terms.previous.txt`.
- If the file changed on disk after the tab loaded it, the save is refused and nothing is written.
- To block a term by name, it also has to be listed under `[guard]` in `search.toml`. That can't be done from the dashboard.

The dashboard has no login, so anyone who can open it can change these two files. It only listens on this machine unless you add names under `allowed_hosts`. The demo's facts can't be changed.

## The assay

The assay is Pyrite's fact checker, named for the test that tells gold from fool's gold. `pyrite finish` won't mark a draft ready unless it passes checks that involve no AI. It blocks confidential terms, unsupported claims, numbers not in the fact bank, changed employers, titles or dates, a changed contact line, outside links and unfilled placeholders, and it enforces the page limits. Resumes are also blocked from naming a specialist term that isn't in your approved sources. If a blocked term is true of you, add it to `approved-terms.txt`. It can't catch a true fact twisted into a false impression, so reading each draft still matters.

It also warns, without blocking, about wording that readers now take as machine-written or empty: em dashes, "spearheaded", "leveraged", "results-driven" and the like, and a cover letter over 350 words. Beside the result, the dashboard shows what share of the posting's skill terms the resume uses, and says so when that share is high enough to read as copied (above about 85%) or too low for a skills filter (below about 40%).

- **What counts as a source.** Your approved sources, minus the "Do not use" and "Unsupported" sections of `facts.md`, which approve nothing. The posting never counts, and neither does its title. A resume that opens a bullet with a tool the posting names, and your sources don't, is blocked.
- **Numbers.** Digits must appear in your sources. Numbers written as words from eleven up are blocked unless your sources use the same word, so write them as digits.
- **Disclaimers.** A sentence may name an unsupported claim only to deny it: "I have not led that", or "the posting lists it, and I have not done it". "Led it with no delays" is still a claim.
- **Every line is checked.** Only your exact approved contact line is exempt, and an indented heading counts as a heading.
- **Ready means the files on disk passed.** `pyrite finish` is the only thing that marks a draft ready. If a draft's files change afterwards, the dashboard shows **Changed since checked** until you click **Check again** or run `pyrite finish <id>`. A ready draft that fails a later check goes back to blocked.
- **Drafts that keep failing.** After `fix_attempts` failed assays (6 unless you set it under `[run]`), the daily run stops retrying a draft. **Tailor this one first** gives it another set of tries.

What it can still miss: a real number attached to the wrong claim, a number from one to ten written as a word, and an invented skill written in lowercase or opening a sentence without the posting naming it.

## Refreshing a resume

**Refresh resume** on a draft you haven't sent has Claude Code rewrite it for that posting, in the background. The assay and the build run afterward, and any errors go back to Claude, up to three tries. If it still fails, the earlier draft and its documents are restored. While it runs, the previous draft is kept as `resume.previous.md` in the job's folder. It needs Claude Code installed and signed in. The demo refuses this, since a real run would spend your usage and overwrite the sample draft.

## Interview prep

**Interview prep** appears on a job once you've logged **Got a reply** or **Interview**. Claude Code writes `interview-prep.md` in that job's folder, in the background, from the posting, the resume you sent, your notes and `facts.md`. The brief covers what they're likely to ask and the true evidence to answer with, the resume lines to be ready for, each gap with an honest answer, questions to ask them, and anything odd in the posting. Open it with **Interview prep brief** on the job.

It runs under the same limits as a resume refresh: no shell, no web access, and it can write only that one file. The assay, which uses no AI, runs afterward, and any errors go back to Claude, up to three tries. The brief is private notes, so the check differs from a resume's:

- **Blocked:** confidential terms, unsupported claims, links, unfilled placeholders, and any number that's in neither your fact bank nor the posting.
- **Flagged for you to read:** a term the posting uses that isn't in your fact bank, since the brief should treat it as a gap.

If it still fails, no new brief is kept and an earlier one goes back. Like the resume check, it can't catch a true fact framed misleadingly, so read the brief against what you remember. `pyrite prep <id>` does the same from the command line.

## Claude usage

The **Sources** tab shows what the Claude runs started from the dashboard or the command line have used: runs, time, tokens and cost, for the last 7 days and all time. `pyrite usage` prints the same numbers.

- **Counted:** Refresh resume and Interview prep, including runs that failed.
- **Not counted:** the daily run, which is a scheduled Claude Code task that starts on its own.
- **Cost** is Claude Code's own estimate at API prices. On a Claude plan it isn't a bill.

## Reply detection

`pyrite inbox` runs after each morning pan. It reads the sender, subject and date of recent Gmail messages and compares them with every active job you've applied to. A match appears as **Possible reply** on the job's card, in the to-do list and on its timeline. Message bodies are never downloaded.

A match never changes a status, so a wrong one can't affect the response rate. Read the email, then use the usual buttons if it's real, or **Dismiss** if it isn't.

**Setup.** Until this is done, the command says it isn't set up and exits cleanly.

1. Create an app password at <https://myaccount.google.com/apppasswords>, which needs 2-Step Verification turned on.
2. Create the credentials file. It lives outside this repository, and the command refuses to use it if other users can read it. On Windows it checks the file's access list, and a file created in your home folder is private by default.

   ```bash
   mkdir -p ~/.config/pyrite && cp tools/pyrite/imap.env.example ~/.config/pyrite/imap.env
   ```

3. Open `~/.config/pyrite/imap.env` and fill in `IMAP_USER` and `IMAP_PASSWORD` yourself.
4. Test it. With no applications logged yet it still checks the login.

   ```bash
   .venv/Scripts/python.exe tools/pyrite.py inbox
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

If the login or connection fails, the pan still succeeds and **Email replies** shows as failing on the Veins tab.

## Common commands

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

`sweep` and `run` are what the dashboard's two buttons start. `discover` reads the boards without checking mail, and `--fresh` also re-reads postings it rejected earlier. `sources` tests every watched board. `rescore` re-applies `search.toml` to postings you haven't acted on, so run it after changing filters. `queue` shows what the next run will work on.

## Adding companies

Add a line under `[watch.*]` in `search.toml` if the careers page is on Greenhouse, Lever, Ashby or Workday, then run `pyrite sources` to confirm it responds. Employers with no public feed go under `[[manual_check]]`, which lists them on the dashboard's Veins tab. Use **Add a posting** for anything you find yourself, such as on LinkedIn.
