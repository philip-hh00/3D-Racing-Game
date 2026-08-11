"""Start und Ziel auf der Minimap: eine Linie quer zur Fahrbahn.

Gewünscht am 08.08.2026: „Es wäre schön, wenn statt einer Raute für die Start-
und Ziellinie eine Linie dargestellt wird."

Vorher stand dort ein Punkt — ein weiss gefüllter Kreis mit 4 px Radius. Der
sagt, **wo** die Linie ist, aber nicht, **wie sie liegt**: auf einer Strecke mit
mehreren Geraden nebeneinander sieht man dem Punkt nicht an, in welche Richtung
gestartet wird. Eine Linie quer zur Fahrbahn zeigt beides.

Geprüft wird die Geometrie, nicht das Bild: die Linie muss die Fahrbahn queren
(also etwa so lang sein wie die Strecke breit ist), senkrecht zur Fahrtrichtung
stehen und innerhalb der Anzeige liegen. Aus Pixeln liesse sich das auch
ablesen, aber ungenau und mit einem Test, den niemand mehr versteht.
"""
from __future__ import annotations

import json
import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.hud.minimap import Minimap  # noqa: E402


class _StreckenAttrappe:
    """Nur das, was die Minimap von einer Strecke liest."""

    class _Wegpunkt:
        def __init__(self, x: float, y: float) -> None:
            self.x, self.y = x, y

    def __init__(self, name: str = "oval") -> None:
        with open(os.path.join(_ROOT, "data", "tracks", f"{name}.json"),
                  encoding="utf-8") as fh:
            daten = json.load(fh)
        self.centerline = [(p["x"], p["y"]) for p in daten["centerline"]]
        self.outer_wall = [(p["x"], p["y"]) for p in daten.get("outer_wall", [])]
        self.inner_wall = [(p["x"], p["y"]) for p in daten.get("inner_wall", [])]
        self.track_width = float(daten.get("track_width", 250.0))
        self.waypoints = [self._Wegpunkt(x, y) for x, y in self.centerline]


@pytest.fixture(params=["oval", "city", "gp", "mountain", "desert"])
def karte(request):
    strecke = _StreckenAttrappe(request.param)
    return Minimap(strecke), strecke


def test_die_startmarkierung_ist_eine_linie_und_kein_punkt(karte):
    """Zwei verschiedene Enden — sonst ist es wieder ein Punkt."""
    minimap, _strecke = karte
    a, b = minimap.startlinie()

    assert a != b
    assert math.dist(a, b) >= 4.0, (
        f"die Linie ist nur {math.dist(a, b):.1f} px lang — auf der Minimap "
        f"nicht von einem Punkt zu unterscheiden")


def test_die_linie_ist_so_breit_wie_die_fahrbahn(karte):
    """Sie soll die Strecke queren, nicht darüber hinausragen.

    Eine Linie, die aus der Fahrbahn herausschaut, sieht auf der Minimap aus
    wie ein Abzweig.
    """
    minimap, strecke = karte
    a, b = minimap.startlinie()

    laenge = math.dist(a, b)
    soll = strecke.track_width * minimap._scale
    assert abs(laenge - soll) <= max(2.0, soll * 0.15), (
        f"{laenge:.1f} px lang, die Fahrbahn misst hier {soll:.1f} px")


def test_die_linie_steht_quer_zur_fahrtrichtung(karte):
    """Längs statt quer wäre keine Ziellinie, sondern ein Stück Fahrbahn."""
    minimap, strecke = karte
    a, b = minimap.startlinie()

    p0 = minimap._world_to_map(strecke.centerline[0])
    p1 = minimap._world_to_map(strecke.centerline[1])
    fahrt = (p1[0] - p0[0], p1[1] - p0[1])
    linie = (b[0] - a[0], b[1] - a[1])

    lf = math.hypot(*fahrt) or 1.0
    ll = math.hypot(*linie) or 1.0
    # Skalarprodukt der Einheitsvektoren: 0 heisst genau senkrecht.
    quer = abs((fahrt[0] * linie[0] + fahrt[1] * linie[1]) / (lf * ll))
    assert quer < 0.25, f"Linie und Fahrtrichtung stehen fast parallel ({quer:.2f})"


def test_die_linie_liegt_in_der_anzeige(karte):
    """Halb abgeschnitten waere sie schlimmer als der Punkt vorher."""
    minimap, _strecke = karte
    flaeche = pygame.Rect(0, 0, Minimap.PANEL_W, Minimap.PANEL_H)

    for punkt in minimap.startlinie():
        assert flaeche.collidepoint(punkt), punkt


def test_die_linie_liegt_auf_der_ziellinie(karte):
    """Ihre Mitte gehört auf den ersten Wegpunkt, nicht irgendwohin."""
    minimap, strecke = karte
    a, b = minimap.startlinie()
    mitte = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)

    soll = minimap._world_to_map((strecke.waypoints[0].x, strecke.waypoints[0].y))
    assert math.dist(mitte, soll) <= 2.0, (mitte, soll)


def test_ohne_wegpunkte_gibt_es_keine_linie():
    """Eine Strecke ohne Wegpunkte darf die Minimap nicht umbringen."""
    strecke = _StreckenAttrappe()
    strecke.waypoints = []
    minimap = Minimap(strecke)

    assert minimap.startlinie() is None


def test_die_minimap_zeichnet_sich_mit_der_linie(karte):
    """Der Weg, den das Spiel wirklich geht — einmal ausgeführt."""
    minimap, _strecke = karte
    schirm = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    minimap.render(schirm, [])
