"""Massstab und Ursprung: 4,32 m lang und mit den Reifen auf dem Boden."""
import numpy as np
import pytest
import trimesh

from trellis_pipeline import origin, scale


def _klotz(extents=(2.0, 1.0, 0.7)):
    return trimesh.creation.box(extents=extents)


def test_skaliert_auf_die_ziellaenge():
    m = scale.auf_ziellaenge(_klotz((2.0, 1.0, 0.7)), 4.32)
    assert m.bounding_box.extents[0] == pytest.approx(4.32)


def test_skalierung_ist_gleichmaessig():
    """Ungleiche Achsfaktoren wuerden das Auto verzerren."""
    vorher = _klotz((2.0, 1.0, 0.7)).bounding_box.extents
    nachher = scale.auf_ziellaenge(_klotz((2.0, 1.0, 0.7)), 4.32).bounding_box.extents
    assert nachher[1] / vorher[1] == pytest.approx(nachher[0] / vorher[0])
    assert nachher[2] / vorher[2] == pytest.approx(nachher[0] / vorher[0])


def test_rad_skaliert_ueber_den_durchmesser():
    rad = trimesh.creation.cylinder(radius=1.0, height=0.5, sections=48)
    rad.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    m = scale.auf_raddurchmesser(rad, 0.65)
    ext = m.bounding_box.extents
    assert ext[0] == pytest.approx(0.65, rel=1e-3)
    assert ext[2] == pytest.approx(0.65, rel=1e-3)


def test_ursprung_liegt_mittig_auf_dem_boden():
    m = _klotz((4.32, 2.08, 1.4))
    m.apply_translation((17.0, -3.0, 9.0))
    origin.auf_bodenkontakt(m)
    kasten = m.bounds
    assert kasten[0][2] == pytest.approx(0.0), "Unterkante gehoert auf z = 0"
    assert m.bounding_box.centroid[0] == pytest.approx(0.0)
    assert m.bounding_box.centroid[1] == pytest.approx(0.0)


def test_radursprung_ist_die_nabenmitte():
    rad = trimesh.creation.cylinder(radius=0.325, height=0.22, sections=48)
    rad.apply_translation((5.0, 5.0, 5.0))
    origin.auf_nabenmitte(rad)
    assert rad.bounding_box.centroid == pytest.approx([0.0, 0.0, 0.0], abs=1e-9)
