"""Teile-Bibliothek: Innenraum, Kennzeichen und erfundene Embleme.

Läuft in Blender. Parameter: siehe Kopf von ``teile.py`` (``teile.innenraum``,
``teile.kennzeichen``, ``teile.emblem``).

**Embleme** sind frei erfunden und geometrisch einfach, eines je
Fahrzeugfamilie. Sie ersetzen die Markenlogos der Sprites; kein Emblem darf
einem echten Markenzeichen nachgebildet werden, und nirgends steht ein Name.
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix

import gemeinsam as g
import teile as t

#: Emblemform je Fahrzeugfamilie (Schlüssel vor dem ersten ``_``).
FAMILIENFORM = {"rookie": "sechseck", "limousine": "oval", "supercar": "delta",
                "drifter": "spuren", "electric": "ein"}


# ---------------------------------------------------------------------------
# Embleme
# ---------------------------------------------------------------------------

def _kreis(r, n, rz=None, w0=0.0, w1=None):
    rz = r if rz is None else rz
    if w1 is None:
        return [(r * math.cos(w0 + 2 * math.pi * k / n), rz * math.sin(w0 + 2 * math.pi * k / n))
                for k in range(n)]
    return [(r * math.cos(w0 + (w1 - w0) * k / (n - 1)), rz * math.sin(w0 + (w1 - w0) * k / (n - 1)))
            for k in range(n)]


def _balken(laenge, breite, winkel_grad=0.0, mitte=(0.0, 0.0)):
    w = math.radians(winkel_grad)
    c, s = math.cos(w), math.sin(w)
    pts = [(-laenge / 2, -breite / 2), (laenge / 2, -breite / 2), (laenge / 2, breite / 2), (-laenge / 2, breite / 2)]
    return [(mitte[0] + a * c - b * s, mitte[1] + a * s + b * c) for a, b in pts]


def emblem(form: str, groesse: float, mats, sockel: bool = True):
    """Emblem in der YZ-Ebene, Vorderseite +X, Mitte im Ursprung.

    Formen: ``sechseck`` (Sechseckring mit Punkt), ``oval`` (Ovalring mit drei
    gestuften Balken), ``delta`` (Dreieckring mit Querbalken), ``spuren``
    (Kreisring mit zwei schrägen Streifen), ``ein`` (offener Ring mit Strich).
    """
    R = groesse / 2
    d = max(0.0015, groesse * 0.04)
    chrom = mats["chrom"]
    teile = []
    x = d / 2 + 0.0008

    def ring(aussen, innen):
        teile.append(t.streifen_extrudieren("emblem", aussen, innen, d, chrom, mitte=x))

    def flaeche(umriss):
        teile.append(t.umriss_extrudieren("emblem", umriss, d, chrom, ebene="yz", mitte=x))

    if form == "sechseck":
        ring(_kreis(R, 6, w0=math.pi / 6), _kreis(R * 0.76, 6, w0=math.pi / 6))
        flaeche(_kreis(R * 0.28, 6, w0=math.pi / 6))
    elif form == "oval":
        ring(_kreis(R, 28, R * 0.64), _kreis(R * 0.82, 28, R * 0.47))
        for k, lg in enumerate((1.2, 0.95, 0.7)):
            flaeche(_balken(R * lg, R * 0.09, mitte=(0.0, R * (0.2 - 0.2 * k))))
    elif form == "delta":
        ring(_kreis(R, 3, w0=math.pi / 2), _kreis(R * 0.6, 3, w0=math.pi / 2))
        flaeche(_balken(R * 0.78, R * 0.09, mitte=(0.0, -R * 0.1)))
    elif form == "spuren":
        ring(_kreis(R, 28), _kreis(R * 0.8, 28))
        for off in (-0.2, 0.2):
            flaeche(_balken(R * 1.05, R * 0.13, 55.0, mitte=(R * off, 0.0)))
    else:  # "ein"
        w0, w1 = math.radians(120), math.radians(420)
        teile.append(t.streifen_extrudieren("emblem", _kreis(R, 22, w0=w0, w1=w1),
                                            _kreis(R * 0.78, 22, w0=w0, w1=w1), d, chrom,
                                            geschlossen=False, mitte=x))
        flaeche(_balken(R * 0.14, R * 0.9, mitte=(0.0, R * 0.5)))
    if sockel:
        rund = {"sechseck": 2.2, "delta": 2.2}.get(form, 2.0)
        sk = t.platte("emblemsockel", groesse * (1.12 if form != "oval" else 1.1),
                      groesse * (1.12 if form != "oval" else 0.76), d,
                      (mats["zierteil"], mats["zierteil"]), rundung=rund, punkte=24)
        teile.append(sk)
    return g.verbinden(teile, "emblem")


def emblemform(key: str, te: dict) -> str:
    return te.get("form", FAMILIENFORM.get(key.split("_")[0], "sechseck"))


# ---------------------------------------------------------------------------
# Kennzeichen
# ---------------------------------------------------------------------------

#: Siebensegment-Zeichen: a oben, b oben rechts, c unten rechts, d unten,
#: e unten links, f oben links, g Mitte.
SEGMENTE = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg",
            "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg", "A": "abcefg",
            "C": "adef", "E": "adefg", "F": "aefg", "H": "bcefg", "L": "def", "P": "abefg",
            "U": "bcdef", "-": "g", " ": ""}


def kennzeichen(text: str, mats, breite: float = 0.52, hoehe: float = 0.115):
    """Schild mit Rahmen und erfundener Aufschrift in Siebensegmentzeichen,
    Vorderseite +X."""
    teile = [t.platte("kennzeichen", breite, hoehe, 0.01, (mats["kennzeichen"], mats["kunststoff"]),
                      rundung=10)]
    rand = 0.008
    aussen = [(y * (breite / 2 + rand) / (breite / 2), z * (hoehe / 2 + rand) / (hoehe / 2))
              for y, z in _superellipse(breite / 2, hoehe / 2, 10, 32)]
    innen = _superellipse(breite / 2 - 0.002, hoehe / 2 - 0.002, 10, 32)
    teile.append(t.streifen_extrudieren("kennzeichenrahmen", aussen, innen, 0.016, mats["kunststoff"],
                                        mitte=0.002))
    zh, zb, st = hoehe * 0.62, hoehe * 0.34, hoehe * 0.075
    schritt = zb + hoehe * 0.16
    text = text.upper()
    gesamt = len(text) * schritt - (schritt - zb)
    for i, zeichen in enumerate(text):
        # Blick auf die Vorderseite (von +X her): links im Bild liegt -Y.
        yc = -gesamt / 2 + i * schritt + zb / 2
        for s in SEGMENTE.get(zeichen, ""):
            umr = _segment(s, yc, zb, zh, st)
            teile.append(t.umriss_extrudieren("schrift", umr, 0.0012, mats["schrift"], ebene="yz",
                                              mitte=0.0056))
    return g.verbinden(teile, "kennzeichen")


def _superellipse(a, b, rundung, n):
    return [(t.sp(math.cos(2 * math.pi * k / n), 2.0 / rundung) * a,
             t.sp(math.sin(2 * math.pi * k / n), 2.0 / rundung) * b) for k in range(n)]


def _segment(s, yc, zb, zh, st):
    """Umriss eines Segments; Blick von +X her, links im Bild = -Y."""
    l, r = yc - zb / 2, yc + zb / 2          # linke und rechte Kante
    o, m, u = zh / 2, 0.0, -zh / 2
    h = st / 2
    if s == "a":
        return [(l, o), (r, o), (r, o - st), (l, o - st)]
    if s == "d":
        return [(l, u + st), (r, u + st), (r, u), (l, u)]
    if s == "g":
        return [(l, m + h), (r, m + h), (r, m - h), (l, m - h)]
    if s == "b":
        return [(r - st, o), (r, o), (r, m), (r - st, m)]
    if s == "c":
        return [(r - st, m), (r, m), (r, u), (r - st, u)]
    if s == "f":
        return [(l, o), (l + st, o), (l + st, m), (l, m)]
    return [(l, m), (l + st, m), (l + st, u), (l, u)]      # e


def kennzeichen_text(key: str) -> str:
    """Erfundene, feste Aufschrift je Fahrzeug."""
    h = sum((i + 7) * ord(c) for i, c in enumerate(key))
    buchstaben = ["AC", "EF", "HU", "LE", "CA", "FE", "UL", "AE", "HA", "LU"]
    return f"{buchstaben[h % len(buchstaben)]} {100 + h % 900}"


# ---------------------------------------------------------------------------
# Innenraum
# ---------------------------------------------------------------------------

def _gruppe(teile, name, drehung_y: float, ort):
    ob = g.verbinden(teile, name)
    ob.data.transform(Matrix.Rotation(drehung_y, 4, "Y"))
    ob.data.transform(Matrix.Translation(ort))
    return ob


def sitz(art: str, lehne_h: float, mats, akzent):
    """Ein Sitz, Ursprung vorn mittig unter der Sitzfläche, Blick nach +X."""
    im = mats["innenraum"]
    teile = [t.kasten("sitz", (-0.24, 0, 0.05), (0.48, 0.44, 0.1), im, fase=0.035)]
    if art == "schale":
        for s in (1, -1):
            teile.append(t.kasten("wange", (-0.22, s * 0.2, 0.1), (0.44, 0.07, 0.08), im, fase=0.03))
        teile.append(t.kasten("sitzmitte", (-0.24, 0, 0.102), (0.4, 0.2, 0.012), akzent, fase=0.004))
    # Lehne: in eigenen Koordinaten aufgebaut, dann nach hinten geneigt.
    lehne = [t.kasten("lehne", (0, 0, lehne_h / 2), (0.1, 0.44, lehne_h), im, fase=0.04)]
    if art == "schale":
        for s in (1, -1):
            lehne.append(t.kasten("lehnenwange", (0.05, s * 0.2, lehne_h * 0.4), (0.12, 0.07, lehne_h * 0.72),
                                  im, fase=0.03))
        lehne.append(t.kasten("lehnenmitte", (0.052, 0, lehne_h * 0.45), (0.01, 0.2, lehne_h * 0.6),
                              akzent, fase=0.003))
        lehne.append(t.kasten("kopfteil", (0, 0, lehne_h + 0.1), (0.09, 0.26, 0.2), im, fase=0.04))
    else:
        lehne.append(t.kasten("kopfstuetze", (0.01, 0, lehne_h + 0.1), (0.09, 0.26, 0.14), im, fase=0.035))
        for s in (1, -1):
            lehne.append(t.zylinder_x("stange", (0, s * 0.07, lehne_h + 0.02), 0.006, 0.01,
                                      mats["chrom"], segmente=6))
    teile.append(_gruppe(lehne, "lehne", math.radians(-14), (-0.46, 0, 0.08)))
    return g.verbinden(teile, "sitz")


def lenkrad(mats):
    """Lenkrad mit drei Speichen, Prall­topf und Säule; Ursprung in der
    Radmitte, Radebene um 25° nach vorn geneigt, Säule nach vorn unten."""
    im = mats["innenraum"]
    bpy.ops.mesh.primitive_torus_add(major_radius=0.175, minor_radius=0.017,
                                     major_segments=28, minor_segments=8)
    kranz = bpy.context.object
    kranz.data.materials.append(im)
    for p in kranz.data.polygons:
        p.use_smooth = True
    teile = [kranz]
    # lokale Ebene XY; +X zeigt später zum unteren Rand, ±Y quer
    teile.append(t.kasten("speiche", (0, 0.09, 0), (0.035, 0.17, 0.012), im, fase=0.005))
    teile.append(t.kasten("speiche", (0, -0.09, 0), (0.035, 0.17, 0.012), im, fase=0.005))
    teile.append(t.kasten("speiche", (0.09, 0, 0), (0.17, 0.03, 0.012), im, fase=0.005))
    teile.append(t.kasten("pralltopf", (0.01, 0, 0.012), (0.1, 0.11, 0.04), mats["zierteil"], fase=0.02))
    saeule = t.zylinder_y("lenksaeule", (0, 0, 0), 0.03, 0.26, im, segmente=10)
    saeule.data.transform(Matrix.Rotation(math.radians(-90), 4, "X"))
    saeule.data.transform(Matrix.Translation((0, 0, 0.14)))
    teile.append(saeule)
    ob = g.verbinden(teile, "lenkrad")
    ob.data.transform(Matrix.Rotation(math.radians(115), 4, "Y"))
    return ob


def innenraum(fo, p, ti: dict, mats):
    """Wanne, Sitze mit Wangen, Armaturenbrett mit Hutze und Bildschirm,
    Mittelkonsole, Lenkrad — so viel, wie hinter getöntem Glas wirkt."""
    ms = fo.ms
    k = p["kabine"]
    art = ti.get("sitz", "schale" if k.get("sitzreihen", 2) == 1 else "komfort")
    akzent = mats[ti.get("akzent_mat", "carbon" if art == "schale" else "innenraum")]
    im = mats["innenraum"]
    teile = []
    us = [fo.dach_u0 + (fo.dach_u1 - fo.dach_u0) * i / 200 for i in range(201)]
    frei = [u for u in us if fo.G(u, 0) > fo.T(u, 0) + 0.05]
    if not frei:
        return teile
    u_hinten, u_vorn = min(frei), max(frei)
    motor = (p.get("teile") or {}).get("motor")
    if motor:
        # Der Innenraum beginnt vor dem Motorraum (Mittelmotor unter Glas).
        u_hinten = max(u_hinten, motor["u"][1] + 0.005)
    n = 30
    punkte, flaechen = [], []
    for i in range(n + 1):
        u = u_hinten + (u_vorn - u_hinten) * i / n
        z = fo.zd(u) - 0.02
        w_i = fo.ws(u) - 0.03
        punkte += [(ms.x(u), w_i, z), (ms.x(u), -w_i, z)]
        if i:
            a = 2 * (i - 1)
            flaechen.append((a, a + 1, a + 3, a + 2))
    teile.append(g.objekt_aus_daten("wanne", punkte, flaechen, [im]))

    def armaturbreite(u):
        return min(fo.ws(u) - 0.06, fo.wg(u) - 0.1)

    u_armatur = u_vorn
    while u_armatur > u_hinten:
        w_a = armaturbreite(u_armatur)
        luft = min(fo.oben(u_armatur, 0), fo.oben(u_armatur, 0.7 * w_a)) - fo.zd(u_armatur)
        if luft > 0.16:
            break
        u_armatur -= 0.002
    if u_armatur <= u_hinten + 0.5 / ms.laenge:
        u_armatur = u_vorn - 0.3 / ms.laenge
    x_a = ms.x(u_armatur)
    z_a = fo.zd(u_armatur)
    w_a = armaturbreite(u_armatur)
    # Armaturenbrett: Körper, gepolsterte Oberkante, Instrumentenhutze, Bildschirm, Düsen
    teile.append(t.kasten("armatur", (x_a - 0.2, 0, z_a + 0.02), (0.4, w_a * 2, 0.14), im, fase=0.04))
    teile.append(t.kasten("armaturleiste", (x_a - 0.4, 0, z_a + 0.03), (0.03, w_a * 2 - 0.08, 0.035),
                          akzent, fase=0.01))
    teile.append(t.kasten("hutze", (x_a - 0.34, w_a * 0.45, z_a + 0.12), (0.16, 0.3, 0.07), im, fase=0.03))
    teile.append(t.kasten("instrumente", (x_a - 0.415, w_a * 0.45, z_a + 0.1), (0.006, 0.24, 0.06),
                          mats["zierteil"], fase=0.002))
    teile.append(t.kasten("bildschirm", (x_a - 0.4, 0, z_a + 0.13), (0.012, 0.24, 0.13),
                          mats["zierteil"], fase=0.004, drehung=(0, math.radians(-12), 0)))
    for y in (-w_a * 0.75, w_a * 0.75, -0.16, 0.16):
        teile.append(t.kasten("duese", (x_a - 0.405, y, z_a + 0.06), (0.01, 0.08, 0.035),
                              mats["kunststoff"], fase=0.003))
    # Mittelkonsole mit Wählhebel
    x_sitz = x_a - 0.8
    laenge = max(0.3, x_a - 0.3 - (x_sitz - 0.45))
    teile.append(t.kasten("konsole", (x_a - 0.3 - laenge / 2, 0, fo.zd(ms.u(x_a - 0.5)) + 0.07),
                          (laenge, 0.2, 0.16), im, fase=0.03))
    teile.append(t.kasten("konsolenblende", (x_a - 0.3 - laenge / 2, 0, fo.zd(ms.u(x_a - 0.5)) + 0.151),
                          (laenge * 0.8, 0.14, 0.006), akzent, fase=0.002))
    teile.append(t.kugel("waehlhebel", (x_a - 0.55, 0, fo.zd(ms.u(x_a - 0.55)) + 0.2), (0.04, 0.035, 0.05),
                         mats["zierteil"], segmente=10, ringe=6))
    # Sitze
    reihen = k.get("sitzreihen", 2)
    for r in range(reihen):
        xs = x_a - 0.56 - r * 0.85
        u_s = ms.u(xs - 0.24)
        if u_s - 0.35 / ms.laenge < u_hinten + 0.02:
            break
        z_s = fo.zd(u_s) - 0.02
        w_s = min(fo.ws(u_s) - 0.08, fo.wg(u_s) - 0.05)
        dach = min(fo.oben(u_s - 0.35 / ms.laenge, w_s * 0.75), fo.oben(u_s, w_s * 0.75))
        platz = dach - z_s - 0.1
        lehne_h = min(0.56, platz - 0.24 if art == "schale" else platz - 0.2)
        if lehne_h < 0.22:
            break
        for seite in (1, -1):
            s = sitz(art if r == 0 else "komfort", lehne_h, mats, akzent)
            s.data.transform(Matrix.Translation((xs, seite * w_s * 0.5, z_s)))
            teile.append(s)
    lr = lenkrad(mats)
    lr.data.transform(Matrix.Translation((x_a - 0.46, w_a * 0.45, z_a + 0.13)))
    teile.append(lr)
    return teile


def verkleidung(karosserie, fo, erlaubt: set, innen_index: int, dicke: float = 0.012):
    """Dachhimmel und Säulenverkleidung: die Haut des Glashauses (ohne Glas)
    um ``dicke`` nach innen versetzt, umgedreht, in ``innenraum``.

    Ohne sie ist die Karosserie von innen hohl: durch die Seitenscheibe sieht
    man die lackierte Rückseite der gegenüberliegenden C-Säule und durch die
    Heckscheibe hinaus, und die Scheibe wirkt schräg geteilt. ``erlaubt``:
    Materialplätze der Haut, die verkleidet werden (Lack, Säulen, Rahmen).
    """
    bm = bmesh.new()
    bm.from_mesh(karosserie.data)
    weg = []
    for f in bm.faces:
        c = f.calc_center_median()
        if f.material_index not in erlaubt or not fo.im_glashaus(c.x, c.y, c.z, rand=0.02):
            weg.append(f)
    bmesh.ops.delete(bm, geom=weg, context="FACES")
    if not bm.faces:
        bm.free()
        return None
    bm.normal_update()
    versatz = [v.normal.copy() * dicke for v in bm.verts]
    for v, d in zip(bm.verts, versatz):
        v.co -= d
    bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
    for f in bm.faces:
        f.material_index = innen_index
    ob = g.objekt_aus(bm, "verkleidung", list(karosserie.data.materials))
    for pol in ob.data.polygons:
        pol.use_smooth = True
    return ob

