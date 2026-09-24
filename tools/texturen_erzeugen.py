"""Texturen, die es nirgends zu laden gibt: Fassaden, Nadelzweige, Banden, Heu.

Läuft mit dem Python des Spiels (PIL, numpy) und schreibt nach
``rohdaten/erzeugt/``; ``tools/blender/umgebung_bauen.py`` bettet die Bilder in
die GLB-Dateien ein. Aufruf::

    .venv\\Scripts\\python.exe tools\\texturen_erzeugen.py

**Fassaden** sind eine Kachel aus einem Geschoss mit einem Fensterfeld. Die
Wand stammt aus einer CC0-Textur (Putz, Ziegel, Holz), die Fenster werden
darübergezeichnet. Zu jeder Farbkachel gehört eine Metallic-Rauheits-Kachel:
Glas ist glatt, Wand ist rau — so spiegeln im Spiel die Fenster den Himmel
und die Wand nicht. Das ist billiger als Fenstergeometrie und aus der
Verfolgerkamera nicht von ihr zu unterscheiden.

**Randfarbe unter Alpha.** Wo eine Blattkarte durchsichtig ist, wird die
Farbe trotzdem auf das mittlere Grün gesetzt. Sonst mischen die Mip-Stufen
den (weißen oder schwarzen) Hintergrund in den Rand, und jeder Baum bekommt
einen hellen Saum.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WURZEL = Path(__file__).resolve().parents[1]
ZIEL = WURZEL / "rohdaten" / "erzeugt"
TEX = WURZEL / "assets" / "texturen"
BLAETTER = WURZEL / "rohdaten" / "cc0" / "blaetter"


def rand_fuellen(bild: Image.Image) -> Image.Image:
    """RGB unter durchsichtigen Pixeln auf die mittlere Farbe setzen."""
    a = np.asarray(bild.convert("RGBA")).astype(np.float64)
    deckend = a[:, :, 3] > 128
    if deckend.any():
        mittel = a[deckend][:, :3].mean(axis=0)
        a[~deckend, :3] = mittel
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def mr_bild(groesse, rauheit_karte: np.ndarray, metall: np.ndarray | None = None) -> Image.Image:
    h, b = rauheit_karte.shape
    rgb = np.zeros((h, b, 3), dtype=np.uint8)
    rgb[:, :, 1] = np.clip(rauheit_karte * 255, 0, 255)
    if metall is not None:
        rgb[:, :, 2] = np.clip(metall * 255, 0, 255)
    return Image.fromarray(rgb, "RGB").resize(groesse)


# ---------------------------------------------------------------------------
# Fassaden
# ---------------------------------------------------------------------------

def wandkachel(name: str, groesse: int, farbe=None, anteil: float = 0.5) -> Image.Image:
    """Ein Ausschnitt einer CC0-Wandtextur, wahlweise eingefärbt."""
    quelle = Image.open(TEX / f"{name}_farbe.jpg").convert("RGB")
    s = int(quelle.width * anteil)
    ausschnitt = quelle.crop((0, 0, s, s)).resize((groesse, groesse), Image.LANCZOS)
    if farbe is not None:
        a = np.asarray(ausschnitt).astype(np.float64) / 255
        grau = a.mean(axis=2, keepdims=True)
        getoent = grau / max(grau.mean(), 1e-3) * np.asarray(farbe) / 255
        ausschnitt = Image.fromarray((np.clip(getoent, 0, 1) * 255).astype(np.uint8))
    return ausschnitt


def fassade(name: str, wand: Image.Image, fenster: dict, groesse=(512, 512)) -> None:
    """Eine Geschosskachel: Wand plus ein Fenster mit Rahmen und Bank.

    ``fenster``: ``breite``/``hoehe``/``unten`` als Anteile der Kachel,
    ``rahmen`` (Farbe), ``glas`` (Farbe), ``sprossen`` (Anzahl senkrechter
    Teilungen), ``band`` (Farbe eines Geschossbands oder None).
    """
    b, h = groesse
    bild = wand.resize(groesse).convert("RGB")
    rau = np.full((h, b), 0.85)
    metall = np.zeros((h, b))
    d = ImageDraw.Draw(bild)
    if fenster.get("band"):
        bh = int(h * 0.08)
        d.rectangle((0, h - bh, b, h), fill=tuple(fenster["band"]))
    fb, fh = int(b * fenster["breite"]), int(h * fenster["hoehe"])
    x0 = (b - fb) // 2
    y1 = h - int(h * fenster["unten"])
    y0 = y1 - fh
    rahmen = int(b * 0.025)
    d.rectangle((x0 - rahmen, y0 - rahmen, x0 + fb + rahmen, y1 + rahmen),
                fill=tuple(fenster["rahmen"]))
    # Glas: dunkel, nach oben etwas heller — der Himmel spiegelt ohnehin im Spiel.
    glas = np.asarray(fenster["glas"], dtype=np.float64)
    for y in range(y0, y1):
        t = (y - y0) / max(1, fh)
        f = glas * (1.15 - 0.3 * t)
        d.line((x0, y, x0 + fb, y), fill=tuple(int(c) for c in np.clip(f, 0, 255)))
    rau[y0:y1, x0:x0 + fb] = 0.06
    teile = fenster.get("sprossen", 1)
    for k in range(1, teile):
        x = x0 + fb * k // teile
        d.rectangle((x - rahmen // 2, y0, x + rahmen // 2, y1), fill=tuple(fenster["rahmen"]))
        rau[y0:y1, x - rahmen // 2:x + rahmen // 2 + 1] = 0.5
    if fenster.get("quer"):
        y = y0 + fh // 3
        d.rectangle((x0, y - rahmen // 2, x0 + fb, y + rahmen // 2), fill=tuple(fenster["rahmen"]))
    # Fensterbank
    d.rectangle((x0 - rahmen * 2, y1 + rahmen, x0 + fb + rahmen * 2, y1 + rahmen * 3),
                fill=tuple(int(c * 0.8) for c in fenster["rahmen"]))
    # Leichter Schmutz unter der Bank.
    schatten = Image.new("L", groesse, 0)
    ImageDraw.Draw(schatten).rectangle((x0, y1 + rahmen * 3, x0 + fb, y1 + rahmen * 8), fill=40)
    schatten = schatten.filter(ImageFilter.GaussianBlur(6))
    bild = Image.composite(Image.new("RGB", groesse, (30, 30, 30)), bild, schatten)
    bild.save(ZIEL / f"fassade_{name}.jpg", quality=90)
    mr_bild(groesse, rau, metall).save(ZIEL / f"fassade_{name}_mr.png")


def glasfassade(name: str, glas, pfosten, groesse=(512, 512)) -> None:
    """Vorhangfassade eines Büroturms: Glas, Pfosten, Brüstungsband."""
    b, h = groesse
    a = np.zeros((h, b, 3))
    rau = np.full((h, b), 0.05)
    metall = np.zeros((h, b))
    glas = np.asarray(glas, dtype=np.float64)
    for y in range(h):
        a[y, :] = glas * (0.85 + 0.3 * (1 - y / h))
    band = int(h * 0.22)
    a[h - band:, :] = np.asarray(pfosten) * 0.8
    rau[h - band:, :] = 0.35
    metall[h - band:, :] = 0.6
    breite = int(b * 0.03)
    for x in (0, b // 2):
        a[:, x:x + breite] = pfosten
        rau[:, x:x + breite] = 0.3
        metall[:, x:x + breite] = 0.9
    rng = np.random.default_rng(len(name))
    a *= rng.uniform(0.96, 1.04, size=(1, 1, 3))
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(ZIEL / f"fassade_{name}.jpg", quality=90)
    mr_bild(groesse, rau, metall).save(ZIEL / f"fassade_{name}_mr.png")


# ---------------------------------------------------------------------------
# Laub
# ---------------------------------------------------------------------------

def nadelzweig(name: str, farbe=(38, 62, 30), groesse=(512, 256), seed: int = 1) -> None:
    """Ein Tannenzweig von links (Ansatz) nach rechts (Spitze)."""
    rng = random.Random(seed)
    b, h = groesse
    bild = Image.new("RGBA", groesse, (0, 0, 0, 0))
    d = ImageDraw.Draw(bild)

    def zweig(x0, y0, laenge, winkel, dicke, tiefe):
        schritte = int(laenge / 3)
        for s in range(schritte):
            t = s / max(1, schritte)
            x = x0 + math.cos(winkel) * laenge * t
            y = y0 + math.sin(winkel) * laenge * t
            nadel = (1 - t * 0.6) * h * 0.13 * (0.6 if tiefe else 1.0)
            for seite in (-1, 1):
                w = winkel + seite * math.radians(rng.uniform(50, 75))
                ton = rng.uniform(0.7, 1.25)
                f = tuple(int(min(255, c * ton)) for c in farbe) + (255,)
                d.line((x, y, x + math.cos(w) * nadel, y + math.sin(w) * nadel), fill=f, width=2)
            if tiefe == 0 and s % 9 == 4 and t < 0.8:
                zweig(x, y, laenge * (1 - t) * 0.5, winkel + rng.choice((-1, 1)) * 0.6,
                      max(1, dicke - 1), 1)
        d.line((x0, y0, x0 + math.cos(winkel) * laenge, y0 + math.sin(winkel) * laenge),
               fill=(70, 50, 35, 255), width=dicke)

    zweig(4, h / 2, b - 12, 0.0, 4, 0)
    rand_fuellen(bild).save(ZIEL / f"{name}.png")


def laub_aufbereiten() -> None:
    for n in ("laub", "busch"):
        quelle = BLAETTER / f"{n}.png"
        if quelle.is_file():
            bild = Image.open(quelle)
            if n == "busch":
                # Links liegt im Atlas ein Rindenstreifen, keine Blätter.
                bild = bild.crop((int(bild.width * 0.24), 0, bild.width, bild.height))
            rand_fuellen(bild).resize((512, 512), Image.LANCZOS).save(ZIEL / f"blatt_{n}.png")


# ---------------------------------------------------------------------------
# Banden, Heu
# ---------------------------------------------------------------------------

#: Erfundene Marken — keine echten Firmen.
BANDEN = [
    ("APEX", "MOTORSPORT", (200, 24, 30), (255, 255, 255)),
    ("VOLTRA", "ENERGY DRINK", (20, 20, 22), (240, 200, 20)),
    ("NORDLICHT", "OIL & LUBES", (18, 60, 150), (255, 255, 255)),
    ("KRONFELD", "REIFEN", (250, 200, 10), (20, 20, 20)),
    ("VELOCIA", "RACING", (240, 240, 240), (200, 20, 20)),
    ("TURBOLINE", "PARTS", (30, 130, 70), (255, 255, 255)),
]


def schrift(groesse: int):
    for pfad in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(pfad, groesse)
        except OSError:
            continue
    return ImageFont.load_default()


def banden() -> None:
    """Werbebanden, 6:1, je eine erfundene Marke."""
    b, h = 1536, 256
    for i, (marke, zusatz, grund, schriftfarbe) in enumerate(BANDEN):
        bild = Image.new("RGB", (b, h), grund)
        d = ImageDraw.Draw(bild)
        d.polygon([(b * 0.72, 0), (b * 0.86, 0), (b * 0.76, h), (b * 0.62, h)],
                  fill=tuple(min(255, int(c * 0.8 + 40)) for c in grund))
        f = schrift(150)
        d.text((60, h / 2), marke, font=f, fill=schriftfarbe, anchor="lm")
        d.text((b - 60, h / 2), zusatz, font=schrift(70), fill=schriftfarbe, anchor="rm")
        bild.save(ZIEL / f"bande_{i}.jpg", quality=92)


def startbanner() -> None:
    """Das Banner der Startbrücke: Karo links und rechts, dazwischen START · ZIEL."""
    b, h = 2048, 256
    bild = Image.new("RGB", (b, h), (14, 14, 18))
    d = ImageDraw.Draw(bild)
    feld = h // 4
    for rand_x in (0, b - 3 * feld):
        for i in range(3):
            for j in range(4):
                if (i + j) % 2 == 0:
                    d.rectangle((rand_x + i * feld, j * feld, rand_x + (i + 1) * feld - 1,
                                 (j + 1) * feld - 1), fill=(240, 240, 240))
    d.text((b / 2, h / 2), "START  ·  ZIEL", font=schrift(150), fill=(250, 250, 250), anchor="mm")
    d.rectangle((3 * feld, h - 14, b - 3 * feld, h), fill=(200, 24, 30))
    bild.save(ZIEL / "startbanner.jpg", quality=92)


def heu() -> None:
    rng = np.random.default_rng(3)
    b = h = 256
    a = np.zeros((h, b, 3))
    basis = np.array([196, 168, 96])
    for _ in range(3000):
        x, y = rng.integers(0, b), rng.integers(0, h)
        l = rng.integers(6, 24)
        ton = rng.uniform(0.7, 1.15)
        a[y, max(0, x - l):x] = basis * ton
    a[a.sum(axis=2) == 0] = basis * 0.75
    Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.6)).save(ZIEL / "heu.jpg", quality=90)


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    fassade("wohn_hell", wandkachel("putz", 512, (228, 220, 205)),
            dict(breite=0.46, hoehe=0.52, unten=0.28, rahmen=(235, 235, 230), glas=(40, 52, 64),
                 sprossen=2, band=(200, 195, 185)))
    fassade("wohn_ocker", wandkachel("putz", 512, (214, 170, 110)),
            dict(breite=0.42, hoehe=0.5, unten=0.3, rahmen=(245, 245, 240), glas=(38, 48, 58),
                 sprossen=2, quer=True))
    fassade("wohn_grau", wandkachel("betonwand", 512),
            dict(breite=0.6, hoehe=0.48, unten=0.3, rahmen=(60, 62, 66), glas=(30, 40, 50),
                 sprossen=3, band=(120, 120, 118)))
    fassade("backstein", wandkachel("ziegel", 512, anteil=0.35),
            dict(breite=0.4, hoehe=0.52, unten=0.28, rahmen=(240, 240, 235), glas=(35, 45, 55),
                 sprossen=2, quer=True))
    fassade("lehm", wandkachel("putz", 512, (196, 150, 104)),
            dict(breite=0.26, hoehe=0.34, unten=0.36, rahmen=(92, 64, 40), glas=(26, 24, 22),
                 sprossen=1))
    fassade("holz", wandkachel("holz", 512, anteil=0.4),
            dict(breite=0.34, hoehe=0.38, unten=0.32, rahmen=(236, 232, 220), glas=(34, 42, 50),
                 sprossen=2, quer=True))
    fassade("bauernhaus", wandkachel("putz", 512, (238, 232, 218)),
            dict(breite=0.36, hoehe=0.44, unten=0.3, rahmen=(120, 70, 40), glas=(36, 44, 52),
                 sprossen=2, quer=True))
    glasfassade("buero_blau", (70, 100, 130), (150, 155, 160))
    glasfassade("buero_gruen", (60, 105, 100), (60, 64, 68))
    glasfassade("buero_bronze", (110, 90, 70), (40, 38, 36))
    nadelzweig("nadelzweig", seed=1)
    nadelzweig("nadelzweig_hell", farbe=(56, 84, 40), seed=2)
    laub_aufbereiten()
    banden()
    startbanner()
    heu()
    print("fertig:", sorted(p.name for p in ZIEL.iterdir()))


if __name__ == "__main__":
    main()
