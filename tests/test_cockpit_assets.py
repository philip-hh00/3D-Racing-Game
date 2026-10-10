"""Cockpit-Knoten in den Fahrzeug-GLBs (Vertrag: ``src/render3d/VEREINBARUNGEN.md``).

Liest jede gebaute ``assets/vehicles/<key>.glb`` samt ``<key>_teile.json`` und prüft
Knoten, Lage und den Block ``cockpit``. Die GLBs sind nicht im Repository; fehlt
eine, wird das Auto übersprungen.
"""
import json
import struct
from pathlib import Path

import numpy as np
import pytest

ORDNER = Path(__file__).resolve().parents[1] / "assets" / "vehicles"
ALLE = ["rookie", "rookie_2", "rookie_3", "limousine", "limousine_2", "limousine_3",
        "supercar", "supercar_2", "supercar_3", "drifter", "drifter_2", "drifter_3",
        "electric", "electric_2", "electric_3"]
KNOTEN = ["augpunkt", "lenkrad", "nadel_tacho", "nadel_drehzahl",
          "spiegel_innen", "spiegel_l", "spiegel_r"]


def _gltf(pfad: Path) -> dict:
    roh = pfad.read_bytes()
    laenge = struct.unpack("<I", roh[12:16])[0]
    return json.loads(roh[20:20 + laenge])


def _uv(pfad: Path, kopf: dict, index: int) -> np.ndarray:
    """TEXCOORD-Accessor (VEC2, float) aus dem BIN-Block."""
    roh = pfad.read_bytes()
    kl = struct.unpack("<I", roh[12:16])[0]
    binaer = roh[20 + kl + 8:]
    acc = kopf["accessors"][index]
    bv = kopf["bufferViews"][acc["bufferView"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    schritt = bv.get("byteStride", 8)
    n = acc["count"]
    roh_uv = np.frombuffer(binaer, dtype=np.uint8, count=(n - 1) * schritt + 8, offset=start)
    return np.array([np.frombuffer(roh_uv[i * schritt:i * schritt + 8], dtype="<f4") for i in range(n)])


def _knoten(kopf: dict) -> dict:
    return {k.get("name"): k for k in kopf["nodes"]}


def _achse_x(kn: dict) -> np.ndarray:
    """Lokale X-Achse eines Knotens in Fahrzeugkoordinaten."""
    x, y, z, w = kn.get("rotation", [0, 0, 0, 1])
    return np.array([1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)])


def _lade(key):
    glb, teile = ORDNER / f"{key}.glb", ORDNER / f"{key}_teile.json"
    if not glb.exists() or not teile.exists():
        pytest.skip(f"{key}.glb nicht gebaut")
    with open(teile, encoding="utf-8") as fh:
        t = json.load(fh)
    kopf = _gltf(glb)
    if "augpunkt" not in _knoten(kopf):
        pytest.skip(f"{key}.glb ohne Cockpit (alter Bau)")
    return kopf, t


@pytest.mark.parametrize("key", ALLE)
def test_cockpit_knoten_und_lage(key):
    kopf, t = _lade(key)
    kn = _knoten(kopf)
    for name in KNOTEN:
        assert name in kn, name
    L, B, H = t["laenge_m"], t["breite_m"], t["hoehe_m"]
    c = t["cockpit"]
    auge = np.array(c["augpunkt"])
    assert np.allclose(auge, kn["augpunkt"]["translation"], atol=1e-3)
    # Augpunkt: links (Linksverkehr-Lenker), in der Kabine, unter dem Dach
    assert 0.2 < auge[1] < 0.6 * B / 2 + 0.2
    assert abs(auge[0]) < L / 2 * 0.6
    assert 0.6 * H < auge[2] < H - 0.05
    ort = {n: np.array(kn[n]["translation"]) for n in KNOTEN}
    for name in ("lenkrad", "nadel_tacho", "nadel_drehzahl"):
        o = ort[name]
        # vor dem Auge, 0,3 bis 0,9 m entfernt, innerhalb der Kabine
        assert 0.3 < np.linalg.norm(o - auge) < 0.9, name
        assert o[0] > auge[0], name
        assert abs(o[1]) < B / 2 * 0.8 and 0.3 < o[2] < H, name
    # Tacho rechts von der Drehzahl, beide etwa gleich hoch
    assert ort["nadel_tacho"][1] < ort["nadel_drehzahl"][1]
    assert abs(ort["nadel_tacho"][2] - ort["nadel_drehzahl"][2]) < 0.02
    # Lenkrad: lokale X-Achse = Säule, zeigt zum Fahrer (nach hinten, leicht nach oben)
    ax = _achse_x(kn["lenkrad"])
    assert ax[0] < -0.8 and 0.1 < ax[2] < 0.6
    # Nadeln: lokale X-Achse zeigt vom Fahrer weg ins Instrument
    for name in ("nadel_tacho", "nadel_drehzahl"):
        assert _achse_x(kn[name])[0] > 0.8, name
    # Spiegel: Innenspiegel mittig oben, Außenspiegel links/rechts außen
    assert abs(ort["spiegel_innen"][1]) < 0.15 and ort["spiegel_innen"][2] > auge[2] - 0.05
    assert ort["spiegel_l"][1] > B / 2 * 0.7 and ort["spiegel_r"][1] < -B / 2 * 0.7


@pytest.mark.parametrize("key", ALLE)
def test_kombiinstrument_sitzt_hinter_dem_lenkrad_im_armaturenbrett(key):
    """Das Lenkrad steht vor den Zifferblättern; sie flankieren die Nabe und liegen so tief,
    dass nichts über das Armaturenbrett in die Scheibe ragt (Kranzoberkante liegt rund 8 cm
    vor dem Lenkradursprung, die Zifferblattebene dahinter)."""
    kopf, t = _lade(key)
    kn = _knoten(kopf)
    ort = {n: np.array(kn[n]["translation"]) for n in ("lenkrad", "nadel_tacho", "nadel_drehzahl")}
    auge = np.array(t["cockpit"]["augpunkt"])
    for name in ("nadel_tacho", "nadel_drehzahl"):
        assert ort[name][0] - ort["lenkrad"][0] >= 0.09, f"{name} liegt nicht hinter dem Kranz"
        assert ort[name][2] <= ort["lenkrad"][2] + 0.14, f"{name} sitzt zu hoch über der Nabe"
        assert ort[name][2] > ort["lenkrad"][2] - 0.02
        # Die Sicht über das Armaturenbrett: das Zifferblatt liegt deutlich unter Augenhöhe.
        assert auge[2] - ort[name][2] > 0.18, name
    # die Nabe steht in der Mitte zwischen beiden
    assert abs((ort["nadel_tacho"][1] + ort["nadel_drehzahl"][1]) / 2 - ort["lenkrad"][1]) < 0.005
    assert 0.07 < ort["nadel_drehzahl"][1] - ort["lenkrad"][1] < 0.12


@pytest.mark.parametrize("key", ALLE)
def test_spiegel_sitzen_im_blickfeld_des_fahrers(key):
    """Innenspiegel mittig; linker Außenspiegel nicht weiter als 45 Grad seitlich und nicht
    steil darunter (sonst liegt er am Bildrand hinter der A-Säule)."""
    import math
    kopf, t = _lade(key)
    kn = _knoten(kopf)
    auge = np.array(t["cockpit"]["augpunkt"])
    assert abs(kn["spiegel_innen"]["translation"][1]) < 0.02
    d = np.array(kn["spiegel_l"]["translation"]) - auge
    azimut = math.degrees(math.atan2(d[1], d[0]))
    hoehe = math.degrees(math.atan2(d[2], math.hypot(d[0], d[1])))
    assert 20 < azimut <= 45, azimut
    assert -20 < hoehe < -3, hoehe


@pytest.mark.parametrize("key", ALLE)
def test_cockpit_block_vollstaendig(key):
    _kopf, t = _lade(key)
    c = t["cockpit"]
    for k in ("augpunkt", "haube", "lenkrad_uebersetzung", "tacho_max_kmh", "tacho_winkel_grad",
              "drehzahl_max", "drehzahl_winkel_grad"):
        assert k in c, k
    assert len(c["augpunkt"]) == 3 and len(c["haube"]) == 3
    # Haube: auf der Mittellinie, vor dem Auge, über dem Boden
    assert c["haube"][1] == 0 and c["haube"][0] > c["augpunkt"][0] and c["haube"][2] > 0.5
    assert 12 <= c["lenkrad_uebersetzung"] <= 15
    assert c["tacho_max_kmh"] >= 150 and c["tacho_max_kmh"] % 20 == 0
    assert c["drehzahl_max"] >= 5000 and c["drehzahl_max"] % 1000 == 0
    assert c["tacho_winkel_grad"] == [-135, 135] and c["drehzahl_winkel_grad"] == [-135, 135]


@pytest.mark.parametrize("key", ALLE)
def test_spiegelglas_material_und_uv(key):
    kopf, _t = _lade(key)
    kn = _knoten(kopf)
    mat_namen = [m["name"] for m in kopf["materials"]]
    for name in ("spiegel_innen", "spiegel_l", "spiegel_r"):
        netz = kopf["meshes"][kn[name]["mesh"]]
        for prim in netz["primitives"]:
            assert mat_namen[prim["material"]] == "spiegel", name
            uv = _uv(ORDNER / f"{key}.glb", kopf, prim["attributes"]["TEXCOORD_0"])
            assert uv.min() >= -1e-4 and uv.max() <= 1 + 1e-4, name
            assert (uv.max(axis=0) - uv.min(axis=0)).min() > 0.9, name


@pytest.mark.parametrize("key", ALLE)
def test_lod1_ohne_cockpitknoten(key):
    lod = ORDNER / f"{key}_lod1.glb"
    if not lod.exists():
        pytest.skip("kein LOD1")
    kn = _knoten(_gltf(lod))
    for name in KNOTEN:
        assert name not in kn, name
