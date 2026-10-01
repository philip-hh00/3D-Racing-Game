"""Aufprallklaenge nehmen mit der Entfernung ab (Fund 01.10.2026).

Gemeldet: Crashgeraeusche sind immer etwa gleich laut, egal wie weit der
Zusammenstoss entfernt ist. Ursache: ``RaceState`` suchte das Fahrzeug mit
``data.get("vehicle_id")``, die Ereignisse tragen aber ``vehicle_body_id``
(Wand) bzw. ``body_a_id``/``body_b_id`` (Fahrzeug gegen Fahrzeug). Das Fahrzeug
blieb ``None``, und ``Rennklang.aufprall`` spielte ohne Daempfung.

Der Test arbeitet mit einem echten Rennen und den Nutzdaten, wie der
``CollisionHandler`` sie wirklich schickt (die Schluessel stehen dort).
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.core import sfx_rennen as sr  # noqa: E402


@pytest.fixture
def rennen(monkeypatch):
    import spielhilfe
    spielhilfe.bus_isolieren(monkeypatch)
    r, _sm = spielhilfe.rennen_bauen("oval", feld=3)
    if r._klang is None:
        r._klang = sr.Rennklang()
    gespielt = []
    monkeypatch.setattr("src.core.sfx.spielen",
                        lambda n, l=1.0, p=0.0: gespielt.append((n, l, p)))
    r._gespielt = gespielt
    yield r
    spielhilfe.alles_schliessen()


def _setzen(fahrzeug, x, y):
    fahrzeug.body.position = (x, y)


def _wand(rennen, fahrzeug, impuls=6000.0):
    rennen._gespielt.clear()
    rennen._on_wall_collision({"vehicle_body_id": id(fahrzeug.body),
                               "impulse": impuls})
    return list(rennen._gespielt)


def test_die_nutzdaten_tragen_die_koerperkennung():
    """Die Schluessel, auf die RaceState sich verlaesst, stehen im Handler."""
    import inspect
    from src.physics import collision_handler
    quelle = inspect.getsource(collision_handler)
    for schluessel in ("vehicle_body_id", "body_a_id", "body_b_id"):
        assert schluessel in quelle


def test_ein_wandtreffer_in_der_ferne_ist_leiser(rennen):
    mensch = rennen._humans[0]
    gegner = rennen.ai_vehicles[0]
    mx, my = sr._position(mensch)
    _setzen(gegner, mx + 5.0, my)
    nah = _wand(rennen, gegner)
    _setzen(gegner, mx + 1500.0, my)
    fern = _wand(rennen, gegner)
    assert nah, "ein Treffer neben dem Hoerer muss klingen"
    assert not fern or fern[0][1] < 0.2 * nah[0][1], (nah, fern)


def test_ein_wandtreffer_mittendrin_ist_leiser_als_nah(rennen):
    mensch = rennen._humans[0]
    gegner = rennen.ai_vehicles[0]
    mx, my = sr._position(mensch)
    _setzen(gegner, mx + 5.0, my)
    nah = _wand(rennen, gegner)
    _setzen(gegner, mx + 500.0, my)
    mitte = _wand(rennen, gegner)
    assert mitte and mitte[0][1] < nah[0][1]
    assert mitte[0][2] > 0.5, "rechts vom Hoerer muss nach rechts gelegt werden"


def test_jenseits_der_hoerweite_ist_ein_treffer_stumm(rennen):
    mensch = rennen._humans[0]
    gegner = rennen.ai_vehicles[0]
    mx, my = sr._position(mensch)
    _setzen(gegner, mx + sr.HOERWEITE + 50.0, my)
    fern = _wand(rennen, gegner)
    assert all(l <= 1e-6 for _n, l, _p in fern), fern


def _beruehrung(rennen, a, b, impuls=6000.0):
    rennen._gespielt.clear()
    rennen._on_vehicle_contact({"body_a_id": id(a.body), "body_b_id": id(b.body),
                                "vehicle_a": getattr(a.body, "data", None),
                                "vehicle_b": getattr(b.body, "data", None),
                                "impulse": impuls})
    return list(rennen._gespielt)


def test_fahrzeug_gegen_fahrzeug_in_der_ferne_ist_leiser(rennen):
    mensch = rennen._humans[0]
    a, b = rennen.ai_vehicles[0], rennen.ai_vehicles[1]
    mx, my = sr._position(mensch)
    _setzen(a, mx + 30.0, my)
    _setzen(b, mx + 60.0, my)
    nah = _beruehrung(rennen, a, b)
    _setzen(a, mx + 1500.0, my)
    _setzen(b, mx + 1530.0, my)
    fern = _beruehrung(rennen, a, b)
    assert nah
    assert not fern or fern[0][1] < 0.2 * nah[0][1], (nah, fern)


def test_ohne_vehicle_a_b_objekte_hilft_die_koerperkennung(rennen):
    """Nur ``body_a_id``/``body_b_id`` — wie bei einem entfernten Mitspieler."""
    mensch = rennen._humans[0]
    a, b = rennen.ai_vehicles[0], rennen.ai_vehicles[1]
    mx, my = sr._position(mensch)
    _setzen(a, mx + 1500.0, my)
    _setzen(b, mx + 1530.0, my)
    rennen._gespielt.clear()
    rennen._on_vehicle_contact({"body_a_id": id(a.body), "body_b_id": id(b.body),
                                "impulse": 6000.0})
    assert all(l <= 1e-6 for _n, l, _p in rennen._gespielt)


def test_das_naehere_fahrzeug_zaehlt(rennen):
    mensch = rennen._humans[0]
    a, b = rennen.ai_vehicles[0], rennen.ai_vehicles[1]
    mx, my = sr._position(mensch)
    _setzen(a, mx + 1400.0, my)
    _setzen(b, mx + 5.0, my)
    assert rennen._aufprall_fahrzeug({"body_a_id": id(a.body),
                                      "body_b_id": id(b.body)}) is b
