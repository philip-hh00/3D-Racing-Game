"""Minimap – top-down miniature of the track with live vehicle dots.

The track road band (filled quads between outer & inner wall) plus the
start/finish marker are baked once onto a Surface at construction; only the
vehicle dots are redrawn each frame.

Coordinates are Y-flipped (``max_y - y``) exactly like the track renderer so
the minimap matches the on-screen track orientation.
"""
from __future__ import annotations

import math

import pygame

from src.core.settings import SCREEN_HEIGHT


class Minimap:
    """Renders a scaled, orientation-correct track overview with vehicle dots."""

    PANEL_W: int = 260
    PANEL_H: int = 190
    PADDING: int = 12
    BG_COLOR: tuple[int, int, int, int] = (10, 10, 15, 200)
    BORDER_COLOR: tuple[int, int, int] = (80, 80, 95)
    ROAD_COLOR: tuple[int, int, int] = (70, 70, 80)
    ROAD_EDGE: tuple[int, int, int] = (120, 120, 135)
    START_COLOR: tuple[int, int, int] = (255, 255, 255)

    def __init__(self, track, screen_h: int = SCREEN_HEIGHT) -> None:
        self.track = track
        self.pos = (20, SCREEN_HEIGHT - self.PANEL_H - 20)   # bottom-left corner
        self._bg_cache: pygame.Surface | None = None
        self._scale = 1.0
        self._min_x = 0.0
        self._max_y = 0.0
        self._offset = (0.0, 0.0)
        self._bake()

    # ------------------------------------------------------------------
    def _bake(self) -> None:
        """Precompute scale/offset and bake the road band + start marker."""
        outer = list(getattr(self.track, "outer_wall", []) or [])
        inner = list(getattr(self.track, "inner_wall", []) or [])
        pts = outer + inner
        if not pts:
            pts = list(self.track.centerline) if getattr(self.track, "centerline", None) else []
        if not pts:
            return

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        tw = max(1.0, max_x - min_x)
        th = max(1.0, max_y - min_y)

        avail_w = self.PANEL_W - 2 * self.PADDING
        avail_h = self.PANEL_H - 2 * self.PADDING
        scale = min(avail_w / tw, avail_h / th)
        self._scale = scale
        self._min_x = min_x
        self._max_y = max_y

        map_w = tw * scale
        map_h = th * scale
        origin_x = self.PADDING + (avail_w - map_w) / 2.0
        origin_y = self.PADDING + (avail_h - map_h) / 2.0
        self._offset = (origin_x, origin_y)

        surf = pygame.Surface((self.PANEL_W, self.PANEL_H), pygame.SRCALPHA)
        surf.fill(self.BG_COLOR)
        pygame.draw.rect(surf, self.BORDER_COLOR,
                         (0, 0, self.PANEL_W, self.PANEL_H), 2, border_radius=8)

        # Road band: fill quads between outer & inner wall (no thick-line artifacts)
        if outer and inner and len(outer) == len(inner):
            o = [self._world_to_map(p) for p in outer]
            n = [self._world_to_map(p) for p in inner]
            m = len(o)
            for i in range(m):
                quad = [o[i], o[(i + 1) % m], n[(i + 1) % m], n[i]]
                pygame.draw.polygon(surf, self.ROAD_COLOR, quad)
            pygame.draw.polygon(surf, self.ROAD_EDGE, o, 1)
            pygame.draw.polygon(surf, self.ROAD_EDGE, n, 1)
        else:
            # Fallback: centerline strip via per-point circles (still artifact-free)
            cl = [self._world_to_map(p) for p in self.track.centerline]
            rad = max(2, int(getattr(self.track, "track_width", 120.0) * scale * 0.5))
            for p in cl:
                pygame.draw.circle(surf, self.ROAD_COLOR, p, rad)

        # Start-/Ziellinie — quer ueber die Fahrbahn.
        #
        # Bis zum 08.08.2026 stand hier ein weisser Punkt. Der sagt, **wo** die
        # Linie ist, aber nicht, **wie sie liegt**: laufen auf einer Strecke
        # mehrere Geraden nebeneinander, sieht man dem Punkt die Startrichtung
        # nicht an. Die Linie zeigt beides.
        linie = self.startlinie()
        if linie is not None:
            a, b = linie
            pygame.draw.line(surf, (0, 0, 0), a, b, 4)          # Kontur
            pygame.draw.line(surf, self.START_COLOR, a, b, 2)

        self._bg_cache = surf

    # ------------------------------------------------------------------
    def startlinie(self):
        """Die Start-/Ziellinie in Panelkoordinaten: ``(anfang, ende)``.

        ``None``, wenn die Strecke keine Wegpunkte hat — dann gibt es nichts zu
        zeichnen, und die Minimap soll daran nicht zerbrechen.

        Eine eigene Methode, weil sich Geometrie pruefen laesst und Pixel nur
        muehsam: die Linie muss die Fahrbahn queren, senkrecht zur
        Fahrtrichtung stehen und im Panel liegen.
        """
        wps = getattr(self.track, "waypoints", None)
        if not wps:
            return None

        mitte = self._world_to_map((wps[0].x, wps[0].y))

        # Fahrtrichtung an der Ziellinie, aus der Mittellinie in Panelkoordinaten
        # genommen — im Weltmass waere die Y-Spiegelung der Karte noch drin.
        cl = list(getattr(self.track, "centerline", []) or [])
        if len(cl) >= 2:
            p0 = self._world_to_map(cl[0])
            p1 = self._world_to_map(cl[1 % len(cl)])
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        else:
            dx, dy = 1.0, 0.0
        laenge = math.hypot(dx, dy)
        if laenge <= 0.0:
            dx, dy, laenge = 1.0, 0.0, 1.0
        # Normale: quer zur Fahrtrichtung.
        nx, ny = -dy / laenge, dx / laenge

        halb = max(3.0, getattr(self.track, "track_width", 120.0) * self._scale / 2.0)
        return ((int(mitte[0] - nx * halb), int(mitte[1] - ny * halb)),
                (int(mitte[0] + nx * halb), int(mitte[1] + ny * halb)))

    # ------------------------------------------------------------------
    def _world_to_map(self, pt: tuple[float, float]) -> tuple[int, int]:
        """World → panel pixels, Y-flipped to match the track renderer."""
        return (
            int((pt[0] - self._min_x) * self._scale + self._offset[0]),
            int((self._max_y - pt[1]) * self._scale + self._offset[1]),
        )

    # ------------------------------------------------------------------
    def render(
        self,
        screen: pygame.Surface,
        vehicles: list,
        player_id: int | None = None,
    ) -> None:
        if self._bg_cache is None:
            return
        panel = self._bg_cache.copy()
        for v in vehicles:
            try:
                pos = v.physics.position
            except AttributeError:
                pos = getattr(v, "position", None)   # RemoteVehicle ghosts
                if pos is None:
                    continue
            mx, my = self._world_to_map(pos)
            if v.id == player_id:
                pygame.draw.circle(panel, (255, 40, 40), (mx, my), 5)
                pygame.draw.circle(panel, (255, 255, 255), (mx, my), 5, 1)
            else:
                color = getattr(v, "minimap_color", None)
                if color is None:
                    # Die Farbe, die das Auto wirklich hat — der Renderer kennt
                    # Sprite und Lackierung. `color_primary` waere hier der
                    # Vorgabewert aus der Fahrzeug-JSON und damit eine Farbe, die
                    # man am Auto nie sieht (gemeldet 30.07.2026).
                    r = getattr(v, "renderer", None) or getattr(v, "_renderer", None)
                    if r is not None and hasattr(r, "punktfarbe"):
                        color = r.punktfarbe()
                if color is None:
                    cfg = getattr(v, "config", None)
                    color = getattr(cfg, "color_primary", None) or (0, 180, 220)
                if isinstance(color, list):
                    color = tuple(color[:3])
                pygame.draw.circle(panel, color, (mx, my), 4)
                pygame.draw.circle(panel, (0, 0, 0), (mx, my), 4, 1)
        screen.blit(panel, self.pos)
