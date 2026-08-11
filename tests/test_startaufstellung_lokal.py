"""Startaufstellung: kein Fahrzeug darf auf dem Platz eines anderen stehen.

Gemeldet am 31.07.2026: im **lokalen Mehrspieler-Grand-Prix** spawnten nach dem
ersten Lauf Fahrzeuge teilweise auf der Position des anderen.

Ursache waren drei Stellen, die ihren Gitterplatz je für sich entschieden:
Spieler 1 aus ``grid_slot``, Spieler 2 **fest auf Gitterplatz 1**, die KI in
einer eigenen Funktion, die nur ihre eigenen Vorgaben kannte. Stand Spieler 1
laut Wertung auf Platz 1, bekamen beide Menschen denselben Platz. Dieselbe Lücke
traf eine KI ohne Wertung, die auf dem Platz eines Menschen landen konnte.

Geprüft wird hier der **ganze Weg**: die Grand-Prix-Übersicht rechnet die
Startreihenfolge, übergibt sie an den Rennzustand, und der verteilt die Plätze.
Ein Test nur auf der Verteilfunktion hätte den Fehler nicht gefunden — die gab
es vorher gar nicht, gefehlt hat die Übergabe.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.core import grand_prix, race_setup  # noqa: E402
from src.states.race_state import RaceState  # noqa: E402


class _FakeSetup:
    """Nur das, was _gitter_bauen anfasst."""

    def __init__(self, *, split: bool, ki: int, online: bool = False) -> None:
        self.is_multiplayer = split
        self._online = online
        self._ki = ki

    def ai_count(self) -> int:
        return self._ki


def _plaetze(n: int = 6) -> list:
    return [object()] * n


# ---------------------------------------------------------------------------
# Der gemeldete Fehler
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("wunsch_p1", [0, 1, 2, 3, 4, 5])
def test_zwei_menschen_nie_auf_demselben_platz(wunsch_p1):
    """Spieler 2 war fest auf Gitterplatz 1 verdrahtet. Sobald die Wertung
    Spieler 1 dorthin setzte, standen beide Autos übereinander."""
    gitter = RaceState._gitter_bauen(
        {"grid_slot": wunsch_p1}, _plaetze(), _FakeSetup(split=True, ki=2))
    assert gitter[0] == wunsch_p1
    assert gitter[0] != gitter[1], f"beide Menschen auf {gitter[0]}"
    assert len(set(gitter)) == len(gitter), gitter


def test_spieler_zwei_bekommt_seinen_platz_aus_der_wertung():
    """Nicht nur kollisionsfrei — der Platz muss auch stimmen."""
    gitter = RaceState._gitter_bauen(
        {"grid_slot": 1, "grid_slot2": 0}, _plaetze(), _FakeSetup(split=True, ki=2))
    assert gitter[:2] == [1, 0]


# ---------------------------------------------------------------------------
# Der ganze Weg: Übersicht → Rennzustand
# ---------------------------------------------------------------------------
class _ShellStub:
    def __init__(self) -> None:
        self.wechsel: list[tuple] = []
        sm = types.SimpleNamespace(
            transition=lambda name, **kw: self.wechsel.append((name, kw)))
        self.state_machine = sm
        self.page_stack: list = []

    def pop_page(self) -> None:
        pass


@pytest.fixture
def lokale_serie(monkeypatch, tmp_path):
    """Lokaler Mehrspieler mit laufender Serie, in der Spieler 2 führt."""
    s = race_setup.current()
    alt = (s.is_multiplayer, s.player_vehicle, s.player2_vehicle,
           s.track_path, list(s.ai_roster))
    s.is_multiplayer = True
    s.player_vehicle = "rookie"
    s.player2_vehicle = "supercar"
    s.track_path = str(_ROOT / "data" / "tracks" / "oval.json")
    s.ai_roster = [types.SimpleNamespace(name="KI Anna", vehicle="drifter",
                                         difficulty="medium"),
                   types.SimpleNamespace(name="KI Bert", vehicle="electric",
                                         difficulty="medium")]
    yield s
    (s.is_multiplayer, s.player_vehicle, s.player2_vehicle,
     s.track_path, s.ai_roster) = alt
    grand_prix.cancel()


def test_uebersicht_uebergibt_beide_spielerplaetze(lokale_serie, monkeypatch):
    """Die Übersicht schickte nur ``grid_slot``. Spieler 2 tauchte in der
    Startreihenfolge auf, aber sein Platz wurde nie übergeben."""
    from src.states.menu.gp_overview_page import GPOverviewPage

    seite = GPOverviewPage.__new__(GPOverviewPage)
    shell = _ShellStub()
    seite.shell = shell
    seite._msg = ""
    # Spieler 2 führt die Wertung an, Spieler 1 ist Zweiter.
    monkeypatch.setattr(seite, "_startreihenfolge",
                        lambda: ["Spieler 2", "Philip", "KI Anna", "KI Bert"])
    monkeypatch.setattr(seite, "_spieler", lambda: [
        {"slot": 0, "name": "Philip", "vehicle": "rookie"},
        {"slot": 1, "name": "Spieler 2", "vehicle": "supercar"},
    ])

    seite._starten()

    name, kw = shell.wechsel[-1]
    assert name == "race"
    assert kw["grid_slot"] == 1, "Spieler 1 ist Zweiter der Wertung"
    assert kw["grid_slot2"] == 0, "Spieler 2 führt und startet vorn"
    assert kw["ai_grid_slots"] == [2, 3]


def test_ganzer_weg_ergibt_eindeutige_plaetze(lokale_serie, monkeypatch):
    """Übersicht rechnet, Rennzustand verteilt — am Ende darf kein Platz
    doppelt sein. Genau das ging vorher schief."""
    from src.states.menu.gp_overview_page import GPOverviewPage

    seite = GPOverviewPage.__new__(GPOverviewPage)
    shell = _ShellStub()
    seite.shell = shell
    seite._msg = ""
    monkeypatch.setattr(seite, "_startreihenfolge",
                        lambda: ["Spieler 2", "Philip", "KI Anna", "KI Bert"])
    monkeypatch.setattr(seite, "_spieler", lambda: [
        {"slot": 0, "name": "Philip", "vehicle": "rookie"},
        {"slot": 1, "name": "Spieler 2", "vehicle": "supercar"},
    ])
    seite._starten()
    _name, kw = shell.wechsel[-1]

    gitter = RaceState._gitter_bauen(kw, _plaetze(), _FakeSetup(split=True, ki=2))
    assert len(set(gitter)) == len(gitter), gitter
    assert gitter[0] == 1 and gitter[1] == 0


def test_erstes_rennen_ohne_wertung(lokale_serie, monkeypatch):
    """Vor dem ersten Lauf gibt es keine Wertung — dann stehen die Menschen
    einfach vorn, und nichts kollidiert."""
    from src.states.menu.gp_overview_page import GPOverviewPage

    seite = GPOverviewPage.__new__(GPOverviewPage)
    shell = _ShellStub()
    seite.shell = shell
    seite._msg = ""
    monkeypatch.setattr(seite, "_startreihenfolge", lambda: [])
    monkeypatch.setattr(seite, "_spieler", lambda: [
        {"slot": 0, "name": "Philip", "vehicle": "rookie"},
        {"slot": 1, "name": "Spieler 2", "vehicle": "supercar"},
    ])
    seite._starten()
    _name, kw = shell.wechsel[-1]
    gitter = RaceState._gitter_bauen(kw, _plaetze(), _FakeSetup(split=True, ki=2))
    assert gitter == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Die anderen Modi — ausdrücklich mitgeprüft
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("split,ki,kwargs,was", [
    (False, 3, {}, "Einzelspieler, normales Rennen"),
    (False, 3, {"grid_slot": 2, "ai_grid_slots": [0, 1, None]},
     "Einzelspieler Grand Prix"),
    (True, 2, {}, "lokaler Mehrspieler, normales Rennen"),
    (True, 0, {}, "lokaler Mehrspieler ohne KI"),
    (True, 4, {"grid_slot": 5, "grid_slot2": 4}, "lokaler MP, Menschen hinten"),
    (False, 0, {}, "Zeitfahren, allein auf der Strecke"),
])
def test_kein_modus_belegt_einen_platz_doppelt(split, ki, kwargs, was):
    gitter = RaceState._gitter_bauen(kwargs, _plaetze(), _FakeSetup(split=split, ki=ki))
    assert len(set(gitter)) == len(gitter), f"{was}: {gitter}"
    assert all(0 <= p < 6 for p in gitter), f"{was}: {gitter}"


@pytest.mark.parametrize("menschen", [[2, 4, 5], [0, 1, 2], [3, 5, 1], [5, 4, 3]])
def test_online_ki_nie_auf_dem_platz_eines_menschen(menschen):
    """Online baut nur der Host die KI. Kennt er die Plätze der Gäste nicht,
    setzt er sie auf einen belegten — die Lobby schickt sie deshalb mit."""
    gitter = RaceState._gitter_bauen(
        {"grid_slot": menschen[0], "human_grid_slots": menschen,
         "online_human_count": len(menschen), "ai_grid_slots": [None, None]},
        _plaetze(), _FakeSetup(split=False, ki=2, online=True))
    ki = gitter[len(menschen):]
    assert not (set(ki) & set(menschen)), f"KI {ki} auf Menschplatz {menschen}"
    assert len(set(gitter)) == len(gitter), gitter


def test_online_ohne_menschliste_bleibt_kollisionsfrei():
    """Rückfall für einen Host ohne die neue Liste: die Plätze müssen trotzdem
    eindeutig bleiben."""
    gitter = RaceState._gitter_bauen(
        {"grid_slot": 2, "online_human_count": 3, "ai_grid_slots": [0, None]},
        _plaetze(), _FakeSetup(split=False, ki=2, online=True))
    assert len(set(gitter)) == len(gitter), gitter
    assert gitter[0] == 2


# ---------------------------------------------------------------------------
# Verteilfunktion: Randfälle
# ---------------------------------------------------------------------------
def test_ohne_startpositionen_leeres_gitter():
    assert RaceState._gitter_bauen({}, [], _FakeSetup(split=True, ki=2)) == []


@pytest.mark.parametrize("muell", [
    [None, None], ["zwei", 1], [True, False], [-1, 99], [1.5, None], [{}, []],
])
def test_verteiler_vertraegt_muell(muell):
    """Die Wünsche kommen aus dem Netz und aus einer Wertung — beides kann
    Unsinn liefern, ohne dass zwei Autos übereinander stehen dürfen."""
    gitter = RaceState.gitterplaetze(muell, 6)
    assert len(gitter) == len(muell)
    assert len(set(gitter)) == len(gitter), gitter
    assert all(0 <= p < 6 for p in gitter), gitter
