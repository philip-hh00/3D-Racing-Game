"""Alles ist mit dem Controller allein erreichbar und bedienbar.

Die Vorgabe des Besitzers (08.10.2026): **jeder** Knopf, Reiter, Stepper, jede
Listenzeile, jedes Textfeld, jeder Dialog und jedes Popup muss ohne Maus und
ohne Tastatur zu erreichen und zu bedienen sein, auf jedem Bildschirm, auch in
den Online-Abläufen. Dazu: der Fokus ist sichtbar, B geht überall zurück, es
gibt keine Sackgassen, und rollende Listen folgen dem Fokus.

Wie geprüft wird, steht in ``tests/controller_pruefung.py``; kurz: es wird
gezeichnet und mitgeschrieben, was bedienbar aussieht, und dann mit dem Pad
(über den Weg des Spiels: Knopf -> ``GamepadManager`` -> synthetische Taste)
abgelaufen, was davon wirklich erreichbar ist. Dazu kommen Abläufe, die nur
einen Sinn ergeben, wenn man sie ganz geht: ein Textfeld füllen, einen Dialog
beantworten, ein Passwort abfragen, eine Lobby verlassen.

Zur Erinnerung, was **absichtlich** nicht mit dem Controller geht:

* Tastenbelegung ändern (Einstellungen > Steuerung): das Fenster sagt es selbst
  („nur mit der Tastatur änderbar"); die Belegung des Pads ist fest.
* Ausgegraute Lobbys in der Lobbyliste (voll / im Rennen): nicht wählbar, auch
  nicht mit der Maus.
* Die Entwicklerwerkzeuge (Fahrzeug-, Klang-, Lacklabor) hinter „Dev-Mode".
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
from tests.test_controller_durchlauf import _gruppen, _schale_mit  # noqa: E402
from tests.test_layout_regeln import _BILD, _INHALT, _seiten  # noqa: E402

A, B = gamepad.BTN_A, gamepad.BTN_B
HOCH, RUNTER = gamepad.BTN_DPAD_UP, gamepad.BTN_DPAD_DOWN
LINKS, RECHTS = gamepad.BTN_DPAD_LEFT, gamepad.BTN_DPAD_RIGHT
X, Y, START = gamepad.BTN_X, gamepad.BTN_Y, gamepad.BTN_START
LB, RB = gamepad.BTN_LB, gamepad.BTN_RB


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.fixture
def pad():
    manager, zurueck = spielhilfe.pad_anmelden()
    yield manager
    zurueck()
    manager._using_pad = False


@pytest.fixture(autouse=True)
def _keine_programme_starten(monkeypatch):
    """Links unter „Info" und der Absturzbericht öffnen echte Programme."""
    import webbrowser
    from src.core import absturz, paths
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setattr(absturz, "oeffnen", lambda *a, **k: None)
    monkeypatch.setattr(paths, "datei_oeffnen", lambda *a, **k: None)


def _bild(schale_oder_seite, flaeche=None) -> bytes:
    schirm = pygame.Surface(_BILD)
    schirm.fill((0, 0, 0))
    if hasattr(schale_oder_seite, "render"):
        schale_oder_seite.render(schirm)
    else:
        schale_oder_seite.draw(schirm, flaeche or _INHALT)
    return pygame.image.tobytes(schirm, "RGB")


# ---------------------------------------------------------------------------
# 1. Die Menueseiten: gezeichnet = erreichbar
# ---------------------------------------------------------------------------

_SEITEN_OHNE_BEDIENUNG = ("Demnaechst", "Profil")      # reine Anzeige / rollt nur


@pytest.mark.parametrize("name", [n for n in sorted(_seiten())
                                  if n not in _SEITEN_OHNE_BEDIENUNG
                                  and n != "Einstellungen"])
def test_seite_jedes_bedienelement_ist_im_fokus_und_erreichbar(name, pad, monkeypatch):
    seite = _seiten()[name]()
    schale = _schale_mit(seite)
    mit = cp.Zeichenmitschrift(monkeypatch)
    _bild(schale)

    gruppen = _gruppen(seite)
    if name == "Online":
        # Die Online-Seite hat je Ansicht eine Gruppe; hier steht die Liste.
        gruppen = [seite._browser.gruppe]
    assert cp.nicht_im_fokus(mit, gruppen) == [], \
        f"{name}: gezeichnet und bedienbar, aber nicht mit dem Controller erreichbar"
    for g in gruppen:
        assert cp.erreichbarkeit(pad, schale, g) == [], \
            f"{name}: per Steuerkreuz nicht erreichbar"


_EINSTELLUNGEN = ["Allgemein", "Steuerung", "Video", "Audio", "Fahrhilfen", "Info"]


@pytest.mark.parametrize("reiter", _EINSTELLUNGEN)
def test_einstellungen_jeder_reiter_ist_mit_dem_controller_komplett(reiter, pad, monkeypatch):
    from src.states.menu.settings_page import SettingsPage
    seite = SettingsPage()
    schale = _schale_mit(seite)
    seite.cat = seite.categories.index(reiter)
    seite._build_content()
    seite._focus_content = True
    mit = cp.Zeichenmitschrift(monkeypatch)
    _bild(schale)
    gruppen = _gruppen(seite)
    assert cp.nicht_im_fokus(mit, gruppen) == []
    for g in gruppen:
        assert cp.erreichbarkeit(
            pad, schale, g,
            vorbereiten=lambda: setattr(seite, "_focus_content", True)) == []


def test_einstellungen_allgemein_sprache_und_beenden_nach_dem_namensfeld(pad):
    """Fund: das Namensfeld schluckte jede Taste, Sprache und „Spiel beenden"
    waren nur mit der Maus zu erreichen."""
    from src.states.menu.settings_page import SettingsPage
    seite = SettingsPage()
    schale = _schale_mit(seite)
    cp.mehrmals(pad, schale, A)                    # Spalte -> Inhalt
    gruppe = seite._content_group
    assert gruppe.focused is seite._name_input
    cp.mehrmals(pad, schale, RUNTER)
    sprache = gruppe.focused
    assert getattr(sprache, "action", "") == "change_language"
    cp.mehrmals(pad, schale, A, RECHTS, A)         # öffnen, ändern, schließen
    assert "language" in seite._pending, "Sprachwechsel ist nicht angekommen"
    cp.mehrmals(pad, schale, RUNTER)
    assert getattr(gruppe.focused, "action", "") == "quit_game"
    cp.mehrmals(pad, schale, A)
    assert schale._quit_dialog is not None, "Beenden fragt nicht nach"


def test_einstellungen_name_per_bildschirmtastatur(pad):
    from src.states.menu.settings_page import SettingsPage
    seite = SettingsPage()
    schale = _schale_mit(seite)
    cp.mehrmals(pad, schale, A, A)                 # Inhalt, dann Tastatur
    assert seite.osk is not None, "A auf dem Namensfeld öffnet keine Tastatur"
    seite._name_input.text = ""
    cp.mehrmals(pad, schale, A)                    # Taste unter dem Cursor
    assert len(seite._name_input.text) == 1
    cp.mehrmals(pad, schale, START)                # Fertig
    assert seite.osk is None
    assert seite._pending.get("username") == seite._name_input.text


def test_einstellungen_info_alle_links_sind_waehlbar_und_oeffnen(pad, monkeypatch):
    """Absturzbericht und Lizenzen waren nur mit der Maus zu öffnen."""
    from src.core import absturz, paths
    import webbrowser
    gesehen = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: gesehen.append("issues"))
    monkeypatch.setattr(absturz, "oeffnen", lambda *a, **k: gesehen.append("crash"))
    monkeypatch.setattr(absturz, "vorhanden", lambda: True)
    monkeypatch.setattr(paths, "datei_oeffnen", lambda *a, **k: gesehen.append("lizenz"))
    from src.states.menu.settings_page import SettingsPage
    seite = SettingsPage()
    schale = _schale_mit(seite)
    seite.cat = seite.categories.index("Info")
    seite._build_content()
    _bild(schale)
    kennungen = [k for k, _r in seite._info_links()]
    assert "issues" in kennungen and "crash" in kennungen
    cp.mehrmals(pad, schale, A)                    # Inhalt der Spalte betreten
    for _ in kennungen:
        cp.mehrmals(pad, schale, A, RECHTS)
        _bild(schale)
    assert set(gesehen) >= {"issues", "crash"}, gesehen
    # der Fokusrahmen ist sichtbar: ein Link weiter sieht anders aus
    vorher = _bild(schale)
    cp.mehrmals(pad, schale, RECHTS)
    assert _bild(schale) != vorher


def test_einstellungen_speichern_ist_mit_dem_controller_erreichbar(pad):
    from src.states.menu.settings_page import SettingsPage
    seite = SettingsPage()
    schale = _schale_mit(seite)
    for _ in range(len(seite.categories)):
        cp.mehrmals(pad, schale, RUNTER)
    assert seite._save_focus


# ---------------------------------------------------------------------------
# 2. Die Menueschale: Reiterleiste und Dialoge
# ---------------------------------------------------------------------------

def test_reiterleiste_jeder_reiter_ist_mit_dem_pad_zu_oeffnen(pad):
    from src.states.menu_shell_state import MenuShellState, _TABS
    from tests.test_controller_durchlauf import _ZustandsAttrappe

    for i in range(len(_TABS)):
        schale = MenuShellState(_ZustandsAttrappe())
        schale.enter()
        for _ in range(i):
            cp.mehrmals(pad, schale, RECHTS)
        assert schale.tab == i
        cp.mehrmals(pad, schale, A)
        oeffnet = bool(schale.page_stack) or schale.state_machine.wechsel \
            or schale.state_machine.stapel
        assert oeffnet, f"Reiter {i}: A bewirkt nichts"


def test_beenden_dialog_ist_mit_dem_pad_bedienbar(pad):
    from src.states.menu_shell_state import MenuShellState
    from tests.test_controller_durchlauf import _ZustandsAttrappe
    schale = MenuShellState(_ZustandsAttrappe())
    schale.enter()
    cp.mehrmals(pad, schale, B)                    # Hauptmenü: B fragt
    assert schale._quit_dialog is not None
    cp.mehrmals(pad, schale, B)                    # B = Nein
    assert schale._quit_dialog is None and not schale.quit_requested
    cp.mehrmals(pad, schale, B, A)                 # Ja (Vorauswahl)
    assert schale.quit_requested


def test_dialog_b_waehlt_die_letzte_antwort():
    """Die Regel für alle Dialoge: B ist die ablehnende, letzte Schaltfläche."""
    from src.ui.widgets import Dialog
    d = Dialog("t", "m", [("Speichern", "save"), ("Verwerfen", "discard"),
                          ("Abbrechen", "cancel")])
    e = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0,
                           synthetic=True)
    assert d.handle_event(e) == "cancel"
