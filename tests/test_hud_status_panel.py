"""Das Status-Panel oben rechts: leicht durchsichtig, aber gedämpft.

Fund 08.08.2026: gemeldet als "waagerechter Balken mitten durch die Schrift" —
helle Fahrbahnmarkierungen schienen durch ein zu ~78 % deckendes Panel. Damals
wurde das Panel deckend. Am 27.09.2026 wollte der Besitzer es ausdrücklich
wieder "leicht durchsichtig". Die Regel ist jetzt: der Hintergrund darf
durchscheinen, aber höchstens gut zur Hälfte gedämpft — eine weiße Linie
dahinter wird zum grauen Schimmer, nicht zum Balken.
"""
from __future__ import annotations

import pygame

from src.hud.hud import HUD

# Eine Farbe, die im Panel selbst nirgends vorkommt (weder Text noch Rahmen):
# taucht sie im Inneren auf, kommt sie von hinten.
_HINTERGRUND = (255, 0, 255)


def _ist_hintergrund(px: tuple[int, int, int]) -> bool:
    # Magenta-Signatur, auch schon anteilig durchscheinend: rot und blau
    # angehoben, gruen fast null. Kein Panelwert trifft das — der undurchsichtige
    # Grund ist (10,10,15), der Rahmen (80,80,95, gruen 80), die Texte sind
    # weiss/gruen/orange/rot (alle mit hohem gruen oder blau nahe null). Bei
    # Alpha 200 scheint Magenta als rund (63, 8, 67) durch, bei 255 gar nicht.
    r, g, b = px[0], px[1], px[2]
    return r > 40 and b > 40 and g < 30


def _panel_gezeichnet(live_diff):
    pygame.init()
    hud = HUD()
    hud._position = 1
    hud._total_vehicles = 4
    hud._current_lap = 3
    hud._total_laps = 3
    hud._race_finished = False
    hud._current_lap_time = 14.88
    hud._last_lap_time = 17.19
    hud._best_lap_time = 17.19
    hud._live_diff = live_diff
    hud._sector_diff = 0.48
    w, h = 520, 460
    surf = pygame.Surface((w, h))
    surf.fill(_HINTERGRUND)  # praegnanter als jede echte Fahrbahn
    hud._render_top_right_panel(surf, w, h, 1.0)

    panel_w = int(260)
    panel_h = int((235 if live_diff is not None else 210))
    panel_x = w - panel_w - 20
    panel_y = 20
    return surf, (panel_x, panel_y, panel_w, panel_h)


#: Anteil des Hintergrunds, der höchstens durchscheinen darf (0..1).
DURCHLASS_MAX = 0.6


def _durchlass(live_diff):
    """Wie stark der Hintergrund je Pixel durchkommt: Panel vor Magenta und
    vor Schwarz zeichnen, der Unterschied im Rotkanal ist der Anteil von hinten.
    Unabhängig von Schriftfarben und Kantenglättung."""
    global _HINTERGRUND
    alt = _HINTERGRUND
    try:
        hell, (px, py, pw, ph) = _panel_gezeichnet(live_diff)
        _HINTERGRUND = (0, 0, 0)
        dunkel, _ = _panel_gezeichnet(live_diff)
    finally:
        _HINTERGRUND = alt
    rand = 14
    return [(hell.get_at((x, y))[0] - dunkel.get_at((x, y))[0]) / 255.0
            for x in range(px + rand, px + pw - rand, 2)
            for y in range(py + rand, py + ph - rand, 2)]


def test_status_panel_daempft_den_hintergrund():
    """Regel: im Inneren scheint der Hintergrund höchstens gedämpft durch."""
    assert max(_durchlass(None)) <= DURCHLASS_MAX


def test_status_panel_daempft_auch_mit_ghost_zeile():
    assert max(_durchlass(0.31)) <= DURCHLASS_MAX


def test_status_panel_ist_leicht_durchsichtig():
    """Und umgekehrt: ganz dicht ist es nicht mehr (Wunsch vom 27.09.2026)."""
    werte = sorted(_durchlass(None))
    assert werte[len(werte) // 2] > 0.2
