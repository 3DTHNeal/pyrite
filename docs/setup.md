# Setting up

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

## The guided way

On Windows, with Python 3.11 or newer installed, double-click `Pyrite.cmd`. Nothing else needs a terminal or a text editor.

1. The first time, it makes the venv in this folder and installs what Pyrite needs, which takes a minute or two and needs the internet once. Without a new enough Python, it says where to get one and changes nothing.
2. The dashboard opens on **Make your workspace**, over the demo. Give your name as it goes on your resume and the folder to make, and choose blank files or a copy of the example. [From the dashboard](#from-the-dashboard) has the details.
3. Pyrite restarts on your new workspace at the Profile tab, which opens on **Setting up**: how many of the required sections are set, and a button to the next one. The rail's **Profile** shows the same count, such as 2/7.
4. Setup goes through the Profile tab's own sections in order, in four groups: About you, Your search, Automation and Workspace. Each says why it matters, and **Where this goes** names the files it writes and how to make the same change by hand. The rail beside the section marks the optional ones and shows how far you've got.
5. At the bottom, **Save and continue** saves the section and opens the next, and **Continue** moves on when there's nothing to save. An optional section that isn't set yet offers **Skip for now**. A required one can be left too, and setup comes back to it. **←** goes back a section.

You can stop at any point and come back. What's done is read from your files each time, not kept as a record of its own, so a change made in a text editor counts too. A section showing **needs you** isn't done yet, and **Needs you** on the Profile tab says why.

The required sections are what a first draft needs: **Name and contact**, **Work history**, **Achievements** and **Master resume** about you, and **Roles you want** and **Companies to watch** in your search, with **Where you'll work** set from the start to take remote roles. The Master resume section runs the fact check on your master as you write it, so a master that passes there passes for every draft. Once every required section is set, the Profile tab says **Setup done**, with **Check the boards now** for the first board check. From then on, a change that lets drafts say more, such as approving a term, asks for a code sent to this computer's notifications ([Confirming with a code](profile.md#confirming-with-a-code)).

On macOS or Linux, make the venv as below and run `.venv/bin/python tools/pyrite.py open`, which opens the same setup. The rest of this page is the same setup by hand, for people who'd rather edit the files.

## The venv

`Pyrite.cmd` makes this the first time it's run. To make it yourself, use Python 3.11 or newer. On Windows, `py -3` picks the newest one installed, which matters where `python` is an older one:

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

### From the dashboard

With no workspace set yet, open the dashboard: double-click `Pyrite.cmd` on Windows, or run `pyrite open`. It opens on **Make your workspace**, over the demo. Give your name as it goes on your resume and the folder to make, which starts as `my-job-search` beside this one, and choose to start from blank files or from a copy of the example. It can make the folder a private git repository too, as `--git` does below. **Make my workspace** does what `init` does, points this folder at the new workspace, and restarts the dashboard on it, at the Profile tab, where [the guided way](#the-guided-way) goes on. **Look around the demo first** closes the box for now: **Make your workspace** at the top of the page opens it again.

It only works while nothing names a workspace, so the dashboard can never make a second one or move Pyrite off the one in use. A new workspace needs no confirmation codes until its required Profile sections are set, since there's nothing in it of yours yet to loosen. See [Confirming with a code](profile.md#confirming-with-a-code).

### From a terminal

`init` makes one from the example's profile and points this folder at it. Put your own name in the quotes. `init` needs one, a name with a space needs the quotes, and `init` refuses a placeholder such as "Your Name":

```bash
.venv/Scripts/python.exe tools/pyrite.py init ../my-job-search --name "Your Name"
```

It puts your name in `search.toml` and on the `# Name` lines of the master resume and letter, leaves out the example's `seed.toml` and clears its `allowed_hosts`, and changes nothing if the folder already has a `profile/`.

With `--blank`, the profile files start with none of the fictional candidate's content: `facts.md` and `run-notes.md` have their headings and a comment under each on what goes there, the master resume has your name and its section headings and the letter your name, and `search.toml` keeps the example's comments and the settings for how Pyrite works, with every setting that describes the candidate emptied. The optional `workday-paste.md` isn't written. `doctor` then names what's still blank, and that `search.toml` has no roles or companies yet. Comments (`<!-- ... -->`) in a source approve nothing, so leaving them in is harmless.

With `--git`, `init` also makes the workspace a git repository of its own, with a `.gitignore` for what shouldn't be kept: SQLite's `-wal` and `-shm` files, the `*.previous.*` copies a save keeps, the browser profile autofill signs in with, the BLS downloads and Word's `~$` lock files. It never adds a remote or pushes. `data/pyrite.db` is kept in the repository on purpose: it's the one file that can't be regenerated, so the repository is its backup. Commit when nothing is running, with no pan, Claude run or dashboard save under way, so the copy is whole. The built `.docx`, `.pdf` and `.txt` files are kept too, since Pyrite checks them against what passed and what was sent, and a rebuild never comes out byte for byte the same. To keep a copy off this computer, push it to a private repository you make yourself. For a workspace you already have, run `init` on the workspace in use with `--git`: it sets up the repository and changes nothing else.

Then replace everything else in `profile/`:

- `facts.md`, `approved-terms.txt` and `run-notes.md` with your own.
- `resume.md` and `cover-letter.md` with your master resume and letter, written in the form under [How the documents are written](documents.md#how-the-documents-are-written). The `[guard]` section of `search.toml` names them as the sources every draft is checked against, and `resume.md` as the one whose employers, titles and dates a draft must match.
- In `search.toml`, `[candidate]` with your name, `[location]`, the tracks, industries and companies to watch, and under `[guard]` your own confidential and unsupported terms and `expected_on_resume`. The assay blocks each capitalized name listed under "Do not use" in `facts.md` without a pattern of its own, so `forbidden` is for what a name alone won't catch, such as a lowercase term. It reads the "Unsupported" section only through `unsupported`, so each line there needs a pattern. `allowed_hosts` under `[dashboard]` lists names the dashboard would answer to, so add only ones you use.
- `workday-paste.md` with your own Workday answers, or delete it if you won't use `pyrite fill`.
- `seed.toml`, if you want it, with the applications you made before Pyrite. `pyrite seed` imports them: one with `applied_on` as applied, and one without under Being tailored, where `pyrite finish` checks it.

To do it by hand instead, copy `example/profile/` into a folder outside this repository and point the code at it. Either set `PYRITE_HOME`, or put the path on one line in a file called `.pyrite-home` in this folder, which git ignores. A Git Bash path such as `/c/Users/you/my-job-search` works too. A relative path in `.pyrite-home` is read from this folder, so `../my-job-search` is the folder beside it, and lines starting with `#` there are notes. A relative `PYRITE_HOME` is read from the folder you start Pyrite in. The folder must be outside this repository and hold `profile/search.toml` or `data/pyrite.db`, or Pyrite stops and says why rather than starting an empty database there. Check it with:

```bash
.venv/Scripts/python.exe tools/pyrite.py where
```

Then ask what's left:

```bash
.venv/Scripts/python.exe tools/pyrite.py doctor
```

It lists every profile file that's still the example's, the example's settings left in `search.toml`, each source under `[guard]` that isn't in your workspace, a master resume or letter that isn't in the form the assay reads, a "Do not use" name the assay can't block by name because your sources also state it as fact, and whether it found the programs Pyrite uses: python-docx, LibreOffice or Word, `pdftotext`, Claude Code and its sign-in, and a mail login. The dashboard lists the same workspace items as **Finish setup** at the top of the to-do list, and the Claude run and the tailoring batch refuse to start while `facts.md` is still the example's, so no usage goes on writing for the fictional candidate.

With neither set, the code uses the fictional `example/` workspace, so it can't touch your data by accident. Commands that write, such as `discover`, `folder` and `finish`, then refuse to run, so nothing real ends up inside this repository. `serve` and `open` start the dashboard on **Make your workspace** instead, over the demo, which saves nothing. `pyrite demo` is the way to look around without a workspace.

Where you'll work and which roles you want can be written in plain words, with no regular expressions: `places = ["Springfield, IL", "Oak Park"]` under `[location]`, and `titles = ["data engineer", "platform engineer"]` under each `[[track]]`. Each is matched as whole words in any case, with any spacing, commas, hyphens, periods or parentheses between them, so `Springfield, IL` matches "springfield il" but not "Springfield, MO", and `St. Louis` matches "St Louis". A place that ends in a US state matches the state written either way and on either side, so `Springfield, IL` also matches "Springfield, Illinois" and "US-IL-Springfield". And `data engineer` matches "Senior Data Engineer" but not "Data Engineering Manager". They work beside the `local` and `title` patterns, so add a pattern only for what plain words can't say, such as a whole state. A blank workspace starts with `places` and shows `titles` in its example track.

If you're not in the US, two settings in `search.toml` matter early: `remote_home` and `remote_elsewhere` under `[location]`, which replace the built-in idea of which remote roles are open to you, and `paper = "a4"` under `[documents]`.

## Protecting a public fork

Turn on the pre-push check once per clone, and keep your denylist in your workspace, since a public list of secrets would be a leak of its own:

```bash
git config core.hooksPath .githooks
```

```bash
git config pyrite.denylist /path/to/my-job-search/profile/public-denylist.txt
```

The check reads file contents, file and branch names, commit messages, annotated tags and the text inside `.docx` and `.pdf` files, with a document's words joined up as a reader sees them. The only binary files it allows are `.docx`, `.pdf` and `.png` under `example/applications/`, `docs/screenshots/`, `docs/images/` and `tools/pyrite/static/icons/`, and a submodule is refused, since its files are in another repository it doesn't read. Reading a PDF's pages needs poppler's `pdftotext`, which Git for Windows includes, or `pypdf`. Without either, a PDF blocks the push, since nothing would vouch for what's on its pages.
