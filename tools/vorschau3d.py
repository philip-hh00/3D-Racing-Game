"""Vorschau: ein Fahrzeug auf einer echten Strecke, Verfolgerkamera, HUD.

    python tools\\vorschau3d.py [--fahrzeug rookie] [--strecke oval]

Der Beweis, dass die Bausteine zusammenpassen: ModernGL zeichnet die Szene in
dasselbe pygame-Fenster, in dem das HUD wie bisher mit ``blit`` und ``draw``
entsteht — nur dass es am Ende als Textur darüberliegt.

**Keine Physik.** Das Fahrzeug folgt der Mittellinie der Strecke; gesteuert
wird nur die Geschwindigkeit. Die Verbindung zu pymunk kommt in Phase D. Was
hier läuft, ist ausschließlich Darstellung.

Der Shader ist bewusst einfach gehalten — ein Richtungslicht, keine
Materialkanäle. Er wird in Phase B3 durch eine PBR-Beleuchtung ersetzt.
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

from src.render3d import ansicht, camera, fenster, mesh, track_mesh  # noqa: E402

VERTEX = """
#version 330
uniform mat4 mvp;
uniform mat4 modell;
in vec3 in_position;
in vec3 in_normale;
in vec2 in_uv;
out vec3 normale;
out vec2 uv;
void main() {
    normale = mat3(modell) * in_normale;
    uv = in_uv;
    gl_Position = mvp * modell * vec4(in_position, 1.0);
}
"""

FRAGMENT = """
#version 330
uniform sampler2D basisfarbe;
uniform vec3 grundton;
uniform float hat_textur;
in vec3 normale;
in vec2 uv;
out vec4 farbe;
void main() {
    vec3 licht = normalize(vec3(0.35, 0.45, 1.0));
    float diffus = max(dot(normalize(normale), licht), 0.0);
    vec3 basis = mix(grundton, texture(basisfarbe, uv).rgb, hat_textur);
    farbe = vec4(basis * (0.38 + 0.62 * diffus), 1.0);
}
"""


def _einheitsmatrix() -> np.ndarray:
    return np.eye(4, dtype="f4")


def _verschiebung(x: float, y: float, z: float) -> np.ndarray:
    m = _einheitsmatrix()
    m[:3, 3] = (x, y, z)
    return m


def _drehung_z(winkel: float) -> np.ndarray:
    m = _einheitsmatrix()
    c, s = math.cos(winkel), math.sin(winkel)
    m[0, 0], m[0, 1] = c, -s
    m[1, 0], m[1, 1] = s, c
    return m


def _band_hochladen(ctx, programm, band) -> "moderngl.VertexArray":
    puffer = [
        (ctx.buffer(np.ascontiguousarray(band.positionen, "f4")), "3f", "in_position"),
        (ctx.buffer(np.ascontiguousarray(band.normalen, "f4")), "3f", "in_normale"),
        (ctx.buffer(np.ascontiguousarray(band.uv, "f4")), "2f", "in_uv"),
    ]
    ibo = ctx.buffer(np.ascontiguousarray(band.indizes, "u4"))
    return ctx.vertex_array(programm, puffer, ibo)


#: Grundtöne der Streckenbänder, solange es keine Texturen gibt.
BANDFARBEN = {
    "fahrbahn": (0.24, 0.24, 0.26),
    "randstein_links": (0.72, 0.20, 0.20),
    "randstein_rechts": (0.72, 0.20, 0.20),
    "untergrund": (0.34, 0.45, 0.24),
}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fahrzeug", default="rookie")
    p.add_argument("--strecke", default="oval")
    a = p.parse_args(argv)

    glb = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}.glb"
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
    programm = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
    programm["basisfarbe"].value = 0

    modell = mesh.hochladen(ctx, programm, mesh.laden(glb))
    netz = track_mesh.aus_datei(strecke_datei)
    baender = [(band, _band_hochladen(ctx, programm, band)) for band in netz.baender]

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
        dt = min(uhr.tick(120) / 1000.0, 0.1)
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

        strecke_pos = (strecke_pos + tempo * dt) % netz.laenge_m
        hier, gier = netz.punkt_bei(strecke_pos)
        kamera.folgen((hier[0], hier[1], 0.0), gier, dt)

        groesse = pygame.display.get_window_size()
        P = camera.perspektive(55.0, fenster.seitenverhaeltnis(groesse), 0.2, 1200.0)
        mvp = P @ kamera.blickmatrix()

        bild.neues_bild()
        programm["mvp"].write(mvp.T.astype("f4").tobytes())

        programm["hat_textur"].value = 0.0
        programm["modell"].write(_einheitsmatrix().T.tobytes())
        for band, vao in baender:
            programm["grundton"].value = BANDFARBEN.get(band.name, (0.5, 0.5, 0.5))
            vao.render()

        programm["hat_textur"].value = 1.0 if modell.basisfarbe else 0.0
        if modell.basisfarbe:
            modell.basisfarbe.use(0)
        grundstellung = _verschiebung(hier[0], hier[1], 0.0) @ _drehung_z(gier)
        for teil in modell.teile:
            m = grundstellung @ _verschiebung(*teil.versatz)
            programm["modell"].write(m.T.astype("f4").tobytes())
            teil.vao.render()

        hud.fill((0, 0, 0, 0))
        for zeile, text in enumerate((
                f"{tempo * 3.6:5.0f} km/h",
                f"{strecke_pos:6.0f} / {netz.laenge_m:.0f} m",
                f"{uhr.get_fps():5.1f} fps",
                "Pfeil hoch/runter: Tempo    Esc: Ende")):
            hud.blit(schrift.render(text, True, (255, 255, 255)), (40, 40 + zeile * 44))
        bild.hud_zeichnen(hud)

        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
