"""RaceManager – countdown, states, standings, per-vehicle finish times & DNF handling."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any
from src.core.event_bus import EventBus
from src.track.lap_tracker import LapTracker

if TYPE_CHECKING:
    from src.track.track import Track
    from src.entities.vehicle import Vehicle


class RaceManager:
    """Orchestrates a race: countdown → racing → finishing → finished.

    In the `finishing` phase the leader has crossed the last finish line but
    other cars are still driving. Each car that completes its final lap gets
    its finish time recorded and its standings position frozen. After the
    DNF timeout (or all cars finished), the race transitions to `finished`.
    """

    # Once the first car finishes, everyone else gets one more grace window to
    # cross the line: the leader's SLOWEST single lap. On a 3-lap race that is
    # the longest of the leader's three laps; on a 1-lap race it is that lap's
    # time. No absolute cap — the grace is purely the leader's own pace, so a
    # slow field on a slow track still gets a fair, proportional window.
    # Fallback only for the degenerate case of a leader with no recorded lap.
    DNF_FALLBACK_GRACE: float = 60.0

    #: Die letzten Sekunden dieser Frist werden im HUD heruntergezaehlt. Die
    #: Frist selbst bleibt die alte Rechnung - der Countdown sagt nur, wann sie
    #: gleich ablaeuft. Vorher lief sie unsichtbar ab: das Rennen endete fuer
    #: einen Nachzuegler ohne Vorwarnung (Playtest 29.07.2026).
    DNF_COUNTDOWN_SECONDS: float = 5.0

    def __init__(
        self,
        vehicles: list[Vehicle],
        track: Track,
        total_laps: int = 3,
        go_time: float | None = None,
        hold_countdown: bool = False,
        event_bus: EventBus | None = None,
    ) -> None:
        self.vehicles = vehicles
        self.track = track
        self.total_laps = total_laps

        # Online-synced GO: local wall-clock time at which the countdown ends.
        # When set, the countdown is driven by the wall clock instead of dt so
        # all clients hit GO at the same real moment. None → local dt countdown.
        self._go_time = go_time
        # Online: freeze the countdown until every peer has finished loading and
        # the server sends RACE_GO (release_countdown). Prevents the host — whose
        # loading screen eats real time — from losing part of its own countdown.
        self._hold_countdown = hold_countdown

        self.lap_trackers: dict[int, LapTracker] = {
            v.id: LapTracker(v.id, track, v) for v in vehicles
        }

        self.state: str = "countdown"        # countdown | racing | finishing | finished
        self.countdown_timer: float = 3.0
        self.race_time: float = 0.0
        self._standings: list[Vehicle] = list(vehicles)

        # Finish tracking
        self.results: list[dict[str, Any]] = []       # ordered by finish position
        self.finished_ids: set[int] = set()
        self._leader_finish_time: float | None = None
        self._leader_id: int | None = None            # first car to finish (sets the grace window)
        # When set, the online layer overrides the locally computed deadline
        # with a server-authoritative one (race_time value at which the grace
        # window expires). Kept separate so the offline path is unaffected.
        self._forced_deadline: float | None = None

        self._event_bus = event_bus or EventBus()
        self._event_bus.subscribe("checkpoint_crossed", self._on_checkpoint_crossed)
        self._event_bus.subscribe("lap_completed", self._on_lap_completed)

        self._update_standings()

    # ------------------------------------------------------------------
    # Update loop
    # ------------------------------------------------------------------
    def release_countdown(self, seconds: float = 3.5) -> None:
        """Start (or restart) the countdown now — called on the server's RACE_GO
        once all peers finished loading, so every client counts down in sync."""
        self._hold_countdown = False
        self._go_time = None
        self.state = "countdown"
        self.countdown_timer = seconds

    def adopt_vehicle(self, vehicle, lap: int = 1, waypoint_progress: float = 0.0,
                      elapsed: float = 0.0) -> None:
        """Take over a vehicle mid-race with a pre-set lap progress.

        Used when the online host inherits the car of a player that dropped out:
        the replacement must continue from the lap and waypoint the human had
        reached, otherwise it would restart at lap 1 and skew the result.
        """
        if vehicle.id in self.lap_trackers:
            return
        self.vehicles.append(vehicle)
        tracker = LapTracker(vehicle.id, self.track, vehicle)
        tracker.current_lap = max(1, int(lap))
        tracker.waypoint_progress = float(waypoint_progress)
        tracker.current_lap_time = max(0.0, float(elapsed))
        tracker.next_checkpoint_idx = self._checkpoint_after(waypoint_progress)
        self.lap_trackers[vehicle.id] = tracker
        self._update_standings()

    def _checkpoint_after(self, waypoint_progress: float) -> int:
        """Which checkpoint index is a vehicle at *waypoint_progress* heading for?

        Checkpoints are a subset of the track's waypoints, so the two indices
        run on completely different scales — a lap has dozens of waypoints but
        only a handful of checkpoints. Counting how many checkpoint waypoints
        lie at or before the current waypoint gives the one still ahead.
        Getting this wrong is not cosmetic: LapTracker.on_checkpoint_hit()
        ignores every crossing that is not the expected checkpoint, so an
        adopted car would silently stop completing laps.
        """
        waypoints = getattr(self.track, "waypoints", None) or []
        cp_positions = [i for i, w in enumerate(waypoints)
                        if getattr(w, "is_checkpoint", False)]
        if not cp_positions:
            return 1
        passed = sum(1 for i in cp_positions if i <= waypoint_progress)
        return passed % len(cp_positions)

    def update(self, dt: float) -> None:
        if self.state == "countdown":
            if self._hold_countdown:
                return   # waiting for all peers to finish loading (RACE_GO)
            if self._go_time is not None:
                import time
                self.countdown_timer = self._go_time - time.time()
            else:
                self.countdown_timer -= dt
            if self.countdown_timer <= 0:
                self.state = "racing"
                EventBus().emit("race_start")
        elif self.state in ("racing", "finishing"):
            self.race_time += dt
            for tracker in self.lap_trackers.values():
                tracker.update(dt)
            self._update_standings()
            if self.state == "racing":
                self._check_leader_finish()
            else:
                self._check_finishing_timeout()

    # ------------------------------------------------------------------
    # Standings
    # ------------------------------------------------------------------
    def _update_standings(self) -> None:
        """Sort standings by finish rank (if finished), then lap+progress.

        Finished vehicles are frozen in their finish order at the front of
        the list; still-racing vehicles are sorted by (lap, waypoint_progress).
        """
        finished = [v for v in self.vehicles if v.id in self.finished_ids]
        # Preserve finish order (from self.results)
        finish_order = {r["vehicle_id"]: i for i, r in enumerate(self.results)}
        finished.sort(key=lambda v: finish_order.get(v.id, 1e9))

        racing = [v for v in self.vehicles if v.id not in self.finished_ids]
        def _sort_key(v: Vehicle) -> tuple[int, float]:
            t = self.lap_trackers[v.id]
            return (t.current_lap, t.waypoint_progress)
        racing.sort(key=_sort_key, reverse=True)

        self._standings = finished + racing

    def get_position(self, vehicle_id: int) -> int:
        for idx, v in enumerate(self._standings):
            if v.id == vehicle_id:
                return idx + 1
        return -1

    # ------------------------------------------------------------------
    # Finish detection
    # ------------------------------------------------------------------
    def _check_leader_finish(self) -> None:
        """When the first car crosses the final line, switch to `finishing`."""
        if not self.finished_ids:
            return
        self.state = "finishing"

    def leader_slowest_lap(self) -> float | None:
        """The leader's slowest single lap — the grace window after they finish.

        None until a car has finished. Falls back to DNF_FALLBACK_GRACE only if
        the leader somehow finished with no recorded lap times.
        """
        if self._leader_id is None:
            return None
        tracker = self.lap_trackers.get(self._leader_id)
        laps = list(tracker.lap_times) if tracker else []
        return max(laps) if laps else self.DNF_FALLBACK_GRACE

    def dnf_deadline(self) -> float | None:
        """race_time at which still-racing cars become DNF, or None if not set.

        A server-authoritative deadline (online) overrides the locally computed
        one; offline it is the leader's finish time plus their slowest lap.
        """
        if self._forced_deadline is not None:
            return self._forced_deadline
        if self._leader_finish_time is None:
            return None
        grace = self.leader_slowest_lap() or self.DNF_FALLBACK_GRACE
        return self._leader_finish_time + grace

    def sekunden_bis_dnf(self) -> float | None:
        """Restzeit bis zum DNF, oder None wenn nichts anzuzeigen ist.

        Erst in den letzten DNF_COUNTDOWN_SECONDS: die Frist selbst ist
        deutlich laenger, ein Zaehler ueber eine ganze Runde waere keine
        Warnung mehr, sondern Dauerbeschallung.
        """
        if self.state != "finishing":
            return None
        ziel = self.dnf_deadline()
        if ziel is None:
            return None
        rest = ziel - self.race_time
        if rest > self.DNF_COUNTDOWN_SECONDS:
            return None
        return max(0.0, rest)

    def force_deadline(self, race_time_value: float) -> None:
        """Online: pin the DNF deadline to a server-chosen race_time."""
        self._forced_deadline = race_time_value

    def force_finish_remaining(self) -> None:
        """Online FORCE_FINISH: mark every still-racing car DNF and end the race.

        Used when the server's grace window expires — a guest whose local
        manager only holds its own car never reaches the `finishing` phase, so
        the ordinary timeout path cannot fire and this ends the race directly.
        """
        if self.state == "finished":
            return
        for v in list(self._standings):
            if v.id not in self.finished_ids:
                self._record_finish(v, dnf=True)
        self._end_race()

    def _check_finishing_timeout(self) -> None:
        """End the race when all cars finished or the grace window expires."""
        if len(self.finished_ids) >= len(self.vehicles):
            self._end_race()
            return

        deadline = self.dnf_deadline()
        if deadline is None:
            return
        if self.race_time >= deadline:
            # Mark remaining vehicles as DNF in current standings order, so the
            # car that got furthest ranks first among the DNFs.
            for v in list(self._standings):
                if v.id not in self.finished_ids:
                    self._record_finish(v, dnf=True)
            self._end_race()

    def _record_finish(self, vehicle: Vehicle, dnf: bool = False) -> None:
        if vehicle.id in self.finished_ids:
            return
        tracker = self.lap_trackers[vehicle.id]
        cfg = getattr(vehicle, "config", None)
        name = getattr(cfg, "name", f"Car {vehicle.id}") if cfg else f"Car {vehicle.id}"
        result = {
            "vehicle_id": vehicle.id,
            "name": name,
            "position": len(self.results) + 1,
            "finish_time": None if dnf else self.race_time,
            "best_lap": tracker.best_lap_time if tracker.best_lap_time != float("inf") else None,
            "lap_times": list(tracker.lap_times),
            "dnf": dnf,
        }
        self.results.append(result)
        self.finished_ids.add(vehicle.id)
        if self._leader_finish_time is None and not dnf:
            self._leader_finish_time = self.race_time
            self._leader_id = vehicle.id

    def _end_race(self) -> None:
        self.state = "finished"
        EventBus().emit("race_finish", {
            "standings": [v.id for v in self._standings],
            "results": list(self.results),
        })

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    def _on_checkpoint_crossed(self, data: dict[str, Any]) -> None:
        vehicle_id = data.get("vehicle_id")
        checkpoint_idx = data.get("checkpoint_idx")
        if vehicle_id in self.lap_trackers:
            self.lap_trackers[vehicle_id].on_checkpoint_hit(checkpoint_idx)

    def _on_lap_completed(self, data: dict[str, Any]) -> None:
        """Fire once per lap per vehicle. When the vehicle finishes total_laps → record finish."""
        vehicle_id = data.get("vehicle_id")
        lap = data.get("lap", 0)
        # `lap` is the lap that was just completed. Finish when it equals total_laps.
        if lap < self.total_laps:
            return
        if vehicle_id in self.finished_ids:
            return
        vehicle = next((v for v in self.vehicles if v.id == vehicle_id), None)
        if vehicle is None:
            return
        self._record_finish(vehicle)

    # ------------------------------------------------------------------
    def cleanup(self) -> None:
        self._event_bus.unsubscribe("checkpoint_crossed", self._on_checkpoint_crossed)
        self._event_bus.unsubscribe("lap_completed", self._on_lap_completed)
