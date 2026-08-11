"""Playtest-Runde 3 (29.07.2026): Serienlänge, Streckenliste, Wertung, Offline.

Funde:

1. Die Serie war nach dem vorletzten Lauf zu Ende. `is_finished` rechnete mit
   `race_index`, der nach jedem Rennen schon auf den nächsten zeigt.
2. Gäste sahen in der Lobby nicht, über wie viele Rennen es geht.
3. In der Übersicht bekamen Gäste nur ihre eigenen Streckendateien zu sehen,
   und die Wahl des Hosts wurde über Pfadvergleiche geraten — eine Strecke,
   die sie nicht hatten, sah aus wie „nichts gewählt".
4. Vor dem ersten Lauf fehlte die KI in Feld und Wertung.
5. Die Ergebnisseite zeigte den Stand VOR dem Rennen, nach dem ersten Lauf gar
   keinen.
6. Der Startknopf war bedienbar, obwohl noch nicht alle bereit waren.
7. Auf der Siegerehrung standen weiter Bereit und Start.
8. Grand Prix gab es nur online mit Übersicht.
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
    SPIELER, _NetzAttrappe, _ShellAttrappe, _seite_in_der_uebersicht,
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


def _ergebnis(name: str, pos: int) -> dict:
    return {"name": name, "position": pos}


# ── 1. Serienlänge ─────────────────────────────────────────────────────────

def test_serie_laeuft_ueber_alle_rennen(serie):
    """Der Fund: nach zwei von drei Läufen kam die Siegerehrung."""
    for lauf in range(1, 3):
        serie.add_race_results([_ergebnis("A", 1), _ergebnis("B", 2)])
        serie.next_race()
        assert not serie.is_finished, f"nach Lauf {lauf} von 3 schon beendet"

    serie.add_race_results([_ergebnis("A", 1), _ergebnis("B", 2)])
    assert serie.is_finished


def test_punkte_summieren_sich_ueber_alle_laeufe(serie):
    """Beweis am Screenshot: letzter Platz hatte nach drei Läufen 2 Punkte,
    also nur zwei gewertete Rennen."""
    from src.core.grand_prix import GP_POINTS
    for _ in range(3):
        serie.add_race_results([_ergebnis("A", 1), _ergebnis("B", 6)])
        serie.next_race()
    assert serie.points["B"] == 3 * GP_POINTS.get(6, 0)
    assert len(serie.history) == 3


# ── 2. Serienlänge in der Lobby ────────────────────────────────────────────

def test_serienlaenge_reist_immer_mit(serie, netz):
    """Auch vor dem Start der Serie — sonst sieht ein Gast in der Lobby nicht,
    worauf er sich einlässt."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_races_stepper.index = seite._gp_races_stepper.options.index("7")
    netz.gesendet.clear()

    seite._push_settings()

    letzte = [m for m in netz.gesendet if m.get("type") == "SET_SETTINGS"][-1]
    assert letzte["settings"]["gp_races"] == 7


def test_gast_sieht_die_serienlaenge_in_der_lobby(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._view = olp._LOBBY
    seite._gp_view = {"gp_races": 5}
    seite._selected_mode = "Grand Prix"

    schirm = pygame.Surface((1920, 1080))
    seite._draw_lobby(schirm, pygame.Rect(0, 0, 1920, 1080))   # darf nicht krachen


# ── 3. Streckenliste kommt vom Host ────────────────────────────────────────

def test_host_verteilt_liste_und_gewaehlten_schluessel(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_pick_track(1)

    einst = [m for m in netz.gesendet if m.get("type") == "SET_SETTINGS"][-1]["settings"]
    assert einst["gp_track_key"] == seite._gp_ui.keys[1]
    schluessel = [e["key"] for e in einst["gp_tracks"]]
    assert schluessel == seite._gp_ui.keys
    assert all("centerline" not in e for e in einst["gp_tracks"]), (
        "Streckenverlauf gehört nicht in einen Block, der bei jeder Änderung mitreist")


def test_gast_uebernimmt_die_liste_des_hosts(serie, netz):
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    geaendert = ui.set_host_tracks([
        {"key": "oval", "name": "Oval"},
        {"key": "custom/host_only", "name": "Nur beim Host", "is_custom": True},
    ])

    assert geaendert
    assert ui.keys == ["oval", "custom/host_only"]
    assert ui.name_of("custom/host_only") == "Nur beim Host"


def test_gleiche_liste_baut_nichts_neu(serie, netz):
    """Sonst springt bei jeder Servernachricht der Cursor zurück."""
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    eintraege = [{"key": "oval", "name": "Oval"}, {"key": "desert", "name": "Wüste"}]
    assert ui.set_host_tracks(eintraege) is True
    ui.cursor = 1
    assert ui.set_host_tracks(eintraege) is False
    assert ui.cursor == 1


def test_fremde_strecke_zeichnet_ohne_verlauf(serie, netz):
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    ui.set_host_tracks([{"key": "custom/nicht_da", "name": "Fremde Strecke"}])
    schirm = pygame.Surface((1920, 1080))
    ui.draw(schirm, gewaehlt_key="custom/nicht_da", ist_host=False,
            gp_view={"gp_race": 1, "gp_total": 3, "gp_standings": []},
            players=SPIELER, eigener_slot=1)


def test_gast_markiert_nach_schluessel_nicht_nach_pfad(serie, netz):
    """Der Pfad des Hosts sagt einem Gast nichts, wenn er die Datei nicht hat."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._gp_view = {
        "gp_active": True, "gp_phase": "overview", "gp_standings": [],
        "gp_tracks": [{"key": "custom/host_only", "name": "Nur beim Host"}],
        "gp_track_key": "custom/host_only",
    }
    schirm = pygame.Surface((1920, 1080))
    seite._draw_gp_overview(schirm, pygame.Rect(0, 0, 1920, 1080))

    assert seite._gp_ui.keys == ["custom/host_only"]


# ── 4. KI gehört ins Feld ──────────────────────────────────────────────────

def test_ki_steht_vor_dem_ersten_lauf_im_feld(serie, netz):
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    schirm = pygame.Surface((1920, 1080))
    ui.draw(schirm, gewaehlt_key="oval", ist_host=True,
            gp_view={"gp_race": 1, "gp_total": 3, "gp_standings": [],
                     "ai_roster": [{"name": "A. Brooks", "vehicle": "rookie"}]},
            players=SPIELER, eigener_slot=0)


def test_ki_roster_reist_in_den_einstellungen(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    netz.gesendet.clear()
    seite._push_settings()
    einst = [m for m in netz.gesendet if m.get("type") == "SET_SETTINGS"][-1]["settings"]
    assert "ai_roster" in einst


# ── 5. Wertung auf der Ergebnisseite ist die nach dem Rennen ───────────────

def test_host_reicht_die_frische_wertung_nach(serie, netz, monkeypatch):
    """race_state trägt die Punkte ein, die Ergebnisseite zeigte aber den
    Stand, den der Server zuletzt verteilt hatte — also den von vorher."""
    from src.net import session
    from src.states.menu.results_page import ResultsPage

    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    monkeypatch.setattr(session, "get_lobby_page", lambda: seite)
    serie.add_race_results([_ergebnis("Philip", 1), _ergebnis("philip2", 2)])

    ergebnis = ResultsPage(
        [{"name": "Philip", "position": 1, "is_player": True, "slot": 0}],
        {"is_online": True})
    ergebnis.enter(_ShellAttrappe())

    stand = {e["name"]: e["points"] for e in ergebnis._gp_view["gp_standings"]}
    assert stand["Philip"] == 10, "Ergebnisseite zeigt den Stand vor dem Rennen"


def test_gast_liest_die_wertung_laufend_nach(serie, netz, monkeypatch):
    """Die Lobby-Seite ERSETZT ihr _gp_view bei jeder LOBBY_STATE. Einmal
    festgehalten wäre der Stand für immer der vom Öffnen."""
    from src.net import session
    from src.states.menu.results_page import ResultsPage

    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    monkeypatch.setattr(session, "get_lobby_page", lambda: seite)
    seite._gp_view = {"gp_active": True, "gp_standings": [{"name": "A", "points": 0}]}

    ergebnis = ResultsPage([{"name": "A", "position": 1}], {"is_online": True})
    ergebnis.enter(_ShellAttrappe())

    seite._gp_view = {"gp_active": True, "gp_standings": [{"name": "A", "points": 10}]}
    ergebnis.update(0.016)

    assert ergebnis._gp_view["gp_standings"][0]["points"] == 10


# ── 6./7. Startknopf und Siegerehrung ──────────────────────────────────────

def test_startknopf_gesperrt_solange_nicht_alle_bereit(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._players = [{"slot": 0, "name": "Philip", "lobby_ready": True},
                      {"slot": 1, "name": "philip2", "lobby_ready": False}]
    seite._update_gp_start_button()

    assert seite._btn_gp_start.enabled is False
    assert seite._btn_gp_start.hint, "gesperrt ohne Begründung"

    seite._players[1]["lobby_ready"] = True
    seite._update_gp_start_button()
    assert seite._btn_gp_start.enabled is True
    assert seite._btn_gp_start.hint == ""


def test_gesperrter_knopf_zeigt_die_begruendung_beim_zeigen():
    from src.ui.widgets import Button
    knopf = Button(pygame.Rect(0, 0, 100, 40), "Start", "start",
                   enabled=False, hint="Alle müssen bereit sein")
    schirm = pygame.Surface((200, 200))
    knopf.draw(schirm, focused=False)     # zeichnet je nach Mausposition


def test_siegerehrung_ohne_bereit_und_start(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    for _ in range(3):
        serie.add_race_results([_ergebnis("Philip", 1), _ergebnis("philip2", 2)])
        serie.next_race()
    seite._build_gp_group()

    assert [w.action for w in seite._gp_group.widgets] == ["gp_leave"]


# ── 8. Grand Prix offline mit Übersicht ────────────────────────────────────

def _offline_seite(mehrspieler: bool = False):
    from src.states.menu.gp_overview_page import GPOverviewPage
    s = race_setup.current()
    s.mode = "Grand Prix"
    s.is_multiplayer = mehrspieler
    sh = _ShellAttrappe()
    seite = GPOverviewPage()
    seite.enter(sh)
    return seite, sh


def test_offline_uebersicht_waehlt_die_strecke(serie):
    seite, _sh = _offline_seite()
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,
                                          unicode="", mod=0))
    assert seite.ui.cursor == 1
    assert seite.ui.keys[1] in str(race_setup.current().track_path).replace("\\", "/")


def test_offline_uebersicht_startet_das_rennen(serie):
    seite, sh = _offline_seite()
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                                          unicode="\r", mod=0))
    assert sh.wechsel and sh.wechsel[0][0] == "race"


def test_offline_uebersicht_zeigt_den_stand(serie):
    seite, _sh = _offline_seite()
    serie.add_race_results([_ergebnis("Philip", 1), _ergebnis("A. Brooks", 2)])
    ansicht = seite._gp_view()

    assert ansicht["gp_standings"][0]["name"] == "Philip"
    assert ansicht["gp_total"] == 3


def test_offline_uebersicht_endet_mit_der_siegerehrung(serie):
    seite, _sh = _offline_seite()
    for _ in range(3):
        serie.add_race_results([_ergebnis("Philip", 1)])
        serie.next_race()

    assert seite._ist_beendet()
    seite._rebuild_group()
    assert [w.action for w in seite.group.widgets] == ["gp_leave"]

    schirm = pygame.Surface((1920, 1080))
    seite.draw(schirm, pygame.Rect(0, 0, 1920, 1080))


def test_offline_uebersicht_ohne_tab_leiste(serie):
    seite, _sh = _offline_seite()
    assert seite.hides_tab_bar() is True


def test_lokaler_mehrspieler_zeigt_beide_fahrer(serie):
    seite, _sh = _offline_seite(mehrspieler=True)
    namen = [p["name"] for p in seite._spieler()]
    assert len(namen) == 2


def test_fahrzeugwahl_fuehrt_bei_grand_prix_in_die_uebersicht(serie):
    """Sonst startet die Streckenauswahl direkt ins Rennen und die Serie hat
    keinen Ort, an dem sie zwischen den Läufen steht."""
    import inspect
    from src.states.car_select_state import CarSelectState
    quelle = inspect.getsource(CarSelectState._weiter_nach_fahrzeugwahl)
    assert 'reopen="gp_overview"' in quelle
    assert "grand_prix.is_active()" in quelle


def test_abbruch_fragt_vorher_nach(serie):
    seite, _sh = _offline_seite()
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                          unicode="", mod=0))
    assert seite._dialog is not None
    assert grand_prix.is_active(), "Serie darf erst nach der Bestätigung weg"
