"""Movie-Modus nach der Zieldurchfahrt (Plan 1.1.0, Abschnitt 2).

Vier Gruppen:

* **Aufstellung** — die TV-Kameras stehen neben der Strecke, ueber dem Boden,
  in keinem Objekt, und sehen die Strecke (reine Rechnung, echte Strecken und
  echtes Gelaende, kein Fenster).
* **Regie** — Zielwahl, naechster Standort voraus, Mindestlaenge, kein Hin und Her.
* **Uhr** — 30 Sekunden nach dem Ende des Feldes zu den Ergebnissen, Enter
  springt sofort.
* **Im Rennen** — offline, online und im Splitscreen: nichts haengt, die
  Wertung kommt wie bisher an, nur das Erscheinen der Seite verschiebt sich.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pygame
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from src.render3d import tv_regie  # noqa: E402
from src.render3d.tv_regie import (  # noqa: E402
    Auto, Film, Nachspiel, Regie, Rundkurs, kameras_platzieren, NACHLAUF_S,
)
from tests import spielhilfe  # noqa: E402


@pytest.fixture(autouse=True)
def _sauber(monkeypatch):
    spielhilfe.bus_isolieren(monkeypatch)
    spielhilfe.aufbau_bewahren(monkeypatch)
    yield
    spielhilfe.alles_schliessen()


# ---------------------------------------------------------------------------
# Aufstellung
# ---------------------------------------------------------------------------

STRECKEN = ["oval", "city", "desert", "gp", "mountain"]


def _welt(name: str):
    """Mittellinie, Breite, Boden und Objekte einer mitgelieferten Strecke —
    so, wie die Rennszene sie baut (ohne OpenGL)."""
    from src.render3d import gelaende, platzierung, thema, track_mesh
    strecke = json.loads((_ROOT / "data" / "tracks" / f"{name}.json").read_text(encoding="utf-8"))
    netz = track_mesh.bauen(strecke)
    t = thema.laden(_ROOT / "data" / "themen", thema.thema_der_strecke(strecke))
    orte = platzierung.platzieren(netz.mittellinie, netz.halbe_breite_m, t, netz.name or name)
    from types import SimpleNamespace
    from src.states.movie_modus import MovieModus
    hind = MovieModus._hindernisse(SimpleNamespace(platzierungen=orte, thema=t))
    auslauf = float(getattr(getattr(t, "auslauf", None), "breite_m", 0.0) or 0.0)
    gel = gelaende.Gelaende(netz.mittellinie, netz.halbe_breite_m, t.gelaende, netz.name or name,
                            rand_arten=t.rand, auslauf_m=auslauf) if t.gelaende else None
    return netz, hind, (gel.hoehe if gel is not None else None), netz.name or name


@pytest.mark.parametrize("name", STRECKEN)
def test_kameras_stehen_neben_der_strecke_ueber_dem_boden(name):
    netz, hind, boden, schluessel = _welt(name)
    st = kameras_platzieren(netz.mittellinie, netz.halbe_breite_m, name=schluessel,
                            hoehe_fn=boden, hindernisse=hind, abstand_m=40.0)
    kurs = Rundkurs(netz.mittellinie)
    assert len(st) >= 6, f"{name}: nur {len(st)} Kameras"
    for s in st:
        x, y, z = (float(v) for v in s.pos)
        # Nicht auf der Fahrbahn und nicht in der Begrenzung.
        assert kurs.abstand(x, y) - netz.halbe_breite_m >= tv_regie.KANTE_MIN_M - 1e-6
        # In keinem Baum, Haus, keiner Tribuene.
        if len(hind):
            frei = np.hypot(hind[:, 0] - x, hind[:, 1] - y) - hind[:, 2]
            assert frei.min() >= tv_regie.OBJEKT_FREI_M - 1e-6, f"{name}: Kamera {s.nr} im Objekt"
        # Ueber dem Boden, 2-8 m.
        g = float(boden(np.array([x]), np.array([y]))[0]) if boden is not None else 0.0
        assert 2.0 - 1e-6 <= z - g <= 8.0 + 1e-6, f"{name}: Kamera {s.nr} {z - g:.1f} m ueber Boden"


def test_es_gibt_tiefe_und_hohe_kameras():
    """Auf den Strecken zusammen: einige neben der Bahn tief, einige erhoeht."""
    hoehen = []
    for name in STRECKEN:
        netz, hind, boden, schluessel = _welt(name)
        for s in kameras_platzieren(netz.mittellinie, netz.halbe_breite_m, name=schluessel,
                                    hoehe_fn=boden, hindernisse=hind, abstand_m=40.0):
            g = float(boden(np.array([s.pos[0]]), np.array([s.pos[1]]))[0]) if boden is not None else 0.0
            hoehen.append(float(s.pos[2]) - g)
    assert min(hoehen) <= 3.5 and max(hoehen) >= 6.0, f"Hoehen {sorted(set(round(h, 1) for h in hoehen))}"
    assert sum(1 for h in hoehen if h <= 3.5) >= 3 and sum(1 for h in hoehen if h >= 6.0) >= 5


@pytest.mark.parametrize("name", STRECKEN)
def test_aufstellung_ist_abwechslungsreich_und_fest(name):
    netz, hind, boden, schluessel = _welt(name)
    a = kameras_platzieren(netz.mittellinie, netz.halbe_breite_m, name=schluessel,
                           hoehe_fn=boden, hindernisse=hind, abstand_m=40.0)
    b = kameras_platzieren(netz.mittellinie, netz.halbe_breite_m, name=schluessel,
                           hoehe_fn=boden, hindernisse=hind, abstand_m=40.0)
    assert [tuple(s.pos) for s in a] == [tuple(s.pos) for s in b], "Aufstellung nicht fest je Strecke"
    assert {s.seite for s in a} == {1, -1}, "alle Kameras auf einer Seite"
    hoehen = {round(float(s.pos[2]) - (float(boden(np.array([s.pos[0]]), np.array([s.pos[1]]))[0])
                                         if boden is not None else 0.0), 1) for s in a}
    # Ein hoher Zaun rund um die Strecke (Oval, Stadt) laesst nur hohe Kameras
    # ueber sich hinwegsehen; tiefe stehen dort, wo nichts im Weg ist.
    assert len(hoehen) >= 2, "kaum verschiedene Hoehen"
    # Reihum entlang der Strecke: kein Loch, das groesser als zwei Abstaende ist.
    kurs = Rundkurs(netz.mittellinie)
    bogen = sorted(s.bogen_m for s in a)
    luecken = np.diff(bogen + [bogen[0] + kurs.laenge])
    assert luecken.max() < 3 * 55.0 + 60.0


def test_kamera_meidet_objekte_und_huegel():
    """Objekte und Gelaende, die im Weg stehen, schliessen Standorte aus."""
    kreis = np.array([[300 * math.cos(w), 300 * math.sin(w)] for w in np.linspace(0, 2 * math.pi, 120, endpoint=False)])
    halb = 6.0
    frei = kameras_platzieren(kreis, halb, name="rund", abstand_m=60.0)
    # Eine Mauer aus Objekten ausserhalb: dort darf keine Kamera stehen.
    winkel = np.linspace(0, 2 * math.pi, 200)
    mauer = np.array([[(300 + 14) * math.cos(w), (300 + 14) * math.sin(w), 8.0] for w in winkel]
                     + [[(300 - 14) * math.cos(w), (300 - 14) * math.sin(w), 8.0] for w in winkel])
    belegt = kameras_platzieren(kreis, halb, name="rund", abstand_m=60.0, hindernisse=mauer)
    for s in belegt:
        d = np.hypot(mauer[:, 0] - s.pos[0], mauer[:, 1] - s.pos[1]) - mauer[:, 2]
        assert d.min() >= tv_regie.OBJEKT_FREI_M - 1e-6
    # Ein Hang direkt an der Strecke verdeckt die Sicht -> dort keine Kamera.
    def hang(x, y):
        r = np.hypot(x, y)
        return np.where(r > 300 + halb + 4.0, 14.0, 0.0)       # steile Wand aussen
    mit_hang = kameras_platzieren(kreis, halb, name="rund", abstand_m=60.0, hoehe_fn=hang)
    for s in mit_hang:
        r = math.hypot(s.pos[0], s.pos[1])
        assert not (r > 300 + halb + 4.0 and s.pos[2] - 14.0 < 2.0 - 1e-6), "Kamera im Hang"
    assert len(frei) >= len(mit_hang) - 1


def _kreis(radius=300.0, n=240):
    return np.array([[radius * math.cos(w), radius * math.sin(w)]
                     for w in np.linspace(0, 2 * math.pi, n, endpoint=False)])


def test_posten_zwischen_kamera_und_strecke_verdeckt():
    """Ein Posten (Radius 2,5, Hoehe 3 m) auf dem Sichtstrahl: Standort ungueltig."""
    kreis = _kreis()
    kurs = Rundkurs(kreis)
    halb = 6.0
    # Kamera 14 m hinter der Fahrbahnkante, 2,5 m hoch, bei Winkel 0 (x = 314 + ...).
    cx, cy, h = 300.0 + halb + 14.0, 0.0, 2.5
    assert tv_regie.standort_gueltig(kurs, halb, None, np.zeros((0, 4)), cx, cy, h, 0.0)
    posten = np.array([[300.0 + halb + 8.0, 0.0, 2.5, 3.0]])   # mitten auf dem Strahl
    assert not tv_regie.standort_gueltig(kurs, halb, None, posten, cx, cy, h, 0.0),         "ein Posten auf dem Sichtstrahl muss den Standort ausschliessen"
    # Weit weg vom Strahl und vom Objektiv stoert er nicht.
    fern = np.array([[300.0 + halb + 8.0, 60.0, 2.5, 3.0]])
    assert tv_regie.standort_gueltig(kurs, halb, None, fern, cx, cy, h, 0.0)


def test_hohes_objekt_vor_dem_objektiv_schliesst_aus():
    kreis = _kreis()
    kurs = Rundkurs(kreis)
    halb = 6.0
    cx, cy, h = 300.0 + halb + 14.0, 0.0, 2.5
    # Seitlich vor der Linse, 5 m entfernt, nicht auf der Mittelachse: sonst frei.
    schild = np.array([[cx - 4.0, 4.0, 1.0, 3.5]])
    assert not tv_regie.standort_gueltig(kurs, halb, None, schild, cx, cy, h, 0.0)
    # Dasselbe niedrig (Reifenstapel) ist kein Problem.
    stapel = np.array([[cx - 7.0, 7.0, 1.0, 0.8]])
    assert tv_regie.standort_gueltig(kurs, halb, None, stapel, cx, cy, h, 0.0)


def test_verdeckte_kameras_werden_beim_schnitt_uebergangen():
    kreis = _kreis()
    st = kameras_platzieren(kreis, 6.0, name="regie", abstand_m=2 * math.pi * 300 / 12)
    kurs = Rundkurs(kreis)
    auto = _auf_kreis(1, 0.3)
    ohne = Regie(kurs, st, runden_gesamt=3)
    erster, _ = ohne.waehle_standort(auto)
    # Posten genau zwischen diesem Standort und dem Auto.
    mitte = (erster.pos[:2] + np.array([auto.x, auto.y])) / 2.0
    posten = np.array([[mitte[0], mitte[1], 2.5, 12.0]])
    mit = Regie(kurs, st, runden_gesamt=3, hindernisse=posten)
    assert not mit.sieht(erster, auto) and ohne.sieht(erster, auto)
    gewaehlt, _ = mit.waehle_standort(auto)
    assert gewaehlt.nr != erster.nr, "die verdeckte Kamera wurde trotzdem gewaehlt"
    assert mit.sieht(gewaehlt, auto)


def test_verdeckung_im_schuss_loest_schnitt_aus():
    kreis = _kreis()
    st = kameras_platzieren(kreis, 6.0, name="regie", abstand_m=2 * math.pi * 300 / 12)
    kurs = Rundkurs(kreis)
    regie = Regie(kurs, st, runden_gesamt=3)
    auto = _auf_kreis(1, 0.3)
    regie.aktualisieren(0.1, [auto, _auf_kreis(2, 3.0)])
    erster = regie.standort
    ziel = next(a for a in [auto, _auf_kreis(2, 3.0)] if a.kennung == regie.ziel_kennung)
    mitte = (erster.pos[:2] + np.array([ziel.x, ziel.y])) / 2.0
    regie.hindernisse = tv_regie.hindernisse_normalisieren(np.array([[mitte[0], mitte[1], 2.5, 12.0]]))
    n = regie.schnitte
    for _ in range(int((Regie.MIN_SCHUSS_S + Regie.VERDECKT_SCHNITT_S + 0.5) * 30)):
        regie.aktualisieren(1 / 30, [ziel, _auf_kreis(2, 3.0)])
    assert regie.schnitte > n, "ein dauerhaft verdecktes Ziel haelt die Kamera fest"


def test_rundkurs_bogen_und_vorsprung():
    kreis = np.array([[100 * math.cos(w), 100 * math.sin(w)] for w in np.linspace(0, 2 * math.pi, 200, endpoint=False)])
    k = Rundkurs(kreis)
    assert k.laenge == pytest.approx(2 * math.pi * 100, rel=0.01)
    s0 = k.bogen_bei(100.0, 0.0)
    s1 = k.bogen_bei(0.0, 100.0)               # eine Viertelrunde weiter
    assert k.vor(s0, s1) == pytest.approx(k.laenge / 4, rel=0.02)
    assert k.vor_vorzeichen(s1, s0) == pytest.approx(-k.laenge / 4, rel=0.02)
    assert k.abstand(110.0, 0.0) == pytest.approx(10.0, abs=0.2)


# ---------------------------------------------------------------------------
# Regie
# ---------------------------------------------------------------------------

def _kreisregie(runden: int = 3, anzahl: int = 12):
    kreis = np.array([[300 * math.cos(w), 300 * math.sin(w)] for w in np.linspace(0, 2 * math.pi, 400, endpoint=False)])
    st = kameras_platzieren(kreis, 6.0, name="regie", abstand_m=2 * math.pi * 300 / anzahl)
    return Regie(Rundkurs(kreis), st, runden_gesamt=runden), kreis


def _auf_kreis(kennung, winkel, runden=1.0, im_ziel=False, eigen=False, tempo=30.0):
    return Auto(kennung, 300 * math.cos(winkel), 300 * math.sin(winkel),
                gier=winkel + math.pi / 2, tempo=tempo, runden=runden,
                im_ziel=im_ziel, eigen=eigen, name=f"Auto {kennung}")


def test_ziel_ist_ein_auto_das_noch_faehrt():
    regie, _ = _kreisregie()
    autos = [_auf_kreis(1, 0.0, runden=3.0, im_ziel=True, eigen=True),
             _auf_kreis(2, 2.0, runden=1.2),
             _auf_kreis(3, 4.0, runden=2.4)]
    assert regie.waehle_ziel(autos).kennung == 3, "nicht das Auto, das dem Ziel am naechsten ist"


def test_zweikampf_schlaegt_einsamen_fuehrenden():
    regie, _ = _kreisregie()
    autos = [_auf_kreis(1, 0.0, runden=2.0),                       # allein vorn
             _auf_kreis(2, 2.5, runden=1.7), _auf_kreis(3, 2.5 + 8 / 300, runden=1.69)]  # Kampf, 8 m
    assert regie.waehle_ziel(autos).kennung in (2, 3)


def test_alle_im_ziel_der_spieler_zuerst_dann_reihum():
    regie, _ = _kreisregie()
    autos = [_auf_kreis(1, 0.0, runden=3.0, im_ziel=True),
             _auf_kreis(2, 1.0, runden=3.0, im_ziel=True, eigen=True),
             _auf_kreis(3, 2.0, runden=3.0, im_ziel=True)]
    erster = regie.waehle_ziel(autos)
    assert erster.kennung == 2, "der Spieler soll zuerst kommen"
    regie.ziel_kennung = 2
    regie._neuer_schuss(autos)
    regie._neuer_schuss(autos)
    regie._neuer_schuss(autos)
    assert len(regie._gezeigt) >= 2, "es wechselt nicht reihum"


def test_standort_ist_der_naechste_voraus():
    regie, _ = _kreisregie()
    auto = _auf_kreis(1, 0.3)
    st, _reichweite = regie.waehle_standort(auto)
    s_auto = regie.kurs.bogen_bei(auto.x, auto.y)
    vor = regie.kurs.vor(s_auto, st.bogen_m)
    assert vor >= regie.VORLAUF_MIN_M
    for andere in regie.standorte:
        v2 = regie.kurs.vor(s_auto, andere.bogen_m)
        if v2 >= regie.VORLAUF_MIN_M and math.hypot(andere.pos[0] - auto.x, andere.pos[1] - auto.y) <= andere.reichweite_m:
            assert v2 >= vor - 1e-6, "ein naeherer Standort voraus wurde uebergangen"


def _fahren(regie, autos_fn, sekunden: float, dt: float = 1 / 30):
    """Die Regie ueber *sekunden* laufen lassen; Liste der Einstellungen
    ``(beginn, ende, standort_nr, ziel)``."""
    schuesse = []
    t = 0.0
    aktuell = None
    for _ in range(int(sekunden / dt)):
        t += dt
        autos = autos_fn(t)
        vorher = (regie.standort.nr if regie.standort else None, regie.ziel_kennung, regie.schnitte)
        regie.aktualisieren(dt, autos)
        if regie.schnitte != vorher[2]:
            if aktuell is not None:
                schuesse.append((aktuell[0], t, aktuell[1], aktuell[2]))
            aktuell = (t, regie.standort.nr, regie.ziel_kennung)
    if aktuell is not None:
        schuesse.append((aktuell[0], t, aktuell[1], aktuell[2]))
    return schuesse


def test_mindestlaenge_und_kein_hin_und_her():
    regie, _ = _kreisregie()
    # Zwei fahrende Autos und eines im Ziel, das langsam rollt.
    def autos(t):
        return [_auf_kreis(1, 0.0 + t * 0.10, runden=1 + t / 60),
                _auf_kreis(2, 2.0 + t * 0.12, runden=1 + t / 55),
                _auf_kreis(3, 4.0 + t * 0.05, runden=3.0, im_ziel=True, eigen=True, tempo=15)]
    schuesse = _fahren(regie, autos, 120.0)
    assert len(schuesse) >= 5, "kaum Schnitte in zwei Minuten"
    # Alle abgeschlossenen Einstellungen sind mindestens MIN_SCHUSS_S lang.
    for beginn, ende, _nr, _ziel in schuesse[:-1]:
        assert ende - beginn >= Regie.MIN_SCHUSS_S - 0.1, f"Einstellung nur {ende - beginn:.1f} s"
    # Kein Pingpong: derselbe Standort nie zweimal direkt hintereinander.
    nummern = [nr for (_b, _e, nr, _z) in schuesse]
    assert all(a != b for a, b in zip(nummern, nummern[1:])), f"Hin und Her: {nummern}"
    # Und ein Standort kehrt erst nach der Sperrzeit wieder, solange noch andere frei sind.
    for i, (b1, _e1, nr1, _z) in enumerate(schuesse):
        for (b2, _e2, nr2, _z2) in schuesse[i + 1:]:
            if nr2 == nr1:
                assert b2 - b1 >= Regie.SPERRE_S - 0.2, f"Standort {nr1} nach {b2 - b1:.1f} s wieder"
                break
    laengen = [e - b for (b, e, _n, _z) in schuesse]
    assert max(laengen) <= Regie.MAX_SCHUSS_S + 0.5


def test_ziel_verschwindet_sofort_neuer_schnitt():
    regie, _ = _kreisregie()
    autos = [_auf_kreis(1, 0.0), _auf_kreis(2, 1.0)]
    regie.aktualisieren(0.1, autos)
    erstes = regie.ziel_kennung
    n = regie.schnitte
    regie.aktualisieren(0.1, [a for a in autos if a.kennung != erstes])
    assert regie.ziel_kennung != erstes and regie.schnitte == n + 1, \
        "ein verschwundenes Ziel muss auch vor der Mindestlaenge einen Schnitt erzwingen"


def test_kamera_haelt_das_auto_im_bild():
    """Die Filmkamera blickt auf das Ziel; das Auto liegt im Sichtfeld."""
    regie, _ = _kreisregie()
    t = 0.0
    dt = 1 / 30
    ausserhalb = 0
    bilder = 0
    for _ in range(int(60 / dt)):
        t += dt
        autos = [_auf_kreis(1, t * 0.10, runden=1 + t / 60), _auf_kreis(2, 3.0 + t * 0.09, runden=1 + t / 50)]
        regie.aktualisieren(dt, autos)
        ziel = next(a for a in autos if a.kennung == regie.ziel_kennung)
        k = regie.kamera
        v = np.asarray(k.blickmatrix(), dtype=np.float64) @ np.array([ziel.x, ziel.y, 0.9, 1.0])
        if v[2] >= -0.5:
            ausserhalb += 1
        else:
            winkel = math.degrees(math.atan2(math.hypot(v[0], v[1]), -v[2]))
            if winkel > k.sichtfeld_grad / 2 * 1.2:
                ausserhalb += 1
        bilder += 1
    assert ausserhalb / bilder < 0.08, f"Ziel in {ausserhalb}/{bilder} Bildern ausserhalb des Sichtfelds"


def test_zoom_bleibt_maessig():
    regie, _ = _kreisregie()
    for _ in range(300):
        regie.aktualisieren(1 / 30, [_auf_kreis(1, 0.0), _auf_kreis(2, 3.0)])
        assert 22.0 - 1e-6 <= regie.kamera.sichtfeld_grad <= 55.0


# ---------------------------------------------------------------------------
# Film: Auszoomen, dann Regie
# ---------------------------------------------------------------------------

def test_film_zoomt_erst_aus_dann_regie():
    regie, _ = _kreisregie()
    film = Film(regie, auszoom_s=1.8, fov_basis=55.0)
    eigen = _auf_kreis(1, 0.5, runden=3.0, im_ziel=True, eigen=True, tempo=10)
    autos = [eigen, _auf_kreis(2, 2.0, runden=1.5)]
    auge0 = np.array([eigen.x - 7.5 * math.cos(eigen.gier), eigen.y - 7.5 * math.sin(eigen.gier), 2.8])
    ziel0 = np.array([eigen.x, eigen.y, 1.0])
    abstaende = []
    t = 0.0
    while film.phase == "zoom":
        film.aktualisieren(1 / 60, auge0, ziel0, eigen, autos)
        t += 1 / 60
        k = film.kamera
        if film.phase == "zoom":      # das Bild nach dem Schnitt gehoert schon der Regie
            abstaende.append(float(np.linalg.norm(np.asarray(k.auge, dtype=float) - [eigen.x, eigen.y, 0.9])))
        assert t < 3.0
    assert 1.7 <= t <= 1.95
    # Es zieht sich weg: Abstand waechst stetig und ohne Sprung.
    assert abstaende[-1] > abstaende[0] * 2.0
    assert max(abs(b - a) for a, b in zip(abstaende, abstaende[1:])) < 0.6
    # Weich an den Enden (Ease): am Anfang und Ende langsamer als in der Mitte.
    schritte = [b - a for a, b in zip(abstaende, abstaende[1:])]
    assert schritte[0] < max(schritte) * 0.2 and schritte[-1] < max(schritte) * 0.2
    film.aktualisieren(1 / 60, auge0, ziel0, eigen, autos)
    assert film.kamera is regie.kamera and regie.standort is not None


# ---------------------------------------------------------------------------
# Uhr
# ---------------------------------------------------------------------------

def test_nachspiel_30_sekunden_nach_dem_ende_des_feldes():
    n = Nachspiel()
    assert NACHLAUF_S == 30.0
    for _ in range(100):
        n.tick(1.0)
    assert not n.bereit and not n.laeuft, "die Uhr laeuft, bevor das Feld fertig ist"
    n.feld_fertig()
    n.feld_fertig()                            # zweiter Aufruf setzt nichts zurueck
    for _ in range(29):
        n.tick(1.0)
    assert n.laeuft and not n.bereit
    n.tick(1.0)
    assert n.bereit


def test_nachspiel_enter_ueberspringt():
    n = Nachspiel()
    n.feld_fertig()
    n.tick(2.0)
    n.ueberspringen()
    assert n.bereit


# ---------------------------------------------------------------------------
# Im Rennen
# ---------------------------------------------------------------------------

DT = 1.0 / 60.0


def _ki_spielt(rennen, tempo: float = 0.9, gegner_tempo: float = 0.5) -> None:
    """Der Mensch faehrt von der KI gesteuert; die Gegner sind langsamer, damit
    er vor ihnen ins Ziel kommt und der Film mitten im Rennen beginnt."""
    rennen._start_player_ai_takeover(rennen.player)
    rennen.player.controller.speed_multiplier = tempo
    for ai in rennen.ai_vehicles:
        ai.controller.speed_multiplier = gegner_tempo
    for ai_ in getattr(rennen, "_humans", [])[1:]:
        rennen._start_player_ai_takeover(ai_)
        ai_.controller.speed_multiplier = tempo


def _bis(rennen, bedingung, sekunden: float, je_bild=None) -> float:
    for i in range(int(sekunden / DT)):
        rennen.handle_events([])
        rennen.update(DT)
        if je_bild is not None:
            je_bild(rennen, i)
        if bedingung(rennen):
            return (i + 1) * DT
    raise AssertionError(f"Bedingung nach {sekunden:.0f} s nicht erreicht "
                         f"(Zustand {rennen.race_manager.state})")


def _spieler_im_ziel(r):
    return r.player.id in r.race_manager.finished_ids


def test_offline_film_beginnt_im_ziel_und_ergebnisse_kommen_30s_nach_dem_feld():
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    _ki_spielt(rennen)
    _bis(rennen, _spieler_im_ziel, 200.0)
    film = rennen._movie.filme.get(0)
    assert film is not None, "kein Film nach der Zieldurchfahrt"
    assert rennen.race_manager.state != "finished", "Test braucht Gegner, die noch fahren"
    assert film.platz == 1
    assert not sm.wechsel

    # Weiter bis das Feld fertig ist; waehrenddessen darf keine Ergebnisseite kommen.
    ende = {}

    def beobachten(r, _i):
        assert not sm.wechsel or "feld" in ende, "Ergebnisse kamen, obwohl das Feld noch fuhr"
        if r.race_manager.state == "finished" and "feld" not in ende:
            ende["feld"] = r.race_manager.race_time
            ende["bild"] = _i

    _bis(rennen, lambda r: "feld" in ende, 300.0, beobachten)
    bilder_bis_ergebnis = 0
    while not sm.wechsel and bilder_bis_ergebnis < int(60.0 / DT):
        rennen.handle_events([])
        rennen.update(DT)
        bilder_bis_ergebnis += 1
    assert sm.wechsel, "nach dem Film ging es nie in die Ergebnisse"
    sekunden = bilder_bis_ergebnis * DT
    from src.states.race_state import RESULTS_OUTRO_SECONDS
    assert NACHLAUF_S - 0.5 <= sekunden <= NACHLAUF_S + RESULTS_OUTRO_SECONDS + 1.0, \
        f"Ergebnisse nach {sekunden:.1f} s statt ~{NACHLAUF_S:.0f} s"
    assert film.regie.schnitte >= 1


def _enter():
    return pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)


def test_offline_enter_tut_nichts_solange_ein_auto_noch_faehrt():
    """Enter/A beendet das Rennen nie vorzeitig: kein Auto wird zum DNF gemacht."""
    from src.core import gamepad
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    _ki_spielt(rennen)
    _bis(rennen, _spieler_im_ziel, 200.0)
    rm = rennen.race_manager
    assert rennen._movie.aktiv and rm.state != "finished"
    ergebnisse_vorher = [dict(r) for r in rm.results]
    for _ in range(3):
        rennen.handle_events([_enter()])
        rennen.handle_events([pygame.event.Event(pygame.JOYBUTTONDOWN, button=gamepad.BTN_A, instance_id=0)])
        rennen.update(DT)
    assert not rennen._movie.skip_gewuenscht and not rennen._movie.ueberspringen_erlaubt()
    assert rm.state != "finished" and not sm.wechsel
    assert [r for r in rm.results if r.get("dnf")] == [], "ein Auto wurde durch Enter zum DNF"
    assert rm.results[:len(ergebnisse_vorher)] == ergebnisse_vorher
    # Das Banner zeigt den Enter-Hinweis jetzt noch nicht.
    assert not rennen._movie.wartet


def test_offline_enter_nach_dem_ende_des_feldes_springt_zu_den_ergebnissen():
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    _ki_spielt(rennen)
    _bis(rennen, _spieler_im_ziel, 200.0)
    _bis(rennen, lambda r: r._movie.wartet, 300.0)
    assert rennen._movie.ueberspringen_erlaubt() and not sm.wechsel
    vor = [dict(r) for r in rennen.race_manager.results]
    rennen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)])
    assert not rennen._movie.skip_gewuenscht            # andere Tasten: nichts
    rennen.handle_events([_enter()])
    _bis(rennen, lambda r: bool(sm.wechsel), 10.0)
    args, kwargs = sm.wechsel[-1]
    assert args[0] == "menu" and len(kwargs["results"]) == 3
    assert rennen.race_manager.results == vor, "die Wertung hat sich durch Enter veraendert"


def test_offline_pad_a_nach_dem_ende_des_feldes():
    from src.core import gamepad
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    _ki_spielt(rennen)
    _bis(rennen, _spieler_im_ziel, 200.0)
    _bis(rennen, lambda r: r._movie.wartet, 300.0)
    rennen.handle_events([pygame.event.Event(pygame.JOYBUTTONDOWN, button=gamepad.BTN_A, instance_id=0)])
    assert rennen._movie.skip_gewuenscht
    _bis(rennen, lambda r: bool(sm.wechsel), 10.0)


def test_enter_waehrend_des_rennens_aendert_die_wertung_nicht():
    """Dieselben Wertungszeilen (und damit dieselben Grand-Prix-Punkte) mit
    und ohne Tastendruck waehrend des Rennens."""
    def lauf(mit_enter: bool):
        rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3, ki_fahrzeug="rookie")
        _ki_spielt(rennen)
        _bis(rennen, _spieler_im_ziel, 200.0)
        if mit_enter:
            for _ in range(10):
                rennen.handle_events([_enter()])
                rennen.update(DT)
        _bis(rennen, lambda r: bool(sm.wechsel), 400.0)
        rows = sm.wechsel[-1][1]["results"]
        spielhilfe.schliessen(rennen)
        return [(r["position"], r["dnf"]) for r in rows]

    assert lauf(True) == lauf(False)


def test_zeitfahren_hat_keinen_film():
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=1, modus="Zeitfahren")
    _ki_spielt(rennen, tempo=0.9)
    _bis(rennen, _spieler_im_ziel, 200.0)
    assert not rennen._movie.aktiv
    _bis(rennen, lambda r: bool(sm.wechsel), 30.0)


def test_dnf_spieler_hat_keinen_film():
    """Wer nicht ins Ziel kommt (DNF), geht wie bisher in die Ergebnisse."""
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=3)
    _bis(rennen, lambda r: bool(sm.wechsel), 400.0)
    assert not rennen._movie.aktiv


# ---------------------------------------------------------------------------
# Online: nichts haengt
# ---------------------------------------------------------------------------

class _Relay:
    """Netzsitzung eines Gastes; die Gesamtwertung schickt der Test selbst."""

    slot = 1
    ping_ms = 30.0

    def __init__(self) -> None:
        self._eingang: list[dict] = []
        self.gesendet: list[dict] = []

    def send_tcp(self, msg: dict) -> None:
        self.gesendet.append(msg)

    def send_state(self, vehicles) -> None:
        pass

    def poll(self):
        while self._eingang:
            yield self._eingang.pop(0)

    def update(self, dt: float) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def ergebnisse_schicken(self) -> None:
        zeilen = [{"position": 1, "name": "Host", "slot": 0, "finish_time": 50.0},
                  {"position": 2, "name": "Gast", "slot": 1, "finish_time": 60.0}]
        self._eingang.append({"source": "tcp", "data": {"type": "RACE_RESULTS", "rows": zeilen}})


def _online_gast(monkeypatch):
    from src.net import session
    relay = _Relay()
    monkeypatch.setattr(session, "get", lambda: relay)
    rennen, sm = spielhilfe.rennen_bauen("oval", runden=1, feld=1)
    rennen._online = True
    for _ in range(int(6.0 / DT)):
        rennen.update(DT)
        if rennen.race_manager.state == "racing":
            break
    assert rennen.race_manager.state == "racing"
    # Der Gast faehrt ueber die Linie, ein Mitspieler ist noch unterwegs.
    rennen.race_manager._record_finish(rennen.player)
    return rennen, sm, relay


def test_online_ergebnisse_kommen_30s_nach_der_gesamtwertung(monkeypatch):
    rennen, sm, relay = _online_gast(monkeypatch)
    # Bis die Gesamtwertung kommt (Mitspieler noch unterwegs): Film laeuft, nichts wechselt.
    for _ in range(int(20.0 / DT)):
        rennen.update(DT)
    assert rennen._movie.aktiv and rennen._online_awaiting and not sm.wechsel
    assert any(m.get("type") == "RACE_RESULT" for m in relay.gesendet), "eigenes Ergebnis nicht gemeldet"
    assert not rennen._movie.nachspiel.laeuft, "Uhr laeuft, bevor das Feld fertig ist"

    relay.ergebnisse_schicken()
    n = 0
    while not sm.wechsel and n < int(60.0 / DT):
        rennen.update(DT)
        n += 1
        if n == int(5.0 / DT):
            assert not sm.wechsel
    assert sm.wechsel, "online haengt der Film die Ergebnisse auf"
    from src.states.race_state import RESULTS_OUTRO_SECONDS
    assert NACHLAUF_S - 0.5 <= n * DT <= NACHLAUF_S + RESULTS_OUTRO_SECONDS + 1.0
    args, kwargs = sm.wechsel[-1]
    assert [z["name"] for z in kwargs["results"]] == ["Host", "Gast"], "Gesamtwertung ging verloren"


def test_online_enter_vor_der_wertung_tut_nichts(monkeypatch):
    rennen, sm, relay = _online_gast(monkeypatch)
    for _ in range(int(3.0 / DT)):
        rennen.update(DT)
    rennen.handle_events([_enter()])
    assert not rennen._movie.skip_gewuenscht, "Enter zaehlt, obwohl noch gefahren wird"
    relay.ergebnisse_schicken()
    for _ in range(int(3.0 / DT)):
        rennen.update(DT)
    assert rennen._movie.wartet and not sm.wechsel, "ohne Enter gilt die 30-s-Uhr"
    rennen.handle_events([_enter()])               # jetzt ist das Feld fertig
    n = 0
    while not sm.wechsel and n < int(10.0 / DT):
        rennen.update(DT)
        n += 1
    assert sm.wechsel and n * DT < 5.0, "nach Enter und Wertung ohne die 30 s"


def test_online_wertung_fehlt_der_alte_notausgang_gilt_weiter(monkeypatch):
    """Kommt nie eine Gesamtwertung, greift die bisherige Frist (kein Deadlock)."""
    rennen, sm, relay = _online_gast(monkeypatch)
    for _ in range(int(2.0 / DT)):
        rennen.update(DT)
    assert rennen._online_awaiting
    rennen._online_await_deadline = 0.0           # Frist abgelaufen
    for _ in range(int((NACHLAUF_S + 6.0) / DT)):
        rennen.update(DT)
        if sm.wechsel:
            break
    assert sm.wechsel, "ohne Wertung haengt der Gast"


# ---------------------------------------------------------------------------
# Splitscreen
# ---------------------------------------------------------------------------

def _split_rennen():
    from src.core import race_setup
    from src.states.race_state import RaceState
    spielhilfe.fahrzeuge_laden()
    spielhilfe.spielstand_zuruecksetzen()
    aufbau = race_setup.current()
    aufbau.mode = "Rennen"
    aufbau.laps = 1
    aufbau.vehicle_count = 4
    aufbau.is_multiplayer = True
    aufbau.track_path = os.path.join(str(_ROOT), "data", "tracks", "oval.json")
    aufbau.sync_ai_roster()
    sm = spielhilfe.StateMachineAttrappe()
    rennen = RaceState(sm)
    rennen.enter(track_path=aufbau.track_path)
    spielhilfe._offen.append(rennen)
    return rennen, sm


def test_splitscreen_ein_film_bis_beide_durch_sind():
    rennen, sm = _split_rennen()
    if not rennen._split:
        pytest.skip("Splitscreen liess sich so nicht aufbauen")
    rennen._start_player_ai_takeover(rennen.player)
    rennen.player.controller.speed_multiplier = 0.9
    for ai in rennen.ai_vehicles:
        ai.controller.speed_multiplier = 0.4
    # Spieler 2 steht (faehrt nicht): nur Spieler 1 kommt ins Ziel.
    _bis(rennen, _spieler_im_ziel, 200.0)
    assert set(rennen._movie.filme) == {0}
    assert not rennen._movie.alle_menschen_im_film()
    assert not rennen._movie.geteilt_gesamt()
    # Enter darf nichts tun, solange Spieler 2 noch faehrt.
    rennen.handle_events([pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)])
    assert not rennen._movie.skip_gewuenscht
    # Die Ansicht: Haelfte 0 filmt, Haelfte 1 bleibt die Verfolgerkamera.
    haelften = [(0, 0, 960, 1080), (960, 0, 960, 1080)]
    h2, k2 = rennen._movie.ansichten(haelften, rennen._kameras)
    assert len(h2) == 2 and k2[0] is rennen._movie.filme[0].kamera and k2[1] is rennen._kameras[1]

    # Spieler 2 kommt auch durch -> ein gemeinsames Bild.
    rennen._start_player_ai_takeover(rennen.player2)
    rennen.player2.controller.speed_multiplier = 0.9
    rennen.race_manager._record_finish(rennen.player2)
    _bis(rennen, lambda r: r._movie.alle_menschen_im_film(), 5.0)
    assert rennen._movie.geteilt_gesamt()
    h3, k3 = rennen._movie.ansichten(haelften, rennen._kameras)
    assert len(h3) == 1 and len(k3) == 1 and h3[0] == (0, 0, 1920, 1080)
