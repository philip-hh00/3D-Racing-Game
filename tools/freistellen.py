"""Ein Bild freistellen und als RGBA nach ComfyUI\\input legen.

    tools\\freistellen.bat "C:\\pfad\\rookie_3d.png"

Warum das noetig ist: ``Trellis2PreProcessImage`` im Node ruft ohne Umschweife
``output_np[:, :, 3]`` auf (nodes.py:2675). Die eingebaute Hintergrund-
entfernung ist dort auskommentiert. Ein Bild ohne Alphakanal - etwa ein Render
mit schwarzem Hintergrund - bricht mit ``IndexError: index 3 is out of bounds``
ab.

Der Node kann das ueber ``remove_background`` selbst erledigen. Dann sieht man
das Ergebnis der Freistellung aber erst nach dem kompletten Durchlauf, und der
dauert eine knappe halbe Stunde. Hier kommt zusaetzlich eine Kontrollansicht
heraus, an der sich in Sekunden erkennen laesst, ob die Silhouette stimmt.

Laeuft mit dem Python aus tools\\ComfyUI\\venv - dort liegt rembg.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HIER = Path(__file__).resolve().parent
INPUT_DIR = HIER / "ComfyUI" / "input"

#: Ab welchem Alphawert ein Pixel als Vordergrund zaehlt - dieselbe Schwelle,
#: die der Node in Zeile 2676 zum Zuschneiden benutzt.
SCHWELLE = int(0.8 * 255)


def freistellen(bild: Image.Image) -> Image.Image:
    from rembg import remove
    return remove(bild.convert("RGB")).convert("RGBA")


def kontrollbild(rgba: Image.Image) -> Image.Image:
    """Das Motiv auf Magenta - dort faellt jeder stehengebliebene Rest auf.

    Ein Schachbrett waere huebscher, aber Magenta kommt an einem Auto nicht vor
    und macht Reste des schwarzen Hintergrunds sofort sichtbar.
    """
    grund = Image.new("RGBA", rgba.size, (255, 0, 255, 255))
    return Image.alpha_composite(grund, rgba)


def bewerten(rgba: Image.Image) -> list[str]:
    """Was an dieser Freistellung auffaellt."""
    alpha = np.asarray(rgba)[:, :, 3]
    anteil = float((alpha > SCHWELLE).mean())
    meldungen = [f"Vordergrund     {anteil * 100:.1f} % der Bildflaeche"]
    if anteil < 0.02:
        meldungen.append("WARNUNG         Fast nichts uebrig - hat rembg das Motiv gefunden?")
    elif anteil > 0.95:
        meldungen.append("WARNUNG         Fast alles Vordergrund - der Hintergrund blieb stehen")
    if not (alpha < SCHWELLE).any():
        meldungen.append("WARNUNG         Kein einziges transparentes Pixel - der Node wuerde "
                         "das Bild ungeschnitten weiterreichen")
    return meldungen


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Bild freistellen und in ComfyUI\\input legen.")
    p.add_argument("bild", type=Path, help="Quellbild, beliebiges Format")
    p.add_argument("--name", help="Dateiname in input\\ (Vorgabe: <quelle>_rgba.png)")
    p.add_argument("--out", type=Path, default=INPUT_DIR, help="Zielordner")
    a = p.parse_args(argv)

    if not a.bild.is_file():
        print(f"FEHLER: {a.bild} nicht gefunden", file=sys.stderr)
        return 2

    quelle = Image.open(a.bild)
    print(f"Quelle          {a.bild}  {quelle.size}  {quelle.mode}")

    rgba = freistellen(quelle)
    a.out.mkdir(parents=True, exist_ok=True)
    name = a.name or f"{a.bild.stem}_rgba.png"
    ziel = a.out / name
    rgba.save(ziel)

    kontrolle = ziel.with_name(f"{ziel.stem}_kontrolle.png")
    kontrollbild(rgba).convert("RGB").save(kontrolle)

    print(f"Freigestellt    {ziel}")
    print(f"Kontrollbild    {kontrolle}   (Motiv auf Magenta)")
    for zeile in bewerten(rgba):
        print(zeile)
    print()
    print("Im Workflow jetzt dieses Bild waehlen. remove_background bleibt dann")
    print("auf false - die Freistellung ist ja schon drin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
