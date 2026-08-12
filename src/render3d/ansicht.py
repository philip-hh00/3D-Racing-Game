"""Die 3D-Ansicht und die Überlagerung mit der pygame-Fläche.

Der Kern der ganzen Portierung steckt hier, und er ist eine Zeile Idee:

``src/core/display.py`` zeichnet seit jeher auf eine **virtuelle Fläche von
1920×1080** und skaliert sie erst am Ende auf das Fenster. HUD, Menüs, Minimap
und alle Labore malen dorthin — rund 250 ``blit``-, 220 ``rect``- und 110
``line``-Aufrufe. Statt diese Fläche auf das Fenster zu bringen, wird sie zur
**Textur** und über die 3D-Szene gelegt.

Damit bleibt der gesamte vorhandene Oberflächencode unangetastet. Er weiß nicht
einmal, dass darunter etwas anderes liegt als vorher.

Der Preis ist ein Texturupload von 1920×1080 je Bild, also 8,3 MB. Bei 60
Bildern je Sekunde sind das 500 MB/s über PCIe — messbar, aber unkritisch. Wer
ihn sparen will, ruft :meth:`Ansicht3D.hud_zeichnen` mit ``geaendert=False``,
solange sich am HUD nichts getan hat; dann wird die vorhandene Textur erneut
verwendet.
"""
from __future__ import annotations

import numpy as np

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


#: Zwei Dreiecke, die den ganzen Bildschirm ausfüllen, als Streifen.
#: Positionen in Clipkoordinaten, Texturkoordinaten dazu.
_VOLLBILD = np.array([
    # x,     y,    u,   v
    [-1.0, -1.0, 0.0, 0.0],
    [+1.0, -1.0, 1.0, 0.0],
    [-1.0, +1.0, 0.0, 1.0],
    [+1.0, +1.0, 1.0, 1.0],
], dtype="f4")

_UEBERLAGERUNG_VERTEX = """
#version 330
in vec2 in_position;
in vec2 in_uv;
out vec2 uv;
void main() {
    uv = in_uv;
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

_UEBERLAGERUNG_FRAGMENT = """
#version 330
uniform sampler2D flaeche;
in vec2 uv;
out vec4 farbe;
void main() {
    farbe = texture(flaeche, uv);
}
"""


def flaeche_als_bytes(flaeche) -> bytes:
    """Eine pygame-Fläche als RGBA-Bytes in OpenGL-Zeilenreihenfolge.

    ``flipped=True`` ist keine Geschmacksfrage: pygame legt Zeile 0 nach oben,
    OpenGL erwartet sie unten. Ohne das steht das HUD auf dem Kopf — dieselbe
    Falle wie bei den Modelltexturen, siehe ``VEREINBARUNGEN.md``.
    """
    import pygame

    return pygame.image.tobytes(flaeche, "RGBA", True)


class Ueberlagerung:
    """Legt eine pygame-Fläche als Textur über das fertige 3D-Bild."""

    def __init__(self, ctx: "moderngl.Context", groesse: tuple[int, int]) -> None:
        self._ctx = ctx
        self._programm = ctx.program(vertex_shader=_UEBERLAGERUNG_VERTEX,
                                     fragment_shader=_UEBERLAGERUNG_FRAGMENT)
        self._vbo = ctx.buffer(_VOLLBILD.tobytes())
        self._vao = ctx.vertex_array(self._programm, [
            (self._vbo, "2f 2f", "in_position", "in_uv"),
        ])
        self._textur = ctx.texture(groesse, 4)
        # Keine Glättung: die Fläche hat genau die Auflösung, in der sie
        # gezeichnet wurde. Interpolation würde nur Text verwaschen.
        self._textur.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self._programm["flaeche"].value = 0

    @property
    def groesse(self) -> tuple[int, int]:
        return self._textur.size

    def aktualisieren(self, flaeche) -> None:
        """Den Inhalt der pygame-Fläche in die Textur schreiben."""
        if tuple(flaeche.get_size()) != tuple(self._textur.size):
            raise ValueError(
                f"Flaeche ist {flaeche.get_size()}, Textur {self._textur.size} - "
                "beide muessen die virtuelle Aufloesung haben")
        self._textur.write(flaeche_als_bytes(flaeche))

    def zeichnen(self) -> None:
        """Über das bestehende Bild legen.

        Ohne Tiefentest: die Überlagerung liegt immer obenauf, unabhängig
        davon, wie nah ein Fahrzeug an der Kamera steht. Mit Alphamischung,
        damit die durchsichtigen Teile des HUD die Szene durchscheinen lassen.
        """
        self._ctx.disable(moderngl.DEPTH_TEST)
        self._ctx.enable(moderngl.BLEND)
        self._ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self._textur.use(0)
        self._vao.render(moderngl.TRIANGLE_STRIP)

    def freigeben(self) -> None:
        for teil in (self._vao, self._vbo, self._textur, self._programm):
            teil.release()


#: Farbe des Himmels, solange es keine Umgebungskarte gibt. Kein Schwarz:
#: metallische Flächen spiegeln die Umgebung, und vor Schwarz wirken sie tot.
HIMMEL = (0.53, 0.68, 0.85)


class Ansicht3D:
    """Ein Bild aufbauen: Szene löschen, 3D zeichnen, HUD darüberlegen."""

    def __init__(self, ctx: "moderngl.Context",
                 hud_groesse: tuple[int, int]) -> None:
        self.ctx = ctx
        self.ueberlagerung = Ueberlagerung(ctx, hud_groesse)

    def neues_bild(self, himmel: tuple[float, float, float] = HIMMEL) -> None:
        """Farb- und Tiefenpuffer leeren, Tiefentest an."""
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.clear(*himmel, 1.0)

    def hud_zeichnen(self, flaeche, geaendert: bool = True) -> None:
        """Die pygame-Fläche über die Szene legen.

        ``geaendert=False`` überspringt den Upload und zeichnet die vorhandene
        Textur erneut — für Bilder, in denen sich am HUD nichts getan hat.
        """
        if geaendert:
            self.ueberlagerung.aktualisieren(flaeche)
        self.ueberlagerung.zeichnen()
