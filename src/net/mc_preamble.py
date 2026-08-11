"""Minecraft handshake preamble for playit.gg TCP tunnels.

playit's "Minecraft Java" tunnel type inspects the *first* packet of every TCP
connection and drops the connection unless it parses as a valid Minecraft
handshake. Our own framing starts with a 4-byte big-endian length, i.e.
``\\x00\\x00\\x00*``, which the tunnel reads as varint "packet length 0" and
rejects with an RST.

Sending one throwaway handshake packet up front satisfies that check. Afterwards
the tunnel is fully transparent — verified against the live tunnel: no PROXY
header, no keepalive requirement, bytes arrive unmodified. The relay server
discards the preamble again (``_strip_mc_preamble`` in server/server.py), which
is unambiguous because our length prefix always begins with ``0x00`` and a
handshake never does.
"""
from __future__ import annotations

PROTOCOL_VERSION = 765   # Minecraft 1.20.4 — any plausible number passes
STATE_STATUS     = 1

# The stripper on the server side reads at most this many bytes before giving up
# on a malformed preamble.
MAX_PREAMBLE = 512


def varint(n: int) -> bytes:
    """Encode a non-negative int as a Minecraft protocol varint."""
    if n < 0:
        raise ValueError("varint is unsigned")
    out = bytearray()
    while True:
        chunk = n & 0x7F
        n >>= 7
        if n:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def build(host: str, port: int, *, next_state: int = STATE_STATUS) -> bytes:
    """One Minecraft handshake packet addressed at *host*:*port*.

    The values only have to be plausible — the tunnel does not forward them
    anywhere, it just validates the shape.
    """
    host_b = host.encode("utf-8")[:255]
    body = (
        b"\x00"
        + varint(PROTOCOL_VERSION)
        + varint(len(host_b))
        + host_b
        + int(port).to_bytes(2, "big")
        + varint(next_state)
    )
    return varint(len(body)) + body
