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

Reihenfolge am gelenkten Rad: `Fahrzeug · Nabe · Lenkung (Z) · Rollen (Y)`.
Gelenkt wird um die Senkrechte durch die Nabe, gerollt danach um die Radachse
im gelenkten Rad; der Sattel bekommt nur die Lenkung. Der Lenkwinkel in
`Fahrzeugstand.lenkwinkel_rad` ist der Winkel der Achsmitte in Radiant (+ = links);
`Fahrzeugknoten` verteilt ihn mit halbem Ackermann auf beide Vorderräder.

Alles, was sich mit dem Rad dreht, muss um Y rotationssymmetrisch sein —
sonst eiert es. Die Materialnamen sind Vertrag mit dem Renderer:

* `lack` — Hauptlack, einfarbig per Faktor, **keine Textur**. Die Lackierung
  aus der Werkstatt ersetzt Farbe, Metallic und Rauheit (`lack.werte_3d`).
* `lack2` — Zweitfarbe/Livree; beim Finish „zweifarbig“ umgefärbt.
* `glas` — `alphaMode BLEND`, wird nach allem Deckenden gezeichnet.
* Übrige (`chrom`, `felge`, `gummi`, `licht_vorn` …) bleiben, wie sie sind.

**Cockpit (ab 1.1.0)** — zusätzliche Knoten nur in `<key>.glb`, nicht im LOD1.
Alle Koordinaten im Fahrzeugsystem oben (+X vorne, +Z oben, Ursprung
Fahrzeugmitte am Boden):

| Knoten | Ursprung | Bewegung |
|---|---|---|
| `augpunkt` | Augenmitte des Fahrers (leeres Objekt) | keine; Cockpitkamera, Blick nach +X |
| `lenkrad` | Mitte des Lenkradkranzes auf der Lenksäulenachse | dreht um die **lokale X-Achse** (= Lenksäule, zeigt zum Fahrer hin geneigt); + = links |
| `nadel_tacho` `nadel_drehzahl` | Drehpunkt der Nadel | drehen um die **lokale X-Achse** (Blickrichtung ins Instrument); in Ruhe zeigt die Nadel auf den Skalenanfang |
| `spiegel_innen` `spiegel_l` `spiegel_r` | Mitte der Spiegelfläche | starr; Spiegelglas als eigenes Netz mit Material `spiegel`, UV 0..1 über die Fläche (U nach rechts, wie der Fahrer hineinschaut) |

`<key>_teile.json` bekommt den Block `"cockpit"`:

```json
"cockpit": {
  "augpunkt": [x, y, z],
  "haube": [x, y, z],
  "lenkrad_uebersetzung": 12.0,
  "tacho_max_kmh": 320, "tacho_winkel_grad": [-135, 135],
  "drehzahl_max": 9000, "drehzahl_winkel_grad": [-135, 135]
}
```

`haube` ist der Kamerapunkt der Motorhaubenansicht. Die Winkelangaben sind
die Drehung um die lokale X-Achse der Nadel bei 0 und bei Maximum. Der
Lenkradwinkel ist der sichtbare Lenkwinkel der Räder mal
`lenkrad_uebersetzung`. Fehlt ein Knoten oder der Block, zeichnet der
Renderer ohne (alte GLBs bleiben gültig).

Wie der Renderer die Knoten bewegt (`vehicle_node.Fahrzeugknoten`):

* Jeder Netzknoten, der nicht `karosserie`, `rad_*` oder `sattel_*` heißt,
  hängt starr am Aufbau (Nicken/Wanken inklusive), mit seinem Ursprung aus
  der GLB — Innenraum- und Spiegelteile brauchen also nichts weiter.
* `lenkrad`: Drehung um die X-Achse durch den Knotenursprung, Winkel
  `-sichtbarer_lenkwinkel · lenkrad_uebersetzung`. Aus Fahrersicht (Blick
  entlang +X) ist ein positiver Winkel um +X im Uhrzeigersinn; links
  (positiver Lenkwinkel) dreht das Lenkrad deshalb gegen den Uhrzeigersinn.
* Nadeln: Winkel um die X-Achse wie in `teile.json` angegeben, linear nach
  Tempo (km/h) bzw. Drehzahl, an den Anschlägen gehalten. Positiv =
  Uhrzeigersinn aus Fahrersicht, also „mehr Tempo = nach rechts“.
* Die Drehung des Knotens selbst steckt schon in den Punkten (`mesh.laden`);
  gedreht wird um die Fahrzeug-X-Achse durch den Ursprung. Eine geneigte
  Lenksäule gehört deshalb in die Geometrie, nicht in die Knotendrehung.
* Fehlt `augpunkt` oder `haube` im Block, schätzt der Renderer sie aus
  `laenge_m`/`breite_m`/`hoehe_m` (`vehicle_node.cockpit_aus_masse`).

**Spiegel** (`spiegel_innen`, `spiegel_l`, `spiegel_r`, Material `spiegel`): in
der Cockpitansicht rendert die Szene (`rennszene._spiegel_rendern`, Modul
`spiegel.py`) für jeden **sichtbaren** Spiegel ein kleines Bild nach hinten in
eine Fließkommatextur (Innen 384×96, außen 224×96; auf Niedrig halb so groß und
jedes zweite Bild) und legt es auf das Glas. Die Kamera sitzt im Ursprung des
Knotens (also auf dem nickenden Aufbau), blickt entlang −X, außen 15° nach
außen. Das Bild ist waagerecht gedreht (Shader: `u → 1 − u`), `v` bleibt, `U`
läuft wie oben vereinbart nach rechts. Das Glas braucht darum **keine**
Normale zum Fahrer und keine besondere Ausrichtung — nur die Mitte als Ursprung
und das Format (Innen ~17×4,4 cm, außen ~16×7 cm; das Bild wird auf 0..1 gestreckt).
Ohne Bild (Spiegel aus, andere Wagen, Werkstatt) zeichnet der Renderer
dunkles, spiegelndes Glas statt der Modellfarbe. Im Spiegel fehlen Gras,
Reifenspuren, Rauch, Scheiben-Durchsicht und die Deko am Rand (nur Kulisse),
Autos kommen im LOD1 mit den großen Teilen.

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

## Tageszeit (ab 1.1.0)

`Rennszene(…, tageszeit="Tag"|"Abend"|"Nacht")`; fehlt der Wert oder ist er
unbekannt, ist es **Tag**, und Tag ist die Welt von 1.0.x unverändert (kein
Wert, kein Pixel anders). Alles dazu steht in `tageszeit.py` (nur Zahlen) und
in den `tz_*`-/`lichter_*`-Uniforms von `shader.py`.

* Sonne und Mond: die Himmelsrichtung kommt aus `assets/himmel/<Thema>.json`,
  die Höhe aus der Tageszeit. Schattenkarte und Geländeschatten lesen
  `Himmel.sonne` und folgen damit automatisch.
* Himmelsbild: wird für Abend/Nacht im Shader verbogen und getönt
  (`tz_himmel`, `tz_tint_*`); die Nacht fügt Sterne und Mond hinzu. Kein neues
  Bild nötig.
* **Lichter** (nachts): bis zu `shader.MAX_LICHTER` Punkt- und Kegellichter je
  Bild als Uniform-Felder, gewählt nach Nähe zum Blickpunkt
  (`tageszeit.lichter_waehlen`), begrenzt durch `grafik.lichter_max`. Es gibt
  keine Lichtschatten. Quellen: Scheinwerfer und Rücklicht je Auto,
  Laternen des Themas, sonst Flutlichtmasten (`masten.py`).
* **Materialnamen als Vertrag:** `licht_vorn` und `licht_hinten`/`bremslicht`
  glühen nachts stärker (Faktor auf die Emission des Modells); in
  Umgebungsmodellen leuchten Materialien, deren Name auf `_bulb` endet, nachts.
  Die Lichtpunkte eines Autos stammen aus den Netzen dieser Materialien
  (links/rechts nach dem Vorzeichen von Y, vorn/hinten nach dem von X).
* Eigene Shader: wer ein weiteres Programm schreibt, das Welt zeichnet, lässt
  `lichter_*` weg und gibt lineares HDR aus — dann bleibt es nachts dunkler als
  der Rest, aber nicht falsch. Wer die Lichter mitrechnen will, nimmt die
  Schleife aus `FRAGMENT` (Block „Lokale Lichter“).
