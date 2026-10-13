"""Was der Fahrer aus dem Augpunkt sieht — geprüft mit Strahlen gegen die Karosserie im GLB.

Gemeldet am 10.10.2026 nach Durchsicht der Cockpitbilder aller 15 Wagen:

* der Bildschirm der Mittelkonsole stand **auf** dem Armaturenbrett, vor der Frontscheibe;
* Zierleisten und Konsolenblende in Wagenfarbe (rookie_2 rot, supercar_3 gelb) quer durchs
  Armaturenbrett — wie Karosserieblech, das in die Kabine ragt;
* limousine_3: Loch im Dachhimmel unter dem Schiebedach (Himmel sichtbar);
* der Dachhimmel füllte rund 40 % des Bildes.

Die GLBs sind nicht im Repository; fehlt eine, wird das Auto übersprungen. Fahrzeugsystem:
+X vorn, +Y links, +Z oben; Blickrichtung des Fahrers +X (wie die Cockpitkamera).
"""
import json
import math
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

ORDNER = Path(__file__).resolve().parents[1] / "assets" / "vehicles"
ALLE = ["rookie", "rookie_2", "rookie_3", "limousine", "limousine_2", "limousine_3",
        "supercar", "supercar_2", "supercar_3", "drifter", "drifter_2", "drifter_3",
        "electric", "electric_2", "electric_3"]
KAROSSERIEFARBEN = ("lack", "lack2")
#: Das Sichtfeld der Cockpitkamera reicht 32 Grad nach oben und unten.
DACHKANTE_MIN_GRAD = 8.0
KOPFFREIHEIT_MIN_M = 0.08

_KOMPONENTE = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_ANZAHL = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _gltf(pfad: Path):
    roh = pfad.read_bytes()
    kl = struct.unpack("<I", roh[12:16])[0]
    return json.loads(roh[20:20 + kl]), roh[20 + kl + 8:]


def _accessor(kopf, binaer, index):
    acc = kopf["accessors"][index]
    bv = kopf["bufferViews"][acc["bufferView"]]
    typ = _KOMPONENTE[acc["componentType"]]
    n = _ANZAHL[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    schritt = bv.get("byteStride") or n * np.dtype(typ).itemsize
    roh = np.frombuffer(binaer, dtype=np.uint8, offset=start, count=(acc["count"] - 1) * schritt + n * np.dtype(typ).itemsize)
    zeilen = np.lib.stride_tricks.as_strided(roh, shape=(acc["count"], n * np.dtype(typ).itemsize), strides=(schritt, 1))
    return np.ascontiguousarray(zeilen).view(typ).reshape(acc["count"], n)


class Modell:
    """Dreiecke der Karosserie mit Materialname je Dreieck, dazu das Auge."""

    def __init__(self, key: str) -> None:
        pfad = ORDNER / f"{key}.glb"
        if not pfad.exists():
            pytest.skip(f"{key}.glb nicht gebaut")
        kopf, binaer = _gltf(pfad)
        knoten = {k.get("name"): k for k in kopf["nodes"]}
        if "augpunkt" not in knoten:
            pytest.skip(f"{key}.glb ohne Cockpit (alter Bau)")
        self.auge = np.array(knoten["augpunkt"]["translation"], dtype=float)
        netz = kopf["meshes"][knoten["karosserie"]["mesh"]]
        tris, namen = [], []
        self.punkte = {}
        for prim in netz["primitives"]:
            mat = kopf["materials"][prim["material"]]["name"]
            pos = _accessor(kopf, binaer, prim["attributes"]["POSITION"]).astype(float)
            idx = _accessor(kopf, binaer, prim["indices"]).reshape(-1, 3)
            tris.append(pos[idx])
            namen += [mat] * len(idx)
            self.punkte.setdefault(mat, []).append(pos)
        self.tris = np.concatenate(tris)
        self.mat = np.array(namen)
        with open(ORDNER / f"{key}_teile.json", encoding="utf-8") as fh:
            self.teile = json.load(fh)

    def strahl(self, start, richtung, ohne=()):
        """Erster Treffer ab ``start``: (Material, Punkt, Entfernung) oder None."""
        d = np.asarray(richtung, dtype=float)
        d = d / np.linalg.norm(d)
        a, b, c = self.tris[:, 0], self.tris[:, 1], self.tris[:, 2]
        e1, e2 = b - a, c - a
        p = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, p)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = np.asarray(start, dtype=float) - a
        u = np.einsum("ij,ij->i", s, p) * inv
        q = np.cross(s, e1)
        v = (q @ d) * inv
        t = np.einsum("ij,ij->i", e2, q) * inv
        treffer = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-6)
        if ohne:
            treffer &= ~np.isin(self.mat, ohne)
        if not treffer.any():
            return None
        t_hit = np.where(treffer, t, np.inf)
        i = int(np.argmin(t_hit))
        return self.mat[i], np.asarray(start, dtype=float) + d * t_hit[i], float(t_hit[i])

    def blick(self, elevation_grad, azimut_grad):
        el, az = math.radians(elevation_grad), math.radians(azimut_grad)
        return np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])


def _kombi_x(m: Modell) -> float:
    """X der Zifferblätter (= Rückwand des Armaturenbretts)."""
    return float(np.concatenate(m.punkte["instr_tacho"])[:, 0].mean())


@lru_cache(maxsize=None)
def _modell(key: str) -> Modell:
    return Modell(key)


@pytest.mark.parametrize("key", ALLE)
def test_bildschirm_steht_im_armaturenbrett_nicht_vor_der_scheibe(key):
    """Hinter der Oberkante des Bildschirms liegt, vom Auge aus, das Armaturenbrett — nie die
    Frontscheibe oder freier Himmel. Steht die Anzeige über der Armaturenlinie, sieht man
    hinter ihrer Kante durch die Scheibe."""
    m = _modell(key)
    pts = np.concatenate(m.punkte["anzeige"])
    # die Anzeige der Mittelkonsole: Punkte nahe der Mittellinie (die Zifferblätter sind eigene Materialien)
    pts = pts[np.abs(pts[:, 1]) < 0.3]
    assert len(pts) > 8, "keine Anzeige in der Mitte"
    oben = pts[pts[:, 2] > pts[:, 2].max() - 0.004]
    assert len(oben) >= 4
    for punkt in oben[:: max(1, len(oben) // 12)]:
        richtung = punkt - m.auge
        treffer = m.strahl(punkt + richtung / np.linalg.norm(richtung) * 0.004, richtung, ohne=("anzeige",))
        assert treffer is not None, f"{key}: hinter der Anzeigekante ist nichts (Himmel)"
        assert treffer[0] not in ("glas",), f"{key}: Bildschirm verdeckt die Frontscheibe ({treffer[0]})"
    # und: seine Oberkante liegt unter der Armaturenoberkante, also tiefer als die höchste
    # Fläche des Armaturenbretts vor ihm
    a = np.array([pts[:, 0].mean() + 0.1, 0.0, 0.0])
    senkrecht = m.strahl(np.array([a[0], 0.0, 2.0]), (0, 0, -1), ohne=("glas",))
    assert senkrecht is not None
    assert pts[:, 2].max() < senkrecht[1][2] - 0.005, f"{key}: Bildschirm ragt über das Armaturenbrett"


@pytest.mark.parametrize("key", ALLE)
def test_im_armaturenbrett_keine_karosseriefarbe(key):
    """Aus dem Auge sieht man im Innenraum nur Innenraummaterial: keine Wagenfarbe quer durchs
    Armaturenbrett, an der Tür oder an der Konsole (Blick durch die Scheibe auf Haube und
    Straße zählt nicht)."""
    m = _modell(key)
    # Armaturenbrett und Konsole: hinter der Vorderkante des Armaturenbretts (die Zifferblätter
    # sitzen 40 cm hinter ihr) und innerhalb von 75 cm Querabstand (Türoberkante und Haube
    # zählen nicht).
    x_vorn = _kombi_x(m) + 0.40
    falsch = []
    for el in range(-34, -1, 3):
        for az in range(-44, 45, 4):
            r = m.blick(el, az)
            start, durch_glas = m.auge, False
            for _ in range(6):
                t = m.strahl(start, r)
                if t is None:
                    break
                if t[0] == "glas":
                    durch_glas = True
                    start = t[1] + r * 1e-3
                    continue
                if (not durch_glas and t[1][0] < x_vorn and abs(t[1][1]) < 0.75
                        and t[0] in KAROSSERIEFARBEN):
                    falsch.append((el, az, t[0], tuple(np.round(t[1], 2))))
                break
    assert not falsch, f"{key}: Karosseriefarbe im Innenraum bei (el, az, mat, pos): {falsch[:4]}"


@pytest.mark.parametrize("key", ALLE)
def test_dachhimmel_ist_geschlossen(key):
    """Nach oben (Dach, Schiebedach) trifft der Blick immer den Dachhimmel — kein Loch, kein
    Himmel, kein Glas — und die Kopffreiheit beträgt mindestens 8 cm."""
    m = _modell(key)
    loecher = []
    for el in range(50, 91, 8):
        for az in range(-60, 61, 12):
            t = m.strahl(m.auge, m.blick(el, az))
            if t is None or t[0] in ("glas", *KAROSSERIEFARBEN):
                loecher.append((el, az, None if t is None else t[0]))
    assert not loecher, f"{key}: Loch im Dachhimmel bei (el, az, mat): {loecher[:5]}"
    oben = m.strahl(m.auge, (0, 0, 1))
    assert oben is not None and oben[2] >= KOPFFREIHEIT_MIN_M, f"{key}: Kopffreiheit {oben}"


@pytest.mark.parametrize("key", ALLE)
def test_dachkante_der_frontscheibe_liegt_nicht_zu_tief(key):
    """Der Dachhimmel soll nicht die oberen 40 % des Bildes füllen: die Oberkante der Scheibe
    liegt, vom Auge aus, mindestens ``DACHKANTE_MIN_GRAD`` über dem Horizont."""
    m = _modell(key)
    kante = None
    for zehntel in range(0, 600, 5):
        el = zehntel / 10
        t = m.strahl(m.auge, m.blick(el, 0.0))
        if t is not None and t[0] != "glas":
            kante = el
            break
    assert kante is not None
    assert kante >= DACHKANTE_MIN_GRAD, f"{key}: Dachkante nur {kante} Grad über dem Horizont"
