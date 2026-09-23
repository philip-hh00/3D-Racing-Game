"""Fahrtest: die echte Physik des Spiels, in der ganzen 3D-Welt.

    python tools\\fahrtest.py [--fahrzeug rookie] [--strecke oval] [--lack metallic:kobaltblau]

    W / S     Gas und Bremse
    A / D     Lenken
    Leertaste Handbremse
    R         Zurück an den Start
    L         Nächste Lackierung (Werkslack → Palette → …)
    Esc       Ende

Gerechnet wird mit **pymunk und den unveränderten Fahrzeugdaten des Spiels** —
``VehicleConfig``, ``PlayerVehicle``, ``PhysicsWorld``, dieselben
Streckenwände. Gezeichnet wird mit derselben :class:`Rennszene` wie im
Rennen: Himmel, Schatten, Umgebung des Streckenthemas, Nicken und Wanken.
So lassen sich neue Fahrzeuge und Lackierungen ohne Menü und Rennen prüfen.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pygame

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from src.core import lack                              # noqa: E402
from src.core.settings import M_PER_PX                 # noqa: E402
from src.entities.player_vehicle import PlayerVehicle  # noqa: E402
from src.entities.vehicle import VehicleConfig         # noqa: E402
from src.physics.physics_world import PhysicsWorld     # noqa: E402
from src.render3d import (ansicht, camera, federung, fenster, platzierung,  # noqa: E402
                          rennszene, thema, track_mesh, vehicle_node)
from src.track.track import Track                      # noqa: E402


def welt3d(pos_px) -> np.ndarray:
    """Eine Spielposition in Pixeln als Weltpunkt in Metern (nicht gespiegelt)."""
    return np.array([pos_px[0] * M_PER_PX, pos_px[1] * M_PER_PX, 0.0])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fahrzeug", default="rookie")
    p.add_argument("--strecke", default="oval")
    p.add_argument("--lack", default=lack.WERK)
    a = p.parse_args(argv)

    fahrzeug_json = WURZEL / "data" / "vehicles" / f"{a.fahrzeug}.json"
    strecke_json = WURZEL / "data" / "tracks" / f"{a.strecke}.json"
    for datei in (fahrzeug_json, strecke_json):
        if not datei.is_file():
            print(f"FEHLER: {datei} fehlt", file=sys.stderr)
            return 2

    pygame.init()
    ctx, hud = fenster.oeffnen(titel=f"Fahrtest: {a.fahrzeug} auf {a.strecke}")
    daten = json.loads(strecke_json.read_text(encoding="utf-8"))
    netz = track_mesh.bauen(daten)
    th = thema.laden(WURZEL / "data" / "themen", thema.thema_der_strecke(daten))
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
    szene = rennszene.Rennszene(
        ctx, netz, WURZEL / "assets" / "vehicles", thema=th,
        texturordner=WURZEL / "assets" / "texturen", himmelordner=WURZEL / "assets" / "himmel",
        umgebungsordner=WURZEL / "assets" / "umgebung", platzierungen=orte,
        fahrzeuge=[a.fahrzeug])

    # --- Die Physik des Spiels, unverändert ------------------------------
    welt = PhysicsWorld()
    strecke = Track(str(strecke_json), welt.space)
    config = VehicleConfig.from_json(str(fahrzeug_json))

    def neu_setzen() -> PlayerVehicle:
        start = strecke.start_positions[0]
        return PlayerVehicle(0, config, (start.x, start.y),
                             math.radians(start.angle), welt.space,
                             config_key=a.fahrzeug)

    auto = neu_setzen()
    lacke = [lack.WERK] + [lack.kennung(f["key"], c["key"])
                           for f in lack.finishes() for c in lack.farben_fuer(f["key"])]
    lack_index = lacke.index(a.lack) if a.lack in lacke else 0
    aufhaengung = federung.Aufhaengung()
    v_alt = (0.0, 0.0)

    bild = ansicht.Ansicht3D(ctx, fenster.VIRTUELL)
    kamera = camera.Verfolgerkamera(abstand_m=7.5, hoehe_m=2.8, zielhoehe_m=1.0)
    kamera.setzen(welt3d(auto.position), auto.angle)
    schrift = pygame.font.SysFont("Consolas", 32)

    uhr = pygame.time.Clock()
    laeuft = True
    while laeuft:
        dt = min(uhr.tick(240) / 1000.0, 0.05)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                laeuft = False
            elif e.type == pygame.VIDEORESIZE:
                fenster.sichtfeld_anpassen(ctx, (e.w, e.h))
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    laeuft = False
                elif e.key == pygame.K_r:
                    welt.remove_body(auto.physics.body, auto.physics.shape)
                    auto = neu_setzen()
                    kamera.setzen(welt3d(auto.position), auto.angle)
                elif e.key == pygame.K_l:
                    lack_index = (lack_index + 1) % len(lacke)

        auto.handle_input()
        welt.step(dt)
        auto.update(dt)

        pos = welt3d(auto.position)
        kamera.folgen(pos, auto.angle, dt)
        v = (auto.physics.body.velocity.x * M_PER_PX, auto.physics.body.velocity.y * M_PER_PX)
        laengs, quer = federung.beschleunigung_im_fahrzeug(v, v_alt, auto.angle, dt)
        v_alt = v
        aufhaengung.fortschreiben(laengs, quer, dt)
        stand = rennszene.Fahrzeugstand(
            kennung=1, schluessel=a.fahrzeug, pos_m=pos, gierwinkel_rad=auto.angle,
            weg_m=auto.signed_speed * M_PER_PX * dt,
            lenkwinkel_rad=vehicle_node.lenkwinkel_aus_fahrzeug(auto),
            lack=lack.werte_3d(lacke[lack_index]),
            nick_rad=aufhaengung.nick_rad, wank_rad=aufhaengung.wank_rad)
        szene.fortschreiben([stand])

        groesse = pygame.display.get_window_size()
        P = camera.perspektive(55.0, fenster.seitenverhaeltnis(groesse), 0.2, 3200.0)
        mvp = P @ kamera.blickmatrix()
        bild.neues_bild()
        szene.zeichnen(mvp, kamera.auge, [stand], fokus=kamera.ziel)

        hud.fill((0, 0, 0, 0))
        zeilen = [
            f"{auto.speed * M_PER_PX * 3.6:5.0f} km/h",
            f"Gang {getattr(auto.engine, 'gear', 0) + 1}   "
            f"{getattr(auto.engine, 'rpm', 0.0):5.0f} U/min",
            f"Lack {lack.anzeigename(lacke[lack_index])}",
            f"{uhr.get_fps():5.1f} fps",
            "W/S Gas-Bremse   A/D Lenken   Leertaste Handbremse   R Start   L Lack   Esc Ende",
        ]
        for i, text in enumerate(zeilen):
            hud.blit(schrift.render(text, True, (255, 255, 255)), (40, 40 + i * 42))
        bild.hud_zeichnen(hud)
        pygame.display.flip()

    szene.freigeben()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
