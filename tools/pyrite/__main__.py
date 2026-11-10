"""Entry point for `python -m pyrite` (run from tools/) and the `pyrite` command that `pip install -e .` adds."""
import importlib.util
import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]
ASSAY = CODE_ROOT / "tools" / "assay"


def assay_problem() -> str:
    """Why the fact checker's general half, the assay package in tools/assay, wouldn't load from this clone, or "".

    A plain `pip install -e .` puts all of tools/ on the path, so it finds the package whenever the clone has it. An
    editable install made in strict mode links only the packages there were when it was made, so one from before the
    package existed can't find it. And PyPI has an unrelated package called assay, which would load in its place."""
    try:
        spec = importlib.util.find_spec("assay")
    except (ImportError, ValueError):
        spec = None
    origin = Path(spec.origin).resolve() if spec and spec.origin else None
    if origin and origin.parent == ASSAY.resolve():
        return ""
    script = f"`python tools/pyrite.py` from {CODE_ROOT}, which looks in the clone first and needs no install"
    if origin:
        return (f"Python found a different package named assay, at {origin.parent}, in place of Pyrite's fact checker in "
                f"{ASSAY}. Uninstall that one or give Pyrite a virtual environment of its own, or run {script}.")
    return (f"Pyrite can't find its fact checker, the assay package in {ASSAY}. An editable install made in strict mode "
            f"links only the packages there were when it was made, and this one was made before the assay had a package "
            f"of its own. Run `pip install -e .` again from {CODE_ROOT}, or run {script}.")


def run() -> None:
    # Pyrite reads its example workspace, prompts and build script from the clone, so a copy in site-packages can't work.
    if not (CODE_ROOT / "example").is_dir():
        sys.exit("Pyrite runs from a clone of its repository. Install it with `pip install -e .` from the clone, not `pip install .`.")
    # The fact checker's general half is a package beside this one. Say why it won't load, rather than a traceback.
    problem = assay_problem()
    if problem:
        sys.exit(problem)
    # Before anything loads: the demo must read the example workspace, whatever else is configured.
    if sys.argv[1:2] == ["demo"]:
        os.environ["PYRITE_HOME"] = str(CODE_ROOT / "example")
    # Making the workspace, or asking how, mustn't need the workspace to be there already. The name matches
    # store.MAY_BE_MISSING, which can't be imported before this is set. Help on one command, `pyrite queue --help`, is
    # asking how too.
    if not sys.argv[1:] or sys.argv[1] in ("init", "help", "--version") or {"-h", "--help"} & set(sys.argv[1:]):
        os.environ["PYRITE_WORKSPACE_MAY_BE_MISSING"] = "1"
    from pyrite.cli import main

    # Read once, when the workspace was found. Nothing this process starts should inherit it.
    os.environ.pop("PYRITE_WORKSPACE_MAY_BE_MISSING", None)
    main()


if __name__ == "__main__":
    run()
