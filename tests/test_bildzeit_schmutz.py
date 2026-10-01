"""Schmutzverfolgung der Oberfläche: nur anfassen, was sich geändert hat.

Die virtuelle Fläche wird jedes Bild geleert und als Textur hochgeladen. In
4K sind das zweimal 33 MB, obwohl das HUD ein Viertel der Fläche belegt. Die
Fläche merkt sich deshalb, wohin gezeichnet wurde (Raster aus Zellen), leert
nur das und lädt nur das hoch.
"""
import numpy as np
import pygame
import pytest

from src.render3d import ansicht
from src.ui import leinwand, zeichnen


@pytest.fixture(autouse=True)
def _pygame():
    pygame.init()
    yield


def _verfolgt(groesse=(640, 360), skala=1.0):
    f = leinwand.Flaeche(groesse, pygame.SRCALPHA, skala)
    f.schmutz_verfolgen()
    return f


def _abdeckung(rects, groesse):
    m = np.zeros((groesse[1], groesse[0]), bool)
    for r in rects:
        m[r.top:r.bottom, r.left:r.right] = True
    return m


def _nicht_leer(f):
    a = pygame.surfarray.pixels_alpha(f)
    out = (np.asarray(a) != 0).T.copy()
    del a
    return out


def test_neue_flaeche_ist_ganz_schmutzig():
    f = _verfolgt()
    assert f.schmutz_rechtecke() is None


def test_nach_dem_hochladen_ist_nichts_schmutzig():
    f = _verfolgt()
    f.schmutz_hochgeladen()
    assert f.schmutz_rechtecke() == []


@pytest.mark.parametrize("skala", [1.0, 2.0])
def test_zeichnen_markiert_nur_die_betroffene_gegend(skala):
    f = _verfolgt(skala=skala)
    f.schmutz_hochgeladen()
    f.blit(pygame.Surface((20, 10)), (100, 50))
    zeichnen.rect(f, (255, 0, 0, 255), (300, 200, 30, 20))
    zeichnen.line(f, (0, 255, 0), (5, 5), (40, 5), 3)
    zeichnen.circle(f, (0, 0, 255), (500, 100), 12)
    f.fill((1, 2, 3, 255), (200, 300, 10, 10))
    rects = f.schmutz_rechtecke()
    assert rects, "es wurde gezeichnet"
    w, h = f.bildpunkte()
    abdeckung = _abdeckung(rects, (w, h))
    assert abdeckung.sum() < w * h * 0.5, "nicht die ganze Fläche"
    # Alles, was gezeichnet wurde, liegt in den gemeldeten Rechtecken.
    assert not (_nicht_leer(f) & ~abdeckung).any()


def test_loeschen_stellt_durchsichtig_her_und_merkt_die_alte_gegend():
    f = _verfolgt()
    f.schmutz_hochgeladen()
    zeichnen.rect(f, (255, 0, 0, 255), (300, 200, 30, 20))
    f.schmutz_loeschen()
    assert not _nicht_leer(f).any()
    # Die Textur zeigt noch das alte Rot: auch diese Gegend muss hoch.
    rects = f.schmutz_rechtecke()
    assert rects
    assert _abdeckung(rects, f.bildpunkte())[210, 310]


def test_loeschen_laesst_ungezeichnetes_unangetastet_und_schnell_leer():
    f = _verfolgt()
    f.schmutz_hochgeladen()
    f.schmutz_loeschen()
    f.schmutz_loeschen()
    assert f.schmutz_rechtecke() == []


def test_unverfolgte_flaeche_meldet_alles():
    f = leinwand.Flaeche((64, 36), pygame.SRCALPHA, 1.0)
    assert f.schmutz_rechtecke() is None
    f.schmutz_loeschen()                      # fuellt einfach ganz
    assert not _nicht_leer(f).any()


def test_zu_viel_schmutz_wird_zu_einem_ganzen_hochladen():
    f = _verfolgt()
    f.schmutz_hochgeladen()
    f.fill((9, 9, 9, 255))
    assert f.schmutz_rechtecke() is None


def test_alles_markieren_zwingt_ganzes_hochladen():
    f = _verfolgt()
    f.schmutz_hochgeladen()
    f.schmutz_alles()
    assert f.schmutz_rechtecke() is None


def test_rechtecke_decken_zellen_lueckenlos_ab_und_liegen_in_der_flaeche():
    f = _verfolgt((1920, 1080))
    f.schmutz_hochgeladen()
    zeichnen.rect(f, (255, 0, 0, 255), (1900, 1060, 20, 20))
    zeichnen.rect(f, (255, 0, 0, 255), (0, 0, 5, 5))
    rects = f.schmutz_rechtecke()
    for r in rects:
        assert r.left >= 0 and r.top >= 0 and r.right <= 1920 and r.bottom <= 1080
    a = _abdeckung(rects, (1920, 1080))
    assert a[1079, 1919] and a[0, 0]


# -- Hochladen ----------------------------------------------------------------

class _Textur:
    """Eine Textur aus Bytes, die Teilschreiben kennt (wie moderngl)."""

    def __init__(self, groesse):
        self.size = groesse
        self.feld = np.zeros((groesse[1], groesse[0], 4), np.uint8)
        self.schreibungen = []

    def write(self, daten, viewport=None):
        a = np.frombuffer(daten, np.uint8)
        if viewport is None:
            self.feld[...] = a.reshape(self.feld.shape)
            self.schreibungen.append(None)
        else:
            x, y, w, h = viewport
            self.feld[y:y + h, x:x + w] = a.reshape(h, w, 4)
            self.schreibungen.append(tuple(viewport))

    def release(self):
        pass


class _Programm(dict):
    def __getitem__(self, k):
        return self.setdefault(k, type("U", (), {"value": None})())


def _ueberlagerung(groesse):
    u = ansicht.Ueberlagerung.__new__(ansicht.Ueberlagerung)
    u._ctx = None
    u._programm = _Programm()
    u._textur = _Textur(groesse)
    u._textur_neu = True
    return u


def _bytes(f):
    w, h = f.bildpunkte()
    return np.frombuffer(memoryview(f.get_view("0")), np.uint8).reshape(h, w, 4).copy()


def test_teilweises_hochladen_ergibt_dieselbe_textur_wie_ganzes():
    f = _verfolgt((640, 360))
    u = _ueberlagerung((640, 360))
    u.aktualisieren(f)                              # erstes Mal: ganz
    assert u._textur.schreibungen == [None]
    for bild in range(6):
        f.schmutz_loeschen()
        zeichnen.rect(f, (200, 30 * bild, 0, 255), (10 + 90 * bild, 20 + 40 * bild, 50, 30))
        zeichnen.circle(f, (0, 255, 0, 255), (320, 300), 10 + bild)
        f.blit(pygame.Surface((12, 12)), (600, 340))
        u._textur.schreibungen.clear()
        u.aktualisieren(f)
        assert u._textur.schreibungen, "es gab etwas zu schreiben"
        assert None not in u._textur.schreibungen, "nur Teile, nicht ganz"
        assert np.array_equal(u._textur.feld, _bytes(f)), f"Bild {bild}"


def test_ohne_aenderung_wird_nichts_geschrieben():
    f = _verfolgt((320, 180))
    u = _ueberlagerung((320, 180))
    u.aktualisieren(f)
    u._textur.schreibungen.clear()
    f.schmutz_loeschen()
    f.schmutz_loeschen()
    u.aktualisieren(f)
    assert u._textur.schreibungen == []


def test_neue_textur_wird_ganz_beschrieben():
    f = _verfolgt((320, 180))
    u = _ueberlagerung((320, 180))
    u.aktualisieren(f)
    u._textur = _Textur((320, 180))                 # etwa nach einer Groessenaenderung
    u._textur_neu = True
    f.schmutz_loeschen()
    zeichnen.rect(f, (255, 0, 0, 255), (10, 10, 10, 10))
    u.aktualisieren(f)
    assert u._textur.schreibungen == [None]
    assert np.array_equal(u._textur.feld, _bytes(f))


def test_unverfolgte_flaeche_wird_immer_ganz_hochgeladen():
    f = leinwand.Flaeche((320, 180), pygame.SRCALPHA, 1.0)
    u = _ueberlagerung((320, 180))
    u.aktualisieren(f)
    u._textur.schreibungen.clear()
    u.aktualisieren(f)
    assert u._textur.schreibungen == [None]


def test_gewoehnliche_pygame_flaeche_geht_wie_vorher():
    f = pygame.Surface((320, 180), pygame.SRCALPHA)
    f.fill((1, 2, 3, 4))
    u = _ueberlagerung((320, 180))
    u.aktualisieren(f)
    assert u._textur.schreibungen == [None]
