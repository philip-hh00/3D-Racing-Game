"""Der Ringpuffer zwischen Erzeugung und Ausgabe (06.08.2026).

Gemeldet: über Monitorlautsprecher **jede Sekunde** ein Aussetzer im Motorklang,
über Kopfhörer zwei je Runde. Regelmäßig heißt: zwei Uhren laufen gegeneinander
und ein Vorrat wird regelmäßig aufgebraucht. Der Vorrat war ein einziger Block,
nachgelegt einmal je **Bild** — der Ton hing damit am Bildtakt.

Dieses Modul ist der Ersatz: der Treiber ruft ab, wenn er Ton braucht, und
dazwischen liegt ein Ring mit Vorrat. Getestet wird hier **ohne Gerät**, und
genau dafür ist die Trennung gemacht — der heikle Teil ist der Ring, nicht die
Soundkarte, und der ist so vollständig nachstellbar.

Vier Dinge müssen stimmen, und jedes davon war schon einmal ein Fehler in diesem
Spiel:

1. Was hineingeht, kommt heraus — in derselben Reihenfolge, ohne Loch.
2. Ein Unterlauf **knackt nicht**. Der Sprung auf null ist genau das Geräusch,
   gegen das der ganze Umbau gemacht ist.
3. Lautstärkeänderungen sind Verläufe, keine Sprünge.
4. Der Abruf aus dem Audiofaden rechnet nichts und wartet auf nichts.
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import tonmischer as tm  # noqa: E402


def _zaehler(start: float = 1.0):
    """Erzeuger, der fortlaufend hochzählt — so ist jede Lücke sichtbar."""
    stand = {"n": start}

    def erzeugen(laenge: int) -> np.ndarray:
        aus = np.arange(stand["n"], stand["n"] + laenge, dtype=np.float32)
        stand["n"] += laenge
        return aus

    return erzeugen


def _fest(wert: float):
    return lambda laenge: np.full(laenge, wert, dtype=np.float32)


# ── Durchreichen ─────────────────────────────────────────────────────────────

def test_was_hineingeht_kommt_heraus():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_zaehler(), 1.0, 1.0)
    m.erzeugen()
    aus = m.abrufen(128)
    assert np.allclose(aus[:, 0], np.arange(1, 129))
    assert np.allclose(aus[:, 0], aus[:, 1]), "beide Kanaele gleich bei Mitte"


def test_der_ring_laeuft_ueber_die_naht_hinweg():
    """Der Fehler, den ein Ringpuffer immer hat, wenn er ihn hat: an der Stelle,
    wo der Schreibzeiger von hinten nach vorn springt."""
    m = tm.Mischer(kapazitaet=256, vorrat=128, stueck=64)
    m.stimme_anlegen(_zaehler(), 1.0, 1.0)
    erwartet = 1
    for _ in range(20):                 # mehrfach ueber die Naht
        m.erzeugen()
        aus = m.abrufen(64)
        assert np.allclose(aus[:, 0], np.arange(erwartet, erwartet + 64)), \
            f"Bruch ab {erwartet}"
        erwartet += 64


def test_teilweiser_abruf_verliert_nichts():
    """Der Treiber ruft in seiner eigenen Stückelung ab, nicht in unserer."""
    m = tm.Mischer(kapazitaet=1024, vorrat=512, stueck=128)
    m.stimme_anlegen(_zaehler(), 1.0, 1.0)
    for _ in range(4):
        m.erzeugen()
    teile = [m.abrufen(n) for n in (50, 7, 200, 255)]
    zusammen = np.concatenate([t[:, 0] for t in teile])
    assert np.allclose(zusammen, np.arange(1, 513))
    assert m.unterlaeufe == 0


def test_der_ring_nimmt_nicht_mehr_als_er_fasst():
    m = tm.Mischer(kapazitaet=256, vorrat=128, stueck=128)
    m.stimme_anlegen(_fest(0.5), 1.0, 1.0)
    assert m.erzeugen() == 128
    assert m.erzeugen() == 128
    assert m.erzeugen() == 0, "der Ring war voll und haette nichts nehmen duerfen"
    assert m.fuellstand == 256


# ── Unterlauf ────────────────────────────────────────────────────────────────

def test_ein_unterlauf_wird_gezaehlt():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_fest(0.5), 1.0, 1.0)
    m.erzeugen()
    m.abrufen(128)
    assert m.unterlaeufe == 0
    m.abrufen(128)                      # nichts mehr da
    assert m.unterlaeufe == 1


def test_ein_unterlauf_knackt_nicht():
    """Der Kern der Sache. Ein Sprung von 0,5 auf 0 ist das Knacken, das über
    Monitorlautsprecher jede Sekunde zu hören war."""
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_fest(0.5), 1.0, 1.0)
    m.erzeugen()
    m.abrufen(128)                      # endet auf 0,5
    aus = m.abrufen(128)                # komplett Unterlauf
    spruenge = np.abs(np.diff(np.concatenate([[0.5], aus[:, 0]])))
    assert float(spruenge.max()) < 0.02, \
        f"groesster Sprung {spruenge.max():.4f} — das knackt"
    assert abs(float(aus[-1, 0])) < 1e-6, "am Ende muss es still sein"


def test_nach_einem_unterlauf_geht_es_ohne_verlust_weiter():
    """Ein Loch darf nicht auch noch Daten verschlucken."""
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_zaehler(), 1.0, 1.0)
    m.erzeugen()
    m.abrufen(128)
    m.abrufen(64)                       # Unterlauf
    m.erzeugen()
    aus = m.abrufen(128)
    assert np.allclose(aus[:, 0], np.arange(129, 257)), \
        "nach dem Unterlauf fehlt etwas"


def test_ohne_vorgeschichte_ist_der_unterlauf_still():
    """Beim allerersten Abruf gibt es keinen letzten Wert zum Auslaufen."""
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    aus = m.abrufen(64)
    assert not np.any(aus)


# ── Lautstärke ───────────────────────────────────────────────────────────────

def test_lautstaerke_wird_ueberblendet_statt_gesprungen():
    """Sechs Fahrzeuge aendern staendig ihre Lautstaerke. Jede davon als Sprung
    waere ein eigenes kleines Knacken."""
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    stimme = m.stimme_anlegen(_fest(1.0), 0.0, 0.0)
    stimme.einstellen(1.0, 1.0)
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[0, 0] < 0.05, "der Verlauf muss bei 0 beginnen"
    assert aus[-1, 0] > 0.95, "und das Ziel erreichen"
    assert float(np.abs(np.diff(aus[:, 0])).max()) < 0.02


def test_panorama_trennt_die_seiten():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_fest(1.0), 1.0, 0.25)
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[-1, 0] == pytest.approx(1.0, abs=0.02)
    assert aus[-1, 1] == pytest.approx(0.25, abs=0.02)


def test_stumme_stimmen_kosten_keine_synthese():
    """Bei sechs Fahrzeugen sind meist die Haelfte ausser Hoerweite."""
    gerufen = {"n": 0}

    def erzeugen(laenge):
        gerufen["n"] += 1
        return np.zeros(laenge, dtype=np.float32)

    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(erzeugen, 0.0, 0.0)
    m.erzeugen()
    assert gerufen["n"] == 0


def test_mehrere_stimmen_werden_summiert():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    for _ in range(3):
        m.stimme_anlegen(_fest(0.2), 1.0, 1.0)
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[-1, 0] == pytest.approx(0.6, abs=0.02)


# ── Stimmen abräumen ─────────────────────────────────────────────────────────

def test_eine_beendete_stimme_blendet_aus_und_verschwindet():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    stimme = m.stimme_anlegen(_fest(1.0), 1.0, 1.0)
    m.erzeugen()
    m.abrufen(128)
    stimme.beenden()
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[0, 0] > 0.9, "sie muss ausblenden, nicht abbrechen"
    assert abs(float(aus[-1, 0])) < 0.02
    assert float(np.abs(np.diff(aus[:, 0])).max()) < 0.02
    m.erzeugen()
    assert m.stimmen == 0, "danach gehoert sie abgeraeumt"


def test_eine_kaputte_quelle_reisst_den_ton_nicht_mit():
    """Ein Fehler in einer Stimme darf nicht das ganze Rennen verstummen
    lassen — und schon gar nicht den Audiofaden treffen."""
    def kaputt(laenge):
        raise RuntimeError("absichtlich")

    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(kaputt, 1.0, 1.0)
    m.stimme_anlegen(_fest(0.4), 1.0, 1.0)
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[-1, 0] == pytest.approx(0.4, abs=0.02), "die gesunde muss klingen"


def test_eine_quelle_mit_falscher_laenge_wird_uebergangen():
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(lambda n: np.zeros(n // 2, dtype=np.float32), 1.0, 1.0)
    m.stimme_anlegen(_fest(0.3), 1.0, 1.0)
    m.erzeugen()
    aus = m.abrufen(128)
    assert aus[-1, 0] == pytest.approx(0.3, abs=0.02)


# ── Die Regeln, auf denen alles steht ────────────────────────────────────────

def test_der_abruf_nimmt_keine_sperre():
    """Die wichtigste Regel: was im Audiofaden haengt, hoert man sofort.

    Geprüft, indem die Sperre des Mischers **gehalten** wird, während abgerufen
    wird. Braucht ``abrufen`` sie, steht der Test.
    """
    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(_fest(0.5), 1.0, 1.0)
    m.erzeugen()
    fertig = threading.Event()

    def abrufen():
        m.abrufen(64)
        fertig.set()

    with m._schloss:
        threading.Thread(target=abrufen, daemon=True).start()
        assert fertig.wait(2.0), "abrufen() haengt an der Sperre des Mischers"


def test_der_abruf_ruft_keine_synthese():
    """Synthese im Audiofaden ist der zweite Weg, ihn zum Haengen zu bringen."""
    gerufen = {"n": 0}

    def erzeugen(laenge):
        gerufen["n"] += 1
        return np.zeros(laenge, dtype=np.float32)

    m = tm.Mischer(kapazitaet=512, vorrat=256, stueck=128)
    m.stimme_anlegen(erzeugen, 1.0, 1.0)
    m.erzeugen()
    vorher = gerufen["n"]
    m.abrufen(128)
    m.abrufen(128)                      # auch der Unterlauf darf nichts rufen
    assert gerufen["n"] == vorher


def test_der_vorrat_ist_ein_abwaegen_und_steht_dokumentiert():
    """Zu wenig reisst Loecher, zu viel laesst den Motor hinter dem Gaspedal
    herhinken. Der Vorgabewert muss in dem Bereich liegen, der beides traegt."""
    m = tm.Mischer()
    sr = 48000
    ms = 1000.0 * m.vorrat / sr
    assert 40.0 <= ms <= 150.0, f"Vorrat {ms:.0f} ms liegt ausserhalb"
    assert m.kapazitaet > m.vorrat, "ohne Luft ueber dem Vorrat stockt der Erzeuger"


def test_ein_ungueltiger_vorrat_wird_abgewiesen():
    with pytest.raises(ValueError):
        tm.Mischer(kapazitaet=256, vorrat=256)
    with pytest.raises(ValueError):
        tm.Mischer(kapazitaet=256, vorrat=0)


# ── Zusammenspiel unter Last ─────────────────────────────────────────────────

def test_erzeuger_und_audiofaden_gleichzeitig():
    """Der eigentliche Betriebsfall, und der einzige Ort, an dem ein Fehler im
    Ring ohne Sperre auffallen wuerde."""
    m = tm.Mischer(kapazitaet=4096, vorrat=2048, stueck=512)
    m.stimme_anlegen(_zaehler(), 1.0, 1.0)
    gelesen: list[np.ndarray] = []
    halt = threading.Event()

    import time

    def erzeuger():
        while not halt.is_set():
            if m.braucht_nachschub():
                m.erzeugen()
            else:
                time.sleep(0.001)

    faden = threading.Thread(target=erzeuger, daemon=True)
    faden.start()
    try:
        for _ in range(100):
            # Getaktet abrufen, wie ein Treiber es tut. Ohne die Pause liest
            # dieser Faden in einer engen Schleife, haelt dabei den GIL und
            # laesst den Erzeuger verhungern — dann unterlaeuft alles, und der
            # Test prueft nichts mehr.
            time.sleep(0.002)
            # Nur unversehrte Abrufe vergleichen. Bei einem Unterlauf hängt das
            # Auslaufen künstliche, absteigende Werte an — die sind vom Zähler
            # nicht zu unterscheiden und würden wie ein Datenfehler aussehen.
            # Weggelassene Stücke schaden nichts: ein Unterlauf **verschluckt**
            # nichts, er verzögert nur, deshalb bleibt der Rest lückenlos.
            vorher = m.unterlaeufe
            stueck = m.abrufen(256)[:, 0].copy()
            if m.unterlaeufe == vorher:
                gelesen.append(stueck)
    finally:
        halt.set()
        faden.join(2.0)

    assert gelesen, "kein einziger unversehrter Abruf — der Erzeuger lief nicht"
    zusammen = np.concatenate(gelesen)
    assert np.all(np.diff(zusammen) > 0), \
        "die Reihenfolge ist durcheinandergeraten oder etwas kam doppelt"
