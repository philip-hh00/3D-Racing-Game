"""Die vier festen Stufen der KI-Fahrer.

Nichts davon ist einstellbar oder wird gespeichert: eine Stufe ist ein Satz
weniger Werte, geeicht mit ``tools/ki_messung.py`` gegen die Rundenzeit von
*Meister* (Ziel: Anfänger +12…21 %, Fortgeschritten +6…12 %, Profi +2,5…6,5 %; gemessen mit
Kompaktwagen, Supercar und Limousine auf gp, city und einer schnellen Editorstrecke).

*Meister* fährt, was das Auto hergibt (1.10.2026: city/Kompaktwagen 21,35 s, die
beste Menschenrunde des Besitzers war 22,09 s); die Lücken darunter kommen aus
``haftung``/``bremsen``/``bremspunkt_m`` (auch auf schnellen Strecken und mit
starken Autos, wo Kehren kaum zählen) und
``kurve_schneiden`` (wirkt vor allem in engen Kehren, z. B. auf *city*, wo
Haftung allein kaum Zeit macht). ``wandabstand_px`` ist für alle gleich: auf
*city* kippt die Rundenzeit zwischen 22 und 26 px um mehr als 15 %, weil die
Kehren dann an die Korridorgrenze stoßen — als Eichgröße ungeeignet.
Rückmeldungen des Besitzers („Profi zu leicht") landen hier.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stufe:
    key: str
    name: str
    haftung: float            # Anteil der Seitenhaftung im Geschwindigkeitsprofil
    bremsen: float            # Anteil der Bremsverzögerung
    bremspunkt_m: float       # so viele Meter früher bremsen als nötig
    wandabstand_px: float     # Ideallinie: Abstand zur Wand
    kurve_schneiden: float    # 0 = volle Scheitelpunkte … 1 = Mittellinie
    fehler_je_min: float      # mittlere Fehler je Minute (verbremst, zu weit, zögert)
    ueberholen_nur_langsame: bool  # überholt nur deutlich langsamere Autos
    bremszone_angriff: bool   # greift innen in der Bremszone an
    verteidigen: bool         # macht vor der Bremszone die Innenseite zu
    mut: float                # 0 … 1: wie eng es im Zweikampf wird
    aufholhilfe: float        # 0 aus … 1 voll (nur unten)


STUFEN: dict[str, Stufe] = {
    "easy": Stufe("easy", "Anfänger", haftung=0.55, bremsen=0.62, bremspunkt_m=4.0,
                  wandabstand_px=22.0, kurve_schneiden=0.38, fehler_je_min=1.5,
                  ueberholen_nur_langsame=True, bremszone_angriff=False, verteidigen=False,
                  mut=0.2, aufholhilfe=1.0),
    "medium": Stufe("medium", "Fortgeschritten", haftung=0.66, bremsen=0.76, bremspunkt_m=3.5,
                    wandabstand_px=22.0, kurve_schneiden=0.35, fehler_je_min=0.8,
                    ueberholen_nur_langsame=False, bremszone_angriff=False, verteidigen=False,
                    mut=0.45, aufholhilfe=0.5),
    "hard": Stufe("hard", "Profi", haftung=0.73, bremsen=0.86, bremspunkt_m=2.0,
                  wandabstand_px=22.0, kurve_schneiden=0.34, fehler_je_min=0.3,
                  ueberholen_nur_langsame=False, bremszone_angriff=True, verteidigen=True,
                  mut=0.7, aufholhilfe=0.0),
    "expert": Stufe("expert", "Meister", haftung=0.88, bremsen=0.95, bremspunkt_m=0.0,
                    wandabstand_px=22.0, kurve_schneiden=0.30, fehler_je_min=0.08,
                    ueberholen_nur_langsame=False, bremszone_angriff=True, verteidigen=True,
                    mut=0.9, aufholhilfe=0.0),
}

REIHE: tuple[str, ...] = ("easy", "medium", "hard", "expert")

#: Anzeige- und Altnamen → Schlüssel. "Einfach"/"Mittel"/"Schwer" standen bis
#: 30.09.2026 in Lobby und Speicherständen.
_NAMEN = {s.name.lower(): k for k, s in STUFEN.items()}
_NAMEN.update({"einfach": "easy", "mittel": "medium", "schwer": "hard"})


def stufe(wert) -> Stufe:
    """Die Stufe zu einem Schlüssel, Anzeigenamen oder Altnamen (sonst Fortgeschritten)."""
    if isinstance(wert, Stufe):
        return wert
    text = str(wert or "").strip().lower()
    if text in STUFEN:
        return STUFEN[text]
    return STUFEN[_NAMEN.get(text, "medium")]
