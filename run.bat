@echo off
rem Runs Cratez straight from the source folder (no exe needed).
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist ".venv\Scripts\python.exe" (
    echo First run - setting up...
    %PY% -m venv .venv || (pause & exit /b 1)
    ".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt || (pause & exit /b 1)
)
start "" ".venv\Scripts\pythonw.exe" app.py
