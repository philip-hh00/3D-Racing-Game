"""Der Schattenfleck unter einem Fahrzeug.

Kein Schattenwurf im Sinne einer Shadow Map — der steht in Phase E1. Was hier
steht, löst ein anderes Problem: **ohne irgendetwas Dunkles unter den Rädern
schweben die Autos.** Bei acht Fahrzeugen auf der Strecke fällt das sofort auf,
weil man die Wagen dann nebeneinander sieht und keiner davon Bodenkontakt zu
haben scheint.

Ein weicher dunkler Fleck kostet vier Eckpunkte je Fahrzeug und behebt genau
diesen Eindruck. Er wird **ohne Tiefenschreiben** gezeichnet: der Fleck ist
kein Körper, und ein Fahrzeug, das über einen fremden Fleck fährt, soll nicht
an dessen Tiefe hängenbleiben.
"""
from __future__ import annotations

import numpy as np

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


#: Wie weit der Fleck über die Fahrzeugmaße hinausragt. Ein Schatten ist
#: breiter als das, was ihn wirft, sobald das Licht nicht senkrecht steht —
#: und ein Fleck, der genau an der Karosseriekante endet, sieht aus wie eine
#: aufgeklebte Matte.
UEBERSTAND = 1.15

#: Wie hoch über der Fahrbahn der Fleck liegt. Genau auf ``z = 0`` kämpft er
#: mit der Fahrbahn um die Tiefe und flackert; zwei Zentimeter sind aus der
#: Verfolgerkamera nicht zu sehen und weit über der float32-Rundung bei
#: Streckenkoordinaten in der Größenordnung von hundert Metern.
HOEHE_M = 0.02

#: Deckkraft in der Mitte des Flecks.
STAERKE = 0.45

VERTEX = """
#version 330
uniform mat4 mvp;
uniform mat4 modell;
in vec3 in_position;
in vec2 in_uv;
out vec2 uv;
void main() {
    uv = in_uv;
    gl_Position = mvp * modell * vec4(in_position, 1.0);
}
"""

FRAGMENT = """
#version 330
uniform float staerke;
in vec2 uv;
out vec4 ausgabe;
void main() {
    // Elliptischer Abfall vom Mittelpunkt nach aussen. Ohne den weichen Rand
    // waere es ein Rechteck auf der Strasse, und das sieht schlimmer aus als
    // gar kein Schatten.
    vec2 d = uv * 2.0 - 1.0;
    float r = length(d);
    ausgabe = vec4(0.0, 0.0, 0.0, staerke * (1.0 - smoothstep(0.35, 1.0, r)));
}
"""


def grundflaeche(laenge_m: float, breite_m: float) -> np.ndarray:
    """Die vier Ecken des Flecks im Fahrzeugkoordinatensystem.

    Mittig um den Fahrzeugursprung, knapp über der Fahrbahn. Reihenfolge als
    Dreiecksstreifen: hinten rechts, hinten links, vorne rechts, vorne links.
    """
    halbe_laenge = float(laenge_m) * UEBERSTAND / 2.0
    halbe_breite = float(breite_m) * UEBERSTAND / 2.0
    return np.array([
        [-halbe_laenge, -halbe_breite, HOEHE_M],
        [-halbe_laenge, +halbe_breite, HOEHE_M],
        [+halbe_laenge, -halbe_breite, HOEHE_M],
        [+halbe_laenge, +halbe_breite, HOEHE_M],
    ], dtype="f4")


#: Texturkoordinaten zu :func:`grundflaeche`, in derselben Reihenfolge.
UV = np.array([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0], [1.0, 1.0]], dtype="f4")


def programm(ctx):
    """Das Schattenprogramm bauen und mit der Vorgabestärke belegen."""
    p = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
    p["staerke"].value = STAERKE
    return p


def flaeche_hochladen(ctx, p, laenge_m: float, breite_m: float):
    """Die vier Ecken als Dreiecksstreifen hochladen."""
    ecken = ctx.buffer(np.ascontiguousarray(grundflaeche(laenge_m, breite_m)))
    uv = ctx.buffer(np.ascontiguousarray(UV))
    return ctx.vertex_array(p, [(ecken, "3f", "in_position"), (uv, "2f", "in_uv")])


class Schattenwerfer:
    """Zeichnet die Flecke aller Fahrzeuge in einem Durchgang.

    Ein eigener Durchgang, weil die Einstellungen für alle gelten: Mischen an,
    Tiefenschreiben aus. Zwischen den Fahrzeugen umzuschalten wäre Aufwand ohne
    Gegenwert.
    """

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.programm = programm(ctx)

    def beginnen(self, mvp: np.ndarray) -> None:
        self.programm["mvp"].write(np.asarray(mvp, dtype="f4").T.tobytes())
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.depth_mask = False

    def zeichnen(self, vao, modell: np.ndarray) -> None:
        self.programm["modell"].write(np.asarray(modell, dtype="f4").T.tobytes())
        vao.render(moderngl.TRIANGLE_STRIP)

    def beenden(self) -> None:
        self.ctx.depth_mask = True
        self.ctx.disable(moderngl.BLEND)

    def freigeben(self) -> None:
        self.programm.release()
