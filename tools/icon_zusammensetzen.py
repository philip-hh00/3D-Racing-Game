"""Setzt den Blender-Autorender (``tools/blender/icon_bauen.py``) auf einen
abgerundeten, dunklen Hintergrund mit Farbverlauf und Lichtkante und erzeugt
daraus ``data/icon.png``, ``data/icon.ico`` und ``data/icon.icns``.

Aufruf::

    .venv\\Scripts\\python.exe -m tools.icon_zusammensetzen <pfad-zum-render.png>

Blender liefert nur das freigestellte Fahrzeug (Alpha-Kanal, siehe
``tools/blender/icon_bauen.py``) — Hintergrund, Rundung und Lichtkante kommen
bewusst erst hier mit PIL dazu, damit sich der Look ohne einen neuen
Blender-Lauf anpassen laesst.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
GROESSE = 1024
RADIUS = 190

#: Dunkles Gruen-Grau oben, fast Schwarz unten — passend zum Wagenlack, aber
#: dunkel genug, dass ein helles Fahrzeug bei 16x16 noch Kontrast hat.
_FARBE_OBEN = (26, 32, 27)
_FARBE_UNTEN = (8, 10, 9)


def _rundes_quadrat(groesse: int, radius: int) -> Image.Image:
    """Dunkler Hintergrund: vertikaler Farbverlauf, abgerundete Ecken, Lichtkante."""
    farbverlauf = Image.new("RGBA", (groesse, groesse))
    zeilen = []
    for y in range(groesse):
        t = y / (groesse - 1)
        zeilen.append(tuple(int(_FARBE_OBEN[i] + (_FARBE_UNTEN[i] - _FARBE_OBEN[i]) * t) for i in range(3)))
    pixel = farbverlauf.load()
    for y, farbe in enumerate(zeilen):
        for x in range(groesse):
            pixel[x, y] = (*farbe, 255)

    maske = Image.new("L", (groesse, groesse), 0)
    ImageDraw.Draw(maske).rounded_rectangle((0, 0, groesse - 1, groesse - 1), radius=radius, fill=255)

    basis = Image.new("RGBA", (groesse, groesse), (0, 0, 0, 0))
    basis.paste(farbverlauf, (0, 0), maske)

    # Lichtkante oben links: ein weicher heller Rand, wie Streiflicht auf Glas —
    # nur auf der Seite der (angenommenen) Lichtquelle, damit es nach Licht statt
    # nach einer gleichmaessig gemalten Umrandung aussieht.
    kante = Image.new("L", (groesse, groesse), 0)
    ImageDraw.Draw(kante).rounded_rectangle((0, 0, groesse - 1, groesse - 1), radius=radius, outline=255, width=10)
    kante = kante.filter(ImageFilter.GaussianBlur(6))

    richtung = Image.new("L", (groesse // 4, groesse), 0)
    rpix = richtung.load()
    for y in range(groesse):
        for x in range(groesse // 4):
            t = max(0.0, 1.0 - ((x * 4) + y) / (groesse * 1.4))
            rpix[x, y] = int(255 * t)
    richtung = richtung.resize((groesse, groesse))

    kante_gerichtet = Image.composite(kante, Image.new("L", (groesse, groesse), 0), richtung)
    licht = Image.new("RGBA", (groesse, groesse), (170, 220, 150, 0))
    basis.paste(licht, (0, 0), kante_gerichtet)

    # Feine dunkle Umrandung, damit die Kante auf hellem UI (helle Taskleiste,
    # weisser Datei-Explorer) nicht verschwimmt.
    rand = Image.new("L", (groesse, groesse), 0)
    ImageDraw.Draw(rand).rounded_rectangle((0, 0, groesse - 1, groesse - 1), radius=radius, outline=255, width=3)
    dunkel = Image.new("RGBA", (groesse, groesse), (0, 0, 0, 140))
    basis.paste(dunkel, (0, 0), rand)

    basis.putalpha(maske)
    return basis


def _auto_crop(im: Image.Image, polster: float = 0.06) -> Image.Image:
    """Schneidet auf den sichtbaren Wagen zu, mit etwas Luft ringsum."""
    bbox = im.getbbox()
    if not bbox:
        return im
    x0, y0, x1, y1 = bbox
    w, h = x1 - x0, y1 - y0
    px, py = int(w * polster), int(h * polster)
    x0, y0 = max(0, x0 - px), max(0, y0 - py)
    x1, y1 = min(im.width, x1 + px), min(im.height, y1 + py)
    return im.crop((x0, y0, x1, y1))


def zusammensetzen(render_pfad: Path) -> Image.Image:
    hintergrund = _rundes_quadrat(GROESSE, RADIUS)

    wagen = Image.open(render_pfad).convert("RGBA")
    wagen = _auto_crop(wagen)

    ziel_breite = int(GROESSE * 0.80)
    skala = ziel_breite / wagen.width
    wagen = wagen.resize((ziel_breite, int(wagen.height * skala)), Image.LANCZOS)

    ox = (GROESSE - wagen.width) // 2
    oy = (GROESSE - wagen.height) // 2 + int(GROESSE * 0.03)

    schatten = Image.new("RGBA", (GROESSE, GROESSE), (0, 0, 0, 0))
    alpha = wagen.split()[3]
    schwarz = Image.new("RGBA", wagen.size, (0, 0, 0, 160))
    schatten.paste(schwarz, (ox + 14, oy + 22), alpha)
    schatten = schatten.filter(ImageFilter.GaussianBlur(18))

    ergebnis = hintergrund.copy()
    ergebnis.alpha_composite(schatten)
    ergebnis.alpha_composite(wagen, (ox, oy))
    return ergebnis


def main() -> None:
    if len(sys.argv) < 2:
        print("Aufruf: python -m tools.icon_zusammensetzen <render.png>")
        raise SystemExit(1)

    ergebnis = zusammensetzen(Path(sys.argv[1]))
    daten_dir = ROOT / "data"

    ergebnis.resize((256, 256), Image.LANCZOS).save(daten_dir / "icon.png")
    print("geschrieben:", daten_dir / "icon.png")

    # Pillows ICO-Schreiber skaliert selbst aus der 1024er-Vorlage herunter —
    # als Basis muss die volle Aufloesung dienen, sonst kommt nur eine Groesse
    # heraus (nachgemessen: eine bereits verkleinerte Basis lieferte nur 16x16).
    ico_groessen = [16, 24, 32, 48, 64, 128, 256]
    ergebnis.save(daten_dir / "icon.ico", format="ICO", sizes=[(g, g) for g in ico_groessen])
    print("geschrieben:", daten_dir / "icon.ico", ico_groessen)

    icns_groessen = [16, 32, 64, 128, 256, 512, 1024]
    icns_frames = {g: ergebnis.resize((g, g), Image.LANCZOS) for g in icns_groessen}
    icns_frames[1024].save(
        daten_dir / "icon.icns",
        format="ICNS",
        append_images=[icns_frames[g] for g in icns_groessen if g != 1024],
    )
    print("geschrieben:", daten_dir / "icon.icns")


if __name__ == "__main__":
    main()
