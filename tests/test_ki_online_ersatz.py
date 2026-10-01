"""Online-Ersatz-KI: das Auto eines ausgestiegenen Spielers sieht das Feld und ist vorbereitet."""
from __future__ import annotations

import types

import pymunk

import ki_hilfe as H  # noqa: F401  (Pfad, SDL-Treiber)


def _rennstand(monkeypatch):
    from src.states.race_state import RaceState
    from src.entities.vehicle_factory import VehicleFactory
    H.config("rookie")
    rs = RaceState(types.SimpleNamespace(transition=lambda *a, **k: None))
    space = pymunk.Space()
    rs.track = H.strecke_laden("oval", space)
    rs.physics_world = types.SimpleNamespace(space=space)
    rs._online = True
    monkeypatch.setattr(RaceState, "_is_online_host", lambda self: True)
    rs.race_manager = types.SimpleNamespace(
        state="racing", lap_trackers={}, race_time=10.0,
        adopt_vehicle=lambda *a, **k: None)
    rs._remote_map = {(1, 1): types.SimpleNamespace(
        _target_pos=(rs.track.centerline[0][0], rs.track.centerline[0][1]),
        _target_angle=0.0, _target_vel=(0.0, 0.0), lap=1, wp=0)}
    rs._remote_config_keys = {(1, 1): "rookie"}
    rs.ai_vehicles = []
    rs._humans = []
    rs._remote_vehicles = []
    rs._ai_feld = None
    rs._driver_names = {}
    rs._vehicle_model = {}
    assert VehicleFactory.get_config("rookie")
    return rs


def test_ersatz_ki_bekommt_das_feld_und_den_plan(monkeypatch):
    rs = _rennstand(monkeypatch)
    assert rs._takeover_remote_vehicle(1)
    ctrl = rs.ai_vehicles[-1].controller
    assert rs._ai_feld is not None
    assert ctrl.opponents is rs._ai_feld          # dieselbe Liste wie alle anderen
    assert ctrl.fahrplan is not None              # Plan steht schon, kein Ruckler im Rennen
