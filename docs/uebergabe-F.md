# Übergabe: Stand nach Phase E (Blender-Assets)

Stand 23.09.2026. Ersetzt `docs/uebergabe-E.md`.

## Was jetzt da ist

Das Spiel zeichnet eine vollständige 3D-Welt. Alle Modelle kommen aus Blender;
die TRELLIS-Pipeline samt Radschnitt und Lackmasken ist entfernt.

| Baustein | Datei |
|---|---|
| GLB-Leser, mehrere Materialien je Knoten | `src/render3d/mesh.py` |
| PBR-Shader: HDRI-Umgebung, Klarlack, Nebel, Schattenkarte, Instanzen | `src/render3d/shader.py` |
| Himmel und Schattenkarte | `src/render3d/licht.py` |
| Szene: Strecke, Begrenzung, Start/Ziel, Umgebung, Fahrzeuge, Laden in Schritten | `src/render3d/rennszene.py` |
| Leitplanke / Betonmauer / Reifenwand | `src/render3d/begrenzung.py` |
| Themen lesen | `src/render3d/thema.py`, `data/themen/*.json` |
| Platzierung (fest je Strecke) | `src/render3d/platzierung.py` |
| Instanziertes Zeichnen mit LOD | `src/render3d/deko.py` |
| Nicken und Wanken | `src/render3d/federung.py`, `vehicle_node.neigen` |
| 3D-Vorschau für Werkstatt und Fahrzeugauswahl | `src/render3d/vorschau.py` |
| Lackierung → Materialwerte | `src/core/lack.py: werte_3d` |
| Ladebildschirm vor dem Rennen | `RaceState._szene_aufbauen`, `_ladebild` |

Verträge (Knoten- und Materialnamen, Achsen): `src/render3d/VEREINBARUNGEN.md`.

## Assets bauen

Alles Erzeugte liegt unter `assets/` und ist (bis auf JSON) nicht versioniert.
Neu bauen mit **einem** Aufruf:

    tools\blender\bauen.bat            alles (Download, Texturen, Himmel, Fahrzeuge, Umgebung)
    tools\blender\bauen.bat fahrzeuge  nur Fahrzeuge
    tools\blender\bauen.bat umgebung   nur Umgebung

Blender 4.5 LTS liegt portabel unter `F:\Blender\blender-4.5.14-windows-x64`
(oder Umgebungsvariable `BLENDER`).

| Schritt | Werkzeug | Ergebnis |
|---|---|---|
| CC0 laden | `tools/assets_laden.py` (Liste: `tools/blender/cc0_liste.json`) | `rohdaten/cc0/`, `assets/texturen/`, `assets/LIZENZEN.md` |
| Texturen erzeugen | `tools/texturen_erzeugen.py` | Fassaden, Nadelzweige, Banden, Startbanner in `rohdaten/erzeugt/` |
| Himmel | `tools/blender/himmel_bauen.py` | `assets/himmel/<Thema>.jpg/.json` (Sonnenrichtung aus dem HDRI) |
| Fahrzeuge | `tools/blender/fahrzeug_bauen.py` + `fahrzeuge.json` | `assets/vehicles/<key>.glb`, `<key>_teile.json` |
| Umgebung | `tools/blender/umgebung_bauen.py` | `assets/umgebung/**.glb`, `katalog.json` |

Fremdmaterial ausschließlich CC0 (Poly Haven), aufgelistet in
`assets/LIZENZEN.md`. Werbebanden tragen erfundene Marken.

## Prüfen

* `tools/szene_foto.py <strecke>` — Bild der Szene ohne Fenster, mit Zeit je Bild.
* `tools/rennen_probe.py <strecke>` — echtes Rennen im Fenster, Fotos und Messung.
* `tools/fahrtest.bat <fahrzeug> <strecke>` — selbst fahren, `L` wechselt die Lackierung.
* Schnelltest: `.venv\Scripts\python.exe -m pytest tests/test_render3d_*.py -q`.

## Gemessen

1920×1080, acht Fahrzeuge, echtes `RaceState` mit Physik, KI und HUD
(`rennen_probe desert`): Median 9,7 ms je Bild, 95. Perzentil 12,6 ms.
Szene allein (`szene_foto`, GP Arena mit rund 1 100 Objekten): 8–9 ms.

## Offen / Ideen

* Startampel leuchtet dauerhaft rot; an den Countdown koppeln.
* Felswände der Kulisse strecken die Textur an steilen Flanken (planare UV).
* Innenraum der Fahrzeuge ist nur angedeutet (Wanne, Sitze, Lenkrad).
* `tools/ComfyUI/` (rund 40 GB, alte Erzeugungsseite) liegt noch lokal und
  kann von Hand gelöscht werden.
