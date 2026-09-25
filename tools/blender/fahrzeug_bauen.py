"""Fahrzeuge in Blender bauen: Karosserie und vier Räder als eigene Knoten.

Aufruf (siehe ``tools/blender/bauen.bat``)::

    blender.exe -b -P tools/blender/fahrzeug_bauen.py -- --fahrzeug alle
    blender.exe -b -P tools/blender/fahrzeug_bauen.py -- --fahrzeug rookie \
        --ausgabe ordner --vorschau ordner --draufsicht ordner

Ergebnis je Fahrzeug:

* ``assets/vehicles/<key>.glb`` mit den Knoten ``karosserie``, ``rad_vl``,
  ``rad_vr``, ``rad_hl``, ``rad_hr`` und ``sattel_vl`` … ``sattel_hr``. Jedes
  Rad hat seinen Ursprung in der Nabenmitte und steht schon an seinem Platz.
* ``assets/vehicles/<key>_teile.json`` im Format, das
  ``src/render3d/vehicle_node.teile_lesen`` liest.

Maße kommen aus ``data/vehicles/<key>.json`` (Länge und Breite aus den
Sprite-Pixeln mal ``M_PER_PX``, Radstand und Raddurchmesser aus ``physics``),
die Form aus ``tools/blender/fahrzeuge.json``.

**Koordinaten der Parameter.** Längs läuft ``u`` von 0 (Heck) bis 1 (Front)
über die *ganze* Sprite-Länge, quer ``v`` von -1 (rechts) bis +1 (links) über
die ganze Sprite-Breite — genau so, wie man es im Sprite abliest (Front nach
rechts, linke Wagenseite oben). Höhen stehen in Metern. Ein Punkt ``(u, v)``
aus dem Sprite landet damit ohne Umrechnung an der richtigen Stelle.

**Wie die Karosserie entsteht.** Ein einziger Loft entlang der Längsachse. Jeder
Querschnitt ist ein Linienzug durch acht Stützpunkte — Boden, Schweller,
breiteste Stelle, Schulter, Scheibenfuß, Dachkante, Dachmitte — mit
gerundeten Ecken (Bézier-Verrundungen mit fester Punktzahl). Ober­halb der
Schulter folgt der Querschnitt der Haube (``deck`` + ``haube``) oder, wo die
Dachkurve ``kabine.dach`` darüber liegt, dem Glashaus. Frontscheibe,
Heckscheibe und Seitenfenster sind damit Teil derselben Haut, ohne Stufe.

**Zonen.** Alles, was eine eigene Farbe oder Vertiefung hat — Scheiben,
Leuchten, Lufteinlässe, Livree, Fugen — ist ein Polygon in einer der Ansichten
``oben`` (u, v), ``seite`` (u, z), ``vorn``/``hinten`` (v, z). Die Haut wird
entlang der Polygonkanten mit senkrechten Ebenen aufgeschnitten
(``bmesh.ops.bisect_plane``), die Flächen darin bekommen ihr Material und auf
Wunsch Stufen (``inset_region``: Rahmen, Vertiefung, Erhöhung) und Lamellen.
So lassen sich Formen direkt aus dem Sprite abnehmen, und die Kanten bleiben
sauber, egal wie grob das Netz darunter ist.

**Teile-Bibliothek.** Mit einem Block ``"teile"`` in der Fahrzeugdatei kommen
Detailteile aus ``teile.py``, ``teile_rad.py`` und ``teile_innen.py``:
Leuchteneinheiten und Gitter in Zonen (``leuchte``, ``gitter``), Fugen,
Profilreifen, Felgen mit Muttern, Bremsscheibe und Sattel, Spiegel, Griffe,
Wischer, Profilflügel, Diffusor, Endrohre, Innenraum, Kennzeichen, erfundene
Embleme. Ohne den Block baut ein Fahrzeug genau wie vorher. Die Parameter
stehen im Kopf von ``teile.py``.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemeinsam as g  # noqa: E402
import teile as tb  # noqa: E402
import teile_innen as ti  # noqa: E402
import teile_rad as tr  # noqa: E402

M_PER_PX = 0.08          # wie src/core/settings.py
PARAMETER = Path(__file__).resolve().parent / "fahrzeuge.json"
ZIEL = g.WURZEL / "assets" / "vehicles"

RADNAMEN = {"vl": (1, 1), "vr": (1, -1), "hl": (-1, 1), "hr": (-1, -1)}

#: Materialplätze der Karosserie, in dieser Reihenfolge.
KAROSSERIE_MATS = ["lack", "lack2", "kunststoff", "glas", "licht_vorn", "scheinwerferglas",
                   "licht_hinten", "blinker", "chrom", "carbon", "zierteil", "dekor_weiss",
                   "innenraum", "kennzeichen"]

#: Kennziffern der Querschnittsabschnitte (Flächenattribut ``seg``).
SEG_BODEN, SEG_SCHWELLER, SEG_FLANKE_U, SEG_FLANKE_O = 0, 1, 2, 3
SEG_HAUBE, SEG_FENSTER, SEG_DACH, SEG_FRONT, SEG_HECK = 4, 5, 6, 8, 9


# ---------------------------------------------------------------------------
# Kurven
# ---------------------------------------------------------------------------

def kurve(punkte, u: float) -> float:
    """Monotone kubische Interpolation (Fritsch-Carlson) durch ``[[u, wert]]``.

    Monoton, damit eine Dachlinie zwischen zwei gleich hohen Punkten nicht
    ausbeult — Catmull-Rom würde über- und unterschwingen.
    """
    p = sorted(punkte)
    xs = [a for a, _ in p]
    ys = [b for _, b in p]
    if u <= xs[0]:
        return ys[0]
    if u >= xs[-1]:
        return ys[-1]
    n = len(xs)
    d = [(ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0] * (n - 2) + [d[-1]]
    for i in range(1, n - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0.0
        else:
            m[i] = 2.0 / (1.0 / d[i - 1] + 1.0 / d[i])
    for i in range(n - 1):
        if xs[i] <= u <= xs[i + 1]:
            h = xs[i + 1] - xs[i]
            t = (u - xs[i]) / h
            h00 = 2 * t ** 3 - 3 * t ** 2 + 1
            h10 = t ** 3 - 2 * t ** 2 + t
            h01 = -2 * t ** 3 + 3 * t ** 2
            h11 = t ** 3 - t ** 2
            return h00 * ys[i] + h10 * h * m[i] + h01 * ys[i + 1] + h11 * h * m[i + 1]
    return ys[-1]


def wert(w, u: float, standard: float = 0.0) -> float:
    """Ein Parameter, der entweder eine Zahl oder eine Kurve ``[[u, w]]`` ist."""
    if w is None:
        return standard
    if isinstance(w, (int, float)):
        return float(w)
    return kurve(w, u)


def sp(wert_: float, exponent: float) -> float:
    """Vorzeichenerhaltende Potenz für Superellipsen."""
    return math.copysign(abs(wert_) ** exponent, wert_)


def bezier(a, k, b, t):
    s = 1 - t
    return (s * s * a[0] + 2 * s * t * k[0] + t * t * b[0],
            s * s * a[1] + 2 * s * t * k[1] + t * t * b[1])


def abstand2(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# Grundformen stehen in teile.py (Teile-Bibliothek), damit die Teile sie
# ohne Kreisimport nutzen können.
from teile import (auf_flaeche, kasten, kugel, netz_aus_ringen, platte, strahl,  # noqa: E402
                   zylinder_x, zylinder_y)


# ---------------------------------------------------------------------------
# Materialien
# ---------------------------------------------------------------------------

def materialien(p):
    lack = p["lack"]
    lack2 = p.get("lack2", [18, 18, 20])
    fl = p.get("felgenfarbe", [200, 202, 205])
    return {
        "lack": g.material("lack", [c / 255 for c in lack], 0.0, 0.3, klarlack=1.0),
        "lack2": g.material("lack2", [c / 255 for c in lack2], 0.0, 0.32, klarlack=1.0),
        "glas": g.material("glas", (0.05, 0.06, 0.075), 0.0, 0.03, alpha=0.8),
        "chrom": g.material("chrom", (0.92, 0.92, 0.93), 1.0, 0.08),
        "felge": g.material("felge", [c / 255 for c in fl], 1.0, p.get("felgenrauheit", 0.22)),
        "gummi": g.material("gummi", (0.07, 0.07, 0.075), 0.0, 0.88),
        "kunststoff": g.material("kunststoff", (0.05, 0.05, 0.055), 0.0, 0.62),
        "innenraum": g.material("innenraum", (0.09, 0.085, 0.08), 0.0, 0.8),
        "licht_vorn": g.material("licht_vorn", (0.95, 0.96, 1.0), 0.0, 0.05,
                                 emission=(1.0, 0.98, 0.92), staerke=1.5),
        "scheinwerferglas": g.material("scheinwerferglas", (0.55, 0.58, 0.62), 0.8, 0.06),
        "licht_hinten": g.material("licht_hinten", (0.55, 0.02, 0.02), 0.0, 0.1,
                                   emission=(1.0, 0.05, 0.03), staerke=1.6),
        "blinker": g.material("blinker", (0.9, 0.45, 0.05), 0.0, 0.1,
                              emission=(1.0, 0.5, 0.05), staerke=0.6),
        "bremse": g.material("bremse", (0.45, 0.45, 0.46), 1.0, 0.45),
        "sattel": g.material("sattel", [c / 255 for c in p.get("sattelfarbe", [60, 60, 64])],
                             0.0, 0.35),
        "kennzeichen": g.material("kennzeichen", (0.93, 0.93, 0.9), 0.0, 0.4),
        "schrift": g.material("schrift", (0.02, 0.02, 0.02), 0.0, 0.5),
        # Sichtcarbon: dunkel, mit Klarlack, leicht metallisch schimmernd.
        "carbon": g.material("carbon", (0.075, 0.078, 0.085), 0.35, 0.32, klarlack=1.0),
        # Hochglanzschwarze Zierteile (Säulen, Spiegelkappen, Blenden).
        "zierteil": g.material("zierteil", (0.025, 0.025, 0.03), 0.0, 0.12, klarlack=1.0),
        # Feste weiße Folie (Livree-Elemente, die beim Umlackieren bleiben).
        "dekor_weiss": g.material("dekor_weiss", (0.93, 0.93, 0.94), 0.0, 0.3, klarlack=1.0),
        # Leuchtenabdeckungen der Teile-Bibliothek (durchsichtig wie "glas").
        "klarglas": g.material("klarglas", (0.55, 0.6, 0.65), 0.0, 0.02, alpha=0.1),
        "streuscheibe": g.material("streuscheibe", (0.62, 0.02, 0.03), 0.0, 0.05, alpha=0.62),
    }


# ---------------------------------------------------------------------------
# Maße und Form
# ---------------------------------------------------------------------------

class Masse:
    """Sollmaße aus der Spieldatei plus abgeleitete Größen."""

    def __init__(self, key: str, p: dict) -> None:
        with open(g.WURZEL / "data" / "vehicles" / f"{key}.json", encoding="utf-8") as fh:
            daten = json.load(fh)
        phys = daten["physics"]
        self.laenge = daten["height_px"] * M_PER_PX
        self.breite_gesamt = daten["width_px"] * M_PER_PX
        self.breite = self.breite_gesamt * max(v for _, v in p["breite"])
        self.radstand = float(phys["wheelbase"])
        self.rad_d = float(phys["wheel_diameter"])
        self.rad_r = self.rad_d / 2
        self.reifen_b = p.get("reifenbreite_m", 0.235)
        self.hoehe = 1.4
        mitte = self.x(p.get("achsmitte_u", 0.5))
        self.achse_vorn = mitte + self.radstand / 2
        self.achse_hinten = mitte - self.radstand / 2
        aussen = p.get("reifen_v", max(v for _, v in p["breite"]) - 0.03) * self.breite_gesamt / 2
        self.spur_halb = aussen - self.reifen_b / 2

    def x(self, u: float) -> float:
        return -self.laenge / 2 + u * self.laenge

    def u(self, x: float) -> float:
        return (x + self.laenge / 2) / self.laenge

    def y(self, v: float) -> float:
        return v * self.breite_gesamt / 2


class Form:
    """Der Querschnitt der Karosserie an jeder Längsstelle."""

    def __init__(self, p: dict, ms: Masse) -> None:
        self.p = p
        self.ms = ms
        self.k = p["kabine"]
        self.u0, self.u1 = p.get("koerper_u", [0.0, 1.0])
        dach = self.k["dach"]
        self.dach_u0 = min(a for a, _ in dach)
        self.dach_u1 = max(a for a, _ in dach)

    # -- Grundgrößen ---------------------------------------------------------
    def w(self, u):
        return self.ms.y(kurve(self.p["breite"], u))

    def zu(self, u):
        return kurve(self.p["unten"], u)

    def zd(self, u):
        return kurve(self.p["deck"], u)

    def zh(self, u):
        return self.zd(u) + wert(self.p.get("haube"), u, 0.03)

    def ws(self, u):
        return self.w(u) * (1 - wert(self.p.get("schulter_einzug"), u, 0.06))

    def wg(self, u):
        return min(self.ms.y(wert(self.k.get("basis_v"), u, 0.8)), self.ws(u) - 0.02)

    def wr(self, u):
        return min(self.ms.y(wert(self.k.get("dach_v"), u, 0.6)), self.wg(u) - 0.05)

    def zr(self, u):
        """Dachmitte, wo die Dachkurve gilt, sonst None."""
        if not (self.dach_u0 <= u <= self.dach_u1):
            return None
        z = kurve(self.k["dach"], u)
        d = self.k.get("dach_versatz_m", 0.0)
        if d:
            enden = min(self.k["dach"][0][1], self.k["dach"][-1][1])
            spitze = max(b for _, b in self.k["dach"])
            z += d * max(0.0, (z - enden) / max(spitze - enden, 1e-3))
        return z

    # -- Flächen -------------------------------------------------------------
    def T(self, u, y):
        """Haube bzw. Kofferraumdeckel: Höhe bei Querlage ``y``."""
        ws = self.ws(u)
        q = min(1.0, abs(y) / max(ws, 1e-3))
        k = wert(self.p.get("haube_form"), u, 2.0)
        return self.zd(u) + (self.zh(u) - self.zd(u)) * (1 - q ** k)

    def G(self, u, y):
        """Glashaus bei Querlage ``y`` (oder -unendlich, wo keins ist)."""
        zr = self.zr(u)
        if zr is None:
            return -1e9
        wr, wg = self.wr(u), self.wg(u)
        dk = wert(self.k.get("dach_woelbung"), u, 0.04)
        ay = abs(y)
        if ay <= wr:
            return zr - dk * (ay / wr) ** 2
        if ay <= wg:
            z_kante = zr - dk
            z_fuss = self.T(u, wg)
            t = (ay - wr) / max(wg - wr, 1e-4)
            return z_kante + (z_fuss - z_kante) * t
        return -1e9

    def oben(self, u, y):
        """Oberseite: Haube und Glashaus, mit weicher Kehle dazwischen.

        Ein hartes ``max`` ergäbe am Scheibenfuß einen Knick, der schräg durch
        das Netz läuft und treppig schattiert. Das glatte Maximum rundet ihn
        mit ``kehle_m`` aus; die Scheibe selbst beginnt erst darüber (Zone).
        """
        a, b = self.T(u, y), self.G(u, y)
        k = self.k.get("kehle_m", 0.05)
        if b < a - k:
            return a
        if a < b - k:
            return b
        h = 0.5 + 0.5 * (b - a) / k
        return a * (1 - h) + b * h + k * h * (1 - h)

    def im_glashaus(self, x, y, z, rand=0.012) -> bool:
        u = self.ms.u(x)
        return z > self.T(u, y) + rand

    # -- Querschnitt ---------------------------------------------------------
    def profil(self, u):
        """Linke Hälfte des Querschnitts: Punkte (y, z) von unten Mitte bis
        oben Mitte, dazu der Abschnitt je Intervall."""
        p, k = self.p, self.k
        w, ws, wg, wr = self.w(u), self.ws(u), self.wg(u), self.wr(u)
        zu, zd = self.zu(u), self.zd(u)
        zw = zu + wert(p.get("breitste_stelle"), u, 0.5) * (zd - zu)
        sh = min(wert(p.get("schweller_h"), u, 0.1), 0.35 * (zw - zu))
        schluessel = [
            (0.0, zu),
            (w * wert(p.get("boden"), u, 0.84), zu),
            (w * wert(p.get("schweller_v"), u, 0.965), zu + sh),
            (w, zw),
            (ws, zd),
            (wg, self.T(u, wg)),
            (wr, self.oben(u, wr)),
            (0.0, self.oben(u, 0.0)),
        ]

        def haube(t):
            y = ws + (wg - ws) * t
            return (y, self.T(u, y))

        def fenster(t):
            y = wg + (wr - wg) * t
            return (y, self.oben(u, y))

        def dach(t):
            y = wr * (1 - t)
            return (y, self.oben(u, y))

        # Optional mehr Punkte je Abschnitt (für Sicken an der Flanke); ohne
        # Angabe bleibt es bei der bisherigen Punktzahl.
        anzahl = p.get("profil_punkte", [2, 1, 3, 3, 4, 3, 6])
        segmente = [(anzahl[0], None), (anzahl[1], None), (anzahl[2], None), (anzahl[3], None),
                    (anzahl[4], haube), (anzahl[5], fenster), (anzahl[6], dach)]
        rundungen = [
            None,
            (wert(p.get("boden_radius"), u, 0.04), 3),
            (wert(p.get("schweller_radius"), u, 0.05), 3),
            (wert(p.get("seiten_radius"), u, 0.25), 5),
            (wert(p.get("schulter_radius"), u, 0.05), 5),
            (wert(k.get("fuss_radius"), u, 0.02), 3),
            (wert(k.get("dachkante_radius"), u, 0.06), 5),
            None,
        ]
        punkte, abschnitt = verrundeter_linienzug(schluessel, segmente, rundungen)
        if p.get("sicken"):
            punkte = self.sicken_praegen(u, punkte, abschnitt)
        return punkte, abschnitt

    def sicken_praegen(self, u, punkte, abschnitt):
        """Charakterlinien an der Flanke: ein schmaler Grat, der nach außen steht.

        ``sicken``: Liste aus ``{"z": Höhe, "tiefe": Überstand, "breite":
        halbe Breite}`` — Höhe und Überstand dürfen Kurven über u sein, so
        läuft eine Sicke vorn und hinten weich aus. Oben endet der Grat
        steiler als unten (``oben_anteil``): so fängt die Kante das Licht wie
        eine gekantete Blechfalz.
        """
        neu = list(punkte)
        for s in self.p["sicken"]:
            zs = wert(s["z"], u, 0.7)
            t_ = wert(s.get("tiefe"), u, 0.01)
            if abs(t_) < 1e-5:
                continue
            b = s.get("breite", 0.05)
            oben = b * s.get("oben_anteil", 0.45)
            for i in range(1, len(punkte) - 1):
                if abschnitt[i - 1] not in (SEG_FLANKE_U, SEG_FLANKE_O) and \
                        abschnitt[min(i, len(abschnitt) - 1)] not in (SEG_FLANKE_U, SEG_FLANKE_O):
                    continue
                y, z = neu[i]
                d = z - zs
                if -b < d <= 0:
                    f = (1 + d / b) ** 2
                elif 0 < d < oben:
                    f = (1 - d / oben) ** 1.5
                else:
                    continue
                neu[i] = (y + t_ * f, z)
        return neu


def verrundeter_linienzug(schluessel, segmente, rundungen):
    """Linienzug durch Stützpunkte mit Bézier-Verrundungen und fester Punktzahl.

    ``segmente``: je Abschnitt (Punkte im Inneren, Kurve oder None für
    gerade). ``rundungen``: je Stützpunkt ``(radius, punkte)`` oder None. Die
    Punktzahl hängt nicht von der Form ab — aufeinanderfolgende Querschnitte
    lassen sich deshalb immer verbinden.
    """
    n_s = len(schluessel)
    # Abschnitte fein abtasten, um Bogenlängen zu kennen.
    fein = []
    for i, (_n, f) in enumerate(segmente):
        a, b = schluessel[i], schluessel[i + 1]
        pts = []
        for j in range(33):
            t = j / 32
            pts.append(f(t) if f else (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        pts[0], pts[-1] = a, b
        s = [0.0]
        for j in range(1, len(pts)):
            s.append(s[-1] + abstand2(pts[j - 1], pts[j]))
        fein.append((pts, s))

    def bei(i, laenge):
        pts, s = fein[i]
        laenge = max(0.0, min(s[-1], laenge))
        for j in range(1, len(s)):
            if s[j] >= laenge:
                t = (laenge - s[j - 1]) / max(s[j] - s[j - 1], 1e-9)
                a, b = pts[j - 1], pts[j]
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        return pts[-1]

    radien = [0.0] * n_s
    for j in range(1, n_s - 1):
        if rundungen[j]:
            r = rundungen[j][0]
            r = min(r, 0.42 * fein[j - 1][1][-1], 0.42 * fein[j][1][-1])
            radien[j] = max(r, 1e-3)

    punkte, abschnitt = [schluessel[0]], []
    for i, (n, _f) in enumerate(segmente):
        laenge = fein[i][1][-1]
        a = radien[i]
        b = laenge - radien[i + 1]
        for j in range(1, n + 1):
            punkte.append(bei(i, a + (b - a) * j / (n + 1)))
            abschnitt.append(i)
        ende = i + 1
        if ende < n_s - 1 and rundungen[ende]:
            m = rundungen[ende][1]
            A = bei(i, laenge - radien[ende])
            B = bei(ende, radien[ende])
            K = schluessel[ende]
            haelfte = (m - 1) // 2
            for j in range(m):
                t = j / (m - 1)
                punkte.append(bezier(A, K, B, t))
                abschnitt.append(i if j <= haelfte else ende)
        else:
            punkte.append(schluessel[ende])
            abschnitt.append(i)
    # abschnitt[k] gehört zum Intervall punkte[k] → punkte[k+1]
    return punkte, abschnitt


def stationen(u0: float, u1: float, n: int) -> list[float]:
    """Stationen dichter an den Enden, wo sich die Form am schnellsten ändert."""
    return [u0 + (u1 - u0) * (0.5 * (i / (n - 1)) + 0.5 * (0.5 - 0.5 * math.cos(math.pi * i / (n - 1))))
            for i in range(n)]


# ---------------------------------------------------------------------------
# Karosserie: Loft
# ---------------------------------------------------------------------------

def haut_bauen(fo: Form, p):
    """Die Karosseriehaut als BMesh, mit Abschnittskennung je Fläche."""
    ms = fo.ms
    bm = bmesh.new()
    seg = bm.faces.layers.int.new("seg")
    bm.faces.layers.int.new("zone")
    buckel_v = p.get("front_buckel_m", 0.06)
    buckel_h = p.get("heck_buckel_m", 0.05)
    ua = fo.u0 + buckel_h / ms.laenge
    ub = fo.u1 - buckel_v / ms.laenge
    us = stationen(ua, ub, p.get("stationen", 120))
    ringe = []
    abschn = None
    for u in us:
        links, abschn = fo.profil(u)
        x = ms.x(u)
        rechts = [(-y, z) for (y, z) in reversed(links[1:-1])]
        ringe.append([bm.verts.new((x, y, z)) for (y, z) in links + rechts])
    n_links = len(abschn)                         # Intervalle links
    r = len(ringe[0])
    seg_ring = []
    for j in range(r):
        if j < n_links:
            seg_ring.append(abschn[j])
        else:
            seg_ring.append(abschn[2 * n_links - 1 - j])
    for i in range(len(ringe) - 1):
        a, b = ringe[i], ringe[i + 1]
        for j in range(r):
            f = bm.faces.new((a[j], a[(j + 1) % r], b[(j + 1) % r], b[j]))
            f[seg] = seg_ring[j]
    kappe(bm, ringe[-1], +1, buckel_v, SEG_FRONT, seg)
    kappe(bm, ringe[0], -1, buckel_h, SEG_HECK, seg)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    i_kunst = KAROSSERIE_MATS.index("kunststoff")
    for f in bm.faces:
        if f[seg] == SEG_BODEN:
            f.material_index = i_kunst
    return bm


def kappe(bm, ring, richtung: int, buckel: float, kennung: int, seg) -> None:
    """Ein Ende des Lofts als flache Kuppel schließen."""
    co = [v.co.copy() for v in ring]
    z0 = min(c.z for c in co)
    z1 = max(c.z for c in co)
    zc = z0 + 0.45 * (z1 - z0)
    vorher = ring
    for s in (0.86, 0.66, 0.44, 0.22):
        d = buckel * math.sqrt(1 - s * s)
        neu = [bm.verts.new((c.x + richtung * d, c.y * s, zc + (c.z - zc) * s)) for c in co]
        n = len(neu)
        for j in range(n):
            f = bm.faces.new((vorher[j], vorher[(j + 1) % n], neu[(j + 1) % n], neu[j]))
            f[seg] = kennung
        vorher = neu
    mitte = bm.verts.new((co[0].x + richtung * buckel, 0.0, zc))
    n = len(vorher)
    for j in range(n):
        f = bm.faces.new((vorher[j], vorher[(j + 1) % n], mitte))
        f[seg] = kennung


# ---------------------------------------------------------------------------
# Zonen
# ---------------------------------------------------------------------------

ACHSEN = tb.ACHSEN


def zone_polygone(z: dict, ms: Masse):
    """Die Polygone einer Zone in Weltkoordinaten ihrer Ansicht."""
    ansicht = z["ansicht"]
    roh = [list(map(float, q)) for q in z["punkte"]]
    if z.get("symmetrisch"):
        roh = roh + [[a, -b] for a, b in reversed(roh) if abs(b) > 1e-6]
    listen = []
    if "linie" in z:
        # Ein Linienzug gegebener Breite als Kette schmaler Vierecke.
        b = z["linie"] / 2
        welt = [welt_punkt(q, ansicht, ms) for q in roh]
        for i in range(len(welt) - 1):
            a, c = welt[i], welt[i + 1]
            d = (c[0] - a[0], c[1] - a[1])
            lg = math.hypot(*d) or 1e-9
            n = (-d[1] / lg * b, d[0] / lg * b)
            e = (d[0] / lg * b * 0.5, d[1] / lg * b * 0.5)
            listen.append([(a[0] - e[0] + n[0], a[1] - e[1] + n[1]),
                           (c[0] + e[0] + n[0], c[1] + e[1] + n[1]),
                           (c[0] + e[0] - n[0], c[1] + e[1] - n[1]),
                           (a[0] - e[0] - n[0], a[1] - e[1] - n[1])])
    else:
        listen.append([welt_punkt(q, ansicht, ms) for q in roh])
    if z.get("spiegeln") and ansicht != "seite":
        # Seitenansicht trifft ohnehin beide Flanken.
        if ansicht == "oben":
            listen += [[(a, -b) for a, b in poly] for poly in list(listen)]
        else:
            listen += [[(-a, b) for a, b in poly] for poly in list(listen)]
    return listen


def welt_punkt(q, ansicht, ms: Masse):
    if ansicht == "oben":
        return (ms.x(q[0]), ms.y(q[1]))
    if ansicht == "seite":
        return (ms.x(q[0]), q[1])
    return (ms.y(q[0]), q[1])


def im_polygon(pt, poly) -> bool:
    x, y = pt
    drin = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            drin = not drin
        j = i
    return drin


def zonen_anwenden(bm, fo: Form, zonen: list, mats) -> dict:
    """Alle Zonen schneiden und einfärben, danach Stufen und Lamellen.

    Liefert je Leuchtenzone (Nummer ab 1) die Haut vor dem Vertiefen, aus der
    ``leuchten_bauen`` die Abdeckscheibe macht.
    """
    ms = fo.ms
    seg = bm.faces.layers.int["seg"]
    zl = bm.faces.layers.int["zone"]
    idx = {n: i for i, n in enumerate(KAROSSERIE_MATS)}
    for nr, z in enumerate(zonen, start=1):
        ansicht = z["ansicht"]
        ia, ib, ic = ACHSEN[ansicht]
        n_min = z.get("n_min", {"oben": -0.2, "seite": 0.3, "vorn": 0.15, "hinten": 0.15}[ansicht])
        auf = {idx[m] for m in z.get("auf", ["lack", "lack2"])}
        segs = set(z["segmente"]) if "segmente" in z else None
        zlim = z.get("z")
        ulim = z.get("u")

        def passt(f):
            if f.material_index not in auf:
                return False
            if segs is not None and f[seg] not in segs:
                return False
            f.normal_update()
            n = f.normal
            if ansicht == "oben" and n.z < n_min:
                return False
            if ansicht == "seite" and abs(n.y) < n_min:
                return False
            if ansicht == "vorn" and n.x < n_min:
                return False
            if ansicht == "hinten" and -n.x < n_min:
                return False
            c = f.calc_center_median()
            if z.get("nur_gh") and not fo.im_glashaus(c.x, c.y, c.z):
                return False
            if z.get("ohne_gh") and fo.im_glashaus(c.x, c.y, c.z):
                return False
            return True

        haupt = zone_polygone(z, ms)
        zusatz = []
        for e in z.get("und", []):
            ez = dict(e)
            ez.setdefault("spiegeln", z.get("spiegeln", False))
            zusatz.append((ACHSEN[ez["ansicht"]], zone_polygone(ez, ms)))
        for i_poly, poly in enumerate(haupt):
            # Alle Prismen, deren Schnitt die Zone bildet: (Achse a, Achse b, Polygon)
            prismen = [(ia, ib, poly)]
            for (ea, eb, _ec), polys in zusatz:
                prismen.append((ea, eb, polys[min(i_poly, len(polys) - 1)]))
            a0 = min(q[0] for q in poly) - 0.02
            a1 = max(q[0] for q in poly) + 0.02
            b0 = min(q[1] for q in poly) - 0.02
            b1 = max(q[1] for q in poly) + 0.02

            def im_rahmen(f):
                for v in f.verts:
                    if a0 <= v.co[ia] <= a1 and b0 <= v.co[ib] <= b1:
                        return True
                return False

            kand = {f for f in bm.faces if im_rahmen(f) and passt(f)}
            if not kand:
                continue
            ebenen = []
            for pa_, pb_, pr in prismen:
                m = len(pr)
                for i in range(m):
                    pa, pb = pr[i], pr[(i + 1) % m]
                    d = (pb[0] - pa[0], pb[1] - pa[1])
                    no = [0.0, 0.0, 0.0]
                    no[pa_], no[pb_] = -d[1], d[0]
                    co = [0.0, 0.0, 0.0]
                    co[pa_], co[pb_] = pa[0], pa[1]
                    box = (pa_, pb_, min(pa[0], pb[0]) - 1e-4, max(pa[0], pb[0]) + 1e-4,
                           min(pa[1], pb[1]) - 1e-4, max(pa[1], pb[1]) + 1e-4)
                    ebenen.append((Vector(co), Vector(no).normalized(), box))
            if zlim:
                for zz, s in ((zlim[0], 1), (zlim[1], -1)):
                    ebenen.append((Vector((0, 0, zz)), Vector((0, 0, s)), None))
            if ulim:
                for uu in ulim:
                    ebenen.append((Vector((ms.x(uu), 0, 0)), Vector((1, 0, 0)), None))
            for co, no, box in ebenen:
                treffer = []
                for f in kand:
                    if not f.is_valid:
                        continue
                    ds = [(v.co - co).dot(no) for v in f.verts]
                    if min(ds) > -1e-5 or max(ds) < 1e-5:
                        continue
                    if box is not None:
                        pa = [v.co[box[0]] for v in f.verts]
                        pb = [v.co[box[1]] for v in f.verts]
                        if max(pa) < box[2] or min(pa) > box[3] or max(pb) < box[4] or min(pb) > box[5]:
                            continue
                    treffer.append(f)
                if not treffer:
                    continue
                kanten = {e for f in treffer for e in f.edges}
                punkte = {v for f in treffer for v in f.verts}
                erg = bmesh.ops.bisect_plane(bm, geom=list(treffer) + list(kanten) + list(punkte),
                                             dist=1e-6, plane_co=co, plane_no=no)
                for el in erg["geom_cut"]:
                    for f in el.link_faces:
                        kand.add(f)
                kand = {f for f in kand if f.is_valid}
            mat = idx[z["mat"]]
            for f in kand:
                if not f.is_valid or not passt(f):
                    continue
                c = f.calc_center_median()
                if not all(im_polygon((c[pa_], c[pb_]), pr) for pa_, pb_, pr in prismen):
                    continue
                if zlim and not (zlim[0] <= c.z <= zlim[1]):
                    continue
                if ulim and not (ms.x(ulim[0]) <= c.x <= ms.x(ulim[1])):
                    continue
                f.material_index = mat
                f[zl] = nr

    # Leuchten der Teile-Bibliothek: die Haut der Zone vor dem Vertiefen
    # abnehmen — daraus wird die bündige Abdeckscheibe.
    deckel = {}
    for nr, z in enumerate(zonen, start=1):
        le = z.get("leuchte")
        if le and le.get("abdeckung", "klarglas") and le.get("abdeckung") is not False:
            deckel[nr] = [[tuple(v.co) for v in f.verts] for f in bm.faces if f[zl] == nr]

    # Stufen: Rahmen, Vertiefungen, Erhöhungen.
    for nr, z in enumerate(zonen, start=1):
        stufen = z.get("stufen")
        if not stufen and z.get("leuchte"):
            le = z["leuchte"]
            stufen = [{"dicke": le.get("rand_m", 0.005), "tiefe": -le.get("tiefe_m", 0.03),
                       "rand": le.get("rand_mat", "zierteil")}]
        if not stufen:
            continue
        flaechen = [f for f in bm.faces if f[zl] == nr]
        if not flaechen:
            continue
        for st in stufen:
            # Ohne "even offset": der streckt die Dicke an spitzen Ecken mit
            # 1/sin(Winkel/2) und zieht bei schmalen Sicheln meterlange Zacken.
            erg = bmesh.ops.inset_region(bm, faces=flaechen, thickness=st.get("dicke", 0.01),
                                         depth=st.get("tiefe", 0.0), use_even_offset=False,
                                         use_boundary=True)
            for f in erg["faces"]:
                f.material_index = idx[st.get("rand", "kunststoff")]
                f[zl] = 0
    return deckel


def zone_mat(z) -> int:
    return KAROSSERIE_MATS.index(z["mat"])


def lamellen_bauen(ob_haut, fo: Form, zonen: list, mats):
    """Lamellen in Lufteinlässen: schmale Stege quer über die Öffnung."""
    ms = fo.ms
    teile = []
    for z in zonen:
        lm = z.get("lamellen")
        if not lm:
            continue
        ansicht = z["ansicht"]
        ia, ib, ic = ACHSEN[ansicht]
        for poly in zone_polygone(z, ms):
            quer = lm.get("richtung", "b") == "b"      # Stege entlang der 2. Achse
            achse = 0 if quer else 1
            lo = min(q[achse] for q in poly)
            hi = max(q[achse] for q in poly)
            n = lm.get("anzahl", 4)
            for k in range(n):
                c = lo + (hi - lo) * (k + 1) / (n + 1)
                # Schnitt der Linie mit dem Polygon
                xs = []
                m = len(poly)
                for i in range(m):
                    pa, pb = poly[i], poly[(i + 1) % m]
                    if (pa[achse] - c) * (pb[achse] - c) < 0:
                        t = (c - pa[achse]) / (pb[achse] - pa[achse])
                        xs.append(pa[1 - achse] + (pb[1 - achse] - pa[1 - achse]) * t)
                xs.sort()
                for s0, s1 in zip(xs[::2], xs[1::2]):
                    s0 += 0.006
                    s1 -= 0.006
                    if s1 - s0 < 0.02:
                        continue
                    # Stückweise setzen: nur dort, wo der Strahl wirklich in die
                    # Öffnung fällt. An einer gewölbten Front stünde ein
                    # durchgehender Steg sonst seitlich in der Luft.
                    stuecke = max(1, int(math.ceil((s1 - s0) / 0.06)))
                    lg = (s1 - s0) / stuecke
                    for k_s in range(stuecke):
                        mitte2 = [0.0, 0.0]
                        mitte2[achse] = c
                        mitte2[1 - achse] = s0 + lg * (k_s + 0.5)
                        start = [0.0, 0.0, 0.0]
                        start[ia], start[ib] = mitte2
                        richtung = [0.0, 0.0, 0.0]
                        start[ic] = -10.0 if ansicht == "hinten" else 10.0
                        richtung[ic] = 1.0 if ansicht == "hinten" else -1.0
                        ok, ort, _n, fi = ob_haut.ray_cast(Vector(start), Vector(richtung))
                        if not ok or ob_haut.data.polygons[fi].material_index != zone_mat(z):
                            continue
                        hoehe = lm.get("hoehe", 0.035)
                        groesse = [0.0, 0.0, 0.0]
                        groesse[[ia, ib][1 - achse]] = lg + 0.004
                        groesse[[ia, ib][achse]] = lm.get("dicke", 0.012)
                        groesse[ic] = hoehe
                        mitte3 = Vector(ort) - Vector(richtung) * (hoehe / 2 - 0.004)
                        spiegelbilder = [mitte3]
                        if ansicht == "seite":
                            m3 = mitte3.copy()
                            m3.y = -m3.y
                            spiegelbilder.append(m3)
                        for m3 in spiegelbilder:
                            teile.append(kasten("lamelle", m3, groesse, mats[lm.get("mat", "kunststoff")]))
    return teile


# ---------------------------------------------------------------------------
# Leuchten und Gitter der Teile-Bibliothek
# ---------------------------------------------------------------------------

def _zonenseiten(ansicht: str):
    """Seitenansichten gelten für beide Flanken, die übrigen für eine Seite."""
    return (True, False) if ansicht == "seite" else (True,)


def leuchten_bauen(ob_haut, treffer, fo: Form, zonen: list, mats, deckel: dict):
    """Leuchteneinheiten in Zonen mit ``leuchte``: Abdeckscheibe bündig auf der
    alten Haut, darunter im vertieften Gehäuse LED-Leisten und Projektoren."""
    ms = fo.ms
    teile = []
    for nr, z in enumerate(zonen, start=1):
        le = z.get("leuchte")
        if not le:
            continue
        ansicht = z["ansicht"]
        boden = {KAROSSERIE_MATS.index(z["mat"])}
        abdeckung = le.get("abdeckung", "klarglas")
        if abdeckung and deckel.get(nr):
            ob = tb.deckel("leuchtenglas", deckel[nr], mats[abdeckung])
            if ob is not None:
                teile.append(ob)
        for poly in zone_polygone(z, ms):
            for links in _zonenseiten(ansicht):
                def proj(a, b, _l=links):
                    return treffer.ansicht(ansicht, a, b, boden, _l)
                leds = le.get("led") or []
                for led in (leds if isinstance(leds, list) else [leds]):
                    teile += _led_bauen(poly, led, proj, ansicht, mats)
                if le.get("projektoren"):
                    teile += _projektoren_bauen(poly, le["projektoren"], proj, mats)
    return teile


def _led_bauen(poly, led, proj, ansicht, mats):
    mat = mats[led.get("mat", "licht_vorn")]
    breite, hoehe = led.get("breite_m", 0.007), led.get("hoehe_m", 0.004)
    wege = []
    if "ringe" in led:
        for f in led["ringe"]:
            wege.append((tb.polygon_skalieren(poly, f), True))
    elif "quer" in led:
        innen, _ = tb.polygon_einruecken(poly, led.get("abstand_m", 0.008))
        b0 = min(q[1] for q in innen)
        b1 = max(q[1] for q in innen)
        for anteil in led["quer"]:
            c = b0 + (b1 - b0) * anteil
            for s0, s1 in tb.quer_schnitte(innen, 1, c):
                wege.append(([(s0, c), (s1, c)], False))
    else:
        innen, aussen = tb.polygon_einruecken(poly, led.get("abstand_m", 0.008))
        verlauf = led.get("verlauf", "rand")
        if verlauf == "rand":
            wege.append((innen, True))
        else:
            ia, ib, _ic = ACHSEN[ansicht]
            if verlauf in ("aussen", "innen"):
                c = tb.schwerpunkt2(poly)
                y = c[1] if ansicht == "oben" else (c[0] if ansicht in ("vorn", "hinten") else 1.0)
                s = (1.0 if y >= 0 else -1.0) * (1.0 if verlauf == "aussen" else -1.0)
                d3 = (0.0, s, 0.0)
            else:
                d3 = {"oben": (0, 0, 1), "unten": (0, 0, -1), "vorn": (1, 0, 0),
                      "hinten": (-1, 0, 0)}[verlauf]
            lauf = tb.laengster_lauf(innen, aussen, (d3[ia], d3[ib]))
            if len(lauf) >= 2:
                wege.append((lauf, False))
    teile = []
    for pts, geschlossen in wege:
        dicht = tb.verdichten(list(pts) + ([pts[0]] if geschlossen else []), 0.01)
        if geschlossen:
            dicht = dicht[:-1]
        stuecke, pp, nn = [], [], []
        for a, b in dicht:
            h = proj(a, b)
            if h is None:
                if len(pp) >= 2:
                    stuecke.append((pp, nn, False))
                pp, nn = [], []
                geschlossen = False
                continue
            pp.append(h[0])
            nn.append(h[1])
        if len(pp) >= 2:
            stuecke.append((pp, nn, geschlossen))
        for pp, nn, gg in stuecke:
            ob = tb.band("led", pp, nn, breite, hoehe, mat, geschlossen=gg)
            if ob is not None:
                teile.append(ob)
    return teile


def _projektoren_bauen(poly, pj, proj, mats):
    a0, a1 = min(q[0] for q in poly), max(q[0] for q in poly)
    b0, b1 = min(q[1] for q in poly), max(q[1] for q in poly)
    n = pj.get("anzahl", 2)
    r = pj.get("radius_m", min(0.032, 0.32 * (b1 - b0)))
    rand = pj.get("rand_anteil", 0.22)
    teile = []
    for k in range(n):
        a = a0 + (a1 - a0) * (rand + (1 - 2 * rand) * (k + 0.5) / n)
        b = b0 + (b1 - b0) * pj.get("lage", 0.5)
        h = proj(a, b)
        if h is None:
            continue
        ort, normale = h
        # Einsätze schauen nach vorn bzw. hinten, nicht nur entlang der Haut.
        fahrt = Vector((1 if ort.x > 0 else -1, 0, 0))
        richtung = (Vector(normale).normalized() + fahrt * pj.get("vorhalt", 0.7)).normalized()
        ob = tb.projektor("projektor", r, mats, pj.get("art", "projektor"))
        teile.append(auf_flaeche(ob, ort, richtung, 0.004))
    return teile


def gitter_bauen(treffer, fo: Form, zonen: list, mats):
    """Gitter in Zonen mit ``gitter``: Waben, Rauten oder Lamellen auf dem
    Boden der vertieften Öffnung."""
    ms = fo.ms
    teile = []
    for z in zonen:
        gt = z.get("gitter")
        if not gt:
            continue
        ansicht = z["ansicht"]
        boden = {KAROSSERIE_MATS.index(z["mat"])}
        art = gt.get("art", "waben")
        mat = mats[gt.get("mat", "zierteil")]
        masche = gt.get("masche_m", 0.032)
        steg = gt.get("steg_m", 0.006)
        hoehe = gt.get("hoehe_m", 0.012)
        for poly in zone_polygone(z, ms):
            innen, _ = tb.polygon_einruecken(poly, gt.get("rand_m", 0.01))
            for links in _zonenseiten(ansicht):
                blick = tb.blickrichtung(ansicht, links)

                def proj(a, b, _l=links):
                    return treffer.ansicht(ansicht, a, b, boden, _l)
                if art == "lamellen":
                    if gt.get("richtung", "a") == "b":
                        ob = tb.gitter_lamellen("gitter", [(q[1], q[0]) for q in innen], masche, steg, hoehe,
                                               lambda a, b, _p=proj: _p(b, a), blick, tb.achse3(ansicht, 0),
                                               mat, gt.get("winkel_grad", 0.0))
                    else:
                        ob = tb.gitter_lamellen("gitter", innen, masche, steg, hoehe, proj, blick,
                                               tb.achse3(ansicht, 1), mat, gt.get("winkel_grad", 0.0))
                else:
                    ob = tb.gitter_zellen("gitter", innen, art, masche, steg, hoehe, proj, blick, mat)
                if ob is not None:
                    teile.append(ob)
    return teile


def glaszonen(p) -> list:
    """Scheiben, Säulen und Dachausschnitte aus ``kabine`` als Zonen."""
    k = p["kabine"]
    rahmen = [{"dicke": k.get("rahmen_m", 0.018), "tiefe": -0.008, "rand": "kunststoff"}]
    zonen = []
    if "frontscheibe" in k:
        zonen.append({"ansicht": "oben", "punkte": k["frontscheibe"], "symmetrisch": True,
                      "mat": "glas", "nur_gh": True, "n_min": 0.05,
                      "segmente": [SEG_FENSTER, SEG_DACH], "stufen": rahmen})
    if "heckscheibe" in k:
        zonen.append({"ansicht": "oben", "punkte": k["heckscheibe"], "symmetrisch": True,
                      "mat": "glas", "nur_gh": True, "n_min": 0.05,
                      "segmente": [SEG_FENSTER, SEG_DACH], "stufen": rahmen})
    if "seitenfenster" in k:
        seitenrahmen = [dict(rahmen[0], rand=k.get("seitenrahmen", "kunststoff"))]
        if k.get("seitenrahmen") == "chrom":
            # Chromleiste außen, dahinter die schwarze Dichtung.
            seitenrahmen = [{"dicke": 0.012, "tiefe": -0.002, "rand": "chrom"},
                            {"dicke": 0.01, "tiefe": -0.006, "rand": "kunststoff"}]
        zonen.append({"ansicht": "seite", "punkte": k["seitenfenster"], "mat": "glas",
                      "nur_gh": True, "n_min": 0.2, "segmente": [SEG_FENSTER],
                      "stufen": seitenrahmen})
    for dz in ("schiebedach", "glasdach"):
        if dz in k:
            zonen.append({"ansicht": "oben", "punkte": k[dz], "symmetrisch": True,
                          "mat": "glas", "nur_gh": True, "segmente": [SEG_DACH, SEG_FENSTER],
                          "stufen": [{"dicke": 0.012, "tiefe": -0.006, "rand": "kunststoff"}]})
    for b in k.get("b_saeulen", []):
        u, breite = b
        zonen.append({"ansicht": "seite", "punkte": [[u - breite / 2, 0], [u + breite / 2, 0],
                                                     [u + breite / 2, 3], [u - breite / 2, 3]],
                      "mat": k.get("saeulen", "zierteil"), "auf": ["glas"], "n_min": 0.2})
    if k.get("dach_mat"):
        # Dach in eigener Farbe: alles oberhalb der Scheibenkante, was nicht Glas ist.
        zonen.append({"ansicht": "oben", "punkte": [[0, -1.2], [1, -1.2], [1, 1.2], [0, 1.2]],
                      "mat": k["dach_mat"], "nur_gh": True, "segmente": [SEG_DACH],
                      "n_min": 0.3})
    return zonen


# ---------------------------------------------------------------------------
# Radläufe
# ---------------------------------------------------------------------------

def radlaeufe(karosserie, fo: Form, p, mats):
    """Radläufe ausschneiden und mit schwarzen Radhausschalen auskleiden."""
    ms = fo.ms
    teile = []
    spiel = p.get("radlauf_spiel_m", 0.04)
    referenz = karosserie.copy()
    referenz.data = karosserie.data.copy()
    bpy.context.scene.collection.objects.link(referenz)
    innen = ms.spur_halb - ms.reifen_b / 2 - 0.05
    aussen = ms.breite_gesamt / 2 + 0.1
    for achse_x in (ms.achse_vorn, ms.achse_hinten):
        r = ms.rad_r + spiel
        for seite in (1, -1):
            schnitt = zylinder_y("schnitt", (achse_x, seite * (innen + aussen) / 2, ms.rad_r),
                                 r, aussen - innen, mats["kunststoff"], segmente=56)
            g.boolesch(karosserie, schnitt)
            breite = aussen - innen
            schale = zylinder_y("radhaus", (achse_x, seite * (innen + breite / 2), ms.rad_r),
                                r - 0.004, breite, mats["kunststoff"], segmente=40, kappen=False)
            bm = bmesh.new()
            bm.from_mesh(schale.data)
            weg = [v for v in bm.verts if v.co.z < ms.rad_r - r * 0.3]
            bmesh.ops.delete(bm, geom=weg, context="VERTS")
            rand = [e for e in bm.edges if e.is_boundary and
                    abs(abs(e.verts[0].co.y) - innen) < 1e-3 and abs(abs(e.verts[1].co.y) - innen) < 1e-3]
            if rand:
                bmesh.ops.edgeloop_fill(bm, edges=rand)
            for v in bm.verts:
                if abs(v.co.y) < innen + 0.01:
                    continue
                t = strahl(referenz, (v.co.x, seite * (ms.breite_gesamt + 1), v.co.z), (0, -seite, 0))
                grenze = abs(t[0].y) - 0.012 if t else innen + 0.02
                v.co.y = seite * max(innen + 0.02, min(abs(v.co.y), grenze))
            bm.to_mesh(schale.data)
            bm.free()
            for pol in schale.data.polygons:
                pol.use_smooth = True
            teile.append(schale)
    bpy.data.objects.remove(referenz, do_unlink=True)
    return teile


# ---------------------------------------------------------------------------
# Anbauteile
# ---------------------------------------------------------------------------

def anbauteile(karosserie, fo: Form, p, mats):
    """Kennzeichen, Spiegel, Griffe, Schweller, Diffusor, Auspuff, Spoiler,
    Wischer. Mit ``teile``-Block kommen die Teile aus der Bibliothek."""
    ms = fo.ms
    teile = []
    tp = p.get("teile")
    x_vorn = ms.x(fo.u1)
    x_hinten = ms.x(fo.u0)

    def setzen(ob, start, richtung, einsenken, dreh=0.0):
        t = strahl(karosserie, start, richtung)
        if t is None:
            bpy.data.objects.remove(ob, do_unlink=True)
            return None
        return auf_flaeche(ob, t[0], t[1], einsenken, dreh)

    # --- Kennzeichen --------------------------------------------------------
    kz = p.get("kennzeichen", {})
    for vorn in (True, False):
        z = kz.get("vorn_m" if vorn else "hinten_m")
        if z is None:
            continue
        if tp is not None and tp.get("kennzeichen", {}) is not False:
            text = (tp.get("kennzeichen") or {}).get("text") or ti.kennzeichen_text(p.get("_key", ""))
            schild = ti.kennzeichen(text, mats)
        else:
            schild = platte("kennzeichen", 0.52, 0.115, 0.012,
                            (mats["kennzeichen"], mats["kunststoff"]), rundung=10)
        vor = -kz.get("vorn_vorsprung_m" if vorn else "hinten_vorsprung_m", 0.0)
        if vorn:
            teile.append(setzen(schild, (x_vorn + 1, 0, z), (-1, 0, 0), vor))
        else:
            teile.append(setzen(schild, (x_hinten - 1, 0, z), (1, 0, 0), vor))

    # --- Spiegel ------------------------------------------------------------
    sp_def = p.get("spiegel", {})
    if sp_def is not None:
        if tp is not None and tp.get("spiegel", {}) is not False:
            teile += spiegel_neu(karosserie, fo, sp_def, tp.get("spiegel") or {}, mats)
        else:
            teile += spiegel_bauen(karosserie, fo, sp_def, mats)

    # --- Türgriffe ----------------------------------------------------------
    for u_griff in p.get("tuergriffe_u", []):
        x = ms.x(u_griff)
        z = fo.zd(u_griff) - p.get("griff_tiefe_m", 0.07)
        for seite in (1, -1):
            if tp is not None and tp.get("tuergriff", {}) is not False:
                tg = tp.get("tuergriff") or {}
                griff = tb.tuergriff(tg.get("art", "buegel"), tg.get("laenge_m", 0.15), mats,
                                     mats[p.get("griffe", "lack")])
                teile.append(setzen(griff, (x, seite * (ms.breite_gesamt + 1), z), (0, -seite, 0), 0.0))
                continue
            griff = kasten("griff", (0, 0, 0), (0.026, 0.15, 0.028), mats[p.get("griffe", "lack")],
                           fase=0.009)
            griff.data.transform(Matrix.Rotation(math.radians(-90), 4, "Z"))
            teile.append(setzen(griff, (x, seite * (ms.breite_gesamt + 1), z), (0, -seite, 0), 0.006))

    # --- Schweller, Splitter, Diffusor --------------------------------------
    if p.get("schweller", True):
        u_a = ms.u(ms.achse_hinten + ms.rad_r + 0.1)
        u_b = ms.u(ms.achse_vorn - ms.rad_r - 0.1)
        ringe = []
        for i in range(12):
            u = u_a + (u_b - u_a) * i / 11
            x = ms.x(u)
            w = fo.w(u) * wert(p.get("schweller_v"), u, 0.965) + p.get("schweller_aussen_m", 0.012)
            zu = fo.zu(u)
            ringe.append(None)
            ringe[-1] = (x, w, zu)
        for seite in (1, -1):
            rs = []
            for (x, w, zu) in ringe:
                prof = [(w - 0.09, zu - 0.005), (w, zu - 0.005), (w + 0.005, zu + 0.05),
                        (w - 0.01, zu + 0.1), (w - 0.09, zu + 0.08)]
                rs.append([(x, seite * a, b) for a, b in prof])
            teile.append(netz_aus_ringen("schweller", rs, mats[p.get("schweller_mat", "kunststoff")],
                                         kappen=True))
    if p.get("splitter", False):
        # Flache Lippe unter dem Stoßfänger, folgt dem Grundriss der Front.
        z_s = fo.zu(fo.u1 - 0.03) + 0.005
        ringe = []
        buckel = p.get("front_buckel_m", 0.06)
        for i in range(9):
            u = fo.u1 - (buckel + 0.3 * i / 8) / ms.laenge
            w = fo.w(u) * wert(p.get("boden"), u, 0.84) + p.get("splitter_ueberstand_m", 0.03)
            x = ms.x(u) + buckel * 0.7 * (1 - i / 8)
            ringe.append([(x, -w, z_s - 0.012), (x, w, z_s - 0.012), (x, w, z_s + 0.012), (x, -w, z_s + 0.012)])
        ringe.reverse()
        teile.append(netz_aus_ringen("splitter", ringe, mats[p.get("splitter_mat", "kunststoff")],
                                     kappen=True))
    if p.get("diffusor", False) and tp is not None and tp.get("diffusor", {}) is not False:
        teile += tb.diffusor(tp.get("diffusor") or {}, fo, p, mats)
    elif p.get("diffusor", False):
        zu = fo.zu(fo.u0 + 0.03)
        breite = 2 * fo.w(fo.u0 + 0.05) * 0.72
        teile.append(kasten("diffusor", (x_hinten + 0.22, 0, zu + 0.02),
                            (0.44, breite, 0.03), mats[p.get("diffusor_mat", "kunststoff")], fase=0.01))
        for i in range(6):
            y = (i - 2.5) * breite / 6
            teile.append(kasten("finne", (x_hinten + 0.2, y, zu + 0.08), (0.36, 0.012, 0.12),
                                mats[p.get("diffusor_mat", "kunststoff")]))

    # --- Auspuff ------------------------------------------------------------
    ap = p.get("auspuff", {"anzahl": 1})
    z_a = ap.get("hoehe_m", fo.zu(fo.u0 + 0.02) + 0.1)
    lagen = {1: [-0.55], 2: [-0.55, 0.55], 4: [-0.66, -0.52, 0.52, 0.66], 0: []}
    for rel in ap.get("lagen", lagen.get(ap.get("anzahl", 1), [])):
        y = rel * fo.w(fo.u0 + 0.05) if not ap.get("mitte_m") else rel * ap["mitte_m"]
        hit = strahl(karosserie, (x_hinten - 1, y, z_a), (1, 0, 0))
        x0 = hit[0].x if hit else x_hinten + 0.1
        r_a = ap.get("radius_m", 0.045)
        if tp is not None and tp.get("auspuff", {}) is not False:
            ta = tp.get("auspuff") or {}
            blende = tb.auspuffblende("auspuff", r_a, ta.get("laenge_m", 0.16), mats, ta.get("art", "rund"))
            blende.data.transform(Matrix.Translation((x0 - 0.035, y, z_a)))
            teile.append(blende)
            if ta.get("blende", True) and hit is not None:
                ring = platte("auspuffblende", r_a * 2.7, r_a * 2.3, 0.01,
                              (mats["zierteil"], mats["zierteil"]), rundung=2.6)
                teile.append(auf_flaeche(ring, hit[0], hit[1], 0.003))
            continue
        teile.append(zylinder_x("auspuff", (x0 + 0.06, y, z_a), r_a, 0.24, mats["chrom"]))
        teile.append(zylinder_x("auspuffloch", (x0 - 0.055, y, z_a), r_a * 0.8, 0.02,
                                mats["kunststoff"]))

    # --- Spoiler ------------------------------------------------------------
    for sp_def in p.get("spoiler", []):
        teile += spoiler(sp_def, karosserie, fo, p, mats)

    # --- Scheibenwischer ----------------------------------------------------
    if tp is not None and tp.get("wischer", {}) is not False:
        if p.get("wischer", True):
            teile += wischer_neu(karosserie, fo, p, tp.get("wischer") or {}, mats)
    elif p.get("wischer", True) and "frontscheibe" in p["kabine"]:
        teile += wischer(karosserie, fo, p, mats)

    # --- Dachantenne -------------------------------------------------------
    if tp is not None and tp.get("antenne"):
        an = tp["antenne"]
        flosse = tb.antenne(an.get("laenge_m", 0.16), an.get("hoehe_m", 0.06), mats[an.get("mat", "lack")])
        hit = strahl(karosserie, (ms.x(an.get("u", 0.2)), 0, 5), (0, 0, -1))
        if hit is not None:
            flosse.data.transform(Matrix.Translation(hit[0]))
            teile.append(flosse)
        else:
            bpy.data.objects.remove(flosse, do_unlink=True)

    # --- Embleme ------------------------------------------------------------
    if tp is not None and tp.get("emblem", {}) is not False:
        te = tp.get("emblem") or {}
        form = ti.emblemform(p.get("_key", ""), te)
        orte = te.get("orte")
        if orte is None:
            orte = [{"ansicht": "vorn", "z_m": kz.get("vorn_m", 0.45) + 0.14},
                    {"ansicht": "hinten", "z_m": kz.get("hinten_m", 0.6) + 0.14}]
        for ort in orte:
            em = ti.emblem(form, ort.get("groesse_m", te.get("groesse_m", 0.07)), mats)
            y = ms.y(ort.get("v", 0.0))
            if ort["ansicht"] == "oben":
                teile.append(setzen(em, (ms.x(ort["u"]), y, 5), (0, 0, -1), 0.0))
            elif ort["ansicht"] == "vorn":
                teile.append(setzen(em, (x_vorn + 1, y, ort["z_m"]), (-1, 0, 0), 0.0))
            else:
                teile.append(setzen(em, (x_hinten - 1, y, ort["z_m"]), (1, 0, 0), 0.0))

    return [o for o in teile if o is not None]


def spiegel_bauen(karosserie, fo: Form, d, mats):
    """Außenspiegel: Gehäuse an einem Arm, Spitze genau bei ``v``."""
    ms = fo.ms
    u = d.get("u", 0.65)
    x = ms.x(u)
    spitze = ms.y(d.get("v", 0.99))
    lang, tief, hoch = d.get("groesse", [0.12, 0.22, 0.13])
    z = d.get("z_m", fo.T(u, fo.wg(u)) + 0.1)
    teile = []
    for seite in (1, -1):
        t = strahl(karosserie, (x, seite * (ms.breite_gesamt + 1), z - 0.07), (0, -seite, 0))
        y_wand = abs(t[0].y) if t else fo.ws(u)
        yc = spitze - tief / 2
        ringe = []
        for i in range(9):
            s = i / 8
            # Gehäuse als Loft entlang y: innen schmaler, außen voll, die
            # Außenkante gerundet; vorne gewölbt, hinten flach (Glasseite).
            b = (0.75 + 0.25 * s) * math.sin(math.pi * (0.5 + 0.47 * s)) ** 0.25 if s > 0.5 else \
                0.75 + 0.25 * s
            ring = []
            for j in range(16):
                w = 2 * math.pi * j / 16
                cx, cz = math.cos(w), math.sin(w)
                ex = sp(cx, 0.5) * lang / 2
                if ex < 0:
                    ex = -lang * 0.18                 # flache Rückseite
                ring.append((x + ex * b - 0.05 * s, seite * (yc - tief / 2 + tief * s),
                             z + sp(cz, 0.45) * hoch / 2 * b))
            ringe.append(ring)
        gehaeuse = netz_aus_ringen("spiegel", ringe, mats[d.get("mat", "lack")], kappen=True)
        teile.append(gehaeuse)
        glas = platte("spiegelglas", tief * 0.8, hoch * 0.72, 0.006, (mats["chrom"], mats["kunststoff"]),
                      rundung=3)
        glas.rotation_euler = (0, 0, math.radians(180 - 12 * seite))
        glas.location = (x - lang * 0.18 - 0.028, seite * yc, z)
        g.transform_anwenden(glas)
        teile.append(glas)
        arm_innen = y_wand - 0.02
        arm_aussen = yc - tief / 2 + 0.02
        if arm_aussen > arm_innen:
            teile.append(kasten("spiegelarm", (x + 0.01, seite * (arm_innen + arm_aussen) / 2, z - 0.035),
                                (0.08, arm_aussen - arm_innen, 0.04), mats[d.get("arm_mat", "kunststoff")],
                                fase=0.012))
        if d.get("blinker", True):
            teile.append(kasten("blinker", (x + lang * 0.4 - 0.042, seite * (spitze - 0.035),
                                            z - hoch * 0.22),
                                (0.03, 0.07, 0.016), mats["blinker"], fase=0.005))
    return teile


def spiegel_neu(karosserie, fo: Form, d, td, mats):
    """Außenspiegel aus der Bibliothek, Lage wie ``spiegel_bauen``."""
    ms = fo.ms
    u = d.get("u", 0.65)
    x = ms.x(u)
    spitze = ms.y(d.get("v", 0.99))
    groesse = d.get("groesse", [0.12, 0.22, 0.13])
    z = d.get("z_m", fo.T(u, fo.wg(u)) + 0.1)
    teile = []
    for seite in (1, -1):
        hit = strahl(karosserie, (x, seite * (ms.breite_gesamt + 1), z - 0.07), (0, -seite, 0))
        y_wand = abs(hit[0].y) if hit else fo.ws(u)
        teile += tb.spiegel(x, z, spitze, y_wand, seite, groesse, mats, d, td)
    return teile


def _wischer_eins(treffer, glas, drehpunkt, a, b, mats):
    """Ein Wischer: Blatt von ``a`` nach ``b`` (x, y) auf der Scheibe, Arm vom
    Drehpunkt (x, y) zur Blattmitte."""
    pts, nrm = [], []
    for i in range(12):
        s = i / 11
        h = treffer.strahl((a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s, 5), (0, 0, -1))
        if h is None or h[2] not in glas:
            continue
        n = Vector(h[1]).normalized()
        pts.append(h[0] + n * 0.002)
        nrm.append(n)
    if len(pts) < 3:
        return []
    teile = tb.wischerblatt("wischer", pts, nrm, mats)
    hp = treffer.strahl((drehpunkt[0], drehpunkt[1], 5), (0, 0, -1))
    if hp is not None:
        k = len(pts) // 2
        n0 = Vector(hp[1]).normalized()
        pa = hp[0] + n0 * 0.012
        pe = pts[k] + nrm[k] * 0.02
        nm = (n0 + nrm[k]).normalized()
        mitte = (pa + pe) / 2 + nm * 0.012
        arm = tb.band("wischerarm", [pa, mitte, pe], [n0, nm, nrm[k]], 0.013, 0.008, mats["zierteil"])
        if arm is not None:
            teile.append(arm)
        teile.append(kugel("wischerlager", pa, (0.034, 0.034, 0.022), mats["zierteil"], 12, 6))
    return teile


def wischer_neu(karosserie, fo: Form, p, tw, mats):
    """Wischer aus der Bibliothek: Blatt mit Träger liegt auf der Scheibe."""
    ms = fo.ms
    k = p["kabine"]
    teile = []
    treffer = tb.Treffer(karosserie)
    glas = {KAROSSERIE_MATS.index("glas")}
    if "frontscheibe" in k:
        u = max(a for a, _ in k["frontscheibe"]) - 0.01
        while u > fo.dach_u0 and fo.G(u, 0) < fo.T(u, 0) + 0.02:
            u -= 0.002
        x_f = ms.x(u)
        anzahl = tw.get("anzahl", 2)
        lagen = tw.get("lagen_m", [0.06, -0.5] if anzahl == 2 else [-0.28])
        laengen = tw.get("laenge_m", [0.62, 0.5] if anzahl == 2 else [0.7])
        for y0, lg in zip(lagen[:anzahl], laengen):
            teile += _wischer_eins(treffer, glas, (x_f + 0.03, y0),
                                   (x_f - 0.045, y0 + 0.05), (x_f - 0.075, y0 + 0.05 + lg), mats)
    if tw.get("heck") and "heckscheibe" in k:
        u = min(a for a, _ in k["heckscheibe"]) + 0.012
        x_h = ms.x(u)
        lg = tw.get("heck_laenge_m", 0.36)
        teile += _wischer_eins(treffer, glas, (x_h - 0.02, 0.0), (x_h + 0.005, 0.04),
                               (x_h + 0.005, 0.04 + lg), mats)
    return teile


def wischer(karosserie, fo: Form, p, mats):
    """Zwei Wischerarme am Fuß der Frontscheibe."""
    ms = fo.ms
    teile = []
    fs = p["kabine"]["frontscheibe"]
    u_fuss = max(a for a, _ in fs) - 0.01
    # Scheibenfuß suchen: wo das Glashaus aus der Haube steigt.
    u = u_fuss
    while u > fo.dach_u0 and fo.G(u, 0) < fo.T(u, 0) + 0.02:
        u -= 0.002
    x = ms.x(u) - 0.03
    for y0, laenge in ((0.1, 0.6), (-0.45, 0.55)):
        t = strahl(karosserie, (x, y0, 5), (0, 0, -1))
        if not t:
            continue
        ort = t[0]
        arm = kasten("wischer", (0, 0, 0), (0.012, laenge, 0.012), mats["kunststoff"])
        arm.rotation_euler = (0, math.radians(-28), math.radians(8))
        arm.location = ort + Vector((0.01, laenge / 2 - 0.05, 0.012))
        g.transform_anwenden(arm)
        teile.append(arm)
    return teile


def spoiler(d, karosserie, fo: Form, p, mats):
    ms = fo.ms
    art = d["art"]
    teile = []
    if art == "fluegel" and d.get("profil"):
        return tb.fluegel(d, fo, lambda s, r: strahl(karosserie, s, r), mats)
    if art == "fluegel":
        # u: Hinterkante; v: halbe Spannweite; Höhe der Oberkante in Metern.
        x_hk = ms.x(d.get("u", 0.02))
        tiefe = d.get("tiefe_m", 0.3)
        halb = ms.y(d.get("v", 0.85))
        z = d["hoehe_m"]
        bm = bmesh.new()
        profil = [(0.0, 0.0), (0.06, 0.03), (0.3, 0.05), (0.7, 0.035), (1.0, 0.0),
                  (0.7, -0.01), (0.3, -0.012), (0.06, -0.01)]
        links, rechts = [], []
        for (a, b) in profil:
            links.append(bm.verts.new((tiefe * (1 - a), halb, b * tiefe * 1.6)))
            rechts.append(bm.verts.new((tiefe * (1 - a), -halb, b * tiefe * 1.6)))
        bm.faces.new(links)
        bm.faces.new(list(reversed(rechts)))
        n = len(profil)
        for i in range(n):
            bm.faces.new((links[i], links[(i + 1) % n], rechts[(i + 1) % n], rechts[i]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        fl = g.objekt_aus(bm, "fluegel", [mats[d.get("mat", "carbon")]])
        fl.rotation_euler = (0, math.radians(d.get("anstellung_grad", 8)), 0)
        fl.location = (x_hk, 0, z - 0.03)
        g.transform_anwenden(fl)
        teile.append(fl)
        if d.get("gurney", True):
            teile.append(kasten("gurney", (x_hk + 0.005, 0, z + 0.01), (0.01, 2 * halb, 0.03),
                                mats[d.get("mat", "carbon")]))
        for seite in (1, -1):
            teile.append(kasten("endplatte", (x_hk + tiefe * 0.5, seite * (halb + 0.006), z - 0.03),
                                (tiefe * 1.15, 0.012, 0.2), mats[d.get("platten_mat", d.get("mat", "carbon"))],
                                fase=0.004))
            # Stützen: vom Flügel schräg nach vorn auf den Kofferraumdeckel.
            fuss_y = seite * halb * d.get("stuetzen_v", 0.55)
            x_fuss = max(x_hk + tiefe * 0.6, ms.x(fo.u0) + d.get("fuss_m", 0.25))
            t = strahl(karosserie, (x_fuss, fuss_y, 5), (0, 0, -1))
            z0 = t[0].z if t else z - 0.3
            x_oben = x_hk + tiefe * 0.45
            laenge = math.hypot(x_fuss - x_oben, z - 0.05 - z0)
            winkel = math.atan2(x_oben - x_fuss, z - 0.05 - z0)
            st = kasten("stuetze", (0, 0, 0), (0.1, 0.018, laenge + 0.04), mats[d.get("stuetzen_mat", "kunststoff")],
                        fase=0.004)
            st.rotation_euler = (0, winkel, 0)
            st.location = ((x_fuss + x_oben) / 2, fuss_y, (z - 0.05 + z0) / 2)
            g.transform_anwenden(st)
            teile.append(st)
    elif art == "lippe":
        u = d.get("u", 0.03)
        x = ms.x(u)
        t = strahl(karosserie, (x, 0, 5), (0, 0, -1))
        z0 = t[0].z if t else fo.zh(u)
        breite = 2 * ms.y(d.get("v", 0.6))
        teile.append(kasten("lippe", (x, 0, z0 + 0.015), (0.1, breite, 0.03),
                            mats[d.get("mat", "lack")], fase=0.012, drehung=(0, math.radians(-14), 0)))
    elif art == "dach":
        # Dachspoiler über der Heckscheibe: vom Dachende nach hinten auskragend.
        k = p["kabine"]
        u_start = d.get("u", k.get("dachende_u", fo.dach_u0 + 0.1))
        laenge = d.get("laenge_m", 0.3)
        halb = ms.y(d.get("v", 0.55))
        x0 = ms.x(u_start)
        z0 = fo.oben(u_start, 0) + 0.005
        ringe = []
        for i in range(10):
            s = i / 9
            y = -halb + 2 * halb * s
            zk = z0 - 0.01 * (y / halb) ** 2
            ringe.append([(x0 + 0.03, y, zk), (x0 - laenge, y, zk - 0.035 - d.get("neigung_m", 0.03)),
                          (x0 - laenge + 0.02, y, zk - 0.075), (x0 + 0.01, y, zk - 0.02)])
        teile.append(netz_aus_ringen("dachspoiler", ringe, mats[d.get("mat", "lack")], kappen=True))
        if d.get("seitenteile_mat"):
            for seite in (1, -1):
                teile.append(kasten("spoilerecke", (x0 - laenge * 0.6, seite * (halb - 0.03), z0 - 0.07),
                                    (laenge * 0.8, 0.05, 0.1), mats[d["seitenteile_mat"]], fase=0.012))
    return teile


def innenraum(fo: Form, p, mats):
    """Wanne, Sitze, Armaturenbrett, Lenkrad — sichtbar durch das getönte Glas."""
    ms = fo.ms
    k = p["kabine"]
    teile = []
    # Wo steht Glashaus über der Haube?
    us = [fo.dach_u0 + (fo.dach_u1 - fo.dach_u0) * i / 200 for i in range(201)]
    frei = [u for u in us if fo.G(u, 0) > fo.T(u, 0) + 0.05]
    if not frei:
        return teile
    u_hinten, u_vorn = min(frei), max(frei)
    n = 30
    punkte, flaechen = [], []
    for i in range(n + 1):
        u = u_hinten + (u_vorn - u_hinten) * i / n
        z = fo.zd(u) - 0.02
        w_i = fo.ws(u) - 0.03
        punkte += [(ms.x(u), w_i, z), (ms.x(u), -w_i, z)]
        if i:
            a = 2 * (i - 1)
            flaechen.append((a, a + 1, a + 3, a + 2))
    teile.append(g.objekt_aus_daten("wanne", punkte, flaechen, [mats["innenraum"]]))

    # Armaturenbrett: so weit hinten, dass es mit 3 cm Luft unter der
    # Frontscheibe bleibt — auch an den Ecken, wo die Scheibe tiefer liegt.
    def armaturbreite(u):
        return min(fo.ws(u) - 0.06, fo.wg(u) - 0.1)

    u_armatur = u_vorn
    while u_armatur > u_hinten:
        w_a = armaturbreite(u_armatur)
        luft = min(fo.oben(u_armatur, 0), fo.oben(u_armatur, 0.7 * w_a)) - fo.zd(u_armatur)
        if luft > 0.16:
            break
        u_armatur -= 0.002
    if u_armatur <= u_hinten + 0.5 / ms.laenge:
        u_armatur = u_vorn - 0.3 / ms.laenge
    x_armatur = ms.x(u_armatur)
    z_a = fo.zd(u_armatur)
    w_a = armaturbreite(u_armatur)
    teile.append(kasten("armatur", (x_armatur - 0.2, 0, z_a + 0.04), (0.4, w_a * 2, 0.16),
                        mats["innenraum"], fase=0.04))
    reihen = k.get("sitzreihen", 2)
    for r in range(reihen):
        x_sitz = x_armatur - 0.8 - r * 0.85
        u_s = ms.u(x_sitz)
        if u_s - 0.35 / ms.laenge < u_hinten + 0.02:
            break
        z_s = fo.zd(u_s) - 0.02
        w_s = min(fo.ws(u_s) - 0.08, fo.wg(u_s) - 0.05)
        dach = min(fo.oben(u_s - 0.35 / ms.laenge, w_s * 0.75), fo.oben(u_s, w_s * 0.75))
        lehne_h = min(0.6, dach - z_s - 0.22)
        if lehne_h < 0.22:
            # Kein Platz unter dem Dach: lieber keine Sitzreihe als eine,
            # die durchs Blech ragt.
            break
        for seite in (1, -1):
            y = seite * w_s * 0.5
            teile.append(kasten("sitz", (x_sitz, y, z_s + 0.03), (0.48, 0.46, 0.1),
                                mats["innenraum"], fase=0.035))
            teile.append(kasten("lehne", (x_sitz - 0.24, y, z_s + lehne_h / 2), (0.11, 0.44, lehne_h),
                                mats["innenraum"], fase=0.04, drehung=(0, math.radians(-14), 0)))
            if dach - (z_s + lehne_h) > 0.2:
                teile.append(kasten("kopfstuetze", (x_sitz - 0.3, y, z_s + lehne_h + 0.06),
                                    (0.08, 0.24, 0.12), mats["innenraum"], fase=0.03))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.17, minor_radius=0.018,
                                     major_segments=24, minor_segments=6)
    lenkrad = bpy.context.object
    lenkrad.name = "lenkrad"
    lenkrad.rotation_euler = (0, math.radians(65), 0)
    lenkrad.location = (x_armatur - 0.44, w_a * 0.45, z_a + 0.12)
    g.transform_anwenden(lenkrad)
    lenkrad.data.materials.append(mats["innenraum"])
    teile.append(lenkrad)
    return teile


# ---------------------------------------------------------------------------
# Räder
# ---------------------------------------------------------------------------

def reifen(ms: Masse, p, mats):
    """Reifen als Drehkörper um Y, Außenseite bei +Y, mit Profil."""
    R = ms.rad_r
    b = ms.reifen_b
    rr = p.get("zoll", 17) * 0.0254 / 2
    h = R - rr
    halb = b / 2
    profil = [
        (rr + 0.004, -halb + 0.012), (rr + 0.012, -halb + 0.002),
        (rr + h * 0.35, -halb - 0.006), (rr + h * 0.7, -halb - 0.004),
        (R - 0.018, -halb + 0.008), (R - 0.004, -halb + 0.024),
    ]
    rillen = [-0.3, -0.1, 0.1, 0.3]
    lauf = [-halb + 0.03]
    for r_ in rillen:
        y = r_ * b
        lauf += [y - 0.007, y - 0.0065, y + 0.0065, y + 0.007]
    lauf.append(halb - 0.03)
    for i, y in enumerate(lauf):
        rad = R
        if 1 <= i <= len(lauf) - 2 and (i - 1) % 4 in (1, 2):
            rad = R - 0.008
        profil.append((rad, y))
    profil += [
        (R - 0.004, halb - 0.024), (R - 0.018, halb - 0.008),
        (rr + h * 0.7, halb + 0.004), (rr + h * 0.35, halb + 0.006),
        (rr + 0.012, halb - 0.002), (rr + 0.004, halb - 0.012),
    ]
    seg = p.get("reifen_segmente", 64)
    punkte, flaechen = [], []
    n = len(profil)
    schulter = {i for i, (r_, y) in enumerate(profil) if r_ >= R - 0.005 and abs(y) > b * 0.34}
    for s in range(seg):
        w = 2 * math.pi * s / seg
        block = (s % 2 == 0)
        for i, (r_, y) in enumerate(profil):
            rad = r_
            if block and i in schulter:
                rad -= 0.006
            punkte.append((rad * math.cos(w), y, rad * math.sin(w)))
    for s in range(seg):
        for i in range(n):
            a = s * n + i
            b_ = s * n + (i + 1) % n
            c = ((s + 1) % seg) * n + (i + 1) % n
            d = ((s + 1) % seg) * n + i
            flaechen.append((a, b_, c, d))
    ob = g.objekt_aus_daten("reifen", punkte, flaechen, [mats["gummi"]])
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(ob.data)
    bm.free()
    g.glatt(ob, 50)
    return ob, rr


def turbinen_felge(p, mats, rr: float, y_rand: float) -> list:
    """Aero-Felge im Turbinenstil: dunkle Grundscheibe, heller Außenring und
    Nabenteller, dazwischen gebogene Schaufeln (``felgen_schaufeln``,
    ``felgen_bogen_grad``, ``felgen_schaufel_breite_m``). Außenseite bei +Y,
    rotationssymmetrisch um Y.
    """
    fm = mats["felge"]
    teile = [zylinder_y("aerogrund", (0, y_rand - 0.03, 0), rr - 0.014, 0.012,
                        mats["kunststoff"], segmente=64)]

    def ring(name, r0, r1, y0, y1, seg=64):
        # Kreisring als geschlossener Drehkörper (Querschnitt: Rechteck).
        prof = [(r0, y0), (r1, y0), (r1, y1), (r0, y1)]
        punkte, flaechen = [], []
        for s in range(seg):
            w = 2 * math.pi * s / seg
            for r_, y in prof:
                punkte.append((r_ * math.cos(w), y, r_ * math.sin(w)))
        for s in range(seg):
            for i in range(4):
                a, b = s * 4 + i, s * 4 + (i + 1) % 4
                c, d = ((s + 1) % seg) * 4 + (i + 1) % 4, ((s + 1) % seg) * 4 + i
                flaechen.append((a, b, c, d))
        ob = g.objekt_aus_daten(name, punkte, flaechen, [fm])
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(ob.data)
        bm.free()
        return ob

    teile.append(ring("aeroring", rr * 0.8, rr - 0.012, y_rand - 0.03, y_rand - 0.006))
    teile.append(zylinder_y("aeroteller", (0, y_rand - 0.02, 0), rr * 0.42, 0.028, fm, segmente=48))
    n = p.get("felgen_schaufeln", 10)
    bogen = math.radians(p.get("felgen_bogen_grad", 28))
    sb = p.get("felgen_schaufel_breite_m", 0.03)
    r0, r1 = rr * 0.4, rr * 0.82
    y0, y1 = y_rand - 0.03, y_rand - 0.004
    schritte = 8
    for i in range(n):
        w0 = 2 * math.pi * i / n
        bm = bmesh.new()
        ringe = []
        for k in range(schritte + 1):
            t = k / schritte
            r_ = r0 + (r1 - r0) * t
            w = w0 + bogen * t
            b = sb * (1 - 0.4 * t) / 2
            # Quer zur Schaufel: tangential in der Radebene
            tx, tz = -math.sin(w), math.cos(w)
            cx, cz = r_ * math.cos(w), r_ * math.sin(w)
            ringe.append([bm.verts.new((cx + s * b * tx, y, cz + s * b * tz))
                          for s, y in ((-1, y0), (1, y0), (1, y1), (-1, y1))])
        for k in range(schritte):
            a, c = ringe[k], ringe[k + 1]
            for j in range(4):
                bm.faces.new((a[j], a[(j + 1) % 4], c[(j + 1) % 4], c[j]))
        bm.faces.new(ringe[0])
        bm.faces.new(list(reversed(ringe[-1])))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        teile.append(g.objekt_aus(bm, "schaufel", [fm]))
    return teile


def felge(ms: Masse, p, mats, rr: float):
    """Felge mit Speichen je Design, Außenseite bei +Y."""
    b = ms.reifen_b
    halb = b / 2
    teile = []
    design = p.get("felge", "fuenf")
    fm = mats["felge"]
    teile.append(zylinder_y("bett", (0, -0.01, 0), rr - 0.012, b - 0.04, mats["bremse"],
                            segmente=48, kappen=False))
    bpy.ops.mesh.primitive_torus_add(major_radius=rr - 0.008, minor_radius=0.011,
                                     major_segments=64, minor_segments=8)
    horn = bpy.context.object
    horn.rotation_euler = (math.radians(90), 0, 0)
    horn.location = (0, halb - 0.02, 0)
    g.transform_anwenden(horn)
    horn.data.materials.append(fm)
    for pol in horn.data.polygons:
        pol.use_smooth = True
    teile.append(horn)

    y_nabe = halb - p.get("felgentiefe_m", 0.06)
    y_rand = halb - 0.024
    if design == "aero":
        scheibe = zylinder_y("aero", (0, y_rand - 0.01, 0), rr - 0.012, 0.018, fm, segmente=64)
        teile.append(scheibe)
        for i in range(5):
            w = 2 * math.pi * i / 5
            loch = kugel("aeroschlitz", (0, 0, 0), (0.1, 0.02, 0.035), mats["kunststoff"], 12, 6)
            loch.data.transform(Matrix.Translation((rr * 0.62, 0, 0)))
            loch.rotation_euler = (0, -w, 0)
            loch.location = (0, y_rand, 0)
            g.transform_anwenden(loch)
            teile.append(loch)
    elif design == "turbine":
        teile += turbinen_felge(p, mats, rr, y_rand)
    else:
        muster = {
            "fuenf": [(0.0, 0.075, 0.045)],
            "zehn": [(-7.0, 0.04, 0.026), (7.0, 0.04, 0.026)],
            "vielspeichen": [(0.0, 0.028, 0.016)],
            "y": [(0.0, 0.05, 0.03), (-9.0, 0.028, 0.02), (9.0, 0.028, 0.02)],
            "tiefbett": [(0.0, 0.05, 0.035)],
            "zentral": [(-6.0, 0.036, 0.024), (6.0, 0.036, 0.024)],
            "mesh": [(-12.0, 0.022, 0.016), (12.0, 0.022, 0.016)],
        }[design]
        anzahl = {"fuenf": 5, "zehn": 5, "vielspeichen": 14, "y": 6,
                  "tiefbett": 6, "zentral": 5, "mesh": 10}[design]
        if design == "tiefbett":
            y_nabe = halb - 0.11
            teile.append(zylinder_y("schuessel", (0, y_rand - 0.035, 0), rr - 0.01, 0.07,
                                    fm, segmente=64, kappen=False))
        for i in range(anzahl):
            for versatz, b0, b1 in muster:
                w = 2 * math.pi * i / anzahl + math.radians(versatz)
                r0, r1 = 0.07, rr - 0.012
                if versatz and design == "y":
                    r0 = rr * 0.55
                bm = bmesh.new()
                vs = []
                for r_, bb, yy in ((r0, b0, y_nabe), (r1, b1, y_rand)):
                    for s in (-1, 1):
                        for d in (0.0, -0.028):
                            vs.append(bm.verts.new((r_, s * bb / 2, yy + d)))
                q = [(0, 2, 6, 4), (1, 5, 7, 3), (0, 4, 5, 1), (2, 3, 7, 6), (0, 1, 3, 2), (4, 6, 7, 5)]
                for f in q:
                    bm.faces.new([vs[k] for k in f])
                bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
                m = Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
                bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
                bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                                 matrix=Matrix.Rotation(-w, 3, "Y"))
                speiche = g.objekt_aus(bm, "speiche", [fm])
                teile.append(speiche)
    teile.append(zylinder_y("nabe", (0, y_nabe + 0.005, 0), 0.085, 0.04, fm, segmente=32))
    if design == "zentral":
        teile.append(zylinder_y("zentralmutter", (0, y_nabe + 0.04, 0), 0.045, 0.05,
                                mats["sattel"], segmente=6))
    else:
        for i in range(5):
            w = 2 * math.pi * i / 5
            teile.append(zylinder_y("mutter", (0.055 * math.cos(w), y_nabe + 0.03, 0.055 * math.sin(w)),
                                    0.011, 0.02, mats["chrom"], segmente=6))
        teile.append(zylinder_y("kappe", (0, y_nabe + 0.03, 0), 0.03, 0.012, mats["kunststoff"],
                                segmente=24))
    teile.append(zylinder_y("bremsscheibe", (0, -0.02, 0), rr - 0.05, 0.028, mats["bremse"],
                            segmente=48))
    return teile


def _emblem_klein(p, mats):
    te = (p.get("teile") or {}).get("emblem") or {}
    form = ti.emblemform(p.get("_key", ""), te)
    return lambda groesse: ti.emblem(form, groesse, mats, sockel=False)


def rad_neu(ms: Masse, p, mats):
    """Rad aus der Bibliothek: Profilreifen, Felge mit Muttern und Kappe,
    Bremsscheibe. Liefert (Teile, Speichenform)."""
    tp = p["teile"]
    rr = p.get("zoll", 17) * 0.0254 / 2
    reif = tr.reifen(ms.rad_r, ms.reifen_b, rr, tp.get("reifen") or {}, mats)
    tf = tp.get("felge") or {}
    if p.get("felge", "fuenf") in tr.MUSTER:
        fteile, form = tr.felge(p, tf, mats, rr, ms.reifen_b, _emblem_klein(p, mats))
        bremse = tr.bremsscheibe(rr, form, tp.get("bremse") or {}, mats)
    else:
        # Aero- und Turbinenfelgen bleiben wie bisher (samt Scheibe).
        fteile = felge(ms, p, mats, rr)
        form = tr.speichenform(p, tf, rr, ms.reifen_b)
        bremse = []
    return [reif] + fteile + bremse, form


def rad_bauen(ms: Masse, p, mats, name: str, vorn: int, seite: int):
    if p.get("teile") is not None:
        teile, _form = rad_neu(ms, p, mats)
    else:
        reif, rr = reifen(ms, p, mats)
        teile = [reif] + felge(ms, p, mats, rr)
    ob = g.verbinden(teile, name)
    if seite < 0:
        ob.data.transform(Matrix.Diagonal((1, -1, 1, 1)))
        ob.data.flip_normals()
    nabe = Vector((ms.achse_vorn if vorn > 0 else ms.achse_hinten,
                   seite * ms.spur_halb, ms.rad_r))
    ob.location = nabe
    return ob, nabe


def sattel_bauen(ms: Masse, p, mats, name: str, vorn: int, seite: int, rr: float):
    """Bremssattel: lenkt mit, dreht aber nicht mit dem Rad."""
    tp = p.get("teile")
    if tp is not None:
        form = tr.speichenform(p, tp.get("felge") or {}, rr, ms.reifen_b)
        ob = tr.bremssattel(name, rr, form, tp.get("bremse") or {}, tp.get("sattel") or {}, mats)
    else:
        r = rr - 0.07
        ob = kasten(name, (0, 0, 0), (0.1, 0.07, 0.16), mats["sattel"], fase=0.015)
        ob.data.transform(Matrix.Translation((-r * 0.7, 0.02, r * 0.7)))
        ob.data.transform(Matrix.Rotation(math.radians(-10 if vorn > 0 else 10), 4, "Y"))
    if seite < 0:
        ob.data.transform(Matrix.Diagonal((1, -1, 1, 1)))
        ob.data.flip_normals()
    ob.location = (ms.achse_vorn if vorn > 0 else ms.achse_hinten, seite * ms.spur_halb, ms.rad_r)
    return ob


# ---------------------------------------------------------------------------
# Ganzes Fahrzeug
# ---------------------------------------------------------------------------

#: Maßstab der Draufsicht, Pixel je Meter. Das Vergleichswerkzeug
#: (``tools/blender/vergleich.py``) skaliert das Sprite auf denselben Wert.
DRAUFSICHT_PX_PRO_M = 125
DRAUFSICHT_RAND_M = 0.3


def _eevee(szene) -> None:
    for kandidat in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES"):
        try:
            szene.render.engine = kandidat
            return
        except TypeError:
            continue


def _licht(name, energie, winkel_grad, drehung):
    sonne = bpy.data.lights.new(name, "SUN")
    sonne.energy = energie
    sonne.angle = math.radians(winkel_grad)
    so = bpy.data.objects.new(name, sonne)
    so.rotation_euler = tuple(math.radians(a) for a in drehung)
    bpy.context.scene.collection.objects.link(so)
    return so


def draufsicht(pfad: Path, ms: Masse) -> None:
    """Orthografisch von oben, Front nach rechts, transparenter Hintergrund.

    Das Bild ist ``(laenge + 2·rand) × (breite + 2·rand)`` Meter groß, der
    Fahrzeugursprung liegt in der Bildmitte — so legt das Vergleichswerkzeug
    das Sprite ohne Suchen darüber.
    """
    szene = bpy.context.scene
    _eevee(szene)
    breite_m = ms.laenge + 2 * DRAUFSICHT_RAND_M
    hoehe_m = ms.breite_gesamt + 2 * DRAUFSICHT_RAND_M
    szene.render.resolution_x = round(breite_m * DRAUFSICHT_PX_PRO_M)
    szene.render.resolution_y = round(hoehe_m * DRAUFSICHT_PX_PRO_M)
    szene.render.film_transparent = True
    szene.view_settings.view_transform = "Standard"
    welt = bpy.data.worlds.new("welt_oben")
    welt.use_nodes = True
    hg = welt.node_tree.nodes["Background"]
    hg.inputs["Color"].default_value = (0.5, 0.52, 0.56, 1.0)
    hg.inputs["Strength"].default_value = 0.6
    szene.world = welt
    lichter = [_licht("sonne_oben", 2.6, 10, (14, -10, 0))]
    kd = bpy.data.cameras.new("kamera_oben")
    kd.type = "ORTHO"
    kd.ortho_scale = breite_m
    kd.clip_end = 100
    ko = bpy.data.objects.new("kamera_oben", kd)
    szene.collection.objects.link(ko)
    ko.location = (0, 0, 20)
    ko.rotation_euler = (0, 0, 0)
    szene.camera = ko
    szene.render.filepath = str(pfad)
    bpy.ops.render.render(write_still=True)
    for ob in [ko] + lichter:
        bpy.data.objects.remove(ob, do_unlink=True)
    szene.render.film_transparent = False


def vorschau_fahrzeug(pfad: Path, ziel=(0.0, 0.0, 0.6), abstand: float = 10.0,
                      azimut_grad: float = 35.0, hoehe_grad: float = 18.0) -> None:
    """Kontrollbild mit Eevee: Hauptlicht, Aufhelllicht, heller Himmel, Boden."""
    szene = bpy.context.scene
    _eevee(szene)
    szene.render.resolution_x = 960
    szene.render.resolution_y = 540
    szene.render.film_transparent = False
    szene.view_settings.view_transform = "AgX"
    try:
        szene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    welt = bpy.data.worlds.new("welt_vorschau")
    welt.use_nodes = True
    hg = welt.node_tree.nodes["Background"]
    hg.inputs["Color"].default_value = (0.42, 0.5, 0.62, 1.0)
    hg.inputs["Strength"].default_value = 0.7
    szene.world = welt
    lichter = [_licht("haupt", 4.0, 3, (40, 10, -30)), _licht("auf", 1.0, 20, (60, -20, 150))]
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=60)
    boden = g.objekt_aus(bm, "boden", [g.material("_boden", (0.42, 0.42, 0.43), 0, 0.9)])
    az = math.radians(azimut_grad)
    el = math.radians(hoehe_grad)
    ziel = Vector(ziel)
    auge = ziel + Vector((math.cos(az) * math.cos(el),
                          math.sin(az) * math.cos(el), math.sin(el))) * abstand
    kd = bpy.data.cameras.new("kamera")
    kd.lens = 50
    ko = bpy.data.objects.new("kamera", kd)
    szene.collection.objects.link(ko)
    ko.location = auge
    ko.rotation_euler = (ziel - auge).to_track_quat("-Z", "Y").to_euler()
    szene.camera = ko
    szene.render.filepath = str(pfad)
    bpy.ops.render.render(write_still=True)
    for ob in [ko, boden] + lichter:
        bpy.data.objects.remove(ob, do_unlink=True)
    szene.view_settings.look = "None"


def karosserie_bauen(fo: Form, p, mats):
    """Haut bauen, Radläufe schneiden, dann Zonen.

    Die Radläufe kommen *vor* den Zonen: der exakte Boolean verträgt die
    vielen feinen Schnittkanten der Zonen schlecht und liefert dann ein
    leeres Netz. Die Flächenattribute (``seg``) übersteht er.
    """
    bm = haut_bauen(fo, p)
    me = bpy.data.meshes.new("karosserie_roh")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("karosserie_roh", me)
    bpy.context.scene.collection.objects.link(ob)
    for n in KAROSSERIE_MATS:
        ob.data.materials.append(mats[n])
    radhaeuser = radlaeufe(ob, fo, p, mats)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    zonen = glaszonen(p) + p.get("zonen", [])
    deckel = zonen_anwenden(bm, fo, zonen, mats)
    bm.to_mesh(ob.data)
    bm.free()
    return ob, zonen, radhaeuser, deckel


def linsen_bauen(ob_haut, fo: Form, zonen: list, mats):
    """Projektorlinsen in Leuchtenzonen: Chromtopf mit leuchtendem Kern.

    Zonenschlüssel ``linsen``: ``{"anzahl": n, "radius": r, "lage": 0..1
    (Höhe im Polygon), "kern": Material, "topf": Material}``. Die Linsen
    sitzen per Strahl auf dem vertieften Boden der Zone — so bekommt der
    Scheinwerfer Tiefe, statt eine flache Leuchtfläche zu sein. Zonen ohne
    ``linsen`` bleiben unberührt.
    """
    ms = fo.ms
    teile = []
    erlaubt = {KAROSSERIE_MATS.index(n) for n in
               ("licht_vorn", "scheinwerferglas", "kunststoff", "zierteil", "licht_hinten", "chrom")}
    for z in zonen:
        ln = z.get("linsen")
        if not ln:
            continue
        ansicht = z["ansicht"]
        ia, ib, ic = ACHSEN[ansicht]
        for poly in zone_polygone(z, ms):
            a0, a1 = min(q[0] for q in poly), max(q[0] for q in poly)
            b0, b1 = min(q[1] for q in poly), max(q[1] for q in poly)
            n = ln.get("anzahl", 2)
            r = ln.get("radius", min(0.032, 0.32 * (b1 - b0)))
            rand = ln.get("rand_anteil", 0.22)
            for k in range(n):
                a = a0 + (a1 - a0) * (rand + (1 - 2 * rand) * (k + 0.5) / n)
                b = b0 + (b1 - b0) * ln.get("lage", 0.5)
                start = [0.0, 0.0, 0.0]
                start[ia], start[ib] = a, b
                richtung = [0.0, 0.0, 0.0]
                start[ic] = -10.0 if ansicht == "hinten" else 10.0
                richtung[ic] = 1.0 if ansicht == "hinten" else -1.0
                ok, ort, normale, fi = ob_haut.ray_cast(Vector(start), Vector(richtung))
                if not ok or ob_haut.data.polygons[fi].material_index not in erlaubt:
                    continue
                topf = zylinder_x("linse", (0, 0, 0), r, 0.02, mats[ln.get("topf", "chrom")], segmente=20)
                kern = zylinder_x("linsenkern", (0.004, 0, 0), r * 0.62, 0.02, mats[ln.get("kern", "licht_vorn")],
                                  segmente=16)
                linse = g.verbinden([topf, kern], "linse")
                teile.append(auf_flaeche(linse, ort, normale, 0.006))
    return teile


def fahrzeug_bauen(key: str, p: dict, ausgabe: Path, vorschau_ordner: Path | None,
                   draufsicht_ordner: Path | None = None):
    g.szene_leeren()
    ms = Masse(key, p)
    fo = Form(p, ms)
    mats = materialien(p)

    karosserie, zonen, radhaeuser, deckel = karosserie_bauen(fo, p, mats)
    lamellen = lamellen_bauen(karosserie, fo, zonen, mats) + linsen_bauen(karosserie, fo, zonen, mats)
    if any(z.get("leuchte") or z.get("gitter") for z in zonen):
        treffer = tb.Treffer(karosserie)
        lamellen += leuchten_bauen(karosserie, treffer, fo, zonen, mats, deckel)
        lamellen += gitter_bauen(treffer, fo, zonen, mats)
    for pol in karosserie.data.polygons:
        pol.use_smooth = True
    g.glatt(karosserie, p.get("glatt_grad", 40))
    anbau = anbauteile(karosserie, fo, p, mats) + radlauf_lippen(karosserie, fo, p, mats)
    tp = p.get("teile")
    if tp is not None and tp.get("innenraum", {}) is not False:
        innen = ti.innenraum(fo, p, tp.get("innenraum") or {}, mats)
    else:
        innen = innenraum(fo, p, mats)
    karo = g.verbinden([karosserie] + lamellen + radhaeuser + anbau + innen, "karosserie")
    ms.hoehe = max(v.co.z for v in karo.data.vertices)

    raeder, naben, saettel = [], {}, []
    rr = p.get("zoll", 17) * 0.0254 / 2
    for kurz, (vorn, seite) in RADNAMEN.items():
        ob, nabe = rad_bauen(ms, p, mats, f"rad_{kurz}", vorn, seite)
        raeder.append(ob)
        naben[f"rad_{kurz}"] = [round(c, 5) for c in nabe]
        saettel.append(sattel_bauen(ms, p, mats, f"sattel_{kurz}", vorn, seite, rr))

    dreiecke = {o.name: g.dreiecke(o) for o in [karo] + raeder + saettel}
    g.glb_schreiben(ausgabe / f"{key}.glb")

    teile = {
        "fahrzeug": key,
        "quelle": "tools/blender/fahrzeug_bauen.py",
        "laenge_m": round(ms.laenge, 4),
        "breite_m": round(ms.breite_gesamt, 4),
        "hoehe_m": round(ms.hoehe, 4),
        "raddurchmesser_m": round(ms.rad_d, 4),
        "radstand_m": round(ms.radstand, 4),
        "achsen": {"vorne": ["rad_vl", "rad_vr"], "hinten": ["rad_hl", "rad_hr"]},
        "gelenkt": ["rad_vl", "rad_vr"],
        "raeder": [{"name": n, "nabe": naben[n], "dreiecke": dreiecke[n]}
                   for n in ("rad_vl", "rad_vr", "rad_hl", "rad_hr")],
        "saettel": [f"sattel_{k}" for k in RADNAMEN],
        "werkslack": p["lack"],
        "dreiecke_karosserie": dreiecke["karosserie"],
    }
    g.json_schreiben(ausgabe / f"{key}_teile.json", teile)
    print(f"[fahrzeug] {key}: {sum(dreiecke.values())} Dreiecke "
          f"(Karosserie {dreiecke['karosserie']}), "
          f"L={ms.laenge:.2f} B={ms.breite_gesamt:.2f} H={ms.hoehe:.2f}")

    if draufsicht_ordner is not None:
        draufsicht(draufsicht_ordner / f"{key}_oben.png", ms)
    if vorschau_ordner is not None:
        vorschau_fahrzeug(vorschau_ordner / f"{key}_vorn.png", ziel=(0, 0, 0.6), abstand=10,
                          azimut_grad=35, hoehe_grad=14)
        vorschau_fahrzeug(vorschau_ordner / f"{key}_hinten.png", ziel=(0, 0, 0.6), abstand=10,
                          azimut_grad=215, hoehe_grad=18)
        vorschau_fahrzeug(vorschau_ordner / f"{key}_seite.png", ziel=(0, 0, 0.7), abstand=12,
                          azimut_grad=90, hoehe_grad=2)


def fugen_zonen(p) -> list:
    """Fugen der Stoßfänger als schmale Rillen rund um Front und Heck.

    ``stossfaenger``: ``{"vorn": [z, u_ab], "hinten": [z, u_bis]}`` — eine
    waagerechte Rille in Höhe ``z`` vor ``u_ab`` bzw. hinter ``u_bis``. Die
    Seitenansicht mit ``n_min = -1`` trifft Flanke und Stirnseite zugleich,
    so läuft die Fuge ohne Absatz um die Ecke.
    """
    zonen = []
    st = p.get("stossfaenger", {})
    for art, (z, u) in st.items():
        u0, u1 = (u, 1.3) if art == "vorn" else (-0.3, u)
        zonen.append({"ansicht": "seite", "punkte": [[u0, z - 0.003], [u1, z - 0.003], [u1, z + 0.003], [u0, z + 0.003]],
                      "n_min": -1.0, "mat": "kunststoff",
                      "stufen": [{"dicke": 0.001, "tiefe": -0.005, "rand": "kunststoff"}]})
    # Fugen der Teile-Bibliothek: Rillen entlang frei gezogener Linien.
    for fu in (p.get("teile") or {}).get("fugen", []):
        punkte = [list(q) for q in fu["punkte"]]
        if fu.get("geschlossen"):
            punkte.append(list(punkte[0]))
        z = {"ansicht": fu["ansicht"], "linie": fu.get("breite_m", 0.005), "punkte": punkte,
             "mat": "kunststoff",
             "stufen": [{"dicke": 0.0008, "tiefe": -fu.get("tiefe_m", 0.005), "rand": "kunststoff"}]}
        for k in ("n_min", "auf", "spiegeln", "symmetrisch", "und", "u", "z", "segmente"):
            if k in fu:
                z[k] = fu[k]
        zonen.append(z)
    return zonen


def radlauf_lippen(karosserie, fo: Form, p, mats):
    """Gebördelte Kante um jeden Radlauf: ein dünner Wulst auf der Haut."""
    if not p.get("radlauf_lippe", True):
        return []
    ms = fo.ms
    teile = []
    r = ms.rad_r + p.get("radlauf_spiel_m", 0.04) + 0.012
    dicke = p.get("lippe_m", 0.014)
    for achse_x in (ms.achse_vorn, ms.achse_hinten):
        for seite in (1, -1):
            ringe = []
            for i in range(41):
                w = math.radians(-8 + 196 * i / 40)
                x = achse_x + r * math.cos(w)
                z = ms.rad_r + r * math.sin(w)
                t = strahl(karosserie, (x, seite * (ms.breite_gesamt + 1), z), (0, -seite, 0))
                if t is None or abs(t[0].y) < ms.spur_halb:
                    ringe.append(None)
                    continue
                y = abs(t[0].y) - dicke * 0.35
                ring = []
                for j in range(8):
                    a = 2 * math.pi * j / 8
                    rr = dicke * (1 + 0.0 * math.cos(a))
                    ring.append((x + math.cos(w) * rr * math.cos(a), seite * (y + rr * math.sin(a)),
                                 z + math.sin(w) * rr * math.cos(a)))
                ringe.append(ring)
            # Nur zusammenhängende Stücke verbinden.
            stueck = []
            for ring in ringe + [None]:
                if ring is None:
                    if len(stueck) > 2:
                        teile.append(netz_aus_ringen("radlauflippe", stueck, mats[p.get("lippe_mat", "lack")],
                                                     kappen=True))
                    stueck = []
                else:
                    stueck.append(ring)
    return teile


def parameter_laden() -> dict:
    """Alle Fahrzeuge mit aufgelöster Vorlage."""
    with open(PARAMETER, encoding="utf-8") as fh:
        alle = json.load(fh)
    # Je Fahrzeug darf eine eigene Datei tools/blender/fahrzeuge/<key>.json den
    # Eintrag aus fahrzeuge.json ersetzen — so lassen sich Fahrzeuge getrennt
    # bearbeiten, ohne dass zwei Leute dieselbe Datei anfassen.
    einzeln = PARAMETER.parent / "fahrzeuge"
    if einzeln.is_dir():
        for datei in sorted(einzeln.glob("*.json")):
            with open(datei, encoding="utf-8") as fh:
                alle[datei.stem] = json.load(fh)
    vorlagen = alle.pop("_vorlagen", {})
    ergebnis = {}
    for key, eintrag in alle.items():
        if key.startswith("_"):
            continue
        p = json.loads(json.dumps(vorlagen.get(eintrag.get("vorlage", ""), {})))
        for k, v in eintrag.items():
            if isinstance(v, dict) and isinstance(p.get(k), dict):
                p[k] = {**p[k], **v}
            else:
                p[k] = v
        # Zonen der Vorlage *nach* denen des Eintrags: dort stehen Fugen, die
        # nur noch über Lack laufen sollen, nicht durch Leuchten oder Gitter.
        basis = vorlagen.get(eintrag.get("vorlage", ""), {})
        if "zonen" in eintrag and basis.get("zonen") and not eintrag.get("zonen_ersetzen"):
            p["zonen"] = eintrag["zonen"] + basis["zonen"]
        p["zonen"] = p.get("zonen", []) + fugen_zonen(p)
        p["_key"] = key
        ergebnis[key] = p
    return ergebnis


def main() -> None:
    args = g.argumente()
    wahl = "alle"
    vorschau_ordner = None
    draufsicht_ordner = None
    ausgabe = ZIEL
    i = 0
    while i < len(args):
        if args[i] == "--fahrzeug":
            wahl = args[i + 1]
            i += 2
        elif args[i] == "--vorschau":
            vorschau_ordner = Path(args[i + 1])
            i += 2
        elif args[i] == "--ausgabe":
            ausgabe = Path(args[i + 1])
            i += 2
        elif args[i] == "--draufsicht":
            draufsicht_ordner = Path(args[i + 1])
            i += 2
        else:
            i += 1
    alle = parameter_laden()
    schluessel = list(alle) if wahl == "alle" else wahl.split(",")
    for key in schluessel:
        fahrzeug_bauen(key, alle[key], ausgabe, vorschau_ordner, draufsicht_ordner)


if __name__ == "__main__":
    main()
