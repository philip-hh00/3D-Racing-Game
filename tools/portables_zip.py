"""Portables ZIP aus einem Ordner - butler-tauglich (itch.io/GameJolt).

Aufruf:  python tools/portables_zip.py <quelle-ordner> <ziel.zip>

Warum nicht PowerShells Compress-Archive (Fund 08.08.2026): butler lehnte das so
erzeugte Archiv ab -- "Invalid container ... Two entries have the same name":

    -rw-rw-rw-  0 B  2D-Racing-Game/_internal/numpy
    -rwxr-xr-x   -   2D-Racing-Game/_internal/numpy/

Compress-Archive legt fuer einen Unterordner zusaetzlich einen 0-Byte-Eintrag
OHNE Schraegstrich an (die "Datei" numpy neben dem Ordner numpy/). butlers
Container-Pruefung sieht darin Datei und Ordner gleichen Namens und bricht ab.

zipfile schreibt saubere Eintraege: Dateien mit vollem Pfad, Ordner nur
implizit (aus den Dateipfaden) bzw. leere Ordner ausdruecklich MIT Schraegstrich
-- nie die Datei-ohne-Schraegstrich-Form, die den Konflikt ausloest. Alle Pfade
mit Vorwaerts-Schraegstrich, damit sie plattformuebergreifend stimmen.
"""
from __future__ import annotations

import os
import sys
import zipfile


def packe(quelle: str, ziel: str) -> None:
    quelle = os.path.abspath(quelle)
    if not os.path.isdir(quelle):
        raise SystemExit(f"[FEHLER] Quelle ist kein Ordner: {quelle}")
    # Der Ordnername (2D-Racing-Game) soll die oberste Ebene im Archiv sein.
    basis = os.path.dirname(quelle)
    zielabs = os.path.abspath(ziel)
    os.makedirs(os.path.dirname(zielabs), exist_ok=True)
    if os.path.exists(zielabs):
        os.remove(zielabs)

    with zipfile.ZipFile(zielabs, "w", zipfile.ZIP_DEFLATED) as z:
        for ordner, unterordner, dateien in os.walk(quelle):
            # Leere Ordner ausdruecklich mitnehmen - aber mit Schraegstrich,
            # nie als Datei ohne Schraegstrich (genau das war der butler-Fehler).
            if not dateien and not unterordner:
                rel = os.path.relpath(ordner, basis).replace(os.sep, "/") + "/"
                z.writestr(rel, "")
                continue
            for name in dateien:
                voll = os.path.join(ordner, name)
                rel = os.path.relpath(voll, basis).replace(os.sep, "/")
                z.write(voll, rel)
    print(zielabs)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Aufruf: portables_zip.py <quelle-ordner> <ziel.zip>", file=sys.stderr)
        raise SystemExit(2)
    packe(sys.argv[1], sys.argv[2])
