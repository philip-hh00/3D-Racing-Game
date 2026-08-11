"""Soundeffekte messen, angleichen und schleifenfähig schneiden (Block C, §C1/C2).

Einmalig ausgeführt, aber bewusst als Skript abgelegt: die Angleichung soll
nachvollziehbar und wiederholbar sein, wenn später Dateien dazukommen. Die
Originale bleiben unangetastet in ``data/audio/sfx/original/``.

    py -3.11 tools/sfx_aufbereiten.py --messen     nur Tabelle, schreibt nichts
    py -3.11 tools/sfx_aufbereiten.py --schreiben  Originale sichern und neu schreiben

Was passiert:

* **Abtastrate vereinheitlichen** auf 48 kHz. Drei Dateien fielen heraus
  (``ui-back`` lag bei 24 kHz, ``click`` und ``race-start`` bei 44,1 kHz).
* **Stille am Anfang kürzen** auf 5 ms. ``ui-back`` startete 230 ms zu spät —
  ein Menüklang, der eine Fünftelsekunde nach dem Druck kommt, wirkt kaputt.
* **Pegel je Kategorie angleichen** (siehe ZIELE). Nicht global: Motoren laufen
  dauerhaft und müssen leiser sein als ein Aufprall, sonst übertönt der Leerlauf
  alles andere.
* **Spitzen begrenzen** auf −1 dBFS. ``car-crash-big`` clippte in der Quelle.
* **Volllastschleifen schneiden**: die beiden „max"-Dateien sind in Wahrheit
  Sweeps. Aus dem gleichmäßigen Mittelstück wird eine Schleife mit
  Überblendung — sonst knackt es bei jedem Rundlauf.

Geschrieben wird WAV: ohne ffmpeg lässt sich kein MP3 erzeugen, und eine zweite
verlustbehaftete Runde über bereits kodiertes Material wäre ohnehin die
schlechtere Wahl.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX = os.path.join(_ROOT, "data", "audio", "sfx")
ORIGINAL = os.path.join(SFX, "original")

ZIEL_SR = 48000
#: Stille vor dem ersten Ton. Nicht auf 0: ein harter Einsatz auf Sample 0
#: knackt, ein paar Millisekunden Vorlauf federn das ab.
VORLAUF_MS = 5.0
#: Ausklang nach dem letzten Ton. Alles darüber ist Speicher ohne Wirkung.
NACHLAUF_MS = 60.0
SPITZE_MAX_DB = -1.0

#: RMS-Zielpegel je Kategorie in dBFS. Motoren bewusst am leisesten — sie
#: laufen ununterbrochen und mehrfach gleichzeitig (ein Kanal je Fahrzeug).
ZIELE = {
    "motor":     -26.0,
    "reifen":    -20.0,
    "aufprall":  -14.0,
    "ui":        -20.0,
    "countdown": -16.0,
}

KATEGORIE = {
    "car-engine-idle-normal":   "motor",
    "car-engine-max-normal":    "motor",
    "car-engine-idle-sport":    "motor",
    "car-engine-reving-sport":  "motor",
    "car-electric-reving":      "motor",
    "tire-screeching-1":        "reifen",
    "tire-screeching-2":        "reifen",
    "car-crash-big":            "aufprall",
    "car-crash-small":          "aufprall",
    "car-wall":                 "aufprall",
    "race-start":               "countdown",
    "click":                    "ui",
    "ui-back":                  "ui",
    "fehler":                   "ui",
}

#: Aus diesen Sweeps wird zusätzlich eine Volllastschleife geschnitten.
SCHLEIFEN_AUS_SWEEP = {
    "car-engine-max-normal":   "car-engine-max-normal-loop",
    "car-engine-reving-sport": "car-engine-max-sport-loop",
}
#: Überblendung am Schleifenübergang. Lang genug, damit der Sprung verschwindet,
#: kurz genug, dass die Periodizität des Motors nicht verwaschen wird.
BLENDE_MS = 25.0


# ── Messen ──────────────────────────────────────────────────────────────────

def db(x: float) -> float:
    return -99.0 if x <= 1e-9 else 20.0 * float(np.log10(x))


def rms_db(x: np.ndarray) -> float:
    return db(float(np.sqrt(np.mean(x ** 2))))


def spitze_db(x: np.ndarray) -> float:
    return db(float(np.max(np.abs(x))))


def _grenzen(mono: np.ndarray, schwelle_db: float = -45.0) -> tuple[int, int]:
    """Erster und letzter Index über der Schwelle (relativ zur Spitze)."""
    spitze = float(np.max(np.abs(mono)))
    if spitze <= 0:
        return 0, len(mono) - 1
    grenze = spitze * (10 ** (schwelle_db / 20.0))
    ueber = np.flatnonzero(np.abs(mono) >= grenze)
    if not ueber.size:
        return 0, len(mono) - 1
    return int(ueber[0]), int(ueber[-1])


#: So lang muss eine Volllastschleife mindestens sein. Kürzer wiederholt sie
#: sich hörbar als Brummen: 40 ms sind 25 Wiederholungen je Sekunde, und das
#: liegt mitten im Hörbereich.
MIN_SCHLEIFE_MS = 110.0


def plateau(mono: np.ndarray, sr: int) -> tuple[int, int]:
    """Gleichmäßigster Abschnitt im oberen Teil eines Sweeps.

    Gesucht wird der längste zusammenhängende Bereich, in dem der spektrale
    Schwerpunkt kaum noch wandert — dort ist der Motor „oben angekommen".

    Die Toleranz wird schrittweise geweitet, bis der Bereich lang genug für
    eine Schleife ist. Mit einer festen Toleranz fiel das Ergebnis je nach
    Datei auf 40 ms zusammen, und so kurz brummt eine Schleife.
    """
    n = max(256, int(sr * 0.02))                   # 20-ms-Raster
    start = int(len(mono) * 0.4)                   # oberes Drittel des Sweeps
    stellen, mitten = [], []
    for i in range(start, len(mono) - n, n // 2):
        s = mono[i:i + n]
        spek = np.abs(np.fft.rfft(s * np.hanning(len(s))))
        f = np.fft.rfftfreq(len(s), 1.0 / sr)
        stellen.append(i)
        mitten.append(float(np.sum(f * spek) / (float(np.sum(spek)) or 1e-9)))
    if len(mitten) < 3:
        return start, len(mono)

    mitten_arr = np.array(mitten)
    bezug = float(np.median(mitten_arr))
    mindest = int(sr * MIN_SCHLEIFE_MS / 1000)

    def laengster_lauf(toleranz: float) -> tuple[int, int]:
        nah = np.abs(mitten_arr - bezug) < toleranz
        bester_start, beste_laenge, lauf_start = 0, 0, None
        for i, ok in enumerate(list(nah) + [False]):
            if ok and lauf_start is None:
                lauf_start = i
            elif not ok and lauf_start is not None:
                if i - lauf_start > beste_laenge:
                    beste_laenge, bester_start = i - lauf_start, lauf_start
                lauf_start = None
        return bester_start, beste_laenge

    for faktor in (0.12, 0.2, 0.3, 0.45, 0.7, 1.0):
        toleranz = max(150.0, bezug * faktor)
        s_idx, laenge = laengster_lauf(toleranz)
        if laenge == 0:
            continue
        von = stellen[s_idx]
        bis = min(stellen[min(s_idx + laenge, len(stellen) - 1)] + n, len(mono))
        if bis - von >= mindest:
            return von, bis
    # Nichts Gleichmäßiges gefunden: den oberen Teil nehmen, lieber etwas
    # Wanderung in der Schleife als eine Schleife, die brummt.
    return max(0, len(mono) - max(mindest, n)), len(mono)


# ── Verarbeiten ─────────────────────────────────────────────────────────────

def laden(pfad: str) -> tuple[np.ndarray, int]:
    daten, sr = sf.read(pfad, always_2d=True, dtype="float32")
    if sr != ZIEL_SR:
        # resample_poly statt einfacher Interpolation: das Tiefpassfilter
        # gehoert dazu, sonst spiegeln sich hohe Anteile hoerbar herunter.
        from math import gcd
        t = gcd(ZIEL_SR, sr)
        daten = resample_poly(daten, ZIEL_SR // t, sr // t, axis=0).astype(np.float32)
    return daten, ZIEL_SR


def zuschneiden(daten: np.ndarray, sr: int) -> np.ndarray:
    mono = daten.mean(axis=1)
    von, bis = _grenzen(mono)
    vorlauf = int(sr * VORLAUF_MS / 1000)
    nachlauf = int(sr * NACHLAUF_MS / 1000)
    a = max(0, von - vorlauf)
    b = min(len(mono), bis + nachlauf)
    return daten[a:b]


def angleichen(daten: np.ndarray, ziel_db: float) -> tuple[np.ndarray, float]:
    """Auf den Zielpegel bringen, danach die Spitze begrenzen.

    Begrenzt wird durch Herunterskalieren, nicht durch Kappen: ein Limiter
    würde den Klang verändern, und die Reserve von 1 dB reicht hier.
    """
    ist = rms_db(daten.mean(axis=1))
    faktor = 10 ** ((ziel_db - ist) / 20.0)
    aus = daten * faktor
    spitze = float(np.max(np.abs(aus)))
    grenze = 10 ** (SPITZE_MAX_DB / 20.0)
    if spitze > grenze:
        aus = aus * (grenze / spitze)
        faktor *= grenze / spitze
    return aus.astype(np.float32), db(faktor)


def schleife_schneiden(daten: np.ndarray, sr: int) -> np.ndarray:
    """Plateau herausschneiden und die Enden ineinander blenden.

    Die Überblendung ist der Punkt: ein roher Schnitt lässt bei jedem Rundlauf
    einen Sprung stehen, und der klickt. Hier wird der Anfang unter das Ende
    gemischt, sodass Ende und Anfang identisch auslaufen.
    """
    mono = daten.mean(axis=1)
    von, bis = plateau(mono, sr)
    stueck = daten[von:bis]
    blende = min(int(sr * BLENDE_MS / 1000), len(stueck) // 3)
    if blende < 8:
        return stueck
    rampe = np.linspace(0.0, 1.0, blende, dtype=np.float32)[:, None]
    kopf = stueck[:blende]
    schwanz = stueck[-blende:]
    gemischt = schwanz * (1.0 - rampe) + kopf * rampe
    return np.concatenate([gemischt, stueck[blende:-blende]]).astype(np.float32)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schreiben", action="store_true",
                   help="Originale sichern und angeglichene WAV schreiben")
    args = p.parse_args()

    quellen = sorted(f for f in os.listdir(SFX)
                     if f.lower().endswith((".mp3", ".wav", ".ogg")))
    if not quellen and os.path.isdir(ORIGINAL):
        quellen = sorted(os.listdir(ORIGINAL))
        basis = ORIGINAL
    else:
        basis = SFX

    kopf = (f"{'Datei':<28} {'Kat':<10} {'RMS vor':>8} {'RMS nach':>9} "
            f"{'Gain':>7} {'Spitze':>8} {'Dauer vor':>10} {'Dauer nach':>11}")
    print(kopf)
    print("-" * len(kopf))

    ergebnisse = []
    for name in quellen:
        stamm = os.path.splitext(name)[0]
        kat = KATEGORIE.get(stamm)
        if kat is None:
            print(f"{name:<28} -- keine Kategorie, übersprungen")
            continue
        daten, sr = laden(os.path.join(basis, name))
        vor_rms, vor_dauer = rms_db(daten.mean(axis=1)), len(daten) / sr
        geschnitten = zuschneiden(daten, sr)
        fertig, gain = angleichen(geschnitten, ZIELE[kat])
        ergebnisse.append((stamm, kat, fertig, sr))
        print(f"{name:<28} {kat:<10} {vor_rms:>7.1f}dB "
              f"{rms_db(fertig.mean(axis=1)):>8.1f}dB {gain:>+6.1f}dB "
              f"{spitze_db(fertig):>7.1f}dB {vor_dauer:>9.2f}s "
              f"{len(fertig)/sr:>10.2f}s")

        if stamm in SCHLEIFEN_AUS_SWEEP:
            schleife = schleife_schneiden(fertig, sr)
            ziel_name = SCHLEIFEN_AUS_SWEEP[stamm]
            ergebnisse.append((ziel_name, kat, schleife, sr))
            # Reines ASCII in der Ausgabe: die Windows-Konsole laeuft in cp1252
            # und wirft bei einem Pfeil eine UnicodeEncodeError.
            print(f"{'  -> ' + ziel_name:<28} {kat:<10} {'':>8} "
                  f"{rms_db(schleife.mean(axis=1)):>8.1f}dB {'':>7} "
                  f"{spitze_db(schleife):>7.1f}dB {'':>10} "
                  f"{len(schleife)/sr:>10.2f}s")

    if not args.schreiben:
        print("\nNur gemessen. Mit --schreiben werden die Dateien ersetzt.")
        return 0

    os.makedirs(ORIGINAL, exist_ok=True)
    if basis == SFX:
        for name in quellen:
            ziel = os.path.join(ORIGINAL, name)
            if not os.path.exists(ziel):
                shutil.move(os.path.join(SFX, name), ziel)
        print(f"\nOriginale gesichert in {ORIGINAL}")

    for stamm, _kat, daten, sr in ergebnisse:
        sf.write(os.path.join(SFX, f"{stamm}.wav"), daten, sr, subtype="PCM_16")
    print(f"{len(ergebnisse)} Dateien geschrieben nach {SFX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
