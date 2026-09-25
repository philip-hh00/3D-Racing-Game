"""Gelände um die Strecke: flacher Korridor, festes Höhenfeld, dichtes Netz, Gras.

Geprüft wird, was man im Spiel sofort sähe, wenn es schiefginge: eine Stufe
zwischen Fahrbahn und Gelände, ein Loch im Boden, Bäume, die über dem Hang
schweben, Gras auf dem Randstein, bei jedem Rennen andere Hügel.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from src.render3d import gelaende, platzierung, thema, track_mesh

WURZEL = Path(__file__).resolve().parents[1]
THEMEN = WURZEL / "data" / "themen"
STRECKEN = ["oval", "city", "desert", "gp", "mountain"]


def _strecke(name):
    daten = json.loads((WURZEL / "data" / "tracks" / f"{name}.json").read_text(encoding="utf-8"))
    netz = track_mesh.bauen(daten)
    th = thema.laden(THEMEN, thema.thema_der_strecke(daten))
    return netz, th


def _gelaende(netz, th, detail=0, name=None):
    return gelaende.Gelaende(netz.mittellinie, netz.halbe_breite_m, th.gelaende,
                             name or netz.name, rand_arten=th.rand,
                             auslauf_m=getattr(getattr(th, "auslauf", None), "breite_m", 0.0),
                             detail=detail)


def _randpunkte(netz, abstaende):
    """Punkte neben der Fahrbahnkante, links und rechts, in den gegebenen Abständen."""
    linie = np.asarray(netz.mittellinie)
    links = np.asarray(netz.links)
    punkte = []
    for a in abstaende:
        for seite in (1.0, -1.0):
            punkte.append(linie + seite * links * (netz.halbe_breite_m + a))
    return np.concatenate(punkte)


@pytest.fixture(scope="module")
def berg():
    netz, th = _strecke("mountain")
    gel = _gelaende(netz, th, detail=0)
    return netz, th, gel


def test_jedes_thema_hat_ein_gelaende():
    arten = {thema.laden(THEMEN, n).gelaende.nah_art for n in
             ("city", "desert", "forest", "mountain", "plains")}
    assert {"flach", "duenen", "huegel", "berge", "wellen"} <= arten
    assert thema.laden(THEMEN, "desert").gelaende.fern_art == "tafelberge"
    assert thema.laden(THEMEN, "mountain").gelaende.schnee_ab_m is not None


def test_gras_ist_je_thema_schaltbar():
    assert not thema.laden(THEMEN, "city").gras.an
    assert thema.laden(THEMEN, "desert").gras.trocken
    assert thema.laden(THEMEN, "forest").gras.an


@pytest.mark.parametrize("name", STRECKEN)
def test_im_korridor_ist_das_gelaende_genau_flach(name):
    netz, th = _strecke(name)
    gel = _gelaende(netz, th)
    innen = gel.korridor - 1.0
    punkte = _randpunkte(netz, np.linspace(-netz.halbe_breite_m, innen, 6))
    # Die Fläche selbst ist bis an den Rand des Korridors genau 0.
    assert np.abs(gel.feld(punkte[:, 0], punkte[:, 1])).max() == 0.0
    # Das Netz auch — nur in der letzten Gitterzelle vor dem Anstieg holt die
    # Nachbarecke draußen ein paar Zentimeter herein.
    zelle = gelaende.DETAIL[0]["fein_m"] * 1.5
    sicher = _randpunkte(netz, np.linspace(-netz.halbe_breite_m, gel.korridor - zelle, 6))
    assert np.abs(gel.hoehe(sicher[:, 0], sicher[:, 1])).max() == 0.0
    assert np.abs(gel.hoehe(punkte[:, 0], punkte[:, 1])).max() < 0.1


def test_das_gelaende_steigt_hinter_dem_korridor_weich_an(berg):
    netz, _th, gel = berg
    abstaende = np.linspace(gel.korridor, gel.korridor + 4.0, 5)
    punkte = _randpunkte(netz, abstaende).reshape(len(abstaende), -1, 2)
    h = np.stack([gel.feld(p[:, 0], p[:, 1]) for p in punkte])
    # Direkt am Korridor praktisch null, dann langsam mehr — keine Stufe.
    assert np.abs(h[0]).max() < 1e-3
    assert np.abs(h[1]).max() < 0.05
    assert np.abs(h[-1]).max() > 0.0


def test_hinter_dem_korridor_ist_es_huegelig(berg):
    _netz, _th, gel = berg
    xs, ys, z = gel._gitter_bauen()
    assert z.max() > 30.0


def test_das_gelaende_ist_je_strecke_fest():
    netz, th = _strecke("gp")
    a = _gelaende(netz, th).netz()
    b = _gelaende(netz, th).netz()
    c = _gelaende(netz, th, name="Andere Strecke").netz()
    assert np.array_equal(a.positionen, b.positionen)
    assert not np.array_equal(a.positionen[:, 2], c.positionen[:, 2])


def test_das_netz_hat_keine_loecher(berg):
    """Jede Kante gehört zu zwei Dreiecken — außer am äußersten Ring."""
    _netz, _th, gel = berg
    netz = gel.netz()
    idx = netz.indizes.astype(np.int64)
    kanten = np.sort(np.concatenate([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]]), axis=1)
    schluessel = kanten[:, 0] * len(netz.positionen) + kanten[:, 1]
    werte, anzahl = np.unique(schluessel, return_counts=True)
    assert anzahl.max() == 2, "Kante mit mehr als zwei Dreiecken: Netz überlappt"
    einzeln = werte[anzahl == 1]
    ecken = np.unique(np.concatenate([einzeln // len(netz.positionen), einzeln % len(netz.positionen)]))
    r = np.linalg.norm(netz.positionen[ecken, :2] - gel.mitte, axis=1)
    assert r.min() > gelaende.AUSSEN_M * 0.8


def test_das_netz_reicht_bis_zum_horizont(berg):
    _netz, _th, gel = berg
    p = gel.netz().positionen
    r = np.linalg.norm(p[:, :2] - gel.mitte, axis=1)
    assert r.max() == pytest.approx(gelaende.AUSSEN_M, rel=0.02)


def test_die_normalen_zeigen_nach_oben_und_sind_normiert(berg):
    _netz, _th, gel = berg
    n = gel.netz().normalen
    assert np.all(np.isfinite(n))
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=1e-4)
    assert n[:, 2].min() > 0.0


def test_hoehe_folgt_dem_gezeichneten_dreieck(berg):
    """Mitten in einer Gitterzelle: die Abfrage liefert das Dreieck, nicht das Feld."""
    _netz, _th, gel = berg
    xs, ys, z = gel._gitter_bauen()
    rng = np.random.default_rng(3)
    i = rng.integers(0, len(xs) - 1, 200)
    j = rng.integers(0, len(ys) - 1, 200)
    u, v = rng.uniform(size=200), rng.uniform(size=200)
    x = xs[i] + u * (xs[i + 1] - xs[i])
    y = ys[j] + v * (ys[j + 1] - ys[j])
    erwartet = np.where(u >= v, z[j, i] + u * (z[j, i + 1] - z[j, i]) + v * (z[j + 1, i + 1] - z[j, i + 1]),
                        z[j, i] + v * (z[j + 1, i] - z[j, i]) + u * (z[j + 1, i + 1] - z[j + 1, i]))
    assert np.allclose(gel.hoehe(x, y), erwartet)
    # Und an den Gitterpunkten genau die Netzhöhe.
    assert np.allclose(gel.hoehe(xs[i], ys[j]), z[j, i])


def test_feinere_stufe_hat_mehr_dreiecke():
    netz, th = _strecke("gp")
    grob = len(_gelaende(netz, th, detail=0).netz().indizes)
    fein = len(_gelaende(netz, th, detail=2).netz().indizes)
    assert fein > 2 * grob


# ---------------------------------------------------------------------------
# Deko auf dem Gelände
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def berg_orte(berg):
    netz, th, _gel = berg
    gel = _gelaende(netz, th, detail=0)
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
    return orte, platzierung.hoehen_setzen(orte, gel, th), gel, th


def test_nichts_schwebt(berg_orte):
    _orte, gesetzt, gel, _th = berg_orte
    x = np.array([p.x for p in gesetzt])
    y = np.array([p.y for p in gesetzt])
    z = np.array([p.z for p in gesetzt])
    assert np.all(z <= gel.hoehe(x, y) + 1e-6)


def test_randobjekte_stehen_auf_null(berg_orte):
    _orte, gesetzt, gel, th = berg_orte
    arten = {n for r in th.rand for n in r.modell.split("|")}
    rand = [p for p in gesetzt if p.modell in arten]
    assert rand
    for p in rand:
        if gel.kantenabstand(np.array([p.x]), np.array([p.y]))[0] < gel.korridor - 2:
            assert p.z == pytest.approx(0.0, abs=0.01)


def test_baeume_nicht_am_steilhang(berg_orte):
    _orte, gesetzt, gel, th = berg_orte
    baeume = [p for p in gesetzt if "tanne" in p.modell]
    assert baeume
    n = gel.neigung_feld_grad(np.array([p.x for p in baeume]), np.array([p.y for p in baeume]))
    assert n.max() <= th.gelaende.baum_hang_max_grad + 1e-6


def test_haeuser_stehen_eben(berg_orte):
    """Unter jedem Haus ist die Fläche geebnet (das Netz folgt je nach Stufe)."""
    _orte, gesetzt, gel, _th = berg_orte
    huetten = [p for p in gesetzt if "almhuette" in p.modell]
    assert huetten, "am Berg fallen sonst alle Hütten weg"
    for p in huetten:
        w = np.linspace(0, 2 * math.pi, 8, endpoint=False)
        r = 9.0 * p.skala * 0.8
        h = gel.feld(p.x + r * np.cos(w), p.y + r * np.sin(w))
        assert h.max() - h.min() < 1e-6


def test_ausduennen_behaelt_den_rand():
    netz, th = _strecke("gp")
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
    duenn = platzierung.ausduennen(orte, th, 0.4, netz.name)
    rand = {n for r in th.rand for n in r.modell.split("|")}
    assert sum(p.modell in rand for p in duenn) == sum(p.modell in rand for p in orte)
    assert len(duenn) < len(orte)
    assert duenn == platzierung.ausduennen(orte, th, 0.4, netz.name)


# ---------------------------------------------------------------------------
# Gras
# ---------------------------------------------------------------------------

def test_kein_gras_auf_der_strecke_und_nicht_zu_weit():
    netz, th = _strecke("gp")
    gel = _gelaende(netz, th)
    feld = gelaende.gras_platzieren(gel, th.gras, 2, netz.name)
    assert len(feld.pos) > 1000
    d = platzierung.abstand_zur_linie(feld.pos[:, :2], netz.mittellinie) - netz.halbe_breite_m
    assert d.min() > 0.8
    assert d.max() < th.gras.bis_m + 1.0


def test_gras_nach_grafikstufe():
    netz, th = _strecke("gp")
    gel = _gelaende(netz, th)
    aus = gelaende.gras_platzieren(gel, th.gras, 0, netz.name)
    duenn = gelaende.gras_platzieren(gel, th.gras, 1, netz.name)
    dicht = gelaende.gras_platzieren(gel, th.gras, 2, netz.name)
    assert len(aus.pos) == 0
    assert 0 < len(duenn.pos) < len(dicht.pos)


def test_kein_gras_in_der_stadt():
    netz, th = _strecke("city")
    gel = _gelaende(netz, th)
    assert len(gelaende.gras_platzieren(gel, th.gras, 2, netz.name).pos) == 0


def test_gras_steht_auf_dem_boden():
    netz, th = _strecke("mountain")
    gel = _gelaende(netz, th)
    feld = gelaende.gras_platzieren(gel, th.gras, 2, netz.name)
    h = gel.hoehe(feld.pos[:, 0], feld.pos[:, 1]) + gelaende.VERSATZ_M
    assert np.allclose(feld.pos[:, 2], h)


def test_grasbueschel_hat_halme_von_fuss_bis_spitze():
    gras = thema.laden(THEMEN, "forest").gras
    pos, nor, uv, idx = gelaende.grasbueschel(gras, 1)
    assert len(idx) == 3 * gras.halme
    assert pos[:, 2].min() == 0.0 and 0.5 < pos[:, 2].max() <= 1.0
    assert nor[:, 2].min() > 0.8
    assert uv[:, 1].min() == 0.0 and uv[:, 1].max() == 1.0


def test_fernwald_nur_draussen_und_unter_der_baumgrenze():
    netz, th = _strecke("mountain")
    gel = _gelaende(netz, th)
    wald = gelaende.fernwald_platzieren(gel, netz.name)
    assert len(wald.pos) > 100
    r = gel.rechteckabstand(wald.pos[:, 0], wald.pos[:, 1])
    assert r.min() > th.gelaende.wald_ab_m
    assert gel.feld(wald.pos[:, 0], wald.pos[:, 1]).max() < th.gelaende.baumgrenze_m


# ---------------------------------------------------------------------------
# Rauschen
# ---------------------------------------------------------------------------

def test_rauschen_ist_glatt_und_begrenzt():
    x = np.linspace(0, 20, 4001)
    n = gelaende.gradientenrauschen(x, np.full_like(x, 0.37), 5)
    assert np.abs(n).max() <= 1.5
    assert np.abs(np.diff(n)).max() < 0.02


def test_kein_gras_auf_vorplaetzen_und_unter_haeusern():
    netz, th = _strecke("gp")
    gel = _gelaende(netz, th)
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
    orte = platzierung.hoehen_setzen(orte, gel, th)
    sperren = platzierung.grasfreie_flaechen(orte, th)
    assert len(sperren) > 0
    feld = gelaende.gras_platzieren(gel, th.gras, 2, netz.name, sperren)
    for x, y, gier, x0, x1, y0, y1 in sperren:
        dx, dy = feld.pos[:, 0] - x, feld.pos[:, 1] - y
        lx = math.cos(gier) * dx + math.sin(gier) * dy
        ly = -math.sin(gier) * dx + math.cos(gier) * dy
        assert not np.any((lx > x0) & (lx < x1) & (ly > y0) & (ly < y1))


def test_grasfreie_flaeche_folgt_dem_grundriss():
    """Ein langes Gebäude sperrt ein langes Rechteck, gedreht wie das Gebäude."""
    th = thema.laden(THEMEN, "forest")
    boxen = next(a for a in th.rand if "boxengebaeude" in a.modell)
    ort = platzierung.Platzierung(boxen.modell, 10.0, 20.0, math.pi / 2, 1.0)
    zeile = platzierung.grasfreie_flaechen([ort], th, {boxen.modell: (-26, 26, -7, 15)})[0]
    assert tuple(zeile) == (10.0, 20.0, math.pi / 2, -26, 26, -7, 15)
