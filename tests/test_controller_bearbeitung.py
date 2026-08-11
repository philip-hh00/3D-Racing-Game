"""Controller: ein Stepper muss erst mit A geöffnet werden.

Gemeldet am 31.07.2026: „wenn User mit dem Controller Buttons <Einstellung>
verändern wollen dann sollten die erstmal mit der Taste A den Button
aktivieren. Sonst kann man mit dem Controller nicht auf den nächsten
Einstellungsbutton wechseln der rechts oder links davon liegt."

Ein Stepper beantwortet links/rechts **immer** mit einer Wertänderung und gibt
damit eine Aktion zurück. ``FocusGroup`` verstand das als „erledigt" und bewegte
den Fokus nicht weiter — am Controller, der nur ein D-Pad hat, saß man fest.

Geprüft wird deshalb beides: dass der Fokus geschlossen weiterwandert, und dass
er geöffnet beim Stepper bleibt. Und dass die **Tastatur** unverändert
durchgreift — dort gibt es TAB und Maus, ein Pflicht-ENTER vor jeder Änderung
wäre ein Rückschritt.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.ui.focus import FocusGroup  # noqa: E402
from src.ui.widgets import Button, Stepper  # noqa: E402


def _pad(key: int, **extra) -> pygame.event.Event:
    """Ein Controller-Ereignis, so wie der Gamepad-Manager es erzeugt."""
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0,
                              synthetic=True, **extra)


def _taste(key: int) -> pygame.event.Event:
    """Eine echte Tastatureingabe."""
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0)


@pytest.fixture
def reihe():
    """Drei Stepper nebeneinander — der Fall aus der Meldung."""
    schritte = [Stepper(pygame.Rect(100 + i * 320, 400, 300, 60), "",
                        ["eins", "zwei", "drei"], index=0, action=f"a{i}")
                for i in range(3)]
    return FocusGroup(schritte, vertical=False), schritte


# ---------------------------------------------------------------------------
# Der gemeldete Fehler
# ---------------------------------------------------------------------------
def test_geschlossen_wandert_der_fokus_zum_nachbarn(reihe):
    gruppe, schritte = reihe
    assert gruppe.index == 0

    assert gruppe.handle_event(_pad(pygame.K_RIGHT)) is None
    assert gruppe.index == 1, "der Fokus muss zum Nachbarn rechts"
    assert schritte[0].index == 0, "der Wert darf sich dabei nicht ändern"

    gruppe.handle_event(_pad(pygame.K_RIGHT))
    assert gruppe.index == 2
    gruppe.handle_event(_pad(pygame.K_LEFT))
    assert gruppe.index == 1
    assert all(s.index == 0 for s in schritte)


def test_a_oeffnet_dann_aendert_das_dpad_den_wert(reihe):
    gruppe, schritte = reihe

    assert gruppe.handle_event(_pad(pygame.K_RETURN)) is None, "A feuert nicht"
    assert gruppe.bearbeiten is True

    assert gruppe.handle_event(_pad(pygame.K_RIGHT)) == "a0"
    assert schritte[0].index == 1
    assert gruppe.index == 0, "geöffnet bleibt der Fokus am Stepper"

    assert gruppe.handle_event(_pad(pygame.K_LEFT)) == "a0"
    assert schritte[0].index == 0
    assert gruppe.index == 0


def test_a_schliesst_wieder(reihe):
    gruppe, _ = reihe
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.handle_event(_pad(pygame.K_RETURN))
    assert gruppe.bearbeiten is False
    gruppe.handle_event(_pad(pygame.K_RIGHT))
    assert gruppe.index == 1


def test_b_schliesst_ohne_die_seite_zu_verlassen(reihe):
    """Seiten, die ESC selbst abfangen, sehen das Ereignis nie — wo es
    ankommt, soll B aber nur den Stepper zumachen."""
    gruppe, _ = reihe
    gruppe.handle_event(_pad(pygame.K_RETURN))
    assert gruppe.handle_event(_pad(pygame.K_ESCAPE)) is None
    assert gruppe.bearbeiten is False


def test_geschlossen_bleibt_esc_folgenlos(reihe):
    """Nicht geöffnet ändert ESC nichts — es läuft weiter wie bisher an das
    Widget (ein Texteingabefeld bricht damit ab), und die Seite behält ihr
    „zurück"."""
    gruppe, schritte = reihe
    assert gruppe.handle_event(_pad(pygame.K_ESCAPE)) is None
    assert gruppe.bearbeiten is False
    assert gruppe.index == 0
    assert all(s.index == 0 for s in schritte)


# ---------------------------------------------------------------------------
# Fokuswechsel schließt
# ---------------------------------------------------------------------------
def test_hoch_runter_schliesst(reihe):
    gruppe, _ = reihe
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.handle_event(_pad(pygame.K_DOWN))
    assert gruppe.bearbeiten is False


def test_maus_schliesst(reihe):
    """Mit der Maus trifft man den Pfeil direkt — ein Bearbeitungsmodus wäre
    dort nur ein zusätzlicher Klick."""
    gruppe, schritte = reihe
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.handle_event(pygame.event.Event(
        pygame.MOUSEBUTTONDOWN, button=1, pos=schritte[1].rect.center))
    assert gruppe.bearbeiten is False
    assert gruppe.index == 1


def test_neue_widgets_schliessen(reihe):
    gruppe, _ = reihe
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.set_widgets([Button(pygame.Rect(0, 0, 100, 40), "x", "x")])
    assert gruppe.bearbeiten is False


def test_offen_ohne_passendes_widget_faellt_zurueck():
    """Baut eine Seite die Liste an ``set_widgets`` vorbei um, darf kein
    offener Zustand ohne Stepper zurückbleiben — das D-Pad ginge ins Leere."""
    gruppe = FocusGroup([Stepper(pygame.Rect(0, 0, 300, 60), "", ["a", "b"])],
                        vertical=False)
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.widgets = [Button(pygame.Rect(0, 0, 300, 60), "x", "x"),
                      Button(pygame.Rect(320, 0, 300, 60), "y", "y")]
    assert gruppe.handle_event(_pad(pygame.K_RIGHT)) is None
    assert gruppe.bearbeiten is False
    assert gruppe.index == 1


# ---------------------------------------------------------------------------
# Was sich nicht ändern darf
# ---------------------------------------------------------------------------
def test_tastatur_greift_weiter_direkt_durch(reihe):
    gruppe, schritte = reihe
    assert gruppe.handle_event(_taste(pygame.K_RIGHT)) == "a0"
    assert schritte[0].index == 1
    assert gruppe.bearbeiten is False


def test_tastatur_enter_feuert_weiter(reihe):
    """ENTER zählt an der Tastatur einen Schritt weiter, wie bisher."""
    gruppe, schritte = reihe
    assert gruppe.handle_event(_taste(pygame.K_RETURN)) == "a0"
    assert schritte[0].index == 1


def test_knopf_bleibt_ein_knopf():
    """Nur Stepper sind zu öffnen. Ein Knopf muss am Controller weiterhin mit
    einem einzigen A auslösen."""
    knoepfe = [Button(pygame.Rect(100, 400, 300, 60), "Start", "start"),
               Button(pygame.Rect(420, 400, 300, 60), "Zurück", "back")]
    gruppe = FocusGroup(knoepfe, vertical=False)
    assert gruppe.handle_event(_pad(pygame.K_RETURN)) == "start"
    assert gruppe.bearbeiten is False
    gruppe.handle_event(_pad(pygame.K_RIGHT))
    assert gruppe.index == 1
    assert gruppe.handle_event(_pad(pygame.K_RETURN)) == "back"


def test_gemischte_reihe_knopf_neben_stepper():
    """Der eigentliche Zweck: vom Stepper zum Knopf daneben kommen."""
    stepper = Stepper(pygame.Rect(100, 400, 300, 60), "", ["a", "b"], action="s")
    knopf = Button(pygame.Rect(420, 400, 300, 60), "Weiter", "weiter")
    gruppe = FocusGroup([stepper, knopf], vertical=False)
    gruppe.handle_event(_pad(pygame.K_RIGHT))
    assert gruppe.index == 1
    assert gruppe.handle_event(_pad(pygame.K_RETURN)) == "weiter"


def test_textfeld_bleibt_unberuehrt():
    """Ein Texteingabefeld ist nicht ``bearbeitbar`` — es schluckt links/rechts
    ohnehin für den Cursor, und daran ändert der Controller nichts."""
    from src.ui.widgets import TextInput
    feld = TextInput(pygame.Rect(100, 400, 300, 60), "Name")
    gruppe = FocusGroup([feld], vertical=False)
    assert gruppe._bearbeitbar(feld) is False
    gruppe.handle_event(_pad(pygame.K_RETURN))
    assert gruppe.bearbeiten is False


def test_gesperrter_stepper_haelt_den_fokus_nicht_fest():
    """Ein Stepper ohne Auswahl gibt nichts zurück. Auch geöffnet darf er den
    Fokus dann nicht behalten — sonst wäre die Falle nur verschoben."""
    leer = Stepper(pygame.Rect(100, 400, 300, 60), "", [], action="leer")
    ziel = Button(pygame.Rect(420, 400, 300, 60), "Weiter", "weiter")
    gruppe = FocusGroup([leer, ziel], vertical=False)
    gruppe.bearbeiten = True
    gruppe.handle_event(_pad(pygame.K_RIGHT))
    assert gruppe.index == 1


# ---------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------
def test_zeichnen_meldet_den_offenen_zustand(reihe):
    gruppe, schritte = reihe
    schirm = pygame.Surface((1920, 1080))
    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.draw(schirm)
    assert schritte[0].bearbeitet is True
    assert schritte[1].bearbeitet is False

    gruppe.handle_event(_pad(pygame.K_RETURN))
    gruppe.draw(schirm)
    assert all(s.bearbeitet is False for s in schritte)


def test_offener_stepper_sieht_anders_aus():
    """Ohne sichtbaren Unterschied wäre das eine unsichtbare Umschaltung, und
    niemand wüsste, warum das D-Pad mal den Wert und mal den Fokus bewegt."""
    stepper = Stepper(pygame.Rect(0, 0, 300, 60), "", ["a", "b"])
    schirm = pygame.Surface((300, 60))

    stepper.bearbeitet = False
    stepper.draw(schirm, focused=True)
    zu = pygame.image.tostring(schirm, "RGB")

    schirm.fill((0, 0, 0))
    stepper.bearbeitet = True
    stepper.draw(schirm, focused=True)
    offen = pygame.image.tostring(schirm, "RGB")

    assert zu != offen


# ---------------------------------------------------------------------------
# Doppelte Auswertung des D-Pads
# ---------------------------------------------------------------------------
def test_rohes_hat_ereignis_wird_ignoriert(reihe):
    """Der Gamepad-Manager übersetzt jeden D-Pad-Druck bereits in ein
    synthetisches KEYDOWN. Wertete ``FocusGroup`` zusätzlich das rohe
    JOYHATMOTION aus, sprang der Fokus pro Druck zwei Felder weit."""
    gruppe, _ = reihe
    hat = pygame.event.Event(pygame.JOYHATMOTION, joy=0, instance_id=0,
                             hat=0, value=(1, 0))
    assert gruppe.handle_event(hat) is None
    assert gruppe.index == 0, "das rohe Ereignis darf nichts bewegen"
