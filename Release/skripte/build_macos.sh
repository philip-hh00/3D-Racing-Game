#!/bin/bash
# macOS release build for 2D-Racing-Game.
# Produces a .app bundle, a .dmg and a portable .zip in ./Release/ausgabe/.
# Run on macOS with Python 3.11 available (python3.11 or python3).
#
#   chmod +x Release/skripte/build_macos.sh
#   ./Release/skripte/build_macos.sh

set -e
# Liegt in Release/skripte/, gearbeitet wird im Wurzelverzeichnis: die
# Spezifikationen und die Datenpfade sind relativ dazu.
cd "$(dirname "$0")/../.."

# --- ensure a Python 3.11+ interpreter (auto-install if missing) ------------
find_py() {
  for c in python3.11 python3.12 python3; do
    if command -v "$c" >/dev/null 2>&1; then
      "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)' 2>/dev/null && { command -v "$c"; return 0; }
    fi
  done
  return 1
}

PY="$(find_py || true)"
if [ -z "$PY" ]; then
  echo "Python 3.11+ not found — installing via Homebrew..."
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew not found — installing Homebrew (may ask for your password)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # add brew to PATH for this shell (Apple Silicon + Intel locations)
    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [ -x /usr/local/bin/brew ] && eval "$(/usr/local/bin/brew shellenv)"
  fi
  brew install python@3.11
  PY="$(find_py || true)"
fi
if [ -z "$PY" ]; then
  echo "[ERROR] Could not obtain Python 3.11+. Install it manually: brew install python@3.11"
  exit 1
fi
echo "Using Python: $PY ($($PY --version))"

# --- virtualenv with build deps ---------------------------------------------
# Es wird bewusst NICHT "source .venv-build/bin/activate" benutzt und auch nicht
# blosses "python": stattdessen direkt "$VENV/bin/python".
#
# Warum (Fehlerbericht 04.08.2026: "line 47: .venv-build/bin/activate: No such
# file or directory"): geprueft wurde nur, ob das VERZEICHNIS existiert. Bricht
# die Erzeugung einmal ab — abgebrochener Lauf, fehlgeschlagenes ensurepip,
# geloeschtes Python nach einem brew-Update —, dann steht das Verzeichnis da,
# aber ohne activate. Beim naechsten Lauf uebersprang die Pruefung die Erzeugung
# und das source scheiterte. Der Interpreterpfad ist der ehrlichere Test, und
# ohne activate haengt der Build nicht an der Shell.
VENV=".venv-build"
VPY="$VENV/bin/python"
if [ ! -x "$VPY" ]; then
  # Halbe Umgebung wegraeumen, statt darin weiterzubauen.
  [ -e "$VENV" ] && { echo "Unvollstaendige Build-Umgebung in $VENV — wird neu angelegt."; rm -rf "$VENV"; }
  "$PY" -m venv "$VENV"
fi
if [ ! -x "$VPY" ]; then
  echo "[ERROR] Build-Umgebung liess sich nicht anlegen ($VPY fehlt)."
  echo "        Pruefe: $PY -m venv --help   (auf Debian/Ubuntu fehlt python3-venv oft)"
  exit 1
fi
echo "Using build venv: $VPY ($("$VPY" --version))"

"$VPY" -m pip install --upgrade pip >/dev/null
"$VPY" -m pip install -r requirements.txt pyinstaller pillow >/dev/null

# --- ensure the .icns icon exists -------------------------------------------
if [ ! -f data/icon.icns ]; then
  "$VPY" - <<'PYEOF'
from PIL import Image
src = Image.open("data/vehicles/Rookie.png").convert("RGBA").rotate(90, expand=True)
w, h = src.size; s = min(w, h)
src = src.crop((w//2 - s//2, h//2 - s//2, w//2 + s//2, h//2 + s//2))
c = Image.new("RGBA", (1024, 1024), (14, 16, 22, 255))
c.alpha_composite(src.resize((880, 880), Image.LANCZOS), (72, 72))
c.save("data/icon.icns", format="ICNS")
PYEOF
fi

# --- version + timestamp -----------------------------------------------------
VERSION="$("$VPY" -c 'from src.core import version; print(version.VERSION)')"
# Bauzeit einbrennen — ohne das zeigt die Info-Seite dem Spieler sein eigenes
# Tagesdatum als Build-Datum, weil version.py sonst date.today() nimmt.
"$VPY" tools/baustempel.py
TS="$(date +%Y-%m-%d_%H%M)"
APPNAME="2D-Racing-Game"
OUT="Release/ausgabe"
mkdir -p "$OUT"

echo "============================================"
echo " $APPNAME macOS build"
echo " Version : $VERSION"
echo " Time    : $TS"
echo "============================================"

# --- build -------------------------------------------------------------------
rm -rf build_tmp/stage_mac
"$VPY" -m PyInstaller Release/pyinstaller/game_macos.spec --distpath build_tmp/stage_mac --workpath build_tmp/work_mac --noconfirm

APP="build_tmp/stage_mac/${APPNAME}.app"
if [ ! -d "$APP" ]; then
  echo "[ERROR] Build failed: $APP not found."
  exit 1
fi

# Ad-hoc code signature so the app launches with less Gatekeeper friction.
# (This is NOT an Apple Developer signature/notarization — see README note.)
codesign --force --deep --sign - "$APP" 2>/dev/null \
  && echo "ad-hoc signed" || echo "[warn] codesign skipped (non-fatal)"

# --- package a .dmg ----------------------------------------------------------
DMG="$OUT/${APPNAME}_v${VERSION}_${TS}.dmg"
STAGE_DMG="build_tmp/dmg"
rm -rf "$STAGE_DMG"; mkdir -p "$STAGE_DMG"
cp -R "$APP" "$STAGE_DMG/"
ln -s /Applications "$STAGE_DMG/Applications" || true
hdiutil create -volname "$APPNAME" -srcfolder "$STAGE_DMG" -ov -format UDZO "$DMG"

# --- package a portable .zip of the .app -------------------------------------
# Die App-Clients von itch.io und GameJolt entpacken ein Archiv selbst und
# starten die .app direkt; ein .dmg passt dort schlechter (der Client kann es
# nicht sauber verwalten). ditto statt zip, weil es die Bundle-Struktur und die
# Ressourcen des .app bewahrt; --keepParent legt die .app als oberste Ebene ins
# Archiv, sodass beim Entpacken wieder genau 2D-Racing-Game.app entsteht.
ZIP="$OUT/${APPNAME}_v${VERSION}_${TS}.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"

echo "============================================"
echo " DONE. Upload files:"
echo " DMG (direct download)  : $DMG"
echo " ZIP (itch.io/GameJolt) : $ZIP"
echo "============================================"
