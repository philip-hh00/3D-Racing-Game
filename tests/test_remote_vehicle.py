"""Tests for the networked ghost car (src/entities/remote_vehicle.py).

Runs under pytest *and* standalone (``python tests/test_remote_vehicle.py``).

Playback is snapshot interpolation: snapshots are timestamped on arrival and
the ghost is drawn INTERP_DELAY behind real time, between the two snapshots
that bracket that render time. The regression these guard against is a ghost
that jumps — from jitter, a late packet, or an uneven sender frame rate. It
must instead only ever move between positions the sender actually reported,
and coast (not freeze, not dart) when the buffer runs dry.

Time is driven through the module's ``_clock`` hook so the tests are
deterministic and fast — no real sleeping, no dependence on frame timing.

Needs pymunk and a dummy display (the ghost builds a renderer), but no window.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import pymunk

pygame.init()
pygame.display.set_mode((64, 64))

from src.entities import remote_vehicle as rvmod
from src.entities.remote_vehicle import (
    RemoteVehicle, MAX_EXTRAPOLATION,
    INTERP_DELAY_MIN, INTERP_DELAY_MAX, INTERP_DELAY_START,
)  # noqa: F401 — some are used only for bounds assertions
from src.entities.vehicle_factory import VehicleFactory

VehicleFactory.load_all_configs()

SPEED = 400.0        # px/s, straight line
DT    = 1.0 / 60.0   # render step
SEND  = 1.0 / 30.0   # server send interval


class _Clock:
    """Virtual monotonic clock installed into the module under test."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _install_clock() -> _Clock:
    clk = _Clock()
    rvmod._clock = clk
    return clk


def _restore_clock():
    rvmod._clock = __import__("time").monotonic


def _ghost(vid: int = 1) -> RemoteVehicle:
    return RemoteVehicle(vehicle_id=vid, sender_slot=1,
                         space=pymunk.Space(), config_key="rookie")


def _snapshot(x: float, vx: float = SPEED) -> dict:
    return {"x": x, "y": 0.0, "angle": 0.0,
            "vx": vx, "vy": 0.0, "omega": 0.0, "lap": 1, "wp": 0}


def _drive(ghost, clk, seconds, *, send=SEND, gap=None):
    """Feed snapshots at *send* interval while advancing the clock at DT, with
    an optional (start, end) window in seconds where packets are dropped.
    Packets carry a send_time and arrive immediately (no latency/jitter), so a
    clean line settles the buffer at the floor. Returns per-frame speed samples."""
    t = 0.0
    next_send = 0.0
    prev = None
    speeds = []
    steps = int(seconds / DT)
    for _ in range(steps):
        in_gap = gap is not None and gap[0] <= t < gap[1]
        if t >= next_send and not in_gap:
            st = clk()   # send_time on the (shared, in this test) clock
            ghost.apply_snapshot(_snapshot(SPEED * t), send_time=st, arrival=st)
            next_send = t + send
        clk.advance(DT)
        ghost.update(DT)
        if prev is not None:
            speeds.append((ghost._pos[0] - prev) / DT)
        prev = ghost._pos[0]
        t += DT
    return speeds


# ---------------------------------------------------------------------------
# Smooth playback
# ---------------------------------------------------------------------------


def test_steady_stream_tracks_the_senders_speed():
    clk = _install_clock()
    try:
        g = _ghost()
        speeds = _drive(g, clk, 2.0)[40:]   # skip warm-up before the buffer fills
        assert min(speeds) > 0.9 * SPEED
        assert max(speeds) < 1.1 * SPEED
    finally:
        _restore_clock()


def test_playback_never_moves_backwards_on_a_forward_sender():
    clk = _install_clock()
    try:
        g = _ghost()
        speeds = _drive(g, clk, 2.0)[40:]
        assert min(speeds) >= -1.0     # no rubber-band reversal
    finally:
        _restore_clock()


def test_a_dropped_packet_does_not_stall_the_ghost():
    clk = _install_clock()
    try:
        g = _ghost()
        speeds = _drive(g, clk, 3.0, gap=(1.4, 1.55))   # 150 ms of loss
        # Pure interpolation (no forward guessing) bridges a real gap by capped
        # extrapolation, then eases back onto the interpolated path — the ghost
        # keeps moving through the whole gap and never freezes. A brief dip at
        # the re-sync is accepted: not guessing the future is the whole point.
        window = speeds[80:110]
        assert min(window) > 0.2 * SPEED, f"ghost stalled to {min(window):.0f} px/s"
        assert min(window) > 1.0, "ghost froze"
    finally:
        _restore_clock()


def test_no_catch_up_dart_after_a_gap():
    clk = _install_clock()
    try:
        g = _ghost()
        speeds = _drive(g, clk, 3.0, gap=(1.4, 1.55))
        assert max(speeds) < 1.5 * SPEED, f"ghost darted to {max(speeds):.0f} px/s"
    finally:
        _restore_clock()


def test_jittery_sender_still_plays_back_smoothly():
    """Uneven send spacing (a slow sender) must not reach the drawn motion."""
    clk = _install_clock()
    try:
        g = _ghost()
        import random
        rng = random.Random(1)
        t = 0.0
        next_send = 0.0
        prev = None
        speeds = []
        for _ in range(int(3.0 / DT)):
            if t >= next_send:
                g.apply_snapshot(_snapshot(SPEED * t))
                next_send = t + SEND * rng.uniform(0.4, 2.2)   # jittery spacing
            clk.advance(DT)
            g.update(DT)
            if prev is not None:
                speeds.append((g._pos[0] - prev) / DT)
            prev = g._pos[0]
            t += DT
        window = speeds[40:]
        assert min(window) > 0.4 * SPEED
        assert max(window) < 1.8 * SPEED
    finally:
        _restore_clock()


# ---------------------------------------------------------------------------
# Buffer exhaustion
# ---------------------------------------------------------------------------


def test_a_silent_peer_comes_to_rest_instead_of_flying_away():
    clk = _install_clock()
    try:
        g = _ghost()
        g.apply_snapshot(_snapshot(0.0))
        clk.advance(MAX_EXTRAPOLATION + 0.5)
        for _ in range(180):
            clk.advance(DT)
            g.update(DT)
        # Extrapolation is capped: it may not run beyond MAX_EXTRAPOLATION worth
        # of travel from the last snapshot.
        assert g._pos[0] <= SPEED * MAX_EXTRAPOLATION + 1.0
    finally:
        _restore_clock()


# ---------------------------------------------------------------------------
# Adaptive delay
# ---------------------------------------------------------------------------


def test_a_steady_line_shrinks_the_delay_to_the_floor():
    """No jitter → the buffer adapts down to the floor (not below, so playback
    stays interpolation, never forward extrapolation)."""
    clk = _install_clock()
    try:
        g = _ghost()
        _drive(g, clk, 6.0)   # long steady stream
        assert g._delay <= INTERP_DELAY_START
        assert g._delay >= INTERP_DELAY_MIN - 1e-9
    finally:
        _restore_clock()


def _delay_after(lateness_samples) -> float:
    """Run a fresh ghost's delay adaptation over a list of packet 'lateness'
    values (how late each packet was vs. its sender-timeline slot)."""
    g = _ghost()
    for late in lateness_samples:
        g._update_delay(late)
    return g._delay


def test_a_jittery_line_buffers_more_than_a_steady_one():
    steady = _delay_after([0.0] * 200)          # every packet on time
    import random
    rng = random.Random(3)
    jittery = _delay_after([rng.uniform(0.0, 0.07) for _ in range(200)])
    assert jittery > steady
    assert jittery <= INTERP_DELAY_MAX


def test_a_steady_line_settles_at_the_floor():
    """Every packet on time (lateness 0) → the buffer rests at the floor, which
    keeps playback interpolating instead of extrapolating."""
    settled = _delay_after([0.0] * 300)
    assert abs(settled - INTERP_DELAY_MIN) < 0.005


def test_delay_grows_faster_than_it_shrinks():
    """Asymmetric adaptation: react quickly when the line worsens, recover
    slowly. Tested on the raw move toward a fixed target."""
    from src.entities.remote_vehicle import ADAPT_UP, ADAPT_DOWN
    assert ADAPT_UP > ADAPT_DOWN

    # Same distance to target, one step up vs one step down.
    g = _ghost()
    g._jitter = 0.05           # target = MIN + JITTER_SIGMAS * 0.05
    g._delay = 0.05            # below target → should jump up fast
    g._update_delay(0.05)
    up_step = g._delay - 0.05

    g2 = _ghost(8)
    g2._jitter = 0.0           # target = floor
    g2._delay = 0.15           # above target → should ease down slowly
    g2._update_delay(0.0)
    down_step = 0.15 - g2._delay

    assert up_step > 0 and down_step > 0
    assert up_step > down_step


def test_burst_delivery_does_not_snap_the_ghost_backwards():
    """The real-world failure: after a gap several packets arrive together
    (WLAN buffering). On the sender timeline they are still spread out, so
    playback must stay monotone — no backward jump."""
    clk = _install_clock()
    try:
        g = _ghost()
        SEND_HZ = 0.02
        OFFSET = -500.0          # sender clock runs 500 s behind local
        # 6 normal packets, then a 118 ms gap, then 5 packets all arriving now.
        normal = [i * SEND_HZ for i in range(6)]
        gap_arrival = normal[-1] + SEND_HZ + 0.118
        burst = [normal[-1] + SEND_HZ + i * SEND_HZ for i in range(5)]
        delivered = [(t, t + OFFSET, SPEED * t) for t in normal]
        delivered += [(gap_arrival, b + OFFSET, SPEED * b) for b in burst]
        delivered.sort(key=lambda d: d[0])

        di = 0
        t = 0.0
        prev = None
        back = []
        for _ in range(int(1.5 / DT)):
            while di < len(delivered) and delivered[di][0] <= t:
                arr, st, x = delivered[di]
                g.apply_snapshot(_snapshot(x), send_time=st, arrival=arr)
                di += 1
            clk.advance(DT)
            g.update(DT)
            if prev is not None and g._pos[0] - prev < -0.5:
                back.append(prev - g._pos[0])
            prev = g._pos[0]
            t += DT
        assert not back, f"{len(back)} backward jumps (max {max(back) if back else 0:.0f}px)"
    finally:
        _restore_clock()


def test_clock_offset_is_estimated_from_the_least_delayed_packet():
    clk = _install_clock()
    try:
        g = _ghost()
        OFFSET = 12345.0
        # Three packets: latencies 0.05, 0.02 (the min), 0.08. Offset ≈ min.
        for send_t, lat in [(0.0, 0.05), (0.1, 0.02), (0.2, 0.08)]:
            g.apply_snapshot(_snapshot(SPEED * send_t),
                             send_time=send_t - OFFSET,
                             arrival=send_t + lat)
        # arrival - send_time = OFFSET + latency; the estimate tracks the min.
        assert abs(g._clock_offset - (OFFSET + 0.02)) < 0.005
    finally:
        _restore_clock()


def test_out_of_order_packet_is_dropped():
    clk = _install_clock()
    try:
        g = _ghost()
        g.apply_snapshot(_snapshot(100.0), send_time=1.0, arrival=1.0)
        g.apply_snapshot(_snapshot(200.0), send_time=2.0, arrival=2.0)
        n = len(g._buffer)
        # An older send_time than the newest buffered → superseded, not added.
        g.apply_snapshot(_snapshot(150.0), send_time=1.5, arrival=2.01)
        assert len(g._buffer) == n
        # but it still updates the raw target (for takeover)
        assert g._target_pos == (150.0, 0.0)
    finally:
        _restore_clock()


def test_delay_never_leaves_its_bounds():
    clk = _install_clock()
    try:
        g = _ghost()
        for _ in range(200):
            g._update_delay(0.001)      # ultra-steady
        assert g._delay >= INTERP_DELAY_MIN - 1e-9
        g2 = _ghost(9)
        import random
        rng = random.Random(1)
        for _ in range(200):
            g2._update_delay(rng.uniform(0.005, 0.5))   # wild
        assert g2._delay <= INTERP_DELAY_MAX + 1e-9
    finally:
        _restore_clock()


# ---------------------------------------------------------------------------
# Collision body
# ---------------------------------------------------------------------------


def test_hitbox_is_the_car_silhouette_not_a_bounding_box():
    clk = _install_clock()
    try:
        g = _ghost(3)
        assert len(g._shape.get_vertices()) > 4
    finally:
        _restore_clock()


def test_kinematic_body_carries_its_velocity():
    clk = _install_clock()
    try:
        g = _ghost(4)
        _drive(g, clk, 0.5)
        assert g._body.velocity.length > 0.0
    finally:
        _restore_clock()


def test_body_follows_the_rendered_position():
    clk = _install_clock()
    try:
        g = _ghost(5)
        _drive(g, clk, 0.5)
        assert abs(g._body.position.x - g._pos[0]) < 0.01
        assert abs(g._body.position.y - g._pos[1]) < 0.01
    finally:
        _restore_clock()


# ---------------------------------------------------------------------------
# Takeover reads the newest raw snapshot, not the interpolated state
# ---------------------------------------------------------------------------


def test_target_mirrors_the_newest_snapshot_for_takeover():
    clk = _install_clock()
    try:
        g = _ghost(6)
        g.apply_snapshot(_snapshot(100.0))
        g.apply_snapshot(_snapshot(140.0))
        # AI takeover spawns at _target_pos — must be the latest reported point,
        # not the delayed playback position.
        assert g._target_pos == (140.0, 0.0)
    finally:
        _restore_clock()


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
