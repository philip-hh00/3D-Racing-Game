"""Leuchteneinheiten für ``fahrzeug_bauen.py``: Rückleuchten und Scheinwerfer.

Läuft **in Blender**. Eine Leuchte ist ein eigenständiges Bauteil in einer
Öffnung der Karosserie (die Zone mit ``leuchte`` vertieft die Haut um
``tiefe_m``), aufgebaut wie eine echte, moderne Leuchte:

* **Deckglas** bündig auf der alten Haut, mit sichtbarer Glaskante nach
  innen; rot getönt, klar über dem Rückfahrlicht (``deckglas_bauen``).
* **Lichtleiter**: runde Stäbe, die über dem Reflektor schweben, mit hellem
  Kern (Leuchtbild quer zum Stab) und Streulicht auf dem Boden darunter —
  die Lichtsignatur, die man aus der Verfolgerkamera erkennt.
* **Kammern** mit dunklen Stegen: Rückstrahler, Blinker, Schlusslicht,
  Bremslicht, Rückfahrlicht nebeneinander.
* **Optiken**, als Hochpoly gebaut und in Normal-, Leucht- und
  Verdeckungskarten gebacken (``backen.py``): Kissenoptik (Waben) hinter dem
  Schlusslicht, LED-Punktmatrix mit Linsen und Reflektorkegeln im Bremslicht,
  Facettenreflektor aus Chrom hinter Blinker und Rückfahrlicht,
  Tripelprismen im Rückstrahler, feine Rillen im Scheinwerfergehäuse.
* **Scheinwerfer**: Projektormodule (Chromschale mit Facetten, dunkle
  Glaslinse, Chromring, Tagfahrlicht-Ring) und Tagfahrlicht-Lichtleiter.

Eingeschaltet wird sie je Leuchtenzone mit ``"einheit"`` unter ``"leuchte"``
in ``tools/blender/fahrzeuge/<key>.json``::

    "einheit": {
      "typ": "band"|"winkel"|"bumerang"|"band_quer"|"ring"|"scheinwerfer",
      "segmente": [["rueckstrahler", 0.1], ["blinker", 0.16], ["schlusslicht", 0.22],
                   ["bremslicht", 0.36], ["rueckfahr", 0.16]]
                   (Anteile entlang der langen Achse; Standard je ``typ``),
      "achse": 0|1 (Standard: die längere Ausdehnung des Umrisses),
      "rand_m": 0.005 (Kammersteg), "steg_hoehe": 0.7 (Anteil der Tiefe),
      "waben_m": 0.006 (Kissenoptik), "led_m": 0.0075 (Punktmatrix),
      "stil": "klassisch" (die bisherige Einheit, ``teile_leuchte_klassisch``),
      "glas": "rot"|"rauch"|"klar" (Deckglas), "klar": ["rueckfahr"] (Kammern
              unter klarem Glas),
      "ansicht": "hinten" (die Teilfläche der Zone, in der die Einheit sitzt;
                 Standard: die größte) | "alle" (je Teilfläche eine Einheit; die
                 Reihenfolge in ``je_ansicht`` ist der Vorrang an der Kante),
      "je_ansicht": {"hinten": {...}, "oben": {...}} (Werte je Teilfläche),
      "lichtleiter": [{"verlauf": "rand"|"oben"|"unten"|"vorn"|"hinten"|"aussen"|"innen"
                       | "quer": [0.5] (waagerechte Stäbe, Anteil der Höhe)
                       | "senkrecht": [0.9] (Anteil der Breite, von der Mitte
                         nach außen) | "ringe": [0.85],
                       "abstand_m": 0.01 (vom Umriss nach innen),
                       "bereich": [0.0, 1.0] (Anteil entlang der langen Achse),
                       "durchmesser_m": 0.006, "hoehe_m": 0.008 (Mitte über dem Boden),
                       "mat": "licht_hinten"|"bremslicht"|"blinker"|"licht_vorn"}],
      "ringe": nur "ring" — {"innen": 0.55} (Bremslicht-Mitte),
      "projektoren": nur "scheinwerfer" — {"anzahl": 2, "radius_m": 0.022,
                      "lage": 0.5, "rand_anteil": 0.22, "vorhalt": 0.6,
                      "ring": true (Tagfahrlicht-Ring um die Schale)}
    }

**Texturen.** Alle Leuchten eines Autos teilen sich einen Atlas (Normal,
Leuchtbild, Verdeckung; ``ATLAS_PX``). Links und rechts liegen auf denselben
Texeln (gespiegelt), gebacken wird nur die linke Seite. Unten im Atlas liegt
ein neutraler Streifen: Farbfelder je Leuchtmaterial (dort landen alle
Flächen mit diesen Materialien außerhalb der Einheiten — Spiegelblinker,
LED-Leisten) und die Querverläufe der Lichtleiter. Die Leuchtmaterialien
behalten ihre Namen (``bremslicht`` wird im Spiel mit dem Pedal
hochgeregelt); ihre Farbe steht danach im Leuchtbild, das Material trägt nur
die Stärke.

``fahrzeug_bauen`` ruft ``einheit_bauen`` je Seite, ``deckglas_bauen`` je
Zone und am Ende ``atlas_anwenden`` mit allen Teilen der Karosserie. **LOD1**
baut dieselben Einheiten ohne Hochpoly, Stege und Facettenschalen und nimmt
den Atlas der vollen Stufe verkleinert auf ``LOD_PX``.
"""
from __future__ import annotations

import hashlib
import math
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import backen
import gemeinsam as g
import teile as tb
import teile_leuchte_klassisch as tlk

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

#: Boden (Reflektor) je Kammer.
SEGMENT_MAT = {
    "rueckstrahler": "katzenauge",
    "blinker": "leuchte_chrom",
    "schlusslicht": "leuchte_innen",     # schwarzer Einsatz, die Waben leuchten rot
    "bremslicht": "bremslicht",
    "rueckfahr": "leuchte_chrom",
}

#: Leuchtmaterialien, deren Farbe ins Leuchtbild wandert.
LEUCHTEND = ("licht_hinten", "bremslicht", "blinker", "licht_vorn")

#: Materialien mit gebackenen Karten (Normal + Verdeckung; Leuchtbild für
#: ``LEUCHTEND`` und ``leuchte_innen``).
TEXTURIERT = LEUCHTEND + ("leuchte_chrom", "leuchte_innen", "katzenauge")

ATLAS_PX = 2048          # Normal und Leuchtbild der vollen Stufe
AO_PX = 1024             # Verdeckung (weich, braucht weniger)
LOD_PX = 512             # alle Karten der LOD1-Stufe
BAND_PX = 96             # neutraler Streifen unten (bei ATLAS_PX)
LUECKE_PX = 24           # Abstand der Inseln (Mipstufen)
DICHTE_MAX = 4000.0      # px/m: 0,25 mm je Texel reichen für LED-Linsen

#: Neutrale Farbfelder im Streifen: (Name, x in px bei ATLAS_PX).
FELDER = [("schwarz", 16), ("licht_hinten", 96), ("bremslicht", 176), ("blinker", 256),
          ("licht_vorn", 336)]
FELD_PX = 64
#: Querverläufe der Lichtleiter je Material: x in px, Breite 208.
STREIFEN = {"licht_hinten": 432, "bremslicht": 656, "blinker": 880, "licht_vorn": 1104}
STREIFEN_PX = (208, 64)

#: Höhe der Optiken über dem Boden: so weit ragen Strahlen beim Backen.
PLATTE_M = 0.0015
KAEFIG_M = 0.003

#: Leuchtstärke der Materialien mit Leuchtbild. Die Karte trägt Farbe und
#: Helligkeit (1 = volle Stärke); gleiche Stärke für alle Böden, damit das
#: Streulicht der Lichtleiter überall gleich hell ist. ``bremslicht`` wird im
#: Spiel noch mit dem Pedal multipliziert (0,25 … 3). Blinker bleiben aus.
STAERKE = {"licht_hinten": 6.0, "bremslicht": 6.0, "licht_vorn": 6.0, "leuchte_innen": 6.0}

#: Wie hell die Optiken im Leuchtbild sind (Anteil von ``STAERKE``).
PEGEL = {
    "waben_grund": 0.0, "waben_seite": 0.03, "waben_kern": 0.11,
    "led_grund": 0.1, "led_kegel": 0.25, "led_linse": 0.6,
    "leiter_kern": 1.0, "leiter_flanke": 0.45, "leiter_unten": 0.12,
    "halo": 0.16,
}

#: Wie weit der heiße Kern einer LED zu Weiß hin ausbrennt. Reines Rot kann
#: nach der Tonabbildung nicht heller wirken als roter Lack in der Sonne;
#: erst der entsättigte Kern (wie auf jedem Foto einer echten LED) leuchtet.
WEISSKERN = 0.35


def _kern(farbe, anteil):
    return tuple(c * (1 - anteil) + anteil for c in farbe)


#: Die Einheiten des Fahrzeugs, das gerade entsteht (je Stufe neu).
_BAU: list = []
#: Atlas der vollen Stufe je Fahrzeug — LOD1 nimmt dieselben Inseln.
_ATLAS: dict = {}


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def eigene_materialien(mats) -> None:
    """Die Materialien der Einheiten ergänzen (Namen stehen im Vertrag frei)."""
    neu = {
        # Facettenreflektor: Chrom, leicht matt, damit die Facetten zeichnen.
        "leuchte_chrom": g.material("leuchte_chrom", (0.86, 0.87, 0.9), 1.0, 0.14),
        # Dunkler Einsatz des Gehäuses: Hochglanzschwarz; leuchtet nur dort,
        # wo das Leuchtbild Streulicht der Lichtleiter trägt.
        "leuchte_innen": g.material("leuchte_innen", (0.018, 0.018, 0.02), 0.3, 0.22,
                                    emission=(0.0, 0.0, 0.0), staerke=1.0),
        # Rückstrahler: rotes Tripelprisma, spiegelt stark.
        "katzenauge": g.material("katzenauge", (0.62, 0.035, 0.03), 0.75, 0.16),
        # Projektorlinse: dunkles, dickes Glas — spiegelt, statt durchzuscheinen.
        "projektorlinse": g.material("projektorlinse", (0.03, 0.035, 0.045), 0.0, 0.02,
                                     klarlack=1.0),
        # Deckgläser: dünn getönt, glatt. Das Spiel mischt Glas nach Alpha.
        "deckglas_rot": g.material("deckglas_rot", (0.55, 0.012, 0.02), 0.0, 0.02, alpha=0.36),
        "deckglas_rauch": g.material("deckglas_rauch", (0.14, 0.01, 0.016), 0.0, 0.02, alpha=0.62),
        "deckglas_klar": g.material("deckglas_klar", (0.82, 0.85, 0.9), 0.0, 0.01, alpha=0.14),
    }
    for k, m in neu.items():
        mats.setdefault(k, m)


def _emissionsfarbe(mat) -> tuple:
    """Leuchtfarbe eines Materials, linear (so steht sie im Knoten)."""
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    return tuple(bsdf.inputs["Emission Color"].default_value[:3])


_QUELLMATS: dict = {}


def _quellmat(farbe_lin, pegel: float):
    """Material der Hochpoly-Quellen: nur die Emission zählt beim Backen."""
    k = (tuple(round(c, 4) for c in farbe_lin), round(pegel, 4))
    m = _QUELLMATS.get(k)
    try:
        if m is not None and m.name in bpy.data.materials:
            return m
    except ReferenceError:            # Szene geleert (nächstes Fahrzeug)
        pass
    m = bpy.data.materials.new(f"_quelle_{len(_QUELLMATS)}")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bsdf.inputs["Emission Color"].default_value = (*farbe_lin, 1.0)
    bsdf.inputs["Emission Strength"].default_value = pegel
    _QUELLMATS[k] = m
    return m


# ---------------------------------------------------------------------------
# Eine Einheit: Ebene, Seite, Teile
# ---------------------------------------------------------------------------

class Einheit:
    """Eine gebaute Leuchte (eine Seite) und was der Atlas über sie wissen muss."""

    def __init__(self, schluessel, ansicht, spiegel, kanonisch, lod, zone):
        self.schluessel = schluessel
        self.ansicht = ansicht
        self.spiegel = spiegel          # rechte Seite: UV aus der gespiegelten linken
        self.kanonisch = kanonisch      # diese Seite wird gebacken
        self.lod = lod
        self.zone = zone                # id() des einheit-Blocks (beide Seiten gleich)
        self.basis = None               # (O, t1, t2, n) in kanonischen Koordinaten
        self.empfaenger = []            # Böden: planare UV im Atlas
        self.leiter = []                # (Objekt, Material): UV im Querverlauf
        self.quellen = []               # Hochpoly (nur kanonisch, nicht LOD)
        self.halo = []                  # ([(s, t), ...], Material)
        self.kammern = []               # (Name, a0, a1) in Achsenkoordinaten
        self.getauscht = False
        self.poly = None
        self.glas = "rot"
        self.klar = ("rueckfahr",)

    def kanon(self, p) -> Vector:
        p = Vector(p)
        return Vector((p.x, -p.y, p.z)) if self.spiegel else p

    def ebene(self, p):
        """Weltpunkt -> (s, t) in Metern in der Ebene der Einheit."""
        o, t1, t2, _n = self.basis
        q = self.kanon(p) - o
        return q.dot(t1), q.dot(t2)

    def welt(self, s, t) -> Vector:
        o, t1, t2, _n = self.basis
        return self.kanon(o + t1 * s + t2 * t)


def _schluessel(ansicht, poly_kanon) -> str:
    roh = ansicht + ";" + ";".join(f"{a:.3f},{b:.3f}" for a, b in poly_kanon)
    return ansicht + "_" + hashlib.md5(roh.encode()).hexdigest()[:10]


def _seite(poly, ansicht, links):
    """(spiegel, über die Mitte) — die rechte Seite (y < 0) ist das Spiegelbild."""
    if ansicht == "seite":
        return (not links), False
    k = 0 if ansicht in ("hinten", "vorn") else 1
    ys = [p[k] for p in poly]
    if min(ys) < -0.01 and max(ys) > 0.01:
        return False, True
    return sum(ys) / len(ys) < 0, False


def _poly_kanon(poly, ansicht, spiegel):
    if not spiegel or ansicht == "seite":
        return [tuple(p) for p in poly]
    if ansicht == "oben":
        return [(a, -b) for a, b in poly]
    return [(-a, b) for a, b in poly]


def _basis(poly, proj, einh: Einheit):
    """Projektionsebene: mittlere Bodennormale, Achsen nach der Ansicht."""
    ia, ib, _ic = tb.ACHSEN[einh.ansicht]
    c = tb.schwerpunkt2(poly)
    proben = [c] + [(c[0] + (p[0] - c[0]) * f, c[1] + (p[1] - c[1]) * f)
                    for p in poly for f in (0.4, 0.75)]
    n = Vector()
    orte = []
    for a, b in proben:
        h = proj(a, b)
        if h is not None:
            n += Vector(h[1]).normalized()
            orte.append(Vector(h[0]))
    if not orte:
        return None
    n = einh.kanon(n.normalized())
    o = einh.kanon(sum(orte, Vector()) / len(orte))
    e1 = Vector((0, 0, 0))
    e1[ia] = 1.0
    e2 = Vector((0, 0, 0))
    e2[ib] = 1.0
    t1 = (e1 - n * e1.dot(n))
    if t1.length < 1e-3:
        t1 = e2.cross(n)
    t1.normalize()
    t2 = n.cross(t1)
    # Hauptachse des Umrisses in der Ebene: schräge, schmale Leuchten
    # bekommen so eine schmale Insel statt eines halb leeren Rechtecks.
    rand = []
    for a, b in poly:
        h = proj(a, b)
        if h is not None:
            q = einh.kanon(Vector(h[0])) - o
            rand.append((q.dot(t1), q.dot(t2)))
    if len(rand) >= 3:
        pts = np.array(_gleichmaessig(rand, 64))
        pts -= pts.mean(axis=0)
        w, v = np.linalg.eigh(pts.T @ pts)
        ax = v[:, int(np.argmax(w))]
        haupt = (t1 * float(ax[0]) + t2 * float(ax[1])).normalized()
        if abs(haupt.dot(e1)) >= abs(haupt.dot(e2)):
            haupt = haupt if haupt.dot(e1) >= 0 else -haupt
        else:
            haupt = haupt if haupt.dot(e2) >= 0 else -haupt
        t1 = haupt
        t2 = n.cross(t1)
    return (o, t1, t2, n)


#: Materialplätze von ``lack``/``lack2`` in der Karosserie (fahrzeug_bauen.KAROSSERIE_MATS).
LACK_INDEX = (0, 1)


def _durch_waende(treffer, ansicht, boden, links, tiefe):
    """Strahl entlang der Blickachse, der Gehäusewände durchquert: an schräg
    zum Betrachter liegenden Leuchten verdeckt sonst die obere Wand den Boden,
    und die Einheit bekäme dort keine Platte."""
    ia, ib, ic = tb.ACHSEN[ansicht]
    rueck = ansicht == "hinten" or (ansicht == "seite" and not links)

    def proj(a, b):
        start = [0.0, 0.0, 0.0]
        richtung = [0.0, 0.0, 0.0]
        start[ia], start[ib] = a, b
        start[ic], richtung[ic] = (-10.0, 1.0) if rueck else (10.0, -1.0)
        start, richtung = Vector(start), Vector(richtung)
        erster = None
        for _ in range(6):
            t = treffer.strahl(start, richtung)
            if t is None:
                return None
            ort, normale, mat = t
            if erster is None:
                if mat in LACK_INDEX:        # außerhalb der Öffnung
                    return None
                erster = ort
            elif (ort - erster).length > tiefe + 0.03:
                return None
            if mat in boden:
                return ort, normale
            start = ort + richtung * 1e-4
        return None
    return proj


def einheit_bauen(poly, einheit: dict, proj, ansicht: str, mats, tiefe: float, links: bool,
                  treffer=None, boden=None, teilpolys=None):
    """Eine Leuchteneinheit im Umriss ``poly`` (Ansichtsebene der Zone).

    ``proj(a, b)`` -> ``(Ort, Normale)`` auf dem vertieften Gehäuseboden;
    ``tiefe`` ist der Abstand des Bodens zur alten Haut (dort liegt das
    Deckglas). Liefert die Spielteile; Hochpoly-Quellen bleiben bis
    ``atlas_anwenden`` in der Szene.
    """
    if einheit.get("stil") == "klassisch":
        # Die bisherige Einheit: kein Atlas, keine Texturen (teile_leuchte_klassisch).
        if einheit.get("_lod"):
            return []
        return tlk.einheit_bauen(poly, einheit, proj, ansicht, mats, tiefe, links)
    eigene_materialien(mats)
    zone = id(einheit)
    if treffer is not None and boden is not None:
        proj = _durch_waende(treffer, ansicht, boden, links, tiefe)
    if einheit.get("ansicht") == "alle" and teilpolys and len(einheit.get("je_ansicht") or {}) > 1:
        # Mehrere Einheiten in einer Zone: die Reihenfolge in ``je_ansicht`` ist
        # der Vorrang. Eine Einheit lässt die Bodenpunkte aus, die im Umriss
        # einer vorrangigen Teilfläche liegen — sonst überlappen sie an der
        # Kante (der Blick von oben trifft auch das steile Heck).
        vor = []
        for a_ in einheit["je_ansicht"]:
            if a_ == ansicht:
                break
            vor.append((tb.ACHSEN[a_], teilpolys.get(a_, [])))

        def proj(a, b, _p=proj):
            h = _p(a, b)
            if h is None:
                return None
            q = h[0]
            for (ja, jb, _jc), polys in vor:
                if any(tb.im_polygon((q[ja], q[jb]), pl) for pl in polys):
                    return None
            return h
    # Je Teilfläche eigene Werte (``"ansicht": "alle"`` baut in jeder eine Einheit).
    einheit = {**einheit, **(einheit.get("je_ansicht") or {}).get(ansicht, {})}
    typ = einheit.get("typ", "band")
    spiegel, _mitte = _seite(poly, ansicht, links)
    pk = _poly_kanon(poly, ansicht, spiegel)
    lod = bool(einheit.get("_lod"))
    einh = Einheit(_schluessel(ansicht, pk), ansicht, spiegel, not spiegel, lod, zone)
    einh.poly = poly
    einh.glas = einheit.get("glas", "klar" if typ == "scheinwerfer" else "rot")
    einh.klar = tuple(einheit.get("klar", ["rueckfahr"]))
    alt = _ATLAS.get("_aktuell", {}).get("basen", {}).get(einh.schluessel) if lod else None
    einh.basis = alt or _basis(poly, proj, einh)
    if einh.basis is None:
        return []
    _BAU.append(einh)
    if typ == "ring":
        teile = _ring_bauen(poly, einheit, proj, mats, tiefe, einh)
    elif typ == "scheinwerfer":
        teile = _scheinwerfer_bauen(poly, einheit, proj, mats, tiefe, einh)
    else:
        teile = _band_bauen(poly, einheit, proj, mats, tiefe, typ, einh)
    teile += _leiter_alle(poly, einheit, proj, mats, einh, tiefe, typ)
    return [t for t in teile if t is not None]


# ---------------------------------------------------------------------------
# Umriss-Helfer
# ---------------------------------------------------------------------------

def _achse_wahl(poly, einheit: dict) -> int:
    a0, a1 = min(p[0] for p in poly), max(p[0] for p in poly)
    b0, b1 = min(p[1] for p in poly), max(p[1] for p in poly)
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


def _platte(name, stationen, proj2, mat, versatz: float = PLATTE_M, quer_m: float = 0.008):
    """Boden einer Kammer: Gitter über die Stützstellen, dem Boden folgend."""
    if len(stationen) < 2:
        return None
    breite = max(b1 - b0 for _a, b0, b1 in stationen)
    k = max(2, int(math.ceil(breite / quer_m)))
    bm = bmesh.new()
    boden_n = Vector()
    reihen = []
    for a, b0, b1 in stationen:
        reihe = []
        gueltig = _gueltiger_bereich(proj2, a, b0, b1, k)
        if gueltig is None:
            reihen.append([None] * (k + 1))
            continue
        b0, b1 = gueltig
        for j in range(k + 1):
            b = b0 + (b1 - b0) * j / k
            h = proj2(a, b)
            if h is None:
                reihe.append(None)
                continue
            boden_n += Vector(h[1]).normalized()
            reihe.append(bm.verts.new(Vector(h[0]) + Vector(h[1]).normalized() * versatz))
        reihen.append(reihe)
    for r0, r1 in zip(reihen, reihen[1:]):
        for j in range(k):
            q = (r0[j], r0[j + 1], r1[j + 1], r1[j])
            if all(v is not None for v in q):
                bm.faces.new(q)
    return _platte_fertig(bm, name, mat, boden_n)


def _gueltiger_bereich(proj2, a, b0, b1, k):
    """Der längste Abschnitt ``[b0, b1]``, in dem der Boden getroffen wird, mit
    genau bestimmten Enden — so endet eine Platte an einer Flächengrenze glatt
    statt in Treppenstufen."""
    n = max(8, 2 * k)
    ok = [proj2(a, b0 + (b1 - b0) * j / n) is not None for j in range(n + 1)]
    if all(ok):
        return b0, b1
    best, lauf = None, None
    for j, treffer in enumerate(ok + [False]):
        if treffer and lauf is None:
            lauf = j
        elif not treffer and lauf is not None:
            if best is None or j - lauf > best[1] - best[0]:
                best = (lauf, j - 1)
            lauf = None
    if best is None or best[1] - best[0] < 1:
        return None

    def rand(gut, schlecht):
        for _ in range(10):
            m = (gut + schlecht) / 2
            if proj2(a, m) is not None:
                gut = m
            else:
                schlecht = m
        return gut
    s = (b1 - b0) / n
    lo = b0 + best[0] * s
    hi = b0 + best[1] * s
    if best[0] > 0:
        lo = rand(lo, lo - s)
    if best[1] < n:
        hi = rand(hi, hi + s)
    return lo, hi


def _platte_fertig(bm, name, mat, boden_n):
    """Normalen vom Boden weg (Käfig und Tangentenraum beim Backen), glatt."""
    if not bm.faces:
        bm.free()
        return None
    bm.normal_update()
    umdrehen = sum(f.normal.dot(boden_n) for f in bm.faces) < 0
    if umdrehen:
        for f in bm.faces:
            f.normal_flip()
    for f in bm.faces:
        f.smooth = True
    return g.objekt_aus(bm, name, [mat])


def _ringplatte(name, poly, f_innen, f_aussen, proj, mat, versatz=PLATTE_M, n_um=72, n_rad=4):
    """Ringfläche zwischen zwei skalierten Umrissen (``f_innen = 0``: Scheibe)."""
    c = tb.schwerpunkt2(poly)
    rund = _gleichmaessig(poly, n_um)
    bm = bmesh.new()
    boden_n = Vector()
    ringe = []
    for i in range(n_rad + 1):
        f = f_aussen + (f_innen - f_aussen) * i / n_rad
        if f < 1e-4:
            break
        ring = []
        for a, b in rund:
            h = proj(c[0] + (a - c[0]) * f, c[1] + (b - c[1]) * f)
            if h is not None:
                boden_n += Vector(h[1]).normalized()
            ring.append(None if h is None else
                        bm.verts.new(Vector(h[0]) + Vector(h[1]).normalized() * versatz))
        ringe.append(ring)
    for r0, r1 in zip(ringe, ringe[1:]):
        for j in range(n_um):
            q = (r0[j], r0[(j + 1) % n_um], r1[(j + 1) % n_um], r1[j])
            if all(v is not None for v in q):
                bm.faces.new(q)
    if f_innen < 1e-4:
        h = proj(*c)
        if h is not None:
            m = bm.verts.new(Vector(h[0]) + Vector(h[1]).normalized() * versatz)
            r = ringe[-1]
            for j in range(n_um):
                if r[j] is not None and r[(j + 1) % n_um] is not None:
                    bm.faces.new((r[j], r[(j + 1) % n_um], m))
    return _platte_fertig(bm, name, mat, boden_n)


def _gleichmaessig(poly, n):
    """Geschlossenen Umriss mit ``n`` gleich weit entfernten Punkten neu abtasten."""
    pts = list(poly) + [poly[0]]
    lg = [0.0]
    for p, q in zip(pts, pts[1:]):
        lg.append(lg[-1] + math.hypot(q[0] - p[0], q[1] - p[1]))
    gesamt = lg[-1] or 1e-9
    out = []
    j = 0
    for i in range(n):
        s = gesamt * i / n
        while lg[j + 1] < s:
            j += 1
        t = (s - lg[j]) / max(lg[j + 1] - lg[j], 1e-12)
        out.append((pts[j][0] + (pts[j + 1][0] - pts[j][0]) * t,
                    pts[j][1] + (pts[j + 1][1] - pts[j][1]) * t))
    return out


def _kammersteg(name, poly, a: float, proj2, mat, hoehe: float, breite: float = 0.003):
    """Trennwand zwischen zwei Kammern, vom Boden bis kurz unter das Glas."""
    iv = tb.quer_schnitte(poly, 0, a)
    if not iv:
        return None
    b0, b1 = max(iv, key=lambda t: t[1] - t[0])
    pts, nrm = [], []
    k = max(2, int(math.ceil((b1 - b0) / 0.008)))
    for j in range(k + 1):
        h = proj2(a, b0 + (b1 - b0) * j / k)
        if h is not None:
            pts.append(h[0])
            nrm.append(h[1])
    if len(pts) < 2:
        return None
    return tb.band(name, pts, nrm, breite, hoehe, mat)


# ---------------------------------------------------------------------------
# Hochpoly-Optiken
# ---------------------------------------------------------------------------

def _ecken(einh: Einheit, platte):
    """Die Ausdehnung einer Bodenplatte in der Ebene der Einheit."""
    mw = platte.matrix_world
    return [einh.ebene(mw @ v.co) for v in platte.data.vertices]


def _raster(einh: Einheit, platte, drin, proj, schritt_s, schritt_t, versatz_zeile=0.0):
    """Rasterpunkte in der Ebene der Einheit, die ``drin(a, b)`` erfüllen.

    Liefert ``(Ort, x, y, n)`` je Punkt: Ort auf der Bodenplatte, Achsen der
    Ebene in die Tangentialebene gedreht.
    """
    ia, ib, _ic = tb.ACHSEN[einh.ansicht]
    ecken = _ecken(einh, platte)
    if not ecken:
        return []
    s0, s1 = min(e[0] for e in ecken) - schritt_s, max(e[0] for e in ecken) + schritt_s
    t0, t1 = min(e[1] for e in ecken) - schritt_t, max(e[1] for e in ecken) + schritt_t
    _o, e_s, _e_t, _n = einh.basis
    e_s = einh.kanon(e_s)
    out = []
    j = 0
    t = t0
    while t <= t1:
        s = s0 + (schritt_s * versatz_zeile if j % 2 else 0.0)
        while s <= s1:
            p = einh.welt(s, t)
            a, b = p[ia], p[ib]
            if drin(a, b):
                h = proj(a, b)
                if h is not None:
                    n = Vector(h[1]).normalized()
                    x = (e_s - n * e_s.dot(n)).normalized()
                    y = n.cross(x)
                    out.append((Vector(h[0]) + n * PLATTE_M, x, y, n))
            s += schritt_s
        t += schritt_t
        j += 1
    return out


def _stempeln(name, orte, vorlage, mats_je_index):
    """Eine Vorlage ``(punkte, flaechen, matindex)`` an jedem Ort einsetzen."""
    punkte, flaechen, mi = vorlage
    bm = bmesh.new()
    for k, (ort, x, y, n) in enumerate(orte):
        vs = [bm.verts.new(ort + x * p[0] + y * p[1] + n * p[2]) for p in punkte]
        for f, m in zip(flaechen, mi):
            try:
                fl = bm.faces.new([vs[i] for i in f])
            except ValueError:
                continue
            fl.material_index = m
    if not bm.faces:
        bm.free()
        return None
    ob = g.objekt_aus(bm, name, mats_je_index)
    for p in ob.data.polygons:
        p.use_smooth = False
    return ob


def _vorlage_wabe(r: float, h: float):
    """Kissenoptik: sechseckige Zelle mit flacher Kuppe (0 Seite, 1 Kern)."""
    punkte, flaechen, mi = [], [], []
    for k in range(6):
        w = math.pi / 6 + k * math.pi / 3
        punkte.append((math.cos(w) * r * 0.97, math.sin(w) * r * 0.97, 0.0))
    for k in range(6):
        w = math.pi / 6 + k * math.pi / 3
        punkte.append((math.cos(w) * r * 0.6, math.sin(w) * r * 0.6, h))
    punkte.append((0.0, 0.0, h * 1.25))
    for k in range(6):
        k2 = (k + 1) % 6
        flaechen.append((k, k2, 6 + k2, 6 + k))
        mi.append(0)
        flaechen.append((6 + k, 6 + k2, 12))
        mi.append(1)
    return punkte, flaechen, mi


def _vorlage_led(abstand: float):
    """LED mit Reflektorkegel und Linse (0 Rand, 1 Kegel, 2 Linse)."""
    r_rand, r_kegel, r_linse = abstand * 0.47, abstand * 0.27, abstand * 0.24
    n = 12
    punkte, flaechen, mi = [], [], []
    ringe = [(r_rand, 0.0006), (r_kegel, 0.0001), (r_linse, 0.00012),
             (r_linse * 0.8, 0.0007), (r_linse * 0.45, 0.00105)]
    for r, z in ringe:
        for k in range(n):
            w = 2 * math.pi * k / n
            punkte.append((math.cos(w) * r, math.sin(w) * r, z))
    punkte.append((0.0, 0.0, 0.0012))
    # äußerer Kragen vom Boden auf den Rand
    for k in range(n):
        w = 2 * math.pi * k / n
        punkte.append((math.cos(w) * abstand * 0.5, math.sin(w) * abstand * 0.5, 0.0))
    kragen = len(ringe) * n + 1
    for k in range(n):
        k2 = (k + 1) % n
        flaechen.append((kragen + k, kragen + k2, k2, k))
        mi.append(0)
    for i, m in ((0, 1), (1, 1), (2, 2), (3, 2)):
        for k in range(n):
            k2 = (k + 1) % n
            flaechen.append((i * n + k, i * n + k2, (i + 1) * n + k2, (i + 1) * n + k))
            mi.append(m)
    spitze = len(ringe) * n
    for k in range(n):
        flaechen.append((4 * n + k, 4 * n + (k + 1) % n, spitze))
        mi.append(2)
    return punkte, flaechen, mi


def _vorlage_facette(w: float, h: float, versatz):
    """Facette: flache Pyramide mit verschobener Spitze (Chromreflektor)."""
    d = w / 2
    punkte = [(-d, -d, 0.0), (d, -d, 0.0), (d, d, 0.0), (-d, d, 0.0),
              (versatz[0] * d, versatz[1] * d, h)]
    flaechen = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)]
    return punkte, flaechen, [0, 0, 0, 0]


def _vorlage_prisma(r: float, h: float):
    """Tripelprisma des Rückstrahlers: sechs Dreiecke zur Spitze."""
    punkte = []
    for k in range(6):
        w = k * math.pi / 3
        punkte.append((math.cos(w) * r, math.sin(w) * r, 0.0))
    punkte.append((0.0, 0.0, h))
    flaechen = [(k, (k + 1) % 6, 6) for k in range(6)]
    return punkte, flaechen, [0] * 6


def _vorlage_rille(laenge: float, breite: float, h: float):
    """Kurzes Stück einer Dreiecksrille (Scheinwerfergehäuse)."""
    l2, b2 = laenge / 2, breite / 2
    punkte = [(-l2, -b2, 0.0), (l2, -b2, 0.0), (l2, 0.0, h), (-l2, 0.0, h),
              (l2, b2, 0.0), (-l2, b2, 0.0)]
    flaechen = [(0, 1, 2, 3), (3, 2, 4, 5)]
    return punkte, flaechen, [0, 0]


def _grundplatte(ob, mat):
    """Kopie eines Bodens als Grundplatte der Quellen (deckt jeden Texel)."""
    k = ob.copy()
    k.data = ob.data.copy()
    k.name = "_quelle_grund"
    bpy.context.scene.collection.objects.link(k)
    k.data.materials.clear()
    k.data.materials.append(mat)
    return k


def _optik(einh: Einheit, art: str, platte, drin, proj, mats, einheit: dict):
    """Hochpoly-Quellen einer Kammer (nur kanonische Seite, nicht LOD1)."""
    if not einh.kanonisch or einh.lod or platte is None:
        return
    rot = _emissionsfarbe(mats["licht_hinten"])
    brems = _emissionsfarbe(mats["bremslicht"])
    null = (0.0, 0.0, 0.0)
    if art == "schlusslicht":
        m = einheit.get("waben_m", 0.006)
        r = m / math.sqrt(3)
        orte = _versetzt(einh, platte, drin, proj, 1.5 * r, math.sqrt(3) * r)
        ob = _stempeln("_quelle_wabe", orte, _vorlage_wabe(r, 0.0009),
                       [_quellmat(rot, PEGEL["waben_seite"]),
                        _quellmat(_kern(rot, 0.12), PEGEL["waben_kern"])])
        grund = _quellmat(rot, PEGEL["waben_grund"])
    elif art == "bremslicht":
        m = einheit.get("led_m", 0.0075)
        orte = _raster(einh, platte, drin, proj, m, m * 0.866, versatz_zeile=0.5)
        ob = _stempeln("_quelle_led", orte, _vorlage_led(m),
                       [_quellmat(brems, PEGEL["led_grund"]), _quellmat(brems, PEGEL["led_kegel"]),
                        _quellmat(_kern(brems, 0.2), PEGEL["led_linse"])])
        grund = _quellmat(brems, PEGEL["led_grund"])
    elif art in ("blinker", "rueckfahr", "chrom"):
        w = 0.0042
        orte = _raster(einh, platte, drin, proj, w, w)
        # Jede Facette mit eigener Neigung: gestreute Spiegelungen wie ein
        # echter Facettenreflektor (fest aus der Lage, nicht zufällig).
        obs = []
        for gruppe in range(4):
            vers = [(0.45, 0.2), (-0.3, 0.45), (0.2, -0.45), (-0.45, -0.25)][gruppe]
            teil = [o for i, o in enumerate(orte) if (i * 7 + (i // 13) * 3) % 4 == gruppe]
            obs.append(_stempeln("_quelle_facette", teil, _vorlage_facette(w, 0.00045, vers),
                                 [_quellmat(null, 0.0)]))
        obs = [o for o in obs if o is not None]
        ob = g.verbinden(obs, "_quelle_facette") if obs else None
        grund = _quellmat(null, 0.0)
    elif art == "rueckstrahler":
        r = 0.0019
        orte = _versetzt(einh, platte, drin, proj, 1.5 * r, math.sqrt(3) * r)
        ob = _stempeln("_quelle_prisma", orte, _vorlage_prisma(r * 0.98, 0.0008),
                       [_quellmat(null, 0.0)])
        grund = _quellmat(null, 0.0)
    elif art == "gehaeuse":
        orte = _raster(einh, platte, drin, proj, 0.006, 0.0018, versatz_zeile=0.5)
        ob = _stempeln("_quelle_rille", orte, _vorlage_rille(0.0062, 0.0017, 0.0003),
                       [_quellmat(null, 0.0)])
        grund = _quellmat(null, 0.0)
    else:
        return
    einh.quellen.append(_grundplatte(platte, grund))
    if ob is not None:
        einh.quellen.append(ob)


def _versetzt(einh, platte, drin, proj, schritt_s, schritt_t):
    """Wabenraster: Spalten im Abstand ``schritt_s``, jede zweite um eine
    halbe Zeilenhöhe versetzt."""
    ia, ib, _ic = tb.ACHSEN[einh.ansicht]
    ecken = _ecken(einh, platte)
    if not ecken:
        return []
    s0, s1 = min(e[0] for e in ecken) - schritt_s, max(e[0] for e in ecken) + schritt_s
    t0, t1 = min(e[1] for e in ecken) - schritt_t, max(e[1] for e in ecken) + schritt_t
    _o, e_s, _e_t, _n = einh.basis
    e_s = einh.kanon(e_s)
    out = []
    i = 0
    s = s0
    while s <= s1:
        t = t0 + (schritt_t / 2 if i % 2 else 0.0)
        while t <= t1:
            p = einh.welt(s, t)
            a, b = p[ia], p[ib]
            if drin(a, b):
                h = proj(a, b)
                if h is not None:
                    n = Vector(h[1]).normalized()
                    x = (e_s - n * e_s.dot(n)).normalized()
                    out.append((Vector(h[0]) + n * PLATTE_M, x, n.cross(x), n))
            t += schritt_t
        s += schritt_s
        i += 1
    return out


# ---------------------------------------------------------------------------
# Bauformen
# ---------------------------------------------------------------------------

def _band_bauen(poly, einheit, proj, mats, tiefe, typ, einh: Einheit):
    segmente = einheit.get("segmente") or STANDARD_SEGMENTE.get(typ, STANDARD_SEGMENTE["band"])
    achse = _achse_wahl(poly, einheit)
    # Die Reihenfolge gilt für die linke Seite, von der Mitte nach außen
    # gezählt, wenn die lange Achse quer liegt; rechts also umgekehrt.
    quer = (einh.ansicht in ("hinten", "vorn")) == (achse == 0)
    if einh.spiegel and quer and einh.ansicht != "seite":
        segmente = list(reversed(segmente))
    poly2, grenzen, getauscht = _segmentgrenzen(poly, segmente, achse)
    einh.getauscht = getauscht
    if getauscht:
        def proj2(a, b, _p=proj):
            return _p(b, a)
    else:
        proj2 = proj
    a0, a1 = grenzen[0], grenzen[-1]
    laenge = max(a1 - a0, 1e-6)
    rand_m = einheit.get("rand_m", 0.005)
    n_stationen = max(3, int(laenge / (0.02 if einh.lod else 0.01)))
    innen2, _ = tb.polygon_einruecken(poly2, 0.002)
    teile = []
    for i, (name_seg, _f) in enumerate(segmente):
        sa0 = grenzen[i] + (rand_m / 2 if i > 0 else 0.0)
        sa1 = grenzen[i + 1] - (rand_m / 2 if i < len(segmente) - 1 else 0.0)
        einh.kammern.append((name_seg, grenzen[i], grenzen[i + 1]))
        if sa1 <= sa0:
            continue
        n = max(2, round(n_stationen * (sa1 - sa0) / laenge))
        stationen = _stationen(poly2, sa0, sa1, n)
        mat = mats[SEGMENT_MAT.get(name_seg, "leuchte_chrom")]
        platte = _platte("leuchte_boden", stationen, proj2, mat)
        if platte is None:
            continue
        einh.empfaenger.append(platte)
        teile.append(platte)

        def drin(a, b, _s0=sa0, _s1=sa1):
            q = (b, a) if getauscht else (a, b)
            return _s0 + 0.0015 < q[0] < _s1 - 0.0015 and tb.im_polygon(q, innen2)
        _optik(einh, name_seg, platte, drin, proj, mats, einheit)
        if name_seg in ("blinker", "rueckfahr"):
            teile += _lichtquelle(name_seg, poly2, sa0, sa1, proj2, mats, einh, tiefe)
    if not einh.lod:
        hoehe = max(0.004, tiefe * einheit.get("steg_hoehe", 0.7))
        for g_ in grenzen[1:-1]:
            steg = _kammersteg("leuchte_steg", poly2, g_, proj2, mats["leuchte_innen"], hoehe,
                               max(0.002, rand_m * 0.6))
            if steg is not None:
                teile.append(steg)
    return teile


def _lichtquelle(name_seg, poly2, sa0, sa1, proj2, mats, einh: Einheit, tiefe):
    """Leuchtmittel vor dem Facettenreflektor: beim Blinker ein bernsteinfarbener
    LED-Stab längs der Kammer (aus), beim Rückfahrlicht eine klare LED-Linse."""
    am = (sa0 + sa1) / 2
    iv = tb.quer_schnitte(poly2, 0, am)
    if not iv:
        return []
    b0, b1 = max(iv, key=lambda t: t[1] - t[0])
    bm_ = (b0 + b1) / 2
    if name_seg == "blinker":
        pp, nn = [], []
        rand = min(0.006, (sa1 - sa0) * 0.2)
        for i in range(9):
            a = sa0 + rand + (sa1 - sa0 - 2 * rand) * i / 8
            iv = tb.quer_schnitte(poly2, 0, a)
            if not iv:
                continue
            c0, c1 = max(iv, key=lambda t: t[1] - t[0])
            h = proj2(a, (c0 + c1) / 2)
            if h is not None:
                pp.append(Vector(h[0]))
                nn.append(Vector(h[1]).normalized())
        if len(pp) < 2:
            return []
        hoehe = min(0.005, max(0.003, tiefe - 0.006))
        ob = _leiterkoerper(pp, nn, hoehe, 0.0022, "blinker", mats, einh)
        return [ob] if ob is not None else []
    h = proj2(am, bm_)
    if h is None:
        return []
    r = max(0.004, min(0.009, (b1 - b0) * 0.22, (sa1 - sa0) * 0.25))
    ort, n = Vector(h[0]), Vector(h[1]).normalized()
    fz = min(1.0, max(0.003, tiefe - 0.005) / (1.1 * r))
    q = Vector((0, 0, 1)).rotation_difference(n)
    mw = Matrix.Translation(ort) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((1, 1, fz, 1))
    seg = 10 if einh.lod else 16
    teile = [_drehen("leuchte_linse", [(r, 0.0), (r * 0.92, 0.6 * r), (r * 0.55, 0.95 * r),
                                        (0.0, 1.05 * r)], seg, mats["projektorlinse"])]
    if not einh.lod:
        teile.append(_torus("leuchte_chromring", 1.08 * r, 0.12 * r, 0.1 * r, 16, 4, mats["chrom"]))
    for t in teile:
        t.data.transform(mw)
    return teile


def _ring_bauen(poly, einheit, proj, mats, tiefe, einh: Einheit):
    ri = einheit.get("ringe") or {}
    if isinstance(ri, list):             # alte Form: Liste von Leisten
        ri = {}
    f_innen = ri.get("innen", 0.55)
    teile = []
    aussen = _ringplatte("leuchte_boden", poly, f_innen + 0.03, 0.97, proj, mats["leuchte_innen"])
    mitte = _ringplatte("leuchte_boden", poly, 0.0, f_innen - 0.02, proj, mats["bremslicht"],
                        n_rad=3)
    c = tb.schwerpunkt2(poly)

    def skaliert_drin(f0, f1):
        p0 = tb.polygon_skalieren(poly, f0) if f0 > 0 else None
        p1 = tb.polygon_skalieren(poly, f1)

        def drin(a, b):
            return tb.im_polygon((a, b), p1) and (p0 is None or not tb.im_polygon((a, b), p0))
        return drin
    for platte, art, (f0, f1) in ((aussen, "schlusslicht", (f_innen + 0.05, 0.95)),
                                  (mitte, "bremslicht", (0.0, f_innen - 0.04))):
        if platte is None:
            continue
        einh.empfaenger.append(platte)
        teile.append(platte)
        _optik(einh, art, platte, skaliert_drin(f0, f1), proj, mats, einheit)
    einh.kammern.append(("schlusslicht", -1e9, 1e9))
    if not einh.lod:
        # Dunkler Steg zwischen Ring und Mitte.
        rund = _gleichmaessig(tb.polygon_skalieren(poly, f_innen + 0.005), 72)
        pp, nn = [], []
        for a, b in rund:
            h = proj(a, b)
            if h is not None:
                pp.append(h[0])
                nn.append(h[1])
        if len(pp) == len(rund):
            teile.append(tb.band("leuchte_steg", pp, nn, 0.004,
                                 max(0.004, tiefe * einheit.get("steg_hoehe", 0.6)),
                                 mats["leuchte_innen"], geschlossen=True))
    del c
    return teile


def _scheinwerfer_bauen(poly, einheit, proj, mats, tiefe, einh: Einheit):
    achse = _achse_wahl(poly, einheit)
    poly2, grenzen, getauscht = _segmentgrenzen(poly, [("gehaeuse", 1.0)], achse)
    einh.getauscht = getauscht
    einh.kammern.append(("gehaeuse", grenzen[0], grenzen[-1]))
    if getauscht:
        def proj2(a, b, _p=proj):
            return _p(b, a)
    else:
        proj2 = proj
    # Der Boden reicht bis an den Rand (ohne den Saum der Kammern).
    a0 = min(p[0] for p in poly2) + 0.002
    a1 = max(p[0] for p in poly2) - 0.002
    n = max(3, int((a1 - a0) / (0.02 if einh.lod else 0.01)))
    platte = _platte("leuchte_boden", _stationen(poly2, a0, a1, n), proj2, mats["leuchte_innen"])
    teile = []
    if platte is not None:
        einh.empfaenger.append(platte)
        teile.append(platte)
        innen2, _ = tb.polygon_einruecken(poly2, 0.002)

        def drin(a, b):
            return tb.im_polygon((b, a) if getauscht else (a, b), innen2)
        _optik(einh, "gehaeuse", platte, drin, proj, mats, einheit)
    pj = einheit.get("projektoren")
    if pj:
        teile += _projektoren(poly, pj, proj, mats, tiefe, einh)
    return teile


def _projektoren(poly, pj, proj, mats, tiefe, einh: Einheit):
    """Projektormodule: Facettenschale aus Chrom, dunkle Linse, Chromring,
    wahlweise ein Tagfahrlicht-Ring um die Schale."""
    a0, a1 = min(q[0] for q in poly), max(q[0] for q in poly)
    b0, b1 = min(q[1] for q in poly), max(q[1] for q in poly)
    n = pj.get("anzahl", 2)
    r = pj.get("radius_m", min(0.024, 0.3 * (b1 - b0)))
    rand = pj.get("rand_anteil", 0.22)
    lage = pj.get("lage", 0.5)
    teile = []
    for k in range(n):
        # Von außen gezählt, damit beide Seiten gleich aussehen.
        f = rand + (1 - 2 * rand) * (k + 0.5) / n
        if einh.ansicht in ("vorn", "hinten") and einh.spiegel:
            f = 1.0 - f
        a = a0 + (a1 - a0) * f
        b = b0 + (b1 - b0) * lage
        if einh.ansicht == "oben" and einh.spiegel:
            b = b0 + (b1 - b0) * (1.0 - lage)
        h = proj(a, b)
        if h is None:
            continue
        ort, normale = Vector(h[0]), Vector(h[1]).normalized()
        fahrt = Vector((1 if ort.x > 0 else -1, 0, 0))
        richtung = (normale + fahrt * pj.get("vorhalt", 0.6)).normalized()
        # Das Modul darf nicht ans Deckglas stoßen.
        hmax = max(0.006, tiefe - 0.004)
        teile += _projektor(r, richtung, ort, hmax, mats, einh, pj.get("ring", True))
    return teile


def _projektor(r, richtung, ort, hmax, mats, einh: Einheit, ring: bool):
    lod = einh.lod
    seg = 12 if lod else 20
    # Höhe skalieren, wenn das Gehäuse flach ist.
    fz = min(1.0, hmax / (0.95 * r))
    q = Vector((0, 0, 1)).rotation_difference(richtung)
    mw = Matrix.Translation(ort) @ q.to_matrix().to_4x4() @ Matrix.Diagonal((1, 1, fz, 1))
    teile = []
    # Schale: vom Boden zum Rand hoch, innen zur Linse hinab — mit harten
    # Facetten (Ringe × Segmente), die das Umgebungslicht zerlegen.
    profil = [(1.62 * r, -0.02 * r), (1.58 * r, 0.5 * r), (1.45 * r, 0.47 * r),
              (1.25 * r, 0.3 * r), (1.07 * r, 0.14 * r), (0.96 * r, 0.1 * r)]
    if lod:
        profil = [profil[0], profil[1], profil[3], profil[5]]
    schale = _drehen("leuchte_schale", profil, seg, mats["leuchte_chrom"], glatt=False)
    linse_p = [(1.0 * r, 0.1 * r)]
    for i in range(1, 7 if not lod else 4):
        w = (math.pi / 2) * i / (6 if not lod else 3)
        linse_p.append((r * math.cos(w) if i < (6 if not lod else 3) else 0.0,
                        0.1 * r + 0.78 * r * math.sin(w)))
    linse = _drehen("leuchte_linse", linse_p, seg + 4, mats["projektorlinse"], glatt=True)
    teile += [schale, linse]
    if not lod:
        teile.append(_torus("leuchte_chromring", 1.03 * r, 0.055 * r, 0.12 * r, 24, 5, mats["chrom"]))
    for t in teile:
        t.data.transform(mw)
    if ring:
        # Tagfahrlicht-Ring: Lichtleiter oben auf dem Schalenrand.
        rr = 1.52 * r
        pts = []
        for i in range(48 if not lod else 24):
            w = 2 * math.pi * i / (48 if not lod else 24)
            pts.append(mw @ Vector((rr * math.cos(w), rr * math.sin(w), 0.52 * r)))
        nn = [richtung] * len(pts)
        ob = _leiterkoerper(pts, nn, 0.0, 0.0022, "licht_vorn", mats, einh, geschlossen=True)
        if ob is not None:
            teile.append(ob)
    return teile


def _drehen(name, profil, seg, mat, glatt=True):
    """Drehkörper um +Z aus ``[(r, z)]`` (Normalen nach außen/oben)."""
    bm = bmesh.new()
    pol = profil[-1][0] < 1e-6
    ringe = []
    for r, z in (profil[:-1] if pol else profil):
        ringe.append([bm.verts.new((r * math.cos(2 * math.pi * k / seg),
                                    r * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)])
    for r0, r1 in zip(ringe, ringe[1:]):
        for k in range(seg):
            bm.faces.new((r0[k], r0[(k + 1) % seg], r1[(k + 1) % seg], r1[k]))
    # Innen geschlossen: Pol oder Deckel zur Achse.
    m = bm.verts.new((0, 0, profil[-1][1]))
    r = ringe[-1]
    for k in range(seg):
        bm.faces.new((r[k], r[(k + 1) % seg], m))
    # Nach oben (zum Betrachter) ausrichten; der Shader dreht Rückseiten ohnehin.
    for f in bm.faces:
        f.normal_update()
        c = f.calc_center_median()
        if f.normal.dot(Vector((c.x, c.y, 0)).normalized() * 0.3 + Vector((0, 0, 1))) < 0:
            f.normal_flip()
    ob = g.objekt_aus(bm, name, [mat])
    for p in ob.data.polygons:
        p.use_smooth = glatt
    return ob


def _torus(name, R, r, z, n_gross, n_klein, mat):
    bm = bmesh.new()
    ringe = []
    for i in range(n_gross):
        w = 2 * math.pi * i / n_gross
        c, s = math.cos(w), math.sin(w)
        ringe.append([bm.verts.new(((R + r * math.cos(2 * math.pi * j / n_klein)) * c,
                                    (R + r * math.cos(2 * math.pi * j / n_klein)) * s,
                                    z + r * math.sin(2 * math.pi * j / n_klein)))
                      for j in range(n_klein)])
    for i in range(n_gross):
        a, b = ringe[i], ringe[(i + 1) % n_gross]
        for j in range(n_klein):
            bm.faces.new((a[j], b[j], b[(j + 1) % n_klein], a[(j + 1) % n_klein]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = g.objekt_aus(bm, name, [mat])
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


# ---------------------------------------------------------------------------
# Lichtleiter
# ---------------------------------------------------------------------------

STANDARD_LEITER = {
    "band": [{"verlauf": "rand", "abstand_m": 0.009}],
    "winkel": [{"verlauf": "rand", "abstand_m": 0.009}],
    "bumerang": [{"verlauf": "rand", "abstand_m": 0.009}],
    "band_quer": [{"quer": [0.5], "abstand_m": 0.006}],
    "ring": [{"ringe": [0.84]}],
    "scheinwerfer": [{"verlauf": "rand", "abstand_m": 0.007, "mat": "licht_vorn"}],
}


def _leiter_alle(poly, einheit, proj, mats, einh: Einheit, tiefe, typ):
    teile = []
    cfgs = einheit.get("lichtleiter", STANDARD_LEITER.get(typ, []))
    for cfg in cfgs:
        mat = cfg.get("mat", "licht_vorn" if typ == "scheinwerfer" else "licht_hinten")
        d = cfg.get("durchmesser_m", 0.008 if typ != "scheinwerfer" else 0.006)
        hoehe = min(cfg.get("hoehe_m", 0.008), max(d * 0.6, tiefe - d / 2 - 0.003))
        for pfad, geschlossen in _leiterwege(poly, cfg, einheit, einh):
            dicht = tb.verdichten(list(pfad) + ([pfad[0]] if geschlossen else []),
                                  0.02 if einh.lod else 0.008)
            if geschlossen:
                dicht = dicht[:-1]
            stuecke, pp, nn = [], [], []
            mitte = tb.schwerpunkt2(poly)
            for a, b in dicht:
                # Randläufe rücken an den Boden heran; gerade Stäbe enden
                # dort, wo der Boden aufhört (sonst zacken sie).
                h = (_naechster_boden(proj, a, b, mitte, d) if "verlauf" in cfg or "ringe" in cfg
                     else proj(a, b))
                if h is None:
                    if len(pp) >= 2:
                        stuecke.append((pp, nn, False))
                    pp, nn = [], []
                    geschlossen = False
                    continue
                pp.append(Vector(h[0]))
                nn.append(Vector(h[1]).normalized())
            if len(pp) >= 2:
                stuecke.append((pp, nn, geschlossen))
            for pp, nn, gg in stuecke:
                ob = _leiterkoerper(pp, nn, hoehe, d / 2, mat, mats, einh, geschlossen=gg)
                if ob is not None:
                    teile.append(ob)
    return teile


def _naechster_boden(proj, a, b, mitte, abstand):
    """Boden unter (a, b); liegt der Punkt über einer Gehäusewand (schräge
    Leuchte: der vertiefte Boden ist gegenüber dem Umriss verschoben), so weit
    zur Mitte rücken, bis er den Boden trifft, plus ``abstand``."""
    h = proj(a, b)
    if h is not None:
        return h
    da, db = mitte[0] - a, mitte[1] - b
    lg = math.hypot(da, db)
    if lg < 1e-6:
        return None
    da, db = da / lg, db / lg
    schritt = 0.002
    for k in range(1, 26):
        s = k * schritt
        if s > lg:
            return None
        if proj(a + da * s, b + db * s) is not None:
            s += abstand
            return proj(a + da * min(s, lg), b + db * min(s, lg))
    return None


def _leiterwege(poly, cfg, einheit, einh: Einheit):
    """Wege eines Lichtleiters im Umriss (Ansichtskoordinaten)."""
    wege = []
    if "ringe" in cfg:
        for f in cfg["ringe"]:
            wege.append((tb.polygon_skalieren(poly, f), True))
        return wege
    innen, aussen = tb.polygon_einruecken(poly, cfg.get("abstand_m", 0.009))
    if "senkrecht" in cfg:
        # Senkrechte Stäbe: bei einem Anteil der ersten Bildachse (von der
        # Wagenmitte nach außen gezählt, wie die Kammern).
        a0 = min(q[0] for q in innen)
        a1 = max(q[0] for q in innen)
        for anteil in cfg["senkrecht"]:
            if einh.spiegel and einh.ansicht in ("hinten", "vorn"):
                anteil = 1.0 - anteil
            c = a0 + (a1 - a0) * anteil
            for s0, s1 in tb.quer_schnitte(innen, 0, c):
                wege.append(([(c, s0), (c, s1)], False))
        return wege
    if "quer" in cfg:
        b0 = min(q[1] for q in innen)
        b1 = max(q[1] for q in innen)
        for anteil in cfg["quer"]:
            c = b0 + (b1 - b0) * anteil
            for s0, s1 in tb.quer_schnitte(innen, 1, c):
                wege.append(([(s0, c), (s1, c)], False))
    else:
        verlauf = cfg.get("verlauf", "rand")
        if verlauf == "rand":
            wege.append((innen, True))
        else:
            ia, ib, _ic = tb.ACHSEN[einh.ansicht]
            if verlauf in ("aussen", "innen"):
                c = tb.schwerpunkt2(poly)
                y = c[1] if einh.ansicht == "oben" else (c[0] if einh.ansicht in ("vorn", "hinten") else 1.0)
                s = (1.0 if y >= 0 else -1.0) * (1.0 if verlauf == "aussen" else -1.0)
                d3 = (0.0, s, 0.0)
            else:
                d3 = {"oben": (0, 0, 1), "unten": (0, 0, -1), "vorn": (1, 0, 0),
                      "hinten": (-1, 0, 0)}[verlauf]
            lauf = tb.laengster_lauf(innen, aussen, (d3[ia], d3[ib]))
            if len(lauf) >= 2:
                wege.append((lauf, False))
    bereich = cfg.get("bereich")
    if bereich:
        wege = _beschneiden(wege, poly, einheit, bereich)
    return wege


def _beschneiden(wege, poly, einheit, bereich):
    """Wege auf einen Anteil der langen Achse kürzen."""
    achse = _achse_wahl(poly, einheit)
    lo = min(p[achse] for p in poly)
    hi = max(p[achse] for p in poly)
    c0, c1 = lo + (hi - lo) * bereich[0], lo + (hi - lo) * bereich[1]
    out = []
    for pfad, geschlossen in wege:
        dicht = tb.verdichten(list(pfad) + ([pfad[0]] if geschlossen else []), 0.004)
        lauf = []
        for q in dicht:
            if c0 <= q[achse] <= c1:
                lauf.append(q)
            elif len(lauf) >= 2:
                out.append((lauf, False))
                lauf = []
            else:
                lauf = []
        if len(lauf) >= 2:
            out.append((lauf, False))
    return out


def _leiterkoerper(punkte, normalen, hoehe, radius, mat_name, mats, einh: Einheit,
                   geschlossen=False):
    """Runder Lichtleiter über dem Boden. UV: v läuft um den Querschnitt
    (0,5 = zum Betrachter), u entlang — die Lage im Querverlauf des Atlas
    setzt ``atlas_anwenden``."""
    n = len(punkte)
    if n < 2:
        return None
    k = 6 if einh.lod else 10
    bm = bmesh.new()
    uv = bm.loops.layers.uv.new(backen.UV_NAME)
    ringe, mitten = [], []
    laenge = [0.0]
    for i in range(1, n):
        laenge.append(laenge[-1] + (Vector(punkte[i]) - Vector(punkte[i - 1])).length)
    gesamt = laenge[-1] + (((Vector(punkte[0]) - Vector(punkte[-1])).length) if geschlossen else 0.0)
    for i in range(n):
        p = Vector(punkte[i])
        nn = Vector(normalen[i]).normalized()
        if geschlossen:
            a, b = Vector(punkte[i - 1]), Vector(punkte[(i + 1) % n])
        else:
            a, b = Vector(punkte[max(i - 1, 0)]), Vector(punkte[min(i + 1, n - 1)])
        t = b - a
        t = t - nn * t.dot(nn)
        if t.length < 1e-9:
            t = Vector((0, 0, 1)).cross(nn) if abs(nn.z) < 0.9 else Vector((1, 0, 0))
        t.normalize()
        s = nn.cross(t).normalized()
        m = p + nn * hoehe
        mitten.append(m)
        ring = []
        for j in range(k + 1):
            w = -math.pi / 2 + 2 * math.pi * j / k       # j = k/2: zum Betrachter
            ring.append(bm.verts.new(m + s * (radius * math.cos(w)) + nn * (radius * math.sin(w))))
        ringe.append(ring)
    reihen = list(range(n)) + ([0] if geschlossen else [])
    us = [laenge[i] / max(gesamt, 1e-9) for i in range(n)] + ([1.0] if geschlossen else [])
    for (i0, i1), (u0, u1) in zip(zip(reihen, reihen[1:]), zip(us, us[1:])):
        r0, r1 = ringe[i0], ringe[i1]
        for j in range(k):
            f = bm.faces.new((r0[j], r0[j + 1], r1[j + 1], r1[j]))
            for lp, (uu, vv) in zip(f.loops, ((u0, j / k), (u0, (j + 1) / k), (u1, (j + 1) / k),
                                              (u1, j / k))):
                lp[uv].uv = (uu, vv)
    if not geschlossen:
        for i, u in ((0, 0.0), (n - 1, 1.0)):
            m = bm.verts.new(mitten[i])
            r = ringe[i]
            for j in range(k):
                try:
                    f = bm.faces.new((r[j], r[j + 1], m))
                except ValueError:
                    continue
                for lp in f.loops:
                    lp[uv].uv = (u, 0.5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        f.smooth = True
    ob = g.objekt_aus(bm, "leuchte_leiter", [mats[mat_name]])
    einh.leiter.append((ob, mat_name))
    if einh.kanonisch and not einh.lod and mat_name != "blinker":
        einh.halo.append(([einh.ebene(p) for p in mitten] + ([einh.ebene(mitten[0])] if geschlossen else []),
                          mat_name))
    return ob


# ---------------------------------------------------------------------------
# Deckglas
# ---------------------------------------------------------------------------

def deckglas_bauen(flaechen, einheit: dict, mats, abstand: float = 0.0015,
                   kante_m: float = 0.004):
    """Deckglas einer Zone mit Einheit: die alte Haut, ``abstand`` darüber,
    mit einer Glaskante ``kante_m`` nach innen. Klar über den Kammern aus
    ``klar`` (Rückfahrlicht), sonst nach ``glas`` getönt."""
    if einheit.get("stil") == "klassisch":
        return []                   # baut ihre Streuscheibe selbst
    eigene_materialien(mats)
    einheiten = [e for e in _BAU if e.zone == id(einheit)]
    glas = einheit.get("glas", "klar" if einheit.get("typ") == "scheinwerfer" else "rot")
    matnamen = [f"deckglas_{glas}", "deckglas_klar"]
    index, punkte, normalen, polys, klasse = {}, [], [], [], []
    for eck in flaechen:
        a, b, c = Vector(eck[0]), Vector(eck[1]), Vector(eck[2])
        fn = (b - a).cross(c - a)
        if fn.length < 1e-12:
            continue
        fn.normalize()
        ids = []
        for co in eck:
            k = (round(co[0], 5), round(co[1], 5), round(co[2], 5))
            if k not in index:
                index[k] = len(punkte)
                punkte.append(Vector(co))
                normalen.append(Vector((0, 0, 0)))
            normalen[index[k]] += fn
            ids.append(index[k])
        if len(set(ids)) >= 3:
            polys.append(ids)
            mitte = sum((Vector(q) for q in eck), Vector()) / len(eck)
            klasse.append(1 if _unter_klarglas(mitte, einheiten) else 0)
    if not polys:
        return []
    versetzt = [p + (nn.normalized() if nn.length > 0 else nn) * abstand
                for p, nn in zip(punkte, normalen)]
    bm = bmesh.new()
    vs = [bm.verts.new(p) for p in versetzt]
    for ids, kl in zip(polys, klasse):
        try:
            f = bm.faces.new([vs[i] for i in ids])
        except ValueError:
            continue
        f.material_index = kl
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # Glaskante: am Rand ein schmales Band nach innen (gemeinsame Ecken).
    richtung = {v: -normalen[i].normalized() for i, v in enumerate(vs) if normalen[i].length > 0}
    unten = {}
    for e in [e for e in bm.edges if len(e.link_faces) == 1]:
        f0 = e.link_faces[0]
        v0, v1 = e.verts
        for v in (v0, v1):
            if v not in unten:
                unten[v] = bm.verts.new(v.co + richtung.get(v, Vector()) * kante_m)
        try:
            f = bm.faces.new((v1, v0, unten[v0], unten[v1]))
            f.material_index = f0.material_index
        except ValueError:
            pass
    for f in bm.faces:
        f.smooth = True
    ob = g.objekt_aus(bm, "leuchte_deckglas", [mats[m] for m in matnamen])
    return [ob]


def _unter_klarglas(p, einheiten) -> bool:
    for e in einheiten:
        # Kammern und Umriss stehen in Koordinaten der Seite, die sie gebaut hat.
        ia, ib, _ic = tb.ACHSEN[e.ansicht]
        a, b = p[ia], p[ib]
        q = (b, a) if e.getauscht else (a, b)
        if not tb.im_polygon((a, b), e.poly):
            continue
        for name, k0, k1 in e.kammern:
            if k0 <= q[0] <= k1 and name in e.klar:
                return True
    return False


# ---------------------------------------------------------------------------
# Atlas: UV, Backen, Karten
# ---------------------------------------------------------------------------

def _ordner(key: str) -> Path:
    d = Path(tempfile.gettempdir()) / "fahrzeug_leuchten" / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inseln(einheiten):
    """Je kanonischer Einheit die Ausdehnung in der Ebene (Meter)."""
    grenzen = {}
    for e in einheiten:
        if not e.kanonisch:
            continue
        ss, tt = [], []
        for ob in e.empfaenger:
            mw = ob.matrix_world
            for v in ob.data.vertices:
                s, t = e.ebene(mw @ v.co)
                ss.append(s)
                tt.append(t)
        if not ss:
            continue
        rand = 0.004
        grenzen[e.schluessel] = (min(ss) - rand, min(tt) - rand, max(ss) + rand, max(tt) + rand)
    return grenzen


def _layout(grenzen) -> dict:
    schluessel = sorted(grenzen)
    groessen = [(grenzen[k][2] - grenzen[k][0], grenzen[k][3] - grenzen[k][1]) for k in schluessel]
    dichte, lage = backen.dichte_suchen(groessen, ATLAS_PX, ATLAS_PX - BAND_PX - LUECKE_PX,
                                        LUECKE_PX, DICHTE_MAX)
    inseln = {}
    for k, (x, y) in zip(schluessel, lage):
        inseln[k] = (x, y + BAND_PX + LUECKE_PX, grenzen[k][0], grenzen[k][1])
    return {"dichte": dichte, "inseln": inseln}


def _uv_planar(einh: Einheit, layout) -> None:
    insel = layout["inseln"].get(einh.schluessel)
    if insel is None:
        for ob in einh.empfaenger:
            backen.uv_fest(ob, *_feld_uv("schwarz"))
        return
    x0, y0, s0, t0 = insel
    d = layout["dichte"]

    def f(p, _poly):
        s, t = einh.ebene(p)
        return ((x0 + (s - s0) * d) / ATLAS_PX, (y0 + (t - t0) * d) / ATLAS_PX)
    for ob in einh.empfaenger:
        backen.uv_setzen(ob, f)


def _feld_uv(name):
    x = dict(FELDER).get(name, 16)
    return ((x + FELD_PX / 2) / ATLAS_PX, (16 + FELD_PX / 2) / ATLAS_PX)


def _uv_leiter(ob, mat_name) -> None:
    x = STREIFEN.get(mat_name)
    uv = ob.data.uv_layers[backen.UV_NAME]
    werte = np.empty(len(uv.data) * 2, dtype=np.float32)
    uv.data.foreach_get("uv", werte)
    w, h = STREIFEN_PX
    rand = 6
    werte[0::2] = (x + rand + werte[0::2] * (w - 2 * rand)) / ATLAS_PX
    werte[1::2] = (16 + rand + werte[1::2] * (h - 2 * rand)) / ATLAS_PX
    uv.data.foreach_set("uv", werte)


def _uv_neutral(ob, eigene: set) -> None:
    """Flächen mit Atlas-Materialien außerhalb der Einheiten (Spiegelblinker,
    LED-Leisten, Schalen, Stege) ins passende Farbfeld legen. Andere Flächen
    und UV anderer Stränge bleiben, wie sie sind."""
    me = ob.data
    if ob in eigene or not me.polygons:
        return
    namen = [m.name if m is not None else "" for m in me.materials]
    if not any(n in TEXTURIERT for n in namen):
        return
    uv = me.uv_layers.get(backen.UV_NAME) or me.uv_layers.new(name=backen.UV_NAME)
    werte = np.empty(len(me.loops) * 2, dtype=np.float32)
    uv.data.foreach_get("uv", werte)
    for p in me.polygons:
        name = namen[p.material_index] if p.material_index < len(namen) else ""
        if name not in TEXTURIERT:
            continue
        u, v = _feld_uv(name if name in LEUCHTEND else "schwarz")
        for li in p.loop_indices:
            werte[2 * li] = u
            werte[2 * li + 1] = v
    uv.data.foreach_set("uv", werte)


def _querverlauf(v):
    """Helligkeit um den Lichtleiter (v = 0,5 zum Betrachter)."""
    d = np.minimum(np.abs(v - 0.5), 0.5)
    kern = np.exp(-(d / 0.16) ** 2)
    return PEGEL["leiter_unten"] + (PEGEL["leiter_flanke"] - PEGEL["leiter_unten"]) * np.clip(
        1 - d / 0.5, 0, 1) + (PEGEL["leiter_kern"] - PEGEL["leiter_flanke"]) * kern


def _streifen_malen(feld_em, farben, feldfarben) -> None:
    """Neutrale Felder und Querverläufe in das Leuchtbild (sRGB)."""
    s = feld_em.shape[0] / ATLAS_PX
    for name, x in FELDER:
        farbe = feldfarben.get(name, (0.0, 0.0, 0.0))
        y0, y1 = int(16 * s), int((16 + FELD_PX) * s)
        feld_em[y0:y1, int(x * s):int((x + FELD_PX) * s), :3] = backen.linear_nach_srgb(farbe)
    w, h = STREIFEN_PX
    for name, x in STREIFEN.items():
        farbe = np.array(farben.get(name, (1.0, 1.0, 1.0)), dtype=np.float32)
        y0, y1 = int(16 * s), int((16 + h) * s)
        rand = 6 * s
        zeilen = np.arange(y0, y1)
        v = np.clip((zeilen + 0.5 - y0 - rand) / max(y1 - y0 - 2 * rand, 1), 0, 1)
        hell = _querverlauf(v)[:, None] * (0.35 if name == "blinker" else 1.0)
        # Der heiße Kern entsättigt leicht, wie eine überbelichtete LED.
        kern = np.exp(-((v - 0.5) / 0.1) ** 2)[:, None] * WEISSKERN
        lin = hell * (farbe[None, :] * (1 - kern) + kern)
        feld_em[y0:y1, int(x * s):int((x + w) * s), :3] = backen.linear_nach_srgb(lin)[:, None, :]


def _halo_malen(feld_em, einheiten, layout, farben) -> None:
    """Streulicht der Lichtleiter auf dem Boden darunter (weiche Linie)."""
    h, w = feld_em.shape[:2]
    lin = backen.srgb_nach_linear(feld_em[..., :3])
    d = layout["dichte"]
    sigma = 0.006 * d
    for e in einheiten:
        insel = layout["inseln"].get(e.schluessel)
        if insel is None:
            continue
        x0, y0, s0, t0 = insel
        for pfad, mat in e.halo:
            farbe = np.array(farben.get(mat, (1, 1, 1)), dtype=np.float32)
            pts = np.array([(x0 + (s - s0) * d, y0 + (t - t0) * d) for s, t in pfad], dtype=np.float32)
            for p, q in zip(pts, pts[1:]):
                lo = np.floor(np.minimum(p, q) - 3 * sigma).astype(int)
                hi = np.ceil(np.maximum(p, q) + 3 * sigma).astype(int)
                lo = np.clip(lo, 0, [w - 1, h - 1])
                hi = np.clip(hi, 0, [w - 1, h - 1])
                if (hi <= lo).any():
                    continue
                xs = np.arange(lo[0], hi[0]) + 0.5
                ys = np.arange(lo[1], hi[1]) + 0.5
                gx, gy = np.meshgrid(xs, ys)
                dv = q - p
                ll = float(dv @ dv) or 1e-9
                tt = np.clip(((gx - p[0]) * dv[0] + (gy - p[1]) * dv[1]) / ll, 0, 1)
                dx = gx - (p[0] + tt * dv[0])
                dy = gy - (p[1] + tt * dv[1])
                wert = PEGEL["halo"] * np.exp(-(dx * dx + dy * dy) / (sigma * sigma))
                block = lin[lo[1]:hi[1], lo[0]:hi[0]]
                np.maximum(block, wert[..., None] * farbe[None, None, :], out=block)
    feld_em[..., :3] = backen.linear_nach_srgb(np.clip(lin, 0, 1))


def atlas_anwenden(objekte, p: dict) -> None:
    """UV setzen, backen (volle Stufe) bzw. den Atlas übernehmen (LOD1) und
    die Karten an die Materialien hängen. ``objekte``: alles, was gleich zur
    Karosserie verbunden wird."""
    einheiten = list(_BAU)
    _BAU.clear()
    if not einheiten:
        return
    key = p.get("_key", "fahrzeug")
    lod = any(e.lod for e in einheiten)
    try:
        if lod:
            stand = _ATLAS.get(key)
            if stand is None:
                return
            layout = stand["layout"]
        else:
            layout = _layout(_inseln(einheiten))
        eigene = set()
        for e in einheiten:
            _uv_planar(e, layout)
            eigene.update(e.empfaenger)
            for ob, mat in e.leiter:
                _uv_leiter(ob, mat)
                eigene.add(ob)
        for ob in objekte:
            if ob is not None and ob.type == "MESH":
                _uv_neutral(ob, eigene)
        mats = {m.name: m for m in bpy.data.materials}
        farben = {n: _emissionsfarbe(mats[n]) for n in LEUCHTEND if n in mats}
        if lod:
            karten = {art: backen.verkleinern(pfad, LOD_PX, _ordner(key) / f"lod1_{art}.png")
                      for art, pfad in stand["karten"].items()}
        else:
            karten = _backen(key, einheiten, layout, farben, _feldfarben(mats, farben))
            _ATLAS[key] = {"layout": layout, "karten": karten,
                           "basen": {e.schluessel: e.basis for e in einheiten if e.kanonisch}}
            _ATLAS["_aktuell"] = _ATLAS[key]
        _karten_zuweisen(karten, mats)
    finally:
        for e in einheiten:
            for q in e.quellen:
                if q.name in bpy.data.objects:
                    bpy.data.objects.remove(q, do_unlink=True)


def _backen(key, einheiten, layout, farben, feldfarben) -> dict:
    ziele = [ob for e in einheiten if e.kanonisch for ob in e.empfaenger]
    quellen = [q for e in einheiten for q in e.quellen]
    glas = [o for o in bpy.data.objects if o.name.startswith("leuchte_deckglas")]
    # Die rechte Seite liegt auf denselben Texeln — nicht mitbacken.
    andere = [ob for e in einheiten if not e.kanonisch for ob in e.empfaenger]
    ordner = _ordner(key)
    roh = backen.backen(ziele, quellen, ordner, f"{key}_roh", groesse=ATLAS_PX,
                        arten=("normal", "emission", "ao"), verbergen=glas + andere,
                        abstand_m=KAEFIG_M, reichweite_m=2 * KAEFIG_M, ao_weite_m=0.025)
    karten = {}
    img = backen.bild_laden(roh["emission"], "emission", f"{key}_em_roh")
    feld = backen.pixel_lesen(img)
    _halo_malen(feld, einheiten, layout, farben)
    _streifen_malen(feld, farben, feldfarben)
    _felder(feld, None)
    backen.pixel_schreiben(img, feld)
    karten["emission"] = backen.speichern(img, ordner / f"{key}_emission.png")
    bpy.data.images.remove(img)
    for art in ("normal", "ao"):
        img = backen.bild_laden(roh[art], art, f"{key}_{art}_roh")
        feld = backen.pixel_lesen(img)
        _felder(feld, backen.VORGABE[art])
        backen.pixel_schreiben(img, feld)
        pfad = backen.speichern(img, ordner / f"{key}_{art}_voll.png")
        bpy.data.images.remove(img)
        if art == "ao":
            pfad = backen.verkleinern(pfad, AO_PX, ordner / f"{key}_ao.png")
        karten[art] = pfad
    return karten


def _felder(feld, wert) -> None:
    """Den neutralen Streifen unten mit dem Vorgabewert füllen (Normal, AO)."""
    if wert is None:
        return
    s = feld.shape[0] / ATLAS_PX
    feld[:int((BAND_PX + LUECKE_PX // 2) * s), :, :] = wert


#: Grundfarbe der Leuchtmittel im ausgeschalteten Zustand (linear): ein
#: ausgeschaltetes Bremslicht ist dunkles Rubinrot, kein roter Lack — sonst
#: leuchtet es in der Sonne, als wäre es an.
AUS_FARBE = {"bremslicht": ((0.07, 0.004, 0.004), 0.18)}


def _karten_zuweisen(karten, mats) -> None:
    bilder = {art: backen.bild_laden(pfad, art, f"leuchten_{art}") for art, pfad in karten.items()}
    for name, (farbe, rauheit) in AUS_FARBE.items():
        m = mats.get(name)
        if m is not None:
            bsdf = next(n for n in m.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
            bsdf.inputs["Base Color"].default_value = (*farbe, 1.0)
            bsdf.inputs["Roughness"].default_value = rauheit
    for name in TEXTURIERT:
        m = mats.get(name)
        if m is None:
            continue
        leuchtet = name in LEUCHTEND or name == "leuchte_innen"
        backen.material_ausstatten(m, normal=bilder.get("normal"), ao=bilder.get("ao"),
                                   emission=bilder.get("emission") if leuchtet else None,
                                   emission_staerke=STAERKE.get(name) if leuchtet else None)


def _staerke(mat) -> float:
    bsdf = next(n for n in mat.node_tree.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    return float(bsdf.inputs["Emission Strength"].default_value)


def _feldfarben(mats, farben) -> dict:
    """Farbe der neutralen Felder: Flächen außerhalb der Einheiten leuchten
    so hell wie bisher, obwohl ihr Material jetzt ``STAERKE`` trägt."""
    out = {}
    for n, c in farben.items():
        alt = _staerke(mats[n])
        neu = STAERKE.get(n, alt)
        out[n] = tuple(min(1.0, x * alt / max(neu, 1e-6)) for x in c)
    return out
