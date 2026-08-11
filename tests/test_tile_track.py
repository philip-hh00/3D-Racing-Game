"""Tests for the tile-based track model (src/track/tile_track.py)."""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.track.tile_track import CELL, Piece, TileTrackDraft


# ---------------------------------------------------------------------------
# Helper: build a complete 12-piece rectangular loop
#
# Layout (grid coords):
#
#   P9  P8  P7         ← top side going west
#    ↑            ↓
#   P10          P6    ← left / right straights
#    ↑            ↓
#   P11  P0  P1  P2    ← bottom side going east  (P0 = START)
#
# Corners:  P2(NW)  P5(SW)  P8(SE)  P11(NE)
# ---------------------------------------------------------------------------
def _rect_loop() -> TileTrackDraft:
    pieces = [
        # bottom side → east
        Piece("straight", col=3, row=3, rotation=0),          # P0 START
        Piece("straight", col=4, row=3, rotation=0),          # P1
        # bottom-right corner: turns east→north
        Piece("curve",    col=5, row=3, rotation=1, radius_cells=1),   # P2 NW arc
        # right side ↑ north
        Piece("straight", col=5, row=4, rotation=1),          # P3
        Piece("straight", col=5, row=5, rotation=1),          # P4
        # top-right corner: turns north→west
        Piece("curve",    col=5, row=6, rotation=0, radius_cells=1),   # P5 SW arc
        # top side ← west
        Piece("straight", col=4, row=6, rotation=0),          # P6
        Piece("straight", col=3, row=6, rotation=0),          # P7
        # top-left corner: turns west→south
        Piece("curve",    col=2, row=6, rotation=3, radius_cells=1),   # P8 SE arc
        # left side ↓ south
        Piece("straight", col=2, row=5, rotation=1),          # P9
        Piece("straight", col=2, row=4, rotation=1),          # P10
        # bottom-left corner: turns south→east
        Piece("curve",    col=2, row=3, rotation=2, radius_cells=1),   # P11 NE arc
    ]
    return TileTrackDraft(
        name="Test Rechteck",
        width=260.0,
        pieces=pieces,
        start_piece_idx=1,   # P1 straight, fed by P0 straight → valid start straight
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_rect_loop_is_closed():
    draft = _rect_loop()
    assert draft.is_closed_loop(), "12-piece rectangle must report as closed loop"


def test_open_loop_detected():
    draft = _rect_loop()
    # Remove the bottom-left corner (P11): opens two ports
    draft.pieces.pop(11)
    assert not draft.is_closed_loop(), "Removing a corner piece must open the loop"
    open_ports = draft.open_ports()
    assert len(open_ports) == 2, f"Expected 2 open ports, got {len(open_ports)}"


def test_curve_radius_r1():
    # The arc of a r=1 curve at any rotation should have radius = CELL/2 = 200 px.
    expected_radius = CELL / 2
    for rot in range(4):
        piece = Piece("curve", col=5, row=5, rotation=rot, radius_cells=1)
        p0, p1 = piece.ports()
        # Points sampled along the arc must all be at distance ≈ expected_radius
        # from the arc center.
        pts = piece.centerline_points(p0)
        cx, cy = piece._arc_center()
        for x, y in pts:
            dist = math.hypot(x - cx, y - cy)
            assert abs(dist - expected_radius) < 0.5, (
                f"rot={rot}: point ({x:.1f},{y:.1f}) at dist {dist:.2f} from center, "
                f"expected {expected_radius}"
            )


def test_curve_radius_r2():
    # r=2: radius = (2-0.5)*CELL = 600 px
    expected_radius = (2 - 0.5) * CELL
    piece = Piece("curve", col=3, row=3, rotation=0, radius_cells=2)
    p0, p1 = piece.ports()
    pts = piece.centerline_points(p0)
    cx, cy = piece._arc_center()
    for x, y in pts:
        dist = math.hypot(x - cx, y - cy)
        assert abs(dist - expected_radius) < 0.5, (
            f"r=2 rot=0: dist {dist:.2f} ≠ {expected_radius}"
        )


def test_curve_r2_ports_connect_to_straight():
    """An r=2 curve's ports must sit at cell-edge centres so 1x1 straights mate."""
    draft = TileTrackDraft(pieces=[
        Piece("curve", col=3, row=3, rotation=0, radius_cells=2),   # S port at col 4
    ])
    curve = draft.pieces[0]
    s_port, w_port = curve.ports()
    # S port should be at the centre of column (col + r-1) = col 4 → x = 4.5*CELL
    assert abs(s_port.wx - 4.5 * CELL) < 0.5, f"S port x={s_port.wx}"
    assert abs(s_port.wy - 3 * CELL) < 0.5
    # A vertical straight directly below (col 4, row 2) must connect to it.
    draft.pieces.append(Piece("straight", col=4, row=2, rotation=1))
    conns = draft.connections()
    # The straight's N port (index 1) connects to the curve's S port.
    assert conns[(1, 1)] == (0, 0), f"straight N should mate curve S, got {conns[(1, 1)]}"


def test_traversal_produces_closed_polyline():
    draft = _rect_loop()
    raw = draft._traverse()
    # First and last raw points should NOT be duplicates (we strip them).
    assert len(raw) > 4
    dist_wrap = math.dist(raw[0], raw[-1])
    assert dist_wrap > 1.0, (
        f"First and last raw points too close ({dist_wrap:.2f}); duplicate not stripped?"
    )


def test_centerline_spacing():
    draft = _rect_loop()
    cl = draft.to_centerline()
    n = len(cl)
    assert n >= 8, f"Too few centerline points: {n}"
    from src.track.tile_track import CENTERLINE_SPACING
    segs = [math.dist(cl[i], cl[(i + 1) % n]) for i in range(n)]
    avg = sum(segs) / n
    assert abs(avg - 20.0) < 3.0, f"Average spacing {avg:.2f} ≠ 20 px"


def test_validate_game_clean_on_closed_loop():
    draft = _rect_loop()
    errs = draft.validate_game()
    codes = [e.code for e in errs]
    assert errs == [], f"Expected no errors, got: {codes}"


def test_start_straight_ok_when_fed_by_straight():
    draft = _rect_loop()
    # P1 (index 1) is a straight fed by P0 (straight) → accel room.
    draft.start_piece_idx = 1
    assert draft.start_straight_ok()
    assert not any(e.code == "start_straight" for e in draft.validate_game())


def test_start_straight_fails_on_curve_start():
    draft = _rect_loop()
    draft.start_piece_idx = 2   # P2 is a curve
    assert not draft.start_straight_ok()
    assert any(e.code == "start_straight" for e in draft.validate_game())


def test_validate_game_open_loop_error():
    draft = _rect_loop()
    draft.pieces.pop(11)
    errs = draft.validate_game()
    assert any(e.code == "open_loop" for e in errs), (
        f"Expected open_loop error, got: {[e.code for e in errs]}"
    )


def test_export_schema_matches_bundled():
    with open("data/tracks/oval.json", encoding="utf-8") as f:
        oval = json.load(f)
    draft = _rect_loop()
    out = draft.to_game_json()

    required_keys = (
        "name", "track_width", "difficulty", "description",
        "background_texture", "centerline", "outer_wall",
        "inner_wall", "waypoints", "start_positions",
    )
    for key in required_keys:
        assert key in out, f"Missing required key: {key!r}"

    # Wall / waypoint / start arrays have same structure as bundled track.
    assert len(out["outer_wall"]) == len(out["centerline"]) == len(out["waypoints"])
    assert set(out["waypoints"][0].keys()) == set(oval["waypoints"][0].keys())
    assert set(out["start_positions"][0].keys()) == set(oval["start_positions"][0].keys())
    assert len(out["start_positions"]) == 6
    assert out["waypoints"][0]["is_checkpoint"] is True   # index 0 always a checkpoint


def test_draft_roundtrip():
    draft = _rect_loop()
    d = draft.to_draft_dict()
    draft2 = TileTrackDraft.from_draft_dict(d)

    assert draft2.name == draft.name
    assert draft2.width == draft.width
    assert len(draft2.pieces) == len(draft.pieces)
    for p_orig, p_rt in zip(draft.pieces, draft2.pieces):
        assert p_orig.kind == p_rt.kind
        assert p_orig.col == p_rt.col
        assert p_orig.row == p_rt.row
        assert p_orig.rotation == p_rt.rotation
        assert p_orig.radius_cells == p_rt.radius_cells


def test_game_json_roundtrip_via_editor_tiles():
    """to_game_json embeds editor_tiles; loading from it must reproduce the draft."""
    draft = _rect_loop()
    game_json = draft.to_game_json()
    assert "editor_tiles" in game_json
    draft2 = TileTrackDraft.from_draft_dict(game_json["editor_tiles"])
    assert draft2.is_closed_loop()
    assert len(draft2.pieces) == len(draft.pieces)


def test_draft_save_load_file(tmp_path):
    """Draft persists to disk and loads back identically."""
    draft = _rect_loop()
    path = str(tmp_path / "test_rect.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(draft.to_draft_dict(), f)
    loaded = TileTrackDraft.load_draft(path)
    assert loaded.name == draft.name
    assert len(loaded.pieces) == len(draft.pieces)
    assert loaded.is_closed_loop()


def test_new_with_start():
    """Vorgelegte Start-/Ziel-Gerade.

    **Zwei** Anlaufgerade hinter der Linie seit dem 08.08.2026, nicht eine: der
    hinterste Startplatz liegt 560 px zurueck, eine Zelle misst 400 px. Mit nur
    einer standen die letzten beiden Autos jenseits des Bauteils — setzte
    jemand dort eine Kurve, starteten sie in der Kurve (gemeldet). Die genaue
    Zahl haelt ``tests/test_startaufstellung.py`` gegen die Startabstaende;
    hier steht der Aufbau.
    """
    draft = TileTrackDraft.new_with_start()
    assert len(draft.pieces) == 4          # 2x Anlauf + Start/Ziel + eine voraus
    start = draft.pieces[draft.start_piece_idx]
    assert start.kind == "straight"
    assert start.col == 5 and start.row == 5
    assert start.rotation == 0
    # Beide Bauteile westlich davon sind die Anlaufgeraden.
    assert draft.piece_at(4, 5) is not None
    assert draft.piece_at(3, 5) is not None
    # Not a closed loop yet
    assert not draft.is_closed_loop()


def test_occupied_cells():
    draft = _rect_loop()
    cells = draft.occupied_cells()
    # 8 straights (1×1 each) + 4 curves (1×1 each with r=1) = 12 distinct cells
    assert len(cells) == 12, f"Expected 12 occupied cells, got {len(cells)}"


def test_piece_at():
    draft = _rect_loop()
    assert draft.piece_at(3, 3) == 0   # P0 START
    assert draft.piece_at(5, 3) == 2   # P2 curve
    assert draft.piece_at(9, 9) is None


def test_unpublish_and_delete_track(tmp_path, monkeypatch):
    """Test unpublish_track and delete_track helpers."""
    from src.track import tile_track
    # Seit dem 04.08.2026 sind das Funktionen über paths.user_path, keine
    # Konstanten mehr: ein gepacktes macOS-Bundle setzt das Arbeitsverzeichnis
    # ins schreibgeschützte .app, und der Editor konnte dort nichts speichern.
    monkeypatch.setattr(tile_track, "draft_dir", lambda: str(tmp_path / "drafts"))
    monkeypatch.setattr(tile_track, "custom_dir", lambda: str(tmp_path / "custom"))
    os.makedirs(tmp_path / "drafts", exist_ok=True)
    os.makedirs(tmp_path / "custom", exist_ok=True)

    name = "Test Track"
    slug = tile_track._slugify(name)
    draft_file = tmp_path / "drafts" / f"{slug}.json"
    custom_file = tmp_path / "custom" / f"{slug}.json"

    # Realer Inhalt mit "name": delete_track sucht die Datei ueber ihren
    # gespeicherten Namen, nicht mehr ueber den geratenen Slug (08.08.2026).
    custom_file.write_text('{"name": "Test Track"}', encoding="utf-8")
    assert custom_file.exists()

    tile_track.unpublish_track(name)
    assert not custom_file.exists()
    assert draft_file.exists()

    assert tile_track.delete_track(name) is True
    assert not draft_file.exists()
    assert not custom_file.exists()


def test_delete_track_findet_empfangene_strecke(tmp_path, monkeypatch):
    """Regel: eine Strecke wird ueber ihren gespeicherten Namen geloescht, nicht
    ueber den geratenen Dateinamen.

    Eine online empfangene Strecke liegt unter ihrem uebertragenen Dateinamen
    (``Rundkurs (2).json``), dessen Stamm den Slug ``rundkurs`` nie trifft. Der
    Name steht aber im JSON, und darueber muss sie auffindbar sein. Auch der
    Ghost haengt am echten Dateinamen (``custom/Rundkurs (2)``), nicht am Slug
    (Fund 08.08.2026)."""
    from src.track import tile_track
    from src.core import ghost
    monkeypatch.setattr(tile_track, "draft_dir", lambda: str(tmp_path / "drafts"))
    monkeypatch.setattr(tile_track, "custom_dir", lambda: str(tmp_path / "custom"))
    os.makedirs(tmp_path / "custom", exist_ok=True)

    empfangen = tmp_path / "custom" / "Rundkurs (2).json"
    empfangen.write_text('{"name": "Rundkurs"}', encoding="utf-8")
    assert tile_track._slugify("Rundkurs") != "Rundkurs (2)"  # Slug traf nie

    geloeschte_ghosts: list[str] = []
    monkeypatch.setattr(ghost, "delete", lambda key: geloeschte_ghosts.append(key))

    assert tile_track.delete_track("Rundkurs") is True
    assert not empfangen.exists()
    assert geloeschte_ghosts == ["custom/Rundkurs (2)"]


def test_delete_track_ohne_treffer_meldet_misserfolg(tmp_path, monkeypatch):
    """Regel: ein Loeschen, das nichts gefunden hat, meldet keinen Erfolg.

    Frueher gab ``delete_track`` immer ``None`` zurueck; der Aufrufer meldete
    Erfolg, auch wenn ``os.remove`` ins Leere lief. Fremde Strecken bleiben
    dabei unberuehrt (Fund 08.08.2026)."""
    from src.track import tile_track
    monkeypatch.setattr(tile_track, "draft_dir", lambda: str(tmp_path / "drafts"))
    monkeypatch.setattr(tile_track, "custom_dir", lambda: str(tmp_path / "custom"))
    os.makedirs(tmp_path / "custom", exist_ok=True)
    andere = tmp_path / "custom" / "andere.json"
    andere.write_text('{"name": "Andere"}', encoding="utf-8")

    assert tile_track.delete_track("Gibt Es Nicht") is False
    assert andere.exists()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def _run_all() -> int:
    import traceback
    funcs = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in funcs:
        sig = fn.__code__.co_varnames[:fn.__code__.co_argcount]
        try:
            if "tmp_path" in sig:
                with tempfile.TemporaryDirectory() as d:
                    import pathlib
                    fn(pathlib.Path(d))
            else:
                fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {fn.__name__}: {e!r}")
            traceback.print_exc()
    print(f"\n{passed}/{len(funcs)} passed")
    return 0 if passed == len(funcs) else 1


if __name__ == "__main__":
    raise SystemExit(_run_all())
