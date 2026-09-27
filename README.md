# 3D-Racing-Game

Ein 3D-Rennspiel mit echter Fahrphysik: 15 Fahrzeuge in fünf Klassen, ein
eigener Streckeneditor, Splitscreen zu zweit am selben Bildschirm und
Online-Rennen mit bis zu sechs Spielern.

## Spielmodi

* **Rennen** — klassisches Rundenrennen gegen die KI
* **Zeitfahren** — du gegen den Ghost der Streckenbestzeit
* **Team-Zeitfahren** — zwei Teams, es zählt die beste Durchschnittszeit
* **Grand Prix** — mehrere Rennen, Punkte über die ganze Serie, am Ende ein Champion

## Fahrzeuge

Fünf Klassen — Kompaktwagen, Supersportler, Drifter, Limousine, Elektro —
mit je drei Modellen und eigenem Fahrverhalten. In der Werkstatt lackierst
du dein Auto in zwölf Farben; Metallic, Neon und Zweifarbig schaltest du
durch Spielfortschritt frei.

## Strecken

Fünf mitgelieferte Strecken, dazu ein Streckeneditor für eigene Kurse —
Verlauf, Breite, Untergrund und Umgebung frei wählbar.

## Installation

Fertige Pakete für Windows und macOS liegen bei den
[Releases](../../releases). Windows: Installer starten. macOS: `.dmg`
öffnen und das Spiel in den Programme-Ordner ziehen.

## Steuerung

Standardmäßig Pfeiltasten (Gas/Bremse/Lenken) und Leertaste (Handbremse);
in den Einstellungen frei belegbar. Controller werden ebenfalls unterstützt.

## Aus dem Quelltext starten

Für Entwicklung und zum Selberbauen:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

Die Release-Pipeline (Windows-/macOS-Builds, Installer) ist in
[`Release/README.md`](Release/README.md) beschrieben.

## Lizenzen

Fahrzeuge, Strecken und Umgebung sind größtenteils selbst erstellt
(`tools/blender/`). Zusätzlich verwendetes Fremdmaterial (Bäume, Felsen,
Texturen) stammt von [Poly Haven](https://polyhaven.com) unter CC0 — Details
in [`assets/LIZENZEN.md`](assets/LIZENZEN.md), auch im Spiel unter
Einstellungen → Info einsehbar.
