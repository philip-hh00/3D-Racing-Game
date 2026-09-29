"""Selbst gerechnete Texturen der Fahrzeuge (alle Autos gemeinsam).

Schreibt nach ``assets/texturen/fahrzeug/`` (wie alle Texturen nicht im
Repository; die CC0-Quellen lädt das Skript von ambientCG nach
``rohdaten/cc0/ambientcg``); ``tools/blender/teile_oberflaeche.py``
legt sie auf die Materialien. Neu rechnen nur, wenn sich hier etwas ändert::

    .venv\\Scripts\\python.exe tools\\fahrzeug_texturen.py

* ``scheibenrand.png`` — Keramikrand der Scheiben (RGBA): u ist der Abstand
  zum Rand (``u = 0.1 + Abstand_m / 0.15``, schwarz bis 5 cm, Punkte bis
  9 cm, ab u = 0.7 klar), v läuft entlang des Rands und
  kachelt. Schwarzes Band, dann ein Punktraster, das nach innen ausläuft,
  dann klares, leicht getöntes Glas. Alpha ist die Deckung.
* ``polster_normal.jpg`` — abgesteppte Sitzmitte: Kanäle alle 5 cm mit
  Doppelnaht, dazu die Narbung aus ``leder_normal.jpg``. Kachel 0,30 m.
* ``anzeige.png`` — oben Kombiinstrument (zwei Rundinstrumente, Mitte
  Anzeige), unten Bildschirm der Mittelkonsole. Leuchtet über die
  Emissionstextur. Erfunden, ohne Marken und Namen.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ZIEL = Path(__file__).resolve().parents[1] / "assets" / "texturen" / "fahrzeug"

#: Deckung des klaren Glases und seine Tönung (sRGB 0..255).
GLAS_DECKUNG = 0.5
GLAS_TON = (20, 25, 27)


def scheibenrand(g: int = 512) -> Image.Image:
    """Keramikrand mit Punktraster, vierfach überabgetastet."""
    ss = 4
    n = g * ss
    u = (np.arange(n) + 0.5) / n
    abstand = (u - 0.1) * 0.15                              # Meter vom Rand
    band = 0.05                                             # voll schwarz bis hier
    ende = 0.09                                             # Punkte laufen hier aus
    # Punktraster: 38 Punkte je Kachel (knapp 4 mm), jede zweite Reihe versetzt.
    raster = 38
    zelle = n / raster
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) + 0.5
    reihe = np.floor(yy / zelle)
    xs = xx / zelle + 0.5 * (reihe % 2)
    dx = (xs - np.floor(xs) - 0.5) * zelle
    dy = (yy / zelle - reihe - 0.5) * zelle
    r = np.sqrt(dx * dx + dy * dy) / zelle                  # 0 .. ~0.7
    # Punktradius fällt vom Band nach innen von "deckend" auf null.
    t = np.clip((abstand - band) / (ende - band), 0.0, 1.0)[None, :]
    radius = 0.72 * (1.0 - t) ** 1.2
    punkt = (r < radius).astype(np.float32)
    deck = np.where(abstand[None, :] < band, 1.0, punkt)
    deck = deck.reshape(g, ss, g, ss).mean(axis=(1, 3))
    alpha = GLAS_DECKUNG + (1.0 - GLAS_DECKUNG) * deck
    rgb = np.array(GLAS_TON, np.float32)[None, None, :] * (1.0 - deck[..., None]) \
        + np.array((7, 7, 8), np.float32)[None, None, :] * deck[..., None]
    bild = np.concatenate([rgb, alpha[..., None] * 255.0], axis=2)
    return Image.fromarray(np.clip(bild + 0.5, 0, 255).astype(np.uint8), "RGBA")


def _normalen(hoehe: np.ndarray, staerke: float) -> np.ndarray:
    gy, gx = np.gradient(hoehe)
    n = np.stack([-gx * staerke, gy * staerke, np.ones_like(hoehe)], axis=-1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def polster(g: int = 512) -> Image.Image:
    kachel_m = 0.30
    px_m = g / kachel_m
    yy, xx = np.mgrid[0:g, 0:g].astype(np.float32)
    kanal = 0.05 * px_m                                     # Kanalabstand in Pixeln
    lage = (yy % kanal) / kanal                             # 0..1 zwischen zwei Kanälen
    # Kissen zwischen den Kanälen, Kanal als schmale Rinne.
    kissen = np.sin(np.pi * lage) ** 0.6
    rinne = np.exp(-((np.minimum(lage, 1 - lage) * kanal) / (0.0016 * px_m)) ** 2)
    h = 1.2 * kissen - 1.4 * rinne
    # Doppelnaht: Stiche 4 mm lang, 1,5 mm Lücke, 3 mm neben der Rinne.
    stich = 0.0055 * px_m
    for seite in (-1, 1):
        mitte = np.where(lage < 0.5, 0.0, kanal) + seite * 0.003 * px_m
        abstand = np.abs(yy % kanal - mitte % kanal)
        abstand = np.minimum(abstand, kanal - abstand)
        an = ((xx + (seite > 0) * stich * 0.5) % stich) < stich * 0.72
        faden = np.exp(-(abstand / (0.0006 * px_m)) ** 2) * an
        h += 0.8 * faden
    n = _normalen(h, 1.1)
    narbung = np.asarray(Image.open(ZIEL / "leder_normal.jpg").convert("RGB").resize((g, g)),
                         np.float32) / 127.5 - 1.0
    n[..., :2] += narbung[..., :2] * 0.8
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return Image.fromarray(np.clip((n * 0.5 + 0.5) * 255 + 0.5, 0, 255).astype(np.uint8), "RGB")


def anzeige(b: int = 512) -> Image.Image:
    """Oben (Zeilen 0..255) das Kombiinstrument, unten der Bildschirm."""
    ss = 2
    B = b * ss
    bild = Image.new("RGB", (B, B), (4, 5, 7))
    d = ImageDraw.Draw(bild)
    h = B // 2
    # --- Kombiinstrument -----------------------------------------------------
    for cx, rot_ab in ((B * 0.25, 0.8), (B * 0.75, 0.82)):
        cy = h * 0.52
        r = h * 0.4
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(70, 76, 84), width=3 * ss)
        for k in range(41):
            w = math.radians(225 - 270 * k / 40)
            lang = k % 5 == 0
            r0 = r * (0.8 if lang else 0.87)
            farbe = (230, 60, 40) if k / 40 >= rot_ab else (220, 225, 230)
            d.line((cx + r0 * math.cos(w), cy - r0 * math.sin(w),
                    cx + r * 0.94 * math.cos(w), cy - r * 0.94 * math.sin(w)),
                   fill=farbe, width=(3 if lang else 1) * ss)
        w = math.radians(225 - 270 * 0.28)
        d.line((cx, cy, cx + r * 0.78 * math.cos(w), cy - r * 0.78 * math.sin(w)),
               fill=(255, 120, 30), width=4 * ss)
        d.ellipse((cx - r * 0.1, cy - r * 0.1, cx + r * 0.1, cy + r * 0.1), fill=(30, 32, 36))
        # Ring aus Licht innen
        d.arc((cx - r * 0.66, cy - r * 0.66, cx + r * 0.66, cy + r * 0.66), 135, 405,
              fill=(40, 90, 150), width=2 * ss)
    # Mitte: kleine Anzeige mit Balken
    x0, x1 = B * 0.44, B * 0.56
    d.rounded_rectangle((x0, h * 0.2, x1, h * 0.8), radius=6 * ss, outline=(60, 66, 74), width=2 * ss)
    for k in range(6):
        y = h * (0.28 + 0.08 * k)
        d.rectangle((x0 + 8 * ss, y, x0 + 8 * ss + (x1 - x0 - 16 * ss) * (0.3 + 0.12 * k), y + 3 * ss),
                    fill=(90, 200, 255) if k < 4 else (255, 170, 40))
    # --- Bildschirm ------------------------------------------------------------
    oben = h
    for y in range(h):
        t = y / h
        d.line((0, oben + y, B, oben + y), fill=(int(10 + 12 * t), int(22 + 18 * t), int(40 + 30 * t)))
    rng = np.random.default_rng(7)
    # Karte: Straßen als helle Linien, ein Weg in Blau
    for _ in range(14):
        a = (rng.uniform(0, B * 0.66), oben + rng.uniform(0, h))
        e = (a[0] + rng.uniform(-200, 200) * ss, max(oben, a[1] + rng.uniform(-120, 120) * ss))
        d.line((a, e), fill=(70, 88, 110), width=3 * ss)
    weg = [(B * 0.08, oben + h * 0.85), (B * 0.25, oben + h * 0.6), (B * 0.32, oben + h * 0.62),
           (B * 0.5, oben + h * 0.3)]
    d.line(weg, fill=(60, 170, 255), width=6 * ss)
    d.ellipse((B * 0.5 - 9 * ss, oben + h * 0.3 - 9 * ss, B * 0.5 + 9 * ss, oben + h * 0.3 + 9 * ss),
              fill=(255, 255, 255))
    # rechte Spalte: Kacheln
    for k in range(3):
        y0 = oben + h * (0.08 + 0.3 * k)
        d.rounded_rectangle((B * 0.7, y0, B * 0.95, y0 + h * 0.24), radius=8 * ss,
                            fill=(28, 40, 58), outline=(60, 80, 105), width=ss)
        d.rectangle((B * 0.73, y0 + h * 0.08, B * (0.76 + 0.05 * k), y0 + h * 0.11), fill=(200, 210, 220))
    d.rectangle((0, oben + h - 26 * ss, B, oben + h), fill=(14, 18, 26))
    for k in range(5):
        cx = B * (0.1 + 0.2 * k)
        d.ellipse((cx - 7 * ss, oben + h - 20 * ss, cx + 7 * ss, oben + h - 6 * ss), outline=(150, 170, 190),
                  width=2 * ss)
    return bild.resize((b, b), Image.LANCZOS)


#: CC0-Quellen von ambientCG (ohne Konto, siehe assets/LIZENZEN.md).
AMBIENTCG = ("Fabric004", "Leather037", "Leather026")
ROH = Path(__file__).resolve().parents[1] / "rohdaten" / "cc0" / "ambientcg"


def _ambientcg_laden(name: str) -> Path:
    """``<name>_1K-JPG.zip`` laden und entpacken, falls noch nicht da."""
    import io
    import urllib.request
    import zipfile
    ordner = ROH / name
    if not (ordner / f"{name}_1K-JPG_NormalGL.jpg").exists():
        url = f"https://ambientcg.com/get?file={name}_1K-JPG.zip"
        anfrage = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(anfrage, timeout=60) as antwort:
            zipfile.ZipFile(io.BytesIO(antwort.read())).extractall(ordner)
    return ordner


def _lade(name: str, art: str, g: int = 512, modus: str = "RGB") -> np.ndarray:
    bild = Image.open(_ambientcg_laden(name) / f"{name}_1K-JPG_{art}.jpg").convert(modus)
    return np.asarray(bild.resize((g, g), Image.LANCZOS), dtype=np.float32) / 255.0


def _mr(rauheit: np.ndarray, metall, datei: str, mittel: float, spanne: float) -> None:
    """glTF-Metallic-Rauheit: Rauheit grün (auf Mittelwert und Streuung
    gebracht), Metall blau."""
    r = mittel + (rauheit - rauheit.mean()) * (spanne / max(float(rauheit.std()), 1e-4))
    r = np.clip(r, 0.03, 1.0)
    bild = np.stack([np.ones_like(r), r, np.ones_like(r) * metall], -1)
    Image.fromarray((bild * 255 + 0.5).astype(np.uint8)).save(ZIEL / datei, quality=92)


def _normal(name: str, datei: str, staerke: float) -> None:
    a = _lade(name, "NormalGL") * 2.0 - 1.0
    a[..., :2] *= staerke
    a /= np.linalg.norm(a, axis=-1, keepdims=True)
    Image.fromarray(((a * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)).save(ZIEL / datei, quality=94)


def cc0_aufbereiten() -> None:
    """Carbon (Fabric004), Leder (Leather037), Narbung (Leather026) auf 512²."""
    farbe = Image.open(_ambientcg_laden("Fabric004") / "Fabric004_1K-JPG_Color.jpg").convert("RGB")
    farbe.resize((512, 512), Image.LANCZOS).save(ZIEL / "carbon_farbe.jpg", quality=92)
    _normal("Fabric004", "carbon_normal.jpg", 1.0)
    _mr(_lade("Fabric004", "Roughness", modus="L"), _lade("Fabric004", "Metalness", modus="L"),
        "carbon_mr.jpg", 0.3, 0.06)
    _normal("Leather037", "leder_normal.jpg", 1.4)
    _mr(_lade("Leather037", "Roughness", modus="L"), 0.0, "leder_mr.jpg", 0.5, 0.07)
    _normal("Leather026", "narbung_normal.jpg", 0.8)
    _mr(_lade("Leather026", "Roughness", modus="L"), 0.0, "narbung_mr.jpg", 0.55, 0.05)


def main() -> None:
    ZIEL.mkdir(parents=True, exist_ok=True)
    cc0_aufbereiten()
    scheibenrand().save(ZIEL / "scheibenrand.png", optimize=True)
    polster().save(ZIEL / "polster_normal.jpg", quality=93)
    anzeige().save(ZIEL / "anzeige.png", optimize=True)
    for n in ("scheibenrand.png", "polster_normal.jpg", "anzeige.png"):
        print(n, (ZIEL / n).stat().st_size)


if __name__ == "__main__":
    main()
