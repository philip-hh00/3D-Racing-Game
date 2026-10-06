"""Auto gegen Auto und Rutschen (06.10.2026).

Gemeldet: „Kollisionen zwischen Autos sind stark übertrieben, die prallen zu
weit ab — wie Gummibälle." und „Verlieren die Reifen die Haftung, gleitet das
Auto wie auf Eis, statt Tempo abzubauen und sich wieder zu fangen."

**Stoß.** Offline teilen sich zwei Autos den Stoß mit einer Stoßzahl von
0,06 — das bleibt so und ist hier festgehalten. Online war es anders: der
Mitspieler ist ein kinematischer Geist (für unser Auto unendlich schwer, mit
Elastizität 0,3), der Verursacher prallte rückwärts ab; dazu ging der volle
Stoß gegen eine unendliche Masse per Netz an den Getroffenen, in jedem zweiten
Fall mit falschem Vorzeichen und dort im Fahrzeugsystem statt in Welt-
koordinaten angelegt.

**Rutschen.** Die Haftung hing am Winkel am Schwerpunkt und galt für beide
Achsen: brach das Heck aus, verlor die Vorderachse mit und konnte das Auto
nicht mehr einfangen. Jetzt hat jede Achse ihre Reifenkennlinie (Spitze bei
8 Grad, rutschend 80 %). Die Gierdämpfung wirkte je Bild statt je Sekunde —
bei 144 Bildern drehte das Auto mit Handbremse halb so weit wie bei 60.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk
import pytest

from src.core.settings import KMH_PER_PXS
from src.entities.components.physics_body import PhysicsBody
from src.physics.physics_world import PhysicsWorld

DT = 1.0 / 60.0


def _fabrik():
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_config("rookie"):
        VehicleFactory.load_all_configs()
    return VehicleFactory


def _auto(welt, key, pos=(0.0, 0.0), winkel_deg=0.0, geschw=(0.0, 0.0), nummer=1):
    auto = _fabrik().create_player_vehicle(key, nummer, pos, math.radians(winkel_deg),
                                           welt.space, lack="werk")
    auto.physics.body.velocity = geschw
    auto.prev_velocity = pymunk.Vec2d(*geschw)
    return auto


def _schritt(welt, autos, dt, gas=0.0, bremse=0.0, lenkung=0.0, handbremse=False):
    from src.entities.vehicle import Vehicle
    for auto in autos:
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = \
            gas, bremse, lenkung, handbremse
        Vehicle.update(auto, dt)
    welt.step(dt)


def _px(kmh: float) -> float:
    return kmh / KMH_PER_PXS


# ---------------------------------------------------------------- Stoß ----

@pytest.mark.parametrize("fps", [30, 60, 144])
@pytest.mark.parametrize("hinten, vorn", [("rookie", "rookie"), ("supercar", "limousine"),
                                          ("drifter", "electric")])
def test_auffahren_prallt_kaum_ab(hinten, vorn, fps):
    """Auffahren mit 100 km/h: Trenngeschwindigkeit höchstens 25 % der Annäherung."""
    welt = PhysicsWorld()
    a = _auto(welt, hinten, (0.0, 0.0), 0.0, (_px(100.0), 0.0), 1)
    b = _auto(welt, vorn, (120.0, 0.0), 0.0, (0.0, 0.0), 2)
    dt = 1.0 / fps
    trenn = 0.0
    for _ in range(int(1.5 / dt)):
        _schritt(welt, (a, b), dt)
        trenn = max(trenn, b.physics.body.velocity.x - a.physics.body.velocity.x)
    assert trenn <= 0.25 * _px(100.0)
    # Der Stoß wird geteilt: keiner steht, keiner fliegt davon.
    for auto in (a, b):
        assert 30.0 < auto.physics.body.velocity.x * KMH_PER_PXS < 75.0


def test_frontal_prallt_kaum_ab():
    welt = PhysicsWorld()
    a = _auto(welt, "rookie", (0.0, 0.0), 0.0, (_px(60.0), 0.0), 1)
    b = _auto(welt, "rookie", (150.0, 0.0), 180.0, (-_px(60.0), 0.0), 2)
    trenn = 0.0
    for _ in range(int(1.5 / DT)):
        _schritt(welt, (a, b), DT)
        trenn = max(trenn, b.physics.body.velocity.x - a.physics.body.velocity.x)
    assert trenn <= 0.25 * _px(120.0)


def _geist(welt, pos):
    from src.entities.remote_vehicle import RemoteVehicle
    _fabrik()
    geist = RemoteVehicle(200, 2, welt.space, "rookie")
    geist._body.position = pos
    geist._body.velocity = (0.0, 0.0)
    return geist


def test_auffahren_auf_einen_geist_prallt_nicht_rueckwaerts():
    """Online: der Mitspieler ist kinematisch — früher -8 km/h aus 100."""
    welt = PhysicsWorld()
    a = _auto(welt, "rookie", (0.0, 0.0), 0.0, (_px(100.0), 0.0))
    _geist(welt, (120.0, 0.0))
    rueck = 0.0
    for _ in range(40):
        _schritt(welt, (a,), DT)
        rueck = max(rueck, -a.physics.body.velocity.x)
    assert rueck * KMH_PER_PXS < 1.0


def test_der_stoss_ans_netz_zeigt_vom_verursacher_weg_und_ist_geteilt():
    from src.core.event_bus import EventBus
    from src.physics.collision_handler import (CollisionHandler, STOSSZAHL_FAHRZEUGE,
                                               stoss_fuer_getroffenen)
    welt = PhysicsWorld()
    bus = EventBus.create_isolated()
    CollisionHandler(welt.space, bus)
    treffer = []
    bus.subscribe("impact_vehicle_vehicle", treffer.append)
    a = _auto(welt, "rookie", (0.0, 0.0), 0.0, (_px(100.0), 0.0))
    geist = _geist(welt, (120.0, 0.0))
    v_vor = a.physics.body.velocity.x
    for _ in range(40):
        _schritt(welt, (a,), DT)
        if treffer:
            break
    assert treffer
    d = treffer[0]
    m = a.physics.body.mass
    jx, jy = stoss_fuer_getroffenen(d["total_impulse"], d["vehicle_a"] is geist, m, m)
    # Weg vom Verursacher (+x), etwa der eigene Anteil eines gleich schweren Autos.
    assert jx > 0.0 and abs(jy) < 0.2 * jx
    soll = (1.0 + STOSSZAHL_FAHRZEUGE) * 0.5 * m * v_vor
    assert jx == pytest.approx(soll, rel=0.15)


class _Zustand:
    pass


def _rennzustand_mit_spieler(winkel_deg):
    from src.states.race_state import RaceState
    rs = RaceState(_Zustand())
    spieler = _Zustand()
    spieler.body = pymunk.Body(1000.0, 1000.0)
    spieler.body.angle = math.radians(winkel_deg)
    rs.player = spieler
    return rs, spieler.body


def test_ein_empfangener_stoss_gilt_in_weltkoordinaten():
    # Das Auto zeigt nach Norden, der Stoß nach Osten: früher als Stoß nach
    # vorn angelegt (im Fahrzeugsystem), jetzt nach Osten.
    rs, body = _rennzustand_mit_spieler(90.0)
    rs._bump_empfangen({"impulse": (10_000.0, 0.0), "sender_slot": 3})
    assert body.velocity.x == pytest.approx(10.0)
    assert abs(body.velocity.y) < 1e-6


def test_ein_schon_gespuerter_stoss_zaehlt_nicht_doppelt():
    import time
    rs, body = _rennzustand_mit_spieler(0.0)
    rs._geist_beruehrt[3] = time.monotonic()
    rs._bump_empfangen({"impulse": (10_000.0, 0.0), "sender_slot": 3})
    assert body.velocity.length == 0.0
    rs._bump_empfangen({"impulse": (10_000.0, 0.0), "sender_slot": 4})
    assert body.velocity.x == pytest.approx(10.0)


# ------------------------------------------------------------ Rutschen ----

def test_reifenkennlinie_ohne_gedaechtnis():
    griff = PhysicsBody.reifen_griff
    assert griff(0.0) == griff(PhysicsBody.SCHLUPF_SPITZE_DEG) == 1.0
    werte = [griff(s * 0.5) for s in range(0, 181)]
    assert all(x >= y for x, y in zip(werte, werte[1:]))      # fällt nur
    assert griff(90.0) == pytest.approx(PhysicsBody.GLEIT_ANTEIL)
    # Gleitreibung echter Reifen: 70-90 % der Haftung.
    assert 0.7 <= PhysicsBody.GLEIT_ANTEIL <= 0.9
    # Kein Gedächtnis: derselbe Winkel gibt denselben Wert, hin wie zurück.
    assert [griff(s * 0.5) for s in range(180, -1, -1)] == werte[::-1]


@pytest.mark.parametrize("key", ["rookie", "supercar", "drifter"])
def test_voll_quer_radiert_mit_gleitreibung(key):
    """Quer rutschend verzögert ein Auto mit etwa Gleitreibung mal Haftgrenze."""
    welt = PhysicsWorld()
    auto = _auto(welt, key, (0.0, 0.0), 90.0, (_px(100.0), 0.0))
    v0 = auto.speed
    n = int(0.25 / DT)
    for _ in range(n):
        _schritt(welt, (auto,), DT)
    verzoegerung = (v0 - auto.speed) / (n * DT)
    haftgrenze = auto.config.grip * 380.0          # px/s², siehe speed_profile
    assert 0.7 * haftgrenze <= verzoegerung <= 0.9 * haftgrenze


@pytest.mark.parametrize("key", ["rookie", "electric", "drifter"])
def test_faengt_sich_nach_dem_rutschen(key):
    """45 Grad quer: der Schräglauf baut sich ab, die Haftung ist wieder voll da."""
    welt = PhysicsWorld()
    auto = _auto(welt, key, (0.0, 0.0), 45.0, (_px(100.0), 0.0))
    _schritt(welt, (auto,), DT)
    assert auto.physics.achs_griff[1] < 0.9                 # rutscht wirklich
    for _ in range(int(1.2 / DT)):
        _schritt(welt, (auto,), DT)
    assert auto.physics.slip_angle_deg < 3.0
    assert auto.physics.achs_griff == (1.0, 1.0)
    assert auto.speed * KMH_PER_PXS > 60.0                  # radiert, steht aber nicht


def test_vorderachse_behaelt_haftung_wenn_das_heck_rutscht():
    """Übersteuern: nur das Heck rutscht — die Front kann gegenlenkend fangen."""
    welt = PhysicsWorld()
    auto = _auto(welt, "drifter")
    phys = auto.physics
    radstand = phys.laenge_px() * phys.wheelbase_ratio
    vorn, hinten = phys._achspunkte(radstand)
    laengs = _px(80.0)
    omega = laengs / (vorn.x - hinten.x)      # Heck 45 Grad, Front 0 Grad
    phys.body.velocity = (laengs, -omega * vorn.x)
    phys.body.angular_velocity = omega
    phys.apply_lateral_friction(auto.config.grip, False, 0.0, DT)
    assert phys.slip_angle_deg > 15.0          # am Schwerpunkt: früher beide Achsen schwächer
    assert phys.achs_griff[0] == 1.0
    assert phys.achs_griff[1] < 0.85


def test_handbremse_quer_gleitet_nicht_wie_auf_eis():
    welt = PhysicsWorld()
    auto = _auto(welt, "drifter", (0.0, 0.0), 90.0, (_px(80.0), 0.0))
    _schritt(welt, (auto,), DT, bremse=1.0, handbremse=True)
    # Blockierte Hinterräder quer: Gleitreibung (früher 30 % x 70 %).
    assert auto.physics.achs_griff[1] >= 0.75


def _handbremsdrehung(key, fps):
    welt = PhysicsWorld()
    auto = _auto(welt, key, (0.0, 0.0), 0.0, (_px(90.0), 0.0))
    dt = 1.0 / fps
    for _ in range(round(0.6 / dt)):
        _schritt(welt, (auto,), dt, bremse=1.0, lenkung=1.0, handbremse=True)
    return math.degrees(auto.physics.body.angle)


@pytest.mark.parametrize("fps", [30, 144, 240])
def test_handbremse_dreht_bei_jeder_bildrate_gleich_weit(fps):
    bei_60 = _handbremsdrehung("drifter", 60)
    assert _handbremsdrehung("drifter", fps) == pytest.approx(bei_60, rel=0.2)
