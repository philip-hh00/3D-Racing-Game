"""Einstellungen: Kategorien wählt nur der Klick, und die Info-Seite bleibt
lesbar (Playtest 05.08.2026).

Zwei Funde, eine Datei:

(1) „Mit Maus steuerung sehr anstrengend durch die Einstellungsuntermenüs zu
wechseln da hovern mit der Maus über dem Untermenü schon die Seite
verändert." — ``handle_event`` wechselte die Kategorie schon bei
``MOUSEMOTION``; ein Vorbeistreifen der Kategorienspalte reichte, um die
Seite umzuschalten. Jetzt merkt sich die Bewegung nur noch die Hover-Position
(für die leichte Fuellung in ``draw``); ausgewaehlt wird ausschliesslich per
Klick.

(2) „Ankündigungen Überschrift wird von den Ankündigungen selbst überlagert."
— die Box in ``_draw_info`` begann 46px unter der Überschrift, die
gerenderte Textfläche von "Ankündigungen" (HEADER-Größe) ist aber 50px hoch —
der Kasten schnitt vier Pixel in die Schrift. Und: "der Commit muss nicht
hinter der Version angezeigt werden" — die Info-Seite zeigte
``version_string()`` inklusive ``(abc1234)``, jetzt nur noch ``version.VERSION``.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.core import profile, version  # noqa: E402
from src.net import server_info  # noqa: E402
from src.states.menu.settings_page import SettingsPage  # noqa: E402
from src.ui import theme  # noqa: E402


@pytest.fixture
def seite(monkeypatch):
    p = profile.Profile(username="Testfahrer")
    p.save = lambda: None
    monkeypatch.setattr(profile, "_current", p, raising=False)
    monkeypatch.setattr(profile, "current", lambda: p)
    # Server-Info fest verdrahtet statt echtem Socket-Versuch — sonst haengt
    # jeder Testlauf am Verbindungsaufbau, und das Ergebnis waere zufaellig.
    monkeypatch.setattr(server_info, "fetch_info_async", lambda: None)
    monkeypatch.setattr(server_info, "get_cached", lambda: {
        "announcements": [
            {"id": "a1", "date": "2026-08-01",
             "title": {"de": "Testankuendigung"},
             "text": {"de": "Ein kurzer Ankuendigungstext zum Testen."}},
        ],
    })
    monkeypatch.setattr(server_info, "version_ok", lambda: None)
    s = SettingsPage()
    s.enter(type("Schale", (), {"state_machine": None})())
    return s


def _bewegung(pos):
    return pygame.event.Event(pygame.MOUSEMOTION, pos=pos, rel=(1, 1), buttons=(0, 0, 0))


def _klick(pos, button: int = 1):
    return pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button)


# ---------------------------------------------------------------------------
# (1) Kategorien: hovern markiert nur, erst der Klick wechselt
# ---------------------------------------------------------------------------
def test_hover_ueber_einer_anderen_kategorie_wechselt_nicht(seite):
    """Der Kern der Meldung: bloßes Überfahren darf die Seite nicht umschalten."""
    seite.cat = 0
    rects = seite._cat_rects()

    seite.handle_event(_bewegung(rects[2].center))

    assert seite.cat == 0, "Hovern hat trotzdem ausgewählt"


def test_hovern_ueber_jede_kategorie_laesst_die_wahl_unangetastet(seite):
    seite.cat = 1
    rects = seite._cat_rects()
    for r in rects:
        seite.handle_event(_bewegung(r.center))
        assert seite.cat == 1


def test_klick_auf_eine_andere_kategorie_wechselt(seite):
    seite.cat = 0
    rects = seite._cat_rects()

    seite.handle_event(_klick(rects[2].center))

    assert seite.cat == 2, "der Klick muss auswählen"


def test_hovern_baut_die_seite_nicht_neu_auf(seite):
    """Ein Nebeneffekt der alten Auswahl-per-Hover: jede Mausbewegung über der
    Spalte rief ``_build_content`` erneut auf. Jetzt bleibt das Widget-Objekt
    dasselbe, solange nicht geklickt wird."""
    seite.cat = 0
    seite._build_content()
    gruppe_vorher = seite._content_group
    rects = seite._cat_rects()

    seite.handle_event(_bewegung(rects[2].center))

    assert seite._content_group is gruppe_vorher


def test_klick_auf_die_bereits_gewaehlte_kategorie_bleibt_dort(seite):
    seite.cat = 3
    rects = seite._cat_rects()

    seite.handle_event(_klick(rects[3].center))

    assert seite.cat == 3


def test_hover_und_klick_verhalten_sich_ueber_alle_kategorien_gleich(seite):
    """Jede Nachbarkategorie einzeln geprüft, nicht nur eine feste Zielzeile."""
    rects = seite._cat_rects()
    for ziel in range(len(rects)):
        seite.cat = 0 if ziel != 0 else 1
        start = seite.cat
        seite.handle_event(_bewegung(rects[ziel].center))
        assert seite.cat == start, f"Hover auf Zeile {ziel} hat ausgewählt"
        seite.handle_event(_klick(rects[ziel].center))
        assert seite.cat == ziel, f"Klick auf Zeile {ziel} hat nicht ausgewählt"


# ---------------------------------------------------------------------------
# (2) Info-Seite: Überschrift und Kasten liegen nicht mehr übereinander
# ---------------------------------------------------------------------------
def _info_zeichnen(seite):
    """Zeichnet die Info-Seite und liefert (Header-Rect, Kasten-Rect, alle Texte)."""
    seite.cat = seite.categories.index("Info")

    text_rects: list[tuple[str, pygame.Rect]] = []
    orig_text = theme.text

    def erfassend_text(screen, s, size, color, pos, **kwargs):
        r = orig_text(screen, s, size, color, pos, **kwargs)
        text_rects.append((s, r))
        return r

    panel_rects: list[pygame.Rect] = []
    orig_panel = theme.panel

    def erfassend_panel(screen, rect, **kwargs):
        panel_rects.append(pygame.Rect(rect))
        return orig_panel(screen, rect, **kwargs)

    import src.states.menu.settings_page as modul
    modul.theme.text = erfassend_text
    modul.theme.panel = erfassend_panel
    try:
        schirm = pygame.Surface((1920, 1080))
        seite.draw(schirm, pygame.Rect(0, 108, 1920, 1080 - 108))
    finally:
        modul.theme.text = orig_text
        modul.theme.panel = orig_panel

    header = next(r for s, r in text_rects if s == "Ankündigungen")
    kasten = panel_rects[0]  # der Ankündigungen-Kasten ist das erste theme.panel() auf der Seite
    return header, kasten, text_rects


def test_ueberschrift_und_ankuendigungskasten_ueberlappen_sich_nicht(seite):
    header, kasten, _ = _info_zeichnen(seite)

    assert not header.colliderect(kasten), f"{header} überlappt {kasten}"
    assert kasten.top >= header.bottom, (
        f"Kasten (top={kasten.top}) beginnt noch innerhalb der Überschrift "
        f"(bottom={header.bottom})")


def test_zwischen_ueberschrift_und_kasten_bleibt_luft(seite):
    """Nicht nur „kein Überlapp" — ein kleiner Abstand, kein Kante-an-Kante."""
    header, kasten, _ = _info_zeichnen(seite)

    assert kasten.top - header.bottom >= 8


def test_die_version_steht_ohne_commit_hash_auf_der_info_seite(monkeypatch, seite):
    """„der Commit muss nicht hinter der Version angezeigt werden" — nur
    ``version.VERSION`` gehört auf die Seite, ``version_string()`` (das den
    Hash in Klammern anhängt) nicht mehr."""
    monkeypatch.setattr(version, "GIT_REV", "abc1234", raising=False)
    assert "(" in version.version_string(), "Testvoraussetzung: der Hash existiert"

    _, _, texte = _info_zeichnen(seite)
    werte = [s for s, _r in texte]

    assert f"v{version.VERSION}" in werte
    assert version.version_string() not in werte
    assert not any("abc1234" in s for s in werte), \
        "der Commit-Hash darf nirgends auf der Info-Seite auftauchen"


def test_version_string_selbst_bleibt_unveraendert(monkeypatch):
    """version.py wird bewusst NICHT angefasst — der Hash bleibt anderswo sichtbar."""
    monkeypatch.setattr(version, "GIT_REV", "abc1234", raising=False)
    assert version.version_string() == f"v{version.VERSION} (abc1234)"
