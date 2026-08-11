"""Das Status-Panel oben rechts laesst die Fahrbahn nicht durchscheinen.

Fund 08.08.2026: gemeldet als "waagerechter Balken mitten durch die Schrift".
Nicht die Trennlinie (die raeumt den Text bei jedem Skalierungsfaktor um ~8 px),
sondern die Fahrbahn hinter einem nur zu ~78 % deckenden Panel: helle
waagerechte Merkmale schienen durch und liefen quer durch POS/LAP.

Die Tests halten die *Regel* — hinter dem Panel darf nichts durchscheinen —
nicht den einen Alphawert. So faellt auch ein spaeteres Zurueckdrehen der
Deckkraft auf.
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


def test_status_panel_ist_undurchsichtig():
    """Regel: im Inneren des Panels scheint der Hintergrund nirgends durch."""
    surf, (px, py, pw, ph) = _panel_gezeichnet(live_diff=None)
    # Rand grosszuegig aussparen: die abgerundeten Ecken sind bewusst
    # durchsichtig und tragen keinen Text.
    rand = 14
    durchscheinend = 0
    for x in range(px + rand, px + pw - rand):
        for y in range(py + rand, py + ph - rand):
            if _ist_hintergrund(surf.get_at((x, y))):
                durchscheinend += 1
    assert durchscheinend == 0, f"{durchscheinend} Pixel scheinen durch das Panel"


def test_status_panel_undurchsichtig_auch_mit_ghost_zeile():
    """Auch die hoehere Ausfuehrung mit GHOST-Zeile bleibt dicht."""
    surf, (px, py, pw, ph) = _panel_gezeichnet(live_diff=0.31)
    rand = 14
    durchscheinend = sum(
        1
        for x in range(px + rand, px + pw - rand)
        for y in range(py + rand, py + ph - rand)
        if _ist_hintergrund(surf.get_at((x, y)))
    )
    assert durchscheinend == 0
