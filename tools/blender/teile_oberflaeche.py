"""Teile-Bibliothek: Oberflächen — Texturkoordinaten, Materialtexturen,
Keramikrand der Scheiben und Kleinteile an Karosserie und Heck.

Läuft in Blender, aufgerufen aus ``fahrzeug_bauen.materialien`` und
``fahrzeug_bauen.modell_bauen``.

**Texturkoordinaten.** Die Karosserie hat keine abgewickelten UV. Hier
bekommt jede Fläche eines gekachelten Materials eine Würfelprojektion in
Metern, geteilt durch die Kachelgröße des Materials (``KACHEL_M``). Auf
``lack``/``lack2`` ist uv damit genau in Metern: der Lack-Block im Shader
(``src/render3d/shader.py``, Strang L) setzt Flakes und Orangenhaut darauf,
so haften sie an der Karosserie. Leder, Carbon und Kunststoff kacheln ihre
gemeinsamen Texturen (``assets/texturen/fahrzeug``) in echter Größe.

**Scheiben** (``glas``): Keramikrand mit Punktraster. Jede Glasinsel bekommt
zwei Schnittlinien nach dem Randabstand; u ist der Abstand zum Rand, v läuft entlang des
Rands (``tools/fahrzeug_texturen.py``, ``scheibenrand.png``). Front- und
Heckscheibe tragen ein breites Band (schwarz bis 5 cm, Punkte bis 9 cm),
Seitenscheiben ein schmales (ein Drittel davon).

Parameter je Fahrzeug (``tools/blender/fahrzeuge/<key>.json``, alle optional)::

    "lack_metallic": 0.0,  "lack_rauheit": 0.3,   Werkslack (Metallic → Flakes)
    "lack2_metallic": 0.0, "lack2_rauheit": 0.32,
    "innen": {"leder": [r, g, b], "polster": [r, g, b], "armatur": [r, g, b]}
             (sRGB 0..255: Sitzwangen, Sitzmitten, Armaturenbrett/Verkleidung)
    "teile": {"bremsleuchte3": {"breite_m": 0.3, "u_versatz": 0.0} | false,
              "kennzeichenleuchte": false}

In **LOD1** (``p["_lod"]``) bleiben die Materialien ohne Texturen, die
Kleinteile fallen weg; die UV des Lacks bleiben (billig, und der Shader
blendet Flakes in der Ferne ohnehin aus).
"""
from __future__ import annotations

import math
from collections import deque

import bmesh
import bpy
from mathutils import Matrix, Vector

import gemeinsam as g
import teile as t

TEXTUREN = g.WURZEL / "assets" / "texturen" / "fahrzeug"

#: Kachelgröße je Material in Metern: uv = Meter / Kachel.
KACHEL_M = {"lack": 1.0, "lack2": 1.0, "dekor_weiss": 1.0, "zierteil": 1.0,
            "carbon": 0.09, "leder": 0.26, "polster": 0.30, "innenraum": 0.11,
            "kunststoff": 0.11}

#: Wie ``tools/fahrzeug_texturen.py``: Tönung (sRGB 0..255) und Deckung des
#: klaren Glases — für LOD1, das ohne ``scheibenrand.png`` auskommt.
GLAS_TON = (20, 25, 27)
GLAS_DECKUNG = 0.5

#: Innenraumfarben je Fahrzeugfamilie (sRGB 0..255), überschreibbar mit ``innen``.
INNEN_FAMILIE = {
    "rookie": {"leder": [44, 45, 48], "polster": [78, 80, 86], "armatur": [30, 30, 32]},
    "limousine": {"leder": [150, 112, 78], "polster": [168, 128, 90], "armatur": [36, 32, 30]},
    "supercar": {"leder": [30, 30, 32], "polster": [150, 28, 30], "armatur": [22, 22, 24]},
    "drifter": {"leder": [28, 28, 30], "polster": [60, 62, 68], "armatur": [22, 22, 24]},
    "electric": {"leder": [205, 205, 200], "polster": [150, 152, 156], "armatur": [42, 43, 46]},
}


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def _bild(name: str, farbe: bool = False):
    pfad = TEXTUREN / name
    img = bpy.data.images.load(str(pfad), check_existing=True)
    if not farbe:
        img.colorspace_settings.name = "Non-Color"
    return img


def texturieren(m, farbe: str | None = None, normal: str | None = None, mr: str | None = None,
                staerke: float = 1.0, leucht: bool = False, alpha: bool = False) -> None:
    """Texturen an ein Principled-Material hängen, so dass der glTF-Export sie
    als baseColor-, metallicRoughness-, normal- und emissiveTexture schreibt."""
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    if farbe:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = _bild(farbe, farbe=True)
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if leucht:
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        if alpha:
            nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            try:
                m.surface_render_method = "BLENDED"
            except AttributeError:                      # pragma: no cover - alt
                m.blend_method = "BLEND"
    if mr:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = _bild(mr)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(tex.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if normal:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = _bild(normal)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = staerke
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


def innenfarben(p) -> dict:
    fam = INNEN_FAMILIE.get(p.get("_key", "").split("_")[0], INNEN_FAMILIE["rookie"])
    return dict(fam, **(p.get("innen") or {}))


def materialien_ergaenzen(mats: dict, p) -> None:
    """Die Materialien aus ``fahrzeug_bauen.materialien`` mit Texturen
    versehen und die neuen Innenraum-Materialien anlegen."""
    innen = innenfarben(p)
    mats["leder"] = g.material("leder", [c / 255 for c in innen["leder"]], 0.0, 1.0)
    mats["polster"] = g.material("polster", [c / 255 for c in innen["polster"]], 0.0, 1.0)
    mats["anzeige"] = g.material("anzeige", (0.02, 0.02, 0.025), 0.0, 0.18,
                                 emission=(1.0, 1.0, 1.0), staerke=0.9)
    arm = innen.get("armatur")
    if arm:
        mats["innenraum"].node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (
            *[g.srgb_nach_linear(c / 255) for c in arm], 1.0)
    if p.get("_lod"):
        # Ohne Randtextur: Tönung und Deckung des klaren Glases als Faktor,
        # damit die Scheiben beim Wechsel der Stufe nicht dunkler werden.
        bsdf = mats["glas"].node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Base Color"].default_value = (
            *[g.srgb_nach_linear(c / 255) for c in GLAS_TON], 1.0)
        bsdf.inputs["Alpha"].default_value = GLAS_DECKUNG
        return
    texturieren(mats["leder"], normal="leder_normal.jpg", mr="leder_mr.jpg", staerke=1.0)
    texturieren(mats["polster"], normal="polster_normal.jpg", mr="leder_mr.jpg", staerke=1.0)
    texturieren(mats["innenraum"], normal="narbung_normal.jpg", mr="narbung_mr.jpg", staerke=0.8)
    texturieren(mats["kunststoff"], normal="narbung_normal.jpg", mr="narbung_mr.jpg", staerke=0.6)
    texturieren(mats["carbon"], farbe="carbon_farbe.jpg", normal="carbon_normal.jpg",
                mr="carbon_mr.jpg", staerke=0.7)
    texturieren(mats["anzeige"], farbe="anzeige.png", leucht=True)
    texturieren(mats["glas"], farbe="scheibenrand.png", alpha=True)


# ---------------------------------------------------------------------------
# Texturkoordinaten
# ---------------------------------------------------------------------------

def _eine_uv_ebene(me):
    """Genau eine UV-Karte ``UVMap`` (glTF TEXCOORD_0, wie ``backen.UV_NAME``);
    was andere Stränge dort für ihre Flächen abgelegt haben, bleibt."""
    if "UVMap" not in me.uv_layers:
        if me.uv_layers:
            me.uv_layers[0].name = "UVMap"
        else:
            me.uv_layers.new(name="UVMap")
    for ebene in [e for e in me.uv_layers if e.name != "UVMap"]:
        me.uv_layers.remove(ebene)
    me.uv_layers.active = me.uv_layers["UVMap"]
    me.uv_layers["UVMap"].active_render = True


def uv_projektion(ob) -> None:
    """Würfelprojektion in Metern je Fläche für alle Materialien aus
    ``KACHEL_M``; andere Flächen behalten ihre UV (Anzeigen, Leuchten)."""
    me = ob.data
    _eine_uv_ebene(me)
    kachel = [KACHEL_M.get(m.name) if m is not None else None for m in me.materials]
    bm = bmesh.new()
    bm.from_mesh(me)
    uvl = bm.loops.layers.uv.verify()
    for f in bm.faces:
        k = kachel[f.material_index] if f.material_index < len(kachel) else None
        if k is None:
            continue
        n = f.normal
        ax, ay, az = abs(n.x), abs(n.y), abs(n.z)
        for lp in f.loops:
            c = lp.vert.co
            if ax >= ay and ax >= az:
                uv = (c.y if n.x > 0 else -c.y, c.z)
            elif ay >= az:
                uv = (-c.x if n.y > 0 else c.x, c.z)
            else:
                uv = (c.x, c.y if n.z > 0 else -c.y)
            lp[uvl].uv = (uv[0] / k, uv[1] / k)
    bm.to_mesh(me)
    bm.free()


def _inseln(faces) -> list:
    rest = set(faces)
    inseln = []
    while rest:
        start = rest.pop()
        insel = [start]
        schlange = deque([start])
        while schlange:
            f = schlange.popleft()
            for e in f.edges:
                for n in e.link_faces:
                    if n in rest:
                        rest.remove(n)
                        insel.append(n)
                        schlange.append(n)
        inseln.append(insel)
    return inseln


def _randschleifen(insel) -> list:
    """Randkanten der Insel als geschlossene Punktzüge (Vertices)."""
    menge = set(insel)
    kanten = [e for f in insel for e in f.edges
              if sum(1 for n in e.link_faces if n in menge) == 1]
    nachbarn = {}
    for e in kanten:
        a, b = e.verts
        nachbarn.setdefault(a, []).append(b)
        nachbarn.setdefault(b, []).append(a)
    offen = set(nachbarn)
    schleifen = []
    while offen:
        v = offen.pop()
        zug = [v]
        vorher = None
        while True:
            weiter = [w for w in nachbarn[v] if w is not vorher and w in offen]
            if not weiter:
                break
            vorher, v = v, weiter[0]
            offen.discard(v)
            zug.append(v)
        if len(zug) >= 3:
            schleifen.append([w.co.copy() for w in zug])
    return schleifen


def _naechster(p, schleifen):
    """(Abstand, Bogenlänge, Schleifenlänge) zum nächsten Randpunkt."""
    best = (1e9, 0.0, 1.0)
    for pts in schleifen:
        s0 = 0.0
        n = len(pts)
        laenge = sum((pts[(i + 1) % n] - pts[i]).length for i in range(n))
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            ab = b - a
            l2 = ab.length_squared
            tt = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, (p - a).dot(ab) / l2))
            d = (a + ab * tt - p).length
            if d < best[0]:
                best = (d, s0 + tt * math.sqrt(l2), laenge)
            s0 += math.sqrt(l2)
    return best


def _schneiden(bm, insel, abstand, r) -> list:
    """Die Flächen einer Insel entlang der Linie "Abstand zum Rand = r"
    zerschneiden. Die neuen Ecken liegen auf vorhandenen Kanten — anders als
    beim Einrücken entstehen keine Zacken, auch nicht an kurzen Randkanten.
    ``abstand``: Ecke -> Abstand, wird für neue Ecken ergänzt."""
    kanten = {e for f in insel for e in f.edges}
    neu = set()
    for e in kanten:
        va, vb = e.verts
        fa, fb = abstand[va] - r, abstand[vb] - r
        if (fa < 0) == (fb < 0):
            continue
        tt = fa / (fa - fb)
        if tt < 0.04 or tt > 0.96:
            continue                     # eine Ecke liegt schon fast auf der Linie
        _ne, nv = bmesh.utils.edge_split(e, va, tt)
        abstand[nv] = r
        neu.add(nv)
    flaechen = {f for v in neu for f in v.link_faces}
    ergebnis = set(insel)
    for f in flaechen:
        if f not in ergebnis:
            continue
        vs = [v for v in f.verts if v in neu]
        if len(vs) != 2:
            continue
        erg = bmesh.ops.connect_verts(bm, verts=vs)
        for e in erg["edges"]:
            ergebnis.update(e.link_faces)
    return [f for f in ergebnis if f.is_valid]


def glas_rand(ob) -> None:
    """Keramikrand: Glasinseln entlang zweier Abstandslinien zerschneiden,
    UV aus Randabstand und Bogenlänge. Kleine Inseln bleiben klar."""
    me = ob.data
    glas = {i for i, m in enumerate(me.materials) if m is not None and m.name == "glas"}
    if not glas:
        return
    _eine_uv_ebene(me)
    bm = bmesh.new()
    bm.from_mesh(me)
    uvl = bm.loops.layers.uv.verify()
    faces = [f for f in bm.faces if f.material_index in glas]
    for insel in _inseln(faces):
        flaeche = sum(f.calc_area() for f in insel)
        n = Vector((0, 0, 0))
        for f in insel:
            n += f.normal * f.calc_area()
        seite = n.length > 0 and abs(n.normalized().y) > 0.7
        faktor = 3.0 if seite else 1.0
        schleifen = _randschleifen(insel)
        if flaeche < 0.02 or not schleifen:
            for f in insel:
                for lp in f.loops:
                    lp[uvl].uv = (0.85, 0.5)
            continue
        lage = {}
        for f in insel:
            for v in f.verts:
                if v not in lage:
                    lage[v] = _naechster(v.co, schleifen)
        abstand = {v: w[0] for v, w in lage.items()}
        # Schnittlinien: Ende des schwarzen Bands, Mitte und Ende der Punkte.
        for r in ((0.017, 0.024, 0.031) if seite else (0.05, 0.07, 0.092)):
            insel = _schneiden(bm, insel, abstand, r)
        for f in insel:
            for v in f.verts:
                if v not in lage:
                    lage[v] = _naechster(v.co, schleifen)
        for f in insel:
            ref = None
            for lp in f.loops:
                d, s, laenge = lage[lp.vert]
                if ref is None:
                    ref = s
                else:
                    s += laenge * round((ref - s) / laenge)
                u = min(0.85, 0.1 + d * faktor / 0.15)
                lp[uvl].uv = (u, s * faktor / 0.15)
    bm.to_mesh(me)
    bm.free()


def oberflaechen(ob) -> None:
    """Nach dem Zusammenfügen der Karosserie: Keramikrand, dann UV."""
    glas_rand(ob)
    uv_projektion(ob)


def anzeige_uv(ob, v0: float, v1: float) -> None:
    """UV einer Anzeige (Blick von hinten, -X): u quer von links nach rechts
    im Bild, v nach oben, in den Streifen v0..v1 des Atlas ``anzeige.png``."""
    me = ob.data
    _eine_uv_ebene(me)
    ys = [v.co.y for v in me.vertices]
    zs = [v.co.z for v in me.vertices]
    y0, y1 = min(ys), max(ys)
    z0, z1 = min(zs), max(zs)
    uvl = me.uv_layers.active.data
    for poly in me.polygons:
        for li in poly.loop_indices:
            c = me.vertices[me.loops[li].vertex_index].co
            u = (y1 - c.y) / max(y1 - y0, 1e-6)
            v = v0 + (v1 - v0) * (c.z - z0) / max(z1 - z0, 1e-6)
            uvl[li].uv = (u, v)


# ---------------------------------------------------------------------------
# Kleinteile
# ---------------------------------------------------------------------------

def _bremsleuchte3(karosserie, fo, p, mats, d):
    """Dritte Bremsleuchte: schmales Gehäuse oben mittig auf der Heckscheibe,
    darin eine Leiste im Material ``bremslicht`` (leuchtet mit dem Pedal)."""
    k = p["kabine"]
    hs = k.get("heckscheibe")
    if not hs:
        return []
    ms = fo.ms
    u_oben = max(q[0] for q in hs)
    u = u_oben - 0.018 / ms.laenge + d.get("u_versatz", 0.0)
    treffer = t.strahl(karosserie, (ms.x(u), 0.0, 5.0), (0, 0, -1))
    if treffer is None:
        return []
    breite = d.get("breite_m", 0.3)
    teile = [t.kasten("bremsleuchte3", (0.004, 0, 0), (0.012, breite, 0.03), mats["zierteil"], fase=0.004),
             t.kasten("bremsleuchte3_led", (0.0105, 0, 0.0), (0.003, breite - 0.03, 0.009),
                      mats["bremslicht"], fase=0.001)]
    ob = g.verbinden(teile, "bremsleuchte3")
    return [t.auf_flaeche(ob, treffer[0], treffer[1], 0.0)]


def _kennzeichenleuchten(karosserie, fo, p, mats):
    """Zwei kleine Leuchten über dem hinteren Kennzeichen, Lichtaustritt
    nach unten (klar, spiegelnd) in schwarzem Gehäuse."""
    z = (p.get("kennzeichen") or {}).get("hinten_m")
    if z is None:
        return []
    ms = fo.ms
    teile = []
    for y in (-0.14, 0.14):
        treffer = t.strahl(karosserie, (ms.x(fo.u0) - 1.0, y, z + 0.072), (1, 0, 0))
        if treffer is None:
            continue
        geh = t.kasten("kennzeichenleuchte", (0.009, 0, 0), (0.018, 0.045, 0.012), mats["kunststoff"], fase=0.003)
        glas = t.kasten("kennzeichenleuchte_glas", (0.012, 0, -0.0062), (0.012, 0.036, 0.002),
                        mats["chrom"], fase=0.0005)
        ob = g.verbinden([geh, glas], "kennzeichenleuchte")
        teile.append(t.auf_flaeche(ob, treffer[0], Vector((-1.0, 0.0, 0.0)), 0.004))
    return teile


def kleinteile(karosserie, fo, p, mats) -> list:
    """Kleinteile an Karosserie und Heck (nicht in LOD1)."""
    tp = p.get("teile")
    if p.get("_lod") or tp is None:
        return []
    teile = []
    d = tp.get("bremsleuchte3", {})
    if d is not False:
        teile += _bremsleuchte3(karosserie, fo, p, mats, d or {})
    if tp.get("kennzeichenleuchte", {}) is not False and tp.get("kennzeichen", {}) is not False:
        teile += _kennzeichenleuchten(karosserie, fo, p, mats)
    return teile
