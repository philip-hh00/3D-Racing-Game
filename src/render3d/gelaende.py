"""Gelände um die Strecke: Hügel, Dünen, Berge bis zum Horizont, Gras am Rand.

Reine Rechnung mit numpy bis auf die beiden Zeichner am Ende. Das Höhenfeld
entsteht zur Laufzeit — keine Datei, kein Blender — aus einem **festen Keim
je Strecke** (dem Streckennamen, wie bei der Platzierung): dieselbe Strecke
hat bei jedem Rennen dieselben Hügel.

**Im Korridor flach.** Fahrbahn, Randstreifen, Begrenzung und der Streifen
mit Banden und Reifenstapeln liegen auf Höhe 0. Gemessen wird der Abstand
zur Fahrbahnkante mit :func:`platzierung.abstand_zur_linie`; bis
``korridor_m`` ist das Gelände exakt 0, danach steigt es über ``anstieg_m``
weich an (glatte Stufe, erste und zweite Ableitung am Rand null — keine
Kante am Übergang).

**Drei Zonen.** ``nah`` direkt hinter dem Korridor, ``fern`` ab einigem
Abstand vom Streckenrechteck, ``horizont`` als Bergkette ganz außen. Jede
Zone hat ihren Charakter aus dem Thema: Dünen, Tafelberge, sanfte Hügel,
steile Berge.

**Das Netz.** Innen ein Gitter um die Strecke, fein im Korridor und nach
außen gröber, das alle Deko trägt; außen Ringe mit gleichem Winkelschritt
bis kurz vor die ferne Ebene der Kamera. Winkelschritt statt Meterschritt,
weil am Horizont die Silhouette zählt: ein Berg in zwei Kilometern braucht
dieselbe Auflösung in Grad wie einer in fünfhundert Metern. Die Ringe
schließen ohne Lücke und ohne T-Stoß an den Gitterrand an.

**Höhe abfragen.** :meth:`Gelaende.hoehe` rechnet auf dem Gitter genau so,
wie die Grafikkarte das Dreieck füllt — ein Baum steht auf dem gezeichneten
Boden, nicht auf der mathematischen Fläche darüber oder darunter.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import shader
from .platzierung import abstand_zur_linie, keim as keim_aus_namen

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Das Gelände liegt 1 cm unter der Fahrbahn — wie der alte Untergrund
#: (``track_mesh.UNTERGRUND_VERSATZ_M``), gegen Z-Fighting im Korridor.
VERSATZ_M = -0.01

#: Bis hierher reichen die Ringe, gemessen von der Streckenmitte. Die ferne
#: Ebene der Kamera liegt bei 3200 m; die Kamera steht bis zu einigen hundert
#: Metern neben der Mitte.
AUSSEN_M = 2800.0

#: Gitterauflösung je ``grafik.gelaende_detail``: (fein, grob) in Metern,
#: Winkelschritte der Ringe, radiales Wachstum der Ringe.
DETAIL = {
    0: dict(fein_m=5.0, grob_m=16.0, winkel=512, wachstum=0.10),
    1: dict(fein_m=3.5, grob_m=11.0, winkel=896, wachstum=0.065),
    2: dict(fein_m=2.2, grob_m=8.0, winkel=1280, wachstum=0.035),
}

#: Wie weit das feine Gitter über das Streckenrechteck hinausgeht (Korridor
#: plus Anstieg) und wie weit das Gitter insgesamt reicht (alle Deko).
KERN_RAND_M = 70.0
GITTER_RAND_M = 320.0

#: Rasterweite der Abstandskarte zur Fahrbahnkante.
ABSTAND_RASTER_M = 4.0


# ---------------------------------------------------------------------------
# Rauschen
# ---------------------------------------------------------------------------

def _hash(ix: np.ndarray, iy: np.ndarray, keim: int) -> np.ndarray:
    n = (ix * 374761393 + iy * 668265263 + (keim % 1000003) * 1442695041) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return n ^ (n >> 16)


#: 256 Gradientenrichtungen, über den Hash ausgewählt — billiger als
#: Kosinus und Sinus je Ecke, und bei hunderttausend Punkten zählt das.
_GRADIENTEN = np.stack([np.cos(np.arange(256) * 2 * math.pi / 256),
                        np.sin(np.arange(256) * 2 * math.pi / 256)], axis=1)


def gradientenrauschen(x: np.ndarray, y: np.ndarray, keim: int) -> np.ndarray:
    """Perlin-artiges Rauschen, etwa −1 … 1, glatt (Quintik)."""
    x0, y0 = np.floor(x), np.floor(y)
    fx, fy = x - x0, y - y0
    ix, iy = x0.astype(np.int64), y0.astype(np.int64)

    def ecke(dx, dy):
        g = _GRADIENTEN[_hash(ix + dx, iy + dy, keim) & 255]
        return g[..., 0] * (fx - dx) + g[..., 1] * (fy - dy)

    u = fx * fx * fx * (fx * (fx * 6.0 - 15.0) + 10.0)
    v = fy * fy * fy * (fy * (fy * 6.0 - 15.0) + 10.0)
    e00, e10, e01, e11 = ecke(0, 0), ecke(1, 0), ecke(0, 1), ecke(1, 1)
    a = e00 + (e10 - e00) * u
    b = e01 + (e11 - e01) * u
    return (a + (b - a) * v) * 1.41


#: Zwischen den Oktaven drehen, damit keine Achsenrichtung durchscheint.
_DREHUNG = (math.cos(0.61), math.sin(0.61))


def fbm(x, y, keim: int, oktaven: int = 4, gewinn: float = 0.5) -> np.ndarray:
    """Oktaven aufsummiert, etwa −1 … 1."""
    summe = np.zeros_like(x, dtype=np.float64)
    amp, norm = 1.0, 0.0
    c, s = _DREHUNG
    for o in range(oktaven):
        summe += amp * gradientenrauschen(x, y, keim + 97 * o)
        norm += amp
        amp *= gewinn
        x, y = (c * x - s * y) * 2.0 + 13.7, (s * x + c * y) * 2.0 - 7.3
    return summe / norm


def graten(x, y, keim: int, oktaven: int = 5) -> np.ndarray:
    """Grat-Rauschen für Gebirge: scharfe Kämme, runde Täler, 0 … 1."""
    summe = np.zeros_like(x, dtype=np.float64)
    amp, norm = 1.0, 0.0
    gewicht = np.ones_like(summe)
    c, s = _DREHUNG
    for o in range(oktaven):
        n = 1.0 - np.abs(gradientenrauschen(x, y, keim + 131 * o))
        n = n * n * gewicht
        gewicht = np.clip(n * 1.6, 0.0, 1.0)
        summe += amp * n
        norm += amp
        amp *= 0.5
        x, y = (c * x - s * y) * 2.1 + 3.1, (s * x + c * y) * 2.1 + 9.9
    return summe / norm


def glatt(a: float, b: float, x) -> np.ndarray:
    """Glatte Stufe von 0 (bei a) auf 1 (bei b), erste und zweite Ableitung am Rand 0."""
    t = np.clip((np.asarray(x, dtype=np.float64) - a) / max(b - a, 1e-9), 0.0, 1.0)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def form(art: str, x, y, keim: int) -> np.ndarray:
    """Die Gestalt einer Geländeart, ``x``/``y`` schon durch die Wellenlänge geteilt.

    Ungefähr 0 … 1; ``wellen`` und ``huegel`` gehen auch etwas unter 0 —
    dann liegt die Strecke auf einem flachen Damm statt in einer Mulde.
    """
    if art == "wellen":
        return 0.35 + 0.65 * fbm(x, y, keim, 3)
    if art == "huegel":
        f = 0.5 + 0.5 * fbm(x, y, keim, 5, 0.45)
        return np.clip(f, 0.0, None) ** 1.35 * 1.4 - 0.15
    if art == "duenen":
        # Kämme quer zum Wind, vom Rauschen verbogen; asymmetrisch wie echte
        # Dünen (flache Luv-, steilere Leeseite).
        w = 0.35
        phase = (x * math.cos(w) + y * math.sin(w)) * 2.0 * math.pi + 2.2 * fbm(x * 0.35, y * 0.35, keim, 3)
        kamm = 0.5 + 0.5 * np.sin(phase + 0.7 * np.sin(phase))
        huelle = 0.55 + 0.45 * fbm(x * 0.4 + 5.0, y * 0.4, keim + 7, 2)
        return kamm ** 1.6 * huelle + 0.12 * fbm(x * 3.0, y * 3.0, keim + 3, 2)
    if art == "tafelberge":
        m = fbm(x, y, keim, 4, 0.42)
        rand = 0.03 * fbm(x * 8.0, y * 8.0, keim + 5, 3)
        oben = glatt(0.10, 0.15, m + rand)
        stufe = glatt(-0.02, 0.02, m + rand)
        schutt = 0.10 * glatt(-0.2, 0.1, m) * (0.5 + 0.5 * fbm(x * 5.0, y * 5.0, keim + 9, 2))
        return 0.72 * oben + 0.22 * stufe + schutt
    if art == "berge":
        return graten(x, y, keim, 6) ** 1.25 * 1.3
    return np.zeros_like(np.asarray(x, dtype=np.float64))


# ---------------------------------------------------------------------------
# Das Gelände einer Strecke
# ---------------------------------------------------------------------------

@dataclass
class Gelaendenetz:
    positionen: np.ndarray       # (n, 3) float32
    normalen: np.ndarray         # (n, 3) float32
    uv: np.ndarray               # (n, 2) float32
    indizes: np.ndarray          # (m, 3) uint32 — erst das Gitter, dann die Ringe
    gitter_dreiecke: int = 0     # so viele Dreiecke vorne gehören zum Gitter


@dataclass
class _Ebnung:
    x: float
    y: float
    r: float
    abfall: float
    hoehe: float


def korridor_m(art, rand_arten=(), auslauf_m: float = 0.0) -> float:
    """Wie weit ab der Fahrbahnkante das Gelände flach bleibt.

    Mindestens ``art.korridor_m``; Randobjekte, die in einer Reihe an der
    Strecke stehen (Banden, Zäune, Laternen), verbreitern ihn so, dass sie
    mit etwas Luft auf dem Flachen stehen, ebenso der Auslauf (Kies) außen
    an den Kurven. Einzelstücke wie die Tribüne
    bekommen stattdessen eine eigene ebene Stelle.
    """
    breite = max(float(art.korridor_m), float(auslauf_m) + 4.0)
    for r in rand_arten:
        if getattr(r, "art", "reihe") == "start":
            continue
        breite = max(breite, float(r.abstand_m) + 2.5)
    return breite


class Gelaende:
    """Höhenfeld, Netz und Abfragen für eine Strecke."""

    def __init__(self, mittellinie_m, halbe_breite_m: float, art, name: str,
                 rand_arten=(), auslauf_m: float = 0.0, detail: int = 2) -> None:
        self.linie = np.asarray(mittellinie_m, dtype=np.float64)[:, :2]
        self.halbbreite = float(halbe_breite_m)
        self.art = art
        self.keim = keim_aus_namen(f"gelaende:{name}")
        self.detail = DETAIL.get(int(detail), DETAIL[2])
        self.korridor = korridor_m(art, rand_arten, auslauf_m)
        self.auslauf_m = float(auslauf_m)
        self.lo = self.linie.min(axis=0)
        self.hi = self.linie.max(axis=0)
        self.mitte = (self.lo + self.hi) / 2.0
        self.halb = (self.hi - self.lo) / 2.0
        self._ebnungen: list[_Ebnung] = []
        self._gitter = None
        self._abstandskarte()

    # -- Abstand zur Fahrbahnkante -----------------------------------------
    def _abstandskarte(self) -> None:
        """Abstand zur Fahrbahnkante auf einem Raster um die Strecke.

        Ein Raster statt jedes Punkt einzeln: die genaue Rechnung gegen alle
        Abschnitte der Mittellinie kostet für hunderttausend Punkte Sekunden.
        Jeder dritte Punkt der Mittellinie reicht (Fehler unter 20 cm), und
        der Abstand ist so glatt, dass bilinear zwischen den Rasterpunkten
        nichts verloren geht, was man sähe.
        """
        rand = self.korridor + self.art.anstieg_m + 3 * ABSTAND_RASTER_M
        lo, hi = self.lo - rand, self.hi + rand
        n = np.ceil((hi - lo) / ABSTAND_RASTER_M).astype(int) + 1
        xs = lo[0] + np.arange(n[0]) * ABSTAND_RASTER_M
        ys = lo[1] + np.arange(n[1]) * ABSTAND_RASTER_M
        gx, gy = np.meshgrid(xs, ys)
        schritt = 3 if len(self.linie) > 60 else 1
        linie = self.linie[::schritt]
        punkte = np.stack([gx.ravel(), gy.ravel()], axis=1)
        d = abstand_zur_linie(punkte, linie)
        self._raster = (lo, n, (d - self.halbbreite).reshape(n[1], n[0]))
        # Dazu der nächste Punkt der Mittellinie je Rasterpunkt (für die Seite).
        self._index_raster = np.minimum(naechster_punkt(punkte, linie) * schritt,
                                        len(self.linie) - 1).reshape(n[1], n[0])
        self._raster_rand = rand

    def kantenabstand(self, x, y) -> np.ndarray:
        """Abstand zur Fahrbahnkante (negativ auf der Fahrbahn); fern: groß."""
        lo, n, d = self._raster
        fx = (np.asarray(x, dtype=np.float64) - lo[0]) / ABSTAND_RASTER_M
        fy = (np.asarray(y, dtype=np.float64) - lo[1]) / ABSTAND_RASTER_M
        drin = (fx >= 0) & (fy >= 0) & (fx <= n[0] - 1) & (fy <= n[1] - 1)
        i = np.clip(np.floor(fx).astype(int), 0, n[0] - 2)
        j = np.clip(np.floor(fy).astype(int), 0, n[1] - 2)
        u = np.clip(fx - i, 0.0, 1.0)
        v = np.clip(fy - j, 0.0, 1.0)
        wert = (d[j, i] * (1 - u) * (1 - v) + d[j, i + 1] * u * (1 - v)
                + d[j + 1, i] * (1 - u) * v + d[j + 1, i + 1] * u * v)
        return np.where(drin, wert, 1e6)

    def naechster_index(self, x, y) -> np.ndarray:
        """Ungefähr nächster Punkt der Mittellinie (aus der Rasterzelle)."""
        lo, n, _d = self._raster
        i = np.clip(np.rint((np.asarray(x) - lo[0]) / ABSTAND_RASTER_M).astype(int), 0, n[0] - 1)
        j = np.clip(np.rint((np.asarray(y) - lo[1]) / ABSTAND_RASTER_M).astype(int), 0, n[1] - 1)
        return self._index_raster[j, i]

    def rechteckabstand(self, x, y) -> np.ndarray:
        """Abstand zum Rechteck um die Strecke (0 innen)."""
        dx = np.maximum(np.abs(np.asarray(x, dtype=np.float64) - self.mitte[0]) - self.halb[0], 0.0)
        dy = np.maximum(np.abs(np.asarray(y, dtype=np.float64) - self.mitte[1]) - self.halb[1], 0.0)
        return np.hypot(dx, dy)

    # -- Höhenfeld ---------------------------------------------------------
    def feld(self, x, y, ebnen: bool = True) -> np.ndarray:
        """Die mathematische Höhe (ohne Netz), in Metern über der Fahrbahn."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        a = self.art
        x, y = np.broadcast_arrays(x, y)
        nah = glatt(self.korridor, self.korridor + a.anstieg_m, self.kantenabstand(x, y))
        h = np.zeros(x.shape)
        rechteck = self.rechteckabstand(x, y)
        zonen = (("nah", None), ("fern", a.fern_ab_m), ("horizont", a.horizont_ab_m))
        for k, (zone, ab) in enumerate(zonen):
            hoehe = float(getattr(a, f"{zone}_hoehe_m"))
            if hoehe == 0.0:
                continue
            lam = max(float(getattr(a, f"{zone}_wellenlaenge_m")), 1.0)
            art = getattr(a, f"{zone}_art")
            if ab is None:
                h = h + hoehe * form(art, x / lam, y / lam, self.keim + 1009 * k)
                continue
            # Ferne Zonen nur dort rechnen, wo sie etwas beitragen.
            maske = glatt(ab, ab * 1.7 + 60.0, rechteck)
            wo = maske > 0
            if not wo.any():
                continue
            h[wo] += hoehe * maske[wo] * form(art, x[wo] / lam, y[wo] / lam, self.keim + 1009 * k)
        h = h * nah
        if ebnen:
            for e in self._ebnungen:
                w = 1.0 - glatt(e.r, e.r + e.abfall, np.hypot(x - e.x, y - e.y))
                h = h + (e.hoehe - h) * w
        return h

    def neigung_feld_grad(self, x, y, r: float = 2.0) -> np.ndarray:
        """Neigung der mathematischen Fläche (ohne Ebnungen), in Grad."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        gx = (self.feld(x + r, y, False) - self.feld(x - r, y, False)) / (2 * r)
        gy = (self.feld(x, y + r, False) - self.feld(x, y - r, False)) / (2 * r)
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    def ebnen(self, x: float, y: float, r: float, abfall: float | None = None) -> float:
        """Eine ebene Stelle anlegen (Haus, Tribüne); liefert ihre Höhe.

        Die Stelle liegt auf der tiefsten Höhe ihres Fußabdrucks: das Haus
        steht in einem kleinen Einschnitt am Hang, nicht auf einem Sockel in
        der Luft. Muss vor der ersten Abfrage des Netzes geschehen.

        Reicht die Stelle samt Übergang an den Korridor heran, liegt sie auf
        Höhe 0 — der Korridor bleibt flach, und zwischen ihm und der Stelle
        entsteht keine Stufe.
        """
        abfall = float(abfall if abfall is not None else max(16.0, 1.5 * r))
        w = np.linspace(0, 2 * math.pi, 12, endpoint=False)
        px = np.concatenate([[x], x + r * np.cos(w)])
        py = np.concatenate([[y], y + r * np.sin(w)])
        hoehe = float(self.feld(px, py).min())
        kante = float(self.kantenabstand(np.array([x]), np.array([y]))[0])
        if kante - r - abfall < self.korridor + self.art.anstieg_m:
            hoehe = 0.0
        self._ebnungen.append(_Ebnung(float(x), float(y), float(r), abfall, hoehe))
        self._gitter = None
        return hoehe

    # -- Gitter ------------------------------------------------------------
    def _achse(self, lo_kern: float, hi_kern: float, lo: float, hi: float) -> np.ndarray:
        fein, grob = self.detail["fein_m"], self.detail["grob_m"]
        n = max(2, int(math.ceil((hi_kern - lo_kern) / fein)))
        kern = np.linspace(lo_kern, hi_kern, n + 1)
        schritt = kern[1] - kern[0]
        aussen = []
        s, p = schritt, 0.0
        while p < (hi - hi_kern) - 1e-6:
            s = min(grob, s * 1.12)
            p = min(p + s, hi - hi_kern)
            aussen.append(p)
        aussen = np.asarray(aussen)
        return np.concatenate([lo_kern - aussen[::-1], kern, hi_kern + aussen])

    def _gitter_bauen(self):
        if self._gitter is not None:
            return self._gitter
        xs = self._achse(self.lo[0] - KERN_RAND_M, self.hi[0] + KERN_RAND_M,
                         self.lo[0] - GITTER_RAND_M, self.hi[0] + GITTER_RAND_M)
        ys = self._achse(self.lo[1] - KERN_RAND_M, self.hi[1] + KERN_RAND_M,
                         self.lo[1] - GITTER_RAND_M, self.hi[1] + GITTER_RAND_M)
        gx, gy = np.meshgrid(xs, ys)
        z = self.feld(gx, gy)
        self._gitter = (xs, ys, z)
        return self._gitter

    def hoehe(self, x, y) -> np.ndarray:
        """Höhe des **gezeichneten** Bodens: im Gitter wie das Dreieck, außen das Feld."""
        xs, ys, z = self._gitter_bauen()
        x = np.atleast_1d(np.asarray(x, dtype=np.float64))
        y = np.atleast_1d(np.asarray(y, dtype=np.float64))
        i = np.searchsorted(xs, x) - 1
        j = np.searchsorted(ys, y) - 1
        drin = (i >= 0) & (j >= 0) & (i < len(xs) - 1) & (j < len(ys) - 1)
        i = np.clip(i, 0, len(xs) - 2)
        j = np.clip(j, 0, len(ys) - 2)
        u = np.clip((x - xs[i]) / (xs[i + 1] - xs[i]), 0.0, 1.0)
        v = np.clip((y - ys[j]) / (ys[j + 1] - ys[j]), 0.0, 1.0)
        z00, z10, z01, z11 = z[j, i], z[j, i + 1], z[j + 1, i], z[j + 1, i + 1]
        # Dieselbe Diagonale wie im Netz: (i, j) → (i+1, j+1).
        unten = u >= v
        wert = np.where(unten, z00 + u * (z10 - z00) + v * (z11 - z10),
                        z00 + v * (z01 - z00) + u * (z11 - z01))
        ergebnis = np.where(drin, wert, 0.0)
        if not drin.all():
            ergebnis[~drin] = self.feld(x[~drin], y[~drin])
        return ergebnis

    def neigung_grad(self, x, y, r: float = 1.5) -> np.ndarray:
        """Neigung des gezeichneten Bodens, in Grad."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        gx = (self.hoehe(x + r, y) - self.hoehe(x - r, y)) / (2 * r)
        gy = (self.hoehe(x, y + r) - self.hoehe(x, y - r)) / (2 * r)
        return np.degrees(np.arctan(np.hypot(gx, gy)))

    # -- Netz --------------------------------------------------------------
    def netz(self) -> Gelaendenetz:
        """Gitter plus Ringe bis :data:`AUSSEN_M`, mit Normalen."""
        xs, ys, z = self._gitter_bauen()
        nx, ny = len(xs), len(ys)
        gx, gy = np.meshgrid(xs, ys)
        pos_gitter = np.stack([gx.ravel(), gy.ravel(), z.ravel()], axis=1)
        idx = np.arange(nx * ny).reshape(ny, nx)
        a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
        c, d = idx[1:, :-1].ravel(), idx[1:, 1:].ravel()
        # Diagonale a–d, wie in :meth:`hoehe`.
        dreiecke = [np.stack([a, b, d], axis=1), np.stack([a, d, c], axis=1)]
        gitter_dreiecke = 2 * len(a)

        # Rand des Gitters gegen den Uhrzeigersinn: unten, rechts, oben, links.
        rand = np.concatenate([idx[0, :-1], idx[:-1, -1], idx[-1, :0:-1], idx[:0:-1, 0]])
        mitte = np.array([(xs[0] + xs[-1]) / 2, (ys[0] + ys[-1]) / 2])
        halb = np.array([(xs[-1] - xs[0]) / 2, (ys[-1] - ys[0]) / 2])
        rand_w = np.arctan2(pos_gitter[rand, 1] - mitte[1], pos_gitter[rand, 0] - mitte[0])
        ordnung = np.argsort(rand_w)
        rand, rand_w = rand[ordnung], rand_w[ordnung]

        m = int(self.detail["winkel"])
        w = -math.pi + (np.arange(m) + 0.5) * 2 * math.pi / m
        cw, sw = np.cos(w), np.sin(w)
        with np.errstate(divide="ignore"):
            rho_rand = np.minimum(halb[0] / np.maximum(np.abs(cw), 1e-9),
                                  halb[1] / np.maximum(np.abs(sw), 1e-9))
        rho_mittel = float(rho_rand.mean())
        delta_max = AUSSEN_M - float(rho_rand.max())
        deltas = []
        dlt = self.detail["grob_m"]
        while dlt < delta_max:
            deltas.append(dlt)
            dlt += max(self.detail["grob_m"], self.detail["wachstum"] * (rho_mittel + dlt))
        deltas.append(delta_max)

        ringe = []
        for dl in deltas:
            rho = rho_rand + dl
            ringe.append(np.stack([mitte[0] + rho * cw, mitte[1] + rho * sw], axis=1))
        ring_xy = np.concatenate(ringe)
        ring_z = self.feld(ring_xy[:, 0], ring_xy[:, 1])
        basis = len(pos_gitter)
        positionen = np.concatenate([pos_gitter, np.column_stack([ring_xy, ring_z])])

        # Reißverschluss vom Gitterrand zum ersten Ring: beide nach Winkel
        # geordnet, je Schritt ein Dreieck, jeder Punkt wird benutzt.
        dreiecke.append(_reissverschluss(rand, rand_w, basis + np.arange(m), w))
        for k in range(len(deltas) - 1):
            innen = basis + k * m + np.arange(m)
            aussen = innen + m
            i1, a1 = np.roll(innen, -1), np.roll(aussen, -1)
            dreiecke += [np.stack([innen, aussen, a1], axis=1), np.stack([innen, a1, i1], axis=1)]
        indizes = np.concatenate(dreiecke).astype(np.uint32)

        positionen[:, 2] += VERSATZ_M
        normalen = _normalen(positionen, indizes)
        return Gelaendenetz(positionen.astype(np.float32), normalen,
                            positionen[:, :2].astype(np.float32), indizes, gitter_dreiecke)


def _reissverschluss(innen, innen_w, aussen, aussen_w) -> np.ndarray:
    """Zwei geschlossene, nach Winkel geordnete Punktreihen mit Dreiecken verbinden."""
    n, m = len(innen), len(aussen)
    i = j = 0
    dreiecke = []
    zwei_pi = 2 * math.pi
    # Beide Reihen beginnen bei −π; am Ende noch einmal den Anfang, um zu schließen.
    iw = np.concatenate([innen_w, innen_w[:1] + zwei_pi])
    aw = np.concatenate([aussen_w, aussen_w[:1] + zwei_pi])
    while i < n or j < m:
        if j >= m or (i < n and iw[i + 1] <= aw[j + 1]):
            dreiecke.append((innen[i % n], aussen[j % m], innen[(i + 1) % n]))
            i += 1
        else:
            dreiecke.append((innen[i % n], aussen[j % m], aussen[(j + 1) % m]))
            j += 1
    return np.asarray(dreiecke, dtype=np.int64)


def _normalen(positionen: np.ndarray, indizes: np.ndarray) -> np.ndarray:
    """Flächengewichtete Eckennormalen; alle zeigen nach oben (Höhenfeld)."""
    p = positionen.astype(np.float64)
    a, b, c = p[indizes[:, 0]], p[indizes[:, 1]], p[indizes[:, 2]]
    fn = np.cross(b - a, c - a)
    fn *= np.where(fn[:, 2:3] < 0, -1.0, 1.0)
    n = np.zeros_like(p)
    ecken = indizes.ravel()
    for achse in range(3):
        n[:, achse] = np.bincount(ecken, weights=np.repeat(fn[:, achse], 3), minlength=len(p))
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return n.astype(np.float32)


# ---------------------------------------------------------------------------
# Gras
# ---------------------------------------------------------------------------

#: Kachelgröße für die Auswahl je Bild, Meter.
GRAS_KACHEL_M = 24.0
#: Zeichenweite je ``grafik.gras`` (0 = aus).
GRAS_WEITE_M = {1: 45.0, 2: 70.0}
#: Dichte je ``grafik.gras``, Anteil der Themen-Dichte.
GRAS_ANTEIL = {1: 0.45, 2: 1.0}
#: Innerster Abstand zur Fahrbahnkante: hinter Randstein und Begrenzung
#: (bis 0,65 m), mit Luft für die Rasterung der Abstandskarte (unter 0,2 m).
GRAS_INNEN_M = 1.1
#: Varianten des Büschels, damit sich keine zwei Nachbarn gleichen.
GRAS_VARIANTEN = 3


@dataclass
class Grasfeld:
    pos: np.ndarray          # (k, 3)
    gier: np.ndarray         # (k,)
    skala: np.ndarray        # (k,)
    variante: np.ndarray     # (k,) int
    kachel: np.ndarray = field(default_factory=lambda: np.zeros((0, 2), dtype=np.int64))


def naechster_punkt(punkte: np.ndarray, linie: np.ndarray, block: int = 2048) -> np.ndarray:
    """Index des nächsten Punkts der Linie, für viele Punkte auf einmal."""
    ergebnis = np.empty(len(punkte), dtype=np.int64)
    for s in range(0, len(punkte), block):
        q = punkte[s:s + block, None, :]
        ergebnis[s:s + block] = ((q - linie[None]) ** 2).sum(axis=2).argmin(axis=1)
    return ergebnis


def gras_platzieren(gel: Gelaende, gras, stufe: int, name: str, sperren=None) -> Grasfeld:
    """Wo Büschel stehen: dicht am Rand, nach außen weniger, in Flecken.

    ``sperren``: gedrehte Rechtecke ohne Gras — Vorplätze, Tribünen, Häuser
    (Zeilen wie :func:`platzierung.grasfreie_flaechen`, 0,5 m Rand dazu).
    """
    leer = Grasfeld(np.zeros((0, 3)), np.zeros(0), np.zeros(0), np.zeros(0, dtype=int))
    if not gras.an or stufe <= 0:
        return leer
    rng = np.random.default_rng(keim_aus_namen(f"gras:{name}"))
    rand = gras.bis_m + gel.halbbreite
    lo, hi = gel.lo - rand, gel.hi + rand
    flaeche = float(np.prod(hi - lo))
    dichte = gras.dichte_je_m2 * GRAS_ANTEIL.get(stufe, 1.0)
    p = rng.uniform(lo, hi, size=(int(flaeche * dichte), 2))
    d = gel.kantenabstand(p[:, 0], p[:, 1])
    ok = (d > GRAS_INNEN_M - 1.0) & (d < gras.bis_m)
    p, d = p[ok], d[ok]
    t = np.clip((d - GRAS_INNEN_M) / (gras.bis_m - GRAS_INNEN_M), 0.0, 1.0)
    flecken = 0.5 + 0.5 * fbm(p[:, 0] / 9.0, p[:, 1] / 9.0, gel.keim + 77, 3)
    behalten = (d >= GRAS_INNEN_M) & (rng.uniform(size=len(p)) < (1.0 - t) ** 0.8 * glatt(0.25, 0.6, flecken) * 1.6)
    p, d = p[behalten], d[behalten]
    if gel.auslauf_m > 0 and len(p):
        # Kein Gras im Kies: die Auslaufzonen (Strang S) je Seite und Punkt.
        from .track_mesh import auslauf_breiten
        breiten = auslauf_breiten(gel.linie, gel.halbbreite, gel.auslauf_m)
        pruefen = np.flatnonzero(d < gel.auslauf_m + 1.0)
        if len(pruefen):
            q = p[pruefen]
            i = gel.naechster_index(q[:, 0], q[:, 1])
            vor = np.roll(gel.linie, -1, axis=0) - np.roll(gel.linie, 1, axis=0)
            links = np.stack([-vor[:, 1], vor[:, 0]], axis=1)
            seite_links = ((q - gel.linie[i]) * links[i]).sum(axis=1) > 0
            breite = np.where(seite_links, breiten[0][i], breiten[1][i])
            weg = np.zeros(len(p), dtype=bool)
            weg[pruefen] = d[pruefen] < breite + 0.4
            p, d = p[~weg], d[~weg]
    if sperren is not None and len(sperren) and len(p):
        frei = np.ones(len(p), dtype=bool)
        for x, y, gier, x0, x1, y0, y1 in np.asarray(sperren, dtype=np.float64):
            c, s = math.cos(gier), math.sin(gier)
            dx, dy = p[:, 0] - x, p[:, 1] - y
            lx, ly = c * dx + s * dy, -s * dx + c * dy
            frei &= ~((lx > x0 - 0.5) & (lx < x1 + 0.5) & (ly > y0 - 0.5) & (ly < y1 + 0.5))
        p = p[frei]
    if len(p) == 0:
        return leer
    neigung = gel.neigung_grad(p[:, 0], p[:, 1])
    p = p[neigung < 32.0]
    z = gel.hoehe(p[:, 0], p[:, 1]) + VERSATZ_M
    k = len(p)
    skala = rng.uniform(*gras.hoehe_m, size=k)
    return Grasfeld(pos=np.column_stack([p, z]), gier=rng.uniform(0, 2 * math.pi, size=k),
                    skala=skala, variante=rng.integers(0, GRAS_VARIANTEN, size=k),
                    kachel=np.floor(p / GRAS_KACHEL_M).astype(np.int64))


def mittlere_farbe(pfad, ton=(1.0, 1.0, 1.0)):
    """Mittlere Farbe einer Bilddatei (sRGB 0..1), getönt; ``None`` ohne Datei."""
    try:
        from PIL import Image
        with Image.open(pfad) as bild:
            rgb = np.asarray(bild.convert("RGB").resize((16, 16)), dtype=np.float64) / 255.0
    except (OSError, ValueError):
        return None
    lin = (rgb ** 2.2).mean(axis=(0, 1)) * np.asarray(ton, dtype=np.float64)
    return tuple(np.clip(lin, 0, 1) ** (1 / 2.2))


def grasbueschel(gras, keim: int, spalten: int = 8):
    """Ein Büschel aus Halmen, 1 m hoch (die Instanz skaliert auf die echte Höhe).

    Jeder Halm: Fuß, Knick, Spitze — drei Dreiecke. Die Normalen zeigen fast
    nach oben: ein Grasbüschel wird wie der Boden darunter beleuchtet, nicht
    wie ein Stapel Papierstreifen. ``u`` wählt die Farbspalte eines Halms,
    ``v`` läuft vom Fuß (0) zur Spitze (1).
    """
    rng = np.random.default_rng(keim)
    pos, nor, uv, idx = [], [], [], []
    streuung = 0.28 if gras.trocken else 0.2
    for h in range(int(gras.halme)):
        r = streuung * math.sqrt(rng.uniform())
        w = rng.uniform(0, 2 * math.pi)
        fuss = np.array([r * math.cos(w), r * math.sin(w), 0.0])
        laenge = rng.uniform(0.55, 1.0)
        # Nach außen geneigt; trockene Halme weit gespreizt.
        neigung = rng.uniform(0.15, 0.45) + (0.35 if gras.trocken else 0.0)
        richtung = w + rng.uniform(-0.6, 0.6)
        aus = np.array([math.cos(richtung), math.sin(richtung), 0.0])
        quer = np.array([-aus[1], aus[0], 0.0])
        breite = rng.uniform(0.018, 0.032) * (1.3 if gras.trocken else 1.0)
        knick = fuss + aus * neigung * 0.35 * laenge + np.array([0, 0, 0.55 * laenge])
        spitze = fuss + aus * neigung * laenge + np.array([0, 0, laenge * (0.92 - 0.25 * neigung)])
        punkte = [fuss - quer * breite, fuss + quer * breite,
                  knick - quer * breite * 0.65, knick + quer * breite * 0.65, spitze]
        n = np.array([0.0, 0.0, 1.0]) + aus * 0.25
        n /= np.linalg.norm(n)
        u = (rng.integers(0, spalten) + 0.5) / spalten
        basis = len(pos)
        for k, pk in enumerate(punkte):
            pos.append(pk)
            nor.append(n)
            uv.append((u, (0.0, 0.0, 0.55, 0.55, 1.0)[k]))
        idx += [(basis, basis + 1, basis + 3), (basis, basis + 3, basis + 2),
                (basis + 2, basis + 3, basis + 4)]
    return (np.asarray(pos, np.float32), np.asarray(nor, np.float32),
            np.asarray(uv, np.float32), np.asarray(idx, np.uint32))


def grasfarben(gras, keim: int, boden=None, spalten: int = 8, zeilen: int = 16) -> np.ndarray:
    """Farbtafel der Halme (zeilen × spalten × 3, uint8), Zeile 0 = Fuß.

    ``boden`` ist die mittlere Farbe der Bodentextur (sRGB, schon getönt):
    der Fuß der Halme geht halb in sie über, sonst stehen die Büschel wie
    aufgeklebt auf dem Boden.
    """
    rng = np.random.default_rng(keim)
    fuss = np.asarray(gras.farbe, dtype=np.float64)
    spitze = np.asarray(gras.spitze, dtype=np.float64)
    if boden is not None:
        boden = np.asarray(boden, dtype=np.float64)
        fuss = 0.5 * fuss + 0.5 * boden * 0.85
        spitze = 0.75 * spitze + 0.25 * np.clip(boden * 1.3, 0, 1)
    t = np.linspace(0, 1, zeilen)[:, None, None]
    tafel = fuss * (0.55 + 0.45 * t) * (1 - t) + spitze * t
    hell = rng.uniform(0.82, 1.15, size=(1, spalten, 1))
    gelb = rng.uniform(-0.06, 0.08, size=(1, spalten, 1)) * np.array([1.0, 0.6, -0.8])
    tafel = np.clip((tafel + gelb * t) * hell, 0, 1)
    return (tafel * 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Zeichnen
# ---------------------------------------------------------------------------

#: Ob das Gelände in die Schattenkarte zeichnet. **Aus**, mit Absicht: die
#: Karte reicht 150 m um den Blickpunkt. Ein Hang darin beschattet sich
#: selbst, derselbe Hang einen Schritt weiter draußen nicht — an der
#: Kartengrenze läuft eine harte, gerade Kante quer über den Berg, und sie
#: wandert mit dem Auto. Die Hänge schattiert der Sonnenwinkel ohnehin
#: weich (abgewandte Seiten dunkel); Schatten *empfängt* das Gelände weiter
#: von Bäumen, Häusern und Autos. Wer es wieder einschaltet, braucht erst
#: eine Karte mit Kaskaden.
GELAENDE_WIRFT_SCHATTEN = False

#: Textureinheiten der drei Bodenschichten (0–3 sind vergeben, siehe shader.py).
EINHEITEN = (8, 9, 10)


def _vao(ctx, programm, positionen, normalen, uv, indizes):
    puffer = [ctx.buffer(np.ascontiguousarray(positionen, "f4")),
              ctx.buffer(np.ascontiguousarray(normalen, "f4")),
              ctx.buffer(np.ascontiguousarray(uv, "f4"))]
    ibo = ctx.buffer(np.ascontiguousarray(indizes, "u4"))
    vao = ctx.vertex_array(programm, [(puffer[0], "3f", "in_position"),
                                      (puffer[1], "3f", "in_normale"),
                                      (puffer[2], "2f", "in_uv")], ibo)
    return vao, puffer + [ibo]


class Gelaendezeichner:
    """Das Geländenetz auf der Grafikkarte, mit Hang- und Höhenmischung."""

    def __init__(self, ctx, programm, schattenprogramm, gel: Gelaende, texturen: dict) -> None:
        self.ctx = ctx
        self.programm = programm
        self.gel = gel
        netz = gel.netz()
        self.dreiecke = len(netz.indizes)
        self.vao, self.puffer = _vao(ctx, programm, netz.positionen, netz.normalen,
                                     netz.uv, netz.indizes)
        self.vao_schatten = None
        if schattenprogramm is not None and GELAENDE_WIRFT_SCHATTEN:
            # Nur das Gitter: die Schattenkarte deckt ohnehin nur 150 m um den
            # Blickpunkt ab, die Ringe liegen weiter draußen.
            vp = ctx.buffer(np.ascontiguousarray(netz.positionen, "f4"))
            vu = ctx.buffer(np.ascontiguousarray(netz.uv, "f4"))
            ib = ctx.buffer(np.ascontiguousarray(netz.indizes[:netz.gitter_dreiecke], "u4"))
            self.puffer += [vp, vu, ib]
            self.vao_schatten = ctx.vertex_array(
                schattenprogramm, [(vp, "3f", "in_position"), (vu, "2f", "in_uv")], ib)
        self.texturen = texturen      # Schicht → (farbe, mr) oder None

    def _uniforms(self) -> None:
        p = self.programm
        a = self.gel.art
        schichten = (a.unten, a.hang, a.fels)
        for einheit, name, s in zip(EINHEITEN, ("gelaende_unten", "gelaende_hang", "gelaende_fels"),
                                    schichten):
            shader.setzen(p, name, einheit)
            t = self.texturen.get(name)
            if t is not None:
                t.use(einheit)
        shader.setzen(p, "gelaende_kachel", tuple(1.0 / max(s.kachel_m, 0.1) for s in schichten))
        shader.setzen(p, "gelaende_ton_unten", tuple(float(c) for c in a.unten.ton))
        shader.setzen(p, "gelaende_ton_hang", tuple(float(c) for c in a.hang.ton))
        shader.setzen(p, "gelaende_ton_fels", tuple(float(c) for c in a.fels.ton))
        shader.setzen(p, "gelaende_grenzen", (float(a.hang_ab), float(a.fels_ab),
                                              float(min(a.hang_hoehe_m, 1e6)),
                                              float(a.schnee_ab_m) if a.schnee_ab_m is not None else -1.0))
        wald = a.wald_farbe
        shader.setzen(p, "gelaende_wald", (*(float(c) for c in wald), float(a.wald_ab_m))
                      if wald is not None else (0.0, 0.0, 0.0, -1.0))
        g = self.gel
        shader.setzen(p, "gelaende_rechteck", (float(g.mitte[0]), float(g.mitte[1]),
                                               float(g.halb[0]), float(g.halb[1])))

    def zeichnen(self) -> None:
        p = self.programm
        self._uniforms()
        shader.setzen(p, "gelaende", 1.0)
        shader.setzen(p, "grundton", (1.0, 1.0, 1.0))
        shader.setzen(p, "hat_basisfarbe", 0.0)
        shader.setzen(p, "hat_metallic_rauheit", 0.0)
        shader.setzen(p, "metallic_faktor", 0.0)
        shader.setzen(p, "rauheit_faktor", 0.95)
        shader.setzen(p, "uv_skala", 1.0)
        shader.setzen(p, "farbton", (1.0, 1.0, 1.0))
        shader.setzen(p, "makro", 0.22)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        shader.setzen(p, "klarlack", 0.0)
        shader.setzen(p, "alpha_faktor", 1.0)
        shader.setzen(p, "alpha_schwelle", 0.0)
        self.vao.render()
        shader.setzen(p, "gelaende", 0.0)

    def schatten_zeichnen(self, programm) -> None:
        if self.vao_schatten is None:
            return
        shader.setzen(programm, "alpha_schwelle", 0.0)
        shader.matrix_setzen(programm, "modell", np.eye(4))
        self.vao_schatten.render()

    def freigeben(self) -> None:
        for ding in [self.vao, self.vao_schatten, *self.puffer]:
            if ding is not None:
                try:
                    ding.release()
                except Exception:                    # pragma: no cover - Treiber
                    pass


class Graszeichner:
    """Grasbüschel instanziert, je Bild nur die Kacheln in Reichweite.

    Die Auswahl kostet Zeit auf der CPU, nicht auf der Grafikkarte: bei
    dichtem Gras sind es zehntausende Matrizen. Deshalb zweierlei:

    * Die Büschel liegen nach Kachel sortiert; sichtbar ist, was in einer
      sichtbaren Kachel liegt, und das sind zusammenhängende Scheiben.
    * Hat sich die Kamera seit der letzten Auswahl kaum bewegt und kaum
      gedreht, bleibt der Instanzpuffer, wie er ist. Die Auswahl hat Rand
      genug, dass dabei nichts fehlt; bei Renntempo wird sie nur jedes
      dritte, vierte Bild neu gerechnet.
    """

    #: So weit darf sich die Kamera bewegen (m) und drehen (1 − cos), bevor
    #: neu ausgewählt wird.
    NEU_AB_M = 2.5
    NEU_AB_DREHUNG = 0.004

    def __init__(self, ctx, programm_instanz, feld: Grasfeld, gras, keim: int, weite_m: float,
                 boden=None) -> None:
        from .deko import instanzmatrizen
        self.ctx = ctx
        self.programm = programm_instanz
        self.weite = float(weite_m)
        self.puffer = []
        self.varianten = []
        self.anzahl = len(feld.pos)
        tafel = grasfarben(gras, keim, boden)
        self.textur = ctx.texture((tafel.shape[1], tafel.shape[0]), 3, np.ascontiguousarray(tafel).tobytes())
        self.textur.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.textur.repeat_x = False
        self.textur.repeat_y = False
        # Kacheln durchnummerieren; jedes Büschel kennt seine Nummer.
        if len(feld.pos):
            kacheln, kachel_nr = np.unique(feld.kachel, axis=0, return_inverse=True)
            kachel_nr = np.asarray(kachel_nr).ravel()
        else:
            kacheln, kachel_nr = np.zeros((0, 2)), np.zeros(0, dtype=np.int64)
        self._mitten = (kacheln.astype(np.float64) + 0.5) * GRAS_KACHEL_M
        for v in range(GRAS_VARIANTEN):
            pos, nor, uv, idx = grasbueschel(gras, keim + 31 * v)
            maske = feld.variante == v
            kap = max(1, int(maske.sum()))
            inst = ctx.buffer(reserve=kap * 64, dynamic=True)
            puffer = [ctx.buffer(pos.tobytes()), ctx.buffer(nor.tobytes()), ctx.buffer(uv.tobytes()),
                      ctx.buffer(idx.tobytes())]
            vao = ctx.vertex_array(programm_instanz, [
                (puffer[0], "3f", "in_position"), (puffer[1], "3f", "in_normale"),
                (puffer[2], "2f", "in_uv"),
                (inst, "4f 4f 4f 4f/i", "in_inst0", "in_inst1", "in_inst2", "in_inst3")], puffer[3])
            self.puffer += puffer + [inst]
            # Nach Kachel sortiert: eine Kachel ist dann eine Scheibe im Feld,
            # und die Auswahl je Bild kopiert zusammenhängende Stücke.
            ordnung = np.argsort(kachel_nr[maske], kind="stable")
            p = feld.pos[maske][ordnung].astype(np.float32)
            nr = kachel_nr[maske][ordnung]
            self.varianten.append(dict(
                vao=vao, inst=inst, kap=kap, xy=p[:, :2].copy(),
                grenzen=np.searchsorted(nr, np.arange(len(kacheln) + 1)),
                mat=instanzmatrizen(p, feld.gier[maske][ordnung].astype(np.float32),
                                    feld.skala[maske][ordnung].astype(np.float32)),
                anzahl=0))
        self._zuletzt = None          # (auge, blickrichtung) der letzten Auswahl

    def _auswaehlen(self, mvp, auge) -> None:
        radius = GRAS_KACHEL_M * 0.75
        d = np.linalg.norm(self._mitten - auge[:2], axis=1)
        h = np.column_stack([self._mitten, np.full(len(self._mitten), auge[2] - 2.0),
                             np.ones(len(self._mitten))]) @ np.asarray(mvp, dtype=np.float64).T
        # Großzügig: die Auswahl gilt auch noch ein paar Grad weiter gedreht.
        sicht = (d < self.weite + radius) & (h[:, 3] > -radius) \
            & (np.abs(h[:, 0]) < h[:, 3] * 1.25 + radius * 2) & (np.abs(h[:, 1]) < h[:, 3] * 1.25 + radius * 3)
        innen = self.weite * 0.7
        auge32 = auge[:2].astype(np.float32)
        # Innen ganze Kacheln wie sie sind; nur Kacheln am äußeren Ring
        # bekommen je Büschel den Abstand — dort schrumpft das Gras zur
        # Grenze hin, statt aufzupoppen (0 jenseits der Weite).
        ganz = np.flatnonzero(sicht & (d + radius < innen))
        ring = np.flatnonzero(sicht & (d + radius >= innen))
        for v in self.varianten:
            g, mat = v["grenzen"], v["mat"]
            stuecke = [mat[g[k]:g[k + 1]] for k in ganz]
            if len(ring):
                rand = np.concatenate([mat[g[k]:g[k + 1]] for k in ring])
                ab = np.linalg.norm(np.concatenate([v["xy"][g[k]:g[k + 1]] for k in ring]) - auge32,
                                    axis=1)
                f = (1.0 - glatt(innen, self.weite, ab)).astype(np.float32)
                rand = rand[f > 0.02]
                rand[:, [0, 1, 2, 4, 5, 6, 8, 9, 10]] *= f[f > 0.02, None]
                stuecke.append(rand)
            k = min(sum(len(s) for s in stuecke), v["kap"])
            v["anzahl"] = k
            if k:
                v["inst"].orphan(v["kap"] * 64)
                v["inst"].write(np.ascontiguousarray(np.concatenate(stuecke)[:k]).tobytes())

    def zeichnen(self, mvp, kamera_position) -> None:
        if len(self._mitten) == 0:
            return
        auge = np.asarray(kamera_position, dtype=np.float64)
        m = np.asarray(mvp, dtype=np.float64)
        blick = m[3, :3] / max(np.linalg.norm(m[3, :3]), 1e-9)
        z = self._zuletzt
        if z is None or np.linalg.norm(auge - z[0]) > self.NEU_AB_M \
                or 1.0 - float(np.dot(blick, z[1])) > self.NEU_AB_DREHUNG:
            self._auswaehlen(m, auge)
            self._zuletzt = (auge.copy(), blick)
        p = self.programm
        shader.setzen(p, "hat_basisfarbe", 1.0)
        shader.setzen(p, "hat_metallic_rauheit", 0.0)
        shader.setzen(p, "grundton", (1.0, 1.0, 1.0))
        shader.setzen(p, "metallic_faktor", 0.0)
        shader.setzen(p, "rauheit_faktor", 0.8)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        shader.setzen(p, "alpha_faktor", 1.0)
        shader.setzen(p, "alpha_schwelle", 0.0)
        shader.setzen(p, "klarlack", 0.0)
        shader.setzen(p, "nebel_faktor", 1.0)
        self.textur.use(0)
        for v in self.varianten:
            if v["anzahl"]:
                v["vao"].render(instances=v["anzahl"])

    def freigeben(self) -> None:
        for v in self.varianten:
            v["vao"].release()
        for ding in [*self.puffer, self.textur]:
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass


# ---------------------------------------------------------------------------
# Ferner Wald
# ---------------------------------------------------------------------------

@dataclass
class Fernwald:
    pos: np.ndarray          # (k, 3)
    gier: np.ndarray
    skala: np.ndarray


def fernwald_platzieren(gel: Gelaende, name: str, anteil: float = 1.0) -> Fernwald:
    """Baumkegel auf den fernen Hügeln: wo Wald ist, nicht zu steil, unter der Baumgrenze.

    Die echten Bäume stehen bis knapp 300 m von der Strecke; dahinter trägt
    dieser Wald die Silhouette der Hügel. Einzelbäume sieht man dort nicht
    mehr, nur eine gezackte, dunkle Kante gegen den Himmel.
    """
    a = gel.art
    leer = Fernwald(np.zeros((0, 3)), np.zeros(0), np.zeros(0))
    dichte = float(a.fernwald_je_ha) * float(anteil)
    if dichte <= 0:
        return leer
    rng = np.random.default_rng(keim_aus_namen(f"fernwald:{name}"))
    rand = float(a.fernwald_bis_m)
    lo, hi = gel.lo - rand, gel.hi + rand
    anzahl = int(np.prod(hi - lo) / 10_000.0 * dichte)
    p = rng.uniform(lo, hi, size=(anzahl, 2))
    r = gel.rechteckabstand(p[:, 0], p[:, 1])
    p = p[(r > a.wald_ab_m) & (r < rand)]
    # Wald in großen Flächen mit Lichtungen, zum Rand hin ausgefranst.
    maske = 0.5 + 0.5 * fbm(p[:, 0] / 260.0, p[:, 1] / 260.0, gel.keim + 311, 4)
    p = p[rng.uniform(size=len(p)) < glatt(0.42, 0.58, maske)]
    if len(p) == 0:
        return leer
    # Neigung aus Vorwärtsdifferenzen: drei Feldaufrufe statt fünf.
    z = gel.feld(p[:, 0], p[:, 1])
    gx = (gel.feld(p[:, 0] + 4.0, p[:, 1]) - z) / 4.0
    gy = (gel.feld(p[:, 0], p[:, 1] + 4.0) - z) / 4.0
    neigung = np.degrees(np.arctan(np.hypot(gx, gy)))
    ok = neigung < 32.0
    if a.baumgrenze_m is not None:
        ok &= z < a.baumgrenze_m - 40.0 * rng.uniform(size=len(p))
    p, z, neigung = p[ok], z[ok], neigung[ok]
    skala = rng.uniform(0.75, 1.35, size=len(p))
    # Am Hang und auf dem groben Außennetz etwas einsinken lassen, nie schweben.
    z = z - 1.5 - np.tan(np.radians(neigung)) * 3.5 * skala
    return Fernwald(np.column_stack([p, z]), rng.uniform(0, 2 * math.pi, size=len(p)), skala)


def baumkegel(seiten: int = 6, hoehe: float = 16.0, radius: float = 3.6):
    """Ein Nadelbaum für die Ferne: zwei gestapelte Kegel, der Fuß steckt im Boden."""
    pos, nor, idx = [], [], []
    for (z0, z1, r) in ((1.0, hoehe * 0.72, radius), (hoehe * 0.42, hoehe, radius * 0.68)):
        spitze = len(pos)
        pos.append((0.0, 0.0, z1))
        nor.append((0.0, 0.0, 1.0))
        for k in range(seiten):
            w = 2 * math.pi * k / seiten
            pos.append((r * math.cos(w), r * math.sin(w), z0))
            n = np.array([math.cos(w), math.sin(w), r / (z1 - z0)])
            nor.append(tuple(n / np.linalg.norm(n)))
        for k in range(seiten):
            idx.append((spitze, spitze + 1 + k, spitze + 1 + (k + 1) % seiten))
    pos = np.asarray(pos, np.float32)
    return (pos, np.asarray(nor, np.float32), np.zeros((len(pos), 2), np.float32),
            np.asarray(idx, np.uint32))


class Fernwaldzeichner:
    """Alle Kegel in einem Aufruf; die Instanzen liegen fest auf der Karte."""

    def __init__(self, ctx, programm_instanz, wald: Fernwald, farbe) -> None:
        from .deko import instanzmatrizen
        self.programm = programm_instanz
        self.farbe = tuple(float(c) for c in farbe)
        self.anzahl = len(wald.pos)
        pos, nor, uv, idx = baumkegel()
        mat = instanzmatrizen(wald.pos.astype(np.float32), wald.gier.astype(np.float32),
                              wald.skala.astype(np.float32))
        self.puffer = [ctx.buffer(pos.tobytes()), ctx.buffer(nor.tobytes()), ctx.buffer(uv.tobytes()),
                       ctx.buffer(idx.tobytes()), ctx.buffer(np.ascontiguousarray(mat).tobytes())]
        self.vao = ctx.vertex_array(programm_instanz, [
            (self.puffer[0], "3f", "in_position"), (self.puffer[1], "3f", "in_normale"),
            (self.puffer[2], "2f", "in_uv"),
            (self.puffer[4], "4f 4f 4f 4f/i", "in_inst0", "in_inst1", "in_inst2", "in_inst3")],
            self.puffer[3])

    def zeichnen(self) -> None:
        if self.anzahl == 0:
            return
        p = self.programm
        shader.setzen(p, "hat_basisfarbe", 0.0)
        shader.setzen(p, "hat_metallic_rauheit", 0.0)
        shader.setzen(p, "grundton", self.farbe)
        shader.setzen(p, "metallic_faktor", 0.0)
        shader.setzen(p, "rauheit_faktor", 0.9)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        shader.setzen(p, "alpha_faktor", 1.0)
        shader.setzen(p, "alpha_schwelle", 0.0)
        shader.setzen(p, "klarlack", 0.0)
        shader.setzen(p, "nebel_faktor", 1.0)
        self.vao.render(instances=self.anzahl)

    def freigeben(self) -> None:
        for ding in [self.vao, *self.puffer]:
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
