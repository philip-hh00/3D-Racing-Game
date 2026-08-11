"""Zufaellige Eingaben in jeden Zustand. Eine einzige Zusage: es bricht nichts.

Der billigste Test, den es gibt, und er haette die beiden Abstuerze vom
05.08.2026 beide gefunden, ohne dass jemand sie melden muss:

* ``NameError: name 'theme' is not defined`` im Streckeneditor — eine
  querschnittliche Aenderung hatte eine von vier Stellen nicht erreicht.
* ``AttributeError: 'SettingsShellAdapter' object has no attribute
  'zurueck_gehen'`` in der Rennpause — dieselbe Woche, dieselbe Ursache.

Beide steckten hinter einem Weg, den man **gehen** muss. Ein Importtest findet
keinen davon, ein Test auf eine bestimmte Taste auch nicht: es war nicht
absehbar, welche Taste es sein wuerde. Zufall ist hier genauer als Absicht.

**Der Startwert steht fest.** Ein Affentest, der bei jedem Lauf andere Tasten
drueckt, faellt irgendwann und ist dann nicht nachzustellen — das ist genau die
Sorte flatterhafter Test, die am 06.08.2026 einen halben Tag gekostet hat. Hier
ist die Folge der Eingaben Teil des Tests: ein Fehlschlag laesst sich wiederholen,
und die Zeile in der Meldung sagt, welcher Schritt es war.

**Was nicht geprueft wird:** ob das Ergebnis sinnvoll ist. Der Affe weiss nicht,
was er tut. Er findet Abstuerze, keine Denkfehler.
"""
from __future__ import annotations

import os
import random
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import gamepad  # noqa: E402
from tests import spielhilfe  # noqa: E402
from tests.test_controller_durchlauf import _ZustandsAttrappe  # noqa: E402
from tests.test_layout_regeln import _INHALT, _ShellAttrappe, _seiten  # noqa: E402

_BILD = (1920, 1080)

#: Wie viele Eingaben je Zustand. Hoch genug, dass der Affe in Untermenues
#: gerat und wieder heraus; niedrig genug, dass der Lauf Sekunden dauert.
_SCHRITTE = 220

#: Fest. Siehe Modulkopf — ein Fund muss nachstellbar sein.
_STARTWERT = 20260807


def _urzustand() -> dict[str, str]:
    """Pruefsummen der Dateien, in die ein Labor schreiben kann.

    Beim Laden dieses Moduls genommen, also bevor der erste Affe laeuft.
    Siehe ``test_der_affe_hinterlaesst_keine_spuren_im_arbeitsbaum``.
    """
    import hashlib
    from pathlib import Path

    wurzel = Path(_ROOT)
    dateien = sorted((wurzel / "data" / "vehicles").glob("*.json")) + \
        sorted((wurzel / "data" / "audio").glob("*.json"))
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dateien}


_URZUSTAND = _urzustand()


def _tastenvorrat() -> list[int]:
    """Die Tasten, die im Spiel etwas bedeuten, plus ein paar, die es nicht tun.

    Die unbedeutenden sind mit Absicht dabei: ein Zustand darf an einer Taste,
    die er nicht kennt, nicht straucheln.
    """
    return [
        pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT,
        pygame.K_RETURN, pygame.K_ESCAPE, pygame.K_SPACE, pygame.K_TAB,
        pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
        pygame.K_PAGEUP, pygame.K_PAGEDOWN, pygame.K_DELETE, pygame.K_BACKSPACE,
        pygame.K_F1, pygame.K_F9, pygame.K_1, pygame.K_2, pygame.K_3,
        pygame.K_LSHIFT, pygame.K_LCTRL,
    ]


def _ereignis(wuerfel: random.Random) -> pygame.event.Event:
    """Ein zufaelliges Eingabeereignis, wie es das Fenster liefern wuerde."""
    art = wuerfel.random()
    if art < 0.45:
        taste = wuerfel.choice(_tastenvorrat())
        return pygame.event.Event(pygame.KEYDOWN, key=taste, unicode="", mod=0)
    if art < 0.55:
        taste = wuerfel.choice(_tastenvorrat())
        return pygame.event.Event(pygame.KEYUP, key=taste, mod=0)
    ort = (wuerfel.randrange(_BILD[0]), wuerfel.randrange(_BILD[1]))
    if art < 0.75:
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=ort,
                                  button=wuerfel.choice([1, 1, 1, 3]))
    if art < 0.85:
        return pygame.event.Event(pygame.MOUSEBUTTONUP, pos=ort, button=1)
    if art < 0.95:
        return pygame.event.Event(pygame.MOUSEMOTION, pos=ort, rel=(1, 1),
                                  buttons=(0, 0, 0))
    return pygame.event.Event(pygame.MOUSEWHEEL, y=wuerfel.choice([-1, 1]), x=0)


def _pad_ereignis(manager, wuerfel: random.Random) -> list[pygame.event.Event]:
    """Ein zufaelliger Pad-Druck, schon in Menuebefehle uebersetzt."""
    tasten = [gamepad.BTN_A, gamepad.BTN_B, gamepad.BTN_X, gamepad.BTN_Y,
              gamepad.BTN_START, gamepad.BTN_BACK,
              gamepad.BTN_DPAD_UP, gamepad.BTN_DPAD_DOWN,
              gamepad.BTN_DPAD_LEFT, gamepad.BTN_DPAD_RIGHT]
    return spielhilfe.pad_druck(manager, wuerfel.choice(tasten))


@pytest.fixture(autouse=True)
def _abgeschirmt(monkeypatch, tmp_path):
    """Der Affe darf alles anfassen — nur nichts hinterlassen.

    Drei Vorkehrungen, jede durch einen Schaden verdient:

    * **Ein Ausweichverzeichnis.** Der Affe findet in Fahrzeug- und Klanglabor
      den Speichern-Knopf, und beide schreiben ueber relative Pfade in
      ``data/``. Beim ersten Lauf am 07.08.2026 standen danach drei
      versionierte Dateien geaendert im Arbeitsbaum.
    * **Ein leerer Ereignisbus** — er faehrt Rennen, und die melden sich am
      prozessweiten Bus an.
    * **Ein eigener Rennaufbau** — er klickt sich durch Strecken- und
      Fahrzeugwahl, und die sind prozessweit.

    Ein Affentest, der den naechsten Test umwirft, ist schlimmer als keiner:
    der Fehler erscheint dann dort, wo er nicht entstanden ist.
    """
    spielhilfe.datenordner_spiegeln(monkeypatch, tmp_path)
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.aufbau_bewahren(monkeypatch)
    yield
    spielhilfe.alles_schliessen()


@pytest.fixture
def pad():
    manager, zurueck = spielhilfe.pad_anmelden()
    yield manager
    zurueck()


# ---------------------------------------------------------------------------
# Die Menueseiten
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_seiten()))
def test_eine_menueseite_ueberlebt_zufaellige_eingaben(name, pad):
    """Tasten, Klicks, Rad und Pad — und dazwischen wird gezeichnet.

    Das Zeichnen gehoert dazu: der Absturz vom 05.08.2026 im Editor kam nicht
    beim Verarbeiten, sondern beim Malen. Wer nur Ereignisse schickt und nie
    rendert, prueft die Haelfte.
    """
    from src.states.menu_shell_state import MenuShellState

    wuerfel = random.Random(_STARTWERT)
    schale = MenuShellState(_ZustandsAttrappe())
    schale.enter()
    schale.push_page(_seiten()[name]())
    schirm = pygame.Surface(_BILD)

    for schritt in range(_SCHRITTE):
        try:
            if wuerfel.random() < 0.25:
                schale.handle_events(_pad_ereignis(pad, wuerfel))
            else:
                schale.handle_events([_ereignis(wuerfel)])
            schale.update(1 / 60)
            schale.render(schirm)
        except Exception as fehler:      # noqa: BLE001 — genau das ist der Fund
            pytest.fail(f"{name}: Schritt {schritt} mit Startwert {_STARTWERT} "
                        f"warf {type(fehler).__name__}: {fehler}")

        if not schale.page_stack:
            # Der Affe hat sich herausgeklickt. Wieder hinein, sonst prueft der
            # Rest des Laufs nur noch das Hauptmenue.
            schale.push_page(_seiten()[name]())


def test_die_menueschale_selbst_ueberlebt_zufaellige_eingaben(pad):
    """Ohne Seite: Reiterleiste, Beenden-Dialog, Ankuendigungen."""
    from src.states.menu_shell_state import MenuShellState

    wuerfel = random.Random(_STARTWERT)
    schale = MenuShellState(_ZustandsAttrappe())
    schale.enter()
    schirm = pygame.Surface(_BILD)

    for schritt in range(_SCHRITTE):
        try:
            if wuerfel.random() < 0.25:
                schale.handle_events(_pad_ereignis(pad, wuerfel))
            else:
                schale.handle_events([_ereignis(wuerfel)])
            schale.update(1 / 60)
            schale.render(schirm)
        except Exception as fehler:      # noqa: BLE001
            pytest.fail(f"Schale: Schritt {schritt} mit Startwert {_STARTWERT} "
                        f"warf {type(fehler).__name__}: {fehler}")


# ---------------------------------------------------------------------------
# Die eigenstaendigen Zustaende
# ---------------------------------------------------------------------------
#
# Der Streckeneditor steht hier nicht aus Vollstaendigkeit: er ist mit 19 %
# der am schlechtesten erreichte Zustand des Spiels und derjenige, in dem der
# Absturz vom 05.08.2026 sass.

def _zustaende():
    from src.states.car_select_state import CarSelectState
    from src.states.editor_state import EditorState
    from src.states.track_select_state import TrackSelectState
    from src.states.vehicle_lab_state import VehicleLabState
    from src.states.welcome_state import WelcomeState

    return {
        "Streckeneditor": EditorState,
        "Fahrzeuglabor": VehicleLabState,
        "Fahrzeugauswahl": CarSelectState,
        "Streckenauswahl": TrackSelectState,
        "Willkommen": WelcomeState,
    }


@pytest.mark.parametrize("name", sorted(_zustaende()))
def test_ein_zustand_ueberlebt_zufaellige_eingaben(name, pad):
    spielhilfe.fahrzeuge_laden()
    spielhilfe.spielstand_zuruecksetzen()

    wuerfel = random.Random(_STARTWERT)
    zustand = _zustaende()[name](_ZustandsAttrappe())
    zustand.enter()
    schirm = pygame.Surface(_BILD)

    try:
        for schritt in range(_SCHRITTE):
            try:
                if wuerfel.random() < 0.25:
                    zustand.handle_events(_pad_ereignis(pad, wuerfel))
                else:
                    zustand.handle_events([_ereignis(wuerfel)])
                zustand.update(1 / 60)
                zustand.render(schirm)
            except Exception as fehler:      # noqa: BLE001
                pytest.fail(f"{name}: Schritt {schritt} mit Startwert "
                            f"{_STARTWERT} warf {type(fehler).__name__}: {fehler}")
    finally:
        if hasattr(zustand, "exit"):
            zustand.exit()


# ---------------------------------------------------------------------------
# Das Rennen
# ---------------------------------------------------------------------------

def test_das_rennen_ueberlebt_zufaellige_eingaben(pad):
    """Waehrenddessen wird wirklich gefahren.

    Pause auf, Pause zu, Einstellungen in der Pause, zurueck — das ist der Weg,
    auf dem am 05.08.2026 der zweite Absturz sass. Er brauchte drei Schritte
    hintereinander, und keiner davon war ungewoehnlich.
    """
    wuerfel = random.Random(_STARTWERT)
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    schirm = pygame.Surface(_BILD)

    try:
        for schritt in range(_SCHRITTE):
            try:
                if wuerfel.random() < 0.25:
                    rennen.handle_events(_pad_ereignis(pad, wuerfel))
                else:
                    rennen.handle_events([_ereignis(wuerfel)])
                rennen.update(1 / 60)
                rennen.render(schirm)
            except Exception as fehler:      # noqa: BLE001
                pytest.fail(f"Rennen: Schritt {schritt} mit Startwert "
                            f"{_STARTWERT} warf {type(fehler).__name__}: {fehler}")
    finally:
        spielhilfe.alles_schliessen()
        spielhilfe.spielstand_zuruecksetzen()


def test_der_affe_hinterlaesst_keine_spuren_im_arbeitsbaum():
    """Kein Test veraendert versionierte Dateien. Auch dieser nicht.

    Beim ersten Lauf am 07.08.2026 tat er es: ``data/vehicles/drifter.json``,
    ``drifter_2.json`` und ``data/audio/motor_klang.json`` standen danach
    geaendert im Arbeitsbaum, weil der Affe in Fahrzeug- und Klanglabor auf
    „Speichern" geraten war. Beide schreiben ueber **relative** Pfade, und die
    Umlenkung in ``conftest.py`` gilt nur fuer Nutzerdaten.

    Der Test steht **hinter** den Affen in dieser Datei und prueft damit deren
    Hinterlassenschaft. Er prueft die Regel, nicht die drei Dateien: alles, was
    ein Labor schreiben kann, ist erfasst.
    """
    import hashlib
    from pathlib import Path

    wurzel = Path(_ROOT)
    dateien = sorted((wurzel / "data" / "vehicles").glob("*.json")) + \
        sorted((wurzel / "data" / "audio").glob("*.json"))
    assert dateien, "keine Datei gefunden — der Test prueft sonst nichts"

    jetzt = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in dateien}
    geaendert = [n for n, h in jetzt.items() if _URZUSTAND.get(n) != h]
    assert geaendert == [], \
        f"der Affentest hat versionierte Dateien veraendert: {geaendert}"


def test_die_rennpause_ueberlebt_zufaellige_eingaben(pad):
    """Gezielt in die Pause und dort herumdruecken.

    Der Affe oben findet die Pause nur zufaellig; hier wird sie geoeffnet und
    der Rest ist wieder Zufall. Der Absturz vom 05.08.2026 lag genau eine Ebene
    tiefer, in den Einstellungen **innerhalb** der Pause.
    """
    wuerfel = random.Random(_STARTWERT)
    rennen, _ = spielhilfe.rennen_bauen("oval", runden=1, feld=2)
    schirm = pygame.Surface(_BILD)

    try:
        spielhilfe.rennen_fahren(rennen, sekunden=4.0)
        rennen._open_pause_settings()

        for schritt in range(_SCHRITTE):
            try:
                if wuerfel.random() < 0.35:
                    rennen.handle_events(_pad_ereignis(pad, wuerfel))
                else:
                    rennen.handle_events([_ereignis(wuerfel)])
                rennen.update(1 / 60)
                rennen.render(schirm)
            except Exception as fehler:      # noqa: BLE001
                pytest.fail(f"Rennpause: Schritt {schritt} mit Startwert "
                            f"{_STARTWERT} warf {type(fehler).__name__}: {fehler}")
    finally:
        spielhilfe.alles_schliessen()
        spielhilfe.spielstand_zuruecksetzen()
