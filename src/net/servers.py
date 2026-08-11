"""Catalogue of relay servers the online multiplayer can connect to.

Each entry carries a *separate* TCP and UDP endpoint because the Hamburg home
server is exposed through two independent playit.gg tunnels that map to
different local ports. It also carries the single-character ``code_prefix`` that
every lobby code created on that server starts with — that prefix is what routes
a joining player to the right server without asking them to pick one.

The shipped list lives in ``data/settings/servers.dat`` as an obfuscated blob
(``tools/pack_servers.py`` writes it).

    This is obfuscation, NOT encryption. The key sits in this file, so anyone
    who unpacks the build can read the addresses. It keeps casual snoopers out
    of a plaintext config and nothing more — the home server's protection has
    to be server-side.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from src.core import paths
from src.net import mc_preamble

_OBF_KEY = b"rennspiel-2d-relay-catalogue-v1"

_DAT_REL  = ("data", "settings", "servers.dat")
_JSON_REL = ("data", "settings", "servers.json")

#: Kennzeichen des Entwicklungsservers. Bewusst **nicht** im ausgelieferten
#: Katalog: ein Spieler, der einen „T"-Code eingetippt bekommt, liest „Unbekannter
#: Lobby-Code" statt in einer Baustelle zu landen. Erreichbar ist der Server nur
#: über ``RACE_SERVER_HOST`` (siehe Documentation/DEV_SERVER.md).
#:
#: „H" ist Helsinki, „D" ist Hamburg — beide vergeben, deshalb ein drittes
#: Zeichen. In ``server.py`` steht es zusätzlich in ``RESERVED_TAGS``, damit die
#: Live-Server es nicht als Füllzeichen in ihre Codes streuen.
DEV_TAG = "T"


@dataclass(frozen=True)
class ServerDef:
    """One relay endpoint."""
    id:           str
    code_prefix:  str          # "H" | "D" — first character of every lobby code
    label:        str          # display name, run through tr()
    tcp_host:     str
    tcp_port:     int
    udp_host:     str
    udp_port:     int
    tcp_preamble: str = ""     # "" | "minecraft"
    srv_record:   str = ""     # SRV name to re-resolve the TCP port from

    def preamble_bytes(self, host: str | None = None, port: int | None = None) -> bytes:
        """Bytes to send before the first frame, or b"" when not tunnelled."""
        if self.tcp_preamble != "minecraft":
            return b""
        return mc_preamble.build(host or self.tcp_host, port or self.tcp_port)


# Last-resort list if neither the .dat nor a dev override can be read. Helsinki
# only: it is the server every shipped build already knows.
_FALLBACK = [
    ServerDef(
        id="helsinki", code_prefix="H", label="Helsinki",
        tcp_host="62.238.50.156", tcp_port=7778,
        udp_host="62.238.50.156", udp_port=7777,
    ),
]

_cache: list[ServerDef] | None = None


# ── Obfuscation ───────────────────────────────────────────────────────────────

def _xor(data: bytes, key: bytes = _OBF_KEY) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def encode(entries: list[dict]) -> str:
    """Serialize a server list into the blob format stored in servers.dat."""
    raw = json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(_xor(raw)).decode("ascii")


def decode(blob: str) -> list[dict]:
    """Inverse of :func:`encode`. Raises on malformed input."""
    raw = _xor(base64.b64decode(blob.strip().encode("ascii")))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("server catalogue must be a list")
    return data


# ── Loading ───────────────────────────────────────────────────────────────────

def _from_dict(d: dict) -> ServerDef:
    tcp_host = str(d["tcp_host"])
    tcp_port = int(d["tcp_port"])
    prefix   = str(d["code_prefix"]).upper()[:1]
    if not prefix:
        raise ValueError("code_prefix must be one character")
    return ServerDef(
        id=str(d["id"]),
        code_prefix=prefix,
        label=str(d.get("label") or d["id"]),
        tcp_host=tcp_host,
        tcp_port=tcp_port,
        udp_host=str(d.get("udp_host") or tcp_host),
        udp_port=int(d.get("udp_port") or tcp_port),
        tcp_preamble=str(d.get("tcp_preamble", "")),
        srv_record=str(d.get("srv_record", "")),
    )


def _parse_list(entries: list) -> list[ServerDef]:
    out: list[ServerDef] = []
    seen: set[str] = set()
    for e in entries:
        try:
            sd = _from_dict(e)
        except Exception:
            continue                       # skip the broken entry, keep the rest
        if sd.code_prefix in seen:
            continue                       # first definition of a prefix wins
        seen.add(sd.code_prefix)
        out.append(sd)
    return out


def _candidate_files(rel: tuple[str, ...]) -> list[Path]:
    return [Path.cwd().joinpath(*rel), paths.bundle_dir().joinpath(*rel)]


def _load_dev_override() -> list[ServerDef] | None:
    """Aus der Umgebung gesetzter Entwicklungsserver, oder None.

    ``RACE_SERVER_TAG`` muss zum ``RACE_SERVER_TAG`` **des Servers** passen, denn
    beide Seiten meinen dieselbe Sache: das erste Zeichen jedes Lobbycodes. Der
    Server setzt es beim Erzeugen, der Client liest daran ab, wohin ein
    eingetippter Code gehört. Stimmen sie nicht überein, legt der Dev-Server
    Codes mit „D" an und der Client antwortet „Unbekannter Lobby-Code" — der
    Fehler sieht dann nach einem Netzproblem aus und ist keines.

    Vorgabe bleibt „H", also der Vorgabewert des Servers: wer bisher nur
    ``RACE_SERVER_HOST`` gesetzt hat, merkt von dieser Erweiterung nichts.
    """
    host = os.environ.get("RACE_SERVER_HOST")
    if not host:
        return None
    port = int(os.environ.get("RACE_SERVER_PORT") or 7777)
    udp  = int(os.environ.get("RACE_SERVER_UDP_PORT") or port)
    tag  = (os.environ.get("RACE_SERVER_TAG", "H").upper() + "H")[0]
    return [ServerDef(
        id="dev", code_prefix=tag, label="Dev",
        tcp_host=host, tcp_port=port, udp_host=host, udp_port=udp,
    )]


def _load_plain_json() -> list[ServerDef] | None:
    for p in _candidate_files(_JSON_REL):
        try:
            if p.is_file():
                parsed = _parse_list(json.loads(p.read_text("utf-8")))
                if parsed:
                    return parsed
        except Exception:
            continue
    return None


def _load_dat() -> list[ServerDef] | None:
    for p in _candidate_files(_DAT_REL):
        try:
            if p.is_file():
                parsed = _parse_list(decode(p.read_text("utf-8")))
                if parsed:
                    return parsed
        except Exception:
            continue
    return None


def reload() -> list[ServerDef]:
    """Re-read the catalogue, honouring the override order. Also clears the cache."""
    global _cache
    _cache = (_load_dev_override() or _load_plain_json()
              or _load_dat() or list(_FALLBACK))
    return _cache


def all_servers() -> list[ServerDef]:
    """The active catalogue (cached after the first call)."""
    return _cache if _cache is not None else reload()


def by_prefix(ch: str) -> ServerDef | None:
    """Server whose lobby codes start with *ch*, or None."""
    if not ch:
        return None
    ch = ch[0].upper()
    return next((s for s in all_servers() if s.code_prefix == ch), None)


def by_id(server_id: str) -> ServerDef | None:
    return next((s for s in all_servers() if s.id == server_id), None)


def for_code(code: str) -> ServerDef | None:
    """Server a lobby code belongs to. None for malformed or unknown codes."""
    code = (code or "").strip().upper()
    if len(code) != 6:
        return None
    return by_prefix(code[0])
