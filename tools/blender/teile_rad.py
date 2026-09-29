"""Teile-Bibliothek, Räder: Reifen, Felge, Bremsscheibe, Bremssattel, Radhaus.

Läuft in Blender. Alles in Radkoordinaten: Ursprung in der Nabenmitte,
Drehachse Y, Außenseite bei +Y (``spiegeln`` macht daraus die rechte Seite).
Winkel ``w`` laufen in der XZ-Ebene von +X nach +Z. Was sich mit dem Rad
dreht, ist um Y rotationssymmetrisch oder regelmäßig verteilt — bis auf das
Ventil, das zu klein ist, um zu eiern.

Aufbau
======

Die Spielgeometrie bleibt sparsam, trägt aber jede Form, die man aus der
Nähe sieht: Reifenwulst, Felgenhorn, Profilrillen und -blöcke, Speichen mit
Tiefe und Auslauf, Nietenkranz, Bremsscheibe mit Topf, Sattel und
Staubschutzblech. Feinheiten stehen in gebackenen Texturen
(``backen_rad.py``), gemeinsam für alle vier Räder eines Autos:

* **``rad_reifen``** — Farbe, ORM, Normalen. UV: ``u = w / π`` (eine
  Kachel je halbe Umdrehung; Schrift und Profil wiederholen sich nach 180°),
  ``v`` entlang des Reifenquerschnitts, innere Flanke → Lauffläche → äußere
  Flanke. Flankenschrift mit erfundener Marke, Zierringe, Samtband,
  Lamellen in den Blöcken, Laufspuren.
* **``rad_metall``** — ein Atlas für alles Metall am Rad und den Sattel:

  ====  ==================  =================================================
  A     u 0–0.5             Felge, ein Sektor (alle Sektoren teilen die Texel)
                            und die Nabe; Smart-UV-Projektion
  B     u 0.5–0.75          Bremsscheibe und Topf, polar (eine Periode des
                            Loch-/Schlitzmusters)
  C     u 0.75–1, v 0.25–1  Bremssattel, abgewickelt entlang des Bogens
  D     u 0.75–1, v 0–0.25  einfarbige Felder (Chrom, Gummi, Lack …);
                            Kleinteile legen ihre UV auf die Feldmitte
  ====  ==================  =================================================

Rechte Räder werden gespiegelt. Flanken- und Sattelflächen tragen dazu das
Flächenattribut ``uv_spiegeln`` mit der Achse ``uv_achse``: ``spiegeln``
setzt dort ``u = achse − u``, sonst stünde die Schrift in Spiegelschrift.

Parameter (``teile`` der Fahrzeugdatei, alle optional)::

    "reifen": {"profil": "sport"|"strasse"|"slick", "bloecke": 24 (gerade),
               "rillen": [-0.2, 0.2], "rille_m": 0.012, "tiefe_m": 0.007,
               "wulst_m": 0.007, "pfeil": 0.35,
               "modell": "APEX R2" (Flankenschrift), "schrift": "schwarz"|"weiss"},
    "felge":  {"radmuttern": 5, "mutter_mat": "chrom"|"titan"|"schwarz",
               "nabenkappe": "emblem"|"glatt", "speiche_tiefe_m": 0.03,
               "speichen": 15 (Vielspeichen), "finish": "metall"|"lack"|"satin",
               "diamant": false (Speichenfront glanzgedreht),
               "lippe": "lack"|"poliert", "schuessel_m": 0.0 (Stufenlippe),
               "nieten": 0 (Schrauben am Stern, Vielfaches der Sektoren)},
    "bremse": {"art": "gelocht"|"geschlitzt"|"glatt", "abstand_m": 0.055,
               "scheibe": "stahl"|"keramik", "topf": "schwarz"|"alu"|"lack"},
    "sattel": {"winkel_grad": 140, "spanne_grad": 56, "schrift": "KESTRA"}

Oberste Schlüssel wie bisher: ``felge`` (Muster), ``zoll``, ``felgenfarbe``,
``sattelfarbe``, ``felgentiefe_m``, ``felgen_schaufeln``,
``felgen_bogen_grad``, ``felgen_schaufel_breite_m``.
"""
from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import backen_rad as bk
import gemeinsam as g

#: Erfundene Marken (keine echten Hersteller).
REIFENMARKE = "TORVANE"
SATTELMARKE = "KESTRA"

#: Atlasbereiche von ``rad_metall`` (u0, v0, u1, v1).
BEREICH_FELGE = (0.0, 0.0, 0.5, 1.0)
BEREICH_SCHEIBE = (0.5, 0.0, 0.75, 1.0)
BEREICH_SATTEL = (0.75, 0.25, 1.0, 1.0)
BEREICH_FELDER = (0.75, 0.0, 1.0, 0.25)
FELDER = ["chrom", "gummi", "kunststoff", "schild", "sattellack", "felgenlack", "mutter",
          "titan", "belag", "schwarz", "alu"]

#: Teilnummern (Flächenattribut ``teil``), danach richtet sich die Oberfläche.
T_FLANKE_AUSSEN, T_FLANKE_INNEN, T_LAUF, T_REIFEN_INNEN = 1, 2, 3, 4
T_BETT, T_HORN, T_LIPPE, T_SITZ = 10, 11, 12, 13
T_SPEICHE, T_SCHAUFEL, T_RING, T_AEROGRUND = 20, 21, 22, 23
T_NABE, T_NIETE = 30, 31
T_REIBRING, T_RAND, T_TOPF = 40, 41, 42
T_SATTEL = 50

#: Speichenmuster: (Sektoren, [(Winkel °, Breite Nabe, Breite Rand, Bogen °, Start/rr)])
MUSTER = {
    "fuenf": (5, [(0.0, 0.062, 0.05, 0.0, None)]),
    "zehn": (5, [(-7.0, 0.044, 0.032, 0.0, None), (7.0, 0.044, 0.032, 0.0, None)]),
    "vielspeichen": (15, [(0.0, 0.026, 0.017, 0.0, None)]),
    "doppelspeichen": (10, [(-3.4, 0.022, 0.015, 0.0, None), (3.4, 0.022, 0.015, 0.0, None)]),
    "y": (6, [(0.0, 0.05, 0.03, 0.0, None), (-9.0, 0.026, 0.02, 0.0, 0.55),
              (9.0, 0.026, 0.02, 0.0, 0.55)]),
    "tiefbett": (6, [(0.0, 0.05, 0.036, 0.0, None)]),
    "zentral": (5, [(-6.0, 0.034, 0.024, 0.0, None), (6.0, 0.034, 0.024, 0.0, None)]),
    # Kreuzspeichen: jede läuft von −11° an der Nabe nach +11° am Rand und umgekehrt
    "mesh": (10, [(0.0, 0.021, 0.016, 22.0, None), (0.0, 0.021, 0.016, -22.0, None)]),
}


# ---------------------------------------------------------------------------
# Netzbau mit UV, Teilnummer und Spiegelachse
# ---------------------------------------------------------------------------

class Netz:
    """Flächen mit UV je Ecke, Teilnummer und Materialplatz je Fläche."""

    def __init__(self) -> None:
        self.punkte: list = []
        self.flaechen: list = []

    def p(self, co) -> int:
        self.punkte.append(tuple(co))
        return len(self.punkte) - 1

    def f(self, idx, uv=None, teil: int = 0, mat: int = 0, achse=None, sektor: int = 0):
        self.flaechen.append((tuple(idx), uv, teil, mat, achse, sektor))

    def anhaengen(self, anderes: "Netz", matrix=None) -> None:
        basis = len(self.punkte)
        for co in anderes.punkte:
            self.punkte.append(tuple(matrix @ Vector(co)) if matrix is not None else co)
        for idx, uv, teil, mat, achse, sektor in anderes.flaechen:
            self.flaechen.append((tuple(i + basis for i in idx), uv, teil, mat, achse, sektor))

    def volumen(self, ab: int = 0) -> float:
        v = 0.0
        for idx, *_ in self.flaechen[ab:]:
            a = Vector(self.punkte[idx[0]])
            for k in range(1, len(idx) - 1):
                b, c = Vector(self.punkte[idx[k]]), Vector(self.punkte[idx[k + 1]])
                v += a.dot(b.cross(c)) / 6.0
        return v

    def umdrehen(self, ab: int = 0) -> None:
        for k in range(ab, len(self.flaechen)):
            idx, uv, *rest = self.flaechen[k]
            self.flaechen[k] = (tuple(reversed(idx)), list(reversed(uv)) if uv else uv, *rest)

    def nach_aussen(self, ab: int) -> None:
        """Geschlossenen Körper (Flächen ab ``ab``) nach außen richten."""
        if self.volumen(ab) < 0:
            self.umdrehen(ab)

    # -- Grundkörper -------------------------------------------------------

    def drehband(self, profil, w0: float, w1: float, seg: int, teil, uv=None, mat: int = 0,
                 achse=None, sektor: int = 0, mitte=(0.0, 0.0), geschlossen: bool = False) -> None:
        """Profil ``[(r, y), …]`` um Y von ``w0`` bis ``w1`` drehen.

        Sichtbar ist die Seite **rechts der Laufrichtung** (r nach rechts, y
        nach oben). ``teil``: Zahl oder Liste je Profilabschnitt. ``uv``:
        ``fn(i_profil, k_ring) -> (u, v)`` oder None. ``geschlossen``: auch
        der Abschnitt vom letzten zum ersten Punkt.
        """
        cx, cz = mitte
        ringe = []
        for k in range(seg + 1):
            w = w0 + (w1 - w0) * k / seg
            c, s = math.cos(w), math.sin(w)
            ringe.append([self.p((cx + r * c, y, cz + r * s)) for r, y in profil])
        n = len(profil)
        abschnitte = n if geschlossen else n - 1
        for k in range(seg):
            a, b = ringe[k], ringe[k + 1]
            for i in range(abschnitte):
                i2 = (i + 1) % n
                t = teil[i] if isinstance(teil, (list, tuple)) else teil
                if t is None:
                    continue
                uvs = None
                if uv is not None:
                    uvs = [uv(i, k), uv(i2, k), uv(i2, k + 1), uv(i, k + 1)]
                self.f((a[i], a[i2], b[i2], b[i]), uvs, t, mat,
                       achse[i] if isinstance(achse, (list, tuple)) else achse, sektor)

    def loft(self, ringe, teil: int, mat: int = 0, uv=None, deckel=True, deckel_uv=None,
             achse=None, sektor: int = 0) -> None:
        """Geschlossene Querschnitte zu einem Körper verbinden, nach außen gerichtet.

        ``uv``: ``fn(k_ring, j_punkt) -> (u, v)``; die Naht liegt zwischen
        letztem und erstem Punkt (dort ``j = n``)."""
        start = len(self.flaechen)
        idx = [[self.p(q) for q in ring] for ring in ringe]
        n = len(ringe[0])
        for k in range(len(ringe) - 1):
            for j in range(n):
                j2 = (j + 1) % n
                uvs = None
                if uv is not None:
                    uvs = [uv(k, j), uv(k, j + 1), uv(k + 1, j + 1), uv(k + 1, j)]
                self.f((idx[k][j], idx[k][j2], idx[k + 1][j2], idx[k + 1][j]), uvs, teil, mat,
                       achse, sektor)
        if deckel:
            for ring in (idx[0], idx[-1]):
                self.f(list(reversed(ring)) if ring is idx[0] else ring,
                       [deckel_uv] * n if deckel_uv else None, teil, mat, None, sektor)
        self.nach_aussen(start)

    # -- Blender-Objekt ----------------------------------------------------

    def objekt(self, name: str, mats) -> bpy.types.Object:
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.punkte, [], [f[0] for f in self.flaechen])
        uvl = me.uv_layers.new(name="UVMap")
        daten = []
        for idx, uv, *_ in self.flaechen:
            daten.extend(uv if uv else [(0.0, 0.0)] * len(idx))
        uvl.data.foreach_set("uv", [c for q in daten for c in q])
        teil = me.attributes.new("teil", "FLOAT", "FACE")
        teil.data.foreach_set("value", [float(f[2]) for f in self.flaechen])
        sp = me.attributes.new("uv_spiegeln", "BOOLEAN", "FACE")
        sp.data.foreach_set("value", [f[4] is not None for f in self.flaechen])
        ax = me.attributes.new("uv_achse", "FLOAT", "FACE")
        ax.data.foreach_set("value", [float(f[4]) if f[4] is not None else 0.0 for f in self.flaechen])
        sk = me.attributes.new("sektor", "INT", "FACE")
        sk.data.foreach_set("value", [int(f[5]) for f in self.flaechen])
        me.polygons.foreach_set("material_index", [f[3] for f in self.flaechen])
        me.update()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        for m in mats:
            ob.data.materials.append(m)
        return ob


def _ccw(profil):
    """Profil gegen den Uhrzeigersinn (r rechts, y oben): Außenseite rechts."""
    fl = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(profil, profil[1:] + profil[:1]))
    return profil if fl > 0 else list(reversed(profil))


def _umriss_ccw(umriss):
    """Geschlossener Umriss ``[((r, y), teil_des_abschnitts), …]`` gegen den
    Uhrzeigersinn; die Teile wandern mit ihren Abschnitten mit."""
    pkt = [q for q, _ in umriss]
    teile = [t for _, t in umriss]
    fl = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pkt, pkt[1:] + pkt[:1]))
    if fl > 0:
        return pkt, teile
    n = len(pkt)
    # Abschnitt j des umgedrehten Umrisses ist Abschnitt n-2-j des alten
    return list(reversed(pkt)), [teile[(n - 2 - j) % n] for j in range(n)]


def feld_uv(name: str, bereich=BEREICH_FELDER):
    """UV-Mitte eines einfarbigen Felds im Atlas."""
    k = FELDER.index(name)
    u0, v0, u1, v1 = bereich
    spalten, zeilen = 8, 4
    return (u0 + (u1 - u0) * ((k % spalten) + 0.5) / spalten,
            v0 + (v1 - v0) * ((k // spalten) + 0.5) / zeilen)


def _in_bereich(uv, bereich):
    u0, v0, u1, v1 = bereich
    return (u0 + (u1 - u0) * uv[0], v0 + (v1 - v0) * uv[1])


# ---------------------------------------------------------------------------
# Reifen
# ---------------------------------------------------------------------------

def reifen_netz(R: float, b: float, rr: float, tp: dict, lod: int = 0):
    """Reifen mit gerundeter Flanke, Felgenschutzkante und Laufflächenprofil.

    Umfangsrillen (``rillen``) laufen durch; Querrillen entstehen je Block
    (``bloecke`` je Umfang) aus vier Ringen, pfeilförmig versetzt, nur an
    den Schultern. ``sport``: zwei Rillen, breite Mittelrippe, tiefe
    Schulterblöcke; ``strasse``: vier schmale Rillen, viele flache
    Schulterblöcke; ``slick``: glatt. Liefert (Netz, Profilangaben für die
    Textur).
    """
    art = tp.get("profil", "sport")
    halb = b / 2
    tiefe = tp.get("tiefe_m", {"strasse": 0.0045}.get(art, 0.007))
    wulst = tp.get("wulst_m", 0.007)
    rb = tp.get("rille_m", {"strasse": 0.009}.get(art, 0.012))
    rillen = tp.get("rillen", {"sport": [-0.2, 0.2], "strasse": [-0.3, -0.1, 0.1, 0.3]}.get(art, []))
    h = R - rr
    # Felgenschutz unten (``schutz``) und Schulter oben (``schulter``) wachsen
    # mit der Flankenhöhe; flache Sportreifen haben beides kleiner.
    schutz = min(0.03, 0.3 * h)
    schulter = min(0.034, 0.34 * h)
    # (r, y, Art): f Flanke, sr Schulterrand, s Schulter, m Mitte, r Rillengrund
    flanke = [
        (rr + 0.002, -halb + 0.02, "f"),
        (rr + 0.45 * schutz, -halb - 0.004, "f"),
        (rr + 0.75 * schutz, -halb - 0.0065, "f"),
        (rr + schutz, -halb - 0.003, "f"),
        (rr + schutz + (h - schutz - schulter) * 0.45, -halb - wulst, "f"),
        (R - schulter, -halb - wulst * 0.75, "f"),
        (R - 0.55 * schulter, -halb - wulst * 0.15, "sr"),
        (R - 0.18 * schulter, -halb + 0.012, "sr"),
    ]
    tw = halb - 0.024
    ys = [(-tw, None)]
    for rl in sorted(rillen):
        yg = rl * b
        ys += [(yg - rb / 2, None), (yg - rb * 0.3, "r"), (yg + rb * 0.3, "r"), (yg + rb / 2, None)]
    ys.append((tw, None))
    voll = []
    for (ya, ka), (yb, kb) in zip(ys, ys[1:]):
        voll.append((ya, ka))
        if ka is None and kb is None and yb - ya > 0.05:
            voll.append(((ya + yb) / 2, None))
    voll.append(ys[-1])
    grenze = max([abs(rl * b) for rl in rillen], default=halb * 0.55) - 1e-6
    lauf = []
    for y, k in voll:
        rc = R - 0.004 * (y / halb) ** 2
        if k == "r":
            lauf.append((rc - tiefe, y, "r"))
        else:
            lauf.append((rc, y, "s" if abs(y) >= grenze else "m"))
    profil = flanke + lauf + [(r_, -y, k) for r_, y, k in reversed(flanke)]
    bloecke = min(tp.get("bloecke", {"strasse": 24, "slick": 64}.get(art, 22)), 24 if art != "slick" else 64)
    bloecke += bloecke % 2          # Periode 180°: gerade Blockzahl
    anteile = {"slick": [(0.0, False)],
               "strasse": [(0.0, False), (0.87, False), (0.89, True), (0.97, True)]}.get(
        art, [(0.0, False), (0.85, False), (0.875, True), (0.965, True)])
    if art == "slick" and lod:
        bloecke = max(32, bloecke // 2)
    pfeil = tp.get("pfeil", {"strasse": 0.15}.get(art, 0.35))
    teilung = 2 * math.pi / bloecke

    # v: Bogenlänge entlang des Querschnitts (ohne Querrillen)
    s = [0.0]
    for (ra, ya, _), (rb_, yb, _) in zip(profil, profil[1:]):
        s.append(s[-1] + math.hypot(rb_ - ra, yb - ya))
    L = s[-1]
    vs = [x / L for x in s]
    n = len(profil)

    netz = Netz()
    m = bloecke * len(anteile)
    ringe = []
    winkel = []
    for k in range(bloecke):
        for f, rille in anteile:
            ring, wr = [], []
            for r_, y, art_p in profil:
                rad = r_
                if rille and art != "slick":
                    if art_p == "s":
                        rad -= tiefe
                    elif art_p == "sr":
                        rad -= tiefe * 0.35
                versatz = pfeil * teilung * (abs(y) / halb) if art_p != "f" else 0.0
                w = teilung * (k + f) + versatz
                ring.append(netz.p((rad * math.cos(w), y, rad * math.sin(w))))
                wr.append(w)
            ringe.append(ring)
            winkel.append(wr)
    for sgm in range(m):
        s2 = (sgm + 1) % m
        zu = 2 * math.pi if s2 == 0 else 0.0
        for i in range(n):
            i2 = (i + 1) % n
            ka, kb = profil[i][2], profil[i2][2]
            if i2 == 0:
                teil, achse = T_REIFEN_INNEN, None
            elif ka == "f" and kb == "f":
                aussen = profil[i][1] > 0
                teil = T_FLANKE_AUSSEN if aussen else T_FLANKE_INNEN
                achse = 0.0
            else:
                teil, achse = T_LAUF, None
            va = vs[i]
            vb = vs[i2] if i2 else vs[i]
            uv = [(winkel[sgm][i] / math.pi, va), (winkel[sgm][i2] / math.pi, vb),
                  ((winkel[s2][i2] + zu) / math.pi, vb), ((winkel[s2][i] + zu) / math.pi, va)]
            netz.f((ringe[sgm][i], ringe[sgm][i2], ringe[s2][i2], ringe[s2][i]), uv, teil, 0, achse)
    netz.nach_aussen(0)
    info = {"art": art, "halb": halb, "R": R, "rr": rr, "teilung": teilung, "pfeil": pfeil,
            "schrift_zone": (rr + schutz + 0.004, R - schulter - 0.002),
            "grenze": grenze, "rille_m": rb, "rillen": [rl * b for rl in rillen],
            "quer": [f for f, rl in anteile if rl], "tiefe": tiefe}
    return netz, info


# ---------------------------------------------------------------------------
# Felge
# ---------------------------------------------------------------------------

class Speichenform:
    """Wo Vorder- und Rückseite der Speichen liegen, je Radius."""

    def __init__(self, r0, r1, y_nabe, y_rand, tiefe):
        self.r0, self.r1 = r0, r1
        self.y_nabe, self.y_rand = y_nabe, y_rand
        self.tiefe = tiefe

    def vorn(self, r):
        tt = max(0.0, min(1.0, (r - self.r0) / (self.r1 - self.r0)))
        return self.y_nabe + (self.y_rand - self.y_nabe) * tt ** 0.8

    def hinten(self, r):
        tt = max(0.0, min(1.0, (r - self.r0) / (self.r1 - self.r0)))
        return self.vorn(r) - self.tiefe * (1 - 0.3 * tt)


def _schuessel(p: dict, tf: dict) -> float:
    return tf.get("schuessel_m", 0.075 if p.get("felge") == "tiefbett" else 0.0)


def speichenform(p: dict, tp: dict, rr: float, b: float) -> Speichenform:
    """Lage der Speichen aus den Fahrzeugparametern (auch für den Sattel)."""
    halb = b / 2
    ya = halb - 0.014
    sch = _schuessel(p, tp)
    y_rand = ya - 0.008 - sch
    if sch > 0:
        y_nabe = y_rand - 0.014
        r1 = rr - 0.04
    elif p.get("felge") in ("turbine", "aero"):
        y_nabe = y_rand - 0.022
        r1 = rr - 0.012
    else:
        y_nabe = halb - p.get("felgentiefe_m", 0.06)
        r1 = rr - 0.012
    return Speichenform(0.075, r1, y_nabe, y_rand, tp.get("speiche_tiefe_m", 0.03))


def _felgenprofil(rr: float, halb: float, form: Speichenform, sch: float):
    """Felgenbett, Horn und Lippe als geschlossener Umriss mit Teil je Abschnitt."""
    ya, yi = halb - 0.014, -halb + 0.014
    rb = rr - 0.024
    pkt = [
        ((rr - 0.007, ya - 0.001), T_HORN),      # Lippe innen
        ((rr + 0.005, ya + 0.0015), T_HORN),     # Lippenfläche
        ((rr + 0.0125, ya - 0.002), T_HORN),     # Hornrundung
        ((rr + 0.014, ya - 0.009), T_SITZ),      # Horn zum Reifen
        ((rr + 0.001, ya - 0.016), T_SITZ),      # Wulstsitz außen
        ((rr + 0.001, yi + 0.016), T_SITZ),
        ((rr + 0.014, yi + 0.009), T_SITZ),
        ((rr + 0.0125, yi + 0.002), T_BETT),
        ((rr + 0.004, yi - 0.0015), T_BETT),     # Horn innen
        ((rr - 0.008, yi + 0.004), T_BETT),
        ((rb, yi + 0.03), T_BETT),               # Tiefbett
        ((rb, form.y_rand - 0.05), T_BETT),
    ]
    if sch > 0:
        r_s = form.r1 + 0.004
        pkt += [((r_s - 0.006, form.y_rand - 0.03), T_BETT),
                ((r_s - 0.006, form.y_rand - 0.004), T_LIPPE),   # Sternrand
                ((r_s, form.y_rand + 0.001), T_LIPPE),
                ((r_s + 0.01, form.y_rand + 0.0015), T_LIPPE),   # Stufe
                ((rr - 0.012, ya - 0.012), T_LIPPE)]             # Schüssel hinauf
    else:
        pkt += [((rr - 0.016, form.y_rand - 0.022), T_BETT),
                ((rr - 0.013, ya - 0.012), T_HORN)]              # innere Lippenwand
    return pkt


def _speiche(netz: Netz, form: Speichenform, w0: float, b0: float, b1: float, bogen: float,
             r_a: float, r_e: float, stationen: int, erhoeht: float = 0.0, teil=T_SPEICHE,
             sektor: int = 1, neigung: float = 0.0) -> None:
    """Eine Speiche: gefaster Querschnitt, Ausrundung an Nabe und Rand, optional
    gebogen (``bogen`` rad von innen nach außen) und verwunden (``neigung``)."""
    ringe = []
    for k in range(stationen + 1):
        tt = k / stationen
        tt = 0.5 - 0.5 * math.cos(math.pi * tt) if stationen > 4 else tt
        r_ = r_a + (r_e - r_a) * tt
        bw = b0 + (b1 - b0) * tt
        # Ausrundung: an Rand und Nabe breiter, wie gegossen
        bw += 0.3 * b1 * max(0.0, (tt - 0.85) / 0.15) ** 2 + 0.2 * b0 * max(0.0, (0.1 - tt) / 0.1) ** 2
        yf = form.vorn(r_) + erhoeht
        yb = form.hinten(r_)
        c = min(0.003, bw * 0.12)
        kr = min(0.0008, bw * 0.03)
        hb = bw / 2
        # Seitenwände leicht nach hinten ausgestellt (Gussschräge), Front flach
        # mit einer Spur Wölbung, Fasen 45°
        quer = [(-hb * 1.08, yb), (hb * 1.08, yb), (hb, yf - c + neigung * hb),
                (hb - c, yf + neigung * (hb - c)), (0.0, yf + kr),
                (-(hb - c), yf - neigung * (hb - c)), (-hb, yf - c - neigung * hb)]
        w = w0 + bogen * tt
        cw, sw = math.cos(w), math.sin(w)
        ringe.append([(r_ * cw - q * sw, y, r_ * sw + q * cw) for q, y in quer])
    netz.loft(ringe, teil, sektor=sektor)


def felge_netz(p: dict, tf: dict, rr: float, b: float, lod: int = 0):
    """Felge: ein Sektor (Bett, Speichen, Nieten) und die Nabe.

    Liefert (Netz Sektor, Anzahl Sektoren, Netz Nabe, Speichenform)."""
    halb = b / 2
    design = p.get("felge", "fuenf")
    form = speichenform(p, tf, rr, b)
    sch = _schuessel(p, tf)
    if design in ("turbine", "aero"):
        n = p.get("felgen_schaufeln", 10 if design == "turbine" else 5)
        speichen = []
    else:
        n, speichen = MUSTER.get(design, MUSTER["fuenf"])
        if design in ("vielspeichen", "doppelspeichen"):
            n = tf.get("speichen", n)
    sektor = Netz()
    spanne = 2 * math.pi / n
    seg = max(2, int(round(56 / n))) if not lod else max(1, int(round(32 / n)))
    # Mitte des Sektors 0 liegt bei w = 0, bei gebogenen Schaufeln um den halben Bogen versetzt
    w_mitte = 0.0
    if design in ("turbine", "aero"):
        w_mitte = math.radians(p.get("felgen_bogen_grad", 28)) / 2
    wa, we = w_mitte - spanne / 2, w_mitte + spanne / 2
    pkt, teile = _umriss_ccw(_felgenprofil(rr, halb, form, sch))
    sektor.drehband(pkt, wa, we, seg, teile, sektor=1, geschlossen=True)
    stationen = (7 if n <= 6 else 5) if not lod else 3
    for versatz, b0, b1, bogen, start in speichen:
        w0 = math.radians(versatz) - math.radians(bogen) / 2
        r_a = form.r0 if start is None else rr * start
        _speiche(sektor, form, w0, b0, b1, math.radians(bogen), r_a, form.r1 + 0.006, stationen,
                 erhoeht=0.0008 if bogen > 0 else 0.0)
    if design in ("turbine", "aero"):
        _turbine(sektor, p, form, rr, halb, n, lod)
    nieten = tf.get("nieten", 36 if design == "tiefbett" else 0)
    if nieten and not lod:
        je = max(1, nieten // n)
        r_n = form.r1 + 0.009
        for k in range(je):
            w = wa + spanne * (k + 0.5) / je
            _niete(sektor, r_n, w, form.y_rand + 0.001)
    nabe = Netz()
    y_n = form.y_nabe
    nabe_profil = [(0.094, y_n - 0.016), (0.094, y_n + 0.003), (0.09, y_n + 0.012),
                   (0.07, y_n + 0.02), (0.045, y_n + 0.024), (0.036, y_n + 0.024),
                   (0.034, y_n + 0.02), (0.0, y_n + 0.02)]
    nabe.drehband(nabe_profil, 0.0, 2 * math.pi, 40 if not lod else 20, T_NABE)
    return sektor, n, nabe, form


def _turbine(netz: Netz, p: dict, form: Speichenform, rr: float, halb: float, n: int, lod: int):
    """Turbinen- und Aerofelge: Schaufeln zwischen Nabenteller und Außenring,
    bei ``aero`` eine dunkle Grundscheibe dahinter (Aerodynamik: geschlossen)."""
    design = p.get("felge")
    bogen = math.radians(p.get("felgen_bogen_grad", 28))
    sb = p.get("felgen_schaufel_breite_m", 0.03)
    spanne = 2 * math.pi / n
    w_mitte = bogen / 2
    wa, we = w_mitte - spanne / 2, w_mitte + spanne / 2
    seg = max(2, int(round(72 / n))) if not lod else 2
    y_r = form.y_rand
    ring = [(rr * 0.8, y_r - 0.028), (rr * 0.8, y_r - 0.004), (rr * 0.81, y_r),
            (rr - 0.012, y_r + 0.002), (rr - 0.008, y_r - 0.02)]
    netz.drehband(_ccw(ring), wa, we, seg, T_RING, sektor=1, geschlossen=True)
    if design == "aero":
        grund = [(rr * 0.42, y_r - 0.03), (rr - 0.01, y_r - 0.03)]
        netz.drehband(list(reversed(grund)), wa, we, seg, T_AEROGRUND, sektor=1)
    r0, r1 = rr * 0.4, rr * 0.82
    stationen = 8 if not lod else 4
    ringe = []
    for k in range(stationen + 1):
        tt = k / stationen
        r_ = r0 + (r1 - r0) * tt
        w = bogen * tt
        bw = sb * (1 - 0.35 * tt) / 2
        y0, y1 = y_r - 0.03, y_r - 0.004 + 0.003 * math.sin(math.pi * tt)
        tx, tz = -math.sin(w), math.cos(w)
        cx, cz = r_ * math.cos(w), r_ * math.sin(w)
        # Verwunden wie eine Turbinenschaufel: eine Kante höher als die andere
        quer = [(-bw, y0), (bw, y0), (bw, y1 - 0.008), (bw * 0.6, y1), (-bw * 0.8, y1 - 0.004),
                (-bw, y1 - 0.012)]
        ringe.append([(cx + q * tx, y, cz + q * tz) for q, y in quer])
    netz.loft(ringe, T_SCHAUFEL, sektor=1)


def _niete(netz: Netz, r: float, w: float, y: float) -> None:
    """Sechskantschraube am Stern einer mehrteiligen Felge."""
    cx, cz = r * math.cos(w), r * math.sin(w)
    prof = [(0.0042, y - 0.001), (0.0042, y + 0.0025), (0.0028, y + 0.0042), (0.0, y + 0.0046)]
    netz.drehband(prof, 0.0, 2 * math.pi, 6, T_NIETE, sektor=1, mitte=(cx, cz))


def muttern_netz(p: dict, tf: dict, form: Speichenform, lod: int) -> Netz:
    """Radmuttern, Zentralmutter, Nabenkappe und Ventil: einfarbige Felder."""
    netz = Netz()
    y_n = form.y_nabe
    design = p.get("felge", "fuenf")
    if design == "zentral":
        uv = feld_uv("mutter")
        prof = [(0.05, y_n + 0.016), (0.05, y_n + 0.034), (0.046, y_n + 0.042), (0.03, y_n + 0.046),
                (0.03, y_n + 0.058), (0.02, y_n + 0.062), (0.0, y_n + 0.062)]
        start = len(netz.flaechen)
        netz.drehband(prof, math.pi / 12, math.pi / 12 + 2 * math.pi, 12, T_NABE)
        for k in range(start, len(netz.flaechen)):
            idx, _uv, *rest = netz.flaechen[k]
            netz.flaechen[k] = (idx, [uv] * len(idx), *rest)
        # Sicherungsstift quer durch die Mutter
        stift = Netz()
        stift.drehband([(0.004, -0.034), (0.004, 0.034)], 0.0, 2 * math.pi, 8, T_NABE)
        for k in range(len(stift.flaechen)):
            idx, _uv, *rest = stift.flaechen[k]
            stift.flaechen[k] = (idx, [feld_uv("chrom")] * len(idx), *rest)
        netz.anhaengen(stift, Matrix.Translation((0, y_n + 0.052, 0)) @ Matrix.Rotation(math.pi / 2, 4, "X"))
        return netz
    anzahl = tf.get("radmuttern", 5)
    uv = feld_uv({"chrom": "chrom", "titan": "titan", "schwarz": "schwarz"}.get(
        tf.get("mutter_mat", "chrom"), "chrom"))
    for i in range(anzahl):
        w = 2 * math.pi * i / anzahl + math.pi / anzahl
        x, z = 0.058 * math.cos(w), 0.058 * math.sin(w)
        prof = [(0.0105, y_n + 0.012), (0.0105, y_n + 0.028), (0.0085, y_n + 0.032),
                (0.0045, y_n + 0.034), (0.0, y_n + 0.034)]
        start = len(netz.flaechen)
        netz.drehband(prof, math.pi / 6, math.pi / 6 + 2 * math.pi, 6, 0, mitte=(x, z))
        for k in range(start, len(netz.flaechen)):
            idx, _uv, *rest = netz.flaechen[k]
            netz.flaechen[k] = (idx, [uv] * len(idx), *rest)
    kappe = [(0.033, y_n + 0.018), (0.033, y_n + 0.03), (0.029, y_n + 0.036),
             (0.019, y_n + 0.038), (0.0, y_n + 0.038)]
    start = len(netz.flaechen)
    netz.drehband(kappe, 0.0, 2 * math.pi, 24 if not lod else 12, 0)
    for k in range(start, len(netz.flaechen)):
        idx, _uv, *rest = netz.flaechen[k]
        netz.flaechen[k] = (idx, [feld_uv("kunststoff")] * len(idx), *rest)
    return netz


def ventil_netz(rr: float, halb: float, form: Speichenform, w: float) -> Netz:
    """Ventil am Felgenbett, schräg nach außen, zwischen zwei Speichen."""
    netz = Netz()
    for prof, feld in (([(0.0038, 0.0), (0.0038, 0.014), (0.0026, 0.016)], "gummi"),
                       ([(0.0026, 0.016), (0.003, 0.017), (0.003, 0.026), (0.0022, 0.028),
                         (0.0, 0.028)], "chrom")):
        teil = Netz()
        teil.drehband(prof, 0.0, 2 * math.pi, 8, 0)
        for k in range(len(teil.flaechen)):
            idx, _uv, *rest = teil.flaechen[k]
            teil.flaechen[k] = (idx, [feld_uv(feld)] * len(idx), *rest)
        netz.anhaengen(teil)
    # Fuß an der inneren Lippenwand, Kappe knapp unter der Lippe
    r0 = rr - 0.014
    y0 = halb - 0.014 - 0.03
    # Achse schräg nach außen und zur Mitte
    rich = Vector((-0.3, 1.0, 0.0)).normalized()
    dreh = Vector((0, 1, 0)).rotation_difference(rich).to_matrix().to_4x4()
    m = Matrix.Rotation(-w, 4, "Y") @ Matrix.Translation((r0, y0, 0)) @ dreh
    aus = Netz()
    aus.anhaengen(netz, m)
    return aus


# ---------------------------------------------------------------------------
# Bremse
# ---------------------------------------------------------------------------

def _bremslage(form: Speichenform, rr: float, tb: dict):
    """(r_o, r_i, y0, y1, y_topf): Scheibe weiter innen, wenn der Stern tief sitzt."""
    r_o = rr - tb.get("abstand_m", 0.055)
    r_i = r_o * 0.56
    frei = min(form.hinten(r_o - 0.05 + k * 0.01) for k in range(8))
    dy = min(0.0, frei - 0.066)
    return r_o, r_i, -0.034 + dy, -0.006 + dy, form.y_nabe - 0.016


def scheibe_periode(tb: dict) -> float:
    """Winkel einer UV-Periode der Scheibe (Vielfaches des Lochmusters)."""
    art = tb.get("art", "gelocht")
    return math.radians({"gelocht": 40.0, "geschlitzt": 30.0}.get(art, 30.0))


def scheibe_netz(rr: float, form: Speichenform, tb: dict, lod: int = 0) -> Netz:
    """Innenbelüftete Scheibe mit Topf, UV polar in Bereich B.

    Eine UV-Periode (``scheibe_periode``) umfasst ganze Loch-/Schlitzmuster;
    alle Perioden teilen sich die Texel. v: Reibflächen 0–0.44 nach Radius
    (Vorder- und Rückseite gemeinsam), Außenrand 0.46–0.58, Topf 0.6–1.
    """
    r_o, r_i, y0, y1, y_topf = _bremslage(form, rr, tb)
    periode = scheibe_periode(tb)
    je = (5 if periode > math.radians(35) else 4) if not lod else 2
    anzahl = int(round(2 * math.pi / periode))
    r_t = r_i - 0.014
    umriss = [
        ((r_i, y0), T_REIBRING), ((r_o - 0.002, y0), T_RAND), ((r_o, y0 + 0.002), T_RAND),
        ((r_o, y1 - 0.002), T_RAND), ((r_o - 0.002, y1), T_REIBRING), ((r_i, y1), T_TOPF),
        ((r_i - 0.007, y1), T_TOPF), ((r_i - 0.011, y_topf - 0.002), T_TOPF),
        ((r_t, y_topf), T_TOPF), ((0.074, y_topf), T_TOPF), ((0.074, y_topf - 0.005), T_TOPF),
        ((r_i - 0.018, y_topf - 0.005), T_TOPF), ((r_t, y0), T_REIBRING),
    ]
    pkt = [q for q, _ in umriss]
    n = len(pkt)
    s_topf = {5: 0.0}
    for i in range(5, 12):
        s_topf[i + 1] = s_topf[i] + math.hypot(pkt[i + 1][0] - pkt[i][0], pkt[i + 1][1] - pkt[i][1])

    def v_von(abschnitt: int, i: int) -> float:
        r, y = pkt[i]
        if abschnitt in (0, 4, 12):
            return 0.44 * (r - r_t) / (r_o - r_t)
        if abschnitt in (1, 2, 3):
            return 0.46 + 0.12 * (y - y0) / (y1 - y0)
        return 0.6 + 0.4 * s_topf[i] / s_topf[12]

    netz = Netz()
    for per in range(anzahl):
        ringe = []
        for k in range(je + 1):
            w = per * periode + periode * k / je
            ringe.append([netz.p((r * math.cos(w), y, r * math.sin(w))) for r, y in pkt])
        for k in range(je):
            ua, ub = k / je, (k + 1) / je
            for i in range(n):
                i2 = (i + 1) % n
                va, vb = v_von(i, i), v_von(i, i2)
                uvs = [_in_bereich((ua, va), BEREICH_SCHEIBE), _in_bereich((ua, vb), BEREICH_SCHEIBE),
                       _in_bereich((ub, vb), BEREICH_SCHEIBE), _in_bereich((ub, va), BEREICH_SCHEIBE)]
                netz.f((ringe[k][i], ringe[k][i2], ringe[k + 1][i2], ringe[k + 1][i]), uvs, umriss[i][1])
    fl = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pkt, pkt[1:] + pkt[:1]))
    if fl < 0:
        netz.umdrehen(0)
    return netz


def sattel_netz(rr: float, form: Speichenform, tb: dict, ts: dict, lod: int = 0):
    """Bremssattel als gerundeter Bogen um den Scheibenrand, UV in Bereich C,
    dazu Staubschutzblech und Entlüfter (einfarbige Felder). Lenkt mit, dreht
    nicht. Liefert (Netz, Lageangaben für die Textur)."""
    r_o, r_i, y0, y1, _ = _bremslage(form, rr, tb)
    r_in = r_o - 0.05
    r_aus = r_o + 0.016
    y_i = y0 - 0.024
    frei = min(form.hinten(r_in + (r_aus - r_in) * k / 8) for k in range(9)) - 0.007
    y_a = max(min(y1 + 0.036, frei), y1 + 0.006)
    mitte = math.radians(ts.get("winkel_grad", 140))
    spanne = math.radians(ts.get("spanne_grad", 56))
    rm, ym = (r_in + r_aus) / 2, (y_i + y_a) / 2
    hr, hy = (r_aus - r_in) / 2, (y_a - y_i) / 2
    # Querschnitt: abgerundetes Rechteck (Superellipse), außen etwas voller
    nq = 16 if not lod else 8
    quer = []
    for j in range(nq):
        a = 2 * math.pi * j / nq + math.pi / nq
        c, s = math.cos(a), math.sin(a)
        e = 0.28
        quer.append((rm + hr * math.copysign(abs(c) ** e, c), ym + hy * math.copysign(abs(s) ** e, s)))
    stn = [-0.5 - 0.05, -0.5 - 0.02, -0.5] + [-0.5 + k / 10 for k in range(1, 10)] + [0.5, 0.5 + 0.02, 0.5 + 0.05]
    if lod:
        stn = [-0.55, -0.5, -0.25, 0.0, 0.25, 0.5, 0.55]
    fak = {-0.55: 0.72, -0.52: 0.9, 0.52: 0.9, 0.55: 0.72}
    # Abwicklung: u entlang des Bogens (Mitte des Bereichs = Sattelmitte),
    # v entlang des Querschnitts; quadratische Texel bei einem Atlas 2:1.
    s_q = [0.0]
    for a, b_ in zip(quer, quer[1:] + quer[:1]):
        s_q.append(s_q[-1] + math.hypot(b_[0] - a[0], b_[1] - a[1]))
    laenge = spanne * 1.12 * rm
    v_pro_m = min(0.72 / s_q[-1], 0.48 / laenge)
    u_pro_m = v_pro_m / 2
    ringe = []
    tts = []
    for tt in stn:
        f = fak.get(round(tt, 2), 1.0)
        w = mitte + spanne * tt
        c, s = math.cos(w), math.sin(w)
        ringe.append([((rm + (r - rm) * f) * c, ym + (y - ym) * f, (rm + (r - rm) * f) * s) for r, y in quer])
        tts.append(tt)
    u_c = (BEREICH_SATTEL[0] + BEREICH_SATTEL[2]) / 2

    def uv(k, j):
        return (u_c + tts[k] * spanne * rm * u_pro_m, BEREICH_SATTEL[1] + 0.015 + s_q[j] * v_pro_m)

    netz = Netz()
    netz.loft(ringe, T_SATTEL, uv=uv, deckel=True, deckel_uv=feld_uv("sattellack"), achse=2 * u_c)
    # Staubschutzblech hinter der Scheibe, mit Aussparung für den Sattel
    if not lod:
        y_s = y0 - 0.012
        blech = [(r_o + 0.006, y_s + 0.008), (r_o + 0.004, y_s), (0.085, y_s)]
        start = len(netz.flaechen)
        luecke = spanne * 0.62
        netz.drehband(blech, mitte + luecke, mitte - luecke + 2 * math.pi, 30, 0)
        for k in range(start, len(netz.flaechen)):
            idx, _uv, *rest = netz.flaechen[k]
            netz.flaechen[k] = (idx, [feld_uv("schild")] * len(idx), *rest)
        # Entlüfterschraube oben auf dem Sattel
        schr = Netz()
        schr.drehband([(0.004, 0.0), (0.004, 0.008), (0.0025, 0.012), (0.0, 0.012)], 0.0,
                      2 * math.pi, 6, 0)
        for k in range(len(schr.flaechen)):
            idx, _uv, *rest = schr.flaechen[k]
            schr.flaechen[k] = (idx, [feld_uv("chrom")] * len(idx), *rest)
        w = mitte + spanne * 0.36
        m = (Matrix.Rotation(-w, 4, "Y") @ Matrix.Translation((r_aus - 0.004, ym + hy * 0.4, 0))
             @ Matrix.Rotation(-math.pi / 2, 4, "Z"))
        netz.anhaengen(schr, m)
    lage = {"mitte": mitte, "spanne": spanne, "rm": rm, "r_in": r_in, "r_aus": r_aus,
            "y_a": y_a, "y_i": y_i}
    return netz, lage


def sattel_y_frei(form: Speichenform, r_a: float, r_b: float) -> float:
    """Wie weit ein Sattel zwischen den Radien r_a und r_b nach außen reichen
    darf, ohne in die Speichen zu ragen."""
    return min(form.hinten(r_a + (r_b - r_a) * k / 8) for k in range(9)) - 0.007


# ---------------------------------------------------------------------------
# Texturen: Reifen
# ---------------------------------------------------------------------------

#: Texturgrößen (Breite, Höhe) je Stufe. Normalen und Farbe in voller,
#: ORM (Verdeckung, Rauheit, Metallic) in halber Auflösung.
AUFLOESUNG = {
    0: {"reifen": (2048, 1024), "reifen_orm": (1024, 512),
        "metall": (2048, 1024), "metall_orm": (1024, 512), "schrift_px": 4200},
    1: {"reifen": (512, 256), "reifen_orm": (256, 128),
        "metall": (512, 256), "metall_orm": (256, 128), "schrift_px": 1200},
}


def _lin(rgb255):
    return bk.srgb_nach_lin(np.asarray(rgb255[:3], np.float32) / 255.0)


def _wickeln(w):
    return (w + math.pi) % (2 * math.pi) - math.pi


def _hoch(a: np.ndarray, faktor: int) -> np.ndarray:
    """Ein Bild ganzzahlig vergrößern (für AO in halber Auflösung)."""
    if faktor <= 1:
        return a
    return np.repeat(np.repeat(a, faktor, axis=0), faktor, axis=1)


def _reifenschrift(info: dict, tp: dict, reifen_b: float):
    """Flankenschrift: (Text, Winkel °, Radius, Höhe, fett, kursiv, sperren)."""
    R, rr = info["R"], info["rr"]
    hs = R - rr
    z0, z1 = info["schrift_zone"]
    zh = z1 - z0
    mitte = (z0 + z1) / 2
    art = info["art"]
    modell = tp.get("modell") or {"sport": "APEX R2", "strasse": "CITY TOUR 4",
                                  "slick": "SLICK"}.get(art, "APEX R2")
    b_mm = int(round(reifen_b * 1000 / 5) * 5)
    quer = int(round(hs / reifen_b * 100 / 5) * 5)
    zoll = int(round(rr * 2 / 0.0254))
    groesse = f"{b_mm}/{quer} ZR{zoll} {88 + zoll // 2}Y"
    h_marke = min(0.026, 0.6 * zh)
    h_modell = min(0.015, 0.38 * zh)
    h_klein = min(0.0095, 0.26 * zh)
    texte = [
        (REIFENMARKE, 90.0, mitte, h_marke, 0.13, 0.2, 1.06),
        (modell, 146.0, mitte, h_modell, 0.09, 0.14, 1.03),
        (groesse, 36.0, mitte, h_klein, 0.05, 0.0, 1.0),
        ("TUBELESS  RADIAL", 4.0, mitte, min(0.006, 0.18 * zh), 0.04, 0.0, 1.1),
    ]
    if art == "sport":
        # Laufrichtung: das Rad dreht vorwärts mit fallendem Winkel
        texte.append(("ROTATION ←", 176.0, mitte, min(0.006, 0.18 * zh), 0.05, 0.0, 1.08))
    return texte, (z0, z1)


def reifen_textur(k: bk.Karten, ao: np.ndarray, info: dict, tp: dict, reifen_b: float, lod: int):
    """Farbe, ORM und Normalen des Reifens aus den Karten."""
    gr = AUFLOESUNG[lod]
    P = k.pos
    y = P[..., 1]
    r, w = k.zylinder()
    teil = k.teil
    flanke = (teil == T_FLANKE_AUSSEN) | (teil == T_FLANKE_INNEN)
    lauf = teil == T_LAUF
    R, halb = info["R"], info["halb"]
    h = np.zeros(r.shape, np.float32)
    basis = np.full(r.shape, 0.030, np.float32)
    rau = np.full(r.shape, 0.84, np.float32)

    # Gummikorn und leichte Fleckigkeit überall
    korn = bk.fbm(P, 0.0022, 2, keim=3) - 0.5
    h += 0.00003 * korn
    fleck = bk.fbm(P, 0.05, 2, keim=11)
    basis *= 0.9 + 0.2 * fleck

    # Flanke: Zierringe, Samtband, Schrift
    texte, (z0, z1) = _reifenschrift(info, tp, reifen_b)
    for rc in (z0 - 0.005, z1 + 0.005):
        ring = np.clip(1 - np.abs(r - rc) / 0.001, 0, 1)
        h += 0.00045 * ring * flanke
    band = flanke & (r > z1 + 0.008) & (r < min(z1 + 0.02, R - 0.02))
    riefen = 0.5 + 0.5 * np.sin(w * r / 0.0018 * 2 * math.pi)
    h += 0.00012 * riefen * band
    basis = np.where(band, basis * 0.7, basis)
    rau = np.where(band, 0.95, rau)
    maske = np.zeros(r.shape, np.float32)
    aussen = y > 0
    kandidat = flanke & (r > z0 - 0.02) & (r < z1 + 0.02)
    ks = np.nonzero(kandidat)
    rk, wk, ak = r[ks], w[ks], aussen[ks]
    mk = np.zeros(rk.shape, np.float32)
    for text, winkel, rc, hoehe, fett, kursiv, sperren in texte:
        sb = bk.Schriftbild(text, hoehe, gr["schrift_px"], fett, kursiv, sperren)
        for wc in (math.radians(winkel), math.radians(winkel) + math.pi):
            dw = _wickeln(wk - wc)
            nah = np.abs(dw) * rk < (sb.x1 - sb.x0)
            if not np.any(nah):
                continue
            xt = np.where(ak[nah], dw[nah], -dw[nah]) * rk[nah]
            yt = rk[nah] - rc
            mk[nah] = np.maximum(mk[nah], sb.abtasten(xt, yt))
    maske[ks] = mk
    erhaben = np.clip(bk.glaetten(maske, 1) * 1.3 - 0.15, 0, 1)
    h += 0.0007 * erhaben
    if tp.get("schrift", "schwarz") == "weiss":
        # Weiße Reifenschrift: leicht vergilbt und abgerieben
        abrieb = 0.85 + 0.15 * bk.fbm(P, 0.004, 2, keim=17)
        basis = basis + (0.5 * abrieb - basis) * maske
        rau = rau + (0.62 - rau) * maske
    else:
        basis = basis + (0.022 - basis) * maske
        rau = rau + (0.5 - rau) * maske

    # Lauffläche: abgefahren, Laufspuren längs, Lamellen
    streifen = bk.rauschen(np.stack([y * 1.0, w * R * 0.04, np.zeros_like(y)], axis=-1), 0.0012, keim=5)
    basis = np.where(lauf, 0.046 * (0.85 + 0.3 * streifen) * (0.9 + 0.2 * fleck), basis)
    rau = np.where(lauf, 0.8 + 0.1 * streifen, rau)
    h += np.where(lauf, 0.00002 * (streifen - 0.5), 0.0)
    schulter = lauf & (np.abs(y) > halb - 0.012)
    basis = np.where(schulter, basis * 1.12, basis)
    if info["art"] != "slick":
        t = info["teilung"]
        ay = np.abs(y)
        f = ((w - info["pfeil"] * t * ay / halb) / t) % 1.0
        rb = info["rille_m"]
        grenze = info["grenze"]
        lamellen = [0.42] if info["art"] == "sport" else [0.3, 0.6]
        sch = lauf & (ay > grenze + rb / 2 + 0.004) & (ay < halb - 0.003)
        for fs in lamellen:
            d = np.abs(((f - fs + 0.5) % 1.0) - 0.5) * t * R
            h -= 0.0025 * sch * np.clip(1 - d / 0.00065, 0, 1)
        for yg in info["rillen"]:
            for seite in (-1, 1):
                kante = yg + seite * rb / 2
                tt = (y - kante) * seite
                kerbe = lauf & (tt > 0) & (tt < 0.009)
                for fs in (0.18, 0.68):
                    d = np.abs(((f - fs - 0.6 * tt / (t * R) + 0.5) % 1.0) - 0.5) * t * R
                    h -= 0.002 * kerbe * np.clip(1 - d / 0.0006, 0, 1) * np.clip((0.009 - tt) / 0.003, 0, 1)

    faktor = max(1, k.breite // ao.shape[1])
    ao_v = np.where(ao[..., 3] > 0.5, ao[..., 0], 1.0)
    ao_voll = _hoch(ao_v, faktor)[:k.hoehe, :k.breite]
    kav = np.clip(1 + h * 180, 0.55, 1.0)            # Vertiefungen dunkler
    basis = basis * (0.55 + 0.45 * ao_voll) * kav
    n = bk.normale_aus_hoehe(h, k)
    deck = k.gedeckt
    n = bk.ausdehnen(n, deck)
    basis = bk.ausdehnen(basis, deck)
    rau = bk.ausdehnen(rau, deck)
    ao_k = bk.ausdehnen(ao_voll * kav, deck)
    orm = np.stack([bk.verkleinern(ao_k, faktor), bk.verkleinern(rau, faktor),
                    np.zeros((k.hoehe // faktor, k.breite // faktor), np.float32)], axis=2)
    basis_b = bk.verkleinern(basis, faktor)
    return np.repeat(basis_b[..., None], 3, axis=2), orm, n


# ---------------------------------------------------------------------------
# Texturen: Felge, Scheibe, Sattel
# ---------------------------------------------------------------------------

def felgen_finish(p: dict, tf: dict):
    """(Farbe linear, Metallic, Rauheit) des Felgenlacks."""
    fl = np.asarray(p.get("felgenfarbe", [200, 202, 205]), np.float32)
    lum, sat = fl.mean() / 255, (fl.max() - fl.min()) / 255
    finish = tf.get("finish") or ("lack" if sat > 0.25 else ("satin" if lum < 0.3 else "metall"))
    met, rau = {"lack": (0.3, 0.26), "satin": (0.55, 0.4), "metall": (0.9, 0.3)}[finish]
    rau = p.get("felgenrauheit", rau)
    return _lin(fl), met, rau


def metall_textur(k: bk.Karten, ao: np.ndarray, fase: np.ndarray, p: dict, tf: dict, tb: dict,
                  ts: dict, lage: dict, bremse: tuple, lod: int):
    """Farbe, ORM und Normalen des Metall-Atlas (Felge, Scheibe, Sattel)."""
    gr = AUFLOESUNG[lod]
    P, N, teil = k.pos, k.nor, k.teil
    y = P[..., 1]
    r, w = k.zylinder()
    form_h = r.shape
    basis = np.zeros(form_h + (3,), np.float32)
    rau = np.full(form_h, 0.5, np.float32)
    met = np.zeros(form_h, np.float32)
    h = np.zeros(form_h, np.float32)

    def ist(*ts_):
        return np.isin(teil, ts_)

    def setzen(maske, farbe, m, rh):
        basis[maske] = farbe
        met[maske] = m
        rau[maske] = rh

    # --- Felge ---------------------------------------------------------------
    F, fm, fr = felgen_finish(p, tf)
    felge = ist(T_BETT, T_HORN, T_LIPPE, T_SITZ, T_SPEICHE, T_SCHAUFEL, T_RING, T_NABE)
    setzen(felge, F, fm, fr)
    lackkorn = bk.fbm(P, 0.003, 2, keim=21) - 0.5
    h += np.where(felge, 0.000006 * lackkorn, 0.0)
    rau = np.where(felge, rau + 0.04 * lackkorn, rau)
    # Innenbett: roh gegossen bei hellen Felgen, sonst dunkler Lack; Bremsstaub
    bett = ist(T_BETT, T_SITZ)
    staub = bk.fbm(P, 0.025, 3, keim=7)
    if float(np.mean(F)) > 0.2:
        innen_farbe = np.array([0.36, 0.36, 0.37], np.float32)
    else:
        innen_farbe = F * 0.7
    staubfarbe = np.array([0.075, 0.062, 0.05], np.float32)
    anteil = np.clip(0.2 + 0.35 * staub, 0, 1)[..., None]
    basis = np.where(bett[..., None], innen_farbe * (1 - anteil) + staubfarbe * anteil, basis)
    rau = np.where(bett, np.clip(fr + 0.25, 0, 0.8), rau)
    # Glanzgedreht (Diamant) bzw. polierte Lippe
    drehriefen = 0.5 + 0.5 * np.sin(r / 0.0011 * 2 * math.pi)
    front = N[..., 1] > 0.72
    if tf.get("diamant"):
        dia = ist(T_SPEICHE, T_HORN, T_RING) & front
        setzen(dia, np.array([0.72, 0.72, 0.74], np.float32), 1.0, 0.0)
        rau = np.where(dia, 0.1 + 0.08 * drehriefen, rau)
        h += np.where(dia, 0.000004 * drehriefen, 0.0)
    if tf.get("lippe") == "poliert" or _schuessel(p, tf) > 0:
        pol = ist(T_HORN, T_LIPPE) & (N[..., 1] > 0.2)
        setzen(pol, np.array([0.72, 0.72, 0.73], np.float32), 1.0, 0.0)
        rau = np.where(pol, 0.14 + 0.08 * drehriefen, rau)
        h += np.where(pol, 0.000004 * drehriefen, 0.0)
    setzen(ist(T_NIETE), np.array([0.6, 0.58, 0.55], np.float32), 1.0, 0.22)
    anzahl = 0 if p.get("felge") == "zentral" else tf.get("radmuttern", 5)
    if anzahl:
        nabe = ist(T_NABE) & (N[..., 1] > 0.5)
        tasche = np.zeros(form_h, np.float32)
        for i in range(anzahl):
            wm = 2 * math.pi * i / anzahl + math.pi / anzahl
            d = np.hypot(P[..., 0] - 0.058 * math.cos(wm), P[..., 2] - 0.058 * math.sin(wm))
            tasche = np.maximum(tasche, np.clip((0.0155 - d) / 0.0025, 0, 1))
        tasche *= nabe
        h -= 0.004 * tasche
        basis = basis * (1 - 0.75 * tasche)[..., None]
    setzen(ist(T_AEROGRUND), np.array([0.02, 0.02, 0.022], np.float32), 0.0, 0.42)

    # --- Scheibe -------------------------------------------------------------
    r_o, r_i, y0, y1, _yt = bremse
    reib, rand, topf = ist(T_REIBRING), ist(T_RAND), ist(T_TOPF)
    art = tb.get("art", "gelocht")
    keramik = tb.get("scheibe", "stahl") == "keramik"
    null = np.zeros_like(r)
    riefen = bk.rauschen(np.stack([r, w * 0.004, null], axis=-1), 0.00045, keim=9)
    riefen2 = bk.rauschen(np.stack([r, w * 0.01, null], axis=-1), 0.002, keim=13)
    if keramik:
        flecken = bk.fbm(P, 0.006, 3, keim=31)
        g_ = 0.05 * (0.65 + 0.8 * flecken) * (0.9 + 0.2 * riefen)
        setzen(reib, np.stack([g_, g_, g_ * 1.04], axis=-1)[reib], 0.0, 0.5)
        rau = np.where(reib, 0.46 + 0.14 * riefen2, rau)
    else:
        g_ = 0.3 + 0.1 * riefen + 0.05 * riefen2
        setzen(reib, np.stack([g_, g_ * 0.995, g_ * 1.01], axis=-1)[reib], 1.0, 0.3)
        rau = np.where(reib, 0.24 + 0.16 * riefen2 + 0.08 * riefen, rau)
    h += np.where(reib, 0.000012 * (riefen - 0.5), 0.0)
    # Unverschlissene Ränder: angerostet (Stahl) bzw. dunkler (Keramik)
    rost = reib & ((r > r_o - 0.0035) | (r < r_i + 0.003))
    if keramik:
        basis = np.where(rost[..., None], basis * 0.75, basis)
    else:
        rostfarbe = (np.array([0.13, 0.075, 0.045], np.float32)
                     * (0.8 + 0.4 * bk.fbm(P, 0.004, 2, keim=4))[..., None])
        basis = np.where(rost[..., None], rostfarbe, basis)
        met = np.where(rost, 0.2, met)
    rau = np.where(rost, 0.8, rau)
    # Bohrungen / Schlitze
    loecher = np.zeros(form_h, np.float32)
    tief = 0.0
    if art == "gelocht":
        for reihe, anteil in enumerate((0.3, 0.52, 0.74)):
            rc = r_i + (r_o - r_i) * anteil
            kk = np.round(w / (2 * math.pi) * 18 - reihe / 3)
            wc = 2 * math.pi * (kk + reihe / 3) / 18
            d = np.hypot(r - rc, r * _wickeln(w - wc))
            loecher = np.maximum(loecher, np.clip((0.0053 - d) / 0.0012, 0, 1))
        tief = 0.003
    elif art == "geschlitzt":
        ra, rb_ = r_i + 0.012, r_o - 0.012
        tt = (r - ra) / (rb_ - ra)
        tk = np.clip(tt, 0, 1)
        kk = np.round((w - 0.28 * tk) / (2 * math.pi / 12))
        d = np.abs(_wickeln(w - 0.28 * tk - 2 * math.pi * kk / 12)) * r
        ende = np.maximum(np.maximum(-tt, tt - 1), 0) * (rb_ - ra)
        d = np.hypot(d, ende)
        loecher = np.clip((0.0019 - d) / 0.0007, 0, 1)
        tief = 0.0015
    loecher *= reib
    h -= tief * loecher
    loch = loecher > 0.99
    basis = np.where(loch[..., None], np.array([0.012, 0.012, 0.013], np.float32), basis)
    rau = np.where(loch, 0.9, rau)
    met = np.where(loch, 0.0, met)
    # Außenrand: Kühlkanäle zwischen den Reibringen
    setzen(rand, np.array([0.2, 0.19, 0.185], np.float32), 0.6, 0.6)
    kanal = rand & (y > y0 + 0.0075) & (y < y1 - 0.0075)
    luecke = kanal & (((w / (2 * math.pi) * 36) % 1.0) < 0.5)
    basis = np.where(luecke[..., None], np.array([0.008, 0.008, 0.008], np.float32), basis)
    h -= 0.003 * luecke
    # Topf
    topf_art = tb.get("topf", "alu" if keramik else "schwarz")
    if topf_art == "alu":
        setzen(topf, np.array([0.55, 0.55, 0.57], np.float32), 1.0, 0.32)
    elif topf_art == "lack":
        setzen(topf, _lin(p.get("sattelfarbe", [60, 60, 64])), 0.0, 0.3)
    else:
        setzen(topf, np.array([0.03, 0.03, 0.032], np.float32), 0.45, 0.35)

    # --- Sattel --------------------------------------------------------------
    sat = ist(T_SATTEL)
    S = _lin(p.get("sattelfarbe", [60, 60, 64]))
    setzen(sat, S, 0.0, 0.2)
    h += np.where(sat, 0.000005 * (bk.fbm(P, 0.002, 2, keim=41) - 0.5), 0.0)
    if lage is not None and np.any(sat):
        schrift = ts.get("schrift", SATTELMARKE)
        hoehe = 0.2 * (lage["r_aus"] - lage["r_in"])
        sb = bk.Schriftbild(schrift, hoehe, gr["schrift_px"], 0.14, 0.18, 1.04)
        aussen = sat & (N[..., 1] > 0.55)
        ks = np.nonzero(aussen)
        dw = _wickeln(w[ks] - lage["mitte"])
        logo = np.zeros(form_h, np.float32)
        logo[ks] = sb.abtasten(dw * r[ks], r[ks] - (lage["r_in"] + lage["r_aus"]) / 2)
        hell = float(np.mean(S)) > 0.45
        schriftfarbe = np.array([0.02, 0.02, 0.022] if hell else [0.8, 0.8, 0.8], np.float32)
        basis = basis + (schriftfarbe - basis) * logo[..., None]
        rau = rau + (0.3 - rau) * logo
        h += 0.00003 * logo

    # --- Verdeckung, Normalen, Felder ------------------------------------------
    faktor = max(1, k.breite // ao.shape[1])
    ao_v = np.where(ao[..., 3] > 0.5, ao[..., 0], 1.0)
    ao_voll = _hoch(ao_v, faktor)[:k.hoehe, :k.breite]
    kav = np.clip(1 + h * 150, 0.4, 1.0)
    basis = basis * (0.6 + 0.4 * ao_voll)[..., None] * kav[..., None]
    n = bk.normalen_mischen(fase, bk.normale_aus_hoehe(h, k))
    deck = k.gedeckt
    n = bk.ausdehnen(n, deck)
    basis = bk.ausdehnen(basis, deck)
    rau = bk.ausdehnen(rau, deck)
    met = bk.ausdehnen(met, deck)
    ao_k = bk.ausdehnen(ao_voll * kav, deck)
    H, W = k.hoehe, k.breite
    hw, hh = max(1, W // 64), max(1, H // 32)
    for name, (farbe, m_, r_) in _felderwerte(F, fm, fr, S).items():
        u, v = feld_uv(name)
        ci, cj = int(u * W), int(v * H)
        sl = (slice(cj - hh, cj + hh), slice(ci - hw, ci + hw))
        basis[sl] = farbe
        n[sl] = (0.0, 0.0, 1.0)
        rau[sl] = r_
        met[sl] = m_
        ao_k[sl] = 1.0
    orm = np.stack([bk.verkleinern(ao_k, faktor), bk.verkleinern(rau, faktor),
                    bk.verkleinern(met, faktor)], axis=2)
    return basis, orm, n


def _felderwerte(F, fm, fr, S):
    return {
        "chrom": (np.array([0.8, 0.8, 0.81], np.float32), 1.0, 0.16),
        "gummi": (np.array([0.028, 0.028, 0.03], np.float32), 0.0, 0.7),
        "kunststoff": (np.array([0.03, 0.03, 0.033], np.float32), 0.0, 0.38),
        "schild": (np.array([0.035, 0.035, 0.036], np.float32), 0.2, 0.75),
        "sattellack": (S, 0.0, 0.2),
        "felgenlack": (F, fm, fr),
        "mutter": (S, 0.3, 0.3),
        "titan": (np.array([0.55, 0.53, 0.5], np.float32), 1.0, 0.25),
        "belag": (np.array([0.04, 0.038, 0.036], np.float32), 0.0, 0.8),
        "schwarz": (np.array([0.02, 0.02, 0.022], np.float32), 0.5, 0.3),
        "alu": (np.array([0.6, 0.6, 0.62], np.float32), 1.0, 0.35),
    }


# ---------------------------------------------------------------------------
# Zusammenbau: ein Rad je Auto bauen und backen, viermal verwenden
# ---------------------------------------------------------------------------

_VORRAT: dict = {}


def _lebt(*obs) -> bool:
    try:
        return all(o is not None and o.name for o in obs)
    except ReferenceError:
        return False


def _platzhalter(name: str):
    alt = bpy.data.materials.get(name)
    if alt is not None:
        return alt
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    return m


def _uv_projizieren(ob, bereich) -> None:
    """Smart-UV-Projektion über alle Flächen, dann in den Atlasbereich."""
    g.aktiv(ob)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(52), island_margin=0.004,
                             area_weight=0.0, correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(rotate=True, margin=0.004)
    bpy.ops.object.mode_set(mode="OBJECT")
    lay = ob.data.uv_layers.active
    uv = np.zeros(len(lay.data) * 2, np.float32)
    lay.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    u0, v0, u1, v1 = bereich
    uv[:, 0] = u0 + uv[:, 0] * (u1 - u0)
    uv[:, 1] = v0 + uv[:, 1] * (v1 - v0)
    lay.data.foreach_set("uv", uv.ravel())


def _sektoren_vervielfachen(ob, n: int) -> None:
    """Flächen mit ``sektor = 1`` n-mal um Y verteilen (UV bleibt gleich)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    sk = bm.faces.layers.int.get("sektor")
    faces = [f for f in bm.faces if f[sk] == 1]
    for k in range(1, n):
        erg = bmesh.ops.duplicate(bm, geom=faces)
        verts = [e for e in erg["geom"] if isinstance(e, bmesh.types.BMVert)]
        bmesh.ops.rotate(bm, verts=verts, cent=(0, 0, 0),
                         matrix=Matrix.Rotation(-2 * math.pi * k / n, 3, "Y"))
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5)
    bm.to_mesh(ob.data)
    bm.free()


def _feld_setzen(ob, name: str, mat_index: int = 0) -> None:
    """Alle Flächen eines Objekts auf ein einfarbiges Feld legen."""
    lay = bk.uv_ebene(ob)
    u, v = feld_uv(name)
    lay.data.foreach_set("uv", [u, v] * len(lay.data))
    ob.data.polygons.foreach_set("material_index", [mat_index] * len(ob.data.polygons))


def _bauen(ms, p: dict, mats, emblem_bauen, lod: int) -> dict:
    tp = p.get("teile") or {}
    tr_ = tp.get("reifen") or {}
    tf = tp.get("felge") or {}
    tb = tp.get("bremse") or {}
    ts = tp.get("sattel") or {}
    rr = p.get("zoll", 17) * 0.0254 / 2
    R, b = ms.rad_r, ms.reifen_b
    m_reifen = _platzhalter("rad_reifen")
    m_metall = _platzhalter("rad_metall")

    rn, rinfo = reifen_netz(R, b, rr, tr_, lod)
    reifen = rn.objekt("reifen", [m_reifen])
    g.glatt(reifen, 48)

    sektor, n, nabe, form = felge_netz(p, tf, rr, b, lod)
    felge = g.verbinden([sektor.objekt("felge", [m_metall]), nabe.objekt("nabe", [m_metall])], "felge")
    _uv_projizieren(felge, BEREICH_FELGE)
    _sektoren_vervielfachen(felge, n)
    g.glatt(felge, 32)

    klein = muttern_netz(p, tf, form, lod)
    if not lod:
        design = p.get("felge", "fuenf")
        w_v = math.pi / n + (math.radians(p.get("felgen_bogen_grad", 28)) / 2
                             if design in ("turbine", "aero") else 0.0)
        klein.anhaengen(ventil_netz(rr, b / 2, form, w_v))
    teile_m = [felge]
    if klein.flaechen:
        k_ob = klein.objekt("klein", [m_metall])
        g.glatt(k_ob, 40)
        teile_m.append(k_ob)
    scheibe = scheibe_netz(rr, form, tb, lod).objekt("scheibe", [m_metall])
    g.glatt(scheibe, 40)
    teile_m.append(scheibe)
    if tf.get("nabenkappe", "emblem") == "emblem" and emblem_bauen is not None and \
            p.get("felge") != "zentral" and not lod:
        em = emblem_bauen(0.042)
        if em is not None:
            em.data.transform(Matrix.Rotation(math.radians(90), 4, "Z"))
            em.data.transform(Matrix.Translation((0, form.y_nabe + 0.038, 0)))
            em.data.materials.clear()
            em.data.materials.append(m_metall)
            _feld_setzen(em, "chrom")
            teile_m.append(em)
    metall = g.verbinden(teile_m, "metall")

    sn, lage = sattel_netz(rr, form, tb, ts, lod)
    sattel = sn.objekt("sattel", [m_metall])
    g.glatt(sattel, 40)

    texturen_backen(reifen, metall, sattel, p, tp, rinfo, lage, form, rr, b, lod, m_reifen, m_metall)

    rad_ob = g.verbinden([reifen, metall], "rad")
    for o in (rad_ob, sattel):
        bpy.context.scene.collection.objects.unlink(o)
        o.use_fake_user = True
    return {"rad": rad_ob, "sattel": sattel, "form": form}


def texturen_backen(reifen, metall, sattel, p, tp, rinfo, lage, form, rr, b, lod, m_reifen, m_metall):
    """Beide Texturgruppen backen und in die Materialien legen."""
    gr = AUFLOESUNG[lod]
    samples = 48 if not lod else 16
    key = p.get("_key", "rad") + ("_lod1" if lod else "")
    tf = tp.get("felge") or {}
    tb = tp.get("bremse") or {}
    ts = tp.get("sattel") or {}
    with bk.Backszene([reifen, metall, sattel]):
        kr = bk.Karten([reifen], *gr["reifen"])
        bk.ao_distanz(0.035)
        ao_r = bk.ao([reifen], *gr["reifen_orm"], samples=samples)
        km = bk.Karten([metall, sattel], *gr["metall"])
        bk.ao_distanz(0.09)
        ao_bild = bk.bild_fliess("_ao_metall", *gr["metall_orm"])
        sattel.hide_render = True
        bk.ao([metall], 0, 0, samples=samples, bild=ao_bild)
        sattel.hide_render = False
        ao_m = bk.ao([sattel], 0, 0, samples=samples, bild=ao_bild, loeschen=False)
        fase = bk.fase([metall, sattel], *gr["metall"], 0.0022 if not lod else 0.004)
    basis, orm, n = reifen_textur(kr, ao_r, rinfo, tp.get("reifen") or {}, b, lod)
    bk.material(m_reifen, bk.bild_schreiben(f"{key}_reifen_farbe", basis, srgb=True),
                bk.bild_schreiben(f"{key}_reifen_orm", orm),
                bk.normalbild(f"{key}_reifen_normal", n))
    bremse = _bremslage(form, rr, tb)
    basis, orm, n = metall_textur(km, ao_m, fase, p, tf, tb, ts, lage, bremse, lod)
    bk.material(m_metall, bk.bild_schreiben(f"{key}_metall_farbe", basis, srgb=True),
                bk.bild_schreiben(f"{key}_metall_orm", orm),
                bk.normalbild(f"{key}_metall_normal", n))


def _kopie(ob, name: str):
    neu = ob.copy()
    neu.data = ob.data.copy()
    neu.name = name
    neu.data.name = name
    neu.use_fake_user = False
    bpy.context.scene.collection.objects.link(neu)
    return neu


def _vorrat(ms, p, mats, emblem_bauen=None) -> dict:
    lod = int(p.get("_lod", 0))
    schluessel = (p.get("_key", ""), lod)
    v = _VORRAT.get(schluessel)
    if v is None or not _lebt(v["rad"], v["sattel"]):
        v = _bauen(ms, p, mats, emblem_bauen, lod)
        _VORRAT[schluessel] = v
    return v


def rad(ms, p: dict, mats, emblem_bauen=None):
    """Ein fertiges Rad (Reifen, Felge, Scheibe) in Radkoordinaten.

    Gebaut und gebacken wird einmal je Auto und Stufe; jeder weitere Aufruf
    liefert eine Kopie mit denselben Materialien. Liefert ([Objekt], Speichenform).
    """
    v = _vorrat(ms, p, mats, emblem_bauen)
    return [_kopie(v["rad"], "rad")], v["form"]


def sattel(name: str, ms, p: dict, mats):
    """Bremssattel samt Staubschutzblech in Radkoordinaten (Kopie)."""
    v = _vorrat(ms, p, mats)
    return _kopie(v["sattel"], name)


def spiegeln(ob) -> None:
    """Ein Rad oder einen Sattel an XZ spiegeln (rechte Seite).

    Flächen mit ``uv_spiegeln`` bekommen ``u = uv_achse − u`` — so bleibt
    die Schrift auf Flanke und Sattel lesbar."""
    me = ob.data
    me.transform(Matrix.Diagonal((1, -1, 1, 1)))
    me.flip_normals()
    sp = me.attributes.get("uv_spiegeln")
    ax = me.attributes.get("uv_achse")
    if sp is None or ax is None or not me.uv_layers:
        return
    np_ = len(me.polygons)
    flags = np.zeros(np_, bool)
    sp.data.foreach_get("value", flags)
    achsen = np.zeros(np_, np.float32)
    ax.data.foreach_get("value", achsen)
    anzahl = np.zeros(np_, np.int64)
    me.polygons.foreach_get("loop_total", anzahl)
    je_ecke = np.repeat(np.arange(np_), anzahl)
    lay = me.uv_layers.active
    uv = np.zeros(len(lay.data) * 2, np.float32)
    lay.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    wahl = flags[je_ecke]
    uv[wahl, 0] = achsen[je_ecke][wahl] - uv[wahl, 0]
    lay.data.foreach_set("uv", uv.ravel())


# ---------------------------------------------------------------------------
# Radhaus: Rippen in der Schale, Federbein, Querlenker, Antriebswelle
# ---------------------------------------------------------------------------

def radhaus_teile(schale, achse_x: float, seite: int, rad_r: float, r: float, innen: float,
                  mats, lod: int = 0) -> list:
    """Was man im Radhaus sieht, damit es nicht leer wirkt.

    ``schale``: die fertige (an die Karosserie geklemmte) Radhausschale, aus
    ihr kommt die Außenkante je Winkel. Die Rippen liegen quer in der Schale,
    Federbein und Querlenker vor der Innenwand, im Spalt zum Reifen (5 cm),
    und nur so dick, dass auch das gelenkte Vorderrad sie nicht schneidet.
    Alles in Fahrzeugkoordinaten, Materialien der Karosserie."""
    if lod:
        return []
    ko = [schale.matrix_world @ v.co for v in schale.data.vertices]
    netz = Netz()
    # Rippen: alle 9° über dem Rad, 1 cm breit, 6 mm hoch
    for grad in range(-6, 190, 9):
        w = math.radians(grad)
        kante = [abs(c.y) for c in ko
                 if abs(math.atan2(c.z - rad_r, c.x - achse_x) - w) < math.radians(6)
                 and abs(c.y) > innen + 0.015]
        if not kante:
            continue
        y1 = min(kante) - 0.025
        if y1 < innen + 0.04:
            continue
        ringe = []
        for yy in (innen + 0.004, y1):
            ring = []
            for dq, dr in ((-0.005, 0.0), (0.005, 0.0), (0.004, 0.006), (-0.004, 0.006)):
                rr_ = r - 0.004 - dr
                ww = w + dq / rr_
                ring.append((achse_x + rr_ * math.cos(ww), seite * yy, rad_r + rr_ * math.sin(ww)))
            ringe.append(ring)
        netz.loft(ringe, 0)
    teile = []
    if netz.flaechen:
        ob = netz.objekt("radhaus_rippen", [mats["kunststoff"]])
        teile.append(ob)
    # Federbein (Gewindefahrwerk): Dämpfer, Feder, Teller
    y_f = seite * (innen + 0.014)
    x_f = achse_x - 0.03
    z0, z1 = rad_r + 0.1, rad_r + r - 0.01
    fb = Netz()
    fb.drehband([(0.019, z0), (0.019, z0 + 0.12), (0.013, z0 + 0.13), (0.011, z1)],
                0.0, 2 * math.pi, 12, 0)
    fb.drehband([(0.034, z0 + 0.1), (0.034, z0 + 0.108), (0.0, z0 + 0.112)],
                0.0, 2 * math.pi, 16, 0)
    daempfer = fb.objekt("federbein", [mats["chrom"]])
    daempfer.data.transform(Matrix(((1, 0, 0, 0), (0, 0, 1, 0), (0, 1, 0, 0), (0, 0, 0, 1))))
    daempfer.data.flip_normals()
    daempfer.data.transform(Matrix.Translation((x_f, y_f, 0)))
    teile.append(daempfer)
    # Feder als Schraubenlinie
    feder = Netz()
    windungen, je, seiten = 5.5, 14, 6
    rf, rd = 0.029, 0.0048
    za, ze = z0 + 0.112, z1 - 0.03
    n = int(windungen * je)
    ringe = []
    for k in range(n + 1):
        t = k / n
        w = 2 * math.pi * windungen * t
        c = Vector((x_f + rf * math.cos(w), y_f + rf * math.sin(w), za + (ze - za) * t))
        tang = Vector((-math.sin(w) * rf * 2 * math.pi * windungen, math.cos(w) * rf * 2 * math.pi * windungen,
                       ze - za)).normalized()
        a = Vector((math.cos(w), math.sin(w), 0.0))
        b = tang.cross(a)
        ringe.append([tuple(c + rd * (math.cos(2 * math.pi * j / seiten) * a + math.sin(2 * math.pi * j / seiten) * b))
                      for j in range(seiten)])
    feder.loft(ringe, 0)
    teile.append(feder.objekt("feder", [mats["zierteil"]]))
    # Querlenker unten und Antriebswelle zur Nabe
    arm = Netz()
    z_a = rad_r - 0.13
    ringe = []
    for yy, hb in ((innen - 0.02, 0.07), (innen + 0.04, 0.025)):
        ringe.append([(achse_x + dx * hb, seite * yy, z_a + dz * 0.012)
                      for dx, dz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    arm.loft(ringe, 0)
    welle = Netz()
    welle.drehband([(0.022, innen - 0.05), (0.022, innen + 0.02), (0.03, innen + 0.03),
                    (0.03, innen + 0.045)], 0.0, 2 * math.pi, 10, 0)
    w_ob = welle.objekt("welle", [mats["kunststoff"]])
    if seite < 0:
        w_ob.data.transform(Matrix.Diagonal((1, -1, 1, 1)))
        w_ob.data.flip_normals()
    w_ob.data.transform(Matrix.Translation((achse_x, 0, rad_r)))
    teile += [arm.objekt("querlenker", [mats["kunststoff"]]), w_ob]
    for o in teile:
        for pol in o.data.polygons:
            pol.use_smooth = True
    return teile
