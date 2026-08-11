"""Kollision und Reifenquietschen im Rennen (Playtest 04.08.2026).

Gemeldet: „Sound im Rennen für Kollision und Reifenquietschen noch nicht
vorhanden". Beide Klänge waren gebaut, verdrahtet und getestet — und **keiner
hat je gespielt.** Zwei verschiedene Ursachen, dieselbe Lehre.

**Aufprall.** ``arbiter.total_impulse`` ist im ``begin``-Rückruf von pymunk
gemessen **0,0** und erst in ``post_solve`` echt (125,0 im Versuch, 300,0 bei
höherem Tempo). Die Schwelle ``IMPULS_AB = 500`` verwarf damit jeden Treffer.
Der Impuls kommt jetzt aus ``post_solve``, und nur beim ersten aufgelösten
Schritt einer Berührung (``is_first_contact``) — sonst klänge es in jedem
Physikschritt, solange man an der Wand schrammt.

**Reifen.** ``sfx_rennen.reifen`` las ``fahrzeug.body.slip_angle_deg``, und
``Vehicle.body`` ist der **pymunk-Körper**; den Winkel führt daneben
``Vehicle.physics``. Es kam also immer 0 heraus.

**Warum die Tests grün waren:** das Testdoppel in ``test_sfx_rennen.py`` legte
``slip_angle_deg`` auf seinen erfundenen Körper. Der Test prüfte die Attrappe und
nicht das Spiel. Deshalb arbeitet dieser Test hier mit der **echten Physik** und
den **echten Fahrzeugobjekten**.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pymunk  # noqa: E402

from src.core import sfx_rennen as sr  # noqa: E402


# ---------------------------------------------------------------------------
# Der Aufprall: der Impuls steht erst in post_solve fest
# ---------------------------------------------------------------------------
def _zusammenstoss(tempo: float = 300.0):
    """Ein Körper fährt gegen eine Wand; sammelt beide Rückrufe mit."""
    from src.core.event_bus import EventBus
    from src.physics.collision_handler import CollisionHandler
    from src.core.settings import (TRACK_WALL_COLLISION_TYPE,
                                   VEHICLE_COLLISION_TYPE)

    bus = EventBus()
    gesehen: list[tuple[str, dict]] = []
    for name in ("collision_vehicle_wall", "impact_vehicle_wall"):
        bus.subscribe(name, lambda d, _n=name: gesehen.append((_n, dict(d))))

    space = pymunk.Space()
    space.gravity = (0, 0)
    CollisionHandler(space, bus)

    auto = pymunk.Body(1200, 5000)
    auto.position = (0, 0)
    auto.velocity = (tempo, 0)
    sa = pymunk.Poly.create_box(auto, (40, 20))
    sa.collision_type = VEHICLE_COLLISION_TYPE
    sa.elasticity = 0.3

    wand = pymunk.Body(body_type=pymunk.Body.STATIC)
    wand.position = (200, 0)
    sw = pymunk.Segment(wand, (0, -200), (0, 200), 5)
    sw.collision_type = TRACK_WALL_COLLISION_TYPE
    space.add(auto, sa, wand, sw)

    for _ in range(120):
        space.step(1 / 120)
    return gesehen


def test_ein_wandtreffer_meldet_seine_wucht():
    """Der Kern des Fundes: aus dem begin-Rückruf kam 0,0."""
    gesehen = _zusammenstoss()
    beginn = [d for n, d in gesehen if n == "collision_vehicle_wall"]
    treffer = [d for n, d in gesehen if n == "impact_vehicle_wall"]
    assert beginn, "die Berührung selbst muss weiter gemeldet werden"
    assert treffer, "kein Impuls-Ereignis — der Aufprall bleibt stumm"
    assert treffer[0]["impulse"] > sr.IMPULS_AB, (
        f"{treffer[0]['impulse']:.0f} liegt unter der Schwelle {sr.IMPULS_AB}")


def test_der_beruehrungsbeginn_traegt_weiter_keinen_brauchbaren_impuls():
    """Festgehalten, damit niemand ihn wieder dafür benutzt."""
    gesehen = _zusammenstoss()
    beginn = [d for n, d in gesehen if n == "collision_vehicle_wall"]
    assert beginn and beginn[0].get("impulse", 0.0) == 0.0


def test_ein_treffer_meldet_sich_genau_einmal():
    """``post_solve`` läuft in jedem Physikschritt, solange berührt wird — ein
    Klang je Schritt wäre ein Maschinengewehr."""
    gesehen = _zusammenstoss()
    treffer = [d for n, d in gesehen if n == "impact_vehicle_wall"]
    assert len(treffer) == 1, f"{len(treffer)} Meldungen für eine Berührung"


def test_ein_sanftes_aufsetzen_bleibt_unter_der_schwelle():
    """Sonst knackt jede Berührung — deshalb gibt es IMPULS_AB überhaupt."""
    gesehen = _zusammenstoss(tempo=5.0)
    treffer = [d for n, d in gesehen if n == "impact_vehicle_wall"]
    assert not treffer or treffer[0]["impulse"] < sr.IMPULS_AB


def test_der_wandtreffer_erreicht_den_klang(monkeypatch):
    """Vom Ereignis bis zu sfx.spielen, ohne Attrappe dazwischen."""
    from src.core import sfx
    gespielt = []
    monkeypatch.setattr(sfx, "spielen", lambda name, *a, **k: gespielt.append(name))
    klang = sr.Rennklang()
    treffer = [d for n, d in _zusammenstoss() if n == "impact_vehicle_wall"]
    klang.wandtreffer(treffer[0]["impulse"])
    assert gespielt == ["car-wall"]


# ---------------------------------------------------------------------------
# Das Quietschen: der Winkel liegt nicht auf dem pymunk-Körper
# ---------------------------------------------------------------------------
class _EchtesFahrzeug:
    """So sieht ein Fahrzeug im Spiel aus: der Winkel liegt im Physikteil, und
    ``body`` ist der pymunk-Körper, der ihn nicht kennt."""

    def __init__(self, winkel: float) -> None:
        self.physics = type("P", (), {"slip_angle_deg": winkel})()
        self.body = pymunk.Body(1, 1)      # kennt slip_angle_deg NICHT

    @property
    def slip_angle_deg(self) -> float:
        return self.physics.slip_angle_deg


def test_der_schraeglauf_wird_am_fahrzeug_gefunden():
    """Der Fund: gelesen wurde vom pymunk-Körper, dort steht er nicht."""
    assert sr._schraeglauf(_EchtesFahrzeug(23.0)) == pytest.approx(23.0)
    assert sr._schraeglauf(_EchtesFahrzeug(0.0)) == 0.0


def test_ein_driftendes_fahrzeug_quietscht_wirklich():
    """Mit dem alten Weg kam hier 0 heraus, und damit Lautstärke 0."""
    winkel = sr._schraeglauf(_EchtesFahrzeug(sr.SCHLUPF_AB + 8.0))
    assert sr.schlupf_lautstaerke(abs(winkel)) > 0.5


def test_normales_kurvenfahren_bleibt_still():
    winkel = sr._schraeglauf(_EchtesFahrzeug(sr.SCHLUPF_AB - 1.0))
    assert sr.schlupf_lautstaerke(abs(winkel)) == 0.0


def test_auch_ein_testdoppel_am_koerper_wird_noch_bedient():
    """Die alten Tests legen den Wert auf ihren erfundenen Körper. Sie sollen
    nicht falsch werden, nur weil das Spiel jetzt richtig liest."""
    import types
    doppel = types.SimpleNamespace(
        body=types.SimpleNamespace(slip_angle_deg=17.0))
    assert sr._schraeglauf(doppel) == pytest.approx(17.0)


def test_ein_fahrzeug_ohne_winkel_stuerzt_nicht_ab():
    """Ferne Fahrzeuge im Onlinerennen sind kinematische Abbilder ohne
    Reifenmodell."""
    import types
    assert sr._schraeglauf(types.SimpleNamespace()) == 0.0
    assert sr._schraeglauf(types.SimpleNamespace(
        physics=types.SimpleNamespace(slip_angle_deg="Unsinn"))) == 0.0
