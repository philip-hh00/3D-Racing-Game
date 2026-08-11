"""Tests for the DNF grace window (src/states/race_manager.py).

Runs under pytest *and* standalone (``python tests/test_dnf_deadline.py``).

Rule: once the first car finishes, every other car gets one more window to
cross the line — the leader's SLOWEST single lap. No absolute cap. Applies to
every race length (the 1-lap case is just "that lap's time"). Online, a
server-authoritative deadline can override the locally computed one.

Neu am 29.07.2026: die letzten fuenf Sekunden dieser Frist zaehlt das HUD
herunter. Die Frist selbst bleibt die alte Rechnung — vorher lief sie
unsichtbar ab und das Rennen endete fuer einen Nachzuegler ohne Vorwarnung.

Needs a real track (pymunk), no display window beyond the renderer stub.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import pymunk

pygame.init()
pygame.display.set_mode((64, 64))

from src.states.race_manager import RaceManager
from src.track.track import Track

_TRACK = os.path.join("data", "tracks", "oval.json")


class _Car:
    def __init__(self, vid):
        self.id = vid
        self.body = None
        self.config = None


def _manager(n=2, laps=3):
    space = pymunk.Space()
    track = Track(_TRACK, space)
    return RaceManager([_Car(i + 1) for i in range(n)], track, total_laps=laps)


def _finish_leader(rm, vid, lap_times, at_race_time):
    """Record *vid* as the first finisher with the given lap times."""
    rm.lap_trackers[vid].lap_times = list(lap_times)
    rm.state = "finishing"
    rm.race_time = at_race_time
    rm._record_finish(next(v for v in rm.vehicles if v.id == vid), dnf=False)


# ---------------------------------------------------------------------------
# Grace window formula
# ---------------------------------------------------------------------------


def test_no_deadline_before_anyone_finishes():
    rm = _manager()
    assert rm.dnf_deadline() is None
    assert rm.sekunden_bis_dnf() is None


def test_grace_is_the_leaders_slowest_lap():
    rm = _manager(laps=3)
    _finish_leader(rm, 1, [20.0, 35.0, 25.0], at_race_time=80.0)
    assert rm.leader_slowest_lap() == 35.0
    assert rm.dnf_deadline() == 80.0 + 35.0


def test_one_lap_race_uses_that_single_lap():
    rm = _manager(laps=1)
    _finish_leader(rm, 1, [42.0], at_race_time=42.0)
    assert rm.dnf_deadline() == 42.0 + 42.0


def test_slowest_lap_is_the_max_not_the_last():
    rm = _manager(laps=3)
    _finish_leader(rm, 1, [50.0, 30.0, 31.0], at_race_time=111.0)
    assert rm.leader_slowest_lap() == 50.0     # first lap was slowest


def test_fallback_grace_when_leader_has_no_recorded_laps():
    rm = _manager()
    _finish_leader(rm, 1, [], at_race_time=100.0)
    assert rm.leader_slowest_lap() == rm.DNF_FALLBACK_GRACE
    assert rm.dnf_deadline() == 100.0 + rm.DNF_FALLBACK_GRACE


# ---------------------------------------------------------------------------
# Countdown: die letzten Sekunden der Frist
# ---------------------------------------------------------------------------


def test_countdown_erst_kurz_vor_ablauf():
    """Ein Zaehler ueber eine ganze Runde waere keine Warnung mehr."""
    rm = _manager(laps=3)
    _finish_leader(rm, 1, [30.0], at_race_time=60.0)     # Frist bis 90.0
    rm.race_time = 80.0
    assert rm.sekunden_bis_dnf() is None, "zu frueh gezaehlt"

    rm.race_time = 87.0
    assert rm.sekunden_bis_dnf() == 3.0


def test_countdown_bleibt_bei_null_stehen():
    rm = _manager(laps=3)
    _finish_leader(rm, 1, [30.0], at_race_time=60.0)
    rm.race_time = 95.0
    assert rm.sekunden_bis_dnf() == 0.0


def test_kein_countdown_solange_noch_niemand_im_ziel_ist():
    rm = _manager()
    rm.state = "racing"
    assert rm.sekunden_bis_dnf() is None


def test_countdown_gilt_auch_fuer_die_server_frist():
    """Online setzt der Server die Frist — der Countdown haengt daran mit."""
    rm = _manager()
    rm.state = "finishing"
    rm.force_deadline(50.0)
    rm.race_time = 40.0
    assert rm.sekunden_bis_dnf() is None
    rm.race_time = 48.0
    assert rm.sekunden_bis_dnf() == 2.0


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


def test_no_dnf_before_the_deadline():
    rm = _manager()
    _finish_leader(rm, 1, [20.0, 35.0, 25.0], at_race_time=80.0)
    rm.race_time = 114.0
    rm._check_finishing_timeout()
    assert 2 not in rm.finished_ids
    assert rm.state == "finishing"


def test_dnf_and_end_at_the_deadline():
    rm = _manager()
    _finish_leader(rm, 1, [20.0, 35.0, 25.0], at_race_time=80.0)
    rm.race_time = 115.5
    rm._check_finishing_timeout()
    assert 2 in rm.finished_ids
    assert rm.state == "finished"
    row = next(r for r in rm.results if r["vehicle_id"] == 2)
    assert row["dnf"] is True
    assert row["finish_time"] is None


def test_everyone_finishing_ends_without_waiting():
    rm = _manager()
    _finish_leader(rm, 1, [40.0], at_race_time=40.0)
    rm.race_time = 41.0
    rm._record_finish(rm.vehicles[1], dnf=False)   # second car finishes cleanly
    rm._check_finishing_timeout()
    assert rm.state == "finished"
    assert all(not r["dnf"] for r in rm.results)


def test_dnf_car_that_got_furthest_ranks_first_among_dnfs():
    rm = _manager(n=3)
    _finish_leader(rm, 1, [30.0], at_race_time=30.0)
    # car 3 is ahead of car 2 on track
    rm.lap_trackers[2].current_lap = 1
    rm.lap_trackers[2].waypoint_progress = 10
    rm.lap_trackers[3].current_lap = 1
    rm.lap_trackers[3].waypoint_progress = 40
    rm._update_standings()
    rm.race_time = 61.0
    rm._check_finishing_timeout()
    dnf_order = [r["vehicle_id"] for r in rm.results if r["dnf"]]
    assert dnf_order == [3, 2]


# ---------------------------------------------------------------------------
# Server-authoritative override
# ---------------------------------------------------------------------------


def test_forced_deadline_overrides_the_local_one():
    rm = _manager()
    _finish_leader(rm, 1, [20.0, 35.0, 25.0], at_race_time=80.0)
    assert rm.dnf_deadline() == 115.0
    rm.force_deadline(95.0)
    assert rm.dnf_deadline() == 95.0


def test_forced_deadline_works_before_any_local_finish():
    """Online a guest may never see a local 'leader' — the server deadline
    must still drive the timeout."""
    rm = _manager(n=1)
    rm.state = "finishing"
    rm.force_deadline(50.0)
    assert rm.dnf_deadline() == 50.0
    rm.race_time = 50.5
    rm._check_finishing_timeout()
    assert 1 in rm.finished_ids
    assert rm.state == "finished"


# ---------------------------------------------------------------------------
# FORCE_FINISH (server told us the grace window is over)
# ---------------------------------------------------------------------------


def test_force_finish_dnfs_a_guest_still_racing():
    """A guest's manager holds only its own car and never enters 'finishing';
    FORCE_FINISH must still end the race with a DNF."""
    rm = _manager(n=1)
    rm.state = "racing"
    rm.race_time = 50.0
    rm.force_finish_remaining()
    assert rm.state == "finished"
    row = rm.results[0]
    assert row["dnf"] is True
    assert row["finish_time"] is None


def test_force_finish_leaves_already_finished_cars_alone():
    rm = _manager(n=2, laps=1)
    _finish_leader(rm, 1, [30.0], at_race_time=30.0)   # car 1 finished cleanly
    rm.force_finish_remaining()
    car1 = next(r for r in rm.results if r["vehicle_id"] == 1)
    car2 = next(r for r in rm.results if r["vehicle_id"] == 2)
    assert car1["dnf"] is False
    assert car2["dnf"] is True


def test_force_finish_is_idempotent():
    rm = _manager(n=1)
    rm.state = "racing"
    rm.force_finish_remaining()
    rm.force_finish_remaining()
    assert len(rm.results) == 1


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
