"""Hilfen für die KI-Tests: Strecken laden, Editorstrecke bauen, Fahrzeugwerte."""
from __future__ import annotations

import json
import math
import os
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk


def strecke_laden(name: str, space: pymunk.Space | None = None):
    from src.track.track import Track
    return Track(os.path.join(WURZEL, "data", "tracks", f"{name}.json"), space or pymunk.Space())


def eigene_strecke(tmp_path, space: pymunk.Space | None = None):
    """Eine Strecke wie aus dem Editor: Kontrollpunkte → Spline → Spiel-JSON.

    Vierzehn Punkte auf einem Kreis — sanfte Kurven mit einer leicht
    eingezogenen Stelle für interessantes Fahren.
    """
    from src.track.track_builder import TrackDefinition
    from src.track.track import Track
    punkte = []
    for i in range(14):
        angle = 2 * math.pi * i / 14
        x = 3500 + 3000 * math.cos(angle)
        y = 3000 + 3000 * math.sin(angle)
        # Slightly tighten one corner (points 6-8) for interest
        if 6 <= i <= 8:
            x *= 0.95
            y *= 0.95
        punkte.append((x, y))
    defn = TrackDefinition(name="KI-Test", control_points=[(float(x), float(y)) for x, y in punkte],
                           width=270.0)
    assert not defn.validate(), [f.message for f in defn.validate()]
    pfad = os.path.join(str(tmp_path), "ki_test.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(defn.to_json(), fh)
    return Track(pfad, space or pymunk.Space())


def config(key: str = "rookie"):
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_config(key):
        VehicleFactory.load_all_configs(os.path.join(WURZEL, "data", "vehicles"))
    return VehicleFactory.get_config(key)
