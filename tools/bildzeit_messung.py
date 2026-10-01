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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("strecke", nargs="?", default="gp")
    ap.add_argument("--sekunden", type=float, default=12.0)
    ap.add_argument("--feld", type=int, default=8)
    ap.add_argument("--aufloesung", default="1920x1080")
    ap.add_argument("--stufe", default="hoch")
    ap.add_argument("--profil", action="store_true")
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
