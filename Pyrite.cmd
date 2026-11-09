@echo off
rem Double-click to open Pyrite. It runs `pyrite open`, which starts the dashboard if it's down, replaces it if it has
rem hung, and opens it in your browser. The dashboard runs with no window, so it keeps going after this one closes.
rem The workspace comes from PYRITE_HOME or .pyrite-home, and the port from port under [dashboard] in search.toml
rem (8787 if unset). See docs/dashboard.md.
cd /d "%~dp0"

rem A fresh clone has no venv yet, so this says how to make one rather than failing to find Python.
if not exist ".venv\Scripts\python.exe" goto novenv

".venv\Scripts\python.exe" tools\pyrite.py open
rem Anything it had to say, such as that there's no workspace yet or another program holds the port, stays on screen.
if errorlevel 1 (
    pause
    exit /b 1
)
exit /b 0

:novenv
echo Pyrite isn't set up in this folder yet: there's no .venv here. From this folder, run:
echo     py -3 -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r tools\requirements.txt
echo     .venv\Scripts\python.exe tools\pyrite.py init ..\my-job-search --name "Your Name"
echo Then run .venv\Scripts\python.exe tools\pyrite.py doctor, which lists what's left. See docs\setup.md.
pause
exit /b 1
