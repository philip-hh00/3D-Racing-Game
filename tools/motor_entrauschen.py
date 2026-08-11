"""Rauschteppich aus den Motorschleifen nehmen (Playtest 05.08.2026).

Gemeldet: „alle sounds sind etwas verrauscht hört sich ein wenig so an als
würden die sounds in einem Windkanal aufgenommen werden."

Gemessen stimmt das: in den Elektro-Schleifen stecken nur **20–30 %** der
Energie in den Harmonischen, der Rest ist Breitbandrauschen. Es stammt aus der
Aufnahme (`car-electric-reving`) und wurde beim Bauen der Drehzahlschichten
mitvervielfacht.

**Wie hier entrauscht wird.** Eine Schleife ist periodisch, ihr Spektrum ist
also ein Kamm aus Harmonischen. Alles *zwischen* den Zinken kann nicht vom Motor
stammen — dort sitzt das Rauschen. Statt die Periode zu kennen (sie steht in der
Tabelle, geht aber selten glatt in der Dateilänge auf), wird der Rauschboden
gemessen: der gleitende Median des Betragsspektrums. Was deutlich darüber liegt,
ist ein Zinken und bleibt; der Boden wird abgesenkt.

Gerechnet wird über die **ganze** Schleife auf einmal. Das ist kein Detail: eine
blockweise Verarbeitung würde die Nahtstelle der Schleife zerstören, und die
Schleife ist genau das, was im Spiel endlos läuft.

**Der Rest bleibt stehen.** Abgesenkt wird auf ``BODEN``, nicht auf null. Ein
Motor ohne jedes Rauschen klingt nicht sauber, sondern synthetisch — die
Aufnahme soll ihren Charakter behalten, nur nicht mehr im Windkanal stehen.

    python tools/motor_entrauschen.py            # Elektro, schreibt die Dateien
    python tools/motor_entrauschen.py --messen   # nur messen, nichts ändern

Die Originale wandern nach ``data/audio/sfx/original/`` (dort liegen schon die
unbearbeiteten Aufnahmen aus §C2), falls sie dort noch nicht stehen.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import sfx  # noqa: E402

#: Fensterbreite in Bins, über die der Rauschboden geschätzt wird. Breit genug,
#: dass ein Zinken den Median nicht selbst anhebt, schmal genug, dass der Boden
#: seiner Form über die Frequenz folgt.
FENSTER = 65

#: Wie viel vom geschätzten Boden stehen bleibt. Null wäre steril: ein Motor
#: ohne jedes Rauschen klingt nach Synthesizer, nicht nach Maschine.
BODEN = 0.18

#: Ab diesem Vielfachen des Bodens gilt ein Bin als Zinken und bleibt ganz.
ZINKEN_AB = 3.0

#: Ab hier werden die Hoehen geneigt, und um wie viel bis zur Nyquistfrequenz.
#:
#: Ohne das waere Entrauschen ein Rueckschritt: das Rauschen hat die hohen
#: Obertoene bisher **verdeckt**. Nimmt man es weg, liegen sie frei, und der
#: Anteil ueber 4 kHz steigt von 9,7 auf 17,5 % — genau das Sirren, das weg
#: sollte. Die Kennwerte sagen es vorweg: „Die Energie liegt erst bei hohen
#: Vielfachen - daher das Sirren." Die Neigung bringt den Anteil dorthin
#: zurueck, wo die abgenommene Fassung lag, ohne den Ton selbst anzutasten.
NEIGUNG_AB_HZ = 2200.0
NEIGUNG_BIS = 0.30


def _rauschboden(betrag: np.ndarray) -> np.ndarray:
    """Gleitender Median des Betragsspektrums — der Teppich unter den Zinken."""
    n = len(betrag)
    halb = FENSTER // 2
    # Rand gespiegelt, damit der Boden nicht zu den Enden hin einbricht.
    erweitert = np.concatenate([betrag[halb:0:-1], betrag, betrag[-2:-halb - 2:-1]])
    fenster = np.lib.stride_tricks.sliding_window_view(erweitert, FENSTER)
    return np.median(fenster, axis=-1)[:n]


def entrauschen(x: np.ndarray) -> tuple[np.ndarray, float]:
    """Die Schleife entrauschen. Gibt (Signal, Tonanteil vorher) zurück."""
    spektrum = np.fft.rfft(x)
    betrag = np.abs(spektrum)
    boden = _rauschboden(betrag)

    vorher = float(np.sum(np.maximum(betrag - boden, 0.0) ** 2)
                   / max(float(np.sum(betrag ** 2)), 1e-12))

    # Weich zwischen Boden und Zinken überblenden statt hart zu schalten: eine
    # Kante im Spektrum ist ein Vor- und Nachschwingen in der Zeit.
    ueber = betrag / np.maximum(boden, 1e-12)
    anteil = np.clip((ueber - 1.0) / max(ZINKEN_AB - 1.0, 1e-9), 0.0, 1.0)
    faktor = BODEN + (1.0 - BODEN) * anteil

    fr = np.fft.rfftfreq(len(x), 1.0 / sfx.SR)
    oben = np.clip((fr - NEIGUNG_AB_HZ) / max(fr[-1] - NEIGUNG_AB_HZ, 1e-9), 0.0, 1.0)
    faktor = faktor * (1.0 - (1.0 - NEIGUNG_BIS) * oben)
    return np.fft.irfft(spektrum * faktor, n=len(x)).astype(np.float32), vorher


def _tonanteil(x: np.ndarray) -> float:
    betrag = np.abs(np.fft.rfft(x))
    boden = _rauschboden(betrag)
    return float(np.sum(np.maximum(betrag - boden, 0.0) ** 2)
                 / max(float(np.sum(betrag ** 2)), 1e-12))


def dateien(motor: str) -> list[str]:
    with open(sfx._pfad("motor_aufnahmen.json"), encoding="utf-8") as fh:
        tabelle = json.load(fh)
    return [e["datei"] for e in tabelle.get(motor, [])]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--motor", default="elektro")
    p.add_argument("--messen", action="store_true",
                   help="nur messen, keine Datei anfassen")
    args = p.parse_args()

    sicherung = os.path.join(os.path.dirname(sfx._pfad("motor_aufnahmen.json")),
                             "original")
    os.makedirs(sicherung, exist_ok=True)

    print(f"{'Datei':26s} {'Ton vorher':>11s} {'Ton nachher':>12s}")
    for name in dateien(args.motor):
        pfad = sfx._pfad(name)
        if not os.path.isfile(pfad):
            continue
        # Immer vom Original ausgehen, damit ein zweiter Lauf nicht auf einer
        # schon bearbeiteten Datei aufsetzt.
        quelle = os.path.join(sicherung, name)
        daten, sr = sf.read(quelle if os.path.isfile(quelle) else pfad,
                            always_2d=True, dtype="float32")
        mono = daten.mean(axis=1)
        sauber, vorher = entrauschen(mono)
        nachher = _tonanteil(sauber)
        print(f"{name:26s} {vorher * 100:10.1f}% {nachher * 100:11.1f}%")
        if args.messen:
            continue
        ziel = os.path.join(sicherung, name)
        if not os.path.isfile(ziel):
            shutil.copy2(pfad, ziel)
        # Pegel der Aufnahme halten: entrauschen nimmt Energie weg, und ein
        # leiserer Motor waere eine zweite, ungewollte Aenderung.
        alt = float(np.sqrt(np.mean(np.square(mono))))
        neu = float(np.sqrt(np.mean(np.square(sauber)))) or 1.0
        sauber = np.clip(sauber * (alt / neu), -1.0, 1.0)
        sf.write(pfad, sauber.astype(np.float32), sr)

    if args.messen:
        print("\nNur gemessen — keine Datei geändert.")
    else:
        print(f"\nOriginale liegen in {sicherung}.")


if __name__ == "__main__":
    main()
