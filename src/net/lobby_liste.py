"""Lobbyliste: offene Lobbys aller Server in einer Liste (Plan 1.1.0).

Jeder Relay beantwortet ``LOBBY_LIST`` mit seinen oeffentlichen und
passwortgeschuetzten Lobbys (``server/server.py:lobby_liste``). Hier werden die
Antworten **aller** Server — Helsinki und Hamburg — zu einer Liste zusammengefuehrt.

Wie die Streckenanfragen ist jede Abfrage eine eigene kurze Verbindung, die
**blockiert**. Sie laeuft deshalb in Arbeitsfaeden, einer je Server und parallel,
damit ein langsamer Server die Liste des anderen nicht aufhaelt. Die Seite
(``src/states/menu/lobby_browser.py``) stoesst alle fuenf Sekunden eine neue Runde
an und liest nur das fertige Ergebnis; nichts hier beruehrt pygame.

Alles, was vom Netz kommt, wird geprueft und gesaeubert, bevor es angezeigt wird
(Block H, H2.12) — auch der Name der Lobby und des Hosts. Eintraege, die auf die
Sperrliste des Spiels treffen, werden ausgeblendet, als gaebe es sie nicht.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from src.net import servertext, servers
from src.net.servers import ServerDef

#: Sekunden zwischen zwei Abfragerunden.
INTERVALL = 5.0
#: Wartezeit je Server. Kuerzer als bei den Strecken: die Liste ist in fuenf
#: Sekunden wieder dran, eine haengende Abfrage soll sie nicht ueberlappen.
TIMEOUT = 4.0
#: Wie viele Runden hintereinander ein Server fehlschlagen darf, bevor seine
#: Lobbys aus der Liste verschwinden. Hamburg hinter dem Tunnel verliert gern
#: einmal eine Antwort; die Liste soll dabei nicht flackern.
FEHLER_GEDULD = 2

#: Fehlerkennung: der Server antwortet auf ``INFO``, kennt aber ``LOBBY_LIST`` nicht
#: (ein aelterer Relay schliesst die Verbindung ohne Antwort). Das ist kein Ausfall.
ZU_ALT = "TOO_OLD"
#: Fehlerkennungen, bei denen der Server nicht (rechtzeitig) antwortet: ausgefallen.
UNERREICHBAR = frozenset({"OFFLINE", "TIMEOUT"})

IM_RENNEN = "racing"
IN_LOBBY  = "lobby"

NAME_MAX = 24
HOST_MAX = 20


@dataclass(frozen=True)
class LobbyEintrag:
    """Eine Zeile der Liste."""
    server:   ServerDef
    code:     str
    name:     str
    host:     str
    players:  int
    max:      int
    status:   str = IN_LOBBY       # IN_LOBBY | IM_RENNEN
    password: bool = False
    mode:     str = ""
    ping_ms:  float | None = None

    @property
    def im_rennen(self) -> bool:
        return self.status == IM_RENNEN

    @property
    def voll(self) -> bool:
        return self.max > 0 and self.players >= self.max

    @property
    def beitretbar(self) -> bool:
        """Offen und mit Platz. Alles andere steht ausgegraut in der Liste."""
        return not self.im_rennen and not self.voll


def _ganz(wert, vorgabe: int, lo: int = 0, hi: int = 99) -> int:
    if isinstance(wert, bool) or not isinstance(wert, int):
        return vorgabe
    return max(lo, min(hi, wert))


def _gesperrt(text: str) -> bool:
    from src.core import profile
    return bool(profile._ist_gesperrt(text))


def eintrag_aus_dict(sd: ServerDef, roh, ping_ms: float | None = None) -> LobbyEintrag | None:
    """Einen Eintrag der Serverantwort prufen und bauen, sonst ``None``.

    Abgelehnt wird, was keine Lobby ist (kein Code in der Form dieses Servers),
    und was auf die Sperrliste trifft.
    """
    if not isinstance(roh, dict):
        return None
    code = roh.get("code")
    if not (isinstance(code, str) and len(code) == 6 and code.isalnum()
            and code[0].upper() == sd.code_prefix):
        return None
    host = servertext.saeubern(roh.get("host"), HOST_MAX, zeilen=False).strip()
    name = servertext.saeubern(roh.get("name"), NAME_MAX, zeilen=False).strip()
    if not host:
        host = "?"
    if not name:
        name = f"Lobby von {host}"[:NAME_MAX].strip()
    if _gesperrt(name) or _gesperrt(host):
        return None
    status = IM_RENNEN if roh.get("status") == IM_RENNEN else IN_LOBBY
    spieler = _ganz(roh.get("players"), 1, 0, 6)
    hoechst = _ganz(roh.get("max"), 0, 0, 6)
    modus = servertext.saeubern(roh.get("mode"), 24, zeilen=False).strip()
    return LobbyEintrag(
        server=sd, code=code.upper(), name=name, host=host, players=spieler,
        max=hoechst, status=status, password=roh.get("password") is True,
        mode=modus, ping_ms=ping_ms,
    )


def sortieren(eintraege: list[LobbyEintrag]) -> list[LobbyEintrag]:
    """Beitretbare zuerst, dann nach Ping (unbekannt zuletzt), dann nach Name."""
    return sorted(eintraege, key=lambda e: (
        not e.beitretbar,
        e.ping_ms if e.ping_ms is not None else float("inf"),
        e.name.lower(), e.code,
    ))


def filtern(eintraege: list[LobbyEintrag], *, nur_beitretbare: bool = False,
            server_id: str = "") -> list[LobbyEintrag]:
    """Die Filter der Seite: nur beitretbare, nur ein Server (leer = alle)."""
    return [e for e in eintraege
            if (not nur_beitretbare or e.beitretbar)
            and (not server_id or e.server.id == server_id)]


def standard_api():
    """Womit abgefragt wird, wenn nichts anderes gegeben ist: ``strecken_client``.

    Eigene Funktion, damit die Testumgebung genau diese eine Stelle abschalten
    kann (``tests/conftest.py``): sonst riefe jede Seite, die im Test ``update``
    erlebt, den echten Relay an.
    """
    from src.net import strecken_client
    return strecken_client


def abfragen(sd: ServerDef, api=None, timeout: float = TIMEOUT) -> list[dict]:
    """Die rohe Liste eines Servers. Blockiert; wirft ``StreckenFehler``.

    Ein Relay ohne die Neuerung schliesst ohne Antwort — das kommt als
    ``UNSUPPORTED`` an (siehe ``strecken_client.anfrage``).
    """
    from src.net import strecken_client
    api = api or standard_api()
    a = api.anfrage(sd, {"type": "LOBBY_LIST"}, timeout)
    if a.get("type") == "LOBBY_ERROR":
        code = str(a.get("code", "ERROR"))
        raise strecken_client.StreckenFehler(
            code, strecken_client.text_fuer(code, str(a.get("reason", ""))))
    if a.get("type") != "LOBBY_LIST" or not isinstance(a.get("lobbies"), list):
        raise strecken_client.StreckenFehler("ANTWORT")
    return a["lobbies"]


class LobbyListe:
    """Die zusammengefuehrte Liste aller Server, im Hintergrund aktuell gehalten.

    ``aktualisieren()`` startet je Server einen Faden (laeuft dort noch einer, wird
    der Server in dieser Runde uebersprungen). ``alle()`` liefert den Stand, ohne
    zu blockieren. Tests setzen ``synchron=True`` und eine eigene ``api``; dann
    laeuft jede Runde im aufrufenden Faden und ohne Netz.
    """

    def __init__(self, api=None, ping_von=None, server_liste=None,
                 synchron: bool = False, info_von=None) -> None:
        self.api = api
        self.synchron = synchron
        self._ping_von = ping_von
        self._info_von = info_von
        self._server_liste = server_liste
        self._lock = threading.Lock()
        self._roh: dict[str, list[dict]] = {}
        #: server_id -> "" (ok) oder die Fehlerkennung der letzten Runde.
        self.fehler: dict[str, str] = {}
        self._fehlrunden: dict[str, int] = {}
        self._laeuft: dict[str, threading.Thread] = {}
        #: Ob schon mindestens ein Server geantwortet hat (oder gescheitert ist).
        self.geladen: set[str] = set()
        self.runden = 0

    # -- Server und Ping -------------------------------------------------------
    def server(self) -> list[ServerDef]:
        return list(self._server_liste() if self._server_liste else servers.all_servers())

    def _ping(self, sd: ServerDef) -> float | None:
        if self._ping_von is not None:
            return self._ping_von(sd)
        from src.net import server_probe
        st = server_probe.get(sd.id)
        if st is None or st.state != server_probe.ONLINE:
            return None
        return st.ping_ms

    def _info_antwortet(self, sd: ServerDef) -> bool:
        """Ob der Server auf ``INFO`` antwortet (blockiert, nur im Arbeitsfaden)."""
        if self._info_von is not None:
            return bool(self._info_von(sd))
        from src.net import server_probe
        host, port, _udp = server_probe.resolve_endpoint(sd)
        return server_probe.probe_tcp(sd, host, port, timeout=TIMEOUT) is not None

    # -- Abfragen --------------------------------------------------------------
    def aktualisieren(self) -> None:
        """Eine Runde: alle Server, parallel."""
        self.runden += 1
        for sd in self.server():
            alt = self._laeuft.get(sd.id)
            if alt is not None and alt.is_alive():
                continue
            if self.synchron:
                self._eine(sd)
            else:
                t = threading.Thread(target=self._eine, args=(sd,), daemon=True,
                                     name=f"lobbyliste-{sd.id}")
                self._laeuft[sd.id] = t
                t.start()

    def _eine(self, sd: ServerDef) -> None:
        try:
            roh = abfragen(sd, self.api)
            fehler = ""
        except Exception as exc:                      # StreckenFehler und alles Unerwartete
            roh, fehler = None, str(getattr(exc, "code", "ERROR"))
            if fehler == "UNSUPPORTED":
                # Verbindung ohne Antwort geschlossen: ein aelterer Relay kennt die
                # Lobbyliste noch nicht -- oder er ist weg. INFO entscheidet.
                try:
                    erreichbar = self._info_antwortet(sd)
                except Exception:
                    erreichbar = False
                fehler = ZU_ALT if erreichbar else "OFFLINE"
        with self._lock:
            self.geladen.add(sd.id)
            if roh is not None:
                self._roh[sd.id] = roh
                self.fehler[sd.id] = ""
                self._fehlrunden[sd.id] = 0
            else:
                self.fehler[sd.id] = fehler
                n = self._fehlrunden.get(sd.id, 0) + 1
                self._fehlrunden[sd.id] = n
                if n >= FEHLER_GEDULD:
                    self._roh.pop(sd.id, None)

    def laeuft_noch(self) -> bool:
        return any(t.is_alive() for t in self._laeuft.values())

    def warten(self, sekunden: float = 5.0) -> None:
        """Nur fuer Tests und Werkzeuge: auf die Faeden warten."""
        for t in list(self._laeuft.values()):
            t.join(sekunden)

    # -- Ergebnis --------------------------------------------------------------
    def alle(self) -> list[LobbyEintrag]:
        """Alle bekannten Lobbys, ungefiltert und unsortiert."""
        with self._lock:
            roh = {k: list(v) for k, v in self._roh.items()}
        out: list[LobbyEintrag] = []
        for sd in self.server():
            ping = self._ping(sd)
            for r in roh.get(sd.id, []):
                e = eintrag_aus_dict(sd, r, ping)
                if e is not None:
                    out.append(e)
        return out

    def ansicht(self, *, nur_beitretbare: bool = False,
                server_id: str = "") -> list[LobbyEintrag]:
        """Was die Seite zeigt: gefiltert und sortiert."""
        return sortieren(filtern(self.alle(), nur_beitretbare=nur_beitretbare,
                                 server_id=server_id))

    def zu_alt(self) -> list[ServerDef]:
        """Server, die erreichbar sind, aber noch keine Lobbyliste kennen."""
        return [s for s in self.server() if self.fehler.get(s.id) == ZU_ALT]

    def ausgefallen(self) -> list[ServerDef]:
        """Server, die gescheitert sind, ohne dass es am Alter liegt."""
        return [s for s in self.server() if self.fehler.get(s.id) and self.fehler[s.id] != ZU_ALT]

    def alle_fehlgeschlagen(self) -> bool:
        """Ob jeder Server geantwortet hat — mit einem Fehler."""
        srv = self.server()
        return bool(srv) and all(self.fehler.get(s.id) for s in srv)
