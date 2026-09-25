"""Himmel und Sonne: Hintergrund, Umgebungskarte, Schattenkarte.

**Himmel.** Ein Panorama aus ``assets/himmel/<Thema>.jpg`` (aus einem
Poly-Haven-HDRI, siehe ``tools/blender/himmel_bauen.py``). Es ist zugleich
Hintergrund und Umgebung: der PBR-Shader liest es mit Mip-Stufen nach
Rauheit, Lack spiegelt so die Wolken, die man auch sieht.

**Sonne.** Ihre Richtung steht in ``<Thema>.json`` und stammt aus dem hellsten
Punkt des HDRI. Der Schatten fällt damit dorthin, wo am Himmel die Sonne
steht.

**Schattenkarte.** Eine Tiefenkarte aus Sicht der Sonne, orthografisch, um
den Punkt herum, auf den die Kamera schaut. 4096² über 150 m ergeben knapp
4 cm je Texel — genug für scharfe Radschatten unter dem eigenen Auto. Der
Mittelpunkt wird auf das Texelraster eingerastet; sonst flimmern die
Schattenkanten, sobald sich die Kamera bewegt.

**Was steht, wird nicht jedes Bild gezeichnet.** Bäume, Felsen, Häuser und
Gelände bewegen sich nicht; ihr Teil der Karte liegt in einer zweiten,
ruhenden Karte. Die folgt dem Blickpunkt nur in Sprüngen (``NACHFUEHREN_M``)
und wird nur dann neu gezeichnet. In jedem Bild wird sie in die eigentliche
Karte kopiert, und nur die Autos kommen neu dazu. Das spart den größten Teil
der Schattenkarte — sie war mit hunderten Deko-Objekten ein Viertel der
Bildzeit, und fast alles davon ist Python, also auf jedem Rechner gleich
teuer.

**Berge und Hügel** stehen nicht in der Schattenkarte (an ihrem Rand liefe
eine harte Kante über den Hang). Ihren Schatten trägt die Sonnensichtkarte
(:class:`Gelaendesicht`): einmal beim Laden über das ganze Gelände
gerechnet, im Shader mit der Schattenkarte multipliziert.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import camera, shader

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None


class Himmel:
    """Das Himmelspanorama als Textur plus Hintergrund-Durchgang."""

    def __init__(self, ctx, ordner: str | Path, name: str) -> None:
        self.ctx = ctx
        self.textur = None
        self.sonne = np.asarray(shader.SONNE_RICHTUNG, dtype=np.float64)
        self.sonne /= np.linalg.norm(self.sonne)
        self.mips = 0.0
        ordner = Path(ordner)
        bild_pfad = ordner / f"{name}.jpg"
        if name and bild_pfad.is_file():
            from PIL import Image
            from .mesh import textur_hochladen
            self.textur = textur_hochladen(ctx, Image.open(bild_pfad), wiederholen=True)
            self.textur.repeat_y = False
            self.mips = float(np.floor(np.log2(max(self.textur.size))))
            try:
                with open(ordner / f"{name}.json", encoding="utf-8") as fh:
                    daten = json.load(fh)
                s = np.asarray(daten["sonne_richtung"], dtype=np.float64)
                self.sonne = s / np.linalg.norm(s)
            except (OSError, KeyError, ValueError):
                pass
        self.programm = shader.himmelprogramm(ctx)
        ecken = np.array([[-1, -1], [3, -1], [-1, 3]], dtype="f4")
        self._puffer = ctx.buffer(ecken.tobytes())
        self.vao = ctx.vertex_array(self.programm, [(self._puffer, "2f", "in_ecke")])

    def binden(self, einheit: int = 2) -> None:
        if self.textur is not None:
            self.textur.use(einheit)

    def zeichnen(self, mvp: np.ndarray, kamera_position) -> None:
        p = self.programm
        shader.matrix_setzen(p, "inverse_vp", np.linalg.inv(np.asarray(mvp, dtype=np.float64)))
        shader.setzen(p, "kamera_position", tuple(float(w) for w in kamera_position))
        shader.setzen(p, "hat_himmel", 1.0 if self.textur is not None else 0.0)
        self.binden(2)
        # Mit Tiefentest, ohne Tiefe zu schreiben: der Himmel liegt knapp vor
        # der fernen Ebene und landet nur dort, wo noch nichts gezeichnet ist.
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = False
        self.vao.render()
        self.ctx.depth_mask = True

    def freigeben(self) -> None:
        for ding in (self.textur, self.vao, self._puffer, self.programm):
            if ding is not None:
                try:
                    ding.release()
                except Exception:                    # pragma: no cover - Treiber
                    pass


def ortho(halbe_breite: float, nah: float, fern: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = 1.0 / halbe_breite
    m[1, 1] = 1.0 / halbe_breite
    m[2, 2] = -2.0 / (fern - nah)
    m[2, 3] = -(fern + nah) / (fern - nah)
    return m


def schattenkarte_groesse(schatten_px: int) -> int:
    """Kantenlänge für ``grafik.schatten_px``: Zweierpotenz, 512 … 8192.

    0 (ohne Schattenwurf) ergibt die kleinste Karte — die Programme werden
    trotzdem gebraucht, und wer im Menü wieder einschaltet, soll nicht auf ein
    neues Rennen warten müssen.
    """
    n = int(schatten_px) if schatten_px and schatten_px > 0 else 512
    n = max(512, min(8192, n))
    return 1 << int(round(np.log2(n)))


#: So weit darf der Blickpunkt wandern, bevor die ruhende Karte neu
#: gezeichnet wird. Die Karte reicht 75 m um ihre Mitte; hinkt die Mitte 15 m
#: hinterher, bleiben vorn noch 60 m Schatten.
NACHFUEHREN_M = 15.0

_KOPIE_VERTEX = """
#version 330
in vec2 in_ecke;
out vec2 uv;
void main() { uv = in_ecke * 0.5 + 0.5; gl_Position = vec4(in_ecke, 0.0, 1.0); }
"""

_KOPIE_FRAGMENT = """
#version 330
uniform sampler2D quelle;
in vec2 uv;
void main() { gl_FragDepth = texture(quelle, uv).r; }
"""


class Schattenkarte:
    """Tiefenkarte der Sonne rund um den Blickpunkt der Kamera."""

    def __init__(self, ctx, groesse: int = 4096, halbe_breite_m: float = 75.0) -> None:
        self.ctx = ctx
        self.halbe_breite = halbe_breite_m
        self.groesse = 0
        self.textur = self.fbo = None
        self.statisch_textur = self.statisch_fbo = None
        #: Ob die ruhende Karte in diesem Bild neu gezeichnet werden muss.
        self.statisch_neu = True
        self._mitte = None
        self._sonne = None
        self.groesse_setzen(groesse)
        self.programm = shader.schattenprogramm(ctx, instanz=False)
        self.programm_instanz = shader.schattenprogramm(ctx, instanz=True)
        self._kopie = ctx.program(vertex_shader=_KOPIE_VERTEX, fragment_shader=_KOPIE_FRAGMENT)
        ecken = np.array([[-1, -1], [3, -1], [-1, 3]], dtype="f4")
        self._kopie_puffer = ctx.buffer(ecken.tobytes())
        self._kopie_vao = ctx.vertex_array(self._kopie, [(self._kopie_puffer, "2f", "in_ecke")])
        self.licht_mvp = np.eye(4, dtype=np.float32)

    def groesse_setzen(self, schatten_px: int) -> None:
        """Karte in neuer Größe anlegen; die Programme (und damit alle VAOs,
        die an ihnen hängen) bleiben."""
        groesse = schattenkarte_groesse(schatten_px)
        if groesse == self.groesse:
            return
        for ding in (self.fbo, self.textur, self.statisch_fbo, self.statisch_textur):
            if ding is not None:
                ding.release()
        self.groesse = groesse
        self.textur = self.ctx.depth_texture((groesse, groesse))
        self.textur.compare_func = "<="
        self.textur.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.textur.repeat_x = False
        self.textur.repeat_y = False
        self.fbo = self.ctx.framebuffer(depth_attachment=self.textur)
        self.statisch_textur = self.ctx.depth_texture((groesse, groesse))
        self.statisch_textur.compare_func = ""
        self.statisch_textur.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.statisch_fbo = self.ctx.framebuffer(depth_attachment=self.statisch_textur)
        self._mitte = None
        self.statisch_neu = True

    def matrix(self, fokus, sonne, nachfuehren_m: float = NACHFUEHREN_M) -> np.ndarray:
        """Licht-MVP für einen Blickpunkt, auf das Texelraster eingerastet.

        Solange der Blickpunkt weniger als ``nachfuehren_m`` von der Mitte der
        ruhenden Karte entfernt ist, bleibt die Matrix, und ``statisch_neu``
        ist falsch. ``nachfuehren_m=0`` erzwingt eine neue Mitte.
        """
        sonne = np.asarray(sonne, dtype=np.float64)
        sonne = sonne / np.linalg.norm(sonne)
        fokus = np.asarray(fokus, dtype=np.float64)
        if (self._mitte is not None and nachfuehren_m > 0.0
                and np.allclose(sonne, self._sonne)
                and float(np.hypot(*(fokus[:2] - self._mitte[:2]))) < nachfuehren_m):
            self.statisch_neu = False
            return self.licht_mvp
        self._mitte = fokus.copy()
        self._sonne = sonne.copy()
        self.statisch_neu = True
        oben = (0.0, 0.0, 1.0) if abs(sonne[2]) < 0.99 else (0.0, 1.0, 0.0)
        # Erst die Blickmatrix im Ursprung, dann den Fokus darin einrasten.
        blick0 = camera.blick(sonne * 400.0, (0.0, 0.0, 0.0), oben).astype(np.float64)
        f = blick0[:3, :3] @ fokus
        texel = 2.0 * self.halbe_breite / self.groesse
        f[0] = np.round(f[0] / texel) * texel
        f[1] = np.round(f[1] / texel) * texel
        verschiebung = np.eye(4)
        verschiebung[:3, 3] = -f
        verschiebung[2, 3] = blick0[2, 3] - f[2]
        blick = verschiebung @ np.vstack([np.hstack([blick0[:3, :3], np.zeros((3, 1))]), [0, 0, 0, 1]])
        proj = ortho(self.halbe_breite, 1.0, 900.0).astype(np.float64)
        self.licht_mvp = (proj @ blick).astype(np.float32)
        return self.licht_mvp

    def statisch_beginnen(self) -> tuple:
        """Die ruhende Karte zum Zeichnen binden (Deko, Gelände)."""
        return self._binden(self.statisch_fbo)

    def beginnen(self) -> tuple:
        """Die eigentliche Karte binden, mit dem Inhalt der ruhenden darin.

        Kopiert wird mit einem Durchgang, der die Tiefe schreibt — das
        Blitten eines reinen Tiefenpuffers tut in moderngl nichts.
        """
        vorher = self._binden(self.fbo)
        ctx = self.ctx
        ctx.depth_func = "1"
        self.statisch_textur.use(0)
        self._kopie["quelle"].value = 0
        self._kopie_vao.render(moderngl.TRIANGLES)
        ctx.depth_func = "<"
        return vorher

    def _binden(self, fbo) -> tuple:
        vorher = (self.ctx.fbo, self.ctx.viewport, self.ctx.scissor)
        fbo.use()
        self.ctx.scissor = None
        self.ctx.viewport = (0, 0, self.groesse, self.groesse)
        fbo.clear(depth=1.0)
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        self.ctx.depth_mask = True
        for p in (self.programm, self.programm_instanz):
            shader.matrix_setzen(p, "licht_mvp", self.licht_mvp)
        return vorher

    def beenden(self, vorher) -> None:
        fbo, viewport, scissor = vorher
        if fbo is not None:
            fbo.use()
        self.ctx.viewport = viewport
        self.ctx.scissor = scissor

    def binden(self, einheit: int = 3) -> None:
        self.textur.use(einheit)

    def freigeben(self) -> None:
        for ding in (self.fbo, self.textur, self.statisch_fbo, self.statisch_textur,
                     self._kopie_vao, self._kopie_puffer, self._kopie,
                     self.programm, self.programm_instanz):
            try:
                ding.release()
            except Exception:                        # pragma: no cover - Treiber
                pass


# ---------------------------------------------------------------------------
# Geländeschatten: die Sonnensichtkarte
# ---------------------------------------------------------------------------
#
# Sonne und Gelände stehen fest, also auch die Schatten der Berge. Sie werden
# einmal beim Laden gerechnet, nicht in jedem Bild gezeichnet — und hängen
# damit nicht an den 150 m der Schattenkarte, an deren Rand das Gelände eine
# harte Kante bekam.
#
# **Grenzhöhe statt hell/dunkel.** Je Texel steht die Höhe, ab der ein Punkt
# die Sonne sieht: ``grenze = max über t > 0 von h(p + t·d) − t·tan(α)`` mit
# ``d`` waagerecht zur Sonne und ``α`` ihrer Höhe. Der Boden liegt im Schatten,
# wenn er unter der Grenze liegt; ein Auto auf dem Kamm, ein Baumwipfel, ein
# Dach vergleichen ihre eigene Höhe — wer darüber ragt, steht in der Sonne.
# Dazu der Abstand zum Verdecker: je weiter weg, desto breiter der Halbschatten.
#
# **Im Sonnenraster.** Das Raster ist nach der Sonne gedreht: jede Zeile läuft
# waagerecht auf die Sonne zu. Dann ist die Grenze ein rückwärts laufendes
# Maximum je Zeile (``np.maximum.accumulate``) — eine Handvoll numpy-Aufrufe
# über das ganze Feld, keine Schleife über Schritte. Die Höhen zeichnet die
# Grafikkarte aus dem Geländenetz in dieses Raster, also genau den Boden, den
# man sieht; der Shader rechnet die Weltposition mit zwei Skalarprodukten in
# das Raster um.
#
# **Grob und fein.** Eine ferne Karte deckt das ganze Gelände bis zum
# Horizont ab, eine feine das Gitter um die Strecke. Die feine übernimmt an
# ihrem sonnenseitigen Rand die Grenze der fernen — Berge draußen schatten
# auch auf die Strecke.

#: Texelgröße in Metern je ``grafik.gelaende_schatten``: (fern, nah); nah
#: ``None`` heißt nur die ferne Karte.
SICHT_DETAIL = {1: (12.0, None), 2: (8.0, 3.0), 3: (6.0, 2.0)}
#: Rand um das Gelände (Ringe bis ``gelaende.AUSSEN_M``), Meter.
SICHT_RAND_M = 40.0
#: So viele Texel vor dem Punkt beginnt die Suche nach Verdeckern. Den Hang
#: selbst schattiert schon der Sonnenwinkel; ohne Abstand zeigte er Akne.
SICHT_VERSATZ_TEXEL = 1
#: Weicher Rand: Mindestbreite in Texeln (waagerecht) und Öffnung des
#: Halbschattens (tan), die Breite wächst mit dem Abstand zum Verdecker.
SICHT_RAND_TEXEL = 1.2
SICHT_HALBSCHATTEN = 0.035
#: Wo nichts ist (außerhalb der Ringe): tief genug, um nie zu verdecken.
SICHT_LEER = -1.0e4
#: Textureinheiten der beiden Karten (0–3 Material, Himmel, Schatten; 5 Maske;
#: 8–10 Gelände, 8–11 Nachbearbeitung).
SICHT_EINHEITEN = (12, 13)


def sonnenachse(sonne):
    """``(d, tan_hoehe)``: waagerechte Richtung zur Sonne (normiert) und die
    Steigung ihrer Höhe. ``None``, wenn die Sonne fast senkrecht steht."""
    s = np.asarray(sonne, dtype=np.float64)
    s = s / np.linalg.norm(s)
    waag = float(np.hypot(s[0], s[1]))
    if waag < 1e-3 or s[2] <= 0.0:
        return None
    return s[:2] / waag, float(s[2] / waag)


class Sonnenraster:
    """Ein nach der Sonne gedrehtes Raster: ``u`` waagerecht zur Sonne hin,
    ``v`` quer dazu. Texel ``(i, j)`` liegt bei ``u0 + (i + ½)·texel``,
    ``v0 + (j + ½)·texel``; Felder sind ``(nv, nu)``, eine Zeile je ``v``."""

    def __init__(self, achse, u0: float, v0: float, texel_m: float, nu: int, nv: int) -> None:
        self.achse = np.asarray(achse, dtype=np.float64)
        self.quer = np.array([-self.achse[1], self.achse[0]])
        self.u0, self.v0 = float(u0), float(v0)
        self.texel = float(texel_m)
        self.nu, self.nv = int(nu), int(nv)

    @classmethod
    def um(cls, achse, punkte_xy, texel_m: float) -> "Sonnenraster":
        """Das kleinste Raster, das alle ``punkte_xy`` (Ecken, Kreis) enthält."""
        a = np.asarray(achse, dtype=np.float64)
        q = np.array([-a[1], a[0]])
        p = np.asarray(punkte_xy, dtype=np.float64).reshape(-1, 2)
        u, v = p @ a, p @ q
        nu = int(np.ceil((u.max() - u.min()) / texel_m)) + 1
        nv = int(np.ceil((v.max() - v.min()) / texel_m)) + 1
        return cls(a, u.min(), v.min(), texel_m, nu, nv)

    def uv(self, x, y):
        """Weltkoordinaten in Rasterkoordinaten (Meter, u und v)."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        return x * self.achse[0] + y * self.achse[1], x * self.quer[0] + y * self.quer[1]

    def punkte(self):
        """Weltkoordinaten ``(x, y)`` aller Texelmitten, je ``(nv, nu)``."""
        u = self.u0 + (np.arange(self.nu) + 0.5) * self.texel
        v = self.v0 + (np.arange(self.nv) + 0.5) * self.texel
        uu, vv = np.meshgrid(u, v)
        return (uu * self.achse[0] + vv * self.quer[0], uu * self.achse[1] + vv * self.quer[1])

    def abtasten(self, feld, x, y, leer: float = SICHT_LEER):
        """Bilinear wie die Grafikkarte (Rand festgehalten); außerhalb ``leer``."""
        u, v = self.uv(x, y)
        fu = (u - self.u0) / self.texel - 0.5
        fv = (v - self.v0) / self.texel - 0.5
        drin = (fu > -1.0) & (fv > -1.0) & (fu < self.nu) & (fv < self.nv)
        fu = np.clip(fu, 0.0, self.nu - 1.0)
        fv = np.clip(fv, 0.0, self.nv - 1.0)
        i = np.minimum(np.floor(fu).astype(np.int64), self.nu - 2)
        j = np.minimum(np.floor(fv).astype(np.int64), self.nv - 2)
        a, b = fu - i, fv - j
        f = np.asarray(feld)
        wert = (f[j, i] * (1 - a) * (1 - b) + f[j, i + 1] * a * (1 - b)
                + f[j + 1, i] * (1 - a) * b + f[j + 1, i + 1] * a * b)
        return np.where(drin, wert, leer)

    def ndc_matrix(self) -> np.ndarray:
        """Welt → Bildraum des Rasters; z so, dass der höhere Boden gewinnt."""
        lu, lv = self.nu * self.texel, self.nv * self.texel
        m = np.zeros((4, 4))
        m[0, :2] = 2.0 * self.achse / lu
        m[0, 3] = -2.0 * self.u0 / lu - 1.0
        m[1, :2] = 2.0 * self.quer / lv
        m[1, 3] = -2.0 * self.v0 / lv - 1.0
        m[2, 2] = -1.0 / 4000.0
        m[3, 3] = 1.0
        return m

    def uniform(self) -> tuple:
        """``(u0, v0, 1/Länge u, 1/Länge v)`` für den Shader."""
        return (self.u0, self.v0, 1.0 / (self.nu * self.texel), 1.0 / (self.nv * self.texel))


def sonnensicht(hoehen, texel_m: float, tan_hoehe: float, versatz: int = SICHT_VERSATZ_TEXEL,
                jenseits=None):
    """Grenzhöhe und Abstand zum Verdecker je Texel eines Sonnenrasters.

    ``hoehen`` ist ``(nv, nu)``, Spalte 0 am weitesten von der Sonne weg.
    ``jenseits``: was hinter dem sonnenseitigen Rand liegt, je Zeile
    ``(u_bezug, grenze, abstand)`` — die Grenze an der Stelle ``u_bezug``
    (Meter ab dem Anfang der Zeile), die nur Verdecker hinter dem Rand zählt.

    Liefert ``(grenze, abstand)``, beide ``(nv, nu)`` float32. Ohne Verdecker
    ist die Grenze sehr tief und der Abstand 0.
    """
    h = np.asarray(hoehen, dtype=np.float64)
    nv, nu = h.shape
    u = (np.arange(nu) + 0.5) * texel_m
    abfall = u * tan_hoehe
    w = h - abfall
    # Rückwärts laufendes Maximum, dazu die Spalte, die es setzt.
    r = w[:, ::-1]
    hoechst = np.maximum.accumulate(r, axis=1)
    spalte = np.where(r >= hoechst, np.arange(nu), 0)
    np.maximum.accumulate(spalte, axis=1, out=spalte)
    hoechst = hoechst[:, ::-1]
    spalte = (nu - 1) - spalte[:, ::-1]
    grenze = np.full((nv, nu), SICHT_LEER, dtype=np.float64)
    abstand = np.zeros((nv, nu), dtype=np.float64)
    m = max(1, int(versatz))
    if nu > m:
        grenze[:, :-m] = hoechst[:, m:] + abfall[:-m]
        abstand[:, :-m] = (spalte[:, m:] - np.arange(nu - m)) * texel_m
    if jenseits is not None:
        u_bezug, g_j, a_j = (np.asarray(x, dtype=np.float64).reshape(-1, 1) for x in jenseits)
        von_draussen = g_j + (u[None, :] - u_bezug) * tan_hoehe
        besser = von_draussen > grenze
        grenze = np.where(besser, von_draussen, grenze)
        abstand = np.where(besser, a_j + (u_bezug - u[None, :]), abstand)
    return grenze.astype(np.float32), abstand.astype(np.float32)


def sonnenlicht_gelaende(raster: Sonnenraster, grenze, abstand, x, y, z, tan_hoehe: float):
    """Wie viel Sonne ein Punkt bekommt, 0..1 — dieselbe Rechnung wie im Shader
    (Block "Strang W2" in ``shader.py``); für Tests und Werkzeuge."""
    g = raster.abtasten(grenze, x, y)
    t = raster.abtasten(abstand, x, y, leer=0.0)
    breite = np.maximum(SICHT_RAND_TEXEL * raster.texel * tan_hoehe, t * SICHT_HALBSCHATTEN)
    s = np.clip(0.5 + (np.asarray(z, dtype=np.float64) - g) / breite, 0.0, 1.0)
    return s * s * (3.0 - 2.0 * s)


def sichtkarten_rechnen(hoehen_fuer, sonne, mitte, radius_m: float, nah_rechteck=None,
                        stufe: int = 3):
    """Beide Karten aus einer Höhenquelle. ``hoehen_fuer(raster)`` liefert die
    Höhen ``(nv, nu)`` eines Rasters (Grafikkarte oder numpy).

    ``mitte``/``radius_m``: das ganze Gelände; ``nah_rechteck``:
    ``(x0, y0, x1, y1)`` des feinen Gitters. Liefert eine Liste
    ``[(raster, grenze, abstand), …]`` (fern, dann nah) und die Steigung der
    Sonne — oder ``([], None)`` ohne Geländeschatten.
    """
    achse = sonnenachse(sonne)
    detail = SICHT_DETAIL.get(int(stufe))
    if achse is None or detail is None:
        return [], None
    d, tan_hoehe = achse
    fern_m, nah_m = detail
    w = np.linspace(0.0, 2.0 * np.pi, 64, endpoint=False)
    r = radius_m / np.cos(np.pi / 64)
    kreis = np.stack([mitte[0] + r * np.cos(w), mitte[1] + r * np.sin(w)], axis=1)
    fern = Sonnenraster.um(d, kreis, fern_m)
    g_f, a_f = sonnensicht(hoehen_fuer(fern), fern.texel, tan_hoehe)
    karten = [(fern, g_f, a_f)]
    if nah_m is not None and nah_rechteck is not None:
        x0, y0, x1, y1 = nah_rechteck
        nah = Sonnenraster.um(d, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], nah_m)
        # Hinter dem sonnenseitigen Rand: die ferne Grenze ein paar ferne
        # Texel vor dem Rand — sie zählt genau die Verdecker ab dem Rand.
        v = nah.v0 + (np.arange(nah.nv) + 0.5) * nah.texel
        u_rand = nah.u0 + nah.nu * nah.texel
        u_bezug = u_rand - SICHT_VERSATZ_TEXEL * fern.texel
        bx = u_bezug * d[0] + v * nah.quer[0]
        by = u_bezug * d[1] + v * nah.quer[1]
        jenseits = (np.full(nah.nv, u_bezug - nah.u0), fern.abtasten(g_f, bx, by),
                    fern.abtasten(a_f, bx, by, leer=0.0))
        g_n, a_n = sonnensicht(hoehen_fuer(nah), nah.texel, tan_hoehe, jenseits=jenseits)
        karten.append((nah, g_n, a_n))
    return karten, tan_hoehe


_HOEHE_VERTEX = """
#version 330
uniform mat4 raster;
in vec3 in_position;
out float hoehe;
void main() { hoehe = in_position.z; gl_Position = raster * vec4(in_position, 1.0); }
"""

_HOEHE_FRAGMENT = """
#version 330
in float hoehe;
out vec2 ausgabe;
void main() { ausgabe = vec2(hoehe, 1.0); }
"""


class Gelaendesicht:
    """Die Sonnensichtkarten auf der Grafikkarte: gerechnet beim Laden,
    gebunden in jedem Bild, gelesen im Block "Strang W2" des Shaders."""

    def __init__(self, ctx, gelaendezeichner, gel, sonne, stufe: int) -> None:
        from . import gelaende
        self.ctx = ctx
        self.texturen = []
        self.karten = []
        self.tan_hoehe = None
        self.achse = None
        if int(stufe) <= 0 or gelaendezeichner is None:
            return
        programm = ctx.program(vertex_shader=_HOEHE_VERTEX, fragment_shader=_HOEHE_FRAGMENT)
        vao = None
        # Ohne gebundenes Ziel (Kontext ohne Fenster) das Standardziel merken.
        vorher = (ctx.fbo or ctx.detect_framebuffer(), ctx.viewport, ctx.scissor)
        try:
            vao = gelaendezeichner.hoehen_vao(programm)

            def hoehen_fuer(raster):
                return self._hoehen_zeichnen(programm, vao, raster)

            xs, ys, _z = gel._gitter_bauen()
            karten, tan_hoehe = sichtkarten_rechnen(
                hoehen_fuer, sonne, gel.mitte, gelaende.AUSSEN_M + SICHT_RAND_M,
                (float(xs[0]), float(ys[0]), float(xs[-1]), float(ys[-1])), stufe)
        finally:
            fbo_alt, viewport, scissor = vorher
            fbo_alt.use()
            ctx.viewport = viewport
            ctx.scissor = scissor
            for ding in (vao, programm):
                if ding is not None:
                    ding.release()
        if not karten:
            return
        self.tan_hoehe = tan_hoehe
        self.achse = tuple(float(c) for c in karten[0][0].achse)
        for raster, grenze, abstand in karten:
            daten = np.ascontiguousarray(np.stack([grenze, abstand], axis=-1), dtype="f4")
            t = ctx.texture((raster.nu, raster.nv), 2, daten.tobytes(), dtype="f4")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = False
            t.repeat_y = False
            self.texturen.append(t)
            self.karten.append(raster)

    def _hoehen_zeichnen(self, programm, vao, raster: Sonnenraster) -> np.ndarray:
        ctx = self.ctx
        farbe = ctx.texture((raster.nu, raster.nv), 2, dtype="f4")
        tiefe = ctx.depth_renderbuffer((raster.nu, raster.nv))
        fbo = ctx.framebuffer(color_attachments=[farbe], depth_attachment=tiefe)
        try:
            fbo.use()
            ctx.scissor = None
            ctx.viewport = (0, 0, raster.nu, raster.nv)
            fbo.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
            ctx.enable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.BLEND)
            ctx.depth_func = "<"
            shader.matrix_setzen(programm, "raster", raster.ndc_matrix())
            vao.render()
            roh = np.frombuffer(fbo.read(components=2, dtype="f4"), dtype=np.float32)
        finally:
            for ding in (fbo, farbe, tiefe):
                ding.release()
        roh = roh.reshape(raster.nv, raster.nu, 2)
        return np.where(roh[..., 1] > 0.5, roh[..., 0], SICHT_LEER)

    def setzen(self, programme, an: bool = True) -> None:
        """Uniforms setzen und die Karten binden; ``an=False`` schaltet ab."""
        aktiv = an and bool(self.karten)
        for p in programme:
            shader.setzen(p, "sicht_an", float(len(self.karten)) if aktiv else 0.0)
            if not aktiv:
                continue
            shader.setzen(p, "sicht_achse", self.achse)
            for k, (name, einheit) in enumerate(zip(("sicht_fern", "sicht_nah"), SICHT_EINHEITEN)):
                raster = self.karten[min(k, len(self.karten) - 1)]
                shader.setzen(p, name, einheit)
                shader.setzen(p, f"{name}_raster", tuple(float(c) for c in raster.uniform()))
            shader.setzen(p, "sicht_weich", (
                float(SICHT_RAND_TEXEL * self.karten[0].texel * self.tan_hoehe),
                float(SICHT_RAND_TEXEL * self.karten[-1].texel * self.tan_hoehe),
                float(SICHT_HALBSCHATTEN)))
        if aktiv:
            for k, einheit in enumerate(SICHT_EINHEITEN):
                self.texturen[min(k, len(self.texturen) - 1)].use(einheit)

    def freigeben(self) -> None:
        for t in self.texturen:
            try:
                t.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self.texturen = []
        self.karten = []
