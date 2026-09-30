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

    Neun Kontrollpunkte: eine lange Gerade unten, zwei weite Bögen rechts und
    eine Kehre (Spitze bei (1700, 1800)), deren engster Mittellinienradius
    knapp über dem Editor-Mindestradius liegt (~190 px bei Breite 270).
    """
    from src.track.track_builder import TrackDefinition, min_radius_for_width
    from src.track.track import Track
    from src.ai.racing_line_solver import _menger_curvature
    punkte = [(0, 0), (2600, 0), (3400, 600), (3400, 1500), (2500, 2100),
              (1700, 1800), (900, 2100), (0, 1600), (-500, 800)]
    defn = TrackDefinition(name="KI-Test", control_points=[(float(x), float(y)) for x, y in punkte],
                           width=270.0)
    assert not defn.validate(), [f.message for f in defn.validate()]
    cl = defn.centerline()
    n = len(cl)
    kmax = max(_menger_curvature(cl[i - 1], cl[i], cl[(i + 1) % n]) for i in range(n))
    assert kmax > 0 and 1.0 / kmax < 450.0, "Editorstrecke ohne enge Kehre"
    assert 1.0 / kmax >= min_radius_for_width(270.0) - 1.0
    assert sum(math.dist(cl[i], cl[(i + 1) % n]) for i in range(n)) > 5000.0
    pfad = os.path.join(str(tmp_path), "ki_test.json")
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(defn.to_json(), fh)
    return Track(pfad, space or pymunk.Space())


def config(key: str = "rookie"):
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_config(key):
        VehicleFactory.load_all_configs(os.path.join(WURZEL, "data", "vehicles"))
    return VehicleFactory.get_config(key)
