"""B4: Räder, die rollen und lenken.

Geprüft wird an gerechneten Punkten, nicht am Bild: wohin wandert ein Punkt
auf der Lauffläche, wenn das Fahrzeug einen Meter fährt, und wohin, wenn es
einlenkt.
"""
import json
import math

import numpy as np
import pytest

from src.render3d import matrix
from src.render3d.vehicle_node import (KAROSSERIE, Fahrzeugknoten, Radplatz,
                                       teile_lesen)

RADIUS = 0.325

#: Toleranz fuer Vergleiche gegen Matrixergebnisse. Die Matrizen sind laut
#: VEREINBARUNGEN.md float32 - dort liegt die relative Genauigkeit bei rund
#: 1e-7, bei Fahrzeugmassen im Meterbereich also einige hundertstel
#: Millimeter. Enger zu pruefen misst die Rundung der Gleitkommazahlen und
#: nicht mehr die Geometrie.
GENAU = 1e-6


def _knoten(lenkbar=True):
    raeder = [
        Radplatz("rad_vl", np.array([1.312, 0.764, RADIUS]), lenkbar),
        Radplatz("rad_vr", np.array([1.312, -0.764, RADIUS]), lenkbar),
        Radplatz("rad_hl", np.array([-1.312, 0.764, RADIUS]), False),
        Radplatz("rad_hr", np.array([-1.312, -0.764, RADIUS]), False),
    ]
    return Fahrzeugknoten(raeder, RADIUS * 2)


def _punkt(m, p):
    """Einen Punkt durch eine Matrix schicken."""
    v = np.array([p[0], p[1], p[2], 1.0], dtype=np.float64)
    return (np.asarray(m, dtype=np.float64) @ v)[:3]


# -- Rollen ------------------------------------------------------------------
def test_ein_meter_weg_dreht_das_rad_um_einen_radius():
    k = _knoten()
    k.weg_zuruecklegen(1.0)
    assert k.rollwinkel_rad == pytest.approx(1.0 / RADIUS)


def test_ein_voller_umfang_ist_eine_ganze_umdrehung():
    k = _knoten()
    k.weg_zuruecklegen(2 * math.pi * RADIUS)
    assert k.rollwinkel_rad == pytest.approx(2 * math.pi)


def test_rueckwaerts_dreht_zurueck():
    k = _knoten()
    k.weg_zuruecklegen(-1.0)
    assert k.rollwinkel_rad == pytest.approx(-1.0 / RADIUS)


def test_stillstand_dreht_nicht():
    """Der Grund, warum der Weg zaehlt und nicht die Zeit."""
    k = _knoten()
    for _ in range(100):
        k.weg_zuruecklegen(0.0)
    assert k.rollwinkel_rad == 0.0


def test_der_oberste_punkt_des_rades_wandert_nach_vorne():
    """Vorwaerts fahren muss das Rad vorwaerts drehen, nicht rueckwaerts.

    Ein Punkt oben auf der Lauflaeche gehoert bei Vorwaertsfahrt nach vorne,
    also in Richtung +X.
    """
    k = _knoten()
    oben = np.array([0.0, 0.0, RADIUS])
    vorher = _punkt(k.rad_matrix(k.raeder[0]), oben)
    k.weg_zuruecklegen(0.05)
    nachher = _punkt(k.rad_matrix(k.raeder[0]), oben)
    assert nachher[0] > vorher[0], "der Punkt oben muss nach vorne wandern"
    assert nachher[2] < vorher[2] + 1e-9


def test_die_nabe_bleibt_beim_rollen_stehen():
    k = _knoten()
    k.weg_zuruecklegen(3.7)
    for rad in k.raeder:
        assert _punkt(k.rad_matrix(rad), (0, 0, 0)) == pytest.approx(rad.nabe, abs=GENAU)


# -- Lenken ------------------------------------------------------------------
def test_nur_die_vorderraeder_lenken():
    k = _knoten()
    k.lenken(0.4)
    vorne = _punkt(k.rad_matrix(k.raeder[0]), (RADIUS, 0, 0))
    hinten = _punkt(k.rad_matrix(k.raeder[2]), (RADIUS, 0, 0))
    assert abs(vorne[1] - k.raeder[0].nabe[1]) > 0.05, "vorne muss einschlagen"
    assert hinten[1] == pytest.approx(k.raeder[2].nabe[1], abs=GENAU)


def test_einschlag_nach_links_dreht_die_radnase_nach_links():
    k = _knoten()
    k.lenken(0.3)
    nase = _punkt(k.rad_matrix(k.raeder[0]), (RADIUS, 0.0, 0.0))
    assert nase[1] > k.raeder[0].nabe[1], "positiver Winkel schlaegt nach +Y ein"


def test_lenken_verschiebt_die_nabe_nicht():
    """Die Lenkachse steht senkrecht durch die Radmitte."""
    k = _knoten()
    k.lenken(0.5)
    for rad in k.raeder:
        assert _punkt(k.rad_matrix(rad), (0, 0, 0)) == pytest.approx(rad.nabe, abs=GENAU)


def test_gelenktes_rad_bleibt_beim_rollen_senkrecht():
    """Vertauschte Reihenfolge waere hier sichtbar: das Rad wuerde eiern.

    Die Radachse zeigt nach dem Einschlagen quer zur Fahrtrichtung, aber
    weiterhin waagerecht - ihre Hochkomponente muss null bleiben, egal wie
    weit gerollt wurde.
    """
    k = _knoten()
    k.lenken(0.35)
    k.weg_zuruecklegen(2.4)
    m = k.rad_matrix(k.raeder[0])
    achse = _punkt(m, (0, 1, 0)) - _punkt(m, (0, 0, 0))
    assert achse[2] == pytest.approx(0.0, abs=GENAU)
    assert np.linalg.norm(achse) == pytest.approx(1.0, abs=GENAU)


# -- Fahrzeug als Ganzes -----------------------------------------------------
def test_matrizen_enthalten_karosserie_vier_raeder_und_saettel():
    m = _knoten().matrizen((0.0, 0.0), 0.0)
    assert set(m) == {KAROSSERIE, "rad_vl", "rad_vr", "rad_hl", "rad_hr",
                      "sattel_vl", "sattel_vr", "sattel_hl", "sattel_hr"}


def test_der_sattel_lenkt_mit_rollt_aber_nicht():
    k = _knoten()
    k.lenken(0.4)
    k.setzen(rollwinkel_rad=1.3, lenkwinkel_rad=0.4)
    m = k.matrizen((0.0, 0.0), 0.0)
    oben = (0.0, 0.0, 0.2)
    # Rollen dreht einen Punkt über der Nabe nach vorn, der Sattel bleibt oben.
    assert _punkt(m["sattel_vl"], oben)[2] == pytest.approx(RADIUS + 0.2, abs=GENAU)
    assert _punkt(m["rad_vl"], oben)[2] < RADIUS + 0.2 - 1e-3
    # Gelenkt: ein Punkt vor der Nabe wandert nach links.
    vorn = _punkt(m["sattel_vl"], (0.2, 0.0, 0.0))
    assert vorn[1] > k.raeder[0].nabe[1] + 1e-3


def test_die_karosserie_kann_sich_neigen_ohne_die_raeder():
    k = _knoten()
    neigung = matrix.drehung_x(0.05)
    m = k.matrizen((0.0, 0.0), 0.0, karosserie=neigung)
    assert np.allclose(m[KAROSSERIE], neigung)
    assert np.allclose(m["rad_vl"], k.matrizen((0.0, 0.0), 0.0)["rad_vl"])


def test_das_fahrzeug_nimmt_die_raeder_mit():
    k = _knoten()
    m = k.matrizen((10.0, -4.0), 0.0)
    assert _punkt(m["rad_vl"], (0, 0, 0)) == pytest.approx(
        k.raeder[0].nabe + np.array([10.0, -4.0, 0.0]), abs=GENAU)


def test_gierwinkel_dreht_das_ganze_fahrzeug():
    k = _knoten()
    m = k.matrizen((0.0, 0.0), math.pi / 2)
    # Vorne links liegt nach einer Vierteldrehung gegen den Uhrzeigersinn
    # bei (-y, +x) der urspruenglichen Nabe.
    nabe = k.raeder[0].nabe
    assert _punkt(m["rad_vl"], (0, 0, 0)) == pytest.approx(
        np.array([-nabe[1], nabe[0], nabe[2]]), abs=GENAU)


def test_zweidimensionale_position_wird_angenommen():
    """Das Spiel fuehrt seine Positionen in 2D."""
    k = _knoten()
    flach = k.matrizen((3.0, 4.0), 0.2)[KAROSSERIE]
    raeumlich = k.matrizen((3.0, 4.0, 0.0), 0.2)[KAROSSERIE]
    assert np.allclose(flach, raeumlich)


# -- Teileliste --------------------------------------------------------------
def test_teileliste_wird_gelesen(tmp_path):
    pfad = tmp_path / "rookie_teile.json"
    pfad.write_text(json.dumps({
        "raddurchmesser_m": 0.65,
        "gelenkt": ["rad_vl", "rad_vr"],
        "raeder": [
            {"name": "rad_vl", "nabe": [1.3, 0.76, 0.325]},
            {"name": "rad_hr", "nabe": [-1.3, -0.76, 0.325]},
        ],
    }), encoding="utf-8")
    plaetze, durchmesser = teile_lesen(pfad)
    assert durchmesser == pytest.approx(0.65)
    assert [p.name for p in plaetze] == ["rad_vl", "rad_hr"]
    assert plaetze[0].gelenkt and not plaetze[1].gelenkt


@pytest.mark.skipif(not __import__("pathlib").Path("assets/vehicles/rookie_teile.json").is_file(),
                    reason="Fahrzeuge noch nicht mit tools/blender/fahrzeug_bauen.py erzeugt")
def test_knoten_aus_der_echten_teileliste():
    k = Fahrzeugknoten.aus_datei("assets/vehicles/rookie_teile.json")
    assert len(k.raeder) == 4
    assert sum(r.gelenkt for r in k.raeder) == 2, "genau die Vorderraeder lenken"
    assert k.radradius_m == pytest.approx(0.325)


def test_durchmesser_null_wird_abgelehnt():
    """Sonst teilt der Rollwinkel durch null und alles wird NaN."""
    with pytest.raises(ValueError, match="Raddurchmesser"):
        Fahrzeugknoten([], 0.0)
