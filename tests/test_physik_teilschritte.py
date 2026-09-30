"""Kräfte über alle Teilschritte, Quietschen nach Reifenschlupf (30.09.2026).

Gemeldet: „Alle Autos beschleunigen nach dem Wandkontakt zu langsam. Außerdem
gibt es immer beim Beschleunigen ein Reifenquietschen."

**Kräfte.** ``PhysicsWorld.step`` teilt ein Bild in ``PHYSICS_SUBSTEPS``
pymunk-Schritte. pymunk löscht ``body.force`` nach jedem Schritt; die Fahrzeuge
legen ihre Kräfte aber nur einmal je Bild an. Motor, Bremse, Luft- und
Rollwiderstand wirkten so nur im ersten Teilschritt — ein Drittel. 0–100 km/h
dauerte beim rookie 20 s.

**Quietschen.** Es hing am Winkel zwischen Fahrtrichtung und Längsachse am
Schwerpunkt. In einer langsamen, engen Kurve ist der rein geometrisch 15–20°
groß, ohne dass ein Reifen rutscht; echtes Untersteuern bei Tempo blieb dagegen
still. Maßgeblich ist der Schlupf an den Reifen.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk
import pytest

from src.core.settings import KMH_PER_PXS
from src.physics.physics_world import PhysicsWorld

DT = 1.0 / 60.0


def test_eine_kraft_wirkt_das_ganze_bild():
    welt = PhysicsWorld()
    koerper = pymunk.Body(2.0, 1.0)
    welt.space.add(koerper, pymunk.Circle(koerper, 1.0))
    koerper.apply_force_at_local_point((6.0, 0.0), (0.0, 0.0))
    welt.step(DT)
    # a = F/m = 3, über ein ganzes Bild
    assert koerper.velocity.x == pytest.approx(3.0 * DT, rel=1e-6)


def test_die_kraft_gilt_nur_fuer_ein_bild():
    welt = PhysicsWorld()
    koerper = pymunk.Body(1.0, 1.0)
    welt.space.add(koerper, pymunk.Circle(koerper, 1.0))
    koerper.apply_force_at_local_point((1.0, 0.0), (0.0, 0.0))
    welt.step(DT)
    welt.step(DT)
    assert koerper.velocity.x == pytest.approx(DT, rel=1e-6)


def _auto(key: str, kmh: float = 0.0):
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_config(key):
        VehicleFactory.load_all_configs()
    welt = PhysicsWorld()
    auto = VehicleFactory.create_player_vehicle(key, 1, (0.0, 0.0), 0.0, welt.space, lack="werk")
    auto.physics.body.velocity = (kmh / KMH_PER_PXS, 0.0)
    auto.prev_velocity = pymunk.Vec2d(*auto.physics.body.velocity)
    return welt, auto


def _fahren(welt, auto, sekunden, gas=1.0, bremse=0.0, lenkung=0.0, handbremse=False):
    from src.entities.vehicle import Vehicle
    groesster = 0.0
    for _ in range(int(sekunden / DT)):
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = gas, bremse, lenkung, handbremse
        Vehicle.update(auto, DT)
        welt.step(DT)
        groesster = max(groesster, auto.physics.reifen_schlupf_deg)
    return groesster


@pytest.mark.parametrize("key, grenze", [("rookie", 9.0), ("supercar", 6.0)])
def test_null_auf_hundert_ist_realistisch(key, grenze):
    welt, auto = _auto(key)
    from src.entities.vehicle import Vehicle
    t = 0.0
    while auto.speed * KMH_PER_PXS < 100.0 and t < 30.0:
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = 1.0, 0.0, 0.0, False
        Vehicle.update(auto, DT)
        welt.step(DT)
        t += DT
    assert t < grenze


def test_bremsweg_aus_hundert_bleibt_wie_bisher():
    # Vor der Korrektur ~35 m (Bremskraft dreifach eingetragen, wirkte zu 1/3).
    welt, auto = _auto("rookie", 100.0)
    start = auto.physics.body.position
    _fahren(welt, auto, 6.0, gas=0.0, bremse=1.0)
    weg_m = (auto.physics.body.position - start).length * 0.08
    assert 30.0 < weg_m < 40.0


def test_frontal_gegen_die_wand_prallt_kaum_ab():
    """Gemeldet 30.09.2026: „wie ein Flummi von der Wand abgestoßen"."""
    import pymunk as pm
    from src.track.track import Track
    welt, auto = _auto("rookie", 60.0)
    wand = pm.Segment(welt.space.static_body, (300.0, -500.0), (300.0, 500.0), 2.0)
    # dieselben Werte wie die Streckenwände
    quelle = Track.__new__(Track)
    raum = pm.Space()
    quelle.outer_wall = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    quelle.inner_wall = []
    quelle._build_physics(raum)
    wand.elasticity = quelle.wall_segments[0].elasticity
    wand.friction = quelle.wall_segments[0].friction
    welt.space.add(wand)
    rueck = 0.0
    from src.entities.vehicle import Vehicle
    for _ in range(int(2.0 / DT)):
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = 0.0, 0.0, 0.0, False
        Vehicle.update(auto, DT)
        welt.step(DT)
        rueck = max(rueck, -auto.physics.body.velocity.x)
    assert rueck * KMH_PER_PXS < 2.0


def test_anfahren_im_einschlag_rutscht_nicht():
    welt, auto = _auto("rookie")
    assert _fahren(welt, auto, 3.0, lenkung=1.0) < 8.0


def test_rutschen_mit_der_handbremse_ist_schlupf():
    # Seit der Lenkgrenze (test_lenkung.py) schiebt ein Auto bei Tempo nicht
    # mehr über die Vorderräder, nur weil die Taste gedrückt ist; echter
    # Schlupf entsteht mit der Handbremse.
    welt, auto = _auto("drifter", 90.0)
    assert _fahren(welt, auto, 0.5, gas=0.0, lenkung=1.0, handbremse=True) > 8.0


def test_das_quietschen_folgt_dem_reifenschlupf():
    from src.core import sfx_rennen as sr
    welt, auto = _auto("rookie")
    _fahren(welt, auto, 2.0, lenkung=1.0)
    assert auto.physics.slip_angle_deg > sr.SCHLUPF_AB      # Schwerpunkt: groß
    assert sr._schraeglauf(auto) < sr.SCHLUPF_AB            # Reifen: kein Rutschen
