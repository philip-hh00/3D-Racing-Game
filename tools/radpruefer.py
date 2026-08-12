"""Radprüfer: Nabe von Hand setzen und die Rundheit ansehen.

    python tools\\radpruefer.py [--fahrzeug rookie]

Die automatische Nabenbestimmung schließt aus einem Netz, in dem Reifen und
Radlauf zusammenhängen — sie trifft die Radmitte nicht immer. Liegt die
Drehachse daneben, **kreist** das Rad beim Rollen, statt sich zu drehen.

Genau das ist hier zu sehen und zu beheben: das ausgewählte Rad dreht sich
ständig, ein weißer Kreis mit dem Sollradius liegt fest um den Ursprung. Läuft
der Reifen ruhig im Kreis, sitzt die Nabe; wandert er, ist sie daneben.

Bedienung
---------
    1 2 3 4     Rad wählen (vl, vr, hl, hr)
    W S         Nabe nach vorne / hinten   (x)
    A D         Nabe nach links / rechts   (y)
    Q E         Nabe nach oben / unten     (z)
    + -         Schrittweite ändern
    R           Drehung anhalten oder weiterlaufen lassen
    Leertaste   Korrektur dieses Rades zurücksetzen
    Strg+S      Alle Korrekturen in trellis_import.json speichern
    Esc         Ende

Gespeichert wird die **Abweichung**, nicht die Nabe selbst — so bleibt eine von
Hand gesetzte Korrektur auch nach einem neuen Import gültig, solange sich das
Modell nicht ändert.
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

import moderngl                                        # noqa: E402

from src.render3d import (ansicht, camera, fenster, matrix, mesh,  # noqa: E402
                          shader, vehicle_node)

RAD_TASTEN = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3}

#: Wie schnell sich das Rad im Prüfstand dreht (Radiant je Sekunde).
DREHRATE = 1.6

#: Schrittweiten in Metern, durchschaltbar mit + und -.
SCHRITTE = (0.001, 0.005, 0.01, 0.02, 0.05)

KREIS_VERTEX = """
#version 330
uniform mat4 mvp;
in vec3 in_position;
void main() { gl_Position = mvp * vec4(in_position, 1.0); }
"""

KREIS_FRAGMENT = """
#version 330
uniform vec3 farbe;
out vec4 ausgabe;
void main() { ausgabe = vec4(farbe, 1.0); }
"""


def _kreis(ctx, programm, radius: float, punkte: int = 256):
    """Ein Sollkreis in der x-z-Ebene um den Ursprung."""
    winkel = np.linspace(0.0, 2.0 * math.pi, punkte, endpoint=True)
    ecken = np.column_stack([radius * np.cos(winkel),
                             np.zeros_like(winkel),
                             radius * np.sin(winkel)]).astype("f4")
    vbo = ctx.buffer(np.ascontiguousarray(ecken).tobytes())
    return ctx.vertex_array(programm, [(vbo, "3f", "in_position")])


def korrekturen_schreiben(pfad: Path, fahrzeug: str,
                          korrekturen: dict[str, np.ndarray]) -> None:
    """Die Abweichungen in ``trellis_import.json`` ablegen.

    Nur was von null verschieden ist — eine Datei voller Nullen sagt nichts
    und macht jede spätere Änderung schwer zu erkennen.
    """
    daten = {}
    if pfad.is_file():
        try:
            daten = json.loads(pfad.read_text(encoding="utf-8"))
        except ValueError:
            daten = {}
    eintrag = daten.setdefault(fahrzeug, {})
    if not isinstance(eintrag, dict):
        eintrag = {}
        daten[fahrzeug] = eintrag
    naben = {name: [round(float(w), 4) for w in wert]
             for name, wert in korrekturen.items() if np.any(np.abs(wert) > 1e-9)}
    if naben:
        eintrag["naben"] = naben
    else:
        eintrag.pop("naben", None)
    pfad.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--fahrzeug", default="rookie")
    a = p.parse_args(argv)

    glb = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}.glb"
    teile_datei = WURZEL / "assets" / "vehicles" / f"{a.fahrzeug}_teile.json"
    config = WURZEL / "trellis_import.json"
    for datei in (glb, teile_datei):
        if not datei.is_file():
            print(f"FEHLER: {datei} fehlt", file=sys.stderr)
            return 2

    pygame.init()
    ctx, hud = fenster.oeffnen(groesse=(1400, 900),
                               titel=f"Radpruefer: {a.fahrzeug}")
    programm = shader.programm(ctx)
    kreisprogramm = ctx.program(vertex_shader=KREIS_VERTEX,
                               fragment_shader=KREIS_FRAGMENT)

    modell = mesh.hochladen(ctx, programm, mesh.laden(glb))
    teile_nach_name = {t.name: t for t in modell.teile}
    knoten = vehicle_node.Fahrzeugknoten.aus_datei(
        teile_datei, korrektur_datei=config, fahrzeug=a.fahrzeug)
    kreis = _kreis(ctx, kreisprogramm, knoten.radradius_m)

    bild = ansicht.Ansicht3D(ctx, fenster.VIRTUELL)
    schrift = pygame.font.SysFont("Consolas", 30)
    fett = pygame.font.SysFont("Consolas", 34, bold=True)

    gewaehlt = 0
    schritt = 2
    dreht = True
    winkel = 0.0
    uhr = pygame.time.Clock()
    laeuft = True

    while laeuft:
        dt = min(uhr.tick(120) / 1000.0, 0.1)
        rad = knoten.raeder[gewaehlt] if knoten.raeder else None

        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                laeuft = False
            elif e.type == pygame.VIDEORESIZE:
                fenster.sichtfeld_anpassen(ctx, (e.w, e.h))
            elif e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    laeuft = False
                elif e.key in RAD_TASTEN and RAD_TASTEN[e.key] < len(knoten.raeder):
                    gewaehlt = RAD_TASTEN[e.key]
                elif e.key == pygame.K_r:
                    dreht = not dreht
                elif e.key in (pygame.K_PLUS, pygame.K_KP_PLUS, pygame.K_EQUALS):
                    schritt = min(schritt + 1, len(SCHRITTE) - 1)
                elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    schritt = max(schritt - 1, 0)
                elif e.key == pygame.K_SPACE and rad is not None:
                    rad.korrektur = np.zeros(3)
                elif e.key == pygame.K_s and (e.mod & pygame.KMOD_CTRL):
                    korrekturen_schreiben(
                        config, a.fahrzeug,
                        {r.name: r.korrektur for r in knoten.raeder})
                    print(f"gespeichert in {config}")

        if rad is not None:
            d = SCHRITTE[schritt]
            tasten = pygame.key.get_pressed()
            richtung = np.array([
                (tasten[pygame.K_w] - tasten[pygame.K_s]) * d,
                (tasten[pygame.K_a] - tasten[pygame.K_d]) * d,
                (tasten[pygame.K_q] - tasten[pygame.K_e]) * d,
            ])
            # Strg+S soll speichern und nicht die Nabe verschieben.
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                richtung[:] = 0.0
            if np.any(richtung):
                rad.korrektur = rad.korrektur + richtung * dt * 12.0

        if dreht:
            winkel += DREHRATE * dt
        knoten.setzen(rollwinkel_rad=winkel)

        # Von der Seite auf das gewaehlte Rad, mit etwas Abstand.
        groesse = pygame.display.get_window_size()
        blickziel = np.zeros(3)
        auge = np.array([0.0, -2.2 if gewaehlt in (1, 3) else 2.2, 0.15])
        P = camera.perspektive(32.0, fenster.seitenverhaeltnis(groesse), 0.05, 60.0)
        mvp = P @ camera.blick(auge, blickziel)

        bild.neues_bild(himmel=(0.10, 0.11, 0.13))
        ctx.enable(moderngl.DEPTH_TEST)

        if rad is not None:
            teil = teile_nach_name.get(rad.name)
            if teil is not None:
                programm["mvp"].write(mvp.T.astype("f4").tobytes())
                programm["kamera_position"].value = tuple(float(w) for w in auge)
                programm["hat_basisfarbe"].value = 1.0 if modell.basisfarbe else 0.0
                programm["hat_metallic_rauheit"].value = (
                    1.0 if modell.metallic_rauheit else 0.0)
                programm["metallic_faktor"].value = 1.0
                programm["rauheit_faktor"].value = 1.0
                if modell.basisfarbe:
                    modell.basisfarbe.use(0)
                if modell.metallic_rauheit:
                    modell.metallic_rauheit.use(1)
                # Nur das Rad, um seinen eigenen Ursprung - ohne Fahrzeug und
                # ohne Nabenversatz, damit der Sollkreis vergleichbar bleibt.
                oertlich = (matrix.verschiebung(rad.korrektur)
                            @ matrix.drehung_y(knoten.rollwinkel_rad)
                            @ matrix.verschiebung(-rad.korrektur))
                shader.modell_setzen(programm, oertlich)
                teil.vao.render()

        # Sollkreis daruebermalen, ohne Tiefentest: er ist eine Schablone,
        # keine Geometrie.
        ctx.disable(moderngl.DEPTH_TEST)
        kreisprogramm["mvp"].write(mvp.T.astype("f4").tobytes())
        kreisprogramm["farbe"].value = (1.0, 1.0, 1.0)
        kreis.render(moderngl.LINE_STRIP)

        hud.fill((0, 0, 0, 0))
        name = rad.name if rad else "kein Rad"
        zeilen = [
            (fett, f"{name}   Sollradius {knoten.radradius_m:.3f} m"),
            (schrift, ""),
            (schrift, "Nabe      x {:+.3f}  y {:+.3f}  z {:+.3f}".format(
                *(rad.nabe if rad is not None else (0, 0, 0)))),
            (schrift, "Korrektur x {:+.3f}  y {:+.3f}  z {:+.3f}".format(
                *(rad.korrektur if rad is not None else (0, 0, 0)))),
            (schrift, f"Schritt   {SCHRITTE[schritt] * 1000:.0f} mm"),
            (schrift, ""),
            (schrift, "1-4 Rad   W/S vor-zurueck   A/D links-rechts   Q/E hoch-runter"),
            (schrift, "+/- Schritt   R Drehung   Leertaste zuruecksetzen"),
            (schrift, "Strg+S speichern   Esc Ende"),
        ]
        for i, (font, text) in enumerate(zeilen):
            if text:
                hud.blit(font.render(text, True, (240, 240, 240)), (40, 40 + i * 42))
        bild.hud_zeichnen(hud)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
