"""
RemoteVehicle — kinematic physics body representing a networked opponent.

Playback uses **snapshot interpolation** (the Valve / Gambetta approach): every
received snapshot is timestamped and buffered, and the ghost is drawn at a
fixed delay *behind* real time, interpolating between the two snapshots that
bracket that render time. Rendering the recent past instead of guessing the
future means jitter and the odd late packet never make the car jump — it only
ever moves between positions the sender actually reported.

The cost is a constant ~INTERP_DELAY of visual lag: a bump lands against a car
drawn slightly behind where it truly is. That trade is deliberate and standard
for networked movement — a steady small offset reads far better than the darts
and rubber-banding that extrapolation produces when a sender's frame rate is
uneven. When the buffer runs dry (real packet loss), playback falls back to
capped dead-reckoning so the ghost coasts on instead of freezing.

Collision: kinematic body pushes dynamic local car but is unaffected by forces,
so every client "feels" the bump without needing a shared physics simulation.
"""
from __future__ import annotations

import math
import time
from collections import deque

import pygame
import pymunk

from src.entities.components.renderer import VehicleRenderer
from src.core.settings import COLLISION_TYPE_VEHICLE

# Visual colors per slot index (slot 0 = local player, so remote starts at 1)
_SLOT_COLORS = [
    (60, 150, 255),    # slot 1 — blue
    (80, 220, 80),     # slot 2 — green
    (220, 80, 220),    # slot 3 — purple
    (220, 140, 0),     # slot 4 — amber
    (220, 80, 80),     # slot 5 — red
]

# Playback delay behind real time — how far the ghost trails the real car.
# ADAPTIVE: it tracks the connection's packet-arrival jitter, buffering little
# on a steady line and more on a jittery one.
#
# The floor is deliberately kept ABOVE the packet spacing so the render time
# almost always sits between two received snapshots — i.e. the ghost is
# INTERPOLATED, never extrapolated forward. Guessing the future is what made
# the ghost snap backwards when the sender braked or cornered, so smoothness is
# chosen over currency here: a steady small trail, no back-jumps.
INTERP_DELAY_MIN = 0.035   # keep two snapshots bracketed even on a clean line
INTERP_DELAY_MAX = 0.15    # bad line: heavy buffering for smoothness
INTERP_DELAY_START = 0.05  # until enough packets have been seen to measure jitter
# Target buffer = this many jitter-sigmas above the floor.
JITTER_SIGMAS = 2.0
# Asymmetric adaptation: grow fast when the line worsens (avoid a burst of
# jumps), shrink slowly when it recovers (no nervous flicker of the delay).
ADAPT_UP   = 0.5
ADAPT_DOWN = 0.03
# EWMA smoothing for the jitter estimate.
_STAT_ALPHA = 0.1

# The render time is a MONOTONE clock, not `now - delay` computed fresh each
# frame: when the buffer must grow (delay jumps up), recomputing would send the
# render time — and the ghost — backwards. Instead it always steps forward,
# chasing `now - delay` at this rate, and slows to a crawl (never reverses)
# when it needs to fall further behind. A back-jump becomes a brief slowdown.
RENDER_CATCHUP = 0.12

# When no snapshot covers the render time (genuine packet loss), the ghost
# dead-reckons from the newest snapshot along its reported velocity, but only
# for this long — after that it holds still so a crashed/timed-out peer does
# not coast across the whole track before the staleness pruning removes it.
MAX_EXTRAPOLATION = 0.35   # seconds past the newest snapshot

# Oldest snapshots are dropped once they are this far behind the render time;
# a handful is plenty to bracket any render time within INTERP_DELAY.
_SNAPSHOT_TTL = 1.0   # seconds


# Playback is driven by the wall clock (snapshots are timestamped on arrival).
# Indirecting through this lets tests drive a virtual clock deterministically
# without any per-call overhead in the real game.
_clock = time.monotonic


class _Snap:
    """One timestamped state sample, in the order the sender produced it."""
    __slots__ = ("t", "x", "y", "vx", "vy", "angle", "omega")

    def __init__(self, t, x, y, vx, vy, angle, omega):
        self.t = t
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.angle = angle
        self.omega = omega


class RemoteVehicle:
    """Kinematic ghost vehicle driven by network state snapshots."""

    def __init__(
        self,
        vehicle_id: int,
        sender_slot: int,
        space: pymunk.Space,
        config_key: str = "rookie",
        lack: str = "werk",
    ) -> None:
        self.id          = vehicle_id
        self.is_remote   = True   # network ghost: must never advance local lap trackers
        self.sender_slot = sender_slot
        self.driver_name = ""
        self.team        = "A"

        # Renderer
        from src.entities.vehicle_factory import VehicleFactory
        cfg     = VehicleFactory.get_config(config_key)
        w       = getattr(cfg, "width_px",    36) if cfg else 36
        h       = getattr(cfg, "height_px",   64) if cfg else 64
        visual  = getattr(cfg, "visual_type", "rookie") if cfg else "rookie"
        color   = _SLOT_COLORS[(sender_slot - 1) % len(_SLOT_COLORS)]
        # Minimap: die Lackfarbe, sobald der Mitspieler eine gewaehlt hat — der
        # Punkt soll aussehen wie das Auto (gemeldet 30.07.2026); die holt sich
        # die Karte dann selbst vom Renderer. Im Werkslack bleibt es bei der
        # Platzfarbe, sonst waeren zwei Mitspieler im selben unveraenderten
        # Fahrzeug auf der Karte nicht mehr auseinanderzuhalten.
        from src.core.lack import WERK, normalisiere
        self.minimap_color = color if normalisiere(lack) == WERK else None
        # Die Lackierung des Mitspielers (Block D, D7). Sie kommt ueber das
        # PICK-Feld und den Lobbyzustand herein, nicht ueber den UDP-Strom: der
        # traegt je Fahrzeug 26 feste Bytes und ist kein Ort fuer eine Kennung.
        # Ein Mitspieler ohne Angabe faehrt im Werkslack — genau wie vorher.
        self.lack = lack
        self._renderer = VehicleRenderer(w, h, color, visual_type=visual,
                                         lack=lack, config_key=config_key)

        # Kinematic pymunk body — collides with dynamic bodies, not affected by forces
        self._body          = pymunk.Body(body_type=pymunk.Body.KINEMATIC)
        self._body.position = (0, 0)
        self._body.data     = self  # for collision handler to identify vehicle

        # Cropped silhouette instead of a full bounding box — same shape the
        # local car uses, so ghosts collide like the real vehicle they mirror.
        from src.entities.vehicle import get_vehicle_vertices
        vertices = None
        try:
            vertices = get_vehicle_vertices(visual, h, w)
        except Exception:
            vertices = None
        if vertices:
            self._shape = pymunk.Poly(self._body, vertices)
        else:
            self._shape = pymunk.Poly.create_box(self._body, (h, w))
        self._shape.collision_type = COLLISION_TYPE_VEHICLE
        self._shape.friction   = 0.2
        self._shape.elasticity = 0.3
        self._space = space
        space.add(self._body, self._shape)

        # Snapshot buffer (oldest → newest)
        self._buffer: deque[_Snap] = deque()

        # Simulation base state (extrapolated forward each frame at 60 FPS)
        self._sim_pos:   tuple[float, float] = (0.0, 0.0)

        self._sim_vel:   tuple[float, float] = (0.0, 0.0)
        self._sim_angle: float               = 0.0
        self._sim_omega: float               = 0.0

        # Exponential error decay vectors (smooth out corrections on packet arrival)
        self._error_pos:   tuple[float, float] = (0.0, 0.0)
        self._error_angle: float               = 0.0

        # _pos/_vel/_angle/_omega are the drawn render state — what is
        # drawn and what drives the kinematic collision body this frame.
        self._pos:   tuple[float, float] = (0.0, 0.0)
        self._vel:   tuple[float, float] = (0.0, 0.0)
        self._angle: float               = 0.0
        self._omega: float               = 0.0

        self._initialized: bool          = False
        self._last_recv_ts: float        = 0.0

        # Legacy compatibility fields
        self._render_time: float | None  = None
        self._last_update_now: float     = 0.0
        self._delay: float               = INTERP_DELAY_START
        self._jitter: float              = 0.0
        self._clock_offset: float | None = None

        self.lap: int = 0
        self.wp:  int = 0

    # ── Network ───────────────────────────────────────────────────────────────

    def apply_snapshot(self, snap: dict, send_time: float = 0.0,
                       arrival: float = 0.0) -> None:
        """Buffer a state snapshot and update prediction base state with error decay."""
        now = _clock()
        self._last_recv_ts = now

        if send_time:
            if arrival <= 0.0:
                arrival = now
            sample = arrival - send_time
            if self._clock_offset is None or sample < self._clock_offset:
                self._clock_offset = sample
            else:
                self._clock_offset += (sample - self._clock_offset) * 0.001
            buf_t = send_time + self._clock_offset
            self._update_delay(arrival - buf_t)
        else:
            buf_t = now

        x = float(snap["x"]); y = float(snap["y"])
        vx = float(snap["vx"]); vy = float(snap["vy"])
        angle = float(snap["angle"]); omega = float(snap.get("omega", 0.0))

        # Out-of-order guard: a late packet whose timeline slot is behind the newest buffered one is dropped
        if self._buffer and buf_t <= self._buffer[-1].t:
            self._target_pos = (x, y); self._target_vel = (vx, vy)
            self._target_angle = angle; self._target_omega = omega
            self.lap = int(snap.get("lap", 0)); self.wp = int(snap.get("wp", 0))
            return

        self._target_pos = (x, y)
        self._target_vel = (vx, vy)
        self._target_angle = angle
        self._target_omega = omega
        self.lap = int(snap.get("lap", 0))
        self.wp  = int(snap.get("wp", 0))

        self._buffer.append(_Snap(buf_t, x, y, vx, vy, angle, omega))
        while len(self._buffer) > 10:
            self._buffer.popleft()

        if not self._initialized:
            self._sim_pos = (x, y)
            self._sim_vel = (vx, vy)
            self._sim_angle = angle
            self._sim_omega = omega
            self._error_pos = (0.0, 0.0)
            self._error_angle = 0.0
            self._pos = (x, y)
            self._vel = (vx, vy)
            self._angle = angle
            self._omega = omega
            self._initialized = True
            self._body.position = pymunk.Vec2d(x, y)
            self._body.angle    = angle
            self._body.velocity = pymunk.Vec2d(vx, vy)
            self._body.angular_velocity = omega
            return

        # Position before new packet
        curr_drawn_x = self._sim_pos[0] + self._error_pos[0]
        curr_drawn_y = self._sim_pos[1] + self._error_pos[1]
        curr_drawn_angle = self._sim_angle + self._error_angle

        # Adopt new simulation state from packet
        self._sim_pos = (x, y)
        self._sim_vel = (vx, vy)

        d_angle = angle - self._sim_angle
        while d_angle > math.pi: d_angle -= 2 * math.pi
        while d_angle < -math.pi: d_angle += 2 * math.pi
        self._sim_angle = self._sim_angle + d_angle
        self._sim_omega = omega

        # Error vector absorbs position difference so there is NO visual jump
        self._error_pos = (curr_drawn_x - x, curr_drawn_y - y)

        err_a = curr_drawn_angle - self._sim_angle
        while err_a > math.pi: err_a -= 2 * math.pi
        while err_a < -math.pi: err_a += 2 * math.pi
        self._error_angle = err_a

    def _update_delay(self, lateness: float) -> None:
        """Re-target the buffer from how late this packet was vs. its sender timeline slot."""
        lateness = max(0.0, lateness)
        self._jitter += (lateness - self._jitter) * _STAT_ALPHA

        target = INTERP_DELAY_MIN + JITTER_SIGMAS * self._jitter
        if target < INTERP_DELAY_MIN:
            target = INTERP_DELAY_MIN
        elif target > INTERP_DELAY_MAX:
            target = INTERP_DELAY_MAX

        rate = ADAPT_UP if target > self._delay else ADAPT_DOWN
        self._delay += (target - self._delay) * rate

    # ── Simulation ────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """Advance simulation linearly and exponentially decay position correction error."""
        if not self._initialized or dt <= 0.0:
            return

        # Cap dead reckoning velocity if network updates have gone silent
        if self.seconds_since_update() > MAX_EXTRAPOLATION:
            self._sim_vel = (0.0, 0.0)
            self._sim_omega = 0.0

        # 1. Dead reckoning forward step
        self._sim_pos = (
            self._sim_pos[0] + self._sim_vel[0] * dt,
            self._sim_pos[1] + self._sim_vel[1] * dt
        )
        self._sim_angle += self._sim_omega * dt

        # 2. Smoothly decay correction error vector (~60ms decay half-life)
        decay = math.exp(-18.0 * dt)
        self._error_pos = (self._error_pos[0] * decay, self._error_pos[1] * decay)
        self._error_angle *= decay

        # 3. Compute final composite drawn state
        self._pos = (self._sim_pos[0] + self._error_pos[0], self._sim_pos[1] + self._error_pos[1])
        self._vel = self._sim_vel
        self._angle = self._sim_angle + self._error_angle
        self._omega = self._sim_omega

        # Drive the kinematic pymunk body
        self._body.position = pymunk.Vec2d(self._pos[0], self._pos[1])
        self._body.angle    = self._angle
        self._body.velocity = pymunk.Vec2d(self._vel[0], self._vel[1])
        self._body.angular_velocity = self._omega



    def _bracket(self, render_t: float) -> tuple[_Snap, _Snap]:
        """Return the newest pair of snapshots that straddles *render_t*."""
        buf = self._buffer
        for i in range(len(buf) - 1, 0, -1):
            if buf[i - 1].t <= render_t <= buf[i].t:
                return buf[i - 1], buf[i]
        return buf[0], buf[1]

    @staticmethod
    def _hermite(s0: _Snap, s1: _Snap, span: float, u: float) -> tuple[float, float]:
        """Cubic Hermite position between two samples, velocities as tangents."""
        u2 = u * u
        u3 = u2 * u
        h00 = 2 * u3 - 3 * u2 + 1
        h10 = u3 - 2 * u2 + u
        h01 = -2 * u3 + 3 * u2
        h11 = u3 - u2
        x = (h00 * s0.x + h10 * span * s0.vx + h01 * s1.x + h11 * span * s1.vx)
        y = (h00 * s0.y + h10 * span * s0.vy + h01 * s1.y + h11 * span * s1.vy)
        return (x, y)

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self, surface: pygame.Surface, offset) -> None:
        if not self._initialized:
            return
        self._renderer.draw(surface, self._pos, self._angle, offset)

        if getattr(self, "driver_name", ""):
            import pygame
            from src.utils.math_utils import to_pygame
            from src.core.settings import SCREEN_HEIGHT
            from src.ui import theme
            from src.core import race_setup
            
            screen_pos = to_pygame(self._pos, SCREEN_HEIGHT)
            x = int(screen_pos[0] + offset.x)
            y = int(screen_pos[1] + offset.y) - 40
            
            if race_setup.current().mode == "Team-Zeitfahren" and getattr(self, "team", ""):
                color = (255, 120, 0) if self.team == "A" else (0, 140, 255)
            else:
                color = (255, 255, 255)
                
            text_surf = theme.font(14).render(self.driver_name, True, color)
            bg_rect = text_surf.get_rect(center=(x, y))
            bg_rect.inflate_ip(8, 4)
            pygame.draw.rect(surface, (10, 11, 18, 180), bg_rect, border_radius=4)
            
            text_rect = text_surf.get_rect(center=(x, y))
            surface.blit(text_surf, text_rect)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def position(self) -> tuple[float, float]:
        return self._pos

    @property
    def velocity(self) -> tuple[float, float]:
        return self._vel

    @property
    def speed(self) -> float:
        """Tempo in px/s — dieselbe Einheit wie ``Vehicle.speed``.

        Gebraucht, damit die KI ein fremdes Spielerfahrzeug wie jedes andere
        behandeln kann: sie fragt an einem Gegner ``position`` und ``speed``.
        Ohne das lief sie in einen AttributeError, sobald ein Abbild im Feld
        stand — und stand keines darin, wich sie nicht aus (gemeldet 04.08.2026).
        """
        return math.hypot(self._vel[0], self._vel[1])

    @property
    def angle(self) -> float:
        return self._angle

    @property
    def bereit(self) -> bool:
        """Ob dieses Abbild schon eine Lage hat, die man glauben kann.

        Vor der ersten Nachricht steht es auf (0, 0) — als Gegner waere es dort
        ein Gespenst, dem eine KI in der Streckenmitte auszuweichen versucht.
        """
        return bool(getattr(self, "_initialized", False))

    @property
    def body(self) -> pymunk.Body:
        return self._body

    def seconds_since_update(self) -> float:
        """Wall time (monotonic) since the last snapshot arrived. inf if none."""
        if not getattr(self, "_initialized", False):
            return float("inf")
        return _clock() - self._last_recv_ts

    def progress(self, num_wp: int) -> float:
        """Race progress comparable with LapTracker: lap * num_waypoints + waypoint index."""
        return self.lap * max(1, num_wp) + self.wp

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self, space: pymunk.Space) -> None:
        if self._shape in space.shapes:
            space.remove(self._shape)
        if self._body in space.bodies:
            space.remove(self._body)
