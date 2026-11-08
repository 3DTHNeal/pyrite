# Changelog

What changed in each release that you'd notice when running Pyrite. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/): until 1.0, a minor version may change the workspace's files or `search.toml` and says so here.

## [Unreleased]

### Added

- `pyrite init <folder>` makes a workspace from the example's profile, without its fictional applications or allowed hosts, and points `.pyrite-home` at it.
- `pyrite doctor` and the dashboard's Finish setup list also name the example's settings left in `search.toml`: its local places, confidential and unsupported terms, ordinary words, the degree every resume is expected to name, preferred cities and mail domains.
- `pyrite --help` lists where to start, and each job id argument says what it is.

### Changed

- `pyrite seed` refuses a `seed.toml` that's still the example's. An application it imports with no `applied_on` goes under Being tailored, where `pyrite finish` checks it, instead of Ready to send, so ready still means the assay passed it.
- `pyrite add` says which job it added and what to run next, and a posting file it can't read stops it with a message instead of a traceback.
- `pyrite finish` says it's building before Word's slow first export, and `finish` and `check` say in words when a resume uses so many of the posting's skill terms that it reads as copied.
- `pyrite where` says when it has fallen back to the example.
- The demo's Check boards now and Run Claude now buttons are disabled, since the demo starts no runs.

### Fixed

- On Windows, a second dashboard on a port already in use no longer starts beside the first, with requests going to either one. It stops and says the port is taken.

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
