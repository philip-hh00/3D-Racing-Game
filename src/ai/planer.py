"""Bahnplaner im Frenet-Raum.

Alle 0,1 s: ~22 Kandidatenbahnen über 2,5 s — Querversätze zur Ideallinie, je
mit zwei Übergangslängen (quintischer Übergang, also ohne Knick). Jede Bahn
bekommt Kosten: Zeit (inklusive „hinter einem Langsameren festhängen“),
Abweichung von der Ideallinie, Wunsch der Taktik, Spurwechsel, und eine sehr
hohe Strafe für jede vorhergesagte Berührung. Das Tempo gilt je Bahn: wer in der Spur hinter einem Langsameren liegt, fährt
höchstens dessen Tempo plus Lückenanteil (Folgen), und die Zeit dieser Bahn
bezahlt das — so ergibt sich „erst bremsen, dann vorbei“ von selbst. Die
billigste gewinnt. Überholen,
Ausweichen und Nebeneinanderfahren ergeben sich daraus.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Gegner:
    s: float
    d: float
    v: float
    laenge: float
    breite: float


@dataclass
class Wunsch:
    zustand: str = "frei"
    seite: float | None = None
    gewicht_seite: float = 0.0
    darf_ausscheren: bool = True
    seitenabstand: float = 12.0
    spaeter_bremsen_px: float = 0.0
    tempo: float = 1.0
    versatz: float = 0.0


@dataclass
class Bahn:
    s: np.ndarray
    d: np.ndarray
    xy: np.ndarray
    v_soll: float
    versatz: float
    gefolgt: bool


def _quintisch(u: np.ndarray) -> np.ndarray:
    return u * u * u * (10.0 - 15.0 * u + 6.0 * u * u)


class Planer:
    SCHRITTE = 12
    HORIZONT_S = 2.5
    VERSAETZE = (0.0, 0.2, -0.2, 0.45, -0.45, 0.7, -0.7, 1.0, -1.0, 1.4, -1.4)
    NUR_SPUR = (0.0, 0.2, -0.2)
    UEBERGANG = (0.45, 1.0)
    W_IDEAL = 0.3
    W_WECHSEL = 0.3
    W_SEITE = 1.5
    W_WAND = 40.0
    KOLLISION = 1.0e4
    FOLGE_GAIN = 1.2
    KURVE_KOSTET = 0.35     # Tempoverlust abseits der Ideallinie in Kurven

    def __init__(self, plan, breite_px: float, laenge_px: float) -> None:
        self.plan = plan
        self.breite = float(breite_px)
        self.laenge = float(laenge_px)
        self._letzter = 0.0

    def planen(self, s0: float, d0: float, v0: float, gegner: list, wunsch: Wunsch) -> Bahn:
        erg = self._planen(s0, d0, v0, gegner, wunsch,
                           self.VERSAETZE if wunsch.darf_ausscheren else self.NUR_SPUR)
        if not wunsch.darf_ausscheren and (erg[0] >= self.KOLLISION
                                           or (erg[1].gefolgt and erg[1].v_soll < 60.0)):
            # Eingeklemmt oder ein (fast) stehendes Auto: dann doch ausweichen.
            erg = self._planen(s0, d0, v0, gegner, wunsch, self.VERSAETZE)
        _, bahn = erg
        self._letzter = bahn.versatz
        return bahn

    def _mass(self, g, w):
        return (0.5 * (self.laenge + g.laenge) + 15.0,
                0.5 * (self.breite + g.breite) + w.seitenabstand)

    def _planen(self, s0, d0, v0, gegner, w, versaetze):
        plan = self.plan
        st = plan.strecke
        hf = plan.halb_frei
        v_ref = max(float(v0), 120.0)
        horizont = max(v_ref * self.HORIZONT_S, 300.0)
        u = np.linspace(0.0, 1.0, self.SCHRITTE + 1)
        s_rel = u * horizont
        s_abs = s0 + s_rel
        d_id = plan.d_viele(s_abs) + w.versatz
        k_id = np.abs(plan.k_viele(s_abs))
        v_prof = plan.v_viele(s_abs + w.spaeter_bremsen_px) * w.tempo
        seg = np.diff(s_rel)
        rel0 = [(st.ds(s0, g.s), g) for g in gegner]
        gz = [(r0, g) + self._mass(g, w) for r0, g in rel0]
        beste = None
        for versatz in versaetze:
            ziel = np.clip(d_id + versatz * hf, -hf, hf)
            for uebergang in self.UEBERGANG:
                q = _quintisch(np.clip(s_rel / (uebergang * horizont), 0.0, 1.0))
                d = d0 + (ziel - d0) * q
                if abs(d0) <= hf:
                    d = np.clip(d, -hf, hf)
                abw = np.abs(d - d_id) / (2.0 * hf)
                v = v_prof * (1.0 - self.KURVE_KOSTET * abw * np.clip(k_id * 400.0, 0.0, 1.0))
                v = np.maximum(v, 30.0)
                # Schritt für Schritt: Folgen begrenzt das Tempo, dieses Tempo
                # bestimmt wieder die Zeit und damit, wo der Gegner dann steht.
                v_eff = v.copy()
                t = np.zeros(self.SCHRITTE + 1)
                for k in range(self.SCHRITTE + 1):
                    vk = float(v_eff[k])
                    tk = 0.0 if k == 0 else t[k - 1] + seg[k - 1] / max(0.5 * (v_eff[k - 1] + vk), 5.0)
                    for r0, g, laengs, quer in gz:
                        if abs(d[k] - g.d) < quer:
                            rel = r0 + g.v * tk - s_rel[k]
                            if rel > 0.0:
                                vk = min(vk, g.v + max(0.0, rel - laengs) * self.FOLGE_GAIN)
                    v_eff[k] = max(vk, 0.0)
                    if k:
                        t[k] = t[k - 1] + seg[k - 1] / max(0.5 * (v_eff[k - 1] + v_eff[k]), 5.0)
                kollision = 0.0
                for r0, g in rel0:
                    rel = r0 + g.v * t - s_rel
                    laengs, quer = self._mass(g, w)
                    treffer = (np.abs(d - g.d) < quer) & (np.abs(rel) < laengs)
                    if treffer.any():
                        erster = int(np.argmax(treffer))
                        kollision += self.KOLLISION * (1.0 + self.SCHRITTE - erster)
                v_soll = float(np.min(np.sqrt(v_eff * v_eff + 2.0 * plan.a_brems * s_rel)))
                gefolgt = bool(np.any(v_eff[:self.SCHRITTE // 2 + 1] < v[:self.SCHRITTE // 2 + 1] - 1e-6))
                zeit = float(t[-1]) / (horizont / v_ref)
                kosten = (zeit + kollision
                          + self.W_IDEAL * float(np.mean(((d - d_id) / hf) ** 2))
                          + self.W_WECHSEL * (versatz - self._letzter) ** 2
                          + self.W_WAND * float(np.sum(np.maximum(0.0, np.abs(d) - hf) ** 2)) / hf ** 2)
                if w.seite is not None:
                    kosten += self.W_SEITE * w.gewicht_seite * ((d[-1] - w.seite) / hf) ** 2
                if beste is None or kosten < beste[0]:
                    beste = (kosten, (d, v_soll, versatz, gefolgt))
        kosten, (d, v_soll, versatz, gefolgt) = beste
        return kosten, Bahn(s_abs, d, st.xy_viele(s_abs, d), float(v_soll), float(versatz), bool(gefolgt))
