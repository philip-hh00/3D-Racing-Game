"""KI-Messung: Stufen und Zweikampf ohne Grafik, schneller als Echtzeit.

    .venv/Scripts/python.exe tools/ki_messung.py --strecken oval,gp,city --auto rookie --runden 3
    .venv/Scripts/python.exe tools/ki_messung.py --feld --eigene

Solo: je Stufe beste Runde (ab Runde 2, fliegend) und Abstand zu Meister.
Feld: gemischtes Feld je Stufe — Überholungen, Kontakte, Hänger, Zieleinläufe.
Grundlage zum Eichen von ``src/ai/stufen.py``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WURZEL)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

DT = 1.0 / 60.0
FELD_AUTOS = ["rookie", "rookie_2", "limousine", "electric", "supercar_2", "drifter"]


def _welt(pfad):
    from src.core.event_bus import EventBus
    from src.physics.collision_handler import CollisionHandler
    from src.physics.physics_world import PhysicsWorld
    from src.track.track import Track
    from src.entities.vehicle_factory import VehicleFactory
    if not VehicleFactory.get_all_keys():
        VehicleFactory.load_all_configs(os.path.join(WURZEL, "data", "vehicles"))
    welt = PhysicsWorld()
    track = Track(pfad, welt.space)
    bus = EventBus()
    CollisionHandler(welt.space, bus)
    return welt, track, bus


def _autos(welt, track, keys, stufe_key):
    from src.ai.stufen import stufe
    from src.entities.vehicle_factory import VehicleFactory
    starts = track.get_start_positions()
    feld = []
    for i, key in enumerate(keys):
        sp = starts[i % len(starts)]
        ai = VehicleFactory.create_ai_vehicle(key, i + 1, sp.pos, math.radians(sp.angle),
                                              welt.space, track, stufe(stufe_key))
        ai.ai_active = True
        feld.append(ai)
    for ai in feld:
        ai.controller.opponents = feld
        ai.controller.vorbereiten()
    return feld


def solo(pfad, auto, stufe_key, runden=3, zeitlimit=400.0):
    welt, track, bus = _welt(pfad)
    (ai,) = _autos(welt, track, [auto], stufe_key)
    st = ai.controller.fahrplan.strecke
    wand = [0]
    koerper = id(ai.physics.body)
    bus.subscribe("impact_vehicle_wall",
                  lambda dt_: wand.__setitem__(0, wand[0] + (dt_.get("vehicle_body_id") == koerper)))
    s_vor = st.sd(*ai.position)[0]
    weg, t, marke, zeiten, letzte = 0.0, 0.0, st.laenge, [], 0.0
    while len(zeiten) < runden and t < zeitlimit:
        ai.update(DT)
        welt.step(DT)
        t += DT
        s = st.sd(*ai.position, hinweis=ai.controller._hint)[0]
        weg += st.ds(s_vor, s)
        s_vor = s
        if weg >= marke:
            zeiten.append(t - letzte)
            letzte = t
            marke += st.laenge
    fliegend = zeiten[1:] or zeiten
    return {"runden": zeiten, "beste": min(fliegend) if fliegend else None,
            "wand": wand[0], "fertig": len(zeiten) >= runden}


def feld(pfad, stufe_key, autos, runden=2, zeitlimit=400.0):
    welt, track, bus = _welt(pfad)
    wagen = _autos(welt, track, autos, stufe_key)
    st = wagen[0].controller.fahrplan.strecke
    zaehler = {"wand": 0, "auto": 0}
    bus.subscribe("impact_vehicle_wall", lambda d: zaehler.__setitem__("wand", zaehler["wand"] + 1))
    bus.subscribe("impact_vehicle_vehicle", lambda d: zaehler.__setitem__("auto", zaehler["auto"] + 1))
    s_vor = [st.sd(*a.position)[0] for a in wagen]
    weg = [0.0] * len(wagen)
    ziel = runden * st.laenge
    stand = [0.0] * len(wagen)          # Zeit ohne Fortschritt
    haenger = set()
    reihenfolge = None
    ueberholungen = 0
    t = 0.0
    while t < zeitlimit and min(weg) < ziel:
        for a in wagen:
            if weg[wagen.index(a)] < ziel:
                a.update(DT)
        welt.step(DT)
        t += DT
        for i, a in enumerate(wagen):
            s = st.sd(*a.position, hinweis=a.controller._hint)[0]
            schritt = st.ds(s_vor[i], s)
            weg[i] += schritt
            s_vor[i] = s
            stand[i] = 0.0 if schritt > 20.0 * DT else stand[i] + DT
            if stand[i] > 5.0 and weg[i] < ziel:
                haenger.add(i)
        if t > 5.0:
            neu = sorted(range(len(wagen)), key=lambda i: -weg[i])
            if reihenfolge is not None:
                ueberholungen += sum(1 for a, b in zip(reihenfolge, neu) if a != b) // 2
            reihenfolge = neu
    return {"ueberholungen": ueberholungen, "auto_kontakte": zaehler["auto"],
            "wand": zaehler["wand"], "haenger": len(haenger),
            "im_ziel": sum(1 for w in weg if w >= ziel), "anzahl": len(wagen)}


def eigene_strecken(ordner):
    from src.track.track_builder import TrackDefinition
    formen = {
        "ki_eigen_kehren": [(0, 0), (2600, 0), (3400, 600), (3400, 1500), (2500, 2100),
                            (1700, 1800), (900, 2100), (0, 1600), (-500, 800)],
        "ki_eigen_schnell": [(0, 0), (4200, 0), (5200, 900), (4800, 2200), (2600, 2600),
                             (600, 2300), (-600, 1200)],
    }
    pfade = []
    os.makedirs(ordner, exist_ok=True)
    for name, punkte in formen.items():
        defn = TrackDefinition(name=name, control_points=[(float(x), float(y)) for x, y in punkte],
                               width=270.0)
        fehler = defn.validate()
        if fehler:
            raise ValueError(f"{name}: {[f.message for f in fehler]}")
        pfad = os.path.join(ordner, f"{name}.json")
        with open(pfad, "w", encoding="utf-8") as fh:
            json.dump(defn.to_json(), fh)
        pfade.append(pfad)
    return pfade


def main() -> None:
    from src.ai.stufen import REIHE, STUFEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--strecken", default="oval,gp,city,desert,mountain")
    ap.add_argument("--auto", default="rookie")
    ap.add_argument("--runden", type=int, default=3)
    ap.add_argument("--feld", action="store_true")
    ap.add_argument("--eigene", action="store_true")
    a = ap.parse_args()
    pfade = [os.path.join(WURZEL, "data", "tracks", f"{n}.json") for n in a.strecken.split(",") if n]
    if a.eigene:
        import tempfile
        pfade += eigene_strecken(tempfile.mkdtemp(prefix="ki_messung_"))
    for pfad in pfade:
        name = os.path.splitext(os.path.basename(pfad))[0]
        ergebnisse = {k: solo(pfad, a.auto, k, a.runden) for k in REIHE}
        meister = ergebnisse["expert"]["beste"]
        for k in REIHE:
            e = ergebnisse[k]
            prozent = (e["beste"] / meister - 1.0) * 100.0 if e["beste"] and meister else float("nan")
            print(f"{name:18s} {STUFEN[k].name:16s} beste {e['beste'] or 0:6.2f}s "
                  f"{prozent:+6.1f}%  Wand {e['wand']:3d}  {'ok' if e['fertig'] else 'NICHT FERTIG'}")
        if a.feld:
            for k in REIHE:
                f = feld(pfad, k, FELD_AUTOS)
                print(f"{name:18s} {STUFEN[k].name:16s} Feld: {f}")


if __name__ == "__main__":
    main()
