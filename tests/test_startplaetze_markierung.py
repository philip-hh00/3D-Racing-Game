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


def _slots(daten: dict, tmp_path) -> tuple[list, list]:
    pfad = tmp_path / "beschaedigt.json"
    pfad.write_text(json.dumps(daten), encoding="utf-8")
    track = Track(str(pfad), pymunk.Space())
    netz = track_mesh.bauen(daten)
    a = [(s.x, s.y, s.angle) for s in track.get_start_positions()]
    b = [(x / M_PER_PX, y / M_PER_PX, math.degrees(w)) for x, y, w in netz.start_positionen]
    return a, b


def test_vier_gespeicherte_werden_acht_im_netz():
    from src.track.track_builder import start_gitter
    d = json.loads(STRECKEN[0].read_text(encoding="utf-8"))
    assert len(d["start_positions"]) == 4
    assert len(start_gitter(d["start_positions"], d["centerline"], d["track_width"])) == FELD_MAX
    assert len(track_mesh.bauen(d).start_positionen) == FELD_MAX


def test_track_und_netz_gleich_bei_beschaedigtem_slot(tmp_path):
    d = json.loads(STRECKEN[0].read_text(encoding="utf-8"))
    d["start_positions"] = [dict(d["start_positions"][0]) for _ in range(FELD_MAX)]
    d["start_positions"][3] = {"x": "kaputt", "y": None}
    a, b = _slots(d, tmp_path)
    assert len(a) == len(b) == FELD_MAX
    assert np.allclose(np.asarray(a), np.asarray(b), atol=1e-6)


def test_track_und_netz_gleich_bei_unbrauchbarer_breite(tmp_path):
    d = json.loads(STRECKEN[0].read_text(encoding="utf-8"))
    d["track_width"] = "viel"
    a, b = _slots(d, tmp_path)   # weder Track noch Netz brechen ab
    assert len(a) == len(b) == FELD_MAX
    assert np.allclose(np.asarray(a), np.asarray(b), atol=1e-6)


def test_markierung_je_platz_bei_editor_strecke(tmp_path):
    _pruefen(_editor_strecke(tmp_path))
