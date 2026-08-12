"""Vorschau: ein Fahrzeug auf einer echten Strecke, Verfolgerkamera, HUD.

    python tools\\vorschau3d.py [--fahrzeug rookie] [--strecke oval]

Der Beweis, dass die Bausteine zusammenpassen: ModernGL zeichnet die Szene in
dasselbe pygame-Fenster, in dem das HUD wie bisher mit ``blit`` und ``draw``
entsteht — nur dass es am Ende als Textur darüberliegt.

**Keine Physik.** Das Fahrzeug folgt der Mittellinie der Strecke; gesteuert
wird nur die Geschwindigkeit. Der Lenkeinschlag wird aus der Krümmung der
Strecke geschätzt, damit die Vorderräder etwas zu tun haben. Die Verbindung zu
pymunk kommt in Phase D. Was hier läuft, ist ausschließlich Darstellung.

Beleuchtet wird mit ``src/render3d/shader.py``: PBR mit Base Color,
Metallic-Roughness und einem Himmel als Umgebung.
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

import moderngl                                       # noqa: E402

from src.render3d import (ansicht, camera, fenster, matrix, mesh,  # noqa: E402
                          shader, track_mesh, vehicle_node)

#: Grundtöne der Streckenbänder, solange es keine Texturen gibt.
BANDFARBEN = {
    "fahrbahn": (0.24, 0.24, 0.26),
    "randstein_links": (0.72, 0.20, 0.20),
    "randstein_rechts": (0.72, 0.20, 0.20),
    "untergrund": (0.34, 0.45, 0.24),
}

#: Wie weit voraus die Krümmung für den geschätzten Lenkeinschlag gemessen
#: wird. Zu kurz und der Einschlag zappelt, zu lang und er kommt zu spät.
VORAUSSCHAU_M = 6.0


def _band_hochladen(ctx, programm, band) -> "moderngl.VertexArray":
    puffer = [
        (ctx.buffer(np.ascontiguousarray(band.positionen, "f4")), "3f", "in_position"),
        (ctx.buffer(np.ascontiguousarray(band.normalen, "f4")), "3f", "in_normale"),
        (ctx.buffer(np.ascontiguousarray(band.uv, "f4")), "2f", "in_uv"),
    ]
    ibo = ctx.buffer(np.ascontiguousarray(band.indizes, "u4"))
    return ctx.vertex_array(programm, puffer, ibo)


def geschaetzter_lenkwinkel(netz, strecke_m: float, radstand_m: float) -> float:
    """Aus der Krümmung der Strecke, nicht aus der Physik.

    Beim Einspurmodell gilt ``tan(einschlag) = radstand / kurvenradius``. Der
    Kurvenradius folgt aus der Richtungsänderung über ein Stück Strecke.
    """
    _, gier_hier = netz.punkt_bei(strecke_m)
    _, gier_dort = netz.punkt_bei(strecke_m + VORAUSSCHAU_M)
    differenz = (gier_dort - gier_hier + math.pi) % (2 * math.pi) - math.pi
    if abs(differenz) < 1e-6:
        return 0.0
    kurvenradius = VORAUSSCHAU_M / differenz
    return math.atan(radstand_m / kurvenradius)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fahrzeug", default="rookie")
    p.add_argument("--strecke", default="oval")
    a = p.parse_args(argv)

    glb = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}.glb"
    teile = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}_teile.json"
    if not glb.is_file():
        print(f"FEHLER: {glb} fehlt.\n"
              f"        Erst erzeugen: python trellis_import.py "
              f"rohdaten\\{a.fahrzeug}.glb --fahrzeug {a.fahrzeug}", file=sys.stderr)
        return 2
    strecke_datei = WURZEL / "data" / "tracks" / f"{a.strecke}.json"
    if not strecke_datei.is_file():
        print(f"FEHLER: {strecke_datei} fehlt", file=sys.stderr)
        return 2

    pygame.init()
    ctx, hud = fenster.oeffnen(titel=f"Vorschau: {a.fahrzeug} auf {a.strecke}")
    programm = shader.programm(ctx)

    modell = mesh.hochladen(ctx, programm, mesh.laden(glb))
    netz = track_mesh.aus_datei(strecke_datei)
    baender = [(band, _band_hochladen(ctx, programm, band)) for band in netz.baender]

    knoten = (vehicle_node.Fahrzeugknoten.aus_datei(
        teile, korrektur_datei=WURZEL / "trellis_import.json",
        fahrzeug=a.fahrzeug) if teile.is_file() else None)
    if knoten is None:
        print(f"HINWEIS: {teile.name} fehlt - die Raeder drehen sich nicht.")
    radstand_m = 2.6
    teile_nach_name = {t.name: t for t in modell.teile}

    bild = ansicht.Ansicht3D(ctx, fenster.VIRTUELL)
    kamera = camera.Verfolgerkamera()
    schrift = pygame.font.SysFont("Consolas", 34)

    strecke_pos = 0.0
    tempo = 25.0                                       # m/s
    uhr = pygame.time.Clock()
    hier, gier = netz.punkt_bei(0.0)
    kamera.setzen((hier[0], hier[1], 0.0), gier)
    laeuft = True

    while laeuft:
        dt = min(uhr.tick(240) / 1000.0, 0.1)
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                laeuft = False
            elif e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                laeuft = False
            elif e.type == pygame.VIDEORESIZE:
                fenster.sichtfeld_anpassen(ctx, (e.w, e.h))

        tasten = pygame.key.get_pressed()
        if tasten[pygame.K_UP]:
            tempo = min(tempo + 30.0 * dt, 90.0)
        if tasten[pygame.K_DOWN]:
            tempo = max(tempo - 40.0 * dt, 0.0)

        weg = tempo * dt
        strecke_pos = (strecke_pos + weg) % netz.laenge_m
        hier, gier = netz.punkt_bei(strecke_pos)
        kamera.folgen((hier[0], hier[1], 0.0), gier, dt)
        if knoten is not None:
            knoten.weg_zuruecklegen(weg)
            knoten.lenken(geschaetzter_lenkwinkel(netz, strecke_pos, radstand_m))

        groesse = pygame.display.get_window_size()
        P = camera.perspektive(55.0, fenster.seitenverhaeltnis(groesse), 0.2, 1200.0)
        mvp = P @ kamera.blickmatrix()

        bild.neues_bild(himmel=shader.HIMMEL_HORIZONT)
        programm["mvp"].write(mvp.T.astype("f4").tobytes())
        programm["kamera_position"].value = tuple(float(w) for w in kamera.auge)

        # Strecke: keine Texturen, dafuer Grundtoene und rauer Belag.
        programm["hat_basisfarbe"].value = 0.0
        programm["hat_metallic_rauheit"].value = 0.0
        programm["metallic_faktor"].value = 0.0
        programm["rauheit_faktor"].value = 0.92
        shader.modell_setzen(programm, matrix.einheit())
        for band, vao in baender:
            programm["grundton"].value = BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            vao.render()

        # Fahrzeug: Basisfarbe und Metallic-Rauheit aus dem Modell.
        programm["hat_basisfarbe"].value = 1.0 if modell.basisfarbe else 0.0
        programm["hat_metallic_rauheit"].value = 1.0 if modell.metallic_rauheit else 0.0
        programm["metallic_faktor"].value = 1.0
        programm["rauheit_faktor"].value = 1.0
        if modell.basisfarbe:
            modell.basisfarbe.use(0)
        if modell.metallic_rauheit:
            modell.metallic_rauheit.use(1)
        if knoten is not None:
            for name, m in knoten.matrizen(hier, gier).items():
                teil = teile_nach_name.get(name)
                if teil is None:
                    continue
                shader.modell_setzen(programm, m)
                teil.vao.render()
        else:
            grund = matrix.fahrzeug(hier, gier)
            for teil in modell.teile:
                shader.modell_setzen(programm, grund @ matrix.verschiebung(teil.versatz))
                teil.vao.render()

        hud.fill((0, 0, 0, 0))
        einschlag = math.degrees(knoten.lenkwinkel_rad) if knoten else 0.0
        for zeile, text in enumerate((
                f"{tempo * 3.6:5.0f} km/h",
                f"{strecke_pos:6.0f} / {netz.laenge_m:.0f} m",
                f"Lenkung {einschlag:+5.1f} Grad",
                f"{uhr.get_fps():5.1f} fps",
                "Pfeil hoch/runter: Tempo    Esc: Ende")):
            hud.blit(schrift.render(text, True, (255, 255, 255)), (40, 40 + zeile * 44))
        bild.hud_zeichnen(hud)

        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
