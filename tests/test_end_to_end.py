"""Der ganze Weg an einem echten GLB: laden, ausrichten, skalieren, schreiben.

Das Modell hier ist ein texturierter Quader, kein Auto - aber es geht durch
dieselben Schritte wie eine TRELLIS-Generierung, inklusive GLB-Datei auf der
Platte und PBR-Material.
"""
import json

import numpy as np
import pytest
import trimesh
from PIL import Image

import trellis_import
from trellis_pipeline import glb_io, orient


def _textur():
    """Ueberwiegend Karosserierot, ein dunkler Streifen als Scheibe."""
    bild = np.zeros((64, 64, 4), dtype=np.uint8)
    bild[:, :] = (203, 60, 59, 255)
    bild[24:40, :] = (48, 52, 58, 255)
    return Image.fromarray(bild, mode="RGBA")


def _texturiertes_auto(extents=(2.0, 0.96, 0.65), keil=False):
    """Quader mit PBR-Material.

    ``keil`` verjuengt das Modell zu +X hin. Ein symmetrischer Quader waere fuer
    den Flip-Test wertlos: um die Hochachse gedreht sieht er genauso aus.
    """
    mesh = trimesh.creation.box(extents=extents)
    if keil:
        vorne = mesh.vertices[:, 0] > 0
        mesh.vertices[vorne, 1] *= 0.35
    uv = np.random.default_rng(7).random((len(mesh.vertices), 2))
    mesh.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=_textur(), metallicFactor=0.4, roughnessFactor=0.5))
    return mesh


def _schief_exportiert(tmp_path, name="rookie.glb", extents=(2.0, 0.96, 0.65),
                       keil=False):
    """Wie es aus TRELLIS kommt: beliebig gedreht, beliebig verschoben."""
    mesh = _texturiertes_auto(extents, keil=keil)
    mesh.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(35), (0.3, 1.0, 0.5)))
    mesh.apply_translation((4.0, -2.0, 6.0))
    pfad = tmp_path / name
    pfad.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(mesh)))
    return pfad


@pytest.fixture
def vehicles_dir(tmp_path):
    ordner = tmp_path / "vehicles"
    ordner.mkdir()
    (ordner / "rookie.json").write_text(json.dumps({"paint": {
        "verfahren": "dominant", "referenzfarbe": [203, 60, 59],
        "farbtoleranz": 0.3, "helligkeit_min": 0.06, "helligkeit_max": 0.51,
        "kantenweichheit": 0.0, "deckkraft": 1.0}}), encoding="utf-8")
    return ordner


def test_ganzer_durchlauf_liefert_masshaltiges_glb(tmp_path, vehicles_dir):
    quelle = _schief_exportiert(tmp_path)
    aus = tmp_path / "assets"

    code = trellis_import.main([
        str(quelle), "--fahrzeug", "rookie",
        "--config", str(tmp_path / "fehlt.json"),
        "--vehicles-dir", str(vehicles_dir), "--out", str(aus)])

    assert code == 0, "Massabweichung im Testmodell"
    ergebnis, _ = glb_io.laden(aus / "rookie.glb")
    ext = ergebnis.bounding_box.extents
    assert ext[0] == pytest.approx(4.32, rel=1e-3)
    assert ergebnis.bounds[0][2] == pytest.approx(0.0, abs=1e-6), "steht nicht auf z=0"
    assert ergebnis.bounding_box.centroid[0] == pytest.approx(0.0, abs=1e-6)


def test_textur_ueberlebt_den_durchlauf(tmp_path, vehicles_dir):
    quelle = _schief_exportiert(tmp_path)
    aus = tmp_path / "assets"
    trellis_import.main([str(quelle), "--fahrzeug", "rookie",
                         "--config", str(tmp_path / "fehlt.json"),
                         "--vehicles-dir", str(vehicles_dir), "--out", str(aus)])
    ergebnis, _ = glb_io.laden(aus / "rookie.glb")
    assert glb_io.basis_textur(ergebnis) is not None


def test_lackmaske_wird_neben_das_glb_gelegt(tmp_path, vehicles_dir):
    quelle = _schief_exportiert(tmp_path)
    aus = tmp_path / "assets"
    trellis_import.main([str(quelle), "--fahrzeug", "rookie",
                         "--config", str(tmp_path / "fehlt.json"),
                         "--vehicles-dir", str(vehicles_dir), "--out", str(aus)])
    maske = aus / "rookie_lackmaske.png"
    assert maske.is_file()
    daten = np.asarray(Image.open(maske))
    assert daten.max() == 255, "kein einziges Lack-Texel gefunden"
    assert daten.min() == 0, "die dunkle Scheibe haette ausgenommen sein muessen"


def test_flip_aus_der_config_wird_angewandt(tmp_path, vehicles_dir):
    config = tmp_path / "trellis_import.json"
    config.write_text('{"rookie": {"flip": true}}', encoding="utf-8")
    aus_normal, aus_flip = tmp_path / "a", tmp_path / "b"

    trellis_import.main([str(_schief_exportiert(tmp_path, "n.glb", keil=True)),
                         "--fahrzeug", "rookie", "--config", str(tmp_path / "fehlt.json"),
                         "--vehicles-dir", str(vehicles_dir), "--out", str(aus_normal)])
    trellis_import.main([str(_schief_exportiert(tmp_path, "f.glb", keil=True)),
                         "--fahrzeug", "rookie", "--config", str(config),
                         "--vehicles-dir", str(vehicles_dir), "--out", str(aus_flip)])

    a, _ = glb_io.laden(aus_normal / "rookie.glb")
    b, _ = glb_io.laden(aus_flip / "rookie.glb")
    assert a.bounding_box.extents == pytest.approx(b.bounding_box.extents, rel=1e-6)
    # Das spitze Ende muss auf der anderen Seite liegen, oben aber oben bleiben.
    assert orient.schwerpunkt(a)[0] == pytest.approx(-orient.schwerpunkt(b)[0], abs=1e-6)
    assert orient.schwerpunkt(a)[0] != pytest.approx(0.0, abs=1e-3)
    assert orient.schwerpunkt(a)[2] == pytest.approx(orient.schwerpunkt(b)[2], abs=1e-6)


def test_rad_bekommt_nabenmitte_als_ursprung(tmp_path, vehicles_dir):
    rad = trimesh.creation.cylinder(radius=1.0, height=0.6, sections=48)
    rad.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(25), (1, 1, 0)))
    quelle = tmp_path / "rad.glb"
    quelle.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(rad)))
    aus = tmp_path / "assets"

    code = trellis_import.main([str(quelle), "--fahrzeug", "rookie", "--typ", "rad",
                                "--config", str(tmp_path / "fehlt.json"),
                                "--vehicles-dir", str(vehicles_dir), "--out", str(aus)])

    assert code == 0
    ergebnis, _ = glb_io.laden(aus / "rookie_rad.glb")
    ext = ergebnis.bounding_box.extents
    assert ext[0] == pytest.approx(0.65, rel=0.02)
    assert ext[2] == pytest.approx(0.65, rel=0.02)
    assert ergebnis.bounding_box.centroid == pytest.approx([0, 0, 0], abs=1e-6)
    assert not (aus / "rookie_lackmaske.png").exists(), "ein Rad hat keinen Lack"


def test_unbekanntes_fahrzeug_bricht_sauber_ab(tmp_path, vehicles_dir, capsys):
    quelle = _schief_exportiert(tmp_path)
    code = trellis_import.main([str(quelle), "--fahrzeug", "ferrari",
                                "--config", str(tmp_path / "fehlt.json"),
                                "--vehicles-dir", str(vehicles_dir),
                                "--out", str(tmp_path / "assets")])
    assert code == 2
    assert "rookie" in capsys.readouterr().err
