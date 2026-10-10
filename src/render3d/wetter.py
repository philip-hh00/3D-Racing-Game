"""Wetter je Rennen: Trocken oder Regen.

Nur Zahlen und numpy — kein OpenGL, kein pygame (siehe ``VEREINBARUNGEN.md``).
Hier steht, wie das Wetter heißt, wie es aussieht (die Zahlen für die Szene) und
was es mit der Fahrphysik macht (:data:`GRIFF_FAKTOR`, :func:`wirksame_config`).

**Trocken ist die heutige Welt.** Die Vorgabe :data:`TROCKEN` ändert nichts:
kein Zweig im Shader, kein Teilchen, kein Faktor auf die Physik —
``tests/test_wetter.py`` prüft das gegen die alten Werte. Wer hier etwas für den
trockenen Fall „verbessert“, verändert jedes Bild.

**Regen.** Bedeckter Himmel (dunkler, entsättigt, Sonne klein und kühl),
leichter Dunst, nasse Fahrbahn (dunklere Farbe, glatter, kräftigere
Spiegelung, ein paar Pfützen), Regenstreifen um die Kamera und Gischt hinter den
Autos. Dazu weniger Haftung für alle: **das ist Physik, nicht Optik** und gilt
für Menschen und KI gleich (:func:`wirksame_config`).
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

#: Die Wetter, wie sie in Lobby, Profil und Lobbyeinstellungen heißen
#: (Schlüssel, deutsch — übersetzt wird erst bei der Anzeige).
NAMEN = ("Trocken", "Regen")
STANDARD = "Trocken"
#: Schlüssel in den Lobbyeinstellungen und im Profil.
SCHLUESSEL = "wetter"

_ALIASE = {"trocken": "Trocken", "dry": "Trocken", "sonne": "Trocken", "sun": "Trocken",
           "regen": "Regen", "rain": "Regen", "wet": "Regen", "nass": "Regen", "rainy": "Regen"}

#: Haftung der Reifen im Regen, als Faktor auf ``config.grip`` (Seitenführung und
#: Traktion). Die Bremse gibt entsprechend nach: ohne Haftung kein Verzögern.
GRIFF_FAKTOR = {"Trocken": 1.0, "Regen": 0.80}
BREMS_FAKTOR = {"Trocken": 1.0, "Regen": 0.82}


def normiere(name) -> str:
    """Ein Wetter aus beliebiger Eingabe; unbekannt oder fehlend ist ``"Trocken"``.

    Eine Lobby von vor 1.1.0 kennt das Feld nicht, ein Server reicht
    Unbekanntes nie weiter, und ein Profil kann von Hand verbogen sein: in
    allen Fällen kommt Trocken heraus, nie ein Fehler.
    """
    if isinstance(name, str):
        return _ALIASE.get(name.strip().lower(), STANDARD)
    return STANDARD


def griff_faktor(name) -> float:
    """Faktor auf Haftung (Quer und Längs) für dieses Wetter."""
    return GRIFF_FAKTOR[normiere(name)]


def brems_faktor(name) -> float:
    return BREMS_FAKTOR[normiere(name)]


def wirksame_config(config, name):
    """Die Fahrzeugwerte, mit denen bei diesem Wetter gefahren wird.

    Trocken gibt ``config`` selbst zurück (dasselbe Objekt, kein Byte anders).
    Sonst eine Kopie mit weniger ``grip`` und ``brake_force``. Physik **und**
    KI (Tempoprofil, Lenkgrenze) lesen diese Kopie, deshalb passt sich die KI
    von selbst an: niedrigeres Kurventempo, früheres Bremsen. Die JSON-Dateien
    unter ``data/vehicles`` bleiben unberührt (sie sind für Online
    geprüfsummt).
    """
    name = normiere(name)
    if name == STANDARD:
        return config
    return dataclasses.replace(config, grip=float(config.grip) * GRIFF_FAKTOR[name],
                               brake_force=float(config.brake_force) * BREMS_FAKTOR[name])


@dataclass(frozen=True)
class Wetter:
    """Wie ein Wetter aussieht (Zahlen für ``Rennszene``)."""

    name: str
    #: Faktor auf Farbe und Stärke der Sonne (bedeckt: schwach und kühl) und
    #: die größte Höhe, in der sie noch steht (Grad; ``None``: keine Grenze).
    sonne_faktor: tuple = (1.0, 1.0, 1.0)
    sonne_hoehe_max_grad: float | None = None
    #: Himmel: Faktor auf die Helligkeit des Themas, Entsättigung (0 unverändert,
    #: 1 grau), Tönung, Anteil der geschlossenen Wolkendecke (0 = Bild bleibt) und
    #: deren Farbe (linear). Das Himmelsbild wird beim Laden so gewandelt.
    himmel_helligkeit: float = 1.0
    himmel_grau: float = 0.0
    himmel_tint: tuple = (1.0, 1.0, 1.0)
    wolken_decke: float = 0.0
    decke_farbe: tuple = (0.5, 0.5, 0.5)
    #: Faktoren auf Nebelfarbe und -dichte (Dunst), Bodenfarbe und den
    #: Farbverlauf des Himmels ohne Bild.
    nebel_faktor: tuple = (1.0, 1.0, 1.0)
    nebel_dichte: float = 1.0
    boden_faktor: tuple = (1.0, 1.0, 1.0)
    verlauf_faktor: tuple = (1.0, 1.0, 1.0)
    #: Faktor auf die Belichtung (die Kamera gleicht einen dunklen Tag etwas aus).
    belichtung: float = 1.0
    #: Nasse Fahrbahn: Stärke (0 trocken, 1 nass), Faktor auf die Farbe, größte
    #: Rauheit (Zielwert), Faktor auf die Spiegelung des Himmels, Anteil der
    #: Fläche mit Pfützen (0 keine).
    nass: float = 0.0
    nass_albedo: float = 1.0
    nass_rauheit: float = 1.0
    nass_spiegel: float = 1.0
    pfuetzen: float = 0.0
    #: Regenstreifen: an/aus (Stärke), Fallgeschwindigkeit (m/s), Wind (m/s, x, y).
    regen: float = 0.0
    regen_fall_m_s: float = 9.0
    regen_wind_m_s: tuple = (0.0, 0.0)
    #: Gischt hinter den Autos: Faktor auf Menge und Deckkraft.
    gischt: float = 0.0
    #: Regenrauschen (Lautstärke, 0 aus).
    rauschen: float = 0.0

    @property
    def aktiv(self) -> bool:
        """Falsch nur für Trocken: dann bleibt alles beim Alten."""
        return self.name != STANDARD


TROCKEN = Wetter(name="Trocken")

REGEN = Wetter(
    name="Regen",
    sonne_faktor=(0.34, 0.37, 0.42),
    sonne_hoehe_max_grad=32.0,
    himmel_helligkeit=0.62,
    himmel_grau=0.75,
    himmel_tint=(0.90, 0.96, 1.05),
    wolken_decke=0.8,
    decke_farbe=(0.50, 0.53, 0.58),
    nebel_faktor=(0.80, 0.84, 0.90),
    nebel_dichte=1.8,
    boden_faktor=(0.78, 0.80, 0.80),
    verlauf_faktor=(0.55, 0.58, 0.62),
    belichtung=1.15,
    nass=1.0,
    nass_albedo=0.5,
    nass_rauheit=0.35,
    nass_spiegel=1.0,
    pfuetzen=0.5,
    regen=1.0,
    regen_fall_m_s=9.0,
    regen_wind_m_s=(-1.2, 0.8),
    gischt=1.0,
    rauschen=1.0,
)

VORGABEN = {"Trocken": TROCKEN, "Regen": REGEN}


def vorgabe(name) -> Wetter:
    """Die Vorgabe zu einem Namen (mit :func:`normiere`)."""
    return VORGABEN[normiere(name)]


def _mal(a, b) -> tuple:
    return tuple(float(x) * float(y) for x, y in zip(a, b))


def umgebung_werte(w: Wetter, thema_werte: dict) -> dict:
    """Die vom Thema (und der Tageszeit) kommenden Werte nach dem Wetter umgerechnet.

    Gleiche Schlüssel wie ``tageszeit.umgebung_werte``. Trocken gibt sie
    unverändert zurück.
    """
    if not w.aktiv:
        return dict(thema_werte)
    v = dict(thema_werte)
    v["sonne_farbe"] = _mal(v["sonne_farbe"], w.sonne_faktor)
    v["himmel_helligkeit"] = float(v["himmel_helligkeit"]) * w.himmel_helligkeit
    v["nebel_farbe"] = _mal(v["nebel_farbe"], w.nebel_faktor)
    v["nebel_dichte"] = float(v["nebel_dichte"]) * w.nebel_dichte
    v["boden_farbe"] = _mal(v["boden_farbe"], w.boden_faktor)
    v["himmel_zenit"] = _mal(v["himmel_zenit"], w.verlauf_faktor)
    v["himmel_horizont"] = _mal(v["himmel_horizont"], w.verlauf_faktor)
    v["belichtung"] = float(v["belichtung"]) * w.belichtung
    return v


def sonne_gedrueckt(sonne, w: Wetter) -> np.ndarray:
    """Richtung zur Sonne, bei Bedeckung höchstens so hoch wie ``sonne_hoehe_max_grad``.

    Die Himmelsrichtung bleibt; nur die Höhe wird begrenzt (die Schatten fallen
    dann etwas länger — schwach sind sie ohnehin).
    """
    s = np.asarray(sonne, dtype=np.float64)
    s = s / np.linalg.norm(s)
    if not w.aktiv or w.sonne_hoehe_max_grad is None:
        return s
    hoehe = math.asin(max(-1.0, min(1.0, float(s[2]))))
    grenze = math.radians(w.sonne_hoehe_max_grad)
    if hoehe <= grenze:
        return s
    az = math.atan2(s[1], s[0])
    return np.array([math.cos(grenze) * math.cos(az), math.cos(grenze) * math.sin(az), math.sin(grenze)])


def himmel_bild(bild_enc: np.ndarray, w: Wetter) -> np.ndarray:
    """Das Himmelsbild bei bedecktem Himmel: grau, flach, die Sonne verschwunden.

    ``bild_enc``: ``(h, w, 3)`` float32 in der Kodierung des Himmelsbildes
    (linear hoch 1/2,2; Zeile 0 oben), wie ``tageszeit.himmel_bild`` oder das
    geladene Bild sie liefern. Ergebnis in derselben Kodierung. Einmal beim
    Laden gerechnet, im Bild kostet es nichts.

    Die Struktur der Wolken bleibt als leises Relief erhalten (aus der
    weichgezeichneten Helligkeit des Bildes), der blaue Himmel und die
    Sonnenscheibe gehen in eine gleichmäßige Decke über, nach oben etwas
    dunkler, am Horizont heller.
    """
    lin = np.maximum(np.asarray(bild_enc, dtype=np.float32), 0.0) ** 2.2
    h = lin.shape[0]
    lum = (lin * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=2)
    # Relief aus einer weichgezeichneten Helligkeit: nur die groben Wolken, ohne Sonne.
    lum = np.minimum(lum, float(np.percentile(lum, 85)))
    try:
        from PIL import Image, ImageFilter
        klein = Image.fromarray(np.clip(lum / max(float(lum.max()), 1e-6) * 255.0, 0, 255).astype(np.uint8))
        radius = max(2.0, lum.shape[1] / 90.0)
        weich = np.asarray(klein.filter(ImageFilter.GaussianBlur(radius)), dtype=np.float32) / 255.0
    except Exception:                                    # pragma: no cover - ohne PIL
        weich = lum / max(float(lum.max()), 1e-6)
    relief = (weich - float(weich.mean())) / max(float(weich.std()), 1e-4)
    e = (0.5 - (np.arange(h) + 0.5) / h) * math.pi        # Höhenwinkel je Zeile
    hoch = np.clip(np.sin(e), 0.0, 1.0)[:, None]
    verlauf = 1.0 - 0.28 * hoch ** 0.7                    # zum Zenit dunkler
    decke = (np.asarray(w.decke_farbe, dtype=np.float32)[None, None, :]
             * (verlauf * (1.0 + 0.16 * relief))[..., None].astype(np.float32))
    mittel = lin.sum(axis=2, keepdims=True) / 3.0
    entsaettigt = lin * (1.0 - w.himmel_grau) + mittel * w.himmel_grau
    entsaettigt = np.minimum(entsaettigt, 0.75)           # keine Sonnenscheibe, kein Weiß
    mischung = entsaettigt * (1.0 - w.wolken_decke) + decke * w.wolken_decke
    mischung = mischung * np.asarray(w.himmel_tint, dtype=np.float32)[None, None, :]
    return (np.maximum(mischung, 0.0) ** (1.0 / 2.2)).astype(np.float32)


def nass_werte(w: Wetter) -> tuple:
    """``(wetter_nass, wetter_pfuetze)`` für den Shader.

    ``wetter_nass``: Stärke, Farbfaktor, größte Rauheit, Spiegelfaktor;
    ``wetter_pfuetze``: Anteil der Pfützen, -, -, -.
    """
    if not w.aktiv or w.nass <= 0.0:
        return (0.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0)
    return ((float(w.nass), float(w.nass_albedo), float(w.nass_rauheit), float(w.nass_spiegel)),
            (float(w.pfuetzen), 0.0, 0.0, 0.0))
