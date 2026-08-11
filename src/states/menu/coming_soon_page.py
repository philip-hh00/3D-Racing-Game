"""A placeholder page that simply announces an unfinished feature."""
from __future__ import annotations

import math

import pygame

from src.states.menu.page import Page
from src.ui import theme
from src.core.i18n import tr


class ComingSoonPage(Page):
    def __init__(self, subtitle: str = "") -> None:
        self.subtitle = subtitle
        self._t = 0.0

    def handle_event(self, event: pygame.event.Event) -> bool:
        return self.zurueck_geklickt(event)

    def update(self, dt: float) -> None:
        self._t += dt

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        self.zurueck_zeichnen(screen, area)
        pulse = 0.5 + 0.5 * math.sin(self._t * 2.0)
        col = (int(180 + 60 * pulse), int(150 + 50 * pulse), 40)
        theme.text(screen, tr("BALD VERFÜGBAR"), theme.TITLE, col, area.center, center=True)
        if self.subtitle:
            theme.text(screen, self.subtitle, theme.BODY, theme.TEXT_DIM,
                       (area.centerx, area.centery + 70), center=True)
