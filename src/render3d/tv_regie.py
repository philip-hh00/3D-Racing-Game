"""TV-Regie fuer den Movie-Modus nach der Zieldurchfahrt.

Reine Rechnung mit numpy — kein OpenGL, kein pygame, ohne Fenster pruefbar.
Der Rennzustand reicht nur Zahlen herein (:class:`Auto`) und bekommt eine
Kamera zurueck (:class:`FilmKamera`, dieselbe Schnittstelle wie
``camera.Verfolgerkamera``: ``auge``, ``ziel``, ``blickmatrix()``, dazu
``sichtfeld_grad``).

Vier Teile:

* :func:`kameras_platzieren` — feste TV-Standorte neben der Strecke, mit
  wechselnder Seite, Hoehe (2-8 m) und Entfernung. Nichts steht auf oder an der
  Fahrbahn, in einem Baum oder Haus oder im Boden, und von jedem Standort ist
  die Strecke zu sehen (Sichtstrahl ueber das Gelaende).
* :class:`Regie` — waehlt Ziel und Standort und schneidet: mindestens
  :data:`Regie.MIN_SCHUSS_S` Sekunden je Einstellung, kein Hin und Her.
* :class:`Film` — eine Ansicht: erst das Auszoomen aus der Verfolgerkamera,
  dann die Regie.
* :class:`Nachspiel` — die Uhr: :data:`NACHLAUF_S` Sekunden nach dem Ende des
  Feldes zu den Ergebnissen, ``Enter`` ueberspringt.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass

import numpy as np

from .camera import blick

#: So lange laeuft der Film nach dem Ende des Feldes (alle im Ziel oder DNF),
#: bevor die Ergebnisse kommen.
NACHLAUF_S = 30.0

#: Dauer des Auszoomens aus der Verfolgerkamera.
AUSZOOM_S = 1.8


# ---------------------------------------------------------------------------
# Kleinkram
# ---------------------------------------------------------------------------

def sanft(u: float) -> float:
    """Ease-in/-out (smootherstep) auf 0..1."""
    u = min(1.0, max(0.0, float(u)))
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def _glatt_faktor(rate: float, dt: float) -> float:
    """Anteil des Weges zum Ziel in *dt* — rahmenratenunabhaengig."""
    return 1.0 - math.exp(-max(0.0, rate) * max(0.0, dt))


class Rundkurs:
    """Die geschlossene Mittellinie mit Bogenlaenge.

    ``bogen_bei`` ordnet einen Punkt der Strecke zu (Meter ab Punkt 0),
    ``vor`` misst, wie weit ein Ort in Fahrtrichtung voraus liegt.
    """

    def __init__(self, mittellinie) -> None:
        a = np.asarray(mittellinie, dtype=np.float64)[:, :2]
        if len(a) < 3:
            raise ValueError("Mittellinie braucht mindestens 3 Punkte")
        b = np.roll(a, -1, axis=0)
        self.linie = a
        self._a = a
        self._ab = b - a
        self._l2 = np.maximum((self._ab ** 2).sum(axis=1), 1e-12)
        seg = np.sqrt(self._l2)
        self._seg = seg
        self.laenge = float(seg.sum())
        self.bogen = np.concatenate([[0.0], np.cumsum(seg)[:-1]])

    def _naechster(self, x: float, y: float):
        p = np.array([x, y], dtype=np.float64)
        t = np.clip(((p - self._a) * self._ab).sum(axis=1) / self._l2, 0.0, 1.0)
        nah = self._a + t[:, None] * self._ab
        d2 = ((p - nah) ** 2).sum(axis=1)
        i = int(np.argmin(d2))
        return i, float(t[i]), math.sqrt(float(d2[i]))

    def bogen_bei(self, x: float, y: float) -> float:
        i, t, _d = self._naechster(x, y)
        return float(self.bogen[i] + t * self._seg[i])

    def abstand(self, x: float, y: float) -> float:
        """Abstand zur Mittellinie (Meter)."""
        return self._naechster(x, y)[2]

    def vor(self, von_m: float, nach_m: float) -> float:
        """Wie weit liegt *nach_m* in Fahrtrichtung vor *von_m*, 0..Laenge."""
        return float((nach_m - von_m) % self.laenge)

    def vor_vorzeichen(self, von_m: float, nach_m: float) -> float:
        """Wie :meth:`vor`, aber -Laenge/2..+Laenge/2 (negativ = dahinter)."""
        v = self.vor(von_m, nach_m)
        return v - self.laenge if v > self.laenge / 2.0 else v

    def punkt_bei(self, s_m: float):
        """``((x, y), (tx, ty))`` — Ort und Fahrtrichtung bei *s_m*."""
        s = float(s_m) % self.laenge
        i = int(np.searchsorted(self.bogen, s, side="right") - 1)
        i = min(max(i, 0), len(self.bogen) - 1)
        u = (s - self.bogen[i]) / self._seg[i]
        pos = self._a[i] + self._ab[i] * u
        t = self._ab[i] / self._seg[i]
        return pos, t


# ---------------------------------------------------------------------------
# Die Kamera
# ---------------------------------------------------------------------------

class FilmKamera:
    """Freie Kamera mit der Schnittstelle der Verfolgerkamera."""

    def __init__(self, auge=(0.0, 0.0, 5.0), ziel=(10.0, 0.0, 1.0),
                 sichtfeld_grad: float = 45.0) -> None:
        self._auge = np.asarray(auge, dtype=np.float64).copy()
        self._ziel = np.asarray(ziel, dtype=np.float64).copy()
        self.sichtfeld_grad = float(sichtfeld_grad)

    def setzen(self, auge, ziel, sichtfeld_grad: float | None = None) -> None:
        self._auge = np.asarray(auge, dtype=np.float64).copy()
        self._ziel = np.asarray(ziel, dtype=np.float64).copy()
        if sichtfeld_grad is not None:
            self.sichtfeld_grad = float(sichtfeld_grad)

    @property
    def auge(self) -> np.ndarray:
        return self._auge.astype(np.float32)

    @property
    def ziel(self) -> np.ndarray:
        return self._ziel.astype(np.float32)

    def blickmatrix(self) -> np.ndarray:
        if np.linalg.norm(self._ziel - self._auge) < 1e-6:
            return blick(self._auge, self._auge + np.array([1.0, 0.0, 0.0]))
        return blick(self._auge, self._ziel)


# ---------------------------------------------------------------------------
# Standorte
# ---------------------------------------------------------------------------

@dataclass
class Standort:
    """Eine feste TV-Kamera."""

    nr: int
    pos: np.ndarray            # (3,) Meter, z ueber NN der Fahrbahn
    bogen_m: float             # naechste Stelle der Mittellinie
    reichweite_m: float = 90.0
    seite: int = 1             # +1 links der Fahrtrichtung, -1 rechts


#: Abstaende von der Fahrbahnkante, aus denen gewuerfelt wird.
_KANTEN_ABSTAENDE_M = (5.0, 8.0, 12.0, 16.0, 22.0, 30.0)
#: Hoehen ueber dem Boden am Standort.
_HOEHEN_M = (2.0, 2.5, 3.5, 5.0, 6.5, 8.0)
#: So weit mindestens von der Fahrbahnkante (dort stehen die Waende).
KANTE_MIN_M = 3.0
#: Freiraum zu Baeumen, Haeusern und anderen Objekten.
OBJEKT_FREI_M = 1.5
#: Mindesthoehe ueber dem Boden.
BODEN_FREI_M = 1.8
#: Objekte bis zu dieser Hoehe versperren die Sicht nicht.
NIEDRIG_M = 1.5

#: Ohne Hoehenangabe: wie hoch ein Objekt etwa ist, nach seinem Radius —
#: Banden und Reifenstapel (unter 1 m), Zaeune, Posten, Buesche (bis 2,5 m),
#: alles Grosse (Baeume, Haeuser, Tribuenen). Der Sichtstrahl muss darueber
#: hinweg gehen.
_OBJEKTHOEHEN_M = ((1.0, 1.2), (2.5, 3.2), (1e9, 12.0))


def _objekthoehe(radius: np.ndarray) -> np.ndarray:
    h = np.full(radius.shape, _OBJEKTHOEHEN_M[-1][1])
    for grenze, hoehe in reversed(_OBJEKTHOEHEN_M[:-1]):
        h = np.where(radius < grenze, hoehe, h)
    return h


def hindernisse_normalisieren(hindernisse) -> np.ndarray:
    """``(n, 4)``: ``x, y, radius, hoehe``. Fehlt die Hoehe (``(n, 3)``), kommt
    sie aus dem Radius."""
    if hindernisse is None:
        return np.zeros((0, 4))
    a = np.asarray(hindernisse, dtype=np.float64)
    if a.size == 0:
        return np.zeros((0, 4))
    a = a.reshape(len(a), -1)
    if a.shape[1] >= 4:
        return a[:, :4]
    return np.column_stack([a[:, :3], _objekthoehe(a[:, 2])])


def _strahl_frei(hoehe_fn, hindernisse: np.ndarray, cx: float, cy: float, cz: float,
                 px: float, py: float, pz: float) -> bool:
    """Geht der Strahl von der Kamera zum Punkt ueber Gelaende und Objekte?"""
    u = np.linspace(0.0, 1.0, 10)[1:-1]
    xs = cx + (px - cx) * u
    ys = cy + (py - cy) * u
    zs = cz + (pz - cz) * u
    if hoehe_fn is not None:
        boden = np.atleast_1d(np.asarray(hoehe_fn(xs, ys), dtype=np.float64))
        if np.any(boden > zs - 0.3):
            return False
    if len(hindernisse):
        ox, oy, orad = hindernisse[:, 0], hindernisse[:, 1], hindernisse[:, 2]
        dx, dy = px - cx, py - cy
        l2 = max(dx * dx + dy * dy, 1e-9)
        t = np.clip(((ox - cx) * dx + (oy - cy) * dy) / l2, 0.0, 1.0)
        d = np.hypot(cx + t * dx - ox, cy + t * dy - oy)
        # Was niedriger ist als ein Auto (Banden, Reifenstapel) verdeckt nichts.
        nah = (d < orad + 0.3) & (hindernisse[:, 3] > NIEDRIG_M)
        if np.any(nah):
            z_strahl = cz + (pz - cz) * t[nah]
            if np.any(z_strahl < hindernisse[nah, 3]):
                return False
    return True


#: Die Strecke, die eine Kamera abdecken soll, relativ zu ihrer Stelle (Meter
#: entlang der Fahrbahn): das Auto kommt von hinten heran und faehrt vorbei.
_ABDECKUNG_M = tuple(np.linspace(-80.0, 40.0, 9))
#: So viel der abgedeckten Strecke darf verdeckt sein.
VERDECKT_MAX = 0.15
#: Weniger als so viele strenge Standorte: der Rest wird gelockert gesucht.
MIN_KAMERAS = 8
#: Oder eine Strecke ist laenger als das ohne Kamera.
MAX_LUECKE_M = 150.0

#: Innerhalb dieser Entfernung vor dem Objektiv darf nichts Hohes stehen.
LINSE_FREI_M = 8.0
#: Auch Niedriges (Banden, Reifenstapel) nicht naeher als das.
LINSE_NAH_M = 5.0


def _linse_frei(hindernisse: np.ndarray, cx: float, cy: float, cz: float,
                zx: float, zy: float, streng: bool = True) -> bool:
    """Steht vor dem Objektiv (vorn, innerhalb :data:`LINSE_FREI_M`) ein Objekt,
    das groesser im Bild waere als ein Auto? Posten, Masten, Schilder, Baeume."""
    if not len(hindernisse):
        return True
    vx, vy = zx - cx, zy - cy
    n = math.hypot(vx, vy)
    if n < 1e-6:
        return True
    vx, vy = vx / n, vy / n
    dx, dy = hindernisse[:, 0] - cx, hindernisse[:, 1] - cy
    dist = np.hypot(dx, dy)
    vorn = (dx * vx + dy * vy) > -hindernisse[:, 2]
    rand = dist - hindernisse[:, 2]
    # Etwas Hohes (Posten, Mast, Schild, Baum) innerhalb von LINSE_FREI_M, oder
    # auch Niedriges (Bande, Reifenstapel) ganz dicht vor der Linse.
    if streng:
        stoert = (((hindernisse[:, 3] > NIEDRIG_M) & (rand < LINSE_FREI_M))
                  | ((hindernisse[:, 3] > 0.7) & (rand < LINSE_NAH_M)))
    else:       # Notnagel auf zugebauten Strecken: nur Hohes, nur dicht davor
        stoert = (hindernisse[:, 3] > NIEDRIG_M) & (rand < LINSE_NAH_M)
    return not np.any(vorn & stoert)


def _sicht_frei(kurs: Rundkurs, halbe_breite_m: float, hoehe_fn, hindernisse: np.ndarray,
                cx: float, cy: float, cz: float, s_m: float, streng: bool = True) -> bool:
    """Sieht die Kamera die Strecke rund um *s_m*?

    Mehrere Strahlen zu Punkten der abzudeckenden Strecke (nicht nur einer):
    Gelaende, Zaeune und Objekte mit ihrem Grundriss und ihrer Hoehe duerfen
    hoechstens :data:`VERDECKT_MAX` davon verdecken, und vor dem Objektiv
    (:data:`LINSE_FREI_M`) darf nichts Hohes stehen.
    """
    (mx, my), _t = kurs.punkt_bei(s_m)
    if not _linse_frei(hindernisse, cx, cy, cz, float(mx), float(my), streng):
        return False
    verdeckt = 0
    for ds in _ABDECKUNG_M:
        (px, py), _t = kurs.punkt_bei(s_m + ds)
        if not _strahl_frei(hoehe_fn, hindernisse, cx, cy, cz, float(px), float(py), 0.8):
            verdeckt += 1
    grenze = VERDECKT_MAX if streng else 0.35
    return verdeckt <= grenze * len(_ABDECKUNG_M)


def standort_gueltig(kurs: Rundkurs, halbe_breite_m: float, hoehe_fn,
                     hindernisse: np.ndarray, x: float, y: float, h: float,
                     s_m: float, streng: bool = True) -> bool:
    """Alle Regeln fuer einen Standort an ``(x, y)`` in *h* Metern Hoehe."""
    if kurs.abstand(x, y) - halbe_breite_m < KANTE_MIN_M:
        return False
    if len(hindernisse):
        d = np.hypot(hindernisse[:, 0] - x, hindernisse[:, 1] - y)
        if np.any(d < hindernisse[:, 2] + OBJEKT_FREI_M):
            return False
    boden = 0.0
    if hoehe_fn is not None:
        boden = float(np.atleast_1d(hoehe_fn(np.array([x]), np.array([y])))[0])
    cz = boden + h
    if h < BODEN_FREI_M:
        return False
    return _sicht_frei(kurs, halbe_breite_m, hoehe_fn, hindernisse, x, y, cz,
                       kurs.bogen_bei(x, y), streng)


def kameras_platzieren(mittellinie, halbe_breite_m: float, *, name: str = "",
                       hoehe_fn=None, hindernisse=None,
                       abstand_m: float = 40.0,
                       reichweite_m: float = 90.0) -> list[Standort]:
    """TV-Kameras entlang der Strecke aufstellen.

    Fest je Strecke (Keim aus *name*). Alle ``abstand_m`` Meter eine, abwechselnd
    links und rechts, in Kurven bevorzugt aussen; Hoehe 2-8 m, Entfernung zur
    Fahrbahnkante 5-30 m, leicht gegen die Stelle versetzt, damit die Kameras
    nicht wie auf einer Schnur stehen.

    *hoehe_fn* ``(x_array, y_array) -> z_array``: der Boden (``Gelaende.hoehe``);
    ohne ist er flach bei 0. *hindernisse* ``(n, 3)``: ``x, y, radius`` von
    allem, was dort steht (Baeume, Haeuser, Tribuenen, Banden), optional dazu
    die Hoehe als vierte Spalte (sonst aus dem Radius geschaetzt).
    """
    kurs = Rundkurs(mittellinie)
    hind = hindernisse_normalisieren(hindernisse)
    rng = np.random.default_rng(zlib.crc32(str(name).encode("utf-8")) & 0x7FFFFFFF)
    anzahl = max(4, int(round(kurs.laenge / max(10.0, abstand_m))))
    schritt = kurs.laenge / anzahl
    standorte: list[Standort] = []
    plaetze = []
    for i in range(anzahl):
        s0 = i * schritt + float(rng.uniform(-0.15, 0.15)) * schritt
        (_p, t1) = kurs.punkt_bei(s0 + 20.0)
        (_p, t2) = kurs.punkt_bei(s0 - 20.0)
        kreuz = float(t2[0] * t1[1] - t2[1] * t1[0])   # >0: Linkskurve
        kurve = kreuz / 40.0
        if abs(kurve) > 1.0 / 200.0:
            bevorzugt = -1 if kurve > 0 else 1         # aussen
            if rng.uniform() < 0.3:
                bevorzugt = -bevorzugt
        else:
            bevorzugt = 1 if i % 2 == 0 else -1
        plaetze.append((s0, bevorzugt))

    def suche(s0: float, bevorzugt: int, streng: bool):
        for versuch in range(40):
            seite = bevorzugt if versuch < 16 else -bevorzugt
            d = float(rng.choice(_KANTEN_ABSTAENDE_M))
            h = float(rng.choice(_HOEHEN_M))
            # Spaeter im Lauf: naeher und niedriger probieren, falls es eng ist.
            if versuch >= 24:
                d = float(rng.choice(_KANTEN_ABSTAENDE_M[:3]))
            s = s0 + float(rng.uniform(-15.0, 15.0))
            (pos, t) = kurs.punkt_bei(s)
            links = np.array([-t[1], t[0]])
            xy = pos + seite * links * (halbe_breite_m + d)
            if standort_gueltig(kurs, halbe_breite_m, hoehe_fn, hind,
                                float(xy[0]), float(xy[1]), h, s0, streng):
                boden = 0.0
                if hoehe_fn is not None:
                    boden = float(np.atleast_1d(hoehe_fn(np.array([xy[0]]), np.array([xy[1]])))[0])
                return Standort(nr=0, pos=np.array([xy[0], xy[1], boden + h]),
                                bogen_m=kurs.bogen_bei(float(xy[0]), float(xy[1])),
                                reichweite_m=reichweite_m, seite=int(seite))
        return None

    fehlend = []
    for s0, bevorzugt in plaetze:
        st = suche(s0, bevorzugt, True)
        if st is not None:
            standorte.append(st)
        else:
            fehlend.append((s0, bevorzugt))
    # Zugebaute Strecken (Zaun ringsum, dichte Haeuser): lieber ein paar
    # Kameras mit etwas Verdeckung als zu wenige.
    def groesste_luecke() -> float:
        b = sorted(st.bogen_m for st in standorte)
        if not b:
            return kurs.laenge
        return float(max(np.diff(b + [b[0] + kurs.laenge])))

    if len(standorte) < MIN_KAMERAS or groesste_luecke() > MAX_LUECKE_M:
        for s0, bevorzugt in fehlend:
            st = suche(s0, bevorzugt, False)
            if st is not None:
                standorte.append(st)
    standorte.sort(key=lambda st: st.bogen_m)
    for nr, st in enumerate(standorte):
        st.nr = nr
    return standorte


# ---------------------------------------------------------------------------
# Autos und Regie
# ---------------------------------------------------------------------------

@dataclass
class Auto:
    """Was die Regie von einem Fahrzeug wissen muss."""

    kennung: int
    x: float                    # Meter
    y: float
    gier: float = 0.0           # Radiant, 0 = +X
    tempo: float = 0.0          # m/s
    runden: float = 0.0         # Fortschritt in Runden (1.5 = halbe zweite Runde)
    im_ziel: bool = False       # im Ziel oder DNF: faehrt nicht mehr um Plaetze
    eigen: bool = False         # das Auto des Spielers, der zuschaut
    name: str = ""


class Regie:
    """Waehlt, wen welche Kamera zeigt, und schneidet."""

    #: Kuerzeste Einstellung. Darunter wird nie geschnitten (ausser das Ziel ist weg).
    MIN_SCHUSS_S = 3.0
    #: Laengste Einstellung, dann wird neu entschieden (bei gleichem Ziel und
    #: gleicher Kamera laeuft sie einfach weiter).
    MAX_SCHUSS_S = 14.0
    #: Ein Standort muss mindestens so weit voraus liegen, damit das Auto ins Bild faehrt.
    VORLAUF_MIN_M = 20.0
    #: Ist das Auto so weit am Standort vorbei, ist die Einstellung zu Ende.
    VORBEI_M = 45.0
    #: Ein gerade benutzter Standort bleibt so lange gesperrt (kein Hin und Her).
    SPERRE_S = 14.0
    #: Wer zwischen zwei Autos kaempft, ist spannender; so nah gilt als Kampf.
    KAMPF_M = 40.0
    #: So lange darf ein Objekt das Ziel verdecken, bevor geschnitten wird.
    VERDECKT_SCHNITT_S = 1.2
    #: Bonus fuer das bisherige Ziel — haelt die Wahl ruhig.
    BEIBEHALTEN_BONUS = 0.25

    def __init__(self, kurs: Rundkurs, standorte: list[Standort],
                 runden_gesamt: int = 3, hindernisse=None, hoehe_fn=None) -> None:
        self.kurs = kurs
        #: Objekte (``x, y, Radius, Hoehe``) und Boden: damit prueft die Regie
        #: beim Waehlen, ob eine Kamera das Ziel wirklich sieht.
        self.hindernisse = hindernisse_normalisieren(hindernisse)
        self.hoehe_fn = hoehe_fn
        self._verdeckt_s = 0.0
        self.standorte = list(standorte)
        self.runden_gesamt = max(1, int(runden_gesamt))
        self.kamera = FilmKamera()
        self.standort: Standort | None = None
        self.ziel_kennung: int | None = None
        self.schuss_alter = 0.0
        self.schnitte = 0
        self._uhr = 0.0
        self._benutzt: dict[int, float] = {}      # Standort-Nr -> Beginn der letzten Einstellung
        self._gezeigt: dict[int, float] = {}      # Auto -> Ende der letzten Einstellung
        self._schuss_reichweite = 0.0

    # -- Entscheidungen ----------------------------------------------------
    def waehle_ziel(self, autos: list[Auto]) -> Auto | None:
        """Wen zeigen? Ein Auto, das noch faehrt: spannende Zweikaempfe und wer
        dem Ziel am naechsten ist. Fahren alle nicht mehr, wechseln die Autos
        im Ziel einander ab (der Spieler zuerst)."""
        if not autos:
            return None
        fahrend = [a for a in autos if not a.im_ziel]
        if fahrend:
            bogen = {a.kennung: self.kurs.bogen_bei(a.x, a.y) for a in fahrend}
            beste, beste_note = None, -1e9
            for a in fahrend:
                luecke = min(
                    (abs(self.kurs.vor_vorzeichen(bogen[a.kennung], bogen[b.kennung]))
                     for b in fahrend if b is not a), default=1e9)
                kampf = max(0.0, 1.0 - luecke / self.KAMPF_M)
                fortschritt = min(1.0, a.runden / self.runden_gesamt)
                note = fortschritt + 0.6 * kampf
                if a.kennung == self.ziel_kennung:
                    note += self.BEIBEHALTEN_BONUS
                if note > beste_note:
                    beste, beste_note = a, note
            return beste
        # Alle im Ziel: wer am laengsten nicht dran war; der Spieler zuerst.
        def zuletzt(a: Auto) -> tuple:
            return (self._gezeigt.get(a.kennung, -1e9), not a.eigen, a.kennung)
        return min(autos, key=zuletzt)

    def sieht(self, st: Standort, auto: Auto) -> bool:
        """Ist der Strahl von der Kamera zum Auto frei (Gelaende, Objekte)?"""
        return _strahl_frei(self.hoehe_fn, self.hindernisse, float(st.pos[0]), float(st.pos[1]),
                            float(st.pos[2]), auto.x, auto.y, 0.8)

    def waehle_standort(self, auto: Auto) -> tuple[Standort | None, float]:
        """Die Kamera, die das Auto als naechste erwartet: der naechste Standort
        voraus, der sichtbar nah genug ist und nicht gerade benutzt wurde.

        Gibt ``(standort, reichweite_dieser_einstellung)``."""
        if not self.standorte:
            return None, 0.0
        s_auto = self.kurs.bogen_bei(auto.x, auto.y)
        gesperrt = {nr for nr, t in self._benutzt.items() if self._uhr - t < self.SPERRE_S}
        zeilen = []
        for st in self.standorte:
            vor = self.kurs.vor(s_auto, st.bogen_m)
            dist = math.hypot(st.pos[0] - auto.x, st.pos[1] - auto.y)
            zeilen.append((st, vor, dist))

        def wahl(ohne_sperre: bool, max_dist: float, vorlauf: bool, sichtbar: bool):
            kand = [(vor, dist, st) for (st, vor, dist) in zeilen
                    if (ohne_sperre or st.nr not in gesperrt)
                    and dist <= max_dist
                    and (not vorlauf or vor >= self.VORLAUF_MIN_M)
                    and (not sichtbar or self.sieht(st, auto))]
            if not kand:
                return None
            if vorlauf:
                vor, dist, st = min(kand, key=lambda k: k[0])
            else:
                vor, dist, st = min(kand, key=lambda k: k[1])
            return st, dist

        # Erst nur Kameras, die das Auto sehen; sonst (alles verdeckt) wie bisher.
        for sichtbar in (True, False):
            for ohne_sperre in (False, True):
                for faktor, vorlauf in ((1.0, True), (2.0, True), (2.0, False), (1e9, False)):
                    gefunden = wahl(ohne_sperre, self.standorte[0].reichweite_m * faktor,
                                    vorlauf, sichtbar)
                    if gefunden is not None:
                        st, dist = gefunden
                        reichweite = max(st.reichweite_m * 1.25, dist * 1.15)
                        return st, reichweite
        return None, 0.0

    def _schuss_zu_ende(self, auto: Auto) -> bool:
        st = self.standort
        if st is None:
            return True
        dist = math.hypot(st.pos[0] - auto.x, st.pos[1] - auto.y)
        if dist > self._schuss_reichweite:
            return True
        s_auto = self.kurs.bogen_bei(auto.x, auto.y)
        if self.kurs.vor_vorzeichen(s_auto, st.bogen_m) < -self.VORBEI_M:
            return True
        return False

    def _neuer_schuss(self, autos: list[Auto]) -> None:
        if self.ziel_kennung is not None:
            self._gezeigt[self.ziel_kennung] = self._uhr
        ziel = self.waehle_ziel(autos)
        if ziel is None:
            return
        st, reichweite = self.waehle_standort(ziel)
        if st is None:
            return
        gleich = (self.standort is not None and st.nr == self.standort.nr
                  and ziel.kennung == self.ziel_kennung)
        self.ziel_kennung = ziel.kennung
        self.schuss_alter = 0.0
        self._verdeckt_s = 0.0
        self._schuss_reichweite = reichweite
        if gleich:
            return                                  # derselbe Blick laeuft weiter
        self.standort = st
        self._benutzt[st.nr] = self._uhr
        self.schnitte += 1
        self._schnitt_setzen(ziel)

    def _schnitt_setzen(self, ziel: Auto) -> None:
        st = self.standort
        punkt = self._blickpunkt(ziel)
        dist = float(np.linalg.norm(punkt - st.pos))
        self.kamera.setzen(st.pos, punkt, self._wunsch_fov(dist))

    # -- Kamera ------------------------------------------------------------
    @staticmethod
    def _blickpunkt(auto: Auto) -> np.ndarray:
        vor = 0.25 * auto.tempo
        return np.array([auto.x + math.cos(auto.gier) * vor,
                         auto.y + math.sin(auto.gier) * vor, 0.9])

    @staticmethod
    def _wunsch_fov(dist: float) -> float:
        """Maessiger Zoom: fern enger, nah weit (22-50 Grad)."""
        breite = 12.0
        return float(min(50.0, max(22.0, 2.0 * math.degrees(math.atan2(breite, max(dist, 1.0))))))

    def aktualisieren(self, dt: float, autos: list[Auto]) -> None:
        """Einen Schritt: schneiden, wenn es dran ist, und dem Ziel folgen."""
        dt = max(0.0, float(dt))
        self._uhr += dt
        if not autos or not self.standorte:
            return
        ziel = next((a for a in autos if a.kennung == self.ziel_kennung), None)
        if self.standort is None or ziel is None:
            self.schuss_alter = 0.0
            self._neuer_schuss(autos)           # Ziel weg oder noch nichts: sofort
            ziel = next((a for a in autos if a.kennung == self.ziel_kennung), None)
            if ziel is None:
                return
        else:
            self.schuss_alter += dt
            # Verdeckt ein Objekt das Ziel laenger als einen Moment, wird geschnitten.
            self._verdeckt_s = 0.0 if self.sieht(self.standort, ziel) else self._verdeckt_s + dt
            if self.schuss_alter >= self.MIN_SCHUSS_S and (
                    self._schuss_zu_ende(ziel) or self.schuss_alter >= self.MAX_SCHUSS_S
                    or self._verdeckt_s >= self.VERDECKT_SCHNITT_S):
                self._neuer_schuss(autos)
                ziel = next((a for a in autos if a.kennung == self.ziel_kennung), ziel)
        # Folgen: weich, aber nah am Auto schneller, sonst fliegt es aus dem Bild.
        st = self.standort
        punkt = self._blickpunkt(ziel)
        dist = float(np.linalg.norm(punkt - st.pos))
        rate = 10.0 if dist < 30.0 else 6.5
        a = _glatt_faktor(rate, dt)
        self.kamera._ziel = self.kamera._ziel + (punkt - self.kamera._ziel) * a
        fov = self.kamera.sichtfeld_grad
        self.kamera.sichtfeld_grad = fov + (self._wunsch_fov(dist) - fov) * _glatt_faktor(2.5, dt)


# ---------------------------------------------------------------------------
# Eine Ansicht: Auszoomen, dann Regie
# ---------------------------------------------------------------------------

class Film:
    """Die Kamera einer Bildhaelfte (oder des ganzen Bildes) im Movie-Modus."""

    #: So weit hinter und ueber dem Auto endet das Auszoomen.
    AUSZOOM_HINTEN_M = 24.0
    AUSZOOM_HOCH_M = 9.0

    def __init__(self, regie: Regie, *, auszoom_s: float = AUSZOOM_S,
                 fov_basis: float = 55.0, hoehe_fn=None, platz: int = 0,
                 kennung: int | None = None) -> None:
        self.regie = regie
        self.auszoom_s = float(auszoom_s)
        self.fov_basis = float(fov_basis)
        self.hoehe_fn = hoehe_fn
        #: Platz im Ziel, fuer das Banner.
        self.platz = int(platz)
        #: Welches Auto zuschaut (fuer die Anzeige).
        self.kennung = kennung
        #: Wem die Regie gerade folgt (fuer die Anzeige).
        self.ziel_name = ""
        self.t = 0.0
        self.phase = "zoom" if self.auszoom_s > 0.0 else "regie"
        self._zoom_kamera = FilmKamera(sichtfeld_grad=self.fov_basis)

    @property
    def kamera(self) -> FilmKamera:
        return self._zoom_kamera if self.phase == "zoom" else self.regie.kamera

    def _boden(self, x: float, y: float) -> float:
        if self.hoehe_fn is None:
            return 0.0
        return float(np.atleast_1d(self.hoehe_fn(np.array([x]), np.array([y])))[0])

    def aktualisieren(self, dt: float, chase_auge, chase_ziel,
                      eigen: Auto | None, autos: list[Auto]) -> FilmKamera:
        self.t += max(0.0, float(dt))
        if self.phase == "zoom":
            if eigen is None or self.t >= self.auszoom_s:
                self.phase = "regie"
            else:
                u = sanft(self.t / self.auszoom_s)
                auto = np.array([eigen.x, eigen.y, 0.0])
                hinten = auto - np.array([math.cos(eigen.gier), math.sin(eigen.gier), 0.0]) \
                    * self.AUSZOOM_HINTEN_M
                hinten[2] = max(self.AUSZOOM_HOCH_M,
                                self._boden(hinten[0], hinten[1]) + 4.0)
                chase_auge = np.asarray(chase_auge, dtype=np.float64)
                chase_ziel = np.asarray(chase_ziel, dtype=np.float64)
                auge = chase_auge + (hinten - chase_auge) * u
                ziel_ende = auto + np.array([0.0, 0.0, 1.0])
                ziel = chase_ziel + (ziel_ende - chase_ziel) * u
                fov = self.fov_basis + (self.fov_basis * 0.85 - self.fov_basis) * u
                self._zoom_kamera.setzen(auge, ziel, fov)
        if self.phase == "regie":
            self.regie.aktualisieren(dt, autos)
        return self.kamera


# ---------------------------------------------------------------------------
# Die Uhr
# ---------------------------------------------------------------------------

@dataclass
class Nachspiel:
    """Wann der Film endet und die Ergebnisse kommen.

    ``feld_fertig()`` startet die Uhr, sobald alle im Ziel oder DNF sind
    (mehrfach aufrufbar). ``ueberspringen()`` beendet den Film sofort.
    ``bereit`` sagt, dass es zu den Ergebnissen gehen darf.
    """

    nachlauf_s: float = NACHLAUF_S
    rest: float | None = None
    uebersprungen: bool = False

    def feld_fertig(self) -> None:
        if self.rest is None:
            self.rest = float(self.nachlauf_s)

    def tick(self, dt: float) -> None:
        if self.rest is not None and self.rest > 0.0:
            self.rest = max(0.0, self.rest - max(0.0, float(dt)))

    def ueberspringen(self) -> None:
        self.uebersprungen = True

    @property
    def laeuft(self) -> bool:
        return self.rest is not None

    @property
    def bereit(self) -> bool:
        return self.uebersprungen or (self.rest is not None and self.rest <= 0.0)
