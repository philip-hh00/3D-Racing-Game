"""Geländeschatten: die Sonnensichtkarte, gerechnet ohne OpenGL.

Was man im Spiel sähe, wenn es schiefginge: der Schatten auf der Sonnenseite
des Hügels statt dahinter, ein Auto auf dem Kamm im Dunkeln, ein Berg
draußen, der die Strecke nicht mehr abschattet, sobald die feine Karte
übernimmt.
"""
from __future__ import annotations

import math

import numpy as np

from src.render3d import grafik, licht


def _huegel(x0=0.0, y0=0.0, hoehe=50.0, breite=40.0):
    def h(x, y):
        return hoehe * np.exp(-((x - x0) ** 2 + (y - y0) ** 2) / (2.0 * breite ** 2))
    return h


def _sonne(von_grad=0.0, hoehe_grad=30.0):
    """Richtung zur Sonne: waagerecht aus ``von_grad`` (0 = +x), ``hoehe_grad`` hoch."""
    a, e = math.radians(von_grad), math.radians(hoehe_grad)
    return (math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e))


def _karten(hoehe, sonne, nah=None, stufe=3):
    return licht.sichtkarten_rechnen(lambda r: hoehe(*r.punkte()), sonne, (0.0, 0.0), 600.0,
                                     nah, stufe)


def _licht(karte, tan_hoehe, x, y, z):
    raster, grenze, abstand = karte
    return licht.sonnenlicht_gelaende(raster, grenze, abstand, np.atleast_1d(x),
                                      np.atleast_1d(y), np.atleast_1d(z), tan_hoehe)[0]


def test_ein_huegel_schattet_von_der_sonne_weg_nicht_zu_ihr_hin():
    h = _huegel()
    karten, tan_hoehe = _karten(h, _sonne(von_grad=0.0))
    fern = karten[0]
    # Sonne im Osten (+x): der Schatten liegt im Westen.
    assert _licht(fern, tan_hoehe, -50.0, 0.0, h(-50.0, 0.0)) < 0.1
    assert _licht(fern, tan_hoehe, 50.0, 0.0, h(50.0, 0.0)) > 0.9
    # Quer zur Sonne und weit hinter dem Schattenende: Sonne.
    assert _licht(fern, tan_hoehe, 0.0, 150.0, 0.0) > 0.9
    assert _licht(fern, tan_hoehe, -300.0, 0.0, 0.0) > 0.9


def test_der_schatten_dreht_mit_der_sonne():
    h = _huegel()
    karten, tan_hoehe = _karten(h, _sonne(von_grad=90.0))   # Sonne im Norden
    fern = karten[0]
    assert _licht(fern, tan_hoehe, 0.0, -50.0, h(0.0, -50.0)) < 0.1
    assert _licht(fern, tan_hoehe, -50.0, 0.0, h(-50.0, 0.0)) > 0.9


def test_wer_ueber_die_grenze_ragt_steht_in_der_sonne():
    """Ein Auto auf dem Kamm, ein Baumwipfel: die eigene Höhe zählt, nicht der Boden."""
    h = _huegel()
    karten, tan_hoehe = _karten(h, _sonne(von_grad=0.0))
    fern = karten[0]
    boden = h(-50.0, 0.0)
    assert _licht(fern, tan_hoehe, -50.0, 0.0, boden) < 0.1
    assert _licht(fern, tan_hoehe, -50.0, 0.0, boden + 60.0) > 0.9


def test_die_feine_karte_kennt_die_berge_draussen():
    """Ein Hügel außerhalb der feinen Karte, auf der Sonnenseite, schattet hinein."""
    h = _huegel(x0=140.0, breite=30.0, hoehe=60.0)
    karten, tan_hoehe = _karten(h, _sonne(von_grad=0.0, hoehe_grad=25.0),
                                nah=(-100.0, -100.0, 60.0, 100.0))
    assert len(karten) == 2
    nah = karten[1]
    assert _licht(nah, tan_hoehe, 20.0, 0.0, 0.0) < 0.1
    assert _licht(nah, tan_hoehe, 20.0, 90.0, 0.0) > 0.9


def test_ohne_sonnenwinkel_und_auf_aus_gibt_es_keine_karte():
    h = _huegel()
    assert _karten(h, (0.0, 0.0, 1.0)) == ([], None)
    assert _karten(h, _sonne(), stufe=0) == ([], None)


def test_niedrig_rechnet_nur_die_grobe_karte():
    niedrig = grafik.STUFEN["niedrig"].gelaende_schatten
    assert licht.SICHT_DETAIL[niedrig][1] is None
    for name in ("mittel", "hoch", "ultra"):
        assert grafik.STUFEN[name].gelaende_schatten >= niedrig
