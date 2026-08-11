"""Playtest-Runde 2 (29.07.2026): sechs Funde aus einer Online-Serie zu zweit.

1. Streckenwechsel des Hosts kam bei den Gästen nie an — Server und
   Gast-Seite waren unschuldig, gewählt wurde erst mit der Leertaste, und das
   stand nirgends. Der Host verteilte damit reihenweise Strecken, die er nur
   angesehen hatte.
2. Die Startaufstellung ignorierte den Serienstand.
3. Nach dem letzten Lauf gab es keinen Abschluss; es ließ sich einfach
   weiterfahren.
4. Der Banner „ZIEL! Warte auf weitere Fahrzeuge" konnte einem Gast nie
   erscheinen: sein lokaler Manager kennt nur das eigene Auto und ist damit
   sofort `finished` statt `finishing`.
5. Die Serienwertung lag über der Ergebnistabelle und über dem Bildrand.
6. Der Lobby-Timeout war eine harte Obergrenze statt eines Leerlaufs und griff
   in der Übersicht gar nicht.
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


def _taste(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0)


def _gesendete_strecken(netz) -> list:
    return [m["settings"]["track_path"] for m in netz.gesendet
            if m.get("type") == "SET_SETTINGS" and "track_path" in m.get("settings", {})]


# ── 1. Streckenwahl erreicht die Gäste ──────────────────────────────────────

def test_host_verteilt_die_strecke_beim_blaettern(serie, netz):
    """Der Cursor des Hosts *ist* die Auswahl. Vorher brauchte es zusätzlich
    die Leertaste — undokumentiert, also drückte sie nie jemand."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    netz.gesendet.clear()

    seite._gp_event(_taste(pygame.K_DOWN))

    verteilt = _gesendete_strecken(netz)
    assert verteilt, "Streckenwechsel wurde nicht verteilt"
    assert seite._gp_ui.keys[1] in verteilt[-1].replace("\\", "/")


def test_gast_verteilt_beim_blaettern_nichts(serie, netz):
    """Angeschaut ist nicht gewählt — für Gäste bleibt das so."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    netz.gesendet.clear()

    seite._gp_event(_taste(pygame.K_DOWN))

    assert _gesendete_strecken(netz) == []
    assert seite._gp_ui.cursor == 1, "Blättern muss er trotzdem dürfen"


def test_leertaste_waehlt_weiterhin(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_ui.cursor = 2
    netz.gesendet.clear()

    seite._gp_event(_taste(pygame.K_SPACE))

    assert _gesendete_strecken(netz), "Leertaste darf nicht wirkungslos werden"


# ── 2. Startaufstellung nach dem Serienstand ────────────────────────────────

def _mit_stand(seite, stand: list[tuple[str, int]]):
    seite._gp_view = {
        "gp_active": True, "gp_phase": "overview", "gp_race": 2, "gp_total": 3,
        "gp_standings": [{"name": n, "points": p} for n, p in stand],
    }


def test_wertung_bestimmt_die_startaufstellung(serie, netz):
    """Namen statt Slots: die Aufstellung umfasst das ganze Feld, KI
    eingeschlossen (siehe tests/test_gp_runde4.py)."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._players = [
        {"slot": 0, "name": "Philip", "lobby_ready": True},
        {"slot": 1, "name": "philip2", "lobby_ready": True},
        {"slot": 3, "name": "Dritter", "lobby_ready": True},
    ]
    race_setup.current().ai_roster = []
    _mit_stand(seite, [("philip2", 25), ("Dritter", 18), ("Philip", 10)])

    assert seite._gp_startreihenfolge() == ["philip2", "Dritter", "Philip"]


def test_ohne_wertung_bleibt_die_bisherige_reihenfolge(serie, netz):
    """Erster Lauf: es gibt noch keinen Stand, also entscheidet der Slot."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    _mit_stand(seite, [])
    assert seite._gp_startreihenfolge() == []


def test_wiedereinsteiger_ohne_punkte_stehen_hinten(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._players = [
        {"slot": 0, "name": "Philip"},
        {"slot": 1, "name": "philip2"},
        {"slot": 2, "name": "Neu"},
    ]
    race_setup.current().ai_roster = []
    _mit_stand(seite, [("philip2", 25), ("Philip", 18)])

    assert seite._gp_startreihenfolge() == ["philip2", "Philip", "Neu"]


def test_gitterplatz_und_netzslot_bleiben_getrennt():
    """Die Ergebnistabelle liest die Bereit-Spalte über den gemeldeten Slot.
    Würde der Gitterplatz denselben Wert überschreiben, stünde dort der
    Zustand eines anderen Spielers."""
    import inspect
    from src.states.menu.online_lobby_page import OnlineLobbyPage
    quelle = inspect.getsource(OnlineLobbyPage._begin_race)
    assert "grid_slot=grid_slot" in quelle
    assert "online_slot=online_slot" in quelle

    from src.states.race_state import RaceState
    assert "grid_slot" in inspect.getsource(RaceState.enter)


# ── 3. Siegerehrung nach dem letzten Lauf ──────────────────────────────────

def test_serienende_wird_verteilt(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    assert seite._gp_settings_payload()["gp_finished"] is False

    for _ in range(3):
        serie.add_race_results([{"name": "Philip", "position": 1},
                                {"name": "philip2", "position": 2}])
        serie.next_race()

    assert seite._gp_settings_payload()["gp_finished"] is True


def test_gast_erkennt_das_serienende_am_verteilten_stand(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    assert seite._gp_ist_beendet() is False

    seite._gp_view = {"gp_active": True, "gp_phase": "overview",
                      "gp_finished": True, "gp_standings": []}
    assert seite._gp_ist_beendet() is True


def test_nach_dem_serienende_startet_kein_rennen_mehr(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_view = {"gp_active": True, "gp_finished": True, "gp_standings": []}
    netz.gesendet.clear()

    seite._request_start()

    assert "START_REQUEST" not in [m.get("type") for m in netz.gesendet]
    assert "beendet" in seite._msg


def test_bedienleiste_zeigt_nur_noch_den_abschluss(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_view = {"gp_active": True, "gp_finished": True, "gp_standings": []}
    seite._build_gp_group()

    aktionen = [w.action for w in seite._gp_group.widgets]
    assert aktionen == ["gp_leave"], "Bereit und Start gehören nach dem Ende weg"


def test_abschluss_fragt_nicht_noch_einmal_nach(serie, netz):
    """Vor dem Ende schützt die Rückfrage die Wertung. Danach gibt es nichts
    mehr zu schützen — dann ist sie nur eine Hürde."""
    seite, _sh, olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_view = {"gp_active": True, "gp_finished": True, "gp_standings": []}
    seite._build_gp_group()

    seite._ask_leave_gp()

    assert seite._dialog is None
    assert seite._view == olp._LOBBY


def test_siegerehrung_zeichnet_ohne_absturz(serie, netz):
    """Der Endstand ist der letzte Bildschirm einer Serie — er darf nicht der
    sein, auf dem das Spiel aussteigt (vgl. Fund vom 28.07. mit theme.font)."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_view = {
        "gp_active": True, "gp_finished": True, "gp_race": 3, "gp_total": 3,
        "gp_standings": [{"name": "philip2", "points": 43},
                         {"name": "Philip", "points": 31},
                         {"name": "A. Brooks", "points": 22},
                         {"name": "T. Hoffman", "points": 12}],
    }
    seite._build_gp_group()
    schirm = pygame.Surface((1920, 1080))
    seite._draw_gp_overview(schirm, pygame.Rect(0, 0, 1920, 1080))


def test_gast_baut_die_leiste_um_wenn_das_ende_hereinkommt(serie, netz):
    """Der Gast erfährt das Serienende nur über den verteilten Stand — dann
    muss auch seine Bedienleiste umschalten."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    assert seite._btn_gp_ready.enabled

    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": SPIELER, "mode": "Grand Prix",
        "settings": {"gp_active": True, "gp_phase": "overview",
                     "gp_finished": True, "gp_standings": []}}})

    assert [w.action for w in seite._gp_group.widgets] == ["gp_leave"]


def test_siegerehrung_vertraegt_zu_wenige_fahrer(serie, netz):
    """Zwei Fahrer, drei Stufen — die dritte bleibt leer statt zu krachen."""
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    schirm = pygame.Surface((1920, 1080))
    ui.draw_ceremony(schirm, gp_view={"gp_standings": [{"name": "A", "points": 5}]},
                     players=[], eigener_slot=0)


# ── 4. Ziel-Banner erreicht auch den Gast ──────────────────────────────────

def test_banner_haengt_nicht_mehr_am_zustand_finished():
    """Ein Gast hat nur sein eigenes Auto im lokalen Manager, ist also nie
    'finishing'. Ohne diese Änderung sah er den Hinweis nie."""
    import inspect
    from src.hud.hud import HUD
    quelle = inspect.getsource(HUD._render_race_finish)
    assert "not self._race_finished" not in quelle


def test_race_state_meldet_warten_auch_beim_gast():
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState)
    assert quelle.count("or self._online_awaiting") >= 2, (
        "beide HUD-Aufrufe müssen das Warten melden")


def test_wartender_gast_bekommt_gar_kein_eigenes_overlay():
    """Zuschauen war der Wunsch — nicht auf eine schwarze Scheibe starren.

    Seit 29.07.2026 zeichnet render() dafür gar nichts mehr: der Hinweis liegt
    oben mittig im HUD, die zweite Zeile unten lag quer über Tacho und
    Drehzahl."""
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState.render)
    assert "if self._online_awaiting:" not in quelle


# ── 5. Ergebnisseite ohne Überlagerung ─────────────────────────────────────

def _ergebnisseite(mit_serie: bool):
    from src.states.menu.results_page import ResultsPage
    zeilen = [{"name": "Philip", "position": 1, "is_player": True, "slot": 0,
               "vehicle": "Compact", "finish_time": 28.5, "best_lap": 28.5}]
    seite = ResultsPage(zeilen, {"is_online": True, "is_grand_prix": mit_serie})
    if mit_serie:
        seite._gp_view = {"gp_race": 1, "gp_total": 3, "gp_standings": []}
    return seite


def test_tabelle_und_wertung_ueberlappen_nicht():
    seite = _ergebnisseite(mit_serie=True)
    lx, breite, _name_w, bereit_x, cols = seite._tabellen_masse(eng=True)

    assert lx + breite <= seite.GP_SPALTE_X, "Tabelle läuft in die Wertung"
    assert bereit_x + 120 <= seite.GP_SPALTE_X, "Bereit-Spalte liegt darunter"
    for _label, x in cols:
        assert x < seite.GP_SPALTE_X


def test_wertung_bleibt_im_bild():
    seite = _ergebnisseite(mit_serie=True)
    assert seite.GP_SPALTE_X + seite.GP_SPALTE_W <= 1920


def test_ohne_serie_bleibt_die_breite_tabelle():
    seite = _ergebnisseite(mit_serie=False)
    lx, breite, _n, bereit_x, _c = seite._tabellen_masse(eng=False)
    assert (lx, breite, bereit_x) == (360, 1300, 1660)


# ── 6. Leerlauf statt harter Obergrenze ────────────────────────────────────

def test_timer_laeuft_nur_im_leerlauf(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY

    for _ in range(10):
        seite.update(1.0)
    assert seite._lobby_timer == pytest.approx(10.0)

    seite.handle_event(_taste(pygame.K_DOWN))
    assert seite._lobby_timer == 0.0, "Eingabe muss den Leerlauf zurücksetzen"


def test_servernachricht_zaehlt_als_lebenszeichen(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._lobby_timer = 400.0

    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": SPIELER, "mode": "Grand Prix",
        "settings": {"gp_active": True, "gp_phase": "overview"}}})

    assert seite._lobby_timer == 0.0


def test_uebersicht_laeuft_ebenfalls_ab(serie, netz):
    """Eine vergessene Serie hielt sonst unbegrenzt einen Lobbyplatz besetzt."""
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    assert seite._view == olp._GP_OVERVIEW

    seite.update(1.0)
    assert seite._lobby_timer == pytest.approx(1.0)


def test_vorwarnung_dreissig_sekunden_vorher(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY

    seite._lobby_timer = olp._LOBBY_IDLE_S - olp._LOBBY_WARN_S - 1.0
    seite.update(0.5)
    assert seite._warn_msg == "", "zu früh gewarnt"

    seite._lobby_timer = olp._LOBBY_IDLE_S - 20.0
    seite.update(0.5)
    assert "20" in seite._warn_msg or "19" in seite._warn_msg


def test_lobby_schliesst_erst_nach_dem_leerlauf(serie, netz):
    from src.states.menu import online_lobby_page as olp
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._view = olp._LOBBY
    seite._lobby_timer = olp._LOBBY_IDLE_S - 0.5

    seite.update(1.0)

    assert seite._view == olp._ROLE
    assert "Aktivität" in seite._msg
