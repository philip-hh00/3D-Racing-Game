"""Ghost recording, playback, and persistence.

Records vehicle trajectory at 30 Hz during a lap and plays it back by
interpolating positions. Saves ghosts per-track to data/ghosts/<track_key>.json.
"""
from __future__ import annotations

import os
import json
import math
from dataclasses import dataclass, field
import pygame

from src.core.settings import SCREEN_HEIGHT
from src.entities.components.renderer import VehicleRenderer

#: Deckkraft des Ghosts (0…1). 120/255 — der Wert, der vorher gemeint war.
GHOST_DECKKRAFT = 120 / 255


@dataclass
class GhostData:
    lap_time: float = 9999.0
    samples: list[list[float]] = field(default_factory=list)  # list of [t, x, y, a]
    sectors: list[float] = field(default_factory=list)
    driver: str = "Ghost"
    vehicle: str = "rookie"

    def to_dict(self) -> dict:
        return {
            "lap_time": self.lap_time,
            "samples": self.samples,
            "sectors": self.sectors,
            "driver": self.driver,
            "vehicle": self.vehicle
        }

    @classmethod
    def from_dict(cls, d: dict) -> GhostData:
        return cls(
            lap_time=d.get("lap_time", 9999.0),
            samples=d.get("samples", []),
            sectors=d.get("sectors", []),
            driver=d.get("driver", "Ghost"),
            vehicle=d.get("vehicle", "rookie")
        )


def track_key(track_path: str) -> str:
    """Der Ghost-Schluessel zu einem Streckenpfad.

    Eine Stelle, an der aus dem Pfad ein Schluessel wird. Vorher stand dieselbe
    Rechnung zweimal in ``race_state`` — einmal beim Laden, einmal beim
    Erzeugen. Zwei Kopien derselben Regel laufen frueher oder spaeter
    auseinander, und dann wird unter einem Schluessel gespeichert und unter
    einem anderen gesucht.
    """
    name = os.path.basename(str(track_path or "")).replace(".json", "")
    if "custom" in str(track_path or "").lower():
        return f"custom/{name}"
    return name


def _ghost_path(track_key: str) -> str:
    """Ablageort einer Ghost-Runde — im **beschreibbaren** Nutzerverzeichnis.

    Bis zum 04.08.2026 war das ein relativer Pfad. Ein gepacktes macOS-Bundle
    setzt das Arbeitsverzeichnis aber auf ``sys._MEIPASS``, also in das
    schreibgeschützte ``.app``: ``save`` schlug dort fehl und verschluckte den
    Fehler (``except Exception: pass``). Eine gefahrene Bestrunde wurde damit im
    Bündel **nie** als Ghost gespeichert, und niemand konnte es merken. Auf dem
    Entwicklungsrechner fällt es nicht auf, weil Arbeits- und
    Nutzerverzeichnis dasselbe sind.
    """
    from src.core.paths import user_path
    sanitized = track_key.replace("/", "_").replace("\\", "_")
    return user_path("data", "ghosts", f"{sanitized}.json")


def brauchbar(daten: "GhostData | None") -> bool:
    """Ob mit diesen Daten ein Ghost fahren kann.

    Ein Ghost ohne Punkte ist keiner. Das klingt nach einer Selbstverstaend-
    lichkeit und war der Grund fuer einen Fund am 07.08.2026: die Erzeugung
    gibt bei fehlenden Startplaetzen oder einem nicht gebauten Fahrzeug ein
    leeres ``GhostData()`` zurueck, das wurde gespeichert, und ab da meldete
    ``exists()`` einen Ghost, den es nicht gab — nie wieder erzeugt, fuer immer
    kein Ghost auf dieser Strecke.
    """
    return bool(daten is not None and daten.samples)


def exists(track_key: str) -> bool:
    """Ob fuer die Strecke ein **brauchbarer** Ghost abgelegt ist.

    Bewusst nicht nur "Datei da": eine leere Datei aus einer aelteren Fassung
    soll sich von selbst erledigen, sonst haetten die Spieler, die schon eine
    haben, nichts von der Reparatur.
    """
    return brauchbar(load(track_key))


def delete(track_key: str) -> None:
    """Delete the ghost file if it exists."""
    path = _ghost_path(track_key)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except Exception:
            pass


def _signatur(daten: dict) -> str:
    """Signatur ueber den Inhalt ohne das Feld ``sig`` (siehe tresor.signatur).

    Ein Ghost ist eine Bestzeit: wer in der Datei die Rundenzeit verkuerzt,
    haette sonst einen Rekord, den er nie gefahren ist (Release 1.0.0).
    """
    from src.core import tresor
    ohne = {k: v for k, v in daten.items() if k != "sig"}
    return tresor.signatur(json.dumps(ohne, sort_keys=True, ensure_ascii=False).encode("utf-8"))


def load(track_key: str) -> GhostData | None:
    """Load ghost data from file, or return None if it doesn't exist.

    Ohne gueltige Signatur gilt die Datei als nicht vorhanden — ein
    veraenderter Ghost wird dann neu erzeugt bzw. von der naechsten Runde
    ersetzt, statt als Bestzeit zu zaehlen.
    """
    path = _ghost_path(track_key)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        from src.core import tresor
        if not tresor.signatur_pruefen(
                json.dumps({k: v for k, v in data.items() if k != "sig"},
                           sort_keys=True, ensure_ascii=False).encode("utf-8"),
                str(data.get("sig", ""))):
            return None
        daten = GhostData.from_dict(data)
    except Exception:
        return None
    # Eine leere Datei aus einer aelteren Fassung gilt als nicht vorhanden.
    return daten if brauchbar(daten) else None


def save(track_key: str, ghost: GhostData) -> None:
    """Ghost ablegen — aber nur, wenn er etwas taugt.

    Ein leerer Ghost auf der Platte ist schlimmer als keiner: er sieht fuer
    ``exists()`` aus wie einer und verhindert damit jede weitere Erzeugung.
    """
    if not brauchbar(ghost):
        return
    path = _ghost_path(track_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        daten = ghost.to_dict()
        daten["sig"] = _signatur(daten)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(daten, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


class GhostRecorder:
    """Records the trajectory of a vehicle during the current lap."""

    def __init__(self) -> None:
        self.samples: list[list[float]] = []
        self.sectors: list[float] = []
        self._last_t: float = -999.0

    def reset(self) -> None:
        self.samples.clear()
        self.sectors.clear()
        self._last_t = -999.0

    def record(self, t: float, x: float, y: float, angle: float) -> None:
        """Sample the position at 30 Hz (interval of ~0.033s)."""
        if t - self._last_t >= 0.033:
            self.samples.append([round(t, 3), round(x, 1), round(y, 1), round(angle, 4)])
            self._last_t = t

    def record_sector(self, t: float) -> None:
        """Record the timestamp when passing a sector checkpoint."""
        self.sectors.append(round(t, 3))


class GhostPlayer:
    """Interpolates and renders a ghost vehicle."""

    def __init__(self, data: GhostData) -> None:
        self.data = data
        from src.entities.vehicle_factory import VehicleFactory
        cfg = VehicleFactory.get_config(getattr(data, "vehicle", "rookie"))
        w = getattr(cfg, "width_px", 26) if cfg else 26
        h = getattr(cfg, "height_px", 54) if cfg else 54
        vis = getattr(cfg, "visual_type", "rookie") if cfg else "rookie"
        # Grau und durchscheinend, aber in der Silhouette des Rekordhalters
        # (gemeldet 30.07.2026: der Ghost sah aus wie ein normaler Mitfahrer).
        # Beides ging vorher ins Leere: `color_primary` zaehlt nur im
        # programmatischen Rueckfall, und das `set_alpha` beim Zeichnen sass auf
        # `_base_surface`, waehrend `draw()` das PNG aus `_orig_sprite` nimmt.
        # Jetzt stecken Grau und Deckkraft in der Oberflaeche selbst.
        self.renderer = VehicleRenderer(
            width=w,
            height=h,
            color_primary=(140, 142, 150),
            color_secondary=(80, 82, 90),
            visual_type=vis,
            config_key=getattr(data, "vehicle", "rookie"),
            entfaerbt=True,
            deckkraft=GHOST_DECKKRAFT,
        )

    def get_position(self, t: float) -> tuple[float, float, float] | None:
        """Return (x, y, angle) interpolated at time t, or None if out of bounds."""
        samples = self.data.samples
        if not samples:
            return None

        # Clamp/wrap or stop at end
        if t <= samples[0][0]:
            return samples[0][1], samples[0][2], samples[0][3]
        if t >= samples[-1][0]:
            return samples[-1][1], samples[-1][2], samples[-1][3]

        # Binary search for the active interval
        low, high = 0, len(samples) - 1
        while low + 1 < high:
            mid = (low + high) // 2
            if samples[mid][0] < t:
                low = mid
            else:
                high = mid

        s1, s2 = samples[low], samples[high]
        t1, x1, y1, a1 = s1
        t2, x2, y2, a2 = s2

        # Interpolation factor
        denom = t2 - t1
        if denom <= 1e-9:
            # Duplicate timestamps — just return the first sample
            return x1, y1, a1
        f = (t - t1) / denom

        # Linear position interpolation
        x = x1 + f * (x2 - x1)
        y = y1 + f * (y2 - y1)

        # Angular interpolation (proper wrapping)
        dx = (1.0 - f) * math.cos(a1) + f * math.cos(a2)
        dy = (1.0 - f) * math.sin(a1) + f * math.sin(a2)
        angle = math.atan2(dy, dx)

        return x, y, angle

    def draw(self, screen: pygame.Surface, t: float, camera_offset: pygame.Vector2) -> None:
        """Draw the semi-transparent ghost at time t."""
        pos = self.get_position(t)
        if not pos:
            return
        x, y, angle = pos
        self.renderer.draw(screen, (x, y), angle, camera_offset)

    def get_live_diff(self, player_pos: tuple[float, float], player_time: float) -> float | None:
        """Find the time difference (player_time - ghost_time) at the player's spatial location."""
        samples = self.data.samples
        if not samples or len(samples) < 2:
            return None

        px, py = player_pos
        min_d2 = float("inf")
        best_t = None

        # Filter by a time window to prevent crossover/hairpin matching
        t_min = player_time - 15.0
        t_max = player_time + 15.0

        for s in samples:
            t_g = s[0]
            if t_g < t_min or t_g > t_max:
                continue
            gx, gy = s[1], s[2]
            d2 = (px - gx)**2 + (py - gy)**2
            if d2 < min_d2:
                min_d2 = d2
                best_t = t_g

        # Must be reasonably close (within ~150px) to consider it a match
        if best_t is not None and min_d2 < 22500:
            return player_time - best_t
        return None


#: Fahrzeugkennung der Ghost-KI. Hoch genug, dass sie mit keinem Rennteilnehmer
#: kollidiert; aus ihr kommt auch der Zufallskeim der KI-Fehler, die Fahrt ist
#: also bei jedem Aufruf dieselbe.
SEED_KENNUNG = 99

#: Fahrername des KI-Ghosts. Daran erkennt das Rennen, dass es keine
#: Spielerrunde ist (siehe :func:`ist_seed`).
SEED_FAHRER = "Seed-Ghost"


def ist_seed(daten: "GhostData | None") -> bool:
    """Ob dieser Ghost die KI-Runde ist und keine gefahrene Spielerrunde."""
    return bool(daten is not None and daten.driver == SEED_FAHRER)


def generate_seed_ghost(track_path: str, progress_callback=None,
                        start: tuple[tuple[float, float], float] | None = None,
                        vehicle: str | None = None) -> GhostData:
    """Den Erst-Ghost einer Strecke: die KI der Stufe *Meister* faehrt eine Runde.

    Gefahren wird mit der echten Physik und demselben ``AIVehicle`` wie im
    Rennen, aus dem Stand und von derselben Stelle wie der Spieler. Aufgezeichnet
    wird sie als gewoehnlicher Ghost und genauso abgespielt — ohne Koerper in der
    Welt des Rennens, also ohne Kollision, ohne Platz in der Wertung und ohne
    Eintrag als Spielerrekord.

    *start* ist ``((x, y), winkel_rad)`` des Spielers; ohne Angabe der erste
    Startplatz der Strecke. *vehicle* ist der Fahrzeugschluessel (der des
    Spielers, damit der Vergleich fair ist); ohne Angabe ``rookie``.

    Scheitert die Simulation, kommt ein **leeres** ``GhostData`` zurueck: kein
    Ghost ist ehrlicher als ein erfundener. Bis zum 06.10.2026 stand hier ein
    Rueckfall, der die Zeiten aus der Ideallinie rechnete (Einheiten durcheinander,
    Start an Punkt 0 der Ideallinie statt am Startplatz): ein Ghost, der in der
    Streckenmitte losraste und nicht einzuholen war. Ausgeloest wurde er jedes
    Mal — der Rennverwalter der Simulation hoerte die Rundenmeldungen nicht
    (siehe ``LapTracker``), das Rennen wurde nie fertig, und nach dem Zeitlimit
    galt die Simulation als gescheitert.
    """
    import math
    from src.physics.physics_world import PhysicsWorld
    from src.track.track import Track
    from src.entities.vehicle_factory import VehicleFactory
    import numpy as np
    from src.ai.stufen import stufe
    from src.physics.checkpoint import Checkpoint
    from src.physics.collision_handler import CollisionHandler
    from src.core.event_bus import EventBus
    from src.states.race_manager import RaceManager

    physics_world = PhysicsWorld()
    temp_space = physics_world.space
    temp_track = Track(track_path, temp_space)

    # 1. Set up checkpoint sensor shapes
    checkpoints = []
    for idx, cp_wp in enumerate(temp_track.get_checkpoints()):
        center_idx = temp_track.get_nearest_waypoint_index((cp_wp.x, cp_wp.y))
        n_cl = len(temp_track.centerline)
        if n_cl > 1:
            p1 = temp_track.centerline[center_idx % n_cl]
            p2 = temp_track.centerline[(center_idx + 1) % n_cl]
            angle = math.degrees(math.atan2(p2[1] - p1[1], p2[0] - p1[0]))
        else:
            angle = 0.0

        checkpoint = Checkpoint(
            idx=idx,
            x=cp_wp.x,
            y=cp_wp.y,
            angle_deg=angle,
            track_width=temp_track.track_width,
            space=temp_space,
        )
        checkpoints.append(checkpoint)

    def _aufraeumen(ai=None) -> None:
        for cp in checkpoints:
            cp.cleanup()
        if ai is not None:
            ai.cleanup(temp_space)
        physics_world.cleanup()

    # 2. Startpose: die des Spielers, sonst der erste Startplatz
    if start is not None:
        start_pos = (float(start[0][0]), float(start[0][1]))
        start_angle = float(start[1])
    else:
        slots = temp_track.get_start_positions()
        if not slots:
            _aufraeumen()
            return GhostData()
        start_pos, start_angle = slots[0].pos, math.radians(slots[0].angle)

    # Make sure vehicle configs are loaded before using the factory
    VehicleFactory.load_all_configs()
    key = vehicle if vehicle and VehicleFactory.get_config(vehicle) else "rookie"

    ai = VehicleFactory.create_ai_vehicle(
        config_key=key,
        vehicle_id=SEED_KENNUNG,
        start_pos=start_pos,
        start_angle=start_angle,
        space=temp_space,
        track=temp_track,
        difficulty=stufe("expert"),
    )

    if ai is None:
        print("[ghost] WARNING: Could not create AI vehicle – check data/vehicles/rookie.json")
        _aufraeumen()
        return GhostData()

    # Activate AI driving (by default AIVehicle.ai_active=False and brakes are held)
    ai.ai_active = True

    # 3. Fahrplan der KI anlegen (Ladebalken: erste Haelfte)

    # Gemeldet wird nur, wenn sich die **Zahl** aendert. Jeder Aufruf kostet im
    # Spiel ein gezeichnetes Bild und die Wartezeit auf den Bildwechsel; der
    # Balken selbst kann ohnehin nur 100 Stufen zeigen.
    #
    # Gemessen am 07.08.2026 auf einer eigenen Strecke: 6871 Aufrufe fuer eine
    # Erzeugung, die 1,3 s rechnet. Bei 60 Hz sind das 115 Sekunden Warten —
    # die gemeldeten „ca. 2 min Ladezeit" waren praktisch vollstaendig das.
    _zuletzt = [-1]

    def _melden(pct: int) -> None:
        if progress_callback is None:
            return
        pct = max(0, min(100, int(pct)))
        if pct != _zuletzt[0]:
            _zuletzt[0] = pct
            progress_callback(pct)

    _melden(0)
    ai.controller.vorbereiten()
    _melden(50)
    plan = ai.controller.fahrplan

    # 4. Initialize race manager and collision handler
    event_bus = EventBus.create_isolated()
    collision_handler = CollisionHandler(temp_space, event_bus)  # noqa: F841 (haelt die Rueckrufe am Leben)
    race_manager = RaceManager(
        vehicles=[ai],
        track=temp_track,
        total_laps=1,
        event_bus=event_bus,
    )
    # Aus dem Stand, ohne Countdown: die Ghost-Zeit beginnt wie die des Spielers
    # beim Startsignal.
    race_manager.state = "racing"
    race_manager.countdown_timer = 0.0

    recorder = GhostRecorder()
    sim_time = 0.0
    # Obergrenze: die Zeit, die der Fahrplan fuer die Runde erwartet, dreifach,
    # hoechstens drei Minuten.
    expected_lap_time = float(sum(plan.strecke.seg_len / np.maximum(plan.v_ziel, 10.0)))
    max_duration = min(180.0, expected_lap_time * 3.0)

    # Listener for checkpoint times
    def on_cp(data):
        if data.get("vehicle_id") == SEED_KENNUNG:
            recorder.record_sector(sim_time)

    event_bus.subscribe("checkpoint_crossed", on_cp)

    # 5. Run simulation loop
    dt = 1.0 / 60.0
    failed = False
    try:
        # Record the exact starting position sample at t = 0.0
        recorder.record(0.0, ai.body.position.x, ai.body.position.y, ai.body.angle)

        while race_manager.state != "finished" and sim_time < max_duration:
            # AIVehicle.update internally calls controller.compute_inputs when ai_active=True
            ai.update(dt)
            physics_world.step(dt)
            race_manager.update(dt)

            sim_time += dt
            recorder.record(sim_time, ai.body.position.x, ai.body.position.y, ai.body.angle)

            # Remaining 50% of progress bar goes to simulation
            _melden(50 + sim_time * 50 / max_duration)
        # Die Runde ist meist vor der Zeitgrenze fertig: der Balken soll nicht
        # bei dem Anteil stehenbleiben, der zufaellig dort erreicht war.
        _melden(100)
    except Exception:
        import traceback
        print("SEED GHOST SIMULATION FAILED:")
        traceback.print_exc()
        failed = True
    finally:
        event_bus.unsubscribe("checkpoint_crossed", on_cp)
        finished = race_manager.state == "finished"
        lap_time = (race_manager.results[0]["finish_time"]
                    if race_manager.results else sim_time)
        race_manager.cleanup()
        _aufraeumen(ai)

    if failed or not finished or not recorder.samples:
        print("[ghost] WARNING: KI-Ghost nicht fertig geworden - Zeitfahren ohne Ghost")
        return GhostData()

    return GhostData(
        lap_time=float(lap_time),
        samples=[[float(v) for v in s] for s in recorder.samples],
        sectors=[float(t) for t in recorder.sectors],
        driver=SEED_FAHRER,
        vehicle=key,
    )
