"""Der Absturzbericht: wo er liegt und wie man ihn aufbekommt (Block F2).

Stürzt das Spiel ab, schreibt ``main.py`` den vollständigen Traceback nach
``crash.log`` und zeigt sechs Sekunden lang den Pfad an. Das ist genau so lange
lesbar, wie niemand ihn abschreiben kann — und wo die Datei liegt, hängt auch
noch vom Betriebssystem ab: im gepackten macOS-Bündel unter
``~/Library/Application Support``, sonst im Arbeitsverzeichnis. Wer den Bericht
melden soll, muss ihn finden können, ohne zu wissen, was ``sys._MEIPASS`` ist.

Deshalb steht der Pfad an **einer** Stelle (hier), und die Einstellungen
verlinken ihn unter „Info" direkt neben „Bugs melden".
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: Dateiname des Absturzberichts, relativ zum Nutzerverzeichnis.
TEILE = ("data", "settings", "crash.log")


def pfad() -> Path:
    """Wo der Absturzbericht liegt — auch wenn es ihn (noch) nicht gibt.

    Der Rückfall auf einen relativen Pfad ist der Fall, in dem ``paths`` selbst
    nicht mehr importierbar ist: Das passiert genau dann, wenn schon etwas sehr
    schiefgegangen ist — also in dem Moment, in dem der Bericht gebraucht wird.
    """
    try:
        from src.core.paths import user_path
        return Path(user_path(*TEILE))
    except Exception:
        p = Path(*TEILE)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return p


def vorhanden() -> bool:
    try:
        return pfad().is_file()
    except Exception:
        return False


def schreiben(text: str) -> Path:
    """Den Bericht ablegen und den benutzten Pfad zurückgeben."""
    ziel = pfad()
    ziel.write_text(text, encoding="utf-8")
    return ziel


def oeffnen() -> bool:
    """Den Bericht im Standardprogramm des Systems öffnen.

    ``False`` heißt: es gibt nichts zu öffnen oder das System hat es abgelehnt.
    Ein Fehlschlag darf niemals aus dem Menü heraus abstürzen — der Weg zur
    Fehlermeldung soll nicht selbst die nächste Fehlermeldung sein.
    """
    if not vorhanden():
        return False
    ziel = str(pfad())
    try:
        if sys.platform == "win32":
            os.startfile(ziel)                      # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", ziel])
        else:
            subprocess.Popen(["xdg-open", ziel])
        return True
    except Exception:
        return False
