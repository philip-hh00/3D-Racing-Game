"""Signierte Pruefsummen der spielrelevanten Dateien schreiben (vor dem Packen).

Aufgerufen von den Bauskripten nach ``tools/baustempel.py``. Siehe
``src/core/integritaet.py``.
"""
from __future__ import annotations

import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

from src.core import integritaet  # noqa: E402

if __name__ == "__main__":
    pfad = integritaet.schreiben(WURZEL)
    print(f"Pruefsummen: {pfad} ({len(integritaet.hashes(WURZEL))} Dateien)")
