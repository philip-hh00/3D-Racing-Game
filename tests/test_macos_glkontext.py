"""macOS bekommt ausdruecklich OpenGL 3.3 Core (gemeldet 07.10.2026).

Ohne Anforderung liefert macOS einen 2.1-Kontext, auf dem kein Shader des
Spiels (``#version 330``) uebersetzt: der Mac-Build zeigte nur Schwarz.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

from src.core import display  # noqa: E402


def _mitschreiben(monkeypatch):
    gesetzt = {}
    monkeypatch.setattr(pygame.display, "gl_set_attribute",
                        lambda attr, wert: gesetzt.__setitem__(attr, wert))
    return gesetzt


def test_macos_fordert_33_core_vorwaertskompatibel_an(monkeypatch):
    gesetzt = _mitschreiben(monkeypatch)
    assert display._gl_version_anfordern("darwin")
    assert gesetzt[pygame.GL_CONTEXT_MAJOR_VERSION] == 3
    assert gesetzt[pygame.GL_CONTEXT_MINOR_VERSION] == 3
    assert gesetzt[pygame.GL_CONTEXT_PROFILE_MASK] == pygame.GL_CONTEXT_PROFILE_CORE
    assert gesetzt[pygame.GL_CONTEXT_FLAGS] & pygame.GL_CONTEXT_FORWARD_COMPATIBLE_FLAG


def test_windows_und_linux_bleiben_unberuehrt(monkeypatch):
    gesetzt = _mitschreiben(monkeypatch)
    assert not display._gl_version_anfordern("win32")
    assert not display._gl_version_anfordern("linux")
    assert gesetzt == {}


def test_kein_shader_verlangt_mehr_als_macos_kann():
    """macOS hat hoechstens OpenGL 4.1 Core."""
    import re
    wurzel = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    versionen = set()
    for ordner, _d, dateien in os.walk(wurzel):
        for name in dateien:
            if name.endswith((".py", ".glsl", ".vert", ".frag")):
                with open(os.path.join(ordner, name), encoding="utf-8", errors="ignore") as f:
                    versionen |= {int(v) for v in re.findall(r"#version (\d+)", f.read())}
    assert versionen and max(versionen) <= 410, versionen
