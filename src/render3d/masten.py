"""Flutlichtmasten an der Strecke, nachts gezeichnet.

Wo ein Thema keine Laternen hat, bekommt die Nacht Masten (Standorte:
:func:`tageszeit.mast_orte`). Gezeichnet werden zwei instanzierte Netze mit
dem Instanz-Programm der Szene: der Mast (dunkles Metall) und die leuchtende
Fläche des Lampenkopfes. Das Licht selbst kommt aus der Lichterliste des
Shaders, nicht von hier.
"""
from __future__ import annotations

import numpy as np

from . import shader, tageszeit
from .deko import instanzmatrizen

try:                                             # pragma: no cover - Importpfad
    import moderngl
except ImportError:                              # pragma: no cover
    moderngl = None

#: Nur Masten in diesem Umkreis um die Kamera werden gezeichnet, Meter.
SICHT_M = 420.0
#: Farbe des Mastes (sRGB) und Emission des Kopfes (linear).
MAST_FARBE = (0.2, 0.21, 0.22)
KOPF_EMISSION = (1.0, 0.82, 0.52)


class Mastzeichner:
    def __init__(self, ctx, programm_instanz, orte: np.ndarray, hoehen=None) -> None:
        self.ctx = ctx
        self.programm = programm_instanz
        orte = np.asarray(orte, dtype=np.float64).reshape(-1, 3)
        self.orte = orte
        n = len(orte)
        pos = np.zeros((n, 3), dtype=np.float32)
        pos[:, :2] = orte[:, :2]
        if hoehen is not None:
            pos[:, 2] = np.asarray(hoehen, dtype=np.float32)
        self.matrizen = instanzmatrizen(pos, orte[:, 2].astype(np.float32), np.ones(n, np.float32))
        self.xy = np.ascontiguousarray(orte[:, :2], dtype=np.float32)
        self._puffer: list = []
        self._vaos: dict = {}
        self._instanzen = ctx.buffer(reserve=max(1, n) * 64, dynamic=True)
        self._puffer.append(self._instanzen)
        for name, (p, nor, idx) in tageszeit.mast_netz().items():
            vp = ctx.buffer(np.ascontiguousarray(p, "f4").tobytes())
            vn = ctx.buffer(np.ascontiguousarray(nor, "f4").tobytes())
            vu = ctx.buffer(np.zeros((len(p), 2), dtype="f4").tobytes())
            ib = ctx.buffer(np.ascontiguousarray(idx, "u4").tobytes())
            self._puffer += [vp, vn, vu, ib]
            self._vaos[name] = ctx.vertex_array(
                programm_instanz,
                [(vp, "3f", "in_position"), (vn, "3f", "in_normale"), (vu, "2f", "in_uv"),
                 (self._instanzen, "4f 4f 4f 4f/i", "in_inst0", "in_inst1", "in_inst2", "in_inst3")],
                ib)

    def zeichnen(self, kamera_position) -> None:
        if len(self.orte) == 0:
            return
        auge = np.asarray(kamera_position, dtype=np.float32)[:2]
        d2 = ((self.xy - auge) ** 2).sum(axis=1)
        auswahl = d2 < SICHT_M * SICHT_M
        k = int(auswahl.sum())
        if k == 0:
            return
        self._instanzen.write(np.ascontiguousarray(self.matrizen[auswahl]).tobytes())
        p = self.programm
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.BLEND)
        shader.modell_schalter_aus(p)
        for name, wert in (("hat_basisfarbe", 0.0), ("hat_metallic_rauheit", 0.0),
                           ("alpha_faktor", 1.0), ("alpha_schwelle", 0.0), ("klarlack", 0.0),
                           ("uv_skala", 1.0), ("farbton", (1.0, 1.0, 1.0)), ("makro", 0.0),
                           ("nebel_faktor", 1.0), ("lod_band", (0.0, 0.0, 0.0)),
                           ("entfaerbung", 0.0), ("deckkraft", 1.0)):
            shader.setzen(p, name, wert)
        shader.setzen(p, "grundton", MAST_FARBE)
        shader.setzen(p, "metallic_faktor", 0.6)
        shader.setzen(p, "rauheit_faktor", 0.55)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))
        self._vaos["mast"].render(instances=k)
        shader.setzen(p, "grundton", (0.9, 0.9, 0.85))
        shader.setzen(p, "metallic_faktor", 0.0)
        shader.setzen(p, "rauheit_faktor", 0.4)
        helle = tageszeit.NACHT.lampen_leuchten
        shader.setzen(p, "emission", tuple(c * helle for c in KOPF_EMISSION))
        self._vaos["kopf"].render(instances=k)
        shader.setzen(p, "emission", (0.0, 0.0, 0.0))

    def freigeben(self) -> None:
        for v in self._vaos.values():
            v.release()
        for b in self._puffer:
            try:
                b.release()
            except Exception:                        # pragma: no cover - Treiber
                pass
        self._vaos = {}
        self._puffer = []
