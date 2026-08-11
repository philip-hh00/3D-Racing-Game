"""tools/portables_zip.py erzeugt ein butler-taugliches Archiv.

Fund 08.08.2026: PowerShells Compress-Archive legte fuer einen Unterordner
zusaetzlich einen 0-Byte-Eintrag ohne Schraegstrich an (Datei ``numpy`` neben
Ordner ``numpy/``); butler (itch.io) lehnte das Archiv ab -- "Two entries have
the same name". Der Test haelt die Regel: im portablen ZIP gibt es nie eine
Datei und einen Ordner gleichen Namens.
"""
from __future__ import annotations

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.portables_zip import packe  # noqa: E402


def _konflikte(namen: list[str]) -> list[str]:
    """Namen, die als Datei (ohne /) UND als Ordnerpraefix (name/...) vorkommen --
    genau das von butler abgelehnte Muster."""
    return [n for n in namen
            if not n.endswith("/")
            and any(m != n and m.startswith(n + "/") for m in namen)]


def _baue_baum(wurzel) -> None:
    spiel = wurzel / "2D-Racing-Game"
    (spiel / "_internal" / "numpy").mkdir(parents=True)
    (spiel / "_internal" / "_sounddevice_data").mkdir(parents=True)  # bewusst leer
    (spiel / "_internal" / "numpy" / "core.pyd").write_text("x", encoding="utf-8")
    (spiel / "2D-Racing-Game.exe").write_text("x", encoding="utf-8")


def test_archiv_hat_keine_namensgleichen_datei_und_ordner(tmp_path):
    _baue_baum(tmp_path)
    ziel = tmp_path / "out.zip"
    packe(str(tmp_path / "2D-Racing-Game"), str(ziel))

    with zipfile.ZipFile(ziel) as z:
        assert z.testzip() is None, "beschaedigtes Archiv"
        namen = z.namelist()

    assert _konflikte(namen) == [], f"Datei und Ordner gleichen Namens: {_konflikte(namen)}"
    assert all("\\" not in n for n in namen), "Rueckwaerts-Schraegstriche im Archiv"
    assert any(n.startswith("2D-Racing-Game/") for n in namen), "Ordner nicht als oberste Ebene"
    # Leerer Ordner bleibt erhalten -- aber MIT Schraegstrich, nicht als Datei.
    assert "2D-Racing-Game/_internal/_sounddevice_data/" in namen


def test_konflikt_erkennung_hat_zaehne():
    """Gegenprobe: genau das von butler abgelehnte Muster wird als Konflikt
    erkannt -- sonst pruefte der Test oben ins Leere."""
    schlecht = [
        "2D-Racing-Game/_internal/numpy",            # 0-Byte-Datei ohne Schraegstrich
        "2D-Racing-Game/_internal/numpy/core.pyd",   # Ordner gleichen Namens
    ]
    assert _konflikte(schlecht) == ["2D-Racing-Game/_internal/numpy"]
