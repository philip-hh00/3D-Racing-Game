"""Streckennetz-Erzeugung fuer den 3D-Renderer (src/render3d/track_mesh.py).

Synthetische Kreisstrecken lassen sich exakt nachrechnen und dienen als
Referenz; die echten Strecken aus ``data/tracks/`` laufen zusaetzlich als
Realitaetscheck mit.

Alle Laengen hier sind Meter (M_PER_PX = 0.08), das Koordinatensystem folgt
``src/render3d/VEREINBARUNGEN.md``: +X vorne, +Y links, +Z oben.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.render3d import track_mesh  # noqa: E402

M_PER_PX = 0.08

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "tracks"
ECHTE_STRECKEN = ["oval", "city", "desert", "gp", "mountain"]


# ---------------------------------------------------------------------------
# Synthetische Strecken
# ---------------------------------------------------------------------------


def _kreis_strecke(radius_px: float = 500.0, n: int = 360,
                    breite_px: float = 200.0) -> dict:
    """Eine exakte Kreisstrecke, gegen den Uhrzeigersinn abgetastet.

    Die Punkte liegen exakt auf dem Kreis, daher lassen sich Flaeche und
    Breite des daraus gebauten Bandes analytisch vorhersagen.
    """
    winkel = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    centerline = [
        {"x": radius_px * math.cos(a), "y": radius_px * math.sin(a)}
        for a in winkel
    ]
    return {
        "name": "Testkreis",
        "track_width": breite_px,
        "background_texture": "Grass",
        "centerline": centerline,
        "outer_wall": [],
        "inner_wall": [],
        "waypoints": [],
        "start_positions": [
            {"x": radius_px, "y": 0.0, "angle": 0.0},
            {"x": 0.0, "y": radius_px, "angle": 90.0},
            {"x": -radius_px, "y": 0.0, "angle": 180.0},
        ],
    }


def _dreiecksflaeche(band: track_mesh.Band) -> float:
    """Summe der Flaechen aller Dreiecke eines Bandes (m^2)."""
    p = band.positionen[band.indizes]  # (m, 3, 3)
    a = p[:, 1] - p[:, 0]
    b = p[:, 2] - p[:, 0]
    kreuz = np.cross(a, b)
    return float(np.sum(np.linalg.norm(kreuz, axis=1)) / 2.0)


# ---------------------------------------------------------------------------
# Kreisstrecke: Flaeche, Breite, Normalen, Geschlossenheit
# ---------------------------------------------------------------------------


def test_kreisstrecke_fahrbahnflaeche_stimmt_mit_2pi_r_mal_breite_ueberein():
    radius_px, n, breite_px = 500.0, 360, 200.0
    strecke = _kreis_strecke(radius_px, n, breite_px)
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    assert fahrbahn is not None

    radius_m = radius_px * M_PER_PX
    breite_m = breite_px * M_PER_PX
    erwartet = 2.0 * math.pi * radius_m * breite_m

    flaeche = _dreiecksflaeche(fahrbahn)

    # Ein n-Eck-Band zwischen zwei konzentrischen n-Ecken hat die Flaeche
    # N * r * w * sin(2*pi/N) statt 2*pi*r*w. Der relative Fehler ist
    # ungefaehr (2*pi)^2 / (6*N^2); bei N=360 sind das rund 5e-5 (0.005 %).
    # 0.1 % Toleranz laesst reichlich Luft und bleibt trotzdem strikt genug,
    # um eine falsch aufgebaute Geometrie zuverlaessig zu erwischen.
    assert flaeche == pytest.approx(erwartet, rel=1e-3)


def test_alle_fahrbahnpunkte_liegen_auf_z_gleich_null():
    strecke = _kreis_strecke()
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    np.testing.assert_array_equal(fahrbahn.positionen[:, 2], 0.0)


def test_normalen_der_fahrbahn_zeigen_nach_oben_und_haben_laenge_eins():
    strecke = _kreis_strecke()
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    erwartet = np.zeros_like(fahrbahn.normalen)
    erwartet[:, 2] = 1.0
    np.testing.assert_allclose(fahrbahn.normalen, erwartet, atol=1e-6)
    laengen = np.linalg.norm(fahrbahn.normalen, axis=1)
    np.testing.assert_allclose(laengen, 1.0, atol=1e-6)


def test_fahrbahn_ist_geschlossen_letzter_ring_verbindet_zum_ersten():
    strecke = _kreis_strecke(n=48)
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    n_ringe = len(fahrbahn.positionen) // 2
    # Bei n geschlossenen Ringen und je 2 Dreiecken pro Segment muss es
    # genau n Segmente geben, nicht n-1 -- sonst faehlt das schliessende Stueck.
    assert fahrbahn.indizes.shape[0] == 2 * n_ringe

    # Es muss ein Dreieck geben, das den letzten Ring (Index n_ringe-1) mit
    # dem ersten Ring (Index 0) verbindet -- die Naht.
    letzter_ring_indizes = {2 * (n_ringe - 1), 2 * (n_ringe - 1) + 1}
    erster_ring_indizes = {0, 1}
    naht_gefunden = any(
        (set(dreieck) & letzter_ring_indizes) and (set(dreieck) & erster_ring_indizes)
        for dreieck in fahrbahn.indizes.tolist()
    )
    assert naht_gefunden


def test_kein_dreieck_ist_entartet_flaeche_ueberall_positiv():
    strecke = _kreis_strecke(n=48)
    netz = track_mesh.bauen(strecke)
    for band in netz.baender:
        p = band.positionen[band.indizes]
        a = p[:, 1] - p[:, 0]
        b = p[:, 2] - p[:, 0]
        flaechen = np.linalg.norm(np.cross(a, b), axis=1) / 2.0
        assert np.all(flaechen > 1e-9), f"entartetes Dreieck in Band {band.name!r}"


def test_breite_quer_entspricht_track_width_mal_m_per_px_an_mehreren_stellen():
    breite_px = 200.0
    strecke = _kreis_strecke(breite_px=breite_px)
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    erwartete_breite_m = breite_px * M_PER_PX

    n_ringe = len(fahrbahn.positionen) // 2
    for i in (0, 10, 90, 180, 270, n_ringe - 1):
        links = fahrbahn.positionen[2 * i]
        rechts = fahrbahn.positionen[2 * i + 1]
        breite = np.linalg.norm(links - rechts)
        assert breite == pytest.approx(erwartete_breite_m, rel=1e-6)


# ---------------------------------------------------------------------------
# UV
# ---------------------------------------------------------------------------


def test_u_deckt_null_bis_eins_ab():
    strecke = _kreis_strecke()
    netz = track_mesh.bauen(strecke)
    fahrbahn = netz.band("fahrbahn")
    u = fahrbahn.uv[:, 0]
    assert u.min() == pytest.approx(0.0, abs=1e-9)
    assert u.max() == pytest.approx(1.0, abs=1e-9)


def test_v_waechst_monoton_entlang_der_strecke_und_ueberschreitet_eins():
    strecke = _kreis_strecke(radius_px=500.0, n=360)
    netz = track_mesh.bauen(strecke, kachellaenge_m=8.0)
    fahrbahn = netz.band("fahrbahn")
    n_ringe = len(fahrbahn.positionen) // 2
    v_je_ring = fahrbahn.uv[0::2, 1][:n_ringe]

    # Monoton innerhalb einer Runde (die Naht am Schluss darf zuruecksetzen).
    assert np.all(np.diff(v_je_ring) >= -1e-9)
    # Der Kreisumfang ist hier weit groesser als eine Kachellaenge, v muss
    # also mehrfach kacheln.
    assert v_je_ring.max() > 1.0


# ---------------------------------------------------------------------------
# Randsteine
# ---------------------------------------------------------------------------


def test_randsteine_liegen_innen_an_der_fahrbahnkante():
    """Die Randsteine liegen auf der Fahrbahn, bündig mit ihrer Kante.

    Die Wände des Spiels fallen mit der Fahrbahnkante zusammen; dort stehen in
    3D die Leitplanken. Außen liegende Randsteine schöben die Planke einen
    Meter hinter die Stelle, an der das Auto abprallt.
    """
    radius_px, breite_px, randstein_m = 500.0, 200.0, 1.0
    strecke = _kreis_strecke(radius_px, n=180, breite_px=breite_px)
    netz = track_mesh.bauen(strecke, randstein_m=randstein_m)

    radius_m = radius_px * M_PER_PX
    halbe_breite_m = breite_px * M_PER_PX / 2.0

    links = netz.band("randstein_links")
    rechts = netz.band("randstein_rechts")
    assert links is not None and rechts is not None

    abstand_links = np.linalg.norm(links.positionen[:, :2], axis=1)
    abstand_rechts = np.linalg.norm(rechts.positionen[:, :2], axis=1)

    # Gegen den Uhrzeigersinn abgetastet zeigt "links" zur Kreismitte.
    assert abstand_links.min() == pytest.approx(radius_m - halbe_breite_m, rel=1e-6)
    assert abstand_links.max() == pytest.approx(
        radius_m - halbe_breite_m + randstein_m, rel=1e-6)
    assert abstand_rechts.max() == pytest.approx(radius_m + halbe_breite_m, rel=1e-6)
    assert abstand_rechts.min() == pytest.approx(
        radius_m + halbe_breite_m - randstein_m, rel=1e-6)
    assert (links.positionen[:, 2] > 0).all()


# ---------------------------------------------------------------------------
# Untergrund
# ---------------------------------------------------------------------------


def test_untergrund_umschliesst_die_gesamte_strecke():
    radius_px = 500.0
    rand_m = 200.0
    strecke = _kreis_strecke(radius_px)
    netz = track_mesh.bauen(strecke, untergrund_rand_m=rand_m)
    fahrbahn = netz.band("fahrbahn")
    untergrund = netz.band("untergrund")
    assert untergrund is not None

    min_u = untergrund.positionen[:, :2].min(axis=0)
    max_u = untergrund.positionen[:, :2].max(axis=0)
    min_f = fahrbahn.positionen[:, :2].min(axis=0)
    max_f = fahrbahn.positionen[:, :2].max(axis=0)

    assert np.all(min_u <= min_f)
    assert np.all(max_u >= max_f)
    # Der Rand muss tatsaechlich um rand_m ueber die Fahrbahn hinausreichen.
    assert np.all(min_f - min_u >= rand_m - 1e-6)
    assert np.all(max_u - max_f >= rand_m - 1e-6)


def test_untergrund_liegt_minimal_unter_z_null_gegen_z_fighting():
    strecke = _kreis_strecke()
    netz = track_mesh.bauen(strecke)
    untergrund = netz.band("untergrund")
    z = untergrund.positionen[:, 2]
    # Knapp unter Null, aber deutlich messbar -- kein Zufallsrauschen.
    assert np.all(z < 0.0)
    assert np.all(z > -1.0)


# ---------------------------------------------------------------------------
# Startpositionen
# ---------------------------------------------------------------------------


def test_startpositionen_anzahl_und_umrechnung_in_radiant():
    strecke = _kreis_strecke()
    netz = track_mesh.bauen(strecke)
    assert len(netz.start_positionen) == len(strecke["start_positions"])

    x_m, y_m, gier_rad = netz.start_positionen[1]  # angle=90 im Kreis-Fixture
    assert gier_rad == pytest.approx(math.pi / 2.0, abs=1e-9)
    assert x_m == pytest.approx(0.0, abs=1e-9)
    assert y_m == pytest.approx(500.0 * M_PER_PX, abs=1e-9)


def test_neunzig_grad_wird_zu_pi_halbe():
    strecke = _kreis_strecke()
    strecke["start_positions"] = [{"x": 0.0, "y": 0.0, "angle": 90.0}]
    netz = track_mesh.bauen(strecke)
    _, _, gier_rad = netz.start_positionen[0]
    assert gier_rad == pytest.approx(math.pi / 2.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Laenge der Mittellinie
# ---------------------------------------------------------------------------


def test_laenge_der_kreisstrecke_entspricht_umfang():
    radius_px = 500.0
    strecke = _kreis_strecke(radius_px, n=360)
    netz = track_mesh.bauen(strecke)
    erwartet = 2.0 * math.pi * radius_px * M_PER_PX
    assert netz.laenge_m == pytest.approx(erwartet, rel=1e-4)


# ---------------------------------------------------------------------------
# Echte Strecken
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ECHTE_STRECKEN)
def test_echte_strecke_laedt_ohne_fehler_und_liefert_plausible_laenge(name):
    pfad = DATA_DIR / f"{name}.json"
    netz = track_mesh.aus_datei(pfad)

    assert netz.band("fahrbahn") is not None
    assert netz.band("randstein_links") is not None
    assert netz.band("randstein_rechts") is not None
    assert netz.band("untergrund") is not None

    # Alle Testrennstrecken sind mehrere hundert Meter bis wenige Kilometer
    # lang -- 50 m .. 20 km deckt das grosszuegig ab und erwischt trotzdem
    # eine kaputte Umrechnung (z.B. vergessene M_PER_PX-Multiplikation).
    assert 50.0 < netz.laenge_m < 20_000.0


def test_oval_strecke_hat_die_erwartete_breite():
    netz = track_mesh.aus_datei(DATA_DIR / "oval.json")
    fahrbahn = netz.band("fahrbahn")
    erwartete_breite_m = 300.0 * M_PER_PX  # track_width aus oval.json
    n_ringe = len(fahrbahn.positionen) // 2
    for i in (0, n_ringe // 3, n_ringe // 2, n_ringe - 1):
        links = fahrbahn.positionen[2 * i]
        rechts = fahrbahn.positionen[2 * i + 1]
        breite = np.linalg.norm(links - rechts)
        assert breite == pytest.approx(erwartete_breite_m, rel=1e-6)
