"""Ein TRELLIS-GLB ohne Handarbeit spielfertig machen.

    python trellis_import.py rohdaten/rookie.glb --fahrzeug rookie
    python trellis_import.py rohdaten/rad.glb   --fahrzeug rookie --typ rad

Der Weg ist immer derselbe: ausrichten, auf Meter skalieren, Ursprung auf den
Bodenkontakt, pruefen, Lackmaske erzeugen, schreiben.

Was das Skript **nicht** kann und auch nicht koennen soll: Vorne und Hinten
auseinanderhalten. Motorhaube und Kofferraum sind sich zu aehnlich, und bei
einem Mittelmotor stimmt selbst die Faustregel nicht. Das steht deshalb je
Modell in ``trellis_import.json``:

    {"rookie": {"flip": false}, "supercar": {"flip": true}}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trellis_pipeline import (glb_io, orient, origin, paintmask, report,
                              vehicle_specs)

HIER = Path(__file__).resolve().parent

#: Wo die Fahrzeug-JSONs des 2D-Spiels liegen. Von dort kommen die Kennwerte
#: der Lackmaske - dieselben, die das Fahrzeuglabor am Sprite abgestimmt hat.
VEHICLES_VORGABE = Path(r"F:\Fahr-Rennspiel-2D\data\vehicles")

CONFIG_VORGABE = HIER / "trellis_import.json"
AUSGABE_VORGABE = HIER / "assets" / "vehicles"


def _flip(config_pfad: Path, key: str) -> bool:
    """Front/Heck-Entscheidung fuer dieses Modell. Fehlt sie, gilt False."""
    try:
        with open(config_pfad, encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        return False
    eintrag = config.get(key)
    return bool(eintrag.get("flip", False)) if isinstance(eintrag, dict) else False


def verarbeiten(quelle: Path, key: str, typ: str, config_pfad: Path,
                vehicles_dir: Path, ausgabe_dir: Path,
                raeder_trennen: bool = True) -> report.Bericht:
    soll = vehicle_specs.spec(key)
    mesh, hinweise = glb_io.laden(quelle)

    mesh = orient.ausrichten(mesh, flip=_flip(config_pfad, key), typ=typ)

    from trellis_pipeline import scale
    if typ == "rad":
        mesh = scale.auf_raddurchmesser(mesh, soll.rad_m)
        origin.auf_nabenmitte(mesh)
        ziel_glb = ausgabe_dir / f"{key}_rad.glb"
    else:
        mesh = scale.auf_ziellaenge(mesh, soll.laenge_m)
        origin.auf_bodenkontakt(mesh)
        ziel_glb = ausgabe_dir / f"{key}.glb"

    bericht = report.pruefen(mesh, soll, typ=typ)
    bericht.hinweise[:0] = hinweise
    print(bericht.text())

    if typ != "rad" and raeder_trennen:
        _mit_raedern(mesh, key, soll, ziel_glb, bericht)
    else:
        glb_io.speichern(mesh, ziel_glb)
        print(f"Geschrieben     {ziel_glb}")

    if typ != "rad":
        _lackmaske(mesh, key, vehicles_dir, ziel_glb, bericht)
    return bericht


def _mit_raedern(mesh, key: str, soll, ziel_glb: Path,
                 bericht: report.Bericht) -> None:
    """Raeder heraustrennen und als Szene mit benannten Knoten schreiben.

    Daneben eine JSON mit den Nabenpositionen: der Renderer muss wissen, um
    welchen Punkt er dreht und lenkt, und soll das nicht aus dem GLB
    zurueckrechnen muessen.
    """
    from trellis_pipeline import radschnitt

    zerlegt = radschnitt.schneiden(mesh, soll)
    bericht.hinweise.extend(zerlegt.hinweise)
    print(zerlegt.text())

    glb_io.speichern(zerlegt.als_szene(), ziel_glb)
    print(f"Geschrieben     {ziel_glb}   (Karosserie + {len(zerlegt.raeder)} Raeder)")

    teile = ziel_glb.with_name(f"{key}_teile.json")
    teile.write_text(json.dumps({
        "fahrzeug": key,
        "laenge_m": soll.laenge_m,
        "breite_m": soll.breite_m,
        "raddurchmesser_m": soll.rad_m,
        "radstand_m": soll.radstand_m,
        "achsen": {"vorne": ["rad_vl", "rad_vr"], "hinten": ["rad_hl", "rad_hr"]},
        "gelenkt": ["rad_vl", "rad_vr"],
        "raeder": [{
            "name": r.name,
            "nabe": [round(v, 5) for v in r.nabe],
            "dreiecke": int(len(r.mesh.faces)),
        } for r in zerlegt.raeder],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Teileliste      {teile}")


def _lackmaske(mesh, key: str, vehicles_dir: Path, ziel_glb: Path,
               bericht: report.Bericht) -> None:
    """Lackmaske neben das GLB legen - oder begruenden, warum nicht."""
    textur = glb_io.basis_textur(mesh)
    if textur is None:
        bericht.hinweise.append("Keine Base-Color-Textur - keine Lackmaske erzeugt")
        print("HINWEIS         Keine Base-Color-Textur - keine Lackmaske erzeugt")
        return

    werte = paintmask.paint_werte(key, vehicles_dir)
    if werte["verfahren"] == "aus":
        print(f"HINWEIS         {key}.json hat verfahren='aus' - keine Lackmaske. "
              f"Kennwerte im Fahrzeuglabor abstimmen.")
        return

    gewicht = paintmask.maske(textur, werte)
    ziel_png = ziel_glb.with_name(f"{key}_lackmaske.png")
    paintmask.als_png(gewicht).save(ziel_png)
    anteil = float(gewicht.mean()) * 100.0
    print(f"Lackmaske       {ziel_png}  ({anteil:.1f} % der Texturflaeche)")
    if anteil < 2.0:
        print("WARNUNG         Maske trifft fast nichts - Kennwerte pruefen")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="TRELLIS-GLB zu einem spielfertigen Asset aufbereiten.")
    p.add_argument("glb", type=Path, help="Pfad zum generierten GLB")
    p.add_argument("--fahrzeug", required=True,
                   help="Fahrzeugkonfiguration, z.B. rookie oder limousine_2")
    p.add_argument("--typ", choices=("karosserie", "rad"), default="karosserie",
                   help="karosserie (Vorgabe) oder rad")
    p.add_argument("--config", type=Path, default=CONFIG_VORGABE,
                   help=f"Front/Heck je Modell (Vorgabe: {CONFIG_VORGABE.name})")
    p.add_argument("--vehicles-dir", type=Path, default=VEHICLES_VORGABE,
                   help="Ordner mit den Fahrzeug-JSONs des 2D-Spiels")
    p.add_argument("--out", type=Path, default=AUSGABE_VORGABE,
                   help="Ausgabeordner")
    p.add_argument("--keine-raeder", action="store_true",
                   help="Raeder nicht heraustrennen, ein Netz ausgeben")
    a = p.parse_args(argv)

    if not a.glb.is_file():
        print(f"FEHLER: {a.glb} nicht gefunden", file=sys.stderr)
        return 2
    try:
        bericht = verarbeiten(a.glb, a.fahrzeug, a.typ, a.config,
                              a.vehicles_dir, a.out,
                              raeder_trennen=not a.keine_raeder)
    except (KeyError, ValueError) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        return 2
    # Warnungen sind Massabweichungen. Sie brechen nichts ab, aber der
    # Rueckgabewert soll sie sichtbar machen, wenn das Skript in einer
    # Schleife ueber alle 15 Fahrzeuge laeuft.
    return 1 if bericht.warnungen else 0


if __name__ == "__main__":
    raise SystemExit(main())
