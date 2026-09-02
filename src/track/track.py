"""Track class - loads track data from JSON and builds pymunk physics walls.

The track JSON format contains:
- name: Track display name
- track_width: Width of the drivable road surface
- centerline: List of {x, y} points defining the track center
- outer_wall / inner_wall: Lists of {x, y} points for wall polygons
- waypoints: List of {x, y, is_checkpoint} for AI navigation / checkpoints
- start_positions: List of {x, y, angle} for car spawn positions
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymunk

from src.core.settings import TRACK_WALL_COLLISION_TYPE


class TrackDataError(Exception):
    """A track file cannot be used at all.

    Raised only when there is nothing salvageable — no readable centerline.
    Damage to single waypoints, walls or start positions is repaired silently
    instead (see ``Track._load``), because a track missing one waypoint is
    still perfectly drivable while a crash mid-transition is not.
    """


# ---------------------------------------------------------------------------
# Tolerant readers for damaged track files
# ---------------------------------------------------------------------------


def _as_float(value: Any, default: float | None, minimum: float | None = None):
    """Number from *value*, or *default* when it is unusable.

    ``OverflowError`` gehört mit in die Liste: JSON erlaubt beliebig lange
    Ganzzahlen, und ``float(10**400)`` wirft. Über eine geteilte Strecke war das
    ein Absturz des ganzen Spiels (Releaseplan H2.2).
    """
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if out != out or out in (float("inf"), float("-inf")):     # NaN / unendlich
        return default
    if minimum is not None and out < minimum:
        return default
    return out


#: Höchste Verschachtelungstiefe, die eine Streckendatei haben darf. Eine echte
#: kommt auf 3 (Objekt → Liste → Punktobjekt); 40 ist also grosszügig.
MAX_TIEFE = 40


def _tiefe_ueberschritten(text: str, grenze: int = MAX_TIEFE) -> bool:
    """Ob *text* tiefer verschachtelt ist als erlaubt — ohne ihn zu parsen.

    ``json.load`` steigt für jede Klammer eine Ebene in die Rekursion. Bei
    ``[[[[...`` mit 100 000 Klammern wirft es ``RecursionError``, und der ist
    kein ``JSONDecodeError`` — er lief also durch jede Fehlerbehandlung
    hindurch und beendete das Spiel (Releaseplan H2.2).

    Klammern in Zeichenketten zählen nicht mit, sonst würde ein Streckenname
    wie ``"[[Oval]]"`` die Prüfung auslösen.
    """
    tiefe = 0
    in_text = False
    maskiert = False
    for z in text:
        if in_text:
            if maskiert:
                maskiert = False
            elif z == "\\":
                maskiert = True
            elif z == '"':
                in_text = False
            continue
        if z == '"':
            in_text = True
        elif z in "[{":
            tiefe += 1
            if tiefe > grenze:
                return True
        elif z in "]}":
            tiefe -= 1
    return False


def _as_sequence(value: Any) -> list:
    """List from *value*; anything else counts as empty.

    Strings are deliberately excluded: iterating one would yield characters and
    turn a typo into hundreds of bogus entries.
    """
    if isinstance(value, list):
        return value
    return []


def _point_list(value: Any) -> list[tuple[float, float]]:
    """Readable {x, y} entries; damaged ones are dropped."""
    out: list[tuple[float, float]] = []
    for p in _as_sequence(value):
        if not isinstance(p, dict):
            continue
        x = _as_float(p.get("x"), None)
        y = _as_float(p.get("y"), None)
        if x is None or y is None:
            continue
        out.append((x, y))
    return out


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Waypoint:
    """A single waypoint on the track, optionally marking a checkpoint."""

    x: float
    y: float
    is_checkpoint: bool = False

    @property
    def pos(self) -> tuple[float, float]:
        """Return position as a simple tuple."""
        return (self.x, self.y)


@dataclass(frozen=True, slots=True)
class StartPosition:
    """A grid start position for a car."""

    x: float
    y: float
    angle: float  # degrees, 0 = right / east

    @property
    def pos(self) -> tuple[float, float]:
        """Return position as a simple tuple."""
        return (self.x, self.y)


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------


class Track:
    """Loads a track from a JSON file and creates pymunk physics walls.

    Attributes:
        name:            Human-readable track name.
        track_width:     Width of the drivable road in pixels.
        centerline:      Ordered list of (x, y) tuples forming the center line.
        outer_wall:      Ordered list of (x, y) tuples for the outer boundary.
        inner_wall:      Ordered list of (x, y) tuples for the inner boundary.
        waypoints:       List of Waypoint objects.
        start_positions: List of StartPosition objects.
        wall_segments:   List of pymunk.Segment shapes for the physics walls.
    """

    # Spatial grid cell size for nearest waypoint queries
    _WP_GRID_SIZE: float = 500.0

    def __init__(self, json_path: str, space: pymunk.Space) -> None:
        # File identity – used to locate the matching trained racing line.
        self.json_path: str = str(json_path)
        self.key: str = Path(json_path).stem
        self.name: str = ""
        self.track_width: float = 100.0
        self.centerline: list[tuple[float, float]] = []
        self.outer_wall: list[tuple[float, float]] = []
        self.inner_wall: list[tuple[float, float]] = []
        self.waypoints: list[Waypoint] = []
        self.start_positions: list[StartPosition] = []
        self.wall_segments: list[pymunk.Segment] = []

        self._load(json_path)
        self._build_physics(space)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self, path: str) -> None:
        """Parse the track JSON file and populate all attributes.

        Damaged entries are skipped rather than fatal: custom tracks get edited
        by hand, tracks received online can arrive truncated, and the editor can
        be interrupted mid-save. Losing one waypoint must not cost the whole
        race — only a track without a usable centerline is beyond repair and
        raises :class:`TrackDataError`.
        """
        from src.core.paths import find_track
        resolved = find_track(str(path))
        if resolved is None:
            raise TrackDataError(f"Streckendatei nicht gefunden: {path}")
        file_path = Path(resolved)

        # Erst als Text lesen, dann prüfen, dann parsen. Der Umweg kostet nichts
        # (die Datei ist auf 1 MB begrenzt) und erlaubt die Tiefenprüfung, bevor
        # json.load in die Rekursion geht.
        #
        # Die Ausnahmeliste ist bewusst breit. Vorher standen hier nur OSError
        # und JSONDecodeError — durch die Maschen fielen RecursionError (tief
        # verschachteltes JSON), UnicodeDecodeError (ungültiges UTF-8) und
        # OverflowError. Alle drei sind über eine geteilte Strecke von jedem
        # Lobbymitglied auslösbar und beendeten das Spiel (Releaseplan H2.2).
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                roh = fh.read()
            if _tiefe_ueberschritten(roh):
                raise TrackDataError(
                    f"Streckendatei zu tief verschachtelt (mehr als {MAX_TIEFE} Ebenen): "
                    f"{file_path}")
            data: Any = json.loads(roh)
        except TrackDataError:
            raise
        except (OSError, ValueError, RecursionError, MemoryError) as exc:
            raise TrackDataError(f"Streckendatei unlesbar: {file_path} ({exc})") from exc

        if not isinstance(data, dict):
            raise TrackDataError(
                f"Streckendatei enthaelt kein Objekt, sondern {type(data).__name__}: {file_path}")

        self.name = str(data.get("name", "Unnamed Track"))
        self.track_width = _as_float(data.get("track_width"), 100.0, minimum=1.0)
        self.background_texture = data.get("background_texture", "grass")

        if self.background_texture == "sand":
            self.background_color = (220, 190, 130)
        elif self.background_texture == "concrete":
            self.background_color = (100, 100, 105)
        elif self.background_texture == "mountain":
            self.background_color = (90, 100, 90)
        else:
            self.background_color = (58, 120, 50)

        self.centerline = _point_list(data.get("centerline"))
        self.outer_wall = _point_list(data.get("outer_wall"))
        self.inner_wall = _point_list(data.get("inner_wall"))

        # Ohne Mittellinie laesst sich weder fahren noch ein Startfeld bauen.
        if len(self.centerline) < 3:
            raise TrackDataError(
                f"Strecke hat keine brauchbare Mittellinie ({len(self.centerline)} Punkte): "
                f"{file_path}")

        self.waypoints = []
        for w in _as_sequence(data.get("waypoints")):
            if not isinstance(w, dict):
                continue
            x = _as_float(w.get("x"), None)
            y = _as_float(w.get("y"), None)
            if x is None or y is None:
                continue
            self.waypoints.append(
                Waypoint(x=x, y=y, is_checkpoint=bool(w.get("is_checkpoint", False))))

        # Build spatial grid for fast nearest-waypoint queries
        self._build_waypoint_grid()

        self.start_positions = []
        for s in _as_sequence(data.get("start_positions")):
            if not isinstance(s, dict):
                continue
            x = _as_float(s.get("x"), None)
            y = _as_float(s.get("y"), None)
            if x is None or y is None:
                continue
            self.start_positions.append(
                StartPosition(x=x, y=y, angle=_as_float(s.get("angle"), 0.0)))
        # Guarantee a full 6-car grid: older tracks stored only 4 slots, so
        # rebuild the staggered grid from the centerline when short.
        from src.core.race_setup import FELD_MAX
        self._ensure_start_grid(FELD_MAX)

    def _ensure_start_grid(self, needed: int) -> None:
        """Top up start_positions to *needed* slots using the centerline."""
        if len(self.start_positions) >= needed or len(self.centerline) < 2:
            return
        from src.track.track_builder import build_start_positions
        slots = build_start_positions(self.centerline, self.track_width, count=needed)
        self.start_positions = [
            StartPosition(x=s["x"], y=s["y"], angle=s["angle"]) for s in slots
        ]

    # ------------------------------------------------------------------
    # Physics
    # ------------------------------------------------------------------

    def _build_physics(self, space: pymunk.Space) -> None:
        """Create pymunk static Segment shapes for outer and inner walls."""
        static_body: pymunk.Body = space.static_body

        self.wall_segments = []

        for wall_points in (self.outer_wall, self.inner_wall):
            if len(wall_points) < 2:
                continue
            # Create segments between consecutive points (closed loop)
            for i in range(len(wall_points)):
                a = wall_points[i]
                b = wall_points[(i + 1) % len(wall_points)]

                segment = pymunk.Segment(static_body, a, b, radius=2.0)
                segment.collision_type = TRACK_WALL_COLLISION_TYPE
                segment.elasticity = 0.3
                segment.friction = 0.7
                space.add(segment)
                self.wall_segments.append(segment)

    # ------------------------------------------------------------------
    # Spatial index for waypoints
    # ------------------------------------------------------------------

    def _build_waypoint_grid(self) -> None:
        """Build a uniform grid index for O(1) nearest waypoint queries."""
        cell_size = self._WP_GRID_SIZE
        self._wp_grid: dict[tuple[int, int], list[int]] = {}
        for i, wp in enumerate(self.waypoints):
            gx = int(wp.x // cell_size)
            gy = int(wp.y // cell_size)
            self._wp_grid.setdefault((gx, gy), []).append(i)

    # Query helpers
    def get_waypoints(self) -> list[Waypoint]:
        """Return all waypoints (including checkpoints)."""
        return list(self.waypoints)

    def get_checkpoints(self) -> list[Waypoint]:
        """Return only waypoints flagged as checkpoints."""
        return [wp for wp in self.waypoints if wp.is_checkpoint]

    def get_start_positions(self) -> list[StartPosition]:
        """Return all grid start positions."""
        return list(self.start_positions)

    def get_nearest_waypoint_index(self, pos: tuple[float, float]) -> int:
        """Find the nearest waypoint index to the given position using spatial grid."""
        if not self.waypoints:
            return 0
        if not hasattr(self, "_wp_grid") or not self._wp_grid:
            self._build_waypoint_grid()

        cell_size = self._WP_GRID_SIZE
        gx = int(pos[0] // cell_size)
        gy = int(pos[1] // cell_size)

        # Search expanding ring of grid cells until we find candidates
        best_idx = 0
        best_dist_sq = float("inf")
        max_ring = 3  # Track width ~300px, grid 500px -> 1 ring covers neighbors

        for ring in range(max_ring + 1):
            for dx in range(-ring, ring + 1):
                for dy in range(-ring, ring + 1):
                    if ring > 0 and abs(dx) != ring and abs(dy) != ring:
                        continue  # Only perimeter cells for rings > 0
                    cell = (gx + dx, gy + dy)
                    if cell not in self._wp_grid:
                        continue
                    for idx in self._wp_grid[cell]:
                        wp = self.waypoints[idx]
                        dx_ = wp.x - pos[0]
                        dy_ = wp.y - pos[1]
                        dist_sq = dx_ * dx_ + dy_ * dy_
                        if dist_sq < best_dist_sq:
                            best_dist_sq = dist_sq
                            best_idx = idx
            # Stop once no unscanned cell could contain a closer waypoint:
            # any point in a further ring is at least (ring * cell_size) away.
            if best_dist_sq != float("inf") and (ring * cell_size) ** 2 >= best_dist_sq:
                break
        return best_idx
