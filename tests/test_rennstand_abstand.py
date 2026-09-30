"""Der Abstand im Rennstand (Playtest 05.08.2026).

Gemeldet: „Im live Rennstand steht der Abstand bei allen Fahrzeugen immer auf
0.00s."

Und das war kein Rundungsfehler, sondern die Rechnung: verglichen wurde die
verstrichene **Gesamtzeit** mit der des Führenden. Solange niemand im Ziel ist,
ist die für alle gleich — alle starten gemeinsam, und
``sum(lap_times) + current_lap_time`` ist schlicht die Rennzeit. Die
Streckenposition kam gar nicht vor. Ein Fahrzeug eine halbe Runde hinten hatte
denselben Wert wie der Führende: +0.00s.

Geprüft wird deshalb genau das, was fehlte: **dass die Position zählt.** Ein
Fahrzeug, das weiter hinten steht, muss einen größeren Abstand bekommen; zwei
auf gleicher Höhe denselben. Die absolute Sekundenzahl ist eine Schätzung und
wird bewusst nur grob geprüft — sie hängt am Tempo, und ein Test auf zwei
Nachkommastellen würde die Schätzung zementieren statt sie zu prüfen.
"""
from __future__ import annotations

import math
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


class _StateMachineAttrappe:
    def transition(self, *a, **k) -> None:
        pass


def _strecke(wegpunkte: int = 100, radius: float = 1000.0):
    """Ein Kreis aus *wegpunkte* Punkten — Länge exakt nachrechenbar."""
    from src.track.track import Waypoint
    punkte = []
    for i in range(wegpunkte):
        w = 2.0 * math.pi * i / wegpunkte
        punkte.append(Waypoint(x=radius * math.cos(w), y=radius * math.sin(w)))
    return types.SimpleNamespace(waypoints=punkte)


def _rennen(fahrzeuge: list[tuple[int, int, float, float]]):
    """RaceState mit einem gestellten Feld.

    *fahrzeuge* ist ``(id, runde, wegpunkt, tempo_pxs)`` je Fahrzeug, in der
    Reihenfolge des Rennstands (Führender zuerst).
    """
    from src.states.race_state import RaceState
    rennen = RaceState(_StateMachineAttrappe())
    rennen.track = _strecke()

    autos, tracker = [], {}
    for vid, runde, wegpunkt, tempo in fahrzeuge:
        autos.append(types.SimpleNamespace(id=vid, speed=tempo))
        tracker[vid] = types.SimpleNamespace(
            current_lap=runde, waypoint_progress=float(wegpunkt),
            lap_times=[], current_lap_time=0.0)
    rennen.race_manager = types.SimpleNamespace(
        vehicles=autos, lap_trackers=tracker, finished_ids=set(),
        _standings=autos)
    return rennen


TEMPO = 500.0   # px/s, für alle gleich — damit nur die Position wirkt


def test_wer_zurueckliegt_bekommt_einen_abstand():
    """Der eigentliche Fund: vorher stand hier 0.00s."""
    rennen = _rennen([(1, 1, 50, TEMPO), (2, 1, 25, TEMPO)])
    assert rennen._abstand_sekunden(2, 1) > 0.0


def test_wer_gleichauf_liegt_hat_keinen_abstand():
    rennen = _rennen([(1, 1, 40, TEMPO), (2, 1, 40, TEMPO)])
    assert rennen._abstand_sekunden(2, 1) == 0.0


def test_doppelter_rueckstand_ist_doppelte_zeit():
    """Bei gleichem Tempo ist der Zusammenhang linear — das ist die Aussage."""
    rennen = _rennen([(1, 1, 60, TEMPO), (2, 1, 50, TEMPO), (3, 1, 40, TEMPO)])
    nah = rennen._abstand_sekunden(2, 1)
    fern = rennen._abstand_sekunden(3, 1)
    assert fern == pytest.approx(2.0 * nah, rel=1e-6)


def test_eine_runde_zurueck_zaehlt_als_rueckstand():
    """Ohne die Runde wäre ein Überrundeter gleichauf mit dem Führenden."""
    rennen = _rennen([(1, 2, 10, TEMPO), (2, 1, 10, TEMPO)])
    eine_runde = rennen._streckenlaenge_px() / TEMPO
    assert rennen._abstand_sekunden(2, 1) == pytest.approx(eine_runde, rel=0.01)


def test_langsamer_unterwegs_heisst_groesserer_abstand():
    """Derselbe Rückstand in Metern braucht bei halbem Tempo doppelt so lange."""
    schnell = _rennen([(1, 1, 50, TEMPO), (2, 1, 40, TEMPO)])
    langsam = _rennen([(1, 1, 50, TEMPO), (2, 1, 40, TEMPO / 2)])
    assert langsam._abstand_sekunden(2, 1) == pytest.approx(
        2.0 * schnell._abstand_sekunden(2, 1), rel=1e-6)


def test_ein_stehendes_fahrzeug_ergibt_keine_fantasiezahl():
    """Wer steht, hätte rechnerisch unendlich Rückstand.

    Gerechnet wird dann mit einem Mindesttempo — die Zahl ist dann die eines
    langsam rollenden Autos und nicht ``inf`` oder eine Division durch null.
    """
    rennen = _rennen([(1, 1, 50, TEMPO), (2, 1, 40, 0.0)])
    wert = rennen._abstand_sekunden(2, 1)
    assert math.isfinite(wert)
    assert 0.0 < wert < 600.0


def test_die_streckenlaenge_stimmt_mit_der_geometrie():
    """Ein 100-Eck um einen Kreis mit Radius 1000 ist knapp der Umfang."""
    rennen = _rennen([(1, 1, 0, TEMPO)])
    umfang = 2.0 * math.pi * 1000.0
    assert rennen._streckenlaenge_px() == pytest.approx(umfang, rel=0.01)


def test_ohne_strecke_wird_nichts_behauptet():
    """Lieber „—" als eine erfundene Zahl."""
    rennen = _rennen([(1, 1, 10, TEMPO), (2, 1, 5, TEMPO)])
    rennen.track = None
    assert rennen._abstand_sekunden(2, 1) is None


def test_der_abstand_haengt_nicht_mehr_an_der_rennzeit():
    """Die Gegenprobe zum Fund.

    Alle Fahrzeuge tragen dieselbe Rennzeit — genau die Lage, in der vorher
    überall 0.00s stand. Der Abstand muss sich trotzdem unterscheiden.
    """
    rennen = _rennen([(1, 1, 70, TEMPO), (2, 1, 40, TEMPO), (3, 1, 10, TEMPO)])
    for t in rennen.race_manager.lap_trackers.values():
        t.lap_times = [42.0]
        t.current_lap_time = 7.5
    werte = [rennen._abstand_sekunden(v, 1) for v in (2, 3)]
    assert werte[0] > 0.0 and werte[1] > werte[0]


# ---------------------------------------------------------------------------
# Die Drehzahl nach der Ziellinie (Playtest 05.08.2026)
# ---------------------------------------------------------------------------
# „Nachdem man die Ziellinie überquert hat spielt die Drehzahl etwas verrückt
#  liegt wahrscheinlich an der KI übernahme."
#
# Die Vermutung stimmte im Auslöser, nicht in der Ursache: die KI übernimmt
# tatsächlich, aber der Fehler steckt im Tempo-Regler. Nach dem Ziel setzt
# `speed_multiplier = 0.5` ein niedriges, konstantes Ziel auf freier Strecke —
# erst dort liegt ein Auto lange genug **genau** auf seinem Zieltempo, dass eine
# Sprungstelle im Gas dauernd getroffen wird. Der Bahnregler blendet das Gas
# deshalb über ``GAS_BAND`` weich aus; diese Tests halten das fest.

def _gas(speed_err: float) -> float:
    """Der Gasanteil des Bahnreglers für einen Tempofehler (Soll minus Ist)."""
    from src.ai.regler import Bahnregler
    return Bahnregler.pedale(object.__new__(Bahnregler), 100.0, 100.0 + speed_err)[0]


def test_das_gas_faellt_am_zielpunkt_nicht_mehr_ins_leere():
    assert _gas(0.001) < 0.01, "kurz vor dem Ziel muss das Gas fast weg sein"


def test_das_gas_geht_stetig_gegen_null():
    """Keine Stufe — größte Änderung zwischen zwei Schritten von 0,05 px/s."""
    werte = [_gas(-1.0 + i * 0.05) for i in range(221)]   # -1 bis +10 px/s
    sprung = max(abs(b - a) for a, b in zip(werte, werte[1:]))
    assert sprung < 0.02, f"Stufe von {sprung:.3f} im Ausblendband"


def test_das_gas_waechst_mit_dem_tempofehler():
    werte = [_gas(i * 0.05) for i in range(1, 221)]
    assert all(b >= a for a, b in zip(werte, werte[1:]))
    assert _gas(6.0) > _gas(3.0) > _gas(0.5) > 0.0


def test_das_ausblendband_ist_klein_genug():
    from src.ai.regler import Bahnregler
    assert Bahnregler.GAS_BAND <= 8.0, \
        "ein breites Band würde die Fahrweise verändern, nicht nur die Sprungstelle"


def test_ein_ki_auto_mit_halbem_tempo_ruckelt_nicht_im_gas():
    """Der Weg des Playtests: echtes Auto, `speed_multiplier = 0.5`."""
    import ki_hilfe as H
    from test_ai import DT, _feld
    welt, track, feld = _feld(lambda sp: H.strecke_laden("oval", sp), ["rookie"])
    auto = feld[0]
    auto.controller.speed_multiplier = 0.5
    gas = []
    for n in range(int(8.0 / DT)):
        auto.update(DT)
        welt.step(DT)
        if n >= int(6.0 / DT):
            gas.append(auto.throttle)
    spruenge = sum(1 for a, b in zip(gas, gas[1:]) if abs(b - a) > 0.3)
    assert spruenge == 0, f"{spruenge} Gas-Sprünge in 2 s"
