"""Fahrplan: Ideallinie und Zieltempo je Stufe, auf jeder Strecke sofort."""
from __future__ import annotations

import numpy as np
import pytest

import ki_hilfe as H
from src.ai.fahrplan import fahrplan_bauen
from src.ai.stufen import STUFEN


@pytest.mark.parametrize("name", ["oval", "gp", "city"])
def test_fahrplan_auf_mitgelieferten_strecken(name):
    track = H.strecke_laden(name)
    plan = fahrplan_bauen(track, H.config("rookie"), STUFEN["hard"])
    n = plan.strecke.n
    assert len(plan.d_ideal) == len(plan.v_ziel) == len(plan.kruemmung) == n
    assert np.all(np.abs(plan.d_ideal) <= plan.halb_frei + 1.0)
    assert np.all(plan.v_ziel > 20.0)
    assert plan.a_brems > 0
    # in Kurven langsamer als auf der schnellsten Geraden
    assert plan.v_ziel.min() < 0.8 * plan.v_ziel.max()


def test_frische_editorstrecke(tmp_path):
    track = H.eigene_strecke(tmp_path)
    plan = fahrplan_bauen(track, H.config("supercar"), STUFEN["expert"])
    assert plan.strecke.laenge > 5000
    assert np.all(np.isfinite(plan.v_ziel))


def test_zwischenwerte_und_zwischenspeicher():
    track = H.strecke_laden("oval")
    a = fahrplan_bauen(track, H.config("rookie"), STUFEN["medium"])
    b = fahrplan_bauen(track, H.config("rookie"), STUFEN["medium"])
    assert a is b
    s = a.strecke.s[5] + 0.5 * a.strecke.seg_len[5]
    assert a.v_bei(s) == pytest.approx(0.5 * (a.v_ziel[5] + a.v_ziel[6]))
    assert a.v_viele(np.array([s]))[0] == pytest.approx(a.v_bei(s))


def test_meister_schneller_als_anfaenger():
    track = H.strecke_laden("gp")
    langsam = fahrplan_bauen(track, H.config("rookie"), STUFEN["easy"])
    schnell = fahrplan_bauen(track, H.config("rookie"), STUFEN["expert"])
    assert langsam.v_ziel.mean() < 0.95 * schnell.v_ziel.mean()


def _eigene_neu_schreiben(tmp_path, aendern):
    """Wie der Editor: dieselbe JSON-Datei wird mit gleicher Punktzahl neu veröffentlicht."""
    import json
    import os
    import pymunk
    from src.track.track import Track
    track = H.eigene_strecke(tmp_path)
    pfad = os.path.join(str(tmp_path), "ki_test.json")
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    aendern(daten)
    with open(pfad, "w", encoding="utf-8") as fh:
        json.dump(daten, fh)
    return track, Track(pfad, pymunk.Space())


def test_neu_veroeffentlichte_strecke_gleicher_pfad_neuer_plan(tmp_path):
    def breiter(daten):
        daten["track_width"] = float(daten["track_width"]) + 40.0
    alt, neu = _eigene_neu_schreiben(tmp_path, breiter)
    assert alt.json_path == neu.json_path and len(alt.centerline) == len(neu.centerline)
    a = fahrplan_bauen(alt, H.config("rookie"), STUFEN["hard"])
    b = fahrplan_bauen(neu, H.config("rookie"), STUFEN["hard"])
    assert a is not b
    assert b.strecke.halb > a.strecke.halb


def test_geaenderte_punkte_gleicher_pfad_neuer_plan(tmp_path):
    def verschieben(daten):
        daten["centerline"][3]["x"] += 60.0
    alt, neu = _eigene_neu_schreiben(tmp_path, verschieben)
    assert len(alt.centerline) == len(neu.centerline)
    a = fahrplan_bauen(alt, H.config("rookie"), STUFEN["hard"])
    b = fahrplan_bauen(neu, H.config("rookie"), STUFEN["hard"])
    assert a is not b
    assert not np.allclose(a.strecke.xy_viele(np.array([2000.0]), np.array([0.0])),
                           b.strecke.xy_viele(np.array([2000.0]), np.array([0.0])))


def test_fahrzeugwerte_in_place_geaendert_neuer_plan():
    import copy
    track = H.strecke_laden("oval")
    cfg = copy.copy(H.config("rookie"))
    a = fahrplan_bauen(track, cfg, STUFEN["hard"])
    cfg.grip = cfg.grip * 0.7
    b = fahrplan_bauen(track, cfg, STUFEN["hard"])
    assert a is not b
    assert b.v_ziel.mean() < a.v_ziel.mean()
