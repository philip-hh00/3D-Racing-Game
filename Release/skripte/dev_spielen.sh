#!/bin/bash
# Das Spiel gegen die Entwicklungsinstanz starten (macOS/Linux).
#
#   ./Release/skripte/dev_spielen.sh            dieser Quellordner, sonst installierte App
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

# Liegt das Skript in einem Quellordner, gilt dieser Stand - nicht eine
# installierte App, die eine andere Version haben kann (der Dev-Server
# verlangt genau seine Version).
WURZEL="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$WURZEL/main.py" ]; then
  cd "$WURZEL"
  if [ -x ".venv/bin/python" ]; then
    echo "Starte $WURZEL aus dem Quelltext gegen den Dev-Server ..."
    exec .venv/bin/python main.py
  fi
  echo "Starte $WURZEL mit python3 gegen den Dev-Server ..."
  exec python3 main.py
fi

APP="/Applications/3D-Racing-Game.app/Contents/MacOS/3D-Racing-Game"
if [ -x "$APP" ]; then
  exec "$APP"
fi
echo "[FEHLER] Weder Quellordner noch installierte App gefunden."
exit 1
