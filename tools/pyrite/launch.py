"""`pyrite open`: the dashboard in the browser, started if it's down and replaced if it has hung.

Pyrite.cmd is a wrapper around this on Windows, and it works the same everywhere else. Anything can answer on a port,
so only a page that's Pyrite's own counts as the dashboard, and only a process that's Pyrite's own `serve` is ever
stopped: closing any other program could lose someone's work.
"""
import os
import re
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .store import CODE_ROOT, NEEDS_SETUP, ROOT

# The dashboard runs under pythonw, with no console of its own, so a console program it starts would open a window
# of its own unless told not to.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULT_PORT = 8787
TITLE = b"<title>Pyrite</title>"
# A first start reads the whole database, so it gets a while. Pyrite.cmd waited about as long.
WAIT_SECONDS = 30
STOP_SECONDS = 5
# A dashboard's command line: tools/pyrite.py serve, the installed pyrite command's serve, or python -m pyrite serve.
# The demo, `pyrite.py demo`, isn't one, and neither is another program that happens to have "pyrite" in its path.
SERVE = re.compile(r"(?:^|[\\/\s\"'])pyrite(?:\.py|\.exe)?[\"']?\s+serve\b|-m\s+pyrite\s+serve\b", re.I)


def dashboard_port(cfg: dict[str, Any]) -> int:
    """The port under [dashboard] in search.toml, so `serve`, `open` and Pyrite.cmd agree on one. 8787 if unset."""
    port = cfg.get("dashboard", {}).get("port", DEFAULT_PORT)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SystemExit(f"port under [dashboard] in profile/search.toml is {port!r}. Make it a whole number from 1 to 65535, "
                         "such as 8790, or remove it to use 8787.")
    return port


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def answering(port: int, timeout: float = 3) -> bool:
    """Whether Pyrite's own page answers on the port. A proxy set for the web is never asked."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url(port), timeout=timeout) as resp:
            return TITLE in resp.read(65536)
    except (OSError, ValueError):
        return False


def _output(command: list[str]) -> str:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def netstat_listener(text: str, port: int) -> int | None:
    """The process listening on the port, from Windows' `netstat -ano`. A listening socket is the one with no remote
    end. Its state is named in the system's language, so it isn't read."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[1] in (f"127.0.0.1:{port}", f"0.0.0.0:{port}") and parts[2] == "0.0.0.0:0" \
                and parts[4].isdigit():
            return int(parts[4])
    return None


def listener(port: int) -> int | None:
    """The process listening on the port on this machine, or None if there's none or it can't be told."""
    if sys.platform == "win32":
        return netstat_listener(_output(["netstat", "-ano", "-p", "TCP"]), port)
    found = re.match(r"\s*(\d+)", _output(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"]))
    found = found or re.search(r"pid=(\d+)", _output(["ss", "-ltnpH", f"sport = :{port}"]))
    return int(found[1]) if found else None


def command_line(pid: int) -> str:
    """How a process was started, or "" if that can't be read."""
    if sys.platform == "win32":
        return _output(["powershell", "-NoProfile", "-Command",
                        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"]).strip()
    proc = Path(f"/proc/{int(pid)}/cmdline")
    try:
        return proc.read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return _output(["ps", "-o", "command=", "-p", str(int(pid))]).strip()


def is_dashboard(pid: int) -> bool:
    return bool(SERVE.search(command_line(pid)))


def _stop(pid: int, port: int) -> None:
    try:
        # On Windows this ends the process outright, as Pyrite.cmd's Stop-Process did.
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    deadline = time.monotonic() + STOP_SECONDS
    while listener(port) == pid and time.monotonic() < deadline:
        time.sleep(0.25)


def start(port: int, home: Path | None = None) -> subprocess.Popen[bytes]:
    """Start `serve` in the background, with no window, so it keeps going after this ends. `home` is a workspace just
    made, which this process didn't start on."""
    python = Path(sys.executable)
    args = [str(python), str(CODE_ROOT / "tools" / "pyrite.py"), "serve", "--port", str(port)]
    null = subprocess.DEVNULL
    # The workspace this found, by its whole path. The dashboard starts in the code folder, where a relative path from
    # PYRITE_HOME or a .pyrite-home edited since would name some other folder, and it must open this one. With none
    # set yet it's left unnamed, since naming the example would open the demo rather than setup.
    env = {**os.environ, "PYRITE_HOME": str(home or ROOT)}
    if home is None and NEEDS_SETUP:
        env.pop("PYRITE_HOME")
    if sys.platform == "win32":
        # pythonw has no console of its own, and a detached process doesn't share this one, so closing it stops nothing.
        windowless = python.with_name("pythonw.exe")
        if windowless.exists():
            args[0] = str(windowless)
        return subprocess.Popen(args, stdin=null, stdout=null, stderr=null, cwd=CODE_ROOT, env=env,
                                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(args, stdin=null, stdout=null, stderr=null, cwd=CODE_ROOT, env=env, start_new_session=True)


def restart(port: int, home: Path | None = None) -> bool:
    """Start a new dashboard on the port this one just let go of, on `home` if that's a workspace just made. Whether
    one answers in time.

    A port can stay taken for a moment after its server closes, and then the new one stops at once, so it's tried again."""
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        child = start(port, home)
        while child.poll() is None and time.monotonic() < deadline:
            if answering(port, timeout=2):
                return True
            time.sleep(0.5)
        time.sleep(1)
    return answering(port)


def open_dashboard(port: int, browse: Callable[[str], object] = webbrowser.open) -> None:
    """Open the dashboard on this port in the browser, starting it if nothing answers there. A dashboard that holds the
    port but has stopped answering is replaced. Any other program on the port is left alone."""
    address = url(port)
    if not answering(port):
        pid = listener(port)
        if pid is not None:
            if not is_dashboard(pid):
                raise SystemExit(f"Port {port} is in use by another program, so Pyrite wasn't started and nothing was closed.\n"
                                 "Close that program, or give Pyrite another port: set port under [dashboard] in "
                                 f"profile/search.toml, such as port = {port + 3 if port + 3 <= 65535 else 8790}.")
            print(f"The dashboard on port {port} stopped answering, so it's being replaced.", flush=True)
            _stop(pid, port)
        print(f"Starting the dashboard at {address}", flush=True)
        child = start(port)
        deadline = time.monotonic() + WAIT_SECONDS
        while not answering(port, timeout=2):
            if child.poll() is not None:
                # It stopped, so whatever it said went nowhere. Running it here shows it, as Pyrite.cmd did.
                print("Pyrite didn't start. Running it here so you can see why:\n", flush=True)
                from .server import serve

                serve(port)
                return
            if time.monotonic() > deadline:
                raise SystemExit(f"The dashboard started but hasn't answered at {address} after {WAIT_SECONDS} seconds. "
                                 "Try again in a minute, or run `pyrite serve` to see what it says.")
            time.sleep(1)
    browse(address)
    print(f"Pyrite is open at {address}. It keeps running after this window closes.")
