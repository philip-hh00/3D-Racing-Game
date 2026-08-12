"""Kleine Matrizenhelfer für Modelltransformationen.

Bewusst getrennt von :mod:`src.render3d.camera`: dort geht es um Blick und
Projektion, hier darum, wo ein Teil im Raum sitzt. Beide folgen derselben
Vereinbarung — ``numpy.ndarray`` mit ``shape=(4, 4)``, ``float32``,
mathematische Zeilenkonvention (``v' = M @ v`` mit ``v`` als Spaltenvektor),
und beim Hochladen nach GLSL wird transponiert.
"""
from __future__ import annotations

import numpy as np


def einheit() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def verschiebung(x: float, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    """Verschiebung. Nimmt auch ein Tripel als erstes Argument."""
    if np.ndim(x) == 1:
        x, y, z = (float(w) for w in x)
    m = einheit()
    m[:3, 3] = (x, y, z)
    return m


def _drehung(achse: int, winkel: float) -> np.ndarray:
    """Drehung um eine Koordinatenachse, im Rechtsschraubensinn."""
    c, s = np.cos(winkel), np.sin(winkel)
    m = einheit()
    i, j = [(1, 2), (2, 0), (0, 1)][achse]
    m[i, i] = c
    m[i, j] = -s
    m[j, i] = s
    m[j, j] = c
    return m


def drehung_x(winkel: float) -> np.ndarray:
    return _drehung(0, winkel)


def drehung_y(winkel: float) -> np.ndarray:
    """Um die Querachse — das ist die Drehung eines rollenden Rades."""
    return _drehung(1, winkel)


def drehung_z(winkel: float) -> np.ndarray:
    """Um die Hochachse — Gierwinkel des Fahrzeugs und Lenkeinschlag."""
    return _drehung(2, winkel)


def fahrzeug(pos_m, gierwinkel_rad: float) -> np.ndarray:
    """Wo das Fahrzeug steht und wohin es zeigt.

    ``pos_m`` darf zwei oder drei Komponenten haben; mit zweien liegt das
    Fahrzeug auf ``z = 0``. Das Spiel führt seine Positionen in 2D, und diese
    Bequemlichkeit spart an jeder Aufrufstelle eine Umrechnung.
    """
    p = np.asarray(pos_m, dtype=np.float64)
    z = float(p[2]) if p.size > 2 else 0.0
    return verschiebung(float(p[0]), float(p[1]), z) @ drehung_z(gierwinkel_rad)
