"""Streckendetails (Strang S): Ideallinie, Randsteine, Auslauf, Gummimaske,
Streckenobjekte und ihre Stufen — alles, was ohne Grafikkarte prüfbar ist."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from src.render3d import grafik, platzierung, rennszene, thema, track_mesh

WURZEL = Path(__file__).resolve().parents[1]
STRECKEN = ["oval", "city", "desert", "gp", "mountain"]


def _netz(name: str) -> track_mesh.Streckennetz:
    return track_mesh.aus_datei(WURZEL / "data" / "tracks" / f"{name}.json")


def _thema_der(name: str) -> thema.Thema:
    import json
    daten = json.loads((WURZEL / "data" / "tracks" / f"{name}.json").read_text(encoding="utf-8"))
    return thema.laden(WURZEL / "data" / "themen", thema.thema_der_strecke(daten))


# ---------------------------------------------------------------------------
# Ideallinie und Gummi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", STRECKEN)
def test_ideallinie_bleibt_auf_der_fahrbahn(name):
    netz = _netz(name)
    o = netz.ideal_versatz_m
    assert len(o) == len(netz.mittellinie)
    assert np.abs(o).max() <= netz.halbe_breite_m - 2.0
    # Sie nutzt die Breite: außen an, innen am Scheitel.
    assert np.abs(o).max() > 0.4 * netz.halbe_breite_m


def test_ideallinie_liegt_im_scheitel_innen():
    """Am engsten Punkt einer Kurve liegt die Linie auf der Innenseite."""
    netz = _netz("gp")
    kr = netz.kruemmung
    i = int(np.argmax(np.abs(kr)))
    # Linkskurve (kr > 0): innen ist links, also positiver Versatz.
    assert np.sign(netz.ideal_versatz_m[i]) == np.sign(kr[i])


def test_gummimaske_folgt_der_ideallinie():
    netz = _netz("gp")
    maske = track_mesh.gummi_maske(netz, quer_px=128)
    assert maske.dtype == np.uint8 and maske.shape[1] == 128
    # Zeile für Zeile liegt das Maximum dort, wo die Ideallinie ist.
    zeilen = maske.shape[0]
    s = (np.arange(zeilen) + 0.5) / zeilen * netz.laenge_m
    o = np.interp(s, np.concatenate([netz.bogen_m, [netz.laenge_m]]),
                  np.concatenate([netz.ideal_versatz_m, netz.ideal_versatz_m[:1]]))
    spalte = (netz.halbe_breite_m - o) / (2 * netz.halbe_breite_m) * 128
    treffer = np.abs(np.argmax(maske, axis=1) - spalte) < 128 * 1.2 / (2 * netz.halbe_breite_m) + 2
    assert treffer.mean() > 0.9
    # Am Rand liegt kaum Gummi.
    assert maske[:, :3].mean() < maske.max(axis=1).mean() * 0.3


# ---------------------------------------------------------------------------
# Randsteine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", STRECKEN)
def test_randsteine_nur_in_kurven_und_innerhalb_der_fahrbahn(name):
    netz = _netz(name)
    for seite in ("randstein_links", "randstein_rechts"):
        band = netz.band(seite)
        assert band is not None
        p = band.positionen[:, :2].astype(np.float64)
        abstand = platzierung.abstand_zur_linie(p, netz.mittellinie)
        # Nie außerhalb der Kante (dort steht die Begrenzung), höchstens die
        # Steinbreite nach innen.
        # (5 cm Spiel: der Abstand zum Linienzug ist an seinen Ecken kürzer.)
        assert abstand.max() <= netz.halbe_breite_m + 0.05
        assert abstand.min() >= netz.halbe_breite_m - 1.0 - 0.05
        assert band.positionen[:, 2].max() <= track_mesh.RANDSTEIN_HOEHE_M + 1e-6
    # Nicht die ganze Strecke: auf Geraden liegt kein Stein.
    kr = np.abs(netz.kruemmung)
    links, rechts = track_mesh.randstein_masken(netz.kruemmung, netz.laenge_m / len(kr))
    assert not (links & rechts).all()
    assert not links[kr < 1 / 400].any() or links.mean() < 0.9


def test_randstein_innenkante_taucht_unter_die_fahrbahn():
    """Stein und Fahrbahn schneiden sich in einer Linie: innen unter z = 0."""
    p = np.asarray(track_mesh.RANDSTEIN_PROFIL)
    assert p[0, 1] < 0 and p[-1, 1] < 0          # beide Enden unter der Fahrbahn
    assert p[-1, 0] == pytest.approx(1.0)
    # Steil genug gegen Z-Fighting: über 10 % Steigung an der Innenkante.
    steigung = (p[-2, 1] - p[-1, 1]) * track_mesh.RANDSTEIN_HOEHE_M / ((p[-1, 0] - p[-2, 0]) * 1.0)
    assert steigung > 0.1


def test_randsteintextur_hat_rot_und_weiss():
    bild = rennszene.randstein_bild(((0.8, 0.1, 0.1), (0.95, 0.95, 0.95)))
    assert bild.shape == (256, 64, 3)
    oben, unten = bild[:128].reshape(-1, 3).mean(0), bild[128:].reshape(-1, 3).mean(0)
    assert oben[0] > 2 * oben[1]                  # rot
    assert unten.min() > 150                      # weiß


# ---------------------------------------------------------------------------
# Auslauf
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", STRECKEN)
def test_auslauf_reicht_nie_bis_an_ein_anderes_streckenstueck(name):
    netz = _netz(name)
    for band in track_mesh.auslauf_baender(netz, 10.0):
        p = band.positionen[:, :2].astype(np.float64)
        abstand = platzierung.abstand_zur_linie(p, netz.mittellinie)
        assert abstand.min() >= netz.halbe_breite_m - 0.05
        # Flach über dem Boden, der Rand darunter.
        assert band.positionen[:, 2].max() == pytest.approx(track_mesh.AUSLAUF_HOEHE_M)
        assert band.positionen[:, 2].min() < 0


def test_auslauf_liegt_aussen_an_kurven():
    netz = _netz("gp")
    links, rechts = track_mesh.auslauf_breiten(netz.mittellinie, netz.halbe_breite_m, 10.0)
    kr = track_mesh._ring_glaetten(netz.kruemmung, 2)
    # In einer scharfen Linkskurve ist außen rechts.
    i = int(np.argmax(kr))
    assert rechts[i] > 5.0 and links[i] == 0.0
    assert 0 < (links > 0).mean() < 0.9


def test_platzierung_laesst_kiesbett_frei():
    netz = _netz("gp")
    th = _thema_der("gp")
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name, details=2)
    kreise = track_mesh.auslauf_kreise(netz.mittellinie, netz.halbe_breite_m, th.auslauf.breite_m)
    deko = {m for d in th.deko for m in d.modell.split("|")}
    for pl in orte:
        if pl.modell not in deko:
            continue
        for (x, y, r) in kreise:
            assert math.hypot(pl.x - x, pl.y - y) >= r - 0.5, pl.modell


# ---------------------------------------------------------------------------
# Streckenobjekte
# ---------------------------------------------------------------------------

def test_fangzaun_kette_ist_lueckenlos():
    """Aufeinanderfolgende Glieder stoßen an: Ende des einen = Anfang des nächsten."""
    netz = _netz("gp")
    art = thema.Randart("strecke/fangzaun", art="kette", abstand_m=4.0, je_m=4.0,
                        seite="aussen", radius_m=0.4)
    rng = np.random.default_rng(1)
    glieder = platzierung.kette_setzen(art, netz.mittellinie, netz.halbe_breite_m,
                                       platzierung._Belegung(), rng)
    assert len(glieder) > 50
    enden = []
    for g in glieder:
        d = np.array([math.cos(g.gier_rad), math.sin(g.gier_rad)]) * 2.0
        enden.append((np.array([g.x, g.y]) - d, np.array([g.x, g.y]) + d))
    luecken = []
    for (a0, a1), (b0, b1) in zip(enden[:-1], enden[1:]):
        luecken.append(min(np.linalg.norm(x - y) for x in (a0, a1) for y in (b0, b1)))
    assert np.median(luecken) < 0.2
    # Die Vorderseite (+Y) zeigt zur Strecke.
    for g in glieder[:20]:
        vorn = np.array([-math.sin(g.gier_rad), math.cos(g.gier_rad)])
        i = int(np.argmin(((netz.mittellinie - (g.x, g.y)) ** 2).sum(axis=1)))
        assert vorn @ (netz.mittellinie[i] - (g.x, g.y)) > 0


def test_streckenobjekte_nach_stufe():
    netz = _netz("gp")
    th = _thema_der("gp")
    wenig = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name, details=0)
    viel = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name, details=2)
    namen0 = {p.modell for p in wenig}
    namen2 = {p.modell for p in viel}
    assert "strecke/tribuene" in namen0 and "strecke/boxengebaeude" in namen0
    assert "strecke/huetchen" not in namen0 and "strecke/huetchen" in namen2
    assert "strecke/fangzaun" not in namen0 and "strecke/fangzaun" in namen2
    # Ohne Angabe gilt die Grafikstufe.
    alt = grafik.aktuell()
    try:
        grafik.stufe_setzen("niedrig")
        ohne = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name)
        assert {p.modell for p in ohne} == namen0
    finally:
        grafik.aus_dict(grafik.als_dict(alt))


def test_start_objekte_stehen_an_der_startlinie():
    netz = _netz("gp")
    th = _thema_der("gp")
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, th, netz.name, details=2)
    tribuene = [p for p in orte if p.modell == "strecke/tribuene"]
    assert len(tribuene) == 1
    d = math.hypot(tribuene[0].x - netz.mittellinie[0, 0], tribuene[0].y - netz.mittellinie[0, 1])
    assert d < netz.halbe_breite_m + 15.0


def test_themen_lesen_strang_s_felder():
    th = _thema_der("city")
    assert th.mittellinie is True
    assert th.auslauf.breite_m > 0 and th.auslauf.textur == "asphalt"
    arten = {r.modell: r for r in th.rand}
    assert arten["strecke/huetchen"].detail == 2
    assert arten["strecke/boxengebaeude"].art == "start"


def test_keine_echten_namen_in_den_streckenobjekten():
    """Banden und Schilder tragen erfundene Marken — nie einen echten Namen."""
    quelle = (WURZEL / "tools" / "texturen_erzeugen.py").read_text(encoding="utf-8")
    quelle += (WURZEL / "tools" / "blender" / "umgebung_bauen.py").read_text(encoding="utf-8")
    for verboten in ("Raht", "Philip"):
        assert verboten not in quelle
