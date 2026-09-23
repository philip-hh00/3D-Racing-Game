"""Umgebung um die Strecke: Themen lesen, Objekte platzieren.

Die Platzierung ist reine Rechnung. Geprüft wird, was man im Spiel sofort
sähe, wenn es schiefginge: Bäume auf der Fahrbahn, bei jedem Rennen ein
anderer Wald, ein Thema, das auf ein Modell zeigt, das es nicht gibt.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from src.render3d import platzierung, thema, track_mesh

WURZEL = Path(__file__).resolve().parents[1]
THEMEN = WURZEL / "data" / "themen"
STRECKEN = ["oval", "city", "desert", "gp", "mountain"]


def _kreis(radius_px=1200.0, breite_px=250.0, n=240):
    w = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return {"name": "Kreis", "track_width": breite_px, "background_texture": "Forest",
            "centerline": [{"x": radius_px * math.cos(a), "y": radius_px * math.sin(a)} for a in w]}


def _netz(strecke):
    return track_mesh.bauen(strecke)


def test_jede_strecke_hat_ein_thema_mit_datei():
    for name in STRECKEN:
        daten = json.loads((WURZEL / "data" / "tracks" / f"{name}.json").read_text(encoding="utf-8"))
        schluessel = thema.thema_der_strecke(daten).lower()
        assert (THEMEN / f"{schluessel}.json").is_file(), name


def test_unbekanntes_thema_faellt_auf_das_ersatzthema_zurueck():
    t = thema.laden(THEMEN, "GibtsNicht")
    assert t.name == thema.ERSATZTHEMA


def test_gross_und_kleinschreibung_egal():
    assert thema.laden(THEMEN, "DESERT").name == "Desert"


def test_platzierung_ist_je_strecke_fest():
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    a = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    b = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    assert [(p.modell, p.x, p.y) for p in a] == [(p.modell, p.x, p.y) for p in b]


def test_andere_strecke_andere_anordnung():
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    a = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    b = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Anderer Kreis")
    assert [(p.x, p.y) for p in a[:50]] != [(p.x, p.y) for p in b[:50]]


def test_nichts_steht_auf_der_fahrbahn():
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    assert len(orte) > 100
    xy = np.array([[p.x, p.y] for p in orte if p.modell != platzierung.STARTBRUECKE])
    abstand = platzierung.abstand_zur_linie(xy, netz.mittellinie)
    assert abstand.min() > netz.halbe_breite_m + 1.0


def test_objekte_ueberlappen_sich_nicht():
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    radien = {a.modell: a.radius_m for a in t.deko}
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    baeume = [p for p in orte if "tanne" in p.modell]
    xy = np.array([[p.x, p.y] for p in baeume])
    d = np.linalg.norm(xy[:, None] - xy[None], axis=2) + np.eye(len(xy)) * 1e9
    r = next(v for k, v in radien.items() if "tanne" in k)
    assert d.min() >= 2 * r * 0.8 * 0.99


def test_banden_schauen_zur_strecke():
    """Lokales +Y zeigt zur Strecke — dort ist die Werbefläche."""
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    orte = [p for p in platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
            if "bande" in p.modell]
    assert orte
    for p in orte:
        vorn = np.array([-math.sin(p.gier_rad), math.cos(p.gier_rad)])
        zur_mitte = -np.array([p.x, p.y]) / math.hypot(p.x, p.y)
        # Außen am Kreis: die Strecke liegt Richtung Kreismitte.
        assert vorn @ zur_mitte > 0.9


def test_innenfeld_wird_erkannt():
    quadrat = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)
    assert platzierung.innerhalb(np.array([[5, 5], [15, 5]]), quadrat).tolist() == [True, False]


@pytest.mark.parametrize("name", ["city", "desert", "forest", "mountain", "plains"])
def test_themen_zeigen_nur_auf_vorhandene_modelle(name):
    katalog_pfad = WURZEL / "assets" / "umgebung" / "katalog.json"
    if not katalog_pfad.is_file():
        pytest.skip("Umgebung noch nicht mit tools/blender/umgebung_bauen.py erzeugt")
    katalog = json.loads(katalog_pfad.read_text(encoding="utf-8"))
    t = thema.laden(THEMEN, name)
    fehlend = [m for m in t.modelle() if m not in katalog]
    assert not fehlend, fehlend


def test_startbruecke_steht_quer_ueber_der_ziellinie():
    netz = _netz(_kreis())
    t = thema.laden(THEMEN, "Forest")
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, "Kreis")
    bruecken = [p for p in orte if p.modell == platzierung.STARTBRUECKE]
    assert len(bruecken) == 1
    b = bruecken[0]
    assert (b.x, b.y) == pytest.approx(tuple(netz.mittellinie[0]), abs=1e-6)
    quer = np.array([math.cos(b.gier_rad), math.sin(b.gier_rad)])
    richtung = netz.mittellinie[1] - netz.mittellinie[0]
    assert abs(quer @ richtung / np.linalg.norm(richtung)) < 0.05
