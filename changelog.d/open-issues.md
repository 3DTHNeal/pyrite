### Changed

- Interview prep and **Refresh resume** start through one shared helper, the Profile editors and **Gaps to answer** check a form's text with one shared check, and `pyrite skills --research` and the daily run find the skills to look up with one shared query. Nothing they do or say changed.
- A test that runs over five minutes now prints every thread's stack and stops the run as failed, instead of hanging until CI cancels the job. `PYRITE_TEST_LIMIT` sets other seconds, or 0 for none. Waits on `pdfinfo`, `icacls`, and git and Pyrite in the tests now have time limits too.

### Fixed

- A pass now records a hash of the very bytes the assay checked. It used to hash the files again after checking them, so a draft or fact bank saved in between was recorded as passed without being checked. Now it shows as changed since the check.
