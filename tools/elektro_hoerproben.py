"""Hörproben für den Elektro-Motorklang (Playtest 05.08.2026).

Gemeldet: „Motorsound elektrische Fahrzeuge hören sich wie ein summen und
fiepen an, ganz unangenehm."

Gemessen bestätigt: der Elektro liegt im spektralen Schwerpunkt bei 1900–2400 Hz
gegen 1100–1400 Hz beim Verbrenner, und sein Spektrum ist **breit** statt
harmonisch gegliedert — genau das hört man als Summen mit Fiepen darüber.

Was sich dagegen tun lässt, ist keine Rechenfrage, sondern eine Geschmacksfrage.
Deshalb entscheidet hier nicht eine Zahl, sondern das Ohr: dieses Werkzeug legt
vier WAV-Dateien nebeneinander — den heutigen Stand und drei Vorschläge — jeweils
als denselben Drehzahlverlauf, damit sie vergleichbar sind.

    python tools/elektro_hoerproben.py

Ergebnis liegt in ``Release/hoerproben/``. Danach entscheiden und den gewählten
Satz in ``data/audio/motor_klang.json`` bzw. in die Fahrzeug-JSONs übernehmen —
dieses Werkzeug ändert von sich aus **nichts** am Spiel.

**Entschieden am 05.08.2026:** „etwas-dunkler", also Färbung +0,30 über dem
Knie 5000/0,18. Übernommen ist die Probe als **Obergrenze**, nicht als
Mittelwert: die Beanstandung lautete „viel zu hoch und fiepsig", und ein
Fahrzeug heller als das abgenommene Muster fiele wieder darunter. Die drei
Elektros stehen deshalb bei +0,30 / +0,45 / +0,60 — dieselbe Reihenfolge wie
zuvor, aber ganz unterhalb der Probe. Festgehalten in
``tests/test_sfx.py::test_kein_elektro_klingt_heller_als_die_abgenommene_probe``.
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import sfx  # noqa: E402

#: Drehzahlverlauf der Probe: hochziehen, halten, zurücknehmen. Kein reiner
#: Sweep — das Fiepen fällt gerade beim Halten auf, und ein Sweep huscht daran
#: vorbei.
VERLAUF = [(0.0, 900), (2.0, 6000), (3.5, 6000), (6.0, 16000),
           (8.0, 16000), (10.0, 1200)]

SEKUNDEN = VERLAUF[-1][0]

#: Die Vorschläge. ``faerbung`` > 0 nimmt Höhen weg (siehe sfx.Faerbung),
#: ``tonhoehe`` < 1 stimmt die ganze Stimme herunter, ``pegel`` skaliert sie.
#: Nach dem Hoeren am 05.08.2026 gewaehlt: Knie 5000/0,18, und die Schleifen
#: sind seither entrauscht (tools/motor_entrauschen.py). Die drei „im-spiel"-
#: Eintraege sind die Faerbungen, die die Elektro-Fahrzeuge tatsaechlich tragen;
#: „abgenommen" ist die Probe, die sie als Obergrenze festlegt, und „ohne-knie"
#: der alte Stand zum Vergleich.
VARIANTEN = {
    "abgenommen":       dict(faerbung=0.30, tonhoehe=1.00, pegel=1.00,
                             knie=5000.0, komp=0.18),
    "im-spiel-hell":    dict(faerbung=0.30, tonhoehe=1.00, pegel=1.00,
                             knie=5000.0, komp=0.18),   # electric_3
    "im-spiel-mitte":   dict(faerbung=0.45, tonhoehe=1.00, pegel=1.00,
                             knie=5000.0, komp=0.18),   # electric
    "im-spiel-dunkel":  dict(faerbung=0.60, tonhoehe=1.00, pegel=1.00,
                             knie=5000.0, komp=0.18),   # electric_2
    "ohne-knie":        dict(faerbung=0.0,  tonhoehe=1.00, pegel=1.00,
                             knie=0.0,    komp=1.00),
}


def _drehzahl(t: float) -> float:
    """Drehzahl zum Zeitpunkt *t*, linear zwischen den Stützstellen."""
    for (t0, u0), (t1, u1) in zip(VERLAUF, VERLAUF[1:]):
        if t0 <= t <= t1:
            anteil = (t - t0) / max(1e-9, t1 - t0)
            return u0 + (u1 - u0) * anteil
    return VERLAUF[-1][1]


def _probe(faerbung: float, tonhoehe: float, pegel: float,
           knie: float, komp: float) -> np.ndarray:
    stimme = sfx.Motorstimme("elektro", tonhoehe=tonhoehe, faerbung=faerbung)
    if not stimme:
        raise SystemExit("Keine Elektro-Aufnahmen gefunden — nichts zu hören.")
    # Die Probe soll die Einstellung zeigen, nicht die Datei — deshalb hier
    # gesetzt und nicht aus motor_klang.json gelesen.
    stimme.knie_upm = knie
    stimme.kompression = komp
    laenge = stimme.blocklaenge
    stuecke, t = [], 0.0
    while t < SEKUNDEN:
        stuecke.append(stimme.block(_drehzahl(t)))
        t += laenge / sfx.SR
    return np.concatenate(stuecke) * pegel


def _schreiben(pfad: str, welle: np.ndarray) -> None:
    import wave
    spitze = float(np.max(np.abs(welle))) or 1.0
    if spitze > 1.0:                      # nur bremsen, nicht normalisieren:
        welle = welle / spitze            # sonst wäre „leiser" nicht mehr leiser
    daten = (np.clip(welle, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(pfad, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sfx.SR)
        fh.writeframes(daten.tobytes())


def main() -> None:
    ziel = os.path.join("Release", "hoerproben")
    os.makedirs(ziel, exist_ok=True)
    print(f"Drehzahlverlauf: {SEKUNDEN:.0f} s, "
          f"{VERLAUF[0][1]} bis {max(u for _t, u in VERLAUF)} UPM\n")
    for name, werte in VARIANTEN.items():
        welle = _probe(**werte)
        pfad = os.path.join(ziel, f"elektro-{name}.wav")
        _schreiben(pfad, welle)
        sp = np.abs(np.fft.rfft(welle * np.hanning(len(welle))))
        fr = np.fft.rfftfreq(len(welle), 1.0 / sfx.SR)
        schwerpunkt = float(np.sum(sp * fr) / max(1e-9, np.sum(sp)))
        ueber4k = float(np.sum(sp[fr > 4000]) / max(1e-9, np.sum(sp)))
        print(f"  {name:24s} Schwerpunkt {schwerpunkt:6.0f} Hz   "
              f"über 4 kHz {ueber4k * 100:4.1f} %   → {pfad}")
    print("\nZum Vergleich: der Sechszylinder liegt im Schwerpunkt bei "
          "1100–1400 Hz.")
    print("Grundton bei Vollgas (16000 UPM): ohne Knie 3200 Hz, "
          "mit Knie 6000/0,25 noch 1700 Hz.")
    print("Nichts am Spiel wurde geändert — das hier sind nur Hörproben.")


if __name__ == "__main__":
    main()
