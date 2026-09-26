# Vereinbarungen für `src/render3d/`

Diese Datei ist bindend. Wer sich nicht daran hält, baut Teile, die nicht
zusammenpassen.

## Koordinatensystem

Rechtshändig, **Meter**:

| Achse | Richtung |
|---|---|
| **+X** | vorne (Fahrtrichtung des Fahrzeugs) |
| **+Y** | links |
| **+Z** | oben |

Der Fahrzeugursprung liegt **mittig auf dem Boden** — genau so, wie
`trellis_import.py` die Modelle ablegt.

## Umrechnung aus der 2D-Welt

Das Spiel rechnet in Pixeln. Der Umrechnungsfaktor steht in
**`src/core/settings.py` als `M_PER_PX = 0.08`** — exakt 12,5 px = 1 m. Immer
von dort importieren, nie 0.08 hinschreiben: an mehreren Stellen im Spielcode
steht die Zahl bereits ausgeschrieben, und eine weitere Kopie macht eine spätere
Änderung unmöglich nachvollziehbar.

```python
from src.core.settings import M_PER_PX

welt3d = (pos2d[0] * M_PER_PX, pos2d[1] * M_PER_PX, 0.0)
gierwinkel = body.angle          # Radiant, 0 zeigt nach +X
```

pymunk rechnet Y nach oben, pygame zeichnet Y nach unten. In 3D gilt die
**pymunk**-Richtung; es wird also *nicht* gespiegelt.

## Matrizen

Alle Matrizen sind `numpy.ndarray` mit `shape=(4, 4)` und `dtype=float32`, in
**mathematischer Zeilenkonvention**:

```python
v_clip = P @ V @ M @ v_welt        # v als Spaltenvektor
```

GLSL erwartet Spaltenkonvention. Beim Hochladen deshalb **transponieren**:

```python
programm["mvp"].write(mvp.T.astype("f4").tobytes())
```

Die Kamera blickt in Blickraumkoordinaten entlang **−Z** (OpenGL-Konvention).

## Texturkoordinaten: einmal spiegeln, beim Hochladen

`trimesh` liefert UV in **OpenGL-Konvention: `v = 0` ist die Unterkante des
Bildes.** Ein Upload mit `Image.tobytes()` legt aber PIL-Zeile 0 — die
*Oberkante* — auf `v = 0`. Ohne Ausgleich steht jede Textur kopf.

**Ausgeglichen wird genau einmal, im Upload** (`mesh._textur_hochladen`), nicht
im Shader. Sonst muss jeder neue Shader daran denken, und der erste, der es
vergisst, erzeugt einen Fehler, den man für ein Modellproblem hält.

Nachgewiesen am 11.08.2026 durch zwei Renderings von `rookie.glb`: ohne
Spiegelung zerfällt die Lackierung in Flecken, mit Spiegelung ergibt sie ein
sauberes Fahrzeug.

Wer Texturkoordinaten außerhalb von OpenGL auswertet — etwa
`trellis_pipeline.paintmask.abdeckung`, das die Lackmaske auf die belegten
Texel begrenzt — rechnet in derselben Konvention:

```python
zeile = (1.0 - v) * (hoehe - 1)
```

## Einheiten und Namen

Code, Kommentare und Bezeichner auf Deutsch, passend zum übrigen Projekt.
Maßangaben tragen die Einheit im Namen: `abstand_m`, `hoehe_m`, `fov_grad`.

## Was hier nicht hingehört

Kein Zugriff auf `pygame`, keine Spiellogik, kein Laden von Dateien außerhalb
der übergebenen Pfade. `render3d` ist ein Darstellungsbaustein und kennt weder
Zustände noch Physik.

**Die Grenze zum Spiel ist `rennszene.Fahrzeugstand`** — Kennung, Schlüssel,
Position in Metern, Gierwinkel, zurückgelegter Weg, Lenkwinkel, entfärbt
ja/nein. Nur Zahlen. Wer die Stände füllt, weiß, was ein `PlayerVehicle` ist;
die Szene muss es nicht wissen, und deshalb sehen ein Ghost, ein
ferngesteuertes Fahrzeug und ein KI-Wagen für sie gleich aus.

Zwei Ausnahmen von der pygame-Regel, beide alt und beide bewusst:
`fenster.py` öffnet das Fenster, und `ansicht.py` liest den Speicher einer
pygame-Fläche, um sie hochzuladen. Beides ist der Übergang selbst.

## Modelle aus Blender: Knoten und Materialien

Die GLB-Dateien entstehen mit den Skripten unter `tools/blender/` und liegen
bereits im Achsensystem oben (`export_yup=False`); `mesh.laden` dreht nichts.

**Fahrzeuge** (`assets/vehicles/<key>.glb`) haben diese Knoten:

| Knoten | Ursprung | Bewegung |
|---|---|---|
| `karosserie` | Fahrzeugmitte am Boden | mit dem Fahrzeug, neigt sich (Nicken/Wanken) |
| `rad_vl` `rad_vr` `rad_hl` `rad_hr` | Nabenmitte | rollen um Y, vorne lenken um Z |
| `sattel_vl` … `sattel_hr` | Nabenmitte | lenken mit, rollen nicht |

Alles, was sich mit dem Rad dreht, muss um Y rotationssymmetrisch sein —
sonst eiert es. Die Materialnamen sind Vertrag mit dem Renderer:

* `lack` — Hauptlack, einfarbig per Faktor, **keine Textur**. Die Lackierung
  aus der Werkstatt ersetzt Farbe, Metallic und Rauheit (`lack.werte_3d`).
* `lack2` — Zweitfarbe/Livree; beim Finish „zweifarbig“ umgefärbt.
* `glas` — `alphaMode BLEND`, wird nach allem Deckenden gezeichnet.
* Übrige (`chrom`, `felge`, `gummi`, `licht_vorn` …) bleiben, wie sie sind.

**Fahrzeug-LOD1** (`assets/vehicles/<key>_lod1.glb`, neben `<key>.glb`):
dieselben Knoten mit denselben Ursprüngen und dieselben Materialnamen
(`lack`, `lack2`, `glas` …), nur mit weniger Dreiecken und ohne Kleinteile.
Es gibt keine eigene Teileliste; `<key>_teile.json` gilt für beide Stufen.
Fehlt die Datei, zeichnet man `<key>.glb`.

**Umgebung** (`assets/umgebung/<gruppe>/<name>.glb`, dazu `_lod1.glb`):
Ursprung mittig am Boden. Objekte, die zur Strecke ausgerichtet werden, zeigen
mit ihrer Vorderseite nach **+Y**. Laub-Materialien enden auf `_maske` und
werden ausgestanzt statt gemischt. Platzbedarf, Höhe und LOD-Abstand stehen in
`assets/umgebung/katalog.json`.
Dort steht auch der **Grundriss** jedes Modells, `grundriss_m: [x_min, x_max,
y_min, y_max]` im Modellraum (Skala 1); `umgebung_bauen.py` schreibt ihn mit,
`tools/katalog_grundrisse.py` ergänzt ihn für ältere Modelle.

**Nichts auf der Fahrbahn — auf jeder Strecke.** Eigene Strecken aus dem
Editor führen oft acht Meter neben sich selbst vorbei. Deshalb misst alles,
was um die Strecke herum entsteht, gegen die Fahrbahn der **ganzen**
Strecke (`track_mesh.Fahrbahnabstand`, exakt, alle Abschnitte), nie nur
gegen das nächste Stück und nie nur mit dem Mittelpunkt: die Platzierung
mit dem Grundriss (`platzierung.KANTE_FREI_M`, `ABSTAND_M`,
`KULISSE_FREI_M`), die Kiesbetten (`track_mesh.KIES_FREI_M`), das Gras,
das Gelände (flach bis `gelaende.KORRIDOR_MIN_M`, nahe Hügel höchstens
`NAH_HANG_MAX` steil). Wer etwas Neues neben die Strecke stellt, prüft es
ebenso; `tests/test_render3d_eigene_strecken.py` baut dafür echte
Kachelstrecken.

**Themen** (`data/themen/<name>.json`) sagen, was um eine Strecke steht; die
Strecke wählt ihr Thema über `background_texture`. Platziert wird zufällig,
aber mit einem Keim aus dem Streckennamen — jede Strecke sieht bei jedem
Rennen gleich aus.
