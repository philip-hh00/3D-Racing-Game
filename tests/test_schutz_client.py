"""Online-Schutz im Spiel (Plan 1.1.0): Pruefsumme, Rauswurf, Melden, „ungueltig".

Die Serverseite (Plausibilitaet, Rauswurfliste, Meldungsspeicher) hat ihre Tests
im Repo des Relays (``tests/test_schutz_server.py``); hier geht es um das, was das
Spiel dazu beitraegt:

* die Summe ist **kanonisch**: Zeilenenden, Einrueckung, Schluesselreihenfolge,
  BOM und Pfadtrenner aendern sie nicht, jeder geaenderte Wert schon;
* sie umfasst nur Spielrelevantes (nicht Profil, eigene Strecken, Lackierungen);
* das Werkzeug ``tools/pruefsummen.py`` traegt sie in ``server/pruefsummen.json``
  ein und prueft sie;
* der Client schickt ``game`` und ``files`` im ``HOST``/``JOIN``, und der echte
  Relay laesst ihn damit herein (und ohne/mit falscher Summe nicht);
* die Lobbyseite zeigt dem Host Kreuzknoepfe, fragt nach, schickt ``KICK`` und
  versteht ``KICKED`` und die neuen Absagen;
* die Ergebnisseite zeigt „ungueltig" und Fahnen zum Melden.
"""
from __future__ import annotations

import importlib.util
import json
import os
import socket
import struct
import sys
import types
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "server"))

import pygame  # noqa: E402

import relaishilfe  # noqa: E402
import server as srv  # noqa: E402
from src.core import integritaet  # noqa: E402
from src.core.version import VERSION  # noqa: E402

_LEN = struct.Struct("!I")


# ══ Kanonische Summe ═════════════════════════════════════════════════════════

FAHRZEUG = {"name": "Test", "physics": {"max_speed": 880.5, "engine_power": 1234.5, "mass": 1350},
            "gear_ratios": [3.5, 2.1, 1.4], "torque_curve": [[800, 144.0], [4000, 305]]}
STRECKE = {"name": "Oval", "track_width": 300.0,
           "centerline": [{"x": float(i * 100), "y": float((i % 3) * 50)} for i in range(20)]}


def _baum(wurzel: Path, *, crlf=False, einrueckung=None, bom=False, umgekehrt=False,
          fahrzeug=FAHRZEUG, strecke=STRECKE) -> Path:
    (wurzel / "data" / "vehicles").mkdir(parents=True, exist_ok=True)
    (wurzel / "data" / "tracks").mkdir(parents=True, exist_ok=True)

    def schreiben(pfad: Path, wert):
        if umgekehrt:
            wert = _umkehren(wert)
        text = json.dumps(wert, indent=einrueckung)
        if crlf:
            text = text.replace("\n", "\r\n")
        daten = text.encode("utf-8")
        pfad.write_bytes((b"\xef\xbb\xbf" if bom else b"") + daten)

    schreiben(wurzel / "data" / "vehicles" / "rookie.json", fahrzeug)
    schreiben(wurzel / "data" / "vehicles" / "supercar.json", dict(fahrzeug, name="Zwei"))
    schreiben(wurzel / "data" / "tracks" / "oval.json", strecke)
    return wurzel


def _umkehren(w):
    if isinstance(w, dict):
        return {k: _umkehren(w[k]) for k in reversed(list(w))}
    if isinstance(w, list):
        return [_umkehren(x) for x in w]
    return w


def test_summe_ist_unabhaengig_von_zeilenenden_einrueckung_bom_und_schluesselfolge(tmp_path):
    a = integritaet.digest(_baum(tmp_path / "a"))
    assert len(a) == 64
    for name, kw in (("crlf", dict(crlf=True, einrueckung=2)), ("bom", dict(bom=True)),
                     ("kompakt", dict(einrueckung=None)), ("tief", dict(einrueckung=8)),
                     ("umgekehrt", dict(umgekehrt=True, crlf=True, bom=True, einrueckung=1))):
        assert integritaet.digest(_baum(tmp_path / name, **kw)) == a, name


def test_jeder_geaenderte_wert_aendert_die_summe(tmp_path):
    a = integritaet.digest(_baum(tmp_path / "a"))
    schneller = json.loads(json.dumps(FAHRZEUG))
    schneller["physics"]["engine_power"] = 2469.0
    assert integritaet.digest(_baum(tmp_path / "b", fahrzeug=schneller)) != a
    kuerzer = json.loads(json.dumps(STRECKE))
    kuerzer["centerline"].pop()
    assert integritaet.digest(_baum(tmp_path / "c", strecke=kuerzer)) != a
    # 1 und 1.0 sind verschiedene Schreibweisen derselben Zahl: das ist bei JSON
    # derselbe Wert - Python rechnet aber unterschiedlich weiter (int/float).
    ganz = json.loads(json.dumps(FAHRZEUG))
    ganz["physics"]["mass"] = 1350.0
    assert integritaet.digest(_baum(tmp_path / "d", fahrzeug=ganz)) != a


def test_nur_spielrelevantes_geht_in_die_summe_ein(tmp_path):
    w = _baum(tmp_path / "a")
    a = integritaet.digest(w)
    (w / "data" / "vehicles" / "lacke.json").write_text('{"x": 1}', encoding="utf-8")     # Lackierungen
    (w / "data" / "vehicles" / "Rookie.png").write_bytes(b"\x89PNG")
    (w / "data" / "tracks" / "custom").mkdir()
    (w / "data" / "tracks" / "custom" / "meine.json").write_text("{}", encoding="utf-8")
    (w / "data" / "tracks" / "meine_strecke.json").write_text("{}", encoding="utf-8")      # kein mitgelieferter Name
    (w / "data" / "settings").mkdir()
    (w / "data" / "settings" / "profile.json").write_text('{"username": "x"}', encoding="utf-8")
    assert integritaet.digest(w) == a
    # Dateinamen sind Teil der Summe: ein umbenanntes Fahrzeug faellt auf.
    (w / "data" / "vehicles" / "rookie.json").rename(w / "data" / "vehicles" / "rookie2.json")
    assert integritaet.digest(w) != a


def test_schluessel_haben_nur_schraegstriche_und_die_reihenfolge_ist_egal(tmp_path, monkeypatch):
    w = _baum(tmp_path / "a")
    h = integritaet.hashes(w)
    assert all("\\" not in k and not k.startswith("/") for k in h)
    assert list(h) == sorted(h)
    a = integritaet.digest(w)
    # Das Dateisystem darf die Dateien in beliebiger Reihenfolge liefern
    # (Windows alphabetisch, macOS/Linux nicht).
    echtes_glob = Path.glob
    monkeypatch.setattr(Path, "glob", lambda self, m: reversed(list(echtes_glob(self, m))))
    assert integritaet.digest(w) == a


def test_kaputte_datei_geht_als_rohbytes_mit_gleichen_zeilenenden_ein(tmp_path):
    w = _baum(tmp_path / "a")
    (w / "data" / "vehicles" / "rookie.json").write_bytes(b"{kaputt\r\nzeile")
    a = integritaet.digest(w)
    (w / "data" / "vehicles" / "rookie.json").write_bytes(b"{kaputt\nzeile")
    assert integritaet.digest(w) == a
    assert a != integritaet.digest(_baum(tmp_path / "b"))


def test_die_summe_des_spiels_in_dieser_arbeitskopie_ist_stabil():
    """Zweimal gerechnet, gleiches Ergebnis; jede Datei geht ein."""
    a = integritaet.digest(_ROOT)
    assert a == integritaet.digest(_ROOT)
    h = integritaet.hashes(_ROOT)
    assert any(k.startswith("data/vehicles/") for k in h)
    assert any(k.startswith("data/tracks/") for k in h)
    assert "data/vehicles/lacke.json" not in h


def test_stand_liefert_dieselbe_summe_wie_digest():
    from src.core.paths import bundle_dir
    assert integritaet.stand().digest == integritaet.digest(bundle_dir())


# ══ tools/pruefsummen.py ═════════════════════════════════════════════════════

def _werkzeug():
    pfad = os.path.join(_ROOT, "tools", "pruefsummen.py")
    spec = importlib.util.spec_from_file_location("pruefsummen_werkzeug", pfad)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_server_eintrag_traegt_summe_tempo_und_streckenlaenge(tmp_path):
    w = _baum(tmp_path / "a")
    e = integritaet.server_eintrag(w)
    assert e["summen"] == [integritaet.digest(w)]
    assert e["fahrzeuge"] == {"rookie": 880.5, "supercar": 880.5}
    assert e["strecken"]["oval"] > 1500
    assert e["dateien"] == 3


def test_werkzeug_eintragen_ersetzt_nur_den_eigenen_eintrag(tmp_path, monkeypatch):
    t = _werkzeug()
    ziel = tmp_path / "pruefsummen.json"
    ziel.write_text(json.dumps({"format": 1, "spiele": {
        "2d": {"1.1.0": {"summen": ["f" * 64]}}, "3d": {"1.0.1": {"summen": ["e" * 64]}}}}),
        encoding="utf-8")
    eintrag = {"summen": ["a" * 64], "dateien": 1, "fahrzeuge": {}, "strecken": {}}
    t.eintragen(ziel, eintrag)
    d = json.loads(ziel.read_text(encoding="utf-8"))
    assert d["spiele"]["2d"]["1.1.0"]["summen"] == ["f" * 64]            # fremdes Spiel unberuehrt
    assert d["spiele"]["3d"]["1.0.1"]["summen"] == ["e" * 64]            # alte Version bleibt
    assert d["spiele"]["3d"][VERSION]["summen"] == ["a" * 64]
    # Ein zweiter Lauf aendert die Datei nicht.
    vorher = ziel.read_bytes()
    t.eintragen(ziel, eintrag)
    assert ziel.read_bytes() == vorher


def test_werkzeug_pruefen_meldet_abweichungen(tmp_path, capsys, monkeypatch):
    t = _werkzeug()
    ziel = tmp_path / "pruefsummen.json"
    monkeypatch.setattr(t.integritaet, "server_eintrag",
                        lambda wurzel: {"summen": ["a" * 64], "dateien": 1,
                                        "fahrzeuge": {"rookie": 800.0}, "strecken": {}})
    assert t.main(["--pruefen", str(ziel)]) == 1                         # Datei fehlt
    t.eintragen(ziel, t.integritaet.server_eintrag(None))
    assert t.main(["--pruefen", str(ziel)]) == 0
    d = json.loads(ziel.read_text(encoding="utf-8"))
    d["spiele"]["3d"][VERSION]["summen"] = ["b" * 64]
    ziel.write_text(json.dumps(d), encoding="utf-8")
    assert t.main(["--pruefen", str(ziel)]) == 1
    assert "Summe passt nicht" in capsys.readouterr().err


def test_werkzeug_eintragen_in_mehrere_dateien(tmp_path):
    t = _werkzeug()
    a, b = tmp_path / "a.json", tmp_path / "b" / "pruefsummen.json"
    assert t.main(["--eintragen", str(a), str(b)]) == 0
    for p in (a, b):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["spiele"]["3d"][VERSION]["summen"] == [integritaet.digest(_ROOT)]


def test_bauskripte_und_pipeline_rufen_die_pruefung_auf():
    """Die Pruefsumme muss im Release-Ablauf stehen, nicht nur im Kopf eines Werkzeugs."""
    def lies(*teile):
        return Path(_ROOT, *teile).read_text(encoding="utf-8")
    for pfad in (("Release", "skripte", "build_windows.bat"),
                 ("Release", "skripte", "build_macos.sh"),
                 ("Release", "skripte", "release_starten.sh"),
                 ("Release", "skripte", "release_starten.bat"),
                 (".github", "workflows", "release.yml")):
        assert "pruefsummen.py --pruefen" in lies(*pfad).replace("\\", "/"), pfad


# ══ Client und Relay ═════════════════════════════════════════════════════════

class _Draht:
    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=5)

    def roh(self, daten: bytes):
        self.s.sendall(daten)

    def empfangen(self):
        try:
            kopf = self._n(4)
            return json.loads(self._n(_LEN.unpack(kopf)[0]))
        except (OSError, ValueError):
            return None

    def _n(self, n):
        aus = b""
        while len(aus) < n:
            t = self.s.recv(n - len(aus))
            if not t:
                raise OSError
            aus += t
        return aus


class _Sockel:
    """Faengt ab, was ``NetworkClient.send_tcp`` verschickt."""
    def __init__(self):
        self.daten = b""

    def sendall(self, d):
        self.daten += d


def _client_paket(msg: dict) -> bytes:
    from src.net.client import NetworkClient
    c = NetworkClient()
    c._tcp = _Sockel()
    c.send_tcp(msg)
    return c._tcp.daten


def test_client_schickt_spiel_und_summe_bei_host_und_join():
    for art in ("HOST", "JOIN"):
        roh = _client_paket({"type": art, "name": "Anna"})
        msg = json.loads(roh[4:])
        assert msg["game"] == "3d" and msg["files"] == integritaet.stand().digest
        assert msg["version"] == VERSION
    anderes = json.loads(_client_paket({"type": "READY"})[4:])
    assert "files" not in anderes and "game" not in anderes


@pytest.fixture
def relay(tmp_path, monkeypatch):
    datei = tmp_path / "pruefsummen.json"
    datei.write_text(json.dumps({"format": 1, "spiele": {
        "3d": {VERSION: {"summen": [integritaet.stand().digest]}}}}), encoding="utf-8")
    monkeypatch.setenv("RACE_PRUEFSUMMEN_DATEI", str(datei))
    monkeypatch.setenv("RACE_FILES_CHECK", "enforce")
    monkeypatch.setattr(srv, "_wache", srv._Wache())
    r = relaishilfe.Relay()
    r.start()
    yield r
    r.stop()


def test_echter_relay_laesst_den_unveraenderten_client_herein(relay):
    d = _Draht(relay.port)
    d.roh(_client_paket({"type": "HOST", "name": "Anna"}))
    assert (d.empfangen() or {}).get("type") == "JOIN_OK"


def test_echter_relay_weist_veraenderte_dateien_ab(relay, monkeypatch):
    from src.core import integritaet as ig
    monkeypatch.setattr(ig, "_stand", ig.Ergebnis(ok=True, digest="d" * 64))
    d = _Draht(relay.port)
    d.roh(_client_paket({"type": "HOST", "name": "Anna"}))
    antwort = d.empfangen() or {}
    assert antwort.get("type") == "JOIN_FAIL" and antwort.get("code") == "MODIFIED_FILES"


def test_summe_wirklich_ohne_den_client_zu_senden_wird_abgewiesen(relay):
    """Ein veraenderter Client lässt die Felder einfach weg."""
    d = _Draht(relay.port)
    body = json.dumps({"type": "HOST", "name": "Mogler", "version": VERSION}).encode()
    d.roh(_LEN.pack(len(body)) + body)
    assert (d.empfangen() or {}).get("code") == "MODIFIED_FILES"


def test_der_client_kennt_die_fahrzeugnummern_des_relays():
    from src.net import protocol
    import schutz
    assert schutz.VEHICLE_TYPES == protocol.VEHICLE_TYPES


# ══ Lobbyseite: Entfernen ════════════════════════════════════════════════════

class _ShellAttrappe:
    def __init__(self):
        self.state_machine = types.SimpleNamespace(transition=lambda *a, **k: None)
        self.page_stack = []
        self.tab = 0

    def pop_page(self):
        pass

    def push_page(self, page):
        pass


class _Netz:
    slot = 0
    ping_ms = 10.0
    connected = True

    def __init__(self):
        self.gesendet = []

    def send_tcp(self, msg):
        self.gesendet.append(msg)

    def poll(self):
        return []

    def set_lobby(self, *a, **k):
        pass

    def register_udp(self):
        pass

    def disconnect(self):
        pass


@pytest.fixture
def lobby(monkeypatch):
    from src.net import server_probe, session
    from src.states.menu import online_lobby_page as olp
    monkeypatch.setattr(server_probe, "start", lambda: None)
    netz = _Netz()
    monkeypatch.setattr(session, "get", lambda: netz)
    seite = olp.OnlineLobbyPage()
    seite.enter(_ShellAttrappe())
    seite._is_host = True
    seite._view = olp._LOBBY
    seite._lobby_id = "H1AAAA"
    seite._players = [
        {"slot": 0, "name": "Anna", "is_host": True},
        {"slot": 1, "name": "Ben", "is_host": False},
        {"slot": 2, "name": "Cleo", "is_host": False},
    ]
    seite._roster_size = 4
    seite._rebuild_roster_widgets()
    seite._refresh_focus_group()
    seite.netz = netz
    seite.olp = olp
    return seite


def _taste(taste):
    return pygame.event.Event(pygame.KEYDOWN, key=taste, unicode="", mod=0)


def test_host_sieht_einen_kreuzknopf_je_anderem_menschen(lobby):
    assert [b.action for b in lobby._kick_buttons] == ["kick_1", "kick_2"]
    for b in lobby._kick_buttons:
        assert b in lobby._lobby_group.widgets          # mit Tastatur/Controller erreichbar
        assert pygame.Rect(0, 0, 1920, 1080).contains(b.rect)
    # Auf Hoehe der eigenen Zeile, rechts neben der Tabelle.
    zeile = lobby.olp._ROW_START_Y + 1 * lobby.olp._ROW_STRIDE
    assert zeile <= lobby._kick_buttons[0].rect.centery <= zeile + lobby.olp._ROW_H


def test_gast_sieht_keine_kreuzknoepfe(lobby):
    lobby._is_host = False
    lobby._rebuild_roster_widgets()
    lobby._refresh_focus_group()
    assert lobby._kick_buttons == []


def test_kreuzknoepfe_ueberdecken_nichts_anderes(lobby):
    for b in lobby._kick_buttons:
        for w in lobby._lobby_group.widgets:
            if w is not b and getattr(w, "rect", None) is not None and w.rect.w > 0:
                assert not b.rect.colliderect(w.rect), (b.action, w)


def test_lobby_zeichnet_mit_kreuzknoepfen(lobby):
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    lobby.draw(screen, pygame.Rect(0, 0, 1920, 1080))
    lobby._selected_mode = "Team-Zeitfahren"
    lobby._rebuild_roster_widgets()
    lobby.draw(screen, pygame.Rect(0, 0, 1920, 1080))


def test_klick_fragt_nach_und_schickt_erst_nach_ja_kick(lobby):
    b = lobby._kick_buttons[0]
    lobby.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=b.rect.center))
    assert lobby._dialog is not None and lobby._kick_ziel == (1, "Ben")
    assert "Ben" in lobby._dialog.message
    assert lobby.netz.gesendet == []                           # noch nichts geschickt
    # Nein
    lobby.handle_event(_taste(pygame.K_ESCAPE))
    assert lobby._dialog is None and lobby.netz.gesendet == []
    # Ja
    lobby.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=b.rect.center))
    lobby.handle_event(_taste(pygame.K_RETURN))                # Fokus steht auf „Ja"
    assert lobby.netz.gesendet == [{"type": "KICK", "slot": 1}]


def test_kick_mit_der_tastatur_erreichbar(lobby):
    b = lobby._kick_buttons[1]
    lobby._lobby_group.index = lobby._lobby_group.widgets.index(b)
    lobby.handle_event(_taste(pygame.K_RETURN))
    assert lobby._kick_ziel == (2, "Cleo")


def test_gast_kann_nicht_entfernen(lobby):
    lobby._is_host = False
    lobby._kick_fragen("kick_1")                               # direkter Aufruf ...
    lobby._kick_ziel = (1, "Ben")
    lobby._kick_senden()                                       # ... bleibt wirkungslos
    assert lobby.netz.gesendet == []


def test_wer_entfernt_wurde_landet_in_der_lobbyliste_mit_meldung(lobby):
    lobby._on_net({"source": "tcp", "data": {"type": "KICKED", "by": "Anna"}})
    assert lobby._view == lobby.olp._BROWSER
    assert "entfernt" in lobby._msg


@pytest.mark.parametrize("code", ["MODIFIED_FILES", "KICKED", "WRONG_GAME"])
def test_beitrittsabsagen_des_schutzes_werden_uebersetzt_angezeigt(lobby, code):
    from src.core.i18n import set_language, tr
    lobby._on_net({"source": "tcp", "data": {"type": "JOIN_FAIL", "code": code,
                                             "reason": "egal"}})
    assert lobby._msg and lobby._msg != "egal"
    set_language("en")
    try:
        lobby._on_net({"source": "tcp", "data": {"type": "JOIN_FAIL", "code": code, "reason": "egal"}})
        assert lobby._msg.isascii() or "–" in lobby._msg
        assert "Spiel" not in lobby._msg.split()[0:1]
    finally:
        set_language("de")


def test_kick_fehler_werden_gemeldet_ohne_die_lobby_zu_verlassen(lobby):
    lobby._on_net({"source": "tcp", "data": {"type": "ERROR", "code": "KICK_BUSY", "reason": "x"}})
    assert lobby._view == lobby.olp._LOBBY and lobby._msg


# ══ Ergebnisseite: ungueltig und Melden ══════════════════════════════════════

class _LobbyAttrappe:
    shell = None
    _race_begun = False
    _is_host = False
    _gp_view: dict = {}
    report_ergebnis = None

    def __init__(self):
        self._players = [{"slot": 0, "on_results": True}, {"slot": 1, "on_results": True},
                         {"slot": 2, "on_results": True}]

    def enter_results_vote(self):
        pass

    def leave_results_vote(self):
        pass

    def update(self, dt):
        pass

    def rematch_status(self):
        return 0, 3, {}, [0, 1, 2], True


def _zeile(name, pos, slot, **extra):
    return dict({"name": name, "position": pos, "online_slot": slot, "vehicle": "rookie",
                 "finish_time": 60.0 + pos, "best_lap": 20.0, "dnf": False, "is_player": False,
                 "is_player2": False, "team": "A"}, **extra)


@pytest.fixture
def ergebnis(monkeypatch):
    from src.net import session
    netz = _Netz()
    lp = _LobbyAttrappe()
    monkeypatch.setattr(session, "get", lambda: netz)
    monkeypatch.setattr(session, "get_lobby_page", lambda: lp)
    from src.states.menu.results_page import ResultsPage
    zeilen = [_zeile("Anna", 1, 0, is_player=True), _zeile("Ben", 2, 1),
              _zeile("Cleo", 4, 2, invalid=True, dnf=True, finish_time=None, best_lap=None),
              _zeile("KI 2", 3, -1)]

    def bauen(meta=None, rows=None):
        seite = ResultsPage(rows or zeilen, dict({"is_online": True, "track_key": "oval"}, **(meta or {})))
        seite.enter(_ShellAttrappe())
        seite.netz, seite.lp = netz, lp
        return seite
    bauen.netz, bauen.lp = netz, lp
    return bauen


def _zeichne(seite):
    screen = pygame.display.get_surface()
    screen.fill((0, 0, 0))
    seite.draw(screen, pygame.Rect(0, 0, 1920, 1080))
    return screen


def test_fahnen_nur_bei_anderen_menschen(ergebnis):
    seite = ergebnis()
    assert [b.action for b in seite._melde_knoepfe] == ["report_1", "report_2"]
    assert all(b in seite.group.widgets for b in seite._melde_knoepfe)
    _zeichne(seite)
    for b in seite._melde_knoepfe:
        assert pygame.Rect(0, 0, 1920, 1080).contains(b.rect)


def test_ohne_netz_oder_offline_keine_fahnen(ergebnis):
    assert ergebnis({"is_online": False})._melde_knoepfe == []


def test_fahnen_liegen_in_allen_darstellungen_im_bild_und_neben_ihrer_zeile(ergebnis):
    for meta in ({}, {"is_grand_prix": True}, {"is_team_zeitfahren": True}):
        seite = ergebnis(meta)
        if meta.get("is_grand_prix"):
            seite._gp_view = {"gp_active": True, "gp_race": 1, "gp_total": 3, "gp_standings": []}
        _zeichne(seite)
        seite._melden_layout()
        for b in seite._melde_knoepfe:
            assert pygame.Rect(0, 0, 1920, 1080).contains(b.rect), (meta, b.rect)
        # untereinander uebereinander gestapelt nur innerhalb einer Spalte, nie ueberlappend
        rs = [b.rect for b in seite._melde_knoepfe]
        assert not rs[0].colliderect(rs[1]), meta


def test_ungueltig_wird_angezeigt_und_zaehlt_nicht(ergebnis):
    seite = ergebnis()
    _zeichne(seite)
    # Die Darstellung stuerzt bei einer ungueltigen Zeile ohne Zeiten nicht.
    assert seite.rows[2]["invalid"] and seite.rows[2]["finish_time"] is None
    ersatz = ergebnis({"is_team_zeitfahren": True})
    from src.states.race_state import score_team_rows
    score_team_rows(ersatz.rows)
    _zeichne(ersatz)
    assert ersatz.rows[2]["score_time"] > 60.0                 # wie ein DNF gewertet


def test_melden_fragt_nach_dem_grund_und_schickt_ihn(ergebnis):
    seite = ergebnis()
    b = seite._melde_knoepfe[0]
    seite.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=b.rect.center))
    assert seite._melde_dialog is not None
    assert seite.netz.gesendet == []
    _zeichne(seite)                                            # der Dialog laesst sich zeichnen
    # Abbrechen schickt nichts
    seite.handle_event(_taste(pygame.K_ESCAPE))
    assert seite._melde_dialog is None and seite.netz.gesendet == []
    # Grund waehlen (zweiter Knopf = „Unsportlich")
    seite.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=b.rect.center))
    seite.handle_event(_taste(pygame.K_RIGHT))
    seite.handle_event(_taste(pygame.K_RETURN))
    assert seite.netz.gesendet == [{"type": "REPORT_PLAYER", "slot": 1, "name": "Ben",
                                    "reason": "griefing"}]
    assert not b.enabled                                       # nicht zweimal


def test_antwort_des_relays_wird_angezeigt_und_fehler_geben_die_fahne_frei(ergebnis):
    seite = ergebnis()
    b = seite._melde_knoepfe[0]
    seite._melde_ziel = b
    seite._melden_senden("cheating")
    seite.lp.report_ergebnis = ("ok", "Ben")
    seite.update(0.016)
    assert "Ben" in seite._status_msg and seite.lp.report_ergebnis is None
    seite._melde_ziel = seite._melde_knoepfe[1]
    seite._melden_senden("name")
    seite.lp.report_ergebnis = ("fehler", "Zu viele")
    seite.update(0.016)
    assert seite._status_msg == "Zu viele"
    assert all(k.enabled for k in seite._melde_knoepfe)


def test_lobbyseite_gibt_antworten_auf_meldungen_weiter(lobby):
    lobby._on_net({"source": "tcp", "data": {"type": "REPORT_OK", "name": "Ben"}})
    assert lobby.report_ergebnis == ("ok", "Ben")
    lobby._on_net({"source": "tcp", "data": {"type": "ERROR", "code": "REPORT_RATE", "reason": "x"}})
    art, text = lobby.report_ergebnis
    assert art == "fehler" and text and text != "x"


def test_rennseite_nimmt_invalid_und_platz_aus_den_ergebnissen_mit():
    quelle = Path(_ROOT, "src", "states", "race_state.py").read_text(encoding="utf-8")
    assert '"invalid": bool(r.get("invalid", False))' in quelle
    assert '"online_slot"' in quelle
