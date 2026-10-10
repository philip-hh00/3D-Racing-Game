"""Tageszeit und Wetter eines Rennens: gewürfelt, selten und nie gewählt.

Seit 1.1.0 stellt niemand mehr Tageszeit oder Wetter ein. Meist scheint die
Sonne; ab und zu wird es Nacht oder regnet es:

* 80 %: Tag bei Trocken (der Normalfall);
* 20 %: zu gleichen Teilen (je etwa 6,67 %) Nacht + Trocken, Tag + Regen,
  Nacht + Regen.

Der Abend wird nicht gewürfelt (die Voreinstellung bleibt in
``render3d.tageszeit`` für später).

Zeitfahren und Team-Zeitfahren fahren immer bei Tag und Trocken: die Ghosts
(auch der erzeugte Erst-Ghost einer Strecke) sind nur bei Sonne gefahren, und
ein Ghost aus dem Regen wäre auf trockener Straße kein fairer Vergleich.

Wer würfelt:

* offline und Splitscreen: ``RaceState.enter`` beim Rennstart, je Rennen neu
  (im Grand Prix also je Lauf);
* online: nur der Host, beim Rennstart in der Lobby (``_request_start``). Er
  schickt das Ergebnis über die optionalen Einstellungen ``tageszeit`` und
  ``wetter`` an alle; Gäste würfeln nie. Fehlen die Schlüssel, gilt Tag und
  Trocken. Das Wetter ändert die Haftung — alle müssen es gleich haben.

Zum Testen und Fotografieren: die Umgebungsvariable ``RACE_BEDINGUNGEN`` (siehe
:func:`uebersteuerung`) legt das Ergebnis des Würfelns fest.
"""

from __future__ import annotations

import os
import random

from src.render3d import tageszeit as _tz
from src.render3d import wetter as _wt

#: Der Normalfall: Sonne bei Tag.
STANDARD = (_tz.STANDARD, _wt.STANDARD)

#: Die gewürfelten Ausnahmen, zu gleichen Teilen.
AUSNAHMEN = (("Nacht", "Trocken"), ("Tag", "Regen"), ("Nacht", "Regen"))

#: Chance auf den Normalfall; der Rest verteilt sich gleichmäßig auf ``AUSNAHMEN``.
CHANCE_STANDARD = 0.80

#: Spielarten, in denen immer ``STANDARD`` gilt (Ghosts fahren nur bei Sonne).
FESTE_MODI = frozenset({"Zeitfahren", "Team-Zeitfahren"})

#: Umgebungsvariable, die das Würfeln übersteuert (nur zum Testen).
UMGEBUNGSVARIABLE = "RACE_BEDINGUNGEN"


def ist_fest(modus) -> bool:
    """Gilt in dieser Spielart immer Tag und Trocken (Zeitfahren, Team-Zeitfahren)?"""
    return modus in FESTE_MODI


def uebersteuerung(umgebung=None):
    """Die Festlegung aus ``RACE_BEDINGUNGEN`` oder ``None``.

    Erlaubt sind ``Tag/Trocken``, ``Nacht/Regen``, auch nur eines von beiden
    (``Regen`` heißt Tag bei Regen, ``Nacht`` Nacht bei Trocken) und der
    Abend (``Abend/Trocken``). Trenner ``/``, ``,``, ``+`` oder Leerzeichen.
    ``zufall`` (oder leer) lässt das Würfeln unberührt. Unverständliches gilt
    nicht — ein Tippfehler darf kein Rennen kosten.
    """
    umgebung = os.environ if umgebung is None else umgebung
    text = str(umgebung.get(UMGEBUNGSVARIABLE, "") or "").strip().lower()
    if not text:
        return None
    teile = [t for t in text.replace(",", "/").replace("+", "/").replace(" ", "/").split("/") if t]
    tageszeit = wetter = None
    for teil in teile:
        if teil in _tz._ALIASE:
            tageszeit = _tz.normiere(teil)
        elif teil in _wt._ALIASE:
            wetter = _wt.normiere(teil)
        else:
            return None
    if tageszeit is None and wetter is None:
        return None
    return (tageszeit or _tz.STANDARD, wetter or _wt.STANDARD)


def wuerfeln(zufall=None, modus="Rennen", umgebung=None) -> tuple[str, str]:
    """Tageszeit und Wetter für ein Rennen: ``(tageszeit, wetter)``.

    *zufall* ist die Zufallsquelle (ein Objekt mit ``random()``; Vorgabe: das
    ``random``-Modul) — Tests geben eine feste mit. *modus* ist die Spielart;
    im Zeitfahren und Team-Zeitfahren kommt immer ``STANDARD`` heraus, ohne
    zu würfeln. *umgebung* ersetzt ``os.environ`` (Tests).
    """
    if ist_fest(modus):
        return STANDARD
    fest = uebersteuerung(umgebung)
    if fest is not None:
        return fest
    r = (zufall if zufall is not None else random).random()
    if r < CHANCE_STANDARD:
        return STANDARD
    anteil = (1.0 - CHANCE_STANDARD) / len(AUSNAHMEN)
    platz = int((r - CHANCE_STANDARD) / anteil)
    return AUSNAHMEN[max(0, min(len(AUSNAHMEN) - 1, platz))]


def normiere(tageszeit, wetter) -> tuple[str, str]:
    """Beide Werte aus beliebiger Eingabe (z. B. fehlende Schlüssel der Lobby)."""
    return _tz.normiere(tageszeit), _wt.normiere(wetter)


def beschreibung(tageszeit, wetter) -> str:
    """Eine kurze Zeile für den Spieler — leer, wenn es der Normalfall ist.

    „Nacht", „Regen", „Regen bei Nacht" (englisch über ``tr``).
    """
    from src.core.i18n import tr
    tageszeit, wetter = normiere(tageszeit, wetter)
    if (tageszeit, wetter) == STANDARD:
        return ""
    if wetter == "Regen" and tageszeit == "Nacht":
        return tr("Regen bei Nacht")
    if wetter == "Regen" and tageszeit == "Abend":
        return tr("Regen am Abend")
    if wetter == "Regen":
        return tr("Regen")
    return tr(tageszeit)
