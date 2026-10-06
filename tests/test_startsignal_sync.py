"""Startsignal und Startampel laufen auf einer Zeitleiste (Block C).

Gemeldet: der Startton ist nicht synchron mit den Lampen. Gemessen an
``race-start.wav``: Piep bei 0,0 / 1,0 / 2,0 s, langer Ton bei 3,0 s — die
Lampen zuenden aber im 0,5-s-Takt ab Restzeit 2,5 s. Der Ton lief als ganze
Datei ab Restzeit 3,0 s (erster Piep eine halbe Sekunde vor der ersten Lampe,
jede zweite Lampe stumm) und kam zudem um den Mixerpuffer (2048 Frames = 43 ms)
verspaetet. Jetzt gilt: je Lampe ein Piep, bei GO der lange Ton, vorgezogen um
die Latenz.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import sfx_rennen, startampel  # noqa: E402

#: Abweichung zwischen Lampe und Ton, die noch als gleichzeitig gilt.
TOLERANZ_S = 0.030
PUFFER = 2048


def test_zeitleiste_hat_je_lampe_einen_piep_und_bei_go_den_langen_ton():
    assert startampel.SIGNAL_ZEITEN_S[:startampel.LAMPEN] == startampel.AMPEL_SCHWELLEN_S
    assert startampel.SIGNAL_ZEITEN_S[-1] == 0.0
    assert startampel.SIGNALE == ("piep",) * startampel.LAMPEN + ("los",)
    assert len(startampel.SIGNALE) == len(startampel.SIGNAL_ZEITEN_S)


def test_faelliges_signal_reihenfolge_und_vorlauf():
    f = startampel.faelliges_signal
    assert f(3.0, 0) is None
    assert f(2.5, 0) == 0
    assert f(2.5, 1) is None                      # schon gespielt
    assert f(2.53, 0, vorlauf_s=0.0) is None
    assert f(2.53, 0, vorlauf_s=0.05) == 0        # mit Vorlauf frueher
    assert f(0.0, 5) == 5                         # langer Ton bei GO
    assert f(-0.1, 6) is None                     # alles gespielt


def test_ruckler_spielt_nur_das_juengste_signal():
    assert startampel.faelliges_signal(1.2, 0) == 2


class _Klang:
    def __init__(self, zeit):
        self.zeit = zeit
        self.gespielt = []

    def startsignal(self, nr):
        self.gespielt.append((nr, self.zeit()))


def _zustand(rm, klang, nr=0):
    return SimpleNamespace(_klang=klang, race_manager=rm, _startsignal_nr=nr)


def _countdown_ablauf(monkeypatch, laenge_s, dt, hold_s=0.0):
    """Ein Countdown Bild fuer Bild, wie ``RaceState.update`` ihn treibt.

    Rueckgabe: je Signal (Nummer, Zeit der Lampenschwelle, Zeit, zu der der Ton
    hoerbar wird), alles in Sekunden seit Beginn des Countdowns.
    """
    from src.states.race_state import RaceState
    zeit = {"t": 0.0}
    rm = SimpleNamespace(state="countdown", countdown_timer=laenge_s, race_time=0.0)
    klang = _Klang(lambda: zeit["t"])
    zustand = _zustand(rm, klang)
    vorlauf = sfx_rennen.startsignal_vorlauf_s(PUFFER)
    monkeypatch.setattr(sfx_rennen, "startsignal_vorlauf_s",
                        lambda *a, **k: vorlauf)

    # Online gehaltener Countdown: Restzeit steht still, kein Signal.
    for _ in range(int(hold_s / dt)):
        RaceState._startsignal_pruefen(zustand, dt)
    assert klang.gespielt == []

    # Gleiche Reihenfolge wie im Spiel: erst pruefen, dann fortschreiben.
    for _ in range(int((laenge_s + 1.0) / dt)):
        RaceState._startsignal_pruefen(zustand, dt)
        zeit["t"] += dt
        if rm.state == "countdown":
            rm.countdown_timer -= dt
            if rm.countdown_timer <= 0:
                rm.state = "racing"
        else:
            rm.race_time += dt

    return [(nr, laenge_s - startampel.SIGNAL_ZEITEN_S[nr],
             t + PUFFER / 48000.0 + sfx_rennen.STARTSIGNAL_EINSATZ_S)
            for nr, t in klang.gespielt]


@pytest.mark.parametrize("laenge", [3.0, 3.5])
@pytest.mark.parametrize("dt", [1 / 30, 1 / 60, 1 / 144])
def test_jedes_signal_faellt_mit_seiner_lampe_zusammen(monkeypatch, laenge, dt):
    """Lokal (3,0 s) wie online (3,5 s), bei 30, 60 und 144 Bildern je Sekunde:
    der Ton wird hoerbar, wenn die Lampe zu sehen ist (innerhalb 30 ms plus
    der halben Bilddauer, die die Bildrate ohnehin vorgibt)."""
    ablauf = _countdown_ablauf(monkeypatch, laenge, dt)
    assert [nr for nr, *_ in ablauf] == list(range(len(startampel.SIGNALE)))
    for nr, t_schwelle, t_ton in ablauf:
        # Die Lampe wird im Bild der Schwellenunterschreitung gezeichnet
        # (Ende des Bildes, im Mittel dt/2) und erscheint ein Bild spaeter.
        sichtbar = t_schwelle + 0.5 * dt + sfx_rennen.ANZEIGE_VERZUG_S
        assert abs(t_ton - sichtbar) < TOLERANZ_S + 0.5 * dt, \
            f"Signal {nr}: Ton {t_ton:.3f} s, Lampe {sichtbar:.3f} s"


def test_bei_60_hz_liegt_der_ton_binnen_30_ms_auf_der_lampe(monkeypatch):
    for nr, t_schwelle, t_ton in _countdown_ablauf(monkeypatch, 3.0, 1 / 60):
        sichtbar = t_schwelle + 0.5 / 60 + sfx_rennen.ANZEIGE_VERZUG_S
        assert abs(t_ton - sichtbar) < TOLERANZ_S


def test_der_alte_ablauf_war_mehr_als_die_toleranz_daneben():
    """Gegenprobe zur Messung: die ganze Datei ab Restzeit 3,0 hatte den
    ersten Piep 0,5 s vor der ersten Lampe und der Puffer allein waren 43 ms."""
    assert startampel.AMPEL_SCHWELLEN_S[0] - 0.0 > TOLERANZ_S
    assert PUFFER / 48000.0 > TOLERANZ_S


def test_online_haltephase_loest_nichts_aus(monkeypatch):
    ablauf = _countdown_ablauf(monkeypatch, 3.5, 1 / 60, hold_s=2.0)
    assert [nr for nr, *_ in ablauf] == list(range(6))


def test_langer_ton_liegt_auf_go(monkeypatch):
    nr, t_schwelle, t_ton = _countdown_ablauf(monkeypatch, 3.0, 1 / 60)[-1]
    assert nr == 5
    assert t_schwelle == pytest.approx(3.0)
    assert abs(t_ton - (3.0 + sfx_rennen.ANZEIGE_VERZUG_S)) < TOLERANZ_S


def test_pausierter_countdown_haelt_den_naechsten_piep_zurueck():
    """Pause: die Restzeit steht, also kommt kein weiteres Signal; nach dem
    Fortsetzen geht es dort weiter, wo es war."""
    from src.states.race_state import RaceState
    rm = SimpleNamespace(state="countdown", countdown_timer=2.0, race_time=0.0)
    klang = _Klang(lambda: 0.0)
    zustand = _zustand(rm, klang)
    RaceState._startsignal_pruefen(zustand, 1 / 60)
    assert [nr for nr, _ in klang.gespielt] == [1]       # Lampe 2 (Rest 2,0)
    RaceState._startsignal_pruefen(zustand, 1 / 60)      # Pause: Rest unveraendert
    assert [nr for nr, _ in klang.gespielt] == [1]
    rm.countdown_timer = 1.5
    RaceState._startsignal_pruefen(zustand, 1 / 60)
    assert [nr for nr, _ in klang.gespielt] == [1, 2]


def test_ruckler_ueber_go_hinaus_spielt_den_langen_ton():
    from src.states.race_state import RaceState
    rm = SimpleNamespace(state="racing", countdown_timer=-0.05, race_time=0.01)
    klang = _Klang(lambda: 0.0)
    zustand = _zustand(rm, klang, nr=len(startampel.SIGNALE) - 1)
    RaceState._startsignal_pruefen(zustand, 0.1)
    assert [nr for nr, _ in klang.gespielt] == [5]
    # Mitten im Rennen nie mehr.
    zustand._startsignal_nr = 5
    rm.race_time = 40.0
    RaceState._startsignal_pruefen(zustand, 1 / 60)
    assert len(klang.gespielt) == 1


def test_ohne_klang_kein_signal():
    from src.states.race_state import RaceState
    rm = SimpleNamespace(state="countdown", countdown_timer=0.0, race_time=0.0)
    zustand = _zustand(rm, None)
    RaceState._startsignal_pruefen(zustand, 1 / 60)   # darf nicht werfen
    assert zustand._startsignal_nr == 0


def test_ausschnitte_aus_der_echten_datei(monkeypatch):
    """Mit der echten ``race-start.wav`` und einem Mixer ohne Geraet: Piep und
    langer Ton haben die erwartete Laenge und setzen nach STARTSIGNAL_EINSATZ_S
    ein; der lange Ton beginnt nicht mit einem Rest vom dritten Piep."""
    import numpy as np
    from src.core import sfx
    if not os.path.isfile(sfx._pfad("race-start.wav")):
        pytest.skip("race-start.wav fehlt")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.mixer.quit()
    pygame.mixer.init(frequency=sfx.SR, size=-16, channels=2, buffer=512)
    try:
        from src.core.resource_manager import ResourceManager
        ganz = ResourceManager().load_sound(sfx._pfad("race-start.wav"))
        rate = pygame.mixer.get_init()[0]
        gemessen = {}
        for art, (von, bis) in sfx_rennen.STARTSIGNAL_AUSSCHNITTE.items():
            klang = sfx._ausschnitt(ganz, ("test", art), von, bis)
            assert klang is not None
            x = np.abs(pygame.sndarray.array(klang).astype(np.float32))
            x = x.max(axis=1) if x.ndim == 2 else x
            laut = np.flatnonzero(x > x.max() * 0.1)
            gemessen[art] = (laut[0] / rate, len(x) / rate)
        piep_ein, piep_len = gemessen["piep"]
        los_ein, los_len = gemessen["los"]
        assert piep_ein == pytest.approx(sfx_rennen.STARTSIGNAL_EINSATZ_S, abs=0.004)
        assert los_ein == pytest.approx(sfx_rennen.STARTSIGNAL_EINSATZ_S, abs=0.004)
        assert 0.2 < piep_len < 0.3
        assert 1.0 < los_len < 1.1
    finally:
        pygame.mixer.quit()
        sfx._ausschnitte.clear()
