"""
RemoteVehicle — kinematic physics body representing a networked opponent.

Playback uses **snapshot interpolation** (the Valve / Gambetta approach): every
received snapshot is placed on the SENDER's timeline (its ``send_time``) and
buffered, and the ghost is drawn at a small adaptive delay *behind* that
timeline, interpolating between the two snapshots that bracket the render
time. Rendering the recent past instead of guessing the future means jitter,
burst delivery and the odd late packet never make the car jump — it only ever
moves between positions the sender actually reported.

The cost is a constant ~INTERP_DELAY of visual lag (two to three packet
intervals at 50 Hz): a bump lands against a car drawn slightly behind where it
truly is. That trade is deliberate and standard for networked movement — a
steady small offset reads far better than the darts and rubber-banding that
extrapolation produces. When the buffer runs dry (real packet loss), playback
falls back to capped dead-reckoning so the ghost coasts on instead of freezing;
the step back onto the interpolated path is blended, never snapped.

Bis 06.10.2026 stand hier stattdessen Dead Reckoning mit Fehlerabbau: jedes
ankommende Paket setzte die Hochrechnung hart auf seine Lage, egal wie alt es
war, und ein Fehlerterm baute den Sprung mit 18/s ab. Ein Paket, das nur rund
60 ms zu spaet kam, zog das Abbild damit sichtbar RUECKWAERTS, kleinere
Schwankungen liessen das Tempo pumpen, in Kurven schoss die Gerade nach aussen
und wurde zurueckgeholt (gemeldet: "ruckeln/springen zurueck"). Puffer und
Verzoegerung wurden zwar gefuehrt, aber nie zum Zeichnen benutzt.

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
from src.ui import zeichnen

# Visual colors per slot index (slot 0 = local player, so remote starts at 1)
_SLOT_COLORS = [
    (60, 150, 255),    # slot 1 — blue
    (80, 220, 80),     # slot 2 — green
    (220, 80, 220),    # slot 3 — purple
    (220, 140, 0),     # slot 4 — amber
    (220, 80, 80),     # slot 5 — red
]

# Playback delay behind the sender's timeline — how far the ghost trails the
# real car. ADAPTIVE: it covers the measured packet spacing (50 Hz gesendet aus
# einer 60-fps-Schleife ergibt abwechselnd 17 und 33 ms) plus the connection's
# arrival jitter, buffering little on a steady line and more on a jittery one.
#
# The floor is deliberately kept ABOVE the packet spacing so the render time
# almost always sits between two received snapshots — i.e. the ghost is
# INTERPOLATED, never extrapolated forward. Guessing the future is what made
# the ghost snap backwards when the sender braked or cornered, so smoothness is
# chosen over currency here: a steady small trail, no back-jumps.
INTERP_DELAY_MIN = 0.04    # zwei Pakete bei 50 Hz, auch auf sauberer Leitung
INTERP_DELAY_MAX = 0.15    # bad line: heavy buffering for smoothness
INTERP_DELAY_START = 0.06  # until enough packets have been seen to measure jitter
# Target buffer = packet spacing + this many jitter-sigmas.
JITTER_SIGMAS = 2.0
# Asymmetric adaptation: grow fast when the line worsens (avoid a burst of
# jumps), shrink slowly when it recovers (no nervous flicker of the delay).
ADAPT_UP   = 0.5
ADAPT_DOWN = 0.03
# EWMA smoothing for the jitter estimate.
_STAT_ALPHA = 0.1
# Paketabstand auf der Senderzeitleiste: ein langsam abklingender Spitzenwert,
# denn der Puffer muss die LAENGSTE uebliche Luecke ueberbruecken, nicht die
# mittlere. Luecken ueber _SPACING_IGNORE sind Verlust oder Pause, kein Takt.
_SPACING_UP     = 0.3
_SPACING_DOWN   = 0.01
_SPACING_IGNORE = 0.25

# The render time is a MONOTONE clock on the sender's timeline, not
# `now - offset - delay` computed fresh each frame: when the buffer must grow
# (delay jumps up), recomputing would send the render time — and the ghost —
# backwards. Instead it always steps forward with the frame, a little faster or
# slower (RENDER_RATE_MIN..MAX) to chase its target. A back-jump becomes a
# brief slowdown. RENDER_CATCHUP is the gain in 1/s on the clock error.
RENDER_CATCHUP  = 5.0
RENDER_RATE_MIN = 0.75
RENDER_RATE_MAX = 1.25
# Liegt die Uhr weiter als das daneben (Senderneustart, lange Haenger), wird
# sie gesetzt statt nachgezogen — der Bildsprung wird dabei wie jeder andere
# ueber die Fehlerkorrektur abgebaut.
RENDER_RESYNC = 0.5

# When no snapshot covers the render time (genuine packet loss), the ghost
# dead-reckons from the newest snapshot along its reported velocity, but only
# for this long — after that it holds still so a crashed/timed-out peer does
# not coast across the whole track before the staleness pruning removes it.
MAX_EXTRAPOLATION = 0.35   # seconds past the newest snapshot

# Stoesst ein neues Paket die gezeichnete Lage um (es kam waehrend der
# Hochrechnung), wird die Differenz nicht gesprungen, sondern als Versatz
# abgebaut: mit CORRECTION_RATE (1/s), aber je Bild nie mehr als
# CORRECTION_SHARE des Wegs, den der Wiedergabepfad in diesem Bild zuruecklegt
# — so kann die Korrektur ein vorwaerts fahrendes Auto bremsen, aber nie
# rueckwaerts ziehen. Steht es (fast), gilt CORRECTION_MIN_SPEED (px/s, gut
# 1 m/s). Ab TELEPORT_DISTANCE (px, 12 m) ist es kein Messfehler mehr, sondern
# ein Neusetzen (Reset auf die Strecke): dann springen.
CORRECTION_RATE      = 10.0
CORRECTION_SHARE     = 0.5
CORRECTION_MIN_SPEED = 15.0
TELEPORT_DISTANCE    = 150.0

# Hermite-Kurven nur ueber kurze Luecken: ueber eine lange (Pause, Verlust)
# zoege die Geschwindigkeit als Tangente die Kurve weit vom Weg ab.
_HERMITE_MAX_SPAN = 0.1

# Ein send_time, das so weit hinter dem neuesten liegt, ist kein vertauschtes
# Paket mehr, sondern ein neu gestarteter Sender mit neuer Uhr.
_STREAM_RESET = 1.0

# Obergrenze des Puffers (Schnappschuesse). Abgebaut wird sonst alles, was
# hinter der Wiedergabezeit liegt — bei 50 Hz und hoechstens 0.15 s Verzoegerung
# sind es kaum zehn.
_BUFFER_MAX = 32


# Playback is driven by the wall clock (arrival stamps + render clock).
# Indirecting through this lets tests drive a virtual clock deterministically
# without any per-call overhead in the real game.
_clock = time.monotonic


def _wrap(winkel: float) -> float:
    """Winkel auf (-pi, pi] — fuer den kurzen Weg zwischen zwei Richtungen."""
    return (winkel + math.pi) % (2.0 * math.pi) - math.pi


class _Snap:
    """One state sample, stamped with the SENDER's clock (``t``)."""
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
        # Auch fuer die 3D-Darstellung: die Rennszene sucht das Modell ueber
        # den Schluessel, genau wie bei Spieler und KI.
        self.config_key  = config_key

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
        # Der Geist ist kinematisch, also fuer unser Auto unendlich schwer:
        # mit 0,3 (x 0,25 am Auto) prallte der Verursacher eines Auffahrunfalls
        # rueckwaerts ab, aus 100 km/h mit -8 km/h (gemeldet 06.10.2026).
        self._shape.elasticity = 0.0
        self._space = space
        space.add(self._body, self._shape)

        # Snapshot buffer (oldest → newest), Zeit = Senderuhr
        self._buffer: deque[_Snap] = deque()

        # _pos/_vel/_angle/_omega are the drawn render state — what is
        # drawn and what drives the kinematic collision body this frame.
        self._pos:   tuple[float, float] = (0.0, 0.0)
        self._vel:   tuple[float, float] = (0.0, 0.0)
        self._angle: float               = 0.0
        self._omega: float               = 0.0

        # Noch abzubauender Versatz zwischen gezeichneter Lage und Wiedergabe-
        # pfad (entsteht, wenn ein Paket die Hochrechnung korrigiert).
        self._err_pos:   tuple[float, float] = (0.0, 0.0)
        self._err_angle: float               = 0.0
        # Lage auf dem Wiedergabepfad im letzten Bild (ohne Versatz).
        self._pfad:      tuple[float, float] = (0.0, 0.0)

        # Newest accepted raw snapshot — read by the AI takeover.
        self._target_pos:   tuple[float, float] = (0.0, 0.0)
        self._target_vel:   tuple[float, float] = (0.0, 0.0)
        self._target_angle: float               = 0.0
        self._target_omega: float               = 0.0

        self._initialized: bool          = False
        self._last_recv_ts: float        = 0.0

        # Wiedergabeuhr (Senderzeit), Puffertiefe und ihre Messgroessen.
        self._render_time: float | None  = None
        self._delay: float               = INTERP_DELAY_START
        self._jitter: float              = 0.0
        self._spacing: float             = 0.0
        # Senderuhr -> eigene Uhr: arrival - send_time des schnellsten Pakets.
        self._clock_offset: float | None = None

        self.lap: int = 0
        self.wp:  int = 0

    # ── Network ───────────────────────────────────────────────────────────────

    def apply_snapshot(self, snap: dict, send_time: float = 0.0,
                       arrival: float = 0.0) -> None:
        """Place a state snapshot on the sender's timeline and buffer it.

        ``send_time`` is the sender's monotonic clock (STATE header), ``arrival``
        our own clock when the datagram came in (stamped in the recv thread).
        Without a send_time the arrival time stands in — then late packets
        can't be told from early ones, but nothing breaks.
        """
        now = _clock()
        self._last_recv_ts = now
        if arrival <= 0.0:
            arrival = now

        x = float(snap["x"]); y = float(snap["y"])
        vx = float(snap["vx"]); vy = float(snap["vy"])
        angle = float(snap["angle"]); omega = float(snap.get("omega", 0.0))

        buf = self._buffer
        vorher = self._sample(self._render_time) if (buf and self._render_time is not None) else None
        ersetzen = False

        if send_time:
            t = float(send_time)
            # Neu gestarteter Sender: seine Uhr hat mit der alten nichts zu tun.
            if buf and t < buf[-1].t - _STREAM_RESET:
                self._neuer_strom()
                vorher = None
            # UDP ordnet nicht: ein Paket, das nicht neuer ist als das neueste
            # gepufferte, ist vertauscht oder doppelt — es wird ganz verworfen,
            # auch fuer Runde/Wegpunkt und die Uebernahme (sonst sprangen die
            # zurueck).
            if buf and t <= buf[-1].t:
                return
            sample = arrival - t
            if self._clock_offset is None or sample < self._clock_offset:
                self._clock_offset = sample
            else:
                # Langsam nachziehen: Uhrendrift, dauerhaft laengerer Weg.
                self._clock_offset += (sample - self._clock_offset) * 0.001
            lateness = sample - self._clock_offset
        else:
            t = arrival - (self._clock_offset or 0.0)
            # Ohne Senderzeit gilt die Ankunftsreihenfolge. Zwei Pakete im
            # selben Augenblick: das spaetere ist das neuere.
            ersetzen = bool(buf) and t <= buf[-1].t
            lateness = 0.0

        if buf and not ersetzen:
            self._note_spacing(t - buf[-1].t)
        self._update_delay(lateness)

        self._target_pos = (x, y)
        self._target_vel = (vx, vy)
        self._target_angle = angle
        self._target_omega = omega
        self.lap = int(snap.get("lap", 0))
        self.wp  = int(snap.get("wp", 0))

        if ersetzen:
            buf[-1] = _Snap(buf[-1].t, x, y, vx, vy, angle, omega)
        else:
            buf.append(_Snap(t, x, y, vx, vy, angle, omega))
        while len(buf) > _BUFFER_MAX:
            buf.popleft()

        if not self._initialized:
            self._pos = (x, y)
            self._pfad = (x, y)
            self._vel = (vx, vy)
            self._angle = angle
            self._omega = omega
            self._initialized = True
            self._body_setzen()
            return

        # Kam das Paket waehrend der Hochrechnung, verschiebt es den Pfad an
        # der aktuellen Wiedergabezeit. Die gezeichnete Lage bleibt stehen, der
        # Unterschied wird ueber die naechsten Bilder abgebaut.
        if vorher is not None:
            self._versatz_aufnehmen(vorher, self._sample(self._render_time))

    def _neuer_strom(self) -> None:
        """Senderuhr neu: Puffer und alles, was an der alten Uhr hing, vergessen."""
        self._buffer.clear()
        self._clock_offset = None
        self._render_time = None
        self._spacing = 0.0
        self._jitter = 0.0

    def _note_spacing(self, abstand: float) -> None:
        """Spitzenwert des Paketabstands auf der Senderzeitleiste nachfuehren."""
        if abstand <= 0.0 or abstand > _SPACING_IGNORE:
            return
        rate = _SPACING_UP if abstand > self._spacing else _SPACING_DOWN
        self._spacing += (abstand - self._spacing) * rate

    def _update_delay(self, lateness: float) -> None:
        """Re-target the buffer from how late this packet was vs. its sender timeline slot."""
        lateness = max(0.0, lateness)
        self._jitter += (lateness - self._jitter) * _STAT_ALPHA

        target = max(INTERP_DELAY_MIN, self._spacing) + JITTER_SIGMAS * self._jitter
        if target > INTERP_DELAY_MAX:
            target = INTERP_DELAY_MAX

        rate = ADAPT_UP if target > self._delay else ADAPT_DOWN
        self._delay += (target - self._delay) * rate

    # ── Simulation ────────────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        """Advance the render clock, sample the buffered path, blend out corrections."""
        if not self._initialized or dt <= 0.0 or not self._buffer:
            return

        ziel = _clock() - (self._clock_offset or 0.0) - self._delay
        r = self._render_time
        if r is None:
            r = ziel
        elif abs(ziel - r) > RENDER_RESYNC:
            vorher = self._sample(r)
            r = ziel
            self._versatz_aufnehmen(vorher, self._sample(r))
        else:
            # Verglichen wird mit dem Stand NACH diesem Schritt — mit dem alten
            # liefe die Uhr im Gleichgewicht ein ganzes Bild vor ihrem Ziel.
            rate = 1.0 + RENDER_CATCHUP * (ziel - (r + dt))
            rate = min(RENDER_RATE_MAX, max(RENDER_RATE_MIN, rate))
            r += dt * rate
        self._render_time = r

        # Was hinter der Wiedergabezeit liegt, braucht nur noch den einen
        # Schnappschuss, der sie von unten einklammert.
        buf = self._buffer
        while len(buf) > 2 and buf[1].t <= r:
            buf.popleft()

        x, y, vx, vy, winkel, omega = self._sample(r)
        weg = math.hypot(x - self._pfad[0], y - self._pfad[1])
        self._pfad = (x, y)
        self._versatz_abbauen(weg, dt)

        ex, ey = self._err_pos
        self._pos = (x + ex, y + ey)
        self._vel = (vx, vy)
        # Stetig weiterdrehen statt den Rohwinkel zu nehmen: springt der
        # Sender ueber +-pi, macht das gezeichnete Auto keinen Satz um 2 pi.
        self._angle += _wrap(winkel + self._err_angle - self._angle)
        self._omega = omega
        self._body_setzen()

    def _sample(self, r: float) -> tuple[float, float, float, float, float, float]:
        """Lage auf dem gepufferten Pfad zur Senderzeit *r*:
        (x, y, vx, vy, angle, omega)."""
        buf = self._buffer
        erster = buf[0]
        if r <= erster.t:
            return (erster.x, erster.y, erster.vx, erster.vy, erster.angle, erster.omega)

        neuester = buf[-1]
        if r >= neuester.t:
            # Puffer leer gelaufen: begrenzt hochrechnen, dann stehen bleiben.
            alter = r - neuester.t
            if alter > MAX_EXTRAPOLATION:
                return (neuester.x + neuester.vx * MAX_EXTRAPOLATION,
                        neuester.y + neuester.vy * MAX_EXTRAPOLATION,
                        0.0, 0.0,
                        neuester.angle + neuester.omega * MAX_EXTRAPOLATION, 0.0)
            return (neuester.x + neuester.vx * alter,
                    neuester.y + neuester.vy * alter,
                    neuester.vx, neuester.vy,
                    neuester.angle + neuester.omega * alter, neuester.omega)

        s0, s1 = self._bracket(r)
        span = s1.t - s0.t
        u = (r - s0.t) / span if span > 1e-9 else 1.0
        lx = s0.x + (s1.x - s0.x) * u
        ly = s0.y + (s1.y - s0.y) * u
        x, y = lx, ly
        if span <= _HERMITE_MAX_SPAN:
            hx, hy = self._hermite(s0, s1, span, u)
            # Passen Geschwindigkeit und Wegstueck nicht zusammen (Rempler,
            # Abprall), schlaegt die Kurve Haken — dann lieber die Gerade.
            sehne = math.hypot(s1.x - s0.x, s1.y - s0.y)
            if math.hypot(hx - lx, hy - ly) <= 0.25 * sehne + 0.5:
                x, y = hx, hy
        vx = s0.vx + (s1.vx - s0.vx) * u
        vy = s0.vy + (s1.vy - s0.vy) * u
        winkel = s0.angle + _wrap(s1.angle - s0.angle) * u
        omega = s0.omega + (s1.omega - s0.omega) * u
        return (x, y, vx, vy, winkel, omega)

    def _versatz_aufnehmen(self, vorher, nachher) -> None:
        """Einen Pfadsprung in den Versatz legen, damit das Bild nicht springt."""
        self._pfad = (nachher[0], nachher[1])
        ex = self._err_pos[0] + vorher[0] - nachher[0]
        ey = self._err_pos[1] + vorher[1] - nachher[1]
        if math.hypot(ex, ey) > TELEPORT_DISTANCE:
            # Neu gesetzt (Reset, Senderneustart): ehrlich springen.
            self._err_pos = (0.0, 0.0)
            self._err_angle = 0.0
            return
        self._err_pos = (ex, ey)
        self._err_angle = _wrap(self._err_angle + _wrap(vorher[4] - nachher[4]))

    def _versatz_abbauen(self, weg: float, dt: float) -> None:
        """Den Versatz abklingen lassen, hoechstens um einen Teil von *weg*,
        dem Stueck, das der Wiedergabepfad in diesem Bild vorangekommen ist."""
        anteil = 1.0 - math.exp(-CORRECTION_RATE * dt)
        ex, ey = self._err_pos
        betrag = math.hypot(ex, ey)
        if betrag > 0.0:
            abbau = min(betrag * anteil,
                        max(CORRECTION_MIN_SPEED * dt, CORRECTION_SHARE * weg))
            rest = betrag - abbau
            if rest < 0.01:
                self._err_pos = (0.0, 0.0)
            else:
                f = rest / betrag
                self._err_pos = (ex * f, ey * f)
        self._err_angle *= 1.0 - anteil
        if abs(self._err_angle) < 1e-4:
            self._err_angle = 0.0

    def _body_setzen(self) -> None:
        """Drive the kinematic pymunk body from the drawn state."""
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
            zeichnen.rect(surface, (10, 11, 18, 180), bg_rect, border_radius=4)

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
    def omega(self) -> float:
        """Gierrate in rad/s — daraus leitet die 3D-Darstellung den Lenkeinschlag ab."""
        return self._omega

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
