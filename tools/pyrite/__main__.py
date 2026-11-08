"""Entry point for `python -m pyrite` (run from tools/) and the `pyrite` command that `pip install -e .` adds."""
import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]


def run() -> None:
    # Pyrite reads its example workspace, prompts and build script from the clone, so a copy in site-packages can't work.
    if not (CODE_ROOT / "example").is_dir():
        sys.exit("Pyrite runs from a clone of its repository. Install it with `pip install -e .` from the clone, not `pip install .`.")
    # Before anything loads: the demo must read the example workspace, whatever else is configured.
    if sys.argv[1:2] == ["demo"]:
        os.environ["PYRITE_HOME"] = str(CODE_ROOT / "example")
    from pyrite.cli import main

    main()


if __name__ == "__main__":
    run()
