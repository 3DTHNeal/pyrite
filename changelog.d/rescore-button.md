### Added

- **Rescore now** under **Your prospects** in Roles you want and Where you'll work, once a save would move any prospect. It backs up `data/pyrite.db` first, then scores the prospects again as `pyrite rescore` does and says what it kept and dropped. It's refused while a run is going.

### Changed

- A pan now rescores your prospects before reading the boards whenever the filters in `search.toml` have changed since they were scored, not only after an update that changes scoring.
