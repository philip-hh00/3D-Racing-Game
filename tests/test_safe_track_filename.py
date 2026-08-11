"""Dateinamen empfangener Strecken dürfen nicht aus dem Ordner ausbrechen.

Audit-Fund: ``_save_received_map`` übernahm den Namen aus der MAP_META-Nachricht
ungeprüft. Ein Host, der ``track_name`` auf ``../../../Startup/x.json`` setzt,
schreibt damit eine Datei außerhalb des Streckenordners — mit Inhalt, den er
selbst bestimmt. Auslösbar von jedem, der eine Lobby hostet.

Mit dem geplanten Teilen eigener Strecken durch alle Spieler wächst die Fläche
weiter, deshalb sitzt die Prüfung zentral in ``paths.safe_track_filename``.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core.paths import safe_track_filename  # noqa: E402


@pytest.mark.parametrize("boesartig", [
    "../../entkommen.json",
    "..\\..\\windows.json",
    "a/b/../../../weg.json",
    "/etc/passwd.json",
    "C:\\Windows\\System32\\x.json",
    "....//....//x.json",
    "../" * 20 + "tief.json",
])
def test_kein_pfadanteil_ueberlebt(boesartig):
    sauber = safe_track_filename(boesartig)
    assert "/" not in sauber and "\\" not in sauber
    assert not sauber.startswith(".")
    assert ".." not in sauber


@pytest.mark.parametrize("boesartig", [
    "../../entkommen.json", "..\\..\\windows.json", "/etc/passwd.json",
])
def test_ergebnis_bleibt_im_zielordner(tmp_path, boesartig):
    ziel = tmp_path / "data" / "tracks" / "online"
    ziel.mkdir(parents=True)
    pfad = os.path.abspath(os.path.join(ziel, safe_track_filename(boesartig)))
    assert pfad.startswith(os.path.abspath(str(ziel)))


def test_normaler_name_bleibt_erhalten():
    assert safe_track_filename("Rundkurs.json") == "Rundkurs.json"


def test_leerzeichen_und_klammern_erlaubt():
    assert safe_track_filename("Mein Kurs (v2).json") == "Mein Kurs (v2).json"


@pytest.mark.parametrize("roh", ["", None, "...", "   ", "/", "\\", "..", "///"])
def test_unbrauchbarer_name_faellt_auf_standard_zurueck(roh):
    assert safe_track_filename(roh) == "online_track.json"


def test_endung_wird_ergaenzt():
    assert safe_track_filename("ohne_endung") == "ohne_endung.json"


def test_ueberlange_namen_werden_gekuerzt():
    lang = "a" * 500 + ".json"
    sauber = safe_track_filename(lang)
    assert len(sauber) <= 80
    assert sauber.endswith(".json")


def test_steuerzeichen_fliegen_raus():
    assert safe_track_filename("bo\x00se\nstrecke.json") == "bosestrecke.json"


def test_eigener_standardwert():
    assert safe_track_filename("..", fallback="ersatz.json") == "ersatz.json"
