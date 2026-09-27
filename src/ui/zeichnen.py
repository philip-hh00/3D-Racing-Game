"""``pygame.draw`` für die Oberfläche: Rasterkoordinaten, Bildpunkte gezeichnet.

Dieselben Funktionen und Parameter wie ``pygame.draw``. Ist das Ziel eine
:class:`src.ui.leinwand.Flaeche`, werden Koordinaten, Radien, Linienbreiten
und Eckradien mit ihrer Skala umgerechnet; sonst geht alles unverändert an
``pygame.draw``. Die Rückgabe ist wie dort das betroffene Rechteck — im
Raster.
"""
from __future__ import annotations

import pygame

from src.ui.leinwand import _px, _rect_px, _rect_raster


def _s(flaeche) -> float:
    return getattr(flaeche, "_s", 1.0)


def _p(pkt, s):
    return (_px(pkt[0], s), _px(pkt[1], s))


def _b(breite, s):
    """Linienbreite: 0 heißt gefüllt und bleibt 0, sonst mindestens 1."""
    return 0 if breite == 0 else max(1, _px(breite, s))


def rect(flaeche, farbe, rechteck, width=0, border_radius=0,
         border_top_left_radius=-1, border_top_right_radius=-1,
         border_bottom_left_radius=-1, border_bottom_right_radius=-1):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.rect(flaeche, farbe, rechteck, width, border_radius,
                                border_top_left_radius, border_top_right_radius,
                                border_bottom_left_radius, border_bottom_right_radius)
    ecke = lambda r: r if r < 0 else _px(r, s)  # noqa: E731
    r = pygame.draw.rect(flaeche, farbe, _rect_px(rechteck, s), _b(width, s),
                         _px(border_radius, s), ecke(border_top_left_radius),
                         ecke(border_top_right_radius), ecke(border_bottom_left_radius),
                         ecke(border_bottom_right_radius))
    return _rect_raster(r, s)


def line(flaeche, farbe, start, ende, width=1):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.line(flaeche, farbe, start, ende, width)
    return _rect_raster(pygame.draw.line(flaeche, farbe, _p(start, s), _p(ende, s),
                                         _b(width, s)), s)


def lines(flaeche, farbe, geschlossen, punkte, width=1):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.lines(flaeche, farbe, geschlossen, punkte, width)
    return _rect_raster(pygame.draw.lines(flaeche, farbe, geschlossen,
                                          [_p(q, s) for q in punkte], _b(width, s)), s)


def aaline(flaeche, farbe, start, ende, *rest):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.aaline(flaeche, farbe, start, ende, *rest)
    return _rect_raster(pygame.draw.aaline(flaeche, farbe, _p(start, s), _p(ende, s)), s)


def aalines(flaeche, farbe, geschlossen, punkte, *rest):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.aalines(flaeche, farbe, geschlossen, punkte, *rest)
    return _rect_raster(pygame.draw.aalines(flaeche, farbe, geschlossen,
                                            [_p(q, s) for q in punkte]), s)


def circle(flaeche, farbe, mitte, radius, width=0, draw_top_right=None,
           draw_top_left=None, draw_bottom_left=None, draw_bottom_right=None):
    s = _s(flaeche)
    viertel = {k: v for k, v in (("draw_top_right", draw_top_right),
                                 ("draw_top_left", draw_top_left),
                                 ("draw_bottom_left", draw_bottom_left),
                                 ("draw_bottom_right", draw_bottom_right)) if v is not None}
    if s == 1.0:
        return pygame.draw.circle(flaeche, farbe, mitte, radius, width, **viertel)
    return _rect_raster(pygame.draw.circle(flaeche, farbe, _p(mitte, s),
                                           max(0, _px(radius, s)), _b(width, s), **viertel), s)


def ellipse(flaeche, farbe, rechteck, width=0):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.ellipse(flaeche, farbe, rechteck, width)
    return _rect_raster(pygame.draw.ellipse(flaeche, farbe, _rect_px(rechteck, s),
                                            _b(width, s)), s)


def arc(flaeche, farbe, rechteck, start, stop, width=1):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.arc(flaeche, farbe, rechteck, start, stop, width)
    return _rect_raster(pygame.draw.arc(flaeche, farbe, _rect_px(rechteck, s), start, stop,
                                        _b(width, s)), s)


def polygon(flaeche, farbe, punkte, width=0):
    s = _s(flaeche)
    if s == 1.0:
        return pygame.draw.polygon(flaeche, farbe, punkte, width)
    return _rect_raster(pygame.draw.polygon(flaeche, farbe, [_p(q, s) for q in punkte],
                                            _b(width, s)), s)
