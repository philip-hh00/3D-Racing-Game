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


# ── Nachbesserungen aus der Durchsicht ───────────────────────────────────────

class _Attrappe:
    """sounddevice-Attrappe; ``raten`` ist die Folge der Raten beim Oeffnen."""

    def __init__(self, monkeypatch, raten=(48000,)):
        import types
        self.raten = list(raten)
        self.strome = []
        attrappe = self

        class Strom:
            def __init__(self, samplerate, **kw):
                self.samplerate = attrappe.raten.pop(0) if len(attrappe.raten) > 1 \
                    else attrappe.raten[0]
                self.callback, self.device = kw["callback"], 0
                attrappe.strome.append(self)

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


def _prozessbetrieb(monkeypatch, kommando=None):
    from src.core import tonausgabe as ta
    monkeypatch.setattr(ta, "PROZESS", True)
    monkeypatch.delenv("RACING_TON_PROZESS", raising=False)
    monkeypatch.setattr(tonprozess, "prozess_moeglich", lambda: (True, ""))
    if kommando is not None:
        monkeypatch.setattr(tonprozess, "kommando", kommando)
    ta.beenden()
    return ta


def test_prozessbetrieb_nur_unter_windows(monkeypatch):
    monkeypatch.delenv("RACING_TON_PROZESS", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    ok, warum = tonprozess.prozess_moeglich()
    assert not ok and "Windows" in warum
    monkeypatch.setattr(sys, "platform", "linux")
    assert not tonprozess.prozess_moeglich()[0]
    monkeypatch.setattr(sys, "platform", "win32")
    assert tonprozess.prozess_moeglich()[0]


def test_klangwerte_gehen_als_stand_an_den_erzeuger(monkeypatch):
    from src.core import motorklang
    gerufen = []
    motorklang.beobachten(lambda: gerufen.append(1))
    try:
        motorklang.setzen("6zyl", "grundpegel", 0.31)
        assert gerufen, "Aenderung wurde nicht gemeldet"
        p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
        try:
            p.werte_senden()
            vorher = int(p.speicher.kopf[tonprozess.K_NEU_LADEN])
            assert vorher >= 1
            motorklang.neu_laden()             # Cache verwerfen, wie der Erzeuger ihn hat
            stand = tonprozess._werte_holen(p.speicher, 0)
            assert stand == vorher
            assert motorklang.werte("6zyl")["grundpegel"] == pytest.approx(0.31)
        finally:
            p.beenden()
    finally:
        motorklang.neu_laden()
        motorklang._beobachter.clear()


def test_erzeuger_uebernimmt_geaenderte_klangwerte():
    from src.core import motorklang
    p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
    try:
        p.werte_senden()
        p.starten()
        ende = time.monotonic() + 20
        while not p.bereit and time.monotonic() < ende:
            time.sleep(0.05)
        assert p.bereit
        k = p.speicher.kopf
        motorklang.setzen("8zyl", "grundpegel", 0.4)
        p.werte_senden()
        ende = time.monotonic() + 5
        while k[tonprozess.K_NEU_IST] != k[tonprozess.K_NEU_LADEN] \
                and time.monotonic() < ende:
            time.sleep(0.02)
        assert k[tonprozess.K_NEU_IST] == k[tonprozess.K_NEU_LADEN]
    finally:
        motorklang.neu_laden()
        p.beenden()


def test_haupt_faengt_alles_und_protokolliert(tmp_path, monkeypatch):
    log = tmp_path / "ton.log"
    monkeypatch.setattr("src.core.paths.user_path", lambda *teile: str(log))
    assert tonprozess.haupt([]) == 1                        # Argumente fehlen
    assert tonprozess.haupt(["gibt_es_nicht_xyz", "1", "1024"]) == 1   # kein Speicher
    assert tonprozess.haupt(["x", "keine_zahl", "1024"]) == 1
    text = log.read_text(encoding="utf-8")
    assert text.count("Erzeugerprozess ausgefallen") == 3


def test_main_flagge_mit_falschen_argumenten_endet_leise():
    import subprocess
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fertig = subprocess.run([sys.executable, os.path.join(wurzel, "main.py"),
                             tonprozess.FLAGGE, "gibt_es_nicht_xyz", "1", "1024"],
                            capture_output=True, text=True, timeout=60, cwd=wurzel)
    assert fertig.returncode == 1


def test_fehlerplatz_bleibt_belegt_bis_der_spielprozess_ihn_freigibt():
    """Ein Erzeuger, der eine Stimme nicht bauen kann, darf den Platz nicht
    freigeben: er gehoert noch der Fernstimme des Spielprozesses."""
    p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
    try:
        sp = p.speicher
        m = tonmischer.Mischer(kapazitaet=1 << 14, vorrat=4800, stueck=1024)
        v = p.stimme_anlegen("gibtsnicht", 1.0, 0.0)
        tonprozess._abgleichen(sp, m, {}, tonmischer)
        assert sp.zustand[v._i] == tonprozess.FEHLER
        w = p.stimme_anlegen("6zyl", 1.0, 0.0)
        assert w._i != v._i, "Platz doppelt vergeben"
        v.beenden()
        tonprozess._abgleichen(sp, m, {}, tonmischer)
        assert sp.zustand[v._i] == tonprozess.FREI
    finally:
        p.beenden()


def test_fernstimme_nach_beenden_ist_ohne_wirkung():
    p = tonprozess.Erzeugerprozess(1 << 14, 1024, 48000, True, 4800)
    v = p.stimme_anlegen("6zyl", 1.0, 0.0)
    p.beenden()
    v.einstellen(0.5, 0.5)
    v.drehzahl_setzen(3000.0)
    v.beenden()


_HAENGER = """
import sys, os, time
sys.path.insert(0, {wurzel!r})
from multiprocessing import shared_memory
from src.core import tonprozess as t
sm = shared_memory.SharedMemory(name=sys.argv[1])
sp = t.Speicher(sm, int(sys.argv[3]))
sp.kopf[t.K_KIND_PID] = os.getpid()
for _ in range(5):
    sp.kopf[t.K_HERZ] += 1
    time.sleep(0.02)
sp.kopf[t.K_BEREIT] = 1
for _ in range(10):
    sp.kopf[t.K_HERZ] += 1
    time.sleep(0.02)
time.sleep(60)         # haengt: kein Herzschlag mehr
"""


def test_haengender_erzeuger_wird_beendet_und_der_faden_uebernimmt(monkeypatch):
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    skript = _HAENGER.format(wurzel=wurzel)
    ta = _prozessbetrieb(monkeypatch, lambda name, pid, kap, *a, **k: [
        sys.executable, "-c", skript, name, str(pid), str(kap)])
    _Attrappe(monkeypatch)
    monkeypatch.setattr(ta, "WACHE_SEKUNDEN", 0.2)
    try:
        assert ta.starten() is True
        p = ta._prozess
        ende = time.monotonic() + 15
        while ta._im_prozess and time.monotonic() < ende:
            time.sleep(0.05)
        assert not ta._im_prozess, "Haenger wurde nicht erkannt"
        pid = int(p.speicher.kopf[tonprozess.K_KIND_PID])
        assert pid
        assert not tonprozess._eltern_lebt(pid)(), "haengender Erzeuger lebt noch"
        assert p.prozess is None or p.prozess.poll() is not None
    finally:
        ta.beenden()


def test_erzeuger_der_nicht_bereit_wird_faellt_zurueck(monkeypatch):
    ta = _prozessbetrieb(monkeypatch, lambda *a, **k: [sys.executable, "-c",
                                                       "import time; time.sleep(60)"])
    _Attrappe(monkeypatch)
    monkeypatch.setattr(ta, "WACHE_SEKUNDEN", 0.2)
    monkeypatch.setattr(ta, "BEREIT_FRIST", 0.6)
    try:
        assert ta.starten() is True
        ende = time.monotonic() + 15
        while ta._im_prozess and time.monotonic() < ende:
            time.sleep(0.05)
        assert not ta._im_prozess
    finally:
        ta.beenden()


def test_neuverbinden_gibt_die_neue_rate_an_den_erzeuger(monkeypatch):
    ta = _prozessbetrieb(monkeypatch)
    _Attrappe(monkeypatch, raten=(48000, 44100))
    try:
        assert ta.starten() is True
        p = ta._prozess
        ende = time.monotonic() + 20
        while not p.bereit and time.monotonic() < ende:
            time.sleep(0.05)
        assert p.bereit and ta._im_prozess
        k = p.speicher.kopf
        ende = time.monotonic() + 5
        while k[tonprozess.K_AUSGABERATE_IST] != 48000 and time.monotonic() < ende:
            time.sleep(0.02)
        assert k[tonprozess.K_AUSGABERATE_IST] == 48000
        assert ta.neu_verbinden() is True
        ende = time.monotonic() + 5
        while k[tonprozess.K_AUSGABERATE_IST] != 44100 and time.monotonic() < ende:
            time.sleep(0.02)
        assert k[tonprozess.K_AUSGABERATE_IST] == 44100, "Erzeuger folgt der Rate nicht"
    finally:
        ta.beenden()
