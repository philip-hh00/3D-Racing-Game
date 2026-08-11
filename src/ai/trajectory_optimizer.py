"""Per-vehicle trajectory computation — physics-informed geometric solving.

Each vehicle gets its own racing line by running the geometric minimum-curvature
solver with vehicle-specific corridor parameters:

- **margin** adapts to the car's physical size (height, width) and grip level.
  Lower grip → wider margin so the car has room when it slides.
- **corner_pull** adapts to the car's steering lock and confidence.
  Slower steering → less apex-cutting so the car can follow the line.

This avoids the instability of iterative gradient methods (which create lines
the AI controller can't reliably track) while still giving each vehicle a
distinct, physics-informed trajectory.

Runs in ~50-100 ms per vehicle (one geometric solve each).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.ai.racing_line_solver import (
    RacingLineGeometry,
    compute_racing_line,
)


@dataclass
class TrajectoryConfig:
    """Vehicle physics envelope for per-vehicle line computation."""
    a_lat_max: float
    a_accel_max: float
    a_brake_max: float
    v_max: float
    car_width: float
    margin: float
    turn_speed: float = 2.2
    turn_safety: float = 0.65


def optimize_trajectory(
    center: list[tuple[float, float]],
    track_width: float,
    config: TrajectoryConfig,
    max_iterations: int = 600,
    progress_callback=None,
) -> RacingLineGeometry:
    """Compute a vehicle-specific racing line using adapted geometric solving.

    The margin and corner_pull are tuned per-vehicle based on the physics
    envelope so that faster/grippier cars get tighter lines and
    slower/slidier cars get safer lines.
    """
    # Grip-based margin: low grip → extra margin (up to +4px)
    grip_ratio = min(1.0, config.a_lat_max / 270.0)
    grip_margin_bonus = (1.0 - grip_ratio) * 4.0

    # Steering-based corner_pull: slower steering → less apex cutting
    effective_steer = config.turn_speed * config.turn_safety
    steer_ratio = min(1.0, effective_steer / 1.43)
    corner_pull = 0.45 + (1.0 - steer_ratio) * 0.10

    adjusted_margin = config.margin + grip_margin_bonus

    if progress_callback:
        progress_callback(0, 1)

    geo = compute_racing_line(
        center, track_width,
        car_width=config.car_width,
        margin=adjusted_margin,
        iterations=max_iterations,
        corner_pull=corner_pull,
    )

    if progress_callback:
        progress_callback(1, 1)

    return geo
