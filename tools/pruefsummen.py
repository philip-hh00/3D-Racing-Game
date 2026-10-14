"""Pruefsummen der spielrelevanten Dateien: fuers Spiel und fuer den Relay.

Siehe ``src/core/integritaet.py`` (was geprueft wird und wie) und
``server/schutz.py`` (was der Relay damit macht).

    python tools/pruefsummen.py                  Bauschritt: signierte Liste fuers
                                                 Spiel schreiben (data/settings/
                                                 pruefsummen.json, ins Paket)
    python tools/pruefsummen.py --eintragen      Summe dieses Releases in
                                                 server/pruefsummen.json eintragen
    python tools/pruefsummen.py --eintragen DATEI [DATEI ...]
                                                 ... in diese Dateien (z. B. in das
                                                 Repo des Relays, siehe unten)
    python tools/pruefsummen.py --pruefen        Exit 1, wenn server/pruefsummen.json
                                                 nicht zu den Dateien passt (Release-
                                                 Pipeline, vor dem Taggen)
    python tools/pruefsummen.py --zeigen         Summe und Dateiliste ausgeben

**Release-Ablauf.** Die Relais laufen mit dem Server aus dem Repo des 2D-Spiels,
und der muss die Summen *beider* Spiele kennen. Pro Spiel und Version einmal:

1. Daten sind fertig, Version steht in ``src/core/version.py``.
2. ``python tools/pruefsummen.py --eintragen server/pruefsummen.json
   <Pfad-zum-anderen-Repo>/server/pruefsummen.json`` — der Eintrag ``(Spiel,
   Version)`` wird ersetzt, alles andere bleibt. Dasselbe im anderen Spiel.
3. Beide ``server/pruefsummen.json`` committen, dann taggen. Der Server liest die
   Datei bei jedem Beitritt neu, wenn sie sich geaendert hat: ein
   ``git pull`` auf dem Relay genuegt, kein Neustart.

``--pruefen`` laeuft vor dem Taggen (``release_starten``) und in der Pipeline
(``.github/workflows/release.yml``, auf jedem Bauknecht, also auch unter macOS):
so faellt auf, wenn die Datei zu den ausgelieferten Dateien nicht passt oder die
Summe unter Windows und macOS auseinanderlaeuft.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL))

from src.core import integritaet  # noqa: E402
from src.core.version import VERSION  # noqa: E402

STANDARD = WURZEL / "server" / "pruefsummen.json"


def _lesen(pfad: Path) -> dict:
    try:
        d = json.loads(pfad.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("spiele"), dict):
            return d
    except FileNotFoundError:
        pass
    except ValueError as exc:
        print(f"{pfad}: unlesbar ({exc}) - wird neu angelegt", file=sys.stderr)
    return {"format": 1, "spiele": {}}


def eintragen(pfad: Path, eintrag: dict) -> None:
    d = _lesen(pfad)
    d["spiele"].setdefault(integritaet.SPIEL, {})[VERSION] = eintrag
    d["spiele"] = {k: dict(sorted(v.items())) for k, v in sorted(d["spiele"].items())}
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def abweichungen(pfad: Path, eintrag: dict) -> list[str]:
    alt = _lesen(pfad)["spiele"].get(integritaet.SPIEL, {}).get(VERSION)
    if alt is None:
        return [f"kein Eintrag fuer {integritaet.SPIEL} {VERSION}"]
    fehler = []
    if eintrag["summen"][0] not in alt.get("summen", []):
        fehler.append("Summe passt nicht")
    for k in ("fahrzeuge", "strecken"):
        if alt.get(k) != eintrag[k]:
            fehler.append(f"{k} passen nicht")
    return fehler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    gruppe = ap.add_mutually_exclusive_group()
    gruppe.add_argument("--eintragen", nargs="*", metavar="DATEI", default=None)
    gruppe.add_argument("--pruefen", nargs="?", const=str(STANDARD), default=None,
                        metavar="DATEI")
    gruppe.add_argument("--zeigen", action="store_true")
    arg = ap.parse_args(argv)

    if arg.zeigen:
        for rel, h in integritaet.hashes(WURZEL).items():
            print(f"{h[:16]}  {rel}")
        print(f"Summe {integritaet.SPIEL} {VERSION}: {integritaet.digest(WURZEL)}")
        return 0

    if arg.eintragen is not None:
        eintrag = integritaet.server_eintrag(WURZEL)
        for ziel in [Path(p) for p in arg.eintragen] or [STANDARD]:
            eintragen(ziel, eintrag)
            print(f"{ziel}: {integritaet.SPIEL} {VERSION} = {eintrag['summen'][0][:16]}... "
                  f"({eintrag['dateien']} Dateien)")
        return 0

    if arg.pruefen is not None:
        eintrag = integritaet.server_eintrag(WURZEL)
        fehler = abweichungen(Path(arg.pruefen), eintrag)
        if fehler:
            print(f"[FEHLER] {arg.pruefen} passt nicht zum Stand "
                  f"({integritaet.SPIEL} {VERSION}): {', '.join(fehler)}", file=sys.stderr)
            print("         Abhilfe: python tools/pruefsummen.py --eintragen "
                  "(siehe Kopf dieser Datei), dann committen.", file=sys.stderr)
            return 1
        print(f"Pruefsummen in Ordnung: {integritaet.SPIEL} {VERSION} "
              f"{eintrag['summen'][0][:16]}...")
        return 0

    pfad = integritaet.schreiben(WURZEL)
    print(f"Pruefsummen: {pfad} ({len(integritaet.hashes(WURZEL))} Dateien)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
