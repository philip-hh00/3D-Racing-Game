"""Online-Grand-Prix: nach dem Lauf muss der Host zurück in die Lobby.

Playtest-Fund vom 28.07.2026: nach dem ersten Lauf kam der Gast nicht ins
nächste Rennen, sah keine Zwischenstände, und der Host hing endlos in
„Warte auf andere Fahrer".

Ursache war eine einzige Zeile: „Nächstes Rennen" schaltete den Host **immer**
in die Streckenauswahl — auch online. Dort startet ein Rennen direkt und lokal.
Der Host verließ damit den Lobby-Ablauf, während die Gäste noch in der Lobby
saßen, und wartete anschließend auf Mitspieler, die nie kommen konnten.

Online gehört jeder dieser Wege zurück in die Lobby: dort wählt der Host die
Strecke und startet über den normalen Bereit-Ablauf, sodass alle mitkommen.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# pygame wird in tests/conftest.py einmalig fuer den ganzen Lauf gestartet.

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402
from src.states.menu.results_page import ResultsPage  # noqa: E402


class _ShellAttrappe:
    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []
        self.state_machine = types.SimpleNamespace(
            transition=lambda name, **kw: self.wechsel.append((name, kw)))
        self.page_stack: list = []
        self.tab = 0

    def pop_page(self) -> None:
        pass


def _zeile(name: str, pos: int, spieler: bool = False) -> dict:
    return {"name": name, "position": pos, "is_player": spieler, "is_player2": False,
            "vehicle": "rookie", "finish_time": 60.0 + pos, "best_lap": 20.0,
            "lap": "3/3", "gap": "-", "best": "20.0", "pos": pos, "gp": "0"}


ZEILEN = [_zeile("Host", 1, True), _zeile("Gast", 2)]


@pytest.fixture
def serie():
    grand_prix.cancel()
    race_setup.current().mode = "Grand Prix"
    yield grand_prix.start_series(3, 3)
    grand_prix.cancel()


def _seite(online: bool) -> tuple[ResultsPage, _ShellAttrappe]:
    sh = _ShellAttrappe()
    seite = ResultsPage(ZEILEN, {"is_grand_prix": True, "is_online": online,
                                 "track_key": "oval"})
    seite.enter(sh)
    return seite, sh


def _enter():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r", mod=0)


def test_naechstes_rennen_online_geht_in_die_lobby(serie):
    serie.add_race_results(ZEILEN)
    seite, sh = _seite(online=True)
    seite.handle_event(_enter())
    assert sh.wechsel == [("menu", {"reopen": "online_lobby_resume"})], (
        "Online darf NICHT in die Streckenauswahl - dort startet ein lokales "
        "Rennen ohne die Mitspieler")


def test_naechstes_rennen_offline_geht_in_die_uebersicht(serie):
    """Seit 29.07.2026 auch offline: die Übersicht führt die Serie, dort steht
    der Zwischenstand und wird die nächste Strecke gewählt. Die
    Streckenauswahl kennt beides nicht."""
    serie.add_race_results(ZEILEN)
    seite, sh = _seite(online=False)
    seite.handle_event(_enter())
    assert sh.wechsel == [("menu", {"reopen": "gp_overview"})]


def test_serie_schaltet_in_beiden_faellen_weiter(serie):
    serie.add_race_results(ZEILEN)
    assert serie.race_index == 0
    seite, _sh = _seite(online=True)
    seite.handle_event(_enter())
    assert serie.race_index == 1


def test_serienende_online_geht_in_die_lobby(serie):
    for _ in range(3):
        serie.add_race_results(ZEILEN)
        serie.next_race()
    seite, sh = _seite(online=True)
    assert [getattr(w, "action", None) for w in seite.group.widgets] == ["finish_gp"]
    seite.handle_event(_enter())
    assert sh.wechsel == [("menu", {"reopen": "online_lobby_resume"})]
    assert not grand_prix.is_active()


def test_serienende_offline_geht_in_die_siegerehrung(serie):
    """Die Serie endet nicht mehr wortlos in der Lobby: die Übersicht zeigt
    erst den Endstand, abgeräumt wird sie dort per Knopf."""
    for _ in range(3):
        serie.add_race_results(ZEILEN)
        serie.next_race()
    race_setup.current().is_multiplayer = False
    seite, sh = _seite(online=False)
    seite.handle_event(_enter())
    assert sh.wechsel == [("menu", {"reopen": "gp_overview"})]
    assert grand_prix.is_active(), "Wertung wird erst nach der Ehrung verworfen"


# ── Abbruchknopf beim Warten auf die Mitspieler ─────────────────────────────

def test_knopf_erscheint_erst_nach_kurzer_wartezeit():
    """Bewusst kein automatischer Abbruch: die Gegenseite lädt womöglich noch
    eine übertragene Strecke und rechnet Ideallinien. Ein Timer würde
    funktionierende Rennen zerreißen — der Host sieht die Lage und entscheidet."""
    from src.states.race_state import HOLD_ABORT_BUTTON_AFTER_S
    assert 2.0 <= HOLD_ABORT_BUTTON_AFTER_S <= 10.0


def _wartender_host():
    from src.states.race_state import RaceState
    sm = types.SimpleNamespace(transition=lambda *a, **k: None)
    state = RaceState(sm)
    state._online = True
    state._my_online_slot = 0
    state._players_is_host = True
    state.race_manager = types.SimpleNamespace(state="countdown", _hold_countdown=True)
    state._load_failed = ""
    return state, sm


def test_wartebeginn_wird_gemerkt_und_zurueckgesetzt():
    import time
    state, _sm = _wartender_host()
    vorher = time.time()
    try:
        state.update(0.016)
    except Exception:
        pass                      # der Rest von update() interessiert hier nicht
    assert vorher - 1 <= state._hold_since <= vorher + 1

    state.race_manager = types.SimpleNamespace(state="racing", _hold_countdown=False)
    try:
        state.update(0.016)
    except Exception:
        pass
    assert state._hold_since == 0.0
    assert state._hold_abort_btn is None


def test_knopf_erscheint_erst_nach_der_wartezeit_und_nur_beim_host():
    import time
    from src.states.race_state import HOLD_ABORT_BUTTON_AFTER_S
    state, _sm = _wartender_host()
    state._is_online_host = lambda: True

    state._hold_since = time.time()
    assert state._update_hold_abort_button() is False, "zu frueh"
    assert state._hold_abort_btn is None

    state._hold_since = time.time() - (HOLD_ABORT_BUTTON_AFTER_S + 1)
    assert state._update_hold_abort_button() is True
    assert state._hold_abort_btn is not None

    # Gast bekommt ihn nie - er kann das Rennen ohnehin nicht neu starten.
    state._is_online_host = lambda: False
    assert state._update_hold_abort_button() is False
    assert state._hold_abort_btn is None


def test_knopf_verschwindet_sobald_nicht_mehr_gewartet_wird():
    import time
    from src.states.race_state import HOLD_ABORT_BUTTON_AFTER_S
    state, _sm = _wartender_host()
    state._is_online_host = lambda: True
    state._hold_since = time.time() - (HOLD_ABORT_BUTTON_AFTER_S + 1)
    assert state._update_hold_abort_button() is True

    state._hold_since = 0.0
    assert state._update_hold_abort_button() is False
    assert state._hold_abort_btn is None


def test_abbruch_fuehrt_in_die_lobby_mit_begruendung():
    from src.states.race_state import RaceState
    gewechselt = []
    sm = types.SimpleNamespace(
        transition=lambda name, **kw: gewechselt.append((name, kw)))
    state = RaceState(sm)
    state._online = True
    state._abort_held_race()
    assert gewechselt[0][0] == "menu"
    assert gewechselt[0][1]["reopen"] == "online_lobby_resume"
    assert gewechselt[0][1]["lobby_msg"]           # Grund wird genannt
    assert state._hold_since == 0.0
    assert state._hold_abort_btn is None


# ── Fahreranzahl und Wartebildschirm ────────────────────────────────────────

def test_bis_zu_sechs_fahrzeuge_in_jedem_online_modus():
    from src.states.menu.online_lobby_page import _SIZE_OPTIONS, _SIZE_OPTIONS_TEAM
    assert max(_SIZE_OPTIONS) == 6
    assert max(_SIZE_OPTIONS_TEAM) == 6


def test_team_modus_nur_gerade_zahlen():
    """Zwei gleich grosse Teams gehen mit ungeraden Zahlen nicht auf."""
    from src.states.menu.online_lobby_page import _SIZE_OPTIONS_TEAM
    assert all(n % 2 == 0 for n in _SIZE_OPTIONS_TEAM)


def test_server_akzeptiert_dieselben_groessen_wie_der_client():
    """Sonst schreibt der Server die Auswahl still zurueck — genau der Fehler,
    der Grand Prix online zu einem normalen Rennen gemacht hat."""
    import os
    import sys
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    from src.states.menu.online_lobby_page import _SIZE_OPTIONS
    for n in _SIZE_OPTIONS:
        assert n in srv.VALID_ROSTER, f"Server lehnt {n} Fahrzeuge ab"


def test_server_akzeptiert_dieselben_modi_wie_der_client():
    import os
    import sys
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    from src.states.menu.online_lobby_page import _MODE_KEYS
    for modus in _MODE_KEYS:
        assert modus in srv.VALID_MODES, f"Server lehnt Modus {modus!r} ab"


def test_gast_bekommt_beim_warten_denselben_hintergrund():
    """Gäste überspringen die Ideallinien-Berechnung und hatten deshalb kein
    Ladevideo — ihr Bildschirm zeigte die fertige Strecke unter einem Overlay,
    sie standen gefühlt schon im Rennen."""
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState._build_racing_lines_optimized)
    kopf = quelle[:quelle.index("for car_idx")]
    assert "_open_loading_video" in kopf
    assert "self._online" in kopf


# ── Grand-Prix-Übersicht als eigene Ebene ───────────────────────────────────

def _online_seite(ist_host: bool):
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers
    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = ist_host
    seite._view = olp._LOBBY
    seite._players = [
        {"slot": 0, "name": "Philip", "lobby_ready": True, "vehicle": "rookie"},
        {"slot": 1, "name": "philip2", "lobby_ready": False, "vehicle": "drifter"},
    ]
    return seite, olp


def test_uebersicht_kennt_eingebaute_und_eigene_strecken():
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    assert {"oval", "desert", "city", "mountain", "gp"} <= set(ui.keys)


def test_host_betritt_die_uebersicht(serie):
    seite, olp = _online_seite(ist_host=True)
    seite._enter_gp_overview()
    assert seite._view == olp._GP_OVERVIEW
    assert seite._gp_phase == "overview"


def test_gast_folgt_der_verteilten_phase(serie):
    """Ohne das säße der Gast in der Lobby, während der Host die Strecke wählt."""
    seite, olp = _online_seite(ist_host=False)
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": seite._players, "mode": "Grand Prix",
        "settings": {"gp_active": True, "gp_phase": "overview",
                     "gp_race": 2, "gp_total": 3, "gp_standings": []},
    }})
    assert seite._view == olp._GP_OVERVIEW


def test_gast_kehrt_zurueck_wenn_die_serie_endet(serie):
    seite, olp = _online_seite(ist_host=False)
    seite._enter_gp_overview()
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": seite._players, "mode": "Rennen",
        "settings": {"gp_active": False},
    }})
    assert seite._view == olp._LOBBY


def test_gast_darf_blaettern_ohne_auszuwaehlen(serie):
    """Angeschaut ist nicht gewählt — sonst hält ein Gast seine Ansicht für
    die Entscheidung des Hosts."""
    seite, _olp = _online_seite(ist_host=False)
    seite._enter_gp_overview()
    vorher = seite._selected_track_path
    seite._gp_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,
                                       unicode="", mod=0))
    assert seite._gp_ui.cursor == 1
    assert seite._selected_track_path == vorher


def test_host_waehlt_die_strecke_aus(serie):
    seite, _olp = _online_seite(ist_host=True)
    seite._enter_gp_overview()
    seite._gp_pick_track(2)
    assert seite._gp_ui.keys[2] in str(seite._selected_track_path).replace("\\", "/")


def test_verlassen_fragt_vorher_nach(serie):
    for ist_host in (True, False):
        seite, _olp = _online_seite(ist_host=ist_host)
        seite._enter_gp_overview()
        seite._gp_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE,
                                           unicode="", mod=0))
        assert seite._dialog is not None, "Verlassen ohne Rückfrage"


def test_server_laesst_frueheres_mitglied_waehrend_des_rennens_zurueck():
    """Wer mitten im Rennen aussteigt, landet direkt in der Übersicht."""
    import inspect
    import os
    import sys
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    quelle = inspect.getsource(srv._handle_tcp)
    assert "frueheres_mitglied" in quelle
