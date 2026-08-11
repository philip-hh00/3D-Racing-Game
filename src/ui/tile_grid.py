"""TileGrid — a scrollable grid of selectable cards (vehicles, tracks, etc.).

The screen supplies the item list and a per-tile draw callback; the grid handles
layout, selection, scrolling (mouse wheel + arrow keys) and a scrollbar. Keyboard
and mouse selection stay in sync.
"""
from __future__ import annotations

import pygame

from src.ui import theme


class TileGrid:
    def __init__(self, area: pygame.Rect, item_count: int, *, columns: int = 3,
                 tile_w: int = 300, tile_h: int = 210, gap: int = 24) -> None:
        self.area = pygame.Rect(area)
        self.columns = max(1, columns)
        self.tile_w = tile_w
        self.tile_h = tile_h
        self.gap = gap
        self.count = item_count
        self.selected = 0
        self.scroll = 0.0          # pixels scrolled down

    # -- layout ----------------------------------------------------------
    @property
    def rows(self) -> int:
        return (self.count + self.columns - 1) // self.columns

    def _content_h(self) -> int:
        return self.rows * self.tile_h + max(0, self.rows - 1) * self.gap

    def _max_scroll(self) -> float:
        return max(0.0, self._content_h() - self.area.height)

    def tile_rect(self, i: int) -> pygame.Rect:
        """Screen rect of item *i* (may be outside the visible area)."""
        row, col = divmod(i, self.columns)
        grid_w = self.columns * self.tile_w + (self.columns - 1) * self.gap
        x0 = self.area.x + (self.area.width - grid_w) // 2
        x = x0 + col * (self.tile_w + self.gap)
        y = self.area.y + row * (self.tile_h + self.gap) - int(self.scroll)
        return pygame.Rect(x, y, self.tile_w, self.tile_h)

    # -- interaction -----------------------------------------------------
    def _ensure_visible(self) -> None:
        r = self.tile_rect(self.selected)
        top = r.y + int(self.scroll)          # position independent of scroll
        if r.y < self.area.y:
            self.scroll = top - self.area.y
        elif r.bottom > self.area.bottom:
            self.scroll = top - self.area.bottom + self.tile_h
        self.scroll = max(0.0, min(self._max_scroll(), self.scroll))

    def handle_event(self, event) -> str | None:
        """Returns 'select' when the highlighted tile changes, 'activate' on click/enter."""
        if self.count == 0:
            return None
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0.0, min(self._max_scroll(), self.scroll - event.y * 60))
            return None
        if event.type == pygame.MOUSEMOTION:
            for i in range(self.count):
                if self.tile_rect(i).collidepoint(event.pos) and self.area.collidepoint(event.pos):
                    if i != self.selected:
                        self.selected = i
                        return "select"
                    return None
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i in range(self.count):
                if self.tile_rect(i).collidepoint(event.pos) and self.area.collidepoint(event.pos):
                    self.selected = i
                    return "activate"
        if event.type == pygame.KEYDOWN:
            c = self.columns
            old = self.selected
            from src.core import keybindings as kb
            if event.key in (pygame.K_LEFT, pygame.K_a, kb.get("left")):
                self.selected = max(0, self.selected - 1)
            elif event.key in (pygame.K_RIGHT, pygame.K_d, kb.get("right")):
                self.selected = min(self.count - 1, self.selected + 1)
            elif event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
                self.selected = max(0, self.selected - c)
            elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
                self.selected = min(self.count - 1, self.selected + c)
            elif event.key == pygame.K_RETURN:
                return "activate"
            if self.selected != old:
                self._ensure_visible()
                return "select"
        return None

    # -- rendering -------------------------------------------------------
    def draw(self, screen: pygame.Surface, draw_tile) -> None:
        """draw_tile(screen, index, rect, selected: bool) renders one card."""
        prev_clip = screen.get_clip()
        screen.set_clip(self.area)
        for i in range(self.count):
            r = self.tile_rect(i)
            if r.bottom < self.area.y or r.y > self.area.bottom:
                continue
            draw_tile(screen, i, r, i == self.selected)
        screen.set_clip(prev_clip)
        self._draw_scrollbar(screen)

    def _draw_scrollbar(self, screen: pygame.Surface) -> None:
        ms = self._max_scroll()
        if ms <= 0:
            return
        track = pygame.Rect(self.area.right + 8, self.area.y, 6, self.area.height)
        pygame.draw.rect(screen, theme.PANEL_LIGHT, track, border_radius=3)
        frac_vis = self.area.height / self._content_h()
        knob_h = max(30, int(track.height * frac_vis))
        knob_y = track.y + int((track.height - knob_h) * (self.scroll / ms))
        pygame.draw.rect(screen, theme.ACCENT, (track.x, knob_y, track.width, knob_h), border_radius=3)
