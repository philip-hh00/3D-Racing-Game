"""Ursprung setzen. Veraendert das Mesh an Ort und Stelle.

Warum das noetig ist: TRELLIS legt den Ursprung in die Mitte des Modells. Wer so
ein Auto im Renderer an eine Fahrbahnposition setzt, bekommt ein Fahrzeug, das
zur Haelfte im Asphalt steckt - oder, nach der ersten Korrektur von Hand, eines
das schwebt. Mit dem Ursprung am Bodenkontakt ist die Fahrzeugposition genau
das, was der Physikcode ohnehin schon fuehrt: der Punkt, auf dem das Auto steht.
"""
from __future__ import annotations

import trimesh


def auf_bodenkontakt(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Ursprung mittig unter das Fahrzeug: x/y in die Bbox-Mitte, z auf die
    Unterkante. Gibt dasselbe Mesh zurueck, damit sich Aufrufe verketten lassen.
    """
    unten, oben = mesh.bounds
    mesh.apply_translation((
        -(unten[0] + oben[0]) / 2.0,
        -(unten[1] + oben[1]) / 2.0,
        -unten[2],
    ))
    return mesh


def auf_nabenmitte(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Ursprung eines Rades in die Nabe, also in die Bbox-Mitte.

    Anders als bei der Karosserie ist hier die Mitte richtig: das Rad wird spaeter
    um diesen Punkt gedreht und gelenkt. Ein Ursprung am Reifenboden wuerde beim
    Drehen einen Kreis beschreiben statt sich zu drehen.
    """
    mesh.apply_translation(-mesh.bounding_box.centroid)
    return mesh
