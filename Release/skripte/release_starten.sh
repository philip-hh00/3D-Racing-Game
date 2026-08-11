#!/bin/bash
# Startet die Pipeline auf GitHub, indem ein Tag gesetzt und gepusht wird.
# Es braucht nichts ausser git — kein zusaetzliches Werkzeug, keine Anmeldung.
#
#   ./release_starten.sh          fragt nach: Testbuild oder Release
#   ./release_starten.sh test     gleich ein Testbuild, ohne Rueckfrage
#   ./release_starten.sh release  gleich ein Release, ohne Rueckfrage
#
# Der Unterschied liegt allein im Tag. Ein Testbuild traegt dieselbe Version und
# unterscheidet sich nur in der eingebrannten Bauzeit; er legt deshalb kein
# Release an, sondern haengt die Pakete als Artefakt an den Lauf.
#
# Schwesterskript zu release_starten.bat — beide muessen dieselben Tagnamen
# erzeugen, sonst greift der Ablauf in .github/workflows/release.yml nicht.
set -e
cd "$(dirname "$0")/../.."

ART="${1:-}"
PY="${PY:-python3}"

VERSION="$("$PY" -c 'from src.core import version; print(version.VERSION)')"
[ -n "$VERSION" ] || { echo "[FEHLER] Version konnte nicht gelesen werden."; exit 1; }

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# Erst den Stand von GitHub holen. Ohne das kennt keiner der Vergleiche unten
# die Wahrheit: weder ob dieser Branch hinterherhinkt, noch ob es den Tag
# drueben schon gibt.
git fetch --quiet origin "$BRANCH" --tags 2>/dev/null || true

# Zeigt der Tag auf einen veralteten Commit, wird der falsche Stand gebaut —
# und das faellt erst auf, wenn im fertigen Paket etwas fehlt. Am 06.08.2026
# genau so passiert: getaggt wurde zwei Merges vor dem aktuellen Stand.
HINTEN=0
if git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  HINTEN="$(git rev-list --count "HEAD..origin/$BRANCH" 2>/dev/null || echo 0)"
fi

# Ein Tag zeigt auf einen Commit, nicht auf den Arbeitsbaum. Ungespeicherte
# Aenderungen waeren im Build nicht drin — und das faellt sonst erst auf, wenn
# das fertige Paket sie nicht enthaelt.
if [ -z "$(git status --porcelain)" ]; then SAUBER="ja"; else SAUBER="nein"; fi

# Was soll gebaut werden? Frueher entschied das ein Argument, das man beim
# Aufruf vergisst — und ein vergessenes Argument hiess: aus Versehen eine
# Versionsnummer verbraucht, die sich nicht mehr zurueckholen laesst
# (gemeldet 07.08.2026). Jetzt wird gefragt.
if [ -z "$ART" ]; then
  echo
  echo " Was soll gebaut werden?"
  echo
  echo "   [1]  Testbuild    — Pakete zum Ausprobieren, kein Release,"
  echo "                       verbraucht KEINE Versionsnummer"
  echo "   [2]  Release      — offizielle Fassung v${VERSION} als Entwurf"
  echo
  while true; do
    read -r -p "Auswahl [1/2, Enter = 1]: " WAHL
    case "${WAHL:-1}" in
      1) ART="test"; break ;;
      2) ART="release"; break ;;
      *) echo "Bitte 1 oder 2." ;;
    esac
  done
fi

if [ "$ART" = "test" ]; then
  TAG="test-${VERSION}-$(date +%m%d-%H%M)"
  WAS="Testbuild (kein Release, Pakete als Artefakt am Lauf)"
else
  TAG="v${VERSION}"
  WAS="Release (Entwurf mit beiden Paketen)"
fi

echo
echo "============================================"
echo " Pipeline starten"
echo " Version     : $VERSION"
echo " Branch      : $BRANCH"
echo " Arbeitsbaum : $SAUBER"
echo " Rueckstand  : $HINTEN Commit(s) hinter origin/$BRANCH"
echo " Tag         : $TAG"
echo " Ergebnis    : $WAS"
echo "============================================"
echo

if [ "$SAUBER" = "nein" ]; then
  echo "[WARNUNG] Der Arbeitsbaum ist nicht sauber. Ein Tag zeigt auf den"
  echo "          letzten Commit — alles Ungespeicherte fehlt im Build."
  echo
fi

if [ "$HINTEN" != "0" ]; then
  echo "[FEHLER] Dieser Branch ist $HINTEN Commit(s) hinter origin/$BRANCH."
  echo "         Getaggt wuerde der alte Stand, gebaut also das Falsche."
  echo "         Abhilfe:  git pull --ff-only"
  exit 1
fi

# Ein doppelt vergebener Tag wird von GitHub abgewiesen, und die Meldung dazu
# ist wenig hilfreich. Lieber hier sagen, was los ist.
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null 2>&1 \
   || git ls-remote --exit-code --tags origin "$TAG" >/dev/null 2>&1; then
  echo "[FEHLER] Tag $TAG gibt es schon (oertlich oder auf GitHub)."
  if [ "$ART" = "test" ]; then
    echo "         Eine Minute warten, der Zeitstempel aendert sich."
  else
    echo "         Fuer eine neue Fassung VERSION in src/core/version.py erhoehen."
  fi
  exit 1
fi

read -r -p "Tag $TAG setzen und pushen? [j/N] " ANTWORT
case "$ANTWORT" in
  j|J) ;;
  *) echo "Abgebrochen."; exit 0 ;;
esac

git tag "$TAG"
# Schlaegt der Push fehl, darf der Tag nicht oertlich stehenbleiben — sonst
# meldet der naechste Lauf "gibt es schon", ohne dass je etwas gebaut wurde.
git push origin "$TAG" || { echo "[FEHLER] Push fehlgeschlagen — Tag wird zurueckgenommen."; git tag -d "$TAG"; exit 1; }

echo
echo "============================================"
echo " Gestartet. Der Fortschritt steht unter:"
echo " $(git remote get-url origin)  ->  Actions"
echo
echo " Erst wenn die Tests gruen sind, wird gebaut. Sind sie rot,"
echo " entsteht KEIN Paket — der Tag steht dann trotzdem da."
echo " Das Zip \"Source code\" an einem Tag ist nicht der Build,"
echo " das legt GitHub von sich aus an."
echo "============================================"
