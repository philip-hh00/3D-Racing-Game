"""HUD - Heads-Up Display overlay for the racing game (Phase 2).

Renders a vehicle-like dashboard at the bottom-center of the screen:
- Semicircular RPM dial (Tachometer) on the left (with green range, red needle, and redline starting at 5200 RPM)
- Semicircular Speedometer dial on the right (with cyan range, red needle, and digital speed)
- Gear indicator (large orange/red number/letter) in the center
- Blinking ESP warning light that triggers during drifts (car with wavy tracks)
- FPS counter (top-left)
"""
from __future__ import annotations

import math
import pygame

from src.core.settings import KMH_PER_PXS
from src.core.i18n import tr
from src.core import startampel
from src.ui import theme
from src.ui import zeichnen, leinwand


class HUD:
    """Dashboard-style HUD with Speedometer, RPM bar, Gear indicator, and ESP light."""

    # -- Layout constants -------------------------------------------------
    _FPS_POS: tuple[int, int] = (12, 8)
    _FPS_FONT_SIZE: int = 20
    _SPEED_FONT_SIZE: int = 36
    _GEAR_LABEL_FONT_SIZE: int = 16
    _GEAR_FONT_SIZE: int = 52
    _TICK_FONT_SIZE: int = 14

    # -- Colours ----------------------------------------------------------
    _COL_FPS: tuple[int, int, int] = (180, 180, 180)
    _COL_SPEED: tuple[int, int, int] = (255, 255, 255)
    _COL_GEAR_TEXT: tuple[int, int, int] = (255, 160, 0)   # Amber/Orange
    _COL_GEAR_LABEL: tuple[int, int, int] = (140, 140, 150)
    _COL_PANEL_BG: tuple[int, int, int, int] = (10, 10, 15, 128)  # Semi-transparent dark blue/gray (~50% opacity)
    #: Hintergrund des Status-Panels oben rechts — leicht durchsichtig (50% Deckkraft).
    #: Ursprünglich undurchsichtig (Alpha 255) oder 78% (Alpha 200) um Artefakte zu vermeiden,
    #: aber die neue Anforderung ist 45-55% Deckkraft für alle Panels einheitlich,
    #: mit dünnem hellen Rand, damit die 3D-Welt dahinter sichtbar bleibt.
    _COL_STATUS_PANEL_BG: tuple[int, int, int, int] = (10, 10, 15, 128)
    _COL_RPM_NORMAL: tuple[int, int, int] = (0, 220, 80)    # Green
    _COL_RPM_REDLINE: tuple[int, int, int] = (240, 40, 40)   # Red

    #: Wie lange „LOS!“ nach dem Countdown eingeblendet bleibt.
    _GO_DISPLAY_SECONDS: float = 1.2

    def __init__(self) -> None:
        pygame.font.init()
        self._init_fonts(1.0)
        self._last_scale = 1.0

        # Live State
        self._speed: float = 0.0
        self._fps: float = 0.0
        self._rpm: float = 1000.0
        self._redline_rpm: float = 6000.0
        self._shift_up_rpm: float = 5100.0
        self._gear: int = 1
        self._is_drifting: bool = False

        # Live Lap metrics
        self._current_lap: int = 1
        self._total_laps: int = 3
        self._current_lap_time: float = 0.0
        self._best_lap_time: float = float("inf")
        self._last_lap_time: float = 0.0
        self._position: int = 1
        self._total_vehicles: int = 1

        # Countdown and Splits
        self._countdown_timer: float | None = None
        self._last_countdown_timer: float | None = None
        self._go_display_timer: float = 0.0
        self._split_info: tuple[float, float] | None = None
        self._race_finished: bool = False
        self._sector_diff: float | None = None
        self._results: list[dict] = []
        self._player_id: int | None = None
        self._waiting_for_field: bool = False
        #: Restsekunden bis zum DNF, solange man selbst noch faehrt.
        self._dnf_seconds: float | None = None
        self._live_diff: float | None = None
        self._standings_list: list[dict[str, Any]] = []

    def _init_fonts(self, scale: float) -> None:
        self._fps_font = theme.font_standard(int(self._FPS_FONT_SIZE * scale))
        self._speed_font = theme.font_standard(int(self._SPEED_FONT_SIZE * scale))
        self._gear_label_font = theme.font_standard(int(self._GEAR_LABEL_FONT_SIZE * scale))
        self._gear_font = theme.font_standard(int(self._GEAR_FONT_SIZE * scale))
        self._tick_font = theme.font_standard(int(self._TICK_FONT_SIZE * scale))
        # Countdown-/GO!-Schrift: die Spielschrift aus theme.py statt der
        # Standardschrift — die Groesse haengt zusaetzlich von der Pop-in-
        # Animation ab, wird also direkt beim Zeichnen ueber theme.font() geholt.
        self._overlay_title_font = theme.font_standard(int(72 * scale))
        self._overlay_body_font = theme.font_standard(int(36 * scale))
        self._split_font = theme.font_standard(int(48 * scale))

    def update(
        self,
        speed: float,
        fps: float,
        rpm: float,
        redline_rpm: float,
        shift_up_rpm: float,
        gear: int,
        is_drifting: bool,
        current_lap: int,
        total_laps: int,
        current_lap_time: float,
        best_lap_time: float,
        last_lap_time: float,
        position: int,
        total_vehicles: int,
        countdown_timer: float | None = None,
        split_info: tuple[float, float] | None = None,
        race_finished: bool = False,
        sector_diff: float | None = None,
        results: list[dict] | None = None,
        player_id: int | None = None,
        waiting_for_field: bool = False,
        live_diff: float | None = None,
        standings: list[dict[str, Any]] | None = None,
        dnf_seconds: float | None = None,
        dt: float = 1.0 / 60.0,
    ) -> None:
        """Update live variables for rendering."""
        self._speed = speed
        self._fps = fps
        self._rpm = rpm
        self._redline_rpm = redline_rpm
        self._shift_up_rpm = shift_up_rpm
        self._gear = gear
        self._is_drifting = is_drifting

        self._current_lap = current_lap
        self._total_laps = total_laps
        self._current_lap_time = current_lap_time
        self._best_lap_time = best_lap_time
        self._last_lap_time = last_lap_time
        self._position = position
        self._total_vehicles = total_vehicles
        self._split_info = split_info
        self._race_finished = race_finished
        self._sector_diff = sector_diff
        self._results = results or []
        self._player_id = player_id
        self._waiting_for_field = waiting_for_field
        self._live_diff = live_diff
        self._standings_list = standings or []
        self._dnf_seconds = dnf_seconds

        # Detect countdown transition to GO!
        if self._last_countdown_timer is not None and countdown_timer is None:
            self._go_display_timer = self._GO_DISPLAY_SECONDS  # Ampel blendet nach dem Start aus

        self._last_countdown_timer = countdown_timer
        self._countdown_timer = countdown_timer

        if self._go_display_timer > 0.0:
            self._go_display_timer -= dt

    def render(self, screen: pygame.Surface, scale: float = 1.0) -> None:
        """Render the complete dashboard HUD overlay."""
        if not hasattr(self, "_last_scale") or self._last_scale != scale:
            self._last_scale = scale
            self._init_fonts(scale)

        w, h = screen.get_size()
        self._render_fps(screen, w, h, scale)
        self._render_dashboard(screen, w, h, scale)
        self._render_top_right_panel(screen, w, h, scale)
        self._render_leaderboard(screen, w, h, scale)
        self._render_ampel(screen, w, h, scale)
        self._render_split_time(screen, w, h, scale)
        self._render_race_finish(screen, w, h, scale)

    def _render_fps(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Draw FPS counter in the top-left corner."""
        fps_text = f"FPS: {self._fps:.0f}"
        surface = self._fps_font.render(fps_text, True, self._COL_FPS)
        pos = (int(self._FPS_POS[0] * scale), int(self._FPS_POS[1] * scale))
        screen.blit(surface, pos)

    def _render_dashboard(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Draw the dual-dial dashboard console at the bottom center."""
        panel_w = int(520 * scale)
        panel_h = int(120 * scale)
        panel_x = (w - panel_w) // 2
        panel_y = h - panel_h - int(20 * scale)

        # Draw semi-transparent panel background
        panel_surf = leinwand.flaeche((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill(self._COL_PANEL_BG)
        # Subtle border with rounded corners
        zeichnen.rect(panel_surf, (120, 120, 140, 100), (0, 0, panel_w, panel_h), max(1, int(2 * scale)), border_radius=int(12 * scale))
        screen.blit(panel_surf, (panel_x, panel_y))

        # Common gauge parameters
        radius = int(42 * scale)
        deg_to_rad = math.pi / 180.0

        # --- 1. Left Gauge: Tachometer (RPM) ---
        cx_rpm = panel_x + int(95 * scale)
        cy_rpm = panel_y + int(60 * scale)

        # Dynamic RPM ranges
        rpm_start = 1000.0 if self._redline_rpm <= 9000.0 else 0.0
        rpm_max_display = max(6000.0, self._redline_rpm * 1.1)
        rpm_band = rpm_max_display - rpm_start
        redline_ratio = (self._redline_rpm - rpm_start) / rpm_band
        redline_deg = 220.0 - redline_ratio * 260.0

        # Draw tachometer background arc
        zeichnen.arc(
            screen,
            (45, 45, 55),
            (cx_rpm - radius, cy_rpm - radius, radius * 2, radius * 2),
            -40.0 * deg_to_rad,
            220.0 * deg_to_rad,
            max(1, int(5 * scale))
        )

        # Draw redline static indicator
        zeichnen.arc(
            screen,
            self._COL_RPM_REDLINE,
            (cx_rpm - radius, cy_rpm - radius, radius * 2, radius * 2),
            -40.0 * deg_to_rad,
            redline_deg * deg_to_rad,
            max(1, int(6 * scale))
        )

        # Ticks on RPM dial
        tick_step = 1000 if rpm_max_display <= 8000 else 2000
        for rpm_val in range(int(rpm_start), int(rpm_max_display), tick_step):
            ratio = (rpm_val - rpm_start) / rpm_band
            tick_deg = 220.0 - ratio * 260.0
            tick_rad = tick_deg * deg_to_rad
            
            is_redline = rpm_val >= self._redline_rpm
            tick_color = self._COL_RPM_REDLINE if is_redline else (220, 220, 220)
            tick_len = int((7 if is_redline else 5) * scale)
            
            x_out = cx_rpm + radius * math.cos(tick_rad)
            y_out = cy_rpm - radius * math.sin(tick_rad)
            x_in = cx_rpm + (radius - tick_len) * math.cos(tick_rad)
            y_in = cy_rpm - (radius - tick_len) * math.sin(tick_rad)
            
            zeichnen.line(screen, tick_color, (x_in, y_in), (x_out, y_out), max(1, int(2 * scale) if is_redline else 1))
            
            # Number label (e.g. 1, 2, 10, 12)
            lbl_num = rpm_val // 1000
            if lbl_num > 0 or rpm_start == 0:
                lbl_surf = self._tick_font.render(str(lbl_num), True, tick_color)
                text_dist = radius - int(14 * scale)
                tx = cx_rpm + text_dist * math.cos(tick_rad)
                ty = cy_rpm - text_dist * math.sin(tick_rad)
                text_rect = lbl_surf.get_rect(center=(int(tx), int(ty)))
                screen.blit(lbl_surf, text_rect)

        # Draw filled active RPM arc
        rpm_ratio = min(1.0, max(0.0, (self._rpm - rpm_start) / rpm_band))
        curr_rpm_deg = 220.0 - rpm_ratio * 260.0
        curr_rpm_rad = curr_rpm_deg * deg_to_rad

        if self._rpm > rpm_start:
            if self._rpm <= self._redline_rpm:
                # All green
                zeichnen.arc(
                    screen,
                    self._COL_RPM_NORMAL,
                    (cx_rpm - radius, cy_rpm - radius, radius * 2, radius * 2),
                    curr_rpm_rad,
                    220.0 * deg_to_rad,
                    max(1, int(5 * scale))
                )
            else:
                # Green part up to redline
                zeichnen.arc(
                    screen,
                    self._COL_RPM_NORMAL,
                    (cx_rpm - radius, cy_rpm - radius, radius * 2, radius * 2),
                    redline_deg * deg_to_rad,
                    220.0 * deg_to_rad,
                    max(1, int(5 * scale))
                )
                # Red part from redline to current RPM
                zeichnen.arc(
                    screen,
                    self._COL_RPM_REDLINE,
                    (cx_rpm - radius, cy_rpm - radius, radius * 2, radius * 2),
                    curr_rpm_rad,
                    redline_deg * deg_to_rad,
                    max(1, int(5 * scale))
                )

        # Draw RPM Label
        rpm_lbl = self._tick_font.render("RPM x1000", True, (140, 140, 150))
        rpm_lbl_rect = rpm_lbl.get_rect(center=(cx_rpm, cy_rpm + radius - int(10 * scale)))
        screen.blit(rpm_lbl, rpm_lbl_rect)

        # RPM Needle
        needle_len = radius - int(3 * scale)
        nx = cx_rpm + needle_len * math.cos(curr_rpm_rad)
        ny = cy_rpm - needle_len * math.sin(curr_rpm_rad)
        # Needle base offsets for a slightly wedge-shaped needle
        nd_base_x1 = cx_rpm + int(4 * scale) * math.cos(curr_rpm_rad - math.pi/2)
        nd_base_y1 = cy_rpm - int(4 * scale) * math.sin(curr_rpm_rad - math.pi/2)
        nd_base_x2 = cx_rpm + int(4 * scale) * math.cos(curr_rpm_rad + math.pi/2)
        nd_base_y2 = cy_rpm - int(4 * scale) * math.sin(curr_rpm_rad + math.pi/2)
        # Draw needle polygon
        zeichnen.polygon(screen, (255, 60, 60), [(nd_base_x1, nd_base_y1), (nd_base_x2, nd_base_y2), (nx, ny)])

        # Center cap
        zeichnen.circle(screen, (15, 15, 20), (cx_rpm, cy_rpm), int(6 * scale))
        zeichnen.circle(screen, (120, 120, 130), (cx_rpm, cy_rpm), int(6 * scale), 1)


        # --- 2. Right Gauge: Speedometer (Speed needle) ---
        cx_spd = panel_x + int(425 * scale)
        cy_spd = panel_y + int(60 * scale)

        # Draw speedometer background arc (0 to 300 km/h)
        zeichnen.arc(
            screen,
            (45, 45, 55),
            (cx_spd - radius, cy_spd - radius, radius * 2, radius * 2),
            -40.0 * deg_to_rad,
            220.0 * deg_to_rad,
            max(1, int(5 * scale))
        )

        # Ticks on Speedometer (0, 50, 100, 150, 200, 250, 300)
        for spd_val in range(0, 350, 50):
            ratio = spd_val / 300.0
            tick_deg = 220.0 - ratio * 260.0
            tick_rad = tick_deg * deg_to_rad
            
            is_major = spd_val % 100 == 0
            tick_color = (220, 220, 220) if is_major else (130, 130, 140)
            tick_len = int((6 if is_major else 4) * scale)
            
            x_out = cx_spd + radius * math.cos(tick_rad)
            y_out = cy_spd - radius * math.sin(tick_rad)
            x_in = cx_spd + (radius - tick_len) * math.cos(tick_rad)
            y_in = cy_spd - (radius - tick_len) * math.sin(tick_rad)
            
            zeichnen.line(screen, tick_color, (x_in, y_in), (x_out, y_out), 1)
            
            # Text label for major values
            if is_major:
                lbl_surf = self._tick_font.render(str(spd_val), True, tick_color)
                text_dist = radius - int(14 * scale)
                tx = cx_spd + text_dist * math.cos(tick_rad)
                ty = cy_spd - text_dist * math.sin(tick_rad)
                text_rect = lbl_surf.get_rect(center=(int(tx), int(ty)))
                screen.blit(lbl_surf, text_rect)

        # Speed Ratio and Angle
        abs_speed = abs(self._speed) * KMH_PER_PXS
        spd_ratio = min(1.0, max(0.0, abs_speed / 300.0))
        curr_spd_deg = 220.0 - spd_ratio * 260.0
        curr_spd_rad = curr_spd_deg * deg_to_rad

        # Draw filled active Speedometer arc (cool cyan/blue)
        if abs_speed > 0.0:
            zeichnen.arc(
                screen,
                (0, 180, 255),
                (cx_spd - radius, cy_spd - radius, radius * 2, radius * 2),
                curr_spd_rad,
                220.0 * deg_to_rad,
                max(1, int(5 * scale))
            )

        # Speed Label
        spd_lbl = self._tick_font.render("km/h", True, (140, 140, 150))
        spd_lbl_rect = spd_lbl.get_rect(center=(cx_spd, cy_spd + radius - int(10 * scale)))
        screen.blit(spd_lbl, spd_lbl_rect)

        # Speed Needle
        nx = cx_spd + needle_len * math.cos(curr_spd_rad)
        ny = cy_spd - needle_len * math.sin(curr_spd_rad)
        nd_base_x1 = cx_spd + int(4 * scale) * math.cos(curr_spd_rad - math.pi/2)
        nd_base_y1 = cy_spd - int(4 * scale) * math.sin(curr_spd_rad - math.pi/2)
        nd_base_x2 = cx_spd + int(4 * scale) * math.cos(curr_spd_rad + math.pi/2)
        nd_base_y2 = cy_spd - int(4 * scale) * math.sin(curr_spd_rad + math.pi/2)
        zeichnen.polygon(screen, (255, 60, 60), [(nd_base_x1, nd_base_y1), (nd_base_x2, nd_base_y2), (nx, ny)])

        # Center cap
        zeichnen.circle(screen, (15, 15, 20), (cx_spd, cy_spd), int(6 * scale))
        zeichnen.circle(screen, (120, 120, 130), (cx_spd, cy_spd), int(6 * scale), 1)


        # --- 3. Center Stack: ESP Warning, Gear, Digital Speed ---
        cx_ctr = panel_x + int(260 * scale)
        
        # A. ESP Warning Light (Blinking amber icon)
        self._draw_esp_icon(screen, cx_ctr, panel_y + int(20 * scale), self._is_drifting, scale)

        # B. Gear Display
        gear_lbl = self._gear_label_font.render(tr("GANG"), True, self._COL_GEAR_LABEL)
        gear_lbl_rect = gear_lbl.get_rect(center=(cx_ctr, panel_y + int(40 * scale)))
        screen.blit(gear_lbl, gear_lbl_rect)

        if self._speed < -2.0:
            gear_text = "R"
            gear_color = (255, 40, 40)   # Red for reverse
        else:
            gear_text = str(self._gear)
            gear_color = self._COL_GEAR_TEXT  # Amber for forward gears
            
        gear_surf = self._gear_font.render(gear_text, True, gear_color)
        gear_rect = gear_surf.get_rect(center=(cx_ctr, panel_y + int(65 * scale)))
        screen.blit(gear_surf, gear_rect)

        # C. Digital Speedometer (px/s → km/h)
        speed_int = int(round(abs(self._speed) * KMH_PER_PXS))
        speed_text = f"{speed_int} km/h"
        speed_surf = self._speed_font.render(speed_text, True, self._COL_SPEED)
        speed_rect = speed_surf.get_rect(center=(cx_ctr, panel_y + int(100 * scale)))
        screen.blit(speed_surf, speed_rect)

    def _draw_esp_icon(self, screen: pygame.Surface, center_x: int, center_y: int, active: bool, scale: float) -> None:
        """Draw the ESP warning light (car silhouette with wavy tracks)."""
        if active:
            if (pygame.time.get_ticks() // 125) % 2 == 0:
                color = (255, 140, 0)  # Bright amber
            else:
                color = (80, 45, 0)   # Dim amber
        else:
            color = (35, 25, 15)       # Dark unlit amber

        # Rear of car silhouette
        body_pts = [
            (center_x - int(5 * scale), center_y - int(8 * scale)),   # Roof top left
            (center_x + int(5 * scale), center_y - int(8 * scale)),   # Roof top right
            (center_x + int(7 * scale), center_y - int(3 * scale)),   # Shoulder right
            (center_x + int(9 * scale), center_y - int(3 * scale)),   # Bumper top right
            (center_x + int(9 * scale), center_y + int(2 * scale)),   # Bumper bottom right
            (center_x - int(9 * scale), center_y + int(2 * scale)),   # Bumper bottom left
            (center_x - int(9 * scale), center_y - int(3 * scale)),   # Bumper top left
            (center_x - int(7 * scale), center_y - int(3 * scale)),   # Shoulder left
        ]
        zeichnen.polygon(screen, color, body_pts)
        
        # Wheels
        zeichnen.rect(screen, color, (center_x - int(8 * scale), center_y + int(2 * scale), int(2 * scale), int(2 * scale)))
        zeichnen.rect(screen, color, (center_x + int(6 * scale), center_y + int(2 * scale), int(2 * scale), int(2 * scale)))
        
        # Wavy skid marks
        left_skid = [
            (center_x - int(7 * scale), center_y + int(4 * scale)),
            (center_x - int(9 * scale), center_y + int(7 * scale)),
            (center_x - int(6 * scale), center_y + int(10 * scale)),
            (center_x - int(9 * scale), center_y + int(13 * scale)),
        ]
        right_skid = [
            (center_x + int(7 * scale), center_y + int(4 * scale)),
            (center_x + int(5 * scale), center_y + int(7 * scale)),
            (center_x + int(8 * scale), center_y + int(10 * scale)),
            (center_x + int(5 * scale), center_y + int(13 * scale)),
        ]
        zeichnen.lines(screen, color, False, left_skid, max(1, int(2 * scale)))
        zeichnen.lines(screen, color, False, right_skid, max(1, int(2 * scale)))

    def _render_top_right_panel(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Draw details like position, lap, and times in the top-right corner."""
        panel_w = int(260 * scale)
        panel_h = int((235 if self._live_diff is not None else 210) * scale)
        panel_x = w - panel_w - int(20 * scale)
        panel_y = int(20 * scale)

        # Leicht durchsichtiger Panel-Hintergrund (50% Deckkraft)
        panel_surf = leinwand.flaeche((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill(self._COL_STATUS_PANEL_BG)
        zeichnen.rect(panel_surf, (120, 120, 140, 100), (0, 0, panel_w, panel_h), max(1, int(2 * scale)), border_radius=int(8 * scale))
        screen.blit(panel_surf, (panel_x, panel_y))

        # 1. Position & Laps
        pos_str = f"POS: {self._position}/{self._total_vehicles}"
        lap_str = f"LAP: {self._current_lap}/{self._total_laps}"
        if self._race_finished:
            lap_str = "FINISH"

        pos_surf = self._speed_font.render(pos_str, True, self._COL_GEAR_TEXT)
        lap_surf = self._speed_font.render(lap_str, True, (255, 255, 255))

        screen.blit(pos_surf, (panel_x + int(15 * scale), panel_y + int(15 * scale)))
        screen.blit(lap_surf, (panel_x + int(15 * scale), panel_y + int(45 * scale)))

        # Helper to format times
        def _fmt(sec: float) -> str:
            if sec == float("inf") or sec <= 0:
                return "--:--.--"
            m = int(sec // 60)
            s = int(sec % 60)
            ms = int((sec % 1) * 100)
            return f"{m:02d}:{s:02d}.{ms:02d}"

        # 2. Times
        curr_time_str = f"TIME: {_fmt(self._current_lap_time)}"
        last_time_str = f"LAST: {_fmt(self._last_lap_time)}"
        best_time_str = f"BEST: {_fmt(self._best_lap_time)}"

        curr_surf = self._fps_font.render(curr_time_str, True, (240, 240, 240))
        last_surf = self._fps_font.render(last_time_str, True, (200, 200, 210))
        best_surf = self._fps_font.render(best_time_str, True, (0, 255, 120))

        screen.blit(curr_surf, (panel_x + int(15 * scale), panel_y + int(90 * scale)))

        if self._live_diff is not None:
            if self._live_diff < 0:
                diff_str = f"GHOST: -{abs(self._live_diff):.2f}s"
                diff_col = (0, 255, 120)
            else:
                diff_str = f"GHOST: +{abs(self._live_diff):.2f}s"
                diff_col = (255, 50, 50)
            diff_surf = self._tick_font.render(diff_str, True, diff_col)
            screen.blit(diff_surf, (panel_x + int(15 * scale), panel_y + int(108 * scale)))

            screen.blit(last_surf, (panel_x + int(15 * scale), panel_y + int(125 * scale)))
            screen.blit(best_surf, (panel_x + int(15 * scale), panel_y + int(145 * scale)))
        else:
            screen.blit(last_surf, (panel_x + int(15 * scale), panel_y + int(110 * scale)))
            screen.blit(best_surf, (panel_x + int(15 * scale), panel_y + int(130 * scale)))

        # 3. Sector Timer
        if self._sector_diff is not None:
            if self._sector_diff < 0:
                sec_text = f"{tr('SEKTOR:')} -{abs(self._sector_diff):.2f}s"
                sec_color = (0, 255, 120)  # Green for improvement
            else:
                sec_text = f"{tr('SEKTOR:')} +{abs(self._sector_diff):.2f}s"
                sec_color = (255, 50, 50)  # Red for slower
        else:
            sec_text = f"{tr('SEKTOR:')} --:--.--"
            sec_color = (160, 160, 170)

        sec_surf = self._fps_font.render(sec_text, True, sec_color)
        sec_y = 190 if self._live_diff is not None else 175
        screen.blit(sec_surf, (panel_x + int(15 * scale), panel_y + int(sec_y * scale)))

    def ampel_stufe(self) -> int:
        """Leuchtende Lampen 0..5 — dieselbe Funktion wie beim 3D-Portal."""
        return startampel.ampel_stufe(self._countdown_timer)

    def ampel_sichtbar(self) -> bool:
        """Ampel steht im Countdown und noch kurz nach dem Start (ausgeschaltet)."""
        return self._countdown_timer is not None or self._go_display_timer > 0.0

    def _render_ampel(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Startampel oben mittig, dem Portal an der Start-/Zielline nachempfunden.

        Dunkles Gehaeuse im Seitenverhaeltnis des Portal-Kastens (3,2 x 0,8 m)
        mit fuenf runden Lampen (Rastermass 0,64 m, Durchmesser 0,4 m), die rot
        nacheinander zuenden und bei GO gemeinsam ausgehen. Die Stufe kommt aus
        ``startampel.ampel_stufe`` — derselben Funktion, die das Portal nutzt.
        Nach dem Start blendet die Ampel aus; ein kleines „LOS!“ bleibt kurz.
        """
        if not self.ampel_sichtbar():
            return
        imcountdown = self._countdown_timer is not None
        fade = 1.0 if imcountdown else max(0.0, min(1.0, self._go_display_timer / 0.5))
        self.zeichne_ampel(screen, w, scale, self.ampel_stufe(), fade, los=not imcountdown)

    @staticmethod
    def zeichne_ampel(screen: pygame.Surface, w: int, scale: float, stufe: int,
                      fade: float = 1.0, los: bool = False) -> None:
        """Zeichnet das Ampelgehaeuse mit ``stufe`` roten Lampen oben mittig.

        Auch die Fortsetzen-Anzeige nach der Pause nutzt diese Zeichnung.
        """
        if fade <= 0.0:
            return

        pitch = int(40 * scale)             # 0,64 m
        gw, gh = pitch * 5, int(pitch * 1.25)  # 3,2 m x 0,8 m
        lampe_r = int(pitch * 0.3125)         # Durchmesser 0,4 m
        pad = max(2, int(5 * scale))
        flaeche = leinwand.flaeche((gw + 2 * pad, gh + 2 * pad), pygame.SRCALPHA)
        zeichnen.rect(flaeche, (15, 15, 17), (pad, pad, gw, gh), border_radius=int(6 * scale))
        zeichnen.rect(flaeche, (70, 70, 78), (pad, pad, gw, gh), width=max(1, int(2 * scale)),
                      border_radius=int(6 * scale))

        for i in range(startampel.LAMPEN):
            cx = pad + pitch // 2 + i * pitch
            cy = pad + gh // 2
            zeichnen.circle(flaeche, (28, 6, 6), (cx, cy), lampe_r + max(1, int(2 * scale)))
            if i < stufe:
                glow = leinwand.flaeche((lampe_r * 4, lampe_r * 4), pygame.SRCALPHA)
                zeichnen.circle(glow, (255, 25, 12, 70), (lampe_r * 2, lampe_r * 2), lampe_r * 2)
                flaeche.blit(glow, (cx - lampe_r * 2, cy - lampe_r * 2))
                zeichnen.circle(flaeche, (225, 28, 20), (cx, cy), lampe_r)
                zeichnen.circle(flaeche, (255, 120, 90), (cx - lampe_r // 3, cy - lampe_r // 3),
                                max(1, lampe_r // 3))
            else:
                zeichnen.circle(flaeche, (60, 14, 14), (cx, cy), lampe_r)

        if fade < 1.0:
            flaeche.set_alpha(int(255 * fade))
        rect = flaeche.get_rect(midtop=(w // 2, int(36 * scale)))
        screen.blit(flaeche, rect)

        if los:
            schrift = theme.font(int(34 * scale))
            los = schrift.render(tr("LOS!"), True, (70, 255, 150))
            los.set_alpha(int(255 * fade))
            screen.blit(los, los.get_rect(midtop=(w // 2, rect.bottom + int(6 * scale))))

    def _render_split_time(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Render checkpoint split difference (e.g. +0.42s in red or -0.23s in green)."""
        if self._split_info:
            diff, display_timer = self._split_info
            
            cx = w // 2
            cy = int(180 * scale)
            
            if diff < 0:
                text = f"-{abs(diff):.2f}s"
                color = (0, 255, 120)  # Neon green
            else:
                text = f"+{abs(diff):.2f}s"
                color = (255, 50, 50)   # Neon red
                
            text_surf = self._split_font.render(text, True, color)
            text_rect = text_surf.get_rect(center=(cx, cy))
            
            # Text background panel
            pad_w = text_rect.width + int(30 * scale)
            pad_h = text_rect.height + int(12 * scale)
            pad_surf = leinwand.flaeche((pad_w, pad_h), pygame.SRCALPHA)
            pad_surf.fill((10, 10, 15, 160))
            zeichnen.rect(pad_surf, color, (0, 0, pad_w, pad_h), max(1, int(2 * scale)), border_radius=int(6 * scale))
            
            screen.blit(pad_surf, (cx - pad_w//2, cy - pad_h//2))
            screen.blit(text_surf, text_rect)

    def _render_race_finish(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Render in-race finish banner while waiting for other vehicles.

        The full results table is handled exclusively by ResultsPage – the HUD
        only shows a small 'ZIEL!' banner while the race is still in 'finishing'
        state (i.e. other cars are still on track).

        Online zählt zusätzlich das Warten auf die Ergebnisse der anderen: der
        lokale Manager eines Gastes kennt nur dessen eigenes Auto, ist also
        sofort 'finished'. Ohne diesen Zusatz konnte ein Gast den Hinweis nie
        sehen — er stand im Ziel und bekam keine Erklärung dafür, warum es
        nicht weitergeht.
        """
        # Wer selbst noch faehrt, braucht keine Meldung ueber die anderen,
        # sondern die Restzeit: gleich ist das Rennen fuer ihn vorbei.
        if self._dnf_seconds is not None:
            self._render_dnf_countdown(screen, w, h, scale)
            return

        if self._waiting_for_field:
            text = self._overlay_body_font.render(
                tr("ZIEL! Warte auf weitere Fahrzeuge..."), True, self._COL_GEAR_TEXT
            )
            rect = text.get_rect(center=(w // 2, int(60 * scale)))
            bg = leinwand.flaeche((rect.width + int(40 * scale), rect.height + int(16 * scale)), pygame.SRCALPHA)
            bg.fill((10, 10, 15, 190))
            zeichnen.rect(bg, self._COL_GEAR_TEXT,
                             (0, 0, bg.get_width(), bg.get_height()), max(1, int(2 * scale)), border_radius=int(6 * scale))
            screen.blit(bg, (rect.x - int(20 * scale), rect.y - int(8 * scale)))
            screen.blit(text, rect)

    def _render_dnf_countdown(self, screen: pygame.Surface, w: int, h: int,
                              scale: float) -> None:
        """Restzeit für alle, die noch auf der Strecke sind.

        Vorher lief die Frist unsichtbar ab: das Rennen endete für einen
        Nachzügler ohne Vorwarnung. Die Sekunden stehen groß über der Bahn,
        darunter, was passiert, wenn sie abgelaufen sind.
        """
        rest = max(0.0, float(self._dnf_seconds or 0.0))
        sekunden = int(rest) + 1 if rest > 0 else 0
        farbe = (255, 90, 70) if rest <= 3.0 else self._COL_GEAR_TEXT

        zahl = self._overlay_title_font.render(str(sekunden), True, farbe)
        z_rect = zahl.get_rect(center=(w // 2, int(70 * scale)))
        unten = self._overlay_body_font.render(
            tr("Zieldurchfahrt oder DNF"), True, farbe)
        u_rect = unten.get_rect(center=(w // 2, z_rect.bottom + int(16 * scale)))

        breite = max(z_rect.width, u_rect.width) + int(48 * scale)
        hoehe = z_rect.height + u_rect.height + int(28 * scale)
        bg = leinwand.flaeche((breite, hoehe), pygame.SRCALPHA)
        bg.fill((10, 10, 15, 200))
        zeichnen.rect(bg, farbe, (0, 0, breite, hoehe),
                         max(1, int(2 * scale)), border_radius=int(8 * scale))
        screen.blit(bg, (w // 2 - breite // 2, z_rect.top - int(10 * scale)))
        screen.blit(zahl, z_rect)
        screen.blit(unten, u_rect)

    def _render_leaderboard(self, screen: pygame.Surface, w: int, h: int, scale: float) -> None:
        """Render a live team leaderboard on the left side of the HUD."""
        if not self._standings_list:
            return

        panel_w = int(240 * scale)
        panel_h = int((35 + len(self._standings_list) * 28) * scale)
        panel_x = int(20 * scale)
        panel_y = int(80 * scale)

        # Translucent panel background
        panel_surf = leinwand.flaeche((panel_w, panel_h), pygame.SRCALPHA)
        panel_surf.fill(self._COL_PANEL_BG)
        zeichnen.rect(panel_surf, (120, 120, 140, 100), (0, 0, panel_w, panel_h), max(1, int(2 * scale)), border_radius=int(6 * scale))
        screen.blit(panel_surf, (panel_x, panel_y))

        # Title
        title_surf = self._tick_font.render("TEAM STANDINGS", True, (255, 255, 255))
        screen.blit(title_surf, (panel_x + int(10 * scale), panel_y + int(10 * scale)))

        # Standings list
        for i, entry in enumerate(self._standings_list):
            row_y = panel_y + int((35 + i * 28) * scale)

            # Rank
            rank_surf = self._fps_font.render(f"{entry['position']}.", True, (160, 160, 170))
            screen.blit(rank_surf, (panel_x + int(10 * scale), row_y))

            # Team colored badge (solid square)
            badge_color = (255, 120, 0) if entry["team"] == "A" else (0, 140, 255)
            badge_rect = pygame.Rect(
                panel_x + int(32 * scale),
                row_y + int(2 * scale),
                int(12 * scale),
                int(12 * scale)
            )
            zeichnen.rect(screen, badge_color, badge_rect, border_radius=int(2 * scale))

            # Name
            name_color = self._COL_GEAR_TEXT if entry["is_player"] else (240, 240, 240)
            name_surf = self._fps_font.render(entry["name"], True, name_color)
            screen.blit(name_surf, (panel_x + int(52 * scale), row_y))
