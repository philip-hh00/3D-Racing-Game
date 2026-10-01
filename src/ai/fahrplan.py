"""Fahrplan eines KI-Autos: Ideallinie und Zieltempo in Frenet-Koordinaten.

Einmal je (Strecke, Auto, Stufe) gerechnet und zwischengespeichert — ein paar
Dutzend Millisekunden beim Laden, kein Training, keine Streckendaten. Die
Ideallinie kommt aus dem vorhandenen Löser (minimale Krümmung im Korridor), das
Zieltempo aus dem Vorwärts-Rückwärts-Profil mit den Grenzen des Autos, beides
mit den Anteilen der Stufe.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

from src.ai.racing_line_solver import compute_racing_line
from src.ai.speed_profile import compute_speed_profile, limits_from_config
from src.ai.strecke_frenet import StreckeFrenet

#: Zusätzlicher Randabstand des Planerkorridors über die halbe Autobreite hinaus.
RAND_PX = 6.0


@dataclass
class Fahrplan:
    strecke: StreckeFrenet
    d_ideal: np.ndarray
    v_ziel: np.ndarray
    kruemmung: np.ndarray
    halb_frei: float
    a_brems: float
    #: Seitenbeschleunigung (px/s²), die das Auto in Kurven sicher aufbringt.
    a_quer: float = 300.0

    def _viele(self, werte: np.ndarray, s) -> np.ndarray:
        st = self.strecke
        s = np.mod(np.asarray(s, dtype=np.float64), st.laenge)
        i = np.clip(np.searchsorted(st.s, s, side="right") - 1, 0, st.n - 1)
        u = (s - st.s[i]) / st.seg_len[i]
        return werte[i] * (1.0 - u) + werte[(i + 1) % st.n] * u

    def d_viele(self, s) -> np.ndarray:
        return self._viele(self.d_ideal, s)

    def v_viele(self, s) -> np.ndarray:
        return self._viele(self.v_ziel, s)

    def k_viele(self, s) -> np.ndarray:
        return self._viele(self.kruemmung, s)

    def d_bei(self, s: float) -> float:
        return float(self.d_viele(np.array([s]))[0])

    def v_bei(self, s: float) -> float:
        return float(self.v_viele(np.array([s]))[0])

    def k_bei(self, s: float) -> float:
        return float(self.k_viele(np.array([s]))[0])


_CACHE: dict = {}


def mittellinie(track) -> list[tuple[float, float]]:
    mitte = list(getattr(track, "centerline", None) or [])
    if len(mitte) < 3:
        mitte = [(wp.x, wp.y) for wp in track.waypoints]
    return mitte


#: Fahrzeugwerte, die in Löser und Tempoprofil eingehen (siehe ``limits_from_config``).
_CONFIG_FELDER = ("mass", "engine_power", "brake_force", "grip", "max_speed",
                  "turn_speed", "width_px")


def _schluessel(mitte, breite: float, config, stufe) -> tuple:
    """Inhaltsbasierter Zwischenspeicher-Schlüssel.

    Der Editor veröffentlicht dieselbe JSON-Datei oft mit gleicher Punktzahl neu,
    und das Fahrzeuglabor ändert Werte bei gleichem Namen — Pfad und Länge
    reichen deshalb nicht: Mittellinie, Breite und Fahrzeugwerte gehen als Inhalt ein.
    """
    punkte = hashlib.sha1(np.asarray(mitte, dtype=np.float64).tobytes()).hexdigest()
    werte = tuple(float(getattr(config, f, 0.0) or 0.0) for f in _CONFIG_FELDER)
    return (punkte, float(breite), werte, stufe.key)


def fahrplan_bauen(track, config, stufe) -> Fahrplan:
    from src.core.settings import M_PER_PX
    mitte = mittellinie(track)
    breite = float(track.track_width)
    schluessel = _schluessel(mitte, breite, config, stufe)
    if schluessel in _CACHE:
        return _CACHE[schluessel]
    strecke = StreckeFrenet(mitte, breite)
    geo = compute_racing_line(mitte, breite, car_width=float(config.width_px),
                              margin=stufe.wandabstand_px, corner_pull=stufe.kurve_schneiden)
    lim = limits_from_config(config, grip_usage=stufe.haftung,
                             brake_confidence=stufe.bremsen, steer_confidence=0.9)
    v = np.asarray(compute_speed_profile(geo, lim), dtype=np.float64)
    # Bremspunkt-Vorhalt: das Tempo einer Stelle darf nicht über dem der
    # nächsten ``bremspunkt_m`` Meter liegen — wer vorsichtig ist, bremst früher.
    vorhalt = stufe.bremspunkt_m / M_PER_PX
    if vorhalt > 0.0:
        k = max(1, int(math.ceil(vorhalt / float(np.mean(strecke.seg_len)))))
        v = np.minimum.reduce([np.roll(v, -j) for j in range(k + 1)])
    d_ideal = np.array([strecke.sd(x, y, hinweis=i)[1] for i, (x, y) in enumerate(geo.points)])
    halb_frei = max(10.0, strecke.halb - float(config.width_px) / 2.0 - RAND_PX)
    plan = Fahrplan(strecke, np.clip(d_ideal, -halb_frei, halb_frei), v,
                    np.asarray(geo.signed_curvature, dtype=np.float64), halb_frei, float(lim.a_brake),
                    float(lim.a_lat))
    _CACHE[schluessel] = plan
    return plan
