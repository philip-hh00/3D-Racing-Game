"""Teile-Bibliothek, Räder: Reifen, Felge, Bremsscheibe, Bremssattel.

Läuft in Blender. Alles in Radkoordinaten: Ursprung in der Nabenmitte,
Drehachse Y, Außenseite bei +Y (``fahrzeug_bauen.rad_bauen`` spiegelt die
rechte Seite). Was sich mit dem Rad dreht, ist um Y rotationssymmetrisch
aufgebaut oder regelmäßig verteilt. Parameter: siehe Kopf von ``teile.py``
(``teile.reifen``, ``teile.felge``, ``teile.bremse``, ``teile.sattel``).
"""
from __future__ import annotations

import math

import bmesh
from mathutils import Matrix

import gemeinsam as g
import teile as t

#: Speichenmuster je Felgenart: (Winkelversatz °, Breite an der Nabe, Breite am Rand)
MUSTER = {
    "fuenf": ([(0.0, 0.075, 0.05)], 5),
    "zehn": ([(-7.0, 0.04, 0.028), (7.0, 0.04, 0.028)], 5),
    "vielspeichen": ([(0.0, 0.028, 0.017)], 14),
    "y": ([(0.0, 0.05, 0.03), (-9.0, 0.028, 0.02), (9.0, 0.028, 0.02)], 6),
    "tiefbett": ([(0.0, 0.05, 0.035)], 6),
    "zentral": ([(-6.0, 0.036, 0.024), (6.0, 0.036, 0.024)], 5),
    "mesh": ([(-12.0, 0.022, 0.016), (12.0, 0.022, 0.016)], 10),
}


# ---------------------------------------------------------------------------
# Reifen
# ---------------------------------------------------------------------------

def reifen(R: float, b: float, rr: float, tp: dict, mats, name: str = "reifen"):
    """Reifen mit gerundeter Flanke, Felgenschutzkante und Laufflächenprofil.

    Umfangsrillen (``rillen``) laufen durch; Querrillen entstehen je Block
    (``bloecke`` je Umfang) aus vier Ringen, pfeilförmig versetzt (die Ecken
    eines Rings liegen nicht auf einem Winkel). ``sport``: durchgehende
    Mittelrippe, Querrillen nur an den Schultern; ``strasse``: Querrillen
    über die ganze Lauffläche; ``slick``: glatt.
    """
    art = tp.get("profil", "sport")
    halb = b / 2
    tiefe = tp.get("tiefe_m", 0.007)
    wulst = tp.get("wulst_m", 0.007)
    rb = tp.get("rille_m", 0.012)
    rillen = tp.get("rillen", {"sport": [-0.2, 0.2], "strasse": [-0.26, 0.0, 0.26]}.get(art, []))
    h = R - rr
    # (r, y, Art): f Flanke, sr Schulterrand, s Schulter, m Mitte, r Rillengrund
    flanke = [
        (rr + 0.002, -halb + 0.02, "f"),
        (rr + 0.012, -halb - 0.002, "f"),
        (rr + 0.02, -halb - 0.006, "f"),
        (rr + 0.028, -halb - 0.002, "f"),
        (rr + h * 0.5, -halb - wulst, "f"),
        (R - 0.024, -halb - wulst * 0.4, "sr"),
        (R - 0.007, -halb + 0.012, "sr"),
    ]
    tw = halb - 0.026
    ys = [(-tw, None)]
    for rl in sorted(rillen):
        yg = rl * b
        ys += [(yg - rb / 2, None), (yg - rb * 0.3, "r"), (yg + rb * 0.3, "r"), (yg + rb / 2, None)]
    ys.append((tw, None))
    # Rippen mit mehr als 5 cm Breite bekommen einen Punkt in der Mitte (Wölbung)
    voll = []
    for (ya, ka), (yb, kb) in zip(ys, ys[1:]):
        voll.append((ya, ka))
        if ka is None and kb is None and yb - ya > 0.05:
            voll.append(((ya + yb) / 2, None))
    voll.append(ys[-1])
    grenze = max([abs(rl * b) for rl in rillen], default=halb * 0.55) - 1e-6
    lauf = []
    for y, k in voll:
        rc = R - 0.004 * (y / halb) ** 2
        if k == "r":
            lauf.append((rc - tiefe, y, "r"))
        else:
            lauf.append((rc, y, "s" if abs(y) >= grenze else "m"))
    profil = flanke + lauf + [(r_, -y, k) for r_, y, k in reversed(flanke)]
    bloecke = tp.get("bloecke", 22)
    anteile = [(0.0, False), (0.7, False), (0.74, True), (0.96, True)]
    pfeil = tp.get("pfeil", 0.35)            # Versatz der Querrillen, Anteil eines Blocks
    teilung = 2 * math.pi / bloecke
    punkte = []
    for k in range(bloecke):
        for f, rille in anteile:
            for r_, y, art_p in profil:
                rad = r_
                if rille and art != "slick":
                    if art_p == "s" or (art_p == "m" and art == "strasse"):
                        rad -= tiefe
                    elif art_p == "sr":
                        rad -= tiefe * 0.6
                versatz = pfeil * teilung * (abs(y) / halb) if art_p != "f" else 0.0
                w = teilung * (k + f) + versatz
                punkte.append((rad * math.cos(w), y, rad * math.sin(w)))
    n = len(profil)
    m = bloecke * len(anteile)
    flaechen = []
    for s in range(m):
        s2 = (s + 1) % m
        for i in range(n):
            i2 = (i + 1) % n
            flaechen.append((s * n + i, s * n + i2, s2 * n + i2, s2 * n + i))
    ob = g.objekt_aus_daten(name, punkte, flaechen, [mats["gummi"]])
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    g.glatt(ob, 48)
    return ob


# ---------------------------------------------------------------------------
# Felge
# ---------------------------------------------------------------------------

def _loft(bm, ringe, mat_index: int = 0):
    """Geschlossene Ringe zu einem Körper mit Deckeln verbinden (in ``bm``)."""
    vs = [[bm.verts.new(p) for p in r] for r in ringe]
    n = len(ringe[0])
    for a, c in zip(vs, vs[1:]):
        for j in range(n):
            f = bm.faces.new((a[j], a[(j + 1) % n], c[(j + 1) % n], c[j]))
            f.material_index = mat_index
    for f in (bm.faces.new(list(reversed(vs[0]))), bm.faces.new(vs[-1])):
        f.material_index = mat_index


class Speichenform:
    """Wo Vorder- und Rückseite der Speichen liegen, je Radius."""

    def __init__(self, r0, r1, y_nabe, y_rand, tiefe):
        self.r0, self.r1 = r0, r1
        self.y_nabe, self.y_rand = y_nabe, y_rand
        self.tiefe = tiefe

    def vorn(self, r):
        tt = max(0.0, min(1.0, (r - self.r0) / (self.r1 - self.r0)))
        return self.y_nabe + (self.y_rand - 0.004 - self.y_nabe) * tt ** 0.8

    def hinten(self, r):
        tt = max(0.0, min(1.0, (r - self.r0) / (self.r1 - self.r0)))
        return self.vorn(r) - self.tiefe * (1 - 0.3 * tt)


def speichenform(p: dict, tp: dict, rr: float, b: float) -> Speichenform:
    """Lage der Speichen aus den Fahrzeugparametern (auch für den Sattel)."""
    halb = b / 2
    y_nabe = halb - (0.11 if p.get("felge") == "tiefbett" else p.get("felgentiefe_m", 0.06))
    return Speichenform(0.075, rr - 0.03, y_nabe, halb - 0.024, tp.get("speiche_tiefe_m", 0.03))


def felge(p: dict, tp: dict, mats, rr: float, b: float, emblem_bauen=None):
    """Felge: Felgenbett mit Horn, Speichen mit gefastem Querschnitt, Nabe,
    Radmuttern und Nabenkappe. Liefert (Teile, Speichenform)."""
    halb = b / 2
    fm = mats["felge"]
    design = p.get("felge", "fuenf")
    teile = []
    form = speichenform(p, tp, rr, b)
    y_rand, y_nabe = form.y_rand, form.y_nabe
    rbett = rr - 0.022
    # Felgenbett und Horn als ein Drehkörper (geschlossener Umriss).
    profil = [
        (rbett, -halb + 0.02), (rbett, y_rand - 0.03), (rr - 0.034, y_rand - 0.006),
        (rr - 0.012, y_rand + 0.001), (rr + 0.006, y_rand + 0.003), (rr + 0.009, y_rand - 0.006),
        (rr + 0.001, y_rand - 0.013), (rr + 0.001, -halb + 0.013), (rr + 0.006, -halb + 0.005),
        (rbett + 0.004, -halb + 0.005),
    ]
    teile.append(t.drehkoerper("felgenbett", profil, [mats["bremse"], fm], segmente=56,
                               abschnitt_mat=[0, 1, 1, 1, 1, 1, 1, 1, 1, 0], ring=True))
    if design in MUSTER:
        muster, anzahl = MUSTER[design]
        bm = bmesh.new()
        for i in range(anzahl):
            for versatz, b0, b1 in muster:
                w0 = 2 * math.pi * i / anzahl + math.radians(versatz)
                r_a = form.r0 if not (versatz and design == "y") else rr * 0.55
                ringe = []
                for k in range(5):
                    tt = k / 4
                    r_ = r_a + (form.r1 + 0.004 - r_a) * tt
                    bw = b0 + (b1 - b0) * tt
                    yf, yb = form.vorn(r_), form.hinten(r_)
                    quer = [(-bw / 2, yb), (bw / 2, yb), (bw / 2, yf - 0.008), (bw * 0.3, yf),
                            (-bw * 0.3, yf), (-bw / 2, yf - 0.008)]
                    c, s = math.cos(w0), math.sin(w0)
                    ringe.append([(r_ * c - q * s, y, r_ * s + q * c) for q, y in quer])
                _loft(bm, ringe)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        speichen = g.objekt_aus(bm, "speichen", [fm])
        g.glatt(speichen, 35)
        teile.append(speichen)
    # Nabe: leicht gewölbte Scheibe
    nabe_profil = [(0.0, y_nabe + 0.028), (0.05, y_nabe + 0.026), (0.088, y_nabe + 0.016),
                   (0.092, y_nabe + 0.004), (0.092, y_nabe - 0.016), (0.0, y_nabe - 0.016)]
    teile.append(t.drehkoerper("nabe", nabe_profil, [fm], segmente=40))
    n_mutter = tp.get("radmuttern", 5)
    mm = mats[tp.get("mutter_mat", "chrom")]
    if design == "zentral":
        teile.append(t.zylinder_y("zentralmutter", (0, y_nabe + 0.045, 0), 0.045, 0.04,
                                  mats["sattel"], segmente=6))
    else:
        for i in range(n_mutter):
            w = 2 * math.pi * i / n_mutter + math.pi / n_mutter
            x, z = 0.058 * math.cos(w), 0.058 * math.sin(w)
            mutter = t.drehkoerper("mutter", [(0.0, y_nabe + 0.046), (0.006, y_nabe + 0.046),
                                              (0.0115, y_nabe + 0.04), (0.0115, y_nabe + 0.022),
                                              (0.0, y_nabe + 0.022)], [mm], segmente=6, glatt=False)
            mutter.data.transform(Matrix.Translation((x, 0, z)))
            teile.append(mutter)
        kappe = t.drehkoerper("nabenkappe", [(0.0, y_nabe + 0.041), (0.024, y_nabe + 0.039),
                                             (0.033, y_nabe + 0.033), (0.034, y_nabe + 0.024),
                                             (0.0, y_nabe + 0.024)], [mats["kunststoff"]], segmente=32)
        teile.append(kappe)
        if tp.get("nabenkappe", "emblem") == "emblem" and emblem_bauen is not None:
            em = emblem_bauen(0.042)
            if em is not None:
                em.data.transform(Matrix.Rotation(math.radians(90), 4, "Z"))
                em.data.transform(Matrix.Translation((0, y_nabe + 0.041, 0)))
                teile.append(em)
    return teile, form


# ---------------------------------------------------------------------------
# Bremse
# ---------------------------------------------------------------------------

def bremsscheibe(rr: float, form: Speichenform, tp_bremse: dict, mats):
    """Innenbelüftete Scheibe mit Topf; gelocht oder geschlitzt als dunkle
    Einlagen auf der Außenseite. Dreht mit dem Rad."""
    art = tp_bremse.get("art", "gelocht")
    r_o = rr - tp_bremse.get("abstand_m", 0.055)
    r_i = r_o * 0.56
    y0, y1 = -0.034, -0.006
    y_topf = form.y_nabe - 0.016
    profil = [
        (r_i, y0), (r_o - 0.003, y0), (r_o, y0 + 0.003), (r_o, y1 - 0.003), (r_o - 0.003, y1),
        (r_i, y1), (r_i - 0.008, y1), (r_i - 0.012, y_topf), (0.1, y_topf), (0.1, y_topf - 0.005),
        (r_i - 0.018, y_topf - 0.005), (r_i - 0.014, y0),
    ]
    topf = 1
    scheibe = t.drehkoerper("bremsscheibe", profil,
                            [mats["bremse"], mats[tp_bremse.get("topf_mat", "kunststoff")]],
                            segmente=48, abschnitt_mat=[0, 0, 0, 0, 0, topf, topf, topf, topf, topf, topf, 0],
                            ring=True)
    g.glatt(scheibe, 40)
    teile = [scheibe]
    if art in ("gelocht", "geschlitzt"):
        bm = bmesh.new()
        ya = y1 + 0.0005
        if art == "gelocht":
            n = 18
            for reihe, anteil in enumerate((0.3, 0.52, 0.74)):
                rc = r_i + (r_o - r_i) * anteil
                for k in range(n):
                    w = 2 * math.pi * (k + reihe / 3) / n
                    cx, cz = rc * math.cos(w), rc * math.sin(w)
                    vs = [bm.verts.new((cx + 0.0045 * math.cos(2 * math.pi * j / 6), ya,
                                        cz + 0.0045 * math.sin(2 * math.pi * j / 6))) for j in range(6)]
                    bm.faces.new(vs)
        else:
            n = 12
            for k in range(n):
                w0 = 2 * math.pi * k / n
                links, rechts = [], []
                for j in range(4):
                    tt = j / 3
                    r_ = r_i + 0.012 + (r_o - r_i - 0.024) * tt
                    w = w0 + 0.28 * tt
                    c, s = math.cos(w), math.sin(w)
                    links.append(bm.verts.new(((r_) * c - 0.002 * s, ya, (r_) * s + 0.002 * c)))
                    rechts.append(bm.verts.new(((r_) * c + 0.002 * s, ya, (r_) * s - 0.002 * c)))
                for j in range(3):
                    bm.faces.new((links[j], links[j + 1], rechts[j + 1], rechts[j]))
        for f in bm.faces:
            f.normal_update()
            if f.normal.y < 0:
                f.normal_flip()
        teile.append(g.objekt_aus(bm, "bohrungen", [mats["kunststoff"]]))
    return teile


def sattel_y_frei(form: Speichenform, r_a: float, r_b: float) -> float:
    """Wie weit ein Sattel zwischen den Radien r_a und r_b nach außen reichen
    darf, ohne in die Speichen zu ragen."""
    return min(form.hinten(r_a + (r_b - r_a) * k / 8) for k in range(9)) - 0.007


def bremssattel(name, rr: float, form: Speichenform, tp_bremse: dict, tp_sattel: dict, mats):
    """Bremssattel als Bogen um den Scheibenrand; Radkoordinaten, lenkt mit,
    dreht nicht."""
    r_o = rr - tp_bremse.get("abstand_m", 0.055)
    r_in = r_o - 0.05
    r_aus = r_o + 0.015
    y_i = -0.058
    y_a = min(0.03, sattel_y_frei(form, r_in, r_aus))
    y_a = max(y_a, -0.004)
    mitte = math.radians(tp_sattel.get("winkel_grad", 140))
    spanne = math.radians(tp_sattel.get("spanne_grad", 56))
    quer = [(r_in, y_i + 0.008), (r_in + 0.008, y_i), (r_aus - 0.01, y_i), (r_aus, y_i + 0.01),
            (r_aus, y_a - 0.01), (r_aus - 0.01, y_a), (r_in + 0.008, y_a), (r_in, y_a - 0.008)]
    rm = (r_in + r_aus) / 2
    ym = (y_i + y_a) / 2
    stationen = [(-0.5 - 0.06, 0.8), (-0.5, 0.96)] + [(-0.5 + k / 8, 1.0) for k in range(1, 8)] + \
                [(0.5, 0.96), (0.5 + 0.06, 0.8)]
    ringe = []
    for tt, f in stationen:
        w = mitte + spanne * tt
        c, s = math.cos(w), math.sin(w)
        ring = []
        for r_, y in quer:
            r2 = rm + (r_ - rm) * f
            y2 = ym + (y - ym) * f
            ring.append((r2 * c, y2, r2 * s))
        ringe.append(ring)
    bm = bmesh.new()
    _loft(bm, ringe)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = g.objekt_aus(bm, name, [mats["sattel"]])
    g.glatt(ob, 40)
    # Ein Material je Sattel: ein Zeichenaufruf mehr je Rad wäre bei acht
    # Autos 32 Aufrufe je Bild.
    return ob
