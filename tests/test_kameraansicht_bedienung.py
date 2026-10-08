"""Kameraansicht umschalten, zurückschauen, im Profil merken (1.1.0).

Taste und Pad, Profil, und im echten Rennen: je Mensch eine eigene Ansicht,
das HUD blendet im Cockpit die Rundinstrumente aus.
"""
from __future__ import annotations

import os
import sys

import pygame
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

from src.core import gamepad, input_source, keybindings as kb, profile  # noqa: E402
from src.render3d import ansichten  # noqa: E402


# ---------------------------------------------------------------------------
# Belegung
# ---------------------------------------------------------------------------

def test_kamera_und_zurueckschauen_sind_belegbar_mit_vorgaben_c_und_b():
    ids = {a: k for a, _lbl, k in kb.ACTIONS}
    assert ids["camera"] == pygame.K_c
    assert ids["look_back"] == pygame.K_b


def test_die_vorgaben_kollidieren_nicht_und_sind_nicht_reserviert():
    tasten = [k for _a, _l, k in kb.ACTIONS]
    assert len(set(tasten)) == len(tasten)
    assert not set(tasten) & kb.RESERVED
    # WASD gilt als zweite Belegung der Fahrtasten und darf nicht überlagert werden.
    assert not set(tasten[-2:]) & {pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d}


def test_die_bezeichnungen_haben_eine_englische_uebersetzung():
    import json
    with open(os.path.join(_ROOT, "data", "i18n", "en.json"), encoding="utf-8") as fh:
        en = json.load(fh)
    for aktion, text, _k in kb.ACTIONS:
        assert text in en or aktion in ("throttle", "left", "right"), text
    for name in ansichten.NAMEN.values():
        assert name in en


class _Tasten:
    def __init__(self, *gedrueckt):
        self._g = set(gedrueckt)

    def __getitem__(self, taste):
        return taste in self._g


def test_tastatur_liest_die_belegten_tasten(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten(kb.get("camera")))
    assert input_source.KeyboardSource().kamera() == (True, False)
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten(kb.get("look_back")))
    assert input_source.KeyboardSource().kamera() == (False, True)
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten())
    assert input_source.KeyboardSource().kamera() == (False, False)


def test_umbelegte_taste_gilt(monkeypatch):
    monkeypatch.setattr(kb, "get", lambda a: {"camera": pygame.K_v, "look_back": pygame.K_n}.get(a, 0))
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten(pygame.K_v, pygame.K_n))
    assert input_source.KeyboardSource().kamera() == (True, True)


class _Pad:
    def __init__(self, *knoepfe):
        self._k = set(knoepfe)

    def get_button(self, n):
        return n in self._k

    def get_numbuttons(self):
        return 16


def test_pad_y_wechselt_und_stickdruck_schaut_zurueck(monkeypatch):
    monkeypatch.setattr(gamepad, "_is_modern_layout", lambda joy: False)
    monkeypatch.setattr(gamepad, "device", lambda i=0: _Pad(gamepad.BTN_Y))
    assert input_source.GamepadSource(0).kamera() == (True, False)
    monkeypatch.setattr(gamepad, "device", lambda i=0: _Pad(gamepad.BTN_RS))
    assert input_source.GamepadSource(0).kamera() == (False, True)


def test_pad_knoepfe_im_modernen_layout_werden_umgerechnet(monkeypatch):
    """Dort liegt der rechte Stickdruck auf der rohen Kennung 8, nicht 9."""
    monkeypatch.setattr(gamepad, "_is_modern_layout", lambda joy: True)
    assert gamepad.knopf_gedrueckt(_Pad(8), gamepad.BTN_RS)
    assert not gamepad.knopf_gedrueckt(_Pad(9), gamepad.BTN_RS)
    assert gamepad.knopf_gedrueckt(_Pad(gamepad.BTN_Y), gamepad.BTN_Y)


def test_pad_ohne_geraet_meldet_nichts(monkeypatch):
    monkeypatch.setattr(gamepad, "device", lambda i=0: None)
    assert input_source.GamepadSource(3).kamera() == (False, False)


def test_die_gewaehlten_padknoepfe_kollidieren_nicht_mit_der_fahrt():
    assert input_source.GamepadSource.KAMERA_WECHSEL not in (gamepad.BTN_A, gamepad.BTN_RB)
    assert input_source.GamepadSource.KAMERA_ZURUECK not in (gamepad.BTN_A, gamepad.BTN_RB)
    assert input_source.GamepadSource.KAMERA_WECHSEL not in (
        gamepad.BTN_START, gamepad.BTN_BACK, gamepad.BTN_B)


def test_kombiniert_gilt_tastatur_oder_pad(monkeypatch):
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten())
    monkeypatch.setattr(gamepad, "_is_modern_layout", lambda joy: False)
    monkeypatch.setattr(gamepad, "device", lambda i=0: _Pad(gamepad.BTN_Y))
    assert input_source.CombinedSource().kamera() == (True, False)
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _Tasten(kb.get("look_back")))
    assert input_source.CombinedSource().kamera() == (True, True)


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

@pytest.fixture
def profil_datei(tmp_path, monkeypatch):
    monkeypatch.setattr(profile, "_profile_path", lambda: str(tmp_path / "profile.json"))
    return tmp_path / "profile.json"


def test_neues_profil_beginnt_mit_der_standardansicht():
    p = profile.Profile(username="Fahrer")
    assert p.ansicht(1) == ansichten.STANDARD
    assert p.ansicht(2) == ansichten.STANDARD


def test_die_ansicht_bleibt_im_profil_erhalten(profil_datei):
    p = profile.Profile(username="Fahrer")
    p.set_ansicht(1, ansichten.COCKPIT)
    p.set_ansicht(2, ansichten.MOTORHAUBE)
    neu = profile.Profile.load()
    assert neu.ansicht(1) == ansichten.COCKPIT
    assert neu.ansicht(2) == ansichten.MOTORHAUBE
    assert neu.username == "Fahrer"


def test_ein_profil_ohne_das_feld_ist_ein_altes_und_bekommt_die_standardansicht(profil_datei):
    profile.Profile(username="Alt").save()
    import json
    from src.core import tresor
    daten = json.loads(tresor.lesen(str(profil_datei)))
    daten.pop("kamera_ansichten")
    tresor.schreiben(str(profil_datei), json.dumps(daten))
    assert profile.Profile.load().ansicht(1) == ansichten.STANDARD


def test_unbekannte_gespeicherte_ansicht_wird_zur_standardansicht(profil_datei):
    p = profile.Profile(username="Fahrer", kamera_ansichten={"1": "hubschrauber", "2": 7})
    assert p.ansicht(1) == ansichten.STANDARD
    assert p.ansicht(2) == ansichten.STANDARD
    p.set_ansicht(1, "hubschrauber")
    assert profile.Profile.load().ansicht(1) == ansichten.STANDARD


def test_ansicht_speichern_schreibt_nur_bei_aenderung(profil_datei):
    p = profile.Profile(username="Fahrer")
    p.set_ansicht(1, ansichten.COCKPIT)
    zeit = profil_datei.stat().st_mtime_ns
    p.set_ansicht(1, ansichten.COCKPIT)
    assert profil_datei.stat().st_mtime_ns == zeit


# ---------------------------------------------------------------------------
# Im Rennen
# ---------------------------------------------------------------------------

class _Quelle:
    """Ein Fahrer, der nichts tut, mit Hand auf Kamera- und Rückblicktaste."""
    is_analog = False

    def __init__(self):
        self.wechsel = False
        self.zurueck = False

    def read(self):
        return 0.0, 0.0, 0.0, False

    def kamera(self):
        return self.wechsel, self.zurueck


@pytest.fixture
def rennen(monkeypatch, tmp_path):
    import spielhilfe
    spielhilfe.bus_isolieren(monkeypatch)
    # Das Profil dieses Tests liegt im Speicher: set_ansicht darf die echte Datei nicht berühren.
    p = profile.Profile(username="Testfahrer")
    monkeypatch.setattr(p, "save", lambda: None)
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    r, _sm = spielhilfe.rennen_bauen("oval", feld=3)
    r._quelle = _Quelle()
    r.player.input_source = r._quelle
    r._profil = p
    yield r
    spielhilfe.alles_schliessen()


def _bild(rennen, n=1):
    for _ in range(n):
        rennen.update(1.0 / 60.0)


def test_das_rennen_startet_in_der_gespeicherten_ansicht(monkeypatch):
    import spielhilfe
    spielhilfe.bus_isolieren(monkeypatch)
    p = profile.Profile(username="Testfahrer", kamera_ansichten={"1": ansichten.COCKPIT})
    monkeypatch.setattr(profile, "current", lambda: p)
    try:
        r, _sm = spielhilfe.rennen_bauen("oval", feld=3)
        assert r._kameras[0].ansicht == ansichten.COCKPIT
        assert r.camera is r._kameras[0]
    finally:
        spielhilfe.alles_schliessen()


def test_taste_schaltet_der_reihe_nach_um_und_merkt_es_im_profil(rennen):
    kam = rennen._kameras[0]
    assert kam.ansicht == ansichten.VERFOLGER_FERN
    gesehen = []
    for _ in range(len(ansichten.ANSICHTEN)):
        rennen._quelle.wechsel = True
        _bild(rennen)
        rennen._quelle.wechsel = False
        _bild(rennen)
        gesehen.append(kam.ansicht)
        assert rennen._profil.ansicht(1) == kam.ansicht
    assert gesehen == [ansichten.VERFOLGER_NAH, ansichten.MOTORHAUBE, ansichten.COCKPIT,
                       ansichten.VERFOLGER_FERN]


def test_gehaltene_taste_schaltet_nur_einmal_um(rennen):
    rennen._quelle.wechsel = True
    _bild(rennen, 10)
    assert rennen._kameras[0].ansicht == ansichten.VERFOLGER_NAH


def test_zurueckschauen_gilt_nur_solange_die_taste_gehalten_wird(rennen):
    kam = rennen._kameras[0]
    assert not kam.rueckblick
    rennen._quelle.zurueck = True
    _bild(rennen)
    assert kam.rueckblick
    rennen._quelle.zurueck = False
    _bild(rennen)
    assert not kam.rueckblick


def test_umschalten_blendet_den_namen_der_ansicht_ein(rennen):
    rennen._quelle.wechsel = True
    _bild(rennen)
    assert rennen._ansicht_hinweis[1][0] == ansichten.NAMEN[ansichten.VERFOLGER_NAH]
    rennen._quelle.wechsel = False
    _bild(rennen, int((rennen.ANSICHT_HINWEIS_S + 0.5) * 60))
    assert 1 not in rennen._ansicht_hinweis


def test_im_cockpit_entfallen_die_rundinstrumente_des_huds(rennen):
    screen = pygame.Surface((1920, 1080), pygame.SRCALPHA)
    rennen._ansicht_huds(screen)
    assert rennen.hud.dashboard_sichtbar
    rennen._kameras[0].ansicht_setzen(ansichten.COCKPIT)
    rennen._ansicht_huds(screen)
    assert not rennen.hud.dashboard_sichtbar
    rennen._kameras[0].ansicht_setzen(ansichten.MOTORHAUBE)
    rennen._ansicht_huds(screen)
    assert rennen.hud.dashboard_sichtbar


def test_hud_zeichnet_ohne_dashboard_weniger_und_stuerzt_nicht(rennen):
    from src.hud.hud import HUD
    hud = HUD()
    mit, ohne = (pygame.Surface((1920, 1080), pygame.SRCALPHA) for _ in range(2))
    hud._render_dashboard(mit, 1920, 1080, 1.0)
    hud.dashboard_sichtbar = False
    hud._render_dashboard(ohne, 1920, 1080, 1.0)
    assert pygame.mask.from_surface(mit).count() > 0
    assert pygame.mask.from_surface(ohne).count() == 0


def test_die_starre_ansicht_sitzt_am_wagen_des_menschen(rennen):
    kam = rennen._kameras[0]
    kam.ansicht_setzen(ansichten.COCKPIT)
    _bild(rennen, 3)
    from src.states.race_state import welt3d
    import numpy as np
    pos = np.array(welt3d(rennen.player.position))
    # Das Auge liegt im Fahrzeug: höchstens vier Meter vom Wagenursprung, über dem Boden.
    assert np.linalg.norm(kam.auge[:2] - pos[:2]) < 2.5
    assert 0.5 < kam.auge[2] < 2.0


def _zustand_ohne_rennen():
    """Ein RaceState nur mit dem, was die Kameraauswahl braucht (kein Rennaufbau)."""
    from src.states.race_state import RaceState
    stand = RaceState.__new__(RaceState)
    stand._kamera_taste_war = {}
    stand._ansicht_hinweis = {}
    return stand


def _mensch(schluessel, quelle=None):
    from types import SimpleNamespace
    return SimpleNamespace(config_key=schluessel, input_source=quelle)


def test_splitscreen_jeder_mensch_hat_seine_eigene_ansicht(monkeypatch):
    from src.states.race_state import RaceState
    p = profile.Profile(username="Testfahrer",
                        kamera_ansichten={"1": ansichten.COCKPIT, "2": ansichten.VERFOLGER_NAH})
    monkeypatch.setattr(profile, "current", lambda: p)
    stand = _zustand_ohne_rennen()
    k1 = RaceState._kamera_bauen(stand, _mensch("rookie"), 1)
    k2 = RaceState._kamera_bauen(stand, _mensch("supercar"), 2)
    assert (k1.ansicht, k2.ansicht) == (ansichten.COCKPIT, ansichten.VERFOLGER_NAH)
    # Jeder Wagen bringt seinen eigenen Augpunkt mit.
    assert not (k1.masse.augpunkt == k2.masse.augpunkt).all()


def test_zwei_menschen_schalten_unabhaengig(monkeypatch):
    """Wechsel und Rückblick des einen berühren die Kamera des anderen nicht."""
    from src.states.race_state import RaceState
    p = profile.Profile(username="Testfahrer")
    monkeypatch.setattr(p, "save", lambda: None)
    monkeypatch.setattr(profile, "current", lambda: p)
    stand = _zustand_ohne_rennen()
    q1, q2 = _Quelle(), _Quelle()
    m1, m2 = _mensch("rookie", q1), _mensch("rookie", q2)
    k1 = RaceState._kamera_bauen(stand, m1, 1)
    k2 = RaceState._kamera_bauen(stand, m2, 2)
    q2.wechsel = True
    q1.zurueck = True
    stand._kamera_eingabe(1, m1, k1)
    stand._kamera_eingabe(2, m2, k2)
    assert (k1.ansicht, k2.ansicht) == (ansichten.VERFOLGER_FERN, ansichten.VERFOLGER_NAH)
    assert k1.rueckblick and not k2.rueckblick
    assert p.ansicht(1) == ansichten.VERFOLGER_FERN and p.ansicht(2) == ansichten.VERFOLGER_NAH
