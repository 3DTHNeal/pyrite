# Changelog

What changed in each release that you'd notice when running Pyrite. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/): until 1.0, a minor version may change the workspace's files or `search.toml` and says so here.

## [Unreleased]

### Added

- **Reached out** in the job panel of a sent application logs a note to the hiring manager or a recruiter: the day, and who and what if you like. It shows in the timeline and on the card, an application one to three days old with nothing logged gets a **Reach out** to-do item, and the follow-up reminder moves to a week after the note. `pyrite outreach <id>` logs one from the command line.
- The database records which scoring its prospects have. When an update changes how postings are scored, the next pan rescores the prospects you haven't acted on, so none keeps an old score or reason, and names any it dropped beside the sweep's result.
- A **Profile** tab, the start of one place for the fact bank and the search settings. It lists each section with what it holds now, a **Needs you** list of what setup still needs with a button to the section that fixes it, and a **History** of every save it makes, where any file's earlier copy can be compared and put back. Sections whose editors aren't built yet say where to make the change meanwhile. The Facts and Settings tabs work as before.
- Editors on the Profile tab for **Name and contact**, **Work history**, **Off limits** and **Skills and terms**. Each change is entered once and written everywhere it belongs: a role to the Timeline in `facts.md` and the headings of `profile/resume.md`, a blocked term to "Do not use" and the `forbidden` pattern that blocks it. Before you save, each shows what will change in every file, worked out by the same code a save uses, and Off limits has a box that shows how the assay reads any sentence. Taking anything off Off limits, or approving a term, asks for a code.
- Profile tab editors for **Achievements**, with an achievement builder that writes one fact line and keeps where it was measured as a wording rule in `run-notes.md`, and **Master resume**, which edits the master resume and letter a block at a time and runs the fact check on them as you type, naming anything only the master says.
- Saves on the Facts tab that would let drafts say more, such as approving a term or taking an item off "Do not use", ask for a six-digit code that Pyrite sends to this computer's notifications, naming the change. `pyrite code` prints the code waiting when the notification doesn't show. A code works once, for that change, for 2 minutes.
- An **Industries** tab: for each industry under `[promote]`, what Pyrite has seen of it, the official BLS employment, pay and growth figures for your metro area, state and the country, and an outlook Claude researches on the web on request, keeping only points whose sources turned up in its own search. Add `naics` codes to each industry and a `[market]` section with your state and metro area to `search.toml`. `pyrite outlook "<industry>"` writes the outlook from the command line.
- `pyrite init <folder>` makes a workspace from the example's profile, without its fictional applications or allowed hosts, and points `.pyrite-home` at it.
- `pyrite doctor` and the dashboard's Finish setup list also name the example's settings left in `search.toml`: its local places, confidential and unsupported terms, ordinary words, the degree every resume is expected to name, preferred cities and mail domains.
- `pyrite --help` lists where to start, and each job id argument says what it is.
- `pyrite doctor` and Finish setup check the master resume and letter for the lines the assay needs (`# Name`, the `@` contact line, `## Experience`, `## Education`, an employer heading) and name what's missing, instead of leaving every draft to fail. They name each "Do not use" term in `facts.md` that `forbidden` doesn't block, the example's tracks and industries left in `search.toml`, and a `workday-paste.md` that's still the example's.
- docs/operating.md has a "How the documents are written" section on the form of a resume and letter.
- `pyrite help`, and `pyrite help <command>` for one command. `pyrite` on its own prints the help instead of an error.
- A mistyped command suggests the one meant, such as `pyrite doctor` for `dcotor`, and a value with a space left out of quotes, such as `--name Alex Rivera`, says to quote it.
- `pip install -r requirements.txt` works from the top of the repository.
- A pan drops postings that aren't openings: a "General Application", "Expression of Interest" or "Talent Community", or one that says it has no open position right now. It also drops postings with a scam's tells: a fee to pay, an interview over WhatsApp or Telegram, or a check sent to you. `rescore` drops ones already listed that you haven't acted on.
- **Possible scam** on a posting with those tells, such as one you added yourself, and a to-do item for it.
- **Not rechecked** on a listing the latest full pan didn't see, because its board failed, left the watch list or didn't answer. It may be down.
- **Possible ghost** also covers a posting that calls itself an evergreen or pipeline role, and a listing with no date that a pan first found 90 days ago or more.
- Mail scam warnings catch task scams (paid "jobs" rating apps or products), a check sent to buy equipment, and interviews over a chat.
- The job panel shows the job's number, such as **Job 56**, which the `pyrite` commands take. While it's open the address ends in `#job-56`, so a bookmark or a link in a note opens that job, and closing it puts back the tab you were on.
- **Got it** on a job whose folder changed after sending, for a folder you reworked on purpose. It stops the warning for the files as they are now, and the warning comes back if they change again. The sent copies stay the record.

### Changed

- `rescore` no longer drops a prospect you've acted on (a note, a next step, a pick, a fit verdict or a status of your own, such as one put back by **Undo pass**). It says how many it kept that way, and names the ones it dropped.
- **New** needs the latest pan to have seen the listing and nothing marking it as a possible ghost.
- A listing is never younger than the day a pan first found it, so a date a board moved forward without a pan seeing it can't make it look new.
- Two Workday postings under the same requisition id with mostly the same title are one job, so a rewritten repost is counted as one, and titles are compared with short forms such as "Sr." and "Engr" spelled out.
- Prospects' **Hide possible ghosts** is now **Only listings that look real**, and hides scams and listings not rechecked too.

- `pyrite folder` starts `resume.md` and `cover-letter.md` from your masters. It never replaces a draft already there, and the daily run's folders are made as before.
- `pyrite doctor` wraps its lines to the terminal and, run outside a venv, says to make one rather than install into that Python. The README's setup starts with the venv.
- Commands that need a workspace, `doctor` and `Pyrite.cmd` point to `pyrite init` when there isn't one, and `Pyrite.cmd` says so at once instead of after half a minute. `pyrite init` on the workspace already in use exits cleanly.
- The build says "1 page", not "1 pages", and the test run prints nothing but its result.
- Help and the messages that point to `pyrite init` show a real folder, `../my-job-search`, instead of `<folder>`, which a shell reads as redirection when it's copied as it is. The help says to type `python tools/pyrite.py` until `pip install -e .` adds the `pyrite` command.
- `pyrite init` refuses a placeholder name such as "Your Name" or a placeholder folder, and for a folder inside the repository, says how to put it beside it instead. `doctor` and Finish setup flag a placeholder name left in `search.toml`.
- `pyrite doctor` lists the profile files still the example's as one finding instead of five, and ends with how many things are left.
- A profile file edited only here and there still counts as the example's while it keeps three or more of the example's sentences. Before, removing the note at the top of `facts.md` that says it's fictional made `doctor` and Finish setup call it yours and let the Claude runs start, with every fictional employer and number still in it. `doctor` quotes one of the lines left.
- `pyrite init` needs `--name`, and puts the name on the `# Name` lines of the master resume and letter as well as in `search.toml`. The top of the new `search.toml` no longer says it's the fictional candidate's.
- Run Claude now and Tailor these now are disabled, with the reason as their tooltip, while `facts.md` is still the example's, rather than asking to use your Claude plan and then refusing. The Finish setup item for the fact bank opens the Facts tab.
- The assay names an unfilled placeholder such as `[X]` once, not again as a term missing from your approved sources.
- CONTRIBUTING's commands use the venv, and say how to turn on the pre-push privacy check.
- The dashboard says to keep its window open and that Ctrl+C stops it, and Ctrl+C stops it without a traceback.

- `pyrite seed` refuses a `seed.toml` that's still the example's. An application it imports with no `applied_on` goes under Being tailored, where `pyrite finish` checks it, instead of Ready to send, so ready still means the assay passed it.
- `pyrite add` says which job it added and what to run next, and a posting file it can't read stops it with a message instead of a traceback.
- `pyrite finish` says it's building before Word's slow first export, and `finish` and `check` say in words when a resume uses so many of the posting's skill terms that it reads as copied.
- `pyrite where` says when it has fallen back to the example.
- The demo's Check boards now and Run Claude now buttons are disabled, since the demo starts no runs.
- The dashboard keeps the tab you're on in the address, so a reload or a bookmark comes back to it, and the arrow keys move along the tabs. The Prospects filters and sort are remembered in the browser.
- The browser tab's title shows how many things are on the to-do list, and the dashboard catches up as soon as you come back to its tab instead of on the next minute.
- `/` jumps to the Prospects search. Enter in the Add a posting form adds it.
- Closing the job panel puts focus back on the card or row that opened it.
- A fit reason is kept whole. Cards, the to-do list and the Closed table show its start, and the job panel shows all of it. Before, it was cut at 400 characters when it was saved, which often lost the gap that decided the fit. Reasons an early version cut at 300 characters, through a word, now end with an ellipsis.
- The Settings tab shows the points a city or industry without its own gets, as `10 (default)`, and updates it as you change the default. **Matches now** says how many points each city adds.
- Prospects shows pay as `$256k–$361k` instead of the posting's `$255,850.00-361,200.00 USD`, with `/hr` for hourly pay and the currency for other dollars. The posting's own words are in the tooltip, and pay it can't read is shown as written.
- Prospects search also matches the location.
- The header gives the board check one line, not a second one when you started it yourself, and says when mail couldn't be checked apart from the boards that failed.
- Workday autofill takes the one entry that starts with, or contains, the sheet's wording when a list has none with that wording exactly, such as `Supply Chain & Logistics Management` for a field of study of `Supply Chain and Logistics`, and lists it under picks to check. Entries that only share words with it, such as `Electronic and Electrical Engineering` for `Electrical and Computer Engineering Technology`, are suggested, never picked. The entries a field left for you lists are each in quotes, so `'Business Administration, Management'` reads as one entry, not two.

### Fixed

- Refresh resume and Interview prep no longer depend on Claude Code honoring an edit rule for one file, which headless runs on one Windows machine refused. Claude gets no tools, hands the document back in its closing message, and Pyrite writes it. An answer with no document in it is asked for again, then fails with the reason on the dashboard instead of looking like a run that changed nothing.
- The pre-push hook works in a `git worktree` that has no `.venv` of its own: it uses the main checkout's venv, then `python3` or `python` if one is 3.11 or newer, and skips the Microsoft Store's placeholder. With none of those it says how to point it at a Python with `git config pyrite.python`, instead of failing on the Store's message.
- A job number that isn't in the database, given to `pyrite job`, `status`, `sent`, `refresh`, `prep`, `triage`, `folder`, `finish`, `fill` or `autofill`, gets one line saying so and a non-zero exit, instead of a Python traceback. The line points at the dashboard, which lists every job, and at what `pyrite queue` actually shows: the ones waiting on a run.
- Finish setup no longer takes words from an explanation under "Do not use" for secret names. It used to name your own name, a site mentioned in passing and an instruction such as "Say", and suggest forbidding them, which would have failed every draft. Asides in parentheses, quoted wording, the first word of each sentence and the words of `[candidate] name` are skipped.
- Reply detection skips the receipts an application sets off, such as "You have successfully applied", "Thank you for applying" and candidate-account password and code mail. "Thank you for your interest" is still flagged, since rejections often say it. When mail matches several applications at one company and its subject names one title, only that application gets it.
- The Gmail mail check tries once more when Claude writes its tool call out as text instead of making it. A run that hands back no usable list is counted as failed in Claude usage, and `pyrite doctor` says when the last mail check failed.
- The Industries tab counts a rejection as hearing back, not as a reply, the same as the dashboard's Reply rate.
- **Add a posting** with the link of a job already tracked opens that job instead of adding it again, which would have tailored it a second time.
- A score's skills reason names the words the posting used, such as "manage a team", instead of a mangled pattern such as "managw+ (a ". A keyword that matched inside another word now shows that word, so the mistake is visible.
- The example's PID and LLM keywords no longer match inside "rapid" and "enrollment". In a real run of 116 postings, every extra hit they made was one of those two words. Copy the patterns if your `search.toml` started from the example: `'\bpid\b|\bpi control'` and `'\bv?llm|large language model'`.
- On Windows, a second dashboard on a port already in use no longer starts beside the first, with requests going to either one. It stops and says the port is taken.
- Notes and a next step typed in the job panel but not saved are no longer thrown away when another button redraws the panel, when you step to the next job or when you close it. They show "Not saved yet" until saved, and leaving the page asks first.
- A double click or a held key can no longer send the same action twice: the job panel's buttons, the Prospects row's Tailor and Pass, and Add a posting wait for the first one to finish.
- Escape in the Add a posting form no longer closes the job panel behind it as well.
- A listing whose board gave no date at first, and one later, now gets that date and an age, instead of staying undated.
- The assay judges every mention of an unsupported claim in a sentence, not only the first, so "I have not worked under X, but led X audits" is blocked.
- Praise after a claim is no longer read as a denial: "Led X, and I could not be prouder of it" or "...and I never missed one" is a claim of X. A negative before a new subject, as in "With no budget I led X", denies nothing either.
- A number keeps its scale: $3M, 212K and "3 million" are checked as those values, not as 3 and 212, in a resume, a letter and a brief alike. 1.5M and 1,500,000 are the same number.
- "35 percent" is checked as a percentage, as 35% is, and a number the fact bank holds only as a percentage no longer approves a count such as "35 engineers".
- "Doubled", "tenfold", "double-digit" and "an order of magnitude" must come from the fact bank, as numbers do.
- The interview brief is checked for spelled-out numbers and multiples, as the resume and letter are.
- An accent or a look-alike letter from another alphabet, such as Cyrillic or Latin small capitals, can no longer hide a confidential name or an unsupported claim. A word spelled in look-alike letters is blocked. Names with letters of their own, such as Søren or Işık, pass as before.
- A "Do not use" or "Unsupported" section in `facts.md` approves nothing at any heading level, subsections included. Before, only a `##` heading was set aside. `pyrite doctor` reads "Do not use" the same way.
- The company and role a draft is allowed to name are set aside only as whole words, so a company called Meta no longer hides part of "Metadata" from the checks.
- A passed draft shows as changed since checked when `facts.md`, another approved source or the `[guard]` rules change after it passed, and reopening it no longer puts it back to ready. Passes from before this keep their verdict.
- Workday autofill types role text only from a draft the assay passed as it is now. A job never checked, one whose last check failed, or one whose `resume.md`, other checked files, fact bank or `[guard]` rules changed since the pass is refused, and the dashboard's Fill Workday form button says why. A worker started before such a change stops and logs why.
- A fill sheet made from a draft the assay hasn't passed, or whose pass no longer covers it, is still written, but it says at the top that its role text hasn't passed the assay and why, and so do the job's history and `pyrite fill`. `pyrite fill <folder>` says no pass was looked up.
- Prospects says `1 posting`, not `1 postings`.
- At about 1000px wide, Prospects' **Tailor** and **Pass** stay in view at the right edge instead of scrolling off it.

## [0.1.0] - 2026-11-09

The first public release.

### Added

- The morning pan: Greenhouse, Lever, Ashby and Workday boards read, filtered and ranked, with reposts and likely ghost jobs flagged.
- The daily run: Claude Code judges new postings and tailors a resume and cover letter for the best ones, each with tools it can't use to apply, send or browse.
- The assay, a deterministic fact checker every draft must pass before it's marked ready. It blocks confidential terms, unsupported claims, numbers and skills missing from the fact bank, links, placeholders and rewritten job history.
- A local dashboard: to-do list, funnel, pipeline, settings and fact bank editing, Refresh resume and interview prep.
- Read-only reply detection over IMAP or the Gmail connector, with scam warnings.
- Fill sheets for application forms, and an experimental Workday autofill that is off by default.
- `pyrite demo`, which serves a fictional candidate with nothing installed.
- `pyproject.toml`: `pip install -e .` adds a `pyrite` command, and `pyrite --version` prints the version.

### Security

These were found in a review before release, and each has a test that keeps it fixed.

- The assay no longer takes any negative earlier in a sentence as a denial. "With no added headcount, cut defects by 83%" was passing, and so were its numbers. A denial now has to sit right next to the claim, and a first-person denial after a claim has to point back at it.
- The assay refuses invisible characters and words that mix alphabets, and reads a word split by Markdown emphasis as the whole word. Full-width digits, numbers inside emphasis and years inside a written-out date are checked as numbers. Link shorteners and chat handles, such as `bit.ly/...` and `t.me/...`, count as links.
- Reopening a closed job makes it ready only if its last assay verdict was a pass and nothing has changed since. It used to restore ready from the job's history alone.
- Lever and Ashby postings go through the same hidden-text filter as the others, by reading their HTML rather than the boards' plain text. The filter also removes Unicode tag characters, sees through whitespace and comments in inline styles, and no longer drops visible text styled `font-size:0.9em` or `opacity:0.5`.
- Interview prep no longer reports success when Claude left an earlier brief in place without writing a new one.
- The dashboard refuses a negative `Content-Length` instead of holding a thread open waiting for it.
