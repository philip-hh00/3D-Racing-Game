"""Teile-Bibliothek für ``fahrzeug_bauen.py``: Grundformen und Karosserie-Anbauteile.

Läuft **in Blender**. Jede Funktion baut ein Teil als Blender-Objekt in
Fahrzeugkoordinaten (+X vorn, +Y links, +Z oben, Meter, siehe
``src/render3d/VEREINBARUNGEN.md``). Räder, Bremsen und Reifen stehen in
``teile_rad.py``, Innenraum, Kennzeichen und Embleme in ``teile_innen.py``.

Eingeschaltet wird die Bibliothek je Fahrzeug mit einem Block ``"teile"`` in
``tools/blender/fahrzeuge/<key>.json``. Fehlt der Block, baut
``fahrzeug_bauen.py`` genau wie bisher. Ist er da, bekommt jedes Teil, das
darin nicht steht, seinen Standard; ``false`` schaltet ein Teil ab. Lage und
Größe kommen weiter aus den alten Schlüsseln (``spiegel``, ``tuergriffe_u``,
``auspuff``, ``kennzeichen``, ``spoiler`` …), der Block sagt nur, *wie* das
Teil aussieht.

Parameter (alle optional, Maße in Metern, Winkel in Grad)::

    "teile": {
      "reifen":   {"profil": "sport"|"strasse"|"slick", "bloecke": 22,
                   "rillen": [-0.2, 0.2] (Lage quer, Anteil der Breite),
                   "rille_m": 0.012, "tiefe_m": 0.007, "wulst_m": 0.007,
                   "pfeil": 0.35 (Pfeilung der Querrillen)},
      "felge":    {"radmuttern": 5, "mutter_mat": "chrom",
                   "nabenkappe": "emblem"|"glatt", "speiche_tiefe_m": 0.03},
      "bremse":   {"art": "gelocht"|"geschlitzt"|"glatt", "abstand_m": 0.055
                   (Scheibe bis Felgenbett), "topf_mat": "kunststoff"},
      "sattel":   {"winkel_grad": 140, "spanne_grad": 56},
                   Farbe weiter über "sattelfarbe"; Knoten sattel_* lenkt mit.
      "spiegel":  {"art": "stiel"|"fuss", "kappe_mat": "lack", "fuss_mat": "zierteil",
                   "schlank": 0.62, "flach": 0.8 (Tiefe/Höhe gegenüber spiegel.groesse),
                   "pfeilung_m": 0.035 (Außenende nach hinten)},
      "tuergriff":{"art": "buegel"|"buendig", "laenge_m": 0.15},
      "wischer":  {"anzahl": 2, "laenge_m": [0.62, 0.5], "lagen_m": [0.06, -0.5]
                   (Drehpunkte quer), "heck": false, "heck_laenge_m": 0.36},
      "diffusor": {"finnen": 5, "laenge_m": 0.5, "winkel_grad": 11,
                   "breite_v": 0.72, "mat": "carbon"},
      "auspuff":  {"art": "rund"|"oval", "laenge_m": 0.16, "blende": true},
      "innenraum":{"sitz": "schale"|"komfort", "akzent_mat": "zierteil"},
      "kennzeichen": {"text": "AC 14"} (Ziffern und A C E F H L P U; Höhe
                   weiter über kennzeichen.vorn_m/hinten_m, dort auch
                   "vorn_vorsprung_m" für ein Schild vor dem Grill;
                   "neigung_grad": 0 = senkrecht, positiv oben nach hinten),
      "antenne":  {"u": 0.2, "laenge_m": 0.16, "hoehe_m": 0.06, "mat": "lack"}
                   (nur wenn angegeben),
      "motor":    {"u": [0.2, 0.333], "v": 0.3, "z_m": [0.45, 0.88],
                   "zylinder": 8, "deckel_mat": "carbon", "metall_mat": "bremse",
                   "ansaug_mat": "alu", "spulen_mat": "sattel"} (nur wenn
                   angegeben: V-Motor unter einer gläsernen Abdeckung, dazu
                   dunkle Wanne; der Innenraum beginnt davor),
      "emblem":   {"form": "sechseck"|"oval"|"delta"|"spuren"|"ein"
                   (Standard je Familie rookie/limousine/supercar/drifter/electric),
                   "groesse_m": 0.07,
                   "orte": [{"ansicht": "oben", "u": 0.95, "v": 0} |
                            {"ansicht": "vorn"|"hinten", "z_m": 0.6, "v": 0}]},
      "fugen":    [{"ansicht": "seite"|"oben"|"vorn"|"hinten",
                    "punkte": [[a, b], ...], "breite_m": 0.005, "tiefe_m": 0.005,
                    "geschlossen": false, "spiegeln": false, "symmetrisch": false,
                    "n_min": ..., "auf": ["lack", "lack2"], "und": [...]}]
    }

In **Zonen** (``zonen``-Liste der Fahrzeugdatei)::

    "leuchte": {"tiefe_m": 0.03 (Gehäusetiefe), "rand_m": 0.005,
                (``mat`` der Zone ist der Gehäuseboden, dunkel: "kunststoff";
                hinter einer Streuscheibe ist der Boden der rote Reflektor
                "rueckstrahler", anders mit "boden_mat"),
                "rand_mat": "zierteil",
                "abdeckung": "klarglas"|"streuscheibe"|null,
                "led": {"verlauf": "rand"|"oben"|"unten"|"vorn"|"hinten"|"aussen"|"innen"
                        (folgt dem 3D-Rand der ganzen Leuchte, auch über ``oder``),
                        "abstand_m": 0.008, "breite_m": 0.007, "hoehe_m": 0.004,
                        (die Leiste sinkt entlang der Leuchtennormale genau so
                        tief wie der Gehäuseboden, auch am schmalen Ende),
                        "ringe": [0.8, 0.45] (statt verlauf: verkleinerte Umrisse),
                        "quer": [0.35, 0.7] (statt verlauf: Streifen quer),
                        "mat": "licht_vorn"} — auch als Liste mehrerer Leisten,
                "projektoren": {"anzahl": 2, "radius_m": 0.028, "lage": 0.5
                                (Anteil quer im Umriss; bei ``spiegeln`` für beide
                                Seiten von außen gleich weit),
                                "rand_anteil": 0.22, "art": "projektor"|"reflektor",
                                "vorhalt": 0.7 (Neigung zur Fahrtrichtung),
                                "ansicht": Umriss welcher Teilfläche (Standard: der Zone)}}
    "oder":    [{"ansicht": "vorn", "punkte": [[v, z], ...], "u": [0.9, 1.2],
                 "n_min": 0.1, ...}] — weitere Umrisse derselben Zone (eigene
                Ansicht, ``n_min``, ``u``, ``z``, ``und``). So läuft eine
                Leuchte vom Kotflügel (Umriss aus dem Sprite, Ansicht ``oben``)
                über die Kante in die Front: oben bleibt es wie im Sprite, von
                vorn ist es kein Schlitz mehr. Beispiel: supercar.
    "gitter":  {"art": "waben"|"raute"|"lamellen", "masche_m": 0.032,
                "steg_m": 0.006, "hoehe_m": 0.012, "rand_m": 0.01,
                "winkel_grad": 0 (Lamellen: Neigung), "richtung": "a"|"b"
                (Lamellen entlang der ersten/zweiten Bildachse), "mat": "zierteil"}

**LOD1** (``<key>_lod1.glb``) baut ``fahrzeug_bauen.lod1_parameter`` aus
denselben Parametern: keine Gitter, Projektoren, Fugen, Wischer, Embleme,
Schrift; glatte Reifen. Neue Schlüssel sollten dort mitgedacht werden.

Die Zone gibt Umriss und Lage (wie im Sprite), die Bibliothek setzt Gehäuse,
Einsätze und Abdeckung hinein. Ohne ``stufen`` bekommt eine Leuchte eine
Vertiefung von ``tiefe_m``.

Im Spoiler ``{"art": "fluegel", ...}`` schaltet ``"profil": "naca"`` den
Profilflügel ein: ``"woelbung"`` (0.06), ``"dicke"`` (0.12), ``"elemente"``
(1|2), ``"stuetzen": "schwanenhals"|"sockel"``, ``"endplatte_m"`` [unten,
oben] Überstand, dazu die alten ``u``, ``v``, ``tiefe_m``, ``hoehe_m``,
``anstellung_grad``, ``fuss_m``, ``stuetzen_v``, ``mat``, ``platten_mat``,
``stuetzen_mat``. ``"schrift": {"text": "DRIFT", "hoehe_m": 0.2, "lage": 0.5,
"oben": "hinten"|"vorn", "kursiv": 0.25, "fett": 0.0, "mat": "dekor_weiss",
"sehne_anteil": 0.42}`` legt einen Schriftzug auf die Oberseite des Blatts
(nicht in LOD1).

In ``kabine``: ``"fensterstege": [{"punkte": [[u, z], ...], "breite_m": 0.024,
"mat": "zierteil"}]`` teilen das Seitenfenster (etwa das feste Dreiecksfenster
hinter der Fondtür ab), ``"verkleidung": true`` baut Dachhimmel und
Säulenverkleidung, damit man durch die Scheiben nicht in eine hohle Karosserie
sieht. Die Enden des Lofts schließt ``"kappe_vorn"``/``"kappe_hinten"``:
``"tangential"`` ohne Knick an der Naht (Standard: flache Kuppel).
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

import gemeinsam as g

#: Achsen einer Ansicht: (erste Bildachse, zweite Bildachse, Blickachse).
ACHSEN = {"oben": (0, 1, 2), "seite": (0, 2, 1), "vorn": (1, 2, 0), "hinten": (1, 2, 0)}


def sp(wert_: float, exponent: float) -> float:
    """Vorzeichenerhaltende Potenz für Superellipsen."""
    return math.copysign(abs(wert_) ** exponent, wert_)


# ---------------------------------------------------------------------------
# Grundformen
# ---------------------------------------------------------------------------

def kasten(name, mitte, groesse, mat, fase: float = 0.0, drehung=None, segmente: int = 2):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(groesse), verts=bm.verts)
    ob = g.objekt_aus(bm, name, [mat])
    if fase > 0:
        mod = ob.modifiers.new("fase", "BEVEL")
        mod.width = fase
        mod.segments = segmente
        mod.limit_method = "NONE"
        g.modifikator_anwenden(ob, mod)
    if drehung is not None:
        ob.rotation_euler = drehung
    ob.location = mitte
    g.transform_anwenden(ob)
    return ob


def kugel(name, mitte, groesse, mat, segmente: int = 20, ringe: int = 10, drehung=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segmente, v_segments=ringe, radius=0.5)
    bmesh.ops.scale(bm, vec=Vector(groesse), verts=bm.verts)
    ob = g.objekt_aus(bm, name, [mat])
    for p in ob.data.polygons:
        p.use_smooth = True
    if drehung is not None:
        ob.rotation_euler = drehung
    ob.location = mitte
    g.transform_anwenden(ob)
    return ob


def zylinder_y(name, mitte, radius, breite, mat, segmente: int = 32, kappen=True):
    """Zylinder mit Achse entlang Y."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=kappen, cap_tris=False, segments=segmente,
                          radius1=radius, radius2=radius, depth=breite)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                     matrix=Matrix.Rotation(math.radians(90), 3, "X"))
    ob = g.objekt_aus(bm, name, [mat])
    ob.location = mitte
    g.transform_anwenden(ob)
    return ob


def zylinder_x(name, mitte, radius, laenge, mat, segmente: int = 20):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=segmente,
                          radius1=radius, radius2=radius, depth=laenge)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                     matrix=Matrix.Rotation(math.radians(90), 3, "Y"))
    ob = g.objekt_aus(bm, name, [mat])
    ob.location = mitte
    g.transform_anwenden(ob)
    return ob


def platte(name, breite, hoehe, dicke, mats, rundung: float = 4.0, punkte: int = 24):
    """Eine Superellipsen-Platte in der YZ-Ebene, Vorderseite zeigt nach +X."""
    bm = bmesh.new()
    vorn, hinten = [], []
    for k in range(punkte):
        w = 2 * math.pi * k / punkte
        y = sp(math.cos(w), 2.0 / rundung) * breite / 2
        z = sp(math.sin(w), 2.0 / rundung) * hoehe / 2
        vorn.append(bm.verts.new((dicke / 2, y, z)))
        hinten.append(bm.verts.new((-dicke / 2, y, z)))
    f_vorn = bm.faces.new(vorn)
    f_hinten = bm.faces.new(list(reversed(hinten)))
    f_vorn.material_index = 0
    f_hinten.material_index = 1
    for k in range(punkte):
        f = bm.faces.new((vorn[k], hinten[k], hinten[(k + 1) % punkte], vorn[(k + 1) % punkte]))
        f.material_index = 1
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return g.objekt_aus(bm, name, list(mats))


def netz_aus_ringen(name, ringe, mat, geschlossen=True, kappen=False, schleife=False, glatt=True):
    """Loft aus Ringen gleicher Punktzahl.

    ``geschlossen``: jeder Ring ist ein geschlossener Querschnitt.
    ``schleife``: der letzte Ring schließt wieder an den ersten an.
    """
    bm = bmesh.new()
    vs = [[bm.verts.new(p) for p in r] for r in ringe]
    n = len(ringe[0])
    m = len(vs)
    for i in range(m if schleife else m - 1):
        a, b = vs[i], vs[(i + 1) % m]
        for j in range(n if geschlossen else n - 1):
            bm.faces.new((a[j], a[(j + 1) % n], b[(j + 1) % n], b[j]))
    if kappen and not schleife:
        bm.faces.new(list(reversed(vs[0])))
        bm.faces.new(vs[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = g.objekt_aus(bm, name, [mat])
    for p in ob.data.polygons:
        p.use_smooth = glatt
    return ob


def drehkoerper(name, profil, mats, segmente: int = 32, abschnitt_mat=None, ring=False,
                glatt=True, drehung=None, versatz_grad: float = 0.0):
    """Drehkörper um Y aus einem Profil ``[(r, y), ...]``.

    Beginnt oder endet das Profil bei ``r = 0``, entsteht dort ein Pol.
    ``ring``: das Profil ist ein geschlossener Umriss. Geschlossene Körper
    bekommen ihre Normalen nach außen gerechnet; bei offenen gilt: läuft das
    Profil in +Y, zeigt die Normale nach außen (+r).
    ``abschnitt_mat``: Materialplatz je Profilabschnitt (Index in ``mats``).
    """
    bm = bmesh.new()
    pol_a = profil[0][0] < 1e-6
    pol_e = profil[-1][0] < 1e-6
    innen = profil[(1 if pol_a else 0):(len(profil) - 1 if pol_e else len(profil))]
    ringe = []
    for s in range(segmente):
        w = math.radians(versatz_grad) + 2 * math.pi * s / segmente
        c, si = math.cos(w), math.sin(w)
        ringe.append([bm.verts.new((r * c, y, r * si)) for r, y in innen])
    m = len(innen)
    off = 1 if pol_a else 0

    def mi(k):
        if not abschnitt_mat:
            return 0
        return abschnitt_mat[min(k, len(abschnitt_mat) - 1)]

    pa = bm.verts.new((0.0, profil[0][1], 0.0)) if pol_a else None
    pe = bm.verts.new((0.0, profil[-1][1], 0.0)) if pol_e else None
    for s in range(segmente):
        a, b = ringe[s], ringe[(s + 1) % segmente]
        for i in range(m - 1):
            f = bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
            f.material_index = mi(i + off)
        if ring:
            f = bm.faces.new((a[m - 1], a[0], b[0], b[m - 1]))
            f.material_index = mi(m - 1 + off)
        if pa is not None:
            f = bm.faces.new((pa, a[0], b[0]))
            f.material_index = mi(0)
        if pe is not None:
            f = bm.faces.new((a[m - 1], pe, b[m - 1]))
            f.material_index = mi(len(profil) - 2)
    if ring or (pa is not None and pe is not None):
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if drehung is not None:
        bmesh.ops.transform(bm, matrix=drehung, verts=bm.verts)
    ob = g.objekt_aus(bm, name, list(mats))
    for p in ob.data.polygons:
        p.use_smooth = glatt
    return ob


#: Drehungen, die die Y-Achse eines Drehkörpers auf eine andere Achse legen.
Y_NACH_X = Matrix.Rotation(math.radians(-90), 4, "Z")
Y_NACH_MINUS_X = Matrix.Rotation(math.radians(90), 4, "Z")


def umriss_extrudieren(name, umriss, dicke, mat, ebene="xz", mitte: float = 0.0, glatt=False):
    """Ein ebener Umriss als Platte. ``ebene`` ``xz``: Dicke entlang Y;
    ``yz``: Dicke entlang X (Vorderseite +X)."""
    bm = bmesh.new()
    a, b = [], []
    for p, q in umriss:
        if ebene == "xz":
            a.append(bm.verts.new((p, mitte - dicke / 2, q)))
            b.append(bm.verts.new((p, mitte + dicke / 2, q)))
        else:
            a.append(bm.verts.new((mitte - dicke / 2, p, q)))
            b.append(bm.verts.new((mitte + dicke / 2, p, q)))
    n = len(a)
    bm.faces.new(a)
    bm.faces.new(list(reversed(b)))
    for i in range(n):
        bm.faces.new((a[i], a[(i + 1) % n], b[(i + 1) % n], b[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = g.objekt_aus(bm, name, [mat])
    for p in ob.data.polygons:
        p.use_smooth = glatt
    return ob


def streifen_extrudieren(name, aussen, innen, dicke, mat, geschlossen=True, mitte: float = 0.0):
    """Band zwischen zwei gleich langen Linienzügen in der YZ-Ebene, Dicke
    entlang X, Vorderseite +X — für Ringe und Bögen (Embleme)."""
    bm = bmesh.new()
    n = len(aussen)
    va = [bm.verts.new((mitte + dicke / 2, y, z)) for y, z in aussen]
    vi = [bm.verts.new((mitte + dicke / 2, y, z)) for y, z in innen]
    ha = [bm.verts.new((mitte - dicke / 2, y, z)) for y, z in aussen]
    hi = [bm.verts.new((mitte - dicke / 2, y, z)) for y, z in innen]
    for i in range(n if geschlossen else n - 1):
        j = (i + 1) % n
        bm.faces.new((va[i], va[j], vi[j], vi[i]))
        bm.faces.new((hi[i], hi[j], ha[j], ha[i]))
        bm.faces.new((ha[i], ha[j], va[j], va[i]))
        bm.faces.new((vi[i], vi[j], hi[j], hi[i]))
    if not geschlossen:
        bm.faces.new((va[0], vi[0], hi[0], ha[0]))
        bm.faces.new((va[-1], ha[-1], hi[-1], vi[-1]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return g.objekt_aus(bm, name, [mat])


def auf_flaeche(ob, treffer, normale, einsenken: float, dreh_um_normale: float = 0.0):
    """Ein Teil, dessen Vorderseite nach +X zeigt, auf eine Fläche setzen."""
    n = Vector(normale).normalized()
    q = Vector((1, 0, 0)).rotation_difference(n)
    oben = q @ Vector((0, 0, 1))
    ziel_oben = Vector((0, 0, 1)) - n * n.z
    if ziel_oben.length > 1e-4 and oben.length > 1e-4:
        ziel_oben.normalize()
        winkel = oben.angle(ziel_oben)
        achse = oben.cross(ziel_oben)
        if achse.dot(n) < 0:
            winkel = -winkel
        q = Matrix.Rotation(winkel, 4, n).to_quaternion() @ q
    if dreh_um_normale:
        q = Matrix.Rotation(dreh_um_normale, 4, n).to_quaternion() @ q
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = q
    ob.location = Vector(treffer) - n * einsenken
    g.transform_anwenden(ob)
    return ob


def strahl(ziel_ob, start, richtung):
    """Wo ein Strahl die Karosserie trifft: (Ort, Normale) oder None."""
    ok, ort, normale, _i = ziel_ob.ray_cast(Vector(start), Vector(richtung).normalized())
    if not ok:
        return None
    return ort, normale


class Treffer:
    """Schnelle Strahltests gegen ein festes Netz, mit Material der Fläche.

    ``Object.ray_cast`` baut seinen Suchbaum bei jedem Aufruf neu; Gitter und
    Leuchten brauchen Tausende Strahlen.
    """

    def __init__(self, ob) -> None:
        me = ob.data
        punkte = [v.co.copy() for v in me.vertices]
        flaechen = [tuple(p.vertices) for p in me.polygons]
        self.baum = BVHTree.FromPolygons(punkte, flaechen, all_triangles=False)
        self.mat = [p.material_index for p in me.polygons]

    def strahl(self, start, richtung):
        ort, normale, index, _d = self.baum.ray_cast(Vector(start), Vector(richtung).normalized())
        if ort is None:
            return None
        return ort, normale, self.mat[index]

    def ansicht(self, ansicht: str, a: float, b: float, erlaubt=None, von_links: bool = True):
        """Strahl entlang der Blickachse einer Ansicht auf den Bildpunkt (a, b)."""
        ia, ib, ic = ACHSEN[ansicht]
        start = [0.0, 0.0, 0.0]
        richtung = [0.0, 0.0, 0.0]
        start[ia], start[ib] = a, b
        if ansicht == "hinten" or (ansicht == "seite" and not von_links):
            start[ic], richtung[ic] = -10.0, 1.0
        else:
            start[ic], richtung[ic] = 10.0, -1.0
        t = self.strahl(start, richtung)
        if t is None or (erlaubt is not None and t[2] not in erlaubt):
            return None
        return t[0], t[1]


def blickrichtung(ansicht: str, von_links: bool = True) -> Vector:
    """Einheitsvektor zum Betrachter der Ansicht."""
    ic = ACHSEN[ansicht][2]
    v = [0.0, 0.0, 0.0]
    v[ic] = -1.0 if (ansicht == "hinten" or (ansicht == "seite" and not von_links)) else 1.0
    return Vector(v)


def achse3(ansicht: str, k: int) -> Vector:
    """Die k-te Bildachse (0 oder 1) als Weltvektor."""
    v = [0.0, 0.0, 0.0]
    v[ACHSEN[ansicht][k]] = 1.0
    return Vector(v)


# ---------------------------------------------------------------------------
# 2D-Helfer für Umrisse aus den Zonen
# ---------------------------------------------------------------------------

def flaeche2(poly) -> float:
    return 0.5 * sum(poly[i - 1][0] * poly[i][1] - poly[i][0] * poly[i - 1][1] for i in range(len(poly)))


def schwerpunkt2(poly):
    n = len(poly)
    return (sum(p[0] for p in poly) / n, sum(p[1] for p in poly) / n)


def im_polygon(pt, poly) -> bool:
    x, y = pt
    drin = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            drin = not drin
        j = i
    return drin


def polygon_einruecken(poly, d: float):
    """Umriss um ``d`` nach innen versetzen (Winkelhalbierende je Ecke).

    Liefert dazu je Ecke die Außennormale — damit lässt sich ein Teil des
    Umrisses nach seiner Lage auswählen (``verlauf``).
    """
    s = 1.0 if flaeche2(poly) > 0 else -1.0
    n = len(poly)
    neu, aussen = [], []
    for i in range(n):
        p0, p1, p2 = poly[i - 1], poly[i], poly[(i + 1) % n]
        e1 = Vector((p1[0] - p0[0], p1[1] - p0[1]))
        e2 = Vector((p2[0] - p1[0], p2[1] - p1[1]))
        if e1.length < 1e-9 or e2.length < 1e-9:
            neu.append(p1)
            aussen.append(Vector((0, 0)))
            continue
        e1.normalize()
        e2.normalize()
        n1 = Vector((-e1.y, e1.x)) * s
        n2 = Vector((-e2.y, e2.x)) * s
        m = n1 + n2
        if m.length < 1e-6:
            m = n1
        m.normalize()
        cos = max(0.35, m.dot(n1))
        neu.append((p1[0] + m.x * d / cos, p1[1] + m.y * d / cos))
        aussen.append(-m)
    return neu, aussen


def polygon_skalieren(poly, f: float):
    c = schwerpunkt2(poly)
    return [(c[0] + (p[0] - c[0]) * f, c[1] + (p[1] - c[1]) * f) for p in poly]


def laengster_lauf(poly, aussen, richtung2) -> list:
    """Der längste zusammenhängende Teil des (geschlossenen) Umrisses, dessen
    Außennormale in ``richtung2`` zeigt."""
    n = len(poly)
    r = Vector(richtung2)
    if r.length < 1e-9:
        return list(poly) + [poly[0]]
    r.normalize()
    gut = [aussen[i].length > 0 and aussen[i].dot(r) > 0.3 for i in range(n)]
    if all(gut):
        return list(poly) + [poly[0]]
    if not any(gut):
        return []
    start = next(i for i in range(n) if not gut[i])
    best, lauf = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if gut[i]:
            lauf.append(poly[i])
        else:
            if len(lauf) > len(best):
                best = lauf
            lauf = []
    if len(lauf) > len(best):
        best = lauf
    return best


def verdichten(punkte, schritt: float):
    """Linienzug so unterteilen, dass kein Stück länger als ``schritt`` ist."""
    if len(punkte) < 2:
        return list(punkte)
    neu = [punkte[0]]
    for a, b in zip(punkte, punkte[1:]):
        lg = math.hypot(b[0] - a[0], b[1] - a[1])
        k = max(1, int(math.ceil(lg / schritt)))
        for j in range(1, k + 1):
            t = j / k
            neu.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return neu


def quer_schnitte(poly, achse: int, c: float):
    """Schnittintervalle der Linie ``koordinate[achse] = c`` mit dem Umriss."""
    xs = []
    m = len(poly)
    for i in range(m):
        pa, pb = poly[i], poly[(i + 1) % m]
        if (pa[achse] - c) * (pb[achse] - c) < 0:
            t = (c - pa[achse]) / (pb[achse] - pa[achse])
            xs.append(pa[1 - achse] + (pb[1 - achse] - pa[1 - achse]) * t)
    xs.sort()
    return list(zip(xs[::2], xs[1::2]))


# ---------------------------------------------------------------------------
# Leisten, Deckel, Leuchteneinsätze
# ---------------------------------------------------------------------------

def band(name, punkte, normalen, breite, hoehe, mat, geschlossen=False):
    """Leiste mit Rechteckquerschnitt entlang eines Linienzugs auf einer Fläche
    (LED-Streifen, Zierleisten). ``normalen``: Flächennormale je Punkt."""
    n = len(punkte)
    if n < 2:
        return None
    ringe = []
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
            continue
        t.normalize()
        s = nn.cross(t).normalized() * (breite / 2)
        ringe.append([p - s, p + s, p + s + nn * hoehe, p - s + nn * hoehe])
    if len(ringe) < 2:
        return None
    return netz_aus_ringen(name, ringe, mat, geschlossen=True, kappen=not geschlossen,
                           schleife=geschlossen, glatt=False)


def deckel(name, flaechen, mat, abstand: float = 0.0015):
    """Abdeckscheibe aus der Originalhaut einer Leuchtenzone.

    ``flaechen``: Liste von Eckpunktlisten (vor dem Vertiefen abgenommen).
    Die Scheibe liegt ``abstand`` über der Haut, damit sie nicht mit dem
    Rahmen flimmert.
    """
    index, punkte, normalen, polys = {}, [], [], []
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
    if not polys:
        return None
    versetzt = [p + (nn.normalized() if nn.length > 0 else nn) * abstand
                for p, nn in zip(punkte, normalen)]
    ob = g.objekt_aus_daten(name, versetzt, polys, [mat])
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def randschleifen(flaechen) -> list:
    """Randschleifen einer Flächenmenge (BMesh-Flächen) in 3D.

    Je Schleife eine Liste ``(Ort, Normale, nach_innen)``: ``nach_innen``
    liegt in der Fläche, senkrecht zum Rand, und zeigt in die Menge hinein.
    """
    for f in flaechen:
        f.normal_update()
    kanten = [e for f in flaechen for e in f.edges
              if sum(1 for lf in e.link_faces if lf in flaechen) == 1]
    nachbarn = {}
    for e in kanten:
        a, b = e.verts
        nachbarn.setdefault(a, []).append((b, e))
        nachbarn.setdefault(b, []).append((a, e))
    benutzt = set()
    ketten = []
    for e0 in kanten:
        if e0 in benutzt:
            continue
        benutzt.add(e0)
        kette = list(e0.verts)
        while True:
            weiter = next(((v, e) for v, e in nachbarn.get(kette[-1], []) if e not in benutzt), None)
            if weiter is None:
                break
            benutzt.add(weiter[1])
            if weiter[0] is kette[0]:
                break
            kette.append(weiter[0])
        if len(kette) >= 3:
            ketten.append(kette)
    ergebnis = []
    for kette in ketten:
        n = len(kette)
        schleife = []
        for i, v in enumerate(kette):
            fl = [f for f in v.link_faces if f in flaechen]
            if not fl:
                continue
            nn = sum((f.normal for f in fl), Vector())
            if nn.length < 1e-9:
                continue
            nn.normalize()
            mitte = sum((f.calc_center_median() for f in fl), Vector()) / len(fl)
            tg = kette[(i + 1) % n].co - kette[i - 1].co
            tg = tg - nn * tg.dot(nn)
            if tg.length < 1e-9:
                continue
            tg.normalize()
            innen = nn.cross(tg).normalized()
            if innen.dot(mitte - v.co) < 0:
                innen = -innen
            schleife.append((v.co.copy(), nn, innen))
        if len(schleife) >= 3:
            ergebnis.append(_schleife_glaetten(schleife))
    return ergebnis


def _schleife_glaetten(schleife, schritt: float = 0.012, runden: int = 4):
    """Randschleife gleichmäßig neu abtasten und glätten.

    Der Rand einer geschnittenen Zone folgt der Dreiecksteilung der Haut und
    springt im Millimeterbereich hin und her; eine Leiste darauf zackt.
    """
    orte = [o for o, _n, _i in schleife]
    n = len(orte)
    laengen = [0.0]
    for i in range(n):
        laengen.append(laengen[-1] + (orte[(i + 1) % n] - orte[i]).length)
    gesamt = laengen[-1]
    m = max(8, int(gesamt / schritt))
    neu = []
    j = 0
    for k in range(m):
        s = gesamt * k / m
        while laengen[j + 1] < s:
            j += 1
        t = (s - laengen[j]) / max(laengen[j + 1] - laengen[j], 1e-9)
        a, b = schleife[j], schleife[(j + 1) % n]
        neu.append([a[0].lerp(b[0], t), a[1].lerp(b[1], t).normalized(), a[2]])
    for _r in range(runden):
        orte = [neu[i - 1][0] * 0.25 + neu[i][0] * 0.5 + neu[(i + 1) % m][0] * 0.25 for i in range(m)]
        for i in range(m):
            neu[i][0] = orte[i]
    ergebnis = []
    for i in range(m):
        ort, nn, innen_alt = neu[i]
        tg = neu[(i + 1) % m][0] - neu[i - 1][0]
        tg = tg - nn * tg.dot(nn)
        if tg.length < 1e-9:
            continue
        innen = nn.cross(tg.normalized()).normalized()
        if innen.dot(innen_alt) < 0:
            innen = -innen
        ergebnis.append((ort, nn, innen))
    return ergebnis


#: Weltrichtungen für ``led.verlauf``.
VERLAUF = {"oben": (0, 0, 1), "unten": (0, 0, -1), "vorn": (1, 0, 0), "hinten": (-1, 0, 0)}


def led_am_rand(schleife, led, treffer, boden, mats, tiefe=None):
    """LED-Leiste entlang einer Randschleife der Leuchte (abgenommen vor dem
    Vertiefen), um ``abstand_m`` nach innen versetzt und auf den
    Gehäuseboden gesenkt. ``verlauf``: ``rand`` (ganz herum) oder
    eine Richtung — dann nur der längste Teil des Rands, dessen Außenseite
    dorthin zeigt (``aussen``/``innen``: weg von der bzw. zur Wagenmitte).

    ``tiefe``: wie tief das Gehäuse vertieft ist. Dann sinkt die Leiste genau
    so weit, wie ``inset_region`` den Boden verschoben hat — entlang der
    Normale der Leuchtenfläche am Rand, der Richtung der Vertiefung. Ein
    Strahl dorthin verfehlt am schmalen, schrägen Ende den Boden (er trifft
    die Gehäusewand oder nichts), die Leiste bliebe dort auf der Haut stehen
    und zackte. Ohne ``tiefe`` wird wie früher per Strahl gesenkt.
    """
    mat = mats[led.get("mat", "licht_vorn")]
    abstand = led.get("abstand_m", 0.008)
    verlauf = led.get("verlauf", "rand")
    pkt, nrm, gueltig = [], [], []
    for ort, nn, innen in schleife:
        p = ort + innen * abstand
        ok = True
        if tiefe is not None:
            p = p - nn * tiefe
            # Liegt dort überhaupt Gehäuseboden? An einer Spitze, die schmaler
            # ist als Abstand und Leiste, träfe die Leiste Wand oder Lack —
            # dort endet sie lieber.
            h = treffer.strahl(p + nn * (tiefe + 0.01), -nn)
            ok = h is not None and h[2] in boden and (h[0] - p).length < max(0.8 * tiefe, 0.008)
        else:
            h = treffer.strahl(p + nn * 0.01, -nn)
            if h is not None and h[2] in boden and (h[0] - p).length < 0.08:
                p = h[0]
        pkt.append(p)
        nrm.append(nn)
        gueltig.append(ok)
    n = len(pkt)
    if verlauf == "rand":
        gut = [True] * n
    else:
        if verlauf in ("aussen", "innen"):
            y = sum(o.y for o, _n, _i in schleife) / n
            s = (1.0 if y >= 0 else -1.0) * (1.0 if verlauf == "aussen" else -1.0)
            d3 = Vector((0.0, s, 0.0))
        else:
            d3 = Vector(VERLAUF[verlauf])
        gut = [(-innen).dot(d3) > led.get("schwelle", 0.3) for _o, _n, innen in schleife]
        if any(gut) and not all(gut):
            # Nur der längste zusammenhängende Teil in Richtung ``verlauf``.
            laeufe = _laeufe(gut)
            best = set(max(laeufe, key=len))
            gut = [i in best for i in range(n)]
    maske = [a and b for a, b in zip(gut, gueltig)]
    if all(maske):
        wege = [(pkt, nrm, True)]
    else:
        wege = [([pkt[i] for i in lauf], [nrm[i] for i in lauf], False)
                for lauf in _laeufe(maske) if len(lauf) >= 3]
    teile = []
    for pp, nn, geschlossen in wege:
        ob = band("led", pp, nn, led.get("breite_m", 0.007), led.get("hoehe_m", 0.004), mat,
                  geschlossen=geschlossen)
        if ob is not None:
            teile.append(ob)
    return teile


def _laeufe(maske) -> list:
    """Zusammenhängende Läufe (Indexlisten) der wahren Einträge einer
    geschlossenen Folge; ein Lauf darf über das Ende hinweg weiterlaufen."""
    n = len(maske)
    if not any(maske):
        return []
    if all(maske):
        return [list(range(n))]
    start = next(i for i in range(n) if not maske[i])
    laeufe, lauf = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if maske[i]:
            lauf.append(i)
        elif lauf:
            laeufe.append(lauf)
            lauf = []
    if lauf:
        laeufe.append(lauf)
    return laeufe


def projektor(name, r: float, mats, art: str = "projektor"):
    """Scheinwerfereinsatz mit Öffnung nach +X, Boden bei x = 0.

    ``projektor``: Chromschale, dunkle Linse, Leuchtring. ``reflektor``:
    tiefe Chromschale mit Glühkörper in der Mitte.
    """
    teile = []
    tiefe = 0.016 if art == "projektor" else 0.022
    # Schale: offener Kegel, innen sichtbar.
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=False, cap_tris=False, segments=20,
                          radius1=r * 0.35, radius2=r, depth=tiefe)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, tiefe / 2))
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                     matrix=Matrix.Rotation(math.radians(90), 3, "Y"))
    # Normalen nach innen: gesehen wird die Innenseite.
    mitte = Vector((tiefe * 2, 0, 0))
    for f in bm.faces:
        if (f.calc_center_median() - mitte).dot(f.normal) > 0:
            f.normal_flip()
    schale = g.objekt_aus(bm, name + "_schale", [mats["chrom"]])
    for p in schale.data.polygons:
        p.use_smooth = True
    teile.append(schale)
    teile.append(zylinder_x(name + "_boden", (0.001, 0, 0), r * 0.36, 0.002, mats["zierteil"], segmente=16))
    if art == "projektor":
        linse = kugel(name + "_linse", (tiefe * 0.35, 0, 0), (r * 1.1, r * 1.1, r * 1.1),
                      mats["zierteil"], segmente=16, ringe=8)
        teile.append(linse)
        bpy.ops.mesh.primitive_torus_add(major_radius=r * 0.8, minor_radius=0.0028,
                                         major_segments=24, minor_segments=5)
        ring = bpy.context.object
        ring.rotation_euler = (0, math.radians(90), 0)
        ring.location = (tiefe * 0.9, 0, 0)
        g.transform_anwenden(ring)
        ring.data.materials.append(mats["licht_vorn"])
        teile.append(ring)
    else:
        teile.append(kugel(name + "_birne", (tiefe * 0.45, 0, 0), (r * 0.5, r * 0.5, r * 0.5),
                           mats["licht_vorn"], segmente=12, ringe=6))
    return g.verbinden(teile, name)


# ---------------------------------------------------------------------------
# Gitter
# ---------------------------------------------------------------------------

def _flaechen_ausrichten(bm, blick: Vector, zellen) -> None:
    """Deckflächen zum Betrachter, Innenwände zur Zellmitte drehen."""
    for f, art, bezug in zellen:
        f.normal_update()
        if art == "deck":
            if f.normal.dot(blick) < 0:
                f.normal_flip()
        else:
            if (bezug - f.calc_center_median()).dot(f.normal) < 0:
                f.normal_flip()


def gitter_zellen(name, poly, art, masche, steg, hoehe, projizieren, blick, mat,
                  seitenverhaeltnis: float = 0.62):
    """Waben- oder Rautengitter in einem Umriss, Zelle für Zelle auf den Boden
    der Öffnung projiziert. ``projizieren(a, b)`` → (Ort, Normale) oder None.
    ``blick``: Einheitsvektor zum Betrachter; die Stege stehen entlang ``blick``.
    """
    if art == "raute":
        ecken_n, ra, rb = 4, masche / 2, masche / 2 * seitenverhaeltnis
        dx, dy = masche, masche * seitenverhaeltnis / 2
        winkel0 = 0.0
        wand = steg / 2 * 1.2
    else:
        ecken_n = 6
        ra = rb = masche / math.sqrt(3)
        dx, dy = masche, masche * math.sqrt(3) / 2
        winkel0 = math.pi / 6
        wand = (steg / 2) / math.cos(math.pi / 6)
    a0 = min(p[0] for p in poly)
    a1 = max(p[0] for p in poly)
    b0 = min(p[1] for p in poly)
    b1 = max(p[1] for p in poly)
    bm = bmesh.new()
    zellen = []
    j = 0
    b = b0
    while b <= b1 + dy:
        a = a0 + (dx / 2 if j % 2 else 0.0)
        while a <= a1 + dx:
            aussen, innen = [], []
            for k in range(ecken_n):
                w = winkel0 + 2 * math.pi * k / ecken_n
                ca, cb = math.cos(w), math.sin(w)
                aussen.append((a + ca * ra, b + cb * rb))
                fi = 1.0 - wand / min(ra, rb)
                innen.append((a + ca * ra * fi, b + cb * rb * fi))
            if all(im_polygon(q, poly) for q in aussen):
                ta, ti, bi = [], [], []
                ok = True
                for qa, qi in zip(aussen, innen):
                    ha, hi = projizieren(*qa), projizieren(*qi)
                    if ha is None or hi is None:
                        ok = False
                        break
                    ta.append(ha[0] + blick * hoehe)
                    ti.append(hi[0] + blick * hoehe)
                    bi.append(hi[0])
                if ok:
                    va = [bm.verts.new(v) for v in ta]
                    vt = [bm.verts.new(v) for v in ti]
                    vb = [bm.verts.new(v) for v in bi]
                    mitte = sum(ti, Vector()) / len(ti) - blick * hoehe * 0.5
                    for k in range(ecken_n):
                        k2 = (k + 1) % ecken_n
                        zellen.append((bm.faces.new((va[k], va[k2], vt[k2], vt[k])), "deck", None))
                        zellen.append((bm.faces.new((vt[k], vt[k2], vb[k2], vb[k])), "wand", mitte))
            a += dx
        b += dy
        j += 1
    if not bm.faces:
        bm.free()
        return None
    _flaechen_ausrichten(bm, blick, zellen)
    return g.objekt_aus(bm, name, [mat])


def gitter_lamellen(name, poly, masche, steg, hoehe, projizieren, blick, b_achse, mat,
                    winkel_grad: float = 0.0, schritt: float = 0.025):
    """Lamellen quer über eine Öffnung (entlang der ersten Bildachse), jede als
    durchgehende, auf den Boden projizierte Leiste. ``winkel_grad`` neigt die
    Lamellen zur zweiten Bildachse hin."""
    b0 = min(p[1] for p in poly)
    b1 = max(p[1] for p in poly)
    n = max(1, int((b1 - b0) / masche))
    w = math.radians(winkel_grad)
    teile = []
    for k in range(n):
        c = b0 + (b1 - b0) * (k + 0.5) / n
        for s0, s1 in quer_schnitte(poly, 1, c):
            if s1 - s0 < 0.02:
                continue
            m = max(2, int(math.ceil((s1 - s0) / schritt)) + 1)
            ringe = []
            for i in range(m):
                a = s0 + (s1 - s0) * i / (m - 1)
                t = projizieren(a, c)
                if t is None:
                    if len(ringe) >= 2:
                        teile.append(netz_aus_ringen(name, ringe, mat, kappen=True, glatt=False))
                    ringe = []
                    continue
                ort = t[0]
                oben = blick * (hoehe * math.cos(w)) + b_achse * (hoehe * math.sin(w))
                dick = b_achse * (steg / 2 * math.cos(w)) - blick * (steg / 2 * math.sin(w))
                ringe.append([ort - dick, ort + dick, ort + dick + oben, ort - dick + oben])
            if len(ringe) >= 2:
                teile.append(netz_aus_ringen(name, ringe, mat, kappen=True, glatt=False))
    teile = [t for t in teile if t is not None]
    return g.verbinden(teile, name) if teile else None


# ---------------------------------------------------------------------------
# Heckflügel
# ---------------------------------------------------------------------------

def naca_profil(woelbung: float, lage: float, dicke: float, n: int = 14):
    """NACA-Vierstellenprofil, Sehne 0..1 von der Vorderkante, geschlossen.

    Liefert Punkte (x, z): Oberseite von der Hinterkante zur Vorderkante,
    dann die Unterseite zurück. Hinterkante geschlossen.
    """
    oben, unten = [], []
    for i in range(n + 1):
        x = 0.5 * (1 - math.cos(math.pi * i / n))
        yt = 5 * dicke * (0.2969 * math.sqrt(x) - 0.126 * x - 0.3516 * x ** 2
                          + 0.2843 * x ** 3 - 0.1036 * x ** 4)
        if x < lage:
            yc = woelbung / lage ** 2 * (2 * lage * x - x * x)
            dyc = 2 * woelbung / lage ** 2 * (lage - x)
        else:
            yc = woelbung / (1 - lage) ** 2 * ((1 - 2 * lage) + 2 * lage * x - x * x)
            dyc = 2 * woelbung / (1 - lage) ** 2 * (lage - x)
        th = math.atan(dyc)
        oben.append((x - yt * math.sin(th), yc + yt * math.cos(th)))
        unten.append((x + yt * math.sin(th), yc - yt * math.cos(th)))
    return list(reversed(oben)) + unten[1:-1]


def fluegelblatt(name, profil, x_vk, z_vk, sehne, halb, anstellung_grad, mat, abtrieb=True):
    """Ein Flügelelement: Profil ``profil`` (x 0..1 ab Vorderkante), Vorderkante
    bei (x_vk, z_vk), nach hinten (−X) gestreckt. ``abtrieb``: Wölbung nach
    unten; die Anstellung hebt die Hinterkante."""
    w = math.radians(anstellung_grad)
    pkt = []
    for x, z in profil:
        z = -z if abtrieb else z
        # nach hinten gestreckt, dann um die Vorderkante gedreht
        dx, dz = -x * sehne, z * sehne
        rx = dx * math.cos(w) + dz * math.sin(w)
        rz = dz * math.cos(w) - dx * math.sin(w)
        pkt.append((x_vk + rx, z_vk + rz))
    ringe = [[(px, y, pz) for px, pz in pkt] for y in (-halb, -halb * 0.5, 0.0, halb * 0.5, halb)]
    ob = netz_aus_ringen(name, ringe, mat, kappen=True, glatt=True)
    g.glatt(ob, 35)
    return ob, pkt


def fluegel(d, fo, strahl_fn, mats):
    """Heckflügel mit Profil, Endplatten und Stützen.

    Lage wie der alte Kastenflügel: ``u`` Hinterkante, ``v`` halbe Spannweite,
    ``hoehe_m`` Oberkante, ``tiefe_m`` Sehne.
    """
    ms = fo.ms
    teile = []
    x_hk = ms.x(d.get("u", 0.02))
    sehne = d.get("tiefe_m", 0.3)
    halb = ms.y(d.get("v", 0.85))
    z_ok = d["hoehe_m"]
    anst = d.get("anstellung_grad", 8)
    prof = naca_profil(d.get("woelbung", 0.06), d.get("woelbung_lage", 0.4), d.get("dicke", 0.12))
    elemente = d.get("elemente", 1)
    mat = mats[d.get("mat", "carbon")]
    s1 = sehne * (0.72 if elemente == 2 else 1.0)
    # Vorderkante so, dass die Hinterkante des Hauptblatts bei x_hk liegt und
    # die Oberkante etwa bei z_ok.
    x_vk = x_hk + s1 * math.cos(math.radians(anst))
    z_vk = z_ok - 0.02
    blatt, pkt = fluegelblatt("fluegel", prof, x_vk, z_vk, s1, halb, anst, mat)
    teile.append(blatt)
    if d.get("schrift"):
        sz = d["schrift"]
        x_mitte = x_vk - s1 * sz.get("sehne_anteil", 0.42) * math.cos(math.radians(anst))
        ob = schrift_auf_blatt(sz, pkt, x_mitte, halb, mats)
        if ob is not None:
            teile.append(ob)
    z_min = min(p[1] for p in pkt)
    z_max = max(p[1] for p in pkt)
    x_min = min(p[0] for p in pkt)
    if elemente == 2:
        s2 = sehne * 0.4
        p_hk = pkt[0]
        klappe, pk2 = fluegelblatt("fluegelklappe", prof, p_hk[0] + s2 * 0.25, p_hk[1] + s2 * 0.35,
                                   s2, halb, anst + 22, mat)
        teile.append(klappe)
        z_max = max(z_max, max(p[1] for p in pk2))
        x_min = min(x_min, min(p[0] for p in pk2))
    elif d.get("gurney", True):
        p_hk = pkt[0]
        teile.append(kasten("gurney", (p_hk[0] + 0.004, 0, p_hk[1] + 0.012), (0.006, 2 * halb, 0.024), mat))
    # Endplatten: Umriss in XZ, unten weiter nach hinten gezogen.
    unten, oben = d.get("endplatte_m", [0.1, 0.05])
    pm = mats[d.get("platten_mat", d.get("mat", "carbon"))]
    xv = x_vk + 0.03
    xh = x_min - 0.035
    za, ze = z_min - unten, z_max + oben
    umriss = [(xv, ze - 0.03), (xv - 0.03, ze), (xh + 0.02, ze), (xh, ze - 0.02),
              (xh - 0.02, za + 0.03), (xh + 0.02, za), (xv - 0.1, za), (xv, za + 0.06)]
    for seite in (1, -1):
        teile.append(umriss_extrudieren("endplatte", umriss, 0.01, pm, mitte=seite * (halb + 0.005)))
    # Stützen
    sm = mats[d.get("stuetzen_mat", d.get("mat", "carbon"))]
    art = d.get("stuetzen", "schwanenhals")
    for seite in (1, -1):
        y = seite * halb * d.get("stuetzen_v", 0.55)
        x_fuss = max(x_hk + sehne * 0.6, ms.x(fo.u0) + d.get("fuss_m", 0.25))
        t = strahl_fn((x_fuss, y, 5), (0, 0, -1))
        z0 = (t[0].z if t else z_ok - 0.3) - 0.01
        if art == "schwanenhals":
            # Von unten über die Vorderkante gebogen, oben am Blatt befestigt.
            x_an = x_vk - s1 * 0.45
            z_an = _oberseite(pkt, x_an) - 0.004
            p0 = Vector((x_fuss, z0))
            p1 = Vector((x_fuss + 0.02, z_max + 0.12))
            p2 = Vector((x_an + 0.12, z_max + 0.1))
            p3 = Vector((x_an, z_an))
            links, rechts = [], []
            m = 14
            for i in range(m + 1):
                t_ = i / m
                q = ((1 - t_) ** 3) * p0 + 3 * ((1 - t_) ** 2) * t_ * p1 + 3 * (1 - t_) * t_ * t_ * p2 + t_ ** 3 * p3
                dq = 3 * ((1 - t_) ** 2) * (p1 - p0) + 6 * (1 - t_) * t_ * (p2 - p1) + 3 * t_ * t_ * (p3 - p2)
                dq.normalize()
                nq = Vector((-dq.y, dq.x))
                b = 0.075 * (1 - t_) + 0.035 * t_
                links.append(q + nq * b / 2)
                rechts.append(q - nq * b / 2)
            umr = [(v.x, v.y) for v in links] + [(v.x, v.y) for v in reversed(rechts)]
            teile.append(umriss_extrudieren("stuetze", umr, 0.014, sm, mitte=y))
            teile.append(kasten("stuetzenfuss", (x_fuss, y, z0 + 0.008), (0.1, 0.03, 0.016), sm, fase=0.004))
        else:
            x_oben = x_vk - s1 * 0.5
            z_u = _unterseite(pkt, x_oben)
            laenge = math.hypot(x_fuss - x_oben, z_u - z0)
            winkel = math.atan2(x_oben - x_fuss, z_u - z0)
            umr = [(-0.05, 0.0), (0.05, 0.0), (0.035, laenge), (-0.035, laenge)]
            st = umriss_extrudieren("stuetze", umr, 0.016, sm)
            st.data.transform(Matrix.Rotation(winkel, 4, "Y"))
            st.location = (x_fuss, y, z0)
            g.transform_anwenden(st)
            teile.append(st)
    return teile


def schriftzug(name, text: str, hoehe: float, mat, kursiv: float = 0.2, fett: float = 0.0):
    """Flacher Schriftzug (Blenders eingebaute Schrift) in der XY-Ebene,
    Mitte im Ursprung, Versalhöhe ``hoehe``, Lesen entlang +X."""
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = text
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    cu.shear = kursiv
    cu.offset = fett
    cu.resolution_u = 2
    hilf = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(hilf)
    tiefe = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(hilf.evaluated_get(tiefe))
    bpy.data.objects.remove(hilf, do_unlink=True)
    bpy.data.curves.remove(cu)
    if not me.vertices:
        return None
    ys = [v.co.y for v in me.vertices]
    xs = [v.co.x for v in me.vertices]
    f = hoehe / max(max(ys) - min(ys), 1e-6)
    mitte = Vector(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, 0))
    me.transform(Matrix.Scale(f, 4) @ Matrix.Translation(-mitte))
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    return ob


def schrift_auf_blatt(sz, pkt, x_mitte, halb, mats):
    """Schriftzug ``sz["text"]`` auf der Oberseite eines Flügelblatts.

    Lesen entlang der Spannweite; ``oben``: wohin die Oberkante der Buchstaben
    zeigt — ``"hinten"`` (wie im Sprite der Drifter: von oben gesehen quer
    lesbar, von hinten Kopf) oder ``"vorn"``. ``hoehe_m`` Versalhöhe entlang
    der Sehne, ``lage`` (0.5) Mitte entlang der Spannweite von rechts nach
    links, ``kursiv``, ``fett`` (Randversatz der Glyphen), ``mat``.
    """
    ob = schriftzug("schrift", sz.get("text", "DRIFT"), sz.get("hoehe_m", 0.2),
                    mats[sz.get("mat", "dekor_weiss")], sz.get("kursiv", 0.25), sz.get("fett", 0.0))
    if ob is None:
        return None
    # Fein unterteilen, damit die Buchstaben der Wölbung folgen.
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    for _ in range(6):
        lang = [e for e in bm.edges if e.calc_length() > 0.02]
        if not lang:
            break
        bmesh.ops.subdivide_edges(bm, edges=lang, cuts=1)
        bmesh.ops.triangulate(bm, faces=bm.faces)
    y_mitte = -halb + 2 * halb * sz.get("lage", 0.5)
    vorzeichen = -1.0 if sz.get("oben", "hinten") == "hinten" else 1.0
    for v in bm.verts:
        tx, ty = v.co.x, v.co.y
        # Lesen von rechts nach links (+Y); Buchstabenoberkante nach -X bzw. +X.
        x = x_mitte + vorzeichen * ty
        y = y_mitte + tx * (-vorzeichen)
        v.co = Vector((x, y, _oberseite(pkt, x) + 0.0015))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:
        if f.normal.z < 0:
            f.normal_flip()
    bm.to_mesh(ob.data)
    bm.free()
    for pol in ob.data.polygons:
        pol.use_smooth = True
    return ob


def _oberseite(pkt, x):
    """Höchster Punkt des Profils bei x (linear zwischen Profilpunkten)."""
    best = -1e9
    for a, b in zip(pkt, pkt[1:] + pkt[:1]):
        if (a[0] - x) * (b[0] - x) <= 0 and abs(b[0] - a[0]) > 1e-9:
            t = (x - a[0]) / (b[0] - a[0])
            best = max(best, a[1] + (b[1] - a[1]) * t)
    return best if best > -1e8 else max(p[1] for p in pkt)


def _unterseite(pkt, x):
    best = 1e9
    for a, b in zip(pkt, pkt[1:] + pkt[:1]):
        if (a[0] - x) * (b[0] - x) <= 0 and abs(b[0] - a[0]) > 1e-9:
            t = (x - a[0]) / (b[0] - a[0])
            best = min(best, a[1] + (b[1] - a[1]) * t)
    return best if best < 1e8 else min(p[1] for p in pkt)


# ---------------------------------------------------------------------------
# Diffusor und Auspuff
# ---------------------------------------------------------------------------

def diffusor(d, fo, p, mats):
    """Rampe unter dem Heck, die nach hinten bis an die Unterkante des
    Stoßfängers ansteigt, mit senkrechten Finnen darunter."""
    ms = fo.ms
    x_hinten = ms.x(fo.u0) + 0.015
    laenge = d.get("laenge_m", 0.5)
    w = math.radians(d.get("winkel_grad", 11))
    halb = fo.w(fo.u0 + 0.06) * d.get("breite_v", 0.72)
    mat = mats[d.get("mat", p.get("diffusor_mat", "carbon"))]
    x_a = x_hinten + laenge
    z_a = fo.zu(ms.u(x_a)) + 0.004
    z_koerper = fo.zu(ms.u(x_hinten + 0.02)) - 0.012
    z_e = max(z_a + laenge * math.tan(w), z_koerper)
    teile = []
    ringe = []
    for i in range(6):
        t_ = i / 5
        x = x_a + (x_hinten - x_a) * t_
        z = z_a + (z_e - z_a) * t_ ** 1.4
        ringe.append([(x, -halb, z - 0.006), (x, halb, z - 0.006), (x, halb, z + 0.006), (x, -halb, z + 0.006)])
    teile.append(netz_aus_ringen("diffusor", ringe, mat, kappen=True, glatt=False))
    n = d.get("finnen", 5)
    z_u = z_a + (z_e - z_a) * d.get("finnen_anteil", 0.45)     # Unterkante der Finnen hinten
    for i in range(n):
        y = -halb + 2 * halb * (i + 0.5) / n if n > 1 else 0.0
        umr = [(x_a - 0.08, z_a + 0.002), (x_hinten, z_u), (x_hinten, z_e - 0.004)]
        for k in range(1, 5):
            t_ = 1 - k / 5
            umr.append((x_a + (x_hinten - x_a) * t_, z_a + (z_e - z_a) * t_ ** 1.4 - 0.004))
        teile.append(umriss_extrudieren("finne", umr, 0.008, mat, mitte=y))
    for seite in (1, -1):
        umr = [(x_a - 0.02, z_a - 0.004), (x_hinten, z_u - 0.02), (x_hinten, z_e), (x_a - 0.04, z_a + 0.006)]
        teile.append(umriss_extrudieren("finne", umr, 0.012, mat, mitte=seite * (halb + 0.006)))
    return teile


# ---------------------------------------------------------------------------
# Motor unter der Glasabdeckung
# ---------------------------------------------------------------------------

def motor(d, fo, mats, einfach: bool = False):
    """Längs eingebauter V-Motor unter einer gläsernen Motorabdeckung.

    Nur so viel, wie man durch das Glas sieht: eine dunkle Wanne (Boden und
    Wände, damit der Blick nicht in die hohle Karosserie fällt), zwei
    Zylinderbänke im V, Nockenwellendeckel aus Carbon mit Zündspulen, eine
    Ansaugbrücke mit Einzelrohren zu den Bänken und seitliche Carbonblenden.

    ``d``: ``u`` [hinten, vorn] und ``v`` (halbe Breite) des Motorraums,
    ``z_m`` [Boden, Oberkante], ``zylinder`` 8 oder 12 (Zahl der Rohre und
    Spulen), ``deckel_mat`` (carbon), ``metall_mat`` (bremse, die Bänke),
    ``ansaug_mat`` (alu, Brücke und Rohre), ``spulen_mat`` (sattel).
    ``einfach`` (LOD1): nur Wanne, Bänke und Ansaugbrücke ohne Fasen.
    """
    ms = fo.ms
    u0, u1 = d.get("u", [0.2, 0.33])
    x0, x1 = ms.x(u0), ms.x(u1)
    yb = ms.y(d.get("v", 0.3))
    z0, z1 = d.get("z_m", [0.45, 0.88])
    deckel = mats[d.get("deckel_mat", "carbon")]
    metall = mats[d.get("metall_mat", "bremse")]
    ansaug = mats[d.get("ansaug_mat", "alu")]
    spulen = mats[d.get("spulen_mat", "sattel")]
    dunkel = mats["kunststoff"]
    fase = 0.0 if einfach else 1.0
    teile = []
    lg = x1 - x0
    xm = (x0 + x1) / 2
    # Wanne: Boden und vier Wände, oben offen.
    wd = 0.01
    teile.append(kasten("motorwanne", (xm, 0, z0), (lg + 2 * wd, 2 * yb + 2 * wd, wd), dunkel))
    for s in (1, -1):
        teile.append(kasten("motorwanne", (xm, s * yb, (z0 + z1) / 2), (lg, wd, z1 - z0), dunkel))
    for x in (x0, x1):
        teile.append(kasten("motorwanne", (x, 0, (z0 + z1) / 2), (wd, 2 * yb, z1 - z0), dunkel))
    # Zylinderbänke im V (je 30° zur Senkrechten), darauf die Deckel.
    lm = lg * 0.86
    h = z1 - z0
    bank_b = min(0.16, yb * 0.5)
    for s in (1, -1):
        # Drehung um X: die Oberseite der linken Bank (s = 1) kippt nach +Y.
        w = -math.radians(30) * s
        achse_oben = Vector((0, -math.sin(w), math.cos(w)))
        achse_quer = Vector((0, math.cos(w), math.sin(w)))
        mitte = Vector((xm, s * yb * 0.42, z0 + h * 0.52))
        teile.append(kasten("zylinderbank", mitte, (lm, bank_b, h * 0.42), metall,
                            fase=0.012 * fase, drehung=(w, 0, 0)))
        oben = mitte + achse_oben * (h * 0.21 + 0.02)
        teile.append(kasten("nockendeckel", oben, (lm * 0.97, bank_b * 0.92, 0.045), deckel,
                            fase=0.015 * fase, drehung=(w, 0, 0)))
        if einfach:
            continue
        # Zündspulen und Einzelrohre der Ansaugbrücke
        n = d.get("zylinder", 8) // 2
        for k in range(n):
            x = xm - lm * 0.4 + lm * 0.8 * (k + 0.5) / n
            spule = oben + Vector((x - xm, 0, 0)) + achse_oben * 0.03 + achse_quer * (s * bank_b * 0.2)
            teile.append(kasten("zuendspule", spule, (0.03, 0.045, 0.022), spulen, drehung=(w, 0, 0)))
            rohr_mitte = Vector((x, s * yb * 0.2, z0 + h * 0.83))
            rohr = zylinder_y("ansaugrohr", (0, 0, 0), 0.021, yb * 0.26, ansaug, segmente=10)
            rohr.rotation_euler = (-s * math.radians(28), 0, 0)
            rohr.location = rohr_mitte
            g.transform_anwenden(rohr)
            teile.append(rohr)
    # Ansaugbrücke in der Mitte, oben ein Carbondeckel.
    teile.append(kasten("ansaugbruecke", (xm, 0, z0 + h * 0.84), (lm * 0.92, yb * 0.42, h * 0.16), ansaug,
                        fase=0.02 * fase))
    if not einfach:
        teile.append(kasten("ansaugdeckel", (xm, 0, z0 + h * 0.93), (lm * 0.8, yb * 0.3, 0.012), deckel,
                            fase=0.005))
        for s in (1, -1):
            # Seitliche Carbonblenden über den Auspuffkrümmern, schräg nach außen.
            teile.append(kasten("motorblende", (xm, s * yb * 0.86, z0 + h * 0.72), (lg * 0.94, yb * 0.3, 0.008),
                                deckel, drehung=(-s * math.radians(35), 0, 0)))
    return teile


def auspuffblende(name, r, laenge, mats, art="rund"):
    """Endrohrblende mit Rollrand und dunklem Inneren, Öffnung nach −X,
    Ursprung in der Öffnungsebene."""
    innen = r * 0.84
    profil = [(0.0, -laenge * 0.55), (innen, -laenge * 0.55), (innen, -0.003),
              (innen + 0.002, 0.0), (r - 0.002, 0.0), (r, -0.004), (r, -laenge), (0.0, -laenge)]
    # Abschnitte: Boden und Innenwand dunkel, Rand und Hülse Chrom.
    ob = drehkoerper(name, profil, [mats["chrom"], mats["kunststoff"]], segmente=24,
                     abschnitt_mat=[1, 1, 0, 0, 0, 0, 0], glatt=True,
                     drehung=Y_NACH_MINUS_X)
    if art == "oval":
        ob.data.transform(Matrix.Diagonal((1, 1.35, 0.8, 1)))
    g.glatt(ob, 40)
    return ob


# ---------------------------------------------------------------------------
# Spiegel, Türgriffe, Wischer
# ---------------------------------------------------------------------------

def spiegel(x, z, spitze, y_wand, seite, groesse, mats, d, td):
    """Außenspiegel: schlankes, nach hinten gepfeiltes Tropfengehäuse,
    eingefasstes Glas, Blinkerleiste und ein Stiel (``stiel``) oder ein Fuß am
    Fensterdreieck (``fuss``). ``schlank`` (0.62) und ``flach`` (0.8)
    verkleinern Tiefe und Höhe gegenüber ``spiegel.groesse``."""
    lang, tief, hoch = groesse
    lang *= td.get("schlank", 0.62)
    hoch *= td.get("flach", 0.8)
    pfeil = td.get("pfeilung_m", 0.035)
    art = td.get("art", "fuss")
    kappe = mats[td.get("kappe_mat", d.get("mat", "lack"))]
    fussmat = mats[td.get("fuss_mat", d.get("arm_mat", "zierteil"))]
    yc = spitze - tief / 2
    teile = []

    def skala(s):
        """(Tiefe, Höhe) des Querschnitts bei s (0 innen, 1 außen)."""
        if s < 0.25:
            t_ = s / 0.25
            glatt = t_ * t_ * (3 - 2 * t_)
            return 0.7 + 0.3 * glatt, 0.55 + 0.45 * glatt
        if s > 0.78:
            f = math.sqrt(max(0.0, 1 - ((s - 0.78) / 0.22) ** 2))
            return 0.25 + 0.75 * f, 0.3 + 0.7 * f
        return 1.0, 1.0

    ringe = []
    m = 14
    for i in range(m + 1):
        s = i / m
        bx, bz = skala(s)
        ring = []
        for j in range(20):
            w = 2 * math.pi * j / 20
            cx, cz = math.cos(w), math.sin(w)
            if cx >= 0:
                ex = sp(cx, 0.8) * lang / 2          # runde Front
            else:
                ex = -lang * 0.18 * abs(cx) ** 0.25  # flache Glasseite, Ecken gerundet
            ez = sp(cz, 0.6) * hoch / 2
            if cz > 0:
                ez *= 1.08                           # oben etwas voller als unten
            ring.append((x + ex * bx - pfeil * s, seite * (yc - tief / 2 + tief * s),
                         z + ez * bz + 0.008 * s))
        ringe.append(ring)
    teile.append(netz_aus_ringen("spiegel", ringe, kappe, kappen=True))
    # Glas mit schwarzem Rahmen, auf der flachen Rückseite
    x_glas = x - lang * 0.18 - pfeil * 0.5 - 0.004
    rahmen = platte("spiegelrahmen", tief * 0.8, hoch * 0.78, 0.006,
                    (mats["kunststoff"], mats["kunststoff"]), rundung=3.0)
    glas = platte("spiegelglas", tief * 0.72, hoch * 0.66, 0.003, (mats["chrom"], mats["kunststoff"]),
                  rundung=3.0)
    glas.location = (-0.003, 0, 0)
    g.transform_anwenden(glas)
    einheit = g.verbinden([rahmen, glas], "spiegelglas")
    einheit.rotation_euler = (0, 0, math.radians(180 - 9 * seite))
    einheit.location = (x_glas, seite * (yc + 0.01), z + 0.004)
    g.transform_anwenden(einheit)
    teile.append(einheit)
    # Blinker: schmale Leiste an der Vorderkante außen unten
    pk, nk = [], []
    for i in range(7):
        s = 0.5 + 0.42 * i / 6
        bx, bz = skala(s)
        pk.append(Vector((x + lang / 2 * bx * 0.8 - pfeil * s, seite * (yc - tief / 2 + tief * s),
                          z - hoch * 0.28 * bz + 0.008 * s)))
        nk.append(Vector((1, 0, -0.5)))
    bl = band("blinker", pk, nk, 0.008, 0.003, mats["blinker"])
    if bl:
        teile.append(bl)
    # Befestigung
    innen = yc - tief / 2 + 0.015
    if art == "stiel":
        ringe = []
        for i in range(7):
            t = i / 6
            yy = y_wand - 0.01 + (innen - y_wand + 0.01) * t
            zz = z - hoch * 0.45 + hoch * 0.3 * t * t
            xx = x - 0.02 + 0.03 * t
            br, hh = 0.045 - 0.018 * t, 0.018 - 0.004 * t
            ringe.append([(xx - br / 2, seite * yy, zz - hh / 2), (xx + br / 2, seite * yy, zz - hh / 2),
                          (xx + br / 2, seite * yy, zz + hh / 2), (xx - br / 2, seite * yy, zz + hh / 2)])
        teile.append(netz_aus_ringen("spiegelstiel", ringe, fussmat, kappen=True))
    else:
        # Fuß: flache Platte an der Tür, Arm zum Gehäuse
        fuss = kasten("spiegelfuss", (x - 0.04, seite * (y_wand + 0.004), z - hoch * 0.25),
                      (0.13, 0.018, 0.06), fussmat, fase=0.008)
        teile.append(fuss)
        if innen > y_wand:
            teile.append(kasten("spiegelarm", (x - 0.01, seite * (y_wand + innen) / 2, z - hoch * 0.22),
                                (0.05, innen - y_wand + 0.02, 0.026), fussmat, fase=0.009))
    return teile


def tuergriff(art, laenge, mats, griffmat):
    """Türgriff mit Griffmulde, Vorderseite +X (wird mit ``auf_flaeche`` auf
    die Flanke gesetzt; die Länge liegt dann waagerecht)."""
    teile = []
    # Mulde: dunkle, flache Schale hinter dem Griff
    mulde = platte("griffmulde", laenge * 0.8, 0.045, 0.004, (mats["zierteil"], mats["zierteil"]), rundung=2.2)
    mulde.location = (0.001, 0, 0)
    g.transform_anwenden(mulde)
    teile.append(mulde)
    if art == "buendig":
        teile.append(platte("griff", laenge, 0.026, 0.006, (griffmat, griffmat), rundung=2.4))
        leiste = platte("griffleiste", laenge * 0.9, 0.005, 0.002, (mats["chrom"], mats["chrom"]), rundung=2.0)
        leiste.location = (0.004, 0, -0.006)
        g.transform_anwenden(leiste)
        teile.append(leiste)
    else:
        ringe = []
        n = 9
        for i in range(n):
            t = i / (n - 1)
            y = -laenge / 2 + laenge * t
            bogen = math.sin(math.pi * t)
            ab = 0.004 + 0.016 * bogen ** 0.5        # Abstand zur Tür
            h = 0.018 + 0.006 * bogen
            dk = 0.012
            ringe.append([(ab, y, -h / 2), (ab + dk, y, -h / 2 + 0.002), (ab + dk, y, h / 2 - 0.002),
                          (ab, y, h / 2)])
        griff = netz_aus_ringen("griff", ringe, griffmat, kappen=True)
        teile.append(griff)
    return g.verbinden(teile, "tuergriff")


def antenne(laenge, hoehe, mat):
    """Dachantenne als Haifischflosse, Fuß im Ursprung, Spitze nach +X
    flach ansteigend, hinten steil abfallend."""
    ringe = []
    n = 8
    for i in range(n + 1):
        s = i / n                        # 0 vorn, 1 hinten
        h = hoehe * math.sin(math.pi * 0.5 * min(1.0, s / 0.8))
        if s > 0.8:
            h *= 0.4 + 0.6 * (1 - s) / 0.2
        b = 0.022 * (1 - 0.5 * s)
        x = laenge / 2 - laenge * s
        ringe.append([(x, -b, -0.01), (x, -b * 0.7, h * 0.6), (x, 0.0, max(h, 0.004)), (x, b * 0.7, h * 0.6),
                      (x, b, -0.01)])
    return netz_aus_ringen("antenne", ringe, mat, kappen=True)


def wischerblatt(name, punkte, normalen, mats):
    """Wischerblatt entlang von Punkten auf der Scheibe: Gummilippe und Träger."""
    teile = []
    lippe = band(name + "_lippe", punkte, normalen, 0.004, 0.008, mats["gummi"])
    if lippe:
        teile.append(lippe)
    oben = [Vector(p) + Vector(n).normalized() * 0.007 for p, n in zip(punkte, normalen)]
    traeger = band(name + "_traeger", oben, normalen, 0.016, 0.008, mats["kunststoff"])
    if traeger:
        teile.append(traeger)
    return teile
