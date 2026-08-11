"""Utility functions for coordinate conversion, interpolation, and angle math."""
from __future__ import annotations

import math

import pymunk


def to_pygame(pos: tuple[float, float], height: int = 1080) -> tuple[int, int]:
    """Convert pymunk coordinates (y-up) to pygame coordinates (y-down).

    Args:
        pos: Position in pymunk coordinate space.
        height: The screen or surface height for y-axis flip.

    Returns:
        Integer pixel coordinates in pygame space.
    """
    return int(pos[0]), int(height - pos[1])


def to_pymunk(pos: tuple[float, float], height: int = 1080) -> tuple[float, float]:
    """Convert pygame coordinates (y-down) to pymunk coordinates (y-up).

    Args:
        pos: Position in pygame coordinate space.
        height: The screen or surface height for y-axis flip.

    Returns:
        Coordinates in pymunk space.
    """
    return float(pos[0]), float(height - pos[1])


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between two values.

    Args:
        a: Start value.
        b: End value.
        t: Interpolation factor (0.0 = a, 1.0 = b). Not clamped.

    Returns:
        The interpolated value.
    """
    return a + (b - a) * t


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max.

    Args:
        value: The value to clamp.
        min_val: Minimum bound.
        max_val: Maximum bound.

    Returns:
        The clamped value.
    """
    return max(min_val, min(max_val, value))


def angle_diff(a: float, b: float) -> float:
    """Compute the shortest signed angle difference between two angles in radians.

    Args:
        a: First angle in radians.
        b: Second angle in radians.

    Returns:
        The shortest angle from a to b, in range [-pi, pi].
    """
    diff = (b - a) % (2.0 * math.pi)
    if diff > math.pi:
        diff -= 2.0 * math.pi
    return diff


def vec2d_to_tuple(v: pymunk.Vec2d) -> tuple[float, float]:
    """Convert a pymunk Vec2d to a plain Python tuple.

    Args:
        v: A pymunk 2D vector.

    Returns:
        A (x, y) tuple of floats.
    """
    return (v.x, v.y)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Euclidean distance between two 2D points.

    Args:
        a: First point (x, y).
        b: Second point (x, y).

    Returns:
        The distance as a float.
    """
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    return math.sqrt(dx * dx + dy * dy)


def normalize_angle(angle: float) -> float:
    """Normalize an angle to the range [-pi, pi].

    Args:
        angle: Angle in radians.

    Returns:
        Normalized angle in [-pi, pi].
    """
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle
