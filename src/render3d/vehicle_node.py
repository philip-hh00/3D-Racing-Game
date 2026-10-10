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


#: Namen der animierten Cockpitknoten (siehe VEREINBARUNGEN.md, "Cockpit").
LENKRAD = "lenkrad"
NADEL_TACHO = "nadel_tacho"
NADEL_DREHZAHL = "nadel_drehzahl"

#: Vorgaben, wenn ``<key>_teile.json`` keinen Block ``cockpit`` hat.
LENKRAD_UEBERSETZUNG = 12.0
TACHO_MAX_KMH = 320.0
TACHO_WINKEL_GRAD = (-135.0, 135.0)
DREHZAHL_MAX = 9000.0
DREHZAHL_WINKEL_GRAD = (-135.0, 135.0)


@dataclass
class Cockpitmasse:
    """Der Block ``cockpit`` aus ``<key>_teile.json``, Fahrzeugsystem in Metern.

    ``augpunkt`` ist die Augenmitte des Fahrers, ``haube`` der Kamerapunkt der
    Motorhaubenansicht. Fehlt der Block oder ein Punkt darin, wird er aus den
    Fahrzeugmaßen abgeschätzt (:func:`cockpit_aus_masse`), damit auch ein altes
    Modell eine brauchbare Ansicht bekommt. ``aus_datei`` sagt, ob mindestens
    ein Punkt aus dem Modell stammt oder alles geschätzt ist.
    """

    augpunkt: np.ndarray
    haube: np.ndarray
    lenkrad_uebersetzung: float = LENKRAD_UEBERSETZUNG
    tacho_max_kmh: float = TACHO_MAX_KMH
    tacho_winkel_grad: tuple[float, float] = TACHO_WINKEL_GRAD
    drehzahl_max: float = DREHZAHL_MAX
    drehzahl_winkel_grad: tuple[float, float] = DREHZAHL_WINKEL_GRAD
    aus_datei: bool = False


def cockpit_aus_masse(laenge_m: float, breite_m: float, hoehe_m: float) -> Cockpitmasse:
    """Augpunkt und Hauben-Kamerapunkt aus den Fahrzeugmaßen schätzen.

    Linkslenker (+Y ist links): der Fahrer sitzt links der Mitte, die
    Augen etwa in Fahrzeugmitte. Die
    Haubenkamera sitzt auf der Mittellinie am Fuß der Frontscheibe, knapp über
    der Haube. Die Werte sind an den fünf Fahrzeugen von 1.0 abgelesen; die
    echten Punkte stehen im Block ``cockpit`` der ``teile.json``.
    """
    # Die Augen liegen drei Dezimeter unter dem Dach, bei hohen Wagen bei vier Fünfteln
    # der Höhe: ein flacher Sportwagen sähe sonst nur sein Dach.
    augenhoehe = max(0.5, min(0.80 * hoehe_m, hoehe_m - 0.30))
    augpunkt = np.array([-0.04 * laenge_m, 0.16 * breite_m, augenhoehe])
    haube = np.array([0.27 * laenge_m, 0.0, 0.80 * hoehe_m])
    return Cockpitmasse(augpunkt=augpunkt, haube=haube)


def _paar(wert, vorgabe: tuple[float, float]) -> tuple[float, float]:
    try:
        a, b = wert
        return float(a), float(b)
    except (TypeError, ValueError):
        return vorgabe


def _punkt(wert) -> np.ndarray | None:
    try:
        p = np.asarray([float(w) for w in wert], dtype=np.float64)
    except (TypeError, ValueError):
        return None
    return p if p.shape == (3,) and np.all(np.isfinite(p)) else None


def cockpit_lesen(daten: dict) -> Cockpitmasse:
    """Aus dem geladenen JSON von ``<key>_teile.json``. Nie ``None``: Lücken werden geschätzt."""
    schaetzung = cockpit_aus_masse(float(daten.get("laenge_m", 4.3)),
                                   float(daten.get("breite_m", 2.0)),
                                   float(daten.get("hoehe_m", 1.4)))
    block = daten.get("cockpit")
    if not isinstance(block, dict):
        return schaetzung
    aug = _punkt(block.get("augpunkt"))
    haube = _punkt(block.get("haube"))

    def zahl(name: str, vorgabe: float, nur_positiv: bool) -> float:
        try:
            w = float(block.get(name, vorgabe))
        except (TypeError, ValueError):
            return vorgabe
        return w if (w > 0.0 or not nur_positiv) else vorgabe

    return Cockpitmasse(
        augpunkt=aug if aug is not None else schaetzung.augpunkt,
        haube=haube if haube is not None else schaetzung.haube,
        lenkrad_uebersetzung=zahl("lenkrad_uebersetzung", LENKRAD_UEBERSETZUNG, False),
        tacho_max_kmh=zahl("tacho_max_kmh", TACHO_MAX_KMH, True),
        tacho_winkel_grad=_paar(block.get("tacho_winkel_grad"), TACHO_WINKEL_GRAD),
        drehzahl_max=zahl("drehzahl_max", DREHZAHL_MAX, True),
        drehzahl_winkel_grad=_paar(block.get("drehzahl_winkel_grad"), DREHZAHL_WINKEL_GRAD),
        aus_datei=aug is not None or haube is not None,
    )


def cockpit_aus_datei(pfad: str | Path) -> Cockpitmasse | None:
    """``cockpit`` aus ``<key>_teile.json``; ``None``, wenn die Datei fehlt oder kaputt ist."""
    try:
        with open(pfad, encoding="utf-8") as fh:
            return cockpit_lesen(json.load(fh))
    except (OSError, ValueError):
        return None


def nadelwinkel(wert: float, maximum: float, winkel_grad: tuple[float, float]) -> float:
    """Drehung einer Nadel um ihre lokale X-Achse in Radiant.

    ``winkel_grad`` ist die Drehung bei 0 und bei ``maximum`` (aus
    ``teile.json``); dazwischen wird linear gemischt, außerhalb gehalten — die
    Nadel schlägt nicht über den Anschlag.
    """
    anteil = 0.0 if maximum <= 0.0 else max(0.0, min(1.0, float(wert) / maximum))
    a0, a1 = winkel_grad
    return math.radians(a0 + (a1 - a0) * anteil)


def lenkradwinkel(lenkwinkel_rad: float, uebersetzung: float) -> float:
    """Drehung des Lenkrads um die lokale X-Achse in Radiant.

    Der sichtbare Radeinschlag mal Übersetzung. Die lokale +X-Achse des
    Lenkrads zeigt entlang der Säule **zum Fahrer hin** (siehe
    ``tools/blender/teile_cockpit.py``). Eine positive Drehung um eine Achse,
    die auf den Betrachter zeigt, läuft für ihn gegen den Uhrzeigersinn: der
    Kranz oben wandert nach links, und das ist ein positiver Lenkwinkel
    (links, +Y). Also ohne Vorzeichenwechsel. Bei den Nadeln zeigt +X dagegen
    vom Fahrer weg ins Instrument: mehr Tempo = im Uhrzeigersinn.
    """
    return float(lenkwinkel_rad) * float(uebersetzung)


def aufbau_aus_neigung(nick_rad: float, wank_rad: float, radradius_m: float) -> np.ndarray | None:
    """Die Neigung des Aufbaus um den Wankpol (Nabenhöhe), ``None`` ohne Neigung."""
    if not nick_rad and not wank_rad:
        return None
    pol = matrix.verschiebung(0.0, 0.0, radradius_m)
    zurueck = matrix.verschiebung(0.0, 0.0, -radradius_m)
    return pol @ matrix.drehung_y(nick_rad) @ matrix.drehung_x(wank_rad) @ zurueck


class Fahrzeugknoten:
    """Karosserie und Räder eines Fahrzeugs, in Bewegung.

    Kennt weder OpenGL noch pygame: es liefert Namen und Matrizen. Wer
    zeichnet, sucht sich die zugehörigen Teile selbst heraus. Das hält den
    Knoten prüfbar, ohne dass ein Grafikkontext nötig wäre.
    """

    def __init__(self, raedern: list[Radplatz], raddurchmesser_m: float,
                 cockpit: Cockpitmasse | None = None,
                 anbauteile: dict[str, np.ndarray] | None = None,
                 achsen: dict[str, np.ndarray] | None = None) -> None:
        if raddurchmesser_m <= 0:
            raise ValueError("Raddurchmesser muss positiv sein")
        self.raeder = list(raedern)
        #: Übersetzungen und Skalen des Cockpits (``None``: nichts animieren).
        self.cockpit = cockpit
        #: Alle weiteren Knoten des Modells mit Netz — Name -> Ursprung im
        #: Fahrzeugsystem. Sie hängen starr am Aufbau; Lenkrad und Nadeln
        #: drehen sich zusätzlich (:meth:`anbauteil_matrix`). Ohne diese Liste
        #: zeichnet die Szene nur Karosserie, Räder und Sättel.
        self.anbauteile: dict[str, np.ndarray] = {
            str(n): np.asarray(v, dtype=np.float64) for n, v in (anbauteile or {}).items()
            if n != KAROSSERIE and not str(n).startswith(("rad_", "sattel_"))}
        #: Ausrichtung der Knoten (Name -> 3×3-Drehung) aus dem GLB. Der Lader
        #: rechnet sie in die Punkte; gedreht werden muss trotzdem um die
        #: **lokale** X-Achse — beim Lenkrad die um 22° geneigte Lenksäule,
        #: nicht die Fahrzeuglängsachse. Ohne Eintrag gilt die Fahrzeugachse.
        self.achsen: dict[str, np.ndarray] = {}
        for n, r in (achsen or {}).items():
            m4 = np.eye(4)
            m4[:3, :3] = np.asarray(r, dtype=np.float64)
            self.achsen[str(n)] = m4
        self.tempo_kmh = 0.0
        self.drehzahl = 0.0
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
        return cls(plaetze, durchmesser, cockpit=cockpit_aus_datei(pfad))

    # -- Zustand ---------------------------------------------------------
    def weg_zuruecklegen(self, weg_m: float) -> None:
        """Die Räder um den zurückgelegten Weg weiterdrehen.

        Vorwärts dreht vorwärts, rückwärts zurück, Stillstand gar nicht — das
        ergibt sich von selbst, weil der Weg das Vorzeichen mitbringt.
        """
        self.rollwinkel_rad += float(weg_m) / self.radradius_m

    def lenken(self, winkel_rad: float) -> None:
        self.lenkwinkel_rad = float(winkel_rad)

    def instrumente(self, tempo_kmh: float = 0.0, drehzahl: float = 0.0) -> None:
        """Tempo (km/h, Betrag) und Drehzahl (1/min) für die Nadeln im Armaturenbrett."""
        self.tempo_kmh = abs(float(tempo_kmh))
        self.drehzahl = max(0.0, float(drehzahl))

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
        return aufbau_aus_neigung(self.nick_rad, self.wank_rad, self.radradius_m)

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

    def anbauteil_matrix(self, name: str, ursprung) -> np.ndarray:
        """Lage eines Knotens am Aufbau: sein Ursprung, dazu die Drehung für Lenkrad und Nadeln.

        Gedreht wird um die **lokale** X-Achse des Knotens durch seinen
        Ursprung. Die Drehung des Knotens steckt schon in den Punkten (siehe
        :func:`src.render3d.mesh.laden`); deshalb ``R · Rx · Rᵀ`` mit der
        Knotenausrichtung ``R`` aus :attr:`achsen`. Alle anderen Teile sitzen starr.
        """
        m = matrix.verschiebung(ursprung)
        c = self.cockpit
        if c is None:
            return m
        if name == LENKRAD:
            if not self.lenkwinkel_rad:
                return m
            dreh = matrix.drehung_x(lenkradwinkel(self.lenkwinkel_rad, c.lenkrad_uebersetzung))
        elif name == NADEL_TACHO:
            dreh = matrix.drehung_x(nadelwinkel(self.tempo_kmh, c.tacho_max_kmh, c.tacho_winkel_grad))
        elif name == NADEL_DREHZAHL:
            dreh = matrix.drehung_x(nadelwinkel(self.drehzahl, c.drehzahl_max, c.drehzahl_winkel_grad))
        else:
            return m
        achse = self.achsen.get(name)
        if achse is not None:
            dreh = achse @ dreh @ achse.T
        return m @ dreh

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
        aufbau = basis if karosserie is None else basis @ karosserie
        ergebnis = {KAROSSERIE: aufbau}
        for name, ursprung in self.anbauteile.items():
            ergebnis[name] = aufbau @ self.anbauteil_matrix(name, ursprung)
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
