@echo off
rem Double-click to open Pyrite. It runs `pyrite open`, which starts the dashboard if it's down, replaces it if it has
rem hung, and opens it in your browser. The dashboard runs with no window, so it keeps going after this one closes.
rem The workspace comes from PYRITE_HOME or .pyrite-home, and the port from port under [dashboard] in search.toml
rem (8787 if unset). With no workspace yet, the dashboard opens on making one. See docs/dashboard.md.
cd /d "%~dp0"

rem A fresh clone has no venv yet, so the first double-click makes one, with nothing to type.
if not exist ".venv\Scripts\python.exe" goto makevenv

:open
".venv\Scripts\python.exe" tools\pyrite.py open
rem Anything it had to say, such as that the workspace named can't be found or another program holds the port, stays on screen.
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0

:makevenv
echo Setting Pyrite up in this folder for the first time. This takes a minute or two, and only happens once.
rem `py -3` picks the newest Python installed, which matters where `python` is an older one.
where py >nul 2>nul
if errorlevel 1 (
    python -m venv .venv
) else (
    py -3 -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 11))"
if errorlevel 1 goto oldpython
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r tools\requirements.txt
if errorlevel 1 goto noinstall
echo Done. Opening Pyrite, which starts on making your workspace.
goto open

:nopython
echo Pyrite needs Python 3.11 or newer, and this computer has none Pyrite could find.
echo Install it from https://www.python.org/downloads/, then double-click Pyrite.cmd again. See docs\setup.md.
pause
exit /b 1

:oldpython
rem Taken away again, so the next double-click tries afresh once a newer Python is installed.
rmdir /s /q .venv
echo Pyrite needs Python 3.11 or newer, and the newest this computer has is older.
echo Install a newer one from https://www.python.org/downloads/, then double-click Pyrite.cmd again. See docs\setup.md.
pause
exit /b 1

:noinstall
rmdir /s /q .venv
echo Pyrite couldn't install what it needs, as pip says above. It needs the internet for this, once.
echo Double-click Pyrite.cmd again to try again, or follow docs\setup.md to do it by hand.
pause
exit /b 1
