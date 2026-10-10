"""Tageszeit je Rennen: Tag, Abend, Nacht (``src/render3d/tageszeit.py``).

Geprüft wird, was sich ohne Bildvergleich festnageln lässt:

* **Tag ist die alte Welt.** Die Vorgabe ändert keinen Wert, der Shader läuft
  an allen Tageszeit-Zweigen vorbei, und ein gezeichnetes Bild setzt weder
  Tönung noch Lichter. (Dass das Bild Pixel für Pixel dasselbe ist wie vor der
  Änderung, wurde einmal gegen den alten Stand verglichen — ein Test kann
  keinen Stand von gestern vorhalten.)
* **Die Voreinstellungen** haben die Eigenschaften, die ihr Name verspricht:
  tiefe warme Sonne am Abend, Mond, Sterne und Lichter bei Nacht.
* **Die Lichterauswahl** nimmt die nächsten ``n``, blendet am Rand aus und
  schreibt in die Felder des Shaders.
* **Lobby und Profil:** das Feld ist optional (fehlt es, ist es Tag), der
  Host verteilt es, der Gast liest es, das Profil merkt es.
"""
from __future__ import annotations

import json
import math
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.render3d import grafik, shader, tageszeit  # noqa: E402
from src.render3d.tageszeit import ABEND, NACHT, TAG  # noqa: E402

#: Die Sonnenrichtung der ersten Fassung (Himmelsbild gp: Forest).
_SONNE = (0.5546, 0.3767, 0.742)


# ---------------------------------------------------------------------------
# Namen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("roh, erwartet", [
    ("Tag", "Tag"), ("Abend", "Abend"), ("Nacht", "Nacht"),
    ("night", "Nacht"), ("  ABEND ", "Abend"), ("day", "Tag"),
    (None, "Tag"), ("", "Tag"), (3, "Tag"), ("Mittag", "Tag"), (["Nacht"], "Tag"),
])
def test_namen_werden_normiert_und_fehlendes_ist_tag(roh, erwartet):
    assert tageszeit.normiere(roh) == erwartet


def test_jeder_name_hat_eine_vorgabe():
    assert set(tageszeit.NAMEN) == set(tageszeit.VORGABEN)
    for n in tageszeit.NAMEN:
        assert tageszeit.vorgabe(n).name == n
    assert tageszeit.vorgabe("unbekannt") is TAG


# ---------------------------------------------------------------------------
# Tag bleibt, wie er war
# ---------------------------------------------------------------------------
def test_tag_aendert_keinen_wert():
    assert not TAG.aktiv
    assert ABEND.aktiv and NACHT.aktiv
    thema = dict(sonne_farbe=(3.0, 2.85, 2.6), himmel_helligkeit=1.0, nebel_farbe=(0.7, 0.8, 0.9),
                 nebel_dichte=0.0018, boden_farbe=(0.3, 0.34, 0.22), himmel_zenit=(0.28, 0.44, 0.78),
                 himmel_horizont=(0.72, 0.8, 0.92), belichtung=1.0)
    assert tageszeit.umgebung_werte(TAG, thema) == thema
    s = np.asarray(_SONNE) / np.linalg.norm(_SONNE)
    assert np.array_equal(tageszeit.sonne_richtung(TAG, _SONNE), s)
    assert tageszeit.himmel_schalter(TAG) == (0.0, 0.0, 0.0, 0.0)
    assert TAG.sterne == 0.0 and not TAG.lichter and TAG.lampen_leuchten == 0.0
    assert (TAG.vorn_leuchten, TAG.hinten_leuchten) == (1.0, 1.0)


def test_schattenversatz_des_tages_ist_der_alte():
    """0,0006 + 0,0025 je Neigung stand fest im Shader, bevor es ein Uniform wurde."""
    assert TAG.schatten_bias == (0.0006, 0.0025)
    assert "schatten_bias.x + schatten_bias.y * neigung" in shader.FRAGMENT
    # und der Vorgabewert des Uniforms ist derselbe
    quelle = Path(shader.__file__).read_text(encoding="utf-8")
    assert '("schatten_bias", (0.0006, 0.0025))' in quelle


def test_shader_hat_platz_fuer_die_lichter():
    assert f"lichter_pos[{shader.MAX_LICHTER}]" in shader.FRAGMENT
    assert "@MAX_LICHTER@" not in shader.FRAGMENT


# ---------------------------------------------------------------------------
# Voreinstellungen
# ---------------------------------------------------------------------------
def _hoehe_grad(v) -> float:
    v = np.asarray(v, dtype=float)
    return math.degrees(math.asin(v[2] / np.linalg.norm(v)))


def test_abend_hat_tiefe_warme_sonne_und_lange_schatten():
    s = tageszeit.sonne_richtung(ABEND, _SONNE)
    assert _hoehe_grad(_SONNE) > 40.0
    assert 5.0 <= _hoehe_grad(s) <= 15.0
    assert math.isclose(float(np.linalg.norm(s)), 1.0, rel_tol=1e-9)
    # Die Himmelsrichtung bleibt: Schatten und Himmelsbild gehören zusammen.
    assert math.isclose(math.atan2(s[1], s[0]), math.atan2(_SONNE[1], _SONNE[0]), abs_tol=1e-9)
    r, g, b = ABEND.sonne_faktor
    assert r > g > b, "warmes Licht: Rot vor Grün vor Blau"
    assert ABEND.belichtung <= 1.0
    assert ABEND.schatten_bias[0] < TAG.schatten_bias[0], "tiefe Sonne braucht weniger Versatz"
    assert not ABEND.lichter and ABEND.lampen_leuchten == 0.0 and ABEND.sterne == 0.0


def test_nacht_hat_mond_sterne_und_lichter():
    s = tageszeit.sonne_richtung(NACHT, _SONNE)
    assert 20.0 <= _hoehe_grad(s) <= 60.0
    assert NACHT.sterne > 0.0 and NACHT.lichter
    assert NACHT.himmel_helligkeit < 0.1
    assert max(NACHT.sonne_faktor) < 0.3, "Mondlicht, nicht Sonnenlicht"
    r, g, b = NACHT.sonne_faktor
    assert b > r, "kühles Licht"
    assert NACHT.belichtung > 1.5, "die Kamera gleicht die Dunkelheit aus"
    assert NACHT.vorn_leuchten > 1.0 and NACHT.hinten_leuchten > 1.0
    assert NACHT.lampen_leuchten > 0.0


def test_umgebung_wird_nach_der_tageszeit_umgerechnet():
    thema = dict(sonne_farbe=(3.0, 3.0, 3.0), himmel_helligkeit=1.0, nebel_farbe=(0.7, 0.8, 0.9),
                 nebel_dichte=0.002, boden_farbe=(0.3, 0.3, 0.3), himmel_zenit=(0.3, 0.4, 0.8),
                 himmel_horizont=(0.7, 0.8, 0.9), belichtung=1.0)
    nacht = tageszeit.umgebung_werte(NACHT, thema)
    assert nacht["himmel_helligkeit"] < 0.1
    assert sum(nacht["sonne_farbe"]) < 0.2 * sum(thema["sonne_farbe"])
    assert nacht["belichtung"] > 2.0
    assert all(a < b for a, b in zip(nacht["nebel_farbe"], thema["nebel_farbe"]))
    abend = tageszeit.umgebung_werte(ABEND, thema)
    assert abend["sonne_farbe"][0] > abend["sonne_farbe"][2] * 2.0
    # das Eingangswörterbuch bleibt unberührt
    assert thema["belichtung"] == 1.0


def test_himmel_schalter_ist_beim_tag_ganz_aus():
    assert tageszeit.himmel_schalter(TAG) == (0.0, 0.0, 0.0, 0.0)
    assert tageszeit.himmel_schalter(ABEND) == (1.0, 0.0, 0.0, 0.0)
    assert tageszeit.himmel_schalter(NACHT)[3] == 1.0


def _himmelsbild():
    """Ein Verlauf: Zeilen oben hell, unten dunkel, mit einem hellen Fleck bei der Sonne."""
    h, w = 64, 128
    bild = np.zeros((h, w, 3), dtype=np.uint8)
    bild[:] = np.linspace(230, 60, h)[:, None, None].astype(np.uint8)
    return bild


def test_himmel_bild_des_tages_aendert_sich_nicht_durch_den_tint():
    bild = _himmelsbild()
    gleich = tageszeit.himmel_bild(bild, TAG, _SONNE)
    erwartet = (bild.astype(np.float32) / 255.0)
    assert np.allclose(gleich, erwartet, atol=1e-4)


def test_himmel_bild_nacht_ist_dunkler_und_blauer():
    bild = _himmelsbild()
    nacht = tageszeit.himmel_bild(bild, NACHT, _SONNE)
    assert nacht.shape == bild.shape and nacht.dtype == np.float32
    lin = (nacht ** 2.2).reshape(-1, 3).mean(axis=0)
    assert lin[2] > lin[0]
    ref = ((bild.astype(np.float32) / 255.0) ** 2.2).reshape(-1, 3).mean(axis=0)
    assert lin[0] < ref[0]


def test_himmel_bild_abend_ist_am_horizont_zur_sonne_hin_orange():
    bild = np.full((64, 128, 3), 128, dtype=np.uint8)
    abend = tageszeit.himmel_bild(bild, ABEND, _SONNE)
    az = math.atan2(_SONNE[1], _SONNE[0])
    spalte_sonne = int((az / (2 * math.pi) + 0.5) * 128) % 128
    spalte_gegen = (spalte_sonne + 64) % 128
    zeile_horizont = 31
    zur_sonne = abend[zeile_horizont, spalte_sonne]
    weg = abend[zeile_horizont, spalte_gegen]
    zenit = abend[0, spalte_sonne]
    assert zur_sonne[0] > zur_sonne[2] * 1.3, "orange"
    assert zur_sonne[0] > weg[0], "zur Sonne hin wärmer"
    assert zenit[2] > zenit[0], "oben bläulich"


def test_himmel_bild_verbiegt_die_hoehe_so_dass_die_bildsonne_auf_das_ziel_rueckt():
    h, w = 256, 8
    e = tageszeit._hoehe_der_zeilen(h)
    bild_h = math.asin(_SONNE[2] / np.linalg.norm(_SONNE))
    # Ein heller Streifen genau auf der Höhe der Bildsonne wandert auf 9 Grad.
    roh = np.zeros((h, w, 3), dtype=np.uint8)
    zeile = int(np.argmin(np.abs(e - bild_h)))
    roh[zeile - 1:zeile + 2] = 255
    nur_verbogen = tageszeit.Tageszeit(name="Test", sonne_hoehe_grad=9.0)
    aus = tageszeit.himmel_bild(roh, nur_verbogen, _SONNE)
    hell = int(np.argmax(aus[:, 0, 0]))
    assert math.degrees(e[hell]) == pytest.approx(9.0, abs=1.5)


# ---------------------------------------------------------------------------
# Lichter
# ---------------------------------------------------------------------------
def _punktlicht(x, y=0.0, z=5.0, r=40.0, staerke=100.0):
    return tageszeit.Licht(pos=(x, y, z), reichweite_m=r, farbe=(staerke,) * 3)


def test_die_naechsten_n_lichter_werden_gewaehlt():
    lichter = [_punktlicht(x) for x in (80.0, 10.0, 30.0, 5.0, 60.0, 20.0)]
    gewaehlt = tageszeit.lichter_waehlen(lichter, (0.0, 0.0, 0.0), 3)
    xs = sorted(l.pos[0] for l in gewaehlt)
    assert xs == [5.0, 10.0, 20.0]


def test_ohne_platz_keine_lichter_und_zu_ferne_entfallen():
    lichter = [_punktlicht(10.0), _punktlicht(500.0)]
    assert tageszeit.lichter_waehlen(lichter, (0, 0, 0), 0) == []
    nur_nahe = tageszeit.lichter_waehlen(lichter, (0, 0, 0), 5)
    assert [l.pos[0] for l in nur_nahe] == [10.0]


def test_lichter_blenden_am_rand_der_sichtweite_aus():
    sicht = 100.0
    nah = tageszeit.lichter_waehlen([_punktlicht(10.0)], (0, 0, 0), 1, sicht)[0]
    mitte = tageszeit.lichter_waehlen([_punktlicht(80.0)], (0, 0, 0), 1, sicht)[0]
    rand = tageszeit.lichter_waehlen([_punktlicht(98.0)], (0, 0, 0), 1, sicht)[0]
    assert nah.farbe[0] == pytest.approx(100.0)
    assert 0.0 < mitte.farbe[0] < nah.farbe[0]
    assert 0.0 <= rand.farbe[0] < mitte.farbe[0]
    # stetig: ein Hauch weiter ist ein Hauch dunkler
    a = tageszeit.lichter_waehlen([_punktlicht(70.0)], (0, 0, 0), 1, sicht)[0].farbe[0]
    b = tageszeit.lichter_waehlen([_punktlicht(70.5)], (0, 0, 0), 1, sicht)[0].farbe[0]
    assert 0.0 < a - b < 3.0


def test_scheinwerfer_wirkt_vor_dem_auto():
    """Ein Kegel wird dort gemessen, wo er leuchtet — nicht an der Lampe."""
    kegel = tageszeit.Licht(pos=(0, 0, 0.7), reichweite_m=60.0, farbe=(1, 1, 1),
                            richtung=(1.0, 0.0, 0.0), innen=0.98, aussen=0.9)
    assert kegel.schwerpunkt()[0] == pytest.approx(18.0)
    assert _punktlicht(0.0).schwerpunkt()[0] == 0.0


def test_packen_fuellt_die_felder_und_laesst_den_rest_leer():
    kegel = tageszeit.Licht(pos=(1, 2, 3), reichweite_m=50.0, farbe=(4.0, 5.0, 6.0),
                            richtung=(0.0, 1.0, 0.0), innen=0.97, aussen=0.85)
    pos, farbe, richtung, n = tageszeit.lichter_packen([kegel, _punktlicht(7.0)], shader.MAX_LICHTER)
    assert n == 2
    assert pos.shape == farbe.shape == richtung.shape == (shader.MAX_LICHTER, 4)
    assert pos.dtype == np.float32
    assert tuple(pos[0]) == (1.0, 2.0, 3.0, 50.0)
    assert tuple(farbe[0]) == pytest.approx((4.0, 5.0, 6.0, 0.97))
    assert tuple(richtung[0]) == pytest.approx((0.0, 1.0, 0.0, 0.85))
    assert richtung[1][3] == tageszeit.PUNKTLICHT > 1.0, "Punktlicht hat keinen Kegel"
    assert not pos[2:].any() and not farbe[2:].any()
    # mehr Lichter als Platz: abgeschnitten, nicht überschrieben
    viele = [_punktlicht(float(i)) for i in range(40)]
    assert tageszeit.lichter_packen(viele, 8)[3] == 8


def _stand(kennung, x, y=0.0, gier=0.0, bremse=0.0, entfaerbt=False):
    return types.SimpleNamespace(kennung=kennung, pos_m=np.array([x, y, 0.0]), gierwinkel_rad=gier,
                                 bremse=bremse, entfaerbt=entfaerbt, schluessel="rookie")


def test_naechste_autos_bekommen_zwei_scheinwerfer_und_ruecklicht():
    punkte = tageszeit.Leuchtpunkte()
    staende = [_stand(i, 10.0 * i) for i in range(7)]
    lichter = tageszeit.lichter_sammeln(staende, (0.0, 0.0, 0.0), lambda s: punkte, nahe_autos=2)
    kegel = [l for l in lichter if l.richtung is not None]
    rot = [l for l in lichter if l.richtung is None]
    # zwei nahe Autos: 2 x 2 Scheinwerfer, dazu fünf ferne mit einem; Rücklicht nur bei den nahen
    assert len(kegel) == 2 * 2 + 5
    assert len(rot) == 2
    assert all(l.farbe[0] > l.farbe[2] * 10 for l in rot), "Rücklicht ist rot"


def test_geister_leuchten_nicht():
    punkte = tageszeit.Leuchtpunkte()
    lichter = tageszeit.lichter_sammeln([_stand(1, 0.0), _stand(2, 5.0, entfaerbt=True)],
                                        (0, 0, 0), lambda s: punkte)
    assert len(lichter) == 3                 # zwei Scheinwerfer und ein Rücklicht des einen Autos


def test_scheinwerfer_zeigen_in_fahrtrichtung_und_leicht_nach_unten():
    punkte = tageszeit.Leuchtpunkte(vorn=((2.0, 0.6, 0.7), (2.0, -0.6, 0.7)))
    gier = math.radians(90.0)                        # das Auto fährt nach +Y
    l = tageszeit.fahrzeug_lichter(_stand(1, 10.0, 20.0, gier), punkte, nah=True, heck=False)
    assert len(l) == 2
    for licht in l:
        assert licht.richtung[1] > 0.99 and licht.richtung[2] < 0
        assert licht.pos[1] == pytest.approx(22.0)
        assert licht.pos[2] == pytest.approx(0.7)
    xs = sorted(licht.pos[0] for licht in l)
    assert xs == pytest.approx([9.4, 10.6])          # links (+Y-Auto: -X) und rechts


def test_bremsen_verstaerkt_das_ruecklicht():
    punkte = tageszeit.Leuchtpunkte()
    frei = tageszeit.fahrzeug_lichter(_stand(1, 0.0, bremse=0.0), punkte)[-1]
    bremst = tageszeit.fahrzeug_lichter(_stand(1, 0.0, bremse=1.0), punkte)[-1]
    assert bremst.farbe[0] > 2.0 * frei.farbe[0]


# --- Leuchtpunkte aus dem Modell --------------------------------------------
def _daten(stuecke):
    """Ein Modell aus (Material, Punkte)-Paaren in einem Teil ``karosserie``."""
    namen = []
    st = []
    for name, pts in stuecke:
        if name not in namen:
            namen.append(name)
        st.append(types.SimpleNamespace(material=namen.index(name),
                                        positionen=np.asarray(pts, dtype=float)))
    teil = types.SimpleNamespace(name="karosserie", versatz=np.zeros(3), stuecke=st)
    return types.SimpleNamespace(teile=[teil],
                                 materialien=[types.SimpleNamespace(name=n) for n in namen])


def test_leuchtpunkte_aus_den_leuchtenden_netzen():
    daten = _daten([
        ("lack", [(0, 0, 0.5)]),
        ("licht_vorn", [(2.0, 0.7, 0.6), (2.0, 0.8, 0.7), (2.0, -0.7, 0.6), (2.0, -0.8, 0.7)]),
        ("licht_hinten", [(-2.1, 0.6, 0.8), (-2.1, -0.6, 0.8)]),
        ("bremslicht", [(-2.1, 0.5, 0.9), (-2.1, -0.5, 0.9)]),
    ])
    p = tageszeit.leuchtpunkte_aus_modell(daten)
    assert len(p.vorn) == 2 and len(p.hinten) == 2
    links, rechts = p.vorn
    assert links[1] == pytest.approx(0.75) and rechts[1] == pytest.approx(-0.75)
    assert links[0] == pytest.approx(2.0) and links[2] == pytest.approx(0.65)
    assert all(h[0] < -2.0 for h in p.hinten)


def test_leuchtpunkte_ohne_leuchtende_netze_nehmen_masse():
    p = tageszeit.leuchtpunkte_aus_modell(_daten([("lack", [(0, 0, 0)])]), 4.0, 2.0)
    assert p.vorn[0][0] == pytest.approx(1.84) and p.vorn[1][1] < 0 < p.vorn[0][1]
    assert p.hinten[0][0] < 0
    assert tageszeit.leuchtpunkte_aus_modell(None, 4.0, 2.0).vorn == p.vorn


def test_ein_rueckfahrlicht_im_heck_ist_kein_scheinwerfer():
    daten = _daten([("licht_vorn", [(2.0, 0.7, 0.6), (2.0, -0.7, 0.6), (-2.0, 0.2, 0.6)])])
    p = tageszeit.leuchtpunkte_aus_modell(daten)
    assert all(v[0] > 0 for v in p.vorn)


# --- Masten ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def netz_gp():
    from src.render3d import track_mesh
    with open(Path(_ROOT) / "data" / "tracks" / "gp.json", encoding="utf-8") as fh:
        return track_mesh.bauen(json.load(fh))


def test_masten_stehen_abseits_der_fahrbahn_der_ganzen_strecke(netz_gp):
    from src.render3d import track_mesh
    orte = tageszeit.mast_orte(netz_gp)
    assert len(orte) >= netz_gp.laenge_m / tageszeit.MAST_JE_M * 0.6
    fb = track_mesh.Fahrbahnabstand(netz_gp.mittellinie, netz_gp.halbe_breite_m,
                                    reichweite_m=netz_gp.halbe_breite_m + 20.0)
    abstand = fb.kante(orte[:, :2])
    assert abstand.min() >= tageszeit.MAST_FREI_M - 1e-6, "ein Mast steht an der Fahrbahn"


def test_masten_zeigen_mit_dem_arm_zur_strecke(netz_gp):
    orte = tageszeit.mast_orte(netz_gp)
    linie = np.asarray(netz_gp.mittellinie)
    for x, y, gier in orte[:12]:
        d = np.hypot(linie[:, 0] - x, linie[:, 1] - y)
        naechster = linie[int(np.argmin(d))]
        richtung = naechster - np.array([x, y])
        richtung /= np.linalg.norm(richtung)
        # der Arm zeigt grob (< 60°) zur nächsten Stelle der Mittellinie
        assert math.cos(gier) * richtung[0] + math.sin(gier) * richtung[1] > 0.5


def test_masten_stehen_nicht_auf_platzierten_objekten(netz_gp):
    frei = tageszeit.mast_orte(netz_gp)
    x, y, _ = frei[3]
    haus = types.SimpleNamespace(modell="x/haus", x=float(x), y=float(y), skala=1.0)
    mit = tageszeit.mast_orte(netz_gp, [haus], {"x/haus": {"radius_m": 5.0}})
    assert len(mit) == len(frei) - 1 or len(mit) < len(frei)
    assert not np.any(np.hypot(mit[:, 0] - x, mit[:, 1] - y) < 5.0)


def test_mastlicht_sitzt_hoch_ueber_dem_arm():
    lichter = tageszeit.mast_lichter(np.array([[10.0, 20.0, 0.0]]))
    assert len(lichter) == 1
    assert lichter[0].pos[2] == pytest.approx(tageszeit.MAST_HOEHE_M - 0.3)
    assert lichter[0].pos[0] > 10.0 + 1.0, "der Kopf hängt am Arm, nicht am Fuß"
    assert lichter[0].richtung is None


def test_mastnetz_ist_ein_geschlossenes_dreiecksnetz():
    for name, (pos, nor, idx) in tageszeit.mast_netz().items():
        assert pos.shape == nor.shape and pos.shape[1] == 3 and idx.shape[1] == 3
        assert idx.max() < len(pos), name
    pos = tageszeit.mast_netz()["mast"][0]
    assert pos[:, 2].max() == pytest.approx(tageszeit.MAST_HOEHE_M - 0.15 + 0.045, abs=0.2) \
        or pos[:, 2].max() >= tageszeit.MAST_HOEHE_M - 0.3


def test_laternen_werden_zu_punktlichtern_am_lampenkopf():
    laterne = types.SimpleNamespace(modell="city/laterne", x=100.0, y=50.0, z=1.0,
                                    gier_rad=math.pi / 2, skala=2.0)
    anderes = types.SimpleNamespace(modell="city/hydrant", x=0.0, y=0.0, z=0.0, gier_rad=0.0, skala=1.0)
    lichter = tageszeit.laternen_lichter([laterne, anderes], "city/laterne", (1.0, 0.0, 5.0))
    assert len(lichter) == 1
    # Kopf (1, 0, 5) · Skala 2, um 90° gedreht: x' = -y = 0, y' = x = 2
    assert lichter[0].pos == pytest.approx((100.0, 52.0, 11.0))


def test_birne_wird_am_material_erkannt():
    daten = _daten([("street_lamp_01", [(0, 0, 0)]), ("street_lamp_01_bulb", [(0.5, 0.0, 6.0), (0.7, 0.0, 6.0)])])
    assert tageszeit.birne_aus_modell(daten) == pytest.approx((0.6, 0.0, 6.0))
    assert tageszeit.birne_aus_modell(_daten([("lack", [(0, 0, 0)])])) is None


# ---------------------------------------------------------------------------
# Grafikstufen
# ---------------------------------------------------------------------------
def test_grafikstufen_sparen_an_lichtern():
    g = grafik.STUFEN
    assert g["niedrig"].lichter_max < g["mittel"].lichter_max < g["hoch"].lichter_max
    assert g["hoch"].lichter_max <= shader.MAX_LICHTER
    assert g["ultra"].lichter_max <= shader.MAX_LICHTER
    assert g["niedrig"].lichter_max >= 4, "auch Niedrig braucht die eigenen Scheinwerfer"


def test_lichter_max_laeuft_durchs_profil():
    werte = grafik.als_dict(grafik.STUFEN["mittel"])
    assert werte["lichter_max"] == grafik.STUFEN["mittel"].lichter_max
    alt = grafik.als_dict(grafik.STUFEN["hoch"])
    del alt["lichter_max"]                           # ein Profil von vor dieser Änderung
    try:
        assert grafik.aus_dict(alt).lichter_max == grafik.STUFEN["hoch"].lichter_max
    finally:
        grafik.aus_dict(grafik.als_dict(grafik.STUFEN["hoch"]))


# ---------------------------------------------------------------------------
# Lobby: das Feld ist optional
# ---------------------------------------------------------------------------
def _online_seite(ist_host: bool):
    from src.states.menu import online_lobby_page as olp
    from src.net import server_probe, servers
    from tests.test_layout_regeln import _ShellAttrappe
    server_probe.start = lambda: None
    server_probe.statuses = lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE, ping_ms=42.0, lobby_count=0)
        for sd in servers.all_servers()]
    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = ist_host
    seite._view = olp._LOBBY
    seite._players = [{"slot": 0, "name": "Host", "lobby_ready": False, "vehicle": "rookie"},
                      {"slot": 1, "name": "Gast", "lobby_ready": False, "vehicle": "drifter"}]
    return seite


def _lobbyzustand(einstellungen: dict) -> dict:
    return {"source": "tcp", "data": {"type": "LOBBY_STATE", "mode": "Rennen", "roster_size": 4,
                                      "players": [{"slot": 0, "name": "Host", "lobby_ready": False,
                                                   "vehicle": "rookie"},
                                                  {"slot": 1, "name": "Gast", "lobby_ready": False,
                                                   "vehicle": "drifter"}],
                                      "settings": einstellungen}}


@pytest.fixture
def aufbau_sauber(monkeypatch):
    from tests import spielhilfe
    spielhilfe.aufbau_bewahren(monkeypatch)
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()
    yield


def test_gast_ohne_feld_im_lobbyzustand_hat_tag(aufbau_sauber):
    """Ein Host mit dem Spiel von vor 1.1.0 schickt das Feld nicht."""
    seite = _online_seite(ist_host=False)
    seite._tageszeit_setzen("Nacht")
    seite._on_net(_lobbyzustand({"laps": 3}))
    assert seite._selected_tageszeit == "Tag"
    from src.core import race_setup
    assert race_setup.current().time_of_day == "Tag"


@pytest.mark.parametrize("wert", ["Abend", "Nacht"])
def test_gast_liest_die_tageszeit_des_hosts(aufbau_sauber, wert):
    seite = _online_seite(ist_host=False)
    seite._on_net(_lobbyzustand({"laps": 3, "tageszeit": wert}))
    assert seite._selected_tageszeit == wert
    from src.core import race_setup
    assert race_setup.current().time_of_day == wert


@pytest.mark.parametrize("muell", [None, "Mittag", 7, ["Nacht"], {"x": 1}])
def test_unbrauchbares_feld_wird_zu_tag(aufbau_sauber, muell):
    seite = _online_seite(ist_host=False)
    seite._on_net(_lobbyzustand({"tageszeit": muell}))
    assert seite._selected_tageszeit == "Tag"


def test_host_verteilt_die_tageszeit_in_den_einstellungen(aufbau_sauber, monkeypatch):
    seite = _online_seite(ist_host=True)
    gesendet = []
    netz = types.SimpleNamespace(send_tcp=lambda m: gesendet.append(m), slot=0, ping_ms=0)
    from src.net import session
    monkeypatch.setattr(session, "get", lambda: netz)
    seite._tageszeit_setzen("Nacht")
    seite._push_settings()
    assert gesendet[-1]["type"] == "SET_SETTINGS"
    assert gesendet[-1]["settings"]["tageszeit"] == "Nacht"
    # die bekannten Felder bleiben, wo sie waren
    assert {"mode", "laps", "track_path", "roster_size"} <= set(gesendet[-1]["settings"])


def test_server_kennt_das_feld_und_haelt_es_in_grenzen():
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    assert "tageszeit" in srv.SETTINGS_KEYS
    assert srv.TAGESZEITEN == {"Tag", "Abend", "Nacht"}


def test_rennaufbau_kennt_die_tageszeit():
    from src.core import race_setup
    assert race_setup.RaceSetup().time_of_day == "Tag"


def test_rennstart_nimmt_die_tageszeit_vom_aufrufer_oder_aus_dem_rennaufbau(monkeypatch):
    from src.core import race_setup
    from src.states.race_state import RaceState
    setup = race_setup.RaceSetup()
    monkeypatch.setattr(race_setup, "_current", setup)

    def selbst(**kwargs):
        s = object.__new__(RaceState)
        s._enter_kwargs = kwargs
        return s

    setup.time_of_day = "Nacht"
    assert selbst()._tageszeit_waehlen() == "Nacht"
    # der Aufrufer sticht den Rennaufbau (die Probefahrt im Editor fährt bei Tag)
    assert selbst(tageszeit="Tag")._tageszeit_waehlen() == "Tag"
    setup.time_of_day = "Quatsch"
    assert selbst()._tageszeit_waehlen() == "Tag"


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------
@pytest.fixture
def profil_pfad(tmp_path, monkeypatch):
    from src.core import profile
    ziel = tmp_path / "profile.json"

    def _user_path(*teile):
        return str(ziel) if teile[-1] == "profile.json" else str(tmp_path.joinpath(*teile))

    monkeypatch.setattr("src.core.paths.user_path", _user_path)
    monkeypatch.setattr(profile, "_current", None)
    yield ziel
    monkeypatch.setattr(profile, "_current", None)


def test_altes_profil_mit_tageszeit_laedt_ohne_fehler_und_verliert_das_feld(profil_pfad):
    """Seit 1.1.0 wird die Tageszeit gewürfelt und nicht mehr im Profil gemerkt."""
    from src.core import profile
    for alt in ("Nacht", "Dämmerung", 12, None):
        profil_pfad.write_text(json.dumps({"username": "Alt", "tageszeit": alt}), encoding="utf-8")
        p = profile.Profile.load()
        assert p.username == "Alt"
        assert not hasattr(p, "tageszeit") and not hasattr(p, "set_tageszeit")
    p.save()
    assert "tageszeit" not in json.loads(profil_pfad.read_text(encoding="utf-8"))


def test_einzelspieler_lobby_hat_keinen_tageszeit_stepper(profil_pfad, monkeypatch):
    from src.states.menu.lobby_page import LobbyPage
    from tests import spielhilfe
    from tests.test_layout_regeln import _ShellAttrappe
    spielhilfe.aufbau_bewahren(monkeypatch)
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()
    seite = LobbyPage()
    seite.enter(_ShellAttrappe())
    assert not hasattr(seite, "tageszeit") and not hasattr(seite, "wetter")
    assert all(getattr(w, "label", "") not in ("Tageszeit", "Wetter") for w in seite.group.widgets)


# ---------------------------------------------------------------------------
# Durch OpenGL
# ---------------------------------------------------------------------------
moderngl = pytest.importorskip("moderngl")
pytest.importorskip("trimesh")

from tests.test_render3d_zeichnen import _bild, _stand as _gl_stand, ctx, modellordner, netz  # noqa: E402,F401
from src.render3d import camera, rennszene  # noqa: E402


def _uniform(programm, name):
    return programm[name].value


def test_tag_laesst_tint_und_lichter_ungesetzt(ctx, netz, modellordner):
    szene = rennszene.Rennszene(ctx, netz, modellordner)
    staende = [_gl_stand()]
    szene.fortschreiben(staende)
    _bild(ctx, szene, staende)
    assert szene.tageszeit is TAG
    p = szene.programm
    assert tuple(_uniform(p, "tz_himmel")) == (0.0, 0.0, 0.0, 0.0)
    assert _uniform(p, "lichter_anzahl") == 0
    assert tuple(_uniform(p, "schatten_bias")) == pytest.approx((0.0006, 0.0025))
    assert szene.masten is None and szene._lampen == []
    szene.freigeben()


def test_tag_ist_der_vorgabewert_und_ein_unbekannter_name_auch(ctx, netz, modellordner):
    a = rennszene.Rennszene(ctx, netz, modellordner)
    b = rennszene.Rennszene(ctx, netz, modellordner, tageszeit="Mittag")
    assert a.tageszeit is TAG and b.tageszeit is TAG
    staende = [_gl_stand()]
    a.fortschreiben(staende)
    b.fortschreiben(staende)
    assert np.array_equal(_bild(ctx, a, staende), _bild(ctx, b, staende))
    a.freigeben()
    b.freigeben()


def test_abend_stellt_sonne_und_tint(ctx, netz, modellordner):
    szene = rennszene.Rennszene(ctx, netz, modellordner, tageszeit="Abend")
    staende = [_gl_stand()]
    szene.fortschreiben(staende)
    bild = _bild(ctx, szene, staende)
    assert bild.std() > 5.0
    p = szene.programm
    assert _hoehe_grad(tuple(_uniform(p, "sonne_richtung"))) == pytest.approx(9.0, abs=0.01)
    assert _uniform(p, "lichter_anzahl") == 0
    assert tuple(_uniform(p, "schatten_bias")) == pytest.approx(ABEND.schatten_bias)
    # Schatten und Sonne gehören zusammen: die Schattenkarte folgt der neuen Richtung
    assert np.allclose(szene.himmel.sonne, tageszeit.sonne_richtung(ABEND, szene.himmel.sonne_bild))
    assert tuple(_uniform(p, "tz_himmel")) == (1.0, 0.0, 0.0, 0.0)
    szene.freigeben()


def test_nacht_laedt_lichter_und_ist_dunkler_als_der_tag(ctx, netz, modellordner):
    helligkeit = {}
    for name in ("Tag", "Nacht"):
        szene = rennszene.Rennszene(ctx, netz, modellordner, tageszeit=name)
        staende = [_gl_stand(kennung=i, x=-6.0 * i) for i in range(3)]
        szene.fortschreiben(staende)
        helligkeit[name] = float(_bild(ctx, szene, staende).mean())
        if name == "Nacht":
            p = szene.programm
            n = _uniform(p, "lichter_anzahl")
            assert 3 <= n <= grafik.aktuell().lichter_max
            pos = np.frombuffer(p["lichter_pos"].read(), dtype="f4").reshape(-1, 4)
            assert (pos[:n, 3] > 0).all(), "jedes gewählte Licht hat eine Reichweite"
        szene.freigeben()
    assert helligkeit["Nacht"] < helligkeit["Tag"]


def test_ohne_lichterbudget_leuchten_nachts_nur_die_materialien(ctx, netz, modellordner):
    alt = grafik.aktuell()
    try:
        grafik.setzen(lichter_max=0)
        szene = rennszene.Rennszene(ctx, netz, modellordner, tageszeit="Nacht")
        staende = [_gl_stand()]
        szene.fortschreiben(staende)
        _bild(ctx, szene, staende)
        assert _uniform(szene.programm, "lichter_anzahl") == 0
        szene.freigeben()
    finally:
        grafik.aus_dict(grafik.als_dict(alt))


def test_nacht_ohne_laternen_stellt_masten_auf(ctx, netz, modellordner):
    szene = rennszene.Rennszene(ctx, netz, modellordner, tageszeit="Nacht")
    # der Teststrecke fehlen Thema und Umgebung: keine Laternen, also Masten
    assert szene.masten is not None and len(szene._lampen) == len(szene.masten.orte)
    staende = [_gl_stand()]
    szene.fortschreiben(staende)
    _bild(ctx, szene, staende)
    szene.freigeben()
    assert szene.masten is None
