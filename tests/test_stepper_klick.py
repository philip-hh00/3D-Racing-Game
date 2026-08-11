"""Klickflächen der Stepper (Playtest 03.08.2026).

Gemeldet: „Klicken der Pfeile der Einstellungstasten in den Einstellungen oder
Lobby ist manchmal verbuggt, nur die linke Seite des Buttons lässt einen nach
links gehen, der Pfeil sitzt aber mittig — sehr verwirrend für den User."

Beides war richtig beobachtet. Bei einem Stepper *mit Beschriftung* sitzt der
Wähler rechts im Element, das ‹ steht also mitten im Kasten; ``handle_click``
zählte aber alles, was nicht genau auf einem der zwei 46 px breiten Pfeile lag,
**vorwärts**. Ein Klick auf die Beschriftung ganz links verstellte den Wert nach
rechts.

Geprüft wird deshalb die Regel, die man dem Element ansieht: links vom Wert
zurück, rechts vom Wert vor, Beschriftung tut nichts.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.ui.widgets import Stepper  # noqa: E402

OPTIONEN = ["Aus", "Niedrig", "Mittel", "Hoch"]


def stepper(label="Texturqualität", breite=560):
    return Stepper(pygame.Rect(100, 200, breite, 60), label, list(OPTIONEN), 2)


# ---------------------------------------------------------------------------
# Der gemeldete Fehler
# ---------------------------------------------------------------------------
def test_klick_auf_die_beschriftung_verstellt_nichts():
    """Der Kern der Meldung. Vorher zählte diese Stelle vorwärts."""
    s = stepper()
    links, _rechts = s._arrow_rects()
    auf_beschriftung = (s.rect.x + 20, s.rect.centery)
    assert auf_beschriftung[0] < links.x, "Messpunkt liegt nicht im Beschriftungsteil"
    assert s.handle_click(auf_beschriftung) is None
    assert s.index == 2, "die Beschriftung ist kein Knopf"


def test_links_vom_wert_geht_zurueck_rechts_davon_vor():
    s = stepper()
    zurueck, vor = s._klickhaelften()
    assert s.handle_click(zurueck.center) == "change"
    assert s.index == 1
    assert s.handle_click(vor.center) == "change"
    assert s.index == 2


def test_die_pfeile_liegen_in_ihrer_eigenen_haelfte():
    """Sonst zeigt der Pfeil in die eine Richtung und der Klick geht in die
    andere — genau die Verwirrung aus der Meldung."""
    for label in ("Texturqualität", ""):
        s = stepper(label)
        pfeil_links, pfeil_rechts = s._arrow_rects()
        zurueck, vor = s._klickhaelften()
        assert zurueck.collidepoint(pfeil_links.center), label
        assert vor.collidepoint(pfeil_rechts.center), label


def test_die_haelften_beruehren_sich_ohne_luecke_und_ohne_ueberlappung():
    for breite in (240, 400, 560, 900):
        s = stepper(breite=breite)
        zurueck, vor = s._klickhaelften()
        assert zurueck.right == vor.x, breite
        assert not zurueck.colliderect(vor), breite


def test_der_ganze_waehler_ist_klickbar():
    """Großzügig treffen soll man dürfen — nur eben in die richtige Richtung."""
    s = stepper()
    zurueck, vor = s._klickhaelften()
    for x in range(zurueck.x, zurueck.right, 7):
        s.index = 2
        assert s.handle_click((x, s.rect.centery)) == "change"
        assert s.index == 1, f"x={x} ging nicht zurück"
    for x in range(vor.x, vor.right, 7):
        s.index = 2
        assert s.handle_click((x, s.rect.centery)) == "change"
        assert s.index == 3, f"x={x} ging nicht vor"


def test_ohne_beschriftung_ist_der_ganze_kasten_der_waehler():
    s = stepper(label="")
    zurueck, vor = s._klickhaelften()
    assert zurueck.x == s.rect.x
    assert vor.right == s.rect.right


def test_klick_ausserhalb_bleibt_folgenlos():
    s = stepper()
    for pos in ((s.rect.x - 5, s.rect.centery), (s.rect.right + 5, s.rect.centery),
                (s.rect.centerx, s.rect.y - 5), (s.rect.centerx, s.rect.bottom + 5)):
        assert s.handle_click(pos) is None
        assert s.index == 2


# ---------------------------------------------------------------------------
# Was unverändert bleiben muss
# ---------------------------------------------------------------------------
def test_gesperrt_bleibt_gesperrt():
    s = Stepper(pygame.Rect(0, 0, 500, 60), "X", list(OPTIONEN), 2, enabled=False)
    zurueck, vor = s._klickhaelften()
    assert s.handle_click(zurueck.center) is None
    assert s.handle_click(vor.center) is None
    assert s.index == 2


def test_ohne_optionen_passiert_nichts():
    s = Stepper(pygame.Rect(0, 0, 500, 60), "X", [])
    zurueck, vor = s._klickhaelften()
    assert s.handle_click(zurueck.center) is None
    assert s.handle_click(vor.center) is None


def test_tastatur_und_controller_bleiben_wie_sie_waren():
    s = stepper()
    assert s.handle_key(pygame.K_LEFT) == "change" and s.index == 1
    assert s.handle_key(pygame.K_RIGHT) == "change" and s.index == 2
    assert s.activate() == "change" and s.index == 3
    assert s.activate() == "change" and s.index == 0, "läuft um"


@pytest.mark.parametrize("breite", [120, 240, 560, 1200])
def test_die_haelften_bleiben_in_jedem_kasten(breite):
    s = stepper(breite=breite)
    for r in s._klickhaelften():
        assert s.rect.contains(r), breite
        assert r.width > 0
