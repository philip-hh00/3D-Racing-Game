"""Layout der neuen Online-Ansichten: kein Text auf Text, nichts seitlich aus dem
Bild (dieselbe Regel wie ``test_layout_regeln``, aber mit Inhalt).

``test_layout_regeln`` zeichnet die Online-Seite ohne Lobbys; hier steht die
Liste voll (lange Namen, Schloss, alle Status) und die Ansichten zum Erstellen,
zur Passwortabfrage und zum Bearbeiten in der Lobby kommen dazu.
"""
from __future__ import annotations

import pygame
import pytest

from tests import spielhilfe
from tests.test_lobbyliste_client import HEL, Api, _e, _in_lobby, _liste, seite  # noqa: F401


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.mark.parametrize("sprache", ["de", "en"])
@pytest.mark.parametrize("ansicht", ["liste", "erstellen", "erstellen_pw", "passwort",
                                     "lobby", "bearbeiten"])
def test_layout_der_neuen_ansichten(ansicht, sprache, seite, monkeypatch):  # noqa: F811
    spielhilfe.sprache_setzen(monkeypatch, sprache)
    mit = spielhilfe.gezeichnete_texte(monkeypatch)
    api = Api({"helsinki": [_e("HAAAAA", "Eine recht lange Lobbybezeichnung",
                               host="LangerHostName", password=True,
                               mode="Team-Zeitfahren"),
                            _e("HBBBBB", "Zweite", status="racing", mode="Grand Prix"),
                            _e("HCCCCC", "Dritte", players=4, mx=4)],
               "hamburg": [_e("DAAAAA", "Hamburger", password=True)]})
    from src.states.menu.lobby_browser import LobbyBrowser
    seite._browser = LobbyBrowser(_liste(api))
    seite.update(0.016)
    if ansicht == "erstellen":
        seite._oeffne_erstellen()
    elif ansicht == "erstellen_pw":
        seite._oeffne_erstellen()
        seite._angaben.stepper.index = 1
        seite._host_gruppe_bauen(behalten=True)
        seite._msg = "Das Passwort braucht 4 bis 16 Zeichen."
    elif ansicht == "passwort":
        seite._pw_ziel = (HEL, "HAAAAA")
        seite._passwort_abfrage(falsch=True)
    elif ansicht in ("lobby", "bearbeiten"):
        _in_lobby(seite, monkeypatch)
        seite._lobby_name = "Eine recht lange Lobbybezeichnung"
        seite._lobby_sicht = "password"
        seite._lobby_hat_pw = True
        if ansicht == "bearbeiten":
            seite._lobby_edit_oeffnen()
            seite._edit_angaben.meldung = "Das Passwort braucht 4 bis 16 Zeichen."
    schirm = pygame.Surface((1920, 1080))
    seite.draw(schirm, pygame.Rect(0, 72, 1920, 1008))
    assert mit.zuege
    schlimm = [f"{a.text!r}{tuple(a.tinte)} liegt auf {b.text!r}{tuple(b.tinte)}"
               for a, b in mit.ueberlagerungen()]
    assert schlimm == [], "\n".join(schlimm)
    raus = [z.text for z in mit.zuege if z.tinte.left < 0 or z.tinte.right > 1920]
    assert raus == []


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_zahnrad_sitzt_neben_den_lobbyangaben(sprache, seite, monkeypatch):  # noqa: F811
    """Sichtbarkeit & Name ist ein Zahnrad oben rechts, nicht mehr ein Knopf in
    der Spalte der Rennoptionen; es liegt auf keinem Text und im Bild."""
    spielhilfe.sprache_setzen(monkeypatch, sprache)
    mit = spielhilfe.gezeichnete_texte(monkeypatch)
    _in_lobby(seite, monkeypatch)
    seite._lobby_name = "Eine recht lange Lobbybezeichnung"
    seite._lobby_sicht = "password"
    seite.update(0.016)
    zahnrad = seite._btn_lobbyinfo
    assert zahnrad not in seite._host_column_widgets()
    assert pygame.Rect(0, 0, 1920, 1080).contains(zahnrad.rect)
    assert zahnrad.rect.w == zahnrad.rect.h <= 56
    schirm = pygame.Surface((1920, 1080))
    seite.draw(schirm, pygame.Rect(0, 72, 1920, 1008))
    ueber = [z.text for z in mit.zuege if z.tinte.colliderect(zahnrad.rect)]
    assert ueber == []
    namen = {z.text: z for z in mit.zuege}
    assert namen["Eine recht lange Lobbybezeichnung"].tinte.right < zahnrad.rect.left
    # kein Knopf der linken Spalte traegt mehr den Namen der Funktion
    assert not any(getattr(b, "action", "") == "lobby_info"
                   for b in seite._host_column_widgets())


def test_zahnrad_ist_per_tastatur_erreichbar_nach_dem_start_knopf(seite, monkeypatch):  # noqa: F811
    _in_lobby(seite, monkeypatch)
    seite._refresh_focus_group()
    w = seite._lobby_group.widgets
    assert w.index(seite._btn_lobbyinfo) == w.index(seite._btn_start) + 1
    assert seite._btn_lobbyinfo.focusable and seite._btn_lobbyinfo.enabled
