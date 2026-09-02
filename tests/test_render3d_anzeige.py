"""Die Anzeige: virtuelle Flaeche, Briefkasten, Mauskoordinaten.

Geprueft wird die **Rechnung**, nicht das Bild. Ein OpenGL-Kontext ist dafuer
nicht noetig und in der Testumgebung (SDL-Treiber ``dummy``) auch nicht zu
haben — genau deshalb muessen die Anzeigefunktionen ohne ihn durchlaufen,
statt zu scheitern.
"""
from __future__ import annotations

import pygame
import pytest

from src.core import display


# ---------------------------------------------------------------------------
# Die virtuelle Flaeche
# ---------------------------------------------------------------------------

def test_virtuelle_flaeche_hat_alphakanal():
    """Ohne Alphakanal deckt die Flaeche die 3D-Szene lueckenlos zu.

    Der ganze Bauplan haengt daran: HUD und Menues zeichnen auf diese Flaeche,
    und wo sie nichts zeichnen, muss die Welt darunter durchscheinen.
    """
    flaeche = display.virtual_surface()
    assert flaeche.get_flags() & pygame.SRCALPHA
    assert flaeche.get_size() == (display.VIRT_W, display.VIRT_H)


def test_halbdurchsichtiges_ueber_durchsichtigem_bleibt_gerade():
    """Begruendet die Alphamischung der Ueberlagerung.

    Legt man eine halbdurchsichtige Tafel auf eine **leere** Flaeche, koennte
    pygame zwei Ergebnisse liefern: gerades Alpha (200, 100, 50, 128) oder
    vormultipliziertes (100, 50, 25, 128). Bei vormultipliziertem muesste die
    Ueberlagerung mit ``ONE, ONE_MINUS_SRC_ALPHA`` mischen, sonst kaeme jede
    durchscheinende HUD-Tafel doppelt abgedunkelt heraus.

    pygame-ce 2.5.8 liefert gerades Alpha. Faellt dieser Test, ist die
    Mischfunktion in ``src/render3d/ansicht.py`` falsch und nicht dieser Test.
    """
    ziel = pygame.Surface((2, 2), pygame.SRCALPHA)
    ziel.fill((0, 0, 0, 0))
    tafel = pygame.Surface((2, 2), pygame.SRCALPHA)
    tafel.fill((200, 100, 50, 128))
    ziel.blit(tafel, (0, 0))
    assert tuple(ziel.get_at((0, 0))) == (200, 100, 50, 128)


# ---------------------------------------------------------------------------
# Briefkasten
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fenster, erwartet", [
    ((1920, 1080), (0, 0, 1920, 1080)),      # genau 16:9
    ((1600, 900), (0, 0, 1600, 900)),        # kleiner, aber 16:9
    ((1600, 1000), (0, 50, 1600, 900)),      # zu hoch: Balken oben und unten
    ((2000, 1000), (111, 0, 1777, 1000)),    # zu breit: Balken links und rechts
])
def test_ansichtsfenster_haelt_sechzehn_zu_neun(fenster, erwartet):
    assert display.ansichtsfenster(fenster) == erwartet


def test_ansichtsfenster_bleibt_bei_null_gross_genug():
    """Ein minimiertes Fenster meldet 0x0. Ein Ansichtsfenster der Breite 0
    ist fuer OpenGL ein Fehler, kein Sonderfall."""
    x, y, b, h = display.ansichtsfenster((0, 0))
    assert b >= 1 and h >= 1


# ---------------------------------------------------------------------------
# Mauskoordinaten
# ---------------------------------------------------------------------------

def test_scale_pos_rechnet_den_briefkasten_heraus(monkeypatch):
    """Im Briefkasten sitzt das Bild versetzt. Ohne Ausgleich greift die Maus
    im Menue um den halben Balken daneben."""
    monkeypatch.setattr(display, "_fenstergroesse", lambda: (1600, 1000))
    assert display.scale_pos((800, 500)) == (960, 540)    # Mitte bleibt Mitte
    assert display.scale_pos((0, 50)) == (0, 0)           # linke obere Bildecke
    assert display.scale_pos((1600, 950)) == (1920, 1080)  # rechte untere


def test_scale_pos_bei_gleicher_groesse_unveraendert(monkeypatch):
    monkeypatch.setattr(display, "_fenstergroesse", lambda: (1920, 1080))
    assert display.scale_pos((123, 456)) == (123, 456)


def test_mausereignisse_werden_mitgerechnet(monkeypatch):
    monkeypatch.setattr(display, "_fenstergroesse", lambda: (1600, 1000))
    roh = [pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (800, 500), "button": 1}),
           pygame.event.Event(pygame.MOUSEWHEEL, {"y": 1})]
    neu = display.remap_mouse_events(roh)
    assert neu[0].pos == (960, 540)
    assert neu[0].button == 1
    assert neu[1].type == pygame.MOUSEWHEEL


# ---------------------------------------------------------------------------
# Ohne OpenGL
# ---------------------------------------------------------------------------

def test_kontext_ohne_opengl_ist_none():
    """Der Testlauf hat kein OpenGL. Das darf kein Fehler sein, sondern heisst
    nur: es wird keine Welt gezeichnet."""
    assert display.kontext() is None


def test_bildaufbau_ohne_kontext_laeuft_durch():
    """``bild_beginnen`` muss die Flaeche auch ohne Kontext leeren — sonst
    stapeln sich in den Tests die Bilder uebereinander."""
    flaeche = display.virtual_surface()
    flaeche.fill((255, 0, 0, 255))
    display.bild_beginnen()
    assert tuple(flaeche.get_at((10, 10))) == (0, 0, 0, 0)
    display.bild_abschliessen()
