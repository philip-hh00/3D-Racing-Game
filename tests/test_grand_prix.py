"""Grand-Prix-Serie: Punkte, Wertungstabelle, Gleichstand.

Die Gleichstandsregel ist die übliche aus dem Motorsport: mehr Punkte, dann
mehr Siege, dann mehr zweite Plätze und so weiter.

Audit-Fund: Ausfälle teilten sich den Zähler mit dem sechsten Platz, und weil
alle Zähler absteigend sortiert werden, brachte ein zusätzlicher Ausfall den
Fahrer nach **vorn**. Bei gleichen Punkten und gleichen Siegen gewann damit,
wer häufiger ausgefallen war.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core.grand_prix import GP_POINTS, GrandPrixSeries  # noqa: E402
from src.core import grand_prix  # noqa: E402


def _serie(rennen=3, runden=3) -> GrandPrixSeries:
    return GrandPrixSeries(races_total=rennen, laps_per_race=runden)


def _namen(serie) -> list[str]:
    return [e["name"] for e in serie.get_standings()]


# ── Punktevergabe ───────────────────────────────────────────────────────────

def test_punkte_nach_tabelle():
    s = _serie()
    s.add_race_results([{"name": f"P{i}", "position": i} for i in range(1, 7)])
    for i in range(1, 7):
        assert s.points[f"P{i}"] == GP_POINTS[i]


def test_ausfall_gibt_keine_punkte():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": 1, "dnf": True}])
    assert s.points["Ann"] == 0


def test_punkte_summieren_sich_ueber_rennen():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": 1}])
    s.add_race_results([{"name": "Ann", "position": 3}])
    assert s.points["Ann"] == GP_POINTS[1] + GP_POINTS[3]


# ── Gleichstand ─────────────────────────────────────────────────────────────

def test_mehr_siege_gewinnt_bei_punktgleichstand():
    s = _serie()
    # Ann: Sieg + Fuenfter = 12, Bo: zweimal Zweiter + ... gleiche Punkte bauen
    s.add_race_results([{"name": "Ann", "position": 1}, {"name": "Bo", "position": 2}])
    s.add_race_results([{"name": "Ann", "position": 5}, {"name": "Bo", "position": 4}])
    assert s.points["Ann"] == s.points["Bo"] == 12
    assert _namen(s)[0] == "Ann"          # ein Sieg schlaegt zwei Podestplaetze


def test_ausfall_bringt_niemanden_nach_vorn():
    """Der eigentliche Fund: gleiche Punkte, gleiche Siege, aber einer hat
    zusaetzlich einen Ausfall - der darf nicht belohnt werden."""
    s = _serie(rennen=2)
    s.add_race_results([{"name": "MitAusfall", "position": 1},
                        {"name": "OhneAusfall", "position": 1}])
    s.add_race_results([{"name": "MitAusfall", "position": 2, "dnf": True}])
    assert s.points["MitAusfall"] == s.points["OhneAusfall"]
    assert _namen(s)[0] == "OhneAusfall"


def test_sechster_platz_schlaegt_ausfall():
    """Beide bringen 0 bis 1 Punkt, aber ins Ziel zu kommen ist besser."""
    s = _serie(rennen=2)
    s.add_race_results([{"name": "Sechster", "position": 3},
                        {"name": "Ausfall", "position": 3}])
    s.add_race_results([{"name": "Sechster", "position": 6},
                        {"name": "Ausfall", "position": 6, "dnf": True}])
    assert _namen(s)[0] == "Sechster"


def test_zweite_plaetze_entscheiden_wenn_siege_gleich():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": 2}, {"name": "Bo", "position": 3}])
    s.add_race_results([{"name": "Ann", "position": 3}, {"name": "Bo", "position": 2}])
    s.add_race_results([{"name": "Ann", "position": 2}, {"name": "Bo", "position": 4}])
    # Ann: 8+6+8 = 22, Bo: 6+8+4 = 18
    assert s.points["Ann"] > s.points["Bo"]
    assert _namen(s)[0] == "Ann"


# ── Robustheit gegen kaputte Ergebniszeilen ─────────────────────────────────

@pytest.mark.parametrize("zeilen", [
    "kaputt", None, 42, [None], [7], ["Text"], [{}], [{"position": 1}],
])
def test_unbrauchbare_zeilen_sprengen_die_wertung_nicht(zeilen):
    s = _serie()
    s.add_race_results(zeilen)
    assert s.points == {}


def test_gute_zeilen_ueberleben_neben_kaputten():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": 1}, None,
                        {"kein": "Name"}, {"name": "Bo", "position": 2}])
    assert set(s.points) == {"Ann", "Bo"}


def test_position_als_text_wird_umgewandelt():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": "1"}])
    assert s.points["Ann"] == GP_POINTS[1]


def test_unlesbare_position_gibt_null_punkte():
    s = _serie()
    s.add_race_results([{"name": "Ann", "position": "erster"}])
    assert s.points["Ann"] == 0


# ── Serienverwaltung ────────────────────────────────────────────────────────

def test_serie_starten_und_abbrechen():
    grand_prix.cancel()
    assert not grand_prix.is_active()
    grand_prix.start_series(4, 3)
    assert grand_prix.is_active()
    assert grand_prix.current().races_total == 4
    grand_prix.cancel()
    assert not grand_prix.is_active()
    assert grand_prix.current() is None


def test_leere_wertung_ohne_rennen():
    assert _serie().get_standings() == []


# ── Modus ist auswählbar ────────────────────────────────────────────────────

def test_grand_prix_ist_freigeschaltet():
    """Die itch.io-Seite bewirbt den Modus als Punkt 4 - er muss ihn auch geben."""
    from src.core import race_setup
    assert "Grand Prix" in race_setup.MODES
    assert "Grand Prix" in race_setup.MODES_ENABLED


def test_jeder_modus_hat_eine_beschreibung():
    from src.core import race_setup
    for modus in race_setup.MODES:
        assert race_setup.MODE_DESCRIPTIONS.get(modus)


# ── Serienfortschritt ───────────────────────────────────────────────────────

def test_next_race_schaltet_weiter():
    s = _serie(rennen=3)
    assert s.race_index == 0
    s.next_race()
    assert s.race_index == 1


def test_next_race_laeuft_nicht_ueber():
    """Sonst zeigte die Streckenauswahl 'Rennen 5 / 3'."""
    s = _serie(rennen=3)
    for _ in range(10):
        s.next_race()
    assert s.race_index == 2


def test_races_left_zaehlt_herunter():
    s = _serie(rennen=3)
    assert s.races_left == 3
    s.add_race_results([{"name": "Ann", "position": 1}])
    assert s.races_left == 2


def test_is_finished_erst_nach_dem_letzten_lauf():
    """Gezählt werden gefahrene Läufe, nicht der Zeiger auf den nächsten.

    Der Test hielt vorher die Fehlzählung fest: nach EINEM von zwei Rennen
    galt die Serie als beendet, weil `next_race()` den Index schon
    weitergeschaltet hatte. Online kostete das den letzten Lauf — die
    Siegerehrung kam nach dem vorletzten Rennen (Playtest 29.07.2026).
    """
    s = _serie(rennen=2)
    assert not s.is_finished

    s.add_race_results([{"name": "Ann", "position": 1}])
    s.next_race()
    assert not s.is_finished, "ein Lauf von zweien ist keine fertige Serie"

    s.add_race_results([{"name": "Ann", "position": 1}])
    s.next_race()
    assert s.is_finished


# ── Markierung gefahrener Strecken ──────────────────────────────────────────

def test_gefahrene_strecken_werden_gemerkt():
    s = _serie()
    s.note_track("oval")
    s.note_track("custom/meine")
    assert s.was_raced("oval")
    assert s.was_raced("custom/meine")
    assert not s.was_raced("desert")


def test_wiederholung_ist_erlaubt_und_wird_gezaehlt():
    """Wiederholungen sind zulässig - die Markierung warnt nur davor."""
    s = _serie()
    s.note_track("oval")
    s.note_track("oval")
    assert s.raced_tracks == ["oval", "oval"]


def test_leerer_streckenschluessel_wird_ignoriert():
    s = _serie()
    s.note_track("")
    s.note_track(None)
    assert s.raced_tracks == []
