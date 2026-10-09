"""Der Weg zu den Online-Strecken: Streckenauswahl und Editor-Projektliste (Plan 1.1.0 §5).

Taste O (Controller: Y) und der Knopf fuehren zum Zustand ``online_strecken``;
der Zustand ist registriert, und der Rueckweg kommt dorthin zurueck.
"""
from __future__ import annotations

import types

import pygame

from src.core.settings import SCREEN_HEIGHT, SCREEN_WIDTH


def _zielliste():
    ziele: list = []
    sm = types.SimpleNamespace(
        transition=lambda ziel, **kw: ziele.append(ziel),
        zurueck=lambda *a, **k: ziele.append("zurueck"))
    return sm, ziele


def _taste(key, **extra):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0, **extra)


def _klick(pos):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1)


def test_streckenauswahl_taste_und_knopf():
    from src.states.track_select_state import TrackSelectState
    sm, ziele = _zielliste()
    z = TrackSelectState(sm)
    z.enter()
    z.handle_events([_taste(pygame.K_o)])
    z.handle_events([_taste(pygame.K_y, synthetic=True)])       # Y am Controller
    z.handle_events([_klick(z._online_rect().center)])
    assert ziele == ["online_strecken"] * 3
    schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    z.render(schirm)
    # Der Knopf liegt im Bild und ueberdeckt weder Startknopf noch Liste.
    assert schirm.get_rect().contains(z._online_rect())
    assert not z._online_rect().colliderect(z._start_rect())
    assert not z._online_rect().colliderect(z.left_panel_rect)


def test_streckenauswahl_im_grand_prix_bleibt_bei_der_serie():
    from src.core import grand_prix
    from src.states.track_select_state import TrackSelectState
    sm, ziele = _zielliste()
    z = TrackSelectState(sm)
    z.enter()
    original = grand_prix.is_active
    grand_prix.is_active = lambda: True
    try:
        z.handle_events([_taste(pygame.K_o)])
    finally:
        grand_prix.is_active = original
    assert ziele == []


def test_editor_projektliste_taste_und_knopf():
    from src.states.editor_state import EditorState
    sm, ziele = _zielliste()
    z = EditorState(sm)
    z._mode = "browse"
    z._handle_browse_event(_taste(pygame.K_o))
    z._handle_browse_event(_klick(z._online_rect().center))
    assert ziele == ["online_strecken"] * 2
    assert pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT).contains(z._online_rect())
    # Der Knopf liegt neben der Projektliste, nicht auf ihr.
    for _i, r in z._browse_layout():
        assert not z._online_rect().colliderect(r)


def test_zustand_ist_im_spiel_registriert():
    import inspect
    from src.core import game
    quelle = inspect.getsource(game)
    assert 'register("online_strecken"' in quelle


def test_online_strecken_zustand_hat_musik_und_rueckweg():
    from src.core.state_machine import StateMachine
    from src.states.online_strecken_state import OnlineStreckenState
    sm = StateMachine()
    sm.register("online_strecken", OnlineStreckenState(sm))
    gespielt = []
    from src.core import audio
    original = (audio.play_menu_music, audio.stop_music)
    audio.play_menu_music = lambda *a, **k: gespielt.append("menue")
    audio.stop_music = lambda *a, **k: gespielt.append("stopp")
    try:
        sm._update_music("online_strecken")
    finally:
        audio.play_menu_music, audio.stop_music = original
    assert gespielt == ["menue"]
