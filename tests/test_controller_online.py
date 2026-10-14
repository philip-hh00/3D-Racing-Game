"""Online mit dem Controller allein: Lobbyliste, Erstellen, Beitreten, Passwort,
Lobby, Zahnrad (Sichtbarkeit und Name).

Siehe ``test_controller_erreichbar`` für die Vorgabe und
``tests/controller_pruefung.py`` für das Werkzeug. Hier die Online-Abläufe, weil
sie als einzige mehrere Ansichten in einer Seite haben (``OnlineLobbyPage._view``)
und dazu Textfelder, Passwörter und Dialoge.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import gamepad  # noqa: E402
from tests import controller_pruefung as cp  # noqa: E402
from tests import spielhilfe  # noqa: E402
from tests.test_lobbyliste_client import HEL, Api, _e, _in_lobby, _liste, seite  # noqa: E402,F401

A, B = gamepad.BTN_A, gamepad.BTN_B
HOCH, RUNTER = gamepad.BTN_DPAD_UP, gamepad.BTN_DPAD_DOWN
LINKS, RECHTS = gamepad.BTN_DPAD_LEFT, gamepad.BTN_DPAD_RIGHT
START, LB, RB = gamepad.BTN_START, gamepad.BTN_LB, gamepad.BTN_RB

_FLAECHE = pygame.Rect(0, 108, 1920, 972)


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.fixture
def pad():
    manager, zurueck = spielhilfe.pad_anmelden()
    yield manager
    zurueck()
    manager._using_pad = False


def _bild(seite) -> bytes:
    schirm = pygame.Surface((1920, 1080))
    schirm.fill((0, 0, 0))
    seite.draw(schirm, _FLAECHE)
    return pygame.image.tobytes(schirm, "RGB")


def _online(seite, anzahl=14):
    """Die Online-Seite mit einer vollen Lobbyliste (mehr Zeilen als Platz)."""
    from src.states.menu.lobby_browser import LobbyBrowser
    api = Api({"helsinki": [_e(f"H{i:05d}", f"Lobby {i}", password=(i % 3 == 0))
                            for i in range(anzahl)]})
    seite._browser = LobbyBrowser(_liste(api))
    seite.update(0.016)
    return seite


def _aktive_gruppe(seite):
    olp = seite.olp
    return {olp._BROWSER: seite._browser.gruppe, olp._HOST_SERVER: seite._host_group,
            olp._JOIN: seite._join_group, olp._PASSWORD: seite._pw_group,
            olp._LOBBY_EDIT: seite._edit_group, olp._LOBBY: seite._lobby_group,
            }[seite._view]


def _ansicht_herstellen(seite, ansicht, monkeypatch):
    olp = seite.olp
    if ansicht == "erstellen":
        seite._oeffne_erstellen()
    elif ansicht == "erstellen_mit_passwort":
        seite._oeffne_erstellen()
        seite._angaben.stepper.index = 1
        seite._host_gruppe_bauen(behalten=True)
    elif ansicht == "passwort":
        seite._pw_ziel = (HEL, "HAAAAA")
        seite._passwort_abfrage(falsch=False)
    elif ansicht == "beitreten":
        seite._view = olp._JOIN
    elif ansicht in ("lobby_host", "lobby_gast"):
        _in_lobby(seite, monkeypatch, host=(ansicht == "lobby_host"))
        seite._players = [
            {"slot": 0, "name": "Host", "lobby_ready": False, "vehicle": "rookie"},
            {"slot": 1, "name": "Gast", "lobby_ready": False, "vehicle": "drifter"}]
        seite._sync_ai_roster()
        seite._rebuild_roster_widgets()
        seite._refresh_focus_group()
    elif ansicht == "lobby_bearbeiten":
        _in_lobby(seite, monkeypatch)
        seite._lobby_edit_oeffnen()


ANSICHTEN = ["liste", "erstellen", "erstellen_mit_passwort", "passwort", "beitreten",
             "lobby_host", "lobby_gast", "lobby_bearbeiten"]


@pytest.mark.parametrize("ansicht", ANSICHTEN)
def test_alles_gezeichnete_ist_im_fokus_und_erreichbar(ansicht, seite, pad, monkeypatch):
    _online(seite)
    _ansicht_herstellen(seite, ansicht, monkeypatch)
    mit = cp.Zeichenmitschrift(monkeypatch)
    _bild(seite)
    gruppe = _aktive_gruppe(seite)
    assert cp.nicht_im_fokus(mit, [gruppe]) == [], \
        f"{ansicht}: gezeichnet und bedienbar, aber nicht im Fokus"
    assert cp.erreichbarkeit(pad, seite, gruppe) == [], \
        f"{ansicht}: mit dem Steuerkreuz nicht erreichbar"


@pytest.mark.parametrize("ansicht", ANSICHTEN)
def test_der_fokus_ist_sichtbar(ansicht, seite, pad, monkeypatch):
    """Wandert der Fokus, muss sich das Bild ändern — sonst sieht man nicht,
    wo man steht."""
    _online(seite)
    _ansicht_herstellen(seite, ansicht, monkeypatch)
    gruppe = _aktive_gruppe(seite)
    bedienbar = [i for i, w in enumerate(gruppe.widgets) if getattr(w, "focusable", False)]
    assert len(bedienbar) >= 2
    bilder = set()
    for i in bedienbar:
        gruppe.index = i
        bilder.add(_bild(seite))
    assert len(bilder) == len(bedienbar), \
        f"{ansicht}: bei {len(bedienbar)} Fokusstellen nur {len(bilder)} verschiedene Bilder"


@pytest.mark.parametrize("ansicht", ["erstellen", "erstellen_mit_passwort",
                                     "passwort", "beitreten"])
def test_b_fuehrt_aus_jeder_ansicht_zur_liste_zurueck(ansicht, seite, pad, monkeypatch):
    _online(seite)
    _ansicht_herstellen(seite, ansicht, monkeypatch)
    assert seite._view != seite.olp._BROWSER
    cp.mehrmals(pad, seite, B)
    assert seite._view == seite.olp._BROWSER


def test_b_in_der_liste_verlaesst_die_seite(seite, pad, monkeypatch):
    """Die Liste gibt B an die Schale weiter (eine Ebene hoch) und frisst es nicht."""
    _online(seite)
    erg = seite.handle_event(pygame.event.Event(
        pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0, synthetic=True))
    assert not erg


@pytest.mark.parametrize("ansicht", ["lobby_host", "lobby_gast"])
def test_lobby_b_fragt_und_b_bleibt(ansicht, seite, pad, monkeypatch):
    _online(seite)
    _ansicht_herstellen(seite, ansicht, monkeypatch)
    cp.mehrmals(pad, seite, B)
    assert seite._dialog is not None, "B in der Lobby muss nachfragen"
    cp.mehrmals(pad, seite, B)                      # B = die letzte Antwort
    assert seite._dialog is None and seite._view == seite.olp._LOBBY


def test_lobby_bearbeiten_b_geht_zur_lobby_zurueck(seite, pad, monkeypatch):
    _online(seite)
    _ansicht_herstellen(seite, "lobby_bearbeiten", monkeypatch)
    cp.mehrmals(pad, seite, B)
    assert seite._view == seite.olp._LOBBY


def test_liste_jede_zeile_ist_erreichbar_und_rollt_mit(seite, pad, monkeypatch):
    """14 Lobbys, 8 Zeilen Platz: der Fokus muss über den Rand hinaus rollen."""
    _online(seite, anzahl=14)
    b = seite._browser
    gesehen = []
    for _ in range(40):
        cp.mehrmals(pad, seite, RUNTER)
        fokus = b.gruppe.focused
        if getattr(fokus, "eintrag", None) is not None:
            gesehen.append(fokus.eintrag.code)
    assert len(set(gesehen)) == 14, f"nur {len(set(gesehen))} von 14 Lobbys erreicht"
    for _ in range(40):
        cp.mehrmals(pad, seite, HOCH)
    assert b.versatz == 0


def test_liste_rollt_auch_mit_den_schultertasten(seite, pad, monkeypatch):
    _online(seite, anzahl=30)
    cp.mehrmals(pad, seite, RB)
    assert seite._browser.versatz > 0
    cp.mehrmals(pad, seite, LB)
    assert seite._browser.versatz == 0


def test_liste_zeile_ohne_passwort_verbindet_mit_a(seite, pad, monkeypatch):
    _online(seite, anzahl=3)
    b = seite._browser
    zeile = next(z for z in b.zeilen if z.eintrag and not z.eintrag.password)
    b.gruppe.index = b.gruppe.widgets.index(zeile)
    cp.mehrmals(pad, seite, A)
    assert seite.aufrufe and seite.aufrufe[0][1].get("lobby_code") == zeile.eintrag.code


def test_liste_zeile_mit_passwort_fuehrt_zur_passwortabfrage(seite, pad, monkeypatch):
    _online(seite, anzahl=3)
    b = seite._browser
    zeile = next(z for z in b.zeilen if z.eintrag and z.eintrag.password)
    b.gruppe.index = b.gruppe.widgets.index(zeile)
    cp.mehrmals(pad, seite, A)
    assert seite._view == seite.olp._PASSWORD
    assert not seite.aufrufe


def test_die_drei_knoepfe_der_liste_fuehren_ans_ziel(seite, pad, monkeypatch):
    olp = seite.olp
    for knopf, ansicht in (("b_erstellen", olp._HOST_SERVER), ("b_code", olp._JOIN)):
        _online(seite)
        seite._view = olp._BROWSER
        b = seite._browser
        b.gruppe.index = b.gruppe.widgets.index(getattr(b, knopf))
        cp.mehrmals(pad, seite, A)
        assert seite._view == ansicht, knopf
    # „Online-Strecken" wechselt den Zustand
    _online(seite)
    seite._view = olp._BROWSER
    gewechselt = []
    seite.shell.state_machine = type("S", (), {
        "transition": lambda self, *a, **k: gewechselt.append(a)})()
    b = seite._browser
    b.gruppe.index = b.gruppe.widgets.index(b.b_strecken)
    cp.mehrmals(pad, seite, A)
    assert gewechselt and gewechselt[0][0] == "online_strecken"


def _tippt(pad, seite, zeichen: str) -> None:
    """Ein Zeichen über die Bildschirmtastatur eintippen (Cursor setzen, A)."""
    osk = seite.osk
    for r, zeile in enumerate(osk.layout):
        if zeichen in zeile:
            osk.row, osk.col = r, zeile.index(zeichen)
            cp.mehrmals(pad, seite, A)
            return
    raise AssertionError(f"{zeichen!r} steht nicht auf der Bildschirmtastatur")


def test_passwort_mit_der_bildschirmtastatur_eingeben(seite, pad, monkeypatch):
    _online(seite, anzahl=3)
    seite._pw_ziel = (HEL, "HAAAAA")
    seite._passwort_abfrage(falsch=False)
    assert seite._pw_group.focused is seite._pw_input
    cp.mehrmals(pad, seite, A)
    assert seite.osk is not None, "A auf dem Passwortfeld öffnet keine Tastatur"
    for z in "A1B2":
        _tippt(pad, seite, z)
    cp.mehrmals(pad, seite, START)                  # Fertig
    assert seite.osk is None and len(seite._pw_input.text) == 4
    assert seite._pw_group.focused is seite._btn_pw_join
    cp.mehrmals(pad, seite, A)
    assert seite.aufrufe and seite.aufrufe[0][1].get("password") == seite._pw_input.text


def test_passwort_sonderzeichen_gibt_es_auf_der_tastatur(seite, pad, monkeypatch):
    _online(seite, anzahl=3)
    seite._pw_ziel = (HEL, "HAAAAA")
    seite._passwort_abfrage(falsch=False)
    cp.mehrmals(pad, seite, A)
    for z in "-!@#":
        _tippt(pad, seite, z)
    assert seite._pw_input.text == "-!@#"


def test_beitreten_per_code_mit_der_bildschirmtastatur(seite, pad, monkeypatch):
    _online(seite, anzahl=3)
    seite._view = seite.olp._JOIN
    cp.mehrmals(pad, seite, A)
    assert seite.osk is not None
    for z in "HAAAAA":
        _tippt(pad, seite, z)
    cp.mehrmals(pad, seite, START)
    assert seite._code_input.text == "HAAAAA"
    assert seite._join_group.focused is seite._btn_join
    from src.net import server_probe
    monkeypatch.setattr(server_probe, "get",
                        lambda sid: type("S", (), {"selectable": True})())
    cp.mehrmals(pad, seite, A)
    assert seite.aufrufe and seite.aufrufe[0][1].get("lobby_code") == "HAAAAA"


def test_lobbyname_apostroph_gibt_es_auf_der_tastatur(seite, pad, monkeypatch):
    """Der Vorgabename „X's Lobby" hat einen Apostroph; ohne ihn auf der
    Tastatur ließe sich der Name am Controller nicht ändern."""
    _online(seite, anzahl=3)
    _ansicht_herstellen(seite, "erstellen", monkeypatch)
    seite._angaben.name_feld.text = ""
    g = seite._host_group
    g.index = g.widgets.index(seite._angaben.name_feld)
    cp.mehrmals(pad, seite, A)
    assert seite.osk is not None
    for z in "MA'X":
        _tippt(pad, seite, z)
    assert seite._angaben.name_feld.text == "MA'X"


def test_spielername_tastatur_hat_keine_sonderzeichen():
    """Die Tastatur für Felder mit Zeichenliste bietet nur diese Zeichen an."""
    from src.core import profile
    from src.ui.widgets import OnScreenKeyboard, TextInput
    feld = TextInput(pygame.Rect(0, 0, 10, 10), "", allowed=profile.NAME_ALLOWED)
    osk = OnScreenKeyboard(feld)
    assert "'" not in [z for zeile in osk.layout for z in zeile]


def test_zahnrad_oeffnet_die_lobbyangaben_und_b_schliesst(seite, pad, monkeypatch):
    olp = seite.olp
    _online(seite)
    _ansicht_herstellen(seite, "lobby_host", monkeypatch)
    g = seite._lobby_group
    g.index = g.widgets.index(seite._btn_lobbyinfo)
    cp.mehrmals(pad, seite, A)
    assert seite._view == olp._LOBBY_EDIT
    a = seite._edit_angaben
    assert seite._edit_group.focused is a.stepper
    vorher = a.stepper.index
    cp.mehrmals(pad, seite, A, RECHTS, A)           # Stepper öffnen, ändern, schließen
    assert a.stepper.index != vorher
    cp.mehrmals(pad, seite, B)
    assert seite._view == olp._LOBBY


def test_zahnrad_uebernehmen_sendet_an_den_server(seite, pad, monkeypatch):
    olp = seite.olp
    _online(seite)
    net = _in_lobby(seite, monkeypatch)
    seite._lobby_edit_oeffnen()
    g = seite._edit_group
    g.index = g.widgets.index(seite._btn_edit_ok)
    cp.mehrmals(pad, seite, A)
    assert seite._view == olp._LOBBY
    gesendet = getattr(net, "gesendet", None) or getattr(net, "sent", None) or []
    assert any(m.get("type") == "SET_LOBBY_INFO" for m in gesendet), gesendet


def test_nur_der_host_hat_das_zahnrad(seite, pad, monkeypatch):
    _online(seite)
    _ansicht_herstellen(seite, "lobby_gast", monkeypatch)
    assert seite._btn_lobbyinfo not in seite._lobby_group.widgets
