"""Active input mode (keyboard vs controller) with a brief change pulse.

Thin layer over :func:`gamepad.using_pad`. Drives the on-screen mode badge and
lets every hint text pick keyboard- or controller-wording via ``src/ui/hints``.
"""
from __future__ import annotations

from src.core import gamepad

_prev: str | None = None
_pulse: float = 0.0


def current() -> str:
    """'gamepad' if the last real input came from a controller, else 'keyboard'."""
    return "gamepad" if gamepad.using_pad() else "keyboard"


def is_pad() -> bool:
    return current() == "gamepad"


def update(dt: float) -> None:
    """Track mode changes to trigger a short highlight pulse on the badge."""
    global _prev, _pulse
    cur = current()
    if cur != _prev:
        if _prev is not None:
            _pulse = 0.6
        _prev = cur
    if _pulse > 0.0:
        _pulse = max(0.0, _pulse - dt)


def pulse() -> float:
    """0..1 highlight strength shortly after a mode change (0 = settled)."""
    return _pulse / 0.6 if _pulse > 0.0 else 0.0
