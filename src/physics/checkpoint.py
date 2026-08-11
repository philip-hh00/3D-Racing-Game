"""Checkpoint class – creates a static sensor shape in pymunk for tracking vehicle laps/splits."""
from __future__ import annotations

import math
import pymunk

from src.core.settings import CHECKPOINT_COLLISION_TYPE


class Checkpoint:
    """A checkpoint line segment that acts as a sensor shape in pymunk physics.

    Spans perpendicular to the track direction across the road.
    """

    def __init__(
        self,
        idx: int,
        x: float,
        y: float,
        angle_deg: float,
        track_width: float,
        space: pymunk.Space,
    ) -> None:
        """Create a checkpoint sensor segment.

        Args:
            idx:         Sequence index of the checkpoint (0 = start/finish).
            x, y:        Center point coordinate of the checkpoint.
            angle_deg:   Direction angle of the centerline in degrees.
            track_width: Width of the track in pixels.
            space:       The pymunk Space to add the sensor shape to.
        """
        self.idx: int = idx
        self.x: float = x
        self.y: float = y
        self.angle_deg: float = angle_deg

        # Perpendicular normal vector (rotated 90 degrees from driving direction)
        rad_perp = math.radians(angle_deg + 90.0)
        nx = math.cos(rad_perp)
        ny = math.sin(rad_perp)

        # Extend slightly past track width (+20 px buffer) to prevent squeeze-throughs at borders
        half_w = (track_width / 2.0) + 20.0

        a = (x + nx * half_w, y + ny * half_w)
        b = (x - nx * half_w, y - ny * half_w)

        # Create static sensor shape
        self.shape = pymunk.Segment(space.static_body, a, b, radius=5.0)
        self.shape.sensor = True
        self.shape.collision_type = CHECKPOINT_COLLISION_TYPE
        self.shape.data = idx

        self._space: pymunk.Space = space
        space.add(self.shape)

    def cleanup(self) -> None:
        """Remove the checkpoint shape from the physics space."""
        if self.shape in self._space.shapes:
            self._space.remove(self.shape)
