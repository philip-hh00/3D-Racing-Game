"""Lobbyliste auf dem Relay: Sichtbarkeit, Passwort, Status, Grenzen (Plan 1.1.0).

Alles gegen einen echten Relay auf einem freien Port (``Relay`` aus
``strecken_hilfe``), die Host-/Gast-Verbindungen sind echte TCP-Verbindungen.
"""
from __future__ import annotations

import asyncio
import hmac

import pytest

from tests.strecken_hilfe import Relay, empfangen, senden, srv


def _lauf(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _frische_zaehler(monkeypatch):
    """Jeder Test beginnt mit leeren Zaehlern - sie sind prozessweit."""
    monkeypatch.setattr(srv, "_wache", srv._Wache())
    monkeypatch.setattr(srv, "_pw_wache", srv._PwWache())
    monkeypatch.setattr(srv, "_lobbyliste_zeiten", {})
    monkeypatch.setattr(srv, "MAX_LOBBIES_PER_IP", 50)
    monkeypatch.setattr(srv, "MAX_CONN_PER_IP", 50)


def _version() -> str:
    return str(srv._load_live_config().get("required_version", ""))


async def _hosten(relay, name="Anna", **extra):
    r, w = await asyncio.open_connection("127.0.0.1", relay.port)
    await senden(w, dict({"type": "HOST", "name": name, "version": _version()}, **extra))
    ok = await empfangen(r)
    return r, w, ok


async def _beitreten(relay, code, name="Ben", **extra):
    r, w = await asyncio.open_connection("127.0.0.1", relay.port)
    await senden(w, dict({"type": "JOIN", "name": name, "lobby_id": code,
                          "version": _version()}, **extra))
    antwort = await empfangen(r)
    return r, w, antwort


async def _liste(relay, **extra):
    a = await relay.frage(dict({"type": "LOBBY_LIST"}, **extra))
    assert a and a["type"] == "LOBBY_LIST", a
    return a["lobbies"]


async def _bis(reader, typ, versuche=8):
    for _ in range(versuche):
        m = await empfangen(reader)
        if m is None:
            return None
        if m.get("type") == typ:
            return m
    return None


def _relay(tmp_path, **kw):
    return Relay(str(tmp_path), **kw)


# --------------------------------------------------------------------------
# Sichtbarkeit und Liste
# --------------------------------------------------------------------------

def test_oeffentlich_passwort_und_privat_in_der_liste(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, w1, ok1 = await _hosten(relay, "Anna", visibility="public",
                                       lobby_name="Offene Runde")
            _, w2, ok2 = await _hosten(relay, "Berta", visibility="password",
                                       lobby_name="Geheim", password="abcd")
            _, w3, ok3 = await _hosten(relay, "Carl", visibility="private",
                                       lobby_name="Versteckt")
            liste = await _liste(relay)
            codes = {e["code"]: e for e in liste}
            assert ok1["lobby_id"] in codes and ok2["lobby_id"] in codes
            assert ok3["lobby_id"] not in codes        # privat: nie gelistet
            a = codes[ok1["lobby_id"]]
            assert a["name"] == "Offene Runde" and a["host"] == "Anna"
            assert a["players"] == 1 and a["max"] >= 2
            assert a["status"] == "lobby" and a["password"] is False
            assert codes[ok2["lobby_id"]]["password"] is True
            for w in (w1, w2, w3):
                w.close()
    _lauf(go())


def test_host_ohne_neue_felder_ist_privat(tmp_path):
    """Abwaertskompatibel: ein aelteres Spiel kennt die Felder nicht."""
    async def go():
        async with _relay(tmp_path) as relay:
            _, w, ok = await _hosten(relay, "Alt")
            assert ok["type"] == "JOIN_OK"
            assert ok["visibility"] == "private"
            assert await _liste(relay) == []
            # Beitritt per Code geht wie immer.
            _, wg, gast = await _beitreten(relay, ok["lobby_id"])
            assert gast["type"] == "JOIN_OK"
            w.close(); wg.close()
    _lauf(go())


def test_standardname_und_bereinigung(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, w1, ok1 = await _hosten(relay, "Anna", visibility="public")
            _, w2, ok2 = await _hosten(
                relay, "Berta", visibility="public",
                lobby_name="Böse\n‮Name<script>" + "x" * 80)
            namen = {e["code"]: e["name"] for e in await _liste(relay)}
            assert namen[ok1["lobby_id"]] == "Anna's Lobby"
            n = namen[ok2["lobby_id"]]
            assert len(n) <= srv.LOBBYNAME_MAX
            assert "\n" not in n and "‮" not in n and "<" not in n
            w1.close(); w2.close()
    _lauf(go())


def test_ungueltige_sichtbarkeit_und_passwort_beim_hosten(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            for extra, code in (
                    ({"visibility": "geheim"}, "BAD_VISIBILITY"),
                    ({"visibility": 7}, "BAD_VISIBILITY"),
                    ({"visibility": "password"}, "BAD_PASSWORD_FORMAT"),
                    ({"visibility": "password", "password": "abc"}, "BAD_PASSWORD_FORMAT"),
                    ({"visibility": "password", "password": "x" * 17}, "BAD_PASSWORD_FORMAT"),
                    ({"visibility": "password", "password": "ab\ncd"}, "BAD_PASSWORD_FORMAT"),
                    ({"visibility": "password", "password": 12345}, "BAD_PASSWORD_FORMAT")):
                _, w, antwort = await _hosten(relay, **extra)
                assert antwort["type"] == "JOIN_FAIL" and antwort["code"] == code, extra
                w.close()
            assert srv._registry.lobbies == {}      # nichts angelegt
    _lauf(go())


def test_liste_verraet_keinen_hash_und_nichts_ueber_private(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, w, ok = await _hosten(relay, visibility="password", password="geheim1")
            roh = await relay.frage({"type": "LOBBY_LIST"})
            text = str(roh)
            assert "geheim1" not in text and "salt" not in text and "hash" not in text
            w.close()
    _lauf(go())


def test_lobby_state_nennt_name_und_sichtbarkeit_aber_keinen_hash(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, "Anna", visibility="password",
                                       password="pass1234", lobby_name="Runde 1")
            rg, wg, gast = await _beitreten(relay, ok["lobby_id"], password="pass1234")
            assert gast["type"] == "JOIN_OK"
            st = await _bis(rg, "LOBBY_STATE")
            assert st["lobby_name"] == "Runde 1"
            assert st["visibility"] == "password" and st["has_password"] is True
            assert "pass1234" not in str(st)
            wh.close(); wg.close()
    _lauf(go())


# --------------------------------------------------------------------------
# Passwort
# --------------------------------------------------------------------------

def test_beitritt_mit_richtigem_und_falschem_passwort(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, wh, ok = await _hosten(relay, visibility="password", password="Sesam")
            code = ok["lobby_id"]
            # ohne Passwort: fragt nach, zaehlt nicht als Fehlversuch
            _, w0, a0 = await _beitreten(relay, code)
            assert a0["type"] == "JOIN_FAIL" and a0["code"] == "BAD_PASSWORD"
            assert a0["need_password"] is True
            # falsch
            _, w1, a1 = await _beitreten(relay, code, password="falsch")
            assert a1["type"] == "JOIN_FAIL" and a1["code"] == "BAD_PASSWORD"
            # richtig
            _, w2, a2 = await _beitreten(relay, code, password="Sesam")
            assert a2["type"] == "JOIN_OK"
            assert len(srv._registry.lobbies[code].clients) == 2
            for w in (wh, w0, w1, w2):
                w.close()
    _lauf(go())


def test_passwort_nur_als_salz_und_hash(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, w1, ok1 = await _hosten(relay, visibility="password", password="gleich1")
            _, w2, ok2 = await _hosten(relay, visibility="password", password="gleich1")
            a = srv._registry.lobbies[ok1["lobby_id"]]
            b = srv._registry.lobbies[ok2["lobby_id"]]
            assert a.pw_hash and a.pw_salt
            assert b"gleich1" not in a.pw_hash + a.pw_salt
            assert a.pw_salt != b.pw_salt            # jedes Mal frisches Salz
            assert a.pw_hash != b.pw_hash            # gleiches Passwort, anderer Hash
            assert "gleich1" not in repr(a.__dict__)
            w1.close(); w2.close()
    _lauf(go())


def test_passwortvergleich_in_konstanter_zeit(tmp_path, monkeypatch):
    aufrufe = []
    echt = hmac.compare_digest

    def spion(a, b):
        aufrufe.append((a, b))
        return echt(a, b)
    monkeypatch.setattr(srv.hmac, "compare_digest", spion)
    lobby = srv.Lobby(lobby_id="HAAAAA")
    srv.pw_setzen(lobby, "Sesam")
    assert srv.pw_stimmt(lobby, "Sesam") and not srv.pw_stimmt(lobby, "sesam")
    assert not srv.pw_stimmt(lobby, 123) and not srv.pw_stimmt(lobby, "x" * 500)
    assert len(aufrufe) == 2                      # genau die beiden echten Vergleiche


def test_fehlversuche_je_ip_werden_gesperrt(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "PW_VERSUCHE", 3)

    async def go():
        async with _relay(tmp_path) as relay:
            _, wh, ok = await _hosten(relay, visibility="password", password="Sesam")
            code = ok["lobby_id"]
            for _ in range(3):
                _, w, a = await _beitreten(relay, code, password="falsch")
                assert a["code"] == "BAD_PASSWORD"
                w.close()
            # jetzt gesperrt - auch das richtige Passwort kommt nicht durch
            _, w, a = await _beitreten(relay, code, password="Sesam")
            assert a["type"] == "JOIN_FAIL" and a["code"] == "TOO_MANY_ATTEMPTS"
            assert a["retry_after"] > 0
            w.close(); wh.close()
    _lauf(go())


def test_hinter_dem_tunnel_zaehlt_die_cid(tmp_path, monkeypatch):
    """Hamburg: alle kommen von derselben Adresse. Ein Spieler darf die anderen
    nicht mit sperren."""
    monkeypatch.setattr(srv, "PW_VERSUCHE", 2)

    async def go():
        async with _relay(tmp_path) as relay:
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})   # Relay stellt es zurueck
            _, wh, ok = await _hosten(relay, visibility="password", password="Sesam")
            code = ok["lobby_id"]
            for _ in range(2):
                _, w, a = await _beitreten(relay, code, password="falsch", cid="spielereins1")
                assert a["code"] == "BAD_PASSWORD"
                w.close()
            _, w, a = await _beitreten(relay, code, password="falsch", cid="spielereins1")
            assert a["code"] == "TOO_MANY_ATTEMPTS"
            w.close()
            # ein anderer Spieler hinter demselben Tunnel ist nicht betroffen
            _, w, a = await _beitreten(relay, code, password="Sesam", cid="spielerzwei2")
            assert a["type"] == "JOIN_OK"
            w.close(); wh.close()
    _lauf(go())


def test_wechselnde_cid_stoppt_die_lobbygrenze(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "PW_VERSUCHE_LOBBY", 4)

    async def go():
        async with _relay(tmp_path) as relay:
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})
            _, wh, ok = await _hosten(relay, visibility="password", password="Sesam")
            code = ok["lobby_id"]
            for i in range(4):
                _, w, a = await _beitreten(relay, code, password="falsch",
                                           cid=f"frischecid{i:02d}")
                assert a["code"] == "BAD_PASSWORD"
                w.close()
            _, w, a = await _beitreten(relay, code, password="falsch", cid="nocheine0815")
            assert a["code"] == "TOO_MANY_ATTEMPTS"
            w.close(); wh.close()
    _lauf(go())


def test_ohne_cid_hinter_dem_tunnel_gemeinsames_konto_mit_hoeherer_grenze(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "PW_VERSUCHE", 1)
    monkeypatch.setattr(srv, "TRUSTED_PROXIES", frozenset({"127.0.0.1"}))
    schluessel, faktor = srv._absender_schluessel("127.0.0.1", {})
    assert schluessel == "proxy" and faktor > 1


def test_lobby_wird_aufgeraeumt_mit_zaehler(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, wh, ok = await _hosten(relay, visibility="password", password="Sesam")
            code = ok["lobby_id"]
            _, w, _a = await _beitreten(relay, code, password="falsch")
            w.close()
            assert code in srv._pw_wache._lobbys
            wh.close()
            await asyncio.sleep(0.3)
            assert code not in srv._registry.lobbies
            assert code not in srv._pw_wache._lobbys
    _lauf(go())


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def test_status_im_rennen_ab_dem_start(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, visibility="public")
            rg, wg, gast = await _beitreten(relay, ok["lobby_id"])
            assert (await _liste(relay))[0]["status"] == "lobby"
            await senden(wh, {"type": "START_REQUEST", "is_custom": False,
                              "track_name": "Test"})
            await asyncio.sleep(0.2)
            assert (await _liste(relay))[0]["status"] == "racing"   # Start laeuft an
            await senden(wh, {"type": "READY"})
            await senden(wg, {"type": "READY"})
            assert await _bis(rg, "START")
            assert (await _liste(relay))[0]["status"] == "racing"
            wh.close(); wg.close()
    _lauf(go())


def test_status_grand_prix_ganze_serie(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, visibility="public")
            lobby = srv._registry.lobbies[ok["lobby_id"]]

            async def setze(**s):
                await senden(wh, {"type": "SET_SETTINGS",
                                  "settings": dict({"mode": "Grand Prix"}, **s)})
                await _bis(rh, "LOBBY_STATE")
                return (await _liste(relay))[0]["status"]

            # GP-Lobby vor dem ersten Lauf: noch offen
            assert await setze(gp_active=True, gp_phase="lobby", gp_locked=False) == "lobby"
            # in der Uebersicht: im Rennen
            assert await setze(gp_phase="overview") == "racing"
            # zwischen zwei Laeufen steht die Lobby-Ebene wieder, die Serie ist aber gesperrt
            assert await setze(gp_phase="lobby", gp_locked=True) == "racing"
            assert lobby.state == "lobby"        # der Relay selbst kennt keinen GP-Zustand
            # Serie vorbei: wieder offen
            assert await setze(gp_active=False, gp_locked=False, gp_phase="lobby") == "lobby"
            wh.close()
    _lauf(go())


def test_voll_wird_mitgezaehlt(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            _, wh, ok = await _hosten(relay, visibility="public")
            await senden(wh, {"type": "SET_SETTINGS", "settings": {"roster_size": 2}})
            _, wg, gast = await _beitreten(relay, ok["lobby_id"])
            assert gast["type"] == "JOIN_OK"
            e = (await _liste(relay))[0]
            assert (e["players"], e["max"]) == (2, 2)
            wh.close(); wg.close()
    _lauf(go())


# --------------------------------------------------------------------------
# Host aendert Sichtbarkeit / Name / Passwort in der Lobby
# --------------------------------------------------------------------------

def test_host_aendert_sichtbarkeit_und_name(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, "Anna", visibility="public", lobby_name="Alt")
            rg, wg, _g = await _beitreten(relay, ok["lobby_id"])
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "private",
                              "lobby_name": "Neu"})
            st = None
            for _ in range(6):
                st = await _bis(rg, "LOBBY_STATE")
                if st and st["lobby_name"] == "Neu":
                    break
            assert st["lobby_name"] == "Neu" and st["visibility"] == "private"
            assert await _liste(relay) == []                  # jetzt versteckt
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "public"})
            await asyncio.sleep(0.2)
            e = (await _liste(relay))[0]
            assert e["name"] == "Neu"                         # Name bleibt
            wh.close(); wg.close()
    _lauf(go())


def test_host_setzt_und_entfernt_passwort(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, visibility="public")
            code = ok["lobby_id"]
            lobby = srv._registry.lobbies[code]
            # Passwort-Lobby ohne Passwort: abgelehnt, Zustand unveraendert
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "password"})
            err = await _bis(rh, "ERROR")
            assert err["code"] == "BAD_PASSWORD_FORMAT" and lobby.sichtbarkeit == "public"
            # mit Passwort
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "password",
                              "password": "neupw1"})
            await asyncio.sleep(0.2)
            assert lobby.pw_hash and (await _liste(relay))[0]["password"] is True
            _, w, a = await _beitreten(relay, code, password="falsch")
            assert a["code"] == "BAD_PASSWORD"
            w.close()
            # Namensaenderung allein behaelt das Passwort
            await senden(wh, {"type": "SET_LOBBY_INFO", "lobby_name": "Zweiter"})
            await asyncio.sleep(0.2)
            assert lobby.pw_hash and lobby.lobby_name == "Zweiter"
            # zurueck auf oeffentlich: Hash ist weg
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "public"})
            await asyncio.sleep(0.2)
            assert lobby.pw_hash == b"" and lobby.pw_salt == b""
            _, w, a = await _beitreten(relay, code)
            assert a["type"] == "JOIN_OK"
            w.close(); wh.close()
    _lauf(go())


def test_nur_der_host_darf_aendern_und_ungueltiges_wird_abgewiesen(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, visibility="public", lobby_name="Mein")
            rg, wg, _g = await _beitreten(relay, ok["lobby_id"])
            lobby = srv._registry.lobbies[ok["lobby_id"]]
            await senden(wg, {"type": "SET_LOBBY_INFO", "visibility": "private"})
            await asyncio.sleep(0.2)
            assert lobby.sichtbarkeit == "public"
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "quatsch"})
            err = await _bis(rh, "ERROR")
            assert err["code"] == "BAD_VISIBILITY" and lobby.sichtbarkeit == "public"
            wh.close(); wg.close()
    _lauf(go())


def test_passwortwechsel_wird_gebremst(tmp_path):
    async def go():
        async with _relay(tmp_path) as relay:
            rh, wh, ok = await _hosten(relay, visibility="password", password="erstes1")
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "password",
                              "password": "zweites1"})
            await senden(wh, {"type": "SET_LOBBY_INFO", "visibility": "password",
                              "password": "drittes1"})
            await _bis(rh, "ERROR")
            lobby = srv._registry.lobbies[ok["lobby_id"]]
            assert srv.pw_stimmt(lobby, "zweites1")      # nur der erste Wechsel galt
            wh.close()
    _lauf(go())


# --------------------------------------------------------------------------
# Anfragen
# --------------------------------------------------------------------------

def test_lobbyliste_anfragen_sind_begrenzt(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "LOBBYLISTE_PRO_MIN", 3)

    async def go():
        async with _relay(tmp_path) as relay:
            for _ in range(3):
                a = await relay.frage({"type": "LOBBY_LIST"})
                assert a["type"] == "LOBBY_LIST"
            a = await relay.frage({"type": "LOBBY_LIST"})
            assert a["type"] == "LOBBY_ERROR" and a["code"] == "RATE"
    _lauf(go())


def test_hamburg_hinter_dem_tunnel_cid_getrennt(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "LOBBYLISTE_PRO_MIN", 1)

    async def go():
        async with _relay(tmp_path) as relay:
            srv.TRUSTED_PROXIES = frozenset({"127.0.0.1"})
            a = await relay.frage({"type": "LOBBY_LIST", "cid": "eins1eins1"})
            b = await relay.frage({"type": "LOBBY_LIST", "cid": "zwei2zwei2"})
            assert a["type"] == b["type"] == "LOBBY_LIST"
            c = await relay.frage({"type": "LOBBY_LIST", "cid": "eins1eins1"})
            assert c["type"] == "LOBBY_ERROR"
    _lauf(go())


def test_ein_server_ohne_die_neuerung_beantwortet_nichts():
    """Gegenprobe zur Dokumentation: LOBBY_LIST ist in LOBBYLISTE_TYPEN, nicht in
    den Typen des Handshakes — ein alter Relay faellt in ``else: return`` und
    schliesst. Hier nur: der neue Typ kollidiert mit keinem bestehenden."""
    assert srv.LOBBYLISTE_TYPEN.isdisjoint(srv.STRECKEN_TYPEN | {"INFO", "HOST", "JOIN"})


def test_vorgabename_wird_gekuerzt():
    n = srv.vorgabe_lobbyname("B" * 40)
    assert len(n) <= srv.LOBBYNAME_MAX and n.endswith("'s Lobby")
    assert srv.vorgabe_lobbyname("test") == "test's Lobby"
