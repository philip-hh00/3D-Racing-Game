"""Himmel für das Spiel: HDRI → Panorama-JPG plus Sonnenrichtung.

Aufruf::

    blender.exe -b -P tools/blender/himmel_bauen.py

Liest die HDRIs aus ``rohdaten/cc0/himmel/`` (siehe ``tools/assets_laden.py``)
und schreibt je Thema ``assets/himmel/<Thema>.jpg`` und ``<Thema>.json``.

Das Spiel liest kein HDR — pygame und PIL können es nicht, und ein
Gleitkommabild von 2048×1024 kostete 25 MB je Thema. Stattdessen wird hier
belichtet: so skaliert, dass der helle Himmel knapp unter Weiß liegt, und als
sRGB gespeichert. Die Sonne selbst wird dabei abgeschnitten; ihre Richtung
geht in die JSON-Datei und von dort in Licht und Schattenwurf. So fällt der
Schatten dahin, wo im Himmel die Sonne steht.

Blender liest HDR nativ, deshalb läuft dieses Skript dort und nicht im Spiel.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gemeinsam as g  # noqa: E402

ROH = g.WURZEL / "rohdaten" / "cc0" / "himmel"
ZIEL = g.WURZEL / "assets" / "himmel"


def umwandeln(thema: str, asset: str) -> None:
    quelle = ROH / f"{asset}.hdr"
    bild = bpy.data.images.load(str(quelle))
    b, h = bild.size
    pixel = np.empty(b * h * 4, dtype=np.float32)
    bild.pixels.foreach_get(pixel)
    # Blender legt Zeile 0 unten ab; das Panorama will oben den Zenit.
    rgb = pixel.reshape(h, b, 4)[::-1, :, :3].astype(np.float64)
    helligkeit = rgb @ np.array([0.2126, 0.7152, 0.0722])

    # Sonne: der hellste Punkt der oberen Hälfte.
    oben = helligkeit[: h // 2]
    zeile, spalte = np.unravel_index(np.argmax(oben), oben.shape)
    hoehe_rad = (0.5 - (zeile + 0.5) / h) * math.pi
    u = (spalte + 0.5) / b
    azimut = (u - 0.5) * 2 * math.pi
    sonne = [math.cos(azimut) * math.cos(hoehe_rad),
             math.sin(azimut) * math.cos(hoehe_rad), math.sin(hoehe_rad)]
    # Unter 18 Grad wird der Schatten unendlich lang und das Bild dunkel;
    # die Richtung bleibt, die Höhe wird angehoben.
    if hoehe_rad < math.radians(28):
        hoehe_rad = math.radians(28)
        sonne = [math.cos(azimut) * math.cos(hoehe_rad),
                 math.sin(azimut) * math.cos(hoehe_rad), math.sin(hoehe_rad)]

    # Belichtung: das 97. Perzentil des Himmels ohne Sonnenumgebung auf 0,9.
    himmel = helligkeit[: h // 2]
    grenze = np.percentile(himmel, 99.5)
    wert = np.percentile(himmel[himmel < grenze], 97)
    skala = 0.9 / max(wert, 1e-6)
    ldr = np.clip(rgb * skala, 0.0, 1.0) ** (1 / 2.2)

    ZIEL.mkdir(parents=True, exist_ok=True)
    klein = ldr[::1, ::1]
    ausgabe = bpy.data.images.new(f"himmel_{thema}", width=b, height=h, alpha=False)
    rgba = np.ones((h, b, 4), dtype=np.float32)
    rgba[:, :, :3] = klein[::-1]
    ausgabe.pixels.foreach_set(rgba.ravel())
    ausgabe.filepath_raw = str(ZIEL / f"{thema}.jpg")
    ausgabe.file_format = "JPEG"
    bpy.context.scene.render.image_settings.quality = 90
    ausgabe.save()
    mittel_horizont = (ldr[int(h * 0.47): int(h * 0.5)].reshape(-1, 3) ** 2.2).mean(axis=0)
    mittel_zenit = (ldr[: int(h * 0.1)].reshape(-1, 3) ** 2.2).mean(axis=0)
    g.json_schreiben(ZIEL / f"{thema}.json", {
        "quelle": f"https://polyhaven.com/a/{asset}",
        "sonne_richtung": [round(c, 4) for c in sonne],
        "sonne_hoehe_grad": round(math.degrees(hoehe_rad), 1),
        "horizont_linear": [round(float(c), 4) for c in mittel_horizont],
        "zenit_linear": [round(float(c), 4) for c in mittel_zenit],
    })
    print(f"[himmel] {thema}: Sonne {sonne}, Skala {skala:.4f}")


def main() -> None:
    with open(g.WURZEL / "tools" / "blender" / "cc0_liste.json", encoding="utf-8") as fh:
        liste = json.load(fh)
    for thema, asset in liste["himmel"].items():
        umwandeln(thema, asset)


if __name__ == "__main__":
    main()
