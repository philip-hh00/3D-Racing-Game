"""UV-Abdeckung: welche Texel im Atlas ueberhaupt auf dem Modell landen."""
import numpy as np
import pytest
from PIL import Image

from trellis_pipeline import paintmask


def _dreieck_uv():
    """Ein Dreieck ueber das linke untere Viertel der Textur."""
    uv = np.array([[0.0, 0.0], [0.5, 0.0], [0.0, 0.5]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    return uv, faces


def test_abgedeckt_ist_wo_das_dreieck_liegt():
    uv, faces = _dreieck_uv()
    deck = paintmask.abdeckung(uv, faces, (64, 64), saum=0)
    # v = 0 ist in glTF unten, in einem Bild ist Zeile 0 oben.
    assert deck[63, 0], "Ecke bei u=0, v=0 gehoert nach unten links"
    assert deck[63, 30]
    assert deck[35, 0]
    assert not deck[0, 63], "gegenueberliegende Ecke ist unbenutzt"


def test_flaeche_stimmt_ungefaehr():
    uv, faces = _dreieck_uv()
    deck = paintmask.abdeckung(uv, faces, (128, 128), saum=0)
    # Halbes Quadrat von einem Viertel der Kantenlaenge = 1/8 der Flaeche
    assert deck.mean() == pytest.approx(0.125, abs=0.02)


def test_saum_erweitert_die_abdeckung():
    uv, faces = _dreieck_uv()
    eng = paintmask.abdeckung(uv, faces, (64, 64), saum=0)
    weit = paintmask.abdeckung(uv, faces, (64, 64), saum=3)
    assert weit.sum() > eng.sum()
    assert weit[eng].all(), "der Saum darf nichts wegnehmen"


def test_uv_ausserhalb_des_bildes_kippt_nichts():
    uv = np.array([[-0.5, -0.5], [1.5, 0.0], [0.0, 1.5]], dtype=np.float32)
    faces = np.array([[0, 1, 2]], dtype=np.int64)
    deck = paintmask.abdeckung(uv, faces, (32, 32), saum=0)
    assert deck.shape == (32, 32)
    assert deck.any()


def test_ohne_dreiecke_ist_nichts_abgedeckt():
    deck = paintmask.abdeckung(np.zeros((0, 2), dtype=np.float32),
                               np.zeros((0, 3), dtype=np.int64), (16, 16))
    assert not deck.any()


def _textur_mit_muell():
    """Lack auf der linken Haelfte, rechts unbenutzter Atlasbereich mit Muell.

    Genau die Lage im echten Modell: xatlas laesst grosse Teile des Atlas frei,
    und was dort steht, landet nie auf dem Fahrzeug - zaehlt aber mit, solange
    die Maske das ganze Bild ansieht.
    """
    rng = np.random.default_rng(5)
    bild = np.zeros((64, 64, 3), dtype=np.uint8)
    bild[:, :32] = (203, 60, 59)
    bild[:, 32:] = rng.integers(0, 255, size=(64, 32, 3), dtype=np.uint8)
    return Image.fromarray(bild, mode="RGB")


ROOKIE_PAINT = {
    "verfahren": "dominant", "referenzfarbe": [203, 60, 59], "farbtoleranz": 0.3,
    "helligkeit_min": 0.06, "helligkeit_max": 0.51, "kantenweichheit": 0.0,
    "deckkraft": 1.0, "saettigungsschwelle": 0.25,
}


def test_maske_ohne_abdeckung_zaehlt_den_muell_mit():
    """Der Ist-Zustand, gegen den der Fix gebaut ist."""
    maske = paintmask.maske(_textur_mit_muell(), ROOKIE_PAINT)
    assert maske[:, 32:].any(), "Vorbedingung: der Muellbereich trifft die Maske"


def test_abdeckung_schneidet_den_unbenutzten_atlas_weg():
    deck = np.zeros((64, 64), dtype=bool)
    deck[:, :32] = True
    maske = paintmask.maske(_textur_mit_muell(), ROOKIE_PAINT, abdeckung=deck)
    assert maske[:, :32].min() == pytest.approx(1.0), "der Lack bleibt vollstaendig"
    assert maske[:, 32:].max() == pytest.approx(0.0), "der unbenutzte Atlas ist weg"


def test_vereinzelt_misst_echtes_rauschen():
    """Das Mass muss eine geschlossene Flaeche von Salz und Pfeffer trennen."""
    flaeche = np.zeros((64, 64), dtype=np.float32)
    flaeche[16:48, 16:48] = 1.0
    assert paintmask.vereinzelt(flaeche) < 0.02

    rng = np.random.default_rng(11)
    salz = (rng.random((64, 64)) < 0.25).astype(np.float32)
    assert paintmask.vereinzelt(salz) > 0.5


def test_vereinzelt_ist_null_ohne_maske():
    assert paintmask.vereinzelt(np.zeros((8, 8), dtype=np.float32)) == 0.0


def test_kontrollbild_dunkelt_nur_das_unmaskierte_ab():
    bild = Image.fromarray(np.full((8, 8, 3), (200, 100, 50), dtype=np.uint8), "RGB")
    gewicht = np.zeros((8, 8), dtype=np.float32)
    gewicht[:, :4] = 1.0
    k = np.asarray(paintmask.kontrollbild(bild, gewicht))
    assert tuple(k[0, 0]) == (200, 100, 50), "Lack bleibt unveraendert"
    assert k[0, 7][0] < 60, "Nicht-Lack wird abgedunkelt"


def test_abdeckung_greift_auch_bei_kantenweichheit():
    """Die Weichzeichnung darf nicht wieder ueber die Abdeckung hinauslaufen."""
    deck = np.zeros((64, 64), dtype=bool)
    deck[:, :32] = True
    maske = paintmask.maske(_textur_mit_muell(),
                            dict(ROOKIE_PAINT, kantenweichheit=4.0), abdeckung=deck)
    assert maske[:, 32:].max() == pytest.approx(0.0)
