"""Vehicle base class and configuration data class."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pymunk

from src.entities.components.physics_body import PhysicsBody
from src.entities.components.engine import Engine
from src.entities.components.steering import Steering
from src.entities.components.brakes import Brakes
from src.entities.components.renderer import VehicleRenderer
from src.core.settings import COLLISION_TYPE_VEHICLE

if TYPE_CHECKING:
    from src.physics.physics_world import PhysicsWorld


def get_vehicle_vertices(visual_type: str, length: float, width: float) -> list[tuple[float, float]]:
    """Generate custom convex polygon vertices tailored to the visual silhouette of each car style."""
    L = length
    W = width

    # Variant configs are named "<class>_2" / "<class>_3"; they share their
    # class's silhouette, so strip the suffix before matching.
    visual_type = str(visual_type).split("_")[0]

    if visual_type == "rookie":
        # Hatchback: rounded/tapered front nose, flat rear tail
        return [
            (L / 2, -W / 6),                    # Front-left nose
            (L / 2 - L * 0.15, -W / 2),         # Front-left fender
            (-L / 2 + L * 0.05, -W / 2),        # Rear-left fender
            (-L / 2, -W * 0.42),                # Rear-left tail
            (-L / 2, W * 0.42),                 # Rear-right tail
            (-L / 2 + L * 0.05, W / 2),         # Rear-right fender
            (L / 2 - L * 0.15, W / 2),          # Front-right fender
            (L / 2, W / 6),                     # Front-right nose
        ]
    elif visual_type == "supercar":
        # Supercar: pointed nose, aerodynamic tapered rear
        return [
            (L / 2, 0.0),                       # Pointed nose
            (L / 2 - L * 0.22, -W / 2),         # Front-left fender
            (-L / 2 + L * 0.12, -W / 2),        # Rear-left fender
            (-L / 2, -W * 0.25),                # Rear-left tail
            (-L / 2, W * 0.25),                 # Rear-right tail
            (-L / 2 + L * 0.12, W / 2),         # Rear-right fender
            (L / 2 - L * 0.22, W / 2),          # Front-right fender
        ]
    elif visual_type == "drifter":
        # Drifter: wide spoiler, slightly chamfered corners
        return [
            (L / 2, -W / 5),
            (L / 2 - L * 0.12, -W / 2),
            (-L / 2 + L * 0.08, -W / 2),
            (-L / 2, -W * 0.35),
            (-L / 2, W * 0.35),
            (-L / 2 + L * 0.08, W / 2),
            (L / 2 - L * 0.12, W / 2),
            (L / 2, W / 5),
        ]
    elif visual_type == "limousine":
        # Limousine: very square, small chamfer
        return [
            (L / 2, -W * 0.35),
            (L / 2 - L * 0.06, -W / 2),
            (-L / 2 + L * 0.06, -W / 2),
            (-L / 2, -W * 0.4),
            (-L / 2, W * 0.4),
            (-L / 2 + L * 0.06, W / 2),
            (L / 2 - L * 0.06, W / 2),
            (L / 2, W * 0.35),
        ]
    elif visual_type == "electric":
        # Electric: futuristic, tapered nose
        return [
            (L / 2, -W * 0.15),
            (L / 2 - L * 0.18, -W / 2),
            (-L / 2 + L * 0.1, -W / 2),
            (-L / 2, -W * 0.3),
            (-L / 2, W * 0.3),
            (-L / 2 + L * 0.1, W / 2),
            (L / 2 - L * 0.18, W / 2),
            (L / 2, W * 0.15),
        ]
    else:
        # Default fallback standard octagon
        return [
            (L / 2, -W / 6),
            (L / 2 - L * 0.15, -W / 2),
            (-L / 2 + L * 0.1, -W / 2),
            (-L / 2, -W * 0.3),
            (-L / 2, W * 0.3),
            (-L / 2 + L * 0.1, W / 2),
            (L / 2 - L * 0.15, W / 2),
            (L / 2, W / 6),
        ]


@dataclass
class VehicleConfig:
    """All physics and visual parameters for a vehicle type."""

    name: str = "Default Car"
    description: str = ""
    visual_type: str = "supercar"
    mass: float = 950.0               # kg
    engine_power: float = 35000.0     # N (force at full throttle)
    max_speed: float = 260.0          # px/s
    grip: float = 0.82                # lateral grip (0–1)
    brake_force: float = 45000.0      # N
    turn_speed: float = 2.2           # rad/s
    drift_threshold: float = 0.65     # speed ratio where grip drops
    drag_coefficient: float = 0.30    # aerodynamic drag coefficient cw
    frontal_area: float = 2.2         # frontal area A in m² (for F = ½·ρ·cw·A·v²)
    roll_coefficient: float = 0.011   # rolling resistance coefficient
    idle_rpm: float = 1000.0
    redline_rpm: float = 6000.0
    width_px: int = 28                # collision box width (overall vehicle width)
    height_px: int = 48               # collision box height (overall length)
    wheelbase_m: float = 2.50         # wheelbase in meters (Radstand)
    com_bias: float = 0.0             # weight bias: + = front-heavy .. - = rear-heavy (Masse-Zentrum)
    wheel_diameter: float = 0.65       # wheel diameter in meters
    color_primary: tuple[int, int, int] = (220, 40, 40)
    color_secondary: tuple[int, int, int] = (40, 40, 40)
    gear_ratios: list[float] | None = None
    num_gears: int = 5
    gear_i_max: float = 3.5
    gear_i_min: float = 0.8
    # Optional custom torque curve: list of [rpm, Nm] points. When set it shapes
    # the engine torque instead of the built-in parabolic/electric formula.
    torque_curve: list[list[float]] | None = None
    drive_type: str = "rwd"
    # Klangfaerbung (Block C, §C5): Tonhoehenversatz und Hoehen-/Tiefenneigung,
    # damit zwei Fahrzeuge derselben Klasse nicht identisch klingen.
    klang_tonhoehe: float = 1.0
    klang_faerbung: float = 0.0
    #: Maskenwerte fuer die Umfaerbung (Releaseplan D3). None heisst: nicht
    #: abgestimmt, das Fahrzeug bietet nur Werkslack an.
    paint: dict | None = None

    @staticmethod
    def from_json(path: str) -> VehicleConfig:
        """Load a VehicleConfig from a JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        phys = data.get("physics", {})
        ratios = data.get("gear_ratios", None)
        if ratios:
            num_gears = len(ratios)
            gear_i_max = float(ratios[0])
            gear_i_min = float(ratios[-1])
        else:
            num_gears = 5
            gear_i_max = 3.5
            gear_i_min = 0.8

        height_px = data.get("height_px", 48)
        width_px = data.get("width_px", 28)
        
        # Load wheelbase in meters, fallback to translating old ratio
        wheelbase_m = phys.get("wheelbase", phys.get("wheelbase_ratio", 0.65) * height_px * 0.08)
        # Load track width in meters, fallback to translating old width
        track_width = phys.get("track_width", width_px * 0.08)

        torque_curve = data.get("torque_curve", None)
        klang = data.get("klang", {})

        # Compute engine_power from torque curve when present
        engine_power = phys.get("engine_power", 35000.0)
        if torque_curve:
            # P(rpm) = T(Nm) × ω(rad/s) ; find max power point
            max_power_watts = 0.0
            for rpm_val, nm_val in torque_curve:
                if rpm_val > 0:
                    omega = rpm_val * 2.0 * math.pi / 60.0
                    p = nm_val * omega
                    if p > max_power_watts:
                        max_power_watts = p
            if max_power_watts > 0:
                # Convert Watts back to internal scale (internal * 7.355 = Watts)
                engine_power = max_power_watts / 7.355

        return VehicleConfig(
            name=data.get("name", "Unknown"),
            description=data.get("description", ""),
            visual_type=data.get("visual_type", "supercar"),
            mass=phys.get("mass", 950.0),
            engine_power=engine_power,
            max_speed=phys.get("max_speed", 260.0),
            grip=phys.get("grip", 0.82),
            brake_force=phys.get("brake_force", 45000.0),
            turn_speed=phys.get("turn_speed", 2.2),
            drift_threshold=phys.get("drift_threshold", 0.65),
            drag_coefficient=phys.get("drag_coefficient", 0.30),
            frontal_area=phys.get("frontal_area", 2.2),
            roll_coefficient=phys.get("roll_coefficient", 0.011),
            idle_rpm=phys.get("idle_rpm", 1000.0),
            redline_rpm=phys.get("redline_rpm", 6000.0),
            width_px=width_px,
            height_px=height_px,
            wheelbase_m=wheelbase_m,
            com_bias=phys.get("com_bias", 0.0),
            wheel_diameter=phys.get("wheel_diameter", 0.65),
            color_primary=tuple(data.get("color_primary", [220, 40, 40])),
            color_secondary=tuple(data.get("color_secondary", [40, 40, 40])),
            gear_ratios=ratios,
            num_gears=num_gears,
            gear_i_max=gear_i_max,
            gear_i_min=gear_i_min,
            torque_curve=torque_curve,
            drive_type=phys.get("drive_type", "rwd"),
            klang_tonhoehe=float(klang.get("tonhoehe", 1.0)),
            klang_faerbung=float(klang.get("faerbung", 0.0)),
            paint=data.get("paint") if isinstance(data.get("paint"), dict) else None,
        )


class Vehicle:
    """Base class for all vehicles, using component composition.

    Owns: PhysicsBody, Engine, Steering, Brakes, VehicleRenderer.
    Subclasses set throttle/brake_input/steer_input per frame.
    """

    is_takeover: bool = False   # online: AI inherited this car from a player that left

    def __init__(
        self,
        vehicle_id: int,
        config: VehicleConfig,
        start_pos: tuple[float, float],
        start_angle: float,
        space: pymunk.Space,
        lack: str = "werk",
        config_key: str = "",
    ) -> None:
        self.id = vehicle_id
        self.config = config
        #: Lackierung dieses Fahrzeugs. Der Spieler waehlt seine in der
        #: Werkstatt; die KI bekommt eine aus ihrer Fahrzeugnummer
        #: (``lack.ki_lack``), damit fuenf gleiche Autos im Feld
        #: auseinanderzuhalten sind. Der Ghost wird stattdessen entfaerbt.
        self.lack = lack
        self.config_key = config_key

        # Generate custom convex polygon vertices based on visual type
        vertices = get_vehicle_vertices(config.visual_type, config.height_px, config.width_px)

        # Components
        self.physics = PhysicsBody(
            mass=config.mass,
            width=config.width_px,
            height=config.height_px,
            position=start_pos,
            angle=start_angle,
            space=space,
            vertices=vertices,
            wheelbase_ratio=config.wheelbase_m / (config.height_px * 0.08),
            com_bias=getattr(config, "com_bias", 0.0),
        )
        self.physics.body.data = self
        self.physics.shape.data = self
        self.engine = Engine(
            max_power=config.engine_power,
            max_speed=config.max_speed,
            gear_ratios=config.gear_ratios,
            gears_max_speeds_ratios=None,
            idle_rpm=config.idle_rpm,
            redline_rpm=config.redline_rpm,
            shift_up_rpm=config.redline_rpm * 0.95,
            torque_curve=getattr(config, "torque_curve", None),
            wheel_diameter=getattr(config, "wheel_diameter", 0.65),
        )
        self.steering = Steering(config.turn_speed, config.drift_threshold, config.grip)
        self.brakes = Brakes(config.brake_force)
        self.renderer = VehicleRenderer(
            config.width_px, config.height_px,
            config.color_primary, config.color_secondary,
            config.visual_type,
            lack=lack,
            config_key=config_key or config.visual_type,
        )

        # Input state (set by subclass each frame)
        self.throttle: float = 0.0
        self.brake_input: float = 0.0
        self.steer_input: float = 0.0
        self.handbrake: bool = False
        self.is_touching_wall: bool = False

        # Subscribe to wall collision events
        from src.core.event_bus import EventBus
        self.event_bus = EventBus()
        self.event_bus.subscribe("collision_vehicle_wall", self._on_wall_collision)
        self.event_bus.subscribe("collision_vehicle_wall_end", self._on_wall_collision_end)

        # Race tracking
        self.current_lap: int = 0
        self.lap_times: list[float] = []

        # Physics extensions live state
        self.prev_velocity = pymunk.Vec2d(0.0, 0.0)
        self.in_slipstream: bool = False

    # ---- Properties ----

    @property
    def body(self) -> pymunk.Body:
        return self.physics.body

    @property
    def speed(self) -> float:
        return self.physics.speed

    @property
    def position(self) -> tuple[float, float]:
        return self.physics.position

    @property
    def angle(self) -> float:
        return self.physics.angle

    @property
    def rpm(self) -> float:
        """Current engine RPM."""
        return self.engine.current_rpm

    @property
    def gear(self) -> int:
        """Current active gearbox gear (1 to 5)."""
        return self.engine.current_gear

    @property
    def is_drifting(self) -> bool:
        """True if the vehicle is currently sliding/drifting or touching a wall."""
        return self.physics.is_drifting or self.is_touching_wall

    @property
    def slip_angle(self) -> float:
        """Current tire slip angle in degrees."""
        return self.physics.slip_angle_deg

    @property
    def signed_speed(self) -> float:
        """Speed in px/s, positive for forward, negative for reverse."""
        angle = self.physics.body.angle
        forward = pymunk.Vec2d(math.cos(angle), math.sin(angle))
        return self.physics.body.velocity.dot(forward)

    # ---- Update ----

    def update(self, dt: float) -> None:
        """Apply all physics forces for this frame."""
        # --- 1. Acceleration & Weight Transfer ---
        current_vel = self.physics.body.velocity
        # Acceleration (finite difference). prev_velocity is initialised to zero in
        # __init__, so the first frame produces no spike.
        accel_vec = (current_vel - self.prev_velocity) / dt
        self.prev_velocity = pymunk.Vec2d(current_vel.x, current_vel.y)

        # Project acceleration onto vehicle forward heading vector
        angle = self.physics.body.angle
        forward = pymunk.Vec2d(math.cos(angle), math.sin(angle))
        long_accel = accel_vec.dot(forward)

        # Weight transfer ratio (-0.35 to 0.35)
        weight_transfer = min(0.35, max(-0.35, long_accel * 0.0012))

        # Adjust steering scale: understeer on acceleration, oversteer on braking
        if weight_transfer > 0.0:
            steer_scale = 1.0 - min(0.22, weight_transfer * 0.7)
        else:
            steer_scale = 1.0 + min(0.15, -weight_transfer * 0.4)

        # --- 2. Slipstream (Windschatten) ---
        self.in_slipstream = False
        drag_coeff = self.config.drag_coefficient

        # Perform forward segment query raycast in the Pymunk space
        space = self.physics._space
        if space:
            # Start raycast from the front of the vehicle
            front_offset = self.config.height_px / 2 + 5
            start_pos = self.physics.body.position + forward * front_offset
            
            # Query range: 400 pixels
            slipstream_max_dist = 400.0
            end_pos = start_pos + forward * slipstream_max_dist
            
            # Query the space for segment intersections
            hits = space.segment_query(start_pos, end_pos, 1.0, pymunk.ShapeFilter())
            info = None
            for h in sorted(hits, key=lambda h: h.alpha):
                if h.shape is None or h.shape.sensor:
                    continue
                if h.shape.body == self.physics.body:
                    continue
                info = h
                break

            # Check if we hit another vehicle
            if info and info.shape and info.shape.body != self.physics.body:
                if info.shape.collision_type == COLLISION_TYPE_VEHICLE:
                    self.in_slipstream = True
                    dist = info.alpha * slipstream_max_dist
                    
                    # Calculate drag reduction: up to 40% reduction at 0 distance, tapering to 0% at 400px
                    drag_reduction = 1.0 - (1.0 - dist / slipstream_max_dist) * 0.40
                    drag_coeff = self.config.drag_coefficient * drag_reduction

        # --- 3. Apply Forces ---
        # Engine force (pass dt and braking flag for shifting logic)
        drive_force = self.engine.compute_force(self.throttle, self.speed, dt, self.brake_input > 0.0)

        # Apply drive force using axle-based torque distribution and limits
        self.physics.apply_drive_force(
            force=drive_force,
            drive_type=getattr(self.config, "drive_type", "rwd"),
            grip=self.config.grip,
            handbrake=self.handbrake,
            weight_transfer=weight_transfer
        )

        # Braking
        brake_force = self.brakes.compute_force(self.brake_input)
        if brake_force > 0.0:
            self.physics.apply_brake_force(brake_force, dt)

        # Steering
        is_analog = getattr(self, "is_analog", False)
        if is_analog:
            self.physics.apply_steering(self.steer_input, dt, is_analog=True)
        else:
            steer_delta = self.steering.compute_steer(
                self.steer_input, self.speed, self.config.max_speed, dt
            )
            steer_delta *= steer_scale
            self.physics.apply_steering(steer_delta, dt, is_analog=False)

        # Drag (with potential slipstream reduction)
        self.physics.apply_drag(drag_coeff, getattr(self.config, "frontal_area", 2.2))

        # Rolling resistance
        self.physics.apply_roll_resistance(self.config.roll_coefficient)

        # Lateral friction (grip)
        # Apply axle-based lateral friction taking handbrake and dynamic weight transfer into account
        self.physics.apply_lateral_friction(self.config.grip, self.handbrake, weight_transfer, dt)

    # ---- Render ----

    def render(self, screen, camera_offset) -> None:
        """Draw the vehicle on screen."""
        self.renderer.draw(
            screen,
            self.physics.position,
            self.physics.angle,
            camera_offset,
        )

        from src.core import race_setup
        
        # 1. Render driver name above vehicle
        if getattr(self, "driver_name", ""):
            import pygame
            from src.utils.math_utils import to_pygame
            from src.core.settings import SCREEN_HEIGHT
            from src.ui import theme
            
            screen_pos = to_pygame(self.physics.position, SCREEN_HEIGHT)
            x = int(screen_pos[0] + camera_offset.x)
            
            is_team_mode = (race_setup.current().mode == "Team-Zeitfahren" and hasattr(self, "team"))
            y = int(screen_pos[1] + camera_offset.y) - (54 if is_team_mode else 40)
            
            if is_team_mode:
                color = (255, 120, 0) if self.team == "A" else (0, 140, 255)
            else:
                color = (255, 255, 255)
                
            text_surf = theme.font(14).render(self.driver_name, True, color)
            bg_rect = text_surf.get_rect(center=(x, y))
            bg_rect.inflate_ip(8, 4)
            pygame.draw.rect(screen, (10, 11, 18, 180), bg_rect, border_radius=4)
            
            text_rect = text_surf.get_rect(center=(x, y))
            screen.blit(text_surf, text_rect)

        # 2. Render Team-Zeitfahren team badge
        if race_setup.current().mode == "Team-Zeitfahren" and hasattr(self, "team"):
            import pygame
            from src.utils.math_utils import to_pygame
            from src.core.settings import SCREEN_HEIGHT
            from src.ui import theme

            screen_pos = to_pygame(self.physics.position, SCREEN_HEIGHT)
            x = int(screen_pos[0] + camera_offset.x)
            y = int(screen_pos[1] + camera_offset.y) - 32

            badge_color = (255, 120, 0) if self.team == "A" else (0, 140, 255)
            pygame.draw.circle(screen, badge_color, (x, y), 10)
            pygame.draw.circle(screen, (255, 255, 255), (x, y), 10, 1)

            text_surf = theme.font(16).render(self.team, True, (255, 255, 255))
            text_rect = text_surf.get_rect(center=(x, y))
            screen.blit(text_surf, text_rect)

    # ---- Collision Callbacks ----

    def _on_wall_collision(self, data: dict[str, Any]) -> None:
        if data.get("vehicle_body_id") == id(self.physics.body):
            self.is_touching_wall = True

    def _on_wall_collision_end(self, data: dict[str, Any]) -> None:
        if data.get("vehicle_body_id") == id(self.physics.body):
            self.is_touching_wall = False

    # ---- Cleanup ----

    def cleanup(self, space: pymunk.Space) -> None:
        """Remove the physics body from the space and unsubscribe events."""
        self.event_bus.unsubscribe("collision_vehicle_wall", self._on_wall_collision)
        self.event_bus.unsubscribe("collision_vehicle_wall_end", self._on_wall_collision_end)
        self.physics.cleanup(space)
