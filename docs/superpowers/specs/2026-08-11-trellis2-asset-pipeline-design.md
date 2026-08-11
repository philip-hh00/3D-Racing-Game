# TRELLIS 2 Asset-Pipeline für 3D-Racing-Game

Stand: 2026-08-11

## Ziel

Aus den vorhandenen 2D-Fahrzeugsprites 3D-Modelle für die 15 Fahrzeug-
konfigurationen erzeugen. TRELLIS 2 läuft lokal, ein Import-Werkzeug macht aus
dem generierten GLB ohne Handarbeit ein spielfertiges Asset.

Quell-Projekt: `F:\Fahr-Rennspiel-2D` (philip-hh00/2D-Racing-Game, Branch `main`)
Ziel-Projekt: `F:\3D-Racing-Game` (philip-hh00/3D-Racing-Game)

## Zielsystem

| Komponente | Ist |
|---|---|
| GPU | RTX 5060 Ti, 16 GB, Blackwell **sm_120** |
| Treiber | 610.88 |
| Python | 3.11.9 unter `py -3.11` |
| Git / LFS | 2.54.0 / 3.7.1 |

## Harte Randbedingung

sm_120 verlangt **PyTorch ≥ 2.7.0 mit cu128**. Ältere CUDA-Builds brechen mit
`CUDA capability sm_120 is not compatible with the current PyTorch installation`
ab.

Daraus folgt:

- Die Anleitung `ericcraft-mh/TRELLIS-install-windows` ist unbrauchbar — sie
  pinnt `torch==2.5.1+cu124`.
- TRELLIS 1 nativ zu bauen hieße kaolin, nvdiffrast, diffoctreerast,
  diff-gaussian-rasterization und spconv gegen sm_120 selbst zu kompilieren.
  Wird nicht gemacht.
- Weg ist **TRELLIS 2 über `visualbruno/ComfyUI-Trellis2`**: dort liegen
  vorkompilierte Windows-Wheels für Torch 2.7.0 + cu128 bei. Kein Visual Studio,
  kein CUDA-Toolkit nötig. TRELLIS 2 liefert außerdem echte PBR-Kanäle
  (Base Color, Roughness, Metallic, Opacity) statt eingebackener Beleuchtung.

## Bekanntes Risiko: Input-Qualität

Die Quellsprites sind reine Top-Down-Orthoansichten, flach cel-shaded. TRELLIS
sieht darin kein Höhenprofil und muss Dachhöhe, Haubenneigung, Schweller und
Radbögen halluzinieren. Entscheidung: erst ein Testlauf mit dem
unveränderten Sprite (P4), danach wird über eine Multi-View-Vorstufe entschieden.

## Verzeichnislayout

```
F:\3D-Racing-Game\
  tools\ComfyUI\              ComfyUI + venv + custom_nodes + models   (gitignored)
  tools\install_trellis2.bat  reproduzierbarer Installer, idempotent
  tools\check_env.bat         Sperren-Check einzeln nachfahrbar
  rohdaten\                   TRELLIS-GLB roh                          (gitignored)
  assets\vehicles\            fertige GLB + Lackmaske-PNG              (committet)
  trellis_import.py           Import-Werkzeug
  trellis_import.json         pro Modell: {"flip": true|false}
```

## Phasen

Jede Phase endet an einer harten Sperre. Vor bestandener Sperre wird nicht
weitergebaut.

| # | Inhalt | Sperre |
|---|---|---|
| P0 | Ordner, `.gitignore`, `git init` + remote, Spec | `git remote -v` zeigt Repo |
| P1 | ComfyUI clone, venv 3.11, torch 2.7.0+cu128, requirements | `2.7.0+cu128 True (12, 0)` |
| P2 | ComfyUI-Trellis2 + 5 Wheels | alle 5 Module importierbar |
| P3 | HF-Login (User) + DINOv3, `main.py --lowvram` | Web-UI + Trellis2-Nodes sichtbar |
| P4 | Testlauf `Rookie.png` → GLB | Ergebnis begutachtet |
| P5 | `trellis_import.py` | Ist-Maße = Soll ±5 %, Maske plausibel |

`natten` wird **nicht** installiert — nur für Pixal3D-T nötig und müsste
kompiliert werden.

## Maßstab

Das 2D-Spiel steht auf exakt **12,5 px = 1 m** (nachgerechnet über alle 15
Fahrzeug-JSONs via `wheelbase_ratio × height_px ÷ wheelbase`, Ergebnis
durchgehend 12,49–12,51). Das 3D-Werkzeug rechnet direkt in Metern, ohne
Pixelumweg.

Sollmaße:

| Konfiguration | L (m) | B (m) | Rad (m) | Radstand (m) |
|---------------|-------|-------|---------|--------------|
| rookie        | 4,32  | 2,08  | 0,65    | 2,624 |
| rookie_2      | 4,24  | 2,08  | 0,64    | 2,674 |
| rookie_3      | 4,40  | 2,16  | 0,65    | 2,674 |
| supercar      | 4,96  | 2,32  | 0,64    | 2,674 |
| supercar_2    | 4,80  | 2,32  | 0,64    | 2,624 |
| supercar_3    | 4,88  | 2,24  | 0,64    | 2,574 |
| drifter       | 4,64  | 2,16  | 0,65    | 3,074 |
| drifter_2     | 4,64  | 2,16  | 0,65    | 2,924 |
| drifter_3     | 4,64  | 2,16  | 0,65    | 3,074 |
| limousine     | 5,20  | 2,16  | 0,69    | 3,274 |
| limousine_2   | 5,12  | 2,16  | 0,68    | 3,174 |
| limousine_3   | 5,20  | 2,16  | 0,69    | 3,274 |
| electric      | 4,96  | 2,16  | 0,73    | 2,942 |
| electric_2    | 5,04  | 2,16  | 0,73    | 2,992 |
| electric_3    | 4,96  | 2,16  | 0,73    | 2,892 |

Für spätere Deko-Assets: Fahrbahnbreite 250 px = 20 m, Editor-Zelle
400 px = 32 m. Bäume 8–20 m, Häuser 6–12 m.

## trellis_import.py

Aufruf:

```
python trellis_import.py rohdaten/rookie.glb --fahrzeug rookie
python trellis_import.py rohdaten/rad.glb --fahrzeug rookie --typ rad
```

Module, je eine Aufgabe:

- **orient** — orientierte Bounding-Box; längste Achse → +X (Fahrtrichtung
  vorne), kürzeste → +Z (oben). Oben/unten über den Schwerpunkt (ein Auto ist
  unten schwerer). Vorne/hinten ist nicht sicher automatisierbar und kommt aus
  `trellis_import.json` als `"flip": true|false` je Modell.
- **scale** — auf die Ziellänge aus der Tabelle. Bei `--typ rad` stattdessen auf
  den Raddurchmesser.
- **origin** — x/y auf Bbox-Mitte, z auf Bbox-Minimum, also Bodenkontakt mittig.
  Ohne das schweben Modelle mit Mittelpunkt-Ursprung im Renderer. Bei
  `--typ rad` ist der Ursprung die Nabenmitte.
- **report** — Dreiecksanzahl, Texturgröße, vorhandene PBR-Kanäle, Ist gegen
  Soll, Warnung bei Abweichung > 5 %.
- **paintmask** — Portierung von `F:\Fahr-Rennspiel-2D\src\core\lack.py`
  (dominante Farbe + Sättigungsschwelle + Helligkeitsfenster). Kennwerte aus dem
  `paint`-Block der jeweiligen `data\vehicles\<key>.json`. Ausgabe als PNG neben
  dem GLB. Entfällt bei `--typ rad`.

Abhängigkeiten: trimesh, numpy, pillow.

## Bewusst nicht im Umfang

- **Rad-Rigging.** TRELLIS liefert ein verschmolzenes Mesh; Vorderräder lenken
  nicht, Räder drehen nicht. Lösung später: Karosserie und Rad getrennt
  generieren, die vier Radpositionen aus Radstand, Breite und Raddurchmesser
  rechnen. Das Werkzeug bereitet das über `--typ rad` vor.
- **Glas** kommt undurchsichtig. Über den Opacity-Kanal später lösbar.
- **LOD** entsteht nicht automatisch. Bei maximal 8 Autos unkritisch.
- **Kollisionsformen** werden nicht gebraucht — die Physik bleibt bei den
  bestehenden 2D-Polygonen, die Meshes sind rein optisch.

## Bekannte Fallstricke

- **Punktwolke statt Mesh am Ende des Graphen**: bekanntes Blackwell-Verhalten
  (microsoft/TRELLIS.2 Issue #99, dort mit einer 5060-Ti-Klasse-Karte). Lösung
  laut Auftrag: Sparse-Backend von `flex_gemm` auf `spconv` umstellen.
  **Tritt hier nicht auf.** Der Testlauf am 11.08.2026 lieferte mit `flex_gemm`
  ein geschlossenes Mesh mit 459 268 Dreiecken. Der Node hat den
  `trellis2-blackwell-fix` eingearbeitet. `spconv` ist nicht installiert und
  wird nicht gebraucht — für sm_120 gäbe es dafür auch kein Wheel.
- **`backend: flash_attn` ist die Voreinstellung aller Beispiel-Workflows**,
  flash_attn ist aber nicht installiert und wäre unter Windows für Torch 2.7 ein
  Kompilat. Auf `sdpa` stellen. Die Vorlagen unter `workflows/` tun das bereits.
- **`torchaudio` steht ungepinnt in `ComfyUI/requirements.txt`.** Wird es von
  PyPI geholt, zieht es sein eigenes Torch mit und überschreibt cu128. Vorher
  explizit `torchaudio==2.7.0` aus dem cu128-Index installieren.
- **`rembg` bringt keinen Backend mit** (`No onnxruntime backend found`).
  `rembg[cpu]` genügt — die Sprites sind bereits freigestellt.
- **`scipy` fehlt leicht im Projekt-venv.** trimesh braucht es für die
  orientierte Bounding-Box, ohne es scheitert `ausrichten` mit
  `Points must be coplanar`.
- Gradio/ASGI-Fehler: `pydantic==2.10.6` und `open3d==0.19.0` sind die bekannten
  funktionierenden Pins.
- Ninja-Build-Fehler: `setuptools==75.8.2`.
- Python muss der offizielle Installer sein, nicht das Embeddable Package —
  letzterem fehlt `Python.h`.
