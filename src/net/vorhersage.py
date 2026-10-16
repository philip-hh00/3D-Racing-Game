"""
Hochrechnung der Gegenwart eines fernen Fahrzeugs aus seinem neuesten Paket.

Reine Rechnung ohne pygame/pymunk: ``hochrechnen(lage, h)`` liefert die Lage
(x, y, vx, vy, winkel, omega), die das Fahrzeug *h* Sekunden nach dem Paket
haben wird. ``h`` ist das Alter des Pakets (``NetworkClient.alter_von``),
also der Weg von Absender ueber Relay zur Gegenstelle plus Wartezeit.

Das Modell ist absichtlich klein (bei 60-100 ms Alter reicht das):

* Das Tempo laeuft mit der aus den letzten Paketen geschaetzten Beschleunigung
  weiter, die nach und nach auf null abklingt (``TAU_BESCHLEUNIGUNG``): wer
  bremst, bremst weiter, aber ewig tut es keiner.
* Die Fahrtrichtung dreht mit der gemeldeten Gierrate, als Kreisbogen. Die
  Gierrate wird von der Lenkeingabe gelenkt (``eingaben``): das Auto
  schwenkt nach einem Lenkausschlag erst mit Verzug ein, die Eingabe weiss
  das eine Rampe frueher als die Gierrate.
* Das Tempo kann nicht unter null fallen: eine Bremsung hochgerechnet endet
  im Stand, nicht im Rueckwaertsfahren.

Einheiten wie im Spiel: px, px/s, rad.
"""
from __future__ import annotations

import math

#: Schrittweite der Hochrechnung (s). Bei 55 m/s sind 10 ms gut 0,5 m Bogen.
SCHRITT = 0.01
#: Abklingzeit der geschaetzten Beschleunigung und der Gierratenaenderung (s).
TAU_BESCHLEUNIGUNG = 0.35
TAU_GIERRATE = 0.5
#: Glaettung der Beschleunigungsschaetzung zwischen zwei Paketen (Anteil des
#: neuen Werts) und ihre Obergrenze in px/s^2 (40 m/s^2 bei 0,08 m/px).
ALPHA_BESCHLEUNIGUNG = 0.5
A_MAX = 500.0
#: Pakete, die weiter auseinander liegen, ergeben keine brauchbare Schaetzung.
SCHAETZ_ABSTAND_MIN = 0.005
SCHAETZ_ABSTAND_MAX = 0.2
#: Unterhalb dieses Tempos (px/s) dreht die Fahrtrichtung nicht mit.
TEMPO_MIN_DREHEN = 8.0

#: Eingaben als Vorwissen: die Gierrate laeuft dem Sollwert aus der Lenkeingabe
#: mit dieser Zeitkonstante nach (s). ``EINGABEN_AN`` schaltet das fuer den
#: A/B-Vergleich ab, ``EINGABEN_GEWICHT`` mischt Sollwert und gemeldete Gierrate.
EINGABEN_AN = True
EINGABEN_GEWICHT = 1.0
LENK_ZEITKONSTANTE = 0.12
#: Lenkausschlag des Spiels: 35 Grad, mit dem Tempo abnehmend (physics_body.py).
LENK_MAX_GRAD = 35.0
LENK_TEMPO = 500.0
#: Haftgrenze quer: grip * QUER_JE_GRIP px/s^2, mal dem Abschlag, den die
#: Messung gegen die echte Physik ergibt.
QUER_JE_GRIP = 380.0
QUER_FAKTOR = 0.9
#: Ab diesem Schraeglauf (rad, ~11 Grad) gelten die Eingaben nicht mehr.
SCHLUPF_MAX = 0.2
#: Unter diesem Tempo (px/s) sagt die Lenkung nichts ueber die Gierrate.
LENK_TEMPO_MIN = 40.0

def beschleunigung(alt_tempo: float, tempo: float, abstand: float, a_alt: float | None) -> float:
    """Tempoaenderung je Sekunde aus zwei Paketen, geglaettet, begrenzt."""
    if not (SCHAETZ_ABSTAND_MIN <= abstand <= SCHAETZ_ABSTAND_MAX):
        return 0.0 if a_alt is None else a_alt * 0.5
    roh = (tempo - alt_tempo) / abstand
    roh = max(-A_MAX, min(A_MAX, roh))
    if a_alt is None:
        return roh
    return a_alt + (roh - a_alt) * ALPHA_BESCHLEUNIGUNG


def gierrate_soll(tempo: float, lenk: float, grip: float, radstand_px: float) -> float:
    """Gierrate (rad/s), auf die ein Auto bei dieser Lenkeingabe zusteuert:
    Einspurmodell mit dem Lenkausschlag des Spiels, begrenzt durch die
    Querhaftung (bei Vollausschlag fahren alle Autos an der Haftgrenze)."""
    if tempo < LENK_TEMPO_MIN or abs(lenk) < 0.01:
        return 0.0
    ausschlag = math.radians(LENK_MAX_GRAD) / (1.0 + (tempo / LENK_TEMPO) ** 1.2)
    einspur = tempo / max(radstand_px, 1.0) * math.tan(ausschlag * min(1.0, abs(lenk)))
    haftung = max(grip, 0.05) * QUER_JE_GRIP * QUER_FAKTOR / tempo
    return math.copysign(min(einspur, haftung), lenk)


def hochrechnen(lage, h: float, grip: float = 0.85, radstand_px: float = 32.0):
    """Lage nach *h* Sekunden.

    *lage* hat x, y, vx, vy, angle, omega, a_s (Beschleunigung px/s^2 entlang
    der Fahrtrichtung) und optional lenk/hand (Eingaben; ``eing`` sagt, ob sie
    mitgeschickt wurden).
    """
    x, y = lage.x, lage.y
    vx, vy = lage.vx, lage.vy
    tempo = math.hypot(vx, vy)
    richtung = math.atan2(vy, vx) if tempo > 1e-6 else lage.angle
    winkel = lage.angle
    omega0 = lage.omega
    a0 = lage.a_s
    if h <= 0.0:
        return x, y, vx, vy, winkel, omega0
    n = max(1, int(math.ceil(h / SCHRITT)))
    dt = h / n
    t = 0.0
    # Sollwert der Gierrate aus der Lenkeingabe (nicht bei Handbremse: dann
    # rutscht das Heck und die Lenkung bestimmt die Drehung nicht mehr).
    omega_soll = None
    if EINGABEN_AN and getattr(lage, "eing", False) and not getattr(lage, "hand", False):
        # Rutscht das Auto (Fahrtrichtung weicht weit von der Blickrichtung ab),
        # bestimmt die Lenkung die Drehung nicht mehr: dann zaehlt nur die Gierrate.
        schraeg = abs((richtung - winkel + math.pi) % (2.0 * math.pi) - math.pi)
        if schraeg < SCHLUPF_MAX:
            omega_soll = omega0 + EINGABEN_GEWICHT * (
                gierrate_soll(tempo, lage.lenk, grip, radstand_px) - omega0)
    for _ in range(n):
        t += dt
        a = a0 * math.exp(-t / TAU_BESCHLEUNIGUNG)
        omega = omega0
        if omega_soll is not None:
            omega = omega_soll + (omega0 - omega_soll) * math.exp(-t / LENK_ZEITKONSTANTE)
        neues_tempo = max(0.0, tempo + a * dt)
        dreh = omega * dt if neues_tempo > TEMPO_MIN_DREHEN else 0.0
        # Mittelpunktregel: Richtung und Tempo in der Mitte des Schritts
        mitte = 0.5 * (tempo + neues_tempo)
        x += math.cos(richtung + 0.5 * dreh) * mitte * dt
        y += math.sin(richtung + 0.5 * dreh) * mitte * dt
        richtung += dreh
        tempo = neues_tempo
        winkel += omega * dt
    return (x, y, math.cos(richtung) * tempo, math.sin(richtung) * tempo,
            winkel, omega)
