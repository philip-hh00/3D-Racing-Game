"""Tageszeit und Wetter werden gewürfelt, nie gewählt (1.1.0).

80 % Tag/Trocken, je ~6,67 % Nacht/Trocken, Tag/Regen und Nacht/Regen;
Zeitfahren und Team-Zeitfahren immer Tag/Trocken; online würfelt nur der Host.
"""

from __future__ import annotations

import json
import os
import random
import types
from collections import Counter

import pytest

from src.core import rennbedingungen as bed

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Fest:
    """Zufallsquelle mit festen Werten (und Zähler), für deterministische Tests."""

    def __init__(self, *werte):
        self.werte = list(werte)
        self.aufrufe = 0

    def random(self):
        self.aufrufe += 1
        return self.werte.pop(0) if len(self.werte) > 1 else self.werte[0]


class _Verboten:
    def random(self):
        raise AssertionError("hier darf nicht gewürfelt werden")


@pytest.fixture(autouse=True)
def _ohne_uebersteuerung(monkeypatch):
    monkeypatch.delenv(bed.UMGEBUNGSVARIABLE, raising=False)


# ---------------------------------------------------------------------------
# Würfeln
# ---------------------------------------------------------------------------
def test_verteilung_ueber_viele_wuerfe():
    zufall = random.Random(1234)
    n = 60000
    zaehler = Counter(bed.wuerfeln(zufall) for _ in range(n))
    assert set(zaehler) == {("Tag", "Trocken"), ("Nacht", "Trocken"), ("Tag", "Regen"), ("Nacht", "Regen")}
    assert zaehler[("Tag", "Trocken")] / n == pytest.approx(0.80, abs=0.01)
    for ausnahme in bed.AUSNAHMEN:
        assert zaehler[ausnahme] / n == pytest.approx(0.2 / 3, abs=0.008)


def test_abend_wird_nicht_gewuerfelt():
    zufall = random.Random(7)
    assert all(t != "Abend" for t, _w in (bed.wuerfeln(zufall) for _ in range(5000)))


def test_grenzen_der_wuerfe_sind_fest():
    assert bed.wuerfeln(_Fest(0.0)) == ("Tag", "Trocken")
    assert bed.wuerfeln(_Fest(0.7999)) == ("Tag", "Trocken")
    assert bed.wuerfeln(_Fest(0.80)) == ("Nacht", "Trocken")
    assert bed.wuerfeln(_Fest(0.8666)) == ("Nacht", "Trocken")
    assert bed.wuerfeln(_Fest(0.8667)) == ("Tag", "Regen")
    assert bed.wuerfeln(_Fest(0.9333)) == ("Tag", "Regen")
    assert bed.wuerfeln(_Fest(0.9334)) == ("Nacht", "Regen")
    assert bed.wuerfeln(_Fest(0.999999)) == ("Nacht", "Regen")


@pytest.mark.parametrize("modus", ["Zeitfahren", "Team-Zeitfahren"])
def test_zeitfahren_ist_immer_tag_und_trocken_ohne_zu_wuerfeln(modus):
    assert bed.wuerfeln(_Verboten(), modus=modus) == ("Tag", "Trocken")
    assert bed.ist_fest(modus)
    # auch wenn die Umgebung etwas anderes will: die Ghosts fahren nur bei Sonne
    assert bed.wuerfeln(_Verboten(), modus=modus, umgebung={bed.UMGEBUNGSVARIABLE: "Nacht/Regen"}) == ("Tag", "Trocken")


@pytest.mark.parametrize("modus", ["Rennen", "Grand Prix"])
def test_rennen_und_grand_prix_wuerfeln(modus):
    assert not bed.ist_fest(modus)
    assert bed.wuerfeln(_Fest(0.95), modus=modus) == ("Nacht", "Regen")


@pytest.mark.parametrize("text, erwartet", [
    ("Nacht/Regen", ("Nacht", "Regen")),
    ("nacht, regen", ("Nacht", "Regen")),
    ("Tag/Trocken", ("Tag", "Trocken")),
    ("Regen", ("Tag", "Regen")),
    ("Nacht", ("Nacht", "Trocken")),
    ("Abend/Trocken", ("Abend", "Trocken")),
    ("Abend+Regen", ("Abend", "Regen")),
])
def test_umgebungsvariable_legt_das_ergebnis_fest(text, erwartet):
    assert bed.wuerfeln(_Verboten(), umgebung={bed.UMGEBUNGSVARIABLE: text}) == erwartet


@pytest.mark.parametrize("text", ["", "   ", "Schnee", "Nacht/Schnee", None])
def test_unbrauchbare_umgebungsvariable_wird_ignoriert(text):
    umgebung = {} if text is None else {bed.UMGEBUNGSVARIABLE: text}
    assert bed.wuerfeln(_Fest(0.95), umgebung=umgebung) == ("Nacht", "Regen")


def test_fehlende_oder_kaputte_werte_sind_tag_und_trocken():
    assert bed.normiere(None, None) == ("Tag", "Trocken")
    assert bed.normiere("Mittag", 7) == ("Tag", "Trocken")
    assert bed.normiere("Nacht", "Regen") == ("Nacht", "Regen")


def test_anzeigetext_nur_wenn_es_nicht_der_normalfall_ist(monkeypatch):
    assert bed.beschreibung("Tag", "Trocken") == ""
    assert bed.beschreibung(None, None) == ""
    assert bed.beschreibung("Nacht", "Trocken") == "Nacht"
    assert bed.beschreibung("Tag", "Regen") == "Regen"
    assert bed.beschreibung("Nacht", "Regen") == "Regen bei Nacht"
    from src.core import i18n
    monkeypatch.setattr(i18n, "_lang", "en")
    try:
        assert bed.beschreibung("Nacht", "Trocken") == "Night"
        assert bed.beschreibung("Tag", "Regen") == "Rain"
        assert bed.beschreibung("Nacht", "Regen") == "Rain at night"
    finally:
        monkeypatch.setattr(i18n, "_lang", "de")


def test_texte_sind_ins_englische_uebersetzt():
    with open(os.path.join(_ROOT, "data", "i18n", "en.json"), encoding="utf-8") as fh:
        en = json.load(fh)
    for schluessel in ("Nacht", "Regen", "Regen bei Nacht", "Regen am Abend"):
        assert en.get(schluessel)


# ---------------------------------------------------------------------------
# RaceState: offline wird je Rennen gewürfelt, online übernimmt jeder den Wert des Hosts
# ---------------------------------------------------------------------------
@pytest.fixture
def aufbau(monkeypatch):
    from src.core import race_setup
    setup = race_setup.RaceSetup()
    monkeypatch.setattr(race_setup, "_current", setup)
    return setup


def _rennstart(**kwargs):
    from src.states.race_state import RaceState
    selbst = object.__new__(RaceState)
    selbst._enter_kwargs = kwargs
    selbst._bedingungen = selbst._bedingungen_festlegen(kwargs)
    return selbst


def test_offline_wuerfelt_jedes_rennen_neu_auch_im_grand_prix(aufbau, monkeypatch):
    aufbau.mode = "Grand Prix"
    monkeypatch.setattr(bed, "random", _Fest(0.1, 0.85, 0.9, 0.99))
    ergebnisse = [_rennstart()._bedingungen for _ in range(4)]
    assert ergebnisse == [("Tag", "Trocken"), ("Nacht", "Trocken"), ("Tag", "Regen"), ("Nacht", "Regen")]
    # das Ergebnis steht im Rennaufbau, und alle Abfragen eines Rennens stimmen überein
    assert (aufbau.time_of_day, aufbau.weather) == ("Nacht", "Regen")
    lauf = _rennstart()
    assert lauf._tageszeit_waehlen() == aufbau.time_of_day
    assert lauf._wetter_waehlen() == aufbau.weather


def test_ein_rennen_wuerfelt_genau_einmal(aufbau, monkeypatch):
    zufall = _Fest(0.95)
    monkeypatch.setattr(bed, "random", zufall)
    lauf = _rennstart()
    for _ in range(5):
        lauf._tageszeit_waehlen()
        lauf._wetter_waehlen()
    assert zufall.aufrufe == 1


@pytest.mark.parametrize("modus", ["Zeitfahren", "Team-Zeitfahren"])
def test_zeitfahren_im_rennstart_ist_tag_und_trocken(aufbau, monkeypatch, modus):
    aufbau.mode = modus
    aufbau.time_of_day, aufbau.weather = "Nacht", "Regen"      # Rest vom letzten Rennen
    monkeypatch.setattr(bed, "random", _Verboten())
    lauf = _rennstart()
    assert lauf._bedingungen == ("Tag", "Trocken")
    assert (aufbau.time_of_day, aufbau.weather) == ("Tag", "Trocken")


def test_aufrufer_legt_die_bedingungen_fest_ohne_zu_wuerfeln(aufbau, monkeypatch):
    monkeypatch.setattr(bed, "random", _Verboten())
    assert _rennstart(tageszeit="Tag", wetter="Trocken")._bedingungen == ("Tag", "Trocken")
    assert _rennstart(tageszeit="Nacht")._bedingungen == ("Nacht", "Trocken")


def test_online_wuerfelt_der_rennstart_nie_sondern_nimmt_die_werte_der_lobby(aufbau, monkeypatch):
    aufbau._online = True
    aufbau.time_of_day, aufbau.weather = "Nacht", "Regen"
    monkeypatch.setattr(bed, "random", _Verboten())
    lauf = _rennstart()
    assert lauf._bedingungen == ("Nacht", "Regen")
    assert lauf._wetter_waehlen() == "Regen"


def test_online_ohne_werte_oder_mit_muell_ist_tag_und_trocken(aufbau, monkeypatch):
    aufbau._online = True
    monkeypatch.setattr(bed, "random", _Verboten())
    assert _rennstart()._bedingungen == ("Tag", "Trocken")
    aufbau.time_of_day, aufbau.weather = None, 12
    assert _rennstart()._bedingungen == ("Tag", "Trocken")


def test_umgebungsvariable_gilt_im_rennstart(aufbau, monkeypatch):
    monkeypatch.setenv(bed.UMGEBUNGSVARIABLE, "Nacht/Regen")
    assert _rennstart()._bedingungen == ("Nacht", "Regen")
    aufbau.mode = "Zeitfahren"
    assert _rennstart()._bedingungen == ("Tag", "Trocken")


# ---------------------------------------------------------------------------
# Online-Lobby: nur der Host würfelt, einmal je Rennstart, und verteilt das Ergebnis
# ---------------------------------------------------------------------------
@pytest.fixture
def aufbau_sauber(monkeypatch):
    from tests import spielhilfe
    spielhilfe.aufbau_bewahren(monkeypatch)
    from src.entities.vehicle_factory import VehicleFactory
    VehicleFactory.load_all_configs()
    yield


def _seite(ist_host):
    from tests.test_render3d_tageszeit import _online_seite
    return _online_seite(ist_host=ist_host)


def _netz(monkeypatch):
    gesendet = []
    netz = types.SimpleNamespace(send_tcp=lambda m: gesendet.append(m), slot=0, ping_ms=0)
    from src.net import session
    monkeypatch.setattr(session, "get", lambda: netz)
    return gesendet


def test_host_wuerfelt_beim_start_einmal_und_schickt_es_vor_dem_start(aufbau_sauber, monkeypatch):
    seite = _seite(True)
    gesendet = _netz(monkeypatch)
    uebertragen = []
    seite._upload_map_bg = lambda *a: uebertragen.append(len(gesendet))
    zufall = _Fest(0.95)
    monkeypatch.setattr(bed, "random", zufall)
    seite._request_start(force=True)
    assert zufall.aufrufe == 1
    einstellungen = [m["settings"] for m in gesendet if m["type"] == "SET_SETTINGS"]
    assert einstellungen and all(e["tageszeit"] == "Nacht" and e["wetter"] == "Regen" for e in einstellungen)
    assert (seite._selected_tageszeit, seite._selected_wetter) == ("Nacht", "Regen")
    from src.core import race_setup
    assert (race_setup.current().time_of_day, race_setup.current().weather) == ("Nacht", "Regen")
    # die Einstellungen sind raus, bevor die Streckenübertragung (und damit der Start) beginnt
    assert uebertragen and uebertragen[0] >= 1


def test_host_wuerfelt_bei_jedem_neustart_neu(aufbau_sauber, monkeypatch):
    seite = _seite(True)
    _netz(monkeypatch)
    seite._upload_map_bg = lambda *a: None
    monkeypatch.setattr(bed, "random", _Fest(0.95, 0.1))
    seite._request_start(force=True)
    assert (seite._selected_tageszeit, seite._selected_wetter) == ("Nacht", "Regen")
    seite._request_start(force=True)
    assert (seite._selected_tageszeit, seite._selected_wetter) == ("Tag", "Trocken")


def test_host_im_zeitfahren_faehrt_tag_und_trocken(aufbau_sauber, monkeypatch):
    seite = _seite(True)
    gesendet = _netz(monkeypatch)
    seite._upload_map_bg = lambda *a: None
    seite._selected_mode = "Team-Zeitfahren"
    monkeypatch.setattr(bed, "random", _Verboten())
    seite._request_start(force=True)
    letzte = [m["settings"] for m in gesendet if m["type"] == "SET_SETTINGS"][-1]
    assert (letzte["tageszeit"], letzte["wetter"]) == ("Tag", "Trocken")


def test_gast_wuerfelt_nie_und_nimmt_die_werte_des_hosts(aufbau_sauber, monkeypatch):
    seite = _seite(False)
    gesendet = _netz(monkeypatch)
    monkeypatch.setattr(bed, "random", _Verboten())
    seite._bedingungen_wuerfeln()
    assert gesendet == []
    from tests.test_render3d_tageszeit import _lobbyzustand
    seite._on_net(_lobbyzustand({"laps": 3, "tageszeit": "Nacht", "wetter": "Regen"}))
    from src.core import race_setup
    assert (seite._selected_tageszeit, seite._selected_wetter) == ("Nacht", "Regen")
    assert (race_setup.current().time_of_day, race_setup.current().weather) == ("Nacht", "Regen")
    # dasselbe, was der Rennstart des Gastes dann übernimmt
    monkeypatch.setattr(race_setup.current(), "_online", True, raising=False)
    assert _rennstart()._bedingungen == ("Nacht", "Regen")


def test_gast_ohne_schluessel_faehrt_tag_und_trocken(aufbau_sauber, monkeypatch):
    seite = _seite(False)
    seite._on_net(__import__("tests.test_render3d_tageszeit", fromlist=["x"])._lobbyzustand({"laps": 3}))
    from src.core import race_setup
    assert (race_setup.current().time_of_day, race_setup.current().weather) == ("Tag", "Trocken")


# ---------------------------------------------------------------------------
# Auswahl ist weg, Profil bleibt ladbar, Ghost fährt trocken
# ---------------------------------------------------------------------------
def test_alle_lobbys_ohne_tageszeit_und_wetter_stepper(aufbau_sauber, monkeypatch):
    from tests.test_layout_regeln import _ShellAttrappe
    from src.states.menu.lobby_page import LobbyPage
    from src.states.menu.mp_lobby_page import MPLobbyPage
    seiten = [LobbyPage(), MPLobbyPage()]
    for seite in seiten:
        seite.enter(_ShellAttrappe())
    seiten.append(_seite(True))
    seiten.append(_seite(False))
    for seite in seiten:
        for name in ("tageszeit", "wetter", "_tageszeit_stepper", "_wetter_stepper"):
            assert not hasattr(seite, name), (type(seite).__name__, name)


def test_profil_ohne_tageszeit_und_wetter_und_altes_mit_beidem_laden(tmp_path, monkeypatch):
    from src.core import profile
    ziel = tmp_path / "profile.json"
    monkeypatch.setattr("src.core.paths.user_path",
                        lambda *t: str(ziel) if t[-1] == "profile.json" else str(tmp_path.joinpath(*t)))
    monkeypatch.setattr(profile, "_current", None)
    ziel.write_text(json.dumps({"username": "Alt", "tageszeit": "Nacht", "wetter": "Regen"}), encoding="utf-8")
    p = profile.Profile.load()
    assert p.username == "Alt"
    p.save()
    gespeichert = json.loads(ziel.read_text(encoding="utf-8"))
    assert "tageszeit" not in gespeichert and "wetter" not in gespeichert
    monkeypatch.setattr(profile, "_current", None)


def test_erst_ghost_wird_trocken_gefahren(monkeypatch):
    from src.core import ghost
    from src.entities.vehicle import Vehicle
    aufrufe = []
    original = Vehicle.wetter_setzen
    monkeypatch.setattr(Vehicle, "wetter_setzen",
                        lambda self, name: (aufrufe.append(name), original(self, name))[1])
    strecke = os.path.join(_ROOT, "data", "tracks", "oval.json")
    if not os.path.isfile(strecke):
        pytest.skip("Teststrecke fehlt")
    ghost.generate_seed_ghost(strecke)
    assert aufrufe == ["Trocken"]
