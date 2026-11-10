### Added

- **Make your workspace.** With no workspace set yet, `Pyrite.cmd` and `pyrite open` start the dashboard on making one, over the demo, instead of stopping with an error. It asks for your name and the folder, starts from blank files or the example, can make it a private git repository, and restarts the dashboard on it at the Profile tab.

### Changed

- A new workspace, made by setup or `pyrite init`, needs no confirmation codes until every required Profile section is set, since there's nothing of yours in it yet to loosen. Codes then start for good. Workspaces made before this need codes as they always did.
