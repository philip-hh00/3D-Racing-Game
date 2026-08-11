"""AIController – decision logic for an AI-controlled vehicle to follow the racing line exactly.

Simplifies steering and speed control to pure geometric pursuit, discarding
complex regulations, whiskers, stuck recovery, and vehicle-ahead avoidance.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.ai.difficulty import DifficultyConfig
    from src.entities.vehicle import Vehicle
    from src.track.track import Track


def normalize_angle(angle: float) -> float:
    """Wrap *angle* into the range ``(-pi, pi]``."""
    return math.atan2(math.sin(angle), math.cos(angle))


# How long the target waypoint index may stay put before we call it "stuck".
# 1.5s survives tight hairpins (where advancing a single waypoint can take a
# moment) while still catching a car pinned against a wall quickly.
STUCK_SECONDS: float = 1.5

# Recovery duration grows with each failed attempt so a car wedged at an
# awkward angle gets more room to back out instead of repeating the same
# short reverse that put it there.
RECOVERY_BASE_SECONDS: float = 1.5
RECOVERY_MAX_SECONDS: float = 4.0

# Grid lane hold: right after the start, every AI keeps the lateral offset of
# its own grid slot instead of all diving to the centre line at once (which
# jams the pack and blocks a stationary player). The offset is held fully for
# GRID_HOLD_SECONDS, then blended out over GRID_FADE_SECONDS. Only engaged when
# the car begins near-stationary (on the grid) — a mid-race AI takeover starts
# already moving and must not snap to a lane.
GRID_HOLD_SECONDS: float = 3.5
GRID_FADE_SECONDS: float = 1.5
GRID_START_SPEED: float = 20.0   # px/s; above this, assume not a grid start


class AIController:
    """A simple geometric path-following controller that follows the racing line exactly."""

    # Dummy constants to prevent AttributeError in dev_state.py
    WHISKER_BASE: float = 55.0
    WHISKER_ANGLE: float = math.radians(20.0)

    #: Ueber diesem Tempofehler (px/s) gibt die KI Gas wie eh und je; darunter
    #: wird es zum Nullpunkt hin ausgeblendet. Bewusst schmal — es soll nur die
    #: Sprungstelle glaetten und nicht die Fahrweise aendern. 6 px/s sind rund
    #: 1,7 km/h; wer so nah am Zieltempo liegt, faehrt ohnehin konstant.
    GAS_AUSBLENDBAND: float = 6.0

    def __init__(self, vehicle: Vehicle, track: Track, difficulty: DifficultyConfig) -> None:
        self.vehicle = vehicle
        self.track = track
        self.difficulty = difficulty

        self.waypoints = track.waypoints
        self.num_wp = len(self.waypoints)

        # Determine track winding: CCW (positive area) -> outward normal is LEFT normal
        # CW (negative area) -> outward normal is RIGHT normal
        centerline = getattr(track, "centerline", None) or []
        if len(centerline) >= 3:
            area = 0.0
            for i in range(len(centerline)):
                x1, y1 = centerline[i]
                x2, y2 = centerline[(i + 1) % len(centerline)]
                area += x1 * y2 - x2 * y1
            self._track_ccw = area > 0  # True = CCW, False = CW
        else:
            self._track_ccw = True  # Default assumption

        # Track nearest waypoint index
        start = self._position()
        self.target_wp_index = track.get_nearest_waypoint_index(start)

        # Stuck & recovery timers
        self.recovery_timer: float = 0.0

        # Grid lane hold (measured on the first active frame; see compute_inputs).
        self._start_timer: float = 0.0        # >0 while the grid lane is held/fading
        self._start_offset: float = 0.0       # lateral offset of our grid slot
        self._start_measured: bool = False

        # Progress-based stuck detection: tracks the last waypoint index we
        # actually reached, not throttle/speed (which stay low while braking
        # or coasting even when the car isn't stuck at all).
        self._progress_wp: int = -1
        self._no_progress_timer: float = 0.0
        self._recovery_attempts: int = 0
        self._recovery_steer_sign: float = 1.0

        # Fields required by dev_state.py and other modules
        self.racing_line = None
        self.rubber_band: float = 0.0
        self._wander_amp: float = 0.0

        # Extra global speed factor on top of difficulty.speed_scale
        # (e.g. set to 0.5 for a cool-down lap after the race is finished).
        self.speed_multiplier: float = 1.0

        # Snapshot debug fields read by the dev state UI
        self.dbg_look: tuple[float, float] = start
        self.dbg_curve: float = 0.0
        self.dbg_state: str = "drive"
        self.dbg_car_ahead: bool = False
        self.opponents: list = []

    def _position(self) -> tuple[float, float]:
        pos = self.vehicle.physics.body.position
        return pos.x, pos.y

    def _raycast_wall_distance(self, start: tuple[float, float], end: tuple[float, float]) -> float | None:
        """Stub method for the dev state sensor visualization."""
        return None

    def _walk(self, start_idx: int, distance: float) -> tuple[int, tuple[float, float]]:
        """Walk forward along waypoints until distance is covered. Returns (idx, point)."""
        idx = start_idx
        acc = 0.0
        n = self.num_wp
        w = self.waypoints
        steps = 0
        while acc < distance and steps < 4 * n:
            p1 = w[idx % n].pos
            p2 = w[(idx + 1) % n].pos
            acc += math.dist(p1, p2)
            idx += 1
            steps += 1
        idx = idx % n
        return idx, w[idx].pos

    def _advance_waypoint(self, pos: tuple[float, float]) -> None:
        """Find the nearest waypoint within a forward search window to update target_wp_index."""
        best = self.target_wp_index
        best_d = math.dist(pos, self.waypoints[best].pos)
        for offset in range(1, 25):
            idx = (self.target_wp_index + offset) % self.num_wp
            d = math.dist(pos, self.waypoints[idx].pos)
            if d < best_d:
                best_d = d
                best = idx
        self.target_wp_index = best

    def _apply_grid_lane_hold(self, look: tuple[float, float],
                              pos: tuple[float, float], v: float,
                              dt: float) -> tuple[float, float]:
        """Hold the AI's own starting lane for the first seconds of the race.

        On the first active frame the car's lateral offset from the centre line
        is measured (its grid slot's lane) and held; it is applied at full
        strength for GRID_HOLD_SECONDS, then blended to zero over
        GRID_FADE_SECONDS. Only engages from a near-stationary grid start, so a
        mid-race takeover never snaps sideways.
        """
        if not self._start_measured:
            self._start_measured = True
            if v < GRID_START_SPEED:
                normal = self._get_outward_normal(self.target_wp_index)
                wp = self.waypoints[self.target_wp_index % self.num_wp].pos
                self._start_offset = ((pos[0] - wp[0]) * normal[0]
                                      + (pos[1] - wp[1]) * normal[1])
                self._start_timer = GRID_HOLD_SECONDS + GRID_FADE_SECONDS

        if self._start_timer <= 0.0:
            return look
        self._start_timer -= dt
        fade = (1.0 if self._start_timer > GRID_FADE_SECONDS
                else max(0.0, self._start_timer / GRID_FADE_SECONDS))
        normal = self._get_outward_normal(self.target_wp_index)
        shift = self._start_offset * fade
        return (look[0] + normal[0] * shift, look[1] + normal[1] * shift)

    def _get_outward_normal(self, wp_index: int) -> tuple[float, float]:
        """Get the outward-pointing track normal at the given waypoint index.
        
        For CCW tracks, left normal points outward.
        For CW tracks, right normal points outward.
        """
        wp_curr = self.waypoints[wp_index].pos
        wp_next = self.waypoints[(wp_index + 1) % self.num_wp].pos
        dx = wp_next[0] - wp_curr[0]
        dy = wp_next[1] - wp_curr[1]
        length = math.hypot(dx, dy)
        if length <= 0.1:
            return (0.0, 1.0)
        # Left normal (-dy, dx) points outward for CCW, inward for CW
        if self._track_ccw:
            return (-dy / length, dx / length)
        else:
            return (dy / length, -dx / length)  # Right normal for CW

    def compute_inputs(self, dt: float) -> tuple[float, float, float]:
        """Return (throttle, brake, steer) to trace the racing line exactly."""
        pos = self._position()
        angle = self.vehicle.physics.body.angle
        v = self.vehicle.speed

        # Advance target index tracker
        self._advance_waypoint(pos)

        # 1. Target Point: lookahead on the racing line
        look_ahead = 70.0 + v * 0.50
        idx, _ = self._walk(self.target_wp_index, look_ahead)

        # Get exact 2D point from SolvedRacingLine if loaded, otherwise centerline
        if self.racing_line is not None and self.racing_line.points:
            look = self.racing_line.points[idx % self.racing_line.n]
        else:
            look = self.waypoints[idx % self.num_wp].pos

        # Recovery state: if we triggered reversing timer, back up
        if self.recovery_timer > 0.0:
            self.recovery_timer -= dt
            # Brake acts as reverse gear when vehicle is stationary or moving backward
            throttle = 0.0
            brake = 1.0
            
            # Steer opposite to target direction to back up in a clean arc
            desired = math.atan2(look[1] - pos[1], look[0] - pos[0])
            diff = normalize_angle(desired - angle)
            target_steer_angle = -diff * (1.6 / (1.0 + (v / 100.0)))
            target_steer_angle = max(-0.60, min(0.60, target_steer_angle))
            target_steer_angle *= self._recovery_steer_sign
            steer_err = target_steer_angle - self.vehicle.physics.steer_angle
            steer = max(-1.0, min(1.0, steer_err * 12.0))
            
            self.dbg_state = "reverse"
            self.dbg_look = look
            return throttle, brake, steer

        # 1b. Grid lane hold — shift the target point onto our own starting lane
        # for the first moments of the race so the field pulls away in parallel
        # instead of all converging on the centre line. Applied to the BASE look
        # before the overtaking/avoidance logic below, so a car can still steer
        # wide around a slow or stopped vehicle on top of holding its lane.
        look = self._apply_grid_lane_hold(look, pos, v, dt)

        # 2. Interactive AI Behaviors (Overtaking, Drafting, Defensive Blocking)
        other_cars = [car for car in self.opponents if car != self.vehicle]
        closest_car = None
        closest_dist = 999.0
        has_car_ahead = False

        overtake_dist = getattr(self.difficulty, 'overtake_dist', 90.0)
        brake_dist = getattr(self.difficulty, 'brake_dist', 65.0)
        draft_dist = getattr(self.difficulty, 'draft_dist', 180.0)
        block_dist = getattr(self.difficulty, 'block_dist', 120.0)
        
        # Look for vehicles ahead
        for car in other_cars:
            c_pos = car.position
            d_px = math.dist(pos, c_pos)
            if d_px < max(overtake_dist, draft_dist) + 40.0:
                car_wp = self.track.get_nearest_waypoint_index(c_pos)
                wp_diff = (car_wp - self.target_wp_index) % self.num_wp
                if (wp_diff < 25 and wp_diff > 0) or (wp_diff == 0 and d_px > 5.0):
                    to_car = (c_pos[0] - pos[0], c_pos[1] - pos[1])
                    forward = (math.cos(angle), math.sin(angle))
                    proj = to_car[0] * forward[0] + to_car[1] * forward[1]
                    if proj > 0.0:
                        if d_px < closest_dist:
                            closest_dist = d_px
                            closest_car = car
                            has_car_ahead = True

        self.dbg_car_ahead = has_car_ahead

        # Initial speed limit config
        if self.racing_line is not None:
            la_idx, _ = self._walk(self.target_wp_index, 0.15 * look_ahead)
            target_speed = self.racing_line.speed_at(la_idx)
        else:
            target_speed = 120.0

        # Apply global speed scale from difficulty config + runtime multiplier
        target_speed *= getattr(self.difficulty, 'speed_scale', 1.0)
        target_speed *= self.speed_multiplier

        # Execute interactive behaviors based on distances
        if has_car_ahead and closest_car is not None:
            to_car = (closest_car.position[0] - pos[0], closest_car.position[1] - pos[1])
            forward = (math.cos(angle), math.sin(angle))
            lat_dist = abs(-to_car[0] * forward[1] + to_car[1] * forward[0])
            
            # A. Overtaking & Collision Avoidance (Steering Offset)
            if closest_dist <= overtake_dist:
                # Find track outward normal at current index
                normal = self._get_outward_normal(self.target_wp_index)
                vec_to_opponent = (closest_car.position[0] - pos[0], closest_car.position[1] - pos[1])
                opponent_offset = vec_to_opponent[0] * normal[0] + vec_to_opponent[1] * normal[1]
                
                # Nudge target point in opposite direction
                nudge_side = -1.0 if opponent_offset > 0.0 else 1.0
                nudge_amt = nudge_side * 70.0
                look = (look[0] + normal[0] * nudge_amt, look[1] + normal[1] * nudge_amt)
                
                # Collision Avoidance Speed Adjustment
                if closest_car.speed < 20.0:
                    # Vehicle ahead is stationary/idling (e.g. human player at start line):
                    # Do NOT stop! Steer wide to bypass them.
                    nudge_amt = nudge_side * 95.0
                    look = (look[0] + normal[0] * nudge_amt, look[1] + normal[1] * nudge_amt)
                    target_speed = max(target_speed * 0.70, 70.0)
                elif closest_dist < brake_dist:
                    # Dangerous close to a moving vehicle: match speed
                    target_speed = min(target_speed, max(closest_car.speed * 0.90, 40.0))
                elif lat_dist < 32.0:
                    # Still in our lane: slow down slightly until we clear them laterally
                    target_speed = min(target_speed, max(closest_car.speed * 0.95, 50.0))

                    
            # B. Slipstream Drafting
            elif overtake_dist < closest_dist <= draft_dist:
                # Blend look target point slightly towards opponent to slipstream behind them
                look = (look[0] * 0.70 + closest_car.position[0] * 0.30, look[1] * 0.70 + closest_car.position[1] * 0.30)

        # C. Defensive Blocking (for vehicles behind us)
        else:
            closest_behind_dist = 999.0
            car_behind = None
            has_car_behind = False
            
            for car in other_cars:
                c_pos = car.position
                d_px = math.dist(pos, c_pos)
                if d_px < block_dist + 30.0:
                    car_wp = self.track.get_nearest_waypoint_index(c_pos)
                    wp_diff = (self.target_wp_index - car_wp) % self.num_wp
                    if wp_diff < 15 and wp_diff > 0:
                        to_car = (c_pos[0] - pos[0], c_pos[1] - pos[1])
                        forward = (math.cos(angle), math.sin(angle))
                        proj = to_car[0] * forward[0] + to_car[1] * forward[1]
                        if proj < 0.0:  # Behind
                            if d_px < closest_behind_dist:
                                closest_behind_dist = d_px
                                car_behind = car
                                has_car_behind = True
                                
            if has_car_behind and car_behind is not None and closest_behind_dist < block_dist:
                normal = self._get_outward_normal(self.target_wp_index)
                to_behind = (car_behind.position[0] - pos[0], car_behind.position[1] - pos[1])
                normal_left = (-math.sin(angle), math.cos(angle))
                behind_offset = to_behind[0] * normal_left[0] + to_behind[1] * normal_left[1]
                if behind_offset > 15.0:
                    # Block on the left side (towards outward normal if behind is on left)
                    look = (look[0] + normal[0] * 30.0, look[1] + normal[1] * 30.0)
                elif behind_offset < -15.0:
                    # Block on the right side
                    look = (look[0] - normal[0] * 30.0, look[1] - normal[1] * 30.0)

        self.dbg_look = look

        # 3. Closed-Loop Steering angle feedback controller
        desired = math.atan2(look[1] - pos[1], look[0] - pos[0])
        diff = normalize_angle(desired - angle)
        
        target_steer_angle = diff * (1.6 / (1.0 + (v / 100.0)))
        target_steer_angle = max(-0.60, min(0.60, target_steer_angle))
        
        steer_err = target_steer_angle - self.vehicle.physics.steer_angle
        steer = max(-1.0, min(1.0, steer_err * 12.0))

        # 4. Proportional speed controller with a deadband to prevent oscillations
        speed_err = target_speed - v
        max_throttle = getattr(self.difficulty, 'max_throttle', 1.0)
        
        if speed_err > 0.0:
            throttle = min(max_throttle, 0.60 + speed_err * 0.05)
            # Weich ausblenden statt abzuschneiden (gemeldet 05.08.2026:
            # „Nachdem man die Ziellinie überquert hat spielt die Drehzahl etwas
            # verrückt").
            #
            # Ohne diese Zeile fiel das Gas beim Nulldurchgang von 0,60 auf 0 —
            # es gab keinen Wert dazwischen. Ein Auto, das genau auf seinem
            # Zieltempo liegt, wechselt damit in jedem Bild zwischen kräftigem
            # Gas und gar keinem, und die Drehzahl (und mit ihr der Motorklang)
            # springt mit. Im Rennen faellt das kaum auf: dort beschleunigt die
            # KI aus Kurven heraus oder bremst, liegt also selten genau auf dem
            # Ziel. Nach dem Ziel dagegen setzt ``speed_multiplier = 0.5`` ein
            # niedriges, konstantes Ziel auf freier Strecke — das Auto liegt
            # dauerhaft genau darauf, und das Pendeln laeuft ununterbrochen.
            #
            # Oberhalb von AUSBLENDBAND bleibt alles wie vorher, also im
            # gesamten Bereich, in dem tatsaechlich gefahren wird.
            if speed_err < self.GAS_AUSBLENDBAND:
                throttle *= speed_err / self.GAS_AUSBLENDBAND
            brake = 0.0
            self.dbg_state = "drive"
        elif speed_err >= -3.0:
            throttle = 0.0
            brake = 0.0
            self.dbg_state = "coast"
        else:
            throttle = 0.0
            brake = min(1.0, (-speed_err - 3.0) * 0.15)
            self.dbg_state = "brake"

        # Stuck detection: measure actual progress along the track (the
        # target waypoint index), not throttle/speed. A pushed or wedged car
        # can sit at low speed with low throttle (coasting/braking) and never
        # trip a throttle-based check, or slide along a wall while throttle
        # stays high without ever advancing a waypoint.
        # _progress_wp is a high-water mark, not "last seen": a car wedged
        # between two waypoints can flip back and forth, and counting every
        # change as progress would reset the timer forever. Only a step
        # FORWARD counts; the modulo makes the wrap at the finish line a
        # normal forward step, while a backward flip lands near num_wp and is
        # rejected by the half-lap window.
        forward = False
        if self.num_wp:
            if self._progress_wp < 0:
                forward = True
            else:
                delta = (self.target_wp_index - self._progress_wp) % self.num_wp
                forward = 0 < delta <= max(1, self.num_wp // 2)

        if forward:
            self._progress_wp = self.target_wp_index
            self._no_progress_timer = 0.0
            self._recovery_attempts = 0
        else:
            self._no_progress_timer += dt

        if self._no_progress_timer > STUCK_SECONDS:
            self._recovery_attempts += 1
            if self._recovery_attempts >= 3 and self.num_wp > 0:
                # Hard unstick: reposition car towards track centerline facing forward
                target_pos = self.waypoints[self.target_wp_index].pos
                next_pos = self.waypoints[(self.target_wp_index + 1) % self.num_wp].pos
                desired_angle = math.atan2(next_pos[1] - target_pos[1], next_pos[0] - target_pos[0])
                body = self.vehicle.physics.body
                body.position = (
                    body.position.x * 0.4 + target_pos[0] * 0.6,
                    body.position.y * 0.4 + target_pos[1] * 0.6
                )
                body.angle = desired_angle
                if hasattr(body, "velocity"):
                    try:
                        import pymunk
                        body.velocity = pymunk.Vec2d(math.cos(desired_angle) * 40.0, math.sin(desired_angle) * 40.0)
                    except Exception:
                        pass
                self.recovery_timer = 0.0
                self._recovery_attempts = 0
                self._no_progress_timer = 0.0

            else:
                self.recovery_timer = min(
                    RECOVERY_MAX_SECONDS, RECOVERY_BASE_SECONDS * self._recovery_attempts
                )
                # Flip steering side from the second attempt onward so a car
                # wedged at an angle doesn't just repeat the move that stuck it.
                if self._recovery_attempts > 1:
                    self._recovery_steer_sign = -self._recovery_steer_sign
                self._no_progress_timer = 0.0

        return throttle, brake, steer

