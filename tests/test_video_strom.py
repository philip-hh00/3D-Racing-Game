"""Videofaden mit Attrappe: Takt, begrenzte Warteschlange, Aufraeumen.

Kein OpenCV und keine Datei noetig: ``VideoStrom`` nimmt eine
``cv2.VideoCapture``-aehnliche Attrappe (siehe ``oeffnen``). Die Ebene
(OpenGL) laesst sich hier nicht pruefen, die Rechnung dazu steht in
``test_fuellen_ansicht.py``.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from src.ui import video_ebene
from src.ui.video_ebene import VideoStrom


class Attrappe:
    """Liefert ``anzahl`` Bilder, deren erster Wert die Nummer ist; danach Ende."""

    def __init__(self, anzahl=5, fps=200.0, haengt: threading.Event | None = None):
        self.anzahl, self.fps = anzahl, fps
        self.i = 0
        self.freigegeben = False
        self.zuruecksetzer = 0
        self.haengt = haengt

    def get(self, prop):
        return self.fps if prop == video_ebene._PROP_FPS else 0.0

    def read(self):
        if self.haengt is not None:
            self.haengt.wait(5)
        if self.i >= self.anzahl:
            return False, None
        bild = np.full((4, 6, 3), self.i, dtype=np.uint8)
        self.i += 1
        return True, bild

    def set(self, prop, wert):
        if prop == video_ebene._PROP_POS:
            self.i = int(wert)
            self.zuruecksetzer += 1
        return True

    def release(self):
        self.freigegeben = True


def _warte(bedingung, sekunden=2.0):
    ende = time.perf_counter() + sekunden
    while time.perf_counter() < ende:
        if bedingung():
            return True
        time.sleep(0.002)
    return bedingung()


def _faeden():
    return [t for t in threading.enumerate() if t.name == "video-decode"]


def test_strom_liefert_bilder_im_takt_und_springt_am_ende_zurueck():
    cap = Attrappe(anzahl=3, fps=200.0)
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap)
    try:
        werte = []
        ende = time.perf_counter() + 2.0
        while len(werte) < 8 and time.perf_counter() < ende:
            b = strom.neuestes()
            if b is not None:
                werte.append(int(b[0, 0, 0]))
            time.sleep(0.001)
        assert len(werte) >= 8
        assert cap.zuruecksetzer >= 1                      # Schleife
        assert strom.groesse == (6, 4)
        assert strom.fps == 200.0
    finally:
        strom.close(warten=True)


def test_nichts_ist_vor_seiner_zeit_faellig():
    jetzt = [100.0]
    cap = Attrappe(anzahl=50, fps=10.0)
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap, uhr=lambda: jetzt[0], tiefe=4)
    try:
        assert _warte(lambda: strom.wartende >= 4)
        assert int(strom.neuestes()[0, 0, 0]) == 0         # Bild 0 ist sofort faellig
        assert strom.neuestes() is None                    # Bild 1 erst 0,1 s spaeter
        jetzt[0] += 0.1
        assert int(strom.neuestes()[0, 0, 0]) == 1
    finally:
        strom.close(warten=True)


def test_langsamer_abnehmer_ueberspringt_bilder_und_warteschlange_bleibt_begrenzt():
    jetzt = [0.0]
    cap = Attrappe(anzahl=1000, fps=30.0)
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap, uhr=lambda: jetzt[0], tiefe=3)
    try:
        assert _warte(lambda: strom.wartende == 3)
        time.sleep(0.05)
        assert strom.wartende == 3                         # Faden wartet, waechst nicht
        assert cap.i <= 5                                  # und liest nicht auf Vorrat
        jetzt[0] += 10.0                                   # Hauptfaden war lange weg
        b = strom.neuestes()
        assert int(b[0, 0, 0]) == 2                        # das neueste faellige zaehlt
        assert strom.uebersprungen == 2
    finally:
        strom.close(warten=True)


def test_hauptfaden_wartet_nie_auf_den_faden():
    haengt = threading.Event()                             # read blockiert
    strom = VideoStrom("x.mp4", oeffnen=lambda p: Attrappe(haengt=haengt))
    try:
        t0 = time.perf_counter()
        for _ in range(100):
            assert strom.neuestes() is None
        assert time.perf_counter() - t0 < 0.05
        t0 = time.perf_counter()
        strom.close()                                      # ohne Warten
        assert time.perf_counter() - t0 < 0.05
    finally:
        haengt.set()
        strom.close(warten=True)


def test_close_beendet_den_faden_und_gibt_die_aufnahme_frei():
    cap = Attrappe(anzahl=100)
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap)
    assert _warte(lambda: strom.wartende > 0)
    strom.close(warten=True)
    assert not strom.lebt
    assert cap.freigegeben
    assert strom.neuestes() is None


def test_unoeffenbare_datei_meldet_fehler_ohne_abzustuerzen():
    strom = VideoStrom("fehlt.mp4", oeffnen=lambda p: None)
    assert _warte(lambda: strom.fehler)
    assert _warte(lambda: not strom.lebt)
    assert strom.neuestes() is None


def test_ausnahme_im_faden_wird_zum_fehler_und_gibt_frei():
    class Kaputt(Attrappe):
        def read(self):
            raise RuntimeError("kaputt")

    cap = Kaputt()
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap)
    assert _warte(lambda: strom.fehler)
    assert _warte(lambda: cap.freigegeben)


def test_dauerhaft_lesefehler_werden_zum_fehler():
    cap = Attrappe(anzahl=0)                               # liefert nie ein Bild
    strom = VideoStrom("x.mp4", oeffnen=lambda p: cap)
    try:
        assert _warte(lambda: strom.fehler, sekunden=5.0)
    finally:
        strom.close(warten=True)


def test_videowechsel_haeuft_keine_faeden_oder_aufnahmen_an():
    vorher = len(_faeden())
    caps = []

    def oeffnen(p):
        c = Attrappe(anzahl=1000)
        caps.append(c)
        return c

    for _ in range(25):
        s = VideoStrom("x.mp4", oeffnen=oeffnen)
        _warte(lambda: s.wartende > 0, 0.5)
        s.close()                                          # wie _ensure_video: nie warten
    assert _warte(lambda: len(_faeden()) <= vorher, 3.0)
    assert _warte(lambda: all(c.freigegeben for c in caps), 3.0)


def test_alle_beenden_haelt_laufende_faeden_an():
    caps = [Attrappe(anzahl=1000) for _ in range(3)]
    stroeme = [VideoStrom("x.mp4", oeffnen=lambda p, c=c: c) for c in caps]
    assert _warte(lambda: all(s.wartende > 0 for s in stroeme))
    video_ebene.alle_beenden()
    assert all(not s.lebt for s in stroeme)
    assert all(c.freigegeben for c in caps)


@pytest.mark.skipif(not video_ebene._HAVE_CV2, reason="OpenCV fehlt")
def test_echte_datei_ueber_cv2(tmp_path):
    import cv2
    pfad = str(tmp_path / "t.mp4")
    w = cv2.VideoWriter(pfad, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (160, 90))
    for _ in range(6):
        w.write(np.full((90, 160, 3), (0, 0, 255), dtype=np.uint8))
    w.release()
    strom = VideoStrom(pfad)
    try:
        assert _warte(lambda: strom.groesse is not None)
        assert strom.groesse == (160, 90)
        bild = None
        ende = time.perf_counter() + 2.0
        while bild is None and time.perf_counter() < ende:
            bild = strom.neuestes()
        assert bild is not None and bild.shape == (90, 160, 3)
        assert bild[45, 80, 2] > 200 and bild[45, 80, 0] < 60     # BGR: rot im letzten Kanal
    finally:
        strom.close(warten=True)
