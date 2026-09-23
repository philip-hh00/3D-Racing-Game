"""Nicken, Wanken und Federweg — rein optisch.

Die Physik des Spiels rechnet in 2D und kennt keine Vertikale: ein Fahrzeug
ist ein Polygon, das über eine Ebene rutscht. Sie soll auch so bleiben (siehe
den Umsetzungsplan: *„Physik in 3D. Bleibt 2D."*). Was fehlt, ist nur das
Aussehen — und das lässt sich aus der Beschleunigung ableiten, die dieselbe
Physik ohnehin erzeugt.

Zwei Größen genügen:

* **Nicken** aus der Längsbeschleunigung. Beim Bremsen taucht die Front ein.
* **Wanken** aus der Querbeschleunigung. In der Kurve legt sich der Aufbau
  nach außen.

Und daraus **der Federweg je Rad.** Der ist kein Schmuck, sondern
Voraussetzung: neigt sich die Karosserie und nimmt die Räder mit, gräbt sich
das kurvenäußere Rad in den Asphalt und das innere schwebt darüber. Bei 4 Grad
Wanken und 0,8 m Spurweite sind das gut 5 cm — ein Sechstel Raddurchmesser.
Der Federweg hebt genau diese Bewegung wieder auf, und das Rad bleibt auf der
Straße.

Gerechnet wird im **Fahrzeugkörper**: +X vorne, +Y links, +Z oben. Ein nach
Norden fahrendes Auto, das bremst, taucht mit seiner Front ein und nicht mit
der Seite, die zufällig nach Westen zeigt.
"""
from __future__ import annotations

import math

import numpy as np

#: Erdbeschleunigung. Die Neigung wird in Vielfachen davon angegeben, weil
#: „ein g" eine Größe ist, die man sich vorstellen kann — 0,3 rad/s² nicht.
ERDBESCHLEUNIGUNG = 9.81

#: Nickwinkel bei einem g Längsbeschleunigung. Zwei Grad: ein Serienwagen
#: taucht unter voller Bremsung sichtbar ein, aber er steht nicht auf der
#: Nase. Mehr sieht aus wie ein Boot.
NICK_JE_G = math.radians(2.0)

#: Wankwinkel bei einem g Querbeschleunigung. Etwas mehr als das Nicken —
#: die Wankfeder ist weicher als die Nickfeder, und in der Kurve sieht man
#: es länger.
WANK_JE_G = math.radians(2.6)

#: Obergrenze für beide Winkel. Ein Aufsetzer in der Physik — zwei Fahrzeuge,
#: die sich ineinander verkeilen — erzeugt für ein Bild Beschleunigungen von
#: mehreren hundert g. Ohne Deckel stünde das Auto dann senkrecht.
NEIGUNG_HOECHSTENS_RAD = math.radians(7.0)

#: Wie schnell die Neigung dem Ziel folgt, in 1/s. Eine echte Feder schwingt;
#: das hier kriecht nur nach. Ein Einschwingen mit Überschwinger sähe besser
#: aus und ist die naheliegende Erweiterung — es braucht dann aber eine
#: Dämpfung, die bei jeder Bildrate stabil bleibt.
WEICHHEIT = 6.0

#: Größter Federweg je Rad. Mehr als sechs Zentimeter ist an einem
#: Serienfahrzeug nicht plausibel, und es fiele auf, wenn ein Rad im Radlauf
#: verschwindet.
FEDERWEG_HOECHSTENS_M = 0.06


def _gedeckelt(wert: float, grenze: float) -> float:
    return max(-grenze, min(grenze, wert))


def federweg_m(nabe, nick_rad: float, wank_rad: float) -> float:
    """Wie weit dieses Rad **gegenüber der Karosserie** wandert, in Metern.

    Die Karosserie dreht um Y (Nicken) und X (Wanken). Ein Punkt bei
    ``(x, y, z)`` verliert dabei die Höhe ``x·nick − y·wank`` — für kleine
    Winkel, und größer als sieben Grad wird hier nichts. Genau diesen Betrag
    bekommt das Rad wieder gutgeschrieben, damit es stehen bleibt, wo es steht.

    Vorzeichen: beim Bremsen (``nick > 0``, Front unten) ist der Wert vorne
    **positiv** — das Rad wandert im Fahrzeugkörper nach oben, die Feder geht
    zusammen.
    """
    x, y = float(nabe[0]), float(nabe[1])
    return _gedeckelt(x * nick_rad - y * wank_rad, FEDERWEG_HOECHSTENS_M)


class Aufhaengung:
    """Der Neigungszustand eines Fahrzeugs, weich nachgeführt."""

    def __init__(self, nick_rad: float = 0.0, wank_rad: float = 0.0) -> None:
        self.nick_rad = float(nick_rad)
        self.wank_rad = float(wank_rad)

    def ziel(self, laengs_mss: float, quer_mss: float) -> tuple[float, float]:
        """Die Winkel, die zu dieser Beschleunigung gehören.

        ``laengs_mss`` zeigt nach vorne (+X), ``quer_mss`` nach links (+Y),
        beide in m/s². Bremsen ist also negativ längs, eine Linkskurve positiv
        quer.
        """
        nick = _gedeckelt(-laengs_mss / ERDBESCHLEUNIGUNG * NICK_JE_G,
                          NEIGUNG_HOECHSTENS_RAD)
        wank = _gedeckelt(quer_mss / ERDBESCHLEUNIGUNG * WANK_JE_G,
                          NEIGUNG_HOECHSTENS_RAD)
        return nick, wank

    def fortschreiben(self, laengs_mss: float, quer_mss: float, dt: float) -> None:
        """Einen Zeitschritt nachführen.

        Exponentiell geglättet mit ``1 - exp(-weichheit·dt)`` und damit
        rahmenratenunabhängig: die Faktoren komponieren exakt, viele kleine
        Schritte landen am selben Punkt wie wenige große. Ein naives
        ``x += (ziel - x)·k·dt`` täte das nicht — das Auto nickte bei 30
        Bildern anders als bei 144. Dieselbe Rechnung wie in
        :class:`~src.render3d.camera.Verfolgerkamera`.
        """
        nick_ziel, wank_ziel = self.ziel(laengs_mss, quer_mss)
        alpha = 1.0 - math.exp(-WEICHHEIT * max(0.0, float(dt)))
        self.nick_rad += (nick_ziel - self.nick_rad) * alpha
        self.wank_rad += (wank_ziel - self.wank_rad) * alpha


def beschleunigung_im_fahrzeug(geschwindigkeit_neu, geschwindigkeit_alt,
                               gierwinkel_rad: float, dt: float
                               ) -> tuple[float, float]:
    """Aus zwei Geschwindigkeiten die Beschleunigung längs und quer, in m/s².

    Beide Geschwindigkeiten in **Metern je Sekunde und Weltkoordinaten**; das
    Ergebnis liegt im Fahrzeugkörper, also längs zur Fahrtrichtung und quer
    dazu. Ohne diese Drehung nickte ein nach Westen bremsendes Auto seitlich.
    """
    if dt <= 0.0:
        return 0.0, 0.0
    a = (np.asarray(geschwindigkeit_neu, dtype=np.float64)
         - np.asarray(geschwindigkeit_alt, dtype=np.float64)) / dt
    c, s = math.cos(gierwinkel_rad), math.sin(gierwinkel_rad)
    return float(a[0] * c + a[1] * s), float(-a[0] * s + a[1] * c)
