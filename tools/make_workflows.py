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
LINK_TYPEN = {"TRELLIS2PIPELINE", "IMAGE_COND", "IMAGE_CONDS", "VIEWS_LIST",
              "COORDS", "SHAPE_SLAT", "TEXTURE_SLAT", "TRIMESH", "IMAGE",
              "MASK", "MESH", "MESHWITHVOXEL", "BVH", "TRELLIS2VOXELMESH"}

VORLAGE_MV = (HIER / "ComfyUI" / "custom_nodes" / "ComfyUI-Trellis2"
              / "example_workflows" / "MeshWithTexturing_MultiView.json")

#: Knoten des Multi-View-Beispiels, die als Muster fuer weitere Ansichten
#: geklont werden: das Bild und seine Vorverarbeitung.
MV_MUSTER_BILD = 3
MV_MUSTER_VORBEREITUNG = 5
#: Der Knoten, der die Ansichten zusammenfuehrt.
MV_SAMMLER = 6
#: Eingangsplatz je Ansicht an :data:`MV_SAMMLER`.
MV_PLATZ = {"front": 1, "heck": 2, "links": 3, "rechts": 4}


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


def bauen(kaskade: int, schritte: int, quelle: str, name: str,
          beschreibung: str) -> Path:
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
    # Trellis2PreProcessImage greift in nodes.py:2675 ungeprueft auf den
    # vierten Kanal zu - die eingebaute Hintergrundentfernung ist dort
    # auskommentiert. Die Sprites bringen ihre Transparenz mit, ein Render
    # nicht. Fuer Renders muss rembg also laufen, sonst bricht der Lauf mit
    # IndexError ab, bevor irgendetwas gerechnet wurde.
    if quelle == "render":
        setzen(graph, "Trellis2PreProcessImage", "remove_background", True)
        setzen(graph, "Trellis2LoadImageWithTransparency", "image", "rookie_3d.png")
    else:
        setzen(graph, "Trellis2PreProcessImage", "remove_background", False)
        setzen(graph, "Trellis2LoadImageWithTransparency", "image", "Rookie.png")
    primitive_setzen(graph, 219, "rookie")

    # Der Beispiel-Workflow zeigt auf einen Pfad vom Rechner des Autors.
    for n in graph["nodes"]:
        if n["type"] == "Preview3D":
            n["widgets_values"] = ["", ""]

    return schreiben(graph, name)


def pruefen(graph: dict) -> list[str]:
    """Den fertigen Graphen gegenlesen, bevor er geschrieben wird.

    Noetig, weil fuer die Multi-View-Vorlagen Knoten und Verbindungen im
    Programm entstehen. Ein falsch gesetzter Verbindungs-Index faellt sonst
    erst auf, wenn die Datei in ComfyUI landet - und dort als stiller Fehler,
    weil ein nicht verbundener Eingang einfach leer bleibt.
    """
    fehler: list[str] = []
    ids = [n["id"] for n in graph["nodes"]]
    if len(ids) != len(set(ids)):
        fehler.append("doppelte Node-IDs")
    byid = {n["id"]: n for n in graph["nodes"]}
    links = {l[0]: l for l in graph["links"]}
    if len(links) != len(graph["links"]):
        fehler.append("doppelte Link-IDs")

    for lid, (_, src, sslot, dst, dslot, _typ) in links.items():
        if src not in byid or dst not in byid:
            fehler.append(f"Link {lid} zeigt auf einen fehlenden Knoten")
            continue
        if sslot >= len(byid[src].get("outputs") or []):
            fehler.append(f"Link {lid}: Ausgang {sslot} an #{src} gibt es nicht")
        if dslot >= len(byid[dst].get("inputs") or []):
            fehler.append(f"Link {lid}: Eingang {dslot} an #{dst} gibt es nicht")

    for n in graph["nodes"]:
        for i, eingang in enumerate(n.get("inputs") or []):
            lid = eingang.get("link")
            if lid is None:
                continue
            if lid not in links:
                fehler.append(f"#{n['id']}.{eingang['name']}: Link {lid} fehlt")
            elif links[lid][3] != n["id"] or links[lid][4] != i:
                fehler.append(f"#{n['id']}.{eingang['name']}: Link {lid} zeigt woanders hin")
        for i, ausgang in enumerate(n.get("outputs") or []):
            for lid in (ausgang.get("links") or []):
                if lid not in links:
                    fehler.append(f"#{n['id']} Ausgang {ausgang['name']}: Link {lid} fehlt")
                elif links[lid][1] != n["id"] or links[lid][2] != i:
                    fehler.append(f"#{n['id']} Ausgang {ausgang['name']}: Link {lid} passt nicht")

    if ids and max(ids) > graph.get("last_node_id", 0):
        fehler.append("last_node_id ist zu klein")
    if links and max(links) > graph.get("last_link_id", 0):
        fehler.append("last_link_id ist zu klein")
    return fehler


def schreiben(graph: dict, name: str) -> Path:
    """Pruefen und schreiben. Ein kaputter Graph wird nicht abgelegt."""
    fehler = pruefen(graph)
    if fehler:
        raise ValueError(f"{name} ist fehlerhaft: " + "; ".join(fehler[:5]))
    ZIEL_DIR.mkdir(parents=True, exist_ok=True)
    ziel = ZIEL_DIR / name
    ziel.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  geschrieben: {ziel}")
    return ziel


def _knoten(graph: dict, node_id: int) -> dict:
    for n in graph["nodes"]:
        if n["id"] == node_id:
            return n
    raise KeyError(f"Node #{node_id} nicht gefunden")


def ansicht_ergaenzen(graph: dict, ansicht: str, dateiname: str,
                      versatz: float) -> None:
    """Eine weitere Ansicht in den Multi-View-Graphen einsetzen.

    Geklont werden Bildknoten und Vorverarbeitung des Musters, damit Groesse,
    Eigenschaften und Version genau denen entsprechen, die der Node erwartet -
    von Hand zusammengesetzte Knoten sind eine Fehlerquelle, die niemand
    braucht.
    """
    from copy import deepcopy

    bild = deepcopy(_knoten(graph, MV_MUSTER_BILD))
    vorb = deepcopy(_knoten(graph, MV_MUSTER_VORBEREITUNG))

    neue_id = int(graph["last_node_id"])
    bild["id"] = neue_id + 1
    vorb["id"] = neue_id + 2
    graph["last_node_id"] = neue_id + 2

    neue_verbindung = int(graph["last_link_id"])
    bild_zu_vorb = neue_verbindung + 1
    vorb_zu_sammler = neue_verbindung + 2
    graph["last_link_id"] = neue_verbindung + 2

    bild["pos"] = [bild["pos"][0], bild["pos"][1] + versatz]
    vorb["pos"] = [vorb["pos"][0], vorb["pos"][1] + versatz]
    bild["title"] = f"Bild {ansicht}"
    bild["widgets_values"] = [dateiname, "image"]

    # Ausgang 2 des Bildknotens ist image_with_alpha - der Weg, auf dem die
    # Transparenz erhalten bleibt.
    for i, ausgang in enumerate(bild["outputs"]):
        ausgang["links"] = [bild_zu_vorb] if i == 2 else None
    vorb["inputs"][0]["link"] = bild_zu_vorb
    vorb["outputs"][0]["links"] = [vorb_zu_sammler]

    sammler = _knoten(graph, MV_SAMMLER)
    sammler["inputs"][MV_PLATZ[ansicht]]["link"] = vorb_zu_sammler

    graph["nodes"] += [bild, vorb]
    graph["links"] += [
        [bild_zu_vorb, bild["id"], 2, vorb["id"], 0, "IMAGE"],
        [vorb_zu_sammler, vorb["id"], 0, MV_SAMMLER, MV_PLATZ[ansicht], "IMAGE"],
    ]
    print(f"  ergaenzt: Ansicht {ansicht} -> {dateiname}")


def bauen_multiview(ansichten: tuple[str, ...], name: str,
                    beschreibung: str) -> Path:
    """Multi-View-Vorlage aus dem Beispiel des Nodes.

    Mehrere Ansichten sind der wirksamste Hebel ueberhaupt: was TRELLIS sieht,
    muss es nicht erfinden. Mit einer Frontansicht allein wird das Heck aus der
    Silhouette erschlossen - Rueckleuchten, Stossfaenger und Heckklappe sind
    dann geraten.
    """
    graph = json.loads(VORLAGE_MV.read_text(encoding="utf-8"))
    print(f"\n=== {name}  ({beschreibung})")

    setzen(graph, "Trellis2LoadModel", "backend", "sdpa")
    setzen(graph, "Trellis2LoadModel", "conv_backend", "flex_gemm")
    setzen(graph, "Trellis2LoadModel", "low_vram", True)

    # Renders bringen keine Transparenz mit, siehe nodes.py:2675.
    setzen(graph, "Trellis2PreProcessImage", "remove_background", True)

    setzen(graph, "Trellis2SparseMultiViewGenerator",
           "sparse_structure_resolution", 64)
    setzen(graph, "Trellis2ShapeMultiViewGenerator", "resolution", 1024)
    setzen(graph, "Trellis2ShapeCascadeMultiViewGenerator", "from_resolution", 512)
    setzen(graph, "Trellis2ShapeCascadeMultiViewGenerator", "to_resolution", 1536)

    setzen(graph, "Trellis2SparseMultiViewGenerator", "sparse_structure_steps", 25)
    setzen(graph, "Trellis2ShapeMultiViewGenerator", "shape_steps", 25)
    setzen(graph, "Trellis2ShapeCascadeMultiViewGenerator", "shape_steps", 25)
    setzen(graph, "Trellis2TexSlatMultiViewGenerator", "texture_steps", 25)

    primitive_setzen(graph, 23, 1000000)      # Simplify-Ziel
    primitive_setzen(graph, 26, 2048)         # texture_size
    primitive_setzen(graph, 22, "rookie")     # Dateiname der Ausgabe

    setzen(graph, "Trellis2LoadImageWithTransparency", "image",
           "rookie_3d_front.png", node_id=2)
    setzen(graph, "Trellis2LoadImageWithTransparency", "image",
           "rookie_3d_heck.png", node_id=MV_MUSTER_BILD)

    for nummer, ansicht in enumerate(a for a in ansichten
                                     if a not in ("front", "heck")):
        ansicht_ergaenzen(graph, ansicht, f"rookie_3d_{ansicht}.png",
                          versatz=600.0 * (nummer + 1))

    for n in graph["nodes"]:
        if n["type"] == "Preview3D":
            n["widgets_values"] = ["", ""]

    return schreiben(graph, name)


def main() -> int:
    if not VORLAGE.is_file():
        print(f"FEHLER: {VORLAGE} nicht gefunden", file=sys.stderr)
        return 2
    try:
        # Zwei Achsen: woher das Bild kommt und wieviel Zeit es kosten darf.
        # Alle vier heben sparse_structure_resolution auf 64 - das ist die
        # Einstellung, die ueber runde Reifen entscheidet, und sie ist in
        # keiner Variante verhandelbar.
        bauen(1024, 15, "sprite", "Fahrzeug_TopDown_Serie.json",
              "Top-Down-Sprite, Durchlauf ueber alle 15 Fahrzeuge")
        bauen(1536, 25, "sprite", "Fahrzeug_TopDown_HQ.json",
              "Top-Down-Sprite, Einzelstueck")
        bauen(1024, 15, "render", "Fahrzeug_Render_Serie.json",
              "3D-Render, Durchlauf ueber alle 15 Fahrzeuge")
        bauen(1536, 25, "render", "Fahrzeug_Render_HQ.json",
              "3D-Render, Einzelstueck, auf 16 GB knapp")
        bauen_multiview(("front", "heck"), "Fahrzeug_MultiView_2.json",
                        "Front und Heck")
        bauen_multiview(("front", "heck", "links", "rechts"),
                        "Fahrzeug_MultiView_4.json",
                        "Front, Heck und beide Flanken")
    except (KeyError, OSError, urllib.error.URLError) as fehler:
        print(f"FEHLER: {fehler}", file=sys.stderr)
        print("Laeuft ComfyUI? tools\\start_gui.bat", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
