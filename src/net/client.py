"""
NetworkClient — non-blocking game-side network interface.

Two daemon threads (TCP recv, UDP recv) fill a thread-safe queue.
The game loop calls poll() each frame to drain the queue (never blocks).

Usage:
    net = NetworkClient()
    sd = servers.by_id("helsinki")
    if net.connect(sd.tcp_host, sd.tcp_port, udp_host=sd.udp_host,
                   udp_port=sd.udp_port, preamble=sd.preamble_bytes()):
        net.send_tcp({"type": "HOST", "name": "Spieler1"})

    # after JOIN_OK arrives in poll():
    net.set_lobby(lobby_id, slot, token)
    net.register_udp()

    # every frame:
    for evt in net.poll():
        src  = evt["source"]   # "tcp" | "udp" | "error" | "internal"
        data = evt["data"]     # dict
        ...

    net.update(dt)   # sends periodic pings
    net.send_state(vehicles)   # 20 Hz — caller must throttle
"""
from __future__ import annotations

import json
import queue
import socket
import struct
import threading
import time
from typing import Iterator, Optional

from src.core.version import VERSION
from src.net.protocol import (
    LEN_PREFIX,
    UDP_PONG, UDP_STATE, UDP_BUMP,
    pack_ping, pack_register, pack_state, pack_bump,
    unpack_pong, unpack_state, unpack_bump,
)


_RECV_BUF    = 8192
_MAX_TCP_MSG = 2 * 1024 * 1024   # 2 MB safety cap
_TCP_TIMEOUT = 60.0               # recv timeout between messages
_UDP_TIMEOUT = 0.1                # non-blocking poll interval


class NetworkClient:
    """Thread-safe network facade for the game loop."""

    def __init__(self):
        self._tcp:  Optional[socket.socket] = None
        self._udp:  Optional[socket.socket] = None
        self._q:    queue.Queue             = queue.Queue()
        self._lock  = threading.Lock()
        self._alive = False

        self._server_addr: tuple = ("", 0)
        self._lobby_id:    str   = ""
        self._slot:        int   = -1

        # Ping state
        self._ping_sent:    float = 0.0
        self._ping_ms:      float = 0.0
        self._ping_accum:   float = 0.0
        self._ping_interval: float = 1.0
        self._tcp_ping_accum: float = 0.0

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self, host: str, port: int, *,
                udp_host: str | None = None, udp_port: int | None = None,
                preamble: bytes = b"") -> bool:
        """Open TCP + UDP sockets, start recv threads. Returns False on error.

        TCP and UDP endpoints are separate: the Hamburg home server is reached
        through two independent playit.gg tunnels that hit different local
        ports. *preamble* is sent before the first frame — the Minecraft
        handshake that tunnel demands (see src/net/mc_preamble.py); empty for a
        direct connection.
        """
        self._server_addr = (udp_host or host, udp_port or port)
        try:
            self._tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp.settimeout(10.0)
            self._tcp.connect((host, port))
            if preamble:
                self._tcp.sendall(preamble)
            self._tcp.settimeout(_TCP_TIMEOUT)

            self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp.bind(("", 0))
            self._udp.settimeout(_UDP_TIMEOUT)

            self._alive = True
            threading.Thread(target=self._tcp_loop, daemon=True, name="net-tcp").start()
            threading.Thread(target=self._udp_loop, daemon=True, name="net-udp").start()
            return True

        except OSError as exc:
            # Close any partially opened socket (e.g. TCP connected but UDP bind failed).
            for sock in (self._tcp, self._udp):
                if sock:
                    try:
                        sock.close()
                    except OSError:
                        pass
            self._tcp = None
            self._udp = None
            self._q.put({"source": "error",
                         "data": {"type": "CONNECT_ERROR", "reason": str(exc)}})
            return False

    def disconnect(self):
        """Close sockets; recv threads exit on next read."""
        self._alive = False
        for sock in (self._tcp, self._udp):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self._tcp = None
        self._udp = None

    # ── Lobby config ──────────────────────────────────────────────────────────

    def set_lobby(self, lobby_id: str, slot: int, token: str = ""):
        """Call immediately after receiving JOIN_OK.

        *token* ist das Sitzungstoken aus ``JOIN_OK``; ``UDP_REGISTER`` muss es
        tragen, sonst weist der Server die Registrierung ab (Block H, H2.1).
        """
        self._lobby_id = lobby_id
        self._slot     = slot
        self._udp_token = token

    def register_udp(self):
        """Tell server which lobby/slot owns this UDP source address.
        Call once after set_lobby() and once after any network change."""
        if not self._udp or not self._lobby_id:
            return
        data = pack_register(self._lobby_id, self._slot,
                             getattr(self, "_udp_token", ""))
        self._udp_send(data)

    # ── Send ─────────────────────────────────────────────────────────────────

    def send_tcp(self, msg: dict):
        """Serialize and send a JSON message over TCP (thread-safe)."""
        if not self._tcp:
            return
        if msg.get("type") in ("HOST", "JOIN") and "version" not in msg:
            msg["version"] = VERSION
        body = json.dumps(msg, ensure_ascii=False).encode()
        packet = LEN_PREFIX.pack(len(body)) + body
        with self._lock:
            try:
                self._tcp.sendall(packet)
            except OSError:
                self._alive = False

    def send_state(self, vehicles: list[dict]):
        """Send a UDP STATE packet. Caller is responsible for the send throttle."""
        if not self._udp or not self._lobby_id:
            return
        data = pack_state(self._lobby_id, self._slot, vehicles, time.monotonic())
        self._udp_send(data)

    def send_bump(self, target_slot: int, impulse_x: float, impulse_y: float):
        """Send a UDP_BUMP packet to relay a collision impulse to a peer."""
        if not self._udp or not self._lobby_id:
            return
        data = pack_bump(self._lobby_id, self._slot, target_slot, impulse_x, impulse_y)
        self._udp_send(data)


    def upload_map(self, path: str):
        """
        Upload a custom map file via TCP.
        Sends MAP_UPLOAD_META → chunks → MAP_DONE.
        Raises ValueError if file exceeds 1 MB.
        Call from a worker thread (blocks while reading file).
        """
        import base64
        import os

        size = os.path.getsize(path)
        if size > 1024 * 1024:
            raise ValueError(
                f"Map zu groß: {size / 1024:.0f} KB — Maximum 1024 KB für Online-Übertragung."
            )

        track_name = os.path.basename(path)
        self.send_tcp({
            "type": "START_REQUEST",
            "track_name": track_name,
            "is_custom": True,
            "size": size,
        })

        # Use a multiple of 3 (e.g., 32766 instead of 32768) so that base64 encoding 
        # of each chunk does not produce padding '=' signs at the end of the chunk.
        # This allows clients to safely concatenate incoming chunks before decoding.
        chunk_size = 32766
        with open(path, "rb") as f:
            while True:
                raw = f.read(chunk_size)
                if not raw:
                    break
                self.send_tcp({"type": "MAP_CHUNK", "data": base64.b64encode(raw).decode()})

        self.send_tcp({"type": "MAP_DONE"})

    def upload_offer(self, path: str, title: str = ""):
        """Eine eigene Strecke als Vorschlag in die Lobby legen.

        Sendet OFFER_META -> OFFER_CHUNK... -> OFFER_DONE. Getrennt vom
        Rennstart-Transfer (upload_map): ein Vorschlag liegt nur in der Lobby
        und startet nichts. Aus einem Arbeitsfaden aufrufen, das Lesen der
        Datei blockiert.

        Raises ValueError, wenn die Datei groesser als 1 MB ist.
        """
        import base64
        import os

        size = os.path.getsize(path)
        if size > 1024 * 1024:
            raise ValueError(
                f"Strecke zu groß: {size / 1024:.0f} KB — Maximum 1024 KB für Online-Übertragung."
            )

        track_name = os.path.basename(path)
        self.send_tcp({
            "type": "OFFER_META",
            "track_name": track_name,
            # Angezeigt wird der Streckenname, nicht der Dateiname.
            "title": title or track_name,
            "size": size,
        })

        # Ein Vielfaches von 3 bytes (z.B. 32766 statt 32768), damit base64
        # ohne Füllzeichen ('=') am Ende endet und Stücke vor dem Dekodieren
        # aneinanderhängt werden können.
        chunk_size = 32766
        with open(path, "rb") as f:
            while True:
                raw = f.read(chunk_size)
                if not raw:
                    break
                self.send_tcp({"type": "OFFER_CHUNK", "data": base64.b64encode(raw).decode()})

        self.send_tcp({"type": "OFFER_DONE"})

    def request_offer(self, slot: int):
        """Einen Vorschlag anfordern. Die Antwort kommt als
        OFFER_DATA_META / OFFER_DATA_CHUNK / OFFER_DATA_DONE ueber poll()."""
        self.send_tcp({"type": "OFFER_REQUEST", "slot": int(slot)})

    # ── Per-frame ─────────────────────────────────────────────────────────────

    def poll(self) -> Iterator[dict]:
        """Drain the incoming event queue. Call once per game frame."""
        while True:
            try:
                yield self._q.get_nowait()
            except queue.Empty:
                return

    def update(self, dt: float):
        """Send periodic UDP pings. Call once per game frame."""
        if not (self._alive and self._lobby_id):
            return
        self._ping_accum += dt
        if self._ping_accum >= self._ping_interval:
            self._ping_accum    = 0.0
            self._ping_sent     = time.monotonic()
            self._udp_send(pack_ping(self._lobby_id, self._slot, self._ping_sent))

        # TCP keepalive to prevent server timeout (timeout=60s in server's _recv)
        self._tcp_ping_accum += dt
        if self._tcp_ping_accum >= 20.0:
            self._tcp_ping_accum = 0.0
            self.send_tcp({"type": "PING"})

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def ping_ms(self) -> float:
        return self._ping_ms

    @property
    def connected(self) -> bool:
        return self._alive

    @property
    def lobby_id(self) -> str:
        return self._lobby_id

    @property
    def slot(self) -> int:
        return self._slot

    # ── Recv threads ─────────────────────────────────────────────────────────

    def _tcp_loop(self):
        buf = b""
        while self._alive:
            try:
                chunk = self._tcp.recv(_RECV_BUF)
                if not chunk:
                    break
                buf += chunk

                # Parse all complete messages from buffer
                while True:
                    if len(buf) < 4:
                        break
                    length = LEN_PREFIX.unpack(buf[:4])[0]
                    if length > _MAX_TCP_MSG:
                        self._alive = False
                        break
                    total = 4 + length
                    if len(buf) < total:
                        break
                    raw  = buf[4:total]
                    buf  = buf[total:]
                    try:
                        msg = json.loads(raw)
                        self._handle_tcp_msg(msg)
                        self._q.put({"source": "tcp", "data": msg})
                    except json.JSONDecodeError as e:
                        print(f"[NetworkClient] JSON decode error: {e} — raw length: {len(raw)}")
                        # Put error event so game can react (e.g., show connection issue)
                        self._q.put({"source": "error", "data": {"type": "JSON_DECODE_ERROR", "detail": str(e)}})

            except socket.timeout:
                continue
            except OSError:
                break

        self._alive = False
        self._q.put({"source": "error", "data": {"type": "DISCONNECTED"}})

    def _udp_loop(self):
        while self._alive:
            try:
                data, _ = self._udp.recvfrom(2048)
                if not data:
                    continue
                t = data[0]
                if t == UDP_PONG:
                    ts = unpack_pong(data)
                    if ts is not None:
                        self._ping_ms = (time.monotonic() - ts) * 1000.0
                elif t == UDP_STATE:
                    parsed = unpack_state(data)
                    if parsed:
                        # Stamp arrival here (in the recv thread) so the
                        # clock-offset estimate isn't skewed by however long the
                        # packet then waits in the queue.
                        parsed["arrival"] = time.monotonic()
                        self._q.put({"source": "udp", "data": parsed})
                elif t == UDP_BUMP:
                    parsed = unpack_bump(data)
                    if parsed:
                        self._q.put({"source": "udp_bump", "data": parsed})

            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_tcp_msg(self, msg: dict):
        """Process housekeeping for specific messages before they hit the queue."""
        if msg.get("type") == "JOIN_OK":
            self._lobby_id = msg.get("lobby_id", "")
            self._slot     = msg.get("slot", -1)

    def _udp_send(self, data: bytes):
        if self._udp:
            try:
                self._udp.sendto(data, self._server_addr)
            except OSError:
                pass
