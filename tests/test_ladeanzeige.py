"""Ein Ladebildschirm vor dem Rennen, nicht zwei.

Gemeldet am 25.09.2026: „vor jedem Rennen gibt es 2 Ladebildschirme … es soll
auch nicht direkt sichtbar sein, was alles für GLBs geladen werden." Vorher
zeigte ``_szene_aufbauen`` einen eigenen Bildschirm mit Balken und Texten wie
„Umgebung forest/tanne_1", danach begann ``_build_racing_lines_optimized`` mit
einem zweiten Balken bei 0 %.
"""
from __future__ import annotations

import inspect

import pytest

from src.states.ladeanzeige import TEXTE, Ladeanzeige


class _Uhr:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _anzeige(abschnitte, uhr=None):
    bilder = []
    anzeige = Ladeanzeige(abschnitte, lambda stand, text: bilder.append((stand, text)),
                          uhr=uhr or _Uhr(), takt_s=0.0)
    return anzeige, bilder


def test_ein_balken_laeuft_ueber_alle_abschnitte_von_0_bis_100():
    anzeige, bilder = _anzeige([("strecke", 3.0), ("linien", 1.0)])
    anzeige.melden("strecke", 0.0)
    anzeige.melden("strecke", 1.0)
    anzeige.melden("linien", 0.0)
    anzeige.melden("linien", 0.5)
    anzeige.fertig()
    staende = [s for s, _ in bilder]
    assert staende[0] == pytest.approx(0.0)
    assert staende[1] == pytest.approx(0.75)
    # Der zweite Abschnitt beginnt, wo der erste aufgehört hat — nicht bei 0.
    assert staende[2] == pytest.approx(0.75)
    assert staende[3] == pytest.approx(0.875)
    assert staende[-1] == pytest.approx(1.0)


def test_der_balken_laeuft_nie_rueckwaerts():
    anzeige, bilder = _anzeige([("strecke", 1.0), ("linien", 1.0)])
    anzeige.melden("linien", 0.8)
    anzeige.melden("strecke", 0.2)
    assert bilder[-1][0] == pytest.approx(0.9)


def test_ein_leerer_abschnitt_kostet_keinen_platz():
    anzeige, bilder = _anzeige([("strecke", 1.0), ("ghost", 0.0), ("linien", 1.0)])
    anzeige.melden("strecke", 1.0)
    anzeige.melden("linien", 0.0)
    assert bilder[-1][0] == pytest.approx(0.5)


def test_gezeichnet_wird_hoechstens_im_takt():
    """Jede Meldung ein Bild hieße: mit V-Sync warten auf jeden Bildwechsel
    (siehe test_ghost_seed — 6871 Meldungen waren zwei Minuten)."""
    uhr = _Uhr()
    bilder = []
    anzeige = Ladeanzeige([("linien", 1.0)], lambda s, t: bilder.append(s),
                          uhr=uhr, takt_s=1 / 30)
    for i in range(1000):
        anzeige.melden("linien", i / 1000)
    assert len(bilder) == 1
    uhr.t = 1.0
    anzeige.melden("linien", 0.5)
    anzeige.fertig()
    assert len(bilder) == 3 and bilder[-1] == pytest.approx(1.0)


def test_die_texte_verraten_keine_dateien():
    anzeige, bilder = _anzeige([("strecke", 1.0), ("linien", 1.0)])
    anzeige.melden("strecke", 0.5)
    anzeige.melden("linien", 0.5)
    anzeige.melden("unbekannt", 0.5)
    for _stand, text in bilder:
        assert text in TEXTE.values()
        assert ".glb" not in text and "/" not in text


def test_das_rennen_zeigt_keinen_zweiten_ladebildschirm():
    from src.states.race_state import RaceState
    quelle = inspect.getsource(RaceState)
    assert "def _ladebild" not in quelle
    aufbau = inspect.getsource(RaceState._szene_aufbauen)
    assert "_lade_melden" in aufbau
    # Die Texte aus Rennszene.aufbauen() (Modellnamen) werden nicht gezeigt.
    assert "for anteil, _text in" in aufbau
