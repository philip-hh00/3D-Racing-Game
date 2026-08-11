"""Drehzahlrampe aus den aufgenommenen Schichten (Block C, §C4).

    py -3.11 tools/motor_schichten_demo.py [--motor 6zyl] [--ziel <ordner>]

Das ist der Wiedergabeweg, den später das Spiel braucht, hier zum Anhören: die
Drehzahl wählt die zwei benachbarten Schichten, jede wird auf die momentane
Drehzahl gestimmt, und zwischen beiden wird überblendet.

Der entscheidende Unterschied zum gescheiterten ersten Anlauf liegt nicht im
Verfahren, sondern im Material. Damals wurden zwei Schleifen über knapp zwei
Oktaven gestreckt — das klingt nach Bandmaschine. Und die Schleifen kamen aus
einer 0,8-Sekunden-Aufnahme, waren also 105 ms lang und wiederholten sich
9,5-mal pro Sekunde: hörbar als Hubschrauber.

Jetzt liegen acht bis zehn Aufnahmen je Motor vor. Der größte Abstand zwischen
zwei Nachbarn ist der Faktor 1,7, die Verstimmung bleibt also klein. Und die
Schleifen sind eine halbe Sekunde lang, wiederholen sich damit zweimal pro
Sekunde statt zehnmal.

Die Breite der Überblendung ist ein Kompromiss, den nur das Ohr entscheiden
kann: breit überblendet klingt es etwas schwebend, schmal überblendet springen
die Wechsel hörbar. ``BLENDE`` stellt das ein.
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
#: Wie breit die Ueberblendung zwischen zwei Schichten ist, als Anteil ihres
#: halben Abstands. 1.0 heisst durchgehend ueberblenden.
#:
#: Bei 1.0 klang es im Hoertest etwas schwebend, bei 0.3 sprangen die Wechsel
#: hoerbar. Der Wert dazwischen ist eine Geschmacksfrage und gehoert ans Ohr,
#: nicht an eine Kennzahl - deshalb per --blende einstellbar.
BLENDE = 1.0


def schichten_laden(motor: str) -> list[tuple[int, np.ndarray]]:
    """[(U/min, Schleife)] nach Drehzahl sortiert. Hochläufe bleiben draußen."""
    with open(os.path.join(SFX, "motor_aufnahmen.json"), encoding="utf-8") as fh:
        tabelle = json.load(fh)
    if motor not in tabelle:
        raise SystemExit(f"Motor {motor!r} nicht in motor_aufnahmen.json "
                         f"(vorhanden: {', '.join(tabelle)})")
    aus = []
    for e in tabelle[motor]:
        if e["rev"] or e["schub"]:
            continue
        daten, sr = sf.read(os.path.join(SFX, e["datei"]), always_2d=True,
                            dtype="float32")
        if sr != SR:
            raise SystemExit(f"{e['datei']}: {sr} Hz, erwartet {SR}")
        aus.append((int(e["upm"]), daten.mean(axis=1).astype(np.float32)))
    aus.sort(key=lambda x: x[0])
    if not aus:
        raise SystemExit(f"Keine Schichten mit konstanter Drehzahl für {motor}")
    return aus


def arbeitsspiel_phase(upm: np.ndarray, sr: int = SR) -> np.ndarray:
    """Fortlaufende Phase in Arbeitsspielen.

    Ein Viertakter braucht für ein Arbeitsspiel zwei Kurbelwellenumdrehungen,
    also ``120 / U/min`` Sekunden. Diese Phase ist der gemeinsame Taktgeber für
    alle Schichten — daran hängt, dass ihre Zündimpulse übereinanderliegen.
    """
    return np.cumsum(upm / (120.0 * sr))


def _lesen(schleife: np.ndarray, phase: np.ndarray, upm_schicht: int,
           sr: int = SR) -> np.ndarray:
    """Schleife an der Stelle abtasten, die zur gemeinsamen Phase gehört.

    Der Trick steckt in der Umrechnung: die Schleife wurde bei *upm_schicht*
    aufgenommen, ein Arbeitsspiel dauert darin also ``120 * sr / upm_schicht``
    Samples. Wird die Schleife mit der gemeinsamen Phase gelesen, ergibt sich
    die Verstimmung von selbst — und zwei gleichzeitig gelesene Schichten
    stehen an derselben Stelle im Arbeitsspiel.

    Ein Versuch, die Zündimpulse benachbarter Schichten zusätzlich zueinander
    auszurichten, ist verworfen: gemessen blieb die Korrelation zwischen zwei
    Schichten in jedem Fall nahe null, und in einem Fall wurde sie durch die
    Ausrichtung schlechter. Zwei verschiedene Aufnahmen korrelieren eben nicht,
    auch nicht auf gleiche Tonhöhe gebracht.
    """
    n = len(schleife)
    spiel_samples = 120.0 * sr / max(1.0, float(upm_schicht))
    zyklen = n / spiel_samples          # Arbeitsspiele in dieser Schleife
    stelle = (phase % zyklen) * spiel_samples
    i0 = np.floor(stelle).astype(np.int64) % n
    frac = (stelle - np.floor(stelle)).astype(np.float32)
    i1 = (i0 + 1) % n
    return schleife[i0] * (1.0 - frac) + schleife[i1] * frac


def rampe(schichten: list[tuple[int, np.ndarray]], dauer: float = 10.0,
          sr: int = SR) -> np.ndarray:
    """Hoch und wieder runter über den gesamten Bereich der Schichten."""
    lo, hi = schichten[0][0], schichten[-1][0]
    n = int(dauer * sr)
    t = np.linspace(0.0, 1.0, n)
    upm = np.where(t < 0.5,
                   lo + (hi - lo) * (t / 0.5),
                   hi - (hi - lo) * ((t - 0.5) / 0.5))

    drehzahlen = np.array([u for u, _s in schichten], dtype=np.float64)
    aus = np.zeros(n, dtype=np.float64)
    # Ein Taktgeber fuer alle Schichten.
    phase = arbeitsspiel_phase(upm, sr)

    for i, (u_i, schleife) in enumerate(schichten):
        links = drehzahlen[i - 1] if i > 0 else u_i - (drehzahlen[1] - u_i)
        rechts = (drehzahlen[i + 1] if i + 1 < len(drehzahlen)
                  else u_i + (u_i - drehzahlen[-2]))

        # Schmale Ueberblendung statt eines Dreiecks ueber den ganzen Abstand.
        #
        # Beim Dreieck spielen auf der halben Strecke zwischen zwei Schichten
        # beide mit 50 Prozent, jede in die Gegenrichtung verstimmt. Ihre
        # Zuendimpulse schieben sich dann ineinander und schweben - genau das
        # klingt synthetisch. Mit BLENDE=0.3 gehoert das mittlere Drittel
        # zwischen zwei Schichten je zur Haelfte einer allein, und ueberblendet
        # wird nur in einem schmalen Streifen um die Mitte.
        gewicht = np.zeros(n)
        for nachbar, seite in ((links, -1), (rechts, +1)):
            mitte = (u_i + nachbar) / 2.0
            halbe = abs(nachbar - u_i) / 2.0
            rand = mitte - seite * halbe * BLENDE      # hier faengt die Blende an
            if seite < 0:
                voll = (upm > rand)
                blend = (upm > mitte - halbe * BLENDE) & (upm <= rand)
            else:
                voll = (upm < rand)
                blend = (upm >= rand) & (upm < mitte + halbe * BLENDE)
            gewicht[voll & (np.sign(upm - u_i) == seite)] = 1.0
            breite = max(1e-9, 2.0 * halbe * BLENDE)
            anteil = np.clip((mitte + halbe * BLENDE - upm) / breite, 0.0, 1.0)
            if seite < 0:
                anteil = 1.0 - anteil
            gewicht[blend] = np.maximum(gewicht[blend], anteil[blend])
        gewicht[np.isclose(upm, u_i, rtol=0.02)] = 1.0
        if i == 0:
            gewicht[upm <= u_i] = 1.0
        if i == len(schichten) - 1:
            gewicht[upm >= u_i] = 1.0
        if not gewicht.any():
            continue
        # Die Verstimmung ergibt sich aus der gemeinsamen Phase von selbst:
        # die Schleife wurde bei u_i aufgenommen, gelesen wird sie mit dem Takt
        # der momentanen Drehzahl.
        stimme = _lesen(schleife, phase, u_i, sr)
        # Wurzelblende: sonst bricht die Lautstaerke in der Mitte ein.
        aus += stimme * np.sqrt(gewicht)

    spitze = float(np.max(np.abs(aus))) or 1e-9
    return (aus / spitze * 0.7).astype(np.float32)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--motor", default="6zyl")
    p.add_argument("--dauer", type=float, default=10.0)
    p.add_argument("--blende", type=float, default=None,
                   help="Breite der Ueberblendung, 0.2 hart bis 1.0 weich")
    p.add_argument("--ziel", default=os.path.join(_ROOT, "build_tmp", "motor_echt"))
    args = p.parse_args()
    os.makedirs(args.ziel, exist_ok=True)

    if args.blende is not None:
        global BLENDE
        BLENDE = args.blende
    schichten = schichten_laden(args.motor)
    print(f"{len(schichten)} Schichten: "
          + ", ".join(f"{u}" for u, _s in schichten) + " U/min")
    abstaende = [schichten[i + 1][0] / schichten[i][0]
                 for i in range(len(schichten) - 1)]
    print(f"groesster Abstand zwischen Nachbarn: Faktor {max(abstaende):.2f}")

    daten = rampe(schichten, args.dauer)
    kennung = f"-b{BLENDE:g}".replace(".", "")
    ziel = os.path.join(args.ziel, f"motor-{args.motor}-rampe{kennung}.wav")
    sf.write(ziel, daten, SR, subtype="PCM_16")
    print(f"\n-> {ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
