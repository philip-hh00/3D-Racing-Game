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


# ---------------------------------------------------------------------------
# Streckenobjekte: Publikum, Fangzaun, Schilder, Flaggen
# ---------------------------------------------------------------------------

#: Kleidung und Haut der Zuschauer, sRGB. Viel Rot, Weiß und Schwarz —
#: Fanfarben —, dazu Alltagsfarben.
KLEIDUNG = [(196, 32, 36), (232, 232, 228), (26, 26, 30), (40, 70, 160), (236, 196, 40),
            (60, 130, 70), (220, 120, 50), (120, 120, 126), (150, 40, 110), (90, 160, 210),
            (180, 150, 110), (240, 90, 120)]
HAUT = [(236, 196, 164), (214, 168, 128), (180, 130, 96), (120, 82, 56), (240, 208, 180)]
HAARE = [(30, 22, 16), (70, 48, 30), (150, 110, 60), (200, 170, 110), (90, 90, 90), (20, 20, 20)]


def publikum() -> None:
    """Zuschauer als Karten: 16 Figuren in einem Bild (4 x 4), mit Alpha.

    Jede Figur sitzt oder steht, von vorn gesehen: Kopf, Haare, Oberkörper in
    einer Fanfarbe, Arme — manche hochgereckt, manche mit Mütze oder Fahne.
    Die Tribüne legt je Platz eine Karte und wählt eine Figur, dadurch sieht
    kein Block gleich aus.
    """
    rng = random.Random(17)
    zelle_b, zelle_h = 128, 256
    bild = Image.new("RGBA", (zelle_b * 4, zelle_h * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(bild)
    for k in range(16):
        x0, y0 = (k % 4) * zelle_b, (k // 4) * zelle_h
        mx = x0 + zelle_b / 2
        haut = rng.choice(HAUT)
        hemd = rng.choice(KLEIDUNG)
        hose = rng.choice([(40, 44, 60), (30, 30, 34), (90, 80, 70), (60, 70, 110)])
        kopf_r = rng.uniform(17, 21)
        kopf_y = y0 + 58 + rng.uniform(-6, 6)
        schulter = kopf_y + kopf_r + 6
        breite = rng.uniform(34, 44)
        # Beine/Hose (sitzend: kurz sichtbar), dann Oberkörper.
        d.rectangle((mx - breite * 0.8, schulter + 88, mx + breite * 0.8, y0 + zelle_h - 4), fill=hose)
        d.rounded_rectangle((mx - breite, schulter, mx + breite, schulter + 100), radius=16, fill=hemd)
        # Arme.
        hoch = rng.random() < 0.35
        for seite in (-1, 1):
            ax = mx + seite * (breite - 6)
            if hoch and (seite == 1 or rng.random() < 0.6):
                d.line((ax, schulter + 10, ax + seite * 14, schulter - 70), fill=hemd, width=16)
                d.ellipse((ax + seite * 14 - 9, schulter - 84, ax + seite * 14 + 9, schulter - 66), fill=haut)
            else:
                d.line((ax, schulter + 10, ax + seite * 4, schulter + 84), fill=hemd, width=15)
                d.ellipse((ax + seite * 4 - 8, schulter + 78, ax + seite * 4 + 8, schulter + 94), fill=haut)
        # Hals, Kopf, Haare oder Mütze.
        d.rectangle((mx - 7, kopf_y + kopf_r - 4, mx + 7, schulter + 4), fill=haut)
        d.ellipse((mx - kopf_r, kopf_y - kopf_r, mx + kopf_r, kopf_y + kopf_r), fill=haut)
        wahl = rng.random()
        if wahl < 0.3:
            muetze = rng.choice(KLEIDUNG)
            d.chord((mx - kopf_r - 1, kopf_y - kopf_r - 3, mx + kopf_r + 1, kopf_y + kopf_r * 0.6),
                    180, 360, fill=muetze)
            d.rectangle((mx - kopf_r - 1, kopf_y - 6, mx + kopf_r + 10, kopf_y - 1), fill=muetze)
        else:
            haar = rng.choice(HAARE)
            d.chord((mx - kopf_r - 1, kopf_y - kopf_r - 2, mx + kopf_r + 1, kopf_y + kopf_r * 0.5),
                    180, 360, fill=haar)
        # Sonnenbrille bei manchen.
        if rng.random() < 0.25:
            d.rectangle((mx - kopf_r * 0.7, kopf_y - 3, mx + kopf_r * 0.7, kopf_y + 4), fill=(15, 15, 18))
        # Streifen oder Aufdruck auf dem Hemd.
        if rng.random() < 0.4:
            streifen = rng.choice(KLEIDUNG)
            d.rectangle((mx - breite, schulter + 30, mx + breite, schulter + 42), fill=streifen)
    bild = rand_fuellen(bild)
    bild.save(ZIEL / "publikum.png")


def fangzaun() -> None:
    """Maschendraht, eine Kachel = 1 m x 1 m, mit Alpha (Material ``fangzaun_maske``).

    Rauten von gut 6 cm, Draht 4 px breit — dünner verschwände er in den
    Mip-Stufen schon auf halbe Distanz.
    """
    groesse = 512
    maschen = 8
    a = np.zeros((groesse, groesse), dtype=np.float64)
    y, x = np.mgrid[0:groesse, 0:groesse] / groesse * maschen
    # Zwei Scharen diagonaler Drähte.
    for u in ((x + y) % 1.0, (x - y) % 1.0):
        d = np.minimum(u, 1.0 - u) * groesse / maschen
        a = np.maximum(a, np.clip(2.6 - d, 0.0, 1.0))
    rgba = np.zeros((groesse, groesse, 4), dtype=np.uint8)
    # Verzinkter Draht, leicht fleckig.
    rng = np.random.default_rng(5)
    ton = 150 + 40 * rng.random((groesse, groesse))
    rgba[:, :, 0] = ton
    rgba[:, :, 1] = ton
    rgba[:, :, 2] = ton + 6
    rgba[:, :, 3] = (a * 255).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(ZIEL / "fangzaun.png")


def schilder() -> None:
    """Schilder der Streckenobjekte: Boxengebäude, Posten, Kameraturm, Flaggen."""
    # Boxengebäude: breites Band über den Garagen.
    b, h = 2048, 192
    bild = Image.new("RGB", (b, h), (22, 26, 34))
    d = ImageDraw.Draw(bild)
    d.rectangle((0, h - 16, b, h), fill=(200, 24, 30))
    d.text((60, h / 2 - 6), "APEX RACEWAY", font=schrift(120), fill=(245, 245, 245), anchor="lm")
    d.text((b - 60, h / 2 - 6), "PIT LANE  ·  BOXEN", font=schrift(90), fill=(245, 200, 30), anchor="rm")
    bild.save(ZIEL / "boxenschild.jpg", quality=92)
    # Garagennummern 1-8 in einer Reihe.
    b, h = 1024, 128
    bild = Image.new("RGB", (b, h), (240, 240, 236))
    d = ImageDraw.Draw(bild)
    for i in range(8):
        d.text((i * 128 + 64, h / 2), str(i + 1), font=schrift(96), fill=(20, 20, 24), anchor="mm")
    bild.save(ZIEL / "garagennummern.jpg", quality=92)
    # Postenhaus: Nummerntafel.
    b, h = 256, 256
    bild = Image.new("RGB", (b, h), (250, 250, 248))
    d = ImageDraw.Draw(bild)
    d.rectangle((0, 0, b, 40), fill=(236, 110, 20))
    d.text((b / 2, 150), "POSTEN", font=schrift(46), fill=(20, 20, 24), anchor="mm")
    d.text((b / 2, 90), "7", font=schrift(64), fill=(236, 110, 20), anchor="mm")
    bild.save(ZIEL / "postenschild.jpg", quality=92)
    # Flaggen: je Marke eine.
    for i, (marke, _zusatz, grund, schriftfarbe) in enumerate(BANDEN[:4]):
        b, h = 512, 320
        bild = Image.new("RGB", (b, h), grund)
        d = ImageDraw.Draw(bild)
        d.rectangle((0, h - 40, b, h), fill=tuple(min(255, int(c * 0.75 + 30)) for c in grund))
        d.text((b / 2, h / 2 - 12), marke, font=schrift(92 if len(marke) < 8 else 70),
               fill=schriftfarbe, anchor="mm")
        bild.save(ZIEL / f"flagge_{i}.jpg", quality=92)
    # Kameraturm: Blende mit "TV".
    b, h = 256, 128
    bild = Image.new("RGB", (b, h), (30, 30, 34))
    d = ImageDraw.Draw(bild)
    d.text((b / 2, h / 2), "TV", font=schrift(90), fill=(245, 245, 245), anchor="mm")
    bild.save(ZIEL / "tvschild.jpg", quality=92)


#: Maße der Boxengasse vor dem Boxengebäude, Meter (siehe
#: ``umgebung_bauen.boxengebaeude``): 8 Garagen je 6 m, 2 m Rand je Seite.
BOXENGASSE_M = (52.0, 8.0)


def boxengasse(je_m: int = 64) -> None:
    """Der Vorplatz der Boxen als **ein** Bild über die ganze Fläche.

    Grund ist der Asphalt der Strecke, auf das Grau der Fahrbahn gezogen und
    etwas dunkler als sie — eine Boxengasse wirkt nie heller als die
    Rennstrecke daneben. Darauf Schmutz, Ölflecken vor den Garagen, Fugen alle
    fünf Meter, eine weiße Linie zwischen Arbeits- und Fahrspur und gelbe
    Boxenfelder. Zeile 0 ist die Streckenseite (v = 1), Spalte 0 liegt bei
    lokal -X. Dazu die Rauheit: Linien etwas glatter.
    """
    breite_m, tiefe_m = BOXENGASSE_M
    b, h = int(breite_m * je_m), int(tiefe_m * je_m)
    rng = np.random.default_rng(23)
    quelle = Image.open(TEX / "asphalt_farbe.jpg").convert("L")
    kachel = quelle.resize((9 * je_m, 9 * je_m), Image.LANCZOS)
    grund = np.asarray(kachel, dtype=np.float64) / 255.0
    grund = np.tile(grund, (h // grund.shape[0] + 1, b // grund.shape[1] + 1))[:h, :b]
    # Kontrast zusammenziehen, auf ein mittleres Grau um 0,22 (sRGB).
    grund = 0.22 + (grund - grund.mean()) * 0.55
    # Großflächiger Schmutz: grobes Rauschen, weich.
    grob = Image.fromarray((rng.random((h // 32 + 2, b // 32 + 2)) * 255).astype(np.uint8))
    grob = np.asarray(grob.resize((b, h), Image.BICUBIC), dtype=np.float64) / 255.0
    grund *= 0.9 + 0.18 * grob
    y_m = (1.0 - (np.arange(h) + 0.5) / h) * tiefe_m          # 0 an den Garagen
    x_m = (np.arange(b) + 0.5) / b * breite_m
    bild = np.stack([grund * 1.0, grund * 0.99, grund * 0.97], axis=2)
    rau = np.full((h, b), 0.86)
    # Ölflecken in der Arbeitsspur vor jeder Garage.
    maske = Image.new("L", (b, h), 0)
    d = ImageDraw.Draw(maske)
    for i in range(8):
        mitte_x = (2.0 + 6.0 * (i + 0.5)) * je_m
        for _ in range(rng.integers(2, 5)):
            cx = mitte_x + rng.normal(0, 1.2) * je_m
            cy = h - (rng.uniform(1.0, 3.2)) * je_m
            r = rng.uniform(0.2, 0.6) * je_m
            d.ellipse((cx - r * 1.4, cy - r, cx + r * 1.4, cy + r), fill=int(rng.uniform(90, 170)))
    fleck = np.asarray(maske.filter(ImageFilter.GaussianBlur(je_m * 0.15)), dtype=np.float64) / 255.0
    bild *= (1.0 - 0.45 * fleck)[:, :, None]
    rau -= 0.2 * fleck
    # Linien: weiß zwischen Arbeits- und Fahrspur (4 m von den Garagen),
    # gestrichelt an der Streckenseite; gelbe Boxenfelder je Garage.
    weiss = np.array([0.72, 0.72, 0.70])
    gelb = np.array([0.74, 0.58, 0.12])

    def band(maske_bool, farbe, abnutzung=0.25):
        staerke = maske_bool * (1.0 - abnutzung * rng.random((h, b)))
        bild[:] = bild * (1 - staerke[:, :, None]) + farbe * staerke[:, :, None]
        rau[:] = np.where(maske_bool, 0.6, rau)

    band(np.abs(y_m - 4.0)[:, None] < 0.07 + 0 * x_m[None, :], weiss)
    strich = ((x_m % 3.0) < 1.5)[None, :]
    band((np.abs(y_m - 7.6)[:, None] < 0.06) & strich, weiss)
    for i in range(8):
        x0, x1 = 2.0 + 6.0 * i + 0.4, 2.0 + 6.0 * (i + 1) - 0.4
        in_x = (x_m >= x0) & (x_m <= x1)
        rahmen = ((np.abs(x_m - x0) < 0.05) | (np.abs(x_m - x1) < 0.05))[None, :] & (y_m < 3.6)[:, None]
        rahmen |= in_x[None, :] & (np.abs(y_m - 3.6) < 0.05)[:, None]
        band(rahmen, gelb)
    # Fugen alle fünf Meter quer, dunkel und schmal.
    fuge = (np.abs(((x_m + 2.5) % 5.0) - 2.5) < 0.012)[None, :] | (np.abs(y_m - 6.0) < 0.012)[:, None]
    bild *= np.where(fuge, 0.55, 1.0)[:, :, None]
    bild *= (0.95 + 0.05 * rng.random((h, b)))[:, :, None]
    Image.fromarray((np.clip(bild, 0, 1) * 255).astype(np.uint8), "RGB").save(ZIEL / "boxengasse.jpg", quality=90)
    mr_bild((b // 2, h // 2), np.clip(rau, 0.3, 1.0)).save(ZIEL / "boxengasse_mr.png")


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
    publikum()
    fangzaun()
    schilder()
    boxengasse()
    print("fertig:", sorted(p.name for p in ZIEL.iterdir()))


if __name__ == "__main__":
    main()
