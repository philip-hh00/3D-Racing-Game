"""Audio manager – playing looped music with fade-in and volume settings."""
from __future__ import annotations

import os
import pygame
from src.core import profile

_current_track: str | None = None

#: Deckel auf die Musiklautstaerke (08.08.2026). Gemeldet: selbst bei 10 % am
#: Regler ist die Musik noch recht laut, rund 30 % leiser waere richtig. Der
#: Regler setzte seinen Wert bisher ungedaempft auf den Kanal. Gleichmaessig um
#: 30 % daempfen statt die Reglerskala zu kruemmen: so behaelt jede Stufe ihre
#: Bedeutung (0 bleibt still, jede hoehere Stufe bleibt lauter als die
#: darunter), sie liegt nur durchweg tiefer.
MUSIK_HEADROOM: float = 0.7


def _gedaempfte_musiklautstaerke(vol: float) -> float:
    """Reglerwert mit festem Deckel — siehe MUSIK_HEADROOM."""
    return vol * MUSIK_HEADROOM

def play_menu_music() -> None:
    """Play menu theme music looped and faded in."""
    _play_track("menu")

def play_race_music() -> None:
    """Play race theme music looped and faded in."""
    _play_track("race")

def stop_music() -> None:
    """Stop the music with a fade out."""
    global _current_track
    if pygame.mixer and pygame.mixer.get_init():
        try:
            pygame.mixer.music.fadeout(1000)
        except Exception:
            pass
    _current_track = None

def _play_track(name: str) -> None:
    """Play a specific audio track loop from data/audio/."""
    global _current_track
    if _current_track == name:
        return

    if not pygame.mixer or not pygame.mixer.get_init():
        return

    path = os.path.join("data", "audio", f"{name}.mp3")
    if not os.path.isfile(path):
        return

    try:
        pygame.mixer.music.load(path)
        vol = profile.current().menu_volume if name == "menu" else profile.current().race_volume
        pygame.mixer.music.set_volume(_gedaempfte_musiklautstaerke(vol))
        # Play looped (-1) with a fade-in of 1500 ms
        pygame.mixer.music.play(-1, fade_ms=1500)
        _current_track = name
    except Exception as e:
        print(f"[Audio] Failed to play track {name}: {e}")
