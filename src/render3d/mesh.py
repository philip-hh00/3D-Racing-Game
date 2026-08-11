"""GLB-Lader für Fahrzeugmodelle.

Zwei getrennte Schichten:

* :func:`laden` liest eine GLB-**Szene** mit benannten Knoten (Karosserie und
  vier Räder, siehe ``trellis_pipeline.radschnitt.Zerlegung.als_szene``) und
  liefert reine Zahlen — kein OpenGL, ohne Kontext testbar.
* :func:`hochladen` gibt diese Zahlen an einen bereits vorhandenen
  ModernGL-Kontext weiter und liefert ein fertiges :class:`Modell` mit einer
  Vertex-Array-Object je Teil.

``trimesh.load(..., process=False)``: ``process=True`` würde doppelte
Vertices verschmelzen und dabei UV-Nähte zerstören — an einer Naht liegen
zwei Vertices absichtlich an derselben Stelle mit verschiedenen
Texturkoordinaten (siehe ``trellis_pipeline/glb_io.py`` und
``trellis_pipeline/radschnitt.py:nachbarschaft``).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import trimesh
from PIL import Image, ImageOps

if TYPE_CHECKING:
    import moderngl


@dataclass
class Teilnetz:
    """Ein benannter Knoten aus der Szene — Karosserie oder ein Rad."""

    name: str
    positionen: np.ndarray    # (n, 3) float32, Meter, im lokalen Ursprung des Knotens
    normalen: np.ndarray      # (n, 3) float32, normiert
    uv: np.ndarray            # (n, 2) float32
    indizes: np.ndarray       # (m, 3) uint32
    versatz: np.ndarray       # (3,) float32 — Position des Knotens in der Szene


@dataclass
class Modelldaten:
    """Ergebnis von :func:`laden` — reine Daten, kein OpenGL."""

    teile: list[Teilnetz]
    basisfarbe: "Image.Image | None"
    metallic_rauheit: "Image.Image | None"

    def teil(self, name: str) -> "Teilnetz | None":
        for t in self.teile:
            if t.name == name:
                return t
        return None


def _material_von(szene: trimesh.Scene):
    """Das erste Material irgendeines Teils.

    Alle Teile eines Fahrzeugs stammen aus demselben TRELLIS-Netz und teilen
    sich einen Texturatlas (siehe ``radschnitt.schneiden`` — die Räder sind
    Submeshes der Karosserie). Ein Material genügt deshalb für das ganze
    Modell.
    """
    for geometrie in szene.geometry.values():
        material = getattr(getattr(geometrie, "visual", None), "material", None)
        if material is not None:
            return material
    return None


def _uv_von(mesh: trimesh.Trimesh) -> np.ndarray:
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    if uv is None:
        return np.zeros((len(mesh.vertices), 2), dtype=np.float32)
    return np.asarray(uv, dtype=np.float32)


def laden(pfad: str | Path) -> Modelldaten:
    """GLB-Szene einlesen.

    Fehlende Normalen werden berechnet (``trimesh`` erledigt das automatisch
    über ``vertex_normals``, sobald keine im Netz stecken), fehlende UV auf 0
    gesetzt.
    """
    szene = trimesh.load(str(pfad), process=False, force="scene")

    teile: list[Teilnetz] = []
    for knoten_name in szene.graph.nodes_geometry:
        transform, geom_name = szene.graph[knoten_name]
        mesh = szene.geometry[geom_name]

        positionen = np.asarray(mesh.vertices, dtype=np.float32)
        normalen = np.asarray(mesh.vertex_normals, dtype=np.float32)
        uv = _uv_von(mesh)
        indizes = np.asarray(mesh.faces, dtype=np.uint32)
        versatz = np.asarray(transform, dtype=np.float32)[:3, 3]

        teile.append(Teilnetz(
            name=knoten_name, positionen=positionen, normalen=normalen,
            uv=uv, indizes=indizes, versatz=versatz))

    material = _material_von(szene)
    basisfarbe = getattr(material, "baseColorTexture", None) if material else None
    metallic_rauheit = (
        getattr(material, "metallicRoughnessTexture", None) if material else None)

    return Modelldaten(teile=teile, basisfarbe=basisfarbe,
                       metallic_rauheit=metallic_rauheit)


@dataclass
class HochgeladenesTeil:
    """Ein Teilnetz, an OpenGL übergeben."""

    name: str
    vao: "moderngl.VertexArray"
    versatz: np.ndarray


@dataclass
class Modell:
    """Ergebnis von :func:`hochladen` — bereit zum Zeichnen."""

    teile: list[HochgeladenesTeil]
    basisfarbe: "moderngl.Texture | None"
    metallic_rauheit: "moderngl.Texture | None"

    def teil(self, name: str) -> "HochgeladenesTeil | None":
        for t in self.teile:
            if t.name == name:
                return t
        return None


def _textur_hochladen(ctx: "moderngl.Context", bild: "Image.Image | None"):
    """Ein PIL-Bild als ModernGL-Textur hochladen.

    ``trimesh`` liefert UV in OpenGL-Konvention: ``v = 0`` ist die
    **Unterkante** des Bildes. PIL-Zeile 0 ist dagegen die *Oberkante* — ohne
    Ausgleich würde jede Textur kopf stehen. Deshalb hier, genau einmal, vor
    dem Hochladen spiegeln (siehe VEREINBARUNGEN.md, Abschnitt
    "Texturkoordinaten"). Bewusst hier und nicht im Shader: sonst muss jeder
    künftige Shader daran denken.
    """
    if bild is None:
        return None
    rgba = bild.convert("RGBA")
    gespiegelt = ImageOps.flip(rgba)
    textur = ctx.texture(gespiegelt.size, 4, gespiegelt.tobytes())
    textur.build_mipmaps()
    return textur


def hochladen(ctx: "moderngl.Context", programm: "moderngl.Program",
              daten: Modelldaten) -> Modell:
    """Puffer und Texturen an OpenGL geben.

    Je Teilnetz entsteht eine Vertex-Array-Object mit den Attributen
    ``in_position`` (3f), ``in_normale`` (3f) und ``in_uv`` (2f), indiziert
    über ``indizes``.
    """
    teile: list[HochgeladenesTeil] = []
    for teilnetz in daten.teile:
        vbo_position = ctx.buffer(
            np.ascontiguousarray(teilnetz.positionen, dtype=np.float32).tobytes())
        vbo_normale = ctx.buffer(
            np.ascontiguousarray(teilnetz.normalen, dtype=np.float32).tobytes())
        vbo_uv = ctx.buffer(
            np.ascontiguousarray(teilnetz.uv, dtype=np.float32).tobytes())
        ibo = ctx.buffer(
            np.ascontiguousarray(teilnetz.indizes, dtype=np.uint32).tobytes())

        vao = ctx.vertex_array(programm, [
            (vbo_position, "3f", "in_position"),
            (vbo_normale, "3f", "in_normale"),
            (vbo_uv, "2f", "in_uv"),
        ], ibo)

        teile.append(HochgeladenesTeil(
            name=teilnetz.name, vao=vao, versatz=teilnetz.versatz.copy()))

    return Modell(
        teile=teile,
        basisfarbe=_textur_hochladen(ctx, daten.basisfarbe),
        metallic_rauheit=_textur_hochladen(ctx, daten.metallic_rauheit),
    )
