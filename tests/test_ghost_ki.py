"""Der Erst-Ghost im Zeitfahren ist die KI der Stufe Meister.

Gemeldet am 06.10.2026: „Der erste generierte Ghost startet extrem schnell und
mitten auf der Strecke, man holt ihn nie ein."

**Ursache.** ``generate_seed_ghost`` liess eine KI eine Runde fahren, damit
daraus der Ghost wird. Die Simulation lief aber auf einem eigenen Ereignisbus,
und der ``LapTracker`` meldete ``lap_completed`` auf dem **globalen**. Der
Rennverwalter der Simulation hoerte es nie, das Rennen wurde nie fertig, und nach
dem Zeitlimit griff ``build_fallback_ghost``: ein Ghost aus der Ideallinie, mit
Geschwindigkeiten in der falschen Einheit, beginnend an Punkt 0 der Ideallinie
und nicht am Startplatz. Der echte Weg wurde auf **keiner** Strecke je benutzt.

**Jetzt.** Die KI faehrt die Runde wirklich (echte Physik, aus dem Stand, von der
Startstelle des Spielers), aufgezeichnet als gewoehnlicher Ghost. Sie ist kein
Teilnehmer des Rennens (keine Kollision, keine Wertung) und wird nicht als
Spielerrekord abgelegt; ab der ersten Runde des Spielers gilt dessen Zeit.
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import ghost  # noqa: E402
from tests import spielhilfe  # noqa: E402


@pytest.fixture(autouse=True)
def _eigenes_ghostverzeichnis(monkeypatch, tmp_path):
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    spielhilfe.aufbau_bewahren(monkeypatch)
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.fahrzeuge_laden()
    yield
    spielhilfe.alles_schliessen()


def _zeitfahren(strecke: str = "oval", **kwargs):
    rennen, _sm = spielhilfe.rennen_bauen(strecke, runden=1, feld=1,
                                          modus="Zeitfahren", **kwargs)
    return rennen


def _eigene_strecke(tmp_path) -> str:
    """Das Oval als eigene Strecke: der Pfad enthaelt ``custom``."""
    ordner = tmp_path / "custom"
    ordner.mkdir()
    ziel = ordner / "ki_ghost_teststrecke.json"
    with open(os.path.join(_ROOT, "data", "tracks", "oval.json"),
              encoding="utf-8") as fh:
        daten = json.load(fh)
    daten["name"] = "KI-Ghost-Teststrecke"
    ziel.write_text(json.dumps(daten), encoding="utf-8")
    return str(ziel)


# ---------------------------------------------------------------------------
# 1. Ohne Ghost: die KI der hoechsten Stufe, von der Startstelle des Spielers
# ---------------------------------------------------------------------------

def test_der_alte_erfundene_ghost_ist_weg():
    """Der Rueckfall aus der Ideallinie ist die Ursache des Funds."""
    assert not hasattr(ghost, "build_fallback_ghost")


def test_ohne_ghost_ist_der_erste_die_ki(monkeypatch):
    rennen = _zeitfahren()

    daten = rennen.ghost_player.data
    assert ghost.ist_seed(daten), daten.driver
    assert daten.samples and daten.lap_time > 0
    # Die KI faehrt eine echte Runde: Zwischenzeiten stammen aus den
    # Pruefpunkten der Simulation, nicht aus einer Rechnung.
    assert daten.sectors, "keine Zwischenzeiten - die Simulation wurde nie fertig"


def test_die_ki_faehrt_auf_der_hoechsten_stufe(monkeypatch):
    from src.ai.stufen import REIHE
    from src.entities.vehicle_factory import VehicleFactory

    gebaut: list = []
    echt = VehicleFactory.create_ai_vehicle.__func__

    def spion(cls, **kwargs):
        gebaut.append(kwargs)
        return echt(cls, **kwargs)

    monkeypatch.setattr(VehicleFactory, "create_ai_vehicle",
                        classmethod(spion))
    # Eine niedrige Rennstufe darf auf den Ghost keinen Einfluss haben.
    _zeitfahren(schwierigkeit="easy")

    ghost_ki = [k for k in gebaut if k["vehicle_id"] == ghost.SEED_KENNUNG]
    assert len(ghost_ki) == 1, gebaut
    stufe = ghost_ki[0]["difficulty"]
    assert stufe.key == "expert" == REIHE[-1]


@pytest.mark.parametrize("strecke", ["oval", "city", "gp", "mountain"])
def test_der_ghost_startet_wo_der_spieler_startet(strecke):
    rennen = _zeitfahren(strecke)
    erster = rennen.ghost_player.data.samples[0]
    spieler = rennen.player.body

    assert erster[0] == 0.0
    assert math.hypot(erster[1] - spieler.position.x,
                      erster[2] - spieler.position.y) < 1.0
    drehung = math.atan2(math.sin(erster[3] - spieler.angle),
                         math.cos(erster[3] - spieler.angle))
    assert abs(drehung) < 0.02, (erster[3], spieler.angle)

    # Zum Startzeitpunkt steht der Ghost dort, wo er gezeichnet wird.
    x, y, _a = rennen.ghost_player.get_position(0.0)
    assert math.hypot(x - spieler.position.x, y - spieler.position.y) < 1.0


def test_der_ghost_startet_aus_dem_stand_und_nicht_mitten_auf_der_strecke():
    """Der gemeldete Fund: Tempo und Ort in den ersten Sekunden."""
    rennen = _zeitfahren()
    daten = rennen.ghost_player.data
    start = daten.samples[0]

    # In der ersten Zehntelsekunde nahezu in Ruhe (Stand), und die ersten
    # Sekunden bleibt er in der Naehe des Startplatzes: ein Auto beschleunigt.
    p = rennen.ghost_player
    x1, y1, _ = p.get_position(0.1)
    assert math.hypot(x1 - start[1], y1 - start[2]) < 5.0
    x2, y2, _ = p.get_position(1.0)
    assert math.hypot(x2 - start[1], y2 - start[2]) < 150.0

    # Nirgends schneller als das Auto kann. Der alte Ghost lief mit 640 px/s
    # los und war dabei noch langsam gegen seine Rundenzeit.
    from src.entities.vehicle_factory import VehicleFactory
    cfg = VehicleFactory.get_config(daten.vehicle)
    hoechst = max(
        math.hypot(b[1] - a[1], b[2] - a[2]) / (b[0] - a[0])
        for a, b in zip(daten.samples, daten.samples[1:]) if b[0] > a[0])
    grenze = float(getattr(cfg, "max_speed", 0.0) or 0.0)
    if grenze > 0:
        assert hoechst <= grenze * 1.15, (hoechst, grenze)


def test_die_ki_ist_nicht_unerreichbar_schnell():
    """Die Rundenzeit liegt im Bereich der KI Meister im normalen Rennen.

    Verglichen wird mit demselben Auto in einem 1-Runden-Rennen auf *Meister*.
    Dort startet die KI aus der zweiten Reihe, ist also etwas langsamer; der
    Ghost darf nur nicht weit unter dieser Zeit liegen (der alte: 14,1 s gegen
    22,6 s auf dem Oval) und nicht weit darueber.
    """
    rennen, _sm = spielhilfe.rennen_bauen(
        "oval", runden=1, feld=2, schwierigkeit="expert", ki_fahrzeug="rookie")
    spielhilfe.rennen_fahren(rennen, 90.0)
    ki = next(r for r in rennen.race_manager.results
              if r["vehicle_id"] != 1 and not r["dnf"])["finish_time"]
    spielhilfe.alles_schliessen()

    zeit = _zeitfahren().ghost_player.data.lap_time
    assert 0.85 * ki <= zeit <= 1.15 * ki, (zeit, ki)


def test_die_ki_faehrt_das_auto_des_spielers():
    rennen = _zeitfahren()
    assert rennen.ghost_player.data.vehicle == rennen.player.config_key


def test_der_ghost_ist_bei_jedem_start_derselbe():
    erster = _zeitfahren().ghost_player.data
    spielhilfe.alles_schliessen()
    zweiter = _zeitfahren().ghost_player.data
    assert erster.lap_time == zweiter.lap_time
    assert erster.samples == zweiter.samples


def test_eigene_strecke_bekommt_den_ki_ghost(tmp_path):
    rennen = _zeitfahren(_eigene_strecke(tmp_path))
    assert ghost.ist_seed(rennen.ghost_player.data)
    assert rennen.ghost_player.data.sectors


# ---------------------------------------------------------------------------
# 2. Der Ghost ist kein Teilnehmer und kein Spielerrekord
# ---------------------------------------------------------------------------

def test_der_ki_ghost_ist_kein_teilnehmer():
    rennen = _zeitfahren()
    assert ghost.ist_seed(rennen.ghost_player.data)

    assert rennen.ai_vehicles == []
    assert [v.id for v in rennen.race_manager.vehicles] == [1]
    assert set(rennen.race_manager.lap_trackers) == {1}
    assert [v.id for v in rennen.race_manager._standings] == [1]
    # Kein Koerper in der Rennwelt: dort steht nur das Auto des Spielers.
    koerper = {s.body for s in rennen.physics_world.space.shapes
               if getattr(s, "body", None) is not None
               and s.body.body_type == s.body.DYNAMIC}
    assert koerper == {rennen.player.body}


def test_der_ki_ghost_wird_nicht_als_rekord_abgelegt():
    rennen = _zeitfahren()
    schluessel = rennen._ghost_track_key
    assert ghost.ist_seed(rennen.ghost_player.data)
    assert not ghost.exists(schluessel), \
        "die KI-Runde liegt als Spielerrekord auf der Platte"
    assert ghost.load(schluessel) is None


def test_die_erste_gefahrene_runde_wird_der_ghost_auch_wenn_sie_langsamer_ist():
    """Ab der ersten Zeit des Spielers gilt dessen Runde — unveraendert."""
    rennen = _zeitfahren()
    ki_zeit = rennen.ghost_player.data.lap_time
    schluessel = rennen._ghost_track_key

    langsamer = ki_zeit + 30.0
    rennen.ghost_recorders[1].record(0.0, 1.0, 2.0, 0.0)
    rennen.ghost_recorders[1].record(1.0, 3.0, 4.0, 0.0)
    rennen.race_manager.results = [
        {"vehicle_id": 1, "finish_time": langsamer, "dnf": False}]
    rennen._on_race_finish({})

    assert ghost.exists(schluessel)
    gespeichert = ghost.load(schluessel)
    assert not ghost.ist_seed(gespeichert)
    assert gespeichert.lap_time == pytest.approx(langsamer)
    assert rennen._new_ghost_saved is True


def test_ein_spielerghost_wird_nur_von_einer_schnelleren_runde_ersetzt():
    schluessel = "oval"
    ghost.save(schluessel, ghost.GhostData(
        lap_time=20.0, driver="Philip", vehicle="rookie",
        samples=[[0.0, 1.0, 2.0, 0.0], [1.0, 3.0, 4.0, 0.0]]))
    rennen = _zeitfahren()
    rennen.ghost_recorders[1].record(0.0, 1.0, 2.0, 0.0)
    rennen.race_manager.results = [
        {"vehicle_id": 1, "finish_time": 25.0, "dnf": False}]
    rennen._on_race_finish({})

    assert ghost.load(schluessel).driver == "Philip"
    assert rennen._new_ghost_saved is False


# ---------------------------------------------------------------------------
# 3. Gibt es einen Spielerghost, bleibt es beim normalen Ablauf
# ---------------------------------------------------------------------------

def test_mit_gefahrener_runde_wird_keine_ki_simuliert(monkeypatch):
    schluessel = "oval"
    ghost.save(schluessel, ghost.GhostData(
        lap_time=19.5, driver="Philip", vehicle="rookie",
        samples=[[0.0, 1.0, 2.0, 0.0], [1.0, 3.0, 4.0, 0.0]]))

    def nie(*a, **k):
        raise AssertionError("die KI darf nicht fahren, ein Ghost liegt vor")

    monkeypatch.setattr(ghost, "generate_seed_ghost", nie)
    rennen = _zeitfahren()

    daten = rennen.ghost_player.data
    assert not ghost.ist_seed(daten)
    assert daten.driver == "Philip"
    assert daten.lap_time == 19.5
    assert rennen._original_ghost_driver == "Philip"


# ---------------------------------------------------------------------------
# 4. Scheitert die Simulation, gibt es keinen erfundenen Ghost
# ---------------------------------------------------------------------------

def test_scheitert_die_ki_gibt_es_gar_keinen_ghost(monkeypatch):
    monkeypatch.setattr(ghost, "generate_seed_ghost",
                        lambda *a, **k: ghost.GhostData())
    rennen = _zeitfahren()

    assert rennen.ghost_player is None
    assert not ghost.exists(rennen._ghost_track_key)
    # Das Rennen laeuft trotzdem.
    spielhilfe.rennen_fahren(rennen, 2.0)


# ---------------------------------------------------------------------------
# 5. Die Ursache: Rundenmeldungen auf dem Bus des Rennverwalters
# ---------------------------------------------------------------------------

def test_der_rennverwalter_hoert_die_runden_auf_seinem_eigenen_bus():
    """Mit eigenem Bus muss auch der Rundenzaehler dort melden.

    Sonst wird ein Rennen auf einem isolierten Bus nie fertig — so kam der
    Rueckfall-Ghost zustande.
    """
    from src.core.event_bus import EventBus
    from src.states.race_manager import RaceManager

    rennen = _zeitfahren()
    bus = EventBus.create_isolated()
    verwalter = RaceManager(vehicles=[rennen.player], track=rennen.track,
                            total_laps=1, event_bus=bus)
    try:
        for zaehler in verwalter.lap_trackers.values():
            assert zaehler._event_bus is bus

        gemeldet: list = []
        bus.subscribe("lap_completed", gemeldet.append)
        globale: list = []
        EventBus().subscribe("lap_completed", globale.append)
        verwalter.lap_trackers[1]._complete_lap()
        assert len(gemeldet) == 1
        assert globale == []
    finally:
        verwalter.cleanup()
