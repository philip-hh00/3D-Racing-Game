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
import pygame

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
    // Senkrecht gespiegelt: pygame legt Zeile 0 nach oben, OpenGL erwartet
    // sie unten. Im Shader und nicht beim Hochladen, weil der Puffer
    // unveraendert aus dem Speicher der Flaeche kommt.
    uv = vec2(in_uv.x, 1.0 - in_uv.y);
    gl_Position = vec4(in_position, 0.0, 1.0);
}
"""

_UEBERLAGERUNG_FRAGMENT = """
#version 330
uniform sampler2D flaeche;
uniform bool bgra;
in vec2 uv;
out vec4 farbe;
void main() {
    vec4 roh = texture(flaeche, uv);
    farbe = bgra ? roh.bgra : roh;
}
"""


def flaeche_als_bytes(flaeche) -> bytes:
    """Eine pygame-Fläche als RGBA-Bytes in **pygame**-Zeilenreihenfolge.

    Der langsame, aber immer richtige Weg — Rückfall für Flächen, deren
    Speicherlayout nicht direkt hochladbar ist (siehe :func:`direkt_lesbar`).

    Bewusst **nicht** gespiegelt: die Spiegelung sitzt im Shader, damit beide
    Wege — der direkte über ``get_view`` und dieser hier — dasselbe liefern.
    Zweimal spiegeln stellt das HUD wieder auf den Kopf.
    """
    import pygame

    return pygame.image.tobytes(flaeche, "RGBA", False)


def direkt_lesbar(flaeche) -> bool:
    """Ob der Speicher der Fläche ohne Umbau hochgeladen werden kann.

    Das ist der Unterschied zwischen 15 ms und 0,02 ms je Bild, gemessen an
    einer Fläche von 1920×1080: ``pygame.image.tobytes`` baut jedes Pixel neu
    zusammen, ``get_view`` reicht nur einen Zeiger weiter.

    Voraussetzung ist ein lückenloses 32-Bit-Layout — bei einer Zeilenlänge,
    die nicht der Breite entspricht, lägen zwischen den Zeilen Füllbytes, und
    das Bild käme schräg heraus.
    """
    return (flaeche.get_bitsize() == 32
            and flaeche.get_pitch() == pygame.Surface.get_width(flaeche) * 4)


def _byteplatz(schiebung: int) -> int:
    """An welcher Bytestelle im Pixel ein Kanal liegt.

    ``get_shifts`` liefert die **Bitposition** im 32-Bit-Wert. Wo dieses Byte
    im Speicher steht, hängt an der Byte-Reihenfolge des Rechners: auf
    Little-Endian steht das niederwertigste Byte zuerst, auf Big-Endian
    zuletzt.
    """
    import sys

    stelle = schiebung // 8
    return stelle if sys.byteorder == "little" else 3 - stelle


def _ist_bgra(flaeche) -> bool:
    """Liegt Blau im Speicher vor Rot?

    Unter Windows liefert eine Fläche mit ``SRCALPHA`` die Bytes als B, G, R, A:
    ``get_shifts()`` meldet Rot bei Bit 16 und Blau bei Bit 0, und auf
    Little-Endian ist Bit 0 das erste Byte.

    Gelesen statt angenommen. Der Fehler wäre ein HUD mit vertauschtem Rot und
    Blau — etwas, das man für einen Fehler in der Farbwahl hält und nicht in
    der Kanalreihenfolge sucht.
    """
    rot, _gruen, blau, _alpha = flaeche.get_shifts()
    return _byteplatz(blau) < _byteplatz(rot)


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
        self._textur_neu = True
        # Linear: in 1920×1080 trifft jeder Bildpunkt genau ein Texel, dort
        # ist das dasselbe wie NEAREST. In jeder anderen Fenstergröße aber
        # verdoppelte NEAREST einzelne Pixel — Schrift sah treppig aus, man
        # konnte die Pixel zählen (gemeldet 27.09.2026).
        self._textur.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self._programm["flaeche"].value = 0
        self._programm["bgra"].value = False

    @property
    def groesse(self) -> tuple[int, int]:
        return self._textur.size

    def aktualisieren(self, flaeche) -> None:
        """Den Inhalt der pygame-Fläche in die Textur schreiben.

        Wenn möglich ohne Umbau: der Speicher der Fläche geht direkt an
        OpenGL, Kanalreihenfolge und Spiegelung erledigt der Shader. Das ist
        der Unterschied zwischen 15 ms und 0,02 ms je Bild — bei 1920×1080 war
        der Umbau vorher drei Viertel der gesamten Bildzeit, während die
        Grafikkarte mit einer halben Millisekunde für die ganze Szene
        auskam.
        """
        groesse = tuple(pygame.Surface.get_size(flaeche))    # Bildpunkte, nicht Raster
        if groesse != tuple(self._textur.size):
            # Das Fenster hat die Größe gewechselt, und die Oberfläche zeichnet
            # in echter Auflösung (src/ui/leinwand.py): Textur mitziehen.
            self._textur.release()
            self._textur = self._ctx.texture(groesse, 4)
            self._textur.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._textur_neu = True
        if direkt_lesbar(flaeche):
            self._programm["bgra"].value = _ist_bgra(flaeche)
            # Eine verfolgte Fläche (die virtuelle) sagt, wo sie sich geändert
            # hat; nur das geht hoch. ``None``: ganz — neue Textur, unverfolgte
            # Fläche oder zu viel Änderung für Stückwerk.
            rechtecke = None
            if not self._textur_neu and hasattr(flaeche, "schmutz_rechtecke"):
                rechtecke = flaeche.schmutz_rechtecke()
            ansicht = memoryview(flaeche.get_view("0"))
            if rechtecke is None:
                self._textur.write(ansicht)
            elif rechtecke:
                feld = np.frombuffer(ansicht, dtype=np.uint8).reshape(groesse[1], groesse[0], 4)
                for r in rechtecke:
                    teil = self._vorrat(r.width * r.height * 4)[:r.width * r.height * 4]
                    teil = teil.reshape(r.height, r.width, 4)
                    np.copyto(teil, feld[r.top:r.bottom, r.left:r.right])
                    self._textur.write(teil, viewport=(r.left, r.top, r.width, r.height))
                del feld
            del ansicht
        else:
            self._programm["bgra"].value = False
            self._textur.write(flaeche_als_bytes(flaeche))
        self._textur_neu = False
        if hasattr(flaeche, "schmutz_hochgeladen"):
            flaeche.schmutz_hochgeladen()

    def _vorrat(self, n: int) -> np.ndarray:
        """Ein wiederverwendeter Zwischenspeicher für Teilstücke.

        Ein frisch angelegtes Feld von einigen MB kostet je Bild Seitenfehler
        des Betriebssystems: ``ascontiguousarray`` brauchte für vier Stücke
        (1,5 Mio. Bildpunkte, 4K) 2,9 ms, das Kopieren in einen Vorrat 0,5 ms.
        """
        vorrat = getattr(self, "_vorrat_feld", None)
        if vorrat is None or len(vorrat) < n:
            vorrat = self._vorrat_feld = np.empty(max(n, 1 << 20), dtype=np.uint8)
        return vorrat

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
