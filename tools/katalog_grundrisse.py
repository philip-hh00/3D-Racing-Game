"""Grundrisse der Umgebungsmodelle in ``assets/umgebung/katalog.json`` nachtragen.

Die Platzierung (``src/render3d/platzierung.py``) prüft mit dem **Grundriss**
jedes Objekts, dass es nicht auf die Fahrbahn ragt — ein Rechteck im
Modellraum, ``grundriss_m: [x_min, x_max, y_min, y_max]`` in Metern, bei
Skala 1 und Gier 0. ``tools/blender/umgebung_bauen.py`` schreibt es beim
Bauen mit; für Modelle, die vorher gebaut wurden, liest dieses Werkzeug die
GLB-Dateien mit :func:`src.render3d.mesh.laden` und ergänzt es, ohne ein
Asset neu zu bauen::

    .venv\\Scripts\\python.exe tools\\katalog_grundrisse.py           # nur fehlende
    .venv\\Scripts\\python.exe tools\\katalog_grundrisse.py --alle    # alle neu messen

Gemessen wird die Stufe 0 (``<name>.glb``); das LOD1 ist höchstens so groß.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

from src.render3d import mesh  # noqa: E402

ORDNER = WURZEL / "assets" / "umgebung"


def grundriss(pfad: Path) -> list[float]:
    """``[x_min, x_max, y_min, y_max]`` über alle Punkte, auf Zentimeter nach außen gerundet."""
    lo, hi = mesh.laden(pfad).grenzen()
    return [math.floor(float(lo[0]) * 100) / 100, math.ceil(float(hi[0]) * 100) / 100,
            math.floor(float(lo[1]) * 100) / 100, math.ceil(float(hi[1]) * 100) / 100]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--alle", action="store_true", help="auch vorhandene Grundrisse neu messen")
    args = ap.parse_args()
    pfad = ORDNER / "katalog.json"
    katalog = json.loads(pfad.read_text(encoding="utf-8"))
    geaendert = 0
    for name, eintrag in katalog.items():
        if "grundriss_m" in eintrag and not args.alle:
            continue
        glb = ORDNER / f"{name}.glb"
        if not glb.is_file():
            print(f"[grundriss] fehlt: {glb}")
            continue
        eintrag["grundriss_m"] = grundriss(glb)
        geaendert += 1
        print(f"[grundriss] {name}: {eintrag['grundriss_m']}")
    # Wie ``gemeinsam.json_schreiben``: LF, zwei Leerzeichen, sortiert.
    with open(pfad, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(dict(sorted(katalog.items())), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"[grundriss] {geaendert} Einträge geschrieben")
    return 0


if __name__ == "__main__":
    sys.exit(main())
