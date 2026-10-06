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
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import matrix

#: Name des Karosserieteils in der GLB-Szene.
KAROSSERIE = "karosserie"

#: Wie viel vom Ackermann-Winkel gilt: 0 = beide Vorderräder gleich, 1 = die
#: reine Geometrie (das kurveninnere Rad schlägt um rund ein Drittel mehr ein
#: als das äußere). Die Hälfte sieht nach Auto aus und nicht nach Lehrbuch.
ACKERMANN = 0.5

#: Größter Radeinschlag, den die Physik kennt (``PhysicsBody.apply_steering``).
LENK_PHYSIK_MAX_RAD = math.radians(35.0)
#: Größter Einschlag, der gezeichnet wird.
LENK_SICHT_MAX_RAD = math.radians(30.0)
#: Verstärkung nahe der Mitte. Die Physik schlägt bei Tempo nur 2–7° ein
#: (die Haftgrenze), und das sieht von hinten nach Geradeaus aus.
LENK_SICHT_GEWINN = 4.0


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
        self._spur_fuer: tuple | None = None
        self._spur: tuple[float, float] | None = None

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
    def _nabe_matrix(self, rad: Radplatz) -> np.ndarray:
        """Die Verschiebung zur Nabe, je Rad einmal gerechnet (nur lesen, schreibgeschützt)."""
        gemerkt = self.__dict__.setdefault("_nabe_gemerkt", {})
        eintrag = gemerkt.get(id(rad))
        if eintrag is None or eintrag[0] is not rad:
            m = matrix.verschiebung(rad.nabe)
            m.setflags(write=False)
            eintrag = gemerkt[id(rad)] = (rad, m)
        return eintrag[1]

    def _achsmasse(self) -> tuple[float, float] | None:
        """Radstand und halbe Spur der Vorderachse, oder ``None`` ohne Ackermann.

        Gebraucht wird ein gelenktes Paar (links und rechts) und mindestens ein
        ungelenktes Rad; sonst bleibt es bei einem Winkel für alle. Je Satz
        Räder einmal gerechnet.
        """
        schluessel = (id(self.raeder), len(self.raeder))
        if self._spur_fuer != schluessel:
            self._spur_fuer = schluessel
            self._spur = None
            vorn = [r for r in self.raeder if r.gelenkt]
            hinten = [r for r in self.raeder if not r.gelenkt]
            if (hinten and any(r.nabe[1] > 0 for r in vorn)
                    and any(r.nabe[1] < 0 for r in vorn)):
                radstand = (sum(float(r.nabe[0]) for r in vorn) / len(vorn)
                            - sum(float(r.nabe[0]) for r in hinten) / len(hinten))
                halbspur = sum(abs(float(r.nabe[1])) for r in vorn) / len(vorn)
                if radstand > 0.5 and halbspur > 0.1:
                    self._spur = (radstand, halbspur)
        return self._spur

    def radwinkel(self, rad: Radplatz) -> float:
        """Lenkwinkel dieses Rades: gelenkt, mit Ackermann, sonst null.

        ``lenkwinkel_rad`` ist der Winkel der Achsmitte. In der Kurve fährt das
        innere Rad den kleineren Kreis und schlägt deshalb weiter ein
        (``atan(L·tan δ / (L ∓ s·tan δ))``, ``s`` die halbe Spur); gezeichnet
        wird davon der Anteil :data:`ACKERMANN`.
        """
        delta = self.lenkwinkel_rad
        if not (rad.gelenkt and delta):
            return 0.0
        masse = self._achsmasse()
        if masse is None:
            return delta
        radstand, halbspur = masse
        seite = 1.0 if rad.nabe[1] > 0 else -1.0
        t = math.tan(delta)
        nenner = max(radstand - seite * halbspur * t, 0.25 * radstand)
        return delta + ACKERMANN * (math.atan2(radstand * t, nenner) - delta)

    def lenk_matrix(self, rad: Radplatz) -> np.ndarray:
        """Nabe an ihrem Platz, um den Lenkeinschlag gedreht — ohne Rollen.

        So steht der Bremssattel: er schwenkt mit dem Rad, dreht sich aber
        nicht mit ihm. Gedreht wird um die Senkrechte durch die Nabe, weil die
        Verschiebung zur Nabe links der Drehung steht (``Nabe @ Lenkung``).
        """
        m = self._nabe_matrix(rad)
        winkel = self.radwinkel(rad)
        if winkel:
            m = m @ matrix.drehung_z(winkel)
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
        # Rollen ist für alle Räder gleich, und die Lenkmatrix braucht Rad und
        # Sattel: je einmal rechnen. Acht Autos, drei Durchgänge — das zählt.
        rollen = matrix.drehung_y(self.rollwinkel_rad)
        for rad in self.raeder:
            lenk = basis @ self.lenk_matrix(rad)
            ergebnis[rad.name] = lenk @ rollen
            ergebnis[rad.sattel] = lenk
        return ergebnis


def sichtbarer_lenkwinkel(physik_rad: float) -> float:
    """Aus dem Radeinschlag der Physik den gezeichneten Einschlag machen.

    Die Physik hält den Einschlag bei Tempo klein (Haftgrenze: bei 150 km/h
    rund 3°), und so kleine Winkel sieht man an einem Rad nicht — es wirkte,
    als lenkten die Vorderräder gar nicht. Gezeichnet wird deshalb
    ``30° · tanh(4 · Winkel / 30°)``: nahe der Mitte vierfach, bei vollem
    Einschlag bis 30° — vorzeichentreu und ohne Sprung bei null.
    """
    return LENK_SICHT_MAX_RAD * math.tanh(
        LENK_SICHT_GEWINN * float(physik_rad) / LENK_SICHT_MAX_RAD)


def lenkwinkel_aus_bewegung(laengs_m_s: float, gierrate_rad_s: float,
                            radstand_m: float) -> float:
    """Den Radeinschlag aus der Fahrt ableiten (Einspurmodell), für Abbilder.

    Ein ferngesteuertes Fahrzeug bekommt über das Netz nur Lage, Tempo und
    Gierrate (der UDP-Strom ist fest 26 Byte je Fahrzeug, siehe
    ``src/net/protocol.py``) — den Lenkwinkel nicht. Die Fahrt verrät ihn:
    ``δ = atan(L · ω / v)``. Rückwärts kehrt sich ``v`` um, und das
    Vorzeichen stimmt von selbst. Langsam wird der Wert ausgeblendet, sonst
    „lenkt" ein Auto, das sich im Stand dreht, voll ein.
    """
    if radstand_m <= 0.0 or laengs_m_s == 0.0:
        return 0.0
    delta = math.atan(radstand_m * gierrate_rad_s / laengs_m_s)
    delta = max(-LENK_PHYSIK_MAX_RAD, min(LENK_PHYSIK_MAX_RAD, delta))
    return delta * min(1.0, abs(laengs_m_s) / 1.5)


def lenkwinkel_aus_fahrzeug(fahrzeug_objekt) -> float:
    """Den gezeichneten Lenkeinschlag aus einem Fahrzeug des Spiels holen.

    Er steckt in ``vehicle.physics.steer_angle`` (siehe
    ``src/entities/components/physics_body.py``), gezeigt wird er durch
    :func:`sichtbarer_lenkwinkel`. Fehlt er, wird nicht gelenkt — ein Ghost
    oder ein ferngesteuertes Fahrzeug bringt ihn nicht mit (für Abbilder siehe
    :func:`lenkwinkel_aus_bewegung`), und ein fehlender Wert soll das Bild nicht
    kosten.
    """
    physik = getattr(fahrzeug_objekt, "physics", None)
    return sichtbarer_lenkwinkel(float(getattr(physik, "steer_angle", 0.0) or 0.0))
