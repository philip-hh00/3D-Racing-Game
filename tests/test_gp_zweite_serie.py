"""Online-Grand-Prix: nach einer beendeten Serie startet die naechste wieder
mit der Uebersicht — nicht als einzelnes Rennen.

Playtest 06.10.2026: „Host stellt Grand Prix ein, alle sind bereit — und es
startet ein normales Einzelrennen statt der Grand-Prix-Uebersicht."

Ursache: ``_gp_phase`` blieb auf "overview" stehen. Der Startknopf der Lobby
fuehrt nur dann in die Uebersicht, wenn die Phase *nicht* schon "overview" ist
(``_lobby_event``, Aktion "start"). Gesetzt wird sie beim Betreten der
Uebersicht, zurueckgesetzt nur in ``_leave_gp_overview``. Endet eine Serie aber
auf der Ergebnisseite — „Grand Prix beenden" nach dem letzten Lauf oder
„Grand Prix abbrechen" mittendrin —, geht es ueber ``resume_after_race`` in die
Lobby, und dieser Weg liess die Phase stehen. Die Lobby zeigte danach
„RENNEN STARTEN", und der Knopf rief ``_request_start`` direkt: die neue Serie
wurde still angelegt und sofort ein Lauf gestartet, ohne Uebersicht. Dasselbe
mit einer Seite, die nach einem Rauswurf aus der Uebersicht (Lobby
geschlossen, Verbindung weg) fuer eine neue Lobby weiterverwendet wird.
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


def _start_druecken(seite) -> None:
    """Den Startknopf der Lobby so ausloesen, wie die Fokusgruppe es meldet."""
    seite._lobby_group.handle_event = lambda ev: "start"
    seite._lobby_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                                          unicode="\r", mod=0))


def test_naechste_serie_beginnt_wieder_in_der_uebersicht(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)

    # Ergebnisseite: „Grand Prix beenden" und „abbrechen" nehmen denselben Weg
    # (results_page): Serie verwerfen, zurueck in die Lobby.
    grand_prix.cancel()
    seite.resume_after_race()
    assert seite._view == olp._LOBBY

    # Neue Serie: Modus steht weiter auf Grand Prix, alle melden sich bereit.
    assert seite._selected_mode == "Grand Prix"
    seite._players = [dict(p, lobby_ready=True) for p in SPIELER]
    seite._update_start_button_label()
    assert seite._btn_start.label.startswith("Zur"), (
        f"der Knopf verspricht ein Rennen: {seite._btn_start.label!r}")

    netz.gesendet.clear()
    _start_druecken(seite)

    assert seite._view == olp._GP_OVERVIEW, "statt der Uebersicht startete ein Rennen"
    assert not any(m.get("type") in ("START_REQUEST", "READY") for m in netz.gesendet)
    assert not sh.wechsel


def test_neue_lobby_auf_alter_seite_beginnt_ohne_serienebene(serie, netz):
    """Rauswurf aus der Uebersicht, dann neue Lobby auf derselben Seite."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_CLOSED", "reason": "Host hat die Verbindung getrennt."}})
    assert seite._view == olp._ROLE

    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_OK", "lobby_id": "HABCDE", "slot": 0, "is_host": True}})
    assert seite._view == olp._LOBBY
    assert seite._gp_phase == "lobby"
    assert seite._gp_ui is None
