@echo off
rem Double-click to open Pyrite. Starts the dashboard if it's down, and replaces it if it has hung.
rem The workspace comes from PYRITE_HOME or .pyrite-home. See docs/operating.md.
cd /d "%~dp0"
set "URL=http://127.0.0.1:8787/"

rem A fresh clone has no venv yet, and starting without one would only show a "Windows cannot find" box.
if not exist ".venv\Scripts\pythonw.exe" goto novenv
rem With no workspace, serve refuses to start, and waiting for it below would take half a minute to say so.
if not defined PYRITE_HOME if not exist ".pyrite-home" goto noworkspace

rem Anything can answer on a port, so check that what answers is Pyrite's own page.
curl.exe -s --max-time 3 %URL% 2>nul | findstr /c:"<title>Pyrite</title>" >nul && goto open

rem Whatever holds the port isn't answering as Pyrite. A hung dashboard is replaced.
rem Any other program is left alone, since closing it could lose someone's work.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127\.0\.0\.1:8787 .*LISTENING"') do (
    powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=%%p'; if ($p.CommandLine -like '*pyrite.py*serve*') { Stop-Process -Id %%p -Force; exit 0 } else { exit 1 }" || goto busy
)

rem pythonw runs with no window, so the dashboard keeps going after this closes.
start "" ".venv\Scripts\pythonw.exe" tools\pyrite.py serve

for /l %%i in (1,1,15) do (
    curl.exe -s --max-time 2 %URL% 2>nul | findstr /c:"<title>Pyrite</title>" >nul && goto open
    ping -n 2 127.0.0.1 >nul
)

echo Pyrite didn't start. Running it here so you can see why:
echo.
".venv\Scripts\python.exe" tools\pyrite.py serve
pause
exit /b 1

:busy
echo Port 8787 is in use by another program, so Pyrite wasn't started and nothing was closed.
echo Close that program, or run Pyrite on another port:
echo     .venv\Scripts\python.exe tools\pyrite.py serve --port 8790
pause
exit /b 1

:novenv
echo Pyrite isn't set up in this folder yet: there's no .venv here. From this folder, run:
echo     py -3 -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r tools\requirements.txt
echo     .venv\Scripts\python.exe tools\pyrite.py init ..\my-job-search --name "Your Name"
echo Then run .venv\Scripts\python.exe tools\pyrite.py doctor, which lists what's left. See docs\operating.md.
pause
exit /b 1

:noworkspace
echo Pyrite has no workspace yet, so there's nothing of yours to show. From this folder, run:
echo     .venv\Scripts\python.exe tools\pyrite.py init ..\my-job-search --name "Your Name"
echo Or look around the fictional example with:
echo     .venv\Scripts\python.exe tools\pyrite.py demo
pause
exit /b 1

:open
start "" %URL%
