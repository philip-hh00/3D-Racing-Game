"""Die Vorderräder lenken sichtbar — um die Senkrechte durch die Nabe.

Gemeldet: die Vorderräder drehen sich beim Lenken nicht mit. Die Matrizen
lenkten längst (``Fahrzeugknoten.lenk_matrix``), aber die Physik schlägt bei
Tempo nur 2–7° ein, das sieht nach Geradeaus aus; ein Abbild (Online) hatte gar
keinen Wert. Geprüft wird hier an gerechneten Punkten: wohin wandert ein Punkt
am Radumfang, was macht der Sattel, was machen die Hinterräder.
"""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from src.render3d import vehicle_node
from src.render3d.vehicle_node import Fahrzeugknoten, Radplatz

RADIUS = 0.325
NABE_VL = np.array([1.312, 0.764, RADIUS])
GENAU = 1e-6


def _knoten():
    raeder = [
        Radplatz("rad_vl", NABE_VL.copy(), True),
        Radplatz("rad_vr", NABE_VL * np.array([1, -1, 1]), True),
        Radplatz("rad_hl", np.array([-1.312, 0.764, RADIUS]), False),
        Radplatz("rad_hr", np.array([-1.312, -0.764, RADIUS]), False),
    ]
    return Fahrzeugknoten(raeder, RADIUS * 2)


def _punkt(m, p):
    v = np.array([p[0], p[1], p[2], 1.0], dtype=np.float64)
    return (np.asarray(m, dtype=np.float64) @ v)[:3]


@pytest.fixture
def ohne_ackermann(monkeypatch):
    """Beide Vorderräder genau im Achswinkel — für die reine Drehgeometrie."""
    monkeypatch.setattr(vehicle_node, "ACKERMANN", 0.0)


# -- Drehachse: senkrecht durch die Nabe ---------------------------------------
@pytest.mark.parametrize("winkel", [math.radians(25), -math.radians(25)])
def test_ein_punkt_am_radumfang_dreht_um_die_senkrechte_durch_die_nabe(ohne_ackermann, winkel):
    k = _knoten()
    k.lenken(winkel)
    rad = k.raeder[0]
    # Punkt vorne am Reifen, 0,325 m vor der Nabe auf Nabenhöhe, ohne Rollen.
    p = _punkt(k.matrizen((0.0, 0.0), 0.0)["rad_vl"], (RADIUS, 0.0, 0.0))
    rel = p - rad.nabe
    assert rel[2] == pytest.approx(0.0, abs=GENAU), "Höhe über der Nabe unverändert"
    assert math.hypot(rel[0], rel[1]) == pytest.approx(RADIUS, abs=GENAU)
    assert math.atan2(rel[1], rel[0]) == pytest.approx(winkel, abs=GENAU)


def test_die_lenkachse_steht_senkrecht_und_die_nabe_bleibt_stehen(ohne_ackermann):
    k = _knoten()
    k.lenken(math.radians(30))
    k.weg_zuruecklegen(3.3)
    m = k.matrizen((0.0, 0.0), 0.0)
    # Die Nabe liegt auch auf der Rollachse und bleibt beim Rollen stehen.
    assert _punkt(m["rad_vl"], (0, 0, 0)) == pytest.approx(NABE_VL, abs=GENAU)
    # Die Lenkung allein (Sattel) lässt die ganze Senkrechte durch die Nabe stehen.
    for dz in (-0.3, 0.0, 0.2, 0.5):
        assert _punkt(m["sattel_vl"], (0.0, 0.0, dz)) == pytest.approx(NABE_VL + [0, 0, dz], abs=GENAU)


# -- Reihenfolge: erst Lenken, dann Rollen im gelenkten Rad ---------------------
@pytest.mark.parametrize("rollen", [0.0, 0.7, 2.9, -4.1])
def test_die_radachse_bleibt_waagerecht_und_liegt_im_eingeschlagenen_rad(ohne_ackermann, rollen):
    k = _knoten()
    delta = math.radians(25)
    k.lenken(delta)
    k.weg_zuruecklegen(rollen * RADIUS)
    m = k.matrizen((0.0, 0.0), 0.0)["rad_vl"]
    achse = _punkt(m, (0, 1, 0)) - _punkt(m, (0, 0, 0))
    assert achse == pytest.approx([-math.sin(delta), math.cos(delta), 0.0], abs=GENAU)


def test_rollen_dreht_um_die_eingeschlagene_achse(ohne_ackermann):
    """Ein Punkt oben am Rad läuft nach vorne — in die eingeschlagene Richtung."""
    k = _knoten()
    delta = math.radians(25)
    k.lenken(delta)
    k.weg_zuruecklegen(0.1)
    m = k.matrizen((0.0, 0.0), 0.0)["rad_vl"]
    p = _punkt(m, (0.0, 0.0, RADIUS)) - NABE_VL
    laufrichtung = np.array([math.cos(delta), math.sin(delta)])
    assert float(p[:2] @ laufrichtung) > 0.0, "oben läuft nach vorne"
    quer = np.array([-math.sin(delta), math.cos(delta)])
    assert float(p[:2] @ quer) == pytest.approx(0.0, abs=GENAU), "kein Eiern zur Seite"


# -- Sattel: lenkt mit, rollt nicht -----------------------------------------------
def test_der_sattel_bekommt_die_lenkung_aber_kein_rollen():
    k = _knoten()
    k.lenken(math.radians(20))
    k.weg_zuruecklegen(0.0)
    still = k.matrizen((0.0, 0.0), 0.0)
    k.weg_zuruecklegen(5.0)
    gerollt = k.matrizen((0.0, 0.0), 0.0)
    assert np.allclose(still["sattel_vl"], gerollt["sattel_vl"]), "Rollen ändert den Sattel nicht"
    assert not np.allclose(still["rad_vl"], gerollt["rad_vl"])
    # Ein Punkt vor der Nabe wandert mit der Lenkung nach links.
    assert _punkt(gerollt["sattel_vl"], (0.2, 0.0, 0.0))[1] > NABE_VL[1] + 1e-3


def test_sattel_und_rad_lenken_um_denselben_winkel():
    k = _knoten()
    k.lenken(math.radians(-18))
    k.weg_zuruecklegen(1.7)
    m = k.matrizen((0.0, 0.0), 0.0)
    for rad in ("vl", "vr"):
        sattel = m["sattel_" + rad][:3, :3]
        achse_rad = m["rad_" + rad][:3, :3] @ [0, 1, 0]
        assert sattel @ [0, 1, 0] == pytest.approx(achse_rad, abs=GENAU)


# -- Hinterräder ---------------------------------------------------------------------
def test_die_hinterraeder_lenken_nie():
    k = _knoten()
    k.weg_zuruecklegen(0.0)
    ruhe = k.matrizen((0.0, 0.0), 0.0)
    k.lenken(math.radians(30))
    voll = k.matrizen((0.0, 0.0), 0.0)
    for name in ("rad_hl", "rad_hr", "sattel_hl", "sattel_hr"):
        assert np.array_equal(ruhe[name], voll[name]), name
    for rad in k.raeder[2:]:
        assert k.radwinkel(rad) == 0.0


# -- Ackermann -----------------------------------------------------------------------
def test_das_kurveninnere_rad_schlaegt_weiter_ein_als_das_aeussere():
    k = _knoten()
    delta = math.radians(25)
    k.lenken(delta)
    links, rechts = k.radwinkel(k.raeder[0]), k.radwinkel(k.raeder[1])
    assert links > delta > rechts > 0.0
    # Nach rechts spiegelt sich alles.
    k.lenken(-delta)
    assert k.radwinkel(k.raeder[1]) == pytest.approx(-links, abs=GENAU)
    assert k.radwinkel(k.raeder[0]) == pytest.approx(-rechts, abs=GENAU)


def test_ackermann_bleibt_zwischen_gleichem_winkel_und_reiner_geometrie():
    k = _knoten()
    delta = math.radians(25)
    k.lenken(delta)
    radstand, halbspur = 2.624, 0.764
    t = math.tan(delta)
    innen = math.atan(radstand * t / (radstand - halbspur * t))
    assert delta < k.radwinkel(k.raeder[0]) < innen


def test_ohne_ackermann_paar_lenken_beide_gleich():
    """Nur ein gelenktes Rad (oder kein ungelenktes): ein Winkel für alle."""
    k = Fahrzeugknoten([Radplatz("rad_vl", NABE_VL.copy(), True)], 0.65)
    k.lenken(0.3)
    assert k.radwinkel(k.raeder[0]) == 0.3


def test_stehendes_rad_ohne_einschlag_hat_winkel_null():
    k = _knoten()
    assert all(k.radwinkel(r) == 0.0 for r in k.raeder)


# -- Sichtbarer Einschlag ---------------------------------------------------------------
def test_kleine_physikwinkel_werden_sichtbar_vergroessert():
    w = math.radians(3.0)           # etwa 150 km/h
    assert vehicle_node.sichtbarer_lenkwinkel(w) > 3.0 * w


def test_voller_einschlag_bleibt_unter_der_sichtgrenze():
    voll = vehicle_node.sichtbarer_lenkwinkel(math.radians(35.0))
    assert math.radians(28.0) < voll <= vehicle_node.LENK_SICHT_MAX_RAD


def test_sichtbarer_einschlag_ist_ungerade_stetig_und_waechst():
    assert vehicle_node.sichtbarer_lenkwinkel(0.0) == 0.0
    werte = [vehicle_node.sichtbarer_lenkwinkel(math.radians(g)) for g in range(0, 36)]
    assert all(b > a for a, b in zip(werte, werte[1:]))
    for g in (1.0, 7.0, 20.0):
        assert vehicle_node.sichtbarer_lenkwinkel(-math.radians(g)) == pytest.approx(
            -vehicle_node.sichtbarer_lenkwinkel(math.radians(g)))


def test_lenkwinkel_aus_fahrzeug_nutzt_den_einschlag_der_physik():
    auto = SimpleNamespace(physics=SimpleNamespace(steer_angle=math.radians(4.0)))
    assert vehicle_node.lenkwinkel_aus_fahrzeug(auto) == pytest.approx(
        vehicle_node.sichtbarer_lenkwinkel(math.radians(4.0)))
    assert vehicle_node.lenkwinkel_aus_fahrzeug(SimpleNamespace()) == 0.0


# -- Abbild: Einschlag aus der Fahrt ------------------------------------------------------
def test_linkskurve_vorwaerts_lenkt_nach_links_rueckwaerts_auch():
    # v = 20 m/s, Gierrate 0,5 rad/s gegen den Uhrzeigersinn, Radstand 2,6 m.
    assert vehicle_node.lenkwinkel_aus_bewegung(20.0, 0.5, 2.6) == pytest.approx(
        math.atan(2.6 * 0.5 / 20.0))
    # Rückwärts mit Linkseinschlag dreht sich das Fahrzeug im Uhrzeigersinn.
    assert vehicle_node.lenkwinkel_aus_bewegung(-5.0, -0.4, 2.6) > 0.0
    assert vehicle_node.lenkwinkel_aus_bewegung(20.0, -0.5, 2.6) < 0.0


def test_im_stand_und_beim_schleichen_lenkt_ein_abbild_nicht_voll_ein():
    assert vehicle_node.lenkwinkel_aus_bewegung(0.0, 2.0, 2.6) == 0.0
    assert abs(vehicle_node.lenkwinkel_aus_bewegung(0.3, 2.0, 2.6)) < math.radians(8.0)
    assert abs(vehicle_node.lenkwinkel_aus_bewegung(1.0, 50.0, 2.6)) <= vehicle_node.LENK_PHYSIK_MAX_RAD


def test_abbild_im_rennzustand_wird_geglaettet_und_gezeichnet():
    """Ein ferngesteuertes Fahrzeug hat keine Physik: der Wert kommt aus Tempo und Gierrate."""
    from src.states.race_state import RaceState
    from src.core.settings import M_PER_PX
    zustand = SimpleNamespace(LENK_GLAETTUNG_S=RaceState.LENK_GLAETTUNG_S,
                              _radstand_m=lambda schluessel: 2.6)
    abbild = SimpleNamespace(config_key="rookie", angle=0.0, omega=0.4,
                             velocity=(20.0 / M_PER_PX, 0.0))
    erste = RaceState._lenkwinkel(zustand, 7, abbild, 1 / 60)
    assert 0.0 < erste
    for _ in range(60):
        letzte = RaceState._lenkwinkel(zustand, 7, abbild, 1 / 60)
    assert letzte > erste, "zieht dem Ziel nach, springt nicht"
    ziel = vehicle_node.sichtbarer_lenkwinkel(vehicle_node.lenkwinkel_aus_bewegung(20.0, 0.4, 2.6))
    assert letzte == pytest.approx(ziel, rel=0.02)
    # Ohne Gierrate und ohne Physik: geradeaus.
    assert RaceState._lenkwinkel(zustand, 9, SimpleNamespace(config_key="rookie"), 1 / 60) == 0.0
