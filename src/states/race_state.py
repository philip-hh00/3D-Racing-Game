"""Race state – handles the active racing gameplay."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import pygame

from src.states.base_state import BaseState
from src.core.settings import (
    SCREEN_WIDTH, SCREEN_HEIGHT, DEBUG, M_PER_PX,
    AI_OPPONENT_COUNT, AI_DEFAULT_DIFFICULTY, AI_VEHICLE_KEYS,
)
from src.core.event_bus import EventBus
from src.physics.physics_world import PhysicsWorld
from src.physics.collision_handler import CollisionHandler
from src.net import payload
from src.track.track import Track, TrackDataError
from src.entities.player_vehicle import PlayerVehicle
from src.entities.vehicle import VehicleConfig
from src.hud.hud import HUD
from src.physics.checkpoint import Checkpoint
from src.states.race_manager import RaceManager
from src.core.i18n import tr
from src.ui import theme

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine

# Team-Zeitfahren: a driver that never finished is not simply dropped from the
# average — that would reward giving up. It is scored as the last finisher's
# time plus this penalty.
DNF_PENALTY = 30.0
# Used when nobody finished at all, so the average stays a finite number.
DNF_FALLBACK_TIME = 300.0

# Die Rennwelt wird in 3D gezeichnet. Sichtfeld und Schnittebenen der
# Verfolgerkamera - dieselben Werte wie in tools/fahrtest.py, an dem sie
# eingestellt wurden.
SICHTFELD_GRAD = 55.0
NAHE_EBENE_M = 0.2
FERNE_EBENE_M = 1200.0
KAMERA_ABSTAND_M = 7.5
KAMERA_HOEHE_M = 2.8
KAMERA_ZIELHOEHE_M = 1.0

# Kennung des Ghosts unter den Fahrzeugstaenden. Negativ, damit sie mit keiner
# echten Fahrzeug-Id zusammenfaellt.
GHOST_KENNUNG = -1

# Obergrenze fuer den Weg, den ein Fahrzeug in einem Bild zurueckgelegt haben
# kann. Ein Sprung - Ruecksetzen an den Start, eine verspaetete Netznachricht -
# ist kein gefahrener Weg, und ohne Deckel wuerden sich die Raeder danach
# einmal wild um sich selbst drehen.
WEG_JE_BILD_HOECHSTENS_M = 20.0


def welt3d(pos_px) -> tuple[float, float, float]:
    """Eine Spielposition in Pixeln als Weltpunkt in Metern.

    pymunk rechnet Y nach oben, die 3D-Welt auch — hier wird also **nicht**
    gespiegelt. ``to_pygame`` in ``src/utils/math_utils.py`` gehoert zum
    2D-Zeichnen, wo pygame Y nach unten zaehlt, und hat hier nichts verloren.
    Genau dieser Griff hat in der Vorbereitung schon einmal Zeit gekostet.
    """
    return (pos_px[0] * M_PER_PX, pos_px[1] * M_PER_PX, 0.0)

# Online: an AI that inherits a dropped player's car gets an id far outside the
# regular 1..N range so it can never collide with a locally spawned vehicle.
TAKEOVER_ID_BASE = 200

# Online position streaming. A bump is the one moment where the peers' physics
# disagree hard — each side treats the other's car as immovable — so positions
# diverge fastest exactly when the correction is most visible. Sending denser
# updates for a moment afterwards keeps every correction small.
# Position send rate. Higher is better up to the sender's frame rate (sending
# is frame-coupled — one packet per frame at most) and its physics step (the
# position only changes per step). 50 Hz halves the packet spacing vs the old
# 30 Hz, which lets the receiver's INTERP_DELAY shrink and the ghost trail the
# real car less. Bandwidth stays tiny: a host streaming 4 cars is ~6 KB/s.
SEND_HZ_NORMAL  = 50.0
SEND_HZ_CONTACT = 60.0   # briefly denser after a bump (capped by 60 fps host)
CONTACT_BOOST_SECONDS = 1.0

# When a car is forced to DNF (grace window expired), it rolls on with no
# input for this long before the results screen appears — a visible "your race
# is over" beat rather than a hard cut.
DNF_COAST_SECONDS = 2.0

# Kurze Nachlaufzeit mit Ausblenden, bevor der Ergebnisschirm kommt (08.08.2026).
# Gemeldet: der Schirm kam uebergangslos, sobald der Letzte ueber die Linie fuhr
# oder DNF war — "als wuerde er einem ins Gesicht geschmissen". Die Welt laeuft
# weiter, ein schwarzer Schleier zieht auf; danach der Schnitt in die Ergebnisse.
RESULTS_OUTRO_SECONDS = 1.2


def score_team_rows(rows: list[dict]) -> tuple[float, float]:
    """Write ``score_time`` into every row and return (team_a_avg, team_b_avg).

    Kept as a free function so the scoring rule can be tested without a running
    race — it is the one piece of Team-Zeitfahren that both the offline race
    and the online combined standings depend on.
    """
    last_finisher_time = 0.0
    for row in rows:
        if not row.get("dnf") and row.get("finish_time") is not None:
            last_finisher_time = max(last_finisher_time, row["finish_time"])
    if last_finisher_time == 0.0:
        last_finisher_time = DNF_FALLBACK_TIME
    penalty_time = last_finisher_time + DNF_PENALTY

    for row in rows:
        if row.get("dnf") or row.get("finish_time") is None:
            row["score_time"] = penalty_time
        else:
            row["score_time"] = row["finish_time"]

    def _avg(team: str) -> float:
        times = [r["score_time"] for r in rows if r.get("team") == team]
        return sum(times) / len(times) if times else 0.0

    return _avg("A"), _avg("B")


#: Nach so vielen Sekunden Warten auf die Mitspieler bekommt der Host einen
#: Abbruchknopf. Bewusst nur ein Angebot und kein automatischer Abbruch: die
#: Gegenseite laedt womoeglich noch eine uebertragene Strecke und rechnet
#: Ideallinien - ein automatischer Abbruch wuerde funktionierende Rennen
#: zerreissen. Der Host sieht die Lage und entscheidet.
HOLD_ABORT_BUTTON_AFTER_S = 5.0


class RaceState(BaseState):
    """The main racing state, managing the physics simulation, entities, camera, and HUD."""

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.physics_world: PhysicsWorld | None = None
        self.collision_handler: CollisionHandler | None = None
        self.track: Track | None = None
        self.player: PlayerVehicle | None = None
        self.ai_vehicles: list[Any] = []
        self._line_geo = None
        #: Die 3D-Welt. ``None``, wenn kein OpenGL da ist (Testlauf) - dann
        #: wird keine Welt gezeichnet, alles andere laeuft weiter.
        self.szene = None
        self.camera = None
        self._kameras: list = []
        #: Was in diesem Bild gezeichnet werden soll. In update() gefuellt,
        #: in render() nur noch gelesen.
        self._staende: list = []
        #: Letzte Sicht als (mvp, ansichtsfenster, briefkasten). Nur fuer
        #: Werkzeuge, die Weltpunkte auf den Bildschirm rechnen muessen -
        #: das KI-Labor zeichnet seine Wegpunkte darueber.
        self._letzte_sicht = None
        self._ghost_letzte_pos: tuple[float, float] | None = None
        self.hud: HUD | None = None
        self.event_bus = EventBus()
        self.quit_requested: bool = False
        self.checkpoints: list[Checkpoint] = []
        self.race_manager: RaceManager | None = None
        # Auch von exit() gelesen. enter() setzt das neu, kann aber bei einer
        # unlesbaren Strecke vorher abbrechen - dann muss der Aufraeumpfad
        # trotzdem durchlaufen.
        self.ghost_recorders: dict = {}
        self._load_failed: str = ""
        self._load_failed_handled: bool = False
        #: (Text, Restzeit) der Rueckmeldung des Klangmitschnitts (F9).
        self._mitschnitt_hinweis: tuple[str, float] | None = None

        # Rolling average for FPS calculation
        self._fps_filtered: float = 60.0

        #: Das Feld, das **jede** KI sieht: Menschen, KI und die Abbilder der
        #: Mitspieler. Eine Liste, die alle Regler halten — nie ersetzen, nur
        #: fortschreiben, sonst sehen sie wieder verschiedene Felder.
        self._ai_feld: list | None = None

        # Online-multiplayer state (populated by enter() when _online=True)
        self._online: bool = False
        self._remote_vehicles: list = []
        self._remote_map: dict = {}
        self._remote_config_keys: dict = {}
        self._send_accum: float = 0.0
        # Seconds of denser position streaming left after a car-to-car touch.
        self._contact_boost: float = 0.0
        # Online: toasts telling the HUD "X left the race [— AI takes over]".
        self._leave_toasts: list[dict] = []
        self._my_online_slot: int = 0
        #: Motorklang des Rennens (Block C). None, wenn kein Audiogeraet
        #: da ist oder keine Aufnahmen vorliegen - das Rennen laeuft dann
        #: still weiter.
        self._klang = None
        self._startsignal_gespielt = False
        # After finishing an online race, wait for the server to collect every
        # peer's result and broadcast the combined standings before showing them.
        self._online_awaiting: bool = False
        self._online_await_deadline: float = 0.0
        # Beginn des Wartens auf die LOADED-Meldungen. 0 = wir warten nicht.
        self._hold_since: float = 0.0
        self._hold_abort_btn = None
        self._online_results_rows = None   # combined rows from RACE_RESULTS
        # DNF grace coordination (all set fresh in enter()).
        self._first_finish_sent: bool = False   # online: FIRST_FINISH sent once
        self._dnf_coast_timer: float = 0.0      # >0 while a DNF car rolls out
        self._outro_active: bool = False        # >0: Ausblenden vor den Ergebnissen laeuft
        self._outro_timer: float = 0.0
        self._outro_rows = None                 # online: Ergebniszeilen fuer danach

    def enter(self, **kwargs) -> None:
        """Initialize the physics world, load the track, spawn player vehicle, camera, and HUD."""
        self._enter_kwargs = kwargs
        self.paused = False
        self._pause_group = None
        self._pause_view = "main"
        self._pause_settings = None
        self._dialog = None
        self.quit_requested = False
        self._race_music_started = False
        self._startsignal_gespielt = False
        self.physics_world = PhysicsWorld()
        self.collision_handler = CollisionHandler(self.physics_world.space, self.event_bus)

        # Load track dynamically
        track_path = kwargs.get("track_path", "data/tracks/oval.json")
        self._track_path = track_path
        self._load_failed = ""
        self._load_failed_handled = False
        try:
            self.track = Track(track_path, self.physics_world.space)
        except TrackDataError as exc:
            # Kein Absturz mitten im Zustandswechsel: merken und in update()
            # zurueck ins Menue. Direkt hier zu wechseln wuerde transition()
            # rekursiv aufrufen, waehrend dieser Zustand noch aufgebaut wird.
            # update() laeuft vor render(), der halbfertige Zustand wird also
            # nie gezeichnet.
            print(f"[RaceState] Strecke nicht ladbar: {exc}")
            self._load_failed = str(exc)
            return

        # Create checkpoint sensor shapes
        self.checkpoints = []
        for idx, cp_wp in enumerate(self.track.get_checkpoints()):
            # Find the tangent direction of the track at this checkpoint
            center_idx = self.track.get_nearest_waypoint_index((cp_wp.x, cp_wp.y))
            n = len(self.track.centerline)
            p1 = self.track.centerline[center_idx % n]
            p2 = self.track.centerline[(center_idx + 1) % n]
            angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
            
            checkpoint = Checkpoint(
                idx=idx,
                x=cp_wp.x,
                y=cp_wp.y,
                angle_deg=angle,
                track_width=self.track.track_width,
                space=self.physics_world.space,
            )
            self.checkpoints.append(checkpoint)

        # Spawning player vehicle
        # Get first starting position from the track, default to center if none.
        # Online: each peer's own network slot (0 = host, 1..N = joiners) picks the
        # grid slot, so real players don't all spawn on top of grid slot 0.
        start_positions = self.track.get_start_positions()
        online_slot = kwargs.get("online_slot", 0)
        self._my_online_slot = online_slot
        self._online_awaiting = False
        self._first_finish_sent = False
        self._dnf_coast_timer = 0.0
        self._dnf_coast_done = False
        self._outro_active = False
        self._outro_timer = 0.0
        self._outro_rows = None
        self._online_await_deadline = 0.0
        self._hold_since = 0.0
        self._hold_abort_btn = None
        self._online_results_rows = None
        self._results_shown = False
        # Gitterplatz und Netzslot sind zwei Dinge: im Grand Prix bestimmt der
        # Stand der Serie den Platz, gemeldet wird weiter unter dem Netzslot.
        # Ohne die Trennung zeigte die Ergebnistabelle die Bereit-Spalte des
        # falschen Spielers an.
        #
        # Vorlaeufiger Platz. Sobald feststeht, wer sonst noch mitfaehrt, wird
        # er unten aus self._gitter berichtigt — dort erst faellt auf, wenn
        # zwei Fahrzeuge denselben Platz wollen.
        my_slot_idx = kwargs.get("grid_slot", online_slot) if start_positions else 0
        if start_positions:
            start_pos = start_positions[my_slot_idx % len(start_positions)]
            pos = start_pos.pos
            # Convert start angle (in degrees, 0 = east) to radians
            angle = math.radians(start_pos.angle)
        else:
            pos = (1200.0, 600.0)
            angle = 0.0

        # Load vehicle config from kwargs (either a config object or key string)
        config = kwargs.get("vehicle_config", None)
        # Der Schluessel wird getrennt gemerkt: die Lackierung haengt im Profil an
        # ihm, und eine VehicleConfig weiss nicht, unter welchem Namen sie geladen
        # wurde.
        config_key = config if isinstance(config, str) else ""
        if isinstance(config, str):
            from src.entities.vehicle_factory import VehicleFactory
            config = VehicleFactory.get_config(config)
        
        if config is None:
            from src.entities.vehicle_factory import VehicleFactory
            config = VehicleFactory.get_config("rookie") or VehicleConfig()
            config_key = config_key or "rookie"

        from src.core import race_setup, input_source, gamepad
        setup = race_setup.current()
        self._split = setup.is_multiplayer
        self._online = getattr(setup, "_online", False)
        # Gitterplaetze fuer ALLE Fahrzeuge an einer Stelle, bevor eines gebaut
        # wird. Vorher entschied das jeder fuer sich: Spieler 1 aus
        # "grid_slot", Spieler 2 fest auf 1, die KI in einer eigenen Funktion.
        # Im lokalen Mehrspieler-Grand-Prix stand Spieler 1 nach dem ersten
        # Lauf auf Platz 1 der Wertung und teilte sich den Platz mit Spieler 2.
        self._gitter = self._gitter_bauen(kwargs, start_positions, setup)
        if start_positions and self._gitter:
            start_pos = start_positions[self._gitter[0] % len(start_positions)]
            pos = start_pos.pos
            angle = math.radians(start_pos.angle)
        self._online_start_ts = getattr(setup, "_online_start_ts", None)
        self._remote_vehicles = []
        self._remote_map = {}
        self._remote_config_keys = {}
        self._send_accum = 0.0
        self._contact_boost = 0.0
        self._leave_toasts = []
        if self._online:
            self._split = False
            from src.net import session as _sess
            _nc0 = _sess.get()
            if _nc0 is not None:
                _nc0.register_udp()   # refresh the server's UDP address mapping for this race
        # Controllers drive during a race, so switch off the menu translation.

        gamepad.set_menu_translation(False)

        from src.core import profile as _prof
        # Kam die Konfiguration als Objekt statt als Schluessel, steht der
        # Schluessel noch in der Lobbywahl.
        config_key = config_key or setup.player_vehicle or "rookie"
        self.player = PlayerVehicle(
            vehicle_id=1,
            config=config,
            start_pos=pos,
            start_angle=angle,
            space=self.physics_world.space,
            lack=_prof.current().paint(config_key),
            config_key=config_key,
        )
        # Splitscreen: each player has an explicit device. Otherwise (single
        # player, online): accept keyboard AND the first controller.
        self.player.input_source = input_source.make_source(setup.p1_input if self._split else "auto")

        # Local multiplayer: a second human on grid slot 1.
        self.player2 = None
        human_count = 1
        if self._split:
            from src.entities.vehicle_factory import VehicleFactory
            p2cfg = VehicleFactory.get_config(setup.player2_vehicle) or config
            # Vorher fest start_positions[1] — im Grand Prix stand Spieler 1
            # nach dem ersten Lauf ebenfalls dort, und beide Autos spawnten
            # ineinander.
            platz2 = self._gitter[1] if len(self._gitter) > 1 else 1
            slot2 = start_positions[platz2 % len(start_positions)] \
                if start_positions else start_positions[0]
            self.player2 = PlayerVehicle(
                vehicle_id=2, config=p2cfg, start_pos=slot2.pos,
                start_angle=math.radians(slot2.angle), space=self.physics_world.space,
                lack=_prof.current().paint(setup.player2_vehicle),
                config_key=setup.player2_vehicle,
            )
            self.player2.input_source = input_source.make_source(setup.p2_input)
            human_count = 2

        # Spawn AI opponents on the grid slots after the human(s). Online: AI must
        # start after EVERY real human in the lobby (kwargs "online_human_count"),
        # not just the one human this peer simulates locally, else the host's AI
        # spawns on top of the grid slot reserved for the other real player.
        ai_slot_offset = kwargs.get("online_human_count", human_count) if self._online else human_count
        self.ai_vehicles = self._spawn_ai_vehicles(start_positions, kwargs, ai_slot_offset)

        # Driver names: humans from lobby/profile, AI from the random name pool.
        from src.core import profile as _profile, ai_names as _ai_names
        if self._online:
            from src.net import session
            nc = session.get()
            local_slot = nc.slot if nc else 0
            pinfo = setup.online_players.get(local_slot, {})
            local_name = pinfo.get("name", _profile.current().username or "SPIELER")
        else:
            local_name = _profile.current().username or "SPIELER"

        self._driver_names = {1: local_name}
        self.player.driver_name = local_name
        self._vehicle_model = {1: tr(getattr(config, "name", ""))}
        if self.player2 is not None:
            self._driver_names[2] = setup.player2_name
            self.player2.driver_name = setup.player2_name
            self._vehicle_model[2] = tr(getattr(self.player2.config, "name", ""))
        # Assign teams to all vehicles
        self.player.team = setup.p1_team
        if self.player2 is not None:
            self.player2.team = setup.p2_team
        for i, ai in enumerate(self.ai_vehicles):
            if i < len(setup.ai_roster):
                nm = setup.ai_roster[i].name
                ai.team = setup.ai_roster[i].team
            else:
                nm = f"Gegner {i+1}"
                ai.team = "A"
            ai.driver_name = nm
            self._driver_names[ai.id] = nm
            self._vehicle_model[ai.id] = tr(getattr(ai.config, "name", ""))
        self._finish_timer = 0.0
        self._results_sent = False

        self.ghost_player = None
        self.ghost_recorders = {}
        self._ghost_track_key = None
        self._new_ghost_saved = False
        self._original_ghost_sectors = []
        self._original_ghost_lap_time = 9999.0
        self._original_ghost_driver = "Ghost"

        if setup.mode == "Zeitfahren":
            from src.core import ghost
            # Aus dem Pfad, den **dieses Rennen** geladen hat, nicht aus
            # race_setup: das Rennen faehrt kwargs["track_path"], der Ghost las
            # bis zum 07.08.2026 race_setup.current().track_path. Alle Wege im
            # Spiel setzen beides, der Unterschied war also nie zu sehen — aber
            # ein Weg, der es einmal vergisst, laesst den Spieler die eine
            # Strecke fahren und zeigt ihm den Ghost einer anderen.
            self._ghost_track_key = ghost.track_key(self._track_path)

            ghost_data = ghost.load(self._ghost_track_key)
            if ghost_data:
                self.ghost_player = ghost.GhostPlayer(ghost_data)
                self._original_ghost_sectors = list(ghost_data.sectors)
                self._original_ghost_lap_time = ghost_data.lap_time
                self._original_ghost_driver = ghost_data.driver

            self.ghost_recorders = {1: ghost.GhostRecorder()}
            if self.player2:
                self.ghost_recorders[2] = ghost.GhostRecorder()

            # Subscribe to checkpoint crossed for sector splits
            self.event_bus.subscribe("checkpoint_crossed", self._on_checkpoint_crossed_ghost)

        # Verfolgerkameras: eine je Mensch. Im Splitscreen bekommt jede ihre
        # eigene Bildhaelfte, das Seitenverhaeltnis rechnet _welt_zeichnen aus.
        from src.render3d import camera as kamera3d
        self._humans = [self.player] + ([self.player2] if self.player2 else [])
        self._kameras = []
        for hp in self._humans:
            kam = kamera3d.Verfolgerkamera(abstand_m=KAMERA_ABSTAND_M,
                                           hoehe_m=KAMERA_HOEHE_M,
                                           zielhoehe_m=KAMERA_ZIELHOEHE_M)
            # Ohne Nachziehen: zum Start steht die Kamera schon hinter dem
            # Auto und faehrt nicht erst von der Streckenmitte heran.
            kam.setzen(welt3d(hp.position), hp.angle)
            self._kameras.append(kam)
        self.camera = self._kameras[0]
        self._staende = []
        self._ghost_letzte_pos = None
        self._szene_aufbauen()

        # Erst hier: der Klang braucht _humans, und das steht ein paar Zeilen
        # weiter oben erst seit dem Kameraaufbau.
        self._klang_aufbauen()

        self.hud = None
        self.hud1 = None
        self.hud2 = None
        if self._split:
            self.hud1 = HUD()
            self.hud2 = HUD()
        else:
            self.hud = HUD()

        from src.hud.minimap import Minimap
        self.minimap = Minimap(self.track)
        if self._split:
            # Shared minimap, centred along the bottom.
            pw = getattr(self.minimap, "PANEL_W", 300)
            ph = getattr(self.minimap, "PANEL_H", 200)
            self.minimap.pos = (SCREEN_WIDTH // 2 - pw // 2, SCREEN_HEIGHT - ph - 20)

        # Post-finish state: player AI takeover + which cars got the 0.5 slowdown
        self._player_ai_ids: set[int] = set()
        self._finish_applied: set[int] = set()
        self._takeover_lines = {}

        # Initialize Race Manager with all humans and AI opponents.
        total_laps = kwargs.get("total_laps") or race_setup.current().laps
        all_vehicles = [*self._humans, *self.ai_vehicles]
        self.race_manager = RaceManager(
            vehicles=all_vehicles,
            track=self.track,
            total_laps=total_laps,
            # Online: hold the countdown until every peer has loaded (RACE_GO),
            # so the host's longer loading screen doesn't eat its own countdown.
            hold_countdown=self._online,
        )

        # Let each AI see the whole field (for blocking / overtaking).
        #
        # **Eine Liste für alle** (ab 04.08.2026). Vorher bekam jeder Regler hier
        # eine eigene Kopie des Feldes, wie es beim Start aussah — wer später
        # dazukam, war für die KI nicht vorhanden. Online kommen die Abbilder der
        # Mitspieler erst mit der ersten Nachricht, also **immer** später:
        # gemeldet als „KI reagiert nicht auf die anderen Userfahrzeuge".
        # Jetzt halten alle Regler dieselbe Liste, und ``_ai_feld_auffrischen``
        # schreibt sie fort.
        self._ai_feld = []
        for ai in self.ai_vehicles:
            ai.controller.opponents = self._ai_feld
        self._ai_feld_auffrischen()

        # Compute per-vehicle physics-optimised racing lines with a loading screen.
        self._build_racing_lines_optimized()

        # Precompute the AI-takeover racing line for every human car during the
        # loading screen, so crossing the finish line doesn't stall ~350ms on a
        # synchronous solve.
        from src.ai.difficulty import get_difficulty as _get_diff
        _hard = _get_diff("hard")
        for _hp in self._humans:
            _ck = getattr(_hp.config, "name", id(_hp.config))
            if _ck not in self._takeover_lines:
                try:
                    self._takeover_lines[_ck] = self._build_racing_line_for(_hp.config, _hard)
                except Exception:
                    pass

        # Online: tell the server we're done loading. The countdown stays frozen
        # until the server has heard this from everyone and broadcasts RACE_GO.
        if self._online:
            from src.net import session as _sess
            _nc = _sess.get()
            if _nc is not None:
                _nc.send_tcp({"type": "LOADED"})

        # Subscribe to collision and race events
        # Der Klang haengt am IMPULS-Ereignis, nicht am Beruehrungsbeginn: im
        # begin-Rueckruf ist die Wucht noch 0 (04.08.2026).
        self.event_bus.subscribe("impact_vehicle_wall", self._on_wall_collision)
        self.event_bus.subscribe("race_finish", self._on_race_finish)
        self.event_bus.subscribe("race_start", self._on_race_start)
        # Auch offline: der Aufprall soll zu hoeren sein, nicht nur gemeldet.
        self.event_bus.subscribe("impact_vehicle_vehicle", self._on_vehicle_contact)

    def _build_racing_lines_optimized(self) -> None:
        """Compute per-vehicle physics-optimised trajectory with a loading screen."""
        from src.ai.racing_line_solver import compute_racing_line_optimized, SolvedRacingLine
        from src.ai.speed_profile import limits_from_config, compute_speed_profile
        from src.core import race_setup

        setup = race_setup.current()
        if setup.mode == "Zeitfahren":
            import os
            from src.core import ghost
            tk = ghost.track_key(self._track_path)

            if not ghost.exists(tk):
                from src.core import display
                screen = display.virtual_surface()
                self._open_loading_video()

                def _ghost_progress(pct):
                    self._render_loading(screen, tr("Generiere Ghost-Seed..."), pct, 100, 0, 1)

                seed_data = ghost.generate_seed_ghost(
                    self._track_path, progress_callback=_ghost_progress)
                ghost.save(tk, seed_data)

                # The ghost was loaded as None in enter() (no file existed yet).
                # Attach the freshly generated seed so it also races THIS first run
                # instead of only appearing on the replay.
                if self.ghost_player is None and seed_data is not None:
                    self.ghost_player = ghost.GhostPlayer(seed_data)
                    self._original_ghost_sectors = list(seed_data.sectors)
                    self._original_ghost_lap_time = seed_data.lap_time
                    self._original_ghost_driver = seed_data.driver

                self._render_loading(screen, tr("Fertig!"), 99, 100, 0, 1)
                self._close_loading_video()

        if not self.track or not self.ai_vehicles:
            self._line_geo = None
            # Gaeste haben kein KI-Roster und damit nichts zu rechnen. Sie warten
            # aber trotzdem auf die anderen - dafuer brauchen sie denselben
            # Hintergrund wie der Host, sonst startet ihr Bildschirm optisch
            # schon im Rennen.
            if self._online:
                self._open_loading_video()
            return

        center = self.track.centerline
        if not center or len(center) < 3:
            center = [(wp.x, wp.y) for wp in self.track.waypoints]

        from src.core import display
        screen = display.virtual_surface()
        total = len(self.ai_vehicles)
        self._open_loading_video()

        for car_idx, ai in enumerate(self.ai_vehicles):
            diff = ai.controller.difficulty
            margin = getattr(diff, "wall_margin", 24.0)
            adjusted_margin = margin + max(0.0, (ai.config.height_px - 48.0) * 0.5)

            car_name = getattr(ai.config, "name", f"Car {car_idx + 1}")

            def _progress(it, max_it, _cn=car_name, _ci=car_idx):
                self._render_loading(screen, _cn, _ci, total, it, max_it)

            geo = compute_racing_line_optimized(
                center, self.track.track_width,
                vehicle_config=ai.config,
                difficulty=diff,
                car_width=ai.config.width_px,
                margin=adjusted_margin,
                progress_callback=_progress,
            )

            if car_idx == 0:
                self._line_geo = geo

            grip_usage = getattr(diff, "grip_usage", None)
            brake_confidence = getattr(diff, "brake_confidence", None)
            steer_confidence = getattr(diff, "steer_confidence", None)

            lim = limits_from_config(ai.config, grip_usage=grip_usage,
                                     brake_confidence=brake_confidence,
                                     steer_confidence=steer_confidence)
            profile = compute_speed_profile(geo, lim)
            ai.controller.racing_line = SolvedRacingLine(
                geo.offsets, profile, geo.signed_curvature, geo.points
            )

        self._render_loading(screen, tr("Fertig!"), total - 1, total, 1, 1)
        self._close_loading_video()

    def _open_loading_video(self) -> None:
        """Open the submenu's video for the loading screen (best-effort)."""
        import os
        from src.core import race_setup
        stem = "Mehrspieler_Lokal" if race_setup.current().is_multiplayer else "Einzelspieler"
        path = os.path.join("data", "menu", f"{stem}.mp4")
        self._load_video = None
        if os.path.isfile(path):
            from src.ui.video_player import VideoPlayer
            vp = VideoPlayer(path, (SCREEN_WIDTH, SCREEN_HEIGHT))
            self._load_video = vp if vp.ok else None

    def _close_loading_video(self) -> None:
        vid = getattr(self, "_load_video", None)
        if vid is not None:
            vid.close()
        self._load_video = None

    def _build_racing_line_for(self, config, difficulty):
        """Build a SolvedRacingLine for one vehicle config (used for player takeover)."""
        from src.ai.racing_line_solver import compute_racing_line_optimized, SolvedRacingLine
        from src.ai.speed_profile import limits_from_config, compute_speed_profile
        center = self.track.centerline
        if not center or len(center) < 3:
            center = [(wp.x, wp.y) for wp in self.track.waypoints]
        margin = getattr(difficulty, "wall_margin", 24.0) + max(0.0, (config.height_px - 48.0) * 0.5)
        geo = compute_racing_line_optimized(
            center, self.track.track_width,
            vehicle_config=config, difficulty=difficulty,
            car_width=config.width_px, margin=margin,
        )
        lim = limits_from_config(
            config,
            grip_usage=getattr(difficulty, "grip_usage", None),
            brake_confidence=getattr(difficulty, "brake_confidence", None),
            steer_confidence=getattr(difficulty, "steer_confidence", None),
        )
        profile = compute_speed_profile(geo, lim)
        return SolvedRacingLine(geo.offsets, profile, geo.signed_curvature, geo.points)

    def _apply_finish_effects(self) -> None:
        """After each vehicle finishes: hand the player to the AI and slow all
        finished cars to a 0.5 speed cool-down lap."""
        if not self.race_manager:
            return
        finished = self.race_manager.finished_ids

        # Slow every newly-finished vehicle to 0.5 speed.
        all_vehicles = [*self.ai_vehicles, *self._humans]
        for v in all_vehicles:
            if v.id in finished and v.id not in self._finish_applied:
                ctrl = getattr(v, "controller", None)
                if v in self._humans:
                    self._start_player_ai_takeover(v)
                    ctrl = getattr(v, "controller", None)
                if ctrl is not None:
                    ctrl.speed_multiplier = 0.5
                self._finish_applied.add(v.id)

    def _start_player_ai_takeover(self, vehicle) -> None:
        """Attach an AIController to a finished human's car so the AI drives its cool-down lap."""
        if vehicle is None or vehicle.id in self._player_ai_ids:
            return
        from src.ai.ai_controller import AIController
        from src.ai.difficulty import get_difficulty
        diff = get_difficulty("hard")
        ctrl = AIController(vehicle, self.track, diff)
        _ck = getattr(vehicle.config, "name", id(vehicle.config))
        line = getattr(self, "_takeover_lines", {}).get(_ck)
        if line is None:
            # Fallback: not precomputed (shouldn't happen) — solve now.
            line = self._build_racing_line_for(vehicle.config, diff)
        ctrl.racing_line = line
        # Dieselbe Liste wie alle anderen Regler — ein uebernommenes Spielerauto
        # faehrt sonst blind durch ein Feld, das es beim Start gab.
        if self._ai_feld is None:
            self._ai_feld = []
            self._ai_feld_auffrischen()
        ctrl.opponents = self._ai_feld
        vehicle.controller = ctrl
        self._player_ai_ids.add(vehicle.id)

    def _ai_feld_auffrischen(self) -> None:
        """Das Feld fortschreiben, das jede KI sieht.

        **In derselben Liste**, nicht als neue: die Regler halten sie, und wer
        sie ersetzt, schneidet sie von der Aenderung ab.

        Drin stehen Menschen, die eigene KI und die Abbilder der Mitspieler.
        Letztere sind neu (gemeldet 04.08.2026: „KI reagiert nicht auf die
        anderen Userfahrzeuge, dabei sind ja Positions- und
        Geschwindigkeitsdaten vorhanden"). Ein Abbild ohne erste Nachricht bleibt
        draussen — es stuende auf (0, 0), und die KI wuerde einem Gespenst in der
        Streckenmitte ausweichen.
        """
        if self._ai_feld is None:
            return
        self._ai_feld[:] = [
            *self._humans, *self.ai_vehicles,
            *[rv for rv in self._remote_vehicles if getattr(rv, "bereit", False)],
        ]

    def _render_loading(self, screen: pygame.Surface, car_name: str,
                        car_idx: int, total_cars: int,
                        iteration: int, max_iterations: int) -> None:
        """Draw the pre-race loading screen: submenu video + progress bar."""
        from src.core import display

        # Der Ladebildschirm laeuft ausserhalb der Bildschleife des Spiels und
        # zeigt sich selbst. Er muss das Bild deshalb selbst anfangen und
        # abschliessen, sonst steht am Ende nichts auf dem Schirm.
        display.bild_beginnen()
        cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2

        # Background: the same looping video as the submenu we came from.
        vid = getattr(self, "_load_video", None)
        frame = vid.get_surface() if (vid is not None and vid.ok) else None
        if frame is not None:
            vid.update(1.0 / 60.0)
            screen.blit(frame, (0, 0))
            dark = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            dark.fill((0, 0, 0, 150))
            screen.blit(dark, (0, 0))
        else:
            theme.draw_background(screen)
            screen.blit(theme.vignette((SCREEN_WIDTH, SCREEN_HEIGHT), 120), (0, 0))

        overall = (car_idx * max_iterations + iteration) / max(1, total_cars * max_iterations)
        pct = int(overall * 100)

        theme.text(screen, tr("Lädt …  {p} %").format(p=pct), theme.TITLE, theme.ACCENT, (cx, cy - 80), center=True)

        bar_w, bar_h = 620, 30
        bx, by = cx - bar_w // 2, cy + 10
        pygame.draw.rect(screen, (40, 44, 56), (bx, by, bar_w, bar_h), border_radius=8)
        fill_w = int(bar_w * overall)
        if fill_w > 0:
            pygame.draw.rect(screen, theme.ACCENT, (bx, by, fill_w, bar_h), border_radius=8)
        pygame.draw.rect(screen, theme.BORDER, (bx, by, bar_w, bar_h), 2, border_radius=8)

        theme.text(screen, tr("Rennen wird vorbereitet"), theme.HINT, theme.TEXT_DIM,
                   (cx, by + 56), center=True)

        display.bild_abschliessen()
        pygame.event.pump()

    @staticmethod
    def _gitter_bauen(kwargs: dict, start_positions: list, setup) -> list[int]:
        """Gitterplaetze fuer das ganze Feld: Menschen zuerst, dann die KI.

        Reihenfolge der Liste ist die Reihenfolge, in der die Fahrzeuge gebaut
        werden — Spieler 1, (Spieler 2), dann die KI. Damit kann jede Stelle
        ihren Platz einfach nachschlagen, statt ihn selbst auszurechnen.
        """
        if not start_positions:
            return []
        plaetze_gesamt = len(start_positions)
        online = getattr(setup, "_online", False)
        split = setup.is_multiplayer and not online

        # Wieviele Menschen belegen vorne Plaetze? Online sind das alle in der
        # Lobby, auch die, die dieser Rechner nicht simuliert — sonst setzt der
        # Host seine KI auf einen Platz, auf dem gleich ein Gast steht.
        menschen = kwargs.get("online_human_count", 1) if online else (2 if split else 1)
        menschen = max(1, min(int(menschen or 1), plaetze_gesamt))

        wuensche: list = [kwargs.get("grid_slot")]
        if split:
            wuensche.append(kwargs.get("grid_slot2"))
        else:
            # Online: die Plaetze der uebrigen Menschen. Die Lobby schickt sie
            # mit ("human_grid_slots"), damit der Host seine KI nicht auf einen
            # Platz setzt, auf dem gleich ein Gast steht. Fehlt die Liste
            # (aelterer Weg), bleiben Platzhalter — die belegen wenigstens
            # irgendwelche Plaetze, statt sie der KI zu ueberlassen.
            andere = [s for s in (kwargs.get("human_grid_slots") or [])
                      if s != kwargs.get("grid_slot")]
            wuensche.extend(andere[:menschen - 1])
            wuensche.extend([None] * max(0, (menschen - 1) - len(andere)))

        ai_vorgabe = kwargs.get("ai_grid_slots") or []
        frei = max(0, plaetze_gesamt - len(wuensche))
        ai_anzahl = min(setup.ai_count(), frei)
        wuensche.extend(ai_vorgabe[i] if i < len(ai_vorgabe) else None
                        for i in range(ai_anzahl))

        return RaceState.gitterplaetze(wuensche, plaetze_gesamt)

    @staticmethod
    def gitterplaetze(wuensche: list, anzahl_plaetze: int) -> list[int]:
        """Je Fahrzeug ein Gitterplatz — **garantiert ohne Doppelbelegung**.

        *wuensche* ist die Wunschliste in Startreihenfolge der Fahrzeuge
        (Spieler 1, Spieler 2, dann die KI). ``None`` heisst "naechster freier";
        eine Zahl ist ein Wunsch aus der Grand-Prix-Wertung.

        Warum zentral: die Plaetze wurden an drei Stellen einzeln vergeben —
        Spieler 1 aus ``grid_slot``, Spieler 2 **fest auf 1**, die KI in einer
        eigenen Funktion, die nur ihre eigenen Vorgaben kannte. Im lokalen
        Mehrspieler-Grand-Prix stand Spieler 1 nach dem ersten Lauf auf Platz 1
        der Wertung und bekam damit denselben Gitterplatz wie Spieler 2 — beide
        Autos spawnten ineinander. Dieselbe Luecke traf eine KI ohne Wertung,
        die auf dem Platz eines Menschen landen konnte.

        Ein doppelt belegter Platz ist kein Schoenheitsfehler: pymunk drueckt
        zwei ineinander stehende Koerper mit voller Wucht auseinander.
        """
        n = max(1, int(anzahl_plaetze))
        plaetze: list[int | None] = [None] * len(wuensche)
        belegt: set[int] = set()

        # Durchgang 1: brauchbare Wuensche einloesen, der erste gewinnt.
        for i, w in enumerate(wuensche):
            if isinstance(w, int) and not isinstance(w, bool) \
                    and 0 <= w < n and w not in belegt:
                plaetze[i] = w
                belegt.add(w)

        # Durchgang 2: den Rest mit den niedrigsten freien Plaetzen auffuellen.
        frei = [p for p in range(n) if p not in belegt]
        naechster = 0
        for i, p in enumerate(plaetze):
            if p is not None:
                continue
            if naechster < len(frei):
                plaetze[i] = frei[naechster]
                naechster += 1
            else:
                # Mehr Fahrzeuge als Plaetze. Kommt nicht vor (die KI-Zahl ist
                # auf die freien Plaetze gedeckelt), aber lieber ein doppelter
                # Platz als ein Absturz beim Rennstart.
                plaetze[i] = i % n
        return [int(p) for p in plaetze]

    def _spawn_ai_vehicles(self, start_positions, kwargs: dict, human_count: int = 1) -> list:
        """Create AI opponents on grid slots after the human player(s)."""
        from src.entities.vehicle_factory import VehicleFactory
        from src.ai.difficulty import get_difficulty
        from src.core import race_setup

        setup = race_setup.current()
        difficulty = get_difficulty(kwargs.get("difficulty") or setup.ai_difficulty)
        from src.core import lack

        # AI opponents fill the field up to the requested size, but never more
        # than the free grid slots. The lobby class restricts which cars the AI
        # may pick.
        free_slots = max(0, len(start_positions) - human_count)
        count = min(setup.ai_count(), free_slots)
        ai_keys = setup.class_keys() or AI_VEHICLE_KEYS

        # Die Plaetze stehen im gemeinsamen Gitter: hinter den Menschen, in der
        # Reihenfolge, in der die KI-Autos gebaut werden.
        plaetze = list(self._gitter[human_count:human_count + count])
        while len(plaetze) < count:            # Rueckfall, falls das Gitter kuerzer ist
            plaetze.append((human_count + len(plaetze)) % max(1, len(start_positions)))

        ai_vehicles: list = []
        for i in range(count):
            slot = start_positions[plaetze[i] % len(start_positions)]
            if i < len(setup.ai_roster):
                driver = setup.ai_roster[i]
                cfg_key = driver.vehicle
                if cfg_key == "random":
                    import random
                    cfg_key = random.choice(ai_keys)
                difficulty = get_difficulty(driver.difficulty)
            else:
                cfg_key = ai_keys[i % len(ai_keys)]
                difficulty = get_difficulty(setup.ai_difficulty)
            vid = i + 1 + human_count
            ai = VehicleFactory.create_ai_vehicle(
                config_key=cfg_key,
                vehicle_id=vid,  # after the human player(s)
                start_pos=slot.pos,
                start_angle=math.radians(slot.angle),
                space=self.physics_world.space,
                track=self.track,
                difficulty=difficulty,
                # Aus der Fahrzeugnummer, nicht aus der Schleifenzaehlung: online
                # baut nur der Gastgeber diese Autos, alle anderen sehen ein
                # Abbild — und beide Seiten kennen nur die Nummer.
                lack=lack.ki_lack(vid),
            )
            if ai:
                ai.config_key = cfg_key   # remembered so online play can broadcast it
                ai_vehicles.append(ai)
        return ai_vehicles

    def _on_race_start(self, data: Any = None) -> None:
        """Activate AI driving when the countdown ends."""
        for ai in self.ai_vehicles:
            ai.ai_active = True

    def _on_checkpoint_crossed_ghost(self, data: dict[str, Any]) -> None:
        vid = data.get("vehicle_id")
        if self.ghost_recorders and vid in self.ghost_recorders:
            if self.race_manager and vid in self.race_manager.lap_trackers:
                tracker = self.race_manager.lap_trackers[vid]
                # Mirror the LapTracker's own validation: only count the expected
                # checkpoint crossed while moving forward, else double triggers /
                # reverse crossings would record bogus sector times.
                if data.get("checkpoint_idx") != tracker.next_checkpoint_idx:
                    return
                if not tracker._is_moving_forward():
                    return
                self.ghost_recorders[vid].record_sector(tracker.current_lap_time)

    #: Bezugstempo, unter das der Abstand nicht gerechnet wird (px/s).
    #: Wer steht, hat rechnerisch unendlich Rueckstand — angezeigt wird dann der
    #: Wert, den ein langsam rollendes Auto braeuchte, statt einer Fantasiezahl.
    ABSTAND_MINDESTTEMPO = 120.0

    def _streckenlaenge_px(self) -> float:
        """Laenge einer Runde in Weltpixeln, aus den Wegpunkten summiert."""
        wp = self.track.waypoints if self.track else []
        if len(wp) < 2:
            return 0.0
        laenge = 0.0
        for a, b in zip(wp, wp[1:] + wp[:1]):
            laenge += math.hypot(b.x - a.x, b.y - a.y)
        return laenge

    def _fortschritt(self, vid: int) -> float:
        """Streckenfortschritt in Wegpunkten, ueber Runden hinweg fortlaufend."""
        wp = len(self.track.waypoints) if self.track else 0
        t = self.race_manager.lap_trackers[vid]
        return t.current_lap * max(1, wp) + t.waypoint_progress

    def _abstand_sekunden(self, vid: int, fuehrender_vid: int) -> float | None:
        """Geschaetzter Rueckstand in Sekunden, aus der Streckenposition.

        Gerechnet wurde hier die verstrichene **Gesamtzeit** gegen die des
        Fuehrenden. Die ist aber fuer alle gleich, solange niemand im Ziel ist:
        alle starten gemeinsam, und `sum(lap_times) + current_lap_time` ist
        schlicht die Rennzeit. Ergebnis war +0.00s in jeder Zeile, bei jedem
        Fahrzeug, das ganze Rennen lang (gemeldet 05.08.2026). Die Streckenposition
        kam in der Rechnung gar nicht vor.

        Jetzt: wie weit liegt das Fahrzeug **auf der Strecke** zurueck, und wie
        lange braeuchte es fuer diese Strecke bei seinem jetzigen Tempo. Das ist
        eine Schaetzung und keine Messung — genau wie in echten Rennserien, wo
        der Abstand auch erst an der naechsten Messstelle stimmt.

        ``None`` heisst: nicht bestimmbar (keine Strecke, keine Wegpunkte).
        """
        if not self.race_manager or not self.track or not self.track.waypoints:
            return None
        laenge = self._streckenlaenge_px()
        if laenge <= 0.0:
            return None
        je_wegpunkt = laenge / len(self.track.waypoints)
        rueckstand_px = (self._fortschritt(fuehrender_vid)
                         - self._fortschritt(vid)) * je_wegpunkt
        if rueckstand_px <= 0.0:
            return 0.0
        eigenes = abs(float(getattr(self._fahrzeug_zu_id(vid), "speed", 0.0) or 0.0))
        return rueckstand_px / max(eigenes, self.ABSTAND_MINDESTTEMPO)

    def _fahrzeug_zu_id(self, vid: int):
        for v in (self.race_manager.vehicles if self.race_manager else []):
            if v.id == vid:
                return v
        return None

    def _mitschnitt_umschalten(self) -> None:
        """F9: Mitschnitt an oder aus, mit Rueckmeldung im Bild.

        Ohne sichtbare Rueckmeldung waere nicht zu erkennen, ob er laeuft — und
        eine Aufnahme, von der man nicht weiss, ob sie mitschreibt, ist keine.
        """
        from src.core import klangmitschnitt
        if klangmitschnitt.laeuft():
            pfad = klangmitschnitt.beenden()
            self._mitschnitt_hinweis = (
                tr("Mitschnitt gespeichert: {p}").format(p=pfad or "?"), 8.0)
        else:
            klangmitschnitt.starten()
            self._mitschnitt_hinweis = (tr("Mitschnitt läuft — F9 beendet ihn."), 4.0)

    def _update_rubber_banding(self) -> None:
        """Give trailing AI (with rubber-banding enabled) a small throttle boost.

        Progress is measured as ``current_lap * num_waypoints + waypoint_index``
        so the gap to the leader spans laps cleanly.
        """
        if not self.race_manager or not self.track:
            return
        num_wp = max(1, len(self.track.waypoints))
        trackers = self.race_manager.lap_trackers

        def progress(vid: int) -> float:
            t = trackers[vid]
            return t.current_lap * num_wp + t.waypoint_progress

        leader = max(progress(v.id) for v in self.race_manager.vehicles)
        for ai in self.ai_vehicles:
            gap = leader - progress(ai.id)
            # Up to +0.3 throttle, reaching full boost at half a lap behind.
            ai.controller.rubber_band = min(0.3, gap / (num_wp * 0.5)) if gap > 0 else 0.0

    # ── Klang (Block C, §C6) ────────────────────────────────────────────────

    def _klang_aufbauen(self) -> None:
        """Eine Motorstimme je Fahrzeug anlegen.

        Das Fahrzeug kennt seinen Konfigurationsschluessel nicht, wohl aber der
        Ort, an dem es gebaut wurde - deshalb wird die Zuordnung hier gebildet.
        Am Schluessel haengt beides: welcher Motor und wie dieses eine Fahrzeug
        davon abweicht.
        """
        from src.core import race_setup, sfx_rennen
        if self._klang is not None:
            # Ein Grand Prix betritt denselben Zustand mehrfach; ohne das
            # bliebe der alte Satz Kanäle belegt und liefe mit.
            self._klang.beenden()
        self._klang = None
        try:
            setup = race_setup.current()
            schluessel: dict[tuple, str] = {}
            for mensch, key in zip(self._humans,
                                   (setup.player_vehicle, setup.player2_vehicle)):
                schluessel[sfx_rennen.kennung(mensch)] = key
            for ai in self.ai_vehicles:
                # config_key statt ai_roster: der Eintrag dort kann "random"
                # sein, das Fahrzeug kennt den tatsächlich gezogenen Wagen.
                schluessel[sfx_rennen.kennung(ai)] = getattr(ai, "config_key", "")

            klang = sfx_rennen.Rennklang()
            klang.starten(self._klang_fahrzeuge(), schluessel)
            self._klang = klang
        except Exception as exc:
            # Klang ist Beiwerk: ein Fehler darf das Rennen nicht verhindern.
            print(f"[RaceState] Motorklang nicht verfuegbar: {exc}")

    def _startsignal_pruefen(self) -> None:
        """Das Startsignal anstoßen, wenn noch genau seine Länge übrig ist.

        ``race-start.wav`` ist der **ganze** Countdown: Piep bei 0,0, 1,0 und
        2,0 Sekunden, der lange Ton bei 3,0. Am Ende des Countdowns abgespielt
        kam er also vier Sekunden zu spät. Der Auslöser hängt deshalb an der
        Restzeit und nicht am Anfang: online läuft der Countdown 3,5 Sekunden,
        lokal 3,0, und der lange Ton soll in beiden Fällen genau auf GO liegen.
        """
        if self._startsignal_gespielt or self._klang is None:
            return
        rm = self.race_manager
        if rm is None or rm.state != "countdown":
            return
        from src.core import sfx_rennen
        if rm.countdown_timer <= sfx_rennen.STARTSIGNAL_VORLAUF:
            self._klang.startsignal()
            self._startsignal_gespielt = True

    def _klang_fahrzeuge(self) -> list:
        """Alles, was klingen soll — eigene Autos, KI und ferne Mitspieler."""
        aus = list(self._humans) + list(self.ai_vehicles)
        aus += [rv for rv in self._remote_vehicles if getattr(rv, "body", None)]
        return aus

    def _hoerpositionen(self) -> list[tuple[float, float]]:
        """Das eigene Fahrzeug ist der Hoerer. Im Splitscreen sind es zwei.

        Vorher war es der Kameramittelpunkt, und das war doppelt falsch. Die
        Kamera rechnet in Pygame-Koordinaten mit gespiegelter y-Achse, die
        Fahrzeuge in Pymunk-Koordinaten - die y-Entfernung war damit Unsinn, und
        weit entfernte Fahrzeuge klangen nah. Gehoert wird ohnehin dort, wo man
        sitzt, nicht dort, wo die Kamera gerade hinschaut.
        """
        from src.core import sfx_rennen
        return [sfx_rennen._position(hp) for hp in self._humans if hp is not None]

    def _fahrzeug_mit_id(self, vehicle_id) -> object | None:
        if vehicle_id is None:
            return None
        for fahrzeug in self._klang_fahrzeuge():
            if getattr(fahrzeug, "id", None) == vehicle_id:
                return fahrzeug
        return None

    def _klang_aktualisieren(self) -> None:
        if self._klang is None:
            return
        try:
            hoerer = self._hoerpositionen()
            self._klang.aktualisieren(self._klang_fahrzeuge(), hoerer)
            # Reifen nur fuers eigene Auto: sechs driftende Autos als
            # Einzelklaenge wuerden zum Maschinengewehr.
            if self.player is not None:
                self._klang.reifen(self.player, hoerer)
        except Exception as exc:
            print(f"[RaceState] Motorklang abgeschaltet: {exc}")
            self._klang = None

    def _dnf_restzeit(self, vehicle_id: int) -> float | None:
        """Restsekunden bis zum DNF — nur fuer ein Auto, das noch faehrt.

        Wer schon durchs Ziel ist, bekommt stattdessen den Warte-Hinweis; ihm
        eine ablaufende Frist zu zeigen, waere schlicht falsch.
        """
        rm = self.race_manager
        if rm is None or vehicle_id in rm.finished_ids:
            return None
        return rm.sekunden_bis_dnf()

    def _online_position(self, vehicle_id: int) -> int:
        """Race position across the whole online field: local vehicles via their
        lap trackers plus every remote car via its last reported progress."""
        if not self.race_manager or not self.track:
            return 1
        num_wp = max(1, len(self.track.waypoints))
        t = self.race_manager.lap_trackers.get(vehicle_id)
        if t is None:
            return 1
        my_prog = t.current_lap * num_wp + t.waypoint_progress
        ahead = 0
        for vid, tr_ in self.race_manager.lap_trackers.items():
            if vid != vehicle_id and (tr_.current_lap * num_wp + tr_.waypoint_progress) > my_prog:
                ahead += 1
        for rv in self._remote_vehicles:
            if rv.progress(num_wp) > my_prog:
                ahead += 1
        return ahead + 1

    def _team_standings_info(self, own_id: int) -> list[dict]:
        """Position list for the Team-Zeitfahren HUD.

        Offline this is exactly `race_manager._standings` (finish order kept
        for finished vehicles, then lap/progress for the rest) — unchanged
        from before. Online, remote ghosts (other humans + their AI, which
        never appear in `_standings`) are merged in and the whole field is
        ranked by race progress, key `(lap, waypoint)` descending, using each
        remote's own snapshot fields since there is no shared finish order
        across the network.
        """
        if not self._online:
            rows = []
            for idx, v in enumerate(self.race_manager._standings):
                ai_takeover = bool(getattr(v, "is_takeover", False))
                name = self._driver_names.get(v.id, "AI")
                if ai_takeover:
                    name += tr(" (KI)")
                rows.append({
                    "position": idx + 1,
                    "name": name,
                    "team": getattr(v, "team", "A"),
                    "is_player": (v.id == own_id),
                    "ai_takeover": ai_takeover,
                })
            return rows

        entries = []
        for v in self.race_manager._standings:
            tracker = self.race_manager.lap_trackers.get(v.id)
            lap = getattr(tracker, "current_lap", 0)
            wp = getattr(tracker, "waypoint_progress", 0)
            entries.append((lap, wp, self._driver_names.get(v.id, "AI"),
                             getattr(v, "team", "A"), v.id == own_id,
                             bool(getattr(v, "is_takeover", False))))
        for rv in self._remote_vehicles:
            entries.append((
                getattr(rv, "lap", 0), getattr(rv, "wp", 0),
                getattr(rv, "driver_name", "?"), getattr(rv, "team", "A"), False,
                bool(getattr(rv, "is_takeover", False)),
            ))
        entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
        rows = []
        for idx, (_lap, _wp, name, team, is_p, ai_takeover) in enumerate(entries):
            if ai_takeover:
                name += tr(" (KI)")
            rows.append({
                "position": idx + 1, "name": name, "team": team,
                "is_player": is_p, "ai_takeover": ai_takeover,
            })
        return rows

    def _on_vehicle_contact(self, data: dict[str, Any]) -> None:
        """Car-to-car touch: sound always, denser streaming and bump relay online."""
        if self._klang is not None:
            self._klang.aufprall(data.get("impulse", 0.0),
                                 self._fahrzeug_mit_id(data.get("vehicle_id")),
                                 self._hoerpositionen())
        if not self._online:
            return

        self._contact_boost = CONTACT_BOOST_SECONDS

        from src.net import session
        nc = session.get()
        if not nc or not nc.connected:
            return

        impulse = data.get("impulse", 0.0)
        if impulse < 50.0:
            return
        tot_imp = data.get("total_impulse")
        if not tot_imp:
            return
        va = data.get("vehicle_a")
        vb = data.get("vehicle_b")
        local_p = self.player
        target_rv = None
        if va is local_p and getattr(vb, "is_remote", False):
            target_rv = vb
        elif vb is local_p and getattr(va, "is_remote", False):
            target_rv = va

        if target_rv and hasattr(target_rv, "sender_slot"):
            nc.send_bump(target_rv.sender_slot, tot_imp.x, tot_imp.y)


    def _on_wall_collision(self, data: dict[str, Any]) -> None:
        """Handle vehicle hitting a wall."""
        impulse = data.get("impulse", 0.0)
        if self._klang is not None:
            fahrzeug = self._fahrzeug_mit_id(data.get("vehicle_id"))
            self._klang.wandtreffer(impulse, fahrzeug, self._hoerpositionen())

    def _on_race_finish(self, data: dict[str, Any]) -> None:
        """Handle race finished event."""
        print(f"[RaceState] Race completed! Standings: {data.get('standings')}")

        from src.core import race_setup
        setup = race_setup.current()
        if setup.mode == "Zeitfahren" and self.ghost_recorders:
            from src.core import ghost
            from src.core import profile

            # Find the best time among human players (1 and 2)
            best_time = float("inf")
            best_vid = None

            # results are in self.race_manager.results
            if self.race_manager:
                for r in self.race_manager.results:
                    vid = r["vehicle_id"]
                    if vid in (1, 2) and not r.get("dnf", False):
                        t = r["finish_time"]
                        if t and t < best_time:
                            best_time = t
                            best_vid = vid

            if best_vid is not None:
                old_time = 9999.0
                if self.ghost_player and self.ghost_player.data:
                    old_time = self.ghost_player.data.lap_time

                if best_time < old_time:
                    # New record!
                    recorder = self.ghost_recorders[best_vid]
                    driver_name = setup.player2_name if best_vid == 2 else (profile.current().username or "Spieler 1")
                    veh_key = setup.player2_vehicle if best_vid == 2 else setup.player_vehicle

                    new_ghost = ghost.GhostData(
                        lap_time=best_time,
                        samples=list(recorder.samples),
                        sectors=list(recorder.sectors),
                        driver=driver_name,
                        vehicle=veh_key,
                    )
                    ghost.save(self._ghost_track_key, new_ghost)
                    self._new_ghost_saved = True
                else:
                    self._new_ghost_saved = False

    def exit(self) -> None:
        """Clean up physics world and event subscriptions."""
        if self._klang is not None:
            self._klang.beenden()
            self._klang = None
        if self._online and self.physics_world:

            for rv in self._remote_vehicles:
                rv.cleanup(self.physics_world.space)
            self._remote_vehicles = []
            self._remote_map = {}
            # Keep the network session + lobby page alive so the player can
            # return to the SAME lobby from results. It is cleared only when
            # they actually leave the lobby (ESC) or pick "Hauptmenü".

        from src.core import gamepad
        gamepad.set_menu_translation(True)   # controllers return to menu control
        self.event_bus.unsubscribe("impact_vehicle_wall", self._on_wall_collision)
        self.event_bus.unsubscribe("race_finish", self._on_race_finish)
        self.event_bus.unsubscribe("race_start", self._on_race_start)
        # Ohne Bedingung, genau wie die Anmeldung in enter(). Die stand einmal
        # unter `if self._online` und wurde am 04.08.2026 auf "auch offline"
        # gezogen, damit der Aufprall zu hoeren ist — die Abmeldung hier ist
        # dabei stehengeblieben. Folge: jedes Offline-Rennen liess seinen
        # Rueckruf fuer immer am prozessweiten Bus haengen. Das Rennen konnte
        # nicht freigegeben werden, und beim naechsten Auto-an-Auto-Kontakt
        # liefen auch alle Rueckrufe der abgeraeumten Rennen davor mit — auf
        # einem Klang, den es nicht mehr gibt. Gefunden am 07.08.2026 von
        # tests/test_rennsimulation.py.
        self.event_bus.unsubscribe("impact_vehicle_vehicle", self._on_vehicle_contact)

        if self.ghost_recorders:
            self.event_bus.unsubscribe("checkpoint_crossed", self._on_checkpoint_crossed_ghost)

        if self.checkpoints:
            for cp in self.checkpoints:
                cp.cleanup()
            self.checkpoints = []

        if self.race_manager:
            self.race_manager.cleanup()
            self.race_manager = None
        
        for ai in self.ai_vehicles:
            ai.cleanup(self.physics_world.space)
        self.ai_vehicles = []

        if self.player:
            self.player.cleanup(self.physics_world.space)
        if getattr(self, "player2", None):
            self.player2.cleanup(self.physics_world.space)
            self.player2 = None
        if self.physics_world:
            self.physics_world.cleanup()

        self.physics_world = None
        self.collision_handler = None
        self.track = None
        if self.szene is not None:
            self.szene.freigeben()
            self.szene = None
        self.player = None
        self.camera = None
        self._kameras = []
        self._staende = []
        self.hud = None

    def _starte_ausblenden(self, online_rows) -> None:
        """Kurze Nachlaufzeit mit Ausblenden vor dem Ergebnisschirm.

        Fund 08.08.2026: der Ergebnisschirm kam uebergangslos, sobald der Letzte
        ueber die Linie fuhr oder DNF war. Statt des harten Schnitts laeuft die
        Welt noch RESULTS_OUTRO_SECONDS weiter, waehrend sich ein schwarzer
        Schleier darueberlegt (siehe _render_outro); erst danach _go_to_results.

        Idempotent: ein zweiter Aufruf verlaengert das Ausblenden nicht.
        """
        if self._outro_active:
            return
        self._outro_active = True
        self._outro_timer = RESULTS_OUTRO_SECONDS
        self._outro_rows = online_rows

    def _outro_alpha(self) -> int:
        """Deckung des Schleiers: 0 zu Beginn, voll schwarz am Ende — dann geht
        der Schnitt in die Ergebnisse nahtlos auf."""
        if not self._outro_active or RESULTS_OUTRO_SECONDS <= 0.0:
            return 0
        fortschritt = 1.0 - max(0.0, self._outro_timer) / RESULTS_OUTRO_SECONDS
        return max(0, min(255, int(255 * fortschritt)))

    def _go_to_results(self, online_rows=None) -> None:
        """Hand the finished race off to the results screen (once).

        online_rows: combined standings from the server (online races). When
        given they replace the locally computed rows."""
        if getattr(self, "_results_shown", False):
            return
        self._results_shown = True
        import os
        from src.core import profile

        from src.core import race_setup
        setup = race_setup.current()

        rows = []
        player_best = None
        for r in (self.race_manager.results if self.race_manager else []):
            vid = r["vehicle_id"]
            if vid == 1:
                player_best = r.get("best_lap")

            v_team = "A"
            if vid == 1:
                v_team = setup.p1_team
            elif vid == 2 and self._split:
                v_team = setup.p2_team
            else:
                ai = next((veh for veh in self.ai_vehicles if veh.id == vid), None)
                if ai:
                    v_team = getattr(ai, "team", "A")

            rows.append({
                "position": r["position"],
                "name": self._driver_names.get(vid, r.get("name", "")),
                "vehicle": self._vehicle_model.get(vid, ""),
                "finish_time": r.get("finish_time"),
                "best_lap": r.get("best_lap"),
                "dnf": r.get("dnf", False),
                "is_player": vid == 1,
                "is_player2": (vid == 2 and self._split),
                "sectors": list(self.ghost_recorders[vid].sectors) if (self.ghost_recorders and vid in self.ghost_recorders) else [],
                "team": v_team
            })

        # Online: the server's combined standings supersede the local-only rows
        # (the local peer never tracked the other players' laps).
        if online_rows is not None:
            rows = online_rows
            player_best = next((r.get("best_lap") for r in rows if r.get("is_player")), None)

        team_a_avg, team_b_avg = score_team_rows(rows)

        track_key = os.path.splitext(os.path.basename(self._track_path))[0]
        is_record = bool(player_best) and profile.current().record_lap(track_key, player_best)

        from src.core import grand_prix
        is_gp = grand_prix.is_active()
        if is_gp:
            gp = grand_prix.current()
            gp.add_race_results(rows)
            # Fuer die Markierung in der Streckenauswahl des naechsten Laufs.
            gp.note_track(track_key)
            # Serie gewonnen (E1a): ohne Netz endet sie genau hier, und genau
            # einmal. Online nicht: dort fuehrt der Gastgeber die Wertung, ein
            # Gast hat gar keine eigene Serie, und der Endstand ist in diesem
            # Augenblick noch nirgends. Gebucht wird das in
            # online_lobby_page._gp_sieg_pruefen, sobald der verteilte Zustand
            # die Serie als beendet meldet.
            if gp.is_finished and not self._online:
                from src.core import profile as _prof, statistik as _stat
                stand = gp.get_standings()
                eigener = (_prof.current().username or "").strip()
                if stand and str(stand[0].get("name", "")).strip() == eigener:
                    _stat.gp_gewonnen()

        meta = {
            "track_key": track_key,
            "is_record": is_record,
            "player_best": player_best,
            "is_zeitfahren": (setup.mode == "Zeitfahren"),
            "is_team_zeitfahren": (setup.mode == "Team-Zeitfahren"),
            "is_grand_prix": is_gp,
            "is_online": self._online,
            "team_a_avg": team_a_avg,
            "team_b_avg": team_b_avg,
            "new_ghost_saved": getattr(self, "_new_ghost_saved", False),
            "ghost_sectors": self._original_ghost_sectors,
            "ghost_lap_time": self._original_ghost_lap_time,
            "ghost_driver": self._original_ghost_driver
        }
        self._statistik_buchen(rows, meta, setup, track_key)
        self.state_machine.transition("menu", results=rows, race_config=meta)

    def _statistik_buchen(self, rows: list, meta: dict, setup, track_key: str) -> None:
        """Das gefahrene Rennen in der Profilstatistik verbuchen (E1).

        Entschieden wird hier **nichts** — welche Regeln gelten (Abbruch, DNF,
        Zeitfahren, Splitscreen), steht in ``statistik`` und nur dort. Diese
        Methode reicht die Zeile des eigenen Fahrzeugs samt Umstaenden weiter.
        Im Splitscreen ist das ausdruecklich nur Spieler 1: es gibt ein Profil
        je Rechner.
        """
        from src.core import statistik
        eigene = next((r for r in rows if r.get("is_player")), None)
        if eigene is None:
            return
        try:
            beste = min((float(r["best_lap"]) for r in rows
                         if r.get("best_lap")), default=None)
            eigene_beste = eigene.get("best_lap")
            beste_im_feld = bool(
                beste is not None and eigene_beste
                and abs(float(eigene_beste) - beste) < 1e-6)
            # Der eigene Gitterplatz steht in _gitter[0] — dieselbe Quelle, aus
            # der das Rennen die Startposition genommen hat.
            startplatz = self._gitter[0] if getattr(self, "_gitter", None) else None
            statistik.rennen_gewertet(
                eigene,
                modus=str(getattr(setup, "mode", "")),
                online=bool(meta.get("is_online")),
                beendet=True,
                strecke=track_key,
                eigene_strecke=(self._streckenherkunft() == "eigen"),
                teilnehmer=len(rows),
                startplatz=startplatz,
                beste_runde_im_feld=beste_im_feld)
            # Ghost geschlagen: die eigene beste Runde unterbietet die Zeit, mit
            # der man ins Rennen gegangen ist. 9999 heisst "es gab keinen".
            ghost_zeit = float(meta.get("ghost_lap_time") or 0.0)
            if (eigene_beste and 0.0 < ghost_zeit < 9000.0
                    and float(eigene_beste) < ghost_zeit):
                statistik.ghost_geschlagen(track_key)
            if self._streckenherkunft() == "fremd":
                statistik.fremde_strecke_gefahren()
        except Exception as exc:      # Statistik darf kein Rennen abbrechen
            print(f"[statistik] nicht verbucht: {exc}")

    def _streckenherkunft(self) -> str:
        """"mitgeliefert", "eigen" oder "fremd" — erkennbar am Ablageort.

        Selbst veroeffentlichte Strecken liegen unter ``data/tracks/custom``,
        online empfangene unter ``data/tracks/online`` (siehe
        online_lobby_page._save_received_map), die mitgelieferten daneben.
        """
        import os
        teile = os.path.normpath(str(getattr(self, "track_path", "") or "")).split(os.sep)
        if "custom" in teile:
            return "eigen"
        if "online" in teile:
            return "fremd"
        return "mitgeliefert"

    @property
    def raw_gamepad(self) -> bool:
        """Read the pad directly while racing; let the menu translate it while paused."""
        return not self.paused

    # ------------------------------------------------------------------
    # Pause sub-view: settings
    # ------------------------------------------------------------------
    def _pause_main_group(self):
        """Rebuild the top-level pause menu (online and offline variants)."""
        from src.ui.widgets import Button
        from src.ui.focus import FocusGroup
        cx = SCREEN_WIDTH // 2 - 150
        cy = SCREEN_HEIGHT // 2
        if self._online:
            ready = bool(getattr(self, "_local_resume_ready", False))
            btn_text = tr("Bereit") + f" {theme.HAKEN}" if ready else tr("Bereit zum Fortsetzen")
            btn_act = "none" if ready else "ready_resume"
            group = FocusGroup([
                Button(pygame.Rect(cx, cy + 30, 300, 50), btn_text, btn_act, enabled=not ready),
                Button(pygame.Rect(cx, cy + 90, 300, 50), tr("Einstellungen"), "settings"),
                Button(pygame.Rect(cx, cy + 150, 300, 50), tr("Beenden"), "quit"),
            ])
            group.index = 1
        else:
            group = FocusGroup([
                Button(pygame.Rect(cx, cy - 90, 300, 50), tr("Fortsetzen"), "resume"),
                Button(pygame.Rect(cx, cy - 30, 300, 50), tr("Rennstand"), "standings"),
                Button(pygame.Rect(cx, cy + 30, 300, 50), tr("Einstellungen"), "settings"),
                Button(pygame.Rect(cx, cy + 90, 300, 50), tr("Beenden"), "quit"),
            ])
            group.index = 2
        return group

    def _leave_pause_settings(self) -> None:
        """Climb one level: settings sub-view -> the pause menu above it."""
        self._pause_settings = None
        self._pause_view = "multiplayer_pause" if self._online else "main"
        self._pause_group = self._pause_main_group()

    def _open_pause_settings(self) -> None:
        from src.states.menu.settings_page import SettingsPage
        race = self

        class SettingsShellAdapter:
            """Minimal shell the settings page can talk to while racing.

            ``pop_page`` is what the page calls after the save/discard dialog,
            so B inside the settings has to land back on the pause menu — not
            fall through to the main menu.

            ``zurueck_gehen`` muss es genauso geben: der Zurueck-Knopf jeder
            Seite ruft es (``Page.zurueck_geklickt``), und dieser Adapter ist
            keine ``MenuShellState``. Gemeldet am 05.08.2026 als Absturz beim
            Klick auf Zurueck in den Pauseneinstellungen."""

            def __init__(self) -> None:
                self.state_machine = race.state_machine
                self.tab = 0
                self.page_stack = [self]

            def pop_page(self) -> None:
                race._leave_pause_settings()

            def zurueck_gehen(self) -> None:
                race._leave_pause_settings()

        page = SettingsPage()
        page.is_pause_context = True
        page.enter(SettingsShellAdapter())
        self._pause_view = "settings"
        self._pause_settings = page

    def _update_hold_abort_button(self) -> bool:
        """Abbruchknopf zeigen? Legt ihn beim ersten Mal an.

        Nur fuer den Host und erst nach einer kurzen Wartezeit. Bewusst kein
        automatischer Abbruch: die Gegenseite laedt womoeglich noch eine
        uebertragene Strecke und rechnet Ideallinien - ein Timer wuerde
        funktionierende Rennen zerreissen. Der Host sieht die Lage und
        entscheidet selbst.
        """
        import time as _t
        wartet = (_t.time() - self._hold_since) if self._hold_since else 0.0
        if not (self._is_online_host() and wartet >= HOLD_ABORT_BUTTON_AFTER_S):
            self._hold_abort_btn = None
            return False
        if self._hold_abort_btn is None:
            from src.ui.widgets import Button
            self._hold_abort_btn = Button(
                pygame.Rect(SCREEN_WIDTH // 2 - 190, SCREEN_HEIGHT // 2 + 110, 380, 62),
                tr("Rennen abbrechen"), "hold_abort", style="secondary")
        return True

    def _abort_held_race(self) -> None:
        """Host bricht ab, waehrend auf die Mitspieler gewartet wird.

        Zurueck in die Lobby statt ins Hauptmenue: die Gruppe steht dort noch
        beisammen und der Host kann direkt neu starten.
        """
        from src.core import gamepad
        from src.net import session as _sess
        nc = _sess.get()
        if nc is not None:
            nc.send_tcp({"type": "ABORT_RACE"})
        self._hold_since = 0.0
        self._hold_abort_btn = None
        gamepad.set_menu_translation(True)
        self.state_machine.transition("menu", reopen="online_lobby_resume",
                                      lobby_msg="Rennstart abgebrochen — nicht alle Mitspieler waren bereit.")

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        """Process keyboard and controller events (supporting pause toggle and menu navigation)."""
        from src.core import gamepad, grand_prix
        for event in events:
            # F9 schneidet den Rennklang mit (05.08.2026). Werkzeug auf Zeit,
            # um die ungeklaerten Stoergeraeusche einzukreisen — siehe
            # src/core/klangmitschnitt.py. Steht ganz vorn, damit es auch in der
            # Pause und waehrend des Wartens geht.
            if event.type == pygame.KEYDOWN and event.key == pygame.K_F9:
                self._mitschnitt_umschalten()
                continue
            # Abbruchknopf waehrend des Wartens auf die Mitspieler. Steht vor
            # allem anderen, damit ihn weder Pausenmenue noch Fahreingaben
            # verschlucken.
            if self._hold_abort_btn is not None:
                ausloesen = False
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    ausloesen = self._hold_abort_btn.hit(event.pos)
                elif event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_RETURN, pygame.K_SPACE):
                    ausloesen = True
                elif event.type == pygame.JOYBUTTONDOWN and event.button == gamepad.BTN_A:
                    ausloesen = True
                if ausloesen:
                    self._abort_held_race()
                    return

            if getattr(self, "_resume_countdown_timer", 0.0) > 0.0:
                continue
            if self._dialog is not None:
                res = self._dialog.handle_event(event)
                if res == "ok":
                    grand_prix.cancel()
                    gamepad.set_menu_translation(True)
                    self.state_machine.transition("menu")
                    self._dialog = None
                elif res == "cancel":
                    self._dialog = None
                return

            is_toggle = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                is_toggle = True
            elif event.type == pygame.JOYBUTTONDOWN and event.button in (gamepad.BTN_START, gamepad.BTN_BACK):
                is_toggle = True

            # Inside a pause sub-view "back" must climb one level, not drop out
            # of the pause menu entirely — the sub-view handlers below do that.
            if is_toggle and self.paused and self._pause_view in ("settings", "standings"):
                is_toggle = False

            if is_toggle:
                if self._online:
                    # Sub-views are handled below; here we only request a pause.
                    if not self.paused:
                        from src.net import session as _sess
                        _nc = _sess.get()
                        if _nc is not None:
                            _nc.send_tcp({"type": "PAUSE"})
                else:
                    self.paused = not self.paused
                    if self.paused:
                        self._pause_view = "main"
                        self._pause_group = self._pause_main_group()
                        self._pause_group.index = 0   # start on "Fortsetzen"
                        gamepad.set_menu_translation(True)
                    else:
                        self._pause_settings = None
                        gamepad.set_menu_translation(False)
                return
                
            if self.paused:
                if self._pause_view == "main":
                    action = self._pause_group.handle_event(event)
                    if action == "resume":
                        self.paused = False
                        gamepad.set_menu_translation(False)
                        return
                    elif action == "standings":
                        self._pause_view = "standings"
                        from src.ui.widgets import Button
                        from src.ui.focus import FocusGroup
                        self._pause_group = FocusGroup([
                            Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, 820, 300, 50), "‹ Zurück", "back_to_main")
                        ])
                        return
                    elif action == "settings":
                        self._open_pause_settings()
                        return
                    elif action == "quit":
                        if grand_prix.is_active():
                            from src.ui.widgets import Dialog
                            self._dialog = Dialog(
                                tr("Grand Prix abbrechen?"),
                                tr("Der Zwischenstand geht verloren."),
                                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")]
                            )
                        else:
                            if self._online:
                                from src.net import session as _sq
                                _ncq = _sq.get()
                                if _ncq is not None:
                                    _ncq.send_tcp({"type": "ABORT_RACE"})
                                gamepad.set_menu_translation(True)
                                self.state_machine.transition("menu", reopen="online_lobby_resume")
                            else:
                                gamepad.set_menu_translation(True)
                                self.state_machine.transition("menu")
                        return
                elif self._pause_view == "multiplayer_pause":
                    action = self._pause_group.handle_event(event)
                    if action == "ready_resume":
                        from src.net import session as _sess
                        _nc = _sess.get()
                        if _nc is not None:
                            _nc.send_tcp({"type": "RESUME_READY"})
                        self._local_resume_ready = True
                        
                        from src.ui.widgets import Button
                        from src.ui.focus import FocusGroup
                        self._pause_group = FocusGroup([
                            Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 30, 300, 50), tr("Bereit") + f" {theme.HAKEN}", "none", enabled=False),
                            Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 90, 300, 50), tr("Einstellungen"), "settings"),
                            Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 150, 300, 50), tr("Beenden"), "quit")
                        ])
                        self._pause_group.index = 1  # focus settings
                    elif action == "settings":
                        self._open_pause_settings()
                    elif action == "quit":
                        from src.net import session as _sq
                        _ncq = _sq.get()
                        if _ncq is not None:
                            _ncq.send_tcp({"type": "ABORT_RACE"})
                        gamepad.set_menu_translation(True)
                        self.state_machine.transition("menu", reopen="online_lobby_resume")
                    return
                elif self._pause_view == "standings":
                    is_back = False
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        is_back = True
                    elif event.type == pygame.JOYBUTTONDOWN and event.button in (gamepad.BTN_BACK, gamepad.BTN_B):
                        is_back = True
 
                    action = self._pause_group.handle_event(event)
                    if action == "back_to_main" or is_back:
                        self._pause_view = "multiplayer_pause" if self._online else "main"
                        self._pause_group = self._pause_main_group()
                        if not self._online:
                            self._pause_group.index = 1   # back on "Rennstand"
                        return
                elif self._pause_view == "settings":
                    # The settings page owns its own levels (content focus, save
                    # button, dialogs). Only when it does NOT consume "back" does
                    # the pause menu climb up one level.
                    if self._pause_settings is not None and self._pause_settings.handle_event(event):
                        return

                    is_back = False
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        is_back = True
                    elif event.type == pygame.JOYBUTTONDOWN and event.button in (gamepad.BTN_BACK, gamepad.BTN_B):
                        is_back = True

                    if is_back:
                        self._leave_pause_settings()
                    return
            
            # Non-paused events:
            if not self.paused and event.type == pygame.KEYDOWN:
                pass  # ENTER-skip removed: race ends directly via _go_to_results()

        # Driving input is read from each human's input source in update().

    def update(self, dt: float) -> None:
        """Update physics, player vehicle position, camera, and HUD."""
        # Strecke war nicht ladbar - zurueck ins Menue statt weiterzulaufen.
        # Der Wechsel passiert hier statt in enter(), weil transition() dort
        # rekursiv in den gerade entstehenden Zustand greifen wuerde.
        if getattr(self, "_load_failed", ""):
            # Kennzeichen bleibt gesetzt, damit auch ein weiterer update() nicht
            # in den halbfertigen Zustand laeuft; enter() setzt es zurueck.
            if not self._load_failed_handled:
                self._load_failed_handled = True
                from src.core import gamepad, grand_prix
                grand_prix.cancel()
                gamepad.set_menu_translation(True)
                self.state_machine.transition("menu", track_error=True)
            return

        if dt <= 0.0:
            return

        # Online: nach dem eigenen Laden warten wir auf die LOADED-Meldungen der
        # anderen. Kommt eine nie - etwa weil ein Mitspieler gar nicht ins Rennen
        # gestartet ist - haengt der Bildschirm sonst unbegrenzt. Kein
        # automatischer Abbruch: die Gegenseite laedt womoeglich noch eine
        # uebertragene Strecke und rechnet Ideallinien. Stattdessen bekommt der
        # Host nach kurzer Zeit einen Knopf und entscheidet selbst.
        if (self._online and self.race_manager
                and self.race_manager.state == "countdown"
                and getattr(self.race_manager, "_hold_countdown", False)):
            import time as _t
            if self._hold_since <= 0.0:
                self._hold_since = _t.time()
        elif self._hold_since:
            # Warten vorbei - Hintergrundvideo freigeben.
            self._hold_since = 0.0
            self._hold_abort_btn = None
            self._close_loading_video()

        from src.core import race_setup
        setup = race_setup.current()

        # Das Feld, das die KI sieht, je Bild einmal fortschreiben. Einmal je
        # Bild statt an jeder Stelle, die etwas hinzufuegt oder wegnimmt: es sind
        # hoechstens ein Dutzend Fahrzeuge, und ein vergessener Aufruf waere
        # genau der Fehler, der gemeldet wurde.
        self._ai_feld_auffrischen()

        # Simple low-pass filter for FPS calculation
        fps_instant = 1.0 / dt
        self._fps_filtered += (fps_instant - self._fps_filtered) * 0.1

        # Online leave-toasts count down in real time regardless of pause state —
        # they're an informational notice about a network event, not part of the
        # race simulation, so freezing them on pause would just make them linger
        # oddly long once the race resumes.
        if getattr(self, "_leave_toasts", None):
            for toast in self._leave_toasts:
                toast["timer"] -= dt
            self._leave_toasts = [t for t in self._leave_toasts if t["timer"] > 0.0]

        if getattr(self, "_resume_countdown_timer", 0.0) > 0.0:
            self._resume_countdown_timer = max(0.0, self._resume_countdown_timer - dt)
            if self._resume_countdown_timer <= 0.0:
                self.paused = False
                self._pause_view = "main"
                from src.core import gamepad
                gamepad.set_menu_translation(False)
            if self._online:
                self._update_online(dt)
            return

        if self.paused:
            if getattr(self, "_pause_view", None) == "settings" and getattr(self, "_pause_settings", None):
                self._pause_settings.update(dt)
            if self._online:
                self._update_online(dt)
            return

        if self.physics_world:
            self.physics_world.step(dt)

        if self.ghost_recorders and self.race_manager and self.race_manager.state == "racing":
            for pid, rec in self.ghost_recorders.items():
                p = self.player if pid == 1 else self.player2
                if p and p.body:
                    tracker = self.race_manager.lap_trackers[pid]
                    rec.record(
                        tracker.current_lap_time,
                        p.body.position.x,
                        p.body.position.y,
                        p.body.angle
                    )

        if self.race_manager:
            if (not self._race_music_started
                    and self.race_manager.state == "countdown"):
                from src.core import audio
                audio.play_race_music()
                self._race_music_started = True
            self._startsignal_pruefen()
            self.race_manager.update(dt)
            self._apply_finish_effects()

            # Online: the moment the first car (locally) crosses the line, tell
            # the server so it can start the shared DNF grace window. Sent once.
            if (self._online and not self._first_finish_sent
                    and self.race_manager._leader_finish_time is not None):
                self._first_finish_sent = True
                from src.net import session as _sess
                _nc = _sess.get()
                if _nc is not None:
                    _nc.send_tcp({"type": "FIRST_FINISH",
                                  "slowest_lap": self.race_manager.leader_slowest_lap() or 0.0})

            # As soon as the race is finished, go to the results screen. Online:
            # report our result and wait for the server's combined standings.
            if self.race_manager.state == "finished" and not self._results_sent:
                # A car forced to DNF rolls out for a beat before results. The
                # rest of update() keeps running so the camera still follows the
                # coasting car; only the jump to results waits.
                if self._local_is_dnf() and self._dnf_coast_timer <= 0.0 \
                        and not self._dnf_coast_done:
                    self._dnf_coast_timer = DNF_COAST_SECONDS
                if self._dnf_coast_timer > 0.0:
                    self._dnf_coast_timer -= dt
                    if self._dnf_coast_timer <= 0.0:
                        self._dnf_coast_done = True
                else:
                    self._results_sent = True
                    if self._online:
                        import time as _t
                        self._online_send_result()
                        self._online_awaiting = True
                        self._online_await_deadline = _t.time() + 30.0
                    else:
                        # Kurze Nachlaufzeit mit Ausblenden statt uebergangslos
                        # in den Ergebnisschirm (08.08.2026). Die Welt laeuft
                        # diesen und die naechsten Bilder weiter.
                        self._starte_ausblenden(None)

            # Ausblenden ticken — laeuft auch, wenn _results_sent schon steht.
            if self._outro_active:
                self._outro_timer -= dt
                if self._outro_timer <= 0.0:
                    self._outro_active = False
                    self._go_to_results(self._outro_rows)
                    return

        # Update AI opponents (controllers read fresh positions post-physics-step).
        if self.ai_vehicles:
            self._update_rubber_banding()
            for ai in self.ai_vehicles:
                ai.update(dt)

        self._klang_aktualisieren()
        # Nach dem Klang, damit die Bildzeit die Arbeit dieses Bildes enthaelt.
        from src.core import klangmitschnitt
        if klangmitschnitt.laeuft():
            klangmitschnitt.bild(dt)
        if self._mitschnitt_hinweis is not None:
            text, rest = self._mitschnitt_hinweis
            self._mitschnitt_hinweis = (text, rest - dt)

        countdown = self.race_manager and self.race_manager.state == "countdown"
        coasting = self._dnf_coast_timer > 0.0
        for hp, cam in zip(self._humans, self._kameras):
            if coasting:
                # Forced-DNF roll-out: no input, let friction bring it to rest.
                hp.throttle, hp.brake_input, hp.steer_input = 0.0, 0.0, 0.0
            elif hp.id in self._player_ai_ids and getattr(hp, "controller", None):
                # AI drives this human's cool-down lap after the finish line.
                hp.throttle, hp.brake_input, hp.steer_input = \
                    hp.controller.compute_inputs(dt)
            elif countdown:
                hp.throttle, hp.brake_input, hp.steer_input = 0.0, 1.0, 0.0
            else:
                hp.handle_input()   # read this human's input source
            hp.update(dt)
            cam.folgen(welt3d(hp.position), hp.angle, dt)

        # Was in diesem Bild zu sehen ist, einmal je Bild einsammeln - nicht
        # beim Zeichnen. Im Splitscreen wird zweimal gezeichnet, aber es
        # vergeht nur einmal Zeit; die Raeder wuerden sonst doppelt so schnell
        # drehen.
        self._staende_fortschreiben(dt)

        # Online: remote cars (other humans + their AI ghosts) are not in the
        # local RaceManager — add them so "Position x/y" shows the real field size.
        total_field = len(self.race_manager.vehicles) + (len(self._remote_vehicles) if self._online else 0) if self.race_manager else 0

        # In splitscreen each half draws its own HUD directly
        if self._split and self.hud1 and self.hud2 and self.player and self.player2 and self.race_manager:
            for p, h in [(self.player, self.hud1), (self.player2, self.hud2)]:
                tracker = self.race_manager.lap_trackers[p.id]
                pos = self.race_manager.get_position(p.id)
                live_diff = None
                if getattr(self, "ghost_player", None) is not None:
                    pos_coords = (p.body.position.x, p.body.position.y) if p.body else (0.0, 0.0)
                    live_diff = self.ghost_player.get_live_diff(pos_coords, tracker.current_lap_time)

                standings_info = []
                if setup.mode == "Team-Zeitfahren":
                    standings_info = self._team_standings_info(p.id)

                h.update(
                    speed=p.signed_speed,
                    fps=self._fps_filtered,
                    rpm=p.rpm,
                    redline_rpm=p.engine.redline_rpm,
                    shift_up_rpm=p.engine.shift_up_rpm,
                    gear=p.gear,
                    is_drifting=p.is_drifting,
                    current_lap=tracker.current_lap,
                    total_laps=self.race_manager.total_laps,
                    current_lap_time=tracker.current_lap_time,
                    best_lap_time=tracker.best_lap_time,
                    last_lap_time=tracker.last_lap_time,
                    position=pos,
                    total_vehicles=total_field,
                    countdown_timer=self.race_manager.countdown_timer if self.race_manager.state == "countdown" else None,
                    split_info=tracker.last_split_info,
                    race_finished=(self.race_manager.state == "finished"),
                    sector_diff=tracker.last_sector_diff,
                    results=self.race_manager.results,
                    player_id=p.id,
                    waiting_for_field=(self.race_manager.state == "finishing"
                                       or self._online_awaiting),
                    dnf_seconds=self._dnf_restzeit(p.id),
                    live_diff=live_diff,
                    standings=standings_info,
                    dt=dt
                )
        elif not self._split and self.hud and self.player and self.race_manager:
            tracker = self.race_manager.lap_trackers[self.player.id]
            pos = self._online_position(self.player.id) if self._online else self.race_manager.get_position(self.player.id)
            live_diff = None
            if getattr(self, "ghost_player", None) is not None:
                pos_coords = (self.player.body.position.x, self.player.body.position.y) if self.player.body else (0.0, 0.0)
                live_diff = self.ghost_player.get_live_diff(pos_coords, tracker.current_lap_time)

            standings_info = []
            if setup.mode == "Team-Zeitfahren":
                standings_info = self._team_standings_info(self.player.id)

            self.hud.update(
                speed=self.player.signed_speed,
                fps=self._fps_filtered,
                rpm=self.player.rpm,
                redline_rpm=self.player.engine.redline_rpm,
                shift_up_rpm=self.player.engine.shift_up_rpm,
                gear=self.player.gear,
                is_drifting=self.player.is_drifting,
                current_lap=tracker.current_lap,
                total_laps=self.race_manager.total_laps,
                current_lap_time=tracker.current_lap_time,
                best_lap_time=tracker.best_lap_time,
                last_lap_time=tracker.last_lap_time,
                position=pos,
                total_vehicles=total_field,
                countdown_timer=self.race_manager.countdown_timer if self.race_manager.state == "countdown" else None,
                split_info=tracker.last_split_info,
                race_finished=(self.race_manager.state == "finished"),
                sector_diff=tracker.last_sector_diff,
                results=self.race_manager.results,
                player_id=self.player.id,
                waiting_for_field=(self.race_manager.state == "finishing"
                                   or self._online_awaiting),
                dnf_seconds=self._dnf_restzeit(self.player.id),
                live_diff=live_diff,
                standings=standings_info,
                dt=dt
            )

        if self._online:
            self._update_online(dt)

        # Finished an online race: the sim keeps running (finished cars do their
        # AI cool-down lap) while we wait for the server's combined standings.
        if self._online_awaiting:
            import time as _t
            # A guest still racing sends state at 30 Hz — keep waiting as long
            # as any remote car is alive (fresh snapshot within 5s). The fixed
            # deadline only fires once every remote has gone silent, so a
            # vanished peer can't hold the host hostage forever.
            if any(rv.seconds_since_update() < 5.0 for rv in self._remote_vehicles):
                self._online_await_deadline = max(self._online_await_deadline, _t.time() + 15.0)
            if self._online_results_rows is not None:
                self._online_awaiting = False
                self._starte_ausblenden(self._online_results_rows)
            elif _t.time() > self._online_await_deadline:
                self._online_awaiting = False
                self._starte_ausblenden(None)   # fallback: local results only

    # ------------------------------------------------------------------
    # Die Welt in 3D
    # ------------------------------------------------------------------

    def _szene_aufbauen(self) -> None:
        """Streckennetz und Fahrzeugmodelle an OpenGL geben.

        Ohne Kontext bleibt ``self.szene`` ``None``: dann wird keine Welt
        gezeichnet und alles andere — Rennlogik, HUD, Minimap, KI, Netz —
        laeuft weiter. Das ist der Testlauf ohne Fenster und kein Rueckfall
        auf einen zweiten Zeichenweg.
        """
        self.szene = None
        from src.core import display
        if display.kontext() is None:
            return
        from src.core.paths import bundle_dir
        from src.render3d import rennszene, track_mesh
        try:
            netz = track_mesh.aus_datei(self._track_path)
            wurzel = bundle_dir()
            self.szene = rennszene.Rennszene(
                display.kontext(), netz,
                modellordner=wurzel / "assets" / "vehicles",
                korrektur_datei=wurzel / "trellis_import.json")
        except Exception as fehler:
            # Ein Fehler in der Darstellung darf kein Rennen kosten. Die
            # Strecke laeuft weiter, man sieht sie nur nicht.
            print(f"[RaceState] 3D-Szene nicht aufgebaut: {fehler}")
            self.szene = None

    def _weg_in_diesem_bild(self, fahrzeug, dt: float) -> float:
        """Wieviel Weg ein Fahrzeug in diesem Bild zurueckgelegt hat, in Metern.

        Mit Vorzeichen: rueckwaerts drehen die Raeder rueckwaerts. Wo es
        ``signed_speed`` gibt (Spieler und KI), ist das der genaue Wert; ein
        ferngesteuertes Fahrzeug bringt nur den Betrag mit und faehrt im Netz
        ohnehin vorwaerts.
        """
        tempo = getattr(fahrzeug, "signed_speed", None)
        if tempo is None:
            tempo = getattr(fahrzeug, "speed", 0.0) or 0.0
        weg = float(tempo) * M_PER_PX * dt
        return max(-WEG_JE_BILD_HOECHSTENS_M, min(WEG_JE_BILD_HOECHSTENS_M, weg))

    def _stand_von(self, fahrzeug, dt: float):
        """Einen Fahrzeugstand aus einem Fahrzeug des Spiels bauen."""
        from src.render3d import rennszene, vehicle_node
        return rennszene.Fahrzeugstand(
            kennung=int(getattr(fahrzeug, "id", 0)),
            schluessel=getattr(fahrzeug, "config_key", "") or "rookie",
            pos_m=welt3d(fahrzeug.position),
            gierwinkel_rad=float(fahrzeug.angle),
            weg_m=self._weg_in_diesem_bild(fahrzeug, dt),
            lenkwinkel_rad=vehicle_node.lenkwinkel_aus_fahrzeug(fahrzeug),
        )

    def _ghost_stand(self):
        """Der Ghost als Fahrzeugstand, entfaerbt.

        Sein Weg kommt aus der Ortsaenderung: ein Ghost ist eine Aufzeichnung
        von Positionen und hat weder Tacho noch Lenkwinkel.
        """
        if not getattr(self, "ghost_player", None) or not self.race_manager:
            return None
        tracker = self.race_manager.lap_trackers.get(1)
        if tracker is None:
            return None
        lage = self.ghost_player.get_position(tracker.current_lap_time)
        if not lage:
            self._ghost_letzte_pos = None
            return None
        x, y, winkel = lage

        weg_m = 0.0
        if self._ghost_letzte_pos is not None:
            dx = x - self._ghost_letzte_pos[0]
            dy = y - self._ghost_letzte_pos[1]
            # Auf die Blickrichtung gerechnet, damit ein rueckwaerts rollender
            # Ghost auch rueckwaerts drehende Raeder hat.
            weg_m = (dx * math.cos(winkel) + dy * math.sin(winkel)) * M_PER_PX
            weg_m = max(-WEG_JE_BILD_HOECHSTENS_M,
                        min(WEG_JE_BILD_HOECHSTENS_M, weg_m))
        self._ghost_letzte_pos = (x, y)

        from src.render3d import rennszene
        return rennszene.Fahrzeugstand(
            kennung=GHOST_KENNUNG,
            schluessel=getattr(self.ghost_player.data, "vehicle", "") or "rookie",
            pos_m=welt3d((x, y)),
            gierwinkel_rad=float(winkel),
            weg_m=weg_m,
            entfaerbt=True,
        )

    def _staende_fortschreiben(self, dt: float) -> None:
        """Einsammeln, wer in diesem Bild zu sehen ist, und die Raeder drehen."""
        staende = [self._stand_von(v, dt)
                   for v in (*self._humans, *self.ai_vehicles, *self._remote_vehicles)]
        ghost = self._ghost_stand()
        if ghost is not None:
            staende.append(ghost)
        self._staende = staende
        if self.szene is not None:
            self.szene.fortschreiben(staende)

    def _welt_zeichnen(self) -> None:
        """Die Welt in OpenGL zeichnen, einmal je Kamera.

        Im Splitscreen bekommt jede Kamera ihre eigene Bildhaelfte als
        Ansichtsfenster; die Schere haelt jede Haelfte in ihren Grenzen. Das
        HUD kommt danach ueber die eine virtuelle Flaeche und weiss von der
        Teilung nichts.
        """
        self._letzte_sicht = None
        if self.szene is None or not self._kameras:
            return
        from src.core import display
        from src.render3d import camera as kamera3d
        ctx = display.kontext()
        if ctx is None:
            return

        briefkasten = display.ansichtsfenster(display.current_win_size())
        x, y, b, h = briefkasten
        if self._split and len(self._kameras) > 1:
            haelften = [(x, y, b // 2, h), (x + b // 2, y, b - b // 2, h)]
        else:
            haelften = [briefkasten]

        for ausschnitt, kam in zip(haelften, self._kameras):
            _vx, _vy, vb, vh = ausschnitt
            ctx.viewport = ausschnitt
            ctx.scissor = ausschnitt
            projektion = kamera3d.perspektive(
                SICHTFELD_GRAD, vb / max(1, vh), NAHE_EBENE_M, FERNE_EBENE_M)
            mvp = projektion @ kam.blickmatrix()
            self.szene.zeichnen(mvp, kam.auge, self._staende)
            self._letzte_sicht = (mvp, ausschnitt, briefkasten)

    def auf_bildschirm(self, pos_px, hoehe_m: float = 0.0):
        """Einen Weltpunkt (Spielpixel) auf die virtuelle Flaeche rechnen.

        Fuer alles, was im 2D-Weg einfach den Kameraversatz abgezogen hat und
        jetzt durch die Projektion muss — das KI-Labor zeichnet damit seine
        Wegpunkte und Ideallinien ueber die 3D-Strecke.

        ``None``, wenn der Punkt hinter der Kamera liegt oder noch kein Bild
        gezeichnet wurde.
        """
        if self._letzte_sicht is None:
            return None
        import numpy as np
        mvp, (vx, vy, vb, vh), (bx, by, bb, bh) = self._letzte_sicht
        welt = np.array([pos_px[0] * M_PER_PX, pos_px[1] * M_PER_PX, hoehe_m, 1.0])
        clip = np.asarray(mvp, dtype=np.float64) @ welt
        if clip[3] <= 1e-6:
            return None
        ndc = clip[:3] / clip[3]
        # OpenGL zaehlt y von unten, die virtuelle Flaeche von oben.
        fenster_x = vx + (ndc[0] * 0.5 + 0.5) * vb
        fenster_y = vy + (ndc[1] * 0.5 + 0.5) * vh
        from src.core import display
        return (int((fenster_x - bx) / max(1, bb) * display.VIRT_W),
                int((bh - (fenster_y - by)) / max(1, bh) * display.VIRT_H))

    def _mitschnitt_zeichnen(self, screen: pygame.Surface) -> None:
        """Rueckmeldung des Klangmitschnitts, oben mittig unter dem Banner.

        Laeuft er, steht dort dauerhaft ein Hinweis: eine Aufnahme, von der man
        nicht weiss, ob sie mitschreibt, ist keine.
        """
        from src.core import klangmitschnitt
        text = None
        if self._mitschnitt_hinweis is not None:
            text, rest = self._mitschnitt_hinweis
            if rest <= 0.0:
                self._mitschnitt_hinweis = None
                text = None
        if text is None and klangmitschnitt.laeuft():
            text = tr("Mitschnitt läuft — F9 beendet ihn.")
        if text:
            theme.text(screen, text, theme.LABEL, theme.ACCENT,
                       (SCREEN_WIDTH // 2, 60), center=True)

    def render(self, screen: pygame.Surface) -> None:
        """Die Welt in 3D zeichnen, HUD und Minimap darueber.

        ``screen`` ist die virtuelle Flaeche von 1920x1080, und sie ist zu
        Beginn des Bildes **durchsichtig**. Wo hier nichts gezeichnet wird,
        scheint die 3D-Welt durch — deshalb wird sie nicht mehr mit der
        Hintergrundfarbe der Strecke gefuellt. Die Farbe war im 2D-Weg das,
        was ausserhalb der Fahrbahn zu sehen war; in 3D ist das der
        Untergrund und der Himmel.
        """
        self._welt_zeichnen()

        if self._split:
            for x, hud_obj in [(0, self.hud1), (SCREEN_WIDTH // 2, self.hud2)]:
                if hud_obj:
                    sub = screen.subsurface((x, 0, SCREEN_WIDTH // 2, SCREEN_HEIGHT))
                    hud_obj.render(sub, scale=0.75)
            pygame.draw.line(screen, (12, 12, 18),
                             (SCREEN_WIDTH // 2, 0), (SCREEN_WIDTH // 2, SCREEN_HEIGHT), 4)
        else:
            if DEBUG and self.physics_world:
                self.physics_world.debug_draw(screen)
            if self.hud:
                self.hud.render(screen)
            if self._online:
                self._render_ping_overlay(screen)
                self._render_leave_toasts(screen)

        # Shared minimap (all vehicles).
        if getattr(self, "minimap", None):
            vehicles = [*self._humans, *self.ai_vehicles, *self._remote_vehicles]
            pid = self.player.id if self.player else None
            self.minimap.render(screen, vehicles, player_id=pid)

        self._mitschnitt_zeichnen(screen)

        # Online: a peer that finished loading early sits in a frozen scene
        # until everyone has loaded (RACE_GO). Show a proper waiting screen
        # instead, mirroring the host's loading phase.
        if (self._online and self.race_manager
                and self.race_manager.state == "countdown"
                and getattr(self.race_manager, "_hold_countdown", False)):
            import time as _t
            cx, cy = SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2

            # Derselbe Hintergrund wie beim Ladebildschirm des Hosts. Vorher sah
            # ein Gast nur ein halbdurchsichtiges Overlay ueber der fertigen
            # Strecke - er stand also gefuehlt schon im Rennen, waehrend der Host
            # noch lud. Jetzt sieht die Wartezeit auf beiden Seiten gleich aus.
            vid = getattr(self, "_load_video", None)
            frame = vid.get_surface() if (vid is not None and vid.ok) else None
            if frame is not None:
                vid.update(1.0 / 60.0)
                screen.blit(frame, (0, 0))
                dark = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                dark.fill((0, 0, 0, 150))
                screen.blit(dark, (0, 0))
            else:
                ov = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                ov.fill((0, 0, 0, 235))
                screen.blit(ov, (0, 0))

            dots = "." * (1 + int(_t.time() * 2) % 3)
            theme.text(screen, tr("Warte auf andere Fahrer") + dots, theme.TITLE,
                       theme.ACCENT, (cx, cy - 80), center=True)

            # Unbestimmter Fortschritt: wie lange die anderen brauchen, weiss
            # niemand. Ein wandernder Balken zeigt wenigstens, dass das Spiel
            # nicht eingefroren ist.
            bar_w, bar_h = 620, 30
            bx, by = cx - bar_w // 2, cy + 10
            pygame.draw.rect(screen, (40, 44, 56), (bx, by, bar_w, bar_h), border_radius=8)
            knopf_w = 160
            pos = (_t.time() * 220) % (bar_w + knopf_w) - knopf_w
            links = max(bx, bx + int(pos))
            rechts = min(bx + bar_w, bx + int(pos) + knopf_w)
            if rechts > links:
                pygame.draw.rect(screen, theme.ACCENT, (links, by, rechts - links, bar_h),
                                 border_radius=8)
            pygame.draw.rect(screen, theme.BORDER, (bx, by, bar_w, bar_h), 2, border_radius=8)

            theme.text(screen, tr("Rennen wird vorbereitet"), theme.HINT, theme.TEXT_DIM,
                       (cx, by + 56), center=True)
            if self._update_hold_abort_button():
                self._hold_abort_btn.draw(screen, focused=True)

        # Online: im Ziel, die anderen fahren noch. Hier steht bewusst nichts
        # mehr - der Hinweis liegt oben mittig im HUD (waiting_for_field), und
        # eine zweite Zeile unten lag quer ueber Drehzahl und Tacho.

        # Draw Pause menu overlay (skip for the dev/KI-Labor edit-pause, which
        # uses self.paused for its own overlay and has no race pause menu).
        if self.paused and not getattr(self, "_is_edit_pause", False):
            if self._pause_view == "settings" and self._pause_settings:
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 220))
                screen.blit(overlay, (0, 0))
                self._pause_settings.draw(screen, pygame.Rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT))
            elif self._pause_view == "standings":
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))

                panel_rect = pygame.Rect(SCREEN_WIDTH // 2 - 450, SCREEN_HEIGHT // 2 - 340, 900, 680)
                theme.panel(screen, panel_rect, alpha=235, border=theme.ACCENT)

                theme.text(screen, "RENNSTAND", theme.HEADER, theme.ACCENT,
                           (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 300), center=True)
                
                from src.core import grand_prix
                is_gp = grand_prix.is_active()
                
                tx = SCREEN_WIDTH // 2 - 400
                top = SCREEN_HEIGHT // 2 - 240
                
                pygame.draw.line(screen, theme.BORDER, (tx, top + 34), (tx + 800, top + 34), 2)
                
                cols = [
                    (tr("POS"), tx + 10),
                    (tr("FAHRER"), tx + 100),
                    (tr("RUNDE"), tx + 340),
                    (tr("ABSTAND"), tx + 480),
                    (tr("BESTE RUNDE"), tx + 640)
                ]
                if is_gp:
                    cols = [
                        (tr("POS"), tx + 10),
                        (tr("FAHRER"), tx + 100),
                        (tr("RUNDE"), tx + 300),
                        (tr("ABSTAND"), tx + 420),
                        (tr("BESTE RUNDE"), tx + 550),
                        (tr("GP-PUNKTE"), tx + 690)
                    ]
                
                for label, x in cols:
                    theme.text(screen, label, theme.LABEL, theme.TEXT_DIM, (x, top + 8))
                    
                pygame.draw.line(screen, theme.BORDER, (tx, top + 42), (tx + 800, top + 42), 1)
                
                standings_rows = []
                leader_time = None
                leader_vid = None
                leader_finished = False
                for idx, v in enumerate(self.race_manager._standings if self.race_manager else []):
                    tracker = self.race_manager.lap_trackers[v.id]
                    is_finished = v.id in self.race_manager.finished_ids

                    curr_total_time = sum(tracker.lap_times) + (0.0 if is_finished else tracker.current_lap_time)
                    if idx == 0:
                        leader_time = curr_total_time
                        leader_vid = v.id
                        leader_finished = is_finished

                    if idx == 0:
                        gap = tr("Leader")
                    elif is_finished and leader_finished and leader_time is not None:
                        # Beide im Ziel: hier ist die Zeitdifferenz keine
                        # Schaetzung mehr, sondern das Ergebnis.
                        gap = f"+{(curr_total_time - leader_time):.2f}s"
                    else:
                        # Sonst aus der Streckenposition schaetzen — die
                        # Rennzeit allein ist fuer alle gleich (siehe
                        # _abstand_sekunden).
                        sek = self._abstand_sekunden(v.id, leader_vid) if leader_vid else None
                        gap = f"+{sek:.2f}s" if sek is not None else "—"

                    bl = tracker.best_lap_time
                    bl_str = "—"
                    if bl != float("inf"):
                        m = int(bl // 60)
                        s = bl - m * 60
                        bl_str = f"{m}:{s:05.2f}" if m else f"{s:.2f}"

                    lap_val = min(tracker.current_lap, self.race_manager.total_laps)
                    lap_str = f"{lap_val}/{self.race_manager.total_laps}"
                    if is_finished:
                        res = next((r for r in self.race_manager.results if r["vehicle_id"] == v.id), None)
                        dnf = res.get("dnf", False) if res else False
                        lap_str = tr("Ziel") if not dnf else "DNF"

                    name = self._driver_names.get(v.id, f"Fahrer {v.id}")
                    if getattr(v, "is_takeover", False):
                        name += tr(" (KI)")

                    gp_pts_str = "—"
                    if is_gp:
                        gp = grand_prix.current()
                        gp_pts_str = f"{gp.points.get(name, 0)} {tr('Pkt')}"

                    standings_rows.append({
                        "pos": idx + 1,
                        "name": name,
                        "lap": lap_str,
                        "gap": gap,
                        "best": bl_str,
                        "gp": gp_pts_str,
                        "is_player": (v.id == 1),
                        "is_player2": (v.id == 2 and self._split)
                    })

                y = top + 56
                medals = {1: (255, 215, 0), 2: (200, 205, 215), 3: (205, 140, 80)}
                for row in standings_rows[:6]:
                    hl = (255, 165, 0) if row["is_player"] else ((60, 150, 255) if row["is_player2"] else None)
                    
                    rrect = pygame.Rect(tx, y - 4, 800, 48)
                    if hl is not None:
                        s = pygame.Surface(rrect.size, pygame.SRCALPHA)
                        s.fill((*theme.PANEL_SEL, 200))
                        screen.blit(s, rrect.topleft)
                        pygame.draw.rect(screen, hl, rrect, 2, border_radius=6)

                    pos_str = str(row["pos"])
                    pcol = medals.get(row["pos"], theme.TEXT)

                    theme.text(screen, pos_str, theme.BODY, pcol, (cols[0][1], y))
                    theme.text(screen, row["name"], theme.BODY, hl if hl is not None else theme.TEXT, (cols[1][1], y))
                    theme.text(screen, row["lap"], theme.BODY, theme.TEXT, (cols[2][1], y))
                    theme.text(screen, row["gap"], theme.BODY, theme.TEXT, (cols[3][1], y))
                    theme.text(screen, row["best"], theme.BODY, theme.TEXT, (cols[4][1], y))
                    if is_gp:
                        theme.text(screen, row["gp"], theme.BODY, theme.TEXT, (cols[5][1], y))
                    y += 54
                    
                if self._pause_group:
                    self._pause_group.draw(screen)

            elif getattr(self, "_pause_view", None) == "multiplayer_pause" and self._pause_group:
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))

                panel_rect = pygame.Rect(SCREEN_WIDTH // 2 - 250, SCREEN_HEIGHT // 2 - 240, 500, 480)
                theme.panel(screen, panel_rect, alpha=235, border=theme.ACCENT)

                theme.text(screen, tr("PAUSE"), theme.HEADER, theme.ACCENT,
                           (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 200), center=True)

                paused_by = getattr(self, "_pause_by_name", tr("Spieler"))
                theme.text(screen, tr("{name} hat das Spiel pausiert.").format(name=paused_by),
                           theme.BODY, theme.TEXT,
                           (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 150), center=True)

                # Draw player readiness list
                py = SCREEN_HEIGHT // 2 - 100
                players = getattr(self, "_mp_pause_players", [])
                for p in players:
                    pname = p.get("name", "Spieler")
                    is_ready = p.get("ready", False)
                    p_txt = f"{pname}: " + (tr("Bereit") + f" {theme.HAKEN}" if is_ready else tr("Wartet..."))
                    p_col = (100, 225, 100) if is_ready else theme.TEXT_DIM
                    theme.text(screen, p_txt, theme.BODY, p_col,
                               (SCREEN_WIDTH // 2, py), center=True)
                    py += 30

                self._pause_group.draw(screen)

            elif self._pause_group:
                overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 180))
                screen.blit(overlay, (0, 0))

                panel_rect = pygame.Rect(SCREEN_WIDTH // 2 - 200, SCREEN_HEIGHT // 2 - 170, 400, 340)
                theme.panel(screen, panel_rect, alpha=230, border=theme.ACCENT)

                theme.text(screen, tr("PAUSE"), theme.HEADER, theme.ACCENT,
                           (SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 - 130), center=True)

                self._pause_group.draw(screen)

        # Draw resume countdown
        if getattr(self, "_resume_countdown_timer", 0.0) > 0.0:
            
            # Draw semi-transparent overlay
            overlay = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 100))
            screen.blit(overlay, (0, 0))
            
            val = self._resume_countdown_timer
            if val > 1.0:
                txt = str(math.ceil(val))
            else:
                txt = tr("LOS!")
                
            # Pulsing effect based on fractional part
            frac = val - int(val)
            if val <= 1.0:
                frac = val
            scale = 1.0 + 0.5 * (1.0 - frac)
            
            font_size = int(80 * scale)
            text_surf = theme.font(font_size).render(txt, True, theme.ACCENT)
            text_rect = text_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
            screen.blit(text_surf, text_rect)

        if self._dialog is not None:
            self._dialog.draw(screen)

        # Ausblenden vor den Ergebnissen ganz zuletzt, ueber allem: waehrend der
        # kurzen Nachlaufzeit zieht ein schwarzer Schleier auf (08.08.2026).
        alpha = self._outro_alpha()
        if alpha > 0:
            schleier = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            schleier.fill((0, 0, 0, alpha))
            screen.blit(schleier, (0, 0))

    # ── Online-multiplayer helpers ────────────────────────────────────────────

    def _is_online_host(self) -> bool:
        from src.net import session
        nc = session.get()
        return nc is not None and nc.slot == 0

    def _local_is_dnf(self) -> bool:
        """True if this peer's own car ended the race as a DNF."""
        if self.race_manager is None or self.player is None:
            return False
        return any(r["vehicle_id"] == self.player.id and r.get("dnf")
                   for r in self.race_manager.results)

    def _takeover_remote_vehicle(self, left_slot: int) -> bool:
        """Host-only: a player dropped mid-race — spawn an AI car at their last
        known position/lap so the race and team scoring keep going (A6).

        Must run BEFORE the corresponding ghost is despawned via
        `_remove_remote`, since it reads the ghost's last snapshot.

        Returns True if a takeover car was actually spawned (used to pick the
        right toast message), False if any guard/precondition short-circuited.
        """
        if not self._online or not self._is_online_host():
            return False
        if self.race_manager is None or self.race_manager.state == "finished":
            return False
        if self.physics_world is None:
            return False
        rv = self._remote_map.get((left_slot, 1))
        if rv is None:
            return False

        vid = TAKEOVER_ID_BASE + left_slot
        # Idempotency: a duplicate PLAYER_LEFT for the same slot must not spawn
        # a second car into the pymunk space (adopt_vehicle alone isn't enough —
        # it only guards *after* the vehicle/body would already have been built).
        if vid in self.race_manager.lap_trackers:
            return False

        # 1. Capture the ghost's last known state BEFORE it is torn down. The
        # "_target_*" fields are the raw last-received network snapshot (not
        # the smoothed/extrapolated render state), so they're the most honest
        # readout of where the player actually was.
        tx, ty = getattr(rv, "_target_pos", (0.0, 0.0))
        angle = getattr(rv, "_target_angle", 0.0)
        vx, vy = getattr(rv, "_target_vel", (0.0, 0.0))
        lap = getattr(rv, "lap", 0)
        wp = getattr(rv, "wp", 0)

        # 2. Who was driving, and in what car.
        from src.core import race_setup
        setup = race_setup.current()
        pinfo = setup.online_players.get(left_slot, {})
        name = pinfo.get("name", f"Spieler {left_slot}")
        team = pinfo.get("team", "A")
        cfg_key = self._remote_config_keys.get((left_slot, 1), "rookie")

        # 3. Build the replacement AI car at the captured transform.
        from src.entities.vehicle_factory import VehicleFactory
        from src.ai.difficulty import get_difficulty
        from src.core import lack
        veh = VehicleFactory.create_ai_vehicle(
            config_key=cfg_key,
            vehicle_id=vid,
            start_pos=(tx, ty),
            start_angle=angle,
            space=self.physics_world.space,
            track=self.track,
            difficulty=get_difficulty(setup.ai_difficulty),
            # Das Auto behaelt die Lackierung des Spielers, der ausgestiegen
            # ist — es ist dasselbe Auto, nur ohne Fahrer. Jede Gegenstelle
            # liest dieselbe Kennung aus dem Lobbyzustand.
            lack=lack.normalisiere(pinfo.get("paint", "")),
        )
        if veh is None:
            return False

        # 4. Carry the last known velocity over so the car doesn't stand still.
        if veh.body:
            veh.body.velocity = (vx, vy)

        # 5. Tag it so results/HUD/UDP streaming treat it like the other AI.
        veh.config_key = cfg_key
        veh.driver_name = name
        veh.team = team
        veh.is_takeover = True
        if self.race_manager.state in ("racing", "finishing"):
            veh.ai_active = True

        # 6. Splice into the race with the human's lap progress preserved.
        # Estimate current lap elapsed time from track waypoint ratio and race time.
        total_wp = len(getattr(self.track, "waypoints", [])) if self.track else 0
        frac = max(0.0, min(0.99, (wp / total_wp) if total_wp > 0 else 0.0))
        race_time = max(0.0, getattr(self.race_manager, "race_time", 0.0))
        laps_driven = max(0.1, (max(1, int(lap)) - 1) + frac)
        est_elapsed = max(0.0, frac * (race_time / laps_driven))
        self.race_manager.adopt_vehicle(veh, lap=lap, waypoint_progress=wp, elapsed=est_elapsed)


        # 7. From here on it streams like any other host-simulated AI.
        self.ai_vehicles.append(veh)
        self._driver_names[vid] = name
        self._vehicle_model[vid] = tr(getattr(veh.config, "name", ""))
        setup.online_ai_teams[vid] = team
        return True

    def _lack_fuer(self, sender_slot: int, vehicle_id: int) -> str:
        """Die Lackierung, in der das Abbild eines Mitspielers gezeichnet wird (D7).

        Sie kommt aus dem Lobbyzustand (``PICK`` → ``settings["picks"]`` →
        ``online_players``) und nicht aus dem UDP-Strom: der traegt je Fahrzeug
        26 feste Bytes und ist kein Ort fuer eine Kennung.

        ``vehicle_id == 1`` ist das Auto des Mitspielers selbst; alles andere
        streamt der Gastgeber fuer seine KI. Deren Farbe steht in **keiner**
        Nachricht: sie haengt allein an der Fahrzeugnummer, und die ist auf
        beiden Seiten dieselbe (``lack.ki_lack``). Ein uebernommenes Auto
        (``TAKEOVER_ID_BASE + Platz``) behaelt die Lackierung seines
        ausgestiegenen Fahrers — auch die steht schon im Lobbyzustand.

        Was unbekannt hereinkommt, macht ``lack.normalisiere`` zum Werkslack —
        ein alter Client oder ein Relay ohne das Feld sieht aus wie vorher.
        """
        from src.core import lack
        from src.core import race_setup
        setup = race_setup.current()
        if vehicle_id >= TAKEOVER_ID_BASE:
            fahrer = setup.online_players.get(vehicle_id - TAKEOVER_ID_BASE, {})
            return lack.normalisiere(fahrer.get("paint", ""))
        if vehicle_id != 1:
            return lack.ki_lack(vehicle_id)
        info = setup.online_players.get(sender_slot, {})
        return lack.normalisiere(info.get("paint", ""))

    def _get_or_create_remote(self, sender_slot: int, vehicle_id: int, config_key: str = "rookie"):
        """Return cached RemoteVehicle for (slot, vehicle_id), creating on first call.

        Keyed by both slot and vehicle_id because one sender (the host) streams
        multiple vehicles in a single packet — its own car plus every AI car.
        """
        key = (sender_slot, vehicle_id)
        if key not in self._remote_map:
            from src.entities.remote_vehicle import RemoteVehicle
            rv = RemoteVehicle(
                vehicle_id=vehicle_id,
                sender_slot=sender_slot,
                space=self.physics_world.space,
                config_key=config_key,
                lack=self._lack_fuer(sender_slot, vehicle_id),
            )
            # Remembered so a host-side takeover can rebuild the same car —
            # RemoteVehicle itself doesn't retain the key past construction.
            self._remote_config_keys[key] = config_key
            # Also kept on the ghost so the engine sound can pick its class
            # without knowing about the slot bookkeeping.
            rv.config_key = config_key
            from src.core import race_setup
            setup = race_setup.current()
            if vehicle_id == 1:
                pinfo = setup.online_players.get(sender_slot, {})
                rv.driver_name = pinfo.get("name", f"Spieler {sender_slot}")
                rv.team = pinfo.get("team", "A")
            else:
                rv.driver_name = self._driver_names.get(vehicle_id, "KI")
                local_ai = next((ai for ai in self.ai_vehicles if ai.id == vehicle_id), None)
                if local_ai:
                    rv.team = local_ai.team
                else:
                    rv.team = setup.online_ai_teams.get(vehicle_id, "A")
            self._remote_vehicles.append(rv)
            self._remote_map[key] = rv
        return self._remote_map[key]

    def _remove_remote(self, sender_slot: int) -> None:
        """Despawn every ghost belonging to a slot that left / timed out."""
        for key in [k for k in self._remote_map if k[0] == sender_slot]:
            rv = self._remote_map.pop(key)
            self._remote_config_keys.pop(key, None)
            if self.physics_world:
                rv.cleanup(self.physics_world.space)
            if rv in self._remote_vehicles:
                self._remote_vehicles.remove(rv)

    def _teardown_online_net(self, why: str = "?") -> None:
        """Drop the network session mid-race and despawn all remote ghosts, so
        the local race can finish cleanly without frozen opponents on track."""
        from src.net import session
        for slot in {k[0] for k in self._remote_map}:
            self._remove_remote(slot)
        session.clear()

    def _online_send_result(self) -> None:
        """Report this peer's finish rows to the server for combined standings.
        The host reports its own car + every AI it simulated; a joining client
        reports only its own car."""
        from src.net import session
        from src.core import profile
        from src.core import race_setup
        nc = session.get()
        if nc is None or self.race_manager is None:
            return
        setup = race_setup.current()
        rows = []
        for r in self.race_manager.results:
            vid = r["vehicle_id"]
            vehicle = next((v for v in self.race_manager.vehicles if v.id == vid), None)
            if vid == 1:
                name = self._driver_names.get(1) or (profile.current().username or "Spieler")
                slot = self._my_online_slot
                team = setup.p1_team
            else:
                # AI (host only) — no network slot of its own.
                name = self._driver_names.get(vid, f"KI {vid}")
                slot = -1
                local_ai = next((ai for ai in self.ai_vehicles if ai.id == vid), None)
                team = getattr(local_ai, "team", None) or setup.online_ai_teams.get(vid, "A")
            rows.append({
                "slot": slot,
                "name": name,
                "vehicle": self._vehicle_model.get(vid, ""),
                "finish_time": r.get("finish_time"),
                "best_lap": r.get("best_lap"),
                "dnf": r.get("dnf", False),
                "team": team,
                "ai_takeover": bool(getattr(vehicle, "is_takeover", False)),
            })
        nc.send_tcp({"type": "RACE_RESULT", "rows": rows})

    def _update_online(self, dt: float) -> None:
        """Drain net queue, interpolate remote vehicles, send own state at 20 Hz."""
        from src.net import session
        nc = session.get()

        if nc is None:
            return

        # Der Keepalive laeuft in der Zustandsmaschine (07.08.2026) — hier
        # noch einmal zu ticken hiesse, doppelt so oft zu pingen.

        # ── Drain incoming events ──────────────────────────────────────────
        for evt in nc.poll():
            src = evt.get("source")
            data = evt.get("data", {})

            if src == "udp":
                # STATE packet: list of vehicles from a remote slot
                sender_slot = data.get("sender_slot")
                vehicles = data.get("vehicles", [])
                if sender_slot is None or sender_slot == nc.slot:
                    continue
                send_time = data.get("send_time", 0.0)
                arrival = data.get("arrival", 0.0)
                for snap in vehicles:
                    vid = snap.get("id", sender_slot * 100)
                    rv  = self._get_or_create_remote(sender_slot, vid, snap.get("cfg", "rookie"))
                    rv.apply_snapshot(snap, send_time, arrival)


            elif src == "udp_bump":
                if data.get("target_slot") == nc.slot:
                    imp = data.get("impulse", (0.0, 0.0))
                    if self.player and getattr(self.player, "body", None):
                        import pymunk
                        self.player.body.apply_impulse_at_local_point(
                            pymunk.Vec2d(float(imp[0]), float(imp[1]))
                        )


            elif src == "tcp":
                msg_type = data.get("type", "")
                if msg_type == "LOBBY_CLOSED":
                    # Host left the lobby (e.g. it reached the results screen and
                    # disconnected). Do NOT abort our own race — finish it locally
                    # and show our own results. Tear down networking and despawn
                    # remote ghosts (they'd otherwise freeze on track).
                    self._teardown_online_net("LOBBY_CLOSED")
                    return
                elif msg_type == "RACE_GO":
                    # Everyone finished loading — start the synchronized countdown.
                    if self.race_manager is not None:
                        self.race_manager.release_countdown(3.5)
                elif msg_type == "GAME_PAUSED":
                    self.paused = True
                    self._pause_by_name = data.get("by_name", "Spieler")
                    self._pause_view = "multiplayer_pause"
                    self._local_resume_ready = False
                    self._mp_pause_players = [{"name": self._pause_by_name, "slot": data.get("by_slot"), "ready": False}]
                    
                    from src.ui.widgets import Button
                    from src.ui.focus import FocusGroup
                    self._pause_group = FocusGroup([
                        Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 30, 300, 50), tr("Bereit zum Fortsetzen"), "ready_resume"),
                        Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 90, 300, 50), tr("Einstellungen"), "settings"),
                        Button(pygame.Rect(SCREEN_WIDTH // 2 - 150, SCREEN_HEIGHT // 2 + 150, 300, 50), tr("Beenden"), "quit")
                    ])
                    from src.core import gamepad
                    gamepad.set_menu_translation(True)
                elif msg_type == "PAUSE_STATUS":
                    self._pause_by_name = data.get("paused_by_name", "Spieler")
                    # Geprueft statt roh uebernommen: diese Liste wird im
                    # Zeichenpfad gelesen, ein kaputter Eintrag schluege dort
                    # jedes Bild zu - mitten im Rennen.
                    self._mp_pause_players = payload.dict_entries(data.get("players"))
                elif msg_type == "GAME_RESUME":
                    # Start unpause countdown
                    self._resume_countdown_timer = 3.0
                    self._pause_group = None
                    self._pause_settings = None
                elif msg_type == "RETURN_LOBBY":
                    # Another peer aborted the race — everyone back to the lobby.
                    from src.core import gamepad
                    gamepad.set_menu_translation(True)
                    self.state_machine.transition("menu", reopen="online_lobby_resume")
                    return
                elif msg_type == "FORCE_FINISH":
                    # Server's DNF grace window expired: end our race now. Any
                    # of our still-racing cars (own car for a guest, own car +
                    # remaining AI for the host) becomes DNF. The finished-state
                    # handling in update() then plays the coast-out and reports.
                    if self.race_manager is not None:
                        self.race_manager.force_finish_remaining()

                elif msg_type == "PLAYER_LEFT":
                    # Authoritative despawn from the server. Host-only: try to
                    # hand the car to an AI BEFORE the ghost is torn down, since
                    # the takeover reads its last snapshot.
                    left_slot = data.get("slot")
                    if left_slot is not None:
                        took_over = self._takeover_remote_vehicle(left_slot)
                        self._remove_remote(left_slot)
                        name = data.get("name", tr("Ein Spieler"))
                        if took_over:
                            toast_text = tr("{n} hat das Rennen verlassen — KI übernimmt").format(n=name)
                        else:
                            toast_text = tr("{n} hat das Rennen verlassen").format(n=name)
                        self._leave_toasts.append({"text": toast_text, "timer": 5.0})
                elif msg_type == "RACE_RESULTS" and self._online_awaiting:
                    # Combined standings for everyone (only meaningful once we
                    # have finished and are waiting).
                    out = []
                    for r in payload.dict_entries(data.get("rows")):
                        out.append({
                            "position": r.get("position"),
                            "name": r.get("name", ""),
                            "vehicle": r.get("vehicle", ""),
                            "finish_time": r.get("finish_time"),
                            "best_lap": r.get("best_lap"),
                            "dnf": r.get("dnf", False),
                            "is_player": r.get("slot") == self._my_online_slot,
                            "is_player2": False,
                            "sectors": [],
                            "team": r.get("team", "A"),
                            "ai_takeover": r.get("ai_takeover", False),
                        })
                    self._online_results_rows = out

            elif src == "error":
                # Our own connection dropped — keep racing locally to the finish
                # rather than dumping the player back to a stale lobby.
                self._teardown_online_net("error:" + str(data.get("type", "?")))
                return

        # ── Advance remote-vehicle interpolation ───────────────────────────
        for rv in self._remote_vehicles:
            rv.update(dt)

        # ── Local staleness fallback ───────────────────────────────────────

        # PLAYER_LEFT is authoritative, but if that TCP message is ever lost a
        # ghost would freeze on track forever. Prune anything stale past the
        # server's own UDP timeout (15 s) plus grace, so the server's PLAYER_LEFT
        # normally wins first and live-but-laggy players are never dropped early.
        _STALE_LIMIT = 18.0
        stale_slots = {
            rv.sender_slot for rv in self._remote_vehicles
            if rv.seconds_since_update() > _STALE_LIMIT
        }
        for slot in stale_slots:
            self._remove_remote(slot)

        # ── Send own position (denser for a moment after a bump) ───────────
        if self._contact_boost > 0.0:
            self._contact_boost = max(0.0, self._contact_boost - dt)
        hz = SEND_HZ_CONTACT if self._contact_boost > 0.0 else SEND_HZ_NORMAL
        _SEND_INTERVAL = 1.0 / hz
        self._send_accum += dt
        if self._send_accum >= _SEND_INTERVAL and self.player and self.player.body:
            self._send_accum -= _SEND_INTERVAL
            from src.core import race_setup as _rs
            b = self.player.body
            tracker = self.race_manager.lap_trackers.get(self.player.id) if self.race_manager else None
            vehicles = [{
                "id": self.player.id,
                "cfg": _rs.current().player_vehicle,
                "x": float(b.position.x),
                "y": float(b.position.y),
                "angle": float(b.angle),
                "vx": float(b.velocity.x),
                "vy": float(b.velocity.y),
                "omega": float(b.angular_velocity),
                "lap": tracker.current_lap if tracker else 0,
                "wp": int(tracker.waypoint_progress) if tracker else 0,
            }]
            # Host also broadcasts AI vehicles so clients see them
            if self._is_online_host():
                for ai in self.ai_vehicles:
                    if ai.body:
                        ab = ai.body
                        ai_tracker = self.race_manager.lap_trackers.get(ai.id) if self.race_manager else None
                        vehicles.append({
                            "id": ai.id,
                            "cfg": getattr(ai, "config_key", "rookie"),
                            "x": float(ab.position.x),
                            "y": float(ab.position.y),
                            "angle": float(ab.angle),
                            "vx": float(ab.velocity.x),
                            "vy": float(ab.velocity.y),
                            "omega": float(ab.angular_velocity),
                            "lap": ai_tracker.current_lap if ai_tracker else 0,
                            "wp": int(ai_tracker.waypoint_progress) if ai_tracker else 0,
                        })
            nc.send_state(vehicles)


    def _render_ping_overlay(self, screen: pygame.Surface) -> None:
        """Small ping badge in the top-left corner, below the FPS counter, during online races."""
        from src.net import session
        nc = session.get()
        if nc is None:
            return
        ping = int(nc.ping_ms)
        color = (80, 220, 80) if ping < 80 else ((255, 200, 0) if ping < 150 else (220, 80, 80))
        theme.text(screen, f"Ping: {ping} ms", theme.HINT, color, (20, 44))

    def _render_leave_toasts(self, screen: pygame.Surface) -> None:
        """Stacked, centered notices under the HUD's top edge: 'X left the race
        [— AI takes over]' (A20). Purely informational — no interaction."""
        if not self._leave_toasts:
            return
        y = 84
        for toast in self._leave_toasts:
            text_surf = theme.font(theme.LABEL).render(toast["text"], True, theme.TEXT)
            panel_rect = text_surf.get_rect(center=(SCREEN_WIDTH // 2, y))
            panel_rect.inflate_ip(32, 16)
            theme.panel(screen, panel_rect, alpha=200, border=theme.ACCENT)
            theme.text(screen, toast["text"], theme.LABEL, theme.TEXT,
                       (SCREEN_WIDTH // 2, y), center=True)
            y += panel_rect.height + 8
