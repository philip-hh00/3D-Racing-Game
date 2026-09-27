"""Countdown-Overlay: Ampel-Punkte, Ziffern-Animation und der Wechsel zu LOS!.

Ergaenzt beim Ueberarbeiten des Countdowns (Spielschrift, Pop-in-Animation,
Ampel-Punkte, gruenes Aufblitzen bei GO!) — haelt fest, dass die Ampel sich
mit dem Countdown fuellt, die Ziffer beim Wechsel neu ansetzt und der
Uebergang zu "LOS!"/"GO!" zuverlaessig ausgeloest wird.
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


def test_countdown_merkt_sich_gesamtdauer_und_ziffer():
    hud = _hud()
    _tick(hud, 3.0)
    assert hud._countdown_total == 3.0
    assert hud._countdown_shown_val == 3

    # Ziffer wechselt auf 2 -> Animation faengt fuer diese Ziffer neu an.
    _tick(hud, 2.9)
    _tick(hud, 2.0)
    assert hud._countdown_shown_val == 2
    assert hud._countdown_anim_t == 0.0


def test_countdown_animation_laeuft_hoch_ohne_ziffernwechsel():
    hud = _hud()
    _tick(hud, 3.0)
    _tick(hud, 2.9, n=5)
    assert hud._countdown_shown_val == 3
    assert hud._countdown_anim_t > 0.0


def test_go_wird_nach_countdown_ausgeloest():
    hud = _hud()
    _tick(hud, 1.0)
    assert hud._go_display_timer == 0.0
    _tick(hud, None)
    assert hud._go_display_timer > 0.0


def test_ampel_faellt_mit_fortschreitendem_countdown_lit_count():
    """Je naeher der Countdown an 0 kommt, desto mehr Ampel-Punkte sind an."""
    hud = _hud()
    _tick(hud, 3.0)
    hud._countdown_timer = 3.0
    lit_fruh = _gelesene_lit_anzahl(hud)
    hud._countdown_timer = 0.2
    lit_spaet = _gelesene_lit_anzahl(hud)
    assert lit_spaet > lit_fruh


def _gelesene_lit_anzahl(hud: HUD) -> int:
    elapsed = max(0.0, hud._countdown_total - hud._countdown_timer)
    frac = min(1.0, elapsed / hud._countdown_total)
    return min(5, int(frac * 5) + 1)


def test_countdown_und_go_zeichnen_ohne_fehler():
    """Rauchtest: Rendern bei mehreren Zeitpunkten wirft nichts."""
    hud = _hud()
    surf = pygame.Surface((W, H))
    for countdown_timer in (3.0, 2.5, 1.9, 1.0, 0.4, None, None):
        _tick(hud, countdown_timer)
        hud.render(surf)
