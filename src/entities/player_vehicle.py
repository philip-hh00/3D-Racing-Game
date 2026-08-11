"""Player-controlled vehicle – maps keyboard input to throttle/brake/steer."""
from __future__ import annotations

import pygame

from src.entities.vehicle import Vehicle
from src.core.input_source import KeyboardSource


class PlayerVehicle(Vehicle):
    """A vehicle controlled by the human player via keyboard.

    Controls:
        W     → Throttle (accelerate)
        S     → Brake (or reverse when nearly stopped)
        A     → Steer left
        D     → Steer right
        SPACE → Handbrake (full brake, reduced grip)
    """

    #: Where this vehicle's input comes from (keyboard by default; a gamepad in
    #: local splitscreen). Set by the race state.
    input_source = None

    def handle_input(self, source=None) -> None:
        """Read the input source and set throttle / brake / steer.

        Args:
            source: an input source (``.read() -> (accel, decel, steer, handbrake)``).
                Falls back to this vehicle's ``input_source`` or a keyboard source.
                A legacy ``pygame`` key state is also accepted for compatibility.
        """
        src = source if source is not None else self.input_source
        if src is None:
            src = self.input_source = KeyboardSource()
        # Backwards compatibility: a raw key-state was passed in.
        if not hasattr(src, "read"):
            src = KeyboardSource()

        accel, decel, steer, handbrake = src.read()
        self.is_analog = getattr(src, "is_analog", False)

        self.handbrake = bool(handbrake)
        if handbrake:
            self.throttle = 0.0
            self.brake_input = 1.0
        elif accel > 0.02:
            if self.signed_speed < -5.0:
                self.throttle = 0.0
                self.brake_input = 1.0
            else:
                self.throttle = accel
                self.brake_input = 0.0
        elif decel > 0.02:
            if self.signed_speed > 5.0:
                self.throttle = 0.0
                self.brake_input = decel
            else:
                self.throttle = -0.6 * decel
                self.brake_input = 0.0
        else:
            self.throttle = 0.0
            self.brake_input = 0.0

        self.steer_input = max(-1.0, min(1.0, steer))
