"""Sprite und Blender-Draufsicht übereinanderlegen — Werkzeug zum Formabgleich.

Läuft mit dem Python des Spiels (pygame, numpy, PIL), **nicht** in Blender::

    .venv/Scripts/python.exe tools/blender/vergleich.py --render <ordner> \
        --ausgabe <ordner> [--fahrzeug rookie,supercar]

``<ordner>`` enthält, was ``fahrzeug_bauen.py --draufsicht <ordner>
--vorschau <ordner>`` geschrieben hat (``<key>_oben.png``, ``<key>_vorn.png``,
``<key>_hinten.png``). Je Fahrzeug entsteht ``<key>_vergleich.png``:

* links oben das Sprite, so zugeschnitten wie im Spiel (``src/core/lack.py``,
  größtes zusammenhängendes Rechteck mit Alpha > 50) und auf Länge × Breite
  aus ``data/vehicles/<key>.json`` skaliert,
* darunter die Draufsicht des Modells im selben Maßstab,
* darunter das Sprite halbtransparent mit dem Umriss des Modells (grün) und
  des Sprites (rot),
* rechts die beiden 3/4-Ansichten.

Dazu die Deckung der Silhouetten (IoU) auf der Konsole.

Mit ``--profil`` statt des Vergleichs: Breitenverlauf und Lage der dunklen
Glasflächen aus dem Sprite messen und als Vorschlag für ``fahrzeuge.json``
ausgeben (``breite``-Kurve, Kabinenenden, Scheibenkanten).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import numpy as np  # noqa: E402
import pygame  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
M_PER_PX = 0.08
PX_PRO_M = 125          # wie DRAUFSICHT_PX_PRO_M in fahrzeug_bauen.py
RAND_M = 0.3            # wie DRAUFSICHT_RAND_M


def masse(key: str) -> tuple[float, float]:
    with open(WURZEL / "data" / "vehicles" / f"{key}.json", encoding="utf-8") as fh:
        d = json.load(fh)
    return d["height_px"] * M_PER_PX, d["width_px"] * M_PER_PX


def sprite_roh(key: str) -> Image.Image:
    """Zuschnitt wie ``lack.roh_sprite``."""
    name = key.capitalize()
    pfad = WURZEL / "data" / "vehicles" / f"{name}.png"
    surf = pygame.image.load(str(pfad))
    ecke = surf.get_at((0, 0))
    if ecke.a == 255:
        surf.set_colorkey(ecke)
        gebacken = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        gebacken.blit(surf, (0, 0))
        surf = gebacken
    m = pygame.mask.from_surface(surf, threshold=50)
    kaesten = m.get_bounding_rects()
    r = sorted(kaesten, key=lambda q: q.width * q.height, reverse=True)[0]
    zuschnitt = pygame.Surface(r.size, pygame.SRCALPHA)
    zuschnitt.blit(surf, (0, 0), r)
    daten = pygame.image.tobytes(zuschnitt, "RGBA")
    return Image.frombytes("RGBA", zuschnitt.get_size(), daten)


def sprite_skaliert(key: str) -> Image.Image:
    """Sprite auf Leinwand in Größe der Draufsicht, Mitte auf Mitte."""
    L, B = masse(key)
    roh = sprite_roh(key)
    w, h = round(L * PX_PRO_M), round(B * PX_PRO_M)
    s = roh.resize((w, h), Image.LANCZOS)
    lw, lh = round((L + 2 * RAND_M) * PX_PRO_M), round((B + 2 * RAND_M) * PX_PRO_M)
    leinwand = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    leinwand.alpha_composite(s, ((lw - w) // 2, (lh - h) // 2))
    return leinwand


def auf_grund(bild: Image.Image, farbe=(150, 150, 150)) -> Image.Image:
    g = Image.new("RGBA", bild.size, (*farbe, 255))
    g.alpha_composite(bild)
    return g.convert("RGB")


def umriss(alpha: np.ndarray) -> np.ndarray:
    m = alpha > 128
    rand = np.zeros_like(m)
    rand[1:-1, 1:-1] = m[1:-1, 1:-1] & ~(m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:])
    # etwas dicker
    d = rand.copy()
    d[1:, :] |= rand[:-1, :]
    d[:, 1:] |= rand[:, :-1]
    return d


def vergleichen(key: str, render: Path, ausgabe: Path) -> float:
    sp = sprite_skaliert(key)
    oben_pfad = render / f"{key}_oben.png"
    ob = Image.open(oben_pfad).convert("RGBA")
    if ob.size != sp.size:
        ob = ob.resize(sp.size, Image.LANCZOS)
    a_s = np.asarray(sp)[:, :, 3]
    a_o = np.asarray(ob)[:, :, 3]
    ms, mo = a_s > 128, a_o > 128
    iou = float((ms & mo).sum() / max(1, (ms | mo).sum()))

    ueber = np.asarray(auf_grund(sp, (40, 40, 40))).astype(np.float32)
    ueber = ueber * 0.55 + 40
    ueber[umriss(a_s)] = (255, 60, 60)
    ueber[umriss(a_o)] = (60, 255, 90)
    ueber = Image.fromarray(ueber.clip(0, 255).astype(np.uint8))

    w, h = sp.size
    bilder = [auf_grund(sp), auf_grund(ob), ueber]
    rechts = []
    for n in ("vorn", "hinten"):
        p = render / f"{key}_{n}.png"
        if p.exists():
            v = Image.open(p).convert("RGB")
            v = v.resize((round(v.width * 1.5 * h / v.height), round(1.5 * h)), Image.LANCZOS)
            rechts.append(v)
    rb = max([r.width for r in rechts], default=0)
    gesamt = Image.new("RGB", (w + rb + 10, max(3 * h + 20, sum(r.height for r in rechts) + 10)),
                       (30, 30, 30))
    for i, b in enumerate(bilder):
        gesamt.paste(b, (0, i * (h + 10)))
    y = 0
    for r in rechts:
        gesamt.paste(r, (w + 10, y))
        y += r.height + 10
    zeichnen = ImageDraw.Draw(gesamt)
    zeichnen.text((6, 2 * (h + 10) + 4), f"{key}  IoU={iou:.3f}", fill=(255, 255, 255))
    ausgabe.mkdir(parents=True, exist_ok=True)
    gesamt.save(ausgabe / f"{key}_vergleich.png")
    return iou


# ---------------------------------------------------------------------------
# Profil aus dem Sprite
# ---------------------------------------------------------------------------

#: Stützstellen der vorgeschlagenen ``breite``-Kurve: dicht an den Enden.
STUETZEN = [0.0, 0.006, 0.015, 0.03, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4,
            0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.925, 0.95, 0.97,
            0.985, 0.994, 1.0]


def _laeufe(maske: np.ndarray):
    """Zusammenhängende True-Bereiche als (Anfang, Ende)."""
    d = np.diff(np.concatenate([[0], maske.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def profil(key: str) -> dict:
    """Grundriss aus dem Sprite messen.

    u läuft wie in ``fahrzeuge.json`` von 0 (Heck, links im Bild) bis 1
    (Front), v von -1 (unten im Bild, rechte Wagenseite) bis +1.

    * ``breite``: halbe Karosseriebreite je u. Reifen, die seitlich unter der
      Karosserie hervorschauen, werden als dunkler Lauf an der Außenkante
      erkannt und abgezogen; Spiegel als kurze Ausreißer über einen gleitenden
      Median entfernt.
    * ``reifen``: u-Bereiche und äußeres v der sichtbaren Reifen.
    * ``spiegel``: u-Bereich und äußeres v der Spiegel.
    """
    roh = sprite_roh(key)
    w = 1000
    h = max(1, round(roh.height * w / roh.width))
    s = np.asarray(roh.resize((w, h), Image.LANCZOS)).astype(np.float32)
    a = s[:, :, 3] > 128
    rgb = s[:, :, :3]
    hell = rgb.mean(axis=2)
    satt = rgb.max(axis=2) - rgb.min(axis=2)
    dunkel = (hell < 70) & (satt < 40)
    oben, unten, roh_o, roh_u = [], [], [], []
    reifen_o, reifen_u = np.zeros(w, bool), np.zeros(w, bool)
    lauf_min = int(0.02 * h)
    for x in range(w):
        ys = np.nonzero(a[:, x])[0]
        if len(ys) == 0:
            oben.append(h / 2)
            unten.append(h / 2)
            roh_o.append(h / 2)
            roh_u.append(h / 2)
            continue
        t, b = ys.min(), ys.max()
        roh_o.append(t)
        roh_u.append(b)
        # dunkler Lauf von außen nach innen
        r = 0
        while t + r < h and dunkel[t + r, x]:
            r += 1
        if r >= lauf_min:
            reifen_o[x] = True
            t = t + r
        r = 0
        while b - r >= 0 and dunkel[b - r, x]:
            r += 1
        if r >= lauf_min:
            reifen_u[x] = True
            b = b - r
        oben.append(t)
        unten.append(b)
    halb = (np.array(unten) - np.array(oben)) / h        # halbe Breite in v
    k = int(w * 0.035)
    pad = np.pad(halb, k, mode="edge")
    med = np.array([np.median(pad[i:i + 2 * k + 1]) for i in range(w)])
    # Nur dort den Median nehmen, wo die Rohbreite deutlich darüber liegt
    # (Spiegel); sonst die Rohbreite, damit Ecken scharf bleiben.
    koerper = np.where(halb > med + 0.015, med, halb)
    spiegel = []
    for x0, x1 in _laeufe(halb > med + 0.03):
        if 3 < x1 - x0 < w * 0.08:
            vo = 1 - 2 * min(roh_o[x0:x1]) / h
            vu = 2 * max(roh_u[x0:x1]) / h - 1
            spiegel.append({"u": [round(x0 / w, 3), round(x1 / w, 3)],
                            "v": round(float(max(vo, vu)), 3)})
    reifen = []
    for maske, seite in ((reifen_o, 1), (reifen_u, -1)):
        for x0, x1 in _laeufe(maske):
            if x1 - x0 < w * 0.05:
                continue
            if seite > 0:
                v = 1 - 2 * min(roh_o[x0:x1]) / h
            else:
                v = 2 * max(roh_u[x0:x1]) / h - 1
            reifen.append({"seite": seite, "u": [round(x0 / w, 3), round(x1 / w, 3)],
                           "mitte": round((x0 + x1) / 2 / w, 3), "v": round(float(v), 3)})
    mitte_off = float(np.median((np.array(oben) + np.array(unten)) / 2 / h - 0.5))
    kurve = []
    for u in STUETZEN:
        x = min(w - 1, int(round(u * (w - 1))))
        lo, hi = max(0, x - 2), min(w, x + 3)
        kurve.append([u, round(float(np.max(koerper[lo:hi])), 3)])
    return {"breite": kurve, "reifen": reifen, "spiegel": spiegel,
            "mittenversatz_v": round(-2 * mitte_off, 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", type=Path)
    ap.add_argument("--ausgabe", type=Path)
    ap.add_argument("--fahrzeug", default="alle")
    ap.add_argument("--profil", action="store_true")
    a = ap.parse_args()
    pygame.init()
    alle = ["rookie", "rookie_2", "rookie_3", "limousine", "limousine_2", "limousine_3",
            "supercar", "supercar_2", "supercar_3", "drifter", "drifter_2", "drifter_3",
            "electric", "electric_2", "electric_3"]
    keys = alle if a.fahrzeug == "alle" else a.fahrzeug.split(",")
    for key in keys:
        if a.profil:
            print(key, json.dumps(profil(key)))
        else:
            iou = vergleichen(key, a.render, a.ausgabe)
            print(f"{key:12s} IoU={iou:.3f}")


if __name__ == "__main__":
    main()
