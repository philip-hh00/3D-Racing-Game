"""Physikalisch stimmige Grenzen der KI: Beschleunigung, Lenkanschlag, Ideallinie.

Anlass (1.10.2026): Meister brauchte auf city mit dem Kompaktwagen 28,3 s, die
beste Menschenrunde war 22,09 s. Ursachen: Ideallinie mit Vorhalten, die den
Korridor in jeder Kurve verengten; Tempoprofil mit 4-fach zu hoher
Beschleunigung und einer Lenkgrenze, die die Physik nicht mehr kennt.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

import ki_hilfe as H
from src.ai.fahrplan import mittellinie
from src.ai.racing_line_solver import compute_racing_line
from src.ai.speed_profile import (VehicleLimits, _corner_speed, compute_speed_profile,
                                  limits_from_config)


def test_beschleunigung_entspricht_der_gemessenen_physik():
    """rookie (Frontantrieb): Vollgas 0…300 px/s gemessen ~53 px/s² (traktionsbegrenzt),
    nicht ``engine_power / mass`` = 220."""
    lim = limits_from_config(H.config("rookie"))
    for v in (50.0, 150.0, 250.0):
        assert 45.0 <= lim.beschleunigung(v) <= 62.0, v
    assert lim.beschleunigung(600.0) < lim.beschleunigung(150.0)     # Luftwiderstand


def test_lenkgrenze_folgt_dem_anschlag():
    """Engster Radius: tan(Anschlag) = Radstand · Krümmung, Anschlag 35° / (1+(v/500)^1,2)."""
    lim = VehicleLimits(a_lat=1e9, a_accel=50.0, a_brake=130.0, v_max=900.0,
                        turn_speed=2.2, turn_safety=0.9, radstand=32.8)
    k = 1.0 / 60.0

    def reicht(v):
        lock = math.radians(35.0) / (1.0 + (v / 500.0) ** 1.2)
        return k * 32.8 <= math.tan(lock * 0.9)

    v = _corner_speed(k, lim)
    assert reicht(v * 0.999)
    assert not reicht(v * 1.02)
    assert _corner_speed(1.0 / 20.0, lim) == 0.0          # enger als der Anschlag je erlaubt


@pytest.mark.parametrize("name", ["city", "gp"])
def test_profil_ohne_antrieb_ist_nur_kurven_und_bremsen(name):
    track = H.strecke_laden(name)
    cfg = H.config("rookie")
    geo = compute_racing_line(mittellinie(track), float(track.track_width),
                              car_width=float(cfg.width_px), margin=22.0, corner_pull=0.3)
    lim = limits_from_config(cfg, grip_usage=0.88, brake_confidence=0.95, steer_confidence=0.9)
    frei = np.array(compute_speed_profile(geo, lim, antrieb_begrenzt=False))
    real = np.array(compute_speed_profile(geo, lim))
    assert np.all(frei >= real - 1e-6)
    assert (frei > real + 20.0).any()


def test_ideallinie_city_nutzt_die_ganze_strecke():
    """Gleichgewichtszeit des Profils auf der Ideallinie: vorher 28,6 s (Vorhalte
    sperrten die Innenseite vor Kurven und in S-Kurven), jetzt ~20,1 s."""
    track = H.strecke_laden("city")
    cfg = H.config("rookie")
    geo = compute_racing_line(mittellinie(track), float(track.track_width),
                              car_width=float(cfg.width_px), margin=22.0, corner_pull=0.3)
    lim = limits_from_config(cfg, grip_usage=0.88, brake_confidence=0.95, steer_confidence=0.9)
    v = np.array(compute_speed_profile(geo, lim, antrieb_begrenzt=False))
    seg = np.array(geo.seg_len)
    zeit = float(np.sum(seg / np.maximum(0.5 * (v + np.roll(v, -1)), 1.0)))
    assert zeit < 22.0, zeit
    assert seg.sum() < 7300.0        # kürzer als die Mittellinie, auch ohne Sperren
