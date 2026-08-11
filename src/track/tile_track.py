"""Tile-based track draft — data model for the in-game editor.

Grid coordinate system
----------------------
  col, row  integers — grid-cell position (origin anywhere; cells are infinite)
  CELL      400 px   — one cell = one straight segment in world space

Piece types
-----------
  straight   1×1 cell.  Ports on opposite faces.
             rotation 0/2 → horizontal (W ↔ E)
             rotation 1/3 → vertical   (S ↔ N)

  curve      r×r cells, r ∈ {1, 2, 3}.  Quarter-circle arc.
             Arc center sits at one *corner* of the r×r block; radius and port
             offset are both h = (r-0.5)*CELL, which lands the two ports on the
             CENTRES of the block's boundary cell-edges so they mate 1:1 with
             1×1 straights regardless of radius.
             r=1 → radius 200 px, r=2 → 600 px, r=3 → 1000 px  (all ≥ 180 ✓)
             rotation 0 → SW corner arc (S ↔ W ports)
             rotation 1 → NW corner arc (W ↔ N ports)
             rotation 2 → NE corner arc (N ↔ E ports)
             rotation 3 → SE corner arc (E ↔ S ports)

Port face_dir convention
------------------------
  0 = east (+x),  90 = north (+y),  180 = west (−x),  270 = south (−y)
  Two ports connect when their world positions match and face_dirs differ by 180°.
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field

from src.track.track_builder import (
    resample_closed,
    build_walls,
    build_waypoints,
    build_start_positions,
    validate,
    ValidationError,
    CENTERLINE_SPACING,
)

CELL: float = 400.0        # world px per grid unit
_ARC_STEP: float = 10.0   # max arc chord length for polyline sampling
_VERSION = 1

#: Ordner fuer Entwuerfe und veroeffentlichte eigene Strecken.
#:
#: **Als Funktionen und ueber paths.user_path** (04.08.2026). Vorher waren das
#: Konstanten mit relativem Pfad, und ein gepacktes macOS-Bundle setzt das
#: Arbeitsverzeichnis auf sys._MEIPASS — also in das schreibgeschuetzte .app.
#: Der Streckeneditor konnte dort nichts speichern; auf dem Entwicklungsrechner
#: faellt das nie auf, weil Arbeitsverzeichnis und Nutzerverzeichnis dasselbe
#: sind. Gelesen wird weiter ueber paths.track_roots (siehe paths.track_files),
#: mitgelieferte Strecken bleiben also auffindbar.
#:
#: Funktionen und keine Konstanten, weil das Nutzerverzeichnis erst zur Laufzeit
#: feststeht — beim Import hat main._fix_cwd noch nicht gewechselt.
def draft_dir() -> str:
    from src.core.paths import user_path
    return user_path("data", "tracks", "drafts")


def custom_dir() -> str:
    from src.core.paths import user_path
    return user_path("data", "tracks", "custom")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "strecke"


def _dateien_mit_namen(ordner: str, name: str) -> list[str]:
    """Alle JSON-Dateien in *ordner*, deren gespeicherter ``name`` *name* ist.

    Warum nach dem Inhalt gesucht und nicht der Dateiname geraten wird
    (08.08.2026): eine online empfangene Strecke legt ``_save_offer`` unter
    ihrem uebertragenen Dateinamen ab (``Rundkurs (2).json``, ``U Strecke.json``),
    nicht unter ``<slug>.json``. Diese Namen treffen den Slug nie
    (``Rundkurs (2)`` gegen ``rundkurs``, ``U Strecke`` gegen ``u_strecke``),
    ``os.remove`` lief ins Leere und der Fehler wurde verschluckt. Der Name
    steht aber im JSON — also wird danach gesucht.
    """
    treffer: list[str] = []
    try:
        eintraege = sorted(os.listdir(ordner))
    except OSError:
        return treffer
    for eintrag in eintraege:
        if not eintrag.lower().endswith(".json"):
            continue
        pfad = os.path.join(ordner, eintrag)
        try:
            with open(pfad, encoding="utf-8") as f:
                if json.load(f).get("name") == name:
                    treffer.append(pfad)
        except (OSError, ValueError):
            # Unlesbare oder defekte Dateien sind kein Treffer, blockieren aber
            # auch nicht das Loeschen der uebrigen.
            continue
    return treffer


def delete_track(name: str) -> bool:
    """Loescht eine Strecke ganz: Entwurf, veroeffentlichte Kopie und Ghost.

    Gibt zurueck, ob ueberhaupt etwas geloescht wurde. Der Aufrufer darf keinen
    Erfolg melden, wenn nichts gefunden wurde (08.08.2026) — genau das war der
    Fund: der geratene ``<slug>.json`` verfehlte eine online empfangene Strecke,
    und das Spiel meldete trotzdem Erfolg.
    """
    from src.core import ghost
    geloescht = False
    custom = custom_dir()
    for ordner, ist_custom in ((draft_dir(), False), (custom, True)):
        for pfad in _dateien_mit_namen(ordner, name):
            try:
                os.remove(pfad)
            except OSError:
                continue
            geloescht = True
            # Der Ghost-Schluessel kommt aus dem tatsaechlichen Dateinamen, nicht
            # aus dem Slug: bei ``custom/Rundkurs (2).json`` heisst er
            # ``custom/Rundkurs (2)`` — den ``<slug>`` haette er ebenso verfehlt.
            if ist_custom:
                ghost.delete(ghost.track_key(pfad))
    return geloescht


def unpublish_track(name: str) -> None:
    """Remove a track from the game (published copy + ghost) but keep its draft.
    If no draft exists yet, first copy the published json to drafts/ so the
    track stays editable."""
    import shutil
    from src.core import ghost
    slug = _slugify(name)
    custom_path = os.path.join(custom_dir(), f"{slug}.json")
    draft_path = os.path.join(draft_dir(), f"{slug}.json")
    try:
        if os.path.isfile(custom_path) and not os.path.isfile(draft_path):
            os.makedirs(draft_dir(), exist_ok=True)
            shutil.copyfile(custom_path, draft_path)
    except OSError:
        pass
    try:
        if os.path.isfile(custom_path):
            os.remove(custom_path)
    except OSError:
        pass
    ghost.delete(f"custom/{slug}")


# ---------------------------------------------------------------------------
# Port
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Port:
    """Connection point at a piece face. face_dir = outward-normal direction (0/90/180/270)."""
    wx: float
    wy: float
    face_dir: int

    def connects_to(self, other: "Port") -> bool:
        return (
            abs(self.wx - other.wx) < 0.5
            and abs(self.wy - other.wy) < 0.5
            and (self.face_dir + 180) % 360 == other.face_dir
        )


# ---------------------------------------------------------------------------
# Piece
# ---------------------------------------------------------------------------
@dataclass
class Piece:
    """One track tile on the grid."""
    kind: str           # "straight" | "curve"
    col: int
    row: int
    rotation: int       # 0–3
    radius_cells: int = 1   # only meaningful for "curve"

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    def _cell_origin(self) -> tuple[float, float]:
        """World SW corner of this piece's bounding box."""
        return (self.col * CELL, self.row * CELL)

    def size(self) -> int:
        """Grid-cell side length of the bounding box (1 for straight)."""
        return self.radius_cells if self.kind == "curve" else 1

    def ports(self) -> tuple[Port, Port]:
        """The two connection ports in world space."""
        ox, oy = self._cell_origin()
        r = self.size()
        C = CELL
        h = (r - 0.5) * C          # port offset = arc radius; lands on edge-centres

        if self.kind == "straight":
            if self.rotation % 2 == 0:      # horizontal
                return (
                    Port(ox, oy + C / 2, 180),        # W face
                    Port(ox + C, oy + C / 2, 0),       # E face
                )
            else:                            # vertical
                return (
                    Port(ox + C / 2, oy, 270),         # S face
                    Port(ox + C / 2, oy + C, 90),      # N face
                )

        # curve — ports at distance h from the arc-centre corner
        if self.rotation == 0:   # SW corner arc
            return (
                Port(ox + h, oy, 270),                 # S face
                Port(ox, oy + h, 180),                 # W face
            )
        elif self.rotation == 1: # NW corner arc
            return (
                Port(ox, oy + r * C - h, 180),         # W face
                Port(ox + h, oy + r * C, 90),          # N face
            )
        elif self.rotation == 2: # NE corner arc
            return (
                Port(ox + r * C - h, oy + r * C, 90),  # N face
                Port(ox + r * C, oy + r * C - h, 0),   # E face
            )
        else:                    # rot 3: SE corner arc
            return (
                Port(ox + r * C, oy + h, 0),           # E face
                Port(ox + r * C - h, oy, 270),         # S face
            )

    def _arc_center(self) -> tuple[float, float]:
        ox, oy = self._cell_origin()
        r = self.size()
        C = CELL
        if self.rotation == 0:
            return (ox, oy)                  # SW corner
        elif self.rotation == 1:
            return (ox, oy + r * C)          # NW corner
        elif self.rotation == 2:
            return (ox + r * C, oy + r * C)  # NE corner
        else:
            return (ox + r * C, oy)          # SE corner

    def centerline_points(self, entry_port: Port) -> list[tuple[float, float]]:
        """World points from entry_port to the exit port.

        The entry_port position itself is NOT included (caller already has it).
        The exit port position IS the last returned point.
        """
        p0, p1 = self.ports()
        # Which of our ports is the entry?
        if abs(p0.wx - entry_port.wx) < 0.5 and abs(p0.wy - entry_port.wy) < 0.5:
            exit_port = p1
        else:
            exit_port = p0

        if self.kind == "straight":
            return [(exit_port.wx, exit_port.wy)]

        # Curve: sample the quarter-circle arc
        cx, cy = self._arc_center()
        radius = (self.radius_cells - 0.5) * CELL
        a_entry = math.atan2(entry_port.wy - cy, entry_port.wx - cx)
        a_exit  = math.atan2(exit_port.wy  - cy, exit_port.wx  - cx)

        # Shortest arc (≈ ±π/2); sign gives CCW (+) or CW (−).
        diff = (a_exit - a_entry) % (2 * math.pi)
        if diff > math.pi:
            diff -= 2 * math.pi

        arc_len = abs(radius * diff)
        n_steps = max(4, int(arc_len / _ARC_STEP) + 1)
        return [
            (cx + radius * math.cos(a_entry + diff * i / n_steps),
             cy + radius * math.sin(a_entry + diff * i / n_steps))
            for i in range(1, n_steps + 1)
        ]

    def occupies(self) -> set[tuple[int, int]]:
        """All grid cells occupied by this piece."""
        s = self.size()
        return {(self.col + dc, self.row + dr) for dc in range(s) for dr in range(s)}

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "col": self.col,
            "row": self.row,
            "rotation": self.rotation,
            "radius_cells": self.radius_cells,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Piece":
        return cls(
            kind=d["kind"],
            col=int(d["col"]),
            row=int(d["row"]),
            rotation=int(d.get("rotation", 0)),
            radius_cells=int(d.get("radius_cells", 1)),
        )


# ---------------------------------------------------------------------------
# TileTrackDraft
# ---------------------------------------------------------------------------
@dataclass
class TileTrackDraft:
    """An in-progress or complete tile-based track."""
    name: str = "Neue Strecke"
    width: float = 260.0
    background_texture: str = "Plains"
    difficulty: str = "Mittel"
    description: str = ""
    pieces: list[Piece] = field(default_factory=list)
    start_piece_idx: int = 0
    version: int = _VERSION

    # ------------------------------------------------------------------
    # Port connectivity graph
    # ------------------------------------------------------------------
    def _port_key(self, port: Port) -> tuple[int, int, int]:
        return (round(port.wx), round(port.wy), port.face_dir)

    def connections(self) -> dict[tuple[int, int], tuple[int, int] | None]:
        """Map (piece_idx, port_idx) → (piece_idx, port_idx) or None if open."""
        port_map: dict[tuple[int, int, int], tuple[int, int]] = {}
        for pi, piece in enumerate(self.pieces):
            for qi, port in enumerate(piece.ports()):
                port_map[self._port_key(port)] = (pi, qi)

        result: dict[tuple[int, int], tuple[int, int] | None] = {}
        for pi, piece in enumerate(self.pieces):
            for qi, port in enumerate(piece.ports()):
                opp_face = (port.face_dir + 180) % 360
                opp_key = (round(port.wx), round(port.wy), opp_face)
                result[(pi, qi)] = port_map.get(opp_key)
        return result

    def open_ports(self) -> list[Port]:
        """Ports that have no matching partner."""
        conns = self.connections()
        result: list[Port] = []
        for (pi, qi), conn in conns.items():
            if conn is None:
                result.append(self.pieces[pi].ports()[qi])
        return result

    def start_straight_ok(self) -> bool:
        """Start/finish line needs a straight run to accelerate on.

        Requires the start piece to be a straight AND the piece feeding into it
        (connected at port 0) to also be a straight — so cars launch onto tarmac.
        """
        if not self.pieces:
            return False
        si = self.start_piece_idx % len(self.pieces)
        sp = self.pieces[si]
        if sp.kind != "straight":
            return False
        conn = self.connections().get((si, 0))
        if conn is None:
            return False
        npi, _ = conn
        return self.pieces[npi].kind == "straight"

    def is_closed_loop(self) -> bool:
        """True iff every port is connected and the pieces form one closed loop."""
        if len(self.pieces) < 2:
            return False
        conns = self.connections()
        if any(v is None for v in conns.values()):
            return False
        try:
            self._traverse(conns)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Loop traversal
    # ------------------------------------------------------------------
    def _traverse(
        self, conns: dict[tuple[int, int], tuple[int, int] | None] | None = None
    ) -> list[tuple[float, float]]:
        """Walk all pieces in loop order; return raw centerline polyline."""
        if not self.pieces:
            raise ValueError("No pieces to traverse.")
        if conns is None:
            conns = self.connections()

        start_pi = self.start_piece_idx % len(self.pieces)
        start_piece = self.pieces[start_pi]
        start_port = start_piece.ports()[0]

        # First point = entry port of the start piece
        pts: list[tuple[float, float]] = [(start_port.wx, start_port.wy)]
        cur_pi, cur_port_idx = start_pi, 0
        visited: set[int] = {cur_pi}

        for _ in range(len(self.pieces) + 1):
            cur_piece = self.pieces[cur_pi]
            entry_port = cur_piece.ports()[cur_port_idx]
            pts.extend(cur_piece.centerline_points(entry_port))

            exit_port_idx = 1 - cur_port_idx
            conn = conns.get((cur_pi, exit_port_idx))
            if conn is None:
                raise ValueError(f"Open port at piece {cur_pi}, port {exit_port_idx}.")

            next_pi, next_port_idx = conn
            if next_pi == start_pi:
                break
            if next_pi in visited:
                raise ValueError("Loop visits a piece twice (figure-8?).")
            visited.add(next_pi)
            cur_pi, cur_port_idx = next_pi, next_port_idx
        else:
            raise ValueError("Traversal did not close after visiting all pieces.")

        # Drop last point if it duplicates pts[0] (the closure seam).
        if len(pts) > 1 and abs(pts[-1][0] - pts[0][0]) < 0.5 and abs(pts[-1][1] - pts[0][1]) < 0.5:
            pts.pop()
        return pts

    # ------------------------------------------------------------------
    # Geometry export
    # ------------------------------------------------------------------
    def to_centerline(self) -> list[tuple[float, float]]:
        """Traversed loop → resampled at CENTERLINE_SPACING (20 px)."""
        return resample_closed(self._traverse(), CENTERLINE_SPACING)

    def validate_game(self) -> list[ValidationError]:
        """Full validation. Empty list = safe to publish."""
        if not self.is_closed_loop():
            return [ValidationError("open_loop", "Strecke ist noch nicht geschlossen.")]
        errs = validate(self.to_centerline(), self.width)
        if not self.start_straight_ok():
            errs.append(ValidationError(
                "start_straight", "Start/Ziel braucht eine Gerade zum Beschleunigen."))
        return errs

    def to_game_json(self) -> dict:
        """Build the complete game-compatible track dict.

        Raises ValueError if the loop is not closed.
        The dict also embeds editor_tiles so the track stays re-editable.
        """
        cl = self.to_centerline()
        outer, inner = build_walls(cl, self.width)
        return {
            "name": self.name,
            "track_width": float(self.width),
            "difficulty": self.difficulty,
            "description": self.description,
            "background_texture": self.background_texture,
            "centerline":    [{"x": float(x), "y": float(y)} for x, y in cl],
            "outer_wall":    [{"x": float(x), "y": float(y)} for x, y in outer],
            "inner_wall":    [{"x": float(x), "y": float(y)} for x, y in inner],
            "waypoints":     build_waypoints(cl),
            "start_positions": build_start_positions(cl, self.width),
            "editor_tiles":  self.to_draft_dict(),   # roundtrip: re-editable
        }

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_draft_dict(self) -> dict:
        return {
            "version": self.version,
            "name": self.name,
            "width": float(self.width),
            "background_texture": self.background_texture,
            "difficulty": self.difficulty,
            "description": self.description,
            "start_piece_idx": self.start_piece_idx,
            "pieces": [p.to_dict() for p in self.pieces],
        }

    @classmethod
    def from_draft_dict(cls, d: dict) -> "TileTrackDraft":
        pieces = [Piece.from_dict(p) for p in d.get("pieces", [])]
        return cls(
            name=d.get("name", "Strecke"),
            width=float(d.get("width", 260.0)),
            background_texture=d.get("background_texture", "Plains"),
            difficulty=d.get("difficulty", "Mittel"),
            description=d.get("description", ""),
            pieces=pieces,
            start_piece_idx=int(d.get("start_piece_idx", 0)),
            version=int(d.get("version", _VERSION)),
        )

    # ------------------------------------------------------------------
    # File I/O  (no user dialogs — everything happens in the background)
    # ------------------------------------------------------------------
    def save_draft(self, slug: str | None = None) -> str:
        """Persist WIP to data/tracks/drafts/<slug>.json. Returns the path."""
        os.makedirs(draft_dir(), exist_ok=True)
        slug = slug or _slugify(self.name)
        path = os.path.join(draft_dir(), f"{slug}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_draft_dict(), f, indent=2, ensure_ascii=False)
        return path

    @property
    def is_published(self) -> bool:
        if not self.name:
            return False
        slug = _slugify(self.name)
        return os.path.exists(os.path.join(custom_dir(), f"{slug}.json"))

    def publish(self, slug: str | None = None) -> tuple[str, list[ValidationError]]:
        """Validate then export to data/tracks/custom/. Returns (path, errors).

        On success: errors is empty and the track appears in the menu immediately
        (track_select_state.py scans custom/ dynamically).
        On failure: path is "" and errors lists what needs fixing.
        """
        errs = self.validate_game()
        if errs:
            return ("", errs)
        os.makedirs(custom_dir(), exist_ok=True)
        slug = slug or _slugify(self.name)
        path = os.path.join(custom_dir(), f"{slug}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_game_json(), f, indent=2, ensure_ascii=False)
        self.save_draft(slug)  # keep draft in sync
        return (path, [])

    @classmethod
    def load_draft(cls, path: str) -> "TileTrackDraft":
        with open(path, encoding="utf-8") as f:
            return cls.from_draft_dict(json.load(f))

    @classmethod
    def load_from_custom(cls, path: str) -> "TileTrackDraft":
        """Re-open a published track for editing (reads the embedded editor_tiles)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        tiles = data.get("editor_tiles")
        if not tiles:
            raise ValueError(f"No editor_tiles in {path!r} — not editable.")
        return cls.from_draft_dict(tiles)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def new_with_start(cls) -> "TileTrackDraft":
        """Neuer Entwurf mit einer vorgelegten Start-/Ziel-Geraden.

        Die Start-/Ziellinie sitzt am Westtor (Port 0) des Bauteils mit dem
        Index ``start_piece_idx``; die Autos stehen **dahinter**, also westlich
        davon.

        **Zwei Gerade dahinter, nicht eine** (08.08.2026). Der hinterste
        Startplatz liegt ``60 + 5 * 100 = 560`` px hinter der Linie, eine Zelle
        ist ``CELL = 400`` px lang. Mit nur einer Geraden standen die letzten
        beiden Autos jenseits des Bauteils — setzte jemand dort eine Kurve,
        starteten sie in der Kurve (so gemeldet). ``build_start_positions``
        schreitet die Mittellinie inzwischen zurueck und haelt sie auch dann auf
        der Bahn; die zweite Gerade sorgt dafuer, dass der Normalfall gar nicht
        erst dorthin kommt.

        Der Name ist uebersetzt: er steht als Vorgabe im Namensfeld und wandert
        von dort in die Datei. Fest deutsch stand dort auch auf Englisch „Neue
        Strecke" (ebenfalls am 08.08.2026 gemeldet).
        """
        from src.core.i18n import tr

        anlauf2 = Piece(kind="straight", col=3, row=5, rotation=0)
        anlauf1 = Piece(kind="straight", col=4, row=5, rotation=0)
        start   = Piece(kind="straight", col=5, row=5, rotation=0)
        rechts  = Piece(kind="straight", col=6, row=5, rotation=0)
        return cls(name=tr("Neue Strecke"),
                   pieces=[anlauf2, anlauf1, start, rechts],
                   start_piece_idx=2)

    # ------------------------------------------------------------------
    # Grid helpers (for the editor UI)
    # ------------------------------------------------------------------
    def occupied_cells(self) -> set[tuple[int, int]]:
        """All grid cells taken by any piece."""
        cells: set[tuple[int, int]] = set()
        for p in self.pieces:
            cells |= p.occupies()
        return cells

    def piece_at(self, col: int, row: int) -> int | None:
        """Index of the piece occupying (col, row), or None."""
        for i, p in enumerate(self.pieces):
            if (col, row) in p.occupies():
                return i
        return None
