"""Strecken online tauschen — die Anfragen an den Relay (Plan 1.1.0 §5).

Jede Anfrage ist eine eigene kurze TCP-Verbindung wie ``INFO``: eine Nachricht
hin, eine zurueck, fertig. Die Funktionen **blockieren** (bis zu ``TIMEOUT``
Sekunden) und gehoeren in einen Arbeitsfaden — die Seite
(``src/states/online_strecken_state.py``) startet sie dort.

Fehler kommen als :class:`StreckenFehler` mit einer Kennung und einem Satz, den
der Spieler lesen kann. Die Kennungen des Servers (``TRACK_ERROR.code``) werden
hier uebersetzt; dazu kommen drei, die nur der Client kennt:

``OFFLINE``      der Server ist nicht erreichbar
``TIMEOUT``      er antwortet nicht
``UNSUPPORTED``  er schliesst ohne Antwort — ein Relay, der die Streckenfunktion
                 noch nicht kennt (ein Server ohne die Neuerung ignoriert die
                 Nachricht, so wie er jede unbekannte ignoriert)
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import struct

from src.core.i18n import tr
from src.net import server_probe
from src.net.servers import ServerDef

_LEN = struct.Struct("!I")

TIMEOUT = 8.0
#: Antworten ueber dieser Groesse sind nicht von unserem Relay (eine Seite Liste
#: sind wenige KB, eine Strecke unter 64 KB).
MAX_ANTWORT = 512 * 1024

#: Seitengroesse der Liste; der Server klemmt auf 20.
JE_SEITE = 8


class StreckenFehler(Exception):
    """Eine Anfrage ist gescheitert. ``text`` ist fuer den Spieler gedacht."""

    def __init__(self, code: str, text: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.text = text or text_fuer(code)


def text_fuer(code: str, vom_server: str = "") -> str:
    """Was der Spieler zu *code* liest — uebersetzt, nicht der Text des Servers.

    Der Server schickt seinen Satz auf Deutsch mit; angezeigt wird die
    uebersetzte Fassung hier, und der Satz des Servers nur fuer eine Kennung,
    die diese Version nicht kennt (ein neuerer Relay).
    """
    tabelle = {
        "OFFLINE":     tr("Der Server ist nicht erreichbar."),
        "TIMEOUT":     tr("Der Server antwortet nicht."),
        "UNSUPPORTED": tr("Dieser Server kann noch keine Online-Strecken. Bitte den anderen Server wählen."),
        "DISABLED":    tr("Online-Strecken sind auf diesem Server gerade abgeschaltet."),
        "BAD_REQUEST": tr("Anfrage unverständlich."),
        "TOO_LARGE":   tr("Die Strecke ist zu groß für den Server."),
        "BAD_FORMAT":  tr("Die Strecke hat ein ungültiges Format."),
        "BAD_TRACK":   tr("Die Strecke ist nicht fahrbar (nicht geschlossen, zu kurz oder überlappend)."),
        "DUPLICATE":   tr("Diese Strecke gibt es auf dem Server schon."),
        "LIMIT_DAY":   tr("Du hast heute schon so viele Strecken hochgeladen, wie erlaubt sind. Morgen geht es weiter."),
        "STORE_FULL":  tr("Der Streckenspeicher dieses Servers ist voll. Bitte später noch einmal versuchen."),
        "NOT_FOUND":   tr("Diese Strecke gibt es nicht (mehr)."),
        "RATE":        tr("Zu viele Anfragen. Bitte einen Moment warten."),
        "SERVER_BUSY": tr("Server ist gerade ausgelastet — versuch es in ein paar Minuten noch einmal."),
        "ERROR":       tr("Der Server konnte die Anfrage nicht bearbeiten."),
        "ANTWORT":     tr("Unerwartete Antwort vom Server."),
    }
    return tabelle.get(code) or vom_server or tabelle["ERROR"]


# -- Kennung dieses Spielers ---------------------------------------------------

def kennung() -> str:
    """Eine zufaellige Kennung, einmal erzeugt und dann behalten.

    Der Relay in Hamburg sieht hinter dem Tunnel nur eine Adresse; die Kennung
    erlaubt ihm, Tagesgrenze und Meldungen je Spieler zu zaehlen. Sie enthaelt
    nichts ueber den Spieler.
    """
    from src.core import paths
    pfad = paths.user_path("data", "settings", "strecken_kennung.txt")
    try:
        with open(pfad, encoding="ascii") as f:
            alt = "".join(z for z in f.read().strip() if z.isalnum())
        if len(alt) >= 8:
            return alt[:32]
    except OSError:
        pass
    neu = secrets.token_hex(8)
    try:
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "w", encoding="ascii") as f:
            f.write(neu)
    except OSError:
        pass                      # dann gilt sie nur fuer diese Sitzung
    return neu


# -- Eine Anfrage --------------------------------------------------------------

def anfrage(sd: ServerDef, msg: dict, timeout: float = TIMEOUT) -> dict:
    """*msg* an *sd* schicken und die Antwort lesen.

    Wirft :class:`StreckenFehler`. Eine ``TRACK_ERROR``-Antwort wird zur
    Ausnahme, alles andere kommt als Dict zurueck.
    """
    host, port, _udp = server_probe.resolve_endpoint(sd)
    try:
        # Auf IPv4 festgenagelt wie probe_tcp/NetworkClient: der Tunnel
        # veroeffentlicht auch eine AAAA-Adresse, die das Spiel nie benutzt.
        with socket.create_connection((socket.gethostbyname(host), port),
                                      timeout=timeout) as s:
            s.settimeout(timeout)
            roh = json.dumps(dict(msg, cid=kennung()), ensure_ascii=False).encode("utf-8")
            s.sendall(sd.preamble_bytes(host, port) + _LEN.pack(len(roh)) + roh)
            kopf = _lesen(s, _LEN.size)
            (laenge,) = _LEN.unpack(kopf)
            if laenge > MAX_ANTWORT:
                raise StreckenFehler("ANTWORT")
            koerper = _lesen(s, laenge)
    except StreckenFehler:
        raise
    except socket.timeout:
        raise StreckenFehler("TIMEOUT")
    except (_Geschlossen, ConnectionResetError, ConnectionAbortedError):
        raise StreckenFehler("UNSUPPORTED")
    except OSError:
        raise StreckenFehler("OFFLINE")
    try:
        antwort = json.loads(koerper.decode("utf-8"))
    except ValueError:
        raise StreckenFehler("ANTWORT")
    if not isinstance(antwort, dict):
        raise StreckenFehler("ANTWORT")
    if antwort.get("type") == "TRACK_ERROR":
        code = str(antwort.get("code", "ERROR"))
        raise StreckenFehler(code, text_fuer(code, str(antwort.get("reason", ""))))
    return antwort


class _Geschlossen(Exception):
    """Der Server hat die Verbindung ohne (vollstaendige) Antwort geschlossen."""


def _lesen(s: socket.socket, n: int) -> bytes:
    puffer = b""
    while len(puffer) < n:
        stueck = s.recv(n - len(puffer))
        if not stueck:
            raise _Geschlossen()
        puffer += stueck
    return puffer


# -- Die vier Anfragen ---------------------------------------------------------

def liste(sd: ServerDef, sortierung: str = "new", suche: str = "",
          seite: int = 0, je_seite: int = JE_SEITE) -> dict:
    """Eine Seite der Streckenliste: ``{"tracks": [...], "page", "pages", "total"}``."""
    a = anfrage(sd, {"type": "TRACK_LIST", "sort": sortierung, "query": suche,
                     "page": seite, "per_page": je_seite})
    if a.get("type") != "TRACK_LIST" or not isinstance(a.get("tracks"), list):
        raise StreckenFehler("ANTWORT")
    return a


def holen(sd: ServerDef, tid: str) -> dict:
    """Eine Strecke samt Entwurf (``["track"]``)."""
    a = anfrage(sd, {"type": "TRACK_GET", "id": tid})
    if a.get("type") != "TRACK_DATA" or not isinstance(a.get("track"), dict):
        raise StreckenFehler("ANTWORT")
    return a


def hochladen(sd: ServerDef, entwurf: dict, name: str, autor: str) -> dict:
    """Einen Entwurf (``editor_tiles``) ablegen. Gibt ``{"id", "name"}``."""
    a = anfrage(sd, {"type": "TRACK_UPLOAD", "track": entwurf, "name": name,
                     "author": autor})
    if a.get("type") != "TRACK_UPLOAD_OK":
        raise StreckenFehler("ANTWORT")
    return a


def melden(sd: ServerDef, tid: str) -> bool:
    """Eine Strecke melden. Gibt zurueck, ob sie dadurch versteckt wurde."""
    a = anfrage(sd, {"type": "TRACK_REPORT", "id": tid})
    if a.get("type") != "TRACK_REPORT_OK":
        raise StreckenFehler("ANTWORT")
    return bool(a.get("hidden"))
