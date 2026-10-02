"""Der Erzeuger kostet den Spielfaden fast nichts mehr (01.10.2026).

Drei Dinge: der Mischer rechnet stumme Stimmen nicht und legt je Stueck nichts
neu an, gestapelte und einzelne Stimmen ergeben dieselbe Summe, und der
Erzeugerprozess startet, liefert Ton, endet sauber und hinterlaesst nichts.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core import sfx, tonmischer, tonprozess  # noqa: E402


class _Sinus:
    """Einfache Quelle; mit ``stapel`` rechnet der Mischer mehrere zusammen."""

    def __init__(self, f: float, mit_stapel: bool) -> None:
        self.f = f
        self.pos = 0
        self.aufrufe = 0
        if mit_stapel:
            self.stapel = self._stapel

    def _block(self, n: int) -> np.ndarray:
        t = (self.pos + np.arange(n)) / 48000.0
        self.pos += n
        return (0.5 * np.sin(2 * np.pi * self.f * t)).astype(np.float32)

    def __call__(self, n: int):
        self.aufrufe += 1
        return self._block(n)

    @staticmethod
    def _stapel(quellen: list, n: int):
        for q in quellen:
            q.aufrufe += 1
        return np.stack([q._block(n) for q in quellen])


def _mischer(mit_stapel: bool):
    m = tonmischer.Mischer(kapazitaet=1 << 15, vorrat=1 << 14, stueck=1024)
    quellen = [_Sinus(f, mit_stapel) for f in (110.0, 170.0, 230.0)]
    stimmen = [m.stimme_anlegen(q, 0.3 + 0.1 * i, 0.6 - 0.1 * i)
               for i, q in enumerate(quellen)]
    return m, quellen, stimmen


def test_gestapelte_summe_gleicht_der_einzelnen():
    a, _qa, sa = _mischer(False)
    b, _qb, sb = _mischer(True)
    for k in range(6):
        if k == 3:                                   # Lautstaerke aendern: Verlauf
            for s in sa + sb:
                s.einstellen(0.9, 0.1)
        assert a.erzeugen() == b.erzeugen() == 1024
    n = a.fuellstand
    assert np.max(np.abs(a.abrufen(n) - b.abrufen(n))) < 1e-5


def test_stumme_stimmen_werden_nicht_gerechnet():
    m, quellen, stimmen = _mischer(True)
    stimmen[1].einstellen(0.0, 0.0)
    stimmen[2].einstellen(0.0, 0.0)
    m.erzeugen()                       # Ausblenden: gerechnet
    m.erzeugen()                       # ab jetzt still
    vorher = m.gerechnet
    aufrufe = [q.aufrufe for q in quellen]
    m.erzeugen()
    assert m.gerechnet - vorher == 1
    assert quellen[1].aufrufe == aufrufe[1] and quellen[2].aufrufe == aufrufe[2]


def test_summenpuffer_wird_wiederverwendet():
    m, _q, _s = _mischer(True)
    m.erzeugen()
    puffer = m._summe
    m.erzeugen()
    m.erzeugen()
    assert m._summe is puffer


def test_beendete_stimmen_werden_abgeraeumt_und_gemeldet():
    gemeldet = []
    m = tonmischer.Mischer(kapazitaet=1 << 14, vorrat=1 << 13, stueck=1024,
                           bei_entfernt=gemeldet.append)
    s = m.stimme_anlegen(_Sinus(100.0, True), 0.5, 0.5)
    m.erzeugen()
    s.beenden()
    m.erzeugen()
    m.erzeugen()
    assert m.stimmen == 0 and gemeldet == [s]


# ── Erzeugerprozess ──────────────────────────────────────────────────────────

@pytest.mark.skipif(not sfx.Motorstimme("6zyl"), reason="keine Motoraufnahmen")
def test_erzeugerprozess_liefert_ton_und_beendet_sich_sauber():
    ok, warum = tonprozess.prozess_moeglich()
    if not ok and "Umgebungsvariable" not in warum:
        pytest.skip(warum)
    p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
    try:
        p.starten()
        ende = time.monotonic() + 20
        while not p.bereit and time.monotonic() < ende:
            time.sleep(0.05)
        assert p.bereit, "Erzeuger wurde nicht bereit"
        sp = p.speicher
        m = tonmischer.Mischer(kapazitaet=1 << 14, vorrat=4800, stueck=1024,
                               begrenzen=True, ring=sp.ring, zaehler=sp.zaehler)
        v = p.stimme_anlegen("6zyl", 1.0, 0.2, 0.5, 0.5)
        assert v is not None and p.stimmen == 1
        v.drehzahl_setzen(3000.0)
        ende = time.monotonic() + 10
        while m.fuellstand < 2048 and time.monotonic() < ende:
            time.sleep(0.01)
        assert m.fuellstand >= 2048
        # Der Ring war schon mit Stille gefuellt, bevor die Stimme dazukam:
        # lesen, bis Ton ankommt.
        block = np.zeros((1, 2), dtype=np.float32)
        ende = time.monotonic() + 10
        while np.abs(block).max() <= 0.01 and time.monotonic() < ende:
            if m.fuellstand >= 1024:
                block = m.abrufen(1024)
            else:
                time.sleep(0.005)
        assert np.abs(block).max() > 0.01
        v.beenden()
        ende = time.monotonic() + 5
        while p.stimmen and time.monotonic() < ende:
            time.sleep(0.01)
        assert p.stimmen == 0, "Platz wurde nicht freigegeben"
        proz = p.prozess
        del m, block
    finally:
        p.beenden()
    assert proz.poll() is not None, "Erzeugerprozess lebt noch"


# ── Befehlszeile, Start ueber main.py, Rueckfall ─────────────────────────────

def test_kommando_gepackt_und_aus_den_quellen():
    gepackt = tonprozess.kommando("shm1", 42, 16384, gepackt=True,
                                  interpreter="C:/Spiel/3D-Racing-Game.exe")
    assert gepackt == ["C:/Spiel/3D-Racing-Game.exe", "--tonprozess", "shm1", "42",
                       "16384"]
    quellen = tonprozess.kommando("shm1", 42, 16384, gepackt=False,
                                  interpreter="python")
    assert quellen == ["python", "-m", "src.core.tonprozess", "shm1", "42", "16384"]


def test_main_springt_vor_der_einzelinstanz_in_den_erzeuger():
    """Die Flagge muss vor ``einzelinstanz.beanspruchen`` verarbeitet werden,
    sonst bekommt der zweite Start das Fenster 'laeuft bereits'."""
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(wurzel, "main.py"), encoding="utf-8") as fh:
        quelle = fh.read()
    assert tonprozess.FLAGGE in quelle
    assert quelle.index(tonprozess.FLAGGE) < quelle.index("beanspruchen()")


@pytest.mark.skipif(not sfx.Motorstimme("6zyl"), reason="keine Motoraufnahmen")
def test_start_ueber_main_py_mit_flagge(monkeypatch):
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setattr(
        tonprozess, "kommando",
        lambda name, pid, kap, *a, **k: [sys.executable, os.path.join(wurzel, "main.py"),
                                         tonprozess.FLAGGE, name, str(pid), str(kap)])
    p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
    try:
        p.starten()
        ende = time.monotonic() + 20
        while not p.bereit and time.monotonic() < ende and p.lebt():
            time.sleep(0.05)
        assert p.bereit, "Erzeuger ueber main.py wurde nicht bereit"
        proz = p.prozess
    finally:
        p.beenden()
    assert proz.poll() is not None


def test_ausgefallener_erzeuger_faellt_auf_den_faden_zurueck(monkeypatch):
    """Ein Prozess, der sofort endet: kein Ausfall des Tons, der Faden uebernimmt."""
    import types
    from src.core import tonausgabe as ta

    class Strom:
        def __init__(self, samplerate, **kw):
            self.samplerate, self.callback, self.device = samplerate, kw["callback"], 0

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    modul = types.ModuleType("sounddevice")
    modul.OutputStream = lambda **kw: Strom(**kw)
    modul.query_devices = lambda n: {"name": "Attrappe"}
    monkeypatch.setitem(sys.modules, "sounddevice", modul)
    monkeypatch.setattr(ta, "PROZESS", True)
    monkeypatch.setattr(ta, "WACHE_SEKUNDEN", 0.1)
    monkeypatch.setattr(tonprozess, "prozess_moeglich", lambda: (True, ""))
    monkeypatch.setattr(tonprozess, "kommando",
                        lambda *a, **k: [sys.executable, "-c", "pass"])
    ta.beenden()
    try:
        assert ta.starten() is True
        assert ta._prozess is not None
        v = ta.motorstimme_anlegen(_Sinus(300.0, True), "6zyl", 1.0, 0.0, 0.5, 0.5)
        assert v is not None
        ende = time.monotonic() + 10
        while ta._im_prozess and time.monotonic() < ende:
            time.sleep(0.05)
        assert not ta._im_prozess, "kein Rueckfall"
        rueckruf = ta._strom.callback
        ton = np.zeros((512, 2), dtype=np.float32)
        ende = time.monotonic() + 5
        while not np.any(ton) and time.monotonic() < ende:
            time.sleep(0.02)
            rueckruf(ton, 512, None, None)
        assert np.any(ton), "nach dem Rueckfall nur Stille"
        # Neue Stimmen gehen jetzt direkt in den Faden.
        assert ta.motorstimme_anlegen(_Sinus(200.0, True), "6zyl", 1.0, 0.0) is not None
        assert ta.zustand()["erzeuger"].startswith("faden")
    finally:
        ta.beenden()
