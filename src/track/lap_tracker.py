"""LapTracker class – tracks checkpoints, laps, lap times, best times, and split differences for a vehicle."""
from __future__ import annotations

import math
import pymunk

from src.core.event_bus import EventBus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.track.track import Track
    from src.entities.vehicle import Vehicle


class LapTracker:
    """Tracks the progress, lap count, and lap times of a single vehicle."""

    def __init__(self, vehicle_id: int, track: Track, vehicle: Vehicle) -> None:
        """Initialize the lap tracker.

        Args:
            vehicle_id: ID of the vehicle being tracked.
            track:      The track reference.
            vehicle:    The vehicle reference.
        """
        self.vehicle_id: int = vehicle_id
        self.track: Track = track
        self.vehicle: Vehicle = vehicle

        self.checkpoints = track.get_checkpoints()
        self.num_checkpoints: int = len(self.checkpoints)

        # State
        self.current_lap: int = 1
        self.next_checkpoint_idx: int = 1  # 0 is start/finish; we ignore it at the start and expect checkpoint 1 first
        self.waypoint_progress: float = 0.0

        # Timers
        self.current_lap_time: float = 0.0
        self.last_lap_time: float = 0.0
        self.best_lap_time: float = float("inf")
        self.lap_times: list[float] = []

        # Splits
        self.current_splits: dict[int, float] = {}  # cp_idx -> time in current lap
        self.best_splits: dict[int, float] = {}  # cp_idx -> best ever split time
        self.last_split_info: tuple[float, float] | None = None  # (diff_seconds, display_timer)
        self.last_sector_diff: float | None = None  # difference in current sector time vs best lap sector time

    def update(self, dt: float) -> None:
        """Update lap timer and position progress.

        Args:
            dt: Delta time in seconds.
        """
        self.current_lap_time += dt

        # Update waypoint progress for standings calculation
        pos = self.vehicle.physics.position
        # Find the nearest waypoint index to the vehicle's position
        idx = self.track.get_nearest_waypoint_index(pos)
        self.waypoint_progress = float(idx)

        # Update split display timer if active
        if self.last_split_info:
            diff, display_timer = self.last_split_info
            display_timer -= dt
            if display_timer <= 0:
                self.last_split_info = None
            else:
                self.last_split_info = (diff, display_timer)

    def on_checkpoint_hit(self, checkpoint_idx: int) -> None:
        """Process a checkpoint crossing event.

        Args:
            checkpoint_idx: Index of the checkpoint segment crossed.
        """
        # Validate checkpoint sequence
        if checkpoint_idx != self.next_checkpoint_idx:
            return  # Wrong order or double trigger -> ignore

        # Ensure vehicle is moving forward
        if not self._is_moving_forward():
            return

        # Record split time
        self.current_splits[checkpoint_idx] = self.current_lap_time

        # Calculate difference to best split if available
        split_diff = None
        if checkpoint_idx in self.best_splits:
            split_diff = self.current_lap_time - self.best_splits[checkpoint_idx]
            self.last_split_info = (split_diff, 3.0)  # Show split for 3.0 seconds

        # Calculate sector time for current lap
        current_sector_time = 0.0
        if checkpoint_idx == 1:
            current_sector_time = self.current_lap_time
        elif checkpoint_idx > 1:
            prev_time = self.current_splits.get(checkpoint_idx - 1)
            if prev_time is not None:
                current_sector_time = self.current_lap_time - prev_time
        elif checkpoint_idx == 0:
            prev_time = self.current_splits.get(self.num_checkpoints - 1)
            if prev_time is not None:
                current_sector_time = self.current_lap_time - prev_time

        # Calculate sector time for best lap
        best_sector_time = None
        if checkpoint_idx in self.best_splits:
            if checkpoint_idx == 1:
                best_sector_time = self.best_splits[1]
            elif checkpoint_idx > 1:
                prev_best = self.best_splits.get(checkpoint_idx - 1)
                if prev_best is not None:
                    best_sector_time = self.best_splits[checkpoint_idx] - prev_best
            elif checkpoint_idx == 0:
                prev_best = self.best_splits.get(self.num_checkpoints - 1)
                if prev_best is not None:
                    best_sector_time = self.best_splits[0] - prev_best

        # Compute sector difference
        if best_sector_time is not None and current_sector_time > 0.0:
            self.last_sector_diff = current_sector_time - best_sector_time
        else:
            self.last_sector_diff = None

        # Handle crossing start/finish line (checkpoint 0)
        if checkpoint_idx == 0:
            self._complete_lap()
        else:
            # Advance expected checkpoint index
            self.next_checkpoint_idx = (checkpoint_idx + 1) % self.num_checkpoints

        # Emit checkpoint event for visual overlays or sounds
        EventBus().emit(
            "checkpoint_registered",
            {
                "vehicle_id": self.vehicle_id,
                "checkpoint_idx": checkpoint_idx,
                "split_diff": split_diff,
                "current_lap_time": self.current_lap_time,
            },
        )

    def _complete_lap(self) -> None:
        """Register the completed lap, update timers/records, and advance lap state."""
        self.last_lap_time = self.current_lap_time
        self.lap_times.append(self.last_lap_time)

        is_best = False
        if self.last_lap_time < self.best_lap_time:
            self.best_lap_time = self.last_lap_time
            is_best = True
            # Update best splits reference from the current lap's splits
            for cp_idx, t in self.current_splits.items():
                self.best_splits[cp_idx] = t

        # Emit lap completed event
        EventBus().emit(
            "lap_completed",
            {
                "vehicle_id": self.vehicle_id,
                "lap": self.current_lap,
                "lap_time": self.last_lap_time,
                "is_best": is_best,
            },
        )

        # Advance lap and reset state
        self.current_lap += 1
        self.next_checkpoint_idx = 1
        self.current_lap_time = 0.0
        self.current_splits = {}

    def _is_moving_forward(self) -> bool:
        """Verify the vehicle is moving forward in the direction of the centerline.

        Returns:
            True if speed projection along heading is positive and above threshold.
        """
        body = self.vehicle.physics.body
        vel = body.velocity
        angle = body.angle
        forward = pymunk.Vec2d(math.cos(angle), math.sin(angle))
        
        # Minimum forward speed of 5 px/s (~1.4 km/h) - low enough for hairpins
        return vel.dot(forward) > 5.0
