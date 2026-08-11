"""Lackierung im Profil — Speichern, Laden, Migration.

Der in Releaseplan D10 geforderte Nachweis für Block D. Geprüft wird die Stelle,
an der die Werkstattwahl zwischen zwei Spielstarts hängt, und die Migration:
**jedes heute existierende Profil kennt `paints` nicht** und muss trotzdem
fehlerfrei laden.

Die Profildatei wird über ``paths.user_path`` in ein tmp-Verzeichnis umgelenkt —
die echte ``data/settings/profile.json`` darf ein Test nie anfassen.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import lack, profile  # noqa: E402


@pytest.fixture
def profil_pfad(tmp_path, monkeypatch):
    """Profildatei ins tmp-Verzeichnis umlenken und den Prozess-Cache leeren."""
    ziel = tmp_path / "profile.json"

    def _user_path(*teile):
        return str(ziel) if teile[-1] == "profile.json" else str(tmp_path.joinpath(*teile))

    monkeypatch.setattr("src.core.paths.user_path", _user_path)
    monkeypatch.setattr(profile, "_current", None)
    yield ziel
    monkeypatch.setattr(profile, "_current", None)


def _schreiben(pfad: Path, daten: dict) -> None:
    """Ein Profil **im Klartext** ablegen — so sahen alle vor dem 02.08.2026 aus."""
    pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")


def _lesen(pfad: Path) -> dict:
    """Die abgelegte Datei als Wörterbuch, egal ob verschlüsselt oder Klartext.

    Seit E4 liegt das Profil verschlüsselt; die Tests hier prüfen weiter den
    *Inhalt* und nicht die Ablage — dafür gibt es ``test_profil_tresor.py``.
    """
    from src.core import tresor
    return json.loads(tresor.lesen(str(pfad)))


# ---------------------------------------------------------------------------
# Speichern und Laden
# ---------------------------------------------------------------------------
def test_wahl_ueberlebt_neustart(profil_pfad):
    p = profile.Profile(username="Tester")
    p.set_paint("supercar", "metallic:kobaltblau")
    p.set_paint("drifter_2", "neon:magenta")

    geladen = profile.Profile.load()
    assert geladen.paint("supercar") == "metallic:kobaltblau"
    assert geladen.paint("drifter_2") == "neon:magenta"


def test_wahl_ist_je_fahrzeug_getrennt(profil_pfad):
    p = profile.Profile(username="Tester")
    p.set_paint("supercar", "metallic:kobaltblau")
    # Ein anderes Fahrzeug bleibt unberührt — nicht global eine Farbe.
    assert p.paint("drifter") == lack.WERK
    assert profile.Profile.load().paint("drifter") == lack.WERK


def test_werkslack_wird_ausgetragen(profil_pfad):
    """Werkslack ist die Vorbelegung und braucht keinen Eintrag. Ein Profil, das
    einmal umlackiert und wieder zurückgesetzt wurde, sieht wieder aus wie
    vorher — sonst sammeln sich Einträge ohne Wirkung."""
    p = profile.Profile(username="Tester")
    p.set_paint("supercar", "neon:rubinrot")
    assert "supercar" in p.paints
    p.set_paint("supercar", lack.WERK)
    assert "supercar" not in p.paints
    assert _lesen(profil_pfad)["paints"] == {}


# ---------------------------------------------------------------------------
# Migration und Robustheit
# ---------------------------------------------------------------------------
def test_altes_profil_ohne_paints_laedt(profil_pfad):
    """Der heutige Stand: kein Profil kennt `paints`. Genau dieser Fall muss
    fehlerfrei laden und auf Werkslack stehen."""
    _schreiben(profil_pfad, {
        "username": "philip",
        "best_laps": {"oval": 16.2},
        "menu_volume": 0.2,
        "language": "de",
        "seen_announcements": ["2026-07-17-welcome"],
    })
    p = profile.Profile.load()
    assert p.username == "philip"
    assert p.best_laps["oval"] == pytest.approx(16.2)
    assert p.paints == {}
    assert p.paint("supercar") == lack.WERK


def test_altes_profil_behaelt_seine_werte_beim_speichern(profil_pfad):
    """Migration darf nichts verlieren: einmal laden und speichern lässt Name,
    Bestzeiten und gesehene Ankündigungen unverändert."""
    vorher = {
        "username": "philip",
        "best_laps": {"oval": 16.2, "city": 30.1},
        "menu_volume": 0.2,
        "race_volume": 0.4,
        "language": "de",
        "seen_announcements": ["a", "b"],
    }
    _schreiben(profil_pfad, vorher)
    profile.Profile.load().save()
    nachher = _lesen(profil_pfad)
    for schluessel, wert in vorher.items():
        assert nachher[schluessel] == wert, schluessel
    assert nachher["paints"] == {}


@pytest.mark.parametrize("muell", [
    "quatsch:blau",          # unbekanntes Finish
    "metallic:knallrosa",    # unbekannte Farbe
    "metallic",              # kein Doppelpunkt
    "",                      # leer
    None,                    # falscher Typ
    123,                     # falscher Typ
    {"a": 1},                # falscher Typ
])
def test_unbekannte_kennung_faellt_auf_werkslack(profil_pfad, muell):
    """Ein neuerer Build, eine verstümmelte Netznachricht oder eine von Hand
    verbogene Zeile dürfen höchstens Werkslack ergeben, nie einen Absturz."""
    _schreiben(profil_pfad, {"username": "x", "paints": {"supercar": muell}})
    assert profile.Profile.load().paint("supercar") == lack.WERK


def test_paints_falscher_typ_wird_verworfen(profil_pfad):
    """`paints` als Liste statt Objekt — kaputte Datei, kein Absturz."""
    _schreiben(profil_pfad, {"username": "x", "paints": ["neon:magenta"]})
    p = profile.Profile.load()
    assert p.paints == {}
    assert p.paint("supercar") == lack.WERK


def test_kaputte_datei_gibt_leeres_profil(profil_pfad):
    profil_pfad.write_text("{ das ist kein JSON", encoding="utf-8")
    p = profile.Profile.load()
    assert p.paints == {}
    assert p.paint("supercar") == lack.WERK


def test_set_paint_lehnt_muell_ab(profil_pfad):
    """Auch der Schreibweg normalisiert: nichts Ungültiges landet in der Datei."""
    p = profile.Profile(username="Tester")
    p.set_paint("supercar", "metallic:knallrosa")
    assert p.paints == {}
    assert _lesen(profil_pfad)["paints"] == {}
