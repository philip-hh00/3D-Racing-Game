"""Game manager – orchestrates Pygame initialization, state changes, and the main loop."""
from __future__ import annotations

import sys
import pygame

from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT, TARGET_FPS
from src.core.state_machine import StateMachine


class GameManager:
    """Manages the main game loop, display creation, and state updates."""

    def __init__(self, debug: bool = False) -> None:
        """Initialize pygame core and display only – all heavy work happens
        inside LoadingState so the window is visible immediately."""
        import os
        os.environ["SDL_RENDER_SCALE_QUALITY"] = "linear"
        # pygame.init() brings the mixer up too — at 44.1 kHz unless told
        # otherwise. Every effect file is 48 kHz, so register that first.
        from src.core import sfx as _sfx
        _sfx.mixer_vorbereiten()
        pygame.init()
        pygame.font.init()
        # Note: channel count and a fallback re-init happen in LoadingState.

        from src.core import display
        from src.core import profile as _profile, i18n
        # Apply saved language before any UI is built.
        i18n.set_language(_profile.current().language)
        # Apply saved video settings before the first frame; profile is loaded lazily.
        # display.apply() setzt Titel und Fenstersymbol selbst
        # (display.set_window_icon aus data/icon.png) — eine Stelle, und sie
        # muss ohnehin nach jedem Aufloesungswechsel neu greifen. Der fruehere
        # eigene Ladeversuch hier las data/icon.ico, das pygame nicht lesen kann
        # (Fund 08.08.2026).
        self.screen = display.apply()
        self.clock = pygame.time.Clock()
        self.state_machine = StateMachine()
        self.running = True
        self.debug = debug

        # Placeholders – will be set after LoadingState completes _register_states().
        self.menu_state = None
        self.car_select_state = None
        self.track_select_state = None
        self.race_state = None
        self.dev_state = None
        self.vehicle_lab_state = None
        self.editor_state = None
        self.welcome_state = None

        # Register and immediately enter the loading state.
        from src.states.loading_state import LoadingState
        self._loading_state = LoadingState(self.state_machine, self)
        self.state_machine.register("loading", self._loading_state)

    def _register_states(self) -> None:
        """Instantiate and register all game states in the state machine.

        Called from LoadingState (step 4) so it happens while the splash is
        still on screen, preventing any first-frame lag in the main menu.
        """
        from src.states.menu_shell_state import MenuShellState
        from src.states.race_state import RaceState
        from src.states.car_select_state import CarSelectState
        from src.states.track_select_state import TrackSelectState
        from src.states.dev_state import DevState
        from src.states.vehicle_lab_state import VehicleLabState
        from src.states.editor_state import EditorState
        from src.states.welcome_state import WelcomeState

        self.menu_state          = MenuShellState(self.state_machine)
        self.car_select_state    = CarSelectState(self.state_machine)
        self.track_select_state  = TrackSelectState(self.state_machine)
        self.race_state          = RaceState(self.state_machine)
        self.dev_state           = DevState(self.state_machine)
        self.vehicle_lab_state   = VehicleLabState(self.state_machine)
        self.editor_state        = EditorState(self.state_machine)
        self.welcome_state       = WelcomeState(self.state_machine)

        self.state_machine.register("menu",         self.menu_state)
        self.state_machine.register("welcome",      self.welcome_state)
        self.state_machine.register("car_select",   self.car_select_state)
        self.state_machine.register("track_select", self.track_select_state)
        self.state_machine.register("race",         self.race_state)
        self.state_machine.register("dev",          self.dev_state)
        self.state_machine.register("vehicle_lab",  self.vehicle_lab_state)
        self.state_machine.register("editor",       self.editor_state)

    #: Obergrenze im Menü. Dort bringt eine höhere Bildrate nichts: das
    #: Hintergrundvideo läuft mit 30 Bildern, die Tafeln stehen still, und
    #: Mauszeiger-Hervorhebungen sieht man bei 60 genauso wie bei 3000.
    #:
    #: Am 04.08.2026 als 144 eingeführt und nur bei „Unbegrenzt" angewendet. Am
    #: 05.08.2026 auf Wunsch auf 60 gesenkt **und** zur echten Obergrenze
    #: gemacht: gemeldet wurden 40–50 % CPU auch bei eingestellten 30 Bildern,
    #: und das kann eine Grenze, die nur „Unbegrenzt" abfängt, nicht erklären.
    MENUE_GRENZE = 60

    def _bildgrenze(self) -> int:
        """Bildrate-Obergrenze für diesen Durchlauf (0 = unbegrenzt).

        Der Profilwert gilt, sobald die Zustände stehen — vorher, im
        Ladebildschirm, sind es ``TARGET_FPS``.

        **Ausnahme Menü**: dort deckelt ``MENUE_GRENZE``, und zwar nach oben.
        Eine eingestellte *kleinere* Zahl bleibt kleiner — wer 30 wählt, bekommt
        30 und nicht 60. Im Rennen gilt die Einstellung unverändert, auch
        „Unbegrenzt": dort ist eine höhere Bildrate ein echter Vorteil, und die
        Physik rechnet ohnehin mit dem gemessenen Zeitschritt.
        """
        if self.menu_state is None:
            return TARGET_FPS
        from src.core import profile as _profile
        grenze = int(getattr(_profile.current(), "fps_limit", TARGET_FPS) or 0)
        im_menue = self.state_machine.current is self.menu_state
        if not im_menue:
            return grenze
        if grenze == 0:
            return self.MENUE_GRENZE
        return min(grenze, self.MENUE_GRENZE)

    def run(self) -> None:
        """Run the main game loop."""
        # Start with the loading state – it calls _register_states() and then
        # transitions to "welcome" or "menu" on its own.
        self.state_machine.transition("loading")

        try:
            while self.running:
                raw_dt = self.clock.tick(self._bildgrenze()) / 1000.0
                dt = min(raw_dt, 0.1)

                events = pygame.event.get()
                from src.core import display
                for event in events:
                    if event.type == pygame.QUIT:
                        self.running = False

                # Handle native window-manager events (maximize/resize) before
                # anything else touches this frame's events: a mode switch
                # rebuilds the display, so any remaining events still carry
                # mouse coordinates for the old window size and must not be
                # used for that.
                for event in events:
                    if display.handle_window_event(event):
                        break

                # Remap mouse coordinates from window-space to virtual 1920x1080 space.
                events = display.remap_mouse_events(events)

                # Normalize numpad Enter to regular Enter so every menu/dialog
                # that checks K_RETURN also accepts the keypad key.
                for i, e in enumerate(events):
                    if e.type in (pygame.KEYDOWN, pygame.KEYUP) and e.key == pygame.K_KP_ENTER:
                        attrs = dict(e.__dict__)
                        attrs["key"] = pygame.K_RETURN
                        events[i] = pygame.event.Event(e.type, attrs)

                # Controller hot-plug + translate gamepad input into menu key events.
                # Import here (not top-level) so gamepad.init() runs during loading.
                from src.core import gamepad
                events = gamepad.normalize_button_events(events)
                gamepad.process_system(events)
                gamepad.observe(events)
                if not getattr(self.state_machine.current, "raw_gamepad", False):
                    # Entweder rohe Pad-Ereignisse oder uebersetzte, nie beide —
                    # siehe gamepad.menue_eingaben().
                    events = gamepad.menue_eingaben(events)

                self.state_machine.handle_events(events)

                # Check if current state requests exit
                if self.menu_state and self.menu_state.quit_requested:
                    self.running = False

                if self.race_state and hasattr(self.race_state, "quit_requested") \
                        and self.race_state.quit_requested:
                    self.state_machine.transition("track_select")
                    self.race_state.quit_requested = False

                from src.core import input_mode
                input_mode.update(dt)
                self.state_machine.update(dt)

                # Ein Bild: erst die Puffer leeren, dann zeichnet der
                # Zustand die Welt in OpenGL und HUD, Menues und Minimap auf
                # die virtuelle Flaeche. bild_abschliessen legt sie als Textur
                # darueber und zeigt das Bild.
                display.bild_beginnen()
                virt = display.virtual_surface()
                self.state_machine.render(virt)
                gamepad.draw_notifications(virt, dt)
                display.bild_abschliessen()

        except Exception:
            # Ensure current state gets a chance to clean up before crash handler takes over
            try:
                current = self.state_machine.current
                if current and hasattr(current, "exit"):
                    current.exit()
            except Exception:
                pass
            raise
        finally:
            self.quit()

    def quit(self) -> None:
        """Shut pygame down. Idempotent: safe to call more than once, and does
        NOT call sys.exit() so a propagating exception keeps its traceback."""
        if getattr(self, "_quit_done", False):
            return
        self._quit_done = True
        # Erst den Audiofaden, dann pygame: der Faden blendet aus und schliesst
        # das Geraet. Bliebe er offen, haenge ein nicht angehaltener Strom am
        # beendeten Prozess — unter Windows ein haengendes Fenster beim Beenden.
        try:
            from src.core import tonausgabe
            tonausgabe.beenden()
        except Exception:
            pass
        pygame.quit()
