"""
Relay server for 2D Racing Game — Online Multiplayer.

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
    # Grand Prix: Serienzustand reist im selben Block mit (§3 D/G-Entwurf).
    "gp_tracks", "gp_track_key", "gp_active", "gp_phase", "gp_finished",
    "gp_locked", "gp_members", "gp_race", "gp_total", "gp_points", "gp_raced",
    "gp_standings",
    # Der Server selbst legt es an (PICK), nicht der Host — steht hier, damit
    # ein Aufraeumen es nicht wegwirft.
    "picks",
})

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
            lobby = _registry.create()
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
                                 "udp_token": conn.token})
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
                                 "udp_token": conn.token})
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
