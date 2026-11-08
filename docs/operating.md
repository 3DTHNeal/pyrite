# Running Pyrite

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

## Setup

Make the venv with Python 3.11 or newer. On Windows, `py -3` picks the newest one installed, which matters where `python` is an older one:

```bash
py -3 -m venv .venv
```

Elsewhere, `python3 -m venv .venv`. Then:

```bash
.venv/Scripts/python.exe -m pip install -r tools/requirements.txt
```

PDFs come from LibreOffice if `soffice` is on `PATH`, and otherwise from Word. Page counts come from poppler's `pdfinfo` if it's on `PATH`, and otherwise from reading the PDF directly. `pyrite doctor`, below, says which of these it found.

## Your workspace

The code and your data are separate. A workspace is a folder outside this repository, preferably its own private git repository:

```text
my-job-search/
  profile/facts.md            what a resume may claim, what's confidential, what's unsupported
  profile/approved-terms.txt  specialist terms that are true of you
  profile/search.toml         what to look for, which companies to watch, what to block
  profile/run-notes.md        personal guidance for the daily run
  profile/resume.md           your master resume: every draft's employers, titles and dates must match it
  profile/cover-letter.md     your master letter, another source of what's true
  profile/seed.toml           optional: applications you made before using this
  profile/workday-paste.md    optional: every Workday field typed out once, which `pyrite fill` merges per job
  applications/               one folder per job
  data/pyrite.db              everything Pyrite tracks. Back this up, because it can't be regenerated.
```

`init` makes one from the example's profile and points this folder at it. Put your own name in the quotes. A name with a space needs them, and `init` refuses a placeholder such as "Your Name":

```bash
.venv/Scripts/python.exe tools/pyrite.py init ../my-job-search --name "Your Name"
```

It leaves out the example's `seed.toml` and clears its `allowed_hosts`, and changes nothing if the folder already has a `profile/`. Then replace everything else in `profile/`:

- `facts.md`, `approved-terms.txt` and `run-notes.md` with your own.
- `resume.md` and `cover-letter.md` with your master resume and letter, written in the form under [How the documents are written](#how-the-documents-are-written). The `[guard]` section of `search.toml` names them as the sources every draft is checked against, and `resume.md` as the one whose employers, titles and dates a draft must match.
- In `search.toml`, `[candidate]` with your name, `[location]`, the tracks, industries and companies to watch, and under `[guard]` your own confidential and unsupported terms and `expected_on_resume`. The assay reads nothing from the "Do not use" and "Unsupported" sections of `facts.md`, so every term in them needs a pattern under `forbidden` or `unsupported` to be blocked. `allowed_hosts` under `[dashboard]` lists names the dashboard would answer to, so add only ones you use.
- `workday-paste.md` with your own Workday answers, or delete it if you won't use `pyrite fill`.
- `seed.toml`, if you want it, with the applications you made before Pyrite. `pyrite seed` imports them: one with `applied_on` as applied, and one without under Being tailored, where `pyrite finish` checks it.

To do it by hand instead, copy `example/profile/` into a folder outside this repository and point the code at it. Either set `PYRITE_HOME`, or put the path on one line in a file called `.pyrite-home` in this folder, which git ignores. A Git Bash path such as `/c/Users/you/my-job-search` works too. Check it with:

```bash
.venv/Scripts/python.exe tools/pyrite.py where
```

Then ask what's left:

```bash
.venv/Scripts/python.exe tools/pyrite.py doctor
```

It lists every profile file that's still the example's, the example's settings left in `search.toml`, each source under `[guard]` that isn't in your workspace, a master resume or letter that isn't in the form the assay reads, each "Do not use" term in `facts.md` that `forbidden` doesn't block, and whether it found the programs Pyrite uses: python-docx, LibreOffice or Word, `pdftotext`, Claude Code and its sign-in, and a mail login. The dashboard lists the same workspace items as **Finish setup** at the top of the to-do list, and the Claude run and the tailoring batch refuse to start while `facts.md` is still the example's, so no usage goes on writing for the fictional candidate.

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

## How the documents are written

Your master resume and letter, and every draft made from them, are Markdown with a few marks of Pyrite's own, one element per line. The builder turns them into Word documents, and the assay reads them, so a master that strays from this form makes every draft fail:

```text
# Your Name                                         your name, exactly as [candidate] name in search.toml
= Senior Data Engineer | Python and Postgres         optional headline under the name
@ Springfield, IL · you@example.com                  the contact line, items separated by " · "
## Summary                                           a section heading
### Acme Data | Jan 2020 – Oct 2026                  an employer and its dates
#### Senior Data Engineer | Springfield, IL | Jan 2020 – Oct 2026     a role, its place and its dates
- Cut nightly batch time from 6 hours to 2 hours.    a bullet
```

- A resume needs `## Experience` and `## Education`. Every `###` and `####` line in a draft must appear word for word in the master resume, so that's where your employers, titles and dates are set.
- A letter opens with the same `# Your Name` and `@` lines as the resume, then the letter as plain paragraphs. The assay takes the first `@` line in your approved sources as the one every document must carry.
- `~ Label` is an italic group label inside a role, and `**bold**` works inside a line.

The example's [resume](../example/profile/resume.md) and [letter](../example/profile/cover-letter.md) show the whole form, and `tools/build_resume.py` describes each mark. `pyrite doctor` says when a master is missing one of the lines the assay needs.

## A new application by hand

1. Add the posting with `pyrite add`, or the dashboard's **Add a posting**, then make its folder with `pyrite folder <id>`. That saves the posting and starts `resume.md` and `cover-letter.md` from your masters.
2. Tailor them to the posting using only facts from `profile/facts.md`. Add new confirmed facts there first.
3. Write `notes.md` with the posting link, fit and gaps.
4. `pyrite finish <id>` builds the documents and runs the assay, and marks the job ready only if it passes.

To build a document without the assay, run the builder yourself, and confirm a resume is two pages:

```bash
.venv/Scripts/python.exe tools/build_resume.py path/to/resume.md --name Your_Name_Resume_Acme --author "Your Name"
```

Cover letters use the same script with `--letter`, and should fit on one page. To build a resume and its letter together, add `--letter-source path/to/cover-letter.md --letter-name Your_Name_Cover_Letter_Acme`: Word's first PDF export in a process takes most of a minute and every later one a moment, so the pair shares one session, which is what `pyrite finish` and the daily run do.

Each build makes three files: the `.docx`, the `.pdf` and a `.txt` for the paste boxes on application sites and LinkedIn. The documents are shaped for the parsers behind applicant tracking systems (one column, standard section names, real bullet characters, nothing in headers or footers), and after the PDF is made its text is read back the way a parser reads it. The build fails if the name, a contact detail, a heading or a date range didn't survive, or if the export produced ligatures that a keyword search can't match. That read-back needs poppler's `pdftotext`, which Git for Windows includes; without it the step is skipped. `docs/resume-playbook.md` has the evidence behind the format and the writing rules, and the table of what each application system does with an upload.

The builder and its writing rules together are the drafter, and they carry a version number (`DRAFTER_VERSION` in `tools/pyrite/checks.py`). Every file built is stamped with it, in the Word document's Version and Keywords properties and the PDF's Keywords, so you can tell which rules a document was written under. `pyrite check` reports the version behind each `.docx` in a folder and warns when it isn't the current one; the dashboard shows the same under the assay result. The playbook's "Drafter versions" table says what changed in each.

## The dashboard

`tools/pyrite.py serve` runs it at <http://127.0.0.1:8787>. It only listens on this machine. On Windows, double-click `Pyrite.cmd`, which starts the dashboard if it's down and replaces it if it has hung. If another program holds port 8787, it says so and closes nothing. To start it at login, put a shortcut to `.venv\Scripts\pythonw.exe tools\pyrite.py serve` in your Startup folder, with this folder as its working directory.

The dashboard labels its parts in plain words. The code and these docs sometimes use the prospector's name each started with:

| On the dashboard | Also called | What it is |
|---|---|---|
| To do | Sluice | Today's to-do list: what needs you, most urgent first |
| Field report | | The summary each Claude run leaves at the top of the to-do list |
| Where they stand | Yield | How many jobs are at each stage now, each counted once, with the closed ones on a line below |
| Pipeline | Claims | Jobs you're working: being tailored, ready, applied and beyond |
| Ready to send | Nuggets | Drafts that passed the assay and are ready to send |
| Prospects | | New postings you haven't judged yet |
| Closed | Tailings | Jobs that are closed out: passed, rejected, ghosted or taken down |
| Sources | Veins | The job boards Pyrite reads, and whether each is working |
| Check boards now | Pan | Reading the boards and checking mail. The command is `pyrite sweep` |
| Fact check | Assay | The checker that decides whether a draft is ready |

Two buttons at the top start a run without waiting for the schedule:

- **Check boards now** reads the job boards and checks mail, as the morning sweep does. It uses no AI.
- **Run Claude now** judges the new postings and tailors the best, as the daily run does. It uses your Claude plan, so it asks first.

A third, **Tailor these now**, sits in the **Being tailored** column of the Pipeline board. It has Claude write every draft waiting there, stretch jobs included, without judging new postings and without the daily run's limit, and its result shows beside the buttons at the top. It uses your Claude plan, so it asks first. A draft that has used up its fix attempts is left alone; **Tailor this one first** on that job gives it another go.

Each runs in the background, shows its progress beside the buttons, and refuses to start while one of its kind is already going. The Claude run and the tailoring batch also refuse to start while the other is going, since both write drafts. The demo starts none of them.

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

A writing run gets everything it needs in its prompt: `profile/facts.md`, `profile/run-notes.md`, `profile/approved-terms.txt`, the model documents the run notes name in backticks (a folder means its `resume.md`, `cover-letter.md` and `notes.md`; a file path means that file), the job's `posting.md` and any draft already in its folder. That saves the six or seven turns a run used to spend reading them, each of which re-sent the whole conversation. The posting goes in fenced as job-board data, as it is everywhere else. **Refresh resume** gets the same. The run may still read the workspace, and must read a draft once before it can change it.

The older way is a Claude Code session of your own following `tools/pyrite/daily_run.md`. That session has a shell, so its rules are only instructions, and its limits are yours to set. If you use it, give it permissions that:

- allow the `pyrite` commands it needs: `queue`, `discover`, `job`, `triage`, `folder`, `finish` and `brief`
- allow edits only under `applications/` in your workspace
- deny edits to `profile/`, `data/` and this repository, and deny web access

Either way, the code holds two lines by itself. Only `pyrite finish` can mark a draft ready, and a draft changed after it passed is flagged on the dashboard.

### Filling a Workday form

No applicant tracking system lets a candidate apply through an API: Workday, Greenhouse, Lever and Ashby all take applications only through their forms, and their apply endpoints need the employer's own credentials. Workday's form is the long one, and its resume parse fills the work history badly, so a workspace can keep `profile/workday-paste.md`: every field, in page order, typed out once. Copy `example/profile/workday-paste.md` to start. Its role sections need to keep the shape the example has, a `### Work experience N` heading, a table with `Job title` and `Company` rows, and one fenced text block, because that's what the merge reads.

**Make fill sheet** on a job, or `pyrite fill <id>` (also `pyrite fill <folder>` for a folder with no job row), writes `fill-sheet.md` in the job's folder: the paste sheet with each role's description replaced by the tailored text from that job's `resume.md`, under a header that names the posting, the files to attach, the fields the sheet says to answer per application, and the lines in `notes.md` about salary, referrals or recruiters. A role the resume leaves out keeps the sheet's standard text and is marked so; a role in the resume with no section on the sheet is listed for you to add. Make it again after the resume changes. A sheet made before the assay passes the draft, or after the draft, fact bank or `[guard]` rules changed since it passed, says at the top that its role text hasn't passed the assay; check the job again and make it again. A sent job gets no new sheet, since its folder is a record.

The sheet is for you, or for a browser session you watch, to fill the form from. Nothing in Pyrite submits an application, and a fill sheet changes nothing about that: you sign in, fill each page, review it and click Submit.

**Typing it for you (experimental, off by default).** This has been tested against a fixture page with Workday's field ids, not yet on a live application, so it's off until your workspace's `search.toml` turns it on:

```toml
[workday]
autofill = true
```

Only the file can turn it on: the dashboard's Settings tab can't. Check that automated form filling is acceptable under the terms of the site you use it on. With it on, **Fill Workday form** on a job, or `pyrite autofill <id>`, opens the job's posting in a browser window of its own, waits for you to sign in and reach the form, and types the sheet in: the work history with its tailored descriptions, education, languages, the skills picker, websites, the resume upload, and the standard application questions. From the command line it pauses before saving each page so you can look; from the dashboard it goes straight through and leaves the browser open for you. Either way it reports what it left for you (the sheet's per-application answers, questions it didn't recognize, skills Workday has no entry for) and which near-matches it picked, on the job's panel and in `autofill-log.txt` in its folder, and stops at the first page it doesn't know, which is the voluntary disclosures or the review page. The button shows only for a Workday posting that hasn't been sent. It types only a draft the assay passed as it is now: a job that hasn't passed, or whose files, fact bank or `[guard]` rules changed since it passed, is refused with the reason until you check it again. On Workday's Apply menu choose **Apply Manually**; a page Workday kept as a draft is left as it is. It has no way to submit: the only footer button it presses is one that saves or continues, and a button that submits is refused. It needs Playwright once:

```bash
.venv/Scripts/python.exe -m pip install -r tools/requirements-autofill.txt
```

```bash
.venv/Scripts/python.exe -m playwright install chromium
```

Each value it types or box it ticks is read back from the page, and one the page didn't take is in the report with what the box shows. A resume counts as attached once Workday shows it as uploaded. Each run keeps a step-by-step record of the fill, starting after you sign in, in `data/browser/last-fill-trace.zip`, replacing the last run's. When a page goes wrong, replay it to see what the page looked like at each step:

```bash
.venv/Scripts/python.exe -m playwright show-trace data/browser/last-fill-trace.zip
```

The record holds your details as the pages showed them and the session's cookies, so keep it to yourself, as you would the rest of `data/`.

The browser profile lives in your workspace's `data/browser/`, so each Workday tenant's sign-in survives between runs. Every tenant customizes its form a little, so the first run on a new one may find a section this doesn't fill; it says so and leaves it to you. Workday spells some skills its own way ("Machine Learning (ML)"); the common ones are built in, and `profile/workday-skills.toml` in your workspace adds more, as `"Your name" = "Workday's name"` lines under `[skills]`. `fill-sheet.json` beside the sheet is what the run reads, so the sheet's shape matters: the sections and field names in `example/profile/workday-paste.md`.

Nothing ever applies on your behalf. Click **I applied** on the dashboard and it schedules a follow-up reminder for 7 days later. It also freezes the job: a read-only copy of `resume.md`, `cover-letter.md` and the built documents goes into the folder's `sent/`, the job leaves the ready list, and from then on nothing rebuilds, refreshes or re-checks its documents. The job shows **Frozen** with links to the sent copies, and **Changed after sending** if a file in the folder stops matching them. A second application to the same company is a new job with its own folder. For applications made before this existed, `pyrite sent <id> --from <subfolder>` keeps the copy from a subfolder you saved by hand. Log what comes back with **Got a reply**, **Interview** or **Rejected** so the numbers stay right. Reply detection points out mail worth checking, but only those buttons change a job's status.

## Deadlines and what to check before applying

Boards have no closing-date field, so the dashboard reads the posting's own words ("accepted at least until November 8, 2026", "expected to close on November 16th, 2026") and, failing that, the `**Deadline:**` line in the job's `notes.md`. A job that hasn't been sent shows **Apply by** on its card and in Prospects, red within two days. Ready drafts closing soonest lead the to-do list, and a prospect or shortlisted job closing within two days gets a **Closing soon** item even if it isn't new. Prospects can be sorted by deadline. A stated deadline that has passed shows quietly, since "at least until" often runs longer.

The job panel opens with **Before you apply** when there's something to settle: the deadline, each `**Check before applying:**` line and each item under a "Before you apply" heading in the notes, any notes line saying to do something before applying, and what you've already sent the employer. It counts your applications to each employer and warns when a job would go past `max_per_company` under `[dashboard]` in `search.toml` (3 if unset), and when a nearly identical title there has already been sent, which is usually another listing of the same job.

A ready draft whose files changed after the assay passed it shows as **Check again** in the to-do list, not **Send**, with a button that rebuilds and rechecks it there, and **Check all again** when there are several. The field report folds away, with a line saying so, once you've applied or passed on anything since it was written.

## When a posting you applied to comes down

A pan that finds a sent application's posting gone shows **Posting down** on its card and puts it on the to-do list, with when it will count as ghosted. If you've logged nothing since (no reply, interview or decision, and no next step of your own), and no possible reply from the inbox is waiting for you, the pan marks it **ghosted** once the posting has been down for `ghost_after_down_days` under `[run]` in `search.toml` (14 if unset; 0 turns it off). The timeline says the pan did it. If the posting comes back, the pan puts the job back to waiting, which it never does for a job you marked ghosted yourself. Reopen a job if they get in touch later. Ghosted jobs count beside rejections under the reply rate, never inside it.

## Going through prospects

**Tailor** and **Pass** sit on each row of Prospects, so a quick no doesn't need the panel. In the job panel, **J** and **K** step through the list you opened it from, and on a job nothing has been written for yet, **T** tailors it and **P** passes, then the next one opens. A pass shows **Undo** for ten seconds, and a passed job that hadn't been sent offers **Undo pass**, which puts it back where it was. A ready draft is only passed with the button, never a key. The first time you open a prospect it's marked as looked at; the Prospects count says how many you haven't opened, and **Not looked at yet** filters to them.

## New listings, reposts and possible ghost jobs

Prospects, the to-do list and the daily run put the newest listings first, ahead of older ones with a similar score. **Priority** is the filter score plus points for age and for a preferred city or industry, minus a penalty for each repost. The weights are under `[freshness]` and `[promote]` in `search.toml`. Priority only changes the order, and the filter score still decides what's kept and tailored.

- **New:** posted in the last 7 days, never reposted, seen by the latest pan, and with nothing else on this list against it.
- **Reposted:** the same job came back under a new listing, or the same listing came back after being taken down. The same job in another city isn't a repost. Age keeps counting from the earliest date on record, so a repost doesn't look new again. A board can also move a date forward without a pan seeing it happen, so a listing is never younger than the day a pan first found it.
- **Re-dated:** a board moved a listing's posted date forward. Only Workday and Ashby are checked, since Greenhouse and Lever report the date a listing was created.
- **Possible ghost:** up 90 days or more, reposted or re-dated twice, or reposted and up 45 days or more. The posting's own words count too: "an evergreen role we keep open on an ongoing basis", or "a pipeline role". It's a prompt to look closer, not proof: some companies keep real openings up all year. A listing with no date that a pan first found 90 days ago or more counts as up that long.
- **Not rechecked:** the latest full pan didn't see the listing. Its board failed, you took the board off your watch list, or Workday didn't answer about it in time. It may be down.
- **Possible scam:** the posting asks you to pay a fee, to talk or interview over WhatsApp, Telegram, Signal or WeChat, or says it will send you a check. A posting that says it would never do these things is warning you about scams, so it doesn't count. Postings on a company's own board almost never do this; a posting you added yourself might. It also goes on the to-do list.
- **May be a repost:** a Workday link ending in `-1` or similar, which often means a requisition has more than one posting. It's a hint only and costs no priority.

**Only listings that look real**, under Show on Prospects, hides possible ghosts, scams and listings not rechecked.

Some postings aren't openings at all, and a pan drops them as it drops a title or place you don't want: a "General Application", "Expression of Interest" or "Talent Community", or a posting that says it has no open position right now. So does a posting with a scam's tells. `pyrite rescore` drops ones already on your list that you haven't acted on. These checks were tried against about 9,000 postings from real boards, and ordinary phrases that share a word, such as "evergreen content", "building a talent pipeline" or "applications are reviewed on a rolling basis", don't count.

A board's first pan sets a baseline, so repost counts stay at zero until a later pan sees something come back.

Two postings count as one job only when their text nearly matches throughout, so openings that share a title and an "about us" paragraph stay separate. On Workday, two postings under the same requisition id with mostly the same title are one job too, since a repost there often comes back rewritten under the old id with `-1` added. Titles are compared with short forms spelled out, so "Sr. Firmware Engr" is "Senior Firmware Engineer". Workday's search returns only some of a site's postings, so each pan asks it directly about the tracked ones it left out. A posting is marked down only when Workday confirms it's gone, and one it confirms is still up isn't mistaken for a repost when the same job appears in another city.

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

## Industries

The **Industries** tab shows how each industry under `[promote]` is doing where you live, in three parts.

- **In your search** is what Pyrite has seen: postings in the last 90 days that passed your filters and count as the industry (judged as above), how many are still listed, local against remote, the employers posting most, and what came of applying. Only postings Pyrite has seen count, so it's thin for the first weeks.
- **Official numbers** come from the BLS [Quarterly Census of Employment and Wages](https://www.bls.gov/cew/), which counts nearly every job from employers' unemployment insurance filings. For your metro area, your state and the country, it shows private-sector jobs, their change over a year, workplaces, average weekly pay against all private jobs in the same area, and concentration (above 1 means the industry is a bigger share of jobs there than nationally). It's solid but runs five to six months behind, and a metro area's industry detail comes out a quarter or two after a state's, so each row names its quarter. The BLS withholds a figure that would reveal one employer's numbers, and the tab says which codes were left out. US only.
- **Outlook** is written by Claude from a web search, when you click **Research with Claude**. It covers hiring and layoffs, investment, the employers nearby, headwinds and what it means for a job search, with every point linked to its source. It's the only Claude run with web access, so it gets nothing else: no files and no shell, and nothing about you beyond the industry, the area and the employers you listed. Plain code then keeps only the points whose sources came up in that run's own searches or pages, and says how many it dropped. That can't prove a page says what a point claims, so open the source before relying on it. `pyrite outlook "<industry>"` does the same from the command line. It uses Sonnet unless `model` under `[market]` says otherwise.

To set it up, give each industry its codes on the Settings card, under **Industry codes (NAICS)**, or as `naics = ["334413", "333242"]` in `search.toml`. Look codes up at [census.gov/naics](https://www.census.gov/naics/). Codes are broad, so pick the narrowest that fit, and don't list one inside another, since its jobs would count twice. Then name where you live:

```toml
[market]
state = "Wisconsin"    # the full name
metro = "Madison, WI"  # as the BLS writes it, without "MSA"
```

The numbers are read from data.bls.gov when the tab opens and kept in `data/market/`, then looked for again after a week. No key or account is needed.

## Your profile

The **Profile** tab brings together everything Pyrite knows about you and your search. It's being built a section at a time, and until a section has its own editor, it says where to change that part instead: the Facts or Settings tab, which work as before, or a file in your workspace.

- **Needs you** lists what setup still needs, the same findings as `pyrite doctor`, each with a button to the section that fixes it.
- Each section shows what it holds now and when the Profile tab last changed it. **Where this goes** names the files and settings it writes.
- **History** lists every save made on the Profile tab, newest first. Pick a file to see what putting back its earlier copy would change, then **Put back**. Putting back is a save like any other: the file as it is now is kept too, and a copy that would let drafts say more asks for a code. The latest 50 copies of each file are kept in `data/history/`.
- A section with edits you haven't saved shows how many, with **Discard** and **Save changes**. Leaving it asks first. If a file changed on disk after the tab loaded it, the save is refused and nothing is written.
- The address names the section, as `#profile/achievements`, so a bookmark or reload comes back to it.

## Your facts

The **Facts** tab shows `profile/facts.md` and `profile/approved-terms.txt`, the two files that say what a resume may claim. The fact bank is shown a section at a time. Click **Edit** on a section, change it and **Save**, or use **Add a section**. Sections named "Do not use" and "Unsupported" are marked **Approves nothing**, because the assay never treats them as a source.

- A save takes effect the next time a draft is checked. Drafts that already passed aren't checked again by themselves.
- The file from before each save is kept beside it, as `facts.previous.md` or `approved-terms.previous.txt`.
- If the file changed on disk after the tab loaded it, the save is refused and nothing is written.
- To block a term by name, it also has to be listed under `[guard]` in `search.toml`. That can't be done from the dashboard.

The dashboard has no login, so anyone who can open it can change these two files. It only listens on this machine unless you add names under `allowed_hosts`. The demo's facts can't be changed.

### Confirming with a code

A save that would let drafts say more than before asks for a code first. On the Facts tab that's adding a line to `approved-terms.txt`, or taking an item off "Do not use" or "Unsupported". Pyrite sends a six-digit code to this computer's notifications, naming the change, and the tab asks for it. Type it in and **Confirm**, and the change is saved. Saves that only add a block, or change facts, go straight through.

- A code works once, for the change it names, for 2 minutes. Five wrong tries end it and nothing is saved. **Send a new code** replaces it.
- No notification, or Focus Assist hid it? `pyrite code` in a terminal on this computer prints the code waiting and what it's for.
- The server decides what needs a code, by comparing the files before and after, so the page can't skip it. It's not a password: anyone who can see this screen can read the code. It stops a change made from another device, or by something driving the browser, without the person at this computer seeing it named.
- Notifications come from each system's built-in route, with nothing to install: Windows PowerShell's toast, AppleScript on macOS, and `notify-send` on Linux.

## The assay

The assay is Pyrite's fact checker, named for the test that tells gold from fool's gold. `pyrite finish` won't mark a draft ready unless it passes checks that involve no AI. It blocks confidential terms, unsupported claims, numbers not in the fact bank, changed employers, titles or dates, a changed contact line, outside links and unfilled placeholders, and it enforces the page limits. Resumes are also blocked from naming a specialist term that isn't in your approved sources. If a blocked term is true of you, add it to `approved-terms.txt`. It can't catch a true fact twisted into a false impression, so reading each draft still matters.

It also warns, without blocking, about wording that readers now take as machine-written or empty: em dashes, "spearheaded", "leveraged", "results-driven" and the like, and a cover letter over 350 words. Beside the result, the dashboard shows what share of the posting's skill terms the resume uses, and says so when that share is high enough to read as copied (above about 85%) or too low for a skills filter (below about 40%).

- **What counts as a source.** Your approved sources, minus the "Do not use" and "Unsupported" sections of `facts.md`, which approve nothing. The posting never counts, and neither does its title. A resume that opens a bullet with a tool the posting names, and your sources don't, is blocked.
- **Numbers.** Digits must appear in your sources. Numbers written as words from eleven up are blocked unless your sources use the same word, so write them as digits.
- **Disclaimers.** A sentence may name an unsupported claim only to deny it: "I have not led that", or "the posting lists it, and I have not done it". "Led it with no delays" is still a claim.
- **Every line is checked.** Only your exact approved contact line is exempt, and an indented heading counts as a heading.
- **Ready means the files on disk passed.** `pyrite finish` is the only thing that marks a draft ready. If a draft's files change afterwards, the dashboard shows **Changed since checked** until you click **Check again** or run `pyrite finish <id>`. A ready draft that fails a later check goes back to blocked.
- **Drafts that keep failing.** After `fix_attempts` failed assays (6 unless you set it under `[run]`), the daily run stops retrying a draft. **Tailor this one first** gives it another set of tries.
- **Passed, with warnings.** A draft that passes but draws a warning a rewrite can clear (a letter naming terms outside your sources or borrowed from the posting, an em dash, filler wording, a long letter, or a resume using more than 85% of the posting's skill terms) gets one more Claude pass from the daily run, told to fix those and nothing else. If that pass fails the assay, the draft that passed goes back, warnings and all. The job's timeline says which happened. Warnings about a file from an older drafter are for you.

What it can still miss: a real number attached to the wrong claim, a number from one to ten written as a word, and an invented skill written in lowercase or opening a sentence without the posting naming it.

## Refreshing a resume

**Refresh resume** on a draft you haven't sent has Claude Code rewrite it for that posting, in the background. The assay and the build run afterward, and any errors go back to Claude, up to three tries. If it still fails, the earlier draft and its documents are restored. A rewrite that passes with a warning it can clear gets one more pass, as in the daily run, though the cover letter isn't this run's to change. While it runs, the previous draft is kept as `resume.previous.md` in the job's folder. It needs Claude Code installed and signed in. The demo refuses this, since a real run would spend your usage and overwrite the sample draft.

## Interview prep

**Interview prep** appears on a job once you've logged **Got a reply** or **Interview**. Claude Code writes `interview-prep.md` in that job's folder, in the background, from the posting, the resume you sent, your notes and `facts.md`. The brief covers what they're likely to ask and the true evidence to answer with, the resume lines to be ready for, each gap with an honest answer, questions to ask them, and anything odd in the posting. Open it with **Interview prep brief** on the job.

It runs under the same limits as a resume refresh: no shell, no web access, and it can write only that one file. The assay, which uses no AI, runs afterward, and any errors go back to Claude, up to three tries. The brief is private notes, so the check differs from a resume's:

- **Blocked:** confidential terms, unsupported claims, links, unfilled placeholders, and any number that's in neither your fact bank nor the posting.
- **Flagged for you to read:** a term the posting uses that isn't in your fact bank, since the brief should treat it as a gap.

If it still fails, no new brief is kept and an earlier one goes back. Like the resume check, it can't catch a true fact framed misleadingly, so read the brief against what you remember. `pyrite prep <id>` does the same from the command line.

## Claude usage

The **Sources** tab shows what the Claude runs Pyrite started have used: runs, time, tokens and cost, for the last 7 days and all time. `pyrite usage` prints the same numbers.

- **Counted:** every Claude run Pyrite starts, including runs that failed: the daily run's judging and tailoring (`pyrite run`, **Run Claude now** and **Tailor these now**), Refresh resume, Interview prep, and checking mail through the Gmail connector.
- **Not counted:** a Claude Code session of your own, such as the older way of running the daily run from `tools/pyrite/daily_run.md`, since Pyrite doesn't start it.
- **Cost** is Claude Code's own estimate at API prices. On a Claude plan it isn't a bill.

## Reply detection

`pyrite inbox` runs after each morning pan. It reads the sender, subject and date of recent Gmail messages and compares them with every active job you've applied to. A match appears as **Possible reply** on the job's card, in the to-do list and on its timeline.

A match never changes a status, so a wrong one can't affect the response rate. Read the email, then use the usual buttons if it's real, or **Dismiss** if it isn't.

There are two ways to read the mailbox. IMAP with an app password is the plain one and never downloads a message body. The Gmail connector in Claude Code needs no password on disk and also warns about job scams, at the cost of one short Claude run per pan.

### Through the Gmail connector

Set `source = "gmail"` under `[inbox]` in `search.toml`. Each pan then starts Claude Code for one narrow job: copy the sender, subject, date and snippet of recent mail, and a little of the text of mail about hiring, into one JSON list that it hands back as its closing message. That run gets only the Gmail `search_threads` and `get_message` tools, and no tool that writes, so it can't send, reply, label or delete anything, or touch a file on this machine, whatever an email tells it. The list is thrown away once judged, so message text never stays on disk or in the database. Only the Primary and Updates categories are read, since that's where replies and recruiter mail land, mail from job boards such as LinkedIn and Indeed is left out of the search, since an alert is never a reply, and the text of a message is read only when it's about hiring and comes from somewhere other than a known employer, applicant tracking system or job board. That last rule is what keeps the run cheap: a confirmation from Workday is judged from its subject and snippet alone. Plain code does the matching above, and the scam check below. The run is counted under **Checking mail** on the Claude usage panel. It uses Sonnet, since copying headers needs no judgment; `model` under `[inbox]` picks another. The first read of a week or two of mail is the longest and dearest one, since later runs only read back a couple of days past the last good one.

Setup: connect Gmail under Connectors in the Claude desktop app, sign in once with `claude auth login` in a terminal outside the app, and test it:

```bash
.venv/Scripts/python.exe tools/pyrite.py inbox
```

A Claude session that has read Gmail itself can also hand over an export in the same shape as `tools/pyrite/mail_check.md` describes, with `pyrite inbox --from <file.json>`.

**Scam warnings** appear as **Possible scam** at the top of the to-do list, with a **Possible scam** mark on the card of any job whose company the mail names, and the reasons in plain words. Only mail about hiring, or mail that names a company Pyrite has seen, is looked at. One strong sign is enough: a domain that looks like the company's but isn't, a personal address claiming to be the company, replies routed to a personal address, an interview over WhatsApp or Telegram, or any mention of gift cards, checks, fees, crypto, bank details or ID documents. Weaker signs, such as "you've been selected" wording, pressure to act within hours, link shorteners or a form to fill in, need two together. Mail from the company's own domain or a known applicant tracking system gets the benefit of the doubt on wording, because a real offer also mentions deadlines and ID checks. A warning changes nothing. Open the mail yourself, don't reply, click or pay, and **Dismiss** it if it turns out to be genuine.

### Through IMAP

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
- The scam rules work from patterns, so they miss a scam that uses none of the usual tells and can flag a blunt recruiter. They're a prompt to look closer, not a verdict.
- It flags automatic "we received your application" notices, and non-marketing mail from a company you also buy from. Mailing-list mail is skipped unless its subject is about hiring.
- If you've applied to two roles at one company, a match appears on both.
- Sender names can be forged. Treat a match as a prompt to open your mailbox, and don't follow links from the dashboard's text.

If the login or connection fails, the pan still succeeds and **Email replies** shows as failing on the Sources tab.

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

Add a line under `[watch.*]` in `search.toml` if the careers page is on Greenhouse, Lever, Ashby or Workday, then run `pyrite sources` to confirm it responds. Employers with no public feed go under `[[manual_check]]`, which lists them on the dashboard's Sources tab. Use **Add a posting** for anything you find yourself, such as on LinkedIn.
