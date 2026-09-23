"""Die Federung: Nicken, Wanken und der Federweg der Räder.

Rein optisch. Die Physik des Spiels rechnet in 2D und kennt weder Nicken noch
Wanken; beides wird aus der Beschleunigung abgeleitet, die sie ohnehin
erzeugt. Genau deshalb steht es hier und nicht in ``src/physics``.

Die entscheidende Zusage steht in
:func:`test_rad_bleibt_auf_der_strasse`: **ein Rad bleibt auf der Straße.**
Die Karosserie neigt sich, das Rad nicht — sonst gräbt es sich beim Bremsen in
den Asphalt oder schwebt darüber.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.render3d import federung, matrix, vehicle_node


ERDBESCHLEUNIGUNG = 9.81


# ---------------------------------------------------------------------------
# Aus Beschleunigung werden Winkel
# ---------------------------------------------------------------------------

def _eingeschwungen(aufhaengung, laengs_mss, quer_mss, dauer=3.0, dt=1 / 120):
    """So lange fortschreiben, bis sich nichts mehr ändert."""
    for _ in range(int(dauer / dt)):
        aufhaengung.fortschreiben(laengs_mss, quer_mss, dt)
    return aufhaengung


def test_bremsen_taucht_die_front_ein():
    a = _eingeschwungen(federung.Aufhaengung(), -ERDBESCHLEUNIGUNG, 0.0)
    assert a.nick_rad > 0.0


def test_beschleunigen_hebt_die_front():
    a = _eingeschwungen(federung.Aufhaengung(), +ERDBESCHLEUNIGUNG, 0.0)
    assert a.nick_rad < 0.0


def test_linkskurve_legt_den_wagen_nach_rechts():
    """In der Linkskurve zeigt die Querbeschleunigung nach +Y (links), und der
    Aufbau kippt nach außen, also nach rechts."""
    a = _eingeschwungen(federung.Aufhaengung(), 0.0, +ERDBESCHLEUNIGUNG)
    assert a.wank_rad > 0.0


def test_ein_g_neigt_um_die_vorgesehenen_grade():
    a = _eingeschwungen(federung.Aufhaengung(), -ERDBESCHLEUNIGUNG, 0.0)
    assert math.degrees(a.nick_rad) == pytest.approx(
        math.degrees(federung.NICK_JE_G), rel=0.05)


def test_geradeaus_stellt_sich_zurueck():
    a = _eingeschwungen(federung.Aufhaengung(), -ERDBESCHLEUNIGUNG, 0.0)
    assert a.nick_rad > 0.0
    _eingeschwungen(a, 0.0, 0.0)
    assert a.nick_rad == pytest.approx(0.0, abs=1e-3)


def test_starke_beschleunigung_wird_gedeckelt():
    """Ein Aufsetzer in der Physik darf das Auto nicht auf den Kopf stellen."""
    a = _eingeschwungen(federung.Aufhaengung(), -50 * ERDBESCHLEUNIGUNG, 0.0)
    assert abs(a.nick_rad) <= federung.NEIGUNG_HOECHSTENS_RAD + 1e-9


def test_neigung_ist_rahmenratenunabhaengig():
    """Dieselbe Zeitspanne, in unterschiedlich viele Schritte zerlegt, ergibt
    denselben Winkel — sonst nickt das Auto bei 30 Bildern anders als bei 144."""
    fein = federung.Aufhaengung()
    for _ in range(100):
        fein.fortschreiben(-ERDBESCHLEUNIGUNG, 0.0, 0.01)
    grob = federung.Aufhaengung()
    for _ in range(10):
        grob.fortschreiben(-ERDBESCHLEUNIGUNG, 0.0, 0.1)
    assert fein.nick_rad == pytest.approx(grob.nick_rad, rel=1e-3)


# ---------------------------------------------------------------------------
# Aus Winkeln wird Federweg
# ---------------------------------------------------------------------------

def test_beim_bremsen_federt_vorne_ein_und_hinten_aus():
    """Die Front senkt sich; **gegenüber der Karosserie** wandert das Vorderrad
    also nach oben. Hinten umgekehrt."""
    vorne = federung.federweg_m((1.3, 0.8, 0.33), nick_rad=0.05, wank_rad=0.0)
    hinten = federung.federweg_m((-1.3, 0.8, 0.33), nick_rad=0.05, wank_rad=0.0)
    assert vorne > 0.0
    assert hinten < 0.0
    assert vorne == pytest.approx(-hinten)


def test_in_der_kurve_federt_die_kurvenaussenseite_ein():
    """Linkskurve: der Wagen legt sich nach rechts, rechts federt ein."""
    links = federung.federweg_m((1.3, +0.8, 0.33), nick_rad=0.0, wank_rad=0.05)
    rechts = federung.federweg_m((1.3, -0.8, 0.33), nick_rad=0.0, wank_rad=0.05)
    assert rechts > 0.0
    assert links < 0.0


def test_federweg_ist_gedeckelt():
    weit = federung.federweg_m((2.6, 1.2, 0.33), nick_rad=0.5, wank_rad=0.5)
    assert abs(weit) <= federung.FEDERWEG_HOECHSTENS_M + 1e-9


def test_ohne_neigung_kein_federweg():
    assert federung.federweg_m((1.3, 0.8, 0.33), 0.0, 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Und daraus die Matrizen
# ---------------------------------------------------------------------------

def _knoten():
    plaetze = [
        vehicle_node.Radplatz("rad_vl", np.array([1.3, 0.8, 0.33]), True),
        vehicle_node.Radplatz("rad_vr", np.array([1.3, -0.8, 0.33]), True),
        vehicle_node.Radplatz("rad_hl", np.array([-1.3, 0.8, 0.33]), False),
        vehicle_node.Radplatz("rad_hr", np.array([-1.3, -0.8, 0.33]), False),
    ]
    return vehicle_node.Fahrzeugknoten(plaetze, 0.66)


def _radhoehe(knoten, name, pos=(10.0, 5.0, 0.0), gier=0.0):
    """Die Welthöhe der Radmitte — die Verschiebung in der Modellmatrix."""
    return float(knoten.matrizen(pos, gier)[name][2, 3])


@pytest.mark.parametrize("nick, wank", [
    (0.0, 0.0), (0.06, 0.0), (-0.06, 0.0), (0.0, 0.06), (0.05, -0.04),
])
def test_rad_bleibt_auf_der_strasse(nick, wank):
    """**Die Zusage der ganzen Federung.**

    Die Karosserie neigt sich, das Rad bleibt auf seiner Höhe. Ohne diesen
    Ausgleich gräbt sich das kurvenäußere Rad beim Einlenken in den Asphalt
    und das innere schwebt darüber — bei 4 Grad Wanken und 0,8 m Spurweite
    sind das gut 5 cm, also ein Sechstel Raddurchmesser.
    """
    knoten = _knoten()
    ruhe = {name: _radhoehe(knoten, name) for name in
            ("rad_vl", "rad_vr", "rad_hl", "rad_hr")}
    knoten.neigen(nick_rad=nick, wank_rad=wank)
    for name, hoehe in ruhe.items():
        assert _radhoehe(knoten, name) == pytest.approx(hoehe, abs=1e-3), name


def test_karosserie_neigt_sich_wirklich():
    """Das Gegenstueck: die Karosserie muss sich bewegen, sonst waere der
    Ausgleich der Raeder ein Ausgleich von nichts."""
    knoten = _knoten()
    ruhe = knoten.matrizen((0.0, 0.0, 0.0), 0.0)[vehicle_node.KAROSSERIE].copy()
    knoten.neigen(nick_rad=0.06, wank_rad=0.0)
    geneigt = knoten.matrizen((0.0, 0.0, 0.0), 0.0)[vehicle_node.KAROSSERIE]
    assert not np.allclose(ruhe, geneigt)

    # Beim Bremsen senkt sich die Front: ein Punkt vorne auf dem Dach liegt
    # tiefer als vorher.
    vorne_oben = np.array([2.0, 0.0, 1.4, 1.0])
    assert (geneigt @ vorne_oben)[2] < (ruhe @ vorne_oben)[2]


def test_neigung_wirkt_im_fahrzeugkoerper_nicht_in_der_welt():
    """Gedreht wird um die Achsen des Fahrzeugs, nicht um die der Welt.

    Ein nach Norden fahrendes Auto, das bremst, taucht mit seiner **Front**
    ein — nicht mit der Seite, die zufaellig nach Westen zeigt.
    """
    knoten = _knoten()
    knoten.neigen(nick_rad=0.06, wank_rad=0.0)
    basis = knoten.matrizen((0.0, 0.0, 0.0), math.pi / 2)[vehicle_node.KAROSSERIE]
    # Fahrzeugvorne zeigt bei 90 Grad Gierwinkel nach +Y.
    vorne = basis @ np.array([2.0, 0.0, 1.0, 1.0])
    hinten = basis @ np.array([-2.0, 0.0, 1.0, 1.0])
    assert vorne[2] < hinten[2]
    assert vorne[1] > hinten[1]          # vorne liegt tatsaechlich nach +Y
