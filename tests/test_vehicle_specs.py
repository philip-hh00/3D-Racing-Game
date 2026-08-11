"""Die Sollmasse sind die harte Vorgabe - hier wird sie festgenagelt."""
import pytest

from trellis_pipeline import vehicle_specs as vs


def test_alle_fuenfzehn_konfigurationen_vorhanden():
    assert len(vs.SPECS) == 15


def test_rookie_masse():
    s = vs.spec("rookie")
    assert s.laenge_m == pytest.approx(4.32)
    assert s.breite_m == pytest.approx(2.08)
    assert s.rad_m == pytest.approx(0.65)
    assert s.radstand_m == pytest.approx(2.624)


def test_limousine_ist_das_laengste_fahrzeug():
    laengste = max(vs.SPECS.values(), key=lambda s: s.laenge_m)
    assert laengste.laenge_m == pytest.approx(5.20)


def test_unbekannter_schluessel_nennt_die_gueltigen():
    with pytest.raises(KeyError) as fehler:
        vs.spec("ferrari")
    assert "rookie" in str(fehler.value)


def test_radpositionen_liegen_symmetrisch_um_den_ursprung():
    """Vier Positionen aus Radstand und Breite - Vorbereitung fuer die
    spaeter getrennt generierten Raeder."""
    s = vs.spec("rookie")
    pos = vs.radpositionen("rookie")
    assert len(pos) == 4
    xs = sorted({round(p[0], 6) for p in pos})
    ys = sorted({round(p[1], 6) for p in pos})
    assert xs == [-s.radstand_m / 2, s.radstand_m / 2]
    # Spurweite schmaler als die Fahrzeugbreite - Raeder stehen nicht ueber
    assert ys[0] == -ys[1]
    assert 0 < ys[1] * 2 < s.breite_m
    # Nabenhoehe ist der Radradius, sonst haengt das Rad im Boden
    assert all(p[2] == pytest.approx(s.rad_m / 2) for p in pos)
