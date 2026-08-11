"""D7 — die Lackierung reist bis zum Mitspieler (Releaseplan §5, Schritt 11).

Bis zum 05.08.2026 sah man online **jeden** im Werkslack. Die Werkstatt war
gebaut, die Lackierung stand im Profil, im Einzelrennen und im Splitscreen wurde
sie gezeichnet — nur über das Netz reiste sie nicht. Damit war der sichtbarste
Teil von Block D genau dort unsichtbar, wo ihn andere sehen sollen.

**Warum nicht über UDP.** Der Positionsstrom trägt je Fahrzeug 26 feste Bytes
(``id vtype x y angle vx vy omega``) und geht dreißigmal in der Sekunde
hinaus — eine Lackkennung gehört dort nicht hinein, sie ändert sich nie während
eines Rennens. Sie reist deshalb einmal über TCP:

    Werkstatt → Profil → ``PICK`` → ``settings["picks"]`` → ``LOBBY_STATE``
    → ``online_players`` → ``RemoteVehicle``

Der Relay bleibt dabei der dumme Relay: er reicht die Kennung durch, ohne zu
wissen, was eine Lackierung ist.

Geprüft wird die **ganze Kette**, nicht ihre Glieder: an jedem Übergang war schon
einmal ein Feldname nur auf einer Seite richtig, und genau das fällt bei
Einzelprüfungen nicht auf.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
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
import pymunk  # noqa: E402

import server as srv  # noqa: E402

from src.core import lack, profile, race_setup  # noqa: E402
from src.core.version import VERSION  # noqa: E402

_LEN = struct.Struct("!I")


# ── Ein echter Relay, wie in den anderen Netztests ──────────────────────────
#: Gemeinsame Fassung, siehe tests/relaishilfe.py — sie faehrt sauber
#: herunter, statt den Ereignisfaden mitten in offenen Verbindungen
#: anzuhalten (06.08.2026).
_Relay = relaishilfe.Relay


class _Draht:
    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self.sock.settimeout(5.0)

    def senden(self, msg: dict) -> None:
        rumpf = json.dumps(msg).encode()
        self.sock.sendall(_LEN.pack(len(rumpf)) + rumpf)

    def empfangen(self, zeit: float = 5.0) -> dict | None:
        self.sock.settimeout(zeit)
        try:
            kopf = self._genau(4)
            (n,) = _LEN.unpack(kopf)
            return json.loads(self._genau(n))
        except (OSError, ValueError, struct.error):
            return None

    def warten_auf(self, typ: str, zeit: float = 5.0, pruefung=None) -> dict | None:
        """Auf eine Nachricht warten — bei ``LOBBY_STATE`` mit *pruefung*.

        Ohne die Bedingung fängt man die falsche ab: der Gastgeber bekommt schon
        beim Beitritt des Gastes einen Lobbyzustand, und der ist älter als das
        ``PICK``, auf das es hier ankommt.
        """
        ende = time.monotonic() + zeit
        while time.monotonic() < ende:
            msg = self.empfangen(max(0.2, ende - time.monotonic()))
            if msg is None:
                return None
            if msg.get("type") == typ and (pruefung is None or pruefung(msg)):
                return msg
        return None

    def _genau(self, n: int) -> bytes:
        aus = b""
        while len(aus) < n:
            teil = self.sock.recv(n - len(aus))
            if not teil:
                raise OSError("zu")
            aus += teil
        return aus

    def zu(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def relay():
    srv._registry = srv._Registry()
    srv._wache = srv._Wache()
    r = _Relay()
    r.start()
    yield r
    r.stop()


@pytest.fixture
def spielstand(monkeypatch):
    p = profile.Profile(username="Philip")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


# ---------------------------------------------------------------------------
# Der Relay reicht die Kennung durch
# ---------------------------------------------------------------------------
def test_der_relay_traegt_die_lackierung_an_alle(relay):
    """Zwei Zeilen im Relay — hier sind sie."""
    wirt = _Draht(relay.port)
    gast = _Draht(relay.port)
    try:
        wirt.senden({"type": "HOST", "name": "Wirt", "version": VERSION})
        ok = wirt.warten_auf("JOIN_OK")
        gast.senden({"type": "JOIN", "lobby_id": ok["lobby_id"], "name": "Gast",
                     "version": VERSION})
        assert gast.warten_auf("JOIN_OK")

        gast.senden({"type": "PICK", "vehicle": "supercar",
                     "paint": "metallic:kobaltblau"})
        zustand = wirt.warten_auf(
            "LOBBY_STATE",
            pruefung=lambda m: any(p.get("vehicle") for p in m["players"]))
        assert zustand is not None
        eintrag = next(p for p in zustand["players"] if p["name"] == "Gast")
        assert eintrag["vehicle"] == "supercar"
        assert eintrag["paint"] == "metallic:kobaltblau"
    finally:
        wirt.zu(), gast.zu()


def test_ohne_angabe_bleibt_es_beim_werkslack(relay):
    """Ein Client ohne das Feld — ein alter Build, ein fremder Client — darf
    nichts kaputtmachen; er faehrt Werkslack wie vorher."""
    wirt = _Draht(relay.port)
    try:
        wirt.senden({"type": "HOST", "name": "Wirt", "version": VERSION})
        ok = wirt.warten_auf("JOIN_OK")
        wirt.senden({"type": "PICK", "vehicle": "rookie"})
        zustand = wirt.warten_auf(
            "LOBBY_STATE",
            pruefung=lambda m: any(p.get("vehicle") for p in m["players"]))
        assert zustand is not None
        eintrag = zustand["players"][0]
        assert eintrag["paint"] == ""
        assert lack.normalisiere(eintrag["paint"]) == lack.WERK
    finally:
        wirt.zu()


def test_eine_erfundene_kennung_wird_gekappt_und_faellt_auf_werkslack(relay):
    """Der Relay prüft die Kennung nicht — er soll der dumme Relay bleiben. Also
    muss die **Anzeige** damit umgehen: was nicht in der Palette steht, ist
    Werkslack."""
    wirt = _Draht(relay.port)
    try:
        wirt.senden({"type": "HOST", "name": "Wirt", "version": VERSION})
        wirt.warten_auf("JOIN_OK")
        wirt.senden({"type": "PICK", "vehicle": "rookie", "paint": "x" * 500})
        zustand = wirt.warten_auf(
            "LOBBY_STATE",
            pruefung=lambda m: any(p.get("paint") for p in m["players"]))
        assert zustand is not None
        roh = zustand["players"][0]["paint"]
        assert len(roh) <= 64, "der Relay muss die Länge deckeln"
        assert lack.normalisiere(roh) == lack.WERK
    finally:
        wirt.zu()


# ---------------------------------------------------------------------------
# Der Client schickt, was im Profil steht
# ---------------------------------------------------------------------------
def test_der_client_schickt_die_lackierung_des_gewaehlten_fahrzeugs(spielstand,
                                                                    monkeypatch):
    from src.states.menu import online_lobby_page as olp
    profile.current().set_paint("supercar", "neon:magenta")
    profile.current().set_paint("rookie", "metallic:rubinrot")

    gesendet = []
    from src.net import session
    monkeypatch.setattr(session, "get", lambda: types.SimpleNamespace(
        send_tcp=lambda m: gesendet.append(m)))

    seite = olp.OnlineLobbyPage.__new__(olp.OnlineLobbyPage)
    seite._selected_vehicle = "supercar"
    seite._push_pick()
    assert gesendet == [{"type": "PICK", "vehicle": "supercar",
                         "paint": "neon:magenta"}]

    gesendet.clear()
    seite._selected_vehicle = "rookie"
    seite._push_pick()
    assert gesendet[0]["paint"] == "metallic:rubinrot", \
        "die Lackierung gilt je Fahrzeug, nicht je Profil"


def test_ein_fahrzeug_ohne_lackierung_meldet_werkslack(spielstand, monkeypatch):
    from src.states.menu import online_lobby_page as olp
    gesendet = []
    from src.net import session
    monkeypatch.setattr(session, "get", lambda: types.SimpleNamespace(
        send_tcp=lambda m: gesendet.append(m)))
    seite = olp.OnlineLobbyPage.__new__(olp.OnlineLobbyPage)
    seite._selected_vehicle = "drifter"
    seite._push_pick()
    assert gesendet[0]["paint"] == lack.WERK


# ---------------------------------------------------------------------------
# Im Rennen: das Abbild trägt sie
# ---------------------------------------------------------------------------
def _rennen_geruest(online_players: dict):
    from src.states.race_state import RaceState
    r = RaceState.__new__(RaceState)
    race_setup.current().online_players = dict(online_players)
    return r


@pytest.mark.parametrize("kennung,erwartet", [
    ("metallic:rubinrot", "metallic:rubinrot"),
    ("neon:kobaltblau", "neon:kobaltblau"),
    ("", lack.WERK),
    ("werk", lack.WERK),
    ("gibtsnicht:blau", lack.WERK),
    ("metallic:gibtsnicht", lack.WERK),
])
def test_das_abbild_bekommt_die_gemeldete_lackierung(kennung, erwartet):
    r = _rennen_geruest({3: {"name": "Gast", "team": "A", "paint": kennung}})
    assert r._lack_fuer(3, 1) == erwartet


def test_die_lackierung_des_gastgebers_geht_nicht_an_seine_ki():
    """Über einen Slot streamt der Gastgeber sein eigenes Auto (``id == 1``)
    **und** seine KI. Nur das erste ist ein Mitspieler mit Werkstatt.

    Seit dem 06.08.2026 fährt die KI Werkslack (siehe ``lack.ki_lack``). Der
    Punkt dieses Tests bleibt derselbe und ist der eigentlich wichtige: die
    Lackierung des Gastgebers darf **nicht** auf seine KI-Autos durchschlagen.
    Täte sie es, führe online ein ganzes Feld im Lack eines Spielers.
    """
    r = _rennen_geruest({0: {"name": "Wirt", "team": "A",
                             "paint": "metallic:rubinrot"}})
    assert r._lack_fuer(0, 1) == "metallic:rubinrot"
    for ki_id in (2, 3, 4, 5, 6):
        assert r._lack_fuer(0, ki_id) == lack.WERK


def test_ein_unbekannter_slot_stuerzt_nicht_ab():
    """Ein Paket kann vor dem Lobbyzustand da sein — dann ist der Slot noch
    unbekannt, und ein Absturz mitten im Rennen wäre die schlechteste Antwort."""
    r = _rennen_geruest({})
    assert r._lack_fuer(9, 1) == lack.WERK


def test_das_abbild_zeichnet_mit_der_lackierung():
    """Bis ins Sprite: der Renderer muss die Kennung wirklich bekommen."""
    from src.entities.remote_vehicle import RemoteVehicle
    raum = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=1, space=raum,
                       config_key="rookie", lack="metallic:rubinrot")
    try:
        assert rv.lack == "metallic:rubinrot"
        assert rv._renderer.lack == "metallic:rubinrot"
        assert rv._renderer.config_key == "rookie"
    finally:
        rv.cleanup(raum)


def test_ein_abbild_ohne_angabe_sieht_aus_wie_vorher():
    from src.entities.remote_vehicle import RemoteVehicle
    raum = pymunk.Space()
    rv = RemoteVehicle(vehicle_id=1, sender_slot=1, space=raum)
    try:
        assert rv.lack == lack.WERK
        assert rv._renderer.lack == lack.WERK
    finally:
        rv.cleanup(raum)


def test_zwei_lackierungen_ergeben_verschiedene_bilder():
    """Sonst reist die Kennung zwar, ändert aber nichts — und niemand merkt es."""
    from src.core import version
    werk = lack.sprite("rookie", "rookie", lack.WERK, lack.BREITE_SPIEL)
    rot = lack.sprite("rookie", "rookie", "metallic:rubinrot", lack.BREITE_SPIEL)
    blau = lack.sprite("rookie", "rookie", "metallic:kobaltblau", lack.BREITE_SPIEL)
    if werk is None:
        pytest.skip("Sprite nicht ladbar")
    if not lack.lackierbar("rookie"):
        pytest.skip("für dieses Fahrzeug ist kein Lack abgestimmt")
    assert rot is not werk and blau is not werk
    assert pygame.image.tostring(rot, "RGBA") != pygame.image.tostring(blau, "RGBA")


# ---------------------------------------------------------------------------
# Die Kette als Ganzes
# ---------------------------------------------------------------------------
def test_von_der_werkstatt_bis_zum_abbild(relay, spielstand):
    """Der eigentliche Nachweis: Profil setzen, über einen echten Relay
    schicken, im Lobbyzustand ankommen, und daraus das Abbild bauen."""
    profile.current().set_paint("supercar", "zweifarbig:sonnengelb")

    wirt = _Draht(relay.port)
    gast = _Draht(relay.port)
    try:
        wirt.senden({"type": "HOST", "name": "Wirt", "version": VERSION})
        ok = wirt.warten_auf("JOIN_OK")
        gast.senden({"type": "JOIN", "lobby_id": ok["lobby_id"], "name": "Gast",
                     "version": VERSION})
        assert gast.warten_auf("JOIN_OK")

        # Was der Client schickt, kommt aus dem Profil.
        gast.senden({"type": "PICK", "vehicle": "supercar",
                     "paint": lack.normalisiere(
                         profile.current().paint("supercar"))})
        zustand = wirt.warten_auf(
            "LOBBY_STATE",
            pruefung=lambda m: any(p.get("paint") for p in m["players"]))
        assert zustand is not None, "der Lobbyzustand mit der Lackierung kam nie"
        gast_eintrag = next(p for p in zustand["players"] if p["name"] == "Gast")

        # Und was der Wirt daraus macht: derselbe Aufbau wie in der Lobbyseite.
        race_setup.current().online_players = {
            p["slot"]: {"name": p.get("name", ""), "team": p.get("team", "A"),
                        "paint": str(p.get("paint", "") or "")}
            for p in zustand["players"]
        }
        from src.states.race_state import RaceState
        r = RaceState.__new__(RaceState)
        assert r._lack_fuer(gast_eintrag["slot"], 1) == "zweifarbig:sonnengelb"
    finally:
        wirt.zu(), gast.zu()


def test_das_feld_steht_in_der_erlaubnisliste_des_relays():
    """``picks`` muss durch die Schlüsselprüfung aus Block H (H2.4) kommen —
    sonst wirft der Relay die Lackierung still weg."""
    assert "picks" in srv.SETTINGS_KEYS
