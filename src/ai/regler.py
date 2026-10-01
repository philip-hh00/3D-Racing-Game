"""Bahnregler: aus einer Bahn (x/y-Punkte) Lenkung, Gas und Bremse.

Lenkung nach *Pure Pursuit*: ein Punkt auf der Bahn im Vorschauabstand, der
Radeinschlag, der genau dorthin einen Kreisbogen fährt:
``delta = atan(2 · Radstand · sin(alpha) / Ld)``. Ausgegeben wird er als Anteil
von ``PhysicsBody.max_einschlag`` — die Physik setzt ihn mit ``is_analog`` um.
"""
from __future__ import annotations

import math

import numpy as np


class Bahnregler:
    VORSCHAU_MIN = 70.0     # px
    VORSCHAU_MAX = 420.0    # px
    VORSCHAU_ZEIT = 0.32    # s
    GAS_BAND = 6.0          # px/s: darunter wird das Gas weich ausgeblendet
    TOTBAND = 4.0           # px/s zu schnell, bevor gebremst wird
    #: Schräglauf (Grad), ab dem das Gas zurückgenommen wird / ganz weg ist. Normaler
    #: Kurvenschlupf liegt bei 2–8°; wer nach einem Kontakt dauerhaft mit 30–60°
    #: quer rutscht, fuhr mit Vollgas weiter und kam nicht mehr heraus (gp/Feld:
    #: 29 → 11 Wandberührungen über sechs Startreihenfolgen). Sanfteres Anheben
    #: schon bei 10° war mit Folgeabstand schlechter (Heckgrip sinkt mit dem Gas).
    SCHLUPF_AB = 28.0
    SCHLUPF_VOLL = 40.0

    def __init__(self, fahrzeug) -> None:
        self.fz = fahrzeug
        xs = [v.x for v in fahrzeug.physics.shape.get_vertices()]
        self.radstand = (max(xs) - min(xs)) * float(fahrzeug.physics.wheelbase_ratio)
        self.grip = float(fahrzeug.config.grip)
        self.vorschau: tuple[float, float] = (0.0, 0.0)

    def _vorschaupunkt(self, bahn: np.ndarray, pos: np.ndarray, v: float) -> np.ndarray:
        ld = min(self.VORSCHAU_MAX, max(self.VORSCHAU_MIN, self.VORSCHAU_ZEIT * v + self.VORSCHAU_MIN))
        k0 = int(np.argmin(np.sum((bahn - pos) ** 2, axis=1)))
        rest = bahn[k0:]
        if len(rest) < 2:
            return bahn[-1]
        seg = np.diff(rest, axis=0)
        laengen = np.hypot(seg[:, 0], seg[:, 1])
        summe = np.cumsum(laengen)
        j = int(np.searchsorted(summe, ld))
        if j >= len(summe):
            richt = seg[-1] / max(laengen[-1], 1e-9)
            return rest[-1] + richt * (ld - summe[-1])
        vorher = summe[j] - laengen[j]
        u = (ld - vorher) / max(laengen[j], 1e-9)
        return rest[j] + seg[j] * u

    def lenkung(self, bahn_xy: np.ndarray, v: float) -> float:
        body = self.fz.physics.body
        pos = np.array([body.position.x, body.position.y], dtype=np.float64)
        ziel = self._vorschaupunkt(np.asarray(bahn_xy, dtype=np.float64), pos, v)
        self.vorschau = (float(ziel[0]), float(ziel[1]))
        dx, dy = ziel - pos
        ld = max(math.hypot(dx, dy), 1.0)
        alpha = math.atan2(math.sin(math.atan2(dy, dx) - body.angle),
                           math.cos(math.atan2(dy, dx) - body.angle))
        delta = math.atan2(2.0 * self.radstand * math.sin(alpha), ld)
        grenze = self.fz.physics.max_einschlag(self.grip, delta)
        return max(-1.0, min(1.0, delta / max(grenze, 1e-4)))

    def pedale(self, v: float, v_soll: float, schlupf_deg: float = 0.0) -> tuple[float, float]:
        e = v_soll - v
        if e > 0.0:
            gas = min(1.0, 0.55 + e * 0.05)
            if e < self.GAS_BAND:
                gas *= e / self.GAS_BAND
            frei = (schlupf_deg - self.SCHLUPF_AB) / (self.SCHLUPF_VOLL - self.SCHLUPF_AB)
            return gas * (1.0 - max(0.0, min(1.0, frei))), 0.0
        if e >= -self.TOTBAND:
            return 0.0, 0.0
        return 0.0, min(1.0, (-e - self.TOTBAND) * 0.06)
