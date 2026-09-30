"""KI-Fahrer: Taktik → Bahnplaner → Bahnregler.

Je Auto ein :class:`~src.ai.fahrplan.Fahrplan` (einmal, zwischengespeichert).
Alle ``PLAN_INTERVALL`` Sekunden entscheidet die Taktik und plant der Planer
neu, in jedem Bild folgt der Regler der gewählten Bahn. Dazu wie bisher:
Startspur halten, Befreien aus der Wand, Aufholhilfe (nur Anfänger und
Fortgeschritten, siehe ``src/ai/stufen.py``).
"""
from __future__ import annotations

import math

from src.ai.stufen import stufe as _stufe

STUCK_SECONDS: float = 1.5
RECOVERY_BASE_SECONDS: float = 2.2
RECOVERY_MAX_SECONDS: float = 4.0
RUECKWAERTS_GAS: float = 0.7
RECOVERY_NACHLAUF: float = 2.0
GRID_HOLD_SECONDS: float = 3.5
GRID_FADE_SECONDS: float = 1.5
GRID_START_SPEED: float = 20.0
GEGNER_SICHT: float = 1200.0     # px


def normalize_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


class AIController:
    PLAN_INTERVALL = 0.1

    def __init__(self, vehicle, track, difficulty="medium") -> None:
        self.vehicle = vehicle
        self.track = track
        self.difficulty = _stufe(difficulty)
        vehicle.is_analog = True          # Lenkung als Anteil des Einschlags
        self.opponents: list = []
        self.speed_multiplier: float = 1.0
        self.rubber_band: float = 0.0
        self.fahrplan = None
        self.recovery_timer: float = 0.0
        pos = self._position()
        self.dbg_look: tuple[float, float] = pos
        self.dbg_state: str = "frei"
        self.dbg_car_ahead: bool = False
        self.dbg_curve: float = 0.0
        self._hint: int | None = None
        self._bahn = None
        self._plan_timer = 0.0
        self._plan_versatz = 0.0
        self._start_timer = 0.0
        self._start_offset = 0.0
        self._start_measured = False
        self._progress_s: float | None = None
        self._no_progress_timer = 0.0
        self._recovery_attempts = 0
        self._recovery_nachlauf = 0.0
        self._recovery_steer_sign = 1.0

    # -- Aufbau ------------------------------------------------------------
    def vorbereiten(self, fortschritt=None) -> None:
        """Fahrplan und Bausteine anlegen (beim Laden aufrufen; sonst beim ersten Bild)."""
        if self.fahrplan is not None:
            return
        from src.ai.fahrer import Fehlerquelle, persoenlichkeit
        from src.ai.fahrplan import fahrplan_bauen
        from src.ai.planer import Planer
        from src.ai.regler import Bahnregler
        from src.ai.taktik import Taktik
        cfg = self.vehicle.config
        self.fahrplan = fahrplan_bauen(self.track, cfg, self.difficulty)
        seed = int(getattr(self.vehicle, "id", 0) or 0)
        self._pers = persoenlichkeit(seed, self.difficulty)
        self._fehler = Fehlerquelle(seed, self.difficulty, self._pers)
        breite, laenge = float(cfg.width_px), float(cfg.height_px)
        self._planer = Planer(self.fahrplan, breite, laenge)
        self._taktik = Taktik(self.fahrplan, self.difficulty, self._pers, breite, laenge)
        self._regler = Bahnregler(self.vehicle)
        self._plan_versatz = (seed % 6) / 6 * self.PLAN_INTERVALL
        if fortschritt is not None:
            fortschritt(1.0)

    def _position(self) -> tuple[float, float]:
        p = self.vehicle.physics.body.position
        return float(p.x), float(p.y)

    # -- Umgebung ------------------------------------------------------------
    def _gegner(self, pos):
        from src.ai.planer import Gegner
        st = self.fahrplan.strecke
        liste = []
        for car in self.opponents:
            if car is self.vehicle or getattr(car, "bereit", True) is False:
                continue
            try:
                gx, gy = car.position
            except Exception:
                continue
            if math.hypot(gx - pos[0], gy - pos[1]) > GEGNER_SICHT:
                continue
            s, d, _ = st.sd(gx, gy)
            cfg = getattr(car, "config", None)
            liste.append(Gegner(s, d, float(getattr(car, "speed", 0.0) or 0.0),
                                float(getattr(cfg, "height_px", 62.0)),
                                float(getattr(cfg, "width_px", 29.0))))
        return liste

    def _aufholfaktor(self) -> float:
        a = self.difficulty.aufholhilfe
        if a <= 0.0:
            return 1.0
        return 1.0 + a * max(-0.06, min(0.03, 0.1 * self.rubber_band))

    def _startspur(self, d: float, v: float, dt: float) -> float:
        if not self._start_measured:
            self._start_measured = True
            if v < GRID_START_SPEED:
                self._start_offset = d
                self._start_timer = GRID_HOLD_SECONDS + GRID_FADE_SECONDS
        if self._start_timer <= 0.0:
            return 0.0
        self._start_timer -= dt
        fade = (1.0 if self._start_timer > GRID_FADE_SECONDS
                else max(0.0, self._start_timer / GRID_FADE_SECONDS))
        return self._start_offset * fade

    # -- Hauptschleife --------------------------------------------------------
    def compute_inputs(self, dt: float) -> tuple[float, float, float]:
        self.vorbereiten()
        # Jedes Bild: ein übernommenes Spielerauto setzt is_analog aus seiner
        # Eingabequelle zurück.
        self.vehicle.is_analog = True
        plan = self.fahrplan
        st = plan.strecke
        pos = self._position()
        s, d, self._hint = st.sd(pos[0], pos[1], self._hint)
        v = float(self.vehicle.speed)

        if self.recovery_timer > 0.0:
            ergebnis = self._befreien(dt, pos, s)
            if self.recovery_timer <= 0.0:
                # Neu anfahren: der Fortschritt zählt ab hier (das Zurücksetzen
                # kostet sonst Weg, und das nächste Befreien käme zu früh).
                # Dazu eine Gnadenfrist: erst ausrollen, dann anfahren.
                self._progress_s = s
                self._no_progress_timer = -STUCK_SECONDS
            return ergebnis

        startspur = self._startspur(d, v, dt)
        self._plan_timer -= dt
        if self._bahn is None or self._plan_timer <= 0.0:
            self._plan_timer = (self._plan_versatz if self._bahn is None
                                else self.PLAN_INTERVALL)
            gegner = self._gegner(pos)
            w = self._taktik.entscheiden(s, d, v, gegner)
            w.tempo *= self._pers.kurve * self._aufholfaktor()
            w.spaeter_bremsen_px += self._pers.bremspunkt_px
            if startspur:
                w.versatz += startspur - plan.d_bei(s)
            fehler = self._fehler.schritt(self.PLAN_INTERVALL)
            if fehler is not None:
                if fehler.art == "weit":
                    aussen = -1.0 if plan.k_bei(s) >= 0 else 1.0
                    w.versatz += aussen * 0.5 * plan.halb_frei * fehler.staerke
                elif fehler.art == "spaet":
                    w.spaeter_bremsen_px += 80.0 * fehler.staerke
                    w.tempo *= 1.0 + 0.03 * fehler.staerke
                else:
                    w.tempo *= 1.0 - 0.2 * fehler.staerke
            self._bahn = self._planer.planen(s, d, v, gegner, w)
            self.dbg_state = w.zustand
            self.dbg_car_ahead = w.zustand in ("folgen", "windschatten", "angriff")
            self.dbg_curve = plan.k_bei(s)

        steer = self._regler.lenkung(self._bahn.xy, v)
        gas, bremse = self._regler.pedale(v, self._bahn.v_soll * self.speed_multiplier)
        self.dbg_look = self._regler.vorschau
        if getattr(self.vehicle, "signed_speed", 0.0) < -5.0:
            # Nach dem Rückwärtsfahren erst zum Stehen kommen, dann vorwärts:
            # Gas gegen die Rollrichtung verpufft sonst, und der Fortschritts-
            # zähler löst das nächste Befreien aus.
            gas, bremse = 0.0, 1.0
        self._fortschritt(dt, s)
        return gas, bremse, steer

    # -- Festgefahren ---------------------------------------------------------
    def _befreien(self, dt, pos, s):
        self.recovery_timer -= dt
        st = self.fahrplan.strecke
        look = st.xy(s + 100.0, self.fahrplan.d_bei(s + 100.0))
        angle = self.vehicle.physics.body.angle
        diff = normalize_angle(math.atan2(look[1] - pos[1], look[0] - pos[0]) - angle)
        steer = max(-1.0, min(1.0, -diff * 1.6)) * self._recovery_steer_sign
        # Erst vorwärts fahren, wenn die Nase halbwegs zur Strecke zeigt — sonst
        # rammt das Auto sofort wieder die Wand (höchstens ``RECOVERY_NACHLAUF`` länger).
        if self.recovery_timer <= 0.0 and abs(diff) > 0.6 and self._recovery_nachlauf < RECOVERY_NACHLAUF:
            self.recovery_timer = dt
            self._recovery_nachlauf += dt
        self.dbg_state = "befreien"
        self.dbg_look = look
        # Rückwärts herausfahren: Bremse allein bewegt ein stehendes Auto nicht
        # (nur negatives Gas legt den Rückwärtsgang ein).
        return -RUECKWAERTS_GAS, 0.0, steer

    def _fortschritt(self, dt: float, s: float) -> None:
        st = self.fahrplan.strecke
        if self._progress_s is None or st.ds(self._progress_s, s) > 20.0:
            self._progress_s = s
            self._no_progress_timer = 0.0
            self._recovery_attempts = 0
            return
        self._no_progress_timer += dt
        if self._no_progress_timer <= STUCK_SECONDS:
            return
        self._recovery_attempts += 1
        self._no_progress_timer = 0.0
        if self._recovery_attempts >= 3:
            ziel = st.xy(s, self.fahrplan.d_bei(s))
            weiter = st.xy(s + 40.0, self.fahrplan.d_bei(s + 40.0))
            winkel = math.atan2(weiter[1] - ziel[1], weiter[0] - ziel[0])
            body = self.vehicle.physics.body
            body.position = (body.position.x * 0.4 + ziel[0] * 0.6,
                             body.position.y * 0.4 + ziel[1] * 0.6)
            body.angle = winkel
            try:
                import pymunk
                body.velocity = pymunk.Vec2d(math.cos(winkel) * 40.0, math.sin(winkel) * 40.0)
            except Exception:
                pass
            self.recovery_timer = 0.0
            self._recovery_attempts = 0
            self._hint = None
        else:
            self._recovery_nachlauf = 0.0
            self.recovery_timer = min(RECOVERY_MAX_SECONDS,
                                      RECOVERY_BASE_SECONDS * self._recovery_attempts)
            if self._recovery_attempts > 1:
                self._recovery_steer_sign = -self._recovery_steer_sign
