"""Difficulty presets for AI opponents.

A :class:`DifficultyConfig` is pure data (Strategy-Pattern parameters). The
:class:`~src.ai.ai_controller.AIController` reads these values to shape its
driving behaviour. Three presets are provided: ``easy`` / ``medium`` / ``hard``.

Settings can be saved/loaded to ``data/ai_settings/<preset>.json``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, fields


@dataclass(frozen=True)
class DifficultyConfig:
    """All tuning parameters that define how an AI opponent drives."""

    name: str
    max_throttle: float             # full-throttle fraction on straights (0.6-1.0)
    look_ahead: float               # look-ahead distance in px (legacy, unused by speed-profile controller)
    brake_threshold: float          # |angle diff| (rad) legacy heuristic (unused by speed-profile controller)
    waypoint_reach_distance: float  # radius (px) to advance the target waypoint
    steering_noise: float           # gaussian noise stddev on steering (0.0-0.15)
    rubber_banding: bool            # throttle bonus when far behind?
    # --- Driving line & character (finetuning) ---
    racing_skill: float = 1.0       # how strongly it cuts the apex line (0-1)
    line_deviation: float = 20.0    # px amplitude it wanders off the racing line
    aggression: float = 0.5         # 0 = timid (yields, early lift) .. 1 = pushy (blocks, tailgates)
    # --- Speed-profile tuning (new) ---
    grip_usage: float = 0.70        # fraction of physical grip used for cornering speed (LAT_SAFETY)
    brake_confidence: float = 0.88  # fraction of max deceleration used for braking (BRAKE_SAFETY)
    steer_confidence: float = 0.65  # fraction of physical steering lock used for turn planning (_TURN_SAFETY)
    wall_margin: float = 24.0       # px safety margin of racing line to wall
    corner_cutting: float = 0.45    # 0 = full apex, 1 = stay on centerline (corner_pull)
    speed_scale: float = 1.0        # global multiplier on target speed
    overtake_dist: float = 90.0     # distance in px to start overtaking
    brake_dist: float = 65.0        # distance in px to start braking/avoidance
    draft_dist: float = 180.0       # max distance in px to slipstream/draft
    block_dist: float = 120.0       # distance in px to block opponent behind


DIFFICULTIES: dict[str, DifficultyConfig] = {
    #                      name      thr  look  brake reach noise rubber skill dev  aggr  grip  brake_c steer_c margin corner speed
    "easy":   DifficultyConfig("Easy",   1.00, 150.0, 0.32, 30.0, 0.00, True,  1.00, 0.0, 0.25, 0.58, 0.78, 0.55, 32.0, 0.55, 0.90),
    "medium": DifficultyConfig("Medium", 1.00, 150.0, 0.32, 30.0, 0.00, False, 1.00, 0.0, 0.55, 0.65, 0.84, 0.60, 26.0, 0.48, 0.96),
    "hard":   DifficultyConfig("Hard",   1.00, 150.0, 0.32, 30.0, 0.00, False, 1.00, 0.0, 0.85, 0.70, 0.88, 0.65, 40.0, 0.45, 0.88),
}


_SETTINGS_DIR = os.path.join("data", "ai_settings")


def get_difficulty(name: str) -> DifficultyConfig:
    """Return the preset for *name*.

    A version tuned and saved in the KI-Labor (``data/ai_settings/<name>.json``)
    takes precedence, so the in-game AI reflects the saved tuning; otherwise the
    built-in preset is used (falling back to ``medium`` if unknown)."""
    saved = load_difficulty(name)
    if saved is not None:
        return saved
    return DIFFICULTIES.get(name, DIFFICULTIES["medium"])


def save_difficulty(name: str, cfg) -> None:
    """Save difficulty settings to ``data/ai_settings/<name>.json``."""
    os.makedirs(_SETTINGS_DIR, exist_ok=True)
    path = os.path.join(_SETTINGS_DIR, f"{name}.json")
    data = {}
    for f in fields(DifficultyConfig):
        data[f.name] = getattr(cfg, f.name)
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2, ensure_ascii=False)


def load_difficulty(name: str) -> DifficultyConfig | None:
    """Load saved settings from ``data/ai_settings/<name>.json``, or None."""
    path = os.path.join(_SETTINGS_DIR, f"{name}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        # Merge with the built-in defaults for forward compatibility. Use the
        # hardcoded preset directly (NOT get_difficulty) to avoid recursion.
        defaults = asdict(DIFFICULTIES.get(name, DIFFICULTIES["medium"]))
        defaults.update(data)
        return DifficultyConfig(**defaults)
    except Exception:
        return None
