@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo  Cratez - building dist\Cratez.exe and its installer
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

echo Fetching ffmpeg to ship inside Cratez...
python installer\get_ffmpeg.py || echo ffmpeg download failed - building without it (tags and cover art need it)

echo Building...
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Cratez --icon icon.ico --add-data "ui;ui" app.py || goto :err

for /f "tokens=3" %%v in ('findstr /b /c:"VERSION = " app.py') do set "VER=%%~v"
set "ISCC="
for /f "delims=" %%i in ('where iscc 2^>nul') do set "ISCC=%%i"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
    echo Building the installer...
    "%ISCC%" /Q /DAppVersion=%VER% installer\windows\cratez.iss || goto :err
    set "SETUP=%~dp0dist\Cratez-Setup-%VER%.exe"
) else (
    echo Inno Setup not found, so no installer this time - install it with:  winget install JRSoftware.InnoSetup
)

echo.
echo ============================================
echo  Done:  %~dp0dist\Cratez.exe
if defined SETUP echo  Installer:  %SETUP%
echo ============================================
echo.
echo  If Windows SmartScreen warns on first run: "More info" then "Run anyway".
echo.
pause
exit /b 0

:err
echo.
echo Build failed - read the messages above. Python 3.10 or newer is required.
pause
exit /b 1
