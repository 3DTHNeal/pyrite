# Contributing

Pyrite is a personal project. I run it on my own job search and share it so others can read it and run their own copy. A fork is the expected way to change it for yourself.

- **Never post real data.** No resumes, fact banks, mail, postings you applied to or `pyrite.db`, in an issue, a pull request or a screenshot. Show the problem on the example workspace instead: `python tools/pyrite.py demo`.
- **Bugs** are welcome with steps that reproduce them on the example workspace.
- **Ideas** are welcome too, but I may not get to them.
- **Questions** go to [Discussions](https://github.com/3DTHNeal/pyrite/discussions), so issues stay for bugs.
- **Pull requests:** open an issue first for anything bigger than a small fix, so neither of us spends time on a change I won't take. Before opening one, run what CI runs: the tests, lint, type check and the privacy check. A fix to the assay comes with a test of the draft it now catches.

  ```bash
  python -m pip install -r tools/requirements-dev.txt
  python -m unittest discover -s tools/tests
  python -m ruff check tools
  python -m mypy
  python tools/check_public.py
  ```

  The tests are split by area (`test_assay.py`, `test_discovery.py`, `test_dashboard.py` and so on), and `tools/tests/support.py` sets up the throwaway workspace they share. Note what changed under "Unreleased" in [CHANGELOG.md](CHANGELOG.md).

- **Security problems** go through [SECURITY.md](SECURITY.md), not an issue.

Contributions are licensed under the [MIT License](LICENSE), as section 10 of the [EULA](EULA.md) says.
