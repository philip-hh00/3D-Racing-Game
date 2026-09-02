# D2 und D3: HUD ueber der 3D-Szene, acht Fahrzeuge im Rennen

Stand: 2026-09-02. Entworfen im Gespraech, bevor eine Zeile geschrieben wurde.

Dieses Dokument beschreibt **was** gebaut wird und **warum so**. Der
Umsetzungsplan mit den einzelnen Schritten steht daneben in
`docs/superpowers/plans/`.

## Ausgangslage

`tools/fahrtest.py` faehrt bereits mit der echten pymunk-Physik des Spiels und
zeichnet in 3D. Die Bausteine stehen und sind geprueft (183 Tests). Was fehlt,
ist der Einzug in das Spiel selbst: `RaceState` zeichnet noch ueber
`TrackRenderer` und Sprites.

**Kein Umschalter zwischen 2D und 3D** (entschieden am 11.08.2026). Der alte
Zeichenweg der Rennwelt wird ersetzt, nicht umgangen.

## Entscheidungen dieses Entwurfs

| Frage | Entscheidung | Warum |
|---|---|---|
| Aufloesungs- und Vollbildwechsel | Der GL-Kontext wird **nie** neu erzeugt | Ein neuer Kontext verwirft Shader, Texturen und Netze. Bei 600.000 Dreiecken je Fahrzeug waere jeder Wechsel ein Aussetzer von Sekunden |
| Acht Fahrzeuge, ein Modell | `<key>.glb`, still auf `rookie` zurueckfallend | Nur `rookie.glb` liegt vor. Kommen `limousine.glb` und `supercar.glb` dazu, greifen sie ohne Codeaenderung |
| Splitscreen | Sofort mit | Die Bildschleife wird ohnehin aufgemacht. Nachtraeglich hiesse, sie ein zweites Mal aufzumachen |
| Alter Zeichenweg | Nur die Rennwelt | `renderer.py` zeichnet auch Menuevorschauen. Ein gedrehtes Sprite auf einer Menuetafel ist dort richtig und kein 3D-Problem |
| Tests ohne OpenGL | Ohne Kontext bleibt die Welt leer | Kein 2D-Modus, kein Umschalter — nur kein Bild. Rennlogik, Rundenzaehlung, KI und Netz bleiben pruefbar, die Suite bleibt in Minuten |

## Aufbau

### Fenster und Bildaufbau — `src/core/display.py`, `src/core/game.py`

Das Fenster wird einmal mit `OPENGL | DOUBLEBUF | RESIZABLE` geoeffnet und
danach nie wieder erzeugt. `SCALED` faellt weg: es vertraegt sich nicht mit
OpenGL, und die Skalierung uebernimmt das bildschirmfuellende Rechteck der
Ueberlagerung.

`display.py` behaelt alle vorhandenen Namen und bekommt drei Aufgaben dazu:

* `kontext()` — der ModernGL-Kontext. `None`, wenn kein OpenGL da ist.
* `bild_beginnen()` — Ansichtsfenster setzen, Puffer leeren, virtuelle Flaeche
  auf **durchsichtig** loeschen.
* `bild_abschliessen()` — virtuelle Flaeche als Textur darueberlegen, `flip()`.
  Ersetzt `blit_to_window()`.

Zwei Dinge haengen daran:

**Die virtuelle Flaeche wird `SRCALPHA`.** Ohne Alphakanal deckt sie die
3D-Szene lueckenlos zu. Menues fuellen weiter deckend und sehen unveraendert
aus; `RaceState` fuellt nicht mehr, dort scheint die Welt durch.

**Briefkasten statt Zerren.** Ist das Fenster nicht 16:9, sitzt das
Ansichtsfenster mittig mit 16:9 darin, der Rand bleibt schwarz. `scale_pos`
rechnet den Versatz heraus, sonst greift die Maus im Menue daneben. Bisher
erledigte das `SCALED`.

Aufloesung und Vollbild schalten ueber `pygame.window.Window` um, ohne
`set_mode`.

### Die Rennszene — `src/render3d/rennszene.py` (neu)

Kennt kein pygame und keine Spielklassen, wie es
`src/render3d/VEREINBARUNGEN.md` verlangt. Eingabe ist eine Liste einfacher
Staende:

```python
@dataclass
class Fahrzeugstand:
    kennung: int          # zum Wiederfinden des Fahrzeugknotens
    schluessel: str       # "rookie", "limousine", ...
    pos_m: np.ndarray
    gierwinkel_rad: float
    weg_m: float          # in diesem Bild zurueckgelegt, mit Vorzeichen
    lenkwinkel_rad: float
    entfaerbt: bool = False
```

Darin:

* **`Modellspeicher`** — laedt `<schluessel>.glb` genau einmal und teilt VAOs
  und Texturen zwischen allen Fahrzeugen desselben Schluessels. Acht Fahrzeuge
  duerfen nicht achtmal 600.000 Dreiecke hochladen.
* **`Rennszene`** — haelt Streckennetz und je Kennung einen `Fahrzeugknoten`,
  zeichnet Strecke, Schattenflecke und Fahrzeuge ueber `zeichnen(kamera, staende)`.

Der Schattenfleck ist ein weiches dunkles Rechteck auf Fahrbahnhoehe mit
eigenem Kleinshader. Ohne ihn schweben acht Fahrzeuge sichtbar ueber der
Strasse. Der Ghost bekommt am Hauptshader zwei Uniformen dazu: `entfaerbung`
und `deckkraft` — kein umgefaerbtes Sprite, sondern ein Schalter im Shader.

### `RaceState`

`enter` baut die Szene nur, wenn `display.kontext()` etwas liefert.
`_render_world(surface, camera)` wird zu einem Zeichnen in OpenGL; `render`
malt danach HUD, Minimap, Pausenmenue und Onlineueberlagerungen unveraendert
auf die virtuelle Flaeche.

Splitscreen: zwei Ansichtsfenster nebeneinander, je eine `Verfolgerkamera`. Das
HUD zeichnet weiter in Unterflaechen der einen virtuellen Flaeche — dort
aendert sich nichts.

`TrackRenderer` und `src/core/camera.py` verlieren ihre Aufgabe in `RaceState`.
`renderer.py` bleibt fuer Fahrzeugauswahl, Lackierung und Labor.

Mitgezeichnet werden ausser Spieler und KI auch der Ghost (entfaerbt) und die
ferngesteuerten Fahrzeuge des Onlinerennens — letztere ueber denselben Weg wie
die KI, nur ohne Lenkwinkel.

## Radschnitt: Raeder sind Rotationskoerper

Getrennt von D2 und D3, parallel bearbeitet.

`assets/vehicles/rookie_teile.json` zeigt das Problem: vier gleiche Raeder,
aber `rad_vl` hat 54.309 Dreiecke und `rad_hl` 35.110. Der Ueberschuss ist
Kotfluegel und Radaufhaengung, und er dreht sich im Spiel mit dem Rad mit.

`_groesste_gruppe` trennt das nicht, weil Reifen und Radlauf bei TRELLIS **eine
durchgehende Flaeche** sind. Der fehlende Unterscheider ist die
Rotationssymmetrie: ein Rad deckt jeden Radiusring ueber volle 360 Grad ab, ein
Kotfluegelbogen ueber rund 120, ein Querlenker ueber einen Punkt.

Gemessen wird die **Winkelabdeckung** je Radiusring um die Nabe. Der
Schnittradius ist der groesste Radius, bis zu dem die Abdeckung hoch bleibt.
Einzelne Ringe unter der Schwelle fallen auch innerhalb des Radius weg, damit
Aufhaengungsteile verschwinden. Speichen werden geschont, indem der Test erst
ausserhalb eines inneren Anteils greift.

Abnahme: die vier Dreieckszahlen liegen dicht beieinander (unter 15 Prozent vom
Median), `pytest tests_pipeline` bleibt gruen.

## Was hier nicht drinsteht

* **Lackierung in 3D** — Phase E2. Bis dahin tragen alle acht denselben Lack.
* **Menuevorschauen in 3D** — eigene Baustelle, gehoert zu E2.
* **Schattenwurf** im Sinne einer Shadow Map — hier gibt es nur den Fleck.
* **Physik in 3D.** Bleibt 2D. Unveraendert.
