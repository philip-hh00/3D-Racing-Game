"""Einbau der neuen KI: Stufen im Menü, keine alten Linienbauer mehr."""
from __future__ import annotations

import pathlib

import ki_hilfe as H

WURZEL = pathlib.Path(H.WURZEL)


def test_vier_stufen_im_rennaufbau():
    from src.core import race_setup
    assert race_setup.DIFFICULTY_KEYS == ["easy", "medium", "hard", "expert"]
    assert race_setup.DIFFICULTY_LABELS["expert"] == "Meister"
    assert race_setup.DIFFICULTY_LABELS["easy"] == "Anfänger"


def test_niemand_baut_mehr_alte_linien():
    for pfad in ("src/states/race_state.py", "src/core/ghost.py"):
        text = (WURZEL / pfad).read_text(encoding="utf-8")
        assert "compute_racing_line_optimized" not in text, pfad
        assert "src.ai.difficulty" not in text, pfad
        assert "SolvedRacingLine" not in text, pfad


def test_online_lobby_kennt_meister():
    text = (WURZEL / "src/states/menu/online_lobby_page.py").read_text(encoding="utf-8")
    assert '"expert"' in text


def test_uebersetzungen():
    import json
    en = json.loads((WURZEL / "data/i18n/en.json").read_text(encoding="utf-8"))
    for name in ("Anfänger", "Fortgeschritten", "Profi", "Meister"):
        assert name in en
