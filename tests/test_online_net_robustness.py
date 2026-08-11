"""Fehlerhafte Netzwerknachrichten dürfen die Lobby nicht beenden.

Audit-Fund: fünf von zehn geprüften LOBBY_STATE-Varianten führten zu einer
unbehandelten Ausnahme mitten im Menü — ein Spielereintrag ohne ``slot``, ein
Eintrag der kein Objekt ist, ``players`` als Text, ``roster_size`` als Text.

Das ist die unangenehmste Fehlerklasse: der Spieler kann sie nicht
reproduzieren und sieht nur, dass das Spiel verschwindet. Wahrscheinlichster
Auslöser ist ein Versionsversatz zwischen Client und Relay — genau dann weicht
die Nachrichtenform ab, und genau dann ist ein sauberer Hinweis wichtiger als
ein Absturz.

Grundsatz wie beim Streckenlader: verwertbare Einträge behalten, unbrauchbare
verwerfen, nie aufgeben.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# pygame wird in tests/conftest.py einmalig fuer den ganzen Lauf gestartet.

from src.net.payload import as_int as _as_int, players as _clean_players  # noqa: E402


# ── Reine Prüffunktionen ────────────────────────────────────────────────────

@pytest.mark.parametrize("roh", ["kaputt", None, 42, {"kein": "Array"}])
def test_unbrauchbare_spielerliste_ergibt_leere_liste(roh):
    assert _clean_players(roh) == []


@pytest.mark.parametrize("eintrag", [None, 7, "Text", [], {"name": "ohne Slot"},
                                     {"slot": "x"}, {"slot": None}, {"slot": -1}])
def test_unbrauchbare_eintraege_fliegen_raus(eintrag):
    assert _clean_players([eintrag]) == []


def test_gute_eintraege_ueberleben_neben_kaputten():
    """Ein einzelner Schaden darf nicht die ganze Lobby unbedienbar machen."""
    roh = [{"slot": 0, "name": "Ann"}, None, {"slot": "x"},
           {"slot": 2, "name": "Bo"}, 42]
    sauber = _clean_players(roh)
    assert [p["slot"] for p in sauber] == [0, 2]
    assert [p["name"] for p in sauber] == ["Ann", "Bo"]


def test_slot_wird_zu_ganzzahl_normalisiert():
    """Ein Slot als Text würde sonst nie zum eigenen Slot passen."""
    sauber = _clean_players([{"slot": "3", "name": "Ann"}])
    assert sauber[0]["slot"] == 3
    assert isinstance(sauber[0]["slot"], int)


def test_uebrige_felder_bleiben_erhalten():
    sauber = _clean_players([{"slot": 1, "name": "Ann", "team": "B",
                              "lobby_ready": True, "vehicle": "supercar"}])
    assert sauber[0]["team"] == "B"
    assert sauber[0]["lobby_ready"] is True
    assert sauber[0]["vehicle"] == "supercar"


@pytest.mark.parametrize("wert,erwartet", [
    (4, 4), ("6", 6), (None, 99), ("viele", 99), ([], 99), (4.0, 4),
])
def test_as_int_faellt_auf_standard_zurueck(wert, erwartet):
    assert _as_int(wert, 99) == erwartet


# ── Ganze Seite gegen fehlerhafte Nachrichten ───────────────────────────────

class _ShellAttrappe:
    def __init__(self) -> None:
        self.state_machine = types.SimpleNamespace(transition=lambda *a, **k: None)

    def pop_page(self) -> None:
        pass

    def push_page(self, page) -> None:
        pass


def _seite():
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers
    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    page = olp.OnlineLobbyPage()
    page.enter(_ShellAttrappe())
    page._view = olp._LOBBY
    return page


@pytest.mark.parametrize("nachricht", [
    {"type": "LOBBY_STATE"},
    {"type": "LOBBY_STATE", "players": "kaputt"},
    {"type": "LOBBY_STATE", "players": [{"name": "ohne Slot"}]},
    {"type": "LOBBY_STATE", "players": [7]},
    {"type": "LOBBY_STATE", "players": [None]},
    {"type": "LOBBY_STATE", "players": [], "roster_size": "viele"},
    {"type": "LOBBY_STATE", "players": [], "mode": 42},
    {"type": "PLAYER_LEFT"},
    {"type": "PLAYER_LEFT", "slot": "x"},
    {"type": "JOIN_OK"},
    {"type": "JOIN_FAIL"},
    {"type": "LOBBY_CLOSED"},
    {"type": "GIBTSNICHT", "beliebig": 1},
    {"kein_typ": True},
    {},
])
def test_fehlerhafte_nachricht_stuerzt_die_seite_nicht_ab(nachricht):
    _seite()._on_net({"source": "tcp", "data": nachricht})


def test_abbruchmeldung_wird_verarbeitet():
    seite = _seite()
    seite._on_net({"source": "error", "data": {"type": "DISCONNECTED"}})
    assert seite._msg


def test_gemischte_spielerliste_bleibt_bedienbar():
    from src.states.menu import online_lobby_page as olp
    seite = _seite()
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE",
        "players": [{"slot": 0, "name": "Ann", "is_host": True}, None,
                    {"slot": 2, "name": "Bo"}],
        "roster_size": 4,
    }})
    assert len(seite._players) == 2
    assert seite._view == olp._LOBBY
