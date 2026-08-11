"""Streckennetz: baut aus einer 2D-Rennstrecke ein 3D-Dreiecksnetz.

Nimmt die JSON-Streckendaten aus ``data/tracks/*.json`` (siehe
``src/track/track.py`` fuer den toleranten Leser dieses Spiels) und erzeugt
daraus Baender aus Dreiecken: Fahrbahn, zwei Randsteine und einen
Untergrund. Alle Ausgaben folgen den Vereinbarungen in
``src/render3d/VEREINBARUNGEN.md``: Rechtshaendiges Koordinatensystem in
Metern, +X vorne, +Y links, +Z oben.

Die Streckendaten selbst liegen in Pixeln; ``M_PER_PX`` rechnet sie um
(12,5 px = 1 m, siehe ``src/core/settings.py``).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: Pixel-nach-Meter-Umrechnung. Muss zu src/core/settings.py::M_PER_PX passen;
#: hier fest verdrahtet, weil render3d laut VEREINBARUNGEN.md keine
#: Spiellogik-Module importieren darf.
M_PER_PX: float = 0.08

#: Wie weit der Untergrund unter z = 0 liegt. 1 cm ist im Vergleich zur
#: float32-Rundung bei den hier ueblichen Koordinaten (Groessenordnung
#: einige hundert bis tausend Meter, also eine absolute Praezision von
#: rund 1e-4 m) um zwei Groessenordnungen groesser -- ausreichend gegen
#: Z-Fighting mit der Fahrbahn bei z = 0, aber optisch nicht wahrnehmbar.
UNTERGRUND_VERSATZ_M: float = -0.01

#: Ab welchem Abstand zwei aufeinanderfolgende Punkte als "derselbe Punkt"
#: gelten und der zweite verworfen wird. Verhindert entartete Dreiecke,
#: wenn eine Streckendatei die Mittellinie versehentlich mit einem
#: doppelten Schlusspunkt speichert.
_DOPPELPUNKT_EPS_M: float = 1e-6


@dataclass
class Band:
    """Ein zusammenhaengendes Stueck Streckennetz (z.B. die Fahrbahn)."""

    name: str
    positionen: np.ndarray    # (n, 3) float32, Meter
    normalen: np.ndarray      # (n, 3) float32
    uv: np.ndarray            # (n, 2) float32
    indizes: np.ndarray       # (m, 3) uint32


@dataclass
class Streckennetz:
    """Das vollstaendige 3D-Netz einer Rennstrecke."""

    baender: list[Band]
    laenge_m: float
    start_positionen: list[tuple[float, float, float]]  # x_m, y_m, gierwinkel_rad

    def band(self, name: str) -> Band | None:
        for b in self.baender:
            if b.name == name:
                return b
        return None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _punkte_lesen(werte: Any) -> list[tuple[float, float]]:
    """{x, y}-Objekte aus der Strecken-JSON als Liste von Tupeln (Pixel)."""
    out: list[tuple[float, float]] = []
    if not isinstance(werte, list):
        return out
    for p in werte:
        if not isinstance(p, dict):
            continue
        try:
            out.append((float(p["x"]), float(p["y"])))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _ohne_folgeduplikate(punkte: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Entfernt aufeinanderfolgende (auch ueber die Naht hinweg) Duplikate.

    Eine Streckendatei kann den Schlusspunkt versehentlich gleich dem
    Startpunkt speichern. Ohne diese Bereinigung waere der Abstand zwischen
    zwei "Ringen" dort Null und das daraus gebaute Dreieck entartet.
    """
    if len(punkte) < 2:
        return list(punkte)
    bereinigt = [punkte[0]]
    for p in punkte[1:]:
        letzter = bereinigt[-1]
        if math.hypot(p[0] - letzter[0], p[1] - letzter[1]) > _DOPPELPUNKT_EPS_M:
            bereinigt.append(p)
    # Naht pruefen: verbindet der letzte Punkt zurueck zum ersten mit
    # (fast) Abstand Null, ist er redundant, weil die Schleife ohnehin
    # geschlossen gerechnet wird.
    if len(bereinigt) > 2:
        erster, letzter = bereinigt[0], bereinigt[-1]
        if math.hypot(erster[0] - letzter[0], erster[1] - letzter[1]) <= _DOPPELPUNKT_EPS_M:
            bereinigt.pop()
    return bereinigt


def _tangenten_und_links(mittellinie_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Tangenten- und Linksrichtung je Punkt einer geschlossenen Schleife.

    Die Tangente an Punkt i folgt aus dem zentralen Differenzenquotienten
    (Punkt i+1 minus Punkt i-1, Index modulo n). Fuer einen exakt
    abgetasteten Kreis liefert das wegen der Symmetrie von Sinus/Kosinus
    die exakte tangentiale Richtung (nicht nur eine Naeherung) -- wichtig
    fuer die Flaechen- und Breitentests.

    "Links" ergibt sich aus hoch x vorwaerts (rechtes-Hand-System, +Z oben):
    links = (0,0,1) x tangente.
    """
    n = len(mittellinie_m)
    vorher = np.roll(mittellinie_m, 1, axis=0)
    nachher = np.roll(mittellinie_m, -1, axis=0)
    richtung = nachher - vorher
    laenge = np.linalg.norm(richtung, axis=1, keepdims=True)
    laenge[laenge < 1e-12] = 1.0
    tangenten = richtung / laenge

    links = np.zeros((n, 2), dtype=np.float64)
    links[:, 0] = -tangenten[:, 1]
    links[:, 1] = tangenten[:, 0]
    return tangenten, links


def _bogenlaengen(mittellinie_m: np.ndarray) -> np.ndarray:
    """Kumulierte Bogenlaenge je Punkt einer geschlossenen Schleife (Meter).

    Punkt 0 bekommt 0.0; jeder weitere Punkt die Distanz zum Vorgaenger
    aufsummiert (die schliessende Strecke zurueck zu Punkt 0 zaehlt nicht
    mehr mit, da sie zu keinem Punkt der Liste mehr gehoert).
    """
    diffs = mittellinie_m[1:] - mittellinie_m[:-1]
    segment_laengen = np.linalg.norm(diffs, axis=1)
    kumuliert = np.concatenate([[0.0], np.cumsum(segment_laengen)])
    return kumuliert


def _gesamtumfang(mittellinie_m: np.ndarray) -> float:
    """Laenge der vollstaendig geschlossenen Mittellinie (Meter)."""
    diffs = mittellinie_m - np.roll(mittellinie_m, -1, axis=0)
    return float(np.sum(np.linalg.norm(diffs, axis=1)))


def _band_aus_ringen(name: str, ring_a_m: np.ndarray, ring_b_m: np.ndarray,
                      u_a: np.ndarray | float, u_b: np.ndarray | float,
                      v_werte: np.ndarray) -> Band:
    """Baut ein geschlossenes Streifenband aus zwei parallelen Punktringen.

    Ring a und Ring b muessen gleich lang sein und in derselben Reihenfolge
    um die Schleife laufen. Die Dreiecksreihenfolge ist so gewaehlt, dass
    die Normale (0, 0, 1) ergibt, wenn Ring a -- vom Bewegungssinn aus
    gesehen -- weiter links liegt als Ring b (siehe Herleitung in den
    Aufrufern).
    """
    n = len(ring_a_m)
    positionen = np.zeros((2 * n, 3), dtype=np.float32)
    positionen[0::2, 0:2] = ring_a_m
    positionen[1::2, 0:2] = ring_b_m

    normalen = np.zeros((2 * n, 3), dtype=np.float32)
    normalen[:, 2] = 1.0

    uv = np.zeros((2 * n, 2), dtype=np.float32)
    uv[0::2, 0] = u_a
    uv[1::2, 0] = u_b
    uv[0::2, 1] = v_werte
    uv[1::2, 1] = v_werte

    indizes = np.empty((2 * n, 3), dtype=np.uint32)
    i = np.arange(n, dtype=np.uint32)
    j = (i + 1) % n
    a, b, c, d = 2 * i, 2 * i + 1, 2 * j, 2 * j + 1
    indizes[0::2, 0] = a
    indizes[0::2, 1] = b
    indizes[0::2, 2] = c
    indizes[1::2, 0] = b
    indizes[1::2, 1] = d
    indizes[1::2, 2] = c

    return Band(name=name, positionen=positionen, normalen=normalen,
                uv=uv, indizes=indizes)


def _rechteck_band(name: str, min_xy_m: np.ndarray, max_xy_m: np.ndarray,
                    z_m: float, kachellaenge_m: float) -> Band:
    """Eine einzelne rechteckige Ebene (z.B. der Untergrund)."""
    positionen = np.array([
        [min_xy_m[0], min_xy_m[1], z_m],
        [max_xy_m[0], min_xy_m[1], z_m],
        [max_xy_m[0], max_xy_m[1], z_m],
        [min_xy_m[0], max_xy_m[1], z_m],
    ], dtype=np.float32)
    normalen = np.zeros((4, 3), dtype=np.float32)
    normalen[:, 2] = 1.0

    breite_m = float(max_xy_m[0] - min_xy_m[0])
    tiefe_m = float(max_xy_m[1] - min_xy_m[1])
    kachel_u = breite_m / kachellaenge_m
    kachel_v = tiefe_m / kachellaenge_m
    uv = np.array([
        [0.0, 0.0],
        [kachel_u, 0.0],
        [kachel_u, kachel_v],
        [0.0, kachel_v],
    ], dtype=np.float32)

    indizes = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32)
    return Band(name=name, positionen=positionen, normalen=normalen,
                uv=uv, indizes=indizes)


# ---------------------------------------------------------------------------
# Aufbau
# ---------------------------------------------------------------------------


def bauen(strecke: dict, randstein_m: float = 1.0,
          untergrund_rand_m: float = 200.0,
          kachellaenge_m: float = 8.0) -> Streckennetz:
    """Baut ein :class:`Streckennetz` aus geladenen Streckendaten (dict).

    Args:
        strecke: Geparste Streckendaten wie in ``data/tracks/*.json``
            (mindestens ``centerline`` und ``track_width``).
        randstein_m: Breite der Randstein-Baender in Metern.
        untergrund_rand_m: Wie weit der Untergrund ueber die Strecke
            (Mittellinie und Randsteine) hinausreicht, in Metern.
        kachellaenge_m: Nach wie vielen Metern sich die Fahrbahntextur
            entlang der Strecke wiederholt (v-Koordinate).
    """
    rohe_mittellinie_px = _punkte_lesen(strecke.get("centerline"))
    if len(rohe_mittellinie_px) < 3:
        raise ValueError("Strecke hat keine brauchbare Mittellinie (weniger als 3 Punkte)")
    mittellinie_px = _ohne_folgeduplikate(rohe_mittellinie_px)
    if len(mittellinie_px) < 3:
        raise ValueError("Mittellinie nach Entfernen von Duplikaten zu kurz")

    mittellinie_m = np.asarray(mittellinie_px, dtype=np.float64) * M_PER_PX

    breite_m = float(strecke.get("track_width", 100.0)) * M_PER_PX
    halbe_breite_m = breite_m / 2.0

    _tangenten, links = _tangenten_und_links(mittellinie_m)

    punkte_links = mittellinie_m + links * halbe_breite_m
    punkte_rechts = mittellinie_m - links * halbe_breite_m

    bogenlaengen_m = _bogenlaengen(mittellinie_m)
    v_werte = bogenlaengen_m / kachellaenge_m

    baender = [
        _band_aus_ringen("fahrbahn", punkte_links, punkte_rechts, 0.0, 1.0, v_werte),
        _band_aus_ringen(
            "randstein_links",
            punkte_links + links * randstein_m, punkte_links,
            1.0, 0.0, v_werte),
        _band_aus_ringen(
            "randstein_rechts",
            punkte_rechts, punkte_rechts - links * randstein_m,
            0.0, 1.0, v_werte),
    ]

    # Untergrund: Bounding-Box ueber Mittellinie und Randsteine, damit die
    # Ebene die ganze sichtbare Strecke sicher umschliesst, plus Rand.
    alle_punkte_m = np.concatenate([
        mittellinie_m,
        punkte_links + links * randstein_m,
        punkte_rechts - links * randstein_m,
    ])
    min_xy = alle_punkte_m.min(axis=0) - untergrund_rand_m
    max_xy = alle_punkte_m.max(axis=0) + untergrund_rand_m
    baender.append(_rechteck_band(
        "untergrund", min_xy, max_xy, UNTERGRUND_VERSATZ_M, kachellaenge_m))

    laenge_m = _gesamtumfang(mittellinie_m)

    start_positionen: list[tuple[float, float, float]] = []
    for s in strecke.get("start_positions", []) or []:
        if not isinstance(s, dict):
            continue
        try:
            x_px = float(s["x"])
            y_px = float(s["y"])
            winkel_grad = float(s.get("angle", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        start_positionen.append(
            (x_px * M_PER_PX, y_px * M_PER_PX, math.radians(winkel_grad)))

    return Streckennetz(baender=baender, laenge_m=laenge_m,
                         start_positionen=start_positionen)


def aus_datei(pfad: str | Path, randstein_m: float = 1.0,
              untergrund_rand_m: float = 200.0,
              kachellaenge_m: float = 8.0) -> Streckennetz:
    """Laedt eine Strecken-JSON-Datei und baut daraus ein :class:`Streckennetz`."""
    pfad = Path(pfad)
    with open(pfad, "r", encoding="utf-8") as datei:
        strecke = json.load(datei)
    return bauen(strecke, randstein_m=randstein_m,
                 untergrund_rand_m=untergrund_rand_m,
                 kachellaenge_m=kachellaenge_m)
