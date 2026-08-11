"""Rebindable keyboard controls for driving.

Actions map to a single key each, defaulting to the arrow keys (plus Space for
the handbrake). Bindings persist to data/settings/keybindings.json. ESC and
ENTER are reserved for menus and cannot be bound.
"""
from __future__ import annotations

import json
import os

import pygame

def _path() -> str:
    """Writable keybindings location (user-data dir)."""
    from src.core.paths import user_path
    return user_path("data", "settings", "keybindings.json")

# action id → (label, default key)
ACTIONS: list[tuple[str, str, int]] = [
    ("throttle",  "Gas geben",   pygame.K_UP),
    ("brake",     "Bremse",      pygame.K_DOWN),
    ("left",      "Lenken links", pygame.K_LEFT),
    ("right",     "Lenken rechts", pygame.K_RIGHT),
    ("handbrake", "Handbremse",  pygame.K_SPACE),
]

RESERVED = {pygame.K_ESCAPE, pygame.K_RETURN}

_bindings: dict[str, int] | None = None


def _defaults() -> dict[str, int]:
    return {a: k for a, _lbl, k in ACTIONS}


def _load() -> dict[str, int]:
    global _bindings
    if _bindings is None:
        _bindings = _defaults()
        try:
            with open(_path(), encoding="utf-8") as f:
                data = json.load(f)
            for a in _bindings:
                if a in data and isinstance(data[a], int):
                    _bindings[a] = data[a]
        except Exception:
            pass
    return _bindings


def save() -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(_load(), f, indent=2)
    except Exception:
        pass


def get(action: str) -> int:
    return _load().get(action, _defaults().get(action, 0))


def key_name(code: int) -> str:
    try:
        return pygame.key.name(code).upper()
    except Exception:
        return "?"


def rebind(action: str, code: int) -> tuple[bool, str]:
    """Assign *code* to *action*. Returns (ok, message)."""
    if code in RESERVED:
        return False, "Diese Taste ist reserviert."
    b = _load()
    for a, key in b.items():
        if a != action and key == code:
            return False, f"Bereits belegt: {label_of(a)}"
    b[action] = code
    save()
    return True, ""


def label_of(action: str) -> str:
    for a, lbl, _k in ACTIONS:
        if a == action:
            return lbl
    return action


def pressed(keys, action: str) -> bool:
    return bool(keys[get(action)])
