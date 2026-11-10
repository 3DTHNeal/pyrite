# Your profile and facts

[All of the guide](README.md)

## Your profile

The **Profile** tab brings together everything Pyrite knows about you and your search. Two of its sections, What comes first and Schedule and mail, are set on the Settings tab, and open it there.

- **Setting up** shows while a new workspace is being set up: how many required sections are set, and a button to the next. Each section then has **Save and continue**, **Skip for now** for an optional one, and a way back, and the rail beside it shows the progress. [The guided way](setup.md#the-guided-way) covers it. It ends for good once every required section is set, with **Setup done** shown once.
- **Needs you** lists what setup still needs, the same findings as `pyrite doctor`, each with a button to the section that fixes it.
- Each section shows what it holds now and when the Profile tab last changed it. **Where this goes** names the files and settings it writes, and how to make the same change by hand.
- **History** lists every save made on the Profile, Facts and Settings tabs, newest first. Pick a file to see what putting back its earlier copy would change, then **Put back**. A save that changed several files, such as your name in `search.toml` and the master resume, offers **Put back this whole save** too, so the files don't end up disagreeing. Putting back is a save like any other: the files as they are now are kept too, and a copy that would let drafts say more asks for a code. The latest 50 copies of each file are kept in `data/history/`.
- A section with edits you haven't saved shows how many, with **Discard** and **Save changes**. Leaving it asks first. If a file changed on disk after the tab loaded it, the save is refused and nothing is written.
- The address names the section, as `#profile/achievements`, so a bookmark or reload comes back to it.
- In a section with an editor, every change is worked out by the code a save uses, before you save. **What changes in your files** shows each file's lines as they'd change, **Before you save** says anything worth knowing first, and a change that needs a code says so and why.

The sections under **About you** that have editors so far:

- **Name and contact** sets your name, each part of the contact line and the paper size. A change goes everywhere the name or contact line appears: `[candidate]` and `[documents]` in `search.toml`, Contact in `facts.md`, and the `# Name` and `@` lines of `profile/resume.md` and `profile/cover-letter.md`. If the assay reads the contact line from a file outside `profile/`, the section names it, since you change that one yourself.
- **Work history** edits employers, roles, titles, places and dates, and lines such as Education. Each change is made to its own line of the Timeline in `facts.md`, so notes after the dates and the way you wrote things stay. The same change is made to the matching `###` and `####` headings in `profile/resume.md`, and an employer's dates follow its roles when they matched them before. A role is refused if `facts.md` wouldn't read it back as typed, such as a title with a comma that isn't in your master resume. **On every resume** sets `expected_on_resume`.
- **Achievements** edits the themed sections of `facts.md` a fact at a time, keeping any lines under a fact with it, and adds sections before "Do not use". The **achievement builder** turns what you did, the before and after, and where it was measured into one fact line, and points out filler words, a percentage with no setting, and "Led" or "Managed" on a role whose title doesn't support it. Where it was measured is saved under **Wording** in `run-notes.md`, so drafts keep it. A fact that names something on Off limits is pointed out before you save.
- **Master resume** edits `profile/resume.md` and `profile/cover-letter.md`: the headline, the text under each heading, and the letter's body. The name, contact line and headings come from the sections above and can't be typed here. Each change runs the fact check on both, and lists what only the master says, such as a number not in `facts.md`. Drafts may use those, because the master is an approved source, so it's worth checking each is true. If `heading_source` names another file, the section says so.
- **Off limits** lists what drafts must never mention and what you haven't done. **Block it** adds a line to "Do not use" or "Unsupported" in `facts.md` and a pattern to `forbidden` or `unsupported` under `[guard]`, written to catch plurals, hyphens and spacing. A capitalized name under "Do not use" is blocked by name even with no pattern, and the section lists those. A name that your sources also state as fact can't be blocked that way, so it's named with a button to add a pattern. **Test a sentence** shows how the assay reads any sentence, including when a denial makes a claim acceptable. **Advanced** shows and edits the patterns themselves. Taking anything off asks for a code.
- **Skills and terms** shows `approved-terms.txt` a term at a time, under the comments that group them. Taking a term off saves straight away; approving one asks for a code.

Under **Your search**:

- **Where you'll work** sets which locations count. **Places** are plain names, such as "Springfield, IL" or a whole state, each matched as whole words in any case, and a place ending in a state also matches the state written out or first. They go under `places` in `[location]`. Patterns written by hand under `local` and `local_exact` stay as they are, and **Advanced** shows them and adds or removes one at a time; `remote_home` and `remote_elsewhere` are shown there too, and changed only in the file. Two switches set whether remote roles count and whether you'll relocate for an onsite role elsewhere. **Test a location** judges anything a board might write, such as "Remote - US", with the filters' own code and your settings as drafted, and says why. **Your prospects** counts the postings still new under Prospects, found on the boards, as local, remote, kept or dropped, now and after the change, and lists the ones that would move. They keep their place until `pyrite rescore`. **Area for the Industries tab** sets `state`, `metro` and `country` under `[market]`, and names a state or metro area the BLS doesn't, once Pyrite has its list of them. The model that researches outlooks is on the Settings tab, under Claude.

Lists in `search.toml` are changed an item at a time, so the other items, their lines and any comments among them stay as they were.

**Companies to watch**, under **Your search**, edits the job boards Pyrite reads every morning, `[watch.greenhouse]`, `[watch.lever]`, `[watch.ashby]` and `[watch.workday]` in `search.toml`, with the companies you check by hand and what Workday sites are searched for.

- **Add a company** takes a careers page address and works out the board from it: `boards.greenhouse.io/<board>` (or `job-boards.greenhouse.io`), `jobs.lever.co/<board>`, `jobs.ashbyhq.com/<board>`, or `<tenant>.<wdN>.myworkdayjobs.com/<site>`. The address of one job on the board works too. Check the company's name it guesses, then **Add to the watchlist**. A company's own careers page often sends its Apply links to one of these boards, so open a job there and paste where Apply goes. An address on any other site is offered for **Check by hand** instead.
- **Watched boards** lists each board with its company's name and key, a Workday site as its tenant, server (`wd1`, `wd5` and so on) and site, and how many postings it listed at the last run, or why it failed. Each is its own line in `search.toml`, changed or taken off on its own, so the comments around it stay. Taking a board off stops it being read from the next run; jobs already found there stay where they are.
- **Test** reads one board once, as `pyrite sources` does, and says whether it answers and how many postings it lists. It saves nothing. It only ever reads that board's own feed on Greenhouse, Lever, Ashby or Workday, built from the key, never an address sent from the page.
- **Check by hand** is `[[manual_check]]`: companies and sites with no board Pyrite can read, which the Sources tab lists as a reminder. Each entry is changed where it is, a key at a time, so comments between entries stay. A new one goes after the last, and one taken off goes with its own lines and the comments just above it. Taking off the last one leaves a commented-out example where the list was, and the next one added takes its place.
- **Workday searches** are `queries` under `[workday]`. A Workday site has no full list to read, so Pyrite searches each one for these, and what they find still goes through your filters.
**Roles you want**, under **Your search**, edits the kinds of role Pyrite keeps: each `[[track]]` in `search.toml`, and the `[scoring]` lists that go with them.

- A role type has a name, **Job titles** written plainly under `titles`, and **Needs a senior title** (`needs_level`). A plain title matches as whole words in any case, so "data engineer" takes "Senior Data Engineer, Platform" but not "Data Engineering Manager". Patterns written by hand under `title` are shown and kept, and can be taken off; **Add a pattern** adds one. `industries` is shown, and set in the file.
- A title goes to the first role type that takes it, so the arrows change the order. **What drafts lead with** is the role type's line under **Emphasis by track** in `run-notes.md`, which follows a rename and goes when the role type does.
- **Senior titles** edits `level_top` and `level_mid`, and **Never these titles** edits `exclude_titles`. **Advanced** edits the skill points in `keywords` and the `flags`, written a row to a line once one changes.
- Each role type is changed a key at a time, so comments and keys the section doesn't edit stay as they were.
- **Try a title** says which role type would take a job title, or why none does.
- **Your prospects with these changes** scores every prospect that a board found and you haven't moved on, with the scorer `pyrite rescore` uses, and lists the ones that would be dropped and the scores that would change. One you've acted on is marked as kept, since a rescore leaves it. Saving changes `search.toml` only: `pyrite rescore` then scores your prospects again, and `pyrite discover --fresh` looks again at postings dropped before.
- **Before you save** points out a new title that **Never these titles** would drop, or that an earlier role type takes first. A role type with no name or no titles, two with the same name, taking off every role type, and a pattern that can't be read or would match any title are refused.

Three sections show what they find and save nothing:

- **Tools check** lists what Pyrite uses on this computer, the same programs `pyrite doctor` checks: python-docx and LibreOffice or Word, which every draft needs, `pdftotext`, Claude Code and reply detection. Each says what it's for, what still works without it, and how to get it. Claude Code and reply detection are set up on the Settings tab, so theirs have a button there. **Check again** asks Claude Code again rather than using its answer from the last minute. A missing program every draft needs goes on **Needs you**.
- **Workspace and backup** names the folder in use and whether `PYRITE_HOME` or `.pyrite-home` chose it. `data/pyrite.db` is the one file there that can't be made again, so **Back up now** copies it into `data/backups/`, whole even while a run is writing to it, and keeps the newest 10. The section also says whether the folder is a git repository that keeps the database, when it was last committed, and how to put a copy back. A copy on the same computer is lost with it, so copy `data/backups/` somewhere else from time to time. The section shows as set while the newest copy is under two weeks old.
- **What comes first** and **Schedule and mail** are set on the Settings tab, under **Cities and industries** and **Daily run**, and their cards open it there.

## Gaps to answer

You may have done something you never thought to put in `facts.md`, and then every draft for a job that asks for it says you haven't. Each tailored draft's `notes.md` lists its gaps, numbered, under **Gaps to prepare for**. **Gaps to answer** on the Profile tab reads those lists in every application's folder, groups the ones that name the same requirement, and asks about the ones that keep coming up, most often raised first. No AI is involved: gaps are grouped by their words, so each question shows what every application's notes said and you can see a group is one question before you answer it.

- **Yes, I've done this** asks for the fact in your own words and the section of `facts.md` it goes in, made if it isn't there. Write what you did, where, and a number if there is one, since a vague yes can't become a bullet. It's added as the Achievements section adds a fact, and a fact that names something on Off limits is pointed out first.
- **No, I haven't** adds a line under "Unsupported" in `facts.md`, in the gap's words or yours, so drafts stop guessing and say so plainly. That only tightens the check, so it needs no code. To have the assay block it as a claim too, add it on Off limits.
- **Doesn't apply** is for a gap that's a decision rather than a fact, such as travel, or one your facts already cover. It stops asking and changes no file. **Not now** leaves it.
- A gap raised by one application is listed only when you ask. One that's already under "Unsupported", or that every application's notes call settled, isn't asked. One whose words match a line in your facts says so, since drafts written before that line was added didn't have it.
- Answers go through the usual save, with the diff first and History after, and a save that takes anything off "Do not use" or "Unsupported" still asks for a code. Which questions you've answered is kept in `data/gap-answers.json`, and only an answer whose line the save really added counts. **Answered** lists them, with **Ask again**, which leaves `facts.md` as it is.
- Each draft you haven't sent whose notes list a gap you answer gets a **Rework** item on the to-do list, since it was written without your answer: use **Refresh resume** or **Tailor this one first**, or **Got it** to keep it as it is. The item goes once its resume is rewritten after the answer. Sent applications are records and aren't flagged. Once a gap comes up in three applications or more, the to-do list has a **Gaps to answer** item that opens this section.

`pyrite gaps` lists the same questions in a terminal and `pyrite gaps answer` answers one, as [Common commands](commands.md) shows.

## Your facts

The **Facts** tab shows `profile/facts.md` and `profile/approved-terms.txt`, the two files that say what a resume may claim. The fact bank is shown a section at a time. Click **Edit** on a section, change it and **Save**, or use **Add a section**. Sections named "Do not use" and "Unsupported" are marked **Approves nothing**, because the assay never treats them as a source.

- A save takes effect the next time a draft is checked. Drafts that already passed aren't checked again by themselves.
- The file from before each save is kept in the Profile tab's History, where **Put back** restores it.
- In `approved-terms.txt`, a line starting with `#` is a comment. It approves nothing, so adding one needs no code.
- If the file changed on disk after the tab loaded it, the save is refused and nothing is written.
- To block a term by name, it also has to be listed under `[guard]` in `search.toml`. That can't be done from the dashboard.

The dashboard has no login, so anyone who can open it can change these two files. It only listens on this machine unless you add names under `allowed_hosts`, written as a list such as `['workstation']`. Anything else there is ignored, and `pyrite doctor` says so. The demo's facts can't be changed.

### Confirming with a code

A save that would let drafts say more than before asks for a code first. On the Facts tab that's adding a line to `approved-terms.txt`, or taking an item off "Do not use" or "Unsupported". Saves that only add a block, or change facts, go straight through.

1. Save as usual. Instead of saving, the tab shows a box saying what the change would let drafts do, with a space for **Code from the notification**.
2. A notification titled **Pyrite code: 123 456** appears in the corner of the screen. It says to type the code into the dashboard and names what it confirms. On Windows it's labelled Windows PowerShell, the app Pyrite uses to show it, and it stays up until you close it. If it's gone, Windows key + N shows it again.
3. Type the code into the box on the dashboard and choose **Confirm**. The change is saved.

The notification can't accept or refuse anything itself: its **Close** button only closes it. Nothing is saved until the code is confirmed on the dashboard, and **Cancel** there puts the form back.

- A code works once, for the change it names, for 2 minutes. Five wrong tries end it and nothing is saved. **Send a new code** replaces it.
- No notification, or Focus Assist hid it? `pyrite code` in a terminal on this computer prints the code waiting and what it's for.
- A new workspace, made by the dashboard's setup or `pyrite init`, needs no codes while it's being set up, since nothing in it is yours yet to loosen. **Needs you** says so. Once every required section on the Profile tab is set, codes start, for good: emptying a section afterwards doesn't stop them. A workspace made before this needs codes as it always did. `data/setting-up.json` marks a workspace that's still being set up.
- The server decides what needs a code, by comparing the files before and after, so the page can't skip it. It's not a password: anyone who can see this screen can read the code. It stops a change made from another device, or by something driving the browser, without the person at this computer seeing it named.
- Notifications come from each system's built-in route, with nothing to install: Windows PowerShell's toast, AppleScript on macOS, and `notify-send` on Linux.
