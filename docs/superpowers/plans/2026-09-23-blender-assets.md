# Blender-Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Realistische Fahrzeuge (Räder getrennt, richtig platziert) und
Themen-Umgebung aus Blender ins 3D-Spiel bringen, geladen vor dem Rennen.

**Architecture:** Blender-Skripte unter `tools/blender/` erzeugen GLBs in
`assets/`. Der Renderer (`src/render3d/`) lädt Mehrmaterial-GLBs, färbt das
Material `lack` um, platziert Deko instanziert nach `data/themen/*.json`.

**Tech Stack:** Blender 4.5 LTS (bpy, headless), Python 3.11, moderngl,
trimesh, numpy, pygame-ce.

## Global Constraints

* Spec: `docs/superpowers/specs/2026-09-23-blender-assets-design.md`.
* `src/render3d/VEREINBARUNGEN.md` gilt: +X vorne, +Y links, +Z oben, Meter,
  Ursprung mittig am Boden, Texturen einmal beim Hochladen gespiegelt.
* `src/render3d/` importiert weder pygame noch Spielklassen.
* Code und Kommentare deutsch. Dateien UTF-8 ohne BOM.
* Blender-Aufruf: `F:\Blender\blender-4.5.14-windows-x64\blender.exe -b -P <skript> -- <args>`.
* Schnelltest: `.venv\Scripts\python.exe -m pytest tests/test_render3d_*.py -q`.

---

### Task 1: TRELLIS-Altbestand entfernen
- [ ] `trellis_pipeline/`, `trellis_import.py`, `trellis_import.json`,
  `tests_pipeline/`, `workflows/`, `tools/radpruefer*`, `tools/start_gui.bat`,
  alte GLBs, Lackmasken löschen (Kopien der GLBs nach `rohdaten/alt/`).
- [ ] Verweise entfernen: `korrektur_datei` in `rennszene`/`race_state`/
  `vehicle_node`, Tools, Tests. Schnelltest grün. Commit.

### Task 2: Mehrmaterial-Laden und Materialshader
- [ ] Test: GLB mit zwei Materialien → `Teilnetz.primitive` je Material mit
  Name, Grundfarbe, Metallic, Rauheit, Emission, Alpha, Texturen.
- [ ] `mesh.laden`/`hochladen` umbauen, Shader um `emission`, `alpha`
  ergänzen, `rennszene` zeichnet je Primitive. Commit.

### Task 3: Fahrzeuggenerator in Blender
- [ ] `tools/blender/fahrzeug_bauen.py` + `tools/blender/fahrzeuge.json`
  (15 Einträge). Ausgabe GLB + `_teile.json`.
- [ ] Test `tests/test_render3d_fahrzeugmodelle.py`: je Fahrzeug-JSON ein GLB,
  Knoten vorhanden, Maße ±5 %, Naben am Boden auf Radradius, Material `lack`.
- [ ] Kontrollrenderings (Blender Eevee) prüfen. Commit.

### Task 4: Lack in 3D
- [ ] `Fahrzeugstand.lack`; `rennszene.lack_parameter(kennung, werkfarbe)` →
  Farbe/Metallic/Rauheit/Zweitfarbe. Test. `race_state` füllt es. Commit.

### Task 5: Umgebungs-Assets
- [ ] CC0-Downloads (Poly Haven) nach `rohdaten/cc0/`, Lizenzliste.
- [ ] `tools/blender/umgebung_bauen.py`: Objekte je Thema + LOD1, Kulisse,
  Bodentexturen nach `assets/`. Commit.

### Task 6: Platzierung und Deko-Zeichnen
- [ ] `data/themen/<thema>.json`. `src/render3d/deko.py`:
  `platzieren(netz, thema, seed) -> list[Platzierung]` (numpy, testbar),
  `Dekozeichner` instanziert mit LOD. Tests: deterministisch, Mindestabstand
  zur Fahrbahn, keine Überlappung. Commit.

### Task 7: Boden, Fahrbahn, Himmel, Nebel, Schatten
- [ ] Fahrbahn- und Untergrundtextur, Untergrund bis hinter die Kulisse,
  Himmel/Nebel je Thema, Shadow Map der Sonne. Commit.

### Task 8: Ladebildschirm
- [ ] `RaceState`: Laden in Schritten mit Balken vor dem Countdown. Commit.

### Task 9: Abnahme
- [ ] Rennen je Strecke mit Screenshot, fps bei 1080p, Suite. Übergabedoku.
