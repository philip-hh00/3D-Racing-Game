"""Engine component – RPM-based combustion engine torque curve and automatic gearbox."""
from __future__ import annotations

import math

from src.core.settings import KMH_PER_PXS

#: Wie schnell rueckwaerts gefahren werden darf, **in km/h**.
#:
#: Die Zahl stand hier einmal als ``max_reverse_speed = 30.0`` mitten im
#: Rechenweg, mit dem Kommentar „Limited to ca. 30 km/h" — verglichen wurde sie
#: aber mit ``current_speed``, und das steht in px/s. 30 px/s sind 8,6 km/h, und
#: weil die Kraft zur Grenze hin auf null faellt, war bei etwa 5 km/h Schluss
#: (gemeldet 05.08.2026). Deshalb steht die Einheit jetzt im Namen und die
#: Umrechnung an genau einer Stelle.
MAX_REVERSE_SPEED_KMH = 30.0


class Engine:
    """Simulates a multi-gear combustion engine with a parabolic torque curve.

    Includes automatic transmission that shifts gears based on engine RPM.
    """

    def __init__(
        self,
        max_power: float,
        max_speed: float,
        gear_ratios: list[float] | None = None,
        gears_max_speeds_ratios: list[float] | None = None,
        idle_rpm: float = 1000.0,
        redline_rpm: float = 6000.0,
        shift_up_rpm: float = 5100.0,
        torque_curve: list[list[float]] | None = None,
        wheel_diameter: float = 0.65,
    ) -> None:
        """
        Args:
            max_power: Reference maximum engine force scaling factor (Newtons).
            max_speed: Reference top speed in px/s.
            gear_ratios: Custom list of gear ratios.
            gears_max_speeds_ratios: (Obsolete, kept for backwards compat)
            idle_rpm: Engine idle RPM.
            redline_rpm: Engine maximum RPM.
            shift_up_rpm: RPM at which the gearbox shifts up.
            wheel_diameter: Wheel diameter in meters.
        """
        self.max_power = max_power
        self.max_speed = max_speed
        self.wheel_diameter = wheel_diameter
        #: Ruecklaufgrenze in px/s — derselben Einheit wie ``current_speed``.
        self.max_reverse_speed_pxs = MAX_REVERSE_SPEED_KMH / KMH_PER_PXS

        # Gearbox setup: configured dynamically from JSON or defaults to standard 5-speed
        self.gear_ratios = gear_ratios or [3.5, 2.0, 1.5, 1.2, 1.0]

        # Calculate gear max speeds physically from ratios and wheel diameter
        # max_speed_pxs = (redline_rpm * pi * d) / (60 * i_ges * 0.08)
        self.gears_max_speeds = []
        import math
        circumference = math.pi * self.wheel_diameter
        for r in self.gear_ratios:
            max_speed_pxs = (redline_rpm * circumference) / (60.0 * r * 0.08)
            self.gears_max_speeds.append(max_speed_pxs)

        # Engine RPM configuration
        self.idle_rpm: float = idle_rpm
        self.redline_rpm: float = redline_rpm
        
        # Optional custom torque curve as sorted (rpm, Nm) points.
        # When present, the actual Nm values are used directly for force
        # calculation (not normalised).
        self.torque_curve: list[tuple[float, float]] | None = None
        self._torque_peak: float = 1.0
        if torque_curve:
            pts = sorted((float(r), float(nm)) for r, nm in torque_curve)
            if pts:
                self.torque_curve = pts
                self._torque_peak = max((nm for _r, nm in pts), default=1.0) or 1.0

        # Calculate engine peak torque in Nm
        if self.torque_curve:
            # Derive peak_torque directly from the custom curve's max Nm
            self.peak_torque = self._torque_peak
        else:
            # Derive from engine power: T = P / omega_peak
            if len(self.gear_ratios) == 1:  # electric
                peak_rpm_calc = idle_rpm + (redline_rpm - idle_rpm) * 0.4
            else:
                peak_rpm_calc = idle_rpm + (redline_rpm - idle_rpm) * 0.75
            omega_peak = max(100.0, peak_rpm_calc * 2.0 * math.pi / 60.0)
            power_watts = max_power * 7.355  # Convert PS-referenced scale to physical Watts
            self.peak_torque = power_watts / omega_peak

        # Shift down at ~40% of the RPM band
        self.shift_down_rpm: float = self.idle_rpm + (self.redline_rpm - self.idle_rpm) * 0.40

        # Live state
        self.current_gear: int = 1  # 1-indexed (1 to 5)
        self.current_rpm: float = self.idle_rpm
        self.shift_cooldown: float = 0.0  # seconds to prevent rapid gear hunting

    def _interp_torque(self, rpm: float) -> float:
        """Linear-interpolate the custom torque table (Nm) at *rpm*."""
        pts = self.torque_curve
        if not pts:
            return 0.0
        if rpm <= pts[0][0]:
            return pts[0][1]
        if rpm >= pts[-1][0]:
            return pts[-1][1]
        for i in range(len(pts) - 1):
            r0, n0 = pts[i]
            r1, n1 = pts[i + 1]
            if r0 <= rpm <= r1:
                t = (rpm - r0) / (r1 - r0) if r1 > r0 else 0.0
                return n0 + (n1 - n0) * t
        return pts[-1][1]

    # ------------------------------------------------------------------
    # Gearbox helpers (crossing-point shifting)
    # ------------------------------------------------------------------

    def _rpm_in_gear(self, gear_idx: int, speed: float) -> float:
        """Engine RPM in *gear_idx* at *speed* (px/s), unclamped."""
        i = self.gear_ratios[gear_idx]
        return (speed * 4.8 * i) / (math.pi * self.wheel_diameter)

    def _torque_nm_at(self, rpm: float) -> float:
        """Engine torque (Nm) at *rpm* – from the custom table or the formula."""
        rpm = max(self.idle_rpm, min(self.redline_rpm, rpm))
        if self.torque_curve is not None:
            return self._interp_torque(rpm)
        if len(self.gear_ratios) == 1:  # electric
            flat = self.idle_rpm + (self.redline_rpm - self.idle_rpm) * 0.4
            f = 1.0 if rpm < flat else 1.0 - 0.65 * ((rpm - flat) / max(1.0, self.redline_rpm - flat))
            return self.peak_torque * f
        peak = self.idle_rpm + (self.redline_rpm - self.idle_rpm) * 0.75
        band = self.redline_rpm - self.idle_rpm
        f = 1.0 - ((rpm - peak) / (band * 0.7)) ** 2
        return self.peak_torque * max(0.45, min(1.0, f))

    def _wheel_force(self, gear_idx: int, speed: float) -> float:
        """Available driving force (N) at the wheels in *gear_idx* at *speed*.

        This is the classic tractive-force curve; comparing gears at the same
        speed gives the natural shift points (shift when a gear pulls harder).
        """
        rpm = self._rpm_in_gear(gear_idx, speed)
        nm = self._torque_nm_at(rpm)
        return nm * self.gear_ratios[gear_idx] * 2.0 / self.wheel_diameter

    def compute_force(self, throttle: float, current_speed: float, dt: float, braking: bool = False) -> float:
        """Calculate drive force.

        Updates gearbox state and engine RPM before computing torque.

        Args:
            throttle: Input throttle from -1.0 (reverse) to 1.0 (forward).
            current_speed: Scalar speed of the vehicle in px/s.
            dt: Frame time delta (used to update shifting cooldown).
            braking: True if the vehicle's brakes are applied.

        Returns:
            Drive force in Newtons.
        """
        # Decrease shifting cooldown
        if self.shift_cooldown > 0.0:
            self.shift_cooldown -= dt

        # Reverse gear handling
        if throttle < 0.0:
            self.current_gear = 1
            max_reverse_speed = self.max_reverse_speed_pxs
            target_rpm = self.idle_rpm + (min(current_speed, max_reverse_speed) / max_reverse_speed) * (self.redline_rpm - self.idle_rpm)
            self.current_rpm += (target_rpm - self.current_rpm) * 15.0 * dt
            self.current_rpm = min(self.redline_rpm, max(self.idle_rpm, self.current_rpm))

            speed_ratio = max(0.0, 1.0 - current_speed / max_reverse_speed)
            if self.torque_curve is not None:
                torque = self._interp_torque(self.current_rpm) * 0.8 * abs(throttle)
            else:
                torque = self.peak_torque * 0.8 * abs(throttle)
            rev_gear_ratio = self.gear_ratios[0]
            drive_force = (torque * rev_gear_ratio * 2.0 / self.wheel_diameter) * speed_ratio
            return -drive_force

        if throttle == 0.0 and not braking:
            # Coasting: no drive force, but still downshift as speed bleeds off so
            # the car is in the right gear the instant it gets back on the power.
            self.current_gear = max(1, self.current_gear)
            if self.shift_cooldown <= 0.0 and self.current_gear > 1:
                gear_idx = self.current_gear - 1
                i_ges = self.gear_ratios[gear_idx]
                coast_rpm = max(self.idle_rpm, (current_speed * 4.8 * i_ges) / (math.pi * self.wheel_diameter))
                if coast_rpm < self.shift_down_rpm:
                    self.current_gear -= 1
                    self.shift_cooldown = 0.2
            # Drop RPM towards idle with engine inertia
            self.current_rpm += (self.idle_rpm - self.current_rpm) * 5.0 * dt
            self.current_rpm = max(self.idle_rpm, self.current_rpm)
            return 0.0

        # Forward automatic shifting logic (or braking shift logic)
        # 1. Calculate physical engine RPM for current gear and speed
        cur = self.current_gear - 1
        n_gears = len(self.gear_ratios)
        raw_rpm = self._rpm_in_gear(cur, current_speed)
        target_rpm = max(self.idle_rpm, min(self.redline_rpm, raw_rpm))

        # 2. Crossing-point shifting: shift into whichever gear pulls hardest at
        #    this speed. Hysteresis (a gear must be clearly better) stops the box
        #    hunting at the crossover point; a redline guard forces an upshift
        #    before over-revving even if the maths hasn't crossed yet.
        UP_HYST = 1.06     # next gear must give >6% more force to upshift
        DOWN_HYST = 1.10   # lower gear must give >10% more force to downshift
        if self.shift_cooldown <= 0.0 and not braking:
            f_cur = self._wheel_force(cur, current_speed)
            # Upshift?
            over_rev = raw_rpm >= self.redline_rpm * 0.985
            if cur < n_gears - 1:
                rpm_next = self._rpm_in_gear(cur + 1, current_speed)
                pulls_better = self._wheel_force(cur + 1, current_speed) > f_cur * UP_HYST
                if over_rev or (pulls_better and rpm_next > self.idle_rpm * 1.05):
                    self.current_gear += 1
                    self.shift_cooldown = 0.35
            # Downshift? (only if we didn't just upshift)
            if self.current_gear - 1 == cur and cur > 0:
                rpm_prev = self._rpm_in_gear(cur - 1, current_speed)
                if self._wheel_force(cur - 1, current_speed) > f_cur * DOWN_HYST \
                        and rpm_prev < self.redline_rpm * 0.98:
                    self.current_gear -= 1
                    self.shift_cooldown = 0.3
        elif self.shift_cooldown <= 0.0 and braking and self.current_gear > 1:
            # Under braking, rev-match down early for corner exit readiness.
            if target_rpm < self.shift_down_rpm * 1.3:
                self.current_gear -= 1
                self.shift_cooldown = 0.12

        if self.current_gear - 1 != cur:
            target_rpm = max(self.idle_rpm, min(self.redline_rpm,
                                                self._rpm_in_gear(self.current_gear - 1, current_speed)))

        # Interpolate current RPM towards target RPM to simulate engine inertia
        self.current_rpm += (target_rpm - self.current_rpm) * 15.0 * dt
        self.current_rpm = min(self.redline_rpm, max(self.idle_rpm, self.current_rpm))

        # 3. Torque at current RPM (Nm) – custom table or built-in formula.
        torque_nm = self._torque_nm_at(self.current_rpm)

        # 4. Calculate drive force at wheels (in Newtons)
        torque = torque_nm * throttle
        gear_ratio = self.gear_ratios[self.current_gear - 1]
        max_gear_speed = self.gears_max_speeds[self.current_gear - 1]
        
        # Scale down force near the top speed of the active gear to prevent over-revving
        speed_in_gear_ratio = current_speed / max_gear_speed
        speed_factor = max(0.0, 1.0 - (speed_in_gear_ratio ** 12))  # steeper drop-off to allow shifting
        
        # Wheel Force (N) = torque * gear_ratio / wheel_radius
        drive_force = (torque * gear_ratio * 2.0 / self.wheel_diameter) * speed_factor

        # Overall speed limiter to match the user-defined max_speed (stored internally in px/s)
        max_speed_pxs = self.max_speed
        if max_speed_pxs > 0.0:
            speed_ratio_overall = current_speed / max_speed_pxs
            overall_speed_factor = max(0.0, 1.0 - (speed_ratio_overall ** 10))
            drive_force *= overall_speed_factor

        return drive_force

    @property
    def shift_up_rpm(self) -> float:
        """Dynamically return the shift up RPM indicator (e.g. 95% of redline)."""
        return self.redline_rpm * 0.95
