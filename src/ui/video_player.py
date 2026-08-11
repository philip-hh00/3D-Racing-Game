"""Looping video background playback for menus and loading screens.

Decodes a video file frame-by-frame with OpenCV and hands out Pygame surfaces,
paced to the clip's own frame rate and looping seamlessly at the end (the clips
are authored with identical first/last frames). Everything degrades gracefully:
if OpenCV is missing or the file can't be opened, :meth:`get_surface` returns
None and callers fall back to a still image or gradient.
"""
from __future__ import annotations

import os

import numpy as np
import pygame

try:
    import cv2
    _HAVE_CV2 = True
except Exception:      # pragma: no cover - optional dependency
    cv2 = None
    _HAVE_CV2 = False


class VideoPlayer:
    def __init__(self, path: str, size: tuple[int, int] | None = None) -> None:
        self.path = path
        self.size = size
        self._cap = None
        self._fps = 30.0
        self._frame_dt = 1.0 / 30.0
        self._acc = 0.0
        self._surface: pygame.Surface | None = None
        #: Haelt den Bildspeicher der aktuellen Flaeche am Leben.
        self._puffer = None
        self._fade_surf: pygame.Surface | None = None
        self._fade_left = 0.0
        self.ok = False
        if _HAVE_CV2 and os.path.isfile(path):
            self._open()

    def _open(self) -> None:
        try:
            self._cap = cv2.VideoCapture(self.path)
            if not self._cap.isOpened():
                self._cap = None
                return
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            if fps and fps > 1:
                self._fps = fps
                self._frame_dt = 1.0 / fps
            self.ok = True
            self._read_next()          # prime the first frame
        except Exception:
            self._cap = None
            self.ok = False

    def _read_next(self) -> None:
        if self._cap is None:
            return
        ret, frame = self._cap.read()
        if not ret or frame is None:
            # Loop back to the start.
            if self._surface is not None:
                self._fade_surf = self._surface.copy()
                self._fade_left = 0.5  # 0.5 seconds crossfade duration
            try:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
            except Exception:
                ret, frame = False, None
            if not ret or frame is None:
                return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        # ``tobytes()`` legte hier je Bild eine zweite Kopie von 6,2 MB an,
        # nur damit ``frombuffer`` etwas zu lesen hat. Das Ergebnis von
        # ``cvtColor`` liegt bereits zusammenhaengend im Speicher — pygame kann
        # direkt daraus lesen. Gemessen am 05.08.2026: die Kopie war die
        # teuerste vermeidbare Einzelheit im Menuebild.
        #
        # ``frombuffer`` kopiert die Daten **nicht**, es zeigt darauf. Der
        # Puffer muss deshalb so lange leben wie die Flaeche — sonst zeigt sie
        # auf freigegebenen Speicher. An die Flaeche haengen laesst er sich
        # nicht (``pygame.Surface`` nimmt keine eigenen Attribute an), also
        # haelt ihn der Spieler neben ihr.
        rgb = np.ascontiguousarray(rgb)
        surf = pygame.image.frombuffer(rgb.data, (w, h), "RGB")
        if self.size and (w, h) != self.size:
            # Skalieren erzeugt eine eigene Flaeche mit eigenem Speicher; der
            # Puffer wird dann nicht mehr gebraucht.
            surf = pygame.transform.smoothscale(surf, self.size)
            rgb = None
        self._surface = surf
        self._puffer = rgb

    def update(self, dt: float) -> None:
        if self._cap is None:
            return
        if self._fade_left > 0.0:
            self._fade_left -= dt
            if self._fade_left <= 0.0:
                self._fade_surf = None
        self._acc += dt
        # Advance at most a few frames per tick to avoid runaway on lag spikes.
        steps = 0
        while self._acc >= self._frame_dt and steps < 3:
            self._acc -= self._frame_dt
            self._read_next()
            steps += 1

    def get_surface(self) -> pygame.Surface | None:
        if self._surface is None:
            return None
        if self._fade_surf is not None and self._fade_left > 0.0:
            # Blend self._fade_surf on top of self._surface
            alpha = self._fade_left / 0.5
            blended = self._surface.copy()
            self._fade_surf.set_alpha(int(255 * alpha))
            blended.blit(self._fade_surf, (0, 0))
            return blended
        return self._surface

    def close(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._surface = None
        self._puffer = None
        self._fade_surf = None
        self._fade_left = 0.0
        self.ok = False
