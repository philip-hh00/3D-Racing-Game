"""Persönlichkeit und Fehler der KI-Fahrer: fest aus der Startnummer."""
from __future__ import annotations

import ki_hilfe as H  # noqa: F401
from src.ai.fahrer import Fehlerquelle, persoenlichkeit
from src.ai.stufen import STUFEN


def test_gleiche_nummer_gleiche_persoenlichkeit():
    assert persoenlichkeit(3, STUFEN["hard"]) == persoenlichkeit(3, STUFEN["hard"])
    assert persoenlichkeit(3, STUFEN["hard"]) != persoenlichkeit(4, STUFEN["hard"])


def test_werte_im_rahmen():
    for seed in range(50):
        p = persoenlichkeit(seed, STUFEN["medium"])
        assert -40.0 <= p.bremspunkt_px <= 40.0
        assert 0.985 <= p.kurve <= 1.015
        assert 0.3 <= p.konstanz <= 1.0
        assert 0.6 <= p.angriff <= 1.4


def _fehler_je_minute(stufe, seed=1, minuten=60):
    q = Fehlerquelle(seed, stufe, persoenlichkeit(seed, stufe))
    anzahl, vorher = 0, None
    for _ in range(int(minuten * 60 / 0.1)):
        f = q.schritt(0.1)
        if f is not None and f is not vorher:
            anzahl += 1
        vorher = f
    return anzahl / minuten


def test_anfaenger_macht_mehr_fehler_als_meister():
    assert _fehler_je_minute(STUFEN["easy"]) > 3 * _fehler_je_minute(STUFEN["expert"])
    assert 0.5 < _fehler_je_minute(STUFEN["easy"]) < 4.0


def test_fehler_sind_wiederholbar():
    a = Fehlerquelle(7, STUFEN["easy"], persoenlichkeit(7, STUFEN["easy"]))
    b = Fehlerquelle(7, STUFEN["easy"], persoenlichkeit(7, STUFEN["easy"]))
    for _ in range(3000):
        fa, fb = a.schritt(0.1), b.schritt(0.1)
        assert (fa is None) == (fb is None)
        if fa is not None:
            assert (fa.art, round(fa.rest, 6)) == (fb.art, round(fb.rest, 6))
