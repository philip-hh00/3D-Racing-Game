"""Die Pfeile ‹ und › jedes Steppers reagieren dort, wo sie gezeichnet sind.

Gemeldet (Produktinhaber, 1.1.0): Bei den erweiterten Grafikeinstellungen geht
der rechte Pfeil, der linke nicht — „die Klickfläche liegt neben dem Zeichen".

Die Fläche lag nicht daneben. Die Seite hat einen Klick im „Erweitert"-Overlay
**doppelt** verarbeitet: erst über die Fokusgruppe (``handle_click``: ‹ = −1,
› = +1), danach noch einmal über ``activate()`` (immer +1). Ein Klick auf ‹
ging damit −1 und +1 und blieb auf dem alten Wert stehen; ein Klick auf ›
sprang um zwei. Dazu kam, dass der Regler im Overlay gar nicht im Puffer
ankam: ``_grafik_aendern`` suchte ihn in der Hauptseite statt im Overlay.

Geprüft wird deshalb am Ende, was der Spieler sieht: **jeder** Stepper jeder
Einstellungskategorie (und des Overlays), angeklickt genau in der Mitte des
gezeichneten Zeichens, in einem 16:9-Fenster und in 16:10-Fenstern, in denen
die Menüs im sicheren Bereich mit Versatz und Maßstab liegen.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import display, profile, sfx  # noqa: E402
from src.states.menu.settings_page import SettingsPage  # noqa: E402
from src.ui.widgets import Stepper  # noqa: E402

FENSTER = [(1920, 1080), (2560, 1600), (1920, 1200), (2560, 1080)]


@pytest.fixture
def seite(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    monkeypatch.setattr(sfx, "menue", lambda *a, **k: None)
    s = SettingsPage()
    s.enter(type("Schale", (), {"state_machine": None})())
    return s


def _fenster(monkeypatch, groesse):
    monkeypatch.setattr(display, "_fenstergroesse", lambda: groesse)


def _klick(seite, monkeypatch_groesse, punkt):
    """Ein Linksklick auf den *sicheren* Punkt, wie ihn die Maus im Fenster erzeugt."""
    abb = display._abbildung()
    if abb is None:
        fpos = punkt
    else:
        sx, sy, ox, oy = abb
        # Mitte des Bildpunkts, damit das Abrunden der Rückrechnung nichts kippt.
        fpos = ((punkt[0] + ox + 0.5) / sx, (punkt[1] + oy + 0.5) / sy)
    ereignis = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                  {"pos": (int(fpos[0]), int(fpos[1])), "button": 1})
    ereignis = display.remap_mouse_events([ereignis])[0]
    return seite.handle_event(ereignis)


def _steppers(gruppe) -> list[Stepper]:
    return [w for w in (gruppe.widgets if gruppe else []) if isinstance(w, Stepper)]


def _alle_stepper(seite):
    """``(Name, Stepper-Liste-Funktion)`` je Kategorie und fürs Overlay."""
    for i, name in enumerate(seite.categories):
        yield name, i, False
    yield "Video/Erweitert", seite.categories.index("Video"), True


def _pruefen(seite, monkeypatch, name, kat, erweitert):
    seite.cat = kat
    seite._build_content()
    seite._advanced_graphics = None
    if erweitert:
        seite._dispatch("grafik_advanced")
        gruppe = seite._advanced_graphics._content_group
    else:
        gruppe = seite._content_group
    steppers = _steppers(gruppe)
    for s in steppers:
        n = len(s.options)
        if n < 2:
            continue
        links, rechts = s._arrow_rects()
        for glyph, d in ((links, -1), (rechts, +1)):
            s.index = n // 2
            vorher = s.index
            _klick(seite, monkeypatch, glyph.center)
            assert s.index == (vorher + d) % n, (
                f"{name}: {s.label!r} {'‹' if d < 0 else '›'} "
                f"ging von {vorher} auf {s.index}, erwartet {(vorher + d) % n}")
    return len(steppers)


@pytest.mark.parametrize("groesse", FENSTER)
def test_jeder_pfeil_jedes_steppers_reagiert_in_der_mitte_des_zeichens(
        seite, monkeypatch, groesse):
    _fenster(monkeypatch, groesse)
    gesamt = 0
    for name, kat, erweitert in _alle_stepper(seite):
        gesamt += _pruefen(seite, monkeypatch, name, kat, erweitert)
    # Allgemein 1, Video 6, Audio 4, Fahrhilfen 4, Overlay 17
    assert gesamt >= 30, gesamt


def test_ein_klick_im_overlay_zaehlt_genau_einmal(seite, monkeypatch):
    _fenster(monkeypatch, (1920, 1080))
    seite.cat = seite.categories.index("Video")
    seite._build_content()
    seite._dispatch("grafik_advanced")
    s = next(w for w in _steppers(seite._advanced_graphics._content_group)
             if w.action == "grafik_schatten_px")
    s.index = 2
    links, rechts = s._arrow_rects()
    _klick(seite, monkeypatch, rechts.center)
    assert s.index == 3
    _klick(seite, monkeypatch, links.center)
    _klick(seite, monkeypatch, links.center)
    assert s.index == 1


def test_ein_regler_im_overlay_landet_im_puffer_und_setzt_die_stufe_auf_eigen(
        seite, monkeypatch):
    _fenster(monkeypatch, (1920, 1080))
    seite.cat = seite.categories.index("Video")
    seite._build_content()
    seite._dispatch("grafik_advanced")
    s = next(w for w in _steppers(seite._advanced_graphics._content_group)
             if w.action == "grafik_schatten_px")
    vorher = seite._grafik_werte()["schatten_px"]
    roh = seite._werte["grafik_schatten_px"]
    s.index = roh.index(vorher)
    links, _rechts = s._arrow_rects()
    _klick(seite, monkeypatch, links.center)
    assert seite._pending["grafik"]["schatten_px"] == roh[(roh.index(vorher) - 1) % len(roh)]
    assert seite._pending["grafik"]["stufe"] == "eigen"


# ---------------------------------------------------------------------------
# Andere Seiten mit Steppern: Lobby (die meisten Stepper des Spiels)
# ---------------------------------------------------------------------------
def test_die_pfeile_der_lobby_stepper_reagieren_in_der_mitte_des_zeichens(monkeypatch):
    from src.core import grand_prix
    from src.entities.vehicle_factory import VehicleFactory
    from src.net import server_probe
    from src.states.menu import online_lobby_page as olp
    from tests import spielhilfe
    from tests.test_layout_regeln import _ShellAttrappe

    spielhilfe.aufbau_bewahren(monkeypatch)
    VehicleFactory.load_all_configs()
    monkeypatch.setattr(server_probe, "start", lambda: None)
    monkeypatch.setattr(server_probe, "statuses", lambda: [])
    monkeypatch.setattr(sfx, "menue", lambda *a, **k: None)
    grand_prix.cancel()
    try:
        seite = olp.OnlineLobbyPage()
        seite.enter(_ShellAttrappe())
        seite._is_host = True
        seite._view = olp._LOBBY
        seite._players = [
            {"slot": 0, "name": "Host", "lobby_ready": False, "vehicle": "rookie"},
            {"slot": 1, "name": "Gast", "lobby_ready": False, "vehicle": "drifter"},
        ]
        seite._refresh_focus_group()
        gruppe = seite._lobby_group
        gepruft = 0
        for s in _steppers(gruppe):
            n = len(s.options)
            if n < 2 or not s.enabled:
                continue
            links, rechts = s._arrow_rects()
            for glyph, d in ((links, -1), (rechts, +1)):
                s.index = n // 2
                vorher = s.index
                gruppe.handle_event(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, {"pos": glyph.center, "button": 1}))
                assert s.index == (vorher + d) % n, (s.label, s.action, d)
                gepruft += 1
        assert gepruft >= 6, gepruft
    finally:
        grand_prix.cancel()
