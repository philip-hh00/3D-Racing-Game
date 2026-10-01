"""Looping video background playback for menus and loading screens.

Decodes a video file frame-by-frame with OpenCV and hands out Pygame surfaces,
paced to the clip's own frame rate and looping seamlessly at the end (the clips
are authored with identical first/last frames). Everything degrades gracefully:
if OpenCV is missing or the file can't be opened, :meth:`get_surface` returns
None and callers fall back to a still image or gradient.
"""
from __future__ import annotations

import os
import threading
import time

import numpy as np
import pygame

try:
    import cv2
    _HAVE_CV2 = True
except Exception:      # pragma: no cover - optional dependency
    cv2 = None
    _HAVE_CV2 = False


class VideoPlayer:
    def __init__(self, path: str, size: tuple[int, int] | None = None,
                 faden: bool = True, abdunkeln=None) -> None:
        """``faden``: Bilder in einem Hintergrundfaden entschluesseln.

        Entschluesseln, Skalieren und Umschreiben eines Bildes kosten in 1440p
        10-16 ms; im Hauptfaden fiel damit jedes Videobild (alle 33 ms) aus dem
        60-Hertz-Takt. cv2 gibt dabei die GIL frei, der Faden laeuft also
        wirklich nebenher. ``faden=False`` (Tests) entschluesselt im Aufruf.

        ``abdunkeln``: ``(schluessel, deckkraft)`` — jedes Bild wird schon beim
        Entschluesseln mit einem schwarzen Ueberzug verrechnet (siehe
        :meth:`abdunkeln_setzen`).
        """
        self.path = path
        self.size = size
        self._cap = None
        self._fps = 30.0
        self._frame_dt = 1.0 / 30.0
        self._acc = 0.0
        self._surface: pygame.Surface | None = None
        self._fade_surf: pygame.Surface | None = None
        self._fade_left = 0.0
        self.ok = False
        self._abdunkeln = abdunkeln
        self._surface_schluessel = None
        self._faktoren: dict = {}
        self._faden_an = faden
        self._faden: threading.Thread | None = None
        self._anfrage = threading.Event()
        self._halt = False
        self._fehler_gemeldet = False
        self._schloss = threading.Lock()
        #: Das fertige naechste Bild des Fadens: ``(flaeche, schleife)``.
        self._fertig = None
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
            if self._faden_an and self.ok:
                self._faden = threading.Thread(target=self._faden_lauf,
                                               name="video-decode", daemon=True)
                self._faden.start()
                self._anfrage.set()
        except Exception:
            self._cap = None
            self.ok = False

    def _read_next(self) -> None:
        """Das naechste Bild holen und uebernehmen (im aufrufenden Faden)."""
        self._uebernehmen(self._entschluesseln())

    def _uebernehmen(self, ergebnis) -> None:
        if ergebnis is None:
            return
        surf, schleife, schluessel = ergebnis
        if schleife and self._surface is not None:
            self._fade_surf = self._surface.copy()
            self._fade_left = 0.5  # 0.5 seconds crossfade duration
        self._surface = surf
        self._surface_schluessel = schluessel

    def abdunkeln_setzen(self, schluessel, deckkraft=None) -> None:
        """Einen schwarzen Ueberzug gleich ins Videobild rechnen lassen.

        ``deckkraft`` ist eine Zahl 0-255 (gleichmaessig) oder ein 2D-``uint8``-
        Feld beliebiger Groesse (z. B. die Alphawerte einer Randabdunklung).
        Das Menue legte beides bisher in jedem Bild als Ueberzug ueber das Video:
        in 1440p 8 ms nur dafuer. Verrechnet im Entschluesselungsfaden kostet es
        den Hauptfaden nichts; er blittet das fertige Bild.

        Wirksam ab dem naechsten entschluesselten Bild; :attr:`bild_schluessel`
        sagt, welcher Ueberzug im aktuellen Bild steckt (``None`` = keiner).
        ``schluessel=None`` schaltet ab.
        """
        # Gleicher Schluessel heisst gleicher Ueberzug — Felder werden nicht
        # verglichen.
        if (self._abdunkeln[0] if self._abdunkeln else None) != schluessel:
            self._abdunkeln = None if schluessel is None else (schluessel, deckkraft)
            with self._schloss:
                self._fertig = None          # ein schon fertiges Bild traegt den alten Ueberzug
            if self._faden is not None:
                self._anfrage.set()

    @property
    def bild_schluessel(self):
        """Schluessel des Ueberzugs, der im aktuellen Bild schon steckt."""
        return self._surface_schluessel

    def _verrechnen(self, frame):
        """``frame`` (BGR) mit dem gewuenschten Ueberzug abdunkeln: ``(bild, schluessel)``."""
        ab = self._abdunkeln
        if ab is None:
            return frame, None
        schluessel, deckkraft = ab
        h, w = frame.shape[:2]
        ident = (schluessel, h, w)
        faktor = self._faktoren.get(ident)
        if faktor is None:
            if isinstance(deckkraft, np.ndarray):
                a = cv2.resize(np.ascontiguousarray(deckkraft, dtype=np.uint8), (w, h),
                               interpolation=cv2.INTER_LINEAR)
            else:
                a = np.full((h, w), int(deckkraft), dtype=np.uint8)
            faktor = cv2.merge([255 - a] * 3)
            self._faktoren = {ident: faktor}
        return cv2.multiply(frame, faktor, scale=1.0 / 255.0), schluessel

    def _faden_lauf(self) -> None:
        # Der Faden gibt die Aufnahme beim Beenden selbst frei: ``close`` darf
        # sie nicht schliessen, solange er noch in ``cap.read`` steckt.
        cap = self._cap
        try:
            while True:
                self._anfrage.wait()
                self._anfrage.clear()
                if self._halt:
                    return
                try:
                    ergebnis = self._entschluesseln()
                except Exception as fehler:
                    ergebnis = None
                    if not self._fehler_gemeldet:
                        self._fehler_gemeldet = True
                        print(f"[video] Entschluesseln fehlgeschlagen ({self.path}): {fehler!r}")
                if ergebnis is None:
                    # Ein Fehlschlag darf das Video nicht einfrieren: kurz warten
                    # und selbst neu bestellen.
                    if self._halt:
                        return
                    time.sleep(0.05)
                    self._anfrage.set()
                    continue
                with self._schloss:
                    self._fertig = ergebnis
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    def _entschluesseln(self):
        """Ein Bild lesen, skalieren und als Flaeche liefern: ``(flaeche, schleife)``.

        ``schleife`` ist wahr, wenn dafuer an den Anfang gesprungen wurde (der
        Hauptfaden blendet dann das letzte Bild aus).
        """
        cap = self._cap
        if cap is None:
            return None
        schleife = False
        ret, frame = cap.read()
        if not ret or frame is None:
            schleife = True
            try:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
            except Exception:
                ret, frame = False, None
            if not ret or frame is None:
                return None
        from src.ui import leinwand
        s = leinwand.skala()
        frame, schluessel = self._verrechnen(frame)
        if self.size:
            surf = self._direkt_in_flaeche(frame, s)
            if surf is not None:
                return surf, schleife, schluessel
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        # Rueckfall (kein Schreibzugriff auf die Flaechenbytes, oder keine
        # Zielgroesse): ueber einen Zwischenpuffer.
        if self.size:
            ziel = (max(1, round(self.size[0] * s)), max(1, round(self.size[1] * s)))
            if (w, h) != ziel:
                rgb = cv2.resize(rgb, ziel, interpolation=cv2.INTER_LINEAR)
                w, h = ziel
        rgb = np.ascontiguousarray(rgb)
        # ``frombuffer`` zeigt auf ``rgb``, ohne zu kopieren. Ohne Skala bliebe
        # die Flaeche am Puffer haengen; ``_flaeche_aus`` kopiert, ``convert``
        # ebenso.
        surf = pygame.image.frombuffer(rgb.data, (w, h), "RGB").convert()
        if self.size and s != 1.0:
            surf = leinwand._flaeche_aus(surf, s)
        return surf, schleife, schluessel

    def _direkt_in_flaeche(self, frame, s: float):
        """Das Videobild in einem Zug in eine fertige :class:`Flaeche` schreiben.

        Gemessen am 01.10.2026 (Vollbild 2560x1440, Skala 1,33): der alte Weg —
        BGR->RGB, ``resize``, ``frombuffer``, dann ``_flaeche_aus`` als Kopie
        der 14-MB-Flaeche — kostete 22 ms je Videobild, ein Drittel davon die
        Kopie. Hier skaliert ``cv2.resize`` (2-3 ms) und ``cvtColor`` schreibt
        die Bytes (BGRA, so liegt eine 32-Bit-Flaeche im Speicher) direkt in
        den Speicher der Zielflaeche. Keine Kopie, keine Zwischenflaeche.

        ``None``, wenn die Flaeche nicht das erwartete Speicherbild hat — dann
        greift der Rueckfall.
        """
        from src.ui import leinwand
        try:
            ziel = leinwand.Flaeche(self.size, 0, s)
            bw, bh = pygame.Surface.get_size(ziel)
            if ziel.get_bytesize() != 4 or ziel.get_pitch() != bw * 4:
                return None
            rot, _g, blau, _a = ziel.get_shifts()
            if (rot, blau) != (16, 0):                 # nicht BGRA im Speicher
                return None
            h, w = frame.shape[:2]
            # Erst in der kleinen Quellgroesse auf 4 Kanaele, dann skalieren:
            # ``resize`` schreibt das Ergebnis selbst in die Flaeche.
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
            ansicht = ziel.get_view("0")             # sperrt die Flaeche
            try:
                ziel_feld = np.frombuffer(ansicht, dtype=np.uint8).reshape(bh, bw, 4)
                if (w, h) == (bw, bh):
                    ziel_feld[...] = frame
                else:
                    cv2.resize(frame, (bw, bh), dst=ziel_feld,
                               interpolation=cv2.INTER_LINEAR)
            finally:
                ziel_feld = None
                del ansicht                           # gibt die Sperre frei
            return ziel
        except Exception:
            return None

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
            if self._faden is None:
                self._read_next()
            else:
                with self._schloss:
                    fertig, self._fertig = self._fertig, None
                if fertig is not None:
                    self._uebernehmen(fertig)
                    self._anfrage.set()          # das uebernaechste Bild bestellen
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
        if self._faden is not None:
            self._halt = True
            self._anfrage.set()
            self._faden.join(timeout=2.0)
            # Der Faden schliesst die Aufnahme selbst; auch wenn er noch haengt.
            self._faden = None
            self._cap = None
        self._fertig = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self._surface = None
        self._fade_surf = None
        self._fade_left = 0.0
        self.ok = False
