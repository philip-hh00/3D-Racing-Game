"""Lackfreischaltung und ihre Anzeige in der Werkstatt (E5 Schritt 4 und 5).

Zwei Dinge dürfen hier nicht schiefgehen, und beide fallen im Spiel erst spät
auf: eine Staffelgrenze, die um eins danebenliegt (dann ist Metallic bei 19
Rennen frei oder bei 21 noch gesperrt), und eine Anzeige, die „gesperrt" sagt,
ohne zu verraten, wie weit es noch ist — genau das, was §E2 abschafft.

Geprüft wird deshalb an den Kanten (4/5 und 19/20) und daran, dass die Werkstatt
ihre Zahlen aus :mod:`src.core.lack` bezieht statt selbst zu rechnen.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import lack, profile, statistik, version  # noqa: E402
from src.core.settings import SCREEN_WIDTH  # noqa: E402
from src.states.menu.werkstatt_page import WerkstattPage, _ausgegraut  # noqa: E402


@pytest.fixture
def ausgeliefert(monkeypatch):
    """Wie im gepackten Bündel — sonst ist ohnehin alles frei (E1)."""
    monkeypatch.setattr(version, "IS_RELEASE", True)
    assert not statistik.alles_frei()


@pytest.fixture
def spielstand(monkeypatch, ausgeliefert):
    """Ein Profil, dessen Zähler der Test frei setzen kann."""
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


def _zaehler(p, **werte) -> None:
    p.statistik.update(werte)


# ---------------------------------------------------------------------------
# Die Staffelgrenzen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rennen,erste,alle", [
    (0, False, False),
    (4, False, False),
    (5, True, False),      # die drei ersten Farben
    (19, True, False),
    (20, True, True),      # jetzt alle zwölf
    (99, True, True),
])
def test_metallic_staffelt_nach_rennen(spielstand, rennen, erste, alle):
    _zaehler(spielstand, rennen=rennen)
    assert lack.ist_freigeschaltet("metallic:rubinrot") is erste
    assert lack.ist_freigeschaltet("metallic:tuerkis") is alle


@pytest.mark.parametrize("siege,erste,alle", [(4, False, False), (5, True, False),
                                              (20, True, True)])
def test_neon_haengt_an_siegen_nicht_an_rennen(spielstand, siege, erste, alle):
    _zaehler(spielstand, rennen=200, siege=siege)
    assert lack.ist_freigeschaltet("neon:kobaltblau") is erste
    assert lack.ist_freigeschaltet("neon:magenta") is alle


@pytest.mark.parametrize("ghosts,erste,alle", [(0, False, False), (1, True, False),
                                               (3, True, True)])
def test_zweifarbig_zaehlt_strecken_nicht_versuche(spielstand, ghosts, erste, alle):
    """Dreimal derselbe Ghost ist nicht dasselbe wie drei Strecken (§E1)."""
    _zaehler(spielstand, ghosts_geschlagen=["oval", "desert", "berg"][:ghosts])
    assert lack.ist_freigeschaltet("zweifarbig:perlweiss") is erste
    assert lack.ist_freigeschaltet("zweifarbig:violett") is alle


def test_dreimal_derselbe_ghost_reicht_nicht(spielstand):
    """Gezählt wird die Liste; dass dieselbe Strecke nur einmal hineinkommt,
    entscheidet ``statistik``, nicht der Lack — sonst gälten für Erfolge und
    Freischaltungen zwei verschiedene Regeln auf demselben Feld."""
    for _ in range(3):
        statistik.ghost_geschlagen("oval")
    assert spielstand.statistik["ghosts_geschlagen"] == ["oval"]
    assert lack.ist_freigeschaltet("zweifarbig:violett") is False


def test_werkslack_und_standard_sind_immer_frei(spielstand):
    assert lack.ist_freigeschaltet(lack.WERK)
    for f in lack.farben():
        assert lack.ist_freigeschaltet(lack.kennung("standard", f["key"]))


def test_die_drei_ersten_farben_stehen_in_der_datei():
    """Welche drei es sind, ist Geschmack und gehört nicht in den Code (§E2)."""
    assert lack.erste_farben() == ["rubinrot", "kobaltblau", "perlweiss"]
    keys = {f["key"] for f in lack.farben()}
    assert set(lack.erste_farben()) <= keys


def test_unsinn_sperrt_nicht_aus(spielstand):
    """Ein verbogenes Profil oder ein alter Build soll Werkslack ergeben."""
    for kenn in ("", "quatsch", "metallic:gibtsnicht", "gibtsnicht:rubinrot", None):
        assert lack.fortschritt(kenn) == (0, 0)
        assert lack.ist_freigeschaltet(kenn) is True


def test_aus_dem_quelltext_gestartet_ist_alles_frei(monkeypatch, spielstand):
    """Beim Entwickeln will niemand erst zwanzig Rennen fahren (§E1)."""
    monkeypatch.setattr(version, "IS_RELEASE", False)
    assert lack.ist_freigeschaltet("neon:magenta") is True
    # Der Fortschritt bleibt ehrlich — nur die Sperre fällt weg.
    assert lack.fortschritt("neon:magenta") == (0, 20)


# ---------------------------------------------------------------------------
# Die Zahl, die man sehen soll
# ---------------------------------------------------------------------------
def test_fortschritt_nennt_zaehler_und_ziel(spielstand):
    _zaehler(spielstand, rennen=7)
    assert lack.fortschritt("metallic:tuerkis") == (7, 20)
    assert lack.fortschritt_text("metallic:tuerkis") == "7 / 20 Rennen"


def test_fortschritt_wird_am_ziel_gekappt(spielstand):
    """„23 / 20" liest sich wie ein Fehler."""
    _zaehler(spielstand, rennen=23)
    assert lack.fortschritt_text("metallic:tuerkis") == "20 / 20 Rennen"


def test_ohne_bedingung_keine_zahl(spielstand):
    assert lack.fortschritt_text("standard:rubinrot") == ""
    assert lack.fortschritt_text(lack.WERK) == ""


def test_jeder_zaehler_hat_eine_vorlage():
    """Sonst stünde in der Werkstatt „7 / 20" ohne Einheit."""
    for fin in lack.finishes():
        staffel = fin.get("freischaltung")
        if isinstance(staffel, dict):
            assert staffel["zaehler"] in lack._VORLAGE


def test_die_englische_uebersetzung_kennt_die_vorlagen():
    import json
    with open(os.path.join("data", "i18n", "en.json"), encoding="utf-8") as f:
        tabelle = json.load(f)
    for vorlage in lack._VORLAGE.values():
        assert vorlage in tabelle, vorlage
        assert tabelle[vorlage].format(a=1, b=2).startswith("1 / 2")


# ---------------------------------------------------------------------------
# Werkstatt
# ---------------------------------------------------------------------------
@pytest.fixture
def werkstatt(spielstand):
    s = WerkstattPage()
    s.enter(object())
    return s


def _zeichnen(s: WerkstattPage) -> pygame.Surface:
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    s.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, 1080 - 108))
    return schirm


def _finish_waehlen(s: WerkstattPage, key: str) -> None:
    s.finish_index = [f["key"] for f in lack.finishes()].index(key) + 1


def _farbe_waehlen(s: WerkstattPage, key: str) -> None:
    s.farb_index = [f["key"] for f in lack.farben()].index(key)


def test_die_werkstatt_fragt_je_farbe(werkstatt, spielstand):
    """Die Staffelung ist je Farbe verschieden — eine Antwort fürs ganze Finish
    wäre für neun von zwölf Feldern falsch."""
    _zaehler(spielstand, rennen=7)
    _finish_waehlen(werkstatt, "metallic")
    assert werkstatt._frei("rubinrot") is True
    assert werkstatt._frei("tuerkis") is False


def test_bei_werkslack_ist_kein_feld_gesperrt(werkstatt, spielstand):
    """Ein Klick aufs Feld springt von Werkslack nach Standard — gefragt werden
    muss also nach Standard, nicht nach Metallic."""
    werkstatt.finish_index = 0
    assert all(werkstatt._frei(f["key"]) for f in lack.farben())


def test_gesperrte_farbe_wird_nicht_ins_profil_geschrieben(werkstatt, spielstand):
    """Auf ``_speichern`` statt ``_uebernehmen``: seit dem 04.08.2026 schreibt
    nur der Speichern-Knopf, und die Sperre muss genau dort greifen."""
    _zaehler(spielstand, rennen=7)
    _finish_waehlen(werkstatt, "metallic")
    _farbe_waehlen(werkstatt, "tuerkis")
    assert werkstatt._speichern() is False
    assert profile.current().paint(werkstatt._key()) == lack.WERK
    assert "7 / 20 Rennen" in werkstatt._meldung


def test_freie_farbe_wird_uebernommen(werkstatt, spielstand):
    _zaehler(spielstand, rennen=7)
    _finish_waehlen(werkstatt, "metallic")
    _farbe_waehlen(werkstatt, "rubinrot")
    assert werkstatt._speichern() is True
    assert profile.current().paint(werkstatt._key()) == "metallic:rubinrot"
    assert werkstatt._meldung == ""


def test_klick_auf_gesperrtes_feld_meldet_den_stand(werkstatt, spielstand):
    _zaehler(spielstand, rennen=7)
    _finish_waehlen(werkstatt, "metallic")
    _zeichnen(werkstatt)
    keys = [f["key"] for f in lack.farben()]
    kasten = dict(werkstatt._farb_rects)[keys.index("tuerkis")]
    werkstatt.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                              pos=kasten.center))
    assert werkstatt._meldung and "7 / 20 Rennen" in werkstatt._meldung
    assert profile.current().paint(werkstatt._key()) == lack.WERK


def test_gesperrtes_feld_wird_ausgegraut_gezeichnet(werkstatt, spielstand):
    """Sichtbar, aber sichtbar nicht dran: das Feld verliert Farbe, behält aber
    genug davon, dass man erkennt, worauf man hinarbeitet."""
    _zaehler(spielstand, rennen=7)
    _finish_waehlen(werkstatt, "metallic")
    schirm = _zeichnen(werkstatt)
    keys = [f["key"] for f in lack.farben()]
    felder = dict(werkstatt._farb_rects)
    frei = schirm.get_at(felder[keys.index("rubinrot")].center)[:3]
    sperr = schirm.get_at(felder[keys.index("tuerkis")].center)[:3]
    assert sum(frei) > sum(sperr), "das gesperrte Feld muss dunkler sein"
    assert max(sperr) - min(sperr) < max(frei) - min(frei), "und blasser"
    assert sum(sperr) > 30, "aber nicht schwarz"


def test_ausgegraut_bleibt_im_farbraum():
    for rgb in ((0, 0, 0), (255, 255, 255), (200, 30, 40), (20, 180, 180)):
        assert all(0 <= k <= 255 for k in _ausgegraut(rgb))


def test_alle_felder_farbig_wenn_alles_frei(werkstatt, spielstand, monkeypatch):
    monkeypatch.setattr(version, "IS_RELEASE", False)
    _finish_waehlen(werkstatt, "neon")
    assert all(werkstatt._frei(f["key"]) for f in lack.farben())


def test_die_werkstatt_rechnet_nicht_selbst(werkstatt, spielstand):
    """Stünde in der Seite eine eigene Grenze, liefe sie irgendwann gegen
    ``lacke.json`` — der Hinweis muss aus :mod:`lack` kommen."""
    _zaehler(spielstand, rennen=12)
    _finish_waehlen(werkstatt, "metallic")
    _farbe_waehlen(werkstatt, "tuerkis")
    assert lack.fortschritt_text(werkstatt._kennung()) == "12 / 20 Rennen"
    _zeichnen(werkstatt)          # darf nicht abstürzen


def test_zeichnen_aendert_die_statistik_nicht(werkstatt, spielstand):
    _zaehler(spielstand, rennen=7, siege=2)
    statistik.werte()             # Vorgabefelder ergaenzen — das ist kein Zaehlen
    vorher = dict(spielstand.statistik)
    for key in ("standard", "metallic", "neon", "zweifarbig"):
        _finish_waehlen(werkstatt, key)
        _zeichnen(werkstatt)
    assert spielstand.statistik == vorher


# ---------------------------------------------------------------------------
# Rückweg (Playtest 03.08.2026)
# ---------------------------------------------------------------------------
def test_esc_nimmt_denselben_weg_wie_der_zurueck_knopf(werkstatt):
    """Gemeldet: „zurück in der Werkstatt geht auch zurück zur Lobby, aber ESC
    führt ins Hauptmenü und nicht zur Lobby."

    Zwei Wege für dieselbe Absicht. Die Shell hätte hier ``pop_page()`` gerufen,
    und der Kurzweg aus der Fahrzeugauswahl hat nichts, was sie abheben könnte.
    """
    class Maschine:
        def __init__(self):
            self.ziel = None

        def transition(self, name, **kwargs):
            self.ziel = (name, kwargs)

    class Schale:
        def __init__(self):
            self.state_machine = Maschine()
            self.gepoppt = 0

        def pop_page(self):
            self.gepoppt += 1

    schale = Schale()
    werkstatt.shell = schale
    werkstatt.rueckweg = ("car_select", {"picker": "p1"})
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    assert werkstatt.handle_event(esc) is True, "ESC muss verbraucht werden"
    ziel, argumente = schale.state_machine.ziel
    assert ziel == "car_select"
    assert argumente["picker"] == "p1"
    # Seit 05.08.2026 reist zusätzlich das Fahrzeug mit, das hier zuletzt auf
    # der Bühne stand. Geprüft wird hier der Weg, nicht die Ladung.
    assert argumente["vehicle_config"] == werkstatt._key()
    assert schale.gepoppt == 0


def test_esc_ohne_kurzweg_geht_eine_ebene_hoch(werkstatt):
    """Als normale Menüseite bleibt es beim alten Verhalten."""
    class Schale:
        def __init__(self):
            self.gepoppt = 0

        def pop_page(self):
            self.gepoppt += 1

    schale = Schale()
    werkstatt.shell = schale
    werkstatt.rueckweg = None
    esc = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0)
    assert werkstatt.handle_event(esc) is True
    assert schale.gepoppt == 1


def test_controller_b_nimmt_denselben_weg(werkstatt):
    """Der Gamepad-Manager übersetzt B in ein synthetisches ESC — es darf nicht
    an einer Prüfung auf ``synthetic`` vorbeilaufen."""
    class Maschine:
        ziel = None

        def transition(self, name, **kwargs):
            Maschine.ziel = (name, kwargs)

    class Schale:
        state_machine = Maschine()

        def pop_page(self):
            raise AssertionError("hätte den Kurzweg nehmen müssen")

    werkstatt.shell = Schale()
    werkstatt.rueckweg = ("car_select", {})
    b = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="", mod=0,
                           synthetic=True, pad_button=1)
    assert werkstatt.handle_event(b) is True
    ziel, argumente = Maschine.ziel
    assert ziel == "car_select"
    assert argumente["vehicle_config"] == werkstatt._key()


def test_der_knopf_in_der_fahrzeugauswahl_heisst_werkstatt():
    """Ein Knopf soll heißen, wohin er führt — in der Werkstatt steht mehr als
    die Lackwahl."""
    import json
    from src.core.i18n import tr
    quelle = open(os.path.join(_ROOT, "src", "states", "car_select_state.py"),
                  encoding="utf-8").read()
    assert 'tr("Werkstatt")' in quelle
    assert 'tr("Lackieren")' not in quelle
    with open(os.path.join("data", "i18n", "en.json"), encoding="utf-8") as f:
        assert "Werkstatt" in json.load(f)
    assert tr("Werkstatt") == "Werkstatt", "deutsch bleibt deutsch"
