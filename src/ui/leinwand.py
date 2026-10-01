"""Scharfe Oberfläche in jeder Fenstergröße.

Die ganze Oberfläche (Menüs, HUD) rechnet in einem festen Raster von
1920×1080 — Positionen, Größen, Abstände. Bis 1.0.0 wurde auch *in* diesem
Raster gezeichnet und das Ergebnis auf das Fenster gestreckt: in 1440p oder 4K
war Schrift weich oder treppig, „man kann beim genauen Hinsehen Pixel zählen"
(gemeldet 27.09.2026).

Jetzt wird in der **echten** Auflösung gezeichnet, gerechnet aber weiter im
Raster. Das leistet :class:`Flaeche`: eine pygame-Fläche, deren Bildpunkte
``skala``-mal so dicht liegen, die nach außen aber ihre Rastergröße meldet.
``blit``, ``fill``, ``set_clip`` und die Zeichenfunktionen in
:mod:`src.ui.zeichnen` rechnen Rasterkoordinaten in Bildpunkte um. Schrift
kommt aus :class:`Schrift` und wird gleich in der echten Größe gerendert —
das ist der Teil, der sichtbar scharf wird.

Bei ``skala == 1`` (Fenster 1920×1080, alle Tests) ist alles wie vorher: die
Fläche *ist* eine gewöhnliche pygame-Fläche gleicher Größe.

Was dabei zu beachten ist:

* Neue Flächen der Oberfläche über :func:`flaeche` anlegen, nicht direkt
  mit ``pygame.Surface`` — sonst ist ihr Inhalt wieder nur im Raster scharf.
* Eine gewöhnliche Fläche (ein geladenes Bild, ein Videobild) darf auf eine
  :class:`Flaeche` geblittet werden: sie wird dabei hochskaliert
  (zwischengespeichert, solange sie sich nicht ändert).
* ``pygame.transform`` auf einer :class:`Flaeche` liefert eine gewöhnliche
  Fläche in *Bildpunkten* — dafür gibt es :func:`skalieren` und
  :func:`drehen`.
"""
from __future__ import annotations

import weakref

import pygame

from src.ui.schmutz import Schmutz

#: Das Raster, in dem die Oberfläche rechnet.
RASTER = (1920, 1080)

_skala: float = 1.0


def skala() -> float:
    """Bildpunkte je Rasterpunkt für neu angelegte Flächen und Schriften."""
    return _skala


def skala_setzen(wert: float) -> None:
    global _skala
    _skala = max(0.25, float(wert))


def _px(v: float, s: float) -> int:
    return int(round(v * s))


def _rect_px(r, s: float) -> pygame.Rect:
    """Ein Rechteck im Raster in Bildpunkte — Kanten runden, nicht Maße.

    Über die Kanten gerundet, damit zwei aneinanderstoßende Rechtecke auch
    nach dem Skalieren lückenlos aneinanderstoßen.
    """
    r = pygame.Rect(r)
    x0, y0 = _px(r.x, s), _px(r.y, s)
    return pygame.Rect(x0, y0, _px(r.right, s) - x0, _px(r.bottom, s) - y0)


def _rect_raster(r: pygame.Rect, s: float) -> pygame.Rect:
    if s == 1.0:
        return pygame.Rect(r)
    x0, y0 = int(r.x / s), int(r.y / s)
    return pygame.Rect(x0, y0, int(round(r.right / s)) - x0, int(round(r.bottom / s)) - y0)


class Flaeche(pygame.Surface):
    """Eine Fläche, die im Raster rechnet und in Bildpunkten zeichnet."""

    #: Schmutzverfolgung, nur für die virtuelle Fläche eingeschaltet
    #: (:meth:`schmutz_verfolgen`); sonst ``None`` und ohne Kosten.
    _schmutz: "Schmutz | None" = None

    def __init__(self, groesse, flags: int = 0, skala_: float | None = None, *args) -> None:
        s = _skala if skala_ is None else float(skala_)
        w, h = int(groesse[0]), int(groesse[1])
        super().__init__((_px(w, s), _px(h, s)), flags, *args)
        self._s = s
        self._raster = (w, h)

    # -- Maße im Raster ----------------------------------------------------
    @property
    def skala(self) -> float:
        return self._s

    def get_size(self):
        return self._raster

    def get_width(self):
        return self._raster[0]

    def get_height(self):
        return self._raster[1]

    def get_rect(self, **kw):
        r = pygame.Rect(0, 0, *self._raster)
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def bildpunkte(self) -> tuple[int, int]:
        """Die echte Größe in Bildpunkten."""
        return super().get_size()

    # -- Schmutz: nur anfassen, was sich geändert hat (src/ui/schmutz.py) -------
    def schmutz_verfolgen(self) -> None:
        """Ab jetzt merken, wohin gezeichnet wird (fürs Leeren und Hochladen)."""
        b, h = super().get_size()
        self._schmutz = Schmutz(b, h)

    def schmutz_alles(self) -> None:
        """Etwas hat an der Verfolgung vorbei geschrieben: alles gilt als geändert."""
        if self._schmutz is not None:
            self._schmutz.alles_setzen()

    def schmutz_loeschen(self) -> None:
        """Die Fläche durchsichtig machen — verfolgt: nur, wohin gezeichnet wurde."""
        if self._schmutz is None:
            pygame.Surface.fill(self, (0, 0, 0, 0))
        else:
            self._schmutz.leeren(self)

    def schmutz_rechtecke(self):
        """Geänderte Gegenden (Bildpunkte) seit dem Hochladen; ``None``: alles."""
        return None if self._schmutz is None else self._schmutz.hochzuladen()

    def schmutz_hochgeladen(self) -> None:
        if self._schmutz is not None:
            self._schmutz.hochgeladen()

    # -- Zeichnen ------------------------------------------------------------
    def blit(self, quelle, ziel, area=None, special_flags=0):
        s = self._s
        if isinstance(ziel, pygame.Rect) or (hasattr(ziel, "__len__") and len(ziel) == 4):
            ziel = pygame.Rect(ziel).topleft
        x, y = ziel[0], ziel[1]
        qs = getattr(quelle, "_s", 1.0)
        if qs != s:
            quelle = _auf_skala(quelle, qs, s)
        flaeche_area = None if area is None else _rect_px(area, s)
        r = pygame.Surface.blit(self, quelle, (_px(x, s), _px(y, s)), flaeche_area, special_flags)
        if self._schmutz is not None:
            self._schmutz.markieren(r)
        return _rect_raster(r, s)

    def blits(self, folge, doreturn=True):
        ergebnis = [self.blit(*e) for e in folge]
        return ergebnis if doreturn else None

    def fill(self, farbe, rect=None, special_flags=0):
        r = None if rect is None else _rect_px(rect, self._s)
        gefuellt = pygame.Surface.fill(self, farbe, r, special_flags)
        if self._schmutz is not None:
            self._schmutz.markieren(gefuellt)
        return _rect_raster(gefuellt, self._s)

    def set_clip(self, rect=None):
        pygame.Surface.set_clip(self, None if rect is None else _rect_px(rect, self._s))

    def get_clip(self):
        return _rect_raster(pygame.Surface.get_clip(self), self._s)

    def get_at(self, pos):
        return pygame.Surface.get_at(self, (min(_px(pos[0], self._s), super().get_width() - 1),
                                            min(_px(pos[1], self._s), super().get_height() - 1)))

    def subsurface(self, rect):
        """Ein Ausschnitt — als gewöhnliche Fläche in Bildpunkten, mit Skala."""
        teil = pygame.Surface.subsurface(self, _rect_px(rect, self._s))
        return _flaeche_aus(teil, self._s)

    def copy(self):
        return _flaeche_aus(pygame.Surface.copy(self), self._s)

    def convert_alpha(self, *a):
        return _flaeche_aus(pygame.Surface.convert_alpha(self, *a), self._s)

    def convert(self, *a):
        return _flaeche_aus(pygame.Surface.convert(self, *a), self._s)


def _flaeche_aus(roh: pygame.Surface, s: float) -> "Flaeche":
    """Eine vorhandene Fläche in Bildpunkten als :class:`Flaeche` mit Skala ``s``."""
    w, h = pygame.Surface.get_size(roh)
    alpha = bool(roh.get_flags() & pygame.SRCALPHA)
    f = Flaeche.__new__(Flaeche)
    pygame.Surface.__init__(f, (w, h), pygame.SRCALPHA if alpha else 0)
    if alpha:
        # Auf durchsichtig addiert = exakte Kopie samt Alpha (ein normales
        # Blit würde das Alpha mit dem leeren Ziel verrechnen).
        pygame.Surface.fill(f, (0, 0, 0, 0))
        pygame.Surface.blit(f, roh, (0, 0), None, pygame.BLEND_RGBA_ADD)
    else:
        pygame.Surface.blit(f, roh, (0, 0))
    ck = roh.get_colorkey()
    if ck is not None:
        f.set_colorkey(ck)
    f._s = s
    f._raster = (int(round(w / s)), int(round(h / s)))
    return f


def px_groesse(groesse) -> tuple[int, int]:
    """Eine Rastergroesse in Bildpunkten der aktuellen Skala (mindestens 1)."""
    return (max(1, _px(groesse[0], _skala)), max(1, _px(groesse[1], _skala)))


_rgba_zuletzt: list = []


def aus_rgba(pixel: bytes, groesse_px: tuple[int, int]) -> "Flaeche":
    """RGBA-Bytes **in Bildpunkten** (z. B. die 3D-Vorschau) als Flaeche der aktuellen Skala.

    Ein Bild, das in Rastergroesse geliefert und auf eine skalierte Flaeche
    geblittet wird, wird dort jedes Mal neu hochgerechnet: ``_auf_skala``
    findet fuer eine frisch erzeugte Flaeche nie einen Treffer, in 1440p
    kostete das 22 ms je Bild in der Werkstatt (gemessen 01.10.2026). Wer die
    Bytes gleich in Bildpunkten rendert, bekommt hier eine Flaeche ohne
    Hochrechnen — und dieselbe Flaeche zurueck, solange ``pixel`` dasselbe
    Objekt bleibt (die Vorschau liefert bei unveraendertem Bild denselben
    Puffer).
    """
    for p, g, f, s in _rgba_zuletzt:
        if p is pixel and g == tuple(groesse_px) and s == _skala:
            return f
    roh = pygame.image.frombuffer(pixel, tuple(groesse_px), "RGBA")
    f = _flaeche_aus(roh, _skala)
    _rgba_zuletzt.insert(0, (pixel, tuple(groesse_px), f, _skala))
    del _rgba_zuletzt[4:]
    return f


def flaeche(groesse, flags: int = 0, *args) -> Flaeche:
    """Eine neue Fläche der Oberfläche, Größe im Raster."""
    return Flaeche(groesse, flags, None, *args)


# ---------------------------------------------------------------------------
# Fremde Flächen auf eine andere Skala bringen
# ---------------------------------------------------------------------------

_cache: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _auf_skala(quelle: pygame.Surface, von: float, nach: float) -> pygame.Surface:
    """``quelle`` (Skala ``von``) in Bildpunkten der Skala ``nach``.

    Zwischengespeichert je Fläche, solange sich ihr Inhalt nicht ändert —
    ein geladenes Symbol wird so einmal skaliert, nicht in jedem Bild. Ob sich
    der Inhalt geändert hat, verrät pygame nicht; geprüft wird deshalb die
    Größe und ein Stichprobenwert. Flächen, die sich jedes Bild ändern
    (Video), sind gewöhnlich schon passend groß.
    """
    w, h = pygame.Surface.get_size(quelle)
    zw, zh = max(1, int(round(w * nach / von))), max(1, int(round(h * nach / von)))
    if (zw, zh) == (w, h):
        return quelle
    try:
        probe = (pygame.Surface.get_at(quelle, (w // 2, h // 2)) if w and h else None,
                 pygame.Surface.get_at(quelle, (w // 3, h // 3)) if w and h else None)
        eintrag = _cache.get(quelle)
        if eintrag is not None and eintrag[0] == (zw, zh, nach) and eintrag[1] == probe:
            return eintrag[2]
    except (TypeError, pygame.error):
        eintrag, probe = None, None
    if w == 0 or h == 0:
        return quelle
    try:
        neu = pygame.transform.smoothscale(quelle, (zw, zh))
    except (ValueError, pygame.error):
        neu = pygame.transform.scale(quelle, (zw, zh))
    try:
        _cache[quelle] = ((zw, zh, nach), probe, neu)
    except TypeError:
        pass
    return neu


def skalieren(quelle, groesse, glatt: bool = True) -> pygame.Surface:
    """``pygame.transform.(smooth)scale`` mit Zielgröße im Raster."""
    s = getattr(quelle, "_s", None)
    if s is None:
        f = pygame.transform.smoothscale if glatt else pygame.transform.scale
        return f(quelle, (int(groesse[0]), int(groesse[1])))
    px = (max(1, _px(groesse[0], s)), max(1, _px(groesse[1], s)))
    roh = (pygame.transform.smoothscale if glatt else pygame.transform.scale)(quelle, px)
    return _flaeche_aus(roh, s)


def drehen(quelle, winkel: float, zoom: float = 1.0) -> pygame.Surface:
    """``pygame.transform.rotozoom``, die Skala bleibt erhalten."""
    roh = pygame.transform.rotozoom(quelle, winkel, zoom)
    s = getattr(quelle, "_s", None)
    return roh if s is None else _flaeche_aus(roh, s)


# ---------------------------------------------------------------------------
# Schrift in echter Größe
# ---------------------------------------------------------------------------

class Schrift:
    """Eine Schrift, die im Raster misst und in Bildpunkten rendert.

    Dieselben Methoden wie ``pygame.font.Font``, soweit die Oberfläche sie
    nutzt; alles Übrige geht an die Schrift in Bildpunkten durch.
    """

    def __init__(self, erzeugen, groesse: int, s: float) -> None:
        self._s = s
        self._font = erzeugen(max(1, int(round(groesse * s))))

    def render(self, text, antialias=True, farbe=(255, 255, 255), hintergrund=None):
        if hintergrund is None:
            roh = self._font.render(text, antialias, farbe)
        else:
            roh = self._font.render(text, antialias, farbe, hintergrund)
        return _flaeche_aus(roh, self._s) if self._s != 1.0 else roh

    def size(self, text):
        w, h = self._font.size(text)
        return (int(round(w / self._s)), int(round(h / self._s)))

    def get_height(self):
        return int(round(self._font.get_height() / self._s))

    def get_linesize(self):
        return int(round(self._font.get_linesize() / self._s))

    def get_ascent(self):
        return int(round(self._font.get_ascent() / self._s))

    def get_descent(self):
        return int(round(self._font.get_descent() / self._s))

    def metrics(self, text):
        return [None if m is None else tuple(int(round(v / self._s)) for v in m)
                for m in self._font.metrics(text)]

    def __getattr__(self, name):
        return getattr(self._font, name)
