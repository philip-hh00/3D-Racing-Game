"""Graphics utility helper for texture scaling and quality settings."""
from __future__ import annotations
import pygame

def scale(surface: pygame.Surface, size: tuple[int, int]) -> pygame.Surface:
    """Scale a surface to a target size based on the texture quality profile setting.

    If quality is "Hoch" (High), it uses smoothscale.
    Otherwise (Niedrig / Low), it uses normal scale.
    """
    from src.core import profile
    p = profile.current()
    quality = getattr(p, "texture_quality", "Hoch")
    if quality == "Hoch":
        return pygame.transform.smoothscale(surface, size)
    else:
        return pygame.transform.scale(surface, size)
