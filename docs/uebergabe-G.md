# Übergabe G: Fahrzeuge in Perfektion — Stand 30.09.2026

Ersetzt `docs/uebergabe-F.md` als Einstieg. Für eine **neue Sitzung** mit
leerem Kontext und der **Blender-MCP-Erweiterung** geschrieben.

## 1. Worum es geht

3D-Rennspiel (pygame-ce + moderngl, Physik 2D), deutscher Code, Version
**1.0.0** kurz vor dem Release. Der Besitzer will die **Fahrzeuge perfekt**,
vor allem die **Rückleuchten** — der Spieler sieht sein Auto fast immer von
hinten schräg oben (Verfolgerkamera). Die Form der 15 Autos bleibt nah an
den Sprites `data/vehicles/*.png` (Draufsicht, vom Besitzer gemalt).

Entscheidungen des Besitzers (gelten weiter):

| Frage | Antwort |
|---|---|
| Vorrang | Form wie Sprite, Details (Leuchten, Räder, Innen) aus Assets/Modellierung |
| Fremde Assets | CC0 und CC-BY erlaubt (Urheber in `assets/LIZENZEN.md`). BlenderKit nicht: Gratis-Assets dürfen nur hinein, wenn sie nicht leicht extrahierbar sind, unsere GLBs liegen offen |
| Budget | nahe Autos bis ~200k Dreiecke, ~3×2048² Texturen; ferne über LOD1 |
| Markenlogos | nie; erfundene Embleme, erfundene Marken (Reifen TORVANE, Sättel KESTRA) |
| Personenname | nirgends im Spiel |
| Sub-Agents | Opus (Sonnet hatte Wochenlimit bis 01.10.) |

## 2. Offen — damit weitermachen

### 2.1 Rookie-Rückleuchten (höchste Priorität)

Die drei Kompaktwagen `rookie`, `rookie_2`, `rookie_3`. Die übrigen Autos
findet der Besitzer „schon ziemlich gut".

- **Gefällt:** die organischere, natürliche Form (zweigeteilt Seitenwand +
  Heckklappe, Lichtleiter, Rauchglas) — das war sein Hauptärger.
- **Stört noch** (markiert in [`uebergabe-G/rookie_markierung.webp`](uebergabe-G/rookie_markierung.webp),
  gelbe Kreise, Spalte „schräg hinten"):
  1. Der **obere äußere Teil der Seitenwandleuchte** zieht sich fast bis in
     die **C-Säule** / an die Seitenscheibe. Die Leuchte muss unterhalb der
     Schulter-/Gürtellinie enden.
  2. Bei `rookie_2` steckt die **rote Flügel-Endplatte in der linken
     Leuchte**. Alle Autos mit Heckflügel prüfen (rookie_2, drifter 1–3,
     supercar 1–3): nichts darf in eine Leuchte ragen.
  3. Leuchten dürfen nicht in die **Heckscheibe** reichen (im letzten
     Zwischenstand behoben, weiter prüfen).
  4. Lieber ruhige Flächen (glattes Rauchglas, ein klar lesbarer
     Lichtleiter) als Lochblech-Punktraster und viele Einzelteile.
- Letzter Zwischenstand: [`uebergabe-G/rookie_zwischenstand.png`](uebergabe-G/rookie_zwischenstand.png).
- Ein Agent arbeitete beim Schreiben noch daran und sollte seinen Stand
  committen. **Zuerst `git status` / `git log -5` prüfen**: uncommittete
  Änderungen an `tools/blender/teile_leuchte.py` und
  `tools/blender/fahrzeuge/rookie*.json` sind sein halber Stand.
- Entwurfsskript des Agents: `%TEMP%\claude\F--3D-Racing-Game\8dcf60ec-…\scratchpad\agent_LX\rookies.py`
  (Scratchpad, geht evtl. verloren — maßgeblich sind die JSONs).

### 2.2 Weitere offene Punkte Fahrzeuge

- **Frontscheinwerfer:** Typ `scheinwerfer` in `teile_leuchte.py`
  (Projektor, Facettenschale, Tagfahrlicht-Ring) ist gebaut, aber
  **ungetestet und in keiner JSON eingeschaltet**.
- `supercar` und `electric_3` laufen bewusst mit `"stil": "klassisch"`
  (alte Leuchteneinheit, `teile_leuchte_klassisch.py`), weil die neue dort
  nicht eindeutig besser war.
- **Glas der Leuchten:** Der Shader mischt Glas per Alpha, dadurch wird die
  Spiegelung mit abgeschwächt. Echte Fresnel-Spiegelung auf dem Deckglas
  bräuchte vormultipliziertes Alpha im Shader (`src/render3d/shader.py`).
- **Entscheidung Besitzer offen:** schwarze Felgen bei `supercar` und
  `supercar_3` verschlucken die neuen Keramikbremsen — Anthrazit statt
  Schwarz? (bisher nicht beantwortet)
- Kleinere Schönheitsfehler: Glaskanten-Splitter am Übergang
  Oberseite/Heck der Seitenwandleuchte; weiße Drifter-Reifenschrift wirkt
  grau; Felgen-Ventil teils heller Punkt; Welle an der Gürtellinie rookie.

### 2.3 Abschluss vor dem Release

1. `tools\blender\bauen.bat fahrzeuge` — baut alle 15 Autos samt LOD1 nach
   `assets/vehicles` (vorher `tools/fahrzeug_texturen.py`, steht jetzt mit
   im Skript und in `.github/workflows/release.yml`). Dauert wegen des
   Backens lange (Leuchten per Cycles/OptiX, Räder ~50 s je Auto).
2. Bildzeit messen: `.venv\Scripts\python.exe tools\rennen_probe.py gp --stufe hoch`
   (Ziel ≤ 16 ms, vorher ~11 ms) und `--stufe niedrig`.
3. Tests: `.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --deselect tests/test_affentest.py`
   (~13 min). Bekannte Altlasten: `test_einzelinstanz`,
   `test_release_pipeline::test_die_rueckfrage_laeuft_wirklich_durch`,
   Affentest (WinError 1314, Symlinks).
4. Installer: `set RACE_KEIN_PAUSE=1 && Release\skripte\build_windows.bat`
   → `Release\ausgabe\3D-Racing-Game_Setup_v1.0.0_*.exe`, danach die exe
   25 s starten lassen.
5. `git push` (main, github.com/philip-hh00/3D-Racing-Game).
6. **Besitzer:** auf dem Online-Server `server/live_config.json`
   (required_version 1.0.0) und `server/server.py` (Datenstand-Prüfung
   DATA_MISMATCH) ausrollen.

## 3. Wie die Fahrzeuge entstehen

Alles prozedural, **Blender 4.5.14 LTS** portabel unter
`F:\Blender\blender-4.5.14-windows-x64\blender.exe`, headless:

```
blender.exe -b -P tools/blender/fahrzeug_bauen.py -- --fahrzeug <key|alle> --ausgabe <ordner> [--vorschau <o>] [--draufsicht <o>] [--lod1|--ohne-lod1]
```

| Datei | Inhalt |
|---|---|
| `tools/blender/fahrzeug_bauen.py` | Generator: Haut aus Zonen, Kabine, Radläufe, `spur_anpassen` (Reifenflanke 2 cm hinter dem Kotflügel), Materialien, Export, LOD1 |
| `tools/blender/fahrzeuge.json` | nur Vorlagen (`_vorlagen`) |
| `tools/blender/fahrzeuge/<key>.json` | Parameter je Auto (Zonen, Leuchten, `teile`-Block) |
| `tools/blender/teile.py` | Teile-Bibliothek (Leuchtenzonen alt, Gitter, Spiegel, Flügel, Diffusor …), Kopf = Parameter-Doku |
| `tools/blender/teile_leuchte.py` | neue Leuchteneinheiten (Deckglas, Lichtleiter, Kammern, gebackene Optiken) |
| `tools/blender/teile_leuchte_klassisch.py` | alte Einheit (`"stil": "klassisch"`) |
| `tools/blender/backen.py` | Cycles-Backwerkzeug (Normal/Emission/AO/Farbe, UV-Packer, OptiX) |
| `tools/blender/teile_rad.py`, `backen_rad.py` | Räder: Reifen, Felgen je Familie, Bremsen, Sättel, gebackene Atlanten |
| `tools/blender/teile_innen.py` | Innenraum (Sitze, Lenkrad, Armaturen, Türverkleidung) |
| `tools/blender/teile_oberflaeche.py` | Scheibenrand (Keramik/Punktraster), Materialtexturen, 3. Bremsleuchte, Kennzeichenleuchte |
| `tools/fahrzeug_texturen.py` | lädt ambientCG-CC0 (Carbon, Leder, Kunststoff) und erzeugt `assets/texturen/fahrzeug/` |
| `tools/blender/vergleich.py` | IoU Draufsicht gegen Sprite — darf nie sinken |

**Prüfen im Spiel:**
```
.venv\Scripts\python.exe tools\szene_foto.py city --modelle <ordner> --fahrzeuge <key> --abstand 6 --kamerahoehe 2.2 --drehen 20 --ziel <png>
```
(`--drehen 0` genau von hinten, `-140` vorn, `--abstand 3` nah). Bilder immer
ansehen und streng urteilen.

**Verträge:** `src/render3d/VEREINBARUNGEN.md` — Knoten `karosserie`,
`rad_vl/vr/hl/hr` (Ursprung Nabe), `sattel_*`; Materialien `lack`/`lack2`
(Werkstatt färbt um), `glas` (BLEND), `bremslicht` (leuchtet mit dem Pedal),
`licht_hinten`, `blinker`; `<key>_lod1.glb`; `<key>_teile.json`.

**Engine** (`src/render3d/`): GLB-Leser `mesh.py` (normalTexture,
emissiveTexture, occlusionTexture, geteilte Bilder nur einmal hochgeladen),
Shader `shader.py` (PBR, Klarlack, Lack-Flakes Block „Strang L",
Geländeschatten, Asphalt), `rennszene.py` (LOD1 ab `grafik.fahrzeug_lod_m`,
Bremslicht), Grafikstufen `grafik.py`.

## 4. Blender MCP in der neuen Sitzung

Die Erweiterung war in der alten Sitzung noch nicht geladen (keine
Blender-Werkzeuge sichtbar). In der neuen Sitzung:

- Mit `ToolSearch` nach „blender" suchen; wenn nichts kommt: MCP-Server mit
  `claude mcp list` prüfen (im Terminal) und Blender mit gestartetem
  MCP-Add-on offen haben.
- Sinnvoll für: Leuchten live in der offenen Szene ansehen und anpassen,
  Kameraansichten rendern, Durchdringungen (Flügel/Leuchte, Leuchte/C-Säule)
  direkt prüfen.
- **Die Quelle der Wahrheit bleibt der Generator.** Was live gefunden wird,
  gehört als Parameter/Code in `fahrzeuge/<key>.json` bzw. `teile_leuchte.py`,
  sonst ist es beim nächsten Bau weg. Live-Szene zum Anschauen: ein Auto mit
  `fahrzeug_bauen.py` bauen und die GLB in Blender importieren (Achsen:
  +X vorn, +Y links, +Z oben, Meter).

## 5. Was in dieser Runde sonst fertig wurde (Kurzüberblick)

Seit Übergabe F, alles committet und (bis `c051d57`) gepusht:

- Ein Ladebildschirm statt zwei, ohne Dateinamen (`src/states/ladeanzeige.py`).
- Umgebung auf eigenen Editor-Strecken nie auf der Fahrbahn (Grundrisse im
  Katalog, `track_mesh.Fahrbahnabstand`, Tests `test_render3d_eigene_strecken.py`).
- Geländeschatten (Sonnensichtkarte), Tribünen/Boxen/Zuschauer entfernt,
  Start/Ziel-Portal mit 5-Lampen-Ampel, neuer Countdown, Icon, Version 1.0.0,
  Installer-Bilder, README, itch.io-Text.
- Grafikmenü mit „Erweitert …"-Seite, HUD halbdurchsichtig, UI in echter
  Auflösung (`src/ui/leinwand.py`, `src/ui/zeichnen.py` — neue Flächen
  immer über `leinwand.flaeche`, Zeichnen über `zeichnen.*`).
- Manipulationsschutz: signierte Prüfsummen der Fahrwerte
  (`src/core/integritaet.py`, `tools/pruefsummen.py`), signierte Ghosts,
  Server prüft Datenstand.
- Räder unter der Karosserie, Laub ohne Nachladen (Deckungs-Mipmaps,
  LOD-Überblendung).
- Fahrzeuge Runde „Perfektion": Normal-/Leucht-/AO-Texturen, gebackene
  Räder, Lack mit Flakes, Keramikrand, echter Innenraum, neue Rückleuchten.

**Gepusht bis zu diesem Übergabe-Commit.** Nicht gepusht ist nur, was der
Leuchten-Agent danach noch committet (siehe 2.1).

## 6. Arbeitsweise, die sich bewährt hat

- Antworten an den Besitzer knapp auf Deutsch; Code/Commits normal, deutsch,
  Commit-Nachricht endet mit `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Parallele Agents: klare Dateibesitzer, gemeinsame Dateien nur in
  markierten Blöcken, nie `git add -A`/`reset`/`checkout`/`stash`.
- Bash-Heredocs über ~8 KB brechen ab → Skripte mit Write in den Scratchpad.
- Backslashes in Python-Heredocs für `.bat`-Dateien vermeiden (`\f` wurde
  einmal zum Seitenvorschub).
