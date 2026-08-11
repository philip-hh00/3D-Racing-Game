# Workflow-Vorlagen für ComfyUI

Beide Dateien per **Drag & Drop** auf die ComfyUI-Fläche ziehen.

| Vorlage | Bilder | Kaskade / steps | Textur |
|---|---|---|---|
| `Fahrzeug_MultiView4_1_Form.json` → `..._2_Textur.json` | **4** — Front, Heck, links, rechts | 1536 / 25 | 1536 |
| `Fahrzeug_MultiView2_1_Form.json` → `..._2_Textur.json` | **2** — Front, Heck | 1536 / 25 | 1536 |
| `Fahrzeug_Render_HQ.json` | 1 — 3/4-Render | 1536 / 25 | 1536 |
| `Fahrzeug_Render_Serie.json` | 1 — 3/4-Render | 1024 / 15 | 1536 |
| `Fahrzeug_TopDown_HQ.json` | 1 — Sprite | 1536 / 25 | 1536 |
| `Fahrzeug_TopDown_Serie.json` | 1 — Sprite | 1024 / 15 | 1536 |

## Multi-View läuft in zwei Stufen

Erst die Form, dann die Textur — zwei Dateien nacheinander:

1. **`Fahrzeug_MultiView4_1_Form.json`** ziehen, Run. Ergebnis:
   `tools\ComfyUI\output\rookie_form_00001_.glb` (Geometrie, unbemalt).
2. **`Fahrzeug_MultiView4_2_Textur.json`** ziehen. Im Node `Trellis2LoadMesh`
   steht der Pfad aus Schritt 1 bereits eingetragen — nur die laufende Nummer
   prüfen. Run. Ergebnis: `rookie_00001_.glb` mit Textur.

**Warum getrennt und nicht in einem Durchlauf?** Weil die beiden Wege über
verschiedene Nodes texturieren, und einer davon weniger kann:

| Node | maximale Texturauflösung |
|---|---|
| `Trellis2TexSlatMultiViewGenerator` — im kombinierten Beispiel | **1024** |
| `Trellis2MeshTexturingMultiView` — getrennte Stufe | **1536** |
| `Trellis2MeshTexturing` — Einzelbild-Weg | **1536** |

Das kombinierte Multi-View-Beispiel des Nodes benutzt den ersten. Ein Modell aus
zwei Ansichten konnte deshalb **schlechter texturiert** aussehen als eines aus
einer einzigen — die bessere Form kam mit der schlechteren Textur. Getrennt
bekommt die Form alle Ansichten und die Textur die volle Auflösung.

Zweiter Vorteil: Die Form ist der teure Teil. Eine Textur lässt sich neu rechnen,
ohne die Form noch einmal zu erzeugen — etwa mit anderen Parametern oder
schärferen Bildern.

**Die Zahl der Ansichten schlägt jede Einstellung.** Was TRELLIS sieht, muss es
nicht erfinden. Aus einem Top-Down-Sprite wird die ganze Flanke geraten, aus
einer 3/4-Frontansicht immer noch das Heck — Rückleuchten, Stoßfänger und
Heckklappe kommen dann aus der Silhouette. Mit Front und Heck fällt das weg, mit
allen vier Ansichten bleibt nichts Ungesehenes übrig.

Die Bilder heißen in den Multi-View-Vorlagen:

```
rookie_3d_front.png   rookie_3d_heck.png   rookie_3d_links.png   rookie_3d_rechts.png
```

**Alle vier Bilder müssen vorhanden sein**, sonst bricht der Lauf am fehlenden
Bild ab. Wer nur zwei hat, nimmt `Fahrzeug_MultiView_2.json`.

Alle Vorlagen außer den Sprite-Varianten erwarten Renders **ohne** eigene
Transparenz und stellen sie über `remove_background` selbst frei — das ist keine
Geschmacksfrage, sondern Pflicht (siehe unten).

Beide heben `sparse_structure_resolution` auf 64 — das ist die Einstellung, die
über runde Reifen entscheidet, und sie ist in keiner Variante verhandelbar.

## Laufzeit

Gemessen am Lauf vom 11.08.2026 mit den **Standardwerten** (19:18 gesamt):

```
Sparse structure @32 :  12 x  9,78 s =  2:01
Shape SLat @512      :  12 x  1,42 s =  0:18
Shape SLat HR @1024  :  12 x 15,49 s =  3:21
Texture SLat         :  12 x  6,81 s =  1:20
Rest (Rekonstruktion, Löcher, xatlas)  ca. 12:00
```

Die Abtastung macht also nur rund 7 der 19 Minuten aus. Die Schrittzahl schlägt
linear auf diese 7 Minuten durch — die Voxelauflösung dagegen auf alles:
32 → 64 verachtfacht die Voxelzahl. Rechne bei `Serie` mit deutlich mehr als
19 Minuten und bei `HQ` mit einem Vielfachen davon. Vor dem Durchlauf über alle
15 einmal messen.

## Was pro Fahrzeug zu ändern ist

Genau zwei Felder:

1. **`Trellis2LoadImageWithTransparency`** → das Sprite wählen, z. B. `Supercar_2.png`.
   `tools\start_gui.bat` kopiert alle 15 Sprites bei jedem Start nach
   `tools\ComfyUI\input\`, sie stehen also in der Auswahlliste.

   Bei den Render-Vorlagen heißt das Bild in der Vorlage `rookie_3d.png` —
   entweder deinen Render so benennen oder im Node umstellen.

   **Das Bild braucht echte Transparenz.** `Trellis2PreProcessImage` greift in
   `nodes.py:2675` ungeprüft auf den vierten Kanal zu — die eingebaute
   Hintergrundentfernung ist dort auskommentiert. Ein Bild ohne Alphakanal, etwa
   ein Render mit schwarzem Hintergrund, bricht mit
   `IndexError: index 3 is out of bounds for axis 2 with size 3` ab. Ein
   Alphakanal, der durchgehend 255 ist, stürzt nicht ab, taugt aber auch nicht:
   Zeile 2684 rechnet `rgb * alpha`, und der Zuschnitt nimmt dann das ganze Bild
   samt Hintergrund.

   Deshalb steht in den **Render-Vorlagen** `remove_background: true` — rembg
   stellt vor dem Durchlauf frei. In den **Sprite-Vorlagen** steht `false`, denn
   die Sprites bringen ihre Transparenz mit, und rembg würde eine saubere
   Freistellung durch eine geschätzte ersetzen.

   Wer die Freistellung vorher sehen will, statt sie nach zwanzig Minuten am
   Mesh zu beurteilen:

   ```
   tools\freistellen.bat "C:\pfad\zum\render.png"
   ```

   Das legt eine freigestellte RGBA-Fassung in `input\` und daneben ein
   Kontrollbild auf Magenta. Wird dieses Bild verwendet, gehört
   `remove_background` wieder auf `false` — die Freistellung ist ja schon drin.
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

## Die Ansichten aufnehmen

Die vier Ansichten müssen **dasselbe Fahrzeug in derselben Größe und aus
derselben Höhe** zeigen — TRELLIS führt sie über eine gemeinsame
Blickrichtungsliste zusammen und rechnet nicht aus, dass die Heckansicht
zufällig näher aufgenommen wurde.

| Ansicht | Blickrichtung |
|---|---|
| `front` | schräg von vorne, das Fahrzeug 3/4 im Bild |
| `heck` | die gegenüberliegende Ecke, also schräg von hinten |
| `links` | Seitenansicht der linken Flanke |
| `rechts` | Seitenansicht der rechten Flanke |

Der Parameter `front_axis` steht in allen Multi-View-Nodes auf `z` und legt
fest, entlang welcher Achse die Frontansicht blickt. Kommt das Modell verdreht
heraus, ist das der erste Schalter — nicht die Bilder neu aufnehmen.

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

Für die Multi-View-Vorlagen entstehen Knoten und Verbindungen im Programm — die
zusätzlichen Bildpfade für links und rechts gibt es im Beispiel des Nodes nicht.
Deshalb liest `make_workflows.py` jeden fertigen Graphen gegen: doppelte IDs,
Verbindungen ins Leere, Ein- und Ausgänge, die nicht zueinander passen. Ein
fehlerhafter Graph wird gar nicht erst geschrieben. Ohne diese Prüfung fällt ein
falscher Verbindungsindex erst in ComfyUI auf, und dort als stiller Fehler —
ein nicht verbundener Eingang bleibt einfach leer.

## Was gegenüber dem Beispiel geändert wurde

| Einstellung | Beispiel | Vorlage | Warum |
|---|---|---|---|
| `Trellis2LoadModel.backend` | `flash_attn` | `sdpa` | flash_attn ist nicht installiert |
| `sparse_structure_resolution` | 32 | **64** | siehe unten |
| `Trellis2ShapeGenerator.resolution` | 512 | 1024 | |
| `ShapeCascade` von/bis | 0 → 1024 | 512 → 1536 | |
| alle `steps` | 12 | 15 bzw. 25 | sauberere Kanten |
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

## Der Regler für Bildtreue: `dino_lock`

Wenn ein Modell dem Bild noch nicht genau genug folgt, ist das die Stellschraube
— und sie ist keine Vermutung, das steht so im Sampler
(`trellis2/pipelines/samplers/flow_euler.py`, `DinoLockMixin`):

> Bei `dino_lock > 0` rechnet jeder Schritt sowohl die CFG-geführte als auch die
> rein DINOv3-bedingte Geschwindigkeit und mischt Richtung DINO.

```
Schritte   0–40 %:  0.92               volle DINO-Bindung, baut die Form
Schritte  40–70 %:  Rampe 0.92 → dino_lock
Schritte 70–100 %:  dino_lock          Leitplanke für die Details
```

`dino_lock = 0` schaltet den Mechanismus komplett ab. Im `Trellis2SparseGenerator`
steht er bereits auf `1.0`, in den Shape-Stufen auf `0`. Beides bleibt in den
Vorlagen so.

**Was es kostet:** jeder Schritt rechnet zwei Geschwindigkeiten statt einer, die
Abtastung dauert also etwa doppelt so lange. `dino_substeps` multipliziert
zusätzlich. Deshalb ist es hier nicht voreingestellt — wer die Bildtreue der
Form noch weiter treiben will, setzt `dino_lock` im `Trellis2ShapeGenerator` und
im `Trellis2ShapeCascadeGenerator` auf etwa 0,3 bis 0,5 und vergleicht.

## Was die Vorlagen nicht lösen können

Bei den **Sprite-Vorlagen**: Die Sprites sind reine Top-Down-Ansichten. TRELLIS
sieht kein einziges Pixel der Flanke — Schweller, Radhausformen, Türfugen und
Reifenflanken werden erfunden, und die Textur der Seiten wird per Inpainting
gefüllt. Keine Auflösungseinstellung erzeugt Information, die im Eingabebild
nicht vorhanden ist. Genau deshalb sind die Render-Vorlagen die bessere Wahl.

Bei **allen** Vorlagen: Welche Seite vorne ist, kann TRELLIS nicht wissen und
das Import-Werkzeug nicht zuverlässig erkennen — Motorhaube und Kofferraum sind
sich zu ähnlich. Zeigt die Front nach `-X`, gehört das Fahrzeug in
`trellis_import.json` auf `"flip": true`.

Auch mit einem 3/4-Render bleibt eine Seite ungesehen. Wenn das stört, ist der
nächste Schritt eine echte Multi-View-Eingabe
(`MeshWithTexturing_MultiView.json`) mit mehreren Ansichten desselben Fahrzeugs.
