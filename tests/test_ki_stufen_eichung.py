"""Eichung der Stufen gegen Meister (Zielbänder aus dem Entwurf).

Langsam (~1–2 min): echte Physik, mehrere Runden je Stufe.
"""
from __future__ import annotations

import os
import sys

import pytest

import ki_hilfe as H

sys.path.insert(0, os.path.join(H.WURZEL, "tools"))
import ki_messung as M

BAENDER = {"easy": (0.10, 0.16), "medium": (0.04, 0.08), "hard": (0.015, 0.04)}


@pytest.mark.parametrize("strecke", ["gp", "city"])
def test_abstaende_der_stufen(strecke):
    pfad = os.path.join(H.WURZEL, "data", "tracks", f"{strecke}.json")
    meister = M.solo(pfad, "rookie", "expert", runden=3)
    assert meister["fertig"]
    for key, (unten, oben) in BAENDER.items():
        e = M.solo(pfad, "rookie", key, runden=3)
        assert e["fertig"], key
        abstand = e["beste"] / meister["beste"] - 1.0
        assert unten <= abstand <= oben, (key, round(abstand, 3))


def test_editorstrecken_ohne_haenger(tmp_path):
    for pfad in M.eigene_strecken(str(tmp_path)):
        for key in ("easy", "expert"):
            f = M.feld(pfad, key, ["rookie", "limousine", "supercar_2", "drifter"], runden=1)
            assert f["haenger"] == 0 and f["im_ziel"] == f["anzahl"], (pfad, key, f)
