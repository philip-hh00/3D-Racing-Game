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


def test_symmetrisch_gleicht_die_vier_naben_an():
    """Ein Auto ist symmetrisch, die Messung weiss das nicht.

    Am Modell aus zwei Ansichten lagen die gemessenen Nabenmitten zwischen
    0,56 und 0,74 m - 18 cm auseinander. Sichtbar waere das als Rad, das beim
    Lenken um eine andere Achse schwenkt als sein Gegenueber.
    """
    schief = {
        "rad_vl": (0.52, 0.96),
        "rad_vr": (-0.86, -0.26),
        "rad_hl": (0.46, 0.88),
        "rad_hr": (-0.94, -0.50),
    }
    gleich = radschnitt.symmetrisch(schief)
    mitten = {n: (b[0] + b[1]) / 2 for n, b in gleich.items()}
    assert mitten["rad_vl"] == pytest.approx(-mitten["rad_vr"], abs=1e-9)
    assert mitten["rad_hl"] == pytest.approx(-mitten["rad_hr"], abs=1e-9)
    breiten = [abs(b[1] - b[0]) for b in gleich.values()]
    assert max(breiten) - min(breiten) < 1e-9, "alle vier Reifen sind gleich breit"


def test_symmetrisch_behaelt_die_seite():
    gleich = radschnitt.symmetrisch({
        "rad_vl": (0.60, 0.90), "rad_vr": (-0.90, -0.60),
        "rad_hl": (0.60, 0.90), "rad_hr": (-0.90, -0.60)})
    assert all(v > 0 for v in gleich["rad_vl"])
    assert all(v < 0 for v in gleich["rad_vr"])


def test_symmetrisch_kommt_mit_einer_fehlenden_achse_zurecht():
    gleich = radschnitt.symmetrisch({"rad_vl": (0.6, 0.9), "rad_vr": (-0.9, -0.6)})
    assert set(gleich) == {"rad_vl", "rad_vr"}


def test_zu_breites_band_wird_nach_innen_gekappt():
    """Ein Pkw-Reifen misst hoechstens rund 45 Prozent seines Durchmessers.

    Am dichteren Modell aus zwei Ansichten lief die Messung von der Lauflaeche
    nach innen in den Radkasten weiter und lieferte Baender bis 60 cm. Gekappt
    wird nach innen - die Aussenkante des Reifens ist die verlaessliche, innen
    geht er ohne Absatz in den Radkasten ueber.

    Geprueft wird die Entscheidung der Messung, nicht die Bounding-Box des
    Ergebnisses: ein grob aufgeloester Zylinder hat nur zwei Dreiecke ueber
    die ganze Reifenbreite, deren Schwerpunkte im Band liegen, waehrend die
    Dreiecke selbst darueber hinausreichen. Daran laesst sich die Kappung
    nicht ablesen.
    """
    s = vehicle_specs.spec("rookie")
    nabe = vehicle_specs.radpositionen("rookie")[0]        # vorne links
    rng = np.random.default_rng(4)

    # Ein dichter Reifenkoerper von 0,55 m Breite, wie ihn ein feines Netz
    # liefert: viele Dreiecksmitten innerhalb des Reifenradius.
    n = 4000
    winkel = rng.uniform(0, 2 * np.pi, n)
    radius = np.sqrt(rng.uniform(0, 1, n)) * s.rad_m / 2 * 0.95
    mitten = np.column_stack([
        nabe[0] + radius * np.cos(winkel),
        rng.uniform(nabe[1] - 0.275, nabe[1] + 0.275, n),
        nabe[2] + radius * np.sin(winkel),
    ])

    band = radschnitt.querband(mitten, nabe, s.rad_m / 2.0)
    assert band is not None, "Vorbedingung: das Band muss messbar sein"
    breite = abs(band[1] - band[0])
    assert breite <= s.rad_m * radschnitt.BAND_HOECHSTANTEIL + 1e-9, \
        f"Band ist {breite:.3f} m breit, hoechstens erlaubt " \
        f"{s.rad_m * radschnitt.BAND_HOECHSTANTEIL:.3f} m"
    # Nach innen gekappt heisst: die Aussenkante bleibt stehen.
    assert max(band) == pytest.approx(nabe[1] + 0.275, abs=0.03)


def test_die_schaetzung_ist_genauso_breit_wie_die_obergrenze():
    """Zwei Vorstellungen davon, wie breit ein Reifen hoechstens ist, waeren
    eine Falle: der eine Weg schnitte doppelt so viel heraus wie der andere."""
    s = vehicle_specs.spec("rookie")
    # Ein Fahrzeug ohne Raeder - die Messung findet nichts, die Schaetzung greift.
    ohne = trimesh.creation.box(extents=(s.laenge_m, s.breite_m, 1.2))
    ohne.apply_translation((0, 0, 0.6))
    zerlegt = radschnitt.schneiden(ohne, s)
    geschaetzt = [h for h in zerlegt.hinweise if "geschaetzt" in h]
    assert geschaetzt, "Vorbedingung: die Schaetzung muss greifen"
    for hinweis in geschaetzt:
        assert f"{s.rad_m * radschnitt.BAND_HOECHSTANTEIL:.2f}" in hinweis


def _reifenpunkte(mitte, radius=0.325, n=3000, seed=9):
    """Punkte auf der Aussenflaeche eines Reifens, plus etwas Felge innen."""
    rng = np.random.default_rng(seed)
    winkel = rng.uniform(0, 2 * np.pi, n)
    r = np.where(rng.random(n) < 0.75, radius, radius * rng.uniform(0.5, 0.8, n))
    return np.column_stack([
        mitte[0] + r * np.cos(winkel),
        rng.uniform(mitte[1] - 0.1, mitte[1] + 0.1, n),
        mitte[2] + r * np.sin(winkel),
    ])


def test_nabe_kommt_aus_der_aufstandsflaeche():
    """Der Fehler, der das Rad kreisen liess statt drehen.

    Die gerechnete Nabe kommt aus der Sollmasstabelle; das erzeugte Modell
    haelt sich nicht auf den Zentimeter daran. Liegt die Drehachse daneben,
    wandert das Rad beim Rollen sichtbar auf und ab.
    """
    echte_mitte = np.array([1.40, 0.76, 0.38])
    punkte = _reifenpunkte(echte_mitte)
    geraten = np.array([1.312, 0.76, 0.325])       # aus der Tabelle, daneben
    gefunden = radschnitt.nabe_aus_bodenkontakt(punkte, geraten, 0.325)
    assert gefunden[0] == pytest.approx(echte_mitte[0], abs=0.02)
    assert gefunden[2] == pytest.approx(echte_mitte[2], abs=0.02)


def test_mitgeschnittener_kotfluegel_zieht_die_nabe_nicht_hoch():
    """Genau daran ist die erste Fassung gescheitert.

    Sie hat ueber die Reifenflanke gemittelt. Der Radlauf liegt aber
    **oberhalb** des Rades und zieht jeden Mittelwert nach oben - am echten
    Modell kamen Nabenhoehen bis 0,51 m heraus, bei einem Rad von 0,65 m
    Durchmesser, das auf der Strasse steht. Der Boden laesst sich nicht
    verschieben, ein Mittelwert schon.
    """
    mitte = np.array([1.35, 0.76, 0.33])
    reifen = _reifenpunkte(mitte)
    rng = np.random.default_rng(1)
    kotfluegel = np.column_stack([
        rng.uniform(mitte[0] - 0.45, mitte[0] + 0.45, 1500),
        rng.uniform(mitte[1] - 0.1, mitte[1] + 0.1, 1500),
        rng.uniform(mitte[2] + 0.30, mitte[2] + 0.75, 1500),
    ])
    gefunden = radschnitt.nabe_aus_bodenkontakt(
        np.vstack([reifen, kotfluegel]), (1.312, 0.76, 0.325), 0.325)
    assert gefunden[2] == pytest.approx(mitte[2], abs=0.02)


def test_nabe_laesst_die_querlage_unberuehrt():
    """Quer entscheidet die Bandmessung, nicht die Aufstandsflaeche."""
    punkte = _reifenpunkte(np.array([1.3, 0.8, 0.35]))
    gefunden = radschnitt.nabe_aus_bodenkontakt(punkte, (1.312, 0.764, 0.325), 0.325)
    assert gefunden[1] == pytest.approx(0.764)


def test_nabe_gibt_bei_zu_wenig_punkten_auf():
    geraten = (1.312, 0.764, 0.325)
    gefunden = radschnitt.nabe_aus_bodenkontakt(np.zeros((4, 3)), geraten, 0.325)
    assert tuple(gefunden) == pytest.approx(geraten)


def test_alle_vier_raeder_stehen_auf_derselben_hoehe():
    """Ein Auto steht waagerecht."""
    naben = {
        "rad_vl": np.array([1.3, 0.76, 0.31]),
        "rad_vr": np.array([1.3, -0.76, 0.36]),
        "rad_hl": np.array([-1.3, 0.76, 0.33]),
        "rad_hr": np.array([-1.3, -0.76, 0.34]),
    }
    gleich = radschnitt.naben_angleichen(naben)
    hoehen = {round(float(n[2]), 9) for n in gleich.values()}
    assert len(hoehen) == 1
    # Laengs- und Querlage bleiben, wie sie gemessen wurden.
    assert gleich["rad_vl"][0] == pytest.approx(1.3)
    assert gleich["rad_vr"][1] == pytest.approx(-0.76)


def test_die_nabe_liegt_im_mittelpunkt_des_herausgetrennten_rades():
    """Am zusammengesetzten Fahrzeug: nach dem Schnitt muss der Ursprung des
    Radnetzes wirklich in der Mitte liegen, sonst eiert es."""
    s = vehicle_specs.spec("rookie")
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), s)
    for rad in zerlegt.raeder:
        v = rad.mesh.vertices
        abstand = np.hypot(v[:, 0], v[:, 2])
        aussen = abstand > 0.8 * s.rad_m / 2
        assert abstand[aussen].std() < 0.02, \
            f"{rad.name}: Reifenflanke nicht rund um den Ursprung"


def test_bericht_nennt_die_dreiecke_je_teil():
    zerlegt = radschnitt.schneiden(_auto_mit_raedern(), vehicle_specs.spec("rookie"))
    text = zerlegt.text()
    assert "Karosserie" in text
    assert "rad_vl" in text
