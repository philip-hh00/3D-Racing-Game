"""KI-Labor – developer mode for inspecting and tuning the AI.

A subclass of :class:`RaceState` that drops the countdown, removes the human
player and spawns all five car types as non-colliding ghosts so the AI can be
watched on every vehicle at once. It layers on a pure *visualisation / tuning*
toolkit (no training – the racing line is computed geometrically at load):

* the geometric racing line from :mod:`src.ai.racing_line_solver` (green), with
  a live-tunable wall margin;
* live editing of the difficulty parameters, applied to all AI in real time;
* pause / single-frame stepping and camera cycling between cars;
* overlays for waypoints, the AI's steering target and its wall whiskers, plus a
  per-car telemetry panel.

Controls are listed on the in-game help panel (F1).
"""
from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING

import pygame
import pymunk

from src.states.race_state import RaceState
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.ai.difficulty import get_difficulty, save_difficulty, load_difficulty
from src.utils.math_utils import to_pygame
from src.core import keybindings as kb
from src.core import display
from src.ui import theme

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


# Editable parameters: (attribute, label, min, max, step, kind, group)
# group: "line" = triggers racing-line recomputation, "speed" = triggers speed-profile recomputation,
#        "ai" = applied live, "bool" = toggle
_PARAMS: list[tuple[str, str, float, float, float, str, str]] = [
    ("max_throttle",     "Speed-Faktor (Gas)", -1e9, 1e9, 0.02, "float", "ai"),
    ("overtake_dist",    "Überhol-Abst (px)",  -1e9, 1e9, 5.0,  "float", "ai"),
    ("brake_dist",       "Brems-Abstand (px)", -1e9, 1e9, 5.0,  "float", "ai"),
    ("draft_dist",       "Windschatten (px)",  -1e9, 1e9, 10.0, "float", "ai"),
    ("block_dist",       "Blockier-Abst (px)", -1e9, 1e9, 10.0, "float", "ai"),
]

_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "max_throttle": {
        "desc": "Limitiert das maximale Gaspedal (Topspeed auf Geraden).",
        "low": "Niedrig: Drosselt die Höchstgeschwindigkeit der KI stark.",
        "high": "Hoch: Erlaubt volles Ausfahren der Höchstgeschwindigkeit."
    },
    "overtake_dist": {
        "desc": "Abstand in Pixeln zum Vordermann, ab dem die KI versucht auszuscheren und zu überholen.",
        "low": "Niedrig: Zieht erst extrem spät/nah am Heck des Vordermannes heraus (aggressiv).",
        "high": "Hoch: Schert bereits sehr frühzeitig aus der Ideallinie aus."
    },
    "brake_dist": {
        "desc": "Sicherheitsabstand in Pixeln zum Heck des Vordermannes, ab dem aktiv gebremst wird.",
        "low": "Niedrig: Bremst erst im letzten Moment (Gefahr von Heckberührungen).",
        "high": "Hoch: Hält sehr großen Sicherheitsabstand ein und bremst früh."
    },
    "draft_dist": {
        "desc": "Maximale Distanz in Pixeln, ab der sich die KI aktiv hinter dem Vordermann einreiht.",
        "low": "Niedrig: Sucht den Windschatten erst bei sehr geringer Distanz.",
        "high": "Hoch: Versucht sich schon von weitem aerodynamisch einzusortieren."
    },
    "block_dist": {
        "desc": "Distanz zum Verfolger in Pixeln, bei der das defensive Abdecken der Spur beginnt.",
        "low": "Niedrig: Blockiert erst, wenn der Gegner fast neben einem ist.",
        "high": "Hoch: Macht bereits frühzeitig und vorsorglich die Überholspur zu."
    }
}


_GHOST_KEYS = ["rookie", "drifter", "electric", "limousine", "supercar"]
_GHOST_COLORS = [
    (45, 180, 220),   # Rookie (light blue)
    (230, 160, 40),   # Drifter (orange)
    (120, 220, 80),   # Electric (green)
    (140, 80, 200),   # Limousine (purple)
    (220, 50, 50),    # Supercar (red)
]


class _LiveDifficulty:
    """A mutable mirror of :class:`DifficultyConfig` the controllers read live."""

    def __init__(self, cfg) -> None:
        for f, v in dataclasses.asdict(cfg).items():
            setattr(self, f, v)

    def load_from(self, cfg) -> None:
        for f, v in dataclasses.asdict(cfg).items():
            setattr(self, f, v)

    def __setattr__(self, name, value):
        super().__setattr__(name, value)


class DevState(RaceState):
    """Developer visualisation / tuning playground built on top of the race."""

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self._fonts: dict[str, pygame.font.Font] = {}

        # Live tuning state
        self.live: _LiveDifficulty | None = None
        self.difficulty_keys = ["easy", "medium", "hard"]
        self.difficulty_index = 1
        self.sel_param = 0

        # View / playback state
        self.paused = False
        self._is_edit_pause = True   # our pause is an edit pause, not the race pause menu
        self._step = False
        self.cam_index = 0
        self.show_help = False
        self.show_waypoints = False
        self.show_line = True
        self.show_sensors = True
        self.show_telemetry = True

        # Geometric racing line
        self._solver_margin = 24.0

        # Cache of computed racing lines, keyed by (param-signature, car-name), so
        # cycling presets back and forth never recomputes the same trajectory twice.
        self._line_cache: dict[tuple, tuple] = {}

        # Collision toggle
        self._collisions_enabled = False

        # Toast notification
        self._toast_text: str = ""
        self._toast_timer: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, **kwargs) -> None:
        kwargs.setdefault("track_path", "data/tracks/oval.json")
        kwargs.setdefault("vehicle_config", "rookie")
        kwargs.setdefault("difficulty", self.difficulty_keys[self.difficulty_index])

        super().enter(**kwargs)

        # No human player in the lab – just watch the AI ghosts.
        if self.player:
            self.player.cleanup(self.physics_world.space)
            self.player = None

        # Ghosts pass through each other (group filter) so they can all share the
        # same line without bumping; they still collide with walls.
        if self.race_manager:
            self.race_manager.vehicles = self.ai_vehicles
            self.race_manager.lap_trackers = {
                v.id: self.race_manager.lap_trackers[v.id]
                for v in self.ai_vehicles if v.id in self.race_manager.lap_trackers
            }

        self._fonts = {
            "title": pygame.font.Font(None, 40),
            "body": pygame.font.Font(None, 26),
            "small": pygame.font.Font(None, 22),
            "big": pygame.font.Font(None, 64),
        }

        # Skip the countdown – race immediately, never auto-finish.
        if self.race_manager:
            self.race_manager.state = "racing"
            self.race_manager.total_laps = 9999
        for ai in self.ai_vehicles:
            ai.ai_active = True
            ai.controller.opponents = self.ai_vehicles

        key = kwargs.get("difficulty", "medium")
        self.difficulty_index = (
            self.difficulty_keys.index(key) if key in self.difficulty_keys else 1
        )

        # Try to load saved settings, fallback to defaults
        saved = load_difficulty(key)
        self.live = _LiveDifficulty(saved if saved else get_difficulty(key))

        # Sync solver margin from loaded config
        self._solver_margin = self.live.wall_margin

        pygame.key.set_repeat(250, 30)  # hold ←/→ to tune smoothly
        self._collisions_enabled = False
        self._apply_collision_mode()
        self._compute_solver_line()

    def exit(self) -> None:
        pygame.key.set_repeat()
        super().exit()

    def _line_signature(self) -> tuple:
        """All live params that change a racing line / speed profile, rounded."""
        L = self.live

        def g(attr: str, default: float) -> float:
            return round(getattr(L, attr, default), 4) if L else default

        return (
            g("grip_usage", 0.70), g("brake_confidence", 0.88),
            g("steer_confidence", 0.65), g("wall_margin", 24.0),
            g("corner_cutting", 0.45), round(self._solver_margin, 4),
        )

    def _compute_solver_line(self) -> None:
        """Rebuild per-vehicle racing lines, reusing cached ones where nothing changed."""
        from src.ai.racing_line_solver import compute_racing_line_optimized, SolvedRacingLine
        from src.ai.speed_profile import limits_from_config, compute_speed_profile

        if not self.track or not self.ai_vehicles:
            return

        center = self.track.centerline
        if not center or len(center) < 3:
            center = [(wp.x, wp.y) for wp in self.track.waypoints]

        screen = pygame.display.get_surface()
        total = len(self.ai_vehicles)
        sig = self._line_signature()

        for car_idx, ai in enumerate(self.ai_vehicles):
            car_name = getattr(ai.config, "name", f"Car {car_idx + 1}")
            cache_key = (sig, car_name)
            cached = self._line_cache.get(cache_key)
            if cached is not None:
                ai.controller.racing_line = SolvedRacingLine(*cached)
                continue

            margin = self._solver_margin + max(0.0, (ai.config.height_px - 48.0) * 0.5)

            def _progress(it, max_it, _cn=car_name, _ci=car_idx):
                if screen is not None:
                    self._render_loading(screen, _cn, _ci, total, it, max_it)

            geo = compute_racing_line_optimized(
                center, self.track.track_width,
                vehicle_config=ai.config,
                difficulty=self.live,
                car_width=ai.config.width_px,
                margin=margin,
                progress_callback=_progress,
            )
            grip = getattr(self.live, 'grip_usage', 0.70) if self.live else None
            brake = getattr(self.live, 'brake_confidence', 0.88) if self.live else None
            steer = getattr(self.live, 'steer_confidence', 0.65) if self.live else None

            lim = limits_from_config(ai.config, grip_usage=grip,
                                     brake_confidence=brake, steer_confidence=steer)
            profile = compute_speed_profile(geo, lim)
            args = (geo.offsets, profile, geo.signed_curvature, geo.points)
            self._line_cache[cache_key] = args
            ai.controller.racing_line = SolvedRacingLine(*args)

    # ------------------------------------------------------------------
    # Collision toggle
    # ------------------------------------------------------------------

    def _apply_collision_mode(self) -> None:
        """Set pymunk shape filters to enable/disable vehicle-vehicle collisions."""
        for ai in self.ai_vehicles:
            if self._collisions_enabled:
                ai.physics.shape.filter = pymunk.ShapeFilter(group=0)
            else:
                ai.physics.shape.filter = pymunk.ShapeFilter(group=1)

    def _toggle_collisions(self) -> None:
        self._collisions_enabled = not self._collisions_enabled
        self._apply_collision_mode()
        if self._collisions_enabled:
            # Push overlapping vehicles apart
            self._separate_overlapping_vehicles()
        self._show_toast(f"Kollisionen: {'AN' if self._collisions_enabled else 'AUS'}")

    def _separate_overlapping_vehicles(self) -> None:
        """Push overlapping vehicles apart when enabling collisions mid-race."""
        for i, a in enumerate(self.ai_vehicles):
            for b in self.ai_vehicles[i + 1:]:
                pa = a.physics.body.position
                pb = b.physics.body.position
                dist = pa.get_distance(pb)
                min_dist = (a.config.height_px + b.config.height_px) / 2.0 + 10.0
                if dist < min_dist and dist > 0.01:
                    direction = (pb - pa).normalized()
                    push = (min_dist - dist) / 2.0 + 5.0
                    a.physics.body.position = pa - direction * push
                    b.physics.body.position = pb + direction * push

    # ------------------------------------------------------------------
    # Toast notification
    # ------------------------------------------------------------------

    def _show_toast(self, text: str, duration: float = 2.5) -> None:
        self._toast_text = text
        self._toast_timer = duration

    # ------------------------------------------------------------------
    # AI ghost spawning (overrides RaceState: 5 car types, no collisions)
    # ------------------------------------------------------------------

    def _spawn_ai_vehicles(self, start_positions, kwargs: dict, human_count: int = 1) -> list:
        """Spawn all five car types stacked on slot 0 as non-colliding ghosts."""
        from src.entities.vehicle_factory import VehicleFactory

        if not start_positions:
            return []
        difficulty = get_difficulty(kwargs.get("difficulty", "hard"))
        slot = start_positions[0]
        vehicles = []
        for i, cfg_key in enumerate(_GHOST_KEYS):
            ai = VehicleFactory.create_ai_vehicle(
                config_key=cfg_key,
                vehicle_id=2 + i,
                start_pos=slot.pos,
                start_angle=math.radians(slot.angle),
                space=self.physics_world.space,
                track=self.track,
                difficulty=difficulty,
                color_primary=_GHOST_COLORS[i],
            )
            if ai:
                # Shared non-zero group → ghosts ignore each other, still hit walls.
                ai.physics.shape.filter = pymunk.ShapeFilter(group=1)
                vehicles.append(ai)
        return vehicles

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        for event in events:
            if event.type != pygame.KEYDOWN:
                continue
            k = event.key
            if k == pygame.K_ESCAPE:
                self.state_machine.zurueck()
                return
            elif k == pygame.K_p:
                self.paused = not self.paused
            elif k == pygame.K_o:
                self.paused = True
                self._step = True
            # Navigate the parameter list with the arrow keys only. The
            # rebindable driving keys are NOT used here so they stay free for
            # other actions (e.g. S = save, even when brake is bound to S).
            elif k == pygame.K_UP:
                self.sel_param = (self.sel_param - 1) % len(_PARAMS)
            elif k == pygame.K_DOWN:
                self.sel_param = (self.sel_param + 1) % len(_PARAMS)
            elif k in (pygame.K_LEFT, pygame.K_a, kb.get("left")):
                self._adjust_param(-1)
            elif k in (pygame.K_RIGHT, pygame.K_d, kb.get("right")):
                self._adjust_param(+1)
            elif k == pygame.K_RETURN:
                self._adjust_param(0, toggle=True)
            elif k == pygame.K_TAB:
                self.cam_index = (self.cam_index + 1) % max(1, len(self.ai_vehicles))
            elif k == pygame.K_r:
                self._respawn()
            elif k == pygame.K_b:
                if not self.paused:
                    self._show_toast("Preset-Wechsel nur im Pause-Modus (P) möglich!")
                else:
                    self._cycle_preset()
            elif k == pygame.K_s:
                if not self.paused:
                    self._show_toast("Speichern nur im Pause-Modus (P) möglich!")
                else:
                    self._save_settings()
            elif k == pygame.K_c:
                self._toggle_collisions()
            elif k == pygame.K_F1:
                self.show_help = not self.show_help
            elif k == pygame.K_F2:
                self.show_waypoints = not self.show_waypoints
            elif k == pygame.K_F3:
                self.show_line = not self.show_line
            elif k == pygame.K_F4:
                self.show_sensors = not self.show_sensors
            elif k == pygame.K_F5:
                self.show_telemetry = not self.show_telemetry

    def _adjust_param(self, direction: int, toggle: bool = False) -> None:
        if self.live is None:
            return
        if not self.paused:
            self._show_toast("Nur im Pause-Modus (Taste P) änderbar!")
            return
        attr, _lbl, lo, hi, step, kind, group = _PARAMS[self.sel_param]
        if kind == "bool":
            if toggle:
                setattr(self.live, attr, not getattr(self.live, attr))
            return
        if toggle:
            return
        val = getattr(self.live, attr) + direction * step
        val = max(lo, min(hi, round(val, 4)))
        setattr(self.live, attr, val)

        # Sync solver margin with the live value
        if attr == "wall_margin":
            self._solver_margin = val

        # Recompute if this parameter affects the line or speed profile
        if group in ("line", "speed"):
            self._compute_solver_line()

    def _cycle_preset(self) -> None:
        self.difficulty_index = (self.difficulty_index + 1) % len(self.difficulty_keys)
        key = self.difficulty_keys[self.difficulty_index]
        saved = load_difficulty(key)
        if self.live:
            self.live.load_from(saved if saved else get_difficulty(key))
            self._solver_margin = self.live.wall_margin
        self._compute_solver_line()
        self._show_toast(f"Preset: {key.upper()}")

    def _save_settings(self) -> None:
        if self.live is None:
            return
        key = self.difficulty_keys[self.difficulty_index]
        save_difficulty(key, self.live)
        self._show_toast(f"Gespeichert: {key}.json")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        self._apply_live()
        if self._toast_timer > 0.0:
            self._toast_timer -= dt
        if self.paused and not self._step:
            self._aim_camera(dt)
            return
        step_dt = (1.0 / 60.0) if self._step else dt
        self._step = False
        super().update(step_dt)
        self._aim_camera(dt)
        self._feed_hud()

    def _apply_live(self) -> None:
        """Push live params onto every AI controller (read each frame)."""
        if self.live is None:
            return
        for ai in self.ai_vehicles:
            c = ai.controller
            c.difficulty = self.live

    def _feed_hud(self) -> None:
        if not (self.hud and self.race_manager):
            return
        target = self._camera_target()
        if not target:
            return
        tracker = self.race_manager.lap_trackers[target.id]
        self.hud.update(
            speed=target.signed_speed, fps=self._fps_filtered, rpm=target.rpm,
            redline_rpm=target.engine.redline_rpm, shift_up_rpm=target.engine.shift_up_rpm,
            gear=target.gear, is_drifting=target.is_drifting,
            current_lap=tracker.current_lap, total_laps=self.race_manager.total_laps,
            current_lap_time=tracker.current_lap_time, best_lap_time=tracker.best_lap_time,
            last_lap_time=tracker.last_lap_time,
            position=self.race_manager.get_position(target.id),
            total_vehicles=len(self.race_manager.vehicles),
            countdown_timer=None, split_info=tracker.last_split_info, race_finished=False,
            sector_diff=tracker.last_sector_diff,
        )

    def _camera_target(self):
        if not self.ai_vehicles:
            return None
        return self.ai_vehicles[self.cam_index % len(self.ai_vehicles)]

    def _aim_camera(self, dt: float) -> None:
        target = self._camera_target()
        if target and self.camera:
            self.camera.follow(to_pygame(target.position, SCREEN_HEIGHT), max(dt, 1e-3))

    def _respawn(self) -> None:
        starts = self.track.get_start_positions() if self.track else []
        if not starts:
            return
        sp = starts[0]
        for car in self.ai_vehicles:
            if car is None:
                continue
            body = car.physics.body
            body.position = sp.pos
            body.angle = math.radians(sp.angle)
            body.velocity = (0.0, 0.0)
            body.angular_velocity = 0.0
            car.is_touching_wall = False
            ctrl = getattr(car, "controller", None)
            if ctrl is not None:
                ctrl.target_wp_index = self.track.get_nearest_waypoint_index(sp.pos)
                # These names must match AIController's real fields — the old
                # underscore-prefixed ones silently created new attributes and
                # never cleared an active recovery on respawn.
                ctrl._no_progress_timer = 0.0
                ctrl._progress_wp = -1
                ctrl.recovery_timer = 0.0
                ctrl._recovery_attempts = 0
                ctrl._launch_dist = 0.0

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _w2s(self, p: tuple[float, float]) -> tuple[int, int]:
        """World (pymunk y-up) → screen, matching the vehicle/track pipeline."""
        off = self.camera.offset
        sx, sy = to_pygame(p, SCREEN_HEIGHT)
        return (int(sx + off.x), int(sy + off.y))

    def render(self, screen: pygame.Surface) -> None:
        super().render(screen)  # track, cars, HUD
        if self.show_waypoints:
            self._draw_waypoints(screen)
        if self.show_line:
            self._draw_solver_line(screen)
        self._draw_ai_markers(screen)
        self._draw_param_panel(screen)
        if self.show_telemetry:
            self._draw_telemetry(screen)
        self._draw_status_bar(screen)
        if self._toast_timer > 0.0:
            self._draw_toast(screen)
        if self.paused:
            self._draw_paused(screen)
        if self.show_help:
            self._draw_help(screen)

    def _draw_waypoints(self, screen: pygame.Surface) -> None:
        if not self.track:
            return
        for wp in self.track.waypoints:
            pygame.draw.circle(screen, (90, 90, 110), self._w2s((wp.x, wp.y)), 2)

    def _draw_solver_line(self, screen: pygame.Surface) -> None:
        """Draw the individual vehicle racing lines, colored by their speed profiles."""
        if not self.ai_vehicles:
            return

        target = self._camera_target()

        # Draw all individual lines
        for ai in self.ai_vehicles:
            line = ai.controller.racing_line
            if not line or not line.points or len(line.points) < 2:
                continue

            pts = [self._w2s(p) for p in line.points]
            prof = line.speeds

            is_target = (ai is target)
            width = 3 if is_target else 1
            alpha_mult = 1.0 if is_target else 0.55

            if prof and len(prof) == len(pts):
                vmax = getattr(ai.config, "max_speed", 260.0)
                n = len(pts)
                for i in range(n):
                    ratio = max(0.0, min(1.0, (prof[i] - 60.0) / max(1.0, vmax - 60.0)))
                    # Fade colors for non-focused vehicles
                    r = int(255 * (1.0 - ratio) * alpha_mult)
                    g = int((60 + 180 * ratio) * alpha_mult)
                    b = int((60 + 50 * ratio) * alpha_mult)
                    pygame.draw.line(screen, (r, g, b), pts[i], pts[(i + 1) % n], width)
            else:
                col = (60, 255, 90) if is_target else (100, 180, 120)
                pygame.draw.lines(screen, col, True, pts, width)

        # Show telemetry details for the active camera target at the top left
        if target and target.controller.racing_line:
            line = target.controller.racing_line
            curvatures = [abs(line.curvature_at(i)) for i in range(line.n)]
            max_c = max(curvatures) if curvatures else 0.0
            minr = (1.0 / max_c) if max_c > 0 else 0.0
            margin = self._solver_margin + max(0.0, (target.config.height_px - 48.0) * 0.5)
            
            # Reconstruct the same grip margin bonus from the optimizer to show accurate margins
            a_lat_max = getattr(target.config, "grip", 0.8) * 380.0 * (self.live.grip_usage if self.live else 0.70)
            grip_ratio = min(1.0, a_lat_max / 270.0)
            grip_margin_bonus = (1.0 - grip_ratio) * 4.0
            adjusted_margin = margin + grip_margin_bonus

            info = (f"Fokus: {target.config.name} | R_min {minr:.0f}px | "
                    f"Marge {adjusted_margin:.1f}px | rot=langsam grün=schnell")
        else:
            info = "Keine Fahrzeug-Ideallinien vorhanden"

        # Draw to the right of the param panel so it never overlaps the HUD
        # (FPS) line at the top-left corner.
        surf = self._fonts["small"].render(info, True, (200, 230, 200))
        screen.blit(surf, (378, 62))

    def _draw_ai_markers(self, screen: pygame.Surface) -> None:
        for ai in self.ai_vehicles:
            c = ai.controller
            tgt = self._w2s(c.dbg_look)
            pygame.draw.circle(screen, (255, 180, 0), tgt, 5, 1)
            pygame.draw.line(screen, (255, 180, 0), self._w2s(ai.position), tgt, 1)
            if self.show_sensors:
                self._draw_whiskers(screen, ai)

    def _draw_whiskers(self, screen: pygame.Surface, ai) -> None:
        c = ai.controller
        pos = ai.position
        angle = ai.physics.body.angle
        reach = c.WHISKER_BASE + ai.speed * 0.33
        front = ai.config.height_px / 2.0 + 2.0
        origin = (pos[0] + math.cos(angle) * front, pos[1] + math.sin(angle) * front)
        for da in (c.WHISKER_ANGLE, -c.WHISKER_ANGLE):
            a = angle + da
            end = (origin[0] + math.cos(a) * reach, origin[1] + math.sin(a) * reach)
            hit = c._raycast_wall_distance(origin, end)
            color = (255, 60, 60) if hit is not None else (60, 200, 60)
            pygame.draw.line(screen, color, self._w2s(origin), self._w2s(end), 1)

    def _panel(self, screen, rect, alpha=185) -> None:
        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        surf.fill((10, 12, 22, alpha))
        screen.blit(surf, rect.topleft)
        pygame.draw.rect(screen, (60, 80, 120), rect, 1)

    def _render_wrapped_text(self, screen: pygame.Surface, text: str, x: int, y: int, max_w: int, font: pygame.font.Font, color: tuple[int, int, int]) -> int:
        words = text.split(' ')
        lines = []
        current_line = []
        for word in words:
            test_line = ' '.join(current_line + [word])
            if font.size(test_line)[0] < max_w:
                current_line.append(word)
            else:
                lines.append(' '.join(current_line))
                current_line = [word]
        if current_line:
            lines.append(' '.join(current_line))
        
        for line in lines:
            surf = font.render(line, True, color)
            screen.blit(surf, (x, y))
            y += font.get_linesize()
        return y

    def _draw_param_panel(self, screen: pygame.Surface) -> None:
        if self.live is None:
            return
        panel_h = 96 + len(_PARAMS) * 28 + 24
        rect = pygame.Rect(20, 90, 340, panel_h)
        self._panel(screen, rect)
        x, y = rect.x + 16, rect.y + 14
        preset = self.difficulty_keys[self.difficulty_index].upper()
        collision_tag = "  [Koll: AN]" if self._collisions_enabled else ""
        screen.blit(self._fonts["title"].render("KI-LABOR", True, (255, 180, 0)), (x, y))
        screen.blit(self._fonts["small"].render(f"Preset (B): {preset}{collision_tag}", True, (170, 175, 190)),
                    (x, y + 44))
        status_text = "PAUSIERT - Bearbeitung erlaubt" if self.paused else "AKTIV - Pause (P) zum Bearbeiten"
        status_color = (100, 255, 100) if self.paused else (230, 90, 90)
        screen.blit(self._fonts["small"].render(status_text, True, status_color), (x, y + 66))
        
        # Track mouse hover
        mx, my = display.mouse_pos()
        hovered_idx = -1
        start_y = rect.y + 14 + 92
        item_h = 28
        if rect.x <= mx <= rect.right:
            if start_y <= my < start_y + len(_PARAMS) * item_h:
                hovered_idx = int((my - start_y) // item_h)

        # Fallback to keyboard selection if mouse is not hovering the parameters list
        active_idx = hovered_idx if hovered_idx != -1 else self.sel_param

        y = start_y
        for i, (attr, lbl, lo, hi, step, kind, _grp) in enumerate(_PARAMS):
            sel = (i == active_idx)
            val = getattr(self.live, attr)
            if kind == "bool":
                vs = "AN" if val else "AUS"
            else:
                vs = f"{val:.3f}" if step < 0.01 else (f"{val:.2f}" if step < 1 else f"{val:.0f}")
            
            # Highlight hovered/selected item
            col = (255, 220, 120) if sel else (200, 205, 215)
            marker = f"{theme.ZEIGER} " if i == self.sel_param else "  "  # Keyboard pointer stays on sel_param
            if hovered_idx == i:
                col = (255, 180, 0)  # Stronger highlight on mouse hover
            
            screen.blit(self._fonts["body"].render(f"{marker}{lbl}", True, col), (x, y))
            vsurf = self._fonts["body"].render(vs, True, col)
            screen.blit(vsurf, vsurf.get_rect(topright=(rect.right - 16, y)))
            y += item_h

        # Draw Tooltip Panel to the right of the parameter panel
        if 0 <= active_idx < len(_PARAMS):
            attr, lbl, lo, hi, step, kind, _grp = _PARAMS[active_idx]
            info = _DESCRIPTIONS.get(attr)
            if info:
                # Aligned to top of the Ki-Labor panel
                tip_rect = pygame.Rect(370, 90, 420, 260)
                self._panel(screen, tip_rect, alpha=210)
                
                # Title
                title_surf = self._fonts["body"].render(lbl.upper(), True, (255, 180, 0))
                screen.blit(title_surf, (tip_rect.x + 16, tip_rect.y + 14))
                
                # Range
                range_str = f"Bereich: {lo} bis {hi}" if kind != "bool" else "Bereich: AN / AUS"
                range_surf = self._fonts["small"].render(range_str, True, (140, 170, 200))
                screen.blit(range_surf, (tip_rect.x + 16, tip_rect.y + 38))
                
                # Divider line
                pygame.draw.line(screen, (60, 80, 120), (tip_rect.x + 10, tip_rect.y + 58), (tip_rect.right - 10, tip_rect.y + 58), 1)
                
                # Description
                y_text = tip_rect.y + 68
                y_text = self._render_wrapped_text(screen, info["desc"], tip_rect.x + 16, y_text, 388, self._fonts["small"], (210, 215, 225))
                y_text += 10
                
                # Low/High effects
                y_text = self._render_wrapped_text(screen, info["low"], tip_rect.x + 16, y_text, 388, self._fonts["small"], (160, 190, 170))
                y_text += 6
                self._render_wrapped_text(screen, info["high"], tip_rect.x + 16, y_text, 388, self._fonts["small"], (190, 160, 160))

    def _draw_telemetry(self, screen: pygame.Surface) -> None:
        target = self._camera_target()
        if target is None:
            return
        rect = pygame.Rect(SCREEN_WIDTH - 360, 220, 340, 300)
        self._panel(screen, rect)
        x, y = rect.x + 16, rect.y + 14
        screen.blit(self._fonts["title"].render(f"KI #{target.id}", True, (0, 230, 255)), (x, y))
        y += 40
        lines = [
            f"Typ:    {target.config.visual_type}",
            f"Speed:  {target.speed:6.1f} px/s",
            f"Gas:    {target.throttle:+.2f}",
            f"Bremse: {target.brake_input:.2f}",
            f"Lenkung:{target.steer_input:+.2f}",
        ]
        ctrl = getattr(target, "controller", None)
        if ctrl is not None:
            lines += [
                f"Zustand: {ctrl.dbg_state}",
                f"WP-Index: {ctrl.target_wp_index}",
                f"Kurve: {ctrl.dbg_curve:.2f} rad",
                f"Wand: {'JA' if target.is_touching_wall else 'nein'}",
                f"Auto vorn: {'JA' if ctrl.dbg_car_ahead else 'nein'}",
            ]
        for ln in lines:
            screen.blit(self._fonts["body"].render(ln, True, (210, 215, 225)), (x, y))
            y += 27

    def _draw_status_bar(self, screen: pygame.Surface) -> None:
        rect = pygame.Rect(0, SCREEN_HEIGHT - 40, SCREEN_WIDTH, 40)
        self._panel(screen, rect, alpha=200)
        tgt = self._camera_target()
        cam = f"KI #{tgt.id} ({tgt.config.visual_type.upper()})" if tgt else "Keine"
        left = (f"F1 Hilfe | TAB Kamera: {cam} | P Pause | O Step | "
                f"R Reset | B Preset | S Speichern | C Koll. | ESC Menü")
        screen.blit(self._fonts["small"].render(left, True, (180, 185, 200)),
                    (16, rect.y + 10))

    def _draw_toast(self, screen: pygame.Surface) -> None:
        """Brief notification shown after save/toggle actions."""
        alpha = min(255, int(self._toast_timer * 255 / 0.5))
        surf = self._fonts["title"].render(self._toast_text, True, (120, 255, 120))
        surf.set_alpha(alpha)
        r = surf.get_rect(center=(SCREEN_WIDTH // 2, 140))
        bg = pygame.Surface((r.width + 40, r.height + 16), pygame.SRCALPHA)
        bg.fill((10, 12, 22, min(200, alpha)))
        screen.blit(bg, (r.x - 20, r.y - 8))
        screen.blit(surf, r)

    def _draw_paused(self, screen: pygame.Surface) -> None:
        s = self._fonts["big"].render("|| PAUSE", True, (255, 200, 60))
        screen.blit(s, s.get_rect(center=(SCREEN_WIDTH // 2, 70)))

    def _draw_help(self, screen: pygame.Surface) -> None:
        rect = pygame.Rect(SCREEN_WIDTH // 2 - 320, 160, 640, 560)
        self._panel(screen, rect, alpha=235)
        x, y = rect.x + 30, rect.y + 24
        screen.blit(self._fonts["title"].render("KI-LABOR — STEUERUNG", True, (255, 180, 0)), (x, y))
        y += 50
        rows = [
            ("↑ / ↓", "Parameter wählen"),
            ("← / →", "Parameter ändern (halten = schnell)"),
            ("ENTER", "Boolean umschalten"),
            ("B", "Schwierigkeits-Preset wechseln"),
            ("S", "Einstellungen speichern (JSON)"),
            ("C", "Fahrzeug-Kollisionen an/aus"),
            ("P", "Pause an/aus"),
            ("O", "Einzelbild vor (im Pausenmodus)"),
            ("TAB", "Kamera durch Fahrzeuge wechseln"),
            ("R", "Alle Autos ans Grid zurücksetzen"),
            ("F2", "Waypoints ein/aus"),
            ("F3", "Ideallinie ein/aus"),
            ("F4", "Wand-Sensoren ein/aus"),
            ("F5", "Telemetrie ein/aus"),
            ("F1", "Diese Hilfe"),
            ("ESC", "Zurück zum Menü"),
        ]
        for keys, desc in rows:
            screen.blit(self._fonts["body"].render(keys, True, (255, 220, 120)), (x, y))
            screen.blit(self._fonts["body"].render(desc, True, (210, 215, 225)), (x + 130, y))
            y += 29
