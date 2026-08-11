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
