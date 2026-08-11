"""Profil auslesen und zurückschreiben (data/settings/profile.json).

Seit Releaseplan E4 liegt das Profil verschlüsselt und signiert ab. Das kostet
genau eine Bequemlichkeit, die beim Entwickeln oft gebraucht wird: die Datei mal
eben im Editor öffnen. Dieses Werkzeug gibt sie zurück:

    python tools/profil_werkzeug.py                     # Klartext ausgeben
    python tools/profil_werkzeug.py > p.json            # ... in eine Datei
    python tools/profil_werkzeug.py --schreiben p.json  # bearbeitet zurück
    python tools/profil_werkzeug.py --pfad andere.json  # anderes Profil

Beim Schreiben legt der Tresor wie im Spiel eine ``profile.bak`` an — ein
vertippter Zähler ist damit ein Dateikopieren weit weg von behoben.

Zur Erinnerung: verschlüsselt heißt hier *Bremsschwelle*, nicht Schutz. Der
Schlüssel steht in ``src/core/tresor.py``, und genau deshalb funktioniert dieses
Werkzeug überhaupt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core import tresor  # noqa: E402


def _standardpfad() -> str:
    return os.path.join("data", "settings", "profile.json")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pfad", default=_standardpfad(), help="Profildatei")
    p.add_argument("--schreiben", metavar="KLARTEXT.json",
                   help="diese JSON-Datei verschlüsselt ins Profil schreiben")
    args = p.parse_args()

    if args.schreiben:
        with open(args.schreiben, encoding="utf-8") as f:
            daten = json.load(f)          # bewusst streng: lieber hier scheitern
        if not isinstance(daten, dict):
            print("Das Profil muss ein JSON-Objekt sein.", file=sys.stderr)
            return 2
        tresor.schreiben(args.pfad, json.dumps(daten, indent=2, ensure_ascii=False))
        print(f"{args.pfad} geschrieben, Sicherung in {tresor.bak_pfad(args.pfad)}",
              file=sys.stderr)
        return 0

    klar = tresor.lesen(args.pfad)
    if klar is None:
        print(f"{args.pfad}: nicht lesbar (weder Hauptdatei noch Sicherung).",
              file=sys.stderr)
        return 1
    print(klar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
