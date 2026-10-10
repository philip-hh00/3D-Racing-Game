"""Der Reiter RENNEN und seine Auswahlseiten (1.1.0).

Fuenf Tabs: RENNEN, STRECKENEDITOR, WERKSTATT, PROFIL, EINSTELLUNGEN. RENNEN
fragt erst "Lokal oder Online", Lokal dann "1 Spieler oder 2 Spieler
(Splitscreen)"; danach gelten die bisherigen Wege. ESC geht genau eine Ebene hoch.

Geprueft wird der ganze Baum mit echten Tasten- und Mausereignissen auf einer
echten Menue-Schale (nur der Zustandsautomat ist eine Attrappe), dazu die
Rueckwege nach Rennen, Ergebnis und Grand Prix.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import race_setup  # noqa: E402
from src.core.i18n import set_language, tr  # noqa: E402
from src.states import menu_shell_state as ms  # noqa: E402
from src.states.menu.lobby_page import LobbyPage  # noqa: E402
from src.states.menu.mp_lobby_page import MPLobbyPage  # noqa: E402
from src.states.menu.mp_name_page import MPNamePage  # noqa: E402
from src.states.menu.online_lobby_page import OnlineLobbyPage  # noqa: E402
from src.states.menu.rennen_wahl_page import LokalWahlPage, RennenWahlPage  # noqa: E402
from src.states.menu_shell_state import MenuShellState  # noqa: E402


class _Automat:
    """Merkt sich Uebergaenge, statt sie auszufuehren."""

    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []

    def transition(self, name, **kwargs):
        self.wechsel.append((name, kwargs))


@pytest.fixture(autouse=True)
def _frisch(monkeypatch):
    monkeypatch.setattr(race_setup, "_current", race_setup.RaceSetup())
    yield
    set_language("de")


@pytest.fixture
def shell():
    sh = MenuShellState(_Automat())
    sh.enter()
    return sh


def _taste(key, pad=False):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0, synthetic=pad)


def _drueck(sh, key, pad=False):
    sh.handle_events([_taste(key, pad)])


def _namen(sh):
    return [type(p).__name__ for p in sh.page_stack]


# ---------------------------------------------------------------------------
# Tabs und Konstanten
# ---------------------------------------------------------------------------
def test_die_fuenf_tabs_in_ihrer_reihenfolge():
    assert [t[0] for t in ms._TABS] == [
        "RENNEN", "STRECKENEDITOR", "WERKSTATT", "PROFIL", "EINSTELLUNGEN"]
    assert [t[2] for t in ms._TABS] == ["rennen", "editor", "werkstatt", "profil", "settings"]


def test_tab_konstanten_zeigen_auf_ihren_tab():
    assert ms._TABS[ms.TAB_RENNEN][2] == "rennen"
    assert ms._TABS[ms.TAB_EDITOR][2] == "editor"
    assert ms._TABS[ms.TAB_WERKSTATT][2] == "werkstatt"
    assert ms._TABS[ms.TAB_PROFIL][2] == "profil"
    assert ms._TABS[ms.TAB_EINSTELLUNGEN][2] == "settings"


def test_der_rennen_tab_nimmt_das_einzelspieler_video():
    assert ms._TABS[ms.TAB_RENNEN][1] == "Einzelspieler"


def test_die_leiste_passt_ins_bild():
    rects = ms.tab_rects()
    assert len(rects) == 5
    assert rects[0].x >= 0 and rects[-1].right <= ms.SCREEN_WIDTH


def test_keine_alten_tabnamen_mehr_in_der_leiste():
    namen = [t[0] for t in ms._TABS]
    assert not {"EINZELSPIELER", "MEHRSPIELER LOKAL", "MEHRSPIELER ONLINE"} & set(namen)


def test_editor_blaettert_auf_rennen_und_werkstatt():
    """PageUp/PageDown im Editor springen auf den Nachbartab, nicht auf eine
    feste Zahl aus der Zeit der sieben Tabs."""
    from src.states.editor_state import EditorState
    ed = EditorState.__new__(EditorState)
    ed.state_machine = _Automat()
    ed._projects = []
    ed._browse_idx = 0
    ed._handle_browse_event(_taste(pygame.K_PAGEUP))
    ed._handle_browse_event(_taste(pygame.K_PAGEDOWN))
    assert ed.state_machine.wechsel == [("menu", {"tab_idx": ms.TAB_RENNEN}),
                                        ("menu", {"tab_idx": ms.TAB_WERKSTATT})]


def test_editor_tabklick_auf_rennen_oeffnet_die_auswahl():
    sh = MenuShellState(_Automat())
    sh.enter(tab_idx=ms.TAB_RENNEN)
    assert _namen(sh) == ["RennenWahlPage"]


# ---------------------------------------------------------------------------
# Der Baum: hinein und wieder hinaus
# ---------------------------------------------------------------------------
def test_enter_auf_rennen_zeigt_lokal_oder_online(shell):
    assert shell.tab == ms.TAB_RENNEN
    _drueck(shell, pygame.K_RETURN)
    assert _namen(shell) == ["RennenWahlPage"]
    seite = shell.page_stack[0]
    assert [k.action for k in seite.group.widgets] == ["lokal", "online"]


def test_lokal_fuehrt_zur_spielerzahl_und_esc_zurueck(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)               # Lokal
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage"]
    assert [k.action for k in shell.page_stack[-1].group.widgets] == ["single", "mp"]
    _drueck(shell, pygame.K_ESCAPE)
    assert _namen(shell) == ["RennenWahlPage"]
    _drueck(shell, pygame.K_ESCAPE)
    assert shell.page_stack == [], "dann die Menueleiste"
    assert shell.tab == ms.TAB_RENNEN


def test_ein_spieler_ist_die_einzelspieler_lobby(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)               # Lokal
    _drueck(shell, pygame.K_RETURN)               # 1 Spieler
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage", "LobbyPage"]
    assert race_setup.current().is_multiplayer is False
    _drueck(shell, pygame.K_ESCAPE)
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage"]


def test_zwei_spieler_gehen_ueber_name_in_die_mp_lobby(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)               # Lokal
    _drueck(shell, pygame.K_RIGHT)                # -> 2 Spieler
    _drueck(shell, pygame.K_RETURN)
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage", "MPNamePage"]
    assert race_setup.current().is_multiplayer is True
    shell.page_stack[-1]._advance()
    assert _namen(shell)[-2:] == ["MPNamePage", "MPLobbyPage"]
    _drueck(shell, pygame.K_ESCAPE)
    _drueck(shell, pygame.K_ESCAPE)
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage"]


def test_online_ist_die_online_seite_und_esc_geht_eine_ebene_hoch(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RIGHT)                # -> Online
    _drueck(shell, pygame.K_RETURN)
    assert _namen(shell) == ["RennenWahlPage", "OnlineLobbyPage"]
    shell.zurueck_gehen()                         # die Online-Seite geht selbst hoch
    assert _namen(shell) == ["RennenWahlPage"]
    _drueck(shell, pygame.K_ESCAPE)
    assert shell.page_stack == []


def test_zurueck_knopf_und_esc_gehen_denselben_weg(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)               # Lokal
    seite = shell.page_stack[-1]
    seite.draw(pygame.Surface((1920, 1080)), shell._content_area())   # legt den Knopf
    klick = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                               pos=seite.zurueck_knopf().rect.center)
    shell.handle_events([klick])
    assert _namen(shell) == ["RennenWahlPage"]


def test_maus_klick_auf_kachel(shell):
    _drueck(shell, pygame.K_RETURN)
    seite = shell.page_stack[-1]
    online = seite.group.widgets[1]
    shell.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                            pos=online.rect.center)])
    assert _namen(shell) == ["RennenWahlPage", "OnlineLobbyPage"]


def test_maus_hover_setzt_den_fokus(shell):
    _drueck(shell, pygame.K_RETURN)
    seite = shell.page_stack[-1]
    seite.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=seite.group.widgets[1].rect.center,
                                          rel=(0, 0), buttons=(0, 0, 0)))
    assert seite.group.index == 1


def test_controller_navigiert_wie_die_tastatur(shell):
    """Der Gamepad-Manager liefert synthetische Tasten: D-Pad rechts, A, B."""
    _drueck(shell, pygame.K_RETURN, pad=True)     # A auf dem Reiter
    _drueck(shell, pygame.K_RIGHT, pad=True)      # D-Pad -> Online
    seite = shell.page_stack[-1]
    assert seite.group.index == 1
    _drueck(shell, pygame.K_LEFT, pad=True)
    assert seite.group.index == 0
    _drueck(shell, pygame.K_RETURN, pad=True)     # A: Lokal
    assert _namen(shell) == ["RennenWahlPage", "LokalWahlPage"]
    _drueck(shell, pygame.K_ESCAPE, pad=True)     # B
    assert _namen(shell) == ["RennenWahlPage"]
    _drueck(shell, pygame.K_ESCAPE, pad=True)
    assert shell.page_stack == []


def test_pfeil_hoch_runter_verliert_den_fokus_nicht(shell):
    _drueck(shell, pygame.K_RETURN)
    seite = shell.page_stack[-1]
    for taste in (pygame.K_DOWN, pygame.K_UP, pygame.K_DOWN, pygame.K_DOWN):
        _drueck(shell, taste)
        assert seite.group.focused is not None


def test_der_fokus_steht_beim_zurueckkommen_auf_dem_gewaehlten_weg(shell):
    stapel = shell.rennen_ebenen("mp_local")
    assert stapel[0].group.focused.action == "lokal"
    assert stapel[1].group.focused.action == "mp"
    assert [type(p).__name__ for p in shell.rennen_ebenen("online")] == ["RennenWahlPage"]
    assert shell.rennen_ebenen("online")[0].group.focused.action == "online"


def test_pagedown_auf_den_auswahlseiten_wechselt_den_tab(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_PAGEDOWN)
    assert shell.page_stack == []
    assert shell.tab == ms.TAB_EDITOR


def test_tab_klick_aus_den_auswahlseiten(shell):
    _drueck(shell, pygame.K_RETURN)
    rect = shell._tab_rects()[ms.TAB_WERKSTATT]
    shell.handle_events([pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                            pos=rect.center)])
    assert shell.page_stack == []
    assert shell.tab == ms.TAB_WERKSTATT


# ---------------------------------------------------------------------------
# Von der Auswahl zum Rennen
# ---------------------------------------------------------------------------
def test_einzelrennen_startet_ueber_die_fahrzeugwahl(shell):
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)               # 1 Spieler -> Lobby
    shell.page_stack[-1]._commit_and_advance()
    assert shell.state_machine.wechsel[-1][0] == "car_select"


def test_splitscreen_startet_ueber_die_fahrzeugwahl(shell, monkeypatch):
    from src.core import gamepad
    monkeypatch.setattr(race_setup, "available_input_specs", lambda: ["keyboard", "pad0"])
    monkeypatch.setattr(gamepad, "device_count", lambda: 1)
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RETURN)
    _drueck(shell, pygame.K_RIGHT)
    _drueck(shell, pygame.K_RETURN)
    shell.page_stack[-1]._advance()
    lobby = shell.page_stack[-1]
    assert isinstance(lobby, MPLobbyPage)
    lobby._advance()
    assert shell.state_machine.wechsel[-1] == ("car_select", {"picker": "p1"})
    assert race_setup.current().is_multiplayer is True


# ---------------------------------------------------------------------------
# Rueckwege: aus der Fahrzeugwahl, aus dem Ergebnis, aus dem Grand Prix
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("reopen,ziel", [
    ("lobby", ["RennenWahlPage", "LokalWahlPage", "LobbyPage"]),
    ("mp_lobby", ["RennenWahlPage", "LokalWahlPage", "MPNamePage", "MPLobbyPage"]),
])
def test_rueckkehr_aus_der_auswahl_baut_die_ebenen_wieder_auf(reopen, ziel):
    sh = MenuShellState(_Automat())
    sh.enter(reopen=reopen)
    assert sh.tab == ms.TAB_RENNEN
    assert _namen(sh) == ziel
    _drueck(sh, pygame.K_ESCAPE)
    assert _namen(sh) == ziel[:-1], "genau eine Ebene"


def test_rueckkehr_in_die_online_lobby_liegt_unter_der_auswahl():
    from src.net import session
    session.clear()
    sh = MenuShellState(_Automat())
    sh.enter(reopen="online_lobby")
    assert sh.tab == ms.TAB_RENNEN
    assert _namen(sh) == ["RennenWahlPage", "OnlineLobbyPage"]
    sh = MenuShellState(_Automat())
    sh.enter(reopen="online_lobby_resume")
    assert _namen(sh) == ["RennenWahlPage", "OnlineLobbyPage"]


def test_ergebnis_zurueck_zur_lobby_einzelspieler():
    from src.states.menu.results_page import ResultsPage
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={})
    assert sh.tab == ms.TAB_RENNEN
    assert _namen(sh) == ["ResultsPage"]
    seite = sh.page_stack[0]
    assert isinstance(seite, ResultsPage)
    seite.group.handle_event = lambda e: "lobby"
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
    assert _namen(sh) == ["RennenWahlPage", "LokalWahlPage", "LobbyPage"]


def test_ergebnis_zurueck_zur_lobby_splitscreen():
    race_setup.current().is_multiplayer = True
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={})
    seite = sh.page_stack[0]
    seite.group.handle_event = lambda e: "lobby"
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
    assert _namen(sh) == ["RennenWahlPage", "LokalWahlPage", "MPNamePage", "MPLobbyPage"]


def test_ergebnis_menue_leert_den_stapel():
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={})
    seite = sh.page_stack[0]
    seite.group.handle_event = lambda e: "menu"
    seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0))
    assert sh.page_stack == [] and sh.tab == ms.TAB_RENNEN


def test_online_ergebnis_zurueck_zur_lobby_liegt_unter_der_auswahl():
    from src.net import session, client
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={"is_online": True})
    assert sh.tab == ms.TAB_RENNEN
    net = client.NetworkClient()
    net._alive = True
    lobby = OnlineLobbyPage()
    lobby.enter(sh)
    lobby._view = "lobby"
    session.set(net)
    session.set_lobby_page(lobby)
    try:
        seite = sh.page_stack[0]
        seite.group.handle_event = lambda e: "lobby"
        seite.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                                              unicode="", mod=0))
        assert _namen(sh) == ["RennenWahlPage", "OnlineLobbyPage"]
        assert sh.page_stack[-1] is lobby
    finally:
        session.clear()


def test_grand_prix_beenden_fuehrt_in_die_lobby_mit_ebenen():
    from src.core import grand_prix
    from src.states.menu.gp_overview_page import GPOverviewPage
    sh = MenuShellState(_Automat())
    sh.enter(reopen="gp_overview")
    assert sh.tab == ms.TAB_RENNEN
    assert _namen(sh) == ["GPOverviewPage"]
    seite = sh.page_stack[0]
    assert isinstance(seite, GPOverviewPage)
    seite._beenden()
    assert _namen(sh) == ["RennenWahlPage", "LokalWahlPage", "LobbyPage"]
    assert not grand_prix.is_active()


def test_online_grand_prix_kehrt_in_die_online_lobby_zurueck():
    """Online-GP laeuft ueber ``online_lobby_resume`` — wie bisher."""
    from src.states.menu.results_page import ResultsPage
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={"is_online": True})
    seite = sh.page_stack[0]
    assert isinstance(seite, ResultsPage)
    seite._go_to_gp_overview()
    assert sh.state_machine.wechsel[-1] == ("menu", {"reopen": "online_lobby_resume"})


def test_werkstatt_kurzweg_nimmt_die_konstante():
    sh = MenuShellState(_Automat())
    sh.enter(reopen="werkstatt", vehicle_config="rookie", rueckweg=("car_select", {}))
    assert sh.tab == ms.TAB_WERKSTATT
    assert ms._TABS[sh.tab][0] == "WERKSTATT"


# ---------------------------------------------------------------------------
# Hintergrundvideo
# ---------------------------------------------------------------------------
def test_video_je_pfad():
    sh = MenuShellState(_Automat())
    sh.enter()
    assert sh._hintergrund_stamm() == "Einzelspieler"
    sh.enter(reopen="online_lobby")
    assert sh._hintergrund_stamm() == "Mehrspieler_Online"
    sh.enter(reopen="mp_lobby")
    assert sh._hintergrund_stamm() == "Mehrspieler_Lokal"
    sh.enter(reopen="lobby")
    assert sh._hintergrund_stamm() == "Einzelspieler"


def test_video_auswahlseiten_bleiben_beim_tabvideo(shell):
    _drueck(shell, pygame.K_RETURN)
    assert shell._hintergrund_stamm() == "Einzelspieler"
    _drueck(shell, pygame.K_RETURN)
    assert shell._hintergrund_stamm() == "Einzelspieler"


def test_video_ergebnis_online_behaelt_das_online_video():
    sh = MenuShellState(_Automat())
    sh.enter(results=[{"name": "P1", "position": 1}], race_config={"is_online": True})
    assert sh._hintergrund_stamm() == "Mehrspieler_Online"


def test_jedes_video_der_pfade_existiert_als_datei_oder_ist_optional():
    for stamm in ("Einzelspieler", "Mehrspieler_Lokal", "Mehrspieler_Online"):
        assert stamm in ms._RENNEN_STAMM.values()


# ---------------------------------------------------------------------------
# Zeichnen und Sprache
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sprache", ["de", "en"])
def test_auswahlseiten_zeichnen_ohne_fehler(shell, sprache):
    set_language(sprache)
    screen = pygame.Surface((1920, 1080))
    shell.render(screen)
    _drueck(shell, pygame.K_RETURN)
    shell.render(screen)
    _drueck(shell, pygame.K_RETURN)
    shell.render(screen)


def test_englische_fassungen():
    set_language("en")
    assert tr("RENNEN") == "RACE"
    assert tr("Lokal") == "Local"
    assert tr("1 Spieler") == "1 Player"
    assert tr("2 Spieler (Splitscreen)") == "2 Players (split screen)"
    assert tr("Online") == "Online"


def test_jede_kachel_hat_eine_englische_fassung():
    set_language("en")
    for seite in (RennenWahlPage(), LokalWahlPage()):
        for aktion, titel, text, _sym in seite._eintraege():
            assert tr(titel) != titel or titel == "Online", titel
            assert tr(text) != text, text
        assert tr(seite.UEBERSCHRIFT) != seite.UEBERSCHRIFT
        assert tr(seite.FRAGE) != seite.FRAGE
