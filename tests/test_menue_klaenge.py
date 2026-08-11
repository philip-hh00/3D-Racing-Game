"""Menügeräusche: es klingt, was etwas bewirkt.

Festgelegt am 02.08.2026. Vorher klang im Menü genau eine Sache — ein
verstellter Wert in den Einstellungen. Zurückgehen war stumm, ein gesperrter
Knopf war stumm, und ein ausgelöster Knopf fühlte sich an wie ins Leere getippt;
``ui-back.wav`` und ``fehler.wav`` lagen seit Block C1 ungenutzt herum.

Was **nicht** klingt, ist genauso festgelegt: das bloße Bewegen des Fokus.
Klänge jeder Schritt, bedeutete keiner mehr etwas.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import sfx  # noqa: E402
from src.ui.focus import FocusGroup  # noqa: E402
from src.ui.widgets import Button, Stepper  # noqa: E402


@pytest.fixture
def gehoert(monkeypatch):
    """Alles, was gespielt wurde: [(Datei, Lautstärke, Bereich), ...]."""
    liste: list[tuple[str, float, str]] = []
    monkeypatch.setattr(
        sfx, "spielen",
        lambda name, laut=1.0, pano=0.0, bereich=sfx.RENNEN:
            liste.append((name, laut, bereich)))
    return liste


def _taste(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0)


def _klick(pos) -> pygame.event.Event:
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)


# ---------------------------------------------------------------------------
# Was klingt
# ---------------------------------------------------------------------------
def test_verstellter_wert_klickt_leise(gehoert):
    st = Stepper(pygame.Rect(100, 400, 300, 60), "", ["a", "b"], action="s")
    gruppe = FocusGroup([st], vertical=False)
    gruppe.handle_event(_taste(pygame.K_RIGHT))
    assert len(gehoert) == 1
    name, laut, bereich = gehoert[0]
    assert (name, bereich) == ("click", sfx.MENUE)
    assert laut < sfx.MENUE_KLAENGE["ausgeloest"][1], "leiser als ein Knopf"


def test_ausgeloester_knopf_klingt_deutlicher(gehoert):
    knopf = Button(pygame.Rect(100, 400, 300, 60), "Start", "start")
    gruppe = FocusGroup([knopf], vertical=False)
    assert gruppe.handle_event(_taste(pygame.K_RETURN)) == "start"
    assert gehoert == [("click", sfx.MENUE_KLAENGE["ausgeloest"][1], sfx.MENUE)]


def test_gesperrter_knopf_sagt_nein(gehoert):
    """Gesperrte Knöpfe sind nicht fokussierbar — treffen kann man sie mit der
    Maus trotzdem. Ohne Antwort sieht es aus, als wäre der Klick verloren."""
    gesperrt = Button(pygame.Rect(100, 400, 300, 60), "Weiter", "next", enabled=False)
    gruppe = FocusGroup([gesperrt], vertical=False)
    assert gruppe.handle_event(_klick(gesperrt.rect.center)) is None
    assert gehoert == [("fehler", sfx.MENUE_KLAENGE["gesperrt"][1], sfx.MENUE)]


def test_eine_ebene_zurueck_klingt_anders_als_vorwaerts(gehoert):
    """Vorwärts und rückwärts müssen unterscheidbar sein — sonst hört man die
    Richtung nicht."""
    sfx.menue("zurueck")
    sfx.menue("ausgeloest")
    assert gehoert[0][0] == "ui-back"
    assert gehoert[1][0] == "click"


def test_seitenwechsel_klingt_nach_zurueck(gehoert):
    from src.states.menu.page import Page
    from src.states.menu_shell_state import MenuShellState

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = [Page(), Page()]
    shell.pop_page()
    assert gehoert == [("ui-back", sfx.MENUE_KLAENGE["zurueck"][1], sfx.MENUE)]


def test_leerer_stapel_klingt_nicht(gehoert):
    from src.states.menu_shell_state import MenuShellState

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = []
    shell.pop_page()
    assert gehoert == []


# ---------------------------------------------------------------------------
# Was nicht klingt
# ---------------------------------------------------------------------------
def test_fokus_bewegen_bleibt_still(gehoert):
    a = Button(pygame.Rect(100, 400, 300, 60), "A", "a")
    b = Button(pygame.Rect(420, 400, 300, 60), "B", "b")
    gruppe = FocusGroup([a, b], vertical=False)
    gruppe.handle_event(_taste(pygame.K_RIGHT))
    gruppe.handle_event(_taste(pygame.K_LEFT))
    assert gruppe.index == 0
    assert gehoert == []


def test_zeigen_ohne_klicken_bleibt_still(gehoert):
    knopf = Button(pygame.Rect(100, 400, 300, 60), "A", "a")
    gruppe = FocusGroup([knopf], vertical=False)
    gruppe.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=(200, 420),
                                           rel=(1, 1), buttons=(0, 0, 0)))
    assert gehoert == []


def test_klick_ins_leere_bleibt_still(gehoert):
    knopf = Button(pygame.Rect(100, 400, 300, 60), "A", "a")
    gruppe = FocusGroup([knopf], vertical=False)
    gruppe.handle_event(_klick((900, 900)))
    assert gehoert == []


def test_unbekannter_anlass_bleibt_still(gehoert):
    sfx.menue("gibtsnicht")
    assert gehoert == []


# ---------------------------------------------------------------------------
# Die Dateien müssen es auch geben
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("anlass", sorted(sfx.MENUE_KLAENGE))
def test_jeder_anlass_hat_eine_datei(anlass):
    name, laut = sfx.MENUE_KLAENGE[anlass]
    assert os.path.isfile(sfx._pfad(f"{name}.wav")), name
    assert 0.0 < laut <= 1.0
