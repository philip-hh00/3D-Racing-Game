"""Block G — Streckenvorschläge, geprüft mit zwei echten Online-Spielern.

Kein Attrappen-Netz: hier läuft der richtige Relay aus ``server/server.py`` auf
einem freien Port, und zwei ``NetworkClient``-Verbindungen hängen mit je einer
``OnlineLobbyPage`` daran. Genau der Ablauf aus dem Plan (§3a G1):

    Gastgeber schaltet Vorschläge frei
      → Gast legt eine eigene Strecke in die Lobby
      → beide sehen sie in der Liste
      → der Gastgeber lädt sie herunter und behält sie
      → er wählt sie aus und startet damit ein Rennen

Warum so aufwendig: die Teile einzeln zu prüfen sagt nichts darüber, ob sie
zusammenpassen. Genau dort lagen die letzten Funde — Nachrichtennamen, die nur
auf einer Seite stimmten, und Zustände, die der Server anders sah als der
Client.

Wichtig für den Aufbau: ``session.set()`` trennt beim Setzen die vorherige
Verbindung. Zwei Clients in einem Prozess brauchen deshalb ein Monkeypatch, das
nur ``session.get`` umbiegt — sonst schießt der Testaufbau seinen eigenen Gast
ab und die Prüfung wird wertlos.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import relaishilfe  # noqa: E402
sys.path.insert(0, os.path.join(_ROOT, "server"))

import pygame  # noqa: E402

import server as srv  # noqa: E402
from src.core import grand_prix, paths, race_setup  # noqa: E402
from src.core.version import VERSION  # noqa: E402
from src.net import session  # noqa: E402
from src.net.client import NetworkClient  # noqa: E402
from src.states.menu import online_lobby_page as olp  # noqa: E402


# ── Aufbau ──────────────────────────────────────────────────────────────────

class _Shell:
    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []
        self.state_machine = types.SimpleNamespace(
            transition=lambda name, **kw: self.wechsel.append((name, kw)))
        self.page_stack: list = []
        self.tab = 2

    def pop_page(self) -> None:
        pass


#: Gemeinsame Fassung, siehe tests/relaishilfe.py — sie faehrt sauber
#: herunter, statt den Ereignisfaden mitten in offenen Verbindungen
#: anzuhalten (06.08.2026).
_Relay = relaishilfe.Relay


@pytest.fixture
def relay():
    r = _Relay()
    r.start()
    yield r
    r.stop()


@pytest.fixture
def aufraeumen(tmp_path, monkeypatch):
    """Empfangene Strecken landen im Nutzerverzeichnis — hier ein leeres."""
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    grand_prix.cancel()
    yield
    grand_prix.cancel()


def _seite(ist_host: bool) -> tuple[olp.OnlineLobbyPage, _Shell]:
    from src.net import server_probe, servers
    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE,
                                  ping_ms=1.0, lobby_count=0)
        for sd in servers.all_servers()
    ]
    sh = _Shell()
    seite = olp.OnlineLobbyPage()
    seite.enter(sh)
    seite._is_host = ist_host
    # Die Seite pumpt das Netz nur in den Ansichten, die eine Verbindung haben.
    # Nach enter() steht sie auf der Rollenwahl — dort käme JOIN_OK nie an.
    seite._view = olp._CONNECTING
    return seite, sh


#: Verbindung des Arbeitsfadens, in dem gerade etwas hochgeladen wird.
_FADEN = threading.local()


class _ErbenderFaden(threading.Thread):
    """Arbeitsfaden, der die Verbindung seines Erzeugers mitnimmt.

    Nötig, weil Strecken-Uploads im Hintergrund laufen und dort ``session.get``
    aufrufen. Im echten Spiel gibt es genau eine Verbindung je Prozess; hier
    zwei, und der Pump schaltet zwischen ihnen um — ohne diese Vererbung lädt
    der Gast über die Leitung des Gastgebers hoch und der Server verwirft es.
    """

    def __init__(self, *a, **kw) -> None:
        self._besitzer = _Spieler.aktiv
        super().__init__(*a, **kw)

    def run(self) -> None:
        _FADEN.netz = self._besitzer
        super().run()


class _Spieler:
    """Eine Verbindung samt Seite. `pumpen()` schaltet session.get auf sie um."""

    aktiv: "NetworkClient | None" = None

    def __init__(self, ist_host: bool, port: int) -> None:
        self.netz = NetworkClient()
        assert self.netz.connect("127.0.0.1", port), "Verbindung fehlgeschlagen"
        self.seite, self.shell = _seite(ist_host)

    def pumpen(self, sekunden: float = 0.4) -> None:
        ende = time.time() + sekunden
        while time.time() < ende:
            _Spieler.aktiv = self.netz
            self.seite.update(0.016)
            time.sleep(0.01)

    def trennen(self) -> None:
        try:
            self.netz.disconnect()
        except Exception:
            pass


def _pumpen(*spieler: _Spieler, sekunden: float = 0.6) -> None:
    """Alle Seiten abwechselnd bedienen, damit Nachrichten hin und her laufen."""
    ende = time.time() + sekunden
    while time.time() < ende:
        for s in spieler:
            _Spieler.aktiv = s.netz
            s.seite.update(0.016)
        time.sleep(0.01)


def _netz_der_aufrufenden_seite():
    """Im Arbeitsfaden die geerbte Verbindung, sonst die gerade gepumpte."""
    return getattr(_FADEN, "netz", None) or _Spieler.aktiv


@pytest.fixture
def zwei_spieler(relay, aufraeumen, monkeypatch):
    monkeypatch.setattr(session, "get", _netz_der_aufrufenden_seite)
    monkeypatch.setattr(session, "set_lobby_page", lambda page: None)
    monkeypatch.setattr(threading, "Thread", _ErbenderFaden)

    host = _Spieler(True, relay.port)
    _Spieler.aktiv = host.netz
    host.netz.send_tcp({"type": "HOST", "name": "Philip", "version": VERSION})
    host.pumpen(0.5)
    assert host.seite._lobby_id, "Host hat keine Lobby bekommen"

    gast = _Spieler(False, relay.port)
    _Spieler.aktiv = gast.netz
    gast.netz.send_tcp({"type": "JOIN", "name": "philip2",
                        "lobby_id": host.seite._lobby_id, "version": VERSION})
    _pumpen(host, gast)
    assert len(host.seite._players) == 2, "Gast ist nicht angekommen"

    yield host, gast

    host.trennen()
    gast.trennen()


def _strecke_anlegen(pfad: str, name: str) -> None:
    """Kleine, gültige Strecke — der Streckenlader muss sie lesen können."""
    punkte = [{"x": 500.0 + 300.0 * (i % 4), "y": 500.0 + 200.0 * (i // 4)}
              for i in range(12)]
    daten = {
        "name": name, "difficulty": "Einfach", "track_width": 220.0,
        "centerline": punkte,
        "waypoints": [{"x": p["x"], "y": p["y"], "is_checkpoint": i % 3 == 0}
                      for i, p in enumerate(punkte)],
    }
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(daten, fh)


# ── Der Ablauf aus dem Plan ─────────────────────────────────────────────────

def test_vorschlag_wandert_vom_gast_zum_host(zwei_spieler, tmp_path):
    host, gast = zwei_spieler

    # 1. Gastgeber schaltet Vorschläge frei
    host.seite._selected_mode = "Grand Prix"
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)
    assert gast.seite._gp_view.get("offers_enabled") is True, (
        "Gast erfährt nichts von der Freischaltung")

    # 2. Gast legt eine eigene Strecke in die Lobby
    eigene = str(tmp_path / "data" / "tracks" / "custom" / "Hausstrecke.json")
    _strecke_anlegen(eigene, "Hausstrecke")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(eigene)
    _pumpen(host, gast, sekunden=1.5)

    # 3. Beide sehen sie in der Liste
    assert len(host.seite._offers) == 1, f"Host sieht {host.seite._offers}"
    eintrag = host.seite._offers[0]
    assert eintrag["name"] == "Hausstrecke.json"
    assert eintrag["from"] == "philip2"
    assert eintrag["size"] > 0
    assert len(gast.seite._offers) == 1, "der Anbieter sieht seinen eigenen nicht"

    # 4. Gastgeber lädt herunter — bewusster Klick, nichts kommt ungefragt
    _Spieler.aktiv = host.netz
    host.netz.request_offer(eintrag["slot"])
    _pumpen(host, gast, sekunden=1.5)

    ziel = tmp_path / "data" / "tracks" / "custom" / "Hausstrecke.json"
    assert ziel.is_file(), f"nicht gespeichert (msg={host.seite._msg!r})"
    assert json.loads(ziel.read_text(encoding="utf-8"))["name"] == "Hausstrecke"


def test_host_faehrt_ein_rennen_mit_der_geschenkten_strecke(zwei_spieler, tmp_path):
    """Der eigentliche Beweis: die empfangene Datei ist fahrbar."""
    host, gast = zwei_spieler
    host.seite._selected_mode = "Grand Prix"
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)

    eigene = str(tmp_path / "data" / "tracks" / "custom" / "Gastspur.json")
    _strecke_anlegen(eigene, "Gastspur")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(eigene)
    _pumpen(host, gast, sekunden=1.5)
    assert host.seite._offers, "kein Vorschlag angekommen"

    _Spieler.aktiv = host.netz
    host.netz.request_offer(host.seite._offers[0]["slot"])
    _pumpen(host, gast, sekunden=1.5)

    empfangen = tmp_path / "data" / "tracks" / "custom" / "Gastspur.json"
    assert empfangen.is_file()

    # Der Host wählt sie wie jede eigene Strecke und startet
    host.seite._selected_track_path = str(empfangen)
    for p in host.seite._players:
        p["lobby_ready"] = True
    grand_prix.start_series(3, 3)
    # Der Upload läuft im Hintergrund und erbt die gerade aktive Verbindung —
    # ohne diese Zeile lädt der Host über die Leitung des Gastes hoch, und der
    # Server verwirft einen START_REQUEST, der nicht vom Gastgeber kommt.
    _Spieler.aktiv = host.netz
    host.seite._request_start()
    _pumpen(host, gast, sekunden=3.0)

    assert [w[0] for w in host.shell.wechsel] == ["race"], (
        f"Host startet nicht (msg={host.seite._msg!r})")
    assert [w[0] for w in gast.shell.wechsel] == ["race"], (
        f"Gast kommt nicht mit (msg={gast.seite._msg!r})")
    gefahren = host.shell.wechsel[0][1]["track_path"]
    assert "Gastspur" in gefahren


# ── Regeln aus dem Plan ─────────────────────────────────────────────────────

def test_ohne_freischaltung_kein_vorschlag(zwei_spieler, tmp_path):
    """Standardmäßig aus — niemand legt ungefragt Dateien in fremde Runden."""
    host, gast = zwei_spieler
    _Spieler.aktiv = host.netz
    host.seite._push_settings()          # offers_enabled bleibt False
    _pumpen(host, gast)

    eigene = str(tmp_path / "data" / "tracks" / "custom" / "Abgelehnt.json")
    _strecke_anlegen(eigene, "Abgelehnt")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(eigene)
    _pumpen(host, gast, sekunden=1.2)

    assert host.seite._offers == []
    assert "ausgeschaltet" in gast.seite._msg


def test_neuer_vorschlag_ersetzt_den_eigenen_alten(zwei_spieler, tmp_path):
    host, gast = zwei_spieler
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)

    for name in ("Erste", "Zweite"):
        pfad = str(tmp_path / "data" / "tracks" / "custom" / f"{name}.json")
        _strecke_anlegen(pfad, name)
        _Spieler.aktiv = gast.netz
        gast.seite._offer_upload(pfad)
        _pumpen(host, gast, sekunden=1.2)

    assert len(host.seite._offers) == 1, "beide Vorschläge liegen in der Lobby"
    assert host.seite._offers[0]["name"] == "Zweite.json"


def test_spaeter_beitretende_bekommen_die_liste(zwei_spieler, tmp_path, relay):
    """Der Relay hält die Vorschläge für die Lebensdauer der Lobby vor."""
    host, gast = zwei_spieler
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)

    pfad = str(tmp_path / "data" / "tracks" / "custom" / "Frueh.json")
    _strecke_anlegen(pfad, "Frueh")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(pfad)
    _pumpen(host, gast, sekunden=1.2)
    assert host.seite._offers

    dritter = _Spieler(False, relay.port)
    try:
        _Spieler.aktiv = dritter.netz
        dritter.netz.send_tcp({"type": "JOIN", "name": "dritter",
                               "lobby_id": host.seite._lobby_id, "version": VERSION})
        _pumpen(host, gast, dritter, sekunden=1.2)
        assert len(dritter.seite._offers) == 1, "Nachzügler sieht nichts"
        assert dritter.seite._offers[0]["name"] == "Frueh.json"
    finally:
        dritter.trennen()


def test_wiedereinsteiger_landet_in_der_uebersicht(zwei_spieler, relay):
    """Läuft eine Serie, gehört ein Gast in die Übersicht — nicht in die Lobby.

    Beim Wiedereinstieg verteilt der Gastgeber gerade nichts Neues; der Gast
    muss sich also allein aus dem Zustand zurechtfinden, den der Relay noch
    gespeichert hat.
    """
    host, gast = zwei_spieler
    host.seite._selected_mode = "Grand Prix"
    grand_prix.start_series(3, 3)
    _Spieler.aktiv = host.netz
    host.seite._enter_gp_overview()          # Host führt die Serie
    _pumpen(host, gast, sekunden=1.0)
    assert gast.seite._view == olp._GP_OVERVIEW

    gast.trennen()
    _pumpen(host, sekunden=0.5)

    zurueck = _Spieler(False, relay.port)
    try:
        _Spieler.aktiv = zurueck.netz
        zurueck.netz.send_tcp({"type": "JOIN", "name": "philip2",
                               "lobby_id": host.seite._lobby_id, "version": VERSION})
        _pumpen(host, zurueck, sekunden=1.2)
        assert zurueck.seite._view == olp._GP_OVERVIEW, (
            f"landet in {zurueck.seite._view!r} statt in der Übersicht")
    finally:
        zurueck.trennen()


def test_gast_in_der_lobby_erfaehrt_vom_ende_der_serie(zwei_spieler):
    """Der Gast sieht die Übersicht gerade nicht — ohne Meldung fiele ihm gar
    nichts auf."""
    host, gast = zwei_spieler
    host.seite._selected_mode = "Grand Prix"
    grand_prix.start_series(3, 3)
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast, sekunden=0.8)

    # Gast sitzt in der Lobby, nicht in der Übersicht
    gast.seite._view = olp._LOBBY
    _Spieler.aktiv = host.netz
    grand_prix.cancel()
    host.seite._push_settings()
    _pumpen(host, gast, sekunden=0.8)

    assert "beendet" in gast.seite._msg


def test_gleicher_name_ueberschreibt_nichts(zwei_spieler, tmp_path):
    """Eine geschenkte Strecke darf nichts Eigenes verdrängen."""
    host, gast = zwei_spieler
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)

    # Der Host hat bereits eine eigene Strecke dieses Namens
    meine = tmp_path / "data" / "tracks" / "custom" / "Kollision.json"
    _strecke_anlegen(str(meine), "Meine eigene")

    fremde = str(tmp_path / "fremd" / "Kollision.json")
    _strecke_anlegen(fremde, "Die vom Gast")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(fremde)
    _pumpen(host, gast, sekunden=1.2)

    _Spieler.aktiv = host.netz
    host.netz.request_offer(host.seite._offers[0]["slot"])
    _pumpen(host, gast, sekunden=1.5)

    assert json.loads(meine.read_text(encoding="utf-8"))["name"] == "Meine eigene", (
        "die eigene Strecke wurde überschrieben")
    zweite = tmp_path / "data" / "tracks" / "custom" / "Kollision (2).json"
    assert zweite.is_file(), list((tmp_path / "data" / "tracks" / "custom").iterdir())
    assert json.loads(zweite.read_text(encoding="utf-8"))["name"] == "Die vom Gast"


# ── Der Schalter zog in die Übersicht um (05.08.2026) ───────────────────────
# „Die Einstellung Track suggestions für den Host in der Lobby soll nicht mehr
#  in der Lobby einstellbar sein sondern in der Grand Prix Übersicht also „eine
#  Seite später" so das der Host auch während der Rennserie umschalten kann.
#  Schon hochgeladene Strecken werden dann aus dem Zwischenspeicher gelöscht und
#  müssten neu hochgeladen werden wenn der Host die Strecken suggestions wieder
#  aktiviert."

def test_der_schalter_steht_nicht_mehr_in_der_lobbyspalte():
    """Er war dort vor dem Serienstart einmalig zu entscheiden."""
    seite = olp.OnlineLobbyPage()
    assert not hasattr(seite, "_offers_stepper")


def _mit_vorschlag(host, gast, tmp_path, name="Hausstrecke"):
    host.seite._selected_mode = "Grand Prix"
    host.seite._offers_enabled = True
    _Spieler.aktiv = host.netz
    host.seite._push_settings()
    _pumpen(host, gast)

    eigene = str(tmp_path / "data" / "tracks" / "custom" / f"{name}.json")
    _strecke_anlegen(eigene, name)
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(eigene)
    _pumpen(host, gast, sekunden=1.5)
    assert len(host.seite._offers) == 1, "Vorbedingung: ein Vorschlag liegt da"


def test_ausschalten_leert_den_zwischenspeicher(zwei_spieler, tmp_path):
    """Beim Host sofort, beim Gast über den Relay — und beim Relay wirklich."""
    host, gast = zwei_spieler
    _mit_vorschlag(host, gast, tmp_path)

    _Spieler.aktiv = host.netz
    host.seite._offers_umschalten()
    _pumpen(host, gast, sekunden=1.0)

    assert host.seite._offers_enabled is False
    assert host.seite._offers == [], "der Host zeigt noch etwas an"
    assert gast.seite._offers == [], "der Gast zeigt noch etwas an"


def test_wieder_einschalten_bringt_nichts_zurueck(zwei_spieler, tmp_path):
    """Der eigentliche Punkt: „müssten neu hochgeladen werden".

    Eine Liste, die unsichtbar weiterlebt und beim Wiedereinschalten
    zurückkommt, wäre eine Überraschung — und der Relay trüge sie bis zum Ende
    der Lobby mit.
    """
    host, gast = zwei_spieler
    _mit_vorschlag(host, gast, tmp_path)

    _Spieler.aktiv = host.netz
    host.seite._offers_umschalten()          # aus
    _pumpen(host, gast, sekunden=1.0)
    _Spieler.aktiv = host.netz
    host.seite._offers_umschalten()          # wieder an
    _pumpen(host, gast, sekunden=1.0)

    assert host.seite._offers_enabled is True
    assert host.seite._offers == [], "der Relay hat die alte Liste aufgehoben"
    assert gast.seite._offers == []


def test_nach_dem_wiedereinschalten_geht_hochladen_erneut(zwei_spieler, tmp_path):
    """Ausgeschaltet heißt nicht kaputt: derselbe Weg muss wieder funktionieren."""
    host, gast = zwei_spieler
    _mit_vorschlag(host, gast, tmp_path)

    _Spieler.aktiv = host.netz
    host.seite._offers_umschalten()
    _pumpen(host, gast, sekunden=1.0)
    _Spieler.aktiv = host.netz
    host.seite._offers_umschalten()
    _pumpen(host, gast, sekunden=1.0)

    zweite = str(tmp_path / "data" / "tracks" / "custom" / "Zweite.json")
    _strecke_anlegen(zweite, "Zweite")
    _Spieler.aktiv = gast.netz
    gast.seite._offer_upload(zweite)
    _pumpen(host, gast, sekunden=1.5)

    assert [e["name"] for e in host.seite._offers] == ["Zweite.json"]


def test_der_gast_kann_den_schalter_nicht_umlegen(zwei_spieler, tmp_path):
    """Er gehört dem Gastgeber — die Übersicht zeigt ihn dem Gast gar nicht."""
    host, gast = zwei_spieler
    _mit_vorschlag(host, gast, tmp_path)

    aktionen = [getattr(w, "action", None) for w in gast.seite._offer_widgets()]
    assert "toggle_offers" not in aktionen
