# Changelog

What changed in each release that you'd notice when running Pyrite. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/): until 1.0, a minor version may change the workspace's files or `search.toml` and says so here.

## [Unreleased]

### Added

- **Settings** now holds how Pyrite runs, in a menu of its own: **Claude** (whether Claude Code is signed in, and the models), **Mail** (IMAP or the Gmail connector, how far back to read, and whether the last read worked), **Daily run** (how many postings are judged and resumes written each morning) and **Dashboard** (the reminders, and whether to look for updates). Each save changes only the keys you changed in `search.toml` and keeps every other line and comment. The cities and industries that used to fill the tab are its last section, **Cities and industries**, and work as before.
- `model` and `effort` under a new `[claude]` table in `search.toml` choose which Claude model judges postings and writes drafts, and how hard it thinks, for the daily run, Refresh resume and Interview prep. Left out, Claude Code's own default is used. A value Claude Code wouldn't take is named when the file loads.
- [docs/technique.md](docs/technique.md) sets out the technique behind the assay as rules you could use on another agent, with a diagram, and shows how the check is measured. `tools/tests/test_assay_probe.py` is that measurement: 124 lines, each added to the example's passing resume and letter. Run it for the table. It runs with the tests and fails if the number the assay stops in any class moves.
- **Gaps to answer** on the Profile tab, and `pyrite gaps`: the requirements your applications' notes keep listing as gaps, grouped by their words with no AI and ranked by how many applications raised them. A yes adds your own words to `facts.md` as a fact, a no adds a line under "Unsupported", and either way the drafts you haven't sent that list the gap get a **Rework** item on the to-do list. `pyrite gaps answer` answers from a terminal. Tailoring now opens each numbered gap in the notes with the requirement in bold, so the same gap reads the same way across applications.
- **Update available** at the top of the dashboard when GitHub's `main` has commits your copy of Pyrite lacks. It lists what they say, and one click fast-forwards the code, installs the packages again if `tools/requirements.txt` changed, and restarts the dashboard on the new code. A code folder left on a branch whose commits are all in GitHub's `main`, such as a merged pull request's, is switched to `main` first, and the button says so. It does nothing with edits to tracked files, with commits GitHub's `main` lacks, or while a run is going: it says which, and the git commands to run, and **Check again** reads the folder again. The check is a `git fetch` once an hour, and `check_updates = false` under `[dashboard]` turns it off.
- A posting past its own firm deadline is a pass: the pan doesn't store a new one, and the next pan or run passes on a job you haven't sent, once, so **Undo pass** sticks. "Accepted at least until" is read as a floor, not a deadline, and past it the job shows **May close any day**.
- `decide_days` under `[run]` (5 if unset): a job closing within that many days goes on the to-do list as **Closing soon**, saying to tailor it or pass, and the daily run judges and tailors it before the rest.
- Pay is judged against the position: each range is compared with what postings for the same track at the same level have paid. One too low to bother with sinks in priority and isn't judged by the daily run unless you pick it, one under the going rate ranks lower, and one well above similar roles is marked, as is a range wide enough to span levels. `[pay]` in `search.toml` sets the currency compared.
- Asks for more years of a skill than it has existed, such as "8+ years of AI agents", show as **Asks the impossible** rather than as your gap, and Claude is told the age of each young skill a posting asks for when it judges and tailors. `pyrite skills` lists the ages Pyrite knows. `research = true` under `[skills]` has the daily run look up the ones it doesn't, on the web, keeping only dated answers with a source the run found. `pyrite skills --research` and `pyrite skills "<skill>"` do it on request.
- **Rare near you**: a local role in a track that rarely comes up nearby ranks higher, by `rare_points` under `[freshness]`.
- The job panel's **What Pyrite read into it** gives the sentences behind the pay, rarity and skill-age tags.
- `reach_out = false` under `[dashboard]` leaves the **Reach out** reminders off the to-do list.
- **Reached out** in the job panel of a sent application logs a note to the hiring manager or a recruiter: the day, and who and what if you like. It shows in the timeline and on the card, an application one to three days old with nothing logged gets a **Reach out** to-do item, and the follow-up reminder moves to a week after the note. `pyrite outreach <id>` logs one from the command line.
- The database records which scoring its prospects have. When an update changes how postings are scored, the next pan rescores the prospects you haven't acted on, so none keeps an old score or reason, and names any it dropped beside the sweep's result.
- A **Profile** tab, the start of one place for the fact bank and the search settings. It lists each section with what it holds now, a **Needs you** list of what setup still needs with a button to the section that fixes it, and a **History** of every save it makes, where any file's earlier copy can be compared and put back. Sections whose editors aren't built yet say where to make the change meanwhile. The Facts and Settings tabs work as before.
- Editors on the Profile tab for **Name and contact**, **Work history**, **Off limits** and **Skills and terms**. Each change is entered once and written everywhere it belongs: a role to the Timeline in `facts.md` and the headings of `profile/resume.md`, a blocked term to "Do not use" and the `forbidden` pattern that blocks it. Before you save, each shows what will change in every file, worked out by the same code a save uses, and Off limits has a box that shows how the assay reads any sentence. Taking anything off Off limits, or approving a term, asks for a code.
- Profile tab editors for **Achievements**, with an achievement builder that writes one fact line and keeps where it was measured as a wording rule in `run-notes.md`, and **Master resume**, which edits the master resume and letter a block at a time and runs the fact check on them as you type, naming anything only the master says.
- Saves on the Facts tab that would let drafts say more, such as approving a term or taking an item off "Do not use", ask for a six-digit code that Pyrite sends to this computer's notifications, naming the change. `pyrite code` prints the code waiting when the notification doesn't show. A code works once, for that change, for 2 minutes.
- An **Industries** tab: for each industry under `[promote]`, what Pyrite has seen of it, the official BLS employment, pay and growth figures for your metro area, state and the country, and an outlook Claude researches on the web on request, keeping only points whose sources turned up in its own search. Add `naics` codes to each industry and a `[market]` section with your state and metro area to `search.toml`. `pyrite outlook "<industry>"` writes the outlook from the command line.
- `pyrite init <folder>` makes a workspace from the example's profile, without its fictional applications or allowed hosts, and points `.pyrite-home` at it.
- `pyrite init --blank` writes the profile files with headings and a comment on what goes where instead of the fictional candidate's content, and `search.toml` with every setting that describes the candidate emptied. `pyrite doctor` and Finish setup then name what's still blank, and say when `search.toml` has no roles under `[[track]]` or no companies to watch.
- `places` under `[location]` and `titles` under each `[[track]]` in `search.toml` take plain place names and job-title words, each matched as whole words in any case, so a search can be set up without writing regular expressions. They work beside the `local` and `title` patterns. `init --blank` starts with `places`, and its example track uses `titles`.
- `pyrite import-resume <file>` drafts your master resume in Pyrite's form from the `.docx`, PDF or `.txt` resume you have, with notes on each line it had to guess at, for you to correct. `--save` writes it to `profile/resume.md`, keeping the old copy in the Profile tab's History.
- `pyrite init --git` makes the workspace a git repository of its own, with a `.gitignore` for SQLite's working files, the `*.previous.*` copies, the autofill browser profile, the BLS downloads and Word's lock files. It keeps `data/pyrite.db`, which can't be regenerated, and says so. It never adds a remote or pushes. Run on the workspace in use, it does only this.
- `pyrite open` opens the dashboard in the browser on any system, starting it in the background if it isn't running and replacing it if it has stopped answering. `Pyrite.cmd` is now a wrapper around it.
- `port` under `[dashboard]` in `search.toml` sets the dashboard's port for `serve`, `open`, `Pyrite.cmd` and the systemd unit. It's 8787 if unset.
- `pyrite doctor` and the dashboard's Finish setup list also name the example's settings left in `search.toml`: its local places, confidential and unsupported terms, ordinary words, the degree every resume is expected to name, preferred cities and mail domains.
- `pyrite --help` lists where to start, and each job id argument says what it is.
- `pyrite doctor` and Finish setup check the master resume and letter for the lines the assay needs (`# Name`, the `@` contact line, `## Experience`, `## Education`, an employer heading) and name what's missing, instead of leaving every draft to fail. They name the example's tracks and industries left in `search.toml`, and a `workday-paste.md` that's still the example's.
- docs/documents.md describes the form a resume and letter are written in.
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
- On a terminal, `pyrite discover`, `rescore`, `queue`, `job`, `check`, `finish`, `fill` and `usage` say what they found in a few lines of words, such as how many postings a pan read, how many were new and why the rest were filtered out. `--json` prints the JSON as before, and so does any run whose output goes to a file or another program, so the daily run, scheduled pans and scripts see no change. `pyrite sources` takes `--json` too.
- A logo and icons. The dashboard has a favicon, and a pixel-art pyrite crystal beside its title that glints now and then and throws sparks while a board check, Claude run or tailoring batch is going. With reduced motion turned on, it holds still. Each stage of **Where they stand** has an icon from a fire assay, from the gold pan for prospects to the cupel's gold bead for an offer. `art/icons/build.py` draws them all.

### Changed

- The code that confirms a change now explains itself. Its notification is titled **Pyrite code: 123 456** and says to type it into the dashboard where it's asking, and what it confirms. On Windows its button reads **Close** instead of Dismiss, since closing it accepts or refuses nothing. The box on the dashboard says the code came as a notification, where to find it again, and labels the space to type it in.

- The dashboard is laid out as an app. A rail down the left names every view, with counts beside To do, Prospects, Closed and failing Sources, and each pipeline stage under Pipeline opens the board at its column. To do is the first view, with the key numbers on one line beside its name. The masthead's paragraphs of status are one line in a bar along the top, which opens to the full story and the **Check boards now** and **Run Claude now** buttons. The stat tiles and the **Where they stand** panel are gone, since the rail carries their numbers, and the board's columns run to the bottom of the window.
- The guide in `docs/operating.md` is now a page per topic, indexed by [docs/README.md](docs/README.md): setting up, writing the documents, the dashboard, finding and ranking postings, the assay, applying and after, your profile and facts, scheduling and Claude runs, reply detection and the common commands. `docs/operating.md` says where each of its sections went, and `pyrite doctor` and the other messages that named it point at the page that now has the answer. The dashboard page has a table of what each colour means.
- The dashboard takes its look from the icons: warm paper and ink in light mode, warm charcoal in dark, and brass for the primary buttons, the selected tab, the funnel's bars and anything that wants you. The masthead has the pixel wordmark beside the crystal. Information tags such as a preferred city are teal and warnings orange, so neither reads as a brass button. Each Pipeline column and the job panel show their stage's icon, the to-do kinds are coloured tags, and an empty to-do list, Prospects search or Closed tab shows the icon of what would be there.
- **Reach out** is one to-do item however many applications are due a note, naming the one whose window closes first and counting the rest, below the other items.
- The systemd sweep unit runs `pyrite sweep`, the same sweep as the dashboard's button, so a timed sweep and one you start can't overlap.
- A place under `places` that ends in a US state matches the state written out or first: "Madison, WI" also matches "Madison, Wisconsin" and "US-WI-Madison". Periods and parentheses count as spaces, so "St. Louis" matches "St Louis".
- A `**Deadline:**` line in a job's notes.md now wins over the date read from the posting.
- The example search.toml ties Madison to Wisconsin, and its `agent`, `field` and `store` patterns no longer catch "Insurance Agent", "Field Robotics" or "Object Store".
- Scoring version 2: the next pan rescores prospects nobody has acted on.
- History offers **Put back this whole save** for a save that changed several files, and warns that putting back one of them leaves the others as they are.
- The job panel works as a dialog: the page behind it can't be clicked or tabbed to while it's open, and closing it returns focus to the job you opened.
- In `approved-terms.txt`, a line starting with `#` is a comment and approves nothing. The Facts tab says so, and adding one needs no code.
- The assay blocks each capitalized name listed under "Do not use" in `facts.md`, so a name is written once and needs no pattern under `[guard] forbidden`. The error names where it's listed. A name your sources also state as fact isn't blocked this way, since every draft that states it would fail, and `pyrite doctor` and the Off limits section name it instead of asking for a pattern for every term.
- `<!-- comments -->` in a fact bank or master approve nothing, and a comment under Contact isn't taken for the contact line.
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

- Adding an employer under **Work history** that your master resume already names, as it does after `pyrite import-resume`, no longer adds it to the resume a second time. The heading and its bullets stay, and only the roles under it are brought into line with what you typed.
- A `[[track]]` in `search.toml` with no `name`, or with `title`, `local`, `exclude_titles` or another list of patterns written without its brackets, is named with how to write it. Before, a role with no name failed on the first posting it matched, and a pattern without brackets was read a letter at a time, which kept nearly every posting.
- **Finish setup** items on the to-do list open the Profile section that fixes them. Most did nothing when clicked. One that's fixed only in a file is shown as text.
- The Claude runs wait until `facts.md` has at least one achievement and the master resume is filled in, and say which is missing. A contact line alone used to count as a fact bank, so a run could spend usage on drafts with nothing to write from. `pyrite doctor` and the to-do list name a fact bank with no achievements.
- The assay stops what a set of 124 fabricated lines showed it missing. A confidential name joined by a non-breaking hyphen, a dash, an underscore, a slash, two spaces or full stops between its letters is blocked, in a cover letter as on a resume, and so is a name listed under "Do not use" split the same way. Patterns already in `search.toml` read this way with no change. Praise worded as a denial no longer excuses an unsupported claim: "no stranger to", "not new to", "no shortage of", "without question", "not a day went by without", and "the posting asks for X, and I have never missed an audit leading it". Multiples and fractions are measurements in any form: doubling, twice as fast, in half, by a third, two-thirds, 3-fold, 3 times faster. A scale is read however it's written: `$3m`, `$3 Million`, `$3 MM`, `$3 mil`, `3 bn`. A scale word beside digits in the fact bank, as in "$1.5 million", no longer approves "five million" of anything. A date alone on a resume line is checked like any other claim.
- The assay no longer blocks a unit written with a micro or ohm sign, such as µm, µs or kΩ, as a disguise, or the K of 1.4K as an unknown term. A word your sources use inside a compound is a known term on its own, so "GPU-batched" approves GPU, and a compound of known words, such as Cross-Team, names nothing new.
- `pyrite doctor` and Finish setup name each line under "Unsupported" that no pattern under `[guard] unsupported` matches, since a draft can make that claim and pass. The example's own rules missed "field failures reproduced in simulation" in that order, and now block it.
- Reply detection through the Gmail connector no longer fails about one check in three. Claude Code could start the run before its Gmail connector had connected, leaving Claude with no tools, so it read no mail and wrote its first tool call out as text. The run now has Claude Code wait for its connectors first. A run that still starts without Gmail is caught from what Claude Code says it started with, and tried once more 30 seconds later. If that fails too, the Sources tab says the connector wasn't connected, or that it needs signing in again or isn't set up, instead of "Claude didn't hand back a usable list".
- Workday autofill no longer answers a question that only shares words with a sheet row. A question asked the other way round ("Are you under 18?"), one about someone else ("a relative who worked here"), one about experience with something the row doesn't name ("years with Kubernetes"), and a passport or travel-visa question are left for you.
- Names and places with a full stop, such as "Mary St. John", "J. Robert Smith" and "St. Louis", are typed whole.
- A ``` block left open on `workday-paste.md` no longer swallows the sections after it. It ends at the next heading, and the fill sheet says so at the top. If the roles still don't read back as the paste sheet has them, no sheet is made.
- A company or name with "letter" in it, such as Letterbox Labs, no longer makes the resume the cover letter on the fill sheet.
- Marking a job applied while a document is locked no longer leaves a half-made `sent/` that counts as the record, and `sent/` holds only the resume, the letter and their built documents, not the autofill log or other files.
- A resume.md saved with a byte-order mark builds with its name as the name. A `#### Role` line without a place builds, and one with a fourth part fails with a sentence that says so. A failed build shows the end of what went wrong.
- `* ` and `+ ` bullets build as bullets, and `<!-- notes -->` are left out of the documents.
- `pyrite import-resume` reads text in Word content controls, text boxes, nested tables and the page footer, and names anything it still couldn't reach. It reads Pyrite's own PDFs back as the master they came from, and reads a `.txt` saved as UTF-16 or with a byte-order mark.
- `pyrite status <id> new` or `shortlisted` is refused for a job you've applied to, since it put a sent application back in line for the daily run, which could rewrite its folder. `pyrite status <id> applied` reopens it, as the dashboard's Reopen does, and the run's queue, triage and tailoring skip any job you've sent, whatever its status says.
- `pyrite fill` writes no fill sheet for a job you've applied to, or into a folder with a copy of what was sent, as the dashboard already didn't.
- `--json` prints one JSON document: `pyrite job` puts the fenced posting in an `untrusted_posting` field, `pyrite discover` lists new job ids in `new_ids`, and `pyrite finish` writes the built file names to stderr.
- `pyrite where` piped to a script on Windows writes the path in the console's code page, so Windows PowerShell 5.1 reads a folder name with an accent correctly.
- A relative path in `.pyrite-home` is read from that file's folder, and lines starting with `#` there are notes. A relative `PYRITE_HOME` is read once, from where you started Pyrite, and the dashboard `pyrite open` starts uses the same workspace.
- `pyrite init` says when `.pyrite-home` or `PYRITE_HOME` already names the folder, rather than telling you to put it there, and says so in a line, with nothing left half-made, when it's given a file or a folder it can't write.
- A port outside 1–65535, a `queue --limit` below 1, a damaged or read-only `data/pyrite.db`, and a run number that isn't there each get a line instead of a traceback. `pyrite <command> --help` works before the workspace is made.
- "Applied on" gives the day you applied where you are, not the UTC date.
- Application folder names keep accented letters as plain ones: "Acmé" makes `acme`, not `acm`.
- Text hidden in a Lever, Ashby or Workday posting stays hidden when the posting also shows a tag such as "&lt;script&gt;". Only Greenhouse's escaped descriptions are unescaped now.
- More ways of hiding text in a posting are caught: transparent text, text the color of its own background, near-zero opacity or font size, `scale(0)`, and `<font color="white">`.
- A job you added yourself and closed out no longer takes a new posting with the same title. The new opening comes in as its own job.
- A `[watch.workday]` entry written like the other boards' (`globex = "Globex"`), or the reverse, fails only that company, with how to write it, in a pan, `pyrite sources` and `pyrite doctor`.
- A track limited to `industries` now matches Greenhouse and Workday listings: their descriptions are fetched so the industry can be judged.
- A pattern in search.toml that isn't valid stops a pan with one line naming it and its setting, instead of every board showing as failing. `pyrite doctor` names it too.
- search.toml saved with a byte-order mark, as Windows PowerShell 5.1 writes it, now reads. One that isn't valid TOML, or has a number in quotes such as `min_score = "forty"`, gives one line naming the line or setting, in the commands, `pyrite doctor` and the dashboard.
- Industry codes written without quotes (`naics = [333998]`) no longer break the Industries tab.
- Remote roles in American towns named for foreign places (Dublin, CA; Paris, TX), and in New Mexico, are no longer dropped as foreign. A remote role that names a US place beside a foreign one is kept.
- "Remote" limited to one state is recognized in more spellings: "REMOTE - CA", "Remote (CA)", "Remote, CA", "Remote - California", "CA - Remote".
- `level_top` and `level_mid` patterns with alternatives, such as `principal|staff`, match whole words only, so "Principality" isn't a principal title.
- Deadlines: "until the position is filled" and the posted or start date are no longer read as the deadline, and "11/30/2026", "30th of November 2026" and longer "will close at 11:59 PM … on Monday, November 16, 2026" are found.
- The Settings tab refuses to save when [promote] holds settings it doesn't show, such as `points` on a skill or a `[promote.extra]` table, instead of dropping them.
- Removing an item from a list in the Profile tab removes its comment too.
- `pyrite add` without a link adds the same title in another place as another job, and says when a posting was already tracked.
- A Gmail mail check that couldn't read your mail, or handed back a list that was cut off, no longer counts as a good check that found nothing. It shows as failed on the Sources tab, and the next check reads those days again.
- Moving a job on, for instance marking it applied, while Claude is polishing or refreshing its draft puts back the draft that passed the assay, so a sent folder never keeps text the assay didn't check. The same goes for losing the Claude Code sign-in during a polish.
- A long tailoring job no longer looks stopped while it's still writing, which could let a second Claude run or tailoring batch start beside it. The dashboard now shows each step, such as "writing draft 2" or "checking draft 1". A Refresh resume still building its documents after its time limit no longer looks stopped either.
- Claude is no longer started again with almost no time left. The run stops and says time ran out.
- When a Claude run runs out of time on Windows, everything it started is stopped, not just the `claude.cmd` wrapper.
- An industry outlook whose answer Claude wrote in the wrong shape finishes as failed with a reason, instead of saying "researching" until it went stale.
- Judging a posting now gets Pyrite's own possible-ghost and scam-sign markings, which its instructions already referred to.
- A Claude run whose answer was no use is counted as failed itself, never another job's run that finished just after it.
- Mail scam warnings now judge senders whose domain uses letters from another alphabet, and addresses like o'brien@, instead of dropping them. They recognize free mail in any country (ymail.com, yahoo.co.uk, gmx.at and more) and look-alike domains such as acme-careers.com for "Acme Robotics". A recruiter mentioning a passport, a driver's licence, a date of birth or a travel refund is no longer flagged on that alone.
- An IMAP password with a character IMAP can't send, such as an accented letter, is reported on the Sources tab without repeating it. Any other unexpected error in a pan's mail check is recorded there too.
- A save that would be refused anyway, for text that can't be saved or a form that's out of date, is refused before a code is sent. It no longer uses up a code and a notification. This covers the Profile tab, the Facts tab and Put back.
- Saves on the Facts and Settings tabs now go into History on the Profile tab, so every earlier version can be put back. Before, only one `.previous` copy was kept beside the file, so a second save lost the original.
- Notes, next steps and update notes that are too long are refused with a message rather than cut short without saying so, and the boxes stop typing at the limit. An impossible date such as 30 February is refused.
- Got a reply, Interview, Offer and Rejected can only be logged on an application you've sent.
- A malformed request, such as a huge job number or deeply nested data, gets a clear refusal instead of a server error.
- A posting added by hand can't have a company, title or location over 200 characters. Very long company names and titles show at most three lines in tables and cards.
- On a phone, long folder paths and notes wrap instead of running off the screen.
- `pyrite serve --port` with a port out of range says so instead of showing a traceback.
- The assay no longer counts the digits of your phone number or zip code as measured numbers, so "a team of 10" can't pass on the strength of a phone number with 010 in it.
- The assay no longer takes praise for a denial: "Never failed an X audit", "not a single X finding", "...and I couldn't have done it alone", "...and I never regretted it" are claims of X.
- A name under `forbidden` that's a plain word, such as `Bluebird`, is also blocked split by a space or a hyphen ("blue bird", "Sky-Lift") and as a plural. The example blocks "hives" as well as "hive".
- A name alone on a line under "Do not use", such as "- Bluebird" or "- Osprey Systems (a customer)", is blocked by name. Before, the first word of every line there was taken for a label.
- A role moved under a different employer, and a line written like a role heading in bold or plain text, are checked against your master resume.
- The assay catches links with any ending (alexrivera.pro, alex@rivera.studio), and no longer blocks a domain-shaped name your sources write, such as an employer called Booking.com or a skill called Socket.IO.
- Unfilled placeholders in more forms are caught: `___%`, `{company_name}`, `<Company Name>`, FIXME.
- Multiples in digits (8x), "seven-figure", changes in percentage points and numbers like .83 are checked against the fact bank.
- A letter's date line may be written any common way: 15 November 2026, Nov. 15, 2026, November 15th, 2026 or 2026-11-15.
- A `.txt` paste-box copy of the resume or letter, or a new `.docx` or `.pdf`, changed or added after the assay passed shows as changed since checked.
- Lines starting with `#` in `approved-terms.txt` approve nothing, as the Facts tab already treated them. Before, a term on such a line was approved without a code.
- A draft that isn't saved as UTF-8 gets a clear error from the assay instead of a crash, and a very long sentence no longer takes minutes to check.
- Refresh resume and Interview prep no longer depend on Claude Code honoring an edit rule for one file, which headless runs on one Windows machine refused. Claude gets no tools, hands the document back in its closing message, and Pyrite writes it. An answer with no document in it is asked for again, then fails with the reason on the dashboard instead of looking like a run that changed nothing.
- The pre-push hook works in a `git worktree` that has no `.venv` of its own: it uses the main checkout's venv, then `python3` or `python` if one is 3.11 or newer, and skips the Microsoft Store's placeholder. With none of those it says how to point it at a Python with `git config pyrite.python`, instead of failing on the Store's message.
- `pyrite check` on the folder of a job with a sent copy no longer says to rebuild documents from an older drafter. It says which drafter the sent documents came from, since what was sent is the record and rebuilding would only make the folder differ from it.
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

### Security

- `python -m pyrite.workday` checks the `[workday]` switch, that the job hasn't been sent, and the assay's pass, as `pyrite autofill` does. Autofill no longer presses a button that agrees to, accepts or sends anything, even one that also says "continue".
- `check_public.py` catches more: phone numbers written with a leading +1, with or without dots, or as ten digits after "phone"; lowercase `c:\users` paths; private files in any case, plus database journals and backups and `.env` copies; GitHub fine-grained, OpenAI project, Google, Stripe live and Slack webhook keys, JWTs, and secrets written as settings; fastmail, comcast and pm.me addresses; annotated tags' messages and taggers; names split across a document's runs or written as entities, and every file inside a zip-based document; and UTF-16 text in image metadata. It reports a submodule instead of crashing, and allows only `.docx`, `.pdf` and `.png` under `example/applications/` and `docs/screenshots/`.
- Pyrite refuses a workspace inside its own repository, where applications and the database could be committed to a public repository, and a folder that isn't a workspace, which used to get an empty database. `pyrite init` says how to make one.
- PRIVACY.md now lists the Industries tab's downloads from the Bureau of Labor Statistics and its outlook research run, which sends the industry, your area and the employers you follow to Claude with web search.
- The Gmail mail check denies every Gmail tool that sends, drafts, labels, trashes or marks mail, so even a workspace `.claude/settings.json` can't allow one. It is told only the companies you've applied to and those under `[inbox.domains]`, fenced as data, not every company a job board listed.
- Drafting runs can never edit or write `profile/`, `data/`, `.claude/` or `CLAUDE.md`, whatever the workspace's settings allow. If anything in `profile/` changes while a draft is written, the draft is put back and the run stops.
- Runs that can read files can't read a Workday fill sheet, autofill log, `workday-paste.md` or `public-denylist.txt` anywhere in the workspace, or the workspace's `.claude/` settings.
- An industry outlook keeps a source only if its whole address is a page Claude opened or one its searches listed, not a site's home page, a shortened address, or a link mentioned inside some other page.
- `allowed_hosts` under `[dashboard]` must be a list of names, matched exactly and ignoring case. A single string, which used to match any piece of a host name, now allows nothing, and `pyrite doctor` says so. A request with no Host header is refused.
- An unexpected server error no longer sends its details to the page. They go to the window the dashboard runs in.

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
