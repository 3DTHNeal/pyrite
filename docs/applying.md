# Applying and after

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

## Deadlines and what to check before applying

Boards have no closing-date field, so the dashboard reads the `**Deadline:**` line in the job's `notes.md` and, failing that, the posting's own words ("accepted at least until November 8, 2026", "expected to close on November 16th, 2026", "accepted until 11/30/2026"). A date after "posted" or "start", or past the end of the sentence, isn't taken for the deadline. A job that hasn't been sent shows **Apply by** on its card and in Prospects: orange within `decide_days` under `[run]` (5 if unset), so there's still time to tailor, and red within two days. Ready drafts closing soonest lead the to-do list, and a prospect or shortlisted job inside that window gets a **Closing soon** item even if it isn't new, saying to tailor it or pass. The daily run judges and tailors those before anything else but your own picks. Prospects can be sorted by deadline.

A deadline is firm unless the posting words it as a floor: "accepted at least until November 8" or "or until the position is filled" says how long it stays up, not when it comes down. A notes line that restates the posting's floor date without the "at least" leaves it a floor. "No later than" counts only about applying, so "relocate no later than March 1" isn't a deadline. A date written without a year, such as "until December 1", is the one nearest today; since its year is a guess, it never passes on a job by itself, and once it has gone by it shows as a floor. Once a firm deadline has gone by, the next pan or run passes on the job, if it hasn't been sent, and says why in its timeline. **Undo pass** puts it back for good: the sweep passes on a job only once. A pan doesn't store a new posting whose own firm deadline has already gone by. Past a floor, a job shows **May close any day** for two weeks and stays on the to-do list, since it's still open but not for long.

The job panel opens with **Before you apply** when there's something to settle: the deadline, each `**Check before applying:**` line and each item under a "Before you apply" heading in the notes, any notes line saying to do something before applying, and what you've already sent the employer. Each thing to settle has a short bold label, such as **Oregon residency**, which tailoring writes at the start of each line. The to-do list and the **Check first** tag on a card show the label alone, and the panel shows it with the whole reason. Notes written before tailoring wrote labels use their first clause, without an opening such as "The posting requires". It counts your applications to each employer and warns when a job would go past `max_per_company` under `[dashboard]` in `search.toml` (3 if unset), and when a nearly identical title there has already been sent, which is usually another listing of the same job.

A ready draft whose files changed after the assay passed it shows as **Check again** in the to-do list, not **Send**, with a button that rebuilds and rechecks it there, and **Check all again** when there are several. The field report folds away, with a line saying so, once you've applied or passed on anything since it was written.

## Filling a Workday form

No applicant tracking system lets a candidate apply through an API: Workday, Greenhouse, Lever and Ashby all take applications only through their forms, and their apply endpoints need the employer's own credentials. Workday's form is the long one, and its resume parse fills the work history badly, so a workspace can keep `profile/workday-paste.md`: every field, in page order, typed out once. Copy `example/profile/workday-paste.md` to start. Its role sections need to keep the shape the example has, a `### Work experience N` heading, a table with `Job title` and `Company` rows, and one fenced text block, because that's what the merge reads.

**Make fill sheet** on a job, or `pyrite fill <id>` (also `pyrite fill <folder>` for a folder with no job row), writes `fill-sheet.md` in the job's folder: the paste sheet with each role's description replaced by the tailored text from that job's `resume.md`, under a header that names the posting, the files to attach, the fields the sheet says to answer per application, and the lines in `notes.md` about salary, referrals or recruiters. A role the resume leaves out keeps the sheet's standard text and is marked so; a role in the resume with no section on the sheet is listed for you to add. Make it again after the resume changes. A ```` ``` ```` block on the paste sheet that isn't closed ends at the next heading, and the sheet says so at the top; if the roles still don't read back as the paste sheet has them, no sheet is made, and the reason is given. A sheet made before the assay passes the draft, or after the draft, fact bank or `[guard]` rules changed since it passed, says at the top that its role text hasn't passed the assay; check the job again and make it again. A sent job gets no new sheet, from the dashboard or `pyrite fill`, since its folder is a record. Nor does a folder with a copy of what was sent in its `sent/`.

The sheet is for you, or for a browser session you watch, to fill the form from. Nothing in Pyrite submits an application, and a fill sheet changes nothing about that: you sign in, fill each page, review it and click Submit.

**Typing it for you (experimental, off by default).** This has been tested against a fixture page with Workday's field ids, not yet on a live application, so it's off until your workspace's `search.toml` turns it on:

```toml
[workday]
autofill = true
```

Only the file can turn it on: the dashboard's Settings tab can't. Check that automated form filling is acceptable under the terms of the site you use it on. With it on, **Fill Workday form** on a job, or `pyrite autofill <id>`, opens the job's posting in a browser window of its own, waits for you to sign in and reach the form, and types the sheet in: the work history with its tailored descriptions, education, languages, the skills picker, websites, the resume upload, and the standard application questions. From the command line it pauses before saving each page so you can look; from the dashboard it goes straight through and leaves the browser open for you. Either way it reports what it left for you (the sheet's per-application answers, questions it didn't recognize, skills Workday has no entry for) and which near-matches it picked, on the job's panel and in `autofill-log.txt` in its folder, and stops at the first page it doesn't know, which is the voluntary disclosures or the review page. When a list has no entry with the sheet's wording, such as a field of study, school, skill or degree, it takes the one entry that starts with, or else contains, that wording as whole words (case, punctuation and "&" for "and" don't matter, and a one-word name doesn't count) and names it as a pick to check. If several entries do, or the nearest only share some words with it, the field is left for you with what the list offers, each entry in quotes. The button shows only for a Workday posting that hasn't been sent. It types only a draft the assay passed as it is now: a job that hasn't passed, or whose files, fact bank or `[guard]` rules changed since it passed, is refused with the reason until you check it again. On Workday's Apply menu choose **Apply Manually**; a page Workday kept as a draft is left as it is. It has no way to submit: the only footer button it presses is one that saves or continues, and a button that submits, sends, or agrees to or accepts terms is refused. A question the sheet doesn't answer closely is left for you: one asked the other way round ("under 18"), about someone else ("a relative who worked here"), or about experience with something the sheet's row doesn't name. It needs Playwright once:

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

## After you apply

Nothing ever applies on your behalf. Click **I applied** on the dashboard and it schedules a follow-up reminder for 7 days later. It also freezes the job: a read-only copy of `resume.md`, `cover-letter.md` and the built `_Resume_` and `_Cover_Letter_` documents goes into the folder's `sent/`, put in place only once every file is copied, the job leaves the ready list, and from then on nothing rebuilds, refreshes or re-checks its documents. The job shows **Frozen** with links to the sent copies, and **Changed after sending** if a file in the folder stops matching them. If you changed the folder on purpose, for instance to keep it as a model for later applications, **Got it** stops the warning for the files as they are now; it comes back if they change again, and the sent copies stay the record either way. A second application to the same company is a new job with its own folder. For applications made before this existed, `pyrite sent <id> --from <subfolder>` keeps the copy from a subfolder you saved by hand. Log what comes back with **Got a reply**, **Interview** or **Rejected** so the numbers stay right. [Reply detection](mail.md) points out mail worth checking, but only those buttons change a job's status.

After applying, find the hiring manager and send one short note within a few days. Log it under **Reaching out** in the job panel with **Reached out**: the day (today unless you change it), who it went to and what you sent or asked, both optional. It goes in the job's timeline, the card shows **Reached out**, and the status stays as it is. Applications one to three days old with nothing logged share one **Reach out** item at the bottom of the to-do list, naming the one whose window closes first and counting the rest. `reach_out = false` under `[dashboard]` in `search.toml` leaves it off. Logging it moves the follow-up reminder to 7 days after the later of the application and the note, so it comes a week after you last made contact; a next step you set yourself is left alone. Log each later note the same way. `pyrite outreach <id> --to "the hiring manager" --note "..."` does it from the command line, with `--on YYYY-MM-DD` for a day before today.

## When a posting you applied to comes down

A pan that finds a sent application's posting gone shows **Posting down** on its card and puts it on the to-do list, with when it will count as ghosted. If you've logged nothing since (no reply, interview or decision, and no next step of your own), and no possible reply from the inbox is waiting for you, the pan marks it **ghosted** once the posting has been down for `ghost_after_down_days` under `[run]` in `search.toml` (14 if unset; 0 turns it off). The timeline says the pan did it. If the posting comes back, the pan puts the job back to waiting, which it never does for a job you marked ghosted yourself. Reopen a job if they get in touch later. Ghosted jobs count beside rejections under the reply rate, never inside it.

## Interview prep

**Interview prep** appears on a job once you've logged **Got a reply** or **Interview**. Claude Code writes `interview-prep.md` in that job's folder, in the background, from the posting, the resume you sent, your notes and `facts.md`. The brief covers what they're likely to ask and the true evidence to answer with, the resume lines to be ready for, each gap with an honest answer, questions to ask them, and anything odd in the posting. Open it with **Interview prep brief** on the job.

It runs under the same limits as a [resume refresh](assay.md#refreshing-a-resume): no tools at all, with the files it needs in its prompt, and the brief handed back in its closing message for Pyrite to write. The assay, which uses no AI, runs afterward, and any errors go back to Claude, up to three tries. The brief is private notes, so the check differs from a resume's:

- **Blocked:** confidential terms, unsupported claims, links, unfilled placeholders, and any number that's in neither your fact bank nor the posting.
- **Flagged for you to read:** a term the posting uses that isn't in your fact bank, since the brief should treat it as a gap.

If it still fails, no new brief is kept and an earlier one stays. Like the resume check, it can't catch a true fact framed misleadingly, so read the brief against what you remember. `pyrite prep <id>` does the same from the command line.
