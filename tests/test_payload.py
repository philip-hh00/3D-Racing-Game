"""Prüfung eingehender Netzdaten (src/net/payload.py).

Audit-Fund im Rennen: die Pausenliste (``GAME_PAUSED``/``PAUSE_STATUS``) und die
Ergebniszeilen (``RACE_RESULTS``) wurden roh aus der Nachricht übernommen. Ein
Eintrag, der kein Objekt ist, beendete das Spiel beim ersten ``.get()`` — bei
der Pausenliste sogar im Zeichenpfad, also jedes Bild mitten im Rennen.

Menü und Rennen benutzen jetzt dieselbe Regel: verwertbare Einträge behalten,
unbrauchbare verwerfen, nie aufgeben.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.net import payload  # noqa: E402


# ── as_int / as_float ───────────────────────────────────────────────────────

@pytest.mark.parametrize("wert,erwartet", [
    (4, 4), ("6", 6), (4.9, 4), (True, 1),
    (None, 99), ("viele", 99), ([], 99), ({}, 99),
])
def test_as_int(wert, erwartet):
    assert payload.as_int(wert, 99) == erwartet


@pytest.mark.parametrize("wert,erwartet", [
    (1.5, 1.5), ("2.5", 2.5), (3, 3.0),
    (None, None), ("schnell", None), ([], None),
    (float("nan"), None), (float("inf"), None), (float("-inf"), None),
])
def test_as_float(wert, erwartet):
    assert payload.as_float(wert) == erwartet


def test_as_float_eigener_standardwert():
    assert payload.as_float("kaputt", 7.0) == 7.0


# ── dict_entries ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("roh", ["Text", None, 42, {"kein": "Array"}, (1, 2)])
def test_dict_entries_nur_listen(roh):
    assert payload.dict_entries(roh) == []


def test_dict_entries_filtert_nichtobjekte():
    roh = [{"a": 1}, None, 7, "Text", [], {"b": 2}]
    assert payload.dict_entries(roh) == [{"a": 1}, {"b": 2}]


def test_dict_entries_laesst_inhalte_unangetastet():
    eintrag = {"name": "Ann", "ready": True}
    assert payload.dict_entries([eintrag])[0] is eintrag


# ── players ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("eintrag", [
    None, 7, "Text", {"name": "ohne Slot"}, {"slot": "x"},
    {"slot": None}, {"slot": -1}, {"slot": []},
])
def test_players_verwirft_unzuordenbare(eintrag):
    assert payload.players([eintrag]) == []


def test_players_normalisiert_slot_zu_ganzzahl():
    """Ein Slot als Text würde bei jedem Vergleich mit dem eigenen durchfallen."""
    sauber = payload.players([{"slot": "3", "name": "Ann"}])
    assert sauber[0]["slot"] == 3 and isinstance(sauber[0]["slot"], int)


def test_players_behaelt_die_gueltigen():
    roh = [{"slot": 0, "name": "Ann"}, None, {"slot": "x"}, {"slot": 2, "name": "Bo"}]
    assert [p["slot"] for p in payload.players(roh)] == [0, 2]


def test_players_kopiert_statt_das_original_zu_aendern():
    original = {"slot": "5", "name": "Ann"}
    payload.players([original])
    assert original["slot"] == "5"


# ── Die Stellen im Rennen, die das benutzen ─────────────────────────────────

@pytest.mark.parametrize("roh", [
    [7], [None], "kaputt", None, [{"name": "Ann"}, None, 42],
])
def test_pausenliste_ist_immer_zeichenbar(roh):
    """Nachbau der Schleife aus dem Zeichenpfad: kein Eintrag darf .get sprengen."""
    for p in payload.dict_entries(roh):
        p.get("name", "Spieler")
        p.get("ready", False)


@pytest.mark.parametrize("roh", [
    [7], [None], "kaputt", None, [{"position": 1}, "Text"],
])
def test_ergebniszeilen_sind_immer_lesbar(roh):
    for r in payload.dict_entries(roh):
        r.get("position")
        r.get("slot")
