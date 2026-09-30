"""Fahrbahn und Gelände erben keine Karten vom zuletzt gezeichneten Auto (30.09.2026).

Gemeldet: „das komische Muster der Straße und der Fahrbahnbegrenzung … scheint
ein Grafikbug zu sein, da manchmal wieder die Originalgrafik angezeigt wird."

Uniforms bleiben im Programm stehen. Die Autos schalten Normal-, Leucht- und
Verdeckungskarte ein; die Fahrbahn setzte sie nie zurück und las, wenn kurz
davor ein Auto gezeichnet worden war, dessen Räder-Atlas als Verdeckung —
Kreise und Zahnkränze auf dem Asphalt. Nah-nach-fern-Reihenfolge je Bild:
deshalb nur manchmal.
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.render3d import shader


class _Uniform:
    def __init__(self):
        self.value = None


class _Programm(dict):
    def __missing__(self, name):
        u = _Uniform()
        self[name] = u
        return u


def _nach_auto():
    p = _Programm()
    for name in ("hat_normalkarte", "hat_emissionskarte", "hat_verdeckung", "klarlack"):
        shader.setzen(p, name, 1.0)
    shader.setzen(p, "lack_effekt", (0.6, 0.4, 0.0))
    return p


def _aus(p):
    return all(p[name].value == wert for name, wert in shader.MODELL_SCHALTER)


def test_die_fahrbahn_schaltet_die_karten_des_autos_ab():
    from src.render3d.rennszene import _Flaeche, Rennszene
    p = _nach_auto()
    szene = types.SimpleNamespace(programm=p, thema=None,
                                  netz=types.SimpleNamespace(halbe_breite_m=6.0, laenge_m=1000.0))
    Rennszene._flaeche_setzen(szene, _Flaeche(vao=None, farbe=(0.3, 0.3, 0.3)))
    assert _aus(p)


def test_das_gelaende_schaltet_die_karten_des_autos_ab():
    import inspect
    from src.render3d import gelaende
    # Jede Zeichenfunktion des Geländes, die Materialwerte setzt, schaltet zuerst ab.
    quelle = inspect.getsource(gelaende)
    bloecke = quelle.split("def zeichnen(self")[1:]
    assert bloecke
    for block in bloecke:
        kopf = block.split("\n    def ")[0]
        if "hat_basisfarbe" in kopf:
            assert kopf.index("modell_schalter_aus") < kopf.index("hat_basisfarbe")
