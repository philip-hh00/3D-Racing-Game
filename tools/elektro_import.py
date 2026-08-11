"""Elektro-Drehzahlschichten aus ``car-electric-reving.wav`` bauen (Block C, §C4).

    py -3.11 tools/elektro_import.py              nur messen
    py -3.11 tools/elektro_import.py --schreiben

## Warum hier synthetisiert und nicht geschnitten wird

Die Datei heißt „reving", ist aber keiner. Gemessen über ihre 3,7 Sekunden
bleibt der stärkste Ton bei 867 Hz und wandert nur von 890 auf 850 Hz — was
ansteigt, ist der **Pegel**, nicht die Tonhöhe. Es gibt also keine Drehzahlleiter
zum Schneiden, so wie sie ``motor_import.py`` aus konstanten Aufnahmen holt.

Aus der Aufnahme kommt deshalb das **Klangbild**, die Leiter wird daraus
gerechnet:

* die Pegel der Harmonischen des Sirrens (1× bis 8× der Grundfrequenz)
* die Rauschbank darunter — Wind und Abrollen, in Hertz festliegend

Bei einem Verbrenner wäre das falsch; sein Klang lebt von Zündimpulsen, die sich
nicht als saubere Obertonreihe schreiben lassen. Ein E-Antrieb ist genau das: ein
Sirren aus wenigen Teiltönen über einem Rauschen. Deshalb trägt der Ansatz hier,
und deshalb ist die Rauschbank **nicht** mitgestimmt — mitgezogenes Rauschen
klingt bei hoher Drehzahl nach Zischen statt nach Fahrtwind.

Die Schleifen laufen konstruktionsbedingt nahtlos: jede Teilschwingung bekommt
eine ganze Zahl Perioden in die Schleifenlänge.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX = os.path.join(_ROOT, "data", "audio", "sfx")
QUELLE = os.path.join(SFX, "car-electric-reving.wav")
SR = 48000
MOTOR = "elektro"

#: Drehzahlleiter. Oben dichter als bei den Verbrennern, weil ein E-Antrieb bis
#: 16000 U/min dreht und ein Schritt sonst über eine ganze Oktave ginge.
DREHZAHLEN = [800, 1600, 2600, 3800, 5200, 7000, 9000, 11500, 14000, 16000]

#: Sirrfrequenz je Umdrehung. 0,2 heißt: die gemessenen 867 Hz gehören zu
#: 4335 U/min, und an der Nenngrenze von 16000 steht das Sirren bei 3200 Hz —
#: hoch, aber nicht schrill.
ORDNUNG = 0.2

#: Pegel der Schleifen über die Drehzahl. Ein E-Antrieb steht fast lautlos da
#: und bleibt auch oben unter einem Verbrenner (dort −26 bis −13 dB).
PEGEL_UNTEN_DB = -32.0
PEGEL_OBEN_DB = -17.0

#: Zahl der berücksichtigten Harmonischen des Sirrens.
HARMONISCHE = 8
#: Angestrebte Schleifenlänge in Millisekunden.
SCHLEIFE_MS = 250.0
#: Fester Startwert, damit zwei Läufe dieselben Schleifen ergeben.
SAAT = 20260730


def db(x: float) -> float:
    return -99.0 if x <= 1e-9 else 20.0 * float(np.log10(x))


def rms_db(x: np.ndarray) -> float:
    return db(float(np.sqrt(np.mean(np.square(x)))))


# ── Messen ──────────────────────────────────────────────────────────────────

def ruhigster_abschnitt(x: np.ndarray, dauer_s: float = 0.7) -> np.ndarray:
    """Das lauteste zusammenhängende Stück — dort ist das Sirren am klarsten.

    Am Anfang und Ende der Aufnahme liegt es unter dem Grundrauschen; eine
    Messung dort würde vor allem den Rauschteppich beschreiben.
    """
    n = int(SR * dauer_s)
    if len(x) <= n:
        return x
    energie = np.convolve(np.square(x), np.ones(n), mode="valid")
    return x[int(np.argmax(energie)):][:n]


def spektrum(x: np.ndarray, laenge: int = 1 << 15) -> tuple[np.ndarray, np.ndarray]:
    f = np.zeros(laenge)
    f[:min(laenge, len(x))] = x[:laenge]
    return (np.abs(np.fft.rfft(f * np.hanning(laenge))),
            np.fft.rfftfreq(laenge, 1.0 / SR))


def grundton(sp: np.ndarray, fr: np.ndarray) -> float:
    """Stärkste Spitze im Bereich, in dem das Sirren liegt."""
    band = (fr > 400.0) & (fr < 1400.0)
    return float(fr[band][int(np.argmax(sp[band]))])


def harmonische_pegel(sp, fr, f0: float) -> list[float]:
    """Amplitude jeder Harmonischen, bezogen auf die stärkste."""
    aus = []
    for n in range(1, HARMONISCHE + 1):
        ziel = f0 * n
        fenster = (fr > ziel - 25.0) & (fr < ziel + 25.0)
        aus.append(float(sp[fenster].max()) if fenster.any() else 0.0)
    groesste = max(aus) or 1.0
    return [a / groesste for a in aus]


def rauschbank(sp, fr, f0: float) -> tuple[np.ndarray, np.ndarray]:
    """Spektrum ohne die Teiltöne, in Terzbändern gemittelt.

    Die Teiltöne werden ausgeschnitten, sonst zöge das Sirren selbst den
    Rauschpegel hoch und die Schleifen bekämen ein Rauschen mit Beule genau da,
    wo ohnehin der Ton sitzt.
    """
    ohne = sp.copy()
    for n in range(1, 40):
        ziel = f0 * n
        if ziel > fr[-1]:
            break
        ohne[(fr > ziel - 40.0) & (fr < ziel + 40.0)] = 0.0

    kanten = [50.0]
    while kanten[-1] < SR / 2:
        kanten.append(kanten[-1] * 2 ** (1 / 3))
    mitten, pegel = [], []
    for a, b in zip(kanten, kanten[1:]):
        m = (fr >= a) & (fr < b) & (ohne > 0)
        if not m.any():
            continue
        mitten.append(float(np.sqrt(a * b)))
        pegel.append(float(np.median(ohne[m])))
    groesste = max(pegel) or 1.0
    return np.array(mitten), np.array(pegel) / groesste


def rausch_anteil(x: np.ndarray, sp, fr, f0: float) -> float:
    """Wie viel der Energie **nicht** im Sirren steckt, 0..1.

    Ohne diese Messung müsste die Mischung aus Ton und Rauschen geraten werden —
    und geraten war in diesem Block schon zweimal falsch.
    """
    ton = 0.0
    for n in range(1, HARMONISCHE + 1):
        fenster = (fr > f0 * n - 40.0) & (fr < f0 * n + 40.0)
        if fenster.any():
            ton += float(np.sum(np.square(sp[fenster])))
    gesamt = float(np.sum(np.square(sp))) or 1e-9
    return max(0.0, min(1.0, 1.0 - ton / gesamt))


# ── Bauen ───────────────────────────────────────────────────────────────────

def schleifenlaenge(f0: float) -> int:
    """Länge, in die eine ganze Zahl Grundschwingungen passt.

    Damit liegt am Rücksprung dieselbe Phase an wie am Anfang — die Schleife
    läuft ohne Naht, und mit ihr jede Harmonische.
    """
    ziel = SR * SCHLEIFE_MS / 1000.0
    perioden = max(1, round(ziel * f0 / SR))
    return int(round(perioden * SR / f0))


def sirren(f0: float, pegel: list[float], laenge: int,
           zufall: np.random.Generator) -> np.ndarray:
    t = np.arange(laenge) / SR
    aus = np.zeros(laenge)
    for n, a in enumerate(pegel, start=1):
        if a <= 0.0005 or f0 * n >= SR / 2:
            continue
        # Ganze Perioden erzwingen: gerundet wird die Frequenz, nicht die Zeit.
        k = max(1.0, round(f0 * n * laenge / SR))
        aus += a * np.sin(2 * np.pi * k * t * SR / laenge
                          + zufall.uniform(0, 2 * np.pi))
    return aus


def rauschen(mitten: np.ndarray, pegel: np.ndarray, laenge: int,
             zufall: np.random.Generator) -> np.ndarray:
    """Rauschen mit der gemessenen Bandverteilung, in Hertz festliegend.

    Im Frequenzbereich erzeugt, damit es sich exakt über die Schleifenlänge
    schließt — zusammengeschnittenes Rauschen knackt an der Naht.
    """
    fr = np.fft.rfftfreq(laenge, 1.0 / SR)
    hoehe = np.interp(np.log(np.maximum(fr, 1.0)), np.log(mitten), pegel,
                      left=pegel[0], right=pegel[-1])
    hoehe[fr < 40.0] = 0.0
    phase = zufall.uniform(0, 2 * np.pi, len(fr))
    return np.fft.irfft(hoehe * np.exp(1j * phase), n=laenge)


def ziel_pegel(upm: int) -> float:
    """Pegel dieser Schicht. Linear über die Drehzahl, nicht über den Index —
    sonst hinge die Lautstärke daran, wie fein die Leiter unterteilt ist."""
    lo, hi = DREHZAHLEN[0], DREHZAHLEN[-1]
    anteil = (upm - lo) / max(1.0, hi - lo)
    return PEGEL_UNTEN_DB + (PEGEL_OBEN_DB - PEGEL_UNTEN_DB) * anteil


def schicht(upm: int, pegel: list[float], mitten, bank, anteil: float,
            zufall: np.random.Generator) -> tuple[np.ndarray, float]:
    """Eine Schleife für diese Drehzahl. Rückgabe: (Schleife, Grundfrequenz)."""
    f0 = ORDNUNG * upm
    laenge = schleifenlaenge(f0)
    ton = sirren(f0, pegel, laenge, zufall)
    grund = rauschen(mitten, bank, laenge, zufall)

    # Auf gleiche Leistung bringen, dann nach dem gemessenen Verhältnis mischen.
    ton /= max(1e-9, float(np.sqrt(np.mean(np.square(ton)))))
    grund /= max(1e-9, float(np.sqrt(np.mean(np.square(grund)))))
    aus = ton * (1.0 - anteil) + grund * anteil

    faktor = 10 ** (ziel_pegel(upm) / 20.0) / max(1e-9, float(np.sqrt(np.mean(np.square(aus)))))
    aus = np.clip(aus * faktor, -1.0, 1.0)
    return aus.astype(np.float32), f0


def naht(schleife: np.ndarray) -> float:
    """Ähnlichkeit von Anfang und dem, was nach dem Ende käme — hier ist das der
    Anfang selbst, gemessen wird trotzdem, damit die Zahl mit den Verbrennern
    vergleichbar bleibt."""
    n = min(int(SR * 0.02), len(schleife) // 3)
    a, b = schleife[:n], np.roll(schleife, -len(schleife))[:n]
    nenner = (float(np.linalg.norm(a)) * float(np.linalg.norm(b))) or 1e-9
    return float(np.dot(a, b) / nenner)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schreiben", action="store_true")
    args = p.parse_args()

    if not os.path.isfile(QUELLE):
        print(f"Nicht gefunden: {QUELLE}")
        return 1

    daten, sr = sf.read(QUELLE, always_2d=True, dtype="float32")
    x = daten.mean(axis=1)
    if sr != SR:
        from scipy.signal import resample_poly
        from math import gcd
        t = gcd(sr, SR)
        x = resample_poly(x, SR // t, sr // t)

    kern = ruhigster_abschnitt(x)
    sp, fr = spektrum(kern)
    f0 = grundton(sp, fr)
    pegel = harmonische_pegel(sp, fr, f0)
    mitten, bank = rauschbank(sp, fr, f0)
    anteil = rausch_anteil(kern, sp, fr, f0)

    print(f"Quelle: {os.path.basename(QUELLE)}  {len(x)/SR:.2f}s  {rms_db(x):.1f} dB")
    print(f"Sirren bei {f0:.0f} Hz, Rauschanteil {anteil*100:.0f} %")
    print("Harmonische: " + "  ".join(f"{n}x {db(a):+.1f}dB"
                                      for n, a in enumerate(pegel, 1)))
    print()

    kopf = f"{'Schicht':<26} {'U/min':>6} {'Sirren':>8} {'Laenge':>8} {'RMS':>8} {'Naht':>6}"
    print(kopf)
    print("-" * len(kopf))

    zufall = np.random.default_rng(SAAT)
    eintraege = []
    for upm in DREHZAHLEN:
        schleife, sirr = schicht(upm, pegel, mitten, bank, anteil, zufall)
        datei = f"motor-{MOTOR}-{upm:04d}.wav"
        g = naht(schleife)
        print(f"{datei:<26} {upm:>6} {sirr:>7.0f}Hz {len(schleife)/SR:>7.3f}s "
              f"{rms_db(schleife):>7.1f}dB {g:>+6.2f}")
        eintraege.append({"datei": datei, "upm": upm, "rev": False,
                          "schub": False, "periode": int(round(SR / sirr)),
                          "nahtguete": round(g, 3)})
        if args.schreiben:
            sf.write(os.path.join(SFX, datei), schleife, SR, subtype="PCM_16")

    if not args.schreiben:
        print("\nNur gemessen. Mit --schreiben werden die Schichten angelegt.")
        return 0

    # Zusammenführen statt überschreiben: die Verbrennerschichten kommen aus
    # motor_import.py und dürfen hier nicht verloren gehen.
    ziel = os.path.join(SFX, "motor_aufnahmen.json")
    tabelle = {}
    if os.path.isfile(ziel):
        with open(ziel, encoding="utf-8") as fh:
            tabelle = json.load(fh)
    tabelle[MOTOR] = eintraege
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(tabelle, fh, ensure_ascii=False, indent=1)
    print(f"\n{len(eintraege)} Schichten und {os.path.basename(ziel)} geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
