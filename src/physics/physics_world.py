"""Physics world – manages the pymunk.Space, stepping, and debug drawing.

The entire game uses a single top-down pymunk space with gravity (0, 0).
Sub-stepping is used for stable collision detection at 60 FPS.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Any, Sequence

import pymunk
import pymunk.pygame_util
import pygame

from src.core.settings import PHYSICS_SUBSTEPS

if TYPE_CHECKING:
    pass


class PhysicsWorld:
    """Wraps a *pymunk.Space* for a top-down racing game.

    Responsibilities
    ----------------
    * Create and own the pymunk space (gravity = 0).
    * Step the simulation with configurable sub-steps.
    * Add / remove bodies and shapes.
    * Register collision handlers with a cleaner API.
    * Provide optional debug drawing on a *pygame.Surface*.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, damping: float = 1.0) -> None:
        """Initialise the physics space.

        Parameters
        ----------
        damping:
            Global velocity damping factor (0 – 1).
            1.0 means bodies retain 100 % of velocity (we use custom drag instead).
        """
        self.space: pymunk.Space = pymunk.Space()
        self.space.gravity = (0.0, 0.0)  # Top-down – no gravity
        self.space.damping = damping

        # Optional debug draw helper (created lazily)
        self._debug_draw_options: pymunk.pygame_util.DrawOptions | None = None

    # ------------------------------------------------------------------
    # Simulation step
    # ------------------------------------------------------------------

    def step(self, dt: float) -> None:
        """Advance the simulation by *dt* seconds using sub-stepping.

        Parameters
        ----------
        dt:
            Delta time since last frame (seconds).
        """
        sub_dt: float = dt / PHYSICS_SUBSTEPS
        for _ in range(PHYSICS_SUBSTEPS):
            self.space.step(sub_dt)

    # ------------------------------------------------------------------
    # Body / shape management
    # ------------------------------------------------------------------

    def add_body(self, body: pymunk.Body, *shapes: pymunk.Shape) -> None:
        """Add a body and its shapes to the space."""
        self.space.add(body, *shapes)

    def remove_body(self, body: pymunk.Body, *shapes: pymunk.Shape) -> None:
        """Remove a body and its shapes from the space.

        Silently skips items that are not in the space.
        """
        for shape in shapes:
            if shape in self.space.shapes:
                self.space.remove(shape)
        if body in self.space.bodies:
            self.space.remove(body)

    # ------------------------------------------------------------------
    # Collision handlers
    # ------------------------------------------------------------------

    def add_collision_handler(
        self,
        type_a: int,
        type_b: int,
        begin_func: Callable[..., bool] | None = None,
        separate_func: Callable[..., None] | None = None,
    ) -> None:
        """Register collision callbacks between two collision types.

        Parameters
        ----------
        type_a, type_b:
            The ``collision_type`` integers of the involved shapes.
        begin_func:
            Called when two shapes start overlapping.  Must return *True*
            to let the collision be processed, *False* to ignore it.
        separate_func:
            Called when two shapes stop overlapping.
        """
        self.space.on_collision(
            type_a,
            type_b,
            begin=begin_func,
            separate=separate_func,
        )

    # ------------------------------------------------------------------
    # Debug drawing
    # ------------------------------------------------------------------

    def debug_draw(self, screen: pygame.Surface) -> None:
        """Draw all physics shapes onto *screen* for debugging.

        Uses ``pymunk.pygame_util.DrawOptions`` which handles the
        Y-axis flip internally.
        """
        if self._debug_draw_options is None:
            self._debug_draw_options = pymunk.pygame_util.DrawOptions(screen)
        self.space.debug_draw(self._debug_draw_options)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Remove **everything** from the space (bodies, shapes, constraints)."""
        # Remove shapes first, then bodies, then constraints
        for shape in list(self.space.shapes):
            self.space.remove(shape)
        for body in list(self.space.bodies):
            self.space.remove(body)
        for constraint in list(self.space.constraints):
            self.space.remove(constraint)
