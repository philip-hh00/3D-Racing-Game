"""Taktik der KI-Fahrer: was will ich gerade — und darf ich das auf dieser Stufe?

Zustände: frei, folgen, windschatten, angriff (innen in der Bremszone),
nebeneinander (Spur halten, nicht reindrücken), verteidigen (vor der Bremszone
einmal nach innen, dann halten — kein Zickzack). Das Ergebnis ist ein
:class:`~src.ai.planer.Wunsch`; entscheiden tut der Planer über seine Kosten.
"""
from __future__ import annotations

import numpy as np

from src.ai.planer import Wunsch

BEREICH_VORNE = 700.0     # px
BEREICH_HINTEN = 300.0    # px
BREMSZONE_SUCHE = 1500.0  # px voraus
BREMSZONE_ABFALL = 0.8    # Zieltempo fällt unter diesen Anteil
ABSTAND_BASIS = 0.10      # s Folgeabstand bei vollem Mut …
ABSTAND_MUT = 0.35        # … plus bis zu so viel bei Mut 0


class Taktik:
    def __init__(self, plan, stufe, pers, breite_px: float, laenge_px: float) -> None:
        self.plan = plan
        self.stufe = stufe
        self.pers = pers
        self.breite = float(breite_px)
        self.laenge = float(laenge_px)
        self._verteidigt_bis: float | None = None
        self._verteidigt_seite = 0.0

    def bremszone(self, s: float, v: float):
        plan = self.plan
        x = np.linspace(0.0, BREMSZONE_SUCHE, 76)
        vz = plan.v_viele(s + x)
        grenze = BREMSZONE_ABFALL * min(v, float(vz[0]))
        unter = vz < grenze
        if not unter.any():
            return None
        i = int(np.argmax(unter))
        tief = i + int(np.argmin(vz[i:min(len(vz), i + 25)]))
        k = plan.k_bei(s + x[tief])
        return float(x[i]), float(plan.strecke.wrap(s + x[tief])), (1.0 if k >= 0 else -1.0)

    def entscheiden(self, s: float, d: float, v: float, gegner: list) -> Wunsch:
        st = self.plan.strecke
        hf = self.plan.halb_frei
        stufe = self.stufe
        w = Wunsch(seitenabstand=8.0 + (1.0 - stufe.mut) * 22.0,
                   abstand_s=ABSTAND_BASIS + (1.0 - stufe.mut) * ABSTAND_MUT)
        rel = [(st.ds(s, g.s), g) for g in gegner]
        neben = [(r, g) for r, g in rel if abs(r) < 0.5 * (self.laenge + g.laenge) + 10.0 and abs(d - g.d) >= 0.5 * (self.breite + g.breite)]
        vorne = [(r, g) for r, g in rel if 0.0 < r < BEREICH_VORNE and (r, g) not in neben]
        hinten = [(r, g) for r, g in rel if -BEREICH_HINTEN < r < 0.0 and (r, g) not in neben]
        if self._verteidigt_bis is not None and st.ds(s, self._verteidigt_bis) <= 0.0:
            self._verteidigt_bis = None
        if neben:
            w.zustand = "nebeneinander"
            w.darf_ausscheren = False
            w.seite = d
            w.gewicht_seite = 1.0
            return w
        if vorne:
            abstand, g = min(vorne, key=lambda rg: rg[0])
            w.zustand = "windschatten" if abstand < 400.0 else "folgen"
            if stufe.ueberholen_nur_langsame and g.v > 0.85 * self.plan.v_bei(g.s):
                w.darf_ausscheren = False
                return w
            bz = self.bremszone(s, v)
            if stufe.bremszone_angriff and bz is not None and bz[0] < 900.0 and abstand < 250.0:
                w.zustand = "angriff"
                w.seite = bz[2] * 0.8 * hf
                w.gewicht_seite = self.pers.angriff
                w.spaeter_bremsen_px = 60.0 * self.pers.angriff
            return w
        if self._verteidigt_bis is not None:
            w.zustand = "verteidigen"
            w.seite = self._verteidigt_seite
            w.gewicht_seite = 1.0
            return w
        if hinten and stufe.verteidigen:
            _, g = max(hinten, key=lambda rg: rg[0])
            bz = self.bremszone(s, v)
            if bz is not None and bz[0] < 600.0 and g.v >= v - 20.0:
                self._verteidigt_bis = bz[1]
                self._verteidigt_seite = bz[2] * 0.6 * hf
                w.zustand = "verteidigen"
                w.seite = self._verteidigt_seite
                w.gewicht_seite = 1.0
        return w
