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
# tatsächlich, aber der Fehler steckt im Tempo-Regler und war die ganze Zeit da.
# Nach dem Ziel setzt `speed_multiplier = 0.5` ein niedriges, konstantes Ziel auf
# freier Strecke — erst dort liegt ein Auto lange genug **genau** auf seinem
# Zieltempo, dass die Sprungstelle dauernd getroffen wird.

def _gas(speed_err: float, band: float | None = None) -> float:
    """Der Gasanteil des Reglers für einen Tempofehler, ohne Fahrzeug drumherum."""
    from src.ai.ai_controller import AIController
    band = AIController.GAS_AUSBLENDBAND if band is None else band
    gas = min(1.0, 0.60 + speed_err * 0.05)
    if speed_err < band:
        gas *= speed_err / band
    return gas


def test_das_gas_faellt_am_zielpunkt_nicht_mehr_ins_leere():
    """Der Kern: zwischen „knapp zu langsam" und „genau richtig" lag ein Sprung
    von 0,60 auf 0. Ein Auto auf seinem Zieltempo pendelte damit jedes Bild."""
    assert _gas(0.001) < 0.01, "kurz vor dem Ziel muss das Gas fast weg sein"


def test_das_gas_geht_stetig_gegen_null():
    """Keine Stufe mehr — geprüft an der größten Änderung zwischen zwei Schritten."""
    from src.ai.ai_controller import AIController
    band = AIController.GAS_AUSBLENDBAND
    werte = [_gas(band * i / 200.0) for i in range(201)]
    sprung = max(abs(b - a) for a, b in zip(werte, werte[1:]))
    assert sprung < 0.02, f"Stufe von {sprung:.2f} im Ausblendband"


def test_das_gas_waechst_mit_dem_tempofehler():
    werte = [_gas(e) for e in (0.5, 1.0, 2.0, 4.0, 6.0)]
    assert all(b > a for a, b in zip(werte, werte[1:])), werte


def test_im_fahrbereich_bleibt_alles_wie_vorher():
    """Die eigentliche Zusicherung: die Fahrweise der KI ändert sich nicht.

    Oberhalb des Ausblendbands muss exakt derselbe Wert herauskommen wie vor der
    Änderung — sonst wäre aus einer Glättung eine neue Fahrweise geworden, und
    alle Rundenzeiten stünden anders da.
    """
    from src.ai.ai_controller import AIController
    for err in (6.0, 8.0, 12.0, 25.0, 60.0, 200.0):
        vorher = min(1.0, 0.60 + err * 0.05)
        assert _gas(err) == pytest.approx(vorher), err
    assert AIController.GAS_AUSBLENDBAND <= 8.0, \
        "ein breites Band würde die Fahrweise verändern, nicht nur die Sprungstelle"


def test_der_regler_steht_wirklich_so_im_code():
    """Der Test oben rechnet den Regler nach — er muss dem Code entsprechen.

    Sonst prüft er eine Formel, die es im Spiel gar nicht gibt.
    """
    import inspect
    from src.ai.ai_controller import AIController
    quelle = inspect.getsource(AIController.compute_inputs)
    assert "throttle = min(max_throttle, 0.60 + speed_err * 0.05)" in quelle
    assert "throttle *= speed_err / self.GAS_AUSBLENDBAND" in quelle
