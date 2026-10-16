"""Gegenwarts-Vorhersage ferner Fahrzeuge (1.1.0): gemeinsame Uhr, Paketformat,
Hochrechnung, weiches Nachfuehren, Rueckfall, Kollisions- und Ranglistenpfad.

Hintergrund: ferne Autos wurden per Snapshot-Interpolation in der Vergangenheit
gezeichnet (Laufzeit + 40-150 ms Puffer), bei 200 km/h 4-10 m hinter dem wahren
Ort; beide Spieler sahen sich selbst vorn. Jetzt kennt jedes Paket sein Alter
(Relayuhr, PING/PONG) und das Abbild steht in der Gegenwart.

Die Messung gegen die echte Fahrzeugphysik steht in ``tools/netz_messung.py``;
hier laufen die Zielwerte daraus als Test.
"""
from __future__ import annotations

import math
import os
import random
import struct
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import pymunk
import pytest

pygame.init()
pygame.display.set_mode((64, 64))

from src.entities import remote_vehicle as rvmod  # noqa: E402
from src.entities.remote_vehicle import RemoteVehicle  # noqa: E402
from src.entities.vehicle_factory import VehicleFactory  # noqa: E402
from src.net import protocol, vorhersage  # noqa: E402
from src.net.client import NetworkClient  # noqa: E402
from src.net.uhrsync import UhrSync  # noqa: E402

VehicleFactory.load_all_configs()

DT = 1.0 / 60.0
V = 700.0          # px/s, knapp 200 km/h
PX_JE_M = 12.5     # 1 / M_PER_PX


class _Uhr:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def uhr():
    u = _Uhr()
    alt = rvmod._clock
    rvmod._clock = u
    yield u
    rvmod._clock = alt


def _geist(**kw) -> RemoteVehicle:
    return RemoteVehicle(vehicle_id=1, sender_slot=1, space=pymunk.Space(),
                         config_key="supercar", **kw)


def _snap(x, y=0.0, vx=V, vy=0.0, angle=0.0, omega=0.0, **extra):
    d = {"x": x, "y": y, "vx": vx, "vy": vy, "angle": angle, "omega": omega,
         "lap": 1, "wp": 0}
    d.update(extra)
    return d


def _fahre_gerade(g, uhr, sekunden, alter=0.07, hz=50.0, start=0.0, ab=0.0):
    """Sender faehrt mit V geradeaus; jedes Paket kommt *alter* nach seinem Stand
    an und kennt dieses Alter. Gibt (Bild-Zeiten, gezeichnete x, wahres x) zurueck."""
    t = ab
    naechstes = ab
    ausgabe = []
    senden = []                   # (Ankunft, Sendezeit)
    while t < ab + sekunden:
        while naechstes <= t:
            senden.append((naechstes + alter, naechstes))
            naechstes += 1.0 / hz
        uhr.t = 1000.0 + t
        while senden and senden[0][0] <= t:
            an, sz = senden.pop(0)
            g.apply_snapshot(_snap(start + V * sz), send_time=5000.0 + sz,
                             arrival=1000.0 + an, alter=alter)
        g.update(DT)
        ausgabe.append((t, g._pos[0], start + V * t))
        t += DT
    return ausgabe


# ── Paketformat ────────────────────────────────────────────────────────────────

def _auto(i=1, **extra):
    d = {"id": i, "cfg": "supercar", "x": 100.5 * i, "y": -20.25, "angle": 0.5,
         "vx": 650.0, "vy": -10.0, "omega": 0.25, "lap": 2, "wp": 7}
    d.update(extra)
    return d


def test_paket_mit_eingaben_und_uhr_rundet_sich():
    roh = protocol.pack_state("ABCDEF", 3, [
        _auto(1, steer=-0.5, throttle=1.0, brake=0.0, handbrake=False),
        _auto(2, steer=1.0, throttle=-0.6, brake=0.8, handbrake=True),
    ], 123.5, clock_offset=-4321.125)
    p = protocol.unpack_state(roh)
    assert p["sender_slot"] == 3 and p["send_time"] == 123.5
    assert p["clock_offset"] == pytest.approx(-4321.125)
    a, b = p["vehicles"]
    assert a["steer"] == pytest.approx(-0.5, abs=0.01) and a["throttle"] == pytest.approx(1.0)
    assert a["brake"] == 0.0 and a["handbrake"] is False
    assert b["steer"] == pytest.approx(1.0) and b["throttle"] == pytest.approx(-0.6, abs=0.01)
    assert b["brake"] == pytest.approx(0.8, abs=0.005) and b["handbrake"] is True
    assert a["x"] == pytest.approx(100.5) and b["lap"] == 2 and b["wp"] == 7


def test_paketgroessen():
    n = protocol.STATE_HEADER.size + protocol.VEHICLE_FMT.size
    assert (protocol.STATE_HEADER.size, protocol.VEHICLE_FMT.size) == (17, 29)
    ohne = protocol.pack_state("ABCDEF", 1, [_auto()], 1.0)
    assert len(ohne) == n == 46                      # unveraendert
    mit = protocol.pack_state("ABCDEF", 1, [_auto(steer=0.0)], 1.0, clock_offset=5.0)
    assert len(mit) == 46 + 10 + 4 == 60
    sechs = protocol.pack_state("ABCDEF", 1, [_auto(i, steer=0.0) for i in range(6)], 1.0,
                                clock_offset=5.0)
    assert len(sechs) == 17 + 6 * 29 + 10 + 6 * 4 == 225


def test_altes_paket_ohne_anhang_bleibt_lesbar():
    p = protocol.unpack_state(protocol.pack_state("ABCDEF", 1, [_auto()], 9.0))
    assert p["clock_offset"] is None
    assert "steer" not in p["vehicles"][0]
    assert p["vehicles"][0]["vx"] == pytest.approx(650.0)


def test_anhang_stoert_einen_leser_des_praefix_nicht():
    """Ein Leser, der nach car_count Fahrzeugen aufhoert (Relay, 2D), sieht
    dieselben Fahrzeuge wie ohne Anhang."""
    kurz = protocol.pack_state("ABCDEF", 1, [_auto(1), _auto(2)], 9.0)
    lang = protocol.pack_state("ABCDEF", 1, [_auto(1, steer=1.0), _auto(2, steer=0.5)], 9.0,
                               clock_offset=1.0)
    assert lang.startswith(kurz)
    n = len(kurz)
    assert lang[:n] == kurz


def test_kaputter_anhang_wird_ignoriert():
    roh = protocol.pack_state("ABCDEF", 1, [_auto(steer=0.3)], 9.0, clock_offset=2.0)
    for kaputt in (roh[:-1], roh + b"\x00", roh[:46] + b"\x00" + roh[47:]):
        p = protocol.unpack_state(kaputt)
        assert p is not None and p["clock_offset"] is None
        assert "steer" not in p["vehicles"][0]
        assert p["vehicles"][0]["x"] == pytest.approx(100.5)


def test_nicht_abgeglichen_heisst_ohne_offset_aber_mit_eingaben():
    p = protocol.unpack_state(protocol.pack_state("ABCDEF", 1, [_auto(steer=0.5)], 9.0))
    assert p["clock_offset"] is None and p["vehicles"][0]["steer"] == pytest.approx(0.5, abs=0.01)


def test_eingaben_werden_begrenzt_und_unsinn_verdaut():
    roh = protocol.pack_state("ABCDEF", 1, [_auto(steer=7.0, throttle=float("nan"),
                                                  brake=-3.0)], 9.0)
    v = protocol.unpack_state(roh)["vehicles"][0]
    assert v["steer"] == pytest.approx(1.0) and v["throttle"] == 0.0 and v["brake"] == 0.0


def test_relay_schutz_liest_pakete_mit_anhang_wie_vorher():
    """Der Schutz im Relay arbeitet mit 29 Byte je Fahrzeug und liest nur car_count
    Fahrzeuge: Anhang aendert nichts, und ein vorhergesagtes Abbild gibt es dort nie."""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
    import schutz
    assert schutz._STATE_FAHRZEUG.size == protocol.VEHICLE_FMT.size
    s = schutz.LobbySchutz("H1AAAA", "2d", "")
    s.namen[1] = "Ben"
    s.rennen_neu({"laps": 3}, b"", "oval")
    s.go(0.0, 0.0)
    for i in range(80):
        t = i * 0.02
        daten = protocol.pack_state("H1AAAA", 1, [
            {"id": 1, "x": 700.0 * t, "y": 5.0, "angle": 0.0, "vx": 700.0, "vy": 0.0,
             "omega": 0.0, "cfg": "supercar", "lap": 1, "wp": 3,
             "steer": 0.0, "throttle": 1.0, "brake": 0.0, "handbrake": False}], t,
            clock_offset=12345.0)
        s.paket(1, daten, t)
    assert (1, 1) in s.stroeme and not s.punkte


def test_pong_mit_relayzeit_und_alter_pong():
    lang = struct.pack("!B d d", protocol.UDP_PONG, 12.5, 777.25)
    assert protocol.unpack_pong_ext(lang) == (12.5, 777.25)
    kurz = struct.pack("!B d", protocol.UDP_PONG, 12.5)
    assert protocol.unpack_pong_ext(kurz) == (12.5, None)
    assert protocol.unpack_pong_ext(b"\x03") is None
    assert protocol.unpack_pong(lang) == 12.5           # alter Leser: erste 9 Bytes
    assert protocol.PONG_EXT_FMT.size == 17


def test_relay_antwortet_auf_ping_mit_seiner_uhr():
    from tests.strecken_hilfe import srv
    gesendet = []

    class _Transport:
        def sendto(self, data, addr):
            gesendet.append((data, addr))

    relay = srv._UDPRelay()
    relay.transport = _Transport()
    ping = protocol.pack_ping("ABCDEF", 1, 42.25)
    vor = time.monotonic()
    relay.datagram_received(ping, ("127.0.0.1", 4000))
    nach = time.monotonic()
    (daten, adr), = gesendet
    assert adr == ("127.0.0.1", 4000) and len(daten) == 17
    ts, relay_zeit = protocol.unpack_pong_ext(daten)
    assert ts == 42.25 and vor <= relay_zeit <= nach
    assert protocol.unpack_pong(daten) == 42.25         # 2D-/Alt-Clients lesen das Praefix


# ── Uhrabgleich ────────────────────────────────────────────────────────────────

def _proben(sync, versatz, hin_ms, her_ms, jitter_ms, n, seed=1, t=100.0, schritt=0.5):
    """n PING/PONG-Runden gegen eine Relayuhr, die *versatz* vor der eigenen liegt."""
    rng = random.Random(seed)
    for _ in range(n):
        auf = (hin_ms + rng.expovariate(1.0 / jitter_ms) if jitter_ms else hin_ms) / 1000.0
        ab = (her_ms + rng.expovariate(1.0 / jitter_ms) if jitter_ms else her_ms) / 1000.0
        t0 = t
        server = t0 + auf + versatz
        t3 = t0 + auf + ab
        sync.probe(t0, t3, server)
        t += schritt
    return t


def test_uhr_findet_den_versatz_bei_symmetrischer_strecke():
    s = UhrSync()
    assert not s.gueltig and s.versatz is None
    _proben(s, 5000.0, 30, 30, 5, 12)
    assert s.gueltig
    assert s.versatz == pytest.approx(5000.0, abs=0.003)


def test_uhr_nimmt_die_kleinste_umlaufzeit():
    s = UhrSync()
    t = 100.0
    # ein Ausreisser mit 400 ms nur auf dem Hinweg (Fehler 200 ms), gute Proben drumherum
    for rtt_hin, rtt_her in [(30, 30), (430, 30), (30, 30), (32, 31), (30, 30), (31, 30)]:
        sync_t0 = t
        s.probe(sync_t0, sync_t0 + (rtt_hin + rtt_her) / 1000.0,
                sync_t0 + rtt_hin / 1000.0 + 77.0)
        t += 0.5
    assert s.versatz == pytest.approx(77.0, abs=0.003)


def test_uhr_springt_nicht_bei_jeder_neuen_probe():
    s = UhrSync()
    t = _proben(s, 10.0, 30, 30, 4, 30)
    vorher = s.versatz
    # eine einzige bessere Probe mit 2 ms Fehler darf den Versatz nur in kleinen Schritten ziehen
    s.probe(t, t + 0.058, t + 0.030 + 10.0 + 0.002)
    assert abs(s.versatz - vorher) < 0.001


def test_uhr_folgt_einem_sprung_der_gegenseite():
    s = UhrSync()
    t = _proben(s, 10.0, 30, 30, 2, 20)
    _proben(s, 400.0, 30, 30, 2, 30, t=t)               # Relay neu gestartet
    assert s.versatz == pytest.approx(400.0, abs=0.005)


def test_uhr_wirft_unsinn_weg():
    s = UhrSync()
    assert not s.probe(5.0, 4.0, 100.0)                 # Antwort vor der Frage
    assert not s.probe(5.0, 9.0, 100.0)                 # 4 s Umlauf
    assert not s.probe(5.0, 5.1, float("nan"))
    assert s.anzahl == 0


def test_alter_aus_beiden_abgleichen():
    nc = NetworkClient()
    assert nc.alter_von(100.0, 50.0, 1.0) is None       # eigener Abgleich fehlt
    _proben(nc._uhr, 20.0, 10, 10, 0, 5)
    assert nc.alter_von(100.0, 50.0, None) is None      # Absender nicht abgeglichen
    # Absender: Relay = Sender + 30; wir: Relay = eigene Uhr + 20
    # gesendet bei Senderzeit 50 -> Relay 80; angekommen bei 100 -> Relay 120 -> Alter 40
    assert nc.alter_von(100.0, 50.0, 30.0) == pytest.approx(40.0, abs=0.001)
    assert nc.alter_von(100.0, 0.0, 30.0) is None       # ohne Sendezeit unbrauchbar


# ── Hochrechnung ───────────────────────────────────────────────────────────────

class _L:
    def __init__(self, **kw):
        self.x = self.y = 0.0
        self.vx, self.vy = V, 0.0
        self.angle = self.omega = self.a_s = 0.0
        self.lenk = 0.0
        self.hand = False
        self.eing = False
        self.__dict__.update(kw)


def test_hochrechnung_gerade_und_beschleunigt():
    x, y, vx, vy, w, om = vorhersage.hochrechnen(_L(), 0.1)
    assert x == pytest.approx(V * 0.1, rel=1e-6) and abs(y) < 1e-9 and vx == pytest.approx(V)
    # bremst mit 400 px/s^2: nach 0,1 s etwas weniger Weg und Tempo
    x2, _, vx2, *_ = vorhersage.hochrechnen(_L(a_s=-400.0), 0.1)
    assert x2 < x and vx2 < V


def test_hochrechnung_bremsen_endet_im_stand_nicht_rueckwaerts():
    x, _, vx, *_ = vorhersage.hochrechnen(_L(vx=20.0, a_s=-500.0), 0.3)
    assert vx >= 0.0 and x >= 0.0


def test_hochrechnung_kreisbogen():
    r = 400.0
    w = V / r
    x, y, vx, vy, winkel, om = vorhersage.hochrechnen(_L(omega=w, angle=0.0, a_s=0.0), 0.2)
    # Kreisbahn um (0, r): Punkt nach 0,2 s
    assert x == pytest.approx(r * math.sin(w * 0.2), rel=0.01)
    assert y == pytest.approx(r * (1 - math.cos(w * 0.2)), rel=0.02)
    assert winkel == pytest.approx(w * 0.2, rel=1e-3)


def test_lenkeingabe_zieht_die_gierrate_vor():
    """Lenkt der Fahrer ein, dreht das Abbild schon, bevor die Gierrate da ist."""
    ohne = vorhersage.hochrechnen(_L(vx=350.0, eing=True, lenk=0.0), 0.15)
    mit = vorhersage.hochrechnen(_L(vx=350.0, eing=True, lenk=1.0), 0.15)
    assert abs(ohne[4]) < 1e-9 and mit[4] > 0.05
    # Handbremse: die Lenkung bestimmt die Drehung nicht
    hand = vorhersage.hochrechnen(_L(vx=350.0, eing=True, lenk=1.0, hand=True), 0.15)
    assert abs(hand[4]) < 1e-9
    # ohne mitgeschickte Eingaben (aelteres Paket) bleibt es bei der gemeldeten Gierrate
    alt = vorhersage.hochrechnen(_L(vx=350.0, eing=False, lenk=1.0), 0.15)
    assert abs(alt[4]) < 1e-9


def test_beschleunigungsschaetzung_wird_geglaettet_und_begrenzt():
    a = vorhersage.beschleunigung(700.0, 690.0, 0.02, None)          # -500 px/s^2
    assert a == pytest.approx(-vorhersage.A_MAX)
    a = vorhersage.beschleunigung(700.0, 0.0, 0.02, -100.0)          # Wand: Begrenzung
    assert a >= -vorhersage.A_MAX
    assert vorhersage.beschleunigung(700.0, 690.0, 1.0, 40.0) == pytest.approx(20.0)  # Luecke


# ── RemoteVehicle: Gegenwart ──────────────────────────────────────────────────

def test_abbild_steht_in_der_gegenwart(uhr):
    g = _geist()
    aus = _fahre_gerade(g, uhr, 3.0, alter=0.07)
    rest = [abs(x - w) / PX_JE_M for t, x, w in aus if t > 1.0]
    assert max(rest) < 0.1, f"{max(rest):.2f} m neben dem wahren Ort"
    assert g._w == 1.0


def test_ohne_alter_bleibt_es_bei_der_interpolation(uhr):
    g = _geist()
    t = 0.0
    for _ in range(180):
        if int(t / 0.02) != int((t - DT) / 0.02):
            g.apply_snapshot(_snap(V * t), send_time=5000.0 + t, arrival=1000.0 + t)
        uhr.t = 1000.0 + t
        g.update(DT)
        t += DT
    assert g._w == 0.0
    assert V * t - g._pos[0] > 0.5 * V * 0.04            # hinkt hinterher wie bisher


def test_umgebungsschalter_waehlt_die_interpolation(uhr, monkeypatch):
    monkeypatch.setenv("RACE_NETZ_MODUS", "interpolation")
    assert rvmod._modus_aus_umgebung() == rvmod.MODUS_INTERPOLATION
    monkeypatch.setenv("RACE_NETZ_MODUS", "vorhersage")
    assert rvmod._modus_aus_umgebung() == rvmod.MODUS_VORHERSAGE
    monkeypatch.delenv("RACE_NETZ_MODUS")
    assert rvmod._modus_aus_umgebung() == rvmod.MODUS_VORHERSAGE      # Vorgabe
    g = _geist()
    g.modus = rvmod.MODUS_INTERPOLATION
    aus = _fahre_gerade(g, uhr, 2.0, alter=0.07)
    assert g._w == 0.0
    assert max(abs(x - w) for t, x, w in aus if t > 1.0) / PX_JE_M > 2.0


def test_unplausibles_alter_zaehlt_nicht_und_blendet_weich_zurueck(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 1.5, alter=0.07)
    assert g._w == 1.0
    # Uhrabgleich kaputt: Alter 5 s (Relay neu gestartet o. ae.) -> zurueck zur Interpolation
    t = 1.5
    spruenge = []
    vor = g._pos[0]
    ende = t + 2.0
    while t < ende:
        uhr.t = 1000.0 + t
        if int(t / 0.02) != int((t - DT) / 0.02):
            g.apply_snapshot(_snap(V * (t - 0.07)), send_time=5000.0 + t - 0.07,
                             arrival=uhr.t, alter=5.0)
        g.update(DT)
        spruenge.append(g._pos[0] - vor)
        vor = g._pos[0]
        t += DT
    assert g._w == 0.0
    assert min(spruenge) > 0.0                           # nie rueckwaerts
    assert max(spruenge) < 1.6 * V * DT                  # und kein Satz


def test_ein_einzelnes_ungueltiges_paket_schaltet_nicht_um(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 1.0, alter=0.07)
    g.apply_snapshot(_snap(V * 0.99), send_time=5000.0 + 1.0, arrival=uhr.t, alter=None)
    g.update(DT)
    assert g._w == 1.0


def test_vorhersage_nie_rueckwaerts_bei_schwankendem_alter(uhr):
    g = _geist()
    rng = random.Random(3)
    t = 0.0
    naechstes = 0.0
    eingang = []
    vor = None
    zurueck = 0
    while t < 6.0:
        while naechstes <= t:
            alter = 0.06 + rng.expovariate(1.0 / 0.015)
            eingang.append((naechstes + alter, naechstes, alter))
            naechstes += 0.02
        uhr.t = 1000.0 + t
        eingang.sort()
        while eingang and eingang[0][0] <= t:
            an, sz, alter = eingang.pop(0)
            g.apply_snapshot(_snap(V * sz), send_time=5000.0 + sz, arrival=1000.0 + an, alter=alter)
        g.update(DT)
        if vor is not None and t > 1.0 and g._pos[0] - vor < -0.01:
            zurueck += 1
        vor = g._pos[0]
        t += DT
    assert zurueck == 0


def test_korrektur_wird_abgebaut_nicht_gesprungen(uhr):
    """Bremst der Gegner staerker als hochgerechnet, rutscht das Abbild nach vorn
    (es bremst mit), springt aber nicht zurueck."""
    g = _geist()
    _fahre_gerade(g, uhr, 1.5, alter=0.07)
    t = 1.5
    x_sender = V * t
    v = V
    vor = g._pos[0]
    schritte = []
    naechstes = t
    while t < 2.5:
        v = max(0.0, v - 900.0 * DT)          # Vollbremsung 72 m/s^2 (unrealistisch hart)
        x_sender += v * DT
        uhr.t = 1000.0 + t
        if t >= naechstes:
            naechstes += 0.02
            g.apply_snapshot(_snap(x_sender, vx=v), send_time=5000.0 + t, arrival=uhr.t + 0.07,
                             alter=0.07)
        g.update(DT)
        schritte.append(g._pos[0] - vor)
        vor = g._pos[0]
        t += DT
    # Im Stand darf der Rest eines Ueberschwingers mit dem Mindesttempo der
    # Korrektur (15 px/s) zurueckkriechen; ein Zurueckspringen waere ein Vielfaches.
    assert min(schritte) >= -rvmod.CORRECTION_MIN_SPEED * DT - 1e-6,         f"Abbild zurueckgesprungen: {min(schritte):.2f} px"
    assert min(schritte[:30]) >= 0.0               # solange er faehrt: nie rueckwaerts


def test_frist_ueberschritten_laeuft_das_abbild_aus(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 1.0, alter=0.07)
    x0 = g._pos[0]
    uhr.t += 5.0                         # der Gegner sendet nichts mehr
    for _ in range(300):
        uhr.t += DT
        g.update(DT)
    weg = (g._pos[0] - x0) / PX_JE_M
    assert 0.0 < weg < 45.0              # laeuft aus, faehrt nicht durch die Strecke
    letzte = g._pos[0]
    uhr.t += 1.0
    g.update(DT)
    assert g._pos[0] == pytest.approx(letzte, abs=1e-6)     # und steht


def test_reset_des_absenders_springt_nach_funkloch_wird_aufgeholt(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 1.0, alter=0.07)
    # Funkloch 0,6 s, danach faehrt der Absender ganz normal weiter
    t = 1.0
    uhr.t = 1000.0 + t
    for _ in range(36):
        t += DT
        uhr.t = 1000.0 + t
        g.update(DT)
    sender_x = V * (t - 0.07)
    g.apply_snapshot(_snap(sender_x), send_time=5000.0 + t - 0.07, arrival=uhr.t, alter=0.07)
    g.update(DT)
    # kein Satz ueber die ganze Luecke: die gezeigte Lage liegt noch zurueck ...
    assert g._pos[0] < sender_x + V * 0.07
    # ... und holt auf
    for _ in range(60):
        t += DT
        uhr.t = 1000.0 + t
        g.update(DT)
    # (kein weiteres Paket: der Auslauf bestimmt das Bild, nur die Fehlerabbau-Mechanik zaehlt)


def test_echter_sprung_des_absenders_wird_uebernommen(uhr):
    """Reset auf die Strecke: der Absender springt 200 m. Das Abbild auch."""
    g = _geist()
    _fahre_gerade(g, uhr, 1.5, alter=0.07)
    t = 1.5
    uhr.t = 1000.0 + t
    ziel_x = V * t + 200.0 * PX_JE_M
    g.apply_snapshot(_snap(ziel_x, vx=0.0), send_time=5000.0 + t, arrival=uhr.t, alter=0.0)
    g.update(DT)
    assert abs(g._pos[0] - ziel_x) < 5.0
    assert g._err_pos == (0.0, 0.0)


def test_kleiner_sprung_wird_nicht_als_reset_gedeutet(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 1.5, alter=0.07)
    t = 1.5
    uhr.t = 1000.0 + t
    # Rempler: der Absender wird um 3 m zur Seite gestossen
    g.apply_snapshot(_snap(V * (t - 0.07), y=3.0 * PX_JE_M), send_time=5000.0 + t - 0.07,
                     arrival=uhr.t, alter=0.07)
    g.update(DT)
    assert g._pos[1] < 3.0 * PX_JE_M * 0.6               # wird eingeblendet, nicht gesetzt


def test_kinematischer_koerper_folgt_der_vorhergesagten_lage(uhr):
    g = _geist()
    _fahre_gerade(g, uhr, 2.0, alter=0.07)
    assert g.body.position.x == pytest.approx(g._pos[0])
    assert g.body.velocity.x == pytest.approx(V, rel=0.02)
    # die Lage ist weit vor dem letzten Paket
    assert g._pos[0] - g._target_pos[0] > V * 0.05


def test_rangliste_und_fortschritt_bleiben_an_den_paketen(uhr):
    g = _geist()
    for i in range(30):
        uhr.t = 1000.0 + i * 0.02
        g.apply_snapshot(_snap(V * i * 0.02, lap=1, wp=0), send_time=5000.0 + i * 0.02,
                         arrival=uhr.t + 0.05, alter=0.05)
    s = _snap(V * 0.6)
    s["lap"], s["wp"] = 2, 5
    uhr.t = 1000.0 + 0.62
    g.apply_snapshot(s, send_time=5000.0 + 0.6, arrival=uhr.t, alter=0.05)
    assert (g.lap, g.wp) == (2, 5)
    assert g.progress(40) == 2 * 40 + 5
    # ein vertauschtes, aelteres Paket ueberschreibt den Fortschritt nicht
    alt = _snap(V * 0.3)
    alt["lap"], alt["wp"] = 1, 9
    g.apply_snapshot(alt, send_time=5000.0 + 0.3, arrival=uhr.t, alter=0.05)
    assert (g.lap, g.wp) == (2, 5)


def test_eingaben_werden_gelesen_und_aelteres_paket_kommt_ohne_aus(uhr):
    g = _geist()
    g.apply_snapshot(_snap(0.0, steer=0.5, throttle=1.0, brake=0.0, handbrake=False),
                     send_time=5000.0, arrival=1000.0, alter=0.05)
    n = g._buffer[-1]
    assert n.eing and n.lenk == 0.5 and n.gas == 1.0
    g2 = _geist()
    g2.apply_snapshot(_snap(0.0), send_time=5000.0, arrival=1000.0, alter=0.05)
    assert not g2._buffer[-1].eing


# ── Messstand: Zielwerte gegen die echte Fahrzeugphysik ──────────────────────────

@pytest.fixture(scope="module")
def fahrt():
    from tools import netz_messung as nm
    bilder = nm.fahrt_aufzeichnen()
    return nm, bilder, nm.Wahrheit(bilder)


def test_ziel_hauptleitung_30ms_5ms_jitter(fahrt):
    """Zielvorgabe: Mittel < 1 m, p95 < 2 m auf Geraden und beim Bremsen; kein
    Rueckwaertsruck; das Bild springt je Bild nie weit von der wahren Bewegung weg."""
    nm, bilder, wahrheit = fahrt
    sz = nm.Szenario("30/5", 30, 30, 5)
    neu = nm.simuliere(bilder, wahrheit, sz, "vorhersage")
    alt = nm.simuliere(bilder, wahrheit, sz, "interpolation")
    gb = neu.alle({"gerade", "bremsen"})
    assert sum(gb) / len(gb) < 1.0 and nm._pct(gb, 0.95) < 2.0
    assert neu.zurueck == 0
    assert max(neu.abw) < 0.5                    # m je Bild (Rempler eingeschlossen)
    a = alt.alle()
    assert sum(a) / len(a) > 4.0                 # die alte Wiedergabe: Meter hinterher
    assert sum(neu.alle()) / len(neu.alle()) < 0.1 * sum(a) / len(a)


@pytest.mark.parametrize("hin,her,jitter,verlust", [
    (15, 15, 2, 0.0), (30, 60, 8, 0.0), (60, 60, 10, 0.05), (60, 60, 20, 0.10),
])
def test_ziel_schlechtere_leitungen(fahrt, hin, her, jitter, verlust):
    nm, bilder, wahrheit = fahrt
    r = nm.simuliere(bilder, wahrheit, nm.Szenario("x", hin, her, jitter, verlust), "vorhersage")
    a = r.alle()
    assert sum(a) / len(a) < 1.0 and nm._pct(a, 0.95) < 2.0
    assert r.zurueck == 0
    assert max(r.abw) < 0.6


def test_ziel_uhrfehler_durch_ungleiche_pingstrecke(fahrt):
    """10 ms Asymmetrie am Empfaenger = 5 ms Uhrfehler = ~0,3 m bei 200 km/h."""
    nm, bilder, wahrheit = fahrt
    r = nm.simuliere(bilder, wahrheit, nm.Szenario("x", 30, 30, 5, 0.0, 10.0), "vorhersage")
    a = r.alle()
    assert sum(a) / len(a) < 1.0 and r.zurueck == 0


def test_ziel_funkloch_wird_weich_aufgeholt(fahrt):
    nm, bilder, wahrheit = fahrt
    for art in ("buendel", "verlust"):
        r = nm.simuliere(bilder, wahrheit,
                         nm.Szenario("x", 30, 30, 5, 0.0, 0.0, (10.0, 0.4, art)), "vorhersage")
        assert r.zurueck == 0
        assert max(r.abw) < 1.0
        a = r.alle()
        assert sum(a) / len(a) < 0.5


def test_ziel_ohne_abgleich_gleich_alt_wie_zuvor(fahrt):
    """Faellt der Uhrabgleich aus (alter Relay), verhaelt sich das Abbild wie bisher."""
    nm, bilder, wahrheit = fahrt
    from src.net.client import NetworkClient as NC
    orig = NC.alter_von
    NC.alter_von = lambda self, *a, **k: None
    try:
        r = nm.simuliere(bilder, wahrheit, nm.Szenario("x", 30, 30, 5), "vorhersage")
    finally:
        NC.alter_von = orig
    ref = nm.simuliere(bilder, wahrheit, nm.Szenario("x", 30, 30, 5), "interpolation")
    a, b = r.alle(), ref.alle()
    assert sum(a) / len(a) == pytest.approx(sum(b) / len(b), rel=1e-6)


# ── Ping-Takt des Uhrabgleichs ─────────────────────────────────────────────────

class _FalscheUhr:
    def __init__(self):
        self.t = 500.0

    def monotonic(self):
        return self.t


class _Steckdose:
    def __init__(self):
        self.gesendet = []

    def sendto(self, data, addr):
        self.gesendet.append(data)


def _client_mit_uhr(monkeypatch):
    from src.net import client as clientmod
    uhr = _FalscheUhr()
    monkeypatch.setattr(clientmod, "time", uhr)
    nc = NetworkClient()
    nc._alive = True
    nc._lobby_id = "ABCDEF"
    nc._slot = 1
    nc._udp = _Steckdose()
    return nc, uhr


def test_pings_laufen_zum_abgleich_schnell_an_und_dann_im_ruhigen_takt(monkeypatch):
    nc, uhr = _client_mit_uhr(monkeypatch)
    for _ in range(int(10.0 / 0.05)):
        uhr.t += 0.05
        nc.update(0.05)
        # der Relay antwortet sofort mit seiner Uhr
        while len(nc._udp.gesendet) > nc._uhr.anzahl:
            ping = nc._udp.gesendet[nc._uhr.anzahl]
            _, _, _, t0 = protocol.PING_FMT.unpack(ping)
            nc._uhr.probe(t0, uhr.t + 0.04, t0 + 0.02 + 99.0)
    assert nc._uhr.gueltig
    # 8 schnelle Pings in ~2 s, danach einer je Sekunde: ~8 + 8
    assert 14 <= len(nc._udp.gesendet) <= 18


def test_alter_relay_ohne_relayzeit_bekommt_nur_wenige_schnelle_pings(monkeypatch):
    nc, uhr = _client_mit_uhr(monkeypatch)
    for _ in range(int(20.0 / 0.05)):
        uhr.t += 0.05
        nc.update(0.05)
    # 12 schnelle (3 s), danach 1 s: ~12 + 17
    assert len(nc._udp.gesendet) <= 31
    assert not nc._uhr.gueltig


# ── Rennszene: Paket -> Abbild, Eingaben -> Paket ─────────────────────────────────

class _FalschesNetz:
    slot = 0
    connected = True

    def __init__(self):
        self.ereignisse = []
        self.gesendet = []

    def poll(self):
        e, self.ereignisse = self.ereignisse, []
        return iter(e)

    def send_state(self, fahrzeuge, zeit=None):
        self.gesendet.append((fahrzeuge, zeit))


def _rennstand(monkeypatch):
    import types
    from src.states.race_state import RaceState
    from src.net import session
    rs = RaceState(types.SimpleNamespace(transition=lambda *a, **k: None))
    rs.physics_world = types.SimpleNamespace(space=pymunk.Space())
    rs._online = True
    rs.race_manager = None
    nc = _FalschesNetz()
    monkeypatch.setattr(session, "get", lambda: nc)
    monkeypatch.setattr(RaceState, "_is_online_host", lambda self: False)
    return rs, nc


def test_rennszene_reicht_das_alter_durch_und_sendet_die_eingaben(monkeypatch, uhr):
    import types
    rs, nc = _rennstand(monkeypatch)
    paket = protocol.unpack_state(protocol.pack_state("ABCDEF", 1, [
        _auto(1, id=1, cfg="supercar", x=100.0, y=0.0, vx=V, vy=0.0, angle=0.0, omega=0.0,
              steer=0.0, throttle=1.0, brake=0.0, handbrake=False)], 5000.0, clock_offset=1.0))
    paket["arrival"] = uhr.t - 0.02
    paket["alter"] = 0.08
    nc.ereignisse.append({"source": "udp", "data": paket})
    rs.player = types.SimpleNamespace(
        id=1, body=pymunk.Body(1.0, 1.0), steer_input=-0.5, throttle=0.7, brake_input=0.25,
        handbrake=True)
    rs._send_accum = 1.0                   # sofort senden
    rs._update_online(DT)
    rv = rs._remote_map[(1, 1)]
    n = rv._buffer[-1]
    assert n.lt == pytest.approx(uhr.t - 0.02 - 0.08)       # Alter kam bis ins Abbild
    assert rv._w == 1.0 and n.eing
    (fahrzeuge, zeit), = nc.gesendet
    f = fahrzeuge[0]
    assert (f["steer"], f["throttle"], f["brake"], f["handbrake"]) == (-0.5, 0.7, 0.25, True)
    # und es passt durch das Paketformat
    roh = protocol.pack_state("ABCDEF", 0, fahrzeuge, 1.0, clock_offset=0.0)
    assert protocol.unpack_state(roh)["vehicles"][0]["handbrake"] is True


def test_rennszene_stempelt_pakete_mit_dem_physikschritt(monkeypatch, uhr):
    import types
    rs, nc = _rennstand(monkeypatch)
    rs.player = types.SimpleNamespace(id=1, body=pymunk.Body(1.0, 1.0))
    t0 = time.monotonic()
    rs._schritt_zeit = t0 - 0.004          # Physikschritt war vor 4 ms
    rs._send_accum = 1.0
    rs._update_online(DT)
    rs._schritt_zeit = t0 - 0.004          # derselbe Schritt noch einmal (Pause): kein altes Datum
    rs._send_accum = 1.0
    rs._update_online(DT)
    (_, z1), (_, z2) = nc.gesendet
    assert z1 == pytest.approx(t0 - 0.004)
    assert z2 is None                      # nicht wachsend -> Sender nimmt die Uhr
