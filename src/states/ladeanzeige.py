"""Ein Ladebildschirm für alles, was vor dem Rennen passiert.

Vor dem Start laufen mehrere Schritte nacheinander: die 3D-Welt aufbauen,
auf einer neuen Strecke den Seed-Ghost erzeugen, die Ideallinien der KI
rechnen, die Linien für die Übernahme nach dem Ziel. Bis zum 25.09.2026 hatte
der erste Schritt einen eigenen Bildschirm und der Rest einen zweiten, der
wieder bei 0 % anfing — gemeldet als „vor jedem Rennen gibt es 2
Ladebildschirme". Hier ist es **ein** Balken über alle Schritte.

Jeder Schritt ist ein Abschnitt mit einem Gewicht, das ungefähr seiner
Dauer entspricht; ein Abschnitt, der diesmal nicht vorkommt, bekommt Gewicht
0 und keinen Platz auf dem Balken. Der Balken läuft nie rückwärts.

Was der Spieler liest, steht in :data:`TEXTE` und ist bewusst allgemein:
welche Modelle und Texturen gerade geladen werden, geht ihn nichts an.

Ohne pygame: gezeichnet wird über die übergebene Funktion, damit sich die
Rechnung ohne Fenster prüfen lässt.
"""
from __future__ import annotations

import time
from typing import Callable

#: Abschnitt → Text auf dem Bildschirm (Schlüssel für ``tr``).
TEXTE = {
    "strecke": "Strecke wird aufgebaut",
    "ghost": "Ghost wird vorbereitet",
    "linien": "Gegner lernen die Strecke",
    "uebernahme": "Letzte Vorbereitungen",
}


class Ladeanzeige:
    """Ein Fortschrittsbalken über mehrere gewichtete Abschnitte.

    ``zeichnen(stand, text)`` bekommt den Gesamtstand 0…1 und den Text des
    laufenden Abschnitts. Gezeichnet wird höchstens alle ``takt_s`` Sekunden:
    mit V-Sync wartet jedes Bild auf den Bildwechsel, und Rechenschritte
    melden sich tausendfach (siehe ``tests/test_ghost_seed.py``).
    """

    def __init__(self, abschnitte: list[tuple[str, float]],
                 zeichnen: Callable[[float, str], None],
                 uhr: Callable[[], float] = time.perf_counter,
                 takt_s: float = 1 / 30) -> None:
        gesamt = sum(max(0.0, g) for _, g in abschnitte) or 1.0
        self._grenzen: dict[str, tuple[float, float]] = {}
        pos = 0.0
        for name, gewicht in abschnitte:
            breite = max(0.0, gewicht) / gesamt
            self._grenzen[name] = (pos, pos + breite)
            pos += breite
        self._zeichnen = zeichnen
        self._uhr = uhr
        self._takt_s = takt_s
        self._zuletzt = None
        self._text = TEXTE["strecke"]
        self.stand = 0.0

    def melden(self, abschnitt: str, anteil: float, sofort: bool = False) -> None:
        """Fortschritt ``anteil`` (0…1) innerhalb von ``abschnitt``."""
        von, bis = self._grenzen.get(abschnitt, (self.stand, self.stand))
        anteil = min(1.0, max(0.0, float(anteil)))
        self.stand = max(self.stand, von + (bis - von) * anteil)
        self._text = TEXTE.get(abschnitt, TEXTE["uebernahme"])
        jetzt = self._uhr()
        if sofort or self._zuletzt is None or jetzt - self._zuletzt >= self._takt_s:
            self._zuletzt = jetzt
            self._zeichnen(self.stand, self._text)

    def fertig(self) -> None:
        """Den vollen Balken einmal zeigen."""
        self.stand = 1.0
        self._zuletzt = self._uhr()
        self._zeichnen(1.0, self._text)
