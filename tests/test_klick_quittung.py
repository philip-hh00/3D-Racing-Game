"""Jeder Klick, der etwas bewirkt, wird hörbar quittiert (Playtest 03.08.2026).

Gemeldet: „Klick-Sound wird nicht bei jedem Klick auf einen Button oder ein
Textfeld abgespielt."

Die Ursache war die Bauweise, nicht eine vergessene Zeile. Der Klang hing allein
an :class:`~src.ui.focus.FocusGroup`; jede Seite mit **eigenen** Klickflächen —
die Farbfelder der Werkstatt, Fahrzeug- und Streckenkacheln, die Pfeilknöpfe der
Werkstatt, die Regler der Laborseiten — lief daran vorbei. Und ein Textfeld nahm
den Klick an, ohne eine Aktion zu melden, blieb also auch still.

Geprüft wird deshalb nicht „ist an Stelle X ein Aufruf", sondern die Wirkung:
ein Klick, den eine Seite verarbeitet, muss die Klangzählung erhöhen. Ein Klick
ins Leere darf sie nicht erhöhen — eine Quittung für nichts wäre genauso falsch.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import lack, profile, sfx, version  # noqa: E402
from src.core.settings import SCREEN_WIDTH  # noqa: E402
from src.ui.focus import FocusGroup  # noqa: E402
from src.ui.widgets import Button, Stepper, TextInput  # noqa: E402


@pytest.fixture(autouse=True)
def stiller_mixer(monkeypatch):
    """Gezählt wird, nicht abgespielt — der Testlauf hat kein Audiogerät."""
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)


def klick(pos, button: int = 1) -> pygame.event.Event:
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


class Zaehler:
    """Merkt sich den Stand vor dem Klick und sagt, wie oft es klang."""

    def __enter__(self):
        self._vorher = sfx.klang_zaehler()
        return self

    def __exit__(self, *_):
        return False

    @property
    def klaenge(self) -> int:
        return sfx.klang_zaehler() - self._vorher


# ---------------------------------------------------------------------------
# FocusGroup: der Fall, der explizit gemeldet wurde
# ---------------------------------------------------------------------------
def test_klick_auf_ein_textfeld_klingt():
    """Ein Textfeld meldet keine Aktion — es nimmt den Klick nur an, um den
    Schreibfokus zu bekommen. Vorher blieb es deshalb still."""
    feld = TextInput(pygame.Rect(100, 100, 300, 50), "Name")
    gruppe = FocusGroup([feld])
    with Zaehler() as z:
        gruppe.handle_event(klick(feld.rect.center))
    assert z.klaenge == 1


def test_klick_auf_einen_knopf_klingt_genau_einmal():
    knopf = Button(pygame.Rect(0, 0, 200, 50), "Los", "los")
    gruppe = FocusGroup([knopf])
    with Zaehler() as z:
        assert gruppe.handle_event(klick(knopf.rect.center)) == "los"
    assert z.klaenge == 1


def test_klick_auf_einen_gesperrten_knopf_klingt_abweisend():
    knopf = Button(pygame.Rect(0, 0, 200, 50), "Los", "los", enabled=False)
    gruppe = FocusGroup([knopf])
    with Zaehler() as z:
        assert gruppe.handle_event(klick(knopf.rect.center)) is None
    assert z.klaenge == 1


def test_klick_ins_leere_bleibt_still():
    knopf = Button(pygame.Rect(0, 0, 200, 50), "Los", "los")
    gruppe = FocusGroup([knopf])
    with Zaehler() as z:
        gruppe.handle_event(klick((900, 900)))
    assert z.klaenge == 0


def test_der_stepper_klingt_bei_jedem_pfeil_und_nicht_auf_der_beschriftung():
    s = Stepper(pygame.Rect(100, 100, 560, 60), "Sprache", ["de", "en"], 0)
    gruppe = FocusGroup([s])
    zurueck, vor = s._klickhaelften()
    for pos in (zurueck.center, vor.center):
        with Zaehler() as z:
            gruppe.handle_event(klick(pos))
        assert z.klaenge == 1, pos
    # Die Beschriftung loest nichts aus, holt aber den Fokus — eine leise
    # Quittung, keine zwei.
    with Zaehler() as z:
        gruppe.handle_event(klick((s.rect.x + 20, s.rect.centery)))
    assert z.klaenge == 1


def test_bewegen_ohne_klick_bleibt_still():
    """Klänge jeder Schritt, hieße keiner mehr etwas."""
    knopf = Button(pygame.Rect(0, 0, 200, 50), "Los", "los")
    zweiter = Button(pygame.Rect(0, 60, 200, 50), "Zwei", "zwei")
    gruppe = FocusGroup([knopf, zweiter])
    with Zaehler() as z:
        gruppe.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=zweiter.rect.center))
        gruppe.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DOWN,
                                               unicode="", mod=0))
    assert z.klaenge == 0


# ---------------------------------------------------------------------------
# klick_quittieren: das Netz von oben
# ---------------------------------------------------------------------------
def test_das_netz_klingt_nur_wenn_noch_nichts_klang():
    e = klick((10, 10))
    with Zaehler() as z:
        vorher = sfx.klang_zaehler()
        sfx.klick_quittieren(e, vorher)
    assert z.klaenge == 1

    with Zaehler() as z:
        vorher = sfx.klang_zaehler()
        sfx.menue("ausgeloest")          # die Seite hat selbst geklungen
        sfx.klick_quittieren(e, vorher)
    assert z.klaenge == 1, "es darf nicht doppelt klingen"


@pytest.mark.parametrize("event", [
    pygame.event.Event(pygame.MOUSEMOTION, pos=(1, 1)),
    pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1),
    pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0),
    pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(1, 1), button=3),
])
def test_das_netz_gilt_nur_fuer_den_linken_mausklick(event):
    with Zaehler() as z:
        sfx.klick_quittieren(event, sfx.klang_zaehler())
    assert z.klaenge == 0


def test_ein_unbekannter_anlass_klingt_nicht_und_zaehlt_nicht():
    with Zaehler() as z:
        sfx.menue("gibtsnicht")
    assert z.klaenge == 0


# ---------------------------------------------------------------------------
# Die Seiten mit eigenen Klickflächen
# ---------------------------------------------------------------------------
@pytest.fixture
def spielstand(monkeypatch):
    monkeypatch.setattr(version, "IS_RELEASE", False)
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    p.statistik = {}
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    return p


def test_die_werkstatt_beantwortet_ihre_eigenen_flaechen(spielstand):
    """Farbfelder, Fahrzeugkacheln und Pfeilknöpfe sind keine Widgets — sie
    liefen an der FocusGroup vorbei und blieben still."""
    from src.states.menu.werkstatt_page import WerkstattPage
    seite = WerkstattPage()
    seite.enter(object())
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    seite.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, 1080 - 108))

    flaechen = [("Farbfeld", seite._farb_rects[0][1]),
                ("Kachel", seite._kachel_rects[1][1]),
                ("Drehknopf", seite._dreh_rects[0])]
    for name, r in flaechen:
        with Zaehler() as z:
            verarbeitet = seite.handle_event(klick(r.center))
            assert verarbeitet, name
            # So sieht es die Schale: verarbeitet, also quittieren.
            sfx.klick_quittieren(klick(r.center), z._vorher)
        assert z.klaenge >= 1, name


def test_gesperrter_lack_klingt_abweisend(monkeypatch, spielstand):
    from src.states.menu.werkstatt_page import WerkstattPage
    monkeypatch.setattr(version, "IS_RELEASE", True)
    seite = WerkstattPage()
    seite.enter(object())
    schirm = pygame.Surface((SCREEN_WIDTH, 1080))
    seite.finish_index = [f["key"] for f in lack.finishes()].index("neon") + 1
    seite.draw(schirm, pygame.Rect(0, 108, SCREEN_WIDTH, 1080 - 108))
    keys = [f["key"] for f in lack.farben()]
    kasten = dict(seite._farb_rects)[keys.index("magenta")]
    with Zaehler() as z:
        seite.handle_event(klick(kasten.center))
    assert z.klaenge == 1
    assert seite._meldung, "und die Meldung dazu"


# ---------------------------------------------------------------------------
# Dass das Netz überhaupt gespannt ist
# ---------------------------------------------------------------------------
def test_die_menueschale_quittiert_verarbeitete_klicks():
    from src.states.menu_shell_state import MenuShellState

    class Seite:
        def handle_event(self, event):
            return True

        def hides_tab_bar(self):
            return True

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = [Seite()]
    shell.tab = 0
    with Zaehler() as z:
        shell._handle_page_event(klick((500, 500)))
    assert z.klaenge == 1


def test_die_menueschale_quittiert_nichts_was_die_seite_liegen_laesst():
    from src.states.menu_shell_state import MenuShellState

    class Seite:
        def handle_event(self, event):
            return False

        def hides_tab_bar(self):
            return True

    shell = MenuShellState.__new__(MenuShellState)
    shell.page_stack = [Seite()]
    shell.tab = 0
    with Zaehler() as z:
        shell._handle_page_event(klick((500, 500)))
    assert z.klaenge == 0
