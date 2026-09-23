"""CC0-Material für die Umgebung laden und aufbereiten.

Liest ``tools/blender/cc0_liste.json`` und holt von Poly Haven (CC0 1.0):

* Modelle als glTF in 1k nach ``rohdaten/cc0/modelle/<id>/`` — Rohmaterial
  für ``tools/blender/umgebung_bauen.py``,
* Oberflächentexturen nach ``rohdaten/cc0/texturen/`` und daraus
  spielfertig nach ``assets/texturen/<name>_farbe.jpg`` und
  ``<name>_mr.png`` (Rauheit im Grünkanal, wie glTF es erwartet),
* Himmel (HDRI, 2k) nach ``rohdaten/cc0/himmel/`` — umgerechnet von
  ``tools/blender/himmel_bauen.py``.

Schon vorhandene Dateien werden nicht erneut geladen. Aufruf::

    .venv\\Scripts\\python.exe tools\\assets_laden.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
LISTE = WURZEL / "tools" / "blender" / "cc0_liste.json"
ROH = WURZEL / "rohdaten" / "cc0"
TEXTUREN = WURZEL / "assets" / "texturen"
API = "https://api.polyhaven.com/files/"
KENNUNG = {"User-Agent": "3D-Racing-Game asset builder (local, CC0)"}

#: Kantenlänge der Spieltexturen. 1024 reicht bei 4-8 m Kachellänge und hält
#: den Grafikspeicher klein.
SPIELGROESSE = 1024


def holen(url: str) -> bytes:
    for versuch in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=KENNUNG),
                                        timeout=120) as antwort:
                return antwort.read()
        except OSError as fehler:
            if versuch == 3:
                raise
            print(f"  erneut ({fehler})")
            time.sleep(2 + versuch * 3)
    raise RuntimeError("unerreichbar")


def speichern(url: str, ziel: Path) -> None:
    if ziel.is_file() and ziel.stat().st_size > 0:
        return
    ziel.parent.mkdir(parents=True, exist_ok=True)
    daten = holen(url)
    ziel.write_bytes(daten)
    print(f"  {ziel.relative_to(WURZEL)} ({len(daten) // 1024} KB)")


def dateiliste(asset: str) -> dict:
    return json.loads(holen(API + asset).decode("utf-8"))


def modell_laden(asset: str) -> None:
    ordner = ROH / "modelle" / asset
    if (ordner / f"{asset}.gltf").is_file():
        return
    print(f"Modell {asset}")
    eintrag = dateiliste(asset)["gltf"]["1k"]["gltf"]
    for pfad, info in eintrag.get("include", {}).items():
        speichern(info["url"], ordner / pfad)
    speichern(eintrag["url"], ordner / f"{asset}.gltf")


def textur_laden(name: str, asset: str) -> None:
    farbe = TEXTUREN / f"{name}_farbe.jpg"
    mr = TEXTUREN / f"{name}_mr.png"
    if farbe.is_file() and mr.is_file():
        return
    print(f"Textur {name} ({asset})")
    dateien = dateiliste(asset)
    roh_farbe = ROH / "texturen" / f"{asset}_diff.jpg"
    roh_rau = ROH / "texturen" / f"{asset}_rough.jpg"
    speichern(dateien["Diffuse"]["2k"]["jpg"]["url"], roh_farbe)
    if "Rough" in dateien:
        speichern(dateien["Rough"]["2k"]["jpg"]["url"], roh_rau)

    from PIL import Image
    TEXTUREN.mkdir(parents=True, exist_ok=True)
    bild = Image.open(roh_farbe).convert("RGB").resize(
        (SPIELGROESSE, SPIELGROESSE), Image.LANCZOS)
    bild.save(farbe, quality=90)
    if roh_rau.is_file():
        rau = Image.open(roh_rau).convert("L").resize(
            (SPIELGROESSE // 2, SPIELGROESSE // 2), Image.LANCZOS)
    else:
        rau = Image.new("L", (SPIELGROESSE // 2, SPIELGROESSE // 2), 200)
    null = Image.new("L", rau.size, 0)
    Image.merge("RGB", (null, rau, null)).save(mr)


def himmel_laden(thema: str, asset: str) -> None:
    ziel = ROH / "himmel" / f"{asset}.hdr"
    if ziel.is_file():
        return
    print(f"Himmel {thema} ({asset})")
    speichern(dateiliste(asset)["hdri"]["2k"]["hdr"]["url"], ziel)


def blatt_laden(name: str, asset: str, farbe_schluessel: str, alpha_schluessel) -> None:
    """Blattkarten mit Alphakanal für die Bäume.

    Die glTF-Fassungen bei Poly Haven tragen JPG ohne Alpha; für
    ausgestanzte Blätter braucht es das PNG, bei manchen Assets als getrennte
    Alphamaske. Zusammengeführt wird zu einem RGBA-Bild.
    """
    ziel = ROH / "blaetter" / f"{name}.png"
    if ziel.is_file():
        return
    print(f"Blaetter {name} ({asset})")
    from PIL import Image
    import io
    dateien = dateiliste(asset)
    farbe = Image.open(io.BytesIO(holen(dateien[farbe_schluessel]["1k"]["png"]["url"])))
    farbe = farbe.convert("RGBA")
    if alpha_schluessel:
        maske = Image.open(io.BytesIO(holen(dateien[alpha_schluessel]["1k"]["png"]["url"])))
        farbe.putalpha(maske.convert("L").resize(farbe.size))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    farbe.save(ziel)


def lizenzen_schreiben(liste: dict) -> None:
    zeilen = [
        "# Lizenzen der Spielassets",
        "",
        "Alle Fahrzeuge, Gebäude, Bäume, Leitplanken und Streckenteile unter",
        "`assets/vehicles/` und `assets/umgebung/` sind mit den Skripten unter",
        "`tools/blender/` selbst erzeugt. Zusätzlich verwendetes Fremdmaterial",
        "stammt ausschließlich von [Poly Haven](https://polyhaven.com) und steht",
        "unter **CC0 1.0** (gemeinfrei, keine Namensnennung nötig — sie steht hier",
        "trotzdem).",
        "",
        "## Modelle",
        "",
    ]
    zeilen += [f"* `{a}` — https://polyhaven.com/a/{a}" for a in liste["modelle"]]
    zeilen += ["", "## Texturen", ""]
    zeilen += [f"* `{n}` ← `{a}` — https://polyhaven.com/a/{a}"
               for n, a in liste["texturen"].items()]
    zeilen += ["", "## Himmel (HDRI)", ""]
    zeilen += [f"* {t}: `{a}` — https://polyhaven.com/a/{a}"
               for t, a in liste["himmel"].items()]
    (WURZEL / "assets" / "LIZENZEN.md").write_text("\n".join(zeilen) + "\n",
                                                   encoding="utf-8", newline="\n")


def main() -> int:
    with open(LISTE, encoding="utf-8") as fh:
        liste = json.load(fh)
    for asset in liste["modelle"]:
        modell_laden(asset)
    for name, asset in liste["texturen"].items():
        textur_laden(name, asset)
    for thema, asset in liste["himmel"].items():
        himmel_laden(thema, asset)
    for name, (asset, farbe, alpha) in liste.get("blaetter", {}).items():
        blatt_laden(name, asset, farbe, alpha)
    lizenzen_schreiben(liste)
    print("fertig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
