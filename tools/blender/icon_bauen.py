"""Rendert ein Fahrzeug-GLB schraeg von vorn als transparentes PNG fuer das Spiel-Icon.

Aufruf (siehe ``Release/README.md`` fuer den vollen Ablauf)::

    blender.exe -b -P tools/blender/icon_bauen.py -- \
        --fahrzeug assets/vehicles/supercar.glb --ausgabe data/icon_render.png \
        --groesse 1024

Das GLB kommt unveraendert aus ``tools/blender/fahrzeug_bauen.py`` — Karosserie
und Raeder als eigene Knoten, Werkslack schon auf dem Material. Dieses Skript
fuegt nur Kamera und Licht hinzu und rendert freigestellt (Alpha); Hintergrund,
abgerundetes Quadrat und Farbverlauf kommen danach mit PIL dazu
(``tools/icon_zusammensetzen.py``), nicht hier — Blender soll nur das Auto
liefern.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy


def _args() -> argparse.Namespace:
    # Blender reicht eigene Argumente vor "--" durch; nur was danach kommt gehoert uns.
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--fahrzeug", required=True, help="Pfad zur .glb-Datei")
    p.add_argument("--ausgabe", required=True, help="Pfad der PNG-Ausgabe")
    p.add_argument("--groesse", type=int, default=1024)
    return p.parse_args(argv)


def _szene_leeren() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for sammlung in (bpy.data.meshes, bpy.data.cameras, bpy.data.lights, bpy.data.materials):
        for datenblock in list(sammlung):
            if datenblock.users == 0:
                sammlung.remove(datenblock)


def _bounding_box(objekte: list) -> tuple[tuple[float, float, float], float]:
    """Mittelpunkt und Radius (halbe Raumdiagonale) ueber alle Meshes."""
    from mathutils import Vector

    min_v = [math.inf, math.inf, math.inf]
    max_v = [-math.inf, -math.inf, -math.inf]
    for obj in objekte:
        if obj.type != "MESH":
            continue
        for ecke in obj.bound_box:
            welt = obj.matrix_world @ Vector(ecke)
            for i in range(3):
                min_v[i] = min(min_v[i], welt[i])
                max_v[i] = max(max_v[i], welt[i])
    mitte = tuple((min_v[i] + max_v[i]) / 2 for i in range(3))
    radius = math.dist(min_v, max_v) / 2
    return mitte, radius


def main() -> None:
    args = _args()
    _szene_leeren()

    bpy.ops.import_scene.gltf(filepath=str(Path(args.fahrzeug).resolve()))
    fahrzeug_objekte = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not fahrzeug_objekte:
        raise RuntimeError(f"Keine Meshes aus {args.fahrzeug} importiert.")

    from mathutils import Matrix, Vector

    # Der glTF-Re-Import landet mit der Hoehe auf der Y-Achse (Wagen "liegt"),
    # nachgemessen an der Bounding-Box: X ist die Laenge, Y (negativ) die Hoehe,
    # Z die Breite. Fuer eine normale Kamera-Draufsicht braucht es Z als
    # Hochachse — deshalb dreht die ganze Szene -90 Grad um X, bevor die Kamera
    # gesetzt wird. Ueber die Weltmatrix statt eines Operators, damit der
    # Ursprung nicht mit verschoben wird.
    dreh = Matrix.Rotation(-math.pi / 2, 4, "X")
    for obj in fahrzeug_objekte:
        obj.matrix_world = dreh @ obj.matrix_world

    mitte, radius = _bounding_box(fahrzeug_objekte)
    mitte_v = Vector(mitte)

    # Kamera schraeg von vorn-links-oben (Fahrzeugfront zeigt in +X, siehe
    # tools/blender/fahrzeug_bauen.py). Abstand aus dem Radius, damit jedes
    # Fahrzeug unabhaengig von seiner Groesse gleich gross im Bild steht.
    richtung = Vector((0.92, -0.62, 0.50)).normalized()
    abstand = radius * 2.15
    kamera_pos = mitte_v + richtung * abstand

    kamera_daten = bpy.data.cameras.new("IconKamera")
    kamera_daten.lens = 50
    kamera_obj = bpy.data.objects.new("IconKamera", kamera_daten)
    bpy.context.scene.collection.objects.link(kamera_obj)
    kamera_obj.location = kamera_pos
    ziel = kamera_obj.constraints.new(type="TRACK_TO")
    ziel.track_axis = "TRACK_NEGATIVE_Z"
    ziel.up_axis = "UP_Y"
    ziel_leer = bpy.data.objects.new("IconZiel", None)
    bpy.context.scene.collection.objects.link(ziel_leer)
    ziel_leer.location = mitte_v
    ziel.target = ziel_leer
    bpy.context.scene.camera = kamera_obj

    # Dreipunktlicht: Fuellung von vorn-oben, Streiflicht seitlich fuer die
    # Kontur, sanftes Gegenlicht von hinten, damit die Silhouette bei 16x16
    # noch von einem dunklen Hintergrund abgesetzt bleibt.
    def _licht(name: str, typ: str, ort: Vector, energie: float, groesse: float = 2.0) -> None:
        daten = bpy.data.lights.new(name, type=typ)
        daten.energy = energie
        if typ == "AREA":
            daten.size = groesse
        obj = bpy.data.objects.new(name, daten)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = ort
        blick = obj.constraints.new(type="TRACK_TO")
        blick.track_axis = "TRACK_NEGATIVE_Z"
        blick.up_axis = "UP_Y"
        blick.target = ziel_leer

    _licht("Fuellicht", "AREA", mitte_v + Vector((0.6, -1.0, 1.4)) * abstand, energie=900, groesse=radius * 2)
    _licht("Streiflicht", "AREA", mitte_v + Vector((-0.9, -0.3, 0.6)) * abstand, energie=500, groesse=radius * 1.5)
    _licht("Gegenlicht", "AREA", mitte_v + Vector((-0.3, 1.0, 0.8)) * abstand, energie=650, groesse=radius * 1.5)

    szene = bpy.context.scene
    szene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
    szene.render.film_transparent = True
    szene.render.resolution_x = args.groesse
    szene.render.resolution_y = args.groesse
    szene.render.resolution_percentage = 100
    szene.render.image_settings.file_format = "PNG"
    szene.render.image_settings.color_mode = "RGBA"
    szene.view_settings.view_transform = "Standard"

    ausgabe = Path(args.ausgabe).resolve()
    ausgabe.parent.mkdir(parents=True, exist_ok=True)
    szene.render.filepath = str(ausgabe)
    bpy.ops.render.render(write_still=True)
    print(f"[icon_bauen] gerendert: {ausgabe}")


if __name__ == "__main__":
    main()
