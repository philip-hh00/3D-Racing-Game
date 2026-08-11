"""Eine unlesbare Strecke darf das Spiel nicht mitreissen.

Die Streckenauswahl prueft nur die Mittellinie. Eine Datei mit gueltiger
Mittellinie, aber kaputten Wegpunkten kommt also bis in den Rennstart durch —
und online erreicht eine uebertragene Strecke den Rennstart voellig ohne
Auswahlbildschirm.

Erwartetes Verhalten: ``enter()`` bricht sauber ab, der erste ``update()``
wechselt zurueck ins Menue. Der Wechsel passiert bewusst nicht in ``enter()``
selbst, weil ``transition()`` sonst rekursiv in den gerade entstehenden Zustand
greifen wuerde.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# pygame wird in tests/conftest.py einmalig fuer den ganzen Lauf gestartet.

import pygame  # noqa: E402

GUTE_MITTELLINIE = [{"x": float(i * 120), "y": 0.0} for i in range(10)]


class _StateMachineAttrappe:
    """Merkt sich nur, wohin gewechselt wurde."""

    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []

    def transition(self, name: str, **kwargs) -> None:
        self.wechsel.append((name, kwargs))


def _race_state():
    from src.states.race_state import RaceState
    sm = _StateMachineAttrappe()
    return RaceState(sm), sm


def _schreibe(tmp_path, inhalt) -> str:
    p = tmp_path / "kaputt.json"
    p.write_text(json.dumps(inhalt), encoding="utf-8")
    return str(p)


def test_unlesbare_strecke_wechselt_ins_menue_statt_abzustuerzen(tmp_path):
    state, sm = _race_state()
    pfad = _schreibe(tmp_path, {"centerline": []})       # keine Mittellinie

    state.enter(track_path=pfad)                          # darf nicht werfen
    assert state._load_failed
    assert sm.wechsel == []                               # noch kein Wechsel

    state.update(0.016)
    assert sm.wechsel == [("menu", {"track_error": True})]


def test_wechsel_passiert_nur_einmal(tmp_path):
    state, sm = _race_state()
    state.enter(track_path=_schreibe(tmp_path, {"centerline": []}))
    state.update(0.016)
    state.update(0.016)
    assert len(sm.wechsel) == 1


def test_aufraeumen_laeuft_auch_nach_abgebrochenem_aufbau(tmp_path):
    """exit() liest Felder, die enter() erst spaet setzt - der Abbruch darf
    den Aufraeumpfad nicht sprengen."""
    state, _sm = _race_state()
    state.enter(track_path=_schreibe(tmp_path, {"centerline": []}))
    state.exit()                                          # darf nicht werfen


def test_kaputte_wegpunkte_verhindern_das_rennen_nicht(tmp_path):
    """Teilschaden wird repariert: die Strecke laedt, das Rennen laeuft."""
    pfad = _schreibe(tmp_path, {
        "centerline": GUTE_MITTELLINIE,
        "waypoints": [{"x": "kaputt", "y": 0}, {"x": 10.0, "y": 0.0}],
        "start_positions": [{"x": "auch kaputt"}],
    })
    state, sm = _race_state()
    state.enter(track_path=pfad)
    assert not state._load_failed
    assert state.track is not None
    assert len(state.track.start_positions) >= 6          # aus Mittellinie gebaut
    state.exit()


def test_fehlende_datei_wechselt_ins_menue():
    state, sm = _race_state()
    state.enter(track_path="data/tracks/gibtsnicht.json")
    state.update(0.016)
    assert sm.wechsel == [("menu", {"track_error": True})]
