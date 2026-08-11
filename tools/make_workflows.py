"""Erzeugt die Fahrzeug-Workflows aus dem Beispiel des Nodes.

Warum ein Skript und keine von Hand zusammengeklickte Datei: die Widget-Werte
eines ComfyUI-Workflows sind eine **Liste ohne Feldnamen**. Welcher Wert welche
Einstellung ist, ergibt sich erst aus der Reihenfolge in ``INPUT_TYPES`` des
Nodes. Ein Update des Nodes, das eine Einstellung einschiebt, verschiebt alles
dahinter - eine von Hand gepflegte Datei wuerde dann still falsche Werte
setzen. Dieses Skript fragt die Reihenfolge beim laufenden Server ab und
schlaegt fehl, wenn etwas nicht mehr passt.

    python tools\\make_workflows.py

Setzt voraus, dass ComfyUI laeuft (tools\\start_gui.bat).
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HIER = Path(__file__).resolve().parent
VORLAGE = (HIER / "ComfyUI" / "custom_nodes" / "ComfyUI-Trellis2"
           / "example_workflows" / "MeshWithTexturing.json")
ZIEL_DIR = HIER.parent / "workflows"
SERVER = "http://127.0.0.1:8188"

#: Werte, die ComfyUI hinter einem INT namens "seed" als zusaetzliches Widget
#: einschiebt. Sie stehen in keiner INPUT_TYPES-Liste und muessen beim Zaehlen
#: der Widget-Plaetze mitgerechnet werden.
SEED_STEUERUNG = ("fixed", "increment", "decrement", "randomize")

#: Eingaenge dieser Typen sind immer Verbindungen, nie Widgets.
LINK_TYPEN = {"TRELLIS2PIPELINE", "IMAGE_COND", "COORDS", "SHAPE_SLAT",
              "TRIMESH", "IMAGE", "MASK", "MESH", "TRELLIS2VOXELMESH"}


def object_info(klasse: str) -> dict:
    with urllib.request.urlopen(f"{SERVER}/object_info/{klasse}", timeout=60) as a:
        return json.load(a)[klasse]


def widget_index(klasse: str, feld: str) -> int:
    """Platz eines Feldes in ``widgets_values``.

    Zaehlt die Verbindungseingaenge heraus und den Steuerungs-Platz hinter
    einem Seed hinzu. Ein zu einem Eingang umgewandeltes Widget behaelt seinen
    Platz in der Liste - deshalb wird hier nach Typ gezaehlt und nicht danach,
    was gerade verkabelt ist.
    """
    info = object_info(klasse)["input"]
    felder = list(info.get("required", {}).items()) + list(info.get("optional", {}).items())
    platz = 0
    for name, spez in felder:
        typ = spez[0]
        if isinstance(typ, str) and typ in LINK_TYPEN:
            continue
        if name == feld:
            return platz
        platz += 2 if name == "seed" else 1
    raise KeyError(f"{klasse} hat kein Feld {feld!r} - Node geaendert?")


def setzen(graph: dict, klasse: str, feld: str, wert, node_id: int | None = None) -> None:
    """Ein Widget setzen und melden, was sich geaendert hat."""
    idx = widget_index(klasse, feld)
    treffer = [n for n in graph["nodes"] if n["type"] == klasse
               and (node_id is None or n["id"] == node_id)]
    if not treffer:
        raise KeyError(f"Kein Node {klasse} im Workflow")
    for n in treffer:
        werte = n.setdefault("widgets_values", [])
        while len(werte) <= idx:
            werte.append(None)
        alt = werte[idx]
        werte[idx] = wert
        if alt != wert:
            print(f"  #{n['id']:>3} {klasse}.{feld}: {alt!r} -> {wert!r}")


def primitive_setzen(graph: dict, node_id: int, wert) -> None:
    for n in graph["nodes"]:
        if n["id"] == node_id:
            alt = n["widgets_values"][0]
            n["widgets_values"][0] = wert
            if alt != wert:
                print(f"  #{node_id:>3} {n['type']}: {alt!r} -> {wert!r}")
            return
    raise KeyError(f"Node #{node_id} nicht gefunden")


def bauen(kaskade: int, schritte: int, name: str, beschreibung: str) -> Path:
    graph = json.loads(VORLAGE.read_text(encoding="utf-8"))
    print(f"\n=== {name}  ({beschreibung})")

    # --- Was hier installiert ist -------------------------------------------
    # flash_attn ist nicht installiert und waere unter Windows fuer Torch 2.7
    # ein Kompilat. sdpa ist reines PyTorch und laeuft immer.
    setzen(graph, "Trellis2LoadModel", "backend", "sdpa")
    # conv_backend bleibt flex_gemm: im Testlauf am 11.08.2026 kam damit auf der
    # 5060 Ti ein geschlossenes Mesh, keine Punktwolke. spconv wird nicht
    # gebraucht - und es gibt dafuer kein sm_120-Wheel.
    setzen(graph, "Trellis2LoadModel", "conv_backend", "flex_gemm")
    setzen(graph, "Trellis2LoadModel", "low_vram", True)

    # --- Aufloesung ---------------------------------------------------------
    # sparse_structure_resolution ist das grobe Voxelgitter ueber die laengste
    # Kante. Bei 32 und 4,32 m Fahrzeuglaenge sind das 13,5 cm je Voxel - ein
    # Reifen von 0,65 m ist damit 5 Voxel breit und kann nicht rund werden.
    # 64 halbiert die Kantenlaenge auf 6,8 cm.
    setzen(graph, "Trellis2SparseGenerator", "sparse_structure_resolution", 64)
    setzen(graph, "Trellis2ShapeGenerator", "resolution", 1024)
    setzen(graph, "Trellis2ShapeCascadeGenerator", "from_resolution", 512)
    setzen(graph, "Trellis2ShapeCascadeGenerator", "to_resolution", kaskade)

    # --- Schritte -----------------------------------------------------------
    # Gemessen am Lauf vom 11.08.2026 (Standardwerte, 19:18 gesamt): die
    # Abtastung macht rund 7 Minuten aus, der Rest sind Rekonstruktion, Loecher
    # und xatlas. Die Schrittzahl schlaegt also linear auf diese 7 Minuten
    # durch - die Voxelaufloesung dagegen auf alles.
    setzen(graph, "Trellis2SparseGenerator", "sparse_structure_steps", schritte)
    setzen(graph, "Trellis2ShapeGenerator", "shape_steps", schritte)
    setzen(graph, "Trellis2ShapeCascadeGenerator", "shape_steps", schritte)
    setzen(graph, "Trellis2MeshTexturing", "texture_steps", schritte)

    # --- Textur -------------------------------------------------------------
    # Die Flanken des Fahrzeugs sind im Top-Down-Bild nicht zu sehen und werden
    # gefuellt. Mehr Ansichten und hoehere Aufloesung machen das weniger grob -
    # erfinden aber weiterhin, was im Bild nicht drin ist.
    setzen(graph, "Trellis2MeshTexturing", "resolution", 1536)
    setzen(graph, "Trellis2MeshTexturing", "max_views", 6)

    # --- Dreiecksbudget -----------------------------------------------------
    primitive_setzen(graph, 209, 1000000)     # Simplify-Ziel
    primitive_setzen(graph, 260, 2048)        # texture_size

    # --- Eingabe und Benennung ---------------------------------------------
    setzen(graph, "Trellis2LoadImageWithTransparency", "image", "Rookie.png")
    primitive_setzen(graph, 219, "rookie")

    # Der Beispiel-Workflow zeigt auf einen Pfad vom Rechner des Autors.
    for n in graph["nodes"]:
        if n["type"] == "Preview3D":
            n["widgets_values"] = ["", ""]

    ZIEL_DIR.mkdir(parents=True, exist_ok=True)
    ziel = ZIEL_DIR / name
    ziel.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  geschrieben: {ziel}")
    return ziel


def main() -> int:
    if not VORLAGE.is_file():
        print(f"FEHLER: {VORLAGE} nicht gefunden", file=sys.stderr)
        return 2
    try:
        # Der Unterschied zwischen den beiden ist vor allem Laufzeit. Beide
        # heben sparse_structure_resolution auf 64 - das ist die Einstellung,
        # die ueber runde Reifen entscheidet, und sie ist in keiner Variante
        # verhandelbar.
        bauen(1024, 15, "Fahrzeug_TopDown_Serie.json",
              "fuer den Durchlauf ueber alle 15 Fahrzeuge")
        bauen(1536, 25, "Fahrzeug_TopDown_HQ.json",
              "Einzelstueck, deutlich laenger und auf 16 GB knapp")
    except (KeyError, OSError, urllib.error.URLError) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        print("Laeuft ComfyUI? tools\\start_gui.bat", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
