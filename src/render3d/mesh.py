"""GLB-Lader für Fahrzeuge und Umgebungsobjekte.

Zwei getrennte Schichten:

* :func:`laden` liest eine GLB-**Szene** mit benannten Knoten und liefert
  reine Zahlen — kein OpenGL, ohne Kontext testbar.
* :func:`hochladen` gibt diese Zahlen an einen vorhandenen ModernGL-Kontext
  und liefert ein fertiges :class:`Modell`.

**Mehrere Materialien je Teil.** Die Modelle kommen aus Blender
(``tools/blender/``) und tragen je Knoten mehrere glTF-Primitive: Lack, Glas,
Chrom, Gummi, Licht. Jedes Primitive ist ein :class:`Stueck` mit eigenem
Material; gezeichnet wird Stück für Stück.

**Gelesen wird die GLB-Datei direkt**, nicht über trimesh: trimesh zerlegt
einen Knoten mit mehreren Primitiven in Geschwisterknoten mit zufälligen
Namensendungen, und der Name des Knotens ist hier Vertrag (``karosserie``,
``rad_vl``, ``sattel_vl``). Das Format ist schlicht genug — JSON-Kopf plus ein
Binärblock — und der eigene Leser ist obendrein schneller.

**Texturkoordinaten.** glTF legt ``v = 0`` an die *Oberkante* des Bildes.
Beim Laden wird auf OpenGL-Konvention gedreht (``v = 1 - v``: ``v = 0`` ist
die Unterkante), und beim Hochladen wird das Bild einmal gespiegelt — genau
wie in ``VEREINBARUNGEN.md`` beschrieben.
"""
from __future__ import annotations

import io
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageOps

if TYPE_CHECKING:
    import moderngl

_KOMPONENTEN = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_TYPEN = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16,
          5125: np.uint32, 5126: np.float32}


# ---------------------------------------------------------------------------
# Daten
# ---------------------------------------------------------------------------

@dataclass
class Material:
    """Ein PBR-Material, so wie der Shader es braucht.

    ``farbe`` ist **sRGB** (0..1), wie ``grundton`` im Shader — glTF speichert
    den Faktor linear, umgerechnet wird beim Laden.
    """

    name: str = ""
    farbe: tuple[float, float, float] = (1.0, 1.0, 1.0)
    alpha: float = 1.0
    metallic: float = 0.0
    rauheit: float = 1.0
    emission: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: ``"OPAQUE"``, ``"MASK"`` (Laub: ausstanzen) oder ``"BLEND"`` (Glas).
    modus: str = "OPAQUE"
    schwelle: float = 0.5
    beidseitig: bool = False
    basisfarbe: "Image.Image | None" = None
    metallic_rauheit: "Image.Image | None" = None

    @property
    def durchsichtig(self) -> bool:
        return self.modus == "BLEND"


@dataclass
class Stueck:
    """Ein glTF-Primitive: ein Material, ein Dreiecksnetz."""

    material: int
    positionen: np.ndarray    # (n, 3) float32, Meter, lokal
    normalen: np.ndarray      # (n, 3) float32, normiert
    uv: np.ndarray            # (n, 2) float32, OpenGL-Konvention
    indizes: np.ndarray       # (m, 3) uint32


@dataclass
class Teilnetz:
    """Ein benannter Knoten — Karosserie, Rad, Sattel oder ein ganzes Objekt."""

    name: str
    stuecke: list[Stueck]
    versatz: np.ndarray       # (3,) float32 — Position des Knotens in der Szene

    @property
    def dreiecke(self) -> int:
        return sum(len(s.indizes) for s in self.stuecke)

    # Alle Stücke als ein Netz — für Prüfungen und Werkzeuge, die das
    # Material nicht interessiert.
    @property
    def positionen(self) -> np.ndarray:
        if not self.stuecke:
            return np.zeros((0, 3), np.float32)
        return np.concatenate([s.positionen for s in self.stuecke])

    @property
    def normalen(self) -> np.ndarray:
        if not self.stuecke:
            return np.zeros((0, 3), np.float32)
        return np.concatenate([s.normalen for s in self.stuecke])

    @property
    def uv(self) -> np.ndarray:
        if not self.stuecke:
            return np.zeros((0, 2), np.float32)
        return np.concatenate([s.uv for s in self.stuecke])

    @property
    def indizes(self) -> np.ndarray:
        teile, basis = [], 0
        for s in self.stuecke:
            teile.append(s.indizes + np.uint32(basis))
            basis += len(s.positionen)
        if not teile:
            return np.zeros((0, 3), np.uint32)
        return np.concatenate(teile).astype(np.uint32)

    def grenzen(self) -> tuple[np.ndarray, np.ndarray]:
        """Kleinste und größte Ecke, lokal."""
        alle = np.concatenate([s.positionen for s in self.stuecke]) if self.stuecke \
            else np.zeros((1, 3), np.float32)
        return alle.min(axis=0), alle.max(axis=0)


@dataclass
class Modelldaten:
    """Ergebnis von :func:`laden` — reine Daten, kein OpenGL."""

    teile: list[Teilnetz]
    materialien: list[Material]

    def teil(self, name: str) -> "Teilnetz | None":
        for t in self.teile:
            if t.name == name:
                return t
        return None

    @property
    def basisfarbe(self) -> "Image.Image | None":
        """Die erste Basisfarbtextur irgendeines Materials."""
        return next((m.basisfarbe for m in self.materialien if m.basisfarbe is not None), None)

    @property
    def metallic_rauheit(self) -> "Image.Image | None":
        return next((m.metallic_rauheit for m in self.materialien
                     if m.metallic_rauheit is not None), None)

    def material(self, name: str) -> "Material | None":
        for m in self.materialien:
            if m.name == name:
                return m
        return None

    def grenzen(self) -> tuple[np.ndarray, np.ndarray]:
        """Umhüllender Quader aller Teile in Szenenkoordinaten."""
        mins, maxs = [], []
        for t in self.teile:
            a, b = t.grenzen()
            mins.append(a + t.versatz)
            maxs.append(b + t.versatz)
        return np.min(mins, axis=0), np.max(maxs, axis=0)


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

def _linear_nach_srgb(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _glb_zerlegen(roh: bytes) -> tuple[dict, bytes]:
    magie, _version, _laenge = struct.unpack_from("<4sII", roh, 0)
    if magie != b"glTF":
        raise ValueError("keine GLB-Datei")
    pos = 12
    kopf, binaer = None, b""
    while pos < len(roh):
        laenge, art = struct.unpack_from("<I4s", roh, pos)
        inhalt = roh[pos + 8: pos + 8 + laenge]
        if art == b"JSON":
            kopf = json.loads(inhalt.decode("utf-8"))
        elif art == b"BIN\x00":
            binaer = inhalt
        pos += 8 + laenge
    if kopf is None:
        raise ValueError("GLB ohne JSON-Kopf")
    return kopf, binaer


class _Leser:
    def __init__(self, kopf: dict, binaer: bytes) -> None:
        self.k = kopf
        self.bin = binaer
        self._bilder: dict[int, Image.Image] = {}

    def accessor(self, index: int) -> np.ndarray:
        acc = self.k["accessors"][index]
        n = _KOMPONENTEN[acc["type"]]
        typ = np.dtype(_TYPEN[acc["componentType"]])
        anzahl = acc["count"]
        if "bufferView" not in acc:
            return np.zeros((anzahl, n), dtype=typ)
        ansicht = self.k["bufferViews"][acc["bufferView"]]
        start = ansicht.get("byteOffset", 0) + acc.get("byteOffset", 0)
        schritt = ansicht.get("byteStride", 0) or typ.itemsize * n
        if schritt == typ.itemsize * n:
            daten = np.frombuffer(self.bin, dtype=typ, count=anzahl * n, offset=start)
            daten = daten.reshape(anzahl, n)
        else:
            roh = np.frombuffer(self.bin, dtype=np.uint8,
                                count=schritt * (anzahl - 1) + typ.itemsize * n, offset=start)
            daten = np.lib.stride_tricks.as_strided(
                roh.view(typ), shape=(anzahl, n),
                strides=(schritt, typ.itemsize)).copy()
        if acc.get("normalized") and typ.kind in "iu":
            daten = daten.astype(np.float32) / float(np.iinfo(typ).max)
        return np.array(daten)

    def bild(self, textur_index: int) -> "Image.Image | None":
        try:
            quelle = self.k["textures"][textur_index]["source"]
        except (KeyError, IndexError):
            return None
        if quelle in self._bilder:
            return self._bilder[quelle]
        info = self.k["images"][quelle]
        if "bufferView" not in info:
            return None
        ansicht = self.k["bufferViews"][info["bufferView"]]
        start = ansicht.get("byteOffset", 0)
        roh = self.bin[start: start + ansicht["byteLength"]]
        bild = Image.open(io.BytesIO(roh))
        bild.load()
        self._bilder[quelle] = bild
        return bild

    def material(self, m: dict) -> Material:
        pbr = m.get("pbrMetallicRoughness", {})
        faktor = pbr.get("baseColorFactor", [1, 1, 1, 1])
        emission = m.get("emissiveFactor", [0, 0, 0])
        staerke = m.get("extensions", {}).get(
            "KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
        mat = Material(
            name=m.get("name", ""),
            farbe=tuple(_linear_nach_srgb(c) for c in faktor[:3]),
            alpha=float(faktor[3]),
            metallic=float(pbr.get("metallicFactor", 1.0)),
            rauheit=float(pbr.get("roughnessFactor", 1.0)),
            emission=tuple(float(c) * float(staerke) for c in emission),
            modus=m.get("alphaMode", "OPAQUE"),
            schwelle=float(m.get("alphaCutoff", 0.5)),
            beidseitig=bool(m.get("doubleSided", False)),
        )
        # Laub aus tools/blender/umgebung_bauen.py: der Name sagt "ausstanzen",
        # gleich wie der Export den Alphamodus nennt.
        if mat.name.endswith("_maske"):
            mat.modus = "MASK"
            mat.schwelle = 0.45
        if "baseColorTexture" in pbr:
            mat.basisfarbe = self.bild(pbr["baseColorTexture"]["index"])
        if "metallicRoughnessTexture" in pbr:
            mat.metallic_rauheit = self.bild(pbr["metallicRoughnessTexture"]["index"])
        return mat


def _knotenmatrix(knoten: dict) -> np.ndarray:
    if "matrix" in knoten:
        return np.asarray(knoten["matrix"], dtype=np.float64).reshape(4, 4).T
    t = np.asarray(knoten.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = knoten.get("rotation", [0, 0, 0, 1])
    s = np.asarray(knoten.get("scale", [1, 1, 1]), dtype=np.float64)
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


def _normalen_berechnen(pos: np.ndarray, idx: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos, dtype=np.float64)
    a, b, c = pos[idx[:, 0]], pos[idx[:, 1]], pos[idx[:, 2]]
    fn = np.cross(b - a, c - a)
    for k in range(3):
        np.add.at(n, idx[:, k], fn)
    laenge = np.linalg.norm(n, axis=1, keepdims=True)
    laenge[laenge == 0] = 1.0
    return (n / laenge).astype(np.float32)


def laden(pfad: str | Path) -> Modelldaten:
    """GLB-Szene einlesen.

    Jeder Knoten mit Netz wird ein :class:`Teilnetz`. Drehung und Skalierung
    des Knotens werden in die Punkte gerechnet, die Verschiebung bleibt als
    ``versatz`` stehen — die Räder brauchen ihren lokalen Ursprung in der Nabe.
    """
    kopf, binaer = _glb_zerlegen(Path(pfad).read_bytes())
    leser = _Leser(kopf, binaer)
    materialien = [leser.material(m) for m in kopf.get("materials", [])]
    if not materialien:
        materialien = [Material(name="standard", rauheit=0.8)]

    knoten_liste = kopf.get("nodes", [])
    eltern = {}
    for i, kn in enumerate(knoten_liste):
        for kind in kn.get("children", []):
            eltern[kind] = i

    def welt(i: int) -> np.ndarray:
        m = _knotenmatrix(knoten_liste[i])
        while i in eltern:
            i = eltern[i]
            m = _knotenmatrix(knoten_liste[i]) @ m
        return m

    teile: list[Teilnetz] = []
    for i, kn in enumerate(knoten_liste):
        if "mesh" not in kn:
            continue
        m = welt(i)
        dreh = m[:3, :3]
        normal_m = np.linalg.inv(dreh).T
        stuecke = []
        for prim in kopf["meshes"][kn["mesh"]]["primitives"]:
            if prim.get("mode", 4) != 4:
                continue
            attr = prim["attributes"]
            pos = leser.accessor(attr["POSITION"]).astype(np.float64)
            if "indices" in prim:
                idx = leser.accessor(prim["indices"]).reshape(-1, 3).astype(np.uint32)
            else:
                idx = np.arange(len(pos), dtype=np.uint32).reshape(-1, 3)
            if "NORMAL" in attr:
                nor = leser.accessor(attr["NORMAL"]).astype(np.float64)
            else:
                nor = _normalen_berechnen(pos, idx).astype(np.float64)
            if "TEXCOORD_0" in attr:
                uv = leser.accessor(attr["TEXCOORD_0"]).astype(np.float32).copy()
                uv[:, 1] = 1.0 - uv[:, 1]
            else:
                uv = np.zeros((len(pos), 2), dtype=np.float32)
            pos = pos @ dreh.T
            nor = nor @ normal_m.T
            laenge = np.linalg.norm(nor, axis=1, keepdims=True)
            laenge[laenge == 0] = 1.0
            nor = nor / laenge
            if np.linalg.det(dreh) < 0:
                idx = idx[:, ::-1].copy()
            stuecke.append(Stueck(
                material=int(prim.get("material", 0)) if "material" in prim else 0,
                positionen=pos.astype(np.float32),
                normalen=nor.astype(np.float32),
                uv=uv, indizes=np.ascontiguousarray(idx, dtype=np.uint32)))
        teile.append(Teilnetz(name=kn.get("name", f"knoten_{i}"), stuecke=stuecke,
                              versatz=m[:3, 3].astype(np.float32)))
    return Modelldaten(teile=teile, materialien=materialien)


# ---------------------------------------------------------------------------
# Hochladen
# ---------------------------------------------------------------------------

@dataclass
class HochgeladenesStueck:
    vao: "moderngl.VertexArray"
    material: int


@dataclass
class HochgeladenesTeil:
    """Ein Teilnetz, an OpenGL übergeben."""

    name: str
    stuecke: list[HochgeladenesStueck]
    versatz: np.ndarray


@dataclass
class HochgeladenesMaterial:
    daten: Material
    basisfarbe: "moderngl.Texture | None" = None
    metallic_rauheit: "moderngl.Texture | None" = None


@dataclass
class Modell:
    """Ergebnis von :func:`hochladen` — bereit zum Zeichnen."""

    teile: list[HochgeladenesTeil]
    materialien: list[HochgeladenesMaterial]
    puffer: list = field(default_factory=list)

    def teil(self, name: str) -> "HochgeladenesTeil | None":
        for t in self.teile:
            if t.name == name:
                return t
        return None

    def material_index(self, name: str) -> int:
        for i, m in enumerate(self.materialien):
            if m.daten.name == name:
                return i
        return -1

    def freigeben(self) -> None:
        for t in self.teile:
            for s in t.stuecke:
                s.vao.release()
        for m in self.materialien:
            for tex in (m.basisfarbe, m.metallic_rauheit):
                if tex is not None:
                    tex.release()
        for p in self.puffer:
            p.release()
        self.teile, self.materialien, self.puffer = [], [], []


def textur_hochladen(ctx: "moderngl.Context", bild: "Image.Image | None",
                     wiederholen: bool = True):
    """Ein PIL-Bild als ModernGL-Textur hochladen, mit Mipmaps.

    Einmal vertikal spiegeln: die UV sind in OpenGL-Konvention (``v = 0``
    unten), PIL-Zeile 0 ist aber die Oberkante (siehe VEREINBARUNGEN.md).
    """
    if bild is None:
        return None
    rgba = bild.convert("RGBA")
    gespiegelt = ImageOps.flip(rgba)
    textur = ctx.texture(gespiegelt.size, 4, gespiegelt.tobytes())
    textur.build_mipmaps()
    textur.repeat_x = wiederholen
    textur.repeat_y = wiederholen
    try:
        textur.anisotropy = 8.0
    except Exception:                                # pragma: no cover - Treiber
        pass
    return textur


#: Früherer Name, von Werkzeugen noch benutzt.
_textur_hochladen = textur_hochladen


def stueck_hochladen(ctx, programm, stueck: Stueck, puffer: list):
    vbo_p = ctx.buffer(np.ascontiguousarray(stueck.positionen, dtype=np.float32).tobytes())
    vbo_n = ctx.buffer(np.ascontiguousarray(stueck.normalen, dtype=np.float32).tobytes())
    vbo_u = ctx.buffer(np.ascontiguousarray(stueck.uv, dtype=np.float32).tobytes())
    ibo = ctx.buffer(np.ascontiguousarray(stueck.indizes, dtype=np.uint32).tobytes())
    puffer += [vbo_p, vbo_n, vbo_u, ibo]
    return ctx.vertex_array(programm, [
        (vbo_p, "3f", "in_position"),
        (vbo_n, "3f", "in_normale"),
        (vbo_u, "2f", "in_uv"),
    ], ibo)


def materialien_hochladen(ctx, materialien: list[Material]) -> list[HochgeladenesMaterial]:
    return [HochgeladenesMaterial(daten=m,
                                  basisfarbe=textur_hochladen(ctx, m.basisfarbe),
                                  metallic_rauheit=textur_hochladen(ctx, m.metallic_rauheit))
            for m in materialien]


def hochladen(ctx: "moderngl.Context", programm: "moderngl.Program",
              daten: Modelldaten) -> Modell:
    """Puffer und Texturen an OpenGL geben — eine VAO je Stück."""
    puffer: list = []
    teile = [HochgeladenesTeil(
        name=t.name,
        stuecke=[HochgeladenesStueck(vao=stueck_hochladen(ctx, programm, s, puffer),
                                     material=s.material) for s in t.stuecke],
        versatz=t.versatz.copy()) for t in daten.teile]
    return Modell(teile=teile, materialien=materialien_hochladen(ctx, daten.materialien),
                  puffer=puffer)
