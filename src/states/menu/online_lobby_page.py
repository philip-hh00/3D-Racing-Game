"""
OnlineLobbyPage — Online multiplayer lobby (Host + Join flow).

Internal views:
    ROLE        pick a side: host a game or join one
    HOST_SERVER relay server list (location, quality bars, ping) + create button
    JOIN        lobby-code input
    CONNECTING  spinner while TCP connects
    LOBBY       waiting room with combined player+AI roster, ready system

The player name is no longer asked for here — it comes from the profile
(settings). Which relay a joining player lands on is derived from the first
character of the lobby code, so guests never have to know where the host is.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pygame

from src.states.menu.page import Page
from src.ui import theme
from src.ui.widgets import Button, Stepper, TextInput, OnScreenKeyboard, ServerRow
from src.ui.focus import FocusGroup
from src.core.i18n import tr
from src.net import payload
from src.states.menu.gp_overview import GPOverview

_ROLE        = "role"
_HOST_SERVER = "host_server"
_JOIN        = "join"
_CONNECTING  = "connecting"
_LOBBY       = "lobby"
#: Grand Prix: eigene Ebene zwischen Lobby und Rennen. Die Lobby richtet
#: die Serie ein, die Uebersicht fuehrt sie.
_GP_OVERVIEW = "gp_overview"

_DIFF_KEYS   = ["easy", "medium", "hard"]
_DIFF_LABELS = [tr("Einfach"), tr("Mittel"), tr("Schwer")]

_MODE_KEYS    = ["Rennen", "Team-Zeitfahren", "Grand Prix"]   # internal values of self._selected_mode
#: Fahrzeuge je Lobby. Team-Zeitfahren braucht gerade Zahlen, deshalb wird
#: die Liste dort auf 4 und 6 eingeschraenkt (siehe _refresh_focus_group).
_SIZE_OPTIONS      = [2, 3, 4, 5, 6]
_SIZE_OPTIONS_TEAM = [4, 6]

#: Leerlauf bis zum Schliessen der Lobby, und wie lange vorher gewarnt wird.
#: Gilt fuer Lobby UND Grand-Prix-Uebersicht - eine vergessene Serie haelt
#: sonst unbegrenzt einen Lobbyplatz auf dem Relay besetzt.
_LOBBY_IDLE_S = 600.0
_LOBBY_WARN_S = 30.0

#: Grenze fuer einen Streckenvorschlag. Dieselbe wie beim Rennstart-Transfer -
#: der Server lehnt alles darueber ohnehin ab.
_OFFER_MAX_B = 1024 * 1024
#: Obergrenze fuer die Summe der empfangenen base64-Stuecke. Bis dahin galt die
#: Grenze nur beim HOCHLADEN: MAP_CHUNK und OFFER_DATA_CHUNK wurden unbegrenzt
#: angehaengt, ein boesartiger oder unterwanderter Relay konnte damit den
#: Arbeitsspeicher des Clients erschoepfen (Releaseplan H2.6). base64 braucht
#: vier Zeichen je drei Byte, dazu etwas Luft fuer Fuellzeichen.
_EMPFANG_MAX_ZEICHEN = (_OFFER_MAX_B * 4) // 3 + 1024
#: Zeilen, die die Auswahlliste gleichzeitig zeigt.
_OFFER_PICK_ROWS = 8

#: Nachrichten, die als Lebenszeichen der Gruppe zaehlen. Ein reiner
#: Verbindungsping darf den Leerlauf nicht zuruecksetzen, sonst laeuft er nie ab.
_AKTIVITAET_MSGS = frozenset({
    "JOIN_OK", "LOBBY_STATE", "PLAYER_LEFT", "MAP_META", "MAP_CHUNK", "MAP_DONE",
    "START", "RESULTS_ENTER",
})

#: Linke Spalte (Host). Wird bei jeder Moduswahl neu gerechnet, siehe
#: _layout_host_column — deshalb stehen die Werte hier und nicht in enter().
_LEFT_X, _LEFT_Y, _LEFT_GAP = 80, 200, 12

_ROSTER_SIZE = 4    # total vehicle slots (host + remote players + AI) — module
                    # default for self._roster_size, which is the live instance
                    # state fed from LOBBY_STATE (see §1 of online_team_tt_plan.md)
_RX          = 960  # right panel x origin
# Row layout constants (derived from right-panel header geometry)
_ROW_H       = 56
_ROW_GAP     = 12
_ROW_STRIDE  = _ROW_H + _ROW_GAP       # 68 px
_ROW_START_Y = 351                      # y of first roster row
# Column x offsets (relative to _RX) — _COL_DIFF/_COL_VEH were nudged left (and
# their AI-row stepper widths shrunk to match) to make room for _COL_TEAM so
# all four columns fit within the ~850px-wide roster row.
_COL_NAME    = 0
_COL_VEH     = 230
_COL_DIFF    = 480
_COL_TEAM    = 700


def _track_name_from_path(path: str) -> str:
    if not path:
        return "—"
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return tr(d.get("name") or os.path.splitext(os.path.basename(path))[0].replace("_", " ").title())
    except Exception:
        return tr(os.path.splitext(os.path.basename(path))[0].replace("_", " ").title())


def _vehicle_display_name(key: str) -> str:
    from src.entities.vehicle_factory import VehicleFactory
    cfg = VehicleFactory.get_config(key)
    return tr(cfg.name) if cfg else key.title()


class OnlineLobbyPage(Page):

    #: Seitenzeit und Ablauf der kurzen Meldung — als Klassenvorgaben, nicht
    #: erst in ``enter``. ``_melde`` liest beide, und ``_melde`` wird auch aus
    #: Wegen gerufen, die ohne vollstaendig betretene Seite auskommen (der
    #: Empfangspuffer etwa, der nur ``_msg`` braucht). Ohne Vorgabe haengt eine
    #: Meldung an einem Attribut, das es zu dem Zeitpunkt noch nicht gibt.
    _time: float = 0.0
    _msg_until: float = 0.0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def enter(self, shell, **kwargs) -> None:
        self.shell      = shell
        self._view      = _ROLE
        self._msg       = ""
        #: Zeitpunkt (Seitenzeit), an dem eine kurze Meldung verfaellt. 0 = bleibt.
        self._msg_until = 0.0
        self.osk: OnScreenKeyboard | None = None
        self._time      = 0.0
        self._is_host   = False
        self._lobby_id  = ""
        self._players: list[dict] = []
        self._lobby_ready = False
        self._lobby_timer = 0.0    # Leerlaufzeit, siehe _LOBBY_IDLE_S
        self._warn_msg    = ""     # Vorwarnung kurz vor dem Schliessen
        self._race_begun = False   # guards against a duplicate "START" broadcast

        # AI roster widgets (rebuilt as players join/leave; host only).
        # Each tuple is (vehicle stepper, difficulty stepper, team stepper|None) —
        # the team stepper only exists while self._selected_mode == "Team-Zeitfahren".
        self._roster_ai_widgets: list[tuple[Stepper, Stepper, Stepper | None]] = []
        self._roster_free_slots: list[int] = []
        self._team_stepper: Stepper | None = None   # own player's team stepper (roster row)

        # Selections
        from src.core import race_setup
        s = race_setup.current()
        # Online uses the full vehicle roster — don't inherit a class filter that
        # may have been set in the single-player lobby.
        s.vehicle_class = "Alle"
        self._selected_track_path = s.track_path
        self._selected_vehicle    = s.player_vehicle
        self._selected_difficulty = s.ai_difficulty
        self._selected_laps       = s.laps

        self._roster_size    = _ROSTER_SIZE
        self._selected_mode  = "Rennen"        # "Rennen" | "Team-Zeitfahren"
        self._selected_class = "Alle"          # "Alle" == Automatisch
        self._my_team        = "A"
        self._team_balance   = {"A": 0, "B": 0, "ok": True}
        # Zuletzt vom Host verteilter Serienzustand (Grand Prix). Auch der
        # Host liest ihn von hier, damit Anzeige und Verteilung nie auseinanderlaufen.
        self._gp_view: dict = {}
        self._gp_ui: GPOverview | None = None
        self._gp_phase: str = "lobby"   # lobby | overview
        #: Rueckfrage vor dem Verlassen. _dialog_aktion sagt, welche - Lobby
        #: und Serie enden unterschiedlich, die Antwort "ok" allein reicht nicht.
        self._dialog = None
        self._dialog_aktion = ""
        #: Was nach einem bestaetigten "Ja" noch zu tun ist - etwa der
        #: Tabwechsel, der die Rueckfrage ueberhaupt ausgeloest hat.
        self._dialog_danach = None
        #: Ob fuer diese Sitzung schon ein Gastgeber-Erfolg gezaehlt wurde.
        self._gastgeber_gezaehlt = False
        #: Serienwertung online (E1a). Gezaehlt wird erst, wenn diese Seite die
        #: Serie **laufen** gesehen hat - wer sich nur in eine fertige Wertung
        #: einklinkt, hat sie nicht gefahren.
        self._gp_lief = False
        self._gp_sieg_gebucht = False
        # ["Alle"] + concrete class names — "Alle" (index 0) doubles as both the
        # internal value AND the display option "Automatisch" (see plan §6.1).
        self._class_keys_list = ["Alle"] + [c for c in race_setup.CLASS_NAMES if c != "Alle"]

        # ── Streckenvorschlaege (Block G) ────────────────────────────────────
        #: Was in der Lobby liegt: [{"slot","name","size","from"}]. Kommt vom
        #: Relay, der die Vorschlaege fuer die Lebensdauer der Lobby haelt.
        self._offers: list[dict] = []
        #: Schalter des Hosts. Standardmaessig aus - niemand soll ungefragt
        #: Dateien in eine fremde Runde legen koennen.
        self._offers_enabled = False
        self._offer_chunks: list[str] = []   # laufender Empfang
        self._offer_name = ""
        self._offer_busy = ""                # Name der gerade hochgeladenen Strecke
        #: Auswahlliste beim Anbieten: [(titel, pfad, groesse)] oder None.
        self._offer_pick: list[tuple[str, str, int]] | None = None
        self._offer_pick_group: FocusGroup | None = None
        self._offer_rows: list = []          # Knoepfe der Zeilen
        self._offer_pick_cursor = 0          # gewaehlte Zeile
        self._offer_pick_offset = 0          # oberste sichtbare Zeile

        # Online custom-track transfer (guest side)
        self._map_chunks: list[str] = []
        self._map_name: str = ""
        self._custom_track_local: str | None = None   # our own copy of the host's custom track
        self._srv_track_path: str | None = None       # last track_path the server sent us

        # ── Server selection state ───────────────────────────────────────────
        from src.net import servers, server_probe
        self._server_defs      = servers.all_servers()
        self._selected_srv_id: str | None = None
        self._connect_server   = None    # ServerDef the live session belongs to
        # Where ESC / a failed connect returns to (host list vs code input).
        self._return_view      = _ROLE

        cx = 960

        # ── ROLE widgets ─────────────────────────────────────────────────────
        self._btn_role_host = Button(
            pygame.Rect(cx - 300, 300, 600, 76), tr("Spiel hosten") + "  ›", "role_host"
        )
        self._btn_role_join = Button(
            pygame.Rect(cx - 300, 400, 600, 76), tr("Spiel beitreten") + "  ›", "role_join",
            style="secondary",
        )
        self._role_group = FocusGroup([self._btn_role_host, self._btn_role_join])

        # ── HOST_SERVER widgets ──────────────────────────────────────────────
        # list_y liegt unter Titel (176) und Unterschrift (226) plus Platz für
        # die Spaltenüberschriften, die 30 px über der ersten Zeile sitzen.
        row_h, row_gap, list_y = 68, 14, 300
        self._server_rows = [
            ServerRow(pygame.Rect(cx - 420, list_y + i * (row_h + row_gap), 840, row_h),
                      sd.label, f"pick_{sd.id}")
            for i, sd in enumerate(self._server_defs)
        ]
        create_y = list_y + len(self._server_rows) * (row_h + row_gap) + 34
        self._btn_back_host = Button(
            pygame.Rect(cx - 420, create_y, 300, 64), "‹  " + tr("Zurück"), "back_role",
            style="secondary"
        )
        self._btn_create = Button(
            pygame.Rect(cx + 120, create_y, 300, 64), tr("Lobby erstellen") + "  ›", "create"
        )
        self._btn_create.enabled = False
        self._btn_create.focusable = False
        self._host_group = FocusGroup(self._server_rows + [self._btn_back_host, self._btn_create])

        # ── JOIN widgets ─────────────────────────────────────────────────────
        self._code_input = TextInput(
            pygame.Rect(cx - 300, 320, 600, 64), text="", max_len=6,
            allowed="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", uppercase=True,
        )
        self._btn_back_join = Button(
            pygame.Rect(cx - 300, 452, 280, 64), "‹  " + tr("Zurück"), "back_role",
            style="secondary"
        )
        self._btn_join = Button(
            pygame.Rect(cx + 20, 452, 280, 64), tr("Beitreten") + "  ›", "join"
        )
        self._join_group = FocusGroup([self._code_input, self._btn_back_join, self._btn_join])

        server_probe.start()

        # ── LOBBY left-panel widgets ───────────────────────────────────────────
        x, w, h, gap = 80, 700, 56, 12
        y = 200

        self._mode_stepper = Stepper(
            pygame.Rect(0, 0, w, h), tr("Spielmodus"),
            [tr("Rennen"), tr("Team-Zeitfahren"), tr("Grand Prix")],
            _MODE_KEYS.index(self._selected_mode) if self._selected_mode in _MODE_KEYS else 0,
            action="set_mode",
        )
        self._size_stepper = Stepper(
            pygame.Rect(0, 0, w, h), tr("Fahrzeuge"),
            [str(n) for n in _SIZE_OPTIONS],
            _SIZE_OPTIONS.index(self._roster_size) if self._roster_size in _SIZE_OPTIONS else 0,
            action="set_size",
        )
        self._class_stepper = Stepper(
            pygame.Rect(0, 0, w, h), tr("Fahrzeugklasse"),
            [tr("Beliebig")] + [tr(c) for c in self._class_keys_list[1:]],
            self._class_keys_list.index(self._selected_class)
            if self._selected_class in self._class_keys_list else 0,
            action="set_class",
        )

        self._gp_races_stepper = Stepper(
            pygame.Rect(0, 0, w, h), tr("Rennen (Grand Prix)"),
            [str(n) for n in range(3, 11)], 1, action="set_gp_races",
        )
        self._laps_stepper = Stepper(
            pygame.Rect(0, 0, w, h), "Runden",
            [str(n) for n in range(1, 11)], self._selected_laps - 1,
        )
        self._diff_stepper = Stepper(
            pygame.Rect(0, 0, w, h), "KI-Schwierigkeit",
            _DIFF_LABELS,
            _DIFF_KEYS.index(self._selected_difficulty)
            if self._selected_difficulty in _DIFF_KEYS else 1,
        )
        self._btn_track   = Button(pygame.Rect(0, 0, w, h),
                                   tr("Strecke wählen") + "  ›", "pick_track")
        self._btn_vehicle = Button(pygame.Rect(0, 0, w, h),
                                   tr("Fahrzeug wählen") + "  ›", "pick_vehicle")
        self._btn_ready   = Button(pygame.Rect(0, 0, w, h),
                                   tr("Bereit"), "toggle_ready")
        self._btn_start   = Button(pygame.Rect(0, 0, w, h),
                                   tr("RENNEN STARTEN") + "  ›", "start")

        self._layout_host_column()

        # Client layout (fewer controls)
        self._btn_vehicle_c = Button(pygame.Rect(0, 0, w, h),
                                     tr("Fahrzeug wählen") + "  ›", "pick_vehicle")
        self._btn_ready_c   = Button(pygame.Rect(0, 0, w, h),
                                     tr("Bereit"), "toggle_ready")

        col_c = theme.Column(x, 390, gap=gap)
        col_c.add(self._btn_vehicle_c)
        col_c.skip(16)
        col_c.add(self._btn_ready_c)


        self._lobby_group = FocusGroup([])  # rebuilt after JOIN_OK / roster change

        from src.net import session
        session.set_lobby_page(self)

        from src.net import server_info
        server_info.fetch_info_async()

    def hides_tab_bar(self) -> bool:
        """Die Grand-Prix-Uebersicht ist eine eigene Ebene, keine Menueseite.
        Ein Klick auf einen Tab wuerde die Netzsitzung verwerfen und die Serie
        fuer alle beenden - also zeigt die Shell dort keine Leiste."""
        return self._view == _GP_OVERVIEW

    def verlassen_erlaubt(self, weiter) -> bool:
        """In der Lobby haengt an einem Tabwechsel die ganze Sitzung.

        Die Leiste ist hier sichtbar und muss deshalb auch reagieren - vorher
        verschluckte die Seite den Klick wortlos (gemeldet 02.08.2026). Statt
        stillschweigend die Verbindung zu kappen (beim Host: die Lobby fuer
        alle), fragt sie dasselbe wie der Zurueck-Weg und geht erst dann weiter.
        """
        if self._view == _CONNECTING:
            self._cleanup_net()
            return True
        if self._view != _LOBBY:
            return True
        self._dialog_danach = weiter
        self._ask_leave_lobby()
        return False

    def on_return_from_select(self) -> None:
        """Called by MenuShellState when returning from car_select or track_select."""
        from src.core import race_setup
        s = race_setup.current()
        self._selected_vehicle    = s.player_vehicle
        if self._is_host:
            # Only the host owns the track selection; a guest's local
            # race_setup.track_path is stale and must not clobber the
            # server-synced value.
            self._selected_track_path = s.track_path
        self._btn_vehicle.label   = tr("Fahrzeug: {v}").format(v=_vehicle_display_name(self._selected_vehicle)) + "  ›"
        self._btn_vehicle_c.label = self._btn_vehicle.label
        self._btn_track.label     = tr("Strecke: {t}").format(t=_track_name_from_path(self._selected_track_path)) + "  ›"
        if self._is_host and self._view == _LOBBY:
            self._push_settings()
            self._push_pick()
        elif not self._is_host and self._view == _LOBBY:
            self._push_pick()

    def resume_after_race(self) -> None:
        """Return to the pre-race lobby view after a finished online race,
        reusing the still-connected session so everyone stays in the lobby."""
        self._view       = _LOBBY
        self._race_begun = False          # allow starting the next race
        self._lobby_ready = False
        self._msg        = ""
        self._update_ready_button_labels()
        self._build_lobby_group()
        self._update_button_labels()
        # Grand Prix: die Gruppe kehrt in die Uebersicht zurueck, nicht in die
        # Lobby - dort waehlt der Host die naechste Strecke. Beim Host zaehlt
        # dafuer seine eigene Serie, nicht der verteilte Stand: der kann vom
        # Server umgeschrieben worden sein (siehe _ist_gp_modus).
        from src.core import grand_prix as _gp
        if self._gp_view.get("gp_active") or (self._is_host and _gp.is_active()):
            self._enter_gp_overview()

        # Der Host schaltet die Serie weiter und verteilt den neuen Stand.
        # Ist die Serie durch, bleibt sie stehen bis er sie beendet.
        if self._is_host:
            from src.core import grand_prix
            gp = grand_prix.current()
            if gp and not gp.is_finished:
                gp.next_race()
            if gp:
                self._push_settings()

        from src.net import session
        net = session.get()
        if net:
            # Un-ready everyone so the next race requires a fresh "Bereit".
            net.send_tcp({"type": "LOBBY_UNREADY"})

    def request_restart(self) -> None:
        """Host rematch from the results screen: same settings, immediate start.
        Skips the lobby-ready gate — guests are brought along by the regular
        MAP_META/START flow (their results screen keeps the network pumped)."""
        if not self._is_host:
            return
        self._msg = ""
        self._race_begun = False
        self._request_start(force=True)

    def send_rematch_ready(self) -> None:
        """Guest on the results screen votes for a rematch: mark ourselves
        lobby-ready so everyone sees it in the roster/results table."""
        from src.net import session
        net = session.get()
        if net is None or self._lobby_ready:
            return
        self._lobby_ready = True
        self._update_ready_button_labels()
        net.send_tcp({"type": "LOBBY_READY"})

    def rematch_status(self) -> tuple[int, int, dict, list, bool]:
        """Rematch-vote info for the results screen.

        Returns (voted, total, ready_by_raw_slot, sorted_raw_slots, all_present).
        The rematch is a UNANIMOUS vote, so every connected player counts — the
        host included, not just the guests. voted = players who pressed "Nochmal
        fahren" (lobby_ready); ready_by_raw_slot maps each raw network slot ->
        voted; sorted_raw_slots translates rank-slots in result rows back to raw
        slots; all_present is True only while every player is still on the
        results screen (on_results), so a player who went back to the lobby or
        left disables the rematch for everyone."""
        ready_by_slot = {}
        total = 0
        voted = 0
        all_present = bool(self._players)
        for p in self._players:
            slot = p.get("slot", 0)
            rd = bool(p.get("lobby_ready", False))
            ready_by_slot[slot] = rd
            total += 1
            if rd:
                voted += 1
            if not p.get("on_results", False):
                all_present = False
        return voted, total, ready_by_slot, sorted(ready_by_slot.keys()), all_present

    def enter_results_vote(self) -> None:
        """Landed on the results screen: announce presence and clear any stale
        vote so the rematch starts from a fresh, unanimous count."""
        from src.net import session
        net = session.get()
        self._lobby_ready = False
        if net:
            net.send_tcp({"type": "RESULTS_ENTER"})
            net.send_tcp({"type": "LOBBY_UNREADY"})

    def leave_results_vote(self) -> None:
        """Left the results screen (back to lobby / exit): drop our presence so
        nobody can start a rematch that would exclude us."""
        from src.net import session
        net = session.get()
        if net:
            net.send_tcp({"type": "RESULTS_LEAVE"})

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        self._time += dt
        if self._msg_until and self._time >= self._msg_until:
            self._msg = ""
            self._msg_until = 0.0
        self._code_input.update(dt)
        if self.osk:
            self.osk.update(dt)
        if self._view in (_ROLE, _HOST_SERVER, _JOIN):
            # Keeps the probe thread alive (it self-terminates once nobody reads
            # the results, since pages are popped without an exit hook).
            from src.net import server_probe
            server_probe.start()
            self._refresh_server_rows()
        # Die Grand-Prix-Uebersicht gehoert hier dazu: sie ist eine eigene Ebene,
        # aber dieselbe Netzsitzung. Ohne sie holte der Host START nie ab und
        # blieb auf "Uebertrage Strecke ..." stehen, waehrend die Gaeste losfuhren.
        if self._view in (_LOBBY, _CONNECTING, _GP_OVERVIEW):
            from src.net import session
            net = session.get()
            if net:
                # Kein net.update(dt) mehr: der Keepalive haengt seit dem
                # 07.08.2026 an der Zustandsmaschine und laeuft damit auch,
                # waehrend der Spieler in der Fahrzeugauswahl steht. Hier
                # bliebe er stehen, sobald diese Seite nicht die aktive ist —
                # und genau daran ist ein Gast aus der Lobby geflogen.
                for evt in net.poll():
                    self._on_net(evt)

        if self._view in (_LOBBY, _GP_OVERVIEW):
            # Leerlauf, nicht Gesamtdauer: der Timer zaehlt nur, solange niemand
            # etwas tut, und faengt bei jeder Eingabe und jeder Servernachricht
            # von vorn an (siehe _lobby_aktivitaet). Vorher war es eine harte
            # Obergrenze - eine Lobby starb nach 10 Minuten auch dann, wenn die
            # ganze Zeit jemand Einstellungen drehte.
            self._lobby_timer += dt
            if self._lobby_timer >= _LOBBY_IDLE_S:
                self._cleanup_net()
                self._view = _ROLE
                self._msg = tr("Lobby nach {m} Minuten ohne Aktivität geschlossen.").format(
                    m=int(_LOBBY_IDLE_S // 60))
                self._lobby_timer = 0.0
            elif self._lobby_timer >= _LOBBY_IDLE_S - _LOBBY_WARN_S:
                self._warn_msg = tr("Lobby schließt in {s} Sekunden — noch jemand da?").format(
                    s=max(1, int(_LOBBY_IDLE_S - self._lobby_timer)))
            else:
                self._warn_msg = ""

        if self._view == _LOBBY:
            # Show min 2 players status message dynamically
            if len(self._players) < 2:
                self._msg = "Mindestens 2 Spieler erforderlich."
            elif self._msg == "Mindestens 2 Spieler erforderlich.":
                self._msg = ""
        elif self._view != _GP_OVERVIEW:
            self._lobby_timer = 0.0
            self._warn_msg = ""

    # ── Network ───────────────────────────────────────────────────────────────

    def _melde(self, text: str, dauer: float = 5.0) -> None:
        """Kurze Rückmeldung, die von selbst wieder verschwindet.

        „Lade hoch …" und „Gespeichert als …" sind Zwischenstände, keine
        Zustände: ohne Ablauf standen sie für den Rest der Sitzung in der
        Übersicht, lange nachdem sie nichts mehr beschrieben.
        """
        self._msg = text
        self._msg_until = self._time + dauer

    def _lobby_aktivitaet(self) -> None:
        """Leerlaufzaehler zuruecksetzen — jemand hat etwas getan."""
        self._lobby_timer = 0.0
        self._warn_msg    = ""

    @staticmethod
    def _servertext(roh, vorgabe: str) -> str:
        """Eine Begruendung vom Relay anzeigefertig machen (Block H, H2.12).

        Jeder Text, den der Relay schickt und das Spiel zeigt, laeuft hier durch:
        Laenge und Zeichen begrenzt, unsichtbare Richtungszeichen entfernt. Danach
        durch ``tr``, damit die bekannten Saetze weiter uebersetzt werden.
        """
        from src.net import servertext
        sauber = servertext.saeubern(roh, 200, zeilen=False)
        return tr(sauber) if sauber else tr(vorgabe)

    def _on_net(self, evt: dict) -> None:
        src  = evt.get("source")
        data = evt.get("data", {})
        if evt.get("source") == "tcp" and data.get("type") in _AKTIVITAET_MSGS:
            self._lobby_aktivitaet()

        if src == "error":
            reason = data.get("reason", "")
            if data.get("type") == "CONNECT_ERROR":
                self._msg = tr("Verbindung fehlgeschlagen: {r}").format(r=reason)
            else:
                self._msg = "Verbindung zum Server getrennt."
            self._view = self._return_view
            self._cleanup_net()
            return

        if src != "tcp":
            return

        t = data.get("type")

        if t == "JOIN_OK":
            self._lobby_id    = data.get("lobby_id", "")
            self._is_host     = data.get("is_host", False)
            self._msg         = ""
            self._view        = _LOBBY
            self._lobby_ready = False
            # Neue Lobby, neue Vorschlaege. Die Seite ueberlebt einen
            # Lobbywechsel, also blieb sonst die Liste der letzten stehen —
            # sichtbar nur fuer einen selbst, denn der Server hat sie nie
            # geschickt.
            self._offers = []
            self._offer_busy = ""
            self._offer_chunks = []
            self._offer_name = ""
            self._close_offer_picker()
            from src.net import session
            net = session.get()
            if net:
                # Das Sitzungstoken kommt mit JOIN_OK und gehoert ab hier zu
                # jeder UDP-Registrierung (Block H, H2.1). Ein Relay ohne die
                # Neuerung schickt keines; dann bleibt es leer, und dort greift
                # weiter nur die IP-Pruefung.
                net.set_lobby(self._lobby_id, data.get("slot", -1),
                              str(data.get("udp_token", "")))
                net.register_udp()
            self._build_lobby_group()
            self._update_button_labels()
            if self._is_host:
                self._push_settings()
            self._push_pick()

        elif t == "JOIN_FAIL":
            if data.get("code") == "VERSION_MISMATCH":
                req = data.get("required_version", "?")
                from src.core.version import VERSION
                self._msg = tr("Deine Spielversion {v} ist veraltet. Bitte lade die aktuelle Version {r} herunter.").format(v=VERSION, r=req)
            else:
                # Auch die Begruendung kommt vom Relay und wird angezeigt — sie
                # wird genauso gesaeubert wie eine Ankuendigung (H2.12).
                self._msg = self._servertext(data.get("reason"),
                                             "Beitritt fehlgeschlagen.")
            self._view = self._return_view
            self._cleanup_net()

        elif t == "LOBBY_STATE":
            old_slots = frozenset(p["slot"] for p in self._players)
            # Geprüft statt roh übernommen: sechs Stellen greifen später ohne
            # Absicherung auf p["slot"] zu. Ein Eintrag ohne brauchbaren Slot
            # oder eine "players"-Liste, die gar keine Liste ist, beendete
            # sonst die ganze Menüseite. Regel liegt in src/net/payload.py,
            # damit Menü und Rennen dieselbe benutzen.
            self._players = payload.players(data.get("players"))
            new_slots = frozenset(p["slot"] for p in self._players)
            # Gastgeber-Erfolg (E1a): eine Lobby zaehlt erst, wenn jemand
            # gekommen ist. Eine Lobby aufmachen und allein darin sitzen ist
            # kein Gastgeben.
            if (self._is_host and not self._gastgeber_gezaehlt
                    and len(new_slots) > 1):
                self._gastgeber_gezaehlt = True
                from src.core import statistik
                statistik.lobby_gehostet()

            # Roster size / mode / team balance are server-authoritative for
            # BOTH host and guest — see plan §4.3/§6.1.
            old_roster_size = self._roster_size
            old_mode        = self._selected_mode
            self._roster_size   = payload.as_int(data.get("roster_size"), self._roster_size)
            self._selected_mode = data.get("mode", self._selected_mode)
            self._team_balance  = data.get("team_balance", self._team_balance)
            self._update_start_button_state()

            from src.net import session as _session
            _net = _session.get()
            my_slot = _net.slot if _net else -1
            for p in self._players:
                if p.get("slot") == my_slot:
                    self._my_team = p.get("team", self._my_team)
                    # The server clears everyone's "Bereit" whenever the mode,
                    # roster, track, laps, class or a team changes. Without
                    # mirroring that here the button would keep claiming we are
                    # ready while the server has already dropped us.
                    self._lobby_ready = bool(p.get("lobby_ready", self._lobby_ready))
                    break
            self._update_ready_button_labels()
            if self._team_stepper is not None:
                self._team_stepper.index = 1 if self._my_team == "B" else 0

            # Serienzustand kommt für ALLE aus den Servereinstellungen — beim
            # Host aus seiner eigenen Serie, bei Gästen aus dem, was der Host
            # zuletzt geschickt hat. Gäste führen keine eigene Serie.
            srv_all = data.get("settings")
            lief_serie = bool(self._gp_view.get("gp_active"))
            boten_vorher = self._offers_aktiv()
            self._gp_view = srv_all if isinstance(srv_all, dict) else {}
            self._gp_sieg_pruefen()
            # Der Schalter fuer Streckenvorschlaege reist in den Einstellungen
            # mit. Der gezeichnete Text liest direkt aus _gp_view und aendert
            # sich damit sofort — die Knoepfe aber entstehen in
            # _build_gp_group, und die wurde auf diesem Weg nie gerufen.
            # Gebaut wurde beim Betreten der Uebersicht, beim Serienende und
            # bei OFFER_LIST; letzteres kommt erst, wenn jemand wirklich
            # hochlaedt. Ein Gast las deshalb "Vorschlaege: An" und hatte
            # keinen Knopf, um selbst etwas anzubieten, bis der Host als
            # erster eine Strecke schickte (gemeldet 07.08.2026).
            #
            # Nur beim echten Wechsel, nicht bei jedem Zustand: ein Neubau
            # setzt die Fokusgruppe zurueck, und der Host verteilt seine
            # Einstellungen bei jeder Kleinigkeit.
            if (self._view == _GP_OVERVIEW
                    and self._offers_aktiv() != boten_vorher):
                self._build_gp_group()
            # Beendet der Gastgeber die Serie, waehrend ein Gast in der Lobby
            # steht, faellt ihm sonst gar nichts auf - die Uebersicht, aus der
            # er herausgeholt wuerde, sieht er ja gerade nicht.
            if (not self._is_host and lief_serie
                    and not self._gp_view.get("gp_active")
                    and self._view != _GP_OVERVIEW):
                self._melde(tr("Der Gastgeber hat den Grand Prix beendet."))

            # Gaeste folgen der Ebene, die der Host verteilt. Ohne das saessen
            # sie in der Lobby, waehrend der Host die Strecke waehlt.
            if not self._is_host and self._view in (_LOBBY, _GP_OVERVIEW):
                # Nur beim tatsaechlichen Wechsel eintreten. _enter_gp_overview
                # setzt "Bereit" bewusst zurueck; auf jede LOBBY_STATE angewandt
                # nahm es dem Gast seine eigene Meldung sofort wieder weg - der
                # Host konnte den Lauf dann nie starten.
                #
                # Die Phase steht bewusst NICHT mehr in der Bedingung: laeuft
                # eine Serie, gehoert ein Gast in die Uebersicht und nicht in
                # die Lobby - auch nach einem Wiedereinstieg, bei dem der Host
                # gerade nichts Neues verteilt.
                if self._gp_view.get("gp_active") and self._view != _GP_OVERVIEW:
                    self._enter_gp_overview()
                elif (self._view == _GP_OVERVIEW and self._gp_ist_beendet()
                        and self._btn_gp_ready.enabled):
                    # Das Serienende kam gerade herein - der noch bediente
                    # Bereit-Knopf verraet die alte Leiste. Umbauen, sonst
                    # stuenden Bereit und Start da, als ginge es weiter.
                    self._build_gp_group()
                elif self._view == _GP_OVERVIEW and not self._gp_view.get("gp_active"):
                    self._leave_gp_overview()

            if not self._is_host:
                srv = data.get("settings", {})
                if not isinstance(srv, dict):
                    srv = {}
                srv_tp = srv.get("track_path")
                if srv_tp and srv_tp != self._srv_track_path:
                    # Host switched track — any custom copy we received is stale.
                    self._srv_track_path      = srv_tp
                    # Der Pfad kommt vom Host und ist damit nicht
                    # vertrauenswuerdig. Ungeprueft landete er in find_track,
                    # das ihn ZUERST roh probiert — auch absolut. Ein Host
                    # konnte damit "/etc/passwd" oder "C:/Windows/win.ini"
                    # schicken und am Verhalten des Gastes ablesen, ob die Datei
                    # existiert (Releaseplan H2.10). Gebraucht wird ohnehin nur
                    # der Dateiname: find_track sucht ihn in allen
                    # Streckenordnern, und eine eigene Strecke des Hosts kommt
                    # ueber den Rennstart-Transfer.
                    from src.core import paths as _p
                    self._selected_track_path = _p.safe_track_filename(
                        str(srv_tp), fallback="online_track.json")
                    self._custom_track_local  = None
                if "laps" in srv:
                    self._selected_laps = int(srv.get("laps", 3))
                    self._laps_stepper.index = max(0, min(9, self._selected_laps - 1))
                if "ai_difficulty" in srv:
                    self._selected_difficulty = srv.get("ai_difficulty", "medium")
                    if self._selected_difficulty in _DIFF_KEYS:
                        self._diff_stepper.index = _DIFF_KEYS.index(self._selected_difficulty)
                if "vehicle_class" in srv:
                    self._selected_class = srv.get("vehicle_class", "Alle")
                    self._enforce_vehicle_class()
                    if self._selected_class in self._class_keys_list:
                        self._class_stepper.index = self._class_keys_list.index(self._selected_class)
                if self._selected_mode in _MODE_KEYS:
                    self._mode_stepper.index = _MODE_KEYS.index(self._selected_mode)
                # Gaeste sehen die Zahl nur; sie kommt vom Host. Gerichtet wird
                # sie ueber dieselbe Stelle wie beim Host, damit beide dieselbe
                # Auswahl zeigen.
                self._groessenwahl_richten()
                ai_roster_data = srv.get("ai_roster")
                if ai_roster_data is not None:
                    from src.core.race_setup import AIDriver
                    from src.core import race_setup as _rs
                    _rs.current().ai_roster = [
                        AIDriver(name=d.get("name", "KI"),
                                 vehicle=d.get("vehicle", "random"),
                                 difficulty=d.get("difficulty", "medium"),
                                 team=d.get("team", "A"))
                        for d in ai_roster_data
                    ]
                    self._rebuild_roster_widgets()
                    self._refresh_focus_group()

            if old_slots != new_slots and self._is_host:
                self._sync_ai_roster()
                self._rebuild_roster_widgets()
                self._refresh_focus_group()
                self._push_settings()   # propagate regenerated roster names to clients

            if self._roster_size != old_roster_size or self._selected_mode != old_mode:
                if self._is_host:
                    self._sync_ai_roster()
                self._rebuild_roster_widgets()
                self._refresh_focus_group()

        elif t == "LOBBY_CLOSED":
            self._msg = self._servertext(data.get("reason"), "Lobby geschlossen.")
            self._view = _ROLE
            self._cleanup_net()

        elif t == "PLAYER_LEFT":
            slot = data.get("slot")
            old_slots = frozenset(p["slot"] for p in self._players)
            self._players = [p for p in self._players if p.get("slot") != slot]
            new_slots = frozenset(p["slot"] for p in self._players)
            if old_slots != new_slots and self._is_host:
                self._sync_ai_roster()
                self._rebuild_roster_widgets()
                self._refresh_focus_group()

        elif t == "MAP_META":
            # Custom track: a transfer is starting — buffer the incoming chunks.
            # Built-in track: everyone confirms with READY — except the host, who
            # was already marked ready server-side when it sent START_REQUEST.
            if data.get("is_custom", False):
                if not self._is_host:
                    self._map_chunks = []
                    self._map_name   = data.get("track_name") or "online_track.json"
                    # Drop the previous race's local copy so a failed/partial new
                    # transfer can't make _begin_race silently reuse the old track.
                    self._custom_track_local = None
                    self._melde("Empfange Strecke …", 30.0)
            elif not self._is_host:
                # Built-in track: no transfer. Drop any stale custom-transfer name
                # so _begin_race's self-heal can't latch onto a previous race's
                # online copy instead of this bundled track.
                self._map_name = None
                self._custom_track_local = None
                from src.net import session
                net = session.get()
                if net:
                    net.send_tcp({"type": "READY"})

        elif t == "MAP_CHUNK":
            if not self._is_host:
                self._stueck_anhaengen(self._map_chunks, data.get("data", ""),
                                       "Strecke")

        elif t == "MAP_DONE":
            if not self._is_host:
                if self._map_chunks:
                    self._save_received_map()
                else:
                    self._melde(tr("Strecke wurde nicht empfangen."), 10.0)

        elif t == "OFFER_LIST":
            self._offers = payload.dict_entries(data.get("offers"))
            if self._offer_busy:
                # Bestaetigung statt eines "Lade hoch ...", das einfach
                # stehenbliebe: die Liste ist der Beweis, dass es angekommen ist.
                self._melde(tr("{n} liegt jetzt in der Lobby.").format(n=self._offer_busy))
                self._offer_busy = ""
            if self._view == _GP_OVERVIEW:
                # Die Knoepfe haengen an der Zeilenzahl - eine Liste, die sich
                # aendert, braucht eine neue Leiste.
                self._build_gp_group()

        elif t == "OFFER_DATA_META":
            self._offer_chunks = []
            self._offer_name = str(data.get("track_name") or "strecke.json")
            self._melde(tr("Empfange {n} …").format(n=self._offer_name), 30.0)

        elif t == "OFFER_DATA_CHUNK":
            self._stueck_anhaengen(self._offer_chunks, data.get("data", ""),
                                   "Vorschlag")

        elif t == "OFFER_DATA_DONE":
            self._save_offer()

        elif t == "START":
            self._begin_race(data)

        elif t == "ERROR":
            if data.get("code") == "TEAM_UNBALANCED":
                # Server sends the counts separately so the sentence stays
                # translatable instead of arriving pre-formatted in German.
                self._msg = tr("Teams nicht ausgeglichen (A: {a}, B: {b}).").format(
                    a=data.get("a", "?"), b=data.get("b", "?"))
            else:
                self._msg = self._servertext(data.get("reason"), "Server-Fehler.")

    # ── Roster management ───────────────────────────────────────────────────────
    # _sync_ai_roster / _rebuild_roster_widgets' AI-stepper branch are host-only;
    # the own-player team stepper built in _rebuild_roster_widgets applies to
    # host AND guest alike (everyone picks their own team).

    # ── Fahrzeugzahl ──────────────────────────────────────────────────────────
    # Drei Dinge muessen zusammenpassen: welche Zahlen der Modus zulaesst, welche
    # gilt, und was der Stepper zeigt. Sie liefen auseinander (gemeldet
    # 04.08.2026), deshalb steht jede Aussage darueber jetzt genau hier.

    def _groessen(self) -> list[int]:
        """Welche Fahrzeugzahlen dieser Modus zulaesst.

        Team-Zeitfahren nur gerade Zahlen — sonst liessen sich die Teams nicht
        gleich gross besetzen.
        """
        if self._selected_mode == "Team-Zeitfahren":
            return list(_SIZE_OPTIONS_TEAM)
        return list(_SIZE_OPTIONS)

    def _groessenwahl_richten(self) -> None:
        """Den Stepper auf die Auswahl des Modus und den geltenden Wert bringen.

        Zeigt an, entscheidet nicht: der Wert kommt vom Host bzw. vom Server.
        Vorher wurde die Liste nur getauscht und der Zeiger nur dabei gesetzt —
        eine vom Server gemeldete Zahl bewegte den Stepper also nie, und die
        Einstellung zeigte „4", waehrend die Lobby mit zwei Plaetzen lief.
        """
        erlaubt = self._groessen()
        labels = [str(n) for n in erlaubt]
        if self._size_stepper.options != labels:
            self._size_stepper.options = labels
        self._size_stepper.index = min(
            range(len(erlaubt)), key=lambda i: abs(erlaubt[i] - self._roster_size))

    def _groesse_setzen(self, wert: int) -> bool:
        """Die Fahrzeugzahl aendern (Host). Sagt, ob sich etwas geaendert hat.

        Ein im Modus unmoeglicher Wert wird auf den naechstliegenden erlaubten
        gezogen — das passiert beim Wechsel nach Team-Zeitfahren mit 3 oder 5
        Fahrzeugen.
        """
        erlaubt = self._groessen()
        if wert not in erlaubt:
            wert = min(erlaubt, key=lambda n: (abs(n - wert), n))
        alt, self._roster_size = self._roster_size, wert
        self._groessenwahl_richten()
        return wert != alt

    def _sync_ai_roster(self) -> None:
        """Set race_setup.ai_roster count to match free (non-player) slots."""
        from src.core import race_setup
        s = race_setup.current()
        real_count      = len(self._players)  # includes host
        ai_count        = max(0, self._roster_size - real_count)
        s.vehicle_count  = ai_count + 1        # 1 local driver + AI
        s.is_multiplayer = False
        s.sync_ai_roster()

    def _rebuild_roster_widgets(self) -> None:
        """Create vehicle+difficulty(+team) Stepper triples for each AI slot,
        and (re)position the own-player team stepper for Team-Zeitfahren."""
        from src.core import race_setup
        from src.entities.vehicle_factory import VehicleFactory
        from src.net import session
        s = race_setup.current()

        real_slots = {p["slot"] for p in self._players}
        self._roster_free_slots = [i for i in range(self._roster_size) if i not in real_slots]
        self._roster_ai_widgets = []

        team_mode = self._selected_mode == "Team-Zeitfahren"

        # Own row's team stepper — available to host AND guest, Team-Zeitfahren only.
        net = session.get()
        my_slot = net.slot if net else -1
        if team_mode and my_slot is not None and my_slot >= 0:
            row_y = _ROW_START_Y + my_slot * _ROW_STRIDE
            t_idx = 1 if self._my_team == "B" else 0
            self._team_stepper = Stepper(
                pygame.Rect(_RX + _COL_TEAM, row_y, 150, _ROW_H), "",
                [tr("Team A"), tr("Team B")], t_idx, action="set_team",
            )
        else:
            self._team_stepper = None

        if not self._is_host:
            return

        class_keys = list(s.class_keys() or ["rookie"])
        veh_keys   = ["random"] + class_keys
        veh_labels = ["Zufällig"] + [
            (VehicleFactory.get_config(k).name if VehicleFactory.get_config(k) else k)
            for k in class_keys
        ]
        diff_labels = [race_setup.DIFFICULTY_LABELS[k] for k in race_setup.DIFFICULTY_KEYS]
        diff_keys   = list(race_setup.DIFFICULTY_KEYS)

        for j, slot in enumerate(self._roster_free_slots):
            if j >= len(s.ai_roster):
                break
            driver = s.ai_roster[j]
            row_y  = _ROW_START_Y + slot * _ROW_STRIDE

            v_idx = veh_keys.index(driver.vehicle) if driver.vehicle in veh_keys else 0
            d_idx = diff_keys.index(driver.difficulty) if driver.difficulty in diff_keys else 1

            v_stepper = Stepper(
                pygame.Rect(_RX + _COL_VEH,  row_y, 240, _ROW_H), "",
                veh_labels, v_idx, action=f"ai_veh_{j}",
            )
            d_stepper = Stepper(
                pygame.Rect(_RX + _COL_DIFF, row_y, 210, _ROW_H), "",
                diff_labels, d_idx, action=f"ai_diff_{j}",
            )
            v_stepper.driver_ref = driver
            v_stepper.veh_keys   = veh_keys
            d_stepper.driver_ref = driver
            d_stepper.diff_keys  = diff_keys

            t_stepper = None
            if team_mode:
                t_idx = 1 if driver.team == "B" else 0
                t_stepper = Stepper(
                    pygame.Rect(_RX + _COL_TEAM, row_y, 150, _ROW_H), "",
                    [tr("Team A"), tr("Team B")], t_idx, action=f"ai_team_{j}",
                )
                t_stepper.driver_ref = driver

            self._roster_ai_widgets.append((v_stepper, d_stepper, t_stepper))

    def _enforce_vehicle_class(self) -> None:
        """Pull our own pick into the lobby's vehicle class (A17).

        The host can switch the class after everyone has already chosen a car.
        Rather than blocking the start on a stale pick, the offending car jumps
        to the first one of the new class — the player still sees it in their
        roster row and can pick a different one from there.
        """
        from src.core import race_setup
        s = race_setup.current()
        s.vehicle_class = self._selected_class
        allowed = s.class_keys()
        if not allowed or self._selected_vehicle in allowed:
            return
        self._selected_vehicle = allowed[0]
        s.player_vehicle = self._selected_vehicle
        self._update_button_labels()
        self._push_pick()
        # Mit Ablauf: das ist ein Ereignis, kein Zustand. Ohne ihn stand die
        # Zeile bis zum Verlassen der Lobby rot in der Fusszeile — der
        # Playtest-Fund vom 07.08.2026.
        self._melde(tr("Fahrzeug an die Klasse {c} angepasst.").format(
            c=tr(self._selected_class)))

    def _update_start_button_state(self) -> None:
        """Team-Zeitfahren: the start button is disabled while team_balance
        (server-computed, never recomputed locally) says teams aren't even."""
        team_mode = self._selected_mode == "Team-Zeitfahren"
        ok = (not team_mode) or self._team_balance.get("ok", True)
        self._btn_start.enabled   = ok
        self._btn_start.focusable = ok

    def _host_column_widgets(self) -> list:
        """Linke Spalte des Hosts in Anzeigereihenfolge — ohne Bereit/Start.

        Zwei Modusabhaengigkeiten stecken hier drin:

        * **Grand Prix hat keine Streckenwahl in der Lobby.** Die Strecke waehlt
          der Host vor jedem Lauf in der Uebersicht. Eine zweite Stelle dafuer
          verspricht eine Wahl, die der naechste Lauf ohnehin ueberschreibt.
        * **Die Serienlaenge steht unter den Runden**, nicht darueber: erst wie
          lang ein Lauf ist, dann wie viele davon.
        """
        gp_mode = self._selected_mode == "Grand Prix"
        reihe = [self._mode_stepper, self._size_stepper, self._class_stepper,
                 self._laps_stepper]
        if gp_mode and self._gp_races_stepper.focusable:
            reihe.append(self._gp_races_stepper)
        # Der Schalter fuer Streckenvorschlaege stand hier bis zum 05.08.2026.
        # Er sitzt jetzt in der Grand-Prix-Uebersicht, „eine Seite später":
        # dort liegt die Liste, auf die er sich bezieht, und dort kann der Host
        # ihn auch zwischen zwei Laeufen noch umlegen.
        if not gp_mode:
            reihe.append(self._btn_track)
        reihe.append(self._btn_vehicle)
        return reihe

    def _layout_host_column(self) -> None:
        """Spalte neu setzen. Gerechnet statt einmalig festgenagelt, sonst
        hinterlaesst jedes ausgeblendete Bedienelement ein Loch."""
        col = theme.Column(_LEFT_X, _LEFT_Y, gap=_LEFT_GAP)
        for widget in self._host_column_widgets():
            col.add(widget)
        col.skip(16)
        col.add(self._btn_ready)
        col.skip(16)
        col.add(self._btn_start)

    def _update_start_button_label(self) -> None:
        """Bei Grand Prix startet der Knopf kein Rennen — er fuehrt in die
        Uebersicht, wo die Strecke des naechsten Laufs gewaehlt wird."""
        if self._selected_mode == "Grand Prix" and self._gp_phase != "overview":
            self._btn_start.label = tr("Zur Übersicht") + "  ›"
        else:
            self._btn_start.label = tr("RENNEN STARTEN") + "  ›"

    def _refresh_focus_group(self) -> None:
        """Assemble FocusGroup from left-panel widgets + AI roster steppers."""
        flat_ai: list = []
        for v_s, d_s, t_s in self._roster_ai_widgets:
            flat_ai.append(v_s)
            flat_ai.append(d_s)
            if t_s is not None:
                flat_ai.append(t_s)

        gp_mode   = self._selected_mode == "Grand Prix"
        # Die Serienlaenge steht nur vor dem ersten Lauf zur Wahl - danach wuerde
        # eine Aenderung die laufende Wertung entwerten.
        from src.core import grand_prix
        gp_laeuft = bool(grand_prix.current() and grand_prix.current().history)
        self._gp_races_stepper.enabled   = gp_mode and not gp_laeuft
        self._gp_races_stepper.focusable = gp_mode and not gp_laeuft
        self._update_start_button_state()
        own_team_widget = [self._team_stepper] if self._team_stepper is not None else []

        if self._is_host:
            self._laps_stepper.enabled   = True
            self._laps_stepper.focusable = True
            self._mode_stepper.enabled   = True
            self._mode_stepper.focusable = True
            self._class_stepper.enabled  = True
            self._class_stepper.focusable = True
            self._groessenwahl_richten()
            self._size_stepper.enabled   = True
            self._size_stepper.focusable = True
            # KI-Schwierigkeit stepper removed from the left panel — difficulty is
            # set per AI driver on the right roster.
            # Reihenfolge, Sichtbarkeit und Position kommen aus einer Quelle,
            # sonst laufen Tastaturweg und Bild auseinander.
            self._update_start_button_label()
            self._layout_host_column()
            # keep_focus: die Liste wird bei jeder Aenderung neu gesetzt —
            # Feldgroesse, Fahrzeugklasse, jede Servernachricht mit geaendertem
            # Kader. Ohne das Behalten sprang die Hervorhebung dabei jedes Mal
            # auf das erste bedienbare Element, also auf den Spielmodus. Wer
            # mit Tastatur oder Controller die Rundenzahl verstellte, musste
            # sich danach wieder herunterarbeiten (gemeldet 07.08.2026).
            # Einzelspieler- und lokale Mehrspieler-Lobby machen es laengst so;
            # diese Stelle war uebersehen worden — daher das „immer noch" in
            # der Meldung.
            self._lobby_group.set_widgets([
                *self._host_column_widgets(),
                self._btn_ready, self._btn_start,
                *flat_ai,
                *own_team_widget,
            ], keep_focus=True)
        else:
            self._laps_stepper.enabled   = False
            self._laps_stepper.focusable = False
            self._mode_stepper.enabled   = False
            self._mode_stepper.focusable = False
            self._size_stepper.enabled   = False
            self._size_stepper.focusable = False
            self._class_stepper.enabled  = False
            self._class_stepper.focusable = False
            self._lobby_group.set_widgets([
                self._btn_vehicle_c, self._btn_ready_c,
                *own_team_widget,
            ], keep_focus=True)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _enter_gp_overview(self) -> None:
        """In die Grand-Prix-Uebersicht wechseln (Host und Gast)."""
        if self._gp_ui is None:
            self._gp_ui = GPOverview()
            # Cursor auf die gewaehlte Strecke setzen, damit die Infospalte
            # sofort das Richtige zeigt.
            key = self._gp_ui.key_for_path(self._selected_track_path)
            if key and key in self._gp_ui.keys:
                self._gp_ui.cursor = self._gp_ui.keys.index(key)
                self._gp_ui.move(0)
        self._gp_phase = "overview"
        self._view = _GP_OVERVIEW
        # Bereit gilt immer nur fuer den naechsten Lauf. Ohne das Zuruecksetzen
        # stehen nach dem ersten Rennen alle dauerhaft auf "Bereit" und der
        # Host koennte sofort weiterstarten, ohne dass jemand zugestimmt hat.
        self._lobby_ready = False
        from src.net import session as _s
        _net = _s.get()
        if _net:
            _net.send_tcp({"type": "LOBBY_UNREADY"})
        self._build_gp_group()
        if self._is_host:
            self._push_settings()

    def _leave_gp_overview(self) -> None:
        """Zurueck in die Lobby - Serie ist vorbei oder abgebrochen."""
        self._gp_phase = "lobby"
        self._gp_ui = None
        self._view = _LOBBY
        self._build_lobby_group()
        if self._is_host:
            self._push_settings()

    def _gp_ist_beendet(self) -> bool:
        """Serie durch — Anzeige und Bedienung schalten auf Siegerehrung um.

        Fuer alle aus dem verteilten Zustand, damit Host und Gast dasselbe
        sehen; der Host faellt zusaetzlich auf seine eigene Serie zurueck, weil
        er den Stand erzeugt, bevor er ihn verteilt hat.
        """
        if self._gp_view.get("gp_finished"):
            return True
        from src.core import grand_prix
        gp = grand_prix.current()
        return bool(self._is_host and gp and gp.is_finished)

    def _gp_sieg_pruefen(self) -> None:
        """Eine online gewonnene Serie verbuchen (E1a).

        Ohne Netz entscheidet das ``race_state`` am Ende des letzten Laufs.
        Online geht das dort nicht: die Wertung führt der Gastgeber, ein Gast
        hat gar keine eigene Serie — und in dem Augenblick, in dem er über die
        Ziellinie fährt, kennt er den Endstand auch noch nicht; der Host trägt
        das Ergebnis erst danach ein und verteilt es. Die Zahlen fehlen also
        nicht, sie kommen nur später und woanders an. Gebucht wird deshalb hier:
        wenn der verteilte Zustand die Serie als beendet meldet, bei Host und
        Gast über denselben Weg.

        Drei Bedingungen, jede gegen einen eigenen Fehler:

        * **einmal je Serie** — der Serienzustand kommt mit jeder ``LOBBY_STATE``
          erneut herein, das sind Dutzende
        * **laufen gesehen** — wer sich in eine bereits fertige Wertung
          einklinkt (Wiedereinstieg nach dem letzten Lauf), hat sie nicht
          gefahren
        * **selbst gewonnen** — verglichen wird der eigene Anzeigename, denn
          genau der steht in den Ergebniszeilen, aus denen die Wertung entsteht
        """
        aktiv = bool(self._gp_view.get("gp_active"))
        fertig = bool(self._gp_view.get("gp_finished"))
        if not aktiv or not fertig:
            self._gp_lief = aktiv        # läuft noch: der Abschluss zählt später
            self._gp_sieg_gebucht = False
            return
        if self._gp_sieg_gebucht or not self._gp_lief:
            return
        self._gp_sieg_gebucht = True
        stand = payload.dict_entries(self._gp_view.get("gp_standings"))
        if not stand:
            return
        if str(stand[0].get("name", "")).strip() != self._player_name():
            return
        from src.core import statistik
        statistik.gp_gewonnen()

    def _offer_widgets(self) -> list:
        """Knöpfe des Vorschlagsbereichs: je Zeile einer, plus „anbieten".

        Der Gastgeber hat zusaetzlich den Schalter selbst — er stand bis zum
        05.08.2026 in der Lobby und war damit vor dem Serienstart einmalig zu
        entscheiden. Hier kann er ihn auch zwischen zwei Laeufen umlegen.
        """
        from src.ui.widgets import Button
        from src.states.menu.gp_overview import GPOverview as _GPU
        # Nach dem letzten Lauf gibt es nichts mehr vorzuschlagen. Dort steht
        # der Abschluss und sonst nichts — ein Schalter, der nichts mehr
        # bewirkt, waere eine Frage ohne Anlass.
        if self._gp_ist_beendet():
            return []
        widgets = []
        if self._is_host:
            widgets.append(Button(
                _GPU.offer_toggle_rect(),
                tr("An") if self._offers_enabled else tr("Aus"),
                "toggle_offers", style="secondary"))
        if not self._offers_aktiv():
            return widgets
        for i, rect in _GPU.offer_download_rects(len(self._offers)):
            eintrag = self._offers[i]
            eigen = payload.as_int(eintrag.get("slot"), -1) == self._eigener_slot()
            widgets.append(Button(
                rect,
                tr("Eigene") if eigen else tr("Herunterladen"),
                f"offer_dl_{payload.as_int(eintrag.get('slot'), -1)}",
                enabled=not eigen, style="secondary"))
        widgets.append(Button(_GPU.offer_add_rect(),
                              tr("Strecke anbieten") + "  ›", "offer_add",
                              style="secondary"))
        return widgets

    def _offers_aktiv(self) -> bool:
        """Vorschläge sind aus, bis der Gastgeber sie einschaltet."""
        if self._is_host:
            return self._offers_enabled
        return bool(self._gp_view.get("offers_enabled"))

    def _eigener_slot(self) -> int:
        from src.net import session
        net = session.get()
        return net.slot if net else -1

    def _build_gp_group(self) -> None:
        """Bedienelemente der Uebersicht. Der Host bekommt zusaetzlich Start."""
        from src.ui.widgets import Button
        y = 960
        # Nach dem letzten Lauf gibt es nichts mehr zu starten und nichts mehr
        # anzumelden - nur noch den Abschluss.
        if self._gp_ist_beendet():
            self._btn_gp_ready = Button(pygame.Rect(0, 0, 0, 0), tr("Bereit"),
                                        "toggle_ready", enabled=False)
            self._btn_gp_leave = Button(pygame.Rect(810, y, 300, 60),
                                        tr("Grand Prix beenden"), "gp_leave")
            self._gp_group = FocusGroup([self._btn_gp_leave] + self._offer_widgets(),
                                        vertical=False)
            self._update_ready_button_labels()
            return
        self._btn_gp_ready = Button(pygame.Rect(60, y, 300, 60), tr("Bereit"),
                                    "toggle_ready")
        self._btn_gp_leave = Button(pygame.Rect(380, y, 300, 60),
                                    tr("Grand Prix verlassen"), "gp_leave",
                                    style="secondary")
        widgets = [self._btn_gp_ready, self._btn_gp_leave]
        if self._is_host:
            self._btn_gp_start = Button(pygame.Rect(700, y, 340, 60),
                                        tr("Rennen starten") + "  ›", "start")
            widgets.insert(1, self._btn_gp_start)
        self._gp_group = FocusGroup(widgets + self._offer_widgets(), vertical=False)
        self._update_ready_button_labels()
        self._update_gp_start_button()

    def _update_gp_start_button(self) -> None:
        """Starten geht erst, wenn alle bereit sind.

        Vorher stand der Knopf bedienbar da und antwortete erst nach dem Druck
        mit einer Meldung — der Host konnte nicht sehen, woran es liegt.
        """
        btn = getattr(self, "_btn_gp_start", None)
        if btn is None:
            return
        bereit = self._all_lobby_ready()
        btn.enabled   = bereit
        btn.focusable = bereit
        btn.hint = "" if bereit else tr("Alle müssen bereit sein")

    def _build_lobby_group(self) -> None:
        self._sync_ai_roster()
        self._rebuild_roster_widgets()
        self._refresh_focus_group()

    def _update_button_labels(self) -> None:
        vn = _vehicle_display_name(self._selected_vehicle)
        tn = _track_name_from_path(self._selected_track_path)
        self._btn_vehicle.label   = tr("Fahrzeug: {v}").format(v=vn) + "  ›"
        self._btn_vehicle_c.label = tr("Fahrzeug: {v}").format(v=vn) + "  ›"
        self._btn_track.label     = tr("Strecke: {t}").format(t=tn) + "  ›"

    def _update_ready_button_labels(self) -> None:
        label = tr("Nicht bereit") if self._lobby_ready else tr("Bereit")
        self._btn_ready.label   = label
        self._btn_ready_c.label = label
        # Der Knopf der Uebersicht wurde hier vergessen: er hiess dauerhaft
        # "Bereit", waehrend die Wertung daneben schon "Bereit √" zeigte.
        btn = getattr(self, "_btn_gp_ready", None)
        if btn is not None:
            btn.label = label
            # Wer bereit ist, hat hier nichts mehr zu tun - dann darf der Knopf
            # auch nicht mehr wie die naechste Handlung aussehen.
            btn.style = "secondary" if self._lobby_ready else "primary"

    def _ai_roster_payload(self) -> list:
        """Serialize the host's AI roster so joining clients show the same
        names / vehicles / difficulties instead of their own random ones."""
        from src.core import race_setup
        return [
            {"name": d.name, "vehicle": d.vehicle,
             "difficulty": d.difficulty, "team": d.team}
            for d in race_setup.current().ai_roster
        ]

    def _push_settings(self) -> None:
        from src.net import session
        net = session.get()
        if not net:
            return
        self._selected_laps       = int(self._laps_stepper.value)
        self._selected_difficulty = _DIFF_KEYS[self._diff_stepper.index]
        einstellungen = {
            "mode":          self._selected_mode,
            "roster_size":   self._roster_size,
            "vehicle_class": self._selected_class,
            "track_path":    self._selected_track_path,
            "track_name":    _track_name_from_path(self._selected_track_path),
            "laps":          self._selected_laps,
            "ai_difficulty": self._selected_difficulty,
            "ai_roster":     self._ai_roster_payload(),
            # Serienlaenge reist immer mit, auch bevor die Serie laeuft - sonst
            # sieht ein Gast in der Lobby nicht, ueber wie viele Rennen es geht.
            "gp_races":      int(self._gp_races_stepper.value),
            # Der Server laesst Vorschlaege nur zu, wenn das hier steht - er
            # liest es aus den Einstellungen, nicht aus einer eigenen Nachricht.
            "offers_enabled": bool(self._offers_enabled),
        }
        # Grand Prix reist im selben Block mit: der Relay speichert unter
        # settings beliebige Schlüssel und schickt sie an alle weiter. Dadurch
        # braucht der Serienzustand keine eigene Protokollnachricht und der
        # Server bleibt der dumme Relay, der er ist.
        einstellungen.update(self._gp_settings_payload())
        net.send_tcp({"type": "SET_SETTINGS", "settings": einstellungen})

    def _gp_startreihenfolge(self) -> list[str]:
        """Namen des ganzen Feldes in Startreihenfolge, Mensch wie KI.

        Gerechnet aus dem **verteilten** Stand und dem **verteilten** KI-Feld,
        die alle gleich haben — jeder Teilnehmer setzt sein eigenes Auto selbst
        auf die Startaufstellung, und zwei Rechnungen aus verschiedenen Quellen
        liessen zwei Autos auf demselben Platz erscheinen.
        """
        from src.core import grand_prix, race_setup
        stand = [str(e.get("name", ""))
                 for e in payload.dict_entries(self._gp_view.get("gp_standings"))]
        if not stand:
            return []
        feld = [str(p.get("name", "")) for p in payload.players(self._players)]
        feld += [d.name for d in race_setup.current().ai_roster]
        return grand_prix.startreihenfolge(stand, feld)

    def _ist_gp_modus(self) -> bool:
        """Gilt gerade Grand Prix?

        Der Host glaubt seiner **eigenen** Serie, nicht dem Modus, den der
        Server zurueckschreibt: ein Relay ohne "Grand Prix" in VALID_MODES
        macht daraus stillschweigend "Rennen", und die laufende Serie waere
        damit fuer alle weg — Lobby statt Uebersicht nach dem Rennen. Gaeste
        haben keine eigene Serie und folgen dem verteilten Modus.
        """
        from src.core import grand_prix
        if self._is_host and grand_prix.is_active():
            return True
        return self._selected_mode == "Grand Prix"

    def _gp_settings_payload(self) -> dict:
        """Serienzustand für die Gäste. Leer, wenn kein Grand Prix läuft."""
        from src.core import grand_prix
        gp = grand_prix.current()
        if not (self._ist_gp_modus() and gp):
            return {"gp_active": False, "gp_locked": False}
        # Streckenliste und gewaehlter Schluessel kommen vom Host. Gaeste
        # zeigten vorher ihre eigenen Dateien und rieten die Wahl ueber
        # Pfadvergleiche - eine Strecke, die sie nicht hatten, sah damit aus
        # wie "nichts gewaehlt".
        strecken, key = [], None
        if self._gp_ui is not None:
            strecken = self._gp_ui.host_track_payload()
            key = self._gp_ui.key_for_path(self._selected_track_path)
        return {
            "gp_tracks":    strecken,
            "gp_track_key": key,
            "gp_active":  True,
            # Phase steuert, welche Ebene die Gaeste zeigen. Ohne sie
            # muessten sie raten, ob gerade Lobby oder Uebersicht gilt.
            "gp_phase":   self._gp_phase,
            # Serie durch: die Uebersicht schaltet auf die Siegerehrung um.
            # Ohne dieses Merkmal liefe bei allen einfach der naechste Lauf an,
            # als waere nichts gewesen.
            "gp_finished": bool(gp.is_finished),
            # Ab dem ersten gefahrenen Lauf ist die Lobby dicht - vorher darf
            # sich das Feld noch füllen.
            "gp_locked":  bool(gp.history),
            "gp_members": {p.get("name", ""): True for p in self._players},
            "gp_race":    gp.race_index + 1,
            "gp_total":   gp.races_total,
            "gp_points":  dict(gp.points),
            "gp_raced":   list(gp.raced_tracks),
            "gp_standings": [
                {"name": e["name"], "points": e["points"]}
                for e in gp.get_standings()
            ],
        }

    def _push_pick(self) -> None:
        """Fahrzeug **und Lackierung** in die Lobby melden (D7).

        Die Lackierung steht im Profil und nicht in der Lobby — sie wird in der
        Werkstatt gewaehlt und gilt je Fahrzeug. Hier reist nur die Kennung mit,
        damit die anderen dasselbe Auto sehen wie man selbst.
        """
        from src.net import session
        net = session.get()
        if net:
            from src.core import lack, profile
            net.send_tcp({"type": "PICK", "vehicle": self._selected_vehicle,
                          "paint": lack.normalisiere(
                              profile.current().paint(self._selected_vehicle))})

    def _toggle_ready(self) -> None:
        self._lobby_ready = not self._lobby_ready
        self._update_ready_button_labels()
        from src.net import session
        net = session.get()
        if net:
            net.send_tcp({"type": "LOBBY_READY" if self._lobby_ready else "LOBBY_UNREADY"})

    def _all_lobby_ready(self) -> bool:
        if len(self._players) < 2:
            return False
        return all(p.get("lobby_ready", False) for p in self._players)

    def _request_start(self, force: bool = False) -> None:
        # Nach dem letzten Lauf ist Schluss. Vorher liess sich hier endlos
        # weiterfahren, waehrend die Wertung laengst feststand.
        if self._gp_ist_beendet():
            self._melde(tr("Der Grand Prix ist beendet."))
            return
        if len(self._players) < 2:
            self._msg = "Mindestens 2 Spieler erforderlich."
            return
        if not force and not self._all_lobby_ready():
            self._msg = "Nicht alle Spieler sind bereit."
            return
        from src.net import session
        net = session.get()
        if not net:
            return
        # Grand Prix: beim ersten Lauf die Serie anlegen. Nur der Host fuehrt
        # sie - Gaeste sehen ausschliesslich das, was er ueber die Einstellungen
        # verteilt.
        if self._selected_mode == "Grand Prix":
            from src.core import grand_prix
            if not grand_prix.is_active():
                grand_prix.start_series(int(self._gp_races_stepper.value),
                                        self._selected_laps)
                self._push_settings()

        track_name = _track_name_from_path(self._selected_track_path)
        # Always transfer the track file — custom AND built-in. A guest cannot be
        # trusted to resolve a bundled path on its own disk: packaged builds
        # resolve data/tracks/*.json inconsistently across machines, so a
        # built-in START used to dead-end the guest in _begin_race
        # ("Strecke wurde nicht empfangen.") while the host raced on alone. The
        # file is <1 MB and the transfer is byte-exact, so uploading it every
        # time is cheap insurance. Falls back to the READY-only path only if the
        # host itself cannot resolve the file to upload (see _upload_map_bg).
        self._melde("Übertrage Strecke …", 30.0)
        import threading
        threading.Thread(target=self._upload_map_bg,
                         args=(self._selected_track_path, track_name), daemon=True).start()

    def _upload_map_bg(self, path: str, track_name: str = "") -> None:
        """Upload the host's track to the relay (worker thread — blocks).

        If the host cannot resolve the file locally, fall back to a plain
        built-in START (READY) so guests that DO have the bundled track can still
        race instead of the host hanging on "Übertrage Strecke …"."""
        from src.core.paths import find_track
        from src.net import session
        net = session.get()
        if not net:
            return
        resolved = find_track(path)
        if not resolved:
            # Can't upload what we can't find — assume it's a bundled track the
            # guest also ships with, and start the built-in way.
            net.send_tcp({"type": "START_REQUEST",
                          "track_name": track_name or _track_name_from_path(path),
                          "is_custom": False})
            net.send_tcp({"type": "READY"})
            return
        try:
            net.upload_map(resolved)
        except Exception as exc:
            self._melde(f"Strecken-Upload fehlgeschlagen: {exc}", 10.0)

    def _stueck_anhaengen(self, puffer: list[str], stueck, was: str) -> bool:
        """Ein empfangenes base64-Stueck anhaengen, solange die Summe passt.

        Ohne diese Grenze wuchs die Liste unbegrenzt: der Server begrenzt eine
        Uebertragung auf 1 MB, aber der Client hat ihm das geglaubt. Ein
        boesartiger Relay konnte damit den Arbeitsspeicher fuellen
        (Releaseplan H2.6).

        Bei Ueberschreitung wird der Puffer verworfen und nicht weiter gefuellt —
        eine halbe Datei ist nutzlos, und weiterzuzaehlen hiesse, dem Absender
        eine zweite Chance auf denselben Angriff zu geben.
        """
        if not isinstance(stueck, str):
            return False
        summe = sum(len(s) for s in puffer) + len(stueck)
        if summe > _EMPFANG_MAX_ZEICHEN:
            puffer.clear()
            self._melde(tr("{was} ist zu groß — Übertragung abgebrochen.").format(was=tr(was)), 10.0)
            return False
        puffer.append(stueck)
        return True

    def _save_received_map(self) -> None:
        """Write the host's transferred custom track into our own user-data dir,
        then confirm READY — the race must start from a file that exists here."""
        import base64
        from src.core import paths
        from src.net import session
        try:
            raw   = base64.b64decode("".join(self._map_chunks))
            # The per-transfer track_name from MAP_META is authoritative — the
            # host sends the real file basename via upload_map(). Deriving the
            # name from _srv_track_path/_selected_track_path instead is stale on
            # a rematch (still points at the previous race's track), which made
            # a second, different track overwrite the first and race the wrong
            # map. So prefer _map_name; only fall back if it is unusable.
            roh = self._map_name if str(self._map_name).endswith(".json") else ""
            if not roh:
                roh = str(self._srv_track_path or self._selected_track_path or "")
            # Der Name stammt vom Host und ist damit nicht vertrauenswuerdig:
            # ohne Pruefung schreibt "../../../Startup/x.json" ausserhalb des
            # Streckenordners, mit Inhalt den der Absender bestimmt.
            name  = paths.safe_track_filename(roh)
            fpath = paths.user_path("data", "tracks", "online", name)
            with open(fpath, "wb") as fh:
                fh.write(raw)
        except Exception as exc:
            self._map_chunks = []
            self._melde(tr("Strecke konnte nicht gespeichert werden: {e}").format(e=exc), 10.0)
            return
        if not os.path.isfile(fpath):
            self._map_chunks = []
            self._melde(tr("Strecke konnte nicht gespeichert werden: {e}").format(e="?"), 10.0)
            return
        self._map_chunks          = []
        self._custom_track_local  = fpath
        self._selected_track_path = fpath
        self._msg = ""
        net = session.get()
        if net:
            net.send_tcp({"type": "READY"})

    # ── Streckenvorschläge (Block G) ────────────────────────────────────────

    def _eigene_strecken(self) -> list[tuple[str, str, int]]:
        """Was sich anbieten lässt: [(Streckenname, Pfad, Größe)].

        Nur selbst gebaute Strecken aus ``data/tracks/custom``. Eingebaute hat
        jeder schon, und was in ``data/tracks/online`` liegt, ist die Kopie
        einer fremden Strecke aus einem Rennstart — die gehört einem nicht.
        """
        from src.core import paths
        aus: list[tuple[str, str, int]] = []
        gesehen: set[str] = set()
        for wurzel in (paths.user_data_dir(), paths.bundle_dir()):
            ordner = wurzel / "data" / "tracks" / "custom"
            if not ordner.is_dir():
                continue
            for datei in sorted(ordner.glob("*.json")):
                if datei.name in gesehen:
                    continue
                gesehen.add(datei.name)
                try:
                    groesse = datei.stat().st_size
                except OSError:
                    continue
                aus.append((_track_name_from_path(str(datei)), str(datei), groesse))
        return aus

    def _offer_upload(self, pfad: str) -> None:
        """Eigene Strecke in die Lobby legen (Arbeitsfaden, blockiert)."""
        from src.net import session
        net = session.get()
        if not net:
            return
        # Grenze hier pruefen, nicht erst im Arbeitsfaden: sonst meldet die
        # Seite erst "Lade hoch ...", um Sekunden spaeter abzubrechen.
        try:
            groesse = os.path.getsize(pfad)
        except OSError as exc:
            self._melde(tr("Vorschlag fehlgeschlagen: {e}").format(e=exc))
            return
        if groesse > _OFFER_MAX_B:
            self._melde(tr("Strecke ist zu groß ({kb} KB, erlaubt sind 1024 KB).").format(
                kb=groesse // 1024))
            return

        titel = _track_name_from_path(pfad)
        self._offer_busy = titel
        self._melde(tr("Lade {n} hoch …").format(n=titel), 30.0)

        def arbeit() -> None:
            try:
                net.upload_offer(pfad, titel)
            except Exception as exc:
                self._offer_busy = ""
                self._melde(tr("Vorschlag fehlgeschlagen: {e}").format(e=exc))

        threading.Thread(target=arbeit, daemon=True).start()

    def _save_offer(self) -> None:
        """Empfangenen Vorschlag zu den eigenen Strecken legen.

        Nichts Eigenes wird überschrieben: bei gleichem Namen bekommt die Datei
        eine Nummer. Der Name des Teilenden steht nur in der Lobby, nicht auf
        der Platte.
        """
        import base64
        from src.core import paths
        if not self._offer_chunks:
            self._melde(tr("Strecke wurde nicht empfangen."), 10.0)
            return
        try:
            roh = base64.b64decode("".join(self._offer_chunks))
            # Der Titel kommt von einem Mitspieler. Fuer den *Pfad* ist er
            # laengst entschaerft (paths.safe_track_filename), fuer seinen
            # *Inhalt* war er es nicht: eine geschenkte Strecke konnte unter
            # jedem beliebigen Namen dauerhaft im Ordner eines anderen
            # Spielers liegen. Hier steht der Empfaenger, also wird hier
            # geschuetzt — abweisen laesst sich ein Geschenk nicht sinnvoll,
            # umbenennen schon (07.08.2026).
            from src.core import profile as _profil
            name = self._offer_name
            if not _profil.validate_track_name(os.path.splitext(name)[0])[0]:
                name = tr("Geteilte Strecke") + ".json"
            ziel = paths.freier_streckenpfad("data/tracks/custom", name)
            with open(ziel, "wb") as fh:
                fh.write(roh)
        except Exception as exc:
            self._offer_chunks = []
            self._melde(tr("Strecke konnte nicht gespeichert werden: {e}").format(e=exc), 10.0)
            return
        self._offer_chunks = []
        self._melde(tr("Gespeichert als {n}").format(n=os.path.basename(ziel)))
        # Die Liste der Uebersicht kommt aus Dateien - ohne Neulesen taucht die
        # frisch geschenkte Strecke erst beim naechsten Betreten auf.
        if self._gp_ui is not None:
            from src.states.menu.gp_overview import load_track_infos
            self._gp_ui.tracks = load_track_infos()
            if self._is_host:
                self._gp_ui.keys = list(self._gp_ui.tracks.keys())
                self._gp_ui.move(0)
                self._push_settings()

    def _begin_race(self, data: dict) -> None:
        # Defense-in-depth: a redundant "START" broadcast (server-side race
        # condition, now also guarded server-side) must not re-enter the race
        # state a second time — that would exit() the already-active RaceState
        # and wipe its just-established network session.
        if self._race_begun:
            return
        self._race_begun = True

        from src.core import race_setup
        s = race_setup.current()

        from src.core.paths import find_track
        from src.core import paths as _paths
        cand = self._custom_track_local or self._selected_track_path
        resolved = None
        if self._custom_track_local and os.path.isfile(self._custom_track_local):
            resolved = self._custom_track_local
        else:
            resolved = find_track(str(cand or ""))
        # Self-heal: a transferred custom track was written to
        # data/tracks/online/<map_name> during _save_received_map. If
        # _custom_track_local was cleared in between (e.g. an interleaved
        # LOBBY_STATE echoing the host's track path), recover it by name so a
        # guest that already confirmed READY never dead-ends on a track it
        # actually has on disk.
        if not resolved and self._map_name:
            base = os.path.basename(str(self._map_name))
            guess = _paths.user_path("data", "tracks", "online", base)
            if os.path.isfile(guess):
                resolved = guess
            else:
                resolved = find_track(base)
        if not resolved:
            # The custom track never arrived — abort instead of crashing in Track._load.
            self._race_begun = False          # allow a later START to succeed
            # Record exactly what we tried so a real, unreproduced failure is
            # pin-pointable from the affected machine instead of guessed at.
            try:
                with open(_paths.user_path("data", "settings", "online_debug.log"),
                          "a", encoding="utf-8") as _fh:
                    _fh.write(
                        "[begin_race] unresolved track | "
                        f"custom_local={self._custom_track_local!r} "
                        f"selected={self._selected_track_path!r} "
                        f"srv={self._srv_track_path!r} map_name={self._map_name!r} "
                        f"is_host={self._is_host}\n"
                    )
            except Exception:
                pass
            self._melde(tr("Strecke wurde nicht empfangen."), 10.0)
            return

        # The AI teams have to be read BEFORE the guest branch clears the roster —
        # guests keep no ai_roster during the race but still need the mapping to
        # colour and score the host's bots.
        guest_roster_teams = [d.team for d in s.ai_roster]
        # Aus demselben Grund hier: die Startreihenfolge braucht die KI-Namen,
        # und der Gast raeumt sein Feld gleich ab.
        gitter = self._gp_startreihenfolge() if self._ist_gp_modus() else []

        s.mode           = self._selected_mode
        s.is_multiplayer = False
        s.track_path     = resolved
        s.laps           = self._selected_laps
        s.player_vehicle = self._selected_vehicle
        s.ai_difficulty  = self._selected_difficulty
        s.vehicle_class  = self._selected_class
        s.p1_team        = self._my_team

        if self._is_host:
            real_count      = len(self._players)
            s.vehicle_count = max(1, self._roster_size - real_count + 1)
            s.sync_ai_roster()
            roster_teams = [d.team for d in s.ai_roster]
        else:
            s.vehicle_count = 1
            roster_teams    = guest_roster_teams
            s.ai_roster     = []

        s._online = True
        s._online_start_ts = None   # countdown now starts on the server's RACE_GO
        from src.net import session as _sess
        _nc      = _sess.get()

        # Each peer must spawn its own local car on the grid slot matching its
        # network slot (0 = host, 1..N = joiners in join order), and AI (host
        # only) must start filling slots AFTER every real human — otherwise every
        # peer places its own car on grid slot 0, so two real players spawn on
        # top of each other and the host's AI overlaps the other player's slot.
        # The grid slot must be the RANK of our network slot among all
        # currently connected players (not the raw, possibly-stale network
        # slot number) — otherwise a reconnecting guest can land on a raw
        # slot like 2 while grid slot 1 sits empty and the host's AI also
        # fills slot 2. Every peer computes this rank from the same
        # server-pushed self._players list (LOBBY_STATE), so ranks are
        # consistent across peers and results reported per-peer (which use
        # this same rank as their reported slot) line up on every side.
        raw_slot = _nc.slot if _nc else 0
        all_slots = sorted(p.get("slot", 0) for p in self._players) or [raw_slot]
        try:
            online_slot = all_slots.index(raw_slot)
        except ValueError:
            online_slot = 0
        online_human_count = max(1, len(self._players))

        # Grand Prix: der Stand der Serie ist die Startaufstellung - Vierter der
        # Wertung startet von Platz vier, egal ob Mensch oder KI. Der Netzslot
        # bleibt davon unberuehrt, er ist die Kennung, unter der Ergebnisse
        # gemeldet werden.
        grid_slot = online_slot
        ai_grid_slots = None
        human_grid_slots = None
        if gitter:
            # Die Plaetze ALLER Menschen, nicht nur des eigenen: der Host baut
            # die KI-Autos und darf sie nicht auf einen Platz setzen, auf dem
            # gleich ein Gast steht. Ohne diese Liste rieten die uebrigen
            # Plaetze sich selbst zusammen.
            human_grid_slots = [
                gitter.index(str(pl.get("name", ""))) if str(pl.get("name", "")) in gitter
                else None
                for pl in self._players
            ]
            mein_name = next((str(p.get("name", "")) for p in self._players
                              if p.get("slot") == raw_slot), "")
            if mein_name in gitter:
                grid_slot = gitter.index(mein_name)
            if self._is_host:
                # Nur der Host baut die KI-Autos - und setzt sie auf die
                # Plaetze, die ihre Wertung ihnen gibt.
                ai_grid_slots = [gitter.index(d.name) if d.name in gitter else None
                                 for d in s.ai_roster]

        s.online_players = {
            p["slot"]: {"name": p.get("name", "Unknown"),
                        "team": p.get("team", "A"),
                        # Lackierung des Mitspielers (D7) — das Rennen faerbt
                        # sein Abbild damit ein.
                        "paint": str(p.get("paint", "") or "")}
            for p in self._players
        }
        # vehicle_id -> team for the host-simulated AI. The id formula mirrors
        # RaceState._spawn_ai_vehicles (`i + 1 + human_count`), so every peer
        # derives the same mapping even though only the host builds the cars.
        s.online_ai_teams = {
            i + 1 + online_human_count: team
            for i, team in enumerate(roster_teams)
        }

        self.shell.state_machine.transition(
            "race",
            track_path=s.track_path,
            total_laps=s.laps,
            vehicle_config=s.player_vehicle,
            online_slot=online_slot,
            grid_slot=grid_slot,
            ai_grid_slots=ai_grid_slots,
            human_grid_slots=human_grid_slots,
            online_human_count=online_human_count,
        )

    def _navigate_to_track_select(self) -> None:
        from src.core import race_setup
        race_setup.current().track_path = self._selected_track_path
        self.shell.state_machine.transition("track_select", online_host_mode=True)

    def _navigate_to_car_select(self) -> None:
        from src.core import race_setup
        race_setup.current().player_vehicle = self._selected_vehicle
        self.shell.state_machine.transition("car_select", online_mode=True,
                                            vehicle_config=self._selected_vehicle)

    # ── Server selection ─────────────────────────────────────────────────────

    def _refresh_server_rows(self) -> None:
        """Copy the latest probe results into the row widgets."""
        from src.net import server_probe
        for row, st in zip(self._server_rows, server_probe.statuses()):
            if st.state == server_probe.OUTDATED:
                status_text = "Version veraltet"
            elif st.state != server_probe.ONLINE:
                status_text = "Offline"
            else:
                status_text = ""
            row.set_status(enabled=st.selectable, bars=st.bars, ping_ms=st.ping_ms,
                           lobby_count=st.lobby_count, status_text=status_text,
                           lobby_max=st.lobby_max, ausgelastet=st.ausgelastet)
            row.selected = (st.server.id == self._selected_srv_id)

        # Drop a selection that just went offline, and pre-select the first
        # usable server so the player can hit "Lobby erstellen" straight away.
        usable = [r for r, sd in zip(self._server_rows, self._server_defs) if r.enabled]
        if self._selected_srv_id and not any(
                r.selected and r.enabled for r in self._server_rows):
            self._selected_srv_id = None
        if self._selected_srv_id is None and usable:
            idx = self._server_rows.index(usable[0])
            self._selected_srv_id = self._server_defs[idx].id
            for i, r in enumerate(self._server_rows):
                r.selected = (i == idx)

        can_create = any(r.enabled for r in self._server_rows) and self._selected_srv_id
        self._btn_create.enabled = bool(can_create)
        self._btn_create.focusable = bool(can_create)

        # A row that just lost focusability must not keep the focus.
        foc = self._host_group.focused
        if foc is not None and not getattr(foc, "focusable", False):
            self._host_group.index = self._host_group._first_focusable()

    def _selected_server(self):
        from src.net import servers
        return servers.by_id(self._selected_srv_id) if self._selected_srv_id else None

    def _player_name(self) -> str:
        """Name from the profile — the online page no longer asks for one."""
        from src.core import profile
        return (profile.current().username or "").strip()[:15] or "Player"

    def _start_connect(self, server, *, is_host: bool, lobby_code: str = "") -> None:
        name = self._player_name()
        self._is_host        = is_host
        self._connect_server = server
        self._view           = _CONNECTING
        self._msg            = ""
        self._players        = []

        from src.net.client import NetworkClient
        from src.net import session, server_probe
        net = NetworkClient()
        session.set(net)

        def _thread():
            # Re-resolve here rather than trusting the config: playit hands out a
            # new port whenever its agent restarts.
            host, tcp_port, udp_port = server_probe.resolve_endpoint(server)
            if not net.connect(host, tcp_port, udp_host=host, udp_port=udp_port,
                               preamble=server.preamble_bytes(host, tcp_port)):
                return
            if is_host:
                net.send_tcp({"type": "HOST", "name": name})
            else:
                net.send_tcp({"type": "JOIN", "name": name, "lobby_id": lobby_code})

        threading.Thread(target=_thread, daemon=True, name="net-connect").start()

    def _cleanup_net(self) -> None:
        from src.net import session
        session.clear()

    # ── Events ────────────────────────────────────────────────────────────────

    #: Was als Eingabe zaehlt. Mausbewegung bewusst nicht — ein Zeiger, der
    #: neben der Tastatur liegt, haelt sonst eine leere Lobby ewig offen.
    _EINGABE_TYPEN = (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN, pygame.MOUSEWHEEL,
                      pygame.JOYBUTTONDOWN, pygame.JOYHATMOTION)

    def handle_event(self, event: pygame.event.Event) -> bool | None:
        if (self._dialog is None and self.osk is None
                and self._view not in self._HAT_EIGENEN_RUECKWEG
                and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.zurueck_knopf().hit(event.pos)):
            self.zurueck()
            return True
        if event.type in self._EINGABE_TYPEN:
            self._lobby_aktivitaet()

        if self.osk:
            if self.osk.handle_event(event):
                self.osk = None
            return True

        # Rueckfragen vor dem Verlassen liegen ueber allem anderen.
        if self._dialog is not None:
            res = self._dialog.handle_event(event)
            if res == "ok":
                aktion = self._dialog_aktion
                self._dialog = None
                if aktion == "lobby_leave":
                    self._confirm_leave_lobby()
                else:
                    self._confirm_leave_gp()
                # Wer die Rueckfrage ausgeloest hat, wollte meist noch woanders
                # hin (Klick auf einen Tab). Das geht erst jetzt.
                danach, self._dialog_danach = self._dialog_danach, None
                if danach is not None:
                    danach()
            elif res is not None:
                self._dialog = None
                self._dialog_danach = None
            return True

        if self._view == _ROLE:
            return self._role_event(event)
        elif self._view == _HOST_SERVER:
            return self._host_server_event(event)
        elif self._view == _JOIN:
            return self._join_event(event)
        elif self._view == _LOBBY:
            return self._lobby_event(event)
        elif self._view == _GP_OVERVIEW:
            self._gp_event(event)
            return True
        elif self._view == _CONNECTING:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._cleanup_net()
                self._view = self._return_view
            return True
        return None

    def _role_event(self, event: pygame.event.Event) -> bool | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return False
        action = self._role_group.handle_event(event)
        if action == "role_host":
            self._msg = ""
            self._return_view = _HOST_SERVER
            self._view = _HOST_SERVER
            if self._server_defs:
                if not self._selected_srv_id:
                    self._selected_srv_id = self._server_defs[0].id
                for row, sd in zip(self._server_rows, self._server_defs):
                    row.selected = (sd.id == self._selected_srv_id)
                self._btn_create.enabled = True
                self._btn_create.focusable = True
            return True
        elif action == "role_join":
            self._msg = ""
            self._return_view = _JOIN
            self._view = _JOIN
            return True
        elif action == "back_menu":
            return False
        return True

    def _host_server_event(self, event: pygame.event.Event) -> bool | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._msg = ""
            self._return_view = _ROLE
            self._view = _ROLE
            return True

        action = self._host_group.handle_event(event)
        if not action:
            return True
        if action == "back_role":
            self._msg = ""
            self._return_view = _ROLE
            self._view = _ROLE
            return True
        if action.startswith("pick_"):
            self._selected_srv_id = action[len("pick_"):]
            self._msg = ""
            for row, sd in zip(self._server_rows, self._server_defs):
                row.selected = (sd.id == self._selected_srv_id)
            self._btn_create.enabled = True
            self._btn_create.focusable = True
            return True
        if action == "create":
            server = self._selected_server()
            if server is None:
                self._msg = "Kein Server verfügbar."
                return True
            self._msg = ""
            self._start_connect(server, is_host=True)
            return True
        return True

    def _join_event(self, event: pygame.event.Event) -> bool | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._msg = ""
            self._return_view = _ROLE
            self._view = _ROLE
            return True

        from src.core import gamepad
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN
                and self._join_group.focused is self._code_input
                and gamepad.using_pad() and self.osk is None):
            self.osk = OnScreenKeyboard(
                self._code_input, on_done=lambda: setattr(self._join_group, "index", 2))
            return True

        action = self._join_group.handle_event(event)
        if action == "edit":
            self._msg = ""          # typing clears the previous complaint
            return True
        if action == "back_role":
            self._msg = ""
            self._return_view = _ROLE
            self._view = _ROLE
            return True
        if action != "join":
            return True

        from src.net import servers, server_probe
        code = self._code_input.text.strip().upper()
        if len(code) != 6:
            self._msg = "Lobby-Code muss 6 Zeichen lang sein."
            return
        server = servers.for_code(code)
        if server is None:
            # First character is the server tag; anything else is a typo or a
            # code from a server this build does not know.
            self._msg = "Unbekannter Lobby-Code."
            return
        st = server_probe.get(server.id)
        if st is None or not st.selectable:
            self._msg = "Server nicht erreichbar."
            return
        self._msg = ""
        self._start_connect(server, is_host=False, lobby_code=code)

    def _gp_event(self, event: pygame.event.Event) -> None:
        """Bedienung der Grand-Prix-Uebersicht."""
        if self._gp_ui is None:
            return

        if self._offer_pick is not None:
            self._offer_pick_event(event)
            return

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._ask_leave_gp()
            return

        # Blaettern duerfen alle - auswaehlen nur der Host. Ein Gast schaut sich
        # Strecken an, ohne etwas zu entscheiden.
        #
        # Beim Host ist der Cursor die Auswahl. Vorher brauchte es zusaetzlich
        # die Leertaste, und weil das nirgends stand, verteilte er reihenweise
        # Strecken, die er nur angesehen hatte: bei den Gaesten blieb die erste
        # stehen. Der Host entscheidet ohnehin allein - ein zweiter Schritt
        # schuetzt hier niemanden.
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_UP, pygame.K_w):
            self._gp_ui.move(-1)
            if self._is_host:
                self._gp_pick_track(self._gp_ui.cursor)
            return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_DOWN, pygame.K_s):
            self._gp_ui.move(+1)
            if self._is_host:
                self._gp_pick_track(self._gp_ui.cursor)
            return
        if event.type == pygame.MOUSEWHEEL:
            # Rad blaettert nur die Ansicht. Wuerde es den Cursor mitnehmen,
            # aendert sich beim Scrollen die Streckenvorschau - und beim Host
            # steht der Cursor auf einer Strecke, die er nie angesehen hat.
            self._gp_ui.scroll_by(-event.y)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in self._gp_ui.tile_rects():
                if rect.collidepoint(event.pos):
                    self._gp_ui.cursor = i
                    if self._is_host:
                        self._gp_pick_track(i)
                    return

        if (self._is_host and event.type == pygame.KEYDOWN
                and event.key == pygame.K_SPACE):
            self._gp_pick_track(self._gp_ui.cursor)
            return

        aktion = self._gp_group.handle_event(event)
        if aktion == "toggle_ready":
            self._toggle_ready()
        elif aktion == "start" and self._is_host:
            self._request_start()
        elif aktion == "gp_leave":
            self._ask_leave_gp()
        elif aktion == "offer_add":
            self._open_offer_picker()
        elif aktion == "toggle_offers" and self._is_host:
            self._offers_umschalten()
        elif aktion and aktion.startswith("offer_dl_"):
            from src.net import session
            net = session.get()
            if net:
                net.request_offer(int(aktion[len("offer_dl_"):]))

    def _offers_umschalten(self) -> None:
        """Streckenvorschlaege an oder aus — jederzeit, auch mitten in der Serie.

        Beim Ausschalten wird der Zwischenspeicher geleert: „Schon hochgeladene
        Strecken werden dann aus dem Zwischenspeicher gelöscht und müssten neu
        hochgeladen werden wenn der Host die Strecken suggestions wieder
        aktiviert." Das ist die ehrliche Lesart von „aus" — eine Liste, die
        unsichtbar weiterlebt und beim Wiedereinschalten zurueckkommt, waere
        eine Ueberraschung, und der Relay traegt sie sonst bis zum Ende der
        Lobby mit.

        Geleert wird auf beiden Seiten. Der Relay macht es selbst, sobald das
        Flag fällt (er allein kennt die Ablage); hier fällt die eigene Anzeige
        sofort, damit sie nicht bis zur naechsten Servernachricht etwas zeigt,
        das gerade verworfen wird.
        """
        self._offers_enabled = not self._offers_enabled
        if not self._offers_enabled:
            self._offers = []
            self._offer_busy = ""
            self._offer_chunks = []
            self._offer_name = ""
            self._close_offer_picker()
        self._push_settings()
        self._build_gp_group()

    # ── Auswahlliste beim Anbieten ──────────────────────────────────────────

    def _open_offer_picker(self) -> None:
        """Auswahlliste aus echten Knöpfen bauen.

        Nicht selbst gezeichnete Zeilen mit eigener Tastenabfrage: Knöpfe in
        einer FocusGroup können Maus, Tastatur und Controller gleichermaßen —
        der Gamepad-Übersetzer macht aus Steuerkreuz und A/B genau die
        Ereignisse, die eine FocusGroup ohnehin versteht.
        """
        from src.ui.widgets import Button
        strecken = self._eigene_strecken()
        if not strecken:
            self._melde(tr("Keine eigenen Strecken vorhanden."))
            return
        self._offer_pick = strecken
        self._offer_pick_cursor = 0
        self._offer_pick_offset = 0
        self._offer_rows = []
        for i, (titel, _pfad, groesse) in enumerate(strecken):
            zu_gross = groesse > _OFFER_MAX_B
            beschriftung = f"{titel}   ({groesse // 1024} KB)"
            self._offer_rows.append(Button(
                pygame.Rect(0, 0, 700, 40), beschriftung, f"pick_{i}",
                style="secondary", enabled=not zu_gross,
                hint=tr("Größer als 1024 KB") if zu_gross else ""))
        self._btn_offer_ok = Button(pygame.Rect(0, 0, 300, 44),
                                    tr("Hochladen") + "  ›", "pick_ok")
        self._btn_offer_cancel = Button(pygame.Rect(0, 0, 300, 44),
                                        tr("Abbrechen"), "pick_cancel",
                                        style="secondary")
        self._offer_pick_group = FocusGroup(
            self._offer_rows + [self._btn_offer_ok, self._btn_offer_cancel])
        self._offer_ok_pruefen()
        self._layout_offer_picker()

    def _offer_ok_pruefen(self) -> None:
        """Hochladen geht nur mit einer Strecke, die durch die Grenze passt."""
        wahl = (self._offer_pick or [])[self._offer_pick_cursor:self._offer_pick_cursor + 1]
        zu_gross = bool(wahl) and wahl[0][2] > _OFFER_MAX_B
        self._btn_offer_ok.enabled   = bool(wahl) and not zu_gross
        self._btn_offer_ok.focusable = self._btn_offer_ok.enabled
        self._btn_offer_ok.hint = tr("Größer als 1024 KB") if zu_gross else ""

    def _offer_max_offset(self) -> int:
        return max(0, len(self._offer_rows) - _OFFER_PICK_ROWS)

    def _layout_offer_picker(self, folge_fokus: bool = True) -> None:
        """Sichtfenster setzen und die Knöpfe darin platzieren.

        Das Rad blättert nur die Ansicht — wie in der Streckenliste daneben.
        Tastatur und Controller bewegen dagegen die Auswahl, und dann muss das
        Fenster ihr folgen, sonst wandert der Fokus unsichtbar davon.
        """
        gruppe = self._offer_pick_group
        if gruppe is None:
            return
        sichtbar = min(len(self._offer_rows), _OFFER_PICK_ROWS)
        if folge_fokus and gruppe.index < len(self._offer_rows):
            fokus = gruppe.index
            if fokus < self._offer_pick_offset:
                self._offer_pick_offset = fokus
            elif fokus >= self._offer_pick_offset + sichtbar:
                self._offer_pick_offset = fokus - sichtbar + 1
        self._offer_pick_offset = max(0, min(self._offer_max_offset(),
                                             self._offer_pick_offset))

        rect = self._offer_pick_rect(sichtbar)
        y = rect.y + 74
        for i, w in enumerate(self._offer_rows):
            if self._offer_pick_offset <= i < self._offer_pick_offset + sichtbar:
                w.rect = pygame.Rect(rect.x + 30, y, rect.width - 90, 40)
                y += 44
            else:
                # Ausserhalb des Fensters: keine Flaeche, also auch kein
                # Mausklick auf etwas Unsichtbares.
                w.rect = pygame.Rect(-1000, -1000, 0, 0)
        self._btn_offer_ok.rect = pygame.Rect(rect.right - 340, rect.bottom - 62, 300, 44)
        self._btn_offer_cancel.rect = pygame.Rect(rect.x + 40, rect.bottom - 62, 300, 44)

    @staticmethod
    def _offer_pick_rect(sichtbar: int) -> pygame.Rect:
        hoehe = sichtbar * 44 + 180
        return pygame.Rect(960 - 380, 540 - hoehe // 2, 760, hoehe)

    def _offer_pick_event(self, event: pygame.event.Event) -> None:
        """Bedienung der Auswahlliste. Liegt vor allem anderen, solange sie
        offen ist — sonst blättert man darunter durch die Strecken des Hosts."""
        gruppe = self._offer_pick_group
        if gruppe is None:
            self._offer_pick = None
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._close_offer_picker()
            return
        if event.type == pygame.MOUSEWHEEL:
            # Nur blaettern, die Auswahl bleibt stehen - dieselbe Regel wie in
            # der Streckenliste daneben.
            self._offer_pick_offset -= event.y
            self._layout_offer_picker(folge_fokus=False)
            return

        aktion = gruppe.handle_event(event)
        self._layout_offer_picker()
        if aktion == "pick_cancel":
            self._close_offer_picker()
        elif aktion == "pick_ok":
            wahl = (self._offer_pick or [])[self._offer_pick_cursor:
                                            self._offer_pick_cursor + 1]
            if wahl:
                pfad = wahl[0][1]
                self._close_offer_picker()
                self._offer_upload(pfad)
                from src.core import statistik
                statistik.strecke_geteilt()
        elif aktion and aktion.startswith("pick_"):
            # Eine Zeile waehlt nur aus. Hochgeladen wird ueber den Knopf -
            # ein Klick in eine Liste soll nicht sofort eine Datei verschicken.
            self._offer_pick_cursor = int(aktion[len("pick_"):])
            self._offer_ok_pruefen()
            if self._btn_offer_ok.enabled:
                gruppe.index = gruppe.widgets.index(self._btn_offer_ok)
            self._layout_offer_picker(folge_fokus=False)

    def _draw_offer_pick_scrollbar(self, screen: pygame.Surface,
                                   rect: pygame.Rect, sichtbar: int) -> None:
        """Leiste rechts neben den Zeilen — wie bei den Streckenkacheln. Ohne
        sie sieht man einer abgeschnittenen Liste nicht an, wie lang sie ist."""
        gesamt = len(self._offer_rows)
        bahn = pygame.Rect(rect.right - 44, rect.y + 74, 8, sichtbar * 44 - 4)
        pygame.draw.rect(screen, theme.PANEL, bahn, border_radius=4)
        pygame.draw.rect(screen, theme.BORDER, bahn, 1, border_radius=4)
        hoehe = max(30, int(bahn.height * sichtbar / gesamt))
        max_off = self._offer_max_offset()
        anteil = (self._offer_pick_offset / max_off) if max_off else 0.0
        daumen = pygame.Rect(bahn.x, bahn.y + int((bahn.height - hoehe) * anteil),
                             bahn.width, hoehe)
        pygame.draw.rect(screen, theme.ACCENT, daumen, border_radius=4)
        theme.text(screen, f"{self._offer_pick_cursor + 1} / {gesamt}",
                   theme.SMALL, theme.TEXT_FAINT,
                   (rect.right - 24, rect.y + 30), topright=True)

    def _close_offer_picker(self) -> None:
        self._offer_pick = None
        self._offer_pick_group = None
        self._offer_rows = []

    def _gp_pick_track(self, index: int) -> None:
        """Host waehlt die Strecke fuer den naechsten Lauf."""
        key = self._gp_ui.key_at(index) if self._gp_ui else None
        info = self._gp_ui.tracks.get(key or "") if self._gp_ui else None
        if not info:
            return
        self._selected_track_path = info["path"]
        self._update_button_labels()
        # Der Server setzt bei jeder Streckenaenderung alle Bereit-Meldungen
        # zurueck - sonst startet jemand eine Strecke, die er nie gesehen hat.
        self._push_settings()

    def _ask_leave_lobby(self) -> None:
        """Rueckfrage vor dem Verlassen der Lobby.

        Beim Host haengt die ganze Runde daran: geht er, ist die Lobby weg.
        Beim Gast nur sein eigener Platz - die Meldung sagt, was zutrifft.
        """
        from src.ui.widgets import Dialog
        self._dialog_aktion = "lobby_leave"
        if self._is_host:
            self._dialog = Dialog(
                tr("Lobby verlassen?"),
                tr("Die Lobby wird für alle geschlossen."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")])
        else:
            self._dialog = Dialog(
                tr("Lobby verlassen?"),
                tr("Die Verbindung wird getrennt."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")])

    def _confirm_leave_lobby(self) -> None:
        self._cleanup_net()
        self._view = _ROLE
        self._msg  = ""

    def _ask_leave_gp(self) -> None:
        """Warnung vor dem Verlassen.

        Fuer den Host endet damit die Serie fuer alle, fuer einen Gast nur seine
        eigene Wertung - die Meldung muss das deutlich unterscheiden.
        """
        from src.ui.widgets import Dialog
        # Ist die Serie durch, gibt es nichts mehr zu verlieren - dann waere
        # die Rueckfrage nur eine Huerde vor dem Abschluss.
        if self._gp_ist_beendet():
            self._confirm_leave_gp()
            return
        self._dialog_aktion = "gp_leave"
        if self._is_host:
            self._dialog = Dialog(
                tr("Grand Prix beenden?"),
                tr("Die Serie endet für alle Mitspieler."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")])
        else:
            # Ehrlich formuliert: die Punkte bleiben beim Gastgeber stehen.
            # Wer zurueckkommt, faehrt mit seinem Stand weiter — frueheren
            # Mitgliedern laesst der Server den Wiedereinstieg ausdruecklich zu.
            self._dialog = Dialog(
                tr("Grand Prix verlassen?"),
                tr("Du verlässt die Lobby und fährst nicht weiter mit."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")])

    def _confirm_leave_gp(self) -> None:
        """Verlassen bestaetigt.

        Der Host beendet die Serie fuer alle: er verteilt gp_active=False,
        woraufhin die Gaeste ueber die Phase automatisch zurueck in die Lobby
        wechseln. Ein Gast verlaesst nur sich selbst.
        """
        from src.core import grand_prix
        if self._is_host:
            grand_prix.cancel()
            self._leave_gp_overview()
            self._melde(tr("Grand Prix beendet."))
        else:
            # Ein Gast, der nur in die Lobby zurueckginge, waere gar nicht raus:
            # der naechste START holt ihn ins Rennen und er wird weiter
            # gewertet. Verlassen heisst deshalb: Verbindung trennen.
            self._cleanup_net()
            self._gp_ui = None
            self._gp_phase = "lobby"
            self._view = _ROLE
            self._melde(tr("Du hast den Grand Prix verlassen."))

    def _draw_gp_overview(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        if self._gp_ui is None:
            return
        from src.net import session
        net = session.get()
        # Gast: Liste und Markierung kommen vom Host, nicht aus eigenen Dateien.
        if not self._is_host:
            if self._gp_ui.set_host_tracks(self._gp_view.get("gp_tracks") or []):
                self._gp_ui.move(0)
        if self._gp_ist_beendet():
            self._gp_ui.draw_ceremony(
                screen, gp_view=self._gp_view, players=self._players,
                eigener_slot=net.slot if net else -1,
            )
        else:
            # Der Host liest seine eigene Wahl lokal: der verteilte Schluessel
            # kommt erst mit dem Echo des Servers zurueck, die Markierung
            # haette also immer einen Schritt hinterhergehinkt.
            eigene = self._gp_ui.key_for_path(self._selected_track_path)
            gewaehlt = eigene if self._is_host else (
                self._gp_view.get("gp_track_key") or eigene)
            self._gp_ui.draw(
                screen,
                offers=self._offers,
                offers_aktiv=self._offers_aktiv(),
                gewaehlt_key=gewaehlt,
                ist_host=self._is_host,
                gp_view=self._gp_view,
                players=self._players,
                eigener_slot=net.slot if net else -1,
            )
        # Jedes Bild geprueft: Bereit-Meldungen kommen ueber das Netz, nicht
        # ueber eine Eingabe, bei der man den Knopf nachziehen koennte.
        self._update_gp_start_button()
        self._gp_group.draw(screen)
        if self._offer_pick is not None:
            self._draw_offer_picker(screen, area)
        if self._msg:
            theme.text(screen, tr(self._msg), theme.BODY, theme.DANGER,
                       (area.centerx, area.bottom - 30), center=True)

    def _draw_offer_picker(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        """Eigene Strecken zur Auswahl. Bewusst schlicht und mittig: es ist ein
        Zwischenschritt, keine zweite Streckenauswahl."""
        gruppe = self._offer_pick_group
        if gruppe is None:
            return
        sichtbar = min(len(self._offer_rows), _OFFER_PICK_ROWS)
        rect = self._offer_pick_rect(sichtbar)
        flaeche = pygame.Surface(rect.size, pygame.SRCALPHA)
        flaeche.fill((14, 16, 22, 245))
        screen.blit(flaeche, rect.topleft)
        pygame.draw.rect(screen, theme.ACCENT, rect, 2, border_radius=10)

        theme.text(screen, tr("Welche Strecke anbieten?"), theme.HEADER, theme.ACCENT,
                   (rect.centerx, rect.y + 34), center=True)

        # Die gewaehlte Zeile bleibt markiert, auch wenn der Fokus schon auf
        # dem Knopf steht - sonst laedt man auf gut Glueck hoch.
        gewaehlt = self._offer_rows[self._offer_pick_cursor] \
            if 0 <= self._offer_pick_cursor < len(self._offer_rows) else None
        if gewaehlt is not None and gewaehlt.rect.width > 0:
            pygame.draw.rect(screen, theme.ACCENT,
                             gewaehlt.rect.inflate(10, 8), 2, border_radius=8)
        gruppe.draw(screen)

        if len(self._offer_rows) > sichtbar:
            self._draw_offer_pick_scrollbar(screen, rect, sichtbar)

    def _lobby_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            # Frueher trennte ein Tastendruck sofort die Verbindung - und beim
            # Host loeste das die ganze Lobby auf. Ein Fehlgriff auf ESC ist zu
            # billig fuer eine Folge, die niemand rueckgaengig machen kann.
            self._ask_leave_lobby()
            return

        old_laps  = self._laps_stepper.index
        old_mode  = self._mode_stepper.index
        old_size  = self._size_stepper.index
        old_class = self._class_stepper.index
        action = self._lobby_group.handle_event(event)

        if action == "pick_track" and self._is_host:
            self._navigate_to_track_select()
            return

        if action == "pick_vehicle":
            self._navigate_to_car_select()
            return

        if action == "toggle_ready":
            self._toggle_ready()
            return

        if action == "start" and self._is_host:
            # Grand Prix: die Lobby richtet nur ein. Gefahren wird aus der
            # Uebersicht heraus, dort waehlt der Host vor jedem Lauf die Strecke.
            if self._selected_mode == "Grand Prix" and self._gp_phase != "overview":
                if not self._all_lobby_ready():
                    self._msg = "Nicht alle Spieler sind bereit."
                    return
                from src.core import grand_prix
                if not grand_prix.is_active():
                    grand_prix.start_series(int(self._gp_races_stepper.value),
                                            self._selected_laps)
                self._enter_gp_overview()
                return
            self._request_start()
            return

        if action == "set_team" and self._team_stepper is not None:
            self._my_team = "B" if self._team_stepper.index == 1 else "A"
            from src.net import session
            net = session.get()
            if net:
                net.send_tcp({"type": "SET_TEAM", "team": self._my_team})
            return

        if action and action.startswith("ai_veh_"):
            j = int(action.split("_")[-1])
            if j < len(self._roster_ai_widgets):
                v_s, _, _t = self._roster_ai_widgets[j]
                v_s.driver_ref.vehicle = v_s.veh_keys[v_s.index]
            self._push_settings()
            return

        if action and action.startswith("ai_diff_"):
            j = int(action.split("_")[-1])
            if j < len(self._roster_ai_widgets):
                _, d_s, _t = self._roster_ai_widgets[j]
                d_s.driver_ref.difficulty = d_s.diff_keys[d_s.index]
            self._push_settings()
            return

        if action and action.startswith("ai_team_"):
            j = int(action.split("_")[-1])
            if j < len(self._roster_ai_widgets):
                _, _, t_s = self._roster_ai_widgets[j]
                if t_s is not None:
                    t_s.driver_ref.team = "B" if t_s.index == 1 else "A"
            self._push_settings()
            return

        mode_changed  = self._is_host and self._mode_stepper.index != old_mode
        size_changed  = self._is_host and self._size_stepper.index != old_size
        class_changed = self._is_host and self._class_stepper.index != old_class
        laps_changed  = self._is_host and self._laps_stepper.index != old_laps

        if mode_changed:
            self._selected_mode = _MODE_KEYS[self._mode_stepper.index]
            # Weg von Grand Prix heisst: Serie beenden. Sonst laeuft sie im
            # Hintergrund weiter und _ist_gp_modus haelt den Host in einer
            # Serie fest, die er gerade verlassen hat.
            if self._selected_mode != "Grand Prix":
                from src.core import grand_prix
                grand_prix.cancel()
            # Der Modus kann die Fahrzeugzahl mitziehen (3 oder 5 gehen im
            # Team-Zeitfahren nicht), und dann braucht das KI-Feld eine neue
            # Besetzung. Ohne diesen Abgleich standen im Feld Zeilen, die nur
            # „KI 3", „KI 4" hiessen und sich nicht einstellen liessen — genau
            # die Meldung vom 04.08.2026.
            self._groesse_setzen(self._roster_size)
            self._sync_ai_roster()
            self._rebuild_roster_widgets()
            self._refresh_focus_group()
        if size_changed:
            # Aus der Liste, die der Stepper GERADE traegt. Vorher stand hier
            # fest _SIZE_OPTIONS, im Team-Zeitfahren traegt er aber [4, 6]:
            # „4" ergab damit 2 Plaetze und „6" ergab 3.
            erlaubt = self._groessen()
            i = max(0, min(self._size_stepper.index, len(erlaubt) - 1))
            self._groesse_setzen(erlaubt[i])
            self._sync_ai_roster()
            self._rebuild_roster_widgets()
            self._refresh_focus_group()
        if class_changed:
            self._selected_class = self._class_keys_list[self._class_stepper.index]
            self._enforce_vehicle_class()
            # sync_ai_roster drops any AI car that is no longer in the class,
            # so the roster we push is already valid.
            self._sync_ai_roster()
            self._rebuild_roster_widgets()
            self._refresh_focus_group()

        if laps_changed or mode_changed or size_changed or class_changed:
            self._push_settings()

    # ── Draw ─────────────────────────────────────────────────────────────────

    #: Wo der eigene Rueckweg steht, wenn es keinen anderen gibt. Der Titel
    #: rueckt dafuer nach rechts.
    ZURUECK_VERSATZ = (80, 16)
    #: Unten links: oben ist hier kein Platz (gemeldet 05.08.2026).
    ZURUECK_UNTEN = True

    #: Ebenen, in denen es schon einen sichtbaren Rueckweg gibt: die
    #: Serverauswahl und die Beitrittsansicht tragen ihr eigenes „‹ Zurueck".
    #: Ein zweiter Knopf daneben waere eine Frage, keine Hilfe.
    #:
    #: Die Grand-Prix-Uebersicht gehoert seit dem 05.08.2026 dazu: „In der Grand
    #: Prix Übersicht ist der Back Button unnötig da es Leave Grand Prix gibt."
    #: Beide fuehrten ohnehin auf dieselbe Rueckfrage (``_ask_leave_gp``) — und
    #: eine Serie zu beenden ist keine Ebene hoch, der benannte Knopf sagt das
    #: und „‹ Zurueck" sagt es nicht. Die Uebersicht des Einzelspielers
    #: (``gp_overview_page``) hatte aus demselben Grund nie einen.
    _HAT_EIGENEN_RUECKWEG = (_HOST_SERVER, _JOIN, _CONNECTING, _GP_OVERVIEW)

    def zurueck(self) -> None:
        """Eine Ebene hoch — je nachdem, in welcher man steht.

        Aus der Lobby heraus wird gefragt: beim Gastgeber loest das Verlassen die
        ganze Lobby auf, und ein Fehlgriff ist zu billig fuer eine Folge, die
        niemand ruecknehmen kann. Dieselbe Stelle bedient ESC.
        """
        if self._view == _LOBBY:
            self._ask_leave_lobby()
        elif self._view == _GP_OVERVIEW:
            self._ask_leave_gp()
        elif self._view in (_HOST_SERVER, _JOIN):
            self._msg = ""
            self._return_view = _ROLE
            self._view = _ROLE
        elif self._view == _CONNECTING:
            self._cleanup_net()
            self._view = self._return_view
        else:
            self.shell.pop_page()

    def draw(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        # Titel zurück nach links gerückt — der Zurück-Knopf sitzt jetzt unten links,
        # nicht oben links. Der alte x=290-Versatz war nur nötig, um Platz zu schaffen.
        theme.text(screen, tr("MEHRSPIELER ONLINE"), theme.HEADER, theme.ACCENT, (80, 128))
        if self._view not in self._HAT_EIGENEN_RUECKWEG:
            self.zurueck_zeichnen(screen, area)

        if self._view == _ROLE:
            self._draw_role(screen, area)
        elif self._view == _HOST_SERVER:
            self._draw_host_server(screen, area)
        elif self._view == _JOIN:
            self._draw_join(screen, area)
        elif self._view == _CONNECTING:
            self._draw_connecting(screen, area)
        elif self._view == _LOBBY:
            self._draw_lobby(screen, area)
        elif self._view == _GP_OVERVIEW:
            self._draw_gp_overview(screen, area)

        # Only the lobby keeps a footer status line. The pre-lobby views place
        # their messages next to the control that caused them.
        if self._msg and self._view == _LOBBY:
            theme.text(screen, tr(self._msg), theme.BODY, theme.DANGER,
                       (area.centerx, area.bottom - 84), center=True)

        # Vorwarnung vor dem Leerlauf-Schluss. Gilt in beiden Ebenen, denn in
        # beiden kann eine Gruppe stehenbleiben.
        if self._warn_msg and self._view in (_LOBBY, _GP_OVERVIEW):
            theme.text(screen, self._warn_msg, theme.BODY, theme.DANGER,
                       (area.centerx, area.bottom - 120), center=True)

        if self._dialog is not None:
            self._dialog.draw(screen)

        if self.osk:
            self.osk.draw(screen)
        else:
            from src.ui import hints
            theme.text(
                screen,
                hints.bar(("confirm", tr("Auswählen")), ("back", tr("Zurück"))),
                theme.HINT, theme.TEXT_DIM, (area.centerx, area.bottom - 40), center=True,
            )

    def _draw_role(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        cx = area.centerx
        theme.text(screen, tr("Als Gastgeber oder Gast spielen?"), theme.TITLE, theme.TEXT,
                   (cx, 210), center=True)
        theme.text(screen, tr("Als Gastgeber wählst du den Server und die Renneinstellungen."),
                   theme.BODY, theme.TEXT_DIM, (cx, 262), center=True)
        self._role_group.draw(screen)
        theme.text(screen, tr("Spielst du unter dem Namen {n} — änderbar in den Einstellungen.")
                   .format(n=self._player_name()),
                   theme.HINT, theme.TEXT_FAINT, (cx, 520), center=True)
        if self._msg:
            theme.text(screen, tr(self._msg), theme.BODY, theme.DANGER, (cx, 570), center=True)

    def _draw_host_server(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        cx = area.centerx
        theme.text(screen, tr("Server wählen"), theme.TITLE, theme.TEXT, (cx, 176), center=True)
        theme.text(screen, tr("Der Ping gilt für dich — deine Mitspieler sehen eigene Werte."),
                   theme.BODY, theme.TEXT_DIM, (cx, 226), center=True)

        # Spaltenüberschriften: dieselben Offsets wie die Zeilen selbst, damit
        # Überschrift und Wert übereinanderstehen. Vorher waren sie relativ zur
        # Zeilenbreite gerechnet und liefen in die Unterschrift der Seite.
        if self._server_rows:
            row = self._server_rows[0]
            head_y = row.rect.y - 30
            theme.text(screen, tr("Standort"), theme.SMALL, theme.TEXT_FAINT,
                       (row.rect.x + ServerRow.COL_NAME, head_y))
            theme.text(screen, tr("Qualität"), theme.SMALL, theme.TEXT_FAINT,
                       (row.rect.x + ServerRow.COL_BARS, head_y))
            theme.text(screen, tr("Ping"), theme.SMALL, theme.TEXT_FAINT,
                       (row.rect.x + ServerRow.COL_PING, head_y), topright=True)
            theme.text(screen, tr("Lobbys"), theme.SMALL, theme.TEXT_FAINT,
                       (row.rect.right - 20, head_y), topright=True)

        self._host_group.draw(screen)

        if self._msg:
            theme.text(screen, tr(self._msg), theme.BODY, theme.DANGER,
                       (cx - 420, self._btn_create.rect.centery - 16))

    def _draw_join(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        cx = area.centerx
        theme.text(screen, tr("Lobby beitreten"), theme.TITLE, theme.TEXT, (cx, 200), center=True)
        theme.text(screen, tr("Lobby-Code (6 Zeichen)"), theme.LABEL, theme.TEXT_DIM,
                   (cx - 300, 286))
        self._join_group.draw(screen)
        if self._msg:
            theme.text(screen, tr(self._msg), theme.BODY, theme.DANGER, (cx - 300, 396))

    def _draw_connecting(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        dots = "." * (1 + int(self._time * 2) % 3)
        theme.text(screen, tr("Verbinde mit Server") + dots, theme.TITLE, theme.ACCENT,
                   area.center, center=True)
        label = tr(self._connect_server.label) if self._connect_server else ""
        theme.text(screen, label, theme.BODY, theme.TEXT_DIM,
                   (area.centerx, area.centery + 60), center=True)

    def _draw_lobby(self, screen: pygame.Surface, area: pygame.Rect) -> None:
        from src.net import session
        net = session.get()
        focused = self._lobby_group.focused

        # ── Left panel ────────────────────────────────────────────────────────
        x = 80
        theme.text(screen, tr("EINSTELLUNGEN"), theme.LABEL, theme.TEXT_DIM, (x, 165))

        if self._is_host:
            for widget in self._host_column_widgets():
                widget.draw(screen, focused is widget)
            self._btn_ready.draw(screen,   focused is self._btn_ready)

            saved_label   = self._btn_start.label
            start_enabled = self._all_lobby_ready()
            if not self._btn_start.enabled:
                self._btn_start.label = "Teams nicht ausgeglichen"  # tr() applied by widget
            elif not start_enabled:
                self._btn_start.label = "WARTE AUF ALLE BEREIT..."  # tr() applied by widget
            self._btn_start.draw(screen, focused is self._btn_start)
            self._btn_start.label = saved_label
        else:
            # Guest sees the host-only steppers (Modus/Fahrzeuge/Klasse) as
            # static text, same pattern as the existing Strecke/Runden lines.
            lines = [(tr("Modus:"), tr(self._selected_mode))]
            if self._selected_mode == "Team-Zeitfahren":
                lines.append((tr("Fahrzeuge:"), str(self._roster_size)))
            if self._selected_mode == "Grand Prix":
                # Ueber wie viele Rennen es geht, stand hier nicht - der Gast
                # sah die Laenge der Serie erst in der Uebersicht.
                lines.append((tr("Rennen:"),
                              str(payload.as_int(self._gp_view.get("gp_races"), 0) or "—")))
            cls_label = tr("Beliebig") if self._selected_class == "Alle" else tr(self._selected_class)

            lines.append((tr("Klasse:"), cls_label))
            tn = _track_name_from_path(self._selected_track_path)
            lines.append((tr("Strecke:"), tn))
            lines.append((tr("Runden:"), str(self._selected_laps)))

            ly = 192
            for label, value in lines:
                theme.text(screen, f"{label}        {value}",
                           theme.BODY, theme.TEXT, (x + 16, ly))
                ly += 32
            # AI difficulty is shown per driver in the right-hand roster, so no
            # separate left-side "Schwierigkeit" line for the client.
            pygame.draw.line(screen, theme.BORDER, (x, 360), (x + 700, 360), 1)
            self._btn_vehicle_c.draw(screen, focused is self._btn_vehicle_c)
            self._btn_ready_c.draw(screen,   focused is self._btn_ready_c)
            theme.text(screen, tr("Warte auf Host-Start ..."),
                       theme.BODY, theme.TEXT_DIM, (x + 16, 570))

        # ── Right panel ────────────────────────────────────────────────────────
        rx = _RX
        ry = 155

        # Lobby-Code (compact)
        theme.text(screen, tr("LOBBY-CODE"), theme.LABEL, theme.TEXT_DIM, (rx, ry))
        code_surf = theme.font(theme.TITLE).render(self._lobby_id, True, theme.ACCENT)
        screen.blit(code_surf, (rx, ry + 24))

        # Which relay this lobby lives on — guests get it too, since the code
        # prefix decided it for them.
        if self._connect_server is not None:
            srv_txt = tr("Server: {name}").format(name=tr(self._connect_server.label))
            if net and net.ping_ms:
                srv_txt += f"  ·  {net.ping_ms:.0f} ms"
            theme.text(screen, srv_txt, theme.LABEL, theme.TEXT_DIM,
                       (rx + 850, ry + 4), topright=True)
        pygame.draw.line(screen, theme.BORDER, (rx, ry + 110), (rx + 850, ry + 110), 1)

        # Roster header
        roster_lbl_y = ry + 125
        theme.text(screen, tr("SPIELER & KI-FAHRER"), theme.LABEL, theme.TEXT_DIM,
                   (rx, roster_lbl_y))

        team_mode = self._selected_mode == "Team-Zeitfahren"

        # Column headers
        col_hdr_y = roster_lbl_y + 30
        theme.text(screen, tr("Name"),
                   theme.SMALL, theme.TEXT_FAINT, (rx + _COL_NAME, col_hdr_y))
        theme.text(screen, tr("Fahrzeug"),
                   theme.SMALL, theme.TEXT_FAINT, (rx + _COL_VEH,  col_hdr_y))
        theme.text(screen, tr("KI-Stärke"),
                   theme.SMALL, theme.TEXT_FAINT, (rx + _COL_DIFF, col_hdr_y))
        if team_mode:
            theme.text(screen, tr("Team"),
                       theme.SMALL, theme.TEXT_FAINT, (rx + _COL_TEAM, col_hdr_y))
        pygame.draw.line(screen, theme.BORDER,
                         (rx, col_hdr_y + 22), (rx + 850, col_hdr_y + 22), 1)

        # Roster rows
        my_slot         = net.slot if net else -1
        players_by_slot = {p["slot"]: p for p in self._players}
        ai_by_slot      = {
            slot: self._roster_ai_widgets[j]
            for j, slot in enumerate(self._roster_free_slots)
            if j < len(self._roster_ai_widgets)
        }

        from src.core import race_setup
        ai_roster = race_setup.current().ai_roster

        def _team_color(team: str):
            return (255, 120, 0) if team == "A" else (0, 140, 255)

        def _team_label(team: str) -> str:
            return tr("Team A") if team == "A" else tr("Team B")

        for slot in range(self._roster_size):
            row_y  = _ROW_START_Y + slot * _ROW_STRIDE
            text_y = row_y + 15   # vertical offset for text within 56px row

            if slot in players_by_slot:
                p         = players_by_slot[slot]
                is_me     = (p.get("slot") == my_slot)
                is_phost  = p.get("is_host", False)
                ready     = p.get("lobby_ready", False)
                vehicle   = p.get("vehicle", "")
                vname     = _vehicle_display_name(vehicle) if vehicle else "—"
                raw_name  = p.get("name", "?")[:13]

                # Build name string with compact badges
                badge = ""
                if is_phost:
                    badge += " ♦"
                if is_me:
                    badge += f" ({tr('Du')})"
                display_name = f"● {raw_name}{badge}"
                name_col     = theme.ACCENT if is_me else theme.TEXT

                # Highlight own row
                if is_me:
                    bg_r = pygame.Rect(rx - 4, row_y - 2, 858, _ROW_H + 4)
                    bg_s = pygame.Surface(bg_r.size, pygame.SRCALPHA)
                    bg_s.fill((*theme.PANEL_SEL, 90))
                    screen.blit(bg_s, bg_r.topleft)

                name_rect = pygame.Rect(rx + _COL_NAME, row_y, 220, _ROW_H)
                theme.text_fit(screen, display_name, theme.BODY, name_col, name_rect, center=False)
                theme.text(screen, vname, theme.BODY, theme.TEXT_DIM,
                           (rx + _COL_VEH, text_y))

                ready_col = (80, 220, 80) if ready else theme.TEXT_DIM
                ready_txt = (f"{theme.HAKEN} " + tr("Bereit")) if ready else tr("Warte…")
                theme.text(screen, ready_txt, theme.BODY, ready_col,
                           (rx + _COL_DIFF, text_y))

                if team_mode:
                    p_team = p.get("team", "A")
                    if is_me and self._team_stepper is not None:
                        self._team_stepper.rect.y = row_y
                        self._team_stepper.draw(screen, focused is self._team_stepper)
                    else:
                        theme.text(screen, _team_label(p_team), theme.BODY,
                                   _team_color(p_team), (rx + _COL_TEAM, text_y))

            else:
                # AI slot
                ai_idx  = self._roster_free_slots.index(slot) \
                    if slot in self._roster_free_slots else -1
                ai_name = (ai_roster[ai_idx].name
                           if 0 <= ai_idx < len(ai_roster)
                           else f"KI {slot + 1}")

                ai_rect = pygame.Rect(rx + _COL_NAME, row_y, 220, _ROW_H)
                theme.text_fit(screen, f"○ {ai_name}", theme.BODY, theme.TEXT_DIM, ai_rect, center=False)

                if slot in ai_by_slot and self._is_host:
                    v_s, d_s, t_s = ai_by_slot[slot]
                    v_s.draw(screen, focused is v_s)
                    d_s.draw(screen, focused is d_s)
                    if team_mode and t_s is not None:
                        t_s.draw(screen, focused is t_s)
                else:
                    # Client: show current values as static text
                    if 0 <= ai_idx < len(ai_roster):
                        vn = _vehicle_display_name(ai_roster[ai_idx].vehicle)
                        dk = ai_roster[ai_idx].difficulty
                        dl = (_DIFF_LABELS[_DIFF_KEYS.index(dk)]
                              if dk in _DIFF_KEYS else dk)
                        ai_team = ai_roster[ai_idx].team
                    else:
                        vn = "—"
                        dl = "—"
                        ai_team = "A"
                    theme.text(screen, vn, theme.BODY, theme.TEXT_FAINT,
                               (rx + _COL_VEH,  text_y))
                    theme.text(screen, dl, theme.BODY, theme.TEXT_FAINT,
                               (rx + _COL_DIFF, text_y))
                    if team_mode:
                        theme.text(screen, _team_label(ai_team), theme.BODY,
                                   _team_color(ai_team), (rx + _COL_TEAM, text_y))

        # Horizontal dividers between rows (skip first — col-header line covers it)
        for i in range(1, self._roster_size + 1):
            div_y = _ROW_START_Y + i * _ROW_STRIDE - 4
            pygame.draw.line(screen, theme.BORDER, (rx, div_y), (rx + 850, div_y), 1)

        # Balance display (Team-Zeitfahren only) + Ping
        row_after_roster_y = _ROW_START_Y + self._roster_size * _ROW_STRIDE + 14
        if team_mode:
            bal_a = self._team_balance.get("A", 0)
            bal_b = self._team_balance.get("B", 0)
            bal_ok = self._team_balance.get("ok", True)
            bal_col = (100, 220, 100) if bal_ok else theme.DANGER
            bal_txt = f"{tr('Team A')}: {bal_a}  ·  {tr('Team B')}: {bal_b}"
            if bal_ok:
                bal_txt += f"  {theme.HAKEN}"
            theme.text(screen, bal_txt, theme.BODY, bal_col, (rx, row_after_roster_y))
            if not bal_ok:
                theme.text(screen, tr("Teams nicht ausgeglichen"), theme.BODY, theme.DANGER,
                           (rx, row_after_roster_y + 26))
                ping_y = row_after_roster_y + 56
            else:
                ping_y = row_after_roster_y + 30
        else:
            ping_y = row_after_roster_y

        if net:
            pm = net.ping_ms
            pcol = (
                (100, 220, 100) if pm < 60
                else (255, 200, 0) if pm < 120
                else theme.DANGER
            )
            theme.text(screen, tr("Mein Ping:") + f"  {pm:.0f} ms", theme.BODY, pcol, (rx, ping_y))
        else:
            theme.text(screen, tr("Kein Netzwerk"), theme.BODY, theme.DANGER, (rx, ping_y))

        self._draw_gp_standings(screen, rx + 560, ping_y - 30)

    def _draw_gp_standings(self, screen: pygame.Surface, x: int, y: int) -> None:
        """Zwischenstand der Serie.

        Quelle ist immer der vom Host verteilte Zustand — auch beim Host selbst.
        Sonst könnten Anzeige und Verteiltes auseinanderlaufen, und niemand
        merkt es, weil beim Host zufällig beides stimmt.
        """
        stand = self._gp_view.get("gp_standings")
        if not self._gp_view.get("gp_active") or not isinstance(stand, list):
            return

        theme.text(screen, tr("GRAND-PRIX-WERTUNG"), theme.LABEL, theme.ACCENT, (x, y))
        theme.text(screen, tr("Lauf {i} von {n}").format(
            i=self._gp_view.get("gp_race", 1), n=self._gp_view.get("gp_total", 1)),
            theme.SMALL, theme.TEXT_FAINT, (x, y + 26))

        zy = y + 54
        for rang, eintrag in enumerate(payload.dict_entries(stand)[:6], start=1):
            name = str(eintrag.get("name", ""))[:16]
            punkte = payload.as_int(eintrag.get("points"), 0)
            farbe = theme.ACCENT if rang == 1 else theme.TEXT
            theme.text(screen, f"{rang}.", theme.LABEL, theme.TEXT_FAINT, (x, zy))
            theme.text(screen, name, theme.LABEL, farbe, (x + 34, zy))
            theme.text(screen, str(punkte), theme.LABEL, farbe, (x + 250, zy), midright=True)
            zy += 30

    def exit(self) -> None:
        from src.net import server_probe
        server_probe.stop()
