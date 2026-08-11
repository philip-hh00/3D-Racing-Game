"""Die Versionsnummer auf die Standardausgabe, sonst nichts (06.08.2026).

Klingt nach einer Zeile zu viel, ist aber die Behebung eines echten Fehlers.
``build_windows.bat`` las die Version so:

    "%PY%" -c "from src.core import version; print(version.VERSION)" > "%TEMP%\\..."

Diese Zeile **beginnt und endet mit einem Anführungszeichen**. In genau dem Fall
entfernt ``cmd`` das äußere Paar, und übrig bleibt als Programmname
``python" -c "from`` — gemeldet am 06.08.2026 als „Der Befehl "python" -c "from"
ist entweder falsch geschrieben oder konnte nicht gefunden werden."

Solange der Interpreter mit vollem Pfad dastand, ging es gut. Erst als das
Skript auf das Python vom Suchpfad zurückfiel, kippte die Auswertung. Ein
Fehler, der von der Länge eines Pfades abhängt, gehört nicht in ein
Bauskript — deshalb steht die Abfrage jetzt hier, und der Aufruf im Skript
kommt **ohne ein einziges inneres Anführungszeichen** aus:

    "%PY%" -m tools.version_ausgeben

Ausgegeben wird nur die nackte Nummer ohne „v" und ohne Commit — das Skript
setzt sie in Dateinamen und reicht sie an Inno Setup weiter.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    # Aus dem Wurzelverzeichnis aufgerufen; ohne das findet der Import nichts,
    # wenn jemand das Werkzeug von woanders startet.
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if wurzel not in sys.path:
        sys.path.insert(0, wurzel)
    from src.core import version
    print(version.VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
