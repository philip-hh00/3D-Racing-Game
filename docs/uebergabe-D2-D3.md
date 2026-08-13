# Übergabe: Phase D2 und D3

Stand nach Commit `b0e375b`. Dieses Dokument ist die Vorlage für den nächsten
Chat — es steht im Repo, damit es nicht am Kontextfenster hängt.

## Auftrag

**D2 und D3 umsetzen.** D1 ist im Kern bewiesen (`tools/fahrtest.py`), muss aber
noch in `RaceState` einziehen.

**Entschieden am 11.08.2026: kein Umschalter zwischen 2D und 3D.** Das hier ist
ein eigenständiges Spiel. Der alte Zeichenweg wird **ersetzt**, nicht umgangen —
`src/track/track_renderer.py`, `src/entities/components/renderer.py` und
`src/core/camera.py` verlieren ihre Aufgabe. Die 2D-Fassung liegt unverändert
und lauffähig unter `F:\Fahr-Rennspiel-2D`, falls sie gebraucht wird.

## Was steht

| Baustein | Datei | Tests |
|---|---|---|
| Kamera, Projektion, Verfolgerkamera | `src/render3d/camera.py` | 18 |
| GLB laden und hochladen | `src/render3d/mesh.py` | 14 |
| Streckennetz aus `data/tracks/*.json` | `src/render3d/track_mesh.py` | 20 + 9 |
| HUD-Überlagerung, Bildaufbau | `src/render3d/ansicht.py` | 11 |
| pygame-Fenster mit OpenGL | `src/render3d/fenster.py` | — |
| Matrizen | `src/render3d/matrix.py` | — |
| Karosserie + vier Räder in Bewegung | `src/render3d/vehicle_node.py` | 22 |
| PBR-Beleuchtung | `src/render3d/shader.py` | 10 |
| Asset-Aufbereitung | `trellis_pipeline/`, `trellis_import.py` | 76 |

Lauffähig: `tools/vorschau3d.bat` (Abspulen an der Mittellinie),
`tools/fahrtest.bat` (**echte pymunk-Physik**, W/S/A/D, Leertaste, R, Esc),
`tools/radpruefer.bat` (Nabe von Hand setzen), `tools/start_gui.bat` (ComfyUI).

Testlauf: `.venv\Scripts\python.exe -m pytest tests_pipeline tests/test_render3d_*.py -q`
→ 183 grün. Die Spielsuite `pytest tests` braucht 7–11 min; zwei Fehlschläge und
19 Affentest-Fehler sind **vorbestehend**, sie fallen im 2D-Projekt genauso aus
(Windows-Recht für Verknüpfungen, `WinError 1314`).

## D2 — HUD über die 3D-Szene

Die Mechanik ist fertig und geprüft, sie muss nur eingehängt werden.

`src/core/display.py` zeichnet seit jeher auf eine virtuelle Fläche von
1920×1080. Genau die wird zur Textur:

```python
bild = ansicht.Ansicht3D(ctx, fenster.VIRTUELL)
bild.neues_bild(himmel=shader.HIMMEL_HORIZONT)
...  # 3D zeichnen
bild.hud_zeichnen(virtuelle_flaeche)   # HUD, Minimap, Menüs unverändert darüber
pygame.display.flip()
```

Zu beachten:

* Mit `pygame.OPENGL` ist die Fläche aus `set_mode` **nicht mehr bemalbar**.
  `display.py` muss die virtuelle Fläche liefern, das Fenster selbst nicht mehr.
* `hud_zeichnen(flaeche, geaendert=False)` überspringt den Upload und zeichnet
  die vorhandene Textur erneut — für Bilder ohne HUD-Änderung.
* Die Überlagerung schaltet den Tiefentest selbst ab und mischt mit Alpha.

Betrifft: `src/core/display.py`, `src/core/game.py` (Hauptschleife),
`src/states/race_state.py` (`render`, `_render_world`), Splitscreen.

## D3 — acht Fahrzeuge, KI fährt

* Je Fahrzeug ein `vehicle_node.Fahrzeugknoten`; das GLB **einmal** laden und
  die VAOs teilen, nicht achtmal 600 000 Dreiecke hochladen.
* Rollwinkel je Fahrzeug aus `signed_speed * M_PER_PX * dt`, Lenkeinschlag aus
  `vehicle_node.lenkwinkel_aus_fahrzeug(fahrzeug)`.
* Die KI (`src/ai/`) rührt nichts an der Darstellung an, sie läuft unverändert.
* Startaufstellung: `strecke.start_positions`, Winkel in **Grad**.
* Ghosts werden im 2D-Weg über `lack.graustufen` entfärbt — in 3D braucht das
  einen Shader-Schalter, kein umgefärbtes Sprite.

## Vereinbarungen (bindend)

`src/render3d/VEREINBARUNGEN.md` lesen. Kurz:

* **+X vorne, +Y links, +Z oben**, Meter, Ursprung des Fahrzeugs mittig am Boden.
* `M_PER_PX = 0.08` aus `src/core/settings.py` importieren, nie hinschreiben.
* Matrizen `(4,4) float32`, Zeilenkonvention, beim Hochladen **transponieren**.
* Texturen werden **einmal beim Hochladen** vertikal gespiegelt, nicht im Shader.
* Base Color ist sRGB und wird im Shader nach linear gerechnet;
  Metallic-Roughness ist lineare Messgröße und bleibt.

## Fallen, die schon einmal Zeit gekostet haben

* **Nicht spiegeln beim Übergang 2D→3D.** pymunk rechnet Y nach oben, die
  3D-Welt auch. `src/utils/math_utils.py` spiegelt für das *pygame*-Zeichnen.
* **Ein Testshader, der `in_normale` oder `in_uv` nicht wirksam benutzt**,
  verliert das Attribut durch die GLSL-Optimierung → `KeyError`. `0.0 * n` wird
  wegoptimiert; `0.5 + 0.5 * abs(normalize(n).z)` hält es am Leben.
* **`framebuffer.read()` liefert Zeilen von unten nach oben.**
* **PowerShell `Set-Content -Encoding utf8` schreibt ein BOM** — Python
  importiert es, der Hygienetest des Projekts nicht.
* **`git check-ignore` überspringt getrackte Pfade**, meldet also fälschlich
  „ignoriert“.
* **Die `.gitignore`-Regeln des 2D-Projekts sind erarbeitet, nicht ausgedacht.**
  Nicht neu erfinden. `Servereinstellungen/` und `Hugging-Face/` bleiben draußen.
* **`test_auslieferung.py`** bewacht die Grenze zwischen `requirements.txt`
  (wird ausgeliefert) und `requirements-dev.txt`. scipy gehört nach dev.

## Offen

* **Zwei Testfahrzeuge fehlen**: `limousine` (5,20 m, Rad 0,69 m) und
  `supercar` (2,32 m breit). Am `rookie` allein lässt sich nicht prüfen, ob
  Ausrichtung, Skalierung und Radschnitt über die Bandbreite tragen. Erzeugen
  mit `workflows/Fahrzeug_MultiView4_1_Form.json` → `..._2_Textur.json`, dann
  `python trellis_import.py rohdaten\<key>.glb --fahrzeug <key>`.
* **Radinnenseite ist offen** — TRELLIS hat sie nie gesehen. Beim Lenken sichtbar.
* **Lackierung in 3D** (Phase E2): Basisfarbe und Lackmaske als zwei Texturen,
  Umfärbung im Shader. `trellis_import.py` sollte dafür die Helligkeits-
  Perzentile der Maskenfläche mitliefern (5./95., wie `lack.py` sie benutzt) und
  die Zusatzkanäle für Neon-Saum und Zweifarb-Streifen in die freien Kanäle der
  Maske packen.
* **Straßentextur**: die Bänder haben UV mit 8 m Kachellänge, aber noch keine
  Textur — nur Grundtöne.
