"""Der Zeichenweg, einmal wirklich durch OpenGL.

Die übrigen Tests prüfen Rechnungen. Dieser hier prüft, dass am Ende ein Bild
dasteht: Shader übersetzen, Puffer passen zu den Attributnamen, Fahrzeugknoten,
Schattenfleck und Ghost-Entfärbung zeichnen ohne Fehler.

Er läuft in einem **eigenständigen** Kontext ohne Fenster und braucht deshalb
kein Spiel. Wo keine brauchbare OpenGL-Umsetzung vorliegt, wird er
übersprungen statt rot — die Testumgebung des Projekts hat kein Fenster, und
ob eine Maschine OpenGL kann, ist keine Aussage über den Code.

Bewusst mit einem **winzigen Ersatzmodell** statt mit ``rookie.glb``: das echte
Modell hat 787 000 Dreiecke, und die schnelle Testrunde soll in Sekunden
durchlaufen. Geprüft wird der Weg, nicht das Auto.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

moderngl = pytest.importorskip("moderngl")
trimesh = pytest.importorskip("trimesh")

from src.render3d import camera, rennszene, track_mesh  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    try:
        kontext = moderngl.create_standalone_context()
    except Exception as fehler:                      # pragma: no cover - Treiber
        pytest.skip(f"Kein OpenGL-Kontext: {fehler}")
    yield kontext
    kontext.release()


@pytest.fixture(scope="module")
def modellordner(tmp_path_factory):
    """Ein Ersatzfahrzeug aus fünf Kisten: Karosserie und vier Räder."""
    ordner = tmp_path_factory.mktemp("vehicles")
    szene = trimesh.Scene()
    karosserie = trimesh.creation.box((4.0, 1.8, 1.2))
    from trimesh.visual.material import PBRMaterial
    karosserie.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(karosserie.vertices), 2)),
        material=PBRMaterial(name="lack", baseColorFactor=[200, 30, 30, 255],
                             metallicFactor=0.0, roughnessFactor=0.4))
    szene.add_geometry(karosserie, node_name="karosserie", geom_name="karosserie")
    naben = {"rad_vl": (1.3, 0.8), "rad_vr": (1.3, -0.8),
             "rad_hl": (-1.3, 0.8), "rad_hr": (-1.3, -0.8)}
    for name, (x, y) in naben.items():
        szene.add_geometry(
            trimesh.creation.box((0.65, 0.2, 0.65)), node_name=name, geom_name=name,
            transform=trimesh.transformations.translation_matrix((x, y, 0.325)))
    szene.export(str(ordner / "rookie.glb"))
    (ordner / "rookie_teile.json").write_text(json.dumps({
        "fahrzeug": "rookie", "laenge_m": 4.0, "breite_m": 1.8,
        "raddurchmesser_m": 0.65,
        "gelenkt": ["rad_vl", "rad_vr"],
        "raeder": [{"name": n, "nabe": [x, y, 0.325]} for n, (x, y) in naben.items()],
    }), encoding="utf-8")
    return ordner


@pytest.fixture(scope="module")
def netz():
    """Ein kurzes gerades Stück Strecke — mehr braucht der Zeichenweg nicht."""
    mittellinie = [{"x": x * 12.5, "y": 0.0} for x in range(0, 40)]
    return track_mesh.bauen({
        "centerline": mittellinie,
        "track_width": 250.0,
        "start_positions": [{"x": 0.0, "y": 0.0, "angle": 0.0}],
    })


def _stand(kennung=1, x=0.0, entfaerbt=False, weg_m=0.0):
    return rennszene.Fahrzeugstand(
        kennung=kennung, schluessel="rookie",
        pos_m=np.array([x, 0.0, 0.0]), gierwinkel_rad=0.0,
        weg_m=weg_m, lenkwinkel_rad=0.0, entfaerbt=entfaerbt)


def _bild(ctx, szene, staende, groesse=(160, 120)):
    """Einmal zeichnen und die Bildpunkte zurückgeben, (h, b, 3)."""
    puffer = ctx.simple_framebuffer(groesse, components=3)
    puffer.use()
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.clear(0.2, 0.4, 0.8)
    kamera = camera.Verfolgerkamera(abstand_m=9.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(staende[0].pos_m, staende[0].gierwinkel_rad)
    mvp = camera.perspektive(55.0, groesse[0] / groesse[1], 0.2, 400.0) \
        @ kamera.blickmatrix()
    szene.zeichnen(mvp, kamera.auge, staende)
    roh = np.frombuffer(puffer.read(components=3), dtype=np.uint8)
    puffer.release()
    # framebuffer.read() liefert Zeilen von unten nach oben.
    return roh.reshape(groesse[1], groesse[0], 3)[::-1]


def test_szene_zeichnet_ueberhaupt_etwas(ctx, netz, modellordner):
    """Strecke, Fahrzeug und Schattenfleck landen im Bildpuffer."""
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    staende = [_stand()]
    szene.fortschreiben(staende)
    bild = _bild(ctx, szene, staende)
    assert bild.std() > 5.0, "Bild ist einfarbig - es wurde nichts gezeichnet"
    szene.freigeben()


def test_acht_fahrzeuge_teilen_ein_modell(ctx, netz, modellordner):
    """Acht Wagen duerfen das GLB nicht achtmal hochladen.

    Sonst waeren es acht mal 787 000 Dreiecke im Grafikspeicher - dieselbe
    Karosserie, achtmal bezahlt.
    """
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    staende = [_stand(kennung=i, x=-4.5 * i) for i in range(8)]
    szene.fortschreiben(staende)
    _bild(ctx, szene, staende)
    modelle = {id(szene.speicher.holen(s.schluessel)) for s in staende}
    assert len(modelle) == 1
    szene.freigeben()


def test_fehlendes_modell_faehrt_mit_dem_ersatz(ctx, netz, modellordner):
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    stand = _stand()
    stand.schluessel = "limousine"
    szene.fortschreiben([stand])
    bild = _bild(ctx, szene, [stand])
    assert bild.std() > 5.0
    assert szene.speicher.holen("limousine").schluessel == "rookie"
    szene.freigeben()


def test_ghost_wird_entfaerbt_gezeichnet(ctx, netz, modellordner):
    """Der Ghost ist grauer als dasselbe Fahrzeug in Farbe.

    Gemessen an der Buntheit — dem Abstand zwischen groesstem und kleinstem
    Farbkanal — und nur dort, wo sich die beiden Bilder unterscheiden. Ueber
    das ganze Bild gemittelt ginge der Unterschied in Himmel und Fahrbahn
    unter.
    """
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    bunt = _bild(ctx, szene, [_stand()])
    grau = _bild(ctx, szene, [_stand(entfaerbt=True)])

    anders = np.any(bunt != grau, axis=2)
    assert anders.sum() > 20, "Der Ghost sieht aus wie das normale Fahrzeug"
    buntheit = lambda b: (b[anders].max(axis=1).astype(int)
                          - b[anders].min(axis=1).astype(int)).mean()
    assert buntheit(grau) < buntheit(bunt)
    szene.freigeben()


def test_raeder_drehen_sich_mit_dem_weg(ctx, netz, modellordner):
    """Nach zurueckgelegtem Weg steht das Rad woanders.

    Geprueft an der Matrix und nicht am Bild: ein Rad, das sich um seine
    Querachse dreht, sieht von hinten fast gleich aus.
    """
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    stand = _stand(weg_m=0.5)
    szene.fortschreiben([stand])
    knoten = szene.knotenspeicher.knoten(1)
    vorher = knoten.matrizen(stand.pos_m, 0.0)["rad_vl"].copy()
    szene.fortschreiben([stand])
    nachher = knoten.matrizen(stand.pos_m, 0.0)["rad_vl"]
    assert not np.allclose(vorher, nachher)
    szene.freigeben()


def test_zeichnen_dreht_die_raeder_nicht_weiter(ctx, netz, modellordner):
    """Im Splitscreen wird zweimal gezeichnet und vergeht einmal Zeit.

    Wuerde ``zeichnen`` den Radzustand fortschreiben, drehten sich die Raeder
    auf der geteilten Anzeige doppelt so schnell.
    """
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    stand = _stand(weg_m=0.5)
    szene.fortschreiben([stand])
    knoten = szene.knotenspeicher.knoten(1)
    vorher = knoten.rollwinkel_rad
    _bild(ctx, szene, [stand])
    _bild(ctx, szene, [stand])
    assert knoten.rollwinkel_rad == pytest.approx(vorher)
    szene.freigeben()
