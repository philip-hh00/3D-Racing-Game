"""Singleton EventBus for decoupled communication between game systems.

Usage:
    from src.core.event_bus import EventBus
    bus = EventBus()
    bus.subscribe("lap_complete", my_handler)
    bus.emit("lap_complete", {"lap": 2, "time": 45.3})
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


class EventBus:
    """A simple publish-subscribe event bus implemented as a singleton.

    All game systems can communicate through named events without
    direct references to each other.
    """

    _instance: EventBus | None = None

    def __new__(cls) -> EventBus:
        """Ensure only one EventBus instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._subscribers: defaultdict[str, list[Callable]] = defaultdict(list)
        return cls._instance

    @classmethod
    def create_isolated(cls) -> "EventBus":
        """Create a standalone EventBus that is NOT the global singleton.

        Used by short-lived simulations (e.g. the seed-ghost generator) that must
        not share subscribers with the live game's global bus."""
        bus = object.__new__(cls)
        bus._subscribers = defaultdict(list)
        return bus

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for the given event type.

        Args:
            event_type: The name of the event to listen for.
            callback: A callable that accepts an optional data argument.
        """
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a callback from the given event type.

        Args:
            event_type: The name of the event.
            callback: The callback to remove.
        """
        try:
            self._subscribers[event_type].remove(callback)
        except ValueError:
            pass  # Callback was not subscribed — ignore silently

    def emit(self, event_type: str, data: Any = None) -> None:
        """Emit an event, calling all registered callbacks.

        Args:
            event_type: The name of the event to emit.
            data: Optional data payload passed to each callback.
        """
        for callback in self._subscribers[event_type]:
            callback(data)

    def reset(self) -> None:
        """Clear all subscribers. Useful for cleanup between game states."""
        self._subscribers.clear()
