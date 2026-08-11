"""Device-aware control hints.

One source of truth for every "press X to Y" line in the game. Each action maps
to a keyboard label and a controller label; :func:`label` / :func:`bar` return
whichever matches the current input mode, so screens never hard-code "ENTER".
"""
from __future__ import annotations

from src.core import input_mode
from src.core.i18n import tr
from src.ui import theme

# action id -> (keyboard label, controller label)
_LABELS: dict[str, tuple[str, str]] = {
    "confirm":  ("ENTER", "A"),
    "back":     ("ESC", "B"),
    "start":    ("ENTER", "A"),
    "nav":      ("Pfeile", "D-Pad"),
    "nav_v":    ("↑/↓", f"D-Pad {theme.HOCH_RUNTER}"),
    "nav_h":    ("←/→", "D-Pad ↔"),
    "adjust":   ("←/→", "D-Pad ↔"),
    "tabs":     ("←/→", "LB/RB"),
    "edit":     ("tippen", "A"),
    "pause":    ("ESC", "Start"),
    "ready":    ("Leertaste", "A"),
    "select":   ("Klick / ENTER", "A"),
    "scroll":   ("Mausrad / ↑↓", f"D-Pad {theme.HOCH_RUNTER}"),
}


def label(action: str) -> str:
    """The key/button label for *action* in the current input mode."""
    kb, pad = _LABELS.get(action, (action, action))
    return tr(pad if input_mode.is_pad() else kb)


def bar(*items: tuple[str, str]) -> str:
    """Build a hint line from (action, description) pairs.

    Example: ``bar(("confirm", "Auswählen"), ("back", "Zurück"))``
    → "A Auswählen    B Zurück" (controller) / "ENTER Auswählen    ESC Zurück".
    """
    return "     ".join(f"{label(a)} {desc}" for a, desc in items)
