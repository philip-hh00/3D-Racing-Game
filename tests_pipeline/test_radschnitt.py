"""Raeder aus dem verschmolzenen TRELLIS-Mesh heraustrennen."""
import numpy as np
import pytest
import trimesh

from trellis_pipeline import radschnitt, vehicle_specs


def _auto_mit_raedern(key="rookie", radbreite=0.20):
    """Ein grober Fahrzeugklotz mit vier Radzylindern an den Sollpositionen.

    Bewusst ein einziges verschmolzenes Netz, so wie TRELLIS es liefert: Reifen
    und Karosserie haengen zusammen, es gibt keine Trennkante zum Nachschlagen.
    """
    s = vehicle_specs.spec(key)
    koerper = trimesh.creation.box(extents=(s.laenge_m, s.breite_m * 0.9, 1.2))
    # Nach oben verjuengt, sonst ist es kein Auto sondern eine Kiste - und die
    # Ausrichtung kann Oben und Unten nicht auseinanderhalten.
    koerper.vertices[koerper.vertices[:, 2] > 0, 1] *= 0.75
    koerper.apply_translation((0, 0, 0.45 + s.rad_m / 2))
    teile = [koerper]
    for x, y, z in vehicle_specs.radpositionen(key):
        rad = trimesh.creation.cylinder(radius=s.rad_m / 2, height=radbreite, sections=64)
        # Zylinder steht auf Z, die Drehachse eines Rades liegt auf Y.
        rad.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
        rad.apply_translation((x, y, z))
        teile.append(rad)
    return trimesh.util.concatenate(teile)


def test_liefert_karosserie_und_vier_raeder():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    assert len(zerlegt.raeder) == 4
    assert zerlegt.karosserie is not None


def test_raeder_sitzen_an_den_sollpositionen():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    soll = sorted(vehicle_specs.radpositionen("rookie"))
    ist = sorted(tuple(round(float(v), 2) for v in r.nabe) for r in zerlegt.raeder)
    for (sx, sy, sz), (ix, iy, iz) in zip(soll, ist):
        assert ix == pytest.approx(sx, abs=0.05)
        assert iy == pytest.approx(sy, abs=0.05)
        assert iz == pytest.approx(sz, abs=0.05)


def test_rad_hat_den_richtigen_durchmesser():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    for rad in zerlegt.raeder:
        ext = rad.mesh.bounding_box.extents
        assert ext[0] == pytest.approx(0.65, rel=0.08), "Durchmesser in Fahrtrichtung"
        assert ext[2] == pytest.approx(0.65, rel=0.08), "Durchmesser in der Hochachse"


def test_radursprung_liegt_in_der_nabe():
    """Sonst beschreibt das Rad beim Drehen einen Kreis, statt sich zu drehen."""
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    for rad in zerlegt.raeder:
        assert rad.mesh.bounding_box.centroid == pytest.approx([0, 0, 0], abs=0.03)


def test_karosserie_behaelt_die_laenge():
    """Der Schnitt darf die Fahrzeugmasse nicht verkleinern."""
    auto = _auto_mit_raedern()
    zerlegt = radschnitt.schneiden(auto, vehicle_specs.spec("rookie"))
    assert zerlegt.karosserie.bounding_box.extents[0] == pytest.approx(
        auto.bounding_box.extents[0], rel=0.02)


def test_keine_dreiecke_gehen_verloren():
    auto = _auto_mit_raedern()
    zerlegt = radschnitt.schneiden(auto, vehicle_specs.spec("rookie"))
    summe = len(zerlegt.karosserie.faces) + sum(len(r.mesh.faces) for r in zerlegt.raeder)
    # Beim Schliessen der Schnittflaeche duerfen Dreiecke dazukommen, keine fehlen.
    assert summe >= len(auto.faces)


def test_raeder_sind_wirklich_aus_der_karosserie_heraus():
    auto = _auto_mit_raedern()
    zerlegt = radschnitt.schneiden(auto, vehicle_specs.spec("rookie"))
    assert len(zerlegt.karosserie.faces) < len(auto.faces)
    for x, y, z in vehicle_specs.radpositionen("rookie"):
        mitten = zerlegt.karosserie.triangles_center
        abstand = np.linalg.norm(mitten - np.array([x, y, z]), axis=1)
        assert abstand.min() > 0.1, "Reste des Rades stecken noch in der Karosserie"


def test_uv_koordinaten_ueberleben_den_schnitt():
    auto = _auto_mit_raedern()
    auto.visual = trimesh.visual.TextureVisuals(
        uv=np.random.default_rng(3).random((len(auto.vertices), 2)),
        material=trimesh.visual.material.PBRMaterial())
    zerlegt = radschnitt.schneiden(auto, vehicle_specs.spec("rookie"))
    assert zerlegt.karosserie.visual.uv is not None
    for rad in zerlegt.raeder:
        assert rad.mesh.visual.uv is not None
        assert len(rad.mesh.visual.uv) == len(rad.mesh.vertices)


def test_szene_hat_benannte_knoten():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    szene = zerlegt.als_szene()
    knoten = set(szene.graph.nodes)
    for name in ("karosserie", "rad_vl", "rad_vr", "rad_hl", "rad_hr"):
        assert name in knoten


def test_szene_setzt_die_raeder_an_ihren_platz():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    szene = zerlegt.als_szene()
    verschiebung = szene.graph.get("rad_vl")[0][:3, 3]
    assert verschiebung == pytest.approx(vehicle_specs.radpositionen("rookie")[0], abs=0.05)


def test_ganzer_durchlauf_schreibt_szene_und_teileliste(tmp_path):
    """Vom GLB bis zu den Dateien, die der Renderer laedt."""
    import json

    import trellis_import
    from trellis_pipeline import glb_io

    auto = _auto_mit_raedern()
    auto.apply_scale(1 / auto.bounding_box.extents[0] * 2.0)   # so wie TRELLIS es liefert
    quelle = tmp_path / "rookie.glb"
    quelle.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(auto)))
    aus = tmp_path / "assets"
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    (vehicles / "rookie.json").write_text("{}", encoding="utf-8")

    code = trellis_import.main([
        str(quelle), "--fahrzeug", "rookie", "--config", str(tmp_path / "fehlt.json"),
        "--vehicles-dir", str(vehicles), "--out", str(aus)])
    assert code == 0

    szene = trimesh.load(str(aus / "rookie.glb"))
    assert isinstance(szene, trimesh.Scene)
    for name in ("karosserie", "rad_vl", "rad_vr", "rad_hl", "rad_hr"):
        assert name in szene.graph.nodes

    teile = json.loads((aus / "rookie_teile.json").read_text(encoding="utf-8"))
    assert teile["fahrzeug"] == "rookie"
    assert teile["gelenkt"] == ["rad_vl", "rad_vr"]
    assert len(teile["raeder"]) == 4
    assert teile["raddurchmesser_m"] == pytest.approx(0.65)
    # Die Nabenhoehe muss der Radradius sein, sonst haengt das Rad im Boden.
    for rad in teile["raeder"]:
        assert rad["nabe"][2] == pytest.approx(0.325, abs=0.02)
    del glb_io


def test_keine_raeder_schreibt_ein_einzelnes_netz(tmp_path):
    import trellis_import

    auto = _auto_mit_raedern()
    quelle = tmp_path / "rookie.glb"
    quelle.write_bytes(trimesh.exchange.gltf.export_glb(trimesh.Scene(auto)))
    aus = tmp_path / "assets"
    vehicles = tmp_path / "vehicles"
    vehicles.mkdir()
    (vehicles / "rookie.json").write_text("{}", encoding="utf-8")

    trellis_import.main([str(quelle), "--fahrzeug", "rookie", "--keine-raeder",
                         "--config", str(tmp_path / "fehlt.json"),
                         "--vehicles-dir", str(vehicles), "--out", str(aus)])
    assert not (aus / "rookie_teile.json").exists()
    geladen = trimesh.load(str(aus / "rookie.glb"))
    anzahl = len(geladen.geometry) if isinstance(geladen, trimesh.Scene) else 1
    assert anzahl == 1


def test_bericht_nennt_die_dreiecke_je_teil():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    text = zerlegt.text()
    assert "Karosserie" in text
    assert "rad_vl" in text
