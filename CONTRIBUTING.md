# Contributing

Pyrite is a personal project. I run it on my own job search and share it so others can read it and run their own copy. A fork is the expected way to change it for yourself.

- **Never post real data.** No resumes, fact banks, mail, postings you applied to or `pyrite.db`, in an issue, a pull request or a screenshot. Show the problem on the example workspace instead: `python tools/pyrite.py demo`.
- **Bugs** are welcome with steps that reproduce them on the example workspace.
- **Ideas** are welcome too, but I may not get to them.
- **Pull requests:** open an issue first for anything bigger than a small fix, so neither of us spends time on a change I won't take. Before opening one, run the tests and the privacy check:

  ```bash
  python -W ignore::ResourceWarning -m unittest discover -s tools/tests
  python tools/check_public.py
  ```

- **Security problems** go through [SECURITY.md](SECURITY.md), not an issue.

Contributions are licensed under the [MIT License](LICENSE), as section 10 of the [EULA](EULA.md) says.
