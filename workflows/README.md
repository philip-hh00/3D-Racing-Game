# Workflow-Vorlagen für ComfyUI

Beide Dateien per **Drag & Drop** auf die ComfyUI-Fläche ziehen.

| Datei | Kaskade | Wofür |
|---|---|---|
| `Fahrzeug_TopDown_HQ.json` | 1536 | Standardfall |
| `Fahrzeug_TopDown_Sicher.json` | 1024 | Rückfall bei `out of memory` |

## Was pro Fahrzeug zu ändern ist

Genau zwei Felder:

1. **`Trellis2LoadImageWithTransparency`** → das Sprite wählen, z. B. `Supercar_2.png`.
   `tools\start_gui.bat` kopiert alle 15 Sprites bei jedem Start nach
   `tools\ComfyUI\input\`, sie stehen also in der Auswahlliste.
2. **`PrimitiveString`** (#219) → den Fahrzeugschlüssel eintragen, z. B. `supercar_2`.
   Er bestimmt die Dateinamen der Ausgabe.

Ergebnis landet in `tools\ComfyUI\output\`:

```
<key>_WhiteMesh_00001_.glb    nur Geometrie
<key>_Textured_00001_.glb     mit PBR-Textur  <- das wird weiterverarbeitet
```

Danach:

```
python trellis_import.py tools\ComfyUI\output\<key>_Textured_00001_.glb --fahrzeug <key>
```

## Wie die Vorlagen entstanden sind

Nicht von Hand, sondern über `tools\make_workflows.py` aus dem Beispiel
`MeshWithTexturing.json` des Nodes. Die Widget-Werte eines Workflows sind eine
Liste ohne Feldnamen — welcher Wert welche Einstellung ist, ergibt sich erst aus
der Reihenfolge in `INPUT_TYPES`. Ein Node-Update, das eine Einstellung
einschiebt, verschiebt alles dahinter. Das Skript fragt die Reihenfolge beim
laufenden Server ab und bricht ab, wenn ein Feld nicht mehr existiert.

Nach einem `git pull` im Node also einmal:

```
python tools\make_workflows.py
```

## Was gegenüber dem Beispiel geändert wurde

| Einstellung | Beispiel | Vorlage | Warum |
|---|---|---|---|
| `Trellis2LoadModel.backend` | `flash_attn` | `sdpa` | flash_attn ist nicht installiert |
| `sparse_structure_resolution` | 32 | **64** | siehe unten |
| `Trellis2ShapeGenerator.resolution` | 512 | 1024 | |
| `ShapeCascade` von/bis | 0 → 1024 | 512 → 1536 | |
| alle `steps` | 12 | 25 | sauberere Kanten |
| `MeshTexturing.resolution` | 1024 | 1536 | |
| `MeshTexturing.max_views` | 4 | 6 | |
| Simplify-Ziel | 500 000 | 1 000 000 | |

**Zur Voxelauflösung:** `sparse_structure_resolution` ist das grobe Gitter über
die längste Kante. Bei 32 und 4,32 m Fahrzeuglänge sind das 13,5 cm je Voxel —
ein Reifen von 0,65 m ist damit fünf Voxel breit und kann nicht rund werden. 64
halbiert die Kantenlänge auf 6,8 cm.

**`conv_backend` bleibt `flex_gemm`.** Im Testlauf am 11.08.2026 kam damit auf
der RTX 5060 Ti ein geschlossenes Mesh und keine Punktwolke. Der bekannte
Blackwell-Fallstrick (microsoft/TRELLIS.2 Issue #99) tritt hier nicht auf — der
Node hat den `trellis2-blackwell-fix` eingearbeitet. `spconv` wird nicht
gebraucht, und dafür gäbe es auch kein sm_120-Wheel.

## Was die Vorlagen nicht lösen können

Die Sprites sind reine Top-Down-Ansichten. TRELLIS sieht kein einziges Pixel der
Flanke — Schweller, Radhausformen, Türfugen und Reifenflanken werden erfunden,
und die Textur der Seiten wird per Inpainting gefüllt. Keine
Auflösungseinstellung erzeugt Information, die im Eingabebild nicht vorhanden
ist. Wenn das nicht reicht, ist der nächste Schritt eine Multi-View-Vorstufe
(`MeshWithTexturing_MultiView.json`) mit vorher erzeugten Seitenansichten.
