"""Gemeinsame Bausteine fuer die Tests zum Streckenaustausch (Plan 1.1.0 §5).

Baut gueltige Entwuerfe im Format des Editors (``TileTrackDraft.to_draft_dict``)
und startet einen echten Relay auf einem freien Port, mit eigenem
Speicherverzeichnis.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import struct
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "server"))

import server as srv  # noqa: E402

_LEN = struct.Struct("!I")


def rundkurs(breit: int = 8, hoch: int = 6, name: str = "Testrunde", *,
             versatz: tuple[int, int] = (0, 0), breite: float = 260.0,
             schwierigkeit: str = "Mittel", textur: str = "Plains") -> dict:
    """Ein Rechteck aus Geraden mit Viertelkreisen (Radius 1) in den Ecken.

    Start/Ziel liegt auf der unteren Kante, die Fahrtrichtung ist von West nach
    Ost. ``breit`` und ``hoch`` zaehlen Zellen, mindestens 3.
    """
    dc, dr = versatz
    teile: list[dict] = []

    def teil(art, col, row, rot, r=1):
        teile.append({"kind": art, "col": col + dc, "row": row + dr,
                      "rotation": rot, "radius_cells": r})

    # untere Kante von West nach Ost, links beginnend mit der Ecke
    teil("curve", 0, 0, 2)                       # unten links: Ost + Nord
    for c in range(1, breit - 1):
        teil("straight", c, 0, 0)
    teil("curve", breit - 1, 0, 1)               # unten rechts: West + Nord
    for r in range(1, hoch - 1):
        teil("straight", breit - 1, r, 1)
    teil("curve", breit - 1, hoch - 1, 0)        # oben rechts: West + Ssued
    for c in range(breit - 2, 0, -1):
        teil("straight", c, hoch - 1, 0)
    teil("curve", 0, hoch - 1, 3)                # oben links: Ost + Sued
    for r in range(hoch - 2, 0, -1):
        teil("straight", 0, r, 1)
    start = 3                                    # Gerade mit einer Geraden davor
    return {
        "version": 1, "name": name, "width": breite,
        "background_texture": textur, "difficulty": schwierigkeit,
        "description": "Eine Testrunde.", "start_piece_idx": start,
        "pieces": teile,
    }


def kopie(d: dict) -> dict:
    return copy.deepcopy(d)


# -- Netz --------------------------------------------------------------------

async def senden(writer, msg: dict) -> None:
    body = json.dumps(msg).encode()
    writer.write(_LEN.pack(len(body)) + body)
    await writer.drain()


async def empfangen(reader, timeout: float = 3.0) -> dict | None:
    try:
        roh = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        laenge = _LEN.unpack(roh)[0]
        koerper = await asyncio.wait_for(reader.readexactly(laenge), timeout=timeout)
        return json.loads(koerper)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        return None


class Relay:
    """Relay im selben Prozess auf einem freien Port, mit eigenem Speicher."""

    def __init__(self, verzeichnis: str, **grenzen) -> None:
        self.verzeichnis = verzeichnis
        self.grenzen = grenzen
        self.server = None
        self.port = 0

    async def __aenter__(self):
        self._alt = (srv._registry, srv._strecken_speicher, srv.TRUSTED_PROXIES)
        srv._registry = srv._Registry()
        # Der Testclient kommt von 127.0.0.1; ohne diese Zeile gilt das als
        # Tunnel und alle Absender waeren ein Konto.
        srv.TRUSTED_PROXIES = frozenset()
        srv._strecken_speicher = srv.StreckenSpeicher(self.verzeichnis, **self.grenzen)
        self.server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        srv._registry, srv._strecken_speicher, srv.TRUSTED_PROXIES = self._alt

    async def frage(self, msg: dict) -> dict | None:
        """Eine Anfrage als eigene Verbindung, wie der Client sie stellt."""
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        try:
            await senden(writer, msg)
            return await empfangen(reader)
        finally:
            writer.close()
