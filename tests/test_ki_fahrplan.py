"""Fahrplan: Ideallinie und Zieltempo je Stufe, auf jeder Strecke sofort."""
from __future__ import annotations

import numpy as np
import pytest

import ki_hilfe as H
from src.ai.fahrplan import fahrplan_bauen
from src.ai.stufen import STUFEN


@pytest.mark.parametrize("name", ["oval", "gp", "city"])
def test_fahrplan_auf_mitgelieferten_strecken(name):
    track = H.strecke_laden(name)
    plan = fahrplan_bauen(track, H.config("rookie"), STUFEN["hard"])
    n = plan.strecke.n
    assert len(plan.d_ideal) == len(plan.v_ziel) == len(plan.kruemmung) == n
    assert np.all(np.abs(plan.d_ideal) <= plan.halb_frei + 1.0)
    assert np.all(plan.v_ziel > 20.0)
    assert plan.a_brems > 0
    # in Kurven langsamer als auf der schnellsten Geraden
    assert plan.v_ziel.min() < 0.8 * plan.v_ziel.max()


def test_frische_editorstrecke(tmp_path):
    track = H.eigene_strecke(tmp_path)
    plan = fahrplan_bauen(track, H.config("supercar"), STUFEN["expert"])
    assert plan.strecke.laenge > 5000
    assert np.all(np.isfinite(plan.v_ziel))


def test_zwischenwerte_und_zwischenspeicher():
    track = H.strecke_laden("oval")
    a = fahrplan_bauen(track, H.config("rookie"), STUFEN["medium"])
    b = fahrplan_bauen(track, H.config("rookie"), STUFEN["medium"])
    assert a is b
    s = a.strecke.s[5] + 0.5 * a.strecke.seg_len[5]
    assert a.v_bei(s) == pytest.approx(0.5 * (a.v_ziel[5] + a.v_ziel[6]))
    assert a.v_viele(np.array([s]))[0] == pytest.approx(a.v_bei(s))


def test_meister_schneller_als_anfaenger():
    track = H.strecke_laden("gp")
    langsam = fahrplan_bauen(track, H.config("rookie"), STUFEN["easy"])
    schnell = fahrplan_bauen(track, H.config("rookie"), STUFEN["expert"])
    assert langsam.v_ziel.mean() < 0.95 * schnell.v_ziel.mean()
