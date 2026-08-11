"""Hand-rolled DNS SRV resolver.

Needed because the playit.gg tunnel port changes whenever its agent restarts, so
the TCP endpoint is re-resolved instead of pinned. dnspython would be one import
but ~1 MB of PyInstaller bundle for a single query type.
"""
from __future__ import annotations

import os
import struct
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.net import srv_lookup  # noqa: E402

_NAME = "_minecraft._tcp.mode-lang.gl.joinmc.link"


def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.split("."):
        out.append(len(label))
        out += label.encode()
    out.append(0)
    return bytes(out)


def _answer(qid: int, name: str, target: str, port: int,
            priority: int = 1, weight: int = 1, count: int = 1) -> bytes:
    """A minimal but well-formed SRV response."""
    header = struct.pack("!HHHHHH", qid, 0x8180, 1, count, 0, 0)
    question = _encode_name(name) + struct.pack("!HH", 33, 1)
    body = b""
    for i in range(count):
        rdata = (struct.pack("!HHH", priority + i, weight, port + i)
                 + _encode_name(target))
        body += (_encode_name(name) + struct.pack("!HHIH", 33, 1, 60, len(rdata))
                 + rdata)
    return header + question + body


@pytest.fixture(autouse=True)
def _clear():
    srv_lookup.clear_cache()
    yield
    srv_lookup.clear_cache()


# ── Parsing ───────────────────────────────────────────────────────────────────

def test_parses_the_real_record_shape():
    msg = _answer(0x1234, _NAME, "mode-lang.gl.at.ply.gg", 37354)
    assert srv_lookup.parse_srv(msg, 0x1234) == ("mode-lang.gl.at.ply.gg", 37354)


def test_lowest_priority_wins():
    # Second record gets priority 2 and port+1, so the first one must win.
    msg = _answer(0x1234, _NAME, "a.example", 1000, priority=1, count=2)
    assert srv_lookup.parse_srv(msg, 0x1234) == ("a.example", 1000)


def test_mismatched_transaction_id_is_rejected():
    """Guards against an off-path reply landing in the socket."""
    msg = _answer(0x1234, _NAME, "a.example", 1000)
    assert srv_lookup.parse_srv(msg, 0x9999) is None


def test_empty_answer_section():
    msg = struct.pack("!HHHHHH", 7, 0x8180, 1, 0, 0, 0) + _encode_name(_NAME) + struct.pack("!HH", 33, 1)
    assert srv_lookup.parse_srv(msg, 7) is None


def test_truncated_message_does_not_raise():
    msg = _answer(0x1234, _NAME, "a.example", 1000)[:20]
    assert srv_lookup.parse_srv(msg, 0x1234) is None


def test_compression_pointer_is_followed():
    """Real resolvers compress the target name; the parser must expand it."""
    qid = 0x2222
    header = struct.pack("!HHHHHH", qid, 0x8180, 1, 1, 0, 0)
    question = _encode_name(_NAME) + struct.pack("!HH", 33, 1)
    name_off = len(header)                       # the question name starts here
    rdata = struct.pack("!HHH", 1, 1, 37354) + b"\xc0" + bytes([name_off])
    body = (b"\xc0" + bytes([name_off]) + struct.pack("!HHIH", 33, 1, 60, len(rdata))
            + rdata)
    assert srv_lookup.parse_srv(header + question + body, qid) == (_NAME, 37354)


def test_pointer_loop_is_survivable():
    qid = 0x3333
    header = struct.pack("!HHHHHH", qid, 0x8180, 0, 1, 0, 0)
    # A record whose name points at itself.
    body = b"\xc0\x0c" + struct.pack("!HHIH", 33, 1, 60, 0)
    with pytest.raises(Exception):
        srv_lookup._read_name(header + body, 12)


# ── Query building ────────────────────────────────────────────────────────────

def test_query_is_a_recursive_srv_question():
    q = srv_lookup.build_query(_NAME, 0xABCD)
    qid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", q[:12])
    assert (qid, flags, qd, an) == (0xABCD, 0x0100, 1, 0)
    assert q.endswith(struct.pack("!HH", 33, 1))


# ── Caching ───────────────────────────────────────────────────────────────────

def test_result_is_cached(monkeypatch):
    calls = []

    class _FakeSocket:
        def __init__(self, *a, **kw):
            calls.append(1)
        def settimeout(self, *_a): pass
        def sendto(self, data, _addr):
            self._qid = struct.unpack("!H", data[:2])[0]
        def recvfrom(self, _n):
            return _answer(self._qid, _NAME, "t.example", 4242), None
        def close(self): pass

    monkeypatch.setattr(srv_lookup.socket, "socket", _FakeSocket)
    assert srv_lookup.resolve_srv(_NAME) == ("t.example", 4242)
    assert srv_lookup.resolve_srv(_NAME) == ("t.example", 4242)
    assert len(calls) == 1                     # second call served from cache


def test_failure_is_cached_too(monkeypatch):
    """Otherwise an unreachable resolver stalls every 3-second probe round."""
    calls = []

    class _DeadSocket:
        def __init__(self, *a, **kw):
            calls.append(1)
        def settimeout(self, *_a): pass
        def sendto(self, *_a): raise OSError("no route")
        def recvfrom(self, _n): raise OSError("no route")
        def close(self): pass

    monkeypatch.setattr(srv_lookup.socket, "socket", _DeadSocket)
    assert srv_lookup.resolve_srv(_NAME) is None
    assert srv_lookup.resolve_srv(_NAME) is None
    assert len(calls) == len(srv_lookup.RESOLVERS)   # one round, then cached


# ── DNS-Transaktionskennung: unvorhersagbar, voller Bereich (08.08.2026) ───────

def test_qid_bleibt_im_16bit_bereich():
    """Jede Kennung passt in 16 Bit -- sie geht als ``!H`` auf die Leitung."""
    for _ in range(2000):
        assert 0 <= srv_lookup._neue_qid() <= 0xFFFF


def test_qid_stammt_nicht_aus_seedbarem_random():
    """Regel: die Kennung ist nicht aus dem vorhersagbaren ``random`` zu ziehen.

    Genau das ist die Schutzwirkung -- ein Angreifer, der den Zustand von
    ``random`` kennt oder setzt, darf die naechste Kennung nicht vorhersagen.
    Deshalb: ``random`` mit festem Seed liefert keine reproduzierbare Folge von
    ``_neue_qid``. Acht Ziehungen, damit ein zufaelliges Gleichauf (1/65536 je
    Wert) den Test nicht falsch gruen macht."""
    import random
    random.seed(1234)
    a = [srv_lookup._neue_qid() for _ in range(8)]
    random.seed(1234)
    b = [srv_lookup._neue_qid() for _ in range(8)]
    assert a != b, "Kennung folgt dem seedbaren random-Zustand -- vorhersagbar"


def test_qid_schoepft_den_vollen_bereich_inklusive_rand(monkeypatch):
    """Deterministisch statt probabilistisch: die Kennung wird aus dem vollen
    16-Bit-Raum gezogen. ``randbelow(0x10000)`` schliesst 0xFFFF ein; das alte
    ``randrange(0, 0xFFFF)`` liess ihn aus."""
    gesehen = {}

    def falle(n):
        gesehen["n"] = n
        return n - 1                       # groesster Wert dieses Bereichs

    monkeypatch.setattr(srv_lookup.secrets, "randbelow", falle)
    q = srv_lookup._neue_qid()
    assert gesehen["n"] == 0x10000, "nicht der volle 16-Bit-Bereich angefordert"
    assert q == 0xFFFF, "0xFFFF ist nicht erreichbar"
