"""Playtest-Runde 5 (29.07.2026): ESC in der Lobby, Serie gegen Server-Umschrieb.

1. ESC trennte die Verbindung sofort — beim Host löste das die ganze Lobby auf.
   Ein Fehlgriff auf eine Taste ist zu billig für eine Folge, die niemand
   rückgängig machen kann. Jetzt dieselbe Rückfrage wie beim Verlassen der
   Serie.
2. Nach dem Rennen landete der Host in der Lobby statt in der Übersicht.
   Auslöser: er las seinen Modus vom Server zurück. Ein Relay ohne
   „Grand Prix" in VALID_MODES schreibt ihn still auf „Rennen" — und damit
   schaltete sich die laufende Serie clientseitig ab.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402
from tests.test_gp_online_start import (  # noqa: E402
    SPIELER, _NetzAttrappe, _seite_in_der_uebersicht,
)


@pytest.fixture
def serie():
    grand_prix.cancel()
    race_setup.current().mode = "Grand Prix"
    yield grand_prix.start_series(3, 3)
    grand_prix.cancel()


@pytest.fixture
def netz(monkeypatch):
    from src.net import session
    n = _NetzAttrappe()
    monkeypatch.setattr(session, "get", lambda: n)
    return n


def _esc():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)


def _enter():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0)


# ── 1. ESC in der Lobby fragt nach ─────────────────────────────────────────

def test_esc_in_der_lobby_trennt_nicht_sofort(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY

    seite.handle_event(_esc())

    assert seite._dialog is not None, "ESC trennt ohne Rückfrage"
    assert seite._view == olp._LOBBY


def test_nein_laesst_alles_wie_es_war(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite.handle_event(_esc())

    seite._dialog = None            # "Nein" schließt den Dialog ohne Folge
    assert seite._view == olp._LOBBY


def test_ja_verlaesst_die_lobby(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite._ask_leave_lobby()
    seite._confirm_leave_lobby()

    assert seite._view == olp._ROLE


def test_host_und_gast_bekommen_verschiedene_warnungen(serie, netz):
    """Beim Host endet die Lobby für alle, beim Gast nur seine Verbindung."""
    texte = {}
    for ist_host in (True, False):
        seite, _sh, olp = _seite_in_der_uebersicht(ist_host=ist_host, netz=netz)
        seite._view = olp._LOBBY
        seite._ask_leave_lobby()
        texte[ist_host] = str(seite._dialog.body if hasattr(seite._dialog, "body")
                              else seite._dialog.__dict__)
    assert texte[True] != texte[False]


def test_dialoge_werden_nicht_verwechselt(serie, netz):
    """Lobby und Serie enden unterschiedlich — ein gemeinsames „ok" reicht
    nicht, um zu wissen, was gemeint war."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)

    seite._ask_leave_gp()
    assert seite._dialog_aktion == "gp_leave"

    seite._view = olp._LOBBY
    seite._ask_leave_lobby()
    assert seite._dialog_aktion == "lobby_leave"


def test_esc_in_der_uebersicht_fragt_weiterhin_nach(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite.handle_event(_esc())
    assert seite._dialog is not None


# ── 2. Serie überlebt einen Server, der den Modus umschreibt ───────────────

def test_host_glaubt_seiner_eigenen_serie(serie, netz):
    """Der Server ohne „Grand Prix" in VALID_MODES antwortet mit „Rennen".
    Vorher schaltete das die laufende Serie beim Host ab."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)

    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": SPIELER, "mode": "Rennen",
        "settings": {}}})

    assert seite._selected_mode == "Rennen", "Server ist autoritativ für den Modus"
    assert seite._ist_gp_modus() is True, "die eigene Serie zählt trotzdem"
    assert seite._gp_settings_payload()["gp_active"] is True


def test_gast_ohne_eigene_serie_folgt_dem_verteilten_modus(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._selected_mode = "Rennen"
    assert seite._ist_gp_modus() is False


def test_host_kehrt_nach_dem_rennen_in_die_uebersicht_zurueck(serie, netz):
    """Auch wenn der verteilte Zustand nichts von der Serie weiß."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite._gp_view = {}                      # Server hat nichts durchgereicht

    seite.resume_after_race()

    assert seite._view == olp._GP_OVERVIEW


def test_gast_bleibt_ohne_verteilte_serie_in_der_lobby(serie, netz):
    """Ein Gast hat keine eigene Serie — ohne verteilten Stand gehört er in
    die Lobby, nicht in eine Übersicht, die er nicht füllen kann."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._view = olp._LOBBY
    seite._gp_view = {}

    seite.resume_after_race()

    assert seite._view == olp._LOBBY


def test_moduswechsel_beendet_die_serie(serie, netz):
    """Sonst läuft sie im Hintergrund weiter und hält den Host in einer Serie
    fest, die er gerade verlassen hat."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite._build_lobby_group()

    # Über die Bedienung, nicht am Feld vorbei: _lobby_event erkennt den
    # Wechsel am Vergleich vor/nach dem Ereignis.
    seite._mode_stepper.index = olp._MODE_KEYS.index("Grand Prix")
    seite._lobby_group.index = seite._lobby_group.widgets.index(seite._mode_stepper)
    seite._lobby_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_LEFT,
                                          unicode="", mod=0))

    assert seite._selected_mode != "Grand Prix"

    assert not grand_prix.is_active()
    assert seite._ist_gp_modus() is False
