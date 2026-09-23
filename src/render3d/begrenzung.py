"""Streckenbegrenzung: Leitplanke, Betonmauer oder Reifenwand an der Fahrbahnkante.

Die Wände des Spiels (``outer_wall``/``inner_wall``) fallen mit der
Fahrbahnkante zusammen. Genau dort steht in 3D die Begrenzung — ein Auto, das
abprallt, berührt sichtbar die Planke. Gebaut wird durch Extrusion eines
Querprofils entlang der Kante, rein mit numpy.

Das Profil ist in ``(aussen_m, hoch_m)`` notiert: ``aussen`` zählt von der
Fahrbahnkante weg, nach außen positiv. Die Reihenfolge läuft so, dass die
Fläche zur Strecke hin zeigt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Streifen:
    """Ein Stück Geometrie mit eigenem Material, wie ``track_mesh.Band``."""

    name: str
    positionen: np.ndarray
    normalen: np.ndarray
    uv: np.ndarray
    indizes: np.ndarray
    farbe: tuple = (0.6, 0.6, 0.6)
    textur: str = ""
    metallic: float = 0.0
    rauheit: float = 0.8
    kachel_m: float = 2.0


#: Querprofile je Stil: Liste von Teilen (Name, Profilpunkte, Material).
PROFILE = {
    "leitplanke": [
        ("planke", [(0.12, 0.48), (0.05, 0.56), (0.1, 0.63), (0.05, 0.7), (0.12, 0.78),
                    (0.16, 0.78), (0.16, 0.48), (0.12, 0.48)],
         dict(farbe=(0.72, 0.74, 0.76), metallic=0.85, rauheit=0.38)),
    ],
    "betonmauer": [
        ("mauer", [(0.0, 0.0), (0.02, 0.08), (0.14, 0.32), (0.2, 0.95), (0.4, 0.95),
                   (0.46, 0.32), (0.58, 0.08), (0.6, 0.0)],
         dict(textur="betonwand", farbe=(0.78, 0.78, 0.76), rauheit=0.85, kachel_m=2.5)),
        ("streifen", [(0.195, 0.8), (0.2, 0.95)],
         dict(farbe=(0.75, 0.1, 0.08), rauheit=0.6)),
    ],
    "reifenwand": [
        ("reifen", [(0.1, 0.0), (0.02, 0.12), (0.0, 0.3), (0.02, 0.5), (0.0, 0.68),
                    (0.03, 0.84), (0.2, 0.92), (0.55, 0.9), (0.62, 0.0)],
         dict(farbe=(0.06, 0.06, 0.065), rauheit=0.9)),
        ("band", [(0.0, 0.62), (0.0, 0.74)],
         dict(farbe=(0.85, 0.85, 0.83), rauheit=0.6)),
    ],
}


def _normalen_2d(kante: np.ndarray) -> np.ndarray:
    t = np.roll(kante, -1, axis=0) - np.roll(kante, 1, axis=0)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-9)
    return np.stack([-t[:, 1], t[:, 0]], axis=1)


def extrudieren(name: str, kante: np.ndarray, aussen: np.ndarray, profil, material: dict) -> Streifen:
    """Ein Profil entlang einer geschlossenen Kante ziehen.

    ``aussen``: Richtung je Kantenpunkt, weg von der Fahrbahn, Länge 1.
    """
    kante = np.asarray(kante, dtype=np.float64)
    n = len(kante)
    profil = np.asarray(profil, dtype=np.float64)
    m = len(profil)
    # Profilnormalen (2D, in der Ebene aussen/hoch) je Segment.
    d = np.diff(profil, axis=0)
    seg_n = np.stack([d[:, 1], -d[:, 0]], axis=1)
    seg_n /= np.maximum(np.linalg.norm(seg_n, axis=1, keepdims=True), 1e-9)
    # Punkte doppelt je Segment (harte Kanten im Profil).
    pos, nor, uv, idx = [], [], [], []
    bogen = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(kante, axis=0), axis=1))])
    bogen = np.concatenate([bogen, [bogen[-1] + np.linalg.norm(kante[0] - kante[-1])]])
    kante_z = np.vstack([kante, kante[:1]])
    aussen_z = np.vstack([aussen, aussen[:1]])
    laenge_profil = np.concatenate([[0.0], np.cumsum(np.linalg.norm(d, axis=1))])
    basis = 0
    for s in range(m - 1):
        for k in (s, s + 1):
            p = kante_z + aussen_z * profil[k, 0]
            z = np.full((n + 1, 1), profil[k, 1])
            pos.append(np.hstack([p, z]))
            nn = np.hstack([aussen_z * seg_n[s, 0], np.full((n + 1, 1), seg_n[s, 1])])
            nor.append(nn)
            uv.append(np.stack([bogen, np.full(n + 1, laenge_profil[k])], axis=1))
        i = np.arange(n)
        a = basis + i
        b = basis + i + 1
        c = basis + (n + 1) + i + 1
        e = basis + (n + 1) + i
        idx.append(np.stack([a, b, c], axis=1))
        idx.append(np.stack([a, c, e], axis=1))
        basis += 2 * (n + 1)
    return Streifen(
        name=name,
        positionen=np.vstack(pos).astype(np.float32),
        normalen=np.vstack(nor).astype(np.float32),
        uv=np.vstack(uv).astype(np.float32),
        indizes=np.vstack(idx).astype(np.uint32),
        **material)


def pfosten(kante: np.ndarray, aussen: np.ndarray, abstand_m: float = 2.0) -> Streifen:
    """Pfosten hinter der Leitplanke, als einfache Kästen."""
    kante = np.asarray(kante)
    seg = np.linalg.norm(np.roll(kante, -1, axis=0) - kante, axis=1)
    bogen = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
    stellen = np.arange(0.0, bogen[-1], abstand_m)
    ii = np.searchsorted(bogen, stellen, side="right") - 1
    ecken = np.array([[0.16, -0.05], [0.28, -0.05], [0.28, 0.05], [0.16, 0.05]])
    pos, nor, uv, idx = [], [], [], []
    for k, i in enumerate(ii):
        a = aussen[i]
        t = np.array([a[1], -a[0]])
        basis = len(pos)
        for (o, q) in ecken:
            xy = kante[i] + a * o + t * q
            pos.append((xy[0], xy[1], 0.0))
            pos.append((xy[0], xy[1], 0.8))
        for s in range(4):
            v0, v1 = basis + 2 * s, basis + 2 * ((s + 1) % 4)
            idx += [(v0, v1, v1 + 1), (v0, v1 + 1, v0 + 1)]
    pos = np.asarray(pos, dtype=np.float32)
    nor = np.zeros_like(pos)
    nor[:, :2] = pos[:, :2] - np.repeat(kante[ii], 8, axis=0)
    nor /= np.maximum(np.linalg.norm(nor, axis=1, keepdims=True), 1e-9)
    uv = np.zeros((len(pos), 2), dtype=np.float32)
    return Streifen("pfosten", pos, nor.astype(np.float32), uv,
                    np.asarray(idx, dtype=np.uint32),
                    farbe=(0.5, 0.52, 0.55), metallic=0.8, rauheit=0.45)


def bauen(netz, stil: str) -> list[Streifen]:
    """Begrenzung beidseits der Strecke im gewünschten Stil."""
    if stil not in PROFILE or len(netz.rand_links) < 3:
        return []
    ergebnis = []
    for seite, kante, aussen in (("links", netz.rand_links, netz.links),
                                 ("rechts", netz.rand_rechts, -netz.links)):
        # Links läuft das Profil mit der Fahrtrichtung, rechts dagegen — sonst
        # zeigten die Flächen auf einer Seite von der Strecke weg.
        if seite == "rechts":
            kante, aussen = kante[::-1].copy(), aussen[::-1].copy()
        for teil, profil, material in PROFILE[stil]:
            prof = profil if seite == "links" else list(reversed(profil))
            ergebnis.append(extrudieren(f"{stil}_{teil}_{seite}", kante, aussen, prof, dict(material)))
        if stil == "leitplanke":
            ergebnis.append(pfosten(kante, aussen))
    return ergebnis
