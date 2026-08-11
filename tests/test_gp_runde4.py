"""Playtest-Runde 4 (29.07.2026): Startaufstellung, leere Spalte, DNF-Frist.

1. Die Startaufstellung nach dem Serienstand griff nicht. Sie sortierte nur
   die Menschen um — die belegen aber ohnehin die vorderen Plätze, der Vierte
   der Wertung stand damit weiter in Reihe eins. Bei zwei Menschen und vier
   KI-Autos war der Effekt praktisch nicht vorhanden.
2. Die Spalte „Bereit" im Grand-Prix-Ergebnis blieb leer: sie gehört zur
   Revanche-Abstimmung, die es dort nicht gibt.
3. Die DNF-Frist lief unsichtbar ab. Sie bleibt die alte Rechnung (langsamste
   Runde des Führenden); heruntergezählt werden die letzten fünf Sekunden.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402
from src.core.race_setup import AIDriver  # noqa: E402
from tests.test_gp_online_start import (  # noqa: E402
    _NetzAttrappe, _seite_in_der_uebersicht,
)


@pytest.fixture
def serie():
    grand_prix.cancel()
    race_setup.current().mode = "Grand Prix"
    yield grand_prix.start_series(3, 3)
    grand_prix.cancel()
    race_setup.current().ai_roster = []


@pytest.fixture
def netz(monkeypatch):
    from src.net import session
    n = _NetzAttrappe()
    monkeypatch.setattr(session, "get", lambda: n)
    return n


# ── 1. Startaufstellung über das ganze Feld ────────────────────────────────

def test_reihenfolge_umfasst_mensch_und_ki():
    """Der Kern des Fundes: nur Menschen umzusortieren ändert nichts, weil die
    ohnehin vorn stehen."""
    stand = ["E. Krüger", "philip2", "H. Braun", "Philip"]
    feld = ["Philip", "philip2", "E. Krüger", "H. Braun"]
    assert grand_prix.startreihenfolge(stand, feld) == [
        "E. Krüger", "philip2", "H. Braun", "Philip"]


def test_wer_noch_nicht_gewertet_ist_haengt_hinten_dran():
    stand = ["philip2", "Philip"]
    feld = ["Philip", "philip2", "Frisch dazu", "Auch neu"]
    assert grand_prix.startreihenfolge(stand, feld) == [
        "philip2", "Philip", "Frisch dazu", "Auch neu"]


def test_namen_ausserhalb_des_feldes_bekommen_keinen_platz():
    """Ein Fahrer, der die Serie verlassen hat, steht weiter in der Wertung —
    aber nicht mehr auf der Strecke."""
    stand = ["Weg", "Philip"]
    feld = ["Philip"]
    assert grand_prix.startreihenfolge(stand, feld) == ["Philip"]


def test_doppelte_namen_zaehlen_einmal():
    """Sonst fällt hinten ein Platz weg und zwei Autos teilen sich einen."""
    assert grand_prix.startreihenfolge(["A"], ["A", "A", "B"]) == ["A", "B"]


def test_seite_rechnet_ueber_das_ganze_feld(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._players = [{"slot": 0, "name": "Philip"}, {"slot": 1, "name": "philip2"}]
    race_setup.current().ai_roster = [AIDriver(name="E. Krüger"),
                                      AIDriver(name="H. Braun")]
    seite._gp_view = {"gp_standings": [{"name": "E. Krüger", "points": 25},
                                       {"name": "philip2", "points": 18},
                                       {"name": "H. Braun", "points": 15},
                                       {"name": "Philip", "points": 12}]}

    assert seite._gp_startreihenfolge() == [
        "E. Krüger", "philip2", "H. Braun", "Philip"]


def test_host_verteilt_gitterplaetze_fuer_seine_ki(serie, netz):
    """Nur der Host baut die KI-Autos — er muss sie auch setzen."""
    import types
    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._players = [{"slot": 0, "name": "Philip"}, {"slot": 1, "name": "philip2"}]
    race_setup.current().ai_roster = [AIDriver(name="E. Krüger"),
                                      AIDriver(name="H. Braun")]
    seite._gp_view = {"gp_standings": [{"name": "E. Krüger", "points": 25},
                                       {"name": "philip2", "points": 18},
                                       {"name": "H. Braun", "points": 15},
                                       {"name": "Philip", "points": 12}]}
    seite._selected_track_path = os.path.join(_ROOT, "data", "tracks", "oval.json")
    seite._roster_size = 4
    seite._race_begun = False

    seite._begin_race({})

    _name, kw = sh.wechsel[-1]
    assert kw["grid_slot"] == 3, "Host ist Vierter der Wertung"
    assert kw["ai_grid_slots"] == [0, 2]


def test_gast_setzt_keine_ki(serie, netz):
    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._players = [{"slot": 0, "name": "Philip"}, {"slot": 1, "name": "philip2"}]
    race_setup.current().ai_roster = [AIDriver(name="E. Krüger")]
    seite._gp_view = {"gp_standings": [{"name": "philip2", "points": 18},
                                       {"name": "E. Krüger", "points": 15},
                                       {"name": "Philip", "points": 12}]}
    seite._selected_track_path = os.path.join(_ROOT, "data", "tracks", "oval.json")
    seite._race_begun = False

    seite._begin_race({})

    _name, kw = sh.wechsel[-1]
    assert kw["grid_slot"] == 0, "Gast führt die Wertung an"
    assert kw["ai_grid_slots"] is None


# Die Gitterplaetze werden seit dem 31.07.2026 an EINER Stelle vergeben
# (RaceState.gitterplaetze). Die Wunschliste steht in der Reihenfolge, in der
# die Fahrzeuge gebaut werden: Spieler 1, (Spieler 2), dann die KI.

def test_rennen_setzt_die_ki_auf_die_vorgegebenen_plaetze():
    from src.states.race_state import RaceState
    # Zwei Menschen auf 1 und 3, zwei gewertete KI auf 0 und 2.
    plaetze = RaceState.gitterplaetze([1, 3, 0, 2], 6)
    assert plaetze[2:] == [0, 2]


def test_ohne_vorgabe_fuellt_die_ki_hinter_den_menschen_auf():
    from src.states.race_state import RaceState
    plaetze = RaceState.gitterplaetze([None, None, None, None, None], 6)
    assert plaetze == [0, 1, 2, 3, 4]


def test_frisch_ergaenzte_ki_bekommt_den_naechsten_freien_platz():
    """Eine KI, die noch in keiner Wertung steht, darf keinen belegten Platz
    erben — sonst stehen zwei Autos übereinander."""
    from src.states.race_state import RaceState
    plaetze = RaceState.gitterplaetze([1, 3, 0, None], 6)
    assert plaetze[2] == 0
    assert len(set(plaetze)) == 4, plaetze


def test_ki_ohne_wertung_landet_nie_auf_dem_platz_eines_menschen():
    """Der Fehler der alten Vergabe: sie zaehlte ab ``human_count`` hoch und
    kannte die tatsaechlichen Plaetze der Menschen nicht. Standen die laut
    Grand-Prix-Wertung weiter hinten, bekam eine ungewertete KI ihren Platz.
    """
    from src.states.race_state import RaceState
    for menschen in ([1, 3], [2, 4], [3, 5], [0, 5]):
        plaetze = RaceState.gitterplaetze(list(menschen) + [None, None], 6)
        ki = plaetze[2:]
        assert not (set(ki) & set(menschen)), f"{menschen} vs {ki}"
        assert len(set(plaetze)) == 4


def test_zwei_menschen_teilen_sich_nie_einen_platz():
    """Der gemeldete Fehler: im lokalen Mehrspieler-Grand-Prix stand Spieler 1
    nach dem ersten Lauf auf Platz 1 der Wertung, Spieler 2 war fest auf
    Gitterplatz 1 verdrahtet — beide Autos spawnten ineinander."""
    from src.states.race_state import RaceState
    for wunsch_p1 in range(6):
        plaetze = RaceState.gitterplaetze([wunsch_p1, None, None, None], 6)
        assert plaetze[0] == wunsch_p1
        assert plaetze[0] != plaetze[1], f"P1 und P2 auf {plaetze[0]}"
        assert len(set(plaetze)) == 4, plaetze


def test_beide_spieler_mit_wunsch_bekommen_ihn():
    from src.states.race_state import RaceState
    assert RaceState.gitterplaetze([1, 0, None, None], 6)[:2] == [1, 0]
    assert RaceState.gitterplaetze([3, 2, None, None], 6)[:2] == [3, 2]


def test_offline_startet_ebenfalls_nach_der_wertung(serie):
    import types
    from src.states.menu.gp_overview_page import GPOverviewPage

    s = race_setup.current()
    s.is_multiplayer = False
    s.ai_roster = [AIDriver(name="E. Krüger"), AIDriver(name="H. Braun")]

    sh = types.SimpleNamespace(
        state_machine=types.SimpleNamespace(transition=lambda n, **kw: None),
        page_stack=[], tab=0)
    wechsel = []
    sh.state_machine.transition = lambda n, **kw: wechsel.append((n, kw))
    seite = GPOverviewPage()
    seite.enter(sh)

    from src.core import profile
    ich = (profile.current().username or "Spieler").strip()
    serie.add_race_results([{"name": "E. Krüger", "position": 1},
                            {"name": "H. Braun", "position": 2},
                            {"name": ich, "position": 3}])

    seite._starten()
    _name, kw = wechsel[-1]
    assert kw["grid_slot"] == 2
    assert kw["ai_grid_slots"] == [0, 1]


# ── 2. Leere Spalte im Grand-Prix-Ergebnis ─────────────────────────────────

def test_ergebnis_ohne_bereit_spalte_bei_grand_prix():
    import inspect
    from src.states.menu.results_page import ResultsPage
    quelle = inspect.getsource(ResultsPage._draw_normal)
    assert 'self.meta.get("is_online") and not eng' in quelle


def test_normales_online_rennen_behaelt_die_spalte():
    """Dort ist sie die Revanche-Abstimmung und wird gebraucht."""
    from src.states.menu.results_page import ResultsPage
    seite = ResultsPage([], {"is_online": True})
    _lx, _b, _n, bereit_x, _c = seite._tabellen_masse(eng=False)
    assert bereit_x == 1660


# ── 3. DNF-Frist mit sichtbarem Countdown ──────────────────────────────────

def test_countdown_dauert_fuenf_sekunden():
    from src.states.race_manager import RaceManager
    assert RaceManager.DNF_COUNTDOWN_SECONDS == 5.0


def test_server_bekommt_weiterhin_die_volle_frist():
    """Der Countdown ist nur Anzeige — die Frist selbst bleibt die langsamste
    Runde des Führenden, und der Server muss dieselbe kennen."""
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState.update)
    assert '"slowest_lap": self.race_manager.leader_slowest_lap()' in quelle


def test_nur_wer_noch_faehrt_sieht_den_countdown():
    import types
    from src.states.race_state import RaceState

    zustand = RaceState.__new__(RaceState)
    zustand.race_manager = types.SimpleNamespace(
        finished_ids={1}, sekunden_bis_dnf=lambda: 3.0)

    assert zustand._dnf_restzeit(1) is None, "im Ziel, also keine Frist mehr"
    assert zustand._dnf_restzeit(2) == 3.0


def test_hud_zeigt_den_countdown_statt_der_wartemeldung():
    import inspect
    from src.hud.hud import HUD
    quelle = inspect.getsource(HUD._render_race_finish)
    assert "_render_dnf_countdown" in quelle
    assert quelle.index("_dnf_seconds is not None") < quelle.index("_waiting_for_field")


def test_countdown_zeichnet_ohne_absturz():
    from src.hud.hud import HUD
    hud = HUD()
    hud._dnf_seconds = 2.4
    schirm = pygame.Surface((1920, 1080))
    hud._render_race_finish(schirm, 1920, 1080, 1.0)
