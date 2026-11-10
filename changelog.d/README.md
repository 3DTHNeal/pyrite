# Changelog notes

A pull request that changes something you'd notice when running Pyrite says so in a file of its own here, not in [CHANGELOG.md](../CHANGELOG.md). Two pull requests then never edit the same lines, so merging one never leaves the other with a conflict to resolve.

Name the file after your branch, such as `changelog.d/short-reasons.md`, and write it as CHANGELOG.md's Unreleased section would read: one or more of the headings Added, Changed, Deprecated, Removed, Fixed and Security, each over its entries.

```markdown
### Fixed

- **Reach out** no longer lists the same company twice.
```

CI's lint job checks every note with `python tools/changelog.py --check`. Before a release, `python tools/changelog.py` puts each note's entries at the top of its heading under Unreleased and deletes the note's file.
