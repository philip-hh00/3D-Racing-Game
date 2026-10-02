"""Mehrere Motorstimmen in einem Rutsch rechnen (01.10.2026).

**Warum es das gibt.** Der Erzeugerfaden rechnete jede Stimme einzeln: je Stimme
und Stueck rund 160 numpy-Aufrufe auf Feldern von 1024 Werten. Jeder davon gibt
den GIL frei und muss ihn danach vom Spielfaden zurueckerbitten, und jede
solche Rueckgabe kostet den Spielfaden einen erzwungenen Wechsel. Im Rennen
machte das acht Millisekunden je Bild aus (``tools/rennen_probe.py gp --stufe
hoch``: 14,5 ms ohne Ton, 22,6 ms mit), obwohl die reine Rechenzeit unter zwei
Millisekunden liegt. Es zaehlt also die **Zahl der Aufrufe**, nicht die Menge.

Hier werden alle hoerbaren Stimmen gestapelt: aus ``V`` Stimmen mit je ``L``
Abtastwerten wird ein Feld ``V x L``, und jeder Rechenschritt laeuft genau einmal
darueber — Phase, Schichtauswahl, Interpolation, Faerbung, Hochpass, Begrenzer.
Dazu kommen Umformungen, die Aufrufe sparen:

* Die Phase ist ein ``cumsum`` ueber ein **Polynom zweiten Grades** im
  Abtastindex (Drehzahl und Streuung laufen linear). Die Summe hat eine
  geschlossene Form, also ein einziges Matrixprodukt statt Rampen und cumsum.
* Die Schleifen liegen je Motor hintereinander, mit einem Wiederholwert am Ende
  und der Differenz zum Nachbarn. Interpolation ist dann ``x[i] + f * d[i]``,
  ohne Umbruch des zweiten Index.
* Die Zeilen der Einpolfilter (``a**k`` und ``a**-k``) haengen nur von der
  Filterkonstante ab und werden gemerkt.

**Gleicher Klang.** Der Weg ist Schritt fuer Schritt derselbe wie
:meth:`sfx.Motorstimme.block` und fuehrt denselben Zustand der Stimmen fort
(Phase, Gewichte, Filterreste, Zufallsfolge). Die Einzelstimme bleibt als
Bezugswert im Code; ``tests/test_motorstapel.py`` vergleicht beide.
"""
from __future__ import annotations

import numpy as np

from src.core import sfx

SR = sfx.SR


class _Flach:
    """Alle Schleifen eines Motors hintereinander (je eine Stelle Wiederholwert)."""

    __slots__ = ("schluessel", "x", "dx", "start", "laenge", "spiel", "zyklen")

    def __init__(self, schichten: sfx.Schichten) -> None:
        schleifen = schichten.schleifen
        self.schluessel = tuple(id(s) for s in schleifen)
        n = len(schleifen)
        self.laenge = [len(s) for s in schleifen]
        self.start = []
        teile_x, teile_d = [], []
        pos = 0
        for s in schleifen:
            self.start.append(pos)
            x = np.empty(len(s) + 1, dtype=np.float32)
            x[:-1] = s
            x[-1] = s[0]
            d = np.zeros(len(s) + 1, dtype=np.float32)
            d[:-1] = np.diff(x.astype(np.float64)).astype(np.float32)
            teile_x.append(x)
            teile_d.append(d)
            pos += len(s) + 1
        self.x = np.concatenate(teile_x) if n else np.zeros(2, dtype=np.float32)
        self.dx = np.concatenate(teile_d) if n else np.zeros(2, dtype=np.float32)
        self.spiel = [120.0 * SR / max(1.0, float(u)) for u in schichten.drehzahlen]
        self.zyklen = [la / sp for la, sp in zip(self.laenge, self.spiel)]


def _flach(schichten: sfx.Schichten) -> _Flach:
    f = getattr(schichten, "_flach", None)
    if f is None or f.schluessel != tuple(id(s) for s in schichten.schleifen):
        f = _Flach(schichten)
        schichten._flach = f
    return f


class _Arbeit:
    """Hilfsfelder je Blocklaenge und die Tabellen der Einpolfilter."""

    def __init__(self) -> None:
        self.laenge = 0
        self.filter: dict[float, tuple[np.ndarray, np.ndarray]] = {}

    def vorbereiten(self, laenge: int) -> None:
        if laenge == self.laenge:
            return
        self.laenge = laenge
        n = np.arange(laenge, dtype=np.float64)
        #: Grundfunktionen der Phasensumme: 1, n+1, n(n+1)/2, n(n+1)(2n+1)/6
        self.phasenbasis = np.stack([np.ones(laenge), n + 1.0, n * (n + 1.0) / 2.0,
                                     n * (n + 1.0) * (2.0 * n + 1.0) / 6.0])
        self.k = n
        #: Verlauf von 0 nach 1 und seine Basis fuer Anfang + Anstieg
        rampe = np.linspace(0.0, 1.0, laenge)
        self.rampenbasis = np.stack([np.ones(laenge), rampe])
        self.filter.clear()

    def einpol(self, a: float) -> tuple[np.ndarray, np.ndarray]:
        """``a**n`` und ``(1-a) * a**-n`` fuer ``y[n] = a*y[n-1] + (1-a)*x[n]``."""
        t = self.filter.get(a)
        if t is None:
            if len(self.filter) > 64:
                self.filter.clear()
            lna = np.log(a)
            t = (np.exp(self.k * lna), (1.0 - a) * np.exp(-self.k * lna))
            self.filter[a] = t
        return t


_arbeit = _Arbeit()


def _einpolig(x: np.ndarray, a: list[float], start: list[float]) -> np.ndarray:
    """Einpolfilter zeilenweise (siehe :func:`sfx._einpolig`), ohne Schleife."""
    ar = _arbeit
    tabellen = [ar.einpol(w) for w in a]
    hoch = np.stack([t[0] for t in tabellen])
    runter = np.stack([t[1] for t in tabellen])
    summe = np.cumsum(x * runter, axis=1)
    summe += (np.asarray(a) * np.asarray(start))[:, None]
    summe *= hoch
    return summe


def bloecke(stimmen: list, upms: list, laenge: int) -> np.ndarray:
    """Naechster Block von *stimmen* bei den Drehzahlen *upms*: ``V x laenge``.

    Entspricht ``[s.block(u, laenge) for s, u in zip(stimmen, upms)]`` (float32,
    in [-1, 1]) und setzt den Zustand jeder Stimme genauso fort.
    """
    V = len(stimmen)
    L = int(laenge)
    if V == 0:
        return np.zeros((0, L), dtype=np.float32)
    ar = _arbeit
    ar.vorbereiten(L)
    nenner = float(L - 1) if L > 1 else 1.0

    # ── Skalare je Stimme (Python, billig) ──────────────────────────────────
    koeff: list[list[float]] = []         # je Stimme: phase0, c0, c1, c2
    pegel: list[float] = []
    reihen_v: list[int] = []
    reihen_koeff: list[list[float]] = []
    reihen_gew: list[tuple[float, float]] = []
    reihen_pegel: list[float] = []
    reihen_off: list[int] = []
    reihen_zyk: list[float] = []
    reihen_spiel: list[float] = []
    reihen_flach: list[_Flach] = []
    clip = np.clip

    for v, (s, upm) in enumerate(zip(stimmen, upms)):
        if not s.schichten:
            koeff.append([0.0, 0.0, 0.0, 0.0])
            pegel.append(0.0)
            continue
        u = s.akustische_drehzahl(s._fuehren(upm, L))
        lo, hi = s.schichten.bereich
        ziel = float(clip(u, lo, hi))
        von = s.upm if s.upm > 0 else ziel
        s.upm = ziel
        # Zyklusstreuung: derselbe Zufallswert und Zustand wie Zyklusstreuung.rate.
        st = s.streuung
        if st:
            a = float(np.exp(-2.0 * np.pi * st.hz * L / SR))
            norm = float(np.sqrt((1.0 - a) / (1.0 + a))) or 1.0
            neu = a * st._letzter + (1.0 - a) * float(st._rng.standard_normal()) / norm
            r0 = 1.0 + st._letzter * st.staerke
            r1 = (neu - st._letzter) * st.staerke / nenner
            st._letzter = neu
        else:
            r0, r1 = 1.0, 0.0
        # schritt(j) = f * (von + w1*j) * (r0 + r1*j) = c0 + c1*j + c2*j*j
        f = s.tonhoehe / (120.0 * SR)
        w1 = (ziel - von) / nenner
        c = [f * von * r0, f * (von * r1 + w1 * r0), f * w1 * r1]
        n_end = L - 1
        summe_end = (c[0] * (n_end + 1) + c[1] * n_end * (n_end + 1) / 2.0
                     + c[2] * n_end * (n_end + 1) * (2 * n_end + 1) / 6.0)
        k0 = [s.phase] + c
        koeff.append(k0)
        s.phase = float(s.phase + summe_end) % 1e6
        p = s.lautstaerke * s.grundpegel
        pegel.append(p)

        flach = _flach(s.schichten)
        neu_g = s.schichten.gewichte(ziel, s.blende)
        alt_g = s._gewichte if s._gewichte is not None else neu_g
        s._gewichte = neu_g
        for i, (g_alt, g_neu) in enumerate(zip(alt_g, neu_g)):
            if g_alt <= 0.001 and g_neu <= 0.001:
                continue
            reihen_v.append(v)
            reihen_koeff.append(k0)
            reihen_gew.append((g_alt, g_neu - g_alt))
            reihen_pegel.append(p)
            reihen_off.append(flach.start[i])
            reihen_zyk.append(flach.zyklen[i])
            reihen_spiel.append(flach.spiel[i])
            reihen_flach.append(flach)

    # ── Schichten: alle Reihen (Stimme x Schicht) auf einmal ────────────────
    R = len(reihen_v)
    if R:
        # Phase je Reihe: ein Matrixprodukt statt Rampe, Streuung und cumsum.
        phase = np.asarray(reihen_koeff) @ ar.phasenbasis             # R x L
        np.remainder(phase, np.asarray(reihen_zyk)[:, None], out=phase)
        phase *= np.asarray(reihen_spiel)[:, None]                     # Stelle
        i0 = phase.astype(np.int64)
        phase -= i0                                                    # Rest
        feld_x, feld_d, versatz = _gemeinsames_feld(reihen_flach)
        i0 += (np.asarray(reihen_off) + versatz)[:, None]
        wert = np.multiply(feld_d.take(i0), phase)
        wert += feld_x.take(i0)
        gew = np.asarray(reihen_gew) @ ar.rampenbasis                  # R x L
        np.sqrt(gew, out=gew)
        wert *= gew
        # Reihen zu Stimmen zusammenfassen, Pegel gleich mit.
        summe = np.zeros((V, R))
        summe[reihen_v, np.arange(R)] = reihen_pegel
        aus = summe @ wert
    else:
        aus = np.zeros((V, L))
    np.clip(aus, -1.0, 1.0, out=aus)

    _faerbung(stimmen, aus, L)
    _hochpass(stimmen, aus, L)
    _begrenzer(stimmen, aus, L)
    np.clip(aus, -1.0, 1.0, out=aus)
    return aus.astype(np.float32)


# ── Gemeinsames Feld der Schleifen ───────────────────────────────────────────
_feld_cache: dict[tuple, tuple] = {}


def _gemeinsames_feld(flache: list):
    """Ein Feld mit den Schleifen aller beteiligten Motoren, dazu der Versatz je Reihe."""
    motoren = []
    ids = []
    for f in flache:
        if id(f) not in ids:
            ids.append(id(f))
            motoren.append(f)
    schluessel = tuple((id(f), f.x.shape[0]) for f in motoren)
    treffer = _feld_cache.get(schluessel)
    if treffer is None:
        versatz = {}
        pos = 0
        for f in motoren:
            versatz[id(f)] = pos
            pos += f.x.shape[0]
        if len(motoren) == 1:
            x, d = motoren[0].x, motoren[0].dx
        else:
            x = np.concatenate([f.x for f in motoren])
            d = np.concatenate([f.dx for f in motoren])
        if len(_feld_cache) > 16:
            _feld_cache.clear()
        treffer = (x, d, versatz)
        _feld_cache[schluessel] = treffer
    x, d, versatz = treffer
    return x, d, np.array([versatz[id(f)] for f in flache], dtype=np.int64)


# ── Faerbung (sfx.Faerbung) ──────────────────────────────────────────────────
def _faerbung(stimmen: list, aus: np.ndarray, L: int) -> None:
    zeilen = [v for v, s in enumerate(stimmen) if s.faerbung]
    if not zeilen:
        return
    fb = [stimmen[v].faerbung for v in zeilen]
    taps = fb[0]._taps
    n = len(taps)
    mitte = (n - 1) // 2
    Z = len(zeilen)
    x = np.empty((Z, n - 1 + L))
    for j, f in enumerate(fb):
        if f._erster:
            f._rest = np.full(n - 1, float(aus[zeilen[j], 0]) if L else 0.0)
            f._erster = False
        x[j, :n - 1] = f._rest
    x[:, n - 1:] = aus if Z == len(stimmen) else aus[zeilen]
    for j, f in enumerate(fb):
        f._rest = x[j, -(n - 1):].copy()
    # Korrelation mit den (symmetrischen) Taps ueber ein Fensterfeld.
    fenster = np.lib.stride_tricks.sliding_window_view(x, n, axis=1)
    tief = np.einsum("zlk,k->zl", fenster, taps)
    trocken = x[:, mitte:mitte + L]
    # (1-f)*trocken + f*tief fuer staerke = f > 0, und (1+f)*trocken - f*tief fuer
    # staerke = -f < 0, beides: trocken + staerke*(tief - trocken)
    tief -= trocken
    tief *= np.array([f.staerke for f in fb])[:, None]
    tief += trocken
    tief *= np.array([f._ausgleich for f in fb])[:, None]
    rein = np.sqrt(np.einsum("zl,zl->z", trocken, trocken) / L)
    raus = np.sqrt(np.einsum("zl,zl->z", tief, tief) / L)
    nach = np.array([f._nach for f in fb])
    gut = (rein > 1e-5) & (raus > 1e-5)
    ziel = np.clip(rein / np.maximum(raus, 1e-300), 0.25, 4.0)
    nach = np.where(gut, nach + (ziel - nach) * 0.08, nach)
    for j, f in enumerate(fb):
        f._nach = float(nach[j])
    tief *= nach[:, None]
    np.clip(tief, -1.0, 1.0, out=tief)
    if Z == len(stimmen):
        aus[...] = tief
    else:
        aus[zeilen] = tief


# ── Hochpass (sfx.Hochpass) ──────────────────────────────────────────────────
def _hochpass(stimmen: list, aus: np.ndarray, L: int) -> None:
    zeilen = [v for v, s in enumerate(stimmen) if s.hochpass]
    if not zeilen:
        return
    hp = [stimmen[v].hochpass for v in zeilen]
    for j, h in enumerate(hp):
        if h._erster:
            h._mittel = float(aus[zeilen[j], 0]) if L else 0.0
            h._erster = False
    a = [float(np.exp(-2.0 * np.pi * h.ecke / SR)) for h in hp]
    x = aus if len(zeilen) == len(stimmen) else aus[zeilen]
    tief = _einpolig(x, a, [h._mittel for h in hp])
    for j, h in enumerate(hp):
        h._mittel = float(tief[j, -1])
    if len(zeilen) == len(stimmen):
        aus -= tief
    else:
        aus[zeilen] = x - tief


# ── Begrenzer (sfx.Begrenzer) ────────────────────────────────────────────────
def _begrenzer(stimmen: list, aus: np.ndarray, L: int) -> None:
    zeilen = [v for v, s in enumerate(stimmen) if s.begrenzer]
    if not zeilen:
        return
    bg = [stimmen[v].begrenzer for v in zeilen]
    alle = len(zeilen) == len(stimmen)
    x = aus if alle else aus[zeilen]
    betrag = np.abs(x)
    a = [float(np.exp(-1000.0 / (b.tempo * SR))) for b in bg]
    glatt = _einpolig(betrag, a, [b._huellkurve for b in bg])
    for j, b in enumerate(bg):
        b._huellkurve = float(glatt[j, -1])
    np.maximum(betrag, glatt, out=betrag)
    np.maximum(betrag, 1e-9, out=betrag)
    schwelle = np.array([b.schwelle for b in bg])[:, None]
    np.divide(schwelle, betrag, out=betrag)
    np.minimum(betrag, 1.0, out=betrag)
    if alle:
        aus *= betrag
    else:
        aus[zeilen] = x * betrag
