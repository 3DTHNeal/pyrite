# Contributing

Pyrite is a personal project. I run it on my own job search and share it so others can read it and run their own copy. A fork is the expected way to change it for yourself.

- **Never post real data.** No resumes, fact banks, mail, postings you applied to or `pyrite.db`, in an issue, a pull request or a screenshot. Show the problem on the example workspace instead: `python tools/pyrite.py demo`.
- **Bugs** are welcome with steps that reproduce them on the example workspace.
- **Ideas** are welcome too, but I may not get to them.
- **Questions** go to [Discussions](https://github.com/3DTHNeal/pyrite/discussions), so issues stay for bugs.
- **Pull requests:** open an issue first for anything bigger than a small fix, so neither of us spends time on a change I won't take. Before opening one, run what CI runs: the tests, lint, type check and the privacy check. A fix to the assay comes with a test of the draft it now catches. A change to how postings are scored or filtered (`evaluate` in `tools/pyrite/score.py`, or `rejection` in `quality.py`) raises `VERSION` in `score.py` by one, so the next pan rescores the prospects people already have instead of leaving them with old scores and reasons.

  Use the venv from the README's setup, with Python 3.11 or newer. These are the Windows paths, and elsewhere it's `.venv/bin/python`:

  ```bash
  .venv/Scripts/python.exe -m pip install -r tools/requirements.txt -r tools/requirements-dev.txt
  .venv/Scripts/python.exe -m unittest discover -s tools/tests
  .venv/Scripts/python.exe -m ruff check tools
  .venv/Scripts/python.exe -m mypy
  .venv/Scripts/python.exe tools/check_public.py
  ```

  Without `tools/requirements.txt` the tests that build documents skip. To have lint, the type check and the privacy check run before every push, turn on the hook once per clone. It blocks a push that CI's lint job would fail, and leaves the tests to you, since they take minutes:

  ```bash
  git config core.hooksPath .githooks
  ```

  The hook uses this checkout's venv, or the main checkout's from a `git worktree`. To use another Python, set `git config pyrite.python /path/to/python`.

  On the dashboard, use the colour variables at the top of `tools/pyrite/static/style.css` rather than new colours. Each has a light and a dark value, every text colour clears 4.5:1 on every surface, and a colour means the same thing everywhere (see the table under "The dashboard" in [docs/operating.md](docs/operating.md)). Icons are drawn by `art/icons/build.py`, never edited by hand: change the script and run it again. Show a change to the page in both themes and at phone width.

  The tests are split by area (`test_assay.py`, `test_discovery.py`, `test_dashboard.py` and so on), and `tools/tests/support.py` sets up the throwaway workspace they share. Note what changed under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).

- **Security problems** go through [SECURITY.md](SECURITY.md), not an issue.
- **Conduct:** the [code of conduct](CODE_OF_CONDUCT.md) covers how we treat each other here, and how to report someone who doesn't.

Contributions are licensed under the [MIT License](LICENSE), as section 10 of the [EULA](EULA.md) says.
