# Writing the documents

[All of the guide](README.md)

Commands use the Windows path `.venv/Scripts/python.exe`. Elsewhere, it's `.venv/bin/python`.

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

### Starting from the resume you have

`pyrite import-resume <file>` reads a `.docx`, a PDF or a `.txt` resume and prints it in this form, for you to correct. It reads the structure the way a parser would, with no AI: the name and contact line at the top, the section headings, each employer and its roles with their dates, and the bullets. Where a line could be read two ways, such as two names with no job-title word in either, it picks one and says which under "Check:", and a line it couldn't place is kept as it was, never dropped. Dates come out as `Jan 2020 – Present` whatever form they were in, and a role with no place of its own takes its employer's.

```bash
.venv/Scripts/python.exe tools/pyrite.py import-resume "My Resume.docx"
```

Add `--save` to write it to `profile/resume.md` instead. The copy it replaces goes in the Profile tab's History, where **Put back** restores it. Where `facts.md` has no contact line or no employers yet, `--save` also fills its Contact line and Timeline from the resume, so they aren't typed twice: **Name and contact** and **Work history** on the Profile tab then open with them. Anything already there is left alone, and a role with no dates leaves the Timeline for you, with a line saying which role. Then check the headings and bullets against the original, and put each claim in `facts.md`: the assay blocks a draft that says anything your sources don't. A PDF needs poppler's `pdftotext`, which Git for Windows includes. A scanned PDF has no text to read, and an old `.doc` needs saving as `.docx` first. From a `.docx` it reads text in tables, content controls, text boxes and the page header and footer too; lines from a text box go at the end, and any text it still couldn't reach is named under "Check:". A `.txt` saved by Notepad as Unicode (UTF-16) is read as such.

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

The builder and its writing rules together are the drafter, and they carry a version number (`DRAFTER_VERSION` in `tools/pyrite/checks.py`). Every file built is stamped with it, in the Word document's Version and Keywords properties and the PDF's Keywords, so you can tell which rules a document was written under. `pyrite check` reports the version behind each `.docx` in a folder and warns when it isn't the current one; the dashboard shows the same under the assay result. A folder with a `sent/` copy only says which drafter the sent documents came from, since what was sent is the record and rebuilding it would make the folder differ from what the company has. The playbook's "Drafter versions" table says what changed in each.
