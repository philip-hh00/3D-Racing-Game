"""Ein Fahrzeug aus Karosserie und vier Rädern, die drehen und lenken.

TRELLIS liefert ein verschmolzenes Netz; ``trellis_pipeline.radschnitt`` trennt
daraus Karosserie und Räder und legt die Nabenpositionen in
``<key>_teile.json`` ab. Dieses Modul macht aus beidem ein Fahrzeug, das sich
bewegt: die Räder rollen mit dem zurückgelegten Weg und die Vorderräder folgen
dem Lenkeinschlag.

**Der Rollwinkel kommt aus dem Weg, nicht aus der Zeit.** Ein Rad, das je
Sekunde eine feste Zahl Umdrehungen macht, dreht sich beim Anhalten weiter und
beim Rückwärtsfahren falsch herum. Mit dem Weg stimmt es in jeder Lage — auch
im Stillstand, auch rückwärts, auch wenn die Bildrate schwankt.

Die Reihenfolge der Drehungen ist nicht beliebig:

    Fahrzeug · Nabe · Lenkung(Z) · Rollen(Y)

Von rechts gelesen: das Rad dreht sich zuerst um seine eigene Querachse, dann
wird es um die senkrechte Lenkachse geschwenkt, dann an seinen Platz am
Fahrzeug gesetzt, dann mit dem Fahrzeug bewegt. Vertauscht man Lenkung und
Rollen, dreht sich ein eingeschlagenes Rad um eine schräge Achse und eiert.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import matrix

#: Name des Karosserieteils in der GLB-Szene.
KAROSSERIE = "karosserie"


@dataclass
class Radplatz:
    """Ein Radteil und wo es hingehört."""

    name: str
    nabe: np.ndarray            # (3,) Meter, im Fahrzeugkoordinatensystem
    gelenkt: bool


def teile_lesen(pfad: str | Path) -> tuple[list[Radplatz], float]:
    """``<key>_teile.json`` einlesen: Radplätze und Raddurchmesser."""
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    gelenkt = set(daten.get("gelenkt") or [])
    plaetze = [
        Radplatz(name=str(r["name"]),
                 nabe=np.asarray(r["nabe"], dtype=np.float64),
                 gelenkt=str(r["name"]) in gelenkt)
        for r in daten.get("raeder", []) or []
    ]
    return plaetze, float(daten.get("raddurchmesser_m", 0.65))


class Fahrzeugknoten:
    """Karosserie und Räder eines Fahrzeugs, in Bewegung.

    Kennt weder OpenGL noch pygame: es liefert Namen und Matrizen. Wer
    zeichnet, sucht sich die zugehörigen Teile selbst heraus. Das hält den
    Knoten prüfbar, ohne dass ein Grafikkontext nötig wäre.
    """

    def __init__(self, raedern: list[Radplatz], raddurchmesser_m: float) -> None:
        if raddurchmesser_m <= 0:
            raise ValueError("Raddurchmesser muss positiv sein")
        self.raeder = list(raedern)
        self.radradius_m = raddurchmesser_m / 2.0
        self.rollwinkel_rad = 0.0
        self.lenkwinkel_rad = 0.0

    @classmethod
    def aus_datei(cls, pfad: str | Path) -> "Fahrzeugknoten":
        plaetze, durchmesser = teile_lesen(pfad)
        return cls(plaetze, durchmesser)

    # -- Zustand ---------------------------------------------------------
    def weg_zuruecklegen(self, weg_m: float) -> None:
        """Die Räder um den zurückgelegten Weg weiterdrehen.

        Vorwärts dreht vorwärts, rückwärts zurück, Stillstand gar nicht — das
        ergibt sich von selbst, weil der Weg das Vorzeichen mitbringt.
        """
        self.rollwinkel_rad += float(weg_m) / self.radradius_m

    def lenken(self, winkel_rad: float) -> None:
        self.lenkwinkel_rad = float(winkel_rad)

    def setzen(self, rollwinkel_rad: float = 0.0, lenkwinkel_rad: float = 0.0) -> None:
        self.rollwinkel_rad = float(rollwinkel_rad)
        self.lenkwinkel_rad = float(lenkwinkel_rad)

    # -- Matrizen --------------------------------------------------------
    def rad_matrix(self, rad: Radplatz) -> np.ndarray:
        """Wo dieses Rad steht, relativ zum Fahrzeug."""
        m = matrix.verschiebung(rad.nabe)
        if rad.gelenkt and self.lenkwinkel_rad:
            m = m @ matrix.drehung_z(self.lenkwinkel_rad)
        return m @ matrix.drehung_y(self.rollwinkel_rad)

    def matrizen(self, pos_m, gierwinkel_rad: float) -> dict[str, np.ndarray]:
        """Modellmatrix je Teilname, einschließlich Karosserie."""
        basis = matrix.fahrzeug(pos_m, gierwinkel_rad)
        ergebnis = {KAROSSERIE: basis}
        for rad in self.raeder:
            ergebnis[rad.name] = basis @ self.rad_matrix(rad)
        return ergebnis


def lenkwinkel_aus_fahrzeug(fahrzeug_objekt) -> float:
    """Den Lenkeinschlag aus einem Fahrzeug des Spiels holen.

    Er steckt in ``vehicle.physics.steer_angle`` (siehe
    ``src/entities/components/physics_body.py``). Fehlt er, wird nicht
    gelenkt — ein Ghost oder ein ferngesteuertes Fahrzeug bringt ihn nicht
    zwingend mit, und ein fehlender Wert soll das Bild nicht kosten.
    """
    physik = getattr(fahrzeug_objekt, "physics", None)
    return float(getattr(physik, "steer_angle", 0.0) or 0.0)
