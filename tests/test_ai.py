"""Unit tests for the AI opponent logic.

Runs under pytest *and* standalone (``python tests/test_ai.py``) so the suite
works even without pytest installed. The AIController is exercised with a
lightweight fake vehicle/track – no pygame or full pymunk space required.

The controller is a pure geometric pursuit follower: it look-aheads along the
waypoints (or the loaded racing line's ``points``), steers toward that target
with a clamped feedback loop, and sets throttle/brake from a proportional
speed controller against ``racing_line.speed_at`` (or a constant fallback).
"""
from __future__ import annotations

import math
import os
import sys

# Allow `import src...` when run directly from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai.difficulty import DIFFICULTIES, get_difficulty
from src.ai.ai_controller import AIController, normalize_angle


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Vec:
    """Minimal stand-in for pymunk.Vec2d (x, y, .length)."""

    def __init__(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y)

    @property
    def length(self) -> float:
        return math.hypot(self.x, self.y)


class _Body:
    def __init__(self, pos: tuple[float, float], angle: float, vel: tuple[float, float]) -> None:
        self._pos = _Vec(*pos)
        self.angle = angle
        self.velocity = _Vec(*vel)
        self.angular_velocity = 0.0

    @property
    def position(self) -> _Vec:
        return self._pos

    @position.setter
    def position(self, val) -> None:
        if isinstance(val, (tuple, list)):
            self._pos = _Vec(val[0], val[1])
        else:
            self._pos = val


class _Physics:
    def __init__(self, body: _Body) -> None:
        self.body = body
        self._space = None  # disables raycasts in tests
        self.steer_angle = 0.0
        self.slip_angle_deg = 0.0


class _Config:
    height_px = 48
    width_px = 28
    wheelbase_m = 2.5
    wheel_diameter = 0.65
    turn_speed = 2.2
    grip = 0.85
    max_speed = 260.0
    mass = 1000.0


class FakeVehicle:
    def __init__(self, pos, angle=0.0, vel=(0.0, 0.0)) -> None:
        self.physics = _Physics(_Body(pos, angle, vel))
        self.config = _Config()
        self.is_touching_wall = False

    @property
    def position(self) -> tuple[float, float]:
        return (self.physics.body.position.x, self.physics.body.position.y)

    @property
    def speed(self) -> float:
        return self.physics.body.velocity.length



class _WP:
    """Waypoint stand-in — the controller reads ``.pos``; ``.x``/``.y`` stay for
    the fake nearest-waypoint search."""

    def __init__(self, x: float, y: float) -> None:
        self.x = float(x)
        self.y = float(y)
        self.pos = (float(x), float(y))
        self.is_checkpoint = False


class FakeTrack:
    """Track with waypoints laid out along the +x axis (y configurable)."""

    def __init__(self, points: list[tuple[float, float]]) -> None:
        self.waypoints = [_WP(x, y) for x, y in points]
        self.track_width = 200.0

    def get_nearest_waypoint_index(self, pos) -> int:
        best, bi = float("inf"), 0
        for i, wp in enumerate(self.waypoints):
            d = (wp.x - pos[0]) ** 2 + (wp.y - pos[1]) ** 2
            if d < best:
                best, bi = d, i
        return bi


class _LineStub:
    """Minimal racing-line stand-in matching the SolvedRacingLine API the
    controller reads: ``.points`` (2D), ``.n`` and ``.speed_at``."""

    def __init__(self, points, speeds=None):
        self.points = [(float(x), float(y)) for x, y in points]
        self.n = len(self.points)
        self.speeds = [float(s) for s in speeds] if speeds is not None else None

    def speed_at(self, i):
        return self.speeds[i % self.n] if self.speeds else 0.0

    def offset_at(self, i):
        return 0.0

    def curvature_at(self, i):
        return 0.0


def _straight_track(n: int = 20, spacing: float = 50.0) -> FakeTrack:
    return FakeTrack([(i * spacing, 0.0) for i in range(n)])


def _make_ctrl(veh: "FakeVehicle", track: "FakeTrack", diff) -> AIController:
    ctrl = AIController(veh, track, diff)
    ctrl._wander_amp = 0.0
    return ctrl


# ---------------------------------------------------------------------------
# Difficulty
# ---------------------------------------------------------------------------


def test_difficulty_values():
    # Presets share skill/line values; character comes from aggression + rubber
    # banding. Hard is the pushiest, easy the only rubber-banded one.
    assert get_difficulty("hard").racing_skill == 1.00
    assert get_difficulty("easy").aggression < get_difficulty("hard").aggression
    assert get_difficulty("easy").rubber_banding is True
    assert get_difficulty("medium").rubber_banding is False
    assert set(DIFFICULTIES) == {"easy", "medium", "hard"}


def test_difficulty_unknown_falls_back_to_medium():
    assert get_difficulty("nonexistent").name == "Medium"


def test_skill_and_aggression_ordering():
    e, m, h = get_difficulty("easy"), get_difficulty("medium"), get_difficulty("hard")
    # Aggression rises easy → hard; only easy rubber-bands.
    assert e.aggression < m.aggression < h.aggression
    assert e.rubber_banding is True
    assert m.rubber_banding is False and h.rubber_banding is False
    # Skill/line-deviation are uniform across the current presets.
    assert e.racing_skill == m.racing_skill == h.racing_skill == 1.0
    assert e.line_deviation == m.line_deviation == h.line_deviation


# ---------------------------------------------------------------------------
# Angle helper
# ---------------------------------------------------------------------------


def test_normalize_angle_wraps():
    # 3*pi wraps to the +/-pi boundary (sign depends on float rounding).
    assert math.isclose(abs(normalize_angle(3 * math.pi)), math.pi, abs_tol=1e-6)
    assert math.isclose(abs(normalize_angle(-3 * math.pi)), math.pi, abs_tol=1e-6)
    assert math.isclose(normalize_angle(0.5), 0.5, abs_tol=1e-9)
    assert math.isclose(normalize_angle(2 * math.pi + 0.3), 0.3, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# Look-ahead / waypoint advance
# ---------------------------------------------------------------------------


def test_initial_target_projects_onto_nearest():
    track = _straight_track()
    veh = FakeVehicle(pos=(0.0, 0.0))
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    # Car sits on waypoint 0 → its track projection is index 0.
    assert ctrl.target_wp_index == 0


def test_advance_waypoint_tracks_forward_progress():
    track = _straight_track(spacing=50.0)
    veh = FakeVehicle(pos=(0.0, 0.0))
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    # Car drives forward to x≈205 (nearest waypoint index 4); projection follows.
    veh.physics.body.position = _Vec(205.0, 30.0)
    ctrl._advance_waypoint((205.0, 30.0))
    assert ctrl.target_wp_index == 4


def test_look_ahead_returns_point_at_least_lookahead_away():
    track = _straight_track(spacing=50.0)
    veh = FakeVehicle(pos=(0.0, 0.0))
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    # _walk covers at least the requested distance (within one spacing).
    idx, pt = ctrl._walk(0, 130.0)
    assert pt[0] >= 130.0 - 50.0


# ---------------------------------------------------------------------------
# Steering sign  (the classic left/right inversion bug)
# ---------------------------------------------------------------------------


def test_steer_left_is_positive():
    # Waypoints curve to the +y side (left in pymunk). Car faces +x.
    track = FakeTrack([(50.0, 0.0), (100.0, 80.0), (150.0, 200.0), (200.0, 360.0)])
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0)
    ctrl = _make_ctrl(veh, track, get_difficulty("hard"))
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert steer > 0.0, f"expected left (positive) steer, got {steer}"


def test_steer_right_is_negative():
    # Waypoints curve to the -y side (right). Car faces +x.
    track = FakeTrack([(50.0, 0.0), (100.0, -80.0), (150.0, -200.0), (200.0, -360.0)])
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0)
    ctrl = _make_ctrl(veh, track, get_difficulty("hard"))
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert steer < 0.0, f"expected right (negative) steer, got {steer}"


def test_steer_output_clamped():
    # Hairpin: the desired steer saturates but the output stays within [-1, 1].
    track = FakeTrack([(0.0, 50.0), (0.0, 150.0), (0.0, 300.0), (0.0, 500.0)])
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(50.0, 0.0))
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert -1.0 <= steer <= 1.0


# ---------------------------------------------------------------------------
# Throttle / brake
# ---------------------------------------------------------------------------


def test_straight_line_full_throttle_no_brake():
    track = _straight_track()
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(40.0, 0.0))
    diff = get_difficulty("hard")
    ctrl = _make_ctrl(veh, track, diff)
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert brake == 0.0
    # Well below the fallback target → throttle saturates to max_throttle.
    assert math.isclose(throttle, diff.max_throttle, abs_tol=1e-9)
    assert abs(steer) < 0.2   # near-straight


def test_sharp_corner_triggers_brake():
    # A racing line whose corner speed is far below the current speed → brake.
    track = _straight_track(spacing=50.0)
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(120.0, 0.0))
    ctrl = AIController(veh, track, get_difficulty("medium"))
    pts = [wp.pos for wp in track.waypoints]
    ctrl.racing_line = _LineStub(pts, [20.0] * len(pts))
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert brake > 0.0, f"low corner speed should brake, got brake={brake}"


def test_slow_in_open_space_drives_forward_not_reverse():
    # Standing start with nothing blocking → power forward (not stuck yet).
    track = _straight_track()
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(0.0, 0.0))
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    throttle, brake, steer = ctrl.compute_inputs(1 / 60.0)
    assert throttle > 0.0 and brake == 0.0, f"open-space start should drive, got {throttle}/{brake}"


def test_wedged_against_wall_enters_reverse_recovery():
    # Full throttle but never moving (v≈0) → stuck timer trips reverse recovery,
    # which drives the brake as a reverse gear (brake=1, throttle=0).
    track = _straight_track()
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(0.0, 0.0))
    veh.is_touching_wall = True
    ctrl = _make_ctrl(veh, track, get_difficulty("medium"))
    out = (0.0, 0.0, 0.0)
    for _ in range(140):  # >2s stuck → recovery active
        out = ctrl.compute_inputs(1 / 60.0)
    throttle, brake, steer = out
    assert ctrl.dbg_state == "reverse"
    assert brake == 1.0 and throttle == 0.0


# ---------------------------------------------------------------------------
# Racing-line following
# ---------------------------------------------------------------------------


def test_racing_line_points_override_look_target():
    # With a racing line loaded, the steering target follows its .points, not
    # the raw centerline.
    track = _straight_track(spacing=50.0)     # centerline y = 0
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0)
    ctrl = AIController(veh, track, get_difficulty("medium"))
    pts = [(wp.pos[0], wp.pos[1] + 40.0) for wp in track.waypoints]
    ctrl.racing_line = _LineStub(pts, [100.0] * len(pts))
    ctrl.compute_inputs(1 / 60.0)
    assert ctrl.dbg_look[1] > 20.0, f"look target ignored racing line: {ctrl.dbg_look}"


def test_racing_line_speed_sets_target():
    # The racing line's speed_at drives the proportional controller's target.
    track = _straight_track(spacing=50.0)
    pts = [wp.pos for wp in track.waypoints]
    # Slow line + fast car → brake.
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(150.0, 0.0))
    ctrl = AIController(veh, track, get_difficulty("medium"))
    ctrl.racing_line = _LineStub(pts, [30.0] * len(pts))
    _, brake, _ = ctrl.compute_inputs(1 / 60.0)
    assert brake > 0.0
    # Fast line + slow car → throttle.
    veh2 = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(10.0, 0.0))
    ctrl2 = AIController(veh2, track, get_difficulty("medium"))
    ctrl2.racing_line = _LineStub(pts, [220.0] * len(pts))
    thr, _, _ = ctrl2.compute_inputs(1 / 60.0)
    assert thr > 0.0


def test_ai_controller_proportional_speed_control():
    track = FakeTrack([(0.0, 50.0), (0.0, 150.0)])
    pts = [wp.pos for wp in track.waypoints]
    # Slower than target speed → throttle, no brake.
    veh = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(10.0, 0.0))
    ctrl = AIController(veh, track, get_difficulty("hard"))
    ctrl.racing_line = _LineStub(pts, [100.0, 100.0])
    throttle, brake, _ = ctrl.compute_inputs(0.016)
    assert throttle > 0.45
    assert brake == 0.0

    # Faster than target speed → brake, no throttle.
    veh_fast = FakeVehicle(pos=(0.0, 0.0), angle=0.0, vel=(150.0, 0.0))
    ctrl_fast = AIController(veh_fast, track, get_difficulty("hard"))
    ctrl_fast.racing_line = _LineStub(pts, [100.0, 100.0])
    throttle_fast, brake_fast, _ = ctrl_fast.compute_inputs(0.016)
    assert throttle_fast == 0.0
    assert brake_fast > 0.0


# ---------------------------------------------------------------------------
# Speed profile & solver (pure geometry, no controller)
# ---------------------------------------------------------------------------


def test_speed_profile_slows_for_corners_and_respects_braking():
    import math as _m
    from src.ai.racing_line_solver import compute_racing_line
    from src.ai.speed_profile import VehicleLimits, compute_speed_profile
    # Loop with one tight pinch so the profile must brake somewhere.
    n = 200
    center = []
    for i in range(n):
        a = 2 * _m.pi * i / n
        r = 340 + 190 * _m.sin(3 * a)   # sharp tri-lobe → tight apexes
        center.append((r * _m.cos(a), r * _m.sin(a)))
    geo = compute_racing_line(center, track_width=180, car_width=28, margin=16)
    lim = VehicleLimits(a_lat=300.0, a_accel=30.0, a_brake=50.0, v_max=260.0, turn_speed=2.2)
    v = compute_speed_profile(geo, lim)
    assert len(v) == n
    assert all(0.0 < s <= lim.v_max + 1e-6 for s in v)
    assert min(v) < lim.v_max - 1.0                     # a corner actually limits speed
    # No segment decelerates harder than the brake limit allows.
    for i in range(n):
        j = (i + 1) % n
        ds = geo.seg_len[i]
        if v[j] < v[i] and ds > 1e-6:
            decel = (v[i] ** 2 - v[j] ** 2) / (2.0 * ds)
            assert decel <= lim.a_brake + 1.0


def test_solver_line_is_shorter_and_in_corridor():
    import math as _m
    from src.ai.racing_line_solver import compute_racing_line
    # A wavy closed loop so the racing line has something to optimise.
    n = 120
    center = []
    for i in range(n):
        a = 2 * _m.pi * i / n
        r = 500 + 120 * _m.sin(3 * a)
        center.append((r * _m.cos(a), r * _m.sin(a)))
    geo = compute_racing_line(center, track_width=200, car_width=28, margin=16)
    clen = sum(_m.dist(center[i], center[(i + 1) % n]) for i in range(n))
    assert geo.length < clen                                   # cuts corners
    assert max(abs(o) for o in geo.offsets) <= geo.half_corridor + 1e-6
    assert all(_m.isfinite(p[0]) and _m.isfinite(p[1]) for p in geo.points)


def test_ai_bypasses_stationary_car_at_start():
    pts = [(i * 20.0, 0.0) for i in range(30)]
    tr = FakeTrack(pts)
    ai_veh = FakeVehicle((10.0, 0.0), vel=(0.0, 0.0))
    stat_veh = FakeVehicle((40.0, 0.0), vel=(0.0, 0.0))

    ai = AIController(ai_veh, tr, get_difficulty("Mittel"))
    ai.opponents = [ai_veh, stat_veh]

    th, br, st = ai.compute_inputs(0.016)
    # AI standing at start line behind a stationary opponent must accelerate and steer wide
    assert th > 0.0
    assert br == 0.0



def test_ai_hard_unstick_reposition_fallback():
    pts = [(i * 20.0, 0.0) for i in range(30)]
    tr = FakeTrack(pts)
    ai_veh = FakeVehicle((0.0, 50.0), vel=(0.0, 0.0))
    ai = AIController(ai_veh, tr, get_difficulty("Mittel"))

    # Initial call to initialize progress tracking
    ai.compute_inputs(0.016)

    # Force 3 failed recovery attempts without waypoint progress
    ai._no_progress_timer = 2.0
    ai._recovery_attempts = 2
    ai.compute_inputs(0.016)

    # Hard unstick should trigger, resetting recovery attempts and moving body closer to track
    assert ai._recovery_attempts == 0
    assert ai_veh.physics.body.position.y < 50.0



# ---------------------------------------------------------------------------
# Grid lane hold (start phase)
# ---------------------------------------------------------------------------


def test_ai_grid_lane_hold_keeps_parallel_offset_at_start():
    """Two AIs on opposite grid lanes aim at their own lane, not the centre —
    so they pull away in parallel instead of converging into each other."""
    track = _straight_track(60, 50.0)
    diff = get_difficulty("medium")

    left = FakeVehicle((0.0, 40.0), angle=0.0, vel=(0.0, 0.0))    # left lane (+y)
    right = FakeVehicle((0.0, -40.0), angle=0.0, vel=(0.0, 0.0))  # right lane (-y)
    cl = _make_ctrl(left, track, diff); cl.opponents = []
    cr = _make_ctrl(right, track, diff); cr.opponents = []

    cl.compute_inputs(1 / 60)
    cr.compute_inputs(1 / 60)

    # Each measured its own lane offset (opposite signs).
    assert cl._start_offset > 10.0
    assert cr._start_offset < -10.0
    # And aims into that lane — the two targets diverge, not merge at y=0.
    assert cl.dbg_look[1] > 20.0
    assert cr.dbg_look[1] < -20.0


def test_ai_grid_lane_hold_skips_a_moving_takeover():
    """A car that starts already moving (mid-race AI takeover) must not snap to
    a lane."""
    from src.ai.ai_controller import GRID_START_SPEED
    track = _straight_track(60, 50.0)
    veh = FakeVehicle((0.0, 40.0), angle=0.0, vel=(GRID_START_SPEED + 50.0, 0.0))
    c = _make_ctrl(veh, track, get_difficulty("medium")); c.opponents = []
    c.compute_inputs(1 / 60)
    assert c._start_timer <= 0.0
    assert c._start_offset == 0.0


def test_ai_start_phase_transitions_smoothly_to_racing_line():
    """After the hold+fade window the offset is gone and the AI aims back at the
    line (centre, y≈0 on this track)."""
    from src.ai.ai_controller import GRID_HOLD_SECONDS, GRID_FADE_SECONDS
    track = _straight_track(400, 50.0)
    veh = FakeVehicle((0.0, 40.0), angle=0.0, vel=(0.0, 0.0))
    c = _make_ctrl(veh, track, get_difficulty("medium")); c.opponents = []

    dt = 1 / 60
    c.compute_inputs(dt)                 # first frame measures the lane offset
    assert abs(c.dbg_look[1]) > 20.0     # held at first

    # Drive forward down the lane so the stuck-recovery never triggers.
    t, x = 0.0, 0.0
    total = GRID_HOLD_SECONDS + GRID_FADE_SECONDS + 0.5
    while t < total:
        x += 300.0 * dt
        veh.physics.body.position = (x, 40.0)
        veh.physics.body.velocity = _Vec(300.0, 0.0)
        c.compute_inputs(dt)
        t += dt

    assert c._start_timer <= 0.0
    # Offset faded out: the target is back near the line, not the +40 lane.
    assert abs(c.dbg_look[1]) < 10.0


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
