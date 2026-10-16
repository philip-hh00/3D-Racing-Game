"""Messstand fuer die Online-Synchronisation: wie weit liegt das Abbild eines
Mitspielers neben dessen wahrer Lage?

Der Absender faehrt mit der ECHTEN Fahrzeugphysik (``Vehicle.update`` + pymunk,
60 Bilder/s) eine festgelegte Fahrt: Gerade auf ~200 km/h, Vollbremsung,
Schikane, Gerade, Bremsung mit Rempler, lange Kurve, Drift mit Handbremse und
Gegenlenken. Aufgezeichnet werden Lage,
Geschwindigkeit, Gierrate und Eingaben je Bild. Die Gegenstelle bekommt
daraus einen Strom wie im Spiel (50 Hz aus der 60-fps-Schleife, UDP ueber den
Relay mit Laufzeit je Strecke, Schwankung, Vertauschung und Verlust) und
zeichnet ein ``RemoteVehicle``. Verglichen wird in jedem Bild die gezeichnete
Lage mit der wahren Lage des Absenders zum SELBEN Zeitpunkt.

Alles laeuft auf einer virtuellen Uhr (``remote_vehicle._clock``) und mit
festem Zufallskeim — das Ergebnis ist reproduzierbar. Die Uhren von Absender,
Relay und Gegenstelle sind gegeneinander verschoben; der Abgleich laeuft ueber
dieselbe Klasse (``UhrSync``) mit denselben simulierten PING/PONG wie im Spiel.

    python tools/netz_messung.py            # Tabelle alt gegen neu
    python tools/netz_messung.py --kurz     # nur die Hauptleitung
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

M_PER_PX = 0.08           # src/core/settings.py::M_PER_PX
FPS = 60.0
DT = 1.0 / FPS


# ── Fahrt des Absenders (echte Physik) ──────────────────────────────────────────

# (bis Sekunde, Gas, Bremse, Lenkung, Phase[, Handbremse])
SKRIPT = [
    (12.0, 1.0, 0.0, 0.0, "gerade"),
    (14.6, 0.0, 1.0, 0.0, "bremsen"),
    (15.4, 0.0, 0.0, 0.0, "gerade"),
    (16.2, 0.6, 0.0, 0.9, "schikane"),
    (17.6, 0.6, 0.0, -1.0, "schikane"),
    (18.4, 0.6, 0.0, 0.8, "schikane"),
    (19.0, 0.8, 0.0, -0.4, "schikane"),
    (26.0, 1.0, 0.0, 0.0, "gerade"),
    (29.0, 0.0, 0.6, 0.0, "bremsen"),
    (35.0, 1.0, 0.0, 0.0, "gerade"),
    (39.0, 0.8, 0.0, 0.28, "kurve"),
    (42.0, 1.0, 0.0, 0.0, "gerade"),
    (43.2, 0.6, 0.0, 0.9, "drift"),
    (44.4, 0.6, 0.0, 0.9, "drift", True),        # Handbremse: das Heck kommt
    (45.6, 0.8, 0.0, -0.6, "drift"),             # Gegenlenken
    (48.0, 1.0, 0.0, 0.0, "gerade"),
]
REMPLER_T = 27.5           # waehrend des zweiten Bremsens: seitlicher Stoss
REMPLER_V = 3.5            # m/s seitlich
REMPLER_W = 0.9            # rad/s Gierstoss
DAUER = SKRIPT[-1][0]


class Bild:
    __slots__ = ("t", "x", "y", "winkel", "vx", "vy", "omega",
                 "lenk", "gas", "bremse", "hand", "phase")


def fahrt_aufzeichnen(config_key: str = "supercar") -> list:
    """Die Fahrt mit der echten Physik fahren; eine ``Bild``-Liste (60 Hz)."""
    from src.entities.vehicle import Vehicle
    from src.entities.vehicle_factory import VehicleFactory
    from src.physics.physics_world import PhysicsWorld
    import pymunk

    if not VehicleFactory.get_config(config_key):
        VehicleFactory.load_all_configs()
    welt = PhysicsWorld()
    auto = VehicleFactory.create_player_vehicle(config_key, 1, (0.0, 0.0), 0.0,
                                                welt.space, lack="werk")
    bilder = []
    n = int(DAUER * FPS)
    rempler_getan = False
    for i in range(n + 1):
        t = i * DT
        for zeile in SKRIPT:
            if t < zeile[0]:
                break
        gas, bremse, lenk, phase = zeile[1:5]
        hand = len(zeile) > 5 and zeile[5]
        if hand:
            gas, bremse = 0.0, 1.0
        auto.throttle, auto.brake_input, auto.steer_input, auto.handbrake = \
            gas, bremse, lenk, hand
        if not rempler_getan and t >= REMPLER_T:
            rempler_getan = True
            b = auto.physics.body
            quer = pymunk.Vec2d(0.0, REMPLER_V / M_PER_PX).rotated(b.angle)
            b.velocity = b.velocity + quer
            b.angular_velocity = b.angular_velocity + REMPLER_W
        Vehicle.update(auto, DT)
        welt.step(DT)
        b = auto.physics.body
        f = Bild()
        f.t = t + DT          # Zustand NACH dem Schritt gilt zum Ende des Bildes
        f.x, f.y = float(b.position.x), float(b.position.y)
        f.winkel = float(b.angle)
        f.vx, f.vy = float(b.velocity.x), float(b.velocity.y)
        f.omega = float(b.angular_velocity)
        f.lenk, f.gas, f.bremse, f.hand = auto.steer_input, auto.throttle, auto.brake_input, bool(auto.handbrake)
        f.phase = phase
        bilder.append(f)
    return bilder


class Wahrheit:
    """Die wahre Lage des Absenders zu jeder Zeit (kubisch zwischen den Bildern)."""

    def __init__(self, bilder):
        self.b = bilder
        self.t0 = bilder[0].t

    def bei(self, t: float):
        b = self.b
        i = int((t - self.t0) * FPS)
        i = max(0, min(len(b) - 2, i))
        a, c = b[i], b[i + 1]
        u = (t - a.t) / (c.t - a.t)
        u = max(0.0, min(1.0, u))
        h = c.t - a.t
        u2, u3 = u * u, u * u * u
        h00, h10, h01, h11 = 2 * u3 - 3 * u2 + 1, u3 - 2 * u2 + u, -2 * u3 + 3 * u2, u3 - u2
        x = h00 * a.x + h10 * h * a.vx + h01 * c.x + h11 * h * c.vx
        y = h00 * a.y + h10 * h * a.vy + h01 * c.y + h11 * h * c.vy
        return x, y

    def vorwaerts(self, t: float):
        i = max(0, min(len(self.b) - 1, int((t - self.t0) * FPS)))
        f = self.b[i]
        n = math.hypot(f.vx, f.vy)
        return (f.vx / n, f.vy / n) if n > 1.0 else (math.cos(f.winkel), math.sin(f.winkel))

    def phase(self, t: float) -> str:
        i = max(0, min(len(self.b) - 1, int((t - self.t0) * FPS)))
        return self.b[i].phase


# ── Leitung, Relay und Gegenstelle ──────────────────────────────────────────────

class Szenario:
    """Eine Leitung: Laufzeit je Strecke (Absender-Relay, Relay-Empfaenger) in ms,
    Schwankung (mittlere Zusatzlaufzeit, exponentiell verteilt), Verlust 0..1."""

    def __init__(self, name, hin_ms, her_ms, jitter_ms, verlust=0.0, asym_ms=0.0, luecke=None):
        self.name, self.hin_ms, self.her_ms = name, hin_ms, her_ms
        self.jitter_ms, self.verlust, self.asym_ms = jitter_ms, verlust, asym_ms
        #: (Start in s, Dauer in s, "buendel" | "verlust"): Funkloch im Strom
        self.luecke = luecke


class Ergebnis:
    def __init__(self):
        self.fehler = {}          # Phase -> [m]
        self.laengs = []          # vorzeichenbehaftet, + = Abbild vor dem Absender
        self.laengs_ph = {}
        self.zurueck = 0
        self.zurueck_max = 0.0
        self.abw = []             # |Bildschritt Abbild - Bildschritt Wahrheit| [m]
        self.frames = 0

    def alle(self, phasen=None):
        out = []
        for ph, v in self.fehler.items():
            if phasen is None or ph in phasen:
                out += v
        return out


def _pct(v, p):
    if not v:
        return float("nan")
    v = sorted(v)
    return v[min(len(v) - 1, int(p * len(v)))]


def simuliere(bilder, wahrheit, sz: Szenario, modus: str, seed: int = 7,
              config_key: str = "supercar", beginn: float = 3.0,
              empfaenger_fps: float = 60.0, daten_hook=None) -> Ergebnis:
    """Die Fahrt ``bilder`` durch die Leitung ``sz`` zu einem ``RemoteVehicle`` in
    ``modus`` schicken und dessen Abbild gegen ``wahrheit`` messen."""
    import heapq
    import random
    import pymunk
    from src.entities import remote_vehicle as rvmod
    from src.entities.vehicle_factory import VehicleFactory
    from src.net import protocol
    from src.net.client import NetworkClient
    from src.net.uhrsync import UhrSync

    if not VehicleFactory.get_config(config_key):
        VehicleFactory.load_all_configs()
    rng = random.Random(seed)
    O_S, O_R, O_Y = 5000.0, 700.0, 123456.0         # Uhr = Weltzeit + O
    sync_s, sync_r = UhrSync(), UhrSync()
    nc = NetworkClient()
    nc._uhr = sync_r

    def bein(basis_ms):
        j = rng.expovariate(1.0 / sz.jitter_ms) if sz.jitter_ms > 0 else 0.0
        return (basis_ms + j) / 1000.0

    ereignisse = []
    zaehler = [0]

    def plane(g, art, *nutz):
        zaehler[0] += 1
        heapq.heappush(ereignisse, (g, zaehler[0], art, nutz))

    # PING/PONG beider Clients mit dem Relay, ab 12 s vor dem Start (Lobbyzeit):
    # erst 8 Proben im Abstand 0,25 s, dann jede Sekunde — wie NetworkClient.update.
    for seite, o, hin in (("s", O_S, sz.hin_ms), ("r", O_R, sz.her_ms)):
        g = -12.0
        n = 0
        while g < DAUER + 1.0:
            # Ungleiche Strecken (Hin langsamer als Zurueck) nur beim Empfaenger:
            # sein Versatz liegt dann um asym/2 daneben.
            asym = sz.asym_ms if seite == "r" else 0.0
            auf = bein(hin + asym)
            ab = bein(hin - asym)
            if rng.random() >= sz.verlust:
                plane(g + auf + ab, "pong", seite, g + o, g + auf + ab + o, g + auf + O_Y)
            n += 1
            g += 0.25 if n < 8 else 1.0

    # Absender-Bilder und Bilder der Gegenstelle
    for f in bilder:
        plane(f.t, "sender", f)
    phase = 0.37 / empfaenger_fps
    k = 0
    while k / empfaenger_fps + phase < DAUER:
        plane(k / empfaenger_fps + phase, "empfang")
        k += 1

    space = pymunk.Space()
    rv = rvmod.RemoteVehicle(vehicle_id=1, sender_slot=1, space=space, config_key=config_key)
    rv.modus = modus
    uhr = [0.0]
    alt = rvmod._clock
    rvmod._clock = lambda: uhr[0]
    res = Ergebnis()
    posteingang = []
    accum = 0.0
    vorher = None
    dt = 1.0 / empfaenger_fps
    try:
        while ereignisse:
            g, _, art, nutz = heapq.heappop(ereignisse)
            if art == "pong":
                seite, t0, t3, ys = nutz
                (sync_s if seite == "s" else sync_r).probe(t0, t3, ys)
            elif art == "sender":
                f = nutz[0]
                accum += DT
                if accum < 1.0 / 50.0 - 1e-9:
                    continue
                accum -= 1.0 / 50.0
                fahrzeug = {"id": 1, "cfg": config_key, "x": f.x, "y": f.y, "angle": f.winkel,
                            "vx": f.vx, "vy": f.vy, "omega": f.omega, "lap": 1, "wp": 0,
                            "steer": f.lenk, "throttle": f.gas, "brake": f.bremse,
                            "handbrake": f.hand}
                roh = protocol.pack_state("ABCDEF", 1, [fahrzeug], g + O_S,
                                          clock_offset=sync_s.versatz)
                if rng.random() < sz.verlust:
                    continue
                an = g + bein(sz.hin_ms) + bein(sz.her_ms)
                if sz.luecke is not None:
                    start, dauer, art_l = sz.luecke
                    if start <= g < start + dauer:
                        if art_l == "verlust":
                            continue
                        an = max(an, start + dauer)       # gebuendelt nach der Pause
                plane(an, "ankunft", roh)
            elif art == "ankunft":
                posteingang.append((g, nutz[0]))
            elif art == "empfang":
                uhr[0] = g + O_R
                for g_an, roh in posteingang:
                    p = protocol.unpack_state(roh)
                    arrival = g_an + O_R
                    alter = nc.alter_von(arrival, p["send_time"], p.get("clock_offset"))
                    if daten_hook:
                        daten_hook(p, alter)
                    rv.apply_snapshot(p["vehicles"][0], p["send_time"], arrival, alter)
                posteingang.clear()
                rv.update(dt)
                if g < beginn or g > DAUER - 0.5 or not rv._initialized:
                    vorher = None
                    continue
                wx, wy = wahrheit.bei(g)
                px, py = rv._pos
                e = math.hypot(px - wx, py - wy) * M_PER_PX
                fx, fy = wahrheit.vorwaerts(g)
                res.fehler.setdefault(wahrheit.phase(g), []).append(e)
                res.laengs.append(((px - wx) * fx + (py - wy) * fy) * M_PER_PX)
                res.laengs_ph.setdefault(wahrheit.phase(g), []).append(res.laengs[-1])
                res.frames += 1
                if vorher is not None:
                    vpx, vpy, vwx, vwy = vorher
                    schritt = ((px - vpx) - (wx - vwx), (py - vpy) - (wy - vwy))
                    res.abw.append(math.hypot(*schritt) * M_PER_PX)
                    vor = ((px - vpx) * fx + (py - vpy) * fy) * M_PER_PX
                    tempo = math.hypot(wx - vwx, wy - vwy) * M_PER_PX * empfaenger_fps
                    if vor < -0.02 and tempo > 3.0:
                        res.zurueck += 1
                        res.zurueck_max = max(res.zurueck_max, -vor)
                vorher = (px, py, wx, wy)
    finally:
        rvmod._clock = alt
        rv.cleanup(space)
    return res


SZENARIEN = [
    Szenario("15 ms, 2 ms Jitter", 15, 15, 2),
    Szenario("30 ms, 5 ms Jitter (Hauptfall)", 30, 30, 5),
    Szenario("30 ms, 5 ms, 3 % Verlust", 30, 30, 5, 0.03),
    Szenario("30/60 ms Strecken, 8 ms", 30, 60, 8),
    Szenario("30 ms, 5 ms, Ping asym. 10 ms", 30, 30, 5, 0.0, 10.0),
    Szenario("60 ms, 10 ms, 5 % Verlust", 60, 60, 10, 0.05),
    Szenario("60 ms, 20 ms, 10 % Verlust", 60, 60, 20, 0.10),
    Szenario("30 ms, 5 ms, 0,4 s Luecke (Buendel)", 30, 30, 5, 0.0, 0.0, (10.0, 0.4, "buendel")),
    Szenario("30 ms, 5 ms, 0,4 s Luecke (Verlust)", 30, 30, 5, 0.0, 0.0, (10.0, 0.4, "verlust")),
    Szenario("100 ms, 40 ms, 15 % Verlust", 100, 100, 40, 0.15),
]


def tabelle(modi=("interpolation", "vorhersage"), szenarien=None, seed=7, bilder=None):
    bilder = bilder or fahrt_aufzeichnen()
    wahrheit = Wahrheit(bilder)
    zeilen = []
    for sz in (szenarien or SZENARIEN):
        for modus in modi:
            r = simuliere(bilder, wahrheit, sz, modus, seed=seed)
            gb = {"gerade", "bremsen"}
            a = r.alle()
            b = r.alle(gb)
            zeilen.append((sz.name, modus,
                           sum(a) / len(a), _pct(a, 0.95), max(a),
                           sum(b) / len(b), _pct(b, 0.95),
                           r.zurueck, r.zurueck_max, max(r.abw), _pct(r.abw, 0.99),
                           sum(r.laengs) / len(r.laengs)))
    return zeilen


def drucken(zeilen):
    print(f"{'Leitung':34s} {'Modus':13s} | {'mittel':>6s} {'p95':>6s} {'max':>6s} | "
          f"{'g+b mit':>7s} {'g+b p95':>7s} | {'zurueck':>7s} {'(max m)':>7s} | "
          f"{'Bildabw max':>11s} {'p99':>5s} | {'laengs':>6s}")
    for z in zeilen:
        print(f"{z[0]:34s} {z[1]:13s} | {z[2]:6.2f} {z[3]:6.2f} {z[4]:6.2f} | "
              f"{z[5]:7.2f} {z[6]:7.2f} | {z[7]:7d} {z[8]:7.3f} | {z[9]:11.3f} {z[10]:5.3f} | {z[11]:+6.2f}")


if __name__ == "__main__":
    if "--fahrt" in sys.argv:
        for s in range(0, int(DAUER) + 1, 2):
            f = fahrt_aufzeichnen()[int(s * FPS)]
            v = math.hypot(f.vx, f.vy) * M_PER_PX
            print(f"{s:3d}s  {f.phase:9s} v={v:5.1f} m/s omega={f.omega:+.2f}")
    else:
        kurz = "--kurz" in sys.argv
        drucken(tabelle(szenarien=SZENARIEN[1:2] if kurz else None))


