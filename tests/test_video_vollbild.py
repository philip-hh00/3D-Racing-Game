"""Menue in Vollbild: Videobild, Vorschau und Tafeln ohne Arbeit je Bild.

Hintergrund (gemeldet 01.10.2026): in 1440p-Vollbild fiel die Bildrate im Menue
auf 9-30 Bilder. Ursachen: jedes Videobild wurde im Hauptfaden entschluesselt,
skaliert und kopiert, ein Abdunkler wurde je Bild neu angelegt, die 3D-Vorschau
in Rastergroesse jedes Mal hochgerechnet und jede Tafel je Bild neu gezeichnet.
"""
from __future__ import annotations

import time

import numpy as np
import pygame
import pytest

from src.ui import leinwand, theme
from src.ui.video_player import VideoPlayer, _HAVE_CV2

pytestmark = pytest.mark.skipif(not _HAVE_CV2, reason="OpenCV fehlt")

FARBEN_BGR = [(0, 0, 255), (0, 255, 0), (255, 0, 0)]      # rot, gruen, blau


@pytest.fixture
def clip(tmp_path):
    import cv2
    pfad = str(tmp_path / "t.mp4")
    w = cv2.VideoWriter(pfad, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (160, 90))
    for i in range(6):
        w.write(np.full((90, 160, 3), FARBEN_BGR[0], dtype=np.uint8))
    w.release()
    return pfad


@pytest.fixture
def skala15():
    alt = leinwand.skala()
    leinwand.skala_setzen(1.5)
    yield 1.5
    leinwand.skala_setzen(alt)


def _mitte(surf):
    return tuple(pygame.Surface.get_at(surf, (pygame.Surface.get_width(surf) // 2,
                                               pygame.Surface.get_height(surf) // 2)))[:3]


def test_videobild_kommt_in_bildpunkten_mit_richtigen_farben(clip, skala15):
    v = VideoPlayer(clip, (160, 90), faden=False)
    try:
        f = v.get_surface()
        assert isinstance(f, leinwand.Flaeche)
        assert f.get_size() == (160, 90)                    # Raster
        assert f.bildpunkte() == (240, 135)                 # Bildpunkte
        r, g, b = _mitte(f)
        assert r > 200 and g < 60 and b < 60                # rot, nicht blau
    finally:
        v.close()


def test_ohne_neues_bild_bleibt_dieselbe_flaeche(clip, skala15):
    """Skaliert wird einmal je Quellbild: ohne Fortschritt dieselbe Flaeche."""
    v = VideoPlayer(clip, (160, 90), faden=False)
    try:
        a = v.get_surface()
        v.update(0.001)                      # weniger als ein Bild
        v.update(0.001)
        assert v.get_surface() is a
        v.update(1 / 30 + 0.001)             # ein Bild weiter
        assert v.get_surface() is not a
    finally:
        v.close()


def test_faden_liefert_bilder_und_wird_beim_schliessen_beendet(clip, skala15):
    v = VideoPlayer(clip, (160, 90), faden=True)
    erstes = v.get_surface()
    gewechselt = False
    for _ in range(100):
        time.sleep(0.01)
        v.update(1 / 30 + 0.001)
        if v.get_surface() is not erstes:
            gewechselt = True
            break
    assert gewechselt
    faden = v._faden
    assert faden is not None and faden.is_alive()
    v.close()
    assert not faden.is_alive()
    assert v.get_surface() is None


def test_abdunkeln_wird_im_entschluesseln_verrechnet(clip, skala15):
    v = VideoPlayer(clip, (160, 90), faden=False, abdunkeln=("seite", 150))
    try:
        r0 = _mitte(v.get_surface())[0]
        assert v.bild_schluessel == "seite"
        # Wie ein schwarzer Ueberzug mit Alpha 150: Rot * 105/255.
        assert abs(r0 - 255 * 105 / 255) <= 12
        v.abdunkeln_setzen(None)
        v.update(1 / 30 + 0.001)
        assert v.bild_schluessel is None
        assert _mitte(v.get_surface())[0] > 200
    finally:
        v.close()


def test_abdunkeln_mit_feld_wirkt_je_ort(clip, skala15):
    # links nichts, rechts voll schwarz
    alpha = np.zeros((9, 16), dtype=np.uint8)
    alpha[:, 8:] = 255
    v = VideoPlayer(clip, (160, 90), faden=False, abdunkeln=("rand", alpha))
    try:
        f = v.get_surface()
        links = tuple(pygame.Surface.get_at(f, (10, 60)))[:3]
        rechts = tuple(pygame.Surface.get_at(f, (230, 60)))[:3]
        assert links[0] > 200
        assert rechts[0] < 20
    finally:
        v.close()


def test_aus_rgba_rechnet_nicht_hoch_und_merkt_sich_den_puffer(skala15):
    pixel = bytes([200, 10, 10, 255]) * (30 * 20)
    a = leinwand.aus_rgba(pixel, (30, 20))
    assert a.bildpunkte() == (30, 20)                       # unveraendert
    assert a.skala == 1.5
    assert leinwand.aus_rgba(pixel, (30, 20)) is a          # kein neuer Aufbau
    assert leinwand.aus_rgba(bytes(bytearray(pixel)), (30, 20)) is not a


def test_px_groesse_folgt_der_skala(skala15):
    assert leinwand.px_groesse((100, 50)) == (150, 75)


def test_tafel_wird_je_groesse_und_skala_nur_einmal_gebaut(skala15):
    ziel = leinwand.flaeche((400, 300), pygame.SRCALPHA)
    theme._panel_cache.clear()
    theme.panel(ziel, pygame.Rect(10, 10, 200, 100))
    n = len(theme._panel_cache)
    erste = list(theme._panel_cache.values())[0][0]
    theme.panel(ziel, pygame.Rect(40, 40, 200, 100))        # anderer Ort, gleiche Karte
    assert len(theme._panel_cache) == n
    assert list(theme._panel_cache.values())[0][0] is erste


def test_tafel_ergibt_dieselbe_farbe_wie_die_gewoehnliche_mischung():
    alt = leinwand.skala()
    leinwand.skala_setzen(1.0)
    try:
        grund = (40, 60, 90, 255)
        a = leinwand.flaeche((120, 80), pygame.SRCALPHA)
        a.fill(grund)
        theme._panel_cache.clear()
        theme.panel(a, pygame.Rect(10, 10, 100, 60), alpha=200, fill=(20, 30, 50))
        b = leinwand.flaeche((120, 80), pygame.SRCALPHA)
        b.fill(grund)
        ueberzug = pygame.Surface((100, 60), pygame.SRCALPHA)
        ueberzug.fill((20, 30, 50, 200))
        b.blit(ueberzug, (10, 10))
        pa = tuple(pygame.Surface.get_at(a, (60, 40)))
        pb = tuple(pygame.Surface.get_at(b, (60, 40)))
        assert all(abs(x - y) <= 2 for x, y in zip(pa, pb))
    finally:
        leinwand.skala_setzen(alt)


def test_menueschale_oeffnet_das_video_auch_in_skalierter_flaeche(skala15):
    """Regression: ein Fehler beim Aufbau des Randueberzugs (surfarray kennt die
    Rastergroesse der Flaeche nicht) wurde still geschluckt, das Menue fiel auf
    den Verlauf zurueck — nur bei Skala != 1, also nur im Vollbild."""
    import os
    from src.core.state_machine import StateMachine
    from src.states.menu_shell_state import MenuShellState
    if not os.path.isfile(os.path.join("data", "menu", "Einzelspieler.mp4")):
        pytest.skip("Menuevideo fehlt")
    ms = MenuShellState(StateMachine())
    ms.tab = 0
    ms._ensure_video("Einzelspieler")
    try:
        assert ms._video is not None
        assert ms._ueberzug_wunsch()[0] == "rand"
    finally:
        ms.exit()
