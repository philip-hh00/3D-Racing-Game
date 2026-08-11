"""Grand Prix online: der Rennstart muss auch aus der Übersicht heraus greifen.

Playtest-Fund: der Host blieb auf „Übertrage Strecke …" stehen, während der
Gast ins Rennen wechselte. Gemessen mit zwei Seiten gegen einen lokalen Relay:

    Host msg    : 'Übertrage Strecke …'
    Gast Wechsel: ['race']
    Host Wechsel: []

Der Server ist entlastet — er verschickt START an alle. Hängen bleibt, wer in
der Grand-Prix-Übersicht steht: dort pumpte `update()` die Netzsitzung nicht,
also wurden START (und jede andere Nachricht) nie abgeholt. Der Host ist
zwangsläufig betroffen, weil er den Lauf aus der Übersicht startet; ein Gast,
der noch in der Lobby saß, kam durch.

Die Tests hier fahren die Seite über `update()` — genau den Weg, den das Spiel
pro Bild geht. Wer stattdessen `_on_net` direkt füttert, überspringt die
kaputte Stelle und sieht den Fehler nicht.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import grand_prix, race_setup  # noqa: E402


class _ShellAttrappe:
    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []
        self.state_machine = types.SimpleNamespace(
            transition=lambda name, **kw: self.wechsel.append((name, kw)))
        self.page_stack: list = []
        self.tab = 0

    def pop_page(self) -> None:
        pass


class _NetzAttrappe:
    """Ersetzt die TCP-Sitzung: merkt sich Gesendetes, gibt Vorbereitetes aus.

    Kein Monkeypatch auf session.set() nötig, weil hier gar keine echte
    Verbindung entsteht — die Seite holt ihre Sitzung ausschließlich über
    session.get().
    """

    def __init__(self, slot: int = 0) -> None:
        self.slot = slot
        self.ping_ms = 42.0       # von der Lobby-Anzeige gelesen
        self.gesendet: list[dict] = []
        self.eingang: list[dict] = []
        self.update_aufrufe = 0
        self.hochgeladen: list[str] = []

    # ── vom Spiel benutzt ────────────────────────────────────────────────
    def send_tcp(self, msg: dict) -> None:
        self.gesendet.append(msg)

    def update(self, dt: float) -> None:
        self.update_aufrufe += 1

    def poll(self):
        while self.eingang:
            yield self.eingang.pop(0)

    def upload_map(self, pfad: str) -> None:
        self.hochgeladen.append(pfad)

    def upload_offer(self, pfad: str, titel: str = "") -> None:
        self.hochgeladen.append((pfad, titel))

    def request_offer(self, slot: int) -> None:
        self.gesendet.append({"type": "OFFER_REQUEST", "slot": slot})

    def set_lobby(self, *a, **kw) -> None:
        pass

    def register_udp(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    # ── Testhilfe ────────────────────────────────────────────────────────
    def zustellen(self, data: dict) -> None:
        self.eingang.append({"source": "tcp", "data": data})


SPIELER = [
    {"slot": 0, "name": "Philip", "lobby_ready": True, "vehicle": "rookie"},
    {"slot": 1, "name": "philip2", "lobby_ready": True, "vehicle": "drifter"},
]


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


def _seite_in_der_uebersicht(ist_host: bool, netz: _NetzAttrappe):
    """Seite im Zustand kurz vor dem Rennstart: Serie läuft, Übersicht offen."""
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers

    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    sh = _ShellAttrappe()
    seite = olp.OnlineLobbyPage()
    seite.enter(sh)
    seite._is_host = ist_host
    netz.slot = 0 if ist_host else 1
    seite._players = list(SPIELER)
    seite._selected_mode = "Grand Prix"
    seite._selected_track_path = os.path.join(_ROOT, "data", "tracks", "oval.json")
    seite._view = olp._LOBBY
    seite._enter_gp_overview()
    assert seite._view == olp._GP_OVERVIEW
    netz.gesendet.clear()
    return seite, sh, olp


def _bilder(seite, n: int = 3) -> None:
    for _ in range(n):
        seite.update(0.016)


# ── Der eigentliche Fund ────────────────────────────────────────────────────

def test_host_startet_aus_der_uebersicht_ins_rennen(serie, netz):
    """START erreicht den Host nur, wenn die Übersicht die Sitzung pumpt."""
    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)

    netz.zustellen({"type": "START", "track_name": "oval.json"})
    _bilder(seite)

    assert [w[0] for w in sh.wechsel] == ["race"], (
        "Host hängt in der Übersicht: START wurde nie abgeholt "
        f"(msg={seite._msg!r})")


def test_gast_startet_aus_der_uebersicht_ins_rennen(serie, netz):
    """Derselbe Weg für den Gast — er steht in derselben Ebene."""
    seite, sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    netz.zustellen({"type": "START", "track_name": "oval.json"})
    _bilder(seite)

    assert [w[0] for w in sh.wechsel] == ["race"]


def test_uebersicht_haelt_die_verbindung_am_leben(serie, netz, monkeypatch):
    """Ohne Keepalive bleiben die Pings aus und der Server wirft uns nach
    kurzer Zeit aus der Lobby — auch ohne Rennstart.

    **Die Stelle hat sich am 07.08.2026 verschoben.** Vorher tickte die Seite
    die Sitzung selbst; damit lief der Keepalive nur, solange gerade diese
    Seite die aktive war. In der Fahrzeugauswahl lief er nicht, und ein Gast
    flog nach gut einer Minute aus der Lobby. Getickt wird jetzt in der
    Zustandsmaschine, also in jedem Zustand — die Zusage dieses Tests gilt
    unveraendert, sie wird nur eine Ebene hoeher eingeloest.

    Zwei Dinge werden deshalb geprueft: dass die Uebersicht die Sitzung **nicht
    mehr selbst** tickt (sonst waere es doppelt), und dass sie ueber den
    normalen Weg trotzdem getickt wird.
    """
    from src.core.state_machine import StateMachine

    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    _bilder(seite, 5)
    assert netz.update_aufrufe == 0, \
        "die Seite tickt die Sitzung doppelt — der Keepalive sitzt jetzt oben"

    class _Huelle:
        def enter(self, **k): pass
        def exit(self): pass
        def handle_events(self, e): pass
        def update(self, dt): seite.update(dt)
        def render(self, s): pass

    sm = StateMachine()
    sm.register("menu", _Huelle())
    sm.transition("menu")
    for _ in range(5):
        sm.update(0.016)

    assert netz.update_aufrufe == 5


def test_uebersicht_nimmt_lobby_nachrichten_entgegen(serie, netz):
    """Serienstand und Mitspielerliste müssen in der Übersicht weiterlaufen."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    netz.zustellen({
        "type": "LOBBY_STATE",
        "players": SPIELER + [{"slot": 2, "name": "dritter", "lobby_ready": False}],
        "mode": "Grand Prix",
        "settings": {"gp_active": True, "gp_phase": "overview",
                     "gp_race": 2, "gp_total": 3, "gp_standings": []},
    })
    _bilder(seite)

    assert len(seite._players) == 3
    assert seite._gp_view.get("gp_race") == 2


# ── Tab-Leiste in der Übersicht ─────────────────────────────────────────────

def test_uebersicht_blendet_die_tab_leiste_aus(serie, netz):
    """Die Übersicht ist eine eigene Ebene, keine Menüseite: die Leiste des
    Hauptmenüs hat dort nichts verloren."""
    seite, _sh, olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    assert seite.hides_tab_bar() is True

    seite._view = olp._LOBBY
    assert seite.hides_tab_bar() is False, "in der Lobby gehört die Leiste hin"


def test_shell_fragt_die_seite_nach_der_leiste(serie, netz):
    from src.states.menu_shell_state import MenuShellState

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = []
    assert shell._tabs_hidden() is False

    seite, _sh, olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    shell.page_stack = [seite]
    assert shell._tabs_hidden() is True

    seite._view = olp._LOBBY
    assert shell._tabs_hidden() is False


def test_seiten_ohne_eigene_meinung_behalten_die_leiste():
    """Standard bleibt Standard — sonst müsste jede Seite nachgezogen werden."""
    from src.states.menu.page import Page
    from src.states.menu_shell_state import MenuShellState

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = [Page()]
    assert shell._tabs_hidden() is False


def test_leiste_wird_auch_wirklich_nicht_gezeichnet():
    """Ohne diese Abfrage bliebe die Leiste sichtbar und nur die Klicks weg —
    die schlechteste der drei möglichen Kombinationen."""
    import inspect
    from src.states.menu_shell_state import MenuShellState
    quelle = inspect.getsource(MenuShellState._draw_tab_bar)
    assert "_tabs_hidden" in quelle


def test_ausgeblendete_leiste_schluckt_keine_klicks(serie, netz):
    """Eine unsichtbare Leiste, die weiter Tabs anklickbar macht, würde die
    Streckenkacheln am oberen Rand unbenutzbar machen — und schlimmer: ein
    Tabwechsel leert den page_stack und beendet damit die Serie."""
    from src.states.menu_shell_state import MenuShellState

    shell = MenuShellState.__new__(MenuShellState)
    shell.tab = 2
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    shell.page_stack = [seite]

    ziel = shell._tab_rects()[0]          # ein anderer Tab als der aktive
    seite.handle_event = lambda e: False  # Seite gibt den Klick frei
    shell._handle_page_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=ziel.center))

    assert shell.page_stack == [seite], "Tabwechsel trotz ausgeblendeter Leiste"
    assert shell.tab == 2


def test_host_meldet_start_an_den_server(serie, netz):
    """Der Startknopf der Übersicht muss dieselbe Kette auslösen wie in der
    Lobby: START_REQUEST + Streckenübertragung."""
    import time
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)

    seite._request_start()
    frist = time.time() + 5.0
    while not netz.hochgeladen and time.time() < frist:
        time.sleep(0.01)

    assert netz.hochgeladen, "Strecke wurde nie hochgeladen"
    assert seite._msg == "Übertrage Strecke …"
