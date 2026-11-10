### Changed

- The assay's general checks are now a package of their own, `tools/assay`, that knows nothing about resumes, so another tool can build a fact checker from the same parts. What a draft passes or fails is unchanged. If you installed Pyrite with `pip install -e .`, run it again so the `pyrite` command finds the new package. Running `python tools/pyrite.py` needs nothing.
