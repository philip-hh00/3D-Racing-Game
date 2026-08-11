"""Das Fahrzeug-Labor muss sich zeichnen lassen (06.08.2026).

Gemeldet: Absturz direkt beim Öffnen, ``NameError: name 'theme' is not
defined`` in ``_draw_params``. Ursache war ein fehlender Modulimport — dieselbe
Sorte Fehler wie am 05.08. im Streckeneditor, jetzt zum dritten Mal.

Gegen die *Sorte* steht ``tests/test_freie_namen.py``, der jeden ungebundenen
Namen im ganzen Quellbaum statisch findet. Dieser Test hier deckt die andere
Lücke ab, die den Fehler durchgelassen hat: es gab **keinen einzigen Test, der
das Labor zeichnet**. Getestet waren Navigation und Tastendrücke, nie der
Zeichenweg — und genau der lief beim Öffnen als Erstes.

Deshalb wird hier nichts nachgestellt und nichts gestubbt, sondern der Zustand
richtig aufgebaut und jede der drei Seiten einmal gezeichnet. Was dabei
herauskommt, prüft der Test bewusst nicht; er prüft, dass es überhaupt
herauskommt.
"""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT  # noqa: E402


@pytest.fixture
def labor():
    from src.core.state_machine import StateMachine
    from src.states.vehicle_lab_state import VehicleLabState
    pygame.init()
    pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    zustand = VehicleLabState(StateMachine())
    zustand.enter(vehicle_config="rookie")
    yield zustand
    zustand.exit()


@pytest.mark.parametrize("seite", ["physik", "lack", "klang"])
def test_jede_seite_zeichnet_ohne_absturz(labor, seite):
    """Der gemeldete Absturz saß auf „physik", der Seite beim Öffnen. Die
    beiden anderen kosten nichts extra und haben dieselbe Sorte Fehler."""
    labor.seite = seite
    labor.render(pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT)))


def test_auch_mit_hilfe_und_ueber_alle_fahrzeuge(labor):
    """F1-Hilfe und Fahrzeugwechsel sind eigene Zweige im Zeichenweg — im
    gemeldeten Fall lag der Fehler in einem Zweig, den kein Test je betrat."""
    schirm = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
    labor.seite = "physik"
    labor.show_help = True
    for _ in range(len(labor.keys)):
        labor._fahrzeug_wechseln(1)
        labor.render(schirm)


def test_der_zeiger_steht_bei_der_ausgewaehlten_zeile(labor):
    """Nicht nur „stürzt nicht ab": die Zeile, auf der die Auswahl steht, muss
    sich auch sichtbar von den anderen unterscheiden."""
    from src.ui import theme
    labor.seite = "physik"
    labor.sel = 0
    gezeichnet: list[str] = []

    class _Mitschreiber:
        """``pygame.font.Font`` laesst sich nicht bestuecken (``render`` ist
        schreibgeschuetzt), deshalb ein Stellvertreter davor."""

        def __init__(self, schrift):
            self._schrift = schrift

        def render(self, text, *a, **kw):
            gezeichnet.append(text)
            return self._schrift.render(text, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._schrift, name)

    labor._fonts["body"] = _Mitschreiber(labor._fonts["body"])
    labor.render(pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT)))
    mit_zeiger = [t for t in gezeichnet if t.startswith(theme.ZEIGER)]
    assert len(mit_zeiger) == 1, f"genau eine Zeile trägt den Zeiger: {mit_zeiger}"
