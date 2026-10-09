#!/bin/bash
# Das Spiel gegen die Entwicklungsinstanz starten (macOS/Linux).
#
#   ./Release/skripte/dev_spielen.sh            installierte App, sonst main.py
#   ./Release/skripte/dev_spielen.sh <Programm> dieses Programm
#
# Solange die Variablen gesetzt sind, zeigt das Online-Menue NUR den
# Dev-Server (Kennzeichen T, siehe Documentation/DEV_SERVER.md).
export RACE_SERVER_HOST=62.238.50.156
export RACE_SERVER_TAG=T
export RACE_SERVER_PORT=7878
export RACE_SERVER_UDP_PORT=7877

if [ -n "$1" ]; then
  exec "$1"
fi
APP="/Applications/3D-Racing-Game.app/Contents/MacOS/3D-Racing-Game"
if [ -x "$APP" ]; then
  exec "$APP"
fi
cd "$(dirname "$0")/../.."
exec python3 main.py
