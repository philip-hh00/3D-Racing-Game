"""Wohin Bäume, Felsen, Häuser, Banden und Berge um eine Strecke kommen.

Reine Rechnung mit numpy — kein OpenGL, ohne Fenster prüfbar. Ergebnis ist
eine Liste von :class:`Platzierung`; gezeichnet wird sie von
:mod:`src.render3d.deko`.

**Zufällig, aber fest je Strecke.** Der Zufallsgenerator bekommt einen Keim
aus dem Streckennamen. Dieselbe Strecke sieht bei jedem Rennen gleich aus —
man erkennt sie wieder, und ein Ghost fährt an denselben Bäumen vorbei wie
beim Aufzeichnen.

**Nichts steht auf der Strecke.** Gemessen wird der Abstand zur
*Fahrbahnkante* (Mittellinie minus halbe Breite), und zwar zur ganzen
Mittellinie, nicht nur zum nächstgelegenen Abschnitt: wo zwei Streckenteile
nah beieinander liegen, bleibt der Streifen dazwischen frei.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

from .thema import Dekoart, Kulisse, Randart, Thema

#: Kurvenradius, unter dem ``"kurven"``-Objekte (Reifenstapel) gesetzt werden.
ENGE_KURVE_M = 45.0


@dataclass
class Platzierung:
    modell: str
    x: float
    y: float
    gier_rad: float
    skala: float
    z: float = 0.0


def _modell(name: str, rng) -> str:
    """``"a|b|c"`` ist eine Auswahl: je Exemplar eines davon."""
    teile = name.split("|")
    return teile[int(rng.integers(len(teile)))] if len(teile) > 1 else name


def keim(name: str) -> int:
    return zlib.crc32(str(name).encode("utf-8")) & 0x7FFFFFFF


# ---------------------------------------------------------------------------
# Geometrie der Mittellinie
# ---------------------------------------------------------------------------

def abstand_zur_linie(punkte: np.ndarray, linie: np.ndarray,
                      block: int = 4096) -> np.ndarray:
    """Kürzester Abstand jedes Punkts zu einem geschlossenen Linienzug."""
    punkte = np.asarray(punkte, dtype=np.float64).reshape(-1, 2)
    a = np.asarray(linie, dtype=np.float64)
    b = np.roll(a, -1, axis=0)
    ab = b - a
    laenge2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
    ergebnis = np.empty(len(punkte))
    for s in range(0, len(punkte), block):
        p = punkte[s:s + block, None, :]
        t = np.clip(((p - a) * ab).sum(axis=2) / laenge2, 0.0, 1.0)
        naechster = a + t[..., None] * ab
        ergebnis[s:s + block] = np.sqrt(((p - naechster) ** 2).sum(axis=2)).min(axis=1)
    return ergebnis


def innerhalb(punkte: np.ndarray, polygon: np.ndarray) -> np.ndarray:
    """Liegt ein Punkt im Innenfeld des geschlossenen Linienzugs?"""
    punkte = np.asarray(punkte, dtype=np.float64).reshape(-1, 2)
    poly = np.asarray(polygon, dtype=np.float64)
    x, y = punkte[:, 0:1], punkte[:, 1:2]
    x1, y1 = poly[:, 0], poly[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    kreuzt = ((y1 <= y) & (y < y2)) | ((y2 <= y) & (y < y1))
    with np.errstate(divide="ignore", invalid="ignore"):
        xs = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
    return (kreuzt & (x < xs)).sum(axis=1) % 2 == 1


def _tangenten(linie: np.ndarray) -> np.ndarray:
    vor = np.roll(linie, -1, axis=0) - np.roll(linie, 1, axis=0)
    return vor / np.maximum(np.linalg.norm(vor, axis=1, keepdims=True), 1e-9)


def _kruemmungsradius(linie: np.ndarray, fenster: int = 3) -> np.ndarray:
    """Kurvenradius je Punkt aus der Richtungsänderung über ein kleines Fenster."""
    t = _tangenten(linie)
    winkel = np.arctan2(t[:, 1], t[:, 0])
    dw = np.angle(np.exp(1j * (np.roll(winkel, -fenster) - np.roll(winkel, fenster))))
    weg = np.linalg.norm(np.roll(linie, -fenster, axis=0) - np.roll(linie, fenster, axis=0), axis=1)
    with np.errstate(divide="ignore"):
        return np.where(np.abs(dw) > 1e-6, weg / np.abs(dw), np.inf)


# ---------------------------------------------------------------------------
# Belegung
# ---------------------------------------------------------------------------

class _Belegung:
    """Welche Kreise schon stehen — ein Raster, damit Nachbarn schnell gefunden sind."""

    def __init__(self, zelle_m: float = 8.0) -> None:
        self.zelle = zelle_m
        self.raster: dict[tuple[int, int], list[tuple[float, float, float]]] = {}

    def frei(self, x: float, y: float, r: float) -> bool:
        cx, cy = int(math.floor(x / self.zelle)), int(math.floor(y / self.zelle))
        reichweite = int(math.ceil((r + 12.0) / self.zelle))
        for i in range(cx - reichweite, cx + reichweite + 1):
            for j in range(cy - reichweite, cy + reichweite + 1):
                for (ox, oy, orad) in self.raster.get((i, j), ()):
                    if (x - ox) ** 2 + (y - oy) ** 2 < (r + orad) ** 2:
                        return False
        return True

    def belegen(self, x: float, y: float, r: float) -> None:
        schluessel = (int(math.floor(x / self.zelle)), int(math.floor(y / self.zelle)))
        self.raster.setdefault(schluessel, []).append((x, y, r))


def _ausrichtung_zur_strecke(richtung_zur_strecke: np.ndarray) -> float:
    """Gierwinkel, bei dem die lokale +Y-Achse eines Objekts zur Strecke zeigt."""
    zx, zy = richtung_zur_strecke
    return math.atan2(-zx, zy)


def rand_setzen(art: Randart, linie: np.ndarray, halbbreite: float,
                belegung: _Belegung, rng, start_index: int = 0) -> list[Platzierung]:
    ergebnis = []
    t = _tangenten(linie)
    links = np.stack([-t[:, 1], t[:, 0]], axis=1)
    seg = np.linalg.norm(np.roll(linie, -1, axis=0) - linie, axis=1)
    bogen = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
    gesamt = float(seg.sum())
    abstand = halbbreite + art.abstand_m

    # Welche Seite ist außen? Ein Schritt nach links — liegt er im Innenfeld?
    probe = linie + links * (halbbreite + 1.0)
    links_innen = innerhalb(probe, linie)

    if art.art == "start":
        indizes = [start_index % len(linie)]
    elif art.art == "kurven":
        radius = _kruemmungsradius(linie)
        indizes = []
        letzter = -1e9
        for i in np.argsort(bogen):
            if radius[i] < ENGE_KURVE_M and bogen[i] - letzter >= art.je_m:
                indizes.append(int(i))
                letzter = bogen[i]
    else:
        schritte = np.arange(rng.uniform(0, art.je_m), gesamt, art.je_m)
        indizes = [int(np.searchsorted(bogen, s, side="right") - 1) for s in schritte]

    for i in indizes:
        for seite in ("aussen", "innen"):
            if art.seite not in (seite, "beide"):
                continue
            if art.art == "kurven" and seite == "innen":
                continue
            nach_links = links_innen[i] == (seite == "innen")
            n = links[i] if nach_links else -links[i]
            pos = linie[i] + n * abstand
            # In engen Kurven läge der Punkt innen womöglich auf der Strecke.
            if abstand_zur_linie(pos[None], linie)[0] < abstand - 0.5:
                continue
            r = art.radius_m * art.skala
            if not belegung.frei(pos[0], pos[1], r):
                continue
            belegung.belegen(pos[0], pos[1], r)
            gier = _ausrichtung_zur_strecke(-n) + math.radians(art.drehung_grad)
            ergebnis.append(Platzierung(_modell(art.modell, rng), float(pos[0]), float(pos[1]),
                                        gier, art.skala))
    return ergebnis


def deko_setzen(art: Dekoart, linie: np.ndarray, halbbreite: float,
                belegung: _Belegung, rng) -> list[Platzierung]:
    rand = art.abstand_m[1] + halbbreite
    lo = linie.min(axis=0) - rand
    hi = linie.max(axis=0) + rand
    flaeche_ha = float(np.prod(hi - lo)) / 10_000.0
    kandidaten = max(64, int(flaeche_ha * art.dichte_je_ha * 3.0))
    p = rng.uniform(lo, hi, size=(kandidaten, 2))
    kante = abstand_zur_linie(p, linie) - halbbreite
    ok = (kante >= art.abstand_m[0]) & (kante <= art.abstand_m[1])
    if art.seite != "beide":
        innen = innerhalb(p, linie)
        ok &= innen if art.seite == "innen" else ~innen
    anteil = ok.mean() if len(ok) else 0.0
    ziel = int(round(flaeche_ha * anteil * art.dichte_je_ha))
    ergebnis = []
    for (x, y) in p[ok]:
        if len(ergebnis) >= ziel:
            break
        s = float(rng.uniform(*art.skala))
        r = art.radius_m * s
        if not belegung.frei(x, y, r):
            continue
        belegung.belegen(x, y, r)
        if art.drehen:
            gier = float(rng.uniform(0, 2 * math.pi))
        else:
            i = int(np.argmin(((linie - (x, y)) ** 2).sum(axis=1)))
            gier = _ausrichtung_zur_strecke(linie[i] - (x, y))
        ergebnis.append(Platzierung(_modell(art.modell, rng), float(x), float(y), gier, s))
    return ergebnis


def kulisse_setzen(art: Kulisse, linie: np.ndarray, rng) -> list[Platzierung]:
    mitte = (linie.min(axis=0) + linie.max(axis=0)) / 2
    ausdehnung = float(np.linalg.norm(linie.max(axis=0) - linie.min(axis=0))) / 2
    ergebnis = []
    for k in range(art.anzahl):
        w = 2 * math.pi * (k + rng.uniform(-0.3, 0.3)) / art.anzahl
        r = ausdehnung + float(rng.uniform(*art.radius_m))
        x, y = mitte + r * np.array([math.cos(w), math.sin(w)])
        # Die lange Seite zur Strecke — ein Bergrücken, keine Bergspitze von vorn.
        gier = w + math.pi / 2 + float(rng.uniform(-0.3, 0.3))
        ergebnis.append(Platzierung(_modell(art.modell, rng), float(x), float(y), gier,
                                    float(rng.uniform(*art.skala))))
    return ergebnis


#: Das Portal über der Start-/Ziellinie. Steht auf jeder Strecke, egal welches
#: Thema — die Linie ist Teil des Rennens, nicht der Landschaft.
STARTBRUECKE = "gemeinsam/startbruecke"


def startbruecke(linie: np.ndarray, halbbreite: float, belegung: _Belegung) -> Platzierung:
    """Über Punkt 0 der Mittellinie, quer zur Fahrtrichtung.

    Punkt 0 ist die Ziellinie des Spiels (Wegpunkt 0, siehe
    ``track_builder.build_waypoints``). Das Modell spannt entlang seiner lokalen
    X-Achse; gedreht wird so, dass diese nach links über die Fahrbahn zeigt.
    """
    t = _tangenten(linie)[0]
    links = np.array([-t[1], t[0]])
    for seite in (1, -1):
        stuetze = linie[0] + seite * links * (halbbreite + 2.5)
        belegung.belegen(float(stuetze[0]), float(stuetze[1]), 3.0)
    return Platzierung(STARTBRUECKE, float(linie[0, 0]), float(linie[0, 1]),
                       math.atan2(links[1], links[0]), 1.0)


def platzieren(mittellinie_m: np.ndarray, halbbreite_m: float, thema: Thema,
               name: str, start_index: int = 0) -> list[Platzierung]:
    """Alles, was um diese Strecke herum steht."""
    linie = np.asarray(mittellinie_m, dtype=np.float64)[:, :2]
    rng = np.random.default_rng(keim(name))
    belegung = _Belegung()
    ergebnis: list[Platzierung] = [startbruecke(linie, halbbreite_m, belegung)]
    for art in thema.rand:
        ergebnis += rand_setzen(art, linie, halbbreite_m, belegung, rng, start_index)
    for art in sorted(thema.deko, key=lambda a: -a.radius_m):
        ergebnis += deko_setzen(art, linie, halbbreite_m, belegung, rng)
    for art in thema.kulisse:
        ergebnis += kulisse_setzen(art, linie, rng)
    return ergebnis
