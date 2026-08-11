"""Motorklang: Synthese gegen Samples, als hörbarer Vergleich (Block C, §9).

Der Releaseplan führt „Motor-Synthese klingt billig" als Risiko und verlangt
früh einen hörbaren Prototyp. Genau den erzeugt dieses Skript: dieselbe
Drehzahlrampe auf mehreren Wegen, danebengelegt zum Vergleichen.

    py -3.11 tools/motor_prototyp.py --ziel <ordner>

## Warum der erste Anlauf künstlich klang

**Synthese.** Zwei Fehler. Die Zündimpulse waren mathematisch gleichmäßig — ein
echter Motor streut von Zylinder zu Zylinder in Zeitpunkt und Stärke, und genau
diese Unregelmäßigkeit macht den Charakter aus. Und der Auspuff war als
Bandpass modelliert. Ein Auspuff ist aber ein **Rohr mit stehender Welle**: der
Schall läuft hin, wird am Ende reflektiert und läuft zurück. Das gehört als
rückgekoppelte Verzögerung nachgebildet, nicht als Filter — daher kam das
Sirenenhafte.

**Samples.** Zwei Schleifen über knapp zwei Oktaven zu strecken klingt nach
Bandmaschine. Übliche Praxis sind mehrere Aufnahmen über den Drehzahlbereich
verteilt, zwischen denen überblendet wird; jede einzelne wird dann nur noch
leicht verstimmt. Die Schichten dafür schneidet ``tools/motor_schichten.py``
aus den vorhandenen Sweeps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import soundfile as sf
from scipy.signal import butter, lfilter, sosfilt

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SFX = os.path.join(_ROOT, "data", "audio", "sfx")
SR = 48000

LEERLAUF_UPM = 850.0
MAX_UPM = 7200.0
SCHALL_MS = 343.0            # Schallgeschwindigkeit in m/s
#: Knie der Abstrahlungsdaempfung. Darueber faellt das Spektrum ab -
#: derselbe Wert bei jeder Drehzahl, denn Auspuff und Abstrahlung
#: aendern sich nicht mit dem Gasfuss.
_KNIE_HZ = 2200.0


def drehzahlrampe(dauer: float = 8.0, sr: int = SR) -> tuple[np.ndarray, np.ndarray]:
    """Hoch, halten, runter. Zweiter Rückgabewert ist die Last (Gas 0..1).

    Beim Hochziehen liegt Last an, beim Herunterdrehen nicht — ein Motor klingt
    im Schiebebetrieb deutlich anders als unter Volllast, und ohne diesen
    Unterschied klingt jede Rampe nach Spielzeug.
    """
    n = int(dauer * sr)
    t = np.linspace(0.0, 1.0, n)
    upm = np.empty(n)
    last = np.empty(n)
    hoch, halten, runter = t < 0.45, (t >= 0.45) & (t < 0.62), t >= 0.62
    upm[hoch] = np.linspace(LEERLAUF_UPM, MAX_UPM, int(hoch.sum()))
    upm[halten] = MAX_UPM
    upm[runter] = np.linspace(MAX_UPM, LEERLAUF_UPM, int(runter.sum()))
    last[hoch] = 1.0
    last[halten] = 1.0
    # Nicht auf null: ein Motor im Schiebebetrieb ist leiser, aber er laeuft
    # weiter. Bei 0.05 fiel der Pegel um 20 dB ab und das Ende der Rampe war
    # praktisch stumm.
    last[runter] = 0.3
    # Lastwechsel weich, sonst knallt der Übergang.
    kern = np.ones(int(sr * 0.08)) / max(1, int(sr * 0.08))
    last = np.convolve(last, kern, mode="same")
    return upm, last


# ── Weg 1: Synthese ─────────────────────────────────────────────────────────

def _rohr(x: np.ndarray, laenge_m: float, rueckkopplung: float,
          daempfung: float, sr: int) -> np.ndarray:
    """Auspuffrohr als rückgekoppelte Verzögerung (stehende Welle).

    Der Schall läuft durchs Rohr, wird am offenen Ende reflektiert und läuft
    zurück — das ergibt eine Resonanz bei c/(2L) und deren Vielfachen, also
    genau die Kammstruktur, die einen Auspuff ausmacht. Die Dämpfung im
    Rückweg (ein einfacher Tiefpass) sorgt dafür, dass hohe Anteile schneller
    verschwinden als tiefe, wie im echten Rohr.
    """
    d = max(2, int(sr * (2.0 * laenge_m) / SCHALL_MS))
    a = np.zeros(d + 2)
    a[0] = 1.0
    a[d] = -rueckkopplung * (1.0 - daempfung)
    a[d + 1] = -rueckkopplung * daempfung
    return lfilter([1.0], a, x)


def synthese(upm: np.ndarray, last: np.ndarray, sr: int = SR,
             zylinder: int = 4, rohr_m: float = 2.2) -> np.ndarray:
    """Impulszug mit Zylinderstreuung, durch Auspuffrohr und Schalldämpfer."""
    rng = np.random.default_rng(11)

    # Zuendfrequenz: je Umdrehung feuern zylinder/2 Zylinder (Viertakt).
    f = upm / 60.0 * (zylinder / 2.0)
    phase = np.cumsum(f) / sr
    zyklus_nr = np.floor(phase).astype(np.int64)
    frac = phase - zyklus_nr

    # Zylinderstreuung: jeder Zylinder zuendet minimal frueher oder spaeter und
    # etwas staerker oder schwaecher. Ohne das klingt der Motor wie ein
    # Signalgeber - diese Unregelmaessigkeit IST der Charakter.
    versatz = rng.normal(0.0, 0.012, zylinder)
    staerke = 1.0 + rng.normal(0.0, 0.09, zylinder)
    idx = zyklus_nr % zylinder
    frac = (frac - versatz[idx]) % 1.0

    # Asymmetrischer Impuls: harter Einsatz, exponentieller Abfall. Ein echter
    # Auspuffstoss ist keine Glocke, sondern ein Knall mit Nachlauf.
    anteil = np.clip((upm - LEERLAUF_UPM) / (MAX_UPM - LEERLAUF_UPM), 0.0, 1.0)
    tau = 0.13 - 0.07 * anteil
    puls = np.exp(-frac / tau) * staerke[idx]
    puls = puls - float(np.mean(puls))

    # Ansaugrauschen, mit der Last lauter. Bandbegrenzt: oberhalb ~5 kHz hat
    # ein Motor nichts zu melden.
    rauschen = rng.standard_normal(len(upm))
    sos = butter(2, [250.0 / (sr / 2), 5000.0 / (sr / 2)], btype="band", output="sos")
    rauschen = sosfilt(sos, rauschen)
    rauschen /= float(np.sqrt(np.mean(rauschen ** 2))) or 1e-9

    roh = puls + rauschen * (0.05 + 0.22 * last * anteil)

    # Auspuff: langes Rohr fuer den tiefen Grundton, kurzer Schalldaempfer
    # darueber. Unter Last ist der Auspuff offener - weniger Daempfung, mehr
    # Rasseln; im Schiebebetrieb schluckt er mehr.
    rueck = 0.55 + 0.25 * float(np.mean(last))
    klang = _rohr(roh, rohr_m, rueck, 0.35, sr)
    klang = _rohr(klang, 0.45, 0.30, 0.6, sr)

    # Karosserie und Abstrahlung: alles ueber ~7 kHz gehoert nicht dazu.
    sos_lp = butter(2, 7000.0 / (sr / 2), btype="low", output="sos")
    klang = sosfilt(sos_lp, klang)

    # Lautstaerke folgt Drehzahl UND Last: Schiebebetrieb ist deutlich leiser.
    klang *= (0.45 + 0.55 * anteil) * (0.5 + 0.5 * last)
    spitze = float(np.max(np.abs(klang))) or 1e-9
    return (klang / spitze * 0.7).astype(np.float32)


# ── Weg 1b: Synthese nach gemessenen Kennwerten ─────────────────────────────

def _formantfilter(x: np.ndarray, formanten: list[float], sr: int) -> np.ndarray:
    """Feste Resonanzen aus der Messung nachbilden.

    Die Frequenzen stammen nicht aus dem Bauch, sondern aus der Spektralhülle
    einer echten Aufnahme (Cepstrum-Glättung). Sie wandern nicht mit der
    Drehzahl — das unterscheidet einen Motor von einer Sirene.
    """
    aus = np.zeros_like(x)
    for i, f0 in enumerate(formanten):
        if f0 <= 40.0 or f0 >= sr / 2 - 200:
            continue
        breite = max(60.0, f0 * 0.35)
        lo = max(30.0, f0 - breite / 2) / (sr / 2)
        hi = min(sr / 2 - 100.0, f0 + breite / 2) / (sr / 2)
        sos = butter(2, [lo, hi], btype="band", output="sos")
        aus += sosfilt(sos, x) * (1.0 / (1.0 + i * 0.6))
    # Nur die Resonanzen durchzulassen war zu viel des Guten: das Spektrum
    # stand dann fest, egal wie die Drehzahl lief - gemessen blieb der
    # Schwerpunkt ueber die ganze Rampe bei 1640 Hz. Ein Teil des ungefilterten
    # Signals bleibt deshalb dabei, damit die wandernden Obertoene hoerbar sind.
    aus /= max(1e-9, float(np.max(np.abs(aus))))
    direkt = x / max(1e-9, float(np.max(np.abs(x))))
    return 0.6 * aus + 0.4 * direkt


def synthese_nach_messung(upm: np.ndarray, last: np.ndarray, kennwerte: dict,
                          sr: int = SR, zylinder: int = 4) -> np.ndarray:
    """Additive Synthese mit gemessenen Obertongewichten und Resonanzen.

    Statt einen Impuls zu formen und zu hoffen, dass das Spektrum stimmt,
    werden die Obertöne direkt mit den Gewichten aus der Messung aufgebaut.
    Das Rauschen wird anschließend so eingestellt, dass der Tonanteil des
    Ergebnisses dem der Aufnahme entspricht — gemessen mit derselben Formel,
    nicht nach Gefühl.
    """
    rng = np.random.default_rng(23)
    gewichte = list(kennwerte["obertoene"])
    formanten = list(kennwerte["formanten_Hz"])

    f = upm / 60.0 * (zylinder / 2.0)
    phase = 2.0 * np.pi * np.cumsum(f) / sr
    anteil = np.clip((upm - LEERLAUF_UPM) / (MAX_UPM - LEERLAUF_UPM), 0.0, 1.0)

    # Gemessen wurden zwölf Obertöne, ein Motor hat aber Dutzende. Über die
    # Messung hinaus wird das Muster fortgesetzt und abfallend gedämpft — mit
    # nur zwölf reichte das Spektrum bei hoher Drehzahl nicht weit genug nach
    # oben, und der Klang wurde ausgerechnet oben dünner statt heller.
    gemessen = len(gewichte)
    while len(gewichte) < 48:
        k = len(gewichte)
        gewichte.append(gewichte[k % gemessen] * (0.75 ** (k / gemessen)))

    ton = np.zeros(len(upm), dtype=np.float64)
    for k, g in enumerate(gewichte, start=1):
        if g <= 0.01 or float(np.max(f)) * k > sr * 0.45:
            continue
        # Obere Obertoene verschwinden bei niedriger Drehzahl - ein Motor im
        # Leerlauf ist dumpfer als unter Volllast.
        oben = np.clip(0.25 + 0.75 * anteil, 0.0, 1.0) ** (k * 0.18)
        # Daempfung nach ABSOLUTER Frequenz, nicht nach Ordnungszahl. Auspuff,
        # Schalldaempfer und Abstrahlung schlucken hohe Anteile unabhaengig
        # davon, bei welcher Drehzahl sie entstehen. Ohne das lagen bei
        # Hoechstdrehzahl alle achtundvierzig Obertoene mit voller Staerke an -
        # achtundvierzig reine Sinustoene im Abstand von 240 Hz, und das klingt
        # nach Orgel statt nach Motor.
        abstrahlung = 1.0 / (1.0 + (f * k / _KNIE_HZ) ** 2)
        # Leichte Unregelmaessigkeit je Oberton, sonst klingt es nach Orgel.
        zittern = 1.0 + 0.05 * np.sin(phase * (0.013 * k) + k)
        ton += g * oben * abstrahlung * zittern * np.sin(phase * k)

    # Halbordnungen (k = 0,5 / 1,5 / 2,5). Ein Viertaktzyklus dauert ZWEI
    # Umdrehungen - die Streuung zwischen den Zylindern wiederholt sich also
    # mit der halben Zuendfrequenz. Diese Anteile liegen UNTER dem Grundton
    # und geben dem Klang oben die Tiefe: bei 7200 U/min zuendet ein
    # Vierzylinder mit 240 Hz, und ohne Halbordnungen war darunter schlicht
    # nichts - genau das klang bei Hoechstdrehzahl duenn und synthetisch.
    # Sie wachsen mit der Drehzahl: im Leerlauf laegen sie bei 14 Hz,
    # unhoerbar bis matschig.
    tief = np.zeros(len(upm), dtype=np.float64)
    for halb, g in ((0.5, 1.0), (1.5, 0.5), (2.5, 0.3)):
        abstrahlung = 1.0 / (1.0 + (f * halb / _KNIE_HZ) ** 2)
        tief += g * abstrahlung * np.sin(phase * halb + halb * 2.1)
    tief *= 0.15 + 0.85 * anteil

    ton /= max(1e-9, float(np.max(np.abs(ton))))

    # Zylinderstreuung. Im Rohrmodell war sie drin, hier fehlte sie: jeder
    # Zylinder feuerte exakt gleich stark, und genau das trennt einen Ton von
    # einem Motor. Ein echter Motor hat je Zylinder etwas andere Verdichtung,
    # Einspritzmenge und Ventilspiel - das wiederholt sich mit der Umdrehung,
    # nicht mit der Zuendung, und ergibt das charakteristische Stampfen.
    zuendung = phase / (2.0 * np.pi)
    welcher = np.floor(zuendung).astype(np.int64) % max(1, zylinder)
    staerke = 1.0 + rng.normal(0.0, 0.13, max(1, zylinder))
    hub = staerke[welcher]
    # Ohne Glaettung springt der Faktor mitten im Impuls und knackt.
    fenster = max(2, int(sr * 0.0015))
    hub = np.convolve(hub, np.ones(fenster) / fenster, mode="same")
    ton *= hub

    rausch = rng.standard_normal(len(upm))
    # Schmaler als vorher (war 200-6000 Hz). Der obere Teil trug nichts zum
    # Motor bei und war genau das, was als Wind wahrgenommen wurde.
    sos = butter(2, [300.0 / (sr / 2), 3200.0 / (sr / 2)], btype="band", output="sos")
    rausch = sosfilt(sos, rausch)
    rausch /= float(np.sqrt(np.mean(rausch ** 2))) or 1e-9

    # Und es wird an die Zuendung gekoppelt: Ansauggeraeusch kommt stossweise
    # mit jedem Arbeitstakt, nicht als Dauerteppich. Ein gleichmaessiges
    # Breitbandrauschen unter dem Klang klingt zwangslaeufig nach Wind - es
    # gehoert zum Motor, also muss es mit ihm atmen.
    huelle = np.abs(ton)
    fenster = max(4, int(sr * 0.002))
    huelle = np.convolve(huelle, np.ones(fenster) / fenster, mode="same")
    huelle /= max(1e-9, float(np.max(huelle)))
    rausch *= 0.25 + 0.75 * huelle

    # Der gemessene Tonanteil taugt NICHT als Ziel. In einer Vorbeifahrt steckt
    # neben dem Motor auch Wind, Reifen und Strasse; gemessene 0,19 hiessen
    # danach 81 % Rauschen, und darauf getrimmt bestand die Synthese praktisch
    # nur noch aus Zischen - der Schwerpunkt blieb ueber die ganze Rampe bei
    # 4 kHz stehen, weil das Rauschband ihn festhielt. Der Rauschanteil wird
    # deshalb fest und sparsam gesetzt: er ist Beiwerk, nicht der Klang.
    klang = _formantfilter(ton + rausch * 0.08 * (0.4 + 0.6 * last), formanten, sr)

    # Die Halbordnungen bewusst am Formantfilter VORBEI und pegelkontrolliert
    # beigemischt. Durch den Filter geschickt landete die Halbordnung eines
    # Achtzylinders (240 Hz) genau auf der staerksten gemessenen Resonanz
    # (246 Hz) und dominierte mit 75 Prozent der Energie den ganzen Klang -
    # aus "etwas Tiefe" wurde ein Subwoofer-Dauerton.
    tief /= max(1e-9, float(np.sqrt(np.mean(tief ** 2))))
    klang /= max(1e-9, float(np.sqrt(np.mean(klang ** 2))))
    klang = klang + 0.38 * tief

    klang *= (0.45 + 0.55 * anteil) * (0.5 + 0.5 * last)
    spitze = float(np.max(np.abs(klang))) or 1e-9
    return (klang / spitze * 0.7).astype(np.float32)


def _tonanteil(x: np.ndarray, sr: int, f0: float, obertoene: int = 24) -> float:
    """Anteil der Energie in den Obertönen — dieselbe Formel wie bei der Messung."""
    if f0 <= 0 or len(x) < 4096:
        return 0.0
    stueck = x[len(x) // 2 - 16384:len(x) // 2 + 16384]
    n = 1 << int(np.ceil(np.log2(len(stueck))))
    spek = np.abs(np.fft.rfft(stueck * np.hanning(len(stueck)), n)) ** 2
    fr = np.fft.rfftfreq(n, 1.0 / sr)
    maske = np.zeros(len(fr), dtype=bool)
    for k in range(1, obertoene + 1):
        ziel = f0 * k
        if ziel > fr[-1]:
            break
        maske |= (fr > ziel * 0.97) & (fr < ziel * 1.03)
    gesamt = float(np.sum(spek[(fr > 60) & (fr < 8000)])) or 1e-9
    return float(np.sum(spek[maske])) / gesamt


# ── Weg 2: Samples in Drehzahlschichten ─────────────────────────────────────

def _mono(pfad: str) -> np.ndarray:
    daten, sr = sf.read(pfad, always_2d=True, dtype="float32")
    if sr != SR:
        raise SystemExit(f"{pfad}: {sr} Hz, erwartet {SR}")
    return daten.mean(axis=1).astype(np.float32)


def _lesen(schleife: np.ndarray, tempo: np.ndarray) -> np.ndarray:
    """Schleife mit veränderlichem Tempo abtasten (lineare Interpolation)."""
    n = len(schleife)
    stelle = np.cumsum(tempo) % n
    i0 = np.floor(stelle).astype(np.int64)
    frac = (stelle - i0).astype(np.float32)
    i1 = (i0 + 1) % n
    return schleife[i0] * (1.0 - frac) + schleife[i1] * frac


def aus_schichten(upm: np.ndarray, last: np.ndarray, dateien: list[str],
                  sr: int = SR, spanne: float = 0.30) -> np.ndarray:
    """Über mehrere Drehzahlschichten überblenden statt eine zu strecken.

    Jede Schicht deckt einen Abschnitt des Drehzahlbereichs ab und wird darin
    nur um *spanne* (±30 %) verstimmt. Zwischen benachbarten Schichten wird
    überblendet — dadurch bleibt die Verstimmung überall klein, und genau daran
    hängt, ob es nach Motor oder nach Bandmaschine klingt.
    """
    schleifen = [_mono(os.path.join(SFX, d)) for d in dateien]
    k = len(schleifen)
    anteil = np.clip((upm - LEERLAUF_UPM) / (MAX_UPM - LEERLAUF_UPM), 0.0, 1.0)

    # Stelle im Schichtstapel: 0 = unterste, k-1 = oberste.
    stelle = anteil * (k - 1)
    unten = np.clip(np.floor(stelle), 0, k - 1).astype(np.int64)
    oben = np.clip(unten + 1, 0, k - 1)
    mischung = (stelle - unten).astype(np.float32)

    aus = np.zeros(len(upm), dtype=np.float32)
    for i, schleife in enumerate(schleifen):
        aktiv_unten = (unten == i)
        aktiv_oben = (oben == i)
        if not (aktiv_unten.any() or aktiv_oben.any()):
            continue
        # Verstimmung innerhalb der Schicht: von -spanne bis +spanne, sodass
        # die Tonhoehe ueber die Grenze hinweg stetig weiterlaeuft.
        lokal = np.clip(stelle - i, -1.0, 1.0)
        tempo = 1.0 + spanne * lokal
        stimme = _lesen(schleife, tempo)
        gewicht = np.zeros(len(upm), dtype=np.float32)
        gewicht[aktiv_unten] = 1.0 - mischung[aktiv_unten]
        gewicht[aktiv_oben] += mischung[aktiv_oben]
        # Wurzelblende: sonst bricht die Lautstaerke in der Mitte ein.
        aus += stimme * np.sqrt(gewicht)

    aus *= (0.45 + 0.55 * anteil) * (0.55 + 0.45 * last)
    spitze = float(np.max(np.abs(aus))) or 1e-9
    return (aus / spitze * 0.7).astype(np.float32)


def _schichtdateien(motor: str) -> list[str]:
    """Schichten des Stapels — ohne die, die die Reihenfolge brechen.

    ``motor_schichten.py`` markiert Schichten, die heller sind als die über
    ihnen. Die gehören nicht in den Stapel: sonst wird der Motor unter Last
    dumpfer statt heller, und das hört man sofort als falsch.
    """
    pfad = os.path.join(SFX, "motor_schichten.json")
    with open(pfad, encoding="utf-8") as fh:
        tabelle = json.load(fh)
    return [e["datei"] for e in tabelle[motor] if e.get("passt", True)]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ziel", default=os.path.join(_ROOT, "build_tmp", "motor_demo3"))
    p.add_argument("--dauer", type=float, default=8.0)
    args = p.parse_args()
    os.makedirs(args.ziel, exist_ok=True)

    upm, last = drehzahlrampe(args.dauer)

    with open(os.path.join(_ROOT, "data", "audio", "motor_kennwerte.json"),
              encoding="utf-8") as fh:
        kennwerte = json.load(fh)["motoren"]

    stuecke = {
        "1-gemessen-sport.wav":   synthese_nach_messung(
            upm, last, kennwerte["sport"], zylinder=4),
        # Zweiter Motor aus derselben, verlaesslichsten Messung - nur mit
        # zwei Zylindern und damit halber Zuendfrequenz. Die Kennwerte der
        # zweiten Aufnahme waren zu wackelig: ein Tonanteil von 0.89 heisst
        # praktisch reiner Klang ohne Rauschen, das klingt nach Synthesizer.
        "2-gemessen-2zylinder.wav": synthese_nach_messung(
            upm, last, kennwerte["sport"], zylinder=2),
    }
    # Rohrmodell und Sample-Schichten sind nach dem Hoervergleich vom
    # 29.07.2026 raus: das Rohrmodell klang nach einem Ton durch ein Rohr - was
    # es woertlich ist -, die Schichten nach Hubschrauber. Letzteres hatte die
    # Messung vorhergesagt: 105-ms-Schleifen wiederholen sich 9,5-mal je
    # Sekunde, und genau so klingt ein Rotor. Die Funktionen bleiben stehen,
    # erzeugt wird damit nichts mehr.
    for name, daten in stuecke.items():
        sf.write(os.path.join(args.ziel, name), daten, SR, subtype="PCM_16")
        print(f"{name:<28} {len(daten)/SR:.1f}s")
    print("\n->", args.ziel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
