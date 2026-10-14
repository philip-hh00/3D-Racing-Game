"""Namensfilter auf dem Relay: verbotene Namen kommen nicht durch (Plan 1.1.0).

Der Filter lief bis 1.0.x nur im Spiel; ein veraenderter Client konnte jeden
Namen senden. Jetzt setzt der Relay die Sperrliste durch, und zwar an allen
Stellen, an denen ein Name vor Fremden landet:

* Spielername       HOST / JOIN                      -> ``field: player``
* Lobbyname         HOST / SET_LOBBY_INFO            -> ``field: lobby``
* Streckenname      TRACK_UPLOAD (auch Beschreibung) -> ``field: track``
* gespeicherte Strecken mit inzwischen verbotenem Namen werden ausgeblendet

Die Absage ist immer der Code ``BAD_NAME``; das Spiel zeigt dazu seinen
uebersetzten Satz. Alles gegen einen echten Relay auf einem freien Port.
"""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from tests.strecken_hilfe import Relay, empfangen, kopie, rundkurs, senden, srv


def _lauf(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _frisch(monkeypatch):
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
    return r, w, await empfangen(r)


async def _beitreten(relay, code, name="Ben"):
    r, w = await asyncio.open_connection("127.0.0.1", relay.port)
    await senden(w, {"type": "JOIN", "name": name, "lobby_id": code,
                     "version": _version()})
    return r, w, await empfangen(r)


async def _bis(reader, typ, versuche=8):
    for _ in range(versuche):
        m = await empfangen(reader)
        if m is None or m.get("type") == typ:
            return m
    return None


def _zu(*writer):
    for w in writer:
        w.close()


# --------------------------------------------------------------------------
# Die Liste liegt neben dem Server
# --------------------------------------------------------------------------

def test_die_liste_liegt_neben_server_py_und_ist_dieselbe_wie_im_spiel():
    """Der Relay laeuft aus ``server/`` (WorkingDirectory der Unit) - dort muss
    die Liste liegen, sonst ist der Filter auf dem Server stillschweigend aus."""
    ordner = os.path.dirname(os.path.abspath(srv.__file__))
    neben = os.path.join(ordner, "name_blacklist.json")
    assert os.path.isfile(neben), "server/name_blacklist.json fehlt"
    im_spiel = os.path.join(os.path.dirname(ordner), "data", "settings",
                            "name_blacklist.json")
    with open(neben, encoding="utf-8") as a, open(im_spiel, encoding="utf-8") as b:
        assert json.load(a) == json.load(b), (
            "server/name_blacklist.json und data/settings/name_blacklist.json "
            "weichen ab - beide muessen gleich sein")
    assert srv._namensliste_holen()["teil"], "Liste wurde nicht geladen"


def test_name_gesperrt_kennt_die_alltagsfaelle():
    assert srv.name_gesperrt("Hurensohn")
    assert srv.name_gesperrt("xX_Admin_Xx")
    assert srv.name_gesperrt("4dm1n")
    assert not srv.name_gesperrt("Anna", "Hans", "Anna's Lobby", "Scunthorpe")
    assert not srv.name_gesperrt("", None)


def test_die_liste_wird_bei_aenderung_neu_gelesen(tmp_path, monkeypatch):
    """Der Besitzer kann ein Wort ergaenzen, ohne den Relay neu zu starten."""
    datei = tmp_path / "name_blacklist.json"
    datei.write_text(json.dumps({"enthalten": ["blumenkohl"], "ganzes_wort": []}),
                     encoding="utf-8")
    monkeypatch.setattr(srv, "_NAMENSLISTE_PFADE", (str(datei),))
    assert srv.name_gesperrt("Blumenkohl")
    assert not srv.name_gesperrt("Rosenkohl")

    datei.write_text(json.dumps({"enthalten": ["rosenkohl"], "ganzes_wort": []}),
                     encoding="utf-8")
    os.utime(datei, ns=(10 ** 18, 10 ** 18 + 5))      # sicher anderer Stand
    assert srv.name_gesperrt("Rosenkohl")
    assert not srv.name_gesperrt("Blumenkohl")


# --------------------------------------------------------------------------
# Spielername: HOST und JOIN
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Hurensohn", "Admin", "n1gger", "xXfuckXx", "S y s t e m"])
def test_host_mit_verbotenem_spielernamen_wird_abgewiesen(tmp_path, name):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            r, w, a = await _hosten(relay, name, visibility="public")
            _zu(w)
            return a, len(srv._registry.lobbies)
    a, lobbys = _lauf(go())
    assert a["type"] == "JOIN_FAIL"
    assert a["code"] == "BAD_NAME"
    assert a["field"] == "player"
    assert a["reason"]
    assert lobbys == 0, "es darf keine Lobby entstehen"


def test_host_mit_erlaubtem_namen_und_standardlobbyname_geht(tmp_path):
    """„<Name>'s Lobby" ist der Vorgabename und muss fuer erlaubte Namen passen -
    ob ausgelassen oder vom Spiel ausdruecklich mitgeschickt."""
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _, w1, a1 = await _hosten(relay, "Anna", visibility="public")
            _, w2, a2 = await _hosten(relay, "Hans", visibility="public",
                                      lobby_name="Hans's Lobby")
            _, w3, a3 = await _hosten(relay, "Scunthorpe", visibility="public",
                                      lobby_name=srv.vorgabe_lobbyname("Scunthorpe"))
            _zu(w1, w2, w3)
            return a1, a2, a3
    a1, a2, a3 = _lauf(go())
    assert a1["type"] == a2["type"] == a3["type"] == "JOIN_OK"
    assert a1["lobby_name"] == "Anna's Lobby"
    assert a2["lobby_name"] == "Hans's Lobby"


def test_join_mit_verbotenem_spielernamen_wird_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _, wh, ok = await _hosten(relay, "Anna")
            _, wg, a = await _beitreten(relay, ok["lobby_id"], "Hitler")
            _, wg2, b = await _beitreten(relay, ok["lobby_id"], "Ben")
            _zu(wh, wg, wg2)
            return a, b
    a, b = _lauf(go())
    assert (a["type"], a["code"], a["field"]) == ("JOIN_FAIL", "BAD_NAME", "player")
    assert b["type"] == "JOIN_OK", "ein erlaubter Name darf nach der Absage trotzdem rein"


def test_der_name_wird_roh_und_gesaeubert_geprueft(tmp_path):
    """Der Relay streicht Sonderzeichen aus dem Namen - die Pruefung darf aber
    nicht davon abhaengen, ob sie vor oder nach dem Streichen stattfindet."""
    async def go():
        async with Relay(str(tmp_path)) as relay:
            r, w, a = await _hosten(relay, "f​u​c​k")
            _zu(w)
            return a
    assert _lauf(go())["code"] == "BAD_NAME"


# --------------------------------------------------------------------------
# Lobbyname: HOST und SET_LOBBY_INFO
# --------------------------------------------------------------------------

def test_host_mit_verbotenem_lobbynamen_wird_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            _, w, a = await _hosten(relay, "Anna", visibility="public",
                                    lobby_name="Nazi Treff")
            _zu(w)
            return a, len(srv._registry.lobbies)
    a, lobbys = _lauf(go())
    assert (a["type"], a["code"], a["field"]) == ("JOIN_FAIL", "BAD_NAME", "lobby")
    assert lobbys == 0


def test_set_lobby_info_mit_verbotenem_namen_wird_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            r, w, ok = await _hosten(relay, "Anna", visibility="public",
                                     lobby_name="Offene Runde")
            await senden(w, {"type": "SET_LOBBY_INFO", "visibility": "public",
                             "lobby_name": "Fuck Lobby"})
            fehler = await _bis(r, "ERROR")
            # Sichtbar unveraendert, und ein erlaubter Name geht danach durch.
            lobbys = srv.lobby_liste()
            await senden(w, {"type": "SET_LOBBY_INFO", "visibility": "public",
                             "lobby_name": "Neue Runde"})
            state = await _bis(r, "LOBBY_STATE")
            _zu(w)
            return fehler, lobbys, state
    fehler, lobbys, state = _lauf(go())
    assert (fehler["code"], fehler["field"]) == ("BAD_NAME", "lobby")
    assert [l["name"] for l in lobbys] == ["Offene Runde"]
    assert state is not None


# --------------------------------------------------------------------------
# Streckenname: TRACK_UPLOAD
# --------------------------------------------------------------------------

def _hoch(entwurf, **extra) -> dict:
    return {"type": "TRACK_UPLOAD", "track": entwurf, "author": "Anna", **extra}


def test_upload_mit_erlaubtem_namen_geht(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            return await relay.frage(_hoch(rundkurs(name="Alte Mühle (Nacht)")))
    assert _lauf(go())["type"] == "TRACK_UPLOAD_OK"


@pytest.mark.parametrize("aendern", [
    lambda d, m: d.update(name="Fuck City"),
    lambda d, m: d.update(name="Admin Track"),
    lambda d, m: d.update(name="Sch3iss Ring"),
    lambda d, m: d.update(description="Hurensohn Piste"),
    lambda d, m: m.update(name="Nigger Ring"),           # eigenes Feld ueberschreibt
])
def test_upload_mit_verbotenem_streckennamen_wird_abgewiesen(tmp_path, aendern):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            d, m = rundkurs(), {}
            aendern(d, m)
            a = await relay.frage(_hoch(d, **m))
            liste = await relay.frage({"type": "TRACK_LIST"})
            return a, liste
    a, liste = _lauf(go())
    assert (a["type"], a["code"], a["field"]) == ("TRACK_ERROR", "BAD_NAME", "track")
    assert liste["total"] == 0, "abgewiesen heisst: nichts gespeichert"


def test_upload_eines_verbotenen_autors_wird_abgewiesen(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            return await relay.frage(_hoch(rundkurs(), author="Hitler"))
    a = _lauf(go())
    assert (a["code"], a["field"]) == ("BAD_NAME", "player")


# --------------------------------------------------------------------------
# Gespeicherte Strecken
# --------------------------------------------------------------------------

def test_gespeicherte_strecke_mit_verbotenem_namen_wird_ausgeblendet(tmp_path):
    """Strecken von vor dem Filter (oder vor einer Erweiterung der Liste) liegen
    noch auf dem Server - sie duerfen weder in der Liste stehen noch ladbar sein."""
    async def go():
        async with Relay(str(tmp_path)) as relay:
            ok = await relay.frage(_hoch(rundkurs(name="Alte Strecke")))
            ok2 = await relay.frage(_hoch(rundkurs(name="Gute Strecke", breit=9)))
            vorher = await relay.frage({"type": "TRACK_LIST"})
            # Der Besitzer erweitert die Liste: ``alte strecke`` ist jetzt verboten.
            speicher = srv.strecken_speicher()
            speicher.tracks[ok["id"]]["name"] = "Hurensohn Ring"
            speicher.tracks[ok2["id"]]["author"] = "Admin"
            nachher = await relay.frage({"type": "TRACK_LIST"})
            geholt = await relay.frage({"type": "TRACK_GET", "id": ok["id"]})
            geholt2 = await relay.frage({"type": "TRACK_GET", "id": ok2["id"]})
            return vorher, nachher, geholt, geholt2
    vorher, nachher, geholt, geholt2 = _lauf(go())
    assert vorher["total"] == 2
    assert nachher["total"] == 0
    assert nachher["tracks"] == []
    assert geholt["type"] == "TRACK_ERROR" and geholt["code"] == "NOT_FOUND"
    assert geholt2["type"] == "TRACK_ERROR" and geholt2["code"] == "NOT_FOUND"


def test_eine_harmlose_strecke_bleibt_sichtbar(tmp_path):
    async def go():
        async with Relay(str(tmp_path)) as relay:
            ok = await relay.frage(_hoch(rundkurs(name="Helsinki Ring")))
            liste = await relay.frage({"type": "TRACK_LIST"})
            geholt = await relay.frage({"type": "TRACK_GET", "id": ok["id"]})
            return liste, geholt
    liste, geholt = _lauf(go())
    assert liste["total"] == 1
    assert geholt["type"] == "TRACK_DATA"
