"""
Relay server for 3D-Racing-Game — Online Multiplayer.

Handles:
  TCP  — Lobby management, JSON messages (length-prefixed), map transfer
  UDP  — Real-time position broadcast (binary struct), ping/pong

Ports come from the environment so one binary serves both deployments:
  RACE_TCP_PORTS  default "7777,7778"   Helsinki keeps 7777 for old clients
  RACE_UDP_PORT   default 7777
  RACE_SERVER_TAG default "H"           first character of every lobby code

Behind a playit.gg "Minecraft Java" tunnel (Hamburg) every TCP connection opens
with a Minecraft handshake packet that the tunnel insists on; it is discarded by
_strip_mc_preamble before the real protocol starts.

Architecture: dumb relay + lobby table. No game physics or AI on server.
Server grants GO (START) after all clients confirm READY.

Requires Python >= 3.10. No external packages needed.
Run:
    python server.py
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import string
import struct
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Set

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

HOST       = "0.0.0.0"
PORT       = 7777
# TCP and UDP ports are configured separately because the Hamburg home server is
# published through two independent playit.gg tunnels that map to different
# local ports (TCP → 7778, UDP → 7777). Helsinki listens on 7777 *and* 7778 for
# TCP so already-shipped 0.4.0-beta clients, which only know 7777, still reach
# the version check instead of getting "connection refused".
TCP_PORTS  = [int(p) for p in os.environ.get("RACE_TCP_PORTS", "7777,7778").split(",") if p.strip()]
UDP_PORT   = int(os.environ.get("RACE_UDP_PORT", str(PORT)))
# First character of every lobby code created here — routes a joining client to
# the right server without asking the player which one the host used.
SERVER_TAG = (os.environ.get("RACE_SERVER_TAG", "H").upper() + "H")[0]
# Taken by some server, so never used as a random filler character.
# H = Helsinki, D = Hamburg (live), T = Entwicklungsinstanz (siehe
# Documentation/DEV_SERVER.md). T steht hier, obwohl kein ausgelieferter Client
# ihn kennt: sonst streuen die Live-Server das Zeichen in ihre Codes, und ein
# Blick auf einen Code sagt nicht mehr eindeutig, wohin er gehoert.
RESERVED_TAGS = "HDT"
MAX_SLOTS  = 6
MAX_MAP_B  = 1024 * 1024   # 1 MB hard cap for custom maps
UDP_TIMEOUT = 15.0          # seconds without UDP packet → disconnect in race
VALID_MODES  = ("Rennen", "Team-Zeitfahren", "Grand Prix")
# Team-Zeitfahren braucht gerade Zahlen (zwei gleich grosse Teams), die
# uebrigen Modi nicht. Geprueft wird die Teamteilung weiter unten.
VALID_ROSTER = (2, 3, 4, 5, 6)

_LIVE_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "live_config.json")

# ── Grenzen und Auslastung (Block H, H2.3 / H2.7 / H2.14) ──────────────────────
#
# Alle Grenzen kommen aus der Umgebung, damit Helsinki (VPS) und Hamburg
# (Heimserver, 5,7 GB RAM) verschieden eingestellt werden koennen, ohne den Code
# anzufassen. Die Vorgaben sind fuer den kleineren der beiden gewaehlt.
MAX_LOBBIES        = int(os.environ.get("RACE_MAX_LOBBIES", "50"))
MAX_CONN_TOTAL     = int(os.environ.get("RACE_MAX_CONN_TOTAL", "200"))
MAX_CONN_PER_IP    = int(os.environ.get("RACE_MAX_CONN_PER_IP", "12"))
MAX_LOBBIES_PER_IP = int(os.environ.get("RACE_MAX_LOBBIES_PER_IP", "3"))
#: TCP-Nachrichten je Sekunde und IP, im Mittel. Kurze Spitzen deckt der Vorrat
#: (``MSG_VORRAT``) ab — beim Lobbybeitritt kommen mehrere Nachrichten auf
#: einmal, und das ist normaler Betrieb.
MAX_MSG_PER_S      = float(os.environ.get("RACE_MAX_MSG_PER_S", "40"))
MSG_VORRAT         = float(os.environ.get("RACE_MSG_BURST", "120"))
#: So viele verworfene Nachrichten in einer Verbindung, dann wird sie getrennt.
#: Verwerfen allein reicht gegen eine Dauerflut nicht — sie kostet weiter Zeit.
FLUT_ABBRUCH       = int(os.environ.get("RACE_FLOOD_ABORT", "300"))
#: UDP-Pakete je Sekunde und Slot (H2.7). Das Spiel sendet ~30/s; 120 laesst
#: reichlich Luft und schneidet die Verstaerkung x5 trotzdem ab.
MAX_UDP_PER_S      = int(os.environ.get("RACE_MAX_UDP_PER_S", "120"))
#: Obergrenze fuer ``lobby.settings`` als JSON, in Bytes (H2.4).
MAX_SETTINGS_B     = int(os.environ.get("RACE_MAX_SETTINGS_B", "65536"))

#: Adressen, hinter denen **mehrere** Spieler stecken koennen und die deshalb
#: nicht je IP begrenzt werden.
#:
#: Hamburg haengt hinter zwei playit.gg-Tunneln. Deren Agent laeuft auf dem
#: Heimserver selbst und verbindet sich nach 127.0.0.1 — **alle** Spieler kommen
#: dort mit derselben Quelladresse an. Eine Grenze je IP wuerde den Server damit
#: auf ``MAX_CONN_PER_IP`` Spieler insgesamt deckeln, also sich selbst abwuergen.
#: Fuer solche Adressen gelten nur die Gesamtgrenzen und die Aufnahmesperre
#: (H2.14) — genau die zweite Schicht, fuer die H2.14 gedacht ist.
#:
#: Helsinki ist direkt erreichbar und sieht echte Spieleradressen; dort greifen
#: die Grenzen je IP vollstaendig.
TRUSTED_PROXIES = frozenset(
    p.strip() for p in os.environ.get("RACE_TRUSTED_PROXIES", "127.0.0.1,::1").split(",")
    if p.strip()
)

#: Ab welchem Anteil der Lobbygrenze welche Laststufe gilt (H2.14).
LAST_GUT_AB  = float(os.environ.get("RACE_LOAD_BUSY_AT", "0.5"))
LAST_VOLL_AB = float(os.environ.get("RACE_LOAD_FULL_AT", "0.85"))

LAST_FREI = "frei"
LAST_GUT  = "gut besucht"
LAST_VOLL = "ausgelastet"


#: Schluessel, die der Host in ``lobby.settings`` legen darf (H2.4).
#:
#: Vorher nahm ``lobby.settings.update(payload)`` **beliebige** Schluessel
#: unbegrenzt an und verteilte jeden davon in jedem ``LOBBY_STATE`` an alle. Der
#: Angreifer ist hier der legitime Host seiner eigenen Lobby, also bremst eine
#: Anfragerate das Wachstum nur, sie begrenzt es nicht.
#:
#: Die Liste ist zugleich die einzige Stelle, an der steht, was in ``settings``
#: ueberhaupt liegen darf — vorher wusste das niemand. Kommt clientseitig ein
#: Feld dazu, muss es hier eingetragen werden; bis dahin faellt es weg, ohne
#: etwas zu brechen (der Relay bleibt der dumme Relay).
SETTINGS_KEYS = frozenset({
    "mode", "roster_size", "vehicle_class", "track_path", "track_name",
    "laps", "ai_difficulty", "ai_roster", "gp_races", "offers_enabled",
    # Tageszeit des Rennens (1.1.0): der Host legt sie fest. Fehlt das Feld, gilt
    # Tag; ein Host mit älterem Spiel schickt es gar nicht.
    "tageszeit",
    # Wetter des Rennens (1.1.0): ebenso, fehlt es, gilt Trocken.
    "wetter",
    # Grand Prix: Serienzustand reist im selben Block mit (§3 D/G-Entwurf).
    "gp_tracks", "gp_track_key", "gp_active", "gp_phase", "gp_finished",
    "gp_locked", "gp_members", "gp_race", "gp_total", "gp_points", "gp_raced",
    "gp_standings",
    # Der Server selbst legt es an (PICK), nicht der Host — steht hier, damit
    # ein Aufraeumen es nicht wegwirft.
    "picks",
})

#: Gültige Werte für ``settings["tageszeit"]``; alles andere wird zu "Tag".
TAGESZEITEN = frozenset({"Tag", "Abend", "Nacht"})

#: Gültige Werte für ``settings["wetter"]``; alles andere wird zu "Trocken".
WETTER = frozenset({"Trocken", "Regen"})

#: Zeichen, die in einem Spielernamen zusaetzlich zu Buchstaben und Ziffern
#: erlaubt sind (H2.13).
NAME_EXTRA = " _-.'"

#: Was der Spieler zu einer Absage zu lesen bekommt. Ein Satz, der sagt, was zu
#: tun ist — „Fehler" allein kann niemand einordnen (H2.14).
_ABSAGE_TEXT = {
    "SERVER_BUSY": ("Server ist gerade ausgelastet — versuch es in ein paar "
                    "Minuten noch einmal oder wähle den anderen Server."),
    "TOO_MANY":    ("Zu viele Verbindungen von deinem Anschluss. Schließe ein "
                    "anderes Spielfenster und versuch es erneut."),
}


def saeubere_name(roh) -> str:
    """Einen Spielernamen auf unbedenkliche Zeichen bringen (H2.13).

    Der Namensfilter des Spiels (``name_blacklist.json``) laeuft nur im Client;
    der Server nahm ``str(msg["name"])[:20]`` ungeprueft und zeigte ihn allen.
    Damit konnte ein veraenderter Client Steuerzeichen, Zeilenumbrueche oder
    Zeichen aus der Rechts-nach-links-Ecke in jede fremde Lobbyliste schreiben.

    Geprueft wird **nicht** gegen eine Wortliste — das bleibt Sache des Clients.
    Hier geht es nur um die Zeichen selbst: Buchstaben und Ziffern in jeder
    Sprache bleiben (``isalnum``, also auch Umlaute und kyrillisch), dazu
    :data:`NAME_EXTRA`. Alles andere fliegt raus.
    """
    text = str(roh)[:40]
    sauber = "".join(z for z in text if z.isalnum() or z in NAME_EXTRA)
    sauber = " ".join(sauber.split())[:20].strip()
    return sauber or "Spieler"


def _settings_groesse(werte: dict) -> int:
    """Wie viele Bytes ``settings`` als JSON belegt (H2.4).

    Gerechnet wird auf dem, was auch verschickt wird — jeder ``LOBBY_STATE``
    traegt den Block an alle. Ein unserialisierbarer Wert gilt als zu gross:
    verschicken liesse er sich ohnehin nicht.
    """
    try:
        return len(json.dumps(werte, ensure_ascii=False).encode())
    except (TypeError, ValueError):
        return MAX_SETTINGS_B + 1


def _load_live_config() -> dict:
    """Read live_config.json fresh on every call so the developer can edit
    required_version / announcements without restarting the server."""
    try:
        with open(_LIVE_CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning(f"live_config.json unreadable: {exc}")
    return {"required_version": "", "announcements": []}

# ── UDP wire types ─────────────────────────────────────────────────────────────
UDP_REGISTER = 0x00   # client registers UDP addr with server
UDP_STATE    = 0x01   # position broadcast
UDP_PING     = 0x02
UDP_PONG     = 0x03
UDP_BUMP     = 0x05


# Structs (network byte order = big-endian "!")
# STATE header PREFIX the relay reads: type(B) lobby(6s) sender_slot(B)
# car_count(B). The client header is longer (it appends a send_time double —
# see src/net/protocol.py), but the relay only needs this 9-byte prefix to
# route the packet and forwards the whole datagram opaquely, so it need not
# know about the extra field.
_S_HDR = struct.Struct("!B 6s B B")
# per-vehicle (opaque to the server — it only relays raw bytes, never unpacks
# this): id(B) vtype(B) x(f) y(f) angle(f) vx(f) vy(f) omega(f) → 26 bytes.
# Kept only for documentation; must stay in sync with src/net/protocol.py.
_S_VEH = struct.Struct("!BB ffffff")
# PING/REGISTER share: type(B) lobby(6s) slot(B)
_S_ID  = struct.Struct("!B 6s B")
#: Laenge des Sitzungstokens im REGISTER-Paket, in Bytes (H2.1 Stufe 2). Es haengt
#: **hinter** dem gemeinsamen Kopf, damit PING unveraendert bleibt: 16 Hexzeichen
#: aus ``secrets.token_hex(8)`` = 64 Bit Zufall, mehr als genug fuer etwas, das
#: nur eine Sitzung lang gilt und nur zusammen mit Lobby-ID und Slot etwas nutzt.
_TOKEN_B = 16
# PING has extra ts(d) after the id part
_S_PING = struct.Struct("!B 6s B d")
# PONG reply: type(B) ts(d)
_S_PONG = struct.Struct("!B d")
# TCP length prefix
_LEN   = struct.Struct("!I")

# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class ClientConn:
    slot: int
    name: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    is_host: bool = False
    udp_addr: Optional[Tuple] = None
    last_udp: float = field(default_factory=time.monotonic)
    ready: bool = False          # READY received (transfer done / built-in confirmed)
    lobby_ready: bool = False    # player pressed "Bereit" in the pre-start lobby
    on_results: bool = False     # player is currently sitting on the results screen
    team: str = "A"              # player-chosen team (Team-Zeitfahren)
    #: IP der TCP-Verbindung dieses Slots. ``UDP_REGISTER`` wird nur von dort
    #: angenommen (H2.1 Stufe 1) — vorher genuegte der Paketinhalt, und wer die
    #: Lobby-ID kannte, konnte den Positionsstrom eines fremden Spielers auf sich
    #: umleiten.
    tcp_ip: str = ""
    #: Sitzungstoken aus ``secrets`` (H2.1 Stufe 2). Deckt auch den Fall, dass
    #: zwei Spieler hinter derselben IP sitzen — oder hinter demselben Tunnel,
    #: wo die IP-Pruefung nichts unterscheiden kann.
    token: str = ""
    #: Fenster fuer die UDP-Rate je Slot (H2.7): Beginn und Zaehler.
    udp_fenster: float = field(default_factory=time.monotonic)
    udp_pakete: int = 0

    def udp_erlaubt(self) -> bool:
        """Ob dieser Slot noch senden darf. Ein Sekundenfenster je Slot; wer
        darueber liegt, wird verworfen und nicht weiterverteilt.

        Ohne das faechert der Relay eine Flut auf bis zu fuenf Peers aus — eine
        Verstaerkung um das Fuenffache **innerhalb** der Lobby, und der Absender
        ist eine erlaubte IP (H2.7).
        """
        jetzt = time.monotonic()
        if jetzt - self.udp_fenster >= 1.0:
            self.udp_fenster = jetzt
            self.udp_pakete = 0
        self.udp_pakete += 1
        return self.udp_pakete <= MAX_UDP_PER_S


@dataclass
class Lobby:
    lobby_id: str
    clients: Dict[int, ClientConn] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    map_meta: dict = field(default_factory=dict)
    map_buffer: bytes = b""
    state: str = "lobby"         # lobby | transferring | racing
    #: Datenstand des Hosts (src/core/integritaet.py); Gaeste muessen passen.
    inhalt: str = ""
    # A built-in-track start briefly leaves state on "lobby" while it waits for
    # everyone's READY. Without this flag a player could slip in during that
    # window: they'd never receive MAP_META, never send READY, and all_ready()
    # would never become true — the start would hang for the whole lobby.
    starting: bool = False
    next_slot: int = 0
    host_slot: int = 0
    mode: str = "Rennen"         # "Rennen" | "Team-Zeitfahren"
    roster_size: int = 4         # 4 or 6 — total vehicle count incl. AI
    # Race-result aggregation (filled while state == "racing")
    results_rows: list = field(default_factory=list)   # rows from all peers
    reported: set = field(default_factory=set)         # human slots that reported
    race_start_ts: float = 0.0
    loaded: set = field(default_factory=set)           # slots that finished loading
    paused_by: Optional[int] = None                    # slot of player who paused
    resume_ready: Set[int] = field(default_factory=set) # slots ready to resume
    # DNF grace: the first peer to see a car finish reports the leader's
    # slowest lap; that starts a single server-side timer, and when it expires
    # everyone still driving is forced to finish (DNF). One timer per race.
    first_finish_seen: bool = False
    finish_timer: Optional["asyncio.Task"] = None
    # Streckenvorschlaege: ein Platz je Spieler-Slot, bleibt fuer die Lebensdauer
    # der Lobby liegen, damit auch spaeter Beitretende ihn noch bekommen.
    offers: Dict[int, dict] = field(default_factory=dict)      # slot -> {"name","data","size","from"}
    offer_buf: Dict[int, bytes] = field(default_factory=dict)  # laufende Uebertragung
    offer_meta: Dict[int, dict] = field(default_factory=dict)  # slot -> {"name","size"}
    # Lobbyliste (Plan 1.1.0): Sichtbarkeit, Anzeigename und Passwort. Ohne die
    # Angaben des Hosts (aelteres Spiel) bleibt die Lobby privat, also unlistbar.
    # Das Passwort liegt nur als Salz + Hash vor, nie im Klartext.
    sichtbarkeit: str = "private"    # "public" | "password" | "private"
    lobby_name: str = ""
    pw_salt: bytes = b""
    pw_hash: bytes = b""
    pw_geaendert: float = 0.0        # monotonic; bremst Passwortwechsel

    @property
    def host(self) -> Optional[ClientConn]:
        return self.clients.get(self.host_slot)

    def all_ready(self) -> bool:
        return bool(self.clients) and all(c.ready for c in self.clients.values())

    def reset_ready(self):
        for c in self.clients.values():
            c.ready = False


# ── Team helpers (free functions — testable without sockets) ───────────────────

def ai_slot_count(lobby: Lobby) -> int:
    """How many AI vehicles fill the roster beyond the connected humans."""
    return max(0, lobby.roster_size - len(lobby.clients))


def human_counts(lobby: Lobby) -> Tuple[int, int]:
    """Connected players per team, AI excluded."""
    a = sum(1 for c in lobby.clients.values() if c.team == "A")
    b = sum(1 for c in lobby.clients.values() if c.team == "B")
    return a, b


def team_counts(lobby: Lobby) -> Tuple[int, int]:
    """Count vehicles per team: humans from ClientConn.team, AI from
    settings["ai_roster"] (capped at ai_slot_count so a longer host-sent
    list can't inflate the count). AI entries without a valid team count
    as "A"."""
    a, b = human_counts(lobby)
    ai_roster = lobby.settings.get("ai_roster", [])
    for entry in ai_roster[:ai_slot_count(lobby)]:
        if isinstance(entry, dict) and entry.get("team") == "B":
            b += 1
        else:
            a += 1
    return a, b


def normalize_ai_teams(lobby: Lobby) -> None:
    """Distribute AI vehicles so both teams reach roster_size // 2, based on
    how many humans already sit on each side. Only applies in Team-Zeitfahren.
    If the human split makes an even distribution impossible, leaves the
    existing team values untouched — START_REQUEST will reject the start and
    the host will see why."""
    if lobby.mode != "Team-Zeitfahren":
        return
    ai_count = ai_slot_count(lobby)
    ziel = lobby.roster_size // 2
    human_a, human_b = human_counts(lobby)
    braucht_a = max(0, ziel - human_a)
    braucht_b = max(0, ziel - human_b)
    if braucht_a + braucht_b != ai_count:
        return
    ai_roster = lobby.settings.get("ai_roster", [])
    if len(ai_roster) < ai_count:
        return
    # Preserve host's manual team assignments if they are already balanced
    curr_a = sum(1 for entry in ai_roster[:ai_count] if isinstance(entry, dict) and entry.get("team") == "A")
    curr_b = sum(1 for entry in ai_roster[:ai_count] if isinstance(entry, dict) and entry.get("team") == "B")
    if curr_a == braucht_a and curr_b == braucht_b:
        return
    for i in range(ai_count):
        ai_roster[i]["team"] = "A" if i < braucht_a else "B"
    lobby.settings["ai_roster"] = ai_roster



def team_balance_info(lobby: Lobby) -> dict:
    """Display-only summary the client can show without recomputing the rule
    itself (keeps client and server balance checks from drifting apart)."""
    a, b = team_counts(lobby)
    if lobby.mode != "Team-Zeitfahren":
        ok = True
    else:
        ok = (a == b) and (a + b) == lobby.roster_size
    return {"A": a, "B": b, "ok": ok}


def reset_lobby_ready(lobby: Lobby) -> None:
    """Any relevant lobby change (mode, roster, track, laps, class, team)
    clears everyone's "Bereit" state so nobody starts against a config they
    haven't seen."""
    for c in lobby.clients.values():
        c.lobby_ready = False


def offer_list(lobby: Lobby) -> list:
    """Vorschlagsliste fuer die Clients — ohne die Dateiinhalte.

    "name" ist der Dateiname (zum Speichern), "title" der Streckenname aus der
    Datei. Angezeigt wird der Titel: ein Dateiname mit .json sagt einem Spieler
    nichts darueber, was er da vor sich hat.
    """
    return [{"slot": s, "name": o["name"], "title": o.get("title") or o["name"],
             "size": o["size"], "from": o["from"]}
            for s, o in sorted(lobby.offers.items())]


# ── Wache: Grenzen je IP, Gesamtgrenzen, Laststufe ─────────────────────────────

class _Wache:
    """Zaehlt, was von wo kommt, und sagt, ob es noch erlaubt ist (H2.3, H2.14).

    Eine Stelle fuer alle Zaehler, weil die Aufnahmesperre aus H2.14 **dieselben**
    braucht wie die Grenzen aus H2.3 — nur mit anderer Absicht: die eine wehrt
    einen Angreifer ab, die andere schuetzt vor zwanzig echten Spielern zur
    selben Zeit.

    Missbrauch wird **nur protokolliert** (H6). Kein automatisches Sperren: ein
    Fehlalarm hinter geteilter IP schliesst einen echten Mitspieler aus.
    """

    def __init__(self) -> None:
        self.verbindungen: Dict[str, int] = {}
        self.lobbys: Dict[str, Set[str]] = {}          # IP → Lobby-IDs
        self._eimer: Dict[str, Tuple[float, float]] = {}   # IP → (Stand, Zeit)
        #: Zaehler fuer das Protokoll, nach Grund.
        self.abgewiesen: Dict[str, int] = {}

    # -- Adressen ------------------------------------------------------------
    @staticmethod
    def ip(addr) -> str:
        """Die IP aus einer ``peername``/``addr``-Angabe. ``"?"``, wenn keine da
        ist — dann greift nur die Gesamtgrenze."""
        if isinstance(addr, (tuple, list)) and addr:
            return str(addr[0])
        return "?"

    @staticmethod
    def unterscheidbar(ip: str) -> bool:
        """Ob hinter dieser Adresse genau ein Spieler stecken kann.

        Hinter einem Tunnel nicht — siehe :data:`TRUSTED_PROXIES`.
        """
        return ip != "?" and ip not in TRUSTED_PROXIES

    def _merken(self, grund: str, ip: str, was: str) -> None:
        self.abgewiesen[grund] = self.abgewiesen.get(grund, 0) + 1
        log.warning(f"abgewiesen [{grund}] {ip}: {was}")

    # -- Verbindungen --------------------------------------------------------
    def verbindungen_gesamt(self) -> int:
        return sum(self.verbindungen.values())

    def darf_verbinden(self, ip: str) -> Optional[str]:
        """Grund der Ablehnung, oder None."""
        if self.verbindungen_gesamt() >= MAX_CONN_TOTAL:
            self._merken("conn_total", ip, f"{self.verbindungen_gesamt()} offen")
            return "SERVER_BUSY"
        if self.unterscheidbar(ip) and self.verbindungen.get(ip, 0) >= MAX_CONN_PER_IP:
            self._merken("conn_ip", ip, f"{self.verbindungen[ip]} von dieser IP")
            return "TOO_MANY"
        return None

    def verbindung_an(self, ip: str) -> None:
        self.verbindungen[ip] = self.verbindungen.get(ip, 0) + 1

    def verbindung_ab(self, ip: str) -> None:
        rest = self.verbindungen.get(ip, 0) - 1
        if rest > 0:
            self.verbindungen[ip] = rest
        else:
            self.verbindungen.pop(ip, None)
        # Der Eimer eines Gastes, der weg ist, braucht nicht liegenzubleiben —
        # sonst waechst die Tabelle mit jeder je gesehenen Adresse.
        if ip not in self.verbindungen:
            self._eimer.pop(ip, None)

    # -- Lobbys --------------------------------------------------------------
    def darf_hosten(self, ip: str) -> Optional[str]:
        if len(_registry.lobbies) >= MAX_LOBBIES or self.laststufe() == LAST_VOLL:
            self._merken("lobby_total", ip, f"{len(_registry.lobbies)} Lobbys offen")
            return "SERVER_BUSY"
        if self.unterscheidbar(ip) and len(self.lobbys.get(ip, ())) >= MAX_LOBBIES_PER_IP:
            self._merken("lobby_ip", ip, f"{len(self.lobbys[ip])} Lobbys dieser IP")
            return "TOO_MANY"
        return None

    def lobby_an(self, ip: str, lid: str) -> None:
        self.lobbys.setdefault(ip, set()).add(lid)

    def lobby_ab(self, lid: str) -> None:
        for ip in [k for k, v in self.lobbys.items() if lid in v]:
            self.lobbys[ip].discard(lid)
            if not self.lobbys[ip]:
                self.lobbys.pop(ip, None)

    # -- Anfragerate ---------------------------------------------------------
    def nachricht_erlaubt(self, ip: str) -> bool:
        """Eimerverfahren: ``MAX_MSG_PER_S`` laufen nach, ``MSG_VORRAT`` passt
        hinein. Damit sind kurze Spitzen frei und Dauerlast begrenzt."""
        if not self.unterscheidbar(ip):
            return True
        jetzt = time.monotonic()
        stand, zuletzt = self._eimer.get(ip, (MSG_VORRAT, jetzt))
        stand = min(MSG_VORRAT, stand + (jetzt - zuletzt) * MAX_MSG_PER_S)
        if stand < 1.0:
            self._eimer[ip] = (stand, jetzt)
            return False
        self._eimer[ip] = (stand - 1.0, jetzt)
        return True

    # -- Auslastung ----------------------------------------------------------
    def laststufe(self) -> str:
        """frei / gut besucht / ausgelastet — aus Lobbys **und** Verbindungen.

        Die hoehere der beiden Auslastungen zaehlt: zwanzig Spieler in vier
        Lobbys sind fuer den Anschluss dasselbe Problem wie zwanzig Lobbys.
        """
        anteil = max(
            len(_registry.lobbies) / max(1, MAX_LOBBIES),
            self.verbindungen_gesamt() / max(1, MAX_CONN_TOTAL),
        )
        if anteil >= LAST_VOLL_AB:
            return LAST_VOLL
        if anteil >= LAST_GUT_AB:
            return LAST_GUT
        return LAST_FREI

    def auslastung(self) -> dict:
        """Was die ``INFO``-Antwort mitgibt (H2.14)."""
        return {
            "lobby_count": len(_registry.lobbies),
            "lobby_max":   MAX_LOBBIES,
            "load":        self.laststufe(),
        }


_wache = _Wache()


# ── Registry (process-global) ──────────────────────────────────────────────────

class _Registry:
    def __init__(self):
        self.lobbies: Dict[str, Lobby] = {}
        #: udp_addr → (lobby_id, slot). Der Slot steht mit dabei, damit ein
        #: Eintrag beim Trennen **sicher** wieder verschwindet (H2.5): vorher
        #: hing das Aufraeumen an ``conn.udp_addr``, also nur an der *letzten*
        #: Adresse eines Clients. Wechselt seine Quelladresse (NAT, neuer
        #: Anschluss, mehrfaches Registrieren), blieben die alten Eintraege
        #: unbegrenzt liegen.
        self.addr_map: Dict[Tuple, Tuple[str, int]] = {}

    def create(self) -> Lobby:
        pool = "".join(c for c in string.ascii_uppercase + string.digits
                       if c not in RESERVED_TAGS)
        while True:
            # secrets statt random (H2.9): der Lobbycode ist die **einzige**
            # Zugangskontrolle. Aus ``random`` sind fuenf Zeichen aus dem Zustand
            # des Mersenne-Twisters vorhersagbar, sobald man ein paar Codes
            # gesehen hat — und Codes sieht jeder, der eine Lobby aufmacht.
            lid = SERVER_TAG + "".join(secrets.choice(pool) for _ in range(5))
            if lid not in self.lobbies:
                break
        lobby = Lobby(lobby_id=lid)
        self.lobbies[lid] = lobby
        log.info(f"Lobby created: {lid}")
        return lobby

    def get(self, lid: str) -> Optional[Lobby]:
        return self.lobbies.get(lid)

    def remove(self, lid: str):
        lobby = self.lobbies.pop(lid, None)
        if lobby:
            self.unbind_lobby(lid)
            _wache.lobby_ab(lid)
            _pw_wache.lobby_ab(lid)
            log.info(f"Lobby removed: {lid}")

    def bind_udp(self, addr: Tuple, lid: str, slot: int):
        self.addr_map[addr] = (lid, slot)

    def unbind_slot(self, lid: str, slot: int) -> None:
        """Jede Adresse dieses Slots austragen — auch die, die er zwischenzeitlich
        hatte."""
        for addr in [a for a, (l, s) in self.addr_map.items()
                     if l == lid and s == slot]:
            self.addr_map.pop(addr, None)

    def unbind_lobby(self, lid: str) -> None:
        for addr in [a for a, (l, _s) in self.addr_map.items() if l == lid]:
            self.addr_map.pop(addr, None)

    def lobby_for_addr(self, addr: Tuple) -> Optional[Lobby]:
        eintrag = self.addr_map.get(addr)
        return self.lobbies.get(eintrag[0]) if eintrag else None

    def slot_for_addr(self, addr: Tuple) -> Optional[int]:
        eintrag = self.addr_map.get(addr)
        return eintrag[1] if eintrag else None


_registry = _Registry()

# ── TCP helpers ────────────────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, msg: dict):
    body = json.dumps(msg, ensure_ascii=False).encode()
    writer.write(_LEN.pack(len(body)) + body)
    await writer.drain()


MAX_PREAMBLE = 512   # a Minecraft handshake is ~32 bytes; anything larger is junk


async def _strip_mc_preamble(reader: asyncio.StreamReader) -> bytes:
    """Discard a leading Minecraft handshake packet, if there is one.

    Clients behind a playit.gg "Minecraft Java" tunnel must open every TCP
    connection with a valid handshake or the tunnel drops them — see
    src/net/mc_preamble.py. Telling the two apart is unambiguous: our own frames
    start with a 4-byte big-endian length and every message is far below 16 MB,
    so the first byte is always 0x00, which is never a valid handshake length.

    Returns the bytes already consumed that belong to the real stream (``b"\\x00"``
    when there was no preamble), to be handed to :func:`_recv` as *prefetched*.
    """
    try:
        first = await asyncio.wait_for(reader.readexactly(1), timeout=15.0)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
        return b""
    if first == b"\x00":
        return first

    # Minecraft varint: 7 bits per byte, high bit continues.
    byte   = first[0]
    length = byte & 0x7F
    shift  = 7
    try:
        while byte & 0x80:
            if shift > 28:
                return b""                      # not a sane varint
            nxt    = await asyncio.wait_for(reader.readexactly(1), timeout=5.0)
            byte   = nxt[0]
            length |= (byte & 0x7F) << shift
            shift  += 7
        if not 0 < length <= MAX_PREAMBLE:
            return b""
        await asyncio.wait_for(reader.readexactly(length), timeout=5.0)
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
        return b""
    return b""


async def _recv(reader: asyncio.StreamReader, prefetched: bytes = b"") -> Optional[dict]:
    try:
        need = 4 - len(prefetched)
        raw_len = prefetched
        if need > 0:
            raw_len += await asyncio.wait_for(reader.readexactly(need), timeout=60.0)
        length = _LEN.unpack(raw_len)[0]
        if length > MAX_MAP_B + 65536:
            return None
        raw = await asyncio.wait_for(reader.readexactly(length), timeout=120.0)
        msg = json.loads(raw)
        # Nur Objekte. ``json.loads(b"5")`` ergibt eine Zahl, und der ganze
        # Nachrichtenweg ruft danach ``msg.get(...)`` — das waere ein
        # AttributeError aus einem gueltigen JSON-Text (H2.8).
        return msg if isinstance(msg, dict) else None
    except (asyncio.IncompleteReadError, asyncio.TimeoutError,
            ConnectionResetError, struct.error, ValueError, RecursionError):
        # ValueError deckt JSONDecodeError **und** UnicodeDecodeError ab: beide
        # erben davon, und ungueltiges UTF-8 im Rumpf war vorher ungefangen
        # (H2.8). RecursionError kommt aus tief verschachteltem JSON.
        return None


async def _broadcast(lobby: Lobby, msg: dict, exclude: int = -1):
    for slot, conn in list(lobby.clients.items()):
        if slot != exclude:
            try:
                await _send(conn.writer, msg)
            except Exception:
                pass


def _lobby_state(lobby: Lobby) -> dict:
    picks = lobby.settings.get("picks", {})
    return {
        "type": "LOBBY_STATE",
        "lobby_id": lobby.lobby_id,
        "settings": lobby.settings,
        "mode": lobby.mode,
        "roster_size": lobby.roster_size,
        **lobby_info(lobby),
        "team_balance": team_balance_info(lobby),
        "players": [
            {
                "slot": c.slot, "name": c.name, "is_host": c.is_host,
                "lobby_ready": c.lobby_ready,
                "on_results": c.on_results,
                "vehicle": picks.get(str(c.slot), {}).get("vehicle", ""),
                "paint": picks.get(str(c.slot), {}).get("paint", ""),
                "team": c.team,
            }
            for c in lobby.clients.values()
        ],
    }


# ── TCP client handler ─────────────────────────────────────────────────────────

async def _handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    addr = writer.get_extra_info("peername")
    ip   = _Wache.ip(addr)
    log.info(f"TCP connect: {addr}")
    lobby: Optional[Lobby] = None
    conn: Optional[ClientConn] = None

    # Verbindungsgrenze **vor** allem anderen (H2.3). Wer schon zu viele offen
    # hat, bekommt eine Absage und wird getrennt — die Absage ist billiger als
    # eine Verbindung, die gehalten wird.
    grund = _wache.darf_verbinden(ip)
    if grund is not None:
        try:
            await _send(writer, {"type": "JOIN_FAIL", "code": grund,
                                 "reason": _ABSAGE_TEXT[grund]})
        except Exception:
            pass
        try:
            writer.close()
        except Exception:
            pass
        return
    _wache.verbindung_an(ip)
    verworfen = 0

    try:
        # ── handshake: HOST or JOIN ──────────────────────────────────────────
        prefetched = await _strip_mc_preamble(reader)
        msg = await asyncio.wait_for(_recv(reader, prefetched), timeout=15.0)
        if not msg:
            return

        t     = msg.get("type")
        name  = saeubere_name(msg.get("name", "Spieler"))

        if t == "INFO":
            cfg = _load_live_config()
            required = str(cfg.get("required_version", ""))
            client_v = str(msg.get("version", ""))
            await _send(writer, {
                "type": "INFO",
                "required_version": required,
                "version_ok": (required == "" or client_v == required),
                "announcements": cfg.get("announcements", []),
                "server_tag": SERVER_TAG,
                # lobby_count bleibt, wo es war — ein alter Client liest genau
                # dieses Feld. lobby_max und load kommen dazu; wer sie nicht
                # kennt, ueberliest sie und laeuft unveraendert (H3 Stufe 3).
                **_wache.auslastung(),
            })
            return

        # Streckenaustausch (Plan 1.1.0 §5): eigene kurze Verbindung wie INFO.
        if t in STRECKEN_TYPEN:
            await _strecken_anfrage(writer, msg, ip)
            return

        # Lobbyliste (Plan 1.1.0): ebenfalls eine kurze Anfrage-Verbindung.
        if t in LOBBYLISTE_TYPEN:
            await _lobbyliste_anfrage(writer, msg, ip)
            return

        if t == "HOST":
            cfg = _load_live_config()
            required = str(cfg.get("required_version", ""))
            client_v = str(msg.get("version", ""))
            if required and client_v != required:
                await _send(writer, {
                    "type": "JOIN_FAIL",
                    "code": "VERSION_MISMATCH",
                    "reason": f"Version {client_v or '?'} veraltet — benötigt {required}.",
                    "required_version": required,
                })
                return
            # Aufnahmesperre: **HOST ja, JOIN nein** (H2.14). Eine neue Lobby
            # ist der teure Vorgang; einem Freund den Beitritt in eine schon
            # laufende Lobby zu verweigern waere die falsche Sparsamkeit — der
            # Slot ist ohnehin reserviert.
            grund = _wache.darf_hosten(ip)
            if grund is not None:
                await _send(writer, {"type": "JOIN_FAIL", "code": grund,
                                     "reason": _ABSAGE_TEXT[grund]})
                return
            inhalt = str(msg.get("inhalt", ""))[:64]
            erlaubt = cfg.get("required_inhalt") or []
            if erlaubt and inhalt not in erlaubt:
                await _send(writer, {"type": "JOIN_FAIL", "code": "DATA_MISMATCH",
                                     "reason": "Spieldateien veraendert."})
                return
            # Sichtbarkeit, Name und Passwort **vor** dem Anlegen pruefen: eine
            # Lobby mit unbrauchbaren Angaben soll gar nicht erst entstehen.
            try:
                angaben = lobby_angaben(msg, name)
            except _LobbyFehler as f:
                await _send(writer, {"type": "JOIN_FAIL", "code": f.code,
                                     "reason": f.reason})
                return
            lobby = _registry.create()
            lobby.inhalt = inhalt
            lobby_angaben_setzen(lobby, *angaben)
            _wache.lobby_an(ip, lobby.lobby_id)
            slot  = 0
            conn  = ClientConn(slot=slot, name=name, reader=reader,
                               writer=writer, is_host=True, tcp_ip=ip,
                               token=secrets.token_hex(8))
            lobby.clients[slot] = conn
            lobby.host_slot     = slot
            lobby.next_slot     = 1
            await _send(writer, {"type": "JOIN_OK", "slot": slot,
                                 "lobby_id": lobby.lobby_id, "is_host": True,
                                 "udp_token": conn.token, **lobby_info(lobby)})
            log.info(f"Host '{name}' → lobby {lobby.lobby_id}")

        elif t == "JOIN":
            cfg = _load_live_config()
            required = str(cfg.get("required_version", ""))
            client_v = str(msg.get("version", ""))
            if required and client_v != required:
                await _send(writer, {
                    "type": "JOIN_FAIL",
                    "code": "VERSION_MISMATCH",
                    "reason": f"Version {client_v or '?'} veraltet — benötigt {required}.",
                    "required_version": required,
                })
                return
            lid = str(msg.get("lobby_id", "")).upper().strip()
            if lid[:1] != SERVER_TAG:
                # Code belongs to a different relay — the client routes by the
                # first character, so this only happens on a typo or a stale code.
                await _send(writer, {"type": "JOIN_FAIL", "code": "WRONG_SERVER",
                                     "reason": "Unbekannter Lobby-Code."})
                return
            lobby = _registry.get(lid)
            if not lobby:
                await _send(writer, {"type": "JOIN_FAIL", "reason": "Lobby nicht gefunden."})
                return
            # Passwort **vor** allen weiteren Auskuenften ueber die Lobby (voll,
            # laeuft schon): wer es nicht kennt, erfaehrt davon nichts.
            absage = passwort_beitritt(lobby, msg, ip)
            if absage is not None:
                await _send(writer, absage)
                return
            # Gleiche Fahrwerte wie der Host (src/core/integritaet.py). Ein
            # Client ohne das Feld (aelter als 1.0.0) scheitert schon an der
            # Versionspruefung oben.
            if getattr(lobby, "inhalt", "") and str(msg.get("inhalt", ""))[:64] != lobby.inhalt:
                await _send(writer, {"type": "JOIN_FAIL", "code": "DATA_MISMATCH",
                                     "reason": "Spieldateien passen nicht zur Lobby."})
                return
            if len(lobby.clients) >= lobby.roster_size or len(lobby.clients) >= MAX_SLOTS:
                await _send(writer, {"type": "JOIN_FAIL", "code": "LOBBY_FULL",
                                     "reason": "Lobby voll."})
                return
            frueheres_mitglied = bool(lobby.settings.get("gp_members", {}).get(name))
            if (lobby.state != "lobby" or lobby.starting) and not frueheres_mitglied:
                await _send(writer, {"type": "JOIN_FAIL", "reason": "Rennen läuft bereits."})
                return
            # Wer mitten im Rennen ausgestiegen ist, darf zurueck - er landet in
            # der Grand-Prix-Uebersicht und faehrt ab dem naechsten Lauf wieder
            # mit. Neue Spieler bleiben draussen (gp_locked, siehe unten).
            # Grand Prix: ab Serienstart kommt niemand Neues mehr hinein, sonst
            # platzt jemand mit 0 Punkten in eine laufende Wertung. Wer vorher
            # dabei war, hat seinen Slot noch und faellt nicht hierunter — der
            # wird oben ueber die freien Slots wieder eingesetzt.
            # Das Flag setzt der Host ueber SET_SETTINGS; ein Server ohne diese
            # Zeilen laesst die Lobby offen, bricht aber nichts.
            if lobby.settings.get("gp_locked") and not lobby.settings.get(
                    "gp_members", {}).get(name):
                await _send(writer, {"type": "JOIN_FAIL", "code": "SERIES_LOCKED",
                                     "reason": "Grand Prix läuft bereits."})
                return
            # Reuse freed slots: pick the smallest index not currently taken,
            # so a re-joining player fills the hole instead of growing the
            # roster forever. (The disconnect idempotency guard compares conn
            # OBJECTS, so slot reuse stays safe.)
            slot = min(set(range(MAX_SLOTS)) - set(lobby.clients.keys()))
            conn = ClientConn(slot=slot, name=name, reader=reader, writer=writer,
                              tcp_ip=ip, token=secrets.token_hex(8))
            # Put the new player on whichever side has fewer HUMANS (counting AI
            # here would be wrong: the AI slots are about to shrink by one, and
            # normalize_ai_teams redistributes them right after anyway).
            ha, hb = human_counts(lobby)
            conn.team = "B" if hb < ha else "A"
            lobby.clients[slot] = conn
            # The joining player consumed an AI slot — redistribute the rest.
            normalize_ai_teams(lobby)
            await _send(writer, {"type": "JOIN_OK", "slot": slot,
                                 "lobby_id": lid, "is_host": False,
                                 "udp_token": conn.token, **lobby_info(lobby)})
            log.info(f"Client '{name}' joined {lid} → slot {slot}")
            await _broadcast(lobby, _lobby_state(lobby))
            # Vorschlaege bleiben liegen, wer spaeter kommt bekommt sie trotzdem.
            if lobby.offers:
                await _send(writer, {"type": "OFFER_LIST", "offers": offer_list(lobby)})

        else:
            return

        # ── main message loop ────────────────────────────────────────────────
        while True:
            msg = await _recv(reader)
            if not msg:
                break
            # Anfragerate je IP (H2.3). Ueber der Rate wird die Nachricht
            # **verworfen**, nicht die Verbindung getrennt: eine Spitze beim
            # Lobbybeitritt ist normaler Betrieb. Haelt die Flut an, ist sie
            # keine Spitze mehr — dann wird getrennt, weil auch das Lesen und
            # Wegwerfen Zeit kostet.
            if not _wache.nachricht_erlaubt(ip):
                verworfen += 1
                if verworfen >= FLUT_ABBRUCH:
                    log.warning(f"Flut von {ip}: {verworfen} Nachrichten verworfen, trenne")
                    break
                continue
            t = msg.get("type")

            # ── Host: lobby settings ───────────────────────────────────────
            if t == "SET_SETTINGS" and conn.is_host:
                if lobby.state != "lobby":
                    await _send(conn.writer, {
                        "type": "ERROR", "code": "MODE_LOCKED",
                        "reason": "Änderung während des Rennens nicht möglich.",
                    })
                    continue
                payload = msg.get("settings", {})
                # Snapshot the fields whose change resets "Bereit" — taken
                # BEFORE settings.update() so we compare old vs. new below.
                before = (
                    lobby.mode, lobby.roster_size,
                    lobby.settings.get("track_path"),
                    lobby.settings.get("laps"),
                    lobby.settings.get("vehicle_class"),
                )
                mode = payload.get("mode")
                if mode not in VALID_MODES:
                    mode = "Rennen"
                roster_size = payload.get("roster_size")
                if roster_size not in VALID_ROSTER:
                    roster_size = lobby.roster_size
                # Team-Zeitfahren teilt das Feld in zwei gleich grosse Haelften -
                # eine ungerade Zahl liesse sich nicht aufteilen. Der Client bietet
                # sie dort gar nicht erst an; hier steht die Regel trotzdem, weil
                # der Server niemandem glauben darf.
                if mode == "Team-Zeitfahren" and roster_size % 2:
                    roster_size = lobby.roster_size if lobby.roster_size % 2 == 0 else 4
                if roster_size < len(lobby.clients):
                    await _send(conn.writer, {
                        "type": "ERROR", "code": "ROSTER_TOO_SMALL",
                        "reason": "Zu viele Spieler in der Lobby für diese Größe.",
                    })
                    roster_size = lobby.roster_size   # don't shrink; rest of the settings still land
                # Nur bekannte Schluessel, und die Ablage insgesamt gedeckelt
                # (H2.4). Ein unbekannter Schluessel wird still weggelassen: der
                # Relay verteilt ``settings`` an alle, und was er nicht kennt,
                # muss er auch nicht weitertragen.
                bekannt = {k: v for k, v in payload.items() if k in SETTINGS_KEYS}
                if "tageszeit" in bekannt and not (isinstance(bekannt["tageszeit"], str)
                                                   and bekannt["tageszeit"] in TAGESZEITEN):
                    bekannt["tageszeit"] = "Tag"
                if "wetter" in bekannt and not (isinstance(bekannt["wetter"], str)
                                                and bekannt["wetter"] in WETTER):
                    bekannt["wetter"] = "Trocken"
                unbekannt = len(payload) - len(bekannt)
                if unbekannt:
                    log.warning(f"Lobby {lobby.lobby_id}: {unbekannt} unbekannte "
                                f"settings-Schlüssel verworfen")
                probe = dict(lobby.settings)
                probe.update(bekannt)
                if _settings_groesse(probe) > MAX_SETTINGS_B:
                    await _send(conn.writer, {
                        "type": "ERROR", "code": "SETTINGS_TOO_BIG",
                        "reason": "Lobby-Einstellungen zu groß.",
                    })
                    log.warning(f"Lobby {lobby.lobby_id}: settings über "
                                f"{MAX_SETTINGS_B} B abgewiesen")
                    continue
                vorschlaege_vorher = bool(lobby.settings.get("offers_enabled"))
                lobby.settings.update(bekannt)
                lobby.mode = mode
                lobby.roster_size = roster_size
                # Schaltet der Host die Streckenvorschlaege aus, faellt die
                # Ablage mit. Sonst traegt der Relay sie bis zum Ende der Lobby
                # mit und liefert sie beim Wiedereinschalten - oder an jeden
                # spaeter Beitretenden - wieder aus (05.08.2026). Der Speicher
                # ist der eigentliche Grund: 6 MB je Lobby liegen sonst fuer
                # etwas herum, das niemand mehr sehen soll.
                if vorschlaege_vorher and not lobby.settings.get("offers_enabled"):
                    if lobby.offers:
                        lobby.offers.clear()
                        await _broadcast(lobby, {"type": "OFFER_LIST",
                                                 "offers": offer_list(lobby)})
                normalize_ai_teams(lobby)
                after = (
                    lobby.mode, lobby.roster_size,
                    lobby.settings.get("track_path"),
                    lobby.settings.get("laps"),
                    lobby.settings.get("vehicle_class"),
                )
                if before != after:
                    reset_lobby_ready(lobby)
                await _broadcast(lobby, _lobby_state(lobby))

            # ── Host: Sichtbarkeit, Name, Passwort der Lobby ────────────────
            elif t == "SET_LOBBY_INFO" and conn.is_host:
                await _lobby_info_aendern(lobby, conn, msg)

            # ── Any client: pick own team (Team-Zeitfahren) ─────────────────
            elif t == "SET_TEAM":
                team = msg.get("team")
                if team in ("A", "B") and lobby.state == "lobby":
                    conn.team = team
                    reset_lobby_ready(lobby)
                    normalize_ai_teams(lobby)
                    await _broadcast(lobby, _lobby_state(lobby))

            # ── Client: vehicle/team pick ──────────────────────────────────
            elif t == "PICK":
                lobby.settings.setdefault("picks", {})[str(conn.slot)] = {
                    "vehicle": msg.get("vehicle"),
                    "team":    msg.get("team"),
                    # Lackierung (Block D, D7). Der Relay bleibt der dumme
                    # Relay: er reicht die Kennung durch, ohne zu wissen, was
                    # eine Lackierung ist. Ein alter Client schickt nichts, dann
                    # steht hier None und alle sehen ihn im Werkslack.
                    "paint":   str(msg.get("paint", ""))[:64],
                }
                await _broadcast(lobby, _lobby_state(lobby))

            # ── Host: start race sequence ──────────────────────────────────
            elif t == "START_REQUEST" and conn.is_host:
                if lobby.mode == "Team-Zeitfahren":
                    a, b = team_counts(lobby)
                    if a != b or (a + b) != lobby.roster_size:
                        # The counts travel as data so the client can build a
                        # translated message; `reason` stays as the raw fallback.
                        await _send(conn.writer, {
                            "type": "ERROR", "code": "TEAM_UNBALANCED",
                            "a": a, "b": b,
                            "reason": f"Teams nicht ausgeglichen (A: {a}, B: {b}).",
                        })
                        continue
                is_custom = bool(msg.get("is_custom", False))
                track_name = str(msg.get("track_name", ""))
                lobby.map_meta = {"track_name": track_name, "is_custom": is_custom}
                lobby.map_buffer = b""
                lobby.starting = True   # closes the join window until _do_start
                lobby.reset_ready()
                for c in lobby.clients.values():
                    c.lobby_ready = False
                if is_custom:
                    lobby.state = "transferring"
                    # Notify guests to expect map data; host marks itself ready
                    # after upload_done is confirmed
                    await _broadcast(lobby, {
                        "type": "MAP_META", "track_name": track_name,
                        "is_custom": True, "size": msg.get("size", 0),
                    }, exclude=conn.slot)
                else:
                    # Built-in track: tell everyone, await READY from all
                    lobby.state = "lobby"   # clear a stale "transferring" from an aborted custom start
                    await _broadcast(lobby, {
                        "type": "MAP_META", "track_name": track_name, "is_custom": False,
                    })
                    conn.ready = True   # host is ready immediately
                    # Guests will send READY after they confirm the track exists

            # ── Host: map upload chunks ────────────────────────────────────
            elif t == "MAP_CHUNK" and conn.is_host and lobby.state == "transferring":
                # Wie bei OFFER_CHUNK: kaputtes base64 darf die Verbindung des
                # Gastgebers nicht beenden — das riss die ganze Lobby mit (H2.8).
                try:
                    raw = base64.b64decode(msg.get("data", ""), validate=True)
                except (ValueError, TypeError):
                    await _send(conn.writer, {"type": "ERROR", "code": "MAP_BROKEN",
                                              "reason": "Übertragung beschädigt."})
                    lobby.map_buffer = b""
                    lobby.state = "lobby"
                    lobby.starting = False
                    continue
                lobby.map_buffer += raw
                if len(lobby.map_buffer) > MAX_MAP_B:
                    await _send(conn.writer, {"type": "ERROR",
                                              "reason": "Map überschreitet 1 MB Limit."})
                    lobby.map_buffer = b""
                    lobby.state = "lobby"
                    lobby.starting = False
                    continue
                # Relay chunk to guests
                for s, c in lobby.clients.items():
                    if not c.is_host:
                        try:
                            await _send(c.writer, {"type": "MAP_CHUNK", "data": msg.get("data")})
                        except Exception:
                            pass

            elif t == "MAP_DONE" and conn.is_host and lobby.state == "transferring":
                for s, c in lobby.clients.items():
                    if not c.is_host:
                        try:
                            await _send(c.writer, {"type": "MAP_DONE"})
                        except Exception:
                            pass
                conn.ready = True   # host upload complete = host ready
                if lobby.all_ready():
                    await _do_start(lobby)

            # ── Any client: bietet eine eigene Strecke an ───────────────────
            elif t == "OFFER_META":
                if not lobby.settings.get("offers_enabled"):
                    await _send(conn.writer, {"type": "ERROR", "code": "OFFERS_OFF",
                                              "reason": "Streckenvorschläge sind ausgeschaltet."})
                    continue
                if lobby.state != "lobby":
                    await _send(conn.writer, {"type": "ERROR", "code": "OFFER_BUSY",
                                              "reason": "Während des Rennens nicht möglich."})
                    continue
                size = int(msg.get("size", 0) or 0)
                if size <= 0 or size > MAX_MAP_B:
                    await _send(conn.writer, {"type": "ERROR", "code": "OFFER_TOO_BIG",
                                              "reason": "Strecke überschreitet 1 MB."})
                    continue
                lobby.offer_buf[conn.slot] = b""
                lobby.offer_meta[conn.slot] = {"name": str(msg.get("track_name", "") or "strecke.json"),
                                               "title": str(msg.get("title", "") or ""),
                                               "size": size}

            elif t == "OFFER_CHUNK":
                if conn.slot not in lobby.offer_buf:
                    continue   # keine laufende Uebertragung fuer diesen Slot
                # Kaputtes base64 wirft binascii.Error (eine ValueError-Art) und
                # beendete vorher die ganze Verbindung ueber den aeusseren
                # except-Zweig (H2.8). Ein Stueck, das nicht dekodiert, verwirft
                # den Vorschlag — eine halbe Datei ist nutzlos.
                try:
                    raw = base64.b64decode(msg.get("data", ""), validate=True)
                except (ValueError, TypeError):
                    lobby.offer_buf.pop(conn.slot, None)
                    lobby.offer_meta.pop(conn.slot, None)
                    await _send(conn.writer, {"type": "ERROR", "code": "OFFER_BROKEN",
                                              "reason": "Übertragung beschädigt."})
                    continue
                lobby.offer_buf[conn.slot] += raw
                if len(lobby.offer_buf[conn.slot]) > MAX_MAP_B:
                    lobby.offer_buf.pop(conn.slot, None)
                    lobby.offer_meta.pop(conn.slot, None)
                    await _send(conn.writer, {"type": "ERROR", "code": "OFFER_TOO_BIG",
                                              "reason": "Strecke überschreitet 1 MB."})
                    continue

            elif t == "OFFER_DONE":
                if conn.slot not in lobby.offer_buf:
                    continue
                daten = lobby.offer_buf.pop(conn.slot)
                meta = lobby.offer_meta.pop(conn.slot, {})
                if not daten:
                    continue
                # Ein neuer Vorschlag ersetzt den eigenen alten von selbst
                # (gleicher Slot-Schluessel wird ueberschrieben).
                lobby.offers[conn.slot] = {"name": str(meta.get("name", "strecke.json")),
                                           "title": str(meta.get("title", "")),
                                           "data": daten, "size": len(daten), "from": conn.name}
                await _broadcast(lobby, {"type": "OFFER_LIST", "offers": offer_list(lobby)})
                log.info(f"Lobby {lobby.lobby_id}: Streckenvorschlag von Slot {conn.slot} ({len(daten)} B)")

            # ── Any client: holt sich die Datei eines Vorschlags ────────────
            elif t == "OFFER_REQUEST":
                # Ueber JSON kommt der Slot auch mal als Text an; die Ablage ist
                # nach Zahlen geschluesselt und faende dann nie etwas.
                try:
                    slot = int(msg.get("slot"))
                except (TypeError, ValueError):
                    continue
                eintrag = lobby.offers.get(slot)
                if eintrag is None:
                    continue
                await _send(conn.writer, {"type": "OFFER_DATA_META", "slot": slot,
                                          "track_name": eintrag["name"], "size": eintrag["size"]})
                # 32766 ist ein Vielfaches von 3 -> base64 endet ohne Fuellzeichen,
                # der Empfaenger kann die Stuecke vor dem Dekodieren aneinanderhaengen.
                daten = eintrag["data"]
                for i in range(0, len(daten), 32766):
                    stueck = daten[i:i + 32766]
                    await _send(conn.writer, {"type": "OFFER_DATA_CHUNK", "slot": slot,
                                              "data": base64.b64encode(stueck).decode()})
                await _send(conn.writer, {"type": "OFFER_DATA_DONE", "slot": slot})

            # ── Any client: finished loading its race, awaiting sync GO ─────
            elif t == "LOADED":
                if lobby.state == "racing":
                    lobby.loaded.add(conn.slot)
                    conn.last_udp = time.monotonic()  # Reset UDP timeout grace period
                    await _maybe_race_go(lobby)

            # ── Any client: pause / resume ready ───────────────────────────
            elif t == "PAUSE" and lobby.state == "racing":
                lobby.paused_by = conn.slot
                lobby.resume_ready.clear()
                await _broadcast(lobby, {
                    "type": "GAME_PAUSED",
                    "by_slot": conn.slot,
                    "by_name": conn.name
                })

            elif t == "RESUME_READY" and lobby.state == "racing" and lobby.paused_by is not None:
                lobby.resume_ready.add(conn.slot)
                await _broadcast(lobby, {
                    "type": "PAUSE_STATUS",
                    "paused_by_name": lobby.clients[lobby.paused_by].name if lobby.paused_by in lobby.clients else "Spieler",
                    "players": [
                        {
                            "name": c.name,
                            "slot": c.slot,
                            "ready": c.slot in lobby.resume_ready
                        }
                        for c in lobby.clients.values()
                    ]
                })
                if set(lobby.clients.keys()).issubset(lobby.resume_ready):
                    lobby.paused_by = None
                    lobby.resume_ready.clear()
                    # Reset UDP timeout for everyone to prevent disconnection during/after pause
                    for c in lobby.clients.values():
                        c.last_udp = time.monotonic()
                    await _broadcast(lobby, {
                        "type": "GAME_RESUME"
                    })

            # ── Any client: abort the race, send everyone back to the lobby ──
            elif t == "ABORT_RACE":
                if lobby.state == "racing":
                    lobby.state = "lobby"
                    lobby.starting = False
                    _cancel_finish_timer(lobby)
                    lobby.loaded = set()
                    lobby.reported = set()
                    lobby.results_rows = []
                    await _broadcast(lobby, {"type": "RETURN_LOBBY"})

            # ── Any client: first car across the line starts the DNF grace ──
            elif t == "FIRST_FINISH":
                if lobby.state == "racing" and not lobby.first_finish_seen:
                    lobby.first_finish_seen = True
                    # Clamp only against broken/hostile values, not the rule:
                    # 10 min is far beyond any real lap, 1 s guards against 0.
                    grace = max(1.0, min(float(msg.get("slowest_lap", 0) or 0), 600.0))
                    lobby.finish_timer = asyncio.ensure_future(_force_finish_after(lobby, grace))
                    log.info(f"Lobby {lobby.lobby_id}: first finish → DNF grace {grace:.1f}s")

            # ── Any client: finished its local race, reports results ────────
            elif t == "RACE_RESULT":
                if lobby.state == "racing":
                    lobby.results_rows.extend(msg.get("rows", []))
                    lobby.reported.add(conn.slot)
                    await _maybe_finalize_results(lobby)

            # ── Any client: signals ready (built-in or custom transfer done) ─
            elif t == "READY":
                conn.ready = True
                log.info(f"Slot {conn.slot} READY in {lobby.lobby_id}")
                if lobby.all_ready():
                    await _do_start(lobby)

            # ── Any client: lobby-ready toggle ────────────────────────────
            elif t == "LOBBY_READY":
                conn.lobby_ready = True
                await _broadcast(lobby, _lobby_state(lobby))

            elif t == "LOBBY_UNREADY":
                conn.lobby_ready = False
                await _broadcast(lobby, _lobby_state(lobby))

            # ── Client: presence on the results screen (rematch-vote gate) ──
            elif t == "RESULTS_ENTER":
                conn.on_results = True
                await _broadcast(lobby, _lobby_state(lobby))

            elif t == "RESULTS_LEAVE":
                conn.on_results = False
                await _broadcast(lobby, _lobby_state(lobby))

            # ── Client: text chat relay ────────────────────────────────────
            elif t == "CHAT":
                text = str(msg.get("text", ""))[:200]
                await _broadcast(lobby, {
                    "type": "CHAT", "slot": conn.slot, "name": conn.name, "text": text,
                }, exclude=conn.slot)

    except asyncio.TimeoutError:
        log.warning(f"TCP timeout: {addr}")
    except Exception as e:
        log.error(f"TCP handler error {addr}: {e}", exc_info=True)
    finally:
        if conn and lobby:
            _on_disconnect(lobby, conn)
        _wache.verbindung_ab(ip)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log.info(f"TCP closed: {addr}")


async def _do_start(lobby: Lobby):
    # Idempotency guard: READY can arrive redundantly (e.g. the host receives
    # its own broadcasted MAP_META and auto-fires an extra READY), so two
    # client tasks can each independently see all_ready()==True and both call
    # this. Without the guard that sends a second "START" broadcast, which
    # makes every client run state_machine.transition("race", ...) twice —
    # the second call's implicit exit() on the already-entered race state
    # wipes its own network session (session.clear()), leaving it permanently
    # disconnected ("NET: MISSING") for the rest of the race.
    if lobby.state == "racing":
        return
    lobby.state = "racing"
    lobby.starting = False
    _cancel_finish_timer(lobby)   # fresh race → fresh grace state
    lobby.results_rows = []
    lobby.reported = set()
    lobby.loaded = set()
    lobby.paused_by = None
    lobby.resume_ready.clear()
    lobby.race_start_ts = time.time()
    for conn in lobby.clients.values():
        conn.last_udp = time.monotonic()
        conn.on_results = False   # fresh rematch-presence state for the next results screen
    # Tell everyone to load their race. The synchronized countdown starts only
    # after all peers report LOADED (see RACE_GO), so the host's longer loading
    # screen doesn't eat part of its own countdown.
    await _broadcast(lobby, {"type": "START"})
    log.info(f"Lobby {lobby.lobby_id}: START broadcast (awaiting LOADED)")


def _cancel_finish_timer(lobby: Lobby) -> None:
    """Stop and forget the DNF grace timer (race ended, restarted, or aborted)."""
    if lobby.finish_timer is not None:
        lobby.finish_timer.cancel()
        lobby.finish_timer = None
    lobby.first_finish_seen = False


async def _force_finish_after(lobby: Lobby, grace: float) -> None:
    """After the grace window, tell everyone still driving to finish (DNF)."""
    try:
        await asyncio.sleep(grace)
    except asyncio.CancelledError:
        return
    if lobby.state != "racing":
        return
    lobby.finish_timer = None
    await _broadcast(lobby, {"type": "FORCE_FINISH"})
    log.info(f"Lobby {lobby.lobby_id}: FORCE_FINISH broadcast (grace expired)")


async def _maybe_race_go(lobby: Lobby):
    """Once every connected peer has finished loading, start the countdown."""
    if lobby.state != "racing" or not lobby.loaded:
        return
    if not set(lobby.clients.keys()).issubset(lobby.loaded):
        return
    await _broadcast(lobby, {"type": "RACE_GO"})
    log.info(f"Lobby {lobby.lobby_id}: RACE_GO (all {len(lobby.loaded)} loaded)")


async def _maybe_finalize_results(lobby: Lobby):
    """Broadcast combined RACE_RESULTS once every still-connected human has
    reported its finish (or when only reporters remain)."""
    if lobby.state != "racing" or not lobby.reported:
        return
    if not set(lobby.clients.keys()).issubset(lobby.reported):
        return
    await _finalize_results(lobby)


async def _finalize_results(lobby: Lobby):
    if lobby.state != "racing":
        return
    lobby.state = "lobby"
    _cancel_finish_timer(lobby)   # results are out; the grace timer is moot
    rows = list(lobby.results_rows)
    # Sort: finishers by time ascending, DNF last; assign positions.
    def _key(r):
        ft = r.get("finish_time")
        return (1 if r.get("dnf") or ft is None else 0, ft if ft is not None else 9e9)
    rows.sort(key=_key)
    for i, r in enumerate(rows):
        r["position"] = i + 1
    await _broadcast(lobby, {"type": "RACE_RESULTS", "rows": rows})
    log.info(f"Lobby {lobby.lobby_id}: RACE_RESULTS broadcast ({len(rows)} rows)")
    lobby.results_rows = []
    lobby.reported = set()


def _on_disconnect(lobby: Lobby, conn: ClientConn):
    # Idempotency: the watchdog may have removed this conn already; a second
    # call (e.g. when the zombie TCP connection finally closes) must not
    # re-run host promotion or broadcast PLAYER_LEFT again.
    if lobby.clients.get(conn.slot) is not conn:
        return
    lobby.clients.pop(conn.slot, None)
    # Jede Adresse dieses Slots austragen, nicht nur die letzte (H2.5): ein
    # Client, dessen Quelladresse sich zwischendurch geaendert hat, liess sonst
    # Eintraege in ``addr_map`` liegen — unbegrenzt und ohne Weg, sie loszuwerden.
    _registry.unbind_slot(lobby.lobby_id, conn.slot)

    if not lobby.clients:
        _registry.remove(lobby.lobby_id)
        return

    # A drop DURING a race must NOT tear the race down for everyone. Keep the
    # lobby (and its UDP relay) alive so the remaining players can finish; if the
    # host dropped, hand host duties to a remaining client. Only close the lobby
    # on a host drop while still in the pre-race lobby.
    if lobby.state == "racing":
        if conn.is_host:
            # A7: without the host there is no more AI simulation → abort the
            # race rather than let it limp along with frozen/vanished bots.
            # A8: the lobby itself survives — a remaining guest becomes host.
            new_host = next(iter(lobby.clients))
            lobby.host_slot = new_host
            lobby.clients[new_host].is_host = True
            lobby.state = "lobby"
            lobby.starting = False
            _cancel_finish_timer(lobby)
            lobby.loaded = set()
            lobby.reported = set()
            lobby.results_rows = []
            lobby.paused_by = None
            lobby.resume_ready.clear()
            reset_lobby_ready(lobby)
            normalize_ai_teams(lobby)   # one human fewer → AI slots shifted
            log.info(f"Host left {lobby.lobby_id} mid-race → race aborted, slot {new_host} promoted")
            asyncio.ensure_future(_broadcast(lobby, {
                "type": "RETURN_LOBBY", "reason": "HOST_LEFT",
            }))
            asyncio.ensure_future(_broadcast(lobby, _lobby_state(lobby)))
            return
        # Guest: race continues, host will take over the vehicle with AI (A6).
        asyncio.ensure_future(_broadcast(lobby, {
            "type": "PLAYER_LEFT", "slot": conn.slot, "name": conn.name,
        }))
        # A peer leaving must not stall the pre-race load sync or the results.
        asyncio.ensure_future(_maybe_race_go(lobby))
        asyncio.ensure_future(_maybe_finalize_results(lobby))
        return

    if conn.is_host:
        log.info(f"Host disconnected from {lobby.lobby_id} → closing lobby")
        asyncio.ensure_future(_close_lobby(lobby))
    else:
        # One human fewer in the pre-race lobby frees an AI slot — rebalance
        # before anyone reads team_balance from the next LOBBY_STATE.
        normalize_ai_teams(lobby)
        asyncio.ensure_future(_broadcast(lobby, {
            "type": "PLAYER_LEFT", "slot": conn.slot, "name": conn.name,
        }))
        asyncio.ensure_future(_broadcast(lobby, _lobby_state(lobby)))
        # The leaver may have been the last READY the start was waiting for —
        # nobody else will re-check, so the start would hang forever.
        if lobby.starting and lobby.all_ready():
            asyncio.ensure_future(_do_start(lobby))


async def _close_lobby(lobby: Lobby):
    await _broadcast(lobby, {
        "type": "LOBBY_CLOSED", "reason": "Host hat die Verbindung getrennt.",
    })
    _registry.remove(lobby.lobby_id)


# ── UDP relay ──────────────────────────────────────────────────────────────────

class _UDPRelay(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport: Optional[asyncio.DatagramTransport] = None

    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP ready on :{UDP_PORT}")

    def datagram_received(self, data: bytes, addr: Tuple):
        if not data:
            return
        t = data[0]

        if t == UDP_REGISTER:
            self._registrieren(data, addr)

        elif t == UDP_PING:
            if len(data) < _S_PING.size:
                return
            try:
                _, _, _, ts = _S_PING.unpack(data[:_S_PING.size])
            except struct.error:
                return
            if self.transport:
                self.transport.sendto(_S_PONG.pack(UDP_PONG, ts), addr)

        elif t in (UDP_STATE, UDP_BUMP):
            if len(data) < _S_HDR.size:
                return
            try:
                _, lid_b, sender_slot, _ = _S_HDR.unpack(data[:_S_HDR.size])
            except struct.error:
                return
            lid = lid_b.decode(errors="ignore").rstrip("\x00")
            # Harden against a client relaying packets into a foreign lobby:
            # trust only the lobby registered for the sender's own address,
            # not the lobby_id embedded in the packet.
            registered = _registry.lobby_for_addr(addr)
            if not registered or registered.lobby_id != lid:
                return
            # Und nur fuer den Slot, der zu dieser Adresse eingetragen ist. Sonst
            # koennte ein Lobbymitglied unter fremder Slotnummer senden und die
            # Autos eines anderen fernsteuern — dieselbe Luecke wie H2.1, nur
            # innerhalb der eigenen Lobby.
            if _registry.slot_for_addr(addr) != sender_slot:
                return
            lobby = registered
            conn = lobby.clients.get(sender_slot)
            if conn is None:
                return
            conn.last_udp = time.monotonic()
            # Rate je Slot (H2.7): darueber wird verworfen statt an bis zu fuenf
            # Peers weiterverteilt.
            if not conn.udp_erlaubt():
                return
            if self.transport:
                for slot, ziel in lobby.clients.items():
                    if slot != sender_slot and ziel.udp_addr:
                        self.transport.sendto(data, ziel.udp_addr)

    # ------------------------------------------------------------------
    def _registrieren(self, data: bytes, addr: Tuple) -> None:
        """``UDP_REGISTER`` — wer darf seine Adresse auf einen Slot legen.

        Der Kern von **H2.1**. Vorher genuegte der Paketinhalt: wer die Lobby-ID
        kannte und einen belegten Slot nannte, leitete den Positionsstrom eines
        fremden Spielers auf sich um. Der Betroffene sah die anderen einfrieren
        und flog nach 15 s per Watchdog heraus.

        Zwei Bedingungen, und beide muessen halten:

        * **Token** (Stufe 2) — aus ``JOIN_OK``, also nur dem echten Inhaber des
          Slots bekannt. Traegt das Paket keins, wird es abgewiesen.
        * **Quell-IP** (Stufe 1) — muss zur TCP-Verbindung des Slots passen.
          Greift nicht, wenn zwei Spieler hinter derselben Adresse sitzen; genau
          dafuer gibt es das Token. Hinter einem Tunnel (:data:`TRUSTED_PROXIES`)
          kommen alle mit derselben Adresse an, dort wird die Pruefung
          uebersprungen — sie waere keine Aussage.
        """
        if len(data) < _S_ID.size:
            return
        try:
            _, lid_b, slot = _S_ID.unpack(data[:_S_ID.size])
        except struct.error:
            return
        lid = lid_b.decode(errors="ignore").rstrip("\x00")
        lobby = _registry.get(lid)
        conn = lobby.clients.get(slot) if lobby else None
        if conn is None:
            return

        token = data[_S_ID.size:_S_ID.size + _TOKEN_B].decode(errors="ignore").rstrip("\x00")
        if not conn.token or not secrets.compare_digest(token, conn.token):
            _wache._merken("udp_token", _Wache.ip(addr),
                           f"Slot {slot} in {lid} ohne gültiges Token")
            return
        if _Wache.unterscheidbar(conn.tcp_ip) and _Wache.ip(addr) != conn.tcp_ip:
            _wache._merken("udp_ip", _Wache.ip(addr),
                           f"Slot {slot} in {lid} gehört {conn.tcp_ip}")
            return

        # Eine frühere Adresse desselben Slots austragen, sonst bleibt sie in
        # ``addr_map`` liegen und zeigt weiter auf den Slot (H2.5).
        _registry.unbind_slot(lid, slot)
        conn.udp_addr = addr
        conn.last_udp = time.monotonic()
        _registry.bind_udp(addr, lid, slot)

    def error_received(self, exc):
        log.warning(f"UDP error: {exc}")


# ── Watchdog ───────────────────────────────────────────────────────────────────

async def _watchdog():
    """Remove players that stop sending UDP packets during a race."""
    while True:
        await asyncio.sleep(5.0)
        now = time.monotonic()
        for lid, lobby in list(_registry.lobbies.items()):
            if lobby.state != "racing":
                continue
            for slot, conn in list(lobby.clients.items()):
                # Only check timeout if the client has actually loaded the race
                if conn.udp_addr and slot in lobby.loaded and (now - conn.last_udp) > UDP_TIMEOUT:
                    log.info(f"UDP timeout: slot {slot} in {lid}")
                    _on_disconnect(lobby, conn)
                    # Close the zombie TCP connection so the client's handler loop
                    # exits; _on_disconnect already broadcast PLAYER_LEFT.
                    try:
                        conn.writer.close()
                    except Exception:
                        pass


# ── Strecken online (Plan 1.1.0, Abschnitt 5) ─────────────────────────────────
#
# Spieler laden eigene Strecken hoch, andere durchsuchen die Liste und holen sie
# sich. Der Relay bleibt dabei dumm: er speichert, prueft das Format und zaehlt.
#
# **Was hochgeladen wird.** Nicht die fertige Spielstrecke (Mittellinie, Waende,
# Wegpunkte: 100 bis 200 KB), sondern der *Entwurf* des Editors — die Liste der
# Bauteile (``editor_tiles``). Der ist unter 20 KB, laesst sich auf dem Server
# vollstaendig pruefen (Raster, Ports, geschlossene Runde) und gibt dem Absender
# keine Zahlen in die Hand, die der Client ungeprueft in eine Physik fuettert.
# Der Empfaenger baut die Spielstrecke selbst daraus (TileTrackDraft).
#
# **Wie gesprochen wird.** Jede Anfrage ist eine eigene kurze Verbindung wie
# ``INFO``: eine Nachricht hin, eine zurueck, fertig. Lobbys sind davon
# unberuehrt, und ein alter Client schickt diese Nachrichten nie. Ein alter
# *Server* kennt sie nicht und schliesst still — der Client liest das als
# „dieser Server kann das noch nicht".
#
# Alles steht in diesem Abschnitt; in ``_handle_tcp`` ist nur ein Aufruf
# eingehaengt (siehe ``STRECKEN_TYPEN``).

import hashlib
import math
import re
from collections import deque

#: Nachrichtentypen, die als eigene Verbindung beantwortet werden.
STRECKEN_TYPEN = frozenset({"TRACK_UPLOAD", "TRACK_LIST", "TRACK_GET", "TRACK_REPORT"})

STRECKEN_DIR = os.environ.get(
    "RACE_STRECKEN_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "strecken_online"),
)
#: Schalter: ``RACE_STRECKEN_AUS=1`` lehnt jede Streckenanfrage ab (Notbremse).
STRECKEN_AUS         = os.environ.get("RACE_STRECKEN_AUS", "") not in ("", "0")
#: Obergrenze fuer den hochgeladenen Entwurf als JSON, in Bytes.
STRECKE_MAX_B        = int(os.environ.get("RACE_STRECKE_MAX_B", str(64 * 1024)))
#: Gesamtspeicher: Anzahl der Strecken (versteckte zaehlen mit) und Megabyte.
STRECKEN_MAX         = int(os.environ.get("RACE_STRECKEN_MAX", "500"))
STRECKEN_MAX_MB      = float(os.environ.get("RACE_STRECKEN_MAX_MB", "50"))
#: Uploads je Absender und UTC-Tag. Hinter einem Tunnel ohne Kennung (siehe
#: ``TRUSTED_PROXIES``) teilen sich alle diese Zahl x ``STRECKEN_PROXY_FAKTOR``.
STRECKEN_PRO_TAG     = int(os.environ.get("RACE_STRECKEN_PRO_TAG", "5"))
STRECKEN_PROXY_FAKTOR = 10
#: Ab so vielen **verschiedenen** Meldern wird eine Strecke versteckt.
STRECKEN_MELDUNGEN   = int(os.environ.get("RACE_STRECKEN_MELDUNGEN", "3"))
#: Anfragen je Minute und Absender (Liste, Abruf, Meldung, Upload zusammen).
STRECKEN_ANFRAGEN    = int(os.environ.get("RACE_STRECKEN_ANFRAGEN", "40"))
STRECKEN_SEITE_MAX   = 20

#: Gueltige Werte im Entwurf.
STRECKE_SCHWIERIGKEITEN = ("Einfach", "Mittel", "Schwer")
STRECKE_BREITE          = (250.0, 300.0)   # track_builder.WIDTH_MIN / WIDTH_MAX
STRECKE_TEILE           = (4, 256)         # Bauteile je Strecke: Minimum, Maximum
STRECKE_RASTER          = 400              # |col|, |row| hoechstens
STRECKE_MIN_LAENGE      = 3000.0           # track_builder.MIN_LENGTH, in px
_ZELLE                  = 400.0            # tile_track.CELL
_ID_MUSTER              = re.compile(r"^[0-9a-f]{8}$")
_TEXTUR_MUSTER          = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,23}$")
_ENTWURF_SCHLUESSEL     = frozenset({"version", "name", "width", "background_texture",
                                     "difficulty", "description", "start_piece_idx",
                                     "pieces"})
_TEIL_SCHLUESSEL        = frozenset({"kind", "col", "row", "rotation", "radius_cells"})

#: Was der Spieler zu einer Absage liest — ein Satz, der sagt, was zu tun ist.
_STRECKEN_TEXT = {
    "DISABLED":    "Online-Strecken sind auf diesem Server gerade abgeschaltet.",
    "BAD_REQUEST": "Anfrage unverständlich.",
    "TOO_LARGE":   "Die Strecke ist zu groß für den Server.",
    "BAD_FORMAT":  "Die Strecke hat ein ungültiges Format.",
    "BAD_TRACK":   "Die Strecke ist nicht fahrbar (nicht geschlossen, zu kurz oder überlappend).",
    "DUPLICATE":   "Diese Strecke gibt es auf dem Server schon.",
    "LIMIT_DAY":   "Du hast heute schon so viele Strecken hochgeladen, wie erlaubt sind. Morgen geht es weiter.",
    "STORE_FULL":  "Der Streckenspeicher dieses Servers ist voll. Bitte später noch einmal versuchen.",
    "NOT_FOUND":   "Diese Strecke gibt es nicht (mehr).",
    "RATE":        "Zu viele Anfragen. Bitte einen Moment warten.",
    "SERVER_BUSY": "Server ist gerade ausgelastet — versuch es in ein paar Minuten noch einmal.",
    "ERROR":       "Der Server konnte die Anfrage nicht bearbeiten.",
}


class _StreckenFehler(Exception):
    """Eine Absage mit Kennung; ``reason`` bekommt der Spieler zu lesen."""

    def __init__(self, code: str, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = text or _STRECKEN_TEXT.get(code, _STRECKEN_TEXT["ERROR"])


def saeubere_text(roh, laenge: int, vorgabe: str, extra: str = NAME_EXTRA) -> str:
    """Wie :func:`saeubere_name`, aber mit eigener Laenge und Vorgabe.

    Buchstaben und Ziffern jeder Sprache bleiben, dazu *extra*; Steuerzeichen,
    Zeilenumbrueche und alles andere fliegen raus. Eine Wortliste gibt es hier
    nicht — das bleibt Sache des Clients, der Anzeigen mit gesperrten Woertern
    ausblendet.
    """
    text = str(roh)[:laenge * 2]
    sauber = "".join(z for z in text if z.isalnum() or z in extra)
    sauber = " ".join(sauber.split())[:laenge].strip()
    return sauber or vorgabe


def _ganze_zahl(wert, lo: int, hi: int, was: str) -> int:
    """``int``, aber streng: kein bool, kein float, im Bereich."""
    if isinstance(wert, bool) or not isinstance(wert, int) or not lo <= wert <= hi:
        raise _StreckenFehler("BAD_FORMAT", f"Ungültiger Wert für {was}.")
    return wert


def _teil_ports(art: str, col: int, row: int, rot: int, r: int) -> tuple:
    """Die zwei Ports eines Bauteils als ``((x, y, Richtung), (x, y, Richtung))``.

    Spiegel von ``tile_track.Piece.ports`` — muss mit dem Client uebereinstimmen
    (tests/test_strecken_online.py vergleicht beide).
    """
    ox, oy = col * _ZELLE, row * _ZELLE
    c = _ZELLE
    s = r if art == "curve" else 1
    h = (s - 0.5) * c
    if art == "straight":
        if rot % 2 == 0:
            return ((ox, oy + c / 2, 180), (ox + c, oy + c / 2, 0))
        return ((ox + c / 2, oy, 270), (ox + c / 2, oy + c, 90))
    if rot == 0:
        return ((ox + h, oy, 270), (ox, oy + h, 180))
    if rot == 1:
        return ((ox, oy + s * c - h, 180), (ox + h, oy + s * c, 90))
    if rot == 2:
        return ((ox + s * c - h, oy + s * c, 90), (ox + s * c, oy + s * c - h, 0))
    return ((ox + s * c, oy + h, 0), (ox + s * c - h, oy, 270))


def _teil_mitte(col: int, row: int, rot: int, s: int) -> tuple:
    ox, oy = col * _ZELLE, row * _ZELLE
    return ((ox, oy), (ox, oy + s * _ZELLE), (ox + s * _ZELLE, oy + s * _ZELLE),
            (ox + s * _ZELLE, oy))[rot]


def _port_schluessel(p: tuple) -> tuple:
    return (round(p[0]), round(p[1]), p[2])


def entwurf_pruefen(roh) -> tuple:
    """Einen Streckenentwurf streng pruefen. Gibt ``(sauberer Entwurf, Angaben)``.

    Wirft :class:`_StreckenFehler`. Der Rueckgabe-Entwurf wird **neu aufgebaut**
    — gespeichert wird nie, was der Absender geschickt hat, sondern nur die
    Felder, die hier geprueft und auf ihre Typen gebracht wurden.

    Geprueft wird: genau die Schluessel des Editors, Bauteile im Raster, keine
    Ueberlappung, jede Verbindung geschlossen, eine einzige Runde durch alle
    Bauteile, Start/Ziel auf einer Geraden mit Gerader davor, Mindestlaenge.
    Das ist dieselbe Auswahl an Regeln wie ``TileTrackDraft.validate_game``,
    ohne die Kurvenradien — die ergeben sich aus den erlaubten Bauteilen und
    der erlaubten Breite von selbst.

    ``Angaben``: ``laenge`` (px), ``teile``, ``umriss`` (Punkte 0..255 fuer die
    Vorschau im Client).
    """
    if not isinstance(roh, dict):
        raise _StreckenFehler("BAD_FORMAT", "Die Strecke fehlt.")
    if set(roh) - _ENTWURF_SCHLUESSEL:
        raise _StreckenFehler("BAD_FORMAT", "Unbekannte Felder in der Strecke.")
    if roh.get("version") != 1 or isinstance(roh.get("version"), bool):
        raise _StreckenFehler("BAD_FORMAT", "Unbekannte Streckenversion.")

    breite = roh.get("width")
    if isinstance(breite, bool) or not isinstance(breite, (int, float)) \
            or not math.isfinite(breite) \
            or not STRECKE_BREITE[0] <= breite <= STRECKE_BREITE[1]:
        raise _StreckenFehler("BAD_FORMAT", "Ungültige Streckenbreite.")
    textur = roh.get("background_texture")
    if not isinstance(textur, str) or not _TEXTUR_MUSTER.match(textur):
        raise _StreckenFehler("BAD_FORMAT", "Ungültiger Hintergrund.")
    schwierigkeit = roh.get("difficulty")
    if schwierigkeit not in STRECKE_SCHWIERIGKEITEN:
        raise _StreckenFehler("BAD_FORMAT", "Ungültige Schwierigkeit.")
    beschreibung = roh.get("description", "")
    if not isinstance(beschreibung, str):
        raise _StreckenFehler("BAD_FORMAT", "Ungültige Beschreibung.")
    name = roh.get("name")
    if not isinstance(name, str):
        raise _StreckenFehler("BAD_FORMAT", "Ungültiger Name.")

    teile_roh = roh.get("pieces")
    if not isinstance(teile_roh, list) \
            or not STRECKE_TEILE[0] <= len(teile_roh) <= STRECKE_TEILE[1]:
        raise _StreckenFehler("BAD_FORMAT", "Ungültige Anzahl Bauteile.")
    teile: list = []
    belegt: set = set()
    for t in teile_roh:
        if not isinstance(t, dict) or set(t) != _TEIL_SCHLUESSEL:
            raise _StreckenFehler("BAD_FORMAT", "Ungültiges Bauteil.")
        art = t["kind"]
        if art not in ("straight", "curve"):
            raise _StreckenFehler("BAD_FORMAT", "Ungültige Bauteilart.")
        col = _ganze_zahl(t["col"], -STRECKE_RASTER, STRECKE_RASTER, "Spalte")
        row = _ganze_zahl(t["row"], -STRECKE_RASTER, STRECKE_RASTER, "Zeile")
        rot = _ganze_zahl(t["rotation"], 0, 3, "Drehung")
        r = _ganze_zahl(t["radius_cells"], 1, 3, "Radius")
        if art == "straight":
            r = 1          # bei Geraden ohne Bedeutung; so gibt es nur eine Schreibweise
        s = r if art == "curve" else 1
        zellen = {(col + dc, row + dr) for dc in range(s) for dr in range(s)}
        if zellen & belegt:
            raise _StreckenFehler("BAD_TRACK")
        belegt |= zellen
        teile.append((art, col, row, rot, r))
    start = _ganze_zahl(roh.get("start_piece_idx"), 0, len(teile) - 1, "Startteil")

    # Ports verbinden (wie TileTrackDraft.connections).
    karte: dict = {}
    for i, (art, col, row, rot, r) in enumerate(teile):
        for q, p in enumerate(_teil_ports(art, col, row, rot, r)):
            karte[_port_schluessel(p)] = (i, q)
    gegen: dict = {}
    for i, (art, col, row, rot, r) in enumerate(teile):
        for q, p in enumerate(_teil_ports(art, col, row, rot, r)):
            partner = karte.get((round(p[0]), round(p[1]), (p[2] + 180) % 360))
            if partner is None:
                raise _StreckenFehler("BAD_TRACK")
            gegen[(i, q)] = partner

    # Eine Runde durch alle Bauteile, ab Port 0 des Startteils.
    laenge = 0.0
    punkte: list = []
    i, q = start, 0
    besucht = {i}
    for _ in range(len(teile) + 1):
        art, col, row, rot, r = teile[i]
        p_ein = _teil_ports(art, col, row, rot, r)[q]
        p_aus = _teil_ports(art, col, row, rot, r)[1 - q]
        punkte.append((p_ein[0], p_ein[1]))
        if art == "straight":
            laenge += _ZELLE
        else:
            radius = (r - 0.5) * _ZELLE
            cx, cy = _teil_mitte(col, row, rot, r)
            a0 = math.atan2(p_ein[1] - cy, p_ein[0] - cx)
            a1 = math.atan2(p_aus[1] - cy, p_aus[0] - cx)
            diff = (a1 - a0) % (2 * math.pi)
            if diff > math.pi:
                diff -= 2 * math.pi
            laenge += abs(radius * diff)
            for k in range(1, 6):
                a = a0 + diff * k / 6
                punkte.append((cx + radius * math.cos(a), cy + radius * math.sin(a)))
        ni, nq = gegen[(i, 1 - q)]
        if ni == start:
            if nq != 0:
                raise _StreckenFehler("BAD_TRACK")   # Start rueckwaerts betreten
            break
        if ni in besucht:
            raise _StreckenFehler("BAD_TRACK")
        besucht.add(ni)
        i, q = ni, nq
    else:
        raise _StreckenFehler("BAD_TRACK")
    if len(besucht) != len(teile):
        raise _StreckenFehler("BAD_TRACK")    # zwei getrennte Runden

    # Start/Ziel: eine Gerade mit einer Geraden davor (start_straight_ok).
    if teile[start][0] != "straight" or teile[gegen[(start, 0)][0]][0] != "straight":
        raise _StreckenFehler("BAD_TRACK")
    if laenge < STRECKE_MIN_LAENGE:
        raise _StreckenFehler("BAD_TRACK")

    sauber = {
        "version": 1,
        "name": saeubere_text(name, 40, "Strecke"),
        "width": round(float(breite), 1),
        "background_texture": textur,
        "difficulty": schwierigkeit,
        "description": saeubere_text(beschreibung, 120, "", NAME_EXTRA + ".,!?:;()"),
        "start_piece_idx": start,
        "pieces": [{"kind": a, "col": c, "row": z, "rotation": d, "radius_cells": r}
                   for (a, c, z, d, r) in teile],
    }
    return sauber, {"laenge": int(round(laenge)), "teile": len(teile),
                    "umriss": _umriss(punkte)}


def _umriss(punkte: list, hoechstens: int = 48) -> list:
    """Die Mittellinie auf wenige Punkte 0..255 gebracht — fuer die Vorschau.

    Der Client zeichnet daraus ein Bild; ueber das Netz gehen keine Bilder. Das
    Seitenverhaeltnis bleibt erhalten, die laengere Seite fuellt 0..255.
    """
    if not punkte:
        return []
    schritt = max(1, math.ceil(len(punkte) / hoechstens))
    auswahl = punkte[::schritt]
    xs = [p[0] for p in punkte]
    ys = [p[1] for p in punkte]
    x0, y0 = min(xs), min(ys)
    mass = max(max(xs) - x0, max(ys) - y0) or 1.0
    return [[int(round((x - x0) / mass * 255)), int(round((y - y0) / mass * 255))]
            for x, y in auswahl]


def entwurf_hash(entwurf: dict) -> str:
    """Fingerabdruck der **Form**, ohne Namen, Text und Lage im Raster.

    Wer eine fremde Strecke unter neuem Namen oder um ein paar Felder
    verschoben noch einmal hochlaedt, bekommt dieselbe Zahl.
    """
    teile = entwurf["pieces"]
    c0 = min(p["col"] for p in teile)
    r0 = min(p["row"] for p in teile)
    flach = sorted((p["kind"], p["col"] - c0, p["row"] - r0, p["rotation"], p["radius_cells"])
                   for p in teile)
    sp = teile[entwurf["start_piece_idx"]]
    kern = {"w": entwurf["width"], "p": flach,
            "s": [sp["col"] - c0, sp["row"] - r0]}
    return hashlib.sha256(json.dumps(kern, sort_keys=True).encode()).hexdigest()


class StreckenSpeicher:
    """Die abgelegten Strecken: je Strecke eine Datei, dazu ein Verzeichnis.

    ``<verzeichnis>/<id>.json``  unveraenderlich: ``{"meta": ..., "track": Entwurf}``
    ``<verzeichnis>/index.json`` Kopfdaten aller Strecken **mit** den veraenderlichen
                                 Feldern (Abrufe, Meldungen, versteckt) und den
                                 Tageszaehlern.

    Geht der Index verloren oder ist er kaputt, wird er aus den Dateien neu
    gebaut (Abrufe und Meldungen beginnen dann bei null). Gespeichert wird
    atomar (Schreiben in eine Nebendatei, dann ``os.replace``), damit ein Absturz
    mitten im Schreiben nie eine halbe Datei hinterlaesst.

    Der Index wird bei jeder Anfrage auf Aenderung geprueft: das Verwaltungs-
    werkzeug (``tools/strecken_verwalten.py``) arbeitet auf denselben Dateien,
    waehrend der Server laeuft.
    """

    def __init__(self, verzeichnis: str, **grenzen) -> None:
        self.verzeichnis = verzeichnis
        self.max_stueck     = grenzen.get("max_stueck", STRECKEN_MAX)
        self.max_bytes      = int(grenzen.get("max_mb", STRECKEN_MAX_MB) * 1024 * 1024)
        self.pro_tag        = grenzen.get("pro_tag", STRECKEN_PRO_TAG)
        self.melde_schwelle = grenzen.get("meldungen", STRECKEN_MELDUNGEN)
        self.anfragen_min   = grenzen.get("anfragen", STRECKEN_ANFRAGEN)
        self.tracks: dict = {}
        self.tag = ""
        self.zaehler: dict = {}
        self.salz = ""
        self._stand = None
        self._eimer: dict = {}
        os.makedirs(self.verzeichnis, exist_ok=True)
        self._laden()

    # -- Pfade und Dateien ---------------------------------------------------
    def _index_pfad(self) -> str:
        return os.path.join(self.verzeichnis, "index.json")

    def _datei(self, tid: str) -> str:
        return os.path.join(self.verzeichnis, f"{tid}.json")

    @staticmethod
    def _schreiben(pfad: str, daten) -> None:
        tmp = pfad + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, pfad)

    def _speichern(self) -> None:
        self._schreiben(self._index_pfad(), {
            "version": 1, "salz": self.salz, "tag": self.tag,
            "zaehler": self.zaehler, "tracks": self.tracks})
        self._stand = self._index_stand()

    def _index_stand(self):
        try:
            return os.stat(self._index_pfad()).st_mtime_ns
        except OSError:
            return None

    def _laden(self) -> None:
        try:
            with open(self._index_pfad(), encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get("tracks"), dict):
                raise ValueError("Index ohne tracks")
            self.tracks = {k: v for k, v in d["tracks"].items()
                           if _ID_MUSTER.match(str(k)) and isinstance(v, dict)}
            self.tag = str(d.get("tag", ""))
            self.zaehler = {str(k): int(v) for k, v in dict(d.get("zaehler", {})).items()}
            self.salz = str(d.get("salz", "")) or secrets.token_hex(8)
            self._stand = self._index_stand()
            return
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning(f"Streckenindex unlesbar, baue neu auf: {exc}")
        self._neu_aufbauen()

    def _neu_aufbauen(self) -> None:
        self.tracks = {}
        self.salz = secrets.token_hex(8)
        self.tag, self.zaehler = "", {}
        try:
            namen = sorted(os.listdir(self.verzeichnis))
        except OSError:
            namen = []
        for n in namen:
            tid = n[:-5]
            if not n.endswith(".json") or not _ID_MUSTER.match(tid):
                continue
            try:
                with open(self._datei(tid), encoding="utf-8") as f:
                    meta = json.load(f)["meta"]
                meta = dict(meta, id=tid, downloads=0, reports=[], hidden=False,
                            bytes=os.path.getsize(self._datei(tid)))
                self.tracks[tid] = meta
            except Exception as exc:
                log.warning(f"Strecke {n} unlesbar, uebersprungen: {exc}")
        self._speichern()

    def _frisch(self) -> None:
        """Index neu lesen, wenn ihn jemand anders geaendert hat."""
        jetzt = self._index_stand()
        if jetzt != self._stand:
            self._laden()

    # -- Schluessel und Grenzen ---------------------------------------------
    def _kurz(self, schluessel: str) -> str:
        return hashlib.sha256((self.salz + schluessel).encode()).hexdigest()[:12]

    def anfrage_erlaubt(self, schluessel: str) -> bool:
        """Gleitendes Minutenfenster je Absender."""
        jetzt = time.monotonic()
        q = self._eimer.setdefault(schluessel, deque())
        while q and jetzt - q[0] > 60.0:
            q.popleft()
        grenze = self.anfragen_min * (STRECKEN_PROXY_FAKTOR if schluessel == "proxy" else 1)
        if len(q) >= grenze:
            return False
        q.append(jetzt)
        if len(self._eimer) > 4096:         # alte Absender nicht ewig behalten
            for k in [k for k, v in self._eimer.items() if not v or jetzt - v[-1] > 60.0]:
                self._eimer.pop(k, None)
        return True

    def belegt(self) -> tuple:
        return len(self.tracks), sum(int(t.get("bytes", 0)) for t in self.tracks.values())

    # -- Schreiben -----------------------------------------------------------
    def hochladen(self, entwurf: dict, angaben: dict, autor: str,
                  schluessel: str, faktor: int = 1) -> dict:
        """Eine bereits gepruefte Strecke ablegen. Wirft :class:`_StreckenFehler`."""
        self._frisch()
        heute = time.strftime("%Y-%m-%d", time.gmtime())
        if self.tag != heute:
            self.tag, self.zaehler = heute, {}
        kurz = self._kurz(schluessel)
        if self.zaehler.get(kurz, 0) >= self.pro_tag * faktor:
            raise _StreckenFehler("LIMIT_DAY")
        hsh = entwurf_hash(entwurf)
        if any(t.get("hash") == hsh for t in self.tracks.values()):
            raise _StreckenFehler("DUPLICATE")
        anzahl, groesse = self.belegt()
        inhalt_b = len(json.dumps(entwurf, ensure_ascii=False).encode()) + 600
        if anzahl >= self.max_stueck or groesse + inhalt_b > self.max_bytes:
            raise _StreckenFehler("STORE_FULL")
        while True:
            tid = secrets.token_hex(4)
            if tid not in self.tracks and not os.path.exists(self._datei(tid)):
                break
        meta = {
            "id": tid, "name": entwurf["name"], "author": autor,
            "theme": entwurf["background_texture"],
            "difficulty": entwurf["difficulty"],
            "length": angaben["laenge"], "pieces": angaben["teile"],
            "outline": angaben["umriss"], "created": int(time.time()),
            "hash": hsh,
        }
        self._schreiben(self._datei(tid), {"meta": meta, "track": entwurf})
        meta = dict(meta, downloads=0, reports=[], hidden=False,
                    bytes=os.path.getsize(self._datei(tid)))
        self.tracks[tid] = meta
        self.zaehler[kurz] = self.zaehler.get(kurz, 0) + 1
        self._speichern()
        return meta

    def melden(self, tid: str, schluessel: str) -> bool:
        """Eine Meldung eintragen. Gibt zurueck, ob die Strecke jetzt versteckt ist."""
        self._frisch()
        t = self.tracks.get(tid)
        if t is None:
            raise _StreckenFehler("NOT_FOUND")
        kurz = self._kurz(schluessel)
        if kurz not in t["reports"]:
            t["reports"].append(kurz)
            if len(t["reports"]) >= self.melde_schwelle and not t["hidden"]:
                t["hidden"] = True
                log.warning(f"Strecke {tid} '{t.get('name')}' versteckt "
                            f"({len(t['reports'])} Meldungen)")
            self._speichern()
        return bool(t["hidden"])

    # -- Lesen ---------------------------------------------------------------
    @staticmethod
    def _oeffentlich(t: dict) -> dict:
        return {k: t[k] for k in ("id", "name", "author", "theme", "difficulty",
                                  "length", "pieces", "outline", "created")
                if k in t} | {"downloads": int(t.get("downloads", 0))}

    def liste(self, sortierung: str = "new", suche: str = "",
              seite: int = 0, je_seite: int = 8) -> dict:
        self._frisch()
        je_seite = max(1, min(STRECKEN_SEITE_MAX, int(je_seite)))
        suche = suche.strip().lower()[:30]
        treffer = [t for t in self.tracks.values() if not t.get("hidden")
                   and (not suche or suche in str(t.get("name", "")).lower()
                        or suche in str(t.get("author", "")).lower())]
        if sortierung == "downloads":
            treffer.sort(key=lambda t: (-int(t.get("downloads", 0)), -int(t.get("created", 0))))
        else:
            treffer.sort(key=lambda t: -int(t.get("created", 0)))
        seiten = max(1, math.ceil(len(treffer) / je_seite))
        seite = max(0, min(seiten - 1, int(seite)))
        teil = treffer[seite * je_seite:(seite + 1) * je_seite]
        return {"tracks": [self._oeffentlich(t) for t in teil], "page": seite,
                "pages": seiten, "total": len(treffer), "sort": sortierung,
                "slots_used": len(self.tracks), "slots_max": self.max_stueck}

    def holen(self, tid: str) -> dict:
        self._frisch()
        t = self.tracks.get(tid)
        if t is None or t.get("hidden"):
            raise _StreckenFehler("NOT_FOUND")
        try:
            with open(self._datei(tid), encoding="utf-8") as f:
                entwurf = json.load(f)["track"]
        except Exception:
            raise _StreckenFehler("NOT_FOUND")
        t["downloads"] = int(t.get("downloads", 0)) + 1
        self._speichern()
        return dict(self._oeffentlich(t), track=entwurf)


_strecken_speicher: Optional[StreckenSpeicher] = None


def strecken_speicher() -> StreckenSpeicher:
    """Der Speicher dieses Prozesses; wird beim ersten Gebrauch angelegt."""
    global _strecken_speicher
    if _strecken_speicher is None:
        _strecken_speicher = StreckenSpeicher(STRECKEN_DIR)
    return _strecken_speicher


def _strecken_schluessel(ip: str, msg: dict) -> tuple:
    """Wer fragt: ``(Schluessel, Faktor fuer die Tagesgrenze)``.

    Eine unterscheidbare Adresse zaehlt selbst. Hinter einem Tunnel (Hamburg)
    sind alle Spieler dieselbe Adresse — dort zaehlt die Kennung, die der Client
    mitschickt (``cid``, zufaellig, vom Spieler selbst erzeugt). Das bremst
    ehrliche Spieler einzeln und ist leicht zu umgehen; wer das tut, trifft aber
    immer noch Speicher- und Anfragegrenze. Ohne Kennung teilen sich alle hinter
    dem Tunnel ein grosses gemeinsames Konto.
    """
    if _Wache.unterscheidbar(ip):
        return f"ip:{ip}", 1
    cid = "".join(z for z in str(msg.get("cid", ""))[:32] if z.isalnum())
    if len(cid) >= 8:
        return f"cid:{cid}", 1
    return "proxy", STRECKEN_PROXY_FAKTOR


async def _strecken_anfrage(writer: asyncio.StreamWriter, msg: dict, ip: str) -> None:
    """Eine Streckenanfrage beantworten. Die Verbindung schliesst der Aufrufer."""
    t = msg.get("type")
    try:
        if STRECKEN_AUS:
            raise _StreckenFehler("DISABLED")
        speicher = strecken_speicher()
        schluessel, faktor = _strecken_schluessel(ip, msg)
        if not speicher.anfrage_erlaubt(schluessel):
            _wache._merken("strecken_rate", ip, f"{t}")
            raise _StreckenFehler("RATE")

        if t == "TRACK_LIST":
            antwort = speicher.liste(
                str(msg.get("sort", "new")) if msg.get("sort") in ("new", "downloads") else "new",
                str(msg.get("query", ""))[:60],
                msg.get("page", 0) if isinstance(msg.get("page", 0), int) else 0,
                msg.get("per_page", 8) if isinstance(msg.get("per_page", 8), int) else 8)
            await _send(writer, dict(antwort, type="TRACK_LIST"))

        elif t == "TRACK_GET":
            tid = str(msg.get("id", ""))
            if not _ID_MUSTER.match(tid):
                raise _StreckenFehler("NOT_FOUND")
            await _send(writer, dict(speicher.holen(tid), type="TRACK_DATA"))

        elif t == "TRACK_REPORT":
            tid = str(msg.get("id", ""))
            if not _ID_MUSTER.match(tid):
                raise _StreckenFehler("NOT_FOUND")
            versteckt = speicher.melden(tid, schluessel)
            await _send(writer, {"type": "TRACK_REPORT_OK", "id": tid, "hidden": versteckt})

        elif t == "TRACK_UPLOAD":
            roh = msg.get("track")
            # Grenze auf dem, was ankommt — nicht auf dem, was der Absender
            # behauptet. ``separators`` wie beim Speichern, sonst zaehlt der
            # Leerraum mit.
            try:
                groesse = len(json.dumps(roh, ensure_ascii=False,
                                         separators=(",", ":")).encode())
            except (TypeError, ValueError):
                raise _StreckenFehler("BAD_FORMAT")
            if groesse > STRECKE_MAX_B:
                raise _StreckenFehler("TOO_LARGE")
            entwurf, angaben = entwurf_pruefen(roh)
            if msg.get("name"):
                entwurf["name"] = saeubere_text(msg["name"], 40, entwurf["name"])
            autor = saeubere_name(msg.get("author", "Spieler"))
            meta = speicher.hochladen(entwurf, angaben, autor, schluessel, faktor)
            log.info(f"Strecke hochgeladen: {meta['id']} '{meta['name']}' von '{autor}'")
            await _send(writer, {"type": "TRACK_UPLOAD_OK", "id": meta["id"],
                                 "name": meta["name"]})
    except _StreckenFehler as f:
        await _send(writer, {"type": "TRACK_ERROR", "code": f.code, "reason": f.reason})
    except Exception as exc:
        log.error(f"Streckenanfrage {t} fehlgeschlagen: {exc}", exc_info=True)
        try:
            await _send(writer, {"type": "TRACK_ERROR", "code": "ERROR",
                                 "reason": _STRECKEN_TEXT["ERROR"]})
        except Exception:
            pass


# ── Lobbyliste: Sichtbarkeit, Name, Passwort (Plan 1.1.0) ───────────────────────
#
# Jede Lobby traegt eine Sichtbarkeit, die der Host waehlt:
#
#   public    in der Liste, jeder darf beitreten
#   password  in der Liste mit Schloss, Beitritt nur mit Passwort
#   private   nicht in der Liste, Beitritt nur mit dem Code (wie bisher)
#
# **Abwaertskompatibel:** ein ``HOST`` ohne ``visibility`` (aelteres Spiel) legt
# eine private Lobby an. Alles Neue steht in eigenen Funktionen; in den
# bestehenden Handlern sind es nur kurze Aufrufe.

#: Nachrichtentypen, die als eigene kurze Verbindung beantwortet werden.
LOBBYLISTE_TYPEN = frozenset({"LOBBY_LIST"})

SICHT_OEFFENTLICH = "public"
SICHT_PASSWORT    = "password"
SICHT_PRIVAT      = "private"
SICHTBARKEITEN    = (SICHT_OEFFENTLICH, SICHT_PASSWORT, SICHT_PRIVAT)

LOBBYNAME_MAX = 24
PW_MIN, PW_MAX = 4, 16
#: Rechenaufwand des Passworthashs. PBKDF2 ist in jedem Python dabei; der Wert
#: ist bewusst mittel — die Lobbypasswoerter sind kurzlebig, und die Grenze fuer
#: Fehlversuche (unten) ist die eigentliche Bremse.
PW_ITERATIONEN = int(os.environ.get("RACE_PW_ITERATIONEN", "20000"))

#: Fehlversuche je Absender im Zeitfenster, danach Sperre bis das Fenster
#: abgelaufen ist. Absender = IP, hinter einem Tunnel (Hamburg) die ``cid`` des
#: Spielers; ohne beides ein gemeinsames Konto mit zehnfacher Grenze.
PW_VERSUCHE        = int(os.environ.get("RACE_PW_VERSUCHE", "5"))
PW_FENSTER         = float(os.environ.get("RACE_PW_FENSTER", "60"))
#: Zusaetzlich je Lobby, ueber alle Absender: eine selbst erzeugte ``cid`` ist
#: leicht zu wechseln, die Lobby aber nicht.
PW_VERSUCHE_LOBBY  = int(os.environ.get("RACE_PW_VERSUCHE_LOBBY", "30"))
PW_FENSTER_LOBBY   = float(os.environ.get("RACE_PW_FENSTER_LOBBY", "600"))
#: Abfragen der Lobbyliste je Minute und Absender (der Client fragt alle 5 s).
LOBBYLISTE_PRO_MIN = int(os.environ.get("RACE_LOBBYLISTE_PRO_MIN", "30"))
#: Wie oft der Host das Passwort wechseln darf (Sekunden Abstand): jeder Wechsel
#: kostet einen Hash.
PW_WECHSEL_ABSTAND = 1.0

_LOBBY_TEXT = {
    "BAD_PASSWORD":        "Falsches Passwort.",
    "PASSWORD_REQUIRED":   "Diese Lobby ist durch ein Passwort geschützt.",
    "TOO_MANY_ATTEMPTS":   "Zu viele falsche Versuche. Bitte in einer Minute noch einmal probieren.",
    "BAD_VISIBILITY":      "Ungültige Sichtbarkeit.",
    "BAD_PASSWORD_FORMAT": f"Das Passwort muss {PW_MIN} bis {PW_MAX} Zeichen lang sein.",
    "RATE":                "Zu viele Anfragen. Bitte einen Moment warten.",
}


class _LobbyFehler(Exception):
    """Eine Absage mit Kennung; ``reason`` bekommt der Spieler zu lesen."""

    def __init__(self, code: str, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = text or _LOBBY_TEXT.get(code, "Fehler.")


# -- Passwort -----------------------------------------------------------------

def pw_pruefen(roh) -> str:
    """Das Passwort, wenn es die Form hat; sonst ``_LobbyFehler``.

    4 bis 16 druckbare Zeichen, keine Steuerzeichen. Kein ``strip``: ein
    Leerzeichen am Ende gehoert dann zum Passwort, und der Client darf es genauso
    senden, wie der Spieler es getippt hat.
    """
    if (not isinstance(roh, str) or not (PW_MIN <= len(roh) <= PW_MAX)
            or not roh.isprintable()):
        raise _LobbyFehler("BAD_PASSWORD_FORMAT")
    return roh


def pw_hash_von(pw: str, salz: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salz, PW_ITERATIONEN)


def pw_setzen(lobby: Lobby, pw: str) -> None:
    """Passwort der Lobby ablegen — als frisches Salz und Hash, nie im Klartext."""
    lobby.pw_salt = secrets.token_bytes(16)
    lobby.pw_hash = pw_hash_von(pw, lobby.pw_salt)


def pw_loeschen(lobby: Lobby) -> None:
    lobby.pw_salt = b""
    lobby.pw_hash = b""


def pw_stimmt(lobby: Lobby, pw) -> bool:
    """Ob *pw* zum Passwort der Lobby passt. Vergleich in konstanter Zeit."""
    if not lobby.pw_hash:
        return True
    if not isinstance(pw, str) or len(pw) > 64:
        return False
    return hmac.compare_digest(pw_hash_von(pw, lobby.pw_salt), lobby.pw_hash)


class _PwWache:
    """Zaehlt falsche Passwoerter je Absender und je Lobby.

    Gleitendes Fenster: gezaehlt werden nur Fehlversuche der letzten
    ``PW_FENSTER`` Sekunden. Ein Absender ueber der Grenze wird abgewiesen, ohne
    dass ueberhaupt gehasht wird — die Sperre ist billiger als der Versuch.
    """

    def __init__(self) -> None:
        self._absender: Dict[str, "list[float]"] = {}
        self._lobbys: Dict[str, "list[float]"] = {}

    @staticmethod
    def _frisch(liste: "list[float]", fenster: float, jetzt: float) -> "list[float]":
        return [z for z in liste if jetzt - z < fenster]

    def gesperrt(self, schluessel: str, faktor: int, lid: str) -> bool:
        jetzt = time.monotonic()
        a = self._frisch(self._absender.get(schluessel, []), PW_FENSTER, jetzt)
        l = self._frisch(self._lobbys.get(lid, []), PW_FENSTER_LOBBY, jetzt)
        return len(a) >= PW_VERSUCHE * faktor or len(l) >= PW_VERSUCHE_LOBBY

    def fehlversuch(self, schluessel: str, lid: str) -> None:
        jetzt = time.monotonic()
        self._absender[schluessel] = self._frisch(
            self._absender.get(schluessel, []), PW_FENSTER, jetzt) + [jetzt]
        self._lobbys[lid] = self._frisch(
            self._lobbys.get(lid, []), PW_FENSTER_LOBBY, jetzt) + [jetzt]
        if len(self._absender) > 2000:        # alte Absender nicht ewig halten
            for k in [k for k, v in self._absender.items()
                      if not self._frisch(v, PW_FENSTER, jetzt)]:
                self._absender.pop(k, None)

    def lobby_ab(self, lid: str) -> None:
        self._lobbys.pop(lid, None)


_pw_wache = _PwWache()


def passwort_beitritt(lobby: Lobby, msg: dict, ip: str) -> Optional[dict]:
    """Prueft das Passwort eines ``JOIN``. ``None`` = darf weiter, sonst die
    Absage als fertige ``JOIN_FAIL``-Nachricht.

    Ohne Passwort in der Nachricht wird **nicht** gezaehlt: das ist kein Raten,
    der Client fragt damit nur, ob eines noetig ist (Beitritt per Code).
    """
    if not lobby.pw_hash:
        return None
    pw = msg.get("password")
    if pw is None or pw == "":
        return {"type": "JOIN_FAIL", "code": "BAD_PASSWORD", "need_password": True,
                "reason": _LOBBY_TEXT["PASSWORD_REQUIRED"]}
    # Absender wie bei den Strecken: eine unterscheidbare IP zaehlt selbst,
    # hinter einem Tunnel die ``cid``, sonst ein gemeinsames Konto.
    schluessel, faktor = _strecken_schluessel(ip, msg)
    if _pw_wache.gesperrt(schluessel, faktor, lobby.lobby_id):
        _wache._merken("pw_versuche", ip, f"Lobby {lobby.lobby_id}")
        return {"type": "JOIN_FAIL", "code": "TOO_MANY_ATTEMPTS",
                "retry_after": int(PW_FENSTER),
                "reason": _LOBBY_TEXT["TOO_MANY_ATTEMPTS"]}
    if pw_stimmt(lobby, pw):
        return None
    _pw_wache.fehlversuch(schluessel, lobby.lobby_id)
    return {"type": "JOIN_FAIL", "code": "BAD_PASSWORD", "need_password": True,
            "reason": _LOBBY_TEXT["BAD_PASSWORD"]}


# -- Angaben der Lobby ----------------------------------------------------------

def lobby_angaben(msg: dict, hostname: str, alt: Optional[Lobby] = None) -> tuple:
    """``(Sichtbarkeit, Name, Passwort oder None)`` aus einem ``HOST`` oder
    ``SET_LOBBY_INFO``. Wirft ``_LobbyFehler``.

    Fehlt ``visibility`` bei einem ``HOST``, gilt ``private`` (aelteres Spiel).
    Bei einer Aenderung (*alt* gesetzt) bleibt, was nicht in der Nachricht steht.
    Das Passwort ist ``None``, wenn es nicht neu gesetzt wird.
    """
    vorgabe_name = f"Lobby von {hostname}"
    if alt is None:
        sicht = msg.get("visibility", SICHT_PRIVAT)
        name_roh = msg.get("lobby_name", "")
    else:
        sicht = msg.get("visibility", alt.sichtbarkeit)
        name_roh = msg.get("lobby_name", alt.lobby_name)
    if not isinstance(sicht, str) or sicht not in SICHTBARKEITEN:
        raise _LobbyFehler("BAD_VISIBILITY")
    name = saeubere_text(name_roh, LOBBYNAME_MAX, vorgabe_name) if name_roh else vorgabe_name
    pw = None
    if sicht == SICHT_PASSWORT:
        if msg.get("password") not in (None, ""):
            pw = pw_pruefen(msg.get("password"))
        elif alt is None or not alt.pw_hash:
            raise _LobbyFehler("BAD_PASSWORD_FORMAT")   # Passwort-Lobby ohne Passwort
    return sicht, name, pw


def lobby_angaben_setzen(lobby: Lobby, sicht: str, name: str, pw: Optional[str]) -> None:
    lobby.sichtbarkeit = sicht
    lobby.lobby_name = name
    if sicht != SICHT_PASSWORT:
        pw_loeschen(lobby)          # ein altes Passwort bleibt nicht liegen
    elif pw is not None:
        pw_setzen(lobby, pw)


def lobby_info(lobby: Lobby) -> dict:
    """Was Mitglieder einer Lobby ueber deren Sichtbarkeit erfahren — nie den Hash."""
    return {
        "lobby_name": lobby.lobby_name,
        "visibility": lobby.sichtbarkeit,
        "has_password": bool(lobby.pw_hash),
    }


async def _lobby_info_aendern(lobby: Lobby, conn: ClientConn, msg: dict) -> None:
    """``SET_LOBBY_INFO`` des Hosts: Sichtbarkeit, Name, Passwort."""
    if msg.get("password") not in (None, "") and (
            time.monotonic() - lobby.pw_geaendert < PW_WECHSEL_ABSTAND):
        await _send(conn.writer, {"type": "ERROR", "code": "RATE",
                                  "reason": _LOBBY_TEXT["RATE"]})
        return
    try:
        sicht, name, pw = lobby_angaben(msg, conn.name, alt=lobby)
    except _LobbyFehler as f:
        await _send(conn.writer, {"type": "ERROR", "code": f.code, "reason": f.reason})
        return
    if pw is not None:
        lobby.pw_geaendert = time.monotonic()
    lobby_angaben_setzen(lobby, sicht, name, pw)
    log.info(f"Lobby {lobby.lobby_id}: Sichtbarkeit {sicht}, Name '{name}'")
    await _broadcast(lobby, _lobby_state(lobby))


# -- Die Liste -------------------------------------------------------------------

def lobby_im_rennen(lobby: Lobby) -> bool:
    """Ob die Lobby gerade nicht beitretbar ist, weil gefahren wird.

    Ein Grand Prix zaehlt fuer die **ganze Serie** als „im Rennen": zwischen den
    Laeufen sitzen die Spieler in der Uebersicht, nicht in der Lobby. Erst wenn
    die Serie vorbei ist (``gp_active`` faellt weg), ist sie wieder offen.
    """
    if lobby.state != "lobby" or lobby.starting:
        return True
    s = lobby.settings
    return bool(s.get("gp_active")
                and (s.get("gp_phase") == "overview" or s.get("gp_locked")))


def lobby_liste() -> list:
    """Die oeffentlichen und passwortgeschuetzten Lobbys dieses Servers.

    Private erscheinen nie. Weder Hash noch Mitgliederdaten — nur, was die
    Liste zeigt.
    """
    out = []
    for lobby in list(_registry.lobbies.values()):
        if lobby.sichtbarkeit not in (SICHT_OEFFENTLICH, SICHT_PASSWORT):
            continue
        host = lobby.host
        if host is None:
            continue
        out.append({
            "code": lobby.lobby_id,
            "name": lobby.lobby_name or f"Lobby von {host.name}",
            "host": host.name,
            "players": len(lobby.clients),
            "max": min(lobby.roster_size, MAX_SLOTS),
            "status": "racing" if lobby_im_rennen(lobby) else "lobby",
            "password": lobby.sichtbarkeit == SICHT_PASSWORT,
            "mode": lobby.mode,
        })
    return out


_lobbyliste_zeiten: Dict[str, "list[float]"] = {}


def _lobbyliste_erlaubt(schluessel: str, faktor: int) -> bool:
    """Gleitendes Minutenfenster je Absender."""
    jetzt = time.monotonic()
    z = [t for t in _lobbyliste_zeiten.get(schluessel, []) if jetzt - t < 60.0]
    if len(z) >= LOBBYLISTE_PRO_MIN * faktor:
        _lobbyliste_zeiten[schluessel] = z
        return False
    z.append(jetzt)
    _lobbyliste_zeiten[schluessel] = z
    if len(_lobbyliste_zeiten) > 2000:
        for k in [k for k, v in _lobbyliste_zeiten.items()
                  if not any(jetzt - t < 60.0 for t in v)]:
            _lobbyliste_zeiten.pop(k, None)
    return True


async def _lobbyliste_anfrage(writer: asyncio.StreamWriter, msg: dict, ip: str) -> None:
    """``LOBBY_LIST`` beantworten. Die Verbindung schliesst der Aufrufer."""
    schluessel, faktor = _strecken_schluessel(ip, msg)
    if not _lobbyliste_erlaubt(schluessel, faktor):
        _wache._merken("lobbyliste_rate", ip, "LOBBY_LIST")
        await _send(writer, {"type": "LOBBY_ERROR", "code": "RATE",
                             "reason": _LOBBY_TEXT["RATE"]})
        return
    await _send(writer, {"type": "LOBBY_LIST", "server_tag": SERVER_TAG,
                         "lobbies": lobby_liste()})


# ── Entry point ────────────────────────────────────────────────────────────────

async def _main():
    loop = asyncio.get_running_loop()

    tcp_servers = []
    for port in TCP_PORTS:
        try:
            tcp_servers.append(await asyncio.start_server(_handle_tcp, HOST, port))
        except OSError as exc:
            log.error(f"TCP port {port} unavailable: {exc}")
    if not tcp_servers:
        raise SystemExit("no TCP port could be bound")

    udp_transport, _ = await loop.create_datagram_endpoint(
        _UDPRelay, local_addr=(HOST, UDP_PORT)
    )

    log.info(f"Relay '{SERVER_TAG}' listening on {HOST} — "
             f"TCP {','.join(str(p) for p in TCP_PORTS)} / UDP {UDP_PORT}")
    asyncio.ensure_future(_watchdog())

    try:
        await asyncio.gather(*(s.serve_forever() for s in tcp_servers))
    finally:
        for s in tcp_servers:
            s.close()
        udp_transport.close()


if __name__ == "__main__":
    asyncio.run(_main())
