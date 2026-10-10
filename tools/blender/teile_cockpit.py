"""Cockpit ab 1.1.0: Augpunkt, Lenkrad, Instrumente und Spiegel als eigene Knoten.

Läuft in Blender. Der Vertrag steht in ``src/render3d/VEREINBARUNGEN.md``
(Abschnitt „Cockpit (ab 1.1.0)“). Was hier entsteht, geht nur in die volle
Stufe ``<key>.glb``, nicht in LOD1.

Knoten (alle mit Ursprung wie im Vertrag; Drehung des Knotens = Achsenlage):

``augpunkt``
    leeres Objekt in Augenhöhe des Fahrers (links, +Y), Blick nach +X.
``lenkrad``
    Ursprung in der Kranzmitte auf der Lenksäulenachse. Lokale **+X** zeigt
    entlang der Säule zum Fahrer hin (nach hinten oben geneigt), lokale +Z ist
    „oben“ am Rad, lokale +Y zeigt zur Rechten des Fahrers. Drehung um +X ist
    für den Fahrer gegen den Uhrzeigersinn, also nach links. Am Kranz oben
    sitzt eine helle Markierung.
``nadel_tacho`` ``nadel_drehzahl``
    Ursprung im Drehpunkt. Lokale **+X** zeigt vom Fahrer weg ins Instrument,
    +Z ist „oben“ im Zifferblatt. Das Netz zeigt bei Knotendrehung 0 auf
    12 Uhr; die Skala läuft von -135° (Anfang, unten links) bis +135° (Ende,
    unten rechts). Drehung um +X ist für den Fahrer im Uhrzeigersinn.
``spiegel_innen`` ``spiegel_l`` ``spiegel_r``
    Ursprung in der Mitte der Glasfläche, Knoten ohne Drehung. Das Netz ist die
    Glasfläche (Material ``spiegel``), Normale zum Fahrer, UV 0..1 über die
    Fläche: U nach rechts, wie der Fahrer hineinschaut, V nach oben.

Die Zifferblätter (``instr_tacho``, ``instr_drehzahl``) sind für jedes Auto
neu gezeichnete Texturen: Skala aus Höchstgeschwindigkeit und Drehzahlgrenze
der Fahrzeugdatei. Sie gehören zur Karosserie (starr, wie das Armaturenbrett).
"""
from __future__ import annotations

import json
import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

import gemeinsam as g
import teile as t

M_PER_PX = 0.08                    # wie src/core/settings.py
KMH_PER_PXS = M_PER_PX * 3.6

#: Skalenwinkel in Grad, im Uhrzeigersinn ab 12 Uhr (Vertrag: Drehung um die
#: lokale X-Achse der Nadel bei 0 und bei Maximum).
SKALA_GRAD = (-135.0, 135.0)

#: Lenkübersetzung (Lenkradwinkel / Radwinkel) je Fahrzeugfamilie.
UEBERSETZUNG = {"rookie": 14.0, "limousine": 15.0, "supercar": 12.0, "drifter": 12.0, "electric": 13.5}

# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _basis(x_achse: Vector, oben_hinweis=Vector((0, 0, 1))):
    """Rechtshändige Basis (x, y, z) mit ``x`` als erster Achse und ``z`` möglichst nach oben."""
    x = Vector(x_achse).normalized()
    z = Vector(oben_hinweis) - x * Vector(oben_hinweis).dot(x)
    z.normalize()
    y = z.cross(x)
    return x, y, z


def _matrix(ort: Vector, x: Vector, y: Vector, z: Vector) -> Matrix:
    return Matrix(((x.x, y.x, z.x, ort.x), (x.y, y.y, z.y, ort.y),
                   (x.z, y.z, z.z, ort.z), (0, 0, 0, 1)))


def _in_welt(ob, m: Matrix) -> None:
    """Netz eines Objekts (Koordinaten im lokalen Rahmen) mit ``m`` in die Welt bringen."""
    ob.data.transform(m)
    ob.data.update()


def _leer(name: str, ort) -> bpy.types.Object:
    ob = bpy.data.objects.new(name, None)
    ob.empty_display_type = "SPHERE"
    ob.empty_display_size = 0.05
    ob.location = Vector(ort)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _als_knoten(ob, name: str, m: Matrix) -> bpy.types.Object:
    """Objekt mit lokal modelliertem Netz zu einem Knoten mit Weltmatrix ``m`` machen."""
    ob.name = name
    ob.data.name = name
    ob.matrix_world = m
    return ob


def _stab(name, a, b, r, mat, n=10):
    """Zylinder von ``a`` nach ``b``."""
    a, b = Vector(a), Vector(b)
    d = b - a
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=n, radius1=r, radius2=r,
                          depth=d.length)
    q = Vector((0, 0, 1)).rotation_difference(d.normalized())
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=q.to_matrix())
    bmesh.ops.translate(bm, verts=bm.verts, vec=(a + b) / 2)
    return g.objekt_aus(bm, name, [mat])


# ---------------------------------------------------------------------------
# Plan: wo sitzt der Fahrer?
# ---------------------------------------------------------------------------

class Plan:
    """Lage von Auge, Lenkrad, Zifferblättern und Haubenpunkt im Fahrzeugsystem."""


def _fahrzeugdaten(key: str) -> dict:
    with open(g.WURZEL / "data" / "vehicles" / f"{key}.json", encoding="utf-8") as fh:
        return json.load(fh)["physics"]


def tacho_max(spitze_kmh: float) -> tuple[int, int]:
    """Skalenende und Abstand der Zahlen: das nächste runde Vielfache über der Höchstgeschwindigkeit."""
    schritt = 20 if spitze_kmh * 1.02 <= 200 else 40
    return int(math.ceil(spitze_kmh * 1.02 / schritt) * schritt), schritt


def drehzahl_max(rot_ab: float) -> tuple[int, int]:
    """Skalenende (volle 1000, gerade über 10000) und Abstand der Zahlen."""
    ende = int(math.ceil(rot_ab * 1.02 / 1000.0)) * 1000
    if ende > 10000:
        ende += ende % 2000
        return ende, 2000
    return ende, 1000


def planen(fo, p: dict, L) -> Plan:
    """Fahrerposition und Lage aller Cockpitteile; ``L`` ist ``teile_innen.Layout``."""
    ms = fo.ms
    key = p.get("_key", "")
    phys = _fahrzeugdaten(key)
    pl = Plan()
    pl.layout = L
    # --- Sitz und Auge ---------------------------------------------------------
    s = L.sitz
    if s:
        xs, ys, zs = s["x"], s["y"], s["z"]
    else:
        xs = L.x_a - 0.56
        u_s = ms.u(xs - 0.24)
        zs = L.boden(u_s) + 0.14
        ys = 0.5 * min(fo.ws(u_s) - 0.08, fo.wg(u_s) - 0.05)
    z_polster = zs + 0.112
    x_e = xs - 0.46
    dach = fo.oben(ms.u(x_e), ys) - 0.02
    z_e = min(z_polster + 0.72, dach - 0.10)
    pl.auge = Vector((x_e, ys, z_e))
    pl.auge_ueber_polster = z_e - z_polster
    # --- Lenkrad -----------------------------------------------------------------
    pl.kranz_r = 0.15 if L.art == "schale" else 0.175
    pl.neigung = math.radians(22.0)             # Säulenachse über der Waagerechten
    z_w = min(L.z_a + 0.03, z_e - 0.10 - 0.93 * pl.kranz_r)
    # --- Zifferblätter -----------------------------------------------------------
    # Das Kombiinstrument sitzt **im Armaturenbrett**: in dessen Rückwand (x_a - 0,40), unter
    # der Oberkante, die als Haube darüber steht. Nichts ragt über das Armaturenbrett in die
    # Frontscheibe. Das Lenkrad steht davor; aus dem Auge gesehen blickt man durch den Kranz
    # über die Nabe auf die Zifferblätter. Dafür darf das Lenkrad tiefer sitzen, als es
    # sonst stünde (nicht tiefer, als die Oberschenkel zulassen).
    pl.dial_r = 0.046
    pl.dial_abstand = 0.092                      # so weit auseinander, dass die Nabe dazwischen steht
    x_wand = L.x_a - 0.40                        # Rückwand des Armaturenbretts
    z_oben = L.z_a + 0.09                        # Oberkante des Armaturenbretts
    x_dial = x_wand - 0.002                      # Zifferblatt senkrecht, bündig vor der Wand
    x_lenkrad = L.x_a - 0.50                     # Kranzoberkante bleibt hinter der Wand
    z_c_tief = z_oben - 0.02 - (pl.dial_r + 0.009)     # Rahmenoberkante 2 cm unter der Kante
    z_c_hoch = z_c_tief + 0.035                         # höchstens so weit hinauf: Haube 3,5 cm über der Kante
    z_w_min = z_w - 0.07                         # so viel tiefer darf das Lenkrad höchstens sitzen

    def _projektion(x_p: float, z_p: float) -> float:
        """Höhe, in der der Sehstrahl vom Auge durch (x_p, z_p) die Zifferblattebene trifft."""
        return z_e - (z_e - z_p) * (x_dial - x_e) / max(x_p - x_e, 0.1)

    z_c = z_c_tief
    for _ in range(6):
        # Oberkante der waagerechten Speichen (die Nabe steht zwischen den Zifferblättern),
        # aus dem Auge auf die Wand projiziert.
        z_nabe = _projektion(x_lenkrad, z_w + 0.025)
        z_noetig = z_nabe + 0.012 + pl.dial_r + 0.009
        # Im Bild bleiben: Zifferblattmitte höchstens 25 Grad unter dem Horizont (das Sichtfeld der
        # Cockpitkamera reicht 32 Grad nach unten), soweit die Haube das zulässt.
        z_blick = z_e - math.tan(math.radians(25.0)) * (x_dial - x_e)
        z_c = min(max(z_noetig, z_blick, z_c_tief), z_c_hoch)
        if z_noetig <= z_c_hoch + 1e-4 or z_w <= z_w_min:
            break
        k = (x_dial - x_e) / max(x_lenkrad - x_e, 0.1)
        z_w = max(z_w - (z_noetig - z_c_hoch) / k, z_w_min)
    pl.lenkrad = Vector((x_lenkrad, ys, z_w))
    # Mitte der beiden Zifferblätter; links (+Y) die Drehzahl, rechts der Tacho.
    mitte = Vector((x_dial, ys, z_c))
    pl.z_c = z_c
    pl.dial_basis = _basis(Vector((1.0, 0.0, 0.0)))   # +X vom Fahrer weg, gemeinsam für beide Zifferblätter
    pl.dial_mitte = mitte
    y_ax = pl.dial_basis[1]                  # +Y des Blatts (nach links aus Sicht des Fahrers)
    pl.dial_ort = {"drehzahl": mitte + y_ax * pl.dial_abstand,
                   "tacho": mitte - y_ax * pl.dial_abstand}
    top_kmh = phys["max_speed"] * KMH_PER_PXS
    pl.tacho_max, pl.tacho_schritt = tacho_max(top_kmh)
    rot = float(phys.get("redline_rpm", 8000.0))
    pl.drehzahl_rot = rot
    pl.drehzahl_max, pl.drehzahl_schritt = drehzahl_max(rot)
    fam = key.split("_")[0]
    pl.uebersetzung = UEBERSETZUNG.get(fam, 14.0)
    # --- Spiegel (Außenspiegel brauchen das Auge vor dem Bau) --------------------
    return pl


# ---------------------------------------------------------------------------
# Zifferblatt-Textur
# ---------------------------------------------------------------------------

def _kreis(cx, cy, rx, ry, n=20, a0=0.0, a1=2 * math.pi):
    return [(cx + rx * math.cos(a0 + (a1 - a0) * k / n), cy + ry * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


#: Strichschrift: Ziffern und wenige Buchstaben in der Box 0..1 (x), 0..1 (y nach oben).
GLYPHEN = {
    "0": [_kreis(0.5, 0.5, 0.48, 0.5, 20)],
    "1": [[(0.12, 0.76), (0.55, 1.0), (0.55, 0.0)]],
    "2": [[(0.04, 0.78), (0.15, 0.94), (0.5, 1.0), (0.85, 0.94), (0.96, 0.75), (0.84, 0.55),
           (0.04, 0.0), (0.96, 0.0)]],
    "3": [[(0.04, 0.95), (0.9, 0.95), (0.45, 0.56), (0.8, 0.52), (0.96, 0.3), (0.82, 0.06),
           (0.45, 0.0), (0.04, 0.1)]],
    "4": [[(0.74, 0.0), (0.74, 1.0), (0.0, 0.3), (1.0, 0.3)]],
    "5": [[(0.9, 1.0), (0.1, 1.0), (0.05, 0.55), (0.55, 0.62), (0.9, 0.45), (0.96, 0.2),
           (0.7, 0.02), (0.08, 0.06)]],
    "6": [[(0.9, 0.95), (0.5, 1.0), (0.12, 0.75), (0.03, 0.35), (0.15, 0.05), (0.5, 0.0),
           (0.88, 0.12), (0.96, 0.38), (0.75, 0.58), (0.4, 0.6), (0.08, 0.4)]],
    "7": [[(0.04, 1.0), (0.96, 1.0), (0.4, 0.0)]],
    "8": [_kreis(0.5, 0.76, 0.42, 0.24, 14), _kreis(0.5, 0.27, 0.5, 0.27, 16)],
    "9": [[(1 - x, 1 - y) for x, y in [(0.9, 0.95), (0.5, 1.0), (0.12, 0.75), (0.03, 0.35),
                                       (0.15, 0.05), (0.5, 0.0), (0.88, 0.12), (0.96, 0.38),
                                       (0.75, 0.58), (0.4, 0.6), (0.08, 0.4)]]],
    "K": [[(0.1, 0.0), (0.1, 1.0)], [(0.95, 1.0), (0.1, 0.45), (0.95, 0.0)]],
    "M": [[(0.0, 0.0), (0.0, 1.0), (0.5, 0.4), (1.0, 1.0), (1.0, 0.0)]],
    "H": [[(0.05, 0.0), (0.05, 1.0)], [(0.95, 0.0), (0.95, 1.0)], [(0.05, 0.5), (0.95, 0.5)]],
    "R": [[(0.05, 0.0), (0.05, 1.0), (0.8, 1.0), (0.95, 0.8), (0.8, 0.55), (0.05, 0.55)],
          [(0.5, 0.55), (0.95, 0.0)]],
    "P": [[(0.05, 0.0), (0.05, 1.0), (0.8, 1.0), (0.95, 0.78), (0.8, 0.52), (0.05, 0.52)]],
    "X": [[(0.05, 0.0), (0.95, 1.0)], [(0.05, 1.0), (0.95, 0.0)]],
    "/": [[(0.1, 0.0), (0.9, 1.0)]],
}


class _Blatt:
    """Eine quadratische Bildfläche -1..1 (y nach oben), mit Überabtastung."""

    def __init__(self, px: int, ss: int = 2) -> None:
        self.N = px * ss
        self.ss = ss
        self.px = px
        ax = (np.arange(self.N, dtype=np.float32) + 0.5) / self.N * 2 - 1
        self.ax = ax
        self.X, self.Y = np.meshgrid(ax, ax)           # Zeile = y (unten = Zeile 0)
        self.R = np.hypot(self.X, self.Y)
        self.TH = np.degrees(np.arctan2(self.X, self.Y))
        self.aa = 2.0 / self.N
        r2 = self.R ** 2
        self.bild = np.stack([0.030 + 0.020 * r2, 0.034 + 0.022 * r2, 0.042 + 0.028 * r2], axis=-1)

    def deckung(self, d):
        return np.clip(0.5 - d / self.aa, 0.0, 1.0)

    def malen(self, cov, farbe) -> None:
        c = cov[..., None]
        self.bild = self.bild * (1 - c) + np.asarray(farbe, dtype=np.float32) * c

    def ring(self, r0, breite, farbe, grad=None) -> None:
        d = np.abs(self.R - r0) - breite / 2
        cov = self.deckung(d)
        if grad is not None:
            cov = cov * ((self.TH >= grad[0]) & (self.TH <= grad[1]))
        self.malen(cov, farbe)

    def striche(self, abstand_grad, breite, ra, rb, farbe_fn) -> None:
        """Radiale Striche entlang der Skala; ``farbe_fn(winkel_grad)`` liefert die Farbe."""
        t0, t1 = SKALA_GRAD
        n = int(round((t1 - t0) / abstand_grad))
        k = np.clip(np.round((self.TH - t0) / abstand_grad), 0, n)
        ang = t0 + k * abstand_grad
        d_bogen = np.abs(self.TH - ang) * (math.pi / 180) * self.R - breite / 2
        d_rad = np.maximum(ra - self.R, self.R - rb)
        cov = self.deckung(np.maximum(d_bogen, d_rad))
        for i in range(n + 1):
            w = t0 + i * abstand_grad
            self.malen(cov * (k == i), farbe_fn(w))

    def linienzug(self, cov, pts, dicke) -> None:
        """Strichschrift in ``cov`` (Maximum über alle Striche)."""
        xs = [p_[0] for p_ in pts]
        ys = [p_[1] for p_ in pts]
        m = dicke + 2 * self.aa
        i0 = max(0, int((min(ys) - m + 1) / 2 * self.N) - 1)
        i1 = min(self.N, int((max(ys) + m + 1) / 2 * self.N) + 2)
        j0 = max(0, int((min(xs) - m + 1) / 2 * self.N) - 1)
        j1 = min(self.N, int((max(xs) + m + 1) / 2 * self.N) + 2)
        if i0 >= i1 or j0 >= j1:
            return
        PX = self.X[i0:i1, j0:j1]
        PY = self.Y[i0:i1, j0:j1]
        dmin = np.full(PX.shape, 9.0, dtype=np.float32)
        for (ax_, ay_), (bx_, by_) in zip(pts[:-1], pts[1:]):
            dx, dy = bx_ - ax_, by_ - ay_
            l2 = max(dx * dx + dy * dy, 1e-12)
            tt = np.clip(((PX - ax_) * dx + (PY - ay_) * dy) / l2, 0.0, 1.0)
            d = np.hypot(PX - (ax_ + tt * dx), PY - (ay_ + tt * dy))
            dmin = np.minimum(dmin, d)
        c = self.deckung(dmin - dicke / 2)
        cov[i0:i1, j0:j1] = np.maximum(cov[i0:i1, j0:j1], c)

    def text(self, cov, s, cx, cy, h, dicke) -> None:
        b = 0.56 * h
        luecke = 0.2 * h
        gesamt = len(s) * b + (len(s) - 1) * luecke
        x0 = cx - gesamt / 2
        for i, zeichen in enumerate(s):
            gx = x0 + i * (b + luecke)
            for linie in GLYPHEN.get(zeichen, []):
                self.linienzug(cov, [(gx + a * b, cy - h / 2 + c * h) for a, c in linie], dicke)

    def ergebnis(self) -> np.ndarray:
        """Auf ``px`` heruntergerechnet, RGBA, Zeile 0 unten, Werte 0..1 (sRGB)."""
        n = self.N // self.ss
        b = self.bild.reshape(n, self.ss, n, self.ss, 3).mean(axis=(1, 3))
        rgba = np.ones((n, n, 4), dtype=np.float32)
        rgba[..., :3] = np.clip(b, 0, 1)
        return rgba


def zifferblatt(maximum: float, gross: float, klein: float, teiler: float, rot_ab: float | None,
                kopf: str, fuss: str, px: int = 512) -> np.ndarray:
    """Zifferblatt-Bild. ``gross``/``klein``: Abstand der großen/kleinen Striche in
    Skalenwerten, ``teiler``: Zahlen werden durch ihn geteilt, ``rot_ab``: Beginn der
    roten Zone (None: keine), ``kopf``/``fuss``: kleine Aufschriften oben/unten."""
    bl = _Blatt(px)
    t0, t1 = SKALA_GRAD
    weiss, rot, blau = (0.88, 0.9, 0.92), (0.95, 0.2, 0.14), (0.24, 0.5, 0.8)
    f_rot = (rot_ab / maximum) if rot_ab else 2.0

    def farbe(w):
        return rot if (w - t0) / (t1 - t0) >= f_rot - 1e-6 else weiss

    bl.ring(0.965, 0.012, (0.28, 0.3, 0.34))
    # farbiger Bogen innen: blau, in der roten Zone rot
    grenze = t0 + (t1 - t0) * min(f_rot, 1.0)
    bl.ring(0.76, 0.014, blau, (t0, grenze))
    if rot_ab:
        bl.ring(0.76, 0.02, rot, (grenze, t1))
    kl = klein / maximum * (t1 - t0)
    gr = gross / maximum * (t1 - t0)
    bl.striche(kl, 0.010, 0.86, 0.93, farbe)
    bl.striche(gr, 0.024, 0.80, 0.93, farbe)
    cov = np.zeros((bl.N, bl.N), dtype=np.float32)
    n = int(round(maximum / gross))
    for i in range(n + 1):
        w = math.radians(t0 + i * gr)
        zahl = str(int(round(i * gross / teiler)))
        bl.text(cov, zahl, 0.60 * math.sin(w), 0.60 * math.cos(w), 0.19 if len(zahl) < 3 else 0.15, 0.020)
    bl.malen(cov, weiss)
    cov = np.zeros((bl.N, bl.N), dtype=np.float32)
    if kopf:
        bl.text(cov, kopf, 0.0, 0.30, 0.095, 0.014)
    if fuss:
        bl.text(cov, fuss, 0.0, -0.46, 0.115, 0.016)
    bl.malen(cov, (0.62, 0.66, 0.72))
    return bl.ergebnis()


def _zifferblatt_material(name: str, rgba: np.ndarray):
    n = rgba.shape[0]
    img = bpy.data.images.new(name, n, n, alpha=False)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    img.colorspace_settings.name = "sRGB"
    m = g.material(name, (1.0, 1.0, 1.0), 0.0, 0.7, emission=(1.0, 1.0, 1.0), staerke=0.7)
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    return m


# ---------------------------------------------------------------------------
# Bauteile
# ---------------------------------------------------------------------------

def _kranz(r: float, kleinr: float, n_gross: int, n_klein: int, mat, phi0=0.0, phi1=2 * math.pi,
           offen=False):
    """Torus um die lokale X-Achse in der YZ-Ebene; ``phi`` zählt von +Y nach +Z."""
    ringe = []
    schritte = n_gross if not offen else n_gross + 1
    for k in range(schritte):
        phi = phi0 + (phi1 - phi0) * (k / n_gross)
        c = Vector((0.0, r * math.cos(phi), r * math.sin(phi)))
        rad = Vector((0.0, math.cos(phi), math.sin(phi)))
        ring = []
        for j in range(n_klein):
            psi = 2 * math.pi * j / n_klein
            ring.append(tuple(c + rad * (kleinr * math.cos(psi)) + Vector((1, 0, 0)) * (kleinr * math.sin(psi))))
        ringe.append(ring)
    return t.netz_aus_ringen("kranz", ringe, mat, geschlossen=True, schleife=not offen, kappen=offen)


def lenkrad_bauen(pl: Plan, mats):
    """Lenkrad als eigener Knoten (siehe Kopf der Datei)."""
    R = pl.kranz_r
    leder = mats.get("leder", mats["innenraum"])
    im = mats["innenraum"]
    teile = [_kranz(R, 0.017, 32, 8, leder)]
    # helle Markierung oben (12 Uhr), 24° Bogen
    teile.append(_kranz(R, 0.0185, 6, 8, mats["dekor_weiss"], math.radians(78), math.radians(102), offen=True))
    # drei Speichen: links, rechts, unten (lokal: ±Y, -Z)
    teile.append(t.kasten("speiche", (0, 0.5 * R, 0), (0.012, R - 0.02, 0.03), im, fase=0.004))
    teile.append(t.kasten("speiche", (0, -0.5 * R, 0), (0.012, R - 0.02, 0.03), im, fase=0.004))
    teile.append(t.kasten("speiche", (0, 0, -0.5 * R), (0.012, 0.03, R - 0.02), im, fase=0.004))
    # Nabe mit Prallplatte zum Fahrer hin, Säulenstummel nach vorn
    teile.append(t.zylinder_x("nabe", (0.016, 0, 0), 0.052, 0.045, mats["zierteil"], segmente=20))
    teile.append(t.zylinder_x("nabenring", (0.0385, 0, 0), 0.040, 0.004, mats["chrom"], segmente=20))
    teile.append(t.zylinder_x("saeule", (-0.12, 0, 0), 0.03, 0.2, im, segmente=12))
    ob = g.verbinden(teile, "lenkrad")
    for pol in ob.data.polygons:
        pol.use_smooth = True
    n = Vector((-math.cos(pl.neigung), 0.0, math.sin(pl.neigung)))
    x, y, z = _basis(n)
    return _als_knoten(ob, "lenkrad", _matrix(pl.lenkrad, x, y, z)), n


def _dial_rahmen(pl: Plan, ort: Vector):
    """Basis der Zifferblätter: +X vom Fahrer weg, zum Auge geneigt (für beide gleich)."""
    return pl.dial_basis


def _zifferblatt_netz(name: str, r: float, mat, n: int = 32):
    """Scheibe in der lokalen YZ-Ebene, Vorderseite -X (zum Fahrer), UV 0..1 über den Durchmesser."""
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    vs = [bm.verts.new((0.0, -r * math.sin(2 * math.pi * k / n), r * math.cos(2 * math.pi * k / n)))
          for k in range(n)]
    # Blick vom Fahrer (aus -X): rechts = -Y, oben = +Z; Umlaufsinn so, dass die Normale nach -X zeigt
    f = bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=[f])
    if f.normal.x > 0:
        f.normal_flip()
    for lp in f.loops:
        c = lp.vert.co
        lp[uvl].uv = (0.5 - c.y / (2 * r), 0.5 + c.z / (2 * r))
    return g.objekt_aus(bm, name, [mat])


def _nadel_bauen(pl: Plan, name: str, ort: Vector, mats):
    """Nadel mit Drehpunkt im Ursprung des Knotens."""
    r = pl.dial_r
    mat = g.material("nadel", (1.0, 0.42, 0.08), 0.0, 0.4, emission=(1.0, 0.35, 0.04), staerke=1.2)
    blatt = t.umriss_extrudieren("nadelblatt", [(-0.0032, -0.014), (0.0032, -0.014), (0.0016, r * 0.86),
                                                 (0.0, r * 0.9), (-0.0016, r * 0.86)],
                                 0.0016, mat, ebene="yz", mitte=-0.0075)
    nabe = t.zylinder_x("nadelnabe", (-0.0085, 0, 0), 0.0075, 0.005, mats["zierteil"], segmente=14)
    ob = g.verbinden([blatt, nabe], name)
    for pol in ob.data.polygons:
        pol.use_smooth = True
    x, y, z = _dial_rahmen(pl, ort)
    return _als_knoten(ob, name, _matrix(ort, x, y, z))


def instrumente_bauen(pl: Plan, mats) -> tuple[list, list]:
    """Zifferblätter samt Rahmen und Hutze (starr, kommen in die Karosserie) und die beiden Nadeln."""
    # Blende über den Zifferblättern: flache Haube, die aus der Oberkante des Armaturenbretts
    # nach hinten ragt und mit ihr abschließt. Darüber nichts, was in die Scheibe ragt.
    r = pl.dial_r
    br = 2 * (pl.dial_abstand + r + 0.02)
    x_wand = pl.layout.x_a - 0.40
    z_haube = pl.z_c + r + 0.009 + 0.012       # Oberkante der Rahmen plus Luft
    haube = t.kasten("hutze", (x_wand - 0.0175, pl.dial_mitte.y, z_haube), (0.035, br, 0.016),
                     mats["innenraum"], fase=0.006)
    statisch = [haube]
    knoten = []
    bild = {
        "tacho": zifferblatt(pl.tacho_max, pl.tacho_schritt, 10.0, 1.0, None, "", "KMH"),
        "drehzahl": zifferblatt(pl.drehzahl_max, pl.drehzahl_schritt, pl.drehzahl_schritt / 2,
                                1000.0, pl.drehzahl_rot, "X1000", "RPM"),
    }
    for art, ort in pl.dial_ort.items():
        mat = _zifferblatt_material(f"instr_{art}", bild[art])
        x, y, z = _dial_rahmen(pl, ort)
        m = _matrix(ort, x, y, z)
        scheibe = _zifferblatt_netz(f"zifferblatt_{art}", pl.dial_r, mat)
        n = 32
        aussen = [(r + 0.009) * np.array([math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)])
                  for k in range(n)]
        innen = [r * np.array([math.cos(2 * math.pi * k / n), math.sin(2 * math.pi * k / n)])
                 for k in range(n)]
        rahmen = t.streifen_extrudieren(f"instrumentrahmen_{art}", [tuple(a) for a in aussen],
                                        [tuple(a) for a in innen], 0.009, mats["zierteil"], mitte=-0.0035)
        for teil in (scheibe, rahmen):
            _in_welt(teil, m)
            statisch.append(teil)
        knoten.append(_nadel_bauen(pl, f"nadel_{art}", ort, mats))
    return statisch, knoten


# ---------------------------------------------------------------------------
# Spiegel
# ---------------------------------------------------------------------------

def _glas(name: str, mitte: Vector, n: Vector, breite: float, hoehe: float, mat, rundung: float = 3.0,
          punkte: int = 24):
    """Spiegelglas: gerundetes Rechteck, Normale ``n`` zum Betrachter, Ursprung in der Mitte,
    UV 0..1 über die Fläche (U nach rechts aus Sicht des Fahrers)."""
    f = -Vector(n).normalized()
    rechts = f.cross(Vector((0, 0, 1)))
    rechts.normalize()
    oben = rechts.cross(f)
    oben = -oben if oben.z < 0 else oben
    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")
    vs = []
    for k in range(punkte):
        w = 2 * math.pi * k / punkte
        a = t.sp(math.cos(w), 2.0 / rundung) * breite / 2
        b = t.sp(math.sin(w), 2.0 / rundung) * hoehe / 2
        vs.append(bm.verts.new(rechts * a + oben * b))
    fl = bm.faces.new(vs)
    bmesh.ops.recalc_face_normals(bm, faces=[fl])
    if fl.normal.dot(n) < 0:
        fl.normal_flip()
    for lp in fl.loops:
        c = lp.vert.co
        lp[uvl].uv = (0.5 + c.dot(rechts) / breite, 0.5 + c.dot(oben) / hoehe)
    ob = g.objekt_aus(bm, name, [mat])
    ob.location = Vector(mitte)
    return ob


def spiegelmaterial():
    return g.material("spiegel", (0.72, 0.76, 0.8), 1.0, 0.05)


def innenspiegel_bauen(karosserie, fo, pl: Plan, mats):
    """Innenspiegel am Scheibenrahmen: Gehäuse und Stiel starr, Glas als Knoten."""
    ms = fo.ms
    fs = fo.p["kabine"].get("frontscheibe") or []
    u_kopf = min(a for a, _ in fs) if fs else fo.dach_u1 - 0.2
    z_kopf = fo.oben(u_kopf + 0.012, 0.0)
    ziel = Vector((ms.x(u_kopf) + 0.12, 0.0, z_kopf - 0.085))
    treffer = t.strahl(karosserie, pl.auge, ziel - pl.auge)
    glas_pkt = Vector(treffer[0]) if treffer else ziel + Vector((0.12, 0, 0))
    glas_pkt.y = 0.0                  # der Strahl vom Auge trifft seitlich: der Spiegel hängt in der Wagenmitte
    zum_auge = (pl.auge - glas_pkt).normalized()
    mitte = glas_pkt + Vector((zum_auge.x, 0.0, zum_auge.z)).normalized() * 0.075
    mitte.z = min(mitte.z, z_kopf - 0.075)
    n = (pl.auge - mitte).normalized()
    x, y, z = _basis(n)            # +X zum Fahrer; Gehäuse in lokalen Maßen
    breite, hoehe, tiefe = 0.21, 0.058, 0.03
    gehaeuse = t.kasten("innenspiegel", (-tiefe / 2, 0, 0), (tiefe, breite, hoehe), mats["kunststoff"], fase=0.012,
                        segmente=3)
    _in_welt(gehaeuse, _matrix(mitte, x, y, z))
    stiel = _stab("innenspiegelstiel", glas_pkt - zum_auge * 0.01, mitte - zum_auge * 0.01, 0.008,
                  mats["kunststoff"])
    glas = _glas("spiegel_innen", mitte + n * 0.0015, n, breite - 0.016, hoehe - 0.014, spiegelmaterial())
    return [gehaeuse, stiel], glas


def aussenspiegel_knoten(mat) -> list:
    """Gläser der Außenspiegel (von ``teile.spiegel`` gesammelt) als Knoten."""
    knoten = []
    for d in t.SPIEGELGLAS:
        name = "spiegel_l" if d["seite"] > 0 else "spiegel_r"
        ob = _glas(name, d["mitte"], d["normale"], d["breite"], d["hoehe"], mat)
        knoten.append(ob)
    return knoten


# ---------------------------------------------------------------------------
# Zusammenbau
# ---------------------------------------------------------------------------

def bauen(karosserie, fo, p: dict, mats, pl: Plan) -> dict:
    """Alle Cockpitteile bauen.

    Ergebnis: ``statisch`` (gehen in die Karosserie), ``knoten`` (eigene Knoten,
    schon in der Szene) und ``daten`` (Block ``cockpit`` für ``_teile.json``)."""
    statisch, knoten = [], []
    # Augpunkt
    knoten.append(_leer("augpunkt", pl.auge))
    # Lenkrad
    lr, _n = lenkrad_bauen(pl, mats)
    knoten.append(lr)
    # Instrumente
    st, kn = instrumente_bauen(pl, mats)
    statisch += st
    knoten += kn
    # Spiegel
    st, glas = innenspiegel_bauen(karosserie, fo, pl, mats)
    statisch += st
    knoten.append(glas)
    knoten += aussenspiegel_knoten(spiegelmaterial())
    # Haubenpunkt: Mittellinie, kurz vor dem Scheibenfuß
    fs = p["kabine"].get("frontscheibe") or []
    ms = fo.ms
    u_fuss = max(a for a, _ in fs) if fs else fo.dach_u1
    x_h = ms.x(u_fuss) + 0.15
    treffer = t.strahl(karosserie, (x_h, 0.0, 3.0), (0, 0, -1))
    z_h = (treffer[0].z if treffer else fo.T(ms.u(x_h), 0.0)) + 0.10
    daten = {
        "augpunkt": [round(c, 4) for c in pl.auge],
        "haube": [round(x_h, 4), 0.0, round(z_h, 4)],
        "lenkrad_uebersetzung": pl.uebersetzung,
        "tacho_max_kmh": pl.tacho_max, "tacho_winkel_grad": [SKALA_GRAD[0], SKALA_GRAD[1]],
        "drehzahl_max": pl.drehzahl_max, "drehzahl_winkel_grad": [SKALA_GRAD[0], SKALA_GRAD[1]],
    }
    return {"statisch": statisch, "knoten": knoten, "daten": daten}
