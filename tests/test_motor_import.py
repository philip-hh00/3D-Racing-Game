"""Drehzahlschichten müssen nahtlos schleifen (Block C, §C4).

Zweimal an derselben Sache gescheitert, deshalb festgehalten:

1. Schleifen wurden mit **fester Länge** geschnitten, ohne Rücksicht auf die
   Wiederholperiode des Motors. Gemessen lag die Nahtgüte bei −0,36 bis +0,11 —
   praktisch null. Im Spiel klang das nach Hubschrauber.
2. Nach der Umstellung auf periodengenaue Schnitte blieb die Naht schlecht,
   weil die anschließende **Überblendung die Länge um ihre eigene Breite
   kürzte** und damit genau die Ausrichtung zerstörte, die der Schnitt gerade
   hergestellt hatte.

Geprüft wird deshalb an einem Signal mit bekannter Periode, ob die Schleife
rund läuft — nicht, ob eine Zwischenrechnung stimmt.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tools"))

# ``motor_import`` zieht scipy (Neuabtastung über resample_poly). Das steht in
# requirements-dev.txt, nicht in requirements.txt — das Spiel braucht es nicht.
# Wer nur die Spielabhängigkeiten installiert hat, soll hier übersprungen werden
# statt beim Einsammeln der Tests abzubrechen: ein Sammelfehler reisst die
# **ganze** Suite ab, und genau das ist der Pipeline am 06.08.2026 passiert.
pytest.importorskip("scipy", reason="nur fuer die Klangwerkzeuge, siehe "
                                    "requirements-dev.txt")

from motor_import import (  # noqa: E402
    SR, nahtguete, schleife_schneiden, zuendperiode,
)


def _motorartig(periode: int, dauer_s: float = 3.0,
                zylinder: int = 4) -> np.ndarray:
    """Signal mit bekannter Wiederholperiode, Aufbau wie ein Motor.

    Mehrere Obertöne plus eine Streuung, die sich erst nach allen Zylindern
    wiederholt — genau das macht die Wiederholperiode länger als die
    Zündperiode.
    """
    n = int(SR * dauer_s)
    t = np.arange(n)
    zuend = periode / zylinder
    phase = 2.0 * np.pi * t / zuend
    signal = np.zeros(n)
    for k, g in ((1, 1.0), (2, 0.5), (3, 0.3), (5, 0.15)):
        signal += g * np.sin(phase * k)
    # Zylinderstreuung: wiederholt sich erst nach `zylinder` Zuendungen.
    welcher = (t // int(zuend)) % zylinder
    signal *= 1.0 + 0.15 * np.array([0.0, 0.4, -0.3, 0.1])[welcher]
    return (signal / np.max(np.abs(signal)) * 0.5).astype(np.float32)[:, None]


def test_findet_die_zuendperiode():
    """Die Autokorrelation findet die kuerzeste starke Wiederholung, und das
    ist die Zuendperiode - nicht das ganze Arbeitsspiel. Wichtig zu wissen,
    weil ein Vielfaches davon deshalb NICHT automatisch die Zylinderstreuung
    trifft."""
    daten = _motorartig(periode=1600, zylinder=4)
    gefunden = zuendperiode(daten.mean(axis=1), SR)
    assert abs(gefunden - 400) <= 2, f"gefunden {gefunden}, erwartet 400"


def test_findet_auch_lange_perioden_im_leerlauf():
    """Bei 900 U/min dauert eine Zuendung 1600 Samples. Mit der frueheren
    Untergrenze von 20 Hz (2400 Samples) lag das noch im Bereich, das ganze
    Arbeitsspiel aber nicht - deshalb reicht die Suche jetzt bis 6 Hz."""
    daten = _motorartig(periode=6400, zylinder=4)
    gefunden = zuendperiode(daten.mean(axis=1), SR)
    assert gefunden > 0
    assert abs(gefunden - 1600) <= 8, f"gefunden {gefunden}, erwartet 1600"


def test_laenge_wird_gesucht_nicht_gerechnet():
    """Vielfache der erkannten Periode zu nehmen war zu naiv: die echte Periode
    ist selten eine ganze Zahl von Samples, und ueber hundert Perioden summiert
    sich die Rundung zu hoerbarer Phasendrift. Die Laenge muss also nicht auf
    der Periodengrenze liegen - sie muss die beste Naht haben."""
    daten = _motorartig(periode=886, zylinder=4)
    stueck, _erkannt, naht = schleife_schneiden(daten, SR)
    assert naht >= 0.8, f"Nahtguete {naht:+.2f}"
    assert int(SR * 0.3) < len(stueck) < int(SR * 0.8), (
        f"Laenge {len(stueck)/SR:.2f}s liegt weit neben dem Ziel von 0,5s")


@pytest.mark.parametrize("periode", [886, 1152, 1600, 3200, 6400])
def test_schleife_laeuft_nahtlos_rund(periode):
    """Der eigentliche Fund. Unter 0,8 klickt es hörbar."""
    daten = _motorartig(periode=periode)
    _stueck, _erkannt, naht = schleife_schneiden(daten, SR)
    assert naht >= 0.8, f"Nahtgüte {naht:+.2f} bei Periode {periode}"


def test_gute_naht_wird_nicht_ueberblendet():
    """Eine Blende kuerzt die Laenge um ihre eigene Breite und wirft das Ende
    damit von der gefundenen Stelle. Bei guter Naht darf sie nicht greifen."""
    daten = _motorartig(periode=1600, zylinder=4)
    stueck, _erkannt, naht = schleife_schneiden(daten, SR)
    assert naht >= 0.8
    # Ohne Blende bleibt die Laenge genau die gefundene; die Blende haette
    # BLENDE_MS abgezogen.
    from motor_import import BLENDE_MS
    zweitens, _e2, _n2 = schleife_schneiden(daten, SR)
    assert len(stueck) == len(zweitens), "nicht wiederholbar"


def test_nahtguete_vergleicht_mit_der_fortsetzung():
    """Der frühere Vergleich (erste gegen letzte 20 ms) prüfte etwas anderes
    und war für eine periodisch geschnittene Schleife bedeutungslos.

    Richtig ist: was steht in der Aufnahme NACH dem Schleifenende, und passt
    das zum Anfang? Genau das passiert beim Rundlauf.
    """
    periode = 1600
    daten = _motorartig(periode=periode)
    # Genau eine Periode ab einer Periodengrenze -> muss nahtlos sein.
    gut = nahtguete(daten, periode * 3, periode, SR)
    assert gut >= 0.9, f"periodengenau, aber Güte nur {gut:+.2f}"
    # Eine halbe Periode versetzt -> darf NICHT als nahtlos gelten.
    schlecht = nahtguete(daten, periode * 3, periode + periode // 2, SR)
    assert schlecht < gut, "halbe Periode versetzt gilt als genauso gut"
