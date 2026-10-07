"""Kameraansichten (1.1.0): Lage je Ansicht, Umschalten, Zurückschauen.

Reine Mathematik, kein Fenster. Die Ansichten stehen in
``src/render3d/ansichten.py``; Welt: +X vorne, +Y links, +Z oben.
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.render3d import ansichten, camera, matrix, vehicle_node  # noqa: E402
from src.render3d.ansichten import (  # noqa: E402
    ANSICHTEN, COCKPIT, MOTORHAUBE, VERFOLGER_FERN, VERFOLGER_NAH, Ansichtskamera,
)

POS = np.array([10.0, 5.0, 0.0])
MASSE = vehicle_node.Cockpitmasse(augpunkt=np.array([-0.2, 0.35, 1.2]),
                                  haube=np.array([1.1, 0.0, 1.15]))


def _kamera(ansicht, gier=0.0, rueck=False, aufbau=None):
    kam = Ansichtskamera(ansicht, MASSE)
    kam.rueckblick = rueck
    kam.setzen(POS, gier)
    if aufbau is not None:
        kam.aufbau_setzen(aufbau)
    return kam


def _vorwaerts(kam):
    v = kam.ziel.astype(np.float64) - kam.auge.astype(np.float64)
    return v / np.linalg.norm(v)


# ---------------------------------------------------------------------------
# Wahl und Umschalten
# ---------------------------------------------------------------------------

def test_die_ansichten_in_der_vereinbarten_reihenfolge():
    assert ANSICHTEN == (VERFOLGER_FERN, VERFOLGER_NAH, MOTORHAUBE, COCKPIT)
    assert ansichten.STANDARD == VERFOLGER_FERN


def test_umschalten_geht_der_reihe_nach_und_beginnt_von_vorn():
    kam = Ansichtskamera(VERFOLGER_FERN, MASSE)
    gesehen = [kam.ansicht]
    for _ in range(len(ANSICHTEN)):
        gesehen.append(kam.wechseln())
    assert gesehen == [*ANSICHTEN, VERFOLGER_FERN]


@pytest.mark.parametrize("wert", [None, "", "quatsch", 3, ["cockpit"], "COCKPIT"])
def test_unbekannte_ansicht_wird_zur_standardansicht(wert):
    assert ansichten.normalisiere(wert) == ansichten.STANDARD
    assert Ansichtskamera(wert).ansicht == ansichten.STANDARD


def test_jede_ansicht_hat_einen_anzeigenamen():
    assert set(ansichten.NAMEN) == set(ANSICHTEN)


# ---------------------------------------------------------------------------
# Lage der Verfolger
# ---------------------------------------------------------------------------

def test_verfolger_fern_ist_die_bisherige_kamera():
    kam = _kamera(VERFOLGER_FERN)
    alt = camera.Verfolgerkamera(abstand_m=7.5, hoehe_m=2.8, zielhoehe_m=1.0)
    alt.setzen(POS, 0.0)
    np.testing.assert_allclose(kam.auge, alt.auge, atol=1e-5)
    np.testing.assert_allclose(kam.ziel, alt.ziel, atol=1e-5)
    assert kam.sichtfeld_grad == pytest.approx(55.0)
    assert kam.nahe_m == pytest.approx(0.2)
    assert not kam.innen


def test_verfolger_nah_ist_naeher_und_tiefer():
    fern, nah = _kamera(VERFOLGER_FERN), _kamera(VERFOLGER_NAH)
    assert np.linalg.norm(nah.auge[:2] - POS[:2]) < np.linalg.norm(fern.auge[:2] - POS[:2])
    assert nah.auge[2] < fern.auge[2]
    assert not nah.innen


@pytest.mark.parametrize("ansicht", [VERFOLGER_FERN, VERFOLGER_NAH])
def test_verfolger_sitzt_hinter_dem_wagen_und_dreht_mit(ansicht):
    gier = math.radians(90.0)
    kam = _kamera(ansicht, gier=gier)
    # Wagen blickt nach +Y: das Auge liegt hinter ihm, bei kleinerem Y.
    assert kam.auge[1] < POS[1]
    assert kam.auge[0] == pytest.approx(POS[0], abs=1e-4)


# ---------------------------------------------------------------------------
# Starre Ansichten
# ---------------------------------------------------------------------------

def test_cockpit_sitzt_im_augpunkt_und_blickt_nach_vorn():
    kam = _kamera(COCKPIT)
    np.testing.assert_allclose(kam.auge, POS + MASSE.augpunkt, atol=1e-5)
    np.testing.assert_allclose(_vorwaerts(kam), [1, 0, 0], atol=1e-5)
    assert kam.innen


def test_haube_sitzt_am_haubenpunkt():
    kam = _kamera(MOTORHAUBE)
    np.testing.assert_allclose(kam.auge, POS + MASSE.haube, atol=1e-5)
    assert kam.innen


def test_cockpit_dreht_mit_dem_gierwinkel():
    kam = _kamera(COCKPIT, gier=math.radians(90.0))
    a = MASSE.augpunkt
    # +90 Grad um Z: (x, y) -> (-y, x)
    np.testing.assert_allclose(kam.auge, POS + np.array([-a[1], a[0], a[2]]), atol=1e-5)
    np.testing.assert_allclose(_vorwaerts(kam), [0, 1, 0], atol=1e-5)


def test_cockpit_haengt_starr_am_aufbau_mit_nicken_und_wanken():
    aufbau = vehicle_node.aufbau_aus_neigung(0.05, 0.08, 0.33)
    kam = _kamera(COCKPIT, aufbau=aufbau)
    erwartet = (matrix.fahrzeug(POS, 0.0) @ aufbau @ np.array([*MASSE.augpunkt, 1.0]))[:3]
    np.testing.assert_allclose(kam.auge, erwartet, atol=1e-4)
    # Nicken 0.05 rad: Blick senkt sich um ebendiesen Winkel (+: Front runter)
    vor = _vorwaerts(kam)
    assert math.asin(-vor[2]) == pytest.approx(0.05, abs=1e-4)
    # Wanken 0.08 rad: das Oben der Kamera kippt um denselben Winkel zur Seite
    oben = kam.oben.astype(np.float64)
    assert abs(oben[1]) == pytest.approx(math.sin(0.08), abs=1e-3)


def test_ohne_aufbau_ist_der_horizont_waagerecht():
    kam = _kamera(COCKPIT)
    np.testing.assert_allclose(kam.oben, [0, 0, 1], atol=1e-6)
    assert _vorwaerts(kam)[2] == pytest.approx(0.0, abs=1e-6)


def test_aufbau_setzen_rechnet_die_starre_lage_sofort_neu():
    kam = _kamera(COCKPIT)
    vorher = kam.auge.copy()
    kam.aufbau_setzen(vehicle_node.aufbau_aus_neigung(0.0, 0.1, 0.33))
    assert not np.allclose(kam.auge, vorher)
    kam.aufbau_setzen(None)
    np.testing.assert_allclose(kam.auge, vorher, atol=1e-5)


def test_starre_ansicht_folgt_ohne_nachziehen():
    kam = _kamera(COCKPIT)
    neu = np.array([40.0, -3.0, 0.0])
    kam.folgen(neu, 0.3, 1.0 / 60.0)
    erwartet = (matrix.fahrzeug(neu, 0.3) @ np.array([*MASSE.augpunkt, 1.0]))[:3]
    np.testing.assert_allclose(kam.auge, erwartet, atol=1e-5)


def test_sichtfeld_und_nahe_ebene_je_ansicht():
    cockpit, haube, fern = _kamera(COCKPIT), _kamera(MOTORHAUBE), _kamera(VERFOLGER_FERN)
    # Das Lenkrad liegt einen halben Meter vor dem Auge: die nahe Ebene bleibt darunter.
    assert cockpit.nahe_m < 0.25 and cockpit.nahe_m < haube.nahe_m <= fern.nahe_m
    assert cockpit.sichtfeld_grad >= fern.sichtfeld_grad
    # Die nahe Ebene schneidet weder in die Haube noch in das Dach über dem Augpunkt.
    assert haube.nahe_m < MASSE.haube[0] - 0.5
    assert cockpit.nahe_m < MASSE.augpunkt[2] - 0.3


# ---------------------------------------------------------------------------
# Zurückschauen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ansicht", [VERFOLGER_FERN, VERFOLGER_NAH])
def test_zurueckschauen_im_verfolger_kamera_vor_dem_wagen_blick_zurueck(ansicht):
    vorn = _kamera(ansicht)
    hinten = _kamera(ansicht, rueck=True)
    assert vorn.auge[0] < POS[0]               # normal: hinter dem Wagen
    assert hinten.auge[0] > POS[0]             # zurück: davor
    assert _vorwaerts(hinten)[0] < 0           # und blickt zum Wagen hin
    assert hinten.auge[2] == pytest.approx(vorn.auge[2], abs=1e-4)
    # Der Wagen bleibt im Bild: das Ziel liegt über dem Wagen.
    np.testing.assert_allclose(hinten.ziel[:2], POS[:2], atol=1e-4)


def test_zurueckschauen_im_cockpit_dreht_um_180_grad_aus_der_wagenmitte():
    vorn = _kamera(COCKPIT)
    hinten = _kamera(COCKPIT, rueck=True)
    np.testing.assert_allclose(_vorwaerts(hinten), -_vorwaerts(vorn), atol=1e-5)
    assert hinten.auge[0] == pytest.approx(vorn.auge[0])
    assert hinten.auge[1] == pytest.approx(POS[1])      # Wagenmitte statt Fahrersitz
    assert hinten.auge[2] == pytest.approx(vorn.auge[2])
    # Das Oben bleibt oben: kein Blick auf dem Kopf.
    np.testing.assert_allclose(hinten.oben, [0, 0, 1], atol=1e-6)


def test_zurueckschauen_auf_der_haube_setzt_die_kamera_ans_heck():
    hinten = _kamera(MOTORHAUBE, rueck=True)
    assert hinten.auge[0] == pytest.approx(POS[0] - MASSE.haube[0])
    assert _vorwaerts(hinten)[0] < 0


@pytest.mark.parametrize("ansicht", ANSICHTEN)
def test_loslassen_bringt_den_blick_nach_vorn_zurueck(ansicht):
    kam = _kamera(ansicht)
    vorher = (kam.auge.copy(), kam.ziel.copy())
    kam.rueckblick = True
    assert not np.allclose(kam.auge, vorher[0]) or not np.allclose(kam.ziel, vorher[1])
    kam.rueckblick = False
    np.testing.assert_allclose(kam.auge, vorher[0], atol=1e-4)
    np.testing.assert_allclose(kam.ziel, vorher[1], atol=1e-4)


def test_zurueckschauen_ist_ein_schnitt_kein_schwenk():
    """Ein weiches Nachziehen führte die Kamera quer durch den Wagen."""
    kam = _kamera(VERFOLGER_FERN)
    kam.rueckblick = True
    sofort = kam.auge.copy()
    kam.folgen(POS, 0.0, 1.0 / 60.0)
    np.testing.assert_allclose(kam.auge, sofort, atol=1e-3)


def test_wechsel_der_ansicht_springt_sofort_an_die_neue_stelle():
    kam = _kamera(VERFOLGER_FERN)
    kam.wechseln()
    erwartet = _kamera(VERFOLGER_NAH)
    np.testing.assert_allclose(kam.auge, erwartet.auge, atol=1e-5)


# ---------------------------------------------------------------------------
# Matrizen und Abfragen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rueck", [False, True])
@pytest.mark.parametrize("ansicht", ANSICHTEN)
def test_der_blick_ist_gueltig_und_das_ziel_liegt_vor_der_kamera(ansicht, rueck):
    kam = _kamera(ansicht, rueck=rueck, aufbau=vehicle_node.aufbau_aus_neigung(0.02, 0.03, 0.33))
    v = kam.blickmatrix()
    assert np.isfinite(v).all()
    ziel = v @ np.array([*kam.ziel, 1.0], dtype=np.float32)
    assert ziel[2] < 0.0           # Blickraum: die Kamera schaut entlang -Z
    p = camera.perspektive(kam.sichtfeld_grad, 16 / 9, kam.nahe_m, 3200.0)
    assert np.isfinite(p).all()


def test_fokus_der_schattenkarte_ist_bei_starren_ansichten_der_wagen():
    np.testing.assert_allclose(_kamera(COCKPIT).fokus, POS + [0, 0, 1], atol=1e-5)
    fern = _kamera(VERFOLGER_FERN)
    np.testing.assert_allclose(fern.fokus, fern.ziel)


def test_blick_aus_aendert_die_kamera_nicht():
    """Für Spiegel: Lage einer beliebigen Ansicht am Wagenzustand, ohne die Wahl zu berühren."""
    kam = _kamera(VERFOLGER_FERN)
    vorher = (kam.auge.copy(), kam.ansicht)
    auge, ziel, oben = kam.blick_aus(COCKPIT, POS, 0.0)
    np.testing.assert_allclose(auge, POS + MASSE.augpunkt, atol=1e-6)
    assert (kam.auge == vorher[0]).all() and kam.ansicht == vorher[1]


def test_masse_setzen_stellt_die_starre_ansicht_neu():
    kam = _kamera(COCKPIT)
    neu = vehicle_node.Cockpitmasse(augpunkt=np.array([0.1, 0.3, 1.0]),
                                    haube=np.array([1.0, 0.0, 1.0]))
    kam.masse_setzen(neu)
    np.testing.assert_allclose(kam.auge, POS + neu.augpunkt, atol=1e-5)
