# Plan 1.1.0

Stand 07.10.2026, abgestimmt mit dem Owner. 1.0.1 (Fehlerbehebungen, Fenster
auf dem MacBook) ist davon getrennt und fertig.

## 1. Kameraansichten (Kern von 1.1.0)

Umschaltbar per Taste und Controller, die Wahl bleibt im Profil:

| Ansicht | Inhalt |
|---|---|
| Verfolger fern | heutige Kamera |
| Verfolger nah | zweiter Abstand, tiefer |
| Motorhaube | Kamera auf der Haube, Karosserie sichtbar |
| Cockpit | Sicht vom Fahrersitz, ohne Hände |
| Zurückschauen | eigene Taste, solange gedrückt: Blick nach hinten |

**Cockpit:**
- Das Lenkrad dreht mit dem Lenkeinschlag.
- Echte Instrumente: Tacho und Drehzahl im Armaturenbrett zeigen die
  Fahrzeugwerte. Das HUD blendet im Cockpit dafür seine Rundinstrumente aus.
- Funktionierende Spiegel: Rück- und Außenspiegel zeigen das Feld dahinter
  (zweite Kamera in eine kleine Textur, reduzierte Detailstufe, je nach
  Grafikstufe abschaltbar).

**Assets:** Innenraum, Lenkrad und Armaturen gibt es
(`tools/blender/teile_innen.py`). Nötig sind:
- Augpunkt je Fahrzeug
- Spiegelflächen als eigene Knoten
- Tacho- und Drehzahlnadel als eigene Knoten
- Lenkrad mit Ursprung in der Lenksäulenachse

## 2. Movie-Modus nach der Zieldurchfahrt

- Nach der eigenen Zieldurchfahrt zoomt die Kamera heraus.
- Danach laufen TV-Kameras: feste Punkte an der Strecke, die automatisch
  wechseln und dem nächsten Fahrzeug folgen. Vorbild sind übliche Rennspiele.
- Das läuft, solange die anderen noch fahren. 30 Sekunden, nachdem alle im
  Ziel oder DNF sind, geht es in die Ergebnisübersicht wie bisher.
- Online darf man nicht hängen bleiben: Die Ergebnisse vom Server kommen
  weiter an, der Timer bestimmt nur, wann die Übersicht erscheint.

## 3. Fahrhilfen (ohne Lenkhilfe)

- Ideallinie einblendbar, nach Bremszonen eingefärbt
- ABS
- Traktionskontrolle
- Alle Hilfen sind einzeln in den Einstellungen schaltbar. Die KI ist davon
  unberührt.

## 4. Tageszeit und Wetter

- Tageszeit je Rennen: Tag, Abend, Nacht. Nachts sind die Scheinwerfer und
  Rückleuchten echte Lichtquellen.
- Wetter als zweiter Schritt: Regen mit nasser Fahrbahn (Spiegelung, weniger
  Grip, Gischt).
- Online legt der Gastgeber Tageszeit und Wetter für alle fest.

## 5. Strecken online austauschen

- Spieler laden eigene Strecken aus dem Editor auf den Server hoch.
- Andere durchsuchen die Liste und laden Strecken herunter (Name, Thema,
  Länge, Vorschaubild).
- Offen: Moderation (Namensfilter vorhanden), Speicherplatz auf dem Relais,
  Missbrauchsschutz. Das braucht eine Server-Änderung, also ein Deploy.

## 6. Controller-Vibration

Rumble bei Kontakt, Rutschen, Randstein und Mauer, in der Stärke einstellbar.

## Reihenfolge

1. Kameras und Cockpit (größter Brocken, Blender-Assets)
2. Movie-Modus (nutzt die Kamerainfrastruktur aus 1)
3. Fahrhilfen und Vibration (klein, unabhängig)
4. Tageszeit, danach Wetter
5. Streckenaustausch (Server-Änderung zuletzt, eigenes Deploy)

Online-relevante Änderungen (Tageszeit/Wetter je Lobby, Streckenaustausch)
heben die Version auf 1.1.0 für beide Spiele, wie bei 1.0.1.

## Stand (08.10.2026, Pause nach Welle 1)

Zweig `v110` (nicht in `main`: `main` bleibt 1.0.1, bis 1.1.0 fertig ist).

Erledigt in Welle 1, volle Testsuite grün (bis auf die bekannten
Umgebungsfälle):
- Kameraansichten (`src/render3d/ansichten.py`), Tasten C / B, Pad Y / R3
- Cockpit-Assets für alle 15 Autos (`tools/blender/teile_cockpit.py`):
  Augpunkt, Lenkrad, Tacho- und Drehzahlnadel, Spiegelglas. Der Lader behält
  die Knotendrehung, Lenkrad und Nadeln drehen um ihre lokale Achse.
- Movie-Modus (`src/render3d/tv_regie.py`, `src/states/movie_modus.py`).
  Enter erst, wenn alle im Ziel oder DNF sind.
- Fahrhilfen (ABS, TC, Ideallinie) und Vibration (`src/entities/fahrhilfen.py`,
  `vibration.py`, `rennhilfen.py`). ABS kann den Bremsweg nicht verkürzen,
  weil die Physik kein Blockieren kennt; es stabilisiert beim Bremsen in
  Kurven.
- Tageszeit Tag/Abend/Nacht (`src/render3d/tageszeit.py`, `masten.py`)

**Fahrzeugmodelle:** Die GLBs mit Cockpit sind gitignoriert. Eine Kopie
liegt in `rohdaten/glb_v110/`. Neu bauen geht mit `tools\blender\bauen.bat
fahrzeuge` (ca. 5 min je Auto). Vor einem Build von 1.1.0 nach
`assets/vehicles/` kopieren.

**Welle 2, Spiegel (fertig):** `src/render3d/spiegel.py`,
`Rennszene._spiegel_rendern`; Grafikfeld `spiegel` (0 aus, 1 niedrig, 2 hoch;
Niedrig-Stufe aus, Mittel 1, Hoch/Ultra 2), Regler in den Grafikeinstellungen.
Nur in der Cockpitansicht und nur für Spiegel im Bild. Kosten auf `gp` im
Cockpit: etwa +1,2 ms Median auf Hoch (Niedrig +0,9) (Messung abwechselnd je Bild).

**Offen, Welle 2:**
1. ~~Funktionierende Spiegel.~~ Erledigt (`src/render3d/spiegel.py`).
2. ~~Wetter: Regen.~~ Erledigt (`src/render3d/wetter.py`, `regen.py`).
3. ~~Strecken online austauschen.~~ Erledigt (`src/net/strecken_client.py`, Server `TRACK_*`).

**Offen, sonst:**
- Augpunkt im Kompaktwagen: Der Dachhimmel nimmt oben fast 40 % des Bildes
  ein. Nach dem Probespielen entscheiden (höher setzen oder leicht nach unten
  neigen).
- Weite TV-Einstellungen: Die Autos wirken teils klein.
- Server: `tageszeit` steht in `SETTINGS_KEYS` nur in `server/server.py` des
  3D-Repos. Die Relais laufen mit dem Server aus dem 2D-Repo, dorthin
  übernehmen. Danach Version 1.1.0 für beide Spiele und neu deployen.
- 2D-Spiel: Fahrhilfen und Vibration ließen sich übertragen. Kameras, Movie
  und Tageszeit sind 3D-only.

## Wetter (Regen)

Trocken / Regen je Rennen, Wahl in allen Lobbys neben der Tageszeit
(`wetter`-Stepper, Profilfeld `wetter`, Lobbyschlüssel `wetter`, fehlt = Trocken;
`server/server.py`: `SETTINGS_KEYS` und `WETTER`). Der Server aus dem 2D-Repo
braucht dieselbe Änderung, dann Version 1.1.0 für beide Spiele.

- Zahlen und Namen: `src/render3d/wetter.py`; Regen und Gischt: `src/render3d/regen.py`.
- Physik: `Vehicle.wirk_config` (Haftung x0,8, Bremse x0,82) für Menschen und KI;
  die KI baut ihren Fahrplan damit und bremst früher. `data/vehicles/*.json`
  bleiben unberührt.
- Rauschen: `sfx_rennen.regenrauschen()` (gefiltertes Rauschen, nichts aufgenommen).
- Messen: `tools/ki_messung.py --wetter Regen`, `tools/rennen_probe.py --wetter Regen`,
  `tools/szene_foto.py --wetter Regen`.
- Nicht gemacht: Tropfen auf der Frontscheibe im Cockpit.
- Gefunden: `ctx.depth_mask = …` ist in moderngl wirkungslos (siehe `VEREINBARUNGEN.md`).

