"""Strang L: Lack-Block im Shader (Flakes, Orangenhaut, Scheiben)."""
from __future__ import annotations

from src.core import lack
from src.render3d import rennszene, shader


def test_uni_werkslack_glitzert_nicht():
    assert rennszene.lack_effekt("lack", 0.0, None) == (0.0, 1.0, 0.0)


def test_metallic_werkslack_hat_flakes():
    flakes, orangenhaut, glas = rennszene.lack_effekt("lack", 0.55, None)
    assert flakes == 1.0 and orangenhaut == 1.0 and glas == 0.0


def test_werkstatt_metallic_ersetzt_den_werkslack():
    werte = lack.werte_3d("metallic:rubinrot")
    assert rennszene.lack_effekt("lack", 0.0, werte)[0] == 1.0
    uni = lack.werte_3d("standard:rubinrot")
    assert rennszene.lack_effekt("lack", 0.6, uni)[0] == 0.0


def test_lack2_ohne_zweitfarbe_behaelt_sein_werksmetallic():
    werte = lack.werte_3d("metallic:rubinrot")
    assert werte.zweitfarbe is None
    assert rennszene.lack_effekt("lack2", 0.0, werte)[0] == 0.0
    assert rennszene.lack_effekt("lack2", 0.5, werte)[0] == 1.0


def test_scheiben_und_andere_materialien():
    assert rennszene.lack_effekt("glas", 0.0, None) == (0.0, 0.0, 1.0)
    assert rennszene.lack_effekt("klarglas", 0.0, None) == (0.0, 0.0, 0.0)
    assert rennszene.lack_effekt("chrom", 1.0, None) == (0.0, 0.0, 0.0)


def test_shader_kennt_den_lackblock():
    assert "uniform vec3 lack_effekt;" in shader.FRAGMENT
    assert "Strang L" in shader.FRAGMENT
