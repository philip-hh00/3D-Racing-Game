"""Entfernen und Melden mit dem Controller allein (Vorgabe: jeder Knopf erreichbar
und sichtbar im Fokus).

Prueft die neuen Bedienelemente des Online-Schutzes ueber den Weg des Spiels
(Pad-Knopf -> GamepadManager -> synthetische Taste -> Seite), mit demselben
Werkzeug wie ``test_controller_online``: Kreuzknoepfe in der Lobby (Host) und
Fahnen auf der Ergebnisseite.
"""
from __future__ import annotations

import os
import sys

import pygame
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import gamepad  # noqa: E402
from tests import controller_pruefung as cp  # noqa: E402
from tests import spielhilfe  # noqa: E402
from tests.test_schutz_client import _zeichne, ergebnis, lobby  # noqa: E402,F401

A, B = gamepad.BTN_A, gamepad.BTN_B
RECHTS, RUNTER = gamepad.BTN_DPAD_RIGHT, gamepad.BTN_DPAD_DOWN

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


# ── Lobby ────────────────────────────────────────────────────────────────────

def test_lobby_kreuzknoepfe_sind_gezeichnet_im_fokus_und_erreichbar(lobby, pad, monkeypatch):
    mit = cp.Zeichenmitschrift(monkeypatch)
    _bild(lobby)
    assert cp.nicht_im_fokus(mit, [lobby._lobby_group]) == []
    assert cp.erreichbarkeit(pad, lobby, lobby._lobby_group) == []
    assert any(w in lobby._lobby_group.widgets for w in lobby._kick_buttons)


def test_lobby_fokus_auf_dem_kreuzknopf_ist_sichtbar(lobby):
    gruppe = lobby._lobby_group
    bilder = set()
    stellen = [i for i, w in enumerate(gruppe.widgets) if getattr(w, "focusable", False)]
    for i in stellen:
        gruppe.index = i
        bilder.add(_bild(lobby))
    assert len(bilder) == len(stellen)


def test_lobby_entfernen_nur_mit_dem_pad(lobby, pad):
    ziel = lobby._kick_buttons[0]
    lobby._lobby_group.index = lobby._lobby_group.widgets.index(ziel)
    cp.druecke(pad, lobby, A)
    assert lobby._dialog is not None and lobby._kick_ziel == (1, "Ben")
    assert lobby.netz.gesendet == []
    cp.druecke(pad, lobby, B)                                   # B = Nein
    assert lobby._dialog is None and lobby.netz.gesendet == []
    cp.druecke(pad, lobby, A)
    cp.druecke(pad, lobby, A)                                   # Fokus steht auf „Ja"
    assert lobby.netz.gesendet == [{"type": "KICK", "slot": 1}]


# ── Ergebnisse ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("meta", [{}, {"is_team_zeitfahren": True}, {"is_grand_prix": True}])
def test_fahnen_sind_im_fokus_und_erreichbar(meta, ergebnis, pad, monkeypatch):
    seite = ergebnis(meta)
    if meta.get("is_grand_prix"):
        seite._gp_view = {"gp_active": True, "gp_race": 1, "gp_total": 3, "gp_standings": []}
    mit = cp.Zeichenmitschrift(monkeypatch)
    _zeichne(seite)
    assert cp.nicht_im_fokus(mit, [seite.group]) == []
    assert cp.erreichbarkeit(pad, seite, seite.group) == []


def test_fahnen_fokus_ist_sichtbar(ergebnis):
    seite = ergebnis()
    bilder = set()
    stellen = [i for i, w in enumerate(seite.group.widgets) if getattr(w, "focusable", False)]
    for i in stellen:
        seite.group.index = i
        schirm = _zeichne(seite)
        bilder.add(pygame.image.tobytes(schirm, "RGB"))
    assert len(bilder) == len(stellen)


def test_melden_nur_mit_dem_pad(ergebnis, pad):
    seite = ergebnis()
    fahne = seite._melde_knoepfe[0]
    seite.group.index = seite.group.widgets.index(fahne)
    cp.druecke(pad, seite, A)
    assert seite._melde_dialog is not None
    cp.druecke(pad, seite, B)                                   # B bricht ab
    assert seite._melde_dialog is None and seite.netz.gesendet == []
    cp.druecke(pad, seite, A)
    cp.druecke(pad, seite, A)                                   # erster Grund: Schummeln
    assert seite.netz.gesendet == [{"type": "REPORT_PLAYER", "slot": 1, "name": "Ben",
                                    "reason": "cheating"}]
