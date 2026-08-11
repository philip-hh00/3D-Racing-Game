"""Prüfen, was über das Netz hereinkommt.

Alles aus einer Netzwerknachricht kann fehlen, den falschen Typ haben oder eine
Liste sein, wo ein Objekt erwartet wird. Im Normalbetrieb passiert das nicht —
der Relay schickt saubere Daten. Es passiert bei einem Versionsversatz zwischen
Client und Server, und genau dann ist eine unbedienbare Lobby immer noch besser
als ein Absturz, den der Spieler nie reproduzieren kann.

Deshalb überall dasselbe Muster: **verwertbare Einträge behalten, unbrauchbare
verwerfen, nie aufgeben.** Geprüft wird an der Stelle, an der die Daten
hereinkommen, nicht an jeder der Stellen, die sie später lesen — sonst wird
garantiert eine vergessen.
"""
from __future__ import annotations

from typing import Any


def as_int(value: Any, default: int) -> int:
    """Ganzzahl aus *value*, sonst *default*."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float | None = None):
    """Kommazahl aus *value*, sonst *default*. NaN und unendlich gelten als
    unbrauchbar — sie würden sich sonst durch jede spätere Rechnung ziehen."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def dict_entries(raw: Any) -> list[dict]:
    """Nur die Einträge einer Liste, die tatsächlich Objekte sind.

    Deckt den häufigsten Fall ab: irgendwo in einer Liste steckt ``None``, eine
    Zahl oder ein Text, und der erste ``.get()``-Aufruf darauf beendet das
    Spiel — oft erst im Zeichenpfad, also mitten im Rennen.
    """
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def players(raw: Any) -> list[dict]:
    """Spielereinträge mit brauchbarem Slot, Slot als Ganzzahl normalisiert.

    Ein Eintrag ohne zuordenbaren Slot ist wertlos: er lässt sich weder einem
    Fahrzeug noch einer Anzeige zuordnen. Ein Slot als Text (``"3"``) würde bei
    jedem Vergleich mit dem eigenen Slot durchfallen, deshalb die Umwandlung.
    """
    out: list[dict] = []
    for p in dict_entries(raw):
        slot = as_int(p.get("slot"), -1)
        if slot < 0:
            continue
        entry = dict(p)
        entry["slot"] = slot
        out.append(entry)
    return out
