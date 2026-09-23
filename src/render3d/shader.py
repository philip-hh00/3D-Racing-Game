"""PBR-Beleuchtung: Lack sieht aus wie Lack, Reifen wie Gummi.

Gerechnet wird Cook-Torrance mit GGX-Verteilung, Smith-Geometrie und
Schlick-Fresnel. Dazu kommt, was ein Bild erst glaubwürdig macht:

* **Umgebung aus einem echten Himmel.** Ist eine Himmelskarte gesetzt (ein
  Equirectangular-Bild aus einem Poly-Haven-HDRI, siehe
  ``tools/blender/himmel_bauen.py``), spiegeln Lack und Glas die Wolken, und
  die Mip-Stufe folgt der Rauheit — rauer Lack spiegelt verwaschen. Ohne
  Karte bleibt der Farbverlauf von Horizont zu Zenit. **Ohne Umgebung ist
  Metall schwarz**: eine metallische Fläche zeigt nur, was um sie herum ist.
* **Klarlack.** Autolack ist eine farbige Schicht unter einer glasklaren. Die
  zweite, sehr glatte Spiegelung darüber ist der Unterschied zwischen Lack und
  Plastik.
* **Schattenwurf** aus einer Schattenkarte der Sonne, mit weichem Rand
  (PCF). Ohne ihn schweben Bäume und Häuser über dem Boden.
* **Nebel**, der zur Horizontfarbe des Himmels hin ausblendet — so endet die
  Welt nicht an einer Kante, sondern im Dunst.
* **Emission** für Scheinwerfer und Rückleuchten, **Alpha-Maske** für Laub,
  **Durchsicht** für Glas.

Zwei Vertex-Shader teilen sich den Fragment-Shader: einer mit einer
Modellmatrix als Uniform (Fahrzeuge, Strecke), einer mit einer Matrix je
Instanz (Bäume, Felsen, Häuser — hunderte Exemplare in einem Aufruf).
"""
from __future__ import annotations

import numpy as np

_VERTEX_KOPF = """
#version 330
uniform mat4 mvp;
uniform mat4 licht_mvp;

in vec3 in_position;
in vec3 in_normale;
in vec2 in_uv;

out vec3 welt_position;
out vec3 welt_normale;
out vec2 uv;
out vec4 licht_position;
"""

VERTEX = _VERTEX_KOPF + """
uniform mat4 modell;
uniform mat3 normalmatrix;

void main() {
    vec4 welt = modell * vec4(in_position, 1.0);
    welt_position = welt.xyz;
    // Normalen brauchen die inverse Transponierte, sonst stehen sie nach einer
    // ungleichmaessigen Skalierung schief auf der Flaeche.
    welt_normale = normalmatrix * in_normale;
    uv = in_uv;
    licht_position = licht_mvp * welt;
    gl_Position = mvp * welt;
}
"""

#: Instanzen tragen ihre Modellmatrix als vier Spalten. Gedreht wird nur um
#: die Hochachse und gleichmäßig skaliert — dann ist ``mat3(modell)`` bis auf
#: die Länge schon die richtige Normalmatrix.
VERTEX_INSTANZ = _VERTEX_KOPF + """
in vec4 in_inst0;
in vec4 in_inst1;
in vec4 in_inst2;
in vec4 in_inst3;

void main() {
    mat4 modell = mat4(in_inst0, in_inst1, in_inst2, in_inst3);
    vec4 welt = modell * vec4(in_position, 1.0);
    welt_position = welt.xyz;
    welt_normale = mat3(modell) * in_normale;
    uv = in_uv;
    licht_position = licht_mvp * welt;
    gl_Position = mvp * welt;
}
"""

FRAGMENT = """
#version 330

const float PI = 3.14159265359;

uniform sampler2D basisfarbe;
uniform sampler2D metallic_rauheit;
uniform sampler2D himmel_karte;
uniform sampler2DShadow schatten_karte;

uniform float hat_basisfarbe;
uniform float hat_metallic_rauheit;
uniform float hat_himmel;
uniform float hat_schatten;
uniform vec3  grundton;          // sRGB, wenn keine Textur da ist
uniform float metallic_faktor;
uniform float rauheit_faktor;
uniform vec3  emission;          // linear, schon mit Staerke multipliziert
uniform float klarlack;          // 0..1
uniform float alpha_faktor;
uniform float alpha_schwelle;    // > 0: ausstanzen (Laub)
uniform float uv_skala;          // Kachelung fuer Boden und Fahrbahn
uniform vec3  farbton;           // Faerbt eine Textur ein (Gras gruener, Sand waermer)
uniform float makro;             // Grossraeumige Helligkeitsschwankung gegen sichtbare Kacheln

uniform vec3 kamera_position;
uniform vec3 sonne_richtung;     // zeigt ZUR Sonne, normiert
uniform vec3 sonne_farbe;
uniform vec3 himmel_zenit;
uniform vec3 himmel_horizont;
uniform vec3 boden_farbe;
uniform float himmel_mips;
uniform float himmel_helligkeit;
uniform vec3  nebel_farbe;
uniform float nebel_dichte;
uniform float nebel_faktor;      // Kulisse: weniger Dunst, sonst verschwinden die Berge
uniform float belichtung;

/* Fuer den Ghost: entfaerben und durchscheinend zeichnen. */
uniform float entfaerbung;
uniform float deckkraft;

in vec3 welt_position;
in vec3 welt_normale;
in vec2 uv;
in vec4 licht_position;

out vec4 ausgabe;

vec3 nach_linear(vec3 srgb) {
    return pow(max(srgb, vec3(0.0)), vec3(2.2));
}

vec2 equirect(vec3 d) {
    float u = 0.5 + atan(d.y, d.x) / (2.0 * PI);
    float v = 0.5 + asin(clamp(d.z, -1.0, 1.0)) / PI;
    return vec2(u, v);
}

/* Der Himmel als Funktion einer Richtung und einer Unschaerfe (0..1). */
vec3 himmel(vec3 richtung, float unschaerfe) {
    vec3 d = normalize(richtung);
    vec3 verlauf;
    float hoch = d.z;
    if (hoch < 0.0) {
        verlauf = mix(himmel_horizont, boden_farbe, clamp(-hoch * 3.0, 0.0, 1.0));
    } else {
        verlauf = mix(himmel_horizont, himmel_zenit, pow(hoch, 0.6));
    }
    if (hat_himmel > 0.5) {
        vec3 dd = d;
        dd.z = max(dd.z, 0.02);   // unterhalb des Horizonts: Horizont + Boden
        vec3 karte = nach_linear(textureLod(himmel_karte, equirect(normalize(dd)),
                                            unschaerfe * himmel_mips).rgb) * himmel_helligkeit;
        if (hoch < 0.0) {
            karte = mix(karte, boden_farbe, clamp(-hoch * 4.0, 0.0, 1.0));
        }
        return karte;
    }
    return verlauf;
}

float verteilung_ggx(float n_dot_h, float rauheit) {
    float a = rauheit * rauheit;
    float a2 = a * a;
    float nenner = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / max(PI * nenner * nenner, 1e-7);
}

float geometrie_schlick(float n_dot_v, float rauheit) {
    float k = (rauheit + 1.0) * (rauheit + 1.0) / 8.0;
    return n_dot_v / (n_dot_v * (1.0 - k) + k);
}

float geometrie_smith(float n_dot_v, float n_dot_l, float rauheit) {
    return geometrie_schlick(n_dot_v, rauheit) * geometrie_schlick(n_dot_l, rauheit);
}

vec3 fresnel_schlick(float kosinus, vec3 f0) {
    return f0 + (1.0 - f0) * pow(clamp(1.0 - kosinus, 0.0, 1.0), 5.0);
}

vec3 fresnel_rauh(float kosinus, vec3 f0, float rauheit) {
    vec3 hoch = max(vec3(1.0 - rauheit), f0);
    return f0 + (hoch - f0) * pow(clamp(1.0 - kosinus, 0.0, 1.0), 5.0);
}

/* Wieviel Sonne hier ankommt, 0..1, mit weichem Rand aus neun Proben. */
float sonnenlicht(vec3 n, vec3 l) {
    if (hat_schatten < 0.5) return 1.0;
    vec3 p = licht_position.xyz / licht_position.w * 0.5 + 0.5;
    if (p.x <= 0.0 || p.x >= 1.0 || p.y <= 0.0 || p.y >= 1.0 || p.z >= 1.0) return 1.0;
    float neigung = clamp(1.0 - dot(n, l), 0.0, 1.0);
    float versatz = 0.0006 + 0.0025 * neigung;
    vec2 texel = 1.0 / vec2(textureSize(schatten_karte, 0));
    float summe = 0.0;
    for (int x = -1; x <= 1; x++) {
        for (int y = -1; y <= 1; y++) {
            summe += texture(schatten_karte, vec3(p.xy + vec2(x, y) * texel * 1.25, p.z - versatz));
        }
    }
    float licht = summe / 9.0;
    // Zum Rand der Karte hin ausblenden, damit keine Kante durchs Bild laeuft.
    vec2 rand = min(p.xy, 1.0 - p.xy);
    float blende = smoothstep(0.0, 0.06, min(rand.x, rand.y));
    return mix(1.0, licht, blende);
}

/* Werterauschen in Weltkoordinaten. Eine Bodentextur von acht Metern
   wiederholt sich auf einem Kilometer 125-mal, und das Auge findet das Muster
   sofort. Zwei Oktaven Helligkeit darueber, 30 und 90 Meter gross, brechen es. */
float rauschen_hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float rauschen(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(rauschen_hash(i), rauschen_hash(i + vec2(1, 0)), u.x),
               mix(rauschen_hash(i + vec2(0, 1)), rauschen_hash(i + vec2(1, 1)), u.x), u.y);
}

vec3 aces(vec3 x) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec2 tuv = uv * uv_skala;
    vec4 textur = texture(basisfarbe, tuv);
    vec3 basis = nach_linear(mix(grundton, textur.rgb, hat_basisfarbe)) * farbton;
    float alpha = alpha_faktor * mix(1.0, textur.a, hat_basisfarbe);
    if (makro > 0.0) {
        float r = 0.65 * rauschen(welt_position.xy / 30.0) + 0.35 * rauschen(welt_position.xy / 90.0 + 17.0);
        basis *= mix(1.0 - makro, 1.0 + makro * 0.7, r);
    }
    if (alpha_schwelle > 0.0 && alpha < alpha_schwelle) discard;

    /* glTF legt Rauheit in den Gruen- und Metallic in den Blaukanal. */
    vec2 mr = texture(metallic_rauheit, tuv).gb;
    float rauheit  = clamp(mix(1.0, mr.x, hat_metallic_rauheit) * rauheit_faktor, 0.04, 1.0);
    float metallic = clamp(mix(1.0, mr.y, hat_metallic_rauheit) * metallic_faktor, 0.0, 1.0);

    vec3 N = normalize(welt_normale);
    vec3 V = normalize(kamera_position - welt_position);
    if (dot(N, V) < 0.0) N = -N;      // Rueckseiten nicht schwarz werden lassen
    vec3 L = normalize(sonne_richtung);
    vec3 H = normalize(V + L);
    vec3 R = reflect(-V, N);

    float n_dot_v = max(dot(N, V), 1e-4);
    float n_dot_l = max(dot(N, L), 0.0);
    float schatten = sonnenlicht(N, L);

    vec3 f0 = mix(vec3(0.04), basis, metallic);

    /* --- Sonne ---------------------------------------------------------- */
    float d = verteilung_ggx(max(dot(N, H), 0.0), rauheit);
    float g = geometrie_smith(n_dot_v, max(n_dot_l, 1e-4), rauheit);
    vec3  f = fresnel_schlick(max(dot(H, V), 0.0), f0);
    vec3 spiegelnd = (d * g * f) / max(4.0 * n_dot_v * max(n_dot_l, 1e-4), 1e-6);
    vec3 streuend = (vec3(1.0) - f) * (1.0 - metallic) * basis / PI;
    vec3 licht = (streuend + spiegelnd) * sonne_farbe * n_dot_l * schatten;

    /* --- Umgebung -------------------------------------------------------- */
    /* Streuend: der ganze Himmel ueber der Flaeche, angenaehert durch die
       stark verwaschene Karte in Normalenrichtung. Im Schatten fehlt die
       Sonne, nicht der Himmel - aber etwas davon: ein Teil des Himmels ist
       vom Schattenwerfer verdeckt. */
    vec3 umgebung_streuend = himmel(N, 1.0) * basis * (1.0 - metallic) * (0.75 + 0.25 * schatten);
    vec3 umgebung_spiegelnd = himmel(R, sqrt(rauheit));
    vec3 fr = fresnel_rauh(n_dot_v, f0, rauheit);
    // Spiegelungen nach unten zeigen den Boden, nicht den Himmel; dunkler.
    umgebung_spiegelnd *= mix(0.35, 1.0, smoothstep(-0.15, 0.1, R.z));
    vec3 umgebung = umgebung_streuend * (vec3(1.0) - fr) + umgebung_spiegelnd * fr;

    vec3 farbe = licht + umgebung;

    /* --- Klarlack -------------------------------------------------------- */
    if (klarlack > 0.0) {
        float kf = 0.04 + 0.96 * pow(1.0 - n_dot_v, 5.0);
        float kd = verteilung_ggx(max(dot(N, H), 0.0), 0.06);
        float kg = geometrie_smith(n_dot_v, max(n_dot_l, 1e-4), 0.06);
        vec3 klar = vec3(kd * kg * kf / max(4.0 * n_dot_v * max(n_dot_l, 1e-4), 1e-6))
                    * sonne_farbe * n_dot_l * schatten;
        klar += himmel(R, 0.08) * kf * mix(0.35, 1.0, smoothstep(-0.15, 0.1, R.z));
        farbe = farbe * (1.0 - klarlack * kf) + klarlack * klar;
    }

    farbe += emission;

    /* --- Nebel ------------------------------------------------------------ */
    float abstand = length(kamera_position - welt_position);
    float nebel = 1.0 - exp(-pow(abstand * nebel_dichte * nebel_faktor, 1.6));
    vec3 dunst = mix(nebel_farbe, himmel(normalize(welt_position - kamera_position) * vec3(1.0, 1.0, 0.1), 0.6), 0.5);
    farbe = mix(farbe, dunst, clamp(nebel, 0.0, 1.0));

    farbe = aces(farbe * belichtung);
    farbe = pow(farbe, vec3(1.0 / 2.2));

    float grau = dot(farbe, vec3(0.2126, 0.7152, 0.0722));
    ausgabe = vec4(mix(farbe, vec3(grau), entfaerbung), deckkraft * alpha);
}
"""

# ---------------------------------------------------------------------------
# Schattenkarte: nur Tiefe
# ---------------------------------------------------------------------------

SCHATTEN_VERTEX = """
#version 330
uniform mat4 licht_mvp;
uniform mat4 modell;
in vec3 in_position;
in vec2 in_uv;
out vec2 uv;
void main() {
    uv = in_uv;
    gl_Position = licht_mvp * modell * vec4(in_position, 1.0);
}
"""

SCHATTEN_VERTEX_INSTANZ = """
#version 330
uniform mat4 licht_mvp;
in vec3 in_position;
in vec2 in_uv;
in vec4 in_inst0;
in vec4 in_inst1;
in vec4 in_inst2;
in vec4 in_inst3;
out vec2 uv;
void main() {
    uv = in_uv;
    gl_Position = licht_mvp * mat4(in_inst0, in_inst1, in_inst2, in_inst3) * vec4(in_position, 1.0);
}
"""

SCHATTEN_FRAGMENT = """
#version 330
uniform sampler2D basisfarbe;
uniform float alpha_schwelle;
in vec2 uv;
void main() {
    // Laub wirft den Schatten seiner Blaetter, nicht den seiner Karten.
    if (alpha_schwelle > 0.0 && texture(basisfarbe, uv).a < alpha_schwelle) discard;
}
"""

# ---------------------------------------------------------------------------
# Himmel als Hintergrund
# ---------------------------------------------------------------------------

HIMMEL_VERTEX = """
#version 330
in vec2 in_ecke;
out vec2 ndc;
void main() {
    ndc = in_ecke;
    gl_Position = vec4(in_ecke, 0.9999, 1.0);
}
"""

HIMMEL_FRAGMENT = """
#version 330
const float PI = 3.14159265359;
uniform mat4 inverse_vp;
uniform vec3 kamera_position;
uniform sampler2D himmel_karte;
uniform float hat_himmel;
uniform vec3 himmel_zenit;
uniform vec3 himmel_horizont;
uniform vec3 boden_farbe;
uniform vec3 sonne_richtung;
uniform vec3 nebel_farbe;
uniform float himmel_helligkeit;
uniform float belichtung;
in vec2 ndc;
out vec4 ausgabe;

vec3 nach_linear(vec3 srgb) { return pow(max(srgb, vec3(0.0)), vec3(2.2)); }
vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
}

void main() {
    vec4 fern = inverse_vp * vec4(ndc, 1.0, 1.0);
    vec3 d = normalize(fern.xyz / fern.w - kamera_position);
    vec3 farbe;
    if (hat_himmel > 0.5) {
        vec3 dd = d;
        dd.z = max(dd.z, 0.0);
        dd = normalize(dd);
        vec2 st = vec2(0.5 + atan(dd.y, dd.x) / (2.0 * PI), 0.5 + asin(dd.z) / PI);
        farbe = nach_linear(textureLod(himmel_karte, st, 0.0).rgb) * himmel_helligkeit;
    } else {
        farbe = mix(himmel_horizont, himmel_zenit, pow(max(d.z, 0.0), 0.6));
    }
    // Zum Horizont hin in den Dunst der Welt uebergehen.
    float dunst = 1.0 - smoothstep(0.0, 0.12, d.z);
    farbe = mix(farbe, nebel_farbe, dunst * 0.8);
    if (d.z < 0.0) farbe = mix(nebel_farbe, boden_farbe, clamp(-d.z * 2.0, 0.0, 1.0));
    // Die Sonne selbst: im LDR-Bild abgeschnitten, hier zurueckgegeben.
    float s = max(dot(d, normalize(sonne_richtung)), 0.0);
    farbe += vec3(1.0, 0.95, 0.85) * (pow(s, 2000.0) * 40.0 + pow(s, 60.0) * 0.4);
    farbe = aces(farbe * belichtung);
    ausgabe = vec4(pow(farbe, vec3(1.0 / 2.2)), 1.0);
}
"""

#: Vorgaben für einen hellen Tag, wenn kein Thema etwas anderes sagt.
HIMMEL_ZENIT = (0.28, 0.44, 0.78)
HIMMEL_HORIZONT = (0.72, 0.80, 0.92)
BODEN_FARBE = (0.20, 0.22, 0.18)
SONNE_RICHTUNG = (0.35, 0.45, 0.82)
SONNE_FARBE = (3.0, 2.85, 2.6)


def setzen(p, name: str, wert) -> None:
    """Ein Uniform setzen, wenn der Compiler es nicht wegoptimiert hat."""
    try:
        p[name].value = wert
    except KeyError:
        pass


def matrix_setzen(p, name: str, m: np.ndarray) -> None:
    try:
        p[name].write(np.ascontiguousarray(np.asarray(m, dtype="f4").T).tobytes())
    except KeyError:
        pass


def _vorgaben(p) -> None:
    for name, wert in (
        ("basisfarbe", 0), ("metallic_rauheit", 1), ("himmel_karte", 2),
        ("schatten_karte", 3),
        ("hat_basisfarbe", 0.0), ("hat_metallic_rauheit", 0.0),
        ("hat_himmel", 0.0), ("hat_schatten", 0.0),
        ("grundton", (0.5, 0.5, 0.5)), ("metallic_faktor", 1.0),
        ("rauheit_faktor", 1.0), ("emission", (0.0, 0.0, 0.0)),
        ("klarlack", 0.0), ("alpha_faktor", 1.0), ("alpha_schwelle", 0.0),
        ("uv_skala", 1.0), ("farbton", (1.0, 1.0, 1.0)), ("makro", 0.0),
        ("entfaerbung", 0.0), ("deckkraft", 1.0),
        ("himmel_zenit", HIMMEL_ZENIT), ("himmel_horizont", HIMMEL_HORIZONT),
        ("boden_farbe", BODEN_FARBE),
        ("sonne_richtung", tuple(np.asarray(SONNE_RICHTUNG) / np.linalg.norm(SONNE_RICHTUNG))),
        ("sonne_farbe", SONNE_FARBE), ("himmel_mips", 8.0),
        ("himmel_helligkeit", 1.0), ("nebel_farbe", HIMMEL_HORIZONT),
        ("nebel_dichte", 0.0), ("nebel_faktor", 1.0), ("belichtung", 1.0),
    ):
        setzen(p, name, wert)
    matrix_setzen(p, "licht_mvp", np.eye(4))


def programm(ctx):
    """Das PBR-Programm für Einzelteile (Modellmatrix als Uniform)."""
    p = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
    _vorgaben(p)
    return p


def programm_instanz(ctx):
    """Das PBR-Programm für instanziertes Zeichnen."""
    p = ctx.program(vertex_shader=VERTEX_INSTANZ, fragment_shader=FRAGMENT)
    _vorgaben(p)
    return p


def schattenprogramm(ctx, instanz: bool = False):
    p = ctx.program(vertex_shader=SCHATTEN_VERTEX_INSTANZ if instanz else SCHATTEN_VERTEX,
                    fragment_shader=SCHATTEN_FRAGMENT)
    setzen(p, "basisfarbe", 0)
    setzen(p, "alpha_schwelle", 0.0)
    matrix_setzen(p, "modell", np.eye(4))
    return p


def himmelprogramm(ctx):
    p = ctx.program(vertex_shader=HIMMEL_VERTEX, fragment_shader=HIMMEL_FRAGMENT)
    _vorgaben(p)
    return p


def normalmatrix(modell: np.ndarray) -> np.ndarray:
    """Die inverse Transponierte des Rotations- und Skalierungsteils."""
    m = np.asarray(modell, dtype=np.float64)[:3, :3]
    return np.linalg.inv(m).T.astype(np.float32)


def modell_setzen(p, modell: np.ndarray) -> None:
    """Modellmatrix und die dazu passende Normalmatrix hochladen."""
    p["modell"].write(np.asarray(modell, dtype=np.float32).T.tobytes())
    try:
        p["normalmatrix"].write(
            np.ascontiguousarray(normalmatrix(modell).T, dtype="f4").tobytes())
    except KeyError:
        pass
