# Entwicklungsserver neben dem Live-Server

Zweite Serverinstanz neben dem Live-Server, damit neue Modi und die Fehlersuche
ihn nicht anfassen. Nach dem öffentlichen Release ist das der Unterschied
zwischen „ich probiere etwas aus" und „ich werfe gerade Spieler aus ihrem
Rennen".

Sie läuft in **Helsinki** (Hetzner-VPS), nicht auf dem Hamburger Heimserver —
entschieden am 06.08.2026. Helsinki ist direkt erreichbar und hat freie Ports;
Hamburg hängt hinter playit.gg-Tunneln, und dort bräuchte eine zweite Instanz
eigene. Das war der einzige nennenswerte Aufwand an der ganzen Sache, und er
fällt damit weg.

Der Code kann das bereits: **alle** Grenzen und Ports kommen aus der Umgebung,
es gibt nichts zu ändern. Was hier steht, ist die Betriebsanleitung.

---

## Das eine Zeichen, auf das es ankommt

Jeder Lobbycode beginnt mit dem Kennzeichen des Servers, auf dem er entstanden
ist. Daran — und nur daran — erkennt ein beitretender Client, wohin er sich
verbinden muss. Vergeben sind:

| Zeichen | Server |
|---|---|
| `H` | Helsinki (VPS) |
| `D` | Hamburg (Heimserver), live |
| `T` | Helsinki, Entwicklungsinstanz |

`T` steht **nicht** im ausgelieferten Katalog (`data/settings/servers.dat`). Ein
Spieler, der versehentlich einen `T`-Code eingetippt bekommt, liest „Unbekannter
Lobby-Code" und landet nicht in der Baustelle. `tests/test_servers_config.py`
hält beides fest: dass `T` nicht ausgeliefert wird und dass kein Kennzeichen
doppelt vergeben ist.

Server- und Clientseite müssen sich über dieses Zeichen einig sein. Stimmen sie
nicht überein, erzeugt der Dev-Server `T`-Codes, die derselbe Client als
unbekannt abweist — der Fehler sieht dann nach einem Netzproblem aus und ist
keines.

---

## Einrichten — einmal, auf dem Server

Der Dev-Server liegt **neben** dem Live-Server, im Heimatverzeichnis desselben
Nutzers:

```
/home/gameuser/racing-server        ← live, unberührt
/home/gameuser/racing-server-dev    ← Entwicklung, Kennzeichen T
```

Ob die Pfade oben stimmen, sagt ein Blick — der Live-Server muss nicht dort
liegen, wo diese Anleitung ihn vermutet:

```bash
systemctl show -p WorkingDirectory racing-server
```

Alles Nötige liegt fertig in `Release/dev-server/`. Als root auf dem Helsinki-
Server:

```bash
git clone --depth 1 https://github.com/philip-hh00/2D-Racing-Game.git /tmp/rennspiel-setup
cd /tmp/rennspiel-setup/Release/dev-server
./einrichten.sh
```

`--depth 1` mit Absicht: das Repo wiegt mit Verlauf und Videos rund 280 MB, und
für die Einrichtung wird nichts davon gebraucht. Der eigentliche Klon des
Dev-Servers entsteht ohnehin erst im Skript.

**Das Einrichtungspaket muss auf dem geklonten Zweig liegen.** Ein `git clone`
ohne Angabe holt den Standardzweig; steckt `Release/dev-server/` noch in einem
offenen Pull Request, ist der Ordner dort schlicht nicht da:

```
-bash: cd: /tmp/rennspiel-setup/Release/dev-server: No such file or directory
```

Dann entweder den Pull Request mergen oder `--branch <zweig>` mitgeben.

Passt etwas nicht, sagt das Skript es **vor** dem ersten Eingriff: es prüft, ob
es den Nutzer gibt, und meldet sich, wenn im Zielverzeichnis kein
`racing-server` daneben liegt. Abweichende Pfade lassen sich mitgeben:

```bash
DEV_NUTZER=gameuser DEV_ORDNER=/pfad/zu/racing-server-dev ./einrichten.sh
```

Das legt in fünf Schritten an: den Klon unter `gameuser`, `/etc/rennspiel-dev.env`,
den Aktualisierer unter `/usr/local/bin/rennspiel-dev-update`, die systemd-Unit
`rennspiel-dev` samt einer eng gefassten sudo-Regel, und gibt die Ports frei
(siehe unten). Der Lauf ist idempotent — ein zweiter richtet nichts doppelt ein.

Drei Dinge, die dabei bewusst so sind:

* **Der Aktualisierer liegt außerhalb des Klons.** bash liest ein Skript
  *während* es läuft, häppchenweise. Läge es im Klon, tauschte ein Pull es
  mitten im Lauf unter dem Interpreter aus.
* **Die sudo-Regel erlaubt genau einen Befehl**, `systemctl restart
  rennspiel-dev`. Mehr braucht der Aktualisierer nicht, und mehr bekommt er
  nicht.
* **Eigenes Verzeichnis statt eines geteilten.** Sonst läge `live_config.json`
  für beide Instanzen an derselben Stelle, und eine Testankündigung erschiene
  bei echten Spielern.

Bei einem **privaten** Repo braucht `gameuser` einen Deploy-Key
(`ssh-keygen`, öffentlichen Teil in GitHub unter Settings → Deploy keys) und
`REPO=git@github.com:philip-hh00/2D-Racing-Game.git` beim Einrichten.

### Die Ports

Das Skript gibt **TCP 7878** und **UDP 7877** frei — mit `ufw`, wenn es das
gibt, sonst mit `iptables`, und es sagt, was es genommen hat. Auf welches
Werkzeug es trifft, rät es nicht: auf dem Helsinki-Server standen ufw-Ketten im
Regelwerk, obwohl `ufw` gar nicht installiert war (Überreste), und die Freigaben
der Live-Ports lagen direkt in der INPUT-Kette.

Zwei Dinge, die es selbst nicht lösen kann:

* **Dauerhaftigkeit.** Eine `iptables`-Regel überlebt den Neustart nur, wenn
  `netfilter-persistent` sie speichert. Fehlt das Paket, sagt das Skript es —
  eine Regel, die bis zum nächsten Neustart gilt, ist schlimmer als keine, weil
  sie genau so lange funktioniert, bis niemand mehr damit rechnet. Auf dem
  Helsinki-Server ist `netfilter-persistent` **aktiviert** (`nftables` dagegen
  abgeschaltet), die Regeln landen also in `/etc/iptables/rules.v4` und stehen
  nach einem Neustart wieder.
* **Die Hetzner-Cloud-Firewall.** Sie filtert *außerhalb* der Maschine und ist
  im Regelwerk des Servers nicht zu sehen. Wer nur dort nachsieht, sucht am
  falschen Ort.

Nachsehen auf der Maschine:

```bash
iptables -L INPUT -n | grep -E '7878|7877'
```

Ob es von außen wirklich durchkommt, sagt nur ein Versuch von deinem Rechner —
siehe „Clientseite" weiter unten.

**Abgenommen am 07.08.2026.** Der Rauchtest gegen die Entwicklungsinstanz lief
mit 9 ok, 0 Warnungen, 0 Fehlern durch: `server_tag = T`, Lobbycode `T9O33L`,
UDP-Ping 45 ms. Eine Hetzner-Cloud-Firewall stand dem nicht im Weg.

---

## Aktualisieren — per Doppelklick

Der Dev-Server hängt an demselben Werkzeug wie die Live-Server:

```
Release\skripte\deploy_servers.bat
```

Es fragt zuerst, was gedeployt werden soll:

```
  Was soll deployt werden?

    [1]  Live       - Helsinki + Hamburg (wie bisher)
    [2]  Dev        - nur die Entwicklungsinstanz auf Helsinki
    [3]  Alles      - beide Live-Server und die Entwicklungsinstanz

Auswahl [1/2/3, Enter = 1]:
```

Die Eingabetaste macht das, was das Skript immer gemacht hat — beide
Live-Server. Wer nur den Dev-Server aktualisiert, fasst die Live-Server nicht
an, und umgekehrt genauso. Für Gewohnte geht auch `deploy_servers.bat dev`
direkt.

Bei `Dev` fragt es nach dem Zweig, Vorgabe ist der hiesige. Danach läuft auf dem
Server `rennspiel-dev-update <zweig>`: fetch, harter Wechsel auf den Zweig,
Dienst neu starten, Zustand und die letzten Protokollzeilen zurück. Von Hand
geht dasselbe:

```bash
sudo -u gameuser rennspiel-dev-update mein-zweig
```

**Zwei verschiedene Verfahren, mit Absicht.** Die Live-Server ziehen mit
`--ff-only`: dort darf nie ein Merge-Commit entstehen, und weicht ein Server ab,
bricht der Pull ab statt still etwas zusammenzuführen. Der Dev-Server setzt
dagegen **hart** zurück — er soll einen Zweig abbilden, nicht einen eigenen
Zustand pflegen. Alles, was dort von Hand geändert wurde, ist danach weg, auch
`server/live_config.json`.

Der Aktualisierer weigert sich, wenn der Zielordner nicht auf `-dev` endet. Ein
hartes Zurücksetzen auf dem Live-Server wäre ein laufendes Rennen weniger.

Der Pull läuft als `gameuser`, nicht als root — sonst gehörten die neuen Dateien
danach root und `gameuser` könnte nicht mehr schreiben. Dieselbe Begründung wie
beim Live-Server auf Helsinki.

---

## Clientseite

Der Katalog wird über die Umgebung überschrieben — es braucht keinen eigenen
Build und keine geänderte `servers.dat`:

```sh
RACE_SERVER_HOST=<Adresse des Dev-Servers> \
RACE_SERVER_TAG=T \
RACE_SERVER_PORT=7878 \
RACE_SERVER_UDP_PORT=7877 \
python main.py
```

Unter Windows (PowerShell):

```powershell
$env:RACE_SERVER_HOST="..."; $env:RACE_SERVER_TAG="T"
$env:RACE_SERVER_PORT="7878"; $env:RACE_SERVER_UDP_PORT="7877"
python main.py
```

Die Serverliste im Online-Menü zeigt dann **nur** „Dev". Das ist Absicht: solange
die Variablen gesetzt sind, kann kein Klick versehentlich auf dem Live-Server
landen. Zum Zurückschalten die Variablen leeren.

`RACE_SERVER_UDP_PORT` fällt auf `RACE_SERVER_PORT` zurück, wenn es fehlt — was
für einen Server ohne getrennte Tunnel meist das Richtige ist.

---

## Was ohnehin schon ohne Neustart geht

Nicht jede Änderung braucht die zweite Instanz. `server/live_config.json` liest
der Server **im Betrieb** neu:

* `required_version` — die Mindestversion, die Clients mitbringen müssen
* `announcements` — die Ankündigungen im Info-Reiter

Dafür genügt das Bearbeiten der Datei. Die Dev-Instanz ist für alles andere da:
Protokolländerungen, neue Modi, alles, was den Serverprozess selbst betrifft.

---

## Grenze

Der Dev-Server ist **nicht** abgesichert wie der Live-Server. Er kennt dieselben
Grenzen aus Block H, aber er läuft mit kleinen Werten und du wirst ihn beim
Ausprobieren in Zustände bringen, gegen die niemand gehärtet hat. Deshalb die
kleinen Grenzen, deshalb kein Kennzeichen im ausgelieferten Katalog — und
deshalb sind seine Ports nichts, was man weitergibt.
