"""Die vier festen KI-Stufen (Entwurf docs/superpowers/specs/2026-09-30-fahrer-ki-design.md)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai.stufen import REIHE, STUFEN, Stufe, stufe


def test_vier_stufen_in_fester_reihenfolge():
    assert REIHE == ("easy", "medium", "hard", "expert")
    assert [STUFEN[k].name for k in REIHE] == ["Anfänger", "Fortgeschritten", "Profi", "Meister"]


def test_jede_stufe_ist_schneller_und_mutiger_als_die_davor():
    for a, b in zip(REIHE, REIHE[1:]):
        sa, sb = STUFEN[a], STUFEN[b]
        assert sa.haftung < sb.haftung
        assert sa.bremsen < sb.bremsen
        assert sa.bremspunkt_m > sb.bremspunkt_m
        assert sa.fehler_je_min > sb.fehler_je_min
        assert sa.mut < sb.mut
        assert sa.aufholhilfe >= sb.aufholhilfe


def test_aufholhilfe_nur_unten():
    assert STUFEN["easy"].aufholhilfe > 0 and STUFEN["medium"].aufholhilfe > 0
    assert STUFEN["hard"].aufholhilfe == 0 and STUFEN["expert"].aufholhilfe == 0


def test_taktiken_nach_stufe():
    assert not STUFEN["easy"].verteidigen and not STUFEN["easy"].bremszone_angriff
    assert STUFEN["easy"].ueberholen_nur_langsame
    assert STUFEN["hard"].verteidigen and STUFEN["hard"].bremszone_angriff
    assert STUFEN["expert"].verteidigen and STUFEN["expert"].bremszone_angriff


def test_nachschlagen():
    assert stufe("expert") is STUFEN["expert"]
    assert stufe("Meister") is STUFEN["expert"]
    assert stufe("Einfach") is STUFEN["easy"]       # alte Anzeige
    assert stufe("Schwer") is STUFEN["hard"]
    assert stufe(STUFEN["hard"]) is STUFEN["hard"]
    assert stufe("quatsch") is STUFEN["medium"]
    assert stufe(None) is STUFEN["medium"]
    assert isinstance(stufe("easy"), Stufe)
