"""Streckendateien duerfen das Spiel nicht abstuerzen lassen.

Kaputte Streckendateien sind kein Sonderfall, sondern Alltag:

* eigene Strecken im Ordner ``data/tracks/custom`` werden von Hand bearbeitet
* online empfangene Strecken koennen bei Verbindungsabbruch unvollstaendig sein
* der Editor kann bei einem Absturz mitten im Speichern unterbrochen werden

Die Streckenauswahl prueft heute nur die Mittellinie. Eine Datei mit gueltiger
Mittellinie, aber kaputten Wegpunkten uebersteht die Auswahl und schlaegt erst
beim Rennstart zu — deshalb muss der Lader selbst robust sein.

Der Grundsatz hier: **ueberspringen statt abstuerzen**. Was sich nicht lesen
laesst, wird verworfen; was lesbar ist, wird benutzt. Nur eine Strecke ohne
brauchbare Mittellinie ist wertlos und wirft eine klare, abfangbare Ausnahme.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from src.physics.physics_world import PhysicsWorld  # noqa: E402
from src.track.track import Track, TrackDataError  # noqa: E402

GUTE_MITTELLINIE = [{"x": float(i * 100), "y": 0.0} for i in range(8)]


def _schreibe(tmp_path, inhalt) -> str:
    p = tmp_path / "strecke.json"
    p.write_text(json.dumps(inhalt), encoding="utf-8")
    return str(p)


def _lade(tmp_path, inhalt) -> Track:
    return Track(_schreibe(tmp_path, inhalt), PhysicsWorld().space)


# ── Beschaedigte Einzelfelder werden uebersprungen ───────────────────────────

@pytest.mark.parametrize("waypoints", [
    [{"y": 1.0}],                                  # x fehlt
    [42],                                          # gar kein Objekt
    [{"x": "links", "y": 0}],                      # Text statt Zahl
    [None],
    "keine Liste",
])
def test_kaputte_wegpunkte_stuerzen_nicht_ab(tmp_path, waypoints):
    track = _lade(tmp_path, {"centerline": GUTE_MITTELLINIE, "waypoints": waypoints})
    assert track.waypoints == []
    assert len(track.centerline) == 8


def test_gute_wegpunkte_bleiben_erhalten_wenn_einer_kaputt_ist(tmp_path):
    """Ein einzelner Schaden darf nicht die ganze Strecke unbrauchbar machen."""
    track = _lade(tmp_path, {
        "centerline": GUTE_MITTELLINIE,
        "waypoints": [
            {"x": 0.0, "y": 0.0, "is_checkpoint": True},
            {"x": "kaputt", "y": 0.0},
            {"x": 200.0, "y": 0.0},
        ],
    })
    assert len(track.waypoints) == 2
    assert len(track.get_checkpoints()) == 1


@pytest.mark.parametrize("start_positions", [
    [{"x": 0.0}],                                  # y fehlt
    [{"x": "a", "y": "b"}],
    [None],
    {"kein": "Array"},
])
def test_kaputte_startpositionen_werden_ersetzt(tmp_path, start_positions):
    """Fehlen brauchbare Startplaetze, baut der Lader sie aus der Mittellinie."""
    track = _lade(tmp_path, {"centerline": GUTE_MITTELLINIE,
                             "start_positions": start_positions})
    assert len(track.start_positions) >= 6


@pytest.mark.parametrize("breite,erwartet", [
    ("breit", 100.0),      # Text -> Standardwert
    (None, 100.0),
    (-5, 100.0),           # negative Breite ist unbrauchbar
    (250, 250.0),
])
def test_streckenbreite_faellt_auf_standard_zurueck(tmp_path, breite, erwartet):
    track = _lade(tmp_path, {"centerline": GUTE_MITTELLINIE, "track_width": breite})
    assert track.track_width == erwartet


def test_kaputte_waende_werden_verworfen(tmp_path):
    track = _lade(tmp_path, {
        "centerline": GUTE_MITTELLINIE,
        "outer_wall": [{"x": 0, "y": 0}, {"x": "?", "y": 1}, {"x": 2, "y": 2}],
        "inner_wall": "unbrauchbar",
    })
    assert len(track.outer_wall) == 2
    assert track.inner_wall == []


# ── Unbrauchbare Dateien werfen eine klare, abfangbare Ausnahme ──────────────

@pytest.mark.parametrize("inhalt", [
    [1, 2, 3],                                     # Liste statt Objekt
    "nur Text",
    42,
    {},                                            # keine Mittellinie
    {"centerline": "nope"},
    {"centerline": []},
    {"centerline": [{"x": 0, "y": 0}]},            # zu wenige Punkte
])
def test_unbrauchbare_datei_wirft_trackdataerror(tmp_path, inhalt):
    with pytest.raises(TrackDataError):
        _lade(tmp_path, inhalt)


def test_kaputtes_json_wirft_trackdataerror(tmp_path):
    p = tmp_path / "strecke.json"
    p.write_text('{"centerline": [{"x": 0,', encoding="utf-8")
    with pytest.raises(TrackDataError):
        Track(str(p), PhysicsWorld().space)


def test_leere_datei_wirft_trackdataerror(tmp_path):
    p = tmp_path / "strecke.json"
    p.write_text("", encoding="utf-8")
    with pytest.raises(TrackDataError):
        Track(str(p), PhysicsWorld().space)


def test_fehlende_datei_wirft_trackdataerror(tmp_path):
    with pytest.raises(TrackDataError):
        Track(str(tmp_path / "gibtsnicht.json"), PhysicsWorld().space)


def test_trackdataerror_ist_abfangbar_als_exception():
    """Aufrufer sollen mit einem einzigen except auskommen."""
    assert issubclass(TrackDataError, Exception)


# ── Eingebaute Strecken bleiben unveraendert ladbar ──────────────────────────

@pytest.mark.parametrize("name", ["oval", "city", "desert", "mountain", "gp"])
def test_eingebaute_strecken_laden_weiterhin(name):
    track = Track(f"data/tracks/{name}.json", PhysicsWorld().space)
    assert len(track.centerline) > 3
    assert len(track.start_positions) >= 6
    assert track.track_width > 0
