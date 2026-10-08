"""Die Ideallinie als Band auf dem Asphalt (Fahrhilfe, Plan 1.1.0).

Bekommt nur Zahlen: Punkte der Linie in Metern, den Weg entlang der Linie und
eine Farbe je Punkt (``src/ai/ideallinie.py`` rechnet sie aus dem Zieltempo der
KI). Gebaut wird **einmal** ein Band aus Dreiecken, ein Vertexpuffer, ein
Aufruf je Bild.

* **Kein Z-Fighting:** das Band liegt ``HOEHE_M`` über dem Boden, schreibt keine
  Tiefe und ist wie die Reifenspuren per ``polygon_offset`` zur Kamera
  verschoben. Die Linie bleibt in der Fahrbahn (die KI hält Wandabstand), also
  auch von den Randsteinen weg.
* **Pfeile statt Vollfläche:** der Shader zeichnet Winkel in Fahrtrichtung über
  einem schwach getönten Band; die Pfeile laufen langsam mit (``zeit``), so
  liest man die Richtung auch im Stehen.
* **Billig:** wenige tausend Eckpunkte, einfacher Fragment-Shader; weit weg und
  ganz nah an der Kamera blendet das Band aus.
"""
from __future__ import annotations

import numpy as np

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Breite des Bandes (m) und Höhe über der Fahrbahn.
BREITE_M = 0.9
HOEHE_M = 0.02
#: Länge eines Pfeils (m) und Geschwindigkeit, mit der sie laufen (m/s).
PFEIL_M = 3.2
PFEIL_TEMPO = 5.0
#: Sichtweite: bis hierher voll, bis hier ganz ausgeblendet (m); nahe Kamera.
FERN_VOLL_M = 90.0
FERN_AUS_M = 230.0
NAH_AUS_M = 1.5
NAH_VOLL_M = 5.0

_VERTEX = """
#version 330
uniform mat4 mvp;
in vec3 in_position;
in vec3 in_farbe;
in vec2 in_uv;               // Weg entlang der Linie (m), Quer -1..1
out vec3 farbe;
out vec2 uv;
out vec2 welt_xy;
void main() {
    farbe = in_farbe;
    uv = in_uv;
    welt_xy = in_position.xy;
    gl_Position = mvp * vec4(in_position, 1.0);
}
"""

_FRAGMENT = """
#version 330
uniform vec3 kamera_position;
uniform float zeit;
uniform float pfeil_m;
uniform float pfeil_tempo;
uniform vec4 sicht;          // fern_voll, fern_aus, nah_aus, nah_voll
in vec3 farbe;
in vec2 uv;
in vec2 welt_xy;
out vec4 ausgabe;
void main() {
    float q = abs(uv.y);
    float rand = 1.0 - smoothstep(0.62, 1.0, q);
    // Winkel (V) in Fahrtrichtung: die Spitze in der Mitte liegt weiter vorn.
    float f = fract((uv.x + q * 0.9 - zeit * pfeil_tempo) / pfeil_m);
    float pfeil = smoothstep(0.0, 0.06, f) * (1.0 - smoothstep(0.34, 0.42, f));
    float abstand = distance(welt_xy, kamera_position.xy);
    float fern = 1.0 - smoothstep(sicht.x, sicht.y, abstand);
    float nah = smoothstep(sicht.z, sicht.w, abstand);
    float a = (0.24 + 0.66 * pfeil) * rand * fern * nah;
    if (a < 0.004) discard;
    // Etwas über 1: ein leichtes Leuchten im HDR, ohne zu blenden.
    ausgabe = vec4(farbe * (1.0 + 0.2 * pfeil), a);
}
"""


def band_bauen(xy_m: np.ndarray, bogen_m: np.ndarray, farben: np.ndarray,
               laenge_m: float, breite_m: float = BREITE_M,
               hoehe_m: float = HOEHE_M) -> tuple[np.ndarray, np.ndarray]:
    """Eckpunkte und Indizes eines geschlossenen Bandes um die Linie.

    Rückgabe: ``(daten, indizes)`` — ``daten`` hat je Eckpunkt acht Werte
    ``x y z r g b u q``, ``indizes`` sind Dreiecke. Der Ring wird mit einem
    zusätzlichen Paar am Ende geschlossen, damit der Weg ``u`` an der Naht
    nicht zurückspringt.
    """
    p = np.asarray(xy_m, dtype=np.float64)
    n = len(p)
    t = np.roll(p, -1, axis=0) - np.roll(p, 1, axis=0)
    t /= np.maximum(np.hypot(t[:, 0], t[:, 1]), 1e-9)[:, None]
    nrm = np.stack([-t[:, 1], t[:, 0]], axis=1)
    halb = 0.5 * float(breite_m)
    links = p + nrm * halb
    rechts = p - nrm * halb
    # Farben leicht verschleifen, damit Übergänge weich statt gestuft sind.
    f = np.asarray(farben, dtype=np.float64)
    f = (np.roll(f, 1, axis=0) + 2.0 * f + np.roll(f, -1, axis=0)) / 4.0

    def ring(a: np.ndarray) -> np.ndarray:           # n -> n + 1 (Naht)
        return np.concatenate([a, a[:1]], axis=0)

    u = np.concatenate([np.asarray(bogen_m, dtype=np.float64), [float(laenge_m)]])
    links, rechts, f = ring(links), ring(rechts), ring(f)
    daten = np.zeros(((n + 1) * 2, 8), dtype=np.float32)
    daten[0::2, 0:2] = links
    daten[1::2, 0:2] = rechts
    daten[:, 2] = hoehe_m
    daten[0::2, 3:6] = f
    daten[1::2, 3:6] = f
    daten[0::2, 6] = u
    daten[1::2, 6] = u
    daten[0::2, 7] = 1.0
    daten[1::2, 7] = -1.0
    k = np.arange(n, dtype=np.uint32) * 2
    indizes = np.stack([k, k + 1, k + 2, k + 2, k + 1, k + 3], axis=1).astype(np.uint32).ravel()
    return daten, indizes


class Ideallinie3D:
    """Das Band im Speicher der Grafikkarte; ``zeichnen`` malt es in die Welt."""

    def __init__(self, ctx, linie) -> None:
        self.ctx = ctx
        self.linie = linie
        daten, indizes = band_bauen(linie.xy_m, linie.bogen_m, linie.farben, linie.laenge_m)
        self.programm = ctx.program(vertex_shader=_VERTEX, fragment_shader=_FRAGMENT)
        self._vbo = ctx.buffer(daten.tobytes())
        self._ibo = ctx.buffer(indizes.tobytes())
        self.vao = ctx.vertex_array(
            self.programm, [(self._vbo, "3f 3f 2f", "in_position", "in_farbe", "in_uv")], self._ibo)
        self._anzahl = len(indizes)
        self.programm["pfeil_m"].value = PFEIL_M
        self.programm["pfeil_tempo"].value = PFEIL_TEMPO
        self.programm["sicht"].value = (FERN_VOLL_M, FERN_AUS_M, NAH_AUS_M, NAH_VOLL_M)

    def zeichnen(self, mvp, kamera_position, zeit: float) -> None:
        ctx = self.ctx
        p = self.programm
        p["mvp"].write(np.asarray(mvp, dtype="f4").T.tobytes())
        p["kamera_position"].value = tuple(float(w) for w in kamera_position[:3])
        p["zeit"].value = float(zeit) % 1000.0
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.depth_mask = False
        ctx.polygon_offset = (-1.0, -4.0)
        self.vao.render(vertices=self._anzahl)
        ctx.polygon_offset = (0.0, 0.0)
        ctx.depth_mask = True
        ctx.disable(moderngl.BLEND)

    def freigeben(self) -> None:
        for ding in (self.vao, self._vbo, self._ibo, self.programm):
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
