#!/bin/bash
# Cratez - wraps dist/Cratez.app in a branded disk image: dist/Cratez-<version>.dmg
# Opens as a dark Cratez window with the app on the left, Applications on the right and an arrow between.
# Called by build.command and the release workflow:  installer/mac/make-dmg.sh 1.1.0
set -e
cd "$(dirname "$0")/../.."
VER="${1:-dev}"
APP="dist/Cratez.app"
DMG="dist/Cratez-$VER.dmg"
VOL="Cratez $VER"
ART="installer/mac"
[ -d "$APP" ] || { echo "$APP not found - build the app first."; exit 1; }

STAGE="$(mktemp -d)"
trap 'hdiutil detach "/Volumes/$VOL" -quiet 2>/dev/null || true; rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
mkdir "$STAGE/.background"
# one TIFF holding the 1x and 2x art, so the window is sharp on Retina screens
tiffutil -cathidpicheck "$ART/dmg-background.png" "$ART/dmg-background@2x.png" -out "$STAGE/.background/background.tiff" >/dev/null
cp icon.icns "$STAGE/.VolumeIcon.icns"

rm -f "$DMG" dist/cratez-rw.dmg
hdiutil create -quiet -srcfolder "$STAGE" -volname "$VOL" -fs HFS+ -format UDRW -size 400m dist/cratez-rw.dmg
hdiutil attach -quiet -readwrite -noverify -noautoopen dist/cratez-rw.dmg
command -v SetFile >/dev/null && SetFile -a C "/Volumes/$VOL" || true

# lay out the window; Finder scripting can be unavailable (e.g. no GUI session), the image still works without it
osascript <<EOF || echo "Finder layout skipped - the disk image works, just without the custom window."
tell application "Finder"
  tell disk "$VOL"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set the bounds of container window to {200, 120, 860, 520}
    set opts to the icon view options of container window
    set arrangement of opts to not arranged
    set icon size of opts to 112
    set text size of opts to 13
    set background picture of opts to file ".background:background.tiff"
    set position of item "Cratez.app" of container window to {180, 190}
    set position of item "Applications" of container window to {480, 190}
    close
    open
    update without registering applications
    delay 2
    close
  end tell
end tell
EOF

sync
# Finder/Spotlight can keep the volume busy for a moment after styling it (hdiutil exit 16)
for i in 1 2 3 4 5; do
    hdiutil detach -quiet "/Volumes/$VOL" && break
    sleep 3
    [ "$i" = 5 ] && hdiutil detach -force "/Volumes/$VOL"
done
hdiutil convert -quiet dist/cratez-rw.dmg -format UDZO -imagekey zlib-level=9 -o "$DMG"
rm -f dist/cratez-rw.dmg
echo "Disk image: $(pwd)/$DMG"
