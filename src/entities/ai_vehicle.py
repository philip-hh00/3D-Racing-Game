"""AI-controlled vehicle – thin Vehicle subclass driven by an AIController."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pymunk

from src.entities.vehicle import Vehicle, VehicleConfig

if TYPE_CHECKING:
    from src.ai.difficulty import DifficultyConfig
    from src.track.track import Track


class AIVehicle(Vehicle):
    """A vehicle whose throttle/brake/steer come from an :class:`AIController`.

    While ``ai_active`` is False (e.g. during the countdown) the car holds the
    brakes, mirroring the player freeze in :class:`RaceState`.
    """

    def __init__(
        self,
        vehicle_id: int,
        config: VehicleConfig,
        start_pos: tuple[float, float],
        start_angle: float,
        space: pymunk.Space,
        track: Track,
        difficulty: "DifficultyConfig",
        lack: str = "werk",
        config_key: str = "",
    ) -> None:
        super().__init__(vehicle_id, config, start_pos, start_angle, space,
                         lack=lack, config_key=config_key)
        # Imported lazily to keep the ai package out of the core import cycle.
        from src.ai.ai_controller import AIController

        self.controller = AIController(self, track, difficulty)
        self.difficulty = difficulty
        self.ai_active: bool = False

    def update(self, dt: float) -> None:
        if self.ai_active:
            self.throttle, self.brake_input, self.steer_input = self.controller.compute_inputs(dt)
        else:
            self.throttle, self.brake_input, self.steer_input = 0.0, 1.0, 0.0
        super().update(dt)
