"""Die Matrizenhelfer sind schneller, rechnen aber bitgleich wie vorher."""
import math
import random

import numpy as np

from src.render3d import matrix


def _alt_einheit():
    return np.eye(4, dtype=np.float32)


def _alt_drehung(achse, winkel):
    c, s = np.cos(winkel), np.sin(winkel)
    m = _alt_einheit()
    i, j = [(1, 2), (2, 0), (0, 1)][achse]
    m[i, i] = c
    m[i, j] = -s
    m[j, i] = s
    m[j, j] = c
    return m


def test_einheit_ist_jedes_mal_ein_neues_feld():
    a = matrix.einheit()
    a[0, 0] = 5.0
    assert matrix.einheit()[0, 0] == 1.0
    assert matrix.einheit().dtype == np.float32


def test_drehungen_sind_bitgleich_wie_vorher():
    zufall = random.Random(11)
    winkel = [0.0, math.pi, -math.pi / 2, 1e-9, 7.5] + [zufall.uniform(-20, 20) for _ in range(5000)]
    for w in winkel:
        for achse, f in enumerate((matrix.drehung_x, matrix.drehung_y, matrix.drehung_z)):
            assert np.array_equal(f(w), _alt_drehung(achse, w)), (achse, w)
            assert f(w).dtype == np.float32


def test_verschiebung_wie_vorher():
    m = matrix.verschiebung(1.0, 2.0, 3.0)
    assert np.array_equal(m[:3, 3], np.array([1, 2, 3], np.float32))
    assert np.array_equal(matrix.verschiebung((4.0, 5.0, 6.0))[:3, 3], np.array([4, 5, 6], np.float32))
    assert np.array_equal(matrix.verschiebung(np.array([7.0, 8.0, 9.0]))[:3, 3], np.array([7, 8, 9], np.float32))


def test_fahrzeugmatrix_wie_vorher():
    zufall = random.Random(5)
    for _ in range(500):
        pos = [zufall.uniform(-500, 500), zufall.uniform(-500, 500), zufall.uniform(0, 3)]
        gier = zufall.uniform(-7, 7)
        alt = (_alt_einheit().__class__ and _verschiebung_alt(*pos)) @ _alt_drehung(2, gier)
        assert np.array_equal(matrix.fahrzeug(pos, gier), alt)
        assert np.array_equal(matrix.fahrzeug(pos[:2], gier), _verschiebung_alt(pos[0], pos[1], 0.0) @ _alt_drehung(2, gier))


def _verschiebung_alt(x, y, z):
    m = _alt_einheit()
    m[:3, 3] = (x, y, z)
    return m
