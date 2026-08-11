"""Geschenkte Strecken müssen überall auftauchen, wo eigene stehen.

Playtest-Fund vom 29.07.2026, **nur auf macOS** reproduzierbar: eine
heruntergeladene Strecke lag als Datei vor, war aber weder in der
Grand-Prix-Übersicht noch im Streckeneditor wählbar.

Ursache ist keine macOS-Eigenheit, sondern ein Unterschied, der nur dort
sichtbar wird: die Listen suchen über **relative** Pfade, also im
Arbeitsverzeichnis. Beim Start aus dem Quellcode ist das dasselbe Verzeichnis,
in das auch geschrieben wird — auf einem gepackten macOS-Build aber zeigt das
Arbeitsverzeichnis ins schreibgeschützte App-Bundle, während Schreibzugriffe
nach ``~/Library/Application Support`` gehen. Die Datei war also da, nur an
einer Stelle, an der niemand nachsah.

Diese Tests stellen genau das her: ein Nutzerverzeichnis, das **nicht** das
Arbeitsverzeichnis ist.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import paths  # noqa: E402


@pytest.fixture
def getrennte_verzeichnisse(tmp_path, monkeypatch):
    """Nutzerdaten liegen woanders als die mitgelieferten Dateien — wie auf
    einem gepackten macOS-Build."""
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(paths, "bundle_dir", lambda: paths.Path(_ROOT))
    monkeypatch.chdir(_ROOT)

    def geschenk(name: str = "Geschenkt") -> str:
        ordner = tmp_path / "data" / "tracks" / "custom"
        ordner.mkdir(parents=True, exist_ok=True)
        pfad = ordner / f"{name}.json"
        mitte = [{"x": 500.0 + 300.0 * (i % 4), "y": 500.0 + 200.0 * (i // 4)}
                 for i in range(12)]
        pfad.write_text(json.dumps({
            "name": name, "difficulty": "Einfach", "track_width": 220.0,
            "centerline": mitte,
            "waypoints": [{"x": p["x"], "y": p["y"], "is_checkpoint": i % 3 == 0}
                          for i, p in enumerate(mitte)],
            # Aus dem Editor stammende Strecken tragen das hier — ohne es
            # zeigt der Editor sie nicht als bearbeitbar an.
            "editor_tiles": [{"kind": "straight", "col": 5, "row": 5, "rotation": 0}],
        }), encoding="utf-8")
        return str(pfad)

    return geschenk


def test_uebersicht_findet_die_geschenkte_strecke(getrennte_verzeichnisse):
    from src.states.menu.gp_overview import load_track_infos
    getrennte_verzeichnisse("Geschenkt")

    strecken = load_track_infos()

    assert any(str(i["name"]) == "Geschenkt" for i in strecken.values()), (
        f"nicht in der Übersicht: {sorted(strecken)}")


def test_uebersicht_zeigt_die_eingebauten_weiterhin(getrennte_verzeichnisse):
    from src.states.menu.gp_overview import load_track_infos
    strecken = load_track_infos()
    assert {"oval", "desert", "city", "mountain", "gp"} <= set(strecken)


def test_uebersicht_zaehlt_keine_strecke_doppelt(getrennte_verzeichnisse):
    """Liegt dieselbe Datei in beiden Wurzeln, gehört sie einmal in die Liste
    — sonst steht sie zweimal in den Kacheln."""
    from src.states.menu.gp_overview import load_track_infos
    getrennte_verzeichnisse("Doppelt")
    schluessel = list(load_track_infos().keys())
    assert len(schluessel) == len(set(schluessel))


def test_streckenauswahl_findet_sie_auch(getrennte_verzeichnisse):
    """Sie liegt bei den eigenen Strecken — also gehört sie auch in die
    normale Streckenauswahl."""
    from src.states.track_select_state import TrackSelectState
    getrennte_verzeichnisse("Geschenkt")

    gefunden = TrackSelectState._streckendateien()

    assert any(p.stem == "Geschenkt" for _k, p, _eigen in gefunden), (
        f"nicht in der Auswahl: {[str(p) for _k, p, _e in gefunden]}")


def test_editor_findet_sie_auch(getrennte_verzeichnisse):
    from src.states.editor_state import veroeffentlichte_strecken
    getrennte_verzeichnisse("Geschenkt")

    gefunden = [os.path.basename(p) for p in veroeffentlichte_strecken()]

    assert "Geschenkt.json" in gefunden, f"nicht im Editor: {gefunden}"


def test_editor_erkennt_eine_veroeffentlichte_strecke(getrennte_verzeichnisse):
    from src.states.editor_state import ist_veroeffentlicht
    getrennte_verzeichnisse("Geschenkt")
    assert ist_veroeffentlicht("Geschenkt") is True
    assert ist_veroeffentlicht("Gibt es nicht") is False


def test_hilfsfunktion_liefert_beide_wurzeln(getrennte_verzeichnisse, tmp_path):
    """Der gemeinsame Nenner: geschrieben wird ins Nutzerverzeichnis, geliefert
    kommt aus dem Bundle. Gesucht werden muss in beidem."""
    getrennte_verzeichnisse("Geschenkt")
    dateien = paths.track_files("custom")
    assert any(p.parent.parent.parent.parent == tmp_path for p in dateien)


def test_hilfsfunktion_vertraegt_fehlende_ordner(monkeypatch, tmp_path):
    """Ein frisch installiertes Spiel hat noch keinen custom-Ordner."""
    leer = tmp_path / "leer"
    leer.mkdir()
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "gibt_es_nicht")
    monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path / "auch_nicht")
    monkeypatch.chdir(leer)          # sonst zählt das Repo als dritte Wurzel
    assert paths.track_files("custom") == []
