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
