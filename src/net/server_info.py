"""Fetch the relay server's live info (required version + announcements).

One blocking helper plus a fire-and-forget background variant used at game
start. The result is cached module-globally; UI screens read get_cached().
"""
from __future__ import annotations

import json
import socket
import struct
import threading

from src.core.version import VERSION

_LEN = struct.Struct("!I")
_cached: dict | None = None
_fetching = False


def get_cached() -> dict | None:
    """Last successful INFO response, or None if not (yet) fetched."""
    return _cached


def version_ok() -> bool | None:
    """True/False once info is available, None while unknown/offline."""
    if _cached is None:
        return None
    return bool(_cached.get("version_ok", True))


def _server_address() -> tuple[str, int]:
    # Same source the lobby uses: data/settings/server.json.
    try:
        with open("data/settings/server.json", encoding="utf-8") as f:
            cfg = json.load(f)
        return str(cfg.get("host", "127.0.0.1")), int(cfg.get("port", 7777))
    except Exception:
        return "127.0.0.1", 7777


def fetch_info(timeout: float = 4.0) -> dict | None:
    """Blocking: connect, send INFO, read one reply, close. None on failure."""
    global _cached
    host, port = _server_address()
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.settimeout(timeout)
            payload = json.dumps({"type": "INFO", "version": VERSION}).encode("utf-8")
            s.sendall(_LEN.pack(len(payload)) + payload)
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
            if msg.get("type") == "INFO":
                _cached = msg
                return msg
    except Exception:
        return None
    return None


def fetch_info_async() -> None:
    """Fire-and-forget background fetch (used once at game start)."""
    global _fetching
    if _fetching or _cached is not None:
        return
    _fetching = True

    def _run():
        global _fetching
        try:
            fetch_info()
        finally:
            _fetching = False

    threading.Thread(target=_run, daemon=True, name="server-info").start()
