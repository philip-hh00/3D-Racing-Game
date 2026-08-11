"""TrackRenderer - pre-renders the race track to a large surface.

The renderer creates an off-screen pygame.Surface containing:
- Green grass background
- Gray asphalt road surface (filled polygon between outer and inner walls)
- Red/white kerb strips along the walls
- White dashed center line

The surface is blitted to the screen each frame with a camera offset,
avoiding per-frame polygon drawing.
"""
from __future__ import annotations

import math
from typing import Sequence

import pygame

from src.track.track import Track, StartPosition
from src.core.settings import SCREEN_HEIGHT


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------

_COL_GRASS: tuple[int, int, int] = (58, 120, 50)
_COL_ASPHALT: tuple[int, int, int] = (70, 70, 78)
_COL_ASPHALT_EDGE: tuple[int, int, int] = (55, 55, 62)
_COL_CENTERLINE: tuple[int, int, int] = (240, 240, 240)
_COL_KERB_RED: tuple[int, int, int] = (200, 40, 40)
_COL_KERB_WHITE: tuple[int, int, int] = (240, 240, 240)
_COL_WALL_LINE: tuple[int, int, int] = (45, 45, 50)

# Kerb geometry
_KERB_WIDTH: float = 8.0
_KERB_SEGMENT_LEN: float = 24.0  # length of each red/white alternation

# Center-line dashes
_DASH_LENGTH: int = 20
_GAP_LENGTH: int = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _offset_polygon(
    points: list[tuple[float, float]],
    offset: float,
    center: tuple[float, float],
) -> list[tuple[float, float]]:
    """Offset a closed polygon outward (positive) or inward (negative)
    relative to *center*.  Uses a simple radial approach which works well
    for convex-ish shapes like our oval.
    """
    cx, cy = center
    result: list[tuple[float, float]] = []
    for px, py in points:
        dx = px - cx
        dy = py - cy
        dist = math.hypot(dx, dy)
        if dist == 0:
            result.append((px, py))
            continue
        nx = dx / dist
        ny = dy / dist
        result.append((px + nx * offset, py + ny * offset))
    return result


def _compute_bounds(
    points: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return (min_x, min_y, max_x, max_y) bounding box of *points*."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _segment_length(
    a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Euclidean distance between two 2-D points."""
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _lerp_point(
    a: tuple[float, float], b: tuple[float, float], t: float
) -> tuple[float, float]:
    """Linearly interpolate between *a* and *b* by factor *t* ∈ [0, 1]."""
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _normal_outward(
    a: tuple[float, float],
    b: tuple[float, float],
    center: tuple[float, float],
) -> tuple[float, float]:
    """Return the unit normal of segment a→b that points away from *center*."""
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return (0.0, 0.0)
    # Two candidate normals
    n1 = (-dy / length, dx / length)
    n2 = (dy / length, -dx / length)
    # Pick the one pointing away from center
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    dot1 = (mid[0] + n1[0] - center[0]) ** 2 + (
        mid[1] + n1[1] - center[1]
    ) ** 2
    dot2 = (mid[0] + n2[0] - center[0]) ** 2 + (
        mid[1] + n2[1] - center[1]
    ) ** 2
    return n1 if dot1 > dot2 else n2


# ---------------------------------------------------------------------------
# TrackRenderer
# ---------------------------------------------------------------------------


class TrackRenderer:
    """Pre-renders a :class:`Track` to a pygame surface for fast blitting.

    The surface is built once in ``__init__`` and then simply blitted each
    frame via :meth:`render`.

    Args:
        track: A loaded :class:`Track` instance.
    """

    def __init__(self, track: Track) -> None:
        self._track: Track = track
        self._surface: pygame.Surface = pygame.Surface((0, 0))
        # World-space origin of the pre-rendered surface
        self._origin_x: float = 0.0
        self._origin_y: float = 0.0
        self.grid_font: pygame.font.Font = pygame.font.Font(None, 40)

        self._build_surface()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        screen: pygame.Surface,
        camera_offset: tuple[float, float] | pygame.Vector2,
    ) -> None:
        """Blit the pre-rendered track surface to *screen*.

        Args:
            screen:        The main display surface.
            camera_offset: Camera offset as (offset_x, offset_y).  Obtained
                           from ``Camera.offset``.
        """
        blit_x = self._origin_x + camera_offset[0]
        blit_y = self._origin_y + camera_offset[1]
        screen.blit(self._surface, (blit_x, blit_y))

    # ------------------------------------------------------------------
    # Surface construction
    # ------------------------------------------------------------------

    def _build_surface(self) -> None:
        """Create the pre-rendered track surface."""
        track = self._track
        if not track.outer_wall or not track.inner_wall:
            return

        # Compute bounding box with generous margin for kerbs / anti-aliasing / camera viewport bounds
        margin: float = 1200.0
        all_points = track.outer_wall + track.inner_wall
        min_x, min_y, max_x, max_y = _compute_bounds(all_points)
        min_x -= margin
        min_y -= margin
        max_x += margin
        max_y += margin

        self._origin_x = min_x
        self._origin_y = SCREEN_HEIGHT - max_y

        width = int(max_x - min_x)
        height = int(max_y - min_y)

        surf = pygame.Surface((width, height))
        
        # Load and scale background image to cover the entire track area
        textured = False
        texture_name = getattr(track, "background_texture", "grass")
        texture_path = f"data/textures/{texture_name}.png"
        try:
            texture_surf = pygame.image.load(texture_path).convert()
            # Stretch the single background image to cover the entire track surface
            from src.core import gfx
            scaled_bg = gfx.scale(texture_surf, (width, height))
            surf.blit(scaled_bg, (0, 0))
            textured = True
        except Exception as e:
            print(f"[TrackRenderer] Could not load background image {texture_path}: {e}")
            
        if not textured:
            # Fallbacks
            if texture_name == "sand":
                bg_color = (220, 190, 130)
            elif texture_name == "concrete":
                bg_color = (100, 100, 105)
            elif texture_name == "mountain":
                bg_color = (90, 100, 90)
            else:
                bg_color = _COL_GRASS
            surf.fill(bg_color)

        # Helper: world→surface coordinates (Y-flipped to match Pygame screen space)
        def _ws(pt: tuple[float, float]) -> tuple[float, float]:
            return (pt[0] - min_x, max_y - pt[1])

        def _ws_list(
            pts: Sequence[tuple[float, float]],
        ) -> list[tuple[float, float]]:
            return [_ws(p) for p in pts]

        # --- 1. Road surface (filled segment-by-segment) ---
        outer_ws = _ws_list(track.outer_wall)
        inner_ws = _ws_list(track.inner_wall)

        # Draw asphalt road segments to leave the infield textured
        n = len(outer_ws)
        for i in range(n):
            quad = [
                outer_ws[i],
                outer_ws[(i + 1) % n],
                inner_ws[(i + 1) % n],
                inner_ws[i]
            ]
            pygame.draw.polygon(surf, _COL_ASPHALT, quad)

        # --- 2. Subtle asphalt edge shading ---
        # Draw slightly darker line along outer edge for depth
        pygame.draw.polygon(surf, _COL_ASPHALT_EDGE, outer_ws, width=3)
        pygame.draw.polygon(surf, _COL_ASPHALT_EDGE, inner_ws, width=3)

        # --- 3. Kerb strips ---
        # Compute track center for normal direction
        cx = sum(p[0] for p in track.centerline) / len(track.centerline)
        cy = sum(p[1] for p in track.centerline) / len(track.centerline)
        center = (cx, cy)

        self._draw_kerbs(surf, track.outer_wall, center, min_x, max_y, outward=True)
        self._draw_kerbs(surf, track.inner_wall, center, min_x, max_y, outward=False)

        # --- 4. Wall boundary lines ---
        pygame.draw.aalines(surf, _COL_WALL_LINE, True, outer_ws)
        pygame.draw.aalines(surf, _COL_WALL_LINE, True, inner_ws)

        # --- 5. Dashed center line ---
        self._draw_dashed_centerline(surf, track.centerline, min_x, max_y)

        # --- 6. Chequered start/finish line ---
        if track.centerline and track.start_positions:
            self._draw_chequered_finish_line(surf, track.centerline[0], track.start_positions[0].angle, track.track_width, min_x, max_y)

        # --- 7. Starting grid markings ---
        self._draw_starting_grid(surf, track.start_positions, min_x, max_y)

        self._surface = surf

    # ------------------------------------------------------------------
    # Kerb drawing
    # ------------------------------------------------------------------

    def _draw_kerbs(
        self,
        surf: pygame.Surface,
        wall_points: list[tuple[float, float]],
        center: tuple[float, float],
        ox: float,
        oy: float,
        *,
        outward: bool,
    ) -> None:
        """Draw alternating red/white kerb strips along a wall polygon.

        Args:
            surf:        Target surface.
            wall_points: Wall polygon points in world space.
            center:      Approximate center of the track (for normal direction).
            ox, oy:      World-space origin offset of the surface.
            outward:     If True, kerbs are drawn on the outside of the wall;
                         otherwise on the inside (towards the road).
        """
        accumulated: float = 0.0
        colour_index: int = 0
        colours = [_COL_KERB_RED, _COL_KERB_WHITE]

        n = len(wall_points)
        if n < 3:
            return

        # Dynamically determine the winding order of the wall polygon
        # (Y is up in world space)
        area = 0.0
        for i in range(n):
            x1, y1 = wall_points[i]
            x2, y2 = wall_points[(i + 1) % n]
            area += (x2 - x1) * (y2 + y1)
        is_cw = area > 0.0

        for i in range(n):
            a = wall_points[i]
            b = wall_points[(i + 1) % n]
            seg_len = _segment_length(a, b)
            if seg_len < 0.1:
                continue

            # Calculate tangent unit vector
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            tx = dx / seg_len
            ty = dy / seg_len

            # Normal pointing towards the grass (away from the road)
            # CCW outer: right (ty, -tx)
            # CCW inner: left (-ty, tx)
            # CW outer: left (-ty, tx)
            # CW inner: right (ty, -tx)
            if is_cw:
                if outward:
                    normal = (-ty, tx)
                else:
                    normal = (ty, -tx)
            else:
                if outward:
                    normal = (ty, -tx)
                else:
                    normal = (-ty, tx)

            # Walk along the segment, drawing alternating coloured quads
            t = 0.0
            while t < seg_len:
                remaining_in_stripe = _KERB_SEGMENT_LEN - (
                    accumulated % _KERB_SEGMENT_LEN
                )
                chunk = min(remaining_in_stripe, seg_len - t)
                t1 = t / seg_len
                t2 = (t + chunk) / seg_len

                p1 = _lerp_point(a, b, t1)
                p2 = _lerp_point(a, b, t2)

                # Build a thin quad offset by kerb width
                k = _KERB_WIDTH
                quad = [
                    (p1[0] - ox, oy - p1[1]),
                    (p2[0] - ox, oy - p2[1]),
                    (p2[0] + normal[0] * k - ox, oy - (p2[1] + normal[1] * k)),
                    (p1[0] + normal[0] * k - ox, oy - (p1[1] + normal[1] * k)),
                ]

                col = colours[colour_index % 2]
                pygame.draw.polygon(surf, col, quad)

                accumulated += chunk
                if accumulated % _KERB_SEGMENT_LEN < 0.01:
                    colour_index += 1
                t += chunk

    # ------------------------------------------------------------------
    # Center-line
    # ------------------------------------------------------------------

    def _draw_dashed_centerline(
        self,
        surf: pygame.Surface,
        centerline: list[tuple[float, float]],
        ox: float,
        oy: float,
    ) -> None:
        """Draw a white dashed line along the track's center line.

        Args:
            surf:       Target surface.
            centerline: Centerline points in world space.
            ox, oy:     World-space origin offset.
        """
        if len(centerline) < 2:
            return

        # Flatten centerline into a polyline with cumulative distances
        total_dist: float = 0.0
        drawing: bool = True
        dash_remaining: float = float(_DASH_LENGTH)

        n = len(centerline)
        for i in range(n):
            a = centerline[i]
            b = centerline[(i + 1) % n]
            seg_len = _segment_length(a, b)
            if seg_len < 0.1:
                continue

            t: float = 0.0
            while t < seg_len:
                chunk = min(dash_remaining, seg_len - t)
                if drawing:
                    t1 = t / seg_len
                    t2 = (t + chunk) / seg_len
                    p1 = _lerp_point(a, b, t1)
                    p2 = _lerp_point(a, b, t2)
                    start = (p1[0] - ox, oy - p1[1])
                    end = (p2[0] - ox, oy - p2[1])
                    pygame.draw.line(surf, _COL_CENTERLINE, start, end, 2)

                dash_remaining -= chunk
                t += chunk

                if dash_remaining <= 0:
                    drawing = not drawing
                    dash_remaining = float(
                        _DASH_LENGTH if drawing else _GAP_LENGTH
                    )

    def _draw_chequered_finish_line(
        self,
        surf: pygame.Surface,
        pos: tuple[float, float],
        angle: float,
        track_width: float,
        min_x: float,
        max_y: float,
    ) -> None:
        """Draw a classic checkerboard start/finish line across the road."""
        rad = math.radians(angle)
        dir_x = math.cos(rad)
        dir_y = math.sin(rad)
        right_x = dir_y
        right_y = -dir_x
        
        # Position exactly at the centerline point
        start_center_x = pos[0]
        start_center_y = pos[1]
        
        half_w = track_width / 2.0
        sq_size = 12
        steps = int(track_width / sq_size) + 1
        
        for step in range(steps):
            t = -half_w + step * sq_size
            pt_x = start_center_x + right_x * t
            pt_y = start_center_y + right_y * t
            
            for row in range(2):
                offset_x = (row - 0.5) * sq_size * dir_x
                offset_y = (row - 0.5) * sq_size * dir_y
                
                sq_cx = pt_x + offset_x
                sq_cy = pt_y + offset_y
                
                color = (255, 255, 255) if (step + row) % 2 == 0 else (20, 20, 20)
                
                c1 = (sq_cx + dir_x * (sq_size/2) + right_x * (sq_size/2), sq_cy + dir_y * (sq_size/2) + right_y * (sq_size/2))
                c2 = (sq_cx + dir_x * (sq_size/2) - right_x * (sq_size/2), sq_cy + dir_y * (sq_size/2) - right_y * (sq_size/2))
                c3 = (sq_cx - dir_x * (sq_size/2) - right_x * (sq_size/2), sq_cy - dir_y * (sq_size/2) - right_y * (sq_size/2))
                c4 = (sq_cx - dir_x * (sq_size/2) + right_x * (sq_size/2), sq_cy - dir_y * (sq_size/2) + right_y * (sq_size/2))
                
                s1 = (c1[0] - min_x, max_y - c1[1])
                s2 = (c2[0] - min_x, max_y - c2[1])
                s3 = (c3[0] - min_x, max_y - c3[1])
                s4 = (c4[0] - min_x, max_y - c4[1])
                
                pygame.draw.polygon(surf, color, [s1, s2, s3, s4])

    def _draw_starting_grid(
        self,
        surf: pygame.Surface,
        start_positions: list[StartPosition],
        min_x: float,
        max_y: float,
    ) -> None:
        """Draw F1-style starting grid markings with thick front lines and numbers on the track."""
        for idx, sp in enumerate(start_positions):
            rad = math.radians(sp.angle)
            dir_x = math.cos(rad)
            dir_y = math.sin(rad)
            right_x = dir_y
            right_y = -dir_x

            # Box dimensions (slightly larger than the scaled-up cars)
            hw = 36.0  # half-width (side to side)
            hl = 60.0  # half-length (front to back)

            # 4 corners in world space
            c1 = (sp.x + dir_x * hl + right_x * hw, sp.y + dir_y * hl + right_y * hw)
            c2 = (sp.x + dir_x * hl - right_x * hw, sp.y + dir_y * hl - right_y * hw)
            c3 = (sp.x - dir_x * hl - right_x * hw, sp.y - dir_y * hl - right_y * hw)
            c4 = (sp.x - dir_x * hl + right_x * hw, sp.y - dir_y * hl + right_y * hw)

            # Convert to surface coordinates (Y-flipped)
            def _ws(pt: tuple[float, float]) -> tuple[float, float]:
                return (pt[0] - min_x, max_y - pt[1])

            s1 = _ws(c1)
            s2 = _ws(c2)
            s3 = _ws(c3)
            s4 = _ws(c4)

            # Draw thick solid front line (width=4)
            pygame.draw.line(surf, (240, 240, 240), s1, s2, 4)
            # Draw side borders extending backward (width=2)
            pygame.draw.line(surf, (240, 240, 240), s1, s4, 2)
            pygame.draw.line(surf, (240, 240, 240), s2, s3, 2)

            # Render and rotate the starting slot number (e.g. "1", "2")
            num_str = str(idx + 1)
            num_surf = self.grid_font.render(num_str, True, (240, 240, 240))
            # Rotate by sp.angle to face in the direction of travel
            rotated_num = pygame.transform.rotate(num_surf, sp.angle)
            
            # Place the number behind the box center
            num_center_x = sp.x - dir_x * (hl + 20.0)
            num_center_y = sp.y - dir_y * (hl + 20.0)
            num_surf_pos = _ws((num_center_x, num_center_y))
            
            rect = rotated_num.get_rect(center=(int(num_surf_pos[0]), int(num_surf_pos[1])))
            surf.blit(rotated_num, rect)
