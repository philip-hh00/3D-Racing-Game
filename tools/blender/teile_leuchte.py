"""Eigenständige Rückleuchten-Einheiten für ``fahrzeug_bauen.py``.

Läuft **in Blender**. Anders als die einfache LED-Leiste aus ``teile.py``
(``led_am_rand``/``_led_bauen``, weiter für Front- und Nebenleuchten in
Gebrauch) baut diese Bibliothek eine Rückleuchte als eigenständiges Bauteil
mit Kammern, Reflektor/Wabenstruktur und mehreren, getrennt sichtbaren
Funktionen (Schlusslicht, Bremslicht, Blinker, Rückfahrlicht, Rückstrahler)
unter einer gewölbten Streuscheibe mit Dicke — wie eine echte Leuchteneinheit,
die in eine Öffnung der Karosserie gesetzt wird.

Eingeschaltet wird sie je Leuchtenzone mit einem Block ``"einheit"`` unter
``"leuchte"`` in ``tools/blender/fahrzeuge/<key>.json``::

    "leuchte": {"tiefe_m": ..., "abdeckung": "streuscheibe" (bleibt stehen,
                aber ungenutzt: die Einheit baut ihre eigene Streuscheibe),
                "einheit": {
                    "typ": "band"|"winkel"|"bumerang"|"band_quer"|"ring",
                    "segmente": [["rueckstrahler", 0.1], ["blinker", 0.16],
                                 ["schlusslicht", 0.22], ["bremslicht", 0.36],
                                 ["rueckfahr", 0.16]]  (Anteile an der Länge,
                                 Reihenfolge entlang der langen Achse; ohne
                                 Angabe ein Standard je ``typ``),
                    "achse": 0|1 (Standard: die längere Ausdehnung des
                                 Umrisses der Zone),
                    "rand_m": 0.006 (Kammersteg zwischen den Segmenten),
                    "waben_m": 0.009 (Maschenweite des Reflektors hinter
                                 Brems-/Schlusslicht),
                    "linse_dicke_m": 0.005, "linse_woelbung_m": 0.008,
                    "ringe": nur "ring" — [{"f": 0.92, "breite_m": 0.012,
                                 "hoehe_m": 0.006, "mat": "licht_hinten"}, ...]
                                 (wie ``led.ringe``, aber als funktionaler
                                 Ring mit Gehäusetiefe statt dünner Leiste)
                }

``typ`` wählt nur die Standard-Segmentanteile und ob rund gebaut wird
(``ring``) oder als Band (alles andere) — ``winkel`` und ``bumerang`` laufen
über denselben Bandbau, nur mit anderen Anteilen; ``band_quer`` legt die
Segmente in der Mitte statt an einem Ende zusammen (durchgehendes
Lichtband, wie bei Elektroautos). Eine geteilte Einheit (Kotflügel und
Heckklappe getrennt) entsteht aus zwei benachbarten Leuchtenzonen mit je
einer eigenen ``einheit`` — dafür ist keine eigene Bauweise nötig.

Ein Segment ``bremslicht``/``schlusslicht`` bekommt eine Wabenstruktur als
Reflektor (``teile.gitter_zellen``, das eigentlich für Lufteinlassgitter
gedacht ist, aber geometrisch genau die geforderte Wabe baut); die übrigen
Segmente bekommen eine flache Farbfläche. Über allem liegt eine gewölbte,
durchsichtige Schale mit Dicke (``bmesh.ops.solidify``): rot (``streuscheibe``)
über allen Segmenten außer dem Rückfahrlicht, dort klar (``klarglas``).

LOD1 lässt ``einheit`` weg (``fahrzeug_bauen.lod1_parameter``); die Zone
fällt dann auf die alte, einfache Fassung zurück: eine flache Streuscheibe
über dem eingefärbten Gehäuseboden, ohne Kammern und Wabe.
"""
from __future__ import annotations

import math

import bmesh
from mathutils import Vector

import gemeinsam as g
import teile as tb


#: Standard-Segmentanteile je Typ (Name, Anteil an der Länge).
STANDARD_SEGMENTE = {
    "band": [("rueckstrahler", 0.12), ("blinker", 0.16), ("schlusslicht", 0.20),
             ("bremslicht", 0.36), ("rueckfahr", 0.16)],
    "winkel": [("blinker", 0.22), ("schlusslicht", 0.22), ("bremslicht", 0.40),
               ("rueckfahr", 0.16)],
    "bumerang": [("schlusslicht", 0.22), ("bremslicht", 0.46), ("blinker", 0.18),
                 ("rueckstrahler", 0.14)],
    "band_quer": [("blinker", 0.10), ("schlusslicht", 0.14), ("bremslicht", 0.52),
                  ("schlusslicht", 0.14), ("blinker", 0.10)],
}

#: Gehäusematerial je Funktion (siehe ``fahrzeug_bauen.materialien``).
SEGMENT_MAT = {
    "rueckstrahler": "rueckstrahler",
    "blinker": "blinker",
    "schlusslicht": "licht_hinten",
    "bremslicht": "bremslicht",
    "rueckfahr": "licht_vorn",         # helles, warmweißes Licht wie vorn.
}

#: Standard-Ringe für ``typ == "ring"`` (außen nach innen).
STANDARD_RINGE = [
    {"f": 0.95, "breite_m": 0.011, "hoehe_m": 0.006, "mat": "licht_hinten"},
    {"f": 0.68, "breite_m": 0.02, "hoehe_m": 0.011, "mat": "bremslicht"},
    {"f": 0.36, "breite_m": 0.013, "hoehe_m": 0.006, "mat": "rueckstrahler"},
]


def einheit_bauen(poly, einheit: dict, proj, ansicht: str, mats, tiefe: float, links: bool):
    """Eine Leuchteneinheit im Umriss ``poly`` (Ansichtsebene der Zone).

    ``proj(a, b)`` -> ``(Ort, Normale)`` auf dem bereits vertieften
    Gehäuseboden (wie bei ``_led_bauen``/``_projektoren_bauen``); ``tiefe``
    ist der Abstand des Bodens zur ursprünglichen Haut (``leuchten_tiefe``) —
    dort sitzt die Streuscheibe.
    """
    typ = einheit.get("typ", "band")
    if typ == "ring":
        return _ring_bauen(poly, einheit, proj, mats, tiefe)
    return _band_bauen(poly, einheit, proj, ansicht, mats, tiefe, typ, links)


def _achse_wahl(poly, einheit: dict) -> int:
    a0 = min(p[0] for p in poly)
    a1 = max(p[0] for p in poly)
    b0 = min(p[1] for p in poly)
    b1 = max(p[1] for p in poly)
    return einheit.get("achse", 0 if (a1 - a0) >= (b1 - b0) else 1)


def _stationen(poly, a0: float, a1: float, n: int):
    """``n + 1`` Stützstellen zwischen ``a0``/``a1`` mit lokaler Breite (Achse 0)."""
    out = []
    for i in range(n + 1):
        a = a0 + (a1 - a0) * i / n
        iv = tb.quer_schnitte(poly, 0, a)
        if not iv:
            continue
        b0, b1 = max(iv, key=lambda t: t[1] - t[0])
        out.append((a, b0, b1))
    return out


def _streifenflaeche(name, stationen, proj, versatz: float, mat, dicke=None, woelbung: float = 0.0):
    """Fläche entlang der Stützstellen, wahlweise mit Dicke (Streuscheibe)."""
    if len(stationen) < 2:
        return None
    bm = bmesh.new()
    n = len(stationen)
    rows = []
    for i, (a, b0, b1) in enumerate(stationen):
        h0, h1 = proj(a, b0), proj(a, b1)
        if h0 is None or h1 is None:
            rows.append(None)
            continue
        n0 = Vector(h0[1]).normalized()
        n1 = Vector(h1[1]).normalized()
        t = i / max(n - 1, 1)
        bulge = woelbung * math.sin(math.pi * t) if woelbung else 0.0
        rows.append((bm.verts.new(Vector(h0[0]) + n0 * (versatz + bulge)),
                     bm.verts.new(Vector(h1[0]) + n1 * (versatz + bulge))))
    faces = []
    for r0, r1 in zip(rows, rows[1:]):
        if r0 and r1:
            faces.append(bm.faces.new((r0[0], r0[1], r1[1], r1[0])))
    if not faces:
        bm.free()
        return None
    if dicke:
        bmesh.ops.solidify(bm, geom=faces, thickness=dicke)
    for f in bm.faces:
        f.smooth = True
    return g.objekt_aus(bm, name, [mat])


def _kammersteg(name, poly, a: float, proj, mat, hoehe: float = 0.007, breite: float = 0.005):
    """Dünne, erhöhte Trennwand zwischen zwei Segmenten (Gehäusekammer)."""
    iv = tb.quer_schnitte(poly, 0, a)
    if not iv:
        return None
    b0, b1 = max(iv, key=lambda t: t[1] - t[0])
    h0, h1 = proj(a, b0), proj(a, b1)
    if h0 is None or h1 is None:
        return None
    return tb.band(name, [h0[0], h1[0]], [h0[1], h1[1]], breite, hoehe, mat)


def _segmentgrenzen(poly, segmente, achse: int):
    umgetauscht = achse == 1
    if umgetauscht:
        poly = [(p[1], p[0]) for p in poly]
    a0 = min(p[0] for p in poly)
    a1 = max(p[0] for p in poly)
    # Die spitzen Enden meiden: an einer schmalen Ecke kippt der breiteste
    # Querschnitt (bei einem nicht konvexen Umriss) leicht in einen anderen
    # Lauf des Umrisses und reißt eine Ecke der Leuchte hoch.
    saum = (a1 - a0) * 0.03
    a0, a1 = a0 + saum, a1 - saum
    gesamt = sum(f for _n, f in segmente) or 1.0
    grenzen = [a0]
    lauf = a0
    for _n, f in segmente:
        lauf += (a1 - a0) * f / gesamt
        grenzen.append(lauf)
    return poly, grenzen, umgetauscht


def _band_bauen(poly, einheit, proj, ansicht, mats, tiefe, typ, links):
    segmente = einheit.get("segmente") or STANDARD_SEGMENTE.get(typ, STANDARD_SEGMENTE["band"])
    achse = _achse_wahl(poly, einheit)
    poly2, grenzen, getauscht = _segmentgrenzen(poly, segmente, achse)
    if getauscht:
        def proj2(a, b, _p=proj):
            return _p(b, a)
    else:
        proj2 = proj
    a0, a1 = grenzen[0], grenzen[-1]
    laenge = max(a1 - a0, 1e-6)
    rand_m = einheit.get("rand_m", 0.005)
    waben_m = einheit.get("waben_m", 0.018)
    dicke = einheit.get("linse_dicke_m", 0.005)
    woelbung = einheit.get("linse_woelbung_m", 0.008)
    n_stationen = max(3, int(laenge / 0.03))
    blick = tb.blickrichtung(ansicht, links)
    teile = []
    # Boden: Reflektor/Wabe oder Farbfläche je Segment, mit Kammersteg dazwischen.
    for i, (name_seg, _f) in enumerate(segmente):
        sa0 = grenzen[i] + (rand_m / 2 if i > 0 else 0.0)
        sa1 = grenzen[i + 1] - (rand_m / 2 if i < len(segmente) - 1 else 0.0)
        if sa1 <= sa0:
            continue
        n = max(2, round(n_stationen * (sa1 - sa0) / laenge))
        stationen = _stationen(poly2, sa0, sa1, n)
        if len(stationen) < 2:
            continue
        mat_name = SEGMENT_MAT.get(name_seg, "kunststoff")
        if name_seg == "bremslicht":
            # Nur das Bremslicht bekommt die teure Wabe als Reflektor — das
            # Dreiecksbudget je Fahrzeug ist knapp (Vertrag: 120k).
            umriss = ([(a, b0) for a, b0, _b1 in stationen] +
                      [(a, b1) for a, _b0, b1 in reversed(stationen)])
            ob = tb.gitter_zellen(f"leuchte_{name_seg}", umriss, "waben", waben_m,
                                  max(0.001, waben_m * 0.16), 0.005, proj2, blick, mats[mat_name])
        else:
            ob = _streifenflaeche(f"leuchte_{name_seg}", stationen, proj2, 0.0, mats[mat_name])
        if ob is not None:
            teile.append(ob)
    for g_ in grenzen[1:-1]:
        steg = _kammersteg("leuchte_steg", poly2, g_, proj2, mats["zierteil"])
        if steg is not None:
            teile.append(steg)
    # Streuscheibe: klar über dem Rückfahrlicht, sonst rot, durchgehend gewölbt.
    for i, (name_seg, _f) in enumerate(segmente):
        sa0, sa1 = grenzen[i], grenzen[i + 1]
        n = max(2, round(n_stationen * (sa1 - sa0) / laenge))
        stationen = _stationen(poly2, sa0, sa1, n)
        lensmat = "klarglas" if name_seg == "rueckfahr" else "streuscheibe"
        ob = _streifenflaeche(f"leuchte_glas_{i}", stationen, proj2, tiefe, mats[lensmat],
                              dicke=dicke, woelbung=woelbung)
        if ob is not None:
            teile.append(ob)
    return teile


def _ring_bauen(poly, einheit, proj, mats, tiefe):
    ringe = einheit.get("ringe") or STANDARD_RINGE
    teile = []
    for r in ringe:
        umriss = tb.polygon_skalieren(poly, r.get("f", 0.8))
        pp, nn = [], []
        ok = True
        for a, b in umriss:
            h = proj(a, b)
            if h is None:
                ok = False
                break
            pp.append(h[0])
            nn.append(h[1])
        if ok and len(pp) >= 3:
            ob = tb.band("leuchtring", pp, nn, r.get("breite_m", 0.015), r.get("hoehe_m", 0.007),
                        mats[r.get("mat", "licht_hinten")], geschlossen=True)
            if ob is not None:
                teile.append(ob)
    dicke = einheit.get("linse_dicke_m", 0.005)
    woelbung = einheit.get("linse_woelbung_m", 0.01)
    a0 = min(p[0] for p in poly)
    a1 = max(p[0] for p in poly)
    stationen = _stationen(poly, a0, a1, max(6, int((a1 - a0) / 0.02)))
    lens = _streifenflaeche("leuchte_glas_ring", stationen, proj, tiefe, mats["streuscheibe"],
                            dicke=dicke, woelbung=woelbung)
    if lens is not None:
        teile.append(lens)
    return teile
