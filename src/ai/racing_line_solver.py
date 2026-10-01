"""Geometric racing-line solver – computes a fast line for *any* track at load.

No training, no per-track data files: given a track's center polyline and its
width, an elastic-band / curvature-minimisation pass produces a smooth,
apex-cutting line that stays inside the drivable corridor. It runs in a few
milliseconds at track load and therefore works on hand-made and (future)
user-designed tracks alike.

Method (minimum-curvature within a corridor):
    1. Start the line on the centerline.
    2. Repeatedly pull every point toward the midpoint of its two neighbours
       (Laplacian smoothing — this is the "make the line straight / minimise
       curvature" force).
    3. After each pull, clamp the point back into the corridor (track half-width
       minus the car's half-width and a safety margin), measured along the fixed
       centerline normal. On straights the smoothing changes nothing; in corners
       it pulls the line to the inside until the clamp stops it at the apex,
       which is exactly the racing line.

The result also carries per-point curvature, which the speed-profile stage
(:mod:`src.ai.speed_profile`) turns into cornering speed limits.
"""
from __future__ import annotations

import math

import numpy as np
from dataclasses import dataclass


@dataclass
class RacingLineGeometry:
    """A solved racing line plus the geometry the speed profile needs."""

    points: list[tuple[float, float]]      # absolute racing-line points (closed loop)
    offsets: list[float]                   # signed lateral offset from the centerline
    normals: list[tuple[float, float]]     # centerline left-normal at each index
    curvature: list[float]                 # 1/radius (px^-1), unsigned, at each point
    signed_curvature: list[float]          # +ve = line turns left (CCW)
    seg_len: list[float]                   # distance from point i to i+1
    half_corridor: float                   # max |offset| that was allowed

    @property
    def length(self) -> float:
        return sum(self.seg_len)

    def max_curvature(self) -> float:
        return max(self.curvature) if self.curvature else 0.0


def _centerline_normals(center: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Unit left-normal at each centerline point (from the local tangent)."""
    n = len(center)
    normals: list[tuple[float, float]] = []
    for i in range(n):
        ax, ay = center[(i - 1) % n]
        bx, by = center[(i + 1) % n]
        tx, ty = bx - ax, by - ay
        length = math.hypot(tx, ty) or 1.0
        tx, ty = tx / length, ty / length
        normals.append((-ty, tx))  # +90° → left of travel direction
    return normals


def _menger_curvature(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    """Curvature (1/radius) of the circle through three points; 0 if collinear."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    acx, acy = c[0] - a[0], c[1] - a[1]
    area2 = abs(abx * acy - aby * acx)          # 2 × triangle area
    d_ab = math.hypot(abx, aby)
    d_bc = math.hypot(c[0] - b[0], c[1] - b[1])
    d_ca = math.hypot(a[0] - c[0], a[1] - c[1])
    denom = d_ab * d_bc * d_ca
    if denom < 1e-9:
        return 0.0
    return 2.0 * area2 / denom                  # 4·area / (|AB||BC||CA|)


def compute_racing_line(
    center: list[tuple[float, float]],
    track_width: float,
    car_width: float = 28.0,
    margin: float = 16.0,
    iterations: int = 800,
    weight: float = 0.35,
    corner_pull: float = 0.45,
    tight_radius: float = 130.0,
    outside_factor: float = 0.5,
    kruemmungsanteil: float = 0.3,
) -> RacingLineGeometry:
    """Solve a fast line for a closed center polyline (numpy, a few ms per 100 points).

    Der Kurs ist ein Gemisch aus kürzestem Weg (Laplace-Glättung) und kleinster
    Krümmung (bi-harmonisch, Anteil ``kruemmungsanteil``) im Korridor: beides
    zusammen ergibt von selbst Außen-Innen-Außen mit spätem Scheitelpunkt. Der
    Korridor ist überall gleich breit (Strecke minus Auto minus ``margin``).

    Früher kamen Vorhalte dazu (Innenseite vor Kurven sperren, Mitte auf kurzen
    Geraden, „S-Kurven“-Kürzung). Sie kosteten auf *city* mit dem Kompaktwagen
    rund 3 s je Runde (28,3 s statt 21,4 s bei gleicher Haftung und 0 Wandkontakten):
    das Auto ist traktionsbegrenzt (~53 px/s²), Tempo geht nur durch
    Kurvenradius und Weglänge zu gewinnen — ein verengter Korridor wirkt wie
    eine zu enge Kurve in jeder Kurve.

    Args:
        center:       Ordered centerline points forming a closed loop.
        track_width:  Full drivable width (px).
        car_width:    Car body width (px) – keeps the whole car off the wall.
        margin:       Gap between car edge and wall (px).
        iterations:   Smoothing iterations.
        weight:       Per-iteration pull strength toward the target.
        corner_pull:  Vorsicht in engen Kurven (0 = voller Scheitelpunkt;
                      0.45 = die Innenseite in den engsten Kurven um bis zu
                      ~22 % des Korridors zurücknehmen). Pro Stufe verschieden.
        tight_radius: Centerline radius (px) at/below which a corner counts as
                      fully "tight" for the corner_pull reduction.
        outside_factor: Anteil der Rücknahme, der auf die Außenseite entfällt.
    """
    n = len(center)
    if n < 3:
        normals = _centerline_normals(center) if center else []
        z = [0.0] * n
        return RacingLineGeometry(list(center), z, normals, z, list(z), list(z), 0.0)

    c = np.asarray(center, dtype=np.float64)
    nor = np.asarray(_centerline_normals(center), dtype=np.float64)
    half_corridor = max(4.0, track_width / 2.0 - car_width / 2.0 - margin)

    def kruemmung(p):
        a, b = np.roll(p, 1, axis=0), np.roll(p, -1, axis=0)
        ab, bc, ca = p - a, b - p, a - b
        kreuz = ab[:, 0] * bc[:, 1] - ab[:, 1] * bc[:, 0]
        nenner = np.hypot(*ab.T) * np.hypot(*bc.T) * np.hypot(*ca.T)
        k = np.where(nenner > 1e-9, 2.0 * np.abs(kreuz) / np.maximum(nenner, 1e-9), 0.0)
        return k, kreuz

    # Korridor je Punkt: in engen Kurven innen (und etwas außen) zurücknehmen.
    k_mitte, kreuz_mitte = kruemmung(c)
    eng = np.minimum(1.0, k_mitte * max(1.0, tight_radius)) ** 2
    zug = corner_pull * 0.5 * eng
    innen = half_corridor * (1.0 - zug)
    aussen = half_corridor * (1.0 - zug * outside_factor)
    lim_links = np.where(kreuz_mitte >= 0.0, innen, aussen)
    lim_rechts = np.where(kreuz_mitte >= 0.0, aussen, innen)

    p = c.copy()
    anteil = float(kruemmungsanteil)
    for _ in range(iterations):
        a, b = np.roll(p, 1, axis=0), np.roll(p, -1, axis=0)
        a2, b2 = np.roll(p, 2, axis=0), np.roll(p, -2, axis=0)
        laplace = 0.5 * (a + b)
        bih = (4.0 * (a + b) - (a2 + b2)) / 6.0
        ziel = (1.0 - anteil) * laplace + anteil * bih
        m = p + (ziel - p) * weight
        off = np.sum((m - c) * nor, axis=1)
        off = np.clip(off, -lim_rechts, lim_links)
        p = c + nor * off[:, None]

    offsets = np.sum((p - c) * nor, axis=1)
    k, kreuz = kruemmung(p)
    signed = k * np.where(kreuz >= 0.0, 1.0, -1.0)
    seg = np.hypot(*(np.roll(p, -1, axis=0) - p).T)
    return RacingLineGeometry(
        [(float(x), float(y)) for x, y in p], offsets.tolist(), [tuple(r) for r in nor.tolist()],
        k.tolist(), signed.tolist(), seg.tolist(), half_corridor,
    )
