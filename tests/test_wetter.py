"""Wetter je Rennen: Trocken oder Regen (``src/render3d/wetter.py``).

Geprüft wird, was sich ohne Bildvergleich festnageln lässt:

* **Trocken ist die alte Welt.** Dasselbe Config-Objekt, dieselbe Bremse, kein
  Shaderzweig, kein Teilchen; ein gezeichnetes Bild ist mit und ohne den
  Parameter Bit für Bit gleich. (Dass es auch Pixel für Pixel dem Stand vor der
  Änderung entspricht, wurde einmal an acht Standbildern gegen ihn verglichen.)
* **Regen nimmt allen Haftung:** Menschen und KI, Quer- und Längsrichtung und
  Bremse; die Fahrzeugdateien bleiben unberührt.
* **Die KI passt sich an:** niedrigeres Kurventempo, früheres Bremsen, und sie
  kommt trotzdem sauber ins Ziel.
* **Lobby, Server und Profil:** das Feld ist optional (fehlt es, ist es
  Trocken), der Host verteilt es, der Gast liest es, das Profil merkt es.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import types

import numpy as np
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from src.render3d import grafik, wetter  # noqa: E402
from src.render3d.wetter import REGEN, TROCKEN  # noqa: E402


# ---------------------------------------------------------------------------
# Namen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("roh, erwartet", [
    ("Trocken", "Trocken"), ("Regen", "Regen"), ("rain", "Regen"), ("  REGEN ", "Regen"),
    ("dry", "Trocken"), (None, "Trocken"), ("", "Trocken"), (4, "Trocken"),
    ("Schnee", "Trocken"), (["Regen"], "Trocken"),
])
def test_namen_werden_normiert_und_fehlendes_ist_trocken(roh, erwartet):
    assert wetter.normiere(roh) == erwartet


def test_jeder_name_hat_eine_vorgabe():
    assert set(wetter.NAMEN) == set(wetter.VORGABEN)
    for n in wetter.NAMEN:
        assert wetter.vorgabe(n).name == n
    assert wetter.vorgabe("unbekannt") is TROCKEN


# ---------------------------------------------------------------------------
# Trocken bleibt, wie es war
# ---------------------------------------------------------------------------
def test_trocken_aendert_keinen_wert():
    assert not TROCKEN.aktiv and REGEN.aktiv
    werte = dict(sonne_farbe=(3.0, 2.8, 2.6), himmel_helligkeit=1.0, nebel_farbe=(0.7, 0.8, 0.9),
                 nebel_dichte=0.004, boden_farbe=(0.2, 0.22, 0.18), himmel_zenit=(0.3, 0.4, 0.8),
                 himmel_horizont=(0.7, 0.8, 0.9), belichtung=1.1)
    assert wetter.umgebung_werte(TROCKEN, werte) == werte
    assert wetter.nass_werte(TROCKEN) == ((0.0, 1.0, 1.0, 1.0), (0.0, 0.0, 0.0, 0.0))
    s = np.array([0.3, 0.4, 0.86])
    assert np.allclose(wetter.sonne_gedrueckt(s, TROCKEN), s / np.linalg.norm(s))


def test_trocken_gibt_dieselbe_config_zurueck():
    from tests.ki_hilfe import config
    cfg = config("rookie")
    assert wetter.wirksame_config(cfg, "Trocken") is cfg
    assert wetter.wirksame_config(cfg, None) is cfg
    assert wetter.wirksame_config(cfg, "Quatsch") is cfg


def test_fahrzeug_ohne_wetter_faehrt_mit_seiner_config():
    import pymunk
    from tests.ki_hilfe import config
    from src.entities.vehicle import Vehicle
    cfg = config("rookie")
    v = Vehicle(1, cfg, (0.0, 0.0), 0.0, pymunk.Space())
    assert v.wetter == "Trocken"
    assert v.wirk_config is cfg
    assert v.brakes.brake_force == cfg.brake_force


def test_die_fahrzeugdateien_bleiben_unberuehrt():
    """Die JSON-Dateien sind für Online geprüfsummt; das Wetter rechnet nur im Speicher."""
    from tests.ki_hilfe import config
    cfg = config("supercar")
    grip0, brems0 = cfg.grip, cfg.brake_force
    nass = wetter.wirksame_config(cfg, "Regen")
    assert nass is not cfg
    assert (cfg.grip, cfg.brake_force) == (grip0, brems0)
    with open(os.path.join(_ROOT, "data", "vehicles", "supercar.json"), encoding="utf-8") as fh:
        assert json.load(fh)["physics"]["grip"] == grip0


# ---------------------------------------------------------------------------
# Regen: weniger Haftung für alle
# ---------------------------------------------------------------------------
def test_regen_senkt_grip_und_bremse():
    from tests.ki_hilfe import config
    cfg = config("rookie")
    nass = wetter.wirksame_config(cfg, "Regen")
    assert nass.grip == pytest.approx(cfg.grip * 0.8)
    assert nass.brake_force == pytest.approx(cfg.brake_force * wetter.BREMS_FAKTOR["Regen"])
    assert nass.mass == cfg.mass and nass.engine_power == cfg.engine_power


@pytest.mark.parametrize("art", ["mensch", "ki"])
def test_physik_bekommt_im_regen_weniger_haftung(art, tmp_path):
    """Menschen und KI geben der Physik denselben niedrigeren Wert."""
    import pymunk
    from tests import ki_hilfe
    from src.entities.vehicle_factory import VehicleFactory
    from src.ai.stufen import stufe
    cfg_key = "rookie"
    erwartet = ki_hilfe.config(cfg_key).grip

    def fahrzeug(regen: bool):
        space = pymunk.Space()
        if art == "mensch":
            v = VehicleFactory.create_player_vehicle(cfg_key, 1, (0.0, 0.0), 0.0, space)
        else:
            track = ki_hilfe.strecke_laden("oval", space)
            v = VehicleFactory.create_ai_vehicle(cfg_key, 1, (0.0, 0.0), 0.0, space, track, stufe("expert"))
        if regen:
            v.wetter_setzen("Regen")
        gesehen = {}
        for name in ("apply_lateral_friction", "apply_drive_force"):
            orig = getattr(v.physics, name)

            def spion(*a, _o=orig, _n=name, **k):
                gesehen[_n] = k.get("grip", a[0] if _n == "apply_lateral_friction" else k.get("grip"))
                return _o(*a, **k)
            setattr(v.physics, name, spion)
        v.physics.body.velocity = pymunk.Vec2d(300.0, 0.0)
        v.throttle = 1.0
        v.update(1.0 / 60.0)
        return gesehen

    trocken, nass = fahrzeug(False), fahrzeug(True)
    assert trocken["apply_lateral_friction"] == pytest.approx(erwartet)
    assert trocken["apply_drive_force"] == pytest.approx(erwartet)
    assert nass["apply_lateral_friction"] == pytest.approx(erwartet * 0.8)
    assert nass["apply_drive_force"] == pytest.approx(erwartet * 0.8)


def _bremsweg(regen: bool, schluessel: str = "supercar") -> float:
    import pymunk
    from src.entities.vehicle_factory import VehicleFactory
    from tests import ki_hilfe
    ki_hilfe.config(schluessel)
    space = pymunk.Space()
    v = VehicleFactory.create_player_vehicle(schluessel, 1, (0.0, 0.0), 0.0, space)
    if regen:
        v.wetter_setzen("Regen")
    v.physics.body.velocity = pymunk.Vec2d(500.0, 0.0)
    dt = 1.0 / 60.0
    for _ in range(600):
        v.throttle, v.brake_input = 0.0, 1.0
        v.update(dt)
        space.step(dt)
        if v.speed < 5.0:
            break
    return v.position[0]


def test_im_regen_ist_der_bremsweg_laenger():
    trocken, nass = _bremsweg(False), _bremsweg(True)
    assert 1.1 < nass / trocken < 1.4, (trocken, nass)


# ---------------------------------------------------------------------------
# Die KI passt sich an
# ---------------------------------------------------------------------------
def test_ki_plan_ist_im_regen_langsamer_und_bremst_frueher():
    import pymunk
    from tests import ki_hilfe
    from src.ai.fahrplan import fahrplan_bauen
    from src.ai.stufen import STUFEN
    track = ki_hilfe.strecke_laden("gp", pymunk.Space())
    cfg = ki_hilfe.config("rookie")
    trocken = fahrplan_bauen(track, cfg, STUFEN["expert"])
    nass = fahrplan_bauen(track, wetter.wirksame_config(cfg, "Regen"), STUFEN["expert"])
    assert trocken is not nass
    assert nass.a_quer == pytest.approx(trocken.a_quer * 0.8)
    assert nass.a_brems < trocken.a_brems
    # nirgends schneller, im Mittel deutlich langsamer
    assert (nass.v_ziel <= trocken.v_ziel + 1e-9).all()
    assert nass.v_ziel.mean() < trocken.v_ziel.mean() * 0.97
    # Kurventempo wie die Wurzel aus dem Haftungsverhältnis, wo die Haftung die Grenze ist
    enge = trocken.v_kurve < trocken.v_kurve.max() * 0.7
    verhaeltnis = nass.v_kurve[enge] / trocken.v_kurve[enge]
    assert 0.85 < float(np.median(verhaeltnis)) <= 0.9


def test_ki_regler_nimmt_die_haftung_des_regens():
    import pymunk
    from tests import ki_hilfe
    from src.entities.vehicle_factory import VehicleFactory
    from src.ai.stufen import stufe
    track = ki_hilfe.strecke_laden("oval", pymunk.Space())
    ki_hilfe.config("rookie")
    ai = VehicleFactory.create_ai_vehicle("rookie", 1, (0.0, 0.0), 0.0, pymunk.Space(), track, stufe("expert"))
    ai.wetter_setzen("Regen")
    ai.controller.vorbereiten()
    assert ai.controller._regler.grip == pytest.approx(ai.config.grip * 0.8)
    assert ai.controller.fahrplan.a_quer == pytest.approx(ai.config.grip * 0.8 * 380.0 * stufe("expert").haftung)


def _ki_messung():
    spec = importlib.util.spec_from_file_location("ki_messung_wetter", os.path.join(_ROOT, "tools", "ki_messung.py"))
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


def test_ki_faehrt_im_regen_langsamer_aber_sauber():
    """Oval, zwei Runden: 4 bis 14 % langsamer, keine Wandberührung, im Ziel."""
    km = _ki_messung()
    pfad = os.path.join(_ROOT, "data", "tracks", "oval.json")
    trocken = km.solo(pfad, "rookie", "expert", runden=2)
    nass = km.solo(pfad, "rookie", "expert", runden=2, wetter="Regen")
    assert trocken["fertig"] and nass["fertig"]
    assert nass["wand"] == 0 and trocken["wand"] == 0
    verhaeltnis = nass["beste"] / trocken["beste"]
    assert 1.04 < verhaeltnis < 1.14, verhaeltnis


def _hilfen_lauf(regen: bool, abs_an: bool, tc_an: bool, schluessel: str):
    """Kleinster Faktor, auf den ABS (Bremse) bzw. TC (Gas) in ein paar Sekunden gehen."""
    import pymunk
    from tests import ki_hilfe
    from src.entities.components.fahrhilfen import Fahrhilfen
    from src.entities.vehicle_factory import VehicleFactory
    ki_hilfe.config(schluessel)
    space = pymunk.Space()
    v = VehicleFactory.create_player_vehicle(schluessel, 1, (0.0, 0.0), 0.0, space)
    if regen:
        v.wetter_setzen("Regen")
    v.fahrhilfen = Fahrhilfen(abs_an=abs_an, tc_an=tc_an)
    dt = 1.0 / 60.0
    kleinste_bremse = kleinstes_gas = 1.0
    if abs_an:
        v.physics.body.velocity = pymunk.Vec2d(500.0, 0.0)
        for i in range(150):
            v.throttle, v.brake_input, v.steer_input = 0.0, 1.0, 1.0 if i < 100 else 0.0
            v.update(dt)
            space.step(dt)
            kleinste_bremse = min(kleinste_bremse, v.bremse_wirksam)
    if tc_an:
        for _ in range(240):
            v.throttle, v.brake_input, v.steer_input = 1.0, 0.0, 0.0
            v.update(dt)
            space.step(dt)
            kleinstes_gas = min(kleinstes_gas, v.gas_wirksam)
    return kleinste_bremse, kleinstes_gas


def test_abs_greift_im_regen_mindestens_so_oft_wie_trocken():
    trocken, _ = _hilfen_lauf(False, True, False, "rookie")
    nass, _ = _hilfen_lauf(True, True, False, "rookie")
    assert nass < 1.0, "ABS nimmt im Regen Bremsdruck weg"
    assert nass <= trocken + 1e-9


def test_traktionskontrolle_greift_im_regen_mindestens_so_oft_wie_trocken():
    _, trocken = _hilfen_lauf(False, False, True, "supercar")
    _, nass = _hilfen_lauf(True, False, True, "supercar")
    assert nass < 1.0, "TC nimmt im Regen Gas weg"
    assert nass <= trocken + 1e-9


# ---------------------------------------------------------------------------
# Regenrauschen
# ---------------------------------------------------------------------------
def test_regenrauschen_ist_eine_nahtlose_beschraenkte_schleife():
    from src.core import sfx, sfx_rennen
    a = sfx_rennen.regenrauschen(sekunden=1.0)
    assert a.shape == (sfx.SR, 2) and a.dtype == np.float32
    assert np.isfinite(a).all() and float(np.abs(a).max()) <= 1.0
    assert float(np.abs(a).mean()) > 0.02, "nicht still"
    # Naht: der Sprung vom Ende zum Anfang ist nicht größer als irgendein anderer
    sprung = float(np.abs(a[0] - a[-1]).max())
    typisch = float(np.percentile(np.abs(np.diff(a, axis=0)), 99.9))
    assert sprung <= typisch * 1.5 + 1e-6
    # links und rechts sind verschieden (Breite)
    assert not np.allclose(a[:, 0], a[:, 1])
    # deterministisch
    assert np.array_equal(a, sfx_rennen.regenrauschen(sekunden=1.0))


# ---------------------------------------------------------------------------
# Himmel, Sonne
# ---------------------------------------------------------------------------
def test_regenhimmel_ist_grau_dunkel_und_ohne_sonnenscheibe():
    h, b = 64, 128
    bild = np.zeros((h, b, 3), dtype=np.float32)
    bild[:32, :, 2] = 0.9                         # blauer Himmel
    bild[:32, :, 0] = 0.3
    bild[10:14, 60:70, :] = 1.0                   # Sonnenscheibe
    graded = wetter.himmel_bild(bild, REGEN)
    assert graded.shape == bild.shape and np.isfinite(graded).all()
    lin = graded ** 2.2
    oben = lin[:32]
    assert float(oben.max()) < 0.75, "keine Sonnenscheibe mehr"
    def saettigung(x):
        return (x.max(axis=2) - x.min(axis=2)).mean() / max(float(x.mean()), 1e-6)
    assert saettigung(oben) < 0.5 * saettigung(bild[:32] ** 2.2), "entsättigt"
    # die Helligkeit des Himmels und der Sonne nimmt ``umgebung_werte`` zurück, nicht das Bild
    assert REGEN.himmel_helligkeit < 1.0 and max(REGEN.sonne_faktor) < 0.5


def test_sonne_steht_bei_regen_hoechstens_so_hoch_wie_die_grenze():
    hoch = np.array([0.1, 0.1, 0.99])
    s = wetter.sonne_gedrueckt(hoch, REGEN)
    assert math.degrees(math.asin(s[2])) == pytest.approx(REGEN.sonne_hoehe_max_grad, abs=0.01)
    assert math.atan2(s[1], s[0]) == pytest.approx(math.atan2(hoch[1], hoch[0]))
    niedrig = np.array([0.9, 0.2, 0.2])
    assert np.allclose(wetter.sonne_gedrueckt(niedrig, REGEN), niedrig / np.linalg.norm(niedrig))


# ---------------------------------------------------------------------------
# Grafikstufen
# ---------------------------------------------------------------------------
def test_grafikstufen_haben_weniger_regen_auf_niedrig():
    s = grafik.STUFEN
    assert s["niedrig"].regen_tropfen < s["mittel"].regen_tropfen < s["hoch"].regen_tropfen <= s["ultra"].regen_tropfen
    assert s["niedrig"].gischt_teilchen < s["mittel"].gischt_teilchen < s["hoch"].gischt_teilchen
    # ein altes Profil ohne die Felder bekommt die der Stufe
    g = grafik.aus_dict({"stufe": "niedrig"})
    assert g.regen_tropfen == s["niedrig"].regen_tropfen
    grafik.stufe_setzen("hoch")


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


def test_gast_ohne_feld_im_lobbyzustand_hat_trocken(aufbau_sauber):
    """Ein Host mit dem Spiel von vor 1.1.0 schickt das Feld nicht."""
    seite = _online_seite(ist_host=False)
    seite._wetter_setzen("Regen")
    seite._on_net(_lobbyzustand({"laps": 3}))
    assert seite._selected_wetter == "Trocken"
    from src.core import race_setup
    assert race_setup.current().weather == "Trocken"


def test_gast_liest_das_wetter_des_hosts(aufbau_sauber):
    seite = _online_seite(ist_host=False)
    seite._on_net(_lobbyzustand({"laps": 3, "tageszeit": "Nacht", "wetter": "Regen"}))
    assert seite._selected_wetter == "Regen"
    assert seite._selected_tageszeit == "Nacht", "die Tageszeit bleibt davon unberührt"
    from src.core import race_setup
    assert race_setup.current().weather == "Regen"


@pytest.mark.parametrize("muell", [None, "Schnee", 7, ["Regen"], {"x": 1}])
def test_unbrauchbares_feld_wird_zu_trocken(aufbau_sauber, muell):
    seite = _online_seite(ist_host=False)
    seite._on_net(_lobbyzustand({"wetter": muell}))
    assert seite._selected_wetter == "Trocken"


def test_host_verteilt_das_wetter_in_den_einstellungen(aufbau_sauber, monkeypatch):
    seite = _online_seite(ist_host=True)
    gesendet = []
    netz = types.SimpleNamespace(send_tcp=lambda m: gesendet.append(m), slot=0, ping_ms=0)
    from src.net import session
    monkeypatch.setattr(session, "get", lambda: netz)
    seite._wetter_setzen("Regen")
    seite._push_settings()
    assert gesendet[-1]["type"] == "SET_SETTINGS"
    assert gesendet[-1]["settings"]["wetter"] == "Regen"
    # die bekannten Felder bleiben, wo sie waren
    assert {"mode", "laps", "track_path", "roster_size", "tageszeit"} <= set(gesendet[-1]["settings"])


def test_online_lobby_hat_keine_steppers_fuer_tageszeit_und_wetter(aufbau_sauber):
    for ist_host in (True, False):
        seite = _online_seite(ist_host=ist_host)
        seite._refresh_focus_group()
        assert not hasattr(seite, "_wetter_stepper") and not hasattr(seite, "_tageszeit_stepper")
        beschriftungen = [getattr(w, "label", "") for w in seite._host_column_widgets()]
        assert "Wetter" not in beschriftungen and "Tageszeit" not in beschriftungen


def test_server_kennt_das_feld_und_haelt_es_in_grenzen():
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    import server as srv
    assert "wetter" in srv.SETTINGS_KEYS
    assert srv.WETTER == {"Trocken", "Regen"}
    assert set(wetter.NAMEN) == srv.WETTER, "Spiel und Server kennen dieselben Wetter"


def test_der_echte_relay_reicht_das_wetter_durch_und_haelt_es_in_grenzen():
    """Gegen den laufenden Server: gültig kommt an, Unsinn wird Trocken, fehlend bleibt fehlend."""
    sys.path.insert(0, os.path.join(_ROOT, "server"))
    from tests import test_relais_absicherung as ra
    import server as srv
    srv._registry = srv._Registry()
    srv._wache = srv._Wache()
    relay = ra._Relay()
    relay.start()
    try:
        d, ok = ra._host(relay)
        try:
            lobby = srv._registry.get(ok["lobby_id"])
            # ein Host von vor 1.1.0: kein Wetterfeld, die Einstellungen kommen trotzdem an
            d.senden({"type": "SET_SETTINGS", "settings": {"laps": 4}})
            assert d.warten_auf("LOBBY_STATE") is not None
            assert lobby.settings.get("laps") == 4 and "wetter" not in lobby.settings
            d.senden({"type": "SET_SETTINGS", "settings": {"wetter": "Regen", "tageszeit": "Nacht"}})
            zustand = d.warten_auf("LOBBY_STATE")
            assert zustand["settings"]["wetter"] == "Regen" and zustand["settings"]["tageszeit"] == "Nacht"
            for muell in ("Schnee", 5, ["Regen"], None, {"a": 1}):
                d.senden({"type": "SET_SETTINGS", "settings": {"wetter": muell}})
                assert d.warten_auf("LOBBY_STATE")["settings"]["wetter"] == "Trocken"
        finally:
            d.zu()
    finally:
        relay.stop()


def test_rennaufbau_kennt_das_wetter():
    from src.core import race_setup
    assert race_setup.RaceSetup().weather == "Trocken"


def test_rennstart_nimmt_das_wetter_vom_aufrufer_oder_aus_dem_rennaufbau(monkeypatch):
    from src.core import race_setup
    from src.states.race_state import RaceState
    setup = race_setup.RaceSetup()
    monkeypatch.setattr(race_setup, "_current", setup)

    def selbst(**kwargs):
        s = object.__new__(RaceState)
        s._enter_kwargs = kwargs
        return s

    setup.weather = "Regen"
    assert selbst()._wetter_waehlen() == "Regen"
    # der Aufrufer sticht den Rennaufbau
    assert selbst(wetter="Trocken")._wetter_waehlen() == "Trocken"
    setup.weather = "Quatsch"
    assert selbst()._wetter_waehlen() == "Trocken"


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


def test_altes_profil_mit_wetter_laedt_ohne_fehler_und_verliert_das_feld(profil_pfad):
    """Seit 1.1.0 wird das Wetter gewürfelt und nicht mehr im Profil gemerkt."""
    from src.core import profile
    for alt in ("Regen", "Gewitter", 12, None):
        profil_pfad.write_text(json.dumps({"username": "Alt", "wetter": alt}), encoding="utf-8")
        p = profile.Profile.load()
        assert p.username == "Alt"
        assert not hasattr(p, "wetter") and not hasattr(p, "set_wetter")
    p.save()
    assert "wetter" not in json.loads(profil_pfad.read_text(encoding="utf-8"))


def test_lobbys_haben_keinen_wetter_stepper(profil_pfad, monkeypatch):
    from tests import spielhilfe
    from tests.test_layout_regeln import _ShellAttrappe
    spielhilfe.aufbau_bewahren(monkeypatch)
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()
    from src.states.menu.lobby_page import LobbyPage
    from src.states.menu.mp_lobby_page import MPLobbyPage
    for klasse in (LobbyPage, MPLobbyPage):
        seite = klasse()
        seite.enter(_ShellAttrappe())
        assert not hasattr(seite, "wetter") and not hasattr(seite, "tageszeit")
        assert all(getattr(w, "label", "") not in ("Tageszeit", "Wetter") for w in seite.group.widgets)


def test_oberflaeche_ist_uebersetzt():
    with open(os.path.join(_ROOT, "data", "i18n", "en.json"), encoding="utf-8") as fh:
        en = json.load(fh)
    for schluessel in ("Wetter", "Wetter:", "Trocken", "Regen"):
        assert schluessel in en and en[schluessel]


# ---------------------------------------------------------------------------
# Durch OpenGL
# ---------------------------------------------------------------------------
moderngl = pytest.importorskip("moderngl")
pytest.importorskip("trimesh")

from tests.test_render3d_zeichnen import _bild, _stand as _gl_stand, ctx, modellordner, netz  # noqa: E402,F401
from src.render3d import rennszene  # noqa: E402


def test_trocken_ist_der_vorgabewert_und_zeichnet_dasselbe(ctx, netz, modellordner):
    a = rennszene.Rennszene(ctx, netz, modellordner)
    b = rennszene.Rennszene(ctx, netz, modellordner, wetter="Trocken")
    c = rennszene.Rennszene(ctx, netz, modellordner, wetter="Schnee")
    assert a.wetter is TROCKEN and b.wetter is TROCKEN and c.wetter is TROCKEN
    assert a.regen is None and b.regen is None
    staende = [_gl_stand()]
    for s in (a, b, c):
        s.fortschreiben(staende, 1.0 / 60.0)
    bild_a = _bild(ctx, a, staende)
    assert np.array_equal(bild_a, _bild(ctx, b, staende))
    assert np.array_equal(bild_a, _bild(ctx, c, staende))
    p = a.programm
    assert tuple(p["wetter_nass"].value)[0] == 0.0
    for s in (a, b, c):
        s.freigeben()


def test_regen_zeichnet_anders_und_dunkler(ctx, netz, modellordner):
    trocken = rennszene.Rennszene(ctx, netz, modellordner)
    nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen")
    assert nass.wetter is REGEN and nass.regen is not None
    staende = [_gl_stand(x=2.0), _gl_stand(kennung=2, x=14.0)]
    for _ in range(40):
        for s in (trocken, nass):
            s.fortschreiben(staende, 1.0 / 60.0)
    bild_t, bild_n = _bild(ctx, trocken, staende), _bild(ctx, nass, staende)
    assert bild_n.std() > 3.0
    assert not np.array_equal(bild_t, bild_n)
    p = nass.programm
    assert tuple(p["wetter_nass"].value)[0] == 1.0
    assert tuple(p["wetter_nass"].value)[1] == pytest.approx(REGEN.nass_albedo)
    assert float(nass.belichtung) > 0.0
    for s in (trocken, nass):
        s.freigeben()


def test_regen_hat_gischt_hinter_schnellen_autos(ctx, netz, modellordner):
    nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen")
    dt = 1.0 / 60.0
    for i in range(90):
        staende = [_gl_stand(x=2.0 + 40.0 * i * dt)]                  # 40 m/s
        nass.fortschreiben(staende, dt)
    assert nass.regen.teilchen_aktiv > 20
    # stehend entsteht keine neue Gischt, die alte verfliegt
    for _ in range(240):
        nass.fortschreiben([_gl_stand(x=80.0)], dt)
    assert nass.regen.teilchen_aktiv == 0
    nass.freigeben()


def test_gischt_folgt_der_grafikstufe(ctx, netz, modellordner):
    alt = grafik.aktuell()
    try:
        grafik.setzen(gischt_teilchen=40)
        nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen")
        dt = 1.0 / 60.0
        for i in range(120):
            nass.fortschreiben([_gl_stand(x=2.0 + 45.0 * i * dt)], dt)
        assert 0 < nass.regen.teilchen_aktiv <= 40
        nass.freigeben()
    finally:
        grafik.aus_dict(grafik.als_dict(alt))


def test_regen_zeichnet_auch_ohne_tropfen_und_nachts(ctx, netz, modellordner):
    alt = grafik.aktuell()
    try:
        grafik.setzen(regen_tropfen=0, gischt_teilchen=0)
        nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen", tageszeit="Nacht")
        staende = [_gl_stand()]
        nass.fortschreiben(staende, 1.0 / 60.0)
        assert _bild(ctx, nass, staende).std() > 1.0
        nass.freigeben()
    finally:
        grafik.aus_dict(grafik.als_dict(alt))
    nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen", tageszeit="Nacht")
    staende = [_gl_stand(kennung=i, x=-6.0 * i) for i in range(3)]
    nass.fortschreiben(staende, 1.0 / 60.0)
    assert _bild(ctx, nass, staende).std() > 1.0
    assert nass.regen._lichter_anzahl > 0, "nachts leuchten die Scheinwerfer im Regen"
    nass.freigeben()


def test_kamerageschwindigkeit_gilt_je_ausschnitt(ctx, netz, modellordner):
    """Im Splitscreen wechseln zwei Kameras einander ab: jede hat ihre eigene Geschwindigkeit."""
    nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen")
    r = nass.regen
    assert np.allclose(r.kamera_bewegt("oben", (0.0, 0.0, 2.0)), 0.0), "erstes Bild: keine Geschwindigkeit"
    r.kamera_bewegt("unten", (500.0, 0.0, 2.0))
    r.zeit += 0.1
    v_oben = r.kamera_bewegt("oben", (1.0, 0.0, 2.0))
    v_unten = r.kamera_bewegt("unten", (503.0, 0.0, 2.0))
    assert v_oben[0] == pytest.approx(10.0)
    assert v_unten[0] == pytest.approx(30.0)
    # ein Sprung (Zurücksetzen auf die Strecke) ist keine Geschwindigkeit
    r.zeit += 0.1
    assert np.allclose(r.kamera_bewegt("oben", (400.0, 0.0, 2.0)), 0.0)
    nass.freigeben()


def test_regen_zeichnet_in_zwei_ausschnitten(ctx, netz, modellordner):
    """Splitscreen: zweimal je Bild gezeichnet, die Zeit vergeht einmal."""
    import moderngl
    from src.render3d import camera
    nass = rennszene.Rennszene(ctx, netz, modellordner, wetter="Regen")
    staende = [_gl_stand(x=2.0), _gl_stand(kennung=2, x=20.0)]
    puffer = ctx.simple_framebuffer((320, 120), components=3)
    puffer.use()
    for bild in range(6):
        nass.fortschreiben(staende, 1.0 / 60.0)
        zeit = nass.regen.zeit
        for i, (x0, x1) in enumerate(((0, 160), (160, 320))):
            ctx.viewport = (x0, 0, x1 - x0, 120)
            ctx.scissor = (x0, 0, x1 - x0, 120)
            ctx.enable(moderngl.DEPTH_TEST)
            kam = camera.Verfolgerkamera(abstand_m=9.0, hoehe_m=3.0, zielhoehe_m=1.0)
            kam.setzen(staende[i].pos_m, staende[i].gierwinkel_rad)
            mvp = camera.perspektive(55.0, 160 / 120, 0.2, 400.0) @ kam.blickmatrix()
            nass.zeichnen(mvp, kam.auge, staende)
        assert nass.regen.zeit == zeit, "zweimal zeichnen lässt keine Zeit vergehen"
    assert len(nass.regen._kamera_alt) == 2
    ctx.scissor = None
    puffer.release()
    nass.freigeben()
