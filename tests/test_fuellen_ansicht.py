"""Fenster ohne Balken: Raster, sicherer Bereich, Maus, Zuschnitt, HUD-Anker.

Seit 1.1.0 fuellen 3D-Welt, Menuehintergrund-Video und HUD das ganze Fenster
(Produktentscheidung 10.10.2026). Menues bleiben ein mittiger 16:9-Bereich.
Geprueft wird die **Rechnung** — ein OpenGL-Kontext ist in der Testumgebung
nicht zu haben.
"""
from __future__ import annotations

import pygame
import pytest

from src.core import display
from src.hud.hud import HUD
from src.hud.minimap import Minimap
from src.ui import leinwand
from src.ui.video_ebene import zuschnitt

FENSTER = {
    "16:9": (1920, 1080),
    "16:9 klein": (1280, 720),
    "16:10": (1440, 900),
    "21:9": (2560, 1080),
    "5:4": (1280, 1024),
}


# ---------------------------------------------------------------------------
# Raster und sicherer Bereich
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fenster, erwartet", [
    ((1920, 1080), (1920, 1080)),
    ((1280, 720), (1920, 1080)),         # 16:9 in jeder Groesse: unveraendert
    ((3840, 2160), (1920, 1080)),
    ((1440, 900), (1920, 1200)),         # 16:10: hoeher
    ((2560, 1080), (2560, 1080)),        # 21:9: breiter
    ((1280, 1024), (1920, 1536)),        # 5:4
    ((0, 0), (1920, 1080)),              # minimiert
])
def test_raster_waechst_auf_einer_achse(fenster, erwartet):
    assert display.raster_groesse(fenster) == erwartet


@pytest.mark.parametrize("fenster", list(FENSTER.values()))
def test_raster_deckt_das_fenster_und_haelt_das_seitenverhaeltnis(fenster):
    rb, rh = display.raster_groesse(fenster)
    assert rb >= 1920 and rh >= 1080
    assert abs(rb / rh - fenster[0] / fenster[1]) < 0.002


def test_sicherer_bereich_ist_mittig_1920_mal_1080():
    assert display.sicherer_rand((1920, 1080)) == pygame.Rect(0, 0, 1920, 1080)
    assert display.sicherer_rand((1920, 1200)) == pygame.Rect(0, 60, 1920, 1080)
    assert display.sicherer_rand((2560, 1080)) == pygame.Rect(320, 0, 1920, 1080)


def test_sicherer_bereich_ist_bei_sechzehn_zu_neun_die_flaeche_selbst():
    flaeche = leinwand.Flaeche((1920, 1080), pygame.SRCALPHA)
    assert display.sicherer_bereich(flaeche) is flaeche


def test_sicherer_bereich_ist_eine_sicht_auf_dieselben_bildpunkte():
    voll = leinwand.Flaeche((2560, 1080), pygame.SRCALPHA)
    voll.schmutz_verfolgen()
    sicher = display.sicherer_bereich(voll)
    assert sicher.get_size() == (1920, 1080)
    sicher.fill((255, 0, 0, 255), (0, 0, 10, 10))
    assert tuple(voll.get_at((320, 0))) == (255, 0, 0, 255)      # Versatz 320
    assert tuple(voll.get_at((319, 0))) == (0, 0, 0, 0)
    assert display.sicherer_bereich(voll) is sicher               # zwischengespeichert


# ---------------------------------------------------------------------------
# Maus
# ---------------------------------------------------------------------------

def _maus(monkeypatch, fenster):
    monkeypatch.setattr(display, "_fenstergroesse", lambda: fenster)


def test_maus_bei_sechzehn_zu_neun_unveraendert(monkeypatch):
    _maus(monkeypatch, (1920, 1080))
    assert display.scale_pos((123, 456)) == (123, 456)
    roh = [pygame.event.Event(pygame.MOUSEMOTION, {"pos": (5, 6), "rel": (1, 2), "buttons": (0, 0, 0)})]
    assert display.remap_mouse_events(roh) is roh


def test_maus_16_zu_9_klein_skaliert_wie_bisher(monkeypatch):
    _maus(monkeypatch, (1280, 720))
    assert display.scale_pos((640, 360)) == (960, 540)
    assert display.scale_pos((1280, 720)) == (1920, 1080)


@pytest.mark.parametrize("fenster", [(1440, 900), (2560, 1080), (1280, 1024)])
def test_maus_mitte_bleibt_mitte_und_ecken_des_sicheren_bereichs_stimmen(monkeypatch, fenster):
    _maus(monkeypatch, fenster)
    fb, fh = fenster
    assert display.scale_pos((fb // 2, fh // 2)) == (960, 540)
    rb, rh = display.raster_groesse(fenster)
    sicher = display.sicherer_rand((rb, rh))
    # Fensterpunkt der linken oberen / rechten unteren Ecke des sicheren Bereichs
    lo = (round(sicher.left * fb / rb), round(sicher.top * fh / rh))
    ru = (round(sicher.right * fb / rb), round(sicher.bottom * fh / rh))
    x, y = display.scale_pos(lo)
    assert abs(x) <= 1 and abs(y) <= 1
    x, y = display.scale_pos(ru)
    assert abs(x - 1920) <= 2 and abs(y - 1080) <= 2


def test_maus_neben_dem_sicheren_bereich_liegt_ausserhalb(monkeypatch):
    """Auf dem Rand neben den Menues darf kein Knopf getroffen werden."""
    _maus(monkeypatch, (2560, 1080))
    assert display.scale_pos((0, 500))[0] < 0
    assert display.scale_pos((2559, 500))[0] > 1920
    _maus(monkeypatch, (1440, 900))
    assert display.scale_pos((700, 0))[1] < 0
    assert display.scale_pos((700, 899))[1] > 1080


def test_mausereignisse_16_zu_10_und_21_zu_9(monkeypatch):
    _maus(monkeypatch, (1440, 900))
    ev = display.remap_mouse_events([
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (720, 450), "button": 1}),
        pygame.event.Event(pygame.MOUSEMOTION, {"pos": (720, 450), "rel": (3, 3), "buttons": (0, 0, 0)}),
        pygame.event.Event(pygame.MOUSEWHEEL, {"y": 1})])
    assert ev[0].pos == (960, 540) and ev[0].button == 1
    assert ev[1].pos == (960, 540) and ev[1].rel == (4, 4)       # 3 * 1,333
    assert ev[2].type == pygame.MOUSEWHEEL
    _maus(monkeypatch, (2560, 1080))
    ev = display.remap_mouse_events([
        pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (1280, 540), "button": 1})])
    assert ev[0].pos == (960, 540)


def test_ansichtsfenster_bleibt_der_sichere_bereich_in_fensterpunkten():
    assert display.ansichtsfenster((1440, 900)) == (0, 45, 1440, 810)
    assert display.vollbild((1440, 900)) == (0, 0, 1440, 900)
    assert display.vollbild((0, 0))[2:] == (1, 1)


# ---------------------------------------------------------------------------
# Video: Zuschnitt statt Strecken
# ---------------------------------------------------------------------------

def test_zuschnitt_16_zu_9_zeigt_alles():
    assert zuschnitt((1920, 1080), (1920, 1080)) == (1.0, 1.0)
    assert zuschnitt((1280, 720), (1920, 1080)) == (1.0, 1.0)


def test_zuschnitt_breiter_schneidet_oben_und_unten():
    ax, ay = zuschnitt((2560, 1080), (1920, 1080))
    assert ax == 1.0
    assert ay == pytest.approx((16 / 9) / (2560 / 1080))


def test_zuschnitt_hoeher_schneidet_links_und_rechts():
    ax, ay = zuschnitt((1440, 900), (1920, 1080))
    assert ay == 1.0
    assert ax == pytest.approx(1.6 / (16 / 9))
    assert 0.89 < ax < 0.91


@pytest.mark.parametrize("fenster", list(FENSTER.values()))
def test_zuschnitt_streckt_nie(fenster):
    """Sichtbarer Ausschnitt in Videopixeln hat genau das Seitenverhaeltnis des Fensters."""
    ax, ay = zuschnitt(fenster, (1920, 1080))
    assert max(ax, ay) == 1.0
    assert (1920 * ax) / (1080 * ay) == pytest.approx(fenster[0] / fenster[1])


# ---------------------------------------------------------------------------
# Rand fortsetzen (Zustaende ohne Video)
# ---------------------------------------------------------------------------

def test_rand_fortsetzen_fuellt_links_und_rechts_aus_der_kante():
    voll = leinwand.Flaeche((2560, 1080), pygame.SRCALPHA)
    voll.schmutz_verfolgen()
    sicher = display.sicherer_bereich(voll)
    sicher.fill((10, 20, 30, 255))
    voll.rand_fortsetzen(display.sicherer_rand(voll.get_size()))
    for x in (0, 150, 319, 2240, 2400, 2559):
        assert tuple(voll.get_at((x, 500))) == (10, 20, 30, 255)


def test_rand_fortsetzen_fuellt_oben_und_unten_und_haelt_verlaeufe():
    voll = leinwand.Flaeche((1920, 1200), pygame.SRCALPHA)
    voll.schmutz_verfolgen()
    sicher = display.sicherer_bereich(voll)
    for y in range(1080):                                  # senkrechter Verlauf
        sicher.fill((y % 256, 0, 0, 255), (0, y, 1920, 1))
    voll.rand_fortsetzen(display.sicherer_rand(voll.get_size()))
    assert tuple(voll.get_at((100, 10))) == (0, 0, 0, 255)           # Zeile 0 des Verlaufs
    assert tuple(voll.get_at((100, 1190)))[0] == 1079 % 256
    assert voll.schmutz_rechtecke() is None or voll.schmutz_rechtecke()   # als geaendert gemeldet


def test_rand_fortsetzen_laesst_durchsichtiges_durchsichtig():
    voll = leinwand.Flaeche((2560, 1080), pygame.SRCALPHA)
    voll.schmutz_verfolgen()
    voll.rand_fortsetzen(display.sicherer_rand(voll.get_size()))
    assert tuple(voll.get_at((10, 10))) == (0, 0, 0, 0)


def test_rand_fortsetzen_mit_skala():
    voll = leinwand.Flaeche((1920, 1200), pygame.SRCALPHA, 0.75)
    sicher = display.sicherer_bereich(voll)
    sicher.fill((9, 9, 9, 255))
    voll.rand_fortsetzen(display.sicherer_rand(voll.get_size()))
    assert tuple(pygame.Surface.get_at(voll, (10, 10))) == (9, 9, 9, 255)
    assert tuple(pygame.Surface.get_at(voll, (10, 890))) == (9, 9, 9, 255)


# ---------------------------------------------------------------------------
# HUD haengt an den echten Raendern
# ---------------------------------------------------------------------------

def _hud_flaeche(breite, hoehe):
    hud = HUD()
    hud._position, hud._total_vehicles = 1, 4
    hud._current_lap, hud._total_laps = 1, 3
    surf = pygame.Surface((breite, hoehe), pygame.SRCALPHA)
    hud.render(surf)
    return surf


def _belegt(surf, rect):
    sub = surf.subsurface(rect)
    return any(sub.get_at((x, y))[3] > 0
               for x in range(0, rect.width, 2) for y in range(0, rect.height, 2))


@pytest.mark.parametrize("breite, hoehe", [(1920, 1080), (2560, 1080), (1920, 1200)])
def test_hud_panel_oben_rechts_sitzt_am_echten_rand(breite, hoehe):
    surf = _hud_flaeche(breite, hoehe)
    assert _belegt(surf, pygame.Rect(breite - 280, 10, 270, 120))      # Panel am rechten Rand
    assert not _belegt(surf, pygame.Rect(breite - 1700, 10, 600, 120))  # nichts in der Mitte der Breite


@pytest.mark.parametrize("breite, hoehe", [(1920, 1080), (2560, 1080), (1920, 1200)])
def test_armaturenbrett_sitzt_unten_mittig(breite, hoehe):
    surf = _hud_flaeche(breite, hoehe)
    assert _belegt(surf, pygame.Rect(breite // 2 - 200, hoehe - 130, 400, 110))
    assert not _belegt(surf, pygame.Rect(breite // 2 - 200, hoehe - 400, 400, 200))


@pytest.mark.parametrize("breite, hoehe", [(1920, 1080), (2560, 1080), (1920, 1200)])
def test_minimap_sitzt_unten_links_und_im_splitscreen_unten_mittig(breite, hoehe):
    mm = Minimap.__new__(Minimap)
    mm.anker = "links"
    assert mm.platz(breite, hoehe) == (20, hoehe - Minimap.PANEL_H - 20)
    mm.anker = "mitte"
    x, y = mm.platz(breite, hoehe)
    assert x == (breite - Minimap.PANEL_W) // 2
    assert y + Minimap.PANEL_H + 20 == hoehe


def test_minimap_bei_sechzehn_zu_neun_wie_bisher():
    mm = Minimap.__new__(Minimap)
    mm.anker = "links"
    assert mm.platz(1920, 1080) == (20, 1080 - Minimap.PANEL_H - 20)
    mm.anker = "mitte"
    assert mm.platz(1920, 1080) == (1920 // 2 - Minimap.PANEL_W // 2, 1080 - Minimap.PANEL_H - 20)


# ---------------------------------------------------------------------------
# Bildaufbau
# ---------------------------------------------------------------------------

class _Automat:
    def __init__(self, zustand):
        self.current = zustand
        self.bekam = None

    def render(self, flaeche):
        self.bekam = flaeche


class _Menue:
    pass


class _Rennen:
    volle_flaeche = True


def test_zustand_zeichnen_gibt_menues_den_sicheren_bereich_und_dem_rennen_alles(monkeypatch):
    voll = leinwand.Flaeche((2560, 1080), pygame.SRCALPHA)
    voll.schmutz_verfolgen()
    monkeypatch.setattr(display, "virtual_surface", lambda: voll)
    a = _Automat(_Menue())
    display.zustand_zeichnen(a)
    assert a.bekam.get_size() == (1920, 1080) and a.bekam is not voll
    a = _Automat(_Rennen())
    display.zustand_zeichnen(a)
    assert a.bekam is voll


def test_zustand_zeichnen_bei_sechzehn_zu_neun_ist_unveraendert(monkeypatch):
    voll = leinwand.Flaeche((1920, 1080), pygame.SRCALPHA)
    monkeypatch.setattr(display, "virtual_surface", lambda: voll)
    a = _Automat(_Menue())
    display.zustand_zeichnen(a)
    assert a.bekam is voll
