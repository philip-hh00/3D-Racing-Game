"""Regen und Gischt: Streifen um die Kamera und Nebel hinter den Autos.

Beides ist bewusst billig und wird erst in das aufgelöste HDR-Bild gezeichnet
(wie der Reifenrauch in ``reifenspuren.py``): dort liegt die Tiefe als Textur,
und alles blendet vor Boden, Autos und Bäumen weg, statt hineinzuschneiden.

**Regenstreifen** entstehen komplett auf der Grafikkarte. Je Tropfen gibt es
nur vier Zufallszahlen in einem festen Puffer; der Vertex-Shader legt ihn in
eine Kiste um die Kamera, lässt ihn mit der Fallgeschwindigkeit sinken und
faltet ihn zurück in die Kiste (``mod``). Die Tropfen stehen dadurch in der
**Welt**, nicht an der Kamera: fährt man schnell, ziehen sie am Bild vorbei. Der
Strich ist die Bahn des Tropfens relativ zur Kamera — ``Tropfen − Kamera``
mal einer kurzen Belichtungszeit — und liegt deshalb von selbst in
Fahrtrichtung. Nachts leuchten Streifen im Kegel eines Scheinwerfers auf
(dieselben Lichter wie im Weltshader).

**Gischt** sind weiche Billboards hinter den Rädern, auf der CPU bewegt (ein
paar hundert Teilchen), mit demselben Shader wie der Reifenrauch. Sie
entstehen ab etwa 25 km/h und je schneller, desto mehr.

Wieviel gezeichnet wird, sagen ``grafik.regen_tropfen`` und
``grafik.gischt_teilchen``.
"""
from __future__ import annotations

import math

import numpy as np

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

from . import reifenspuren, shader

#: Kantenlänge der Kiste um die Kamera, Meter (x, y, z). Die Kamera sitzt in der
#: Mitte, nach oben ist mehr Platz (Tropfen fallen von oben ein).
KISTE_M = (26.0, 26.0, 18.0)
#: Belichtungszeit der Streifen, Sekunden: der Strich ist so lang, wie der
#: Tropfen relativ zur Kamera in dieser Zeit kommt.
STRICH_S = 0.022
#: Kürzester und längster Strich, Meter. Stehend wären es nur 20 cm (9 m/s mal
#: die Belichtungszeit) — zu kurz, um als Regen zu wirken.
STRICH_MIN_M = 0.55
STRICH_MAX_M = 3.0
#: Breite eines Streifens in Bildpunkten (bei 1080 Zeilen).
STRICH_BREITE_PX = 1.5
#: Höchstzahl der Gischtteilchen, für die Puffer; ``grafik.gischt_teilchen`` begrenzt sie.
GISCHT_PUFFER = 1600

#: Gischt: Mindesttempo (m/s), Teilchen je Sekunde und Rad bei Volltempo, Reichweite
#: (m) um die Kamera, in der noch Gischt entsteht.
GISCHT_AB_M_S = 7.0
GISCHT_RATE = 46.0
GISCHT_REICHWEITE_M = 90.0

_STRICH_VERTEX = """
#version 330
uniform mat4 vp;               // Welt relativ zur Kamera -> Clip
uniform vec3 kamera_position;
uniform vec3 kiste;
uniform vec3 fall;             // Tropfengeschwindigkeit, Welt (m/s)
uniform vec3 kamera_v;         // Kamerageschwindigkeit, Welt (m/s)
uniform float zeit;
uniform float strich_s;
uniform float strich_max;
uniform float strich_min;
uniform float breite_px;
uniform vec2 pixel_ndc;        // 2 / Breite, 2 / Hoehe
in vec2 in_ecke;               // x: 0 Kopf, 1 Schwanz; y: quer -1 .. 1
in vec4 in_samen;
out vec2 ecke;
out float helle;
out float rand;
out vec3 rel_pos;
void main() {
    vec3 v = fall * (0.85 + 0.3 * in_samen.w);
    vec3 b = in_samen.xyz * kiste;
    vec3 p = b + v * zeit;
    vec3 voll = mod(p - kamera_position, kiste);
    vec3 rel = voll - vec3(0.5 * kiste.xy, 0.3 * kiste.z);
    vec3 d = (v - kamera_v) * strich_s;
    float laenge = length(d);
    vec3 richtung3 = laenge > 1.0e-4 ? d / laenge : vec3(0.0, 0.0, -1.0);
    d = richtung3 * clamp(laenge, strich_min, strich_max);
    vec3 schwanz = rel - d;
    vec4 c0 = vp * vec4(rel, 1.0);
    vec4 c1 = vp * vec4(schwanz, 1.0);
    float nah = 0.15;
    ecke = in_ecke;
    helle = 0.45 + 0.55 * fract(in_samen.w * 7.13 + in_samen.x * 3.7);
    rel_pos = rel;
    vec2 q = abs(rel.xy) / (0.5 * kiste.xy);
    float z_rand = min(voll.z / (0.15 * kiste.z), (kiste.z - voll.z) / (0.15 * kiste.z));
    rand = clamp(min(1.0 - max(q.x, q.y), z_rand) * 5.0, 0.0, 1.0);
    if (c0.w < nah && c1.w < nah) { gl_Position = vec4(0.0, 0.0, 2.0, 1.0); return; }
    if (c0.w < nah) c0 = mix(c0, c1, (nah - c0.w) / (c1.w - c0.w));
    if (c1.w < nah) c1 = mix(c1, c0, (nah - c1.w) / (c0.w - c1.w));
    vec2 n0 = c0.xy / c0.w;
    vec2 n1 = c1.xy / c1.w;
    vec2 dp = (n1 - n0) / pixel_ndc;
    float lp = length(dp);
    vec2 richt = lp > 1.0e-3 ? dp / lp : vec2(0.0, 1.0);
    float dist = max(length(rel), 0.5);
    float breit = breite_px * clamp(5.0 / dist, 0.75, 1.7);
    vec2 quer = vec2(-richt.y, richt.x) * pixel_ndc * breit * 0.5;
    vec4 c = in_ecke.x < 0.5 ? c0 : c1;
    vec2 n = c.xy / c.w + quer * in_ecke.y + richt * pixel_ndc * 0.5 * (in_ecke.x * 2.0 - 1.0);
    gl_Position = vec4(n * c.w, c.z, c.w);
}
"""

_STRICH_FRAGMENT = """
#version 330
#define MAX_LICHTER @MAX_LICHTER@
uniform vec3 farbe;
uniform float deckkraft;
uniform vec3 kamera_position;
uniform int  lichter_anzahl;
uniform vec4 lichter_pos[MAX_LICHTER];
uniform vec4 lichter_farbe[MAX_LICHTER];
uniform vec4 lichter_richtung[MAX_LICHTER];
in vec2 ecke;
in float helle;
in float rand;
in vec3 rel_pos;
out vec4 ausgabe;
void main() {
    float quer = 1.0 - abs(ecke.y);
    float laengs = 1.0 - 0.85 * ecke.x;
    // Nah an der Kamera (im Cockpit: innerhalb der Scheibe) gibt es keine Streifen.
    float nah = smoothstep(1.0, 2.2, length(rel_pos));
    float a = deckkraft * helle * rand * quer * laengs * nah;
    vec3 f = farbe;
    if (lichter_anzahl > 0) {
        vec3 wp = kamera_position + rel_pos;
        vec3 lampe = vec3(0.0);
        for (int i = 0; i < lichter_anzahl; i++) {
            vec4 lp = lichter_pos[i];
            vec3 dl = lp.xyz - wp;
            float d2 = dot(dl, dl);
            if (d2 > lp.w * lp.w) continue;
            float dist = sqrt(d2);
            vec3 Lv = dl / max(dist, 1e-4);
            vec4 ld = lichter_richtung[i];
            float kegel = 1.0;
            if (ld.w < 1.5) {
                kegel = smoothstep(ld.w, lichter_farbe[i].w, dot(-Lv, ld.xyz));
                if (kegel <= 0.0) continue;
            }
            float r = dist / lp.w;
            float fenster = clamp(1.0 - r * r * r * r, 0.0, 1.0);
            lampe += lichter_farbe[i].rgb * (fenster * fenster * kegel / (d2 + 16.0));
        }
        f += lampe * 0.3;
        a *= 0.7 + 1.2 * clamp(dot(lampe, vec3(0.33)), 0.0, 1.0);
    }
    a = clamp(a, 0.0, 0.9);
    if (a < 0.004) discard;
    ausgabe = vec4(f, a);
}
"""


#: Wie der Reifenrauch (``reifenspuren._RAUCH_FRAGMENT``), dazu: nah an der Kamera
#: blendet jedes Teilchen aus — sonst verdeckt die Gischt des eigenen Autos
#: die Strecke direkt vor der Verfolgerkamera.
_GISCHT_FRAGMENT = """
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
    float form = 1.0 - smoothstep(0.0, 1.0, r);
    form *= form;
    float wolke = 0.65 + 0.35 * sin(ecke.x * 4.3 + keim * 6.28) * sin(ecke.y * 3.7 + keim * 11.0);
    vec2 uv = gl_FragCoord.xy / groesse;
    float d = textureLod(tiefe, uv, 0.0).r;
    float szene = 1.0e5;
    if (d < 1.0) {
        vec4 p = inv_vp * vec4(uv * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
        szene = length(p.xyz / p.w);
    }
    float weich = clamp((szene - eigener_abstand) / 0.8, 0.0, 1.0);
    float nah = smoothstep(2.0, 7.0, eigener_abstand);
    float a = deckkraft * form * wolke * weich * nah;
    if (a < 0.002) discard;
    ausgabe = vec4(farbe, a);
}
"""


class Regen:
    """Regenstreifen und Gischt einer Szene."""

    def __init__(self, ctx, wetter, tropfen: int = 3600, gischt: int = GISCHT_PUFFER) -> None:
        self.ctx = ctx
        self.wetter = wetter
        self.zeit = 0.0
        self.max_tropfen = int(tropfen)
        rng = np.random.default_rng(23)
        samen = rng.random((self.max_tropfen, 4)).astype("f4")
        self._samen = ctx.buffer(samen.tobytes())
        quelle = _STRICH_FRAGMENT.replace("@MAX_LICHTER@", str(shader.MAX_LICHTER))
        self.p_strich = ctx.program(vertex_shader=_STRICH_VERTEX, fragment_shader=quelle)
        ecken = np.array([[0, -1], [0, 1], [1, -1], [1, 1]], dtype="f4")
        self._ecken = ctx.buffer(ecken.tobytes())
        self.vao_strich = ctx.vertex_array(self.p_strich, [
            (self._ecken, "2f", "in_ecke"),
            (self._samen, "4f/i", "in_samen"),
        ])
        for name, wert in (("lichter_anzahl", 0),):
            try:
                self.p_strich[name].value = wert
            except KeyError:                       # pragma: no cover - wegoptimiert
                pass
        self._lichter_anzahl = 0
        self._kamera_alt: dict = {}            # Ausschnitt -> (Zeit, Position)
        self._kamera_v = np.zeros(3)

        # Gischt: derselbe Shader wie der Reifenrauch, eigene Teilchen.
        self.p_gischt = ctx.program(vertex_shader=reifenspuren._RAUCH_VERTEX,
                                    fragment_shader=_GISCHT_FRAGMENT)
        n = int(gischt)
        self.kapazitaet = n
        self.limit = n
        self.t_pos = np.zeros((n, 3), np.float32)
        self.t_v = np.zeros((n, 3), np.float32)
        self.t_alter = np.full(n, 1e9, np.float32)
        self.t_leben = np.ones(n, np.float32)
        self.t_groesse = np.ones(n, np.float32)
        self.t_deck = np.zeros(n, np.float32)
        self.t_keim = np.random.default_rng(5).random(n).astype(np.float32)
        self._kopf = 0
        self._rng = np.random.default_rng(17)
        self._guthaben: dict = {}
        self._letzte_pos: dict = {}
        self._fokus = None
        self._ecken_b = ctx.buffer(np.array([[-1, -1], [1, -1], [-1, 1], [1, 1]], dtype="f4").tobytes())
        self._inst = ctx.buffer(reserve=n * 6 * 4)
        self.vao_gischt = ctx.vertex_array(self.p_gischt, [
            (self._ecken_b, "2f", "in_ecke"),
            (self._inst, "4f 2f/i", "in_teilchen", "in_werte"),
        ])
        #: Farben (linear, HDR): ``rennszene`` setzt sie aus Dunst und Himmel.
        self.regen_farbe = (0.5, 0.52, 0.58)
        self.gischt_farbe = (0.55, 0.58, 0.62)

    # -- Licht (Nacht) -------------------------------------------------------
    def lichter_setzen(self, pos, farbe, richtung, anzahl: int) -> None:
        """Die Lichter dieses Bildes (wie im Weltshader) für die Streifen."""
        self._lichter_anzahl = int(anzahl)
        p = self.p_strich
        shader.setzen(p, "lichter_anzahl", int(anzahl))
        if anzahl:
            shader.feld_setzen(p, "lichter_pos", pos)
            shader.feld_setzen(p, "lichter_farbe", farbe)
            shader.feld_setzen(p, "lichter_richtung", richtung)

    # -- Fortschreiben (Gischt) ------------------------------------------------
    def fortschreiben(self, staende, raeder_von, dt: float, limit: int | None = None) -> None:
        """Zeit weiter, neue Gischt hinter schnellen Autos, Teilchen bewegen."""
        dt = min(max(float(dt or 0.0), 0.0), 0.1)
        self.zeit += dt
        if limit is not None and int(limit) != self.limit:
            self.limit = max(0, min(self.kapazitaet, int(limit)))
            self.t_alter[self.limit:] = 1e9
            if self._kopf >= max(self.limit, 1):
                self._kopf = 0
        gesehen = set()
        for stand in staende:
            if getattr(stand, "entfaerbt", False):
                continue
            kennung = stand.kennung
            gesehen.add(kennung)
            pos = np.asarray(stand.pos_m, dtype=np.float64)
            alt = self._letzte_pos.get(kennung)
            v = np.zeros(3)
            if alt is not None and dt > 0.0 and np.linalg.norm(pos[:2] - alt[:2]) < reifenspuren.SPRUNG_M:
                v = (pos - alt) / dt
            self._letzte_pos[kennung] = pos.copy()
            tempo = float(np.hypot(v[0], v[1]))
            if tempo < GISCHT_AB_M_S or dt <= 0.0 or self.limit <= 0:
                continue
            if self._fokus is not None and float(np.hypot(*(pos[:2] - self._fokus[:2]))) > GISCHT_REICHWEITE_M:
                continue
            c, s = math.cos(stand.gierwinkel_rad), math.sin(stand.gierwinkel_rad)
            for i, (rx, ry, hinten) in enumerate(raeder_von(stand)):
                rad = np.array([pos[0] + c * rx - s * ry, pos[1] + s * rx + c * ry, pos[2] + 0.12])
                self._ausstossen((kennung, i), rad, v, tempo, (c, s), math.copysign(1.0, ry), hinten, dt)
        for kennung in [k for k in self._letzte_pos if k not in gesehen]:
            del self._letzte_pos[kennung]
        for schluessel in [k for k in self._guthaben if k[0] not in gesehen]:
            del self._guthaben[schluessel]
        self._bewegen(dt)

    def _ausstossen(self, schluessel, rad, v, tempo, gier, seite, hinten, dt) -> None:
        voll = min(1.0, (tempo - GISCHT_AB_M_S) / 26.0)
        rate = GISCHT_RATE * voll * (1.0 if hinten else 0.35) * self.wetter.gischt
        guthaben = self._guthaben.get(schluessel, 0.0) + rate * dt
        anzahl = int(guthaben)
        self._guthaben[schluessel] = guthaben - anzahl
        if anzahl <= 0:
            return
        c, s = gier
        vor = np.array([c, s, 0.0])
        quer = np.array([-s, c, 0.0]) * seite
        for _ in range(anzahl):
            i = self._kopf
            self._kopf = (self._kopf + 1) % max(self.limit, 1)
            z = self._rng.random(5)
            self.t_pos[i] = rad + vor * (z[4] - 0.5) * 0.3
            self.t_v[i] = (v * 0.2 - vor * (1.2 + 0.05 * tempo) + quer * (0.3 + z[0] * 1.4)
                           + np.array([0.0, 0.0, 0.7 + z[1] * 1.6 + 0.02 * tempo])).astype(np.float32)
            self.t_alter[i] = 0.0
            self.t_leben[i] = 0.9 + z[2] * 0.9
            self.t_groesse[i] = 0.4 + z[3] * 0.4
            self.t_deck[i] = (0.045 + 0.055 * voll) * (0.7 if not hinten else 1.0) * self.wetter.gischt

    def _bewegen(self, dt: float) -> None:
        if dt <= 0.0:
            return
        lebt = self.t_alter < self.t_leben
        if not lebt.any():
            return
        self.t_alter[lebt] += dt
        self.t_v[lebt] *= math.exp(-1.5 * dt)
        self.t_v[lebt, 2] += 0.12 * dt
        self.t_pos[lebt] += self.t_v[lebt] * dt

    @property
    def teilchen_aktiv(self) -> int:
        return int((self.t_alter < self.t_leben).sum())

    def leeren(self) -> None:
        self.t_alter[:] = 1e9
        self._letzte_pos.clear()
        self._guthaben.clear()

    # -- Zeichnen --------------------------------------------------------------
    def kamera_bewegt(self, schluessel, kamera_position) -> np.ndarray:
        """Geschwindigkeit der Kamera dieses Ausschnitts (aus ihrer Bewegung seit dem letzten Bild)."""
        pos = np.asarray(kamera_position, dtype=np.float64)[:3]
        alt = self._kamera_alt.get(schluessel)
        v = np.zeros(3)
        if alt is not None:
            dt = self.zeit - alt[0]
            if dt > 1e-4 and float(np.linalg.norm(pos - alt[1])) < 12.0:
                v = (pos - alt[1]) / dt
        self._kamera_alt[schluessel] = (self.zeit, pos.copy())
        return v

    def streifen_zeichnen(self, vp_relativ: np.ndarray, kamera_position, groesse, schluessel=0,
                          tropfen: int | None = None) -> None:
        """Die Regenstreifen in den **gerade gebundenen** Zwischenpuffer, mit Tiefentest.

        Aufzurufen nach dem Deckenden und vor dem Glas der Autos: so liegt der
        Regen hinter der Scheibe, und die Tiefe (die das Glas dort schreibt)
        steht ihm nicht im Weg. Schreibt selbst keine Tiefe.
        """
        ctx = self.ctx
        kam = np.asarray(kamera_position, dtype=np.float64)[:3]
        self._fokus = kam
        v_kam = self.kamera_bewegt(schluessel, kam)
        n = self.max_tropfen if tropfen is None else max(0, min(int(tropfen), self.max_tropfen))
        w = self.wetter
        if n <= 0 or w.regen <= 0.0:
            return
        vp = np.asarray(vp_relativ, dtype=np.float64)
        p = self.p_strich
        p["vp"].write(vp.astype("f4").T.tobytes())
        p["kamera_position"].value = tuple(float(c) for c in kam)
        p["kiste"].value = KISTE_M
        p["fall"].value = (float(w.regen_wind_m_s[0]), float(w.regen_wind_m_s[1]), -float(w.regen_fall_m_s))
        p["kamera_v"].value = tuple(float(c) for c in v_kam)
        p["zeit"].value = float(self.zeit % 600.0)
        p["strich_s"].value = STRICH_S
        p["strich_max"].value = STRICH_MAX_M
        p["strich_min"].value = STRICH_MIN_M
        p["breite_px"].value = STRICH_BREITE_PX * max(1.0, groesse[1] / 1080.0)
        p["pixel_ndc"].value = (2.0 / groesse[0], 2.0 / groesse[1])
        p["farbe"].value = tuple(float(c) for c in self.regen_farbe)
        p["deckkraft"].value = 0.42 * float(w.regen)
        # ``ctx.depth_mask`` gibt es in moderngl nicht (es wäre ein stilles
        # Nichts); die Tiefenmaske gehört dem Framebuffer.
        fbo = ctx.fbo
        maske = fbo.depth_mask
        fbo.depth_mask = False
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.vao_strich.render(moderngl.TRIANGLE_STRIP, instances=n)
        ctx.disable(moderngl.BLEND)
        fbo.depth_mask = maske

    def gischt_zeichnen(self, vp_relativ: np.ndarray, kamera_position, tiefe, groesse) -> None:
        """Die Gischt in das aufgelöste HDR-Bild; ``tiefe`` ist dessen Tiefentextur."""
        if self.teilchen_aktiv == 0:
            return
        ctx = self.ctx
        kam = np.asarray(kamera_position, dtype=np.float64)[:3]
        vp = np.asarray(vp_relativ, dtype=np.float64)
        tiefe.use(8)
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._gischt_zeichnen(vp, kam, tiefe, groesse)
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)

    def _gischt_zeichnen(self, vp, kam, tiefe, groesse) -> None:
        lebt = np.nonzero(self.t_alter < self.t_leben)[0]
        if len(lebt) == 0:
            return
        kam32 = kam.astype(np.float32)
        alter = self.t_alter[lebt]
        rest = 1.0 - alter / self.t_leben[lebt]
        deck = self.t_deck[lebt] * np.clip(alter / 0.12, 0.0, 1.0) * rest ** 1.2
        groesse_m = self.t_groesse[lebt] + alter * 1.4
        pos = self.t_pos[lebt]
        ordnung = np.argsort(-np.linalg.norm(pos - kam32, axis=1))        # hinten zuerst
        daten = np.empty((len(lebt), 6), np.float32)
        daten[:, :3] = pos[ordnung]
        daten[:, 3] = groesse_m[ordnung]
        daten[:, 4] = deck[ordnung]
        daten[:, 5] = self.t_keim[lebt][ordnung]
        self._inst.write(daten.tobytes())
        rechts = vp[0, :3] / max(np.linalg.norm(vp[0, :3]), 1e-9)
        oben = vp[1, :3] / max(np.linalg.norm(vp[1, :3]), 1e-9)
        p = self.p_gischt
        p["vp"].write(vp.astype("f4").T.tobytes())
        p["inv_vp"].write(np.linalg.inv(vp).astype("f4").T.tobytes())
        p["kamera_position"].value = tuple(float(w) for w in kam32)
        p["rechts"].value = tuple(float(w) for w in rechts)
        p["oben"].value = tuple(float(w) for w in oben)
        p["groesse"].value = (float(groesse[0]), float(groesse[1]))
        p["farbe"].value = tuple(float(c) for c in self.gischt_farbe)
        p["tiefe"].value = 8
        self.vao_gischt.render(moderngl.TRIANGLE_STRIP, instances=len(lebt))

    def freigeben(self) -> None:
        for ding in (self.vao_strich, self.vao_gischt, self._samen, self._ecken, self._ecken_b,
                     self._inst, self.p_strich, self.p_gischt):
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
