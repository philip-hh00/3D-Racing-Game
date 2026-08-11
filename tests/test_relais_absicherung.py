"""Block H, Stufen 2–4: der Relay wird **angegriffen**, nicht bedient (§7a H4).

Vorbild ist ``tests/test_block_g_online.py`` — echter Server aus
``server/server.py`` auf einem freien Port, echte Verbindungen. Der Unterschied
ist die Absicht: hier versucht jeder Test, etwas zu erreichen, was er nicht
darf. Bei einem Sicherheitsblock ist „behauptet" zu wenig (H6).

Je Befund ein Test, der ihn festhält:

============  =================================================================
H2.1          fremden Slot per ``UDP_REGISTER`` übernehmen → abgewiesen
H2.3          mehr Verbindungen und Lobbys öffnen als erlaubt → abgewiesen
H2.4          ``SET_SETTINGS`` mit 500 unbekannten Schlüsseln → Lobby wächst nicht
H2.5          ``addr_map`` wächst nicht über die Slots hinaus
H2.7          UDP-Flut wird nicht an bis zu fünf Peers ausgefächert
H2.8          kaputtes base64, ungültiges UTF-8 → Verbindung überlebt
H2.9          Lobbycodes aus ``secrets``, nicht aus ``random``
H2.12         Text vom Relay wird gekürzt und gekennzeichnet
H2.13         Name mit Steuerzeichen landet nicht in der Lobbyliste
H2.14         über die Lobbygrenze hinaus hosten → ``SERVER_BUSY``, **JOIN geht durch**
============  =================================================================

**Der Tunnel.** Hamburg hängt hinter playit.gg; dessen Agent läuft auf dem
Heimserver und verbindet sich nach ``127.0.0.1``. Dort kommen *alle* Spieler mit
derselben Quelladresse an, eine Grenze je IP würde den Server auf
``MAX_CONN_PER_IP`` Spieler insgesamt deckeln — also sich selbst abwürgen.
Deshalb steht ``127.0.0.1`` in ``TRUSTED_PROXIES``, und deshalb **leeren** die
Tests diese Liste, wo sie die Grenzen je IP prüfen: sonst prüften sie nichts.
Genau das ist auch der Grund, warum es die Aufnahmesperre (H2.14) gibt — sie
greift ohne IP-Unterscheidung.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import struct
import sys
import threading
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import relaishilfe  # noqa: E402
sys.path.insert(0, os.path.join(_ROOT, "server"))

import server as srv  # noqa: E402

from src.core.version import VERSION  # noqa: E402

_LEN = struct.Struct("!I")


# ── Aufbau ─────────────────────────────────────────────────────────────────
#: Der echte Server im Hintergrund. Die Klasse stand hier wortgleich wie in
#: zwei anderen Testdateien und ist am 06.08.2026 nach tests/relaishilfe.py
#: gewandert — samt der Begruendung, warum sauberes Herunterfahren noetig ist.
_Relay = relaishilfe.Relay


class _Draht:
    """Eine rohe TCP-Verbindung zum Relay — ohne ``NetworkClient`` dazwischen.

    Ein Angreifer benutzt unseren Client nicht; er schickt, was er will. Deshalb
    steht hier das Rahmenformat von Hand.
    """

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self.sock.settimeout(5.0)

    def senden(self, msg: dict) -> None:
        rumpf = json.dumps(msg).encode()
        self.sock.sendall(_LEN.pack(len(rumpf)) + rumpf)

    def roh(self, daten: bytes) -> None:
        self.sock.sendall(daten)

    def empfangen(self, zeit: float = 5.0) -> dict | None:
        self.sock.settimeout(zeit)
        try:
            kopf = self._genau(4)
            (laenge,) = _LEN.unpack(kopf)
            return json.loads(self._genau(laenge))
        except (OSError, ValueError, struct.error):
            return None

    def _genau(self, n: int) -> bytes:
        aus = b""
        while len(aus) < n:
            teil = self.sock.recv(n - len(aus))
            if not teil:
                raise OSError("Verbindung zu")
            aus += teil
        return aus

    def warten_auf(self, typ: str, zeit: float = 5.0) -> dict | None:
        ende = time.monotonic() + zeit
        while time.monotonic() < ende:
            msg = self.empfangen(max(0.2, ende - time.monotonic()))
            if msg is None:
                return None
            if msg.get("type") == typ:
                return msg
        return None

    def zu(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@pytest.fixture
def relay():
    srv._registry = srv._Registry()
    srv._wache = srv._Wache()
    r = _Relay()
    r.start()
    yield r
    r.stop()


@pytest.fixture
def ohne_tunnel(monkeypatch):
    """Die Grenzen je IP prüfen — dafür muss ``127.0.0.1`` unterscheidbar sein.

    Im Betrieb steht die Adresse in ``TRUSTED_PROXIES``, weil hinter dem
    playit.gg-Tunnel alle Spieler von dort kommen. Für den Test ist sie ein
    einzelner Angreifer.
    """
    monkeypatch.setattr(srv, "TRUSTED_PROXIES", frozenset())


def _host(relay, name: str = "Gastgeber") -> tuple[_Draht, dict]:
    d = _Draht(relay.port)
    d.senden({"type": "HOST", "name": name, "version": VERSION})
    antwort = d.empfangen()
    return d, (antwort or {})


def _join(relay, lid: str, name: str = "Gast") -> tuple[_Draht, dict]:
    d = _Draht(relay.port)
    d.senden({"type": "JOIN", "lobby_id": lid, "name": name, "version": VERSION})
    antwort = d.empfangen()
    return d, (antwort or {})


def _register(lid: str, slot: int, token: str) -> bytes:
    return (srv._S_ID.pack(srv.UDP_REGISTER, lid.encode()[:6].ljust(6, b"\x00"), slot)
            + token.encode()[:srv._TOKEN_B].ljust(srv._TOKEN_B, b"\x00"))


class _Merker:
    """Nimmt auf, wohin der UDP-Teil sendet, statt es wirklich zu tun."""

    def __init__(self) -> None:
        self.gesendet: list[tuple[bytes, tuple]] = []

    def sendto(self, daten, addr) -> None:
        self.gesendet.append((daten, addr))


def _udp_teil() -> srv._UDPRelay:
    teil = srv._UDPRelay()
    teil.transport = _Merker()
    return teil


# ---------------------------------------------------------------------------
# H2.1 — fremden Slot übernehmen
# ---------------------------------------------------------------------------
def _lobby_mit_zwei(relay):
    """Gastgeber und Gast, beide mit Token und beide UDP-registriert."""
    wirt, ok_h = _host(relay)
    lid = ok_h["lobby_id"]
    gast, ok_g = _join(relay, lid)
    return wirt, gast, lid, ok_h, ok_g


def test_jeder_bekommt_ein_eigenes_token(relay):
    wirt, gast, _lid, ok_h, ok_g = _lobby_mit_zwei(relay)
    try:
        assert ok_h.get("udp_token") and ok_g.get("udp_token")
        assert ok_h["udp_token"] != ok_g["udp_token"]
        assert len(ok_h["udp_token"]) == srv._TOKEN_B
    finally:
        wirt.zu(), gast.zu()


def test_ein_fremder_slot_laesst_sich_nicht_uebernehmen(relay):
    """Der Kern von H2.1: wer die Lobby-ID kennt, konnte den Positionsstrom
    eines fremden Spielers auf sich umleiten — ohne Token, ohne alles."""
    wirt, gast, lid, ok_h, _ok_g = _lobby_mit_zwei(relay)
    try:
        teil = _udp_teil()
        lobby = srv._registry.get(lid)
        angreifer = ("203.0.113.7", 55555)

        # 1. ohne Token
        teil.datagram_received(_register(lid, 0, ""), angreifer)
        assert lobby.clients[0].udp_addr != angreifer

        # 2. mit geratenem Token
        teil.datagram_received(_register(lid, 0, "0" * 16), angreifer)
        assert lobby.clients[0].udp_addr != angreifer

        # 3. mit dem Token des **anderen** Slots
        teil.datagram_received(_register(lid, 0, _ok_g["udp_token"]), angreifer)
        assert lobby.clients[0].udp_addr != angreifer

        # 4. mit dem richtigen Token geht es — sonst prüfte der Test nichts
        teil.datagram_received(_register(lid, 0, ok_h["udp_token"]), angreifer)
        assert lobby.clients[0].udp_addr == angreifer
    finally:
        wirt.zu(), gast.zu()


def test_die_quelladresse_muss_zur_verbindung_passen(relay, ohne_tunnel):
    """Stufe 1 der Gegenmaßnahme, ohne Tunnel: die IP allein reicht schon."""
    wirt, _ok = _host(relay)
    try:
        lid = _ok["lobby_id"]
        lobby = srv._registry.get(lid)
        lobby.clients[0].tcp_ip = "198.51.100.4"     # als käme er von dort
        teil = _udp_teil()
        teil.datagram_received(_register(lid, 0, _ok["udp_token"]),
                              ("203.0.113.7", 4242))
        assert lobby.clients[0].udp_addr is None
        teil.datagram_received(_register(lid, 0, _ok["udp_token"]),
                              ("198.51.100.4", 4242))
        assert lobby.clients[0].udp_addr == ("198.51.100.4", 4242)
    finally:
        wirt.zu()


def test_unter_fremder_slotnummer_senden_geht_nicht(relay):
    """Dieselbe Lücke innerhalb der eigenen Lobby: ein Mitglied gibt sich als
    ein anderer Slot aus und fernsteuert dessen Auto."""
    wirt, gast, lid, ok_h, ok_g = _lobby_mit_zwei(relay)
    try:
        teil = _udp_teil()
        a_addr, b_addr = ("127.0.0.1", 5001), ("127.0.0.1", 5002)
        teil.datagram_received(_register(lid, 0, ok_h["udp_token"]), a_addr)
        teil.datagram_received(_register(lid, 1, ok_g["udp_token"]), b_addr)
        teil.transport.gesendet.clear()
        # Der Gast (Slot 1) behauptet, Slot 0 zu sein.
        kopf = srv._S_HDR.pack(srv.UDP_STATE, lid.encode()[:6].ljust(6, b"\x00"), 0, 0)
        teil.datagram_received(kopf, b_addr)
        assert teil.transport.gesendet == []
    finally:
        wirt.zu(), gast.zu()


# ---------------------------------------------------------------------------
# H2.3 — Grenzen je IP und insgesamt
# ---------------------------------------------------------------------------
def _warten_bis(bedingung, zeit: float = 3.0) -> bool:
    ende = time.monotonic() + zeit
    while time.monotonic() < ende:
        if bedingung():
            return True
        time.sleep(0.02)
    return False


def test_mehr_verbindungen_als_erlaubt_werden_abgewiesen(relay, ohne_tunnel,
                                                        monkeypatch):
    """Gezählt wird ab dem Verbindungsaufbau, nicht ab der ersten Nachricht.

    Absichtlich **ohne** etwas zu senden: genau so hält ein Angreifer
    Verbindungen — ein Byte alle 59 s genügte vorher, um beliebig viele offen zu
    halten. Eine ``INFO``-Verbindung taugt hier nicht, weil der Server sie nach
    der Antwort schließt und den Platz sofort wieder freigibt.
    """
    monkeypatch.setattr(srv, "MAX_CONN_PER_IP", 3)
    offen = []
    try:
        for _ in range(3):
            offen.append(_Draht(relay.port))
        assert _warten_bis(lambda: srv._wache.verbindungen_gesamt() >= 3), \
            "der Server hat die drei nicht angenommen"
        d = _Draht(relay.port)
        offen.append(d)
        antwort = d.empfangen(3.0)
        assert antwort is not None, "die vierte lief einfach mit"
        assert antwort.get("type") == "JOIN_FAIL"
        assert antwort.get("code") == "TOO_MANY"
        assert antwort.get("reason")
    finally:
        for d in offen:
            d.zu()


def test_die_gesamtgrenze_gilt_auch_hinter_einem_tunnel(relay, monkeypatch):
    """Hinter playit.gg kommen alle von derselben Adresse — dort greift nur
    diese Grenze, und sie muss greifen."""
    monkeypatch.setattr(srv, "MAX_CONN_TOTAL", 2)
    offen = []
    try:
        for _ in range(2):
            offen.append(_Draht(relay.port))
        assert _warten_bis(lambda: srv._wache.verbindungen_gesamt() >= 2)
        d = _Draht(relay.port)
        offen.append(d)
        antwort = d.empfangen(3.0)
        assert antwort and antwort.get("code") == "SERVER_BUSY"
    finally:
        for d in offen:
            d.zu()


def test_mehr_lobbys_je_ip_als_erlaubt_werden_abgewiesen(relay, ohne_tunnel,
                                                        monkeypatch):
    monkeypatch.setattr(srv, "MAX_LOBBIES_PER_IP", 2)
    offen = []
    try:
        for _ in range(2):
            d, ok = _host(relay)
            offen.append(d)
            assert ok.get("type") == "JOIN_OK"
        d, ok = _host(relay)
        offen.append(d)
        assert ok.get("code") == "TOO_MANY"
        assert len(srv._registry.lobbies) == 2
    finally:
        for d in offen:
            d.zu()


def test_eine_geschlossene_lobby_gibt_ihren_platz_wieder_frei(relay, ohne_tunnel,
                                                             monkeypatch):
    """Sonst wäre die Grenze nach drei Lobbys für immer erreicht."""
    monkeypatch.setattr(srv, "MAX_LOBBIES_PER_IP", 1)
    d, ok = _host(relay)
    assert ok.get("type") == "JOIN_OK"
    d.zu()
    ende = time.monotonic() + 3.0
    while srv._registry.lobbies and time.monotonic() < ende:
        time.sleep(0.05)
    d2, ok2 = _host(relay)
    try:
        assert ok2.get("type") == "JOIN_OK", "der Platz kam nicht zurück"
    finally:
        d2.zu()


def test_eine_nachrichtenflut_beendet_die_verbindung(relay, ohne_tunnel,
                                                     monkeypatch):
    monkeypatch.setattr(srv, "MAX_MSG_PER_S", 5.0)
    monkeypatch.setattr(srv, "MSG_VORRAT", 5.0)
    monkeypatch.setattr(srv, "FLUT_ABBRUCH", 20)
    d, ok = _host(relay)
    try:
        assert ok.get("type") == "JOIN_OK"
        # Harmlose Nachrichten, aber viele: der Server soll sie verwerfen und
        # dann trennen, statt sie alle zu bearbeiten.
        for _ in range(200):
            try:
                d.senden({"type": "LOBBY_READY"})
            except OSError:
                break
        ende = time.monotonic() + 3.0
        zu = False
        while time.monotonic() < ende and not zu:
            try:
                d.sock.settimeout(0.2)
                if d.sock.recv(4096) == b"":
                    zu = True
            except socket.timeout:
                try:
                    d.senden({"type": "LOBBY_READY"})
                except OSError:
                    zu = True
            except OSError:
                zu = True
        assert zu, "die Flut lief unbegrenzt weiter"
    finally:
        d.zu()


def test_eine_streckenuebertragung_wird_nicht_gebremst(relay, ohne_tunnel):
    """Der teuerste erlaubte Vorgang, mit echten Zahlen.

    Der Client schickt eine Strecke in Stücken von 32766 B; 1 MB sind damit 32
    Stücke plus META und DONE. Zwei solche Übertragungen hintereinander (ein
    Vorschlag und der Streckentransfer beim Start) sind ~68 Nachrichten in
    wenigen Sekunden — sie müssen **alle** durchgehen, sonst bricht die
    Übertragung an der Ratenbegrenzung ab und niemand versteht, warum.
    """
    d, ok = _host(relay)
    try:
        d.senden({"type": "SET_SETTINGS", "settings": {"offers_enabled": True}})
        assert d.warten_auf("LOBBY_STATE") is not None
        import base64
        stueck = base64.b64encode(b"x" * 32766).decode()
        d.senden({"type": "OFFER_META", "size": 1024 * 1024, "track_name": "x.json"})
        for _ in range(32):
            d.senden({"type": "OFFER_CHUNK", "data": stueck})
        d.senden({"type": "OFFER_DONE"})
        liste = d.warten_auf("OFFER_LIST")
        assert liste is not None, "die Übertragung wurde unterwegs abgeschnitten"
        assert liste["offers"] and liste["offers"][0]["size"] == 32 * 32766
    finally:
        d.zu()


def test_eine_normale_spitze_wird_nicht_bestraft(relay, ohne_tunnel):
    """Beim Lobbybeitritt kommen mehrere Nachrichten auf einmal — das ist
    Betrieb, nicht Angriff. Dafür ist der Vorrat im Eimer da."""
    d, ok = _host(relay)
    try:
        for _ in range(20):
            d.senden({"type": "LOBBY_READY"})
            d.senden({"type": "LOBBY_UNREADY"})
        d.senden({"type": "CHAT", "text": "noch da?"})
        assert srv._registry.get(ok["lobby_id"]) is not None
        d.senden({"type": "SET_SETTINGS", "settings": {"laps": 5}})
        zustand = d.warten_auf("LOBBY_STATE")
        assert zustand is not None, "die Verbindung wurde zu Unrecht getrennt"
    finally:
        d.zu()


# ---------------------------------------------------------------------------
# H2.14 — Aufnahmesperre: HOST nein, JOIN ja
# ---------------------------------------------------------------------------
def test_ueber_der_lobbygrenze_wird_kein_host_mehr_angenommen(relay, monkeypatch):
    monkeypatch.setattr(srv, "MAX_LOBBIES", 2)
    offen = []
    try:
        for _ in range(2):
            d, ok = _host(relay)
            offen.append(d)
            assert ok.get("type") == "JOIN_OK"
        d, ok = _host(relay)
        offen.append(d)
        assert ok.get("code") == "SERVER_BUSY"
        # Ein Satz, der sagt, was zu tun ist — nicht nur „Fehler".
        assert "ausgelastet" in ok.get("reason", "").lower()
    finally:
        for d in offen:
            d.zu()


def test_ein_beitritt_geht_auch_bei_vollem_server_noch_durch(relay, monkeypatch):
    """Der ausdrückliche Wunsch aus H2.14: einem Freund den Beitritt in eine
    schon laufende Lobby zu verweigern wäre die falsche Sparsamkeit — der Slot
    ist ohnehin reserviert."""
    monkeypatch.setattr(srv, "MAX_LOBBIES", 1)
    wirt, ok = _host(relay)
    offen = [wirt]
    try:
        assert ok.get("type") == "JOIN_OK"
        assert srv._wache.laststufe() == srv.LAST_VOLL
        d, ok2 = _join(relay, ok["lobby_id"])
        offen.append(d)
        assert ok2.get("type") == "JOIN_OK", "JOIN muss durchgehen"
    finally:
        for d in offen:
            d.zu()


def test_info_traegt_die_laststufe_und_die_grenze(relay, monkeypatch):
    monkeypatch.setattr(srv, "MAX_LOBBIES", 4)
    d = _Draht(relay.port)
    try:
        d.senden({"type": "INFO", "version": VERSION})
        info = d.empfangen()
        assert info["lobby_count"] == 0
        assert info["lobby_max"] == 4
        assert info["load"] == srv.LAST_FREI
    finally:
        d.zu()


def test_ein_alter_client_liest_weiter_lobby_count(relay):
    """Der Anzeigeteil braucht **keinen** Versionsschnitt: das alte Feld bleibt,
    wo es war, und die neuen kommen daneben."""
    d = _Draht(relay.port)
    try:
        d.senden({"type": "INFO", "version": VERSION})
        info = d.empfangen()
        assert "lobby_count" in info
        for feld in ("required_version", "version_ok", "announcements", "server_tag"):
            assert feld in info, feld
    finally:
        d.zu()


@pytest.mark.parametrize("lobbys,erwartet", [
    (0, srv.LAST_FREI), (4, srv.LAST_FREI), (5, srv.LAST_GUT),
    (8, srv.LAST_GUT), (9, srv.LAST_VOLL), (10, srv.LAST_VOLL),
])
def test_die_laststufe_folgt_der_belegung(monkeypatch, lobbys, erwartet):
    monkeypatch.setattr(srv, "MAX_LOBBIES", 10)
    monkeypatch.setattr(srv, "_registry", srv._Registry())
    monkeypatch.setattr(srv, "_wache", srv._Wache())
    for _ in range(lobbys):
        srv._registry.create()
    assert srv._wache.laststufe() == erwartet


# ---------------------------------------------------------------------------
# H2.4 — settings nimmt nur bekannte Schlüssel
# ---------------------------------------------------------------------------
def test_fuenfhundert_unbekannte_schluessel_lassen_die_lobby_nicht_wachsen(relay):
    d, ok = _host(relay)
    try:
        lobby = srv._registry.get(ok["lobby_id"])
        d.senden({"type": "SET_SETTINGS", "settings": {
            "laps": 4, **{f"muell_{i}": "x" * 100 for i in range(500)}}})
        assert d.warten_auf("LOBBY_STATE") is not None
        assert set(lobby.settings) <= srv.SETTINGS_KEYS
        assert lobby.settings.get("laps") == 4, "das Bekannte muss ankommen"
        assert not any(k.startswith("muell_") for k in lobby.settings)
    finally:
        d.zu()


def test_eine_zu_grosse_ablage_wird_abgewiesen(relay, monkeypatch):
    monkeypatch.setattr(srv, "MAX_SETTINGS_B", 2048)
    d, ok = _host(relay)
    try:
        lobby = srv._registry.get(ok["lobby_id"])
        d.senden({"type": "SET_SETTINGS",
                  "settings": {"gp_points": {str(i): i for i in range(5000)}}})
        fehler = d.warten_auf("ERROR")
        assert fehler and fehler.get("code") == "SETTINGS_TOO_BIG"
        assert srv._settings_groesse(lobby.settings) <= 2048
    finally:
        d.zu()


def test_der_bekannte_serienzustand_passt_weiter_durch(relay):
    """Die Erlaubnisliste darf den Grand Prix nicht abschneiden — er reist
    vollständig in ``settings`` mit."""
    d, ok = _host(relay)
    try:
        lobby = srv._registry.get(ok["lobby_id"])
        d.senden({"type": "SET_SETTINGS", "settings": {
            "mode": "Grand Prix", "gp_active": True, "gp_race": 2,
            "gp_total": 5, "gp_points": {"philip": 25},
            "gp_standings": [{"name": "philip", "points": 25}],
            "gp_members": {"philip": True}, "gp_locked": True,
            "gp_phase": "overview", "gp_tracks": [], "gp_track_key": "oval",
            "gp_raced": ["oval"], "gp_finished": False, "offers_enabled": True,
        }})
        assert d.warten_auf("LOBBY_STATE") is not None
        assert lobby.settings["gp_points"] == {"philip": 25}
        assert lobby.settings["gp_locked"] is True
        assert lobby.settings["offers_enabled"] is True
    finally:
        d.zu()


def test_jeder_schluessel_den_der_client_schickt_ist_erlaubt():
    """Sonst fällt beim nächsten Feld still etwas weg. Geprüft gegen den
    Quelltext des Clients, nicht gegen eine zweite Liste."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu",
                               "online_lobby_page.py"), encoding="utf-8").read()
    import ast
    baum = ast.parse(quelle)
    gesucht = ("_push_settings", "_gp_settings_payload")
    fehlend = set()
    for knoten in ast.walk(baum):
        if not (isinstance(knoten, ast.FunctionDef) and knoten.name in gesucht):
            continue
        for k in ast.walk(knoten):
            if isinstance(k, ast.Dict):
                for schluessel in k.keys:
                    if (isinstance(schluessel, ast.Constant)
                            and isinstance(schluessel.value, str)
                            and schluessel.value not in srv.SETTINGS_KEYS
                            # Der Umschlag der Nachricht selbst („type",
                            # „settings") und die Schlüssel *innerhalb* eines
                            # Wertes (etwa {"name": …} in gp_standings) sind
                            # keine settings-Schlüssel.
                            and schluessel.value not in (
                                "type", "settings",
                                "name", "points", "vehicle", "team")):
                        fehlend.add(schluessel.value)
    assert not fehlend, f"Client schickt, Server verwirft: {sorted(fehlend)}"


# ---------------------------------------------------------------------------
# H2.5 — addr_map wächst nicht
# ---------------------------------------------------------------------------
def test_die_adresstabelle_waechst_nicht_mit_jedem_wechsel(relay):
    """Vorher hing das Aufräumen an der **letzten** Adresse eines Clients; jede
    frühere blieb liegen und zeigte weiter auf den Slot."""
    wirt, ok = _host(relay)
    try:
        lid = ok["lobby_id"]
        teil = _udp_teil()
        for port in range(6000, 6010):
            teil.datagram_received(_register(lid, 0, ok["udp_token"]),
                                  ("127.0.0.1", port))
        assert len(srv._registry.addr_map) == 1
        assert srv._registry.slot_for_addr(("127.0.0.1", 6009)) == 0
    finally:
        wirt.zu()


def test_beim_trennen_verschwindet_der_eintrag(relay):
    wirt, ok = _host(relay)
    lid = ok["lobby_id"]
    teil = _udp_teil()
    teil.datagram_received(_register(lid, 0, ok["udp_token"]), ("127.0.0.1", 6100))
    assert srv._registry.addr_map
    wirt.zu()
    ende = time.monotonic() + 3.0
    while srv._registry.addr_map and time.monotonic() < ende:
        time.sleep(0.05)
    assert not srv._registry.addr_map, "die Adresse blieb liegen"


# ---------------------------------------------------------------------------
# H2.7 — keine Verstärkung ×5 innerhalb der Lobby
# ---------------------------------------------------------------------------
def test_eine_udp_flut_wird_nicht_ausgefaechert(relay, monkeypatch):
    monkeypatch.setattr(srv, "MAX_UDP_PER_S", 10)
    wirt, gast, lid, ok_h, ok_g = _lobby_mit_zwei(relay)
    try:
        teil = _udp_teil()
        a, b = ("127.0.0.1", 6200), ("127.0.0.1", 6201)
        teil.datagram_received(_register(lid, 0, ok_h["udp_token"]), a)
        teil.datagram_received(_register(lid, 1, ok_g["udp_token"]), b)
        teil.transport.gesendet.clear()
        kopf = srv._S_HDR.pack(srv.UDP_STATE, lid.encode()[:6].ljust(6, b"\x00"), 0, 0)
        for _ in range(100):
            teil.datagram_received(kopf, a)
        assert len(teil.transport.gesendet) <= 10, \
            f"{len(teil.transport.gesendet)} Pakete weitergegeben"
    finally:
        wirt.zu(), gast.zu()


def test_normales_senden_kommt_vollstaendig_an(relay):
    """30 Pakete/s sendet das Spiel — die Grenze darf den Betrieb nicht treffen."""
    wirt, gast, lid, ok_h, ok_g = _lobby_mit_zwei(relay)
    try:
        teil = _udp_teil()
        a, b = ("127.0.0.1", 6300), ("127.0.0.1", 6301)
        teil.datagram_received(_register(lid, 0, ok_h["udp_token"]), a)
        teil.datagram_received(_register(lid, 1, ok_g["udp_token"]), b)
        teil.transport.gesendet.clear()
        kopf = srv._S_HDR.pack(srv.UDP_STATE, lid.encode()[:6].ljust(6, b"\x00"), 0, 0)
        for _ in range(30):
            teil.datagram_received(kopf, a)
        assert len(teil.transport.gesendet) == 30
    finally:
        wirt.zu(), gast.zu()


# ---------------------------------------------------------------------------
# H2.8 — kaputte Eingaben beenden keine Verbindung
# ---------------------------------------------------------------------------
def test_kaputtes_base64_beendet_die_verbindung_nicht(relay):
    d, ok = _host(relay)
    try:
        lid = ok["lobby_id"]
        d.senden({"type": "SET_SETTINGS", "settings": {"offers_enabled": True}})
        assert d.warten_auf("LOBBY_STATE") is not None
        d.senden({"type": "OFFER_META", "size": 100, "track_name": "x.json"})
        d.senden({"type": "OFFER_CHUNK", "data": "das ist kein base64!!!"})
        fehler = d.warten_auf("ERROR")
        assert fehler and fehler.get("code") == "OFFER_BROKEN"
        # Und die Lobby steht noch.
        d.senden({"type": "SET_SETTINGS", "settings": {"laps": 7}})
        assert d.warten_auf("LOBBY_STATE") is not None
        assert srv._registry.get(lid) is not None
    finally:
        d.zu()


def test_ungueltiges_utf8_beendet_nur_diese_nachricht(relay):
    d, ok = _host(relay)
    try:
        rumpf = b'{"type": "CHAT", "text": "\xff\xfe"}'
        d.roh(_LEN.pack(len(rumpf)) + rumpf)
        # _recv gibt None → die Schleife bricht ab und die Verbindung geht zu.
        # Entscheidend ist, dass der **Server** weiterläuft: eine neue
        # Verbindung muss sofort wieder bedient werden.
        d2 = _Draht(relay.port)
        try:
            d2.senden({"type": "INFO", "version": VERSION})
            assert d2.empfangen(), "der Server ist mitgegangen"
        finally:
            d2.zu()
    finally:
        d.zu()


@pytest.mark.parametrize("rumpf", [b"5", b'"text"', b"[1,2,3]", b"null",
                                   b"{", b"[" * 200])
def test_gueltiges_json_das_kein_objekt_ist_wird_verworfen(relay, rumpf):
    """``json.loads(b"5")`` ergibt eine Zahl, und der ganze Nachrichtenweg ruft
    danach ``msg.get(...)``."""
    d = _Draht(relay.port)
    try:
        d.roh(_LEN.pack(len(rumpf)) + rumpf)
        d2 = _Draht(relay.port)
        try:
            d2.senden({"type": "INFO", "version": VERSION})
            assert d2.empfangen()
        finally:
            d2.zu()
    finally:
        d.zu()


def test_ein_zu_kurzes_udp_paket_stuerzt_nicht_ab(relay):
    teil = _udp_teil()
    for daten in (b"\x00", b"\x00\x01", b"\x01\x02\x03", b"\x02" * 3,
                  bytes([srv.UDP_REGISTER]) + b"AB"):
        teil.datagram_received(daten, ("127.0.0.1", 7000))
    assert teil.transport.gesendet == []


# ---------------------------------------------------------------------------
# H2.9 — Lobbycodes
# ---------------------------------------------------------------------------
def test_lobbycodes_kommen_aus_secrets():
    """Der Code ist die **einzige** Zugangskontrolle. Aus ``random`` sind fünf
    Zeichen vorhersagbar, sobald man ein paar Codes gesehen hat — und Codes sieht
    jeder, der eine Lobby aufmacht."""
    quelle = open(os.path.join(_ROOT, "server", "server.py"), encoding="utf-8").read()
    erzeugen = quelle.split("def create(self)")[1].split("\n    def ")[0]
    assert "secrets.choice" in erzeugen
    assert "random." not in erzeugen


def test_die_codes_wiederholen_sich_nicht(monkeypatch):
    monkeypatch.setattr(srv, "_registry", srv._Registry())
    codes = {srv._registry.create().lobby_id for _ in range(200)}
    assert len(codes) == 200
    assert all(c[0] == srv.SERVER_TAG and len(c) == 6 for c in codes)


# ---------------------------------------------------------------------------
# H2.13 — Namen
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("roh,erwartet", [
    ("Philip", "Philip"),
    ("Müller-Lüdenscheidt", "Müller-Lüdenscheidt"),
    ("Спартак", "Спартак"),
    ("", "Spieler"),
    ("   ", "Spieler"),
    ("\n\n\n", "Spieler"),
    ("Zeile1\nZeile2", "Zeile1Zeile2"),
    ("a\x00b", "ab"),
    ("\x1b[31mrot", "31mrot"),
    ("<script>", "script"),
    ("x" * 100, "x" * 20),
])
def test_namen_werden_auf_unbedenkliche_zeichen_gebracht(roh, erwartet):
    assert srv.saeubere_name(roh) == erwartet


def test_ein_name_mit_steuerzeichen_landet_nicht_in_der_lobbyliste(relay):
    wirt, ok = _host(relay)
    try:
        d, _ok2 = _join(relay, ok["lobby_id"], name="Ha\x00ck\ner\x1b[0m")
        try:
            zustand = wirt.warten_auf("LOBBY_STATE")
            assert zustand is not None
            namen = [p["name"] for p in zustand["players"]]
            for name in namen:
                assert "\x00" not in name and "\n" not in name and "\x1b" not in name
        finally:
            d.zu()
    finally:
        wirt.zu()


# ---------------------------------------------------------------------------
# H2.12 — Text vom Relay
# ---------------------------------------------------------------------------
def test_ein_langer_servertext_wird_gekuerzt():
    from src.net import servertext
    aus = servertext.saeubern("A" * 5000)
    assert len(aus) <= servertext.MAX_ZEICHEN + 1
    assert aus.endswith("…")


def test_steuerzeichen_und_richtungszeichen_fliegen_raus():
    from src.net import servertext
    aus = servertext.saeubern("Datei‮sicher​\x07 hier")
    assert "‮" not in aus and "​" not in aus and "\x07" not in aus
    assert "sicher" in aus


def test_eine_wand_aus_zeilenumbruechen_wird_begrenzt():
    from src.net import servertext
    aus = servertext.saeubern("\n".join(f"Zeile {i}" for i in range(500)))
    assert aus.count("\n") < servertext.MAX_ZEILEN


def test_eine_ueberschrift_bleibt_einzeilig():
    from src.net import servertext
    aus = servertext.saeubern("Titel\nzweite Zeile", 80, zeilen=False)
    assert "\n" not in aus


def test_eine_ankuendigung_vom_relay_wird_gesaeubert():
    from src.net import servertext
    aus = servertext.saeubere_ankuendigung({
        "id": "x\x00y", "date": "2026-08-04\n\n",
        "title": {"de": "Titel‮" + "!" * 500},
        "text": {"de": "Text\x07", **{f"xx{i}": "y" for i in range(50)}},
    })
    assert aus["id"] == "xy"
    assert "\n" not in aus["date"]
    assert len(aus["title"]["de"]) <= servertext.MAX_TITEL + 1
    assert "‮" not in aus["title"]["de"]
    assert aus["text"]["de"] == "Text"
    assert len(aus["text"]) <= 8, "ein Relay legt sonst beliebig viele Sprachen ab"


def test_die_ankuendigung_ist_als_servernachricht_gekennzeichnet():
    """Ein Fremdtext soll nicht wie eine Aussage des Spiels aussehen."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu_shell_state.py"),
                  encoding="utf-8").read()
    assert 'tr("Servernachricht")' in quelle


def test_jeder_grund_vom_relay_laeuft_durch_die_saeuberung():
    """Vier Stellen zeigen ``reason`` an; jede muss über den Helfer gehen."""
    quelle = open(os.path.join(_ROOT, "src", "states", "menu",
                               "online_lobby_page.py"), encoding="utf-8").read()
    import re
    for treffer in re.finditer(r'tr\(data\.get\("reason"', quelle):
        zeile = quelle[:treffer.start()].count("\n") + 1
        assert False, f"reason ungesäubert angezeigt, Zeile {zeile}"
