### Added

- `pyrite doctor`, **Needs you** on the Profile tab and **Finish setup** on the to-do list say when no posting can reach `min_score` or `tailor_min_score` with your settings as they are, and when a title and place that match fall under `min_score` because nothing adds points for skills. Each says what the parts of a score are worth and where to change them.
- They also say when the master resume has its headings and nothing under them, or the master letter has nothing after its contact line.

### Changed

- A blank workspace, from **Blank files** in setup or `init --blank`, starts with `min_score` and `tailor_min_score` at 25. It has no points for skills yet, so with the example's 40 and 55 a remote posting with exactly the title asked for was dropped, and no draft was ever written unless you picked the job. A workspace made before this keeps its limits, and is told when they're out of reach.
- A blank workspace's **Never these titles** starts with interns, co-ops and apprentices only. It used to keep the example's whole list, which leaves out designers, analysts, writers, nurses, recruiters and more.
- A blank workspace no longer starts with the example's pay under `[relocation]`, so **Moving for it** asks for yours.

### Fixed

- **Master resume** no longer counts as set, and setup as done, while the resume is only the headings Work history wrote, or the letter has no body. With `cover_letters = false`, the letter isn't needed.
- The Profile tab's **Schedule and mail** card says when the pan and the daily run start and whether reply detection is set up, and shows as set once both runs are scheduled. It used to say "set" whatever the case.
