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

# Lenkanschlag wie in PhysicsBody.apply_steering: 35 Grad, mit dem Tempo kleiner,
# ``35 deg / (1 + (v/LOCK_REF)^LOCK_EXP)``. Mit dem Radstand ergibt das den engsten
# fahrbaren Radius (kinematisch: tan(delta) = Radstand * Kruemmung). Fruehere
# Fassung rechnete mit der Giergeschwindigkeit ``turn_speed`` aus
# ``Steering.compute_steer`` — die setzt die Physik gar nicht mehr ein, das Profil
# bremste enge Kehren dadurch ohne Grund aus.
_LOCK_REF: float = 500.0
_LOCK_EXP: float = 1.2
_LOCK_GRAD: float = 35.0
# Anteil des Anschlags, den die Bahnfuehrung nutzen darf (Reserve zum Nachlenken).
_TURN_SAFETY: float = 0.9


@dataclass
class VehicleLimits:
    """Acceleration + steering envelope of one vehicle, in game (pixel) units."""

    a_lat: float       # max lateral acceleration before sliding (px/s²)
    a_accel: float     # max forward acceleration (px/s²)
    a_brake: float     # max braking deceleration (px/s²)
    v_max: float       # top speed (px/s)
    turn_speed: float  # (alt, nicht mehr im Profil) Giergeschwindigkeit bei Stillstand
    turn_safety: float = _TURN_SAFETY  # fraction of steering lock used for planning
    radstand: float = 33.0  # Radstand in px (engster Radius = Radstand / tan(Anschlag))
    #: Vollgas-Beschleunigung (px/s²) auf einem Tempogitter ``a_tab_dv`` px/s
    #: Abstand, aus Motor, Getriebe, Traktion und Widerstaenden (siehe
    #: ``beschleunigungstabelle``). ``None``: konstant ``a_accel``.
    a_tab: tuple[float, ...] | None = None
    a_tab_dv: float = 10.0

    def beschleunigung(self, v: float) -> float:
        """Mögliche Beschleunigung (px/s²) bei Tempo ``v`` (px/s)."""
        if not self.a_tab:
            return self.a_accel
        x = max(0.0, v) / self.a_tab_dv
        i = int(x)
        if i >= len(self.a_tab) - 1:
            return self.a_tab[-1]
        u = x - i
        return self.a_tab[i] * (1.0 - u) + self.a_tab[i + 1] * u


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
    radstand = float(getattr(config, "wheelbase_m", 0.0) or 0.0) / M_PER_PX or 33.0
    lim = VehicleLimits(a_lat, a_accel, a_brake, v_max, turn_speed, _steer_conf, radstand)
    tab = beschleunigungstabelle(config, lim.a_tab_dv)
    if tab:
        lim.a_tab = tab
        lim.a_accel = tab[0]
    return lim


def beschleunigungstabelle(config, dv: float = 10.0) -> tuple[float, ...] | None:
    """Vollgas-Beschleunigung (px/s²) je Tempo ``k * dv`` px/s, wie die Physik sie liefert.

    Antriebskraft aus dem Motor (Drehmomentkurve, bester Gang, Drehzahlgrenzen
    wie ``Engine.compute_force``), begrenzt durch die Traktion der angetriebenen
    Achse (Haftung × Achslast inkl. Gewichtsverlagerung wie in
    ``PhysicsBody.apply_drive_force``), abzüglich Luft- und Rollwiderstand.
    ``engine_power`` ist *keine* Kraft: es wirkte in der alten Annahme
    ``Leistung / Masse`` rund viermal zu stark (rookie: 220 statt 53 px/s²).
    Ohne brauchbare Motordaten ``None``.
    """
    from src.core.settings import M_PER_PX
    try:
        from src.entities.components.engine import Engine
        motor = Engine(
            max_power=float(config.engine_power), max_speed=float(config.max_speed),
            gear_ratios=getattr(config, "gear_ratios", None),
            idle_rpm=float(getattr(config, "idle_rpm", 1000.0)),
            redline_rpm=float(getattr(config, "redline_rpm", 6000.0)),
            torque_curve=getattr(config, "torque_curve", None),
            wheel_diameter=float(getattr(config, "wheel_diameter", 0.65)),
        )
        masse = float(config.mass)
        grip = float(config.grip)
        cw = float(getattr(config, "drag_coefficient", 0.3))
        flaeche = float(getattr(config, "frontal_area", 2.2))
        roll = float(getattr(config, "roll_coefficient", 0.011))
        antrieb = str(getattr(config, "drive_type", "rwd")).lower()
        vorn = max(0.35, min(0.65, 0.5 + float(getattr(config, "com_bias", 0.0))))
        v_top = float(config.max_speed)
    except Exception:
        return None
    if masse <= 0.0 or v_top <= 0.0:
        return None
    werte: list[float] = []
    for k in range(int(v_top / dv) + 2):
        v = k * dv
        kraft = 0.0
        for g, uebersetzung in enumerate(motor.gear_ratios):
            gang_top = motor.gears_max_speeds[g]
            f = motor._wheel_force(g, v) * max(0.0, 1.0 - (v / gang_top) ** 12)
            kraft = max(kraft, f)
        kraft *= max(0.0, 1.0 - (v / v_top) ** 10)
        widerstand = (0.5 * 1.2 * cw * flaeche * (v * M_PER_PX) ** 2
                      + roll * masse * 9.81) if v > 0.5 else 0.0
        a = kraft / masse / M_PER_PX
        for _ in range(4):      # Gewichtsverlagerung hängt von a selbst ab
            wt = min(0.35, a * 0.0012)
            v_last = max(0.1, min(0.9, vorn - wt))
            h_last = max(0.1, min(0.9, (1.0 - vorn) + wt))
            if antrieb == "fwd":
                traktion = grip * v_last * masse * 9.81
                f_antrieb = min(kraft, traktion)
            elif antrieb == "awd":
                f_antrieb = (min(kraft * 0.5, grip * v_last * masse * 9.81)
                             + min(kraft * 0.5, grip * h_last * masse * 9.81))
            else:
                f_antrieb = min(kraft, grip * h_last * masse * 9.81)
            a = max(0.0, f_antrieb - widerstand) / masse / M_PER_PX
        werte.append(a)
    return tuple(max(1.0, w) for w in werte)


def _corner_speed(curvature: float, limits: VehicleLimits, eps: float = 1e-6) -> float:
    """Max speed for a corner of *curvature*, limited by BOTH grip and steering.

    Radius-based speed calculation (physically correct):
    With Radius R = 1 / curvature, the grip limit is:
        v = sqrt(a_lat * R)
    This directly ensures:
    - Tighter curves (smaller R) -> lower safe speed.
    - Wider curves (larger R) -> higher safe speed.

    Grip limit:     v = sqrt(a_lat / kappa).
    Steering limit: kinematic, tan(delta) = wheelbase * curvature, with the lock
                    angle of PhysicsBody.apply_steering (35 degrees, falling with
                    speed). The largest v with that lock sufficient is found by
                    bisection (the lock shrinks with v).
    """
    if curvature <= eps:
        return limits.v_max
    v_grip = math.sqrt(limits.a_lat / curvature)
    noetig = curvature * limits.radstand      # tan(delta)

    def steer_ok(v: float) -> bool:
        lock = math.radians(_LOCK_GRAD) / (1.0 + (v / _LOCK_REF) ** _LOCK_EXP)
        return noetig <= math.tan(lock * limits.turn_safety)

    hi = limits.v_max
    if steer_ok(hi):
        v_steer = hi
    elif not steer_ok(0.0):
        v_steer = 0.0           # enger als der Anschlag je erlaubt
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
    antrieb_begrenzt: bool = True,
) -> list[float]:
    """Return the max safe speed (px/s) at each racing-line point.

    ``antrieb_begrenzt=False`` lässt den Vorwärtsdurchgang weg: das Profil ist dann
    nur noch die Obergrenze aus Kurven und Bremsen. Für einen Regler, der das
    Profil als Sollwert nimmt, ist das richtig — mehr als der Motor liefert, kann
    das Gas ohnehin nicht geben, und eine Tempoobergrenze *unter* dem, was das
    Auto real schafft (Kurvenschneiden, Windschatten, Modellfehler von ein paar
    Prozent), bremst es ohne Grund (mountain +1,3 s, gp +0,35 s).
    """
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
        for i in (range(n) if antrieb_begrenzt else ()):
            j = (i + 1) % n
            cap = math.sqrt(v[i] * v[i] + 2.0 * limits.beschleunigung(v[i]) * seg[i])
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
