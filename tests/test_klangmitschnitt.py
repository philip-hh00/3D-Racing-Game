"""Der Mitschnitt, mit dem die Störgeräusche eingekreist werden (05.08.2026).

Gemeldet und ungeklärt: „ca. 2 mal pro Runde" ein Störgeräusch. Drei Verdachte
sind ausgemessen und ausgeschlossen (Blockgrenzen, Lautstärkestufen,
Kanaldiebstahl) — bleibt der Weg **nach** unserer Rechnung, und der hängt am
Rechner des Spielers.

Der Mitschnitt zählt deshalb genau eine Zahl, auf die es ankommt: wie oft eine
Motorstimme beim Nachlegen einen **stehenden** Kanal vorgefunden hat. Das ist
eine Lücke im Ton. Stimmt sie mit der Zahl der gehörten Störungen überein, sind
es Lücken; ist sie null, liefert das Spiel sauber ab.

Geprüft wird hier, dass diese Zählung stimmt und dass ein nicht laufender
Mitschnitt nichts kostet — er soll ein Werkzeug auf Zeit sein und nicht das
Rennen belasten, das er vermessen soll.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.core import klangmitschnitt as km  # noqa: E402


@pytest.fixture(autouse=True)
def sauber(monkeypatch, tmp_path):
    from src.core import paths
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path)
    if km.laeuft():
        km.beenden()
    yield tmp_path
    if km.laeuft():
        km.beenden()


def _block(n: int = 64) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def test_ohne_start_wird_nichts_gezaehlt():
    """Der ausgeschaltete Zustand muss folgenlos sein — sonst sammelt das
    Werkzeug im normalen Rennen Speicher an."""
    assert km.laeuft() is False
    km.block_gemerkt(_block(), True)
    km.bild(0.016)
    assert km.beenden() is None


def test_ein_aussetzer_wird_gezaehlt(sauber):
    km.starten()
    km.block_gemerkt(_block(), False)
    km.block_gemerkt(_block(), True)     # der Kanal stand
    km.block_gemerkt(_block(), False)
    km.bild(0.016)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    assert bericht["aussetzer"] == 1
    assert bericht["bloecke_nachgelegt"] == 3


def test_ohne_aussetzer_steht_dort_null(sauber):
    """Der aussagekräftigste Fall: sauber geliefert, trotzdem Störungen gehört
    heißt, dass es nicht am Spiel liegt."""
    km.starten()
    for _ in range(20):
        km.block_gemerkt(_block(), False)
    km.bild(0.016)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    assert bericht["aussetzer"] == 0


def test_der_bericht_nennt_die_frist_und_die_bilder_darueber(sauber):
    """Ohne die Frist ist eine Bildzeit nur eine Zahl. Sie sagt erst etwas,
    wenn danebensteht, wie lange das Nachlegen Zeit hatte."""
    km.starten()
    km.bild(0.016)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    from src.core import sfx
    assert bericht["frist_ms"] == pytest.approx(1000.0 * sfx.BLOCK / sfx.SR, abs=0.01)
    assert "bilder_ueber_frist" in bericht
    assert bericht["blocklaenge"] == sfx.BLOCK


def test_der_bericht_nennt_den_audiofaden(sauber):
    """Seit dem Umbau am 06.08.2026 die entscheidende Zeile: welcher Weg lief.

    Ohne sie wäre bei einer Meldung nicht zu unterscheiden, ob der Audiofaden
    lief und trotzdem gestört hat, oder ob er gar nicht erst zustande kam und
    der alte Weg schuld ist — zwei völlig verschiedene Ursachen.
    """
    km.starten()
    km.bild(0.016)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    faden = bericht["audiofaden"]
    assert "laeuft" in faden
    if not faden["laeuft"]:
        assert faden.get("grund"), "ein Fehlschlag ohne Begruendung hilft niemandem"
    else:
        assert faden["rate"] > 0
        assert "unterlaeufe" in faden


def test_der_mitschnitt_legt_ton_und_bericht_ab(sauber):
    km.starten()
    for _ in range(5):
        km.block_gemerkt(np.full(128, 0.2, dtype=np.float32), False)
    km.bild(0.016)
    pfad = km.beenden()
    assert pfad.endswith(".json")
    assert os.path.isfile(pfad)
    assert os.path.isfile(pfad[:-5] + ".wav"), "ohne Ton ist der Bericht halb"


def test_ein_zweiter_start_beginnt_bei_null(sauber):
    km.starten()
    km.block_gemerkt(_block(), True)
    km.beenden()
    km.starten()
    km.bild(0.016)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    assert bericht["aussetzer"] == 0, "der alte Stand wurde mitgeschleppt"


def test_der_mitschnitt_waechst_nicht_unbegrenzt(sauber):
    """Ein vergessener Mitschnitt darf den Speicher nicht auffressen."""
    km.starten()
    for _ in range(4200):
        km.block_gemerkt(_block(8), False)
    bericht = json.loads(open(km.beenden(), encoding="utf-8").read())
    assert bericht["bloecke_nachgelegt"] == 4200      # gezaehlt wird alles
    assert len(km._stuecke) <= 4000                   # aufgehoben nicht


def test_die_rennschleife_ruft_den_mitschnitt_nur_wenn_er_laeuft():
    """Sonst kostet das Werkzeug in jedem Rennen Rechenzeit."""
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState.update)
    assert "klangmitschnitt.laeuft()" in quelle


def test_f9_schaltet_um():
    import inspect
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState.handle_events)
    assert "pygame.K_F9" in quelle
    assert "_mitschnitt_umschalten" in quelle
