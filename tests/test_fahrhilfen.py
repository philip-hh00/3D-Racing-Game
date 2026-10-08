"""Fahrhilfen: ABS und Traktionskontrolle (Plan 1.1.0, Punkt 3).

Geprüft wird, was zugesagt ist:

* **Aus = wie vorher.** Das Fahrskript ``_skript`` ist gegen den Stand *vor*
  den Fahrhilfen gefahren worden (Hauptordner, alter Quelltext); die
  Endzustände unten sind dessen Zahlen. Ein Auto ohne Fahrhilfen -- und eines
  mit abgeschalteten -- muss sie auf sechs Stellen treffen.
* **ABS** nimmt Bremsdruck weg, wenn eine Achse rutscht oder die Seitenhaftung
  ausgereizt ist; geradeaus bremst das Auto wie ohne. Die Handbremse bleibt
  unberührt.
* **Traktionskontrolle** nimmt Gas weg, bis die angetriebene Achse die Kraft
  überträgt: weniger Durchdrehen, praktisch gleiche Beschleunigung.
* Die KI hat nie welche.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk  # noqa: E402

from src.core.settings import KMH_PER_PXS, M_PER_PX  # noqa: E402
from src.entities.components.fahrhilfen import Fahrhilfen, MIN_TEMPO  # noqa: E402
from src.entities.vehicle_factory import VehicleFactory  # noqa: E402
from src.physics.physics_world import PhysicsWorld  # noqa: E402

DT = 1.0 / 60.0


def _auto(key: str, kmh: float = 0.0, abs_an: bool = False, tc_an: bool = False,
          objekt: bool = False):
    if not VehicleFactory.get_config(key):
        VehicleFactory.load_all_configs()
    welt = PhysicsWorld()
    a = VehicleFactory.create_player_vehicle(key, 1, (0.0, 0.0), 0.0, welt.space, lack="werk")
    a.physics.body.velocity = (kmh / KMH_PER_PXS, 0.0)
    a.prev_velocity = pymunk.Vec2d(*a.physics.body.velocity)
    a.is_analog = False
    if abs_an or tc_an or objekt:
        a.fahrhilfen = Fahrhilfen(abs_an=abs_an, tc_an=tc_an)
    return welt, a


def _schritt(welt, a, gas=0.0, bremse=0.0, lenken=0.0, handbremse=False):
    a.throttle, a.brake_input, a.steer_input, a.handbrake = gas, bremse, lenken, handbremse
    a.update(DT)
    welt.step(DT)


# ---------------------------------------------------------------------------
# Aus = wie vorher
# ---------------------------------------------------------------------------

def _skript(t: float):
    if t < 3.0:
        return 1.0, 0.0, 0.0, False
    if t < 4.5:
        return 1.0, 0.0, 0.6 if t < 3.8 else -0.6, False
    if t < 6.0:
        return 0.0, 1.0, 0.3, False
    if t < 6.6:
        return 0.0, 0.0, 1.0, True
    if t < 8.0:
        return 0.7, 0.0, -0.4, False
    return 0.0, 0.5, 0.0, False


def _proben(key: str, objekt: bool):
    welt, a = _auto(key, objekt=objekt)
    raus = []
    for i in range(480):
        _schritt(welt, a, *_skript(i * DT))
        if i + 1 in (120, 240, 330, 400, 480):
            b = a.physics.body
            raus.append((b.position.x, b.position.y, b.velocity.x, b.velocity.y, b.angle,
                         b.angular_velocity, a.engine.current_rpm, a.engine.current_gear))
    return raus


#: Endzustände des Skripts aus dem Quelltext vor den Fahrhilfen (x, y, vx, vy,
#: Winkel, Gierrate, Drehzahl, Gang) bei Bild 120, 240, 330, 400, 480.
_VORHER = {
    "rookie": [(107.473185, 0.0, 107.582059, 0.0, 0.0, 0.0, 4156.203, 1),
               (369.235367, 91.650453, 122.834783, 133.762373, 0.90007961, -0.72119818, 4389.902, 2),
               (562.930211, 206.516869, 39.554608, 48.450647, 0.78273592, 0.33256383, 2869.036, 1),
               (571.550807, 218.14465, 1.408924, 2.843037, 0.86202366, 0.03733116, 800.188, 1),
               (609.269952, 243.260557, 59.729263, 28.880184, 0.5753793, -0.41228449, 2513.774, 1)],
    "supercar": [(109.26431, 0.0, 143.05638, 0.0, 0.0, 0.0, 4539.012, 1),
                 (561.87465, 115.234512, 273.809671, 184.902079, 0.61509269, -0.64403072, 7511.821, 2),
                 (972.445194, 289.641351, 152.177384, 130.792946, 0.66915381, 0.64179504, 6811.829, 1),
                 (1027.537503, 422.026334, -32.68432, 98.182642, 1.77637166, 0.83347994, 2605.03, 1),
                 (1094.291261, 628.496648, 152.140653, 172.928878, 0.88612088, -0.68346682, 7527.818, 1)],
    "drifter": [(78.578714, 0.0, 91.3937, 0.0, 0.0, 0.0, 2875.429, 1),
                (343.397519, 83.292861, 146.230761, 130.113925, 0.76923819, -0.64277625, 6340.662, 1),
                (565.787292, 200.542555, 58.175747, 59.508203, 0.73240627, 0.36588205, 3033.551, 1),
                (585.973374, 228.164505, 6.291141, 12.692424, 0.98496887, 0.10677968, 900.996, 1),
                (613.402948, 256.197074, 37.323934, 30.684144, 0.7721638, -0.26212394, 1498.937, 1)],
}


@pytest.mark.parametrize("objekt", [False, True], ids=["ohne_objekt", "objekt_alles_aus"])
@pytest.mark.parametrize("key", sorted(_VORHER))
def test_aus_faehrt_wie_vor_den_fahrhilfen(key, objekt):
    for ist, soll in zip(_proben(key, objekt), _VORHER[key]):
        assert ist[7] == soll[7]                              # Gang
        for a, b in zip(ist[:7], soll[:7]):
            assert a == pytest.approx(b, abs=1e-3, rel=1e-7), (key, ist, soll)


def test_ki_und_neue_fahrzeuge_haben_keine_fahrhilfen():
    _welt, a = _auto("rookie")
    assert a.fahrhilfen is None
    from src.entities.ai_vehicle import AIVehicle
    assert AIVehicle.fahrhilfen is None


# ---------------------------------------------------------------------------
# ABS
# ---------------------------------------------------------------------------

def _bremsen(key: str, abs_an: bool, lenken: float = 0.0, kmh: float = 150.0):
    welt, a = _auto(key, kmh, abs_an=abs_an)
    t, max_schlupf = 0.0, 0.0
    p0 = a.physics.body.position
    while a.speed * KMH_PER_PXS > 3.0 and t < 20.0:
        _schritt(welt, a, bremse=1.0, lenken=lenken)
        t += DT
        if a.speed * KMH_PER_PXS > 30.0:
            max_schlupf = max(max_schlupf, a.physics.reifen_schlupf_deg)
    return (a.physics.body.position - p0).length * M_PER_PX, t, max_schlupf


@pytest.mark.parametrize("key", ["rookie", "supercar", "limousine", "drifter"])
def test_abs_geradeaus_bremst_wie_ohne(key):
    ohne, _t0, _ = _bremsen(key, False)
    mit, _t1, _ = _bremsen(key, True)
    assert mit == pytest.approx(ohne, rel=0.005)
    assert 50.0 < mit < 110.0            # 150 km/h in Wagen von 1,1 bis 1,3 g: 70 bis 85 m


@pytest.mark.parametrize("key", ["rookie", "supercar", "limousine", "drifter"])
def test_abs_im_einschlag_haelt_den_schlupf_klein_und_bremst_weiter(key):
    ohne, _t0, schlupf_ohne = _bremsen(key, False, lenken=0.5)
    mit, _t1, schlupf_mit = _bremsen(key, True, lenken=0.5)
    assert schlupf_mit < schlupf_ohne * 0.8          # Reifen schieben weniger
    assert mit < ohne * 1.10                         # Preis: wenige Prozent Bremsweg
    assert mit > ohne * 0.99


def test_abs_bremst_nie_ganz_ab():
    welt, a = _auto("rookie", 150.0, abs_an=True)
    a.physics.vorn_schlupf_deg = a.physics.hinten_schlupf_deg = 60.0
    a.physics.quer_auslastung = (9.0, 9.0)
    for _ in range(30):
        a.brake_input = 1.0
        gas, bremse = a.fahrhilfen.anwenden(a, 0.0, 1.0, DT)
        a.physics.vorn_schlupf_deg = a.physics.hinten_schlupf_deg = 60.0
        a.physics.quer_auslastung = (9.0, 9.0)
    assert 0.25 <= bremse < 0.5                      # stark gedrosselt, aber nie null


def test_abs_laesst_die_handbremse_in_ruhe():
    welt, a = _auto("rookie", 120.0, abs_an=True, tc_an=True)
    a.handbrake = True
    a.physics.vorn_schlupf_deg = a.physics.hinten_schlupf_deg = 40.0
    gas, bremse = a.fahrhilfen.anwenden(a, 0.5, 1.0, DT)
    assert (gas, bremse) == (0.5, 1.0)


def test_abs_greift_unter_schritttempo_nicht():
    welt, a = _auto("rookie", MIN_TEMPO * KMH_PER_PXS * 0.5, abs_an=True)
    a.physics.vorn_schlupf_deg = 40.0
    a.physics.quer_auslastung = (9.0, 9.0)
    assert a.fahrhilfen.anwenden(a, 0.0, 1.0, DT)[1] == 1.0


def test_abs_ohne_schlupf_laesst_die_bremse_unberuehrt():
    welt, a = _auto("rookie", 150.0, abs_an=True)
    assert a.fahrhilfen.anwenden(a, 0.0, 0.7, DT)[1] == pytest.approx(0.7)


def test_abs_verfaelscht_die_eingabe_des_fahrers_nicht():
    welt, a = _auto("rookie", 150.0, abs_an=True)
    for _ in range(60):
        _schritt(welt, a, bremse=1.0, lenken=0.5)
    assert a.brake_input == 1.0                      # Eingabe bleibt
    assert a.bremse_wirksam <= 1.0                   # Wirkung kann kleiner sein


# ---------------------------------------------------------------------------
# Traktionskontrolle
# ---------------------------------------------------------------------------

def _anfahren(key: str, tc_an: bool):
    welt, a = _auto(key, 0.0, tc_an=tc_an)
    t, t100, ueberschuss = 0.0, None, 0.0
    while t < 10.0:
        _schritt(welt, a, gas=1.0)
        t += DT
        if t <= 3.0:
            ueberschuss += a.physics.antriebs_ueberschuss * DT
        if t100 is None and a.speed * KMH_PER_PXS >= 100.0:
            t100 = t
    return ueberschuss / 3.0, t100


@pytest.mark.parametrize("key", ["rookie", "limousine", "drifter"])
def test_tc_nimmt_das_durchdrehen_beim_anfahren(key):
    ohne, t_ohne = _anfahren(key, False)
    mit, t_mit = _anfahren(key, True)
    assert ohne > 0.25                               # ohne Hilfe verpufft ein Drittel und mehr
    assert mit < 0.10                                # mit Hilfe kaum noch
    assert t_mit < t_ohne * 1.03                     # und schneller als +3 % wird es nicht


def test_tc_allrad_verbessert_und_verliert_nichts():
    ohne, t_ohne = _anfahren("supercar", False)
    mit, t_mit = _anfahren("supercar", True)
    assert mit < ohne
    assert t_mit == pytest.approx(t_ohne, rel=0.01)  # die starke Achse behaelt ihr Gas


def test_tc_ohne_durchdrehen_laesst_das_gas_wie_es_ist():
    welt, a = _auto("rookie", 100.0, tc_an=True)
    a.physics.antriebs_ueberschuss_min = 0.0
    a.physics.hinten_schlupf_deg = a.physics.vorn_schlupf_deg = 1.0
    assert a.fahrhilfen.anwenden(a, 0.8, 0.0, DT)[0] == pytest.approx(0.8)


def test_tc_nimmt_gas_bei_schraeglauf_der_antriebsachse():
    welt, a = _auto("limousine", 100.0, tc_an=True)      # Heckantrieb
    a.physics.hinten_schlupf_deg = 30.0
    gas = a.fahrhilfen.anwenden(a, 1.0, 0.0, DT)[0]
    assert gas < 0.5
    # Schraeglauf der Vorderachse ist bei Heckantrieb kein Grund
    welt, b = _auto("limousine", 100.0, tc_an=True)
    b.physics.vorn_schlupf_deg = 30.0
    assert b.fahrhilfen.anwenden(b, 1.0, 0.0, DT)[0] == pytest.approx(1.0)


def test_tc_gas_kommt_nach_dem_durchdrehen_zurueck():
    welt, a = _auto("rookie", 0.0, tc_an=True)
    a.fahrhilfen.gas_faktor = 0.2
    a.physics.antriebs_ueberschuss_min = 0.0
    gas = 0.0
    for _ in range(120):
        gas = a.fahrhilfen.anwenden(a, 1.0, 0.0, DT)[0]
    assert gas == pytest.approx(1.0)


def test_fahrhilfen_schalter_einzeln():
    welt, a = _auto("rookie", 150.0, abs_an=False, tc_an=True)
    a.physics.vorn_schlupf_deg = 40.0
    a.physics.quer_auslastung = (9.0, 9.0)
    assert a.fahrhilfen.anwenden(a, 0.0, 1.0, DT)[1] == 1.0      # ABS aus
    welt, b = _auto("rookie", 150.0, abs_an=True, tc_an=False)
    b.physics.antriebs_ueberschuss_min = 0.6
    assert b.fahrhilfen.anwenden(b, 1.0, 0.0, DT)[0] == 1.0      # TC aus
