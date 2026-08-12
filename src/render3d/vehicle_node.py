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
    #: Verschiebung der Drehachse gegenüber dem Ursprung des Radnetzes.
    #: Die automatische Nabenbestimmung trifft die Radmitte nicht immer — sie
    #: muss aus einem Netz schließen, in dem Reifen und Radlauf zusammenhängen.
    #: Liegt die Achse daneben, kreist das Rad beim Rollen. Mit
    #: ``tools/radpruefer.py`` lässt sich die Abweichung von Hand einstellen;
    #: sie landet in ``trellis_import.json`` und wird hier angewandt, ohne das
    #: Netz neu erzeugen zu müssen.
    korrektur: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float64))


def korrekturen_lesen(pfad: str | Path, fahrzeug: str) -> dict[str, np.ndarray]:
    """Nabenkorrekturen aus ``trellis_import.json``.

    Aufbau: ``{"rookie": {"naben": {"rad_vl": [0.01, 0.0, -0.02]}}}``. Fehlt
    die Datei oder der Eintrag, wird nicht korrigiert.
    """
    try:
        with open(pfad, encoding="utf-8") as fh:
            daten = json.load(fh)
    except (OSError, ValueError):
        return {}
    eintrag = daten.get(fahrzeug)
    naben = eintrag.get("naben") if isinstance(eintrag, dict) else None
    if not isinstance(naben, dict):
        return {}
    return {str(name): np.asarray(wert, dtype=np.float64)
            for name, wert in naben.items()
            if isinstance(wert, (list, tuple)) and len(wert) == 3}


def teile_lesen(pfad: str | Path,
                korrekturen: dict[str, np.ndarray] | None = None
                ) -> tuple[list[Radplatz], float]:
    """``<key>_teile.json`` einlesen: Radplätze und Raddurchmesser."""
    with open(pfad, encoding="utf-8") as fh:
        daten = json.load(fh)
    gelenkt = set(daten.get("gelenkt") or [])
    korrekturen = korrekturen or {}
    plaetze = [
        Radplatz(name=str(r["name"]),
                 nabe=np.asarray(r["nabe"], dtype=np.float64),
                 gelenkt=str(r["name"]) in gelenkt,
                 korrektur=np.asarray(
                     korrekturen.get(str(r["name"]), (0.0, 0.0, 0.0)),
                     dtype=np.float64))
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
    def aus_datei(cls, pfad: str | Path,
                  korrektur_datei: str | Path | None = None,
                  fahrzeug: str | None = None) -> "Fahrzeugknoten":
        """Aus ``<key>_teile.json``, wahlweise mit Nabenkorrekturen.

        Ohne ``fahrzeug`` wird der Schlüssel aus dem Dateinamen abgeleitet:
        ``rookie_teile.json`` gehört zu ``rookie``.
        """
        pfad = Path(pfad)
        if fahrzeug is None:
            fahrzeug = pfad.stem.removesuffix("_teile")
        korrekturen = (korrekturen_lesen(korrektur_datei, fahrzeug)
                       if korrektur_datei else {})
        plaetze, durchmesser = teile_lesen(pfad, korrekturen)
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
        """Wo dieses Rad steht, relativ zum Fahrzeug.

        Mit Korrektur wird um einen Punkt gedreht, der neben dem Ursprung des
        Netzes liegt: erst den Ursprung auf die wahre Radmitte schieben
        (``-korrektur``), dann drehen, dann alles zusammen an den Platz
        (``nabe + korrektur``). Das Netz selbst bleibt unangetastet, die
        Korrektur wirkt also ohne neuen Import.
        """
        hat_korrektur = bool(np.any(rad.korrektur))
        m = matrix.verschiebung(np.asarray(rad.nabe) + rad.korrektur
                                if hat_korrektur else rad.nabe)
        if rad.gelenkt and self.lenkwinkel_rad:
            m = m @ matrix.drehung_z(self.lenkwinkel_rad)
        m = m @ matrix.drehung_y(self.rollwinkel_rad)
        if hat_korrektur:
            m = m @ matrix.verschiebung(-np.asarray(rad.korrektur))
        return m

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
