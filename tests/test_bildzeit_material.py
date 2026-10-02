"""Materialwechsel ohne Umweg: ``deko.material_setzen`` und ``shader.setzen_viele``.

Beim Zeichnen der Deko wird je Stück ein Material gesetzt (rund 90-mal je
Bild, je Material ein Dutzend Uniforms). Die Werte je Material werden einmal
gerechnet und gemerkt; gesetzt wird, was sich gegenüber dem Programm geändert
hat. Das Ergebnis muss dasselbe sein wie vorher.
"""
import random
from types import SimpleNamespace

from src.render3d import deko, mesh, shader


class _Uniform:
    def __init__(self, protokoll, name):
        self._p, self._n = protokoll, name

    @property
    def value(self):
        return None

    @value.setter
    def value(self, wert):
        self._p.append((self._n, wert))


class _Programm:
    """Wie ein moderngl-Programm: Zuweisung an ``p[name].value``."""

    def __init__(self, fehlend=()):
        self.geschrieben = []
        self._fehlend = set(fehlend)

    def __getitem__(self, name):
        if name in self._fehlend:
            raise KeyError(name)
        return _Uniform(self.geschrieben, name)


class _Textur:
    def __init__(self, name):
        self.name = name

    def use(self, einheit):
        _Textur.gebunden[einheit] = self.name


_Textur.gebunden = {}


def _referenz_material_setzen(p, hm):
    """Die Fassung vor der Optimierung, Wort für Wort."""
    m = hm.daten
    shader.setzen(p, "hat_basisfarbe", 1.0 if hm.basisfarbe is not None else 0.0)
    shader.setzen(p, "hat_metallic_rauheit", 1.0 if hm.metallic_rauheit is not None else 0.0)
    shader.setzen(p, "grundton", tuple(m.farbe))
    shader.setzen(p, "metallic_faktor", float(m.metallic))
    shader.setzen(p, "rauheit_faktor", float(m.rauheit))
    shader.setzen(p, "emission", tuple(m.emission))
    shader.setzen(p, "alpha_faktor", 1.0 if m.modus != "BLEND" else float(m.alpha))
    shader.setzen(p, "alpha_schwelle", float(m.schwelle) if m.modus == "MASK" else 0.0)
    shader.setzen(p, "klarlack", 0.0)
    if hm.basisfarbe is not None:
        hm.basisfarbe.use(0)
    if hm.metallic_rauheit is not None:
        hm.metallic_rauheit.use(1)
    normal = getattr(hm, "normalkarte", None)
    leucht = getattr(hm, "emissionskarte", None)
    ao = getattr(hm, "verdeckung", None)
    shader.setzen(p, "hat_normalkarte", 1.0 if normal is not None else 0.0)
    shader.setzen(p, "hat_emissionskarte", 1.0 if leucht is not None else 0.0)
    shader.setzen(p, "hat_verdeckung", 1.0 if ao is not None else 0.0)
    if normal is not None:
        shader.setzen(p, "normal_staerke", float(m.normal_staerke))
        normal.use(6)
    if leucht is not None:
        leucht.use(7)
    if ao is not None:
        ao.use(4)


def _material(zufall, i):
    daten = mesh.Material(
        name=f"m{i}",
        farbe=(zufall.random(), zufall.random(), zufall.random()),
        alpha=zufall.choice([1.0, 0.5]),
        metallic=zufall.choice([0.0, 1.0, 0.3]),
        rauheit=zufall.choice([0.2, 0.8]),
        emission=zufall.choice([(0.0, 0.0, 0.0), (1.0, 0.5, 0.0)]),
        modus=zufall.choice(["OPAQUE", "MASK", "BLEND"]),
        schwelle=zufall.choice([0.3, 0.5]),
        normal_staerke=zufall.choice([1.0, 0.5]),
    )
    tex = lambda n: _Textur(f"{n}{i}") if zufall.random() < 0.5 else None  # noqa: E731
    return mesh.HochgeladenesMaterial(
        daten, basisfarbe=tex("b"), metallic_rauheit=tex("mr"),
        normalkarte=tex("n"), emissionskarte=tex("e"), verdeckung=tex("ao"))


def test_material_setzen_schreibt_dasselbe_wie_die_alte_fassung():
    zufall = random.Random(7)
    materialien = [_material(zufall, i) for i in range(6)]
    alt, neu = _Programm(), _Programm()
    for _ in range(200):
        hm = zufall.choice(materialien)
        _Textur.gebunden.clear()
        _referenz_material_setzen(alt, hm)
        gebunden_alt = dict(_Textur.gebunden)
        _Textur.gebunden.clear()
        deko.material_setzen(neu, hm)
        assert dict(_Textur.gebunden) == gebunden_alt
        # Zwischendurch stellt anderer Code Uniforms um, etwa der Lack.
        if zufall.random() < 0.3:
            shader.setzen(alt, "klarlack", 1.0)
            shader.setzen(neu, "klarlack", 1.0)
    assert neu.geschrieben == alt.geschrieben
    assert neu._zuletzt == alt._zuletzt


def test_unbekannte_uniforms_werden_uebergangen():
    zufall = random.Random(3)
    hm = _material(zufall, 0)
    p = _Programm(fehlend=("emission", "klarlack"))
    deko.material_setzen(p, hm)
    assert all(n not in ("emission", "klarlack") for n, _ in p.geschrieben)
    assert p._zuletzt["emission"] == tuple(hm.daten.emission)


def test_gemerkte_werte_folgen_einem_ausgetauschten_material():
    zufall = random.Random(5)
    hm = _material(zufall, 1)
    p = _Programm()
    deko.material_setzen(p, hm)
    hm.daten = mesh.Material(name="neu", farbe=(0.1, 0.2, 0.3), metallic=0.9)
    deko.material_setzen(p, hm)
    assert p._zuletzt["grundton"] == (0.1, 0.2, 0.3)
    assert p._zuletzt["metallic_faktor"] == 0.9


def test_setzen_viele_ueberspringt_unveraendertes():
    p = _Programm()
    shader.setzen_viele(p, (("a", 1.0), ("b", (1.0, 2.0))))
    shader.setzen_viele(p, (("a", 1.0), ("b", (1.0, 3.0))))
    assert p.geschrieben == [("a", 1.0), ("b", (1.0, 2.0)), ("b", (1.0, 3.0))]


def test_setzen_viele_und_setzen_teilen_den_merkzettel():
    p = _Programm()
    shader.setzen(p, "a", 2.0)
    shader.setzen_viele(p, (("a", 2.0),))
    assert p.geschrieben == [("a", 2.0)]


def test_schnellweg_faellt_bei_geaenderter_moderngl_schnittstelle_auf_value_zurueck():
    geschrieben = []

    class Ctx:
        def _write_uniform(self, *a):
            raise TypeError("neue Signatur")

    class U:
        array_length, dimension, fmt = 1, 1, "f"
        ctx = Ctx()
        program_obj, location, gl_type, element_size = 0, 0, 0, 4

        @property
        def value(self):
            return None

        @value.setter
        def value(self, w):
            geschrieben.append(w)

    class P(dict):
        def __getitem__(self, k):
            return U()

    p = P()
    shader.setzen(p, "x", 1.5)
    shader.setzen(p, "x", 2.5)
    assert geschrieben == [1.5, 2.5]
