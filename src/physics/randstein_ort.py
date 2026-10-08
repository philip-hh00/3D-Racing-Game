"""Wo ein Auto auf einem Randstein steht (für die Controller-Vibration).

Die Physik kennt keine Randsteine — sie sind Darstellung (``track_mesh``) und
fassen das Auto nicht an. Für das Gefühl am Controller genügt aber zu wissen,
ob ein Rad auf einem liegt. Dafür werden dieselben Masken benutzt, mit denen
das Netz die Randsteine baut (``track_mesh.randstein_masken``): wo sie dort
liegen, liegt auch hier einer, und das Rad sitzt genau dann darauf, wenn es
im äußersten Meter der Fahrbahn steht.

Gerechnet wird in Pixeln der Spielwelt, mit dem Frenet-Gerüst der KI
(``StreckeFrenet``) über **dieselben Mittellinienpunkte** wie das Netz — so
passen Maskenindex und Segment zusammen.
"""
from __future__ import annotations

import math

import numpy as np

from src.ai.strecke_frenet import StreckeFrenet
from src.core.settings import M_PER_PX

#: Breite eines Randsteins in Metern (``track_mesh.bauen(randstein_m=1.0)``).
RANDSTEIN_BREITE_M = 1.0
#: Die Räder sitzen so weit neben der Fahrzeugmitte (m): Spurweite halbe, grob.
HALBE_SPUR_M = 0.85
#: Halber Radstand (m), für den Versatz bei schrägem Auto.
HALBER_RADSTAND_M = 1.3


class Randsteine:
    """Randstein-Abfrage für eine Strecke: ``auf_randstein(x_px, y_px, gier)``."""

    def __init__(self, netz) -> None:
        from src.render3d import track_mesh
        mitte_px = np.asarray(netz.mittellinie, dtype=np.float64) / M_PER_PX
        self.halbe_breite_px = float(netz.halbe_breite_m) / M_PER_PX
        self.frenet = StreckeFrenet(mitte_px, 2.0 * self.halbe_breite_px)
        n = len(mitte_px)
        punktabstand = float(netz.laenge_m) / max(n, 1)
        self.links, self.rechts = track_mesh.randstein_masken(
            np.asarray(netz.kruemmung, dtype=np.float64), punktabstand)
        self._hinweis: dict = {}

    @classmethod
    def aus_streckendaten(cls, strecke: dict) -> "Randsteine":
        """Aus den JSON-Daten einer Strecke (ohne OpenGL, z. B. im Test)."""
        from src.render3d import track_mesh
        return cls(track_mesh.bauen(strecke))

    def auf_randstein(self, x_px: float, y_px: float, gier: float, schluessel=None) -> bool:
        """Steht ein Rad des Autos an dieser Stelle auf einem Randstein?

        ``schluessel`` (z. B. die Fahrzeugnummer) merkt sich das Segment für die
        nächste Abfrage, damit nur ein Fenster um die letzte Stelle abgesucht wird.
        """
        f = self.frenet
        hinweis = self._hinweis.get(schluessel)
        s, d, i = f.sd(x_px, y_px, hinweis=hinweis)
        if schluessel is not None:
            self._hinweis[schluessel] = i
        # Winkel zur Strecke: ein schräges Auto ragt mit einer Ecke weiter hinaus.
        richt = f.seg_dir[i]
        winkel = gier - math.atan2(float(richt[1]), float(richt[0]))
        quer_m = HALBE_SPUR_M * abs(math.cos(winkel)) + HALBER_RADSTAND_M * abs(math.sin(winkel))
        aussen_px = abs(d) + quer_m / M_PER_PX
        beginn_px = self.halbe_breite_px - RANDSTEIN_BREITE_M / M_PER_PX
        if aussen_px < beginn_px:
            return False
        maske = self.links if d > 0.0 else self.rechts      # Frenet: links positiv
        return bool(maske[i % len(maske)])
