"""PBR-Beleuchtung: Lack sieht aus wie Lack, Reifen wie Gummi.

TRELLIS 2 liefert echte Materialkanäle — Base Color, Roughness, Metallic —
statt eingebackener Beleuchtung. Genau deswegen ist es hier die richtige Wahl,
und genau deshalb muss der Shader sie auch benutzen. Ein einzelnes
Richtungslicht auf der Basisfarbe wirft sie weg; das Fahrzeug wirkt dann flach
und stumpf, obwohl das Modell mehr hergibt.

**Ohne Umgebung ist Metall schwarz.** Eine metallische Fläche hat keine
diffuse Streuung, sie zeigt nur, was um sie herum ist. Vor einem schwarzen
Nichts zeigt sie nichts. Deshalb steht hier ein Himmel im Shader — ein
Farbverlauf von Horizont zu Zenit plus eine Sonne. Er ersetzt keine
Umgebungskarte, aber er ist der Unterschied zwischen einem Auto und einer
Silhouette.

Gerechnet wird Cook-Torrance mit GGX-Verteilung, Smith-Geometrie und
Schlick-Fresnel — das Übliche, und das, was auch der Betrachter von ComfyUI
zeigt.
"""
from __future__ import annotations

import numpy as np

VERTEX = """
#version 330

uniform mat4 mvp;
uniform mat4 modell;
uniform mat3 normalmatrix;

in vec3 in_position;
in vec3 in_normale;
in vec2 in_uv;

out vec3 welt_position;
out vec3 welt_normale;
out vec2 uv;

void main() {
    vec4 welt = modell * vec4(in_position, 1.0);
    welt_position = welt.xyz;
    // Normalen brauchen die inverse Transponierte, sonst stehen sie nach einer
    // ungleichmaessigen Skalierung schief auf der Flaeche. Hier wird nie
    // ungleichmaessig skaliert, aber der Aufwand ist eine Matrix und der
    // Fehler waere schwer zu finden.
    welt_normale = normalmatrix * in_normale;
    uv = in_uv;
    gl_Position = mvp * welt;
}
"""

FRAGMENT = """
#version 330

const float PI = 3.14159265359;

uniform sampler2D basisfarbe;
uniform sampler2D metallic_rauheit;
uniform float hat_basisfarbe;
uniform float hat_metallic_rauheit;
uniform vec3  grundton;          // wenn keine Textur da ist
uniform float metallic_faktor;
uniform float rauheit_faktor;

uniform vec3 kamera_position;
uniform vec3 sonne_richtung;     // zeigt ZUR Sonne, normiert
uniform vec3 sonne_farbe;
uniform vec3 himmel_zenit;
uniform vec3 himmel_horizont;
uniform vec3 boden_farbe;

in vec3 welt_position;
in vec3 welt_normale;
in vec2 uv;

out vec4 ausgabe;

/* Der Himmel als Funktion einer Richtung. Ersetzt die Umgebungskarte:
   oben Zenitfarbe, am Horizont heller, darunter der Boden. */
vec3 himmel(vec3 richtung) {
    float hoch = richtung.z;
    if (hoch < 0.0) {
        return mix(himmel_horizont, boden_farbe, clamp(-hoch * 2.0, 0.0, 1.0));
    }
    return mix(himmel_horizont, himmel_zenit, pow(hoch, 0.6));
}

/* GGX: wie stark die Mikroflaechen in Richtung h zeigen. */
float verteilung_ggx(float n_dot_h, float rauheit) {
    float a = rauheit * rauheit;
    float a2 = a * a;
    float nenner = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / max(PI * nenner * nenner, 1e-7);
}

/* Smith: wieviel sich die Mikroflaechen gegenseitig verdecken. */
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

/* Base Color liegt in glTF **sRGB-codiert** vor, gerechnet wird aber linear.
   Ohne diese Umrechnung sind Mitteltoene rund doppelt so hell wie sie sein
   sollten: das Bild wirkt flau und ausgewaschen, Farben blass. Der
   Metallic-Roughness-Kanal ist dagegen lineare Messgroesse und bleibt, wie er
   ist - ihn mitzurechnen waere derselbe Fehler in der anderen Richtung. */
vec3 nach_linear(vec3 srgb) {
    return pow(srgb, vec3(2.2));
}

void main() {
    vec3 basis = nach_linear(
        mix(grundton, texture(basisfarbe, uv).rgb, hat_basisfarbe));

    /* glTF legt Rauheit in den Gruen- und Metallic in den Blaukanal. */
    vec2 mr = texture(metallic_rauheit, uv).gb;
    float rauheit  = clamp(mix(1.0, mr.x, hat_metallic_rauheit) * rauheit_faktor, 0.04, 1.0);
    float metallic = clamp(mix(0.0, mr.y, hat_metallic_rauheit) * metallic_faktor, 0.0, 1.0);

    vec3 N = normalize(welt_normale);
    vec3 V = normalize(kamera_position - welt_position);
    if (dot(N, V) < 0.0) N = -N;      // Rueckseiten nicht schwarz werden lassen
    vec3 L = normalize(sonne_richtung);
    vec3 H = normalize(V + L);
    vec3 R = reflect(-V, N);

    float n_dot_v = max(dot(N, V), 1e-4);
    float n_dot_l = max(dot(N, L), 0.0);

    /* Nichtmetalle spiegeln rund vier Prozent, Metalle in ihrer eigenen Farbe. */
    vec3 f0 = mix(vec3(0.04), basis, metallic);

    /* --- Sonne ---------------------------------------------------------- */
    float d = verteilung_ggx(max(dot(N, H), 0.0), rauheit);
    float g = geometrie_smith(n_dot_v, max(n_dot_l, 1e-4), rauheit);
    vec3  f = fresnel_schlick(max(dot(H, V), 0.0), f0);
    vec3 spiegelnd = (d * g * f) / max(4.0 * n_dot_v * max(n_dot_l, 1e-4), 1e-6);
    vec3 streuend = (vec3(1.0) - f) * (1.0 - metallic) * basis / PI;
    vec3 licht = (streuend + spiegelnd) * sonne_farbe * n_dot_l;

    /* --- Umgebung -------------------------------------------------------- */
    /* Streuend: was der ganze Himmel ueber dieser Flaeche beitraegt. Statt
       einer Integration die Farbe in Normalenrichtung - fuer einen glatten
       Farbverlauf ist der Fehler klein und die Ersparnis gross. */
    vec3 umgebung_streuend = himmel(N) * basis * (1.0 - metallic);

    /* Spiegelnd: was aus der Spiegelrichtung kommt. Mit steigender Rauheit
       verwaschen zur mittleren Himmelsfarbe - das ersetzt die vorgefilterten
       Stufen einer echten Umgebungskarte. */
    vec3 mittel = mix(himmel_horizont, himmel_zenit, 0.5);
    vec3 umgebung_spiegelnd = mix(himmel(R), mittel, rauheit);
    vec3 fr = fresnel_rauh(n_dot_v, f0, rauheit);

    vec3 umgebung = umgebung_streuend * (vec3(1.0) - fr) + umgebung_spiegelnd * fr;

    vec3 farbe = licht + umgebung;

    /* Reinhard und Gamma. Ohne beides brennen die Glanzlichter aus und die
       Mitten sind zu dunkel - eine PBR-Rechnung liefert lineare Energie, kein
       fertiges Bild. */
    farbe = farbe / (farbe + vec3(1.0));
    farbe = pow(farbe, vec3(1.0 / 2.2));
    ausgabe = vec4(farbe, 1.0);
}
"""

#: Vorgaben für einen bedeckten, hellen Tag. Der Zenit ist kräftiger als der
#: Horizont, weil ein Himmel nach oben hin dunkler und satter wird.
HIMMEL_ZENIT = (0.28, 0.44, 0.78)
HIMMEL_HORIZONT = (0.72, 0.80, 0.92)
BODEN_FARBE = (0.20, 0.22, 0.18)
SONNE_RICHTUNG = (0.35, 0.45, 0.82)
SONNE_FARBE = (3.0, 2.85, 2.6)


def programm(ctx):
    """Das PBR-Programm bauen und mit brauchbaren Vorgaben belegen."""
    p = ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
    p["basisfarbe"].value = 0
    p["metallic_rauheit"].value = 1
    p["hat_basisfarbe"].value = 0.0
    p["hat_metallic_rauheit"].value = 0.0
    p["grundton"].value = (0.5, 0.5, 0.5)
    p["metallic_faktor"].value = 1.0
    p["rauheit_faktor"].value = 1.0
    p["himmel_zenit"].value = HIMMEL_ZENIT
    p["himmel_horizont"].value = HIMMEL_HORIZONT
    p["boden_farbe"].value = BODEN_FARBE
    p["sonne_richtung"].value = tuple(
        np.asarray(SONNE_RICHTUNG) / np.linalg.norm(SONNE_RICHTUNG))
    p["sonne_farbe"].value = SONNE_FARBE
    return p


def normalmatrix(modell: np.ndarray) -> np.ndarray:
    """Die inverse Transponierte des Rotations- und Skalierungsteils.

    Als 3x3, weil eine Verschiebung Normalen nichts angeht.
    """
    m = np.asarray(modell, dtype=np.float64)[:3, :3]
    return np.linalg.inv(m).T.astype(np.float32)


def modell_setzen(p, modell: np.ndarray) -> None:
    """Modellmatrix und die dazu passende Normalmatrix hochladen."""
    p["modell"].write(np.asarray(modell, dtype=np.float32).T.tobytes())
    p["normalmatrix"].write(
        np.ascontiguousarray(normalmatrix(modell).T, dtype="f4").tobytes())
