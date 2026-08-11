"""Loading state – runs all heavy initialization steps while showing a
progress bar, so the main menu starts lag-free and the controller
startup guard expires during the visible loading phase.

Steps executed (one per frame):
  1. pygame.mixer.init()           – audio engine
  2. VehicleFactory.load_all_configs – JSON vehicle data
  3. gamepad.init()                 – controller scan (+ 800 ms guard set)
  4. Register all game states       – fonts, surfaces, etc.
  5. Transition to menu / welcome   – hand off to normal flow
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from src.states.base_state import BaseState
from src.core.settings import SCREEN_WIDTH, SCREEN_HEIGHT
from src.core.i18n import tr

if TYPE_CHECKING:
    from src.core.state_machine import StateMachine


class LoadingState(BaseState):
    """Splash screen that performs initialization one step per frame."""

    # Each step is (label, callable).  Callables are set up in enter() so
    # that they can safely reference self._sm (the parent GameManager).
    _STEPS: list[tuple[str, str]] = [
        ("Audio-Engine",        "_step_audio"),
        ("Fahrzeug-Daten",      "_step_vehicles"),
        ("Controller",          "_step_gamepad"),
        ("Spielzustände",       "_step_states"),
        ("Bereit",              "_step_finish"),
    ]

    def __init__(self, state_machine: StateMachine, game_manager) -> None:
        super().__init__(state_machine)
        self._gm = game_manager          # reference to GameManager
        self._step_idx: int = 0
        self._t: float = 0.0            # for animation
        self._dot_t: float = 0.0        # dot animation timer
        self._dots: str = ""
        self._label: str = "Initialisierung…"
        self._done: bool = False
        # Skip one frame before starting so we render at least once first.
        self._first_frame: bool = True

    # ------------------------------------------------------------------
    # State interface
    # ------------------------------------------------------------------

    def enter(self, **kwargs) -> None:
        self._step_idx = 0
        self._done = False
        self._first_frame = True
        self._label = "Initialisierung…"

    def handle_events(self, events: list[pygame.event.Event]) -> None:
        pass  # No user input during loading

    def update(self, dt: float) -> None:
        self._t += dt
        self._dot_t += dt
        if self._dot_t >= 0.4:
            self._dot_t = 0.0
            self._dots = self._dots + "." if len(self._dots) < 3 else ""

        if self._done:
            return

        # Skip the very first update so the splash renders before work begins.
        if self._first_frame:
            self._first_frame = False
            return

        # Execute one step per frame to keep the display responsive.
        if self._step_idx < len(self._STEPS):
            label, method_name = self._STEPS[self._step_idx]
            self._label = label
            getattr(self, method_name)()
            self._step_idx += 1

    def render(self, screen: pygame.Surface) -> None:
        self._draw(screen)

    # ------------------------------------------------------------------
    # Init steps
    # ------------------------------------------------------------------

    def _step_audio(self) -> None:
        # Ueber sfx.mixer_starten, damit der Mixer mit 48 kHz laeuft: alle
        # Effektdateien liegen so vor, und ein Mixer mit 44,1 kHz wuerde jeden
        # davon beim Laden umrechnen - samt der Motorschleifen, deren Laenge
        # dabei nicht mehr zur Drehzahl passt.
        try:
            from src.core import sfx
            sfx.mixer_starten()
        except Exception as e:
            print(f"[Loading] Audio init failed: {e}")

        # Der Audiofaden fuer den Motorklang (06.08.2026). Er laeuft neben dem
        # Mixer: pygame behaelt Menueklaenge, Reifen und Aufpralle, der
        # Motorklang bekommt seinen eigenen Weg mit Ringpuffer. Nur der brauchte
        # ihn — er ist der einzige Klang, der Block fuer Block erzeugt wird.
        #
        # Schlaegt es fehl (kein PortAudio, kein Ausgabegeraet), bleibt es beim
        # alten Weg ueber pygame. Deshalb hier kein Abbruch, nur eine Notiz.
        try:
            from src.core import tonausgabe
            if not tonausgabe.starten():
                print(f"[Loading] Audiofaden nicht verfuegbar, "
                      f"Rueckfall auf pygame: {tonausgabe.grund()}")
        except Exception as e:
            print(f"[Loading] Audiofaden fehlgeschlagen: {e}")

    def _step_vehicles(self) -> None:
        from src.entities.vehicle_factory import VehicleFactory
        VehicleFactory.load_all_configs("data/vehicles")

    def _step_gamepad(self) -> None:
        from src.core import gamepad
        gamepad.init()

    def _step_states(self) -> None:
        self._gm._register_states()

    def _step_finish(self) -> None:
        """Transition to menu or welcome screen once all steps are done."""
        from src.core import profile
        self._done = True
        # Der gespeicherte Name wird gegen die **heutige** Sperrliste gehalten,
        # nicht nur gegen die von damals: eine neue Fassung kann Woerter
        # nachtragen, die ein Spieler laengst traegt. Er waehlt dann neu und
        # behaelt alles andere — Bestzeiten, Statistik, Freischaltungen
        # (gemeldet und so entschieden am 07.08.2026).
        if profile.current().exists() and not profile.namensneuwahl_noetig():
            self.state_machine.transition("menu")
        else:
            self.state_machine.transition("welcome")

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _draw(self, screen: pygame.Surface) -> None:
        W, H = SCREEN_WIDTH, SCREEN_HEIGHT

        # --- Background gradient ------------------------------------------
        screen.fill((10, 11, 18))
        # Subtle radial glow in the center
        glow = pygame.Surface((600, 600), pygame.SRCALPHA)
        for r in range(280, 0, -8):
            alpha = int(18 * (1 - r / 280))
            pygame.draw.circle(glow, (255, 180, 0, alpha), (300, 300), r)
        screen.blit(glow, (W // 2 - 300, H // 2 - 300))

        # --- Logo / title --------------------------------------------------
        f_title = pygame.font.Font(None, 96)
        f_sub   = pygame.font.Font(None, 38)
        f_label = pygame.font.Font(None, 30)

        title_surf = f_title.render("2D-Racing-Game", True, (255, 180, 0))
        screen.blit(title_surf, title_surf.get_rect(center=(W // 2, H // 2 - 130)))

        sub_surf = f_sub.render(tr("Wird geladen"), True, (180, 183, 195))
        screen.blit(sub_surf, sub_surf.get_rect(center=(W // 2, H // 2 - 50)))

        # --- Progress bar -------------------------------------------------
        total = len(self._STEPS)
        progress = min(self._step_idx / total, 1.0)

        bar_w = 520
        bar_h = 8
        bar_x = W // 2 - bar_w // 2
        bar_y = H // 2 + 20

        # Track
        pygame.draw.rect(screen, (30, 33, 44), (bar_x, bar_y, bar_w, bar_h), border_radius=4)
        # Fill
        fill_w = int(bar_w * progress)
        if fill_w > 0:
            # Gradient: draw thin rects with color shift
            for i in range(fill_w):
                t = i / max(1, bar_w)
                r = int(220 + 35 * t)
                g = int(140 + 40 * t)
                b = int(0)
                pygame.draw.rect(screen, (r, g, b), (bar_x + i, bar_y, 1, bar_h))

        # Glow at the leading edge
        if 0 < fill_w < bar_w:
            glow_x = bar_x + fill_w
            for gw in range(12, 0, -2):
                ga = int(80 * gw / 12)
                pygame.draw.rect(screen, (255, 210, 80, ga),
                                 (glow_x - gw, bar_y - 2, gw * 2, bar_h + 4),
                                 border_radius=2)

        # --- Step label ---------------------------------------------------
        label_text = f"{tr(self._label)}{self._dots}"
        label_surf = f_label.render(label_text, True, (150, 154, 168))
        screen.blit(label_surf, label_surf.get_rect(center=(W // 2, bar_y + 32)))

        # --- Version hint -------------------------------------------------
        from src.core.version import version_string
        ver_surf = f_label.render(version_string(), True, (60, 64, 78))
        screen.blit(ver_surf, ver_surf.get_rect(topright=(W - 30, H - 36)))
