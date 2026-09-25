"""Ein echtes Rennen im echten Fenster, ohne Menü — für Abnahme und Messung.

    .venv\\Scripts\\python.exe tools\\rennen_probe.py gp --sekunden 20 --bilder ordner

Baut ``RaceState`` genau wie das Spiel (mit Ladebildschirm), lässt das Feld
fahren, speichert Bildschirmfotos und misst die Zeit je Bild. Der Mensch
bleibt am Start stehen; die KI fährt davon und durchs Bild.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "tests"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("strecke", nargs="?", default="gp")
    ap.add_argument("--sekunden", type=float, default=15.0)
    ap.add_argument("--bilder", default="")
    ap.add_argument("--feld", type=int, default=8)
    ap.add_argument("--aufloesung", default="1920x1080")
    ap.add_argument("--stufe", default="",
                    help="Grafikstufe erzwingen (niedrig, mittel, hoch, ultra); sonst die aus dem Profil")
    ap.add_argument("--setzen", action="append", default=[],
                    help="Einzelwert nach der Stufe, z. B. --setzen ssao=0 (mehrfach)")
    args = ap.parse_args()

    import numpy as np
    import pygame
    from src.core import display, sfx
    sfx.mixer_vorbereiten()
    pygame.init()
    display.apply_settings(resolution=args.aufloesung, fullscreen=False)
    if args.stufe:
        from src.render3d import grafik
        display.kontext()            # wendet erst das Profil an ...
        grafik.stufe_setzen(args.stufe)  # ... dann gilt, was hier verlangt ist
    if args.setzen:
        import json as _json
        from src.render3d import grafik
        display.kontext()
        werte = {}
        for eintrag in args.setzen:
            feld, _, roh = eintrag.partition("=")
            try:
                werte[feld] = _json.loads(roh)
            except ValueError:
                werte[feld] = roh
        grafik.setzen(**werte)

    import spielhilfe
    t0 = time.perf_counter()
    rennen, _sm = spielhilfe.rennen_bauen(args.strecke, feld=args.feld, runden=3)
    print(f"Aufbau mit Laden: {time.perf_counter() - t0:.2f} s, "
          f"Szene: {'ja' if rennen.szene is not None else 'NEIN'}")

    ordner = Path(args.bilder) if args.bilder else None
    if ordner:
        ordner.mkdir(parents=True, exist_ok=True)
    uhr = pygame.time.Clock()
    zeiten = []
    fotos = {1.0: "start", args.sekunden * 0.5: "mitte", args.sekunden - 0.1: "ende"}
    t = 0.0
    while t < args.sekunden:
        dt = min(uhr.tick(0) / 1000.0, 0.05)
        t += dt
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                t = args.sekunden
        a = time.perf_counter()
        rennen.update(dt)
        display.bild_beginnen()
        rennen.render(display.virtual_surface())
        display.bild_abschliessen()
        zeiten.append(time.perf_counter() - a)
        for zeitpunkt, name in list(fotos.items()):
            if t >= zeitpunkt and ordner:
                ctx = display.kontext()
                b, h = display.current_win_size()
                roh = ctx.screen.read(viewport=(0, 0, b, h), components=3)
                from PIL import Image
                Image.frombytes("RGB", (b, h), roh).transpose(Image.FLIP_TOP_BOTTOM).save(
                    ordner / f"{args.strecke}_{name}.png")
                del fotos[zeitpunkt]
    z = np.array(zeiten[30:]) * 1000
    from src.render3d import grafik
    print(f"{args.strecke} ({grafik.aktuell().stufe}): {len(zeiten)} Bilder, Median {np.median(z):.1f} ms, "
          f"95. Perzentil {np.percentile(z, 95):.1f} ms, Zustand {rennen.race_manager.state}")
    spielhilfe.alles_schliessen()
    pygame.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
