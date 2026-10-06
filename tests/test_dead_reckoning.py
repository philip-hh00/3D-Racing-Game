"""Tests for Dead Reckoning and UDP Bump impulses."""
from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymunk
from src.entities.remote_vehicle import RemoteVehicle
from src.net import protocol


def test_dead_reckoning_smooths_corrections_without_snapping(monkeypatch):
    """Laeuft der Puffer leer, rechnet das Abbild hoch. Kommt dann ein Paket,
    das die Hochrechnung korrigiert, springt die gezeichnete Lage nicht — der
    Unterschied wird ueber die naechsten Bilder abgebaut, vorwaerts."""
    from src.entities import remote_vehicle as rv_mod
    uhr = [100.0]
    monkeypatch.setattr(rv_mod, "_clock", lambda: uhr[0])
    space = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=1, space=space)

    # Erstes Paket am Ursprung, Senderuhr = eigene Uhr
    rv.apply_snapshot({"x": 0.0, "y": 0.0, "vx": 100.0, "vy": 0.0, "angle": 0.0},
                      send_time=100.0, arrival=100.0)
    assert rv.position == (0.0, 0.0)

    # 0.3 s ohne Paket: Wiedergabe laeuft ueber das Pufferende hinaus und
    # rechnet mit vx=100 hoch.
    for _ in range(18):
        uhr[0] += 1.0 / 60.0
        rv.update(1.0 / 60.0)
    vorher = rv.position[0]
    assert vorher > 10.0

    # Das naechste Paket meldet den Wagen deutlich weiter hinten als hochgerechnet:
    # er hat gebremst und rollt nun mit 40 px/s weiter.
    rv.apply_snapshot({"x": 10.0, "y": 0.0, "vx": 40.0, "vy": 0.0, "angle": 0.0},
                      send_time=100.3, arrival=uhr[0])
    assert abs(rv.position[0] - vorher) < 0.1     # kein Sprung beim Eintreffen

    letzte = rv.position[0]
    for i in range(1, 91):
        uhr[0] += 1.0 / 60.0
        if i % 2 == 0:
            st = 100.3 + i / 60.0
            rv.apply_snapshot({"x": 10.0 + 40.0 * (st - 100.3), "y": 0.0, "vx": 40.0,
                               "vy": 0.0, "angle": 0.0}, send_time=st, arrival=uhr[0])
        rv.update(1.0 / 60.0)
        assert rv.position[0] >= letzte - 1e-6     # nie rueckwaerts
        letzte = rv.position[0]
    # ... und am Ende wieder auf dem gemeldeten Weg (kurz hinter dem Sender).
    soll = 10.0 + 40.0 * (uhr[0] - 100.3 - rv._delay)
    assert abs(rv.position[0] - soll) < 3.0


def test_udp_bump_packing_and_unpacking():
    data = protocol.pack_bump(lobby_id="ROOM12", sender_slot=1, target_slot=2, impulse_x=150.5, impulse_y=-80.25)
    unpacked = protocol.unpack_bump(data)

    assert unpacked is not None
    assert unpacked["lobby_id"] == "ROOM12"
    assert unpacked["sender_slot"] == 1
    assert unpacked["target_slot"] == 2
    assert abs(unpacked["impulse"][0] - 150.5) < 0.01
    assert abs(unpacked["impulse"][1] - (-80.25)) < 0.01


def test_race_state_vehicle_contact_uses_session_client():
    """Verify that RaceState._on_vehicle_contact retrieves network client via session.get() without AttributeError."""
    from src.states.race_state import RaceState
    from src.net import session, client

    class MockSM:
        def __init__(self):
            self.states = {}

    sm = MockSM()
    rs = RaceState(sm)
    rs._online = True

    sent_bumps = []
    class MockNetClient(client.NetworkClient):
        def __init__(self):
            super().__init__()
            self._alive = True
        def send_bump(self, target_slot, ix, iy):
            sent_bumps.append((target_slot, ix, iy))


    mock_nc = MockNetClient()
    session.set(mock_nc)

    class MockVehicle:
        def __init__(self, is_remote=False, sender_slot=1):
            self.is_remote = is_remote
            self.sender_slot = sender_slot

    local_p = MockVehicle(is_remote=False)
    remote_p = MockVehicle(is_remote=True, sender_slot=2)
    rs.player = local_p

    class MockVec:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    # Trigger contact event
    rs._on_vehicle_contact({
        "impulse": 100.0,
        "total_impulse": MockVec(120.0, -50.0),
        "vehicle_a": local_p,
        "vehicle_b": remote_p,
    })

    assert len(sent_bumps) == 1
    assert sent_bumps[0] == (2, 120.0, -50.0)

    session.clear()

