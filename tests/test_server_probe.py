"""Server health probe: quality thresholds, status matrix, endpoint resolution.

The displayed ping is measured over UDP on purpose. Through the playit.gg tunnel
the TCP path costs roughly twice as much (~101 ms vs ~46 ms measured) while the
race itself only ever uses UDP — grading the home server by its TCP figure would
mark it red for latency it never actually imposes.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.net import server_probe  # noqa: E402
from src.net.servers import ServerDef  # noqa: E402

_DIRECT = ServerDef(id="direct", code_prefix="H", label="Direct",
                    tcp_host="1.2.3.4", tcp_port=7778,
                    udp_host="1.2.3.4", udp_port=7777)

_TUNNEL = ServerDef(id="tunnel", code_prefix="D", label="Tunnel",
                    tcp_host="old.example", tcp_port=1111,
                    udp_host="old.example", udp_port=1111,
                    tcp_preamble="minecraft",
                    srv_record="_minecraft._tcp.example")


# ── Quality bars ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ping,bars", [
    (0, 3), (39.9, 3),      # good below 40 ms
    (40, 2), (89.9, 2),     # medium up to 90 ms
    (90, 1), (400, 1),      # poor from 90 ms
    (None, 0),              # unknown
])
def test_quality_bars_thresholds(ping, bars):
    assert server_probe.quality_bars(ping) == bars


def test_offline_status_has_no_bars_even_with_a_ping_value():
    st = server_probe.ServerStatus(server=_DIRECT, state=server_probe.OFFLINE, ping_ms=10)
    assert st.bars == 0
    assert not st.selectable


def test_online_status_is_selectable():
    st = server_probe.ServerStatus(server=_DIRECT, state=server_probe.ONLINE, ping_ms=10)
    assert st.bars == 3
    assert st.selectable


# ── Endpoint resolution ───────────────────────────────────────────────────────

def test_endpoint_without_srv_uses_the_configured_values():
    assert server_probe.resolve_endpoint(_DIRECT) == ("1.2.3.4", 7778, 7777)


def test_srv_result_overrides_host_and_both_ports(monkeypatch):
    """playit reassigns the port on agent restart and both tunnels share it."""
    monkeypatch.setattr(server_probe.srv_lookup, "resolve_srv",
                        lambda name, **kw: ("new.ply.gg", 42424))
    assert server_probe.resolve_endpoint(_TUNNEL) == ("new.ply.gg", 42424, 42424)


def test_srv_failure_falls_back_to_the_configured_values(monkeypatch):
    monkeypatch.setattr(server_probe.srv_lookup, "resolve_srv", lambda name, **kw: None)
    assert server_probe.resolve_endpoint(_TUNNEL) == ("old.example", 1111, 1111)


# ── Status matrix ─────────────────────────────────────────────────────────────

def _patch(monkeypatch, *, info, ping):
    monkeypatch.setattr(server_probe, "probe_tcp", lambda *a, **kw: info)
    monkeypatch.setattr(server_probe, "probe_udp", lambda *a, **kw: ping)


def test_unreachable_tcp_is_offline(monkeypatch):
    _patch(monkeypatch, info=None, ping=12.0)
    st = server_probe.probe_once(_DIRECT)
    assert st.state == server_probe.OFFLINE
    assert st.ping_ms is None


def test_version_mismatch_is_outdated(monkeypatch):
    _patch(monkeypatch, info={"version_ok": False, "required_version": "9.9.9",
                              "lobby_count": 3}, ping=12.0)
    st = server_probe.probe_once(_DIRECT)
    assert st.state == server_probe.OUTDATED
    assert st.required_version == "9.9.9"
    assert not st.selectable


def test_dead_udp_counts_as_offline_even_when_tcp_answers(monkeypatch):
    """A lobby you can enter but never race in is worse than a hidden server."""
    _patch(monkeypatch, info={"version_ok": True, "lobby_count": 1}, ping=None)
    assert server_probe.probe_once(_DIRECT).state == server_probe.OFFLINE


def test_healthy_server_reports_udp_ping_and_lobby_count(monkeypatch):
    _patch(monkeypatch, info={"version_ok": True, "lobby_count": 2}, ping=46.0)
    st = server_probe.probe_once(_DIRECT)
    assert st.state == server_probe.ONLINE
    assert st.ping_ms == 46.0
    assert st.lobby_count == 2
    assert st.bars == 2
