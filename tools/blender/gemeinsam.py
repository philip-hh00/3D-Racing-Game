"""Gemeinsame Helfer für die Blender-Skripte unter ``tools/blender/``.

Läuft **in Blender** (``bpy``), nicht im Spiel. Aufgerufen wird über
``tools/blender/bauen.bat`` bzw. direkt:

    blender.exe -b -P tools/blender/fahrzeug_bauen.py -- --fahrzeug rookie

Achsen wie im Spiel (``src/render3d/VEREINBARUNGEN.md``): +X vorne, +Y links,
+Z oben, Meter. Exportiert wird mit ``export_yup=False`` — die GLB-Dateien
liegen damit bereits im Achsensystem des Spiels, der Lader dreht nichts.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

WURZEL = Path(__file__).resolve().parents[2]


def argumente() -> list[str]:
    """Was nach ``--`` auf der Blender-Kommandozeile steht."""
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1:]
    return []


def szene_leeren() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for sammlung in (bpy.data.meshes, bpy.data.materials, bpy.data.images,
                     bpy.data.objects, bpy.data.curves):
        for ding in list(sammlung):
            sammlung.remove(ding)


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def srgb_nach_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def material(name: str, farbe=(0.8, 0.8, 0.8), metallic: float = 0.0,
             rauheit: float = 0.5, emission=None, staerke: float = 0.0,
             alpha: float = 1.0, bild: str | None = None,
             bild_mr: str | None = None, klarlack: float = 0.0):
    """Ein Principled-Material, das der glTF-Export versteht.

    ``farbe`` in sRGB 0..1 — so, wie man Farben notiert. Blender rechnet im
    Knoten linear; umgerechnet wird hier, damit die Zahlen in den
    Parameterdateien dieselben sind wie in ``lacke.json``.
    """
    vorhanden = bpy.data.materials.get(name)
    if vorhanden is not None:
        return vorhanden
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    lin = [srgb_nach_linear(c) for c in farbe[:3]]
    bsdf.inputs["Base Color"].default_value = (*lin, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = rauheit
    if klarlack:
        bsdf.inputs["Coat Weight"].default_value = klarlack
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (
            *[srgb_nach_linear(c) for c in emission], 1.0)
        bsdf.inputs["Emission Strength"].default_value = staerke
    if alpha < 1.0:
        bsdf.inputs["Alpha"].default_value = alpha
        try:
            m.surface_render_method = "BLENDED"
        except AttributeError:                      # pragma: no cover - alt
            m.blend_method = "BLEND"
    if bild:
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(bild))
        m.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if bild_mr:
        tex = m.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(bild_mr))
        tex.image.colorspace_settings.name = "Non-Color"
        sep = m.node_tree.nodes.new("ShaderNodeSeparateColor")
        m.node_tree.links.new(tex.outputs["Color"], sep.inputs["Color"])
        m.node_tree.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        m.node_tree.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    return m


# ---------------------------------------------------------------------------
# Netze
# ---------------------------------------------------------------------------

def objekt_aus(bm: bmesh.types.BMesh, name: str, materialien=()) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for m in materialien:
        ob.data.materials.append(m)
    return ob


def objekt_aus_daten(name: str, punkte, flaechen, materialien=(),
                     mat_index=None) -> bpy.types.Object:
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(p) for p in punkte], [], [tuple(f) for f in flaechen])
    me.validate()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    for m in materialien:
        ob.data.materials.append(m)
    if mat_index is not None:
        for poly, i in zip(ob.data.polygons, mat_index):
            poly.material_index = i
    return ob


def aktiv(ob) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def modifikator_anwenden(ob, mod) -> None:
    aktiv(ob)
    bpy.ops.object.modifier_apply(modifier=mod.name)


def unterteilen(ob, stufen: int = 2) -> None:
    mod = ob.modifiers.new("unterteilung", "SUBSURF")
    mod.levels = stufen
    mod.render_levels = stufen
    mod.subdivision_type = "CATMULL_CLARK"
    modifikator_anwenden(ob, mod)


def glatt(ob, winkel_grad: float = 35.0) -> None:
    aktiv(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(winkel_grad))


def boolesch(ob, werkzeug, art: str = "DIFFERENCE", loeschen: bool = True) -> None:
    mod = ob.modifiers.new("bool", "BOOLEAN")
    mod.operation = art
    mod.object = werkzeug
    mod.solver = "EXACT"
    modifikator_anwenden(ob, mod)
    if loeschen:
        bpy.data.objects.remove(werkzeug, do_unlink=True)


def verbinden(objekte, name: str) -> bpy.types.Object:
    """Mehrere Objekte zu einem verschmelzen; Materialien bleiben je Fläche."""
    objekte = [o for o in objekte if o is not None]
    bpy.ops.object.select_all(action="DESELECT")
    for o in objekte:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objekte[0]
    if len(objekte) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = name
    ob.data.name = name
    return ob


def transform_anwenden(ob) -> None:
    aktiv(ob)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def ursprung_setzen(ob, punkt) -> None:
    """Den Objektursprung auf ``punkt`` legen, ohne die Geometrie zu bewegen."""
    punkt = Vector(punkt)
    ob.data.transform(Matrix.Translation(-punkt))
    ob.location = punkt


def dreiecke(ob) -> int:
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def glb_schreiben(pfad: Path, objekte=None) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    if objekte is not None:
        bpy.ops.object.select_all(action="DESELECT")
        for o in objekte:
            o.select_set(True)
    bpy.ops.export_scene.gltf(
        filepath=str(pfad), export_format="GLB", export_yup=False,
        use_selection=objekte is not None, export_apply=True,
        export_materials="EXPORT", export_image_format="AUTO",
        export_texcoords=True, export_normals=True, export_tangents=False,
        export_cameras=False, export_lights=False, export_extras=False,
        export_animations=False, export_skins=False, export_morph=False)


def json_schreiben(pfad: Path, daten) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(daten, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Vorschaubild
# ---------------------------------------------------------------------------

def vorschau(pfad: Path, ziel=(0.0, 0.0, 0.6), abstand: float = 9.0,
             azimut_grad: float = 35.0, hoehe_grad: float = 18.0,
             breite: int = 960, hoehe: int = 540, boden: bool = True,
             linse_mm: float = 50.0) -> None:
    """Ein schnelles Kontrollbild mit Eevee: Sonne, Himmel, grauer Boden."""
    szene = bpy.context.scene
    for kandidat in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            szene.render.engine = kandidat
            break
        except TypeError:
            continue
    szene.render.resolution_x = breite
    szene.render.resolution_y = hoehe
    szene.render.film_transparent = False
    szene.view_settings.view_transform = "AgX"

    welt = bpy.data.worlds.new("welt")
    welt.use_nodes = True
    hg = welt.node_tree.nodes["Background"]
    hg.inputs["Color"].default_value = (0.55, 0.68, 0.9, 1.0)
    hg.inputs["Strength"].default_value = 0.9
    szene.world = welt

    sonne = bpy.data.lights.new("sonne", "SUN")
    sonne.energy = 4.0
    sonne.angle = math.radians(3)
    so = bpy.data.objects.new("sonne", sonne)
    so.rotation_euler = (math.radians(40), math.radians(10), math.radians(-30))
    szene.collection.objects.link(so)

    if boden:
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60)
        b = objekt_aus(bm, "boden", [material("_boden", (0.42, 0.42, 0.43), 0, 0.9)])
    az = math.radians(azimut_grad)
    el = math.radians(hoehe_grad)
    ziel = Vector(ziel)
    auge = ziel + Vector((math.cos(az) * math.cos(el),
                          math.sin(az) * math.cos(el), math.sin(el))) * abstand
    kd = bpy.data.cameras.new("kamera")
    kd.lens = linse_mm
    ko = bpy.data.objects.new("kamera", kd)
    szene.collection.objects.link(ko)
    ko.location = auge
    richtung = ziel - auge
    ko.rotation_euler = richtung.to_track_quat("-Z", "Y").to_euler()
    szene.camera = ko
    szene.render.filepath = str(pfad)
    bpy.ops.render.render(write_still=True)
    # Hilfsobjekte wieder entfernen, damit ein folgender Export sie nicht
    # mitnimmt.
    for ob in (ko, so):
        bpy.data.objects.remove(ob, do_unlink=True)
    if boden:
        bpy.data.objects.remove(b, do_unlink=True)
