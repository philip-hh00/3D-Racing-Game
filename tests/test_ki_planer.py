"""Planer: wählt aus Kandidatenbahnen — Ideallinie, Ausweichen, Überholen, Folgen."""
from __future__ import annotations

import math

import numpy as np
import pytest

import ki_hilfe as H  # noqa: F401
from src.ai.fahrplan import Fahrplan
from src.ai.planer import Gegner, Planer, Wunsch
from src.ai.strecke_frenet import StreckeFrenet

R = 5000.0      # fast gerade
BREITE, LAENGE = 29.0, 62.0


def _plan(v=600.0, v_einbruch_bei=None, breite=40, mit_kurve=False):
    n = 1500
    mitte = [(R * math.cos(2 * math.pi * i / n), R * math.sin(2 * math.pi * i / n)) for i in range(n)]
    st = StreckeFrenet(mitte, 300.0)
    v_ziel = np.full(n, v)
    if v_einbruch_bei is not None:
        i0 = st.index(v_einbruch_bei)
        v_ziel[i0:i0 + breite] = 200.0
    v_kurve = v_ziel.copy() if mit_kurve else None
    return Fahrplan(st, np.zeros(n), v_ziel, np.full(n, 1.0 / R), 150.0 - 15.0 - 6.0, 800.0,
                    v_kurve=v_kurve)


def test_frei_bleibt_auf_der_ideallinie():
    plan = _plan()
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 600.0, [], Wunsch())
    assert abs(bahn.d[-1]) < 5.0
    assert bahn.v_soll == pytest.approx(600.0, rel=0.02)
    assert bahn.xy.shape == (len(bahn.s), 2)


def test_weicht_einem_stehenden_auto_aus():
    plan = _plan()
    g = Gegner(s=500.0, d=0.0, v=0.0, laenge=LAENGE, breite=BREITE)
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 500.0, [g], Wunsch())
    naehe = np.abs(bahn.s - g.s) < LAENGE
    assert naehe.any()
    assert np.all(np.abs(bahn.d[naehe] - g.d) >= BREITE)


def test_folgt_ohne_ausscheren():
    plan = _plan()
    g = Gegner(s=220.0, d=0.0, v=400.0, laenge=LAENGE, breite=BREITE)
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 600.0, [g], Wunsch(darf_ausscheren=False))
    assert bahn.gefolgt
    assert bahn.v_soll < 480.0
    assert abs(bahn.d[-1]) < 0.25 * plan.halb_frei


def test_ueberholt_wenn_es_darf():
    plan = _plan()
    g = Gegner(s=220.0, d=0.0, v=400.0, laenge=LAENGE, breite=BREITE)
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 600.0, [g], Wunsch())
    assert abs(bahn.d[-1]) > 0.35 * plan.halb_frei


def test_bleibt_zwischen_den_waenden():
    plan = _plan()
    gegner = [Gegner(s=300.0, d=d, v=0.0, laenge=LAENGE, breite=BREITE) for d in (-80.0, 0.0, 80.0)]
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 400.0, gegner, Wunsch())
    assert np.all(np.abs(bahn.d) <= plan.halb_frei + 1e-6)


def test_bremst_vor_einem_langsamen_abschnitt():
    plan = _plan(v_einbruch_bei=250.0)
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 600.0, [], Wunsch())
    assert bahn.v_soll < 560.0


def test_seitenwunsch_wird_befolgt():
    plan = _plan()
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, 600.0, [],
                                                Wunsch(seite=80.0, gewicht_seite=1.0))
    assert bahn.d[-1] > 40.0


def test_wunsch_haelt_wandreserve():
    # Ein Seitenwunsch bis an den Rand darf das Auto nicht bis auf die 6 px von
    # ``halb_frei`` an die Wand bringen: schräg stehend ragt die Ecke darüber hinaus.
    plan = _plan()
    hf = plan.halb_frei
    bahn = Planer(plan, BREITE, LAENGE).planen(
        100.0, 0.0, 300.0, [], Wunsch(seite=hf, gewicht_seite=50.0))
    assert np.max(np.abs(bahn.d)) <= hf - 10.0


def test_kurzer_seitenwechsel_ist_fahrbar():
    # Selbst wenn nur der kurze Übergang zur Wahl steht, darf der starke Seitenwunsch
    # nicht mehr Seitenbeschleunigung verlangen, als das Auto hat (sonst bricht es
    # aus und dreht sich).
    class NurKurz(Planer):
        UEBERGANG = (0.45,)

    plan = _plan()
    v = 270.0
    bahn = NurKurz(plan, BREITE, LAENGE).planen(
        100.0, -42.0, v, [], Wunsch(seite=85.0, gewicht_seite=10.0))
    ds = np.diff(bahn.s)
    steigung = np.diff(bahn.d) / ds
    a_quer = np.abs(np.diff(steigung) / ds[1:]) * v * v
    assert a_quer.max() <= 1.3 * plan.a_quer


@pytest.mark.parametrize("v0", (400.0, 450.0, 500.0))
@pytest.mark.parametrize("abstand", (100.0, 125.0, 150.0))
def test_stehendes_auto_voraus_nie_mit_vollem_tempo_durch(v0, abstand):
    # Ein stehendes Auto 100-150 px voraus in der eigenen Spur: die Bahn weicht mit
    # Seitenabstand aus ODER das Sollziel reicht zum Anhalten davor. Nie geradeaus
    # mit Profiltempo hindurch (auch mit der Begrenzung der Seitenbeschleunigung).
    plan = _plan()
    g = Gegner(s=100.0 + abstand, d=0.0, v=0.0, laenge=LAENGE, breite=BREITE)
    bahn = Planer(plan, BREITE, LAENGE).planen(100.0, 0.0, v0, [g], Wunsch())
    naehe = np.abs(bahn.s - g.s) < LAENGE
    if naehe.any():
        weicht_aus = np.all(np.abs(bahn.d[naehe] - g.d) >= BREITE)
    else:
        weicht_aus = False
    frei = max(0.0, abstand - LAENGE)
    bremst_genug = bahn.v_soll ** 2 <= 2.0 * plan.a_brems * frei + 30.0 ** 2
    assert weicht_aus or bremst_genug, (bahn.v_soll, bahn.d[naehe], abstand)


def test_spaeter_bremsen_verschiebt_nur_die_bremsflanke():
    # Ein Tempoeinbruch voraus: wer später bremst, darf davor schneller sein.
    plan = _plan(v_einbruch_bei=250.0)
    p = Planer(plan, BREITE, LAENGE)
    spaet = p.planen(100.0, 0.0, 600.0, [], Wunsch(spaeter_bremsen_px=60.0)).v_soll
    normal = p.planen(100.0, 0.0, 600.0, [], Wunsch()).v_soll
    frueh = p.planen(100.0, 0.0, 600.0, [], Wunsch(spaeter_bremsen_px=-60.0)).v_soll
    assert spaet > normal > frueh


def test_spaeter_bremsen_loescht_keine_enge_kurve():
    # Ein Tempoeinbruch (Spitzkehre), schmaler als die Verschiebung: der Scheitel
    # darf nicht weggefüllt werden — das Kurventempo bleibt Obergrenze.
    plan = _plan(v_einbruch_bei=250.0, breite=4, mit_kurve=True)
    i0 = plan.strecke.index(250.0)
    s_scheitel = plan.strecke.s[i0 + 2]
    s0 = float(plan.strecke.s[i0]) - 60.0
    p = Planer(plan, BREITE, LAENGE)
    normal = p.planen(s0, 0.0, 120.0, [], Wunsch()).v_soll
    spaet = p.planen(s0, 0.0, 120.0, [], Wunsch(spaeter_bremsen_px=120.0)).v_soll
    assert s_scheitel > s0
    assert spaet <= normal + 1.0
    assert spaet < 450.0


def test_bremsverschiebung_ist_begrenzt():
    plan = _plan(v_einbruch_bei=250.0)
    p = Planer(plan, BREITE, LAENGE)
    a = p.planen(100.0, 0.0, 600.0, [], Wunsch(spaeter_bremsen_px=Planer.BREMS_SHIFT_MAX)).v_soll
    b = p.planen(100.0, 0.0, 600.0, [], Wunsch(spaeter_bremsen_px=Planer.BREMS_SHIFT_MAX + 200.0)).v_soll
    assert a == b
