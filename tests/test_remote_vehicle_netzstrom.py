"""Ferne Fahrzeuge unter einem echten Netzstrom: kein Ruckeln, kein Zurueckspringen.

Gemeldet 06.10.2026: Mitspieler und die vom Host gerechneten KI-Autos zuckten
online und sprangen kurz zurueck. Ursache war ``RemoteVehicle.update``: statt
den gepufferten Pfad wiederzugeben, setzte jedes Paket die Hochrechnung hart
auf seine (verschieden alte) Lage, und der Fehlerabbau zog das Abbild bei
jedem verspaeteten Paket rueckwaerts.

Hier laeuft der Strom so, wie er im Spiel ankommt: gesendet mit 50 Hz aus
einer 60-fps-Schleife (also abwechselnd 17 und 33 ms Abstand), mit Laufzeit,
Schwankung, Verlust, Doppeln, vertauschter Reihenfolge, Paketbuendeln nach
einer WLAN-Pause und einer Senderuhr, die mit der eigenen nichts zu tun hat.
Geprueft wird, was man sieht: der gezeichnete Wagen kommt auf seinem Weg nie
zurueck, schiesst nicht vor, bleibt auf der Linie und haengt nur wenig nach.

Zeit laeuft ueber den ``_clock``-Haken des Moduls — deterministisch, ohne
Schlafen. Braucht pymunk und eine Attrappen-Anzeige, aber kein Fenster.
"""
from __future__ import annotations

import math
import os
import random
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import pymunk
import pytest

pygame.init()
pygame.display.set_mode((64, 64))

from src.entities import remote_vehicle as rvmod  # noqa: E402
from src.entities.remote_vehicle import RemoteVehicle, INTERP_DELAY_MAX  # noqa: E402
from src.entities.vehicle_factory import VehicleFactory  # noqa: E402

VehicleFactory.load_all_configs()

SENDER_FPS = 60.0
SEND_HZ = 50.0
# Senderuhr laeuft 500 s hinter der eigenen — nur die Abstaende zaehlen.
SENDER_VERSATZ = -500.0
START = 1000.0


class _Uhr:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t


@pytest.fixture
def uhr():
    u = _Uhr()
    alt = rvmod._clock
    rvmod._clock = u
    yield u
    rvmod._clock = alt


# ── Bahnen: Zeit (eigene Uhr) -> (x, y, vx, vy, winkel, omega) ─────────────────

KREIS_M = (2000.0, 2000.0)
KREIS_R = 600.0
KREIS_V = 700.0                     # px/s, gut 200 km/h
KREIS_W = KREIS_V / KREIS_R         # rad/s


def _kreis(t: float):
    phi = (t - START) * KREIS_W
    x = KREIS_M[0] + KREIS_R * math.cos(phi)
    y = KREIS_M[1] + KREIS_R * math.sin(phi)
    vx = -KREIS_V * math.sin(phi)
    vy = KREIS_V * math.cos(phi)
    return x, y, vx, vy, phi + math.pi / 2, KREIS_W


def _phase(pos) -> float:
    return math.atan2(pos[1] - KREIS_M[1], pos[0] - KREIS_M[0])


BREMS_V0 = 800.0
BREMS_A = 1600.0                    # px/s², steht nach 0.5 s
BREMS_AB = START + 0.6
BREMS_HALT = BREMS_V0 * 0.6 + BREMS_V0 ** 2 / (2 * BREMS_A)


def _bremsen(t: float):
    dt = t - START
    if t <= BREMS_AB:
        return BREMS_V0 * dt, 0.0, BREMS_V0, 0.0, 0.0, 0.0
    tb = min(t - BREMS_AB, BREMS_V0 / BREMS_A)
    v = BREMS_V0 - BREMS_A * tb
    x = BREMS_V0 * 0.6 + BREMS_V0 * tb - 0.5 * BREMS_A * tb * tb
    return x, 0.0, v, 0.0, 0.0, 0.0


DREH_W = 4.0                        # rad/s — ein Dreher


def _dreher(t: float):
    w = ((t - START) * DREH_W + math.pi) % (2 * math.pi) - math.pi   # wie (-pi, pi]
    return 300.0, 300.0, 0.0, 0.0, w, DREH_W


# ── Netzstrom ─────────────────────────────────────────────────────────────────

def _strom(bahn, dauer: float, *, latenz=0.03, schwankung=0.0, verlust=0.0,
           doppelt=0.0, vertauscht=0.0, stufen=(), buendel=(), seed=1):
    """Pakete wie im Spiel: (ankunft, send_time, snap), nach Ankunft sortiert.

    Gesendet wird im Takt der Senderschleife (60 fps) ueber einen 50-Hz-
    Akkumulator, genau wie ``RaceState._update_online``. ``stufen``:
    (von, bis, mehr) — was in diesem Fenster gesendet wird, braucht ``mehr``
    Sekunden laenger, in Reihenfolge (Funkloch, Energiesparen, Routenwechsel).
    ``buendel``: (von, bis) — alles dazwischen kommt gesammelt bei ``bis`` an
    (WLAN-Puffer).
    """
    rng = random.Random(seed)
    pakete = []
    akku = 0.0
    t = START
    bild = 1.0 / SENDER_FPS
    while t < START + dauer:
        akku += bild
        t += bild
        if akku < 1.0 / SEND_HZ:
            continue
        akku -= 1.0 / SEND_HZ
        if rng.random() < verlust:
            continue
        x, y, vx, vy, w, om = bahn(t)
        snap = {"id": 1, "x": x, "y": y, "vx": vx, "vy": vy,
                "angle": w, "omega": om, "lap": 1, "wp": 0}
        ankunft = t + latenz + rng.uniform(0.0, schwankung)
        if rng.random() < vertauscht:
            ankunft += 0.045           # ueberholt vom naechsten Paket
        for von, bis, mehr in stufen:
            if von <= t < bis:
                ankunft += mehr
        for von, bis in buendel:
            if von <= ankunft < bis:
                ankunft = bis
        pakete.append((ankunft, t + SENDER_VERSATZ, snap))
        if rng.random() < doppelt:
            pakete.append((ankunft + 0.004, t + SENDER_VERSATZ, dict(snap)))
    pakete.sort(key=lambda p: p[0])
    return pakete


def _abspielen(uhr, pakete, dauer: float, fps: float = 60.0):
    """Empfaenger: Pakete bis jetzt zustellen, dann ``update``. Liefert je Bild
    (zeit, position, winkel)."""
    g = RemoteVehicle(vehicle_id=1, sender_slot=1, space=pymunk.Space(),
                      config_key="rookie")
    dt = 1.0 / fps
    i = 0
    bilder = []
    while uhr.t < START + dauer:
        uhr.t += dt
        while i < len(pakete) and pakete[i][0] <= uhr.t:
            ankunft, st, snap = pakete[i]
            g.apply_snapshot(snap, send_time=st, arrival=ankunft)
            i += 1
        g.update(dt)
        if g.bereit:
            bilder.append((uhr.t, g.position, g.angle))
    return g, bilder


def _kreis_pruefen(bilder, fps: float, *, max_nachlauf: float, max_quer: float = 3.0):
    """Auf dem Kreis: nie zurueck, gleichmaessiges Tempo, auf der Linie, kleiner
    Nachlauf. Das Tempo darf sich bewegen, solange die Wiedergabe ihre
    Verzoegerung nachstellt — aber nicht pumpen (vorher 0.5- bis 1.5-fach auf
    wackeliger Leitung) und nicht vorschiessen."""
    dt = 1.0 / fps
    bilder = [b for b in bilder if b[0] > START + 0.3]   # Anlauf des Puffers
    rueck, tempo, quer, nachlauf = [], [], [], []
    for (t0, p0, _), (t1, p1, _) in zip(bilder, bilder[1:]):
        dphi = (_phase(p1) - _phase(p0) + math.pi) % (2 * math.pi) - math.pi
        weg = dphi * KREIS_R
        if weg < -1e-6:
            rueck.append(weg)
        tempo.append(weg / dt / KREIS_V)
    for t, p, _ in bilder:
        quer.append(abs(math.hypot(p[0] - KREIS_M[0], p[1] - KREIS_M[1]) - KREIS_R))
        soll = (t - START) * KREIS_W
        nachlauf.append(((soll - _phase(p) + math.pi) % (2 * math.pi) - math.pi) / KREIS_W)
    assert not rueck, f"{len(rueck)} Rueckspruenge, groesster {min(rueck):.2f} px"
    assert min(tempo) > 0.7 and max(tempo) < 1.3,         f"Tempo pumpt zwischen {min(tempo):.2f}- und {max(tempo):.2f}-fach"
    assert max(quer) < max_quer, f"bis {max(quer):.1f} px neben der Linie"
    assert min(nachlauf) > 0.0, "vor dem echten Wagen — das waere geraten"
    assert max(nachlauf) < max_nachlauf, f"Nachlauf bis {max(nachlauf) * 1000:.0f} ms"


# ── Gleichmaessige Fahrt unter verschiedenen Leitungen ────────────────────────

def test_saubere_leitung_kreis_ohne_ruckeln(uhr):
    pakete = _strom(_kreis, 4.0)
    _, bilder = _abspielen(uhr, pakete, 4.0)
    _kreis_pruefen(bilder, 60.0, max_nachlauf=0.03 + 0.08)


@pytest.mark.parametrize("fps", [60.0, 75.0, 144.0, 30.0])
def test_wackelige_leitung_kreis_ohne_ruckeln(uhr, fps):
    """Schwankung 40 ms, Verlust, Doppel, vertauschte Pakete — bei jeder
    Bildrate des Empfaengers (Schwebung zwischen Sende- und Bildtakt)."""
    pakete = _strom(_kreis, 5.0, schwankung=0.04, verlust=0.05, doppelt=0.05,
                    vertauscht=0.08, seed=7)
    _, bilder = _abspielen(uhr, pakete, 5.0, fps=fps)
    _kreis_pruefen(bilder, fps, max_nachlauf=0.03 + 0.04 + INTERP_DELAY_MAX + 0.03)


def test_laufzeitsprung_zieht_nicht_zurueck(uhr):
    """Der gemeldete Fall: die Laufzeit springt fuer eine Weile um 80 ms nach
    oben. Vorher zog das erste spaete Paket das Abbild sichtbar zurueck und
    das Ende des Lochs liess es mit mehr als doppeltem Tempo vorschiessen."""
    pakete = _strom(_kreis, 4.0, schwankung=0.005,
                    stufen=[(START + 1.0, START + 1.4, 0.08),
                            (START + 2.5, START + 2.7, 0.06)])
    _, bilder = _abspielen(uhr, pakete, 4.0)
    # Bis der Puffer gewachsen ist, wird kurz hochgerechnet: ein paar Pixel
    # neben der Linie, sanft zurueckgefuehrt.
    _kreis_pruefen(bilder, 60.0, max_nachlauf=0.03 + 0.08 + INTERP_DELAY_MAX,
                   max_quer=6.0)


def test_paketbuendel_nach_wlan_pause(uhr):
    """120 ms nichts, dann alles auf einmal — wird im Sendeabstand abgespielt.

    Laenger als der Puffer reicht, wird tangential hochgerechnet; auf dem
    Kreis mit 600 px Radius liegt das Abbild dabei bis gut einen halben Meter
    neben der Linie und wird dann sanft zurueckgefuehrt — ohne Rueckwaertsruck.
    """
    pakete = _strom(_kreis, 4.0, schwankung=0.005,
                    buendel=[(START + 1.5, START + 1.62), (START + 2.8, START + 2.95)])
    _, bilder = _abspielen(uhr, pakete, 4.0)
    _kreis_pruefen(bilder, 60.0, max_nachlauf=0.03 + 0.15 + INTERP_DELAY_MAX,
                   max_quer=10.0)


# ── Bremsen, Drehen, Duplikate, Neustart ──────────────────────────────────────

def test_vollbremsung_ohne_ueberschiessen_und_zurueckspringen(uhr):
    pakete = _strom(_bremsen, 2.0, schwankung=0.03, vertauscht=0.05, seed=3)
    _, bilder = _abspielen(uhr, pakete, 2.0)
    xs = [p[0] for _, p, _ in bilder]
    for a, b in zip(xs, xs[1:]):
        # 0.05 px sind 4 mm: die Hermite-Kurve darf am Haltepunkt so wenig
        # ueberstehen, ein sichtbarer Ruck nach hinten nicht.
        assert b >= a - 0.05, f"zurueck von {a:.2f} auf {b:.2f}"
    assert max(xs) <= BREMS_HALT + 1.0, f"ueber den Haltepunkt hinaus: {max(xs):.1f}"
    assert abs(xs[-1] - BREMS_HALT) < 1.0


def test_dreher_ueber_die_winkelgrenze_springt_nicht(uhr):
    """Der Sender meldet den Winkel in (-pi, pi]; das Abbild dreht stetig weiter
    statt beim Uebertritt einmal um 2 pi zurueckzuschnappen."""
    pakete = _strom(_dreher, 3.0, schwankung=0.02, seed=5)
    _, bilder = _abspielen(uhr, pakete, 3.0)
    bilder = [b for b in bilder if b[0] > START + 0.3]
    for (_, _, w0), (_, _, w1) in zip(bilder, bilder[1:]):
        dw = w1 - w0
        assert 0.0 <= dw <= DREH_W * 1.3 / 60.0, f"Winkelsprung {dw:.3f} rad"


def test_doppeltes_paket_wird_ignoriert(uhr):
    g = RemoteVehicle(vehicle_id=1, sender_slot=1, space=pymunk.Space())
    snap = {"x": 10.0, "y": 0.0, "vx": 0.0, "vy": 0.0, "angle": 0.0, "omega": 0.0}
    g.apply_snapshot(snap, send_time=5.0, arrival=START)
    g.apply_snapshot(dict(snap, x=99.0), send_time=5.0, arrival=START + 0.01)
    assert len(g._buffer) == 1
    assert g._target_pos == (10.0, 0.0)


def test_neu_gestarteter_sender_wird_wieder_verfolgt(uhr):
    """Startet der Mitspieler sein Spiel neu, beginnt seine Uhr woanders. Das
    darf nicht als 'alles veraltet' enden, bei dem das Abbild fuer immer steht."""
    g = RemoteVehicle(vehicle_id=1, sender_slot=1, space=pymunk.Space())
    for i in range(30):
        uhr.t += 0.02
        g.apply_snapshot({"x": 10.0 * i, "y": 0.0, "vx": 500.0, "vy": 0.0, "angle": 0.0},
                         send_time=900.0 + 0.02 * i, arrival=uhr.t)
        g.update(0.02)
    for i in range(30):
        uhr.t += 0.02
        g.apply_snapshot({"x": 1000.0 + 10.0 * i, "y": 0.0, "vx": 500.0, "vy": 0.0,
                          "angle": 0.0}, send_time=3.0 + 0.02 * i, arrival=uhr.t)
        g.update(0.02)
    assert g._target_pos[0] == 1290.0
    assert abs(g.position[0] - 1290.0) < 60.0


def test_kinematischer_koerper_folgt_der_zeichnung(uhr):
    """Der Koerper ist kinematisch (kein Gegeneinander mit lokaler Physik) und
    steht in jedem Bild genau dort, wo das Abbild gezeichnet wird."""
    pakete = _strom(_kreis, 1.5, schwankung=0.03, seed=2)
    g, _ = _abspielen(uhr, pakete, 1.5)
    assert g.body.body_type == pymunk.Body.KINEMATIC
    assert math.hypot(g.body.position.x - g.position[0],
                      g.body.position.y - g.position[1]) < 1e-6
    assert abs(g.body.angle - g.angle) < 1e-9
    assert g.body.velocity.length == pytest.approx(KREIS_V, rel=0.05)


# ── 3D-Szene: eigene Kennung je fernem Fahrzeug ───────────────────────────────

def test_fernes_fahrzeug_teilt_keine_szenenkennung_mit_dem_eigenen():
    """Jeder Mitspieler sendet sein Auto mit Id 1 — wie das eigene. Unter einer
    gemeinsamen Kennung teilten sie sich in der 3D-Szene Raeder, Lenkung,
    Neigung und Reifenspur."""
    from types import SimpleNamespace
    from src.states.race_state import szenen_kennung, GHOST_KENNUNG
    eigen = SimpleNamespace(id=1)
    ki = SimpleNamespace(id=3)
    fern_a = SimpleNamespace(id=1, is_remote=True, sender_slot=1)
    fern_b = SimpleNamespace(id=1, is_remote=True, sender_slot=2)
    fern_ki = SimpleNamespace(id=3, is_remote=True, sender_slot=0)
    kennungen = [szenen_kennung(v) for v in (eigen, ki, fern_a, fern_b, fern_ki)]
    assert kennungen[:2] == [1, 3]
    assert len(set(kennungen)) == len(kennungen)
    assert GHOST_KENNUNG not in kennungen
