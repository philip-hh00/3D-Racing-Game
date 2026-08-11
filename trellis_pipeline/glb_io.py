"""GLB laden und schreiben, ohne unterwegs Material zu verlieren.

TRELLIS 2 liefert echte PBR-Materialien - Base Color, Roughness, Metallic,
Opacity - statt eingebackener Beleuchtung. Das ist der Grund, warum es hier
gegenueber TRELLIS 1 die richtige Wahl ist, und genau deshalb darf der Import
die Materialien nicht unterwegs abstreifen.
"""
from __future__ import annotations

from pathlib import Path

import trimesh
from PIL import Image


class MehrereGeometrien(Warning):
    """Die Datei enthaelt mehr als ein Netz."""


def laden(pfad: str | Path) -> tuple[trimesh.Trimesh, list[str]]:
    """Ein GLB als einzelnes Mesh laden. Liefert Mesh und Hinweise.

    ``process=False``: trimesh wuerde sonst doppelte Vertices verschmelzen. Das
    klingt harmlos, zerstoert aber die UV-Naehte - an einer UV-Naht liegen zwei
    Vertices absichtlich an derselben Stelle mit verschiedenen Texturkoordinaten.
    """
    hinweise: list[str] = []
    geladen = trimesh.load(str(pfad), process=False, force="scene")

    teile = list(geladen.geometry.values()) if isinstance(geladen, trimesh.Scene) \
        else [geladen]
    teile = [t for t in teile if isinstance(t, trimesh.Trimesh)]
    if not teile:
        raise ValueError(f"{pfad}: kein Dreiecksnetz enthalten")

    if len(teile) == 1:
        mesh = teile[0].copy()
        # Die Szenengrafik kann eine Transformation tragen - sonst kommt das
        # Modell im lokalen statt im Weltkoordinatensystem an.
        if isinstance(geladen, trimesh.Scene):
            mesh.apply_transform(geladen.graph.get(
                list(geladen.geometry.keys())[0])[0])
        return mesh, hinweise

    hinweise.append(
        f"{len(teile)} Teilnetze zusammengefasst - nur das Material des "
        f"groessten Teils ueberlebt")
    zusammen = trimesh.util.concatenate(
        sorted(teile, key=lambda t: len(t.faces), reverse=True))
    return zusammen, hinweise


def basis_textur(mesh: trimesh.Trimesh) -> Image.Image | None:
    """Die Base-Color-Textur, falls vorhanden."""
    material = getattr(getattr(mesh, "visual", None), "material", None)
    if material is None:
        return None
    for feld in ("baseColorTexture", "image"):
        bild = getattr(material, feld, None)
        if isinstance(bild, Image.Image):
            return bild
    return None


def speichern(was: trimesh.Trimesh | trimesh.Scene, pfad: str | Path) -> Path:
    """Als GLB schreiben. Legt fehlende Ordner an.

    Nimmt ein einzelnes Netz oder eine ganze Szene - bei getrennten Raedern
    haengt an der Szene die Knoten-Hierarchie, und die ist der eigentliche
    Inhalt.
    """
    ziel = Path(pfad)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    szene = was if isinstance(was, trimesh.Scene) else trimesh.Scene(was)
    ziel.write_bytes(trimesh.exchange.gltf.export_glb(szene, include_normals=True))
    return ziel
