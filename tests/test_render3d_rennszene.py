"""Die Rennszene, soweit sie ohne Grafikkarte prüfbar ist.

Was einen OpenGL-Kontext braucht — Puffer, Texturen, Zeichnen — steht hier
nicht. Geprüft wird, was danebenliegt und trotzdem falsch sein kann: welche
Datei zu welchem Fahrzeugschlüssel gehört, dass jedes Fahrzeug seinen eigenen
Radzustand behält, und wie groß der Schattenfleck ausfällt.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.render3d import rennszene, schatten


# ---------------------------------------------------------------------------
# Welches Modell gehört zu welchem Schlüssel
# ---------------------------------------------------------------------------

def _glb_anlegen(ordner, *namen):
    ordner.mkdir(parents=True, exist_ok=True)
    for name in namen:
        (ordner / f"{name}.glb").write_bytes(b"glTF")


def test_modelldatei_nimmt_den_eigenen_schluessel(tmp_path):
    _glb_anlegen(tmp_path, "rookie", "limousine")
    pfad, schluessel = rennszene.modelldatei(tmp_path, "limousine")
    assert pfad.name == "limousine.glb"
    assert schluessel == "limousine"


def test_modelldatei_faellt_auf_den_ersatz_zurueck(tmp_path):
    """Acht Fahrzeuge, aber erst ein Modell im Repo.

    Der Rückfall ist Absicht und kein Notnagel: kommt ``limousine.glb`` dazu,
    greift sie ohne Codeänderung.
    """
    _glb_anlegen(tmp_path, "rookie")
    pfad, schluessel = rennszene.modelldatei(tmp_path, "limousine")
    assert pfad.name == "rookie.glb"
    assert schluessel == "rookie"


def test_modelldatei_ohne_jedes_modell(tmp_path):
    assert rennszene.modelldatei(tmp_path, "limousine") == (None, "")


def test_teiledatei_folgt_dem_ersetzten_schluessel(tmp_path):
    """Wird rookie statt limousine geladen, gehören auch rookies Radplätze dazu.

    Sonst säßen die Naben der Limousine an einem Rookie-Netz — die Räder
    stünden neben dem Auto.
    """
    _glb_anlegen(tmp_path, "rookie")
    (tmp_path / "rookie_teile.json").write_text(json.dumps({
        "laenge_m": 4.32, "breite_m": 2.08, "raddurchmesser_m": 0.65,
        "gelenkt": ["rad_vl"],
        "raeder": [{"name": "rad_vl", "nabe": [1.2, 0.76, 0.33]}],
    }), encoding="utf-8")
    _pfad, schluessel = rennszene.modelldatei(tmp_path, "limousine")
    daten = rennszene.teile_laden(tmp_path, schluessel)
    assert daten is not None
    assert daten.laenge_m == pytest.approx(4.32)
    assert [p.name for p in daten.plaetze] == ["rad_vl"]


# ---------------------------------------------------------------------------
# Radzustand je Fahrzeug
# ---------------------------------------------------------------------------

class _Knotenattrappe:
    def __init__(self) -> None:
        self.weg_m = 0.0
        self.lenkwinkel_rad = 0.0

    def weg_zuruecklegen(self, weg_m):
        self.weg_m += weg_m

    def lenken(self, winkel_rad):
        self.lenkwinkel_rad = winkel_rad

    def neigen(self, nick_rad=0.0, wank_rad=0.0):
        self.neigung = (nick_rad, wank_rad)


def _stand(kennung, weg_m=0.0, lenkwinkel_rad=0.0):
    return rennszene.Fahrzeugstand(
        kennung=kennung, schluessel="rookie", pos_m=np.zeros(3),
        gierwinkel_rad=0.0, weg_m=weg_m, lenkwinkel_rad=lenkwinkel_rad)


def test_jedes_fahrzeug_behaelt_seinen_eigenen_radzustand():
    """Der Rollwinkel wächst mit dem gefahrenen Weg — er ist Zustand.

    Ein Knoten je Bild neu gebaut setzte ihn jedes Mal auf null zurück, und
    die Räder stünden bei voller Fahrt still.
    """
    speicher = rennszene.Knotenspeicher(lambda schluessel: _Knotenattrappe())
    speicher.fortschreiben([_stand(1, weg_m=2.0), _stand(2, weg_m=5.0)])
    speicher.fortschreiben([_stand(1, weg_m=3.0), _stand(2, weg_m=1.0)])
    assert speicher.knoten(1).weg_m == pytest.approx(5.0)
    assert speicher.knoten(2).weg_m == pytest.approx(6.0)


def test_lenkwinkel_wird_gesetzt_nicht_aufaddiert():
    speicher = rennszene.Knotenspeicher(lambda schluessel: _Knotenattrappe())
    speicher.fortschreiben([_stand(1, lenkwinkel_rad=0.3)])
    speicher.fortschreiben([_stand(1, lenkwinkel_rad=0.1)])
    assert speicher.knoten(1).lenkwinkel_rad == pytest.approx(0.1)


def test_verschwundene_fahrzeuge_werden_vergessen():
    """Sonst wächst der Speicher über ein Grand-Prix-Wochenende mit."""
    speicher = rennszene.Knotenspeicher(lambda schluessel: _Knotenattrappe())
    speicher.fortschreiben([_stand(1), _stand(2)])
    speicher.fortschreiben([_stand(2)])
    assert speicher.knoten(1) is None
    assert speicher.knoten(2) is not None


def test_knoten_ohne_teiledatei_stoert_nicht():
    """Ein Fahrzeug ohne ``_teile.json`` hat keine trennbaren Räder. Das darf
    das Bild kosten, aber keinen Absturz."""
    speicher = rennszene.Knotenspeicher(lambda schluessel: None)
    speicher.fortschreiben([_stand(1, weg_m=2.0)])
    assert speicher.knoten(1) is None


# ---------------------------------------------------------------------------
# Schattenfleck
# ---------------------------------------------------------------------------

def test_schattenflaeche_umschliesst_das_fahrzeug():
    ecken = schatten.grundflaeche(4.32, 2.08)
    x, y = ecken[:, 0], ecken[:, 1]
    assert x.max() - x.min() == pytest.approx(4.32 * schatten.UEBERSTAND)
    assert y.max() - y.min() == pytest.approx(2.08 * schatten.UEBERSTAND)


def test_schattenflaeche_liegt_knapp_ueber_der_fahrbahn():
    """Genau auf z = 0 kämpfte sie mit der Fahrbahn um die Tiefe und flackerte."""
    ecken = schatten.grundflaeche(4.32, 2.08)
    assert np.allclose(ecken[:, 2], schatten.HOEHE_M)
    assert 0.0 < schatten.HOEHE_M < 0.1


def test_schattenflaeche_ist_mittig():
    ecken = schatten.grundflaeche(4.0, 2.0)
    assert ecken[:, 0].mean() == pytest.approx(0.0)
    assert ecken[:, 1].mean() == pytest.approx(0.0)
