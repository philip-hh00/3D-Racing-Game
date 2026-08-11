"""Version info for the game. Single source of truth."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date

VERSION = "0.9.0-beta"
# Packaged (PyInstaller) builds are releases → dev tools hidden.
# Running from source shows them.
IS_RELEASE = getattr(sys, "frozen", False)


def _baustempel() -> dict:
    """Die beim Packen eingebrannte Bauzeit, oder ein leeres Wörterbuch.

    ``tools/baustempel.py`` legt die Datei vor dem Packen an, die
    Spezifikationen nehmen sie mit ins Bündel. Fehlt sie, läuft das Spiel aus
    dem Quelltext — dann sind „gebaut" und „gestartet" derselbe Moment und das
    heutige Datum ist die richtige Antwort.
    """
    try:
        # paths zieht nur os/sys/pathlib — kein Ringschluss über version.
        from src.core import paths
        pfad = os.fspath(paths.bundle_dir() / "data" / "settings" / "build_stamp.json")
    except Exception:
        pfad = os.path.join("data", "settings", "build_stamp.json")
    try:
        with open(pfad, encoding="utf-8") as fh:
            stempel = json.load(fh)
        return stempel if isinstance(stempel, dict) else {}
    except Exception:
        return {}


_STEMPEL = _baustempel()

#: Wann dieser Build entstanden ist.
#:
#: Stand bis zum 06.08.2026 auf ``date.today()`` — ausgerechnet beim **Start**,
#: bei einem gepackten Build also auf dem Rechner des Spielers. Die Info-Seite
#: zeigte ihm damit sein eigenes Tagesdatum. Seit es Testbuilds gibt, die
#: dieselbe Version tragen und sich nur in der Bauzeit unterscheiden, ist die
#: Angabe die einzige Stelle, an der ein Stand auseinanderzuhalten ist.
BUILD_DATE = str(_STEMPEL.get("datum") or date.today().isoformat())

#: Uhrzeit des Builds (UTC), leer bei einem Lauf aus dem Quelltext. An einem Tag
#: entstehen mehrere Testbuilds — das Datum allein trennt sie nicht.
BUILD_TIME = str(_STEMPEL.get("zeit") or "")

#: Woher der Build kommt: leer von Hand, sonst was die Pipeline gesetzt hat.
BUILD_QUELLE = str(_STEMPEL.get("quelle") or "")

def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=1,
        ).decode().strip()
    except Exception:
        return ""

GIT_REV = _git_rev()

def version_string() -> str:
    rev = f" ({GIT_REV})" if GIT_REV else ""
    return f"v{VERSION}{rev}"
