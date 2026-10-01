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


def ampel_stufe(rest_s: float | None) -> int:
    """Anzahl leuchtender Lampen 0..5 bei ``rest_s`` Sekunden Restzeit.

    ``None`` heisst: kein Countdown aktiv (Rennen laeuft) -> alle aus.
    """
    if rest_s is None:
        return 0
    return sum(1 for schwelle in AMPEL_SCHWELLEN_S if rest_s <= schwelle)
