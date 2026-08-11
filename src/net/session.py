"""Global network session — singleton NetworkClient shared across states."""
from __future__ import annotations
from typing import Optional

_client = None
_lobby_page = None   # OnlineLobbyPage instance kept alive across sub-state navigation


def get():
    """Return the active NetworkClient or None."""
    return _client


def set(client) -> None:
    global _client
    if _client is not None and _client is not client:
        try:
            _client.disconnect()
        except Exception:
            pass
    _client = client


def get_lobby_page():
    return _lobby_page


def set_lobby_page(page) -> None:
    global _lobby_page
    _lobby_page = page


def clear() -> None:
    """Disconnect and discard the current client and lobby page reference."""
    global _client, _lobby_page
    if _client is not None:
        _client.disconnect()
    _client = None
    _lobby_page = None
