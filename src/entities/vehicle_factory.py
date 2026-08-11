"""Vehicle factory for loading and caching vehicle configurations."""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import dataclasses

from src.entities.vehicle import Vehicle, VehicleConfig
from src.entities.player_vehicle import PlayerVehicle
from src.entities.ai_vehicle import AIVehicle

if TYPE_CHECKING:
    import pymunk
    from src.track.track import Track
    from src.ai.difficulty import DifficultyConfig


class VehicleFactory:
    """Loads, caches, and instantiates vehicles from JSON configurations."""

    _configs: dict[str, VehicleConfig] = {}

    @classmethod
    def load_all_configs(cls, directory: str = "data/vehicles") -> None:
        """Scan directory and load all vehicle JSON configurations."""
        cls._configs.clear()
        dir_path = Path(directory)
        if not dir_path.exists():
            return

        for file_path in dir_path.glob("*.json"):
            try:
                # Der Ordner enthaelt nicht nur Fahrzeuge: lacke.json haelt die
                # Lackpalette. Ohne diese Pruefung landete sie als 16. "Fahrzeug"
                # in der Liste — sichtbar im Fahrzeuglabor als "12 / 16".
                # Merkmal eines Fahrzeugs ist visual_type.
                import json as _json
                with open(file_path, encoding="utf-8") as fh:
                    if not isinstance(_json.load(fh).get("visual_type"), str):
                        continue
                config = VehicleConfig.from_json(str(file_path))
                # Store by name/key (filename without extension)
                key = file_path.stem
                cls._configs[key] = config
            except Exception as e:
                print(f"[VehicleFactory] Error loading {file_path}: {e}")

    @classmethod
    def get_available_configs(cls) -> list[VehicleConfig]:
        """Return a list of all loaded vehicle configurations."""
        return list(cls._configs.values())

    @classmethod
    def get_config(cls, key: str) -> VehicleConfig | None:
        """Get a vehicle configuration by its key."""
        return cls._configs.get(key)

    @classmethod
    def get_all_keys(cls) -> list[str]:
        """Return all keys of loaded configurations."""
        return list(cls._configs.keys())

    @classmethod
    def create_player_vehicle(
        cls,
        config_key: str,
        vehicle_id: int,
        start_pos: tuple[float, float],
        start_angle: float,
        space: pymunk.Space,
        lack: str | None = None,
    ) -> PlayerVehicle | None:
        """Create and return a PlayerVehicle instance using a config key.

        Args:
            lack: Lackkennung. None heisst: die im Profil gewaehlte nehmen —
                das ist der Normalfall, damit die Werkstattwahl im Rennen
                ankommt, ohne dass jede Aufrufstelle daran denken muss.
        """
        config = cls.get_config(config_key)
        if not config:
            return None
        if lack is None:
            from src.core import profile
            lack = profile.current().paint(config_key)
        return PlayerVehicle(
            vehicle_id=vehicle_id,
            config=config,
            start_pos=start_pos,
            start_angle=start_angle,
            space=space,
            lack=lack,
            config_key=config_key,
        )

    @classmethod
    def create_ai_vehicle(
        cls,
        config_key: str,
        vehicle_id: int,
        start_pos: tuple[float, float],
        start_angle: float,
        space: pymunk.Space,
        track: Track,
        difficulty: DifficultyConfig,
        color_primary: tuple[int, int, int] | None = None,
        lack: str | None = None,
    ) -> AIVehicle | None:
        """Create an AIVehicle from a config key, with an optional color override.

        Args:
            config_key:    Vehicle JSON key (e.g. ``"supercar"``).
            vehicle_id:    Unique id within the race.
            start_pos:     Spawn position in pymunk coords.
            start_angle:   Spawn heading in radians.
            space:         The pymunk space.
            track:         Track reference for waypoint navigation.
            difficulty:    Difficulty preset shaping the driving behaviour.
            color_primary: Body colour for the *procedural* fallback — sichtbar
                nur bei einem Fahrzeug ohne PNG. Fuer sichtbare Farbe: *lack*.
            lack:          Lackkennung. None heisst Werkslack — die KI erbt
                ausdruecklich **nicht** die Wahl des Spielers aus dem Profil.
        """
        config = cls.get_config(config_key)
        if not config:
            return None
        if color_primary is not None:
            config = dataclasses.replace(config, color_primary=tuple(color_primary))
        from src.core.lack import WERK, normalisiere
        return AIVehicle(
            vehicle_id=vehicle_id,
            config=config,
            start_pos=start_pos,
            start_angle=start_angle,
            space=space,
            track=track,
            difficulty=difficulty,
            lack=normalisiere(lack) if lack is not None else WERK,
            config_key=config_key,
        )
