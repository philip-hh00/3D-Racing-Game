"""Physics-based speed profile for a racing line.

Given a solved :class:`~src.ai.racing_line_solver.RacingLineGeometry` and a
vehicle's acceleration limits, compute the maximum safe speed at every point of
the line. This is the classic forward–backward "velocity profile" algorithm and,
like the line solver, it is deterministic, runs in a few milliseconds at load
and works on any track:

    1. Per point, the cornering limit from the friction circle:
       ``v = sqrt(a_lat / curvature)`` (a straight → unlimited → capped at v_max).
    2. A backward pass enforces braking: you can only enter a point fast enough
       that you can still slow to the next point's limit in the gap between them.
    3. A forward pass enforces engine power: you can only leave a point as fast
       as you could accelerate to from the previous one.

Because the track is a closed loop, the two passes are repeated a few times so
the start/finish coupling settles.

The per-vehicle limits come straight from each car's config (force/mass, grip),
so every car gets its own profile with no training. ``LAT_GRIP_SCALE`` maps the
config's 0–1 grip coefficient to a lateral acceleration in the game's physics
units; it is the single global constant to calibrate against real driving.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Maps config.grip (0–1) to max lateral acceleration in px/s². This is NOT a
# guess: the physics caps lateral grip at `grip * half_mass * 380 * dt` per axle
# (GRIP_SCALE = 380 in PhysicsBody.apply_lateral_friction), which works out to a
# sustainable lateral acceleration of exactly `grip * 380`. SAFETY keeps the
# target just inside that limit so the car corners at the edge of grip without
# tipping over it into a slide.
LAT_GRIP_SCALE: float = 380.0

# Default safety margins (used when no difficulty overrides are given).
LAT_SAFETY: float = 0.70   # corner just inside the grip limit (margin vs sliding)
BRAKE_SAFETY: float = 0.88

# Steering-lock curve mirrored from Steering.compute_steer: the achievable yaw
# rate is turn_speed / (1 + (v/LOCK_REF)^LOCK_EXP). This caps how tight a corner
# the car can physically take at a given speed – often *more* restrictive than
# grip in slow hairpins, which is why it must be in the speed profile.
_LOCK_REF: float = 500.0
_LOCK_EXP: float = 1.2
# The controller can't perfectly realise the theoretical max yaw, so plan tight
# corners against a fraction of it – the difference is what made the fastest car
# run wide in the tightest hairpin.
_TURN_SAFETY: float = 0.65


@dataclass
class VehicleLimits:
    """Acceleration + steering envelope of one vehicle, in game (pixel) units."""

    a_lat: float       # max lateral acceleration before sliding (px/s²)
    a_accel: float     # max forward acceleration (px/s²)
    a_brake: float     # max braking deceleration (px/s²)
    v_max: float       # top speed (px/s)
    turn_speed: float  # base yaw rate (rad/s) at zero speed
    turn_safety: float = _TURN_SAFETY  # fraction of steering lock used for planning


def limits_from_config(
    config,
    lat_grip_scale: float = LAT_GRIP_SCALE,
    grip_usage: float | None = None,
    brake_confidence: float | None = None,
    steer_confidence: float | None = None,
) -> VehicleLimits:
    """Derive a :class:`VehicleLimits` from a vehicle's config (no measurement).

    Forward/braking limits are force/mass; the lateral limit scales the grip
    coefficient; turn_speed feeds the steering-lock corner limit. Per-car
    differences carry straight through, so each car gets a distinct profile.

    The optional ``grip_usage``, ``brake_confidence`` and ``steer_confidence``
    parameters override the module-level safety margins, allowing the AI Lab
    to tune them live.
    """
    from src.core.settings import M_PER_PX
    _grip_usage = grip_usage if grip_usage is not None else LAT_SAFETY
    _brake_conf = brake_confidence if brake_confidence is not None else BRAKE_SAFETY
    _steer_conf = steer_confidence if steer_confidence is not None else _TURN_SAFETY

    mass = max(1.0, getattr(config, "mass", 950.0))
    a_accel = (getattr(config, "engine_power", 35000.0) / mass) / M_PER_PX
    a_brake = (getattr(config, "brake_force", 45000.0) / mass * _brake_conf) / M_PER_PX
    a_lat = lat_grip_scale * _grip_usage * getattr(config, "grip", 0.8)
    v_max = getattr(config, "max_speed", 260.0)
    turn_speed = getattr(config, "turn_speed", 2.2)
    return VehicleLimits(a_lat, a_accel, a_brake, v_max, turn_speed, _steer_conf)


def _corner_speed(curvature: float, limits: VehicleLimits, eps: float = 1e-6) -> float:
    """Max speed for a corner of *curvature*, limited by BOTH grip and steering.

    Radius-based speed calculation (physically correct):
    With Radius R = 1 / curvature, the grip limit is:
        v = sqrt(a_lat * R)
    This directly ensures:
    - Tighter curves (smaller R) -> lower safe speed.
    - Wider curves (larger R) -> higher safe speed.

    Grip limit:     v = sqrt(a_lat / kappa).
    Steering limit: the car must yaw at v*kappa rad/s, but the lock curve caps
                    the yaw at turn_speed/(1+(v/LOCK_REF)^LOCK_EXP). The largest
                    v satisfying v*kappa*(1+(v/LOCK_REF)^LOCK_EXP) <= turn_speed
                    is found by bisection (the left side rises with v).
    """
    if curvature <= eps:
        return limits.v_max
    v_grip = math.sqrt(limits.a_lat / curvature)

    max_yaw = limits.turn_speed * limits.turn_safety

    def steer_ok(v: float) -> bool:
        return v * curvature * (1.0 + (v / _LOCK_REF) ** _LOCK_EXP) <= max_yaw

    hi = limits.v_max
    if steer_ok(hi):
        v_steer = hi
    else:
        lo = 0.0
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            if steer_ok(mid):
                lo = mid
            else:
                hi = mid
        v_steer = lo
    return min(limits.v_max, v_grip, v_steer)


def compute_speed_profile(
    geometry,
    limits: VehicleLimits,
    passes: int = 3,
    eps: float = 1e-6,
) -> list[float]:
    """Return the max safe speed (px/s) at each racing-line point."""
    curv = geometry.curvature
    seg = geometry.seg_len
    n = len(curv)
    if n == 0:
        return []

    # 1. Cornering limit per point (grip AND steering-lock).
    v = [_corner_speed(c, limits, eps) for c in curv]

    for _ in range(passes):
        # 2. Backward braking pass: v[i] limited by the next point + braking.
        for k in range(n):
            i = (n - 1 - k) % n
            j = (i + 1) % n
            cap = math.sqrt(v[j] * v[j] + 2.0 * limits.a_brake * seg[i])
            if v[i] > cap:
                v[i] = cap
        # 3. Forward acceleration pass: v[j] limited by the previous + engine.
        for i in range(n):
            j = (i + 1) % n
            cap = math.sqrt(v[i] * v[i] + 2.0 * limits.a_accel * seg[i])
            if v[j] > cap:
                v[j] = cap

    # 4. Smooth the profile to take the edge off local curvature noise/spikes
    window = 5
    half = window // 2
    smoothed = [0.0] * n
    for i in range(n):
        chunk = [v[(i + offset) % n] for offset in range(-half, half + 1)]
        smoothed[i] = sum(chunk) / window

    # 5. Re-enforce braking after smoothing (smoothing can violate brake limits)
    for _ in range(2):
        for k in range(n):
            i = (n - 1 - k) % n
            j = (i + 1) % n
            cap = math.sqrt(smoothed[j] * smoothed[j] + 2.0 * limits.a_brake * seg[i])
            if smoothed[i] > cap:
                smoothed[i] = cap
    return smoothed
