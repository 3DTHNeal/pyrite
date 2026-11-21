### Changed

- **Add a posting** asks before adding a company and title you already track at another link, or with none, since it may be the same job listed twice. **Open it** goes to the job you have, and **Add it anyway** adds this one as another opening, with a line in its timeline naming the other. `pyrite add` says the same and takes `--anyway`.
- Settings › Claude checks a model's name when you save it, unless it's one of Claude Code's aliases, and refuses one Claude Code doesn't know. The check is one turn with no tools, counted with the rest of the Claude usage.
- `pyrite check` takes a job's number, and finds a folder named as the dashboard names it, `applications/…`, from wherever it's run.

### Fixed

- `pyrite queue` and the morning briefing no longer name a board as failing after it's taken off the watchlist.
- A run that fails on its model says to change it under Settings › Claude, not Claude Code's "Run --model".
- `pyrite check` on a folder that isn't there, or a job with no folder, says so and exits 2, rather than reporting a draft blocked for a missing `resume.md`.
- `pyrite import-resume` reads a role written on one line with commas, such as "Employer, Title, Milwaukee, WI, Aug 2012 - Jun 2017", title first or employer first, with or without a comma before the state. It no longer loses such a line while saying it kept it, or takes the town for the employer, and it says when an employer's place has no role to go on.
- The folded **Finish setup** line on To do counts its items, rather than running their sentences together.
