# Portierung des Rennspiels auf 3D — Umsetzungsplan

Stand: 2026-08-11

## Entscheidungen, die diesem Plan zugrunde liegen

| Frage | Entscheidung |
|---|---|
| Renderer | **pygame-ce + ModernGL** — pygame behält Fenster, Eingabe, Audio, HUD, Menüs |
| Vorgehen | 2D-Code ins neue Repo **kopieren** und dort umbauen; das 2D-Spiel bleibt lauffähig |
| Repo-Inhalt | Quelltext, Konfiguration, Spieldaten in Textform. Keine großen Binärdateien |
| Meilenstein 1 | Ein Auto auf einer **echten Strecke**, Verfolgerkamera |
| Physik | bleibt **unverändert** bei pymunk in 2D. Die Meshes sind rein optisch |

## Ausgangslage

Kartiert am 11.08.2026 über vier parallele Analysen des 2D-Projekts
(`F:\Fahr-Rennspiel-2D`, 113 Python-Dateien, rund 33 000 Zeilen).

### Was übernommen wird, ohne es anzufassen

| Bereich | Warum unberührt |
|---|---|
| `src/physics/`, `src/entities/components/physics_body.py` | pymunk rechnet in 2D weiter. Ein Auto ist ein konvexes Polygon, Reifenkräfte greifen über ein Fahrradmodell an Vorder- und Hinterachse an |
| `src/ai/` | Die KI liest Wegpunkte und Fahrzeugkinematik. Kein einziger Zugriff auf Darstellung |
| `src/net/` | Zustandsabgleich über UDP mit binärem Format: Position, Winkel, Geschwindigkeit. Der Fahrzeugtyp ist ein Byte-Index. Optik ist rein lokal |
| `src/hud/`, `src/ui/` | Bleibt pygame. Rund 250 `blit`-, 220 `rect`- und 110 `line`-Aufrufe, die niemand neu schreiben will |
| `src/core/state_machine.py`, `src/states/` (Menüs) | Zustandswechsel, Menüs, Labore bleiben wie sie sind |
| `data/tracks/*.json` | Das Streckenformat trägt bereits alles, was 3D-Geometrie braucht |

### Was ersetzt wird

| Datei | Heute | Künftig |
|---|---|---|
| `src/entities/components/renderer.py` | Sprite drehen und blitten | 3D-Knoten: Karosserie plus vier Räder |
| `src/track/track_renderer.py` | Vorgebackene 2D-Fläche aus Polygonen | Streckenmesh mit Textur |
| `src/core/camera.py` | 2D-Versatz mit weicher Verfolgung | Perspektivische Kamera, Blick- und Projektionsmatrix |

### Der Maßstab stimmt bereits

`M_PER_PX = 0.08` in `src/entities/components/physics_body.py` — das sind exakt
**12,5 px = 1 m** und deckt sich mit der Sollmaßtabelle in
`trellis_pipeline/vehicle_specs.py`. Die Umrechnung Weltkoordinate → Meter ist
damit eine Multiplikation mit 0,08 und keine Kalibrierung.

Achsen im 2D-Spiel: pymunk rechnet Y nach oben, pygame zeichnet Y nach unten,
umgerechnet in `src/utils/math_utils.py`. Winkel 0 zeigt nach +X.

Im 3D-Raum gilt die Vereinbarung aus dem Import-Werkzeug: **+X vorne, +Y links,
+Z oben**, Ursprung mittig auf dem Boden. Die Abbildung ist damit

```
welt3d = (pos2d.x * 0.08, pos2d.y * 0.08, 0.0)
gierwinkel = body.angle
```

## Die entscheidende Bauentscheidung: wie HUD und 3D zusammenkommen

`src/core/display.py` zeichnet heute schon auf eine **virtuelle Fläche von
1920×1080**, die anschließend auf die Fenstergröße skaliert wird. Genau das ist
der Ansatzpunkt:

1. Das Fenster wird mit `pygame.OPENGL | pygame.DOUBLEBUF` geöffnet.
2. ModernGL rendert die 3D-Szene in den Bildpuffer.
3. HUD, Minimap und Menüs zeichnen **unverändert** auf die virtuelle Fläche.
4. Diese Fläche wird als Textur hochgeladen und als bildschirmfüllendes Rechteck
   mit Alpha darübergelegt.

Damit bleiben rund 33 000 Zeilen pygame-Code unangetastet. Der Preis ist ein
Texturupload von 1920×1080 je Bild; bei 60 Bildern je Sekunde ist das auf einer
5060 Ti nicht messbar, und er entfällt in Bildern, in denen sich am HUD nichts
ändert.

## Phasen

Jede Phase endet an einem Zustand, den man **sehen oder messen** kann. Keine
Phase beginnt, bevor die vorige das erreicht hat.

### A — Grundgerüst

| # | Aufgabe | Abnahme |
|---|---|---|
| A1 | 2D-Code nach `src/` kopieren, `requirements.txt` zusammenführen, Testlauf | Bestehende Tests des 2D-Projekts laufen im neuen Repo durch |
| A2 | Ablageordner für die großen Medien einrichten, `docs/assets.md` schreiben | Ein frischer Klon sagt, welche Medien fehlen und woher sie kommen |
| A3 | ModernGL-Kontext im pygame-Fenster, Testdreieck | Fenster zeigt das Dreieck, `pygame.event` funktioniert weiter |

### B — Kern des 3D-Renderers

| # | Aufgabe | Abnahme |
|---|---|---|
| B1 | `render3d/mesh.py`: GLB laden (trimesh), Vertex- und Indexpuffer, PBR-Texturen hochladen | `rookie.glb` erscheint als Standbild, Textur sichtbar |
| B2 | `render3d/camera.py`: Projektion, Blickmatrix, Verfolgerkamera mit weicher Nachführung | Kamera umkreist das Standmodell |
| B3 | `render3d/shader/`: PBR-Beleuchtung mit Base Color, Metallic-Roughness, einem Richtungslicht und einer Himmelsfarbe | Lack glänzt, Reifen matt, kein schwarzes Metall |
| B4 | `render3d/vehicle_node.py`: Karosserie plus vier Räder aus `<key>_teile.json`, Rollen aus der Geschwindigkeit, Lenken aus `steer_angle` | Räder drehen und lenken sichtbar richtig |

### C — Strecke in 3D

| # | Aufgabe | Abnahme |
|---|---|---|
| C1 | `render3d/track_mesh.py`: Fahrbahnband aus `centerline`, `outer_wall`, `inner_wall` bauen; UV entlang der Strecke laufen lassen | `oval.json` erscheint als befahrbares Band |
| C2 | Untergrund als große Ebene mit der vorhandenen Hintergrundtextur, Randsteine als eigenes Band | Strecke liegt in einer Landschaft statt im Leeren |
| C3 | Start-Ziel-Linie und Startaufstellung aus `start_positions` | Startfeld sitzt an derselben Stelle wie in 2D |

### D — Zusammenführung

| # | Aufgabe | Abnahme |
|---|---|---|
| D1 | `RaceState._render_world()` auf den 3D-Weg umstellen, 2D-Weg über einen Schalter behalten | Rennen läuft in 3D, umschaltbar zurück auf 2D |
| D2 | HUD-Fläche als Textur überlagern | Drehzahlmesser, Rundenanzeige, Minimap unverändert sichtbar |
| D3 | Alle acht Fahrzeuge, KI fährt | Ein vollständiges Rennen von der Startaufstellung bis zur Zielflagge |

### E — Feinschliff

| # | Aufgabe | Abnahme |
|---|---|---|
| E1 | Schattenwurf der Fahrzeuge (Shadow Map oder projizierter Fleck) | Autos stehen auf der Straße statt darüber zu schweben |
| E2 | Lackierung in 3D über die Lackmaske aus `trellis_import.py` | Ein umlackiertes Auto sieht aus wie im Fahrzeuglabor gewählt |
| E3 | Bildrate messen und einhalten | 60 Bilder je Sekunde mit acht Fahrzeugen |

## Was nicht im Plan steht

- **Physik in 3D.** Bleibt 2D. Federung, Nicken und Wanken lassen sich später
  rein optisch aus Beschleunigung und Querkraft ableiten, ohne die Physik
  anzufassen.
- **Streckeneditor in 3D.** Der Editor arbeitet auf Kacheln und Splines, nicht
  auf Optik. Er bleibt 2D.
- **Kollisionsformen aus Meshes.** Die vorhandenen Polygone bleiben.
- **Netzwerkformat.** Unverändert.

## Fehlende Assets zum Testen

### Zwingend, sonst kann ich nicht abnehmen

| Asset | Wofür | Woher |
|---|---|---|
| **2 weitere Fahrzeuge** — je ein langes (`limousine`) und ein breites (`supercar`) | Prüfen, dass Ausrichtung, Skalierung und Radschnitt nicht nur am `rookie` funktionieren. Radgrößen reichen von 0,64 bis 0,73 m, Längen von 4,24 bis 5,20 m | Du: 3/4-Render, dann `Fahrzeug_Render_HQ.json` und `trellis_import.py` |

### Nützlich, aber ich kann es vorläufig selbst erzeugen

| Asset | Wofür | Behelf |
|---|---|---|
| Asphalttextur, kachelbar, mit Rauheitskanal | Fahrbahn | Prozedural erzeugt: Rauschen plus Körnung, reicht für die Abnahme |
| Himmel oder Umgebungskarte | Ohne Umgebung wirken metallische Flächen schwarz — das ist keine Geschmacksfrage, sondern wie PBR rechnet | Farbverlauf vom Horizont zum Zenit, prozedural |
| Randsteintextur rot/weiß | Kerbs | Prozedural |

### Später, nicht für den Meilenstein

Bäume 8–20 m, Häuser 6–12 m, Leitplanken, Tribünen. Maßstab siehe
`docs/superpowers/specs/2026-08-11-trellis2-asset-pipeline-design.md`:
Fahrbahnbreite 250 px = 20 m, Editor-Zelle 400 px = 32 m.

## Arbeitsteilung mit Sub-Agents

Delegiert wird, was **klar begrenzt und selbst prüfbar** ist. Jeder Auftrag
bekommt eine Testdatei mit, gegen die er arbeitet; ohne grüne Tests gilt er als
nicht erledigt.

| Auftrag | Warum delegierbar |
|---|---|
| B1 GLB-Lader | Ein- und Ausgabe scharf umrissen: Datei rein, Puffer und Texturen raus |
| B2 Kameramathematik | Reine Matrizen, gegen bekannte Werte prüfbar |
| C1 Streckenmesh | JSON rein, Dreiecksnetz raus. Prüfbar über Flächeninhalt, Randlage, Geschlossenheit |

Nicht delegiert werden Zusammenführung und Umbau bestehender Zustände
(Phase D) — dort hängt zu viel an Kenntnis des Umfelds, und ein Fehler bricht
ein laufendes Spiel.

## Reihenfolge und Abhängigkeiten

```
A1 ── A2
 │
 └── A3 ── B1 ── B4 ── D1 ── D2 ── D3 ── E1 ── E2 ── E3
      │     │           │
      │     └── B3 ─────┘
      └── B2       C1 ── C2 ── C3
```

B1, B2 und C1 hängen nur an A3 und können parallel laufen.
