"""Tastaturlenkung mit Tempo- und Haftungsgrenze (30.09.2026).

Gemeldet: „die Lenkung ist mit der Tastatur sehr direkt. Damit geht ja auch nur
ganz oder gar nicht … das ist schwierig bei hohen Geschwindigkeiten zu lenken."

Gemessen: bei 150 km/h brachte die Taste in ~0,25 s rund 17° Radeinschlag, die
Haftung trägt dort ~2,5°. Jetzt: Höchsteinschlag aus der Haftung (etwas darüber,
damit man provozieren kann), weiche Rampe hin und zurück, beim Driften mehr
Einschlag zum Gegenlenken.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk

from src.core.settings import KMH_PER_PXS
from src.physics.physics_world import PhysicsWorld

DT = 1.0 / 60.0


def _auto(kmh: float, key: str = "rookie"):
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_config(key):
        VehicleFactory.load_all_configs()
    welt = PhysicsWorld()
    auto = VehicleFactory.create_player_vehicle(key, 1, (0.0, 0.0), 0.0, welt.space, lack="werk")
    auto.physics.body.velocity = (kmh / KMH_PER_PXS, 0.0)
    auto.prev_velocity = pymunk.Vec2d(*auto.physics.body.velocity)
    auto.is_analog = False
    return welt, auto


def _schritte(welt, auto, sekunden, lenkung, gas=0.35):
    from src.entities.vehicle import Vehicle
    schlupf = []
    for _ in range(max(1, round(sekunden / DT))):
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = gas, 0.0, lenkung, False
        Vehicle.update(auto, DT)
        welt.step(DT)
        schlupf.append(auto.physics.reifen_schlupf_deg)
    return schlupf


def test_bei_tempo_bleibt_voller_einschlag_im_griff():
    welt, auto = _auto(150.0)
    richtung0 = auto.physics.body.angle
    schlupf = _schritte(welt, auto, 1.0, 1.0)
    # das Auto dreht deutlich ein …
    assert abs(auto.physics.body.angle - richtung0) > math.radians(20)
    # … ohne dass die Vorderräder dauerhaft schieben
    assert sum(schlupf[-30:]) / 30 < 8.0


def test_kurzes_tippen_lenkt_nur_wenig():
    welt, auto = _auto(150.0)
    _schritte(welt, auto, 1.0, 1.0)
    voll = abs(auto.physics.steer_angle)
    welt, auto = _auto(150.0)
    _schritte(welt, auto, 0.05, 1.0)
    assert abs(auto.physics.steer_angle) < 0.5 * voll


def test_langsam_bleibt_der_volle_einschlag():
    welt, auto = _auto(15.0)
    _schritte(welt, auto, 0.6, 1.0, gas=0.1)
    assert abs(auto.physics.steer_angle) > math.radians(25)


def test_loslassen_stellt_zurueck():
    welt, auto = _auto(100.0)
    _schritte(welt, auto, 0.6, 1.0)
    _schritte(welt, auto, 0.35, 0.0)
    assert abs(auto.physics.steer_angle) < math.radians(0.5)
