"""Sollmasse der 15 Fahrzeugkonfigurationen, in Metern.

Das 2D-Spiel steht auf **12,5 px = 1 m** (nachgerechnet ueber alle 15
Fahrzeug-JSONs via ``wheelbase_ratio x height_px / wheelbase``, Ergebnis
durchgehend 12,49-12,51). Hier wird trotzdem nur in Metern gerechnet: der
Pixelmassstab ist eine Eigenschaft der 2D-Darstellung, nicht des Modells. Wer
ihn im 3D-Weg mitschleppt, muss ihn an jeder Stelle wieder herauskuerzen.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fahrzeugmasse:
    key: str
    laenge_m: float
    breite_m: float
    rad_m: float
    radstand_m: float


def _m(key, laenge, breite, rad, radstand):
    return key, Fahrzeugmasse(key, laenge, breite, rad, radstand)


SPECS: dict[str, Fahrzeugmasse] = dict([
    _m("rookie",      4.32, 2.08, 0.65, 2.624),
    _m("rookie_2",    4.24, 2.08, 0.64, 2.674),
    _m("rookie_3",    4.40, 2.16, 0.65, 2.674),
    _m("supercar",    4.96, 2.32, 0.64, 2.674),
    _m("supercar_2",  4.80, 2.32, 0.64, 2.624),
    _m("supercar_3",  4.88, 2.24, 0.64, 2.574),
    _m("drifter",     4.64, 2.16, 0.65, 3.074),
    _m("drifter_2",   4.64, 2.16, 0.65, 2.924),
    _m("drifter_3",   4.64, 2.16, 0.65, 3.074),
    _m("limousine",   5.20, 2.16, 0.69, 3.274),
    _m("limousine_2", 5.12, 2.16, 0.68, 3.174),
    _m("limousine_3", 5.20, 2.16, 0.69, 3.274),
    _m("electric",    4.96, 2.16, 0.73, 2.942),
    _m("electric_2",  5.04, 2.16, 0.73, 2.992),
    _m("electric_3",  4.96, 2.16, 0.73, 2.892),
])

#: Wie weit die Spurweite unter der Fahrzeugbreite liegt. Die Breite in der
#: Tabelle ist das Aussenmass ueber die Kotfluegel; die Raeder stehen darunter,
#: sonst ragen sie sichtbar heraus.
SPURWEITE_ANTEIL = 0.82


def spec(key: str) -> Fahrzeugmasse:
    """Sollmasse eines Fahrzeugs. Unbekannt heisst Abbruch, nicht Vorgabewert -
    ein stillschweigend falsch skaliertes Auto faellt erst im Spiel auf."""
    try:
        return SPECS[key]
    except KeyError:
        raise KeyError(
            f"Unbekannte Fahrzeugkonfiguration {key!r}. "
            f"Gueltig sind: {', '.join(SPECS)}"
        ) from None


def radpositionen(key: str) -> list[tuple[float, float, float]]:
    """Die vier Nabenmittelpunkte im Fahrzeugkoordinatensystem.

    Vorbereitung fuer die getrennt generierten Raeder: TRELLIS liefert ein
    verschmolzenes Mesh, in dem nichts lenkt und nichts dreht. Karosserie und
    Rad kommen deshalb aus zwei Laeufen, und die Radposition wird gerechnet
    statt aus dem Mesh gesucht.

    Reihenfolge: vorne links, vorne rechts, hinten links, hinten rechts.
    +X ist vorne, +Y ist links, +Z ist oben, der Ursprung liegt mittig auf dem
    Boden.
    """
    s = spec(key)
    x = s.radstand_m / 2.0
    y = s.breite_m * SPURWEITE_ANTEIL / 2.0
    z = s.rad_m / 2.0
    return [(x, y, z), (x, -y, z), (-x, y, z), (-x, -y, z)]
