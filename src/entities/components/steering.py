"""Steering component – computes turn angle using a non-linear steering lock curve."""
from __future__ import annotations


class Steering:
    """Calculates steering angle changes with a non-linear speed-dependent lock curve

    to prevent spin-outs and simulate realistic steering limits at high speed.
    """

    def __init__(self, turn_speed: float, drift_threshold: float, grip: float) -> None:
        """
        Args:
            turn_speed: Base turn rate in rad/s.
            drift_threshold: Speed ratio above which grip starts dropping.
            grip: Base grip coefficient.
        """
        self.turn_speed = turn_speed
        self.drift_threshold = drift_threshold
        self.grip = grip

    def compute_steer(
        self, steer_input: float, speed: float, max_speed: float, dt: float
    ) -> float:
        """Calculate the steering angle delta for this frame.

        Steering lock is limited at high speeds to simulate tires understeer
        and keep the vehicle stable.

        Args:
            steer_input: -1.0 (full right) to 1.0 (full left) - Pymunk convention.
            speed: Current vehicle speed in px/s.
            max_speed: Maximum vehicle speed in px/s.
            dt: Delta time in seconds.

        Returns:
            Angle change in radians (already scaled by dt).
        """
        if abs(steer_input) < 0.01 or speed < 2.0:
            return 0.0

        # Steering lock curve: limits turning capacity non-linearly at high speeds.
        # At speed=0: lock_factor=1.0. At speed=500: lock_factor=0.5. At speed=1300: lock_factor ~0.2.
        lock_factor = 1.0 / (1.0 + (speed / 500.0) ** 1.2)

        # Calculate final turning rate
        steer_rate = steer_input * self.turn_speed * lock_factor

        return steer_rate * dt
