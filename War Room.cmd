@echo off
rem Double-click to open the war room. Starts the dashboard if it's down, and replaces it if it has hung.
rem The workspace comes from WARROOM_HOME or .warroom-home. See docs/operating.md.
cd /d "%~dp0"
set "URL=http://127.0.0.1:8787/"

curl.exe -s -o nul --max-time 3 %URL% && goto open

rem Something holding the port without answering is a hung dashboard.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127\.0\.0\.1:8787 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1

rem pythonw runs with no window, so the dashboard keeps going after this closes.
start "" ".venv\Scripts\pythonw.exe" tools\wr.py serve

for /l %%i in (1,1,15) do (
    curl.exe -s -o nul --max-time 2 %URL% && goto open
    ping -n 2 127.0.0.1 >nul
)

echo The war room didn't start. Running it here so you can see why:
echo.
".venv\Scripts\python.exe" tools\wr.py serve
pause
exit /b 1

:open
start "" %URL%
