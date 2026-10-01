"""Startplatz-Markierungen im 3D-Netz: jeder belegte Platz hat eine, auf der Fahrbahn.

Gemeldet: bei mehreren Fahrzeugen sind die Startplaetze nicht auf der Strasse
markiert. Ursache: das Netz las nur die (4) in der Streckendatei gespeicherten
Plaetze, das Spiel setzt aber bis zu ``FELD_MAX`` (8) Fahrzeuge auf das aus der
Mittellinie ergaenzte Gitter von ``Track``.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pymunk
import pytest

from src.core.race_setup import FELD_MAX
from src.core.settings import M_PER_PX
from src.render3d import track_mesh
from src.track.track import Track

STRECKEN = sorted((Path(__file__).resolve().parents[1] / "data" / "tracks").glob("*.json"))


def _editor_strecke(tmp_path) -> Path:
    """Eine Strecke wie aus dem Editor: Start-Plaetze aus ``build_start_positions``."""
    from src.track.track_builder import build_start_positions
    pfad = STRECKEN[0]
    d = json.loads(pfad.read_text(encoding="utf-8"))
    cl = [(p["x"], p["y"]) if isinstance(p, dict) else tuple(p) for p in d["centerline"]]
    d["start_positions"] = build_start_positions(cl, d["track_width"], count=4)
    ziel = tmp_path / "editor.json"
    ziel.write_text(json.dumps(d), encoding="utf-8")
    return ziel


def _pruefen(pfad: Path) -> None:
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    netz = track_mesh.bauen(daten)
    track = Track(str(pfad), pymunk.Space())
    slots = track.get_start_positions()[:FELD_MAX]
    assert len(slots) == FELD_MAX
    assert len(netz.start_positionen) >= len(slots)
    mitte = np.asarray(netz.mittellinie)
    for slot, (x, y, winkel) in zip(slots, netz.start_positionen):
        # stimmt mit dem Platz ueberein, auf dem das Auto wirklich steht
        assert x == pytest.approx(slot.x * M_PER_PX, abs=0.01)
        assert y == pytest.approx(slot.y * M_PER_PX, abs=0.01)
        assert math.cos(winkel - math.radians(slot.angle)) > 0.999
        # und liegt auf der Fahrbahn (Querabstand zur Mittellinie < halbe Breite)
        quer = np.hypot(mitte[:, 0] - x, mitte[:, 1] - y).min()
        assert quer < netz.halbe_breite_m


@pytest.mark.parametrize("pfad", STRECKEN, ids=lambda p: p.stem)
def test_markierung_je_platz_bei_mitgelieferten_strecken(pfad):
    _pruefen(pfad)


def test_markierung_je_platz_bei_editor_strecke(tmp_path):
    _pruefen(_editor_strecke(tmp_path))
