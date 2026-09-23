"""Ein Fahrzeug einzeln, für die Werkstatt und die Fahrzeugauswahl.

Rendert in ein eigenes Bild außerhalb des Fensters und gibt die Pixel zurück;
wer sie als pygame-Fläche braucht, macht daraus eine (siehe
``src/states/menu/werkstatt_page.py``). So muss das Menü nichts von OpenGL
wissen, und die Werkstatt zeigt genau das Modell und genau die Lackierung,
die später auf der Strecke fährt.

Gerendert wird nur, wenn sich etwas ändert — Fahrzeug, Lackierung, Winkel
oder Größe. Die Werkstatt dreht das Auto auf Knopfdruck, nicht fortlaufend;
ein Bild je Klick genügt.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from . import camera, matrix, schatten, shader
from .rennszene import Lackwerte, Modellspeicher, fahrzeugteile_zeichnen

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Kantenglättung der Vorschau. Das Menü zeigt das Auto groß und still — da
#: fallen Treppen an der Silhouette sofort auf.
PROBEN = 4


class Fahrzeugvorschau:
    def __init__(self, ctx, modellordner: str | Path, himmelordner: str | Path | None = None,
                 himmel: str = "City") -> None:
        from . import licht
        self.ctx = ctx
        self.programm = shader.programm(ctx)
        self.himmel = licht.Himmel(ctx, himmelordner or ".", himmel)
        self.schattenwerfer = schatten.Schattenwerfer(ctx)
        self.speicher = Modellspeicher(ctx, self.programm, modellordner,
                                       schattenprogramm=self.schattenwerfer.programm)
        self._leere_tiefe = ctx.depth_texture((1, 1))
        self._leere_tiefe.compare_func = "<="
        p = self.programm
        shader.setzen(p, "sonne_richtung", (0.45, 0.35, 0.82))
        shader.setzen(p, "hat_himmel", 1.0 if self.himmel.textur is not None else 0.0)
        shader.setzen(p, "himmel_mips", max(1.0, self.himmel.mips - 1.0))
        shader.setzen(p, "nebel_dichte", 0.0)
        shader.setzen(p, "boden_farbe", (0.08, 0.09, 0.11))
        self._groesse = None
        self._fbo = self._fbo_aufloesen = None
        self._letzter = None
        self._pixel = None

    def _puffer(self, groesse) -> None:
        if self._groesse == groesse:
            return
        for ding in (self._fbo, self._fbo_aufloesen):
            if ding is not None:
                ding.release()
        b, h = groesse
        self._fbo = self.ctx.framebuffer(
            color_attachments=[self.ctx.renderbuffer((b, h), 4, samples=PROBEN)],
            depth_attachment=self.ctx.depth_renderbuffer((b, h), samples=PROBEN))
        self._fbo_aufloesen = self.ctx.framebuffer(
            color_attachments=[self.ctx.renderbuffer((b, h), 4)])
        self._groesse = groesse

    def bild(self, schluessel: str, lack: Lackwerte | None, gier_grad: float,
             groesse: tuple[int, int]) -> tuple[bytes, tuple[int, int]] | None:
        """RGBA-Pixel von oben nach unten, oder ``None`` ohne Modell."""
        groesse = (max(8, int(groesse[0])), max(8, int(groesse[1])))
        schluessel_bild = (schluessel, repr(lack), round(gier_grad, 2), groesse)
        if schluessel_bild == self._letzter and self._pixel is not None:
            return self._pixel, groesse
        fm = self.speicher.holen(schluessel)
        if fm is None:
            return None
        self._puffer(groesse)

        ctx = self.ctx
        vorher = (ctx.fbo, ctx.viewport, ctx.scissor)
        try:
            self._fbo.use()
            ctx.scissor = None
            ctx.viewport = (0, 0, *groesse)
            ctx.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)

            laenge = fm.teile.laenge_m if fm.teile else 4.5
            ziel = np.array([0.0, 0.0, 0.55])
            abstand = laenge * 1.05 + 0.9
            hoehe = np.radians(17.0)
            seite = np.radians(-38.0)
            auge = ziel + abstand * np.array([np.cos(hoehe) * np.cos(seite),
                                              np.cos(hoehe) * np.sin(seite), np.sin(hoehe)])
            mvp = camera.perspektive(30.0, groesse[0] / groesse[1], 0.1, 100.0) \
                @ camera.blick(auge, ziel)

            p = self.programm
            shader.matrix_setzen(p, "mvp", mvp)
            shader.setzen(p, "kamera_position", tuple(float(w) for w in auge))
            shader.setzen(p, "hat_schatten", 0.0)
            shader.setzen(p, "entfaerbung", 0.0)
            shader.setzen(p, "deckkraft", 1.0)
            shader.setzen(p, "uv_skala", 1.0)
            self.himmel.binden(2)
            self._leere_tiefe.use(3)

            gier = np.radians(gier_grad)
            knoten = fm.knoten()
            if knoten is not None:
                matrizen = knoten.matrizen((0.0, 0.0, 0.0), gier)
            else:
                grund = matrix.fahrzeug((0.0, 0.0, 0.0), gier)
                matrizen = {t.name: grund @ matrix.verschiebung(t.versatz) for t in fm.modell.teile}

            # Kontaktschatten: das Auto steht, statt zu schweben. Getrennte
            # Mischung für Alpha, damit der Fleck im durchsichtigen Bild als
            # Schatten ankommt und nicht als Loch.
            if fm.schatten_vao is not None:
                self.schattenwerfer.beginnen(mvp)
                ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                                  moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
                self.schattenwerfer.zeichnen(fm.schatten_vao, matrix.fahrzeug((0, 0, 0), gier))
                self.schattenwerfer.beenden()

            ctx.enable(moderngl.DEPTH_TEST)
            ctx.disable(moderngl.BLEND)
            fahrzeugteile_zeichnen(p, fm.modell, matrizen, lack, False)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                              moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
            ctx.depth_mask = False
            fahrzeugteile_zeichnen(p, fm.modell, matrizen, lack, True)
            ctx.depth_mask = True
            ctx.disable(moderngl.BLEND)

            ctx.copy_framebuffer(self._fbo_aufloesen, self._fbo)
            roh = self._fbo_aufloesen.read(components=4, alignment=1)
        finally:
            fbo, viewport, scissor = vorher
            if fbo is not None:
                fbo.use()
            ctx.viewport = viewport
            ctx.scissor = scissor
        # framebuffer.read() liefert Zeilen von unten nach oben.
        zeilen = np.frombuffer(roh, dtype=np.uint8).reshape(groesse[1], groesse[0], 4)[::-1]
        self._pixel = np.ascontiguousarray(zeilen).tobytes()
        self._letzter = schluessel_bild
        return self._pixel, groesse

    def freigeben(self) -> None:
        self.speicher.freigeben()
        for ding in (self._fbo, self._fbo_aufloesen, self._leere_tiefe, self.programm):
            if ding is not None:
                try:
                    ding.release()
                except Exception:                    # pragma: no cover - Treiber
                    pass
        self.himmel.freigeben()
        self.schattenwerfer.freigeben()
