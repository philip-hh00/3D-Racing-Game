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
    # Abweichungen von der Ideallinie müssen fahrbar und wandsicher sein:
    # - Wandreserve: wer von der Ideallinie abweicht (Ausweichen, Angriff,
    #   Nebeneinander), kommt der Wand höchstens bis ``halb_frei - WAND_RESERVE``
    #   nahe (die Ideallinie selbst darf weiter hinaus). Das Auto steht in Kurven
    #   schräg, seine Ecke ragt dann über die 6 px Rand von ``halb_frei`` hinaus.
    # - Querbeschleunigung: der Seitenwechsel darf nur ``QUER_ANTEIL`` der
    #   Seitenbeschleunigung des Autos verbrauchen (quintischer Übergang:
    #   a = 5,77 · Δ / T²), sonst bricht das Auto aus und dreht sich.
    WAND_RESERVE = 12.0
    QUER_ANTEIL = 1.0
    #: Größte Verschiebung des Bremspunkts (px), Summe aus Angriff, Persönlichkeit, Fehler.
    BREMS_SHIFT_MAX = 120.0

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

    def _planen(self, s0, d0, v0, gegner, w, versaetze):
        plan = self.plan
        st = plan.strecke
        hf = plan.halb_frei
        K = self.SCHRITTE
        v_ref = max(float(v0), 120.0)
        horizont = max(v_ref * self.HORIZONT_S, 300.0)
        s_rel = np.linspace(0.0, horizont, K + 1)
        s_abs = s0 + s_rel
        d_id = plan.d_viele(s_abs) + w.versatz
        k_id = np.clip(np.abs(plan.k_viele(s_abs)) * 400.0, 0.0, 1.0)
        # Bremspunkt verschieben: nur die Bremsflanke (Tempoeinbrüche voraus)
        # rückt, nicht das ganze Profil. Später bremsen (δ>0): die Einbrüche
        # beginnen δ weiter vorn; früher bremsen (δ<0): sie beginnen |δ| früher.
        v_prof = plan.v_viele(s_abs)
        delta = float(np.clip(w.spaeter_bremsen_px, -self.BREMS_SHIFT_MAX, self.BREMS_SHIFT_MAX))
        if delta > 0.0:
            # Nie über dem reinen Kurventempo: eine Spitzkehre, schmaler als δ,
            # darf nicht weggefüllt werden.
            v_prof = np.minimum(np.maximum(v_prof, plan.v_viele(s_abs - delta)),
                                plan.v_kurve_viele(s_abs))
        elif delta < 0.0:
            v_prof = np.minimum(v_prof, plan.v_viele(s_abs - delta))
        v_prof = v_prof * w.tempo
        seg = np.diff(s_rel)

        # Kandidaten (C, K+1): Versatz-Hauptschleife, Übergang innen
        vers = np.repeat(np.asarray(versaetze, dtype=float), len(self.UEBERGANG))
        uebg = np.tile(np.asarray(self.UEBERGANG, dtype=float), len(versaetze))
        rand = np.minimum(hf, np.maximum(np.abs(d_id), hf - self.WAND_RESERVE))
        ziel = np.clip(d_id[None, :] + vers[:, None] * hf, -rand[None, :], rand[None, :])
        # Fahrbare Abweichung: Seitenwechsel gegen die Zeit des Übergangs begrenzen
        dauer = np.maximum(uebg * horizont / v_ref, 0.3)
        max_quer = self.QUER_ANTEIL * plan.a_quer * dauer ** 2 / 5.77
        abw0 = d0 - d_id[0]
        ziel = d_id[None, :] + abw0 + np.clip(ziel - d_id[None, :] - abw0,
                                             -max_quer[:, None], max_quer[:, None])
        q = _quintisch(np.clip(s_rel[None, :] / (uebg[:, None] * horizont), 0.0, 1.0))
        d = d0 + (ziel - d0) * q
        if abs(d0) <= hf:
            d = np.clip(d, -hf, hf)
        abw = np.abs(d - d_id) / (2.0 * hf)
        v = np.maximum(v_prof * (1.0 - self.KURVE_KOSTET * abw * k_id), 30.0)
        C = len(vers)

        # Gegner, die nie eine Rolle spielen, fallen weg
        r0l, gvl, gdl, lgl, qul = [], [], [], [], []
        for g in gegner:
            r0 = st.ds(s0, g.s)
            laengs = 0.5 * (self.laenge + g.laenge) + 15.0
            if abs(r0) > horizont + 2.0 * laengs or (r0 < -laengs and g.v <= v0):
                continue
            r0l.append(r0)
            gvl.append(g.v)
            gdl.append(g.d)
            lgl.append(laengs)
            qul.append(0.5 * (self.breite + g.breite) + w.seitenabstand)
        G = len(r0l)

        v_eff = v.copy()
        t = np.zeros((C, K + 1))
        kollision = np.zeros(C)
        if G:
            r0a, gva, gda = np.array(r0l), np.array(gvl), np.array(gdl)
            lga, qua = np.array(lgl), np.array(qul)
            in_spur = np.abs(d[:, :, None] - gda) < qua           # (C, K+1, G)
            basis = r0a[None, :] - s_rel[:, None]                  # (K+1, G)
            for k in range(K + 1):
                if k:
                    tk = t[:, k - 1] + seg[k - 1] / np.maximum(0.5 * (v_eff[:, k - 1] + v[:, k]), 5.0)
                else:
                    tk = t[:, 0]
                rel = basis[k] + gva * tk[:, None]
                hinter = in_spur[:, k, :] & (rel > 0.0)
                cap = np.where(hinter, gva + np.maximum(0.0, rel - lga) * self.FOLGE_GAIN, np.inf).min(axis=1)
                v_eff[:, k] = np.maximum(np.minimum(v[:, k], cap), 0.0)
                if k:
                    t[:, k] = t[:, k - 1] + seg[k - 1] / np.maximum(0.5 * (v_eff[:, k - 1] + v_eff[:, k]), 5.0)
            rel = basis[None] + gva * t[:, :, None]
            treffer = in_spur & (np.abs(rel) < lga)
            erster = np.argmax(treffer, axis=1)                    # (C, G)
            kollision = (self.KOLLISION * (1.0 + K - erster) * treffer.any(axis=1)).sum(axis=1)
        else:
            t[:, 1:] = np.cumsum(seg / np.maximum(0.5 * (v[:, 1:] + v[:, :-1]), 5.0), axis=1)

        zeit = t[:, -1] / (horizont / v_ref)
        kosten = (zeit + kollision
                  + self.W_IDEAL * np.mean(((d - d_id) / hf) ** 2, axis=1)
                  + self.W_WECHSEL * (vers - self._letzter) ** 2
                  + self.W_WAND * np.sum(np.maximum(0.0, np.abs(d) - hf) ** 2, axis=1) / hf ** 2)
        if w.seite is not None:
            kosten = kosten + self.W_SEITE * w.gewicht_seite * ((d[:, -1] - w.seite) / hf) ** 2
        b = int(np.argmin(kosten))
        h = K // 2 + 1
        gefolgt = bool(np.any(v_eff[b, :h] < v[b, :h] - 1e-6))
        v_soll = float(np.min(np.sqrt(v_eff[b] ** 2 + 2.0 * plan.a_brems * s_rel)))
        return float(kosten[b]), Bahn(s_abs, d[b], st.xy_viele(s_abs, d[b]), v_soll, float(vers[b]), gefolgt)
