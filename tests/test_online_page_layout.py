"""Serverauswahl: Navigation und Layout.

Zwei Playtest-Funde vom 28.07.2026 werden hier festgehalten:

1. ESC bzw. Controller-B sprang aus jedem Untermenü direkt ins Hauptmenü statt
   eine Stufe zurück. Ursache: ``handle_event`` gab nichts zurück, also hielt
   die Menü-Shell das Ereignis für unverbraucht und warf zusätzlich zur
   internen Rückkehr die ganze Seite weg.
2. In der Serverliste überlagerten sich Ping und Lobby-Anzahl, und die
   Spaltenüberschriften liefen in die Unterschrift der Seite.

Layout wird gegen echte Textbreiten geprüft, nicht gegen Wunschwerte — die
längsten Texte ("Version veraltet", "Keine Lobbys") sind der Maßstab.
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


class _ShellAttrappe:
    def __init__(self) -> None:
        self.state_machine = types.SimpleNamespace(transition=lambda *a, **k: None)
        self.gepoppt = 0

    def pop_page(self) -> None:
        self.gepoppt += 1

    def push_page(self, page) -> None:
        pass


def _seite():
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers

    # Prober stilllegen: der Test soll kein Netz anfassen.
    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    page = olp.OnlineLobbyPage()
    page.enter(_ShellAttrappe())
    return page, olp


def _esc():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)


# ── Navigation ───────────────────────────────────────────────────────────────

def test_zurueck_aus_serverauswahl_geht_eine_stufe_hoch():
    page, olp = _seite()
    page._view = olp._HOST_SERVER
    verbraucht = page.handle_event(_esc())
    assert page._view == olp._ROLE
    assert verbraucht is True          # Shell darf die Seite NICHT wegwerfen


def test_zurueck_aus_codeeingabe_geht_eine_stufe_hoch():
    page, olp = _seite()
    page._view = olp._JOIN
    verbraucht = page.handle_event(_esc())
    assert page._view == olp._ROLE
    assert verbraucht is True


def test_zurueck_aus_rollenauswahl_verlaesst_die_seite():
    """Hier gibt es keine Ebene mehr — das Ereignis muss durchgereicht werden,
    damit die Shell die Seite schliesst."""
    page, olp = _seite()
    page._view = olp._ROLE
    assert page.handle_event(_esc()) is not True


def test_zurueck_beim_verbinden_bricht_ab_ohne_die_seite_zu_schliessen():
    page, olp = _seite()
    page._view = olp._CONNECTING
    page._return_view = olp._HOST_SERVER
    assert page.handle_event(_esc()) is True
    assert page._view == olp._HOST_SERVER


def test_zurueck_knopf_fuehrt_ebenfalls_eine_stufe_hoch():
    page, olp = _seite()
    page._view = olp._HOST_SERVER
    page._host_group.index = page._host_group.widgets.index(page._btn_back_host)
    page.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                                         unicode="\r", mod=0))
    assert page._view == olp._ROLE


# ── Layout ───────────────────────────────────────────────────────────────────

def _breite(text: str, groesse) -> int:
    from src.ui import theme
    return theme.font(groesse).size(text)[0]


def test_ping_und_status_ueberlagern_sich_nicht():
    from src.ui import theme
    from src.ui.widgets import ServerRow

    # Ungünstigster Fall: längster Ping neben längstem Statustext.
    ping_rechts = ServerRow.COL_PING
    status_links = 840 - 20 - ServerRow.COL_STATUS_W
    assert ping_rechts < status_links, (
        f"Ping endet bei {ping_rechts}, Statusspalte beginnt bei {status_links}")

    laengster_status = max(_breite(t, theme.LABEL) for t in
                           ("Keine Lobbys", "Version veraltet", "12 Lobbys", "Offline"))
    assert laengster_status <= ServerRow.COL_STATUS_W, (
        f"Längster Statustext {laengster_status} px passt nicht in "
        f"{ServerRow.COL_STATUS_W} px")


def test_name_reicht_nicht_in_die_balken():
    from src.ui.widgets import ServerRow
    assert ServerRow.COL_NAME + 100 < ServerRow.COL_BARS


def test_spaltenueberschriften_liegen_unter_der_unterschrift():
    """Überschriften sassen vorher auf y=244, die Unterschrift auf y=240."""
    page, olp = _seite()
    unterschrift_unterkante = 226 + 34          # Textgrösse BODY
    erste_zeile = page._server_rows[0].rect.y
    ueberschrift_y = erste_zeile - 30
    assert ueberschrift_y > unterschrift_unterkante, (
        f"Überschrift bei y={ueberschrift_y} kollidiert mit Unterschrift "
        f"(endet bei {unterschrift_unterkante})")


def test_zeilen_und_knoepfe_ueberlappen_sich_nicht():
    page, _olp = _seite()
    letzte_zeile = page._server_rows[-1].rect
    assert page._btn_create.rect.top >= letzte_zeile.bottom
    assert page._btn_back_host.rect.right < page._btn_create.rect.left


def test_alle_views_zeichnen_ohne_fehler():
    page, olp = _seite()
    screen = pygame.display.get_surface()
    bereich = pygame.Rect(0, 90, 1920, 990)
    for view in (olp._ROLE, olp._HOST_SERVER, olp._JOIN, olp._CONNECTING):
        page._view = view
        page._msg = "Testmeldung"
        page.update(0.016)
        screen.fill((0, 0, 0))
        page.draw(screen, bereich)
