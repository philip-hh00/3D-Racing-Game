"""
Wire protocol for online multiplayer.

TCP:  length-prefixed JSON  →  4-byte big-endian length + UTF-8 JSON body
UDP:  binary struct packets →  fixed layout per message type

Keep in sync with server/server.py (same struct layouts).
"""
from __future__ import annotations

import json
import struct
from typing import Optional

# ── UDP message type bytes ─────────────────────────────────────────────────────
UDP_REGISTER = 0x00   # client registers UDP addr with server
UDP_STATE    = 0x01   # position broadcast (relayed by server)
UDP_PING     = 0x02   # client → server
UDP_PONG     = 0x03   # server → client (echoes timestamp)
UDP_BUMP     = 0x05   # peer → peer collision impulse (relayed by server)

# BUMP: type(B) lobby_id(6s) sender_slot(B) target_slot(B) impulse_x(f) impulse_y(f) → 17 bytes
BUMP_HEADER  = struct.Struct("!B 6s B B ff")


# ── Structs (network byte order, big-endian "!") ───────────────────────────────
# STATE header: type(B) lobby_id(6s) sender_slot(B) car_count(B) send_time(d)
#              → 17 bytes. send_time is the SENDER's monotonic clock at send.
# The receiver interpolates on this timeline (offset into its own clock), not
# on arrival time — so burst delivery (WLAN buffering: several packets arriving
# together after a gap) still plays back at the spacing they were sent, instead
# of stacking on one arrival instant and snapping the ghost.
STATE_HEADER = struct.Struct("!B 6s B B d")
# per-vehicle: id(B) vtype(B) x(f) y(f) angle(f) vx(f) vy(f) omega(f)
#              lap(B) wp(H)  → 29 bytes  (lap/wp = race progress for
#              cross-network position ranking)
# NOTE: server/server.py's _S_VEH doc-struct comment is now cosmetically
# out of date (server never unpacks vehicle bodies, so no functional change
# there is required).
VEHICLE_FMT  = struct.Struct("!BB ffffff B H")

# Vehicle config key <-> single-byte wire index, so remote peers render the
# correct car model/color instead of always falling back to "rookie".
# APPEND-ONLY: index = wire value; never reorder/remove existing entries or
# every peer must be on the same build to stay compatible.
VEHICLE_TYPES = [
    "rookie", "supercar", "drifter", "limousine", "electric",
    "rookie_2", "rookie_3",
    "supercar_2", "supercar_3",
    "drifter_2", "drifter_3",
    "limousine_2", "limousine_3",
    "electric_2", "electric_3",
]
_VTYPE_TO_IDX = {k: i for i, k in enumerate(VEHICLE_TYPES)}


def _vtype_to_idx(key: str) -> int:
    return _VTYPE_TO_IDX.get(key, 0)


def _idx_to_vtype(idx: int) -> str:
    return VEHICLE_TYPES[idx] if 0 <= idx < len(VEHICLE_TYPES) else "rookie"
# shared id header: type(B) lobby_id(6s) slot(B)                   → 8 bytes
ID_HEADER    = struct.Struct("!B 6s B")
# PING: type(B) lobby_id(6s) slot(B) timestamp(d)                  → 16 bytes
PING_FMT     = struct.Struct("!B 6s B d")
# PONG reply: type(B) timestamp(d)                                  → 9 bytes
PONG_FMT     = struct.Struct("!B d")
# TCP length prefix
LEN_PREFIX   = struct.Struct("!I")

# State packet max size: header(9) + 6 vehicles × 29 bytes = 183 bytes
# Well within a single UDP datagram.


def _lid(lobby_id: str) -> bytes:
    """Encode lobby_id to exactly 6 null-padded bytes."""
    return lobby_id.encode()[:6].ljust(6, b"\x00")


# ── TCP ───────────────────────────────────────────────────────────────────────

def pack_tcp(msg: dict) -> bytes:
    """Serialize a dict as length-prefixed UTF-8 JSON."""
    body = json.dumps(msg, ensure_ascii=False).encode()
    return LEN_PREFIX.pack(len(body)) + body


def read_tcp_length(header4: bytes) -> int:
    return LEN_PREFIX.unpack(header4)[0]


# ── UDP pack ──────────────────────────────────────────────────────────────────

#: Laenge des Sitzungstokens hinter dem gemeinsamen Kopf (Block H, H2.1 Stufe 2).
#: Muss zu ``server.py:_TOKEN_B`` passen.
TOKEN_B = 16


def pack_register(lobby_id: str, slot: int, token: str = "") -> bytes:
    """UDP_REGISTER: tell server which lobby/slot owns this source addr.

    Das Token kommt aus ``JOIN_OK`` und haengt **hinter** dem gemeinsamen
    Kopf — ``PING`` teilt denselben Kopf und bleibt damit unveraendert. Ohne
    Token nahm der Server die Registrierung allein aufgrund des Paketinhalts an:
    wer die Lobby-ID kannte, konnte den Positionsstrom eines fremden Spielers auf
    sich umleiten (Block H, H2.1).
    """
    roh = str(token).encode("ascii", "ignore")[:TOKEN_B]
    return ID_HEADER.pack(UDP_REGISTER, _lid(lobby_id), slot) + roh.ljust(TOKEN_B, b"\x00")


def pack_state(lobby_id: str, sender_slot: int, vehicles: list[dict],
               send_time: float = 0.0) -> bytes:
    """
    Pack a STATE packet.

    vehicles — list of dicts with keys: id, x, y, angle, vx, vy, omega, cfg, lap, wp
    ("cfg" is a vehicle config key, e.g. "rookie"; defaults to "rookie" if absent.
    "lap"/"wp" are race-progress fields; default to 0 if absent).
    send_time — the sender's monotonic clock at send, for receiver-side
    timeline reconstruction.
    Total size: 17 + 29 × len(vehicles) bytes.
    """
    header = STATE_HEADER.pack(UDP_STATE, _lid(lobby_id), sender_slot,
                               len(vehicles), float(send_time))
    body = b"".join(
        VEHICLE_FMT.pack(
            v["id"], _vtype_to_idx(v.get("cfg", "rookie")),
            v["x"], v["y"], v["angle"], v["vx"], v["vy"], v["omega"],
            min(255, max(0, int(v.get("lap", 0)))),
            min(65535, max(0, int(v.get("wp", 0)))),
        )
        for v in vehicles
    )
    return header + body


def pack_ping(lobby_id: str, slot: int, ts: float) -> bytes:
    return PING_FMT.pack(UDP_PING, _lid(lobby_id), slot, ts)


# ── UDP unpack ────────────────────────────────────────────────────────────────

def unpack_state(data: bytes) -> Optional[dict]:
    """
    Unpack a STATE packet received from the relay.

    Returns:
        {"lobby_id": str, "sender_slot": int,
         "vehicles": [{"id": int, "x": float, "y": float, "angle": float,
                       "vx": float, "vy": float, "omega": float,
                       "lap": int, "wp": int}, ...]}
    or None on malformed input.
    """
    if len(data) < STATE_HEADER.size:
        return None
    _, lid_b, sender_slot, count, send_time = STATE_HEADER.unpack(data[:STATE_HEADER.size])
    lobby_id = lid_b.decode(errors="ignore").rstrip("\x00")

    offset   = STATE_HEADER.size
    vsz      = VEHICLE_FMT.size
    vehicles = []
    for _ in range(count):
        if offset + vsz > len(data):
            break
        vid, vtype, x, y, angle, vx, vy, omega, lap, wp = VEHICLE_FMT.unpack(data[offset:offset + vsz])
        vehicles.append({
            "id": vid, "cfg": _idx_to_vtype(vtype), "x": x, "y": y, "angle": angle,
            "vx": vx, "vy": vy, "omega": omega, "lap": lap, "wp": wp,
        })
        offset += vsz

    return {"lobby_id": lobby_id, "sender_slot": sender_slot,
            "send_time": send_time, "vehicles": vehicles}


def unpack_pong(data: bytes) -> Optional[float]:
    """Extract echoed timestamp from a PONG packet, or None."""
    if len(data) < PONG_FMT.size:
        return None
    _, ts = PONG_FMT.unpack(data[:PONG_FMT.size])
    return ts


def pack_bump(lobby_id: str, sender_slot: int, target_slot: int,
              impulse_x: float, impulse_y: float) -> bytes:
    """Pack a UDP_BUMP packet to send a collision impulse to a peer."""
    return BUMP_HEADER.pack(UDP_BUMP, _lid(lobby_id), sender_slot, target_slot,
                            float(impulse_x), float(impulse_y))


def unpack_bump(data: bytes) -> Optional[dict]:
    """Unpack a UDP_BUMP packet."""
    if len(data) < BUMP_HEADER.size:
        return None
    _, lid_b, sender_slot, target_slot, ix, iy = BUMP_HEADER.unpack(data[:BUMP_HEADER.size])
    lobby_id = lid_b.decode(errors="ignore").rstrip("\x00")
    return {"lobby_id": lobby_id, "sender_slot": sender_slot,
            "target_slot": target_slot, "impulse": (ix, iy)}

