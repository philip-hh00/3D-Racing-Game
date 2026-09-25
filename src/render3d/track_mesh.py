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
from dataclasses import dataclass, field
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

#: Randsteine: Höhe am Scheitel ihres flach gewölbten Profils. Echte
#: Kurbs sind drei bis fünf Zentimeter hoch; die Physik merkt davon nichts.
RANDSTEIN_HOEHE_M: float = 0.035

#: Querprofil eines Randsteins: (Anteil der Breite von der Fahrbahnkante nach
#: innen, Anteil von ``RANDSTEIN_HOEHE_M``). Der erste Abschnitt ist die
#: senkrechte Außenseite an der Kante, der Rest die gewölbte Oberseite. Die
#: Innenkante taucht **unter** die Fahrbahn und steigt steil an: so schneiden
#: sich Stein und Fahrbahn in einer Linie statt in einer Fläche — kein
#: Z-Fighting, keine Lücke.
RANDSTEIN_PROFIL: tuple = ((0.0, -0.6), (0.0, 0.35), (0.07, 0.72), (0.3, 0.97),
                           (0.55, 1.0), (0.8, 0.74), (0.94, 0.3), (1.0, -0.25))

#: Kurven, deren Radius darunter liegt, bekommen innen Randsteine …
RANDSTEIN_INNEN_R_M: float = 95.0
#: … und am Kurvenausgang außen, wenn sie noch enger sind.
RANDSTEIN_AUSSEN_R_M: float = 60.0

#: Auslaufzonen außen an Kurven mit kleinerem Radius als diesem.
AUSLAUF_R_M: float = 140.0
#: Höhe der Auslauffläche über z = 0. Deutlich über dem Boden, damit Kies und
#: Gelände auch in 300 m Entfernung nicht um dieselbe Tiefe streiten.
AUSLAUF_HOEHE_M: float = 0.04

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
    #: Die Mittellinie in Metern, (n, 2). Nicht nur fuer das Netz gebraucht:
    #: Kamera, Gegnerlogik und alles, was "wo auf der Strecke" beantworten
    #: muss, braucht sie ebenfalls. Ohne sie muesste der Aufrufer sie aus den
    #: Dreiecken zurueckrechnen - und wuesste dabei mehr ueber den inneren
    #: Aufbau der Baender, als ihm guttut.
    mittellinie: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2), dtype=np.float64))
    #: Fahrtrichtung je Punkt der Mittellinie, (n, 2), auf Laenge 1.
    #: Getrennt gefuehrt, weil sie **zwischen** den Punkten weiterlaufen muss:
    #: die Richtung eines Streckenabschnitts allein ist innerhalb des
    #: Abschnitts konstant und springt an jeder Punktgrenze. Bei 1,6 m
    #: Punktabstand und 25 m/s waeren das 15 Spruenge je Sekunde - sichtbar
    #: als ruckartiges Einlenken, obwohl die Position sauber laeuft.
    tangenten: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2), dtype=np.float64))
    halbe_breite_m: float = 0.0
    #: Fahrbahnkanten, (n, 2) — dort stehen die Wände des Spiels.
    rand_links: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    rand_rechts: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    #: Linksrichtung je Punkt, (n, 2), auf Länge 1.
    links: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))
    name: str = ""
    thema: str = ""
    #: Bogenlänge je Punkt der Mittellinie, Meter (Punkt 0 hat 0).
    bogen_m: np.ndarray = field(default_factory=lambda: np.zeros(0))
    #: Krümmung je Punkt, 1/m, positiv in Linkskurven.
    kruemmung: np.ndarray = field(default_factory=lambda: np.zeros(0))
    #: Querversatz der Ideallinie zur Mittellinie je Punkt, Meter, nach links
    #: positiv. Nur fürs Auge (Gummiabrieb) — die KI rechnet ihre eigene.
    ideal_versatz_m: np.ndarray = field(default_factory=lambda: np.zeros(0))

    def band(self, name: str) -> Band | None:
        for b in self.baender:
            if b.name == name:
                return b
        return None

    def punkt_bei(self, strecke_m: float) -> tuple[np.ndarray, float]:
        """Position und Fahrtrichtung nach *strecke_m* Metern ab dem Anfang.

        Laeuft ueber das Ende hinaus wieder von vorne los - die Strecke ist
        geschlossen. Liefert ``((x_m, y_m), gierwinkel_rad)``; der Gierwinkel
        ist im selben Sinn gemessen wie ``body.angle`` im Spiel, 0 zeigt
        nach +X.

        Die Richtung wird zwischen den Tangenten der beiden Nachbarpunkte
        interpoliert, nicht aus dem Abschnitt selbst genommen. Die Richtung
        eines Abschnitts ist innerhalb des Abschnitts konstant und springt an
        jeder Punktgrenze - bei 1,6 m Punktabstand und 25 m/s fuenfzehnmal je
        Sekunde, und das sieht man dem Fahrzeug an.
        """
        punkte = np.asarray(self.mittellinie, dtype=np.float64)
        if len(punkte) < 2:
            raise ValueError("Streckennetz hat keine Mittellinie")

        geschlossen = np.vstack([punkte, punkte[:1]])
        laengen = np.linalg.norm(np.diff(geschlossen, axis=0), axis=1)
        summe = np.concatenate([[0.0], np.cumsum(laengen)])
        gesamt = float(summe[-1])

        s = float(strecke_m) % gesamt if gesamt > 0 else 0.0
        i = int(np.searchsorted(summe, s, side="right") - 1)
        i = min(max(i, 0), len(laengen) - 1)

        rest = (s - summe[i]) / laengen[i] if laengen[i] > 0 else 0.0
        a, b = geschlossen[i], geschlossen[i + 1]
        pos = a + (b - a) * rest

        richtung = self._richtung_bei(i, rest, b - a)
        return pos, float(math.atan2(richtung[1], richtung[0]))

    def _richtung_bei(self, i: int, rest: float, rueckfall: np.ndarray) -> np.ndarray:
        """Fahrtrichtung innerhalb eines Abschnitts, stetig ueber die Grenze.

        Ohne hinterlegte Tangenten bleibt nur die Richtung des Abschnitts
        selbst — das ist die Sprungvariante, aber besser als gar keine Antwort.
        """
        tangenten = np.asarray(self.tangenten, dtype=np.float64)
        if len(tangenten) != len(self.mittellinie) or len(tangenten) == 0:
            return rueckfall
        a = tangenten[i % len(tangenten)]
        b = tangenten[(i + 1) % len(tangenten)]
        gemischt = a + (b - a) * rest
        laenge = float(np.linalg.norm(gemischt))
        # Bei einer Kehrtwende koennen sich zwei Tangenten aufheben. Dann ist
        # die Mischung nicht aussagekraeftig und der Abschnitt selbst besser.
        return gemischt / laenge if laenge > 1e-9 else rueckfall


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
                      v_werte: np.ndarray, v_naht: float | None = None) -> Band:
    """Baut ein geschlossenes Streifenband aus zwei parallelen Punktringen.

    Ring a und Ring b muessen gleich lang sein und in derselben Reihenfolge
    um die Schleife laufen. Die Dreiecksreihenfolge ist so gewaehlt, dass
    die Normale (0, 0, 1) ergibt, wenn Ring a -- vom Bewegungssinn aus
    gesehen -- weiter links liegt als Ring b (siehe Herleitung in den
    Aufrufern).

    ``v_naht``: Schliesst die Schleife mit einer **Kopie** des ersten Rings,
    die dieses v bekommt (die Gesamtlaenge). Ohne sie liefe v im letzten
    Abschnitt von der vollen Laenge auf 0 zurueck, und jede Textur entlang
    der Strecke wuerde dort auf 1,6 m zusammengestaucht.
    """
    if v_naht is not None:
        ring_a_m = np.vstack([ring_a_m, ring_a_m[:1]])
        ring_b_m = np.vstack([ring_b_m, ring_b_m[:1]])
        v_werte = np.concatenate([v_werte, [v_naht]])
        u_a = np.concatenate([np.broadcast_to(u_a, len(ring_a_m) - 1), [np.ravel(u_a)[0]]]) \
            if np.ndim(u_a) else u_a
        u_b = np.concatenate([np.broadcast_to(u_b, len(ring_b_m) - 1), [np.ravel(u_b)[0]]]) \
            if np.ndim(u_b) else u_b
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

    segmente = n - 1 if v_naht is not None else n
    indizes = np.empty((2 * segmente, 3), dtype=np.uint32)
    i = np.arange(segmente, dtype=np.uint32)
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
# Kurven, Ideallinie
# ---------------------------------------------------------------------------


def kruemmung(mittellinie_m: np.ndarray, fenster: int = 3) -> np.ndarray:
    """Krümmung je Punkt (1/m), positiv in Linkskurven.

    Aus der Richtungsänderung über ``2 * fenster`` Abschnitte — ein einzelner
    Abschnitt von 1,6 m rauscht zu sehr, um daraus Kurven abzulesen.
    """
    linie = np.asarray(mittellinie_m, dtype=np.float64)
    t, _ = _tangenten_und_links(linie)
    winkel = np.arctan2(t[:, 1], t[:, 0])
    dw = np.angle(np.exp(1j * (np.roll(winkel, -fenster) - np.roll(winkel, fenster))))
    weg = np.linalg.norm(np.roll(linie, -fenster, axis=0) - np.roll(linie, fenster, axis=0), axis=1)
    return dw / np.maximum(weg, 1e-6)


def _ring_glaetten(werte: np.ndarray, breite: int) -> np.ndarray:
    """Gleitendes Mittel über ``2 * breite + 1`` Punkte einer geschlossenen Schleife."""
    if breite <= 0:
        return np.asarray(werte, dtype=np.float64)
    kern = np.ones(2 * breite + 1) / (2 * breite + 1)
    erweitert = np.concatenate([werte[-breite:], werte, werte[:breite]])
    return np.convolve(erweitert, kern, mode="valid")


def ideallinie(mittellinie_m: np.ndarray, links: np.ndarray, halbe_breite_m: float,
               rand_m: float = 2.6) -> np.ndarray:
    """Querversatz der Linie geringster Krümmung, je Punkt, nach links positiv.

    Gesucht ist ``p_i = c_i + n_i * o_i`` mit möglichst kleinen zweiten
    Differenzen — das ist die Linie, auf der ein Auto am wenigsten lenkt:
    außen anfahren, innen am Scheitel, außen hinaus. Unter der Randbedingung
    ``|o| <= halbe_breite - rand`` gelöst als kleines lineares
    Ausgleichsproblem mit aktiver Menge (ein paar hundert Unbekannte). Die
    KI des Spiels rechnet ihre Linie selbst; diese hier dient nur dem
    Gummiabrieb auf dem Asphalt.
    """
    alle_c = np.asarray(mittellinie_m, dtype=np.float64)
    alle_n = np.asarray(links, dtype=np.float64)
    gesamt_n = len(alle_c)
    grenze = max(0.3, halbe_breite_m - rand_m)
    if gesamt_n < 5:
        return np.zeros(gesamt_n)
    # Gerechnet wird auf jedem k-ten Punkt (rund alle 4 m): die Linie ist
    # glatt, und das Gleichungssystem wächst mit der dritten Potenz.
    abstand = _gesamtumfang(alle_c) / gesamt_n
    k = max(1, int(round(4.0 / max(abstand, 1e-6))))
    if gesamt_n // k < 12:
        k = 1
    c, nrm = alle_c[::k], alle_n[::k]
    n = len(c)
    eins = np.eye(n)
    lap = np.roll(eins, -1, axis=1) + np.roll(eins, 1, axis=1) - 2.0 * eins
    a = np.vstack([lap * nrm[:, 0][None, :], lap * nrm[:, 1][None, :]])
    b = np.concatenate([lap @ c[:, 0], lap @ c[:, 1]])
    # Ein wenig Zug zur Mitte: auf langen Geraden ist die Lage sonst beliebig.
    lam = 1e-7
    ata = a.T @ a + lam * eins
    atb = a.T @ b
    o = np.zeros(n)
    fest = np.zeros(n, dtype=bool)
    for _ in range(30):
        frei = ~fest
        rechts = -(atb[frei] + ata[np.ix_(frei, fest)] @ o[fest])
        o[frei] = np.linalg.solve(ata[np.ix_(frei, frei)], rechts)
        drueber = frei & (np.abs(o) > grenze)
        if not drueber.any():
            break
        o[drueber] = np.clip(o[drueber], -grenze, grenze)
        fest |= drueber
    o = np.clip(o, -grenze, grenze)
    if k == 1:
        return o
    s_alle = _bogenlaengen(alle_c)
    s_grob = s_alle[::k]
    gesamt = _gesamtumfang(alle_c)
    return np.interp(s_alle, np.concatenate([s_grob, [gesamt]]), np.concatenate([o, o[:1]]))


def _laeufe(maske: np.ndarray) -> list[tuple[int, int]]:
    """Zusammenhängende ``True``-Stücke einer Ringmaske: ``(start, anzahl)``.

    Ein Lauf darf über die Naht (letzter → erster Punkt) gehen. Ist alles
    ``True``, gibt es genau einen Lauf über den ganzen Ring.
    """
    maske = np.asarray(maske, dtype=bool)
    n = len(maske)
    if n == 0 or not maske.any():
        return []
    if maske.all():
        return [(0, n)]
    k = int(np.argmin(maske))                       # ein freier Punkt
    gedreht = np.roll(maske, -k)
    kanten = np.diff(np.concatenate([[0], gedreht.astype(np.int8), [0]]))
    anfaenge = np.flatnonzero(kanten == 1)
    enden = np.flatnonzero(kanten == -1)
    return [(int((a + k) % n), int(e - a)) for a, e in zip(anfaenge, enden)]


def _ring_dehnen(maske: np.ndarray, punkte: int) -> np.ndarray:
    """Jeden ``True``-Punkt um ``punkte`` nach beiden Seiten ausweiten."""
    if punkte <= 0:
        return maske.copy()
    return _ring_glaetten(maske.astype(np.float64), punkte) > 1e-9


def _ring_schrumpfen(maske: np.ndarray, punkte: int) -> np.ndarray:
    return ~_ring_dehnen(~maske, punkte)


def randstein_masken(kr: np.ndarray, punktabstand_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Wo Randsteine liegen: je Seite eine Maske über die Punkte.

    Innen über die ganze Kurve, deren Radius unter ``RANDSTEIN_INNEN_R_M``
    liegt; außen nur am Ausgang der engeren Kurven — dort, wo ein Auto
    hinausgetragen wird. Kurze Lücken werden geschlossen, Stummel verworfen.
    """
    kr = _ring_glaetten(np.asarray(kr, dtype=np.float64), 2)
    n = len(kr)
    schritt = max(punktabstand_m, 1e-3)
    links = kr > 1.0 / RANDSTEIN_INNEN_R_M
    rechts = kr < -1.0 / RANDSTEIN_INNEN_R_M
    for vorzeichen in (1.0, -1.0):
        eng = vorzeichen * kr > 1.0 / RANDSTEIN_AUSSEN_R_M
        for start, anzahl in _laeufe(eng):
            if anzahl >= n:
                (rechts if vorzeichen > 0 else links)[:] = True
                continue
            von = start + anzahl // 2
            bis = start + anzahl + int(round(14.0 / schritt))
            idx = np.arange(von, bis) % n
            # Linkskurve: außen ist rechts.
            (rechts if vorzeichen > 0 else links)[idx] = True
    ergebnis = []
    luecke = int(round(5.0 / schritt))
    rand = int(round(2.5 / schritt))
    for maske in (links, rechts):
        maske = _ring_schrumpfen(_ring_dehnen(maske, luecke), luecke)
        maske = _ring_dehnen(maske, rand)
        for start, anzahl in _laeufe(maske):
            if anzahl * schritt < 9.0 and anzahl < n:
                maske[np.arange(start, start + anzahl) % n] = False
        ergebnis.append(maske)
    return ergebnis[0], ergebnis[1]


# ---------------------------------------------------------------------------
# Randsteine als Körper
# ---------------------------------------------------------------------------


def _profilnormalen(d: np.ndarray, z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Glatte Normalen eines Querprofils je Punkt, (m, k) in (d, z).

    ``d`` zählt von der Kante nach innen. Jeder Abschnitt hat die Normale
    ``(-dz, dd)``, an inneren Punkten wird gemittelt.
    """
    dd = np.diff(d, axis=1)
    dz = np.diff(z, axis=1)
    laenge = np.maximum(np.hypot(dd, dz), 1e-9)
    nd, nz = -dz / laenge, dd / laenge
    pd = np.concatenate([nd[:, :1], nd[:, :-1] + nd[:, 1:], nd[:, -1:]], axis=1)
    pz = np.concatenate([nz[:, :1], nz[:, :-1] + nz[:, 1:], nz[:, -1:]], axis=1)
    laenge = np.maximum(np.hypot(pd, pz), 1e-9)
    return pd / laenge, pz / laenge


def _profilstreifen(kante: np.ndarray, innen: np.ndarray, v: np.ndarray,
                    profil_d: np.ndarray, profil_z: np.ndarray,
                    geschlossen: bool) -> tuple:
    """Ein Querprofil entlang einer Kante: Positionen, Normalen, UV, Indizes.

    ``profil_d``/``profil_z``: (m, k), je Kantenpunkt ein eigenes Profil
    (so lässt sich die Höhe an den Enden auslaufen lassen).
    """
    m, k = profil_d.shape
    nd, nz = _profilnormalen(profil_d, profil_z)
    pos = np.zeros((m, k, 3))
    pos[:, :, :2] = kante[:, None, :] + innen[:, None, :] * profil_d[:, :, None]
    pos[:, :, 2] = profil_z
    nor = np.zeros((m, k, 3))
    nor[:, :, :2] = innen[:, None, :] * nd[:, :, None]
    nor[:, :, 2] = nz
    uv = np.zeros((m, k, 2))
    breite = max(float(profil_d.max()), 1e-6)
    uv[:, :, 0] = profil_d / breite
    uv[:, :, 1] = v[:, None]
    segmente = m if geschlossen else m - 1
    i = np.arange(segmente)[:, None]
    j = np.arange(k - 1)[None, :]
    a = i * k + j
    b = i * k + j + 1
    c = ((i + 1) % m) * k + j + 1
    d = ((i + 1) % m) * k + j
    idx = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3),
                          np.stack([a, c, d], -1).reshape(-1, 3)])
    return pos.reshape(-1, 3), nor.reshape(-1, 3), uv.reshape(-1, 2), idx


def _endkappe(kante: np.ndarray, innen: np.ndarray, richtung: np.ndarray,
              profil_d: np.ndarray, profil_z: np.ndarray) -> tuple:
    """Das offene Ende eines Randsteins zumachen: Profil bis zur Unterkante."""
    unten = float(profil_z.min())
    k = len(profil_d)
    oben = np.zeros((k, 3))
    oben[:, :2] = kante + innen * profil_d[:, None]
    oben[:, 2] = profil_z
    tief = oben.copy()
    tief[:, 2] = unten
    pos = np.vstack([oben, tief])
    nor = np.zeros_like(pos)
    nor[:, :2] = richtung
    uv = np.zeros((2 * k, 2))
    idx = []
    for s in range(k - 1):
        idx += [(s, s + 1, k + s + 1), (s, k + s + 1, k + s)]
    idx = np.asarray(idx, dtype=np.int64).reshape(-1, 3)
    # Wo das Profil die Unterkante berührt, fallen Ecken zusammen: weg damit.
    p = pos[idx]
    flaeche = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    return pos, nor, uv, idx[flaeche > 1e-9]


def randsteine_bauen(name: str, kante: np.ndarray, innen: np.ndarray,
                     bogen_m: np.ndarray, maske: np.ndarray, breite_m: float,
                     tangenten: np.ndarray, gesamt_m: float) -> Band | None:
    """Alle Randsteine einer Seite als ein Band.

    ``kante``: die Fahrbahnkante dieser Seite, ``innen``: Richtung zur
    Fahrbahnmitte. Der Stein liegt **innerhalb** der Fahrbahn — außen an der
    Kante steht die Begrenzung, und dort prallt das Auto ab. An den Enden
    läuft die Höhe auf ein Viertel aus, eine Kappe schließt den Körper.
    """
    profil = np.asarray(RANDSTEIN_PROFIL, dtype=np.float64)
    n = len(kante)
    teile = []
    for start, anzahl in _laeufe(maske):
        geschlossen = anzahl >= n
        idx = (np.arange(start, start + anzahl) % n) if not geschlossen else np.arange(n)
        if len(idx) < 2:
            continue
        v = bogen_m[idx].astype(np.float64)
        # Über die Naht hinweg weiterzählen, sonst springt das Streifenmuster.
        v = v + np.concatenate([[0.0], np.cumsum(np.diff(v) < 0)]) * gesamt_m
        if geschlossen:
            faktor = np.ones(len(idx))
        else:
            weg = v - v[0]
            rest = np.minimum(weg, weg[-1] - weg)
            x = np.clip(rest / 3.0, 0.0, 1.0)
            faktor = 0.25 + 0.75 * x * x * (3 - 2 * x)
        d = np.tile(profil[:, 0] * breite_m, (len(idx), 1))
        z = profil[None, :, 1] * RANDSTEIN_HOEHE_M * faktor[:, None]
        # Außenseite (hart) und Oberseite (glatt) getrennt: an der Kante
        # knickt die Fläche um 90 Grad.
        for von, bis in ((0, 2), (1, len(profil))):
            teile.append(_profilstreifen(kante[idx], innen[idx], v, d[:, von:bis], z[:, von:bis],
                                         geschlossen))
        if not geschlossen:
            for ende, richtung in ((0, -tangenten[idx[0]]), (-1, tangenten[idx[-1]])):
                teile.append(_endkappe(kante[idx[ende]], innen[idx[ende]], richtung,
                                       d[ende], z[ende]))
    if not teile:
        return None
    pos, nor, uv, ind = [], [], [], []
    basis = 0
    for p, nn, u, i in teile:
        if len(i) == 0:
            continue
        pos.append(p)
        nor.append(nn)
        uv.append(u)
        ind.append(i + basis)
        basis += len(p)
    return Band(name=name, positionen=np.vstack(pos).astype(np.float32),
                normalen=np.vstack(nor).astype(np.float32),
                uv=np.vstack(uv).astype(np.float32),
                indizes=np.vstack(ind).astype(np.uint32))


# ---------------------------------------------------------------------------
# Auslaufzonen
# ---------------------------------------------------------------------------


def auslauf_breiten(mittellinie_m: np.ndarray, halbe_breite_m: float,
                    breite_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Breite der Auslaufzone je Punkt, links und rechts, Meter (0: keine).

    Außen an Kurven unter ``AUSLAUF_R_M``, vom Kurveneingang bis weit hinter
    den Ausgang (dorthin trägt es ein Auto), linsenförmig aus- und
    einlaufend. Wo ein anderes Stück der Strecke nah vorbeiführt, wird die
    Zone schmaler — sie darf nie bis an die Nachbarfahrbahn reichen.
    """
    linie = np.asarray(mittellinie_m, dtype=np.float64)
    n = len(linie)
    if n < 5 or breite_m <= 0:
        return np.zeros(n), np.zeros(n)
    t, links = _tangenten_und_links(linie)
    seg = np.linalg.norm(np.roll(linie, -1, axis=0) - linie, axis=1)
    schritt = float(seg.mean()) if n else 1.0
    kr = _ring_glaetten(kruemmung(linie), 2)
    ergebnis = []
    for seite in (1.0, -1.0):                       # links, rechts
        # Außen links liegt in einer Rechtskurve.
        kurve = -seite * kr > 1.0 / AUSLAUF_R_M
        ziel = np.zeros(n)
        for start, anzahl in _laeufe(kurve):
            vor = int(round(6.0 / schritt))
            nach = int(round(28.0 / schritt))
            gesamt = min(anzahl + vor + nach, n)
            idx = np.arange(start - vor, start - vor + gesamt) % n
            s = np.arange(gesamt) * schritt
            rest = np.minimum(s, s[-1] - s)
            x = np.clip(rest / 18.0, 0.0, 1.0)
            ziel[idx] = np.maximum(ziel[idx], breite_m * (x * x * (3 - 2 * x)))
        # Platz bis zur Nachbarstrecke: schrittweise nach außen tasten.
        frei = ziel.copy()
        kandidaten = np.flatnonzero(ziel > 0)
        if len(kandidaten):
            kante = linie[kandidaten] + seite * links[kandidaten] * halbe_breite_m
            aussen = seite * links[kandidaten]
            for e in np.arange(1.0, breite_m + 3.01, 1.0):
                p = kante + aussen * e
                abst = _abstand_zur_linie(p, linie)
                # Am eigenen Stück wächst der Abstand mit e; fällt er darunter,
                # kommt ein anderes Streckenstück näher.
                zu_nah = abst < halbe_breite_m + min(e, 4.0) - 0.3
                grenze = np.where(zu_nah, np.maximum(e - 3.0, 0.0), np.inf)
                frei[kandidaten] = np.minimum(frei[kandidaten], grenze)
        breite = np.minimum(ziel, frei)
        # Sprünge aus dem Tasten weich machen, ohne irgendwo breiter zu werden.
        for _ in range(2):
            breite = np.minimum(breite, _ring_glaetten(breite, 3))
        breite[breite < 1.2] = 0.0
        ergebnis.append(breite)
    return ergebnis[0], ergebnis[1]


def _abstand_zur_linie(punkte: np.ndarray, linie: np.ndarray, block: int = 2048) -> np.ndarray:
    """Kürzester Abstand jedes Punkts zu einem geschlossenen Linienzug."""
    punkte = np.asarray(punkte, dtype=np.float64).reshape(-1, 2)
    a = np.asarray(linie, dtype=np.float64)
    b = np.roll(a, -1, axis=0)
    ab = b - a
    laenge2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
    ergebnis = np.empty(len(punkte))
    for s in range(0, len(punkte), block):
        p = punkte[s:s + block, None, :]
        tt = np.clip(((p - a) * ab).sum(axis=2) / laenge2, 0.0, 1.0)
        naechster = a + tt[..., None] * ab
        ergebnis[s:s + block] = np.sqrt(((p - naechster) ** 2).sum(axis=2)).min(axis=1)
    return ergebnis


def auslauf_baender(netz: "Streckennetz", breite_m: float,
                    hoehe_m: float = AUSLAUF_HOEHE_M) -> list[Band]:
    """Die Auslaufflächen als Bänder, UV in Weltmetern (die Textur kachelt wie Boden).

    Querprofil von der Fahrbahnkante nach außen: auf Randsteinhöhe
    ansetzen, flach auf ``hoehe_m``, am äußeren Rand steil unter den Boden —
    so endet der Kies an einer sauberen Linie im Gras. An den Enden eines
    Stücks taucht die Fläche ebenso unter.
    """
    linie = np.asarray(netz.mittellinie, dtype=np.float64)
    breiten = auslauf_breiten(linie, netz.halbe_breite_m, breite_m)
    ergebnis = []
    for seite, breite, name in ((1.0, breiten[0], "auslauf_links"),
                                (-1.0, breiten[1], "auslauf_rechts")):
        teile = []
        n = len(linie)
        for start, anzahl in _laeufe(breite > 0):
            geschlossen = anzahl >= n
            idx = np.arange(n) if geschlossen else np.arange(start - 1, start + anzahl + 1) % n
            kante = linie[idx] + seite * netz.links[idx] * netz.halbe_breite_m
            aussen = seite * netz.links[idx]
            w = np.maximum(breite[idx], 1.2)
            e = np.stack([np.zeros_like(w), np.full_like(w, 0.4), w - 0.45, w], axis=1)
            z = np.tile(np.array([0.012, hoehe_m, hoehe_m, -0.06]), (len(idx), 1))
            if not geschlossen:
                z[0] = z[-1] = -0.06
            # Die Profilrichtung ist hier "nach außen".
            p, nn, _uv, ii = _profilstreifen(kante, aussen, np.zeros(len(idx)), e, z, geschlossen)
            teile.append((p, nn, p[:, :2].copy(), ii))
        if not teile:
            continue
        pos, nor, uv, ind, basis = [], [], [], [], 0
        for p, nn, u, ii in teile:
            pos.append(p)
            nor.append(nn)
            uv.append(u)
            ind.append(ii + basis)
            basis += len(p)
        ergebnis.append(Band(name=name, positionen=np.vstack(pos).astype(np.float32),
                             normalen=np.vstack(nor).astype(np.float32),
                             uv=np.vstack(uv).astype(np.float32),
                             indizes=np.vstack(ind).astype(np.uint32)))
    return ergebnis


def auslauf_kreise(mittellinie_m: np.ndarray, halbe_breite_m: float, breite_m: float,
                   abstand_m: float = 3.0) -> list[tuple[float, float, float]]:
    """Die Auslaufzonen als Kreise ``(x, y, r)`` — für die Platzierung.

    Bäume und Häuser dürfen nicht im Kiesbett stehen.
    """
    linie = np.asarray(mittellinie_m, dtype=np.float64)
    if len(linie) < 5:
        return []
    _t, links = _tangenten_und_links(linie)
    kreise = []
    for seite, breite in zip((1.0, -1.0), auslauf_breiten(linie, halbe_breite_m, breite_m)):
        letzter = None
        for i in np.flatnonzero(breite > 0):
            mitte = linie[i] + seite * links[i] * (halbe_breite_m + breite[i] / 2)
            if letzter is not None and np.linalg.norm(mitte - letzter) < abstand_m:
                continue
            letzter = mitte
            kreise.append((float(mitte[0]), float(mitte[1]), float(breite[i] / 2 + 0.5)))
    return kreise


# ---------------------------------------------------------------------------
# Gummiabrieb
# ---------------------------------------------------------------------------


def gummi_maske(netz: "Streckennetz", quer_px: int = 128,
                laengs_m_je_px: float = 0.5, max_laengs_px: int = 4096) -> np.ndarray:
    """Wo auf der Fahrbahn Gummi liegt: (laengs, quer) uint8, 0..255.

    Zeile 0 liegt bei Bogenlänge 0, die letzte kurz vor dem Ende — die
    Textur kachelt längs, die Naht läuft durch. Spalte 0 ist die linke
    Fahrbahnkante (u = 0 im Fahrbahnband). Abgefahren wird entlang der
    Ideallinie, dunkler in Kurven und Bremszonen: zwei schmale Spuren (die
    Räder) in einem breiten, schwachen Schleier (die Streuung des Felds).
    """
    linie = np.asarray(netz.mittellinie, dtype=np.float64)
    n = len(linie)
    if n < 3 or netz.halbe_breite_m <= 0:
        return np.zeros((1, quer_px), dtype=np.uint8)
    gesamt = _gesamtumfang(linie)
    zeilen = int(min(max_laengs_px, max(64, round(gesamt / laengs_m_je_px))))
    bogen = np.concatenate([np.asarray(netz.bogen_m, dtype=np.float64), [gesamt]])
    versatz = np.asarray(netz.ideal_versatz_m, dtype=np.float64)
    if len(versatz) != n:
        versatz = np.zeros(n)
    kr = np.abs(_ring_glaetten(np.asarray(netz.kruemmung, dtype=np.float64)
                               if len(netz.kruemmung) == n else kruemmung(linie), 3))
    # Stärke: Grundschleier auf Geraden, voll in Kurven und davor (Bremsen).
    schritt = gesamt / n
    vorlauf = int(round(40.0 / max(schritt, 1e-3)))
    kurvig = np.clip(kr * 45.0, 0.0, 1.0)
    brems = np.max(np.stack([np.roll(kurvig, -k) for k in range(0, vorlauf + 1, 2)]), axis=0)
    staerke = 0.35 + 0.65 * _ring_glaetten(np.maximum(kurvig, 0.8 * brems), 4)
    s = (np.arange(zeilen) + 0.5) / zeilen * gesamt
    o = np.interp(s, bogen, np.concatenate([versatz, versatz[:1]]))
    k = np.interp(s, bogen, np.concatenate([staerke, staerke[:1]]))
    breite = 2.0 * netz.halbe_breite_m
    x = (np.arange(quer_px) + 0.5) / quer_px * breite          # ab linker Kante
    quer = netz.halbe_breite_m - x                                # nach links positiv
    d = quer[None, :] - o[:, None]
    spur = 0.85
    wert = (0.45 * np.exp(-0.5 * (d / 1.6) ** 2)
            + 0.5 * (np.exp(-0.5 * ((d - spur) / 0.32) ** 2) + np.exp(-0.5 * ((d + spur) / 0.32) ** 2))
            + 0.12 * np.exp(-0.5 * (d / 3.5) ** 2))
    wert = np.clip(wert * k[:, None], 0.0, 1.0)
    return (wert * 255.0 + 0.5).astype(np.uint8)


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

    tangenten, links = _tangenten_und_links(mittellinie_m)

    punkte_links = mittellinie_m + links * halbe_breite_m
    punkte_rechts = mittellinie_m - links * halbe_breite_m

    bogenlaengen_m = _bogenlaengen(mittellinie_m)
    v_werte = bogenlaengen_m / kachellaenge_m
    gesamt_m = _gesamtumfang(mittellinie_m)
    kr = kruemmung(mittellinie_m)

    baender = [
        _band_aus_ringen("fahrbahn", punkte_links, punkte_rechts, 0.0, 1.0, v_werte,
                         v_naht=gesamt_m / kachellaenge_m),
    ]
    # Randsteine liegen **auf** der Fahrbahn, am Rand innen: die Wände des
    # Spiels fallen mit der Fahrbahnkante zusammen, und dort stehen in 3D die
    # Leitplanken. Lägen die Randsteine außen, stünde die Planke einen Meter
    # hinter der Stelle, an der das Auto abprallt. Nur in Kurven, als Körper
    # mit gewölbtem Profil; auf den Geraden markiert die Randlinie im
    # Asphalt die Kante. v in Metern entlang der Mittellinie.
    punktabstand = gesamt_m / max(len(mittellinie_m), 1)
    maske_links, maske_rechts = randstein_masken(kr, punktabstand)
    for name, kante, innen, maske in (("randstein_links", punkte_links, -links, maske_links),
                                      ("randstein_rechts", punkte_rechts, links, maske_rechts)):
        band = randsteine_bauen(name, kante, innen, bogenlaengen_m, maske, randstein_m,
                                tangenten, gesamt_m)
        if band is not None:
            baender.append(band)

    # Untergrund: Bounding-Box ueber Mittellinie und Randsteine, damit die
    # Ebene die ganze sichtbare Strecke sicher umschliesst, plus Rand.
    alle_punkte_m = np.concatenate([mittellinie_m, punkte_links, punkte_rechts])
    min_xy = alle_punkte_m.min(axis=0) - untergrund_rand_m
    max_xy = alle_punkte_m.max(axis=0) + untergrund_rand_m
    baender.append(_rechteck_band(
        "untergrund", min_xy, max_xy, UNTERGRUND_VERSATZ_M, kachellaenge_m))

    laenge_m = gesamt_m

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
                         start_positionen=start_positionen,
                         mittellinie=mittellinie_m,
                         tangenten=tangenten,
                         halbe_breite_m=halbe_breite_m,
                         rand_links=punkte_links, rand_rechts=punkte_rechts,
                         links=links,
                         name=str(strecke.get("name", "")),
                         thema=str(strecke.get("theme") or strecke.get("background_texture") or ""),
                         bogen_m=bogenlaengen_m, kruemmung=kr,
                         ideal_versatz_m=ideallinie(mittellinie_m, links, halbe_breite_m))


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
