# Übergabe: Phase E

Stand nach Phase D, 02.09.2026. Dieses Dokument ist die Vorlage für den
nächsten Chat — es steht im Repo, damit es nicht am Kontextfenster hängt. Es
ersetzt `docs/uebergabe-D2-D3.md`.

## Wo das Projekt steht

**Phase D ist fertig.** Das Spiel zeichnet seine Rennwelt in 3D, es gibt
keinen zweiten Zeichenweg mehr. Abgenommen an einem Rennen auf dem Oval mit
acht Fahrzeugen, gefahren bis `race_manager.state == "finished"`, mit HUD,
Minimap, Startaufstellung und Zielflagge.

| Baustein | Datei |
|---|---|
| Fenster, Bildaufbau, Briefkasten, Mauskoordinaten | `src/core/display.py` |
| Rennwelt: Strecke, Fahrzeuge, Schattenflecke | `src/render3d/rennszene.py` |
| Schattenfleck | `src/render3d/schatten.py` |
| Kamera, Projektion, Verfolgerkamera | `src/render3d/camera.py` |
| GLB laden und hochladen | `src/render3d/mesh.py` |
| Streckennetz aus `data/tracks/*.json` | `src/render3d/track_mesh.py` |
| HUD-Überlagerung | `src/render3d/ansicht.py` |
| Karosserie und vier Räder in Bewegung | `src/render3d/vehicle_node.py` |
| PBR-Beleuchtung, Ghost-Entfärbung | `src/render3d/shader.py` |
| Asset-Aufbereitung, Radschnitt | `trellis_pipeline/`, `trellis_import.py` |

Entfernt, weil ohne Aufrufer: `src/track/track_renderer.py` und
`src/core/camera.py`. Sie liegen unverändert im 2D-Projekt unter
`F:\Fahr-Rennspiel-2D`. **`src/entities/components/renderer.py` bleibt** — es
zeichnet die Sprites in Fahrzeugauswahl, Lackierung und Fahrzeuglabor.

## Wie ein Bild entsteht

```python
display.bild_beginnen()               # Puffer leeren, Flaeche durchsichtig
state_machine.render(display.virtual_surface())
#   RaceState zeichnet darin die Welt in OpenGL und malt HUD und Minimap
#   wie bisher auf die virtuelle Flaeche
display.bild_abschliessen()           # Flaeche als Textur darueber, flip()
```

Vier Dinge, die daran hängen und die man kennen muss:

* **Das Fenster wird genau einmal erzeugt.** Ein zweites `set_mode` verwirft
  den OpenGL-Kontext und mit ihm jedes Netz und jede Textur. Auflösung und
  Vollbild schalten über `pygame.window.Window` um (`display._umschalten`).
* **Die virtuelle Fläche trägt einen Alphakanal.** Wo niemand zeichnet,
  scheint die Welt durch. `RaceState.render` füllt deshalb keinen Hintergrund
  mehr.
* **`SCALED` ist weg**, es verträgt sich nicht mit OpenGL. Der 16:9-Ausschnitt
  wird gerechnet (`display.ansichtsfenster`), der Rand bleibt schwarz, und
  `scale_pos` rechnet den Versatz für die Maus wieder heraus.
* **Ohne OpenGL liefert `display.kontext()` `None`.** Dann wird keine Welt
  gezeichnet und alles andere läuft weiter. Das ist der Testlauf ohne Fenster
  und **kein** Rückfall auf einen zweiten Zeichenweg.

## Wie ein Fahrzeug in die Szene kommt

`src/render3d/rennszene.py` kennt keine Spielklassen. Es bekommt je Bild eine
Liste von `Fahrzeugstand` — Kennung, Fahrzeugschlüssel, Position in Metern,
Gierwinkel, in diesem Bild zurückgelegter Weg, Lenkwinkel, entfärbt ja/nein.
`RaceState._staende_fortschreiben` füllt sie; ein Ghost, ein ferngesteuertes
Fahrzeug und ein KI-Wagen unterscheiden sich dort durch nichts als ihre Werte.

* **Modelle werden geteilt, Zustände nicht.** Acht Wagen auf demselben Netz
  laden das GLB einmal. Der Rollwinkel eines Rades wächst dagegen mit dem
  gefahrenen Weg und braucht je Fahrzeug einen eigenen `Fahrzeugknoten`.
* **Fehlt ein Modell, springt `rookie` ein**, und der Ersatz zieht auch die
  passende `_teile.json` nach sich. Kommt `limousine.glb` dazu, greift sie
  ohne Codeänderung.
* **Fortschreiben und Zeichnen sind getrennt.** Im Splitscreen wird zweimal
  gezeichnet, aber es vergeht nur einmal Zeit.

## Was gemessen ist

* **Bildrate**: acht Fahrzeuge auf dem Oval, 1280×720, Median 7,5 ms je Bild,
  95. Perzentil 10,1 ms — rund 134 Bilder je Sekunde einschließlich Physik, KI
  und HUD-Upload. Damit ist E3 vorweggenommen, solange nichts Teures dazukommt.
* **Schnelle Testrunde**:
  `.venv\Scripts\python.exe -m pytest tests_pipeline tests/test_render3d_*.py -q`
  → 221 grün in rund 8 Sekunden.
* **Spielsuite**: `pytest tests` → 2483 grün, 9 übersprungen, in 5:40 min.
  Zwei Fehlschläge (`test_einzelinstanz`, `test_release_pipeline`) und 19
  Affentest-Fehler sind **vorbestehend** und fallen im 2D-Projekt genauso aus
  (Windows-Recht für Verknüpfungen, `WinError 1314`).

## Was noch nicht gut aussieht

Nach Dringlichkeit:

1. **Alle acht Wagen tragen denselben Lack.** Das ist E2 und der auffälligste
   Punkt: ein Feld aus acht identischen roten Autos.
2. **Die Fahrbahn hat keine Textur**, nur Grundtöne. Die Bänder tragen bereits
   UV mit 8 m Kachellänge (`track_mesh`), es fehlt nur das Bild.
3. **Der Untergrund endet sichtbar am Horizont.** Die Ebene reicht 200 m über
   die Strecke hinaus (`track_mesh.bauen`, `untergrund_rand_m`); dahinter
   steht der Himmel. Bei flacher Kamera sieht man die Kante.
4. **Weiße Splitter am Felgenrand.** Reste der Schnittnaht, die mit dem Rad
   mitdrehen. Sie liegen innerhalb der Silhouette und fallen nur beim genauen
   Hinsehen auf. Zu sehen mit einer Seitenansicht des Rades bei mehreren
   Drehwinkeln.
5. **Die Radinnenseite ist offen** — TRELLIS hat sie nie gesehen. Beim Lenken
   sichtbar.
6. **Kein gerichteter Schattenwurf** (E1). Es gibt nur den weichen Fleck unter
   dem Fahrzeug.

## Offene Assets

* **Zwei Testfahrzeuge fehlen weiterhin**: `limousine` (5,20 m, Rad 0,69 m)
  und `supercar` (2,32 m breit). Am `rookie` allein lässt sich nicht prüfen,
  ob Ausrichtung, Skalierung und Radschnitt über die Bandbreite tragen —
  besonders der Radschnitt, dessen Schwellen an genau einem Modell gemessen
  sind. Erzeugen mit `workflows/Fahrzeug_MultiView4_1_Form.json` →
  `..._2_Textur.json`, dann
  `python trellis_import.py rohdaten\<key>.glb --fahrzeug <key>`.
* **Straßentextur, kachelbar, mit Rauheitskanal.**

## Vereinbarungen (bindend)

`src/render3d/VEREINBARUNGEN.md` lesen. Kurz:

* **+X vorne, +Y links, +Z oben**, Meter, Ursprung des Fahrzeugs mittig am Boden.
* `M_PER_PX = 0.08` aus `src/core/settings.py` importieren, nie hinschreiben.
* Matrizen `(4,4) float32`, Zeilenkonvention, beim Hochladen **transponieren**.
* Texturen werden **einmal beim Hochladen** vertikal gespiegelt, nicht im Shader.
* Base Color ist sRGB und wird im Shader nach linear gerechnet;
  Metallic-Roughness ist lineare Messgröße und bleibt.
* `src/render3d/` kennt weder pygame noch Spielklassen. Die Grenze ist
  `rennszene.Fahrzeugstand`.

## Fallen, die schon einmal Zeit gekostet haben

* **Nicht spiegeln beim Übergang 2D→3D.** pymunk rechnet Y nach oben, die
  3D-Welt auch. `src/utils/math_utils.py` spiegelt für das *pygame*-Zeichnen.
  Dafür gibt es jetzt `race_state.welt3d`.
* **Ein Testshader, der `in_normale` oder `in_uv` nicht wirksam benutzt**,
  verliert das Attribut durch die GLSL-Optimierung → `KeyError`. `0.0 * n` wird
  wegoptimiert; `0.5 + 0.5 * abs(normalize(n).z)` hält es am Leben.
* **`framebuffer.read()` liefert Zeilen von unten nach oben.**
* **`set_mode` ein zweites Mal aufzurufen kostet den GL-Kontext.** Siehe oben.
* **Ein Fahrzeugstand je Bild, nicht je Ansicht.** Sonst drehen sich die Räder
  im Splitscreen doppelt so schnell.
* **PowerShell `Set-Content -Encoding utf8` schreibt ein BOM** — Python
  importiert es, der Hygienetest des Projekts nicht.
* **Die `.gitignore`-Regeln des 2D-Projekts sind erarbeitet, nicht ausgedacht.**
  Nicht neu erfinden. `Servereinstellungen/` und `Hugging-Face/` bleiben draußen.
* **`test_auslieferung.py`** bewacht die Grenze zwischen `requirements.txt`
  (wird ausgeliefert) und `requirements-dev.txt`. scipy gehört nach dev.

## Werkzeuge

`tools/fahrtest.bat` (echte pymunk-Physik, W/S/A/D, Leertaste, R, Esc),
`tools/vorschau3d.bat` (Abspulen an der Mittellinie), `tools/radpruefer.bat`
(Nabe von Hand setzen), `tools/start_gui.bat` (ComfyUI).
