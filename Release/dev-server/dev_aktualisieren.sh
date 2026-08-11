#!/bin/bash
# Die Entwicklungsinstanz auf einen Stand aus dem Repo bringen (07.08.2026).
#
#   dev_aktualisieren.sh [branch]      Vorgabe: main
#
# **Wird nach /usr/local/bin/ kopiert, nicht aus dem Klon gestartet.** Der Grund
# ist eine Falle, die sonst irgendwann zuschlägt: bash liest ein Skript
# **während** es läuft, häppchenweise. Läge diese Datei im Klon, würde ein Pull
# sie mitten im Lauf unter dem Interpreter austauschen — und was danach
# ausgeführt wird, steht in keinem Verhältnis mehr zu dem, was jemand gelesen
# hat. Deshalb: einmal installieren, dann liegt sie außerhalb dessen, was sie
# selbst verändert.
#
# Was hier passiert, ist Absicht und keine Vorsicht: der Klon wird **hart** auf
# den Stand des Zweigs gesetzt. Der Dev-Server soll den Zweig abbilden, nicht
# einen eigenen Zustand pflegen. Alles, was dort von Hand geändert wurde, ist
# danach weg — auch `server/live_config.json`.
set -euo pipefail

: "${DEV_ORDNER:=/home/gameuser/racing-server-dev}"
: "${DEV_DIENST:=rennspiel-dev}"
BRANCH="${1:-main}"

# Sicherung gegen den einen Fehler, der wirklich weh täte: dieses Skript darf
# den Live-Server nicht anfassen. Es setzt hart zurück — auf dem falschen
# Verzeichnis wäre das ein laufendes Rennen weniger.
case "$DEV_ORDNER" in
  *-dev|*-dev/) ;;
  *) echo "[FEHLER] DEV_ORDNER endet nicht auf -dev: $DEV_ORDNER" >&2
     echo "         Das sieht nach dem Live-Server aus. Abbruch." >&2
     exit 1 ;;
esac
[ -d "$DEV_ORDNER/.git" ] || { echo "[FEHLER] Kein Git-Klon: $DEV_ORDNER" >&2; exit 1; }

cd "$DEV_ORDNER"

echo "== Entwicklungsinstanz aktualisieren =="
echo "   Ordner : $DEV_ORDNER"
echo "   Zweig  : $BRANCH"
echo "   Vorher : $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-60)"
echo

git fetch --prune --quiet origin
if ! git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null; then
  echo "[FEHLER] Zweig gibt es auf GitHub nicht: $BRANCH" >&2
  echo "         Vorhanden sind u.a.:" >&2
  git branch -r --format='           %(refname:short)' | head -10 >&2
  exit 1
fi

git checkout -q -B "$BRANCH" "origin/$BRANCH"
git reset -q --hard "origin/$BRANCH"

echo "   Nachher: $(git rev-parse --short HEAD) $(git log -1 --format=%s | cut -c1-60)"
echo

# Der Server braucht nur die Standardbibliothek (server/requirements.txt sagt
# das ausdrücklich). Trotzdem nachsehen, statt es vorauszusetzen: kommt dort
# je etwas dazu, soll es hier auffallen und nicht beim ersten Verbindungsversuch.
if grep -qvE '^\s*(#|$)' server/requirements.txt 2>/dev/null; then
  echo "== Abhängigkeiten =="
  python3 -m pip install --quiet --user -r server/requirements.txt
fi

echo "== Dienst neu starten =="
sudo systemctl restart "$DEV_DIENST"
sleep 1
if systemctl is-active --quiet "$DEV_DIENST"; then
  echo "   laeuft."
else
  echo "[FEHLER] $DEV_DIENST laeuft nicht. Letzte Zeilen:" >&2
  journalctl -u "$DEV_DIENST" -n 20 --no-pager >&2
  exit 1
fi

echo
journalctl -u "$DEV_DIENST" -n 5 --no-pager
echo
echo "Fertig. Lobbycodes dieser Instanz beginnen mit T."
