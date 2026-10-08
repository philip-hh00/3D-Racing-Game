"""Controller-Vibration (Plan 1.1.0, Punkt 6): Zuordnung der Anlässe zu Rumble.

Alles mit einem falschen Controller: ein Spion statt ``gamepad.rumble``, und
eine Joystick-Attrappe, wo es um den Weg bis ins Gerät geht. Zugesagt sind:

* Treffer, Wandschleifen, Rutschen und Randstein ergeben je ein eigenes
  Muster, skaliert mit dem Impuls bzw. dem Schlupf;
* die Reglerstufe (Aus, Schwach, Mittel, Stark) skaliert alles, Aus schweigt;
* jeder Spieler hat seinen eigenen Controller (Splitscreen);
* ein Controller ohne Rumble oder ein Treiberfehler stört das Rennen nie.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from src.core import gamepad, vibration  # noqa: E402
from src.core.input_source import CombinedSource, GamepadSource, KeyboardSource  # noqa: E402
from src.core.vibration import Vibration  # noqa: E402

DT = 1.0 / 60.0


class Spion:
    """Sammelt, was an den Controller ginge."""

    def __init__(self, antwort=True):
        self.befehle: list[tuple] = []
        self.stopps: list[int] = []
        self.antwort = antwort

    def __call__(self, index, tief, hoch, ms):
        self.befehle.append((index, tief, hoch, ms))
        if isinstance(self.antwort, Exception):
            raise self.antwort
        return self.antwort

    def stopp(self, index):
        self.stopps.append(index)


def _v(pad=0, stufe=3, antwort=True):
    spion = Spion(antwort)
    return Vibration(pad, stufe, ausgabe=spion, stopp=spion.stopp), spion


def _laufen(v, sekunden, **kw):
    for _ in range(round(sekunden / DT)):
        v.fortschreiben(DT, **kw)


# ---------------------------------------------------------------------------
# Abbildung der Anlässe
# ---------------------------------------------------------------------------

def test_leichter_treffer_ist_kurz_und_schwach_schwerer_lang_und_stark():
    leicht = vibration.stoss_aus_impuls(900.0)
    schwer = vibration.stoss_aus_impuls(9000.0)
    assert leicht[0] < schwer[0] and leicht[2] < schwer[2]
    assert 0.0 < leicht[0] < 0.6 and schwer[0] == pytest.approx(1.0)
    assert schwer[2] == pytest.approx(vibration.STOSS_DAUER_S[1])


def test_unter_der_schwelle_kein_stoss():
    assert vibration.stoss_aus_impuls(vibration.IMPULS_AB - 1) == (0.0, 0.0, 0.0)
    assert vibration.stoss_aus_impuls(float("nan")) == (0.0, 0.0, 0.0)
    assert vibration.stoss_aus_impuls("kaputt") == (0.0, 0.0, 0.0)


def test_stoss_wird_gesendet_und_klingt_ab():
    v, spion = _v()
    v.stoss(6000.0)
    _laufen(v, 0.05)
    erster = spion.befehle[0]
    assert erster[0] == 0 and erster[1] > 0.5 and erster[2] > 0.3
    _laufen(v, 1.0)
    # nach dem Stoss: gestoppt, nichts Neues mehr
    assert spion.stopps == [0]
    n = len(spion.befehle)
    _laufen(v, 0.5)
    assert len(spion.befehle) == n


def test_staerkerer_stoss_gibt_staerkeren_befehl():
    a, sa = _v()
    b, sb = _v()
    a.stoss(1000.0)
    b.stoss(8000.0)
    a.fortschreiben(DT)
    b.fortschreiben(DT)
    assert sb.befehle[0][1] > sa.befehle[0][1]


def test_wandschleifen_brummt_gleichmaessig_solange_beruehrt():
    v, spion = _v()
    _laufen(v, 0.5, wand=True, tempo_ms=30.0)
    assert spion.befehle and all(b[1] > 0.2 and b[2] > 0.1 for b in spion.befehle)
    _laufen(v, 0.2, wand=False, tempo_ms=30.0)
    assert spion.stopps == [0]


def test_rutschen_gibt_tiefes_grollen_nach_schlupf():
    schwach, s1 = _v()
    stark, s2 = _v()
    _laufen(schwach, 0.3, schlupf=0.35, tempo_ms=25.0)
    _laufen(stark, 0.3, schlupf=1.0, tempo_ms=25.0)
    assert s1.befehle and s2.befehle
    assert s2.befehle[-1][1] > s1.befehle[-1][1]
    assert s2.befehle[-1][2] == 0.0                  # nur der tiefe Motor
    # kein Rutschen: Ruhe
    ruhig, s3 = _v()
    _laufen(ruhig, 0.3, schlupf=0.1, tempo_ms=25.0)
    assert s3.befehle == []


def test_stehend_rutscht_nichts():
    v, spion = _v()
    _laufen(v, 0.3, schlupf=1.0, randstein=True, tempo_ms=0.5)
    assert spion.befehle == []


def test_randstein_gibt_kurze_schlaege_auf_dem_hohen_motor():
    v, spion = _v()
    _laufen(v, 1.0, randstein=True, tempo_ms=30.0)
    assert len(spion.befehle) >= 4                   # mehrere Schlaege, nicht ein Dauerton
    assert all(b[1] == 0.0 and b[2] > 0.3 for b in spion.befehle if b[2] > 0.0)
    # Schlag, Pause, Schlag: zwischendurch wird gestoppt
    assert len(spion.stopps) >= 2


def test_schnelleres_tempo_schlaegt_oefter():
    langsam, s1 = _v()
    schnell, s2 = _v()
    _laufen(langsam, 2.0, randstein=True, tempo_ms=5.0)
    _laufen(schnell, 2.0, randstein=True, tempo_ms=45.0)
    assert len(s2.stopps) > len(s1.stopps)


def test_anlaesse_ueberlagern_sich_mit_dem_staerksten():
    v, spion = _v()
    v.stoss(9000.0)
    v.fortschreiben(DT, schlupf=0.4, wand=True, tempo_ms=30.0)
    assert spion.befehle[0][1] == pytest.approx(1.0, abs=0.05)


# ---------------------------------------------------------------------------
# Reglerstufe
# ---------------------------------------------------------------------------

def test_stufen_skalieren_der_regler():
    pegel = []
    for stufe in range(4):
        v, spion = _v(stufe=stufe)
        v.stoss(9000.0)
        v.fortschreiben(DT)
        pegel.append(spion.befehle[0][1] if spion.befehle else 0.0)
    assert pegel[0] == 0.0
    assert pegel[0] < pegel[1] < pegel[2] < pegel[3] <= 1.0


def test_aus_schweigt_ganz():
    v, spion = _v(stufe=0)
    v.stoss(9000.0)
    _laufen(v, 0.5, schlupf=1.0, wand=True, randstein=True, tempo_ms=40.0)
    assert spion.befehle == []


def test_stufe_aus_waehrend_der_fahrt_stoppt_sofort():
    v, spion = _v(stufe=3)
    _laufen(v, 0.2, wand=True, tempo_ms=30.0)
    v.stufe_setzen(0)
    assert spion.stopps == [0]
    _laufen(v, 0.2, wand=True, tempo_ms=30.0)
    assert spion.stopps == [0] and len(spion.befehle) <= 14


def test_unsinnige_stufen_ergeben_aus():
    assert vibration.stufe_faktor(None) == 0.0
    assert vibration.stufe_faktor("viel") == 0.0
    assert vibration.stufe_faktor(9) == 0.0
    assert vibration.stufe_faktor(-1) == 0.0
    assert vibration.stufe_faktor(3) == vibration.STAERKEN[-1]


# ---------------------------------------------------------------------------
# Jeder Spieler seinen Controller
# ---------------------------------------------------------------------------

def test_splitscreen_zwei_spieler_zwei_controller():
    spion = Spion()
    p1 = Vibration(0, 3, ausgabe=spion, stopp=spion.stopp)
    p2 = Vibration(1, 3, ausgabe=spion, stopp=spion.stopp)
    p1.stoss(9000.0)
    p1.fortschreiben(DT)
    p2.fortschreiben(DT, wand=True, tempo_ms=30.0)
    indizes = {b[0] for b in spion.befehle}
    assert indizes == {0, 1}
    nur_p1 = [b for b in spion.befehle if b[0] == 0]
    nur_p2 = [b for b in spion.befehle if b[0] == 1]
    assert nur_p1[0][1] > nur_p2[0][1]               # Stoss stark, Wand schwaecher


def test_tastatur_hat_keinen_controller_und_schweigt():
    assert vibration.pad_index_von(KeyboardSource()) is None
    spion = Spion()
    v = Vibration(vibration.pad_index_von(KeyboardSource()), 3, ausgabe=spion, stopp=spion.stopp)
    v.stoss(9000.0)
    _laufen(v, 0.3, schlupf=1.0, tempo_ms=30.0)
    assert spion.befehle == []


def test_pad_index_aus_der_eingabequelle():
    assert vibration.pad_index_von(GamepadSource(1)) == 1
    assert vibration.pad_index_von(GamepadSource(0)) == 0
    assert vibration.pad_index_von(CombinedSource()) == 0     # Tastatur + erster Controller
    assert vibration.pad_index_von(None) is None


# ---------------------------------------------------------------------------
# Robustheit: Controller ohne Rumble, Treiberfehler, abgezogen
# ---------------------------------------------------------------------------

def test_pad_ohne_rumble_stoert_nie_und_wird_nicht_jedes_bild_probiert():
    v, spion = _v(antwort=False)                     # rumble() sagt: nicht unterstuetzt
    _laufen(v, 2.0, wand=True, schlupf=1.0, tempo_ms=30.0)
    assert len(spion.befehle) <= 2                   # einmal versucht, dann Sperre


def test_ausnahme_im_treiber_wird_geschluckt():
    v, spion = _v(antwort=RuntimeError("Treiber"))
    v.stoss(9000.0)
    _laufen(v, 1.0, wand=True, tempo_ms=30.0)        # darf nicht werfen
    assert len(spion.befehle) <= 2


def test_nach_der_sperre_wird_es_erneut_versucht():
    v, spion = _v(antwort=False)
    _laufen(v, 0.1, wand=True, tempo_ms=30.0)
    erster = len(spion.befehle)
    spion.antwort = True                             # Controller wieder da
    _laufen(v, vibration.SPERRE_S + 0.5, wand=True, tempo_ms=30.0)
    assert len(spion.befehle) > erster


def test_fehlender_stopp_wirft_nicht():
    spion = Spion()
    v = Vibration(0, 3, ausgabe=spion, stopp=None)
    _laufen(v, 0.2, wand=True, tempo_ms=30.0)
    v.stoppen()                                      # kein Stopp-Rueckruf: nur still


def test_stopp_wirft_nicht():
    def kaputt(_i):
        raise OSError("abgezogen")
    spion = Spion()
    v = Vibration(0, 3, ausgabe=spion, stopp=kaputt)
    _laufen(v, 0.2, wand=True, tempo_ms=30.0)
    v.stoppen()


def test_befehle_sind_kurz_und_werden_erneuert():
    v, spion = _v()
    _laufen(v, 1.0, wand=True, tempo_ms=30.0)
    assert all(b[3] <= 250 for b in spion.befehle)   # vergessen verklingt von selbst
    assert len(spion.befehle) <= 15                  # nicht jedes Bild ans Geraet


# ---------------------------------------------------------------------------
# Der Weg bis ins Geraet (gamepad.rumble)
# ---------------------------------------------------------------------------

class JoyMitRumble:
    def __init__(self):
        self.rumbles = []
        self.gestoppt = 0

    def rumble(self, tief, hoch, ms):
        self.rumbles.append((tief, hoch, ms))
        return True

    def stop_rumble(self):
        self.gestoppt += 1


class JoyOhneRumble:
    def rumble(self, tief, hoch, ms):
        return False

    def stop_rumble(self):
        raise pygame.error("nicht unterstuetzt")


class JoyDefekt:
    def rumble(self, *a):
        raise pygame.error("kaputt")

    def stop_rumble(self):
        raise pygame.error("kaputt")


@pytest.fixture
def manager(monkeypatch):
    m = gamepad.GamepadManager()
    monkeypatch.setattr(gamepad, "_gamepad_manager", m)
    return m


def test_gamepad_rumble_geht_an_den_richtigen_controller(manager):
    j0, j1 = JoyMitRumble(), JoyMitRumble()
    manager._joysticks = [j0, j1]
    assert gamepad.rumble(1, 0.5, 0.25, 100) is True
    assert j1.rumbles == [(0.5, 0.25, 100)] and j0.rumbles == []
    gamepad.stop_rumble(0)
    assert j0.gestoppt == 1 and j1.gestoppt == 0


def test_gamepad_rumble_ohne_unterstuetzung_stuerzt_nicht(manager):
    manager._joysticks = [JoyOhneRumble(), JoyDefekt()]
    assert gamepad.rumble(0, 1.0, 1.0, 100) is False
    assert gamepad.rumble(1, 1.0, 1.0, 100) is False
    assert gamepad.rumble(5, 1.0, 1.0, 100) is False         # gibt es nicht
    gamepad.stop_rumble(0)
    gamepad.stop_rumble(1)
    gamepad.stop_rumble(5)


def test_gamepad_ohne_manager(monkeypatch):
    monkeypatch.setattr(gamepad, "_gamepad_manager", None)
    assert gamepad.rumble(0, 1.0, 1.0, 100) is False
    gamepad.stop_rumble(0)


def test_vibration_bis_in_die_joystick_attrappe(manager):
    manager._joysticks = [JoyMitRumble(), JoyMitRumble()]
    v = Vibration(1, 2)                              # Vorgabe: gamepad.rumble und stop_rumble
    v.stoss(9000.0)
    _laufen(v, 0.6)
    assert manager._joysticks[1].rumbles and not manager._joysticks[0].rumbles
    assert manager._joysticks[1].gestoppt >= 1


def test_vibration_mit_defektem_pad_stuerzt_nicht(manager):
    manager._joysticks = [JoyDefekt()]
    v = Vibration(0, 3)
    v.stoss(9000.0)
    _laufen(v, 1.0, wand=True, tempo_ms=30.0)
    v.stoppen()
