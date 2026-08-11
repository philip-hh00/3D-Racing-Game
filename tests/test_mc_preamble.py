"""Minecraft handshake preamble: client side builds it, server side drops it.

playit.gg's "Minecraft Java" tunnel rejects any TCP connection whose first
packet is not a valid handshake. The relay therefore has to swallow that packet
again before the real protocol starts, without breaking direct connections that
never send one — see online_server_select_plan.md §0 and §7.
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

import server as srv          # noqa: E402
from src.net import mc_preamble  # noqa: E402

_LEN = struct.Struct("!I")


def _frame(msg: dict) -> bytes:
    body = json.dumps(msg).encode()
    return _LEN.pack(len(body)) + body


async def _feed(data: bytes):
    """Push *data* through a StreamReader and run the handshake path on it."""
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    prefetched = await srv._strip_mc_preamble(reader)
    return await srv._recv(reader, prefetched)


# ── Builder ───────────────────────────────────────────────────────────────────

def test_varint_encoding():
    assert mc_preamble.varint(0) == b"\x00"
    assert mc_preamble.varint(31) == b"\x1f"
    assert mc_preamble.varint(128) == b"\x80\x01"
    assert mc_preamble.varint(765) == b"\xfd\x05"


def test_build_matches_the_wire_capture():
    """Exactly the bytes the live tunnel accepted during the connectivity test."""
    pre = mc_preamble.build("mode-lang.gl.joinmc.link", 37354)
    assert pre == (b"\x1f\x00\xfd\x05\x18mode-lang.gl.joinmc.link\x91\xea\x01")
    assert len(pre) == 32


def test_first_byte_never_collides_with_our_length_prefix():
    # Our frames always start with 0x00 (messages are far below 16 MB), which is
    # what makes the server-side detection unambiguous.
    pre = mc_preamble.build("x.example", 1)
    assert pre[0] != 0x00


# ── Server-side stripping ─────────────────────────────────────────────────────

def test_strips_preamble_and_reads_the_real_message():
    pre = mc_preamble.build("mode-lang.gl.joinmc.link", 37354)
    msg = asyncio.run(_feed(pre + _frame({"type": "INFO", "version": "1.0"})))
    assert msg == {"type": "INFO", "version": "1.0"}


def test_direct_connection_without_preamble_still_works():
    msg = asyncio.run(_feed(_frame({"type": "HOST", "name": "Ann"})))
    assert msg == {"type": "HOST", "name": "Ann"}


def test_preamble_split_across_reads():
    """The tunnel may deliver the handshake and the payload separately."""
    async def run():
        pre = mc_preamble.build("h.example", 25565)
        reader = asyncio.StreamReader()
        reader.feed_data(pre[:10])
        loop = asyncio.get_running_loop()
        loop.call_soon(reader.feed_data, pre[10:])
        loop.call_later(0.01, reader.feed_data, _frame({"type": "PING"}))
        loop.call_later(0.02, reader.feed_eof)
        prefetched = await srv._strip_mc_preamble(reader)
        return await srv._recv(reader, prefetched)

    assert asyncio.run(run()) == {"type": "PING"}


def test_oversized_preamble_is_rejected():
    """A huge varint length must not make the server read for ever."""
    bogus = mc_preamble.varint(srv.MAX_PREAMBLE + 1) + b"\x00" * 32
    assert asyncio.run(_feed(bogus + _frame({"type": "INFO"}))) is None


def test_garbage_after_preamble_yields_no_message():
    pre = mc_preamble.build("h.example", 1)
    assert asyncio.run(_feed(pre + b"\xff\xff\xff\xff")) is None
