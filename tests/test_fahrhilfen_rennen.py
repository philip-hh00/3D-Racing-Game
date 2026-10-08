"""Fahrhilfen im Spiel: Profil, Einstellungsseite, Rennen, Ideallinie, Randsteine.

Die Physik der Hilfen steht in ``test_fahrhilfen.py``, die Vibration in
``test_vibration.py``. Hier geht es um die Verdrahtung:

* **Profil:** Standard (alle Hilfen aus), Speichern und Laden, Unsinn im Profil;
* **Einstellungen:** Reiter „Fahrhilfen", gepufferte Werte, Rohwerte statt
  Anzeigetext (auf Englisch derselbe Wert wie auf Deutsch);
* **Rennen:** nur Menschen bekommen Hilfen, die KI nie; Schalter wirken sofort;
  im Splitscreen hat jeder seinen Controller;
* **Ideallinie:** Farben nach dem Zieltempo der KI, ein geschlossenes Band;
* **Randsteine:** wo das Netz einen baut, merkt es auch das Rad.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import spielhilfe  # noqa: E402
from src.core import i18n, profile, sfx  # noqa: E402
from src.core.settings import M_PER_PX  # noqa: E402

GP = os.path.join(_ROOT, "data", "tracks", "gp.json")


@pytest.fixture
def profil(monkeypatch, tmp_path):
    """Ein frisches Profil im Zwischenspeicher; Speichern geht in ein Temp-Verzeichnis."""
    monkeypatch.setattr(profile, "_profile_path", lambda: str(tmp_path / "profile.json"))
    p = profile.Profile(username="Testfahrer")
    monkeypatch.setattr(profile, "_current", p, raising=False)
    return p


@pytest.fixture(autouse=True)
def deutsch_danach():
    yield
    i18n.set_language("de")
    spielhilfe.alles_schliessen()


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------

def test_standard_ist_alles_aus_und_vibration_mittel(profil):
    assert profil.fahrhilfe("abs") is False
    assert profil.fahrhilfe("tc") is False
    assert profil.fahrhilfe("linie") is False
    assert profil.fahrhilfe("vibration") == 2
    assert profil.fahrhilfen == {}                   # nichts gespeichert, was nicht gewaehlt wurde


def test_fahrhilfen_bleiben_nach_dem_neustart(profil):
    profil.set_fahrhilfe("abs", True)
    profil.set_fahrhilfe("linie", True)
    profil.set_fahrhilfe("vibration", 3)
    neu = profile.Profile.load()
    assert neu.fahrhilfe("abs") is True
    assert neu.fahrhilfe("tc") is False
    assert neu.fahrhilfe("linie") is True
    assert neu.fahrhilfe("vibration") == 3


def test_altes_profil_ohne_fahrhilfen_laedt_mit_standard(profil, tmp_path):
    from src.core import tresor
    tresor.schreiben(str(tmp_path / "profile.json"), json.dumps({"username": "Alt", "best_laps": {}}))
    p = profile.Profile.load()
    assert p.username == "Alt"
    assert p.fahrhilfe("abs") is False and p.fahrhilfe("vibration") == 2


@pytest.mark.parametrize("unsinn", [
    {"abs": "ja", "tc": 1, "linie": None, "vibration": "stark"},
    {"vibration": 99}, {"vibration": -3}, {"vibration": True}, {"vibration": 1.5},
    {"unbekannt": True},
])
def test_unsinn_im_profil_ergibt_den_standard(profil, unsinn):
    profil.fahrhilfen = dict(unsinn)
    assert profil.fahrhilfe("abs") is False
    assert profil.fahrhilfe("tc") is False
    assert profil.fahrhilfe("linie") is False
    assert 0 <= profil.fahrhilfe("vibration") <= 3
    if unsinn.get("vibration") == 99:
        assert profil.fahrhilfe("vibration") == 3
    if unsinn.get("vibration") == -3:
        assert profil.fahrhilfe("vibration") == 0
    if unsinn == {"unbekannt": True}:
        assert profil.fahrhilfe("vibration") == 2


def test_unbekannte_hilfe_wird_nicht_gespeichert(profil):
    profil.set_fahrhilfe("lenkhilfe", True)
    assert "lenkhilfe" not in profil.fahrhilfen


def test_profil_ohne_fahrhilfen_schluessel_schreibt_leeres_objekt(profil, tmp_path):
    profil.save()
    from src.core import tresor
    assert json.loads(tresor.lesen(str(tmp_path / "profile.json")))["fahrhilfen"] == {}


# ---------------------------------------------------------------------------
# Einstellungen
# ---------------------------------------------------------------------------

@pytest.fixture
def seite(monkeypatch, profil):
    from src.states.menu.settings_page import SettingsPage
    monkeypatch.setattr(sfx, "spielen", lambda *a, **k: None)
    s = SettingsPage()
    s.enter(type("Schale", (), {"state_machine": None})())
    s.cat = s.categories.index("Fahrhilfen")
    s._build_content()
    return s


def _regler(seite):
    return {w.action: w for w in seite._content_group.widgets}


def test_reiter_fahrhilfen_gibt_es_im_spiel_und_im_pausenmenue(seite):
    from src.states.menu.settings_page import SettingsPage
    assert "Fahrhilfen" in seite.categories
    pause = SettingsPage()
    pause.is_pause_context = True
    assert "Fahrhilfen" in pause.categories


def test_vier_regler_in_der_richtigen_stellung(seite, profil):
    r = _regler(seite)
    assert set(r) == {"fh_abs", "fh_tc", "fh_linie", "fh_vibration"}
    assert [r[a].index for a in ("fh_abs", "fh_tc", "fh_linie")] == [0, 0, 0]
    assert r["fh_vibration"].index == 2 and len(r["fh_vibration"].options) == 4


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_regler_stellen_gepuffert_und_speichern(seite, profil, sprache):
    i18n.set_language(sprache)
    seite._build_content()
    r = _regler(seite)
    r["fh_abs"].index = 1
    r["fh_tc"].index = 1
    r["fh_vibration"].index = 3
    for a in ("fh_abs", "fh_tc", "fh_vibration"):
        seite._dispatch(a)
    assert profil.fahrhilfen == {}                          # noch nicht gespeichert
    assert seite._pending["fahrhilfen"] == {"abs": True, "tc": True, "vibration": 3}
    assert seite._dirty
    assert seite._apply_pending()
    assert profil.fahrhilfe("abs") and profil.fahrhilfe("tc") and not profil.fahrhilfe("linie")
    assert profil.fahrhilfe("vibration") == 3
    # nach dem Speichern zeigen die Regler den gespeicherten Stand
    r = _regler(seite)
    assert r["fh_abs"].index == 1 and r["fh_linie"].index == 0 and r["fh_vibration"].index == 3


def test_verwerfen_laesst_das_profil_unberuehrt(seite, profil):
    r = _regler(seite)
    r["fh_linie"].index = 1
    seite._dispatch("fh_linie")
    seite._pending = {}
    seite._build_content()
    assert profil.fahrhilfe("linie") is False
    assert _regler(seite)["fh_linie"].index == 0


def test_vibrationsregler_gibt_eine_probe_auf_den_controllern(seite, monkeypatch):
    from src.core import gamepad
    gesendet = []
    monkeypatch.setattr(gamepad, "device_count", lambda: 2)
    monkeypatch.setattr(gamepad, "rumble", lambda i, t, h, ms: gesendet.append((i, t, h)) or True)
    r = _regler(seite)
    r["fh_vibration"].index = 0
    seite._dispatch("fh_vibration")
    assert gesendet == []                                   # Aus: keine Probe
    r["fh_vibration"].index = 3
    seite._dispatch("fh_vibration")
    assert {g[0] for g in gesendet} == {0, 1} and all(g[1] > 0 for g in gesendet)


# ---------------------------------------------------------------------------
# Im Rennen
# ---------------------------------------------------------------------------

def _hilfen(profil, **werte):
    profil.fahrhilfen = dict(werte)


def test_ohne_gewaehlte_hilfe_hat_kein_auto_eine(profil):
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=4)
    rennen.update(1 / 60)
    assert rennen.player.fahrhilfen is None
    assert all(ki.fahrhilfen is None for ki in rennen.ai_vehicles)


def test_nur_der_mensch_bekommt_hilfen_nie_die_ki(profil):
    _hilfen(profil, abs=True, tc=True)
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=4)
    rennen.update(1 / 60)
    fh = rennen.player.fahrhilfen
    assert fh is not None and fh.abs_an and fh.tc_an
    assert all(ki.fahrhilfen is None for ki in rennen.ai_vehicles)
    for _ in range(120):
        rennen.update(1 / 60)
    assert all(ki.fahrhilfen is None for ki in rennen.ai_vehicles)


def test_schalter_wirken_im_laufenden_rennen_und_einzeln(profil):
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=3)
    rennen.update(1 / 60)
    assert rennen.player.fahrhilfen is None
    _hilfen(profil, tc=True)
    rennen.update(1 / 60)
    assert rennen.player.fahrhilfen.tc_an and not rennen.player.fahrhilfen.abs_an
    _hilfen(profil, abs=True)
    rennen.update(1 / 60)
    assert rennen.player.fahrhilfen.abs_an and not rennen.player.fahrhilfen.tc_an
    _hilfen(profil)                                          # alles wieder aus
    rennen.update(1 / 60)
    assert rennen.player.fahrhilfen is None


def test_ki_runden_sind_mit_und_ohne_hilfe_des_menschen_gleich(profil):
    """Die Hilfe gehoert dem Menschen: das Feld faehrt davon unberuehrt."""
    endstaende = []
    for hilfe in (False, True):
        _hilfen(profil, abs=hilfe, tc=hilfe)
        rennen, _sm = spielhilfe.rennen_bauen("oval", feld=3, ki_fahrzeug="rookie")
        for _ in range(60 * 14):
            rennen.update(1 / 60)
        endstaende.append([(round(k.body.position.x, 4), round(k.body.position.y, 4))
                           for k in rennen.ai_vehicles])
        spielhilfe.alles_schliessen()
    # Der Mensch steht im Gitter und stoert nicht (Zeitfahren-aehnlich): gleiche Stellung.
    assert endstaende[0] == endstaende[1]


def test_vibration_je_mensch_auf_seinem_controller(profil):
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=4)
    rennen.update(1 / 60)
    assert set(rennen._hilfen.vibration) == {rennen.player.id}
    assert rennen._hilfen.vibration[rennen.player.id].pad_index == 0     # Tastatur + erster Controller


def test_splitscreen_zwei_menschen_zwei_pads(profil, monkeypatch):
    from src.core import race_setup
    monkeypatch.setattr(race_setup.RaceSetup, "is_multiplayer",
                        property(lambda self: True, lambda self, wert: None))

    def zwei_pads():
        race_setup._current = race_setup.RaceSetup()
        aufbau = race_setup.current()
        aufbau.player2_vehicle = "rookie"
        aufbau.p1_input, aufbau.p2_input = "pad0", "pad1"

    monkeypatch.setattr(spielhilfe, "spielstand_zuruecksetzen", zwei_pads)
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=4)
    spielhilfe_hilfen = rennen._hilfen
    assert rennen._split
    pads = {vid: v.pad_index for vid, v in spielhilfe_hilfen.vibration.items()}
    assert pads == {rennen.player.id: 0, rennen.player2.id: 1}


def test_stoss_trifft_nur_den_betroffenen_menschen(profil, monkeypatch):
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=4)
    gesendet = []
    v = rennen._hilfen.vibration[rennen.player.id]
    v.pad_index = 0
    v._ausgabe = lambda i, t, h, ms: gesendet.append((i, t, h)) or True
    rennen._hilfen.stoss(rennen.ai_vehicles[0], 9000.0)       # ein KI-Auto: nichts
    v.fortschreiben(1 / 60)
    assert gesendet == []
    rennen._hilfen.stoss(rennen.player, 9000.0)
    v.fortschreiben(1 / 60)
    assert gesendet and gesendet[0][1] > 0.5


def test_pause_und_ende_stoppen_die_vibration(profil):
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=3)
    gestoppt = []
    v = rennen._hilfen.vibration[rennen.player.id]
    v.pad_index = 0
    v._gesendet = (0.5, 0.5)
    v._stopp = gestoppt.append
    rennen.paused = True
    rennen.update(1 / 60)
    assert gestoppt == [0]
    v._gesendet = (0.5, 0.5)
    rennen.paused = False
    rennen.exit()
    assert gestoppt == [0, 0]
    spielhilfe._offen.clear()


def test_vibration_aus_im_profil_schweigt_im_rennen(profil):
    _hilfen(profil, vibration=0)
    rennen, _sm = spielhilfe.rennen_bauen("oval", feld=3)
    gesendet = []
    v = rennen._hilfen.vibration[rennen.player.id]
    v.pad_index = 0
    v._ausgabe = lambda *a: gesendet.append(a) or True
    rennen.update(1 / 60)
    rennen._hilfen.stoss(rennen.player, 9000.0)
    for _ in range(30):
        rennen.update(1 / 60)
    assert gesendet == []


# ---------------------------------------------------------------------------
# Ideallinie
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def gp_linie():
    from src.entities.vehicle_factory import VehicleFactory
    from src.physics.physics_world import PhysicsWorld
    from src.track.track import Track
    spielhilfe.fahrzeuge_laden()
    welt = PhysicsWorld()
    strecke = Track(GP, welt.space)
    cfg = VehicleFactory.get_config("rookie")
    from src.ai import ideallinie
    return ideallinie.fuer_fahrzeug(strecke, cfg), strecke, cfg


def test_ideallinie_ist_ein_geschlossener_ring_mit_allen_drei_farben(gp_linie):
    linie, _strecke, _cfg = gp_linie
    n = len(linie.klasse)
    assert n > 300 and linie.xy_m.shape == (n, 2)
    assert set(np.unique(linie.klasse)) == {0, 1, 2}
    schritt = np.hypot(*(np.roll(linie.xy_m, -1, axis=0) - linie.xy_m).T)
    assert schritt.max() < 3.0 and schritt.min() > 0.2        # keine Spruenge, auch am Ringschluss
    assert linie.laenge_m == pytest.approx(linie.bogen_m[-1] + linie.bogen_m[1], rel=0.01)


def test_ideallinie_bleibt_auf_der_fahrbahn(gp_linie):
    linie, strecke, _cfg = gp_linie
    from src.ai.strecke_frenet import StreckeFrenet
    mitte = [(p[0], p[1]) for p in strecke.centerline]
    frenet = StreckeFrenet(mitte, float(strecke.track_width))
    hinweis = None
    for x, y in linie.xy_m[::7]:
        _s, d, hinweis = frenet.sd(x / M_PER_PX, y / M_PER_PX)
        assert abs(d) < frenet.halb - 8.0                      # ein Stueck vor der Kante, auch vor dem Randstein


def test_rot_dort_wo_das_zieltempo_faellt_gruen_wo_es_steigt(gp_linie):
    linie, _strecke, _cfg = gp_linie
    v = linie.tempo_ms
    dv = np.roll(v, -1) - v
    rot = linie.klasse == 2
    gruen = linie.klasse == 0
    # Mehrheitlich so, nicht im Einzelnen (Vorlauf und Glaettung verschieben Raender).
    assert dv[rot].mean() < 0.0 < dv[gruen].mean()
    assert v[rot].mean() > v[linie.klasse == 1].mean() * 0.8   # Rot liegt vor Kurven, nicht in ihnen


def test_ohne_bremszonen_keine_rote_linie():
    from src.ai import ideallinie
    v = np.full(400, 50.0 / M_PER_PX)                           # gleichmaessig schnell
    k = ideallinie.klassen_aus_profil(v, 1.0 / M_PER_PX, 100.0)
    assert (k == ideallinie.GRUEN).all()


def test_bremszone_wird_rot_und_der_vorlauf_beginnt_davor():
    from src.ai import ideallinie
    s = np.arange(600) * (1.0 / M_PER_PX)                      # 1 m Schritte, in px
    v = np.full(600, 60.0 / M_PER_PX)
    a_brems = 100.0                                            # px/s^2
    # ab Punkt 300 faellt das Tempo mit voller Bremsfaehigkeit auf die Haelfte
    for k in range(300, 400):
        v[k] = np.sqrt(max(v[k - 1] ** 2 - 2 * a_brems * (1.0 / M_PER_PX), (30.0 / M_PER_PX) ** 2))
    v[400:] = v[399]
    klasse = ideallinie.klassen_aus_profil(v, 1.0 / M_PER_PX, a_brems)
    assert klasse[350] == ideallinie.ROT
    erstes_rot = int(np.argmax(klasse == ideallinie.ROT))
    assert 285 <= erstes_rot < 300                             # etwas vor dem Tempoabfall
    assert klasse[100] == ideallinie.GRUEN


def test_band_hat_pro_punkt_zwei_ecken_und_gueltige_indizes(gp_linie):
    linie, _s, _c = gp_linie
    from src.render3d.ideallinie import band_bauen, HOEHE_M, BREITE_M
    daten, indizes = band_bauen(linie.xy_m, linie.bogen_m, linie.farben, linie.laenge_m)
    n = len(linie.xy_m)
    assert daten.shape == ((n + 1) * 2, 8) and daten.dtype == np.float32
    assert indizes.max() == (n + 1) * 2 - 1 and len(indizes) == n * 6
    assert np.allclose(daten[:, 2], HOEHE_M)
    breite = np.hypot(daten[0::2, 0] - daten[1::2, 0], daten[0::2, 1] - daten[1::2, 1])
    assert breite.mean() == pytest.approx(BREITE_M, rel=0.02)
    assert np.all(np.diff(daten[0::2, 6]) > 0)                  # Weg waechst ueber die Naht hinweg


def test_band_ueber_dem_boden_gegen_z_fighting():
    from src.render3d import ideallinie as r
    assert 0.005 <= r.HOEHE_M <= 0.05      # sichtbar ueber dem Asphalt, unter den Randsteinen (3,5 cm)


# ---------------------------------------------------------------------------
# Randsteine
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def randsteine():
    from src.physics.randstein_ort import Randsteine
    with open(GP, encoding="utf-8") as f:
        return Randsteine.aus_streckendaten(json.load(f))


def _stelle(r, i, quer_px):
    """Ein Punkt, quer_px links (+) von der Mittellinie bei Segment i, mit Richtung."""
    f = r.frenet
    p = f.punkte[i] + f.normale[i] * quer_px
    return float(p[0]), float(p[1]), math.atan2(float(f.seg_dir[i][1]), float(f.seg_dir[i][0]))


def test_randstein_wo_das_netz_einen_baut(randsteine):
    r = randsteine
    assert r.links.any() and r.rechts.any() and not r.links.all()
    i = int(np.flatnonzero(r.links)[len(np.flatnonzero(r.links)) // 2])
    kante = r.halbe_breite_px
    x, y, gier = _stelle(r, i, kante - 8.0)               # aeusserster Meter, links
    assert r.auf_randstein(x, y, gier)
    x, y, gier = _stelle(r, i, 0.0)                       # Fahrbahnmitte
    assert not r.auf_randstein(x, y, gier)


def test_kein_randstein_wo_keiner_liegt(randsteine):
    r = randsteine
    frei = np.flatnonzero(~r.links)
    i = int(frei[len(frei) // 2])
    x, y, gier = _stelle(r, i, r.halbe_breite_px - 8.0)
    assert not r.auf_randstein(x, y, gier)


def test_randstein_seite_stimmt(randsteine):
    r = randsteine
    nur_links = np.flatnonzero(r.links & ~r.rechts)
    i = int(nur_links[len(nur_links) // 2])
    x, y, gier = _stelle(r, i, -(r.halbe_breite_px - 8.0))  # rechts, wo hier keiner liegt
    assert not r.auf_randstein(x, y, gier)
    x, y, gier = _stelle(r, i, r.halbe_breite_px - 8.0)
    assert r.auf_randstein(x, y, gier)


def test_randstein_abfrage_mit_merkhilfe_gibt_dasselbe(randsteine):
    r = randsteine
    i = int(np.flatnonzero(r.rechts)[5])
    x, y, gier = _stelle(r, i, -(r.halbe_breite_px - 8.0))
    erst = r.auf_randstein(x, y, gier, schluessel=7)
    zweit = r.auf_randstein(x, y, gier, schluessel=7)         # mit dem gemerkten Segment
    ohne = r.auf_randstein(x, y, gier)
    assert erst == zweit == ohne is True


def test_schraeges_auto_ragt_weiter_hinaus(randsteine):
    r = randsteine
    i = int(np.flatnonzero(r.links)[len(np.flatnonzero(r.links)) // 2])
    quer = r.halbe_breite_px - 14.0                       # knapp ausserhalb des Meters
    x, y, gier = _stelle(r, i, quer)
    gerade = r.auf_randstein(x, y, gier)
    schraeg = r.auf_randstein(x, y, gier + math.radians(70))
    assert schraeg or not gerade                          # schraeg zaehlt mindestens so oft
