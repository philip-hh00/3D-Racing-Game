"""Musiklautstaerke: fester Deckel unter dem Reglerwert.

Fund 08.08.2026: die Musik war selbst bei niedrigem Regler noch zu laut, weil
der Reglerwert ungedaempft auf den Musikkanal ging. Entschieden: gleichmaessig
um 30 % daempfen. Die Tests halten die *Regel*, nicht den einen Wert 0,7 —
damit ein spaeteres Verstellen des Deckels auffaellt, statt still die Bedeutung
des Reglers zu verschieben.
"""
from __future__ import annotations

import pytest

from src.core import audio, profile


def test_musik_hat_headroom_unter_dem_regler():
    """Es gibt ueberhaupt einen Deckel: der Ausgabewert liegt unter dem Regler
    (ausser bei 0), und der volle Regler bleibt unter dem Maximum des Kanals."""
    assert audio.MUSIK_HEADROOM < 1.0
    assert audio._gedaempfte_musiklautstaerke(1.0) < 1.0
    for v in (0.1, 0.5, 1.0):
        assert audio._gedaempfte_musiklautstaerke(v) < v


def test_regler_behaelt_seine_bedeutung():
    """0 bleibt still, und jede hoehere Stufe bleibt lauter als die darunter —
    die Skala wird nur gesenkt, nicht gekruemmt."""
    assert audio._gedaempfte_musiklautstaerke(0.0) == 0.0
    stufen = [i / 10.0 for i in range(11)]  # der Regler zeigt 0..10
    werte = [audio._gedaempfte_musiklautstaerke(s) for s in stufen]
    assert werte == sorted(werte)
    assert all(a < b for a, b in zip(werte, werte[1:]))


@pytest.mark.parametrize("spielen,feld", [
    (audio.play_menu_music, "menu_volume"),
    (audio.play_race_music, "race_volume"),
])
def test_play_track_wendet_den_deckel_an(monkeypatch, spielen, feld):
    """Der Weg vom Regler bis zum Kanal ist verkabelt — fuer Menue *und*
    Rennen, denn beide gemeldet. Ohne diese Pruefung bliebe der Deckel eine
    Zahl, die niemand benutzt."""
    prof = profile.current()
    monkeypatch.setattr(prof, feld, 0.6, raising=False)

    gesetzt: list[float] = []
    monkeypatch.setattr(audio.pygame.mixer.music, "set_volume", gesetzt.append)
    monkeypatch.setattr(audio.pygame.mixer.music, "load", lambda *a, **k: None)
    monkeypatch.setattr(audio.pygame.mixer.music, "play", lambda *a, **k: None)
    # Frueher gespielte Spur wuerde sonst als "laeuft schon" den Aufruf schlucken.
    monkeypatch.setattr(audio, "_current_track", None, raising=False)

    spielen()
    assert gesetzt == [pytest.approx(0.6 * audio.MUSIK_HEADROOM)]
