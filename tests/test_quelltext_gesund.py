"""Der Quelltext übersetzt und enthält keine Merge-Reste.

Anlass (30.07.2026): ein Merge zwischen der Audio-Arbeit und Block D hat
**Konfliktmarker in `src/entities/vehicle.py` mitcommittet**. Damit war `main`
für jeden, der pullt, sofort unbrauchbar — `python main.py` bricht mit
``SyntaxError`` ab, bevor irgendetwas passiert. Keiner der damals 630 Tests hat
das gemerkt, weil alle nur einzelne Module importieren und `vehicle.py` in den
betroffenen Läufen nie an die Reihe kam.

Diese beiden Prüfungen kosten unter einer Sekunde und fangen die ganze Klasse
Fehler: jede Datei muss übersetzbar sein, und nichts darf nach einem
unaufgelösten Konflikt aussehen.
"""
from __future__ import annotations

import py_compile
import subprocess
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[1]

#: Marker, wie git sie beim Konflikt hineinschreibt. Bewusst am Zeilenanfang und
#: mit genau sieben Zeichen geprüft — sonst schlägt die Prüfung bei Markdown-
#: Trennlinien (`=======`) oder Kommentarbalken fehl.
_MARKER = ("<<<<<<<", "=======", ">>>>>>>")

_TEXTENDUNGEN = {".py", ".json", ".md", ".spec", ".iss", ".bat", ".sh", ".txt",
                 ".gitattributes"}


def _verfolgte_dateien() -> list[Path]:
    """Nur von git verfolgte Dateien — kein __pycache__, kein Build-Ausschuss."""
    roh = subprocess.run(["git", "ls-files", "-z"], cwd=WURZEL,
                         capture_output=True, text=True, check=True).stdout
    return [WURZEL / p for p in roh.split("\0") if p]


def _python_dateien() -> list[Path]:
    return [p for p in _verfolgte_dateien() if p.suffix == ".py" and p.is_file()]


def test_es_gibt_ueberhaupt_dateien_zu_pruefen():
    """Absicherung der Prüfung selbst: liefert `git ls-files` nichts, würden die
    beiden Tests unten stillschweigend durchlaufen und nichts prüfen."""
    assert len(_python_dateien()) > 50


@pytest.mark.parametrize("pfad", _python_dateien(), ids=lambda p: str(p.relative_to(WURZEL)))
def test_datei_uebersetzt(pfad: Path):
    try:
        py_compile.compile(str(pfad), doraise=True, cfile=str(pfad) + ".pyc-test")
    except py_compile.PyCompileError as fehler:
        pytest.fail(f"{pfad.relative_to(WURZEL)} übersetzt nicht:\n{fehler}")
    finally:
        Path(str(pfad) + ".pyc-test").unlink(missing_ok=True)


def test_keine_konfliktmarker():
    treffer: list[str] = []
    for pfad in _verfolgte_dateien():
        if not pfad.is_file() or pfad.suffix not in _TEXTENDUNGEN:
            continue
        # Diese Datei nennt die Marker im Text und darf sich nicht selbst melden.
        if pfad.resolve() == Path(__file__).resolve():
            continue
        try:
            zeilen = pfad.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for nr, zeile in enumerate(zeilen, 1):
            gestrippt = zeile.rstrip()
            if any(gestrippt == m or gestrippt.startswith(m + " ") for m in _MARKER):
                treffer.append(f"{pfad.relative_to(WURZEL)}:{nr}: {gestrippt[:60]}")
    assert not treffer, "Unaufgelöste Merge-Marker im Quelltext:\n" + "\n".join(treffer)
