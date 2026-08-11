"""Lobby codes carry the server identity in their first character.

That prefix is the whole routing mechanism for joining players: the client picks
the relay from ``code[0]`` instead of asking the player where the host is, and
the server refuses codes that are not its own (online_server_select_plan.md §6).
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


def _client_version() -> str:
    return str(srv._load_live_config().get("required_version", ""))


@pytest.fixture
def clean_registry():
    saved = srv._registry
    srv._registry = srv._Registry()
    yield srv._registry
    srv._registry = saved


# ── Code generation ───────────────────────────────────────────────────────────

def test_codes_start_with_the_server_tag(monkeypatch, clean_registry):
    monkeypatch.setattr(srv, "SERVER_TAG", "D")
    for _ in range(50):
        lobby = clean_registry.create()
        assert lobby.lobby_id[0] == "D"
        assert len(lobby.lobby_id) == 6


def test_reserved_tags_never_appear_after_the_first_character(monkeypatch, clean_registry):
    """Otherwise a random 'D' inside a Helsinki code would read like a prefix."""
    monkeypatch.setattr(srv, "SERVER_TAG", "H")
    for _ in range(200):
        lobby = clean_registry.create()
        assert not set(lobby.lobby_id[1:]) & set(srv.RESERVED_TAGS)


def test_codes_are_unique(monkeypatch, clean_registry):
    monkeypatch.setattr(srv, "SERVER_TAG", "H")
    ids = {clean_registry.create().lobby_id for _ in range(100)}
    assert len(ids) == 100


# ── JOIN routing ──────────────────────────────────────────────────────────────

def test_join_with_foreign_prefix_is_refused(monkeypatch, clean_registry):
    monkeypatch.setattr(srv, "SERVER_TAG", "H")

    async def run():
        server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            # Host a real lobby, then try to join it through a rewritten prefix.
            hr, hw = await asyncio.open_connection("127.0.0.1", port)
            await _send(hw, {"type": "HOST", "name": "Host", "version": _client_version()})
            ok = await _recv(hr)
            assert ok and ok["type"] == "JOIN_OK"
            lid = ok["lobby_id"]

            gr, gw = await asyncio.open_connection("127.0.0.1", port)
            await _send(gw, {"type": "JOIN", "name": "Guest", "version": _client_version(),
                             "lobby_id": "D" + lid[1:]})
            reply = await _recv(gr)
            hw.close()
            gw.close()
            return reply
        finally:
            server.close()
            await server.wait_closed()

    reply = asyncio.run(run())
    assert reply["type"] == "JOIN_FAIL"
    assert reply["code"] == "WRONG_SERVER"


def test_join_with_own_prefix_succeeds(monkeypatch, clean_registry):
    monkeypatch.setattr(srv, "SERVER_TAG", "H")

    async def run():
        server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            hr, hw = await asyncio.open_connection("127.0.0.1", port)
            await _send(hw, {"type": "HOST", "name": "Host", "version": _client_version()})
            ok = await _recv(hr)
            lid = ok["lobby_id"]

            gr, gw = await asyncio.open_connection("127.0.0.1", port)
            await _send(gw, {"type": "JOIN", "name": "Guest", "version": _client_version(),
                             "lobby_id": lid})
            reply = await _recv(gr)
            hw.close()
            gw.close()
            return reply
        finally:
            server.close()
            await server.wait_closed()

    reply = asyncio.run(run())
    assert reply["type"] == "JOIN_OK"


def test_info_reports_lobby_count_and_tag(monkeypatch, clean_registry):
    monkeypatch.setattr(srv, "SERVER_TAG", "D")
    clean_registry.create()
    clean_registry.create()

    async def run():
        server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            await _send(w, {"type": "INFO", "version": _client_version()})
            reply = await _recv(r)
            w.close()
            return reply
        finally:
            server.close()
            await server.wait_closed()

    reply = asyncio.run(run())
    assert reply["type"] == "INFO"
    assert reply["lobby_count"] == 2
    assert reply["server_tag"] == "D"
