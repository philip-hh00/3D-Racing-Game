# Blender-Assets: Fahrzeuge und Streckenumgebung

Stand 23.09.2026. Ersetzt die TRELLIS-Fahrzeuge und den Radschnitt.

## Entscheidungen (mit dem Nutzer abgestimmt)

* Blender 4.5 LTS als portable Installation unter `F:\Blender`, headless
  aufgerufen (`blender -b -P skript.py -- argumente`).
* **Fahrzeuge prozedural** in Blender, **Umgebung gemischt**: eigene
  Blender-Modelle plus CC0-Material (Poly Haven, ambientCG), in Blender
  aufbereitet. Lizenzen in `assets/LIZENZEN.md`.
* **15 eigene Fahrzeugmodelle** — je Eintrag in `data/vehicles/*.json`.
* TRELLIS-Pipeline, Radschnitt, Lackmasken und alte GLBs werden entfernt.
* Themen: City, Desert, Forest, Mountain, Plains.
* Leistung: Ziel >= 60 fps bei 1080p, instanziert, zwei LOD-Stufen.
* Platzierung zufällig, aber **fest je Strecke** (Seed aus dem Streckennamen).
* **Ladebildschirm mit Balken** vor dem Countdown.

## Fahrzeuge

Generator `tools/blender/fahrzeug_bauen.py`, Parameter je Fahrzeug in
`tools/blender/fahrzeuge.json`. Maße aus der Fahrzeug-JSON: Länge =
`height_px * M_PER_PX`, Breite = `width_px * M_PER_PX`, Radstand und
Raddurchmesser aus `physics`.

Ausgabe je Fahrzeug `assets/vehicles/<key>.glb` mit den Knoten
`karosserie`, `rad_vl`, `rad_vr`, `rad_hl`, `rad_hr`. Jedes Rad hat seinen
Ursprung in der Nabenmitte und sitzt bereits an seinem Platz. Dazu
`<key>_teile.json` im bisherigen Format. Achsen nach
`src/render3d/VEREINBARUNGEN.md`: +X vorne, +Y links, +Z oben, Ursprung mittig
am Boden.

Materialien (Namen sind Vertrag mit dem Renderer):

| Material | Rolle |
|---|---|
| `lack` | wird mit der Lackierung umgefärbt |
| `lack2` | Zweitfarbe (Dach/Streifen), nur bei Finish `zweifarbig` umgefärbt |
| `glas` | dunkel getönt, glatt, leicht durchscheinend |
| `chrom`, `felge` | Metall |
| `gummi` | Reifen |
| `kunststoff`, `innenraum` | matt schwarz/grau |
| `licht_vorn`, `licht_hinten` | selbstleuchtend |

## Umgebung

Generator `tools/blender/umgebung_bauen.py` erzeugt
`assets/umgebung/<thema>/<objekt>.glb` (mit `_lod1`), dazu
Bodentexturen in `assets/texturen/`. Beschreibung je Thema in
`data/themen/<thema>.json`: welche Objekte, wie häufig, in welchem
Abstandsband zur Strecke, Himmel- und Nebelfarben, Boden- und Fahrbahntextur.

## Renderer

* `mesh.py` lädt mehrere Materialien je Teil (ein VAO je Material-Primitive).
* `Fahrzeugstand.lack` trägt die Lackkennung; die Szene rechnet sie in Farbe,
  Metallic und Rauheit um (`werk` = Farbe aus dem Modell).
* `deko.py`: Platzierung (rein numpy, testbar) und instanziertes Zeichnen.
* Himmel und Nebel je Thema, Untergrund bis unter die Kulisse.
* Gerichteter Schattenwurf per Shadow Map.
* Ladebildschirm in `RaceState`, bevor der Countdown läuft.

## Abnahme

* Rennen auf jeder Strecke startet, Screenshot je Thema.
* >= 60 fps bei 1920x1080 mit acht Fahrzeugen.
* Tests: Teile-JSON je Fahrzeug, Platzierung deterministisch und nicht auf der
  Fahrbahn, Mehrmaterial-Laden, Lackumrechnung. Bestehende Suite grün bis auf
  die bekannten Altfehler.
