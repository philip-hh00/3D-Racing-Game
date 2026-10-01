"""Countdown-Overlay: Startampel (fuenf Lampen) statt Ziffern.

Die HUD-Ampel spiegelt die Startampel am Portal; die Stufe kommt aus
``src.core.startampel`` (siehe auch test_startampel_hud.py). Hier: Ablauf
Countdown -> LOS! -> ausgeblendet und Rauchtest des Zeichnens.
"""
from __future__ import annotations

import pygame

from src.hud.hud import HUD

W, H = 1920, 1080


def _hud() -> HUD:
    pygame.init()
    return HUD()


def _tick(hud: HUD, countdown_timer: float | None, dt: float = 1.0 / 60.0, n: int = 1) -> None:
    for _ in range(n):
        hud.update(
            speed=0, fps=60, rpm=1000, redline_rpm=6000, shift_up_rpm=5100,
            gear=1, is_drifting=False, current_lap=1, total_laps=3,
            current_lap_time=0.0, best_lap_time=float("inf"), last_lap_time=0.0,
            position=1, total_vehicles=1, countdown_timer=countdown_timer, dt=dt,
        )


def test_go_wird_nach_countdown_ausgeloest():
    hud = _hud()
    _tick(hud, 1.0)
    assert hud._go_display_timer == 0.0
    _tick(hud, None)
    assert hud._go_display_timer > 0.0


def test_ampel_fuellt_sich_mit_fortschreitendem_countdown():
    hud = _hud()
    _tick(hud, 3.0)
    fruh = hud.ampel_stufe()
    _tick(hud, 0.2)
    assert hud.ampel_stufe() > fruh


def test_countdown_und_go_zeichnen_ohne_fehler():
    """Rauchtest: Rendern bei mehreren Zeitpunkten wirft nichts."""
    hud = _hud()
    surf = pygame.Surface((W, H))
    for countdown_timer in (3.0, 2.5, 1.9, 1.0, 0.4, None, None):
        _tick(hud, countdown_timer)
        hud.render(surf)
