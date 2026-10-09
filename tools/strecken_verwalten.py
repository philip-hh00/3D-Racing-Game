"""Verwaltung der online abgelegten Strecken (Plan 1.1.0 §5) — Kommandozeile.

Arbeitet direkt auf dem Speicherverzeichnis des Relays (``RACE_STRECKEN_DIR``,
Vorgabe ``strecken_online`` neben ``server.py``) und braucht den Server weder
laufend noch gestoppt: der Server prueft den Index bei jeder Anfrage auf
Aenderungen. Es wird nichts importiert — die Datei laesst sich allein auf den
Relay kopieren.

    python tools/strecken_verwalten.py list                 alle Strecken
    python tools/strecken_verwalten.py list --versteckt     nur gemeldete
    python tools/strecken_verwalten.py zeige ID             eine Strecke im Detail
    python tools/strecken_verwalten.py loeschen ID [ID ...] endgueltig entfernen
    python tools/strecken_verwalten.py freigeben ID [ID ..] wieder sichtbar, Meldungen null
    python tools/strecken_verwalten.py verstecken ID [ID ..] von Hand verstecken
    python tools/strecken_verwalten.py --dir PFAD ...       anderes Verzeichnis

Eine geloeschte Strecke darf danach wieder hochgeladen werden (die
Duplikatsperre haengt an der Datei). Eine nur versteckte Strecke bleibt gesperrt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

_ID = re.compile(r"^[0-9a-f]{8}$")


def standard_verzeichnis() -> str:
    env = os.environ.get("RACE_STRECKEN_DIR")
    if env:
        return env
    hier = os.path.dirname(os.path.abspath(__file__))
    for kandidat in (os.path.join(hier, "strecken_online"),
                     os.path.join(os.path.dirname(hier), "server", "strecken_online")):
        if os.path.isdir(kandidat):
            return kandidat
    return os.path.join(hier, "strecken_online")


class Ablage:
    """Lesen und Schreiben von ``index.json`` und ``<id>.json``."""

    def __init__(self, verzeichnis: str) -> None:
        self.verzeichnis = verzeichnis
        self.index_pfad = os.path.join(verzeichnis, "index.json")
        self.daten = self._lesen()

    def _lesen(self) -> dict:
        try:
            with open(self.index_pfad, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("tracks"), dict):
                return d
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            print(f"Index unlesbar ({exc}); der Server baut ihn beim Start neu auf.",
                  file=sys.stderr)
        return {"version": 1, "salz": "", "tag": "", "zaehler": {}, "tracks": {}}

    @property
    def tracks(self) -> dict:
        return self.daten["tracks"]

    def speichern(self) -> None:
        tmp = self.index_pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.daten, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, self.index_pfad)

    def datei(self, tid: str) -> str:
        return os.path.join(self.verzeichnis, f"{tid}.json")

    def loeschen(self, tid: str) -> bool:
        gefunden = self.tracks.pop(tid, None) is not None
        try:
            os.remove(self.datei(tid))
            gefunden = True
        except FileNotFoundError:
            pass
        if gefunden:
            self.speichern()
        return gefunden

    def freigeben(self, tid: str) -> bool:
        t = self.tracks.get(tid)
        if t is None:
            return False
        t["hidden"] = False
        t["reports"] = []
        self.speichern()
        return True

    def verstecken(self, tid: str) -> bool:
        t = self.tracks.get(tid)
        if t is None:
            return False
        t["hidden"] = True
        self.speichern()
        return True


def _zeile(t: dict) -> str:
    datum = time.strftime("%Y-%m-%d", time.gmtime(int(t.get("created", 0))))
    marke = "VERSTECKT" if t.get("hidden") else ""
    return (f"{t['id']}  {datum}  {str(t.get('name', ''))[:30]:<30}  "
            f"{str(t.get('author', ''))[:20]:<20}  "
            f"{int(t.get('downloads', 0)):>5} Abrufe  "
            f"{len(t.get('reports', [])):>2} Meldungen  {marke}").rstrip()


def _ids_pruefen(ids: list[str]) -> list[str]:
    gut = [i.lower() for i in ids if _ID.match(i.lower())]
    for i in ids:
        if not _ID.match(i.lower()):
            print(f"Ungueltige Kennung: {i!r} (acht Hexzeichen erwartet)", file=sys.stderr)
    return gut


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Online-Strecken des Relays verwalten.")
    ap.add_argument("--dir", default=None, help="Speicherverzeichnis (Vorgabe: RACE_STRECKEN_DIR)")
    sub = ap.add_subparsers(dest="befehl", required=True)
    p = sub.add_parser("list", help="Strecken auflisten")
    p.add_argument("--versteckt", action="store_true", help="nur versteckte")
    p = sub.add_parser("zeige", help="eine Strecke im Detail")
    p.add_argument("id")
    for name in ("loeschen", "freigeben", "verstecken"):
        p = sub.add_parser(name)
        p.add_argument("ids", nargs="+")
    arg = ap.parse_args(argv)

    verzeichnis = arg.dir or standard_verzeichnis()
    if not os.path.isdir(verzeichnis):
        print(f"Kein Verzeichnis: {verzeichnis}", file=sys.stderr)
        return 2
    ab = Ablage(verzeichnis)

    if arg.befehl == "list":
        zeilen = sorted(ab.tracks.values(), key=lambda t: -int(t.get("created", 0)))
        if arg.versteckt:
            zeilen = [t for t in zeilen if t.get("hidden")]
        for t in zeilen:
            print(_zeile(t))
        groesse = sum(int(t.get("bytes", 0)) for t in ab.tracks.values())
        print(f"{len(zeilen)} angezeigt, {len(ab.tracks)} gespeichert, {groesse / 1024:.0f} KB")
        return 0

    if arg.befehl == "zeige":
        t = ab.tracks.get(arg.id.lower())
        if t is None:
            print("Unbekannte Kennung.", file=sys.stderr)
            return 1
        for k in ("id", "name", "author", "theme", "difficulty", "length", "pieces",
                  "downloads", "hidden", "created", "bytes", "hash"):
            print(f"{k:<11} {t.get(k)}")
        print(f"{'reports':<11} {len(t.get('reports', []))}")
        return 0

    aktion = {"loeschen": ab.loeschen, "freigeben": ab.freigeben,
              "verstecken": ab.verstecken}[arg.befehl]
    fehlt = 0
    for tid in _ids_pruefen(arg.ids):
        if aktion(tid):
            print(f"{arg.befehl}: {tid}")
        else:
            print(f"{tid}: nicht gefunden", file=sys.stderr)
            fehlt += 1
    return 1 if fehlt else 0


if __name__ == "__main__":
    sys.exit(main())
