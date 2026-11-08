# Changelog

What changed in each release that you'd notice when running Pyrite. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/): until 1.0, a minor version may change the workspace's files or `search.toml` and says so here.

## [Unreleased]

### Added

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

### Changed

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

### Fixed

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
