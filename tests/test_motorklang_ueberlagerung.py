"""Überlagerung mehrerer Motoren — die Störfrequenzen im Rennen (C8).

Gemeldet am 02.08.2026: „die Motoren für sich klingen alle gut, aber immer wenn
ein weiteres Fahrzeug auf dem Bildschirm zu sehen ist, sind die Störfrequenzen
da. Wenn ich ganz alleine fahre, hört sich der Motor gut an."

**Erster Versuch (02.08.2026) — falsch.** Gemessen wurde damals, dass zwei
Fahrzeuge derselben Klasse mit festem Tonhöhenversatz (§C5) auf jeder Ordnung
gegeneinander schweben, und der Charakter wurde von der Tonhöhe in die
Klangfarbe verlagert: alle Fahrzeuge auf ``tonhoehe = 1.0``. Im Playtest am
03.08.2026 war nichts besser.

**Warum die Messung nicht gereicht hat.** Alle Tests hier liefen mit
**derselben Drehzahl** für beide Fahrzeuge — 4000 gegen 4000. Genau dort gibt es
das Problem nicht. Im Rennen fährt kein Auto exakt so schnell wie das andere;
sobald sich die Drehzahlen um 200 UPM unterscheiden, schweben die Motoren
wieder, ganz ohne Tonhöhenversatz. Ein Test, der den Betriebsfall nicht
nachstellt, kann eine Behebung bestätigen, die keine ist.

**Die Ursache (03.08.2026).** Jede Schicht ist eine Aufnahme, die als *Schleife*
läuft. Damit ist eine Stimme streng periodisch: die Ähnlichkeit mit sich selbst
nach einer Schleifenlänge ist **1,0000**. Ein echter Motor erreicht das nie.
Diese Perfektion ergibt ein Linienspektrum mit messerscharfen Oberwellen, und
zwei davon erzeugen eine saubere, laute Schwebung. Deshalb hat auch nichts
anderes geholfen: es ist nicht die *gleiche* Aufnahme, es ist die *perfekte*.
Zwei Rennfahrzeuge bei 5000/5300 UPM, gemessen an der höchsten Einzellinie im
Hüllkurvenband 5–30 Hz und ihrem Abstand zum Bandmittel:

=================================  =======  =========
                                    Linie    Schärfe
=================================  =======  =========
eine Stimme allein                    0,20        5,3
zwei Stimmen, ohne Zyklusstreuung     9,41       95,2
zwei Stimmen, mit 0,8 % Streuung      3,00       12,3
=================================  =======  =========

**Behoben** durch ``sfx.Zyklusstreuung``: 0,8 % langsame Zufallsschwankung der
Rate je Stimme, mit eigener Zufallsfolge. Damit ist keine Stimme mehr streng
periodisch — die Selbstähnlichkeit fällt von 1,0000 auf unter 0,1 —, und aus dem
Schwebungs*ton* wird die Rauheit, die zwei Motoren nebeneinander eben haben.

**Die richtige Kennzahl.** Nicht die Energie im Band: die zählt Ton und Rauheit
zusammen und *steigt* durch die Streuung, weshalb der Eingriff am 02.08.2026
schon einmal als wirkungslos verworfen wurde. Was zählt, ist die **Höhe der
höchsten Einzellinie** und ihre **Schärfe** (Linie geteilt durch Bandmittel).
Eine Schwebung ist ein Ton: eine schmale, hohe Linie. Rauheit ist flach.

**Der bewusst hingenommene Preis.** Bei *exakt* gleicher Drehzahl schwanken die
beiden unabhängigen Streuungen gegeneinander, die Linie steigt dort von 0,36 auf
2,95. Das ist gemessen und gewollt: der Fall kommt im Rennen praktisch nicht vor,
und 3 % breitbandige Rauheit ist harmlos gegen 13 % als Ton bei 20 Hz.
"""
from __future__ import annotations

import itertools
import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import sfx, sfx_rennen as sr  # noqa: E402

#: Fahrzeuge je Klasse — die teilen sich eine Aufnahme und überlagern sich
#: deshalb am stärksten.
KLASSEN = {
    "Hatchback":    ["rookie", "rookie_2", "rookie_3"],
    "Limousine":    ["limousine", "limousine_2", "limousine_3"],
    "Drifter":      ["drifter", "drifter_2", "drifter_3"],
    "Rennfahrzeug": ["supercar", "supercar_2", "supercar_3"],
}


@pytest.fixture(scope="module", autouse=True)
def fahrzeuge():
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")


def stimme(key: str, upm: float, bloecke: int = 160,
           streuung: float | None = None) -> np.ndarray:
    """Eine Motorstimme, genau wie das Rennen sie baut.

    Die erste Hälfte wird verworfen: der Pegelausgleich der Färbung regelt sich
    über etwa eine halbe Sekunde ein. *streuung* überschreibt die Zyklusstreuung
    — ``0.0`` stellt den Stand vor dem 03.08.2026 wieder her.
    """
    from src.core import motorklang
    tonhoehe, faerbung = sr.klangfarbe_von_schluessel(key)
    motor = sr.motor_fuer_klasse(sr.klasse_von_schluessel(key))
    werte = dict(motorklang.werte(motor))
    if streuung is not None:
        werte["zyklusstreuung"] = float(streuung)
    s = sfx.Motorstimme(motor, tonhoehe, faerbung, werte=werte)
    x = np.concatenate([s.block(upm) for _ in range(bloecke)])
    return x[len(x) // 2:]


def _huellspektrum(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    k = 240                                   # ~5 ms Fenster
    huelle = np.convolve(np.abs(x), np.ones(k) / k, mode="valid")
    pegel = float(huelle.mean())
    schwankung = huelle - pegel
    sp = np.abs(np.fft.rfft(schwankung * np.hanning(len(schwankung))))
    sp = sp / len(schwankung) / max(pegel, 1e-9) * 100
    fr = np.fft.rfftfreq(len(schwankung), 1.0 / sfx.SR)
    return fr, sp, pegel


#: Die Energie im Band 5–30 Hz stand hier bis zum 03.08.2026 als Kennzahl.
#: Sie ist ersatzlos gestrichen, nicht nur unbenutzt: sie zählt Schwebungston
#: und breitbandige Rauheit zusammen, und die Zyklusstreuung tauscht genau das
#: eine gegen das andere. Zweimal hat diese Zahl deshalb einen richtigen
#: Eingriff als wirkungslos aussehen lassen. Wer sie zurückholt, holt den
#: Irrtum mit.


def schwebung(x: np.ndarray) -> tuple[float, float]:
    """(Linie, Schärfe) der stärksten Schwebung im Band 5–30 Hz.

    *Linie* ist die Modulationstiefe an der stärksten Einzelfrequenz, in Prozent
    des Mittelpegels — also wie tief das Signal dort atmet. *Schärfe* ist ihr
    Verhältnis zum Bandmittel: ein Ton ist schmal und hoch, Rauheit ist flach.
    Beide zusammen unterscheiden „schwebt" von „ist rau", und das ist der
    Unterschied, um den es hier geht.
    """
    fr, sp, _p = _huellspektrum(x)
    band = (fr >= 5.0) & (fr < 30.0)
    linie = float(sp[band].max())
    return linie, linie / max(float(np.median(sp[band])), 1e-9)


# ---------------------------------------------------------------------------
# Der gemeldete Fehler — im Betriebsfall, also bei UNTERSCHIEDLICHER Drehzahl
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("klasse", sorted(KLASSEN))
def test_zwei_autos_bei_verschiedener_drehzahl_schweben_nicht_als_ton(klasse):
    """Der Betriebsfall, den die Tests vom 02.08.2026 nicht abgedeckt haben.

    Kein Auto fährt exakt so schnell wie das andere. Verglichen wird derselbe
    Klang mit und ohne Zyklusstreuung — absolute Schwellen wären hier nur
    scheingenau, der Faktor ist die Aussage. Gemessen liegt er zwischen 2,3
    (Hatchback) und 22 (Drifter).
    """
    keys = KLASSEN[klasse]
    if not sfx.schichten(sr.motor_fuer_klasse(sr.klasse_von_schluessel(keys[0]))):
        pytest.skip("keine Aufnahmen vorhanden")
    a, b = keys[0], keys[1]
    ohne = schwebung(stimme(a, 4200.0, streuung=0.0)
                     + stimme(b, 4400.0, streuung=0.0))
    mit = schwebung(stimme(a, 4200.0) + stimme(b, 4400.0))
    assert mit[1] < ohne[1] / 2.0, (
        f"{klasse}: Schärfe {mit[1]:.1f} mit, {ohne[1]:.1f} ohne Streuung")
    assert mit[0] < ohne[0], (
        f"{klasse}: Linie {mit[0]:.2f} mit, {ohne[0]:.2f} ohne Streuung")


def test_ohne_zyklusstreuung_ist_die_schwebung_ein_reiner_ton():
    """Der Gegenbeweis, und die Zahl aus der Meldung.

    Zwei Rennfahrzeuge bei 5000/5300 UPM: ohne Streuung sitzt die ganze
    Schwankung auf einer Linie, hoch über allem anderen im Band. Genau das hört
    man als Störfrequenz.
    """
    if not sfx.schichten("8zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    linie, schaerfe = schwebung(stimme("supercar", 5000.0, streuung=0.0)
                                + stimme("supercar_2", 5300.0, streuung=0.0))
    assert schaerfe > 40.0, f"Schärfe nur {schaerfe:.1f} — Messaufbau prüfen"
    einzeln = schwebung(stimme("supercar", 5000.0, streuung=0.0))[0]
    assert linie > einzeln * 8, f"Linie {linie:.2f} gegen {einzeln:.2f} allein"


def test_die_schleife_allein_ist_die_ursache():
    """Die Wurzel, in einer Zahl: eine Stimme ohne Streuung wiederholt sich nach
    einer Schleifenlänge **exakt**. Kein Motor tut das, und nur weil unsere es
    taten, konnten zwei davon sauber gegeneinander schweben."""
    if not sfx.schichten("4zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    sch = sfx.schichten("4zyl")
    laenge = len(sch.schleifen[int(np.argmax(sch.gewichte(4500.0, 1.0)))])

    def aehnlichkeit(streuung):
        x = stimme("rookie", 4500.0, bloecke=200, streuung=streuung)
        a, b = x[:len(x) - laenge], x[laenge:]
        return float(np.dot(a, b) / max(1e-9, np.linalg.norm(a) * np.linalg.norm(b)))

    assert aehnlichkeit(0.0) > 0.999, "die Schleife war nicht mehr perfekt?"
    assert abs(aehnlichkeit(None)) < 0.5, "die Streuung bricht die Periode nicht"


def test_der_alte_tonhoehenversatz_war_nicht_die_ursache():
    """Bei gleicher Drehzahl macht ein fester Tonhöhenversatz die Schwebung
    tatsächlich schlimmer — das war am 02.08.2026 richtig gemessen. Es war nur
    nicht der Fall, der im Rennen auftritt."""
    if not sfx.schichten("8zyl"):
        pytest.skip("keine Aufnahmen vorhanden")

    def bauen(tonhoehe):
        s = sfx.Motorstimme("8zyl", tonhoehe, 0.0,
                            werte=dict(sfx.Motorstimme("8zyl").werte,
                                       zyklusstreuung=0.0))
        x = np.concatenate([s.block(4000.0) for _ in range(120)])
        return x[len(x) // 2:]

    unisono = schwebung(bauen(1.0) + bauen(1.0))[0]
    verstimmt = schwebung(bauen(0.96) + bauen(1.00))[0]
    assert verstimmt > unisono * 4, (
        f"verstimmt {verstimmt:.2f}, unisono {unisono:.2f}")


# ---------------------------------------------------------------------------
# Die Zyklusstreuung selbst
# ---------------------------------------------------------------------------
def test_die_streuung_ist_ab_werk_an():
    """Ausnahme von „Vorgabe = bisherige Wirkung" (§C8): die bisherige Wirkung
    war der Fehler."""
    from src.core import motorklang
    assert motorklang.VORGABE["zyklusstreuung"] > 0.0
    for motor in ("4zyl", "6zyl", "8zyl"):
        assert motorklang.werte(motor)["zyklusstreuung"] > 0.0


def test_jede_stimme_streut_fuer_sich():
    """Zwei Motoren, die identisch schwanken, sind so streng gekoppelt wie zwei
    ohne Streuung — dann wäre nichts gewonnen."""
    a = sfx.Zyklusstreuung(0.01, 1.0)
    b = sfx.Zyklusstreuung(0.01, 1.0)
    ra = np.concatenate([np.atleast_1d(a.rate(2048)) for _ in range(20)])
    rb = np.concatenate([np.atleast_1d(b.rate(2048)) for _ in range(20)])
    assert not np.allclose(ra, rb)
    r = float(np.corrcoef(ra, rb)[0, 1])
    assert abs(r) < 0.5, f"Streuungen laufen im Gleichschritt (r={r:.2f})"


def test_die_streuung_bleibt_ueber_blockgrenzen_stetig():
    """Ein Sprung in der Rate ist ein Sprung in der Tonhöhe — und der knackt."""
    s = sfx.Zyklusstreuung(0.02, 1.0, saat=1)
    bloecke = [np.atleast_1d(s.rate(512)) for _ in range(30)]
    ganz = np.concatenate(bloecke)
    innen = float(np.abs(np.diff(ganz)).max())
    naht = max(abs(float(bloecke[i + 1][0] - bloecke[i][-1]))
               for i in range(len(bloecke) - 1))
    assert naht <= innen * 1.5, f"Naht {naht:.2e}, innen {innen:.2e}"


def test_die_streuung_haelt_ihre_staerke_unabhaengig_vom_tempo():
    """Sonst wäre der Tempo-Regler heimlich ein zweiter Stärke-Regler."""
    for hz in (0.5, 1.0, 4.0, 10.0):
        s = sfx.Zyklusstreuung(0.01, hz, saat=5)
        werte = np.concatenate([np.atleast_1d(s.rate(2048)) for _ in range(400)])
        assert 0.006 < float(np.std(werte)) < 0.016, f"{hz} Hz: {np.std(werte):.4f}"


def test_ausgeschaltet_kostet_die_streuung_nichts():
    s = sfx.Zyklusstreuung(0.0, 1.0)
    assert not s
    assert s.rate(2048) == 1.0


def test_werte_setzen_behaelt_die_zufallsfolge():
    """Im Labor wird gedreht, während der Motor läuft. Eine neue Zufallsfolge
    wäre ein Sprung in der Tonhöhe bei jedem Reglerklick."""
    if not sfx.schichten("4zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    s = sfx.Motorstimme("4zyl")
    s.block(3000.0)
    vorher = s.streuung._letzter
    folge = s.streuung._rng
    s.werte_setzen(dict(s.werte, zyklusstreuung=0.02))
    assert s.streuung._letzter == vorher
    assert s.streuung._rng is folge
    assert s.streuung.staerke == 0.02


@pytest.mark.parametrize("klasse", sorted(KLASSEN))
def test_kein_fahrzeug_ist_gegen_ein_anderes_verstimmt(klasse):
    """Die Wurzel selbst: gleiche Aufnahme, gleiche Tonhöhe.

    Wer hier wieder einen Versatz einträgt, bekommt das Flattern zurück — und
    zwar dauerhaft, weil er auch dann besteht, wenn zwei Autos exakt gleich
    schnell fahren.
    """
    hoehen = {k: sr.klangfarbe_von_schluessel(k)[0] for k in KLASSEN[klasse]}
    assert max(hoehen.values()) - min(hoehen.values()) < 0.005, hoehen


# ---------------------------------------------------------------------------
# Der Charakter darf trotzdem nicht verloren gehen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("klasse", sorted(KLASSEN))
def test_die_fahrzeuge_klingen_weiter_verschieden(klasse):
    """Der Versatz ist weg, der Charakter nicht: er sitzt jetzt in der
    Klangfarbe. Ohne diesen Test wäre der einfachste Weg zum grünen Test
    oben, allen Fahrzeugen denselben Klang zu geben."""
    farben = sorted(sr.klangfarbe_von_schluessel(k)[1] for k in KLASSEN[klasse])
    assert farben[-1] - farben[0] >= 0.6, farben
    assert len(set(farben)) == len(farben), "zwei Fahrzeuge klingen identisch"


@pytest.mark.parametrize("klasse", sorted(KLASSEN))
def test_die_klangfarbe_aendert_die_lautstaerke_nicht(klasse):
    """Sonst wäre aus einer Klangfarbe eine Bevorzugung geworden.

    Gemessen am 02.08.2026: mit der breiteren Färbung unterschieden sich drei
    Fahrzeuge derselben Klasse um **Faktor 2,3** in der Lautstärke — der
    Pegelausgleich rechnete mit der Filterenergie und traf damit ein Signal,
    das über das ganze Band verteilt ist. Ein Motor ist das nicht.
    """
    keys = KLASSEN[klasse]
    if not sfx.schichten(sr.motor_fuer_klasse(sr.klasse_von_schluessel(keys[0]))):
        pytest.skip("keine Aufnahmen vorhanden")
    pegel = [float(np.sqrt(np.mean(np.square(stimme(k, 4000.0))))) for k in keys]
    assert max(pegel) / max(min(pegel), 1e-9) < 1.15, dict(zip(keys, pegel))


def test_pegelausgleich_haelt_den_pegel_ueber_die_faerbung():
    """Dasselbe isoliert, ohne Fahrzeugdaten."""
    if not sfx.schichten("4zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    roh = np.concatenate([sfx.Motorstimme("4zyl", 1.0, 0.0).block(4000.0)
                          for _ in range(60)])
    trocken = float(np.sqrt(np.mean(np.square(roh))))
    for staerke in (-0.45, -0.2, 0.2, 0.45):
        f = sfx.Faerbung(staerke)
        aus = np.concatenate([f(roh[i:i + 2048])
                              for i in range(0, len(roh) - 2048, 2048)])
        spaet = aus[len(aus) // 2:]
        verhaeltnis = float(np.sqrt(np.mean(np.square(spaet)))) / trocken
        assert 0.9 < verhaeltnis < 1.1, f"Färbung {staerke}: Faktor {verhaeltnis:.2f}"


# ---------------------------------------------------------------------------
# Das ganze Feld
# ---------------------------------------------------------------------------
def test_sechs_fahrzeuge_schweben_nicht_als_ton():
    """Ein ganzes Feld, jedes Auto mit eigener Drehzahl — der Pulk auf der
    Gegengeraden. Geprüft wird wieder die Schärfe: dass es rauscht, ist richtig;
    dass ein Ton darüber steht, wäre der Fehler."""
    keys = ["rookie", "rookie_2", "supercar", "supercar_2", "drifter", "limousine"]
    if not sfx.schichten("8zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    upms = [3900.0, 4050.0, 4200.0, 4380.0, 4520.0, 4700.0]
    ohne = schwebung(sum(stimme(k, u, streuung=0.0) for k, u in zip(keys, upms)))
    mit = schwebung(sum(stimme(k, u) for k, u in zip(keys, upms)))
    assert mit[1] < ohne[1], f"Schärfe {mit[1]:.1f} mit, {ohne[1]:.1f} ohne"
    assert mit[1] < 20.0, f"noch ein Ton im Feld: Schärfe {mit[1]:.1f}"
