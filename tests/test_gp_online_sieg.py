"""Online gewonnene Grand-Prix-Serien zählen mit (E1a).

Ohne Netz bucht ``race_state`` am Ende des letzten Laufs. Online geht das dort
nicht — die Wertung führt der Gastgeber, ein Gast hat gar keine eigene Serie —,
also bucht die Online-Lobby, sobald der verteilte Zustand die Serie als beendet
meldet.

Der teure Fehler wäre hier nicht ein fehlender Erfolg, sondern ein
geschenkter: der Serienzustand kommt mit **jeder** ``LOBBY_STATE`` erneut
herein. Wer einmal gewinnt und dann zwei Minuten in der Siegerehrung sitzt,
darf nicht hundert Serien gutgeschrieben bekommen.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import profile, statistik  # noqa: E402
from src.states.menu.online_lobby_page import OnlineLobbyPage  # noqa: E402


@pytest.fixture
def spielstand(monkeypatch):
    p = profile.Profile(username="philip")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


@pytest.fixture
def seite(spielstand):
    """Nur die Felder, die die Serienwertung anfasst — die ganze Seite hochzu-
    fahren zöge Netz, Fonts und Streckenlisten mit herein."""
    s = OnlineLobbyPage.__new__(OnlineLobbyPage)
    s._gp_view = {}
    s._gp_lief = False
    s._gp_sieg_gebucht = False
    return s


def _zustand(s, *, aktiv=True, fertig=False, erster="philip"):
    s._gp_view = {
        "gp_active": aktiv,
        "gp_finished": fertig,
        "gp_standings": [{"name": erster, "points": 30},
                         {"name": "Gegner", "points": 18}],
    }
    s._gp_sieg_pruefen()


def _siege() -> int:
    return int(statistik.werte().get("gp_siege", 0))


def test_serie_gewonnen_zaehlt(seite):
    _zustand(seite)                       # Lauf 1 … n-1
    _zustand(seite, fertig=True)
    assert _siege() == 1


def test_zweiter_platz_zaehlt_nicht(seite):
    _zustand(seite)
    _zustand(seite, fertig=True, erster="Gegner")
    assert _siege() == 0


def test_der_endstand_wird_nur_einmal_gebucht(seite):
    """Der Serienzustand kommt mit jeder LOBBY_STATE erneut herein."""
    _zustand(seite)
    for _ in range(50):
        _zustand(seite, fertig=True)
    assert _siege() == 1


def test_zwei_serien_nacheinander_zaehlen_zweimal(seite):
    _zustand(seite)
    _zustand(seite, fertig=True)
    _zustand(seite, aktiv=False)          # Serie beendet, zurück in die Lobby
    _zustand(seite)                       # neue Serie
    _zustand(seite, fertig=True)
    assert _siege() == 2


def test_wer_erst_zur_siegerehrung_dazukommt_bekommt_nichts(seite):
    """Wiedereinstieg nach dem letzten Lauf: die Wertung steht schon, gefahren
    ist sie deswegen nicht."""
    _zustand(seite, fertig=True)
    assert _siege() == 0


def test_laufende_serie_zaehlt_noch_nicht(seite):
    for _ in range(5):
        _zustand(seite)
    assert _siege() == 0


def test_ohne_serie_passiert_nichts(seite):
    seite._gp_view = {}
    seite._gp_sieg_pruefen()
    assert _siege() == 0


def test_leere_wertung_stuerzt_nicht_ab(seite):
    _zustand(seite)
    seite._gp_view = {"gp_active": True, "gp_finished": True, "gp_standings": []}
    seite._gp_sieg_pruefen()
    assert _siege() == 0


def test_muell_in_der_wertung_stuerzt_nicht_ab(seite):
    """Die Wertung kommt über das Netz — ein Host kann alles schicken."""
    _zustand(seite)
    seite._gp_view = {"gp_active": True, "gp_finished": True,
                      "gp_standings": ["kein dict", 42, None]}
    seite._gp_sieg_pruefen()
    assert _siege() == 0


def test_langer_name_wird_wie_in_der_lobby_gekuerzt(seite, spielstand):
    """Der Anzeigename ist auf 15 Zeichen gekürzt — genau der steht in den
    Ergebniszeilen, aus denen die Wertung entsteht."""
    spielstand.username = "einsehrlangername_mit_anhang"
    _zustand(seite)
    _zustand(seite, fertig=True, erster="einsehrlangern")
    assert _siege() == 0
    _zustand(seite, aktiv=False)
    _zustand(seite)
    _zustand(seite, fertig=True, erster="einsehrlangerna")
    assert _siege() == 1
