### Changed

- **Needs you** on the Profile tab says it's the same health check as `pyrite doctor`. A pattern that isn't valid now has a button to the section that edits it: Where you'll work, Roles you want, or Settings › Cities and industries. A finding for a section set on the Settings tab says so on its button and opens it there.

### Fixed

- The Profile tab opens when `profile/search.toml` can't be read, with the problem and its line first under **Needs you**, instead of failing to load. A setting of the wrong kind, such as a number written as text, is listed there too.
- A `search.toml` with a list or quote left open names the end of the file and what to look for, instead of saying "Fix that line" with no line.
