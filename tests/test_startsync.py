"""Gleichzeitiger Start im Online-Rennen: GO kommt auf allen Rechnern zur selben Zeit.

Ursache der Verschiebung war, dass jeder Client den Countdown erst beim Abholen
von RACE_GO (je Rechner ein anderer Bildtakt) startete, die Laufzeit der
Meldung nicht abzog und die 3,5 s aus gedeckelten Bildzeiten summierte. Jetzt
rechnet jeder vom Eintreffen der Meldung (Empfangsthread) abzueglich seiner
einfachen Laufzeit und zaehlt an der Uhr.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from src.net.client import NetworkClient
from src.states.race_manager import RaceManager

from tests.strecken_hilfe import srv


class _Uhr:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _manager(uhr: _Uhr) -> RaceManager:
    rm = RaceManager([], types.SimpleNamespace(waypoints=[]), hold_countdown=True)
    rm._uhr = uhr
    return rm


def _simuliere(latenz_s: float, fps: float, uhr: _Uhr, t_senden: float,
               countdown_s: float = 3.5, ende: float = 6.0) -> float:
    """Ein Client: RACE_GO trifft bei t_senden + latenz ein, wird im naechsten
    Bild abgeholt; gibt die Uhrzeit zurueck, zu der er auf Gruen schaltet."""
    rm = _manager(uhr)
    ankunft = t_senden + latenz_s
    dt = min(0.1, 1.0 / fps)          # wie im Spiel: Bildzeit gedeckelt
    uhr.t = t_senden - 0.2
    abgeholt = False
    while uhr.t < t_senden + ende:
        uhr.t += 1.0 / fps
        if not abgeholt and uhr.t >= ankunft:
            rm.release_countdown(countdown_s, ankunft=ankunft, latenz_s=latenz_s)
            abgeholt = True
        rm.update(dt)
        if rm.state == "racing":
            return uhr.t
    raise AssertionError("nie gestartet")


def test_zwei_clients_verschiedene_latenz_und_bildrate():
    uhr = _Uhr()
    t0 = 1000.0
    host = _simuliere(0.005, 144.0, uhr, t0)      # Host im selben Netz, schnell
    gast = _simuliere(0.140, 30.0, uhr, t0)       # Gast weit weg, langsamer Rechner
    assert abs(host - gast) < 0.05
    # beide liegen bei Absendezeit + 3,5 s (hoechstens ein Bild spaeter)
    assert 0.0 <= host - (t0 + 3.5) <= 1 / 144 + 1e-6
    assert 0.0 <= gast - (t0 + 3.5) <= 1 / 30 + 1e-6


def test_gleiche_latenz_gleiche_zeit_trotz_bildrate():
    uhr = _Uhr()
    a = _simuliere(0.04, 144.0, uhr, 1000.0)
    b = _simuliere(0.04, 30.0, uhr, 1000.0)
    c = _simuliere(0.04, 10.0, uhr, 1000.0)       # unter dem dt-Deckel von 0,1 s
    assert abs(a - b) < 0.04
    assert abs(c - a) < 0.11                      # nur die eigene Bildlaenge


def test_spaetes_abholen_verschiebt_go_nicht():
    """Ein Ruckler, der RACE_GO erst 400 ms nach dem Eintreffen abholt, darf
    GO nicht um 400 ms schieben."""
    uhr = _Uhr()
    rm = _manager(uhr)
    ankunft = 1000.05
    uhr.t = 1000.45                      # erst jetzt im Bild
    rm.release_countdown(3.5, ankunft=ankunft, latenz_s=0.05)
    assert rm.countdown_timer == pytest.approx(3.5 - 0.05 - 0.40, abs=1e-6)
    uhr.t = 1003.5
    rm.update(0.1)
    assert rm.state == "racing"


def test_altes_verhalten_ohne_ankunft_unveraendert():
    rm = RaceManager([], types.SimpleNamespace(waypoints=[]), hold_countdown=True)
    rm.update(0.1)
    assert rm.state == "countdown" and rm.countdown_timer == 3.0   # gehalten
    rm.release_countdown(3.5)
    for _ in range(34):
        rm.update(0.1)
    assert rm.state == "countdown"
    rm.update(0.1)
    rm.update(0.1)
    assert rm.state == "racing"


def test_zeit_seit_go_zaehlt_zum_rennen():
    uhr = _Uhr()
    rm = _manager(uhr)
    uhr.t = 1000.0
    rm.release_countdown(3.5, ankunft=1000.0)
    uhr.t = 1003.6                       # ein Bild ueber GO hinaus
    rm.update(0.1)
    assert rm.state == "racing"
    assert rm.race_time == pytest.approx(0.1, abs=1e-6)


def test_laufzeit_schaetzung_nimmt_kleinste_umlaufzeit():
    nc = NetworkClient()
    assert nc.einfache_laufzeit_s == 0.0
    for ms in (180.0, 60.0, 95.0, 400.0):
        nc._ping_verlauf.append(ms)
    assert nc.einfache_laufzeit_s == pytest.approx(0.030)


def test_race_go_wird_im_empfangsthread_gestempelt():
    nc = NetworkClient()
    msg = {"type": "RACE_GO", "countdown_ms": 3500}
    nc._handle_tcp_msg(msg)
    assert isinstance(msg["_ankunft"], float)
    anderes = {"type": "START"}
    nc._handle_tcp_msg(anderes)
    assert "_ankunft" not in anderes


def test_server_sendet_countdown_ms(monkeypatch):
    gesendet = []

    async def _bc(lobby, msg):
        gesendet.append(msg)

    monkeypatch.setattr(srv, "_broadcast", _bc)
    lobby = types.SimpleNamespace(state="racing", loaded={0, 1},
                                  clients={0: object(), 1: object()}, lobby_id="ABCDEF")
    asyncio.run(srv._maybe_race_go(lobby))
    assert gesendet == [{"type": "RACE_GO", "countdown_ms": 3500}]
