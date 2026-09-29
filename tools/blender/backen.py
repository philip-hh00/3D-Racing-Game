"""Details backen: feine Hochpoly-Geometrie in Texturen einer sparsamen Spielgeometrie.

Läuft **in Blender** (Cycles, headless; mit Grafikkarte über OptiX/CUDA,
sonst auf der CPU). Wiederverwendbar für jeden Strang, der Feinheiten nicht
als Dreiecke ins Spiel bringen will — Leuchtenoptiken, Reifenflanken,
Bremsscheiben, Gitter::

    import backen
    karten = backen.backen(ziele, quellen, ordner, "rookie_leuchten",
                           groesse=2048, arten=("normal", "emission", "ao"),
                           verbergen=[glas], abstand_m=0.004, reichweite_m=0.008)
    # -> {"normal": Path, "emission": Path, "ao": Path}
    bilder = {art: backen.bild_laden(pfad, art) for art, pfad in karten.items()}
    backen.material_ausstatten(mat, normal=bilder["normal"], ao=bilder["ao"])

**Ziele** sind die Netze, die ins Spiel gehen. Sie brauchen eine UV-Karte
``UVMap`` (``UV_NAME``) ohne Überlappung — wer spiegelt, backt nur eine Seite
und legt die andere auf dieselben Texel. **Quellen** sind die feinen Netze
darüber (höchstens ``abstand_m`` über dem Ziel, nicht tiefer als
``reichweite_m - abstand_m`` darunter); sie müssen das Ziel überall decken,
sonst bleibt dort der Vorgabewert stehen. Am einfachsten legt man eine Kopie
des Ziels als Grundplatte unter die Details.

Die Karten und ihre Konventionen — genau so, wie der Shader des Spiels sie
liest (``src/render3d/shader.py``):

* ``normal``: Tangentenraum, OpenGL (grün = +V), linear. Vorgabe flach.
* ``emission``: die Leuchtfarbe der Quellen (Emission Color × Strength, auf
  1 begrenzt), sRGB. Vorgabe schwarz. Im Spiel wird sie mit ``emissiveFactor``
  × ``emissiveStrength`` multipliziert.
* ``ao``: Umgebungsverdeckung im Rotkanal, linear, Reichweite ``ao_weite_m``.
  Verdecken können alle sichtbaren Objekte der Szene (Gehäusewände,
  Lichtleiter), nicht nur die Quellen. Vorgabe 1.
* ``farbe``: Grundfarbe der Quellen (DIFFUSE, nur Farbe), sRGB.

Was keinen Texel eines Ziels trifft, behält den Vorgabewert — dadurch mischen
die Mipstufen am Inselrand nichts Falsches hinein. ``rand_px`` erweitert die
Inseln nach außen, damit auch die gröberen Mipstufen sauber bleiben.

Die Szene wird nicht verändert: die Ziele werden kopiert und zu einem
Hilfsobjekt verbunden, die Hilfsobjekte am Ende wieder gelöscht, verborgene
Objekte wieder eingeblendet.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
import numpy as np

#: Name der UV-Karte, die gebacken und exportiert wird (glTF TEXCOORD_0).
UV_NAME = "UVMap"

#: Vorgabewert je Kartenart (RGBA, in den gespeicherten Werten des Bildes).
VORGABE = {
    "normal": (0.5, 0.5, 1.0, 1.0),
    "emission": (0.0, 0.0, 0.0, 1.0),
    "ao": (1.0, 1.0, 1.0, 1.0),
    "farbe": (0.5, 0.5, 0.5, 1.0),
}

#: Farbraum je Kartenart.
FARBRAUM = {"normal": "Non-Color", "emission": "sRGB", "ao": "Non-Color", "farbe": "sRGB"}

#: Cycles-Backtyp je Kartenart.
BACKTYP = {"normal": "NORMAL", "emission": "EMIT", "ao": "AO", "farbe": "DIFFUSE"}

#: Abtastungen je Kartenart (Kantenglättung bzw. Rauschen der Verdeckung).
PROBEN = {"normal": 8, "emission": 8, "ao": 128, "farbe": 4}


# ---------------------------------------------------------------------------
# Gerät
# ---------------------------------------------------------------------------

_GERAET: str | None = None


def geraet_waehlen() -> str:
    """Cycles auf die Grafikkarte legen (OptiX, sonst CUDA, sonst HIP/Metal),
    ohne sie auf der CPU. ``BACKEN_CPU=1`` erzwingt die CPU."""
    global _GERAET
    szene = bpy.context.scene
    szene.render.engine = "CYCLES"
    if _GERAET is None:
        _GERAET = "CPU"
        if os.environ.get("BACKEN_CPU") != "1":
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for typ in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = typ
                    prefs.get_devices()
                except (TypeError, ValueError):
                    continue
                gpus = [d for d in prefs.devices if d.type == typ]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type == typ
                    _GERAET = typ
                    break
    szene.cycles.device = "CPU" if _GERAET == "CPU" else "GPU"
    return _GERAET


# ---------------------------------------------------------------------------
# Bilder
# ---------------------------------------------------------------------------

def bild_neu(name: str, groesse: int, art: str) -> bpy.types.Image:
    """Ein leeres Bild mit dem Vorgabewert der Kartenart."""
    alt = bpy.data.images.get(name)
    if alt is not None:
        bpy.data.images.remove(alt)
    img = bpy.data.images.new(name, groesse, groesse, alpha=False, float_buffer=False)
    img.colorspace_settings.name = FARBRAUM[art]
    img.generated_color = VORGABE[art]
    return img


def pixel_lesen(img) -> np.ndarray:
    """Pixel als ``(h, w, 4)``-Feld, Zeile 0 = unten (UV ``v = 0``)."""
    w, h = img.size
    a = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def pixel_schreiben(img, feld: np.ndarray) -> None:
    img.pixels.foreach_set(np.ascontiguousarray(feld, dtype=np.float32).ravel())
    img.update()


def speichern(img, pfad: Path) -> Path:
    pfad = Path(pfad)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    img.filepath_raw = str(pfad)
    img.file_format = "PNG"
    img.save()
    return pfad


def bild_laden(pfad: Path, art: str, name: str | None = None) -> bpy.types.Image:
    """Eine gebackene Karte laden (mit dem richtigen Farbraum)."""
    img = bpy.data.images.load(str(pfad), check_existing=False)
    img.name = name or Path(pfad).stem
    img.colorspace_settings.name = FARBRAUM.get(art, "sRGB")
    return img


def verkleinern(pfad: Path, groesse: int, ziel: Path) -> Path:
    """Eine Karte auf ``groesse``² verkleinern (für LOD-Stufen).

    Halbiert schrittweise mit Mittelwert (wie eine Mipstufe) — ``Image.scale``
    tastet nur ab und lässt feine Muster flimmern.
    """
    img = bpy.data.images.load(str(pfad), check_existing=False)
    feld = pixel_lesen(img)
    while feld.shape[0] > groesse and feld.shape[0] % 2 == 0:
        h, w = feld.shape[0] // 2, feld.shape[1] // 2
        feld = feld.reshape(h, 2, w, 2, 4).mean(axis=(1, 3))
    klein = bpy.data.images.new(img.name + "_klein", feld.shape[1], feld.shape[0],
                                alpha=False, float_buffer=False)
    klein.colorspace_settings.name = img.colorspace_settings.name
    pixel_schreiben(klein, feld)
    speichern(klein, ziel)
    bpy.data.images.remove(img)
    bpy.data.images.remove(klein)
    return Path(ziel)


def rechteck_fuellen(feld: np.ndarray, rechteck_uv, farbe) -> None:
    """``rechteck_uv = (u0, v0, u1, v1)`` im Feld mit ``farbe`` (RGB[A]) füllen."""
    h, w = feld.shape[:2]
    u0, v0, u1, v1 = rechteck_uv
    x0, x1 = int(round(u0 * w)), int(round(u1 * w))
    y0, y1 = int(round(v0 * h)), int(round(v1 * h))
    feld[y0:y1, x0:x1, :len(farbe)] = farbe


def linear_nach_srgb(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def srgb_nach_linear(c):
    c = np.clip(np.asarray(c, dtype=np.float32), 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, np.power((c + 0.055) / 1.055, 2.4))


# ---------------------------------------------------------------------------
# Backen
# ---------------------------------------------------------------------------

def _zielobjekt(ziele) -> bpy.types.Object:
    """Kopien der Ziele zu einem Hilfsobjekt verbinden (ein Material)."""
    kopien = []
    for ob in ziele:
        k = ob.copy()
        k.data = ob.data.copy()
        bpy.context.scene.collection.objects.link(k)
        if UV_NAME not in k.data.uv_layers:
            raise ValueError(f"backen: Ziel {ob.name} hat keine UV-Karte {UV_NAME}")
        kopien.append(k)
    bpy.ops.object.select_all(action="DESELECT")
    for k in kopien:
        k.select_set(True)
    bpy.context.view_layer.objects.active = kopien[0]
    if len(kopien) > 1:
        bpy.ops.object.join()
    ziel = bpy.context.view_layer.objects.active
    ziel.name = "_backziel"
    ziel.data.uv_layers.active = ziel.data.uv_layers[UV_NAME]
    ziel.data.materials.clear()
    for p in ziel.data.polygons:
        p.material_index = 0
    # Das Hilfsziel selbst verdeckt nichts: es liegt unter den Quellen.
    for attr in ("visible_diffuse", "visible_glossy", "visible_transmission",
                 "visible_shadow", "visible_volume_scatter"):
        setattr(ziel, attr, False)
    return ziel


def _backmaterial(ziel, img) -> None:
    m = bpy.data.materials.new("_backen")
    m.use_nodes = True
    knoten = m.node_tree.nodes.new("ShaderNodeTexImage")
    knoten.image = img
    m.node_tree.nodes.active = knoten
    ziel.data.materials.clear()
    ziel.data.materials.append(m)


def backen(ziele, quellen, ordner: Path, name: str, groesse: int = 2048,
           arten=("normal", "emission", "ao"), verbergen=(), abstand_m: float = 0.004,
           reichweite_m: float = 0.008, ao_weite_m: float = 0.03, rand_px: int = 16,
           proben: dict | None = None, quellen_je_art: dict | None = None) -> dict:
    """Feine Quellen auf die Ziele backen; je Art eine PNG in ``ordner``.

    ``quellen_je_art``: andere Quellen für einzelne Arten (etwa nur die
    Leuchtkörper für ``emission``). ``verbergen``: Objekte, die nicht
    mitwirken sollen (Glas!); die Ziele selbst werden ohnehin verborgen.
    """
    geraet_waehlen()
    szene = bpy.context.scene
    if szene.world is None:
        szene.world = bpy.data.worlds.new("_backwelt")
    szene.world.light_settings.distance = ao_weite_m
    szene.cycles.use_denoising = False
    szene.render.bake.use_selected_to_active = True
    proben = {**PROBEN, **(proben or {})}

    verborgen = []
    for ob in list(ziele) + list(verbergen):
        if ob is not None and not ob.hide_render:
            ob.hide_render = True
            verborgen.append(ob)
    ziel = _zielobjekt(ziele)
    ziel.hide_render = False
    ergebnis = {}
    try:
        for art in arten:
            img = bild_neu(f"{name}_{art}", groesse, art)
            _backmaterial(ziel, img)
            qu = (quellen_je_art or {}).get(art, quellen)
            bpy.ops.object.select_all(action="DESELECT")
            for q in qu:
                q.select_set(True)
            ziel.select_set(True)
            bpy.context.view_layer.objects.active = ziel
            szene.cycles.samples = proben[art]
            if art == "farbe":
                szene.render.bake.use_pass_direct = False
                szene.render.bake.use_pass_indirect = False
                szene.render.bake.use_pass_color = True
            bpy.ops.object.bake(type=BACKTYP[art], normal_space="TANGENT",
                                normal_r="POS_X", normal_g="POS_Y", normal_b="POS_Z",
                                use_selected_to_active=True, cage_extrusion=abstand_m,
                                max_ray_distance=reichweite_m, margin=rand_px,
                                margin_type="EXTEND", use_clear=False,
                                target="IMAGE_TEXTURES")
            ergebnis[art] = speichern(img, Path(ordner) / f"{name}_{art}.png")
            bpy.data.images.remove(img)
    finally:
        m = ziel.data.materials[0] if ziel.data.materials else None
        bpy.data.objects.remove(ziel, do_unlink=True)
        if m is not None:
            bpy.data.materials.remove(m)
        for ob in verborgen:
            ob.hide_render = False
    return ergebnis


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def _uv_knoten(nt):
    for n in nt.nodes:
        if n.bl_idname == "ShaderNodeUVMap" and n.uv_map == UV_NAME:
            return n
    n = nt.nodes.new("ShaderNodeUVMap")
    n.uv_map = UV_NAME
    return n


def _bildknoten(nt, img):
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = img
    t.interpolation = "Linear"
    nt.links.new(_uv_knoten(nt).outputs["UV"], t.inputs["Vector"])
    return t


def _gltf_ausgabe(nt):
    """Die Knotengruppe, über die der glTF-Export die Verdeckung findet."""
    grp = bpy.data.node_groups.get("glTF Material Output")
    if grp is None:
        grp = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        grp.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    for n in nt.nodes:
        if n.bl_idname == "ShaderNodeGroup" and n.node_tree is grp:
            return n
    n = nt.nodes.new("ShaderNodeGroup")
    n.node_tree = grp
    return n


def material_ausstatten(mat, normal=None, emission=None, ao=None, farbe=None,
                        normal_staerke: float = 1.0, emission_staerke: float | None = None) -> None:
    """Gebackene Karten an ein Principled-Material hängen, so wie der
    glTF-Export sie als ``normalTexture``, ``emissiveTexture`` (Faktor 1,
    Stärke über ``KHR_materials_emissive_strength``) und ``occlusionTexture``
    schreibt. ``emission`` ersetzt die Leuchtfarbe: die Karte trägt die Farbe,
    das Material nur noch die Stärke."""
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled")
    if normal is not None:
        t = _bildknoten(nt, normal)
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.uv_map = UV_NAME
        nm.inputs["Strength"].default_value = normal_staerke
        nt.links.new(t.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    if emission is not None:
        t = _bildknoten(nt, emission)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Emission Color"])
        if emission_staerke is not None:
            bsdf.inputs["Emission Strength"].default_value = emission_staerke
    if ao is not None:
        t = _bildknoten(nt, ao)
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(t.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Red"], _gltf_ausgabe(nt).inputs["Occlusion"])
    if farbe is not None:
        t = _bildknoten(nt, farbe)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])


# ---------------------------------------------------------------------------
# UV
# ---------------------------------------------------------------------------

def uv_setzen(ob, funktion) -> None:
    """UV je Ecke aus ``funktion(welt_punkt, flaeche) -> (u, v)``."""
    me = ob.data
    uv = me.uv_layers.get(UV_NAME) or me.uv_layers.new(name=UV_NAME)
    mw = ob.matrix_world
    werte = np.empty(len(me.loops) * 2, dtype=np.float32)
    for p in me.polygons:
        for li in p.loop_indices:
            u, v = funktion(mw @ me.vertices[me.loops[li].vertex_index].co, p)
            werte[2 * li] = u
            werte[2 * li + 1] = v
    uv.data.foreach_set("uv", werte)


def uv_fest(ob, u: float, v: float) -> None:
    """Alle Ecken auf einen Punkt legen (neutraler Bereich des Atlas)."""
    me = ob.data
    uv = me.uv_layers.get(UV_NAME) or me.uv_layers.new(name=UV_NAME)
    werte = np.tile(np.array([u, v], dtype=np.float32), len(me.loops))
    uv.data.foreach_set("uv", werte)


def regalpacken(groessen, breite: float, hoehe: float, luecke: float):
    """Rechtecke ``[(w, h)]`` zeilenweise in ``breite × hoehe`` legen.

    Liefert je Rechteck ``(x, y)`` oder ``None``, wenn es nicht passt. Die
    Reihenfolge der Eingabe bleibt die der Ausgabe; gelegt wird nach Höhe.
    """
    reihenfolge = sorted(range(len(groessen)), key=lambda i: -groessen[i][1])
    lage = [None] * len(groessen)
    x = y = zeile = 0.0
    for i in reihenfolge:
        w, h = groessen[i]
        if x + w > breite:
            x, y, zeile = 0.0, y + zeile + luecke, 0.0
        if w > breite or y + h > hoehe:
            return None
        lage[i] = (x, y)
        x += w + luecke
        zeile = max(zeile, h)
    return lage


def dichte_suchen(groessen_m, breite_px: int, hoehe_px: int, luecke_px: int,
                  hoechstens: float = 4000.0) -> tuple[float, list]:
    """Größte Texeldichte (px/m, höchstens ``hoechstens``), bei der alle
    Inseln ``groessen_m`` ins Rechteck passen; dazu die Lage in Pixeln."""
    lo, hi = 1.0, hoechstens
    beste = None
    for _ in range(40):
        mitte = math.sqrt(lo * hi)
        lage = regalpacken([(w * mitte, h * mitte) for w, h in groessen_m],
                           breite_px, hoehe_px, luecke_px)
        if lage is None:
            hi = mitte
        else:
            lo, beste = mitte, lage
    if beste is None:
        raise ValueError("backen: Inseln passen nicht in den Atlas")
    return lo, beste
