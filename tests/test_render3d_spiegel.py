"""Spiegel im Cockpit (1.1.0): Kamera aus dem Knoten, Spiegelung, wann gezeichnet wird.

Rechnung und Auswahl prüfen reine Tests; die Spiegelung (links hinten steht im
Spiegel links), das Auflegen aufs Glas und das Überspringen außerhalb des
Cockpits laufen einmal wirklich durch OpenGL — in einem Kontext ohne Fenster,
übersprungen, wo es keinen gibt. Vertrag der Knoten: ``VEREINBARUNGEN.md``.
"""
from __future__ import annotations

import json
import math
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.render3d import ansichten, camera, grafik, matrix, spiegel  # noqa: E402
from src.render3d.vehicle_node import Cockpitmasse, Fahrzeugknoten, Radplatz  # noqa: E402

INNEN = np.array([0.42, 0.01, 1.33])
LINKS = np.array([0.51, 0.93, 1.09])
RECHTS = np.array([0.51, -0.93, 1.09])
COCKPIT = Cockpitmasse(augpunkt=np.array([-0.1, 0.35, 1.2]), haube=np.array([1.2, 0.0, 1.1]))


def _knoten() -> Fahrzeugknoten:
    raeder = [Radplatz("rad_vl", np.array([1.3, 0.8, 0.33]), True),
              Radplatz("rad_vr", np.array([1.3, -0.8, 0.33]), True),
              Radplatz("rad_hl", np.array([-1.3, 0.8, 0.33]), False),
              Radplatz("rad_hr", np.array([-1.3, -0.8, 0.33]), False)]
    return Fahrzeugknoten(raeder, 0.66, cockpit=COCKPIT,
                          anbauteile={"spiegel_innen": INNEN, "spiegel_l": LINKS,
                                      "spiegel_r": RECHTS})


# ---------------------------------------------------------------------------
# Kamera aus dem Knoten
# ---------------------------------------------------------------------------

def test_spiegelkamera_sitzt_im_knoten_und_blickt_nach_hinten():
    k = _knoten()
    pos, gier = (30.0, -12.0, 0.0), 0.9
    m = k.matrizen(pos, gier)
    for name, ursprung in (("spiegel_innen", INNEN), ("spiegel_l", LINKS), ("spiegel_r", RECHTS)):
        auge, ziel, oben = spiegel.pose(name, ursprung, pos, gier, k.aufbau_matrix())
        np.testing.assert_allclose(auge, m[name][:3, 3], atol=1e-6)
        blick = (ziel - auge) / np.linalg.norm(ziel - auge)
        vorn = np.array([math.cos(gier), math.sin(gier), 0.0])
        assert blick @ vorn < -0.9, "der Spiegel blickt nach hinten"
        np.testing.assert_allclose(oben, [0, 0, 1], atol=1e-9)


def test_spiegelkamera_rechnet_wie_blick_aus_der_ansichtskamera():
    """Dieselbe Lage wie ``Ansichtskamera.blick_aus`` mit Punkt und Richtung des Knotens."""
    kam = ansichten.Ansichtskamera(ansichten.COCKPIT, COCKPIT)
    k = _knoten()
    k.neigen(0.03, -0.05)
    pos, gier = (4.0, 7.0, 0.0), -1.2
    for name, ursprung in (("spiegel_innen", INNEN), ("spiegel_l", LINKS)):
        art = spiegel.ARTEN[name]
        erwartet = kam.blick_aus(ansichten.COCKPIT, pos, gier, k.aufbau_matrix(),
                                 punkt=ursprung, richtung=art.richtung())
        ist = spiegel.pose(name, ursprung, pos, gier, k.aufbau_matrix())
        for a, b in zip(ist, erwartet):
            np.testing.assert_allclose(a, b, atol=1e-9)


def test_spiegelkamera_nickt_und_wankt_mit_dem_aufbau():
    """Auf dem schwingenden Aufbau wandert der Spiegel mit — wie sein Knoten."""
    k = _knoten()
    k.neigen(0.05, 0.08)
    pos, gier = (0.0, 0.0, 0.0), 0.0
    auge, ziel, oben = spiegel.pose("spiegel_l", LINKS, pos, gier, k.aufbau_matrix())
    np.testing.assert_allclose(auge, k.matrizen(pos, gier)["spiegel_l"][:3, 3], atol=1e-6)
    gerade = spiegel.pose("spiegel_l", LINKS, pos, gier, None)
    assert not np.allclose(auge, gerade[0])
    assert not np.allclose(oben, [0, 0, 1])           # das Dach neigt sich, der Spiegel mit


def test_aussenspiegel_blicken_nach_aussen_der_innenspiegel_gerade():
    k = _knoten()
    pos, gier = (0.0, 0.0, 0.0), 0.0
    d = {}
    for name, ursprung in (("spiegel_innen", INNEN), ("spiegel_l", LINKS), ("spiegel_r", RECHTS)):
        auge, ziel, _o = spiegel.pose(name, ursprung, pos, gier, k.aufbau_matrix())
        d[name] = (ziel - auge) / np.linalg.norm(ziel - auge)
    assert d["spiegel_innen"][1] == pytest.approx(0.0, abs=1e-9)
    assert d["spiegel_l"][1] > 0.1 and d["spiegel_r"][1] < -0.1      # links: +Y, rechts: -Y
    assert d["spiegel_l"][1] == pytest.approx(-d["spiegel_r"][1])


# ---------------------------------------------------------------------------
# Spiegelung
# ---------------------------------------------------------------------------

def _bildpunkt_u(name: str, ursprung, welt_punkt) -> float:
    """Wo ein Weltpunkt im Kamerabild des Spiegels liegt (0 = links, 1 = rechts), vor dem Drehen."""
    art = spiegel.ARTEN[name]
    groesse = art.groesse(2)
    auge, ziel, oben = spiegel.pose(name, ursprung, (0.0, 0.0, 0.0), 0.0, None)
    mvp = spiegel.matrix(name, groesse, auge, ziel, oben)
    c = mvp.astype(np.float64) @ np.array([*welt_punkt, 1.0])
    assert c[3] > 0, "der Punkt liegt hinter der Spiegelkamera"
    return float(c[0] / c[3] * 0.5 + 0.5)


@pytest.mark.parametrize("name,ursprung", [("spiegel_innen", INNEN), ("spiegel_l", LINKS),
                                           ("spiegel_r", RECHTS)])
def test_auto_hinten_links_steht_im_spiegel_links(name, ursprung):
    """Die Kamera blickt nach hinten: links steht in ihrem Bild rechts. Der Spiegel dreht es zurück."""
    u_links, _ = spiegel.spiegel_uv(_bildpunkt_u(name, ursprung, (-12.0, 2.0, 0.7)), 0.5)
    u_rechts, _ = spiegel.spiegel_uv(_bildpunkt_u(name, ursprung, (-12.0, -2.0, 0.7)), 0.5)
    # Im Kamerabild ist links (+Y) rechts; nach dem Drehen ist es links des anderen.
    assert u_links < u_rechts
    # Und der Punkt links hinten liegt vor dem Drehen rechts im Bild.
    assert _bildpunkt_u(name, ursprung, (-12.0, 2.0, 0.7)) > _bildpunkt_u(name, ursprung, (-12.0, -2.0, 0.7))


def test_spiegel_uv_dreht_waagerecht():
    assert spiegel.spiegel_uv(0.0, 0.3) == (1.0, 0.3)
    assert spiegel.spiegel_uv(1.0, 0.8) == (0.0, 0.8)
    assert spiegel.spiegel_uv(0.25, 0.5) == (0.75, 0.5)


def test_blick_ohne_numpy_gleicht_camera_blick():
    auge, ziel, oben = (3.0, -2.0, 1.1), (-17.0, 4.0, 0.9), (0.02, 0.01, 1.0)
    np.testing.assert_allclose(spiegel._blick(auge, ziel, oben),
                               camera.blick(auge, ziel, oben), atol=1e-5)


# ---------------------------------------------------------------------------
# Wann gezeichnet wird
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ansicht,erwartet", [
    (ansichten.COCKPIT, True),
    (ansichten.MOTORHAUBE, False),
    (ansichten.VERFOLGER_FERN, False),
    (ansichten.VERFOLGER_NAH, False),
])
def test_nur_im_cockpit_brauchen_spiegel_ein_bild(ansicht, erwartet):
    assert spiegel.noetig(ansichten.Ansichtskamera(ansicht)) is erwartet


def test_beim_zurueckschauen_und_ohne_ansicht_keine_spiegel():
    kam = ansichten.Ansichtskamera(ansichten.COCKPIT)
    kam.rueckblick = True
    assert spiegel.noetig(kam) is False
    # Eine Kamera ohne Ansicht (Zuschauer, TV-Regie) hat keine Spiegel.
    assert spiegel.noetig(SimpleNamespace()) is False
    assert spiegel.noetig(SimpleNamespace(ansicht="tv")) is False


def test_nur_sichtbares_glas_wird_gerechnet():
    # Hauptkamera blickt nach +X: ein Spiegel davor liegt im Bild, einer weit seitlich oder dahinter nicht.
    mvp = camera.perspektive(64.0, 16 / 9, 0.08, 500.0) @ camera.blick((0, 0, 1.2), (20, 0, 1.2))
    assert spiegel.sichtbar(mvp, (3.0, 0.2, 1.3))
    assert not spiegel.sichtbar(mvp, (0.5, -3.0, 1.0))        # weit rechts, fast neben dem Auge
    assert not spiegel.sichtbar(mvp, (-5.0, 0.0, 1.2))        # hinter der Kamera


def test_takt_hoch_innen_jedes_bild_aussen_jedes_zweite_niedrig_alle_jedes_zweite():
    hoch_innen = [spiegel.jetzt_dran(2, b, 0) for b in range(8)]
    hoch_aussen = [spiegel.jetzt_dran(2, b, 1) for b in range(8)]
    assert all(hoch_innen)
    assert sum(hoch_aussen) == 4
    for index in range(3):
        niedrig = [spiegel.jetzt_dran(1, b, index) for b in range(8)]
        assert sum(niedrig) == 4 and not any(a and b for a, b in zip(niedrig, niedrig[1:]))
    # Niedrig versetzt die Spiegel: nie alle im selben Bild.
    assert not all(spiegel.jetzt_dran(1, b, i) for i in range(3) for b in (0,))


def test_takt_zaehlt_je_mensch_nicht_je_zeichenaufruf():
    """Im Splitscreen zeichnet die Szene zweimal je Bild: jeder Mensch bekommt seinen eigenen Takt."""
    speicher = spiegel.Spiegelspeicher(None)
    folge = [(speicher.takt(1), speicher.takt(2)) for _ in range(4)]
    assert folge == [(0, 0), (1, 1), (2, 2), (3, 3)]
    # Beide Außenspiegel kommen also reihum dran, keiner bleibt stehen.
    for kennung in (1, 2):
        takte = [speicher.takt(kennung) for _ in range(6)]
        assert sum(spiegel.jetzt_dran(2, t, 1) for t in takte) == 3


def test_bildgroesse_folgt_dem_format_des_glases_und_der_stufe():
    for name in spiegel.NAMEN:
        art = spiegel.ARTEN[name]
        hoch, niedrig = art.groesse(2), art.groesse(1)
        assert hoch[0] > niedrig[0] and hoch[1] > niedrig[1]
        assert hoch[0] / hoch[1] == pytest.approx(niedrig[0] / niedrig[1], rel=0.2)
    # Innenspiegel breit und flach (17 x 4,4 cm), Außenspiegel runder (16 x 7 cm).
    assert spiegel.ARTEN["spiegel_innen"].groesse(2)[0] / spiegel.ARTEN["spiegel_innen"].groesse(2)[1] >= 3.5
    assert 2.0 <= spiegel.ARTEN["spiegel_l"].groesse(2)[0] / spiegel.ARTEN["spiegel_l"].groesse(2)[1] <= 2.6


# ---------------------------------------------------------------------------
# Grafikeinstellung
# ---------------------------------------------------------------------------

def test_grafikfeld_spiegel_hat_je_stufe_einen_vorgabewert():
    g = grafik.STUFEN
    assert {g[n].spiegel for n in grafik.STUFEN_NAMEN} <= {0, 1, 2}
    assert g["niedrig"].spiegel <= g["mittel"].spiegel <= g["hoch"].spiegel <= g["ultra"].spiegel
    assert g["hoch"].spiegel == 2


def test_grafik_spiegel_bleibt_im_profil():
    grafik.stufe_setzen("hoch")
    grafik.setzen(spiegel=1)
    daten = grafik.als_dict()
    assert daten["spiegel"] == 1 and daten["stufe"] == "eigen"
    grafik.stufe_setzen("hoch")
    assert grafik.aus_dict(daten).spiegel == 1
    # Ein älteres Profil ohne das Feld bekommt den Wert seiner Stufe.
    alt = dict(daten)
    del alt["spiegel"]
    alt["stufe"] = "mittel"
    assert grafik.aus_dict(alt).spiegel == grafik.STUFEN["mittel"].spiegel
    grafik.stufe_setzen("hoch")


def test_profil_speichert_den_spiegel(tmp_path, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile, "_profile_path", lambda: str(tmp_path / "profil.json"))
    p = profile.Profile(username="probe")
    grafik.stufe_setzen("hoch")
    grafik.setzen(spiegel=0)
    p.grafik = grafik.als_dict()
    p.save()
    geladen = profile.Profile.load()
    assert geladen.grafik["spiegel"] == 0
    assert grafik.aus_dict(geladen.grafik).spiegel == 0
    grafik.stufe_setzen("hoch")


def test_einstellungsseite_hat_einen_regler_fuer_den_spiegel():
    from src.states.menu import settings_page
    regler = {f: o for f, _b, o in settings_page._grafik_regler()}
    assert [w for w, _a in regler["spiegel"]] == [0, 1, 2]


# ---------------------------------------------------------------------------
# Durch OpenGL
# ---------------------------------------------------------------------------

moderngl = pytest.importorskip("moderngl")
trimesh = pytest.importorskip("trimesh")

from src.render3d import rennszene, shader, track_mesh  # noqa: E402


@pytest.fixture(scope="module")
def ctx():
    try:
        kontext = moderngl.create_standalone_context()
    except Exception as fehler:                      # pragma: no cover - Treiber
        pytest.skip(f"Kein OpenGL-Kontext: {fehler}")
    yield kontext
    kontext.release()


def _flaeche(punkte, material):
    from trimesh.visual.material import PBRMaterial
    t = trimesh.Trimesh(vertices=punkte, faces=[[0, 1, 2], [0, 2, 3]], process=False)
    t.visual = trimesh.visual.TextureVisuals(
        uv=np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float), material=material)
    return t


@pytest.fixture(scope="module")
def modellordner(tmp_path_factory):
    """Ein Ersatzauto aus Kisten mit Spiegelglas oben auf dem Dach."""
    from trimesh.visual.material import PBRMaterial
    ordner = tmp_path_factory.mktemp("vehicles_spiegel")
    szene = trimesh.Scene()
    karosserie = trimesh.creation.box((4.0, 1.8, 1.2))
    karosserie.visual = trimesh.visual.TextureVisuals(
        uv=np.zeros((len(karosserie.vertices), 2)),
        material=PBRMaterial(name="lack", baseColorFactor=[200, 30, 30, 255],
                             metallicFactor=0.0, roughnessFactor=0.4))
    szene.add_geometry(karosserie, node_name="karosserie", geom_name="karosserie")
    naben = {"rad_vl": (1.3, 0.8), "rad_vr": (1.3, -0.8), "rad_hl": (-1.3, 0.8), "rad_hr": (-1.3, -0.8)}
    for name, (x, y) in naben.items():
        szene.add_geometry(trimesh.creation.box((0.65, 0.2, 0.65)), node_name=name, geom_name=name,
                           transform=trimesh.transformations.translation_matrix((x, y, 0.325)))
    glas = _flaeche(np.array([[0, -0.084, -0.022], [0, 0.084, -0.022], [0, 0.084, 0.022], [0, -0.084, 0.022]]),
                    PBRMaterial(name="spiegel", baseColorFactor=[180, 190, 200, 255],
                                metallicFactor=1.0, roughnessFactor=0.05))
    szene.add_geometry(glas, node_name="spiegel_innen", geom_name="spiegel_innen",
                       transform=trimesh.transformations.translation_matrix((0.4, 0.0, 1.0)))
    szene.export(str(ordner / "rookie.glb"))
    (ordner / "rookie_teile.json").write_text(json.dumps({
        "fahrzeug": "rookie", "laenge_m": 4.0, "breite_m": 1.8, "raddurchmesser_m": 0.65,
        "gelenkt": ["rad_vl", "rad_vr"],
        "raeder": [{"name": n, "nabe": [x, y, 0.325]} for n, (x, y) in naben.items()],
    }), encoding="utf-8")
    return ordner


@pytest.fixture(scope="module")
def netz():
    mittellinie = [{"x": x * 12.5, "y": 0.0} for x in range(-20, 40)]
    return track_mesh.bauen({"centerline": mittellinie, "track_width": 250.0,
                             "start_positions": [{"x": 0.0, "y": 0.0, "angle": 0.0}]})


@pytest.fixture(autouse=True)
def _grafik_zuruecksetzen():
    grafik.stufe_setzen("hoch")
    yield
    grafik.stufe_setzen("hoch")


def _stand(kennung, x, y=0.0):
    return rennszene.Fahrzeugstand(kennung=kennung, schluessel="rookie",
                                   pos_m=np.array([x, y, 0.0]), gierwinkel_rad=0.0)


def _zeichnen(ctx, szene, staende, spiegel_fuer):
    puffer = ctx.simple_framebuffer((160, 120), components=3)
    puffer.use()
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.clear(0.2, 0.4, 0.8)
    kamera = camera.Verfolgerkamera(abstand_m=9.0, hoehe_m=3.0, zielhoehe_m=1.0)
    kamera.setzen(staende[0].pos_m, staende[0].gierwinkel_rad)
    mvp = camera.perspektive(55.0, 160 / 120, 0.2, 400.0) @ kamera.blickmatrix()
    szene.fortschreiben(staende)
    szene.zeichnen(mvp, kamera.auge, staende, spiegel=spiegel_fuer)
    puffer.release()


def _rote_spalten(pf) -> np.ndarray:
    """Spalten (0..1) der roten Pixel im Spiegelbild — das Rot des Lacks der anderen Autos."""
    b, h = pf.groesse
    roh = np.frombuffer(pf.farbe.read(), dtype=np.float16).astype(np.float32).reshape(h, b, 4)
    rot = (roh[..., 0] > 0.08) & (roh[..., 0] > 3.0 * roh[..., 1]) & (roh[..., 0] > 3.0 * roh[..., 2])
    spalten = np.nonzero(rot)[1]
    return (spalten + 0.5) / b


@pytest.mark.parametrize("quer,links_im_kamerabild", [(3.0, True), (-3.0, False)])
def test_spiegelbild_zeigt_das_auto_dahinter_auf_der_richtigen_seite(
        ctx, netz, modellordner, quer, links_im_kamerabild):
    """Auto 12 m hinter uns, 3 m links: im Kamerabild (nach hinten) rechts, im Spiegel links."""
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    staende = [_stand(1, 0.0), _stand(2, -12.0, quer)]
    _zeichnen(ctx, szene, staende, spiegel_fuer=1)
    pf = szene.spiegelspeicher.satz(1, 2)["spiegel_innen"]
    assert pf.gueltig
    u = _rote_spalten(pf)
    assert len(u) > 20, "das Auto hinter uns steht nicht im Spiegelbild"
    # Kamerabild: links des Wagens (+Y) liegt rechts im Bild.
    assert bool(u.mean() > 0.5) is links_im_kamerabild
    # Auf dem Glas (Spiegelung) liegt es auf der Seite, auf der es wirklich ist.
    assert bool(spiegel.spiegel_uv(float(u.mean()), 0.5)[0] < 0.5) is links_im_kamerabild
    szene.freigeben()


def test_spiegelbild_mit_mehrfachproben_wird_zusammengefasst(ctx, netz, modellordner, monkeypatch):
    """Der Weg mit MSAA (``spiegel.MSAA``) löst auf die Textur auf und liefert dasselbe Bild."""
    monkeypatch.setattr(spiegel, "MSAA", True)
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    _zeichnen(ctx, szene, [_stand(1, 0.0), _stand(2, -12.0, 3.0)], spiegel_fuer=1)
    pf = szene.spiegelspeicher.satz(1, 2)["spiegel_innen"]
    assert pf.fbo_ms is not None and pf.gueltig
    assert len(_rote_spalten(pf)) > 20 and _rote_spalten(pf).mean() > 0.5
    szene.freigeben()


def test_ohne_cockpit_wird_kein_spiegel_gezeichnet(ctx, netz, modellordner):
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    aufrufe = []
    original = szene._spiegel_rendern
    szene._spiegel_rendern = lambda *a, **k: aufrufe.append(1) or original(*a, **k)
    staende = [_stand(1, 0.0), _stand(2, -12.0, 3.0)]
    _zeichnen(ctx, szene, staende, spiegel_fuer=None)
    assert aufrufe == [] and szene._spiegel_aktiv == {}
    assert szene.spiegelspeicher._saetze == {}, "Puffer nur für wen sie braucht"
    _zeichnen(ctx, szene, staende, spiegel_fuer=1)
    assert aufrufe == [1]
    szene.freigeben()


def test_spiegel_aus_in_der_grafik_zeichnet_keinen(ctx, netz, modellordner):
    grafik.setzen(spiegel=0)
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    _zeichnen(ctx, szene, [_stand(1, 0.0), _stand(2, -12.0, 3.0)], spiegel_fuer=1)
    assert szene.spiegelspeicher._saetze == {}
    szene.freigeben()


def test_niedrig_rechnet_halbe_aufloesung_und_nicht_jedes_bild(ctx, netz, modellordner):
    grafik.setzen(spiegel=1)
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    staende = [_stand(1, 0.0), _stand(2, -12.0, 3.0)]
    _zeichnen(ctx, szene, staende, spiegel_fuer=1)
    pf = szene.spiegelspeicher.satz(1, 1)["spiegel_innen"]
    assert pf.groesse == spiegel.ARTEN["spiegel_innen"].groesse(1)
    assert pf.groesse[0] < spiegel.ARTEN["spiegel_innen"].groesse(2)[0]
    szene.freigeben()


def test_spiegel_hinter_der_kamera_wird_nicht_gerechnet(ctx, netz, modellordner):
    """Das Glas ist nur in der Cockpitansicht zu sehen; liegt es nicht im Bild, kostet es nichts."""
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    gerechnet = []
    original = szene._spiegel_bild
    szene._spiegel_bild = lambda *a, **k: gerechnet.append(a[1]) or original(*a, **k)
    staende = [_stand(1, 0.0)]
    puffer = ctx.simple_framebuffer((160, 120), components=3)
    puffer.use()
    szene.fortschreiben(staende)
    # Kamera blickt vom Wagen weg nach hinten: das Glas auf dem Dach liegt hinter ihr.
    mvp = camera.perspektive(55.0, 160 / 120, 0.2, 400.0) @ camera.blick((-3.0, 0.0, 1.5), (-40.0, 0.0, 1.5))
    szene.zeichnen(mvp, (-3.0, 0.0, 1.5), staende, spiegel=1)
    assert gerechnet == []
    puffer.release()
    szene.freigeben()


def test_glas_zeigt_das_bild_waagerecht_gedreht(ctx):
    """Das Glas liest das Kamerabild von rechts nach links: links im Bild rot, rechts grün wird rechts rot."""
    p = shader.programm(ctx)
    shader.modell_setzen(p, np.eye(4))
    shader.matrix_setzen(p, "mvp", np.eye(4))
    shader.setzen(p, "spiegel_modus", 1.0)
    bild = ctx.texture((2, 1), 4, np.array([[[1, 0, 0, 1], [0, 1, 0, 1]]], dtype=np.float16).tobytes(),
                       dtype="f2")
    bild.filter = (moderngl.NEAREST, moderngl.NEAREST)
    bild.use(spiegel.EINHEIT)
    ecken = np.array([[-1, -1, 0, 0, 0, 1, 0, 0], [1, -1, 0, 0, 0, 1, 1, 0],
                      [1, 1, 0, 0, 0, 1, 1, 1], [-1, 1, 0, 0, 0, 1, 0, 1]], dtype="f4")
    vbo = ctx.buffer(ecken.tobytes())
    ibo = ctx.buffer(np.array([0, 1, 2, 0, 2, 3], dtype="u4").tobytes())
    vao = ctx.vertex_array(p, [(vbo, "3f 3f 2f", "in_position", "in_normale", "in_uv")], ibo)
    ziel = ctx.simple_framebuffer((8, 4), components=4)
    ziel.use()
    ctx.disable(moderngl.DEPTH_TEST)
    ctx.clear(0, 0, 0, 1)
    vao.render()
    roh = np.frombuffer(ziel.read(components=4), dtype=np.uint8).reshape(4, 8, 4)
    links, rechts = roh[2, 1], roh[2, 6]
    # u = 0 (links auf dem Glas) liest die rechte Seite des Bildes: grün.
    assert links[1] > 150 and links[0] < 60
    assert rechts[0] > 150 and rechts[1] < 60
    ctx.enable(moderngl.DEPTH_TEST)
    for ding in (vao, vbo, ibo, bild, ziel, p):
        ding.release()


def test_glas_ohne_bild_ist_dunkles_spiegelglas(ctx, netz, modellordner):
    """Spiegel aus oder fremdes Auto: dunkles, spiegelndes Glas — kein Chrom-Loch, kein Rosa."""
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    fm = szene.speicher.holen("rookie")
    materialien = {hm.daten.name for hm, _e in rennszene._zeichenplan(fm.modell)[False] if hm is not None}
    assert spiegel.MATERIAL in materialien
    werte = dict(rennszene.SPIEGEL_GLAS)
    assert max(werte["grundton"]) < 0.7 and werte["rauheit_faktor"] < 0.2   # dunkler als Chrom (0,72/0,76/0,8)
    assert werte["metallic_faktor"] == 1.0                       # spiegelt den Himmel
    assert 0.0 < max(werte["emission"]) < 0.05                   # nie ganz schwarz, nie hell
    szene.freigeben()
