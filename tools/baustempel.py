"""Bauzeit in eine Datei schreiben, die ins Bündel wandert (06.08.2026).

``version.BUILD_DATE`` stand auf ``date.today()``. Das wird ausgerechnet, wenn
das Spiel **läuft** — bei einem gepackten Build also auf dem Rechner des
Spielers, an dem Tag, an dem er spielt. Die Info-Seite zeigte ihm damit sein
eigenes Tagesdatum als „Build-Datum"; die Angabe war nie falsch zu erkennen und
immer wertlos.

Gebraucht wird sie aber, seit es Testbuilds gibt: die tragen dieselbe Version
aus ``version.py`` und unterscheiden sich **nur** in der Bauzeit. Ohne einen
eingebrannten Stempel wäre am laufenden Spiel nicht zu sehen, welcher Stand
gerade läuft.

Deshalb schreibt dieses Werkzeug vor dem Packen ``data/settings/build_stamp.json``.
``version.py`` liest die Datei, wenn sie da ist, und fällt sonst auf das
heutige Datum zurück — aus dem Quelltext gestartet ist genau das richtig, denn
dort ist „gebaut" und „gestartet" derselbe Moment.

    python -m tools.baustempel

Die Datei gehört **nicht** ins Repo (``.gitignore``): sie entsteht beim Bauen
und beschreibt einen einzelnen Build, nicht den Quellstand.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

_ZIEL = os.path.join("data", "settings", "build_stamp.json")


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode().strip()
    except Exception:
        return ""


def schreiben(ziel: str = _ZIEL) -> dict:
    """Stempel erzeugen und ablegen. Gibt den geschriebenen Inhalt zurück."""
    jetzt = datetime.now(timezone.utc)
    stempel = {
        # Datum allein reicht nicht: an einem Tag entstehen mehrere Testbuilds.
        "datum": jetzt.strftime("%Y-%m-%d"),
        "zeit": jetzt.strftime("%H:%M"),
        "commit": _git_rev(),
        # Woher der Build kommt. Die Pipeline setzt das, von Hand bleibt es leer.
        "quelle": os.environ.get("RACE_BUILD_QUELLE", ""),
    }
    os.makedirs(os.path.dirname(ziel), exist_ok=True)
    with open(ziel, "w", encoding="utf-8") as fh:
        json.dump(stempel, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return stempel


def main() -> int:
    if not os.path.isdir("src"):
        print("[FEHLER] Aus dem Wurzelverzeichnis des Projekts aufrufen.",
              file=sys.stderr)
        return 1
    stempel = schreiben()
    print(f"Bauzeit eingebrannt: {stempel['datum']} {stempel['zeit']} UTC"
          + (f"  ({stempel['commit']})" if stempel["commit"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
