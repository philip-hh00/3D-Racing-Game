"""Lackierungen: Palette, Maskenfindung, Farbauftrag, Zwischenspeicher.

Eine Lackierung ist eine **Grundfarbe × ein Finish**, als Text notiert
(``"metallic:kobaltblau"``), dazu der Sonderfall ``"werk"`` — das unveraenderte
PNG. Palette und Finish-Kennzahlen liegen in ``data/vehicles/lacke.json``,
die fahrzeugbezogenen Maskenwerte im ``paint``-Block der jeweiligen
Fahrzeug-JSON.

Zwei Dinge sind bewusst getrennt (Releaseplan D2):

* **Maske finden** — welche Pixel sind Lack? Hier unterscheiden sich die zwei
  Verfahren (Saettigungsschwelle bzw. dominante Farbe plus Toleranz).
* **Farbe auftragen** — was passiert mit diesen Pixeln? Das ist immer dasselbe:
  die Zielfarbe wird auf die vorhandene Helligkeitsverteilung gelegt.

Ohne diese Trennung waeren unbunte Zielfarben unerreichbar: eine Farbtondrehung
kann aus einem roten Auto nie ein graues machen. So funktionieren Anthrazit und
Perlweiss genauso wie Rubinrot.

Zur Arbeitsbreite: die Sprites sind bis 2816 px breit, gezeichnet werden sie mit
~90 px (Rennen) bis ~900 px (Werkstattvorschau). Umfaerben in Originalgroesse
kostet ~3,9 s pro Fahrzeug und ist damit ausgeschlossen — gerechnet wird auf
einer verkleinerten Arbeitskopie, deren Breite der Verwendungszweck bestimmt.
"""
from __future__ import annotations

import json
import os
from typing import Any

import numpy as np
import pygame

#: Werkslack — das unveraenderte PNG. Vorbelegung fuer jedes Fahrzeug und
#: Rueckfall fuer alles, was nicht aufgeloest werden kann.
WERK = "werk"

#: Arbeitsbreite fuer Rennen und Fahrzeugauswahl (dort <= ~90 px gezeichnet).
BREITE_SPIEL = 512
#: Arbeitsbreite fuer die Werkstattvorschau und die Laborseite.
BREITE_VORSCHAU = 1024

_PALETTE_PFAD = os.path.join("data", "vehicles", "lacke.json")

#: Vorgabewerte des paint-Blocks. Fehlt der Block, gilt ``verfahren: "aus"`` —
#: das Fahrzeug bietet dann nur Werkslack an.
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


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
_palette: dict | None = None


def _laden() -> dict:
    global _palette
    if _palette is None:
        try:
            with open(_PALETTE_PFAD, encoding="utf-8") as f:
                rohdaten = json.load(f)
        except Exception:
            rohdaten = {}
        farben, finishes = [], []
        for eintrag in rohdaten.get("farben", []):
            try:
                r, g, b = (int(v) for v in eintrag["rgb"][:3])
                farben.append({"key": str(eintrag["key"]),
                               "name": str(eintrag.get("name", eintrag["key"])),
                               "rgb": (max(0, min(255, r)), max(0, min(255, g)),
                                       max(0, min(255, b)))})
            except (KeyError, TypeError, ValueError):
                continue          # eine kaputte Zeile darf die Palette nicht kippen
        for eintrag in rohdaten.get("finishes", []):
            try:
                finishes.append(dict(eintrag, key=str(eintrag["key"]),
                                     name=str(eintrag.get("name", eintrag["key"]))))
            except (KeyError, TypeError):
                continue
        erste = [str(k) for k in rohdaten.get("erste_farben", [])
                 if any(f["key"] == k for f in farben)]
        # ``ki_lacke`` wird seit dem 06.08.2026 nicht mehr gelesen — die KI
        # faehrt Werkslack (siehe ki_lack). Der Schluessel ist aus lacke.json
        # entfernt; eine von Hand ergaenzte alte Datei stoert trotzdem nicht,
        # sie wird schlicht uebergangen.
        _palette = {"farben": farben, "finishes": finishes, "erste_farben": erste}
    return _palette


def erste_farben() -> list[str]:
    """Die Farben, die eine Freischaltung zuerst hergibt (§E2).

    Warm, kalt, unbunt — ein Vorgeschmack, der die Bandbreite zeigt, statt
    dreimal etwas Aehnlichem. Steht in ``lacke.json``, nicht im Code: welche
    drei es sind, ist eine Frage des Geschmacks und keine des Programms.
    """
    return list(_laden().get("erste_farben", []))


def farben() -> list[dict]:
    """Grundfarben in Anzeigereihenfolge: ``{"key", "name", "rgb"}``."""
    return list(_laden()["farben"])


#: Ab welcher Buntheit eine Grundfarbe als bunt gilt (Saettigung, 0…1).
#: Anthrazit liegt bei 0,15 und Perlweiss bei 0,02; die naechste Farbe darueber
#: ist Eisblau mit 0,61. Die Schwelle liegt also mit Absicht weit von allem weg,
#: was sie trennt — eine neue Palettenfarbe muesste schon unbunt gemeint sein,
#: um hier hineinzufallen.
BUNT_AB = 0.25


def buntheit(rgb) -> float:
    """Saettigung einer Farbe (0 = grau, 1 = voll bunt)."""
    werte = [int(k) for k in rgb[:3]]
    hoch, tief = max(werte), min(werte)
    return 0.0 if hoch <= 0 else (hoch - tief) / float(hoch)


def farben_fuer(finish_key: str) -> list[dict]:
    """Grundfarben, die in diesem Finish etwas ergeben.

    Neon lebt vom Leuchten: die Saettigung wird ans Maximum gezogen und ein Saum
    aufgehellt. An einer unbunten Farbe hat beides nichts zu greifen — „Neon
    Anthrazit" sieht aus wie Anthrazit, „Neon Perlweiss" wie Perlweiss (gemeldet
    04.08.2026). Welche Finishes es betrifft, steht in ``lacke.json``
    (``nur_bunte``) und nicht hier: es ist eine Aussage ueber das Finish.
    """
    alle = farben()
    if not (finish(finish_key) or {}).get("nur_bunte"):
        return alle
    return [f for f in alle if buntheit(f["rgb"]) >= BUNT_AB]


def finishes() -> list[dict]:
    """Finishes in Anzeigereihenfolge. ``bedingung`` ist None, wenn frei."""
    return list(_laden()["finishes"])


def farbe(key: str) -> dict | None:
    for f in _laden()["farben"]:
        if f["key"] == key:
            return f
    return None


def finish(key: str) -> dict | None:
    for f in _laden()["finishes"]:
        if f["key"] == key:
            return f
    return None


# ---------------------------------------------------------------------------
# Kennungen
# ---------------------------------------------------------------------------
def kennung(finish_key: str, farb_key: str) -> str:
    return f"{finish_key}:{farb_key}"


def zerlege(kenn: str) -> tuple[str, str] | None:
    """``"metallic:rubinrot"`` → ``("metallic", "rubinrot")``.

    None fuer Werkslack **und** fuer alles Unbekannte: ein alter Build, eine
    verstuemmelte Netznachricht oder ein von Hand verbogenes Profil sollen den
    Werkslack ergeben, nie einen Absturz oder ein leeres Auto.
    """
    if not isinstance(kenn, str) or ":" not in kenn:
        return None
    fin, _, far = kenn.partition(":")
    if finish(fin) is None or farbe(far) is None:
        return None
    return fin, far


def normalisiere(kenn: str | None) -> str:
    """Jede Eingabe auf eine gueltige Kennung abbilden (sonst Werkslack)."""
    return kenn if (isinstance(kenn, str) and zerlege(kenn) is not None) else WERK


def werte_3d(kennung):
    """Eine Lackierung (``"metallic:rubinrot"``) als Zahlen für die 3D-Szene.

    ``None`` für Werkslack: dann trägt das Modell seine eigene Farbe. Die
    Finishes übersetzen sich in Material: Metallic glänzt metallisch, Neon
    leuchtet ein wenig, Zweifarbig färbt die Zweitfarbe (Dach, Streifen,
    Livree — Material ``lack2``) hell oder dunkel, je nach Grundfarbe.
    """
    from src.render3d.rennszene import Lackwerte
    teile = zerlege(kennung) if isinstance(kennung, str) else None
    if teile is None:
        return None
    finish_key, farb_key = teile
    grund = farbe(farb_key)
    fin = finish(finish_key) or {}
    if grund is None:
        return None
    rgb = tuple(c / 255.0 for c in grund["rgb"])
    werte = Lackwerte(farbe=rgb)
    if finish_key == "metallic":
        werte.metallic, werte.rauheit = 0.55, 0.22
    elif finish_key == "neon":
        werte.rauheit, werte.leuchten = 0.28, 0.35
    elif finish_key == "zweifarbig":
        hell = sum(rgb) / 3 > 0.55
        zweit = fin.get("zweitfarbe_dunkel" if hell else "zweitfarbe_hell", [40, 40, 44])
        werte.zweitfarbe = tuple(c / 255.0 for c in zweit)
    return werte


def ki_lack(vehicle_id: int) -> str:
    """Die Lackierung des KI-Autos: **immer Werkslack** (entschieden 06.08.2026).

    Die Vorgeschichte, weil hier eine frühere Entscheidung umgedreht wird. Am
    05.08.2026 fiel auf, dass alle KI-Autos gleich aussahen: ``color_primary``
    zählt nur im programmatischen Rückfall (Releaseplan D0), also wurde die
    zugewiesene Farbe nie gezeichnet. Die Behebung gab jedem KI-Auto echten
    Lack, ausgerechnet aus seiner Fahrzeugnummer.

    Am 06.08.2026 ist das auf Wunsch zurückgenommen: die KI fährt Werkslack.
    Lackierungen sind das, was der Spieler sich erarbeitet und in der Werkstatt
    aussucht — verteilt an jedes Feld von Gegnern verliert das seinen Wert.

    **Was damit zurückkommt:** mehrere KI-Autos derselben Bauart sind wieder
    nur an ihrer Position zu unterscheiden, nicht an der Farbe. Das ist der
    bewusst in Kauf genommene Preis, kein übersehener Fehler.

    Die Signatur bleibt, obwohl die Nummer nicht mehr gebraucht wird: alle
    Aufrufer sind damit unverändert, und die Rückrichtung wäre eine Zeile. Für
    das Netz ändert sich nichts — beide Seiten rechnen weiterhin dasselbe aus,
    jetzt eben trivialerweise.
    """
    return WERK


def anzeigename(kenn: str) -> str:
    from src.core.i18n import tr
    teile = zerlege(kenn)
    if teile is None:
        return tr("Werkslack")
    fin, far = teile
    return f"{tr(finish(fin)['name'])} · {tr(farbe(far)['name'])}"


#: Welcher Zaehler hinter welchem Stichwort in ``lacke.json`` steckt.
#: Getrennt gehalten, damit in der Datei ein Wort steht und kein Feldname —
#: wer die Staffelung aendert, soll nicht wissen muessen, wie das Profil
#: intern heisst.
_ZAEHLER = {
    "rennen": lambda s: int(s.get("rennen", 0)),
    "siege": lambda s: int(s.get("siege", 0)),
    "podeste": lambda s: int(s.get("podeste", 0)),
    "gp_siege": lambda s: int(s.get("gp_siege", 0)),
    "ghosts": lambda s: len(s.get("ghosts_geschlagen", [])),
}

#: Wie der Fortschritt in der Werkstatt ausgeschrieben wird. Als Vorlage und
#: nicht als blosses Wort, weil „Rennen" allein schon als Uebersetzung fuer den
#: Spielmodus vergeben ist — Vorlagen sind eindeutig und uebersetzen sich sauber.
_VORLAGE = {
    "rennen": "{a} / {b} Rennen",
    "siege": "{a} / {b} Siege",
    "podeste": "{a} / {b} Podeste",
    "gp_siege": "{a} / {b} Serien",
    "ghosts": "{a} / {b} Ghosts",
}


def _staffel(kenn: str) -> tuple[str, int] | None:
    """(Zaehlername, noetige Zahl) — None heisst: nichts zu erfuellen."""
    teile = zerlege(normalisiere(kenn))
    if teile is None:
        return None
    fin_key, farb_key = teile
    staffel = (finish(fin_key) or {}).get("freischaltung")
    if not isinstance(staffel, dict):
        return None
    name = str(staffel.get("zaehler", ""))
    if name not in _ZAEHLER:
        return None
    # Die ersten Farben kommen frueher — die erste Belohnung soll frueh
    # kommen, das vollstaendige Set soll etwas bedeuten (§E2).
    frueh = farb_key in erste_farben()
    try:
        ziel = int(staffel.get("erste" if frueh else "alle", 0))
    except (TypeError, ValueError):
        return None
    return name, max(0, ziel)


def fortschritt(kenn: str) -> tuple[int, int]:
    """(erreicht, noetig) fuer eine Lackierung — die Zahl fuer „7 / 20".

    Ziel 0 heisst: nichts zu erfuellen, die Lackierung ist immer frei. Die
    Zahl statt nur „gesperrt", weil ohne sie niemand weiss, ob er kurz davor
    ist oder weit weg (§E2, Werkstatt-Anzeige).
    """
    hilfe = _staffel(kenn)
    if hilfe is None:
        return (0, 0)
    name, ziel = hilfe
    from src.core import statistik
    return (_ZAEHLER[name](statistik.werte()), ziel)


def fortschritt_text(kenn: str) -> str:
    """„7 / 20 Rennen" — leer, wenn es nichts zu erfuellen gibt.

    Der erreichte Wert wird am Ziel gekappt: „23 / 20" liest sich wie ein
    Fehler, obwohl es nur heisst, dass laengst freigeschaltet ist.
    """
    from src.core.i18n import tr
    hilfe = _staffel(kenn)
    if hilfe is None or hilfe[1] <= 0:
        return ""
    wert, ziel = fortschritt(kenn)
    return tr(_VORLAGE[hilfe[0]]).format(a=min(wert, ziel), b=ziel)


def ist_freigeschaltet(kenn: str) -> bool:
    """Ob die Lackierung benutzt werden darf (§E2).

    Werkslack und Standard sind immer frei; die drei Speziallacke haengen an
    Zaehlern aus dem Profil, gestaffelt nach Farbe. Welche Zahlen gelten, steht
    in ``lacke.json`` — nicht hier.

    Aus dem Quelltext gestartet ist alles frei: beim Entwickeln will niemand
    erst zwanzig Rennen fahren, um einen Lack anzusehen (§E1). Im
    ausgelieferten Buendel greift die Ausnahme nie.
    """
    from src.core import statistik
    if statistik.alles_frei():
        return True
    wert, ziel = fortschritt(kenn)
    return wert >= ziel


# ---------------------------------------------------------------------------
# Fahrzeugbezogene Maskenwerte
# ---------------------------------------------------------------------------
_paint_cache: dict[str, dict[str, Any]] = {}


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


def paint_werte(vehicle_key: str) -> dict[str, Any]:
    """paint-Block eines Fahrzeugs aus ``data/vehicles/<key>.json``.

    Bewusst direkt aus der Datei und nicht über ``VehicleFactory``: das zieht
    ``pymunk`` und die halbe Fahrzeugklasse mit herein, obwohl es hier nur um
    acht Zahlen geht. Fehlt der Block, gilt ``verfahren: "aus"`` — das Fahrzeug
    bietet dann nur Werkslack an, und das ist der heutige Stand aller 15.
    """
    if vehicle_key not in _paint_cache:
        roh = None
        try:
            with open(os.path.join("data", "vehicles", f"{vehicle_key}.json"),
                      encoding="utf-8") as f:
                roh = json.load(f).get("paint")
        except Exception:
            roh = None
        _paint_cache[vehicle_key] = auffuellen(roh)
    return dict(_paint_cache[vehicle_key])


def lackierbar(vehicle_key: str) -> bool:
    """Ob fuer dieses Fahrzeug ueberhaupt etwas anderes als Werkslack angeboten
    wird. Ohne abgestimmten paint-Block: nein."""
    return paint_werte(vehicle_key)["verfahren"] != "aus"


# ---------------------------------------------------------------------------
# Bildrechnung
# ---------------------------------------------------------------------------
def _kastenfilter(a: np.ndarray, k: int) -> np.ndarray:
    """Separabler Kastenfilter über Teilsummen — O(n) statt O(n·k²).

    Die naive Fassung (k² Verschiebungen eines Vollbild-Arrays addieren) hat bei
    2300×1000 px 3,9 s gebraucht, weil sie 25 Arrays dieser Groesse anlegt.
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


def _arrays(surf: pygame.Surface) -> tuple[np.ndarray, np.ndarray]:
    rgb = pygame.surfarray.array3d(surf).astype(np.float32)
    alpha = pygame.surfarray.array_alpha(surf).astype(np.float32)
    return rgb, alpha


def _surface(rgb: np.ndarray, alpha: np.ndarray) -> pygame.Surface:
    out = pygame.Surface(rgb.shape[:2], pygame.SRCALPHA)
    pygame.surfarray.blit_array(out, np.clip(rgb, 0, 255).astype(np.uint8))
    kanal = pygame.surfarray.pixels_alpha(out)
    kanal[:, :] = np.clip(alpha, 0, 255).astype(np.uint8)
    del kanal
    return out


def dominante_farbe(surf: pygame.Surface) -> tuple[int, int, int]:
    """Haeufigste sichtbare Farbe — der Vorschlag fuer die Referenzfarbe."""
    return _dominante_arr(*_arrays(surf))


def _dominante_arr(rgb: np.ndarray, alpha: np.ndarray) -> tuple[int, int, int]:
    sichtbar = rgb[alpha > 40]
    if sichtbar.size == 0:
        return (128, 128, 128)
    grob = (sichtbar // 16).astype(np.int32)
    schluessel = grob[:, 0] * 1024 + grob[:, 1] * 32 + grob[:, 2]
    werte, anzahl = np.unique(schluessel, return_counts=True)
    top = int(werte[anzahl.argmax()])
    return (int((top // 1024) * 16 + 8), int(((top // 32) % 32) * 16 + 8),
            int((top % 32) * 16 + 8))


def graustufen(surf: pygame.Surface) -> pygame.Surface:
    """Eine entfaerbte Kopie — Helligkeit bleibt, Farbe geht.

    Bewusst nicht ueber die Lackmaske: der Ghost soll als Ganzes grau sein,
    Scheiben und Reifen eingeschlossen. Eine Umlackierung nach Anthrazit haette
    ein *anthrazitfarbenes Auto* ergeben, kein Gespenst.
    """
    rgb, alpha = _arrays(surf)
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return _surface(np.repeat(lum[..., None], 3, axis=2), alpha)


def durchscheinend(surf: pygame.Surface, deckkraft: float) -> pygame.Surface:
    """Eine Kopie mit heruntergerechnetem Alphakanal.

    Nicht ``set_alpha``: die Oberflaeche wird vor dem Zeichnen skaliert und
    gedreht, und beides gibt den Flaechen-Alphawert nicht zuverlaessig weiter.
    Im Kanal steht er dagegen fest — er ueberlebt jede Verwandlung.
    """
    rgb, alpha = _arrays(surf)
    return _surface(rgb, alpha * max(0.0, min(1.0, float(deckkraft))))


#: Untergrenze fuer die Helligkeit eines Minimap-Punktes. Der dunkelste
#: Fahrzeuglack der Palette liegt bei RGB 24 — ein Punkt in dieser Farbe ist auf
#: der Karte nicht von seiner schwarzen Umrandung zu unterscheiden. Der Farbton
#: bleibt erhalten, nur die Helligkeit wird angehoben.
PUNKT_MIN = 110


def _aufhellen(rgb: tuple[int, int, int], mindest: int = PUNKT_MIN) -> tuple[int, int, int]:
    hoch = max(int(v) for v in rgb[:3])
    if hoch >= mindest:
        return tuple(int(v) for v in rgb[:3])          # type: ignore[return-value]
    if hoch <= 0:
        return (mindest, mindest, mindest)
    faktor = mindest / float(hoch)
    return tuple(min(255, int(round(v * faktor))) for v in rgb[:3])  # type: ignore[return-value]


_wagenfarbe_cache: dict[tuple[str, str, str], tuple[int, int, int] | None] = {}


def wagenfarbe(vehicle_key: str, visual_type: str,
               kenn: str) -> tuple[int, int, int] | None:
    """Die Farbe, die dieses Auto im Rennen **hat** — fuer Punkte und Marken.

    Lackiert: die aufgetragene Farbe. Werkslack: die haeufigste sichtbare Farbe
    des PNG, also das, was man sieht. Bis zum 05.08.2026 las die Minimap
    ``color_primary`` aus der Fahrzeug-JSON und zeigte damit den Vorgabewert des
    programmatischen Rueckfalls — eine Farbe, die seit dem 15. Sprite nirgends
    mehr vorkommt (gemeldet 30.07.2026).

    ``None`` heisst: kein Bild da. Dann faellt der Aufrufer auf
    ``color_primary`` zurueck, und das ist dort auch richtig — ohne PNG wird das
    Auto tatsaechlich in dieser Farbe gezeichnet.
    """
    kenn = normalisiere(kenn)
    schluessel = (str(vehicle_key), str(visual_type), kenn)
    if schluessel not in _wagenfarbe_cache:
        _wagenfarbe_cache[schluessel] = _wagenfarbe(vehicle_key, visual_type, kenn)
    return _wagenfarbe_cache[schluessel]


def _wagenfarbe(vehicle_key: str, visual_type: str,
                kenn: str) -> tuple[int, int, int] | None:
    teile = zerlege(kenn)
    if teile is not None and paint_werte(vehicle_key)["verfahren"] != "aus":
        ziel = _zielfarbe(*teile)
        return _aufhellen((int(ziel[0]), int(ziel[1]), int(ziel[2])))
    # Werkslack (oder ein Fahrzeug ohne abgestimmten paint-Block, das trotz
    # Kennung unveraendert gezeichnet wird): am Bild selbst nachsehen. 128 px
    # genuegen — die haeufigste Farbe haengt nicht an der Aufloesung.
    basis = arbeitskopie(visual_type, 128)
    if basis is None:
        return None
    return _aufhellen(dominante_farbe(basis))


def _maske_arr(rgb: np.ndarray, alpha: np.ndarray,
               werte: dict) -> tuple[np.ndarray, np.ndarray]:
    """Kern von :func:`maske` auf bereits ausgelesenen Arrays.

    Getrennt, weil ``pygame.surfarray`` der teuerste Posten im ganzen Weg ist:
    ``umfaerben`` hat die Oberflaeche anfangs viermal ausgelesen (zweimal selbst,
    zweimal ueber ``maske``) und damit ein Drittel der Rechenzeit verbraten.
    """
    sichtbar = alpha > 40
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
        # Quadratisch vergleichen — die Wurzel je Pixel bringt nichts.
        grenze = float(werte.get("farbtoleranz", 0.18)) * 441.673
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
    return np.clip(gewicht, 0.0, 1.0), lum


def maske(surf: pygame.Surface, werte: dict) -> tuple[np.ndarray, np.ndarray]:
    """Maskengewichte (0…1) und normalisierte Helligkeit.

    Das **Helligkeitsfenster** gilt in beiden Verfahren. Es ist der Hebel gegen
    mitgezaehlte Scheiben und Reifen: bei einem grauen Auto mit grauen Fenstern
    trennt keine Farbschwelle die beiden, ein Helligkeitsunterschied schon.
    """
    rgb, alpha = _arrays(surf)
    return _maske_arr(rgb, alpha, werte)


def _zielfarbe(fin_key: str, far_key: str) -> np.ndarray:
    """Die Farbe, die tatsaechlich aufgetragen wird.

    Fuer alle Finishes die Palettenfarbe — nur Neon zieht die Saettigung ans
    Maximum und ist damit merklich greller als der Palettenwert. Getrennt
    gehalten, weil ausser dem Auftrag auch die Minimap wissen muss, welche Farbe
    ein Auto hat (:func:`wagenfarbe`), und die beiden nie auseinanderlaufen
    duerfen.
    """
    ziel = np.array(farbe(far_key)["rgb"], dtype=np.float32)
    if fin_key == "neon":
        groesste = float(ziel.max())
        if groesste > 0:
            ziel = np.clip(ziel * (255.0 / groesste) * 0.92 + 12.0, 0, 255)
    return ziel


def _randband(fest: np.ndarray, breite: int) -> np.ndarray:
    """Schmales Band innen an der Maskengrenze (Erosion abgezogen)."""
    innen = fest
    for _ in range(max(1, breite)):
        pad = np.pad(innen, 1, mode="constant", constant_values=True)
        innen = (innen & pad[:-2, 1:-1] & pad[2:, 1:-1]
                 & pad[1:-1, :-2] & pad[1:-1, 2:])
    return fest & ~innen


def umfaerben(surf: pygame.Surface, kenn: str, werte: dict) -> pygame.Surface:
    """Eine Arbeitskopie in der Lackierung *kenn*. Werkslack gibt *surf* zurueck."""
    teile = zerlege(kenn)
    if teile is None or werte.get("verfahren", "aus") == "aus":
        return surf
    fin_key, far_key = teile
    fin = finish(fin_key) or {}
    ziel = _zielfarbe(fin_key, far_key)

    rgb, alpha = _arrays(surf)
    gewicht, lum = _maske_arr(rgb, alpha, werte)
    fest = gewicht > 0.5
    if int(fest.sum()) < 20:
        return surf               # nichts gefunden — lieber unveraendert als kaputt

    # Helligkeit am 5./95. Perzentil DER MASKENFLAECHE normalisieren, nicht des
    # ganzen Bildes: sonst verschiebt der Hintergrund die Skala.
    tief, hoch = np.percentile(lum[fest], [5, 95])
    ln = np.clip((lum - tief) / max(1e-6, float(hoch - tief)), 0.0, 1.0)

    if fin_key == "metallic":
        k = float(fin.get("kontrast", 1.6))
        ln = np.clip(0.5 + (ln - 0.5) * k, 0.0, 1.0)

    helligkeit = (0.45 + 1.1 * ln)[..., None]
    neu = ziel[None, None, :] * helligkeit

    if fin_key == "zweifarbig":
        neu = np.where(_streifen(fest, rgb.shape[:2], fin)[..., None],
                       _zweitfarbe(ziel, fin)[None, None, :] * helligkeit, neu)

    if fin_key == "neon":
        rand = _randband(fest, int(fin.get("saum_breite", 3)))
        neu = np.where(rand[..., None],
                       np.clip(neu * float(fin.get("saum_faktor", 1.5))
                               + float(fin.get("saum_offset", 26.0)), 0, 255), neu)

    deck = (gewicht * float(werte.get("deckkraft", 1.0)))[..., None]
    return _surface(deck * neu + (1.0 - deck) * rgb, alpha)


def _streifen(fest: np.ndarray, form: tuple[int, int], fin: dict) -> np.ndarray:
    """Rallye-Streifen entlang der Laengsachse.

    Bild-X ist die Fahrzeuglaenge, Bild-Y die Breite (``renderer.py`` skaliert
    auf ``(height_px, width_px)``), der Streifen laeuft also entlang X und sitzt
    mittig in Y. Die Mitte kommt aus dem **Schwerpunkt der Maske**, nicht aus der
    halben Bildhoehe: ein hoher Heckfluegel verschiebt den Zuschnitt, und ein auf
    die Bildmitte gerechneter Streifen laeuft dann neben der Karosseriemitte.
    """
    band = np.zeros(form, dtype=bool)
    zeilen = np.nonzero(fest.any(axis=0))[0]
    if zeilen.size == 0:
        return band
    gewicht_y = fest.sum(axis=0).astype(np.float64)
    mitte = float((np.arange(form[1]) * gewicht_y).sum() / max(1.0, gewicht_y.sum()))
    hoehe = float(zeilen.max() - zeilen.min() + 1)
    halb = max(1.0, hoehe * float(fin.get("band_anteil", 0.22)) / 2.0)
    von = max(0, int(round(mitte - halb)))
    bis = min(form[1], int(round(mitte + halb)))
    band[:, von:bis] = True
    return band


def _zweitfarbe(ziel: np.ndarray, fin: dict) -> np.ndarray:
    """Streifenfarbe: hell oder dunkel, je nachdem was mehr Kontrast gibt."""
    hell = np.array(fin.get("zweitfarbe_hell", (235, 238, 240)), dtype=np.float32)
    dunkel = np.array(fin.get("zweitfarbe_dunkel", (55, 58, 65)), dtype=np.float32)
    return dunkel if abs(float(ziel.mean()) - hell.mean()) < \
        abs(float(ziel.mean()) - dunkel.mean()) else hell


# ---------------------------------------------------------------------------
# Sprites: freistellen, verkleinern, umfaerben, im Speicher halten
# ---------------------------------------------------------------------------
_roh_cache: dict[str, pygame.Surface | None] = {}
_lack_cache: dict[tuple[str, str, int], pygame.Surface] = {}


def roh_sprite(visual_type: str) -> pygame.Surface | None:
    """Freigestelltes Original — gleiche Logik wie ``VehicleRenderer``."""
    if visual_type in _roh_cache:
        return _roh_cache[visual_type]
    pfad = os.path.join("data", "vehicles", f"{str(visual_type).capitalize()}.png")
    surf: pygame.Surface | None = None
    try:
        if os.path.isfile(pfad):
            surf = pygame.image.load(pfad)
            if pygame.display.get_init() and pygame.display.get_surface() is not None:
                surf = surf.convert_alpha()
            ecke = surf.get_at((0, 0))
            if ecke.a == 255:
                surf.set_colorkey(ecke)
                gebacken = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
                gebacken.blit(surf, (0, 0))
                surf = gebacken
            m = pygame.mask.from_surface(surf, threshold=50)
            kaesten = m.get_bounding_rects()
            if kaesten:
                r = sorted(kaesten, key=lambda q: q.width * q.height, reverse=True)[0]
                if r.width > 0 and r.height > 0:
                    zuschnitt = pygame.Surface(r.size, pygame.SRCALPHA)
                    zuschnitt.blit(surf, (0, 0), r)
                    surf = zuschnitt
    except Exception:
        surf = None
    _roh_cache[visual_type] = surf
    return surf


def arbeitskopie(visual_type: str, breite: int) -> pygame.Surface | None:
    """Freigestelltes Original, auf *breite* verkleinert (nie vergroessert)."""
    roh = roh_sprite(visual_type)
    if roh is None:
        return None
    if roh.get_width() <= breite:
        return roh
    hoehe = max(1, int(roh.get_height() * breite / roh.get_width()))
    from src.core import gfx
    return gfx.scale(roh, (breite, hoehe))


def sprite(vehicle_key: str, visual_type: str, kenn: str,
           breite: int = BREITE_SPIEL) -> pygame.Surface | None:
    """Umgefaerbtes Sprite, im Arbeitsspeicher gehalten.

    Werkslack liefert das unveraenderte Original zurueck (nicht die
    Arbeitskopie) — damit sieht ein Fahrzeug ohne Lackwahl exakt so aus wie vor
    Block D.
    """
    kenn = normalisiere(kenn)
    if kenn == WERK:
        return roh_sprite(visual_type)
    schluessel = (visual_type, kenn, breite)
    fertig = _lack_cache.get(schluessel)
    if fertig is None:
        basis = arbeitskopie(visual_type, breite)
        if basis is None:
            return None
        fertig = umfaerben(basis, kenn, paint_werte(vehicle_key))
        _lack_cache[schluessel] = fertig
    return fertig


def cache_leeren() -> None:
    """Zwischenspeicher verwerfen — nach einer Aenderung im Fahrzeuglabor."""
    _lack_cache.clear()
    _paint_cache.clear()
    _wagenfarbe_cache.clear()


def palette_neu_laden() -> None:
    global _palette
    _palette = None
    _lack_cache.clear()
    _wagenfarbe_cache.clear()
