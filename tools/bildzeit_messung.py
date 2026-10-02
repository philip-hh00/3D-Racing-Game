"""Bildzeit-Messung: cProfile und Zeit je Stufe eines echten Rennens.

    .venv\\Scripts\\python.exe tools\\bildzeit_messung.py gp --stufe hoch --aufloesung 1920x1080 --profil

Wie ``rennen_probe.py``, aber getrennt gemessen: ``update``, Zeichnen von Welt
und HUD (``render``), Überlagerung (``bild_abschliessen`` ohne Flip) und der
Flip selbst. ``--profil`` gibt zusätzlich die teuersten Funktionen aus.
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "tests"))


def _stufen_einhaengen() -> dict:
    """Zeitnehmer um die wichtigen Schritte legen; gezählt wird erst, wenn ``messen`` an ist."""
    import importlib
    ziele = [
        ("update: KI-Feld auffrischen", "src.states.race_state", "RaceState", "_ai_feld_auffrischen"),
        ("update: Physikschritt (pymunk)", "src.physics.physics_world", "PhysicsWorld", "step"),
        ("update: Rennverwaltung", "src.states.race_manager", "RaceManager", "update"),
        ("update: KI-Fahrzeug gesamt", "src.entities.ai_vehicle", "AIVehicle", "update"),
        ("  KI-Regler (compute_inputs)", "src.ai.ai_controller", "AIController", "compute_inputs"),
        ("    Planer", "src.ai.planer", "Planer", "planen"),
        ("    sd() Lotfusspunkt", "src.ai.strecke_frenet", "StreckeFrenet", "sd"),
        ("  Fahrzeugphysik (Vehicle.update)", "src.entities.vehicle", "Vehicle", "update"),
        ("update: Klang", "src.states.race_state", "RaceState", "_klang_aktualisieren"),
        ("update: Staende + Raeder fortschreiben", "src.states.race_state", "RaceState", "_staende_fortschreiben"),
        ("render: Welt (3D) gesamt", "src.states.race_state", "RaceState", "_welt_zeichnen"),
        ("  Schattenkarte", "src.render3d.rennszene", "Rennszene", "_schattenkarte_zeichnen"),
        ("  Nachbearbeitung beginnen", "src.render3d.nachbearbeitung", "Nachbearbeitung", "beginnen"),
        ("  Deko (Farbe + Schatten)", "src.render3d.deko", "Dekozeichner", "zeichnen"),
        ("  Gras", "src.render3d.gelaende", "Graszeichner", "zeichnen"),
        ("  Strecke + Gelaende", "src.render3d.rennszene", "Rennszene", "_strecke_zeichnen"),
        ("  Himmel", "src.render3d.licht", "Himmel", "zeichnen"),
        ("  Fahrzeug zeichnen (je Durchgang)", "src.render3d.rennszene", "Rennszene", "_fahrzeug_zeichnen"),
        ("  Klecksschatten", "src.render3d.rennszene", "Rennszene", "_schatten_zeichnen"),
        ("  Nachbearbeitung abschliessen", "src.render3d.nachbearbeitung", "Nachbearbeitung", "abschliessen"),
        ("render: HUD", "src.hud.hud", "HUD", "render"),
        ("render: Minimap", "src.hud.minimap", "Minimap", "render"),
    ]
    werte: dict = {}
    zustand = {"an": False}
    for name, modul, klasse, methode in ziele:
        try:
            k = getattr(importlib.import_module(modul), klasse)
            orig = getattr(k, methode)
        except (ImportError, AttributeError):
            continue
        werte[name] = [0.0, 0]

        def eingewickelt(*a, _o=orig, _w=werte[name], **kw):
            if not zustand["an"]:
                return _o(*a, **kw)
            t0 = time.perf_counter()
            try:
                return _o(*a, **kw)
            finally:
                _w[0] += time.perf_counter() - t0
                _w[1] += 1

        setattr(k, methode, eingewickelt)
    werte["_zustand"] = zustand
    return _Stufen(werte)


class _Stufen(dict):
    """Die Zähler; ``an`` schaltet das Zählen."""

    def __init__(self, werte):
        zustand = werte.pop("_zustand")
        super().__init__(werte)
        self.zustand = zustand


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("strecke", nargs="?", default="gp")
    ap.add_argument("--sekunden", type=float, default=12.0)
    ap.add_argument("--feld", type=int, default=8)
    ap.add_argument("--aufloesung", default="1920x1080")
    ap.add_argument("--stufe", default="hoch")
    ap.add_argument("--profil", action="store_true")
    ap.add_argument("--stufen", action="store_true",
                    help="Zeit je Arbeitsschritt (eingeschlossen, ohne cProfile-Aufschlag)")
    ap.add_argument("--gc", action="store_true", help="gc.freeze() nach dem Laden, hohe Schwellen")
    ap.add_argument("--zeilen", type=int, default=45)
    ap.add_argument("--sortierung", default="tottime")
    args = ap.parse_args()

    import numpy as np
    import pygame
    from src.core import display, sfx
    sfx.mixer_vorbereiten()
    pygame.init()
    display.apply_settings(resolution=args.aufloesung, fullscreen=False)
    from src.render3d import grafik
    display.kontext()
    grafik.stufe_setzen(args.stufe)

    import spielhilfe
    rennen, _sm = spielhilfe.rennen_bauen(args.strecke, feld=args.feld, runden=3)
    stufen = _stufen_einhaengen() if args.stufen else None
    if args.gc:
        import gc
        gc.collect()
        gc.freeze()
        gc.set_threshold(50000, 20, 20)
    uhr = pygame.time.Clock()
    spalten = {"update": [], "beginnen": [], "render": [], "abschluss": [], "flip": [], "gesamt": []}
    pr = cProfile.Profile() if args.profil else None
    t = 0.0
    n = 0
    # Der Flip wird getrennt gemessen: bild_abschliessen ruft ihn am Ende.
    echter_flip = pygame.display.flip
    flipzeit = [0.0]

    def flip():
        a = time.perf_counter()
        echter_flip()
        flipzeit[0] = time.perf_counter() - a

    pygame.display.flip = flip

    # Wie viel der HUD-Fläche geht je Bild hoch? (Schmutzverfolgung)
    from src.ui import leinwand
    hoch = {"bilder": 0, "ganz": 0, "flaeche": 0}
    echt = leinwand.Flaeche.schmutz_rechtecke

    def gemessen(self):
        r = echt(self)
        hoch["bilder"] += 1
        w, h = self.bildpunkte()
        if r is None:
            hoch["ganz"] += 1
            hoch["flaeche"] += w * h
        else:
            hoch["flaeche"] += sum(x.width * x.height for x in r)
        hoch["gesamt"] = w * h
        return r

    leinwand.Flaeche.schmutz_rechtecke = gemessen
    while t < args.sekunden:
        dt = min(uhr.tick(0) / 1000.0, 0.05)
        t += dt
        n += 1
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                t = args.sekunden
        messen = n > 60
        if stufen is not None:
            stufen.zustand["an"] = messen
        b = time.perf_counter()
        if pr is not None and messen:
            pr.enable()
        rennen.update(dt)
        c = time.perf_counter()
        display.bild_beginnen()
        d = time.perf_counter()
        rennen.render(display.virtual_surface())
        e_ = time.perf_counter()
        display.bild_abschliessen()
        f = time.perf_counter()
        if pr is not None and messen:
            pr.disable()
        if messen:
            spalten["update"].append(c - b)
            spalten["beginnen"].append(d - c)
            spalten["render"].append(e_ - d)
            spalten["abschluss"].append(f - e_ - flipzeit[0])
            spalten["flip"].append(flipzeit[0])
            spalten["gesamt"].append(f - b)
    print(f"{args.strecke} {args.stufe} {args.aufloesung}: {len(spalten['gesamt'])} Bilder")
    for k, v in spalten.items():
        z = np.array(v) * 1000
        print(f"  {k:11s} Median {np.median(z):6.2f} ms  Mittel {z.mean():6.2f}  p95 {np.percentile(z, 95):6.2f}")
    if stufen is not None:
        n_bilder = max(1, len(spalten["gesamt"]))
        print("  Arbeitsschritte (ms je Bild, eingeschlossen; Aufrufe je Bild):")
        for name, (summe, aufrufe) in stufen.items():
            print(f"    {name:44s} {summe / n_bilder * 1000:6.2f}   {aufrufe / n_bilder:6.1f}x")
    if hoch["bilder"]:
        print(f"  HUD-Upload: im Mittel {hoch['flaeche'] / hoch['bilder'] / hoch['gesamt'] * 100:.0f} % der Fläche, "
              f"{hoch['ganz']} von {hoch['bilder']} Bildern ganz")
    if pr is not None:
        st = pstats.Stats(pr)
        st.sort_stats(args.sortierung).print_stats(args.zeilen)
    spielhilfe.alles_schliessen()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
