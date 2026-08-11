"""Tests for Dead Reckoning and UDP Bump impulses."""
from __future__ import annotations

import math
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymunk
from src.entities.remote_vehicle import RemoteVehicle
from src.net import protocol


def test_dead_reckoning_smooths_corrections_without_snapping():
    space = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=1, space=space)

    # Initial snapshot at origin
    rv.apply_snapshot({"x": 0.0, "y": 0.0, "vx": 100.0, "vy": 0.0, "angle": 0.0})
    assert rv.position == (0.0, 0.0)

    # Update for 0.1s: dead reckoning moves sim_pos to (10.0, 0.0)
    rv.update(0.1)
    assert round(rv.position[0], 1) == 10.0

    # New packet arrives with x=12.0 (2.0px error offset absorbed into error_pos)
    rv.apply_snapshot({"x": 12.0, "y": 0.0, "vx": 100.0, "vy": 0.0, "angle": 0.0})
    # Instant position must start at pre-packet drawn position (10.0), NOT jump to 12.0!
    assert abs(rv.position[0] - 10.0) < 0.1

    # Over 0.1s of update frames, error decays smoothly and position converges to simulated trajectory
    for _ in range(6):
        rv.update(0.0166)

    # Drawn position should be moving smoothly along vx=100
    assert rv.position[0] > 10.0


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

