@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo  Cratez - building dist\Cratez.exe
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo Creating a private Python environment...
    %PY% -m venv .venv || goto :err
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip >nul 2>nul
echo Installing yt-dlp and PyInstaller...
python -m pip install --upgrade -r requirements.txt || goto :err

echo Building...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Cratez --icon icon.ico --add-data "ui;ui" app.py || goto :err

echo.
echo ============================================
echo  Done:  %~dp0dist\Cratez.exe
echo ============================================
echo.
echo  Optional: install ffmpeg for tagged files and the best stream quality:
echo      winget install Gyan.FFmpeg
echo  If Windows SmartScreen warns on first run: "More info" then "Run anyway".
echo.
pause
exit /b 0

:err
echo.
echo Build failed - read the messages above. Python 3.10 or newer is required.
pause
exit /b 1
