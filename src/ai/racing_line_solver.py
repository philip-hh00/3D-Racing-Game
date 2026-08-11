"""Geometric racing-line solver – computes a fast line for *any* track at load.

No training, no per-track data files: given a track's center polyline and its
width, an elastic-band / curvature-minimisation pass produces a smooth,
apex-cutting line that stays inside the drivable corridor. It runs in a few
milliseconds at track load and therefore works on hand-made and (future)
user-designed tracks alike.

Method (minimum-curvature within a corridor):
    1. Start the line on the centerline.
    2. Repeatedly pull every point toward the midpoint of its two neighbours
       (Laplacian smoothing — this is the "make the line straight / minimise
       curvature" force).
    3. After each pull, clamp the point back into the corridor (track half-width
       minus the car's half-width and a safety margin), measured along the fixed
       centerline normal. On straights the smoothing changes nothing; in corners
       it pulls the line to the inside until the clamp stops it at the apex,
       which is exactly the racing line.

The result also carries per-point curvature, which the speed-profile stage
(:mod:`src.ai.speed_profile`) turns into cornering speed limits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RacingLineGeometry:
    """A solved racing line plus the geometry the speed profile needs."""

    points: list[tuple[float, float]]      # absolute racing-line points (closed loop)
    offsets: list[float]                   # signed lateral offset from the centerline
    normals: list[tuple[float, float]]     # centerline left-normal at each index
    curvature: list[float]                 # 1/radius (px^-1), unsigned, at each point
    signed_curvature: list[float]          # +ve = line turns left (CCW)
    seg_len: list[float]                   # distance from point i to i+1
    half_corridor: float                   # max |offset| that was allowed

    @property
    def length(self) -> float:
        return sum(self.seg_len)

    def max_curvature(self) -> float:
        return max(self.curvature) if self.curvature else 0.0


class SolvedRacingLine:
    """Per-waypoint lateral offset + target speed the AIController reads.

    Indexed by waypoint/centerline index (the two are 1:1 on every track), so it
    plugs straight into :meth:`AIController._racing_line_point` (``offset_at``)
    and the controller's speed-profile branch (``speed_at``). Built from the
    solver geometry and a per-vehicle :mod:`src.ai.speed_profile`.
    """

    def __init__(
        self,
        offsets: list[float],
        speeds: list[float],
        signed_curvature: list[float] | None = None,
        points: list[tuple[float, float]] | None = None,
    ) -> None:
        self.offsets = list(offsets)
        self.speeds = list(speeds)
        self.signed_curvature = list(signed_curvature) if signed_curvature else None
        self.points = list(points) if points else None
        self.n = len(self.offsets)

    def offset_at(self, idx: int) -> float:
        return self.offsets[idx % self.n] if self.n else 0.0

    def speed_at(self, idx: int) -> float:
        return self.speeds[idx % self.n] if self.speeds else 0.0

    def curvature_at(self, idx: int) -> float:
        """Signed curvature (1/px, +ve = left) of the line, 0 if unavailable."""
        if not self.signed_curvature:
            return 0.0
        return self.signed_curvature[idx % len(self.signed_curvature)]


def _centerline_normals(center: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Unit left-normal at each centerline point (from the local tangent)."""
    n = len(center)
    normals: list[tuple[float, float]] = []
    for i in range(n):
        ax, ay = center[(i - 1) % n]
        bx, by = center[(i + 1) % n]
        tx, ty = bx - ax, by - ay
        length = math.hypot(tx, ty) or 1.0
        tx, ty = tx / length, ty / length
        normals.append((-ty, tx))  # +90° → left of travel direction
    return normals


def _menger_curvature(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    """Curvature (1/radius) of the circle through three points; 0 if collinear."""
    abx, aby = b[0] - a[0], b[1] - a[1]
    acx, acy = c[0] - a[0], c[1] - a[1]
    area2 = abs(abx * acy - aby * acx)          # 2 × triangle area
    d_ab = math.hypot(abx, aby)
    d_bc = math.hypot(c[0] - b[0], c[1] - b[1])
    d_ca = math.hypot(a[0] - c[0], a[1] - c[1])
    denom = d_ab * d_bc * d_ca
    if denom < 1e-9:
        return 0.0
    return 2.0 * area2 / denom                  # 4·area / (|AB||BC||CA|)


def compute_racing_line(
    center: list[tuple[float, float]],
    track_width: float,
    car_width: float = 28.0,
    margin: float = 16.0,
    iterations: int = 600,
    weight: float = 0.35,
    corner_pull: float = 0.45,
    tight_radius: float = 130.0,
    outside_factor: float = 0.5,
) -> RacingLineGeometry:
    """Solve a minimum-curvature racing line for a closed center polyline.

    Args:
        center:       Ordered centerline points forming a closed loop.
        track_width:  Full drivable width (px).
        car_width:    Car body width (px) – keeps the whole car off the wall.
        margin:       Extra safety gap to the wall (px).
        iterations:   Smoothing iterations (a few hundred converges; cheap).
        weight:       Per-iteration pull strength toward the neighbour midpoint.
        corner_pull:  How much to shrink the usable corridor in tight corners
                      (0 = full apex; 0.45 = keep the line ~55 % off the wall in
                      the tightest bends so the car has clearance there).
        tight_radius: Centerline radius (px) at/below which a corner counts as
                      fully "tight" for the corner_pull reduction.
        outside_factor: How much to pull in the outside corridor in tight corners
                      relative to corner_pull. 0 = fully open, 1 = symmetric.
    """
    n = len(center)
    if n < 3:
        normals = _centerline_normals(center) if center else []
        z = [0.0] * n
        return RacingLineGeometry(list(center), z, normals, z, list(z), list(z), 0.0)

    normals = _centerline_normals(center)
    half_corridor = max(4.0, track_width / 2.0 - car_width / 2.0 - margin)

    # Per-point corridor: tighter on the curve inside where the centerline bends hard,
    # so the racing line can't dive all the way to the inside wall in a sharp corner,
    # but left more open on the curve outside to allow the vehicle to go wide (Out-In-Out).
    tight_kappa = 1.0 / max(1.0, tight_radius)
    final_limits: list[tuple[float, float]] = []
    lookahead = 22
    lookback = 15
    outside_factor = 0.5
    
    for i in range(n):
        # 1. Local curvature limits (baseline apex safety)
        a = center[(i - 1) % n]
        b = center[i]
        c = center[(i + 1) % n]
        k_self = _menger_curvature(a, b, c)
        cross_self = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        
        tight_self = min(1.0, k_self / tight_kappa) ** 2
        local_pull = corner_pull * 0.5  # allow cutting slightly closer than raw slider value
        
        tightened_inside = half_corridor * (1.0 - local_pull * tight_self)
        tightened_outside = half_corridor * (1.0 - local_pull * outside_factor * tight_self)
        
        if cross_self >= 0.0:  # Left turn
            lim_left = tightened_inside
            lim_right = tightened_outside
        else:                  # Right turn
            lim_left = tightened_outside
            lim_right = tightened_inside
            
        # 2. Lookahead limits (smooth Out-In-Out entry prep)
        max_left_prep = 0.0
        max_right_prep = 0.0
        
        for dist in range(3, lookahead):
            idx = (i + dist) % n
            ax = center[(idx - 1) % n]
            bx = center[idx]
            cx = center[(idx + 1) % n]
            k_ahead = _menger_curvature(ax, bx, cx)
            cross_ahead = (bx[0] - ax[0]) * (cx[1] - bx[1]) - (bx[1] - ax[1]) * (cx[0] - bx[0])
            
            # Triangular weight peaking at dist = 10
            w = max(0.0, 1.0 - abs(dist - 10.0) / 9.0)
            tight_ahead = min(1.0, k_ahead / tight_kappa) ** 2 * w
            
            if cross_ahead >= 0.0:
                max_left_prep = max(max_left_prep, tight_ahead)
            else:
                max_right_prep = max(max_right_prep, tight_ahead)
                
        # Apply smooth lookahead restrictions to block the inside before a curve
        # scaled dynamically by corridor width (disabled on very narrow tracks like Mountain)
        corridor_scale = max(0.0, min(1.0, (half_corridor - 50.0) / 25.0))
        entry_push = 0.25 * corridor_scale
        lim_left *= (1.0 - entry_push * max_left_prep)
        lim_right *= (1.0 - entry_push * max_right_prep)
        
        # 3. Centering on straights between curves
        is_straight = (k_self < 0.0008)
        has_curve_before = False
        for j in range(3, lookback):
            idx = (i - j) % n
            ax = center[(idx - 1) % n]
            bx = center[idx]
            cx = center[(idx + 1) % n]
            if _menger_curvature(ax, bx, cx) > 0.0012:
                has_curve_before = True
                break
                
        has_curve_after = False
        for j in range(3, lookahead):
            idx = (i + j) % n
            ax = center[(idx - 1) % n]
            bx = center[idx]
            cx = center[(idx + 1) % n]
            if _menger_curvature(ax, bx, cx) > 0.0012:
                has_curve_after = True
                break
                
        if is_straight and has_curve_before and has_curve_after:
            # Centering: scale limits down symmetrically (relaxed on narrow tracks)
            centering_limit = 0.70 + 0.30 * (1.0 - corridor_scale)
            lim_left = min(lim_left, half_corridor * centering_limit)
            lim_right = min(lim_right, half_corridor * centering_limit)
            
        # S-Curve Late Apex Detection (Option C)
        if k_self > 0.0010:
            my_sign = 1.0 if cross_self >= 0.0 else -1.0
            for dist in range(12, 32):
                idx = (i + dist) % n
                ax = center[(idx - 1) % n]
                bx = center[idx]
                cx = center[(idx + 1) % n]
                k_ahead = _menger_curvature(ax, bx, cx)
                if k_ahead > 0.0010:
                    cross_ahead = (bx[0] - ax[0]) * (cx[1] - bx[1]) - (bx[1] - ax[1]) * (cx[0] - bx[0])
                    ahead_sign = 1.0 if cross_ahead >= 0.0 else -1.0
                    if ahead_sign != my_sign:
                        # Opposing curve detected ahead -> S-curve entry! Tighten inside corridor.
                        if cross_self >= 0.0:
                            lim_left *= 0.60
                        else:
                            lim_right *= 0.60
                        break
            
        final_limits.append((lim_left, lim_right))

    pts: list[tuple[float, float]] = list(center)
    for _ in range(iterations):
        new_pts: list[tuple[float, float]] = [(0.0, 0.0)] * n
        for i in range(n):
            px, py = pts[i]
            ax, ay = pts[(i - 1) % n]
            bx, by = pts[(i + 1) % n]
            
            # Laplacian smoothing target (minimizes curvature)
            mx_lap = 0.5 * (ax + bx)
            my_lap = 0.5 * (ay + by)
            
            # Bi-harmonic smoothing target (minimizes change of curvature / curvature-rate)
            ax2, ay2 = pts[(i - 2) % n]
            bx2, by2 = pts[(i + 2) % n]
            mx_bih = (4.0 * (ax + bx) - (ax2 + bx2)) / 6.0
            my_bih = (4.0 * (ay + by) - (ay2 + by2)) / 6.0
            
            # Blend: 70% Laplacian (minimize curvature), 30% Bi-harmonic (minimize curvature rate)
            mx_target = 0.70 * mx_lap + 0.30 * mx_bih
            my_target = 0.70 * my_lap + 0.30 * my_bih
            
            # Apply weight
            mx = px + (mx_target - px) * weight
            my = py + (my_target - py) * weight
            
            # Clamp into the corridor along the normal.
            cx, cy = center[i]
            nlx, nly = normals[i]
            lim_left, lim_right = final_limits[i]
            off = (mx - cx) * nlx + (my - cy) * nly
            off = max(-lim_right, min(lim_left, off))
            new_pts[i] = (cx + nlx * off, cy + nly * off)
        pts = new_pts

    offsets = [
        (pts[i][0] - center[i][0]) * normals[i][0]
        + (pts[i][1] - center[i][1]) * normals[i][1]
        for i in range(n)
    ]
    curvature = [
        _menger_curvature(pts[(i - 1) % n], pts[i], pts[(i + 1) % n]) for i in range(n)
    ]
    signed_curvature = []
    for i in range(n):
        a, b, c = pts[(i - 1) % n], pts[i], pts[(i + 1) % n]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        sign = 1.0 if cross >= 0.0 else -1.0    # +ve = left / CCW
        signed_curvature.append(curvature[i] * sign)
    seg_len = [math.dist(pts[i], pts[(i + 1) % n]) for i in range(n)]
    return RacingLineGeometry(
        pts, offsets, normals, curvature, signed_curvature, seg_len, half_corridor
    )


def compute_racing_line_optimized(
    center: list[tuple[float, float]],
    track_width: float,
    vehicle_config,
    difficulty=None,
    car_width: float = 28.0,
    margin: float = 16.0,
    progress_callback=None,
) -> RacingLineGeometry:
    """Physics-based trajectory optimizer; falls back to geometric solver on error."""
    try:
        from src.ai.trajectory_optimizer import optimize_trajectory, TrajectoryConfig
        from src.ai.speed_profile import limits_from_config

        grip_usage = getattr(difficulty, "grip_usage", None) if difficulty else None
        brake_conf = getattr(difficulty, "brake_confidence", None) if difficulty else None
        steer_conf = getattr(difficulty, "steer_confidence", None) if difficulty else None

        lim = limits_from_config(vehicle_config, grip_usage=grip_usage,
                                 brake_confidence=brake_conf, steer_confidence=steer_conf)
        tc = TrajectoryConfig(
            a_lat_max=lim.a_lat,
            a_accel_max=lim.a_accel,
            a_brake_max=lim.a_brake,
            v_max=lim.v_max,
            car_width=car_width,
            margin=margin,
            turn_speed=lim.turn_speed,
            turn_safety=lim.turn_safety,
        )
        return optimize_trajectory(center, track_width, tc,
                                   progress_callback=progress_callback)
    except Exception:
        return compute_racing_line(center, track_width, car_width=car_width,
                                   margin=margin)
