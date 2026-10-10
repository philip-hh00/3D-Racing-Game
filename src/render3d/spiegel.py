"""Funktionierende Spiegel im Cockpit (ab 1.1.0).

Der Innenspiegel (``spiegel_innen``) und die beiden Außenspiegel
(``spiegel_l``, ``spiegel_r``) zeigen das Feld hinter dem Wagen. Dazu rendert
die Szene für jeden sichtbaren Spiegel ein kleines Bild in eine Textur und legt
sie auf das Glas (Material ``spiegel``, UV 0..1, U nach rechts, wie der Fahrer
hineinschaut — siehe ``VEREINBARUNGEN.md``).

Dieses Modul hält, was nicht OpenGL-Szene ist:

* **Die Kamera eines Spiegels** aus dem Ursprung seines Knotens: sie sitzt in
  der Mitte des Glases, blickt nach hinten (Außenspiegel leicht nach außen) und
  nickt und wankt mit dem Aufbau (:func:`pose`, rechnet wie
  :meth:`~src.render3d.ansichten.Ansichtskamera.blick_aus` mit ``punkt``).
* **Die Spiegelung.** Die Kamera blickt nach hinten; ein Auto links hinter dem
  Wagen steht in ihrem Bild rechts. Ein Spiegel zeigt es links, also wird das
  Bild beim Auflegen auf das Glas waagerecht gedreht (:func:`spiegel_uv`, im
  Shader ``spiegel_modus``). Schrift steht damit seitenverkehrt, wie im echten
  Spiegel.
* **Wann gezeichnet wird** (:func:`noetig`, :func:`sichtbar`,
  :func:`jetzt_dran`): nur in der Cockpitansicht und nur, wo das Glas im Bild
  liegt; auf Niedrig nur jedes zweite Bild, in halber Auflösung.
* **Die Puffer** (:class:`Spiegelpuffer`, :class:`Spiegelspeicher`): je Mensch
  und Spiegel eine kleine Fließkommatextur (lineares HDR, wie die Welt selbst).
  Sie wird **nicht** abgebildet, sondern vom Glas unverändert gelesen — die
  Abbildung am Ende des Bildes behandelt den Spiegel dann wie jeden anderen
  Teil der Welt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import ansichten, camera

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

SPIEGEL_INNEN = "spiegel_innen"
SPIEGEL_L = "spiegel_l"
SPIEGEL_R = "spiegel_r"
#: Reihenfolge, in der die Spiegel gezeichnet werden.
NAMEN = (SPIEGEL_INNEN, SPIEGEL_L, SPIEGEL_R)

#: Name des Glasmaterials im Modell.
MATERIAL = "spiegel"

#: Texturplatz des Spiegelbildes im Weltshader. 0–7 belegen Farbe, Rauheit,
#: Himmel, Schatten, Verdeckung, Gummimaske, Normalen, Leuchtbild; 8–11 die
#: Nachbearbeitung, 12/13 die Geländesicht.
EINHEIT = 14

#: Wie weit ein anderes Auto im Spiegel noch gezeichnet wird (Meter) und wie
#: viele, die nächsten zuerst. Jedes Auto kostet auch im LOD1 ein Dutzend
#: Aufrufe; im Spiegel zählen die, die dicht dran sind.
AUTO_WEITE_M = 220.0
AUTOS_MAX = 3
#: Welche Teile eines Autos im Spiegel gezeichnet werden: die großen. Ein Auto
#: ist dort gut fünfzig Pixel breit; Zierleisten, Kennzeichen, Chrom, Felgen
#: und Leuchteninnenleben (jedes ein eigener Aufruf) sieht niemand. Von hinten
#: gesehen blickt man auf die Front der Wagen: Scheinwerfer ja, Rücklicht nein.
AUTO_MATERIALIEN = frozenset({
    "lack", "lack2", "carbon", "kunststoff", "rad_reifen", "glas", "licht_vorn"})
#: Wie weit Bäume und Häuser (Deko) im Spiegel reichen: 0 heißt nur die
#: Kulisse (Berge, Skyline). Die Deko am Rand kostete je Spiegel gut eine
#: Millisekunde Python und fällt im kleinen Bild kaum auf.
DEKO_WEITE_M = 0.0
#: Ferne Ebene der Spiegelkamera.
FERNE_M = 900.0
#: Mehrfachproben im Spiegelbild: glättet Zäune und Bäume, kostet aber das
#: Zusammenfassen (gut 0,3 ms CPU je Spiegel und Bild) — meist nicht wert.
MSAA = False


@dataclass(frozen=True)
class Spiegelart:
    """Wie ein Spiegel sieht: Blickrichtung, Sichtfeld, Bildgröße."""

    name: str
    #: Drehung des Blicks von „geradeaus nach hinten“ nach außen, Grad
    #: (+ = nach links). Die Außenspiegel sind leicht nach außen gestellt, so
    #: bleibt am inneren Rand die eigene Flanke im Bild.
    auswaerts_grad: float
    #: Vertikales Sichtfeld; das waagerechte ergibt sich aus dem Bildformat.
    sichtfeld_grad: float
    nahe_m: float
    #: Bildgröße je Stufe (``grafik.spiegel``): Breite × Höhe in Pixeln. Das
    #: Format folgt dem des Glases im Modell (innen 17 × 4,4 cm, außen 16 × 7 cm).
    groessen: dict

    def groesse(self, stufe: int) -> tuple[int, int]:
        return self.groessen[2 if stufe >= 2 else 1]

    def richtung(self) -> np.ndarray:
        """Blickrichtung im Fahrzeugsystem (+X vorne, +Y links): nach hinten, etwas nach außen."""
        w = math.radians(self.auswaerts_grad)
        return np.array([-math.cos(w), math.sin(w), 0.0])


ARTEN: dict[str, Spiegelart] = {
    SPIEGEL_INNEN: Spiegelart(SPIEGEL_INNEN, 0.0, 20.0, 0.3, {1: (192, 48), 2: (384, 96)}),
    SPIEGEL_L: Spiegelart(SPIEGEL_L, 15.0, 24.0, 0.3, {1: (112, 48), 2: (224, 96)}),
    SPIEGEL_R: Spiegelart(SPIEGEL_R, -15.0, 24.0, 0.3, {1: (112, 48), 2: (224, 96)}),
}


# ---------------------------------------------------------------------------
# Rechnung
# ---------------------------------------------------------------------------

def pose(name: str, ursprung, pos, gier: float, aufbau=None):
    """Auge, Ziel und Oben der Kamera eines Spiegels.

    ``ursprung`` ist der Ursprung des Knotens im Fahrzeugsystem (Mitte des
    Glases), ``pos``/``gier`` der Wagen, ``aufbau`` die gezeichnete Neigung des
    Aufbaus. Dieselbe Rechnung wie ``Ansichtskamera.blick_aus(..., punkt=…)``.
    """
    return ansichten.blick_am_wagen(ursprung, ARTEN[name].richtung(), pos, gier, aufbau)


_projektionen: dict = {}


def _blick(auge, ziel, oben) -> np.ndarray:
    """lookAt wie :func:`camera.blick`, aber ohne numpy-Kleinkram: je Spiegel und Bild gerechnet.

    Der Blick eines Spiegels geht waagerecht nach hinten, nie senkrecht — der
    Sonderfall von ``camera.blick`` (Blick parallel zu oben) entfällt.
    """
    ax, ay, az = float(auge[0]), float(auge[1]), float(auge[2])
    fx, fy, fz = float(ziel[0]) - ax, float(ziel[1]) - ay, float(ziel[2]) - az
    n = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / n, fy / n, fz / n
    ox, oy, oz = float(oben[0]), float(oben[1]), float(oben[2])
    rx, ry, rz = fy * oz - fz * oy, fz * ox - fx * oz, fx * oy - fy * ox
    n = math.sqrt(rx * rx + ry * ry + rz * rz)
    rx, ry, rz = rx / n, ry / n, rz / n
    ux, uy, uz = ry * fz - rz * fy, rz * fx - rx * fz, rx * fy - ry * fx
    return np.array([
        [rx, ry, rz, -(rx * ax + ry * ay + rz * az)],
        [ux, uy, uz, -(ux * ax + uy * ay + uz * az)],
        [-fx, -fy, -fz, fx * ax + fy * ay + fz * az],
        [0.0, 0.0, 0.0, 1.0]])


def matrix(name: str, groesse: tuple[int, int], auge, ziel, oben) -> np.ndarray:
    """Projektion mal Blick der Spiegelkamera (Welt -> Clip)."""
    schluessel = (name, int(groesse[0]), int(groesse[1]))
    projektion = _projektionen.get(schluessel)
    if projektion is None:
        art = ARTEN[name]
        projektion = _projektionen[schluessel] = camera.perspektive(
            art.sichtfeld_grad, groesse[0] / max(1, groesse[1]), art.nahe_m, FERNE_M)
    return projektion @ _blick(auge, ziel, oben)


def spiegel_uv(u: float, v: float) -> tuple[float, float]:
    """Wo das Glas-UV im Kamerabild liegt: waagerecht gedreht wie ein Spiegel.

    Dieselbe Abbildung rechnet der Shader (``spiegel_modus``).
    """
    return 1.0 - u, v


def noetig(kamera) -> bool:
    """Ob die Kamera eines Menschen Spiegel braucht: nur im Cockpit, nicht beim Zurückschauen.

    Haube und Verfolger sehen keinen Spiegel; beim Zurückschauen sitzt die
    Kamera in der Wagenmitte und blickt nach hinten — die Spiegel stehen
    hinter ihr. Andere Kameras (Zuschauer, TV) haben keine Ansicht.
    """
    return (getattr(kamera, "ansicht", None) == ansichten.COCKPIT
            and not getattr(kamera, "rueckblick", False))


def sichtbar(mvp_haupt, punkt, rand: float = 0.25) -> bool:
    """Ob die Mitte des Glases im Bild der Hauptkamera liegt (mit Rand für die Größe des Glases)."""
    p = np.asarray(punkt, dtype=np.float64)
    c = np.asarray(mvp_haupt, dtype=np.float64) @ np.array([p[0], p[1], p[2], 1.0])
    if c[3] <= 1e-6:
        return False
    grenze = 1.0 + rand
    return bool(abs(c[0]) <= grenze * c[3] and abs(c[1]) <= grenze * c[3])


def jetzt_dran(stufe: int, bild: int, index: int) -> bool:
    """Ob der Spiegel ``index`` (Reihenfolge in :data:`NAMEN`) in Bild ``bild`` neu gezeichnet wird.

    Hoch: der Innenspiegel jedes Bild, die Außenspiegel jedes zweite — sie
    sind klein und am Rand, bei 60 Bildern sieht man 30 nicht, und es hält die
    Kosten unter anderthalb Millisekunden. Niedrig: alle jedes zweite Bild,
    versetzt, damit nicht alle im selben Bild zahlen.
    """
    if stufe >= 2 and index == 0:
        return True
    return (int(bild) + int(index)) % 2 == 0


# ---------------------------------------------------------------------------
# Puffer
# ---------------------------------------------------------------------------

class Spiegelpuffer:
    """Ein kleines Bild: Fließkommatextur mit Tiefe, bei Bedarf mit Mehrfachproben."""

    def __init__(self, ctx, groesse: tuple[int, int], msaa: bool) -> None:
        self.ctx = ctx
        self.groesse = (int(groesse[0]), int(groesse[1]))
        #: Ob der Inhalt zu einem Bild gehört, das noch stimmt (nach Unsichtbarkeit: nein).
        self.gueltig = False
        b, h = self.groesse
        self.farbe = ctx.texture((b, h), 4, dtype="f2")
        self.farbe.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.farbe.repeat_x = self.farbe.repeat_y = False
        self._dinge = [self.farbe]
        self.fbo_ms = None
        if msaa:
            farbe_ms = ctx.renderbuffer((b, h), 4, samples=4, dtype="f2")
            tiefe_ms = ctx.depth_renderbuffer((b, h), samples=4)
            self.fbo_ms = ctx.framebuffer(color_attachments=[farbe_ms], depth_attachment=tiefe_ms)
            self.fbo = ctx.framebuffer(color_attachments=[self.farbe])
            self._dinge += [self.fbo_ms, self.fbo, farbe_ms, tiefe_ms]
        else:
            tiefe = ctx.depth_renderbuffer((b, h))
            self.fbo = ctx.framebuffer(color_attachments=[self.farbe], depth_attachment=tiefe)
            self._dinge += [self.fbo, tiefe]

    def beginnen(self) -> None:
        """Binden, Ausschnitt setzen, leeren."""
        ctx = self.ctx
        (self.fbo_ms or self.fbo).use()
        ctx.scissor = None
        ctx.viewport = (0, 0, *self.groesse)
        (self.fbo_ms or self.fbo).clear(0.0, 0.0, 0.0, 1.0, depth=1.0)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        ctx.depth_mask = True

    def abschliessen(self) -> None:
        """Mehrfachproben zusammenfassen; danach liegt das Bild in :attr:`farbe`."""
        if self.fbo_ms is not None:
            self.ctx.copy_framebuffer(self.fbo, self.fbo_ms)
        self.gueltig = True

    def freigeben(self) -> None:
        for ding in self._dinge:
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self._dinge = []


class Spiegelspeicher:
    """Die Spiegelpuffer aller Menschen: je Kennung drei Puffer in der Größe der Stufe."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self._saetze: dict[int, tuple[int, dict]] = {}
        self._takte: dict[int, int] = {}

    def takt(self, kennung: int) -> int:
        """Zählt die Bilder dieses Menschen (nicht die der Szene: im Splitscreen
        zeichnet sie zweimal je Bild, und ein gemeinsamer Zähler ließe einen der
        beiden immer im selben Takt)."""
        self._takte[kennung] = self._takte.get(kennung, -1) + 1
        return self._takte[kennung]

    def satz(self, kennung: int, stufe: int) -> dict:
        """``{name: Spiegelpuffer}`` für diesen Menschen; bei geänderter Stufe neu gebaut."""
        stufe = 2 if stufe >= 2 else 1
        eintrag = self._saetze.get(kennung)
        if eintrag is not None and eintrag[0] == stufe:
            return eintrag[1]
        if eintrag is not None:
            for puffer in eintrag[1].values():
                puffer.freigeben()
        puffer = {name: Spiegelpuffer(self.ctx, ARTEN[name].groesse(stufe), msaa=MSAA and stufe >= 2)
                  for name in NAMEN}
        self._saetze[kennung] = (stufe, puffer)
        return puffer

    def freigeben(self) -> None:
        for _stufe, puffer in self._saetze.values():
            for p in puffer.values():
                p.freigeben()
        self._saetze = {}
        self._takte = {}
