"""Die Mittellinie am Streckennetz: wo bin ich nach n Metern.

Getrennt von test_render3d_track.py, weil es hier nicht um Dreiecke geht,
sondern um die Frage, die Kamera, Gegnerlogik und Startaufstellung stellen.
"""
import math

import numpy as np
import pytest

from src.render3d import track_mesh


def _kreisstrecke(radius_px=500.0, punkte=360, breite_px=300.0):
    winkel = np.linspace(0.0, 2.0 * math.pi, punkte, endpoint=False)
    return {
        "track_width": breite_px,
        "centerline": [{"x": float(radius_px * math.cos(w)),
                        "y": float(radius_px * math.sin(w))} for w in winkel],
        "start_positions": [],
    }


def test_mittellinie_kommt_in_metern_heraus():
    netz = track_mesh.bauen(_kreisstrecke())
    assert netz.mittellinie.shape == (360, 2)
    radius_m = float(np.linalg.norm(netz.mittellinie, axis=1).mean())
    assert radius_m == pytest.approx(500.0 * 0.08, rel=1e-9)


def test_punkt_bei_null_ist_der_erste_punkt():
    netz = track_mesh.bauen(_kreisstrecke())
    pos, _ = netz.punkt_bei(0.0)
    assert pos == pytest.approx(netz.mittellinie[0], abs=1e-9)


def test_punkt_bei_laeuft_ueber_das_ende_hinaus_wieder_von_vorne():
    netz = track_mesh.bauen(_kreisstrecke())
    a, ga = netz.punkt_bei(12.0)
    b, gb = netz.punkt_bei(12.0 + netz.laenge_m)
    assert a == pytest.approx(b, abs=1e-6)
    assert ga == pytest.approx(gb, abs=1e-9)


def test_eine_halbe_runde_liegt_gegenueber():
    netz = track_mesh.bauen(_kreisstrecke())
    anfang, _ = netz.punkt_bei(0.0)
    haelfte, _ = netz.punkt_bei(netz.laenge_m / 2.0)
    assert haelfte == pytest.approx(-anfang, abs=1e-3)


def test_der_gierwinkel_zeigt_in_fahrtrichtung():
    """Auf einem gegen den Uhrzeigersinn abgetasteten Kreis steht die
    Fahrtrichtung senkrecht auf dem Radius, nach links gedreht."""
    netz = track_mesh.bauen(_kreisstrecke())
    for anteil in (0.0, 0.25, 0.5, 0.75):
        pos, gier = netz.punkt_bei(netz.laenge_m * anteil)
        radial = pos / np.linalg.norm(pos)
        fahrt = np.array([math.cos(gier), math.sin(gier)])
        assert abs(float(radial @ fahrt)) < 0.02, "Fahrtrichtung ist nicht radial"
        kreuz = radial[0] * fahrt[1] - radial[1] * fahrt[0]
        assert kreuz > 0.9, "Fahrtrichtung muss gegen den Uhrzeigersinn zeigen"


def test_gleichmaessige_schritte_ergeben_gleiche_abstaende():
    """Interpoliert wird nach Bogenlaenge, nicht nach Punktindex."""
    netz = track_mesh.bauen(_kreisstrecke())
    schritt = netz.laenge_m / 50.0
    punkte = np.array([netz.punkt_bei(i * schritt)[0] for i in range(50)])
    abstaende = np.linalg.norm(np.diff(punkte, axis=0), axis=1)
    assert abstaende.std() < 0.01 * abstaende.mean()


def test_negative_strecke_laeuft_rueckwaerts():
    netz = track_mesh.bauen(_kreisstrecke())
    a, _ = netz.punkt_bei(-5.0)
    b, _ = netz.punkt_bei(netz.laenge_m - 5.0)
    assert a == pytest.approx(b, abs=1e-6)


def test_ohne_mittellinie_wird_gemeldet():
    leer = track_mesh.Streckennetz(baender=[], laenge_m=0.0, start_positionen=[])
    with pytest.raises(ValueError, match="Mittellinie"):
        leer.punkt_bei(1.0)


def test_echte_strecken_liefern_punkte_auf_der_fahrbahn():
    """Der Punkt nach n Metern muss innerhalb der halben Streckenbreite um
    die Mittellinie liegen - sonst stimmt die Interpolation nicht."""
    netz = track_mesh.aus_datei("data/tracks/oval.json")
    for anteil in np.linspace(0.0, 1.0, 25, endpoint=False):
        pos, _ = netz.punkt_bei(netz.laenge_m * float(anteil))
        abstand = np.linalg.norm(netz.mittellinie - pos, axis=1).min()
        assert abstand < 1.0, "Punkt liegt zu weit von der Mittellinie weg"
