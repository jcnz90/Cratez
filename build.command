#!/bin/bash
# Cratez - builds dist/Cratez.app and dist/Cratez-<version>.dmg on macOS. Double-click this file (or run it in Terminal).
cd "$(dirname "$0")"
echo "============================================"
echo " Cratez - building dist/Cratez.app"
echo "============================================"
if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install it from https://www.python.org/downloads/ (or: brew install python) and run this again."
  read -n 1 -s -r -p "Press any key to close"; exit 1
fi
set -e
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
echo "Installing yt-dlp and PyInstaller..."
python -m pip install --upgrade -r requirements.txt
echo "Building..."
VER="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app.py)"
python -m PyInstaller --noconfirm --clean --windowed --name Cratez --icon icon.icns --add-data "ui:ui" \
  --osx-bundle-identifier app.cratez.Cratez app.py
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VER" dist/Cratez.app/Contents/Info.plist 2>/dev/null || true
# the app is unsigned: clear the quarantine flag so Gatekeeper lets it open with a right-click > Open
xattr -dr com.apple.quarantine dist/Cratez.app 2>/dev/null || true
echo "Building the disk image..."
bash installer/mac/make-dmg.sh "$VER"
echo
echo "============================================"
echo " Done:  $(pwd)/dist/Cratez.app"
echo " Installer:  $(pwd)/dist/Cratez-$VER.dmg   (open it, drag Cratez into Applications)"
echo "============================================"
echo " First launch: right-click the app > Open (it's unsigned)."
echo " Optional: brew install ffmpeg   - tags, cover art and MP3 conversion"
echo
[ -n "$CI" ] || read -n 1 -s -r -p "Press any key to close"
