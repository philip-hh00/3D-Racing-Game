"""HUD-Startampel: gleiche Lampenstufe wie das 3D-Portal (eine Quelle)."""
from __future__ import annotations

import pygame
import pytest

from src.core import startampel
from src.hud.hud import HUD


def _hud() -> HUD:
    pygame.init()
    return HUD()


def _tick(hud, countdown_timer, dt=1 / 60, n=1):
    for _ in range(n):
        hud.update(
            speed=0, fps=60, rpm=1000, redline_rpm=6000, shift_up_rpm=5100,
            gear=1, is_drifting=False, current_lap=1, total_laps=3,
            current_lap_time=0.0, best_lap_time=float("inf"), last_lap_time=0.0,
            position=1, total_vehicles=1, countdown_timer=countdown_timer, dt=dt,
        )


def test_stufenfunktion_wie_portal():
    assert startampel.ampel_stufe(3.0) == 0
    assert startampel.ampel_stufe(2.5) == 1
    assert startampel.ampel_stufe(0.4) == 5
    assert startampel.ampel_stufe(None) == 0


@pytest.mark.parametrize("rest", [3.5, 3.0, 2.5, 2.2, 1.7, 1.0, 0.6, 0.1])
def test_hud_lampen_gleich_portal(rest):
    from src.states import race_state
    hud = _hud()
    _tick(hud, rest)
    assert hud.ampel_stufe() == startampel.ampel_stufe(rest)
    # Portal rechnet mit derselben Funktion/Schwellen.
    assert race_state.AMPEL_SCHWELLEN_S is startampel.AMPEL_SCHWELLEN_S
    assert race_state.ampel_stufe is startampel.ampel_stufe


def test_hud_ampel_bei_go_aus_und_blendet_aus():
    hud = _hud()
    _tick(hud, 0.3)
    _tick(hud, None)
    assert hud.ampel_stufe() == 0
    assert hud.ampel_sichtbar()
    _tick(hud, None, dt=0.5, n=4)
    assert not hud.ampel_sichtbar()


def test_hud_ampel_zeichnet_rot():
    hud = _hud()
    _tick(hud, 0.3)
    surf = pygame.Surface((1920, 1080))
    surf.fill((90, 120, 90))
    hud.render(surf)
    rot = sum(1 for x in range(760, 1160, 2) for y in range(20, 160, 2)
              if surf.get_at((x, y))[0] > 200 and surf.get_at((x, y))[1] < 80)
    assert rot > 100
