"""Persönlichkeit und Fehler eines KI-Fahrers — fest aus der Startnummer.

Gleiche Startnummer, gleicher Fahrer: Tests und Online-Rennen sehen dasselbe.
Die Persönlichkeit verschiebt Bremspunkt, Kurventempo und Angriffslust ein
wenig; die Fehlerquelle streut, je nach Stufe, kurze Patzer ein.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Persoenlichkeit:
    bremspunkt_px: float   # + bremst später, − früher
    kurve: float           # Faktor aufs Zieltempo
    konstanz: float        # 0,3 nervös … 1 konstant
    angriff: float         # 0,6 zurückhaltend … 1,4 bissig


def persoenlichkeit(seed: int, stufe) -> Persoenlichkeit:
    rng = random.Random(int(seed) * 7919 + 17)
    return Persoenlichkeit(bremspunkt_px=rng.uniform(-40.0, 40.0),
                           kurve=rng.uniform(0.985, 1.015),
                           konstanz=rng.uniform(0.3, 1.0),
                           angriff=rng.uniform(0.6, 1.4))


@dataclass
class Fehler:
    art: str       # "weit" (Linie zu weit), "spaet" (verbremst), "zoegern" (Gas zu spät)
    rest: float    # Sekunden
    staerke: float  # 0 … 1


class Fehlerquelle:
    ARTEN = ("weit", "spaet", "zoegern")

    def __init__(self, seed: int, stufe, pers: Persoenlichkeit) -> None:
        self._rng = random.Random(int(seed) * 104729 + 3)
        self._rate = stufe.fehler_je_min * (1.4 - 0.8 * pers.konstanz) / 60.0
        self.aktiv: Fehler | None = None

    def schritt(self, dt: float) -> Fehler | None:
        if self.aktiv is not None:
            self.aktiv.rest -= dt
            if self.aktiv.rest <= 0.0:
                self.aktiv = None
            return self.aktiv
        if self._rng.random() < self._rate * dt:
            self.aktiv = Fehler(self._rng.choice(self.ARTEN),
                                self._rng.uniform(0.8, 2.0),
                                self._rng.uniform(0.3, 1.0))
        return self.aktiv
