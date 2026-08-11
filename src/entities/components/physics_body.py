"""PhysicsBody component – wraps a pymunk.Body and Shape for a vehicle.

All physics calculations happen in pymunk coordinate space (Y-up).
The renderer is responsible for coordinate conversion to pygame (Y-down).
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pymunk

from src.core.settings import COLLISION_TYPE_VEHICLE

if TYPE_CHECKING:
    pass


class PhysicsBody:
    """Encapsulates a pymunk rigid body and box shape for a vehicle.

    Provides high-level force application methods. Other modules
    should NOT touch pymunk directly — they go through this component.
    """

    def __init__(
        self,
        mass: float,
        width: float,
        height: float,
        position: tuple[float, float],
        angle: float,
        space: pymunk.Space,
        vertices: list[tuple[float, float]] | None = None,
        wheelbase_ratio: float = 0.65,
        com_bias: float = 0.0,
    ) -> None:
        """Create a physics body and add it to the space.

        Args:
            mass: Vehicle mass in kg.
            width: Collision box width in pixels.
            height: Collision box height in pixels.
            position: Starting position in pymunk coords (x, y).
            angle: Starting angle in radians.
            space: The pymunk space to add the body to.
            vertices: Optional list of custom polygon vertices.
        """
        if vertices is not None:
            moment = pymunk.moment_for_poly(mass, vertices)
        else:
            moment = pymunk.moment_for_box(mass, (height, width))

        self.body = pymunk.Body(mass, moment)
        self.body.position = position
        self.body.angle = angle

        if vertices is not None:
            self.shape = pymunk.Poly(self.body, vertices)
        else:
            self.shape = pymunk.Poly.create_box(self.body, (height, width))

        self.shape.friction = 0.7
        self.shape.elasticity = 0.25
        self.shape.collision_type = COLLISION_TYPE_VEHICLE

        self._space = space
        space.add(self.body, self.shape)

        # Chassis geometry (tunable in the vehicle lab)
        self.wheelbase_ratio: float = wheelbase_ratio  # fraction of length between axles
        self.com_bias: float = com_bias                # + front-heavy, - rear-heavy

        # Drift & Slip Live State
        self.is_drifting: bool = False
        self.slip_angle_deg: float = 0.0
        self.steer_angle: float = 0.0

    # ---- Properties ----

    @property
    def position(self) -> tuple[float, float]:
        """Raw pymunk position (x, y). Renderer handles conversion."""
        return (self.body.position.x, self.body.position.y)

    @property
    def angle(self) -> float:
        """Current rotation angle in radians."""
        return self.body.angle

    @property
    def speed(self) -> float:
        """Current scalar speed (magnitude of velocity)."""
        return self.body.velocity.length

    @property
    def velocity(self) -> pymunk.Vec2d:
        """Current velocity vector."""
        return self.body.velocity

    # ---- Force application ----

    def apply_drive_force(
        self, 
        force: float, 
        drive_type: str, 
        grip: float, 
        handbrake: bool, 
        weight_transfer: float
    ) -> None:
        """Apply drive force taking drivetrain type and axle traction limits into account."""
        body = self.body
        mass = body.mass

        # Wheelbase & axles
        verts = self.shape.get_vertices()
        xs = [v.x for v in verts]
        length = max(xs) - min(xs) if xs else 80.0
        wheelbase = length * self.wheelbase_ratio

        front_local = pymunk.Vec2d(wheelbase / 2, 0)
        rear_local = pymunk.Vec2d(-wheelbase / 2, 0)

        # Dynamic axle weight loads from weight bias and transfer
        front_frac = max(0.35, min(0.65, 0.5 + self.com_bias))
        front_frac_dyn = max(0.1, min(0.9, front_frac - weight_transfer))
        rear_frac_dyn = max(0.1, min(0.9, (1.0 - front_frac) + weight_transfer))

        # Grip coefficients per axle (handbrake locks the rear axle only)
        front_grip = grip
        rear_grip = grip * 0.3 if handbrake else grip

        # Max traction limits per axle (Newtons)
        max_traction_front = front_grip * front_frac_dyn * mass * 9.81
        max_traction_rear = rear_grip * rear_frac_dyn * mass * 9.81

        # Calculate wheel directions in local space
        steer_cos = math.cos(self.steer_angle)
        steer_sin = math.sin(self.steer_angle)
        front_dir_local = pymunk.Vec2d(steer_cos, steer_sin)
        rear_dir_local = pymunk.Vec2d(1.0, 0.0)

        # Apply force per drivetrain configuration
        d_type = drive_type.lower()
        if d_type == "fwd":
            # 100% on front axle
            f_front = max(-max_traction_front, min(max_traction_front, force))
            body.apply_force_at_local_point(front_dir_local * (f_front / 0.08), front_local)
        elif d_type == "awd":
            # 50/50 split
            force_half = force * 0.5
            f_front = max(-max_traction_front, min(max_traction_front, force_half))
            f_rear = max(-max_traction_rear, min(max_traction_rear, force_half))
            body.apply_force_at_local_point(front_dir_local * (f_front / 0.08), front_local)
            body.apply_force_at_local_point(rear_dir_local * (f_rear / 0.08), rear_local)
        else:  # rwd default
            # 100% on rear axle
            f_rear = max(-max_traction_rear, min(max_traction_rear, force))
            body.apply_force_at_local_point(rear_dir_local * (f_rear / 0.08), rear_local)

    def apply_brake_force(self, force: float, dt: float) -> None:
        """Apply a braking force opposing the current velocity.

        Args:
            force: Maximum brake force magnitude in Newtons.
            dt: Delta time of the frame.
        """
        vel = self.body.velocity
        speed = vel.length
        if speed > 0.1:
            # Convert force in Newtons to Pymunk units, then clamp to prevent overshoot
            force_pymunk = force / 0.08
            max_stopping_force = (speed * self.body.mass) / dt
            brake_val = min(force_pymunk, max_stopping_force)
            brake_vec = -vel.normalized() * brake_val
            self.body.apply_force_at_world_point(brake_vec, self.body.position)

    def apply_roll_resistance(self, roll_coeff: float) -> None:
        """Apply rolling resistance force opposing current velocity direction.

        Formula: F = -c_roll * mass * g
        """
        vel = self.body.velocity
        speed = vel.length
        if speed > 0.1:
            # F_roll in Newtons
            f_roll_newtons = roll_coeff * self.body.mass * 9.81
            # Convert to Pymunk units
            f_roll_pymunk = f_roll_newtons / 0.08
            roll_vec = -vel.normalized() * f_roll_pymunk
            self.body.apply_force_at_world_point(roll_vec, self.body.position)

    def apply_lateral_friction(self, grip: float, handbrake: bool, weight_transfer: float, dt: float) -> None:
        """Apply lateral friction at the front and rear axles (Bicycle Model).

        This creates realistic front-axle steering and rear-axle tracking
        with physical yaw rotation and steering drag.
        """
        body = self.body
        mass = body.mass

        # Wheelbase (distance between front and rear axle)
        verts = self.shape.get_vertices()
        xs = [v.x for v in verts]
        length = max(xs) - min(xs) if xs else 80.0
        wheelbase = length * self.wheelbase_ratio  # tunable (Radstand)

        # Local positions of front and rear axles
        front_local = pymunk.Vec2d(wheelbase / 2, 0)
        rear_local = pymunk.Vec2d(-wheelbase / 2, 0)

        # World velocities at the axles
        vel_front = body.velocity_at_local_point(front_local)
        vel_rear = body.velocity_at_local_point(rear_local)

        # Local direction vectors of front and rear wheels
        cos_s = math.cos(self.steer_angle)
        sin_s = math.sin(self.steer_angle)
        
        front_right_local = pymunk.Vec2d(-sin_s, cos_s)
        rear_right_local = pymunk.Vec2d(0, 1)

        # Convert local wheel directions to world vectors
        front_right_world = front_right_local.rotated(body.angle)
        rear_right_world = rear_right_local.rotated(body.angle)

        # Project axle velocities onto lateral unit vectors
        lateral_speed_front = vel_front.dot(front_right_world)
        lateral_speed_rear = vel_rear.dot(rear_right_world)

        # Calculate vehicle slip angle at center of mass
        vel_center = body.velocity
        speed = vel_center.length

        # Grip coefficients per axle (handbrake affects rear axle only)
        front_grip = grip
        rear_grip = grip * 0.3 if handbrake else grip

        # Scale grip with weight transfer to match Phase 3 lateral stability
        grip_scale = 1.0 + weight_transfer
        front_grip *= grip_scale
        rear_grip *= grip_scale

        if speed < 10.0:
            self.slip_angle_deg = 0.0
            effective_grip_front = front_grip
            effective_grip_rear = rear_grip
        else:
            angle = body.angle
            direction = pymunk.Vec2d(math.cos(angle), math.sin(angle))
            forward_speed = vel_center.dot(direction)
            ref_angle = angle if forward_speed >= 0.0 else angle + math.pi
            
            vel_angle = math.atan2(vel_center.y, vel_center.x)
            diff = (vel_angle - ref_angle) % (2.0 * math.pi)
            if diff > math.pi:
                diff -= 2.0 * math.pi
            self.slip_angle_deg = math.degrees(abs(diff))

            # Grip vs slip angle (brush-tyre approximation)
            if self.slip_angle_deg < 15.0:
                effective_grip_front = front_grip
                effective_grip_rear = rear_grip
            elif self.slip_angle_deg < 40.0:
                t = (self.slip_angle_deg - 15.0) / 25.0
                effective_grip_front = front_grip * (1.0 - t * 0.30)
                effective_grip_rear = rear_grip * (1.0 - t * 0.30)
            else:
                effective_grip_front = front_grip * 0.70
                effective_grip_rear = rear_grip * 0.70

        # Damp rotation slightly
        body.angular_velocity *= 0.93

        # Axle mass split for lateral grip. We use the static split here to maintain
        # steering stability for the AI, while the drive force uses dynamic weight transfer.
        front_frac_dyn = max(0.35, min(0.65, 0.5 + self.com_bias))
        rear_frac_dyn = 1.0 - front_frac_dyn

        front_mass_dyn = mass * front_frac_dyn
        rear_mass_dyn = mass * rear_frac_dyn

        # Max lateral impulse per axle using dynamic axle load
        max_impulse_front = effective_grip_front * front_mass_dyn * 380.0 * dt
        max_impulse_rear = effective_grip_rear * rear_mass_dyn * 380.0 * dt

        # Front axle lateral correction (apply in local coordinate space)
        desired_impulse_front = -lateral_speed_front * front_mass_dyn
        applied_impulse_front = min(max_impulse_front, max(-max_impulse_front, desired_impulse_front))
        impulse_front_local = front_right_local * applied_impulse_front
        body.apply_impulse_at_local_point(impulse_front_local, front_local)

        # Rear axle lateral correction (apply in local coordinate space)
        desired_impulse_rear = -lateral_speed_rear * rear_mass_dyn
        applied_impulse_rear = min(max_impulse_rear, max(-max_impulse_rear, desired_impulse_rear))
        impulse_rear_local = rear_right_local * applied_impulse_rear
        body.apply_impulse_at_local_point(impulse_rear_local, rear_local)

        # Determine if drifting
        self.is_drifting = (
            (abs(desired_impulse_front) >= max_impulse_front * 0.98
             or abs(desired_impulse_rear) >= max_impulse_rear * 0.98)
            and speed > 40.0
        )

    def apply_drag(self, cw: float, frontal_area: float = 2.2) -> None:
        """Apply physically-correct aerodynamic drag.

        F = ½ · ρ · cw · A · v²  (v in m/s), then converted to pymunk units by
        /0.08 exactly like the drive/brake/roll forces – previously this used the
        raw ``cw·v_px²`` which was ~9.5× too strong and scale-inconsistent, so
        cars never reached their top speed and couldn't rev out the gears.

        Args:
            cw:            Aerodynamic drag coefficient (~0.27–0.35).
            frontal_area:  Frontal area A in m².
        """
        vel = self.body.velocity
        speed = vel.length  # px/s
        if speed > 0.5:
            v_ms = speed * 0.08              # 0.08 m per px
            f_newtons = 0.5 * 1.2 * cw * frontal_area * v_ms * v_ms  # ρ_air = 1.2
            f_pymunk = f_newtons / 0.08
            self.body.apply_force_at_world_point(-vel.normalized() * f_pymunk, self.body.position)

    def apply_steering(self, steer_val: float, dt: float, is_analog: bool = False) -> None:
        """Update the front wheel steering angle based on steering input.

        Args:
            steer_val: Steering angle rate change in radians (digital) or raw steer input (analog).
            dt: Delta time of the frame.
            is_analog: True if steering is controlled by analog gamepad axis.
        """
        speed = self.body.velocity.length
        lock_factor = 1.0 / (1.0 + (speed / 500.0) ** 1.2)
        max_steer = math.radians(35.0) * lock_factor
        
        if is_analog:
            # Direct analog steering with responsiveness filter
            target_steer = steer_val * max_steer
            responsiveness = 15.0  # Radians per second LERP tracking
            self.steer_angle += (target_steer - self.steer_angle) * responsiveness * dt
            self.steer_angle = max(-max_steer, min(max_steer, self.steer_angle))
        else:
            steer_delta = steer_val
            # Keep steering angle within the speed-dependent lock limits
            self.steer_angle = max(-max_steer, min(max_steer, self.steer_angle))
            
            if abs(steer_delta) > 0.0001:
                # Accumulate steering rate towards the target lock
                self.steer_angle = max(-max_steer, min(max_steer, self.steer_angle + steer_delta))
            else:
                # Self-centering steering when no input is active
                centering_speed = 12.0  # radians per second
                self.steer_angle -= self.steer_angle * centering_speed * dt
                if abs(self.steer_angle) < 0.001:
                    self.steer_angle = 0.0

    # ---- Cleanup ----

    def cleanup(self, space: pymunk.Space) -> None:
        """Remove this body and shape from the pymunk space."""
        if self.shape in space.shapes:
            space.remove(self.shape)
        if self.body in space.bodies:
            space.remove(self.body)
