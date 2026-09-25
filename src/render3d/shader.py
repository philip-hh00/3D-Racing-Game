"""PBR-Beleuchtung: Lack sieht aus wie Lack, Reifen wie Gummi.

**Alle Programme liefern lineares HDR, Tonemapping in nachbearbeitung.py.**
Kein ``aces``, kein Gamma, keine Belichtung in einem Fragment-Shader hier —
wer ein neues Programm schreibt, gibt Licht in linearen Einheiten aus
(Werte über 1 sind erlaubt und erwünscht: daraus wird Bloom). Die Welt
wird in einen RGBA16F-Zwischenpuffer gezeichnet; Belichtung, ACES, Gamma,
Farbkorrektur und Glättung macht :mod:`src.render3d.nachbearbeitung`.

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

/* === Strang S: Asphalt der Fahrbahn (Anfang) ==============================
   Nur fuer die Fahrbahn (asphalt > 0), gesetzt von
   rennszene._strecke_hochladen. uv ist dort in Metern: x quer ab der linken
   Kante, y entlang der Mittellinie (Bogenlaenge ab der Ziellinie). Alles
   entsteht in diesen Streckenkoordinaten und kachelt deshalb nicht: Bahnen
   des Fertigers, heller Rand, Gummi der Ideallinie (Maske aus
   track_mesh.gummi_maske), Flicken, Risse, Linien und die Ziellinie. */
uniform float asphalt;            // 0 aus, 1 einfach, 2 mit Flicken, Rissen, Kachelbruch
uniform sampler2D strecken_maske; // r: Gummiabrieb
uniform vec2  strecke_mass;       // Breite, Laenge (m)
uniform vec4  strecke_linien;     // Randlinie ab Kante (0: keine), Linienbreite, Mittellinie (0/1), Gelbanteil

/* 1 auf einer Linie der halben Breite hb um abstand = 0, weich ueber ein Pixel. */
float s_linie(float abstand, float hb) {
    float w = max(fwidth(abstand), 1e-4);
    return 1.0 - smoothstep(hb - w, hb + w, abs(abstand));
}

/* Ein Riss entlang einer Hoehenlinie des Rauschens, ``breite`` in Metern.
   Der Abstand zur Linie wird durch das Gefaelle des Rauschens geteilt —
   sonst wird der Riss dort, wo das Rauschen flach ist, zur breiten Pfuetze.
   In der Ferne blendet er aus, statt zu flimmern. */
float s_riss(float r, float hoehe, float breite, float pixel_m) {
    float gefaelle = max(length(vec2(dFdx(r), dFdy(r))) / pixel_m, 1e-3);
    float d = abs(r - hoehe) / gefaelle;
    return (1.0 - smoothstep(breite, breite + pixel_m, d)) * clamp(breite / pixel_m * 2.0, 0.0, 1.0);
}

void asphalt_details(inout vec3 basis, inout float rauheit) {
    vec2 m = uv;
    float breite = strecke_mass.x;
    float kante = min(m.x, breite - m.x);
    if (asphalt > 1.5 && hat_basisfarbe > 0.5) {
        // Kachelbruch: eine zweite, gedrehte Probe, nach Rauschen eingemischt.
        // Nur mit gesetzter Basistextur — sonst liegt auf Einheit 0 irgendetwas.
        vec2 q = mat2(0.8, -0.6, 0.6, 0.8) * (m * uv_skala * 0.71) + vec2(0.37, 0.61);
        vec3 zweit = nach_linear(texture(basisfarbe, q).rgb) * farbton;
        basis = mix(basis, zweit, smoothstep(0.3, 0.7, rauschen(welt_position.xy / 6.0 + 3.1)));
    }
    // Die Asphalttextur ist fast schwarz und sehr koernig; eingefaerbt auf
    // ein glaubhaftes Grau wuerde jedes Korn zum Fleck. Kontrast und
    // Saettigung zur Mitte hin zusammenziehen.
    vec3 mittel = farbton * 0.0105;
    basis = mix(mittel, basis, 0.55);
    basis = mix(vec3(dot(basis, vec3(0.3, 0.59, 0.11))), basis, 0.35);
    // Bahnen des Fertigers (laengs gestreckt) und grossflaechige Schwankung.
    float bahn = rauschen(vec2(m.x / 4.2, m.y / 70.0));
    float gross = rauschen(vec2(m.x / 16.0, m.y / 40.0) + 5.0);
    basis *= 0.86 + 0.14 * bahn + 0.12 * gross;
    // Heller Rand: Staub und kaum befahren.
    basis *= 1.0 + 0.22 * (1.0 - smoothstep(0.2, 3.2, kante)) * (0.7 + 0.6 * rauschen(m * vec2(1.3, 0.2)));
    // Gummi der Ideallinie, in Laengsstreifen.
    float gummi = texture(strecken_maske, vec2(m.x / breite, m.y / strecke_mass.y)).r;
    gummi *= 0.7 + 0.3 * rauschen(vec2(m.x * 3.1, m.y * 0.07));
    basis *= 1.0 - 0.62 * gummi;
    rauheit *= 1.0 - 0.2 * gummi;
    if (asphalt > 1.5) {
        // Flicken: rechteckige Ausbesserungen, je Zelle hoechstens einer.
        vec2 zelle = vec2(7.3, 26.0);
        vec2 id = floor(m / zelle);
        vec2 lokal = m - id * zelle;
        // Ohne Verzweigung: fwidth braucht alle Nachbarpixel im selben Zweig.
        float da = step(rauschen_hash(id + 11.0), 0.13);
        vec2 gr = vec2(1.6 + 3.4 * rauschen_hash(id + 3.0), 2.2 + 13.0 * rauschen_hash(id + 5.0));
        gr = min(gr, zelle - 0.8);
        vec2 ecke = 0.4 + (zelle - 0.8 - gr) * vec2(rauschen_hash(id + 7.0), rauschen_hash(id + 9.0));
        vec2 d = abs(lokal - ecke - gr * 0.5) - gr * 0.5;
        float innen = max(d.x, d.y);
        float w = max(fwidth(innen), 1e-4);
        float flick = (1.0 - smoothstep(-w, w, innen)) * da;
        float ton = 0.68 + 0.14 * rauschen_hash(id + 13.0);
        basis *= mix(1.0, ton * (0.92 + 0.16 * rauschen(m * 1.7)), flick);
        basis *= 1.0 - 0.45 * s_linie(innen, 0.035) * da;
        rauheit *= mix(1.0, 0.88, flick);
        // Risse nur in manchen Abschnitten: vergossene Fugen (dunkel,
        // glaenzend) und feine Haarrisse.
        float zone = smoothstep(0.62, 0.8, rauschen(m / vec2(9.0, 30.0) + 41.0));
        // Laengsrisse laufen mit der Fahrbahn, Querrisse quer dazu; ein
        // wenig feineres Rauschen macht sie unruhig statt glatt.
        float rl = rauschen(m * vec2(0.35, 0.025) + 31.0) * 0.9 + rauschen(m * vec2(2.5, 0.4) + 7.0) * 0.1;
        float rq = rauschen(m * vec2(0.04, 0.25) + 13.0) * 0.9 + rauschen(m * vec2(0.5, 2.2) + 3.0) * 0.1;
        float pixel_m = max(length(fwidth(m)), 1e-4);
        float verguss = max(s_riss(rl, 0.5, 0.02, pixel_m), s_riss(rq, 0.5, 0.016, pixel_m)) * zone;
        float r2 = rauschen(m * vec2(2.2, 1.6) + 57.0) * 0.6 + rauschen(m * 5.3 + 3.0) * 0.4;
        float haar = s_riss(r2, 0.5, 0.005, pixel_m) * zone * 0.6;
        basis *= 1.0 - 0.5 * verguss - 0.35 * haar;
        rauheit *= 1.0 - 0.12 * verguss;
        // Laengsnaht zwischen zwei Fertigerbahnen.
        basis *= 1.0 - 0.12 * s_linie(m.x - breite * 0.37, 0.03);
    }
    // Linien: weiss oder gelb, abgefahren, wo der Gummi liegt.
    vec3 lack = mix(vec3(0.78, 0.78, 0.76), vec3(0.78, 0.55, 0.08), strecke_linien.w);
    float hb = strecke_linien.y * 0.5;
    float farbe = 0.0;
    if (strecke_linien.x > 0.0) farbe = s_linie(kante - strecke_linien.x - hb, hb);
    if (strecke_linien.z > 0.5) {
        float strich = s_linie(fract(m.y / 9.0) - 0.25, 0.25);
        farbe = max(farbe, s_linie(m.x - breite * 0.5, hb) * strich);
    }
    // Ziellinie: Karos ueber die ganze Breite, 1,6 m lang, um y = 0.
    float s = mod(m.y + 0.8, strecke_mass.y) - 0.8;
    vec2 karo = floor(vec2(m.x, s + 0.8) / 0.4);
    float dunkel = mod(karo.x + karo.y, 2.0);
    float ziel = s_linie(s, 0.8);
    basis = mix(basis, mix(lack, vec3(0.012), dunkel), ziel);
    rauheit = mix(rauheit, 0.6, ziel);
    farbe *= (0.8 + 0.2 * rauschen(m * vec2(2.0, 0.5))) * (1.0 - 0.6 * gummi);
    basis = mix(basis, lack, farbe);
    rauheit = mix(rauheit, 0.55, farbe);
}
/* === Strang S: Asphalt der Fahrbahn (Ende) ============================== */

/* === Strang W: Gelaende (Anfang, gelaende.py) ===========================
   Bodentexturen nach Hang und Hoehe mischen: unten Gras oder Sand, am Hang
   Fels mit Gras oder Sandstein, steil nackter Fels (von der Seite
   projiziert, sonst zieht er sich zu Streifen), oben Schnee, in der Ferne
   Wald als Farbe. Nur aktiv, wenn `gelaende` > 0.5 - alle anderen Flaechen
   laufen am Block vorbei. */
uniform float gelaende;
uniform sampler2D gelaende_unten;
uniform sampler2D gelaende_hang;
uniform sampler2D gelaende_fels;
uniform vec3  gelaende_kachel;      // 1/m je Schicht: unten, hang, fels
uniform vec3  gelaende_ton_unten;
uniform vec3  gelaende_ton_hang;
uniform vec3  gelaende_ton_fels;
uniform vec4  gelaende_grenzen;     // hang_ab, fels_ab (1 - n.z), hang_hoehe_m, schnee_ab_m (<0: keiner)
uniform vec4  gelaende_wald;        // Farbe sRGB, a = ab_m vom Streckenrechteck (<0: kein Wald)
uniform vec4  gelaende_rechteck;    // Mitte xy, halbe Ausdehnung xy

vec3 gelaende_probe(sampler2D t, vec2 p) {
    return pow(max(texture(t, p).rgb, vec3(0.0)), vec3(2.2));
}

/* Aus drei Richtungen projiziert, nach der Normalen gewichtet (b). In der
   Ferne gut dreimal groesser gekachelt: an einem Hang in 300 m reihen sich
   sonst die Kacheln zu sichtbaren Baendern. */
vec3 gelaende_dreifach_k(sampler2D t, vec3 p, float k, vec3 b) {
    return gelaende_probe(t, p.yz * k) * b.x + gelaende_probe(t, p.xz * k) * b.y
         + gelaende_probe(t, p.xy * k) * b.z;
}

vec3 gelaende_dreifach(sampler2D t, vec3 p, float k, vec3 b) {
    float fern = smoothstep(70.0, 260.0, length(kamera_position - p));
    if (fern < 0.01) return gelaende_dreifach_k(t, p, k, b);
    vec3 grob = gelaende_dreifach_k(t, p + 13.7, k * 0.29, b);
    if (fern > 0.99) return grob;
    return mix(gelaende_dreifach_k(t, p, k, b), grob, fern);
}

vec3 gelaende_basis(vec3 p, vec3 n) {
    float r1 = rauschen(p.xy / 13.0);
    float r2 = rauschen(p.xy / 57.0 + 3.7);
    float steil = 1.0 - clamp(n.z, 0.0, 1.0) + (r1 - 0.5) * 0.08;
    // Unten zweimal in verschiedenem Massstab und gedreht - gegen Kacheln.
    vec2 q = p.xy * gelaende_kachel.x;
    vec3 unten = mix(gelaende_probe(gelaende_unten, q),
                     gelaende_probe(gelaende_unten, vec2(q.y, -q.x) * 0.31 + 0.17),
                     0.25 + 0.3 * r2) * gelaende_ton_unten;
    float w_hang = smoothstep(gelaende_grenzen.x - 0.05, gelaende_grenzen.x + 0.07, steil);
    w_hang = max(w_hang, smoothstep(gelaende_grenzen.z - 4.0, gelaende_grenzen.z + 4.0,
                                    p.z + (r2 - 0.5) * 10.0));
    vec3 farbe = unten;
    vec3 b = pow(abs(n), vec3(4.0));
    b /= (b.x + b.y + b.z);
    if (w_hang > 0.001) {
        // Flach von oben, am Hang von der Seite - sonst zieht sich die
        // Textur zu Streifen. Weich gewichtet, damit keine Naht entsteht.
        vec3 hang = gelaende_dreifach(gelaende_hang, p, gelaende_kachel.y, b);
        farbe = mix(unten, hang * gelaende_ton_hang, w_hang);
    }
    float w_fels = smoothstep(gelaende_grenzen.y - 0.06, gelaende_grenzen.y + 0.1, steil);
    if (w_fels > 0.001) {
        vec3 fels = gelaende_dreifach(gelaende_fels, p, gelaende_kachel.z, b) * gelaende_ton_fels;
        farbe = mix(farbe, fels, w_fels);
    }
    if (gelaende_wald.a >= 0.0) {
        vec2 aussen = max(abs(p.xy - gelaende_rechteck.xy) - gelaende_rechteck.zw, vec2(0.0));
        float r = length(aussen) + (r2 - 0.5) * 120.0;
        float krone = 0.6 * rauschen(p.xy / 7.0) + 0.4 * rauschen(p.xy / 2.3 + 9.1);
        float w = smoothstep(gelaende_wald.a, gelaende_wald.a * 1.5, r) * (1.0 - w_fels)
                * smoothstep(0.3, 0.5, r1 * 0.5 + r2 * 0.7);
        vec3 wald = pow(gelaende_wald.rgb, vec3(2.2)) * (0.5 + 0.8 * krone);
        farbe = mix(farbe, wald, w);
    }
    if (gelaende_grenzen.w >= 0.0) {
        float w_schnee = smoothstep(gelaende_grenzen.w - 30.0, gelaende_grenzen.w + 30.0,
                                    p.z + (r2 - 0.5) * 120.0 + (r1 - 0.5) * 30.0)
                       * (1.0 - smoothstep(0.38, 0.62, steil));
        farbe = mix(farbe, vec3(0.80, 0.83, 0.88) * (0.92 + 0.12 * r1), w_schnee);
    }
    return farbe;
}
/* === Strang W: Gelaende (Ende) ========================================== */

/* === Strang W2: Gelaendeschatten (Anfang, licht.Gelaendesicht) ===========
   Die Sonnensichtkarte: je Texel die Hoehe, ab der ein Punkt die Sonne
   sieht (r), und der Abstand zum Verdecker (g). Das Raster ist nach der
   Sonne gedreht; die Weltposition kommt ueber zwei Skalarprodukte hinein.
   Eine ferne Karte ueber das ganze Gelaende, eine feine ueber das Gitter um
   die Strecke, zum Rand der feinen hin weich ineinander. Gilt fuer alles,
   was mit diesem Shader gezeichnet wird: Boden, Strecke, Deko, Autos -
   wer hoeher steht als die Grenze, steht in der Sonne. */
uniform float sicht_an;          // 0 aus, 1 nur fern, 2 fern und nah
uniform sampler2D sicht_fern;
uniform sampler2D sicht_nah;
uniform vec2  sicht_achse;       // waagerecht zur Sonne, normiert
uniform vec4  sicht_fern_raster; // u0, v0, 1/Laenge u, 1/Laenge v
uniform vec4  sicht_nah_raster;
uniform vec3  sicht_weich;       // Mindestbreite fern, nah (m, senkrecht); Halbschatten (tan)

float sicht_probe(sampler2D karte, vec2 uv, float z, float mindest) {
    vec2 gt = texture(karte, uv).rg;
    float breite = max(mindest, gt.y * sicht_weich.z);
    float s = clamp(0.5 + (z - gt.x) / breite, 0.0, 1.0);
    return s * s * (3.0 - 2.0 * s);
}

float gelaende_sicht(vec3 p) {
    if (sicht_an < 0.5) return 1.0;
    vec2 q = vec2(dot(p.xy, sicht_achse), dot(p.xy, vec2(-sicht_achse.y, sicht_achse.x)));
    // Erst die feine Karte; wer ganz in ihr liegt, braucht die ferne nicht.
    float nah = 0.0;
    float licht_nah = 1.0;
    if (sicht_an > 1.5) {
        vec2 uv_nah = (q - sicht_nah_raster.xy) * sicht_nah_raster.zw;
        vec2 r = min(uv_nah, 1.0 - uv_nah);
        nah = smoothstep(0.0, 0.05, min(r.x, r.y));
        if (nah > 0.0) licht_nah = sicht_probe(sicht_nah, uv_nah, p.z, sicht_weich.y);
        if (nah >= 1.0) return licht_nah;
    }
    vec2 uv = (q - sicht_fern_raster.xy) * sicht_fern_raster.zw;
    vec2 rand = min(uv, 1.0 - uv);
    // Hinter dem letzten Ring gibt es kein Gelaende mehr: dort Sonne.
    float licht = mix(1.0, sicht_probe(sicht_fern, uv, p.z, sicht_weich.x),
                      smoothstep(0.0, 0.01, min(rand.x, rand.y)));
    return mix(licht, licht_nah, nah);
}
/* === Strang W2: Gelaendeschatten (Ende) ================================= */

void main() {
    vec2 tuv = uv * uv_skala;
    vec4 textur = texture(basisfarbe, tuv);
    vec3 basis = nach_linear(mix(grundton, textur.rgb, hat_basisfarbe)) * farbton;
    if (gelaende > 0.5) basis = gelaende_basis(welt_position, normalize(welt_normale));  // Strang W
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
    if (asphalt > 0.0) asphalt_details(basis, rauheit);   // Strang S

    vec3 N = normalize(welt_normale);
    vec3 V = normalize(kamera_position - welt_position);
    if (dot(N, V) < 0.0) N = -N;      // Rueckseiten nicht schwarz werden lassen
    vec3 L = normalize(sonne_richtung);
    vec3 H = normalize(V + L);
    vec3 R = reflect(-V, N);

    float n_dot_v = max(dot(N, V), 1e-4);
    float n_dot_l = max(dot(N, L), 0.0);
    float schatten = sonnenlicht(N, L) * gelaende_sicht(welt_position);  // Strang W2

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

    // Lineares HDR: Abbildung und Gamma macht die Nachbearbeitung.
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
in vec2 ndc;
out vec4 ausgabe;

vec3 nach_linear(vec3 srgb) { return pow(max(srgb, vec3(0.0)), vec3(2.2)); }

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
    ausgabe = vec4(farbe, 1.0);
}
"""

#: Vorgaben für einen hellen Tag, wenn kein Thema etwas anderes sagt.
HIMMEL_ZENIT = (0.28, 0.44, 0.78)
HIMMEL_HORIZONT = (0.72, 0.80, 0.92)
BODEN_FARBE = (0.20, 0.22, 0.18)
SONNE_RICHTUNG = (0.35, 0.45, 0.82)
SONNE_FARBE = (3.0, 2.85, 2.6)


def setzen(p, name: str, wert) -> None:
    """Ein Uniform setzen, wenn der Compiler es nicht wegoptimiert hat.

    Unverändertes wird übersprungen: acht Autos mit je fast 40 Stücken und gut
    zehn Uniforms pro Stück sind einige tausend Aufrufe je Bild, und die
    meisten setzen, was schon drinsteht (vier gleiche Räder, gleiches Chrom).
    Gemessen kostete das rund 7 ms je Bild auf der CPU. Der Merkzettel hängt
    am Programm selbst — ein neues Programm fängt leer an.
    """
    stand = getattr(p, "_zuletzt", None)
    if stand is None:
        stand = {}
        try:
            p._zuletzt = stand
        except AttributeError:                       # pragma: no cover - Attrappen
            pass
    if name in stand and stand[name] == wert:
        return
    try:
        p[name].value = wert
    except KeyError:
        pass
    stand[name] = wert


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
        ("nebel_dichte", 0.0), ("nebel_faktor", 1.0),
        ("sicht_an", 0.0), ("sicht_fern", 12), ("sicht_nah", 13),   # Strang W2
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
