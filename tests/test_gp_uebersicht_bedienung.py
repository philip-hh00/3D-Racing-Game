"""Bedienung von Grand-Prix-Lobby und -Übersicht (Playtest 29.07.2026).

Sechs Funde aus einer Runde zu zweit:

1. Der Gast konnte sich in der Übersicht nicht bereit melden — jede
   LOBBY_STATE-Nachricht des Servers rief erneut `_enter_gp_overview()` auf,
   und das setzt „Bereit" bewusst zurück. Damit konnte der Host nie starten.
2. Der Bereit-Knopf der Übersicht hieß immer „Bereit", auch wenn die Wertung
   daneben schon „Bereit √" zeigte — und stand dauerhaft hervorgehoben da.
3. In der Lobby wählte der Host bei Grand Prix eine Strecke, die die Übersicht
   danach sowieso überschreibt. Zwei Orte für dieselbe Entscheidung.
4. Der Startknopf hieß „RENNEN STARTEN", führt bei Grand Prix aber in die
   Übersicht.
5. Die Serienlänge stand über den Runden statt darunter.
6. An der abgeschnittenen Kachelliste war nicht zu erkennen, wie viel noch folgt.
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
from tests.test_gp_online_start import (  # noqa: E402
    SPIELER, _NetzAttrappe, _ShellAttrappe, _seite_in_der_uebersicht,
)


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


def _lobby_state(seite, **settings) -> dict:
    grund = {"gp_active": True, "gp_phase": "overview",
             "gp_race": 1, "gp_total": 3, "gp_standings": []}
    grund.update(settings)
    return {"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": seite._players,
        "mode": "Grand Prix", "settings": grund,
    }}


def _seite_in_der_lobby(ist_host: bool, netz: _NetzAttrappe, modus: str):
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers

    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = ist_host
    seite._view = olp._LOBBY
    seite._players = list(SPIELER)
    seite._selected_mode = modus
    seite._mode_stepper.index = olp._MODE_KEYS.index(modus)
    seite._build_lobby_group()
    return seite, olp


# ── 1. Gast kann sich bereit melden ─────────────────────────────────────────

def test_bereit_des_gastes_ueberlebt_die_naechste_lobby_nachricht(serie, netz):
    """Der Fund, der den Host blockierte: der Gast drückt „Bereit", die nächste
    Serverantwort nimmt es ihm sofort wieder weg."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)

    seite._toggle_ready()
    assert seite._lobby_ready is True

    # Der Server bestätigt und schickt die Liste zurück — mit uns als bereit.
    seite._players[1]["lobby_ready"] = True
    seite._on_net(_lobby_state(seite))

    assert seite._lobby_ready is True, "Bereit wurde durch LOBBY_STATE zurückgesetzt"
    assert "LOBBY_UNREADY" not in [m.get("type") for m in netz.gesendet]


def test_gast_betritt_die_uebersicht_nur_einmal(serie, netz):
    """Der erneute Eintritt baut auch die Bedienleiste neu und wirft dabei den
    Fokus weg — mitten in der Bedienung."""
    seite, _sh, olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    gruppe = seite._gp_group

    seite._on_net(_lobby_state(seite))

    assert seite._view == olp._GP_OVERVIEW
    assert seite._gp_group is gruppe, "Bedienleiste wurde ohne Not neu gebaut"


def test_gast_wechselt_weiterhin_aus_der_lobby_in_die_uebersicht(serie, netz):
    """Die Absicherung darf den eigentlichen Wechsel nicht verhindern."""
    seite, olp = _seite_in_der_lobby(ist_host=False, netz=netz, modus="Grand Prix")
    seite._on_net(_lobby_state(seite))
    assert seite._view == olp._GP_OVERVIEW


# ── 2. Bereit-Knopf der Übersicht ───────────────────────────────────────────

def test_knopf_zeigt_den_gegenteiligen_zustand(serie, netz):
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    assert seite._btn_gp_ready.label == "Bereit"

    seite._toggle_ready()
    assert seite._btn_gp_ready.label == "Nicht bereit"

    seite._toggle_ready()
    assert seite._btn_gp_ready.label == "Bereit"


def test_knopf_steht_nicht_dauerhaft_hervorgehoben(serie, netz):
    """Wer bereit ist, hat hier nichts mehr zu tun — dann darf der Knopf auch
    nicht wie die nächste Handlung aussehen."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    assert seite._btn_gp_ready.style == "primary"

    seite._toggle_ready()
    assert seite._btn_gp_ready.style == "secondary"


def test_knopf_folgt_auch_dem_server(serie, netz):
    """Der Server räumt „Bereit" bei jeder Einstellungsänderung ab. Der Knopf
    muss das mitbekommen, sonst behauptet er das Gegenteil der Wertung."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=False, netz=netz)
    seite._toggle_ready()
    assert seite._btn_gp_ready.label == "Nicht bereit"

    seite._players[1]["lobby_ready"] = False
    seite._on_net(_lobby_state(seite))

    assert seite._lobby_ready is False
    assert seite._btn_gp_ready.label == "Bereit"


# ── 3.-5. Linke Spalte der Lobby ────────────────────────────────────────────

def test_grand_prix_hat_keine_streckenwahl_in_der_lobby(netz):
    """Die Strecke wird vor jedem Lauf in der Übersicht gewählt. Eine zweite
    Stelle dafür verspricht eine Wahl, die der nächste Lauf überschreibt."""
    seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus="Grand Prix")
    spalte = seite._host_column_widgets()

    assert seite._btn_track not in spalte
    assert seite._btn_vehicle in spalte, "Fahrzeug bleibt wählbar"


def test_normales_rennen_behaelt_die_streckenwahl(netz):
    seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus="Rennen")
    assert seite._btn_track in seite._host_column_widgets()


def test_serienlaenge_steht_unter_den_runden(netz):
    """Vorher stand sie als viertes über den Runden."""
    seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus="Grand Prix")
    spalte = seite._host_column_widgets()
    assert spalte.index(seite._gp_races_stepper) == spalte.index(seite._laps_stepper) + 1


def test_spalte_hat_keine_luecken(netz):
    """Ausgeblendete Bedienelemente dürfen kein Loch hinterlassen — die Spalte
    wird gerechnet, nicht einmalig beim Aufbau festgenagelt."""
    for modus in ("Rennen", "Grand Prix"):
        seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus=modus)
        spalte = seite._host_column_widgets()
        for oben, unten in zip(spalte, spalte[1:]):
            abstand = unten.rect.y - oben.rect.bottom
            assert abstand == 12, f"{modus}: Abstand {abstand} px statt 12"


def test_startknopf_heisst_bei_grand_prix_zur_uebersicht(netz):
    seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus="Grand Prix")
    assert "Übersicht" in seite._btn_start.label

    seite, _olp = _seite_in_der_lobby(ist_host=True, netz=netz, modus="Rennen")
    assert "RENNEN STARTEN" in seite._btn_start.label


# ── 6. Bildlaufleiste der Streckenliste ─────────────────────────────────────

def _uebersicht_mit(anzahl: int):
    from src.states.menu.gp_overview import GPOverview
    ui = GPOverview()
    ui.keys = [f"strecke_{i}" for i in range(anzahl)]
    return ui


def test_keine_leiste_wenn_alles_sichtbar_ist():
    from src.states.menu.gp_overview import VISIBLE_TILES
    ui = _uebersicht_mit(VISIBLE_TILES)
    assert ui.scrollbar_rects() is None


def test_daumen_zeigt_anteil_und_stelle():
    from src.states.menu.gp_overview import VISIBLE_TILES
    ui = _uebersicht_mit(VISIBLE_TILES * 3)
    bahn, daumen = ui.scrollbar_rects()

    assert bahn.height > daumen.height, "Daumen füllt die ganze Bahn"
    assert daumen.top == bahn.top, "am Anfang steht der Daumen oben"

    ui.cursor = len(ui.keys) - 1
    ui.move(0)                      # Scrollfenster nachziehen
    _bahn, unten = ui.scrollbar_rects()
    assert unten.bottom == bahn.bottom, "am Ende steht der Daumen unten"
    assert unten.top > daumen.top


def test_mausrad_blaettert_ohne_die_auswahl_mitzunehmen(serie, netz):
    """Blättern und Auswählen sind zwei Dinge. Nahm das Rad den Cursor mit,
    wanderte beim Scrollen die Streckenvorschau mit — und der Host stand am
    Ende auf einer Strecke, die er nie angesehen hatte."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_ui.keys = [f"strecke_{i}" for i in range(20)]
    seite._gp_ui.cursor = 0

    seite._gp_event(pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-3))

    assert seite._gp_ui.scroll == 3
    assert seite._gp_ui.cursor == 0, "Rad hat die Auswahl mitgenommen"


def test_blaettern_laeuft_nicht_ueber_die_liste_hinaus():
    from src.states.menu.gp_overview import VISIBLE_TILES
    ui = _uebersicht_mit(VISIBLE_TILES + 2)

    ui.scroll_by(-5)
    assert ui.scroll == 0

    ui.scroll_by(99)
    assert ui.scroll == 2, "unter der letzten Kachel darf kein Leerraum stehen"


def test_pfeiltasten_holen_die_auswahl_zurueck_ins_bild(serie, netz):
    """Nach dem Blättern muss die Tastatur wieder zusammenführen, sonst
    bewegt sich der Cursor unsichtbar außerhalb des Ausschnitts."""
    seite, _sh, _olp = _seite_in_der_uebersicht(ist_host=True, netz=netz)
    seite._gp_ui.keys = [f"strecke_{i}" for i in range(20)]
    seite._gp_ui.cursor = 0
    seite._gp_ui.scroll_by(10)

    seite._gp_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,
                                       unicode="", mod=0))

    assert seite._gp_ui.cursor == 1
    assert seite._gp_ui.scroll <= 1


def test_leiste_liegt_neben_den_kacheln_nicht_in_der_wertung():
    from src.states.menu.gp_overview import RIGHT_X, TILE_W, TILE_X, VISIBLE_TILES
    ui = _uebersicht_mit(VISIBLE_TILES * 2)
    bahn, _daumen = ui.scrollbar_rects()
    assert TILE_X + TILE_W <= bahn.x
    assert bahn.right < RIGHT_X
