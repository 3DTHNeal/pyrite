#!/usr/bin/env python3
"""War room command line. Run `python3 tools/wr.py --help`."""
import os
import sys
from pathlib import Path

# Before anything loads: the demo must read the example workspace, whatever else is configured.
if sys.argv[1:2] == ["demo"]:
    os.environ["WARROOM_HOME"] = str(Path(__file__).resolve().parents[1] / "example")

from warroom.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
