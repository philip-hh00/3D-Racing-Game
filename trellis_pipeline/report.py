"""Abnahmebericht: was ist da, und stimmt es mit der Vorgabe ueberein.

Der Bericht bricht nichts ab. Ein zu breites Modell ist immer noch besser als
gar keines, und ob 6 Prozent Abweichung stoeren, entscheidet der Blick auf das
Fahrzeug - nicht das Skript. Gemeldet wird es aber, und zwar deutlich: ein still
durchgelassener Fehler taucht sonst erst im Spiel wieder auf.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import trimesh

from .vehicle_specs import Fahrzeugmasse

#: Ab welcher relativen Abweichung vom Sollmass gewarnt wird.
TOLERANZ = 0.05


@dataclass
class Bericht:
    dreiecke: int
    ist_laenge_m: float
    ist_breite_m: float
    ist_hoehe_m: float
    soll: Fahrzeugmasse
    typ: str
    texturgroesse: tuple[int, int] | None = None
    pbr_kanaele: list[str] = field(default_factory=list)
    #: Massabweichungen ueber der Toleranz - das, wonach das Skript gefragt wird.
    warnungen: list[str] = field(default_factory=list)
    #: Alles andere, was auffaellt. Getrennt gehalten, damit "Masse stimmen"
    #: eine beantwortbare Frage bleibt: eine fehlende Textur ist ein Mangel,
    #: aber keine Aussage ueber die Geometrie.
    hinweise: list[str] = field(default_factory=list)

    def text(self) -> str:
        zeilen = [
            f"Fahrzeug        {self.soll.key}  ({self.typ})",
            f"Dreiecke        {self.dreiecke:,}".replace(",", "."),
            f"Textur          {self._textur_text()}",
            f"PBR-Kanaele     {', '.join(self.pbr_kanaele) or 'keine'}",
        ]
        if self.typ == "rad":
            zeilen.append(
                f"Durchmesser     ist {self.ist_laenge_m:.3f} m   "
                f"soll {self.soll.rad_m:.3f} m")
            zeilen.append(f"Breite          ist {self.ist_breite_m:.3f} m")
        else:
            zeilen.append(
                f"Laenge          ist {self.ist_laenge_m:.2f} m   "
                f"soll {self.soll.laenge_m:.2f} m")
            zeilen.append(
                f"Breite          ist {self.ist_breite_m:.2f} m   "
                f"soll {self.soll.breite_m:.2f} m")
            zeilen.append(f"Hoehe           ist {self.ist_hoehe_m:.2f} m")
        for w in self.warnungen:
            zeilen.append(f"WARNUNG         {w}")
        if not self.warnungen:
            zeilen.append("Alle Masse im Soll.")
        for h in self.hinweise:
            zeilen.append(f"HINWEIS         {h}")
        return "\n".join(zeilen)

    def _textur_text(self) -> str:
        if self.texturgroesse is None:
            return "keine gefunden"
        return f"{self.texturgroesse[0]} x {self.texturgroesse[1]} px"


def _abweichung(ist: float, soll: float) -> float:
    return abs(ist - soll) / soll if soll > 0 else 0.0


def _textur_und_kanaele(mesh: trimesh.Trimesh):
    """Texturgroesse und vorhandene PBR-Kanaele aus dem Material lesen.

    TRELLIS 2 liefert echte PBR-Materialien statt eingebackener Beleuchtung -
    genau deswegen ist es hier die richtige Wahl. Ob die Kanaele wirklich
    ankommen, sagt aber erst das geladene Modell.
    """
    material = getattr(getattr(mesh, "visual", None), "material", None)
    if material is None:
        return None, []
    kanaele: list[str] = []
    groesse = None
    for feld, name in (("baseColorTexture", "base_color"),
                       ("metallicRoughnessTexture", "metallic_roughness"),
                       ("normalTexture", "normal"),
                       ("emissiveTexture", "emissive"),
                       ("occlusionTexture", "occlusion"),
                       ("image", "base_color")):
        bild = getattr(material, feld, None)
        if bild is None:
            continue
        if name not in kanaele:
            kanaele.append(name)
        if groesse is None and hasattr(bild, "size"):
            groesse = tuple(bild.size)
    # Opacity steckt im Alphakanal der Base Color, nicht in einer eigenen Textur.
    haupt = getattr(material, "baseColorTexture", None) or getattr(material, "image", None)
    if haupt is not None and getattr(haupt, "mode", "") in ("RGBA", "LA", "PA"):
        alpha = np.asarray(haupt.convert("RGBA"))[..., 3]
        if alpha.min() < 255:
            kanaele.append("opacity")
    return groesse, kanaele


def pruefen(mesh: trimesh.Trimesh, soll: Fahrzeugmasse, typ: str) -> Bericht:
    """Ist-Masse gegen Soll pruefen und alles Wissenswerte einsammeln."""
    ext = [float(v) for v in mesh.bounding_box.extents]
    groesse, kanaele = _textur_und_kanaele(mesh)
    bericht = Bericht(
        dreiecke=int(len(mesh.faces)),
        ist_laenge_m=ext[0], ist_breite_m=ext[1], ist_hoehe_m=ext[2],
        soll=soll, typ=typ, texturgroesse=groesse, pbr_kanaele=kanaele)

    if typ == "rad":
        pruefungen = [("Durchmesser", ext[0], soll.rad_m),
                      ("Durchmesser (Hochachse)", ext[2], soll.rad_m)]
    else:
        pruefungen = [("Laenge", ext[0], soll.laenge_m),
                      ("Breite", ext[1], soll.breite_m)]

    for name, ist, sollwert in pruefungen:
        ab = _abweichung(ist, sollwert)
        if ab > TOLERANZ:
            bericht.warnungen.append(
                f"{name} weicht {ab * 100:.1f} % ab: "
                f"ist {ist:.3f} m, soll {sollwert:.3f} m")

    if typ != "rad" and not kanaele:
        bericht.hinweise.append(
            "Keine Textur im Modell - ohne Base Color gibt es keine Lackmaske")
    return bericht
