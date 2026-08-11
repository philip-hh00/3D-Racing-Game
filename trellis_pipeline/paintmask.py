"""Lackmaske aus der Base-Color-Textur.

Portierung von ``src/core/lack.py`` aus dem 2D-Spiel (Funktion ``_maske_arr``).
Bewusst dieselbe Rechnung und dieselben Kennwerte: das Fahrzeuglabor stimmt die
Werte im ``paint``-Block am 2D-Sprite ab, und was dort als Lack gilt, muss auch
in 3D als Lack gelten. Wuerde hier ein eigenes Verfahren stehen, haetten
dieselben Zahlen zwei verschiedene Bedeutungen.

Zwei Unterschiede zur 2D-Fassung, beide durch die Datenlage erzwungen:

* Gerechnet wird auf ``numpy``-Arrays aus Pillow statt auf ``pygame``-Surfaces -
  hier laeuft kein Spiel, und pygame nur fuer den Array-Zugriff mitzuschleppen
  waere unsinnig.
* Base-Color-Texturen aus TRELLIS kommen oft als RGB ohne Alphakanal. Fehlt er,
  gilt jedes Texel als sichtbar. Der 2D-Weg konnte sich auf freigestellte
  Sprites verlassen, eine UV-Textur hat keinen Hintergrund zum Freistellen.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

#: Vorgabewerte des paint-Blocks, wortgleich zu lack.PAINT_VORGABE. Fehlt der
#: Block, gilt ``verfahren: "aus"`` - das Fahrzeug bietet dann nur Werkslack an.
PAINT_VORGABE: dict[str, Any] = {
    "verfahren": "aus",
    "saettigungsschwelle": 0.25,
    "referenzfarbe": None,
    "farbtoleranz": 0.18,
    "helligkeit_min": 0.05,
    "helligkeit_max": 0.95,
    "kantenweichheit": 1.5,
    "deckkraft": 1.0,
}

VERFAHREN = ("aus", "saettigung", "dominant")

#: Laenge der Raumdiagonale des RGB-Wuerfels, sqrt(3) * 255. Die Farbtoleranz
#: ist ein Anteil davon - so bedeutet 0,3 dasselbe wie im 2D-Spiel.
_RGB_DIAGONALE = 441.673

#: Ab diesem Alphawert gilt ein Texel als sichtbar (wie in lack.py).
_ALPHA_SICHTBAR = 40


def auffuellen(roh: Any) -> dict[str, Any]:
    """Einen paint-Block auf vollstaendige, plausible Werte bringen."""
    werte = dict(PAINT_VORGABE)
    if isinstance(roh, dict):
        for k in PAINT_VORGABE:
            if k in roh:
                werte[k] = roh[k]
    if werte.get("verfahren") not in VERFAHREN:
        werte["verfahren"] = "aus"
    return werte


def paint_werte(vehicle_key: str, vehicles_dir: str | Path) -> dict[str, Any]:
    """paint-Block aus ``<vehicles_dir>/<key>.json``.

    Direkt aus der Datei gelesen und nicht ueber den Spielcode: das zoege pygame
    und pymunk herein, obwohl es um acht Zahlen geht.
    """
    pfad = Path(vehicles_dir) / f"{vehicle_key}.json"
    try:
        with open(pfad, encoding="utf-8") as f:
            roh = json.load(f).get("paint")
    except (OSError, ValueError):
        roh = None
    return auffuellen(roh)


def _kastenfilter(a: np.ndarray, k: int) -> np.ndarray:
    """Separabler Kastenfilter ueber Teilsummen - O(n) statt O(n*k^2).

    Uebernommen aus lack.py; bei 2K-Texturen ist der Unterschied derselbe wie
    dort bei den grossen Sprites.
    """
    if k < 1:
        return a
    fenster = 2 * k + 1
    erg = a
    for achse in (0, 1):
        pad = np.pad(erg, [(k + 1, k) if i == achse else (0, 0) for i in range(2)],
                     mode="edge")
        summe = np.cumsum(pad, axis=achse)
        vorne = np.take(summe, np.arange(fenster, summe.shape[achse]), axis=achse)
        hinten = np.take(summe, np.arange(0, summe.shape[achse] - fenster), axis=achse)
        erg = (vorne - hinten) / float(fenster)
    return erg


def _arrays(bild: Image.Image) -> tuple[np.ndarray, np.ndarray]:
    """RGB als float32 und Alpha. Ohne Alphakanal gilt alles als sichtbar."""
    if bild.mode == "RGBA":
        daten = np.asarray(bild, dtype=np.float32)
        return daten[..., :3], daten[..., 3]
    rgb = np.asarray(bild.convert("RGB"), dtype=np.float32)
    return rgb, np.full(rgb.shape[:2], 255.0, dtype=np.float32)


def dominante_farbe(bild: Image.Image) -> tuple[int, int, int]:
    """Haeufigste sichtbare Farbe - der Rueckfall fuer die Referenzfarbe."""
    return _dominante_arr(*_arrays(bild))


def _dominante_arr(rgb: np.ndarray, alpha: np.ndarray) -> tuple[int, int, int]:
    sichtbar = rgb[alpha > _ALPHA_SICHTBAR]
    if sichtbar.size == 0:
        return (128, 128, 128)
    grob = (sichtbar // 16).astype(np.int32)
    schluessel = grob[:, 0] * 1024 + grob[:, 1] * 32 + grob[:, 2]
    werte, anzahl = np.unique(schluessel, return_counts=True)
    top = int(werte[anzahl.argmax()])
    return (int((top // 1024) * 16 + 8), int(((top // 32) % 32) * 16 + 8),
            int((top % 32) * 16 + 8))


def maske(bild: Image.Image, werte: dict) -> np.ndarray:
    """Maskengewichte 0…1 je Texel.

    Das **Helligkeitsfenster** gilt in beiden Verfahren. Es ist der Hebel gegen
    mitgezaehlte Scheiben und Reifen: bei einem grauen Auto mit grauen Fenstern
    trennt keine Farbschwelle die beiden, ein Helligkeitsunterschied schon.
    """
    rgb, alpha = _arrays(bild)
    sichtbar = alpha > _ALPHA_SICHTBAR
    lum = (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]) / 255.0

    verfahren = werte.get("verfahren", "aus")
    if verfahren == "saettigung":
        hoch = rgb.max(axis=2)
        tief = rgb.min(axis=2)
        sat = np.where(hoch > 0, (hoch - tief) / np.maximum(hoch, 1e-6), 0.0)
        treffer = sat >= float(werte.get("saettigungsschwelle", 0.25))
    elif verfahren == "dominant":
        ref = werte.get("referenzfarbe")
        if not ref:
            ref = _dominante_arr(rgb, alpha)
        abweichung = rgb - np.array(ref[:3], dtype=np.float32)
        # Quadratisch vergleichen - die Wurzel je Texel bringt nichts.
        grenze = float(werte.get("farbtoleranz", 0.18)) * _RGB_DIAGONALE
        treffer = np.einsum("...i,...i->...", abweichung, abweichung) <= grenze * grenze
    else:
        treffer = np.zeros(sichtbar.shape, dtype=bool)

    treffer &= (sichtbar
                & (lum >= float(werte.get("helligkeit_min", 0.0)))
                & (lum <= float(werte.get("helligkeit_max", 1.0))))

    gewicht = treffer.astype(np.float32)
    weich = float(werte.get("kantenweichheit", 0.0))
    if weich > 0:
        gewicht = _kastenfilter(gewicht, max(1, int(round(weich))))
        gewicht *= sichtbar          # nie ueber die Silhouette hinaus verschmieren
    return np.clip(gewicht, 0.0, 1.0)


def als_png(gewicht: np.ndarray) -> Image.Image:
    """Maske als 8-Bit-Graustufenbild - weiss ist Lack."""
    return Image.fromarray(
        np.clip(gewicht * 255.0, 0, 255).astype(np.uint8), mode="L")
