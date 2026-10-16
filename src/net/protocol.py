"""
Wire protocol for online multiplayer.

TCP:  length-prefixed JSON  →  4-byte big-endian length + UTF-8 JSON body
UDP:  binary struct packets →  fixed layout per message type

Keep in sync with server/server.py (same struct layouts).
"""
from __future__ import annotations

import json
import math
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
# PONG with the relay clock: type(B) timestamp(d) server_time(d)    → 17 bytes.
# timestamp = the client's PING stamp echoed, server_time = the relay's
# monotonic clock when it answered. The first 9 bytes are the old PONG, so
# clients that only know PONG_FMT keep working. See src/net/uhrsync.py.
PONG_EXT_FMT = struct.Struct("!B d d")

# STATE trailer (appended AFTER the car bodies; a parser that stops after
# ``car_count`` bodies — the relay's schutz.py, the 2D game — never sees it):
#   head: mark(B)=0xE1 flags(B) clock_offset(d)                    → 10 bytes
#         flags bit0 = clock_offset valid. clock_offset = (relay clock - the
#         sender's monotonic clock) at send: with the header's send_time it puts
#         every snapshot on the shared relay timeline, so the receiver knows its
#         exact age (present-time prediction, src/entities/remote_vehicle.py).
#   per car, in body order: steer(b) throttle(b) brake(B) flags(B) → 4 bytes
#         steer -127..127 = -1..1, throttle -127..127 = -1..1 (negative =
#         reverse), brake 0..255 = 0..1, flags bit0 = handbrake.
# One car: 17 + 29 + 10 + 4 = 60 bytes. Six cars: 17 + 174 + 10 + 24 = 225.
STATE_EXT_MARK = 0xE1
STATE_EXT_HEAD = struct.Struct("!B B d")
STATE_EXT_CAR  = struct.Struct("!b b B B")
# TCP length prefix
LEN_PREFIX   = struct.Struct("!I")

# State packet max size: header(17) + 6 vehicles × 29 + trailer(10 + 6 × 4) = 225 bytes
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


def _zahl(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _q127(x) -> int:
    """-1..1 -> -127..127."""
    return max(-127, min(127, int(round(_zahl(x) * 127.0))))


def pack_state(lobby_id: str, sender_slot: int, vehicles: list[dict],
               send_time: float = 0.0, clock_offset: Optional[float] = None) -> bytes:
    """
    Pack a STATE packet.

    vehicles — list of dicts with keys: id, x, y, angle, vx, vy, omega, cfg, lap, wp
    ("cfg" is a vehicle config key, e.g. "rookie"; defaults to "rookie" if absent.
    "lap"/"wp" are race-progress fields; default to 0 if absent). Optional
    inputs per car: "steer", "throttle", "brake", "handbrake".
    send_time — the sender's monotonic clock at send, for receiver-side
    timeline reconstruction.
    clock_offset — relay clock minus the sender's clock (None: not synchronised
    yet). The trailer (inputs + offset) is written when either is present.
    Total size: 17 + 29 × len(vehicles) bytes, plus 10 + 4 × len(vehicles)
    with the trailer.
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
    mit_eingaben = any("steer" in v for v in vehicles)
    gueltig = clock_offset is not None and math.isfinite(clock_offset)
    if not (mit_eingaben or gueltig):
        return header + body
    ext = STATE_EXT_HEAD.pack(STATE_EXT_MARK, 1 if gueltig else 0,
                              float(clock_offset) if gueltig else 0.0)
    ext += b"".join(
        STATE_EXT_CAR.pack(
            _q127(v.get("steer", 0.0)), _q127(v.get("throttle", 0.0)),
            min(255, max(0, int(round(_zahl(v.get("brake", 0.0)) * 255.0)))),
            1 if v.get("handbrake") else 0,
        )
        for v in vehicles
    )
    return header + body + ext


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

    # Trailer: only trusted when it has exactly the length the car count asks
    # for — anything else (an older/newer sender, a damaged datagram) is ignored.
    clock_offset = None
    rest = len(data) - offset
    if (len(vehicles) == count and rest == STATE_EXT_HEAD.size + STATE_EXT_CAR.size * count
            and data[offset] == STATE_EXT_MARK):
        _, flags, off = STATE_EXT_HEAD.unpack(data[offset:offset + STATE_EXT_HEAD.size])
        if (flags & 1) and math.isfinite(off):
            clock_offset = off
        pos = offset + STATE_EXT_HEAD.size
        for v in vehicles:
            steer, thr, brk, fl = STATE_EXT_CAR.unpack(data[pos:pos + STATE_EXT_CAR.size])
            pos += STATE_EXT_CAR.size
            v["steer"] = steer / 127.0
            v["throttle"] = thr / 127.0
            v["brake"] = brk / 255.0
            v["handbrake"] = bool(fl & 1)

    return {"lobby_id": lobby_id, "sender_slot": sender_slot,
            "send_time": send_time, "vehicles": vehicles,
            "clock_offset": clock_offset}


def unpack_pong(data: bytes) -> Optional[float]:
    """Extract echoed timestamp from a PONG packet, or None."""
    if len(data) < PONG_FMT.size:
        return None
    _, ts = PONG_FMT.unpack(data[:PONG_FMT.size])
    return ts


def unpack_pong_ext(data: bytes) -> Optional[tuple]:
    """(echoed PING stamp, relay clock or None) from a PONG, or None if malformed.

    A relay that predates the clock sync answers with the short 9-byte PONG;
    then the second value is None and the client stays on snapshot interpolation.
    """
    if len(data) >= PONG_EXT_FMT.size:
        _, ts, server_time = PONG_EXT_FMT.unpack(data[:PONG_EXT_FMT.size])
        if math.isfinite(server_time):
            return ts, server_time
        return ts, None
    if len(data) >= PONG_FMT.size:
        _, ts = PONG_FMT.unpack(data[:PONG_FMT.size])
        return ts, None
    return None


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

