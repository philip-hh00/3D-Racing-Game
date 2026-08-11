"""Relay server catalogue: blob round-trip, override order, code routing.

Covers online_server_select_plan.md §2 and §6 — the pieces that decide *which*
server a player ends up on. A mistake here sends someone to the wrong relay and
looks like "lobby not found" with no way to tell why.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from src.net import servers  # noqa: E402

_ENTRIES = [
    {"id": "helsinki", "code_prefix": "H", "label": "Helsinki",
     "tcp_host": "1.2.3.4", "tcp_port": 7778,
     "udp_host": "1.2.3.4", "udp_port": 7777},
    {"id": "hamburg", "code_prefix": "D", "label": "Hamburg",
     "tcp_host": "tunnel.example", "tcp_port": 37354,
     "udp_host": "tunnel.example", "udp_port": 37354,
     "tcp_preamble": "minecraft",
     "srv_record": "_minecraft._tcp.example"},
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Run every test against a scratch cwd and a clean environment."""
    for var in ("RACE_SERVER_HOST", "RACE_SERVER_PORT", "RACE_SERVER_UDP_PORT",
                "RACE_SERVER_TAG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    # bundle_dir() points at the repo, which ships a real servers.dat — hide it
    # so the tests see only what they write themselves.
    monkeypatch.setattr(servers.paths, "bundle_dir", lambda: tmp_path / "_nowhere")
    servers.reload()
    yield
    servers.reload()


def _write_dat(tmp_path, entries):
    p = tmp_path / "data" / "settings"
    p.mkdir(parents=True, exist_ok=True)
    (p / "servers.dat").write_text(servers.encode(entries), "utf-8")


def _write_json(tmp_path, entries):
    p = tmp_path / "data" / "settings"
    p.mkdir(parents=True, exist_ok=True)
    (p / "servers.json").write_text(json.dumps(entries), "utf-8")


# ── Blob format ───────────────────────────────────────────────────────────────

def test_encode_decode_round_trip():
    assert servers.decode(servers.encode(_ENTRIES)) == _ENTRIES


def test_blob_is_not_plaintext():
    blob = servers.encode(_ENTRIES)
    assert "tunnel.example" not in blob
    assert "helsinki" not in blob


# ── Load order ────────────────────────────────────────────────────────────────

def test_loads_from_dat(tmp_path):
    _write_dat(tmp_path, _ENTRIES)
    loaded = servers.reload()
    assert [s.id for s in loaded] == ["helsinki", "hamburg"]
    assert loaded[1].tcp_preamble == "minecraft"
    assert loaded[1].srv_record == "_minecraft._tcp.example"


def test_plain_json_beats_dat(tmp_path):
    _write_dat(tmp_path, _ENTRIES)
    _write_json(tmp_path, [dict(_ENTRIES[0], id="devbox", tcp_host="127.0.0.1")])
    loaded = servers.reload()
    assert [s.id for s in loaded] == ["devbox"]
    assert loaded[0].tcp_host == "127.0.0.1"


def test_env_override_beats_everything(tmp_path, monkeypatch):
    _write_dat(tmp_path, _ENTRIES)
    _write_json(tmp_path, _ENTRIES)
    monkeypatch.setenv("RACE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("RACE_SERVER_PORT", "9999")
    loaded = servers.reload()
    assert len(loaded) == 1
    assert (loaded[0].tcp_host, loaded[0].tcp_port) == ("127.0.0.1", 9999)
    # UDP falls back to the TCP port when not given separately.
    assert loaded[0].udp_port == 9999


def test_corrupt_dat_falls_back(tmp_path):
    p = tmp_path / "data" / "settings"
    p.mkdir(parents=True, exist_ok=True)
    (p / "servers.dat").write_text("not-a-valid-blob!!", "utf-8")
    loaded = servers.reload()
    assert [s.id for s in loaded] == ["helsinki"]      # hardcoded fallback


def test_broken_entry_is_skipped_rest_survives(tmp_path):
    _write_dat(tmp_path, [{"id": "bad"}, _ENTRIES[1]])
    loaded = servers.reload()
    assert [s.id for s in loaded] == ["hamburg"]


def test_duplicate_prefix_first_wins(tmp_path):
    dupe = dict(_ENTRIES[1], id="other", code_prefix="H")
    _write_dat(tmp_path, [_ENTRIES[0], dupe])
    assert [s.id for s in servers.reload()] == ["helsinki"]


# ── Code routing ──────────────────────────────────────────────────────────────

def test_for_code_routes_by_first_character(tmp_path):
    _write_dat(tmp_path, _ENTRIES)
    servers.reload()
    assert servers.for_code("HAB12C").id == "helsinki"
    assert servers.for_code("D9XYZ1").id == "hamburg"


def test_for_code_is_case_insensitive(tmp_path):
    _write_dat(tmp_path, _ENTRIES)
    servers.reload()
    assert servers.for_code("d9xyz1").id == "hamburg"


@pytest.mark.parametrize("code", ["", "X12345", "H1234", "H1234567", "12345H"])
def test_for_code_rejects_unknown_and_malformed(tmp_path, code):
    _write_dat(tmp_path, _ENTRIES)
    servers.reload()
    assert servers.for_code(code) is None


# ── Entwicklungsserver (06.08.2026) ───────────────────────────────────────────
#
# Zweite Serverinstanz auf demselben Rechner, damit neue Modi und Fehlersuche
# den Live-Server nicht anfassen. Beide Seiten muessen sich ueber **ein** Zeichen
# einig sein: das erste jedes Lobbycodes. Der Server setzt es beim Erzeugen, der
# Client liest daran ab, wohin ein eingetippter Code gehoert.

def test_dev_server_uebernimmt_das_kennzeichen_aus_der_umgebung(tmp_path, monkeypatch):
    """Ohne das war der Client fest auf „H" — ein Dev-Server mit „T" haette
    Codes erzeugt, die derselbe Client als unbekannt abweist."""
    monkeypatch.setenv("RACE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("RACE_SERVER_TAG", servers.DEV_TAG)
    loaded = servers.reload()
    assert [s.code_prefix for s in loaded] == [servers.DEV_TAG]
    assert servers.for_code(servers.DEV_TAG + "AB12C").id == "dev"


def test_ohne_kennzeichen_bleibt_es_bei_H(tmp_path, monkeypatch):
    """Der Vorgabewert des Servers ist „H". Wer bisher nur den Host gesetzt hat,
    darf von der Erweiterung nichts merken."""
    monkeypatch.setenv("RACE_SERVER_HOST", "127.0.0.1")
    assert servers.reload()[0].code_prefix == "H"


def test_das_kennzeichen_wird_gross_geschrieben_und_gekuerzt(tmp_path, monkeypatch):
    """Lobbycodes werden in Großbuchstaben verglichen; ein kleines „t" in der
    Umgebung darf deshalb nicht ins Leere laufen."""
    monkeypatch.setenv("RACE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("RACE_SERVER_TAG", "test")
    assert servers.reload()[0].code_prefix == "T"


def test_ein_leeres_kennzeichen_faellt_auf_H_zurueck(tmp_path, monkeypatch):
    """Sonst entstuende ein Server ohne Prefix, und ``for_code`` fände nie etwas."""
    monkeypatch.setenv("RACE_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("RACE_SERVER_TAG", "")
    assert servers.reload()[0].code_prefix == "H"


def test_der_dev_server_steht_nicht_im_ausgelieferten_katalog():
    """Die eigentliche Sicherung: ein Spieler darf nie in der Baustelle landen.

    Gelesen wird die **echte** ``servers.dat``, nicht die der Testumgebung —
    genau die Datei, die im Build steckt.
    """
    from pathlib import Path
    dat = Path(_ROOT) / "data" / "settings" / "servers.dat"
    assert dat.is_file(), "ohne Katalog prüft dieser Test nichts"
    eintraege = servers.decode(dat.read_text("utf-8"))
    kennzeichen = [str(e.get("code_prefix", "")).upper()[:1] for e in eintraege]
    assert servers.DEV_TAG not in kennzeichen, \
        f"der Entwicklungsserver ist mit ausgeliefert worden: {eintraege}"
    assert len(kennzeichen) == len(set(kennzeichen)), \
        f"zwei Server teilen sich ein Kennzeichen, einer davon wird nie erreicht: {kennzeichen}"


def test_server_und_client_meinen_dasselbe_zeichen():
    """``RESERVED_TAGS`` im Server hält die Kennzeichen aus den Füllstellen der
    Lobbycodes heraus. Fehlt der Dev-Buchstabe dort, streuen die Live-Server ihn
    in ihre Codes, und ein Code ist nicht mehr auf den ersten Blick zuzuordnen.
    """
    import re
    from pathlib import Path
    quelle = (Path(_ROOT) / "server" / "server.py").read_text("utf-8")
    treffer = re.search(r'^RESERVED_TAGS\s*=\s*"([^"]*)"', quelle, re.M)
    assert treffer, "RESERVED_TAGS nicht gefunden"
    assert servers.DEV_TAG in treffer.group(1)


# ── Preamble wiring ───────────────────────────────────────────────────────────

def test_preamble_only_for_tunnelled_servers(tmp_path):
    _write_dat(tmp_path, _ENTRIES)
    hel, ham = servers.reload()
    assert hel.preamble_bytes() == b""
    pre = ham.preamble_bytes()
    assert pre and pre[0] != 0x00        # never collides with our length prefix
