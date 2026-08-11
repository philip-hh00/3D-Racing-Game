"""Track selection state – menu to select one of five tracks with specs and a rotating minimap preview."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from src.states.base_state import BaseState
from src.core.settings import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    COLOR_UI_BG,
    COLOR_UI_TEXT,
    COLOR_UI_ACCENT,
    COLOR_UI_PANEL,
)
from src.core.i18n import tr
from src.core import display
from src.ui import theme

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


class TrackSelectState(BaseState):
    """Interactive screen allowing the player to select a racetrack.

    Shows track cards on the left, detailed specs and description on the right,
    and a rotating 2D vector preview of the highlighted track layout on the right.
    """

    @staticmethod
    def _streckendateien() -> list[tuple[str, Path, bool]]:
        """Die fünf mitgelieferten Strecken plus alles Eigene.

        Eigene werden über alle Wurzeln gesucht, nicht nur relativ zum
        Arbeitsverzeichnis: auf einem gepackten macOS-Build liegen sie in
        ``Application Support``, das Arbeitsverzeichnis zeigt aber ins Bundle
        (siehe paths.track_roots).
        """
        from src.core import paths
        return paths.strecken()

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.selected_index: int = 0
        self.track_keys: list[str] = ["oval", "desert", "city", "mountain", "gp"]
        self.selected_vehicle_config: str = "rookie"

        # AI opponent difficulty (applies to all AI cars equally). Persists on
        # this reused state instance across screens.
        self.ai_difficulty_keys: list[str] = ["easy", "medium", "hard"]
        self.ai_difficulty_labels: dict[str, str] = {
            "easy": "EINFACH", "medium": "MITTEL", "hard": "SCHWER",
        }
        self.ai_difficulty_colors: dict[str, tuple[int, int, int]] = {
            "easy": (50, 220, 80), "medium": (255, 160, 0), "hard": (240, 50, 50),
        }
        self.ai_difficulty_index: int = 1  # medium

        # UI configuration
        self.left_panel_rect = pygame.Rect(80, 160, 480, 800)
        self.right_panel_rect = pygame.Rect(600, 160, 1240, 800)
        #: Der Rueckweg als Knopf, oben links ueber der linken Spalte.
        from src.ui.widgets import ZurueckKnopf
        self._zurueck_knopf = ZurueckKnopf(80, 72)
        self.turntable_center = (1480, 480)
        self.turntable_radius = 240

        # Fonts
        self.title_font: pygame.font.Font | None = None
        self.header_font: pygame.font.Font | None = None
        self.body_font: pygame.font.Font | None = None
        self.label_font: pygame.font.Font | None = None
        self.hint_font: pygame.font.Font | None = None

        # Preloaded track details & centerlines
        self._tracks_cache: dict[str, dict[str, Any]] = {}
        self._time: float = 0.0

    def enter(self, **kwargs) -> None:
        """Set up fonts and load track data."""
        self.title_font = pygame.font.Font(None, 80)
        self.header_font = pygame.font.Font(None, 46)
        self.body_font = pygame.font.Font(None, 32)
        self.label_font = pygame.font.Font(None, 28)
        self.hint_font = pygame.font.Font(None, 24)

        self._dialog = None

        self._online_host_mode = kwargs.get("online_host_mode", False)

        from src.core import grand_prix, race_setup
        if grand_prix.is_active():
            gp = grand_prix.current()
            race_setup.current().laps = gp.laps_per_race

        # Remember selected car configuration from previous state
        self.selected_vehicle_config = kwargs.get("vehicle_config", race_setup.current().player_vehicle)
        self.track_scroll = 0
        #: Welche Kachel bereits **angeklickt** ausgewaehlt wurde — nicht
        #: dasselbe wie ``selected_index``, mit dem man schon ausgewaehlt
        #: ankommt. -1: in diesem Besuch noch nichts geklickt.
        self._klick_gewaehlt = -1
        #: Kachel unter dem Zeiger — nur Anzeige, keine Auswahl.
        self._hover_index = -1

        # Discover tracks: the 5 bundled ones (fixed order) + any user tracks in
        # data/tracks/custom/ (siehe _streckendateien).
        self._tracks_cache.clear()
        self.track_keys = []
        entries = self._streckendateien()

        for key, path, is_custom in entries:
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                centerline = [(float(p["x"]), float(p["y"])) for p in data.get("centerline", [])]
                if len(centerline) < 3:
                    print(f"[TrackSelectState] Skipping malformed track {path}")
                    continue

                xs = [p[0] for p in centerline]
                ys = [p[1] for p in centerline]
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                tcx = (min_x + max_x) / 2.0
                tcy = (min_y + max_y) / 2.0
                tdim = max(max_x - min_x, max_y - min_y)

                cps = sum(1 for w in data.get("waypoints", []) if w.get("is_checkpoint", False))

                self._tracks_cache[key] = {
                    "name": data.get("name", "Unnamed Track"),
                    "difficulty": data.get("difficulty", "Einfach"),
                    "description": data.get("description", ""),
                    "track_width": float(data.get("track_width", 200.0)),
                    "centerline": centerline,
                    "cx": tcx,
                    "cy": tcy,
                    "max_dim": tdim,
                    "checkpoints_count": cps,
                    "path": str(path),
                    "is_custom": is_custom,
                }
                self.track_keys.append(key)
            except Exception as e:
                print(f"[TrackSelectState] Error loading track {path}: {e}")

        if self.selected_index >= len(self.track_keys):
            self.selected_index = 0

    def _editor_button_rect(self) -> pygame.Rect:
        return pygame.Rect(30, 30, 360, 72)

    def _track_card_rects(self) -> list[tuple[int, pygame.Rect]]:
        x = self.left_panel_rect.x + 20
        y_start = self.left_panel_rect.y + 30
        item_height = 140
        spacing = 15
        out = []
        start = getattr(self, "track_scroll", 0)
        end = min(len(self.track_keys), start + 5)
        for row, i in enumerate(range(start, end)):
            out.append((i, pygame.Rect(x, y_start + row * (item_height + spacing), 440, item_height)))
        return out

    def _start_rect(self) -> pygame.Rect:
        """Der sichtbare Weg nach vorn, unter der Streckenliste.

        Gefordert am 05.08.2026: „bei der Streckenauswahl den Button Rennen
        start." Der zweite Klick auf die Kachel tut dasselbe — aber er steht
        nirgends angeschrieben.
        """
        return pygame.Rect(self.left_panel_rect.x + 20,
                           self.left_panel_rect.bottom + 16, 440, 60)

    def _start_beschriftung(self) -> str:
        """Online waehlt der Gastgeber nur aus — gestartet wird in der Lobby."""
        return tr("Übernehmen") if self._online_host_mode else tr("Rennen starten")

    def _draw_start_button(self, screen: pygame.Surface) -> None:
        from src.core import display
        r = self._start_rect()
        hover = r.collidepoint(display.mouse_pos())
        pygame.draw.rect(screen, (58, 44, 16) if hover else (44, 34, 14), r,
                         border_radius=6)
        pygame.draw.rect(screen, theme.ACCENT_HOT if hover else theme.ACCENT, r, 2,
                         border_radius=6)
        theme.text_fit(screen, self._start_beschriftung() + "  ›", theme.BODY,
                     theme.ACCENT_HOT if hover else theme.ACCENT,
                     r.inflate(-24, 0), center=True)

    def _track_ensure_visible(self) -> None:
        if self.selected_index < self.track_scroll:
            self.track_scroll = self.selected_index
        elif self.selected_index >= self.track_scroll + 5:
            self.track_scroll = self.selected_index - 5 + 1

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        """Handle keyboard + mouse inputs for navigation and selection."""
        from src.core import grand_prix
        for event in events:
            if self._dialog is not None:
                res = self._dialog.handle_event(event)
                if res == "ok":
                    # Abgebrochen heisst nicht „ganz nach vorne": der Weg geht
                    # eine Ebene hoch, dorthin, wo die Serie eingerichtet wurde
                    # (gemeldet 04.08.2026: „das fuehrt aber manchmal auch
                    # direkt zum Hauptmenue").
                    grand_prix.cancel()
                    self._dialog = None
                    self.state_machine.zurueck()
                elif res == "cancel":
                    self._dialog = None
                continue

            if event.type == pygame.MOUSEMOTION:
                # Nur zeigen, nicht waehlen (gemeldet 05.08.2026). Eine Auswahl,
                # die der Zeiger im Vorbeigehen mitnimmt, ist keine.
                self._hover_index = -1
                for i, rect in self._track_card_rects():
                    if rect.collidepoint(event.pos):
                        self._hover_index = i
                        break
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                from src.core import sfx as _sfx
                if self._zurueck_knopf.hit(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._zurueck()
                    _sfx.klick_quittieren(event, vorher)
                    return
                if self._start_rect().collidepoint(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._confirm()
                    _sfx.klick_quittieren(event, vorher)
                    return
                for i, rect in self._track_card_rects():
                    if rect.collidepoint(event.pos):
                        # Erster Klick waehlt, der zweite auf dieselbe Kachel
                        # startet. Kein Zeitfenster: gemeint ist die
                        # Reihenfolge, nicht die Geschwindigkeit.
                        schon_gewaehlt = (self._klick_gewaehlt == i)
                        self.selected_index = i
                        self._klick_gewaehlt = i
                        self._track_ensure_visible()
                        vorher = _sfx.klang_zaehler()
                        if schon_gewaehlt:
                            self._confirm()
                            _sfx.klick_quittieren(event, vorher)
                        else:
                            # Eine Kachel anwaehlen ist ein Verstellen, kein
                            # Ausloesen — leiser Anlass (gemeldet 03.08.2026).
                            _sfx.klick_quittieren(event, vorher, "verstellt")
                        return
            elif event.type == pygame.MOUSEWHEEL:
                if self.track_keys:
                    max_scroll = max(0, len(self.track_keys) - 5)
                    self.track_scroll = max(0, min(max_scroll, getattr(self, "track_scroll", 0) - event.y))
            elif event.type == pygame.KEYDOWN:
                from src.core import keybindings as kb
                if event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
                    self.selected_index = (self.selected_index - 1) % len(self.track_keys)
                    self._track_ensure_visible()
                elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
                    self.selected_index = (self.selected_index + 1) % len(self.track_keys)
                    self._track_ensure_visible()
                elif event.key == pygame.K_RETURN:
                    self._confirm()
                elif event.key == pygame.K_ESCAPE:
                    self._zurueck()

    def _zurueck(self) -> None:
        """Eine Ebene hoch — dorthin, wo die Streckenwahl geoeffnet wurde.

        Der einzige Ort, der das entscheidet: Taste und Knopf nehmen denselben
        Weg (gemeldet 04.08.2026). Laeuft eine Serie, haengt am Rueckweg ihr
        Zwischenstand — dann wird erst gefragt.
        """
        from src.core import grand_prix
        if self._online_host_mode:
            self.state_machine.transition("menu", reopen="online_lobby")
            return
        if grand_prix.is_active():
            from src.ui.widgets import Dialog
            self._dialog = Dialog(
                tr("Grand Prix abbrechen?"),
                tr("Der Zwischenstand geht verloren."),
                [(tr("Ja"), "ok"), (tr("Nein"), "cancel")]
            )
            return
        from src.core import race_setup
        if race_setup.current().is_multiplayer:
            self.state_machine.transition("car_select", picker="p2")
        else:
            self.state_machine.transition(
                "car_select", vehicle_config=self.selected_vehicle_config
            )

    def _confirm(self) -> None:
        key = self.track_keys[self.selected_index]
        track_info = self._tracks_cache.get(key)
        if track_info:
            from src.core import race_setup
            race_setup.current().track_path = track_info["path"]
            if self._online_host_mode:
                self.state_machine.transition("menu", reopen="online_lobby")
            else:
                self.state_machine.transition(
                    "race",
                    vehicle_config=self.selected_vehicle_config,
                    track_path=track_info["path"],
                )

    def update(self, dt: float) -> None:
        """Update preview rotation timer."""
        self._time += dt

    def render(self, screen: pygame.Surface) -> None:
        """Render the complete track selection screen."""
        # Deep space techy background
        screen.fill((12, 12, 20))
        self._draw_grid_background(screen)

        # Screen Title
        title_surf = self.title_font.render(tr("STRECKENAUSWAHL"), True, COLOR_UI_ACCENT)
        title_rect = title_surf.get_rect(midtop=(SCREEN_WIDTH // 2, 40))
        screen.blit(title_surf, title_rect)
        self._zurueck_knopf.draw(screen)

        from src.core import grand_prix
        if grand_prix.is_active():
            gp = grand_prix.current()
            gp_text = tr("RENNEN {i} / {n}").format(i=gp.race_index + 1, n=gp.races_total)
            badge_surf = self.header_font.render(gp_text, True, (255, 215, 0))
            badge_rect = badge_surf.get_rect(midtop=(SCREEN_WIDTH // 2, 100))
            screen.blit(badge_surf, badge_rect)

        # Draw panels
        self._draw_panel(screen, self.left_panel_rect)
        self._draw_panel(screen, self.right_panel_rect)

        # Draw lists & details
        self._draw_track_list(screen)
        self._draw_track_details(screen)
        self._draw_start_button(screen)

        # Footer hints
        if self.hint_font:
            from src.ui import hints
            hint_str = hints.bar(("start", tr("Starten")), ("back", tr("Zurück")))
            hint_surf = self.hint_font.render(hint_str, True, (150, 150, 160))
            hint_rect = hint_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 50))
            screen.blit(hint_surf, hint_rect)
        theme.draw_input_badge(screen, (SCREEN_WIDTH - 20, 20))

        if self._dialog is not None:
            self._dialog.draw(screen)

    def _draw_editor_button(self, screen: pygame.Surface) -> None:
        """Eye-catching 'build your own track' button in the top-left corner."""
        rect = self._editor_button_rect()
        mx, my = display.mouse_pos()
        hover = rect.collidepoint(mx, my)
        pulse = 0.5 + 0.5 * math.sin(self._time * 3.0)
        base = (60, 48, 18) if not hover else (90, 70, 24)
        pygame.draw.rect(screen, base, rect, border_radius=8)
        glow = (255, 220, 90) if hover else (int(200 + 40 * pulse), int(160 + 40 * pulse), 40)
        pygame.draw.rect(screen, glow, rect, 3, border_radius=8)

        icon = self.header_font.render("+", True, COLOR_UI_ACCENT)
        screen.blit(icon, icon.get_rect(midleft=(rect.x + 18, rect.centery)))
        t1 = self.label_font.render(tr("STRECKEN-EDITOR"), True, (255, 235, 180))
        t2 = self.hint_font.render(tr("Eigene Strecke bauen (E)"), True, (200, 200, 210))
        screen.blit(t1, (rect.x + 58, rect.y + 14))
        screen.blit(t2, (rect.x + 58, rect.y + 42))

    def _draw_ai_difficulty(self, screen: pygame.Surface) -> None:
        """Draw the KI-difficulty chooser ( ‹ MITTEL › ) below the right panel."""
        key = self.ai_difficulty_keys[self.ai_difficulty_index]
        color = self.ai_difficulty_colors[key]
        cx = self.right_panel_rect.centerx
        y = self.right_panel_rect.bottom + 14

        # Label "KI-GEGNER:  ‹ MITTEL ›" on one compact line.
        lbl = self.label_font.render(tr("KI-GEGNER:"), True, COLOR_UI_TEXT)
        val = self.header_font.render(tr(self.ai_difficulty_labels[key]), True, color)
        arrow_l = self.header_font.render("‹", True, COLOR_UI_ACCENT)
        arrow_r = self.header_font.render("›", True, COLOR_UI_ACCENT)

        val_rect = val.get_rect(center=(cx + 60, y + 22))
        screen.blit(val, val_rect)
        screen.blit(arrow_l, arrow_l.get_rect(midright=(val_rect.left - 24, val_rect.centery)))
        screen.blit(arrow_r, arrow_r.get_rect(midleft=(val_rect.right + 24, val_rect.centery)))
        screen.blit(lbl, lbl.get_rect(midright=(val_rect.left - 60, val_rect.centery)))

    def _draw_grid_background(self, screen: pygame.Surface) -> None:
        """Draw a subtle animated tech grid on the background."""
        grid_color = (25, 25, 40)
        grid_size = 80
        offset_x = int((self._time * 20.0) % grid_size)
        offset_y = int((self._time * 15.0) % grid_size)

        for x in range(offset_x, SCREEN_WIDTH, grid_size):
            pygame.draw.line(screen, grid_color, (x, 0), (x, SCREEN_HEIGHT), 1)
        for y in range(offset_y, SCREEN_HEIGHT, grid_size):
            pygame.draw.line(screen, grid_color, (0, y), (SCREEN_WIDTH, y), 1)

    def _draw_panel(self, screen: pygame.Surface, rect: pygame.Rect) -> None:
        """Draw a semi-transparent panel with a glow border."""
        panel_bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel_bg.fill(COLOR_UI_PANEL)
        screen.blit(panel_bg, rect.topleft)
        pygame.draw.rect(screen, (50, 50, 80), rect, 2, border_radius=4)

    def _draw_track_list(self, screen: pygame.Surface) -> None:
        """Draw the track selection cards on the left side."""
        difficulty_colors = {
            "Einfach": (50, 220, 80),
            "Mittel": (255, 160, 0),
            "Schwer": (240, 50, 50),
        }

        from src.core import grand_prix
        gp_series = grand_prix.current() if grand_prix.is_active() else None

        for i, rect in self._track_card_rects():
            key = self.track_keys[i]
            track_info = self._tracks_cache.get(key)
            if not track_info:
                continue

            item_rect = rect
            is_selected = (i == self.selected_index)
            # Der Zeiger waehlt nicht mehr aus — die Kachel unter ihm bekommt
            # deshalb eine eigene, schwaechere Marke.
            is_hovered = (i == self._hover_index) and not is_selected

            # Card background
            card_surf = pygame.Surface((item_rect.width, item_rect.height), pygame.SRCALPHA)
            diff_color = difficulty_colors.get(track_info["difficulty"], COLOR_UI_TEXT)

            if is_selected:
                card_surf.fill((60, 45, 20, 220))
                pygame.draw.rect(card_surf, COLOR_UI_ACCENT, (0, 0, item_rect.width, item_rect.height), 2, border_radius=4)
                pygame.draw.rect(card_surf, COLOR_UI_ACCENT, (0, 0, 8, item_rect.height))
            else:
                card_surf.fill((38, 38, 50, 200) if is_hovered else (25, 25, 35, 180))
                pygame.draw.rect(card_surf,
                                 (110, 110, 135) if is_hovered else (50, 50, 65),
                                 (0, 0, item_rect.width, item_rect.height), 1, border_radius=4)
                pygame.draw.rect(card_surf, diff_color, (0, 0, 6, item_rect.height))

            screen.blit(card_surf, item_rect.topleft)

            # Custom-track badge. Im Grand Prix hat die Markierung "schon
            # gefahren" Vorrang: Wiederholungen sind erlaubt, aber man soll
            # nicht versehentlich zweimal dieselbe Strecke waehlen.
            badge_surf = None
            if gp_series is not None and gp_series.was_raced(key):
                badge_surf = self.hint_font.render(f"{theme.HAKEN} " + tr("gefahren"), True, (150, 155, 170))
            elif track_info.get("is_custom"):
                badge_surf = self.hint_font.render(tr("♦ Eigene"), True, (120, 200, 255))

            # Name
            name_color = COLOR_UI_ACCENT if is_selected else COLOR_UI_TEXT
            badge_w = badge_surf.get_width() + 10 if badge_surf else 0
            name_rect = pygame.Rect(item_rect.x + 20, item_rect.y + 20, item_rect.width - 40 - badge_w, 32)
            theme.text_fit(screen, tr(track_info["name"]), theme.BODY, name_color, name_rect, center=False)

            if badge_surf:
                screen.blit(badge_surf, (item_rect.right - badge_surf.get_width() - 18, item_rect.y + 22))

            # Difficulty Tag
            diff_surf = self.hint_font.render(f"{tr('SCHWIERIGKEIT:')} {tr(track_info['difficulty']).upper()}", True, diff_color)
            screen.blit(diff_surf, (item_rect.x + 20, item_rect.y + 60))

            # Length estimate (pixels to km conversion: 1000px = 1.0 km)
            length_px = track_info["max_dim"] * math.pi  # rough loop length
            length_km = length_px / 1000.0
            length_surf = self.hint_font.render(
                tr("Distanz: ca. {km} km  |  {cp} Checkpoints").format(km=f"{length_km:.1f}", cp=track_info['checkpoints_count']),
                True, (160, 160, 175) if is_selected else (100, 100, 115)
            )
            screen.blit(length_surf, (item_rect.x + 20, item_rect.y + 95))

            # Selected indicator arrow
            if is_selected:
                pulse = 0.5 + 0.5 * math.sin(self._time * 5.0)
                arrow_offset = int(pulse * 6)
                pygame.draw.polygon(screen, COLOR_UI_ACCENT, [
                    (item_rect.right - 25 + arrow_offset, item_rect.centery - 8),
                    (item_rect.right - 15 + arrow_offset, item_rect.centery),
                    (item_rect.right - 25 + arrow_offset, item_rect.centery + 8)
                ])

        # Draw vertical scrollbar if list overflows
        total = len(self.track_keys)
        if total > 5:
            sb_x = self.left_panel_rect.right - 15
            sb_y = self.left_panel_rect.y + 30
            sb_h = 740
            pygame.draw.line(screen, (40, 44, 56), (sb_x, sb_y), (sb_x, sb_y + sb_h), 4)

            handle_h = max(30, int(sb_h * (5 / total)))
            max_scroll = total - 5
            scroll_pct = self.track_scroll / max_scroll if max_scroll > 0 else 0
            handle_y = sb_y + int(scroll_pct * (sb_h - handle_h))

            pygame.draw.rect(screen, COLOR_UI_ACCENT, (sb_x - 3, handle_y, 6, handle_h), border_radius=3)

    def _draw_track_details(self, screen: pygame.Surface) -> None:
        """Draw the detailed specs, description, and rotating minimap of the active track."""
        selected_key = self.track_keys[self.selected_index]
        track_info = self._tracks_cache.get(selected_key)
        if not track_info:
            return

        # --- 1. ROTATING MINIMAP & TURNTABLE ---
        # Draw turntable grid
        pygame.draw.circle(screen, (30, 35, 50), self.turntable_center, self.turntable_radius)
        num_spokes = 16
        for i in range(num_spokes):
            angle_rad = i * (2 * math.pi / num_spokes) + (self._time * 0.1)
            end_x = self.turntable_center[0] + self.turntable_radius * math.cos(angle_rad)
            end_y = self.turntable_center[1] + self.turntable_radius * math.sin(angle_rad)
            pygame.draw.line(screen, (22, 25, 36), self.turntable_center, (end_x, end_y), 1)
        
        for r in (50, 100, 150, 200):
            pygame.draw.circle(screen, (25, 30, 42), self.turntable_center, r, 1)

        # Turquoise neon turntable ring
        pygame.draw.circle(screen, (0, 180, 200), self.turntable_center, self.turntable_radius, 2)
        for offset_deg in (0, 90, 180, 270):
            rad = math.radians(offset_deg + self._time * 12.0)
            node_x = int(self.turntable_center[0] + self.turntable_radius * math.cos(rad))
            node_y = int(self.turntable_center[1] + self.turntable_radius * math.sin(rad))
            pygame.draw.circle(screen, (100, 255, 255), (node_x, node_y), 4)

        # Draw the rotating track layout
        centerline = track_info["centerline"]
        if len(centerline) >= 2:
            cx, cy = track_info["cx"], track_info["cy"]
            max_dim = track_info["max_dim"]
            
            # Scale factor: fit within 340px bounding box
            fit_box = 340.0
            scale = fit_box / max_dim if max_dim > 0 else 1.0
            
            # Compute preview rotation angle
            rot_angle = -self._time * 0.4  # clockwise rotation
            cos_a = math.cos(rot_angle)
            sin_a = math.sin(rot_angle)
            
            screen_pts = []
            for px, py in centerline:
                # 1. Translate to origin relative to track geometric center
                dx = px - cx
                dy = py - cy
                
                # 2. Rotate
                rx = dx * cos_a - dy * sin_a
                ry = dx * sin_a + dy * cos_a
                
                # 3. Scale and translate to turntable center
                sx = self.turntable_center[0] + rx * scale
                sy = self.turntable_center[1] - ry * scale  # Y-up in world, Y-down in screen
                
                screen_pts.append((int(sx), int(sy)))

            # Draw outer glow line
            pygame.draw.lines(screen, (0, 180, 200, 80), True, screen_pts, 8)
            # Draw core neon line
            pygame.draw.lines(screen, (0, 255, 255), True, screen_pts, 3)

            # Draw orange starting line indicator dot
            if screen_pts:
                pygame.draw.circle(screen, COLOR_UI_ACCENT, screen_pts[0], 6)
                pygame.draw.circle(screen, (255, 255, 255), screen_pts[0], 3)

        # --- 2. TITLE & DESCRIPTION ---
        desc_x = self.right_panel_rect.x + 50
        desc_y = self.right_panel_rect.y + 50

        name_large = self.header_font.render(tr(track_info["name"]), True, COLOR_UI_ACCENT)
        screen.blit(name_large, (desc_x, desc_y))

        # Description paragraphs (wrapped)
        self._draw_multiline_text(
            screen,
            tr(track_info["description"]),
            self.body_font,
            (210, 210, 220),
            pygame.Rect(desc_x, desc_y + 60, 480, 200),
        )

        # --- 3. SPECS & PROGRESS BAR STACK ---
        stats_y = self.right_panel_rect.y + 350
        self._draw_stats_stack(screen, track_info, desc_x, stats_y)

    def _draw_multiline_text(
        self,
        surface: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        color: tuple[int, int, int],
        rect: pygame.Rect,
    ) -> None:
        """Utility method to wrap and render text in a bounding box."""
        words = text.split(" ")
        lines = []
        current_line = []
        for word in words:
            current_line.append(word)
            test_line = " ".join(current_line)
            if font.size(test_line)[0] > rect.width:
                current_line.pop()
                lines.append(" ".join(current_line))
                current_line = [word]
        if current_line:
            lines.append(" ".join(current_line))

        y = rect.y
        for line in lines:
            line_surf = font.render(line, True, color)
            surface.blit(line_surf, (rect.x, y))
            y += font.get_linesize() + 4

    def _draw_stats_stack(
        self,
        screen: pygame.Surface,
        track_info: dict[str, Any],
        x: int,
        y: int,
    ) -> None:
        """Render the track performance/difficulty stats stacked vertically."""
        # 1. Track Length
        length_px = track_info["max_dim"] * math.pi
        length_km = length_px / 1000.0
        # Map 3.0km - 10.0km to 0.1 - 1.0
        len_ratio = (length_km - 3.0) / 7.0
        len_ratio = max(0.1, min(1.0, len_ratio))
        len_val = f"{length_km:.2f} km"

        # 2. Difficulty
        diff_str = track_info["difficulty"]
        diff_colors = {
            "Einfach": (50, 220, 80),
            "Mittel": (255, 160, 0),
            "Schwer": (240, 50, 50),
        }
        diff_ratios = {
            "Einfach": 0.33,
            "Mittel": 0.66,
            "Schwer": 1.0,
        }
        diff_ratio = diff_ratios.get(diff_str, 0.5)
        diff_color = diff_colors.get(diff_str, COLOR_UI_ACCENT)

        # 3. Checkpoints
        cps = track_info["checkpoints_count"]
        # Map 2 to 8 checkpoints to 0.2 - 1.0
        cp_ratio = (cps - 2) / 6.0
        cp_ratio = max(0.1, min(1.0, cp_ratio))
        cp_val = tr("{cp} Checkpoints").format(cp=cps)

        # 4. Width
        width_val_raw = track_info["track_width"]
        # Map 200 to 350 width to 0.1 - 1.0
        width_ratio = (width_val_raw - 200) / 150.0
        width_ratio = max(0.1, min(1.0, width_ratio))
        width_val = f"{width_val_raw:.0f} px"

        stats = [
            (tr("Streckenlänge"), len_ratio, len_val, COLOR_UI_ACCENT),
            (tr("Schwierigkeitsgrad"), diff_ratio, tr(diff_str).upper(), diff_color),
            (tr("Runden-Sektoren"), cp_ratio, cp_val, (0, 220, 255)),
            (tr("Fahrbahnbreite (Road Width)"), width_ratio, width_val, (220, 100, 255)),
        ]

        bar_width = 480
        bar_height = 16
        gap_y = 80

        for i, (label, ratio, val_str, color) in enumerate(stats):
            cell_x = x
            cell_y = y + i * gap_y

            # Render label and value text
            label_surf = self.label_font.render(label, True, COLOR_UI_TEXT)
            screen.blit(label_surf, (cell_x, cell_y))

            val_surf = self.label_font.render(val_str, True, color)
            val_rect = val_surf.get_rect(topright=(cell_x + bar_width, cell_y))
            screen.blit(val_surf, val_rect)

            # Draw progress bar background (dark bezel line)
            bar_rect = pygame.Rect(cell_x, cell_y + 35, bar_width, bar_height)
            pygame.draw.rect(screen, (30, 30, 45), bar_rect, border_radius=4)
            pygame.draw.rect(screen, (50, 50, 70), bar_rect, 1, border_radius=4)

            # Draw filled portion
            fill_width = int(bar_width * ratio)
            if fill_width > 0:
                fill_rect = pygame.Rect(cell_x, cell_y + 35, fill_width, bar_height)
                pygame.draw.rect(screen, color, fill_rect, border_radius=4)

                # Light glow overlay line
                pygame.draw.line(screen, (255, 255, 255), (cell_x, cell_y + 36), (cell_x + fill_width, cell_y + 36), 1)
