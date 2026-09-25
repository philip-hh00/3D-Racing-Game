"""Realismus Runde 2, Strang G: Nachbearbeitung, Reifenspuren, Grafikstufen.

Geprüft wird an echten Bildern aus einem eigenständigen OpenGL-Kontext (ohne
Fenster), wo es um Pixel geht, und ohne Kontext, wo es um Regeln geht:
welche Stufe eine Grafikkarte bekommt, wann ein Reifen rutscht, was das
Profil speichert, was die Einstellungsseite aus einem Regler macht.
"""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from src.render3d import grafik, reifenspuren


@pytest.fixture(autouse=True)
def _stufe_zuruecksetzen():
    vorher = grafik.aktuell()
    yield
    grafik._aktuell = vorher


# ---------------------------------------------------------------------------
# Regeln ohne OpenGL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, stufe", [
    ("NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2", "hoch"),
    ("Intel(R) UHD Graphics 620", "niedrig"),
    ("Intel(R) Iris(R) Xe Graphics", "niedrig"),
    ("AMD Radeon(TM) Graphics", "niedrig"),
    ("AMD Radeon Vega 8 Graphics", "niedrig"),
    ("NVIDIA GeForce GTX 1050 Ti/PCIe/SSE2", "niedrig"),
    ("NVIDIA GeForce MX450/PCIe/SSE2", "niedrig"),
    ("Radeon RX 580 Series", "mittel"),
    ("NVIDIA GeForce GTX 1660 SUPER/PCIe/SSE2", "mittel"),
    ("Intel(R) Arc(TM) A770 Graphics", "hoch"),
    ("AMD Radeon RX 7900 XTX", "hoch"),
    ("llvmpipe (LLVM 15.0.7, 256 bits)", "niedrig"),
    ("", "mittel"),
    (None, "mittel"),
])
def test_erster_start_waehlt_die_stufe_nach_der_grafikkarte(name, stufe):
    assert grafik.stufe_fuer_grafikkarte(name) == stufe


def test_geradeaus_rutscht_nichts():
    assert reifenspuren.reifenschlupf((30.0, 0.0), 0.0) == (0.0, 0.0)


def test_quer_zur_fahrtrichtung_rutscht_hinten_mehr():
    vorn, hinten = reifenschlupf_quer = reifenspuren.reifenschlupf((20.0, 8.0), 0.0)
    assert hinten == pytest.approx(1.0)
    assert 0.0 < vorn < hinten, reifenschlupf_quer


def test_vollbremsung_blockiert_vorn():
    vorn, hinten = reifenspuren.reifenschlupf((25.0, 0.0), 0.0, laengs_m_s2=-12.0, bremse=1.0)
    assert vorn > 0.9 and hinten > 0.5
    # Leichtes Bremsen hinterlässt nichts.
    assert reifenspuren.reifenschlupf((25.0, 0.0), 0.0, laengs_m_s2=-4.0, bremse=1.0) == (0.0, 0.0)


def test_durchdrehen_nur_an_der_angetriebenen_achse():
    vorn, hinten = reifenspuren.reifenschlupf((2.0, 0.0), 0.0, gas=1.0, antrieb="rwd")
    assert hinten > 0.3 and vorn == 0.0
    vorn, hinten = reifenspuren.reifenschlupf((2.0, 0.0), 0.0, gas=1.0, antrieb="fwd")
    assert vorn > 0.3 and hinten == 0.0
    # Bei Tempo dreht nichts mehr durch.
    assert reifenspuren.reifenschlupf((30.0, 0.0), 0.0, gas=1.0) == (0.0, 0.0)


def test_die_seite_macht_aus_einem_regler_eine_eigene_stufe(monkeypatch):
    from src.states.menu import settings_page
    werte = grafik.als_dict(grafik.STUFEN["mittel"])
    assert settings_page._grafik_stufe_erkennen(werte) == "mittel"
    werte["ssao"] = 2
    assert settings_page._grafik_stufe_erkennen(werte) == "eigen"
    # Jedes Feld aus grafik.py hat einen Regler.
    felder = {f for f, _b, _o in settings_page._grafik_regler()}
    assert felder == set(grafik.als_dict()) - {"stufe"}


def test_profil_speichert_die_grafik(tmp_path, monkeypatch):
    from src.core import profile
    monkeypatch.setattr(profile, "_profile_path", lambda: str(tmp_path / "profil.json"))
    p = profile.Profile(username="probe")
    assert p.grafik is None                   # erster Start: noch nichts gewählt
    grafik.stufe_setzen("niedrig")
    grafik.setzen(bloom=True)
    p.grafik = grafik.als_dict()
    p.save()
    geladen = profile.Profile.load()
    assert geladen.grafik["stufe"] == "eigen" and geladen.grafik["bloom"] is True
    assert grafik.aus_dict(geladen.grafik).schatten_px == grafik.STUFEN["niedrig"].schatten_px


def test_erster_start_legt_die_erkannte_stufe_ab(monkeypatch):
    from src.core import display, profile
    p = profile.Profile()
    monkeypatch.setattr(profile, "current", lambda: p)
    monkeypatch.setattr(p, "save", lambda: None)

    class Kontext:
        info = {"GL_RENDERER": "Intel(R) UHD Graphics 630"}

    assert display.grafik_einrichten(Kontext()) == "niedrig"
    assert p.grafik["stufe"] == "niedrig"
    # Beim zweiten Start gilt das Profil, nicht mehr die Karte.
    p.grafik["stufe"], p.grafik["ssao"] = "eigen", 2
    Kontext.info = {"GL_RENDERER": "NVIDIA GeForce RTX 5090"}
    display.grafik_einrichten(Kontext())
    assert grafik.aktuell().ssao == 2 and grafik.aktuell().stufe == "eigen"


# ---------------------------------------------------------------------------
# Mit OpenGL
# ---------------------------------------------------------------------------

moderngl = pytest.importorskip("moderngl")


@pytest.fixture(scope="module")
def ctx():
    try:
        kontext = moderngl.create_standalone_context()
    except Exception as fehler:                      # pragma: no cover - Treiber
        pytest.skip(f"Kein OpenGL-Kontext: {fehler}")
    yield kontext
    kontext.release()


def _hdr_bild(ctx, nb, einstellung, farbe, groesse=(64, 48), ausschnitt=None, ziel=None):
    """Eine Fläche in HDR-Farbe durch die Kette schicken; Pixel des Ziels."""
    ziel = ziel or ctx.simple_framebuffer(groesse, components=4)
    ziel.use()
    ctx.viewport = ausschnitt or (0, 0, *groesse)
    nb.beginnen(np.eye(4), (0.0, 0.0, 0.0), einstellung)
    ctx.clear(*farbe, 1.0)
    nb.abschliessen(1.0)
    roh = np.frombuffer(ziel.read(components=3), dtype=np.uint8)
    return roh.reshape(ziel.size[1], ziel.size[0], 3), ziel


@pytest.mark.parametrize("stufe", ["niedrig", "mittel", "hoch", "ultra"])
def test_hdr_wird_abgebildet_statt_abgeschnitten(ctx, stufe):
    """Weiß mal acht ist nach ACES hell, aber nicht die Grenze aller Kanäle,
    und Grau bleibt Grau — in jeder Stufe, ohne NaN."""
    from src.render3d.nachbearbeitung import Nachbearbeitung
    nb = Nachbearbeitung(ctx)
    g = grafik.STUFEN[stufe]
    hell, _ = _hdr_bild(ctx, nb, g, (8.0, 8.0, 8.0))
    mitte = hell[20:28, 28:36].mean()
    assert 235 < mitte <= 255
    grau, _ = _hdr_bild(ctx, nb, g, (0.18, 0.18, 0.18))
    wert = grau[20:28, 28:36].mean(axis=(0, 1))
    assert 90 < wert.mean() < 190, wert
    assert np.ptp(wert) < 6, "Grau hat einen Farbstich bekommen"
    nb.freigeben()


def test_jeder_ausschnitt_bekommt_nur_sein_bild(ctx):
    """Splitscreen: zwei Ausschnitte in einem Ziel, jeder mit eigener Farbe."""
    from src.render3d.nachbearbeitung import Nachbearbeitung
    nb = Nachbearbeitung(ctx)
    ziel = ctx.simple_framebuffer((80, 40), components=4)
    ziel.use()
    ctx.viewport = (0, 0, 80, 40)
    ctx.clear(0.0, 0.0, 0.0, 1.0)
    g = grafik.STUFEN["hoch"]
    _hdr_bild(ctx, nb, g, (1.0, 0.05, 0.05), ausschnitt=(0, 0, 40, 40), ziel=ziel)
    ctx.scissor = (40, 0, 40, 40)
    bild, _ = _hdr_bild(ctx, nb, g, (0.05, 0.05, 1.0), ausschnitt=(40, 0, 40, 40), ziel=ziel)
    ctx.scissor = None
    links, rechts = bild[15:25, 5:35].mean(axis=(0, 1)), bild[15:25, 45:75].mean(axis=(0, 1))
    assert links[0] > links[2] * 3, links
    assert rechts[2] > rechts[0] * 3, rechts
    nb.freigeben()


def test_welt_in_kleinerer_aufloesung_fuellt_trotzdem_das_ziel(ctx):
    from src.render3d.nachbearbeitung import Nachbearbeitung
    nb = Nachbearbeitung(ctx)
    g = grafik.Grafik(aufloesung_skala=0.5, kantenglaettung="fxaa", ssao=0, bloom=False)
    bild, _ = _hdr_bild(ctx, nb, g, (0.5, 0.5, 0.5), groesse=(100, 60))
    assert nb._saetze and next(iter(nb._saetze)).__getitem__(0) == (50, 30)
    assert bild.min() > 60, "Ränder des Ziels blieben leer"
    nb.freigeben()


def Fahrzeugstand(**werte):
    """Wie ``rennszene.Fahrzeugstand`` — die Spuren lesen nur Zahlen daraus."""
    grund = dict(entfaerbt=False, schlupf_vorn=0.0, schlupf_hinten=0.0)
    grund.update(werte)
    return SimpleNamespace(**grund)


def test_spuren_landen_im_ringpuffer_und_laufen_ueber(ctx):
    spuren = reifenspuren.Reifenspuren(ctx, stuecke=50, teilchen=32)
    raeder = lambda _s: reifenspuren.ERSATZRAEDER
    for i in range(80):
        stand = Fahrzeugstand(kennung=1, schluessel="x", pos_m=np.array([i * 0.5, 0.0, 0.0]),
                              gierwinkel_rad=0.0, schlupf_vorn=1.0, schlupf_hinten=1.0)
        spuren.fortschreiben([stand], raeder, 1 / 60)
    assert spuren.belegt == 50, "der Ring hat eine feste Größe"
    assert spuren.teilchen_aktiv > 0, "rutschende Hinterräder qualmen"
    # Ohne Schlupf kommt nichts mehr dazu, und leeren setzt alles zurück.
    kopf = spuren._kopf
    stand = Fahrzeugstand(kennung=1, schluessel="x", pos_m=np.array([80.0, 0.0, 0.0]),
                          gierwinkel_rad=0.0)
    for _ in range(3):
        spuren.fortschreiben([stand], raeder, 1 / 60)
    spuren.fortschreiben([stand], raeder, 1 / 60)
    assert spuren._kopf in (kopf, (kopf + 4) % 50)   # höchstens die Endstücke
    spuren.leeren()
    assert spuren.belegt == 0 and spuren.teilchen_aktiv == 0
    spuren.freigeben()


def test_ein_sprung_beginnt_eine_neue_spur(ctx):
    spuren = reifenspuren.Reifenspuren(ctx, stuecke=100, teilchen=8)
    raeder = lambda _s: ((0.0, 0.0, True),)
    for x in (0.0, 0.5, 1.0, 50.0, 50.5):
        spuren.fortschreiben([Fahrzeugstand(kennung=1, schluessel="x", pos_m=np.array([x, 0.0, 0.0]),
                                            gierwinkel_rad=0.0, schlupf_hinten=1.0)], raeder, 1 / 60)
    daten = np.frombuffer(spuren._vbo.read(), dtype="f4").reshape(-1, 4, 7)[:spuren.belegt]
    laengen = np.linalg.norm(daten[:, 2, :2] - daten[:, 0, :2], axis=1)
    assert laengen.max() < 1.0, "über den Sprung darf kein Streifen gezogen werden"
    spuren.freigeben()
