"""Zustand der Startampel — eine Quelle fuer 3D-Portal und HUD.

Die fuenf Lampen zuenden im Countdown nacheinander (Motorsport-Ampelbatterie),
bei GO gehen alle gleichzeitig aus. Das 3D-Portal (``RaceState``) und die
HUD-Ampel fragen beide diese Funktion, damit sie nie auseinanderlaufen.
"""
from __future__ import annotations

#: Verbleibende Countdown-Sekunden, ab der je ein weiteres Lampenpaar zuendet —
#: unabhaengig von der tatsaechlichen Laenge des Countdowns (3 s lokal,
#: 3,5 s online).
AMPEL_SCHWELLEN_S = (2.5, 2.0, 1.5, 1.0, 0.5)

LAMPEN = len(AMPEL_SCHWELLEN_S)

#: Art der Startsignale: ein kurzer Piep je Lampenzuendung, bei GO der lange Ton.
SIGNAL_PIEP = "piep"
SIGNAL_LOS = "los"

#: Verbleibende Countdown-Sekunden, bei denen je ein Startsignal klingen soll —
#: **dieselben** Schwellen wie die Lampen plus GO bei 0,0. Frueher spielte der
#: Ton die ganze ``race-start.wav`` (Piep bei 3, 2, 1, langer Ton bei 0) ab,
#: waehrend die Lampen im 0,5-s-Takt zuenden: der erste Piep lag eine halbe
#: Sekunde vor der ersten Lampe, die Haelfte der Lampen blieb stumm. Jetzt
#: haengt jedes Signal an genau einer Lampe, eine Zeitleiste fuer Bild und Ton.
SIGNAL_ZEITEN_S = AMPEL_SCHWELLEN_S + (0.0,)
SIGNALE = (SIGNAL_PIEP,) * LAMPEN + (SIGNAL_LOS,)


def faelliges_signal(rest_s: float, schon: int, vorlauf_s: float = 0.0,
                     dt: float = 0.0) -> int | None:
    """Nummer des juengsten faelligen Startsignals, sonst ``None``.

    ``schon`` ist die Zahl bereits angestossener Signale (sie laufen der Reihe
    nach). ``vorlauf_s`` ist die Strecke, die der Ton vom Anstossen bis zum
    Ohr braucht (Mixerpuffer): das Signal wird entsprechend frueher angestossen,
    damit es mit der Lampe zusammenfaellt und nicht erst hinterher klingt.
    ``dt`` ist die Bilddauer; die Restzeit gilt am Bildanfang, das Bild zeigt
    sie aber erst am Ende. Mit ``dt / 2`` wird auf das naechstliegende Bild
    gerundet, statt im Mittel ein halbes Bild zu spaet zu klingen.
    Bei einem Ruckler zaehlt nur das juengste Signal: ein Piep, der schon
    vorbei ist, soll nicht nachtraeglich im Pulk klingen.
    """
    jetzt = rest_s - 0.5 * dt
    faellig = None
    for nr in range(schon, len(SIGNAL_ZEITEN_S)):
        if jetzt <= SIGNAL_ZEITEN_S[nr] + vorlauf_s:
            faellig = nr
    return faellig


def fortsetzen_stufe(rest_s: float) -> tuple[int, bool]:
    """Ampel fuer den Neustart nach der Pause (3 s, zuvor "3, 2, 1, LOS!").

    Zeitlauf wie bisher: bis 1 s Restzeit zaehlen die Lampen hoch (die
    Portal-Schwellen, auf 2 s gestreckt), danach alle aus und "LOS!".
    Rueckgabe: (leuchtende Lampen, LOS anzeigen).
    """
    if rest_s <= 1.0:
        return 0, True
    return ampel_stufe((rest_s - 1.0) * (AMPEL_SCHWELLEN_S[0] / 2.0)), False


def ampel_stufe(rest_s: float | None) -> int:
    """Anzahl leuchtender Lampen 0..5 bei ``rest_s`` Sekunden Restzeit.

    ``None`` heisst: kein Countdown aktiv (Rennen laeuft) -> alle aus.
    """
    if rest_s is None:
        return 0
    return sum(1 for schwelle in AMPEL_SCHWELLEN_S if rest_s <= schwelle)
