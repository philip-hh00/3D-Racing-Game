"""Taktik: aus der Lage auf der Strecke ein Wunsch an den Planer."""
from __future__ import annotations

import math

import numpy as np

import ki_hilfe as H  # noqa: F401
from src.ai.fahrer import persoenlichkeit
from src.ai.fahrplan import Fahrplan
from src.ai.planer import Gegner
from src.ai.stufen import STUFEN
from src.ai.strecke_frenet import StreckeFrenet
from src.ai.taktik import Taktik

R = 5000.0
B, L = 29.0, 62.0


def _plan(kurve_bei=None, links=True):
    n = 1500
    mitte = [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n)) for i in range(n)]
    st = StreckeFrenet(mitte, 300.0)
    v = np.full(n, 600.0)
    k = np.full(n, 1.0 / R)
    if kurve_bei is not None:
        i0 = st.index(kurve_bei)
        v[i0:i0 + 30] = 250.0
        k[i0:i0 + 30] = (1.0 if links else -1.0) / 300.0
    return Fahrplan(st, np.zeros(n), v, k, 129.0, 800.0)


def _taktik(key, plan):
    s = STUFEN[key]
    return Taktik(plan, s, persoenlichkeit(1, s), B, L)


def test_frei():
    w = _taktik("hard", _plan()).entscheiden(100.0, 0.0, 600.0, [])
    assert w.zustand == "frei" and w.seite is None


def test_nebeneinander_haelt_die_spur():
    w = _taktik("hard", _plan()).entscheiden(100.0, 60.0, 600.0,
                                            [Gegner(110.0, -30.0, 600.0, L, B)])
    assert w.zustand == "nebeneinander"
    assert not w.darf_ausscheren
    assert w.seite == 60.0


def test_anfaenger_ueberholt_nur_deutlich_langsamere():
    plan = _plan()
    t = _taktik("easy", plan)
    knapp = t.entscheiden(100.0, 0.0, 600.0, [Gegner(300.0, 0.0, 570.0, L, B)])
    assert not knapp.darf_ausscheren
    lahm = t.entscheiden(100.0, 0.0, 600.0, [Gegner(300.0, 0.0, 300.0, L, B)])
    assert lahm.darf_ausscheren


def test_profi_greift_innen_in_der_bremszone_an():
    plan = _plan(kurve_bei=700.0, links=True)
    w = _taktik("hard", plan).entscheiden(100.0, 0.0, 600.0, [Gegner(250.0, 0.0, 590.0, L, B)])
    assert w.zustand == "angriff"
    assert w.seite is not None and w.seite > 0      # Linkskurve: innen ist links
    assert w.spaeter_bremsen_px > 0


def test_fortgeschritten_greift_nicht_in_der_bremszone_an():
    plan = _plan(kurve_bei=700.0)
    w = _taktik("medium", plan).entscheiden(100.0, 0.0, 600.0, [Gegner(250.0, 0.0, 590.0, L, B)])
    assert w.zustand != "angriff"


def test_verteidigen_ein_spurwechsel():
    plan = _plan(kurve_bei=600.0, links=False)
    t = _taktik("expert", plan)
    hinten = [Gegner(40.0, 0.0, 610.0, L, B)]
    w1 = t.entscheiden(150.0, 0.0, 600.0, hinten)
    assert w1.zustand == "verteidigen"
    assert w1.seite is not None and w1.seite < 0    # Rechtskurve: innen ist rechts
    # Gegner wechselt die Seite — wir bleiben, wo wir sind
    w2 = t.entscheiden(200.0, w1.seite, 600.0, [Gegner(100.0, -w1.seite, 610.0, L, B)])
    assert w2.seite == w1.seite


def test_anfaenger_verteidigt_nicht():
    plan = _plan(kurve_bei=600.0)
    w = _taktik("easy", plan).entscheiden(150.0, 0.0, 600.0, [Gegner(40.0, 0.0, 610.0, L, B)])
    assert w.zustand == "frei"
