"""Ausrichtung: laengste Achse nach +X, kuerzeste nach +Z, unten bleibt unten."""
import numpy as np
import pytest
import trimesh

from trellis_pipeline import orient


def _karosserie_klotz(laenge=4.0, breite=2.0, hoehe=1.4, unten_schwer=True):
    """Ein Quader in der Groessenordnung eines Autos, absichtlich schief gelegt.

    Mit ``unten_schwer`` bekommt er zusaetzliche Masse an einem Ende - so wie ein
    echtes Auto, dessen Schwerpunkt unter der Mitte der Bounding-Box liegt.
    """
    koerper = trimesh.creation.box(extents=(laenge, breite, hoehe))
    if unten_schwer:
        ballast = trimesh.creation.box(extents=(laenge * 0.9, breite * 0.9, hoehe * 0.2))
        ballast.apply_translation((0, 0, -hoehe * 0.4))
        koerper = trimesh.util.concatenate([koerper, ballast])
    return koerper


def _verdrehen(mesh, winkel_grad=(37, 21, 63)):
    m = mesh.copy()
    for achse, winkel in zip(np.eye(3), winkel_grad):
        m.apply_transform(trimesh.transformations.rotation_matrix(
            np.radians(winkel), achse))
    m.apply_translation((11.0, -4.0, 7.5))
    return m


def test_laengste_achse_liegt_hinterher_auf_x():
    m = orient.ausrichten(_verdrehen(_karosserie_klotz(4.0, 2.0, 1.4)))
    ext = m.bounding_box.extents
    assert ext[0] > ext[1] > ext[2]
    assert ext[0] == pytest.approx(4.0, rel=0.02)
    assert ext[1] == pytest.approx(2.0, rel=0.02)


def test_dach_zeigt_nach_oben_wenn_das_modell_auf_dem_kopf_liegt():
    kopfueber = _karosserie_klotz()
    kopfueber.apply_transform(trimesh.transformations.rotation_matrix(np.pi, (1, 0, 0)))
    m = orient.ausrichten(kopfueber)
    mitte_z = m.bounding_box.centroid[2]
    assert orient.schwerpunkt(m)[2] < mitte_z, "Schwerpunkt muss unter der Bbox-Mitte liegen"


def _auto_form(unten_breit=2.10, oben_breit=1.50, laenge=4.32, hoehe=1.40):
    """Eine Form wie ein Auto: unten breit, oben schmaler.

    Ein Quader taugt fuer diese Frage nicht - er ist oben so breit wie unten.
    """
    m = trimesh.creation.box(extents=(laenge, unten_breit, hoehe))
    oben = m.vertices[:, 2] > 0
    m.vertices[oben, 1] *= oben_breit / unten_breit
    return m


def test_breite_entscheidet_ueber_oben_und_unten():
    assert not orient.steht_auf_dem_dach(_auto_form())
    kopfueber = _auto_form()
    kopfueber.apply_transform(trimesh.transformations.rotation_matrix(np.pi, (1, 0, 0)))
    assert orient.steht_auf_dem_dach(kopfueber)


def _kasten_auf_raedern(oben_schmaler=1.0):
    """Karosserie auf vier Radzylindern.

    Mit ``oben_schmaler = 1.0`` ist der Koerper ein Quader - oben so breit wie
    unten. Werte darunter verjuengen ihn nach oben, wie bei einem Fahrzeug.
    """
    koerper = trimesh.creation.box(extents=(4.32, 1.87, 1.2))
    oben = koerper.vertices[:, 2] > 0
    koerper.vertices[oben, 1] *= oben_schmaler
    koerper.apply_translation((0, 0, 0.775))
    teile = [koerper]
    for x in (1.312, -1.312):
        for y in (0.853, -0.853):
            rad = trimesh.creation.cylinder(radius=0.325, height=0.2, sections=64)
            rad.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
            rad.apply_translation((x, y, 0.325))
            teile.append(rad)
    return trimesh.util.concatenate(teile)


def test_fahrzeugform_auf_raedern_wird_nicht_umgedreht():
    """Der Fall, an dem das reine Schwerpunktkriterium gescheitert ist.

    Bei einem Koerper auf vier Radzylindern liegt der flaechengewichtete
    Schwerpunkt ueber der Bbox-Mitte - "unten schwerer" gilt fuer die Masse,
    nicht fuer die Oberflaeche. Die Breite entscheidet hier richtig.
    """
    auto = _kasten_auf_raedern(oben_schmaler=0.75)
    assert orient.schwerpunkt(auto)[2] > auto.bounding_box.centroid[2], \
        "Vorbedingung: genau hier taeuscht der Schwerpunkt"
    assert not orient.steht_auf_dem_dach(auto)


def test_bei_gleicher_breite_entscheidet_der_schwerpunkt():
    """Die dokumentierte Grenze des Verfahrens.

    Ein Koerper, der oben genauso breit ist wie unten, gibt ueber die Breite
    nichts her. Dann faellt die Entscheidung auf den Schwerpunkt zurueck - und
    der kann bei kantigen Formen daneben liegen. Ein Fahrzeug aus TRELLIS ist
    oben schmaler; wer hier hineinlaeuft, hat kein Auto vor sich.
    """
    quader = _kasten_auf_raedern(oben_schmaler=1.0)
    ueber_der_mitte = orient.schwerpunkt(quader)[2] > quader.bounding_box.centroid[2]
    assert orient.steht_auf_dem_dach(quader) == ueber_der_mitte


def test_ausrichtung_spiegelt_nicht():
    """Eine Spiegelung wuerde aus einem Rechtslenker einen Linkslenker machen."""
    urspruenglich = _verdrehen(_karosserie_klotz())
    m = orient.ausrichten(urspruenglich)
    assert m.volume == pytest.approx(urspruenglich.volume, rel=1e-6)
    assert np.linalg.det(orient.letzte_matrix(m)[:3, :3]) == pytest.approx(1.0, abs=1e-6)


def test_flip_dreht_um_die_hochachse_und_laesst_oben_oben():
    m = orient.ausrichten(_verdrehen(_karosserie_klotz()), flip=False)
    g = orient.ausrichten(_verdrehen(_karosserie_klotz()), flip=True)
    assert m.bounding_box.extents == pytest.approx(g.bounding_box.extents, rel=1e-6)
    assert orient.schwerpunkt(g)[2] == pytest.approx(orient.schwerpunkt(m)[2], abs=1e-6)


def test_rad_legt_die_drehachse_auf_y():
    """Ein Rad ist eine Scheibe: zwei grosse Achsen (Durchmesser), eine kleine
    (Breite). Die kleine muss quer zur Fahrtrichtung liegen, nicht nach oben."""
    rad = trimesh.creation.cylinder(radius=0.325, height=0.22, sections=48)
    rad.apply_transform(trimesh.transformations.rotation_matrix(np.radians(40), (0, 1, 1)))
    m = orient.ausrichten(rad, typ="rad")
    ext = m.bounding_box.extents
    assert ext[1] == pytest.approx(0.22, rel=0.05), "Breite gehoert auf Y"
    assert ext[0] == pytest.approx(0.65, rel=0.05)
    assert ext[2] == pytest.approx(0.65, rel=0.05)
