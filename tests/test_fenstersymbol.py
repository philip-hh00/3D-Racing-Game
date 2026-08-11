"""Das Fenstersymbol laesst sich wirklich laden.

Fund 08.08.2026: im Fenster stand die Python-Schlange statt des Spielsymbols.
Beide Ladewege scheiterten still — ``data/icon.ico`` kann pygame nicht lesen
("Unsupported ICO bitmap format"), und ``data/menu/Icon.png`` gab es nicht (und
der Pfad war relativ). Die Tests laden das Symbol *tatsaechlich*, statt nur den
Aufruf zu sehen: nur so faellt eine Datei auf, die pygame nicht lesen kann.
"""
from __future__ import annotations

import pygame

from src.core import display
from src.core.paths import bundle_dir


def test_ausgeliefertes_symbol_ist_von_pygame_ladbar():
    """Regel: das mitgelieferte Symbol ist eine Datei, die pygame liest.

    Die ICO erfuellte das nicht — genau daran scheiterte der alte Weg. Geprueft
    wird der Weg, den das Spiel geht: ``bundle_dir()/data/icon.png``.
    """
    pygame.init()
    pfad = bundle_dir() / "data" / "icon.png"
    assert pfad.is_file(), f"Symboldatei fehlt: {pfad}"
    surf = pygame.image.load(str(pfad))
    assert surf.get_width() > 0 and surf.get_height() > 0


def test_ico_bleibt_fuer_pygame_unlesbar_ist_also_nicht_die_quelle():
    """Gegenprobe zum Fund: die ICO ist weiterhin nicht ladbar. Sie darf
    deshalb nicht die Laufzeitquelle sein — sie bleibt nur das Symbol der
    ausfuehrbaren Datei."""
    pygame.init()
    ico = bundle_dir() / "data" / "icon.ico"
    if not ico.is_file():
        return  # nichts zu zeigen
    with_error = False
    try:
        pygame.image.load(str(ico))
    except Exception:
        with_error = True
    assert with_error, "Wenn pygame die ICO liest, ist der Fund hinfaellig"


def test_set_window_icon_setzt_ein_echtes_symbol(monkeypatch):
    """Regel: der Setzweg laedt eine echte Flaeche und uebergibt sie.

    Nicht nur "set_icon wurde gerufen": frueher wurde ein Aufruf gezaehlt, der
    in Wahrheit nie eine Flaeche bekam."""
    pygame.init()
    gesetzt: list[pygame.Surface] = []
    monkeypatch.setattr(pygame.display, "set_icon", gesetzt.append)
    display.set_window_icon()
    assert len(gesetzt) == 1
    assert isinstance(gesetzt[0], pygame.Surface)
    assert gesetzt[0].get_width() > 0 and gesetzt[0].get_height() > 0
