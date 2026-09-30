"""Strecke in Frenet-Koordinaten: s entlang der Mittellinie, d quer (links positiv)."""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from src.ai.strecke_frenet import StreckeFrenet

R = 1000.0


def _kreis(n=300):
    # gegen den Uhrzeigersinn: links der Fahrtrichtung liegt die Kreismitte
    return [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n)) for i in range(n)]


def test_laenge_und_start():
    st = StreckeFrenet(_kreis(), 300.0)
    assert st.laenge == pytest.approx(2 * math.pi * R, rel=1e-3)
    assert st.s[0] == 0.0
    assert st.halb == 150.0


def test_hin_und_zurueck():
    st = StreckeFrenet(_kreis(), 300.0)
    for s in (0.0, 10.0, 1234.5, st.laenge - 3.0):
        for d in (-120.0, 0.0, 80.0):
            x, y = st.xy(s, d)
            s2, d2, _ = st.sd(x, y)
            assert st.ds(s, s2) == pytest.approx(0.0, abs=2.0)
            assert d2 == pytest.approx(d, abs=2.0)


def test_links_ist_positiv():
    st = StreckeFrenet(_kreis(), 300.0)
    # Kreis gegen den Uhrzeigersinn: innen (Richtung Mitte) ist links
    _, d, _ = st.sd(0.9 * R, 0.0)
    assert d > 0


def test_hinweis_findet_dasselbe():
    st = StreckeFrenet(_kreis(), 300.0)
    x, y = st.xy(500.0, 30.0)
    s1, d1, i1 = st.sd(x, y)
    s2, d2, i2 = st.sd(x, y, hinweis=i1 + 5)
    assert (s1, d1, i1) == pytest.approx((s2, d2, i2))


def test_ds_ueber_die_ziellinie():
    st = StreckeFrenet(_kreis(), 300.0)
    assert st.ds(st.laenge - 10.0, 5.0) == pytest.approx(15.0)
    assert st.ds(5.0, st.laenge - 10.0) == pytest.approx(-15.0)


def test_xy_viele_wie_einzeln():
    st = StreckeFrenet(_kreis(), 300.0)
    s = np.array([0.0, 700.0, 6000.0])
    d = np.array([10.0, -40.0, 90.0])
    viele = st.xy_viele(s, d)
    for k in range(3):
        assert tuple(viele[k]) == pytest.approx(st.xy(s[k], d[k]))
