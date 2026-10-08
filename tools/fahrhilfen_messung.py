"""Messung der Fahrhilfen (ABS, Traktionskontrolle) mit der echten Fahrzeugphysik.

    .venv\\Scripts\\python.exe tools\\fahrhilfen_messung.py [--fahrzeug rookie ...]

Gefahren wird mit ``PlayerVehicle``-Physik in einem leeren pymunk-Raum, mit
Eingaben nach Skript: gleiche Eingabe, einmal ohne und einmal mit Hilfe.

* **Bremsweg** aus 150 km/h, geradeaus, Vollbremsung.
* **Bremsen in der Kurve** aus 150 km/h bei halbem Einschlag: Schräglauf und
  Spurabweichung gegenüber derselben Fahrt ohne Bremse.
* **Anfahren**: Durchdrehen (Anteil der Antriebskraft, den die Achse nicht
  überträgt, über die ersten drei Sekunden) und Zeit auf 100 km/h.

Hinweis: Das Spiel kennt kein Blockieren der Räder (die Bremse ist eine
Verzögerung ohne Reifenlimit, 1,1 bis 1,3 g). Der "Bezug blockiert" ist deshalb
eine Rechnung mit Gleitreibung, kein Spielverhalten.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pymunk                                              # noqa: E402

from src.core.settings import KMH_PER_PXS, M_PER_PX        # noqa: E402
from src.entities.components.fahrhilfen import Fahrhilfen  # noqa: E402
from src.entities.vehicle_factory import VehicleFactory    # noqa: E402
from src.physics.physics_world import PhysicsWorld         # noqa: E402

DT = 1.0 / 60.0


def auto(schluessel: str, kmh: float, abs_an: bool = False, tc_an: bool = False):
    if not VehicleFactory.get_config(schluessel):
        VehicleFactory.load_all_configs(str(WURZEL / "data" / "vehicles"))
    welt = PhysicsWorld()
    a = VehicleFactory.create_player_vehicle(schluessel, 1, (0.0, 0.0), 0.0, welt.space, lack="werk")
    a.physics.body.velocity = (kmh / KMH_PER_PXS, 0.0)
    a.prev_velocity = pymunk.Vec2d(*a.physics.body.velocity)
    a.is_analog = False
    if abs_an or tc_an:
        a.fahrhilfen = Fahrhilfen(abs_an=abs_an, tc_an=tc_an)
    return welt, a


def schritt(welt, a, gas=0.0, bremse=0.0, lenken=0.0, handbremse=False):
    a.throttle, a.brake_input, a.steer_input, a.handbrake = gas, bremse, lenken, handbremse
    a.update(DT)
    welt.step(DT)


def bremsweg(schluessel: str, abs_an: bool, lenken: float = 0.0, kmh: float = 150.0):
    welt, a = auto(schluessel, kmh, abs_an=abs_an)
    t, max_schlupf, weg = 0.0, 0.0, 0.0
    p0 = a.physics.body.position
    while a.speed * KMH_PER_PXS > 3.0 and t < 20.0:
        schritt(welt, a, bremse=1.0, lenken=lenken)
        t += DT
        max_schlupf = max(max_schlupf, a.physics.reifen_schlupf_deg if a.speed * KMH_PER_PXS > 30 else 0.0)
    weg = (a.physics.body.position - p0).length * M_PER_PX
    return weg, t, max_schlupf


def blockiert_bezug(schluessel: str, kmh: float = 150.0):
    """Bremsweg mit **blockierten Rädern** nach dem Reifenmodell: Gleitreibung.

    Das Spiel selbst kennt kein Blockieren (die Bremse ist eine Verzögerung
    ohne Reifenlimit), also rechnet das hier als Bezug eindimensional: statt
    der Bremskraft der Autos wirkt ``GLEIT_ANTEIL * Haftung * g``, wie bei der
    Handbremse. Dazu die Haftung nach der Last (Haftung × g), mit der auch
    ``apply_drive_force`` rechnet.
    """
    from src.entities.components.physics_body import PhysicsBody
    cfg = VehicleFactory.get_config(schluessel)
    a_max = cfg.grip * 9.81                       # haftend, m/s²
    a_gleit = PhysicsBody.GLEIT_ANTEIL * a_max    # blockiert, m/s²
    v = kmh / 3.6
    return v * v / (2.0 * a_gleit), a_max, a_gleit


def anfahren(schluessel: str, tc_an: bool):
    welt, a = auto(schluessel, 0.0, tc_an=tc_an)
    t, t100, ueberschuss = 0.0, None, 0.0
    kraft_summe, n = 0.0, 0
    while t < 10.0:
        schritt(welt, a, gas=1.0)
        t += DT
        if t <= 3.0:
            ueberschuss += a.physics.antriebs_ueberschuss * DT
        if t100 is None and a.speed * KMH_PER_PXS >= 100.0:
            t100 = t
    return ueberschuss / 3.0, t100 or float("nan"), a.speed * KMH_PER_PXS


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fahrzeug", nargs="*", default=["rookie", "supercar", "limousine", "drifter"])
    args = ap.parse_args(argv)
    print("== Bremsweg aus 150 km/h (Vollbremsung, geradeaus) ==")
    for k in args.fahrzeug:
        w0, t0, _ = bremsweg(k, False)
        w1, t1, _ = bremsweg(k, True)
        wb, a_max, a_gleit = blockiert_bezug(k)
        print(f"{k:10s} ohne ABS {w0:5.1f} m  mit ABS {w1:5.1f} m  "
              f"| Bezug blockiert (Gleitreibung {a_gleit / 9.81:.2f} g): {wb:5.1f} m")
    print("\n== Bremsen im Einschlag 0,5 aus 150 km/h ==")
    for k in args.fahrzeug:
        r0 = bremsweg(k, False, lenken=0.5)
        r1 = bremsweg(k, True, lenken=0.5)
        print(f"{k:10s} ohne ABS {r0[0]:5.1f} m (max. Schlupf {r0[2]:4.1f} Grad)   "
              f"mit ABS {r1[0]:5.1f} m ({r1[2]:4.1f} Grad)")
    print("\n== Anfahren, Vollgas: Durchdrehen (0-3 s) und 0-100 km/h ==")
    for k in args.fahrzeug:
        u0, t0, _ = anfahren(k, False)
        u1, t1, _ = anfahren(k, True)
        print(f"{k:10s} ohne TC {u0 * 100:4.0f} % verpufft, {t0:.2f} s   "
              f"mit TC {u1 * 100:4.0f} % verpufft, {t1:.2f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
