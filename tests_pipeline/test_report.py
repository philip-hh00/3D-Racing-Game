"""Der Bericht ist die Abnahme: stimmen die Masse, ist eine Textur da."""
import pytest
import trimesh

from trellis_pipeline import report, vehicle_specs


def _auto(laenge=4.32, breite=2.08, hoehe=1.40):
    return trimesh.creation.box(extents=(laenge, breite, hoehe))


def test_masse_im_soll_ergeben_keine_warnung():
    b = report.pruefen(_auto(), vehicle_specs.spec("rookie"), typ="karosserie")
    assert b.warnungen == []
    assert b.ist_laenge_m == pytest.approx(4.32)


def test_zu_breites_modell_wird_gemeldet():
    b = report.pruefen(_auto(breite=2.60), vehicle_specs.spec("rookie"), typ="karosserie")
    assert any("Breite" in w for w in b.warnungen)


def test_abweichung_knapp_unter_fuenf_prozent_ist_in_ordnung():
    b = report.pruefen(_auto(breite=2.08 * 1.049), vehicle_specs.spec("rookie"),
                       typ="karosserie")
    assert b.warnungen == []


def test_abweichung_knapp_ueber_fuenf_prozent_warnt():
    b = report.pruefen(_auto(breite=2.08 * 1.051), vehicle_specs.spec("rookie"),
                       typ="karosserie")
    assert len(b.warnungen) == 1


def test_dreiecke_werden_gezaehlt():
    b = report.pruefen(_auto(), vehicle_specs.spec("rookie"), typ="karosserie")
    assert b.dreiecke == 12


def test_fehlende_textur_wird_gemeldet_nicht_verschwiegen():
    """Kein Massfehler, aber auch nichts, was stillschweigend durchgehen darf."""
    b = report.pruefen(_auto(), vehicle_specs.spec("rookie"), typ="karosserie")
    assert b.texturgroesse is None
    assert b.pbr_kanaele == []
    assert any("Textur" in h for h in b.hinweise)
    assert b.warnungen == []


def test_text_nennt_ist_und_soll():
    text = report.pruefen(_auto(), vehicle_specs.spec("rookie"), typ="karosserie").text()
    assert "4.32" in text
    assert "Dreiecke" in text
