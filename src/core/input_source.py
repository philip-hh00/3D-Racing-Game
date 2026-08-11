"""Driving input sources: keyboard or a specific gamepad.

Each source produces a normalised intent tuple ``(accel, decel, steer, handbrake)``:
    accel, decel  0..1   (analog on a gamepad, 0/1 on the keyboard)
    steer        -1..1   (+1 = left, matching the physics convention)
    handbrake    bool

The vehicle turns these intents into throttle/brake/reverse. This abstraction is
what lets one player drive on the keyboard and another on a controller in the
local splitscreen mode.
"""
from __future__ import annotations

import pygame

from src.core import keybindings as kb
from src.core import gamepad

_STICK_DEADZONE = 0.15


class KeyboardSource:
    """Reads the rebindable driving keys (arrow keys by default; WASD alias)."""
    is_analog = False

    def read(self) -> tuple[float, float, float, bool]:
        keys = pygame.key.get_pressed()
        accel = 1.0 if (kb.pressed(keys, "throttle") or keys[pygame.K_w]) else 0.0
        decel = 1.0 if (kb.pressed(keys, "brake") or keys[pygame.K_s]) else 0.0
        left = kb.pressed(keys, "left") or keys[pygame.K_a]
        right = kb.pressed(keys, "right") or keys[pygame.K_d]
        steer = 1.0 if left else (-1.0 if right else 0.0)
        handbrake = bool(kb.pressed(keys, "handbrake"))
        return accel, decel, steer, handbrake


def _trigger(j, axis: int) -> float:
    """Normalise an SDL2 trigger axis (rest −1 → 0, pressed +1 → 1) with deadzone."""
    try:
        val = j.get_axis(axis)
        norm = (val + 1.0) * 0.5
        # 5% deadzone to filter rest drift
        if norm < 0.05:
            return 0.0
        return max(0.0, min(1.0, (norm - 0.05) / 0.95))
    except Exception:
        return 0.0


class GamepadSource:
    """Reads a specific controller: RT gas, LT brake, left stick steer, A handbrake."""
    is_analog = True

    def __init__(self, index: int) -> None:
        self.index = index

    def read(self) -> tuple[float, float, float, bool]:
        j = gamepad.device(self.index)
        if j is None:
            return 0.0, 0.0, 0.0, False
        accel = _trigger(j, gamepad.AX_RT)
        decel = _trigger(j, gamepad.AX_LT)
        try:
            sx = j.get_axis(gamepad.AX_LEFT_X)
        except Exception:
            sx = 0.0
        steer = -sx if abs(sx) > _STICK_DEADZONE else 0.0
        try:
            handbrake = bool(j.get_button(gamepad.BTN_A))
        except Exception:
            handbrake = False
        return accel, decel, steer, handbrake


class CombinedSource:
    """Keyboard + first gamepad merged: whichever device is actively used wins.

    Used for singleplayer/online races where no explicit device was picked, so
    the player can drive with either input without configuring anything.
    ``is_analog`` reflects the device that produced the current steering value
    (pad steering wants the analog path in the physics)."""
    is_analog = False

    def __init__(self) -> None:
        self._kb = KeyboardSource()
        self._pad = GamepadSource(0)

    def read(self) -> tuple[float, float, float, bool]:
        k_accel, k_decel, k_steer, k_hb = self._kb.read()
        p_accel, p_decel, p_steer, p_hb = self._pad.read()
        pad_active = (p_accel > 0.0 or p_decel > 0.0 or p_steer != 0.0 or p_hb)
        kb_active = (k_accel > 0.0 or k_decel > 0.0 or k_steer != 0.0 or k_hb)
        # Pad input wins when present; keyboard otherwise. Steering analog flag
        # follows whichever source is steering right now.
        self.is_analog = pad_active and not kb_active
        if pad_active and not kb_active:
            return p_accel, p_decel, p_steer, p_hb
        if kb_active and pad_active:
            # Both at once: take the stronger pedal of each and keyboard steer
            # if pressed, else pad steer.
            accel = max(k_accel, p_accel)
            decel = max(k_decel, p_decel)
            steer = k_steer if k_steer != 0.0 else p_steer
            self.is_analog = (steer == p_steer and p_steer != 0.0)
            return accel, decel, steer, (k_hb or p_hb)
        return k_accel, k_decel, k_steer, k_hb


_keyboard_singleton = KeyboardSource()


def make_source(spec: str):
    """Build a source from a lobby spec: 'keyboard', 'pad0', 'pad1', or 'auto'
    (keyboard + first pad combined, for singleplayer/online)."""
    if spec == "auto":
        return CombinedSource()
    if spec == "keyboard":
        return _keyboard_singleton
    if spec.startswith("pad"):
        try:
            return GamepadSource(int(spec[3:]))
        except ValueError:
            pass
    return _keyboard_singleton
