"""Track geometry pipeline — turns editor control points into a playable track.

UI-free on purpose: imported by the in-game tile editor (via tile_track) and the
game/tests, so it must not depend on any UI toolkit. It produces the EXACT JSON
schema the five bundled tracks use (centerline / outer_wall / inner_wall /
waypoints / start_positions), so editor output is indistinguishable from a
hand-made track and works with the AI solver, minimap, lap tracker, etc.
unchanged.

Pipeline:
    control points → closed Catmull-Rom spline → resample @ 20px
    → walls (± width/2 along the centerline normal)
    → waypoints (+ evenly spaced checkpoints)
    → 4 staggered start positions behind the finish line.

The closed spline structurally guarantees "start and end are connected" — there
is no open-track state to get wrong.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.ai.racing_line_solver import _menger_curvature, _centerline_normals

# Geometry constants, matched to the bundled tracks.
CENTERLINE_SPACING: float = 20.0     # px between resampled centerline points
WIDTH_MIN: float = 250.0             # narrowest bundled track (city)
WIDTH_MAX: float = 300.0             # widest bundled track (oval)
MIN_LENGTH: float = 3000.0           # px; shortest bundled track is ~6600px
DEFAULT_CHECKPOINTS: int = 7
START_COUNT: int = 6


def min_radius_for_width(width: float) -> float:
    """Tightest allowed corner radius (px).

    Coupled to width so the inner wall never collapses: at radius = width/2 the
    inner wall degenerates to a point, so we keep a safety band above that. The
    floor of 180px matches the tightest bundled track corners.
    """
    return max(180.0, width / 2.0 + 40.0)


@dataclass
class ValidationError:
    """A single reason a track is not yet saveable."""
    code: str
    message: str
    indices: list[int] = field(default_factory=list)   # centerline indices to highlight


# ---------------------------------------------------------------------------
# Spline + resampling
# ---------------------------------------------------------------------------
def catmull_rom_closed(
    control: list[tuple[float, float]], samples_per_seg: int = 24
) -> list[tuple[float, float]]:
    """Dense points along a closed Catmull-Rom spline through *control*."""
    n = len(control)
    if n < 3:
        return list(control)
    out: list[tuple[float, float]] = []
    for i in range(n):
        p0 = control[(i - 1) % n]
        p1 = control[i]
        p2 = control[(i + 1) % n]
        p3 = control[(i + 2) % n]
        for s in range(samples_per_seg):
            t = s / samples_per_seg
            t2 = t * t
            t3 = t2 * t
            # Standard Catmull-Rom basis (tension 0.5)
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                       + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                       + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    return out


def resample_closed(
    pts: list[tuple[float, float]], spacing: float = CENTERLINE_SPACING
) -> list[tuple[float, float]]:
    """Resample a closed polyline to roughly-equal *spacing* between points."""
    n = len(pts)
    if n < 3:
        return list(pts)
    # Cumulative arc length around the loop.
    seg = [math.dist(pts[i], pts[(i + 1) % n]) for i in range(n)]
    total = sum(seg)
    if total < 1e-6:
        return list(pts)
    count = max(3, int(round(total / spacing)))
    step = total / count

    out: list[tuple[float, float]] = []
    target = 0.0
    acc = 0.0
    i = 0
    for _ in range(count):
        # Walk until the accumulated length passes the target.
        while acc + seg[i] < target and i < n - 1:
            acc += seg[i]
            i += 1
        # Guard against floating drift wrapping past the last segment.
        s = seg[i] if seg[i] > 1e-9 else 1e-9
        frac = (target - acc) / s
        frac = max(0.0, min(1.0, frac))
        a = pts[i]
        b = pts[(i + 1) % n]
        out.append((a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac))
        target += step
    return out


# ---------------------------------------------------------------------------
# Walls / waypoints / starts
# ---------------------------------------------------------------------------
def _signed_area(pts: list[tuple[float, float]]) -> float:
    n = len(pts)
    a = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return 0.5 * a


def build_walls(
    centerline: list[tuple[float, float]], width: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Return (outer_wall, inner_wall), each 1:1 with the centerline.

    Outer = the wall farther from the loop centroid, inner = nearer, so kerb
    rendering (which keys off the centroid) lands on the correct side regardless
    of the centerline's winding direction.
    """
    normals = _centerline_normals(centerline)
    half = width / 2.0
    left = [(c[0] + nlx * half, c[1] + nly * half)
            for c, (nlx, nly) in zip(centerline, normals)]
    right = [(c[0] - nlx * half, c[1] - nly * half)
             for c, (nlx, nly) in zip(centerline, normals)]
    # Positive signed area = CCW → left normal points outward.
    if _signed_area(centerline) > 0.0:
        return left, right    # outer, inner
    return right, left


def build_waypoints(
    centerline: list[tuple[float, float]], num_checkpoints: int = DEFAULT_CHECKPOINTS
) -> list[dict]:
    """Waypoints 1:1 with centerline; evenly spaced checkpoints, index 0 always."""
    n = len(centerline)
    num_cp = max(3, min(num_checkpoints, n))
    cp_indices = {int(round(k * n / num_cp)) % n for k in range(num_cp)}
    cp_indices.add(0)
    return [
        {"x": float(x), "y": float(y), "is_checkpoint": (i in cp_indices)}
        for i, (x, y) in enumerate(centerline)
    ]


def _punkt_rueckwaerts(centerline: list[tuple[float, float]], strecke: float):
    """Der Punkt *strecke* Pixel **entlang der Mittellinie** hinter dem Ziel.

    Gibt ``(x, y, tx, ty)`` — Ort und Fahrtrichtung dort.

    Abgeschritten und nicht extrapoliert: die Mittellinie ist eine geschlossene
    Runde, rueckwaerts von Punkt 0 geht es also ans Ende der Liste und von dort
    weiter nach vorn.
    """
    n = len(centerline)
    rest = max(0.0, strecke)
    i = 0                       # wir stehen auf centerline[0] und gehen zurueck
    while rest > 0.0 and n > 1:
        vorher = centerline[(i - 1) % n]
        hier = centerline[i % n]
        dx, dy = hier[0] - vorher[0], hier[1] - vorher[1]
        laenge = math.hypot(dx, dy)
        if laenge <= 0.0:
            i -= 1
            continue
        if rest <= laenge:
            anteil = rest / laenge
            x = hier[0] - dx * anteil
            y = hier[1] - dy * anteil
            return x, y, dx / laenge, dy / laenge
        rest -= laenge
        i -= 1
        if i <= -n:             # einmal ganz herum: die Strecke ist kuerzer
            break
    hier = centerline[i % n]
    naechster = centerline[(i + 1) % n]
    dx, dy = naechster[0] - hier[0], naechster[1] - hier[1]
    laenge = math.hypot(dx, dy) or 1.0
    return hier[0], hier[1], dx / laenge, dy / laenge


def build_start_positions(
    centerline: list[tuple[float, float]], width: float, count: int = START_COUNT
) -> list[dict]:
    """Versetzte Startaufstellung in zwei Reihen hinter der Ziellinie.

    Abstaende wie gehabt: ``60 + i * 100`` px zurueck, ``±0.2 * width`` zur
    Seite, abwechselnd links und rechts.

    **Entlang der Mittellinie zurueck, nicht geradeaus.** Bis zum 08.08.2026
    wurde von der Tangente am ersten Punkt aus extrapoliert — die Autos standen
    also auf einer Geraden, egal wie die Strecke hinter der Linie verlaeuft.
    Der hinterste Platz liegt 560 px zurueck, eine Editorzelle ist 400 px lang:
    wer direkt hinter der Ziellinie eine Kurve baute, hatte die letzten beiden
    Autos neben der Fahrbahn stehen (gemeldet 08.08.2026). Auch die
    Fahrtrichtung kommt jetzt von der Stelle, an der das Auto wirklich steht,
    und nicht von der Ziellinie — sonst stuende es in der Kurve quer.

    Die mitgelieferten Strecken sind davon unberuehrt: ihre Startplaetze stehen
    fertig in der Streckendatei. Gerechnet wird nur fuer Strecken aus dem
    Editor und dort, wo eine Strecke mehr Plaetze braucht, als sie mitbringt.
    """
    n = len(centerline)
    if n < 2:
        return []
    lateral = 0.2 * width

    starts: list[dict] = []
    for i in range(count):
        back = 60.0 + i * 100.0
        side = 1.0 if i % 2 == 0 else -1.0
        px, py, tx, ty = _punkt_rueckwaerts(centerline, back)
        nlx, nly = -ty, tx                      # linke Normale an dieser Stelle
        x = px + nlx * lateral * side
        y = py + nly * lateral * side
        starts.append({"x": float(x), "y": float(y),
                       "angle": float(math.degrees(math.atan2(ty, tx)))})
    return starts


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _segments_intersect(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])
    return (ccw(p1, p3, p4) != ccw(p2, p3, p4)
            and ccw(p1, p2, p3) != ccw(p1, p2, p4))


def _self_intersects(pts: list[tuple[float, float]]) -> list[int]:
    """Return centerline indices involved in a self-crossing (empty if clean)."""
    n = len(pts)
    hits: list[int] = []
    for i in range(n):
        a1, a2 = pts[i], pts[(i + 1) % n]
        # Skip adjacent segments (they share an endpoint).
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            b1, b2 = pts[j], pts[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                hits.extend([i, j])
    return hits


def validate(centerline: list[tuple[float, float]], width: float) -> list[ValidationError]:
    """Check a resampled centerline against all playability rules."""
    errors: list[ValidationError] = []
    n = len(centerline)
    if n < 8:
        errors.append(ValidationError("too_short", "Strecke hat zu wenige Punkte."))
        return errors

    if not (WIDTH_MIN <= width <= WIDTH_MAX):
        errors.append(ValidationError(
            "width", f"Streckenbreite muss zwischen {WIDTH_MIN:.0f} und {WIDTH_MAX:.0f}px liegen."))

    # Length
    length = sum(math.dist(centerline[i], centerline[(i + 1) % n]) for i in range(n))
    if length < MIN_LENGTH:
        errors.append(ValidationError(
            "length", f"Strecke zu kurz ({length:.0f}px < {MIN_LENGTH:.0f}px)."))

    # Minimum corner radius
    min_r = min_radius_for_width(width)
    tight: list[int] = []
    for i in range(n):
        k = _menger_curvature(centerline[(i - 1) % n], centerline[i], centerline[(i + 1) % n])
        if k > 0.0 and (1.0 / k) < min_r:
            tight.append(i)
    if tight:
        errors.append(ValidationError(
            "radius", f"{len(tight)} Kurve(n) enger als Mindestradius ({min_r:.0f}px).", tight))

    # Self-intersection
    crossing = _self_intersects(centerline)
    if crossing:
        errors.append(ValidationError(
            "self_intersect", "Strecke überschneidet sich selbst.", sorted(set(crossing))))

    return errors


# ---------------------------------------------------------------------------
# High-level definition + JSON
# ---------------------------------------------------------------------------
@dataclass
class TrackDefinition:
    """Everything the editor holds for one track; builds the full game JSON."""
    name: str = "Neue Strecke"
    control_points: list[tuple[float, float]] = field(default_factory=list)
    width: float = 280.0
    background_texture: str = "Plains"
    difficulty: str = "Mittel"
    description: str = ""
    num_checkpoints: int = DEFAULT_CHECKPOINTS

    def centerline(self) -> list[tuple[float, float]]:
        dense = catmull_rom_closed(self.control_points)
        return resample_closed(dense, CENTERLINE_SPACING)

    def validate(self) -> list[ValidationError]:
        if len(self.control_points) < 4:
            return [ValidationError("min_points", "Mindestens 4 Kontrollpunkte nötig.")]
        return validate(self.centerline(), self.width)

    def to_json(self) -> dict:
        """Build the complete game-track dict (raises if invalid)."""
        cl = self.centerline()
        outer, inner = build_walls(cl, self.width)
        return {
            "name": self.name,
            "track_width": float(self.width),
            "difficulty": self.difficulty,
            "description": self.description,
            "background_texture": self.background_texture,
            "centerline": [{"x": float(x), "y": float(y)} for x, y in cl],
            "outer_wall": [{"x": float(x), "y": float(y)} for x, y in outer],
            "inner_wall": [{"x": float(x), "y": float(y)} for x, y in inner],
            "waypoints": build_waypoints(cl, self.num_checkpoints),
            "start_positions": build_start_positions(cl, self.width),
            # Editor-only: lets us reopen and re-edit losslessly. The game ignores it.
            "editor_control_points": [[float(x), float(y)] for x, y in self.control_points],
        }

    @classmethod
    def from_json(cls, data: dict) -> "TrackDefinition":
        """Reconstruct an editable definition from a saved track dict."""
        cps = data.get("editor_control_points")
        if cps:
            control = [(float(x), float(y)) for x, y in cps]
        else:
            # No editor metadata (e.g. a bundled track): downsample the centerline
            # to a workable set of control points.
            cl = [(p["x"], p["y"]) for p in data.get("centerline", [])]
            stride = max(1, len(cl) // 16)
            control = cl[::stride]
        return cls(
            name=data.get("name", "Strecke"),
            control_points=control,
            width=float(data.get("track_width", 280.0)),
            background_texture=data.get("background_texture", "Plains"),
            difficulty=data.get("difficulty", "Mittel"),
            description=data.get("description", ""),
        )
