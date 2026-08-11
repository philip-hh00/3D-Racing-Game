"""Brakes component – computes braking force."""
from __future__ import annotations


class Brakes:
    """Simple brake force calculator."""

    def __init__(self, brake_force: float) -> None:
        """
        Args:
            brake_force: Maximum brake force in Newtons.
        """
        self.brake_force = brake_force

    def compute_force(self, brake_input: float) -> float:
        """Calculate the brake force for this frame.

        Args:
            brake_input: 0.0 (no braking) to 1.0 (full brake).

        Returns:
            Brake force in Newtons.
        """
        return brake_input * self.brake_force
