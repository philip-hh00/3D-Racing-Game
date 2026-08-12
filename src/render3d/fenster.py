"""Das Fenster: pygame öffnet es, ModernGL zeichnet hinein.

Beide teilen sich denselben OpenGL-Kontext. pygame behält damit Fenster,
Ereignisse, Eingabe und Ton — nur das Zeichnen wandert zu OpenGL.

Der Haken, der die ganze Bauweise bestimmt: mit ``pygame.OPENGL`` ist die
Fläche aus ``set_mode`` **nicht mehr bemalbar**. ``blit`` und ``draw`` darauf
tun nichts Sichtbares mehr. Deshalb bekommt die Oberfläche eine eigene Fläche
in der virtuellen Auflösung, auf die sie wie bisher zeichnet; die wird am Ende
des Bildes als Textur darübergelegt (siehe :mod:`src.render3d.ansicht`).

Genau so arbeitet ``src/core/display.py`` ohnehin schon: dort entsteht seit
jeher eine virtuelle Fläche von 1920×1080, die erst zum Schluss auf die
Fenstergröße skaliert wird.
"""
from __future__ import annotations

import pygame

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Auflösung, in der die Oberfläche zeichnet. Muss zu ``settings.SCREEN_*``
#: passen, sonst sitzt das HUD verschoben.
VIRTUELL = (1920, 1080)


def oeffnen(groesse: tuple[int, int] = (1600, 900),
            titel: str = "3D-Racing-Game",
            vsync: bool = True):
    """Fenster mit OpenGL-Kontext öffnen.

    Liefert ``(kontext, hud_flaeche)``. Die HUD-Fläche hat die virtuelle
    Auflösung und einen Alphakanal — sie ist das, worauf der vorhandene
    Oberflächencode zeichnet.
    """
    pygame.display.set_mode(groesse, pygame.OPENGL | pygame.DOUBLEBUF
                            | pygame.RESIZABLE, vsync=1 if vsync else 0)
    pygame.display.set_caption(titel)

    kontext = moderngl.create_context()
    hud = pygame.Surface(VIRTUELL, pygame.SRCALPHA)
    return kontext, hud


def sichtfeld_anpassen(kontext, groesse: tuple[int, int]) -> None:
    """Nach einer Größenänderung des Fensters.

    Ohne das zeichnet OpenGL weiter in den alten Ausschnitt und das Bild wird
    beschnitten oder gestaucht.
    """
    kontext.viewport = (0, 0, max(1, groesse[0]), max(1, groesse[1]))


def seitenverhaeltnis(groesse: tuple[int, int]) -> float:
    return max(1, groesse[0]) / max(1, groesse[1])
