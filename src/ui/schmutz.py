"""Schmutzverfolgung für die virtuelle Fläche: nur anfassen, was sich geändert hat.

Die virtuelle Fläche wird jedes Bild geleert und als Textur hochgeladen — in
4K sind das zweimal 33 MB, obwohl das HUD nur einen Bruchteil davon belegt
(gemessen 01.10.2026: rund 8 ms je Bild auf der CPU). Die Fläche wird dazu in
``SPALTEN`` × ``ZEILEN`` Zellen geteilt, und :class:`Schmutz` merkt:

* ``inhalt``: Zellen, in denen die Fläche nicht mehr durchsichtig sein kann —
  nur die müssen zu Beginn des nächsten Bildes geleert werden;
* ``fehlt``: Zellen, in denen die Textur von der Fläche abweicht — nur die
  müssen hochgeladen werden;
* ``alles``: nichts ist bekannt (neue Fläche, neue Textur): ganz leeren und
  ganz hochladen.

Gemeldet wird von :class:`src.ui.leinwand.Flaeche` (``blit``, ``fill``) und den
Zeichenfunktionen in :mod:`src.ui.zeichnen`. Wer an ihnen vorbei in die Fläche
schreibt, ruft ``Flaeche.schmutz_alles()``.
"""
from __future__ import annotations

import pygame


class Schmutz:
    SPALTEN = 12
    ZEILEN = 8
    #: Ab diesem Anteil schmutziger Zellen lohnt Stückwerk nicht mehr.
    GRENZE = 0.6
    #: Zeichenfunktionen melden ihr Rechteck knapp; ein Rand schadet nicht.
    RAND = 2

    def __init__(self, breite: int, hoehe: int) -> None:
        self.w, self.h = max(1, int(breite)), max(1, int(hoehe))
        n = self.SPALTEN * self.ZEILEN
        self.inhalt = bytearray(n)
        self.fehlt = bytearray(n)
        self.alles = True
        self._eins = b"\x01" * self.SPALTEN
        self._leer = bytes(n)
        self._voll = b"\x01" * n
        # Zelle c deckt die Bildpunkte x mit x * SPALTEN // w == c ab.
        self.xs = [-(-c * self.w // self.SPALTEN) for c in range(self.SPALTEN + 1)]
        self.ys = [-(-z * self.h // self.ZEILEN) for z in range(self.ZEILEN + 1)]

    def markieren(self, r) -> None:
        """Ein beschriebenes Rechteck (Bildpunkte) vermerken."""
        if r.width <= 0 or r.height <= 0:
            return
        S, Z, w, h = self.SPALTEN, self.ZEILEN, self.w, self.h
        x0 = max(0, r.left - self.RAND)
        y0 = max(0, r.top - self.RAND)
        x1 = min(w, r.right + self.RAND)
        y1 = min(h, r.bottom + self.RAND)
        if x1 <= x0 or y1 <= y0:
            return
        c0, c1 = x0 * S // w, (x1 - 1) * S // w
        z0, z1 = y0 * Z // h, (y1 - 1) * Z // h
        n = c1 - c0 + 1
        if n == S and z1 - z0 + 1 == Z:
            self.inhalt[:] = self._voll
            self.fehlt[:] = self._voll
            return
        eins = self._eins[:n]
        inhalt, fehlt = self.inhalt, self.fehlt
        for z in range(z0, z1 + 1):
            a = z * S + c0
            inhalt[a:a + n] = eins
            fehlt[a:a + n] = eins

    def alles_setzen(self) -> None:
        """Es wurde an der Verfolgung vorbei geschrieben: nichts ist mehr bekannt."""
        self.alles = True
        self.inhalt[:] = self._voll

    def _laeufe(self, zellen: bytearray, z: int):
        """Waagerechte Läufe gesetzter Zellen einer Zeile als ``(a, b)``, ``b`` ausgeschlossen."""
        S = self.SPALTEN
        zeile = zellen[z * S:(z + 1) * S]
        c = 0
        while c < S:
            if zeile[c]:
                a = c
                while c < S and zeile[c]:
                    c += 1
                yield a, c
            else:
                c += 1

    def _rechtecke(self, zellen: bytearray) -> list:
        """Zellen als möglichst wenige Rechtecke: gleiche Läufe untereinander werden eins."""
        offen: dict = {}
        fertig: list = []
        for z in range(self.ZEILEN):
            laeufe = set(self._laeufe(zellen, z))
            neu = {}
            for lauf, (z0, _zl) in offen.items():
                if lauf in laeufe:
                    neu[lauf] = (z0, z)
                else:
                    fertig.append((lauf, z0, _zl))
            for lauf in laeufe:
                if lauf not in neu:
                    neu[lauf] = (z, z)
            offen = neu
        fertig.extend((lauf, z0, zl) for lauf, (z0, zl) in offen.items())
        return [pygame.Rect(self.xs[a], self.ys[z0], self.xs[b] - self.xs[a],
                            self.ys[zl + 1] - self.ys[z0]) for (a, b), z0, zl in fertig]

    def leeren(self, flaeche) -> None:
        """Die Fläche durchsichtig machen — soweit sie es nicht schon ist."""
        if self.alles or all(self.inhalt):
            pygame.Surface.fill(flaeche, (0, 0, 0, 0))
            self.fehlt[:] = self._voll
            self.inhalt[:] = self._leer
            return
        if not any(self.inhalt):
            return
        for z in range(self.ZEILEN):
            for a, b in self._laeufe(self.inhalt, z):
                pygame.Surface.fill(flaeche, (0, 0, 0, 0),
                                    (self.xs[a], self.ys[z], self.xs[b] - self.xs[a],
                                     self.ys[z + 1] - self.ys[z]))
        fehlt, inhalt = self.fehlt, self.inhalt
        for i in range(len(inhalt)):
            if inhalt[i]:
                fehlt[i] = 1
        self.inhalt[:] = self._leer

    def hochzuladen(self):
        """Rechtecke (Bildpunkte), die in die Textur müssen; ``None`` heißt: ganz."""
        if self.alles:
            return None
        n = sum(self.fehlt)
        if n == 0:
            return []
        if n > self.GRENZE * len(self.fehlt):
            return None
        return self._rechtecke(self.fehlt)

    def hochgeladen(self) -> None:
        self.fehlt[:] = self._leer
        self.alles = False


class Weiterleitung:
    """Schmutz eines Ausschnitts: meldet an die Elternfläche, verschoben um den Versatz.

    Ein Ausschnitt (``Flaeche.subsurface``) teilt sich den Speicher mit der
    Elternfläche. Was in ihn gezeichnet wird, muss dort als Schmutz ankommen,
    sonst bliebe es beim Leeren und Hochladen unbemerkt.
    """

    def __init__(self, eltern: Schmutz, dx: int, dy: int) -> None:
        self.eltern, self.dx, self.dy = eltern, int(dx), int(dy)

    def markieren(self, r) -> None:
        self.eltern.markieren(r.move(self.dx, self.dy))

    def alles_setzen(self) -> None:
        self.eltern.alles_setzen()

    def leeren(self, flaeche) -> None:
        r = pygame.Surface.fill(flaeche, (0, 0, 0, 0))
        self.markieren(r)

    def hochzuladen(self):
        return None

    def hochgeladen(self) -> None:
        pass
