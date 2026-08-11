"""Klangwerte je Motortyp und die Klang-Seite im Labor (Releaseplan C8).

Zwei Dinge werden hier festgehalten:

1. **Die Vorgabe ändert nichts.** Das Modul einzuführen darf den Klang nicht
   verstellen — abgestimmt wird bewusst, nicht durch ein Update. Alle Vorgaben
   sind deshalb das bisherige Verhalten.
2. **Die zwei Ebenen bleiben getrennt.** Was für eine Motorbauart gilt, landet
   in ``data/audio/motor_klang.json``; die zwei Werte eines einzelnen
   Fahrzeugs bleiben in dessen Fahrzeug-JSON.

Geschrieben wird in Tests **niemals** in die echten Dateien: ``_DATEI`` zeigt
auf ein Verzeichnis von pytest, und der Cache wird vor jedem Test geleert.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import motorklang, sfx  # noqa: E402


@pytest.fixture(autouse=True)
def sauber(monkeypatch, tmp_path):
    """Kein Test fasst die echte Klangdatei an."""
    ziel = tmp_path / "motor_klang.json"
    monkeypatch.setattr(motorklang, "_DATEI", str(ziel))
    monkeypatch.setattr(motorklang, "_pfad", lambda: str(ziel))
    motorklang.neu_laden()
    yield ziel
    motorklang.neu_laden()


# ---------------------------------------------------------------------------
# Vorgaben und Grenzen
# ---------------------------------------------------------------------------
def test_ohne_datei_gelten_die_vorgaben():
    assert motorklang.werte("8zyl") == pytest.approx(motorklang.VORGABE)


def test_vorgabe_ist_das_bisherige_verhalten():
    """Sonst klingt das Spiel nach dem Update anders, ohne dass jemand etwas
    abgestimmt hätte."""
    v = motorklang.VORGABE
    assert v["schichtblende"] == sfx.BLENDE
    assert v["blocklaenge"] == sfx.BLOCK
    assert v["grundpegel"] == 1.0
    assert v["hochpass_hz"] == 0.0, "Hochpass aus"
    assert v["begrenzer_schwelle"] == 1.0, "Begrenzer aus"
    assert v["drehzahlglaettung"] == 0.0, "Drehzahl folgt sofort"


def test_jeder_wert_hat_grenzen():
    assert set(motorklang.GRENZEN) == set(motorklang.VORGABE)
    for k, (lo, hi, schritt, dez) in motorklang.GRENZEN.items():
        assert lo <= motorklang.VORGABE[k] <= hi, k
        assert schritt > 0 and dez >= 0, k


@pytest.mark.parametrize("muell", ["viel", None, [], {}, float("nan"),
                                   float("inf"), -1e9, 1e9])
def test_muell_in_der_datei_ergibt_einen_gueltigen_wert(sauber, muell):
    """Die Datei ist von Hand editierbar. Ein Tippfehler darf keinen stummen
    oder übersteuerten Motor ergeben."""
    sauber.write_text(json.dumps({"motoren": {"8zyl": {"grundpegel": muell}}}),
                      encoding="utf-8")
    motorklang.neu_laden()
    lo, hi, _s, _d = motorklang.GRENZEN["grundpegel"]
    assert lo <= motorklang.werte("8zyl")["grundpegel"] <= hi


def test_kaputte_datei_wirft_nicht(sauber):
    sauber.write_text("{kein json", encoding="utf-8")
    motorklang.neu_laden()
    assert motorklang.werte("8zyl") == pytest.approx(motorklang.VORGABE)


def test_setzen_begrenzt_sofort():
    assert motorklang.setzen("8zyl", "begrenzer_schwelle", 5.0) == 1.0
    assert motorklang.setzen("8zyl", "begrenzer_schwelle", -3.0) == 0.1


def test_speichern_und_wieder_lesen(sauber):
    motorklang.setzen("8zyl", "hochpass_hz", 40.0)
    motorklang.setzen("6zyl", "grundpegel", 0.8)
    motorklang.global_setzen("puffer", 1024.0)
    pfad = motorklang.speichern()
    assert os.path.isfile(pfad)
    motorklang.neu_laden()
    assert motorklang.werte("8zyl")["hochpass_hz"] == pytest.approx(40.0)
    assert motorklang.werte("6zyl")["grundpegel"] == pytest.approx(0.8)
    assert motorklang.puffer() == 1024


def test_auf_vorgabe_trifft_nur_einen_motor():
    motorklang.setzen("8zyl", "hochpass_hz", 40.0)
    motorklang.setzen("6zyl", "hochpass_hz", 60.0)
    motorklang.auf_vorgabe("8zyl")
    assert motorklang.werte("8zyl")["hochpass_hz"] == 0.0
    assert motorklang.werte("6zyl")["hochpass_hz"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Was die Werte im Klang bewirken
# ---------------------------------------------------------------------------
def _stimme(**abweichung) -> sfx.Motorstimme:
    w = dict(motorklang.VORGABE)
    w.update(abweichung)
    return sfx.Motorstimme("8zyl", 1.0, 0.0, w)


def test_grundpegel_skaliert_den_klang():
    if not sfx.schichten("8zyl"):
        pytest.skip("keine Aufnahmen vorhanden")
    laut = lambda s: float(np.sqrt(np.mean(np.square(
        np.concatenate([s.block(3200.0) for _ in range(3)])))))
    assert laut(_stimme(grundpegel=0.5)) < laut(_stimme(grundpegel=1.0)) * 0.6


def test_blocklaenge_bestimmt_die_blockgroesse():
    for laenge in (512, 1024, 4096):
        assert len(_stimme(blocklaenge=laenge).block(3200.0)) == laenge


def test_schmale_blende_laesst_nur_eine_schicht_klingen():
    """Genau der Zweck des Reglers: zu schmal springen die Wechsel, zu breit
    schwebt es."""
    sch = sfx.schichten("8zyl")
    if not sch:
        pytest.skip("keine Aufnahmen vorhanden")
    mitte = (sch.drehzahlen[2] + sch.drehzahlen[3]) / 2.0
    knapp_davor = mitte - (sch.drehzahlen[3] - sch.drehzahlen[2]) * 0.2
    eng = [g for g in sch.gewichte(knapp_davor, 0.0) if g > 0.001]
    weit = [g for g in sch.gewichte(knapp_davor, 1.0) if g > 0.001]
    assert len(eng) == 1
    assert len(weit) == 2


def test_hochpass_nimmt_den_gleichanteil_weg():
    hp = sfx.Hochpass(60.0)
    x = np.full(2048, 0.4, dtype=np.float32)
    letzter = np.concatenate([hp(x) for _ in range(8)])[-1]
    assert abs(float(letzter)) < 0.01


def test_hochpass_aus_laesst_alles_durch():
    x = np.full(256, 0.4, dtype=np.float32)
    assert np.array_equal(sfx.Hochpass(0.0)(x), x)


@pytest.mark.parametrize("schwelle", [0.3, 0.5, 0.85])
def test_begrenzer_haelt_die_schwelle_ein(schwelle):
    bg = sfx.Begrenzer(schwelle, 12.0)
    laut = (np.sin(np.linspace(0, 400, 4096)) * 0.95).astype(np.float32)
    assert float(np.abs(bg(laut)).max()) <= schwelle + 1e-6


def test_begrenzer_aus_laesst_alles_durch():
    x = (np.sin(np.linspace(0, 40, 512)) * 0.95).astype(np.float32)
    assert np.array_equal(sfx.Begrenzer(1.0, 12.0)(x), x)


def test_begrenzer_greift_sofort_nicht_erst_spaeter():
    """Ein träger Angriff ließe die erste Spitze durch — und die ist die, die
    man hört."""
    bg = sfx.Begrenzer(0.4, 200.0)
    x = np.concatenate([np.zeros(64), np.full(64, 0.9)]).astype(np.float32)
    assert float(np.abs(bg(x)).max()) <= 0.4 + 1e-6


def test_drehzahlglaettung_laesst_die_drehzahl_nachlaufen():
    """Gegen den Gangwechsel: ohne Glättung springt die Tonhöhe in einem
    Block, mit Glättung zieht sie nach."""
    ohne = _stimme(drehzahlglaettung=0.0)
    mit = _stimme(drehzahlglaettung=120.0)
    for s in (ohne, mit):
        s.block(3200.0)
    ohne.block(2000.0)
    mit.block(2000.0)
    assert ohne._gefuehrt == pytest.approx(2000.0)
    assert mit._gefuehrt > 2400.0, "die geführte Drehzahl muss nachhängen"


def test_glaettung_kommt_am_ziel_an():
    s = _stimme(drehzahlglaettung=60.0)
    s.block(3200.0)
    for _ in range(80):
        s.block(2000.0)
    assert s._gefuehrt == pytest.approx(2000.0, abs=5.0)


def test_filter_ueberleben_einen_reglerklick():
    """Im Labor wird gedreht, während der Motor läuft. Würden die Filter dabei
    neu gebaut, knackte es bei jedem Klick — ausgerechnet das sucht man hier."""
    s = _stimme(hochpass_hz=40.0, begrenzer_schwelle=0.8)
    s.block(3200.0)
    mittel, huelle = s.hochpass._mittel, s.begrenzer._huellkurve
    assert mittel != 0.0 or huelle != 0.0
    w = dict(motorklang.VORGABE)
    w.update(hochpass_hz=45.0, begrenzer_schwelle=0.75)
    s.werte_setzen(w)
    assert s.hochpass._mittel == mittel
    assert s.begrenzer._huellkurve == huelle
    assert s.hochpass.ecke == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Die Seite im Labor
# ---------------------------------------------------------------------------
@pytest.fixture
def labor():
    from src.core.state_machine import StateMachine
    from src.states.vehicle_lab_state import VehicleLabState

    sm = StateMachine()
    lab = VehicleLabState(sm)
    sm.register("vehicle_lab", lab)
    lab.enter(vehicle_config="supercar")
    lab.seite = "klang"
    yield lab
    lab._klang.beenden()
    # Die Fahrzeugkonfigurationen sind ein Singleton: was hier an
    # klang_tonhoehe gedreht wurde, saehe sonst jeder spaetere Test.
    # Geschrieben wird nichts — nur der Speicher wird wieder sauber.
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs("data/vehicles")


def test_motortyp_kommt_aus_der_fahrzeugklasse(labor):
    assert labor._klang.motor() == "8zyl", "Rennfahrzeug fährt achtzylindrig"


def test_hochschalten_senkt_die_drehzahl(labor):
    k = labor._klang
    k.gang, k.upm = 3, 3200.0
    vorher = k.upm
    k.schalten(+1)
    assert k.gang == 4
    assert k.upm < vorher, "hochschalten heißt weniger Drehzahl"


def test_runterschalten_hebt_sie(labor):
    k = labor._klang
    k.gang, k.upm = 3, 3000.0
    k.schalten(-1)
    assert k.gang == 2
    assert k.upm > 3000.0


def test_der_letzte_gang_ist_der_letzte(labor):
    k = labor._klang
    k.gang = len(k._uebersetzungen())
    upm = k.upm
    k.schalten(+1)
    assert k.gang == len(k._uebersetzungen())
    assert k.upm == upm


def test_drehzahl_bleibt_im_aufgenommenen_bereich(labor):
    k = labor._klang
    lo, hi = sfx.schichten(k.motor()).bereich
    for _ in range(200):
        k.drehzahl_verstellen(+1)
    assert k.upm <= hi
    for _ in range(400):
        k.drehzahl_verstellen(-1)
    assert k.upm >= lo


def test_motorwerte_und_fahrzeugwerte_landen_woanders(labor):
    """Der Kern der Aufteilung: was für alle Achtzylinder gilt, darf nicht in
    der Fahrzeugdatei landen — und umgekehrt."""
    k = labor._klang
    k.zeile = next(i for i, r in enumerate(k._REGLER_TEST) if r[1] == "hochpass_hz")
    k._verstellen(+1)
    assert motorklang.werte("8zyl")["hochpass_hz"] > 0.0
    assert not hasattr(labor._cfg(), "klang_hochpass_hz")

    k.zeile = next(i for i, r in enumerate(k._REGLER_TEST) if r[1] == "tonhoehe")
    k._verstellen(-1)
    assert labor._cfg().klang_tonhoehe < 1.0
    assert "tonhoehe" not in motorklang.werte("8zyl")


def test_jeder_regler_bleibt_in_seinen_grenzen(labor):
    k = labor._klang
    for i, (_st, schluessel, _lbl, quelle, _e) in enumerate(k._REGLER_TEST):
        k.zeile = i
        lo, hi, _s, _d = k._grenzen(schluessel, quelle)
        for _ in range(400):
            k._verstellen(+1)
        assert k._lesen(schluessel, quelle) == pytest.approx(hi), schluessel
        for _ in range(800):
            k._verstellen(-1)
        assert k._lesen(schluessel, quelle) == pytest.approx(lo), schluessel


def test_zeichnen_geht_ohne_audiogeraet(labor):
    schirm = pygame.Surface((1920, 1080))
    labor.render(schirm)
    k = labor._klang
    assert k._rects, "keine Klickflächen"
    assert k._pfeile, "keine Reglerpfeile"
    assert len(k._stufen) == 5, "fünf Stationen, fünf Zwischenstände"


def test_die_stationen_zeigen_verschiedene_stufen(labor):
    """Sonst wäre der Signalweg fünfmal dasselbe Bild."""
    k = labor._klang
    k.zeile = next(i for i, r in enumerate(k._REGLER_TEST) if r[1] == "hochpass_hz")
    for _ in range(8):
        k._verstellen(+1)
    k._signatur = None
    k._neu_rechnen()
    roh, _takt, gefaerbt, hochpass, begrenzer = k._stufen
    assert not np.array_equal(roh, gefaerbt) or k._lesen("faerbung", "fahrzeug") == 0.0
    assert not np.array_equal(gefaerbt, hochpass), "der Hochpass tut nichts"
    assert begrenzer.shape == roh.shape


def test_anzeige_stoert_den_laufenden_klang_nicht(labor):
    """Gerechnet wird auf einer eigenen Stimme. Liefe die Anzeige über die
    spielende, drehte jedes Bild deren Phase weiter und zerhackte den Klang."""
    k = labor._klang
    k.hoeren_umschalten(True)
    if k.stimme is None:
        pytest.skip("kein Mixer")
    vorher = k.stimme.phase
    k._signatur = None
    k._neu_rechnen()
    assert k.stimme.phase == vorher
