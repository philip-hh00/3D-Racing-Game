"""Tests for the Qt-free track geometry pipeline (src/track/track_builder.py)."""
from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.track import track_builder as tb


def _circle_control_points(radius=900.0, cx=1500.0, cy=1500.0, n=12):
    return [
        (cx + radius * math.cos(2 * math.pi * i / n),
         cy + radius * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def test_centerline_spacing_is_20px():
    d = tb.TrackDefinition(control_points=_circle_control_points(), width=280.0)
    cl = d.centerline()
    n = len(cl)
    segs = [math.dist(cl[i], cl[(i + 1) % n]) for i in range(n)]
    avg = sum(segs) / n
    assert abs(avg - tb.CENTERLINE_SPACING) < 3.0, f"avg spacing {avg}"


def test_walls_are_one_to_one_and_offset():
    d = tb.TrackDefinition(control_points=_circle_control_points(), width=280.0)
    cl = d.centerline()
    outer, inner = tb.build_walls(cl, 280.0)
    assert len(outer) == len(cl) == len(inner)
    # Each wall point is ~half-width from its centerline point.
    for c, o in zip(cl, outer):
        assert abs(math.dist(c, o) - 140.0) < 1.0


def test_valid_circle_has_no_errors():
    d = tb.TrackDefinition(control_points=_circle_control_points(radius=900.0), width=280.0)
    errs = d.validate()
    assert errs == [], f"unexpected errors: {[e.code for e in errs]}"


def test_tight_corner_triggers_radius_error():
    # A tiny circle -> radius well below the minimum.
    d = tb.TrackDefinition(control_points=_circle_control_points(radius=120.0), width=280.0)
    codes = {e.code for e in d.validate()}
    assert "radius" in codes, f"got {codes}"


def test_too_few_control_points():
    d = tb.TrackDefinition(control_points=[(0, 0), (100, 0), (100, 100)])
    codes = {e.code for e in d.validate()}
    assert "min_points" in codes


def test_schema_matches_bundled_track():
    with open("data/tracks/oval.json", encoding="utf-8") as f:
        oval = json.load(f)
    d = tb.TrackDefinition(control_points=_circle_control_points(), width=280.0)
    out = d.to_json()
    # Every key the game reads must be present.
    for key in ("name", "track_width", "difficulty", "description",
                "background_texture", "centerline", "outer_wall",
                "inner_wall", "waypoints", "start_positions"):
        assert key in out, f"missing {key}"
    # Waypoint / wall shapes match the bundled convention.
    assert set(out["waypoints"][0].keys()) == set(oval["waypoints"][0].keys())
    assert set(out["start_positions"][0].keys()) == set(oval["start_positions"][0].keys())
    assert len(out["outer_wall"]) == len(out["centerline"]) == len(out["waypoints"])
    assert len(out["start_positions"]) == 6
    assert out["waypoints"][0]["is_checkpoint"] is True   # start is always a checkpoint


def test_roundtrip_stable():
    d = tb.TrackDefinition(name="RT", control_points=_circle_control_points(), width=270.0)
    j1 = d.to_json()
    d2 = tb.TrackDefinition.from_json(j1)
    j2 = d2.to_json()
    # Control points survive the roundtrip, so geometry is identical.
    assert d2.control_points == d.control_points
    assert j1["centerline"] == j2["centerline"]
    assert j1["track_width"] == j2["track_width"]


def _run_all() -> int:
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e!r}")
    print(f"{passed}/{len(funcs)} passed")
    return 0 if passed == len(funcs) else 1


if __name__ == "__main__":
    raise SystemExit(_run_all())
