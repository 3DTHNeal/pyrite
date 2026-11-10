### Added

- **Guided setup.** While a new workspace is set up, the Profile tab opens on **Setting up**: how many required sections are set, with a button to the next. Each section's footer has **Save and continue**, **Skip for now** for an optional one, and a way back, the rail beside it shows the progress and which sections are optional, and the app rail's **Profile** shows the count. Progress is read from your files each time, so you can leave and come back. Once every required section is set, the tab says **Setup done**, with **Check the boards now**.
- **Where this goes** in each Profile section also says how to make the same change by hand.

### Changed

- On Windows, the first double-click of `Pyrite.cmd` in a fresh clone makes the venv and installs what Pyrite needs, instead of saying what to type in a terminal. Without Python 3.11 or newer, it says where to get it.
- A Profile section fills the view below the top bar, with its rail of sections kept in sight and drawn like the app's own rail.
- `docs/setup.md` and the README lead with the guided way, and keep the steps by hand after it. CONTRIBUTING.md describes the fresh-clone test.

### Fixed

- **Master resume** no longer reads as set while `resume.md` is still the blank form a new workspace starts with.
- **Roles you want** no longer opens on "Keep at least one role type" in a new workspace that has none yet.
