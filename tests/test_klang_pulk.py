"""Klang im Pulk: die Motoren dürfen einander nicht beeinflussen (Klang-Pulk).

Gemeldet: „Sind die anderen Autos um mich herum, klingt es völlig unrealistisch,
als würden sich die Einzelklänge beeinflussen; weiter weg höre ich mein Auto
wieder klar. Teils hing es am Ausgabegerät."

Gemessene Ursachen (Szenario: eigenes Auto 5000 UPM, fünf Gegner in 100–300 px
bei 4200–5450 UPM, 6-Zylinder-Aufnahmen):

* Das **Pegelbudget** nahm *alle* Stimmen gemeinsam zurück — auch das eigene
  Auto. Bei fünf Gegnern fiel der Pegel des eigenen Motors auf 48 % (RMS
  0,232 -> 0,110, -6,4 dB), allein durch die Nähe der anderen.
* Die Summe wurde **nirgends begrenzt**: schon bei einem Gegner in 100 px lag die
  Spitze bei 1,05. Float über 1,0 schneidet der Treiber hart ab (je nach Gerät
  und Betriebsmodus verschieden) -> Verzerrung genau im Pulk.
* Alle Stimmen einer Klasse starteten **phasengleich** auf derselben Schleife.
* Der Strom wurde fest mit 48 kHz geöffnet; nimmt ein Gerät (WASAPI geteilt,
  Bluetooth, 44,1 kHz) das nicht an, fiel der ganze Motorklang auf den
  Rückfallweg.
"""
from __future__ import annotations

import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core import sfx, sfx_rennen as sr, tonausgabe as ta, tonmischer


# ── Pegelverteilung ─────────────────────────────────────────────────────────

def _laute(abstaende):
    return [sr.daempfung(d) for d in abstaende]


def test_eigener_motor_bleibt_bei_fuenf_gegnern_unveraendert():
    laut = _laute([0.0, 100.0, 150.0, 200.0, 250.0, 300.0])
    pegel = sr.pegel_zuteilen(laut, [True] + [False] * 5)
    assert pegel[0] == pytest.approx(laut[0], abs=1e-9)
    alleine = sr.pegel_zuteilen(laut[:1], [True])
    assert pegel[0] == pytest.approx(alleine[0])


def test_gegner_summe_ist_begrenzt():
    laut = _laute([0.0] + [60.0] * 8)
    pegel = sr.pegel_zuteilen(laut, [True] + [False] * 8)
    assert sum(pegel[1:]) <= sr.GEGNER_BUDGET + 1e-9


def test_hoechstens_drei_gegner_sind_hoerbar():
    laut = _laute([0.0, 80.0, 110.0, 140.0, 170.0, 200.0, 230.0])
    pegel = sr.pegel_zuteilen(laut, [True] + [False] * 6)
    hoerbar = [p for p in pegel[1:] if p > 1e-6]
    assert len(hoerbar) <= sr.MAX_GEGNER
    assert pegel[1] > 0 and pegel[-1] == 0.0


def test_wenige_gegner_werden_nicht_zurueckgenommen():
    laut = _laute([0.0, 150.0])
    pegel = sr.pegel_zuteilen(laut, [True, False])
    assert pegel[1] == pytest.approx(laut[1])


def test_rangwechsel_springt_nicht():
    """Zwei Gegner tauschen den dritten/vierten Platz: kein Pegelsprung."""
    basis = _laute([100.0, 120.0, 140.0])
    vorher = sr.pegel_zuteilen(basis + _laute([200.0 - 1e-3, 200.0]), [False] * 5)
    nachher = sr.pegel_zuteilen(basis + _laute([200.0 + 1e-3, 200.0]), [False] * 5)
    for a, b in zip(vorher, nachher):
        assert abs(a - b) < 0.01


def test_ausblendung_ist_stetig_beim_eintritt_eines_vierten():
    ps = []
    for d4 in np.linspace(400.0, 140.0, 80):
        laut = _laute([100.0, 110.0, 130.0, float(d4)])
        ps.append(sr.pegel_zuteilen(laut, [False] * 4)[3])
    assert max(abs(a - b) for a, b in zip(ps, ps[1:])) < 0.1


def test_mehrere_eigene_hoerer_bleiben_alle_ungedaempft():
    """Splitscreen: zwei eigene Autos."""
    laut = _laute([0.0, 0.0, 100.0, 120.0])
    pegel = sr.pegel_zuteilen(laut, [True, True, False, False])
    assert pegel[0] == laut[0] and pegel[1] == laut[1]


def test_rennklang_reicht_eigenen_pegel_ungedaempft_durch(monkeypatch):
    class Stimme:
        def __init__(self):
            self.werte = []
            self.stimme = True

        def aktualisieren(self, upm, l, r):
            self.werte.append((l, r))

        def beenden(self):
            pass

    stimmen = {}

    def _fuer(self, fz):
        return stimmen.setdefault(sr.kennung(fz), Stimme())

    monkeypatch.setattr(sr.Rennklang, "_stimme_fuer", _fuer)
    monkeypatch.setattr(sr, "_mixer_bereit", lambda: True)
    monkeypatch.setattr(sfx, "effekt_lautstaerke", lambda *a, **k: 1.0)

    def auto(x, i):
        body = types.SimpleNamespace(position=(x, 0.0), velocity=(0.0, 0.0))
        return types.SimpleNamespace(body=body, id=i, rpm=4000.0 + 100 * i,
                                     sender_slot=None)

    autos = [auto(0.0, 0)] + [auto(100.0 + 40 * i, i + 1) for i in range(5)]
    k = sr.Rennklang()
    k._aktiv = True
    k.aktualisieren(autos, [(0.0, 0.0)])
    eigen = stimmen[(None, 0)].werte[-1]
    assert max(eigen) == pytest.approx(1.0, abs=1e-6)


# ── Summe ohne Übersteuerung ────────────────────────────────────────────────

def test_weichbegrenzer_laesst_leises_unberuehrt_und_bleibt_unter_eins():
    x = np.linspace(-5.0, 5.0, 2001).astype(np.float32)
    y = tonmischer.weich_begrenzen(x)
    leise = np.abs(x) <= tonmischer.KNIE
    assert np.allclose(y[leise], x[leise])
    assert np.abs(y).max() <= 1.0
    assert np.all(np.diff(y) >= -1e-7), "nicht monoton"


def test_mischer_uebersteuert_nicht_bei_lauter_summe():
    m = tonmischer.Mischer(begrenzen=True)
    for _ in range(6):
        m.stimme_anlegen(lambda n: np.full(n, 0.9, np.float32), 1.0, 1.0)
    m.erzeugen()
    assert np.abs(m._ring).max() <= 1.0


# ── Unabhängigkeit der Stimmen ──────────────────────────────────────────────

def _korr(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def test_stimmen_starten_nicht_phasengleich():
    a = sfx.Motorstimme("6zyl", startphase_streuen=True)
    if not a:
        pytest.skip("keine Aufnahmen")
    b = sfx.Motorstimme("6zyl", startphase_streuen=True)
    assert a.phase != b.phase
    assert sfx.Motorstimme("6zyl").phase == 0.0     # Labor/Standard unveraendert


def test_startphasen_sind_verteilt_und_reihenfolgeunabhaengig(monkeypatch):
    """Feste Saat statt des globalen Zaehlers (sonst haengt der Test von der
    Reihenfolge der anderen Tests ab)."""
    if not sfx.Motorstimme("6zyl"):
        pytest.skip("keine Aufnahmen")
    monkeypatch.setattr(sfx, "_streuung_nr", 0)
    phasen = [sfx.Motorstimme("6zyl", startphase_streuen=True).phase
              for _ in range(8)]
    for i in range(8):
        for j in range(i + 1, 8):
            assert abs(phasen[i] - phasen[j]) > 0.25
    assert all(0.0 <= p < 64.0 for p in phasen)


def test_gleiche_drehzahl_ergibt_weniger_korrelierte_signale(monkeypatch):
    """Ohne Zyklusstreuung (reiner Effekt der Startphase) sind zwei Stimmen
    bei gleicher Drehzahl ohne Versatz identisch, mit Versatz im Mittel
    deutlich unkorreliert. Mittel ueber mehrere Paare mit fester Saat."""
    if not sfx.Motorstimme("6zyl"):
        pytest.skip("keine Aufnahmen")
    from src.core import motorklang
    werte = dict(motorklang.werte("6zyl"))
    werte["zyklusstreuung"] = 0.0

    def stimme(streuen):
        return sfx.Motorstimme("6zyl", werte=werte, startphase_streuen=streuen)

    def signal(s):
        return np.concatenate([s.block(5000.0, 4096) for _ in range(3)])

    monkeypatch.setattr(sfx, "_streuung_nr", 0)
    ohne = abs(_korr(signal(stimme(False)), signal(stimme(False))))
    mit = [abs(_korr(signal(stimme(True)), signal(stimme(True))))
           for _ in range(6)]
    assert ohne > 0.95
    assert float(np.mean(mit)) < 0.5


def test_pulkszenario_eigener_pegel_und_spitze():
    """Das Szenario der Meldung, offline gerendert."""
    rpms = [5000.0] + [4200.0 + 250.0 * i for i in range(5)]
    stimmen = [sfx.Motorstimme("6zyl", startphase_streuen=True) for _ in rpms]
    if not stimmen[0]:
        pytest.skip("keine Aufnahmen")
    laut = _laute([0.0, 100.0, 150.0, 200.0, 250.0, 300.0])
    pegel = sr.pegel_zuteilen(laut, [True] + [False] * 5)
    bloecke = [np.concatenate([s.block(r, 4096) for _ in range(10)])
               for s, r in zip(stimmen, rpms)]
    summe = sum(b * p for b, p in zip(bloecke, pegel))
    assert pegel[0] == laut[0]
    out = tonmischer.weich_begrenzen(summe.astype(np.float32))
    assert np.abs(out).max() <= 1.0
    # Der eigene Motor traegt in der Summe unveraendert bei
    rest = summe - bloecke[0] * pegel[0]
    assert np.sqrt(np.mean(rest ** 2)) < np.sqrt(np.mean((bloecke[0] * pegel[0]) ** 2))


# ── Abtastrate ──────────────────────────────────────────────────────────────

def test_raten_kandidaten_bevorzugen_aufnahmerate_dann_geraeterate():
    sd = types.SimpleNamespace(
        query_devices=lambda *a, **k: {"default_samplerate": 44100.0, "name": "x"})
    assert ta.raten_kandidaten(sd, 48000) == [48000, 44100]


def test_raten_kandidaten_ohne_abfrage_und_bei_gleicher_rate():
    def kaputt(*a, **k):
        raise RuntimeError("kein Geraet")
    assert ta.raten_kandidaten(types.SimpleNamespace(query_devices=kaputt),
                               48000) == [48000, 44100]
    gleich = types.SimpleNamespace(
        query_devices=lambda *a, **k: {"default_samplerate": 48000.0})
    assert ta.raten_kandidaten(gleich, 48000) == [48000, 44100]


def test_raten_kandidaten_bluetooth_16k_und_exotische_raten():
    sd = types.SimpleNamespace(
        query_devices=lambda *a, **k: {"default_samplerate": 16000.0})
    k = ta.raten_kandidaten(sd, 48000)
    assert k[0] == 48000 and 16000 in k
    sd = types.SimpleNamespace(
        query_devices=lambda *a, **k: {"default_samplerate": 96000.0})
    assert ta.raten_kandidaten(sd, 48000)[:2] == [48000, 96000]


@pytest.fixture
def geraet_44k(monkeypatch):
    """Ein Geraet, das nur 44,1 kHz annimmt (geteilter Modus, kein Umrechnen)."""
    modul = types.ModuleType("sounddevice")
    angefragt = []

    class Strom:
        def __init__(self, samplerate, callback):
            self.samplerate = samplerate
            self.callback = callback
            self.device = 0

        def start(self):
            pass

        def stop(self):
            pass

        def close(self):
            pass

    def OutputStream(*, samplerate, channels, dtype, blocksize, latency,
                     callback, **kw):
        angefragt.append(samplerate)
        if samplerate != 44100:
            raise RuntimeError("Invalid sample rate")
        return Strom(samplerate, callback)

    modul.OutputStream = OutputStream
    modul.query_devices = lambda *a, **k: {"name": "Attrappe",
                                            "default_samplerate": 44100.0}
    monkeypatch.setitem(sys.modules, "sounddevice", modul)
    ta.beenden()
    yield angefragt
    ta.beenden()


def test_geraet_nur_mit_44k_oeffnet_den_faden_statt_zurueckzufallen(geraet_44k):
    assert ta.starten() is True
    assert geraet_44k[0] == 48000 and geraet_44k[-1] == 44100
    z = ta.zustand()
    assert z["rate"] == 44100 and z["laeuft"]


def test_mischer_rechnet_auf_geraeterate_um():
    m = tonmischer.Mischer(kapazitaet=16384, vorrat=4096, stueck=1024,
                           quellrate=48000, ausgaberate=44100)
    t = {"i": 0}

    def sinus(n):
        i = np.arange(t["i"], t["i"] + n)
        t["i"] += n
        return (0.5 * np.sin(2 * np.pi * 1000.0 * i / 48000.0)).astype(np.float32)

    m.stimme_anlegen(sinus, 1.0, 1.0)
    for _ in range(12):
        m.erzeugen()
    daten = m.abrufen(m.fuellstand)[:, 0]
    assert len(daten) == pytest.approx(12 * 1024 * 44100 / 48000, abs=4)
    spek = np.abs(np.fft.rfft(daten * np.hanning(len(daten))))
    f = np.argmax(spek) * 44100.0 / len(daten)
    assert f == pytest.approx(1000.0, abs=15.0)
    # kein Knacken an den Stueckgrenzen
    assert np.abs(np.diff(daten)).max() < 2 * np.pi * 1000 / 44100 * 0.5 * 1.1


def _alias_energie(rate_aus, ton_hz, alias_hz):
    """Energie bei alias_hz nach Umrechnung 48k -> rate_aus eines Tons."""
    m = tonmischer.Mischer(kapazitaet=65536, vorrat=4096, stueck=1024,
                           quellrate=48000, ausgaberate=rate_aus)
    t = {"i": 0}

    def ton(n):
        i = np.arange(t["i"], t["i"] + n)
        t["i"] += n
        return (0.5 * np.sin(2 * np.pi * ton_hz * i / 48000.0)).astype(np.float32)

    m.stimme_anlegen(ton, 1.0, 1.0)
    for _ in range(30):
        m.erzeugen()
    x = m.abrufen(m.fuellstand)[200:, 0]
    spek = np.abs(np.fft.rfft(x * np.hanning(len(x)))) / len(x)
    k = int(round(alias_hz * len(x) / rate_aus))
    return float(spek[k - 3:k + 4].max())


def test_zehn_khz_ton_spiegelt_bei_16k_nicht_nach_6k():
    """10 kHz liegt ueber der Nyquist von 16 kHz (8 kHz) und wuerde ohne
    Tiefpass als 6 kHz hoerbar werden."""
    alias = _alias_energie(16000, 10000.0, 6000.0)
    referenz = _alias_energie(16000, 3000.0, 3000.0)     # Durchlass
    assert alias < 0.02 * referenz


def test_umrechnung_laesst_durchlassband_stehen():
    assert _alias_energie(16000, 2000.0, 2000.0) > 0.11


def test_umrechnung_ohne_tiefpass_bei_kleinem_verhaeltnis():
    m = tonmischer.Mischer(quellrate=48000, ausgaberate=44100)
    m.stimme_anlegen(lambda n: np.full(n, 0.25, np.float32), 1.0, 1.0)
    m.erzeugen()
    assert not hasattr(m, "_tp_rate")


def test_rate_wird_je_erzeugen_einmal_gelesen():
    """Wechselt die Rate mitten im Aufruf, rechnet dieser noch mit der alten."""
    m = tonmischer.Mischer(kapazitaet=16384, vorrat=4096, stueck=1024,
                           quellrate=48000, ausgaberate=44100)

    def quelle(n):
        m.ausgaberate_setzen(16000)       # Wechsel waehrend der Synthese
        return np.full(n, 0.25, np.float32)

    m.stimme_anlegen(quelle, 1.0, 1.0)
    n = m.erzeugen()
    assert n == pytest.approx(1024 * 44100 / 48000, abs=3)


def test_start_scheitert_nach_bau_der_strom_wird_geschlossen(monkeypatch):
    modul = types.ModuleType("sounddevice")
    stroeme = []

    class Strom:
        def __init__(self, rate):
            self.samplerate = rate
            self.geschlossen = False

        def start(self):
            if self.samplerate == 48000:
                raise RuntimeError("start fehlgeschlagen")

        def close(self):
            self.geschlossen = True

    def OutputStream(*, samplerate, **kw):
        s = Strom(samplerate)
        stroeme.append(s)
        return s

    modul.OutputStream = OutputStream
    modul.query_devices = lambda *a, **k: {"default_samplerate": 44100.0}
    s = ta._strom_oeffnen(modul, 48000, lambda *a: None)
    assert s.samplerate == 44100
    assert stroeme[0].geschlossen is True


def test_gleiche_rate_laeuft_unveraendert_durch():
    m = tonmischer.Mischer()
    m.stimme_anlegen(lambda n: np.full(n, 0.25, np.float32), 1.0, 1.0)
    assert m.erzeugen() == 1024
