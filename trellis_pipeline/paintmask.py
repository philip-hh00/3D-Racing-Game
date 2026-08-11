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
    rgb, alpha = _arrays(bild)
    return _dominante_arr(rgb, alpha > _ALPHA_SICHTBAR)


def _dominante_arr(rgb: np.ndarray, gilt: np.ndarray) -> tuple[int, int, int]:
    """Haeufigste Farbe unter den geltenden Texeln.

    ``gilt`` ist bereits die fertige Auswahl - bei einem Atlas also inklusive
    UV-Abdeckung. Ohne das waere die dominante Farbe womoeglich die des
    unbenutzten Atlasbereichs, der oft groesser ist als das Fahrzeug.
    """
    auswahl = rgb[gilt]
    if auswahl.size == 0:
        return (128, 128, 128)
    grob = (auswahl // 16).astype(np.int32)
    schluessel = grob[:, 0] * 1024 + grob[:, 1] * 32 + grob[:, 2]
    werte, anzahl = np.unique(schluessel, return_counts=True)
    top = int(werte[anzahl.argmax()])
    return (int((top // 1024) * 16 + 8), int(((top // 32) % 32) * 16 + 8),
            int((top % 32) * 16 + 8))


#: Wieviele Texel Saum die Abdeckung ueber die Dreiecke hinaus bekommt.
#: Der Texturierer laesst um jeden Chart einen Rand mitlaufen, damit beim
#: Filtern nichts Fremdes hereingezogen wird. Dieser Rand gehoert zum Lack.
ABDECKUNG_SAUM = 2

#: Abtaststufen. Ein Dreieck kommt in die erste Stufe, deren Ordnung mindestens
#: seiner laengsten Kante in Texeln entspricht - so faellt zwischen den
#: Abtastpunkten nie mehr als ein Texel durch. Was groesser ist als die letzte
#: Stufe, wird einzeln rasterisiert.
ABDECKUNG_STUFEN = (2, 4, 8, 16, 32)

#: Wieviele Dreiecke auf einmal abgetastet werden. 460.000 Dreiecke mal 15
#: Punkte auf einen Schlag waeren einige hundert Megabyte.
ABDECKUNG_BLOCK = 100_000


def _baryzentrisch(ordnung: int) -> np.ndarray:
    """Gleichmaessige Punkte im Dreieck, als Gewichte der drei Ecken."""
    punkte = [(i / ordnung, j / ordnung, (ordnung - i - j) / ordnung)
              for i in range(ordnung + 1) for j in range(ordnung + 1 - i)]
    return np.asarray(punkte, dtype=np.float32)


def _abtasten(ecken: np.ndarray, ordnung: int, breite: int, hoehe: int,
              deck: np.ndarray) -> None:
    """Dreiecke gleicher Groessenordnung auf einen Schlag abtasten."""
    gewichte = _baryzentrisch(ordnung)
    for start in range(0, len(ecken), ABDECKUNG_BLOCK):
        block = ecken[start:start + ABDECKUNG_BLOCK]            # (n, 3, 2)
        punkte = np.einsum("kd,ndc->nkc", gewichte, block)      # (n, k, 2)
        _eintragen(punkte[..., 0].ravel(), punkte[..., 1].ravel(),
                   breite, hoehe, deck)


def _eintragen(u: np.ndarray, v: np.ndarray, breite: int, hoehe: int,
               deck: np.ndarray) -> None:
    # v = 0 liegt in glTF unten, Zeile 0 eines Bildes liegt oben.
    spalte = np.clip(np.rint(u * (breite - 1)), 0, breite - 1).astype(np.int32)
    zeile = np.clip(np.rint((1.0 - v) * (hoehe - 1)), 0, hoehe - 1).astype(np.int32)
    deck[zeile, spalte] = True


def _rasterisieren(ecken: np.ndarray, breite: int, hoehe: int,
                   deck: np.ndarray) -> None:
    """Einzeln und vollstaendig - fuer die wenigen sehr grossen Dreiecke.

    Ueber das umschliessende Rechteck und einen baryzentrischen Test. Fuer
    tausende kleine Dreiecke waere das viel zu langsam, fuer eine Handvoll
    grosse ist es genau richtig und exakt.
    """
    for dreieck in ecken:
        x = dreieck[:, 0] * (breite - 1)
        y = (1.0 - dreieck[:, 1]) * (hoehe - 1)
        x0, x1 = int(np.floor(x.min())), int(np.ceil(x.max()))
        y0, y1 = int(np.floor(y.min())), int(np.ceil(y.max()))
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, breite - 1), min(y1, hoehe - 1)
        if x1 < x0 or y1 < y0:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        flaeche = ((x[1] - x[0]) * (y[2] - y[0]) - (x[2] - x[0]) * (y[1] - y[0]))
        if abs(flaeche) < 1e-12:
            continue
        a = ((x[1] - gx) * (y[2] - gy) - (x[2] - gx) * (y[1] - gy)) / flaeche
        b = ((x[2] - gx) * (y[0] - gy) - (x[0] - gx) * (y[2] - gy)) / flaeche
        drin = (a >= -1e-6) & (b >= -1e-6) & (a + b <= 1 + 1e-6)
        deck[y0:y1 + 1, x0:x1 + 1] |= drin


def abdeckung(uv: np.ndarray, faces: np.ndarray, groesse: tuple[int, int],
              saum: int = ABDECKUNG_SAUM) -> np.ndarray:
    """Welche Texel der Textur ueberhaupt auf dem Modell landen.

    xatlas packt das Fahrzeug in tausende Flicken und laesst dazwischen grosse
    Teile des Atlas frei - beim rookie sind es rund 8000 Charts auf 2048 x 2048.
    Was in den Zwischenraeumen steht, ist Fuellmaterial und wird nie gezeichnet.
    Eine Lackmaske, die das ganze Bild ansieht, zaehlt es trotzdem mit; im
    ersten Lauf waren so 32,7 Prozent der Texturflaeche als Lack markiert,
    ueberzogen mit Sprenkeln aus dem unbenutzten Bereich.

    Abgetastet statt exakt rasterisiert: die Dreiecke sind im Atlas winzig -
    460.000 Dreiecke auf 4,2 Millionen Texel sind im Mittel neun Texel pro
    Dreieck -, und 15 baryzentrische Punkte je Dreieck treffen davon jedes.
    Der Saum schliesst, was zwischen den Abtastpunkten durchfaellt, und bildet
    zugleich den Rand ab, den der Texturierer um jeden Chart legt.

    ``groesse`` ist (Breite, Hoehe) wie bei Pillow; zurueck kommt ein Feld in
    Bildanordnung, also (Hoehe, Breite).
    """
    breite, hoehe = int(groesse[0]), int(groesse[1])
    deck = np.zeros((hoehe, breite), dtype=bool)
    faces = np.asarray(faces)
    if faces.size == 0 or uv is None or len(uv) == 0:
        return deck

    uv = np.asarray(uv, dtype=np.float32)
    alle = uv[faces]                                            # (F, 3, 2)

    # Laengste Kante je Dreieck in Texeln - danach richtet sich die Abtastdichte.
    in_texeln = alle * np.array([breite - 1, hoehe - 1], dtype=np.float32)
    kanten = np.linalg.norm(
        in_texeln - in_texeln[:, [1, 2, 0], :], axis=2).max(axis=1)

    offen = np.ones(len(alle), dtype=bool)
    for stufe in ABDECKUNG_STUFEN:
        dran = offen & (kanten <= stufe)
        if dran.any():
            _abtasten(alle[dran], stufe, breite, hoehe, deck)
            offen &= ~dran
    if offen.any():
        _rasterisieren(alle[offen], breite, hoehe, deck)

    if saum > 0:
        from scipy import ndimage
        deck = ndimage.binary_dilation(
            deck, structure=np.ones((2 * saum + 1, 2 * saum + 1), dtype=bool))
    return deck


def abdeckung_fuer(mesh, groesse: tuple[int, int]) -> np.ndarray | None:
    """Abdeckung direkt aus einem Mesh. ``None``, wenn es keine UVs hat."""
    uv = getattr(getattr(mesh, "visual", None), "uv", None)
    if uv is None or len(uv) == 0:
        return None
    return abdeckung(np.asarray(uv), np.asarray(mesh.faces), groesse)


def maske(bild: Image.Image, werte: dict,
          abdeckung: np.ndarray | None = None) -> np.ndarray:
    """Maskengewichte 0…1 je Texel.

    Das **Helligkeitsfenster** gilt in beiden Verfahren. Es ist der Hebel gegen
    mitgezaehlte Scheiben und Reifen: bei einem grauen Auto mit grauen Fenstern
    trennt keine Farbschwelle die beiden, ein Helligkeitsunterschied schon.

    ``abdeckung`` begrenzt das Ergebnis auf die Texel, die tatsaechlich auf dem
    Modell landen - siehe :func:`abdeckung`. Ohne sie wird das ganze Bild
    ausgewertet, was bei einem freigestellten 2D-Sprite richtig ist, bei einem
    UV-Atlas aber nicht.
    """
    rgb, alpha = _arrays(bild)
    sichtbar = alpha > _ALPHA_SICHTBAR
    if abdeckung is not None:
        sichtbar = sichtbar & abdeckung
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
            ref = _dominante_arr(rgb, sichtbar)
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


#: Wie stark Unmaskiertes im Kontrollbild abgedunkelt wird.
KONTROLLE_DUNKEL = 0.18


def kontrollbild(bild: Image.Image, gewicht: np.ndarray) -> Image.Image:
    """Die Textur mit abgedunkeltem Nicht-Lack.

    Die reine Schwarzweissmaske ist irrefuehrend: xatlas zerlegt das Fahrzeug
    in tausende Charts, eine durchgehende Motorhaube erscheint darin als
    tausend kleine Inseln. Das sieht nach Rauschen aus, ist aber die
    Atlas-Struktur. Auf der Textur liegend ist sofort erkennbar, ob die roten
    Flaechen echten Karosserieteilen folgen.
    """
    rgb = np.asarray(bild.convert("RGB"), dtype=np.float32)
    fest = gewicht[..., None] > 0.5
    return Image.fromarray(
        np.where(fest, rgb, rgb * KONTROLLE_DUNKEL).astype(np.uint8), mode="RGB")


def vereinzelt(gewicht: np.ndarray) -> float:
    """Anteil der Maskentexel, die kaum maskierte Nachbarn haben.

    Das Mass fuer echtes Rauschen. Eine saubere Flaeche liegt nahe null, weil
    fast jeder Texel von seinesgleichen umgeben ist; Salz und Pfeffer treibt
    den Wert nach oben. Am rookie sind es 0,8 Prozent - die Maske ist also
    zusammenhaengend, auch wenn sie zerstueckelt aussieht.
    """
    from scipy import ndimage

    fest = gewicht > 0.5
    if not fest.any():
        return 0.0
    nachbarn = ndimage.uniform_filter(fest.astype(np.float32), size=3)
    return float((fest & (nachbarn < 0.4)).sum()) / float(fest.sum())
