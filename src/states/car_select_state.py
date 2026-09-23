"""Car selection state – menu to select one of five vehicles with specs and 2D rotation preview."""
from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

import pygame

from src.states.base_state import BaseState
from src.core.settings import (
    SCREEN_WIDTH,
    SCREEN_HEIGHT,
    COLOR_UI_BG,
    COLOR_UI_TEXT,
    COLOR_UI_ACCENT,
    COLOR_UI_PANEL,
    KMH_PER_PXS,
)
from src.entities.vehicle_factory import VehicleFactory
from src.entities.components.renderer import VehicleRenderer
from src.core.i18n import tr

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


#: Der schmalste Balken, den das langsamste Fahrzeug noch bekommt. Null waere
#: ehrlich, sieht aber aus wie ein Fehler — ein Rest bleibt stehen.
_BALKEN_MINIMUM = 0.08


def _top_speed_spanne() -> tuple[float, float]:
    """Langsamstes und schnellstes Fahrzeug der Flotte, in px/s.

    Gemessen statt geraten: kommt ein Fahrzeug dazu, verschiebt sich die Skala
    von selbst. Eine feste Spanne im Code war genau der Fehler — sie stand in
    km/h, waehrend ``max_speed`` in px/s gefuehrt wird.
    """
    configs = VehicleFactory.get_available_configs()
    if not configs:
        # Im Spiel laedt der Ladebildschirm die Flotte lange vorher. Wer den
        # Balken einzeln benutzt (Test, Werkzeug), soll dafuer nicht erst die
        # Fabrik von Hand fuellen muessen.
        VehicleFactory.load_all_configs()
        configs = VehicleFactory.get_available_configs()
    werte = [c.max_speed for c in configs]
    if not werte:
        return 0.0, 1.0
    return min(werte), max(werte)


def top_speed_anteil(config) -> float:
    """Wie voll der Hoechstgeschwindigkeits-Balken steht: 0 bis 1.

    Gemeldet am 05.08.2026: „Blaue Statusbar bei Top Speed ist bei jedem
    Fahrzeug voll." Gerechnet wurde ``(max_speed - 160) / 80`` — eine Spanne in
    km/h gegen einen Wert in px/s. Die Flotte liegt zwischen 597 und 984 px/s,
    also lag **jedes** Fahrzeug ueber der Obergrenze und klemmte auf 1,0.

    Bezugspunkt sind jetzt, wie gewuenscht, die tatsaechlichen Grenzwerte ueber
    alle Fahrzeuge.
    """
    langsamstes, schnellstes = _top_speed_spanne()
    spanne = schnellstes - langsamstes
    if spanne <= 0.0:
        return 1.0
    anteil = (config.max_speed - langsamstes) / spanne
    anteil = _BALKEN_MINIMUM + anteil * (1.0 - _BALKEN_MINIMUM)
    return max(0.0, min(1.0, anteil))


class CarSelectState(BaseState):
    """Interactive screen allowing the player to select a vehicle.

    Shows car cards on the left, detailed specs and description on the right,
    and a rotating 2D model of the currently highlighted car in the center-right.
    """

    def __init__(self, state_machine: StateMachine) -> None:
        super().__init__(state_machine)
        self.selected_index: int = 0
        self.car_keys: list[str] = ["rookie", "supercar", "drifter", "limousine", "electric"]
        self.picker: str = "p1"
        
        # UI configuration
        self.left_panel_rect = pygame.Rect(80, 160, 480, 800)
        self.right_panel_rect = pygame.Rect(600, 160, 1240, 800)
        #: Der Rueckweg als Knopf, oben links ueber der linken Spalte.
        from src.ui.widgets import ZurueckKnopf
        self._zurueck_knopf = ZurueckKnopf(80, 72)
        self.turntable_center = (1485, 380)
        self.turntable_radius = 160

        # Fonts
        self.title_font: pygame.font.Font | None = None
        self.header_font: pygame.font.Font | None = None
        self.body_font: pygame.font.Font | None = None
        self.label_font: pygame.font.Font | None = None
        self.hint_font: pygame.font.Font | None = None

        # Renderers cache (to avoid rebuilding surfaces every frame)
        self._renderers: dict[str, VehicleRenderer] = {}
        self._time: float = 0.0

    def enter(self, **kwargs) -> None:
        """Set up fonts and ensure all vehicles are loaded."""
        self.title_font = pygame.font.Font(None, 80)
        self.header_font = pygame.font.Font(None, 46)
        self.body_font = pygame.font.Font(None, 32)
        self.label_font = pygame.font.Font(None, 28)
        self.hint_font = pygame.font.Font(None, 24)

        # Restrict the roster to the lobby's chosen vehicle class.
        from src.core import race_setup, gamepad, profile
        s = race_setup.current()
        self.car_keys = list(s.class_keys()) or \
            ["rookie", "supercar", "drifter", "limousine", "electric"]

        self._online_mode = kwargs.get("online_mode", False)
        self.picker = kwargs.get("picker", "p1")
        if s.is_multiplayer:
            active_device = s.p1_input if self.picker == "p1" else s.p2_input
            gamepad.set_device_filter(active_device)
            veh_key = s.player_vehicle if self.picker == "p1" else s.player2_vehicle
        else:
            gamepad.set_device_filter(None)
            veh_key = s.player_vehicle
        # Ein ausdruecklich uebergebenes Fahrzeug sticht die Lobbywahl — es ist
        # eine Anweisung und keine Voreinstellung. Genau darueber kommt die
        # Werkstatt zurueck: wer dort das Fahrzeug wechselt, soll es hier
        # ausgewaehlt vorfinden und nicht wieder das, mit dem er hingegangen ist
        # (gemeldet 05.08.2026). Vorher galt das nur im Einzelspieler.
        veh_key = kwargs.get("vehicle_config") or veh_key

        # Select vehicle passed in kwargs if valid, else keep in range.
        if veh_key in self.car_keys:
            self.selected_index = self.car_keys.index(veh_key)
        elif self.selected_index >= len(self.car_keys):
            self.selected_index = 0
        self.car_scroll = 0
        #: Welche Kachel bereits **angeklickt** ausgewaehlt wurde. Nicht
        #: dasselbe wie ``selected_index``: mit dem kommt man schon ausgewaehlt
        #: an (aus der Lobby, aus der Werkstatt), und dann waere der erste Klick
        #: gleich der zweite. -1 heisst: in diesem Besuch noch nichts geklickt.
        self._klick_gewaehlt = -1
        #: Kachel unter dem Zeiger — nur Anzeige, keine Auswahl.
        self._hover_index = -1

        # Make sure configs are loaded
        if not VehicleFactory.get_available_configs():
            VehicleFactory.load_all_configs("data/vehicles")

        # Pre-build vehicle renderers in der jeweils gewaehlten Lackierung.
        self._renderers.clear()
        for key in self.car_keys:
            config = VehicleFactory.get_config(key)
            if config:
                self._renderers[key] = VehicleRenderer(
                    config.width_px,
                    config.height_px,
                    config.color_primary,
                    config.color_secondary,
                    config.visual_type,
                    lack=profile.current().paint(key),
                    config_key=key,
                )

    def _car_card_rects(self) -> list[tuple[int, pygame.Rect]]:
        x = self.left_panel_rect.x + 20
        y_start = self.left_panel_rect.y + 30
        item_height = 140
        spacing = 15
        out = []
        start = getattr(self, "car_scroll", 0)
        end = min(len(self.car_keys), start + 5)
        for row, i in enumerate(range(start, end)):
            out.append((i, pygame.Rect(x, y_start + row * (item_height + spacing), 440, item_height)))
        return out

    def _car_ensure_visible(self) -> None:
        if self.selected_index < self.car_scroll:
            self.car_scroll = self.selected_index
        elif self.selected_index >= self.car_scroll + 5:
            self.car_scroll = self.selected_index - 5 + 1

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        from src.core import race_setup
        s = race_setup.current()
        active_device = s.p2_input if (s.is_multiplayer and self.picker == "p2") else s.p1_input
        if s.is_multiplayer:
            active_device = s.p1_input if self.picker == "p1" else s.p2_input
        else:
            active_device = "keyboard"
        is_kb = (active_device == "keyboard")

        for event in events:
            if event.type == pygame.MOUSEMOTION:
                if is_kb:
                    # Nur zeigen, nicht waehlen (gemeldet 05.08.2026): „mit dem
                    # ersten Mausklick diese hervorgehoben werden (Ausgewählt
                    # bleiben auch wenn ich dann über die anderen
                    # auswhlmöglichkeiten drüber hovere)". Vorher zog jede
                    # Mausbewegung die Auswahl mit — wer sein Fahrzeug gewaehlt
                    # hatte und den Zeiger nur wegbewegte, hatte ein anderes.
                    self._hover_index = -1
                    for i, rect in self._car_card_rects():
                        if rect.collidepoint(event.pos):
                            self._hover_index = i
                            break
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not is_kb:
                    continue
                from src.core import sfx as _sfx
                if self._zurueck_knopf.hit(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._zurueck()
                    _sfx.klick_quittieren(event, vorher)
                    return
                if self._werkstatt_rect().collidepoint(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._werkstatt_oeffnen()
                    # Gesperrt heisst hier: fuer dieses Fahrzeug ist kein Lack
                    # abgestimmt. Dann fuehrt der Knopf nirgendwohin, und das
                    # soll man hoeren (gemeldet 03.08.2026).
                    from src.core import lack as _lack
                    key = self.car_keys[self.selected_index] if self.car_keys else ""
                    _sfx.klick_quittieren(event, vorher,
                                          "ausgeloest" if key and _lack.lackierbar(key)
                                          else "gesperrt")
                    return
                if self._weiter_rect().collidepoint(event.pos):
                    vorher = _sfx.klang_zaehler()
                    self._confirm()
                    _sfx.klick_quittieren(event, vorher)
                    return
                for i, rect in self._car_card_rects():
                    if rect.collidepoint(event.pos):
                        # Erster Klick waehlt, der zweite auf dieselbe Kachel
                        # fuehrt weiter. Ohne Zeitfenster: „mit dem nächsten
                        # klick gehts dann weiter" ist eine Aussage ueber die
                        # Reihenfolge, nicht ueber die Geschwindigkeit — ein
                        # Doppelklick-Fenster von 400 ms hat dagegen jeden
                        # bestraft, der zwischendurch hinsieht.
                        schon_gewaehlt = (self._klick_gewaehlt == i)
                        self.selected_index = i
                        self._klick_gewaehlt = i
                        self._car_ensure_visible()
                        vorher = _sfx.klang_zaehler()
                        if schon_gewaehlt:
                            self._confirm()
                            _sfx.klick_quittieren(event, vorher)
                        else:
                            _sfx.klick_quittieren(event, vorher, "verstellt")
                        return
            elif event.type == pygame.MOUSEWHEEL:
                if not is_kb:
                    continue
                if self.car_keys:
                    max_scroll = max(0, len(self.car_keys) - 5)
                    self.car_scroll = max(0, min(max_scroll, getattr(self, "car_scroll", 0) - event.y))
            elif event.type == pygame.KEYDOWN:
                from src.core import keybindings as kb
                if event.key in (pygame.K_UP, pygame.K_w, kb.get("throttle")):
                    self.selected_index = (self.selected_index - 1) % len(self.car_keys)
                    self._car_ensure_visible()
                elif event.key in (pygame.K_DOWN, pygame.K_s, kb.get("brake")):
                    self.selected_index = (self.selected_index + 1) % len(self.car_keys)
                    self._car_ensure_visible()
                elif event.key == pygame.K_RETURN:
                    self._confirm()
                elif event.key == pygame.K_l:
                    self._werkstatt_oeffnen()
                elif event.key == pygame.K_ESCAPE:
                    self._zurueck()

    def _zurueck(self) -> None:
        """Eine Ebene hoch — dorthin, wo die Fahrzeugwahl geoeffnet wurde.

        Der einzige Ort, der das entscheidet: Taste und Knopf nehmen denselben
        Weg (gemeldet 04.08.2026). Bei zwei Spielern liegt zwischen den beiden
        Wahlen eine Ebene, also geht es von Spieler 2 erst zu Spieler 1 zurueck
        und nicht gleich in die Lobby.
        """
        from src.core import race_setup
        s = race_setup.current()
        if self._online_mode:
            self.state_machine.transition("menu", reopen="online_lobby")
        elif s.is_multiplayer:
            if self.picker == "p2":
                self.state_machine.transition("car_select", picker="p1")
            else:
                self.state_machine.transition("menu", reopen="mp_lobby")
        else:
            self.state_machine.transition("menu", reopen="lobby")

    def _confirm(self) -> None:
        from src.core import race_setup
        s = race_setup.current()
        if self._online_mode:
            s.player_vehicle = self.car_keys[self.selected_index]
            self.state_machine.transition("menu", reopen="online_lobby")
        elif s.is_multiplayer:
            if self.picker == "p1":
                s.player_vehicle = self.car_keys[self.selected_index]
                self.state_machine.transition("car_select", picker="p2")
            else:
                s.player2_vehicle = self.car_keys[self.selected_index]
                self._weiter_nach_fahrzeugwahl(s)
        else:
            s.player_vehicle = self.car_keys[self.selected_index]
            self._weiter_nach_fahrzeugwahl(s)

    def _weiter_nach_fahrzeugwahl(self, s) -> None:
        """Grand Prix geht in die Uebersicht, alles andere in die Streckenwahl.

        In der Uebersicht steht die Serie zwischen den Laeufen: dort wird die
        naechste Strecke gewaehlt und der Stand gezeigt. Die Streckenauswahl
        kennt beides nicht und startet direkt ins Rennen.
        """
        from src.core import grand_prix
        if s.mode == "Grand Prix" and grand_prix.is_active():
            self.state_machine.transition("menu", reopen="gp_overview")
            return
        self.state_machine.transition("track_select", vehicle_config=s.player_vehicle)

    def exit(self) -> None:
        """Clear device filter when leaving vehicle selection."""
        from src.core import gamepad
        gamepad.set_device_filter(None)

    def update(self, dt: float) -> None:
        """Update animation timer."""
        self._time += dt

    def render(self, screen: pygame.Surface) -> None:
        """Render the complete car selection screen."""
        # Deep space techy background
        screen.fill((12, 12, 20))
        self._draw_grid_background(screen)

        # Screen Title
        from src.core import race_setup, profile
        s = race_setup.current()
        if s.is_multiplayer:
            if self.picker == "p1":
                p_name = profile.current().username or "Spieler 1"
                title_text = tr("SPIELER 1 WÄHLT — {n}").format(n=p_name)
                title_color = (255, 120, 0) # Orange
            else:
                p2_name = s.player2_name or "Spieler_2"
                title_text = tr("SPIELER 2 WÄHLT — {n}").format(n=p2_name)
                title_color = (60, 150, 255) # Blue
        else:
            title_text = tr("FAHRZEUGAUSWAHL")
            title_color = COLOR_UI_ACCENT

        title_surf = self.title_font.render(title_text, True, title_color)
        title_rect = title_surf.get_rect(midtop=(SCREEN_WIDTH // 2, 50))
        screen.blit(title_surf, title_rect)

        # Draw left and right glassmorphic panels
        self._draw_panel(screen, self.left_panel_rect)
        self._draw_panel(screen, self.right_panel_rect)

        # Draw vehicle list in the left panel
        self._draw_vehicle_list(screen)

        # Draw details in the right panel
        self._draw_vehicle_details(screen)

        self._zurueck_knopf.draw(screen)

        # Kurzweg in die Werkstatt, daneben der Weg nach vorn
        self._draw_werkstatt_button(screen)
        self._draw_weiter_button(screen)

        # Draw footer controls hints
        if self.hint_font:
            from src.ui import hints
            hint_str = hints.bar(("confirm", tr("Wählen")), ("back", tr("Zurück")))
            hint_surf = self.hint_font.render(hint_str, True, (150, 150, 160))
            hint_rect = hint_surf.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 50))
            screen.blit(hint_surf, hint_rect)
        from src.ui import theme as _th
        _th.draw_input_badge(screen, (SCREEN_WIDTH - 20, 20))

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
        # Background
        panel_bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        panel_bg.fill(COLOR_UI_PANEL)
        screen.blit(panel_bg, rect.topleft)

        # Border outline
        pygame.draw.rect(screen, (50, 50, 80), rect, 2, border_radius=4)

    def _draw_vehicle_list(self, screen: pygame.Surface) -> None:
        """Draw the vehicle selection items on the left side."""
        for i, rect in self._car_card_rects():
            key = self.car_keys[i]
            config = VehicleFactory.get_config(key)
            if not config:
                continue

            item_rect = rect
            is_selected = (i == self.selected_index)
            # Der Zeiger waehlt nicht mehr aus, er zeigt nur noch. Deshalb
            # braucht die Kachel unter ihm eine eigene, schwaechere Marke —
            # sonst gaebe die Maus gar keine Rueckmeldung mehr darueber, was
            # ein Klick treffen wuerde.
            is_hovered = (i == self._hover_index) and not is_selected

            # Card background
            card_surf = pygame.Surface((item_rect.width, item_rect.height), pygame.SRCALPHA)
            if is_selected:
                # Golden-orange highlights for selected card
                card_surf.fill((60, 45, 20, 220))
                pygame.draw.rect(card_surf, COLOR_UI_ACCENT, (0, 0, item_rect.width, item_rect.height), 2, border_radius=4)
                # Left accent border strip
                pygame.draw.rect(card_surf, COLOR_UI_ACCENT, (0, 0, 8, item_rect.height))
            else:
                card_surf.fill((38, 38, 50, 200) if is_hovered else (25, 25, 35, 180))
                pygame.draw.rect(card_surf,
                                 (110, 110, 135) if is_hovered else (50, 50, 65),
                                 (0, 0, item_rect.width, item_rect.height), 1, border_radius=4)
                # Farbstreifen = gewaehlte Lackfarbe. Vorher stand hier
                # config.color_primary — ein Wert, den man am Auto nie sieht,
                # seit jedes Fahrzeug ein PNG hat.
                pygame.draw.rect(card_surf, self._streifenfarbe(key, config),
                                 (0, 0, 6, item_rect.height))

            screen.blit(card_surf, item_rect.topleft)

            # Text content
            from src.ui import theme as _th
            name_color = COLOR_UI_ACCENT if is_selected else COLOR_UI_TEXT
            name_rect = pygame.Rect(item_rect.x + 20, item_rect.y + 20, item_rect.width - 40, 32)
            _th.text_fit(screen, tr(config.name), _th.BODY, name_color, name_rect, center=False)

            # Visual type / tag
            type_labels = {
                "rookie": "HATCHBACK - FRONTANTRIEB",
                "supercar": "SUPERSPORT - ALLRAD",
                "drifter": "DRIFTING - HECKANTRIEB",
                "limousine": "LUXUS-COUPÉ - DYNAMISCH",
                "electric": "ELEKTRO-PROTOTYP - DIREKT",
            }
            tag_text = tr(type_labels.get(config.visual_type, "FAHRZEUG"))
            tag_color = (255, 255, 255) if is_selected else (130, 130, 150)
            tag_surf = self.hint_font.render(tag_text, True, tag_color)
            screen.blit(tag_surf, (item_rect.x + 20, item_rect.y + 60))

            # Small specs summary
            n_gears = len(config.gear_ratios or [1.0])
            specs_text = f"{config.mass:.0f} kg  |  {config.max_speed * KMH_PER_PXS:.0f} km/h  |  " + tr("{n} Gänge").format(n=n_gears)
            if config.visual_type == "electric":
                specs_text = f"{config.mass:.0f} kg  |  {config.max_speed * KMH_PER_PXS:.0f} km/h  |  Direct Drive"
            specs_surf = self.hint_font.render(specs_text, True, (160, 160, 175) if is_selected else (100, 100, 115))
            screen.blit(specs_surf, (item_rect.x + 20, item_rect.y + 95))

            # Selected indicator arrow
            if is_selected:
                # Pulsing arrow icon on the right
                pulse = 0.5 + 0.5 * math.sin(self._time * 5.0)
                arrow_offset = int(pulse * 6)
                pygame.draw.polygon(screen, COLOR_UI_ACCENT, [
                    (item_rect.right - 25 + arrow_offset, item_rect.centery - 8),
                    (item_rect.right - 15 + arrow_offset, item_rect.centery),
                    (item_rect.right - 25 + arrow_offset, item_rect.centery + 8)
                ])

        # Draw vertical scrollbar if list overflows
        total = len(self.car_keys)
        if total > 5:
            sb_x = self.left_panel_rect.right - 15
            sb_y = self.left_panel_rect.y + 30
            sb_h = 740
            pygame.draw.line(screen, (40, 44, 56), (sb_x, sb_y), (sb_x, sb_y + sb_h), 4)

            handle_h = max(30, int(sb_h * (5 / total)))
            max_scroll = total - 5
            scroll_pct = self.car_scroll / max_scroll if max_scroll > 0 else 0
            handle_y = sb_y + int(scroll_pct * (sb_h - handle_h))

            pygame.draw.rect(screen, COLOR_UI_ACCENT, (sb_x - 3, handle_y, 6, handle_h), border_radius=3)

    @staticmethod
    def _streifenfarbe(key: str, config) -> tuple[int, int, int]:
        """Farbe des Kachelstreifens: die gewaehlte Lackfarbe, sonst Grau.

        Werkslack hat keine eigene Farbe — ein Streifen in `color_primary` waere
        eine Farbe, die am Auto nirgends vorkommt.
        """
        from src.core import lack, profile
        teile = lack.zerlege(profile.current().paint(key))
        if teile is None:
            return (110, 114, 128)
        return lack.farbe(teile[1])["rgb"]

    def _werkstatt_rect(self) -> pygame.Rect:
        return pygame.Rect(self.left_panel_rect.x,
                           self.left_panel_rect.bottom + 16, 300, 56)

    def _weiter_rect(self) -> pygame.Rect:
        """Der sichtbare Weg nach vorn, rechts neben dem Werkstatt-Knopf.

        Gefordert am 05.08.2026: „Ich denke es ergibt auch sinn wenn es in er
        Fahrzeugauswahl einen weiter button gibt." Der zweite Klick auf die
        Kachel tut dasselbe — aber er ist nirgends angeschrieben, und ein Weg,
        den man kennen muss, ist keiner.
        """
        r = self._werkstatt_rect()
        return pygame.Rect(r.right + 16, r.y, 300, 56)

    def _weiter_beschriftung(self) -> str:
        """Online wird nur gewaehlt — gestartet wird in der Lobby.

        „Muss online natürlich anders gelöst werden hier wird ja nur gewählt da
        das Rennen über den Button in der Lobby gestartet wird." Deshalb steht
        dort „Übernehmen" und nicht „Weiter": der Knopf legt die Wahl ab und
        geht zurueck, er fuehrt nicht weiter.
        """
        return tr("Übernehmen") if self._online_mode else tr("Weiter")

    def _draw_weiter_button(self, screen: pygame.Surface) -> None:
        from src.core import display
        from src.ui import theme as _th
        r = self._weiter_rect()
        hover = r.collidepoint(display.mouse_pos())
        fill = (58, 44, 16) if hover else (44, 34, 14)
        pygame.draw.rect(screen, fill, r, border_radius=6)
        pygame.draw.rect(screen, _th.ACCENT_HOT if hover else _th.ACCENT, r, 2,
                         border_radius=6)
        _th.text_fit(screen, self._weiter_beschriftung() + "  ›", _th.BODY,
                     _th.ACCENT_HOT if hover else _th.ACCENT,
                     r.inflate(-24, 0), center=True)

    def _draw_werkstatt_button(self, screen: pygame.Surface) -> None:
        from src.core import display, lack
        from src.ui import theme as _th
        r = self._werkstatt_rect()
        key = self.car_keys[self.selected_index] if self.car_keys else ""
        an = bool(key) and lack.lackierbar(key)
        hover = an and r.collidepoint(display.mouse_pos())
        if not an:
            fill, border, txt = (26, 28, 36), _th.DISABLED, _th.DISABLED
        else:
            fill = (46, 50, 62) if hover else (32, 36, 46)
            border = _th.ACCENT_HOT if hover else _th.BORDER_LIGHT
            txt = _th.TEXT
        pygame.draw.rect(screen, fill, r, border_radius=8)
        pygame.draw.rect(screen, border, r, 2, border_radius=8)
        # „Werkstatt" und nicht „Lackieren": der Knopf fuehrt in die Werkstatt,
        # und dort steht mehr als nur die Lackwahl (gemeldet 03.08.2026). Ein
        # Knopf soll heissen, wohin er fuehrt.
        _th.text_fit(screen, tr("Werkstatt"), _th.BODY, txt, r.inflate(-24, 0), center=True)
        if not an:
            _th.text(screen, tr("Für dieses Fahrzeug noch nicht abgestimmt"), _th.SMALL,
                     _th.TEXT_FAINT, (r.right + 16, r.centery - 9), max_w=420)

    def _werkstatt_oeffnen(self) -> None:
        """Kurzweg in die Werkstatt, mit genau dem Rueckweg, den wir gekommen sind.

        Die Fahrzeugauswahl hat drei Rueckwege (online, lokal p1/p2,
        Einzelspieler). Statt sie in der Werkstatt nachzubauen, geben wir den
        eigenen Zustand samt Argumenten mit — dann landet man wieder hier, mit
        unveraenderter Fahrzeug- und Streckenwahl.
        """
        from src.core import lack
        key = self.car_keys[self.selected_index] if self.car_keys else ""
        if not key or not lack.lackierbar(key):
            return
        zurueck = ("car_select", {"picker": self.picker,
                                  "online_mode": self._online_mode,
                                  "vehicle_config": key})
        self.state_machine.transition("menu", reopen="werkstatt",
                                      vehicle_config=key, rueckweg=zurueck)

    def _draw_vehicle_details(self, screen: pygame.Surface) -> None:
        """Draw the detailed specs, description, and turntable of the active vehicle."""
        selected_key = self.car_keys[self.selected_index]
        config = VehicleFactory.get_config(selected_key)
        renderer = self._renderers.get(selected_key)
        if not config or not renderer:
            return

        # --- 1. TURNTABLE & 2D PREVIEW ---
        # Draw tech turntable grid
        pygame.draw.circle(screen, (30, 35, 50), self.turntable_center, self.turntable_radius)
        # Radial lines
        num_spokes = 16
        for i in range(num_spokes):
            angle_rad = i * (2 * math.pi / num_spokes) + (self._time * 0.1)
            end_x = self.turntable_center[0] + self.turntable_radius * math.cos(angle_rad)
            end_y = self.turntable_center[1] + self.turntable_radius * math.sin(angle_rad)
            pygame.draw.line(screen, (22, 25, 36), self.turntable_center, (end_x, end_y), 1)
        
        # Inner rings
        for r in (50, 100, 150, 200):
            pygame.draw.circle(screen, (25, 30, 42), self.turntable_center, r, 1)

        # Turquoise/Cyan neon turntable edge ring
        pygame.draw.circle(screen, (0, 180, 200), self.turntable_center, self.turntable_radius, 2)
        # Subtle blinking nodes on the turntable edge
        for offset_deg in (0, 90, 180, 270):
            rad = math.radians(offset_deg + self._time * 12.0)
            node_x = int(self.turntable_center[0] + self.turntable_radius * math.cos(rad))
            node_y = int(self.turntable_center[1] + self.turntable_radius * math.sin(rad))
            pygame.draw.circle(screen, (100, 255, 255), (node_x, node_y), 4)

        # Draw the rotating car model in the center of the turntable
        # Pymunk coordinate space (Y is up, which maps to -Y in Pygame)
        world_y = SCREEN_HEIGHT - self.turntable_center[1]
        car_world_pos = (self.turntable_center[0], world_y)
        rotation_angle = (self._time * 0.8) % (2 * math.pi)

        # Das 3D-Modell auf dem Drehteller, in der Lackierung aus dem Profil.
        # Ohne OpenGL bleibt das Sprite darunter.
        if self._auto_3d_zeichnen(screen, selected_key, rotation_angle):
            self._details_text_zeichnen(screen, config)
            return

        # Draw car shadow slightly offset
        scale_factor = 1.6
        shadow_w = int(config.height_px * scale_factor)
        shadow_h = int(config.width_px * scale_factor)
        shadow_offset = pygame.Vector2(-12, 12)

        # Draw shadow shape (simplified rotating)
        shadow_surf = pygame.Surface((shadow_w + 16, shadow_h + 16), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow_surf, (0, 0, 0, 80), (4, 4, shadow_w, shadow_h))
        shadow_rot = pygame.transform.rotate(shadow_surf, math.degrees(rotation_angle))
        shadow_rot_rect = shadow_rot.get_rect(center=(self.turntable_center[0] + shadow_offset.x, self.turntable_center[1] + shadow_offset.y))
        screen.blit(shadow_rot, shadow_rot_rect)

        # Draw actual vector vehicle with scale
        renderer.draw(screen, car_world_pos, rotation_angle, pygame.Vector2(0, 0), scale=scale_factor)
        self._details_text_zeichnen(screen, config)

    def _auto_3d_zeichnen(self, screen: pygame.Surface, key: str, winkel_rad: float) -> bool:
        from src.core import lack
        from src.core import profile as _prof
        from src.states.menu.werkstatt_page import fahrzeugvorschau
        vorschau = fahrzeugvorschau()
        if vorschau is None:
            return False
        kasten = pygame.Rect(0, 0, int(self.turntable_radius * 2.6), int(self.turntable_radius * 1.7))
        kasten.center = (self.turntable_center[0], self.turntable_center[1] - 10)
        try:
            ergebnis = vorschau.bild(key, lack.werte_3d(_prof.current().paint(key)),
                                     math.degrees(winkel_rad), kasten.size)
        except Exception as fehler:                    # pragma: no cover - Treiber
            print(f"[CarSelect] 3D-Vorschau fehlgeschlagen: {fehler}")
            return False
        if ergebnis is None:
            return False
        pixel, groesse = ergebnis
        screen.blit(pygame.image.frombuffer(pixel, groesse, "RGBA"), kasten.topleft)
        return True

    def _details_text_zeichnen(self, screen: pygame.Surface, config) -> None:
        # --- 2. TITLE & DESCRIPTION ---
        # Draw vehicle header
        desc_x = self.right_panel_rect.x + 50
        desc_y = self.right_panel_rect.y + 50

        name_large = self.header_font.render(tr(config.name), True, COLOR_UI_ACCENT)
        screen.blit(name_large, (desc_x, desc_y))

        # Description text block (wrapped)
        self._draw_multiline_text(
            screen,
            tr(config.description),
            self.body_font,
            (210, 210, 220),
            pygame.Rect(desc_x, desc_y + 60, 480, 200),
        )

        # --- 3. SPECS & PROGRESS BAR GRID ---
        stats_y = self.right_panel_rect.y + 350
        self._draw_stats_grid(screen, config, desc_x, stats_y)

        # --- 4. POWER CURVE (kW / RPM) UNDER TURNTABLE ---
        self._draw_power_curve(screen, config)

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

    def _draw_stats_grid(
        self,
        screen: pygame.Surface,
        config: any,
        x: int,
        y: int,
    ) -> None:
        """Render the performance stats progress bars in a vertical stack."""
        # Calculate stats on 0.0 to 1.0 scale
        # 1. Top Speed — Skala aus der Flotte, siehe top_speed_anteil()
        speed_ratio = top_speed_anteil(config)
        speed_val = f"{config.max_speed * KMH_PER_PXS:.0f} km/h"

        # 2. Acceleration (engine power / mass, roughly 20 to 36)
        p_to_w = config.engine_power / config.mass
        accel_ratio = (p_to_w - 20.0) / 16.0
        accel_ratio = max(0.1, min(1.0, accel_ratio))
        accel_val = f"{p_to_w:.1f} W/kg"

        # 3. Handling (turn speed * grip, roughly 1.3 to 2.1)
        handling_val_raw = config.turn_speed * config.grip
        handling_ratio = (handling_val_raw - 1.2) / 1.0
        handling_ratio = max(0.1, min(1.0, handling_ratio))
        handling_val = tr("Sehr Agil") if handling_ratio > 0.8 else (tr("Agil") if handling_ratio > 0.5 else tr("Stabil"))

        # 4. Driftiness (lower grip + lower drift threshold increases score)
        drift_score = (1.0 - config.grip) + (1.0 - config.drift_threshold)
        drift_ratio = (drift_score - 0.3) / 0.5
        drift_ratio = max(0.1, min(1.0, drift_ratio))
        drift_val = tr("Extrem") if drift_ratio > 0.8 else (tr("Moderat") if drift_ratio > 0.4 else tr("Gering"))

        stats = [
            (tr("Höchstgeschwindigkeit"), speed_ratio, speed_val),
            (tr("Beschleunigung"), accel_ratio, accel_val),
            (tr("Handling / Agilität"), handling_ratio, handling_val),
            (tr("Drift-Neigung (Driftiness)"), drift_ratio, drift_val),
        ]

        bar_width = 480
        bar_height = 16
        gap_y = 80

        # Render stats stacked vertically
        for i, (label, ratio, val_str) in enumerate(stats):
            cell_x = x
            cell_y = y + i * gap_y

            # Render label and value text
            label_surf = self.label_font.render(label, True, COLOR_UI_TEXT)
            screen.blit(label_surf, (cell_x, cell_y))

            val_surf = self.label_font.render(val_str, True, COLOR_UI_ACCENT)
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
                # Use a gradient coloring based on the ratio
                bar_color = (
                    int(255 * (1.0 - ratio)),
                    int(200 * ratio + 55),
                    int(255 * ratio),
                )
                bar_color = (
                    max(0, min(255, bar_color[0])),
                    max(0, min(255, bar_color[1])),
                    max(0, min(255, bar_color[2])),
                )
                pygame.draw.rect(screen, bar_color, fill_rect, border_radius=4)

                # Neon light overlay glow on the fill
                pygame.draw.line(screen, (255, 255, 255), (cell_x, cell_y + 36), (cell_x + fill_width, cell_y + 36), 1)

    def _draw_power_curve(self, screen: pygame.Surface, config) -> None:
        """Render a compact power curve (kW over RPM) under the turntable."""
        gx = 1215
        gy = 570
        gw = 540
        gh = 300

        # Draw tech panel background
        panel_rect = pygame.Rect(gx, gy, gw, gh)
        pygame.draw.rect(screen, (16, 18, 28), panel_rect)
        pygame.draw.rect(screen, (0, 180, 200), panel_rect, 1, border_radius=4)

        # Kopfzeile: nur der Titel. Der Spitzenwert stand hier ebenfalls und lag
        # darueber — beide begannen auf derselben Hoehe, und der Spitzensatz ist
        # breit genug, um links in den Titel zu laufen (gemeldet 05.08.2026).
        # Er steht jetzt unten, wo eine ganze Zeile frei ist.
        title_surf = self.label_font.render(tr("Leistung (kW)"), True, (0, 230, 255))
        screen.blit(title_surf, (gx + 16, gy + 10))

        # Dyno chart area. Die linke Spalte ist breiter als frueher: die
        # Achsenzahlen standen bei 1237 und die Zeichenflaeche begann bei 1275,
        # dreistellige Werte ragten also hinein.
        cx = gx + 72
        cy = gy + 48
        cw = gw - 102
        ch = gh - 122
        pygame.draw.rect(screen, (22, 26, 38), (cx, cy, cw, ch))

        # Get the power curve points
        idle = config.idle_rpm
        red = config.redline_rpm
        
        pts = []
        if config.torque_curve:
            sorted_pts = sorted(config.torque_curve)
            pts = [(rpm, rpm * nm / 9549.3) for rpm, nm in sorted_pts]
        else:
            for i in range(21):
                rpm = idle + (red - idle) * i / 20.0
                if len(config.gear_ratios or []) == 1:  # electric
                    flat = idle + (red - idle) * 0.4
                    factor = 1.0 if rpm < flat else max(0.0, 1.0 - 0.65 * ((rpm - flat) / max(1.0, red - flat)))
                else:
                    peak = idle + (red - idle) * 0.75
                    band = red - idle
                    factor = max(0.45, min(1.0, 1.0 - ((rpm - peak) / (band * 0.7)) ** 2))
                ps = factor * (config.engine_power * 0.01)
                kw = ps / 1.35962
                pts.append((rpm, kw))

        if not pts:
            return

        kw_max = max(p[1] for p in pts) if pts else 1.0
        kw_axis = max(50.0, math.ceil(kw_max / 50.0) * 50.0)

        # Grid lines and Y axis. Rechtsbuendig an der Achse statt an einer festen
        # Spalte — sonst haengt die Ausrichtung an der Stellenzahl.
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            yy = cy + ch - ch * frac
            pygame.draw.line(screen, (40, 44, 60), (cx, yy), (cx + cw, yy), 1)
            lbl = self.hint_font.render(f"{frac*kw_axis:.0f}", True, (150, 150, 160))
            screen.blit(lbl, lbl.get_rect(midright=(cx - 8, yy)))
        # Die Einheit stand als eigene Marke ueber der Achse und lag damit im
        # Titel. Sie ist dort ohnehin doppelt: die Ueberschrift heisst
        # „Leistung (kW)".

        # X axis (RPM)
        pygame.draw.line(screen, (40, 44, 60), (cx, cy + ch), (cx + cw, cy + ch), 1)
        beschriftet = []
        for frac in (0.0, 0.25, 0.5, 0.75):
            xx = cx + cw * frac
            rpm_val = idle + (red - idle) * frac
            lbl = self.hint_font.render(f"{rpm_val:.0f}", True, (150, 150, 160))
            if frac == 0.0:
                # Linksbuendig statt zentriert: mittig auf der Achse stiess die
                # erste Zahl mit der Null der Leistungsachse zusammen — die
                # beiden teilen sich die Ecke.
                rect = lbl.get_rect(topleft=(cx, cy + ch + 6))
            else:
                rect = lbl.get_rect(midtop=(xx, cy + ch + 6))
            beschriftet.append(rect)
            screen.blit(lbl, rect)
        einheit = self.hint_font.render(tr("U/min"), True, (255, 120, 0))
        einheit_rect = einheit.get_rect(midtop=(cx + cw, cy + ch + 6))
        einheit_rect.right = min(einheit_rect.right, gx + gw - 10)
        # Nur zeichnen, wenn sie nicht auf der letzten Zahl sitzt.
        if not any(r.colliderect(einheit_rect) for r in beschriftet):
            screen.blit(einheit, einheit_rect)

        # Plot curve
        def _rpm_x(rpm):
            return cx + cw * (max(0.0, min(1.0, (rpm - idle) / (red - idle))) if red > idle else 0.0)

        line_pts = [(_rpm_x(r), cy + ch - ch * min(1.0, kw / kw_axis)) for r, kw in pts]
        if len(line_pts) >= 2:
            pygame.draw.lines(screen, (255, 120, 0), False, line_pts, 2)

        # Max Power Peak marker
        max_idx = max(range(len(pts)), key=lambda i: pts[i][1])
        peak_rpm, peak_kw = pts[max_idx]
        px = _rpm_x(peak_rpm)
        py = cy + ch - ch * min(1.0, peak_kw / kw_axis)
        pygame.draw.circle(screen, (255, 200, 60), (int(px), int(py)), 5)
        
        # Der Spitzenwert bekommt die unterste Zeile der Tafel fuer sich. Vorher
        # stand er neben dem Titel und lief in ihn hinein.
        peak_text = tr("Spitze: {kw} kW ({ps} PS) bei {rpm} U/min").format(
            kw=f"{peak_kw:.1f}", ps=f"{peak_kw*1.35962:.0f}", rpm=f"{peak_rpm:.0f}")
        from src.ui import theme as _th
        _th.text_fit(screen, peak_text, _th.HINT, (255, 200, 60),
                     pygame.Rect(gx + 16, gy + gh - 30, gw - 32, 24))
