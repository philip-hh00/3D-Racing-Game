# Online-Schutz (1.1.0)

Gilt für beide Spiele; der Relay (`server/server.py` + `server/schutz.py`) läuft aus
dem Repo des 2D-Spiels, das 3D-Repo trägt eine Kopie (Tests). Die Logik steht in
`server/schutz.py` (reine Funktionen, nur Standardbibliothek), `server.py` ruft sie
an kurzen Haken auf und hat einen eigenen Block „Schutz" (KICK, REPORT_PLAYER).

## 1. Dateiprüfsumme

* `HOST`/`JOIN` tragen `game` (`"2d"`/`"3d"`) und `files` (SHA-256).
* Die Summe bildet `src/core/integritaet.py` über `data/vehicles/*.json` (ohne
  `lacke.json`), die fünf mitgelieferten Strecken (`data/tracks/<name>.json`) und im
  2D-Spiel `data/ai_settings/*.json`. **Kanonisch**: der JSON-*Inhalt* wird in fester
  Schreibweise gehasht (sortierte Schlüssel, ASCII), Pfade mit `/`, sortiert.
  Zeilenenden, Einrückung, BOM, Schlüsselreihenfolge, Windows/macOS, Quelltext/PyInstaller
  ändern die Summe nicht (getestet).
* Der Relay lässt nur herein, wenn die Summe zu `(game, version)` in
  `server/pruefsummen.json` steht. Sonst `JOIN_FAIL` mit `code: MODIFIED_FILES`.
  Fehlt die Datei oder der Eintrag, wird ebenfalls abgewiesen (und laut protokolliert).
* Anderes Spiel in der Lobby: `JOIN_FAIL` `WRONG_GAME`.
* **Schalter** (nur Umgebung des Relays): `RACE_FILES_CHECK=enforce` (Vorgabe) |
  `log` (nur protokollieren, alle herein) | `off`. Für die Entwicklungsinstanz steht
  `log` in `Release/dev-server/rennspiel-dev.env`.

### Release-Schritt

Pro Spiel und Version, wenn die Daten feststehen:

```
python tools/pruefsummen.py --eintragen server/pruefsummen.json <anderes-Repo>/server/pruefsummen.json
git add server/pruefsummen.json   # in beiden Repos committen
```

Der Eintrag enthält außerdem Höchsttempo je Fahrzeug (px/s) und Streckenlängen (px) für
die Plausibilität. `--pruefen` vergleicht Datei und Stand und scheitert, wenn sie
auseinanderlaufen. Es läuft in `Release/skripte/build_windows.bat`, `build_macos.sh`,
`release_starten.bat/.sh` (vor dem Tag) und in `.github/workflows/release.yml` (eigener
Job auf Linux, dazu in jedem Bauauftrag, also auch macOS). Der Relay liest die Datei bei
jeder Änderung neu: `git pull` genügt.

## 2. Plausibilität

Positionsstrom (UDP `STATE`, nur im Rennen), je Fahrzeug nach **Ankunftszeit am Relay**:

* Guthaben-Modell: je Sekunde dürfen `1,35 × Höchsttempo` Pixel zurückgelegt werden; das
  Guthaben wächst mit der Zeit (ohne Obergrenze während einer Funkstille) und ist beim
  Ansparen auf 3 s Fahrt begrenzt. Verzögerte, geballte, verlorene und vertauschte Pakete
  ändern daran nichts (Tests mit 25 % Verlust, 2,5 s Stau, Funkstille).
* Fehlbetrag > 100 px = 1 Punkt, > 600 px über dem Guthaben (Sprung) = 3 Punkte;
  gemeldetes Tempo > 1,6 × Höchsttempo über 2 s = 1,5 Punkte. Ab 3 Punkten gilt der
  Spieler für dieses Rennen als verdächtig.

Ergebniszeilen (`RACE_RESULT`):

* nur bekannte Felder; nur die eigene Zeile (Host zusätzlich KI-Zeilen), Doppelte weg;
  fremde Zeilen = 3 Punkte.
* Zeit < Runden × (0,7 × Mittellinie ÷ höchstes Tempo) oder beste Runde darunter;
  `beste Runde × Runden > Gesamtzeit`; Abweichung von dem, was der Relay selbst im
  Rundenzähler des Stroms gesehen hat (3 s + 3 % Spielraum; Pausen und Countdown
  herausgerechnet).
* `FIRST_FINISH` wird nur geglaubt, wenn die Rennuhr mindestens Runden × Mindestrunde
  zeigt; die Schonfrist ist nie kürzer als die Mindestrunde.
* Verdächtige/unmögliche Zeilen gehen als `invalid: true` (mit `dnf: true`, ohne Zeiten)
  an alle und stehen am Ende. Der Relay protokolliert (`Schutz: …`).

**Grenzen:** wer lange steht und dann weniger als das angesparte Guthaben (~4 000 px)
springt, fällt nicht auf; Tempo bis 1,35 × Höchsttempo auch nicht; ein Client, der
konsistente gefälschte Pakete mit passendem Rundenzähler schickt, nicht. Code-Änderungen
im Quelltext-Spiel erfasst die Prüfsumme nicht.

## 3. Entfernen

Host schickt `KICK {slot}`. Relay → Spieler `KICKED {by}`, dann Verbindung zu;
`PLAYER_LEFT` + `LOBBY_STATE` an die anderen. Der Spieler kommt in diese Lobby nicht
wieder (`JOIN_FAIL` `KICKED`), bis sie geschlossen wird: gesperrt wird die Kennung (`cid`),
die Adresse (nur wo sie jemanden unterscheidet, nicht hinter dem Tunnel) und, ohne beides,
der Name. Hinter einer gemeinsamen Heimadresse trifft die Adressensperre auch Mitbewohner.
**Wann:** in der Lobby und zwischen den Rennen; während Start/Rennen `ERROR KICK_BUSY`.
Im Spiel: Kreuzknopf neben jedem Mitspieler (Maus, Tastatur, Controller), mit Rückfrage.

## 4. Melden

Ergebnisliste: Fahne je Mitmensch → Grund (Schummeln, Unsportlich, Name, Sonstiges) →
`REPORT_PLAYER {slot, name, reason: cheating|griefing|name|other}` → `REPORT_OK`.
Fehler: `ERROR` `REPORT_UNKNOWN|SELF|REASON|RATE|OFF`. Abgelegt in
`server/meldungen/meldungen.json` (`RACE_MELDUNGEN_DIR`): Melder (Name, cid), Ziel (Name,
cid, Hash der Adresse), Lobby, Spiel, Version, Zeit, Grund, Verdachtsmarken. Grenzen: 6
je Stunde, 20 je Tag je Melder, höchstens 5 verschiedene Ziele je Lobby, Doppelte
zählen nicht. Verwaltung: `python tools/meldungen_verwalten.py list|top|zeige|erledigt|loeschen`.
