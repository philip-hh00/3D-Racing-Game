"""Fahrtest: die echte Physik des Spiels, dargestellt in 3D.

    python tools\\fahrtest.py [--fahrzeug rookie] [--strecke oval]

    W / S     Gas und Bremse
    A / D     Lenken
    Leertaste Handbremse
    R         Zurueck an den Start
    Esc       Ende

Der Unterschied zu ``vorschau3d.py``: dort schiebt sich das Fahrzeug an der
Mittellinie entlang, hier fährt es. Gerechnet wird mit **pymunk und den
unveränderten Fahrzeugdaten des Spiels** — ``VehicleConfig``, ``PlayerVehicle``,
``PhysicsWorld``, dieselben Streckenwände. Nur gezeichnet wird anders.

Das ist der Nachweis für Phase D: die Physik bleibt in 2D, die Darstellung wird
3D, und beides passt über ``M_PER_PX`` zusammen. Geht das hier, geht es auch in
``RaceState``.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pygame

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import moderngl                                        # noqa: E402

from src.core.settings import M_PER_PX                 # noqa: E402
from src.entities.player_vehicle import PlayerVehicle  # noqa: E402
from src.entities.vehicle import VehicleConfig         # noqa: E402
from src.physics.physics_world import PhysicsWorld     # noqa: E402
from src.render3d import (ansicht, camera, fenster, matrix, mesh,  # noqa: E402
                          shader, track_mesh, vehicle_node)
from src.track.track import Track                      # noqa: E402

from vorschau3d import BANDFARBEN, _band_hochladen     # noqa: E402


def welt3d(pos_px) -> np.ndarray:
    """Eine Spielposition in Pixeln als Weltpunkt in Metern.

    pymunk rechnet Y nach oben, die 3D-Welt auch — hier wird also **nicht**
    gespiegelt. Die Spiegelung in ``src/utils/math_utils.py`` gehört zum
    2D-Zeichnen, wo pygame Y nach unten zählt, und hat hier nichts verloren.
    """
    return np.array([pos_px[0] * M_PER_PX, pos_px[1] * M_PER_PX, 0.0])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fahrzeug", default="rookie")
    p.add_argument("--strecke", default="oval")
    a = p.parse_args(argv)

    glb = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}.glb"
    teile_datei = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}_teile.json"
    fahrzeug_json = WURZEL / "data" / "vehicles" / f"{a.fahrzeug}.json"
    strecke_json = WURZEL / "data" / "tracks" / f"{a.strecke}.json"
    for datei in (glb, fahrzeug_json, strecke_json):
        if not datei.is_file():
            print(f"FEHLER: {datei} fehlt", file=sys.stderr)
            return 2

    pygame.init()
    ctx, hud = fenster.oeffnen(titel=f"Fahrtest: {a.fahrzeug} auf {a.strecke}")
    programm = shader.programm(ctx)

    modell = mesh.hochladen(ctx, programm, mesh.laden(glb))
    teile_nach_name = {t.name: t for t in modell.teile}
    netz = track_mesh.aus_datei(strecke_json)
    baender = [(band, _band_hochladen(ctx, programm, band)) for band in netz.baender]
    knoten = (vehicle_node.Fahrzeugknoten.aus_datei(
        teile_datei, korrektur_datei=WURZEL / "trellis_import.json",
        fahrzeug=a.fahrzeug) if teile_datei.is_file() else None)

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

        auto.handle_input()
        welt.step(dt)
        auto.update(dt)

        pos = welt3d(auto.position)
        kamera.folgen(pos, auto.angle, dt)
        if knoten is not None:
            # Der Rollwinkel kommt aus dem tatsaechlich gefahrenen Weg, mit
            # Vorzeichen: rueckwaerts drehen die Raeder rueckwaerts.
            knoten.weg_zuruecklegen(auto.signed_speed * M_PER_PX * dt)
            knoten.lenken(vehicle_node.lenkwinkel_aus_fahrzeug(auto))

        groesse = pygame.display.get_window_size()
        P = camera.perspektive(55.0, fenster.seitenverhaeltnis(groesse), 0.2, 1200.0)
        mvp = P @ kamera.blickmatrix()

        bild.neues_bild(himmel=shader.HIMMEL_HORIZONT)
        programm["mvp"].write(mvp.T.astype("f4").tobytes())
        programm["kamera_position"].value = tuple(float(w) for w in kamera.auge)

        programm["hat_basisfarbe"].value = 0.0
        programm["hat_metallic_rauheit"].value = 0.0
        programm["metallic_faktor"].value = 0.0
        programm["rauheit_faktor"].value = 0.92
        shader.modell_setzen(programm, matrix.einheit())
        for band, vao in baender:
            programm["grundton"].value = BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            vao.render()

        programm["hat_basisfarbe"].value = 1.0 if modell.basisfarbe else 0.0
        programm["hat_metallic_rauheit"].value = 1.0 if modell.metallic_rauheit else 0.0
        programm["metallic_faktor"].value = 1.0
        programm["rauheit_faktor"].value = 1.0
        if modell.basisfarbe:
            modell.basisfarbe.use(0)
        if modell.metallic_rauheit:
            modell.metallic_rauheit.use(1)
        if knoten is not None:
            for name, m in knoten.matrizen(pos, auto.angle).items():
                teil = teile_nach_name.get(name)
                if teil is not None:
                    shader.modell_setzen(programm, m)
                    teil.vao.render()
        else:
            grund = matrix.fahrzeug(pos, auto.angle)
            for teil in modell.teile:
                shader.modell_setzen(programm, grund @ matrix.verschiebung(teil.versatz))
                teil.vao.render()

        hud.fill((0, 0, 0, 0))
        zeilen = [
            f"{auto.speed * M_PER_PX * 3.6:5.0f} km/h",
            f"Gang {getattr(auto.engine, 'gear', 0) + 1}   "
            f"{getattr(auto.engine, 'rpm', 0.0):5.0f} U/min",
            f"Lenkung {math.degrees(auto.physics.steer_angle):+5.1f} Grad",
            f"{uhr.get_fps():5.1f} fps",
            "W/S Gas-Bremse   A/D Lenken   Leertaste Handbremse   R Start   Esc Ende",
        ]
        for i, text in enumerate(zeilen):
            hud.blit(schrift.render(text, True, (255, 255, 255)), (40, 40 + i * 42))
        bild.hud_zeichnen(hud)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
