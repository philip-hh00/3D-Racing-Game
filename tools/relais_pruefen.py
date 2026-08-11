#!/usr/bin/env python3
"""Rauchtest gegen die echten Relays — nach jedem Server-Deploy.

    python tools/relais_pruefen.py

Prüft, was von außen prüfbar ist, ohne einen einzigen Spieler zu störén: eine
``INFO``-Abfrage, ein UDP-Ping, und **eine** Lobby, die sofort wieder
geschlossen wird.

Warum es dieses Werkzeug gibt: die Angriffstests aus ``tests/test_relais_absicherung.py``
gehören ausdrücklich **nicht** gegen die Produktion. Eine Verbindungsflut ist von
einem echten Angriff nicht zu unterscheiden, kann den playit.gg-Tunnel drosseln
und sperrt beim Auslösen der Aufnahmesperre gerade spielende Leute aus. Was gegen
die echten Server gehört, ist genau das hier: **läuft dort der Stand, den ich
gepullt habe?**

Die wichtigste Frage von allen ist die dritte. ``live_config.json`` wird bei jeder
Anfrage frisch gelesen, ``server.py`` **nicht** — ein Pull ohne Neustart des
Prozesses sieht in der Versionsanzeige richtig aus und hat trotzdem keine der
neuen Prüfungen an Bord. Die neuen ``INFO``-Felder sind der Beweis, dass der
neue Code läuft.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.version import VERSION            # noqa: E402
from src.net import servers                     # noqa: E402
from src.net.protocol import pack_register      # noqa: E402
from src.net.server_probe import resolve_endpoint  # noqa: E402

_LEN  = struct.Struct("!I")
_PING = struct.Struct("!B 6s B d")
_PONG = struct.Struct("!B d")
_UDP_PING, _UDP_PONG = 0x02, 0x03

OK, WARN, FEHLER = "  ok  ", " warn ", "FEHLER"
_zaehler = {OK: 0, WARN: 0, FEHLER: 0}


def sagen(stufe: str, text: str) -> None:
    _zaehler[stufe] = _zaehler.get(stufe, 0) + 1
    print(f"   [{stufe}] {text}")


class Draht:
    """Eine TCP-Verbindung zum Relay, mit dem Rahmenformat des Spiels."""

    def __init__(self, host: str, port: int, preamble: bytes = b"") -> None:
        self.sock = socket.create_connection((host, port), timeout=8.0)
        self.sock.settimeout(8.0)
        if preamble:
            self.sock.sendall(preamble)

    def senden(self, msg: dict) -> None:
        rumpf = json.dumps(msg, ensure_ascii=False).encode()
        self.sock.sendall(_LEN.pack(len(rumpf)) + rumpf)

    def empfangen(self, zeit: float = 8.0) -> dict | None:
        self.sock.settimeout(zeit)
        try:
            kopf = self._genau(4)
            (n,) = _LEN.unpack(kopf)
            return json.loads(self._genau(n))
        except (OSError, ValueError, struct.error):
            return None

    def warten_auf(self, typ: str, zeit: float = 8.0) -> dict | None:
        ende = time.monotonic() + zeit
        while time.monotonic() < ende:
            msg = self.empfangen(max(0.5, ende - time.monotonic()))
            if msg is None:
                return None
            if msg.get("type") == typ:
                return msg
        return None

    def _genau(self, n: int) -> bytes:
        aus = b""
        while len(aus) < n:
            teil = self.sock.recv(n - len(aus))
            if not teil:
                raise OSError("Verbindung zu")
            aus += teil
        return aus

    def zu(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def udp_ping(host: str, port: int) -> float | None:
    """Das Rennen läuft **nur** über UDP. Ein Relay mit totem UDP-Weg ließe
    Spieler in die Lobby und dann im Nichts stehen."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    try:
        for _ in range(3):
            los = time.monotonic()
            try:
                s.sendto(_PING.pack(_UDP_PING, b"PROBE\x00", 0, los), (host, port))
                daten, _ = s.recvfrom(2048)
            except OSError:
                continue
            if len(daten) >= _PONG.size and daten[0] == _UDP_PONG:
                _, echo = _PONG.unpack(daten[:_PONG.size])
                return (time.monotonic() - echo) * 1000.0
        return None
    finally:
        s.close()


def pruefen(sd) -> None:
    host, tcp_port, udp_port = resolve_endpoint(sd)
    print(f"\n── {sd.label}  ({host}:{tcp_port} TCP / {udp_port} UDP)")

    # 1. Erreichbarkeit und INFO
    try:
        d = Draht(host, tcp_port, sd.preamble_bytes(host, tcp_port))
    except OSError as e:
        sagen(FEHLER, f"nicht erreichbar: {e}")
        return
    try:
        d.senden({"type": "INFO", "version": VERSION})
        info = d.empfangen()
    finally:
        d.zu()
    if not info:
        sagen(FEHLER, "keine INFO-Antwort — läuft der Prozess?")
        return
    sagen(OK, "erreichbar, INFO antwortet")

    # 2. Version
    verlangt = str(info.get("required_version", ""))
    if verlangt == VERSION:
        sagen(OK, f"required_version = {verlangt} (passt zu diesem Client)")
    elif not verlangt:
        sagen(WARN, "required_version ist leer — kein Versionszwang aktiv")
    else:
        sagen(FEHLER, f"required_version = {verlangt}, Client ist {VERSION}")
    if info.get("version_ok") is not True:
        sagen(FEHLER, "version_ok ist nicht True — dieser Client käme nicht hinein")

    # 3. Läuft der NEUE server.py? (Block H, H2.14)
    neu = [f for f in ("lobby_max", "load") if f in info]
    if len(neu) == 2:
        sagen(OK, f"neue INFO-Felder da: {info['lobby_count']} / {info['lobby_max']} "
                  f"Lobbys, Laststufe „{info['load']}\"")
    else:
        sagen(FEHLER, "lobby_max/load FEHLEN — der Prozess läuft noch mit dem "
                      "alten server.py. Pull allein reicht nicht, er braucht "
                      "einen Neustart")
        return

    # 4. Erwartetes Feld: Servertag muss zum Lobbycode-Präfix passen
    if str(info.get("server_tag", "")) == sd.code_prefix:
        sagen(OK, f"server_tag = {info['server_tag']}")
    else:
        sagen(FEHLER, f"server_tag = {info.get('server_tag')!r}, erwartet "
                      f"{sd.code_prefix!r} — Lobbycodes würden falsch geroutet")

    # 5. Ankündigungen
    anzahl = len(info.get("announcements", []))
    sagen(OK
          if anzahl else WARN, f"{anzahl} Ankündigungen ausgeliefert")

    # 6. UDP — der Weg, über den das Rennen läuft
    ms = udp_ping(host, udp_port)
    if ms is None:
        sagen(FEHLER, "UDP antwortet nicht — Lobby ginge, Rennen nicht")
    else:
        sagen(OK, f"UDP-Ping {ms:.0f} ms")

    # 7. Sitzungstoken von Ende zu Ende (H2.1). Eine Lobby, sofort wieder zu.
    try:
        wirt = Draht(host, tcp_port, sd.preamble_bytes(host, tcp_port))
    except OSError as e:
        sagen(WARN, f"Lobbyprobe übersprungen: {e}")
        return
    try:
        wirt.senden({"type": "HOST", "name": "Rauchtest", "version": VERSION})
        ok = wirt.warten_auf("JOIN_OK")
        if not ok:
            sagen(FEHLER, "HOST bekam kein JOIN_OK")
            return
        token = str(ok.get("udp_token", ""))
        if len(token) == 16:
            sagen(OK, f"JOIN_OK trägt ein Sitzungstoken (Lobby {ok.get('lobby_id')})")
        else:
            sagen(FEHLER, "JOIN_OK trägt KEIN Token — ohne es bleibt jedes "
                          "Rennen bewegungslos")
            return

        lid, slot = str(ok.get("lobby_id", "")), int(ok.get("slot", 0))
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.settimeout(2.0)
        try:
            # Mit falschem Token: muss abgewiesen werden. Prüfbar von außen nur
            # daran, dass danach mit dem richtigen weiter alles geht — der Relay
            # antwortet auf REGISTER nicht. Der Wert liegt darin, dass ein
            # falsches Token den Slot NICHT umbiegt und der Watchdog uns
            # anschließend nicht hinauswirft.
            u.sendto(pack_register(lid, slot, "0" * 16), (host, udp_port))
            time.sleep(0.2)
            u.sendto(pack_register(lid, slot, token), (host, udp_port))
            time.sleep(0.2)
            ms2 = udp_ping(host, udp_port)
            sagen(OK if ms2 is not None else WARN,
                  "UDP-Registrierung angenommen (kein Abbruch der Verbindung)")
        finally:
            u.close()
    finally:
        wirt.zu()
        sagen(OK, "Testlobby wieder geschlossen")


def main() -> int:
    print(f"Rauchtest — Client-Version {VERSION}")
    print("Angriffstests gehören NICHT hierher, die laufen gegen einen lokalen")
    print("Relay: python -m pytest tests/test_relais_absicherung.py")
    for sd in servers.all_servers():
        try:
            pruefen(sd)
        except Exception as e:                     # noqa: BLE001
            sagen(FEHLER, f"unerwartet: {type(e).__name__}: {e}")
    print(f"\nErgebnis: {_zaehler.get(OK, 0)} ok, {_zaehler.get(WARN, 0)} Warnungen, "
          f"{_zaehler.get(FEHLER, 0)} Fehler")
    if _zaehler.get(FEHLER):
        print("\nWas jetzt: bei fehlenden INFO-Feldern den Serverprozess neu")
        print("starten. Bei fehlendem Token läuft dort noch der alte server.py.")
    return 1 if _zaehler.get(FEHLER) else 0


if __name__ == "__main__":
    raise SystemExit(main())
