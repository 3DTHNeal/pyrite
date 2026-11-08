#!/usr/bin/env python3
"""Pyrite command line. Run `python3 tools/pyrite.py --help`."""
import os
import sys
from pathlib import Path

# Kept to syntax any Python 3 can read, so an old one gets this message instead of a traceback.
if sys.version_info < (3, 11):
    sys.exit("Pyrite needs Python 3.11 or newer, and this is {}.{}. On Windows, `py -3.11 tools/pyrite.py ...` "
             "picks a newer one if it's installed; see docs/operating.md to make a venv.".format(*sys.version_info[:2]))

# Before anything loads: the demo must read the example workspace, whatever else is configured.
if sys.argv[1:2] == ["demo"]:
    os.environ["PYRITE_HOME"] = str(Path(__file__).resolve().parents[1] / "example")

from pyrite.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
