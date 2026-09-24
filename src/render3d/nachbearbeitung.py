"""Nachbearbeitung: aus dem linearen HDR-Bild der Welt ein fertiges Bild.

Seit Realismus Runde 2 liefern **alle** Programme in ``shader.py`` lineares
HDR — Licht in physikalischen Einheiten, ohne Abbildung auf den Bildschirm.
Die Welt landet deshalb nicht mehr direkt im Fenster, sondern erst in einem
Zwischenpuffer mit Fließkommafarben (RGBA16F) und Tiefentextur. Danach, der
Reihe nach:

1. **Auflösen** der Kantenglättung: bei ``msaa4`` wird mit vier Proben je
   Pixel gezeichnet und hier auf eine Probe zusammengefasst (Farbe und Tiefe).
2. **Umgebungsverdeckung (SSAO)** aus der Tiefe: Ecken, Radkästen und der
   Übergang Auto–Boden werden dunkler. Halbe oder volle Auflösung, danach
   tiefenabhängig weichgezeichnet — so blutet sie nicht über Kanten (Halos).
3. **Bloom** über eine Kette halbierter Bilder: nur was nach der Belichtung
   heller als Weiß ist (Sonne im Lack, Rückleuchten), leuchtet etwas über.
4. **ACES-Abbildung** mit Belichtung, danach Gamma.
5. **Farbkorrektur**: etwas Kontrast und Sättigung, eine leichte Vignette.
6. **FXAA**, wenn so eingestellt; zuletzt ein Hauch Rauschen gegen Stufen im
   Himmelsverlauf (8 Bit reichen für einen weichen Verlauf nicht ganz).

Das Ziel ist, was beim Aufruf von :meth:`Nachbearbeitung.beginnen` gebunden
war — Fenster, Splitscreen-Hälfte oder ein Bild außerhalb des Fensters — mit
genau dessen Ausschnitt. Jeder Ausschnitt bekommt eigene Puffer in seiner
Größe; die Welt wird in ``grafik.aufloesung_skala`` davon gerechnet und erst
im letzten Durchgang auf den Ausschnitt gezogen. Das HUD liegt darüber und
bleibt immer scharf.

Was die Kette kostet, steht in ``grafik.py`` (``ssao``, ``bloom``,
``kantenglaettung``, ``aufloesung_skala``); gelesen wird in jedem Bild, eine
Änderung im Menü greift also sofort.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import grafik as grafik_modul

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


#: Zielhelligkeit, ab der Bloom einsetzt (nach der Belichtung, vor ACES), und
#: wie weich der Übergang ist.
BLOOM_SCHWELLE = 1.6
BLOOM_KNIE = 0.8
#: Wie stark das Leuchten dazukommt. Klein halten: ein Bild, das überall
#: glimmt, sieht nach Weichzeichner aus, nicht nach Licht.
BLOOM_STAERKE = 0.14
#: Radius der Umgebungsverdeckung in Metern und wie dunkel sie höchstens wird.
SSAO_RADIUS_M = 0.7
SSAO_STAERKE = 0.9
#: Farbkorrektur: 1.0 heißt unverändert.
KONTRAST = 1.06
SAETTIGUNG = 1.08
VIGNETTE = 0.22

#: Höchstzahl gleichzeitig vorgehaltener Puffersätze (Vollbild, zwei
#: Splitscreen-Hälften). Wer die Fenstergröße zieht, erzeugt ständig neue —
#: die ältesten gehen dann zurück.
PUFFERSAETZE = 3

_VERTEX = """
#version 330
in vec2 in_ecke;
out vec2 uv;
void main() {
    uv = in_ecke * 0.5 + 0.5;
    gl_Position = vec4(in_ecke, 0.0, 1.0);
}
"""

_SSAO = """
#version 330
uniform sampler2D tiefe;
uniform mat4 vp;          // Welt relativ zur Kamera -> Clip
uniform mat4 inv_vp;
uniform vec3 kern[12];
uniform float radius;
uniform float staerke;
in vec2 uv;
out vec2 ausgabe;          // r: Verdeckung (1 = frei), g: Abstand zur Kamera

vec3 ort(vec2 t) {
    float d = textureLod(tiefe, t, 0.0).r;
    vec4 p = inv_vp * vec4(t * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return p.xyz / p.w;
}

void main() {
    float d = textureLod(tiefe, uv, 0.0).r;
    if (d >= 1.0) { ausgabe = vec2(1.0, 1.0e5); return; }
    vec3 p = ort(uv);
    float abstand = length(p);
    if (abstand > 160.0) { ausgabe = vec2(1.0, abstand); return; }

    // Normale aus der Tiefe: je Achse die kleinere Differenz, sonst kippt
    // sie an jeder Silhouette.
    vec2 px = 1.0 / vec2(textureSize(tiefe, 0));
    vec3 pr = ort(uv + vec2(px.x, 0.0)), pl = ort(uv - vec2(px.x, 0.0));
    vec3 po = ort(uv + vec2(0.0, px.y)), pu = ort(uv - vec2(0.0, px.y));
    vec3 dx = (length(pr - p) < length(p - pl)) ? pr - p : p - pl;
    vec3 dy = (length(po - p) < length(p - pu)) ? po - p : p - pu;
    vec3 n = normalize(cross(dx, dy));
    if (dot(n, p) > 0.0) n = -n;

    // Je Pixel anders gedreht; das Weichzeichnen danach macht daraus Flaeche.
    float w = 6.2831853 * fract(52.9829189 * fract(dot(gl_FragCoord.xy, vec2(0.06711056, 0.00583715))));
    vec3 zufall = vec3(cos(w), sin(w), 0.0);
    if (abs(n.z) > 0.9) zufall = vec3(cos(w), 0.0, sin(w)).xzy;
    vec3 t = normalize(zufall - n * dot(zufall, n));
    mat3 tbn = mat3(t, cross(n, t), n);

    float bias = 0.02 + abstand * 0.002;
    float verdeckt = 0.0;
    for (int i = 0; i < 12; i++) {
        vec3 s = p + tbn * kern[i] * radius;
        vec4 c = vp * vec4(s, 1.0);
        if (c.w <= 0.0) continue;
        vec2 st = c.xy / c.w * 0.5 + 0.5;
        if (st.x < 0.0 || st.x > 1.0 || st.y < 0.0 || st.y > 1.0) continue;
        float lq = length(ort(st));
        // Nur, was wirklich in der Naehe liegt, verdeckt: ein Auto zehn
        // Meter vor dem Boden wirft keinen Kranz auf ihn.
        float bereich = smoothstep(0.0, 1.0, radius / max(abs(abstand - lq), 1e-4));
        verdeckt += (lq < length(s) - bias ? 1.0 : 0.0) * bereich;
    }
    float ao = 1.0 - verdeckt / 12.0;
    float blende = 1.0 - smoothstep(70.0, 160.0, abstand);
    ausgabe = vec2(mix(1.0, ao, staerke * blende), abstand);
}
"""

_SSAO_WEICH = """
#version 330
uniform sampler2D quelle;
uniform vec2 schritt;
in vec2 uv;
out vec2 ausgabe;
void main() {
    vec2 mitte = textureLod(quelle, uv, 0.0).rg;
    float summe = mitte.r;
    float gewicht = 1.0;
    float toleranz = 0.04 * mitte.g + 0.1;
    for (int i = -3; i <= 3; i++) {
        if (i == 0) continue;
        vec2 s = textureLod(quelle, uv + schritt * float(i), 0.0).rg;
        float g = exp(-float(i * i) / 8.0) * exp(-abs(s.g - mitte.g) / toleranz);
        summe += s.r * g;
        gewicht += g;
    }
    ausgabe = vec2(summe / gewicht, mitte.g);
}
"""

_BLOOM_AB = """
#version 330
uniform sampler2D quelle;
uniform vec2 texel;           // der Quelle
uniform float erste;          // 1: Schwelle und Belichtung anwenden
uniform float belichtung;
uniform float schwelle;
uniform float knie;
in vec2 uv;
out vec4 ausgabe;

vec3 probe(vec2 o) { return textureLod(quelle, uv + o * texel, 0.0).rgb; }

vec3 hell(vec3 c) {
    c = min(c * belichtung, vec3(64.0));
    float h = max(c.r, max(c.g, c.b));
    float weich = clamp(h - schwelle + knie, 0.0, 2.0 * knie);
    weich = weich * weich / (4.0 * knie + 1e-4);
    return c * max(weich, h - schwelle) / max(h, 1e-4);
}

float karis(vec3 c) { return 1.0 / (1.0 + dot(c, vec3(0.2126, 0.7152, 0.0722))); }

void main() {
    // 13 Proben (Jimenez 2014): weich genug fuer eine glatte Kette, ohne
    // dass einzelne helle Pixel flackern.
    vec3 a = probe(vec2(-2, 2)), b = probe(vec2(0, 2)), c = probe(vec2(2, 2));
    vec3 d = probe(vec2(-2, 0)), e = probe(vec2(0, 0)), f = probe(vec2(2, 0));
    vec3 g = probe(vec2(-2, -2)), h = probe(vec2(0, -2)), i = probe(vec2(2, -2));
    vec3 j = probe(vec2(-1, 1)), k = probe(vec2(1, 1));
    vec3 l = probe(vec2(-1, -1)), m = probe(vec2(1, -1));
    if (erste > 0.5) {
        a = hell(a); b = hell(b); c = hell(c); d = hell(d); e = hell(e); f = hell(f);
        g = hell(g); h = hell(h); i = hell(i); j = hell(j); k = hell(k); l = hell(l); m = hell(m);
        // Karis-Mittel: ein einzelnes gleissendes Pixel (Sonne im Lack)
        // zaehlt weniger, sonst blinkt der Bloom bei jeder Bewegung.
        vec3 g0 = (j + k + l + m) * 0.25, g1 = (a + b + d + e) * 0.25, g2 = (b + c + e + f) * 0.25;
        vec3 g3 = (d + e + g + h) * 0.25, g4 = (e + f + h + i) * 0.25;
        float w0 = karis(g0) * 0.5, w1 = karis(g1) * 0.125, w2 = karis(g2) * 0.125;
        float w3 = karis(g3) * 0.125, w4 = karis(g4) * 0.125;
        ausgabe = vec4((g0 * w0 + g1 * w1 + g2 * w2 + g3 * w3 + g4 * w4) / (w0 + w1 + w2 + w3 + w4), 1.0);
        return;
    }
    vec3 s = e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
    ausgabe = vec4(s, 1.0);
}
"""

_BLOOM_AUF = """
#version 330
uniform sampler2D quelle;
uniform vec2 texel;
uniform float gewicht;
in vec2 uv;
out vec4 ausgabe;
vec3 probe(vec2 o) { return textureLod(quelle, uv + o * texel, 0.0).rgb; }
void main() {
    vec3 s = probe(vec2(0, 0)) * 4.0
           + (probe(vec2(-1, 0)) + probe(vec2(1, 0)) + probe(vec2(0, -1)) + probe(vec2(0, 1))) * 2.0
           + probe(vec2(-1, -1)) + probe(vec2(1, -1)) + probe(vec2(-1, 1)) + probe(vec2(1, 1));
    ausgabe = vec4(s / 16.0 * gewicht, 1.0);
}
"""

_ENDE = """
#version 330
uniform sampler2D hdr;
uniform sampler2D ao;
uniform sampler2D bloom;
uniform sampler2D tiefe;
uniform mat4 inv_vp;
uniform float hat_ao;
uniform float ao_halb;
uniform float hat_bloom;
uniform float bloom_staerke;
uniform float belichtung;
uniform float kontrast;
uniform float saettigung;
uniform float vignette;
uniform float mit_alpha;       // Vorschau: Durchsicht behalten
uniform float luma_in_alpha;   // fuer FXAA danach
uniform float rauschen;        // gegen Stufen im Verlauf, nur im letzten Durchgang
in vec2 uv;
out vec4 ausgabe;

vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

float abstand_bei(vec2 t) {
    float d = textureLod(tiefe, t, 0.0).r;
    if (d >= 1.0) return 1.0e5;
    vec4 p = inv_vp * vec4(t * 2.0 - 1.0, d * 2.0 - 1.0, 1.0);
    return length(p.xyz / p.w);
}

/* Die halb aufgeloeste Verdeckung auf volle Aufloesung: von den vier
   Nachbarn zaehlen die, deren Abstand zu diesem Pixel passt. Bilinear allein
   zoege an jeder Silhouette einen hellen oder dunklen Saum. */
float verdeckung() {
    if (ao_halb < 0.5) return textureLod(ao, uv, 0.0).r;
    vec2 groesse = vec2(textureSize(ao, 0));
    vec2 f = uv * groesse - 0.5;
    ivec2 i0 = ivec2(floor(f));
    vec2 w = fract(f);
    float mitte = abstand_bei(uv);
    float summe = 0.0, gewicht = 0.0;
    for (int y = 0; y <= 1; y++) {
        for (int x = 0; x <= 1; x++) {
            ivec2 ij = clamp(i0 + ivec2(x, y), ivec2(0), ivec2(groesse) - 1);
            vec2 s = texelFetch(ao, ij, 0).rg;
            float b = (x == 1 ? w.x : 1.0 - w.x) * (y == 1 ? w.y : 1.0 - w.y);
            float g = (b + 1e-3) / (1e-3 + abs(s.g - mitte) / (0.03 * mitte + 0.05));
            summe += s.r * g;
            gewicht += g;
        }
    }
    return summe / max(gewicht, 1e-5);
}

float zufall(vec2 p) {
    return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
}

void main() {
    vec4 roh = textureLod(hdr, uv, 0.0);
    vec3 c = roh.rgb;
    if (any(isnan(c)) || any(isinf(c))) c = vec3(0.0);
    c = clamp(c, 0.0, 256.0);
    if (hat_ao > 0.5) c *= verdeckung();
    c *= belichtung;
    if (hat_bloom > 0.5) c += textureLod(bloom, uv, 0.0).rgb * bloom_staerke;
    c = aces(c);
    c = pow(c, vec3(1.0 / 2.2));

    float grau = dot(c, vec3(0.2126, 0.7152, 0.0722));
    c = mix(vec3(grau), c, saettigung);
    c = clamp((c - 0.5) * kontrast + 0.5, 0.0, 1.0);
    vec2 r = uv - 0.5;
    c *= 1.0 - vignette * smoothstep(0.2, 0.9, dot(r, r) * 2.0);
    c += (zufall(gl_FragCoord.xy) - 0.5) / 255.0 * rauschen;

    float a = 1.0;
    if (mit_alpha > 0.5) a = roh.a;
    else if (luma_in_alpha > 0.5) a = dot(c, vec3(0.299, 0.587, 0.114));
    ausgabe = vec4(c, a);
}
"""

_FXAA = """
#version 330
uniform sampler2D ldr;
uniform vec2 texel;
in vec2 uv;
out vec4 ausgabe;

float zufall(vec2 p) {
    return fract(52.9829189 * fract(dot(p, vec2(0.06711056, 0.00583715))));
}

void main() {
    // FXAA nach Lottes, die schnelle Fassung: die Luma steht im Alphakanal.
    vec4 m = textureLod(ldr, uv, 0.0);
    float lnw = textureLod(ldr, uv + vec2(-1.0, -1.0) * texel, 0.0).a;
    float lne = textureLod(ldr, uv + vec2( 1.0, -1.0) * texel, 0.0).a;
    float lsw = textureLod(ldr, uv + vec2(-1.0,  1.0) * texel, 0.0).a;
    float lse = textureLod(ldr, uv + vec2( 1.0,  1.0) * texel, 0.0).a;
    float lm = m.a;
    float lmin = min(lm, min(min(lnw, lne), min(lsw, lse)));
    float lmax = max(lm, max(max(lnw, lne), max(lsw, lse)));
    vec3 c = m.rgb;
    if (lmax - lmin > max(0.0312, lmax * 0.125)) {
        vec2 dir = vec2(-((lnw + lne) - (lsw + lse)), ((lnw + lsw) - (lne + lse)));
        float reduzieren = max((lnw + lne + lsw + lse) * (0.25 / 8.0), 1.0 / 128.0);
        float kehr = 1.0 / (min(abs(dir.x), abs(dir.y)) + reduzieren);
        dir = clamp(dir * kehr, vec2(-8.0), vec2(8.0)) * texel;
        vec3 a = 0.5 * (textureLod(ldr, uv + dir * (1.0 / 3.0 - 0.5), 0.0).rgb
                      + textureLod(ldr, uv + dir * (2.0 / 3.0 - 0.5), 0.0).rgb);
        vec3 b = a * 0.5 + 0.25 * (textureLod(ldr, uv - dir * 0.5, 0.0).rgb
                                 + textureLod(ldr, uv + dir * 0.5, 0.0).rgb);
        float lb = dot(b, vec3(0.299, 0.587, 0.114));
        c = (lb < lmin || lb > lmax) ? a : b;
    }
    c += (zufall(gl_FragCoord.xy) - 0.5) / 255.0;
    ausgabe = vec4(c, 1.0);
}
"""


def ssao_kern(anzahl: int = 12, keim: int = 7) -> np.ndarray:
    """Proben in der Halbkugel über der Fläche, zur Mitte hin dichter."""
    rng = np.random.default_rng(keim)
    kern = []
    for i in range(anzahl):
        v = rng.normal(size=3)
        v[2] = abs(v[2]) + 0.15
        v /= np.linalg.norm(v)
        skala = (i + 1) / anzahl
        v *= 0.15 + 0.85 * skala * skala
        kern.append(v)
    return np.asarray(kern, dtype="f4")


def kamera_relativ(mvp: np.ndarray, kamera_position) -> np.ndarray:
    """``mvp`` für Punkte relativ zur Kamera.

    Die Tiefe wird in der Nachbearbeitung zurück in einen Ort gerechnet. In
    Weltkoordinaten sind das Zahlen um tausend Meter, und float32 verliert dort
    die Zentimeter, auf die es bei der Verdeckung ankommt. Relativ zur Kamera
    bleibt alles klein.
    """
    t = np.eye(4)
    t[:3, 3] = np.asarray(kamera_position, dtype=np.float64)[:3]
    return np.asarray(mvp, dtype=np.float64) @ t


@dataclass
class _Satz:
    """Alle Puffer für einen Ausschnitt einer Größe mit einer Einstellung."""

    groesse: tuple[int, int]
    msaa: bool
    ssao: int
    bloom: bool
    fxaa: bool
    farbe: object = None
    tiefe: object = None
    fbo: object = None              # Ziel der Szene
    fbo_ms: object = None           # mit Mehrfachproben, sonst None
    fbo_farbe: object = None        # nur Farbe, für Rauch und Ähnliches
    ao: list = field(default_factory=list)       # [textur, fbo] x2
    bloom_kette: list = field(default_factory=list)  # [(textur, fbo)]
    ldr: object = None
    fbo_ldr: object = None
    dinge: list = field(default_factory=list)

    def freigeben(self) -> None:
        for ding in self.dinge:
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self.dinge = []


class Nachbearbeitung:
    """Zwischenpuffer und alle Durchgänge nach der Welt."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        prog = ctx.program
        self.p_ssao = prog(vertex_shader=_VERTEX, fragment_shader=_SSAO)
        self.p_weich = prog(vertex_shader=_VERTEX, fragment_shader=_SSAO_WEICH)
        self.p_ab = prog(vertex_shader=_VERTEX, fragment_shader=_BLOOM_AB)
        self.p_auf = prog(vertex_shader=_VERTEX, fragment_shader=_BLOOM_AUF)
        self.p_ende = prog(vertex_shader=_VERTEX, fragment_shader=_ENDE)
        self.p_fxaa = prog(vertex_shader=_VERTEX, fragment_shader=_FXAA)
        ecken = np.array([[-1, -1], [3, -1], [-1, 3]], dtype="f4")
        self._puffer = ctx.buffer(ecken.tobytes())
        self._vaos = {id(p): ctx.vertex_array(p, [(self._puffer, "2f", "in_ecke")])
                      for p in (self.p_ssao, self.p_weich, self.p_ab, self.p_auf,
                                self.p_ende, self.p_fxaa)}
        self.p_ssao["kern"].write(ssao_kern().tobytes())
        self._saetze: dict[tuple, _Satz] = {}
        self._lauf = None

    # -- Puffer -------------------------------------------------------------
    def _satz(self, groesse, msaa, ssao, bloom, fxaa) -> _Satz:
        schluessel = (groesse, msaa, ssao, bloom, fxaa)
        satz = self._saetze.pop(schluessel, None)
        if satz is None:
            satz = self._satz_bauen(*schluessel)
        self._saetze[schluessel] = satz                  # zuletzt benutzt nach hinten
        while len(self._saetze) > PUFFERSAETZE:
            aeltester = next(iter(self._saetze))
            self._saetze.pop(aeltester).freigeben()
        return satz

    def _satz_bauen(self, groesse, msaa, ssao, bloom, fxaa) -> _Satz:
        ctx = self.ctx
        s = _Satz(groesse, msaa, ssao, bloom, fxaa)
        b, h = groesse
        s.farbe = ctx.texture((b, h), 4, dtype="f2")
        s.farbe.filter = (moderngl.LINEAR, moderngl.LINEAR)
        s.farbe.repeat_x = s.farbe.repeat_y = False
        s.tiefe = ctx.depth_texture((b, h))
        s.tiefe.filter = (moderngl.NEAREST, moderngl.NEAREST)
        s.tiefe.repeat_x = s.tiefe.repeat_y = False
        s.fbo = ctx.framebuffer(color_attachments=[s.farbe], depth_attachment=s.tiefe)
        s.fbo_farbe = ctx.framebuffer(color_attachments=[s.farbe])
        s.dinge += [s.fbo, s.fbo_farbe, s.farbe, s.tiefe]
        if msaa:
            farbe_ms = ctx.renderbuffer((b, h), 4, samples=4, dtype="f2")
            tiefe_ms = ctx.depth_renderbuffer((b, h), samples=4)
            s.fbo_ms = ctx.framebuffer(color_attachments=[farbe_ms], depth_attachment=tiefe_ms)
            s.dinge += [s.fbo_ms, farbe_ms, tiefe_ms]
        if ssao:
            teiler = 2 if ssao == 1 else 1
            ab = (max(1, b // teiler), max(1, h // teiler))
            for _ in range(2):
                t = ctx.texture(ab, 2, dtype="f2")
                t.filter = (moderngl.NEAREST, moderngl.NEAREST)
                t.repeat_x = t.repeat_y = False
                f = ctx.framebuffer(color_attachments=[t])
                s.ao.append((t, f))
                s.dinge += [f, t]
        if bloom:
            gb, gh = max(1, b // 2), max(1, h // 2)
            for _ in range(6):
                t = ctx.texture((gb, gh), 3, dtype="f2")
                t.filter = (moderngl.LINEAR, moderngl.LINEAR)
                t.repeat_x = t.repeat_y = False
                f = ctx.framebuffer(color_attachments=[t])
                s.bloom_kette.append((t, f))
                s.dinge += [f, t]
                if min(gb, gh) <= 8:
                    break
                gb, gh = max(1, gb // 2), max(1, gh // 2)
        if fxaa:
            s.ldr = ctx.texture((b, h), 4)
            s.ldr.filter = (moderngl.LINEAR, moderngl.LINEAR)
            s.ldr.repeat_x = s.ldr.repeat_y = False
            s.fbo_ldr = ctx.framebuffer(color_attachments=[s.ldr])
            s.dinge += [s.fbo_ldr, s.ldr]
        return s

    # -- Ablauf ---------------------------------------------------------------
    def beginnen(self, mvp: np.ndarray, kamera_position, einstellung=None, *,
                 mit_alpha: bool = False, vignette: float | None = None) -> None:
        """Den Zwischenpuffer binden; die Welt zeichnet danach wie gewohnt.

        Ziel und Ausschnitt sind, was jetzt gebunden ist. ``einstellung``
        ist ein :class:`~src.render3d.grafik.Grafik`; ohne sie gilt die
        aktuelle Stufe.
        """
        ctx = self.ctx
        g = einstellung or grafik_modul.aktuell()
        ziel, ausschnitt, schere = ctx.fbo, tuple(ctx.viewport), ctx.scissor
        vb, vh = max(1, int(ausschnitt[2])), max(1, int(ausschnitt[3]))
        skala = min(1.0, max(0.25, float(g.aufloesung_skala)))
        groesse = (max(1, round(vb * skala)), max(1, round(vh * skala)))
        kg = str(g.kantenglaettung)
        satz = self._satz(groesse, kg == "msaa4", int(g.ssao), bool(g.bloom), kg == "fxaa")
        vp = kamera_relativ(mvp, kamera_position)
        self._lauf = {
            "ziel": ziel, "ausschnitt": ausschnitt, "schere": schere, "satz": satz,
            "vp": vp, "mit_alpha": mit_alpha,
            "vignette": VIGNETTE if vignette is None else float(vignette),
            "aufgeloest": False,
        }
        fbo = satz.fbo_ms or satz.fbo
        fbo.use()
        ctx.scissor = None
        ctx.viewport = (0, 0, *groesse)
        fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        ctx.depth_mask = True

    @property
    def groesse(self) -> tuple[int, int] | None:
        """Auflösung, in der die Welt gerade gerechnet wird."""
        return self._lauf["satz"].groesse if self._lauf else None

    def aufloesen(self):
        """Mehrfachproben zusammenfassen; ``(farbtextur, tiefentextur)``.

        Danach ist ein Puffer **nur mit Farbe** gebunden: wer jetzt noch
        zeichnet (Rauch), mischt in das HDR-Bild und liest die Tiefe als
        Textur, statt gegen sie zu testen.
        """
        satz = self._lauf["satz"]
        if not self._lauf["aufgeloest"]:
            if satz.fbo_ms is not None:
                self.ctx.copy_framebuffer(satz.fbo, satz.fbo_ms)
            self._lauf["aufgeloest"] = True
        satz.fbo_farbe.use()
        self.ctx.viewport = (0, 0, *satz.groesse)
        return satz.farbe, satz.tiefe

    def _voll(self, p) -> None:
        self._vaos[id(p)].render(moderngl.TRIANGLES)

    def abschliessen(self, belichtung: float = 1.0) -> None:
        """Alle Durchgänge rechnen und ins Ziel schreiben."""
        ctx = self.ctx
        lauf = self._lauf
        if lauf is None:
            return
        self.aufloesen()
        satz: _Satz = lauf["satz"]
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        ctx.depth_mask = False
        vp = lauf["vp"]
        inv_vp = np.linalg.inv(vp)
        from .shader import matrix_setzen, setzen

        # --- Umgebungsverdeckung --------------------------------------------
        if satz.ao:
            (ao0, f0), (ao1, f1) = satz.ao
            p = self.p_ssao
            matrix_setzen(p, "vp", vp)
            matrix_setzen(p, "inv_vp", inv_vp)
            setzen(p, "tiefe", 0)
            setzen(p, "radius", SSAO_RADIUS_M)
            setzen(p, "staerke", SSAO_STAERKE)
            satz.tiefe.use(0)
            f0.use()
            ctx.viewport = (0, 0, *ao0.size)
            self._voll(p)
            p = self.p_weich
            setzen(p, "quelle", 0)
            for quelle, ziel, schritt in ((ao0, f1, (1.0 / ao0.size[0], 0.0)),
                                          (ao1, f0, (0.0, 1.0 / ao0.size[1]))):
                ziel.use()
                quelle.use(0)
                setzen(p, "schritt", schritt)
                self._voll(p)

        # --- Bloom -------------------------------------------------------------
        if satz.bloom_kette:
            p = self.p_ab
            setzen(p, "quelle", 0)
            setzen(p, "belichtung", float(belichtung))
            setzen(p, "schwelle", BLOOM_SCHWELLE)
            setzen(p, "knie", BLOOM_KNIE)
            quelle = satz.farbe
            for i, (t, f) in enumerate(satz.bloom_kette):
                f.use()
                ctx.viewport = (0, 0, *t.size)
                quelle.use(0)
                setzen(p, "texel", (1.0 / quelle.size[0], 1.0 / quelle.size[1]))
                setzen(p, "erste", 1.0 if i == 0 else 0.0)
                self._voll(p)
                quelle = t
            p = self.p_auf
            setzen(p, "quelle", 0)
            setzen(p, "gewicht", 1.0)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = moderngl.ONE, moderngl.ONE
            for i in range(len(satz.bloom_kette) - 1, 0, -1):
                klein, _ = satz.bloom_kette[i]
                gross, f = satz.bloom_kette[i - 1]
                f.use()
                ctx.viewport = (0, 0, *gross.size)
                klein.use(0)
                setzen(p, "texel", (1.0 / klein.size[0], 1.0 / klein.size[1]))
                self._voll(p)
            ctx.disable(moderngl.BLEND)

        # --- Abbildung, Farbe, Glättung ----------------------------------------
        p = self.p_ende
        for name, einheit in (("hdr", 0), ("ao", 1), ("bloom", 2), ("tiefe", 3)):
            setzen(p, name, einheit)
        satz.farbe.use(0)
        satz.tiefe.use(3)
        setzen(p, "hat_ao", 1.0 if satz.ao else 0.0)
        setzen(p, "ao_halb", 1.0 if satz.ssao == 1 else 0.0)
        if satz.ao:
            satz.ao[0][0].use(1)
            matrix_setzen(p, "inv_vp", inv_vp)
        setzen(p, "hat_bloom", 1.0 if satz.bloom_kette else 0.0)
        if satz.bloom_kette:
            satz.bloom_kette[0][0].use(2)
            setzen(p, "bloom_staerke", BLOOM_STAERKE / len(satz.bloom_kette))
        setzen(p, "belichtung", float(belichtung))
        setzen(p, "kontrast", KONTRAST)
        setzen(p, "saettigung", SAETTIGUNG)
        setzen(p, "vignette", lauf["vignette"])
        setzen(p, "mit_alpha", 1.0 if lauf["mit_alpha"] else 0.0)

        ziel, ausschnitt, schere = lauf["ziel"], lauf["ausschnitt"], lauf["schere"]
        if satz.fbo_ldr is not None and not lauf["mit_alpha"]:
            satz.fbo_ldr.use()
            ctx.viewport = (0, 0, *satz.groesse)
            setzen(p, "luma_in_alpha", 1.0)
            setzen(p, "rauschen", 0.0)
            self._voll(p)
            ziel.use()
            ctx.viewport = ausschnitt
            ctx.scissor = schere
            q = self.p_fxaa
            setzen(q, "ldr", 0)
            setzen(q, "texel", (1.0 / satz.groesse[0], 1.0 / satz.groesse[1]))
            satz.ldr.use(0)
            self._voll(q)
        else:
            ziel.use()
            ctx.viewport = ausschnitt
            ctx.scissor = schere
            setzen(p, "luma_in_alpha", 0.0)
            setzen(p, "rauschen", 1.0)
            self._voll(p)

        ctx.depth_mask = True
        ctx.enable(moderngl.DEPTH_TEST)
        self._lauf = None

    def freigeben(self) -> None:
        for satz in self._saetze.values():
            satz.freigeben()
        self._saetze = {}
        for ding in (*self._vaos.values(), self._puffer, self.p_ssao, self.p_weich,
                     self.p_ab, self.p_auf, self.p_ende, self.p_fxaa):
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self._vaos = {}
