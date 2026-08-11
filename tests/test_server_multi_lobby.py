"""Isolation tests for running several lobbies on one relay server.

Runs under pytest *and* standalone (``python tests/test_server_multi_lobby.py``).

These cover ``online_team_tt_plan.md`` §5.8: two groups must be able to play
independently on the same server. Everything that is keyed by lobby — the
registry, the TCP broadcasts, the UDP relay, the result aggregation — is
exercised with two lobbies live at the same time.

The TCP tests drive a real ``asyncio`` server on an ephemeral port. The UDP
tests call ``_UDPRelay.datagram_received`` directly with a recording transport,
which needs no socket and makes the "packet claims a foreign lobby" case easy
to assert.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "server"))

import server as srv  # noqa: E402

_LEN = struct.Struct("!I")


# ---------------------------------------------------------------------------
# TCP helpers
# ---------------------------------------------------------------------------


async def _send(writer, msg: dict) -> None:
    body = json.dumps(msg).encode()
    writer.write(_LEN.pack(len(body)) + body)
    await writer.drain()


async def _recv(reader, timeout: float = 3.0) -> dict | None:
    try:
        raw = await asyncio.wait_for(reader.readexactly(4), timeout=timeout)
        length = _LEN.unpack(raw)[0]
        body = await asyncio.wait_for(reader.readexactly(length), timeout=timeout)
        return json.loads(body)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError):
        return None


async def _recv_until(reader, msg_type: str, tries: int = 8) -> dict | None:
    """Read messages until one of *msg_type* shows up (or we run dry)."""
    for _ in range(tries):
        msg = await _recv(reader)
        if msg is None:
            return None
        if msg.get("type") == msg_type:
            return msg
    return None


async def _drain(reader, seconds: float = 0.25) -> list:
    """Collect everything that arrives within *seconds*."""
    out = []
    try:
        while True:
            msg = await _recv(reader, timeout=seconds)
            if msg is None:
                break
            out.append(msg)
    except Exception:  # noqa: BLE001
        pass
    return out


class _Server:
    """In-process relay on an ephemeral port, with a clean registry."""

    def __init__(self) -> None:
        self.server = None
        self.port = 0
        self._saved_registry = None

    async def __aenter__(self):
        self._saved_registry = srv._registry
        srv._registry = srv._Registry()
        self.server = await asyncio.start_server(srv._handle_tcp, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
        srv._registry = self._saved_registry

    async def connect(self):
        return await asyncio.open_connection("127.0.0.1", self.port)


def _client_version() -> str:
    """The server gates HOST/JOIN on live_config.json's required_version, so
    the test client has to claim whatever the running config demands."""
    return str(srv._load_live_config().get("required_version", ""))


async def _host_lobby(srv_ctx, name: str = "Host"):
    reader, writer = await srv_ctx.connect()
    await _send(writer, {"type": "HOST", "name": name, "version": _client_version()})
    ok = await _recv(reader)
    assert ok and ok.get("type") == "JOIN_OK", ok
    return reader, writer, ok["lobby_id"]


async def _join_lobby(srv_ctx, lobby_id: str, name: str = "Gast"):
    reader, writer = await srv_ctx.connect()
    await _send(writer, {"type": "JOIN", "name": name,
                         "lobby_id": lobby_id, "version": _client_version()})
    ok = await _recv(reader)
    return reader, writer, ok


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Registry isolation
# ---------------------------------------------------------------------------


def test_two_hosts_get_distinct_lobbies():
    async def go():
        async with _Server() as s:
            _r1, w1, lid_a = await _host_lobby(s, "A")
            _r2, w2, lid_b = await _host_lobby(s, "B")
            assert lid_a != lid_b
            assert set(srv._registry.lobbies) == {lid_a, lid_b}
            assert len(srv._registry.lobbies[lid_a].clients) == 1
            assert len(srv._registry.lobbies[lid_b].clients) == 1
            w1.close(); w2.close()
    _run(go())


def test_lobby_id_collision_is_retried():
    """create() must keep rolling until it finds a free code."""
    async def go():
        async with _Server() as s:  # noqa: F841
            taken = srv._registry.create().lobby_id
            second = srv._registry.create().lobby_id
            assert taken != second
            assert len(srv._registry.lobbies) == 2
    _run(go())


def test_registry_is_empty_after_everyone_leaves():
    async def go():
        async with _Server() as s:
            writers = []
            for _ in range(8):
                _r, w, _lid = await _host_lobby(s)
                writers.append(w)
            assert len(srv._registry.lobbies) == 8
            for w in writers:
                w.close()
            await asyncio.sleep(0.4)
            assert srv._registry.lobbies == {}, srv._registry.lobbies
            assert srv._registry.addr_map == {}
    _run(go())


# ---------------------------------------------------------------------------
# Broadcast isolation
# ---------------------------------------------------------------------------


def test_chat_does_not_leak_into_the_other_lobby():
    async def go():
        async with _Server() as s:
            _ra, wa, lid_a = await _host_lobby(s, "HostA")
            rb, wb, lid_b = await _host_lobby(s, "HostB")
            rg, wg, ok = await _join_lobby(s, lid_a, "GastA")
            assert ok.get("type") == "JOIN_OK"
            await _drain(rb)   # clear anything queued for lobby B

            await _send(wa, {"type": "CHAT", "text": "nur für A"})
            got_a = await _recv_until(rg, "CHAT")
            assert got_a and got_a["text"] == "nur für A"

            leaked = await _drain(rb)
            assert not [m for m in leaked if m.get("type") == "CHAT"], leaked
            wa.close(); wb.close(); wg.close()
    _run(go())


def test_settings_change_stays_inside_its_lobby():
    async def go():
        async with _Server() as s:
            _ra, wa, lid_a = await _host_lobby(s, "HostA")
            _rb, wb, lid_b = await _host_lobby(s, "HostB")
            await _send(wa, {"type": "SET_SETTINGS", "settings": {
                "mode": "Team-Zeitfahren", "roster_size": 6, "laps": 7,
            }})
            await asyncio.sleep(0.2)
            la = srv._registry.lobbies[lid_a]
            lb = srv._registry.lobbies[lid_b]
            assert (la.mode, la.roster_size) == ("Team-Zeitfahren", 6)
            assert (lb.mode, lb.roster_size) == ("Rennen", 4)
            assert lb.settings.get("laps") is None
            wa.close(); wb.close()
    _run(go())


def test_host_leaving_one_lobby_leaves_the_other_untouched():
    async def go():
        async with _Server() as s:
            _ra, wa, lid_a = await _host_lobby(s, "HostA")
            rg, wg, _ok = await _join_lobby(s, lid_a, "GastA")
            _rb, wb, lid_b = await _host_lobby(s, "HostB")

            wa.close()
            await asyncio.sleep(0.4)
            assert lid_b in srv._registry.lobbies
            assert len(srv._registry.lobbies[lid_b].clients) == 1
            wg.close(); wb.close()
    _run(go())


# ---------------------------------------------------------------------------
# Join limit / team gate over the wire
# ---------------------------------------------------------------------------


def test_join_is_refused_once_the_roster_is_full():
    async def go():
        async with _Server() as s:
            _ra, wa, lid = await _host_lobby(s, "Host")
            writers = [wa]
            for i in range(3):                       # fills roster_size 4
                _r, w, ok = await _join_lobby(s, lid, f"G{i}")
                assert ok.get("type") == "JOIN_OK", ok
                writers.append(w)
            _r, w, ok = await _join_lobby(s, lid, "ZuViel")
            assert ok.get("type") == "JOIN_FAIL"
            assert ok.get("code") == "LOBBY_FULL"
            for x in writers + [w]:
                x.close()
    _run(go())


def test_join_is_refused_during_the_start_window():
    """A built-in-track start leaves lobby.state on "lobby" until everyone has
    sent READY. A player slipping in during that window would never get
    MAP_META, never send READY, and all_ready() would never become true — the
    start would hang for everyone."""
    async def go():
        async with _Server() as s:
            ra, wa, lid = await _host_lobby(s, "Host")
            _rg, wg, ok = await _join_lobby(s, lid, "Gast")
            assert ok.get("type") == "JOIN_OK"
            await _drain(ra)
            await _send(wa, {"type": "START_REQUEST", "track_name": "oval",
                             "is_custom": False})
            await asyncio.sleep(0.2)
            lobby = srv._registry.lobbies[lid]
            assert lobby.starting is True
            assert lobby.state == "lobby"      # the trap this test guards

            _r, w, res = await _join_lobby(s, lid, "ZuSpaet")
            assert res.get("type") == "JOIN_FAIL", res
            wa.close(); wg.close(); w.close()
    _run(go())


def test_start_window_closes_once_the_race_begins():
    async def go():
        async with _Server() as s:
            ra, wa, lid = await _host_lobby(s, "Host")
            rg, wg, _ok = await _join_lobby(s, lid, "Gast")
            await _drain(ra)
            await _send(wa, {"type": "START_REQUEST", "track_name": "oval",
                             "is_custom": False})
            await asyncio.sleep(0.2)
            await _send(wg, {"type": "READY"})
            await asyncio.sleep(0.3)
            lobby = srv._registry.lobbies[lid]
            assert lobby.state == "racing"
            assert lobby.starting is False
            wa.close(); wg.close()
    _run(go())


def test_a_rejected_start_reopens_the_lobby():
    """TEAM_UNBALANCED must not leave the lobby stuck in the start window."""
    async def go():
        async with _Server() as s:
            ra, wa, lid = await _host_lobby(s, "Host")
            await _send(wa, {"type": "SET_SETTINGS", "settings": {
                "mode": "Team-Zeitfahren", "roster_size": 4,
                "ai_roster": [{"name": "KI1", "team": "A"}],
            }})
            await asyncio.sleep(0.15)
            lobby = srv._registry.lobbies[lid]
            lobby.settings["ai_roster"] = [{"name": "KI1", "team": "A"},
                                           {"name": "KI2", "team": "A"},
                                           {"name": "KI3", "team": "A"}]
            lobby.clients[0].team = "A"
            await _drain(ra)
            await _send(wa, {"type": "START_REQUEST", "track_name": "oval",
                             "is_custom": False})
            err = await _recv_until(ra, "ERROR")
            assert err and err.get("code") == "TEAM_UNBALANCED", err
            assert lobby.starting is False
            wa.close()
    _run(go())


def test_roster_cannot_shrink_below_the_player_count():
    async def go():
        async with _Server() as s:
            ra, wa, lid = await _host_lobby(s, "Host")
            await _send(wa, {"type": "SET_SETTINGS",
                             "settings": {"mode": "Team-Zeitfahren", "roster_size": 6}})
            await asyncio.sleep(0.15)
            writers = [wa]
            for i in range(4):                       # 5 players total
                _r, w, ok = await _join_lobby(s, lid, f"G{i}")
                assert ok.get("type") == "JOIN_OK", ok
                writers.append(w)
            await _drain(ra)
            await _send(wa, {"type": "SET_SETTINGS",
                             "settings": {"mode": "Team-Zeitfahren", "roster_size": 4}})
            err = await _recv_until(ra, "ERROR")
            assert err and err.get("code") == "ROSTER_TOO_SMALL", err
            assert srv._registry.lobbies[lid].roster_size == 6
            for x in writers:
                x.close()
    _run(go())


def test_unbalanced_teams_block_the_start():
    async def go():
        async with _Server() as s:
            ra, wa, lid = await _host_lobby(s, "Host")
            await _send(wa, {"type": "SET_SETTINGS", "settings": {
                "mode": "Team-Zeitfahren", "roster_size": 4,
                "ai_roster": [{"name": "KI1", "team": "A"},
                              {"name": "KI2", "team": "A"}],
            }})
            await asyncio.sleep(0.15)
            lobby = srv._registry.lobbies[lid]
            # Force a split the AI cannot repair: host alone, both bots on A.
            lobby.settings["ai_roster"] = [{"name": "KI1", "team": "A"},
                                           {"name": "KI2", "team": "A"}]
            lobby.clients[0].team = "A"
            await _drain(ra)
            await _send(wa, {"type": "START_REQUEST", "track_name": "oval",
                             "is_custom": False})
            err = await _recv_until(ra, "ERROR")
            assert err and err.get("code") == "TEAM_UNBALANCED", err
            assert lobby.state == "lobby"
            wa.close()
    _run(go())


def test_set_team_is_scoped_to_the_sender_and_lobby():
    async def go():
        async with _Server() as s:
            _ra, wa, lid_a = await _host_lobby(s, "HostA")
            rg, wg, _ok = await _join_lobby(s, lid_a, "GastA")
            _rb, wb, lid_b = await _host_lobby(s, "HostB")

            await _send(wg, {"type": "SET_TEAM", "team": "B"})
            await asyncio.sleep(0.2)
            la = srv._registry.lobbies[lid_a]
            lb = srv._registry.lobbies[lid_b]
            guest_slot = next(sl for sl in la.clients if sl != 0)
            assert la.clients[guest_slot].team == "B"
            assert la.clients[0].team == "A"          # host untouched
            assert all(c.team == "A" for c in lb.clients.values())
            wa.close(); wg.close(); wb.close()
    _run(go())


# ---------------------------------------------------------------------------
# UDP relay isolation
# ---------------------------------------------------------------------------


class _RecordingTransport:
    def __init__(self) -> None:
        self.sent: list = []

    def sendto(self, data, addr):
        self.sent.append((data, addr))


def _state_packet(lobby_id: str, sender_slot: int) -> bytes:
    return srv._S_HDR.pack(srv.UDP_STATE,
                           lobby_id.encode()[:6].ljust(6, b"\x00"),
                           sender_slot, 0)


def _register_packet(lobby_id: str, slot: int, token: str = "") -> bytes:
    """Wie der Client registriert — samt Sitzungstoken (Block H, H2.1 Stufe 2).

    Ohne Token weist der Server die Registrierung ab; genau das prüft
    ``tests/test_relais_absicherung.py``. Hier soll der Aufbau *gelingen*, also
    trägt das Paket eins.
    """
    return (srv._S_ID.pack(srv.UDP_REGISTER,
                           lobby_id.encode()[:6].ljust(6, b"\x00"), slot)
            + token.encode()[:srv._TOKEN_B].ljust(srv._TOKEN_B, b"\x00"))


def _udp_fixture():
    """Two lobbies, two registered UDP peers each, on a fresh registry."""
    srv._registry = srv._Registry()
    relay = _UDPRelayUnderTest()
    lobbies = {}
    port = 40000
    for name in ("A", "B"):
        lobby = srv._registry.create()
        for slot in (0, 1):
            token = f"tok{name}{slot}"
            conn = srv.ClientConn(slot=slot, name=f"{name}{slot}",
                                  reader=None, writer=None,
                                  tcp_ip="127.0.0.1", token=token)
            lobby.clients[slot] = conn
            addr = ("127.0.0.1", port)
            port += 1
            relay.datagram_received(
                _register_packet(lobby.lobby_id, slot, token), addr)
        lobbies[name] = lobby
    return relay, lobbies


class _UDPRelayUnderTest(srv._UDPRelay):
    def __init__(self) -> None:
        super().__init__()
        self.transport = _RecordingTransport()


def test_udp_state_reaches_only_the_senders_own_lobby():
    relay, lobbies = _udp_fixture()
    a, b = lobbies["A"], lobbies["B"]
    sender_addr = a.clients[0].udp_addr
    relay.transport.sent.clear()
    relay.datagram_received(_state_packet(a.lobby_id, 0), sender_addr)

    targets = {addr for _data, addr in relay.transport.sent}
    assert targets == {a.clients[1].udp_addr}
    assert b.clients[0].udp_addr not in targets
    assert b.clients[1].udp_addr not in targets


def test_udp_state_claiming_a_foreign_lobby_is_dropped():
    """Hardening: the lobby is taken from the sender's registration, not from
    the packet, so a client cannot relay into someone else's race."""
    relay, lobbies = _udp_fixture()
    a, b = lobbies["A"], lobbies["B"]
    sender_addr = a.clients[0].udp_addr
    relay.transport.sent.clear()
    relay.datagram_received(_state_packet(b.lobby_id, 0), sender_addr)
    assert relay.transport.sent == []


def test_udp_state_from_an_unregistered_address_is_dropped():
    relay, lobbies = _udp_fixture()
    a = lobbies["A"]
    relay.transport.sent.clear()
    relay.datagram_received(_state_packet(a.lobby_id, 0), ("127.0.0.1", 59999))
    assert relay.transport.sent == []


def test_same_host_different_ports_stay_in_their_own_lobbies():
    """Two players behind one NAT: the addr_map key is (ip, port), so their
    lobbies must not bleed into each other."""
    relay, lobbies = _udp_fixture()
    a, b = lobbies["A"], lobbies["B"]
    assert a.clients[0].udp_addr[0] == b.clients[0].udp_addr[0]
    assert a.clients[0].udp_addr[1] != b.clients[0].udp_addr[1]

    relay.transport.sent.clear()
    relay.datagram_received(_state_packet(b.lobby_id, 0), b.clients[0].udp_addr)
    targets = {addr for _data, addr in relay.transport.sent}
    assert targets == {b.clients[1].udp_addr}


# ---------------------------------------------------------------------------
# Result aggregation isolation
# ---------------------------------------------------------------------------


def test_results_are_aggregated_per_lobby():
    async def go():
        srv._registry = srv._Registry()
        a = srv._registry.create()
        b = srv._registry.create()
        for lobby, tag in ((a, "A"), (b, "B")):
            lobby.state = "racing"
            for slot in (0, 1):
                lobby.clients[slot] = srv.ClientConn(
                    slot=slot, name=f"{tag}{slot}", reader=None, writer=None)
            lobby.results_rows = [{"name": f"{tag}{slot}", "finish_time": 10.0 + slot,
                                   "team": "A" if slot == 0 else "B"}
                                  for slot in (0, 1)]
            lobby.reported = {0, 1}
        sent: list = []

        async def fake_broadcast(lobby, msg, exclude=-1):
            sent.append((lobby.lobby_id, msg))

        original = srv._broadcast
        srv._broadcast = fake_broadcast
        try:
            await srv._finalize_results(a)
        finally:
            srv._broadcast = original

        assert len(sent) == 1
        lid, msg = sent[0]
        assert lid == a.lobby_id
        assert msg["type"] == "RACE_RESULTS"
        assert {r["name"] for r in msg["rows"]} == {"A0", "A1"}
        assert [r["team"] for r in msg["rows"]] == ["A", "B"]
        assert b.results_rows and b.state == "racing"   # lobby B untouched
    _run(go())


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def _run_all() -> int:
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    total = len(funcs)
    print(f"\n{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
