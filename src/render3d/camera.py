"""Kameramathematik fuer den 3D-Renderer.

Reine lineare Algebra. Kein pygame, kein OpenGL, keine Spiellogik — siehe
``VEREINBARUNGEN.md`` im selben Verzeichnis (bindend): Koordinatensystem
+X vorne / +Y links / +Z oben, Meter, Matrizen als ``numpy.ndarray``
``shape=(4, 4)`` ``dtype=float32`` in mathematischer Zeilenkonvention
(``v_clip = P @ V @ M @ v_welt`` mit ``v`` als Spaltenvektor). Der Blickraum
folgt der OpenGL-Konvention: die Kamera blickt entlang **-Z**, +Y ist oben,
+X ist rechts.
"""
from __future__ import annotations

import numpy as np


def perspektive(fov_grad: float, seitenverhaeltnis: float,
                 nah_m: float, fern_m: float) -> np.ndarray:
    """Perspektivische Projektionsmatrix (rechtshaendiger Blickraum, Blick entlang -Z).

    ``fov_grad`` ist das vertikale Sichtfeld in Grad. Nach der
    perspektivischen Teilung (``clip / clip.w``) landet die nahe Ebene bei
    NDC-z = -1 und die ferne Ebene bei NDC-z = +1 — das ist die
    OpenGL-Konvention, fuer die diese Matrix gebaut ist.
    """
    f = 1.0 / np.tan(np.radians(fov_grad) / 2.0)
    p = np.zeros((4, 4), dtype=np.float32)
    p[0, 0] = f / seitenverhaeltnis
    p[1, 1] = f
    p[2, 2] = (fern_m + nah_m) / (nah_m - fern_m)
    p[2, 3] = (2.0 * fern_m * nah_m) / (nah_m - fern_m)
    p[3, 2] = -1.0
    return p


def blick(auge, ziel, oben=(0.0, 0.0, 1.0)) -> np.ndarray:
    """Blickmatrix (Weltraum -> Blickraum), klassisches lookAt.

    ``auge`` und ``ziel`` sind Weltkoordinaten (Meter), ``oben`` gibt die
    Weltrichtung "oben" vor (Vorgabe: +Z, siehe Vereinbarungen). Das
    Ergebnis ist unabhaengig davon, welche Weltachse "vorne" bedeutet: die
    lookAt-Konstruktion braucht nur Auge, Ziel und Oben, alle bereits in
    Weltkoordinaten.
    """
    auge = np.asarray(auge, dtype=np.float64)
    ziel = np.asarray(ziel, dtype=np.float64)
    oben = np.asarray(oben, dtype=np.float64)

    vorwaerts = ziel - auge
    vorwaerts /= np.linalg.norm(vorwaerts)
    kreuz = np.cross(vorwaerts, oben)
    if np.linalg.norm(kreuz) < 1e-8:
        # vorwaerts ist (nahezu) parallel zu oben - z.B. Blick exakt nach
        # oben oder unten bei Vorgabe-oben (0,0,1). cross(vorwaerts, oben)
        # waere dann der Nullvektor und die folgende Division durch die Norm
        # erzeugt NaN in der gesamten Matrix, ohne Fehlermeldung (schwarzes
        # Bild). Ersatz-oben: die Welt-Y-Achse, wenn vorwaerts nahe der
        # Welt-Z-Achse liegt (der ueberwiegende Praxisfall, senkrechter
        # Blick nach oben/unten mit Standard-oben +Z), sonst die Welt-Z-Achse.
        # Eine der beiden ist immer garantiert nicht parallel zu vorwaerts,
        # da vorwaerts nicht gleichzeitig zu Z und zu Y parallel sein kann.
        ersatz_oben = (
            np.array([0.0, 1.0, 0.0]) if abs(vorwaerts[2]) > 0.9
            else np.array([0.0, 0.0, 1.0])
        )
        kreuz = np.cross(vorwaerts, ersatz_oben)
    rechts = kreuz / np.linalg.norm(kreuz)
    oben_orthogonal = np.cross(rechts, vorwaerts)

    v = np.eye(4, dtype=np.float64)
    v[0, :3] = rechts
    v[1, :3] = oben_orthogonal
    v[2, :3] = -vorwaerts
    v[:3, 3] = -v[:3, :3] @ auge
    return v.astype(np.float32)


class Verfolgerkamera:
    """Kamera hinter dem Fahrzeug, die weich nachzieht.

    Sitzt ``abstand_m`` hinter dem Fahrzeug (entgegen dessen +X-Richtung,
    gedreht um den Gierwinkel) und ``hoehe_m`` darueber; blickt auf einen
    Punkt ``zielhoehe_m`` ueber dem Fahrzeugursprung.
    """

    def __init__(self, abstand_m: float = 8.0, hoehe_m: float = 3.0,
                 zielhoehe_m: float = 1.0, weichheit: float = 4.0) -> None:
        self._abstand_m = abstand_m
        self._hoehe_m = hoehe_m
        self._zielhoehe_m = zielhoehe_m
        self._weichheit = weichheit
        # Intern float64: die Rahmenratenunabhaengigkeit beruht auf exakter
        # Komposition von Exponentialfaktoren (siehe folgen()); float32
        # wuerde bei vielen kleinen Schritten (z.B. 100x dt=0.01) sichtbar
        # staerker runden als bei wenigen grossen (10x dt=0.1) und die
        # beiden Wege liessen sich nicht mehr auf sinnvolle Toleranz
        # vergleichen. Nach aussen (Property, Blickmatrix) wird auf float32
        # gemaess Vereinbarung gecastet.
        self._auge = np.zeros(3, dtype=np.float64)
        self._ziel = np.zeros(3, dtype=np.float64)

    def _zielwerte(self, fahrzeug_pos_m, gierwinkel_rad):
        fahrzeug_pos_m = np.asarray(fahrzeug_pos_m, dtype=np.float64)
        vorne_richtung = np.array(
            [np.cos(gierwinkel_rad), np.sin(gierwinkel_rad), 0.0],
            dtype=np.float64,
        )
        auge = (
            fahrzeug_pos_m
            - self._abstand_m * vorne_richtung
            + np.array([0.0, 0.0, self._hoehe_m])
        )
        ziel = fahrzeug_pos_m + np.array([0.0, 0.0, self._zielhoehe_m])
        return auge, ziel

    def setzen(self, fahrzeug_pos_m, gierwinkel_rad) -> None:
        """Ohne Nachziehen direkt hinter das Fahrzeug setzen (Rennstart)."""
        self._auge, self._ziel = self._zielwerte(fahrzeug_pos_m, gierwinkel_rad)

    def folgen(self, fahrzeug_pos_m, gierwinkel_rad, dt: float) -> None:
        """Weich nachziehen. Rahmenratenunabhaengig.

        Ein naives ``pos += (ziel - pos) * weichheit * dt`` haengt vom
        gewaehlten dt ab: zwei gleich lange Zeitspannen, in unterschiedlich
        viele Schritte zerlegt, ergeben unterschiedliche Endpositionen
        (Euler-Integration erster Ordnung, Fehler waechst mit dt). Exponentielle
        Glaettung mit dem Faktor ``1 - exp(-weichheit * dt)`` ist dagegen die
        exakte Loesung der Differentialgleichung ``dx/dt = weichheit * (ziel
        - x)`` fuer ein konstantes Ziel: die Faktoren komponieren exakt,
        ``exp(-k*dt1) * exp(-k*dt2) == exp(-k*(dt1+dt2))``. Deshalb landen
        viele kleine Schritte und wenige grosse Schritte ueber dieselbe
        Zeitspanne am selben Punkt (siehe Test auf Rahmenratenunabhaengigkeit).
        """
        ziel_auge, ziel_ziel = self._zielwerte(fahrzeug_pos_m, gierwinkel_rad)
        alpha = 1.0 - np.exp(-self._weichheit * dt)
        self._auge = self._auge + (ziel_auge - self._auge) * alpha
        self._ziel = self._ziel + (ziel_ziel - self._ziel) * alpha

    @property
    def auge(self) -> np.ndarray:
        return self._auge.astype(np.float32)

    @property
    def ziel(self) -> np.ndarray:
        return self._ziel.astype(np.float32)

    def blickmatrix(self) -> np.ndarray:
        return blick(self._auge, self._ziel)
