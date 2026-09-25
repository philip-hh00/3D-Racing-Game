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

from . import grafik, track_mesh
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


def _ringabstand(bogen: np.ndarray, von: float, gesamt: float) -> np.ndarray:
    """Abstand entlang der geschlossenen Strecke, in beide Richtungen."""
    d = np.abs(bogen - von) % gesamt
    return np.minimum(d, gesamt - d)


def _scheitel(linie: np.ndarray, grenze_m: float) -> list[int]:
    """Je Kurve enger als ``grenze_m`` der Punkt stärkster Krümmung."""
    radius = _kruemmungsradius(linie)
    ergebnis = []
    for start, anzahl in track_mesh._laeufe(radius < grenze_m):
        idx = np.arange(start, start + anzahl) % len(linie)
        ergebnis.append(int(idx[np.argmin(radius[idx])]))
    return ergebnis


def rand_setzen(art: Randart, linie: np.ndarray, halbbreite: float,
                belegung: _Belegung, rng, start_index: int = 0,
                sperre: _Belegung | None = None,
                auslauf_breite_m: float = 0.0) -> list[Platzierung]:
    """Randobjekte einer Art. ``sperre``: Flächen, auf denen nichts stehen
    darf, was weiter als drei Meter von der Kante weg steht (Kiesbetten)."""
    if art.art == "kette":
        return kette_setzen(art, linie, halbbreite, belegung, rng, start_index, auslauf_breite_m)
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
        ziel = (bogen[start_index % len(linie)] + art.versatz_m) % gesamt
        indizes = [int(np.argmin(_ringabstand(bogen, ziel, gesamt)))]
    elif art.art == "scheitel":
        indizes = _scheitel(linie, ENGE_KURVE_M * 1.4)
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
    if art.bereich_m > 0 and art.art != "start":
        nah = _ringabstand(bogen, bogen[start_index % len(linie)], gesamt) <= art.bereich_m
        indizes = [i for i in indizes if nah[i]]

    for i in indizes:
        for seite in ("aussen", "innen"):
            if art.seite not in (seite, "beide") and art.art != "scheitel":
                continue
            if art.art == "kurven" and seite == "innen":
                continue
            if art.art == "scheitel" and seite == "aussen":
                continue
            nach_links = links_innen[i] == (seite == "innen")
            n = links[i] if nach_links else -links[i]
            pos = linie[i] + n * abstand
            # In engen Kurven läge der Punkt innen womöglich auf der Strecke.
            if abstand_zur_linie(pos[None], linie)[0] < abstand - 0.5:
                continue
            r = art.radius_m * art.skala
            # Was an der Startlinie steht, kommt zuerst und hat dort Vorrang;
            # der grobe Kreis einer langen Tribüne träfe sonst die Startbrücke.
            if art.art != "start" and not belegung.frei(pos[0], pos[1], r):
                continue
            if (sperre is not None and art.art != "start" and art.abstand_m >= 3.0
                    and not sperre.frei(pos[0], pos[1], r * 0.5)):
                continue
            belegung.belegen(pos[0], pos[1], r)
            gier = _ausrichtung_zur_strecke(-n) + math.radians(art.drehung_grad)
            ergebnis.append(Platzierung(_modell(art.modell, rng), float(pos[0]), float(pos[1]),
                                        gier, art.skala))
    return ergebnis


def kette_setzen(art: Randart, linie: np.ndarray, halbbreite: float,
                 belegung: _Belegung, rng, start_index: int = 0,
                 auslauf_breite_m: float = 0.0) -> list[Platzierung]:
    """Glieder lückenlos aneinander, etwa Fangzaunfelder von ``je_m`` Länge.

    Gelegt wird entlang der **versetzten** Linie im Abstand ``abstand_m`` von
    der Kante und nach deren eigener Bogenlänge — außen in einer Kurve ist
    sie länger als die Mittellinie, und Glieder im Mittellinienabstand
    klafften dort auseinander. Jedes Glied spannt von Stützpunkt zu
    Stützpunkt (lokal +X), die Vorderseite (+Y) zeigt zur Strecke. Mit
    ``seite = "auslauf"`` folgt die Kette dem äußeren Rand der Kiesbetten.
    """
    t = _tangenten(linie)
    links = np.stack([-t[:, 1], t[:, 0]], axis=1)
    n = len(linie)
    seg = np.linalg.norm(np.roll(linie, -1, axis=0) - linie, axis=1)
    bogen = np.concatenate([[0.0], np.cumsum(seg)])[:-1]
    gesamt = float(seg.sum())
    links_innen = innerhalb(linie + links * (halbbreite + 1.0), linie)
    aussen_links = bool(links_innen.mean() < 0.5)
    zuege = []                    # (Punkte, Maske), je Seite ein Zug
    if art.seite == "auslauf":
        breiten = track_mesh.auslauf_breiten(linie, halbbreite, auslauf_breite_m)
        for vorzeichen, breite in zip((1.0, -1.0), breiten):
            pkt = linie + vorzeichen * links * (halbbreite + breite[:, None] + art.abstand_m)
            zuege.append((pkt, breite > 0))
    else:
        seiten = {"aussen": [aussen_links], "innen": [not aussen_links],
                  "beide": [True, False]}.get(art.seite, [aussen_links])
        for nach_links in seiten:
            vorzeichen = 1.0 if nach_links else -1.0
            pkt = linie + vorzeichen * links * (halbbreite + art.abstand_m)
            zuege.append((pkt, np.ones(n, dtype=bool)))
    if art.bereich_m > 0:
        nah = _ringabstand(bogen, bogen[start_index % n], gesamt) <= art.bereich_m
        zuege = [(p, m & nah) for p, m in zuege]
    ergebnis = []
    for pkt, maske in zuege:
        # Wo die versetzte Linie einem anderen Stück zu nah kommt: Lücke.
        maske = maske & (abstand_zur_linie(pkt, linie) > halbbreite + min(art.abstand_m, 2.0) - 0.3)
        for start, anzahl in track_mesh._laeufe(maske):
            geschlossen = anzahl >= n
            idx = np.arange(n) if geschlossen else np.arange(start, start + anzahl) % n
            p = pkt[idx]
            if geschlossen:
                p = np.vstack([p, p[:1]])
            s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
            if s[-1] < art.je_m:
                continue
            stellen = np.append(np.arange(0.0, s[-1] - art.je_m * 0.5, art.je_m), s[-1])
            stuetzen = np.stack([np.interp(stellen, s, p[:, 0]), np.interp(stellen, s, p[:, 1])], axis=1)
            for a, b in zip(stuetzen[:-1], stuetzen[1:]):
                sehne = b - a
                if float(np.linalg.norm(sehne)) < 0.3 * art.je_m:
                    continue
                mitte = (a + b) / 2
                gier = math.atan2(sehne[1], sehne[0])
                i = int(np.argmin(((linie - mitte) ** 2).sum(axis=1)))
                zur_strecke = linie[i] - mitte
                if -math.sin(gier) * zur_strecke[0] + math.cos(gier) * zur_strecke[1] < 0:
                    gier += math.pi
                belegung.belegen(float(mitte[0]), float(mitte[1]), art.radius_m)
                ergebnis.append(Platzierung(_modell(art.modell, rng), float(mitte[0]), float(mitte[1]),
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
               name: str, start_index: int = 0, details: int | None = None) -> list[Platzierung]:
    """Alles, was um diese Strecke herum steht."""
    linie = np.asarray(mittellinie_m, dtype=np.float64)[:, :2]
    rng = np.random.default_rng(keim(name))
    belegung = _Belegung()
    ergebnis: list[Platzierung] = [startbruecke(linie, halbbreite_m, belegung)]
    # Streckenobjekte nach Grafikstufe; Kiesbetten bleiben frei (Strang S).
    if details is None:
        details = grafik.aktuell().strecken_details
    auslauf_m = float(getattr(getattr(thema, "auslauf", None), "breite_m", 0.0) or 0.0)
    sperre = _Belegung()
    for (x, y, r) in track_mesh.auslauf_kreise(linie, halbbreite_m, auslauf_m) if auslauf_m > 0 else []:
        sperre.belegen(x, y, r)
    # Was an der Startlinie steht (Tribüne, Boxen), zuerst: es braucht viel
    # Platz, und eine Bande davor ist leichter verschoben als eine Tribüne.
    for art in sorted(thema.rand, key=lambda a: a.art != "start"):
        if getattr(art, "detail", 0) > details:
            continue
        ergebnis += rand_setzen(art, linie, halbbreite_m, belegung, rng, start_index,
                                sperre=sperre, auslauf_breite_m=auslauf_m)
    for liste in sperre.raster.values():
        for (x, y, r) in liste:
            belegung.belegen(x, y, r)
    for art in sorted(thema.deko, key=lambda a: -a.radius_m):
        ergebnis += deko_setzen(art, linie, halbbreite_m, belegung, rng)
    for art in thema.kulisse:
        ergebnis += kulisse_setzen(art, linie, rng)
    return ergebnis


# ---------------------------------------------------------------------------
# Gelände (Strang W): Nachschritt nach dem Platzieren
# ---------------------------------------------------------------------------

#: So steil darf der Boden unter einem Haus sein, bevor es geebnet wird —
#: steiler, und das Haus entfällt (eine Terrasse in der Felswand sähe
#: gebaut aus, nicht gewachsen).
EBNEN_MAX_GRAD = 28.0


def _arten_je_modell(thema: Thema | None) -> dict:
    """Modellname → (Gruppe, Art); ``"a|b"`` zählt für beide."""
    arten: dict = {}
    if thema is None:
        return arten
    for gruppe, liste in (("rand", thema.rand), ("deko", thema.deko), ("kulisse", thema.kulisse)):
        for art in liste:
            for name in art.modell.split("|"):
                arten.setdefault(name, (gruppe, art))
    return arten


def _fussabdruck(x: float, y: float, r: float, n: int = 6) -> tuple[np.ndarray, np.ndarray]:
    w = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return (np.concatenate([[x], x + r * np.cos(w)]), np.concatenate([[y], y + r * np.sin(w)]))


def hoehen_setzen(orte: list[Platzierung], gelaende, thema: Thema | None = None) -> list[Platzierung]:
    """Jede Platzierung auf den Boden an ihrem Ort — ein Schritt nach dem Platzieren.

    Die Platzierer rechnen flach; erst hier kommt das Gelände dazu, an einer
    Stelle für alle. ``gelaende`` ist ein :class:`~src.render3d.gelaende.Gelaende`
    (oder etwas mit ``feld``, ``neigung_feld_grad``, ``kantenabstand``,
    ``korridor``, ``ebnen``, ``hoehe``). In dieser Reihenfolge:

    1. **Ebnen.** Häuser (``flach``) und Randobjekte, die über den flachen
       Korridor hinausragen (die Tribüne), bekommen eine ebene Stelle. Ist
       der Hang dafür zu steil (Median über den Fußabdruck), entfällt das Haus.
    2. **Steilhänge.** Bäume und Büsche stehen nicht an Hängen über
       ``hang_max_grad`` (Vorgabe aus dem Thema); Felsen dürfen steiler.
    3. **Höhe.** Das Tiefste unter dem Fußabdruck — so schwebt nichts, und
       am Hang steckt die Bergseite ein Stück im Boden, wie bei einem
       echten Stamm.

    Liefert die verbliebenen Platzierungen; die Liste wird nicht verändert.
    """
    arten = _arten_je_modell(thema)
    baum_max = getattr(getattr(thema, "gelaende", None), "baum_hang_max_grad", 28.0)
    bleiben: list[tuple[Platzierung, float]] = []
    if not orte:
        return []

    # 1. und 2.: entscheiden, was bleibt, und die ebenen Stellen anmelden —
    # vor der ersten Höhenabfrage, denn danach steht das Netz. Das Feld wird
    # für alle Orte auf einmal gefragt: einzeln kostete es Sekunden.
    info = [arten.get(pl.modell, ("", None)) for pl in orte]
    # Kulisse hat statt eines Platzbedarfs einen Ring (von–bis); dort zählt
    # nur, dass der Fuß nicht schwebt.
    radien = np.array([(20.0 if g == "kulisse" else float(getattr(art, "radius_m", 1.0)))
                       * float(pl.skala) for pl, (g, art) in zip(orte, info)])
    x = np.array([pl.x for pl in orte])
    y = np.array([pl.y for pl in orte])
    kante = gelaende.kantenabstand(x, y)
    neigung = gelaende.neigung_feld_grad(x, y)
    haeuser = [k for k, (g, art) in enumerate(info) if g == "deko" and getattr(art, "flach", False)]
    haus_steil = {}
    if haeuser:
        fx, fy, zu = [], [], []
        for k in haeuser:
            px, py = _fussabdruck(orte[k].x, orte[k].y, radien[k])
            fx.append(px)
            fy.append(py)
            zu.append(np.full(len(px), k))
        zu = np.concatenate(zu)
        n = gelaende.neigung_feld_grad(np.concatenate(fx), np.concatenate(fy))
        for k in haeuser:
            haus_steil[k] = float(np.median(n[zu == k]))

    for k, (pl, (gruppe, art)) in enumerate(zip(orte, info)):
        radius = float(radien[k])
        if k in haus_steil:
            if haus_steil[k] > EBNEN_MAX_GRAD:
                continue
            gelaende.ebnen(pl.x, pl.y, radius)
            bleiben.append((pl, radius * 0.8))
        elif gruppe == "rand":
            if kante[k] + radius > gelaende.korridor:
                gelaende.ebnen(pl.x, pl.y, radius)
            bleiben.append((pl, 0.0))
        elif gruppe == "deko":
            grenze = art.hang_max_grad if art.hang_max_grad is not None else baum_max
            if neigung[k] > grenze:
                continue
            # Halber Platzbedarf: am Hang sinkt die Bergseite ein, die
            # Talseite hängt nicht in der Luft.
            bleiben.append((pl, min(radius * 0.5, 3.5)))
        else:
            # Kulisse und Unbekanntes: nur absenken.
            bleiben.append((pl, min(radius * 0.2, 8.0)))

    # 3.: Höhen, alle Fußabdrücke in einem Aufruf.
    xs, ys, zu = [], [], []
    for k, (pl, r) in enumerate(bleiben):
        px, py = _fussabdruck(pl.x, pl.y, r) if r > 0 else (np.array([pl.x]), np.array([pl.y]))
        xs.append(px)
        ys.append(py)
        zu.append(np.full(len(px), k))
    if not bleiben:
        return []
    z = gelaende.hoehe(np.concatenate(xs), np.concatenate(ys))
    tiefste = np.full(len(bleiben), np.inf)
    np.minimum.at(tiefste, np.concatenate(zu), z)
    ergebnis = []
    for (pl, _r), h in zip(bleiben, tiefste):
        ergebnis.append(Platzierung(pl.modell, pl.x, pl.y, pl.gier_rad, pl.skala,
                                    float(pl.z + h)))
    return ergebnis


def ausduennen(orte: list[Platzierung], thema: Thema | None, anteil: float,
               name: str = "") -> list[Platzierung]:
    """Nur einen Anteil der verstreuten Deko behalten (``grafik.deko_dichte``).

    Randobjekte und Kulisse bleiben alle — eine Bande mit Lücke sieht
    kaputt aus, ein Wald mit weniger Bäumen nicht. Fest je Strecke.
    """
    if anteil >= 0.999:
        return list(orte)
    arten = _arten_je_modell(thema)
    rng = np.random.default_rng(keim(f"duenn:{name}"))
    zufall = rng.uniform(size=len(orte))
    return [pl for pl, u in zip(orte, zufall)
            if arten.get(pl.modell, ("", None))[0] != "deko" or u < anteil]


def grasfreie_flaechen(orte: list[Platzierung], thema: Thema | None,
                       ausdehnung: dict | None = None, ab_radius_m: float = 2.0) -> np.ndarray:
    """Gedrehte Rechtecke, in denen kein Gras wächst: unter Randobjekten
    (Boxengebäude mit Vorplatz, Tribünen, Posten) und Häusern.

    Je Zeile ``(x, y, gier, x_min, x_max, y_min, y_max)`` — die Grenzen im
    Modellraum, schon skaliert. ``ausdehnung`` nennt je Modell die echten
    Grenzen ``(x_min, x_max, y_min, y_max)`` aus dem GLB; fehlt ein Modell
    dort, gilt ein Quadrat aus dem Platzbedarf des Themas. Ein Kreis reicht
    nicht: das Boxengebäude ist 52 × 22 m groß, samt Vorplatz.

    Kleines (Banden, Hütchen, Zaunglieder unter ``ab_radius_m``) sperrt
    nichts — Gras bis an den Pfosten sieht richtig aus.
    """
    arten = _arten_je_modell(thema)
    ausdehnung = ausdehnung or {}
    zeilen = []
    for pl in orte:
        gruppe, art = arten.get(pl.modell, ("", None))
        if gruppe == "rand" or (gruppe == "deko" and getattr(art, "flach", False)):
            r = float(getattr(art, "radius_m", 0.0))
            if r * float(pl.skala) < ab_radius_m:
                continue
            x0, x1, y0, y1 = ausdehnung.get(pl.modell, (-r, r, -r, r))
            s = float(pl.skala)
            zeilen.append((pl.x, pl.y, pl.gier_rad, x0 * s, x1 * s, y0 * s, y1 * s))
    return np.asarray(zeilen, dtype=np.float64).reshape(-1, 7)
