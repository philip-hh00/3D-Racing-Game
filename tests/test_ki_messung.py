"""Mess-Werkzeug der KI: läuft ohne Grafik und liefert plausible Zahlen."""
from __future__ import annotations

import ki_hilfe as H
import os
import sys

sys.path.insert(0, os.path.join(H.WURZEL, "tools"))
import ki_messung as M


def test_solo_auf_dem_oval():
    erg = M.solo(os.path.join(H.WURZEL, "data/tracks/oval.json"), "rookie", "hard", runden=2)
    assert erg["fertig"]
    assert len(erg["runden"]) == 2
    assert 5.0 < erg["beste"] < 60.0


def test_feld_kommt_ins_ziel():
    erg = M.feld(os.path.join(H.WURZEL, "data/tracks/oval.json"), "medium",
                 ["rookie", "rookie_2", "limousine", "electric"], runden=1)
    assert erg["anzahl"] == 4
    assert erg["im_ziel"] == 4
    assert erg["haenger"] == 0


def test_eigene_strecken(tmp_path):
    pfade = M.eigene_strecken(str(tmp_path))
    assert len(pfade) == 2 and all(os.path.isfile(p) for p in pfade)
