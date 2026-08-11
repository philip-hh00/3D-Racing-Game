"""Online-Grand-Prix: die Lobby ist ab Serienstart gesperrt.

Entschieden im Interview: wer vorher dabei war, kann mit demselben Code
zurückkehren; neue Spieler kommen nicht mehr hinein. Sonst platzt jemand mit
0 Punkten in eine laufende Wertung und kann den Titel nicht mehr gewinnen —
das Feld bleibt lieber lückenhaft.

Der Serienzustand selbst reist über den vorhandenen Einstellungskanal
(``SET_SETTINGS`` → ``lobby.settings`` → ``LOBBY_STATE``). Der Relay speichert
dort beliebige Schlüssel, deshalb braucht Grand Prix keine eigene
Protokollnachricht — nur die Sperre muss der Server kennen, weil nur er JOIN
ablehnen kann.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "server"))

import server as srv  # noqa: E402

_LEN = struct.Struct("!I")


async def _send(writer, msg: dict) -> None:
    body = json.dumps(msg).encode()
    writer.write(_LEN.pack(len(body)) + body)
    await writer.drain()


async def _recv(reader, timeout: float = 3.0) -> dict | None:
    try:
        raw = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        length = _LEN.unpack(raw)[0]
        body = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
        return json.loads(body)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        return None


async def _recv_until(reader, typ: str, tries: int = 8) -> dict | None:
    for _ in range(tries):
        msg = await _recv(reader)
        if msg is None:
            return None
        if msg.get("type") == typ:
            return msg
    return None


def _version() -> str:
    return str(srv._load_live_config().get("required_version", ""))


@pytest.fixture
def sauberes_register():
    alt = srv._registry
    srv._registry = srv._Registry()
    yield srv._registry
    srv._registry = alt


async def _lobby_mit_sperre(port_holder, mitglieder: dict, gesperrt: bool):
    """Lobby aufsetzen, Sperre über den Einstellungskanal setzen."""
    server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    port_holder.append((server, port))

    hr, hw = await asyncio.open_connection("127.0.0.1", port)
    await _send(hw, {"type": "HOST", "name": "HostAnn", "version": _version()})
    ok = await _recv_until(hr, "JOIN_OK")
    lid = ok["lobby_id"]

    await _send(hw, {"type": "SET_SETTINGS", "settings": {
        "mode": "Grand Prix",
        "gp_active": True,
        "gp_locked": gesperrt,
        "gp_members": mitglieder,
    }})
    await asyncio.sleep(0.1)
    return lid, hr, hw


def _lauf(coro):
    return asyncio.run(coro)


def test_fremder_kommt_nicht_in_laufende_serie(sauberes_register):
    async def run():
        offen = []
        try:
            lid, _hr, hw = await _lobby_mit_sperre(offen, {"HostAnn": True}, True)
            gr, gw = await asyncio.open_connection("127.0.0.1", offen[0][1])
            await _send(gw, {"type": "JOIN", "name": "Fremder",
                             "version": _version(), "lobby_id": lid})
            antwort = await _recv(gr)
            hw.close(); gw.close()
            return antwort
        finally:
            for s, _p in offen:
                s.close()
                await s.wait_closed()

    antwort = _lauf(run())
    assert antwort["type"] == "JOIN_FAIL"
    assert antwort["code"] == "SERIES_LOCKED"


def test_frueheres_mitglied_darf_zurueck(sauberes_register):
    async def run():
        offen = []
        try:
            lid, _hr, hw = await _lobby_mit_sperre(
                offen, {"HostAnn": True, "GastBo": True}, True)
            gr, gw = await asyncio.open_connection("127.0.0.1", offen[0][1])
            await _send(gw, {"type": "JOIN", "name": "GastBo",
                             "version": _version(), "lobby_id": lid})
            antwort = await _recv(gr)
            hw.close(); gw.close()
            return antwort
        finally:
            for s, _p in offen:
                s.close()
                await s.wait_closed()

    assert _lauf(run())["type"] == "JOIN_OK"


def test_offene_lobby_nimmt_jeden(sauberes_register):
    """Vor dem ersten Lauf darf sich das Feld noch fuellen."""
    async def run():
        offen = []
        try:
            lid, _hr, hw = await _lobby_mit_sperre(offen, {"HostAnn": True}, False)
            gr, gw = await asyncio.open_connection("127.0.0.1", offen[0][1])
            await _send(gw, {"type": "JOIN", "name": "Neuer",
                             "version": _version(), "lobby_id": lid})
            antwort = await _recv(gr)
            hw.close(); gw.close()
            return antwort
        finally:
            for s, _p in offen:
                s.close()
                await s.wait_closed()

    assert _lauf(run())["type"] == "JOIN_OK"


def test_serienzustand_erreicht_den_gast(sauberes_register):
    """Grand Prix braucht keine eigene Protokollnachricht - der Zustand reist
    im Einstellungsblock mit, den der Relay ohnehin an alle verteilt."""
    async def run():
        offen = []
        try:
            lid, _hr, hw = await _lobby_mit_sperre(offen, {"HostAnn": True}, False)
            gr, gw = await asyncio.open_connection("127.0.0.1", offen[0][1])
            await _send(gw, {"type": "JOIN", "name": "GastBo",
                             "version": _version(), "lobby_id": lid})
            await _recv_until(gr, "JOIN_OK")

            await _send(hw, {"type": "SET_SETTINGS", "settings": {
                "gp_active": True, "gp_race": 2, "gp_total": 5,
                "gp_standings": [{"name": "HostAnn", "points": 18},
                                 {"name": "GastBo", "points": 12}],
            }})
            zustand = None
            for _ in range(10):
                msg = await _recv(gr)
                if msg and msg.get("type") == "LOBBY_STATE":
                    if msg.get("settings", {}).get("gp_standings"):
                        zustand = msg
                        break
            hw.close(); gw.close()
            return zustand
        finally:
            for s, _p in offen:
                s.close()
                await s.wait_closed()

    zustand = _lauf(run())
    assert zustand is not None, "Gast hat den Serienzustand nie gesehen"
    srv_set = zustand["settings"]
    assert srv_set["gp_race"] == 2 and srv_set["gp_total"] == 5
    assert srv_set["gp_standings"][0]["name"] == "HostAnn"
