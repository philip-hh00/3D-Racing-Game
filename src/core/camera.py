"""Camera – smooth viewport tracking for the player vehicle."""
from __future__ import annotations

import pygame

from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT


class Camera:
    """Follows a target position with smooth linear interpolation.

    The camera stores its position in *world* coordinates (pymunk/pygame
    agnostic — whatever the render pipeline uses).
    """

    def __init__(self, view_w: int = SCREEN_WIDTH, view_h: int = SCREEN_HEIGHT) -> None:
        self.x: float = 0.0
        self.y: float = 0.0
        self.zoom: float = 1.0
        # Viewport size the camera centres within (a splitscreen half is narrower).
        self.view_w = view_w
        self.view_h = view_h

    def follow(self, target_pos: tuple[float, float], dt: float,
               lerp_speed: float = 5.0) -> None:
        """Smoothly move the camera toward the target position.

        Args:
            target_pos: World position of the target (center of screen).
            dt: Delta time in seconds.
            lerp_speed: How quickly the camera catches up (higher = faster).
        """
        target_x = target_pos[0] - self.view_w / 2
        target_y = target_pos[1] - self.view_h / 2
        self.x += (target_x - self.x) * lerp_speed * dt
        self.y += (target_y - self.y) * lerp_speed * dt

    @property
    def offset(self) -> pygame.Vector2:
        """Return the offset vector to subtract from world positions."""
        return pygame.Vector2(-self.x, -self.y)

    def world_to_screen(self, pos: tuple[float, float]) -> tuple[int, int]:
        """Convert a world position to screen coordinates."""
        return (
            int(pos[0] - self.x),
            int(pos[1] - self.y),
        )
