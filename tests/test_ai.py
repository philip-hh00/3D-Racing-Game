"""Der KI-Fahrer im echten Physikmodell: Runden, Ausweichen, Wiederholbarkeit.

Ersetzt die Tests der alten Schienen-KI (bis 30.09.2026).
"""
from __future__ import annotations

import math

import ki_hilfe as H
from src.ai.stufen import STUFEN
from src.core.event_bus import EventBus
from src.physics.collision_handler import CollisionHandler
from src.physics.physics_world import PhysicsWorld

DT = 1.0 / 60.0


def _feld(track_fabrik, autos, stufe_key="hard", tmp_path=None):
    from src.entities.vehicle_factory import VehicleFactory
    welt = PhysicsWorld()
    track = track_fabrik(welt.space)
    CollisionHandler(welt.space, EventBus())
    H.config("rookie")
    feld = []
    starts = track.get_start_positions()
    for i, key in enumerate(autos):
        sp = starts[i % len(starts)]
        ai = VehicleFactory.create_ai_vehicle(key, i + 1, sp.pos, math.radians(sp.angle),
                                              welt.space, track, STUFEN[stufe_key])
        ai.ai_active = True
        feld.append(ai)
    for ai in feld:
        ai.controller.opponents = feld
        ai.controller.vorbereiten()
    return welt, track, feld


def _fahren(welt, feld, sekunden):
    st = feld[0].controller.fahrplan.strecke
    weg = [0.0] * len(feld)
    vorher = [st.sd(*a.position)[0] for a in feld]
    for _ in range(int(sekunden / DT)):
        for a in feld:
            a.update(DT)
        welt.step(DT)
        for i, a in enumerate(feld):
            s = st.sd(*a.position, hinweis=a.controller._hint)[0]
            weg[i] += st.ds(vorher[i], s)
            vorher[i] = s
    return weg, st


def test_eine_runde_auf_dem_oval():
    welt, track, feld = _feld(lambda sp: H.strecke_laden("oval", sp), ["rookie"])
    weg, st = _fahren(welt, feld, 45.0)
    assert weg[0] > st.laenge


def test_frische_editorstrecke_ohne_vorbereitung(tmp_path):
    welt, track, feld = _feld(lambda sp: H.eigene_strecke(tmp_path, sp), ["supercar"], "expert")
    weg, st = _fahren(welt, feld, 60.0)
    assert weg[0] > st.laenge


def test_ueberholt_ein_stehendes_auto():
    welt, track, feld = _feld(lambda sp: H.strecke_laden("oval", sp), ["rookie", "rookie"])
    stehend, fahrend = feld[0], feld[1]   # Startplatz 1 (vorn) steht, Startplatz 2 fährt
    stehend.ai_active = False
    weg, st = _fahren(welt, [fahrend, stehend], 25.0)
    assert weg[0] > weg[1] + 1000.0


def test_gleiche_startnummer_gleiche_eingaben():
    ergebnisse = []
    for _ in range(2):
        welt, track, feld = _feld(lambda sp: H.strecke_laden("gp", sp), ["drifter"], "easy")
        eingaben = []
        for _ in range(int(8.0 / DT)):
            eingaben.append(feld[0].controller.compute_inputs(DT))
            feld[0].throttle, feld[0].brake_input, feld[0].steer_input = eingaben[-1]
            from src.entities.vehicle import Vehicle
            Vehicle.update(feld[0], DT)
            welt.step(DT)
        ergebnisse.append(eingaben)
    assert ergebnisse[0] == ergebnisse[1]


def test_alte_stufennamen_gehen():
    from src.ai.ai_controller import AIController
    welt, track, feld = _feld(lambda sp: H.strecke_laden("oval", sp), ["rookie"])
    ctrl = AIController(feld[0], track, "Schwer")
    assert ctrl.difficulty is STUFEN["hard"]


def test_planen_ist_je_auto_versetzt():
    welt, track, feld = _feld(lambda sp: H.strecke_laden("oval", sp), ["rookie", "rookie"])
    assert feld[0].id % 6 != feld[1].id % 6
    bilder = [[], []]
    for i, a in enumerate(feld):
        orig = a.controller._planer.planen
        bild = [0]

        def spion(*args, _o=orig, _l=bilder[i], _b=bild, **kw):
            _l.append(_b[0])
            return _o(*args, **kw)
        a.controller._planer.planen = spion
        a.controller._bild = bild
    for n in range(int(0.5 / DT)):
        for a in feld:
            a.controller._bild[0] = n
            a.update(DT)
        welt.step(DT)
    assert len(bilder[0]) >= 4 and len(bilder[1]) >= 4
    assert set(bilder[0]) != set(bilder[1])
    assert not (set(bilder[0]) & set(bilder[1]) == set(bilder[0]))
