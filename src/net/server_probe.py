"""Background health/latency probe for the relay servers.

Runs one daemon thread while the online menu is open and refreshes every server
in the catalogue every few seconds. The UI only reads the results — nothing here
touches pygame or blocks the render thread.

Two separate measurements per round:

* **TCP INFO** — reachability, version compatibility and the lobby count.
* **UDP ping** — the number the player sees.

The split matters: through the playit.gg tunnel the TCP path measures ~101 ms
while UDP measures ~46 ms (Helsinki: 43 / 40). Races carry *only* UDP traffic,
so showing the TCP figure would brand the home server as bad for a cost it never
pays during a race.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
import time
from dataclasses import dataclass

from src.core.version import VERSION
from src.net import servers, srv_lookup
from src.net.servers import ServerDef

_LEN  = struct.Struct("!I")
_PING = struct.Struct("!B 6s B d")
_PONG = struct.Struct("!B d")
_UDP_PING = 0x02
_UDP_PONG = 0x03

INTERVAL     = 3.0     # seconds between probe rounds
IDLE_STOP    = 8.0     # stop probing this long after the last statuses() call
TCP_TIMEOUT  = 4.0
UDP_TIMEOUT  = 1.0
UDP_SAMPLES  = 3

# Quality thresholds in milliseconds — measured over UDP.
GOOD_MS   = 40
MEDIUM_MS = 90

ONLINE   = "online"
OFFLINE  = "offline"
OUTDATED = "outdated"

#: Laststufe, bei der der Relay keine neuen Lobbys mehr annimmt. Der Text kommt
#: so vom Server (``server.py:LAST_VOLL``) — er steht in **einer** Sprache im
#: Protokoll und wird erst beim Anzeigen uebersetzt.
BUSY = "ausgelastet"


@dataclass
class ServerStatus:
    server:           ServerDef
    state:            str = OFFLINE
    ping_ms:          float | None = None
    lobby_count:      int = 0
    #: Lobbygrenze des Relays und seine Laststufe (Block H, H2.14). Ein Relay
    #: ohne die Neuerung schickt beides nicht — dann bleibt ``lobby_max`` 0 und
    #: die Anzeige zeigt weiter nur die Zahl der offenen Lobbys. Genau deshalb
    #: braucht dieser Teil **keinen** Versionsschnitt.
    lobby_max:        int = 0
    load:             str = ""
    required_version: str = ""
    tcp_host:         str = ""      # endpoint actually used (post SRV lookup)
    tcp_port:         int = 0
    udp_port:         int = 0

    @property
    def ausgelastet(self) -> bool:
        """Ob der Relay gerade keine neuen Lobbys annimmt (H2.14)."""
        return self.load == BUSY

    @property
    def selectable(self) -> bool:
        # Ausgelastet heisst: sichtbar, aber nicht waehlbar — dasselbe Muster wie
        # bei „Version veraltet". Wer es trotzdem probiert (die Zeile war beim
        # Anzeigen noch frei), bekommt SERVER_BUSY in der Lobby zu sehen.
        return self.state == ONLINE and not self.ausgelastet

    @property
    def bars(self) -> int:
        """0 = unknown/offline, 1 = poor, 2 = medium, 3 = good."""
        if self.state != ONLINE or self.ping_ms is None:
            return 0
        if self.ping_ms < GOOD_MS:
            return 3
        if self.ping_ms < MEDIUM_MS:
            return 2
        return 1


def quality_bars(ping_ms: float | None) -> int:
    """Bar count for a raw latency value (0 when unknown)."""
    if ping_ms is None:
        return 0
    if ping_ms < GOOD_MS:
        return 3
    if ping_ms < MEDIUM_MS:
        return 2
    return 1


# ── Single-shot measurements ──────────────────────────────────────────────────

def resolve_endpoint(sd: ServerDef) -> tuple[str, int, int]:
    """Current ``(tcp_host, tcp_port, udp_port)`` for *sd*.

    playit reassigns the port when its agent restarts, so a configured SRV
    record is re-resolved and wins over the stored values. Both tunnels of a
    playit account share one port number, so the SRV port is applied to UDP too.
    """
    if not sd.srv_record:
        return sd.tcp_host, sd.tcp_port, sd.udp_port
    hit = srv_lookup.resolve_srv(sd.srv_record)
    if not hit:
        return sd.tcp_host, sd.tcp_port, sd.udp_port
    target, port = hit
    return target or sd.tcp_host, port, port


def probe_tcp(sd: ServerDef, host: str, port: int,
              timeout: float = TCP_TIMEOUT) -> dict | None:
    """Send INFO, return the parsed reply, or None if unreachable.

    Pinned to IPv4 via gethostbyname because NetworkClient opens AF_INET
    sockets. The playit tunnel publishes an AAAA record, so an unpinned
    create_connection would happily measure a path the game never takes — and
    report a server as up (or down) for the wrong address family.
    """
    try:
        with socket.create_connection((socket.gethostbyname(host), port),
                                      timeout=timeout) as s:
            s.settimeout(timeout)
            pre = sd.preamble_bytes(host, port)
            payload = json.dumps({"type": "INFO", "version": VERSION}).encode("utf-8")
            s.sendall(pre + _LEN.pack(len(payload)) + payload)

            hdr = b""
            while len(hdr) < _LEN.size:
                chunk = s.recv(_LEN.size - len(hdr))
                if not chunk:
                    return None
                hdr += chunk
            (length,) = _LEN.unpack(hdr)
            if length > 512 * 1024:
                return None
            body = b""
            while len(body) < length:
                chunk = s.recv(length - len(body))
                if not chunk:
                    return None
                body += chunk
            msg = json.loads(body.decode("utf-8"))
            return msg if msg.get("type") == "INFO" else None
    except Exception:
        return None


def probe_udp(host: str, port: int, samples: int = UDP_SAMPLES,
              timeout: float = UDP_TIMEOUT) -> float | None:
    """Best of *samples* UDP round trips in ms, or None if nothing answers.

    The relay replies to PING without needing a lobby, so a dummy id is fine.
    """
    try:
        addr = (socket.gethostbyname(host), port)
    except OSError:
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    best: float | None = None
    try:
        for _ in range(samples):
            sent = time.monotonic()
            try:
                sock.sendto(_PING.pack(_UDP_PING, b"PROBE\x00", 0, sent), addr)
                data, _ = sock.recvfrom(2048)
            except OSError:
                continue
            if len(data) < _PONG.size or data[0] != _UDP_PONG:
                continue
            _, echoed = _PONG.unpack(data[:_PONG.size])
            rtt = (time.monotonic() - echoed) * 1000.0
            if best is None or rtt < best:
                best = rtt
    finally:
        sock.close()
    return best


def probe_once(sd: ServerDef) -> ServerStatus:
    """One full measurement round for a single server."""
    host, tcp_port, udp_port = resolve_endpoint(sd)
    st = ServerStatus(server=sd, tcp_host=host, tcp_port=tcp_port, udp_port=udp_port)

    info = probe_tcp(sd, host, tcp_port)
    if info is None:
        return st                                   # OFFLINE
    st.lobby_count      = int(info.get("lobby_count", 0) or 0)
    st.lobby_max        = int(info.get("lobby_max", 0) or 0)
    st.load             = str(info.get("load", ""))
    st.required_version = str(info.get("required_version", ""))
    if not info.get("version_ok", True):
        st.state = OUTDATED
        return st

    st.ping_ms = probe_udp(host, udp_port)
    # TCP alone is not enough: the race never uses it. A server whose UDP path
    # is dead would let players into a lobby and then strand them.
    st.state = ONLINE if st.ping_ms is not None else OFFLINE
    return st


# ── Background prober ─────────────────────────────────────────────────────────

class _Prober:
    def __init__(self) -> None:
        self._lock    = threading.Lock()
        self._results: dict[str, ServerStatus] = {}
        self._thread: threading.Thread | None = None
        self._stop    = threading.Event()
        self._last_read = 0.0

    def start(self) -> None:
        """Idempotent — safe to call every frame while a server list is visible."""
        self._last_read = time.monotonic()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        with self._lock:
            for sd in servers.all_servers():
                self._results.setdefault(sd.id, ServerStatus(server=sd))
        self._thread = threading.Thread(target=self._run, daemon=True, name="server-probe")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # The menu shell pops pages without an exit hook, so the thread ends
        # itself once nobody is looking at the results any more.
        while not self._stop.is_set():
            if time.monotonic() - self._last_read > IDLE_STOP:
                return
            for sd in servers.all_servers():
                if self._stop.is_set():
                    return
                st = probe_once(sd)
                with self._lock:
                    self._results[sd.id] = st
            self._stop.wait(INTERVAL)

    def statuses(self) -> list[ServerStatus]:
        """Current status per server, in catalogue order."""
        self._last_read = time.monotonic()
        with self._lock:
            return [self._results.get(sd.id) or ServerStatus(server=sd)
                    for sd in servers.all_servers()]

    def get(self, server_id: str) -> ServerStatus | None:
        with self._lock:
            return self._results.get(server_id)


_prober = _Prober()

start    = _prober.start
stop     = _prober.stop
statuses = _prober.statuses
get      = _prober.get
