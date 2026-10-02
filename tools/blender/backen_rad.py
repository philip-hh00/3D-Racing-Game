"""Backwerkzeug der Räder: Texturen aus Cycles-Bakes und numpy.

Läuft **in Blender**. ``teile_rad.py`` baut die Räder als sparsame
Spielgeometrie mit eigener UV-Belegung; dieses Modul macht daraus Texturen,
die der Renderer versteht (glTF: ``baseColorTexture``, ``normalTexture`` im
OpenGL-Tangentenraum, ``metallicRoughnessTexture`` und ``occlusionTexture``
in einer ORM-Textur: R Verdeckung, G Rauheit, B Metallic).

Der Weg ist zweistufig:

1. **Cycles backt, was Geometrie braucht**: die Lage jedes Texels im Raum
   (Position, Normale, Teilnummer — Emissions-Bakes in Fließkommabilder),
   die Umgebungsverdeckung (AO) des ganzen Rads und abgerundete Kanten (der
   Bevel-Knoten, als Tangentennormalen gebacken).
2. **numpy rechnet die Oberfläche**: aus Position und Teilnummer entstehen
   Farbe, Rauheit, Metallic und ein Höhenfeld (Schrift, Lamellen, Bohrungen,
   Schleifspuren …). Aus dem Höhenfeld werden Tangentennormalen — mit den
   echten Texelabständen in Metern aus der Positionskarte — und mit den
   Bevel-Normalen verrechnet.

So wirken Details in Millimetern, ohne dass die Spielgeometrie sie tragen
muss. Schrift kommt aus Blenders Textobjekten (``data/fonts/NotoSans-Spiel.ttf``),
wird hier zu einer Maske gerastert und auf Reifenflanke oder Bremssattel
gelegt.

Richtungen im numpy-Bild: ``bild[j, i]`` — Zeile ``j`` wächst mit ``v``
(Blender-Konvention, Zeile 0 unten), Spalte ``i`` mit ``u``.
"""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import bmesh
import bpy
import numpy as np

try:                                    # Grafikkarte wählen wie das gemeinsame Backwerkzeug
    import backen as _gemeinsam
except ImportError:                     # pragma: no cover - ohne backen.py: CPU
    _gemeinsam = None

_ORDNER: Path | None = None


def ordner() -> Path:
    """Arbeitsordner für die gebackenen PNGs (der glTF-Export liest sie dort)."""
    global _ORDNER
    if _ORDNER is None or not _ORDNER.exists():
        _ORDNER = Path(tempfile.mkdtemp(prefix="rad_texturen_"))
    return _ORDNER


# ---------------------------------------------------------------------------
# Cycles
# ---------------------------------------------------------------------------

class Backszene:
    """Cycles einstellen und alles außer ``sichtbar`` aus dem Render nehmen.

    Das Rad wird im Ursprung gebacken, wo sonst die Karosserie steht; ohne
    Ausblenden träfen die AO-Strahlen das Blech.
    """

    def __init__(self, sichtbar, ao_distanz_m: float = 0.08) -> None:
        self.sichtbar = set(o.name for o in sichtbar)
        self.ao_distanz_m = ao_distanz_m

    def __enter__(self):
        sz = bpy.context.scene
        self.alt_engine = sz.render.engine
        self.alt_welt = sz.world
        self.versteckt = []
        for o in sz.objects:
            if o.name not in self.sichtbar and not o.hide_render:
                o.hide_render = True
                self.versteckt.append(o.name)
        sz.render.engine = "CYCLES"
        sz.cycles.device = "CPU"
        if _gemeinsam is not None and hasattr(_gemeinsam, "geraet_waehlen"):
            try:
                _gemeinsam.geraet_waehlen()
            except Exception:           # pragma: no cover - Treiber
                sz.cycles.device = "CPU"
        sz.cycles.use_denoising = False
        welt = bpy.data.worlds.get("_backwelt") or bpy.data.worlds.new("_backwelt")
        welt.light_settings.distance = self.ao_distanz_m
        sz.world = welt
        return self

    def __exit__(self, *_):
        sz = bpy.context.scene
        for n in self.versteckt:
            o = bpy.data.objects.get(n)
            if o is not None:
                o.hide_render = False
        sz.render.engine = self.alt_engine
        sz.world = self.alt_welt
        return False


def bild_fliess(name: str, breite: int, hoehe: int):
    """Leeres Fließkommabild (Alpha 0 = nicht getroffen)."""
    alt = bpy.data.images.get(name)
    if alt is not None:
        bpy.data.images.remove(alt)
    img = bpy.data.images.new(name, breite, hoehe, alpha=True, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    img.generated_color = (0.0, 0.0, 0.0, 0.0)
    return img


def _bakematerial(knoten_fn, bild):
    m = bpy.data.materials.new("_backen")
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    aus = nt.nodes.new("ShaderNodeOutputMaterial")
    schatten = knoten_fn(nt) if knoten_fn is not None else None
    if schatten is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        schatten = bsdf.outputs[0]
    nt.links.new(schatten, aus.inputs["Surface"])
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bild
    nt.nodes.active = tex
    return m


def backen(objekte, bild, art: str, knoten_fn=None, samples: int = 1,
           rand_px: int = 0, loeschen: bool = True) -> np.ndarray:
    """``objekte`` mit einem Ersatzmaterial nach ``bild`` backen.

    ``art``: ``EMIT``, ``AO`` oder ``NORMAL`` (Tangentenraum). Die
    Originalmaterialien kommen danach zurück. Liefert das Bild als Feld
    ``(h, w, 4)``.
    """
    mat = _bakematerial(knoten_fn, bild)
    alt = {}
    for o in objekte:
        alt[o.name] = [s.material for s in o.material_slots]
        if not o.material_slots:
            o.data.materials.append(mat)
        for s in o.material_slots:
            s.material = mat
    sz = bpy.context.scene
    sz.cycles.samples = samples
    bpy.ops.object.select_all(action="DESELECT")
    for o in objekte:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objekte[0]
    try:
        bpy.ops.object.bake(type=art, use_clear=loeschen, margin=rand_px,
                            margin_type="EXTEND", normal_space="TANGENT",
                            use_selected_to_active=False, target="IMAGE_TEXTURES")
    finally:
        for o in objekte:
            for s, m in zip(o.material_slots, alt[o.name]):
                s.material = m
            if not alt[o.name]:
                o.data.materials.clear()
        bpy.data.materials.remove(mat)
    return lesen(bild)


def lesen(bild) -> np.ndarray:
    w, h = bild.size
    a = np.empty(w * h * 4, np.float32)
    bild.pixels.foreach_get(a)
    return a.reshape(h, w, 4)


def _emission(quelle):
    def knoten(nt):
        em = nt.nodes.new("ShaderNodeEmission")
        if quelle == "position":
            tc = nt.nodes.new("ShaderNodeTexCoord")
            nt.links.new(tc.outputs["Object"], em.inputs["Color"])
        elif quelle == "normale":
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            nt.links.new(geo.outputs["Normal"], em.inputs["Color"])
        else:
            at = nt.nodes.new("ShaderNodeAttribute")
            at.attribute_type = "GEOMETRY"
            at.attribute_name = quelle
            nt.links.new(at.outputs["Fac"], em.inputs["Color"])
        return em.outputs[0]
    return knoten


def _fase(radius_m: float):
    def knoten(nt):
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bev = nt.nodes.new("ShaderNodeBevel")
        bev.samples = 16
        bev.inputs["Radius"].default_value = radius_m
        nt.links.new(bev.outputs["Normal"], bsdf.inputs["Normal"])
        return bsdf.outputs[0]
    return knoten


class Karten:
    """Die Geometriekarten einer UV-Belegung: Position, Normale, Teil, Deckung."""

    def __init__(self, objekte, breite: int, hoehe: int, teil_attribut: str = "teil") -> None:
        self.breite, self.hoehe = breite, hoehe
        b = bild_fliess("_karte", breite, hoehe)
        a = backen(objekte, b, "EMIT", _emission("position"), rand_px=2)
        self.pos = a[..., :3].copy()
        self.gedeckt = a[..., 3] > 0.5
        self.nor = backen(objekte, b, "EMIT", _emission("normale"), rand_px=2)[..., :3].copy()
        ln = np.linalg.norm(self.nor, axis=2, keepdims=True)
        self.nor /= np.maximum(ln, 1e-6)
        # Teilnummern ohne Rand (sonst mischt die Randfüllung Nachbarn).
        self.teil = np.rint(backen(objekte, b, "EMIT", _emission(teil_attribut))[..., 0]).astype(np.int32)
        bpy.data.images.remove(b)
        # Texelgröße in Metern je Richtung (für Höhe → Normale).
        self.du, self.dv = self._schritt()

    def _schritt(self):
        p = self.pos
        du = np.zeros(p.shape[:2], np.float32)
        dv = np.zeros(p.shape[:2], np.float32)
        du[:, 1:-1] = np.linalg.norm(p[:, 2:] - p[:, :-2], axis=2) / 2
        dv[1:-1, :] = np.linalg.norm(p[2:, :] - p[:-2, :], axis=2) / 2
        return du, dv

    def zylinder(self):
        """(Radius um Y, Winkel in der XZ-Ebene) je Texel."""
        x, z = self.pos[..., 0], self.pos[..., 2]
        return np.hypot(x, z), np.arctan2(z, x)


def ao_distanz(meter: float) -> None:
    """Reichweite der AO-Strahlen (Cycles liest sie aus der Welt)."""
    bpy.context.scene.world.light_settings.distance = meter


def ao(objekte, breite: int, hoehe: int, samples: int = 64, loeschen: bool = True,
       bild=None) -> np.ndarray:
    """Umgebungsverdeckung backen; mit ``bild`` und ``loeschen=False`` kommen
    weitere Objekte in dasselbe Bild."""
    b = bild if bild is not None else bild_fliess("_ao", breite, hoehe)
    a = backen(objekte, b, "AO", None, samples=samples, rand_px=4, loeschen=loeschen)
    return a


def fase(objekte, breite: int, hoehe: int, radius_m: float) -> np.ndarray:
    """Abgerundete Kanten als Tangentennormalen (−1..1)."""
    b = bild_fliess("_fase", breite, hoehe)
    a = backen(objekte, b, "NORMAL", _fase(radius_m), samples=4, rand_px=4)
    bpy.data.images.remove(b)
    n = a[..., :3] * 2.0 - 1.0
    leer = a[..., 3] < 0.5
    n[leer] = (0.0, 0.0, 1.0)
    return n


# ---------------------------------------------------------------------------
# numpy: Rauschen, Höhe → Normale, Mischen
# ---------------------------------------------------------------------------

def _hash(ix, iy, iz, keim):
    h = (ix.astype(np.int64) * 374761393 + iy.astype(np.int64) * 668265263
         + iz.astype(np.int64) * 1274126177 + keim * 97531) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF).astype(np.float32) / 65535.0


def rauschen(p: np.ndarray, skala_m: float, keim: int = 0) -> np.ndarray:
    """Wertrauschen 0..1, dreilinear, ``p`` (..., 3) in Metern."""
    q = p / skala_m
    i = np.floor(q)
    f = q - i
    f = f * f * (3 - 2 * f)
    i = i.astype(np.int64)
    ergebnis = 0.0
    for dx in (0, 1):
        wx = f[..., 0] if dx else 1 - f[..., 0]
        for dy in (0, 1):
            wy = f[..., 1] if dy else 1 - f[..., 1]
            for dz in (0, 1):
                wz = f[..., 2] if dz else 1 - f[..., 2]
                ergebnis = ergebnis + wx * wy * wz * _hash(i[..., 0] + dx, i[..., 1] + dy,
                                                          i[..., 2] + dz, keim)
    return ergebnis


def fbm(p: np.ndarray, skala_m: float, stufen: int = 3, keim: int = 0) -> np.ndarray:
    s, a, summe, gewicht = skala_m, 1.0, 0.0, 0.0
    for k in range(stufen):
        summe = summe + a * rauschen(p, s, keim + 17 * k)
        gewicht += a
        s *= 0.5
        a *= 0.55
    return summe / gewicht


def glaetten(a: np.ndarray, px: int) -> np.ndarray:
    """Kastenfilter (zweimal: annähernd Gauß), Rand geklemmt."""
    if px <= 0:
        return a
    for _ in range(2):
        for achse in (0, 1):
            pad = [(0, 0)] * a.ndim
            pad[achse] = (px, px)
            b = np.pad(a, pad, mode="edge")
            c = np.cumsum(b, axis=achse, dtype=np.float64)
            z = np.zeros_like(np.take(c, [0], axis=achse))
            c = np.concatenate([z, c], axis=achse)
            n = a.shape[achse]
            a = ((np.take(c, np.arange(2 * px + 1, 2 * px + 1 + n), axis=achse)
                  - np.take(c, np.arange(0, n), axis=achse)) / (2 * px + 1)).astype(np.float32)
    return a


def normale_aus_hoehe(h: np.ndarray, k: Karten) -> np.ndarray:
    """Tangentennormalen (−1..1) aus einem Höhenfeld in Metern.

    Gradient über Nachbartexel, geteilt durch deren Abstand im Raum. Wo die
    Nachbarn auf einer anderen UV-Insel liegen (Abstand viel größer als ein
    Texel üblich), bleibt die Fläche glatt.
    """
    n = np.zeros(h.shape + (3,), np.float32)
    n[..., 2] = 1.0
    typisch = np.median(k.du[k.gedeckt & (k.du > 0)]) if np.any(k.gedeckt) else 1e-3
    for achse, d in ((1, k.du), (0, k.dv)):
        vor = np.roll(h, -1, axis=achse)
        nach = np.roll(h, 1, axis=achse)
        ok = (d > 1e-7) & (d < typisch * 6)
        # Deckung beider Nachbarn
        ok &= np.roll(k.gedeckt, -1, axis=achse) & np.roll(k.gedeckt, 1, axis=achse)
        g = np.where(ok, (vor - nach) / np.maximum(2 * d, 1e-9), 0.0)
        n[..., 0 if achse == 1 else 1] = -g
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return n


def normalen_mischen(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Zwei Tangentennormalen (−1..1) überlagern („Whiteout“)."""
    n = np.stack([a[..., 0] + b[..., 0], a[..., 1] + b[..., 1], a[..., 2] * b[..., 2]], axis=2)
    return n / np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-6)


def ausdehnen(a: np.ndarray, gedeckt: np.ndarray, schritte: int = 12) -> np.ndarray:
    """Werte über den Inselrand hinaus fortsetzen (gegen Säume in Mipmaps)."""
    a = a.copy()
    m = gedeckt.copy()
    for _ in range(schritte):
        if m.all():
            break
        summe = np.zeros_like(a)
        anzahl = np.zeros(m.shape, np.float32)
        for dj, di in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            mm = np.roll(np.roll(m, dj, 0), di, 1)
            aa = np.roll(np.roll(a, dj, 0), di, 1)
            summe += aa * (mm[..., None] if a.ndim == 3 else mm)
            anzahl += mm
        neu = (~m) & (anzahl > 0)
        teil = summe / np.maximum(anzahl, 1)[..., None] if a.ndim == 3 else summe / np.maximum(anzahl, 1)
        a[neu] = teil[neu]
        m |= neu
    return a


def lin_nach_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def srgb_nach_lin(c):
    c = np.clip(np.asarray(c, np.float32), 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def verkleinern(a: np.ndarray, faktor: int) -> np.ndarray:
    if faktor <= 1:
        return a
    h, w = a.shape[:2]
    a = a[:h - h % faktor, :w - w % faktor]
    form = (h // faktor, faktor, w // faktor, faktor) + a.shape[2:]
    return a.reshape(form).mean(axis=(1, 3))


# ---------------------------------------------------------------------------
# Schrift
# ---------------------------------------------------------------------------

_SCHRIFT = None


def schrift():
    global _SCHRIFT
    try:
        if _SCHRIFT is not None and _SCHRIFT.name:
            return _SCHRIFT
    except ReferenceError:
        pass
    # Eine statische Schrift: variable Schriften (Blenders Inter) haben sich
    # überlappende Konturen, die beim Füllen Löcher in N, R, A stanzen.
    kandidaten = [Path(__file__).resolve().parents[2] / "data" / "fonts" / "NotoSans-Spiel.ttf",
                  Path(bpy.utils.system_resource("DATAFILES")) / "fonts" / "Inter.woff2"]
    for pfad in kandidaten:
        if not pfad.exists():
            continue
        try:
            _SCHRIFT = bpy.data.fonts.load(str(pfad), check_existing=True)
            return _SCHRIFT
        except (RuntimeError, OSError):              # pragma: no cover
            continue
    _SCHRIFT = bpy.data.fonts.load("<builtin>")
    return _SCHRIFT


class Schriftbild:
    """Ein Text als gerasterte Maske; Mitte im Ursprung, Meter.

    ``hoehe_m``: Versalhöhe. ``fett``: Umriss verbreitern (Anteil der Höhe),
    ``kursiv``: Scherung, ``sperren``: Zeichenabstand (Blender ``space_character``).

    Gerastert wird aus den Umrissen der Glyphen (gerade-ungerade Regel), nicht
    aus Blenders Füllung: die stanzt bei fetter oder variabler Schrift Löcher.
    """

    def __init__(self, text: str, hoehe_m: float, px_pro_m: float, fett: float = 0.0,
                 kursiv: float = 0.0, sperren: float = 1.0, breite_f: float = 1.0) -> None:
        from mathutils.geometry import interpolate_bezier
        cu = bpy.data.curves.new("_schrift", "FONT")
        cu.body = text
        cu.font = schrift()
        cu.size = 1.0
        cu.space_character = sperren
        cu.align_x = "CENTER"
        cu.align_y = "CENTER"
        ob = bpy.data.objects.new("_schrift", cu)
        bpy.context.scene.collection.objects.link(ob)
        dg = bpy.context.evaluated_depsgraph_get()
        kurve = ob.evaluated_get(dg).to_curve(dg)
        # Versalhöhe: ein "H" ist bei Blenders Schriftgröße 1 rund 0.505 hoch
        # (gemessen, Segoe UI wie Inter).
        skala = hoehe_m / 0.505
        umrisse = []
        for sp in kurve.splines:
            pkt = []
            if sp.type == "BEZIER":
                bp = sp.bezier_points
                n = len(bp)
                for i in range(n):
                    a, b_ = bp[i], bp[(i + 1) % n]
                    teil = interpolate_bezier(a.co, a.handle_right, b_.handle_left, b_.co, 7)
                    pkt += [(q.x, q.y) for q in teil[:-1]]
            else:
                pkt = [(q.co.x, q.co.y) for q in sp.points]
            if len(pkt) >= 3:
                umrisse.append([((x + kursiv * y) * skala * breite_f, y * skala) for x, y in pkt])
        ob.to_curve_clear()
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.curves.remove(cu)
        xs = [q[0] for u in umrisse for q in u] or [0.0]
        ys = [q[1] for u in umrisse for q in u] or [0.0]
        rand = hoehe_m * 0.3
        self.x0, self.x1 = min(xs) - rand, max(xs) + rand
        self.y0, self.y1 = min(ys) - rand, max(ys) + rand
        self.px = px_pro_m
        w = max(2, int(math.ceil((self.x1 - self.x0) * px_pro_m)))
        h = max(2, int(math.ceil((self.y1 - self.y0) * px_pro_m)))
        m = _fuellen(umrisse, self.x0, self.y0, px_pro_m, w, h)
        dick = int(round(fett * hoehe_m * px_pro_m))
        if dick > 0:
            m = _weiten(m, dick)
        self.maske = m

    def abtasten(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Maske an Stellen (Meter, Textkoordinaten) bilinear, außen 0."""
        return bilinear(self.maske, (x - self.x0) * self.px - 0.5, (y - self.y0) * self.px - 0.5)


def _fuellen(umrisse, x0, y0, px, w, h, ueber: int = 3) -> np.ndarray:
    """Geschlossene Umrisse mit der Gerade-ungerade-Regel füllen, überabgetastet."""
    W, H = w * ueber, h * ueber
    s = px * ueber
    kanten = []
    for u in umrisse:
        for (ax, ay), (bx, by) in zip(u, u[1:] + u[:1]):
            kanten.append(((ax - x0) * s, (ay - y0) * s, (bx - x0) * s, (by - y0) * s))
    k = np.array(kanten, np.float64)
    ya = np.minimum(k[:, 1], k[:, 3])
    yb = np.maximum(k[:, 1], k[:, 3])
    m = np.zeros((H, W), np.float32)
    spalten = np.arange(W) + 0.5
    for j in range(H):
        yy = j + 0.5
        sel = (ya <= yy) & (yb > yy)
        if not np.any(sel):
            continue
        e = k[sel]
        t = (yy - e[:, 1]) / (e[:, 3] - e[:, 1])
        xs = np.sort(e[:, 0] + t * (e[:, 2] - e[:, 0]))
        # Anzahl der Schnitte links von jeder Spalte: ungerade = innen
        m[j] = (np.searchsorted(xs, spalten) % 2).astype(np.float32)
    return verkleinern(m, ueber)


def _weiten(m: np.ndarray, px: int) -> np.ndarray:
    """Maske um ``px`` Pixel verbreitern (rundes Strukturelement)."""
    aus = m.copy()
    for dj in range(-px, px + 1):
        for di in range(-px, px + 1):
            if dj * dj + di * di > px * px:
                continue
            aus = np.maximum(aus, np.roll(np.roll(m, dj, 0), di, 1))
    return aus


def bilinear(bild: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """``bild[j, i]`` an Gleitkommastellen (Spalte x, Zeile y), außen 0."""
    h, w = bild.shape
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = x - x0, y - y0
    ergebnis = np.zeros(x.shape, np.float32)
    for dx, wx in ((0, 1 - fx), (1, fx)):
        for dy, wy in ((0, 1 - fy), (1, fy)):
            xi, yi = x0 + dx, y0 + dy
            ok = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
            werte = np.zeros(x.shape, np.float32)
            werte[ok] = bild[yi[ok], xi[ok]]
            ergebnis += wx * wy * werte
    return ergebnis


# ---------------------------------------------------------------------------
# Bilder schreiben und Material
# ---------------------------------------------------------------------------

def bild_schreiben(name: str, rgb: np.ndarray, srgb: bool = False):
    """Ein fertiges Bild (h, w, 3; linear 0..1) als PNG ablegen und laden.

    ``srgb``: Farbbild — wird vor dem Speichern nach sRGB gewandelt.
    """
    h, w = rgb.shape[:2]
    daten = lin_nach_srgb(rgb) if srgb else np.clip(rgb, 0.0, 1.0)
    rgba = np.concatenate([daten, np.ones((h, w, 1), np.float32)], axis=2).astype(np.float32)
    alt = bpy.data.images.get(name)
    if alt is not None:
        bpy.data.images.remove(alt)
    img = bpy.data.images.new(name, w, h, alpha=False)
    img.colorspace_settings.name = "sRGB" if srgb else "Non-Color"
    img.pixels.foreach_set(rgba.ravel())
    pfad = ordner() / f"{name}.png"
    img.filepath_raw = str(pfad)
    img.file_format = "PNG"
    img.save()
    img.reload()
    return img


def normalbild(name: str, n: np.ndarray):
    return bild_schreiben(name, n * 0.5 + 0.5)


def _gltf_ausgang(nt):
    """Die Knotengruppe, aus der der glTF-Export die Verdeckung liest."""
    gruppe = bpy.data.node_groups.get("glTF Material Output")
    if gruppe is None:
        gruppe = bpy.data.node_groups.new("glTF Material Output", "ShaderNodeTree")
        gruppe.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
        gruppe.interface.new_socket("Thickness", in_out="INPUT", socket_type="NodeSocketFloat")
    knoten = nt.nodes.new("ShaderNodeGroup")
    knoten.node_tree = gruppe
    return knoten


def material(m, basis, orm, normal, normal_staerke: float = 1.0):
    """Principled-Material mit Farb-, ORM- und Normalentextur (glTF-tauglich).

    ``m``: ein vorhandenes Material (seine Knoten werden ersetzt) oder ein Name.
    """
    if isinstance(m, str):
        m = bpy.data.materials.get(m) or bpy.data.materials.new(m)
    m.use_nodes = True
    nt = m.node_tree
    for k in list(nt.nodes):
        nt.nodes.remove(k)
    aus = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], aus.inputs["Surface"])
    t_basis = nt.nodes.new("ShaderNodeTexImage")
    t_basis.image = basis
    nt.links.new(t_basis.outputs["Color"], bsdf.inputs["Base Color"])
    t_orm = nt.nodes.new("ShaderNodeTexImage")
    t_orm.image = orm
    trenn = nt.nodes.new("ShaderNodeSeparateColor")
    nt.links.new(t_orm.outputs["Color"], trenn.inputs["Color"])
    nt.links.new(trenn.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(trenn.outputs["Blue"], bsdf.inputs["Metallic"])
    ausgang = _gltf_ausgang(nt)
    nt.links.new(trenn.outputs["Red"], ausgang.inputs["Occlusion"])
    t_n = nt.nodes.new("ShaderNodeTexImage")
    t_n.image = normal
    nk = nt.nodes.new("ShaderNodeNormalMap")
    nk.space = "TANGENT"
    nk.inputs["Strength"].default_value = normal_staerke
    nt.links.new(t_n.outputs["Color"], nk.inputs["Color"])
    nt.links.new(nk.outputs["Normal"], bsdf.inputs["Normal"])
    return m


def uv_ebene(ob, name: str = "UVMap"):
    """UV-Ebene eines Objekts (anlegen, falls es keine gibt)."""
    if not ob.data.uv_layers:
        ob.data.uv_layers.new(name=name)
    return ob.data.uv_layers.active
