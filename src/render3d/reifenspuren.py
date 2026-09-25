"""Reifenspuren und Reifenrauch.

**Wann ein Reifen rutscht**, entscheidet :func:`reifenschlupf` aus Zahlen,
die das Spiel ohnehin hat: Geschwindigkeit, Gierwinkel, Längsbeschleunigung,
Gas, Bremse, Handbremse, Antriebsart. Das Ergebnis — Schlupf vorn und hinten,
je 0..1 — reist im :class:`~src.render3d.rennszene.Fahrzeugstand` zur Szene.
Die Szene weiß dadurch weiter nichts von Fahrzeugklassen.

**Spuren** sind dunkle Streifen knapp über dem Boden, je Rad ein Band aus
kurzen Vierecken. Alle Bänder liegen in *einem* Ringpuffer fester Größe: das
älteste Stück wird überschrieben, wenn ein neues kommt. Jede Ecke kennt ihre
Entstehungszeit; der Shader blendet danach langsam aus. Gezeichnet wird mit
einem Aufruf, ohne Tiefe zu schreiben und leicht zur Kamera versetzt.

**Rauch** sind weiche Billboards an den rutschenden Rädern, auf der CPU
bewegt (ein paar hundert Teilchen). Gezeichnet wird er nach dem Auflösen der
Kantenglättung in das HDR-Bild: dort liegt die Tiefe als Textur, und jedes
Teilchen blendet vor Boden und Auto weich aus, statt mit harter Kante
hineinzuschneiden.

Ob beides läuft, sagt ``grafik.reifenspuren``.
"""
from __future__ import annotations

import math
import time

import numpy as np

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Breite einer Spur (etwa die Lauffläche) und Länge eines Stücks.
SPUR_BREITE_M = 0.24
SPUR_STUECK_M = 0.4
#: Nach so vielen Sekunden ist eine Spur verschwunden.
SPUR_LEBEN_S = 60.0
#: Plätze im Ringpuffer. Ein Stück ist 40 cm lang: 6000 Stücke sind zwei
#: Kilometer Spur, verteilt auf alle Räder aller Autos.
SPUR_STUECKE = 6000
#: Ab diesem Schlupf zeichnet ein Rad.
SPUR_AB = 0.2
#: Höhe über dem Boden gegen Z-Fighting.
SPUR_HOEHE_M = 0.012
#: Weiter als so springt ein Rad nicht in einem Bild — sonst ist es ein
#: Neustart (Zurücksetzen auf die Strecke), und die Spur beginnt neu.
SPRUNG_M = 6.0

#: Rauch: höchstens so viele Teilchen, ab welchem Schlupf, wie viele je
#: Sekunde und Rad bei vollem Schlupf.
RAUCH_TEILCHEN = 480
RAUCH_AB = 0.4
RAUCH_RATE = 22.0

#: Radplätze, wenn ein Modell keine ``_teile.json`` hat: (x, y, hinten).
ERSATZRAEDER = ((1.35, 0.8, False), (1.35, -0.8, False),
                (-1.35, 0.8, True), (-1.35, -0.8, True))


def _glatt(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def reifenschlupf(geschwindigkeit_m_s, gier_rad: float, laengs_m_s2: float = 0.0,
                  gas: float = 0.0, bremse: float = 0.0, handbremse: bool = False,
                  antrieb: str = "rwd") -> tuple[float, float]:
    """Wie stark die Reifen vorn und hinten rutschen, je 0..1.

    * **Querschlupf** (Drift): der Wagen bewegt sich seitwärts zur
      Blickrichtung. Ab 1,5 m/s quer beginnt es, bei 5 m/s ist es voll.
    * **Blockieren**: Handbremse (hinten) oder eine Bremsung mit mehr als
      rund 0,8 g.
    * **Durchdrehen**: Vollgas aus dem Stand, an der angetriebenen Achse,
      bis etwa 35 km/h auslaufend.
    """
    vx, vy = float(geschwindigkeit_m_s[0]), float(geschwindigkeit_m_s[1])
    tempo = math.hypot(vx, vy)
    c, s = math.cos(gier_rad), math.sin(gier_rad)
    quer = abs(-s * vx + c * vy)
    drift = _glatt(1.5, 5.0, quer) * _glatt(3.0, 8.0, tempo)
    vorn = drift * 0.7
    hinten = drift

    if tempo > 3.0:
        if handbremse:
            hinten = max(hinten, 0.9)
        if bremse > 0.5:
            voll = _glatt(7.5, 11.0, -float(laengs_m_s2))
            vorn = max(vorn, voll)
            hinten = max(hinten, voll * 0.8)

    if gas > 0.85 and tempo < 10.0:
        spin = (1.0 - _glatt(2.0, 10.0, tempo)) * _glatt(0.3, 1.0, tempo + 0.3)
        a = antrieb.lower()
        if a in ("rwd", "awd"):
            hinten = max(hinten, spin * (0.6 if a == "awd" else 0.85))
        if a in ("fwd", "awd"):
            vorn = max(vorn, spin * (0.6 if a == "awd" else 0.85))
    return min(1.0, vorn), min(1.0, hinten)


# ---------------------------------------------------------------------------
# Shader
# ---------------------------------------------------------------------------

_SPUR_VERTEX = """
#version 330
uniform mat4 mvp;
in vec3 in_position;
in vec4 in_daten;          // alpha, geburt, quer (0..1), laengs (m)
out vec4 daten;
void main() {
    daten = in_daten;
    gl_Position = mvp * vec4(in_position, 1.0);
}
"""

_SPUR_FRAGMENT = """
#version 330
uniform float zeit;
uniform float leben;
in vec4 daten;
out vec4 ausgabe;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
void main() {
    float alter = zeit - daten.y;
    float blende = 1.0 - smoothstep(leben * 0.25, leben, alter);
    float q = daten.z;
    float rand = smoothstep(0.0, 0.2, q) * smoothstep(1.0, 0.8, q);
    // Profilrillen quer und etwas Unruhe laengs: Gummi liegt nie gleichmaessig.
    float rillen = 0.8 + 0.2 * sin(q * 38.0);
    float unruhe = 0.75 + 0.25 * hash(vec2(floor(daten.w * 5.0), floor(q * 6.0)));
    float a = clamp(daten.x * blende * rand * rillen * unruhe, 0.0, 1.0);
    if (a < 0.003) discard;
    // Schwarz mit Deckkraft: der Boden darunter wird dunkler, sein Licht
    // (Sonne, Schatten) bleibt erhalten.
    ausgabe = vec4(0.004, 0.0037, 0.0035, a);
}
"""

_RAUCH_VERTEX = """
#version 330
uniform mat4 vp;            // relativ zur Kamera
uniform vec3 kamera_position;
uniform vec3 rechts;
uniform vec3 oben;
in vec2 in_ecke;
in vec4 in_teilchen;         // x, y, z, groesse
in vec2 in_werte;            // deckkraft, keim
out vec2 ecke;
out float deckkraft;
out float keim;
out float eigener_abstand;
void main() {
    ecke = in_ecke;
    deckkraft = in_werte.x;
    keim = in_werte.y;
    vec3 rel = in_teilchen.xyz - kamera_position
             + (rechts * in_ecke.x + oben * in_ecke.y) * in_teilchen.w * 0.5;
    eigener_abstand = length(rel);
    gl_Position = vp * vec4(rel, 1.0);
}
"""

_RAUCH_FRAGMENT = """
#version 330
uniform sampler2D tiefe;
uniform mat4 inv_vp;
uniform vec2 groesse;
uniform vec3 farbe;
in vec2 ecke;
in float deckkraft;
in float keim;
in float eigener_abstand;
out vec4 ausgabe;
void main() {
    float r = length(ecke);
    if (r > 1.0) discard;
    float form = 1.0 - smoothstep(0.15, 1.0, r);
    float wolke = 0.7 + 0.3 * sin(ecke.x * 4.3 + keim * 6.28) * sin(ecke.y * 3.7 + keim * 11.0);
    vec2 uv = gl_FragCoord.xy / groesse;
    float d = textureLod(tiefe, uv, 0.0).r;
    float szene = 1.0e5;
    if (d < 1.0) {
        vec4 p = inv_vp * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
        szene = length(p.xyz / p.w);
    }
    // Weich statt hart: nahe an einer Flaeche blendet das Teilchen aus.
    float weich = clamp((szene - eigener_abstand) / 0.8, 0.0, 1.0);
    float a = deckkraft * form * wolke * weich;
    if (a < 0.002) discard;
    ausgabe = vec4(farbe, a);
}
"""


class Reifenspuren:
    """Spuren im Ringpuffer und Rauchteilchen, für alle Fahrzeuge einer Szene."""

    def __init__(self, ctx, stuecke: int = SPUR_STUECKE, teilchen: int = RAUCH_TEILCHEN) -> None:
        self.ctx = ctx
        self.zeit = 0.0
        self._uhr = None
        self.kapazitaet = int(stuecke)
        self.p_spur = ctx.program(vertex_shader=_SPUR_VERTEX, fragment_shader=_SPUR_FRAGMENT)
        self.p_rauch = ctx.program(vertex_shader=_RAUCH_VERTEX, fragment_shader=_RAUCH_FRAGMENT)
        # Je Stück vier Ecken zu je 7 Zahlen: x y z, alpha geburt quer laengs.
        self._vbo = ctx.buffer(reserve=self.kapazitaet * 4 * 7 * 4)
        self._vbo.write(np.zeros(self.kapazitaet * 4 * 7, dtype="f4").tobytes())
        basis = np.arange(self.kapazitaet, dtype=np.uint32)[:, None] * 4
        indizes = (basis + np.array([0, 1, 2, 2, 1, 3], dtype=np.uint32)).astype("u4")
        self._ibo = ctx.buffer(indizes.tobytes())
        self.vao_spur = ctx.vertex_array(
            self.p_spur, [(self._vbo, "3f 4f", "in_position", "in_daten")], self._ibo)
        self._kopf = 0
        self.belegt = 0
        self._raeder: dict = {}           # (kennung, rad) -> Zustand
        self._letzte_pos: dict = {}       # kennung -> (x, y)

        # Rauch
        self.max_teilchen = int(teilchen)
        n = self.max_teilchen
        self.t_pos = np.zeros((n, 3), np.float32)
        self.t_v = np.zeros((n, 3), np.float32)
        self.t_alter = np.full(n, 1e9, np.float32)
        self.t_leben = np.ones(n, np.float32)
        self.t_groesse = np.ones(n, np.float32)
        self.t_deck = np.zeros(n, np.float32)
        self.t_keim = np.random.default_rng(3).random(n).astype(np.float32)
        self._t_kopf = 0
        self._rng = np.random.default_rng(11)
        self._guthaben: dict = {}
        ecken = np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], dtype="f4")
        self._ecken = ctx.buffer(ecken.tobytes())
        self._inst = ctx.buffer(reserve=n * 6 * 4)
        self.vao_rauch = ctx.vertex_array(self.p_rauch, [
            (self._ecken, "2f", "in_ecke"),
            (self._inst, "4f 2f/i", "in_teilchen", "in_werte"),
        ])
        self.rauch_farbe = (0.9, 0.9, 0.92)

    # -- Fortschreiben ----------------------------------------------------------
    def leeren(self) -> None:
        self._vbo.write(np.zeros(self.kapazitaet * 4 * 7, dtype="f4").tobytes())
        self._kopf = self.belegt = 0
        self._raeder.clear()
        self.t_alter[:] = 1e9

    def fortschreiben(self, staende, raeder_von, dt: float | None = None) -> None:
        """Neue Spurstücke und Rauch aus den Ständen dieses Bildes.

        ``raeder_von(stand)`` liefert die Radplätze des Fahrzeugs als
        ``[(x, y, hinten), …]`` in Fahrzeugkoordinaten.
        """
        if dt is None:
            jetzt = time.perf_counter()
            dt = 0.0 if self._uhr is None else jetzt - self._uhr
            self._uhr = jetzt
        dt = min(max(float(dt), 0.0), 0.1)
        self.zeit += dt
        neu = []
        gesehen = set()
        for stand in staende:
            if getattr(stand, "entfaerbt", False):
                continue
            kennung = stand.kennung
            gesehen.add(kennung)
            vorn = float(getattr(stand, "schlupf_vorn", 0.0) or 0.0)
            hinten = float(getattr(stand, "schlupf_hinten", 0.0) or 0.0)
            pos = np.asarray(stand.pos_m, dtype=np.float64)
            alt = self._letzte_pos.get(kennung)
            v = np.zeros(3)
            if alt is not None and dt > 0 and np.linalg.norm(pos[:2] - alt[:2]) < SPRUNG_M:
                v = (pos - alt) / dt
            self._letzte_pos[kennung] = pos.copy()
            c, s = math.cos(stand.gierwinkel_rad), math.sin(stand.gierwinkel_rad)
            for i, (rx, ry, ist_hinten) in enumerate(raeder_von(stand)):
                w = hinten if ist_hinten else vorn
                rad = np.array([pos[0] + c * rx - s * ry, pos[1] + s * rx + c * ry,
                                pos[2] + SPUR_HOEHE_M])
                self._rad_fortschreiben((kennung, i), rad, w, neu)
                if ist_hinten and w > RAUCH_AB and dt > 0:
                    self._rauch_ausstossen((kennung, i), rad, v, w, dt)
        for schluessel in [k for k in self._raeder if k[0] not in gesehen]:
            del self._raeder[schluessel]
        for kennung in [k for k in self._letzte_pos if k not in gesehen]:
            del self._letzte_pos[kennung]
        if neu:
            self._schreiben(np.asarray(neu, dtype="f4").reshape(-1, 4 * 7))
        self._rauch_bewegen(dt)

    def _rad_fortschreiben(self, schluessel, rad, schlupf, neu) -> None:
        zustand = self._raeder.get(schluessel)
        staerke = 0.0 if schlupf < SPUR_AB else 0.25 + 0.65 * _glatt(SPUR_AB, 0.8, schlupf)
        if zustand is None:
            if staerke > 0.0:
                self._raeder[schluessel] = {"pos": rad, "ecken": None, "alpha": 0.0, "laengs": 0.0}
            return
        weg = rad[:2] - zustand["pos"][:2]
        laenge = float(np.hypot(*weg))
        if laenge > SPRUNG_M:
            del self._raeder[schluessel]
            return
        if laenge < SPUR_STUECK_M and staerke > 0.0:
            return
        if laenge < 0.05:
            if staerke == 0.0:
                del self._raeder[schluessel]
            return
        richtung = weg / laenge
        quer = np.array([-richtung[1], richtung[0], 0.0]) * (SPUR_BREITE_M * 0.5)
        links, rechts = rad + quer, rad - quer
        if zustand["ecken"] is None:
            a_l, a_r = zustand["pos"] + quer, zustand["pos"] - quer
        else:
            a_l, a_r = zustand["ecken"]
        l0, l1 = zustand["laengs"], zustand["laengs"] + laenge
        a0, a1 = zustand["alpha"], staerke
        z = self.zeit
        neu.extend([*a_l, a0, z, 0.0, l0, *a_r, a0, z, 1.0, l0,
                    *links, a1, z, 0.0, l1, *rechts, a1, z, 1.0, l1])
        if staerke == 0.0:
            del self._raeder[schluessel]
            return
        zustand.update(pos=rad, ecken=(links, rechts), alpha=staerke, laengs=l1 % 1000.0)

    def _schreiben(self, stuecke: np.ndarray) -> None:
        stuecke = stuecke[-self.kapazitaet:]
        n = len(stuecke)
        platz = self.kapazitaet - self._kopf
        erst = min(n, platz)
        groesse = 4 * 7 * 4
        self._vbo.write(stuecke[:erst].tobytes(), offset=self._kopf * groesse)
        if n > erst:
            self._vbo.write(stuecke[erst:].tobytes(), offset=0)
        self._kopf = (self._kopf + n) % self.kapazitaet
        self.belegt = min(self.kapazitaet, self.belegt + n)

    def _rauch_ausstossen(self, schluessel, rad, v, schlupf, dt) -> None:
        guthaben = self._guthaben.get(schluessel, 0.0) + RAUCH_RATE * dt * _glatt(RAUCH_AB, 1.0, schlupf)
        anzahl = int(guthaben)
        self._guthaben[schluessel] = guthaben - anzahl
        for _ in range(anzahl):
            i = self._t_kopf
            self._t_kopf = (self._t_kopf + 1) % self.max_teilchen
            zufall = self._rng.random(4)
            self.t_pos[i] = rad + np.array([0.0, 0.0, 0.2])
            self.t_v[i] = (v * 0.15 + np.array([(zufall[0] - 0.5) * 1.6, (zufall[1] - 0.5) * 1.6,
                                                0.4 + zufall[2] * 0.5])).astype(np.float32)
            self.t_alter[i] = 0.0
            self.t_leben[i] = 1.8 + zufall[3] * 1.4
            self.t_groesse[i] = 0.7 + zufall[0] * 0.4
            self.t_deck[i] = 0.16 + 0.22 * _glatt(RAUCH_AB, 1.0, schlupf)

    def _rauch_bewegen(self, dt: float) -> None:
        if dt <= 0.0:
            return
        lebt = self.t_alter < self.t_leben
        if not lebt.any():
            return
        self.t_alter[lebt] += dt
        daempfung = math.exp(-1.6 * dt)
        self.t_v[lebt] *= daempfung
        self.t_v[lebt, 2] += 0.25 * dt
        self.t_pos[lebt] += self.t_v[lebt] * dt

    @property
    def teilchen_aktiv(self) -> int:
        return int((self.t_alter < self.t_leben).sum())

    # -- Zeichnen ---------------------------------------------------------------
    def spuren_zeichnen(self, mvp) -> None:
        if self.belegt == 0:
            return
        ctx = self.ctx
        p = self.p_spur
        p["mvp"].write(np.asarray(mvp, dtype="f4").T.tobytes())
        p["zeit"].value = self.zeit
        p["leben"].value = SPUR_LEBEN_S
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.depth_mask = False
        ctx.polygon_offset = (-1.0, -4.0)
        self.vao_spur.render(vertices=self.belegt * 6)
        ctx.polygon_offset = (0.0, 0.0)
        ctx.depth_mask = True
        ctx.disable(moderngl.BLEND)

    def rauch_zeichnen(self, vp_relativ: np.ndarray, kamera_position, tiefe, groesse) -> None:
        """In das aufgelöste HDR-Bild; ``tiefe`` ist dessen Tiefentextur."""
        lebt = np.nonzero(self.t_alter < self.t_leben)[0]
        if len(lebt) == 0:
            return
        kam = np.asarray(kamera_position, dtype=np.float32)[:3]
        alter = self.t_alter[lebt]
        leben = self.t_leben[lebt]
        rest = 1.0 - alter / leben
        deck = self.t_deck[lebt] * np.clip(alter / 0.15, 0.0, 1.0) * rest ** 1.5
        groesse_m = self.t_groesse[lebt] + alter * 1.3
        pos = self.t_pos[lebt]
        ordnung = np.argsort(-np.linalg.norm(pos - kam, axis=1))    # hinten zuerst
        daten = np.empty((len(lebt), 6), np.float32)
        daten[:, :3] = pos[ordnung]
        daten[:, 3] = groesse_m[ordnung]
        daten[:, 4] = deck[ordnung]
        daten[:, 5] = self.t_keim[lebt][ordnung]
        self._inst.write(daten.tobytes())

        vp = np.asarray(vp_relativ, dtype=np.float64)
        rechts = vp[0, :3] / max(np.linalg.norm(vp[0, :3]), 1e-9)
        oben = vp[1, :3] / max(np.linalg.norm(vp[1, :3]), 1e-9)
        p = self.p_rauch
        p["vp"].write(vp.astype("f4").T.tobytes())
        p["inv_vp"].write(np.linalg.inv(vp).astype("f4").T.tobytes())
        p["kamera_position"].value = tuple(float(w) for w in kam)
        p["rechts"].value = tuple(float(w) for w in rechts)
        p["oben"].value = tuple(float(w) for w in oben)
        p["groesse"].value = (float(groesse[0]), float(groesse[1]))
        p["farbe"].value = tuple(float(c) for c in self.rauch_farbe)
        p["tiefe"].value = 8          # Platz der Nachbearbeitung, siehe dort E0
        tiefe.use(8)
        ctx = self.ctx
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.vao_rauch.render(moderngl.TRIANGLE_STRIP, instances=len(lebt))
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    def freigeben(self) -> None:
        for ding in (self.vao_spur, self.vao_rauch, self._vbo, self._ibo, self._ecken,
                     self._inst, self.p_spur, self.p_rauch):
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
