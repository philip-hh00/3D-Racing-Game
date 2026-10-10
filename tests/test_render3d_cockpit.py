"""Cockpit-Knoten (1.1.0): Lenkrad und Nadeln drehen, alte Modelle bleiben gültig.

Die echten GLBs bringen die Knoten ``lenkrad``, ``nadel_tacho`` und
``nadel_drehzahl`` erst mit dem Cockpit-Umbau mit. Diese Tests arbeiten mit
einem erfundenen Satz Knoten — Vertrag siehe ``src/render3d/VEREINBARUNGEN.md``.
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

from src.render3d import matrix, rennszene, vehicle_node  # noqa: E402
from src.render3d.vehicle_node import Cockpitmasse, Fahrzeugknoten, Radplatz  # noqa: E402

LENKRAD = np.array([0.35, 0.36, 0.95])
TACHO = np.array([0.40, 0.45, 0.98])
DREHZAHL = np.array([0.40, 0.25, 0.98])
SPIEGEL = np.array([0.20, 0.0, 1.25])

COCKPIT = Cockpitmasse(
    augpunkt=np.array([-0.1, 0.35, 1.2]), haube=np.array([1.2, 0.0, 1.1]),
    lenkrad_uebersetzung=12.0,
    tacho_max_kmh=320.0, tacho_winkel_grad=(-135.0, 135.0),
    drehzahl_max=9000.0, drehzahl_winkel_grad=(-120.0, 100.0))


def _raeder():
    return [Radplatz("rad_vl", np.array([1.3, 0.8, 0.33]), True),
            Radplatz("rad_vr", np.array([1.3, -0.8, 0.33]), True),
            Radplatz("rad_hl", np.array([-1.3, 0.8, 0.33]), False),
            Radplatz("rad_hr", np.array([-1.3, -0.8, 0.33]), False)]


def _knoten(cockpit=COCKPIT, **kw):
    anbau = {"lenkrad": LENKRAD, "nadel_tacho": TACHO, "nadel_drehzahl": DREHZAHL,
             "spiegel_innen": SPIEGEL}
    return Fahrzeugknoten(_raeder(), 0.66, cockpit=cockpit, anbauteile=anbau, **kw)


def _winkel_um_x(m: np.ndarray, ursprung: np.ndarray) -> float:
    """Drehwinkel der Matrix ``m`` um die X-Achse, wenn der Knoten bei ``ursprung`` sitzt."""
    rot = m[:3, :3]
    assert np.allclose(m[:3, 3], ursprung, atol=1e-5), "der Ursprung darf nicht wandern"
    assert np.allclose(rot @ [1, 0, 0], [1, 0, 0], atol=1e-5), "gedreht wird um X"
    return math.atan2(rot[2, 1], rot[1, 1])


# ---------------------------------------------------------------------------
# Rechnung
# ---------------------------------------------------------------------------

def test_nadel_zeigt_am_anfang_den_anfangswinkel_und_am_ende_den_endwinkel():
    assert vehicle_node.nadelwinkel(0.0, 320.0, (-135.0, 135.0)) == pytest.approx(math.radians(-135))
    assert vehicle_node.nadelwinkel(320.0, 320.0, (-135.0, 135.0)) == pytest.approx(math.radians(135))
    assert vehicle_node.nadelwinkel(160.0, 320.0, (-135.0, 135.0)) == pytest.approx(0.0)


def test_nadel_schlaegt_nicht_ueber_den_anschlag():
    assert vehicle_node.nadelwinkel(900.0, 320.0, (-135.0, 135.0)) == pytest.approx(math.radians(135))
    assert vehicle_node.nadelwinkel(-5.0, 320.0, (-135.0, 135.0)) == pytest.approx(math.radians(-135))
    assert vehicle_node.nadelwinkel(10.0, 0.0, (-135.0, 135.0)) == pytest.approx(math.radians(-135))


def test_lenkrad_dreht_mit_der_uebersetzung():
    # 5 Grad Radeinschlag links, Übersetzung 12 -> 60 Grad am Lenkrad.
    w = vehicle_node.lenkradwinkel(math.radians(5.0), 12.0)
    assert w == pytest.approx(math.radians(60.0))
    assert vehicle_node.lenkradwinkel(-math.radians(5.0), 12.0) == pytest.approx(-math.radians(60.0))
    assert vehicle_node.lenkradwinkel(0.0, 12.0) == 0.0


def _lenkrad_achsen(neigung_grad: float = 22.0) -> np.ndarray:
    """Ausrichtung des Lenkrad-Knotens wie im Generator: +X zeigt zum Fahrer hin (nach hinten oben)."""
    w = math.radians(neigung_grad)
    x = np.array([-math.cos(w), 0.0, math.sin(w)])       # Säulenachse zum Fahrer
    z = np.array([0.0, 0.0, 1.0]) - x * x[2]
    z /= np.linalg.norm(z)                               # "oben" am Rad
    y = np.cross(z, x)
    return np.column_stack([x, y, z])


@pytest.mark.parametrize("neigung", [0.0, 22.0])
def test_lenkrad_dreht_beim_lenken_nach_links_oben_nach_links(neigung):
    """Links lenken: der Kranz oben wandert nach links (+Y), unten nach rechts; rechts umgekehrt."""
    achsen = _lenkrad_achsen(neigung)
    oben = achsen[:, 2] * 0.17                           # Punkt oben am Kranz, relativ zum Ursprung
    k = _knoten(achsen={"lenkrad": achsen})
    k.lenken(math.radians(5.0))                          # links
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    neu = (m @ np.append(oben, 1.0))[:3] - LENKRAD
    assert neu[1] > 0.02, "links lenken: oben am Kranz geht nach links (+Y)"
    unten = (m @ np.append(-oben, 1.0))[:3] - LENKRAD
    assert unten[1] < -0.02
    k.lenken(-math.radians(5.0))                         # rechts
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    neu = (m @ np.append(oben, 1.0))[:3] - LENKRAD
    assert neu[1] < -0.02


# ---------------------------------------------------------------------------
# Matrizen mit erfundenen Knoten
# ---------------------------------------------------------------------------

def test_zusatzknoten_stehen_in_den_matrizen_und_sitzen_am_aufbau():
    k = _knoten()
    m = k.matrizen((3.0, 4.0, 0.0), 0.7)
    assert {"karosserie", "lenkrad", "nadel_tacho", "nadel_drehzahl", "spiegel_innen"} <= set(m)
    basis = matrix.fahrzeug((3.0, 4.0, 0.0), 0.7)
    # Spiegel starr: Fahrzeug · Ursprung des Knotens
    np.testing.assert_allclose(m["spiegel_innen"], basis @ matrix.verschiebung(SPIEGEL), atol=1e-5)


def test_zusatzknoten_neigen_sich_mit_dem_aufbau():
    k = _knoten()
    k.neigen(0.04, 0.06)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)
    erwartet = k.aufbau_matrix() @ matrix.verschiebung(SPIEGEL)
    np.testing.assert_allclose(m["spiegel_innen"], erwartet, atol=1e-5)
    np.testing.assert_allclose(m["karosserie"], k.aufbau_matrix(), atol=1e-5)


def test_lenkrad_dreht_um_die_lokale_x_achse_durch_seinen_ursprung():
    k = _knoten()
    k.lenken(math.radians(3.0))
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    assert _winkel_um_x(m, LENKRAD) == pytest.approx(
        vehicle_node.lenkradwinkel(math.radians(3.0), 12.0), abs=1e-5)


def test_lenkrad_steht_gerade_ohne_lenkeinschlag():
    k = _knoten()
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    np.testing.assert_allclose(m, matrix.verschiebung(LENKRAD), atol=1e-6)


def test_lenkrad_folgt_dem_wechsel_des_einschlags_und_nimmt_nichts_mit():
    k = _knoten()
    k.lenken(0.2)
    k.lenken(0.0)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    np.testing.assert_allclose(m, matrix.verschiebung(LENKRAD), atol=1e-6)


def test_lenkrad_nutzt_die_uebersetzung_aus_teile_json():
    eng = Cockpitmasse(augpunkt=COCKPIT.augpunkt, haube=COCKPIT.haube, lenkrad_uebersetzung=6.0)
    k = _knoten(cockpit=eng)
    k.lenken(0.1)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["lenkrad"]
    assert abs(_winkel_um_x(m, LENKRAD)) == pytest.approx(0.6, abs=1e-5)


@pytest.mark.parametrize("kmh, erwartet_grad", [(0.0, -135.0), (160.0, 0.0), (320.0, 135.0), (999.0, 135.0)])
def test_tachonadel_folgt_dem_tempo(kmh, erwartet_grad):
    k = _knoten()
    k.instrumente(tempo_kmh=kmh)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["nadel_tacho"]
    assert _winkel_um_x(m, TACHO) == pytest.approx(math.radians(erwartet_grad), abs=1e-5)


def test_rueckwaerts_zeigt_der_tacho_den_betrag():
    k = _knoten()
    k.instrumente(tempo_kmh=-160.0)
    assert k.tempo_kmh == 160.0


@pytest.mark.parametrize("u_min, erwartet_grad", [(0.0, -120.0), (4500.0, -10.0), (9000.0, 100.0)])
def test_drehzahlnadel_nutzt_ihre_eigene_skala(u_min, erwartet_grad):
    k = _knoten()
    k.instrumente(drehzahl=u_min)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)["nadel_drehzahl"]
    assert _winkel_um_x(m, DREHZAHL) == pytest.approx(math.radians(erwartet_grad), abs=1e-5)


def test_ohne_cockpitdaten_sitzen_alle_zusatzknoten_starr():
    k = _knoten(cockpit=None)
    k.lenken(0.3)
    k.instrumente(200.0, 5000.0)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)
    np.testing.assert_allclose(m["lenkrad"], matrix.verschiebung(LENKRAD), atol=1e-6)
    np.testing.assert_allclose(m["nadel_tacho"], matrix.verschiebung(TACHO), atol=1e-6)


def test_altes_modell_ohne_zusatzknoten_liefert_wie_bisher_nur_karosserie_raeder_saettel():
    k = Fahrzeugknoten(_raeder(), 0.66)
    k.lenken(0.2)
    k.instrumente(100.0, 3000.0)       # darf nichts bewirken und nichts werfen
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)
    assert set(m) == {"karosserie", *(r.name for r in _raeder()),
                      *(r.sattel for r in _raeder())}


def test_raeder_und_karosserie_werden_nicht_als_anbauteil_doppelt_gefuehrt():
    k = Fahrzeugknoten(_raeder(), 0.66, cockpit=COCKPIT,
                       anbauteile={"karosserie": [0, 0, 0], "rad_vl": [1, 1, 1],
                                   "sattel_vl": [1, 1, 1], "lenkrad": LENKRAD})
    assert set(k.anbauteile) == {"lenkrad"}


def test_fehlt_ein_knoten_wird_nur_der_vorhandene_bewegt():
    k = Fahrzeugknoten(_raeder(), 0.66, cockpit=COCKPIT, anbauteile={"nadel_tacho": TACHO})
    k.lenken(0.1)
    k.instrumente(320.0, 9000.0)
    m = k.matrizen((0.0, 0.0, 0.0), 0.0)
    assert "lenkrad" not in m and "nadel_drehzahl" not in m
    assert _winkel_um_x(m["nadel_tacho"], TACHO) == pytest.approx(math.radians(135), abs=1e-5)


# ---------------------------------------------------------------------------
# teile.json
# ---------------------------------------------------------------------------

def test_cockpitblock_wird_gelesen():
    daten = {"laenge_m": 4.3, "breite_m": 2.0, "hoehe_m": 1.5,
             "cockpit": {"augpunkt": [0.1, 0.4, 1.15], "haube": [1.0, 0.0, 1.05],
                         "lenkrad_uebersetzung": 14.0,
                         "tacho_max_kmh": 280, "tacho_winkel_grad": [-120, 120],
                         "drehzahl_max": 8000, "drehzahl_winkel_grad": [-100, 110]}}
    c = vehicle_node.cockpit_lesen(daten)
    np.testing.assert_allclose(c.augpunkt, [0.1, 0.4, 1.15])
    np.testing.assert_allclose(c.haube, [1.0, 0.0, 1.05])
    assert c.lenkrad_uebersetzung == 14.0
    assert (c.tacho_max_kmh, c.tacho_winkel_grad) == (280.0, (-120.0, 120.0))
    assert (c.drehzahl_max, c.drehzahl_winkel_grad) == (8000.0, (-100.0, 110.0))
    assert c.aus_datei


def test_ohne_block_wird_aus_den_massen_geschaetzt():
    c = vehicle_node.cockpit_lesen({"laenge_m": 4.32, "breite_m": 2.08, "hoehe_m": 1.5})
    assert not c.aus_datei
    # Linkslenker: der Fahrer sitzt links (+Y), unter dem Dach, hinter der Haubenkamera.
    assert 0.0 < c.augpunkt[1] < 0.6
    assert 0.8 < c.augpunkt[2] < 1.5
    assert c.augpunkt[0] < c.haube[0]
    assert c.haube[0] > 0.5 and c.haube[1] == 0.0
    assert c.lenkrad_uebersetzung == vehicle_node.LENKRAD_UEBERSETZUNG


def test_kaputte_angaben_im_block_fallen_auf_die_schaetzung_zurueck():
    daten = {"laenge_m": 4.3, "breite_m": 2.0, "hoehe_m": 1.4,
             "cockpit": {"augpunkt": [1, 2], "haube": "x", "tacho_max_kmh": -4,
                         "tacho_winkel_grad": 5, "lenkrad_uebersetzung": "viel"}}
    c = vehicle_node.cockpit_lesen(daten)
    schaetzung = vehicle_node.cockpit_aus_masse(4.3, 2.0, 1.4)
    np.testing.assert_allclose(c.augpunkt, schaetzung.augpunkt)
    np.testing.assert_allclose(c.haube, schaetzung.haube)
    assert c.tacho_max_kmh == vehicle_node.TACHO_MAX_KMH
    assert c.tacho_winkel_grad == vehicle_node.TACHO_WINKEL_GRAD
    assert c.lenkrad_uebersetzung == vehicle_node.LENKRAD_UEBERSETZUNG


def test_schaetzung_fuer_flache_und_hohe_wagen_bleibt_unter_dem_dach():
    for hoehe in (1.15, 1.3, 1.5):
        c = vehicle_node.cockpit_aus_masse(4.5, 2.0, hoehe)
        assert c.augpunkt[2] < hoehe - 0.2


def test_cockpit_aus_datei_fehlend_oder_kaputt(tmp_path):
    assert vehicle_node.cockpit_aus_datei(tmp_path / "gibt_es_nicht.json") is None
    (tmp_path / "kaputt.json").write_text("{", encoding="utf-8")
    assert vehicle_node.cockpit_aus_datei(tmp_path / "kaputt.json") is None


def test_die_mitgelieferten_teile_dateien_geben_ein_brauchbares_cockpit():
    wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ordner = os.path.join(wurzel, "assets", "vehicles")
    for schluessel in ("rookie", "supercar", "limousine", "drifter", "electric"):
        c = vehicle_node.cockpit_aus_datei(os.path.join(ordner, f"{schluessel}_teile.json"))
        assert c is not None
        assert c.augpunkt[2] > 0.5 and 0.0 < c.augpunkt[1] < 1.0


def test_teile_laden_bringt_das_cockpit_mit(tmp_path):
    teile = {"fahrzeug": "test", "laenge_m": 4.0, "breite_m": 2.0, "hoehe_m": 1.4,
             "raddurchmesser_m": 0.65, "gelenkt": ["rad_vl"],
             "raeder": [{"name": "rad_vl", "nabe": [1.2, 0.8, 0.33]}],
             "cockpit": {"augpunkt": [0.0, 0.3, 1.1], "haube": [1.0, 0.0, 1.0]}}
    (tmp_path / "test_teile.json").write_text(json.dumps(teile), encoding="utf-8")
    t = rennszene.teile_laden(tmp_path, "test")
    np.testing.assert_allclose(t.cockpit.augpunkt, [0.0, 0.3, 1.1])


# ---------------------------------------------------------------------------
# Anbindung an die Szene
# ---------------------------------------------------------------------------

def _modell(*namen):
    teile = [SimpleNamespace(name=n, versatz=np.array(v, dtype=np.float32)) for n, v in namen]
    return SimpleNamespace(teile=teile)


def test_fahrzeugmodell_reicht_die_zusatzknoten_mit_ursprung_an_den_knoten_weiter():
    plaetze = _raeder()
    teile = rennszene.Teiledaten(plaetze=plaetze, raddurchmesser_m=0.66, laenge_m=4.3,
                                 breite_m=2.0, cockpit=COCKPIT)
    modell = _modell(("karosserie", (0, 0, 0)), ("rad_vl", (1.3, 0.8, 0.33)),
                     ("lenkrad", LENKRAD), ("nadel_tacho", TACHO))
    fm = rennszene.Fahrzeugmodell("test", modell, teile)
    k = fm.knoten()
    assert set(k.anbauteile) == {"lenkrad", "nadel_tacho"}
    np.testing.assert_allclose(k.anbauteile["lenkrad"], LENKRAD, atol=1e-6)
    assert k.cockpit is COCKPIT


def test_der_knotenspeicher_gibt_tempo_und_drehzahl_an_die_nadeln():
    speicher = rennszene.Knotenspeicher(lambda schluessel: _knoten())
    stand = rennszene.Fahrzeugstand(kennung=1, schluessel="x", pos_m=np.zeros(3),
                                    gierwinkel_rad=0.0, lenkwinkel_rad=0.1,
                                    tempo_kmh=210.0, drehzahl=6500.0)
    speicher.fortschreiben([stand])
    k = speicher.knoten(1)
    assert (k.tempo_kmh, k.drehzahl, k.lenkwinkel_rad) == (210.0, 6500.0, 0.1)


def test_lenkrad_dreht_um_die_geneigte_lenksaeule_nicht_um_die_laengsachse():
    """Der Lader rechnet die Knotendrehung in die Punkte; gedreht werden muss
    trotzdem um die lokale X-Achse des Knotens (die um 22° geneigte Saeule)."""
    import numpy as np
    from src.render3d import vehicle_node as vn
    neigung = np.radians(22.0)
    # Lokale X-Achse zeigt nach hinten-oben (zum Fahrer), wie im Blender-Bau.
    c, s = np.cos(neigung), np.sin(neigung)
    r = np.array([[-c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, -c]])   # Spalten: lokale Achsen
    assert abs(np.linalg.det(r) - 1.0) < 1e-9
    cockpit = vn.Cockpitmasse(augpunkt=np.array([0.0, 0.4, 1.1]), haube=np.array([1.0, 0.0, 1.2]),
                              lenkrad_uebersetzung=12.0)
    knoten = vn.Fahrzeugknoten([], 0.6, cockpit=cockpit,
                               anbauteile={"lenkrad": np.zeros(3)},
                               achsen={"lenkrad": r})
    knoten.lenkwinkel_rad = np.radians(10.0)
    m = knoten.anbauteil_matrix("lenkrad", np.zeros(3))[:3, :3]
    saeule = r[:, 0]
    assert np.allclose(m @ saeule, saeule, atol=1e-9)        # Achse bleibt stehen
    assert not np.allclose(m @ np.array([1.0, 0.0, 0.0]), [1.0, 0.0, 0.0])
