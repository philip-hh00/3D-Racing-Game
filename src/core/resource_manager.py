"""Singleton resource manager – loads and caches images, fonts, and sounds."""
from __future__ import annotations

import pygame


class ResourceManager:
    """Caches loaded assets to avoid repeated disk I/O.

    Usage:
        rm = ResourceManager()
        img = rm.load_image("assets/images/cars/car_01.png")
    """

    _instance: ResourceManager | None = None

    def __new__(cls) -> ResourceManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._image_cache: dict[str, pygame.Surface] = {}
            cls._instance._font_cache: dict[tuple[str | None, int], pygame.font.Font] = {}
            cls._instance._sound_cache: dict[str, pygame.mixer.Sound] = {}
        return cls._instance

    def load_image(self, path: str) -> pygame.Surface:
        """Load an image from disk (cached). Returns a Surface with alpha."""
        if path not in self._image_cache:
            surface = pygame.image.load(path).convert_alpha()
            self._image_cache[path] = surface
        return self._image_cache[path]

    def load_font(self, path: str | None, size: int) -> pygame.font.Font:
        """Load a font (cached). Pass None for the pygame default font."""
        key = (path, size)
        if key not in self._font_cache:
            if path is None:
                font = pygame.font.Font(None, size)
            else:
                font = pygame.font.Font(path, size)
            self._font_cache[key] = font
        return self._font_cache[key]

    def get_default_font(self, size: int) -> pygame.font.Font:
        """Convenience: load the pygame default font at a given size."""
        return self.load_font(None, size)

    def load_sound(self, path: str) -> pygame.mixer.Sound:
        """Load a sound effect (cached)."""
        if path not in self._sound_cache:
            self._sound_cache[path] = pygame.mixer.Sound(path)
        return self._sound_cache[path]

    def clear_cache(self) -> None:
        """Drop all cached assets."""
        self._image_cache.clear()
        self._font_cache.clear()
        self._sound_cache.clear()
