"""Ein Foto der Rennwelt, ohne Spiel und ohne Fenster.

Baut die 3D-Szene einer Strecke genau so auf wie das Rennen (Thema,
Umgebung, Himmel, Schatten, Fahrzeuge in Startaufstellung) und rendert aus
der Verfolgerkamera in eine PNG-Datei. Zum Prüfen von Assets und Licht::

    .venv\\Scripts\\python.exe tools\\szene_foto.py gp --ziel foto.png
    .venv\\Scripts\\python.exe tools\\szene_foto.py desert --fahrzeuge supercar,drifter --abstand 9

Gemessen wird dabei auch die Zeit je Bild (Mittel über 30 Bilder), damit man
sieht, was ein neues Asset kostet.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

from src.core.settings import M_PER_PX  # noqa: E402
from src.render3d import camera, platzierung, rennszene, thema, track_mesh  # noqa: E402

ALLE = ["rookie", "rookie_2", "rookie_3", "limousine", "limousine_2", "limousine_3",
        "supercar", "supercar_2", "supercar_3", "drifter", "drifter_2", "drifter_3",
        "electric", "electric_2", "electric_3"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("strecke")
    ap.add_argument("--ziel", default="szene.png")
    ap.add_argument("--fahrzeuge", default="")
    ap.add_argument("--modelle", default=str(WURZEL / "assets" / "vehicles"))
    ap.add_argument("--breite", type=int, default=1600)
    ap.add_argument("--hoehe", type=int, default=900)
    ap.add_argument("--abstand", type=float, default=7.5)
    ap.add_argument("--kamerahoehe", type=float, default=2.8)
    ap.add_argument("--vorlauf", type=float, default=0.0,
                    help="Meter entlang der Strecke vor dem Startpunkt")
    ap.add_argument("--drehen", type=float, default=0.0,
                    help="Kamera um das Auto drehen, Grad")
    args = ap.parse_args()

    import moderngl
    ctx = moderngl.create_standalone_context()
    strecke = json.loads((WURZEL / "data" / "tracks" / f"{args.strecke}.json").read_text(encoding="utf-8"))
    netz = track_mesh.bauen(strecke)
    th = thema.laden(WURZEL / "data" / "themen", thema.thema_der_strecke(strecke))
    t0 = time.perf_counter()
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
    fahrzeuge = [f for f in args.fahrzeuge.split(",") if f] or ALLE[:8]
    szene = rennszene.Rennszene(
        ctx, netz, args.modelle, thema=th,
        texturordner=WURZEL / "assets" / "texturen", himmelordner=WURZEL / "assets" / "himmel",
        umgebungsordner=WURZEL / "assets" / "umgebung", platzierungen=orte, fahrzeuge=fahrzeuge)
    ladezeit = time.perf_counter() - t0

    starts = strecke.get("start_positions", [])[: len(fahrzeuge)]
    staende = []
    for i, (s, key) in enumerate(zip(starts, fahrzeuge)):
        pos = np.array([s["x"] * M_PER_PX, s["y"] * M_PER_PX, 0.0])
        gier = math.radians(float(s.get("angle", 0.0)))
        pos += np.array([math.cos(gier), math.sin(gier), 0.0]) * args.vorlauf
        staende.append(rennszene.Fahrzeugstand(kennung=i + 1, schluessel=key, pos_m=pos,
                                               gierwinkel_rad=gier))
    szene.fortschreiben(staende)
    erster = staende[0]
    kam = camera.Verfolgerkamera(abstand_m=args.abstand, hoehe_m=args.kamerahoehe, zielhoehe_m=1.0)
    kam.setzen(erster.pos_m, erster.gierwinkel_rad + math.radians(args.drehen))

    fbo = ctx.framebuffer(color_attachments=[ctx.texture((args.breite, args.hoehe), 4, samples=0)],
                          depth_attachment=ctx.depth_renderbuffer((args.breite, args.hoehe)))
    fbo.use()
    ctx.viewport = (0, 0, args.breite, args.hoehe)
    mvp = camera.perspektive(55.0, args.breite / args.hoehe, 0.2, 3200.0) @ kam.blickmatrix()
    zeiten = []
    for _ in range(31):
        fbo.use()
        ctx.clear(0.5, 0.6, 0.8, 1.0, depth=1.0)
        a = time.perf_counter()
        szene.zeichnen(mvp, kam.auge, staende, fokus=kam.ziel)
        ctx.finish()
        zeiten.append(time.perf_counter() - a)
    from PIL import Image
    roh = fbo.read(components=3)
    Image.frombytes("RGB", (args.breite, args.hoehe), roh).transpose(Image.FLIP_TOP_BOTTOM).save(args.ziel)
    print(f"{args.strecke}: {len(orte)} Objekte, Laden {ladezeit:.2f} s, "
          f"Bild {np.median(zeiten[1:]) * 1000:.1f} ms (Median)")
    szene.freigeben()
    return 0


if __name__ == "__main__":
    sys.exit(main())
