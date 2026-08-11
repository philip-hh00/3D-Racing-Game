"""Nur ein laufendes Spiel je Rechner (offener Punkt aus A2).

Zwei Instanzen schreiben dieselbe ``profile.json``. Solange das eine Klartext-
datei war, kostete ein Schreibkonflikt im schlimmsten Fall ein paar Bestzeiten.
Seit E4 liegt das Profil **verschlüsselt und signiert** in einem Behälter — wer
mittendrin darüberschreibt, macht daraus nicht ein veraltetes, sondern ein
unlesbares Profil, und mit ihm gehen Freischaltungen und Statistik verloren.

Entschieden am 05.08.2026: die zweite Instanz startet gar nicht erst.

**Warum eine Sperrdatei allein nicht genügt.** „Datei da → belegt" wäre in drei
Zeilen geschrieben und würde das Spiel nach dem ersten Absturz dauerhaft
blockieren — die Datei bliebe liegen, und niemand weiß, dass er sie löschen
muss. Gesperrt wird deshalb über das Betriebssystem (``flock`` bzw.
``msvcrt``): so eine Sperre hängt an der offenen Datei, und die schließt das
System beim Ende des Prozesses selbst. Auch bei einem Absturz, auch beim
Abschießen im Taskmanager. Es gibt keinen Zustand, aus dem man sich von Hand
befreien müsste.

**Im Zweifel geht das Spiel auf.** Kann auf einer Plattform nicht gesperrt
werden, gilt das nicht als „belegt". Ein Spiel, das wegen einer unbekannten
Dateisystemeigenheit nicht mehr startet, ist schlimmer als ein Schreibkonflikt,
den es vielleicht nie gibt.
"""
from __future__ import annotations

import os
import sys

#: Bleibt für die Laufzeit offen — die Sperre hängt an dieser offenen Datei.
#: Als Modulvariable, damit der Müllsammler sie nicht einsammelt und dabei
#: stillschweigend die Sperre löst.
_halter = None

DATEINAME = "instanz.lock"


def _pfad() -> str:
    from src.core import paths
    return paths.user_path("data", "settings", DATEINAME)


def _sperren(fh) -> bool:
    """Exklusiv sperren, ohne zu warten. ``False`` heißt: jemand hat sie schon."""
    if sys.platform == "win32":
        try:
            import msvcrt
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
        except Exception:
            return True          # kein Sperrmechanismus → nicht blockieren
    try:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    except Exception:
        return True              # kein Sperrmechanismus → nicht blockieren


def beanspruchen() -> bool:
    """Diese Instanz als die laufende eintragen.

    ``True``: der Weg ist frei. ``False``: es läuft bereits eine.
    """
    global _halter
    if _halter is not None:
        return True              # schon beansprucht, nicht doppelt zählen
    try:
        fh = open(_pfad(), "a+b")
    except OSError:
        return True              # nicht schreibbar → nicht blockieren
    if not _sperren(fh):
        try:
            fh.close()
        except OSError:
            pass
        return False
    _halter = fh
    try:
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()).encode("ascii"))
        fh.flush()
    except OSError:
        pass                     # die Nummer ist Beiwerk, die Sperre zählt
    return True


def freigeben() -> None:
    """Sperre lösen. Das System täte es beim Prozessende ohnehin — hier steht
    es für den geordneten Fall und für Tests, die mehrfach beanspruchen."""
    global _halter
    if _halter is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt
            _halter.seek(0)
            msvcrt.locking(_halter.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(_halter.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        _halter.close()
    except OSError:
        pass
    _halter = None
