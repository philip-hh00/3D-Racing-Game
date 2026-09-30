"""Die Strecke in Frenet-Koordinaten.

``s`` ist die Bogenlänge entlang der Mittellinie in Fahrtrichtung, ``d`` der
Querversatz, **links positiv**. Planer, Taktik und Fahrplan rechnen nur so; nach
x/y geht es erst für den Lenkregler zurück. Gebaut aus ``Track.centerline``
(Stützpunkte ~20 px auseinander), also für jede Strecke sofort da.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


class StreckeFrenet:
    def __init__(self, mitte: Sequence[tuple[float, float]], breite: float) -> None:
        p = np.asarray(mitte, dtype=np.float64)
        if p.ndim != 2 or len(p) < 3:
            raise ValueError("Mittellinie braucht mindestens drei Punkte")
        self.punkte = p
        self.n = len(p)
        seg = np.roll(p, -1, axis=0) - p
        self.seg_len = np.maximum(np.hypot(seg[:, 0], seg[:, 1]), 1e-9)
        self.seg_dir = seg / self.seg_len[:, None]
        self.s = np.concatenate(([0.0], np.cumsum(self.seg_len)[:-1]))
        self.laenge = float(np.sum(self.seg_len))
        t = np.roll(p, -1, axis=0) - np.roll(p, 1, axis=0)
        t /= np.maximum(np.hypot(t[:, 0], t[:, 1]), 1e-9)[:, None]
        self.normale = np.stack([-t[:, 1], t[:, 0]], axis=1)
        self.halb = float(breite) / 2.0

    # -- s ---------------------------------------------------------------
    def wrap(self, s: float) -> float:
        return float(s) % self.laenge

    def ds(self, a: float, b: float) -> float:
        """Kürzester Weg von a nach b entlang der Strecke, vorzeichenbehaftet."""
        d = (float(b) - float(a)) % self.laenge
        return d - self.laenge if d >= self.laenge / 2.0 else d

    def index(self, s: float) -> int:
        return int(np.searchsorted(self.s, self.wrap(s), side="right") - 1)

    # -- s/d → x/y -----------------------------------------------------------
    def xy_viele(self, s: np.ndarray, d: np.ndarray) -> np.ndarray:
        s = np.mod(np.asarray(s, dtype=np.float64), self.laenge)
        d = np.asarray(d, dtype=np.float64)
        i = np.clip(np.searchsorted(self.s, s, side="right") - 1, 0, self.n - 1)
        u = (s - self.s[i]) / self.seg_len[i]
        j = (i + 1) % self.n
        basis = self.punkte[i] + self.seg_dir[i] * (self.seg_len[i] * u)[:, None]
        nrm = self.normale[i] * (1.0 - u)[:, None] + self.normale[j] * u[:, None]
        nrm /= np.maximum(np.hypot(nrm[:, 0], nrm[:, 1]), 1e-9)[:, None]
        return basis + nrm * d[:, None]

    def xy(self, s: float, d: float) -> tuple[float, float]:
        p = self.xy_viele(np.array([s]), np.array([d]))[0]
        return float(p[0]), float(p[1])

    # -- x/y → s/d -----------------------------------------------------------
    def sd(self, x: float, y: float, hinweis: int | None = None) -> tuple[float, float, int]:
        """Lotfußpunkt auf der Mittellinie: (s, d, Segment).

        Mit ``hinweis`` (Segment vom letzten Aufruf) wird nur ±40 Segmente
        darum gesucht, sonst überall.
        """
        if hinweis is None:
            idx = np.arange(self.n)
        else:
            idx = (int(hinweis) + np.arange(-40, 41)) % self.n
        a = self.punkte[idx]
        r = np.array([x, y], dtype=np.float64) - a
        u = np.clip(np.einsum("ij,ij->i", r, self.seg_dir[idx]), 0.0, self.seg_len[idx])
        naechst = a + self.seg_dir[idx] * u[:, None]
        abst = np.sum((np.array([x, y]) - naechst) ** 2, axis=1)
        k = int(np.argmin(abst))
        i = int(idx[k])
        rel = r[k]
        richt = self.seg_dir[i]
        d = float(richt[0] * rel[1] - richt[1] * rel[0])
        return self.wrap(self.s[i] + u[k]), d, i
