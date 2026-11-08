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
    # Making the workspace, or asking how, mustn't need the workspace to be there already. The name matches
    # store.MAY_BE_MISSING, which can't be imported before this is set.
    if not sys.argv[1:] or sys.argv[1] in ("init", "help", "-h", "--help", "--version"):
        os.environ["PYRITE_WORKSPACE_MAY_BE_MISSING"] = "1"
    from pyrite.cli import main

    # Read once, when the workspace was found. Nothing this process starts should inherit it.
    os.environ.pop("PYRITE_WORKSPACE_MAY_BE_MISSING", None)
    main()


if __name__ == "__main__":
    run()
