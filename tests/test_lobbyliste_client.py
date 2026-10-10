"""Lobbyliste im Spiel: zusammengefuehrte Server, Sortierung, Filter, Auffrischen,
ausgegraute Lobbys, Passwort- und Erstellen-Ablauf der Seite (Plan 1.1.0).

Alles mit Attrappen, kein Netz: eine ``api`` mit ``anfrage(sd, msg, timeout)``
liefert die Antworten der beiden Server, ``ping_von`` den Ping.
"""
from __future__ import annotations

import os
import sys
import threading
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pygame  # noqa: E402

from src.net import lobby_liste, servers  # noqa: E402
from src.net.lobby_liste import LobbyListe  # noqa: E402
from src.net.strecken_client import StreckenFehler  # noqa: E402
from src.net.servers import ServerDef  # noqa: E402

HEL = ServerDef(id="helsinki", code_prefix="H", label="Helsinki",
                tcp_host="h", tcp_port=1, udp_host="h", udp_port=1)
HAM = ServerDef(id="hamburg", code_prefix="D", label="Hamburg",
                tcp_host="d", tcp_port=2, udp_host="d", udp_port=2)


def _e(code, name="Runde", host="Anna", players=1, mx=4, status="lobby",
       password=False, mode="Rennen"):
    return {"code": code, "name": name, "host": host, "players": players,
            "max": mx, "status": status, "password": password, "mode": mode}


class Api:
    """Antworten je Server; ``fehler`` laesst einen Server scheitern."""

    def __init__(self, antworten=None, fehler=None):
        self.antworten = antworten or {}
        self.fehler = fehler or {}
        self.aufrufe = []

    def anfrage(self, sd, msg, timeout=0):
        self.aufrufe.append((sd.id, msg["type"]))
        if sd.id in self.fehler:
            raise StreckenFehler(self.fehler[sd.id])
        return {"type": "LOBBY_LIST", "lobbies": list(self.antworten.get(sd.id, []))}


def _liste(api, pings=None, **kw):
    pings = pings if pings is not None else {"helsinki": 40.0, "hamburg": 20.0}
    return LobbyListe(api=api, ping_von=lambda sd: pings.get(sd.id),
                      server_liste=lambda: [HEL, HAM], synchron=True, **kw)


# --------------------------------------------------------------------------
# Zusammenfuehren
# --------------------------------------------------------------------------

def test_lobbys_beider_server_stehen_in_einer_liste():
    api = Api({"helsinki": [_e("HAAAAA", "Eins")], "hamburg": [_e("DBBBBB", "Zwei")]})
    liste = _liste(api)
    liste.aktualisieren()
    alle = liste.alle()
    assert {(e.server.id, e.code) for e in alle} == {("helsinki", "HAAAAA"),
                                                      ("hamburg", "DBBBBB")}
    assert all(t == "LOBBY_LIST" for _, t in api.aufrufe)


def test_alle_server_werden_gleichzeitig_gefragt():
    """Beide Anfragen muessen sich treffen - sonst waere es nacheinander."""
    schranke = threading.Barrier(2, timeout=3)

    class Parallel(Api):
        def anfrage(self, sd, msg, timeout=0):
            schranke.wait()
            return super().anfrage(sd, msg, timeout)

    api = Parallel({"helsinki": [_e("HAAAAA")], "hamburg": [_e("DBBBBB")]})
    liste = LobbyListe(api=api, ping_von=lambda sd: 10.0,
                       server_liste=lambda: [HEL, HAM])
    liste.aktualisieren()
    liste.warten()
    assert len(liste.alle()) == 2 and not any(liste.fehler.values())


def test_ping_kommt_vom_jeweiligen_server():
    api = Api({"helsinki": [_e("HAAAAA")], "hamburg": [_e("DBBBBB")]})
    liste = _liste(api, {"helsinki": 77.0, "hamburg": 12.0})
    liste.aktualisieren()
    ping = {e.server.id: e.ping_ms for e in liste.alle()}
    assert ping == {"helsinki": 77.0, "hamburg": 12.0}


# --------------------------------------------------------------------------
# Sortieren und Filtern
# --------------------------------------------------------------------------

def test_sortierung_beitretbare_zuerst_dann_ping():
    api = Api({
        "helsinki": [_e("HAAAAA", "Hel offen"), _e("HBBBBB", "Hel im Rennen", status="racing")],
        "hamburg": [_e("DAAAAA", "Ham offen"), _e("DBBBBB", "Ham voll", players=4, mx=4)],
    })
    liste = _liste(api, {"helsinki": 40.0, "hamburg": 20.0})
    liste.aktualisieren()
    namen = [e.name for e in liste.ansicht()]
    # Hamburg ist schneller -> zuerst; Nicht-Beitretbare (Rennen/voll) zuletzt,
    # auch sie nach Ping
    assert namen == ["Ham offen", "Hel offen", "Ham voll", "Hel im Rennen"]


def test_gleicher_ping_sortiert_nach_name():
    api = Api({"helsinki": [_e("HAAAAA", "Zebra"), _e("HBBBBB", "Anton")]})
    liste = _liste(api)
    liste.aktualisieren()
    assert [e.name for e in liste.ansicht(server_id="helsinki")] == ["Anton", "Zebra"]


def test_filter_nur_beitretbare():
    api = Api({"helsinki": [_e("HAAAAA", "offen"),
                            _e("HBBBBB", "rennen", status="racing"),
                            _e("HCCCCC", "voll", players=4, mx=4)]})
    liste = _liste(api)
    liste.aktualisieren()
    assert len(liste.ansicht()) == 3
    assert [e.name for e in liste.ansicht(nur_beitretbare=True)] == ["offen"]


def test_filter_server():
    api = Api({"helsinki": [_e("HAAAAA")], "hamburg": [_e("DBBBBB")]})
    liste = _liste(api)
    liste.aktualisieren()
    assert [e.server.id for e in liste.ansicht(server_id="hamburg")] == ["hamburg"]
    assert len(liste.ansicht(server_id="")) == 2


def test_grand_prix_lobby_im_rennen_ist_nicht_beitretbar():
    """Der Relay meldet die ganze Serie als „racing"; die Liste graut sie aus."""
    api = Api({"helsinki": [_e("HAAAAA", "GP", status="racing", mode="Grand Prix")]})
    liste = _liste(api)
    liste.aktualisieren()
    e = liste.alle()[0]
    assert e.im_rennen and not e.beitretbar


# --------------------------------------------------------------------------
# Pruefung des Fremden
# --------------------------------------------------------------------------

def test_eintraege_werden_gesaeubert_und_geprueft():
    api = Api({"helsinki": [
        _e("HAAAAA", "Gut\n‮Schlecht" + "x" * 50, host="Ho\x00st"),
        _e("DXXXXX", "falscher Server"),              # Code gehoert zu Hamburg
        _e("H12", "zu kurz"),
        "kein dict", None,
        {"code": "HZZZZZ"},                            # nur Code: Rest wird ergaenzt
        _e("HYYYYY", "Zahlen", players="viele", mx=999),
    ]})
    liste = _liste(api)
    liste.aktualisieren()
    alle = {e.code: e for e in liste.alle()}
    assert set(alle) == {"HAAAAA", "HZZZZZ", "HYYYYY"}
    a = alle["HAAAAA"]
    assert "\n" not in a.name and "‮" not in a.name and len(a.name) <= 25
    assert "\x00" not in a.host
    assert alle["HZZZZZ"].name.startswith("Lobby von")
    assert 0 <= alle["HYYYYY"].players <= 6 and alle["HYYYYY"].max <= 6


def test_gesperrte_namen_werden_ausgeblendet(monkeypatch):
    monkeypatch.setattr(lobby_liste, "_gesperrt", lambda t: "boese" in t.lower())
    api = Api({"helsinki": [_e("HAAAAA", "Boese Runde"), _e("HBBBBB", "Nett", host="Boese"),
                            _e("HCCCCC", "Nett")]})
    liste = _liste(api)
    liste.aktualisieren()
    assert [e.code for e in liste.alle()] == ["HCCCCC"]


def test_passwort_nur_bei_echtem_true():
    api = Api({"helsinki": [_e("HAAAAA", password=True), _e("HBBBBB", password="ja"),
                            _e("HCCCCC", password=1)]})
    liste = _liste(api)
    liste.aktualisieren()
    assert {e.code: e.password for e in liste.alle()} == {
        "HAAAAA": True, "HBBBBB": False, "HCCCCC": False}


# --------------------------------------------------------------------------
# Ausfaelle
# --------------------------------------------------------------------------

def test_ein_server_faellt_aus_der_andere_bleibt():
    api = Api({"hamburg": [_e("DBBBBB")]}, fehler={"helsinki": "OFFLINE"})
    liste = _liste(api)
    liste.aktualisieren()
    assert [e.server.id for e in liste.alle()] == ["hamburg"]
    assert liste.fehler["helsinki"] == "OFFLINE" and liste.fehler["hamburg"] == ""
    assert not liste.alle_fehlgeschlagen()


def test_alte_eintraege_bleiben_kurz_und_verschwinden_dann():
    api = Api({"helsinki": [_e("HAAAAA")]})
    liste = _liste(api)
    liste.aktualisieren()
    assert len(liste.alle()) == 1
    api.fehler["helsinki"] = "TIMEOUT"
    liste.aktualisieren()                         # eine verlorene Antwort: kein Flackern
    assert len(liste.alle()) == 1
    for _ in range(lobby_liste.FEHLER_GEDULD):
        liste.aktualisieren()
    assert liste.alle() == []


def test_server_ohne_lobbyliste_ist_kein_absturz():
    """Ein Relay ohne die Neuerung schliesst ohne Antwort (UNSUPPORTED), antwortet aber auf INFO."""
    api = Api({"hamburg": [_e("DBBBBB")]}, fehler={"helsinki": "UNSUPPORTED"})
    liste = _liste(api, info_von=lambda sd: True)
    liste.aktualisieren()
    assert liste.fehler["helsinki"] == lobby_liste.ZU_ALT
    assert len(liste.alle()) == 1
    assert [s.id for s in liste.zu_alt()] == ["helsinki"] and liste.ausgefallen() == []


def test_ohne_antwort_auch_auf_info_ist_der_server_ausgefallen_nicht_zu_alt():
    api = Api({}, fehler={"helsinki": "UNSUPPORTED", "hamburg": "OFFLINE"})
    liste = _liste(api, info_von=lambda sd: False)
    liste.aktualisieren()
    assert liste.fehler == {"helsinki": "OFFLINE", "hamburg": "OFFLINE"}
    assert liste.zu_alt() == [] and len(liste.ausgefallen()) == 2


def test_info_wird_nur_nach_geschlossener_verbindung_gefragt():
    gefragt = []
    api = Api({}, fehler={"helsinki": "TIMEOUT", "hamburg": "UNSUPPORTED"})
    liste = _liste(api, info_von=lambda sd: gefragt.append(sd.id) or True)
    liste.aktualisieren()
    assert gefragt == ["hamburg"]
    assert liste.fehler["helsinki"] == "TIMEOUT"


def test_unsinnige_antwort_ist_ein_fehler():
    class Murks(Api):
        def anfrage(self, sd, msg, timeout=0):
            return {"type": "LOBBY_LIST", "lobbies": "nein"}

    liste = _liste(Murks())
    liste.aktualisieren()
    assert liste.alle() == [] and liste.alle_fehlgeschlagen()


def test_lobby_error_wird_zum_fehler():
    class Rate(Api):
        def anfrage(self, sd, msg, timeout=0):
            return {"type": "LOBBY_ERROR", "code": "RATE", "reason": "langsam"}

    liste = _liste(Rate())
    liste.aktualisieren()
    assert liste.fehler["helsinki"] == "RATE"


# --------------------------------------------------------------------------
# Die Ansicht
# --------------------------------------------------------------------------

def _ansicht(api, pings=None, **kw):
    from src.states.menu.lobby_browser import LobbyBrowser
    b = LobbyBrowser(_liste(api, pings, **kw))
    return b


def _taste(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode="", mod=0)


def test_auffrischen_alle_fuenf_sekunden():
    api = Api({"helsinki": [_e("HAAAAA")]})
    b = _ansicht(api)
    b.update(0.016)
    erste = b.liste.runden
    assert erste == 1                              # gleich beim ersten Mal
    b.update(4.0)
    assert b.liste.runden == 1                     # noch nicht
    b.update(1.1)
    assert b.liste.runden == 2                     # nach 5 s
    assert lobby_liste.INTERVALL == 5.0


def test_ausgegraute_zeilen_sind_nicht_waehlbar():
    api = Api({"helsinki": [_e("HAAAAA", "offen"),
                            _e("HBBBBB", "rennen", status="racing"),
                            _e("HCCCCC", "voll", players=4, mx=4)]})
    b = _ansicht(api)
    b.update(0.016)
    z = b.zeilen
    assert [x.eintrag.name for x in z[:3]] == ["offen", "rennen", "voll"]
    assert z[0].focusable and z[0].enabled
    assert not z[1].focusable and not z[1].enabled
    assert not z[2].focusable and not z[2].enabled
    assert z[3].eintrag is None
    # Klick auf eine ausgegraute Zeile tut nichts
    klick = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=z[1].rect.center)
    assert b.handle_event(klick) is None and b.gewaehlt is None
    # Klick auf die offene waehlt sie
    klick = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=z[0].rect.center)
    assert b.handle_event(klick) == "beitreten"
    assert b.gewaehlt.code == "HAAAAA"


def test_filter_in_der_ansicht():
    api = Api({"helsinki": [_e("HAAAAA", "offen"), _e("HBBBBB", "rennen", status="racing")],
               "hamburg": [_e("DCCCCC", "ham")]})
    b = _ansicht(api)
    b.update(0.016)
    sichtbar = lambda: [z.eintrag.name for z in b.zeilen if z.eintrag]  # noqa: E731
    assert len(sichtbar()) == 3
    b.s_nur.index = 1
    b.neu_zeigen()
    assert sorted(sichtbar()) == ["ham", "offen"]
    b.s_nur.index = 0
    b.s_server.index = 1                           # Helsinki
    b.neu_zeigen()
    assert sorted(sichtbar()) == ["offen", "rennen"]
    assert b.server_id == "helsinki"


def test_fokus_bleibt_bei_seiner_lobby_wenn_sich_die_reihenfolge_aendert():
    api = Api({"helsinki": [_e("HAAAAA", "Hel")], "hamburg": [_e("DBBBBB", "Ham")]})
    pings = {"helsinki": 10.0, "hamburg": 50.0}
    b = _ansicht(api, pings)
    b.update(0.016)
    assert [z.eintrag.name for z in b.zeilen[:2]] == ["Hel", "Ham"]
    b.gruppe.index = b.gruppe.widgets.index(b.zeilen[1])      # Fokus auf „Ham"
    pings["hamburg"] = 5.0                                    # jetzt ist Ham schneller
    b.neu_zeigen()
    assert [z.eintrag.name for z in b.zeilen[:2]] == ["Ham", "Hel"]
    assert b.gruppe.focused.eintrag.name == "Ham"


def test_scrollen_bei_mehr_als_acht_lobbys():
    from src.states.menu.lobby_browser import ZEILEN
    lobbys = [_e(f"H{i:05d}"[:6], f"Lobby {i:02d}") for i in range(12)]
    b = _ansicht(Api({"helsinki": lobbys}))
    b.update(0.016)
    assert [z.eintrag.name for z in b.zeilen][0] == "Lobby 00"
    rad = pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1)
    b.handle_event(rad)
    assert b.zeilen[0].eintrag.name == "Lobby 01"
    # mit der Tastatur am unteren Rand weiterrollen
    b.handle_event(_taste(pygame.K_PAGEDOWN))
    assert b.versatz == 12 - ZEILEN
    b.handle_event(_taste(pygame.K_PAGEUP))
    assert b.versatz == 0


def test_fuss_text_je_zustand():
    b = _ansicht(Api({}))
    b.liste.geladen.clear()
    assert "Lade" in b._fusszeile()[0] or "Loading" in b._fusszeile()[0]
    b.update(0.016)
    assert "keine Lobby offen" in b._fusszeile()[0]
    b2 = _ansicht(Api({}, fehler={"helsinki": "OFFLINE", "hamburg": "OFFLINE"}))
    b2.update(0.016)
    assert "Keine Verbindung" in b2._fusszeile()[0]


def test_fuss_text_server_zu_alt_ist_keine_stoerung():
    """Regression: ein erreichbarer Relay ohne LOBBY_LIST hiess "Keine Verbindung zu den Servern"."""
    fehler = {"helsinki": "UNSUPPORTED", "hamburg": "UNSUPPORTED"}
    b = _ansicht(Api({}, fehler=fehler), info_von=lambda sd: True)
    b.update(0.016)
    text, farbe = b._fusszeile()
    assert "zu alt" in text and "Lobbyliste" in text
    assert "Keine Verbindung" not in text and "erreichbar" not in text
    # Einer zu alt, einer wirklich weg: beide Gruende stehen da, getrennt benannt.
    api = Api({}, fehler={"helsinki": "UNSUPPORTED", "hamburg": "OFFLINE"})
    b2 = _ansicht(api, info_von=lambda sd: sd.id == "helsinki")
    b2.update(0.016)
    text = b2._fusszeile()[0]
    assert "Nicht erreichbar: Hamburg" in text and "Zu alt für die Lobbyliste: Helsinki" in text


def test_fuss_text_zu_alt_ist_auch_englisch_uebersetzt():
    import json
    en = json.load(open(os.path.join(_ROOT, "data", "i18n", "en.json"), encoding="utf-8"))
    for schluessel in ("Zu alt für die Lobbyliste: {s}",
                       "Die Server sind zu alt für die Lobbyliste. Erstelle eine Lobby oder tritt per Code bei."):
        assert en.get(schluessel)


# --------------------------------------------------------------------------
# Die Seite: Beitreten, Passwort, Erstellen
# --------------------------------------------------------------------------

class _ShellAttrappe:
    def __init__(self):
        self.verlauf = []
        self.state_machine = types.SimpleNamespace(
            transition=lambda name, **k: self.verlauf.append(name))
        self.gepoppt = 0

    def pop_page(self):
        self.gepoppt += 1

    def push_page(self, seite):
        pass


@pytest.fixture
def seite(monkeypatch):
    from src.net import server_probe
    from src.states.menu import online_lobby_page as olp
    from src.states.menu.lobby_browser import LobbyBrowser
    monkeypatch.setattr(server_probe, "start", lambda: None)
    monkeypatch.setattr(server_probe, "statuses", lambda: [
        server_probe.ServerStatus(server=sd, state=server_probe.ONLINE, ping_ms=42.0)
        for sd in servers.all_servers()])
    page = olp.OnlineLobbyPage()
    page.enter(_ShellAttrappe())
    api = Api({"helsinki": [_e("HAAAAA", "Offen"),
                            _e("HBBBBB", "Geheim", password=True)]})
    page._browser = LobbyBrowser(_liste(api))
    page.update(0.016)
    # kein echter Verbindungsaufbau
    aufrufe = []
    monkeypatch.setattr(page, "_start_connect",
                        lambda server, **kw: aufrufe.append((server.id, kw)))
    page.aufrufe = aufrufe
    page.olp = olp
    return page


def _klick_zeile(page, name):
    z = next(z for z in page._browser.zeilen if z.eintrag and z.eintrag.name == name)
    page.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                         pos=z.rect.center))


def test_die_liste_ist_die_erste_ansicht(seite):
    assert seite._view == seite.olp._BROWSER


def test_beitreten_ohne_passwort_verbindet_sofort(seite):
    _klick_zeile(seite, "Offen")
    assert seite.aufrufe == [("helsinki", {"is_host": False, "lobby_code": "HAAAAA"})]


def test_beitreten_mit_passwort_fragt_zuerst(seite):
    olp = seite.olp
    _klick_zeile(seite, "Geheim")
    assert seite.aufrufe == []
    assert seite._view == olp._PASSWORD and seite._pw_ziel[1] == "HBBBBB"
    # zu kurzes Passwort wird nicht gesendet
    seite._pw_input.text = "abc"
    seite._pw_group.index = seite._pw_group.widgets.index(seite._btn_pw_join)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite.aufrufe == [] and seite._msg
    # richtig lang: gesendet, mit dem Passwort
    seite._pw_input.text = "Sesam"
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite.aufrufe == [("helsinki", {"is_host": False, "lobby_code": "HBBBBB",
                                           "password": "Sesam"})]


def test_falsches_passwort_fragt_hoeflich_noch_einmal(seite):
    olp = seite.olp
    seite._pw_ziel = (servers.by_prefix("H") or seite._server_defs[0], "HBBBBB")
    seite._pw_gesendet = True
    seite._view = olp._CONNECTING
    seite._on_net({"source": "tcp", "data": {"type": "JOIN_FAIL", "code": "BAD_PASSWORD",
                                             "need_password": True, "reason": "Falsches Passwort."}})
    assert seite._view == olp._PASSWORD
    assert "Passwort" in seite._msg and seite._pw_input.text == ""
    # nochmal versuchen geht ohne Umweg
    seite._pw_input.text = "richtig"
    seite._pw_group.index = seite._pw_group.widgets.index(seite._btn_pw_join)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite.aufrufe[-1][1]["password"] == "richtig"


def test_beitritt_per_code_zu_passwortlobby_fragt_nach(seite):
    olp = seite.olp
    seite._return_view = olp._JOIN
    seite._pw_ziel = (seite._server_defs[0], "HBBBBB")
    seite._pw_gesendet = False
    seite._view = olp._CONNECTING
    seite._on_net({"source": "tcp", "data": {"type": "JOIN_FAIL", "code": "BAD_PASSWORD",
                                             "need_password": True}})
    assert seite._view == olp._PASSWORD and seite._msg == ""    # nur fragen, nicht tadeln


def test_zu_viele_versuche_fuehren_zurueck_zur_liste(seite):
    olp = seite.olp
    seite._return_view = olp._BROWSER
    seite._pw_ziel = (seite._server_defs[0], "HBBBBB")
    seite._view = olp._CONNECTING
    seite._on_net({"source": "tcp", "data": {
        "type": "JOIN_FAIL", "code": "TOO_MANY_ATTEMPTS", "retry_after": 60,
        "reason": "Zu viele falsche Versuche. Bitte in einer Minute noch einmal probieren."}})
    assert seite._view == olp._BROWSER and "Versuche" in seite._msg


def _erstellen_klick(page):
    page._host_group.index = page._host_group.widgets.index(page._btn_create)
    page.handle_event(_taste(pygame.K_RETURN))


def test_erstellen_standard_ist_oeffentlich_mit_vorgabename(seite):
    olp = seite.olp
    seite._browser.b_erstellen.activate()
    seite._browser.gruppe.index = seite._browser.gruppe.widgets.index(seite._browser.b_erstellen)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite._view == olp._HOST_SERVER
    a = seite._angaben
    assert a.sichtbarkeit == "public" and not a.passwort_sichtbar()
    assert a.name.startswith("Lobby von ") and len(a.name) <= 24
    _erstellen_klick(seite)
    assert len(seite.aufrufe) == 1
    kw = seite.aufrufe[0][1]
    assert kw["is_host"] is True
    assert kw["angaben"]["visibility"] == "public"
    assert kw["angaben"]["lobby_name"] == a.name and "password" not in kw["angaben"]


def test_erstellen_mit_passwort_braucht_passwort_und_zeigt_das_feld(seite):
    olp = seite.olp
    seite._oeffne_erstellen()
    a = seite._angaben
    a.stepper.index = 1
    seite._host_gruppe_bauen(behalten=True)
    assert a.pw_feld in seite._host_group.widgets
    _erstellen_klick(seite)
    assert seite.aufrufe == [] and seite._msg            # ohne Passwort kein Start
    a.pw_feld.text = "abc"
    _erstellen_klick(seite)
    assert seite.aufrufe == []                           # zu kurz
    a.pw_feld.text = "geheim1"
    _erstellen_klick(seite)
    msg = seite.aufrufe[0][1]["angaben"]
    assert msg["visibility"] == "password" and msg["password"] == "geheim1"
    # zurueck auf privat: Feld weg, kein Passwort in der Nachricht
    a.stepper.index = 2
    seite._host_gruppe_bauen(behalten=True)
    assert a.pw_feld not in seite._host_group.widgets
    assert "password" not in a.nachricht("x") and a.nachricht("x")["visibility"] == "private"


def test_lobbyname_wird_wie_spielernamen_geprueft(seite, monkeypatch):
    from src.core import profile
    seite._oeffne_erstellen()
    a = seite._angaben
    monkeypatch.setattr(profile, "_ist_gesperrt", lambda t: "boese" in t.lower())
    a.name_feld.text = "Boese Runde"
    _erstellen_klick(seite)
    assert seite.aufrufe == [] and seite._msg
    a.name_feld.text = "Ordentlich <b>"
    seite._msg = ""
    _erstellen_klick(seite)
    assert seite.aufrufe == [] and seite._msg            # Zeichen nicht erlaubt
    a.name_feld.text = "Nette Runde"
    _erstellen_klick(seite)
    assert seite.aufrufe[0][1]["angaben"]["lobby_name"] == "Nette Runde"


def test_leerer_name_gilt_als_vorgabe(seite):
    seite._oeffne_erstellen()
    seite._angaben.name_feld.text = "   "
    _erstellen_klick(seite)
    assert seite.aufrufe[0][1]["angaben"]["lobby_name"].startswith("Lobby von")


def test_online_strecken_oeffnet_die_streckenseite(seite):
    b = seite._browser
    b.gruppe.index = b.gruppe.widgets.index(b.b_strecken)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite.shell.verlauf == ["online_strecken"]


def test_mit_code_beitreten_fuehrt_zur_codeeingabe(seite):
    b = seite._browser
    b.gruppe.index = b.gruppe.widgets.index(b.b_code)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite._view == seite.olp._JOIN


def test_esc_aus_der_liste_verlaesst_die_seite(seite):
    assert seite.handle_event(_taste(pygame.K_ESCAPE)) is False


# -- In der Lobby ------------------------------------------------------------

class _NetAttrappe:
    slot = 0
    ping_ms = 0.0

    def __init__(self):
        self.gesendet = []

    def send_tcp(self, msg):
        self.gesendet.append(msg)

    def poll(self):
        return []

    def update(self, dt):
        pass


def _in_lobby(page, monkeypatch, host=True):
    from src.net import session
    net = _NetAttrappe()
    monkeypatch.setattr(session, "get", lambda: net)
    page._is_host = host
    page._view = page.olp._LOBBY
    page._build_lobby_group()
    return net


def test_lobby_state_setzt_name_und_sichtbarkeit(seite, monkeypatch):
    _in_lobby(seite, monkeypatch, host=False)
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "lobby_name": "Meine\nRunde", "visibility": "password",
        "has_password": True, "players": [{"slot": 0, "name": "A", "is_host": True}],
        "settings": {}, "mode": "Rennen", "roster_size": 4}})
    assert seite._lobby_name == "Meine Runde" and seite._lobby_sicht == "password"
    assert seite._lobby_hat_pw is True
    # ein Relay ohne die Felder laesst den Stand, wie er ist
    seite._on_net({"source": "tcp", "data": {
        "type": "LOBBY_STATE", "players": [{"slot": 0, "name": "A", "is_host": True}],
        "settings": {}, "mode": "Rennen", "roster_size": 4}})
    assert seite._lobby_sicht == "password"


def test_host_aendert_sichtbarkeit_in_der_lobby(seite, monkeypatch):
    olp = seite.olp
    net = _in_lobby(seite, monkeypatch)
    seite._lobby_name, seite._lobby_sicht = "Alt", "public"
    assert seite._btn_lobbyinfo in seite._lobby_group.widgets
    seite._lobby_group.index = seite._lobby_group.widgets.index(seite._btn_lobbyinfo)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite._view == olp._LOBBY_EDIT
    a = seite._edit_angaben
    assert a.sichtbarkeit == "public" and a.name == "Alt"
    a.stepper.index = 1
    seite._edit_gruppe_bauen(behalten=True)
    a.pw_feld.text = "neupw1"
    a.name_feld.text = "Neu"
    seite._edit_group.index = seite._edit_group.widgets.index(seite._btn_edit_ok)
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite._view == olp._LOBBY
    assert net.gesendet[-1] == {"type": "SET_LOBBY_INFO", "visibility": "password",
                                "lobby_name": "Neu", "password": "neupw1"}


def test_name_aendern_ohne_neues_passwort_behaelt_das_alte(seite, monkeypatch):
    net = _in_lobby(seite, monkeypatch)
    seite._lobby_name, seite._lobby_sicht, seite._lobby_hat_pw = "Alt", "password", True
    seite._lobby_edit_oeffnen()
    a = seite._edit_angaben
    a.name_feld.text = "Zweiter"
    seite._edit_group.index = seite._edit_group.widgets.index(seite._btn_edit_ok)
    seite.handle_event(_taste(pygame.K_RETURN))
    msg = net.gesendet[-1]
    assert msg["visibility"] == "password" and "password" not in msg
    assert msg["lobby_name"] == "Zweiter"


def test_gast_hat_keinen_knopf_fuer_die_angaben(seite, monkeypatch):
    _in_lobby(seite, monkeypatch, host=False)
    seite._refresh_focus_group()
    assert seite._btn_lobbyinfo not in seite._lobby_group.widgets


def test_zurueck_aus_dem_bearbeiten_geht_in_die_lobby(seite, monkeypatch):
    _in_lobby(seite, monkeypatch)
    seite._lobby_edit_oeffnen()
    seite.handle_event(_taste(pygame.K_ESCAPE))
    assert seite._view == seite.olp._LOBBY


def test_alle_ansichten_lassen_sich_zeichnen(seite, monkeypatch):
    """Rauchprobe: keine Ansicht wirft beim Zeichnen."""
    olp = seite.olp
    schirm = pygame.Surface((1920, 1080))
    flaeche = pygame.Rect(0, 72, 1920, 1008)
    seite.draw(schirm, flaeche)
    seite._oeffne_erstellen()
    seite._angaben.stepper.index = 1
    seite._host_gruppe_bauen(behalten=True)
    seite.draw(schirm, flaeche)
    seite._view = olp._JOIN
    seite.draw(schirm, flaeche)
    seite._pw_ziel = (seite._server_defs[0], "HBBBBB")
    seite._view = olp._PASSWORD
    seite.draw(schirm, flaeche)
    _in_lobby(seite, monkeypatch)
    seite._lobby_name, seite._lobby_sicht = "Meine Lobby", "password"
    seite.draw(schirm, flaeche)
    seite._lobby_edit_oeffnen()
    seite.draw(schirm, flaeche)


def test_absage_wird_nicht_vom_getrennt_des_relays_ueberschrieben(seite):
    """Der Relay schliesst nach einer Absage die Verbindung. Dessen „getrennt"
    liegt schon in der Schlange und darf die Begruendung nicht ersetzen."""
    from src.net import session

    class Net:
        def __init__(self):
            self.ereignisse = [
                {"source": "tcp", "data": {"type": "JOIN_FAIL", "code": "LOBBY_FULL",
                                           "reason": "Lobby voll."}},
                {"source": "error", "data": {"type": "DISCONNECTED"}}]

        def poll(self):
            while self.ereignisse:
                yield self.ereignisse.pop(0)

        def disconnect(self):
            pass

    session.set(Net())
    try:
        seite._pw_ziel = None
        seite._return_view = seite.olp._BROWSER
        seite._view = seite.olp._CONNECTING
        seite.update(0.1)
        assert seite._view == seite.olp._BROWSER
        assert "voll" in seite._msg.lower() and "getrennt" not in seite._msg
    finally:
        session.clear()
