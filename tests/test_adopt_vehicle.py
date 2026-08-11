"""Tests for RaceManager.adopt_vehicle — taking a car over mid-race.

Runs under pytest *and* standalone (``python tests/test_adopt_vehicle.py``).

This is what happens when an online player drops out and the host's AI
inherits their car (``online_team_tt_plan.md`` §6.4). The delicate part is the
lap state: the replacement has to continue where the human was, and it has to
be told which checkpoint it is heading for.

Checkpoints are a *subset* of the track's waypoints, so the two indices live on
different scales — the oval has 330 waypoints and 6 checkpoints. Deriving one
from the other naively puts the car on the wrong expected checkpoint, and
``LapTracker.on_checkpoint_hit`` silently ignores every crossing that is not
the expected one: the car would drive forever without completing a lap and end
up DNF, which is exactly what the takeover exists to prevent.

Needs a real track (and therefore pymunk), but no display.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymunk

from src.states.race_manager import RaceManager
from src.track.track import Track

_TRACK = os.path.join("data", "tracks", "oval.json")


class _FakeVehicle:
    """Only needs an id — adopt_vehicle never touches the physics body."""

    def __init__(self, vid: int) -> None:
        self.id = vid
        self.body = None


def _manager() -> tuple[RaceManager, Track]:
    space = pymunk.Space()
    track = Track(_TRACK, space)
    return RaceManager([_FakeVehicle(1)], track, total_laps=3), track


def _checkpoint_waypoints(track: Track) -> list[int]:
    return [i for i, w in enumerate(track.waypoints) if w.is_checkpoint]


# ---------------------------------------------------------------------------
# Checkpoint mapping
# ---------------------------------------------------------------------------


def test_the_two_indices_really_are_on_different_scales():
    """Guards the premise of this whole file — if a track ever had as many
    checkpoints as waypoints, the mapping below would be trivially right for
    the wrong reason."""
    _rm, track = _manager()
    cps = _checkpoint_waypoints(track)
    assert len(cps) < len(track.waypoints)
    assert len(cps) >= 2


def test_start_of_lap_expects_the_first_checkpoint():
    """Index 0 is start/finish and counts as already passed."""
    rm, _track = _manager()
    assert rm._checkpoint_after(0) == 1


def test_checkpoint_advances_exactly_at_its_waypoint():
    rm, track = _manager()
    cps = _checkpoint_waypoints(track)
    assert rm._checkpoint_after(cps[1] - 1) == 1
    assert rm._checkpoint_after(cps[1]) == 2
    assert rm._checkpoint_after(cps[1] + 1) == 2


def test_after_the_last_checkpoint_it_wraps_to_start_finish():
    rm, track = _manager()
    cps = _checkpoint_waypoints(track)
    assert rm._checkpoint_after(cps[-1]) == 0
    assert rm._checkpoint_after(len(track.waypoints) - 1) == 0


def test_mapping_is_monotonic_across_a_whole_lap():
    """Walking the lap must never make the expected checkpoint go backwards
    (apart from the single wrap at the end)."""
    rm, track = _manager()
    seen = [rm._checkpoint_after(wp) for wp in range(len(track.waypoints))]
    wraps = sum(1 for a, b in zip(seen, seen[1:]) if b < a)
    assert wraps == 1
    assert seen[0] == 1


def test_result_is_always_a_valid_checkpoint_index():
    rm, track = _manager()
    n = len(_checkpoint_waypoints(track))
    for wp in range(0, len(track.waypoints), 7):
        assert 0 <= rm._checkpoint_after(wp) < n


# ---------------------------------------------------------------------------
# Adoption
# ---------------------------------------------------------------------------


def test_adopted_vehicle_keeps_the_humans_lap_and_progress():
    rm, track = _manager()
    cps = _checkpoint_waypoints(track)
    wp = cps[2] + 3
    rm.adopt_vehicle(_FakeVehicle(207), lap=2, waypoint_progress=wp, elapsed=4.5)
    tracker = rm.lap_trackers[207]
    assert tracker.current_lap == 2
    assert tracker.waypoint_progress == wp
    assert tracker.current_lap_time == 4.5
    assert tracker.next_checkpoint_idx == 3


def test_adopted_vehicle_joins_the_field_and_the_standings():
    rm, _track = _manager()
    before = len(rm.vehicles)
    rm.adopt_vehicle(_FakeVehicle(207), lap=1)
    assert len(rm.vehicles) == before + 1
    assert 207 in rm.lap_trackers
    assert any(v.id == 207 for v in rm._standings)


def test_adoption_is_idempotent():
    """A duplicate PLAYER_LEFT must not build a second tracker or overwrite
    the progress of the first one."""
    rm, _track = _manager()
    rm.adopt_vehicle(_FakeVehicle(207), lap=3, waypoint_progress=40.0)
    count = len(rm.vehicles)
    rm.adopt_vehicle(_FakeVehicle(207), lap=1, waypoint_progress=0.0)
    assert len(rm.vehicles) == count
    assert rm.lap_trackers[207].current_lap == 3


def test_lap_number_is_never_below_one():
    rm, _track = _manager()
    rm.adopt_vehicle(_FakeVehicle(207), lap=0)
    assert rm.lap_trackers[207].current_lap == 1


def test_negative_elapsed_is_clamped():
    rm, _track = _manager()
    rm.adopt_vehicle(_FakeVehicle(207), elapsed=-5.0)
    assert rm.lap_trackers[207].current_lap_time == 0.0


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def _run_all() -> int:
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    total = len(funcs)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
