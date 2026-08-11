"""Lackmaske - dieselbe Rechnung wie im 2D-Spiel (src/core/lack.py)."""
import numpy as np
import pytest
from PIL import Image

from trellis_pipeline import paintmask


ROOKIE_PAINT = {
    "verfahren": "dominant",
    "saettigungsschwelle": 0.25,
    "referenzfarbe": [203, 60, 59],
    "farbtoleranz": 0.3,
    "helligkeit_min": 0.06,
    "helligkeit_max": 0.51,
    "kantenweichheit": 0.0,
    "deckkraft": 1.0,
}


#: Spaltenbereiche der Testtextur. Die Lackflaeche ist absichtlich die groesste:
#: bei Gleichstand haengt die dominante Farbe von der Sortierreihenfolge ab, und
#: ein Test, der auf so etwas baut, prueft nicht das Verfahren sondern numpy.
LACK = slice(0, 32)
SCHEIBE = slice(32, 48)
UNSICHTBAR = slice(48, 64)


def _testtextur():
    """Links Karosserierot, dann dunkle Scheibe, rechts durchsichtig."""
    bild = np.zeros((16, 64, 4), dtype=np.uint8)
    bild[:, LACK] = (203, 60, 59, 255)       # Lack
    bild[:, SCHEIBE] = (48, 52, 58, 255)     # Scheibe, sehr dunkel
    bild[:, UNSICHTBAR] = (0, 0, 0, 0)       # unsichtbar
    return Image.fromarray(bild, mode="RGBA")


def test_lack_wird_getroffen():
    maske = paintmask.maske(_testtextur(), ROOKIE_PAINT)
    assert maske[:, LACK].min() == pytest.approx(1.0)


def test_scheibe_bleibt_aussen_vor():
    """Das Helligkeitsfenster ist der Hebel gegen mitgezaehlte Scheiben."""
    maske = paintmask.maske(_testtextur(), ROOKIE_PAINT)
    assert maske[:, SCHEIBE].max() == pytest.approx(0.0)


def test_unsichtbares_zaehlt_nicht():
    maske = paintmask.maske(_testtextur(), ROOKIE_PAINT)
    assert maske[:, UNSICHTBAR].max() == pytest.approx(0.0)


def test_verfahren_aus_ergibt_leere_maske():
    maske = paintmask.maske(_testtextur(), dict(ROOKIE_PAINT, verfahren="aus"))
    assert maske.max() == pytest.approx(0.0)


def test_fehlende_referenzfarbe_wird_aus_dem_bild_bestimmt():
    werte = dict(ROOKIE_PAINT, referenzfarbe=None)
    maske = paintmask.maske(_testtextur(), werte)
    assert maske[:, LACK].min() == pytest.approx(1.0)


def test_kantenweichheit_erzeugt_einen_uebergang():
    weich = paintmask.maske(_testtextur(), dict(ROOKIE_PAINT, kantenweichheit=3.0))
    zwischenwerte = weich[(weich > 0.01) & (weich < 0.99)]
    assert zwischenwerte.size > 0


def test_toleranz_null_trifft_nur_die_referenzfarbe_selbst():
    maske = paintmask.maske(_testtextur(), dict(ROOKIE_PAINT, farbtoleranz=0.0))
    assert maske[:, LACK].min() == pytest.approx(1.0)
    assert maske[:, SCHEIBE].max() == pytest.approx(0.0)


def test_ohne_alphakanal_gilt_alles_als_sichtbar():
    """TRELLIS-Base-Color-Texturen kommen oft als RGB ohne Alpha."""
    bild = Image.fromarray(np.full((8, 8, 3), (203, 60, 59), dtype=np.uint8), mode="RGB")
    maske = paintmask.maske(bild, ROOKIE_PAINT)
    assert maske.min() == pytest.approx(1.0)


def test_paint_werte_kommen_aus_der_fahrzeug_json(tmp_path):
    (tmp_path / "rookie.json").write_text(
        '{"paint": {"verfahren": "dominant", "farbtoleranz": 0.3}}', encoding="utf-8")
    werte = paintmask.paint_werte("rookie", tmp_path)
    assert werte["verfahren"] == "dominant"
    assert werte["farbtoleranz"] == 0.3
    # Fehlendes wird aus der Vorgabe aufgefuellt
    assert werte["helligkeit_max"] == 0.95


def test_fehlender_paint_block_schaltet_ab(tmp_path):
    (tmp_path / "rookie.json").write_text('{"name": "Rookie"}', encoding="utf-8")
    assert paintmask.paint_werte("rookie", tmp_path)["verfahren"] == "aus"

