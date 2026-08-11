"""Fahrzeug-Labor – dev page to tune every vehicle parameter live.

Edit a car's physics (mass, power, top speed, grip, brakes, steering, drag),
its engine (idle / redline / shift points) and its gearbox (per-gear ratios and
speed bands), see the resulting engine torque curve and gear speed bands drawn
live, run an acceleration/top-speed benchmark on demand, and save it all back to
``data/vehicles/<key>.json``.

Entered from the main menu with **V**. Controls on the F1 help / status bar.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from src.states.base_state import BaseState
from src.core import keybindings as kb
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.core import display
from src.ui import theme

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


# Unit conversions come from settings (single source shared with HUD + car select).
from src.core.settings import M_PER_PX, KMH_PER_PXS  # noqa: E402
PS_PER_POWER: float = 0.01           # power:  PS  = engine_power(N) * this (÷100)
_TORQUE_NOMINAL: float = 320.0  # Nm scale used when seeding a table from the formula

_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "drive_type": {
        "title": "Antriebsart",
        "range": "Typen: FWD / RWD / AWD",
        "desc": "Bestimmt, welche Achse die Antriebskraft des Motors auf den Boden überträgt.",
        "low": "FWD (Frontantrieb): Zieht das Fahrzeug. Stabil, neigt aber beim Beschleunigen in Kurven zu Untersteuern (schiebt geradeaus).",
        "high": "RWD (Heckantrieb): Schiebt das Fahrzeug. Agil, erlaubt Leistungsübersteuern (Driften).\nAWD (Allrad): 50:50-Verteilung. Bietet maximale Traktion."
    },
    "mass": {
        "title": "Masse",
        "range": "10.0 - 100000.0 kg",
        "desc": "Das Gesamtgewicht des Fahrzeugs.",
        "low": "Geringes Gewicht verbessert Beschleunigung und Bremsweg massiv und macht das Handling in Kurven extrem agil.",
        "high": "Hohes Gewicht macht das Fahrzeug träge, verlängert Bremswege und erhöht das Risiko, aus der Kurve getragen zu werden."
    },
    "engine_power": {
        "title": "Motorleistung",
        "range": "1.0 - 10000.0 PS (berechnet)",
        "desc": "Die maximale Leistung des Motors (aus der Drehmomentkurve ermittelt).",
        "low": "Niedrige Werte führen zu geringer Zugkraft und langsamer Beschleunigung.",
        "high": "Höhere Werte sorgen für extremen Vortrieb, erfordern aber guten Reifen-Grip, um Wheelspin (Durchdrehen) zu vermeiden."
    },
    "max_speed": {
        "title": "Höchstgeschwindigkeit",
        "range": "1.0 - 10000.0 km/h",
        "desc": "Die von der KI angestrebte Höchstgeschwindigkeit auf gerader Strecke.",
        "low": "Die KI drosselt den Motor frühzeitig ab und fährt insgesamt langsamer.",
        "high": "Ermöglicht dem Fahrzeug, die Leistung auf Geraden voll auszuspielen und die Maximalgeschwindigkeit zu erreichen."
    },
    "grip": {
        "title": "Reifen-Grip (Reibung)",
        "range": "0.01 - 100.0",
        "desc": "Der Haftungsbeiwert der Reifen auf der Fahrbahn.",
        "low": "Sehr rutschig. Das Fahrzeug bricht schnell aus, driftet unkontrolliert und rutscht in die Streckenbegrenzung.",
        "high": "Fahrzeug klebt förmlich auf der Straße. Ermöglicht extreme Kurvengeschwindigkeiten ohne Rutschen."
    },
    "brake_force": {
        "title": "Bremskraft",
        "range": "0.0 - 1000000.0 N",
        "desc": "Die maximale Verzögerungskraft der Bremsanlage.",
        "low": "Fahrzeuge benötigen extrem lange Bremswege und rutschen ungebremst in Kurvenwände.",
        "high": "Kürzeste Bremswege vor Kurven, ermöglicht spätes Bremsen und aggressives Anfahren von Kehren."
    },
    "turn_speed": {
        "title": "Lenkrate",
        "range": "0.01 - 100.0 rad/s",
        "desc": "Die maximale Lenkgeschwindigkeit beim Einschlagen der Räder.",
        "low": "Träges Ansprechverhalten. Das Fahrzeug reagiert spät und steuert unzureichend ein (Untersteuern).",
        "high": "Extrem direkte Lenkung. Fahrzeug lenkt sofort ein, kann bei hohen Geschwindigkeiten aber unruhig wirken."
    },
    "drift_threshold": {
        "title": "Drift-Schwelle",
        "range": "0.01 - 100.0",
        "desc": "Das Geschwindigkeitsverhältnis, ab dem das Fahrzeug in den Gleitreibungs-Modus übergeht.",
        "low": "Reifen verlieren sehr früh die Haftung, was stabiles Fahren erschwert.",
        "high": "Reifen halten die Haftung länger aufrecht, bevor sie ins Rutschen geraten."
    },
    "drag_coefficient": {
        "title": "Luftwiderstand (cW)",
        "range": "0.00 - 100.0",
        "desc": "Der Luftwiderstandsbeiwert der Karosserie.",
        "low": "Fahrzeug gleitet widerstandsarm durch die Luft. Höhere Höchstgeschwindigkeit.",
        "high": "Starker Bremseffekt bei hohen Geschwindigkeiten, der den Motor bei hohem Tempo stark belastet."
    },
    "roll_coefficient": {
        "title": "Rollwiderstand",
        "range": "0.000 - 100.0",
        "desc": "Der mechanische Widerstand der Reifen beim Abrollen.",
        "low": "Fahrzeug rollt fast reibungsfrei weiter, wenn kein Gas gegeben wird.",
        "high": "Permanenter, leichter Bremseffekt, der die Höchstgeschwindigkeit und Effizienz mindert."
    },
    "width_px": {
        "title": "Fahrzeugbreite",
        "range": "0.10 - 100.0 m",
        "desc": "Die physische Breite der Fahrzeugkollisionsbox.",
        "low": "Schmaleres Fahrzeug. Kann enge Passagen leichter durchfahren und Kollisionen besser ausweichen.",
        "high": "Breiteres Fahrzeug. Blockiert die Strecke effektiver, läuft aber Gefahr, an Tunnelwänden anzuecken."
    },
    "height_px": {
        "title": "Fahrzeuglänge",
        "range": "0.10 - 100.0 m",
        "desc": "Die physische Länge der Fahrzeugkollisionsbox.",
        "low": "Kompaktes Fahrzeug. Dreht sich agiler und hat einen geringeren Wendekreis.",
        "high": "Langes Fahrzeug. Stabilisiert die Spur, schwenkt jedoch in Kurven mit dem Heck weiter aus."
    },
    "wheelbase_m": {
        "title": "Radstand",
        "range": "0.10 - 100.0 m",
        "desc": "Der Abstand zwischen den Achsen (wichtig für das physikalische Fahrradmodell).",
        "low": "Erhöht die Agilität und Drehwilligkeit des Fahrzeugs, neigt bei Fahrfehlern jedoch zum Überdrehen.",
        "high": "Beruhigt das Fahrzeug bei hohen Geschwindigkeiten, erfordert aber einen größeren Kurvenradius."
    },
    "wheel_diameter": {
        "title": "Raddurchmesser",
        "range": "0.05 - 50.00 m",
        "desc": "Der Durchmesser der Antriebsräder.",
        "low": "Ermöglicht hohe Motordrehzahlen bei niedrigen Geschwindigkeiten (bessere Beschleunigung aus dem Stand).",
        "high": "Senkt die Motordrehzahl bei hohem Tempo (erhöht die theoretische Endgeschwindigkeit bei gleicher Übersetzung)."
    },
    "com_bias": {
        "title": "Gewichtsverteilung",
        "range": "20:80 bis 80:20 (-0.30 bis 0.30)",
        "desc": "Verlagerung des Schwerpunkts (Vorderachse zu Hinterachse).",
        "low": "Hecklastig. Vorderachse verliert Grip beim Beschleunigen, Heck lenkt agil ein, neigt zum Ausbrechen.",
        "high": "Frontlastig. Höhere Spurtreue beim Beschleunigen, neigt in Kurven jedoch zum Untersteuern."
    },
    "idle_rpm": {
        "title": "Idle-RPM",
        "range": "0.0 - 1000000.0 rpm",
        "desc": "Die Standdrehzahl des Motors.",
        "low": "Motor tourt im Stand sehr weit ab.",
        "high": "Der Motor hält eine hohe Leerlaufdrehzahl, was beim Einkuppeln mehr Drehmoment liefert."
    },
    "redline_rpm": {
        "title": "Redline-RPM",
        "range": "1.0 - 1000000.0 rpm (berechnet)",
        "desc": "Die Maximaldrehzahl des Motors vor dem Eingreifen des Drehzahlbegrenzers.",
        "low": "Geringes nutzbares Drehzahlband, erfordert frühes Hochschalten.",
        "high": "Motor kann extrem hoch gedreht werden, um die Gänge voll auszufahren."
    },
    "button_torque": {
        "title": "Motorkurve bearbeiten",
        "range": "Editor",
        "desc": "Öffnet ein Bearbeitungsfenster für die Drehmomentwerte (Nm) an 10 Stützpunkten über das Drehzahlband.",
        "low": "Erlaubt das Anpassen des Ansprechverhaltens und der Leistungscharakteristik.",
        "high": "Ermöglicht z. B. die Simulation von Elektromotoren (hohes Drehmoment im Keller) oder Rennmotoren."
    },
    "button_gears": {
        "title": "Getriebe bearbeiten",
        "range": "Editor",
        "desc": "Öffnet ein Bearbeitungsfenster für das Getriebe.",
        "low": "Erlaubt das Festlegen der Ganganzahl (1 bis 8) und der Übersetzungsgrenzen.",
        "high": "Ermöglicht feine Abstufungen für Rennstrecken oder lange Gänge für Höchstgeschwindigkeit."
    }
}

# Editable scalar params, all values in DISPLAY units:
#   (attr, label, min, max, step, decimals, unit, factor)   display = internal * factor
_SCALARS: list[tuple[str, str, float, float, float, int, str, float]] = [
    ("mass",             "Masse",            10.0,   100000.0, 10.0, 0, "kg",   1.0),
    ("engine_power",     "Motorleistung (berechnet)", 1.0, 10000.0, 5.0, 0, "PS",   PS_PER_POWER),
    ("max_speed",        "Höchstgeschwindigkeit", 1.0, 10000.0, 5.0, 0, "km/h", KMH_PER_PXS),
    ("grip",             "Grip (Reibung mu)", 0.01,  100.0,  0.01, 2, "",     1.0),
    ("brake_force",      "Bremskraft",       0.0,    1000000.0, 100.0, 0, "N", 1.0),
    ("turn_speed",       "Lenkrate",         0.01,   100.0,  0.05, 2, "rad/s", 1.0),
    ("drift_threshold",  "Drift-Schwelle",   0.01,   100.0,  0.02, 2, "",     1.0),
    ("drag_coefficient", "Luftwiderstand (cW)",0.00,   100.0,  0.01, 2, "",     1.0),
    ("roll_coefficient", "Rollwiderstand",    0.000,  100.0,  0.001, 3, "",    1.0),
    ("width_px",         "Breite (Fahrzeugbreite)", 0.10, 100.0, 0.05, 2, "m",   M_PER_PX),
    ("height_px",        "Länge (Fahrzeuglänge)", 0.10, 100.0, 0.05, 2, "m",   M_PER_PX),
    ("wheelbase_m",      "Radstand",         0.10,   100.0,  0.05, 2, "m",    1.0),
    ("wheel_diameter",   "Raddurchmesser",   0.05,   50.00,  0.01, 2, "m",     1.0),
    ("com_bias",         "Gewichtsverteilung", -0.30, 0.30, 0.01, 2, "", 1.0),
    ("idle_rpm",         "Leerlauf-RPM",     0.0,    1000000.0, 50.0, 0, "rpm", 1.0),
    ("redline_rpm",      "Redline-RPM (berechnet)", 1.0, 1000000.0, 100.0, 0, "rpm", 1.0),
]


class VehicleLabState(BaseState):
    """Interactive editor for vehicle configurations."""

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self._fonts: dict[str, pygame.font.Font] = {}
        self.keys: list[str] = []
        self.veh_index: int = 0
        self.sel: int = 0            # index into the flat editable-item list
        self._scroll: int = 0        # first visible item row
        self.show_help: bool = False
        self.status: str = ""
        self.dirty: bool = False
        self._bench: dict[str, Any] | None = None
        self._bench_job: dict[str, Any] | None = None  # incremental benchmark state
        self._active_overlay: str | None = None  # "torque" | "gears" | None
        self._overlay_inputs: list[dict[str, Any]] = []
        self._overlay_sel: int = 0
        self._overlay_status: str = ""
        #: Sichtbare Seite: "physik" (der bisherige Inhalt) oder "lack".
        self.seite: str = "physik"
        self._lack = None                        # LackLabor, lazy
        self._klang = None                       # KlangLabor, lazy
        self._reiter_rects: list[tuple[str, pygame.Rect]] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def enter(self, **kwargs) -> None:
        from src.entities.vehicle_factory import VehicleFactory
        if not VehicleFactory.get_all_keys():
            VehicleFactory.load_all_configs("data/vehicles")
        self.keys = sorted(VehicleFactory.get_all_keys())
        want = kwargs.get("vehicle_config")
        self.veh_index = self.keys.index(want) if want in self.keys else 0
        self.sel = 0
        self._scroll = 0
        self.status = ""
        self.dirty = False
        self._bench = None
        self._bench_job = None
        self._active_overlay = None
        self._overlay_inputs = []
        self._overlay_sel = 0
        self._overlay_status = ""
        self.seite = kwargs.get("seite", "physik")
        if self._lack is None:
            from src.states.lack_labor import LackLabor
            self._lack = LackLabor(self)
        self._lack._signatur = None
        if self._klang is None:
            from src.states.klang_labor import KlangLabor
            self._klang = KlangLabor(self)
        self._klang._signatur = None
        self._fonts = {
            "title": theme.font(46),
            "head": theme.font(32),
            "body": theme.font(26),
            "small": theme.font(22),
        }
        pygame.key.set_repeat(250, 30)
        self._update_derived_values()

    def exit(self) -> None:
        pygame.key.set_repeat()
        # Sonst laeuft der Motor weiter, waehrend man schon wieder im Menue steht.
        if self._klang is not None:
            self._klang.beenden()

    # ------------------------------------------------------------------
    # Current config + editable-item model
    # ------------------------------------------------------------------

    @property
    def _key(self) -> str:
        return self.keys[self.veh_index] if self.keys else ""

    def _cfg(self):
        from src.entities.vehicle_factory import VehicleFactory
        return VehicleFactory.get_config(self._key)

    def _fahrzeug_wechseln(self, d: int) -> None:
        """Naechstes/vorheriges Fahrzeug. Ausgelagert, weil die Lackier-Seite
        denselben Weg ueber ihre Stepper geht."""
        if not self.keys:
            return
        self.veh_index = (self.veh_index + d) % len(self.keys)
        self.sel = 0
        self._bench = None
        self._update_derived_values()
        if self._lack is not None:
            self._lack._signatur = None
        if self._klang is not None:
            self._klang._signatur = None

    def _verwerfen(self) -> None:
        """Ungespeicherte Aenderungen wegwerfen — laedt die Datei neu.

        Ohne das gibt es auf der Lackier-Seite keinen Weg zurueck: man verstellt
        acht Regler, sieht dass es schlechter ist, und muesste sich die alten
        Werte gemerkt haben.
        """
        from src.entities.vehicle_factory import VehicleFactory
        VehicleFactory.load_all_configs("data/vehicles")
        from src.core import lack as _lack
        _lack.cache_leeren()
        from src.core import motorklang as _mk
        _mk.neu_laden()
        if self._klang is not None:
            self._klang._signatur = None
            self._klang.werte_uebernehmen()
        self.dirty = False
        self.status = "Verworfen — Werte aus der Datei"
        self._update_derived_values()
        if self._lack is not None:
            self._lack._signatur = None

    def _update_derived_values(self) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        # Ensure wheel diameter has a default if missing
        if not hasattr(cfg, "wheel_diameter") or cfg.wheel_diameter is None:
            cfg.wheel_diameter = 0.65
        table = self._ensure_torque(cfg)
        if table:
            table.sort(key=lambda pt: pt[0])
            cfg.redline_rpm = max(pt[0] for pt in table)
            cfg.idle_rpm = min(pt[0] for pt in table)
            max_p = max(pt[0] * pt[1] / 70.235 for pt in table)
            cfg.engine_power = round(max_p, 1)


    def _ensure_torque(self, cfg) -> list[list[float]]:
        """Return the car's torque table, seeding one from the formula if absent."""
        if cfg.torque_curve:
            return cfg.torque_curve
        idle, red = cfg.idle_rpm, cfg.redline_rpm
        table = []
        for i in range(6):
            rpm = idle + (red - idle) * i / 5.0
            nm = self._formula_factor(cfg, rpm) * _TORQUE_NOMINAL
            table.append([round(rpm, 0), round(nm, 0)])
        cfg.torque_curve = table
        return table

    def _items(self) -> list[tuple[str, Any]]:
        """Flat list: scalars, and the two edit buttons."""
        items: list[tuple[str, Any]] = [("choice", ("drive_type", "Antriebsart", ["fwd", "rwd", "awd"]))]
        items.extend([("scalar", s) for s in _SCALARS])
        items.append(("button_torque", "Motorkurve bearbeiten..."))
        items.append(("button_gears", "Getriebeübersetzung bearbeiten..."))
        return items

    def _adjust(self, direction: int) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        items = self._items()
        if not items:
            return
        # Clamp selection index to avoid out of bounds
        self.sel = max(0, min(self.sel, len(items) - 1))
        kind, data = items[self.sel]
        if kind == "scalar":
            attr, _lbl, lo, hi, step, _dec, _u, factor = data
            # derived or measured params are read-only:
            if attr in ("engine_power", "redline_rpm"):
                return
            # Edit happens in display units; store back in internal units.
            internal = getattr(cfg, attr) + direction * (step / factor)
            internal = max(lo / factor, min(hi / factor, internal))
            if attr in ("width_px", "height_px"):
                internal = round(internal)
            setattr(cfg, attr, round(internal, 4))
            self.dirty = True
            self._bench = None  # stale after an edit
        elif kind == "choice":
            attr, _lbl, options = data
            current = getattr(cfg, attr, "rwd")
            if current not in options:
                current = "rwd"
            idx = options.index(current)
            new_idx = (idx + direction) % len(options)
            setattr(cfg, attr, options[new_idx])
            self.dirty = True
            self._bench = None
        elif kind == "button_torque" and direction == 1:
            self._open_overlay("torque")
        elif kind == "button_gears" and direction == 1:
            self._open_overlay("gears")

    # ------------------------------------------------------------------
    # Save + benchmark
    # ------------------------------------------------------------------

    def _save(self) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        path = Path("data/vehicles") / f"{self._key}.json"
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            existing = {}
        existing.update({
            "name": cfg.name,
            "description": cfg.description,
            "visual_type": cfg.visual_type,
            "width_px": int(cfg.width_px),
            "height_px": int(cfg.height_px),
            "color_primary": list(cfg.color_primary),
            "color_secondary": list(cfg.color_secondary),
            "gear_ratios": [round(r, 3) for r in cfg.gear_ratios],
            "torque_curve": [[round(p[0], 0), round(p[1], 0)] for p in (cfg.torque_curve or [])],
            "physics": {
                "mass": cfg.mass, "engine_power": self._compute_power_from_curve(cfg),
                "max_speed": cfg.max_speed, "grip": cfg.grip,
                "brake_force": cfg.brake_force, "turn_speed": cfg.turn_speed,
                "drift_threshold": cfg.drift_threshold,
                "drag_coefficient": cfg.drag_coefficient,
                "roll_coefficient": cfg.roll_coefficient,
                "wheelbase": round(cfg.wheelbase_m, 3),
                "wheelbase_ratio": round(cfg.wheelbase_m / (cfg.height_px * 0.08), 3),
                "com_bias": round(cfg.com_bias, 3),
                "wheel_diameter": round(cfg.wheel_diameter, 3),
                "idle_rpm": cfg.idle_rpm, "redline_rpm": cfg.redline_rpm,
                "drive_type": getattr(cfg, "drive_type", "rwd"),
            },
        })
        # Maskenwerte der Lackierung. Nur schreiben, wenn abgestimmt — ein
        # paint-Block mit verfahren "aus" ist dasselbe wie keiner, und ein
        # leerer Block in 15 Dateien waere nur Rauschen im Diff.
        paint = getattr(cfg, "paint", None)
        if isinstance(paint, dict) and paint.get("verfahren", "aus") != "aus":
            existing["paint"] = paint
        else:
            existing.pop("paint", None)
        # Die zwei Klangwerte dieses Fahrzeugs (§C5/C8). Wie beim Lack nur
        # schreiben, wenn sie von der Vorgabe abweichen — sonst stuenden in
        # 15 Dateien zwei Zeilen, die nichts aussagen.
        # Gelesen wird der Block "klang" (vehicle.py:218) — genau dorthin muss
        # er auch zurueck. Als flache Schluessel geschrieben waeren sie beim
        # naechsten Laden unsichtbar und die Abstimmung waere still verloren.
        tonhoehe = float(getattr(cfg, "klang_tonhoehe", 1.0))
        faerbung = float(getattr(cfg, "klang_faerbung", 0.0))
        if abs(tonhoehe - 1.0) > 1e-6 or abs(faerbung) > 1e-6:
            existing["klang"] = {"tonhoehe": round(tonhoehe, 3),
                                 "faerbung": round(faerbung, 3)}
        else:
            existing.pop("klang", None)
        try:
            path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
            self.dirty = False
            self.status = f"Gespeichert: {path.name}"
            # Umgefaerbte Sprites im Speicher stammen aus den alten Werten.
            from src.core import lack as _lack
            _lack.cache_leeren()
            if self._lack is not None:
                self._lack._signatur = None
            # Die Werte des Motortyps liegen in einer eigenen Datei — sie
            # gelten fuer alle Fahrzeuge dieser Bauart, nicht nur fuer dieses.
            from src.core import motorklang as _mk
            _mk.speichern()
            if self._klang is not None:
                self._klang._signatur = None
        except Exception as exc:
            self.status = f"Speichern fehlgeschlagen: {exc}"

    _BENCH_CHUNK = 150       # physics steps advanced per frame (no game freeze)
    _BENCH_MAX_ACCEL = 60 * 90

    @staticmethod
    def _compute_power_from_curve(cfg) -> float:
        """Compute engine_power (internal scale) from the torque curve, or fall back."""
        tc = cfg.torque_curve
        if tc:
            import math as _m
            max_pw = 0.0
            for rpm_val, nm_val in tc:
                if rpm_val > 0:
                    pw = nm_val * (rpm_val * 2.0 * _m.pi / 60.0)
                    if pw > max_pw:
                        max_pw = pw
            if max_pw > 0:
                return max_pw / 7.355
        return cfg.engine_power

    def _start_benchmark(self) -> None:
        """Kick off an incremental headless run (advanced in update() → no freeze)."""
        cfg = self._cfg()
        if cfg is None or self._bench_job is not None:
            return
        from src.physics.physics_world import PhysicsWorld
        from src.entities.vehicle import Vehicle
        w = PhysicsWorld()
        v = Vehicle(1, cfg, (0.0, 0.0), 0.0, w.space)
        self._bench_job = {
            "w": w, "v": v, "phase": "accel", "frame": 0,
            "t100": None, "t150": None, "top": 0.0, "bx": None, "progress": 0.0,
            "thr100": 100.0 / KMH_PER_PXS, "thr150": 150.0 / KMH_PER_PXS,
        }
        self._bench = None
        self.status = "Benchmark läuft…"

    def _step_benchmark(self) -> None:
        job = self._bench_job
        if not job:
            return
        w, v, dt = job["w"], job["v"], 1.0 / 60.0
        for _ in range(self._BENCH_CHUNK):
            if job["phase"] == "accel":
                v.throttle = 1.0; v.brake_input = 0.0; v.steer_input = 0.0
                v.update(dt); w.step(dt); job["frame"] += 1
                s = v.speed
                if job["t100"] is None and s >= job["thr100"]:
                    job["t100"] = job["frame"] * dt
                if job["t150"] is None and s >= job["thr150"]:
                    job["t150"] = job["frame"] * dt
                job["top"] = max(job["top"], s)
                job["progress"] = min(0.7, job["frame"] / self._BENCH_MAX_ACCEL * 0.7)
                if (job["top"] - s > 3.0 and job["frame"] > 120) or job["frame"] >= self._BENCH_MAX_ACCEL:
                    job["phase"] = "brake"
            else:  # brake from top speed down to standstill
                v.throttle = 0.0; v.brake_input = 1.0; v.steer_input = 0.0
                v.update(dt); w.step(dt)
                s = v.speed
                if job["bx"] is None and s <= job["thr100"]:
                    job["bx"] = v.physics.body.position.x
                if job["bx"] is not None:
                    job["progress"] = 0.7 + 0.3 * (1.0 - min(1.0, s / max(1.0, job["thr100"])))
                if s < 5.0:
                    bx = job["bx"] if job["bx"] is not None else v.physics.body.position.x
                    dist = abs(v.physics.body.position.x - bx)
                    
                    cfg = self._cfg()
                    self._bench = {"t100": job["t100"], "t150": job["t150"],
                                   "top": job["top"] * KMH_PER_PXS, "brake": dist * M_PER_PX}
                    v.cleanup(w.space)
                    self._bench_job = None
                    self.status = "Benchmark fertig. Leistungswerte aktualisiert."
                    return

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    _REITER = [("physik", "PHYSIK"), ("torque", "MOTORKURVE"),
               ("gears", "GETRIEBE"), ("lack", "LACKIERUNG"), ("klang", "KLANG")]

    def _reiter_klick(self, pos) -> bool:
        for name, r in self._reiter_rects:
            if not r.collidepoint(pos):
                continue
            if name in ("torque", "gears"):
                # Motorkurve und Getriebe sind Overlays, keine eigenen Seiten —
                # der Reiter oeffnet sie, damit die Leiste nicht luegt.
                self._open_overlay(name)
            else:
                if self.seite == "klang" and name != "klang" and self._klang is not None:
                    # Wer den Reiter verlaesst, will den Motor nicht weiter hoeren.
                    self._klang.beenden()
                self.seite = name
                if name == "lack" and self._lack is not None:
                    self._lack._signatur = None
                if name == "klang" and self._klang is not None:
                    self._klang._signatur = None
            return True
        return False

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        # Reiterleiste liegt ueber allem ausser einem offenen Overlay.
        from src.core import sfx as _sfx
        if self._active_overlay is None:
            for event in events:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    vorher = _sfx.klang_zaehler()
                    if self._reiter_klick(event.pos):
                        _sfx.klick_quittieren(event, vorher)
                        return

        if self.seite == "klang":
            for event in events:
                vorher = _sfx.klang_zaehler()
                if self._klang is not None and self._klang.handle_event(event):
                    # Die Laborseiten haben ihre eigenen Reglerflaechen und
                    # laufen an der FocusGroup vorbei (gemeldet 03.08.2026).
                    _sfx.klick_quittieren(event, vorher, "verstellt")
                    continue
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    # Eine Ebene, ein Schritt — wie beim Lack-Reiter.
                    if self._klang is not None:
                        self._klang.beenden()
                    self.seite = "physik"
                    return
                elif event.key in (pygame.K_TAB, pygame.K_RIGHTBRACKET):
                    self._fahrzeug_wechseln(+1)
                elif event.key == pygame.K_LEFTBRACKET:
                    self._fahrzeug_wechseln(-1)
                elif event.key == pygame.K_s:
                    self._save()
                elif event.key == pygame.K_F1:
                    self.show_help = not self.show_help
            return

        if self.seite == "lack":
            for event in events:
                vorher = _sfx.klang_zaehler()
                if self._lack is not None and self._lack.handle_event(event):
                    _sfx.klick_quittieren(event, vorher, "verstellt")
                    continue
                if event.type != pygame.KEYDOWN:
                    continue
                if event.key == pygame.K_ESCAPE:
                    # Der Lack-Reiter ist eine Ebene fuer sich: zurueck geht es
                    # erst auf die Physik-Seite, nicht gleich aus dem Labor
                    # heraus (gemeldet 02.08.2026).
                    self.seite = "physik"
                    return
                elif event.key in (pygame.K_TAB, pygame.K_RIGHTBRACKET):
                    self._fahrzeug_wechseln(+1)
                elif event.key == pygame.K_LEFTBRACKET:
                    self._fahrzeug_wechseln(-1)
                elif event.key == pygame.K_s:
                    self._save()
                elif event.key == pygame.K_F1:
                    self.show_help = not self.show_help
            return

        # Route to overlay if active
        if self._active_overlay is not None:
            # Check mouse clicks first
            for event in events:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for idx, inp in enumerate(self._overlay_inputs):
                        box_rect = inp.get("rect")
                        if box_rect and box_rect.collidepoint(event.pos):
                            self._overlay_sel = idx
                            break
                elif event.type == pygame.KEYDOWN:
                    self._handle_overlay_event(event)
            return

        for event in events:
            if event.type != pygame.KEYDOWN:
                continue
            k = event.key
            n = max(1, len(self._items()))
            if k == pygame.K_ESCAPE:
                # Dorthin zurueck, wo das Labor geoeffnet wurde — in der Regel
                # die Einstellungen, Kategorie Entwickler.
                self.state_machine.zurueck()
                return
            elif k in (pygame.K_TAB, pygame.K_RIGHTBRACKET):
                self._fahrzeug_wechseln(+1)
            elif k == pygame.K_LEFTBRACKET:
                self._fahrzeug_wechseln(-1)
            # Arrow keys only, so the rebindable driving keys stay free for other
            # actions (e.g. S = save even when brake is bound to S).
            elif k == pygame.K_UP:
                self.sel = (self.sel - 1) % n
            elif k == pygame.K_DOWN:
                self.sel = (self.sel + 1) % n
            elif k in (pygame.K_LEFT, pygame.K_a, kb.get("left")):
                self._adjust(-1)
            elif k in (pygame.K_RIGHT, pygame.K_d, kb.get("right")):
                # Clamp selection index to avoid out of bounds
                items = self._items()
                self.sel = max(0, min(self.sel, len(items) - 1))
                kind, data = items[self.sel]
                if kind in ("button_torque", "button_gears"):
                    self._open_overlay("torque" if kind == "button_torque" else "gears")
                else:
                    self._adjust(+1)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                # Clamp selection index to avoid out of bounds
                items = self._items()
                self.sel = max(0, min(self.sel, len(items) - 1))
                kind, data = items[self.sel]
                if kind == "button_torque":
                    self._open_overlay("torque")
                elif kind == "button_gears":
                    self._open_overlay("gears")
            elif k == pygame.K_b:
                self._start_benchmark()
            elif k == pygame.K_s:
                self._save()
            elif k == pygame.K_F1:
                self.show_help = not self.show_help

    def update(self, dt: float) -> None:
        self._step_benchmark()
        if self.seite == "klang" and self._klang is not None:
            self._klang.update(dt)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, screen: pygame.Surface) -> None:
        screen.fill((14, 15, 24))
        cfg = self._cfg()
        title = f"FAHRZEUG-LABOR — {cfg.name if cfg else '?'}  ({self._key})"
        screen.blit(self._fonts["title"].render(title, True, (255, 180, 0)), (40, 24))
        dirty = "  ·  *ungespeichert*" if self.dirty else ""
        seitenname = {"lack": "LACKIERUNG", "klang": "KLANG"}.get(self.seite, "PHYSIK")
        zusatz = ""
        if self.seite == "klang" and self._klang is not None:
            zusatz = f"  ·  Motor {self._klang.motor()}"
        sub = (f"{seitenname}  ·  Fahrzeug {self.veh_index + 1} / "
               f"{len(self.keys)}{zusatz}{dirty}")
        screen.blit(self._fonts["small"].render(sub, True, (170, 175, 190)), (44, 66))

        self._draw_reiter(screen)

        if self.seite == "klang":
            if self._klang is not None:
                self._klang.draw(screen, pygame.Rect(40, 110, SCREEN_WIDTH - 80,
                                                     SCREEN_HEIGHT - 150))
            self._draw_status(screen)
            if self.show_help:
                self._draw_help(screen)
            return

        if self.seite == "lack":
            if self._lack is not None:
                self._lack.draw(screen, pygame.Rect(40, 110, SCREEN_WIDTH - 80,
                                                    SCREEN_HEIGHT - 150))
            self._draw_status(screen)
            if self.show_help:
                self._draw_help(screen)
            return

        self._draw_params(screen)
        self._draw_engine_curve(screen)
        self._draw_gears(screen)
        self._draw_bench(screen)
        self._draw_status(screen)
        if self.show_help:
            self._draw_help(screen)

        if self._active_overlay is not None:
            self._draw_overlay(screen)

    def _draw_reiter(self, screen: pygame.Surface) -> None:
        self._reiter_rects = []
        breite, hoehe, luecke = 158, 42, 8
        gesamt = len(self._REITER) * breite + (len(self._REITER) - 1) * luecke
        x = SCREEN_WIDTH - 40 - gesamt
        for name, label in self._REITER:
            r = pygame.Rect(x, 28, breite, hoehe)
            self._reiter_rects.append((name, r))
            aktiv = (name == self.seite)
            hover = r.collidepoint(display.mouse_pos())
            pygame.draw.rect(screen, (58, 48, 20) if aktiv else
                             ((36, 40, 52) if hover else (24, 27, 36)), r, border_radius=5)
            pygame.draw.rect(screen, theme.ACCENT if aktiv else
                             (theme.BORDER_LIGHT if hover else theme.BORDER), r,
                             2 if aktiv else 1, border_radius=5)
            theme.text_fit(screen, label, theme.SMALL,
                           theme.TEXT if (aktiv or hover) else theme.TEXT_FAINT,
                           r.inflate(-10, -8), center=True)
            x += breite + luecke

    def _panel(self, screen, rect, alpha=190) -> None:
        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        surf.fill((10, 12, 22, alpha))
        screen.blit(surf, rect.topleft)
        pygame.draw.rect(screen, (60, 80, 120), rect, 1)

    def _item_text(self, cfg, kind, data) -> tuple[str, str]:
        if kind == "scalar":
            attr, lbl, lo, hi, step, dec, unit, factor = data

            if attr == "com_bias":
                front = int(round((0.5 + getattr(cfg, attr)) * 100.0))
                rear = 100 - front
                return lbl, f"{front}:{rear}"

            val = getattr(cfg, attr) * factor
            return lbl, f"{val:.{dec}f} {unit}".strip()
        if kind == "choice":
            attr, lbl, _opts = data
            val = getattr(cfg, attr, "rwd").upper()
            return lbl, val
        if kind == "button_torque":
            return "Motorkurve bearbeiten...", ">>"
        if kind == "button_gears":
            return "Getriebeübersetzung bearbeiten...", ">>"
        return "?", ""

    def _draw_wrapped_text(self, screen: pygame.Surface, text: str, font, color, rect: pygame.Rect) -> None:
        """Helper to draw text with automatic word wrapping within a rect."""
        x, y = rect.topleft
        max_w = rect.width
        lines = text.split('\n')
        for raw_line in lines:
            words = raw_line.split(' ')
            space_w, _ = font.size(' ')
            line = []
            line_w = 0
            for word in words:
                w, h = font.size(word)
                if line_w + w > max_w:
                    if line:
                        screen.blit(font.render(' '.join(line), True, color), (x, y))
                        y += h + 2
                    line = [word]
                    line_w = w
                else:
                    line.append(word)
                    line_w += w + space_w
            if line:
                _, h = font.size(' '.join(line))
                screen.blit(font.render(' '.join(line), True, color), (x, y))
                y += h + 5
        return y

    def _draw_params(self, screen: pygame.Surface) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        rect = pygame.Rect(40, 100, 640, 900)
        self._panel(screen, rect)
        items = self._items()
        row_h = 25
        # Limit visible list rows to leave space for tooltips at the bottom
        max_rows = 16
        # keep the selection inside the visible window (scroll)
        if self.sel < self._scroll:
            self._scroll = self.sel
        elif self.sel >= self._scroll + max_rows:
            self._scroll = self.sel - max_rows + 1
        self._scroll = max(0, min(self._scroll, max(0, len(items) - max_rows)))

        x, y = rect.x + 20, rect.y + 14
        # drawvisible rows
        for idx in range(self._scroll, min(len(items), self._scroll + max_rows)):
            kind, data = items[idx]
            sel = (idx == self.sel)
            lbl, vs = self._item_text(cfg, kind, data)
            col = (255, 220, 120) if sel else (205, 210, 220)
            marker = f"{theme.ZEIGER} " if sel else "  "
            screen.blit(self._fonts["body"].render(f"{marker}{lbl}", True, col), (x, y))
            vsurf = self._fonts["body"].render(vs, True, col)
            screen.blit(vsurf, vsurf.get_rect(topright=(rect.right - 18, y)))
            y += row_h

        # draw scroll indicator if needed
        if len(items) > max_rows:
            info = f"{self.sel + 1}/{len(items)}  (scrollbar)"
            screen.blit(self._fonts["small"].render(info, True, (120, 130, 150)),
                        (x, rect.y + 14 + max_rows * row_h + 10))

        # Separator line
        pygame.draw.line(screen, (50, 70, 100), (rect.x + 20, rect.y + 440), (rect.right - 20, rect.y + 440), 1)

        # Mouse hover detection for tooltips
        m_x, m_y = display.mouse_pos()
        hovered_idx = -1
        if rect.x <= m_x <= rect.right and rect.y + 14 <= m_y <= rect.y + 14 + max_rows * row_h:
            row_under_mouse = (m_y - (rect.y + 14)) // row_h
            if 0 <= row_under_mouse < min(len(items) - self._scroll, max_rows):
                hovered_idx = self._scroll + row_under_mouse

        active_idx = self.sel
        active_idx = max(0, min(active_idx, len(items) - 1))

        # Get active item attribute key
        kind, data = items[active_idx]
        if kind == "scalar":
            attr = data[0]
        elif kind == "choice":
            attr = data[0]
        elif kind == "button_torque":
            attr = "button_torque"
        elif kind == "button_gears":
            attr = "button_gears"
        else:
            attr = ""

        # Draw Tooltip description
        if attr in _DESCRIPTIONS:
            info = _DESCRIPTIONS[attr]
            tx = rect.x + 20
            ty = rect.y + 460
            
            # Title
            title_surf = self._fonts["head"].render(info["title"], True, (255, 180, 0))
            screen.blit(title_surf, (tx, ty))
            
            # Range / Type
            range_surf = self._fonts["small"].render(info["range"], True, (0, 200, 220))
            screen.blit(range_surf, (rect.right - range_surf.get_width() - 20, ty + 6))
            ty += 32
            
            # Description
            desc_rect = pygame.Rect(tx, ty, rect.width - 40, 200)
            ty = self._draw_wrapped_text(screen, info["desc"], self._fonts["body"], (230, 235, 245), desc_rect) + 16

            # Low/High effects
            effect_rect = pygame.Rect(tx, ty, rect.width - 40, 250)
            low_high_text = f"Niedrigere Werte:\n{info['low']}\n\nHöhere Werte:\n{info['high']}"
            if attr == "drive_type":
                low_high_text = f"Effekte der Antriebsarten:\n{info['low']}\n{info['high']}"
            elif attr in ("button_torque", "button_gears"):
                low_high_text = f"Zweck:\n{info['low']}\n\nFlexibilität:\n{info['high']}"
            self._draw_wrapped_text(screen, low_high_text, self._fonts["small"], (170, 180, 195), effect_rect)

    def _formula_factor(self, cfg, rpm: float) -> float:
        idle, red = cfg.idle_rpm, cfg.redline_rpm
        if len(cfg.gear_ratios) == 1:  # electric
            flat = idle + (red - idle) * 0.4
            if rpm < flat:
                return 1.0
            return max(0.0, 1.0 - 0.65 * ((rpm - flat) / max(1.0, red - flat)))
        peak = idle + (red - idle) * 0.75
        band = red - idle
        tf = 1.0 - ((rpm - peak) / (band * 0.7)) ** 2
        return max(0.45, min(1.0, tf))

    def _draw_engine_curve(self, screen: pygame.Surface) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        rect = pygame.Rect(710, 100, 1170, 430)
        self._panel(screen, rect)
        screen.blit(self._fonts["head"].render("Dyno-Diagramm: Drehmoment (Nm) & Leistung (kW)", True, (0, 230, 255)),
                    (rect.x + 20, rect.y + 12))
        gx, gy = rect.x + 70, rect.y + 60
        gw, gh = rect.width - 150, rect.height - 130
        pygame.draw.rect(screen, (30, 35, 50), (gx, gy, gw, gh))
        
        idle, red = cfg.idle_rpm, cfg.redline_rpm
        table = self._ensure_torque(cfg)
        
        # Calculate power (kW) for each point: kW = rpm * Nm / 9549.3
        kw_table = [(rpm, rpm * nm / 9549.3) for rpm, nm in table]
        
        nm_max = max((p[1] for p in table), default=1.0) or 1.0
        nm_axis = max(100.0, math.ceil(nm_max / 100.0) * 100.0)
        
        kw_max = max((p[1] for p in kw_table), default=1.0) or 1.0
        kw_axis = max(50.0, math.ceil(kw_max / 50.0) * 50.0)
        
        # Gridlines with double Y-axis labels
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            yy = gy + gh - gh * frac
            pygame.draw.line(screen, (45, 50, 68), (gx, yy), (gx + gw, yy), 1)
            # Left: Nm (Cyan)
            screen.blit(self._fonts["small"].render(f"{frac*nm_axis:.0f}", True, (0, 200, 220)),
                        (gx - 52, yy - 10))
            # Right: kW (Orange)
            screen.blit(self._fonts["small"].render(f"{frac*kw_axis:.0f}", True, (255, 120, 0)),
                        (gx + gw + 12, yy - 10))
                        
        screen.blit(self._fonts["small"].render("Nm", True, (0, 200, 220)), (gx - 52, gy - 22))
        screen.blit(self._fonts["small"].render("kW", True, (255, 120, 0)), (gx + gw + 12, gy - 22))

        def _rpm_x(rpm):
            return gx + gw * (max(0.0, min(1.0, (rpm - idle) / (red - idle))) if red > idle else 0.0)

        # Draw Torque Curve (Cyan)
        spts = sorted(table)
        t_line = [(_rpm_x(r), gy + gh - gh * min(1.0, nm / nm_axis)) for r, nm in spts]
        if len(t_line) >= 2:
            pygame.draw.lines(screen, (0, 230, 255), False, t_line, 3)
            
        # Draw Power Curve (Orange)
        spts_kw = sorted(kw_table)
        p_line = [(_rpm_x(r), gy + gh - gh * min(1.0, kw / kw_axis)) for r, kw in spts_kw]
        if len(p_line) >= 2:
            pygame.draw.lines(screen, (255, 120, 0), False, p_line, 3)
            
        # Highlight points
        items = self._items()
        self.sel = max(0, min(self.sel, len(items) - 1)) if items else 0
        sel_kind, sel_data = items[self.sel] if items else ("", None)
        overlay_hot_idx = -1
        if self._active_overlay == "torque":
            overlay_hot_idx = self._overlay_sel // 2

        for i, (r, nm) in enumerate(table):
            px = _rpm_x(r)
            # Draw circle on torque curve
            py_t = gy + gh - gh * min(1.0, nm / nm_axis)
            # Draw circle on power curve
            kw_val = r * nm / 9549.3
            py_p = gy + gh - gh * min(1.0, kw_val / kw_axis)
            
            hot = (sel_kind in ("torque_rpm", "torque_nm") and sel_data == i) or (overlay_hot_idx == i)
            # Torque marker
            pygame.draw.circle(screen, (255, 200, 60) if hot else (0, 230, 255), (int(px), int(py_t)), 5, 0 if hot else 1)
            # Power marker
            pygame.draw.circle(screen, (255, 200, 60) if hot else (255, 120, 0), (int(px), int(py_p)), 5, 0 if hot else 1)
            
        # markers: shift-up + redline
        def _vline(rpm, color, label):
            if red <= idle:
                return
            fx = gx + gw * max(0.0, min(1.0, (rpm - idle) / (red - idle)))
            pygame.draw.line(screen, color, (fx, gy), (fx, gy + gh), 1)
            screen.blit(self._fonts["small"].render(label, True, color), (fx - 16, gy + gh + 6))
        _vline(red, (240, 80, 80), "red")
        screen.blit(self._fonts["small"].render(f"{idle:.0f} rpm", True, (120, 130, 150)),
                    (gx - 10, gy + gh + 6))
        screen.blit(self._fonts["small"].render(f"{red:.0f} rpm", True, (120, 130, 150)),
                    (gx + gw - 60, gy + gh + 24))

    def _draw_gears(self, screen: pygame.Surface) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        rect = pygame.Rect(710, 545, 1170, 250)
        self._panel(screen, rect)
        screen.blit(self._fonts["head"].render("Getriebe-Diagramm: Motordrehzahl über Fahrgeschwindigkeit", True, (0, 230, 255)),
                    (rect.x + 20, rect.y + 10))
                    
        gx, gy = rect.x + 70, rect.y + 45
        gw, gh = rect.width - 150, rect.height - 90
        pygame.draw.rect(screen, (22, 26, 38), (gx, gy, gw, gh))
        
        ratios = cfg.gear_ratios or [3.5, 2.0, 1.5, 1.2, 1.0]
        red = cfg.redline_rpm
        wheel_d = getattr(cfg, "wheel_diameter", 0.65)
        
        v_max_gears = [(red * math.pi * wheel_d * 3.6) / (60.0 * max(0.001, r)) for r in ratios]
        v_max_axis = max(100.0, math.ceil(max(v_max_gears) / 50.0) * 50.0)
        
        # Gridlines Y (RPM)
        for frac in (0.0, 0.5, 1.0):
            yy = gy + gh - gh * frac
            pygame.draw.line(screen, (40, 44, 60), (gx, yy), (gx + gw, yy), 1)
            lbl = self._fonts["small"].render(f"{frac*red:.0f}", True, (150, 150, 160))
            screen.blit(lbl, (gx - 46, yy - 8))
        screen.blit(self._fonts["small"].render("RPM", True, (0, 230, 255)), (gx - 46, gy - 20))
        
        # Gridlines X (Speed)
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            xx = gx + gw * frac
            pygame.draw.line(screen, (40, 44, 60), (xx, gy), (xx, gy + gh), 1)
            lbl = self._fonts["small"].render(f"{frac*v_max_axis:.0f}", True, (150, 150, 160))
            screen.blit(lbl, (xx - 14, gy + gh + 6))
        screen.blit(self._fonts["small"].render("km/h", True, (120, 130, 150)), (gx + gw + 10, gy + gh + 6))
        
        # Draw diagonal lines
        colors = [(90, 160, 240), (90, 200, 130), (230, 190, 60), (230, 120, 90),
                  (180, 110, 220), (90, 210, 210), (240, 140, 180), (150, 150, 150)]
                  
        overlay_hot_idx = -1
        if self._active_overlay == "gears":
            overlay_hot_idx = self._overlay_sel
            
        for idx, ratio in enumerate(ratios):
            v_max_gear = v_max_gears[idx]
            x0, y0 = gx, gy + gh
            
            if v_max_gear > v_max_axis:
                clip_ratio = v_max_axis / v_max_gear
                x1 = gx + gw
                y1 = gy + gh - gh * clip_ratio
            else:
                x1 = gx + gw * (v_max_gear / v_max_axis)
                y1 = gy
                
            is_hot = (overlay_hot_idx == idx)
            color = (255, 200, 60) if is_hot else colors[idx % len(colors)]
            thickness = 3 if is_hot else 2
            
            pygame.draw.line(screen, color, (x0, y0), (int(x1), int(y1)), thickness)
            
            lbl_x = min(max(gx + 4, int(x1) - 30), gx + gw - 95)
            lbl_y = gy + 4 + (idx % 3) * 15
            screen.blit(self._fonts["small"].render(f"G{idx+1} (i={ratio:.2f})", True, color), (int(lbl_x), int(lbl_y)))

    def _draw_bench(self, screen: pygame.Surface) -> None:
        rect = pygame.Rect(710, 810, 1170, 150)
        self._panel(screen, rect)
        screen.blit(self._fonts["head"].render("Benchmark  (B = messen)", True, (120, 255, 160)),
                    (rect.x + 20, rect.y + 12))
        x, y = rect.x + 24, rect.y + 54
        # Running: draw a progress bar (computation is spread over frames).
        if self._bench_job is not None:
            prog = self._bench_job.get("progress", 0.0)
            bar = pygame.Rect(x, y, rect.width - 48, 26)
            pygame.draw.rect(screen, (30, 40, 35), bar, border_radius=4)
            fill = pygame.Rect(x, y, int((rect.width - 48) * prog), 26)
            pygame.draw.rect(screen, (80, 220, 130), fill, border_radius=4)
            screen.blit(self._fonts["small"].render(f"Berechne… {prog*100:.0f} %", True, (220, 255, 230)),
                        (x + 8, y + 36))
            return
        b = self._bench
        if not b:
            screen.blit(self._fonts["body"].render("Noch nicht gemessen — B drücken.", True, (180, 185, 200)), (x, y))
            return
        def fmt(v, unit, dec=1):
            return f"{v:.{dec}f}{unit}" if v is not None else "—"
        cols = [
            f"0→100 km/h: {fmt(b['t100'],'s')}",
            f"0→150 km/h: {fmt(b['t150'],'s')}",
            f"Topspeed: {fmt(b['top'],' km/h',0)}",
            f"Bremsweg 100→0: {fmt(b['brake'],' m')}",
        ]
        for i, c in enumerate(cols):
            screen.blit(self._fonts["body"].render(c, True, (210, 230, 215)),
                        (x + (i % 2) * 560, y + (i // 2) * 34))

    def _draw_status(self, screen: pygame.Surface) -> None:
        rect = pygame.Rect(0, SCREEN_HEIGHT - 40, SCREEN_WIDTH, 40)
        self._panel(screen, rect, alpha=210)
        # Auf der Lackier-Seite ist jede Bedienung als Stepper oder Knopf
        # sichtbar — eine Tastenliste waere doppelt, und "B Benchmark" gilt dort
        # ohnehin nicht.
        if self.seite == "lack":
            left = "ESC zurück"
        elif self.seite == "klang":
            # Leertaste ist der einzige Griff, der nicht als Knopf dasteht.
            left = "Leertaste hören / anhalten   ·   ESC zurück"
        else:
            left = ("F1 Hilfe | ↑↓ wählen | ←→ ändern | TAB Fahrzeug | "
                    "B Benchmark | S Speichern | ESC Menü")
        screen.blit(self._fonts["small"].render(left, True, (180, 185, 200)), (16, rect.y + 10))
        if self.status:
            ts = self._fonts["small"].render(self.status, True, (120, 255, 160))
            screen.blit(ts, ts.get_rect(topright=(SCREEN_WIDTH - 16, rect.y + 10)))

    def _draw_help(self, screen: pygame.Surface) -> None:
        rect = pygame.Rect(SCREEN_WIDTH // 2 - 300, 200, 600, 430)
        self._panel(screen, rect, alpha=238)
        x, y = rect.x + 30, rect.y + 24
        screen.blit(self._fonts["title"].render("FAHRZEUG-LABOR", True, (255, 180, 0)), (x, y))
        y += 54
        rows = [
            ("↑ / ↓", "Parameter/Editor wählen"),
            ("← / →", "Wert ändern (halten = schnell)"),
            ("TAB / [ ]", "Fahrzeug wechseln"),
            ("ENTER", "Editor öffnen (Getriebe/Kurve)"),
            ("B", "Benchmark messen (läuft im Hintergrund)"),
            ("S", "In JSON speichern"),
            ("F1", "Diese Hilfe"),
            ("ESC", "Zurück zum Menü"),
        ]
        for keys, desc in rows:
            screen.blit(self._fonts["body"].render(keys, True, (255, 220, 120)), (x, y))
            screen.blit(self._fonts["body"].render(desc, True, (210, 215, 225)), (x + 150, y))
            y += 34

    def _open_overlay(self, mode: str) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
        self._active_overlay = mode
        self._overlay_status = ""
        self._overlay_sel = 0
        self._overlay_inputs = []

        if mode == "torque":
            curve = self._ensure_torque(cfg)
            for i in range(10):
                if i < len(curve):
                    rpm_val = str(int(curve[i][0]))
                    nm_val = str(int(curve[i][1]))
                else:
                    rpm_val = ""
                    nm_val = ""
                
                self._overlay_inputs.append({
                    "type": "torque_rpm",
                    "row": i,
                    "col": 0,
                    "text": rpm_val,
                    "rect": None
                })
                self._overlay_inputs.append({
                    "type": "torque_nm",
                    "row": i,
                    "col": 1,
                    "text": nm_val,
                    "rect": None
                })
        elif mode == "gears":
            self._overlay_inputs.append({
                "type": "gear_num_gears",
                "row": 0,
                "col": 0,
                "text": str(getattr(cfg, "num_gears", 5)),
                "rect": None
            })
            self._overlay_inputs.append({
                "type": "gear_i_max",
                "row": 1,
                "col": 0,
                "text": f"{getattr(cfg, 'gear_i_max', 3.5):.2f}",
                "rect": None
            })
            self._overlay_inputs.append({
                "type": "gear_i_min",
                "row": 2,
                "col": 0,
                "text": f"{getattr(cfg, 'gear_i_min', 0.8):.2f}",
                "rect": None
            })

    def _handle_overlay_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        
        k = event.key
        
        # Close without saving
        if k == pygame.K_ESCAPE:
            self._active_overlay = None
            return
            
        # Save and apply (S key)
        if k == pygame.K_s:
            self._overlay_save()
            return
            
        num_fields = len(self._overlay_inputs)
        if not num_fields:
            return

        if k in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
            if self._active_overlay == "torque":
                self._overlay_sel = (self._overlay_sel - 2) % num_fields
            else:
                self._overlay_sel = (self._overlay_sel - 1) % num_fields
        elif k in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
            if self._active_overlay == "torque":
                self._overlay_sel = (self._overlay_sel + 2) % num_fields
            else:
                self._overlay_sel = (self._overlay_sel + 1) % num_fields
        elif k in (pygame.K_LEFT, pygame.K_RIGHT, kb.get("left"), kb.get("right")):
            if self._active_overlay == "torque":
                self._overlay_sel = self._overlay_sel ^ 1
        elif k in (pygame.K_TAB, pygame.K_RETURN, pygame.K_KP_ENTER):
            self._overlay_sel = (self._overlay_sel + 1) % num_fields
        elif k == pygame.K_BACKSPACE:
            field = self._overlay_inputs[self._overlay_sel]
            field["text"] = field["text"][:-1]
        elif k in (pygame.K_PERIOD, pygame.K_KP_PERIOD, pygame.K_COMMA):
            field = self._overlay_inputs[self._overlay_sel]
            if field["type"] != "gear_num_gears" and "." not in field["text"]:
                field["text"] += "."
        elif getattr(event, "unicode", "").isdigit():
            field = self._overlay_inputs[self._overlay_sel]
            max_len = 1 if field["type"] == "gear_num_gears" else 6
            if len(field["text"]) < max_len:
                field["text"] += event.unicode

    def _overlay_save(self) -> None:
        cfg = self._cfg()
        if cfg is None or self._active_overlay is None:
            return
            
        if self._active_overlay == "torque":
            parsed_rows = []
            for r in range(10):
                x_str = self._overlay_inputs[2 * r]["text"].strip()
                y_str = self._overlay_inputs[2 * r + 1]["text"].strip()
                
                if not x_str and not y_str:
                    continue
                    
                if not x_str or not y_str:
                    self._overlay_status = f"Fehler in Zeile {r+1}: Beide Spalten müssen gefüllt sein!"
                    return
                    
                try:
                    x_val = float(x_str)
                    y_val = float(y_str)
                except ValueError:
                    self._overlay_status = f"Fehler in Zeile {r+1}: Ungültige Zahl eingegeben!"
                    return
                    
                parsed_rows.append((x_val, y_val))
            
            if len(parsed_rows) < 2:
                self._overlay_status = "Fehler: Mindestens 2 Punkte werden benötigt!"
                return
            parsed_rows.sort(key=lambda pt: pt[0])
            cfg.torque_curve = [[round(pt[0], 0), round(pt[1], 0)] for pt in parsed_rows]
            self._update_derived_values()
            
        elif self._active_overlay == "gears":
            num_gears_str = self._overlay_inputs[0]["text"].strip()
            i_max_str = self._overlay_inputs[1]["text"].strip()
            i_min_str = self._overlay_inputs[2]["text"].strip()
            
            if not num_gears_str or not i_max_str or not i_min_str:
                self._overlay_status = "Fehler: Alle Felder müssen ausgefüllt sein!"
                return
                
            try:
                num_gears = int(num_gears_str)
                i_max = float(i_max_str)
                i_min = float(i_min_str)
            except ValueError:
                self._overlay_status = "Fehler: Ungültige Zahlenwerte!"
                return
                
            if num_gears < 1 or num_gears > 8:
                self._overlay_status = "Fehler: Anzahl der Gänge muss zwischen 1 und 8 liegen!"
                return
            if i_max <= 0.0 or i_min <= 0.0:
                self._overlay_status = "Fehler: Übersetzungen müssen größer als 0 sein!"
                return
            if num_gears > 1 and i_max <= i_min:
                self._overlay_status = "Fehler: 1. Gang (i_max) muss größer als Top-Gang (i_min) sein!"
                return
                
            cfg.num_gears = num_gears
            cfg.gear_i_max = i_max
            cfg.gear_i_min = i_min
            
            # Generate gear ratios geometrically
            if num_gears > 1:
                cfg.gear_ratios = [round(i_max * (i_min / i_max) ** (i / (num_gears - 1)), 3) for i in range(num_gears)]
            else:
                cfg.gear_ratios = [i_min]
                
            self._update_derived_values()

        self.dirty = True
        self._bench = None
        self.status = "Editor-Änderungen übernommen."
        self._active_overlay = None

    def _draw_overlay(self, screen: pygame.Surface) -> None:
        cfg = self._cfg()
        if cfg is None:
            return
            
        # Transparent backdrop
        bg = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
        bg.fill((10, 10, 15, 200))
        screen.blit(bg, (0, 0))

        # Wide Modal panel
        rect = pygame.Rect(SCREEN_WIDTH // 2 - 580, SCREEN_HEIGHT // 2 - 320, 1160, 640)
        self._panel(screen, rect, alpha=245)

        # Title
        if self._active_overlay == "torque":
            title = "MOTORKURVE EINGEBEN (Max. 10 Punkte)"
            col0_lbl = "Drehzahl / RPM (X)"
            col1_lbl = "Drehmoment / Nm (Y)"
        else:
            title = "GETRIEBEÜBERSETZUNGEN BERECHNEN (Spreizung)"
            col0_lbl = ""
            col1_lbl = ""

        screen.blit(self._fonts["title"].render(title, True, (0, 230, 255)), (rect.x + 40, rect.y + 24))

        # Column headers
        if self._active_overlay == "torque":
            screen.blit(self._fonts["head"].render(col0_lbl, True, (170, 180, 200)), (rect.x + 70, rect.y + 80))
            screen.blit(self._fonts["head"].render(col1_lbl, True, (170, 180, 200)), (rect.x + 300, rect.y + 80))

        # Table rows or parameters
        if self._active_overlay == "torque":
            start_y = rect.y + 120
            row_h = 36
            for r in range(10):
                ry = start_y + r * row_h
                
                # Row label
                lbl = f"P{r+1}:"
                screen.blit(self._fonts["body"].render(lbl, True, (140, 150, 170)), (rect.x + 30, ry + 4))

                for c in (0, 1):
                    idx = 2 * r + c
                    inp = self._overlay_inputs[idx]
                    rx = rect.x + 70 if c == 0 else rect.x + 300
                    width_box = 210
                    
                    box_rect = pygame.Rect(rx, ry, width_box, 30)
                    inp["rect"] = box_rect
                    
                    # Active box highlight
                    is_active = (idx == self._overlay_sel)
                    border_color = (255, 200, 60) if is_active else (60, 80, 120)
                    box_bg_color = (20, 24, 38) if is_active else (14, 16, 26)
                    
                    pygame.draw.rect(screen, box_bg_color, box_rect)
                    pygame.draw.rect(screen, border_color, box_rect, 1)

                    # Cursor blinking
                    text_to_draw = inp["text"]
                    if is_active and (pygame.time.get_ticks() // 500) % 2 == 0:
                        text_to_draw += "_"

                    surf = self._fonts["body"].render(text_to_draw, True, (255, 255, 255) if is_active else (200, 205, 215))
                    screen.blit(surf, (box_rect.x + 10, box_rect.y + 4))
        else: # gears
            # We have only 3 fields. Let's space them nicely
            start_y = rect.y + 160
            row_h = 60
            labels = [
                "Anzahl Gänge (1 - 8)",
                "Übersetzung 1. Gang (i_max)",
                "Übersetzung Top-Gang (i_min)"
            ]
            for r in range(3):
                ry = start_y + r * row_h
                
                # Draw the description label
                lbl_text = labels[r]
                screen.blit(self._fonts["body"].render(lbl_text, True, (170, 180, 200)), (rect.x + 40, ry + 4))
                
                inp = self._overlay_inputs[r]
                rx = rect.x + 340
                width_box = 180
                
                box_rect = pygame.Rect(rx, ry, width_box, 32)
                inp["rect"] = box_rect
                
                # Active box highlight
                is_active = (r == self._overlay_sel)
                border_color = (255, 200, 60) if is_active else (60, 80, 120)
                box_bg_color = (20, 24, 38) if is_active else (14, 16, 26)
                
                pygame.draw.rect(screen, box_bg_color, box_rect)
                pygame.draw.rect(screen, border_color, box_rect, 1)

                # Cursor blinking
                text_to_draw = inp["text"]
                if is_active and (pygame.time.get_ticks() // 500) % 2 == 0:
                    text_to_draw += "_"

                surf = self._fonts["body"].render(text_to_draw, True, (255, 255, 255) if is_active else (200, 205, 215))
                screen.blit(surf, (box_rect.x + 10, box_rect.y + 4))

        # Live graph display on the right
        gx, gy = rect.x + 600, rect.y + 120
        gw, gh = 510, 360
        
        if self._active_overlay == "torque":
            live_table = []
            for r in range(10):
                x_str = self._overlay_inputs[2 * r]["text"].strip()
                y_str = self._overlay_inputs[2 * r + 1]["text"].strip()
                if x_str and y_str:
                    try:
                        live_table.append([float(x_str), float(y_str)])
                    except ValueError:
                        pass
            
            live_table.sort(key=lambda pt: pt[0])
            pygame.draw.rect(screen, (30, 35, 50), (gx, gy, gw, gh))
            
            if len(live_table) >= 2:
                idle = min(pt[0] for pt in live_table)
                red = max(pt[0] for pt in live_table)
                span = red - idle
                
                kw_table = [(rpm, rpm * nm / 9549.3) for rpm, nm in live_table]
                nm_max = max((p[1] for p in live_table), default=1.0) or 1.0
                nm_axis = max(100.0, math.ceil(nm_max / 100.0) * 100.0)
                kw_max = max((p[1] for p in kw_table), default=1.0) or 1.0
                kw_axis = max(50.0, math.ceil(kw_max / 50.0) * 50.0)
                
                # Gridlines
                for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                    yy = gy + gh - gh * frac
                    pygame.draw.line(screen, (45, 50, 68), (gx, yy), (gx + gw, yy), 1)
                    screen.blit(self._fonts["small"].render(f"{frac*nm_axis:.0f}", True, (0, 200, 220)),
                                (gx - 52, yy - 10))
                    screen.blit(self._fonts["small"].render(f"{frac*kw_axis:.0f}", True, (255, 120, 0)),
                                (gx + gw + 12, yy - 10))
                                
                screen.blit(self._fonts["small"].render("Nm", True, (0, 200, 220)), (gx - 52, gy - 22))
                screen.blit(self._fonts["small"].render("kW", True, (255, 120, 0)), (gx + gw + 12, gy - 22))

                def _live_rpm_x(rpm):
                    return gx + gw * (max(0.0, min(1.0, (rpm - idle) / span)) if span > 0.0 else 0.0)

                t_line = [(_live_rpm_x(r), gy + gh - gh * min(1.0, nm / nm_axis)) for r, nm in live_table]
                pygame.draw.lines(screen, (0, 230, 255), False, t_line, 3)
                
                p_line = [(_live_rpm_x(r), gy + gh - gh * min(1.0, kw / kw_axis)) for r, kw in kw_table]
                pygame.draw.lines(screen, (255, 120, 0), False, p_line, 3)
                
                overlay_hot_idx = self._overlay_sel // 2
                for i, (r, nm) in enumerate(live_table):
                    px = _live_rpm_x(r)
                    py_t = gy + gh - gh * min(1.0, nm / nm_axis)
                    py_p = gy + gh - gh * min(1.0, (r * nm / 9549.3) / kw_axis)
                    hot = (overlay_hot_idx == i)
                    pygame.draw.circle(screen, (255, 200, 60) if hot else (0, 230, 255), (int(px), int(py_t)), 5, 0 if hot else 1)
                    pygame.draw.circle(screen, (255, 200, 60) if hot else (255, 120, 0), (int(px), int(py_p)), 5, 0 if hot else 1)
            else:
                lbl = self._fonts["body"].render("Mindestens 2 gültige Zeilen eingeben...", True, (150, 160, 180))
                screen.blit(lbl, (gx + 40, gy + gh // 2 - 10))
                
        elif self._active_overlay == "gears":
            # Live preview from the 3 fields: num_gears, i_max, i_min
            num_gears_str = self._overlay_inputs[0]["text"].strip()
            i_max_str = self._overlay_inputs[1]["text"].strip()
            i_min_str = self._overlay_inputs[2]["text"].strip()
            
            num_gears, i_max, i_min = 0, 0.0, 0.0
            if num_gears_str and i_max_str and i_min_str:
                try:
                    num_gears = int(num_gears_str)
                    i_max = float(i_max_str)
                    i_min = float(i_min_str)
                except ValueError:
                    pass
                    
            pygame.draw.rect(screen, (22, 26, 38), (gx, gy, gw, gh))
            
            if num_gears >= 1 and i_max > 0.0 and i_min > 0.0:
                if num_gears > 1:
                    live_ratios = [i_max * (i_min / i_max) ** (i / (num_gears - 1)) for i in range(num_gears)]
                else:
                    live_ratios = [i_min]
                
                # Sawtooth gear diagram: RPM over Speed (km/h)
                red = cfg.redline_rpm
                wheel_d = getattr(cfg, "wheel_diameter", 0.65)
                # Compute gear speeds: max_speed_kmh = (redline_rpm * pi * d * 3.6) / (60.0 * ratio)
                v_max_gears = [(red * math.pi * wheel_d * 3.6) / (60.0 * max(0.001, r)) for r in live_ratios]
                v_max_axis = max(100.0, math.ceil(max(v_max_gears) / 50.0) * 50.0)
                
                # Gridlines
                # Y-axis (RPM)
                for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                    yy = gy + gh - gh * frac
                    pygame.draw.line(screen, (40, 44, 60), (gx, yy), (gx + gw, yy), 1)
                    lbl = self._fonts["small"].render(f"{frac*red:.0f}", True, (150, 150, 160))
                    screen.blit(lbl, (gx - 46, yy - 8))
                screen.blit(self._fonts["small"].render("RPM", True, (0, 230, 255)), (gx - 46, gy - 20))
                
                # X-axis (Speed km/h)
                for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                    xx = gx + gw * frac
                    pygame.draw.line(screen, (40, 44, 60), (xx, gy), (xx, gy + gh), 1)
                    lbl = self._fonts["small"].render(f"{frac*v_max_axis:.0f}", True, (150, 150, 160))
                    screen.blit(lbl, (xx - 14, gy + gh + 6))
                screen.blit(self._fonts["small"].render("km/h", True, (120, 130, 150)), (gx + gw + 10, gy + gh + 6))
                
                # Draw diagonal lines
                colors = [(90, 160, 240), (90, 200, 130), (230, 190, 60), (230, 120, 90),
                          (180, 110, 220), (90, 210, 210), (240, 140, 180), (150, 150, 150)]
                
                overlay_hot_idx = self._overlay_sel
                for idx, ratio in enumerate(live_ratios):
                    v_max_gear = v_max_gears[idx]
                    x0, y0 = gx, gy + gh
                    
                    if v_max_gear > v_max_axis:
                        clip_ratio = v_max_axis / v_max_gear
                        x1 = gx + gw
                        y1 = gy + gh - gh * clip_ratio
                    else:
                        x1 = gx + gw * (v_max_gear / v_max_axis)
                        y1 = gy
                        
                    is_hot = (overlay_hot_idx == idx or (overlay_hot_idx >= len(live_ratios) and idx == len(live_ratios) - 1))
                    color = (255, 200, 60) if is_hot else colors[idx % len(colors)]
                    thickness = 3 if is_hot else 2
                    
                    pygame.draw.line(screen, color, (x0, y0), (int(x1), int(y1)), thickness)
                    
                    lbl_x = x1 + 4 if v_max_gear <= v_max_axis else x1 - 24
                    lbl_y = y1 - 12 if v_max_gear <= v_max_axis else y1 + 4
                    screen.blit(self._fonts["small"].render(f"G{idx+1}", True, color), (int(lbl_x), int(lbl_y)))
            else:
                lbl = self._fonts["body"].render("Gültige Getriebedaten eingeben...", True, (150, 160, 180))
                screen.blit(lbl, (gx + 40, gy + gh // 2 - 10))

        # Status error label
        if self._overlay_status:
            err_surf = self._fonts["body"].render(self._overlay_status, True, (240, 80, 80))
            screen.blit(err_surf, (rect.x + 40, rect.bottom - 80))

        # Action keys
        actions = "S: Speichern & Schließen     |     ESC: Abbrechen / Schließen"
        act_surf = self._fonts["small"].render(actions, True, (150, 160, 180))
        screen.blit(act_surf, (rect.x + 40, rect.bottom - 40))
