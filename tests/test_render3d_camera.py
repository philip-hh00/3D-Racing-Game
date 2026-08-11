"""Tests fuer die Kameramathematik (src/render3d/camera.py).

Reine lineare Algebra: keine pygame-, keine OpenGL-Abhaengigkeit. Die
Konventionen (Koordinatensystem, Matrixform, Einheiten) stehen bindend in
``src/render3d/VEREINBARUNGEN.md``.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.render3d.camera import Verfolgerkamera, blick, perspektive


# ---------------------------------------------------------------------------
# perspektive()
# ---------------------------------------------------------------------------

def test_perspektive_bildet_nahe_ebene_auf_clip_z_gleich_minus_w_ab():
    p = perspektive(fov_grad=60.0, seitenverhaeltnis=16 / 9, nah_m=0.1, fern_m=1000.0)
    punkt_blickraum = np.array([0.0, 0.0, -0.1, 1.0], dtype=np.float32)  # auf der nahen Ebene
    clip = p @ punkt_blickraum
    assert math.isclose(clip[2], -clip[3], rel_tol=1e-5, abs_tol=1e-5)
    assert math.isclose(clip[2] / clip[3], -1.0, rel_tol=1e-5, abs_tol=1e-5)


def test_perspektive_bildet_ferne_ebene_auf_clip_z_gleich_plus_w_ab():
    p = perspektive(fov_grad=60.0, seitenverhaeltnis=16 / 9, nah_m=0.1, fern_m=1000.0)
    punkt_blickraum = np.array([0.0, 0.0, -1000.0, 1.0], dtype=np.float32)  # auf der fernen Ebene
    clip = p @ punkt_blickraum
    assert math.isclose(clip[2], clip[3], rel_tol=1e-5, abs_tol=1e-5)
    assert math.isclose(clip[2] / clip[3], 1.0, rel_tol=1e-5, abs_tol=1e-5)


def test_perspektive_liefert_4x4_float32():
    p = perspektive(fov_grad=60.0, seitenverhaeltnis=16 / 9, nah_m=0.1, fern_m=1000.0)
    assert p.shape == (4, 4)
    assert p.dtype == np.float32


# ---------------------------------------------------------------------------
# blick()
# ---------------------------------------------------------------------------

def test_blick_liefert_orthonormale_rotation_mit_determinante_eins():
    v = blick(auge=(0.0, 0.0, 2.0), ziel=(5.0, 1.0, 0.0))
    rotation = v[:3, :3].astype(np.float64)
    identitaet = rotation @ rotation.T
    assert np.allclose(identitaet, np.eye(3), atol=1e-5)
    assert math.isclose(np.linalg.det(rotation), 1.0, abs_tol=1e-4)


def test_blick_punkt_vor_der_kamera_hat_negatives_z():
    # Kamera im Ursprung, blickt entlang +X der Welt.
    v = blick(auge=(0.0, 0.0, 0.0), ziel=(1.0, 0.0, 0.0))
    punkt_vorne = np.array([5.0, 0.0, 0.0, 1.0], dtype=np.float32)  # liegt vor der Kamera
    punkt_blickraum = v @ punkt_vorne
    assert punkt_blickraum[2] < 0.0


def test_blick_punkt_hinter_der_kamera_hat_positives_z():
    v = blick(auge=(0.0, 0.0, 0.0), ziel=(1.0, 0.0, 0.0))
    punkt_hinten = np.array([-5.0, 0.0, 0.0, 1.0], dtype=np.float32)
    punkt_blickraum = v @ punkt_hinten
    assert punkt_blickraum[2] > 0.0


def test_blick_liefert_4x4_float32():
    v = blick(auge=(0.0, 0.0, 2.0), ziel=(5.0, 1.0, 0.0))
    assert v.shape == (4, 4)
    assert v.dtype == np.float32


def _pruefe_endliche_orthonormale_matrix(v: np.ndarray) -> None:
    assert np.all(np.isfinite(v))
    rotation = v[:3, :3].astype(np.float64)
    assert np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-5)
    assert math.isclose(np.linalg.det(rotation), 1.0, abs_tol=1e-4)


def test_blick_senkrecht_nach_unten_bei_paralleler_oben_richtung_bleibt_endlich():
    # vorwaerts = (0,0,-1), Vorgabe-oben = (0,0,1): antiparallel, cross() = 0.
    v = blick(auge=(0.0, 0.0, 5.0), ziel=(0.0, 0.0, 0.0))
    _pruefe_endliche_orthonormale_matrix(v)


def test_blick_senkrecht_nach_oben_bei_paralleler_oben_richtung_bleibt_endlich():
    # vorwaerts = (0,0,1), Vorgabe-oben = (0,0,1): parallel, cross() = 0.
    v = blick(auge=(0.0, 0.0, 0.0), ziel=(0.0, 0.0, 5.0))
    _pruefe_endliche_orthonormale_matrix(v)


# ---------------------------------------------------------------------------
# Verfolgerkamera
# ---------------------------------------------------------------------------

def test_verfolgerkamera_setzen_bei_gierwinkel_null_steht_hinter_fahrzeug():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    assert np.allclose(kamera.auge, [-8.0, 0.0, 3.0], atol=1e-5)
    assert np.allclose(kamera.ziel, [0.0, 0.0, 1.0], atol=1e-5)


def test_verfolgerkamera_setzen_bei_gierwinkel_90grad_ist_entsprechend_gedreht():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=math.pi / 2)
    assert np.allclose(kamera.auge, [0.0, -8.0, 3.0], atol=1e-5)
    assert np.allclose(kamera.ziel, [0.0, 0.0, 1.0], atol=1e-5)


def test_verfolgerkamera_setzen_beruecksichtigt_fahrzeugposition():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(fahrzeug_pos_m=(10.0, 20.0, 0.0), gierwinkel_rad=0.0)
    assert np.allclose(kamera.auge, [2.0, 20.0, 3.0], atol=1e-5)
    assert np.allclose(kamera.ziel, [10.0, 20.0, 1.0], atol=1e-5)


def test_verfolgerkamera_setzen_springt_sofort():
    kamera = Verfolgerkamera()
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    erstes_auge = np.array(kamera.auge, copy=True)
    # Fahrzeug ist weit weggesprungen (z.B. Rennstart auf neuer Position).
    kamera.setzen(fahrzeug_pos_m=(100.0, 0.0, 0.0), gierwinkel_rad=0.0)
    assert not np.allclose(kamera.auge, erstes_auge)
    assert np.allclose(kamera.auge, [92.0, 0.0, 3.0], atol=1e-5)


def test_verfolgerkamera_folgen_naehert_sich_an_ohne_sofort_anzukommen():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0, weichheit=4.0)
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    ziel_auge = np.array([92.0, 0.0, 3.0])

    kamera.folgen(fahrzeug_pos_m=(100.0, 0.0, 0.0), gierwinkel_rad=0.0, dt=0.1)

    abstand_vorher = np.linalg.norm(np.array([-8.0, 0.0, 3.0]) - ziel_auge)
    abstand_nachher = np.linalg.norm(np.array(kamera.auge) - ziel_auge)
    assert abstand_nachher < abstand_vorher
    assert abstand_nachher > 1e-6  # noch nicht angekommen


def test_verfolgerkamera_folgen_naehert_sich_im_lauf_der_zeit_beliebig_nah_an():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0, weichheit=4.0)
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    for _ in range(500):
        kamera.folgen(fahrzeug_pos_m=(100.0, 0.0, 0.0), gierwinkel_rad=0.0, dt=1 / 60)
    assert np.allclose(kamera.auge, [92.0, 0.0, 3.0], atol=1e-3)
    assert np.allclose(kamera.ziel, [100.0, 0.0, 1.0], atol=1e-3)


def test_verfolgerkamera_folgen_ist_rahmenratenunabhaengig():
    """100 Schritte a 0,01s muessen praktisch am selben Ort landen wie 10 Schritte a 0,1s.

    Beide simulieren dieselbe Zeitspanne (1s) mit demselben, unveraenderlichen
    Ziel. Die Exponentialglaettung x' = ziel + (x - ziel) * exp(-weichheit*dt)
    komponiert exakt: exp(-k*dt1) * exp(-k*dt2) == exp(-k*(dt1+dt2)). Die
    Toleranz von 1e-6 deckt nur noch Rundungsfehler der Gleitkomma-Arithmetik
    ab (verschiedene Anzahl Multiplikationen in float64), keine methodischen
    Abweichungen.
    """
    kamera_fein = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0, weichheit=4.0)
    kamera_grob = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0, weichheit=4.0)
    kamera_fein.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    kamera_grob.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)

    ziel_fahrzeug = (100.0, 30.0, 0.0)
    for _ in range(100):
        kamera_fein.folgen(fahrzeug_pos_m=ziel_fahrzeug, gierwinkel_rad=0.3, dt=0.01)
    for _ in range(10):
        kamera_grob.folgen(fahrzeug_pos_m=ziel_fahrzeug, gierwinkel_rad=0.3, dt=0.1)

    assert np.allclose(kamera_fein.auge, kamera_grob.auge, atol=1e-6)
    assert np.allclose(kamera_fein.ziel, kamera_grob.ziel, atol=1e-6)


def test_verfolgerkamera_folgen_mit_dt_null_aendert_nichts():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0, weichheit=4.0)
    kamera.setzen(fahrzeug_pos_m=(0.0, 0.0, 0.0), gierwinkel_rad=0.0)
    auge_vorher = np.array(kamera.auge, copy=True)
    ziel_vorher = np.array(kamera.ziel, copy=True)

    kamera.folgen(fahrzeug_pos_m=(100.0, 50.0, 0.0), gierwinkel_rad=1.2, dt=0.0)

    assert np.array_equal(kamera.auge, auge_vorher)
    assert np.array_equal(kamera.ziel, ziel_vorher)


def test_verfolgerkamera_blickmatrix_stimmt_mit_blick_ueberein():
    kamera = Verfolgerkamera(abstand_m=8.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(fahrzeug_pos_m=(3.0, 4.0, 0.0), gierwinkel_rad=0.5)
    erwartet = blick(kamera.auge, kamera.ziel)
    assert np.allclose(kamera.blickmatrix(), erwartet, atol=1e-5)
    assert kamera.blickmatrix().shape == (4, 4)
    assert kamera.blickmatrix().dtype == np.float32
