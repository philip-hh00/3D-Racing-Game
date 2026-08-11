"""Die KI muss auch auf fremde Spielerfahrzeuge reagieren (Playtest 04.08.2026).

Gemeldet: „KI reagiert nicht auf die anderen Userfahrzeuge, dabei sind ja
positions und geschwindigkeitsdaten vorhanden damit sollte die KI auch auf die
anderen Userfahrzeuge reagieren bzüglich ausweichen überholen usw."

Die Daten waren da, die KI hat sie nie gesehen. Zwei Ursachen.

**Das Feld war eine Momentaufnahme.** ``race_state.enter`` hat jedem Regler die
Liste ``[*humans, *ai_vehicles]`` gegeben — so, wie das Feld beim Start aussah.
Die Abbilder der Mitspieler entstehen aber erst mit ihrer ersten Nachricht, also
**immer** danach. Sie standen damit in keiner Gegnerliste. Jetzt halten alle
Regler dieselbe Liste, und ``_ai_feld_auffrischen`` schreibt sie je Bild fort.

**Ein Abbild war kein brauchbarer Gegner.** ``RemoteVehicle`` hatte kein
``speed``; die Ausweichlogik fragt genau danach (»steht das Auto vor mir?«). Wäre
das Abbild einfach in die Liste gewandert, hätte es einen ``AttributeError``
gegeben — der eine Fehler, der beim Zuschauen aussieht wie „reagiert nicht".

Geprüft wird nicht die Liste, sondern das Verhalten: dasselbe Fahrzeug, dieselbe
Strecke, einmal mit und einmal ohne fremdes Auto davor — die Regler müssen
verschiedene Eingaben liefern.
"""
from __future__ import annotations

import math
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402
import pymunk  # noqa: E402

from src.ai.ai_controller import AIController  # noqa: E402
from src.ai.difficulty import get_difficulty  # noqa: E402


# ---------------------------------------------------------------------------
# Eine gerade Strecke und ein Fahrzeug, das darauf fährt
# ---------------------------------------------------------------------------
class _Strecke:
    """Eine kerzengerade Strecke nach Osten — jede Ausweichbewegung ist damit
    eindeutig zu sehen, weil ohne Gegner nichts zu lenken wäre."""

    def __init__(self, n: int = 400, schritt: float = 40.0) -> None:
        from src.track.track import Waypoint
        self.waypoints = [Waypoint(i * schritt, 0.0) for i in range(n)]
        self.width = 300.0

    def get_nearest_waypoint_index(self, pos) -> int:
        beste, weite = 0, float("inf")
        for i, w in enumerate(self.waypoints):
            d = math.dist(pos, w.pos)
            if d < weite:
                beste, weite = i, d
        return beste

    def get_track_width(self) -> float:
        return self.width


class _Fahrzeug:
    """Ein Fahrzeug, soweit der Regler es anfasst."""

    def __init__(self, pos, tempo: float = 120.0, winkel: float = 0.0) -> None:
        koerper = pymunk.Body(1200, 5000)
        koerper.position = pymunk.Vec2d(*pos)
        koerper.velocity = pymunk.Vec2d(tempo, 0.0)
        koerper.angle = winkel
        self.physics = types.SimpleNamespace(
            position=pos, speed=tempo, angle=winkel,
            steer_angle=0.0, body=koerper)
        self.config = types.SimpleNamespace(name="Testwagen")
        self.id = 1

    @property
    def position(self):
        return self.physics.position

    @property
    def speed(self):
        return self.physics.speed

    @property
    def angle(self):
        return self.physics.angle

    @property
    def body(self):
        return self.physics.body


def _abbild(pos, tempo: float, *, bereit: bool = True):
    """Ein RemoteVehicle ohne Netz: nur Lage, Tempo und Bereitschaft gesetzt."""
    from src.entities.remote_vehicle import RemoteVehicle
    rv = RemoteVehicle.__new__(RemoteVehicle)
    rv._pos = pos
    rv._vel = (tempo, 0.0)
    rv._angle = 0.0
    rv._initialized = bereit
    return rv


def _regler(gegner: list, tempo: float = 120.0) -> AIController:
    strecke = _Strecke()
    auto = _Fahrzeug((0.0, 0.0), tempo)
    r = AIController(auto, strecke, get_difficulty("medium"))
    r.opponents = gegner
    # Gitterhaltung überspringen: sie gilt nur in den ersten Sekunden nach dem
    # Start und würde die Messung überlagern.
    r._grid_hold_t = 99.0
    return r


def _eingaben(gegner: list) -> tuple[float, float, float]:
    r = _regler(gegner)
    return r.compute_inputs(1.0 / 60)


# ---------------------------------------------------------------------------
# Ein Abbild ist ein brauchbarer Gegner
# ---------------------------------------------------------------------------
def test_ein_abbild_kennt_sein_tempo():
    """Der zweite Fund: die Ausweichlogik fragt ``speed``, und es gab keines."""
    rv = _abbild((100.0, 0.0), 90.0)
    assert rv.speed == pytest.approx(90.0)
    assert rv.position == (100.0, 0.0)


def test_das_tempo_ist_in_derselben_einheit_wie_am_eigenen_auto():
    """``Vehicle.speed`` ist die Länge des Geschwindigkeitsvektors in px/s. Wäre
    das Abbild in km/h unterwegs, hielte die KI jedes fremde Auto für stehend."""
    rv = _abbild((0.0, 0.0), 0.0)
    rv._vel = (30.0, 40.0)
    assert rv.speed == pytest.approx(50.0)


def test_ein_abbild_ohne_nachricht_gilt_nicht_als_bereit():
    """Vor der ersten Nachricht steht es auf (0, 0) — als Gegner wäre es ein
    Gespenst, dem eine KI mitten auf der Strecke auszuweichen versucht."""
    assert _abbild((0.0, 0.0), 0.0, bereit=False).bereit is False
    assert _abbild((0.0, 0.0), 0.0).bereit is True


# ---------------------------------------------------------------------------
# Die KI reagiert darauf — gemessen, nicht behauptet
# ---------------------------------------------------------------------------
def test_ein_fremdes_auto_direkt_davor_aendert_die_lenkung():
    """Der Kern: dieselbe Lage, einmal mit und einmal ohne Abbild davor."""
    ohne = _eingaben([])
    mit = _eingaben([_abbild((70.0, 0.0), 120.0)])
    assert abs(mit[2] - ohne[2]) > 0.05, (
        f"Lenkung unverändert: ohne {ohne[2]:.3f}, mit {mit[2]:.3f}")


def _seitlich(r: AIController) -> float:
    """Wie weit der Zielpunkt neben der Mittellinie liegt.

    Die Teststrecke läuft genau nach Osten, die Querachse ist also y. Ohne
    Gegner liegt der Zielpunkt auf 0 — jeder Wert daneben ist Ausweichen.
    """
    return r.dbg_look[1]


def test_ein_stehendes_fremdes_auto_wird_weiter_umfahren_als_ein_fahrendes():
    """Ein Mitspieler, der am Start stehen bleibt oder sich gedreht hat, ist ein
    Hindernis und kein Gegner: die KI soll deutlicher aussenrum als bei einem,
    der mitfährt — und nicht dahinter warten."""
    fahrend = _regler([_abbild((70.0, 0.0), 120.0)])
    fahrend.compute_inputs(1.0 / 60)
    stehend = _regler([_abbild((70.0, 0.0), 0.0)])
    stehend.compute_inputs(1.0 / 60)
    assert abs(_seitlich(fahrend)) > 20.0, "gar kein Ausweichen"
    assert abs(_seitlich(stehend)) > abs(_seitlich(fahrend)) + 20.0


def test_ein_deutlich_langsameres_auto_dicht_davor_bremst_die_ki_ein():
    """Auf freier Strecke gibt die KI bei 60 px/s Gas. Mit einem fremden Auto
    dicht davor, das nur 30 fährt, muss sie stattdessen verzögern."""
    frei = _regler([], tempo=60.0)
    frei.compute_inputs(1.0 / 60)
    assert frei.dbg_state == "drive"

    r = _regler([_abbild((55.0, 0.0), 30.0)], tempo=60.0)
    r.compute_inputs(1.0 / 60)
    assert r.dbg_state in ("brake", "coast"), r.dbg_state


def test_die_ki_merkt_ein_auto_vor_sich():
    r = _regler([_abbild((70.0, 0.0), 120.0)])
    r.compute_inputs(1.0 / 60)
    assert r.dbg_car_ahead is True


def test_ein_fremdes_auto_weit_hinten_stoert_nicht():
    """Sonst würde die KI schon auf der Gegengeraden ausweichen."""
    ohne = _eingaben([])
    weit = _eingaben([_abbild((-4000.0, 0.0), 120.0)])
    assert weit == pytest.approx(ohne)


def test_ein_abbild_ohne_nachricht_bewegt_die_ki_nicht():
    """Es steht auf (0, 0) — genau da, wo die KI selbst steht."""
    ohne = _eingaben([])
    gespenst = _eingaben([_abbild((0.0, 0.0), 0.0, bereit=False)])
    # Der Regler bekommt es gar nicht zu sehen (race_state filtert), aber selbst
    # wenn: auf dem eigenen Punkt darf es keine Lenkbewegung auslösen.
    assert abs(gespenst[2] - ohne[2]) < 0.5


# ---------------------------------------------------------------------------
# Das Feld im Rennen: eine Liste, fortgeschrieben
# ---------------------------------------------------------------------------
class _RennenGeruest:
    """``RaceState`` nur mit den Feldern, die ``_ai_feld_auffrischen`` anfasst."""

    def __init__(self, menschen, ki, abbilder) -> None:
        from src.states.race_state import RaceState
        self._echt = RaceState.__new__(RaceState)
        self._echt._humans = menschen
        self._echt.ai_vehicles = ki
        self._echt._remote_vehicles = abbilder
        self._echt._ai_feld = []

    def feld(self) -> list:
        self._echt._ai_feld_auffrischen()
        return self._echt._ai_feld


def test_das_feld_nimmt_die_abbilder_der_mitspieler_auf():
    mensch = _Fahrzeug((0.0, 0.0))
    ki = _Fahrzeug((100.0, 0.0))
    rv = _abbild((200.0, 0.0), 120.0)
    g = _RennenGeruest([mensch], [ki], [rv])
    assert g.feld() == [mensch, ki, rv]


def test_ein_spaeter_dazugekommenes_abbild_landet_im_feld():
    """Genau der Fund: die Abbilder entstehen **immer** nach dem Start."""
    mensch = _Fahrzeug((0.0, 0.0))
    abbilder: list = []
    g = _RennenGeruest([mensch], [], abbilder)
    assert g.feld() == [mensch]
    abbilder.append(_abbild((200.0, 0.0), 120.0))
    assert len(g.feld()) == 2, "nach dem Start dazu — und trotzdem gesehen"


def test_ein_abbild_ohne_nachricht_bleibt_draussen():
    mensch = _Fahrzeug((0.0, 0.0))
    g = _RennenGeruest([mensch], [], [_abbild((0.0, 0.0), 0.0, bereit=False)])
    assert g.feld() == [mensch]


def test_ein_abgemeldetes_abbild_verschwindet_wieder():
    mensch = _Fahrzeug((0.0, 0.0))
    rv = _abbild((200.0, 0.0), 120.0)
    abbilder = [rv]
    g = _RennenGeruest([mensch], [], abbilder)
    assert rv in g.feld()
    abbilder.remove(rv)
    assert rv not in g.feld()


def test_die_liste_wird_fortgeschrieben_und_nicht_ersetzt():
    """Der Kern der Bauweise: die Regler halten **diese** Liste. Wer sie
    ersetzt, schneidet jeden Regler von der Änderung ab — und genau so war der
    Fehler entstanden."""
    mensch = _Fahrzeug((0.0, 0.0))
    g = _RennenGeruest([mensch], [], [])
    vorher = g.feld()
    g._echt._remote_vehicles.append(_abbild((200.0, 0.0), 120.0))
    nachher = g.feld()
    assert nachher is vorher, "die Liste wurde ersetzt statt fortgeschrieben"


def test_jede_ki_haelt_dieselbe_liste():
    """Sonst sieht eine von ihnen ein anderes Feld als die nächste."""
    quelle = open(os.path.join(_ROOT, "src", "states", "race_state.py"),
                  encoding="utf-8").read()
    for zeile in quelle.splitlines():
        if ".opponents" in zeile and "=" in zeile and "self._ai_feld" not in zeile:
            assert False, f"eigenes Feld statt der gemeinsamen Liste: {zeile.strip()}"


def test_das_feld_wird_im_rennen_je_bild_aufgefrischt():
    """An jeder Stelle einzeln nachzuziehen wäre genau der vergessene Aufruf."""
    quelle = open(os.path.join(_ROOT, "src", "states", "race_state.py"),
                  encoding="utf-8").read()
    schleife = quelle.split("def update(self, dt: float) -> None:")[1]
    schleife = schleife.split("\n    def ")[0]
    assert "_ai_feld_auffrischen()" in schleife
