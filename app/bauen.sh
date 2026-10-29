#!/bin/bash
# Baut aus app/Kanban.swift das Mac-Programm Kanban.app.
#
#   ./bauen.sh            → legt Kanban.app im Projektordner an
#   ./bauen.sh --einbauen → kopiert sie zusätzlich nach /Applications
#
set -euo pipefail
cd "$(dirname "$0")"
ORDNER="$(cd .. && pwd)"   # hier liegen server.py, index.html und kanban.db
APP="$ORDNER/Kanban.app"
INHALT="$APP/Contents"

echo "→ Alte Fassung wegräumen"
rm -rf "$APP"
mkdir -p "$INHALT/MacOS" "$INHALT/Resources"

echo "→ Swift übersetzen"
swiftc -parse-as-library -O -o "$INHALT/MacOS/Kanban" Kanban.swift

echo "→ Info.plist schreiben"
cat > "$INHALT/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>Kanban</string>
  <key>CFBundleDisplayName</key>       <string>Kanban</string>
  <key>CFBundleIdentifier</key>        <string>de.bobmarley.kanban</string>
  <key>CFBundleExecutable</key>        <string>Kanban</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key>           <string>1</string>
  <key>LSMinimumSystemVersion</key>    <string>14.0</string>
  <key>NSHighResolutionCapable</key>   <true/>
  <key>NSPrincipalClass</key>          <string>NSApplication</string>
  <key>KanbanOrdner</key>              <string>$ORDNER</string>
  <!-- Das Board kommt von http://localhost – ohne diese Freigabe blockt macOS das -->
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
  <key>NSDocumentsFolderUsageDescription</key>
  <string>Kanban speichert das Board in kanban.db im Projektordner unter „Dokumente“.</string>
</dict>
</plist>
PLIST

echo "→ Signieren (lokal, ohne Entwicklerkonto)"
codesign --force --sign - "$APP"
codesign --verify --verbose=1 "$APP"

if [[ "${1:-}" == "--einbauen" ]]; then
  echo "→ Nach /Applications kopieren"
  rm -rf "/Applications/Kanban.app"
  cp -R "$APP" /Applications/
  echo "   fertig: /Applications/Kanban.app"
else
  echo "   fertig: $APP"
fi
