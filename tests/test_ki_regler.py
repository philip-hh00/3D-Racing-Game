"""Bahnregler: folgt einer Bahn am Limit, ohne zu rutschen."""
from __future__ import annotations

import math

import numpy as np
import pymunk

import ki_hilfe as H  # noqa: F401  (Pfade, SDL)
from src.ai.regler import Bahnregler
from src.core.settings import KMH_PER_PXS
from src.entities.vehicle import Vehicle
from src.physics.physics_world import PhysicsWorld

DT = 1.0 / 60.0


def _auto(key, x, y, winkel, v):
    from src.entities.vehicle_factory import VehicleFactory
    H.config(key)
    welt = PhysicsWorld()
    auto = VehicleFactory.create_player_vehicle(key, 1, (x, y), winkel, welt.space, lack="werk")
    auto.physics.body.velocity = (v * math.cos(winkel), v * math.sin(winkel))
    auto.prev_velocity = pymunk.Vec2d(*auto.physics.body.velocity)
    auto.is_analog = True
    return welt, auto


def _bogen(winkel0, r, n=80):
    # Kreis gegen den Uhrzeigersinn um den Ursprung, ab winkel0 voraus
    w = winkel0 + np.linspace(0.0, 1.2, n)
    return np.stack([r * np.cos(w), r * np.sin(w)], axis=1)


def test_haelt_einen_kreis_am_limit():
    r = 1500.0
    grip = H.config("rookie").grip
    v = math.sqrt(0.85 * grip * 380.0 * r)
    welt, auto = _auto("rookie", 0.0, -r, 0.0, v)
    regler = Bahnregler(auto)
    fehler, schlupf = [], []
    for k in range(int(6.0 / DT)):
        p = auto.physics.body.position
        bahn = _bogen(math.atan2(p.y, p.x), r)
        auto.steer_input = regler.lenkung(bahn, auto.speed)
        auto.throttle, auto.brake_input = regler.pedale(auto.speed, v)
        auto.handbrake = False
        Vehicle.update(auto, DT)
        welt.step(DT)
        if k * DT > 2.0:
            fehler.append(abs(math.hypot(p.x, p.y) - r))
            schlupf.append(auto.physics.reifen_schlupf_deg)
    assert max(fehler) < 45.0
    assert max(schlupf) < 6.0


def test_findet_von_der_seite_auf_eine_gerade():
    welt, auto = _auto("supercar", 0.0, 60.0, 0.0, 500.0)
    regler = Bahnregler(auto)
    for _ in range(int(3.0 / DT)):
        x = auto.physics.body.position.x
        bahn = np.stack([np.linspace(x, x + 1500.0, 40), np.zeros(40)], axis=1)
        auto.steer_input = regler.lenkung(bahn, auto.speed)
        auto.throttle, auto.brake_input = regler.pedale(auto.speed, 500.0)
        auto.handbrake = False
        Vehicle.update(auto, DT)
        welt.step(DT)
    assert abs(auto.physics.body.position.y) < 10.0


def test_pedale():
    welt, auto = _auto("rookie", 0.0, 0.0, 0.0, 0.0)
    regler = Bahnregler(auto)
    gas, bremse = regler.pedale(100.0, 300.0)
    assert gas > 0.9 and bremse == 0.0
    gas, bremse = regler.pedale(300.0, 100.0)
    assert gas == 0.0 and bremse > 0.9
    assert regler.pedale(200.0, 201.0)[0] < 0.2       # weich am Ziel
    assert regler.pedale(200.0, 198.0) == (0.0, 0.0)  # Totband


def test_gas_weg_bei_dauerhaftem_querrutschen():
    """Normaler Schlupf lässt das Gas; ab ~30° Querstand geht die KI vom Gas."""
    welt, auto = _auto("rookie", 0.0, 0.0, 0.0, 0.0)
    regler = Bahnregler(auto)
    assert regler.pedale(100.0, 300.0, 8.0)[0] > 0.9
    assert regler.pedale(100.0, 300.0, 20.0)[0] > 0.9
    assert 0.0 < regler.pedale(100.0, 300.0, 34.0)[0] < 0.9
    assert regler.pedale(100.0, 300.0, 45.0)[0] == 0.0
    assert regler.pedale(300.0, 100.0, 45.0)[1] > 0.9      # Bremsen bleibt
