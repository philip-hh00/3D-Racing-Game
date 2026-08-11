"""Minimal DNS SRV resolver (no third-party dependency).

The playit.gg tunnel port can change when the agent restarts, so the TCP
endpoint has to be re-resolved from its SRV record instead of being pinned in
the config. dnspython would do this in three lines but adds ~1 MB to the
PyInstaller bundle for one query type, hence this hand-rolled version.

Only SRV (type 33) over UDP is supported, answers are cached briefly, and every
failure path falls back to "unknown" so callers can keep their configured
values.
"""
from __future__ import annotations

import secrets
import socket
import struct
import threading
import time

# Public resolvers, tried in order. The OS resolver is deliberately not used:
# reading it portably (Windows registry vs /etc/resolv.conf) is more code than
# this whole module.
RESOLVERS = ("1.1.1.1", "8.8.8.8")
TIMEOUT   = 2.0
CACHE_TTL = 60.0

_TYPE_SRV = 33
_CLASS_IN = 1

_lock: threading.Lock = threading.Lock()
_cache: dict[str, tuple[float, tuple[str, int] | None]] = {}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ── Wire format ───────────────────────────────────────────────────────────────

def _encode_name(name: str) -> bytes:
    out = bytearray()
    for label in name.rstrip(".").split("."):
        b = label.encode("idna" if any(ord(c) > 127 for c in label) else "ascii")
        if not 0 < len(b) < 64:
            raise ValueError(f"bad DNS label: {label!r}")
        out.append(len(b))
        out += b
    out.append(0)
    return bytes(out)


def _read_name(msg: bytes, off: int) -> tuple[str, int]:
    """Decode a (possibly compressed) name; return (name, offset after it)."""
    labels: list[str] = []
    jumped = False
    end = off
    hops = 0
    while True:
        if off >= len(msg):
            raise ValueError("truncated name")
        ln = msg[off]
        if ln & 0xC0 == 0xC0:                      # compression pointer
            if off + 1 >= len(msg):
                raise ValueError("truncated pointer")
            ptr = ((ln & 0x3F) << 8) | msg[off + 1]
            if not jumped:
                end = off + 2
            off = ptr
            jumped = True
            hops += 1
            if hops > 32:                          # pointer loop
                raise ValueError("name pointer loop")
            continue
        off += 1
        if ln == 0:
            if not jumped:
                end = off
            break
        labels.append(msg[off:off + ln].decode("ascii", "replace"))
        off += ln
    return ".".join(labels), end


def _neue_qid() -> int:
    """Zufaellige DNS-Transaktionskennung (16 Bit).

    Aus ``secrets``, nicht aus ``random`` (08.08.2026): die Kennung ist der Teil
    des Schutzes gegen eingeschleuste Antworten (neben dem zufaelligen
    Quell-Port). Aus dem vorhersagbaren Mersenne-Twister von ``random`` liesse
    sie sich fuer einen Off-Path-Angreifer erraten, der eine gefaelschte Antwort
    unterschieben und den Spieler so auf einen fremden Relay lenken will. Der
    Rest des Codes nutzt aus demselben Grund ``secrets`` (Lobbycode und
    Sitzungstoken, H2.9).

    ``randbelow(0x10000)`` deckt den vollen Bereich 0..0xFFFF ab; das alte
    ``randrange(0, 0xFFFF)`` liess 0xFFFF aus.
    """
    return secrets.randbelow(0x10000)


def build_query(name: str, qid: int) -> bytes:
    header = struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0)   # RD set
    return header + _encode_name(name) + struct.pack("!HH", _TYPE_SRV, _CLASS_IN)


def parse_srv(msg: bytes, qid: int) -> tuple[str, int] | None:
    """Pick the SRV record with the lowest priority. None if there is none.

    Total by design — a truncated or malformed reply is just "no answer", never
    an exception, because this parses bytes handed over by whatever answered on
    port 53.
    """
    if len(msg) < 12:
        return None
    try:
        rid, _flags, qd, an, _ns, _ar = struct.unpack("!HHHHHH", msg[:12])
        if rid != qid or an == 0:
            return None

        off = 12
        for _ in range(qd):
            _, off = _read_name(msg, off)
            off += 4                                # qtype + qclass

        best: tuple[int, str, int] | None = None
        for _ in range(an):
            _, off = _read_name(msg, off)
            if off + 10 > len(msg):
                break
            rtype, _rclass, _ttl, rdlen = struct.unpack("!HHIH", msg[off:off + 10])
            off += 10
            if off + rdlen > len(msg):
                break
            if rtype == _TYPE_SRV and rdlen >= 7:
                priority, _weight, port = struct.unpack("!HHH", msg[off:off + 6])
                target, _ = _read_name(msg, off + 6)
                if target and (best is None or priority < best[0]):
                    best = (priority, target, port)
            off += rdlen
    except (ValueError, struct.error, IndexError):
        return None

    if best is None:
        return None
    return best[1], best[2]


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_srv(name: str, *, timeout: float = TIMEOUT,
                use_cache: bool = True) -> tuple[str, int] | None:
    """Resolve *name* to ``(target_host, port)``, or None on any failure.

    Negative results are cached too, so an unreachable resolver does not stall
    the probe loop every 3 seconds.
    """
    if not name:
        return None

    now = time.monotonic()
    if use_cache:
        with _lock:
            hit = _cache.get(name)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    result: tuple[str, int] | None = None
    for resolver in RESOLVERS:
        qid = _neue_qid()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(timeout)
            sock.sendto(build_query(name, qid), (resolver, 53))
            data, _ = sock.recvfrom(2048)
            result = parse_srv(data, qid)
            if result:
                break
        except Exception:
            continue
        finally:
            sock.close()

    with _lock:
        _cache[name] = (now, result)
    return result
