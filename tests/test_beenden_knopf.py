"""Beenden-Knopf unter Einstellungen > Allgemein.

Fund 08.08.2026: unter "Allgemein" fehlte ein Knopf zum Beenden; er soll
denselben Dialog oeffnen wie ESC im Hauptmenue — eine Stelle, nicht zwei.

Die Tests halten die Regel: der Beenden-Dialog wird an genau *einer* Stelle
gebaut, und beide Ausloeser (ESC und der Knopf) gehen durch sie.
"""
from __future__ import annotations

import types
from pathlib import Path

import pygame
import pytest

from src.core.state_machine import StateMachine
from src.states.menu_shell_state import MenuShellState
from src.states.menu.settings_page import SettingsPage

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def shell(monkeypatch):
    monkeypatch.setattr(StateMachine, "_update_music", lambda self, name: None, raising=False)
    sm = StateMachine()
    return MenuShellState(sm)


def test_beenden_bestaetigen_oeffnet_den_dialog(shell):
    assert shell._quit_dialog is None
    shell.beenden_bestaetigen()
    assert shell._quit_dialog is not None


def test_esc_im_hauptmenue_oeffnet_denselben_dialog(shell):
    """ESC auf oberster Ebene oeffnet die Rueckfrage."""
    assert not shell.page_stack
    shell.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)])
    assert shell._quit_dialog is not None


def test_allgemein_hat_einen_beenden_knopf(shell):
    """Unter "Allgemein" steht ein Knopf mit der Aktion quit_game."""
    seite = SettingsPage()
    seite.enter(shell)
    seite.cat = 0  # Allgemein steht immer an erster Stelle
    seite._build_content()
    aktionen = [getattr(w, "action", None) for w in seite._content_group.widgets]
    assert "quit_game" in aktionen


def test_knopf_ruft_dieselbe_stelle_wie_esc(shell):
    """Die Aktion quit_game oeffnet den Dialog der Schale, baut ihn nicht selbst."""
    seite = SettingsPage()
    gerufen = types.SimpleNamespace(mal=0)
    stub = types.SimpleNamespace(beenden_bestaetigen=lambda: setattr(gerufen, "mal", gerufen.mal + 1))
    seite.shell = stub
    seite._dispatch("quit_game")
    assert gerufen.mal == 1


def test_dialog_wird_nur_an_einer_stelle_gebaut():
    """Regel gegen die Rueckkehr der Dopplung: die Rueckfrage 'Beenden?' wird im
    Schalencode genau einmal konstruiert, und ESC ruft dafuer die gemeinsame
    Methode statt einen eigenen Dialog zu bauen."""
    quelle = (_ROOT / "src" / "states" / "menu_shell_state.py").read_text(encoding="utf-8")
    assert quelle.count('Dialog(tr("Beenden?")') == 1
    assert "self.beenden_bestaetigen()" in quelle
