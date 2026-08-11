"""Collision handler – wires up pymunk collision callbacks to the EventBus.

Collision types used:
    VEHICLE_COLLISION_TYPE  (1) – any vehicle body
    TRACK_WALL_COLLISION_TYPE (2) – track wall segments
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pymunk

from src.core.settings import VEHICLE_COLLISION_TYPE, TRACK_WALL_COLLISION_TYPE, COLLISION_TYPE_CHECKPOINT

if TYPE_CHECKING:
    from src.core.event_bus import EventBus


class CollisionHandler:
    """Registers pymunk collision callbacks and forwards them as EventBus events.

    Events emitted
    ---------------
    ``"collision_vehicle_wall"``
        Data: ``{"vehicle_body_id": int, "impulse": float}``
    ``"collision_vehicle_vehicle"``
        Data: ``{"body_a_id": int, "body_b_id": int, "impulse": float}``
    """

    def __init__(self, space: pymunk.Space, event_bus: EventBus) -> None:
        """Set up all collision callbacks on *space*.

        Parameters
        ----------
        space:
            The pymunk space to listen for collisions in.
        event_bus:
            The application's event bus for emitting collision events.
        """
        self._space: pymunk.Space = space
        self._event_bus: EventBus = event_bus

        # Vehicle ↔ Wall
        #
        # **Zwei Rückrufe, zwei Aufgaben** (04.08.2026). ``begin`` meldet, DASS
        # berührt wird — daran hängt ``is_touching_wall``. Die Wucht steht dort
        # aber noch nicht fest: ``arbiter.total_impulse`` ist im ``begin``
        # gemessen **0,0** und erst in ``post_solve`` echt (125,0 im Versuch).
        # Mit der Schwelle ``IMPULS_AB = 500`` hat deshalb **nie** ein
        # Aufprallklang gespielt — gemeldet als „Sound im Rennen für Kollision
        # und Reifenquietschen noch nicht vorhanden".
        space.on_collision(
            VEHICLE_COLLISION_TYPE,
            TRACK_WALL_COLLISION_TYPE,
            begin=self._on_vehicle_wall,
            post_solve=self._on_vehicle_wall_impact,
            separate=self._on_vehicle_wall_separate,
        )

        # Vehicle ↔ Vehicle
        space.on_collision(
            VEHICLE_COLLISION_TYPE,
            VEHICLE_COLLISION_TYPE,
            begin=self._on_vehicle_vehicle,
            post_solve=self._on_vehicle_vehicle_impact,
            separate=self._on_vehicle_vehicle_separate,
        )

        # Vehicle ↔ Checkpoint
        space.on_collision(
            VEHICLE_COLLISION_TYPE,
            COLLISION_TYPE_CHECKPOINT,
            begin=self._on_vehicle_checkpoint,
        )

    # ------------------------------------------------------------------
    # Vehicle ↔ Wall
    # ------------------------------------------------------------------

    def _on_vehicle_wall(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> bool:
        """Called when a vehicle starts touching a track wall."""
        impulse: float = arbiter.total_impulse.length

        # Determine which shape is the vehicle
        shape_a, shape_b = arbiter.shapes
        vehicle_shape = (
            shape_a
            if shape_a.collision_type == VEHICLE_COLLISION_TYPE
            else shape_b
        )

        self._event_bus.emit(
            "collision_vehicle_wall",
            {
                "vehicle_body_id": id(vehicle_shape.body),
                "impulse": impulse,
            },
        )
        return True  # let pymunk resolve the collision normally

    def _on_vehicle_wall_impact(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> None:
        """Die Wucht eines Wandtreffers — hier steht sie fest.

        Nur beim **ersten** aufgelösten Schritt einer Berührung
        (``is_first_contact``). ``post_solve`` läuft sonst in jedem Schritt,
        solange man an der Wand schrammt; ein Klang je Schritt wäre ein
        Maschinengewehr. Der erste Schritt trägt genau die Wucht des Einschlags.
        """
        if not arbiter.is_first_contact:
            return
        shape_a, shape_b = arbiter.shapes
        vehicle_shape = (
            shape_a
            if shape_a.collision_type == VEHICLE_COLLISION_TYPE
            else shape_b
        )
        self._event_bus.emit(
            "impact_vehicle_wall",
            {
                "vehicle_body_id": id(vehicle_shape.body),
                "impulse": arbiter.total_impulse.length,
            },
        )

    def _on_vehicle_wall_separate(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> None:
        """Called when a vehicle stops touching a track wall."""
        shape_a, shape_b = arbiter.shapes
        vehicle_shape = (
            shape_a
            if shape_a.collision_type == VEHICLE_COLLISION_TYPE
            else shape_b
        )
        self._event_bus.emit(
            "collision_vehicle_wall_end",
            {
                "vehicle_body_id": id(vehicle_shape.body),
            },
        )

    # ------------------------------------------------------------------
    # Vehicle ↔ Vehicle
    # ------------------------------------------------------------------

    def _on_vehicle_vehicle(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> bool:
        """Called when two vehicles start colliding."""
        from src.core import race_setup
        if race_setup.current().mode == "Zeitfahren":
            return False  # No collisions in Time Trial

        impulse: float = arbiter.total_impulse.length
        shape_a, shape_b = arbiter.shapes

        self._event_bus.emit(
            "collision_vehicle_vehicle",
            {
                "body_a_id": id(shape_a.body),
                "body_b_id": id(shape_b.body),
                "vehicle_a": getattr(shape_a.body, "data", None),
                "vehicle_b": getattr(shape_b.body, "data", None),
                "total_impulse": arbiter.total_impulse,
                "impulse": impulse,
            },
        )
        return True  # let pymunk resolve the collision normally


    def _on_vehicle_vehicle_impact(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> None:
        """Die Wucht einer Fahrzeugberührung — siehe _on_vehicle_wall_impact.

        Hier hängt mehr dran als der Klang: online wird die Wucht an den
        getroffenen Mitspieler weitergegeben, damit sein Auto den Stoß auch
        spürt. Mit der Null aus ``begin`` blieb auch das aus.
        """
        if not arbiter.is_first_contact:
            return
        from src.core import race_setup
        if race_setup.current().mode == "Zeitfahren":
            return
        shape_a, shape_b = arbiter.shapes
        self._event_bus.emit(
            "impact_vehicle_vehicle",
            {
                "body_a_id": id(shape_a.body),
                "body_b_id": id(shape_b.body),
                "vehicle_a": getattr(shape_a.body, "data", None),
                "vehicle_b": getattr(shape_b.body, "data", None),
                "total_impulse": arbiter.total_impulse,
                "impulse": arbiter.total_impulse.length,
            },
        )

    def _on_vehicle_vehicle_separate(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> None:
        """Called when two vehicles stop colliding."""
        pass

    # ------------------------------------------------------------------
    # Vehicle ↔ Checkpoint
    # ------------------------------------------------------------------

    def _on_vehicle_checkpoint(
        self,
        arbiter: pymunk.Arbiter,
        space: pymunk.Space,
        data: dict[str, Any],
    ) -> bool:
        """Called when a vehicle crosses a checkpoint sensor."""
        shape_a, shape_b = arbiter.shapes
        vehicle_shape = (
            shape_a
            if shape_a.collision_type == VEHICLE_COLLISION_TYPE
            else shape_b
        )
        checkpoint_shape = (
            shape_a
            if shape_a.collision_type == COLLISION_TYPE_CHECKPOINT
            else shape_b
        )

        veh_obj = getattr(vehicle_shape.body, "data", None)
        if getattr(veh_obj, "is_remote", False):
            return True   # network ghosts don't advance local lap tracking

        vehicle_id = None
        if veh_obj:
            vehicle_id = getattr(veh_obj, "id", None)

        checkpoint_idx = getattr(checkpoint_shape, "data", None)

        if vehicle_id is not None and checkpoint_idx is not None:
            self._event_bus.emit(
                "checkpoint_crossed",
                {
                    "vehicle_id": vehicle_id,
                    "checkpoint_idx": checkpoint_idx,
                },
            )
        return True
