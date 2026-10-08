"""Die wählbaren Kameraansichten eines Menschen im Rennen (ab 1.1.0).

Reine Mathematik und Zustand, kein pygame, kein OpenGL — dieselbe Vereinbarung
wie :mod:`src.render3d.camera` (+X vorne, +Y links, +Z oben, Meter).

Vier Ansichten, per Taste der Reihe nach umschaltbar:

* ``verfolger_fern`` — die bisherige Kamera hinter dem Wagen,
* ``verfolger_nah``  — näher und tiefer dran,
* ``motorhaube``     — starr am Wagen, am Punkt ``cockpit.haube``,
* ``cockpit``        — starr am Wagen, im Augpunkt des Fahrers.

Dazu das **Zurückschauen**: solange es gehalten wird, blickt die aktive Ansicht
nach hinten (Verfolger: die Kamera wechselt vor den Wagen und blickt zurück;
Cockpit: der Blick dreht sich um 180 Grad, aus der Wagenmitte statt vom
Fahrersitz, damit die eigene Kopfstütze nicht im Bild steht; Haube: die
Kamera sitzt am Heck).

:class:`Ansichtskamera` ist **eine** Kamera je Mensch (im Splitscreen also
zwei). Sie hat dieselbe Schnittstelle wie
:class:`~src.render3d.camera.Verfolgerkamera` (``setzen``, ``folgen``, ``auge``,
``ziel``, ``blickmatrix``) und dazu ``sichtfeld_grad``, ``nahe_m``, ``fokus``
und ``innen``. Wer eine andere Kamera braucht (Zuschauer, Zielkamera),
baut sich ein anderes Objekt mit derselben Schnittstelle — der Zeichner fragt
nur diese Eigenschaften ab.

**Für Spiegel (Welle 2):** :meth:`Ansichtskamera.blick_aus` liefert die Lage
(Auge, Blickrichtung, Oben) einer beliebigen Kamera am Wagen, ohne die gewählte
Ansicht zu ändern; ein Spiegel braucht den Wagenzustand
(``pos``, ``gier``, ``aufbau``) und den Punkt seines Knotens
(``spiegel_innen`` / ``spiegel_l`` / ``spiegel_r``).
"""
from __future__ import annotations

import numpy as np

from . import camera, matrix, vehicle_node

VERFOLGER_FERN = "verfolger_fern"
VERFOLGER_NAH = "verfolger_nah"
MOTORHAUBE = "motorhaube"
COCKPIT = "cockpit"

#: Reihenfolge beim Umschalten.
ANSICHTEN = (VERFOLGER_FERN, VERFOLGER_NAH, MOTORHAUBE, COCKPIT)
STANDARD = VERFOLGER_FERN

#: Anzeigenamen (deutsch; die Oberfläche übersetzt sie mit ``tr``).
NAMEN = {
    VERFOLGER_FERN: "Verfolger fern",
    VERFOLGER_NAH: "Verfolger nah",
    MOTORHAUBE: "Motorhaube",
    COCKPIT: "Cockpit",
}

#: Daten der Verfolger: (Abstand, Höhe, Zielhöhe, Sichtfeld, nahe Ebene).
#: „fern“ sind die Werte, an denen die Kamera von Anfang an eingestellt wurde
#: (``tools/fahrtest.py``); „nah“ rückt ein Drittel heran und senkt sich.
VERFOLGER_FERN_WERTE = (7.5, 2.8, 1.0, 55.0, 0.2)
VERFOLGER_NAH_WERTE = (5.0, 1.75, 1.05, 60.0, 0.2)

#: Sichtfeld und nahe Ebene der starren Ansichten. Im Cockpit liegt das
#: Lenkrad einen halben Meter vor dem Auge: die nahe Ebene muss darunter
#: bleiben. Auf der Haube reicht weniger, dort liegt nichts so nah — dafür
#: darf die Ebene nicht in die Frontscheibe oder das Dach schneiden.
MOTORHAUBE_SICHTFELD_GRAD = 60.0
MOTORHAUBE_NAHE_M = 0.15
COCKPIT_SICHTFELD_GRAD = 64.0
COCKPIT_NAHE_M = 0.08

#: Entfernung des Blickziels der starren Ansichten (nur Richtung zählt).
_ZIELWEG_M = 20.0


def normalisiere(wert) -> str:
    """Eine gespeicherte Ansicht prüfen: unbekanntes oder Fremdes wird zur Standardansicht."""
    return wert if isinstance(wert, str) and wert in ANSICHTEN else STANDARD


def naechste(ansicht: str) -> str:
    """Die Ansicht nach ``ansicht``, am Ende wieder von vorn."""
    i = ANSICHTEN.index(normalisiere(ansicht))
    return ANSICHTEN[(i + 1) % len(ANSICHTEN)]


def starr(ansicht: str) -> bool:
    """Ob die Ansicht starr am Wagen sitzt (Haube und Cockpit)."""
    return ansicht in (MOTORHAUBE, COCKPIT)


class Ansichtskamera:
    """Die Kamera eines Menschen: gewählte Ansicht, Zurückschauen, Nachziehen."""

    def __init__(self, ansicht: str = STANDARD,
                 masse: vehicle_node.Cockpitmasse | None = None) -> None:
        self._ansicht = normalisiere(ansicht)
        #: Augpunkt und Haubenpunkt; ohne Angabe wird aus einem mittleren Wagen geschätzt.
        self.masse = masse or vehicle_node.cockpit_aus_masse(4.3, 2.0, 1.4)
        self._rueckblick = False
        self._fern = self._verfolger(VERFOLGER_FERN_WERTE)
        self._nah = self._verfolger(VERFOLGER_NAH_WERTE)
        # Letzter Stand des Wagens, damit ein Wechsel der Ansicht sofort stimmt.
        self._pos = np.zeros(3, dtype=np.float64)
        self._gier = 0.0
        self._aufbau: np.ndarray | None = None
        self._auge = np.zeros(3, dtype=np.float64)
        self._ziel = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        self._oben = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        self._angekommen = False

    @staticmethod
    def _verfolger(werte) -> camera.Verfolgerkamera:
        abstand, hoehe, zielhoehe, _fov, _nahe = werte
        return camera.Verfolgerkamera(abstand_m=abstand, hoehe_m=hoehe, zielhoehe_m=zielhoehe)

    # -- Wahl --------------------------------------------------------------
    @property
    def ansicht(self) -> str:
        return self._ansicht

    def ansicht_setzen(self, ansicht: str) -> None:
        """Eine Ansicht wählen; unbekannte werden zur Standardansicht."""
        neu = normalisiere(ansicht)
        if neu != self._ansicht:
            self._ansicht = neu
            self._neu_ausrichten()

    def wechseln(self) -> str:
        """Zur nächsten Ansicht. Gibt die neue zurück."""
        self.ansicht_setzen(naechste(self._ansicht))
        return self._ansicht

    @property
    def rueckblick(self) -> bool:
        return self._rueckblick

    @rueckblick.setter
    def rueckblick(self, an: bool) -> None:
        an = bool(an)
        if an != self._rueckblick:
            self._rueckblick = an
            self._neu_ausrichten()

    def masse_setzen(self, masse: vehicle_node.Cockpitmasse | None) -> None:
        """Augpunkt und Haubenpunkt des gefahrenen Wagens."""
        if masse is not None:
            self.masse = masse
            self._neu_ausrichten()

    def aufbau_setzen(self, aufbau: np.ndarray | None) -> None:
        """Neigung des Aufbaus (Nicken/Wanken) relativ zum Fahrzeug, wie sie gezeichnet wird.

        Die starren Ansichten hängen daran. Wer sie nicht setzt (Verfolger),
        braucht sie nicht. Die Pose wird sofort neu gerechnet — der Aufbau
        wird erst im selben Bild gesetzt, nachdem die Federung gerechnet hat.
        """
        self._aufbau = None if aufbau is None else np.asarray(aufbau, dtype=np.float64)
        if self._angekommen and starr(self._ansicht):
            self._starr_rechnen()

    # -- Eigenschaften der aktiven Ansicht -----------------------------------
    @property
    def innen(self) -> bool:
        """Ob das Auge im oder am eigenen Wagen sitzt (kein Verfolger)."""
        return starr(self._ansicht)

    @property
    def sichtfeld_grad(self) -> float:
        if self._ansicht == COCKPIT:
            return COCKPIT_SICHTFELD_GRAD
        if self._ansicht == MOTORHAUBE:
            return MOTORHAUBE_SICHTFELD_GRAD
        if self._ansicht == VERFOLGER_NAH:
            return VERFOLGER_NAH_WERTE[3]
        return VERFOLGER_FERN_WERTE[3]

    @property
    def nahe_m(self) -> float:
        if self._ansicht == COCKPIT:
            return COCKPIT_NAHE_M
        if self._ansicht == MOTORHAUBE:
            return MOTORHAUBE_NAHE_M
        return VERFOLGER_FERN_WERTE[4]

    def _verfolger_aktiv(self) -> camera.Verfolgerkamera:
        return self._nah if self._ansicht == VERFOLGER_NAH else self._fern

    # -- Bewegung ----------------------------------------------------------
    def _neu_ausrichten(self) -> None:
        """Nach Wechsel der Ansicht oder des Blicks sofort an die richtige Stelle springen.

        Ein weiches Nachziehen von hinten nach vorn führte die Kamera quer
        durch den Wagen; ein Umschalten ist ein Schnitt.
        """
        if not self._angekommen:
            return
        self.setzen(self._pos, self._gier)

    def setzen(self, fahrzeug_pos_m, gierwinkel_rad: float) -> None:
        """Ohne Nachziehen an die Sollstelle setzen (Rennstart, Wechsel)."""
        self._pos = np.asarray(fahrzeug_pos_m, dtype=np.float64)
        self._gier = float(gierwinkel_rad)
        self._angekommen = True
        for kam in (self._fern, self._nah):
            self._verfolger_stellen(kam, setzen=True, dt=0.0)
        if starr(self._ansicht):
            self._starr_rechnen()
        else:
            self._aus_verfolger()

    def folgen(self, fahrzeug_pos_m, gierwinkel_rad: float, dt: float) -> None:
        """Weich nachziehen (Verfolger) oder starr mitfahren (Haube, Cockpit)."""
        self._pos = np.asarray(fahrzeug_pos_m, dtype=np.float64)
        self._gier = float(gierwinkel_rad)
        if not self._angekommen:
            self.setzen(self._pos, self._gier)
            return
        if starr(self._ansicht):
            self._starr_rechnen()
            # Die Verfolger folgen weiter im Hintergrund nicht: beim Wechsel
            # zurück wird ohnehin neu gesetzt.
            return
        self._verfolger_stellen(self._verfolger_aktiv(), setzen=False, dt=dt)
        self._aus_verfolger()

    def _verfolger_stellen(self, kam: camera.Verfolgerkamera, setzen: bool, dt: float) -> None:
        # Rückblick: die Kamera sitzt vor dem Wagen und blickt zurück. Dafür
        # wird das Fahrzeug um 180 Grad gedreht gemeldet — Auge „hinter“ einem
        # rückwärts gedrehten Wagen ist vor dem echten.
        gier = self._gier + (np.pi if self._rueckblick else 0.0)
        if setzen:
            kam.setzen(self._pos, gier)
        else:
            kam.folgen(self._pos, gier, dt)

    def _aus_verfolger(self) -> None:
        kam = self._verfolger_aktiv()
        self._auge = np.asarray(kam.auge, dtype=np.float64)
        self._ziel = np.asarray(kam.ziel, dtype=np.float64)
        self._oben = np.array([0.0, 0.0, 1.0])

    def _starr_rechnen(self) -> None:
        auge, ziel, oben = self.blick_aus(self._ansicht, self._pos, self._gier,
                                          self._aufbau, self._rueckblick)
        self._auge, self._ziel, self._oben = auge, ziel, oben

    def blick_aus(self, ansicht: str, pos, gier: float, aufbau=None,
                  rueckblick: bool = False):
        """Auge, Ziel und Oben einer starren Ansicht an einem Wagenzustand.

        Ändert nichts an der Kamera — das ist die Stelle, die auch ein Spiegel
        nutzen kann. ``aufbau`` ist die gezeichnete Neigung des Aufbaus.
        """
        m = matrix.fahrzeug(pos, gier).astype(np.float64)
        if aufbau is not None:
            m = m @ np.asarray(aufbau, dtype=np.float64)
        punkt = np.asarray(self.masse.augpunkt if ansicht == COCKPIT else self.masse.haube,
                           dtype=np.float64)
        richtung = np.array([1.0, 0.0, 0.0])
        if rueckblick:
            if ansicht == MOTORHAUBE:
                # Von der Haube zurück sähe man nur die eigene Frontscheibe:
                # die Kamera sitzt dann an der Stelle am Heck.
                punkt = np.array([-punkt[0], punkt[1], punkt[2]])
            else:
                # Im Cockpit blickte man dem eigenen Sitz in die Kopfstütze:
                # der Blick geht von der Wagenmitte aus, wie in den Innenspiegel.
                punkt = np.array([punkt[0], 0.0, punkt[2]])
            richtung = -richtung
        auge = m @ np.array([punkt[0], punkt[1], punkt[2], 1.0])
        vorn = m[:3, :3] @ richtung
        oben = m[:3, :3] @ np.array([0.0, 0.0, 1.0])
        return auge[:3], auge[:3] + vorn * _ZIELWEG_M, oben

    # -- Abfragen ------------------------------------------------------------
    @property
    def auge(self) -> np.ndarray:
        return self._auge.astype(np.float32)

    @property
    def ziel(self) -> np.ndarray:
        return self._ziel.astype(np.float32)

    @property
    def oben(self) -> np.ndarray:
        return self._oben.astype(np.float32)

    @property
    def fokus(self) -> np.ndarray:
        """Wohin die Schattenkarte schaut: bei den starren Ansichten der Wagen selbst."""
        if starr(self._ansicht):
            return (self._pos + np.array([0.0, 0.0, 1.0])).astype(np.float32)
        return self.ziel

    def blickmatrix(self) -> np.ndarray:
        return camera.blick(self._auge, self._ziel, self._oben)
