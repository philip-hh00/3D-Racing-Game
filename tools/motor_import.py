"""Aufgenommene Motorklänge zu Drehzahlschichten verarbeiten (Block C, §C4).

    py -3.11 tools/motor_import.py              nur messen
    py -3.11 tools/motor_import.py --schreiben

Erwartet Aufnahmen in ``data/audio/sfx/aufnahmen/`` nach dem Schema
``<motor>-<upm>.wav`` (konstante Drehzahl) bzw. ``<motor>-rev.wav`` (Hochlauf) —
Einzelheiten in ``Documentation/motorsound_aufnahme.md``.

## Der Punkt, an dem die alten Schnitte scheiterten

Schleifen wurden mit fester Länge geschnitten, ohne Rücksicht darauf, wo im
Arbeitsspiel sie enden. Gemessen lag die Ähnlichkeit zwischen Ende und Anfang
bei −0,36 bis +0,11 — praktisch null. Im Spiel klang das nach Hubschrauber.

Hier wird die Länge deshalb **gesucht statt gerechnet**: geprüft wird direkt, ob
der Anfang der Schleife zu dem passt, was in der Aufnahme nach ihrem Ende kommt
— genau das passiert beim Rundlauf. Die beste Länge gewinnt.

Der naheliegende Weg über ganzzahlige Vielfache der Zündperiode trägt nicht: die
echte Periode ist selten eine ganze Zahl von Samples (bei 6500 U/min sind es
221,5), und über hundert Perioden summiert sich die Rundung zu hörbarer
Phasendrift. Die Ausgabe nennt die Nahtgüte je Schicht — über 0,8 ist sauber.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX = os.path.join(_ROOT, "data", "audio", "sfx")
AUFNAHMEN = os.path.join(SFX, "aufnahmen")
SR = 48000

#: Zielpegel der Motorschleifen. Dieselbe Kategorie wie in
#: tools/sfx_aufbereiten.py — Motoren laufen dauerhaft und mehrfach
#: gleichzeitig, deshalb leiser als Aufpralleffekte.
ZIEL_RMS_DB = -26.0
#: Angestrebte Schleifenlänge. Die tatsächliche weicht ab — gesucht wird die
#: Länge mit der besten Naht in der Nähe dieses Ziels.
SCHLEIFE_MS = 500.0
#: Überblendung als Notnagel, falls keine brauchbare Naht gefunden wird.
BLENDE_MS = 8.0

_MUSTER = re.compile(r"^(?P<motor>[^-]+)-(?P<art>\d+|rev)(?P<schub>-schub)?$",
                     re.IGNORECASE)


def db(x: float) -> float:
    return -99.0 if x <= 1e-9 else 20.0 * float(np.log10(x))


def rms_db(x: np.ndarray) -> float:
    return db(float(np.sqrt(np.mean(x ** 2))))


def laden(pfad: str) -> np.ndarray:
    daten, sr = sf.read(pfad, always_2d=True, dtype="float32")
    if sr != SR:
        from math import gcd
        t = gcd(SR, sr)
        daten = resample_poly(daten, SR // t, sr // t, axis=0).astype(np.float32)
    return daten


def zuendperiode(mono: np.ndarray, sr: int, lo_hz: float = 6.0,
                 hi_hz: float = 400.0) -> int:
    """Wiederholperiode in Samples, über Autokorrelation des Signals.

    Gesucht wird nicht die Zündperiode allein, sondern die Periode, mit der
    sich das Signal **wirklich** wiederholt. Bei einem Motor ist das das ganze
    Arbeitsspiel: die Streuung zwischen den Zylindern wiederholt sich erst,
    wenn alle einmal gefeuert haben. Bei einem Vierzylinder ist das das
    Vierfache der Zündperiode.

    Der Suchbereich reicht deshalb bis 6 Hz hinunter — im Leerlauf dauert ein
    Arbeitsspiel über 6000 Samples, und mit der früheren Untergrenze von 20 Hz
    fand die Suche dort nur einen Zufallstreffer.
    """
    x = mono - float(np.mean(mono))
    if len(x) < sr // 4:
        return 0
    # Nur ein Ausschnitt aus der Mitte - Anfang und Ende koennen Ein- und
    # Ausschwingen enthalten.
    m = x[len(x) // 4: len(x) // 4 * 3]
    korr = np.correlate(m, m, mode="full")[len(m) - 1:]
    lo, hi = int(sr / hi_hz), min(int(sr / lo_hz), len(korr) - 1)
    if lo >= hi:
        return 0
    return lo + int(np.argmax(korr[lo:hi]))


def nahtguete(quelle: np.ndarray, start: int, laenge: int, sr: int) -> float:
    """Wie gut läuft die Schleife rund? 1,0 wäre nahtlos.

    Verglichen wird der **Anfang der Schleife** mit dem, was in der Aufnahme
    unmittelbar **nach ihrem Ende** kommt. Genau das passiert beim Rundlauf: es
    springt zurück auf den Anfang, und wenn dort dasselbe steht, wie es
    weitergegangen wäre, hört man nichts.

    Der frühere Vergleich (erste gegen letzte 20 ms) prüfte etwas anderes und
    war für eine periodisch geschnittene Schleife bedeutungslos.
    """
    mono = quelle.mean(axis=1) if quelle.ndim > 1 else quelle
    n = min(int(sr * 0.02), laenge // 3)
    if n < 8 or start + laenge + n > len(mono):
        return 0.0
    a = mono[start:start + n]
    b = mono[start + laenge:start + laenge + n]
    nenner = (float(np.linalg.norm(a)) * float(np.linalg.norm(b))) or 1e-9
    return float(np.dot(a, b) / nenner)


def schleife_schneiden(daten: np.ndarray, sr: int) -> tuple[np.ndarray, int, float]:
    """Schleife mit der besten Naht herausschneiden.

    Rückgabe: (Schleife, erkannte Zündperiode in Samples, Nahtgüte).
    """
    mono = daten.mean(axis=1)
    periode = zuendperiode(mono, sr)
    ziel = int(sr * SCHLEIFE_MS / 1000)
    reserve = int(sr * 0.02) + 1

    # Die Länge wird nicht gerechnet, sondern gesucht: geprüft wird direkt die
    # Nahtgüte, und die beste gewinnt.
    #
    # Vielfache der erkannten Periode zu nehmen war zu naiv. Die echte Periode
    # ist selten eine ganze Zahl von Samples — bei 6500 U/min sind es 221,5 —,
    # und über hundert Perioden summiert sich die Rundung zu einem halben
    # Zündtakt Phasendrift. Dazu findet die Autokorrelation die Zündperiode und
    # nicht das ganze Arbeitsspiel, sodass auch die Zylinderstreuung nicht
    # zusammenpasst. Beides fällt weg, wenn direkt das Ergebnis geprüft wird.
    start = 0
    laenge = min(ziel, len(daten))
    if len(daten) > ziel + reserve:
        spanne = max(int(sr * 0.02), min(2 * periode if periode > 0 else 0,
                                         ziel // 2))
        start = max(0, min((len(daten) - ziel) // 2,
                           len(daten) - ziel - spanne - reserve))
        beste = -2.0
        for kandidat in range(max(8, ziel - spanne), ziel + spanne + 1):
            if start + kandidat + reserve > len(daten):
                break
            guete = nahtguete(daten, start, kandidat, sr)
            if guete > beste:
                beste, laenge = guete, kandidat

    naht = nahtguete(daten, start, laenge, sr)
    stueck = daten[start:start + laenge]

    # Ueberblenden nur als Notnagel, wenn die Suche keine brauchbare Naht
    # gefunden hat. Bei einem guten Schnitt wuerde die Blende schaden: sie
    # kuerzt die Laenge um ihre eigene Breite und wirft das Ende damit von der
    # Stelle, die gerade gefunden wurde. Genau daran scheiterte der Selbsttest.
    if naht < 0.8:
        blende = min(int(sr * BLENDE_MS / 1000), len(stueck) // 4)
        if blende >= 8:
            rampe = np.linspace(0.0, 1.0, blende, dtype=np.float32)
            if stueck.ndim > 1:
                rampe = rampe[:, None]
            gemischt = stueck[-blende:] * (1.0 - rampe) + stueck[:blende] * rampe
            stueck = np.concatenate([gemischt, stueck[blende:-blende]])

    return stueck.astype(np.float32), periode, naht


def angleichen(daten: np.ndarray, versatz_db: float) -> np.ndarray:
    """Pegel verschieben und Spitze auf −1 dBFS begrenzen."""
    aus = daten * (10 ** (versatz_db / 20.0))
    spitze = float(np.max(np.abs(aus)))
    grenze = 10 ** (-1.0 / 20.0)
    if spitze > grenze:
        aus = aus * (grenze / spitze)
    return aus.astype(np.float32)


def einlesen() -> dict[str, list[dict]]:
    """Aufnahmen nach Motor gruppieren, konstante Drehzahlen nach U/min sortiert."""
    if not os.path.isdir(AUFNAHMEN):
        return {}
    motoren: dict[str, list[dict]] = {}
    for name in sorted(os.listdir(AUFNAHMEN)):
        stamm, endung = os.path.splitext(name)
        if endung.lower() not in (".wav", ".flac", ".mp3", ".ogg"):
            continue
        treffer = _MUSTER.match(stamm)
        if not treffer:
            print(f"  ! {name}: Name passt nicht ins Schema, übersprungen")
            continue
        motor = treffer.group("motor").lower()
        art = treffer.group("art").lower()
        motoren.setdefault(motor, []).append({
            "datei": name,
            "upm": 0 if art == "rev" else int(art),
            "rev": art == "rev",
            "schub": bool(treffer.group("schub")),
        })
    for eintraege in motoren.values():
        eintraege.sort(key=lambda e: (e["rev"], e["schub"], e["upm"]))
    return motoren


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--schreiben", action="store_true")
    args = p.parse_args()

    motoren = einlesen()
    if not motoren:
        print(f"Keine Aufnahmen in {AUFNAHMEN}")
        print("Anleitung: Documentation/motorsound_aufnahme.md")
        return 1

    tabelle: dict[str, list[dict]] = {}
    kopf = (f"{'Schicht':<26} {'U/min':>6} {'Periode':>8} {'RMS vor':>8} "
            f"{'RMS nach':>9} {'Dauer':>7} {'Naht':>6}")
    print(kopf)
    print("-" * len(kopf))

    for motor, eintraege in motoren.items():
        # Innerhalb eines Motors bleiben die Pegelverhaeltnisse erhalten: nur
        # der leiseste Eintrag wird auf den Zielpegel gehoben, alle anderen um
        # denselben Betrag. Sonst waere Volllast genauso laut wie Leerlauf.
        gemessen = []
        for e in eintraege:
            daten = laden(os.path.join(AUFNAHMEN, e["datei"]))
            gemessen.append((e, daten, rms_db(daten.mean(axis=1))))
        leisester = min(w for _e, _d, w in gemessen)
        versatz = ZIEL_RMS_DB - leisester

        ausgabe = []
        for e, daten, vor in gemessen:
            if e["rev"]:
                fertig = angleichen(daten, versatz)
                periode, naht = 0, 0.0
                datei = f"motor-{motor}-rev.wav"
            else:
                stueck, periode, naht = schleife_schneiden(daten, SR)
                fertig = angleichen(stueck, versatz)
                schub = "-schub" if e["schub"] else ""
                datei = f"motor-{motor}-{e['upm']:04d}{schub}.wav"

            marke = "" if (e["rev"] or naht >= 0.8) else "  <- Naht prüfen"
            print(f"{datei:<26} {e['upm'] or '-':>6} {periode or '-':>8} "
                  f"{vor:>7.1f}dB {rms_db(fertig.mean(axis=1)):>8.1f}dB "
                  f"{len(fertig)/SR:>6.2f}s {naht:>+6.2f}{marke}")

            ausgabe.append({"datei": datei, "upm": e["upm"], "rev": e["rev"],
                            "schub": e["schub"], "periode": periode,
                            "nahtguete": round(naht, 3)})
            if args.schreiben:
                sf.write(os.path.join(SFX, datei), fertig, SR, subtype="PCM_16")
        tabelle[motor] = ausgabe
        print()

    if args.schreiben:
        ziel = os.path.join(SFX, "motor_aufnahmen.json")
        with open(ziel, "w", encoding="utf-8") as fh:
            json.dump(tabelle, fh, ensure_ascii=False, indent=1)
        print(f"Schichten und {os.path.basename(ziel)} geschrieben.")
    else:
        print("Nur gemessen. Mit --schreiben werden die Schichten angelegt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
