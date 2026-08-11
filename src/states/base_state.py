"""Abstract base class for all game states."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


class BaseState(ABC):
    """Every game state (menu, race, pause, etc.) inherits from this.

    Lifecycle:
        enter() → [handle_events / update / render loop] → exit()

    Overlay lifecycle (push/pop):
        enter() → ... → pause() → [overlay runs] → resume() → ... → exit()
    """

    def __init__(self, state_machine: StateMachine) -> None:
        self.state_machine = state_machine

    def enter(self, **kwargs) -> None:
        """Called when this state becomes active."""
        pass

    def exit(self) -> None:
        """Called when leaving this state."""
        pass

    def pause(self) -> None:
        """Called when another state is pushed on top."""
        pass

    def resume(self) -> None:
        """Called when the overlaying state is popped."""
        pass

    def rueckweg_kwargs(self) -> dict | None:
        """Womit dieser Zustand wiederherzustellen ist, wenn jemand hierher
        zurueckkehrt.

        ``None`` heisst: die Argumente nehmen, mit denen er zuletzt betreten
        wurde. Wer seinen Stand selbst haelt, gibt ``{}`` zurueck — dann wird er
        beim Zurueckkommen nicht neu aufgebaut.
        """
        return None

    @abstractmethod
    def handle_events(self, events: list[pygame.event.Event]) -> None:
        """Process input events."""
        ...

    @abstractmethod
    def update(self, dt: float) -> None:
        """Update game logic."""
        ...

    @abstractmethod
    def render(self, screen: pygame.Surface) -> None:
        """Draw to screen."""
        ...
