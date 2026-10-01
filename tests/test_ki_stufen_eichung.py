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

#: Kompaktwagen auf gp/city; schnelle Strecken und starke Autos liegen darunter
#: (nur die Untergrenze zählt dort, siehe ``MINDEST``).
BAENDER = {"easy": (0.12, 0.23), "medium": (0.06, 0.12), "hard": (0.025, 0.065)}
MINDEST = {"easy": 0.12, "medium": 0.06, "hard": 0.025}

_CACHE: dict = {}


def _solo(pfad, auto, key):
    """Gleiche Läufe nicht doppelt fahren (Meister dient mehreren Tests)."""
    if (pfad, auto, key) not in _CACHE:
        _CACHE[(pfad, auto, key)] = M.solo(pfad, auto, key, runden=3)
    return _CACHE[(pfad, auto, key)]


@pytest.mark.parametrize("strecke", ["gp", "city"])
def test_abstaende_der_stufen(strecke):
    pfad = os.path.join(H.WURZEL, "data", "tracks", f"{strecke}.json")
    meister = _solo(pfad, "rookie", "expert")
    assert meister["fertig"]
    for key, (unten, oben) in BAENDER.items():
        e = _solo(pfad, "rookie", key)
        assert e["fertig"], key
        abstand = e["beste"] / meister["beste"] - 1.0
        assert unten <= abstand <= oben, (key, round(abstand, 3))


def test_meister_nahe_an_der_menschenrunde():
    """city, Kompaktwagen: beste Menschenrunde des Besitzers 22,09 s (1.10.2026);
    Meister soll höchstens 5 % darüber liegen (vorher 28,3 s), ohne Wandkontakt."""
    pfad = os.path.join(H.WURZEL, "data", "tracks", "city.json")
    meister = _solo(pfad, "rookie", "expert")
    assert meister["fertig"] and meister["wand"] == 0
    assert 22.09 * 0.9 <= meister["beste"] <= 22.09 * 1.05, meister["beste"]


def test_stufen_trennen_sich_auch_mit_starkem_auto_auf_schneller_strecke(tmp_path):
    """Die Lücken kommen nicht nur aus engen Kehren: Supercar und Limousine auf der
    schnellen Editorstrecke müssen sich ebenfalls deutlich staffeln."""
    pfad = next(p for p in M.eigene_strecken(str(tmp_path)) if "schnell" in p)
    for auto in ("supercar", "limousine_2"):
        meister = _solo(pfad, auto, "expert")
        assert meister["fertig"]
        letzter = 0.0
        for key in ("hard", "medium", "easy"):
            e = _solo(pfad, auto, key)
            assert e["fertig"], (auto, key)
            abstand = e["beste"] / meister["beste"] - 1.0
            assert abstand >= MINDEST[key], (auto, key, round(abstand, 3))
            assert abstand > letzter, (auto, key)
            letzter = abstand


def test_editorstrecken_ohne_haenger(tmp_path):
    for pfad in M.eigene_strecken(str(tmp_path)):
        for key in ("easy", "expert"):
            f = M.feld(pfad, key, ["rookie", "limousine", "supercar_2", "drifter"], runden=1)
            assert f["haenger"] == 0 and f["im_ziel"] == f["anzahl"], (pfad, key, f)
