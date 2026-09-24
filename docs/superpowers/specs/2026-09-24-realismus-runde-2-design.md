# Realismus Runde 2

Stand 24.09.2026. Ziel: Fahrzeuge und Rennwelt deutlich realistischer, die
Autos bleiben dabei erkennbar **die Autos aus den Sprites** in `data/vehicles`.
Grafik im Spiel einstellbar, damit auch ein schwacher Rechner spielen kann.

## Entscheidungen (Interview)

| Frage | Antwort |
|---|---|
| Fahrzeuge | Teile-Bibliothek in Blender; Aussehen bleibt nah am Sprite |
| Seite/Front/Heck | leite ich aus der Fahrzeugklasse ab (keine Zusatzbilder) |
| Weitere Bereiche | Render-Effekte, Gelände & Horizont, Streckendetails |
| Bäume & Gebäude | bleiben diese Runde, wie sie sind |
| Grafik-Einstellungen | Stufen Niedrig/Mittel/Hoch/Ultra + Einzelregler, beim ersten Start automatisch |
| Mindest-PC | Einsteiger-Karte (GTX 1050 / RX 560): 1080p, Stufe Niedrig, 60 fps |
| Markenlogos der Sprites | in 3D durch **erfundene Embleme** ersetzen |
| GitHub-Link im Spiel | bleibt |
| Ablauf | vier Stränge parallel mit Agents |

## Gemeinsamer Vertrag

`src/render3d/grafik.py` ist die einzige Stelle, an der steht, was die Welt
kosten darf (`grafik.aktuell()`). Jedes neue Merkmal mit Kosten bekommt dort ein
Feld und je Stufe einen Wert. Budget auf dem Entwicklungsrechner (RTX 5060 Ti),
gemessen mit `tools/szene_foto.py` bzw. `tools/rennen_probe.py`:

* Niedrig: Welt ≤ 3 ms je Bild (Faustregel: GTX 1050 ≈ ein Achtel davon)
* Hoch: echtes Rennen, 8 Autos, 1080p ≤ 16 ms je Bild
* Ultra: darf mehr kosten

Bestehende Verträge gelten weiter: `src/render3d/VEREINBARUNGEN.md` (Achsen,
Knoten `karosserie`/`rad_*`/`sattel_*`, Materialien `lack`/`lack2`/`glas`,
`_maske`).

## Stränge und Besitz

Jeder Strang ändert nur die Dateien, die ihm gehören. Gemeinsame Dateien
(`rennszene.py`, `shader.py`, `platzierung.py`, `data/themen/*.json`,
`umgebung_bauen.py`) nur in eigenen, klar abgegrenzten Blöcken und immer
frisch gelesen vor jeder Änderung.

**F — Fahrzeuge (Teile-Bibliothek).** `tools/blender/teile*.py` (neu),
`fahrzeug_bauen.py`, `fahrzeuge*.json`, `assets/vehicles`. Karosserie als
lackierbare Hülle mit eingeschnittenen Fugen; Bibliothek wiederverwendbarer
Detailteile (Leuchteneinheiten mit Gehäuse/Reflektor/LED/Streuscheibe, Grills
und Lamellen, Spiegel, Türgriffe, Wischer, Flügel mit Profil und Endplatten,
Diffusor, Reifen mit Profil und Flanke, Felgen mit Radmuttern, Bremsscheibe
und Sattel, Innenraum). Folierung aus dem Sprite als Textur. Erfundene
Embleme statt Markenlogos. Erst Pilot an einem Auto je Klasse, dann alle 15.

**G — Grafik.** `shader.py` (Hauptbesitzer), `licht.py`, neue
`nachbearbeitung.py`, `rennszene.zeichnen`, `vorschau.py`, Profil,
Einstellungsseite, i18n. HDR-Bild in Zwischenpuffer, Umgebungsverdeckung,
Bloom, FXAA/MSAA, Farbkorrektur, Auflösungsskala, Reifenspuren und -rauch,
Grafikmenü mit Stufen und Einzelreglern, Stufe beim ersten Start nach GPU.

**W — Gelände & Horizont.** Neue `gelaende.py`, Boden in `rennszene.py`,
Höhe in `platzierung.py`, Gelände-/Bergfunktionen in `umgebung_bauen.py`.
Hügeliges Gelände je Strecke (flach im Streckenkorridor), Hang-/Höhenmischung
der Bodentexturen, Bergkette am Horizont je Thema, Gras nah an der Strecke.

**S — Streckendetails.** `track_mesh.py`, `begrenzung.py`,
`texturen_erzeugen.py`, neue Streckenobjekte in `umgebung_bauen.py`,
Randarten in `platzierung.py` und Themen. Asphalt mit Flicken, Rissen,
dunkler Ideallinie; 3D-Randsteine; Kiesbetten; Tribünen mit Publikum,
Boxengebäude, Streckenposten, Fangzäune, Hütchen.

## Fertig heißt

Fotos je Thema vorher/nachher, Zeitmessung je Stufe im Budget, Tests grün
(`.venv\Scripts\python.exe -m pytest tests -q`, bekannte Altlasten
ausgenommen), Release-Build läuft.
