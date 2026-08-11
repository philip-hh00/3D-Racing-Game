"""Ergebnisseite im Grand Prix — besonders der Endstand nach dem letzten Lauf.

Playtest-Fund vom 28.07.2026: die Serie lief im Einzelspieler vollständig durch
und das Spiel stürzte genau beim Siegerbild ab. Ursache war kein Logikfehler,
sondern drei Aufrufe der Art

    theme.text(screen, "1", pygame.font.Font(None, 140), ...)

— an dritter Stelle erwartet ``theme.text`` eine Schriftgröße, kein fertiges
Font-Objekt. Der Fehler schlug erst zu, als das Siegertreppchen tatsächlich
gezeichnet wurde, also nach dem letzten Lauf einer kompletten Serie. Deshalb
prüft dieser Test jeden Lauf einer Serie und nicht nur einen beliebigen.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# pygame wird in tests/conftest.py einmalig fuer den ganzen Lauf gestartet.

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402
from src.states.menu.results_page import ResultsPage  # noqa: E402


class _ShellAttrappe:
    def __init__(self) -> None:
        self.state_machine = types.SimpleNamespace(transition=lambda *a, **k: None)
        self.page_stack: list = []
        self.tab = 0

    def pop_page(self) -> None:
        pass


def _zeile(name: str, pos: int, spieler: bool = False) -> dict:
    return {"name": name, "position": pos, "is_player": spieler, "is_player2": False,
            "vehicle": "rookie", "finish_time": 60.0 + pos, "best_lap": 20.0,
            "lap": "3/3", "gap": "-", "best": "20.0", "pos": pos, "gp": "0"}


@pytest.fixture
def serie():
    grand_prix.cancel()
    race_setup.current().mode = "Grand Prix"
    race_setup.current().is_multiplayer = False
    yield grand_prix.start_series(3, 3)
    grand_prix.cancel()


ZEILEN = [_zeile("Du", 1, True), _zeile("KI-1", 2), _zeile("KI-2", 3)]


def _zeichne(rows, meta):
    screen = pygame.display.get_surface()
    seite = ResultsPage(rows, meta)
    seite.enter(_ShellAttrappe())
    screen.fill((0, 0, 0))
    seite.draw(screen, pygame.Rect(0, 0, 1920, 1080))
    return seite


def test_jeder_lauf_der_serie_laesst_sich_zeichnen(serie):
    """Der Absturz kam erst im letzten Lauf — also alle prüfen."""
    for lauf in range(3):
        serie.add_race_results(ZEILEN)
        serie.note_track(["oval", "city", "desert"][lauf])
        _zeichne(ZEILEN, {"is_grand_prix": True, "track_key": "oval"})
        if lauf < 2:
            serie.next_race()


def test_endstand_zeigt_abschlussknopf(serie):
    for _ in range(3):
        serie.add_race_results(ZEILEN)
        serie.next_race()
    seite = _zeichne(ZEILEN, {"is_grand_prix": True, "track_key": "desert"})
    assert [getattr(w, "action", None) for w in seite.group.widgets] == ["finish_gp"]


def test_zwischenstand_zeigt_weiter_und_abbrechen(serie):
    serie.add_race_results(ZEILEN)
    seite = _zeichne(ZEILEN, {"is_grand_prix": True, "track_key": "oval"})
    aktionen = [getattr(w, "action", None) for w in seite.group.widgets]
    assert aktionen == ["next_gp_race", "cancel_gp"]


def test_endstand_mit_nur_einem_fahrer(serie):
    """Randfall: Siegertreppchen braucht drei Plätze, es gibt aber nur einen."""
    eine_zeile = [_zeile("Allein", 1, True)]
    serie.add_race_results(eine_zeile)
    for _ in range(2):
        serie.next_race()
        serie.add_race_results(eine_zeile)
    _zeichne(eine_zeile, {"is_grand_prix": True, "track_key": "oval"})


def test_endstand_ohne_ergebniszeilen(serie):
    serie.add_race_results([])
    for _ in range(2):
        serie.next_race()
        serie.add_race_results([])
    _zeichne([], {"is_grand_prix": True, "track_key": "oval"})


# ── Die eigentliche Fehlerursache ───────────────────────────────────────────

def test_theme_font_vertraegt_ein_font_objekt():
    """Ein Font statt einer Größe darf höchstens falsch aussehen."""
    from src.ui import theme
    f = pygame.font.Font(None, 40)
    assert theme.font(f) is f


def test_theme_text_vertraegt_ein_font_objekt():
    from src.ui import theme
    screen = pygame.display.get_surface()
    theme.text(screen, "1", pygame.font.Font(None, 140), (255, 215, 0), (100, 100))


def test_theme_font_ueberlebt_wenn_pygame_font_kein_typ_ist(monkeypatch):
    """Regression aus dem PyInstaller-Build.

    Dort ist ``pygame.font.Font`` kein Typ, und ``isinstance(x, pygame.font.Font)``
    warf "isinstance() arg 2 must be a type". Getroffen hat es sofort die
    Tab-Leiste im Hauptmenü — das gebaute Spiel startete überhaupt nicht mehr,
    während in der Entwicklungsumgebung alles lief.

    Hier wird genau dieser Zustand nachgestellt: Font durch etwas ersetzen, das
    kein Typ ist. theme.font muss trotzdem arbeiten.
    """
    from src.ui import theme
    # Schrift vorher einmal erzeugen: der Austausch unten macht pygame.font.Font
    # unbrauchbar, damit koennte auch das Laden nicht mehr funktionieren. Geprueft
    # werden soll die Typpruefung, nicht das Laden.
    theme.font(theme.BODY)
    monkeypatch.setattr(pygame.font, "Font", object(), raising=False)
    assert theme.font(theme.BODY).render("x", True, (255, 255, 255)) is not None


@pytest.mark.parametrize("groesse", [10, 24, 32, 80, 140])
def test_theme_font_mit_ganzzahlen(groesse):
    from src.ui import theme
    assert theme.font(groesse).render("x", True, (255, 255, 255)) is not None


def test_theme_font_liefert_weiterhin_nach_groesse():
    from src.ui import theme
    a = theme.font(theme.BODY)
    b = theme.font(theme.BODY)
    assert a is b                      # Cache greift weiterhin
    assert a is not theme.font(theme.TITLE)
