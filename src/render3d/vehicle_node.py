"""Ein Fahrzeug aus Karosserie und vier Rädern, die drehen und lenken.

Die Modelle kommen aus Blender (``tools/blender/fahrzeug_bauen.py``): jedes Rad
ist ein eigener Knoten mit Ursprung in der Nabenmitte, dazu je Rad ein
Bremssattel, der mitlenkt, aber nicht mitrollt. Die Nabenpositionen stehen in
``<key>_teile.json``. Dieses Modul macht daraus ein Fahrzeug, das sich
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
from dataclasses import dataclass, field
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

    @property
    def sattel(self) -> str:
        """Name des Bremssattels, der zu diesem Rad gehört."""
        return "sattel_" + self.name.removeprefix("rad_")


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
        self.nick_rad = 0.0
        self.wank_rad = 0.0

    @classmethod
    def aus_datei(cls, pfad: str | Path) -> "Fahrzeugknoten":
        """Aus ``<key>_teile.json``."""
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

    def neigen(self, nick_rad: float = 0.0, wank_rad: float = 0.0) -> None:
        """Den Aufbau nicken (+: Front runter) und wanken (+: rechts runter) lassen.

        Die Räder bleiben, wo sie sind — sie hängen nicht an der Karosserie,
        sondern am Fahrzeug. Der Federweg ergibt sich so von selbst (siehe
        :mod:`src.render3d.federung`).
        """
        self.nick_rad = float(nick_rad)
        self.wank_rad = float(wank_rad)

    def aufbau_matrix(self) -> np.ndarray | None:
        """Die Neigung des Aufbaus relativ zum Fahrzeug, um den Wankpol.

        Gedreht wird um einen Punkt auf Nabenhöhe: so neigt sich das Dach
        sichtbar, während der Schweller kaum wandert — wie bei einem echten
        Auto, dessen Wankachse knapp über der Straße liegt.
        """
        if not self.nick_rad and not self.wank_rad:
            return None
        pol = matrix.verschiebung(0.0, 0.0, self.radradius_m)
        zurueck = matrix.verschiebung(0.0, 0.0, -self.radradius_m)
        return pol @ matrix.drehung_y(self.nick_rad) @ matrix.drehung_x(self.wank_rad) @ zurueck

    def setzen(self, rollwinkel_rad: float = 0.0, lenkwinkel_rad: float = 0.0) -> None:
        self.rollwinkel_rad = float(rollwinkel_rad)
        self.lenkwinkel_rad = float(lenkwinkel_rad)

    # -- Matrizen --------------------------------------------------------
    def lenk_matrix(self, rad: Radplatz) -> np.ndarray:
        """Nabe an ihrem Platz, um den Lenkeinschlag gedreht — ohne Rollen.

        So steht der Bremssattel: er schwenkt mit dem Rad, dreht sich aber
        nicht mit ihm.
        """
        m = matrix.verschiebung(rad.nabe)
        if rad.gelenkt and self.lenkwinkel_rad:
            m = m @ matrix.drehung_z(self.lenkwinkel_rad)
        return m

    def rad_matrix(self, rad: Radplatz) -> np.ndarray:
        """Wo dieses Rad steht, relativ zum Fahrzeug."""
        return self.lenk_matrix(rad) @ matrix.drehung_y(self.rollwinkel_rad)

    def matrizen(self, pos_m, gierwinkel_rad: float,
                 karosserie: np.ndarray | None = None) -> dict[str, np.ndarray]:
        """Modellmatrix je Teilname, einschließlich Karosserie und Sätteln.

        ``karosserie`` ist eine zusätzliche Lage des Aufbaus relativ zum
        Fahrzeug (Nicken, Wanken, Einfedern); die Räder bleiben davon
        unberührt auf der Straße.
        """
        basis = matrix.fahrzeug(pos_m, gierwinkel_rad)
        if karosserie is None:
            karosserie = self.aufbau_matrix()
        ergebnis = {KAROSSERIE: basis if karosserie is None else basis @ karosserie}
        for rad in self.raeder:
            ergebnis[rad.name] = basis @ self.rad_matrix(rad)
            ergebnis[rad.sattel] = basis @ self.lenk_matrix(rad)
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
