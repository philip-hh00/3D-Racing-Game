"""Global constants and configuration for the racing game."""
from __future__ import annotations


# --- Display ---
SCREEN_WIDTH: int = 1920
SCREEN_HEIGHT: int = 1080
TARGET_FPS: int = 60

# --- Physics ---
PHYSICS_SUBSTEPS: int = 3
PHYSICS_DT: float = 1.0 / (TARGET_FPS * PHYSICS_SUBSTEPS)

# --- Unit scale (single source of truth) ---
# The physics converts real Newtons to pymunk units by dividing by 0.08, i.e.
# 1 px = 0.08 m. Every speed/length display MUST use these so the HUD, the car
# selection specs and the vehicle-lab benchmark all agree.
M_PER_PX: float = 0.08
KMH_PER_PXS: float = M_PER_PX * 3.6   # px/s → km/h  (= 0.288)

# --- Camera ---
CAMERA_LERP_SPEED: float = 5.0

# --- Minimap ---
MINIMAP_SCALE: float = 0.12

# --- Track ---
TRACK_WIDTH_DEFAULT: float = 80.0

# --- AI opponents ---
AI_OPPONENT_COUNT: int = 3
AI_DEFAULT_DIFFICULTY: str = "medium"
# Vehicle config keys cycled through for AI cars (mixed field = livelier).
# Only a fallback — the race normally uses the selected class's keys
# (race_setup.class_keys()), which covers all three cars per class.
AI_VEHICLE_KEYS: list[str] = [
    "supercar", "supercar_2", "supercar_3",
    "drifter", "drifter_2", "drifter_3",
    "limousine", "limousine_2", "limousine_3",
    "electric", "electric_2", "electric_3",
]

# --- Collision types (for pymunk collision filtering) ---
COLLISION_TYPE_VEHICLE: int = 1
COLLISION_TYPE_WALL: int = 2
COLLISION_TYPE_CHECKPOINT: int = 3

# Aliases used by existing modules (physics_body, collision_handler, track)
VEHICLE_COLLISION_TYPE: int = COLLISION_TYPE_VEHICLE
TRACK_WALL_COLLISION_TYPE: int = COLLISION_TYPE_WALL
CHECKPOINT_COLLISION_TYPE: int = COLLISION_TYPE_CHECKPOINT

# --- Colors (R, G, B) ---
# Track colors
COLOR_ASPHALT: tuple[int, int, int] = (60, 60, 65)
COLOR_TRACK_BORDER: tuple[int, int, int] = (200, 200, 200)
COLOR_CURB_RED: tuple[int, int, int] = (200, 40, 40)
COLOR_CURB_WHITE: tuple[int, int, int] = (240, 240, 240)
COLOR_GRASS: tuple[int, int, int] = (45, 120, 50)
COLOR_GRASS_DARK: tuple[int, int, int] = (35, 100, 40)
COLOR_START_LINE: tuple[int, int, int] = (255, 255, 255)

# UI colors
COLOR_UI_BG: tuple[int, int, int] = (20, 20, 30)
COLOR_UI_TEXT: tuple[int, int, int] = (230, 230, 230)
COLOR_UI_ACCENT: tuple[int, int, int] = (255, 180, 0)
COLOR_UI_DANGER: tuple[int, int, int] = (220, 50, 50)
COLOR_UI_SUCCESS: tuple[int, int, int] = (50, 200, 80)
COLOR_UI_PANEL: tuple[int, int, int, int] = (10, 10, 20, 180)

# Vehicle colors (for procedural rendering)
#
# Nur fuer den programmatischen Rueckfall — ein Fahrzeug ohne PNG. Alle 15
# haben eines, diese Farben sind im Spiel also nirgends zu sehen. Wer KI-Autos
# unterscheidbar machen will, ist bei `lack.ki_lack()` richtig (Fund
# 30.07.2026: die Zuweisung hier hat nie etwas bewirkt).
COLOR_PLAYER_CAR: tuple[int, int, int] = (220, 40, 40)
COLOR_AI_CAR_1: tuple[int, int, int] = (40, 100, 220)
COLOR_AI_CAR_2: tuple[int, int, int] = (40, 200, 80)
COLOR_AI_CAR_3: tuple[int, int, int] = (200, 180, 40)

# HUD colors
COLOR_HUD_SPEED: tuple[int, int, int] = (0, 255, 120)
COLOR_HUD_RPM: tuple[int, int, int] = (255, 100, 50)
COLOR_HUD_LAP: tuple[int, int, int] = (255, 255, 100)

# --- Debug ---
DEBUG: bool = False
