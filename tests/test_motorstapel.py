"""Gestapelte Motorstimmen klingen wie einzeln gerechnete (01.10.2026).

Der Erzeugerfaden rechnet alle hoerbaren Stimmen in einem Durchgang
(``motorstapel.bloecke``). Die Einzelstimme ``Motorstimme.block`` bleibt als
Bezugswert: beide muessen auf 1e-5 dasselbe liefern, Block fuer Block, samt
fortgefuehrtem Zustand. Die Schichten sind synthetisch, damit der Test ohne die
(nicht eingecheckten) Aufnahmen laeuft.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import motorstapel, sfx  # noqa: E402


def _schichten(name: str, upms: list[int], saat: int) -> sfx.Schichten:
    s = sfx.Schichten.__new__(sfx.Schichten)
    s.motor = name
    rng = np.random.default_rng(saat)
    s.drehzahlen = list(upms)
    s.schleifen = []
    for i, u in enumerate(upms):
        n = int(60000 + 7000 * i)
        t = np.arange(n) / sfx.SR
        f = u / 5.0
        sig = (0.4 * np.sin(2 * np.pi * f * t) + 0.2 * np.sin(2 * np.pi * 2 * f * t)
               + 0.05 * rng.standard_normal(n))
        s.schleifen.append(sig.astype(np.float32))
    return s


@pytest.fixture
def motoren(monkeypatch):
    monkeypatch.setitem(sfx._schichten_cache, "a",
                        _schichten("a", [900, 1500, 2400, 3500, 5000], 1))
    monkeypatch.setitem(sfx._schichten_cache, "b",
                        _schichten("b", [1000, 2000, 4000, 6000], 2))


WERTE = [
    {},                                                    # Vorgabe
    {"hochpass_hz": 40.0, "begrenzer_schwelle": 0.5,
     "begrenzer_tempo_ms": 12.0, "zyklusstreuung": 0.01},
    {"drehzahlglaettung": 120.0, "knie_upm": 3000.0, "kompression": 0.3,
     "grundpegel": 0.8, "schichtblende": 0.5, "zyklusstreuung": 0.005},
    {"hochpass_hz": 25.0},
]


def _paar():
    """Zwei gleiche Gruppen von Stimmen (gleiche Zufallsfolgen)."""
    def bauen():
        sfx._streuung_nr = 100
        aus = []
        for i, (m, th, fa) in enumerate([("a", 1.0, 0.4), ("b", 1.03, -0.3),
                                         ("a", 0.97, 0.0), ("b", 1.05, 0.7)]):
            from src.core import motorklang
            w = motorklang.werte(m)
            w.update(WERTE[i])
            aus.append(sfx.Motorstimme(m, th, fa, werte=w,
                                       startphase_streuen=True))
        return aus
    return bauen(), bauen()


def _upms(k: int) -> list[float]:
    return [1200 + 90 * k, 3000 + 40 * k, 5200 - 70 * (k % 15) , 800 + 400 * (k % 9)]


def test_gestapelt_gleich_einzeln():
    einzeln, stapel = _paar()
    for k in range(40):
        u = _upms(k)
        ref = np.stack([s.block(x, 1024) for s, x in zip(einzeln, u)])
        neu = motorstapel.bloecke(stapel, u, 1024)
        assert neu.shape == ref.shape and neu.dtype == np.float32
        assert np.max(np.abs(neu - ref)) < 1e-5, f"Block {k}"
    for a, b in zip(einzeln, stapel):
        assert abs(a.phase - b.phase) < 1e-9
        assert a._gewichte == pytest.approx(b._gewichte)
        assert a.faerbung._nach == pytest.approx(b.faerbung._nach)


def test_teilmenge_und_wechselnde_zusammensetzung():
    """Stimmen kommen und gehen (Hoerweite): der Zustand bleibt je Stimme."""
    einzeln, stapel = _paar()
    for k in range(30):
        auswahl = [i for i in range(4) if (k + i) % 3 != 0] or [0]
        u = _upms(k)
        ref = np.stack([einzeln[i].block(u[i], 1024) for i in auswahl])
        neu = motorstapel.bloecke([stapel[i] for i in auswahl],
                                  [u[i] for i in auswahl], 1024)
        assert np.max(np.abs(neu - ref)) < 1e-5, f"Block {k}"


def test_andere_blocklaenge():
    einzeln, stapel = _paar()
    for k in range(6):
        n = (512, 1024, 700)[k % 3]
        u = _upms(k)
        ref = np.stack([s.block(x, n) for s, x in zip(einzeln, u)])
        neu = motorstapel.bloecke(stapel, u, n)
        assert np.max(np.abs(neu - ref)) < 1e-5


def test_stimme_ohne_aufnahmen_bleibt_still(monkeypatch):
    monkeypatch.setitem(sfx._schichten_cache, "leer", sfx.Schichten.__new__(sfx.Schichten))
    s = sfx._schichten_cache["leer"]
    s.motor, s.drehzahlen, s.schleifen = "leer", [], []
    stumm = sfx.Motorstimme("leer")
    aus = motorstapel.bloecke([stumm], [3000.0], 256)
    assert aus.shape == (1, 256) and not aus.any()
