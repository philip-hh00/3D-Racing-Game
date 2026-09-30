"""Festgefahren: das Auto muss sich aus der Wand lösen und weiterfahren."""
from __future__ import annotations

import math
import os
import sys

import ki_hilfe as H

sys.path.insert(0, os.path.join(H.WURZEL, "tools"))
import ki_messung as M


def _feststecker(strecke, seite, winkel_zur_strecke_grad):
    """Ein Auto steht mit der Nase an der Wand (seite=+1 links, -1 rechts)."""
    welt, track, bus = M._welt(os.path.join(H.WURZEL, "data", "tracks", f"{strecke}.json"))
    (auto,) = M._autos(welt, track, ["rookie"], "medium")
    st = auto.controller.fahrplan.strecke
    hf = auto.controller.fahrplan.halb_frei
    s = 300.0
    x, y = st.xy(s, seite * (hf + 4.0))
    i = st.index(s)
    tang = math.atan2(st.seg_dir[i][1], st.seg_dir[i][0])
    body = auto.physics.body
    body.position = (x, y)
    body.angle = tang + seite * math.radians(winkel_zur_strecke_grad)
    body.velocity = (0.0, 0.0)
    body.angular_velocity = 0.0
    auto.controller._hint = None
    auto.controller._start_measured = True      # keine Startspur-Haltung für ein umgesetztes Auto
    return welt, auto, st, hf


def test_rueckwaerts_nicht_in_ein_auto_dahinter():
    # Nase in der Wand, dicht dahinter steht ein zweites Auto: kein Rammen.
    welt, track, bus = M._welt(os.path.join(H.WURZEL, "data", "tracks", "gp.json"))
    a, b = M._autos(welt, track, ["rookie", "rookie_2"], "medium")
    st = a.controller.fahrplan.strecke
    hf = a.controller.fahrplan.halb_frei
    s = 300.0
    i = st.index(s)
    tang = math.atan2(st.seg_dir[i][1], st.seg_dir[i][0])
    kontakte = []
    bus.subscribe("impact_vehicle_vehicle", lambda d: kontakte.append(d))
    a.physics.body.position = st.xy(s, hf + 4.0)
    a.physics.body.angle = tang + math.radians(90.0)
    a.physics.body.velocity = (0.0, 0.0)
    b.physics.body.position = st.xy(s, hf + 4.0 - 85.0)     # 85 px hinter a, zur Streckenmitte
    b.physics.body.angle = tang + math.radians(90.0)
    b.physics.body.velocity = (0.0, 0.0)
    a.controller.opponents = [a, b]
    for auto in (a, b):
        auto.controller._hint = None
        auto.controller._start_measured = True
    kleinster = 1e9
    for _ in range(int(5.0 / M.DT)):
        a.update(M.DT)            # b bleibt als Hindernis stehen
        welt.step(M.DT)
        kleinster = min(kleinster, math.dist(a.position, b.position))
    assert not kontakte
    assert kleinster > 62.0


def _fahren(welt, auto, st, sekunden):
    t, s_vor, weg = 0.0, st.sd(*auto.position)[0], 0.0
    while t < sekunden:
        auto.update(M.DT)
        welt.step(M.DT)
        t += M.DT
        s = st.sd(*auto.position, hinweis=auto.controller._hint)[0]
        weg += st.ds(s_vor, s)
        s_vor = s
    return weg


def test_nase_quer_in_der_wand_kommt_frei():
    for strecke in ("gp", "city"):
        for seite in (1, -1):
            welt, auto, st, hf = _feststecker(strecke, seite, 80.0)
            weg = _fahren(welt, auto, st, 8.0)
            assert weg > 150.0, (strecke, seite, weg)


def test_feld_in_der_stadt_ohne_haenger_und_mit_wenig_wandkontakt():
    # Sechs Autos, zwei Runden, Stufe Meister: früher blieben hier drei Autos in der
    # Wand hängen (Rückwärtsgang fehlte, Ausweichbahnen bis 6 px an die Wand).
    erg = M.feld(os.path.join(H.WURZEL, "data", "tracks", "city.json"), "expert",
                 M.FELD_AUTOS, runden=2)
    assert erg["im_ziel"] == erg["anzahl"]
    assert erg["haenger"] == 0
    assert erg["wand"] <= 12
