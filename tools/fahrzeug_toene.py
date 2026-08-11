"""Ein Motorklang je Fahrzeug (Block C, §C3/§C5).

    py -3.11 tools/fahrzeug_toene.py --ziel <ordner>

Grundlage ist die Synthese aus ``tools/motor_prototyp.py``, eingestellt auf die
Kennwerte, die an echten Aufnahmen gemessen wurden. Unterschieden wird auf zwei
Ebenen:

**Je Klasse die Zylinderzahl.** Sie bestimmt die Zündfrequenz und damit den
Charakter: ein Vierzylinder zündet bei gleicher Drehzahl halb so oft wie ein
Achtzylinder, klingt also tiefer und einzelschlägiger. Dazu je Klasse ein
anderes Knie der Abstrahlungsdämpfung — ein großer Motor klingt dumpfer, ein
Rennmotor offener.

**Je Modell eine leichte Färbung.** Innerhalb einer Klasse unterscheiden sich
die drei Modelle nur um ±6 % Tonhöhe und etwas Klangfarbe. Das fällt als
Charakterunterschied auf, ohne dass ein Kompaktwagen plötzlich nach Supercar
klingt — genau die Vorgabe aus §C5.

Elektro läuft über einen eigenen Weg: dort gibt es keine Zündungen, sondern ein
Getriebe- und Wechselrichterpfeifen, dessen Frequenz proportional zur Drehzahl
steigt. Zylinderstreuung wäre dort sinnlos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motor_prototyp import (  # noqa: E402
    LEERLAUF_UPM, MAX_UPM, SR, drehzahlrampe, synthese_nach_messung,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Klasse -> (Zylinder, Knie der Daempfung in Hz). Weniger Zylinder heisst
#: tiefere Zuendfrequenz; ein kleiner Motor darf dafuer heller klingen.
KLASSEN = {
    "Hatchback":    {"zylinder": 4, "knie": 2400.0},
    "Limousine":    {"zylinder": 6, "knie": 1900.0},
    "Drifter":      {"zylinder": 6, "knie": 2600.0},
    "Rennfahrzeug": {"zylinder": 8, "knie": 3000.0},
    "Elektroauto":  {"zylinder": 0, "knie": 4200.0},   # 0 = kein Verbrenner
}

#: Fahrzeug -> Klasse. Reihenfolge wie im Spiel.
FAHRZEUGE = {
    "rookie": "Hatchback", "rookie_2": "Hatchback", "rookie_3": "Hatchback",
    "limousine": "Limousine", "limousine_2": "Limousine", "limousine_3": "Limousine",
    "drifter": "Drifter", "drifter_2": "Drifter", "drifter_3": "Drifter",
    "supercar": "Rennfahrzeug", "supercar_2": "Rennfahrzeug",
    "supercar_3": "Rennfahrzeug",
    "electric": "Elektroauto", "electric_2": "Elektroauto",
    "electric_3": "Elektroauto",
}

#: Das wievielte Modell einer Klasse bekommt welchen Tonhoehenversatz.
#: Das dritte klingt hoeher gedreht als das erste, wie in §C5 beschrieben.
VERSATZ = [-0.06, 0.0, 0.06]
#: Und eine leichte Verschiebung des Daempfungsknies - dieselbe Reihenfolge.
KNIE_FAKTOR = [0.9, 1.0, 1.12]


def synthese_elektro(upm: np.ndarray, last: np.ndarray, kennwerte: dict,
                     sr: int = SR, uebersetzung: float = 9.0,
                     knie: float = 4200.0) -> np.ndarray:
    """Elektroantrieb: Pfeifen statt Zündungen.

    Die Frequenz steigt proportional zur Drehzahl, es gibt keine Arbeitstakte
    und damit weder Zylinderstreuung noch stoßweises Ansauggeräusch. Die
    Obertongewichte stammen aus der Messung der vorhandenen Elektroaufnahme,
    deren Energie erst bei hohen Vielfachen liegt — genau das macht das
    typische Sirren aus.
    """
    rng = np.random.default_rng(31)
    gewichte = list(kennwerte["obertoene"])
    f = upm / 60.0 * uebersetzung
    phase = 2.0 * np.pi * np.cumsum(f) / sr
    anteil = np.clip((upm - LEERLAUF_UPM) / (MAX_UPM - LEERLAUF_UPM), 0.0, 1.0)

    ton = np.zeros(len(upm), dtype=np.float64)
    for k, g in enumerate(gewichte, start=1):
        if g <= 0.02 or float(np.max(f)) * k > sr * 0.45:
            continue
        abstrahlung = 1.0 / (1.0 + (f * k / knie) ** 2)
        ton += g * abstrahlung * np.sin(phase * k)
    ton /= max(1e-9, float(np.max(np.abs(ton))))

    # Wechselrichter und Kuehlung: leises, gleichmaessiges Rauschen. Bewusst
    # NICHT an einen Takt gekoppelt - es gibt keinen.
    rausch = rng.standard_normal(len(upm))
    sos = butter(2, [400.0 / (sr / 2), 6000.0 / (sr / 2)], btype="band", output="sos")
    rausch = sosfilt(sos, rausch)
    rausch /= float(np.sqrt(np.mean(rausch ** 2))) or 1e-9

    klang = ton + rausch * 0.05
    klang *= (0.35 + 0.65 * anteil) * (0.6 + 0.4 * last)
    spitze = float(np.max(np.abs(klang))) or 1e-9
    return (klang / spitze * 0.7).astype(np.float32)


def fuer_fahrzeug(name: str, kennwerte: dict, dauer: float = 5.0) -> np.ndarray:
    klasse = FAHRZEUGE[name]
    einstellung = KLASSEN[klasse]
    modell = ["", "_2", "_3"].index(
        name[len(name.rstrip("0123456789_")):] or "")
    versatz = VERSATZ[modell]
    knie = einstellung["knie"] * KNIE_FAKTOR[modell]

    upm, last = drehzahlrampe(dauer)
    # Tonhoehenversatz ueber die Drehzahl: eine hoeher gedrehte Auslegung
    # klingt ueber den ganzen Bereich etwas heller.
    upm = upm * (1.0 + versatz)

    if einstellung["zylinder"] == 0:
        return synthese_elektro(upm, last, kennwerte["elektro"], knie=knie)

    import motor_prototyp
    alt = motor_prototyp._KNIE_HZ
    try:
        motor_prototyp._KNIE_HZ = knie
        return synthese_nach_messung(upm, last, kennwerte["sport"],
                                     zylinder=einstellung["zylinder"])
    finally:
        motor_prototyp._KNIE_HZ = alt


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ziel", default=os.path.join(_ROOT, "build_tmp", "fahrzeug_toene"))
    p.add_argument("--dauer", type=float, default=5.0)
    args = p.parse_args()
    os.makedirs(args.ziel, exist_ok=True)

    with open(os.path.join(_ROOT, "data", "audio", "motor_kennwerte.json"),
              encoding="utf-8") as fh:
        kennwerte = json.load(fh)["motoren"]

    for name in FAHRZEUGE:
        daten = fuer_fahrzeug(name, kennwerte, args.dauer)
        klasse = FAHRZEUGE[name]
        zyl = KLASSEN[klasse]["zylinder"]
        datei = f"{klasse}-{name}-{zyl or 'E'}zyl.wav"
        sf.write(os.path.join(args.ziel, datei), daten, SR, subtype="PCM_16")
        print(f"{datei:<44} {len(daten)/SR:.1f}s")
    print("\n->", args.ziel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
