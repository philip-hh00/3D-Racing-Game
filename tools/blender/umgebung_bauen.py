"""Umgebung in Blender bauen: Bäume, Felsen, Häuser, Banden, Berge.

Aufruf (siehe ``tools/blender/bauen.bat``)::

    blender.exe -b -P tools/blender/umgebung_bauen.py
    blender.exe -b -P tools/blender/umgebung_bauen.py -- --nur city/buero_turm_1 --vorschau ordner

Voraussetzungen: ``tools/assets_laden.py`` (CC0-Material von Poly Haven) und
``tools/texturen_erzeugen.py`` (Fassaden, Nadelzweige, Banden).

Ergebnis: ``assets/umgebung/<gruppe>/<name>.glb``, bei aufwendigen Objekten
dazu ``<name>_lod1.glb`` für die Ferne, und ``assets/umgebung/katalog.json``
mit Platzbedarf, Höhe und LOD-Abstand je Objekt. Die Themen unter
``data/themen/`` verweisen auf diese Namen.

Drei Herkünfte:

* **CC0-Modelle** (Felsen, Köcherbäume, Laternen, Hydranten) werden
  importiert, auf Maß gebracht und dezimiert — die Originale haben bis zu
  150 000 Dreiecke, im Spiel stehen davon hunderte.
* **Kartenbäume**: Stamm plus Zweig- oder Blattkarten mit Alphamaske. Einige
  hundert Dreiecke je Baum, die Normalen zeigen von der Krone nach außen,
  damit die Krone wie ein Körper beleuchtet wird und nicht wie ein Stapel
  Papier.
* **Gebäude** als Quader mit Fassadentextur; die Fenster spiegeln über den
  Rauheitskanal den Himmel.

Achsen wie im Spiel: +Z oben, Ursprung mittig am Boden. Objekte, die zur
Strecke ausgerichtet werden (Banden, Tribünen), zeigen mit ihrer Vorderseite
nach **+Y**.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemeinsam as g  # noqa: E402

CC0 = g.WURZEL / "rohdaten" / "cc0" / "modelle"
ERZEUGT = g.WURZEL / "rohdaten" / "erzeugt"
TEX = g.WURZEL / "assets" / "texturen"
ZIEL = g.WURZEL / "assets" / "umgebung"

KATALOG: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def tex_mat(name: str, farbe_bild: Path, mr_bild: Path | None = None,
            maske: bool = False, farbe=(1, 1, 1), rauheit: float = 0.85, metallic: float = 0.0):
    """Material mit Bildtextur. ``maske``: Laub, wird im Spiel ausgestanzt.

    Masken-Materialien enden auf ``_maske`` — daran erkennt der Lader des
    Spiels die Alpha-Maske, unabhängig davon, wie der glTF-Export den
    Alphamodus benennt.
    """
    if maske and not name.endswith("_maske"):
        name += "_maske"
    m = g.material(name, farbe, metallic, rauheit, bild=str(farbe_bild),
                   bild_mr=str(mr_bild) if mr_bild else None)
    if maske:
        bsdf = m.node_tree.nodes["Principled BSDF"]
        tex = [n for n in m.node_tree.nodes if n.type == "TEX_IMAGE"][0]
        m.node_tree.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        try:
            m.surface_render_method = "DITHERED"
        except AttributeError:                      # pragma: no cover
            m.blend_method = "CLIP"
    return m


def wand(name: str):
    return tex_mat(name, TEX / f"{name}_farbe.jpg", TEX / f"{name}_mr.png")


def fassade(name: str):
    return tex_mat(f"fassade_{name}", ERZEUGT / f"fassade_{name}.jpg",
                   ERZEUGT / f"fassade_{name}_mr.png")


def farbe(name: str, rgb, rauheit: float = 0.6, metallic: float = 0.0, **kw):
    return g.material(name, [c / 255 for c in rgb], metallic, rauheit, **kw)


# ---------------------------------------------------------------------------
# Netzhelfer
# ---------------------------------------------------------------------------

def kasten(name, mitte, groesse, mat, drehung_z: float = 0.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(groesse), verts=bm.verts)
    if drehung_z:
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                         matrix=Matrix.Rotation(drehung_z, 3, "Z"))
    bmesh.ops.translate(bm, vec=Vector(mitte), verts=bm.verts)
    return g.objekt_aus(bm, name, [mat])


def zylinder(name, mitte, r_unten, r_oben, hoehe, mat, segmente=12, kappen=True, achse="Z"):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=kappen, cap_tris=False, segments=segmente,
                          radius1=r_unten, radius2=r_oben, depth=hoehe)
    if achse == "X":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "Y"))
    elif achse == "Y":
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.pi / 2, 3, "X"))
    bmesh.ops.translate(bm, vec=Vector(mitte), verts=bm.verts)
    ob = g.objekt_aus(bm, name, [mat])
    return ob


def uv_kasten(ob, kachel_m: float = 2.0, fassade_b: float | None = None,
              fassade_h: float | None = None, z0: float = 0.0) -> None:
    """Weltbezogene Würfelprojektion.

    Mit ``fassade_b``/``fassade_h`` bekommen senkrechte Flächen je
    Fensterachse und Geschoss genau eine Kachel — die Fassadentextur ist so
    gebaut.
    """
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new()
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.active
    for f in bm.faces:
        n = f.normal
        for l in f.loops:
            p = ob.matrix_world @ l.vert.co
            if abs(n.z) > 0.6:
                l[uv].uv = (p.x / kachel_m, p.y / kachel_m)
            else:
                waagerecht = p.y if abs(n.x) > abs(n.y) else p.x
                if n.x < -0.5 or n.y > 0.5:
                    waagerecht = -waagerecht
                if fassade_b:
                    l[uv].uv = (waagerecht / fassade_b, (p.z - z0) / fassade_h)
                else:
                    l[uv].uv = (waagerecht / kachel_m, p.z / kachel_m)
    bm.to_mesh(me)
    bm.free()


def uv_zylinder(ob, umfang_kacheln: float = 2.0, hoehe_m: float = 2.0) -> None:
    me = ob.data
    if not me.uv_layers:
        me.uv_layers.new()
    bm = bmesh.new()
    bm.from_mesh(me)
    uv = bm.loops.layers.uv.active
    for f in bm.faces:
        mitte_w = math.atan2(f.calc_center_median().y, f.calc_center_median().x)
        for l in f.loops:
            w = math.atan2(l.vert.co.y, l.vert.co.x)
            if w - mitte_w > math.pi:
                w -= 2 * math.pi
            elif mitte_w - w > math.pi:
                w += 2 * math.pi
            l[uv].uv = (w / (2 * math.pi) * umfang_kacheln, l.vert.co.z / hoehe_m)
    bm.to_mesh(me)
    bm.free()


def normalen_von(ob, mitte, abflachung: float = 1.0) -> None:
    """Normalen radial von ``mitte`` weg — für Kronen aus Karten."""
    me = ob.data
    mitte = Vector(mitte)
    normalen = []
    for l in me.loops:
        p = me.vertices[l.vertex_index].co
        d = p - mitte
        d.z *= abflachung
        d.z += 0.35 * d.length
        normalen.append(d.normalized() if d.length > 1e-6 else Vector((0, 0, 1)))
    if hasattr(me, "use_auto_smooth"):                # Blender < 4.1
        me.use_auto_smooth = True
    me.normals_split_custom_set(normalen)


def karte(bm, mitte, richtung, oben, laenge, breite, uv0=(0, 0), uv1=(1, 1),
          haengen: float = 0.0, segmente: int = 2):
    """Eine Karte von ``mitte`` in ``richtung``, optional durchhängend."""
    richtung = Vector(richtung).normalized()
    quer = richtung.cross(Vector(oben)).normalized() * breite / 2
    reihe = []
    for s in range(segmente + 1):
        t = s / segmente
        p = Vector(mitte) + richtung * laenge * t - Vector((0, 0, haengen * t * t * laenge))
        u = uv0[0] + (uv1[0] - uv0[0]) * t
        reihe.append((bm.verts.new(p - quer), bm.verts.new(p + quer), u))
    uvl = bm.loops.layers.uv.verify()
    for s in range(segmente):
        a0, a1, ua = reihe[s]
        b0, b1, ub = reihe[s + 1]
        f = bm.faces.new((a0, b0, b1, a1))
        for l, w in zip(f.loops, ((ua, uv0[1]), (ub, uv0[1]), (ub, uv1[1]), (ua, uv1[1]))):
            l[uvl].uv = w


def boden_ab(ob, versenken: float = 0.0) -> None:
    """Ursprung mittig unten, Unterkante auf z = -versenken."""
    g.transform_anwenden(ob)
    vs = [v.co for v in ob.data.vertices]
    mx = (min(v.x for v in vs) + max(v.x for v in vs)) / 2
    my = (min(v.y for v in vs) + max(v.y for v in vs)) / 2
    mz = min(v.z for v in vs)
    ob.data.transform(Matrix.Translation((-mx, -my, -mz - versenken)))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def uv_vereinheitlichen(objekte) -> None:
    """Genau eine UV-Ebene je Objekt, immer ``UVMap`` genannt.

    Beim Verbinden führt Blender UV-Ebenen **nach Namen** zusammen. Heißt die
    Ebene der Blattkarten anders als die des Stamms, landen die Blätter in
    ``TEXCOORD_1`` und haben in ``TEXCOORD_0`` lauter Nullen — im Spiel wird
    dann jeder Punkt der Karte an derselben, durchsichtigen Ecke der Textur
    abgetastet und die Krone verschwindet.
    """
    for o in objekte:
        if o is None or o.type != "MESH":
            continue
        ebenen = o.data.uv_layers
        if not ebenen:
            ebenen.new(name="UVMap")
            continue
        aktiv = ebenen.active or ebenen[0]
        for e in list(ebenen):
            if e.name != aktiv.name:
                ebenen.remove(e)
        ebenen[0].name = "UVMap"


def exportieren(schluessel: str, objekte, lod1=None, lod_abstand_m: float = 80.0,
                schatten: bool = True, radius_m: float | None = None) -> None:
    uv_vereinheitlichen(objekte)
    uv_vereinheitlichen(lod1 or [])
    ob = g.verbinden([o for o in objekte if o is not None], schluessel.split("/")[-1])
    vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
    b = max(max(v.x for v in vs) - min(v.x for v in vs), max(v.y for v in vs) - min(v.y for v in vs))
    h = max(v.z for v in vs)
    g.glb_schreiben(ZIEL / f"{schluessel}.glb", [ob])
    eintrag = {"radius_m": round(radius_m if radius_m else b / 2 * 0.8, 2),
               "hoehe_m": round(h, 2), "dreiecke": g.dreiecke(ob), "schatten": schatten,
               # Grundriss am Boden, Modellraum [x_min, x_max, y_min, y_max]:
               # damit prüft die Platzierung, dass nichts auf die Fahrbahn ragt
               # (für ältere Modelle ergänzt tools/katalog_grundrisse.py).
               "grundriss_m": [math.floor(min(v.x for v in vs) * 100) / 100,
                               math.ceil(max(v.x for v in vs) * 100) / 100,
                               math.floor(min(v.y for v in vs) * 100) / 100,
                               math.ceil(max(v.y for v in vs) * 100) / 100]}
    if lod1 is not None:
        lob = g.verbinden([o for o in lod1 if o is not None], ob.name + "_lod1")
        g.glb_schreiben(ZIEL / f"{schluessel}_lod1.glb", [lob])
        eintrag["lod1"] = True
        eintrag["lod_abstand_m"] = lod_abstand_m
        eintrag["dreiecke_lod1"] = g.dreiecke(lob)
        bpy.data.objects.remove(lob, do_unlink=True)
    KATALOG[schluessel] = eintrag
    g.json_schreiben(ZIEL / "katalog.json", dict(sorted(KATALOG.items())))
    print(f"[umgebung] {schluessel}: {eintrag}")


def kopie(ob, name):
    neu = ob.copy()
    neu.data = ob.data.copy()
    neu.name = name
    bpy.context.scene.collection.objects.link(neu)
    return neu


def dezimieren(ob, ziel_dreiecke: int) -> None:
    # Mehrere Anläufe: an UV-Nähten bremst der Collapse, ein zweiter Durchgang
    # mit dem Rest-Verhältnis kommt dann doch ans Ziel.
    for _ in range(4):
        ist = g.dreiecke(ob)
        if ist <= ziel_dreiecke * 1.15:
            return
        mod = ob.modifiers.new("dezimieren", "DECIMATE")
        mod.ratio = max(0.001, ziel_dreiecke / ist)
        mod.use_collapse_triangulate = True
        g.modifikator_anwenden(ob, mod)
    if g.dreiecke(ob) > ziel_dreiecke * 1.5:
        mod = ob.modifiers.new("dezimieren", "DECIMATE")
        mod.decimate_type = "UNSUBDIV"
        mod.iterations = 2
        g.modifikator_anwenden(ob, mod)


# ---------------------------------------------------------------------------
# CC0-Modelle
# ---------------------------------------------------------------------------

def cc0(asset: str, objekte=None, hoehe_m: float | None = None, skala: float | None = None,
        dreiecke: int = 3000, dreiecke_lod1: int = 500, bildgroesse: int = 512,
        versenken: float = 0.0, liegend: bool = False):
    """Ein Poly-Haven-Modell importieren, auf Maß bringen und vereinfachen.

    ``objekte``: Indizes der gewünschten Teilobjekte (nach Namen sortiert) —
    viele Sets liefern mehrere Varianten nebeneinander.
    """
    vorher = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(CC0 / asset / f"{asset}.gltf"))
    neu = [o for o in bpy.data.objects if o not in vorher]
    netze = sorted([o for o in neu if o.type == "MESH"], key=lambda o: o.name)
    wahl = netze if objekte is None else [netze[i] for i in objekte]
    for o in neu:
        if o not in wahl:
            if o.type == "MESH" or o.type == "EMPTY":
                pass
    for o in wahl:
        o.matrix_world = o.matrix_world.copy()
    # Eltern lösen, Transformationen einbacken.
    for o in wahl:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
    for o in neu:
        if o not in wahl:
            bpy.data.objects.remove(o, do_unlink=True)
    ob = g.verbinden(wahl, asset)
    g.transform_anwenden(ob)
    if liegend:
        ob.data.transform(Matrix.Rotation(math.pi / 2, 4, "X"))
    boden_ab(ob, 0.0)
    vs = [v.co for v in ob.data.vertices]
    h = max(v.z for v in vs)
    s = skala if skala else (hoehe_m / h if hoehe_m else 1.0)
    ob.data.transform(Matrix.Scale(s, 4))
    ob.data.transform(Matrix.Translation((0, 0, -versenken * h * s)))
    # Materialien: undurchsichtig, ohne Normalenkarten, kleinere Bilder.
    for m in ob.data.materials:
        if m is None or not m.use_nodes:
            continue
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        for n in list(m.node_tree.nodes):
            if n.type == "NORMAL_MAP":
                m.node_tree.nodes.remove(n)
        if bsdf is not None:
            for l in list(bsdf.inputs["Alpha"].links):
                m.node_tree.links.remove(l)
            bsdf.inputs["Alpha"].default_value = 1.0
        try:
            m.surface_render_method = "DITHERED"
        except AttributeError:                      # pragma: no cover
            m.blend_method = "OPAQUE"
        for n in m.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                if "nor" in n.image.name.lower():
                    m.node_tree.nodes.remove(n)
                    continue
                if n.image.size[0] > bildgroesse:
                    n.image.scale(bildgroesse, bildgroesse)
    # Der glTF-Import trennt die Punkte an jeder UV-Naht. Bei Fotogrammetrie
    # sind das tausende Inseln, und der Collapse kommt über keine Naht
    # hinweg. Zusammenführen — die UV bleiben je Ecke erhalten.
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
    bm.to_mesh(ob.data)
    bm.free()
    lod = kopie(ob, asset + "_lod1")
    dezimieren(ob, dreiecke)
    dezimieren(lod, dreiecke_lod1)
    for o in (ob, lod):
        for p in o.data.polygons:
            p.use_smooth = True
    return ob, lod


# ---------------------------------------------------------------------------
# Bäume und Pflanzen
# ---------------------------------------------------------------------------

def stamm(name, hoehe, r_unten, r_oben, mat, segmente=8, versatz=(0, 0, 0)):
    ob = zylinder(name, (0, 0, hoehe / 2), r_unten, r_oben, hoehe, mat, segmente, kappen=False)
    uv_zylinder(ob, 1.0, 2.0)
    ob.data.transform(Matrix.Translation(versatz))
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def tanne(name: str, hoehe: float, radius: float, seed: int, zweig="nadelzweig",
          dichte: float = 1.0):
    rng = random.Random(seed)
    rinde = wand("rinde")
    nadel = tex_mat(f"laub_{zweig}", ERZEUGT / f"{zweig}.png", maske=True, rauheit=0.85)
    teile = [stamm("stamm", hoehe * 0.95, radius * 0.07 + 0.08, 0.03, rinde)]
    bm = bmesh.new()
    unten = max(1.2, hoehe * 0.16)
    etagen = max(4, int((hoehe - unten) / 0.55 * dichte))
    for k in range(etagen):
        t = k / (etagen - 1)
        z = unten + (hoehe - unten - 0.4) * t
        r = radius * (1 - t) ** 0.9 + 0.35
        anzahl = max(4, int((5 + 5 * (1 - t)) * dichte))
        start = rng.uniform(0, 2 * math.pi)
        for a in range(anzahl):
            w = start + 2 * math.pi * a / anzahl + rng.uniform(-0.2, 0.2)
            neigung = rng.uniform(-0.35, -0.1)
            richtung = Vector((math.cos(w), math.sin(w), neigung))
            oben = Vector((0, 0, 1)) + Vector((rng.uniform(-.3, .3), rng.uniform(-.3, .3), 0))
            karte(bm, (0, 0, z), richtung, oben, r * rng.uniform(1.0, 1.2), r * 0.75,
                  haengen=rng.uniform(0.05, 0.2), segmente=2)
    # Spitze: zwei gekreuzte, stehende Karten.
    for w in (0.0, math.pi / 2):
        karte(bm, (0, 0, hoehe - 1.3), (0, 0, 1), (math.cos(w), math.sin(w), 0), 1.4, 0.9, segmente=1)
    krone = g.objekt_aus(bm, "krone", [nadel])
    normalen_von(krone, (0, 0, hoehe * 0.35), 0.6)
    return teile + [krone]


def laubbaum(name: str, hoehe: float, kronen_r: float, seed: int, blatt="blatt_laub",
             karten: int = 90, rinden_mat=None):
    rng = random.Random(seed)
    rinde = rinden_mat or wand("rinde")
    laub = tex_mat(f"laub_{blatt}", ERZEUGT / f"{blatt}.png", maske=True, rauheit=0.8)
    stamm_h = hoehe - kronen_r * 1.3
    teile = [stamm("stamm", stamm_h + kronen_r * 0.5, 0.18 + hoehe * 0.012, 0.08, rinde)]
    mitte = Vector((0, 0, hoehe - kronen_r))
    for a in range(4):
        w = a * math.pi / 2 + rng.uniform(-0.4, 0.4)
        ast = zylinder("ast", (0, 0, 0), 0.09, 0.03, kronen_r * 1.1, rinde, 6, kappen=False)
        ast.data.transform(Matrix.Translation((0, 0, kronen_r * 0.55)))
        ast.data.transform(Matrix.Rotation(math.radians(rng.uniform(35, 55)), 4, "Y"))
        ast.data.transform(Matrix.Rotation(w, 4, "Z"))
        ast.data.transform(Matrix.Translation((0, 0, stamm_h * 0.85)))
        teile.append(ast)
    bm = bmesh.new()
    for _ in range(karten):
        # Punkt nahe der Hülle eines abgeflachten Ellipsoids.
        while True:
            p = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)))
            if 0.35 < p.length <= 1.0:
                break
        p = p.normalized() * (0.55 + 0.45 * p.length)
        pos = mitte + Vector((p.x * kronen_r, p.y * kronen_r, p.z * kronen_r * 0.75))
        aussen = (pos - mitte).normalized()
        richtung = (aussen + Vector((rng.uniform(-.6, .6), rng.uniform(-.6, .6), rng.uniform(-.4, .2)))).normalized()
        oben = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 1.0))
        groesse = kronen_r * rng.uniform(0.7, 1.0)
        start = pos - richtung * groesse * 0.5
        karte(bm, start, richtung, oben, groesse, groesse, segmente=1)
    krone = g.objekt_aus(bm, "krone", [laub])
    normalen_von(krone, mitte, 0.8)
    return teile + [krone]


def busch(name: str, radius: float, seed: int, blatt="blatt_busch", karten: int = 26):
    rng = random.Random(seed)
    laub = tex_mat(f"laub_{blatt}", ERZEUGT / f"{blatt}.png", maske=True, rauheit=0.8)
    bm = bmesh.new()
    mitte = Vector((0, 0, radius * 0.45))
    for _ in range(karten):
        w = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(0.1, 0.8) * radius
        pos = Vector((math.cos(w) * r, math.sin(w) * r, rng.uniform(0.0, radius * 0.7)))
        richtung = Vector((math.cos(w), math.sin(w), rng.uniform(0.3, 1.0))).normalized()
        groesse = radius * rng.uniform(0.8, 1.2)
        karte(bm, pos - richtung * groesse * 0.35, richtung,
              Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0.5)), groesse, groesse, segmente=1)
    ob = g.objekt_aus(bm, "busch", [laub])
    normalen_von(ob, mitte, 0.7)
    return [ob]


def kaktus(name: str, hoehe: float, seed: int):
    """Saguaro: gerippter Stamm, ein bis drei Arme."""
    rng = random.Random(seed)
    gruen = farbe("kaktus", (74, 104, 58), 0.7)

    def saeule(r, h, basis, kappe=True):
        bm = bmesh.new()
        rippen = 12
        ringe = max(3, int(h / 0.25))
        verts = []
        for k in range(ringe + 1):
            z = h * k / ringe
            spitze = max(0.0, (z - (h - r)) / r) if kappe else 0.0
            rr = r * math.sqrt(max(0.0, 1 - spitze ** 2))
            ring = []
            for i in range(rippen * 2):
                w = math.pi * i / rippen
                rad = rr * (1.0 if i % 2 == 0 else 0.86)
                ring.append(bm.verts.new((basis[0] + math.cos(w) * rad, basis[1] + math.sin(w) * rad,
                                          basis[2] + z)))
            verts.append(ring)
        n = rippen * 2
        for k in range(ringe):
            for i in range(n):
                bm.faces.new((verts[k][i], verts[k][(i + 1) % n], verts[k + 1][(i + 1) % n], verts[k + 1][i]))
        ob = g.objekt_aus(bm, "saeule", [gruen])
        for p in ob.data.polygons:
            p.use_smooth = True
        return ob

    r = 0.22 + hoehe * 0.02
    teile = [saeule(r, hoehe, (0, 0, 0))]
    for a in range(rng.randint(1, 3)):
        w = rng.uniform(0, 2 * math.pi)
        z = hoehe * rng.uniform(0.35, 0.6)
        weg = r * 2.2
        x, y = math.cos(w) * weg, math.sin(w) * weg
        quer = zylinder("arm_quer", (weg / 2, 0, 0), r * 0.7, r * 0.7, weg, gruen, 12, achse="X")
        quer.data.transform(Matrix.Rotation(w, 4, "Z"))
        quer.data.transform(Matrix.Translation((0, 0, z)))
        for poly in quer.data.polygons:
            poly.use_smooth = True
        teile.append(quer)
        teile.append(saeule(r * 0.7, hoehe * rng.uniform(0.25, 0.4), (x, y, z - r * 0.3)))
    return teile


# ---------------------------------------------------------------------------
# Gebäude
# ---------------------------------------------------------------------------

def gebaeude(breite: float, tiefe: float, geschosse: int, fassaden_name: str,
             geschoss_h: float = 3.1, achse_b: float = 3.0, dach: str = "flach",
             dach_mat=None, sockel_mat=None, seed: int = 0):
    rng = random.Random(seed)
    h = geschosse * geschoss_h
    teile = []
    korpus = kasten("korpus", (0, 0, h / 2), (breite, tiefe, h), fassade(fassaden_name))
    uv_kasten(korpus, fassade_b=achse_b, fassade_h=geschoss_h)
    teile.append(korpus)
    if sockel_mat is not None:
        sockel = kasten("sockel", (0, 0, 0.35), (breite + 0.08, tiefe + 0.08, 0.7), sockel_mat)
        uv_kasten(sockel, 1.5)
        teile.append(sockel)
    if dach == "flach":
        rand = wand("betonwand")
        d = 0.25
        for (m, s) in (((0, tiefe / 2 - d / 2, h + 0.4), (breite, d, 0.8)),
                       ((0, -tiefe / 2 + d / 2, h + 0.4), (breite, d, 0.8)),
                       ((breite / 2 - d / 2, 0, h + 0.4), (d, tiefe, 0.8)),
                       ((-breite / 2 + d / 2, 0, h + 0.4), (d, tiefe, 0.8))):
            k = kasten("attika", m, s, rand)
            uv_kasten(k, 2.0)
            teile.append(k)
        blech = farbe("dachtechnik", (150, 152, 155), 0.45, 0.6)
        for _ in range(rng.randint(1, 3)):
            bb, tt = rng.uniform(1.5, 3.5), rng.uniform(1.5, 3.0)
            x = rng.uniform(-breite / 2 + bb, breite / 2 - bb)
            y = rng.uniform(-tiefe / 2 + tt, tiefe / 2 - tt)
            teile.append(kasten("technik", (x, y, h + 0.7), (bb, tt, 1.4), blech))
        teile.append(kasten("dachflaeche", (0, 0, h + 0.02), (breite - 0.1, tiefe - 0.1, 0.04),
                            farbe("dachpappe", (60, 60, 62), 0.9)))
    else:
        first = min(breite, tiefe) * 0.38
        bm = bmesh.new()
        ueber = 0.5
        b2, t2 = breite / 2 + ueber, tiefe / 2 + ueber
        v = [bm.verts.new(p) for p in ((-b2, -t2, h), (b2, -t2, h), (b2, t2, h), (-b2, t2, h),
                                        (-b2, 0, h + first), (b2, 0, h + first))]
        bm.faces.new((v[0], v[1], v[5], v[4]))
        bm.faces.new((v[2], v[3], v[4], v[5]))
        dachob = g.objekt_aus(bm, "dach", [dach_mat or wand("dachziegel")])
        mod = dachob.modifiers.new("dicke", "SOLIDIFY")
        mod.thickness = 0.18
        g.modifikator_anwenden(dachob, mod)
        uv_kasten(dachob, 3.0)
        # Giebeldreiecke in der Fassade.
        bm = bmesh.new()
        for x in (-breite / 2, breite / 2):
            a = bm.verts.new((x, -tiefe / 2, h))
            b = bm.verts.new((x, tiefe / 2, h))
            c = bm.verts.new((x, 0, h + first * (tiefe / 2) / t2))
            bm.faces.new((a, b, c) if x > 0 else (b, a, c))
        giebel = g.objekt_aus(bm, "giebel", [wand("putz") if "holz" not in fassaden_name else fassade(fassaden_name)])
        uv_kasten(giebel, 3.0)
        teile += [dachob, giebel]
    return teile


def buero_turm(name, breite, tiefe, hoehe, fassaden_name, seed):
    rng = random.Random(seed)
    geschoss = 3.6
    geschosse = max(4, int(hoehe / geschoss))
    teile = gebaeude(breite, tiefe, geschosse, fassaden_name, geschoss_h=geschoss,
                     achse_b=3.0, dach="flach", seed=seed)
    # Ein zurückgesetzter Aufbau oben, damit die Silhouette nicht nur ein Quader ist.
    if rng.random() < 0.7:
        h = geschosse * geschoss
        auf = kasten("aufbau", (0, 0, h + 3.0), (breite * 0.55, tiefe * 0.55, 6.0), fassade(fassaden_name))
        uv_kasten(auf, fassade_b=3.0, fassade_h=geschoss, z0=h)
        teile.append(auf)
    return teile


# ---------------------------------------------------------------------------
# Streckenrand
# ---------------------------------------------------------------------------

def reifen(name, mitte, mat, weiss=None):
    bpy.ops.mesh.primitive_torus_add(major_radius=0.3, minor_radius=0.11, major_segments=20,
                                     minor_segments=8, location=mitte)
    ob = bpy.context.object
    ob.name = name
    ob.scale = (1, 1, 0.9)
    g.transform_anwenden(ob)
    ob.data.materials.append(weiss if weiss else mat)
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def reifenstapel():
    gummi = farbe("gummi", (22, 22, 24), 0.9)
    weiss = farbe("reifen_weiss", (230, 230, 228), 0.7)
    rot = farbe("reifen_rot", (200, 30, 30), 0.7)
    teile = []
    for i, x in enumerate((-0.62, 0.0, 0.62)):
        for k in range(4):
            mat = gummi
            if k == 3:
                mat = weiss if i % 2 == 0 else rot
            teile.append(reifen("reifen", (x, 0, 0.1 + k * 0.2), gummi, mat if k == 3 else None))
    lod = [kasten("stapel", (0, 0, 0.4), (1.86, 0.62, 0.8), gummi)]
    return teile, lod


def werbebande(index: int):
    bild = ERZEUGT / f"bande_{index}.jpg"
    front = tex_mat(f"bande_{index}", bild, rauheit=0.45)
    ruecken = farbe("bandengestell", (70, 72, 75), 0.5, 0.6)
    teile = []
    tafel = kasten("tafel", (0, 0, 0.75), (6.0, 0.08, 1.0), ruecken)
    teile.append(tafel)
    bm = bmesh.new()
    v = [bm.verts.new(p) for p in ((-3.0, 0.045, 0.25), (3.0, 0.045, 0.25), (3.0, 0.045, 1.25), (-3.0, 0.045, 1.25))]
    f = bm.faces.new(v)
    uvl = bm.loops.layers.uv.verify()
    # Von vorn (+Y) gesehen läuft +X nach links: u deshalb von rechts nach
    # links, sonst steht die Schrift spiegelverkehrt.
    for l, w in zip(f.loops, ((1, 0), (0, 0), (0, 1), (1, 1))):
        l[uvl].uv = w
    teile.append(g.objekt_aus(bm, "werbung", [front]))
    for x in (-2.6, 2.6):
        teile.append(kasten("fuss", (x, -0.15, 0.25), (0.08, 0.5, 0.5), ruecken))
    return teile


def tribuene():
    beton = wand("betonwand")
    sitze = [farbe(f"sitz_{i}", c, 0.5) for i, c in enumerate(((200, 30, 30), (230, 230, 230), (30, 60, 160)))]
    kleidung = [farbe(f"zuschauer_{i}", c, 0.8) for i, c in enumerate((
        (180, 40, 40), (40, 60, 150), (230, 230, 220), (30, 30, 32), (230, 190, 40), (60, 130, 70), (210, 120, 60)))]
    rng = random.Random(7)
    teile = []
    laenge, stufen = 36.0, 10
    for s in range(stufen):
        y = -s * 0.85
        z = s * 0.5
        k = kasten("stufe", (0, y - 0.425, z / 2 + 0.25), (laenge, 0.85, z + 0.5), beton)
        uv_kasten(k, 2.0)
        teile.append(k)
        teile.append(kasten("sitzreihe", (0, y - 0.55, z + 0.62), (laenge - 1, 0.45, 0.25), sitze[s % 3]))
        for i in range(int(laenge / 0.55)):
            if rng.random() < 0.55:
                x = -laenge / 2 + 0.6 + i * 0.55
                teile.append(kasten("zuschauer", (x, y - 0.55, z + 1.0), (0.42, 0.3, 0.6), rng.choice(kleidung)))
                teile.append(kasten("kopf", (x, y - 0.55, z + 1.42), (0.2, 0.22, 0.24),
                                    farbe("haut", (205, 160, 125), 0.7)))
    hinten = -stufen * 0.85
    wandob = kasten("rueckwand", (0, hinten - 0.2, stufen * 0.5 / 2 + 2.0), (laenge, 0.4, stufen * 0.5 + 4.0), beton)
    uv_kasten(wandob, 2.0)
    teile.append(wandob)
    dachh = stufen * 0.5 + 4.2
    dach = kasten("dach", (0, hinten / 2, dachh), (laenge + 1, -hinten + 2.5, 0.25),
                  farbe("tribuenendach", (225, 228, 232), 0.35, 0.3))
    teile.append(dach)
    stahl = farbe("stahl", (90, 92, 96), 0.4, 0.8)
    for x in range(-16, 17, 8):
        teile.append(kasten("stuetze", (x, hinten - 0.1, dachh / 2), (0.3, 0.3, dachh), stahl))
    for t in teile:
        t.data.transform(Matrix.Translation((0, -hinten / 2, 0)))
    return teile


def startbruecke(spannweite: float = 27.0):
    """Portal über der Start-/Ziellinie, quer entlang lokal X, Banner nach ±Y.

    Gitterstützen, Traverse mit Banner auf beiden Seiten und eine
    Startampel. Die Spannweite reicht über die breiteste Strecke samt
    Begrenzung; auf schmaleren Strecken stehen die Stützen etwas weiter weg.
    """
    stahl = farbe("portal_stahl", (60, 62, 68), 0.4, 0.8)
    rot = farbe("ampel_rot", (200, 20, 20), 0.3, emission=(1.0, 0.1, 0.05), staerke=2.0)
    dunkel = farbe("ampel_gehaeuse", (15, 15, 17), 0.5)
    banner = tex_mat("startbanner", ERZEUGT / "startbanner.jpg", rauheit=0.5)
    teile = []
    halb = spannweite / 2
    hoehe = 7.5
    for x in (-halb, halb):
        for dx in (-0.35, 0.35):
            for dy in (-0.35, 0.35):
                teile.append(kasten("stuetze", (x + dx, dy, hoehe / 2), (0.14, 0.14, hoehe), stahl))
        for z in range(1, 8):
            teile.append(kasten("strebe", (x, 0, z * hoehe / 8), (0.8, 0.8, 0.06), stahl))
        teile.append(kasten("fuss", (x, 0, 0.15), (1.4, 1.4, 0.3), farbe("beton", (150, 150, 148), 0.9)))
    teile.append(kasten("traverse", (0, 0, hoehe + 0.6), (spannweite + 1.0, 0.9, 1.9), stahl))
    for seite in (1, -1):
        bm = bmesh.new()
        y = seite * 0.46
        v = [bm.verts.new(p) for p in ((-halb + 1, y, hoehe - 0.2), (halb - 1, y, hoehe - 0.2),
                                        (halb - 1, y, hoehe + 1.4), (-halb + 1, y, hoehe + 1.4))]
        f = bm.faces.new(v if seite > 0 else list(reversed(v)))
        uvl = bm.loops.layers.uv.verify()
        ecken = ((1, 0), (0, 0), (0, 1), (1, 1)) if seite > 0 else ((0, 1), (1, 1), (1, 0), (0, 0))
        for l, w in zip(f.loops, ecken):
            l[uvl].uv = w
        teile.append(g.objekt_aus(bm, "banner", [banner]))
    # Startampel: fünf Lampenpaare in der Mitte unter der Traverse.
    teile.append(kasten("ampel", (0, 0, hoehe - 0.7), (3.2, 0.5, 0.8), dunkel))
    for i in range(5):
        for seite in (1, -1):
            lampe = zylinder("lampe", (-1.28 + i * 0.64, seite * 0.26, hoehe - 0.7), 0.2, 0.2, 0.04,
                             rot, 16, achse="Y")
            teile.append(lampe)
    return teile


def zaun():
    holz = wand("holz")
    teile = []
    for x in (-2.0, 0.0, 2.0):
        k = kasten("pfosten", (x, 0, 0.6), (0.12, 0.12, 1.2), holz)
        uv_kasten(k, 1.0)
        teile.append(k)
    for z in (0.45, 0.95):
        k = kasten("latte", (0, 0, z), (4.1, 0.05, 0.14), holz)
        uv_kasten(k, 1.0)
        teile.append(k)
    return teile


def heuballen():
    heu = tex_mat("heu", ERZEUGT / "heu.jpg", rauheit=0.95)
    ob = zylinder("ballen", (0, 0, 0.7), 0.7, 0.7, 1.2, heu, 20, achse="Y")
    uv_kasten(ob, 1.0)
    for p in ob.data.polygons:
        p.use_smooth = True
    return [ob]


def windrad():
    weiss = farbe("windrad", (235, 237, 240), 0.35)
    teile = [zylinder("turm", (0, 0, 40), 2.0, 1.2, 80, weiss, 16)]
    teile.append(kasten("gondel", (0.8, 0, 81), (6, 2.6, 2.6), weiss))
    for k in range(3):
        blatt = kasten("blatt", (0, 0, 19), (0.3, 1.6, 38), weiss)
        blatt.data.transform(Matrix.Rotation(k * 2 * math.pi / 3 + 0.3, 4, "X"))
        blatt.data.transform(Matrix.Translation((-2.4, 0, 81)))
        teile.append(blatt)
    return teile


# ---------------------------------------------------------------------------
# Streckenobjekte (Strang S): Tribüne mit Publikum, Boxen, Posten, Fangzaun,
# Hütchen, Flaggen, Kameraturm. Vorderseite nach +Y, zur Strecke.
# ---------------------------------------------------------------------------

def tafel(name, ecken, mat, uv=((0, 0), (1, 0), (1, 1), (0, 1))):
    """Ein Viereck mit UV — Schilder, Karten, Netzflächen."""
    bm = bmesh.new()
    v = [bm.verts.new(p) for p in ecken]
    f = bm.faces.new(v)
    uvl = bm.loops.layers.uv.verify()
    for l, w in zip(f.loops, uv):
        l[uvl].uv = w
    return g.objekt_aus(bm, name, [mat])


def _atlas_uv(k: int, spalten: int = 4, zeilen: int = 4):
    """UV-Ecken der Figur ``k`` im Publikumsbild (Zeile 0 oben im Bild)."""
    s, z = k % spalten, k // spalten
    u0, u1 = s / spalten, (s + 1) / spalten
    v1 = 1.0 - z / zeilen
    v0 = v1 - 1.0 / zeilen
    return ((u0, v0), (u1, v0), (u1, v1), (u0, v1))


def tribuene_publikum(laenge: float = 30.0, reihen: int = 9, seed: int = 3):
    """Tribüne mit Dach und Publikum aus Karten.

    Jeder Platz ist eine Karte mit einer von 16 Figuren (siehe
    ``texturen_erzeugen.publikum``), zufällig gewählt und leicht versetzt —
    so gibt es Farbvariation ohne je Zuschauer ein eigenes Material. Zwei
    Dreiecke je Kopf: 300 Zuschauer kosten weniger als ein Baum.
    """
    rng = random.Random(seed)
    beton = wand("betonwand")
    sitzfarben = [farbe(f"tribuene_sitz_{i}", c, 0.45) for i, c in
                  enumerate(((30, 60, 150), (200, 30, 30), (230, 230, 230)))]
    stahl = farbe("tribuene_stahl", (70, 74, 80), 0.4, 0.8)
    dach_mat = farbe("tribuene_dach", (228, 230, 234), 0.35, 0.3)
    leute = tex_mat("publikum", ERZEUGT / "publikum.png", maske=True, rauheit=0.85)
    teile = []
    stufe_t, stufe_h = 0.85, 0.5
    for s in range(reihen):
        y = -s * stufe_t
        z = s * stufe_h
        k = kasten("stufe", (0, y - stufe_t / 2, z / 2 + 0.25), (laenge, stufe_t, z + 0.5), beton)
        uv_kasten(k, 2.0)
        teile.append(k)
        # Sitzreihe: ein farbiger Block je Reihe, Blöcke im Wechsel.
        teile.append(kasten("sitze", (0, y - 0.6, z + 0.68), (laenge - 1.0, 0.4, 0.36),
                            sitzfarben[(s // 3) % 3]))
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.verify()
    for s in range(reihen):
        y = -s * stufe_t - 0.35
        z = s * stufe_h + 0.5
        x = -laenge / 2 + 0.7
        while x < laenge / 2 - 0.7:
            if rng.random() < 0.8:
                b = rng.uniform(0.52, 0.6)
                h = b * 2.0 * rng.uniform(0.92, 1.06)
                xx = x + rng.uniform(-0.06, 0.06)
                ecken = [(xx + b / 2, y, z), (xx - b / 2, y, z), (xx - b / 2, y, z + h), (xx + b / 2, y, z + h)]
                v = [bm.verts.new(p) for p in ecken]
                f = bm.faces.new(v)
                # Von vorn (+Y) gesehen läuft +X nach links; die erste Ecke
                # (+X) ist deshalb die linke untere des Bildes.
                uvs = _atlas_uv(rng.randrange(16))
                for l, w in zip(f.loops, uvs):
                    l[uvl].uv = w
            x += rng.uniform(0.55, 0.62)
    publikum = g.objekt_aus(bm, "publikum", [leute])
    teile.append(publikum)
    hinten = -reihen * stufe_t
    hoch = reihen * stufe_h
    rueck = kasten("rueckwand", (0, hinten - 0.2, (hoch + 4.2) / 2), (laenge, 0.4, hoch + 4.2), beton)
    uv_kasten(rueck, 2.0)
    teile.append(rueck)
    for x in (-laenge / 2 - 0.2, laenge / 2 + 0.2):
        seite = kasten("seitenwand", (x, hinten / 2, (hoch + 1.0) / 2), (0.4, -hinten + 0.2, hoch + 1.0), beton)
        uv_kasten(seite, 2.0)
        teile.append(seite)
    # Brüstung vorn mit Werbung.
    teile.append(kasten("bruestung", (0, 0.1, 0.55), (laenge, 0.2, 1.1), stahl))
    for i, x in enumerate(range(-int(laenge / 2) + 3, int(laenge / 2) - 2, 6)):
        mat = tex_mat(f"bande_{i % 6}", ERZEUGT / f"bande_{i % 6}.jpg", rauheit=0.45)
        teile.append(tafel("werbung", [(x + 3, 0.205, 0.1), (x - 3, 0.205, 0.1),
                                       (x - 3, 0.205, 1.1), (x + 3, 0.205, 1.1)], mat,
                           uv=((0, 0), (1, 0), (1, 1), (0, 1))))
    # Dach: leicht geneigt, auf Stützen hinten, vorn auskragend.
    dach_h = hoch + 4.0
    bm = bmesh.new()
    d = [bm.verts.new(p) for p in ((-laenge / 2 - 0.6, hinten - 0.5, dach_h), (laenge / 2 + 0.6, hinten - 0.5, dach_h),
                                   (laenge / 2 + 0.6, 1.2, dach_h - 0.9), (-laenge / 2 - 0.6, 1.2, dach_h - 0.9))]
    bm.faces.new(d)
    dach = g.objekt_aus(bm, "dach", [dach_mat])
    mod = dach.modifiers.new("dicke", "SOLIDIFY")
    mod.thickness = 0.25
    g.modifikator_anwenden(dach, mod)
    teile.append(dach)
    for x in range(-int(laenge / 2), int(laenge / 2) + 1, 10):
        teile.append(kasten("stuetze", (x, hinten - 0.25, dach_h / 2), (0.3, 0.3, dach_h), stahl))
        # Schräger Träger unter dem Dach nach vorn.
        traeger = kasten("traeger", (0, 0, 0), (0.18, -hinten + 1.8, 0.3), stahl)
        traeger.data.transform(Matrix.Rotation(math.atan2(0.9, -hinten + 1.7), 4, "X"))
        traeger.data.transform(Matrix.Translation((x, (hinten + 1.2) / 2, dach_h - 0.6)))
        teile.append(traeger)
    for tl in teile:
        tl.data.transform(Matrix.Translation((0, -hinten / 2, 0)))
    return teile


def boxengebaeude(garagen: int = 8, breite_garage: float = 6.0, tiefe: float = 14.0):
    """Boxengebäude an Start und Ziel: Garagen unten, Glasband oben, Schild.

    Offene Tore zeigen einen dunklen Innenraum mit Werkbank, geschlossene ein
    Rolltor aus Wellblech. Darüber Nummern je Box, oben das Band mit dem
    Streckennamen und eine Dachterrasse mit Geländer.
    """
    laenge = garagen * breite_garage
    rng = random.Random(11)
    putz = wand("putz")
    beton = wand("betonwand")
    wellblech = wand("wellblech")
    dunkel = farbe("box_innen", (34, 36, 40), 0.8)
    boden = farbe("box_boden", (120, 122, 126), 0.6)
    scheibe = farbe("box_scheibe", (40, 58, 74), 0.08, 0.1)
    stahl = farbe("box_stahl", (190, 194, 200), 0.35, 0.8)
    rot = farbe("box_rot", (196, 28, 34), 0.45)
    werk = farbe("box_werkbank", (200, 60, 30), 0.5)
    schild = tex_mat("boxenschild", ERZEUGT / "boxenschild.jpg", rauheit=0.4)
    nummern = tex_mat("garagennummern", ERZEUGT / "garagennummern.jpg", rauheit=0.5)
    teile = []
    tor_h, og_h = 4.6, 3.6
    front = tiefe / 2
    # Hauptkörper bis zur Rückwand der Garagen, Decke über den Garagen.
    hinten_y, innen_y = -tiefe / 2, front - 3.2
    korpus = kasten("korpus", (0, (hinten_y + innen_y) / 2, (tor_h + og_h) / 2),
                    (laenge, innen_y - hinten_y, tor_h + og_h), putz)
    uv_kasten(korpus, 3.0)
    teile.append(korpus)
    teile.append(kasten("decke", (0, front - 1.6, tor_h + 0.1), (laenge, 3.2, 0.2), beton))
    teile.append(kasten("og_boden", (0, front - 2.2, tor_h + og_h / 2), (laenge, 2.0, og_h), putz))
    for i in range(garagen):
        x = -laenge / 2 + breite_garage * (i + 0.5)
        # Pfeiler zwischen den Toren.
        pf = kasten("pfeiler", (x - breite_garage / 2 + 0.25, front - 0.5, tor_h / 2), (0.5, 1.0, tor_h), beton)
        uv_kasten(pf, 2.0)
        teile.append(pf)
        offen = rng.random() < 0.6
        # Nische: dunkler Innenraum 3 m tief.
        teile.append(kasten("nische_boden", (x, front - 1.6, 0.02), (breite_garage - 0.5, 3.0, 0.04), boden))
        if offen:
            teile.append(kasten("nische", (x, front - 3.1, tor_h / 2), (breite_garage - 0.5, 0.1, tor_h), dunkel))
            teile.append(kasten("werkbank", (x + rng.uniform(-1.5, 1.5), front - 2.7, 0.5), (1.8, 0.6, 1.0), werk))
            teile.append(kasten("reifen", (x - 2.0, front - 2.6, 0.35), (0.7, 0.7, 0.7),
                                farbe("box_reifen", (20, 20, 22), 0.9)))
            hoehe_tor = tor_h * rng.uniform(0.0, 0.2)
        else:
            hoehe_tor = tor_h
        if hoehe_tor > 0.05:
            tor = kasten("rolltor", (x, front - 0.2, tor_h - hoehe_tor / 2), (breite_garage - 0.5, 0.08, hoehe_tor),
                         wellblech)
            uv_kasten(tor, 2.0)
            teile.append(tor)
        # Nummer über dem Tor.
        u0, u1 = i / 8.0, (i + 1) / 8.0
        teile.append(tafel("nummer", [(x + 0.6, front + 0.01, tor_h + 0.05), (x - 0.6, front + 0.01, tor_h + 0.05),
                                      (x - 0.6, front + 0.01, tor_h + 0.65), (x + 0.6, front + 0.01, tor_h + 0.65)],
                           nummern, uv=((u0, 0), (u1, 0), (u1, 1), (u0, 1))))
    pf = kasten("pfeiler", (laenge / 2 - 0.25, front - 0.5, tor_h / 2), (0.5, 1.0, tor_h), beton)
    uv_kasten(pf, 2.0)
    teile.append(pf)
    # Sturz über den Toren, rote Kante.
    teile.append(kasten("sturz", (0, front - 0.45, tor_h + 0.35), (laenge, 0.9, 0.7), rot))
    # Obergeschoss: Glasband, etwas zurückgesetzt, mit Pfosten.
    teile.append(kasten("glasband", (0, front - 1.2, tor_h + 0.7 + (og_h - 0.7) / 2),
                        (laenge - 0.4, 0.1, og_h - 0.9), scheibe))
    for x in range(int(-laenge / 2), int(laenge / 2) + 1, 3):
        teile.append(kasten("pfosten", (x, front - 1.15, tor_h + 0.7 + (og_h - 0.7) / 2), (0.1, 0.12, og_h - 0.9),
                            stahl))
    # Dach mit Überstand und Schildband vorn.
    dach_h = tor_h + og_h
    teile.append(kasten("dach", (0, 0.2, dach_h + 0.2), (laenge + 1.0, tiefe + 0.4, 0.4), beton))
    teile.append(kasten("schildtraeger", (0, front + 0.35, dach_h + 0.75), (laenge, 0.15, 1.4), stahl))
    teile.append(tafel("schild", [(laenge / 2 - 1, front + 0.44, dach_h + 0.1), (-laenge / 2 + 1, front + 0.44, dach_h + 0.1),
                                  (-laenge / 2 + 1, front + 0.44, dach_h + 1.4), (laenge / 2 - 1, front + 0.44, dach_h + 1.4)],
                       schild, uv=((0, 0), (1, 0), (1, 1), (0, 1))))
    # Geländer der Dachterrasse.
    for y in (-tiefe / 2 + 0.3,):
        teile.append(kasten("gelaender", (0, y, dach_h + 1.4), (laenge, 0.06, 0.06), stahl))
    for x in (-laenge / 2 + 0.3, laenge / 2 - 0.3):
        teile.append(kasten("gelaender", (x, 0, dach_h + 1.4), (0.06, tiefe - 0.6, 0.06), stahl))
    # Vorplatz aus Beton vor den Garagen — die Boxengasse.
    # Ein Bild über die ganze Fläche (texturen_erzeugen.boxengasse): Linien,
    # Boxenfelder und Ölflecken sitzen dort, wo die Garagen sind.
    gasse = tex_mat("boxengasse", ERZEUGT / "boxengasse.jpg", ERZEUGT / "boxengasse_mr.png")
    vb, vt = laenge + 4.0, 8.0
    vorplatz = kasten("vorplatz", (0, front + vt / 2, 0.035), (vb, vt, 0.07), gasse)
    me = vorplatz.data
    me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            u = (co.x + vb / 2) / vb
            v = (co.y - front) / vt
            if poly.normal.z < 0.6:
                # Seiten: nur ein schmaler Streifen am Rand des Bildes.
                v = min(max(v, 0.002), 0.998)
            me.uv_layers[0].data[li].uv = (u, v)
    teile.append(vorplatz)
    # Drei Hütchen vor der ersten Box.
    for k in range(3):
        teile += huetchen_einzeln((-laenge / 2 + 2.0 + k * 1.2, front + 1.6, 0))
    return teile


def huetchen_einzeln(pos):
    orange = farbe("huetchen_orange", (240, 90, 20), 0.55)
    weiss = farbe("huetchen_reflex", (240, 240, 236), 0.3)
    schwarz = farbe("huetchen_fuss", (22, 22, 24), 0.8)
    x, y, z = pos
    teile = [kasten("fuss", (x, y, z + 0.015), (0.38, 0.38, 0.03), schwarz)]
    kegel = zylinder("kegel", (x, y, z + 0.03 + 0.35), 0.16, 0.025, 0.7, orange, 10, kappen=False)
    for p in kegel.data.polygons:
        p.use_smooth = True
    teile.append(kegel)
    for h0, h1 in ((0.30, 0.40), (0.48, 0.55)):
        r0 = 0.16 - (0.16 - 0.025) * h0 / 0.7 + 0.004
        r1 = 0.16 - (0.16 - 0.025) * h1 / 0.7 + 0.004
        band = zylinder("band", (x, y, z + 0.03 + (h0 + h1) / 2), r0, r1, h1 - h0, weiss, 10, kappen=False)
        for p in band.data.polygons:
            p.use_smooth = True
        teile.append(band)
    return teile


def huetchen_gruppe():
    """Drei Hütchen in einer Reihe entlang lokal X."""
    teile = []
    for k in range(3):
        teile += huetchen_einzeln(((k - 1) * 1.1, 0.0, 0.0))
    return teile


def postenhaus():
    """Streckenposten: kleines Häuschen mit Fenstern rundum, Schild und Flaggenhalter."""
    weiss = farbe("posten_weiss", (236, 236, 232), 0.6)
    orange = farbe("posten_orange", (236, 110, 20), 0.5)
    scheibe = farbe("posten_scheibe", (40, 56, 70), 0.08, 0.1)
    stahl = farbe("posten_stahl", (150, 154, 160), 0.4, 0.8)
    gelb = farbe("posten_flagge_gelb", (250, 210, 20), 0.7)
    schild = tex_mat("postenschild", ERZEUGT / "postenschild.jpg", rauheit=0.5)
    b, t_, h = 2.4, 2.0, 2.5
    teile = [kasten("sockel", (0, 0, 0.15), (b + 0.3, t_ + 0.3, 0.3), wand("betonwand")),
             kasten("wand", (0, 0, 0.3 + h / 2), (b, t_, h), weiss),
             kasten("streifen", (0, 0, 0.3 + 0.9), (b + 0.02, t_ + 0.02, 0.18), orange),
             kasten("dach", (0, 0.15, 0.3 + h + 0.1), (b + 0.6, t_ + 0.8, 0.2), orange)]
    # Fensterband vorn und an den Seiten.
    teile.append(kasten("fenster_vorn", (0, t_ / 2 + 0.01, 0.3 + 1.75), (b - 0.4, 0.02, 0.9), scheibe))
    for x in (-b / 2 - 0.01, b / 2 + 0.01):
        teile.append(kasten("fenster_seite", (x, 0.1, 0.3 + 1.75), (0.02, t_ - 0.6, 0.9), scheibe))
    teile.append(tafel("schild", [(0.45, t_ / 2 + 0.03, 0.45), (-0.45, t_ / 2 + 0.03, 0.45),
                                  (-0.45, t_ / 2 + 0.03, 1.1), (0.45, t_ / 2 + 0.03, 1.1)], schild,
                       uv=((0, 0), (1, 0), (1, 1), (0, 1))))
    # Stange mit gerollter gelber Flagge neben dem Häuschen.
    teile.append(zylinder("stange", (b / 2 + 0.4, t_ / 2 - 0.1, 1.3), 0.025, 0.025, 2.6, stahl, 6))
    teile.append(zylinder("flagge", (b / 2 + 0.4, t_ / 2 - 0.1, 2.25), 0.06, 0.06, 0.7, gelb, 6))
    return teile


def fangzaun_feld(laenge: float = 4.0, hoehe: float = 3.4, knick: float = 0.8):
    """Ein Feld Fangzaun entlang lokal X: Pfosten links, Maschendraht mit
    Alphamaske, oben zur Strecke (+Y) abgeknickt, Rohre oben und unten.

    Die Felder werden lückenlos aneinandergesetzt (``platzierung.kette_setzen``);
    der Pfosten am rechten Ende gehört schon zum nächsten Feld.
    """
    netz = tex_mat("fangzaun", ERZEUGT / "fangzaun.png", maske=True, rauheit=0.45, metallic=0.7)
    stahl = farbe("fangzaun_stahl", (120, 124, 130), 0.4, 0.8)
    beton = farbe("fangzaun_fuss", (150, 150, 146), 0.9)
    h = laenge / 2
    teile = [tafel("netz", [(-h, 0, 0.1), (h, 0, 0.1), (h, 0, hoehe), (-h, 0, hoehe)], netz,
                   uv=((0, 0.1), (laenge, 0.1), (laenge, hoehe), (0, hoehe))),
             tafel("netz_knick", [(-h, 0, hoehe), (h, 0, hoehe), (h, knick * 0.8, hoehe + knick * 0.6),
                                  (-h, knick * 0.8, hoehe + knick * 0.6)], netz,
                   uv=((0, 0), (laenge, 0), (laenge, knick), (0, knick)))]
    pfosten = zylinder("pfosten", (-h, -0.06, hoehe / 2), 0.055, 0.055, hoehe, stahl, 8)
    teile.append(pfosten)
    arm = zylinder("arm", (0, 0, 0), 0.045, 0.045, knick, stahl, 6)
    arm.data.transform(Matrix.Rotation(-math.atan2(0.8, 0.6), 4, "X"))
    arm.data.transform(Matrix.Translation((-h, knick * 0.4 - 0.03, hoehe + knick * 0.3)))
    teile.append(arm)
    for z in (0.12, hoehe):
        teile.append(zylinder("rohr", (0, -0.03, z), 0.03, 0.03, laenge, stahl, 6, achse="X"))
    teile.append(kasten("fuss", (-h, -0.06, 0.05), (0.3, 0.3, 0.14), beton))
    return teile


def flaggenmasten(anzahl: int = 3, abstand: float = 3.0, hoehe: float = 8.0):
    """Masten mit wehenden Flaggen der erfundenen Marken, entlang lokal X."""
    stahl = farbe("mast_stahl", (210, 212, 216), 0.3, 0.8)
    beton = farbe("mast_fuss", (150, 150, 146), 0.9)
    teile = []
    for k in range(anzahl):
        x = (k - (anzahl - 1) / 2) * abstand
        teile.append(zylinder("mast", (x, 0, hoehe / 2), 0.07, 0.045, hoehe, stahl, 8))
        teile.append(kasten("fuss", (x, 0, 0.1), (0.5, 0.5, 0.2), beton))
        teile.append(zylinder("knauf", (x, 0, hoehe + 0.05), 0.08, 0.08, 0.1, stahl, 8))
        mat = tex_mat(f"flagge_{k % 4}", ERZEUGT / f"flagge_{k % 4}.jpg", rauheit=0.8)
        # Flagge weht nach +X, leicht gewellt. Zwei Lagen, 4 cm auseinander:
        # vorn (+Y) mit gespiegeltem u — von dort läuft +X nach links —,
        # hinten mit dem geraden. So liest sich die Marke von beiden Seiten,
        # und der Tiefentest trennt die Lagen sauber.
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.verify()
        spalten = 8
        fl_b, fl_h = 2.4, 1.5
        oben = hoehe - 0.15
        for lage, spiegeln in ((0.02, True), (-0.02, False)):
            reihe = []
            for s in range(spalten + 1):
                u = s / spalten
                welle = math.sin(u * math.pi * 2.2 + k) * 0.18 * u + lage
                px = x + 0.08 + u * fl_b
                reihe.append((bm.verts.new((px, welle, oben - fl_h - 0.1 * u)),
                              bm.verts.new((px, welle, oben)), 1.0 - u if spiegeln else u))
            for s in range(spalten):
                a0, a1, ua = reihe[s]
                b0, b1, ub = reihe[s + 1]
                ecken = (a0, b0, b1, a1) if spiegeln else (a1, b1, b0, a0)
                uvs = ((ua, 0), (ub, 0), (ub, 1), (ua, 1)) if spiegeln else ((ua, 1), (ub, 1), (ub, 0), (ua, 0))
                f = bm.faces.new(ecken)
                for l, w in zip(f.loops, uvs):
                    l[uvl].uv = w
        fl = g.objekt_aus(bm, "flagge", [mat])
        for p in fl.data.polygons:
            p.use_smooth = True
        teile.append(fl)
    return teile


def kameraturm(hoehe: float = 6.0):
    """TV-Kameraturm: Gerüst mit Streben, Plattform mit Geländer, Kamera auf
    Stativ unter einem Sonnendach. Die Kamera schaut zur Strecke (+Y)."""
    gerust = farbe("turm_geruest", (170, 174, 180), 0.4, 0.8)
    holz = wand("holz")
    schwarz = farbe("kamera_schwarz", (26, 26, 30), 0.35, 0.2)
    linse = farbe("kamera_linse", (20, 30, 50), 0.05, 0.4)
    plane = farbe("turm_plane", (30, 60, 150), 0.7)
    schild = tex_mat("tvschild", ERZEUGT / "tvschild.jpg", rauheit=0.5)
    s = 0.9
    teile = []
    for x in (-s, s):
        for y in (-s, s):
            teile.append(kasten("bein", (x, y, hoehe / 2), (0.08, 0.08, hoehe), gerust))
    for z in (1.5, 3.0, 4.5):
        for (m, g_) in (((0, -s, z), (2 * s, 0.05, 0.05)), ((0, s, z), (2 * s, 0.05, 0.05)),
                        ((-s, 0, z), (0.05, 2 * s, 0.05)), ((s, 0, z), (0.05, 2 * s, 0.05))):
            teile.append(kasten("riegel", m, g_, gerust))
    for x in (-s, s):
        strebe = kasten("strebe", (0, 0, 0), (0.04, 0.04, math.hypot(2 * s, hoehe)), gerust)
        strebe.data.transform(Matrix.Rotation(math.atan2(2 * s, hoehe), 4, "X"))
        strebe.data.transform(Matrix.Translation((x, 0, hoehe / 2)))
        teile.append(strebe)
    boden = kasten("plattform", (0, 0, hoehe + 0.05), (2 * s + 0.6, 2 * s + 0.6, 0.1), holz)
    uv_kasten(boden, 1.5)
    teile.append(boden)
    for (m, g_) in (((0, -s - 0.3, hoehe + 1.05), (2 * s + 0.6, 0.05, 0.05)),
                    ((-s - 0.3, 0, hoehe + 1.05), (0.05, 2 * s + 0.6, 0.05)),
                    ((s + 0.3, 0, hoehe + 1.05), (0.05, 2 * s + 0.6, 0.05))):
        teile.append(kasten("gelaender", m, g_, gerust))
    for x in (-s - 0.3, s + 0.3):
        for y in (-s - 0.3, s + 0.3):
            teile.append(kasten("gel_pfosten", (x, y, hoehe + 0.55), (0.05, 0.05, 1.0), gerust))
    # Rücken hinter dem Schild: von hinten keine Spiegelschrift.
    teile.append(kasten("tv_ruecken", (0, s + 0.27, hoehe - 0.45), (1.04, 0.06, 0.54), schwarz))
    teile.append(tafel("tv", [(0.5, s + 0.31, hoehe - 0.7), (-0.5, s + 0.31, hoehe - 0.7),
                              (-0.5, s + 0.31, hoehe - 0.2), (0.5, s + 0.31, hoehe - 0.2)], schild,
                       uv=((0, 0), (1, 0), (1, 1), (0, 1))))
    # Stativ und Kamera.
    for w in (0.0, 2.1, 4.2):
        bein = zylinder("stativ", (0, 0, 0), 0.02, 0.02, 1.3, schwarz, 5)
        bein.data.transform(Matrix.Rotation(0.3, 4, "X"))
        bein.data.transform(Matrix.Rotation(w, 4, "Z"))
        bein.data.transform(Matrix.Translation((0.2 * math.sin(w), -0.2 * math.cos(w), hoehe + 0.72)))
        teile.append(bein)
    teile.append(kasten("kamera", (0, 0.1, hoehe + 1.5), (0.35, 0.7, 0.4), schwarz))
    teile.append(zylinder("objektiv", (0, 0.6, hoehe + 1.5), 0.13, 0.11, 0.4, linse, 12, achse="Y"))
    teile.append(zylinder("sucher", (0.24, -0.1, hoehe + 1.55), 0.06, 0.06, 0.2, schwarz, 8, achse="Y"))
    # Sonnendach auf vier Stangen.
    for x in (-s, s):
        for y in (-s, s):
            teile.append(kasten("dachstange", (x, y, hoehe + 1.3), (0.04, 0.04, 2.5), gerust))
    teile.append(kasten("sonnendach", (0, 0, hoehe + 2.6), (2 * s + 0.4, 2 * s + 0.4, 0.06), plane))
    return teile


def _strecke_fertig(fertig, schluessel, teile, max_abstand_m=None, **kw):
    """``fertig`` plus Sichtgrenze im Katalog (Kleinteile enden früher)."""
    fertig(schluessel, teile, **kw)
    if max_abstand_m is not None and schluessel in KATALOG:
        KATALOG[schluessel]["max_abstand_m"] = max_abstand_m
        g.json_schreiben(ZIEL / "katalog.json", dict(sorted(KATALOG.items())))


# ---------------------------------------------------------------------------
# Kulisse
# ---------------------------------------------------------------------------

def rauschen(x, y, seed, oktaven=5):
    """Einfaches Werterauschen, deterministisch, ohne externe Bibliothek."""
    wert = 0.0
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for o in range(oktaven):
        xi, yi = x * freq, y * freq
        x0, y0 = math.floor(xi), math.floor(yi)
        fx, fy = xi - x0, yi - y0

        def h(i, j):
            n = (i * 374761393 + j * 668265263 + (seed + o * 101) * 1442695041) & 0xFFFFFFFF
            n = (n ^ (n >> 13)) * 1274126177 & 0xFFFFFFFF
            return (n & 0xFFFF) / 65535.0

        sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        a = h(x0, y0) + (h(x0 + 1, y0) - h(x0, y0)) * sx
        b = h(x0, y0 + 1) + (h(x0 + 1, y0 + 1) - h(x0, y0 + 1)) * sx
        wert += (a + (b - a) * sy) * amp
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return wert / norm


def gelaende(name, breite, tiefe, hoehe, seed, stil: str, aufloesung: int = 64):
    """Ein Bergrücken oder Hügel als Höhenfeld, Materialien nach Höhe und Neigung."""
    mats = {
        "schnee": [wand("fels_gras"), wand("felswand"), farbe("schnee", (236, 240, 246), 0.55)],
        "huegel": [wand("wiese"), wand("fels_gras"), farbe("wald_dunkel", (40, 62, 36), 0.9)],
        "wald": [wand("waldboden"), wand("fels_gras"), farbe("wald_dunkel", (34, 54, 30), 0.9)],
        "wueste": [wand("sand"), wand("sandstein"), wand("felswand")],
    }[stil]
    bm = bmesh.new()
    n = aufloesung
    raster = []
    for j in range(n + 1):
        zeile = []
        for i in range(n + 1):
            u, v = i / n - 0.5, j / n - 0.5
            abfall = max(0.0, 1 - (2 * abs(u)) ** 2.2) * max(0.0, 1 - (2 * abs(v)) ** 2.2)
            if stil == "schnee":
                z = hoehe * abfall ** 0.8 * (0.35 + 0.9 * rauschen(u * 4, v * 3, seed))
                z += hoehe * 0.25 * max(0.0, rauschen(u * 9, v * 9, seed + 1) - 0.5) * abfall
            elif stil == "wueste":
                plateau = min(1.0, abfall * 2.6) ** 3
                z = hoehe * plateau * (0.92 + 0.12 * rauschen(u * 6, v * 6, seed))
            else:
                z = hoehe * abfall * (0.6 + 0.5 * rauschen(u * 3, v * 3, seed))
            zeile.append(bm.verts.new((u * breite, v * tiefe, z)))
        raster.append(zeile)
    uvl = bm.loops.layers.uv.verify()
    for j in range(n):
        for i in range(n):
            bm.faces.new((raster[j][i], raster[j][i + 1], raster[j + 1][i + 1], raster[j + 1][i]))
    bm.normal_update()
    # Steile Flanken von der Seite projizieren, flache von oben — sonst zieht
    # sich die Felstextur an jeder Wand zu Streifen.
    for f in bm.faces:
        n_ = f.normal
        for l in f.loops:
            c = l.vert.co
            if n_.z > 0.7:
                l[uvl].uv = (c.x / 24.0, c.y / 24.0)
            elif abs(n_.x) > abs(n_.y):
                l[uvl].uv = (c.y / 24.0, c.z / 24.0)
            else:
                l[uvl].uv = (c.x / 24.0, c.z / 24.0)
    for f in bm.faces:
        zm = f.calc_center_median().z
        steil = 1 - f.normal.z
        if stil == "schnee":
            f.material_index = 2 if zm > hoehe * (0.42 + 0.15 * steil) and steil < 0.7 else (1 if steil > 0.3 or zm > hoehe * 0.3 else 0)
        elif stil == "wueste":
            f.material_index = 1 if steil > 0.25 else (0 if zm < hoehe * 0.1 else 2 if zm > hoehe * 0.85 else 1)
        else:
            f.material_index = 1 if steil > 0.45 else 0
    hoehen = [[v.co.z for v in zeile] for zeile in raster]
    ob = g.objekt_aus(bm, name, mats)
    for p in ob.data.polygons:
        p.use_smooth = True
    teile = [ob]
    if stil in ("wald", "huegel"):
        # Waldsilhouette: einfache Kegel auf der Oberfläche.
        rng = random.Random(seed)
        dunkel = mats[2]
        bm2 = bmesh.new()
        anzahl = 260 if stil == "wald" else 70
        for _ in range(anzahl):
            u, v = rng.uniform(-0.45, 0.45), rng.uniform(-0.45, 0.45)
            i, j = int((u + 0.5) * n), int((v + 0.5) * n)
            z = hoehen[j][i]
            if z < hoehe * 0.08:
                continue
            h = rng.uniform(10, 18)
            r = h * 0.28
            spitze = bm2.verts.new((u * breite, v * tiefe, z + h))
            ring = [bm2.verts.new((u * breite + math.cos(w) * r, v * tiefe + math.sin(w) * r, z - 1.0))
                    for w in [k * 2 * math.pi / 6 for k in range(6)]]
            for k in range(6):
                bm2.faces.new((ring[k], ring[(k + 1) % 6], spitze))
        teile.append(g.objekt_aus(bm2, "waldkegel", [dunkel]))
    return teile


def skyline(seed):
    rng = random.Random(seed)
    namen = ["buero_blau", "buero_gruen", "buero_bronze", "wohn_grau"]
    teile = []
    x = -90.0
    while x < 90:
        b = rng.uniform(22, 38)
        t = rng.uniform(22, 36)
        h = rng.uniform(50, 170)
        for tl in buero_turm("turm", b, t, h, rng.choice(namen), rng.randint(0, 999)):
            tl.data.transform(Matrix.Translation((x + b / 2, rng.uniform(-30, 30), 0)))
            teile.append(tl)
        x += b + rng.uniform(4, 14)
    return teile


# ---------------------------------------------------------------------------
# Katalog der Objekte
# ---------------------------------------------------------------------------

def alle_bauen(nur: set[str] | None, vorschau: Path | None) -> None:
    def soll(s):
        return nur is None or s in nur

    def fertig(schluessel, teile, lod=None, **kw):
        exportieren(schluessel, teile, lod, **kw)
        if vorschau is not None:
            eintrag = KATALOG[schluessel]
            h = max(eintrag["hoehe_m"], eintrag["radius_m"] * 1.5, 1.0)
            bpy.ops.import_scene.gltf(filepath=str(ZIEL / f"{schluessel}.glb"))
            for o in bpy.context.scene.objects:
                if o.parent is None and o.type == "MESH" and o.name.startswith(schluessel.split("/")[-1]):
                    o.matrix_world = Matrix.Rotation(-math.pi / 2, 4, "X") @ o.matrix_world
            g.vorschau(vorschau / (schluessel.replace("/", "_") + ".png"),
                       ziel=(0, 0, h * 0.45), abstand=h * 2.6 + 3, azimut_grad=-60,
                       hoehe_grad=12, breite=480, hoehe=360)
        g.szene_leeren()

    # --- gemeinsam ------------------------------------------------------------
    if soll("gemeinsam/reifenstapel"):
        t, l = reifenstapel()
        fertig("gemeinsam/reifenstapel", t, l, lod_abstand_m=60, radius_m=1.0)
    for i in range(6):
        if soll(f"gemeinsam/bande_{i}"):
            fertig(f"gemeinsam/bande_{i}", werbebande(i), radius_m=3.1)
    if soll("gemeinsam/startbruecke"):
        fertig("gemeinsam/startbruecke", startbruecke(), radius_m=2.0)
    if soll("gemeinsam/tribuene"):
        fertig("gemeinsam/tribuene", tribuene(), radius_m=16.0)

    # --- Streckenobjekte (Strang S) ------------------------------------------
    if soll("strecke/tribuene"):
        _strecke_fertig(fertig, "strecke/tribuene", tribuene_publikum(), radius_m=16.0)
    if soll("strecke/tribuene_klein"):
        _strecke_fertig(fertig, "strecke/tribuene_klein", tribuene_publikum(14.0, 6, seed=5), radius_m=8.0)
    if soll("strecke/boxengebaeude"):
        _strecke_fertig(fertig, "strecke/boxengebaeude", boxengebaeude(), radius_m=24.0)
    if soll("strecke/postenhaus"):
        _strecke_fertig(fertig, "strecke/postenhaus", postenhaus(), radius_m=1.8, max_abstand_m=450.0)
    if soll("strecke/fangzaun"):
        _strecke_fertig(fertig, "strecke/fangzaun", fangzaun_feld(), radius_m=2.0, max_abstand_m=250.0)
    if soll("strecke/huetchen"):
        _strecke_fertig(fertig, "strecke/huetchen", huetchen_gruppe(), radius_m=1.8, max_abstand_m=160.0)
    if soll("strecke/flaggenmasten"):
        _strecke_fertig(fertig, "strecke/flaggenmasten", flaggenmasten(), radius_m=4.5)
    if soll("strecke/kameraturm"):
        _strecke_fertig(fertig, "strecke/kameraturm", kameraturm(), radius_m=1.6)

    # --- Bäume ----------------------------------------------------------------
    for i, (h, r) in enumerate(((12.0, 3.2), (9.0, 2.6), (15.0, 3.6))):
        if soll(f"natur/tanne_{i + 1}"):
            fertig(f"natur/tanne_{i + 1}", tanne("tanne", h, r, 11 + i),
                   tanne("tanne", h, r, 11 + i, dichte=0.45), lod_abstand_m=70, radius_m=r * 0.6)
    for i, (h, r) in enumerate(((11.0, 3.4), (8.0, 2.6), (14.0, 4.2))):
        if soll(f"natur/laubbaum_{i + 1}"):
            fertig(f"natur/laubbaum_{i + 1}", laubbaum("laubbaum", h, r, 21 + i),
                   laubbaum("laubbaum", h, r, 21 + i, karten=35), lod_abstand_m=70, radius_m=r * 0.6)
    for i, r in enumerate((1.2, 0.8)):
        if soll(f"natur/busch_{i + 1}"):
            fertig(f"natur/busch_{i + 1}", busch("busch", r, 31 + i), radius_m=r)
    for i, h in enumerate((6.5, 4.5, 8.0)):
        if soll(f"desert/kaktus_{i + 1}"):
            fertig(f"desert/kaktus_{i + 1}", kaktus("kaktus", h, 41 + i), radius_m=1.2)

    # --- CC0 ------------------------------------------------------------------
    cc0_liste = [
        ("desert/koecherbaum_1", "quiver_tree_01", dict(hoehe_m=5.5, dreiecke=6000, dreiecke_lod1=900)),
        ("desert/koecherbaum_2", "quiver_tree_02", dict(hoehe_m=3.8, dreiecke=4000, dreiecke_lod1=700)),
        ("desert/toter_stamm", "dead_quiver_trunk", dict(hoehe_m=2.6, dreiecke=1500, dreiecke_lod1=300)),
        ("desert/steppenbusch", "wild_rooibos_bush", dict(objekte=[0], hoehe_m=1.1, dreiecke=2500, dreiecke_lod1=400)),
        ("desert/fels_1", "namaqualand_boulder_02", dict(skala=2.6, dreiecke=3000, dreiecke_lod1=500, versenken=0.08)),
        ("desert/fels_2", "namaqualand_boulder_05", dict(skala=3.5, dreiecke=2500, dreiecke_lod1=400, versenken=0.08)),
        ("desert/klippe", "namaqualand_cliff_01", dict(skala=14.0, dreiecke=12000, dreiecke_lod1=3000, versenken=0.05)),
        ("natur/moosfels_1", "rock_moss_set_01", dict(objekte=[0], skala=1.8, dreiecke=2500, dreiecke_lod1=400, versenken=0.1)),
        ("natur/moosfels_2", "rock_moss_set_01", dict(objekte=[2], skala=1.8, dreiecke=2500, dreiecke_lod1=400, versenken=0.1)),
        ("natur/findling", "boulder_01", dict(skala=2.2, dreiecke=3000, dreiecke_lod1=500, versenken=0.06)),
        ("natur/felsbrocken", "rock_07", dict(skala=12.0, dreiecke=2000, dreiecke_lod1=400, versenken=0.1)),
        ("natur/stein", "stone_01", dict(skala=14.0, dreiecke=1500, dreiecke_lod1=300, versenken=0.1)),
        ("natur/baumstumpf", "tree_stump_01", dict(skala=1.3, dreiecke=2500, dreiecke_lod1=400)),
        ("natur/totholz", "dead_tree_trunk", dict(skala=1.6, dreiecke=2500, dreiecke_lod1=400)),
        ("natur/farn", "fern_02", dict(objekte=[0], skala=1.4, dreiecke=1500, dreiecke_lod1=300)),
        ("city/laterne", "street_lamp_01", dict(hoehe_m=6.0, dreiecke=3000, dreiecke_lod1=500)),
        ("city/hydrant", "fire_hydrant", dict(objekte=[0], hoehe_m=0.8, dreiecke=1500, dreiecke_lod1=300)),
        ("city/muelltonne", "metal_trash_can", dict(objekte=[0], hoehe_m=1.0, dreiecke=1500, dreiecke_lod1=300)),
        ("city/stromkasten", "utility_box_01", dict(hoehe_m=1.3, dreiecke=1500, dreiecke_lod1=300)),
        ("gemeinsam/betonblock", "concrete_road_barrier_02", dict(hoehe_m=1.05, dreiecke=1500, dreiecke_lod1=200)),
    ]
    for schluessel, asset, kw in cc0_liste:
        if soll(schluessel):
            ob, lod = cc0(asset, **kw)
            fertig(schluessel, [ob], [lod], lod_abstand_m=60)

    # --- Gebäude --------------------------------------------------------------
    haeuser = [
        ("city/wohnblock_1", dict(breite=24, tiefe=14, geschosse=6, fassaden_name="wohn_hell")),
        ("city/wohnblock_2", dict(breite=30, tiefe=12, geschosse=5, fassaden_name="wohn_ocker")),
        ("city/wohnblock_3", dict(breite=18, tiefe=16, geschosse=8, fassaden_name="wohn_grau")),
        ("city/backstein_1", dict(breite=20, tiefe=12, geschosse=4, fassaden_name="backstein")),
        ("city/backstein_2", dict(breite=14, tiefe=12, geschosse=3, fassaden_name="backstein",
                                  dach="giebel", dach_mat=None)),
        ("desert/lehmhaus_1", dict(breite=9, tiefe=7, geschosse=1, fassaden_name="lehm", geschoss_h=3.4)),
        ("desert/lehmhaus_2", dict(breite=13, tiefe=8, geschosse=2, fassaden_name="lehm", geschoss_h=3.2)),
        ("natur/holzhuette", dict(breite=8, tiefe=6, geschosse=1, fassaden_name="holz", geschoss_h=3.0,
                                  dach="giebel", achse_b=3.0)),
        ("mountain/almhuette", dict(breite=12, tiefe=9, geschosse=2, fassaden_name="holz", geschoss_h=2.9,
                                    dach="giebel")),
        ("plains/bauernhaus", dict(breite=14, tiefe=10, geschosse=2, fassaden_name="bauernhaus",
                                   dach="giebel")),
    ]
    for schluessel, kw in haeuser:
        if soll(schluessel):
            kw = dict(kw)
            if kw.get("dach") == "giebel" and kw.get("dach_mat") is None:
                kw["dach_mat"] = wand("dach_grau") if "alm" in schluessel or "huette" in schluessel \
                    else wand("dachziegel")
            if "almhuette" in schluessel:
                kw["sockel_mat"] = wand("felswand")
            teile = gebaeude(seed=len(schluessel), **kw)
            fertig(schluessel, teile, radius_m=max(kw["breite"], kw["tiefe"]) * 0.62)
    if soll("plains/scheune"):
        teile = gebaeude(16, 11, 2, "holz", geschoss_h=3.6, dach="giebel",
                         dach_mat=wand("wellblech"), seed=5)
        fertig("plains/scheune", teile, radius_m=11)
    for i, (b, t, h, f) in enumerate(((26, 26, 70, "buero_blau"), (22, 30, 48, "buero_gruen"),
                                      (30, 24, 95, "buero_bronze"))):
        if soll(f"city/buero_turm_{i + 1}"):
            fertig(f"city/buero_turm_{i + 1}", buero_turm("turm", b, t, h, f, 51 + i),
                   radius_m=max(b, t) * 0.62, lod_abstand_m=200)
    if soll("plains/zaun"):
        fertig("plains/zaun", zaun(), radius_m=2.0)
    if soll("plains/heuballen"):
        fertig("plains/heuballen", heuballen(), radius_m=0.9)
    if soll("plains/windrad"):
        fertig("plains/windrad", windrad(), radius_m=6, schatten=False)

    # --- Kulisse --------------------------------------------------------------
    kulissen = [
        ("mountain/schneeberg_1", dict(breite=900, tiefe=420, hoehe=320, seed=1, stil="schnee")),
        ("mountain/schneeberg_2", dict(breite=700, tiefe=380, hoehe=240, seed=2, stil="schnee")),
        ("forest/waldhuegel", dict(breite=600, tiefe=320, hoehe=90, seed=3, stil="wald")),
        ("plains/huegel", dict(breite=700, tiefe=360, hoehe=60, seed=4, stil="huegel")),
        ("desert/tafelberg", dict(breite=380, tiefe=260, hoehe=110, seed=5, stil="wueste")),
    ]
    for schluessel, kw in kulissen:
        if soll(schluessel):
            fertig(schluessel, gelaende(schluessel.split("/")[-1], **kw), schatten=False,
                   radius_m=kw["breite"] * 0.4)
    if soll("city/skyline"):
        fertig("city/skyline", skyline(9), schatten=False, radius_m=100)


def main() -> None:
    args = g.argumente()
    nur = None
    vorschau = None
    i = 0
    while i < len(args):
        if args[i] == "--nur":
            nur = set(args[i + 1].split(","))
            i += 2
        elif args[i] == "--vorschau":
            vorschau = Path(args[i + 1])
            i += 2
        else:
            i += 1
    g.szene_leeren()
    katalog_pfad = ZIEL / "katalog.json"
    if nur is not None and katalog_pfad.is_file():
        with open(katalog_pfad, encoding="utf-8") as fh:
            KATALOG.update(json.load(fh))
    alle_bauen(nur, vorschau)
    g.json_schreiben(katalog_pfad, dict(sorted(KATALOG.items())))


if __name__ == "__main__":
    main()
