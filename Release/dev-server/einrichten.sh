#!/bin/bash
# Die Entwicklungsinstanz einmalig einrichten (07.08.2026).
#
# Auf dem Helsinki-Server als root ausführen. Danach genügt zum Aktualisieren
# der Doppelklick auf Release/skripte/devserver_aktualisieren.bat vom eigenen
# Rechner aus.
#
#   REPO=git@github.com:philip-hh00/2D-Racing-Game.git ./einrichten.sh
#
# Idempotent: ein zweiter Lauf richtet nichts doppelt ein und überschreibt
# nichts, was schon passt.
set -euo pipefail

: "${DEV_NUTZER:=gameuser}"
: "${DEV_ORDNER:=/home/gameuser/racing-server-dev}"
: "${DEV_DIENST:=rennspiel-dev}"
: "${REPO:=https://github.com/philip-hh00/2D-Racing-Game.git}"
: "${ZWEIG:=main}"

[ "$(id -u)" -eq 0 ] || { echo "[FEHLER] Als root ausfuehren." >&2; exit 1; }
HIER="$(cd "$(dirname "$0")" && pwd)"

ELTERN="$(dirname "$DEV_ORDNER")"
echo "== Einrichtung =="
echo "   Nutzer  : $DEV_NUTZER"
echo "   Ordner  : $DEV_ORDNER"
echo "   Dienst  : $DEV_DIENST"
echo "   Repo    : $REPO ($ZWEIG)"
echo

# Zwei Annahmen, die dieses Skript trifft und die falsch sein koennen. Sie
# hier zu pruefen kostet nichts; sie erst nach der halben Einrichtung zu
# bemerken kostet Aufraeumen.
if ! id -u "$DEV_NUTZER" >/dev/null 2>&1; then
  echo "[FEHLER] Nutzer $DEV_NUTZER gibt es nicht." >&2
  echo "         Vorhanden sind u.a.: $(ls /home | tr '\n' ' ')" >&2
  echo "         Abhilfe:  DEV_NUTZER=... DEV_ORDNER=/home/.../racing-server-dev $0" >&2
  exit 1
fi
if [ ! -d "$ELTERN" ]; then
  echo "[FEHLER] Verzeichnis gibt es nicht: $ELTERN" >&2
  exit 1
fi
# Der Dev-Server soll **neben** dem Live-Server liegen. Liegt dort keiner, ist
# entweder der Pfad falsch geraten oder der Live-Server steht woanders — in
# beiden Faellen besser einmal hinsehen als hinterher suchen.
if [ ! -d "$ELTERN/racing-server" ]; then
  echo "[WARNUNG] In $ELTERN liegt kein racing-server."
  echo "          Steht der Live-Server woanders? Dann DEV_ORDNER passend setzen."
  echo "          Gefunden:  $(ls -d "$ELTERN"/*/ 2>/dev/null | tr '\n' ' ')"
  echo
fi

echo "== 1/5  Klon anlegen =="
if [ -d "$DEV_ORDNER/.git" ]; then
  echo "   gibt es schon: $DEV_ORDNER"
else
  sudo -u "$DEV_NUTZER" git clone --branch "$ZWEIG" "$REPO" "$DEV_ORDNER"
fi

echo "== 2/5  Umgebung =="
if [ -f /etc/rennspiel-dev.env ]; then
  echo "   gibt es schon: /etc/rennspiel-dev.env (unveraendert gelassen)"
else
  install -m 0644 "$HIER/rennspiel-dev.env" /etc/rennspiel-dev.env
  echo "   angelegt: /etc/rennspiel-dev.env"
fi

echo "== 3/5  Aktualisierer =="
# Bewusst nach /usr/local/bin und nicht aus dem Klon gestartet: sonst tauscht
# ein Pull das Skript aus, waehrend es laeuft.
install -m 0755 "$HIER/dev_aktualisieren.sh" /usr/local/bin/rennspiel-dev-update
echo "   installiert: /usr/local/bin/rennspiel-dev-update"

echo "== 4/5  Dienst =="
install -m 0644 "$HIER/rennspiel-dev.service" \
        /etc/systemd/system/"$DEV_DIENST".service
# Genau ein Recht, und nur fuer diese eine Unit: der Aktualisierer muss sie neu
# starten koennen, ohne dass jemand ein Passwort tippt. Mehr braucht er nicht,
# und mehr bekommt er nicht.
cat > /etc/sudoers.d/rennspiel-dev <<EOF
$DEV_NUTZER ALL=(root) NOPASSWD: /bin/systemctl restart $DEV_DIENST, /usr/bin/systemctl restart $DEV_DIENST
EOF
chmod 0440 /etc/sudoers.d/rennspiel-dev
visudo -cf /etc/sudoers.d/rennspiel-dev >/dev/null
systemctl daemon-reload
systemctl enable --now "$DEV_DIENST"
echo "   $DEV_DIENST laeuft: $(systemctl is-active "$DEV_DIENST")"

echo "== 5/5  Firewall =="
# Zwei Anlaeufe, zwei falsche Auskuenfte — deshalb steht hier jetzt mehr als
# eine Zeile.
#
# Erst hing die Bedingung an einer englischen Statuszeile von ufw und meldete
# "kein aktives ufw", obwohl die ufw-Ketten im Regelwerk standen. Dann stellte
# sich heraus: **ufw ist gar nicht installiert.** Die Ketten sind Ueberreste,
# und die Freigaben der Live-Ports stehen direkt in der INPUT-Kette — gesetzt
# also mit iptables, nicht mit ufw (07.08.2026).
#
# Also nicht raten, welches Werkzeug gemeint ist, sondern nehmen, was da ist.
# Eine ACCEPT-Regel ist in jedem Fall ungefaehrlich; und schlaegt hier etwas
# fehl, darf es die Einrichtung nicht abbrechen — der Server laeuft dann, er
# ist nur noch nicht erreichbar.
_freigeben() {
  local tcp=7878 udp=7877
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "$tcp"/tcp comment "Rennspiel Dev TCP" >/dev/null 2>&1 || true
    ufw allow "$udp"/udp comment "Rennspiel Dev UDP" >/dev/null 2>&1 || true
    echo "   ufw: $tcp/tcp und $udp/udp eingetragen"
    return 0
  fi
  if command -v iptables >/dev/null 2>&1; then
    # -C fragt, ob es die Regel schon gibt: ohne das saehe ein zweiter Lauf
    # dieselbe Regel doppelt in der Kette.
    iptables -C INPUT -p tcp --dport "$tcp" -j ACCEPT 2>/dev/null \
      || iptables -A INPUT -p tcp --dport "$tcp" -j ACCEPT
    iptables -C INPUT -p udp --dport "$udp" -j ACCEPT 2>/dev/null \
      || iptables -A INPUT -p udp --dport "$udp" -j ACCEPT
    echo "   iptables: $tcp/tcp und $udp/udp freigegeben"
    if command -v netfilter-persistent >/dev/null 2>&1; then
      netfilter-persistent save >/dev/null 2>&1 \
        && echo "   dauerhaft gespeichert (netfilter-persistent)" \
        || echo "   [WARNUNG] Speichern fehlgeschlagen — Regel gilt bis zum Neustart"
    else
      echo "   [WARNUNG] netfilter-persistent fehlt — die Regel gilt nur bis"
      echo "             zum Neustart. Dauerhaft: apt install iptables-persistent"
    fi
    return 0
  fi
  echo "   [WARNUNG] weder ufw noch iptables gefunden — $tcp/tcp und $udp/udp"
  echo "             von Hand freigeben."
  return 0
}
_freigeben || true
echo "   Nachsehen:  iptables -L INPUT -n | grep -E '7878|7877'"
echo "   Bei Hetzner zaehlt zusaetzlich die Cloud-Firewall im Konsolen-Portal."

echo
echo "Fertig. Zum Aktualisieren von Hand:"
echo "   sudo -u $DEV_NUTZER rennspiel-dev-update <zweig>"
