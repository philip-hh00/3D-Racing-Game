"""Tonspur aus Videoaufnahmen ziehen und als WAV ablegen (Block C).

    py -3.11 tools/video_ton_extrahieren.py <quellordner> [--ziel <ordner>]

Hintergrund: die Motoraufnahmen entstanden mit einem Bildschirmaufzeichner und
liegen deshalb als MP4 vor. Für die Weiterverarbeitung zählt nur der Ton — das
Video ist reiner Speicherverbrauch.

Der Decoder kommt aus ``imageio-ffmpeg``: das Paket bringt eine eigene
ffmpeg-Binärdatei mit und braucht keine Systeminstallation. Ohne einen Decoder
ist an den Ton eines MP4 nicht heranzukommen; ``soundfile`` liest nur reine
Audioformate.

Der Dateiname wird übernommen, weil er die Drehzahl trägt (``3600-1-min.mp4``
→ 3600 U/min). ``Leerlauf`` wird als solcher erkannt und bekommt die Drehzahl
erst später, aus der gemessenen Zündfrequenz.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

SR = 48000


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("imageio-ffmpeg fehlt: py -3.11 -m pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


#: Drehzahl, unter der eine „Leerlauf"-Aufnahme geführt wird. Aus dem Namen
#: geht sie nicht hervor, gemessen wurde sie beim Aufnehmen.
LEERLAUF_UPM = {"6zyl": 1250}


def upm_aus_name(name: str) -> int | None:
    """Drehzahl aus dem Dateinamen, 0 bei Leerlauf, None wenn unklar."""
    if re.search(r"leerlauf|idle", name, re.IGNORECASE):
        return 0
    treffer = re.match(r"^(\d{3,5})", os.path.basename(name))
    return int(treffer.group(1)) if treffer else None


def motor_aus_name(name: str, standard: str) -> str:
    """Motorkennung aus dem Dateinamen, z.B. ``4260-1-min-8-zyl.mp4`` → 8zyl.

    Die Aufnahmen mehrerer Motoren liegen im selben Ordner. Ohne diese
    Zuordnung landeten alle Drehzahlen in einem Topf, und die Schichten hätten
    zwischen Motoren übergeblendet — hörbar als Wechsel des Fahrzeugs mitten
    im Hochdrehen.
    """
    treffer = re.search(r"(\d+)\s*-?\s*zyl", name, re.IGNORECASE)
    return f"{treffer.group(1)}zyl" if treffer else standard


def extrahieren(quelle: str, ziel: str, exe: str) -> None:
    """Tonspur nach WAV, 48 kHz, Mono.

    Mono mit Absicht: die Aufnahme ist ein Bildschirmmitschnitt, beide Kanäle
    tragen dasselbe Signal. Mono halbiert den Speicher und macht die spätere
    Verteilung im Raum (ein Kanal je Fahrzeug) einfacher.
    """
    befehl = [exe, "-y", "-loglevel", "error", "-i", quelle,
              "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", ziel]
    subprocess.run(befehl, check=True)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("quelle", help="Ordner mit den Videodateien")
    p.add_argument("--ziel", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "audio", "sfx", "aufnahmen"))
    p.add_argument("--motor", default="v8",
                   help="Kennung für die Benennung, z.B. v8 oder 4zyl")
    args = p.parse_args()

    exe = ffmpeg()
    os.makedirs(args.ziel, exist_ok=True)

    videos = sorted(f for f in os.listdir(args.quelle)
                    if f.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")))
    if not videos:
        print(f"Keine Videos in {args.quelle}")
        return 1

    for name in videos:
        upm = upm_aus_name(name)
        if upm is None:
            print(f"  ! {name}: keine Drehzahl im Namen erkennbar, übersprungen")
            continue
        motor = motor_aus_name(name, args.motor)
        if upm == 0:
            upm = LEERLAUF_UPM.get(motor, 0)
            if not upm:
                print(f"  ! {name}: Leerlaufdrehzahl für {motor} unbekannt, "
                      f"in LEERLAUF_UPM ergänzen")
                continue
        ziel_name = f"{motor}-{upm:04d}.wav"
        ziel = os.path.join(args.ziel, ziel_name)
        extrahieren(os.path.join(args.quelle, name), ziel, exe)
        groesse = os.path.getsize(ziel)
        print(f"{name:<26} -> {ziel_name:<16} {groesse/1024/1024:5.1f} MB")

    print(f"\n-> {args.ziel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
