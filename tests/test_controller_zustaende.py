"""Die Vollbild-Zustände mit dem Controller allein: Fahrzeug- und Streckenwahl,
Werkstatt, Ergebnisse, Willkommen, Streckeneditor, Rennpause, Online-Strecken.

Siehe ``test_controller_erreichbar`` für die Vorgabe und ``test_controller_online``
für die Online-Ansichten der Menüschale.
"""
from __future__ import annotations

import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import gamepad, profile, race_setup  # noqa: E402
from tests import controller_pruefung as cp  # noqa: E402
from tests import spielhilfe  # noqa: E402

A, B = gamepad.BTN_A, gamepad.BTN_B
HOCH, RUNTER = gamepad.BTN_DPAD_UP, gamepad.BTN_DPAD_DOWN
LINKS, RECHTS = gamepad.BTN_DPAD_LEFT, gamepad.BTN_DPAD_RIGHT
X, Y, START = gamepad.BTN_X, gamepad.BTN_Y, gamepad.BTN_START
LB, RB = gamepad.BTN_LB, gamepad.BTN_RB


@pytest.fixture(autouse=True)
def _aufbau_bewahren(monkeypatch):
    spielhilfe.aufbau_bewahren(monkeypatch)


@pytest.fixture
def pad():
    manager, zurueck = spielhilfe.pad_anmelden()
    yield manager
    zurueck()
    manager._using_pad = False


@pytest.fixture
def spielstand(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


class _Maschine:
    """Eine Zustandsmaschine, die Wechsel merkt, statt sie zu gehen."""

    def __init__(self) -> None:
        self.wechsel: list[tuple[str, dict]] = []
        self.zurueck_zaehler = 0

    def transition(self, name, **kwargs) -> None:
        self.wechsel.append((name, kwargs))

    def push(self, name, **kwargs) -> None:
        self.wechsel.append((name, kwargs))

    def pop(self) -> None:
        pass

    def zurueck(self, fallback="menu") -> bool:
        self.zurueck_zaehler += 1
        self.wechsel.append((fallback, {"_zurueck": True}))
        return True

    @property
    def letzter(self) -> str | None:
        return self.wechsel[-1][0] if self.wechsel else None


def _render(zustand) -> bytes:
    schirm = pygame.Surface((1920, 1080))
    schirm.fill((0, 0, 0))
    zustand.render(schirm)
    return pygame.image.tobytes(schirm, "RGB")


def _taste(key, synthetic=True):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0,
                              synthetic=synthetic)


# ---------------------------------------------------------------------------
# Fahrzeugwahl
# ---------------------------------------------------------------------------

@pytest.fixture
def autowahl(spielstand):
    from src.entities.vehicle_factory import VehicleFactory
    from src.states.car_select_state import CarSelectState
    VehicleFactory.load_all_configs()
    z = CarSelectState(_Maschine())
    z.enter(picker="p1")
    return z


def test_fahrzeugwahl_werkstatt_knopf_ist_per_pad_erreichbar(autowahl, pad):
    """Fund: der Werkstatt-Knopf hatte nur die Taste L und die Maus."""
    z = autowahl
    z.selected_index = z.car_keys.index("rookie")
    assert z._werkstatt_frei()
    vorher = _render(z)
    cp.mehrmals(pad, z, RECHTS)
    assert z._knopf_fokus == "werkstatt"
    assert _render(z) != vorher, "der Fokus auf dem Werkstatt-Knopf ist nicht zu sehen"
    cp.mehrmals(pad, z, A)
    assert z.state_machine.letzter == "menu"
    assert z.state_machine.wechsel[-1][1]["reopen"] == "werkstatt"


def test_fahrzeugwahl_weiter_knopf_per_pad(autowahl, pad):
    z = autowahl
    cp.mehrmals(pad, z, RECHTS, RECHTS)
    assert z._knopf_fokus == "weiter"
    vorher = _render(z)
    cp.mehrmals(pad, z, LINKS)
    assert z._knopf_fokus == "werkstatt" and _render(z) != vorher
    cp.mehrmals(pad, z, RECHTS, A)
    assert z.state_machine.letzter == "track_select"


def test_fahrzeugwahl_vom_knopf_zurueck_in_die_liste(autowahl, pad):
    z = autowahl
    cp.mehrmals(pad, z, RECHTS)
    assert z._knopf_fokus
    cp.mehrmals(pad, z, HOCH)
    assert not z._knopf_fokus
    ersterwahl = z.selected_index
    cp.mehrmals(pad, z, RUNTER)
    assert z.selected_index == (ersterwahl + 1) % len(z.car_keys)


def test_fahrzeugwahl_jedes_fahrzeug_ist_erreichbar_und_liste_rollt_mit(autowahl, pad):
    z = autowahl
    z.selected_index = 0
    gesehen = set()
    for _ in range(len(z.car_keys) + 2):
        gesehen.add(z.selected_index)
        cp.mehrmals(pad, z, RUNTER)
        sichtbar = {i for i, _r in z._car_card_rects()}
        assert z.selected_index in sichtbar, "der Fokus liegt auf einer unsichtbaren Kachel"
    assert gesehen == set(range(len(z.car_keys)))


def test_fahrzeugwahl_b_geht_zurueck_und_a_waehlt(autowahl, pad):
    z = autowahl
    cp.mehrmals(pad, z, B)
    assert z.state_machine.letzter == "menu"
    z.state_machine.wechsel.clear()
    cp.mehrmals(pad, z, A)
    assert z.state_machine.letzter == "track_select"


def test_fahrzeugwahl_b_vom_knopf_geht_auch_zurueck(autowahl, pad):
    z = autowahl
    cp.mehrmals(pad, z, RECHTS, B)
    assert z.state_machine.letzter == "menu"


# ---------------------------------------------------------------------------
# Streckenwahl
# ---------------------------------------------------------------------------

@pytest.fixture
def streckenwahl(spielstand):
    from src.entities.vehicle_factory import VehicleFactory
    from src.states.track_select_state import TrackSelectState
    VehicleFactory.load_all_configs()
    z = TrackSelectState(_Maschine())
    z.enter(vehicle_config="rookie")
    return z


def test_streckenwahl_jede_strecke_ist_erreichbar_und_liste_rollt_mit(streckenwahl, pad):
    z = streckenwahl
    z.selected_index = 0
    gesehen = set()
    for _ in range(len(z.track_keys) + 2):
        gesehen.add(z.selected_index)
        cp.mehrmals(pad, z, RUNTER)
        sichtbar = {i for i, _r in z._track_card_rects()}
        assert z.selected_index in sichtbar
    assert gesehen == set(range(len(z.track_keys)))


def test_streckenwahl_online_strecken_ist_per_pad_erreichbar(streckenwahl, pad):
    z = streckenwahl
    vorher = _render(z)
    cp.mehrmals(pad, z, RECHTS)
    assert _render(z) != vorher, "der Fokus auf „Online-Strecken“ ist nicht zu sehen"
    cp.mehrmals(pad, z, A)
    assert z.state_machine.letzter == "online_strecken"


def test_streckenwahl_a_startet_und_b_geht_zurueck(streckenwahl, pad):
    z = streckenwahl
    cp.mehrmals(pad, z, B)
    assert z.state_machine.letzter == "car_select"
    cp.mehrmals(pad, z, A)
    assert z.state_machine.letzter == "race"


# ---------------------------------------------------------------------------
# Werkstatt
# ---------------------------------------------------------------------------

@pytest.fixture
def werkstatt(spielstand):
    from src.states.menu.werkstatt_page import WerkstattPage

    class Schale:
        def __init__(self):
            self.abgeraeumt = 0
            self.state_machine = _Maschine()

        def pop_page(self):
            self.abgeraeumt += 1

        def zurueck_gehen(self):
            self.abgeraeumt += 1

    s = WerkstattPage()
    s.enter(Schale())
    return s


def _werkstatt_zeichnen(w) -> bytes:
    schirm = pygame.Surface((1920, 1080))
    schirm.fill((0, 0, 0))
    w.draw(schirm, pygame.Rect(0, 108, 1920, 972))
    return pygame.image.tobytes(schirm, "RGB")


def _fokus_auf(w, feld) -> None:
    w._gruppe.index = w._gruppe.widgets.index(feld)


def test_werkstatt_alles_gezeichnete_ist_erreichbar(werkstatt, pad, monkeypatch):
    mit = cp.Zeichenmitschrift(monkeypatch)
    _werkstatt_zeichnen(werkstatt)
    assert cp.nicht_im_fokus(mit, [werkstatt._gruppe]) == []
    assert cp.erreichbarkeit(pad, werkstatt, werkstatt._gruppe) == []


def test_werkstatt_drehen_mit_dem_pad(werkstatt, pad):
    """Fund: die Pfeile zum Drehen des Fahrzeugs waren nur mit der Maus da."""
    w = werkstatt
    _werkstatt_zeichnen(w)
    links, rechts = w._dreh_felder
    assert links.focusable and rechts.focusable
    _fokus_auf(w, rechts)
    cp.mehrmals(pad, w, A)
    assert w.winkel == 15.0
    _fokus_auf(w, links)
    cp.mehrmals(pad, w, A, A)
    assert w.winkel % 360 == 345.0


def test_werkstatt_jedes_fahrzeug_ist_mit_dem_pad_erreichbar(werkstatt, pad):
    """Fund: nur die sichtbaren Kacheln waren fokussierbar, und das Blättern ging
    nur mit der Maus — Fahrzeuge hinter dem Rand blieben unerreichbar."""
    w = werkstatt
    assert len(w.fahrzeuge) > 7
    erreicht = {w.index}
    _werkstatt_zeichnen(w)
    for _ in range(3 * len(w.fahrzeuge)):
        # nach rechts durch die Kacheln, am Rand über den Blätterpfeil
        fokus = w._gruppe.focused
        if fokus not in w._kachel_felder and fokus not in w._blatt_felder:
            _fokus_auf(w, w._kachel_felder[w.index])
        cp.mehrmals(pad, w, RECHTS)
        if w._gruppe.focused in w._blatt_felder:
            cp.mehrmals(pad, w, A)                 # blättern
            for _ in range(60):
                w.update(1 / 30)                   # Streifen gleitet
        _werkstatt_zeichnen(w)
        fokus = w._gruppe.focused
        if fokus in w._kachel_felder:
            cp.mehrmals(pad, w, A)
            erreicht.add(w.index)
        if len(erreicht) == len(w.fahrzeuge):
            break
    assert len(erreicht) == len(w.fahrzeuge), \
        f"nur {len(erreicht)} von {len(w.fahrzeuge)} Fahrzeugen erreicht"


def test_werkstatt_fokus_auf_farbfeld_und_kachel_ist_sichtbar(werkstatt, pad):
    """Fund: Farbfelder und Fahrzeugkacheln hatten keinen Fokusrahmen."""
    w = werkstatt
    w._finish_stepper.index = 1
    w.finish_index = 1
    w._farb_index_richten()
    _werkstatt_zeichnen(w)
    bilder = set()
    frei = [f for f in w._farb_felder if f.focusable][:3]
    assert len(frei) >= 2
    for f in frei:
        _fokus_auf(w, f)
        bilder.add(_werkstatt_zeichnen(w))
    assert len(bilder) == len(frei), "Fokus auf Farbfeldern ist nicht zu sehen"
    bilder.clear()
    kacheln = [f for f in w._kachel_felder if f.focusable][:3]
    for f in kacheln:
        _fokus_auf(w, f)
        bilder.add(_werkstatt_zeichnen(w))
    assert len(bilder) == len(kacheln), "Fokus auf Fahrzeugkacheln ist nicht zu sehen"


def test_werkstatt_farbe_waehlen_und_speichern_mit_dem_pad(werkstatt, pad):
    w = werkstatt
    w._finish_stepper.index = 1
    w.finish_index = 1
    w._farb_index_richten()
    _werkstatt_zeichnen(w)
    ziel = next(f for f in w._farb_felder if f.focusable and f.action != f"farbe_{w.farb_index}")
    _fokus_auf(w, ziel)
    cp.mehrmals(pad, w, A)
    assert w.farb_index == int(ziel.action[len("farbe_"):])
    _werkstatt_zeichnen(w)
    assert w._knopf_speichern.focusable, "Speichern bleibt gesperrt"
    _fokus_auf(w, w._knopf_speichern)
    cp.mehrmals(pad, w, A)
    assert not w._geaendert()


# ---------------------------------------------------------------------------
# Ergebnisse
# ---------------------------------------------------------------------------

def _ergebnis_seite(sektoren: int):
    from src.states.menu.results_page import ResultsPage
    zeilen = [{"vehicle_id": i, "name": f"Fahrer {i}", "position": i,
               "finish_time": 60.0 + i, "best_lap": 30.0 + i, "is_player": i == 1,
               "lap_times": [30.0 + i, 30.5 + i], "dnf": False,
               "sectors": [round(5.0 * k, 2) for k in range(1, sektoren + 1)]}
              for i in range(1, 4)]
    seite = ResultsPage(zeilen, {"mode": "Zeitfahren", "ghost_sectors":
                                 [round(5.5 * k, 2) for k in range(1, sektoren + 1)]})
    return seite


def test_ergebnisse_sektoren_rollen_mit_hoch_runter(pad):
    from tests.test_controller_durchlauf import _schale_mit
    seite = _ergebnis_seite(20)
    schale = _schale_mit(seite)
    seite._scroll_max = 5                           # so, als hätte das Zeichnen es gesetzt
    cp.mehrmals(pad, schale, RUNTER)
    assert seite._scroll == 1
    cp.mehrmals(pad, schale, HOCH, HOCH)
    assert seite._scroll == 0


# ---------------------------------------------------------------------------
# Willkommen (Namenseingabe beim ersten Start)
# ---------------------------------------------------------------------------

def test_willkommen_los_gehts_ist_per_pad_erreichbar(pad, spielstand, monkeypatch):
    from src.states.welcome_state import SCHRITT_HILFE, WelcomeState
    z = WelcomeState(_Maschine())
    z.enter()
    z.input.text = "Fahrer_1"
    vorher = _render(z)
    cp.mehrmals(pad, z, RUNTER)
    assert z.gruppe.focused is z.ok
    assert _render(z) != vorher, "Fokus auf dem Knopf ist nicht zu sehen"
    cp.mehrmals(pad, z, A)
    assert z.schritt == SCHRITT_HILFE
    cp.mehrmals(pad, z, A)                          # Kurzanleitung -> Menü
    assert z.state_machine.letzter == "menu"


def test_willkommen_name_per_bildschirmtastatur(pad, spielstand):
    from src.states.welcome_state import SCHRITT_HILFE, WelcomeState
    z = WelcomeState(_Maschine())
    z.enter()
    z.input.text = ""
    cp.mehrmals(pad, z, A)
    assert z.osk is not None
    for _ in range(3):
        cp.mehrmals(pad, z, A, RECHTS)
    assert z.input.text == "ABC"
    cp.mehrmals(pad, z, START)                      # Fertig -> bestätigt
    assert z.osk is None and z.schritt == SCHRITT_HILFE, z.error


# ---------------------------------------------------------------------------
# Streckeneditor
# ---------------------------------------------------------------------------

@pytest.fixture
def editor(spielstand):
    from src.states.editor_state import EditorState
    from src.track.tile_track import TileTrackDraft
    z = EditorState(_Maschine())
    z.enter()
    z.draft = TileTrackDraft()
    z.draft.name = "Probe"
    z._mode = "edit"
    return z


def test_editor_eigenschaften_leiste_ist_mit_dem_pad_komplett(editor, pad):
    """Fund: START fokussiert die Eigenschaftenleiste, aber das Steuerkreuz kam
    nie über das Namensfeld hinaus — Breite, Hintergrund, Schwierigkeit,
    Speichern, Veröffentlichen, Abbrechen und Löschen waren so nicht zu
    erreichen (nur über den virtuellen Zeiger)."""
    z = editor
    assert z.raw_gamepad
    cp.mehrmals(pad, z, START)
    assert z._props_focused and not z.raw_gamepad
    erreicht = {z._props_field}
    for _ in range(len(z._props_layout_rects())):
        cp.mehrmals(pad, z, RUNTER)
        erreicht.add(z._props_field)
    assert erreicht == set(range(len(z._props_layout_rects())))
    # Breite verstellen
    z._props_field = 1
    breite = z.draft.width
    cp.mehrmals(pad, z, LINKS)
    assert z.draft.width != breite
    # und zurück zum Zeichnen
    cp.mehrmals(pad, z, B)
    assert not z._props_focused and z.raw_gamepad


def test_editor_speichern_ueber_die_leiste(editor, pad, monkeypatch):
    z = editor
    gerufen = []
    monkeypatch.setattr(z, "_do_save_draft", lambda *a, **k: gerufen.append(1))
    cp.mehrmals(pad, z, START)
    z._props_field = 4
    cp.mehrmals(pad, z, A)
    assert gerufen


def test_editor_name_per_bildschirmtastatur(editor, pad):
    z = editor
    cp.mehrmals(pad, z, START)
    z._props_field = 0
    cp.mehrmals(pad, z, A)
    assert z.osk is not None


# ---------------------------------------------------------------------------
# Rennpause
# ---------------------------------------------------------------------------

def test_rennpause_jeder_punkt_ist_mit_dem_pad_erreichbar(pad, spielstand):
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=2)
    try:
        cp.mehrmals(pad, rennen, START)
        assert rennen.paused, "Start pausiert das Rennen nicht"
        gruppe = rennen._pause_group
        aktionen = []
        for _ in range(len(gruppe.widgets)):
            aktionen.append(getattr(gruppe.focused, "action", None))
            cp.mehrmals(pad, rennen, RUNTER)
        assert {"resume", "standings", "settings", "quit"} <= set(aktionen), aktionen
        # Einstellungen auf und mit B wieder zu
        gruppe.index = [getattr(w, "action", "") for w in gruppe.widgets].index("settings")
        cp.mehrmals(pad, rennen, A)
        assert rennen._pause_view == "settings"
        cp.mehrmals(pad, rennen, B)
        assert rennen._pause_view == "main" and rennen.paused
        # Rennstand auf, B zurück
        rennen._pause_group.index = [getattr(w, "action", "")
                                     for w in rennen._pause_group.widgets].index("standings")
        cp.mehrmals(pad, rennen, A)
        assert rennen._pause_view == "standings"
        cp.mehrmals(pad, rennen, B)
        assert rennen._pause_view == "main"
        # Fortsetzen
        rennen._pause_group.index = 0
        cp.mehrmals(pad, rennen, A)
        assert not rennen.paused
    finally:
        spielhilfe.alles_schliessen()


# ---------------------------------------------------------------------------
# Online-Strecken (Tauschbörse)
# ---------------------------------------------------------------------------

from tests.test_strecken_client import (FalscheApi, _eigene_ablegen, _eintrag,  # noqa: E402
                                        _seite as _strecken_seite, ordner)  # noqa: E402,F401
from tests.strecken_hilfe import rundkurs  # noqa: E402


def test_strecken_alles_ist_erreichbar(ordner, pad, monkeypatch):
    api = FalscheApi([_eintrag(n) for n in range(6)])
    st, _sm = _strecken_seite(api)
    mit = cp.Zeichenmitschrift(monkeypatch)
    _render(st)
    assert cp.nicht_im_fokus(mit, [st.gruppe]) == []
    assert cp.erreichbarkeit(pad, st, st.gruppe) == []


def test_strecken_fokus_ist_sichtbar(ordner, pad):
    api = FalscheApi([_eintrag(n) for n in range(6)])
    st, _sm = _strecken_seite(api)
    bedienbar = [i for i, w in enumerate(st.gruppe.widgets) if w.focusable]
    bilder = set()
    for i in bedienbar:
        st.gruppe.index = i
        bilder.add(_render(st))
    assert len(bilder) == len(bedienbar)


def test_strecken_herunterladen_und_melden_mit_dem_pad(ordner, pad):
    api = FalscheApi([_eintrag(n) for n in range(3)])
    st, _sm = _strecken_seite(api)
    st.gruppe.index = st.gruppe.widgets.index(st.zeilen[1])
    cp.mehrmals(pad, st, A)                          # Zeile wählen
    assert st.auswahl == 1
    st.gruppe.index = st.gruppe.widgets.index(st.b_aktion)
    cp.mehrmals(pad, st, A)
    st.update(0.0)
    assert any(a[0] == "holen" for a in api.aufrufe), api.aufrufe
    # Melden: Dialog, A = Ja
    st._knoepfe_aktualisieren()
    st.gruppe.index = st.gruppe.widgets.index(st.b_melden)
    cp.mehrmals(pad, st, A)
    assert st.dialog is not None, "Melden fragt nicht nach"
    cp.mehrmals(pad, st, B)                          # B = Abbrechen
    assert st.dialog is None and not api.gemeldet
    st.gruppe.index = st.gruppe.widgets.index(st.b_melden)
    cp.mehrmals(pad, st, A, A)                       # Ja
    st.update(0.0)
    assert api.gemeldet


def test_strecken_suchen_mit_der_bildschirmtastatur(ordner, pad):
    api = FalscheApi([_eintrag(n) for n in range(3)])
    st, _sm = _strecken_seite(api)
    st.gruppe.index = st.gruppe.widgets.index(st.suchfeld)
    cp.mehrmals(pad, st, A)
    assert st.osk is not None, "A auf dem Suchfeld öffnet keine Tastatur"
    st.osk.row, st.osk.col = 0, 0
    cp.mehrmals(pad, st, A, START)
    assert st.osk is None and st.suchfeld.text


def test_strecken_hochladen_mit_dem_pad(ordner, pad):
    _eigene_ablegen(ordner, rundkurs(5, 4, name="Meine Runde"), "meine_runde.json")
    api = FalscheApi([_eintrag(1)])
    st, _sm = _strecken_seite(api)
    st.gruppe.index = st.gruppe.widgets.index(st.b_modus)
    cp.mehrmals(pad, st, A)                          # Eigene hochladen
    assert st.modus == "eigene"
    zeile = next(z for z in st.zeilen if z.eintrag)
    st.gruppe.index = st.gruppe.widgets.index(zeile)
    cp.mehrmals(pad, st, A)
    st.gruppe.index = st.gruppe.widgets.index(st.b_aktion)
    cp.mehrmals(pad, st, A)
    assert st.dialog is not None, "Hochladen fragt nicht nach"
    cp.mehrmals(pad, st, A)                          # Hochladen
    st.update(0.0)
    assert api.hochgeladen


def test_strecken_y_wechselt_die_ansicht_und_b_geht_zurueck(ordner, pad):
    api = FalscheApi([_eintrag(1)])
    st, sm = _strecken_seite(api)
    cp.mehrmals(pad, st, Y)
    assert st.modus == "eigene"
    cp.mehrmals(pad, st, B)                          # erst zur Liste
    assert st.modus == "liste"
    cp.mehrmals(pad, st, B)                          # dann hinaus
    assert sm.zurueck_aufrufe == 1


def test_strecken_seiten_blaettern_mit_den_schultertasten(ordner, pad):
    api = FalscheApi([_eintrag(n) for n in range(20)])
    st, _sm = _strecken_seite(api)
    cp.mehrmals(pad, st, RB)
    assert st.seite == 1
    cp.mehrmals(pad, st, LB)
    assert st.seite == 0
