"""Drehzahlschichten aus den Sweep-Aufnahmen schneiden (Block C, §C4).

Warum überhaupt Schichten: eine einzelne Schleife über den ganzen Drehzahlbereich
zu strecken klingt nach Bandmaschine, nicht nach Motor. Übliche Praxis in
Rennspielen sind mehrere Aufnahmen über den Drehzahlbereich verteilt, zwischen
denen überblendet wird — jede einzelne wird dann nur noch leicht verstimmt, und
genau das hält den Klang glaubwürdig.

Aufgenommen wurden hier keine Einzeldrehzahlen, sondern zwei Sweeps. Die lassen
sich aber aufschneiden: an jeder Stelle eines Sweeps steht der Motor bei einer
anderen Drehzahl, also liefert jeder Abschnitt eine Schicht.

    py -3.11 tools/motor_schichten.py            nur messen
    py -3.11 tools/motor_schichten.py --schreiben

Geschrieben wird ``<motor>-l<n>.wav`` plus eine ``motor_schichten.json`` mit dem
gemessenen Grundton je Schicht — daraus ergibt sich später, wie weit eine
Schicht verstimmt werden darf, bevor die nächste übernimmt.
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
SR = 48000

#: Je Sweep: (Quelldatei, Name der Schichten, Anzahl).
QUELLEN = [
    ("car-engine-reving-sport.wav", "motor-sport", 4),
    ("car-engine-max-normal.wav",   "motor-normal", 3),
    ("car-electric-reving.wav",     "motor-electric", 3),
]
#: Grundschicht je Motor: der Leerlauf. Er ist die unterste Drehzahl.
LEERLAUF = {
    "motor-sport":    "car-engine-idle-sport.wav",
    "motor-normal":   "car-engine-idle-normal.wav",
    "motor-electric": None,       # Elektro hat keinen eigenen Leerlauf
}

SCHICHT_MS = 130.0     # Länge einer Schicht
BLENDE_MS = 25.0       # Überblendung am Rundlauf


def _mono(daten: np.ndarray) -> np.ndarray:
    return daten.mean(axis=1) if daten.ndim > 1 else daten


def grundton(mono: np.ndarray, sr: int, lo: float = 30.0, hi: float = 600.0) -> float:
    """Grundfrequenz per Autokorrelation.

    Bei Motoren ist das die Zündfrequenz oder ein Vielfaches davon. Für die
    Verstimmung zählt ohnehin nur das **Verhältnis** der Schichten zueinander,
    nicht der absolute Wert — deshalb reicht dieses einfache Verfahren.
    """
    x = mono - float(np.mean(mono))
    if len(x) < 512:
        return 0.0
    korr = np.correlate(x, x, mode="full")[len(x) - 1:]
    lo_i, hi_i = int(sr / hi), min(int(sr / lo), len(korr) - 1)
    if lo_i >= hi_i:
        return 0.0
    versatz = lo_i + int(np.argmax(korr[lo_i:hi_i]))
    return sr / versatz if versatz else 0.0


def schwerpunkt(mono: np.ndarray, sr: int) -> float:
    spek = np.abs(np.fft.rfft(mono * np.hanning(len(mono))))
    f = np.fft.rfftfreq(len(mono), 1.0 / sr)
    return float(np.sum(f * spek) / (float(np.sum(spek)) or 1e-9))


def rundlauf(stueck: np.ndarray, sr: int) -> np.ndarray:
    """Enden ineinander blenden, damit die Schleife nicht klickt."""
    blende = min(int(sr * BLENDE_MS / 1000), len(stueck) // 3)
    if blende < 8:
        return stueck
    rampe = np.linspace(0.0, 1.0, blende, dtype=np.float32)
    if stueck.ndim > 1:
        rampe = rampe[:, None]
    gemischt = stueck[-blende:] * (1.0 - rampe) + stueck[:blende] * rampe
    return np.concatenate([gemischt, stueck[blende:-blende]]).astype(np.float32)


def schichten(daten: np.ndarray, sr: int, anzahl: int) -> list[tuple[float, np.ndarray]]:
    """Sweep in *anzahl* Schichten schneiden, gleichmäßig über die Länge.

    Der Anfang bleibt draußen: dort setzt der Ton erst ein, das Material taugt
    nicht als Schleife.
    """
    n = int(sr * SCHICHT_MS / 1000)
    laenge = len(daten)
    if laenge < n * 2:
        # Zu kurz zum Aufteilen: eine Schicht aus dem hinteren Teil.
        return [(0.0, rundlauf(daten[-n:], sr))]
    start = int(laenge * 0.18)
    ende = laenge - n
    if ende <= start:
        start, ende = 0, max(1, laenge - n)
    stellen = np.linspace(start, ende, anzahl).astype(int)
    aus = []
    for s in stellen:
        stueck = daten[s:s + n]
        aus.append((s / sr, rundlauf(stueck, sr)))
    return aus


def aufsteigende_folge(werte: list[float]) -> list[bool]:
    """Welche Schichten bilden den größten Stapel, der nach oben heller wird?

    Der Stapel muss von unten nach oben heller werden — das ist die ganze Idee
    dahinter. Wird eine Schicht wieder dunkler, klingt der Motor unter Last
    dumpfer als im Leerlauf, also falsch herum.

    Gesucht wird deshalb die **längste aufsteigende Teilfolge**, nicht bloß der
    erste Verstoß: eine einfache Regel warf bei den Sportschichten ausgerechnet
    die hellste weg, weil der Sweep am Ende wieder abfiel. Bei gleich langen
    Möglichkeiten gewinnt die mit dem helleren Ende — das ist der Klang bei
    Höchstdrehzahl, und der soll aus echtem Material kommen.
    """
    n = len(werte)
    if n == 0:
        return []
    laenge = [1] * n
    vorher = [-1] * n
    for i in range(n):
        for j in range(i):
            if werte[j] < werte[i] and laenge[j] + 1 > laenge[i]:
                laenge[i], vorher[i] = laenge[j] + 1, j
    beste = max(range(n), key=lambda i: (laenge[i], werte[i]))
    drin = [False] * n
    while beste != -1:
        drin[beste] = True
        beste = vorher[beste]
    return drin


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schreiben", action="store_true")
    args = p.parse_args()

    tabelle: dict[str, list[dict]] = {}
    kopf = f"{'Schicht':<26} {'ab s':>6} {'Dauer':>7} {'Grundton':>9} {'Schwerpunkt':>12}"
    print(kopf)
    print("-" * len(kopf))

    for quelle, name, anzahl in QUELLEN:
        pfad = os.path.join(SFX, quelle)
        if not os.path.isfile(pfad):
            print(f"{quelle}: fehlt, übersprungen")
            continue
        daten, sr = sf.read(pfad, always_2d=True, dtype="float32")
        eintraege: list[dict] = []

        leerlauf_datei = LEERLAUF.get(name)
        if leerlauf_datei:
            ll, _sr = sf.read(os.path.join(SFX, leerlauf_datei), always_2d=True,
                              dtype="float32")
            ll_mono = _mono(ll)
            f0 = grundton(ll_mono, sr)
            eintraege.append({"datei": leerlauf_datei, "grundton": round(f0, 1),
                              "schwerpunkt": round(schwerpunkt(ll_mono, sr)),
                              "quelle": "leerlauf"})
            print(f"{leerlauf_datei:<26} {'-':>6} {len(ll)/sr:>6.2f}s "
                  f"{f0:>8.1f}Hz {schwerpunkt(ll_mono, sr):>11.0f}Hz")

        for i, (ab, stueck) in enumerate(schichten(daten, sr, anzahl), start=1):
            mono = _mono(stueck)
            f0 = grundton(mono, sr)
            sp = schwerpunkt(mono, sr)
            datei = f"{name}-l{i}.wav"
            eintraege.append({"datei": datei, "grundton": round(f0, 1),
                              "schwerpunkt": round(sp), "quelle": quelle,
                              "ab_s": round(ab, 3)})
            print(f"{datei:<26} {ab:>6.2f} {len(stueck)/sr:>6.2f}s "
                  f"{f0:>8.1f}Hz {sp:>11.0f}Hz")
            if args.schreiben:
                sf.write(os.path.join(SFX, datei), stueck, sr, subtype="PCM_16")
        for e, drin in zip(eintraege, aufsteigende_folge(
                [x["schwerpunkt"] for x in eintraege])):
            e["passt"] = drin
            if not drin:
                print(f"    ! {e['datei']} passt nicht in die Reihenfolge "
                      f"({e['schwerpunkt']} Hz) -> nicht im Stapel")
        tabelle[name] = eintraege

    if args.schreiben:
        ziel = os.path.join(SFX, "motor_schichten.json")
        with open(ziel, "w", encoding="utf-8") as fh:
            json.dump(tabelle, fh, ensure_ascii=False, indent=1)
        print(f"\nSchichten und {os.path.basename(ziel)} geschrieben.")
    else:
        print("\nNur gemessen. Mit --schreiben werden die Schichten angelegt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
