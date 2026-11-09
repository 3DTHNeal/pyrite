#!/usr/bin/env python3
"""Pyrite command line. Run `python3 tools/pyrite.py --help`."""
import sys

# Kept to syntax any Python 3 can read, so an old one gets this message instead of a traceback.
if sys.version_info < (3, 11):  # noqa: UP036
    sys.exit("Pyrite needs Python 3.11 or newer, and this is {}.{}. On Windows, `py -3 tools/pyrite.py ...` runs the newest "
             "one installed, and elsewhere `python3` may be newer. docs/setup.md shows how to make a venv with it.".format(*sys.version_info[:2]))

from pyrite.__main__ import run

if __name__ == "__main__":
    run()
