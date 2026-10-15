"""Verwaltung der gemeldeten Spieler (Online-Schutz, Plan 1.1.0) - Kommandozeile.

Arbeitet direkt auf ``meldungen.json`` im Meldeverzeichnis des Relays
(``RACE_MELDUNGEN_DIR``, Vorgabe ``server/meldungen`` im Repo). Der Server muss
dafuer weder laufen noch gestoppt sein: er liest die Datei neu, sobald sie sich
aendert. Es wird nichts importiert - die Datei laesst sich allein auf den Relay
kopieren.

    python tools/meldungen_verwalten.py list                 alle Meldungen
    python tools/meldungen_verwalten.py list --offen         nur unerledigte
    python tools/meldungen_verwalten.py list --spiel 3d      nur ein Spiel
    python tools/meldungen_verwalten.py list --ziel NAME     nur gegen diesen Spieler
    python tools/meldungen_verwalten.py top                  wer am haeufigsten gemeldet wurde
    python tools/meldungen_verwalten.py zeige ID             eine Meldung im Detail
    python tools/meldungen_verwalten.py erledigt ID [ID ..]  als bearbeitet markieren
    python tools/meldungen_verwalten.py loeschen ID [ID ..]  endgueltig entfernen
    python tools/meldungen_verwalten.py loeschen --alle      alles entfernen
    python tools/meldungen_verwalten.py loeschen --aelter-als TAGE
    python tools/meldungen_verwalten.py --dir PFAD ...       anderes Verzeichnis

Spalte ``Marken``: was der Relay in der Lobby selbst an dem gemeldeten Spieler
beobachtet hat (``SPRUNG``, ``TEMPO_WEG``, ``ZEIT_ZU_KURZ`` ...). Eine Meldung
mit Marken wiegt schwerer als eine ohne. Gemeldet wird in der Ergebnisliste,
ueber die Meldekennung ``melder_key`` (gesalzener Hash) erkennt man mehrfache
Melder, ohne dass Adressen im Klartext stehen.
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
    env = os.environ.get("RACE_MELDUNGEN_DIR")
    if env:
        return env
    hier = os.path.dirname(os.path.abspath(__file__))
    for kandidat in (os.path.join(os.path.dirname(hier), "server", "meldungen"),
                     os.path.join(hier, "meldungen")):
        if os.path.isdir(kandidat):
            return kandidat
    return os.path.join(os.path.dirname(hier), "server", "meldungen")


class Ablage:
    def __init__(self, verzeichnis: str) -> None:
        self.pfad = os.path.join(verzeichnis, "meldungen.json")
        self.daten = self._lesen()

    def _lesen(self) -> dict:
        try:
            with open(self.pfad, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and isinstance(d.get("meldungen"), list):
                return d
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            print(f"Datei unlesbar ({exc}).", file=sys.stderr)
        return {"version": 1, "salz": "", "meldungen": []}

    @property
    def liste(self) -> list:
        return self.daten["meldungen"]

    def speichern(self) -> None:
        tmp = self.pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.daten, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.pfad)

    def finde(self, mid: str):
        return next((m for m in self.liste if m.get("id") == mid), None)


def _zeile(m: dict) -> str:
    zeit = time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(m.get("zeit", 0))))
    marken = ",".join(m.get("marken", [])) or "-"
    status = "erledigt" if m.get("erledigt") else "offen"
    return (f"{m.get('id', '?'):<8}  {zeit}  {str(m.get('spiel', '')):<2}  "
            f"{str(m.get('ziel', {}).get('name', ''))[:18]:<18}  "
            f"{str(m.get('grund', ''))[:9]:<9}  "
            f"von {str(m.get('melder', {}).get('name', ''))[:15]:<15}  "
            f"{status:<8}  Marken: {marken}").rstrip()


def _ids_pruefen(ids: list[str]) -> list[str]:
    gut = []
    for i in ids:
        if _ID.match(i.lower()):
            gut.append(i.lower())
        else:
            print(f"Ungueltige Kennung: {i!r} (acht Hexzeichen erwartet)", file=sys.stderr)
    return gut


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Gemeldete Spieler des Relays verwalten.")
    ap.add_argument("--dir", default=None, help="Meldeverzeichnis (Vorgabe: RACE_MELDUNGEN_DIR)")
    sub = ap.add_subparsers(dest="befehl", required=True)
    p = sub.add_parser("list", help="Meldungen auflisten")
    p.add_argument("--offen", action="store_true", help="nur unerledigte")
    p.add_argument("--spiel", choices=("2d", "3d"))
    p.add_argument("--ziel", help="Name des gemeldeten Spielers")
    sub.add_parser("top", help="meistgemeldete Spieler")
    p = sub.add_parser("zeige", help="eine Meldung im Detail")
    p.add_argument("id")
    p = sub.add_parser("erledigt", help="als bearbeitet markieren")
    p.add_argument("ids", nargs="+")
    p = sub.add_parser("loeschen", help="Meldungen entfernen")
    p.add_argument("ids", nargs="*")
    p.add_argument("--alle", action="store_true")
    p.add_argument("--aelter-als", type=int, metavar="TAGE", dest="aelter")
    arg = ap.parse_args(argv)

    verzeichnis = arg.dir or standard_verzeichnis()
    if not os.path.isdir(verzeichnis):
        print(f"Kein Verzeichnis: {verzeichnis}", file=sys.stderr)
        return 2
    ab = Ablage(verzeichnis)

    if arg.befehl == "list":
        z = sorted(ab.liste, key=lambda m: -int(m.get("zeit", 0)))
        if arg.offen:
            z = [m for m in z if not m.get("erledigt")]
        if arg.spiel:
            z = [m for m in z if m.get("spiel") == arg.spiel]
        if arg.ziel:
            z = [m for m in z if str(m.get("ziel", {}).get("name", "")).lower() == arg.ziel.lower()]
        for m in z:
            print(_zeile(m))
        print(f"{len(z)} angezeigt, {len(ab.liste)} gespeichert")
        return 0

    if arg.befehl == "top":
        zaehler: dict[str, list] = {}
        for m in ab.liste:
            ziel = m.get("ziel", {})
            k = str(ziel.get("cid") or ziel.get("name"))
            e = zaehler.setdefault(k, [str(ziel.get("name", "")), 0, set()])
            e[1] += 1
            e[2].update(m.get("marken", []))
        for k, (name, n, marken) in sorted(zaehler.items(), key=lambda kv: -kv[1][1])[:20]:
            print(f"{n:>3}  {name[:20]:<20}  Marken: {','.join(sorted(marken)) or '-'}")
        return 0

    if arg.befehl == "zeige":
        m = ab.finde(arg.id.lower())
        if m is None:
            print("Unbekannte Kennung.", file=sys.stderr)
            return 1
        print(json.dumps(m, ensure_ascii=False, indent=1))
        return 0

    if arg.befehl == "erledigt":
        fehlt = 0
        for mid in _ids_pruefen(arg.ids):
            m = ab.finde(mid)
            if m is None:
                print(f"{mid}: nicht gefunden", file=sys.stderr)
                fehlt += 1
            else:
                m["erledigt"] = True
                print(f"erledigt: {mid}")
        ab.speichern()
        return 1 if fehlt else 0

    # loeschen
    vorher = len(ab.liste)
    if arg.alle:
        ab.daten["meldungen"] = []
    elif arg.aelter is not None:
        grenze = time.time() - arg.aelter * 86400
        ab.daten["meldungen"] = [m for m in ab.liste if int(m.get("zeit", 0)) >= grenze]
    elif arg.ids:
        weg = set(_ids_pruefen(arg.ids))
        vorhanden = {m.get("id") for m in ab.liste}
        for i in sorted(weg - vorhanden):
            print(f"{i}: nicht gefunden", file=sys.stderr)
        ab.daten["meldungen"] = [m for m in ab.liste if m.get("id") not in weg]
        if not (weg & vorhanden):
            return 1
    else:
        print("Nichts angegeben: IDs, --alle oder --aelter-als TAGE.", file=sys.stderr)
        return 2
    ab.speichern()
    print(f"{vorher - len(ab.liste)} entfernt, {len(ab.liste)} uebrig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
